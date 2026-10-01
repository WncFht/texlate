# Lane 09：Inciteful 逆向

> **结论**：同类产品里架构最透明、最小而美的实现——单人开发者 + Rust 后端 + OpenAlex 数据 +「每次查询物化一个临时 SQLite 库、前端发裸 SQL」的激进设计。算法栈（PageRank + Adamic/Adar + Salton 共被引 + BFS + num_citing）全是标准图算法零 ML，是「完全形态」最直接的可复制蓝本。
> **状态**：时点证据（2026-09-19 口径）——对第三方服务的时点观察，仅供互操作参考。
> **日期**：2026-09-19

## 产品定位

Inciteful 由 Michael Weishuhn 2020 年独立开发上线[^istl]；项目缘起是帮做学术的妻子查文献时意识到自己其实在手绘引用网络。演进史：第一年是 OpenCitations/Crossref API 拼凑的 Python notebook（建图 15 分钟+），后学 Rust、换数据库与数据源、重构数次才达到实时性能[^about]。数据源从 MAG 换代到 OpenAlex（当前后端命名空间即 `/openalex`）。现状：主产品是医疗证据产品 Inciteful Med，学术工具留在 `/academic/` 路径免费运营，约 4 万月活[^substack]；前端 Vue 开源（AGPL-3.0）、Zotero 插件与 MCP server 开源，图构建后端闭源[^gh]。

## 产品面

六个工具：Paper Discovery（seed→局部图→Similar/Important/Review/Recent 分栏榜 + 作者/机构/期刊榜）、LitReview（多 seed 强化版 1–500 个）、Literature Connector（两篇论文全图双向 BFS 最短引用路径）、Einstein（离爱因斯坦几跳的彩蛋版）、Search（题名/DOI/arXiv URL 定位 seed）、SQL Query Panel（对当前图的 SQLite 库执行任意 SQL，power-user 卖点）。附属：BibTeX 导入导出、Zotero 插件、MCP server 9 工具[^mcp]。

## 架构画像（实测）

最激进的发现：graph API 的 query 端点**接收并执行裸 SQL**（实测 `POST graph.incitefulmed.com/openalex/query/W2741809807?prune=10000`，body `SELECT sqlite_version()` 返回 3.51.1）。行为还原：后端持有全量引用图（OpenAlex 子集）；收到 seed 实时做图扩展算指标，**物化成独立 SQLite 库缓存 24h+**；之后前端所有表格通过 POST SQL 到这个库取数，服务端强追加 LIMIT[^pde][^pu]。

实测 dump 出的 schema（压缩重写，列类型略）：

```sql
CREATE TABLE papers (
  paper_id TEXT PRIMARY KEY, doi TEXT, authors TEXT, num_authors INTEGER,
  title TEXT, published_year INTEGER, journal TEXT,
  num_citing INTEGER, num_cited_by INTEGER,
  distance INTEGER, page_rank REAL, adamic_adar REAL, cocite REAL
) WITHOUT ROWID
CREATE TABLE authors (author_id, paper_id, name, sequence, affiliation,
  affiliation_id, ror, published_year, partial_page_rank REAL, PRIMARY KEY(paper_id, author_id))
CREATE VIRTUAL TABLE title_search USING FTS5(paper_id, search_text, tokenize='porter unicode61')
CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)  -- 建图参数
```

metadata 表实测：`graph_depth=2, paper_count=48496, citation_count=393964`（seed=W2741809807）。

API 面全部免鉴权：`POST /openalex/query/{W-id}?prune={n}` 建图+SQL（冷启动小图 ~1.3s、48k 节点图 SQL ~0.7s）；`ids[]=` 多 seed（distance 0=1 个虚拟节点、distance 1=seed 们、distance 2=候选池——「fake node」trick 实测吻合）；`GET /openalex/paper/{id}` 返回完整 citing/cited_by ID 数组（图遍历原语）；`GET /openalex/connector?from=&to=&extend=` 返回 paths/connections/papers_searched（实测搜 52785 篇找到 1 跳直连）。库是 OpenAlex 子集——只收「有引用数据」的论文。

## 算法（官方文档 + 前端 SQL 模板双重取证）

