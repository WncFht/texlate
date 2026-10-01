# alphaXiv 逆向调研报告

> **结论**：alphaXiv 的公共 REST 面几乎完全无鉴权，社区 SDK 已把端点枚举干净；其 overview「翻译」是多语言再生成而非 PDF 重编译，与 texlate 路线不同；references 解析器与 per-language 状态机是可借鉴的成熟设计。
> **状态**：时点证据（2026-09-19 口径）——逆向结论是对第三方服务的时点观察，仅供互操作参考，服务端状态随时会变。
> **日期**：2026-09-19

对 https://www.alphaxiv.org/ 做了一轮「网络调研 + 直接探针 + 前端抓包」三层逆向。结论：**逆向成本极低**——其公共 REST 面几乎完全免鉴权开放，社区已有成型的 Python SDK 把端点枚举干净，前端 bundle 泄露了从实验开关到模型清单的大量内部信息。唯一需要账号的是写操作与 AI assistant 链路（API key `axv1_...` 或 session cookie）。

## 公司背景

alphaXiv 是斯坦福本科生 Rehaan Ahmad 与 Raj Palleti 的课设项目（导师 Sebastian Thrun），最初形态是「把 arXiv URL 里的 arxiv 换成 alphaxiv 就能在论文上逐行评论」的论坛[^telescoper][^ironside]。现已演进成论文讨论 + AI overview/翻译/播客 + assistant 问答 + 文献库 + wiki 的综合平台，有 iOS 应用（app-id 6782411985）与官方 MCP server[^axmcp]。

## 架构画像

### 前端

React 19 + TanStack Router/Start 全栈 SSR（流式 `$R[...]`/`$_TSR` 脱水数据块，论文页 SSR 直接内嵌完整聚合：metadata、AI summary、评论树、citations、figures），rolldown-vite 打包（Rust 版 Vite），React Query + 自研 `live-query` WebSocket 层，KaTeX 渲染，自带 pdf.js 资产做阅读器，PostHog 做分析 + 实验开关，better-auth 1.6.23 客户端，Google One-Tap/FedCM 登录 + 邮箱 OTP。源码 map 未发布（404）。

### 边缘与后端

Cloudflare 全代理（h3、cf-cache-status、nel 上报），响应头带 `version: <git sha>`、`ratelimit: 1500000/h`（极宽松）。`api.alphaxiv.org/` 返回 "Dreaming is free" 彩蛋页。后端错误信息直接泄漏 zod schema（feed 接口枚举值、WS 频道参数 UUIDv7 校验都是这么探出来的），说明服务端是 TypeScript/zod 系。ID 体系：arXiv ID 为 `universal_paper_id`；`paper_group`（跨版本聚合）与 `paper_version`（每版一条，`version_label: vN`）均为 UUIDv7。

### 资产域（全部无鉴权 CDN）

| 域                                                                                    | 内容                                            |
| ------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `pdfs.assets.alphaxiv.org/{id}v{n}.pdf`                                               | 论文 PDF（必须带版本号，如 `1706.03762v7.pdf`） |
| `thumbnails.assets.alphaxiv.org/{64,256,512,768,1024}/{uuid}.avif` 与 `/{id}v{n}.png` | 首页缩略图                                      |
| `paper-assets.alphaxiv.org/figures/{id}v{n}/...`                                      | 从 LaTeX 源抽出的论文插图                       |
| `paper-podcasts.alphaxiv.org/{pgid}/podcast.mp3` `.../transcript.json`                | AI 播客音频与 transcript                        |
| `user.assets.alphaxiv.org`                                                            | 头像/机构图标                                   |
| `proxy.assets.alphaxiv.org`                                                           | 外部图片代理                                    |

## 协议面（四层）

### 1. REST:`api.alphaxiv.org`

以下全部实测过（除标注 auth 的外均**无需任何凭证**，CORS 固定回 `allow-origin: https://www.alphaxiv.org`，浏览器侧第三方被挡、服务端随意调）：

