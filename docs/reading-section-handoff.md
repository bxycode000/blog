# 阅读板块实现交接文档（微信读书）

> 面向后续接手的 agent：本文包含需求、调研结论、技术决策、代码结构、踩坑记录与当前进度。
> 最后更新：2026-10-17
> 仓库：`D:\Self-website\blog\blog`（Hugo 静态站，Stack 主题）

---

## 一、摘要

### 项目目标

在个人网站新增「阅读板块」，展示并同步微信读书的阅读记录：书名、作者、封面、阅读状态、阅读进度、开始/读完时间、短评。支持「想读 / 在读 / 已读」三分类，按更新时间倒序。要求不影响站点现有功能，凭据只走环境变量。

### 技术栈

| 项 | 选型 |
|----|------|
| 站点生成 | Hugo 0.168.0 extended |
| 主题 | hugo-theme-stack（部署环境 `-e stack`），另有 reimu 配置未用于线上 |
| 部署 | GitHub Actions → `bxycode000/bxycode000.github.io` |
| 数据同步 | Python 3.13（本机用 `py` 启动，不是 `python3`），仅标准库 |
| 数据源 | 微信读书 Agent API Gateway |
| 前端 | 原生 HTML/CSS/JS，无框架、无构建步骤 |

### 当前进度

**三个阶段已全部实现并验证，尚未提交 git。**

- 数据层完成：`scripts/weread/` 四个模块，全量同步跑通。
- 页面层完成：`layouts/page/reading.html` 重写，浏览器实测通过。
- 自动化完成：定时同步 workflow 已写好，本地未实际触发（需要远端 Secret）。

### 已完成

- [x] 确认微信读书可用接口并实测字段
- [x] 设计 `books.json` schema v2 与三分类判定口径
- [x] 实现同步脚本、增量缓存、限流退避、失败回退
- [x] 重写阅读页：三标签、倒序、分批渲染、搜索、封面降级
- [x] 构建验证、浏览器交互验证、故障降级验证
- [x] 定时同步 workflow、`.gitignore`、使用说明

### 未完成 / 待用户操作

- [ ] 在 GitHub 仓库添加 Secret `WEREAD_API_KEY`（定时任务必需）
- [ ] 手工短评内容为空，需用户按需填写 `reviews.manual.json`
- [ ] 代码尚未 commit / push
- [ ] 可选优化：封面本地镜像、单书笔记详情页、统计图表

---

## 二、原始需求

1. 确认微信读书有可用的公开 API 或数据导出途径。
2. 设计阅读数据结构与内容组织，支持「想读 / 在读 / 已读」，按更新时间倒序。
3. 给出可落地方案：数据获取与存储（构建期 vs 运行时）、页面渲染、封面处理、更新机制。
4. 说明缓存与请求频率控制，保证获取失败时页面仍正常展示。
5. 只给方案与关键代码结构，不改动现有其他功能，凭据统一用环境变量。

后续用户要求「分阶段执行」，因此从方案进入实现。

---

## 三、环境与仓库现状（接手必读）

### 关键路径

```
D:\Self-website\blog\blog\
├─ config/_default/hugo.toml        # baseURL、语言
├─ config/stack/                    # 线上主题配置（-e stack）
├─ config/reimu/                    # 另一套主题配置，未用于线上
├─ content/page/reading/
│  ├─ index.md                      # 阅读页 front matter（未改动）
│  ├─ books.json                    # 同步产物（已替换为 schema v2）
│  └─ reviews.manual.json           # 新增：手工短评
├─ layouts/page/reading.html        # 已重写
├─ scripts/
│  ├─ weread_sync.py                # 旧：HTML 快照解析，保留未动
│  └─ weread/                       # 新增：API 同步
├─ .github/workflows/
│  ├─ hugo_deploy.yaml              # 现有部署流程，未改动
│  └─ weread-sync.yaml              # 新增：定时同步 + 部署
└─ docs/                            # 设计稿与使用说明
```

### 本地命令

