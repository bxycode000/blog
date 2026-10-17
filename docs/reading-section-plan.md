# 阅读板块实现方案（微信读书）

> 状态：设计稿，未实施。本文只描述方案与关键代码结构，不改动站点现有页面、配置和脚本。
>
> 环境核实时间：2026-10-17。站点：Hugo 0.168.0 extended，Stack 主题，GitHub Actions 构建部署。

---

## 一、结论先行

1. **有可用接口**：微信读书官方 Agent Skills API（`https://i.weread.qq.com/api/agent/gateway`），用个人 `wrk-` API Key 鉴权。已用本机环境变量中的 Key 实测通过，能拿到书架、逐书进度、个人想法/划线、阅读统计。
2. **推荐构建期同步**：GitHub Actions 或本地运行同步脚本 → 生成 `books.json` → Hugo 构建静态页。浏览器端不接触 API Key，也不需要服务端代理。
3. **三个分类可用现有字段严格互斥地推导**：想读 = 完全没读过；在读 = 读过但未完成；已读 = `finishReading == 1`。注意「已读」不能只看 `progress == 100`。
4. **「短评」没有稳定接口字段**：该账号的 `/review/list/mine` 返回的全是章节点评/划线想法（`chapterName` 有值、`isFinish` 为 null）。方案采用「手写短评覆盖 + 接口整本书评兜底」两层合并，不编造。
5. **开始时间不可靠**：`startReadingTime` 大量为 0。有值就用，没有则回退到最早笔记时间，再没有就显示「—」。
6. **封面可 CDN 缩略图**：`?imageView2/2/w/144/format/webp` 把 60–90KB 压到约 10KB；但 `res.weread.qq.com` 是签名重定向，不支持缩放，需原图或本地镜像。

---

## 二、数据源核实

### 2.1 官方 Agent API（推荐）

```
POST https://i.weread.qq.com/api/agent/gateway
Authorization: Bearer $WEREAD_API_KEY
Content-Type: application/json

{"api_name": "/shelf/sync", "skill_version": "1.0.5"}
```

- Key 获取：<https://weread.qq.com/r/weread-skills> → 微信扫码 → 「快速配置 → 获取 API Key」，形如 `wrk-xxxxxxxx`。
- 业务参数必须与 `api_name`、`skill_version` **平铺在同一层**，包进 `params` 会被静默忽略。
- `errcode` 非 0 即失败；回包出现 `upgrade_info` 应停止同步并提示升级。
- 发送 `{"api_name": "/_list"}` 可拉取当前可用接口清单。

这不是匿名公开 API，而是绑定账号的官方 Agent 接口。Key 等同账号凭证，只能放环境变量/CI Secret。

### 2.2 与「HTML 快照导出」的对比

| 维度 | Agent API | HTML 快照（现有 `weread_sync.py`） |
|------|-----------|----------------------------------|
| 数据完整性 | 书架 + 逐书进度 + 笔记 + 统计 | 依赖导出工具，字段受限 |
| 自动化 | 可直接跑 CI | 需人工导出文件 |
| 稳定性 | 官方接口，有版本协商 | 解析页面结构，模板一变就坏 |
| 凭据 | 需要 API Key | 无 |

结论：新板块走 API；现有 `scripts/weread_sync.py` 保留不动，作为历史快照导入的备用路径。

### 2.3 需要的接口与调用成本（实测）

| 接口 | 用途 | 请求数 |
|------|------|--------|
| `/shelf/sync` | 书架全量：书名、作者、封面、`finishReading`、`readUpdateTime`、`updateTime`、`readerLink`、`deepLink`、`secret` | 1 |
| `/book/getprogress` | 单本进度：`progress`、`readingTime`、`startReadingTime`、`finishTime`、`updateTime` | 每本 1 次，**无批量接口** |
| `/user/notebooks` | 有笔记的书索引：`reviewCount` / `noteCount` / `bookmarkCount`、`sort` | 1 次（`count=100`，实测 76 本一次取完） |
| `/review/list/mine` | 单本个人想法/点评 | 仅对有 `reviewCount > 0` 的书，本账号 10 本 |
| `/readdata/detail?mode=overall` | 总时长、阅读天数、偏好分类 | 1 |

