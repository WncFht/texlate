# Litmaps 逆向调研

对 Litmaps（litmaps.com）做了「官网/docs 取证 + 前端 bundle 静态分析 + api.litmaps.com 实探」三层逆向。结论先行：**它本质是一个把 Crossref+Semantic Scholar+OpenAlex 三家开放元数据合并去重后、自建 2.7 亿节点引用图数据库、再以异步 search job 提供「共被引/文献耦合互联度」推荐的服务**——数据管道是主要资产，算法本身直白，API 设计简洁可抄。

## 公司背景

Litmaps 2016 年 6 月创立于新西兰惠灵顿，联合创始人 Axton Pitt（神经科学转软件开发，技术负责人）与 Kyle Webster（分子生物学博士候选人，CEO 角色），第三位联合创始人 Digl Dixon[^dealroom][^medium-origin][^nzherald]。创始初衷是「画一张全科学的地图」（map of all science），实践后转向以 seed 论文为中心的工具化产品[^dealroom]。

2025 年 5 月公司宣布两件事：收购美国竞品 ResearchRabbit，并完成 100 万美元融资首轮关闭（NZ$680K，由英国 Scholarly Angels 领投——其 lead investor Andrew Preston 是 Publons 创始人，Publons 后被 Clarivate 收购）[^scoop][^itbrief]。当时公司 ARR 约 100 万美元、收购后总用户超 200 万（官网此前口径为 35 万+、覆盖 150+ 国家；校友页面称 180+ 国）[^scoop][^landing][^akl-alumni]。后续报道出现 NZD $1.4M 的融资口径，并明确「将把 Litmaps 与 ResearchRabbit 合并为单一平台」[^ecommerce]。

## 产品面

官网把功能归为四块：Discover（发现）、Visualize（可视化）、Share（协作分享）、Monitor（监控提醒）[^landing]。核心对象叫 **Litmap（literature map）**：选一篇或多篇 seed 文章，系统在引用网络上扩张出候选集并绘制成可交互地图。

官方推荐的典型用法是 **Search-Loop**：从 1–2 篇 seed 起步 → 看推荐 → 把相关文章加进输入集 → 重跑使结果更精准，循环至 10–20 篇精选[^linkedin-searchloop]。Monitor 则是在某张 map 上点「Enable Monitor」，系统保存该次的搜索配置（含算法、输入集、过滤器），对每周新入库的文章定期重跑并邮件推送命中结果——bundle 里可见 `monitorFrequency` 枚举与 `/map/{id}/monitor/results` 端点（实测）[^bundle]。

周边生态：Zotero OAuth 同步（`/zotero/createRequestToken`、`/zotero/token/`）、LibKey 机构全文打通（`/articles/libkey`、`/libkey/libraries`）、tag/collection/workspace/team 协作、ORCID 记录查询（`/orcid/record`）、自定义文章（`/customArticle`）、笔记（`/note`）、Intercom 客服[^bundle]。

## 算法：三件套官方披露 + bundle 实锤

docs.litmaps.com 的「Search algorithms in Litmaps」一文明确列出三个可选算法[^docs-algo]，与前端 bundle 内的算法注册表逐字对应（实测，bundle 内部 key 名曝光）：

| key | 展示名 | 官方描述 | 机制推断 |
| --- | --- | --- | --- |
| `shallow` | Shared Citations &amp; References（默认） | 单输入：从该文的 citations、references 与 **co-citations**（官方定义=「references 的引用者」，即文献耦合邻域）中返回最互联的文章；多输入：从全部输入的 citations+references 中返回最互联的 | 一跳扩展 + 图内互联度排序（共被引+耦合混合计数） |
| `authorFiltration` | Common Authors | 分析输入集的共同作者合作模式，返回这些作者组合的其他文章 | 作者面过滤召回 |
| `semantic` | Similar Text | 对输入的标题+摘要做 AI 语义分析找内容相似文章；**唯一不用引用的算法** | embedding/LLM 语义检索 |

bundle 里 `semantic` 算法的说明文字带一句「This technique uses an AI Large Language Model」，官方承认语义路走 LLM[^bundle]。另有一个隐藏模式 `seed`：当输入恰好 1 篇、无过滤器且算法为 shallow 时，前端把算法改写成 `seed`，返回 20 条结果（bundle 逻辑实测）[^bundle]。

辅助排序信号在可视化层暴露为轴选项[^docs-vis]：**Momentum**（被引数按发表新近度调整，带滑杆）、**Map Connectivity**（图内被引数，曾名 Map Relevance）、Cite Count、Ref Count、Publication Date。四种布局：Standard（同图混排）、Ring（推荐外圈/输入内圈）、Side by Side（推荐上/输入下）、By Author[^docs-vis]。