```bash
cd D:/Self-website/blog/blog

# 构建（必须带 -e stack，否则主题配置不对）
./hugo.exe -e stack -d "$TEMP/hugo-out"

# 同步数据
py scripts/weread/sync.py
```

### 注意事项

- 本机 Python 只能用 `py` 调用，`python3` 不存在。
- `assets/jsconfig.json` 是会话开始前就存在的未跟踪文件，与本次改动无关，不要误提交或删除。
- 现有 `hugo_deploy.yaml` 在 push 到 `main` 时构建并部署，使用 `secrets.TOKEN`。

---

## 四、数据源调研结论

### 4.1 可用接口

微信读书提供官方 Agent API，不是匿名公开 API：

```http
POST https://i.weread.qq.com/api/agent/gateway
Authorization: Bearer $WEREAD_API_KEY
Content-Type: application/json

{"api_name": "/shelf/sync", "skill_version": "1.0.5"}
```

- Key 获取：<https://weread.qq.com/r/weread-skills> → 微信扫码 → 「快速配置 → 获取 API Key」，格式 `wrk-...`。
- 业务参数必须与 `api_name`、`skill_version` **平铺在同一层**；包进 `params` 会被静默忽略。
- `errcode` 非 0 即失败；回包出现 `upgrade_info` 应停止同步并提示升级。
- `{"api_name": "/_list"}` 可拉取全部可用接口。

### 4.2 用到的接口

| 接口 | 用途 | 请求量 |
|------|------|--------|
| `/shelf/sync` | 书架全量：`bookId`、`title`、`author`、`cover`、`category`、`finishReading`、`readUpdateTime`、`updateTime`、`readerLink`、`deepLink`、`secret` | 1 次 |
| `/book/getprogress` | 单本进度：`progress`、`readingTime`、`startReadingTime`、`finishTime`、`updateTime` | 每本 1 次，无批量接口 |
| `/user/notebooks` | 有笔记的书索引：`reviewCount`、`noteCount`、`bookmarkCount`、`sort` | 1 次（`count=100`） |
| `/review/list/mine` | 单本个人想法/点评 | 仅有 `reviewCount > 0` 的书 |
| `/readdata/detail?mode=overall` | 总阅读天数、总时长 | 1 次 |

### 4.3 实测数据（2026-10-17，本账号）

| 指标 | 数值 |
|------|------|
| 书架电子书 | 490 本（专辑 0，文章收藏入口 1） |
| 私密书（`secret == 1`） | 58 本 |
| `finishReading == 1` | 36 本 |
| 全量三分类 | 想读 130 / 在读 322 / 已读 38 |
| **过滤私密后（实际发布）** | **432 本：想读 130 / 在读 293 / 已读 9** |
| 已读中能取到 `finishTime` | 36 / 38（其余回退最近阅读时间） |
| `startReadingTime > 0` | 83 / 490 |
| 有笔记的书 | 76 本；有个人点评的 10 本 |
| 全量同步耗时 | 约 40 秒（并发 4）；缓存命中约 2.5 秒 |

### 4.4 字段口径与陷阱

1. **「读完」以 `finishReading` 为准，不能只看 `progress == 100`。**
   本账号有 11 本书手动标记读完但进度停在 93、95、97 甚至 0。另有 2 本进度 100 但未打完成标记，按规则也归入已读。
2. **`finishTime` 对手动标记读完同样有效**，可直接作为读完时间。
3. **`startReadingTime` 覆盖差**（490 本仅 83 本有值），不能作为唯一来源。
4. **`isStartReading` 不可信**，同样 0% 的书返回值不一致，不要用来判断状态。
5. **没有「整本书短评」字段。** `/review/list/mine` 返回的 `type=1` 全部带 `chapterName`，`isFinish` 为 null；唯一一条非章节想法来自私密书。短评必须靠手工层。
6. **`secret == 1` 是私密阅读**，公开站点默认过滤。
7. **统计口径不要混用**：`/readdata/detail` 返回「读完 116 本」是历史全量，与书架 36 本不是同一口径。
8. **时间戳统一 Unix 秒**，展示转 `YYYY-MM-DD`；`readingTime` 单位是秒。
9. **封面域名有四种**：`cdn.weread.qq.com`、`wfqqreader-*.image.myqcloud.com`、`res.weread.qq.com`、`weread-*.file.myqcloud.com`。前三者中 `res.weread.qq.com` 是签名重定向，加缩放参数会 401。