| 端点                                                                        | 实测结果                                                                                                                                                               |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /papers/v3/legacy/{arxivId}`                                           | 主聚合：paper_version+paper_group+authors_v2+verified_authors+organization_info+**完整评论树**（1706.03762 实测 200）                                                  |
| `GET /papers/v3/{id}` `/preview`                                            | 单版本/紧凑元数据；`GET /papers/v3/previews?ids=u1,u2` 批量                                                                                                            |
| `GET /papers/v3/{pvid}/full-text`                                           | **逐页抽取文本** `[{pageNumber,text}]`——他们 PDF 理解的底座                                                                                                            |
| `GET /papers/v3/{pvid}/overview/{lang}`                                     | **AI overview 多语言版**：翻译标题/摘要 + 完整 markdown 中文博客 + summary 六件套 + 带 justification 的相关引用                                                        |
| `GET /papers/v3/{pvid}/overview/status`                                     | 翻译状态机：12 语言（en/zh/ja/ko/de/es/fr/hi/ru/tr/bg/ro）各自 state/requestedAt/updatedAt                                                                             |
| `GET /papers/v3/{id}v{n}/references`                                        | **结构化参考文献**：每条带 PDF 页内坐标 (page,x,y)、label、原文 text、解析出的 arxivId/paperGroupId，`resolverVersion: 5`                                              |
| `GET /papers/v3/{pvid}/abstract-citations`                                  | 摘要页引用                                                                                                                                                             |
| `GET /papers/v3/{pvid}/ai-detection`                                        | AI 生成检测：fractionAi/Assisted/Human + 逐窗口判定                                                                                                                    |
| `GET /papers/v3/{pvid}/model-links`                                         | 文中模型名链接 sidecar                                                                                                                                                 |
| `GET /papers/v3/{pgid}/figures`                                             | LaTeX 源抽图路径清单                                                                                                                                                   |
| `GET /papers/v3/x-mentions-db/{pgid}`                                       | 社媒提及（不少论文 404）                                                                                                                                               |
| `GET /papers/v3/{pgid}/similar-papers`                                      | 相似论文（对 id 类型敏感，社区标注为 noisy）                                                                                                                           |
| `GET /papers/v3/legacy/{pgid}/comments`                                     | 公开评论流                                                                                                                                                             |
| `GET /search/v2/paper/fast?q=`                                              | 搜索建议（link/paperId/title/snippet）                                                                                                                                 |
| `GET /v1/search/paper?q=`                                                   | 富搜索（summary+metrics+org+repo，单响应 ~187KB）                                                                                                                      |
| `GET /v1/search/closest-topic?input=`                                       | 主题归一                                                                                                                                                               |
| `GET /papers/v3/feed`                                                       | 首页 feed；zod 泄漏 schema：`sort∈{Hot,Comments,Views,Likes,GitHub,ForYou,Recent}`、`interval∈{3,7,30,90 Days,All time}`+pageNum/pageSize；`ForYou` 需登录（401 明示） |
| `GET /organizations/v2/search` `/top`                                       | 机构搜索/榜单                                                                                                                                                          |
| `GET /events/v1`                                                            | 活动列表（实测空数组）                                                                                                                                                 |
| `GET /open-graph/v1/{paper,researcher,organization,folder}/{id}`            | **OG 图渲染服务**，直接吐 PNG                                                                                                                                          |
| `POST /papers/v3/{pgid}/view`                                               | 浏览计数（公开写）                                                                                                                                                     |
| `GET /assistant/v2/url-metadata?url=`                                       | URL→metadata（登录页浏览器直调）                                                                                                                                       |
| `POST /papers/v2/{pvid}/comment`、`POST /comments/v2/{id}/upvote`、`DELETE` | auth：评论/投票                                                                                                                                                        |
| `POST /v2/papers/{arxivId}/versions/{n}/request-ai?preferredLanguage=`      | auth：**触发 AI overview/翻译生成**                                                                                                                                    |
| `GET/POST /assistant/v2*`                                                   | auth：assistant 会话列表、`/chat` SSE、`/{sid}/messages`                                                                                                               |
| `GET/PATCH /users/v3`、`/folders/v3*`、`POST /papers/v3/{pgid}/like`        | auth：用户/收藏/点赞                                                                                                                                                   |

无 swagger/openapi（社区探过全 404）。错误体统一 `{"error":{"message","issues":[zod]}}`，401 一律 `Missing Authorization`。

### 2. WebSocket:`wss://api.alphaxiv.org/live`