实测本账号（2026-10-17）：书架 490 本（无专辑）+ 1 个文章收藏入口。**全量**三分类为想读 130 / 在读 322 / 已读 38，其中 `finishReading == 1` 共 36 本，另有 2 本 `progress == 100` 但未打完成标记；11 本「手动标记读完」的书 `progress < 100`；38 本已读中 36 本能取到 `finishTime`，其余 2 本回退到最近阅读时间。`startReadingTime > 0` 仅 83 本。私密书 58 本。

**按默认过滤私密后（实际会发布的数据）**：432 本，想读 130 / 在读 293 / 已读 9（其中 `finishReading == 1` 8 本）。已读数量骤降是因为多数已读书被设为了私密。

有笔记的书 76 本（`/user/notebooks` 一次 `count=100` 取完），其中有个人点评的 10 本。全量 490 本逐书拉进度，8 并发实测约 9 秒；增量同步通常只有个位数请求。

### 2.4 字段口径与坑（都已实测）

1. **「读完」以 `finishReading` 为准。** 本账号有书 `finishReading == 1` 但 `progress` 停在 93、95、97，甚至 0。只用 `progress >= 100` 会漏掉这批。
2. **`finishTime` 对「手动标记读完」也有效。** 实测 `progress = 93` 的书仍有 `finishTime`，可直接作为读完时间；没有时回退到 `readUpdateTime`。
3. **`startReadingTime` 不可靠。** 全量 490 本里仅 83 本大于 0，其余都是 0。不能把它当唯一来源。
4. **`isStartReading` 不可信。** 同样 0% 的书返回值不一致，不要用它判断状态。
5. **短评缺失。** `/review/list/mine` 的 `type=1` 全部带 `chapterName`，`isFinish` 为 null；没有稳定的「整本书评」标识。因此短评必须有手工层。
6. **`secret == 1` 是私密阅读。** 本账号 58 本。公开站点默认应排除，避免把私密阅读发布出去。
7. **统计口径不要混用。** `/readdata/detail` 返回「读完 116 本」，是历史全量；书架 `finishReading` 只有 36 本。分类计数一律以书架为准。
8. **时间戳统一 Unix 秒**，展示前转 `YYYY-MM-DD`；`readingTime` 单位是秒。
9. **封面域名有四种**：`cdn.weread.qq.com`(322)、`wfqqreader-...myqcloud.com`(110)、`res.weread.qq.com`(54)、`weread-...file.myqcloud.com`(4)。前两者与最后一个支持 `imageView2`，`res.weread.qq.com` 会 302 到签名 URL，加参数直接 401。

---

## 三、数据结构

### 3.1 状态判定（三分类，互斥且穷尽）

```python
finished = (book.get("finishReading") == 1) or (progress >= 100)
if finished:
    status = "finished"          # 已读
elif progress > 0 or reading_time > 0:
    status = "reading"           # 在读（含「翻过几页」）
else:
    status = "want"              # 想读（从未打开/时长为 0）
```

- 不引入「翻过」第四类，统一并入「在读」，否则三分类无法穷尽。
- 已读时把 `progress` 归一化为 100，避免卡片上出现「已读 93%」。
- 每次同步后断言：`count(want) + count(reading) + count(finished) == 总条目数`。

### 3.2 `books.json` schema（v2）

```jsonc
{
  "version": 2,
  "generatedAt": "2026-10-17T03:00:00+08:00",
  "generatedTs": 1792177200,
  "source": "weread-agent-api",
  "counts": { "want": 130, "reading": 293, "finished": 9, "total": 432 },
  "stats": {
    "readDays": 1319,
    "totalReadTime": 16429202,
    "totalReadTimeText": "4563 小时 40 分钟"
  },
  "books": [
    {
      "id": "3300045845",
      "title": "伊豆舞女",
      "author": "[日]川端康成",
      "cover": "https://cdn.weread.qq.com/...jpg?imageView2/2/w/144/format/webp",
      "coverOriginal": "https://cdn.weread.qq.com/...jpg",
      "link": "https://weread.qq.com/web/reader/f8d32ac0813ab7868g015ebc",
      "detailLink": "https://weread.qq.com/book-detail?type=1&v=f8d32ac0813ab7868g015ebc",
      "category": "文学",
      "status": "want",
      "progress": 0,
      "readingTime": 0,
      "readingTimeText": "",
      "startDate": null,
      "startSource": "unknown",
      "finishDate": null,
      "lastReadDate": "2023-03-23",
      "updatedAt": 1693404091,
      "review": "",
      "reviewSource": null,
      "notes": { "thoughts": 0, "highlights": 0, "bookmarks": 0 },
      "secret": false
    }
  ]
}
```