---

## 五、关键决策与依据

| 决策 | 选择 | 依据 |
|------|------|------|
| 数据获取时机 | **构建期生成** | 运行时请求会暴露 Key；加代理又多一个依赖。静态页零运行时风险 |
| 数据源 | Agent API，不用 HTML 快照 | 字段完整、可自动化、不依赖导出工具；旧快照脚本保留作备用 |
| 分类数量 | 三分类，不设「翻过」 | 需求只要三类；`progress=0` 但有时长的书并入「在读」，保证穷尽 |
| 已读判定 | `finishReading == 1` 或进度 100 | 实测差 11 本，只用进度会漏 |
| 短评来源 | 手工文件优先，接口整本书评兜底 | 数据源没有稳定短评字段，不能编造 |
| 开始时间 | 接口 → 最早笔记时间 → 不显示 | 覆盖不全时宁可缺省，不伪造 |
| 封面 | CDN 缩略图 + 失败占位 | 74KB → 约 10KB；签名域名只能原图 |
| 排序 | 每类内按状态相关时间倒序 | 已读取读完时间，在读取最近阅读，想读取入架时间 |
| 缓存 | 本地 JSON + TTL + 版本戳 | 把 490 次请求降到增量个位数 |
| 定时任务 | 同 workflow 内构建部署 | `GITHUB_TOKEN` 推送不会触发另一个 workflow |

---

## 六、数据结构（schema v2）

`content/page/reading/books.json`：

```jsonc
{
  "version": 2,
  "source": "weread-agent-api",
  "generatedAt": "2026-10-17T21:30:00+08:00",
  "generatedTs": 1792176600,
  "counts": { "want": 130, "reading": 293, "finished": 9, "total": 432 },
  "stats": {
    "readDays": 1319,
    "totalReadTime": 16429202,
    "totalReadTimeText": "4563 小时 40 分钟"
  },
  "books": [
    {
      "id": "3300043489",
      "title": "伊豆的舞女",
      "author": "[日]川端康成",
      "cover": "https://cdn.weread.qq.com/...jpg?imageView2/2/w/144/format/webp",
      "coverOriginal": "https://cdn.weread.qq.com/...jpg",
      "link": "https://weread.qq.com/web/reader/...",
      "detailLink": "https://weread.qq.com/book-detail?type=1&v=...",
      "category": "文学",
      "status": "reading",
      "progress": 1,
      "readingTime": 120,
      "readingTimeText": "2 分钟",
      "startDate": "2024-03-20",
      "startSource": "api",
      "finishDate": null,
      "lastReadDate": "2024-03-20",
      "updatedAt": 1710936298,
      "review": "",
      "reviewSource": null,
      "notes": { "thoughts": 0, "highlights": 0, "bookmarks": 0 },
      "secret": false
    }
  ]
}
```

字段规则：

- `status` 只能是 `want` / `reading` / `finished`。
- 已读的 `progress` 归一化为 `100`，避免出现「已读 93%」。
- `startSource`：`api` / `first-note` / `unknown`，便于排查时间来源。
- 想读的 `lastReadDate` 强制为 `null`。
- `notes` 只存数量，不存正文，控制 JSON 体积。
- 私密书默认不进入 `books`。

---

## 七、核心逻辑

### 7.1 三分类（互斥且穷尽）

```python
def classify(shelf_book, progress):
    p = int(progress.get("progress") or 0)
    finished = shelf_book.get("finishReading") == 1 or p >= 100
    if finished:
        return "finished", 100
    if p > 0 or int(progress.get("readingTime") or 0) > 0:
        return "reading", p
    return "want", 0
```

### 7.2 排序时间