自研 pub/sub，文本帧协议极简洁（前端抓包 + 页内注入实测）：

- 订阅：发 `a<channel>;<arg1>;<arg2>`，一行一条可批量；
- 数据帧：`a["<channel>;<args>",<payload>]`（首帧即推当前快照，之后推增量）；
- 错误帧：`b["<channel>",{zod error}]`；
- 前端凭此实现 react-query 的 liveQuery 包装（`raw` 查询 + `liveChannel` 推送合并）。

已确认频道：`paper-podcast;<pgid>`、`ai-overview-v2;<pvid>;<lang>;public`、`ai-overview-status;<pvid>`、`ai-overview-content;<pvid>;<lang>`、`ai-detection;<pvid>`、`abstract-citations`、`paper-comments`、`paper-extras`、`paper-figures`、`paper-resolved`、`paper-version`、`paper-notes`、`assistant-chat`（assistant 流式通道，移动端 `/assistant/v3/chat` 同款）、`assistant-usage;<uuid>`、`user-votes` 等；还有一整套 `admin-*` 频道（agent-trace-tree、assistant-metrics、digest-preview、moderator-feed……）。**overview 生成的进度推送与 assistant 流式输出都走这里**——生成中订阅频道即可实时拉中间态。

### 3. BFF:`www.alphaxiv.org/_serverFn/<id>`

TanStack Start server functions，一等公民 UI 操作的实际执行层；`<id>` 为编译期分配的函数 id（未在静态 bundle 中以字面量暴露，需运行时枚举或从路由 chunk 的 stub 生成器追）。未授权探测返回 `500 HTTPError`（id 不存在即穿透到后端报错）。

### 4. MCP：`api.alphaxiv.org/mcp/v1`（**唯一官方文档面**）

OAuth 2.1 浏览器登录或 `Authorization: Bearer axv1_...`（Settings → API Keys 自助创建，删 key 即吊销）。11 个工具：`discover_papers`（agentic 多轮检索）、`get_paper_content`（默认返回 LLM 优化的 intermediate report，可 `fullText` 取逐页原文）、`answer_pdf_queries`（按查询过滤返回页级 XML）、`read_files_from_github_repository`（读论文 GitHub 仓文件树/内容）+ 7 个 library 文件夹管理。CORS 锁一方来源，浏览器里须 `mcp-remote` 桥[^axmcp]。

### 5. 顺手暴露的导出格式（无鉴权）

`https://www.alphaxiv.org/abs/{id}.md` → 全文抽取文本；`/overview/{id}.md` → intermediate research report markdown；`/$lang/abs/{id}`（如 `/zh/abs/...`）→ 本地化 SSR 页。

## 内容管线（怎么生产出来的）