## 数据层（实测出内部结构）

官方 Database FAQ：**270M+ 文章，数据源 = Crossref + Semantic Scholar + OpenAlex 三家合并**，只索引 Open Access metadata（标题/发表日期/摘要/references &amp; citations），不含全文；做去重与版本归并（preprint↔正式版归并到 articleFamily，展示最新且元数据最全版本）；引用数与 Google Scholar 口径不同属正常[^docs-db]。

对 `GET https://api.litmaps.com/article/1` 的实测拿到了内部 record 全貌（2026-09-19）：

```json
{"id":1,"familyId":259553333,"title":"Transitional problems from reform to growth…",
 "forwardEdges":"183588513,264492099,…","forwardEdgeCount":41,
 "backwardEdges":"130635288,276062853,…","backwardEdgeCount":46,
 "openAlexIds":["W1557014962"],"magIds":[1557014962],
 "semanticScholarCorpusIds":[264657486],"dois":["10.1787/267677618887"],
 "arxivIds":[],"pubmedIds":[],"doctype":"report-series","retracted":false,
 "authors":[{"authorIndex":0,"authorPosition":"first","id":26088394,"displayName":"…"}],
 "openAccessUrl":"https://www.oecd-ilibrary.org/…"}
```

可见内部模型：**稠密 int 内部 id；每条 article 直接内嵌 forwardEdges/backwardEdges 两个 id 列表**（forward=被引、backward=参考文献，方向为推断）**+ 一组多源外部 id 映射**（openAlex/mag/s2/doi/arxiv/pubmed）。`/articleFamily/{id}` 返回 `{defaultArticleId, otherArticleIds}` 做版本归并。这是教科书式的「自建引用图服务化」结构——2.7 亿节点、每条记录自带邻接表，REST 直查。

质量面实测：keywordSearch 返回过 Zenodo 垃圾记录（"Post Utme/Masters Form" 之类 SEO  spam DOI、以及同题重复条目），与其 FAQ 承认的去重残留一致——**自建库必须留质量过滤层**。

## 协议面（curl 实测，2026-09-19）

API 基址 `https://api.litmaps.com`。错误体统一 `{"error":true,"reason":"…"}`；解码错误泄漏 **`CodingKeys(stringValue:…)`——后端是 Swift Codable**（疑 Vapor/Hummingbird），403 文案 `{"reason":"Forbidden"}`。

无鉴权可读（实测）：`/health`、`/article/{int}`、`/articleFamily/{int}`、`/author/{int}`（返回 hIndex/orcid/citationCount/articleCount/normalizedNames）、`/keywordSearch?query=`（返回 `{results:[int ids], metadata:{total}}`，fuzzy 全库检索）。

鉴权门（403 Forbidden，实测 `POST /search`）：`/search`、`/map*`、`/monitor/*`、`/user/*`、`/workspace*`、`/collection*`、`/team*`、`/zotero/*`、`/subscription/*`、`/note*`、`/tag*`、`/shares`、`/sync`、`/customArticle*`。

搜索是异步 job 化设计（bundle 实测）：`POST /search?type=&lt;algo&gt;`，body 为序列化 discover config（`{type, algorithm, inputs:[{type:"article",id}], keyword?, dateRange?{min,max}}`）→ 返回 `{id, searchResultId}` → 轮询 `GET /searchResult/{id}?type=&amp;page=1&amp;per=1000` → 组件卸载时 `DELETE /search/{id}?type=` 清理；前端打点「Discover finishes in Xs」。

从 bundle 提取的完整 REST 清单（节选）：`/articles`、`/article/`、`/articleFamily/`、`/articletitles/resolved`、`/authors`、`/author/`、`/collection(s)`、`/map(s)`、`/mapNodes?mapId=`、`/mapLayouts?mapId=`、`/mapGroups?mapId=`、`/mapShare/`、`/search`、`/searchResult/`、`/seed/`、`/explore`、`/multiple/{type}?ids=`（批量）、`/monitor/result(s)`、`/sort`、`/user/*`、`/workspace`、`/team`、`/invite`、`/subscription/*`、`/academicEmail?email=`、`/hiddenArticles`、`/image`、`/content`、`/survey`、`/allowed-error`、`/health`。

限流实测：连续密集探测后 api/app/www 三个域同时 TLS EOF 约数分钟后自动恢复（docs 子域是 Intercom 托管不受影响）——存在 WAF/速率限制，抓取需温和。

## 前端与定价