```python
def updated_at(status, shelf_book, progress):
    if status == "finished":
        return int(progress.get("finishTime") or progress.get("updateTime")
                   or shelf_book.get("readUpdateTime") or 0)
    if status == "reading":
        return int(progress.get("updateTime") or shelf_book.get("readUpdateTime") or 0)
    return int(shelf_book.get("updateTime") or shelf_book.get("readUpdateTime") or 0)
```

### 7.3 短评合并

```python
def pick_review(book, manual, api_reviews):
    # 1. 手工层：bookId 优先，其次书名
    for key in (book.get("bookId"), clean(book.get("title"))):
        entry = manual.get(key)
        if entry:
            text = clean(entry.get("text") if isinstance(entry, dict) else entry)
            if text:
                return text, "manual"

    # 2. 接口兜底：只取没有 chapterName 的条目，视为整本书评
    candidates = [
        clean(r.get("content"))
        for r in api_reviews
        if not r.get("chapterName") and clean(r.get("content"))
    ]
    if candidates:
        return candidates[0], "api"
    return "", None
```

### 7.4 封面缩略图

```python
def cover_url(url, width=144):
    url = (url or "").strip()
    if not url or "res.weread.qq.com" in url:
        return url  # 签名重定向，加参数会 401
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}imageView2/2/w/{width}/format/webp"
```

实测：74KB → 9.9KB（webp）；`res.weread.qq.com` 只能原图（约 277KB），靠懒加载控制。

### 7.5 缓存与限流

| 层 | 位置 | 失效条件 |
|----|------|----------|
| 书架 | 不缓存 | 每轮必拉 1 次 |
| 逐书进度 | `.cache/weread/progress.json` | `readUpdateTime` 变化，或 7 天 |
| 笔记/想法 | `.cache/weread/reviews.json` | 该书 `sort` 变化，或 24 小时 |

```python
MAX_WORKERS = 4
TIMEOUT = 30
RETRIES = 3
BACKOFF = 1.5
THROTTLE = 0.12
```

- 每次请求前轻微错峰；HTTP 429/499 使用更长退避。
- 单本失败不中断整体，**回退旧缓存**，避免把「在读」误降级成「想读」。
- 落盘前把本轮结果合并进旧缓存，否则缓存永远只有最后一次的数据。

### 7.6 失败降级

| 故障 | 行为 |
|------|------|
| 无 `WEREAD_API_KEY` | 退出码 3，不写文件，旧 `books.json` 保留 |
| 接口超时/限流 | 重试 3 次；仍失败则跳过并沿用旧缓存 |
| 全量同步失败 | 不覆盖 `books.json` |
| `books.json` 缺失/损坏 | 模板用 `try` 捕获，显示「阅读数据尚未同步」 |
| 封面 404 | `onerror` 切换书名首字占位，布局不塌 |

模板中的容错写法（Hugo 0.168 支持 `try`）：

```go-html-template
{{- $data := dict -}}
{{- with .Resources.Get "books.json" -}}
  {{- with try (transform.Unmarshal .) -}}
    {{- if not .Err -}}{{- $data = .Value -}}{{- end -}}
  {{- end -}}
{{- end -}}
```

---

## 八、代码与文件变更清单

### 新增

| 文件 | 作用 |
|------|------|
| `scripts/weread/client.py` | 鉴权、请求、重试、限流退避 |
| `scripts/weread/cache.py` | 增量缓存读写，原子替换 |
| `scripts/weread/build.py` | 分类、排序、短评合并、封面、校验 |
| `scripts/weread/sync.py` | CLI 入口，编排同步流程 |
| `content/page/reading/reviews.manual.json` | 手工短评（当前只有 `_comment` 说明） |
| `.github/workflows/weread-sync.yaml` | 每天 03:00（北京时间）同步 + 构建 + 部署 |
| `docs/reading-section-plan.md` | 完整设计稿 |
| `docs/reading-section-usage.md` | 使用说明 |

### 修改