- **Overview/Blog**：固定模板（TLDR→Problem→Big Idea→How It Works→Formulas→Results→Limitations→Future→Related Papers），图从 LaTeX 源 `\includegraphics` 抽[^obsixiv]；产出 `intermediateReport`（英文分析报告，喂给下游 LLM）+ 各语言 `overview` 成稿。**「翻译」= overview 的多语言生成**，状态机按语言追踪，不是 PDF 重编译——与 texlate 的 ctex 重排版路线完全不同。
- **播客**：Claude 4.1 Opus 写 transcript + gpt-4o-mini-tts 合成，约 $0.50/篇，月产 2.5 万篇[^axpodcast]。
- **检索/问答**：Qwen3-8B 微调的 retrieval agent（工具 `keyword_search`/`semantic_search`/`read_abstract`/`read_page`），GT 标注靠 Sonnet 4.5 + Gemini 3 Flash deep-research agent[^axqa]。
- **Assistant**：前端 bundle 泄漏模型清单——Fast/Smart/Pro 三档映射 `gpt-5.6-sol/terra/luna`、`claude-opus-5`、`claude-sonnet-5`、`gemini-3.8-flash`、`gemini-3.1-pro`、`deepseek-v4.1-flash`、`deepseek-v4-pro`、`kimi-k2.6`、`qwen-3.5`、`minimax-m2.7`、`mercury-2`、`glm-5.3-flash`。实验开关亦明文：`live-assistant-stream`（WS 流式）、`search-decider-jev`（Jev 检索决策模型）、`citation-resolution-v2`（服务端解析引用悬浮）、`for-you-seed`/`hot-slots`（feed 冷启动/热门槽位）、`wiki-tab`、`digest-email-copy`、`feed-card-date-style`。
- **AI 检测**：逐窗口 fraction + "Fully Human Written" 式结论，独立 sidecar。

## 生态与已有工具

