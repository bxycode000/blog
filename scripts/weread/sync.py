#!/usr/bin/env python3
"""微信读书 → content/page/reading/books.json

用法（仓库根目录执行）:
    py scripts/weread/sync.py               # 增量同步
    py scripts/weread/sync.py --full        # 忽略缓存，全量重拉
    py scripts/weread/sync.py --include-secret  # 包含私密书籍（默认过滤）
    py scripts/weread/sync.py --dry-run     # 只统计，不写文件

凭据只从环境变量 WEREAD_API_KEY 读取。
"""

import argparse
import concurrent.futures as cf
import datetime
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build
import cache
from client import MAX_WORKERS, WeReadError, api

REPO = Path(__file__).resolve().parent.parent.parent
OUT = REPO / "content" / "page" / "reading" / "books.json"
MANUAL = REPO / "content" / "page" / "reading" / "reviews.manual.json"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def fetch_progress(books: list[dict], cached: dict, full: bool) -> tuple[dict, int]:
    """返回 (progress_map, 失败数)。只对变化的书发请求；失败时回退旧缓存。"""
    result = {}
    todo = []
    for b in books:
        bid = b.get("bookId", "")
        entry = cached.get(bid)
        stamp = int(b.get("readUpdateTime") or 0)
        if (not full and entry
                and entry.get("stamp") == stamp
                and cache.is_fresh(entry, cache.PROGRESS_TTL)):
            result[bid] = entry
        else:
            todo.append(b)

    log(f"逐书进度：命中缓存 {len(result)} 本，需请求 {len(todo)} 本")
    errors = 0

    def one(b):
        try:
            data = api("/book/getprogress", bookId=b["bookId"])
            return b["bookId"], {
                "stamp": int(b.get("readUpdateTime") or 0),
                "data": data.get("book") or {},
                "fetchedAt": int(time.time()),
            }
        except WeReadError as exc:
            return b["bookId"], {"error": str(exc)}

    if todo:
        with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for bid, entry in pool.map(one, todo):
                if entry.get("error"):
                    errors += 1
                    if errors <= 5:
                        log(f"  跳过 {bid}：{entry['error']}")
                    # 失败时沿用旧缓存，避免把「在读」降级成「想读」
                    if bid in cached:
                        result[bid] = cached[bid]
                else:
                    result[bid] = entry

    return result, errors


def fetch_notebooks() -> dict:
    """有笔记的书索引，按 bookId 建表。"""
    out = {}
    last_sort = None
    for _ in range(20):
        params = {"count": 100}
        if last_sort:
            params["lastSort"] = last_sort
        data = api("/user/notebooks", **params)
        for item in data.get("books") or []:
            out[item.get("bookId", "")] = item
        if not data.get("hasMore"):
            break
        last_sort = (data.get("books") or [{}])[-1].get("sort")
    return out


def fetch_reviews(notebooks: dict, cached: dict, full: bool) -> dict:
    """只拉有个人点评的书。"""
    out = {}
    todo = []
    for bid, nb in notebooks.items():
        if int(nb.get("reviewCount") or 0) <= 0:
            continue
        entry = cached.get(bid)
        if not full and entry and entry.get("sort") == nb.get("sort") and cache.is_fresh(entry, cache.REVIEWS_TTL):
            out[bid] = entry.get("reviews") or []
        else:
            todo.append((bid, nb))

    log(f"个人想法：命中缓存 {len(out)} 本，需请求 {len(todo)} 本")

    def one(item):
        bid, nb = item
        try:
            reviews = []
            synckey = 0
            for _ in range(10):
                params = {"bookid": bid, "count": 100}
                if synckey:
                    params["synckey"] = synckey
                data = api("/review/list/mine", **params)
                for entry in data.get("reviews") or []:
                    reviews.append(entry.get("review") or {})
                if not data.get("hasMore"):
                    break
                synckey = data.get("synckey") or 0
                if not synckey:
                    break
            return bid, {"sort": nb.get("sort"), "reviews": reviews, "fetchedAt": int(time.time())}
        except WeReadError as exc:
            log(f"  想法拉取失败 {bid}：{exc}")
            return bid, None

    if todo:
        with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for bid, entry in pool.map(one, todo):
                if entry:
                    out[bid] = entry["reviews"]
                    cached[bid] = entry

    return out


def read_manual() -> dict:
    if not MANUAL.exists():
        return {}
    try:
        data = json.loads(MANUAL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"手工短评解析失败，已忽略：{exc}")
        return {}
    # 以 _ 开头的键是说明性字段，不当作书评条目
    return {k: v for k, v in data.items() if not k.startswith("_")}


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="忽略缓存")
    parser.add_argument("--include-secret", action="store_true", help="包含私密书籍")
    parser.add_argument("--dry-run", action="store_true", help="不写文件")
    args = parser.parse_args()

    started = time.time()

    try:
        shelf = api("/shelf/sync")
    except WeReadError as exc:
        log(f"同步失败：{exc}")
        log("保留现有 books.json，构建可继续。")
        return 3

    all_books = shelf.get("books") or []
    log(f"书架 {len(all_books)} 本，专辑 {len(shelf.get('albums') or [])} 个")

    progress_cache = cache.load("progress")
    reviews_cache = cache.load("reviews")

    progress_map, progress_errors = fetch_progress(all_books, progress_cache, args.full)

    try:
        notebooks = fetch_notebooks()
    except WeReadError as exc:
        log(f"笔记索引拉取失败，笔记数量将为空：{exc}")
        notebooks = {}

    reviews_map = fetch_reviews(notebooks, reviews_cache, args.full)
    manual = read_manual()

    records = build.build_records(
        shelf, progress_map, notebooks, reviews_map, manual,
        include_secret=args.include_secret,
    )

    expected = len(all_books) if args.include_secret else sum(1 for b in all_books if b.get("secret") != 1)
    build.validate(records, expected_total=expected)

    counts = {"want": 0, "reading": 0, "finished": 0}
    for r in records:
        counts[r["status"]] += 1

    stats = {}
    try:
        detail = api("/readdata/detail", mode="overall", baseTime=0)
        stats = {
            "readDays": int(detail.get("readDays") or 0),
            "totalReadTime": int(detail.get("totalReadTime") or 0),
            "totalReadTimeText": build.fmt_duration(detail.get("totalReadTime")),
        }
    except WeReadError as exc:
        log(f"阅读统计拉取失败，跳过统计卡片：{exc}")

    payload = build.summarize(records, stats)
    payload["generatedAt"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    payload["generatedTs"] = int(time.time())

    log("")
    log(f"条目 {len(records)} = 想读 {counts['want']} + 在读 {counts['reading']} + 已读 {counts['finished']}  ✓")
    log(f"进度请求失败 {progress_errors} 本；手工短评 {len(manual)} 条；耗时 {time.time() - started:.1f}s")

    if args.dry_run:
        log("dry-run：未写入文件")
        return 0

    atomic_write(OUT, payload)
    # 合并旧缓存再落盘：只覆盖本轮真正拿到新数据的条目
    for bid, entry in progress_map.items():
        progress_cache[bid] = entry
    cache.save("progress", progress_cache)
    cache.save("reviews", reviews_cache)
    log(f"已写入 {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