| 文件 | 变更 |
|------|------|
| `content/page/reading/books.json` | 替换为 schema v2 真实数据（432 本） |
| `layouts/page/reading.html` | 整页重写：三标签、分批、搜索、短评、封面降级 |
| `.gitignore` | 追加 `.cache/weread/` |

### 未改动

`config/**`、`content/page/{about,archives,search}`、`content/post/**`、`scripts/weread_sync.py`、`hugo_deploy.yaml`、主题目录。

### 页面实现要点

- 服务端用 `where` + `sort` 分好类，三个 `<section>` 全部渲染，JS 只负责切换 `hidden`；无 JS 也能看到内容。
- 每类初始显示 60 张，`显示更多` 每次 +60；搜索跨分类，但同样受分批上限约束。
- 标签状态写入 URL hash（`#reading` / `#finished` / `#want`），可直链。
- 卡片固定封面 72×98，图片失败用书名首字占位。
- 搜索匹配 `data-title` + `data-author`。

### 定时任务要点

```yaml
on:
  schedule:
    - cron: "0 19 * * *"   # UTC 19:00 = 北京时间 03:00
  workflow_dispatch:
```

- 同步步骤 `continue-on-error: true`，失败只发警告，继续用旧数据构建部署。
- 同一个 workflow 内完成构建和部署，因为 `GITHUB_TOKEN` 推送的提交不会触发 `hugo_deploy.yaml`。

---

## 九、实施中遇到的问题与修复

| # | 问题 | 现象 | 修复 |
|---|------|------|------|
| 1 | 并发过高触发限流 | 第二次运行大量 `HTTP Error 499`，55 本失败 | 并发 8 → 4；增加 0.12s 错峰；429/499 专用退避 |
| 2 | 失败被误判为「想读」 | 计数从 130/293 变成 161/262 | 请求失败时回退旧缓存，不用空进度参与分类 |
| 3 | 缓存不持久 | 每轮都全量请求，缓存文件只有 2 字节 | 落盘前把本轮结果合并进旧缓存字典 |
| 4 | 损坏 JSON 导致构建失败 | 写坏 `books.json` 后 `hugo` 直接报错退出 | 模板用 `try (transform.Unmarshal .)` 捕获，降级为空状态 |
| 5 | 模板上下文错误 | `$.title` 报 `can't evaluate field title` | `range` 内先 `{{- $b := . }}`，统一用 `$b` |
| 6 | 想读显示「最近阅读」 | 未开始的书出现阅读日期 | `status == "want"` 时 `lastReadDate = null` |
| 7 | `_comment` 被算作短评 | 日志显示「手工短评 1 条」 | 读取时过滤 `_` 开头的键 |
| 8 | 搜索绕过分批限制 | 搜索时一次渲染全部匹配卡片 | 搜索与浏览共用 `state.shown[status]` 上限，计数改为「匹配 X 本，已显示 Y 本」 |
| 9 | 交互测试误判 | 正则把可选 ` hidden` 分组当成未隐藏 | 改为对 `<article ...>` 标签逐个检查是否含 ` hidden` |

---

## 十、验证记录

### 数据

- 全量同步：`条目 432 = 想读 130 + 在读 293 + 已读 9 ✓`，与独立统计脚本一致。
- 缓存命中：第二次运行 0 次进度请求，2.5 秒完成。
- 字段完整性：空书名 0、空封面 0、空链接 0；已读 9 本全部有 `finishDate`。
- 私密泄露：输出中 `secret == true` 为 0。
- 排序：三类均与 `updatedAt` 降序完全一致（HTML 转义后比对）。

### 页面（无头 Edge）

| 场景 | 结果 |
|------|------|
| 初始加载 | 在读显示 60 / 432，另两类隐藏 |
| 切换到已读 | 9 张全部可见，hash 变为 `#finished` |
| 切换到想读 | 显示 60 张 |
| 点击显示更多 | 60 → 120 |
| 搜索「川端」 | 匹配 22 本，在读 9 + 想读 13 |
| 搜索无结果 | 三个面板全部隐藏，计数为 0 |
| 移动端（503px 视口） | 无横向溢出；560px 以下单列规则存在 |