字段说明：

| 字段 | 来源 | 说明 |
|------|------|------|
| `status` | 推导 | `want` / `reading` / `finished` |
| `progress` | `/book/getprogress` | 0–100 整数；已读归一化为 100 |
| `startDate` | `startReadingTime` → 最早笔记时间 → null | `startSource` 记录来源，便于排查 |
| `finishDate` | `finishTime` → `readUpdateTime` | 仅已读有值 |
| `lastReadDate` | `updateTime` → 书架 `readUpdateTime` | 在读/已读的最近阅读 |
| `updatedAt` | 按状态取排序时间戳 | 见 3.4 |
| `review` | 手工层 → 接口整本书评 | 见 3.3 |
| `notes` | `/user/notebooks` | 只存数量，不存正文，控制体积 |
| `secret` | `/shelf/sync` | 默认过滤，不输出到公开 JSON |

> 划线/想法正文不放进 `books.json`。本账号 380 条笔记，全量嵌入会让 JSON 从 260KB 涨到不可控；若以后要做单书笔记页，再按书懒加载独立文件。

### 3.3 短评的两层合并

```python
review = manual_reviews.get(book_id) or manual_reviews.get(title) or ""
source = "manual" if review else None

if not review:
    # 接口兜底：只取没有 chapterName 的条目，视为整本书评
    candidates = [r for r in api_reviews if not r.get("chapterName") and (r.get("content") or "").strip()]
    if candidates:
        review = max(candidates, key=lambda r: r.get("createTime", 0))["content"].strip()
        source = "api"
```

手工层文件 `content/page/reading/reviews.manual.json`：

```json
{
  "3300045845": { "text": "短篇干净，像雪落下来。", "date": "2026-10-01" },
  "伊豆舞女": { "text": "按书名兜底匹配，bookId 优先。" }
}
```

- 手工短评在每次同步后保留，不会被覆盖。
- 接口整本书评只作为兜底，避免把章节点评误当短评。
- 两者都没有时，卡片不显示短评区块，不留空壳。

### 3.4 排序规则

需求是「按更新时间倒序」。不同状态的时间语义不同，`updatedAt` 按状态取值：

| 状态 | `updatedAt` | 回退 |
|------|-------------|------|
| 在读 | `getprogress.updateTime` | 书架 `readUpdateTime` |
| 已读 | `getprogress.finishTime` | 最近阅读时间 |
| 想读 | 书架 `updateTime`（入架/更新时间） | `readUpdateTime` |

同一标签页内按 `updatedAt` 降序，时间相同按书名 `localeCompare('zh-Hans-CN')`。前端排序逻辑与后端保持一致，避免「切换标签后顺序跳变」。

---

## 四、实现方案

### 4.1 总体架构：构建期生成（推荐）

```
GitHub Actions / 本地
        │
        ├─ scripts/weread/sync.py ──► WeRead Agent API
        │        │
        │        ├─ 写 content/page/reading/books.json（原子替换）
        │        ├─ 读/写 .cache/weread/*.json（增量缓存）
        │        └─ 读 reviews.manual.json（手工短评，不覆盖）
        │
        └─ hugo -e stack ──► public/reading/index.html
```

- 浏览器只拿到静态 HTML/JSON，不接触 Key。
- 同步失败时保留上一次 `books.json`，构建照常成功。
- 不引入运行时请求，因此没有 CORS、超时、密钥泄露问题。

**不推荐运行时请求**：静态站点直接调 API 会暴露 Key；加 Cloudflare Worker/Vercel 代理则多一个可用性依赖，且每次访问都消耗接口配额。

### 4.2 目录与文件（新增，不改现有文件）

