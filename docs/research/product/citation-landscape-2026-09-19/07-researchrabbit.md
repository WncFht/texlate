# Research Rabbit 逆向调研

ResearchRabbit（researchrabbit.ai）是文献发现赛道里「迭代式引用链」路线的代表产品：用户给若干种子论文，系统沿引用网络逐层扩张候选并按「连接度」打分排序，配合引用地图可视化与文献夹管理，形成「搜索→挑新结果→再搜」的循环（官方自称 follow your curiosity，媒体俗称 "Spotify for papers"）。本轮调研做了官网/帮助文档取证 + `app.researchrabbit.ai` 前端 bundle 与 API 端点实测（2026-09-19，以下标「实测」者均为当日 curl/解析所得）。

## 背景与公司沿革

ResearchRabbit 2021 年创立于美国西雅图（注册地址 4730 32nd Ave S），创始人为 Michael Ma，联合创始人兼首席设计官 Ben Slater，法人实体别名为 Human Intelligence Technologies Incorporated[^cbinsights][^linkedin]。2022 年 6 月完成一轮早期风投（PitchBook 记录，金额未披露）[^pitchbook]。产品早期以「免费、无广告、不卖数据」为卖点在学术圈口碑传播，用户规模宣称 100 万+。

2025 年 5 月 8 日，新西兰惠灵顿公司 Litmaps 宣布收购 ResearchRabbit，并同时宣布完成 100 万美元融资的首关（约 NZ$680K，由英国 Scholarly Angels 领投，领投人 Andrew Preston 为 Publons 创始人）。官宣口径为「合并后用户超 200 万、Litmaps ARR 翻倍至约 $1M」[^scoop][^itbrief]。收购后 Litmaps 联合创始人 Axton Pitt 出任 ResearchRabbit CEO，官网页脚版权已变为 `© 2026 Litmap Ltd`（实测）。团队 2026 年 1 月自述为 9 人小团队、全球分布式（新西兰+美国）[^env]。

2025 年 10 月，产品做了史上最大改版（10 月 15 日公告、10 月 20–30 日间上线，官方 releases 页标记 "Welcome to the new ResearchRabbit October 20, 2025"），旧的多列卡片迭代界面被单视图「rabbit hole」流程取代[^releases][^aarontay]。

## 数据源（官方明示）

帮助文档直接写明了数据底座，透明度在同类产品中罕见[^db]：

- 规模为 **3.1 亿+ 文献条目**（同一文档旧版写 270M+，已更新为 310M+；首页亦宣称 310 million），来自**三家数据商：Crossref、Semantic Scholar、OpenAlex**。
- 只索引具备 **Open Access Metadata**（标题/作者/日期/摘要/参考文献与被引）的条目——闭源但元数据开放的付费墙文章也在库内；元数据不开放的条目无法入库，这是官方给出的缺文主因。
- **每周更新**；同一作品多版本时「优先最新、被引最高的版本」。
- 聚合口径覆盖 PubMed、arXiv、bioRxiv、medRxiv，并经由数据商间接覆盖 Web of Science、Scopus、Microsoft Academic Graph 的来源文献；官方引用 Gusenbauer 2022 年 Scientometrics 研究自证 S2 覆盖面为 56 库中第二[^db]。
- 引文缺失的解释口径：与 Google Scholar 计算口径不同、对端条目无 OA metadata、新文/新引延迟、版本 DOI 不同[^db]。

## 推荐算法（官方披露的完整链路）

ResearchRabbit 在帮助文档里把算法讲到了「可复现轮廓」的程度[^algo][^how][^ai]：

### 两段式结构

每次搜索以**种子论文（seed articles，免费档 ≤50、付费档 ≤300）**为输入，算法分两阶段：

1. **候选集选择**——不搜全库，只取与种子「connected」的候选。connected 的定义按官方原文包括四类：
   - 直接引用关系（一方引用另一方）；
   - 共享 reference（即文献耦合 bibliographic coupling）或共享 citation（即共被引 co-citation）；
   - 共享作者/合著关系；
   - 标题/摘要语义相似推断出的连接（这是 2025 改版新增的语义通道）。
   候选集可达数十万量级。
2. **候选排序**——按与整个种子集的 connectedness 打分，因子同样混合「共享引用/被引 + 作者/合著 + 语义相似」，外加官方称为 "complex mathsy stuff" 的归一化项防止条目被不公平提升/压低。排序参数对用户固定不可调。