**建图**：单 seed 以无向边处理，depth-1 拉全部引用 + 被引，depth-2 再扩一层收层内边；典型 depth-2 图 1–5 万节点，预计超 15 万节点停在 depth-1 并建议加关键词过滤[^pde]。多 seed 造虚拟节点 cites 全部 seed，相似度相对虚拟节点算。

**指标五件套全标准算法**：PageRank（重要性，局部子图迭代，作者侧 `partial_page_rank` 摊到作者）；**Adamic/Adar**（耦合相似——共同引用按 1/log 被引数 加权，共享冷门引用权重高）；**Salton 余弦**（共被引，分母 √(被引数之积) 补偿规模悬殊）；BFS distance；`num_citing` 排序识别综述（引用图内论文最多者≈综述）。

**前端 SQL 模板可直接照抄**：相似论文 `ORDER BY adamic_adar + COALESCE(cocite,0) DESC`；重要论文 `ORDER BY page_rank DESC`；近期重要加 `published_year > (strftime('%Y', 'now') - 3)`；作者榜 `SUM(partial_page_rank)`；LitReview 作者加权 `SUM(page_rank / (CASE WHEN num_authors < 4 THEN num_authors WHEN sequence = 0 OR sequence = num_authors - 1 THEN 3 ELSE num_authors * 3 END))`；新锐学者 `MIN(published_year) > (strftime('%Y', 'now') - 10)`；机构/期刊榜 `SUM(page_rank)` 分组聚合。

**Literature Connector**：全图当无向图做双向 BFS——两端逐层扩展到前沿相交，只保留最短路径上的点边；`extend` 参数把路径上限 +1 层；作者称「还没遇到过连不上的」[^lcd]。

## 可借鉴点

1. **per-query 物化视图是核心设计**：「每个 graph 一个可查询视图」做成极简事实标准，SQL 面板即 power-user 卖点。但裸 SQL 暴露公网在生产上不可接受——照搬「物化+schema」设计，对外只暴露参数化查询。
2. **数据策略务实**：引用图只需 `paper_id + references/citations` 边，富字段按需从 OpenAlex API 现取（他们库里富字段全空）——证明发现层根本不需要全文。
3. **规模数字可外推**：depth-2 典型 1–5 万节点冷建 ~1s——全 arXiv 做同等服务绰绰有余。
4. **缺陷照单吸收**：相似度天然偏新文、「重要」榜偏老文；只有标题无摘要关键词过滤弱；作者按 name 字符串聚合有同名合并问题（复刻用 author_id）；schema 先行富字段可后补。
5. **生态面可直接用**：graph API 完全开放（任意 SELECT 都能跑），自建完成前可当临时图数据源兜底。

## 结论

六七个同类产品里最适合当「完全形态」蓝本的一个：算法栈完整逆向且有官方文档兜底、schema 可直接当模板、单机可复现。

### 参考文献

[^about]: Inciteful. About Inciteful（2026-09-19 实测提取）. incitefulmed.com/academic/about

[^pde]: Inciteful. Paper Discovery Explained. inciteful-academic-docs repo. [raw.githubusercontent.com](https://raw.githubusercontent.com/inciteful-xyz/inciteful-academic-docs/master/paper-disovery-explained.md)

[^pu]: Inciteful. Power Users (SQL schema + filters). inciteful-academic-docs repo. [raw.githubusercontent.com](https://raw.githubusercontent.com/inciteful-xyz/inciteful-academic-docs/master/power-users.md)

[^lcd]: Inciteful. Literature Connector Explained. inciteful-academic-docs repo. [raw.githubusercontent.com](https://raw.githubusercontent.com/inciteful-xyz/inciteful-academic-docs/master/literature-connector-explained.md)

[^istl]: Issues in Science and Technology Librarianship. Citation Network Based Research Discovery Using Inciteful. [journals.library.ualberta.ca](https://journals.library.ualberta.ca/istl/index.php/istl/article/download/2974/2860?inline=1)

[^substack]: Erika@Inciteful Med. Welcome to Informed Consent. [incitefulmed.substack.com](https://incitefulmed.substack.com/p/welcome-to-informed-consent)

[^gh]: GitHub. inciteful-xyz organization repositories. [github.com/inciteful-xyz](https://github.com/inciteful-xyz)

[^mcp]: inciteful-xyz. inciteful-mcp README. [github.com/inciteful-xyz/inciteful-mcp](https://github.com/inciteful-xyz/inciteful-mcp)