### 降级

- 删除 `books.json`：构建成功，显示空状态。
- 写入损坏 JSON：构建成功，显示空状态。
- 清空 `WEREAD_API_KEY`：脚本退出码 3，构建成功，页面仍渲染 432 张卡片。

### 回归

首页、关于、归档、文章页均正常构建，未受影响。

---

## 十一、其他 agent 接入须知

### 硬性约束

1. **不要改动阅读板块以外的页面、配置和主题**，除非用户明确要求。
2. **凭据只从环境变量读取**（`WEREAD_API_KEY`），不得写入源码、示例、测试或提交历史；文档中不要回显完整 Key。
3. **默认过滤私密书籍**（`secret == 1`）。要展示必须显式传 `--include-secret`，不能默认公开。
4. **「已读」必须用 `finishReading == 1` 或进度 100 判定**，不能只信 `progress`。
5. **开始时间缺失时显示为空**，不要用同步时间或入架时间冒充。
6. **短评不得用章节点评冒充**；接口兜底只接受 `chapterName` 为空的条目。
7. 旧脚本 `scripts/weread_sync.py` 是 HTML 快照路径，**保留不动**。

### 常用命令

```bash
cd D:/Self-website/blog/blog

py scripts/weread/sync.py                # 增量同步
py scripts/weread/sync.py --full         # 忽略缓存
py scripts/weread/sync.py --include-secret
py scripts/weread/sync.py --dry-run

./hugo.exe -e stack -d "$TEMP/hugo-out"  # 构建到临时目录
```

### 容易踩的坑

- `python3` 在本机不存在，用 `py`。
- Hugo 必须带 `-e stack`，否则读的是错误主题配置。
- Hugo 的 `sort ... "updatedAt" "desc"` 对整数字段有效；字段名拼错会静默不排序。
- `transform.Unmarshal` 遇到坏 JSON 会中断构建，必须用 `try`。
- 微信读书接口参数必须平铺，包 `params` 不会报错但会返回默认结果。
- `res.weread.qq.com` 封面加任何查询参数都会 401。
- GitHub Actions 里用 `GITHUB_TOKEN` 推送不会触发其他 workflow。
- 无头 Edge/Chrome 的最小视口约 500px，测 390px 需要用 iframe 或设备模拟。

### 当前数据状态

- `books.json`：432 本，130 / 293 / 9，生成时间以文件内 `generatedAt` 为准。
- `reviews.manual.json`：仅含 `_comment`，实际短评 0 条。
- `.cache/weread/`：本地存在，已被 gitignore，CI 中为空（首跑全量）。

---

## 十二、下一步建议

1. **提交代码**：按「数据层 / 页面 / 自动化」拆三个 commit，便于回滚。
2. **配置 Secret**：GitHub → Settings → Secrets → Actions 添加 `WEREAD_API_KEY`，手动触发一次 `weread-sync` 验证。
3. **补短评**：从微信读书 App 复制书评到 `reviews.manual.json`，键用 bookId 或书名。
4. **可选：封面本地镜像**。若担心 CDN 限流，同步时下载到 `content/page/reading/covers/`，模板改用 Hugo `Resize`；数据结构已保留 `coverOriginal`。
5. **可选：笔记详情页**。目前只展示笔记数量；若要做单书划线/想法页，按书生成独立 JSON 懒加载，避免主页面膨胀。
6. **可选：统计图表**。`/readdata/detail` 已能取到年度时长与偏好分类，可作为阅读页顶部可视化，但要注意与书架口径区分。

---

## 十三、相关文档

- `docs/reading-section-plan.md`：完整设计稿（含更多方案对比与风险分析）。
- `docs/reading-section-usage.md`：面向站长的日常使用与故障处理说明。

---

## 十四、2026-10-17 晚：阅读页 v2（四分类 + 年份筛选 + UI 重构）

> 接手 agent：速构构（网页通专家）。本次改动只涉及页面层，同步脚本与数据层未动。

### 改动范围

