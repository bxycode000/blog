#!/usr/bin/env python3
"""回溯书架外的历史阅读记录 → data/history.json

原理：/readdata/detail?mode=weekly 会返回当周读得最多的前 10 本书（含 bookId），
从注册日按周扫描即可收集到大量已移出书架的书；再合并笔记库、补全书目与进度。

用法（仓库根目录执行）:
    py scripts/weread/history.py             # 增量：回扫最近 8 周 + 补齐缓存
    py scripts/weread/history.py --full      # 从注册日全量扫描
    py scripts/weread/history.py --dry-run   # 只统计，不写 data/history.json
    py scripts/weread/history.py --refresh   # 强制重拉全部书目/进度
    py scripts/weread/history.py --limit 20  # 只处理前 N 本（调试用）

凭据只从环境变量 WEREAD_API_KEY 读取。
"""

import argparse
import concurrent.futures as cf
import datetime
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build
import cache
from client import MAX_WORKERS, WeReadError, api

REPO = Path(__file__).resolve().parent.parent.parent
OUT = REPO / "data" / "history.json"

INFO_TTL = 30 * 24 * 3600
PROGRESS_TTL = 7 * 24 * 3600
CACHE_NAME = "history"

_PATH_TITLE = re.compile(r"^[A-Za-z]:[\\/]|\\\\wwwroot\\\\", re.I)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def week_points(start: datetime.datetime, end: datetime.datetime):
    cur = start
    while cur <= end:
        yield cur
        cur += datetime.timedelta(days=7)


def load_cache() -> dict:
    data = cache.load(CACHE_NAME)
    if not data or "books" not in data:
        data = {"version": 1, "lastWeekTs": 0, "books": {}}
    return data


def _ts_from_date(value) -> int:
    if not value:
        return 0
    try:
        return int(datetime.datetime.strptime(str(value), "%Y-%m-%d").timestamp())
    except ValueError:
        return 0


def bootstrap_from_output(cached: dict) -> None:
    """CI 没有本地缓存时，用已发布的 data/history.json 当基线，避免每天全量重扫。"""
    if cached.get("books") or not OUT.exists():
        return
    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    now_ts = int(time.time())
    for rec in data.get("books") or []:
        bid = rec.get("id")
        if not bid:
            continue
        cached["books"][bid] = {
            "title": rec.get("title") or "",
            "firstSeen": 0,
            "lastSeen": _ts_from_date(rec.get("lastReadDate")),
            "readSeconds": int(rec.get("readingTime") or 0),
            "info": {
                "bookId": bid,
                "title": rec.get("title"),
                "author": rec.get("author"),
                "cover": rec.get("cover"),
                "category": rec.get("category"),
                "readerLink": rec.get("link"),
                "deepLink": rec.get("link"),
            },
            "infoAt": now_ts,
            "progress": {
                "progress": rec.get("progress") or 0,
                "updateTime": _ts_from_date(rec.get("lastReadDate")),
                "finishTime": _ts_from_date(rec.get("finishDate")),
            },
            "progressAt": now_ts,
        }
        notes = rec.get("notes") or {}
        if notes:
            cached["books"][bid]["notebook"] = {
                "markedStatus": 1 if rec.get("status") == "finished" else 0,
                "reviewCount": notes.get("thoughts") or 0,
                "noteCount": notes.get("highlights") or 0,
                "bookmarkCount": notes.get("bookmarks") or 0,
            }
    cached["lastWeekTs"] = int(data.get("lastWeekTs") or 0)
    log(f"已从 data/history.json 载入基线 {len(cached['books'])} 本")


def sweep_weeks(cached: dict, start: datetime.datetime, end: datetime.datetime) -> tuple[int, int]:
    """按周扫描 readLongest，写入缓存。返回 (扫描周数, 新增书数)。"""
    books = cached["books"]
    new_count = 0
    weeks = 0
    last_ts = 0
    for point in week_points(start, end):
        ts = int(point.timestamp())
        weeks += 1
        last_ts = max(last_ts, ts)
        try:
            data = api("/readdata/detail", mode="weekly", baseTime=ts)
        except WeReadError as exc:
            log(f"  跳过 {point:%Y-%m-%d}：{exc}")
            continue
        for item in data.get("readLongest") or []:
            b = item.get("book") or {}
            bid = b.get("bookId")
            if not bid:
                continue
            entry = books.setdefault(bid, {
                "title": build.clean(b.get("title")),
                "firstSeen": ts,
                "lastSeen": ts,
                "readSeconds": 0,
            })
            entry["title"] = entry.get("title") or build.clean(b.get("title"))
            entry["firstSeen"] = min(entry.get("firstSeen") or ts, ts)
            entry["lastSeen"] = max(entry.get("lastSeen") or ts, ts)
            entry["readSeconds"] = max(entry.get("readSeconds") or 0, int(item.get("readTime") or 0))
            if not entry.get("info"):
                new_count += 1
        if weeks % 20 == 0:
            cached["lastWeekTs"] = last_ts
            cache.save(CACHE_NAME, cached)
            log(f"  已扫描 {weeks} 周，累计 {len(books)} 本")
    cached["lastWeekTs"] = last_ts
    cache.save(CACHE_NAME, cached)
    return weeks, new_count