前端是 Create React App SPA（webpackJsonpclient）：React + styled-components + react-router，reCAPTCHA、Intercom、Hotjar、Rewardful 联盟营销、`api.paritydeals.com` 购买力平价折扣判定[^bundle]。

定价（pricing 页实测）[^pricing]：Free = 月度 literature alerts、basic search、≤20 inputs、每图 100 文章、2 张 Litmaps；Pro = **$10/月**（年付 $120 省 20%，学术邮箱教育价）、daily/可配置 alerts、advanced search、无限 inputs/articles/maps；Team = 团队共享 workspace，询价。另有 100+ 国 LMIC 国家折扣自动发码[^lmic]。

## 可复制性评估

- **数据层是其真正壁垒也是最大工程量**：三家开放源 ingest → 多源 id 对齐去重 → 版本家族归并 → 内嵌边表落库。这套管道等于「重做一个小号 OpenAlex」，但它的 record 结构（内部 int id + 多源 id 数组 + forward/backward id lists）是可直接借鉴的 schema。
- **算法层出奇地薄**：默认算法就是「一跳邻域（citations+references+共被引）里按图内互联度排序」，加作者过滤与语义两个旁路；排序轴就是 cited count、图内被引、时间衰减被引。没有任何神秘成分——任何人拿到引用图都能复刻。
- **API 设计可抄**：异步 search job（POST→searchResultId 轮询）避免长连接；读端点裸开放、写端点 403；`/multiple/{type}?ids=` 批量取数。
- **Monitor 的本质**是把 discover config 持久化、周期性对增量文章重跑再 diff——实现成本低、用户黏性高。
- **教训**：它库里实测到 Zenodo spam 与重复条目混进检索结果——自建库若不做质量门（来源白名单/DOI 前缀过滤/重复归并强度），检索体验会被垃圾数据拖垮。

## 探针产物

`tmp/citation-survey/litmaps/`：`main.chunk.js`（1.5MB 前端 bundle）、`landing.html`、`pricing.html`、`app.html`、`seedmap.html`、`database.html`、`lmic.html`、docs 四篇 `https_docs_litmaps_com_*.html`、`kw.json`，扫描脚本 `scan.py`、`endpoints.py`、`grep_seed.py`、`grep2.py`、`extract.py`。

### 参考文献

[^dealroom]: Dealroom. Litmaps company information, funding &amp; investors. [app.dealroom.co](https://app.dealroom.co/companies/litmaps)
[^medium-origin]: Hamish. The origin of Litmaps and the team. Medium/Litmaps. [medium.com](https://medium.com/litmaps/-8f0dbc87390a)
[^nzherald]: NZ Herald. Wellington start-up Litmaps raises $1m to revolutionise science research. [nzherald.co.nz](https://www.nzherald.co.nz/business/wellington-startup-litmaps-raises-1m-to-revolutionise-science-research/5P4JHNDTQFCD5FBKX7KK2ASI5Y/)
[^ecommerce]: eCommerceNews. Litmaps secures NZD $1.4 million to drive global platform growth. [ecommercenews.co.nz](https://ecommercenews.co.nz/story/litmaps-secures-nzd-1-4-million-to-drive-global-platform-growth)
[^landing]: Litmaps 官网首页与 Features 页（实测 2026-09-19）. [litmaps.com](https://www.litmaps.com/)
[^docs-algo]: Litmaps Docs. Search algorithms in Litmaps（实测 2026-09-19）. [docs.litmaps.com](https://docs.litmaps.com/en/articles/9029858-search-algorithms-in-litmaps)
[^docs-db]: Litmaps Docs. Our database FAQ（实测 2026-09-19）. [docs.litmaps.com](https://docs.litmaps.com/en/articles/7212085-our-database-faq)
[^docs-vis]: Litmaps Docs. Understand research faster visually（实测 2026-09-19）. [docs.litmaps.com](https://docs.litmaps.com/en/articles/9181490-understand-research-faster-visually)
[^bundle]: app.litmaps.com 前端 bundle `main.55b9d000.chunk.js` 静态分析（实测 2026-09-19，本地存档 tmp/citation-survey/litmaps/main.chunk.js）.
[^pricing]: Litmaps Pricing 页（实测 2026-09-19）. [litmaps.com/pricing](https://www.litmaps.com/pricing)
[^lmic]: Litmaps Country Discounts 页（实测 2026-09-19）. [litmaps.com/lmic](https://www.litmaps.com/lmic)
[^linkedin-searchloop]: Litmaps LinkedIn. Search-Loop Method 工作流贴. [linkedin.com](https://www.linkedin.com/posts/litmaps_want-to-use-litmaps-for-your-literature-review-activity-7285391486072897536-xTAj)