另一篇文档补充：推荐倾向「在引用网络中最具影响力的文章，影响力同时来自引用数量与质量」——即带质量加权的图重要性度量，而非裸被引计数[^how]。官方 AI 声明明确：**核心推荐不用 LLM**，用的是「一度与二度连接的 network-based 算法」「graph mathematics、old-school server infrastructure、a little bit of pre-processed magic」——即预计算图结构 + 轻量在线打分[^ai][^env]。

### 用户可调的旋钮

Search Settings 里候选集来源可选：Articles 三模式 **Similar / References / Citations**；Authors 两模式 **These Authors / Other Related Authors**（后者先在 Similar 通道找相关文、再取它们的作者）[^algo]。Advanced（RR+ 付费档）过滤项：关键词（题录/摘要松散匹配、无布尔）、发表日期区间、SJR 分区、期刊 H 指数区间、必须有 OA PDF、撤稿状态（仅撤稿/排除撤稿）[^algo][^aarontay]。

第三方评测（图书情报博主 Aaron Tay，对 2025 改版做了逐功能拆解）推测：Similar 通道大概率是标题/摘要 embedding（Litmaps 侧公开用 SPECTER 系语义检索，RR 侧未确认）；引用/被引通道是直接引用链遍历；共被引与文献耦合是否参与 Similar 打分他无法确认[^aarontay]。本报告按官方「四类 connected」口径采信「参与候选」，具体权重未验证。

## 产品形态（2025-10 改版后）

### 核心交互：rabbit hole 迭代链

搜索以 session 为单位（API 对象 `search-sessions/{id}/steps/{n}`，实测于 bundle）：每点一次「Find Related Articles / Search」生成一个新 iteration checkpoint；Similar/References/Citations 三模式切换作用于「当前 iteration 的输入集」、不生成新迭代；从旧 checkpoint 重新搜索会开一个 branch 并清掉其后的 future iterations；关闭 session 时引导把挑选结果批量存入 collections[^aarontay]。未登录也有 quickstart 体验流（bundle 常量 `QUICKSTART_ARTICLE_LIMIT=20`、最短加载 8s，实测）。

### 引用地图可视化

内置 citation map：默认 x 轴=发表年份、y 轴=被引数（对数刻度可选）、节点间箭头=引用方向；x/y/节点尺寸三个轴均可在被引数/参考文献数/发表日期间切换[^aarontay]。Litmaps 侧可视化轴更多（momentum、map connectivity），被定位为整合后互补[^aarontay]。

### 文献夹与外部集成

- Collections：持久彩色编码文献夹，无限量；library 与 folders 体系，支持 folder 共享协作（`/folder-shares`、`/folder-memberships` 端点，实测于 bundle）。
- 导入：BibTeX/RIS/CSV 文件（官方文档点名 Zotero、Mendeley、EndNote、Paperpile 导出格式兼容）；**Zotero Importer** 走 OAuth 授权后按 Zotero collection 单向拉入；旧版双向同步在 2025 改版中移除，官方称双向同步功能开发中[^zotero]。
- 导出：BibTeX 回导 Zotero[^zotero]。
- `/articles/pdf-parse` 端点存在（实测于 bundle），即上传 PDF 解析入库的路径。
- 另有 notes、readings/batch、evaluations、projects（RR+ 多项目隔离）等辅助对象（bundle 端点，未逐一实测语义）。

### 研究诚信：Signals 集成

付费档卖点之一是 "Signals alerts"——Signals 是第三方研究诚信公司 research-signals.com 的产品（Signals Data Graph：撤稿、自引率、幻觉参考文献、tortured phrases、AI 滥用等 30+ 检查项），2025 年 8 月宣布与 Litmaps/RR 系合作，在文献网络中嵌入诚信评估徽章[^signals]。前端 bundle 中有 `open-signals-report`、`signals-dismissed`、"View Report in Signals" 字样与撤稿过滤组件（实测）。撤稿过滤本身是候选过滤项之一（付费档）。

## 技术栈逆向（实测）

### 前端

`app.researchrabbit.ai` 为 Vite 打包的 React SPA（`/assets/index-*.js` 单 bundle 约 3.2MB，实测 2026-09-19 下载解析）：React + styled-components（`withConfig(displayName:)` 签名）+ **d3**（111 处引用，图布局应基于 d3-force）+ SWR 数据获取 + moment 日期库；`sigma` 字样仅 5 处、权重低，未采信 sigma.js。营销主站 www.researchrabbit.ai 是 Webflow 站点（实测页面指纹 `*.webflow.shared.*.css`）。客服 Intercom（Fin widget + `/intercom/tokens/signed` 端点），分析 Mixpanel，注册验证码 reCAPTCHA（google recaptcha + 国内可达的 recaptcha.net 域），国家差异化定价用 ParityDeals API。

