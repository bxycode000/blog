#!/usr/bin/env python3
"""微信读书 Agent API 客户端：鉴权、请求、重试与节流。

凭据只从环境变量 WEREAD_API_KEY 读取，不落盘、不写日志。
"""

import json
import os
import random
import time
import urllib.error
import urllib.request

GATEWAY = "https://i.weread.qq.com/api/agent/gateway"
SKILL_VERSION = os.environ.get("WEREAD_SKILL_VERSION", "1.0.5")

MAX_WORKERS = 4
TIMEOUT = 30
RETRIES = 3
BACKOFF = 1.5
THROTTLE = 0.12


class WeReadError(RuntimeError):
    pass


def api_key() -> str:
    key = (os.environ.get("WEREAD_API_KEY") or "").strip()
    if not key:
        raise WeReadError(
            "缺少 WEREAD_API_KEY 环境变量。请在 https://weread.qq.com/r/weread-skills "
            "获取 API Key 后注入环境变量（不要写进仓库）。"
        )
    return key


def api(name: str, *, timeout: int = TIMEOUT, retries: int = RETRIES, **params):
    """调用网关接口。业务参数必须与 api_name 平铺在同一层。"""
    body = {"api_name": name, "skill_version": SKILL_VERSION, **params}
    payload = json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(retries):
        # 轻微错峰，避免并发请求在同一毫秒打满网关
        time.sleep(THROTTLE + random.random() * 0.08)
        req = urllib.request.Request(GATEWAY, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            # 429/499 是限流信号，退避要比普通错误更久
            wait = (5.0 if exc.code in (429, 499) else BACKOFF) * (attempt + 1)
            if attempt < retries - 1:
                time.sleep(wait + random.random())
            continue
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(BACKOFF * (attempt + 1) + random.random() * 0.5)
            continue

        if data.get("upgrade_info"):
            raise WeReadError(f"服务端要求升级 skill：{data['upgrade_info']}")
        if data.get("errcode"):
            raise WeReadError(f"{name} 返回 errcode={data['errcode']}: {data.get('errmsg', '')}")
        return data

    raise WeReadError(f"{name} 请求失败（重试 {retries} 次）：{last_error}")