def merge_notebooks(cached: dict) -> int:
    """合并笔记库：离架书也可能有笔记与读完标记。"""
    books = cached["books"]
    added = 0
    last = None
    total = 0
    while True:
        params = {"count": 100}
        if last:
            params["lastSort"] = last
        data = api("/user/notebooks", **params)
        items = data.get("books") or []
        total += len(items)
        for item in items:
            bid = item.get("bookId")
            if not bid:
                continue
            b = item.get("book") or {}
            entry = books.setdefault(bid, {
                "title": build.clean(b.get("title")),
                "firstSeen": 0,
                "lastSeen": 0,
                "readSeconds": 0,
            })
            if not entry.get("title"):
                entry["title"] = build.clean(b.get("title"))
            entry["notebook"] = {
                "markedStatus": item.get("markedStatus"),
                "readingProgress": item.get("readingProgress"),
                "reviewCount": item.get("reviewCount") or 0,
                "noteCount": item.get("noteCount") or 0,
                "bookmarkCount": item.get("bookmarkCount") or 0,
            }
            if not entry.get("info"):
                added += 1
        if not data.get("hasMore") or not items:
            break
        last = items[-1].get("sort")
    log(f"笔记库：{total} 本，补充候选 {added} 本")
    return total


def ensure_details(cached: dict, targets: list[str], refresh: bool = False) -> int:
    """补齐 info / progress。返回失败数。"""
    books = cached["books"]
    todo = []
    now = int(time.time())
    for bid in targets:
        entry = books.get(bid) or {}
        need_info = refresh or not entry.get("info") or (now - int(entry.get("infoAt") or 0)) > INFO_TTL
        need_progress = refresh or not entry.get("progress") or (now - int(entry.get("progressAt") or 0)) > PROGRESS_TTL
        if need_info or need_progress:
            todo.append((bid, need_info, need_progress))

    log(f"书目/进度：需请求 {len(todo)} 本（目标 {len(targets)} 本）")
    if not todo:
        return 0

    errors = 0

    def one(task):
        bid, need_info, need_progress = task
        entry = books.get(bid) or {}
        try:
            if need_info:
                info = api("/book/info", bookId=bid)
                entry["info"] = {k: info.get(k) for k in (
                    "bookId", "title", "author", "translator", "cover", "category",
                    "publisher", "publishTime", "isbn", "wordCount", "newRating",
                    "readerLink", "deepLink", "intro",
                )}
                entry["infoAt"] = int(time.time())
            if need_progress:
                data = api("/book/getprogress", bookId=bid)
                entry["progress"] = data.get("book") or {}
                entry["progressAt"] = int(time.time())
            books[bid] = entry
            return bid, None
        except WeReadError as exc:
            return bid, str(exc)

    done = 0
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for bid, err in pool.map(one, todo):
            done += 1
            if err:
                errors += 1
                if errors <= 5:
                    log(f"  跳过 {bid}：{err}")
            if done % 100 == 0:
                cache.save(CACHE_NAME, cached)
                log(f"  已补全 {done}/{len(todo)}")

    cache.save(CACHE_NAME, cached)
    return errors


