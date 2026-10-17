# 阅读板块使用说明

阅读页（`/reading/`）的数据来自微信读书 Agent API，在**构建期**生成静态数据，浏览器端不接触密钥。

## 一次性配置

1. 获取 API Key：<https://weread.qq.com/r/weread-skills> → 微信扫码 → 「快速配置 → 获取 API Key」，复制 `wrk-` 开头的字符串。
2. 注入环境变量，**不要写进仓库**：

   ```powershell
   # PowerShell（当前会话）
   $env:WEREAD_API_KEY = "wrk-xxxxxxxx"
   ```

   ```bash
   # bash / Git Bash
   export WEREAD_API_KEY=wrk-xxxxxxxx
   ```

3. 在 GitHub 仓库 `Settings → Secrets and variables → Actions` 添加 `WEREAD_API_KEY`，供定时任务使用。现有部署还需要 `TOKEN`（已配置）。

## 日常同步

```bash
py scripts/weread/sync.py      # 书架四分类数据
py scripts/weread/history.py   # 书架外历史阅读（增量回扫最近 8 周）
```

- 首次全量约 40 秒（490 本逐书拉进度），之后走缓存约 3 秒。
- 只写 `content/page/reading/books.json` 与 `data/history.json`，不碰其他文件。
- 输出会打印自检行，例如 `条目 432 = 想读 130 + 在读 293 + 已读 9 ✓`，三数之和必须等于条目数（页面上的「准备读」是模板按 180 天规则从「在读」里再拆出来的）。

常用参数：

| 参数 | 作用 |
|------|------|
| `--full` | 忽略缓存，全量重拉 |
| `--include-secret` | 包含私密书籍（默认过滤） |
| `--dry-run` | 只统计不写文件 |

`history.py` 的参数：

| 参数 | 作用 |
|------|------|
| `--full` | 从注册日按周全量回溯（首次用，约 4 分钟） |
| `--weeks N` | 增量回扫周数，默认 8 |
| `--refresh` | 强制重拉书目与进度 |
| `--dry-run` | 只统计不写 `data/history.json` |
| `--limit N` | 只处理前 N 本（调试） |

## 数据口径

| 分类 | 判据 |
|------|------|
| 已读 | 书架 `finishReading == 1` 或进度 100% |
| 在读 | 未读完，但进度 > 0 或累计阅读时长 > 0，且最近 180 天有阅读 |
| 想读 | 从未开始 |
| 准备读 | 在读但超过 180 天无阅读记录（模板按构建日自动重算） |

- 已读的书进度统一显示 100%，读完时间优先取 `finishTime`。
- 开始时间优先取 `startReadingTime`，缺失时回退到最早笔记时间，都没有则不显示（不伪造）。
- 每类按「更新时间」倒序：已读取读完时间，在读取最近阅读时间，想读取入架/更新时间。

## 历史阅读（书架外）

微信读书 App 的「读过 1298 / 读完 116」是历史口径，而 `/shelf/sync` 只返回当前书架。`history.py` 通过 `/readdata/detail?mode=weekly` 按周回溯「当周读得最多的前 10 本书」，再合并笔记库、补全书目与进度，数据写入 `data/history.json`。

页面展示上已并入主阅读页：

- 可确认读完的历史书并入「已读」分类；
- 其余进入第五个分类「历史阅读」（带「已移出书架」角标）；
- 分类、年份、搜索、URL 直链全部共用一套交互。

- 首次全量：349 周、约 4 分钟，得到 452 本书（其中 39 本可确认读完）。
- 之后增量：只回扫最近 8 周，约 7 秒。
- CI 没有本地缓存时，会从已发布的 `data/history.json` 恢复基线，不会每天全量重扫。
- 局限：每周只取前 10 本、过滤阅读不足 5 分钟的书，因此**不是完整历史**；离架书的进度/读完时间可能缺失，最后阅读时间是周级近似。
- 私密标记：离架书没有 `secret` 字段，无法判断是否私密，展示前请自行确认。

## 手工短评

微信读书接口没有稳定的「整本书短评」字段（`/review/list/mine` 返回的都是章节点评）。需要短评时编辑 `content/page/reading/reviews.manual.json`：

```json
{
  "3300043489": { "text": "雪国的冷与美，读完像从一场雪里走出来。", "date": "2026-10-01" },
  "伊豆的舞女": { "text": "也可以直接用书名，bookId 优先。" }
}
```

- 键可以是 `bookId` 或书名。
- 以 `_` 开头的键是说明字段，不会被当作短评。
- 每次同步都不会覆盖这个文件。

## 更新机制

| 方式 | 触发 |
|------|------|
| 手动 | 本地跑同步脚本后提交 `books.json`，推送触发 `hugo_deploy.yaml` |
| 定时 | `.github/workflows/weread-sync.yaml`，每天北京时间 03:00 |

定时任务在同一个 workflow 里完成「同步 → 构建 → 部署」，因为用 `GITHUB_TOKEN` 推送的提交不会触发另一个 workflow。同步失败时只发警告，继续用上一次的数据构建，页面不会空白。

## 故障处理

| 现象 | 处理 |
|------|------|
| 页面显示「阅读数据尚未同步」 | `books.json` 缺失或损坏，重新运行同步脚本 |
| 同步退出码 3 | 没有 `WEREAD_API_KEY`，按上面的方式注入 |
| 提示「服务端要求升级 skill」 | 提高 `WEREAD_SKILL_VERSION` 环境变量后重试 |
| 大量 499/429 | 接口限流，脚本已自动退避；稍后重试或减少并发 |
| 封面显示书名首字 | 封面加载失败，属正常降级，不影响布局 |

## 文件结构

```
scripts/weread/
├─ client.py     # 鉴权、请求、重试、限流
├─ cache.py      # 增量缓存（.cache/weread/，已 gitignore）
├─ build.py      # 状态推导、短评合并、排序、校验
├─ sync.py       # 书架同步 CLI
└─ history.py    # 书架外历史回溯 CLI

content/page/reading/
├─ index.md              # 页面 front matter（不动）
├─ books.json            # 同步产物
└─ reviews.manual.json   # 手工短评

data/history.json                    # 历史阅读数据源（并入主页面）
layouts/page/reading.html            # 阅读页（五分类：在读/已读/想读/准备读/历史阅读）
layouts/partials/reading/styles.html # 共享样式
.github/workflows/weread-sync.yaml   # 定时同步 + 部署
```