```
blog/
├─ scripts/
│  ├─ weread_sync.py              # 现有：HTML 快照导入，保留不动
│  └─ weread/
│     ├─ __init__.py
│     ├─ client.py                # API 客户端：鉴权、重试、限流
│     ├─ cache.py                 # 本地缓存读写
│     ├─ build.py                 # 状态推导、排序、schema 组装
│     └─ sync.py                  # CLI 入口
├─ content/page/reading/
│  ├─ index.md                    # 现有，不改（menu/layout 已就绪）
│  ├─ books.json                  # 同步产物（替换现有快照数据）
│  ├─ reviews.manual.json         # 新增：手工短评
│  └─ covers/                     # 可选：本地封面镜像
├─ layouts/page/reading.html      # 阅读页布局（本次功能范围内调整）
└─ .github/workflows/
   ├─ hugo_deploy.yaml            # 现有，不改
   └─ weread-sync.yaml            # 新增：定时同步
```

`.gitignore` 增加：

```
.cache/weread/
```

`books.json` 与 `reviews.manual.json` 要提交，保证无 Key 的本地构建和 fork 也能出页面。

### 4.3 同步脚本关键结构

`scripts/weread/client.py`：

```python
import json, os, random, time, urllib.request, urllib.error

GATEWAY = "https://i.weread.qq.com/api/agent/gateway"
SKILL_VERSION = os.environ.get("WEREAD_SKILL_VERSION", "1.0.5")

class WeReadError(RuntimeError):
    pass

def api_key() -> str:
    key = (os.environ.get("WEREAD_API_KEY") or "").strip()
    if not key:
        raise WeReadError("缺少 WEREAD_API_KEY 环境变量")
    return key

def api(name: str, *, timeout=30, retries=3, **params):
    body = {"api_name": name, "skill_version": SKILL_VERSION, **params}
    req = urllib.request.Request(
        GATEWAY,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("errcode"):
                raise WeReadError(f"{name} errcode={data['errcode']}")
            if data.get("upgrade_info"):
                raise WeReadError("服务端要求升级 skill：" + str(data["upgrade_info"]))
            return data
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == retries - 1:
                raise WeReadError(f"{name} 请求失败：{exc}") from exc
            time.sleep(1.5 * (attempt + 1) + random.random() * 0.5)
```

`scripts/weread/cache.py`：

```python
import json, os, time
from pathlib import Path

CACHE_DIR = Path(".cache/weread")

def load(name: str) -> dict:
    p = CACHE_DIR / f"{name}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

def save(name: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_DIR / f"{name}.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CACHE_DIR / f"{name}.json")
```

`scripts/weread/sync.py` 主流程：

```python
def main():
    shelf = api("/shelf/sync")
    books = shelf.get("books") or []

    progress_cache = load("progress")          # {bookId: {"stamp": readUpdateTime, "data": {...}}}
    todo = []
    for b in books:
        bid = b["bookId"]
        stamp = b.get("readUpdateTime", 0)
        cached = progress_cache.get(bid)
        if cached and cached.get("stamp") == stamp and fresh(cached, days=7):
            continue
        todo.append(b)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(api, "/book/getprogress", bookId=b["bookId"]): b for b in todo}
        for fut in as_completed(futures):
            b = futures[fut]
            try:
                progress_cache[b["bookId"]] = {
                    "stamp": b.get("readUpdateTime", 0),
                    "data": fut.result().get("book") or {},
                    "fetchedAt": int(time.time()),
                }
            except WeReadError as exc:
                log.warning("跳过 %s：%s", b.get("title"), exc)

    notebooks = fetch_notebooks()               # 分页直到 hasMore == 0
    reviews = fetch_reviews(notebooks)          # 仅 reviewCount > 0 的书
    manual = read_manual_reviews()

    records = build_records(books, progress_cache, notebooks, reviews, manual)
    validate(records, total=len(books) + len(shelf.get("albums") or []) + bool(shelf.get("mp")))
    atomic_write(OUT, {"version": 2, "generatedAt": now_iso(), "books": records, ...})
```

`build.py` 里的状态与排序：