| 文件 | 变更 |
|------|------|
| `layouts/page/reading.html` | 整页重写：四分类、年份筛选、URL 状态、空状态、设计令牌重构 |
| `content/page/reading/index.md` | 仅 front matter 的 description 与正文说明更新 |
| `D:/Self-website/blog/.hugo-out/`（构建产物，gitignore 范围外的工作目录） | 本地验证用 |

### 四分类口径（模板层派生，不改 books.json）

- `want` / `finished`：沿用原判定（`finishReading` 或进度 100 → 已读）。
- **弃读（新）**：`status == "reading"` 且 `lastReadDate`（无则 `updatedAt`）距构建日超过 **180 天** → `abandoned`。基于构建时的 `now` 每次自动重算，"停滞 N 天"在模板里计算。
- 每类的排序键：在读/弃读 = `lastReadDate`；已读 = `finishDate`；想读 = `updatedAt`（入架时间）。
- 年份归档键：已读 = `finishDate` 年（回退 `lastReadDate`）；在读/弃读 = `lastReadDate` 年；想读 = 入架年。

实测本账号：在读 293 → **在读 38 + 弃读 255**（>365 天的就有 217 本）。

### 交互与状态

- 分类切换：tab 胶囊（roving tabindex，←/→/Home/End 键盘导航）+ 统计卡也可点。
- 年份筛选与状态**联动保持**（切 tab 不清年份）；搜索同理由 chips 单独移除。
- 状态写入 URL 查询串（`?status=abandoned&year=2023`，`history.replaceState`），可直链；默认 `reading` 不写。
- 空状态：区分"筛选组合无结果"（含条件描述 + 清除年份 / 重置全部）与"分类为空"。
- 显示更多：每批 60，带 160ms 加载反馈与新增卡片入场动画（`prefers-reduced-motion` 全局禁用）。
- 重置按钮只在"非默认状态"时出现。

### 视觉

- 设计令牌一套（`--surface/--ink/--line` 等 20+ 变量），亮/暗两套，`prefers-color-scheme` + `[data-scheme]` 双通道（Stack 主题切换 dark 时 `[data-scheme="dark"]` 会生效）。
- 分类四色体系：想读灰蓝 / 在读蓝 / 已读绿 / 弃读暖棕，色点、徽章、进度条、统计卡左侧色条共用。
- 搜索 160ms 防抖，结果计数 `aria-live="polite"`；封面 SVG 占位首字在图片加载前常驻（`::before` 层）。
- 响应式：>900px 工具栏单行；<900px 筛选区换行、搜索占满；<640px 统计 2×2、单列卡片、隐藏分隔点。

### 验证记录（Playwright + 本机 Edge，headless）

交互（1280px）：四 tab 初始态/切换/计数 ✓；弃读 60 本→更多→120 ✓；年份 2023 筛出 19/255 且 URL 带参 ✓；切 tab 年份保持（在读+2023=0 本，联动正确）✓；搜索"川端" ✓；空状态文案与操作按钮 ✓；一键重置回默认 ✓；键盘 ← 切到已读 ✓；JS 报错 0。
响应式（390px）：横向溢出 0px，单列卡片，工具栏 sticky ✓。深色：`color-scheme: dark` 下 body 背景正确 ✓。

### 已知取舍

- 弃读阈值 180 天写死在模板（`$abandonDays := 180`）；要调就改这一个变量。
- 同步脚本 `counts` 仍是三分类口径，页面 tab 数字是模板重算的（与统计卡一致，不会矛盾）。
- 旧 hash 路由（`#finished`）不再支持，改用 `?status=` 查询参数。
- **23:10 调整**：第四类标签由「弃读」改为「准备读」，内部键 `abandoned` → `planned`（URL 同步变为 `?status=planned`），判定口径不变（仍在读且超过 180 天未读）；meta description 同步更新。

---

## 十五、2026-10-18 凌晨：书架外历史阅读（`/reading-history/`）

### 背景

App 统计「在读 1131 / 读完 116」是历史口径，`/shelf/sync` 只有当前 493 本；书架外的书此前完全无法展示。

### 数据链路

