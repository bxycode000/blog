#!/usr/bin/env python3
"""同步过程中的本地增量缓存。

缓存放在 .cache/weread/（已 gitignore），不参与构建产物。
写入用临时文件 + os.replace，避免进程中断留下半个 JSON。
"""

import json
import os
import time
from pathlib import Path

CACHE_DIR = Path(".cache/weread")

PROGRESS_TTL = 7 * 24 * 3600
REVIEWS_TTL = 24 * 3600


def _path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def load(name: str) -> dict:
    p = _path(name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save(name: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(f"{name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _path(name))


def is_fresh(entry: dict, ttl: int) -> bool:
    fetched = entry.get("fetchedAt") or 0
    return (time.time() - fetched) < ttl