### 后端与 API

API 基座 `https://api.researchrabbit.ai`（实测）：

- `/health` 免鉴权返回 `Everything's great!`（200）；`server: ResearchRabbit Service`，经 AWS **CloudFront** 分发（`x-amz-cf-pop: HKG54-P1`、`x-cache: Miss from cloudfront`）。
- **后端是 Swift**：`POST /users/login` 传空体的报错为 `No such key 'email' at path ''. No value associated with key CodingKeys(stringValue: "email", intValue: nil)`——`CodingKeys` 是 Swift Codable 解码错误签名，服务端应为 Vapor/Hummingbird 系（实测，2026-09-19）。
- 错误格式统一 `{"error":true,"reason":"..."}`；401/403/404 语义分明（`/searches` 401、`/search` 404、`POST /users` 无 reCAPTCHA 403）。
- 认证：邮箱密码（`/users/login`）+ Google OAuth（`POST /users/oauth-sign-in {idToken}`，实测于 bundle）；Bearer token + `GET /users/refresh-token` 续期；2026-07-08 后注册账号强制邮箱验证（bundle 常量 `requireVerificationMoment`）。

bundle 提取到的端点面（字面量，未逐一探活）：`/searches`、`/search-sessions[/steps]`、`/articles/{id}`、`/articles/batch`、`/articles/pdf-parse`、`/authors/batch`、`/user-articles/batch/{create,delete,patch}`、`/user-authors/{id}`、`/edges/between`（图边查询）、`/folders`、`/folders/batch-queries/update`、`/folder-shares`、`/folder-memberships`、`/folder-share-invites`、`/notes`、`/readings/batch`、`/evaluations`、`/projects`、`/library`、`/zotero/request-tokens|access-tokens`、`/oauth-tokens`、`/subscriptions/{checkout-session,prices,products}`、`/users/{login,oauth-sign-in,me,refresh-token,stripe-customer-portal}`、`/password-resets`、`/verifications`、`/intercom/tokens/signed`、`/components`（404）。**全部业务端点需登录**，无公开查询 API——与 alphaXiv 全裸 REST 面相反，ResearchRabbit 的图数据零公开面。

## 商业模式

| 档位 | 价格 | 要点 |
| --- | --- | --- |
| Free | $0 永久 | 无限次搜索 310M 库；无限 library/collections；种子 ≤50 篇/次搜索；基础搜索设置；可共享 collection |
| ResearchRabbit+ | $10/月（年付）或 $12.5/月 | 种子 ≤300 篇；高级搜索控制（关键词/日期/SJR/H-index/OA/撤稿过滤）；多 projects；Signals alerts；优先客服；ParityDeals 国家折扣码 |
| Institution | 询价 | LibKey 图书馆集成、批量用户管理、用量统计、专属支持 |

（来源：pricing 页实测 2026-09-19[^pricing]）。官方自我定位「the only free AI research tool available worldwide」，并把按国家购买力定价作为全球公平性承诺[^about]。

## 收购后与 Litmaps 的整合方向

已可见的整合：Litmaps 视觉语言进入 RR（彩色 collections）；RR bundle 内直接链 docs.litmaps.com 帮助文；Signals 徽章同时挂两边；Aaron Tay 评测口径下两者定位互补——RR 强在迭代链交互、Litmaps 强在可视化/过滤与 "momentum" 类指标轴[^aarontay]。功能迁移有取舍：旧版多列并行视图被单视图取代（官方认为更清爽、Aaron Tay 认为 checkpoint 触发不够直觉）；Zotero 双向同步暂时回退为单向导入[^aarontay][^zotero]。双方独立域名与产品并存，未见合并为单站的公开计划（未验证是否有 roadmap）。

## 可复制性评估