```python
def classify(shelf_book, progress):
    p = int(progress.get("progress") or 0)
    finished = shelf_book.get("finishReading") == 1 or p >= 100
    if finished:
        return "finished", 100
    if p > 0 or int(progress.get("readingTime") or 0) > 0:
        return "reading", p
    return "want", 0

def updated_at(status, shelf_book, progress):
    if status == "finished":
        return progress.get("finishTime") or progress.get("updateTime") or shelf_book.get("readUpdateTime", 0)
    if status == "reading":
        return progress.get("updateTime") or shelf_book.get("readUpdateTime", 0)
    return shelf_book.get("updateTime") or shelf_book.get("readUpdateTime", 0)
```

`validate()` 至少断言：

```python
assert sum(c["count"] for c in counts.values()) == total
assert counts["finished"] == sum(1 for b in books if b.get("finishReading") == 1)
assert all(r["title"] for r in records)
assert all(r["status"] in {"want", "reading", "finished"} for r in records)
```

### 4.4 Hugo 页面渲染

现有 `layouts/page/reading.html` 已经是自定义整页（不套主题 baseof），本次只调整它，其他布局不动。

数据读取与降级：

```go-html-template
{{- $data := dict -}}
{{- with .Resources.Get "books.json" -}}
  {{- $data = . | transform.Unmarshal -}}
{{- end -}}

{{- if not $data.books -}}
  <p class="empty">阅读数据尚未同步，稍后再来看看。</p>
{{- else -}}
  {{- $order := slice "reading" "finished" "want" -}}
  {{- range $status := $order -}}
    {{- $list := sort (where $data.books "status" $status) "updatedAt" "desc" -}}
    <section class="panel" data-panel="{{ $status }}" {{ if ne $status "reading" }}hidden{{ end }}>
      {{- range $list -}}
        {{ partial "reading/card.html" . }}
      {{- end -}}
    </section>
  {{- end -}}
{{- end -}}
```

关键点：

- `where` + `sort` 在模板里完成分类与倒序，服务端渲染，无 JS 也能看到内容。
- 三个 `<section>` 一次渲染，JS 只负责切换 `hidden`；卡片数量大时再加分批显示。
- 想读 130 本，建议初始只渲染前 60 张，剩余用 `<template>` 或 JSON 懒加载；在读 293 本同理。否则单页 DOM 过重。
- 卡片固定封面宽高比（如 72×98），图片失败时用书名首字占位，避免布局跳动。

标签切换与搜索（原生 JS，无依赖）：

```js
const panels = document.querySelectorAll('[data-panel]');
const tabs = document.querySelectorAll('[data-tab]');

function show(status) {
  panels.forEach(p => { p.hidden = p.dataset.panel !== status; });
  tabs.forEach(t => { t.classList.toggle('on', t.dataset.tab === status); });
  history.replaceState(null, '', `#${status}`);
}

tabs.forEach(t => t.addEventListener('click', () => show(t.dataset.tab)));
show(location.hash.slice(1) || 'reading');