- **[petroslamb/alphaxiv-py](https://github.com/petroslamb/alphaxiv-py)**（MIT，9★，2026-07 仍验证有效）：完整端点清单 `docs/api-inventory.md`（本报告 REST 表大量沿用其实测结论）+ CLI；认证支持 `ALPHAXIV_API_KEY` 环境变量与 `alphaxiv auth login-web` 浏览器 cookie 持久化。**直接可用，无需重写**。
- [alphaXiv/OpenResearch](https://github.com/alphaXiv/OpenResearch)（官方，5.3k★，Rust）：本地优先 research agent 工作台（`orx` CLI 包装 Claude Code/Codex 做文献循环），其 assistant 思路的开源姊妹产品。
- [danjuan-77/alphaxiv-skill](https://github.com/danjuan-77/alphaxiv-skill)：Agent Skill 封装，额外暴露 `sota`/`implementations`/`top` 端点；[AlphaClawXiv](https://github.com/Riddhimaan-Senapati/AlphaClawXiv)：MCP→OpenClaw 插件含 OAuth 实现。
- 仿品/同类：[little-alphaxiv](https://github.com/HZHdyzx/little-alphaxiv)（FastAPI+SQLite+React+pdf.js 自托管复刻，Zotero 同步）、[alphaxiv-open](https://github.com/juvu/alphaxiv-open)（FastAPI+markitdown+MiniRAG+Gemini）、[obsixiv](https://github.com/asahium/obsixiv)（Obsidian 插件，可反推 overview 模板）；Explainpaper（高亮解释）、HF Papers（榜单）、SciRate（投票）各占一角，alphaXiv 独占「逐行评论+grounded QA+ 自动 blog」三合一。

## 可行性结论

| 目标                                                     | 难度       | 路径                                                                                    |
| -------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------- |
| 读任意论文元数据/评论/全文/参考/图/AI overview（含中文） | **零成本** | REST 裸调 + `.md` 路由 + WS 快照                                                        |
| 复刻搜索/feed/相似论文/趋势榜                            | **零成本** | 同上，schema 已被 zod 泄漏                                                              |
| 复刻 overview 生成/翻译/播客                             | 低         | 已知 prompt 模板结构 + 公开状态机；生成触发 `request-ai` 需自有账号 key                 |
| 复用其 assistant 问答                                    | 低         | 官方 MCP（free tier 配额）或 `axv1_` key 直调 `/assistant/v2/chat` SSE                  |
| 复刻前端                                                 | 中         | 无 sourcemap，但 SSR 数据全明、协议已破译；直接抄数据层即可                             |
| 拿其全集语料                                             | 低 - 中    | feed/搜索/枚举 arXiv ID 拉 `legacy`+`full-text`+`overview`，1.5M/h 限流够爬，但注意合规 |

对 texlate 的直接价值：①他们的 `full-text` 逐页抽取 + `references` 带坐标解析是 PDF 理解层的成熟参照（尤其 `resolverVersion` 迭代到 v5 说明引用解析是个持续打磨的活）；②`overview/status` 的 per-language 状态机、`live` WS 频道协议、feed 枚举设计可借鉴进 server 端 API 形态；③overview 翻译 ≠ 论文翻译，我们的产品差异点（重编译 PDF）恰好是他们没做的；④若要低成本起步，直接用 `alphaxiv-py` 或其代码模式即可，无需从零下端点。

### 覆盖率实测（2026-09-19，对语料库抽样 45 篇）

alphaXiv 富产物是**头部爆款专属**而非全库资产：随机近年代论文 15/15 有元数据但 references 仅 1/15、overview 0/15、full-text 0/15；OpenAlex 高引热层 15 篇同样 overview 0/15、references 3/15；2007 前 archive 式老 ID（astro-ph/…）0/15 根本未索引。overview/zh/full-text 全靠 `request-ai` 按需生成（auth 门槛），不做预计算。结论：**alphaXiv 只能当机会型增强（命中即免费使用），不能进核心管线当依赖**；引用图要自建——texlate 有 LaTeX 源可抽 `.bbl`/`\bibitem` 边，覆盖率天然好于他们 PDF 侧解析；引用排序用 OpenAlex（免 key）/S2（429 需 key）而非他们的图。

## 生成管线逆向（overview / references / zh 导读）

基于 1706.03762v7 的 en/zh overview 逐字段 diff、overview/status 时间戳、references 负载结构、前端 bundle 的触发逻辑与阶段文案，三条管线的内部结构可以还原到「能照着重实现」的程度。全图见 [2026-09-19-alphaxiv-pipeline.svg](2026-09-19-alphaxiv-pipeline.svg)。

### Overview：三段式

**Stage 0 ingest（共享底座）**：每个 paper_version 拉 arXiv e-print → 逐页抽文本（`/full-text`，`[{pageNumber,text}]`）→ 从 LaTeX 源抽图送 `paper-assets` CDN（overview markdown 里嵌的 `ModalNet-21.png` 就是源 tarball 原文件名）→ 跑 references resolver。这套产物同时供阅读器、搜索、MCP 使用。

**Stage 1 — `intermediateReport`**：LLM 对全文做固定六节的 "Research Paper Analysis"（Authors/Institutions → Broader Landscape → Objectives → Methodology → Findings → Significance），本例 24.9KB 英文。证据：节标题逐字固定；en/zh 负载里字节级相同——**从不翻译**，是给下游模型吃的中间产物而非用户内容；MCP `get_paper_content` 默认返回的 "LLM optimized report" 正是它。这是他们的「论文理解」标准件。

**Stage 2 — `overview` + `summary` + `citations`**：agentic 写作 pass。UI 阶段文案（bundle 明文）：`Preparing AI overview` → `Reading the papers behind the answer` → `Weighing what the results agree on` → `Writing the overview`——"papers behind the answer" 是复数，即生成时会去读相关论文做小型文献综述；另有 admin 频道 `admin-agent-trace-tree` 暴露 agent 调用树。产出三件：① `overview` = **动态结构** blog markdown（本例 7 节、9.5KB，含 `$$` 公式与 paper-assets 插图）——obsixiv 反推出的固定九节模板应是 v1 旧版；② `summary` = 固定字段卡片 {summary, originalProblem[], solution[], keyInsights[], results[], feedDescription}；③ `citations` = 挑选的相关论文，每条带 `justification`（为什么相关）+ `alphaxivLink`（已解析进自家图）。生成全程经 WS `ai-overview-v2;<pvid>;<lang>;public` 直播，`v2` 表明已是第二代管线。

**Stage 3 — per-language 翻译**：逐字段 diff 给出精确的翻译面：`title`、`abstract`、`summary` 五字段、`overview` 全文（含节标题）、`citations[].title`+`justification`、`summarySectionTitles`/`overviewSectionTitles`/`aiTooltips` 界面串。**不译**：`intermediateReport`（字节级相同）、`citations[].fullCitation`、链接与图床 URL。状态机 `translations.<lang>.{state,requestedAt,updatedAt}` 显示：en/ru/de/es/fr/hi/ko 同一秒批（ingest 期批量回填），zh/ja/ro/tr/bg 的请求时间散布数月——**按需懒翻译**；单语言耗时 10–35s（tr 33.6s、ro 15.2s、bg 10.7s），对 ~12KB 输出即一次快速模型调用量级。

**触发逻辑**（bundle 实锤）：overview 已存在 → `POST /v2/papers/{upid}/versions/{n}/request-ai-translation/{language}`；不存在 → `POST .../request-ai?preferredLanguage=`。均 auth；409 = 已请求过；未生成论文上 WS 快照推 null。

### References: resolver v5

`/papers/v3/{id}v{n}/references` 输出 `{status, resolverVersion:5, entries[40], byDestName, byDestPos}`。机制可完整还原：① 从 PDF 定位每条 `\bibitem` 的页内坐标（`page,x,y`——byDestPos 里 y 递减即 PDF 底左原点坐标系）；② 解析原始条目 `text`：正则抓 `arXiv:XXXX`/`abs/XXXX` 显式 id → DOI → 标题匹配自家索引兜底，回填 `paperGroupId`/`universalId`/`arxivId`，标 `reason∈{confirmed,no-candidate}`（本例 22/40 命中 arXiv、31/40 有 universalId、9 条无候选）；③ `byDestName` 把 hyperref named dest `cite.<bibkey>` → entry index，阅读器里点 `[5]` 引用链即查此表弹卡片/跳 alphaXiv 页；④ `byDestPos` 是 `page:x:y`→index 的坐标兜底，覆盖只给矩形不带 named dest 的 link annot。`resolverVersion` 迭代到 5 说明该解析器按版本全量重跑。texlate 的 `align.py` 用同一招 named-dest 锚点同步，印证路线可行。

### 看不到的部分与补全手段

各 stage 的**具体模型与 prompt** 在服务端，不可直接观测。旁证：podcast 管线官方公开为 Claude 4.1 Opus + gpt-4o-mini-tts[^axpodcast]；retrieval agent 是 Qwen3-8B 微调[^axqa]；assistant 菜单 13 个模型说明他们按任务选模型；翻译延迟 10–35s 指向 flash/mini 档。要完全看活：`axv1_` key 对未生成论文调 `request-ai`，同时订阅 `ai-overview-v2` 频道抓流式中间态；`admin-agent-trace-tree` 需管理员权限。生成件无需复刻 prompt：**overview/intermediateReport/references 全是公开 GET**——消费方直接读产物即可。

### 参考文献

[^telescoper]: In the Dark. Introducing alphaXiv. 博客 2024. [telescoper.blog](https://telescoper.blog/2024/03/09/introducing-alphaxiv/)

[^ironside]: Ironside News. AlphaXiv: The New Hub for Open Scientific Dialogue（IEEE Spectrum 对 Rehaan Ahmad 的访谈转述）. 2025. [ironsidenews.com](https://ironsidenews.com/alphaxiv-the-new-hub-for-open-scientific-dialogue/)

[^axmcp]: alphaXiv. MCP Server Documentation. 官方文档。[alphaxiv.org/docs/mcp](https://www.alphaxiv.org/docs/mcp)

[^axqa]: alphaXiv. ArxivQA: Training Retrieval Agents for arXiv Search. 官方博文。[alphaxiv.org/blog/training-retrieval-agents-for-arxiv-search](https://www.alphaxiv.org/blog/training-retrieval-agents-for-arxiv-search)

[^axpodcast]: alphaXiv. Paper Podcasts（Claude 4.1 Opus transcript + gpt-4o-mini-tts，$0.50/篇）. 官方博文。[alphaxiv.org/abs/8e14c70c-14f0-4ce7-b87b-8fa942277c7f](https://www.alphaxiv.org/abs/8e14c70c-14f0-4ce7-b87b-8fa942277c7f)

[^obsixiv]: asahium. obsixiv — Obsidian 仿品，可反推 overview 模板。GitHub. [github.com/asahium/obsixiv](https://github.com/asahium/obsixiv)