- **数据层**：RR 的三源聚合（Crossref+S2+OpenAlex）全部是公开可得数据，310M 量级基本是 OpenAlex 全库规模；引文边=OpenAlex `referenced_works` + S2 `references/citations` + Crossref 开放引用，自建无授权障碍。其「只索引 OA metadata」的口径实为合规免责声明，自建者可同样照用。
- **算法层**：候选=种子的一/二度引用邻域 ∪ 文献耦合 ∪ 共被引 ∪ 合著 ∪ 标题/摘要语义近邻；排序=多因子 connectedness 加权 + 归一化。整链无 LLM、无黑盒——是「图遍历 + 打分」的经典工程，算法本身零壁垒；壁垒只在候选集动辄数十万时的**预计算图与服务化遍历能力**（官方自述 "pre-processed magic"）。
- **工程层**：Swift/Vapor 单体 + CloudFront + d3-force 前端是朴素组合；搜索 session/step 的对象模型（checkpoint/branch/fork 语义）是交互设计上的真正资产，值得照抄。
- **生态位参考**（Aaron Tay 横向评）：迭代引文链选 RR、可视化过滤选 Litmaps、单种子快速成图选 Connected Papers、系统综述透明选 citationchaser[^aarontay]——做完整形态应把四者能力面合并。
- **风险点**：官方未披露语义相似的具体 embedding 模型（未验证）；共被引/耦合在 Similar 打分中的权重未披露（未验证）；「quality of citations」的具体度量未披露（疑似 PageRank/被引量加权，未验证）。

## 探针产物

scratch 目录 `tmp/citation-survey/researchrabbit/`：`landing.html`、`about-us.html`、`pricing.html`、`features.html`、`help_guide.html`、`releases.html`、`articles.html`（官网页快照）、`article_12454605.html`（数据库文档）、`article_12875619.html`（搜索算法文档）、`article_12454660.html`（工作原理文档）、`article_13545485.html`（AI 声明）、`art_13545441.html`（工程/环保声明）、`art_12796541.html`（Zotero 集成文档）、`art_12454538.html`、`art_12454547.html`（Similar/Later Work 教程）、`app_landing.html`（SPA 入口）、`app_index.js`（3.2MB 前端 bundle 原件，端点与组件指纹均出自此文件）。

### 参考文献

[^cbinsights]: CB Insights. ResearchRabbit - Products, Competitors, Financials. CB Insights. [cbinsights.com](https://www.cbinsights.com/company/researchrabbit)
[^linkedin]: LinkedIn. ResearchRabbit company profile. LinkedIn. [linkedin.com](https://www.linkedin.com/company/researchrabbit)
[^pitchbook]: PitchBook. ResearchRabbit 2026 Company Profile. PitchBook. [pitchbook.com](https://pitchbook.com/profiles/company/494010-37)
[^scoop]: Scoop Business. NZ Startup Litmaps Acquires US Rival And Raises $1M To Accelerate AI-Driven Research Worldwide. Scoop 2025. [scoop.co.nz](https://www.scoop.co.nz/stories/BU2505/S00127/nz-startup-litmaps-acquires-us-rival-and-raises-1m-to-accelerate-ai-driven-research-worldwide.htm)
[^itbrief]: ITBrief. Litmaps acquires ResearchRabbit, raises $1 million for AI. ITBrief 2025. [itbrief.co.nz](https://itbrief.co.nz/story/litmaps-acquires-researchrabbit-raises-1-million-for-ai)
[^env]: Nathan. Environmental impact and how we work. ResearchRabbit Guides 2026. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/13545441-environmental-impact-and-how-we-work)
[^releases]: ResearchRabbit. Releases. ResearchRabbit. [researchrabbit.ai](https://www.researchrabbit.ai/releases)
[^aarontay]: Aaron Tay. ResearchRabbit's 2025 revamp: iterative chaining without the clutter. Substack 2025. [aarontay.substack.com](https://aarontay.substack.com/p/researchrabbits-2025-revamp-iterative)
[^db]: Digl. The ResearchRabbit Database. ResearchRabbit Guides 2026. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/12454605-the-researchrabbit-database)
[^algo]: Digl. What's behind ResearchRabbit's search algorithm?. ResearchRabbit Guides 2025. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/12875619-what-s-behind-researchrabbit-s-search-algorithm)
[^how]: Digl. How does ResearchRabbit work?. ResearchRabbit Guides 2025. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/12454660-how-does-researchrabbit-work)
[^ai]: Nathan. How ResearchRabbit uses AI. ResearchRabbit Guides 2026. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/13545485-how-researchrabbit-uses-ai)
[^zotero]: Digl. Using the Zotero Importer. ResearchRabbit Guides 2026. [learn.researchrabbit.ai](https://learn.researchrabbit.ai/en/articles/12796541-using-the-zotero-importer)
[^signals]: Signals. Signals Announces Innovative Research Integrity Badge and Key Partnerships. Signals 2025. [research-signals.com](https://research-signals.com/2025/08/21/badge-announcement/)
[^pricing]: ResearchRabbit. Pricing. ResearchRabbit. [researchrabbit.ai](https://www.researchrabbit.ai/pricing)
[^about]: ResearchRabbit. About Us. ResearchRabbit. [researchrabbit.ai](https://www.researchrabbit.ai/about-us)
