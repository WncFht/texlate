# Inciteful 逆向调研

对 Inciteful（现域名 incitefulmed.com/academic/，旧域名 inciteful.xyz 301 跳转）做了「官方文档研读 + 前端 bundle 反编译 + 生产 API 实测」三层逆向。结论先行：**这是同类产品里架构最透明、也最小而美的实现**——单人开发者 + Rust 后端 + OpenAlex 数据 + 「每次查询物化一个临时 SQLite 库、前端直接发裸 SQL」的激进设计。全部算法（PageRank + Adamic/Adar + Salton 共被引）有官方文档与前端 SQL 模板双重佐证，API 面完全无鉴权且实测可用，是「完全形态引用图谱发现层」最直接的可复制蓝本。

## 公司与作者

Inciteful 由 **Michael Weishuhn** 于 2020 年独立开发上线[^istl]。他是创业者+开发者，更早的身份是教育市场平台 Wyzant 的联合创始人[^substack]。项目缘起写在 About 页（实测提取的原文）：帮做学术的妻子查文献时陷入「Google Scholar → 扫参考文献 → 查被引 → 回 Scholar」的手工循环，意识到自己其实在手绘引用网络，于是动手自动化。

产品演进史（About 页 + 官方文档交叉验证）：第一年形态是「用 OpenCitations / Crossref API 拼凑的 Python notebook」，给一篇只有几十条引用的论文建图要 15 分钟以上；随后学了**Rust**、换了多个数据库、换过数据源、重构数次才达到现在的实时性能[^about]。数据源随之换代：旧官方文档写 MAG（Microsoft Academic Graph）为基底、Semantic Scholar 供摘要、Unpaywall 供 OA 链接、Crossref 供元数据、OpenCitations 供引用边[^data]；**当前实测后端已切到 OpenAlex**（API 命名空间即 `/openalex`，前端直调 `api.openalex.org` 做搜索补全），MAG 早已并入 OpenAlex 谱系。

现状：域名已整体迁到 incitefulmed.com，主线产品是面向消费者的医疗证据产品 Inciteful Med（"Take charge of your health with personalized, evidence-based insights"），学术工具作为 Inciteful Academic/Search 保留在 `/academic/` 路径下免费运营，官方 Substack 宣称约 4 万月活用户[^substack][^casrai]。GitHub 组织 `inciteful-xyz` 下有 6 个仓库：前端 `inciteful-web`（Vue，AGPL-3.0，133 star）、`inciteful-zotero-plugin`（TypeScript，294 star）、`inciteful-mcp`（2026-09 新建的 MCP server，MIT）、`inciteful-academic-docs`（官方文档，MIT）、`inciteful-blog`、`large-graph-analysis`；**图构建与服务后端闭源**[^gh]。

## 产品面（六个工具）

| 工具 | 路由 | 干什么 |
| --- | --- | --- |
| Paper Discovery | `/p/{id}`、`/p/q` | 围绕 seed（支持多 seed）建局部引用图，分栏输出 Similar/Important/Review/Recent 论文榜 + 作者/机构/期刊榜 |
| LitReview | `/array/` | Paper Discovery 的多 seed 强化版（1–500 个 seed，MCP 文档证实上限），迭代式"加 seed→重建图→逼近主题"工作流 |
| Literature Connector | `/p/q`（from/to 参数） | 两篇论文间在**全图**上做双向 BFS 找最短引用路径，可扩展一层；输出路径子图 |
| Einstein | `/einstein` | Connector 的彩蛋版：你的论文离爱因斯坦的论文几跳（"Six Degrees of Einstein"） |
| Search / GraphSearch | `/search` | 题名/DOI/PubMed URL/arXiv URL 检索定位 seed |
| SQL Query Panel | 嵌在各仪表盘 | 对当前图对应的 SQLite 库**直接执行任意 SQL**（power-user 卖点） |

附属面：BibTeX 导入（需 DOI）作 seed、导出 bib/ris；Zotero 插件（官方仓库 294 star）；beta features 开关页；MCP server 暴露 9 个工具（search_papers/get_paper/similar_papers/connect_papers/discover_papers/literature_review/get_abstract/get_full_text_links/get_full_text）[^mcp]。

## 架构画像（实测）

### 前端

Vue 3 SPA（`vendor-vue` chunk），懒加载路由 chunk 按工具命名（`PaperDiscovery-*.js`、`LitReviewQuery-*.js`、`LitConnectorBody-*.js`、`Einstein-*.js`、`QueryPanel-*.js` 等），PostHog 分析 + Sentry 监控，前端 AGPL-3.0 开源。搜索补全与单篇元数据直接调 `api.openalex.org`（`works?search=`、`autocomplete/works?q=`、`works/{id}`，mailto=`hello@incitefulmed.com` 走 polite pool）；引用图相关全部走自家 `graph.incitefulmed.com`。