// 搜索：只在当前面板内过滤，按 data-title/data-author 匹配
```

### 4.5 封面处理

三种方案，按投入排序：

**方案 A：CDN 缩略图（推荐默认）**

```python
def cover_url(url: str, width: int = 144) -> str:
    if not url:
        return ""
    if "res.weread.qq.com" in url:
        return url  # 签名重定向，不支持缩放
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}imageView2/2/w/{width}/format/webp"
```

- 实测 74KB → 9.9KB（webp），110 本 `wfqqreader` 域名的图同样有效。
- 54 本 `res.weread.qq.com` 只能原图（约 277KB），靠 `loading="lazy"` 控制实际加载量。
- 模板加 `loading="lazy" decoding="async" referrerpolicy="no-referrer"`，`onerror` 切换占位样式。

**方案 B：本地镜像（离线可用）**

- 同步时下载到 `content/page/reading/covers/<bookId>.jpg`，构建时用 Hugo 图片处理：

```go-html-template
{{- with $cover := $.Resources.Get (printf "covers/%s.jpg" .id) -}}
  {{- $thumb := $cover.Resize "144x webp q80" -}}
  <img src="{{ $thumb.RelPermalink }}" width="144" height="196" alt="{{ .title }}">
{{- end -}}
```

- 490 张 webp 约 5MB，仓库会变大；首次构建图片处理也会变慢。
- 适合对「页面不依赖第三方 CDN」有要求的场景。

**方案 C：不下载、不缩放，直接原图**

- 最简单，但首屏流量高，不推荐。

默认用 A；若后续发现 CDN 限流或图片失效，再切 B，数据结构不变（同时保留 `cover` 与 `coverOriginal`）。

---

## 五、缓存与请求频率控制

### 5.1 三层缓存

| 层 | 位置 | 失效条件 | 作用 |
|----|------|----------|------|
| 书架 | 每次同步必拉 | 不缓存 | 1 次请求，必须最新 |
| 逐书进度 | `.cache/weread/progress.json` | `readUpdateTime` 变化，或缓存超过 7 天 | 把 490 次降到增量几次 |
| 笔记/想法 | `.cache/weread/reviews.json` | 该书 `sort` 变化，或超过 24 小时 | 避免重复拉有笔记的书 |
| 封面 | 浏览器/CDN 缓存 | URL 不变即复用 | 不重复下载 |

### 5.2 请求节流参数

```python
MAX_WORKERS = 8          # 实测稳定；再高容易触发限流
TIMEOUT = 30             # 秒
RETRIES = 3
BACKOFF = 1.5            # 1.5s, 3s, 4.5s + 随机抖动
MAX_CONSECUTIVE_FAILURES = 5
```

- 连续 5 次失败立即停止本轮同步，避免在账号异常时打满接口。
- 单本失败不中断整体：跳过并记录，保留缓存里的旧值。
- 同步结束打印摘要：请求数、成功/跳过/失败数、耗时、状态计数自检结果。
- 定时任务每天 1 次足够；手动同步加 5 分钟本地节流，避免调试时反复全量拉取。

---

## 六、失败降级

| 故障 | 行为 |
|------|------|
| 无 `WEREAD_API_KEY` | 脚本退出码 3，不写文件；构建继续用旧 `books.json` |
| 接口 5xx/超时 | 重试 3 次；仍失败则跳过该书，保留缓存值 |
| 全量同步失败 | **不覆盖** `books.json`，以非 0 退出但 CI 不阻断部署 |
| `books.json` 缺失/损坏 | Hugo 模板走 `with` 空分支，显示「数据尚未同步」，构建成功 |
| 封面 404/超时 | `onerror` 显示书名首字占位，卡片高度不变 |
| 短评缺失 | 不渲染短评区块，不留空行 |
| 字段缺失（开始时间等） | 显示「—」，不猜测、不用同步时间冒充 |

原子写入：

```python
def atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
```

这样即使进程在写一半时被杀，也不会留下半个 JSON。

---

## 七、更新机制

### 7.1 手动触发（默认）

```bash
export WEREAD_API_KEY=...        # 或 GitHub Actions Secret
py scripts/weread/sync.py
git add content/page/reading/books.json
git commit -m "reading: sync $(date +%F)"
git push
```

本地 PowerShell 用 `$env:WEREAD_API_KEY`；脚本只从环境变量读取，不落盘、不写进仓库。

### 7.2 定时任务（GitHub Actions）

新增 `.github/workflows/weread-sync.yaml`：

```yaml
name: weread-sync

on:
  schedule:
    - cron: "0 19 * * *"      # UTC 19:00 = 北京时间 03:00
  workflow_dispatch:

permissions:
  contents: write

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Sync WeRead data
        env:
          WEREAD_API_KEY: ${{ secrets.WEREAD_API_KEY }}
        run: python scripts/weread/sync.py
      - name: Commit if changed
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add content/page/reading/books.json
          git diff --staged --quiet || git commit -m "reading: auto sync"
          git push