def to_records(cached: dict, shelf_ids: set[str]) -> list[dict]:
    records = []
    skipped_path = 0
    for bid, entry in cached["books"].items():
        if bid in shelf_ids:
            continue
        info = entry.get("info") or {}
        pr = entry.get("progress") or {}
        nb = entry.get("notebook") or {}
        nb_book = nb.get("book") or {}

        title = build.clean(info.get("title") or entry.get("title") or nb_book.get("title"))
        if not title:
            continue
        if _PATH_TITLE.search(title):
            skipped_path += 1
            continue

        p = int(pr.get("progress") or nb.get("readingProgress") or 0)
        finished = (nb.get("markedStatus") == 1 or p >= 100 or bool(pr.get("finishTime")))
        status = "finished" if finished else "read"

        # 离架书的 getprogress.updateTime 可能是查询时间，优先用周扫描实际看到该书的周
        last_ts = int(entry.get("lastSeen") or 0) or int(pr.get("updateTime") or 0)
        finish_ts = int(pr.get("finishTime") or 0)

        records.append({
            "id": bid,
            "title": title,
            "author": build.clean(info.get("author") or nb_book.get("author")),
            "cover": build.cover_url(info.get("cover") or nb_book.get("cover")),
            "link": info.get("readerLink") or info.get("deepLink") or "",
            "category": build.clean(info.get("category")),
            "status": status,
            "progress": 100 if finished and p <= 0 else p,
            "readingTime": int(pr.get("recordReadingTime") or entry.get("readSeconds") or 0),
            "lastReadDate": build.fmt_date(last_ts),
            "finishDate": build.fmt_date(finish_ts) if finished else None,
            "notes": {
                "thoughts": int(nb.get("reviewCount") or 0),
                "highlights": int(nb.get("noteCount") or 0),
                "bookmarks": int(nb.get("bookmarkCount") or 0),
            },
            "source": "history",
        })

    # 同书名同作者的去重（保留进度更高的一条），并过滤明显异常的导入条目
    best = {}
    for rec in records:
        key = (rec["title"], rec["author"])
        cur = best.get(key)
        if cur is None or rec["progress"] > cur["progress"] or (
            rec["progress"] == cur["progress"] and (rec["lastReadDate"] or "") > (cur["lastReadDate"] or "")
        ):
            best[key] = rec

    result = list(best.values())
    result.sort(key=lambda r: (r["lastReadDate"] or "", r["title"]), reverse=True)
    if skipped_path:
        log(f"过滤异常条目 {skipped_path} 条（标题为本地路径）")
    log(f"去重：{len(records)} → {len(result)} 本")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="回溯书架外的历史阅读记录")
    parser.add_argument("--full", action="store_true", help="从注册日全量扫描")
    parser.add_argument("--weeks", type=int, default=8, help="增量回扫周数（默认 8）")
    parser.add_argument("--refresh", action="store_true", help="强制重拉书目与进度")
    parser.add_argument("--dry-run", action="store_true", help="不写 data/history.json")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 本（调试）")
    args = parser.parse_args()

    started = time.time()
    shelf = api("/shelf/sync")
    shelf_ids = {b.get("bookId") for b in (shelf.get("books") or [])}
    log(f"书架 {len(shelf_ids)} 本")

    overall = api("/readdata/detail", mode="overall")
    reg_ts = int(overall.get("registTime") or 0)
    now = datetime.datetime.now()
    end = now.replace(hour=12, minute=0, second=0, microsecond=0)

    cached = load_cache()
    bootstrap_from_output(cached)
    if args.full or not cached.get("lastWeekTs") or not cached.get("books"):
        start = datetime.datetime.fromtimestamp(reg_ts) if reg_ts else end - datetime.timedelta(weeks=52 * 6)
        log(f"全量扫描：{start:%Y-%m-%d} → {end:%Y-%m-%d}")
    else:
        start = datetime.datetime.fromtimestamp(cached["lastWeekTs"]) - datetime.timedelta(weeks=args.weeks)
        log(f"增量扫描：{start:%Y-%m-%d} → {end:%Y-%m-%d}")

    weeks, _ = sweep_weeks(cached, start, end)
    log(f"周扫描完成：{weeks} 周，缓存 {len(cached['books'])} 本")

    merge_notebooks(cached)

    targets = [bid for bid in cached["books"] if bid not in shelf_ids]
    if args.limit:
        targets = targets[: args.limit]
    errors = ensure_details(cached, targets, refresh=args.refresh)

    records = to_records(cached, shelf_ids)
    years = sorted({int(r["lastReadDate"][:4]) for r in records if r.get("lastReadDate")}, reverse=True)
    payload = {
        "version": 1,
        "source": "weread-readdata-history",
        "generatedAt": now.astimezone().isoformat(timespec="seconds"),
        "count": len(records),
        "finished": sum(1 for r in records if r["status"] == "finished"),
        "years": years,
        "lastWeekTs": int(cached.get("lastWeekTs") or 0),
        "books": records,
    }

    log(f"结果：{len(records)} 本（已确认读完 {payload['finished']} 本，失败 {errors} 本，耗时 {time.time()-started:.0f}s）")
    if args.dry_run:
        log("dry-run：未写文件")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)
    log(f"已写入 {OUT}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WeReadError as exc:
        log(f"失败：{exc}")
        raise SystemExit(1)