### 后端：每次查询一个临时 SQLite

最激进的发现：graph API 的 query 端点**接收并执行裸 SQL**。实测：

```
POST https://graph.incitefulmed.com/openalex/query/W2741809807?prune=10000
Content-Type: text/plain

SELECT sqlite_version()        →  [{"sqlite_version()":"3.51.1"}]
SELECT 1                       →  [{"1":1}]
```

行为还原：后端持有全量引用图（OpenAlex 子集）；收到 seed 后实时做图扩展、算指标，把结果**物化成一个独立的 SQLite 库**（缓存 24+ 小时[^pde]）；之后前端所有表格都通过 POST SQL 到这个库来取数——每个表格底部的 SQL 按钮能让用户查看并改写查询[^pu]。服务端会强行追加 `LIMIT 50`（实测我的 `LIMIT 5` 被改写成 `LIMIT 50` 后报错信息里回显）。

实测 dump 出的真实 schema（比官方文档还全）：

```sql
CREATE TABLE papers (
  paper_id TEXT PRIMARY KEY, doi TEXT, authors TEXT, num_authors INTEGER,
  title TEXT, published_year INTEGER, journal TEXT,
  num_citing INTEGER, num_cited_by INTEGER,
  distance INTEGER, page_rank REAL, adamic_adar REAL, cocite REAL
) WITHOUT ROWID

CREATE TABLE authors (
  author_id TEXT, paper_id TEXT, name TEXT, sequence INTEGER,
  affiliation TEXT, affiliation_id TEXT, ror TEXT, published_year INTEGER,
  partial_page_rank REAL, PRIMARY KEY(paper_id, author_id)
) WITHOUT ROWID

CREATE VIRTUAL TABLE title_search USING FTS5(paper_id, search_text,
  tokenize = 'porter unicode61')
CREATE VIRTUAL TABLE all_title_terms USING fts5vocab(title_search, row)
CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)
```

`metadata` 表记录建图参数：实测 `graph_depth=2, paper_count=48496, citation_count=393964`（seed=W2741809807, prune=10000）。FTS 实测可用：`title_search('open access')` 返回 bm25 负分排序、`all_title_terms` 吐 porter 词干词频（"scienc""bibliometr""citat"），即关键词云与关键词过滤的底座。

### API 面（全部实测，无鉴权）

| 端点 | 实测结果 |
| --- | --- |
| `POST /openalex/query/{W-id}?prune={n}` | 单 seed 建图 + SQL 执行。冷启动小图 ~1.3s 回（实测 W4403448164→2431 节点）；48k 节点图 SQL 响应 ~0.7s |
| `POST /openalex/query?ids[]=a&amp;ids[]=b&amp;prune={n}` | 多 seed：实测 distance 0 = 1 个虚拟节点、distance 1 = 2 个 seed、distance 2 = 1600 个前沿节点——与官方"fake node"文档完全吻合 |
| `GET /openalex/paper/{id}?condensed=` | 单篇详情 + **完整 `citing`/`cited_by` ID 数组**（W2741809807 实测：54 出边 + 1214 入边）——这是图遍历原语，单机就能爬全图邻接 |
| `GET /openalex/paper?ids[]=…` | 批量取详情 |
| `GET /openalex/connector?from=&amp;to=&amp;extend={0,5}` | 返回 `{papers(带 distance/path_count), paths, connections[{citing,cited}], num_paths, papers_searched, max_hops}`；实测 papers_searched=52785 找到 1 跳直连 |
| `GET /openalex/export/bib`、`/export/ris` | 导出 |
| `GET /openalex/zotero/auth/initiate` | Zotero OAuth 串联 |
| `b.incitefulmed.com` | 产品侧 API（tours/surveys/feature flags，非图面） |

ID 兼容：OpenAlex `W…`、裸 DOI、`doi:`、`pmid:` 前缀均可（MCP README 证实 PMCID/Inciteful 内部 ID 也行）[^mcp]。注意他们的库是 **OpenAlex 子集**：部分 W-id 在 connector 上返回 `Error: Paper not found`（实测 W2963403869、W2139507971 均无数据），即只收"有引用数据"的论文。CORS 回 `vary: Origin`，无浏览器白名单观察；测试期间未遇到 429，**速率上限未验证**。

## 算法（官方文档 + SQL 模板双重取证）

### 建图