```

**关键注意**：用 `GITHUB_TOKEN` 推送的提交不会触发 `hugo_deploy.yaml`（GitHub 防止递归触发）。两种解法：

1. 在同一个 workflow 里继续执行 Hugo 构建和部署步骤（复制 `hugo_deploy.yaml` 的 build/deploy），推荐；
2. 或使用个人 PAT（现有 `secrets.TOKEN`）推送，让 `hugo_deploy.yaml` 正常触发。

方案 1 少一个 secret，链路更短；方案 2 复用现有部署配置。二选一，不要同时上。

### 7.3 更新频率建议

- 阅读数据变化慢，每天 1 次足够；书架 490 本全量首跑后，增量通常只有几本。
- 若只想在发文时更新，可只用手动触发，CI 里不加 cron。
- 失败不阻断：同步 job 失败时页面仍由上次数据构建，不会出现空白页。

---

## 八、实施步骤与验收

### 阶段 1：数据层（不改页面）

1. 新建 `scripts/weread/`，实现 `client.py` / `cache.py` / `build.py` / `sync.py`。
2. 用现有 `books.json` 做对照，跑一次全量，检查：
   - 公开条目 = 432（490 本中过滤 58 本私密；本账号无专辑，`mp` 文章收藏入口不计入书籍列表）；
   - `finished` = 9（过滤私密后，`finishReading == 1` 8 本 + 1 本 `progress == 100`）；
   - 三状态计数之和 = 公开条目数；全量口径下应为 490 / 38；
   - 抽查 3 本已读书有 `finishDate`，3 本在读有 `progress`；
   - 私密书默认不出现在输出中。
3. 连续跑第二次，确认请求数降到个位数（缓存生效）。

### 阶段 2：页面层

4. 调整 `layouts/page/reading.html`：三标签、按 `updatedAt` 倒序、短评区块、封面占位。
5. 本地 `./hugo.exe -e stack` 构建，检查：
   - 无 JS 时三个 section 都在 DOM 里；
   - 想读初始渲染数量受控，滚动/按钮能加载更多；
   - 图片失败时布局不塌。
6. 移动端 390px 宽度检查卡片与标签不溢出。

### 阶段 3：自动化

7. 新增 `weread-sync.yaml`，手动 `workflow_dispatch` 跑通。
8. 确认同步后自动部署，且失败时旧数据仍可构建。

### 验收清单

- [ ] 三分类互斥且总数守恒
- [ ] 已读判定以 `finishReading` 为准，手动读完的书有读完时间
- [ ] 每类内按更新时间倒序
- [ ] 短评优先手工、其次整本书评，不误用章节点评
- [ ] 开始时间缺失时显示「—」，不编造
- [ ] 私密书籍默认不公开
- [ ] Key 只存在于环境变量/CI Secret
- [ ] 断网/接口失败时页面仍正常显示旧数据
- [ ] 现有文章、归档、关于页不受影响

---

## 九、风险与边界

1. **接口非正式公开契约**：Agent API 随 `skill_version` 演进，字段可能裁剪。脚本应对缺字段宽容，回包出现 `upgrade_info` 时停止并提示，而不是硬跑。
2. **短评依赖人工维护**：这是数据源本身的限制，不是实现缺陷。若以后微信读书开放整本书评字段，只需替换 `build.py` 的合并逻辑，页面不用动。
3. **开始时间覆盖不全**：只有 `startReadingTime > 0` 或有笔记的书能拿到。若产品上必须展示，建议改为「首次有记录的时间」并在页面注明口径，而不是伪造。
4. **想读数量大**：公开后想读 130 本、在读 293 本，单页 DOM 会很重。分批渲染是必要的，不建议一次性输出全部 DOM。
5. **封面外链**：CDN 可能限流或改签名策略。保留 `coverOriginal` 和本地镜像开关，出问题时能快速切换。
6. **私密阅读**：默认过滤 `secret == 1`；如果用户希望展示，应在 `sync.py` 加显式配置项，而不是默认公开。

---

## 十、关键文件清单

| 文件 | 动作 | 说明 |
|------|------|------|
| `scripts/weread/client.py` | 新增 | API 客户端、重试、限流 |
| `scripts/weread/cache.py` | 新增 | 本地增量缓存 |
| `scripts/weread/build.py` | 新增 | 状态推导、短评合并、排序、校验 |
| `scripts/weread/sync.py` | 新增 | CLI 入口 |
| `content/page/reading/reviews.manual.json` | 新增 | 手工短评 |
| `content/page/reading/books.json` | 替换 | 新 schema v2 |
| `layouts/page/reading.html` | 调整 | 三标签、短评、封面降级 |
| `.github/workflows/weread-sync.yaml` | 新增 | 定时同步 |
| `.gitignore` | 追加 | `.cache/weread/` |
| `scripts/weread_sync.py` | 不动 | 旧 HTML 快照路径保留 |
| 其他页面/配置 | 不动 | 不影响现有功能 |
