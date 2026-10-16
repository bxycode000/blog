#!/usr/bin/env python3
"""微信读书快照 HTML -> 博客「阅读」页数据。

用法（在仓库根 D:\\Self-website\\blog\\blog 下）:
    py scripts/weread_sync.py "C:\\Users\\...\\我的阅读记录（已过滤）.html"

输入为 WorkBuddy 等工具导出的阅读记录 HTML 快照，
输出 content/page/reading/books.json（Hugo page bundle 内的数据文件）。
"""

import html as htmlmod
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DEFAULT = REPO / "content" / "page" / "reading" / "books.json"

TAG_RE = re.compile(r"<[^>]+>")


def clean(s):
    """去标签 + 反转义 HTML 实体。"""
    if not s:
        return ""
    return htmlmod.unescape(TAG_RE.sub("", s)).strip()


def parse_record(block):
    attrs = dict(re.findall(r'data-([\w-]+)="([^"]*)"', block))
    m = re.search(r'<figure class="cover"><img src="([^"]+)"', block)
    cover = m.group(1) if m else ""
    m = re.search(r'<h3 class="title"><a href="(https://weread\.qq\.com/web/reader/[^"]+)"', block)
    link = m.group(1) if m else ""
    m = re.search(r'<span class="cat">([^<]*)</span>', block)
    subcat = clean(m.group(1)) if m else ""
    m = re.search(r'最近阅读 <time datetime="([^"]+)"', block)
    last_read = m.group(1) if m else ""
    m = re.search(r'入架/更新 <time datetime="([^"]+)"', block)
    added = m.group(1) if m else ""

    thoughts = []
    for li in re.findall(r'<li class="thought">(.*?)</li>', block, re.S):
        q = re.search(r'<blockquote class="tquote">(.*?)</blockquote>', li, re.S)
        t = re.search(r'<p class="ttext">(.*?)</p>', li, re.S)
        meta = re.search(r'章节：(.*?)\s*·\s*<time datetime="([^"]+)"', li, re.S)
        thoughts.append({
            "quote": clean(q.group(1)) if q else "",
            "text": clean(t.group(1)) if t else "",
            "chapter": clean(meta.group(1)) if meta else "",
            "date": meta.group(2) if meta else "",
        })

    highlights = []
    for li in re.findall(r'<li class="highlight">(.*?)</li>', block, re.S):
        q = re.search(r"<blockquote>(.*?)</blockquote>", li, re.S)
        meta = re.search(r'<p class="hmeta">(.*?)\s*·\s*<time datetime="([^"]+)"', li, re.S)
        highlights.append({
            "text": clean(q.group(1)) if q else "",
            "chapter": clean(meta.group(1)) if meta else "",
            "date": meta.group(2) if meta else "",
        })

    return {
        "title": attrs.get("title", ""),
        "author": attrs.get("author", ""),
        "cover": cover,
        "link": link,
        "category": attrs.get("cat", ""),
        "subcategory": subcat,
        "status": attrs.get("status", "unread"),
        "progress": int(attrs.get("progress", "0") or 0),
        "last_ts": int(attrs.get("last", "0") or 0),
        "added_ts": int(attrs.get("added", "0") or 0),
        "last_read": last_read,
        "added": added,
        "notes_count": int(attrs.get("notes", "0") or 0),
        "thoughts": thoughts,
        "highlights": highlights,
    }


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    doc = src.read_text(encoding="utf-8")

    stats = [
        {"value": v, "label": clean(l)}
        for v, l in re.findall(r'<div class="stat"><b>([^<]*)</b><span>([^<]*)</span></div>', doc)
    ]
    years = [
        {"year": y, "width": int(w), "text": clean(t)}
        for y, w, t in re.findall(
            r'<span class="ylabel">(\d{4})</span><div class="ytrack"><div class="yfill" style="width:(\d+)%"></div></div><span class="yval">([^<]*)</span>',
            doc,
        )
    ]
    top_categories = [
        {"name": clean(n), "width": int(w), "text": clean(t)}
        for n, w, t in re.findall(
            r'<span class="clabel">([^<]*)</span><div class="ctrack"><div class="cfill" style="width:(\d+)%"></div></div><span class="cval">([^<]*)</span>',
            doc,
        )
    ]
    categories = [
        {"value": v, "label": clean(l)}
        for v, l in re.findall(r'<option value="([^"]+)">([^<]*)</option>', doc)
    ]
    m = re.search(r"生成时间\s*([\d\-: ]+?)\s*·", doc)
    generated = m.group(1).strip() if m else ""

    books = [parse_record(b) for b in re.split(r'<article class="record"', doc)[1:]]

    out = {
        "generated": generated,
        "stats": stats,
        "years": years,
        "top_categories": top_categories,
        "categories": categories,
        "books": books,
    }

    OUT_DEFAULT.parent.mkdir(parents=True, exist_ok=True)
    OUT_DEFAULT.write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    n_thoughts = sum(len(b["thoughts"]) for b in books)
    n_highlights = sum(len(b["highlights"]) for b in books)
    print(f"已写入 {OUT_DEFAULT}")
    print(f"书籍 {len(books)} 条 | 想法 {n_thoughts} 条 | 划线 {n_highlights} 条 | 快照时间 {generated}")


if __name__ == "__main__":
    main()