单 seed：以无向边处理引用关系，depth-1 拉全部"引用的+被引的"，depth-2 再扩一层并收层内边。官方口径：典型 depth-2 图 1–2 万篇论文/5–10 万边，最大见过 100 万节点/300 万边（建图要 3–4 分钟）；**depth-2 预计超过 15 万节点就停在 depth-1** 并建议加关键词过滤[^pde]。`prune` 参数实测影响保留规模（prune=0→31332、=100→38258、=10000→48496 节点，语义为裁剪阈值、数值越大保留越多，精确定义未验证）。

多 seed：造一个 cites 全部 seed 的**虚拟节点**（distance 0），seed 们 distance 1、候选池 distance 2；相似度一律相对虚拟节点计算[^pde]。

### 指标

| 指标 | 算法 | 角色 |
| --- | --- | --- |
| 重要性 | **PageRank**（局部子图上迭代） | "重要论文/重要作者/机构/期刊"榜的排序键；作者侧有 `partial_page_rank` 把论文 rank 摊到作者 |
| 相似度（耦合侧） | **Adamic/Adar**：对 a、b 共同引用的每个文献按 1/log（被引数） 加权 | 官方解释：不过度惩罚共同引了热门文献、又奖励共享冷门引用（"共享一个小生态"信号） |
| 相似度（共被引侧） | **Salton 指数**（共被引余弦，分母 √（两者被引数之积）） | 补偿两论文被引规模悬殊 |
| 综述识别 | 图内 `num_citing` 排序（引用图内论文最多的≈综述） | SQL 里带一个 (num_citing, year, journal) 同组 &gt;8 篇即整组排除的去重 hack——剔除共享参考书目的专刊/会议集 |
| 关键词过滤 | 标题 FTS5 porter stem + AND/OR/NOT 布尔查询 | 无摘要，只有标题（官方明说） |

### 前端 SQL 模板（从 bundle 提取的原版查询）

- **相似论文**：`ORDER BY adamic_adar + COALESCE(cocite,0) DESC`（`AND (adamic_adar&gt;0 OR cocite&gt;0)`）
- **重要论文**：`ORDER BY page_rank DESC, adamic_adar DESC`
- **近期重要**：`published_year &gt; now-3 AND … ORDER BY page_rank DESC`
- **活跃学者新作**：先按 `SUM(partial_page_rank)` 取 top-100 作者，再取其近 3 年论文按 `adamic_adar` 排
- **LitReview 的作者加权更精细**：`page_rank / (CASE WHEN num_authors&lt;4 THEN num_authors WHEN sequence=0 OR sequence=num_authors-1 THEN 3 ELSE num_authors*3 END)`——首末位作者按 1/3 计贡献、中间作者按 1/(3·N)
- **新锐学者**：`HAVING MIN(published_year) &gt; now-10` 后按 `SUM(partial_page_rank)` 排
- **机构/期刊榜**：`SUM(page_rank)` 或 `SUM(adamic_adar+cocite)` 分组聚合

### Literature Connector

官方文档：把全图当无向图做**双向 BFS**——两端各逐层扩展、直到前沿相交，交点即最短路径必经之路；只保留最短路径上的点边成图，输出时把边统一改成 source→destination 方向方便布局。`extend` 参数把路径长度上限+1 层（"小图太无聊就多给一层"）。作者声称"还没遇到过连不上的两篇论文"；Einstein 页自述"目前最大 6 跳，诚实讲我没见过超过 5 跳的"[^lcd][^eins]。

## 数据流总览

OpenAlex（引用边+元数据，子集入库）→ Rust 后端（实时图扩展 + PageRank/Adamic-Adar/Salton 计算）→ 每次查询物化 SQLite（papers/authors/FTS/metadata，缓存 24h+）→ 前端 SQL-over-HTTP 取数渲染；检索与摘要补全走 `api.openalex.org` 直连，OA 链接历史上走 Unpaywall、摘要历史上走 S2[^data]。

## 可复制性评估

**这是六七个同类产品里最适合当「完全形态」蓝本的一个**，理由：

