#!/usr/bin/env python3
"""把接口回包转换成页面消费的 books.json（schema v2）。

这里只做纯转换，不发请求。状态判定与排序口径集中在此，
避免同步脚本和模板各算一套。
"""

import datetime
import re

# 微信读书导出文本常混入零宽字符，会把标题和短评里的标点弄断
_ZW = re.compile(r"[\u200b\u200c\u200d\ufeff\u00ad]")


def clean(text: str) -> str:
    return _ZW.sub("", text or "").strip()


def fmt_date(ts) -> str | None:
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def fmt_duration(seconds: int) -> str:
    minutes = int(seconds or 0) // 60
    if minutes <= 0:
        return ""
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} 小时 {minutes} 分钟"
    if hours:
        return f"{hours} 小时"
    return f"{minutes} 分钟"


def cover_url(url: str, width: int = 144) -> str:
    """缩略图。res.weread.qq.com 是签名重定向，加参数会 401，只能原图。"""
    url = (url or "").strip()
    if not url or "res.weread.qq.com" in url or "imageView2" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}imageView2/2/w/{width}/format/webp"


def classify(shelf_book: dict, progress: dict) -> tuple[str, int]:
    """返回 (status, progress)。三分类互斥且穷尽。"""
    p = int(progress.get("progress") or 0)
    finished = shelf_book.get("finishReading") == 1 or p >= 100
    if finished:
        return "finished", 100
    if p > 0 or int(progress.get("readingTime") or 0) > 0:
        return "reading", p
    return "want", 0


def updated_at(status: str, shelf_book: dict, progress: dict) -> int:
    if status == "finished":
        return int(progress.get("finishTime") or progress.get("updateTime")
                   or shelf_book.get("readUpdateTime") or 0)
    if status == "reading":
        return int(progress.get("updateTime") or shelf_book.get("readUpdateTime") or 0)
    return int(shelf_book.get("updateTime") or shelf_book.get("readUpdateTime") or 0)


def pick_review(book: dict, manual: dict, api_reviews: list) -> tuple[str, str | None]:
    """短评：手工层优先，其次只取没有 chapterName 的整本书评。"""
    for key in (book.get("bookId"), clean(book.get("title"))):
        entry = manual.get(key)
        if entry:
            text = clean(entry.get("text") if isinstance(entry, dict) else entry)
            if text:
                return text, "manual"

    candidates = [
        clean(r.get("content"))
        for r in api_reviews
        if not r.get("chapterName") and clean(r.get("content"))
    ]
    if candidates:
        return candidates[0], "api"
    return "", None


def build_records(shelf: dict, progress_map: dict, notebooks: dict,
                  reviews_map: dict, manual: dict, include_secret: bool = False) -> list[dict]:
    records = []
    for b in shelf.get("books") or []:
        if b.get("secret") == 1 and not include_secret:
            continue

        bid = b.get("bookId", "")
        progress = (progress_map.get(bid) or {}).get("data") or {}
        nb = notebooks.get(bid) or {}

        status, pct = classify(b, progress)

        start_ts = int(progress.get("startReadingTime") or 0)
        start_source = "api" if start_ts > 0 else "unknown"
        start_date = fmt_date(start_ts)

        if not start_date:
            stamps = [int(r.get("createTime") or 0) for r in (reviews_map.get(bid) or [])]
            stamps = [s for s in stamps if s > 0]
            if stamps:
                start_date = fmt_date(min(stamps))
                start_source = "first-note"

        finish_date = None
        if status == "finished":
            finish_date = fmt_date(progress.get("finishTime")) or fmt_date(
                progress.get("updateTime") or b.get("readUpdateTime")
            )

        review, review_source = pick_review(b, manual, reviews_map.get(bid) or [])

        # 想读没有阅读记录，lastReadDate 会让页面出现「最近阅读」的错觉
        last_read = fmt_date(progress.get("updateTime") or b.get("readUpdateTime"))
        if status == "want":
            last_read = None

        records.append({
            "id": bid,
            "title": clean(b.get("title")),
            "author": clean(b.get("author")),
            "cover": cover_url(b.get("cover")),
            "coverOriginal": b.get("cover") or "",
            "link": b.get("readerLink") or b.get("deepLink") or "",
            "detailLink": b.get("deepLink") or "",
            "category": clean(b.get("category")),
            "status": status,
            "progress": pct,
            "readingTime": int(progress.get("readingTime") or 0),
            "readingTimeText": fmt_duration(progress.get("readingTime")),
            "startDate": start_date,
            "startSource": start_source,
            "finishDate": finish_date,
            "lastReadDate": last_read,
            "updatedAt": updated_at(status, b, progress),
            "review": review,
            "reviewSource": review_source,
            "notes": {
                "thoughts": int(nb.get("reviewCount") or 0),
                "highlights": int(nb.get("noteCount") or 0),
                "bookmarks": int(nb.get("bookmarkCount") or 0),
            },
            "secret": b.get("secret") == 1,
        })

    records.sort(key=lambda r: (-r["updatedAt"], r["title"]))
    return records


def summarize(records: list[dict], stats: dict) -> dict:
    counts = {"want": 0, "reading": 0, "finished": 0}
    for r in records:
        counts[r["status"]] += 1
    return {
        "version": 2,
        "source": "weread-agent-api",
        "counts": {**counts, "total": len(records)},
        "stats": stats,
        "books": records,
    }


def validate(records: list[dict], expected_total: int | None = None) -> None:
    statuses = {"want", "reading", "finished"}
    assert all(r["status"] in statuses for r in records), "存在非法 status"
    assert all(r["title"] for r in records), "存在空书名"
    if expected_total is not None:
        assert len(records) == expected_total, f"条目数 {len(records)} != 预期 {expected_total}"