- 新增 `scripts/weread/history.py`：`/readdata/detail?mode=weekly` 返回当周读得最多的前 10 本（含 bookId），从注册日 2020-02-10 扫 349 周 → 575 本唯一书，其中 450 本不在书架；合并笔记库离架书 48 本 → 456；去重 + 过滤 1 条本地路径异常条目 → **452 本（39 本可确认读完）**。
- 逐本调 `/book/info` + `/book/getprogress` 补详情（抽样 30 本全部成功）。
- 产物 `data/history.json`，含 `lastWeekTs`；CI 无本地缓存时 `bootstrap_from_output()` 用该文件恢复基线，避免每天全量重扫。
- 增量：默认回扫最近 8 周，约 7 秒；全量约 4 分钟。

### 状态与时间口径

- `lastReadDate` 用周扫描的 `lastSeen`（周级近似）。**不要用 `getprogress.updateTime`**：实测离架书有 4 本返回当天、27 本与最后阅读相差 >365 天，不可信。
- 状态：笔记库 `markedStatus=1` 或 `progress=100`/有 `finishTime` → 已读；其余为「读过」。离架已读书的 progress 可能停在 52/92，不强制归 100。
- 私密标记：离架书无 `secret` 字段，无法判断，公开前需用户确认。

### 页面与文件

- `layouts/page/reading-history.html` + `content/page/reading-history/index.md`；搜索、年份、分批 60、空状态、重置、URL `?year=`。
- 共享样式抽到 `layouts/partials/reading/styles.html`，两个页面复用。**坑：partial 放在 `<style>` 内必须加 `| safeCSS`，否则 Hugo 输出 `ZgotmplZ`，整页无样式。**
- 主阅读页 hero 增加「历史阅读 452 本」入口（`site.Data.history.count`）。
- `.github/workflows/weread-sync.yaml` 增加 history 步骤，提交 `books.json` + `data/history.json`。

### 验证

- Hugo `-e stack` 构建通过；历史页 452 卡片、60 分批、年份 2023 筛出 246、搜索/空状态/重置正常，0 JS 错误；暗色与 390px 移动端正常。
- 顺带修复两个样式问题：① `.prog .fill` 的 `--c` 未在卡片上定义，进度条一直透明；② `.card` 未设 `min-width:0`，最长作者名把移动端网格撑宽 71px。
- 局限：每周前 10、过滤 <5 分钟，非完整历史；剩余约 300 本（短阅读/第 11 名以后）只能手动补录或申请个人数据副本。

---

## 十六、2026-10-18 02:15：历史数据并入主页面（删除独立历史页）

### 设计

用户要求整合。合并方案：

- **历史中「已确认读完」的书并入「已读」分类**（`status=="finished"` 的 39 本），已读从 9 → 48。
- 其余 413 本成为**第五个分类「历史阅读」**（紫色系 `--c-history`），卡片带「已移出书架」角标与最后阅读时间，进度 >0 时显示进度条。
- 去重：按 `title|author` 与书架比对（当前 0 重名，仍保留防护）。
- 统计卡 5 列（移动端 2 列，奇数最后一张跨 2 列）；tab、年份、搜索、分批、URL 状态全链路共用；`?status=history&year=2023` 可直链。
- **删除** `layouts/page/reading-history.html` 与 `content/page/reading-history/`；`data/history.json` 保留为数据源。

### 模板要点（layouts/page/reading.html）

- 书架数据先建 `$shelfKeys`（title|author 集合），历史循环里 `continue` 跳过重名。
- 历史条目 `dict "src" "history"`，年份口径：已读=finishDate（回退 lastReadDate），其余=lastReadDate。
- `STATUSES` 数组加 `'history'`；空状态条件改为 `and (not $books) (not $history)`。

### 验证

Playwright：五 tab（38/48/130/255/413）、已读 2023 年筛出 8 本、历史+2023 联动 237 本、URL 带双参数、重置回在读、暗色历史徽章 `rgb(179,157,208)`、390px 溢出 0、0 JS 错误。884 张卡片。