1. **算法栈已被完整逆向且有官方文档兜底**：PageRank（重要性）+ Adamic/Adar（耦合相似）+ Salton（共被引）+ BFS distance + num_citing 综述识别——五个指标全是标准图算法，无任何 ML 依赖，单机即可复现。前端 SQL 模板已在本报告与 `tmp/citation-survey/inciteful/` 留档，榜单语义可直接照抄。
2. **"每查询物化一个 SQLite"是神来之笔也是最大教训点**：它把"每个 graph 一个可查询视图"做成了极简事实标准——SQL 面板直接变成 power-user 卖点。但**把裸 SQL 暴露给公网**（虽然服务端限 LIMIT 50、只读表）在生产上不可接受：正确姿势是照搬"物化+schema"设计，对外只暴露参数化查询。自建时这份 schema（papers/authors/FTS/metadata 四张表）可以直接当模板。
3. **数据策略务实且已验证两代**：引用图只需要 `paper_id + references/citations` 边，全图吃 OpenAlex dump；摘要/OA 链接等富字段按需从 OpenAlex API 现取（他们就是这么干的——库里 `fields_of_study`/`pdf_urls` 全空）。证明"发现层"根本不需要全文。
4. **规模数字可外推**：depth-2 图典型 1–5 万节点，冷建 ~1s 级；阈值 15 万节点截断。说明一台大内存机器 + 全图邻接表就能支撑这个体验等级——全 arXiv（250 万节点）做同等服务绰绰有余。
5. **缺陷也要照单吸收**：相似度天然偏新文（官方明说 coupling/cocite 都随时间偏置）；"重要"榜天然偏老文；只有标题没有摘要导致关键词过滤弱；作者按 `name` 字符串聚合（SQL `GROUP BY name`），有同名合并问题——其 `authors.author_id` 存在但没在榜里用，复刻时应用 author_id。Inciteful 自己都留了 `volume`/`fields_of_study`/`pdf_urls` 空字段，说明 schema 先行、数据可后补。
6. **生态面可白嫖**：他们的 graph API 目前完全开放（`SELECT` 任意 SQL 都能跑），在自建完成前可以当临时图数据源兜底；`/paper/{id}` 的 citing/cited_by 全量邻接输出更是免费的图遍历入口。MCP server 的出现说明官方有意把它平台化——值得持续关注[^mcp]。

## 探针产物

scratch 目录 `tmp/citation-survey/inciteful/`：

- `index.html`、`index.js`（主 bundle）、`QueryPanel-CqoywGto.js`、`PaperDiscovery-DMZUM2e6.js`、`LitReview-Bxb7p2tv.js`、`LitConnectorBody-BhApFkwr.js`、`Einstein-CiSbjEM2.js`、`GraphSearch-Dp-wdbrQ.js`、`DataSources-byw5zXc9.js`、`About-LUjP1RPA.js`、`PaperDiscoveryQuery-*.js`、`LitReviewQuery-*.js`（前端资产与提取出的 SQL 模板来源）
- `doc-*.md.txt`（官方文档 7 篇原文：index/quick-start/faq/use-cases/power-users/graphs-explained/literature-connector-explained/paper-disovery-explained）
- `pc.json`、`pf.json`（`/paper/{id}` 全量邻接响应）、`conn*.json`、`c.json`（connector 响应）、`query1.json`/`query2.json`（错误信息取证）、`docs_tree.json`

### 参考文献

[^about]: Inciteful. About Inciteful. incitefulmed.com/academic/about 页面字符串提取（2026-09-19 实测）.
[^pde]: Inciteful. Paper Discovery Explained. inciteful-academic-docs repo, `paper-disovery-explained.md`. [raw.githubusercontent.com](https://raw.githubusercontent.com/inciteful-xyz/inciteful-academic-docs/master/paper-disovery-explained.md)
[^pu]: Inciteful. Power Users (SQL schema + filters). inciteful-academic-docs repo, `power-users.md`.
[^lcd]: Inciteful. Literature Connector Explained. inciteful-academic-docs repo, `literature-connector-explained.md`.
[^eins]: Inciteful. Einstein 页文案. `Einstein-CiSbjEM2.js` chunk 提取（2026-09-19 实测）.
[^data]: Inciteful. The Underlying Data / DataSources 页. `paper-disovery-explained.md` 末段 + `DataSources-byw5zXc9.js`.
[^istl]: Issues in Science and Technology Librarianship. Citation Network Based Research Discovery Using Inciteful. [journals.library.ualberta.ca](https://journals.library.ualberta.ca/istl/index.php/istl/article/download/2974/2860?inline=1)
[^substack]: Erika@Inciteful Med. Welcome to Informed Consent. [incitefulmed.substack.com](https://incitefulmed.substack.com/p/welcome-to-informed-consent)
[^casrai]: CASRAI. Inciteful: Citation-Network Paper Discovery Explained. [casrai.org](https://casrai.org/guides/inciteful-citation-network-paper-discovery)
[^gh]: GitHub. inciteful-xyz organization repositories. [github.com/inciteful-xyz](https://github.com/inciteful-xyz)
[^mcp]: inciteful-xyz. inciteful-mcp README/source. [github.com/inciteful-xyz/inciteful-mcp](https://github.com/inciteful-xyz/inciteful-mcp)
