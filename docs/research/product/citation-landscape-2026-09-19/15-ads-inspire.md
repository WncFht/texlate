# NASA ADS 与 INSPIRE-HEP 调研

两个「单一机构自建全领域引用图谱 + 发现层」的最佳先例：NASA ADS（天文/物理，~1600 万记录，Solr 二阶算子 + 使用量数据）和 INSPIRE-HEP（高能物理，~154 万记录，结构化 references 内嵌互链）。两者都把「引用关系」做成了一等公民的查询语义，而不是藏在「相关论文」按钮后面——这正是完整形态发现层该有的 API 设计范式。

## NASA ADS

### 定位与规模

ADS（Astrophysics Data System）由 Smithsonian Astrophysical Observatory 在 NASA 资助下运营，覆盖天文、物理及 arXiv 预印本，官方自述「three bibliographic databases containing more than 13.3 million records」且同时**追踪引用（citations）与使用量（usage）**两类信号做发现与评估[^ads-home]。全文可检索（full-text search），是其区别于多数元数据库的关键资产。

### API 准入与限流

API token 免费：注册 ADS 账号后在用户设置页点「Generate a new key」，所有请求带 `Authorization: Bearer &lt;token&gt;` 头[^adsapi-readme]。无 token 请求一律 401 `{"message": "Missing \"Authorization\" in headers."}`（实测 2026-09-19）。限流按**端点独立**计算，响应头 `X-RateLimit-Limit/-Remaining/-Reset` 公示额度（文档示例 search=5000/day；`/search/bigquery` 上限约 100 次/日、每次最多 2000 个 bibcode；重置在 UTC 零点）[^adsapi-readme][^adsapi-notebook]。

### Solr 二阶算子（本 lane 的核心发现）

ADS 查询语法 = Apache Solr + 一组「二阶算子」（second-order operators）：「database functions which form secondary queries based on attributes of the objects returned in an initial query」——即先用普通查询取一个论文集合，算子把这个集合**沿引用/使用/文本关系变换成另一个集合**[^ads-second-order]。

| 算子 | 语义（官方原文摘录） | 底层信号 |
| --- | --- | --- |
| `citations(query)` | 返回引用了 query 结果集的论文 | 引用图入边 |
| `references(query)` | 返回被 query 结果集引用的论文（出现在其参考文献表中） | 引用图出边 |
| `similar(query)` | 「Ranks all ADS abstracts by text similarity to the first-order results' combined abstract text」，排除集合自身 | 摘要文本相似度 |
| `trending(query)` | 「what else readers of the first-order papers read, merges those lists, and sorts by frequency」——该集合的读者**最近还在读什么** | 共读（co-readership/使用量） |
| `useful(query)` | 「Combines the reference lists of first-order papers and sorts by citation frequency」——集合的参考文献里被引频次最高的，官方定位为「methods and techniques useful to conduct research in this field」 | 文献耦合聚合 → 方法论基石 |
| `reviews(query)` | 「Combines articles citing the first-order papers, sorted by appearance frequency」——引用集合的论文中频次最高的，定位「papers containing the most extensive reviews」 | 共被引聚合 → 综述 |
| `topn(N, query, sort)` | 取前 N 条，可嵌套（`trending(topn(10, reviews("weak lensing")))`） | 通用截断 |

官方示例：`citations(author:"huchra, john")`（引用 Huchra 全部论文的文献）、`references(bibcode:2003AJ….125..525J)`（该文引用的文献）、`similar("weak lensing" -entdate:[NOW-7DAYS TO *]) entdate:[NOW-7DAYS TO *]`（相似于旧集合但限近 7 天——because the operator excludes first-order results，拼接 disjoint 区间是惯用法）[^ads-second-order][^ads-citref]。

**这套算子的发现语义拆解**：`useful` ≈ 文献耦合的聚合版（"这个领域都在引什么"→奠基方法）；`reviews` ≈ 共被引的聚合版（"谁大量引用了这个集合"→综述）；`trending` 是 ADS 独有——需要自家匿名 reader 阅读日志，别家没有使用量数据就抄不了；`similar` 是纯文本线。

### oracle_service：个性化推荐的极简配方

ADS 开源组件清单里的 Recommender 是 `oracle_service`[^adsapi-openapi]。其 `/readhist` 端点实现的是一个**查询拼装器**：输入匿名 reader 的 16 位 ID，产出 Solr 查询串如 `(similar(topn(10, reader:&lt;reader&gt;, entry_date desc)) entdate:[NOW-5DAYS TO *])`——即「取该用户最近读的 10 篇 → 对合并摘要做文本相似 → 限定近 5 天入库」[^adsapi-oracle]。可调参数 `num_docs`(5)/`cutoff_days`(5)/`top_n_reads`(10)/`sort`。没有独立模型或索引，推荐质量完全委托给 Solr 的 `similar()` 算子——**个性化 feed = 阅读历史 + 文本相似 + 时间截断**，是可直接照搬的配方。`function` 参数可取 similar/trending/useful/reviews 四种。

同服务还含 `/matchdoc`：对 abstract/title/author/year 逐字段打分合并成 confidence，用于判定 arXiv 版与出版版是否同一篇（dedup/合并场景）。

### 可视化层

- **Author Network**：共著频率网络，取结果集中 top-200 高频作者，社区分组 + 可选按引用数加权；点击组边可看跨组合作者[^ads-viz]。
- **Paper Network**：**按共享参考文献（bibliographic coupling）分组**论文——「papers sharing references tend to have similar topics」；组名用组内标题的共享独特词标注；点开组展示「组内最高被引」和「最常被引用的参考文献」（后者可发现未进结果集的相关文献）[^ads-viz]。
- **Results Graph**：发表日期 × 引用数 × recent views（近 90 天 ADS 访问次数）的可定制散点，支持刷选过滤——用「recent views」信号可挖出「引用还没起来的新晋热文」[^ads-viz]。
- **Concept Cloud**：标题+摘要词频，与全库词频对比，滑杆在「独特」与「高频」间调节——本质 TF-IDF 关键词云[^ads-viz]。

### myADS：通知即「持久化 Solr 查询」

新版 myADS 四类通知[^ads-myads]：①arXiv 日更——选定 arXiv 分类的全部新论文，可选关键词把列表二分（命中/未命中）；②Citations 周更——追踪指定作者的新被引（「keep an eye on what papers are citing your own work」）；③Keywords/Authors 周更；④**General——任意合法 ADS 查询存为日/周通知**，系统自动追加 `entdate:[NOW-7DAYS TO NOW]` 式时间截断只推增量[^ads-myads]。周刊每条通知只含 top-5。实现侧走 `vault` 服务（stored search + notifications）[^adsapi-openapi]。

### bibcode 与开源组件

bibcode 为定长 19 字符 `YYYYJJJJJVVVVMPPPPA`（年/刊名左对齐/卷右对齐或 conf|meet|book|proc/限定符/页右对齐/首作者姓首字母），点号补齐[^ads-bibcode]。arXiv 预印本映射为刊名位 `arXiv` 的模式（如 `2017arXiv170603762V`；官方文档明示「Modern bibcodes are likely to be deprecated in the future」勿依赖语义）。开源组件：solr-service、vault、biblib-service、export_service、metrics_service、author_affiliation_service、citation_helper_service、harbour-service、object_service、ADSJournalsDB、oracle_service、reference_service、resolver_service、vis-services[^adsapi-openapi]。

## INSPIRE-HEP

### 定位与规模

高能物理社区库（SPIRES 血统可溯至 1960s），现为 Invenio3 架构、CERN/DESY/Fermilab/SLAC/IHEP/CNRS 合营。`collection:citeable` 实测 1,537,238 条（2026-09-19）——规模只有 ADS 的十分之一，但**引用数据是策展级精度**（curated_relation 标志位区分机器抽取与人工确认）。

### API 面（免鉴权，实测全通）

- 限流：每 IP 先放 50 个突发请求、随后最多 2 req/s；超限返回 429 + `x-retry-in` 头[^inspire-api]。`size` 上限 1000，单次搜索最多翻 10000 条（超出需拆查询）[^inspire-api]。
- 记录类型：literature/authors/conferences/seminars/journals/experiments/institutions/jobs/data 九类。
- **双标识符直通**：内部 `literature/{recid}`、`authors/{id}`；外部 `arxiv/{id}`、`doi/{doi}`、`orcid/{id}`——实测 `GET /api/arxiv/1706.03762`（200，返回 "Attention Is All You Need"）与 `GET /api/arxiv/hep-th/9901001`（200，老 ID 直通）[^selftest]。
- 单条响应自带 `links`：bibtex/latex-eu/latex-us/cv/json-expanded 格式切换 + `citations` 链接（实为 `refersto:recid:N` 搜索 URL）。`?format=bibtex` 实测返回带 texkey 的干净 BibTeX。
- 搜索语法：literature 用 SPIRES 兼容语法（`a E.Witten.1` 作者 BAI、`topcite 1000+` 被引过滤、`eprint:xxx` arXiv ID），其他类型用 ES query string；另支持任意 metadata 字段路径 `abstracts.source:Springer`、`dois.value:*`[^inspire-api]。

### 引用图数据形态（对自建管线最有参考价值）

literature 记录的 `metadata.references[]` 每条含 `record.$ref`（指向被引文献的 recid API URL）+ `reference`（原始解析字段：journal_title/volume/page/artid/texkey/raw_ref）+ `curated_relation` 布尔位——**引用边以「被引记录链接 + 原始字符串 + 策展标志」三件套存储**[^selftest]。`citation_count` 与 `citation_count_without_self_citations` 双计数直接挂在记录上。

搜索算子两个，语义命名与直觉相反（实测确认，2026-09-19）：`refersto:recid:1729` → 73 条 = 引用了 1729 的论文（=该记录 citation_count）；`citedby:recid:1729` → 8 条 = 1729 引用的论文（=其 references 数）[^selftest]。

### 作者消歧与机构图谱

authors 记录含多 schema 标识（INSPIRE BAI `Edward.Witten.1`、INSPIRE ID、ORCID、WIKIPEDIA、TWITTER、SPIRES HEPNAMES）+ `positions[]`（rank/start/end + `institutions` $ref 互链）+ `advisors`（师承）——作者-机构边和论文-引用边同构存储，图是连成一体的[^selftest]。

### refextract：引文抽取管线

`inspirehep/refextract`（GPLv2）：抽取 HEP 文献参考文献的库，源自 Invenio `docextract` 模块[^refextract]。API 三个：`extract_journal_reference`（字符串→期刊坐标）、`extract_references_from_file/url`（PDF→结构化引用，输出 author/doi/journal_title/volume/year/page/texkey/raw_ref/linemarker）。底层依赖 `pdftotext` + 规则解析（README 未披露模型——实为正则/知识库匹配路线，非神经网络）；macOS 装不了（mmap resize），官方建议 Docker[^refextract]。抽取后由 INSPIRE 管线按 texkey/期刊坐标匹配到 recid 写入 `record.$ref`。

## zbMATH Open 与 MathSciNet（带过）

zbMATH Open REST API（api.zbmath.org/v1）免鉴权可用，`/document/_search?search_string=py:2020` 实测 200[^selftest]；记录含 author codes（作者消歧）与 review 文本，但引用边覆盖远不及 ADS/INSPIRE。MathSciNet（AMS）为付费墙产品、无开放 API，仅有 subscription 内 citation matching——对开放发现层无借鉴价值。

## 可借鉴的算子/功能清单

完整形态「引用图谱发现 API」可照抄的语义设计：

| 算子/功能 | 语义 | 所需数据 | 实现提示 |
| --- | --- | --- | --- |
| `citations(q)` / `references(q)` | 集合→入边/出边 | 引用图 | 边表 join，最易实现 |
| `useful(q)` | 集合参考文献按频次聚合 → 领域方法基石 | 引用图 | bibliographic coupling 的聚合形式 |
| `reviews(q)` | 引用集合者按频次聚合 → 综述 | 引用图 | co-citation 的聚合形式 |
| `similar(q)` | 合并摘要文本相似（排除自身） | 摘要 + 向量/TF-IDF | embedding ANN 或 Solr MoreLikeThis |
| `trending(q)` | 集合读者的共读热门 | **使用量日志** | 无日志源做不了，ADS 独占优势 |
| `topn(N,q,sort)` 嵌套 | 截断+排序 | 通用 | 组合子模式值得照搬 |
| `recent views` 信号 | 近 90 天访问数 → 早于引用累积的热度 | 使用日志 | 同上，可做公开页浏览计数替代 |
| Paper Network | bibliographic coupling 聚类 + 标题独特词命名 | 引用图+标题 | coupling 矩阵 + 社区检测 + TF-IDF 标注 |
| notification = 持久化查询 | 任意发现查询 + 自动时间截断 → 推送 | 图+调度器 | `entdate` 截断 trick 直接可用 |
| `refersto:`/`citedby:` 字段语法 | 把引用关系暴露为搜索谓词 | 引用图 | 注意 INSPIRE 命名反直觉，自建时避免 |
| curated_relation 标志 | 机器抽取 vs 人工确认分置信度 | 策展流程 | 引用边带 provenance 是专业库通行做法 |

ADS 的独特壁垒是 readership 数据（trending/myADS 个性化都靠它）；INSPIRE 的独特壁垒是策展精度与 BAI 作者消歧。两者之外的部分——引用图算子、coupling 聚类、持久化查询通知——全部可在自建引用图上复刻。

## 探针产物

`tmp/citation-survey/ads-inspire/`：`inspire-lit-1729.json`（单记录+references 结构）、`inspire-arxiv-1706.json`/`inspire-arxiv-old.json`（新旧 arXiv ID 搜索）、`inspire-extid-arxiv.json`/`inspire-extid-old.json`（外部标识符直通）、`inspire-refersto.json`/`inspire-citedby.json`（两向引用查询实测）、`inspire-topcite.json`（mostcited 排序+topcite 过滤）、`inspire-bibtex.txt`（bibtex 导出格式）、`inspire-author-witten.json`（作者 BAI/positions 结构）、`inspire-count.json`（citeable 总量）、`ads-solr-noauth.json`（ADS 401 鉴权要求）、`zbmath-test.json`（zbMATH 免鉴权）。INSPIRE OAI-PMH 探测因 TLS 中断未取得——未验证。

### 参考文献

[^ads-home]: SAO/NASA ADS. ADS Home Page（archive 快照）. 2017. [adsabs.harvard.edu](https://web.archive.org/web/20171028043512/http:/articles.adsabs.harvard.edu/)
[^adsapi-readme]: NASA ADS. adsabs-dev-api README. GitHub. [github.com/adsabs/adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api/blob/master/README.md)
[^adsapi-notebook]: NASA ADS. Search API (Python) notebook. GitHub. [github.com/adsabs/adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api/blob/master/API_documentation_Python/Search_API_Python.ipynb)
[^adsapi-openapi]: NASA ADS. openapi_public.yaml. GitHub. [github.com/adsabs/adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api/blob/2e221c0f/openapi/openapi_public.yaml)
[^adsapi-oracle]: NASA ADS. oracle_service README. GitHub. [github.com/adsabs/oracle_service](https://github.com/adsabs/oracle_service/blob/master/README.md)
[^ads-second-order]: NASA ADS. Second-Order Queries. ADS Help. [adsabs.github.io/help/search/second-order](https://adsabs.github.io/help/search/second-order)
[^ads-citref]: NASA ADS. Citations and References Operators. ADS Help. [adsabs.github.io/help/search/citations-and-references](https://adsabs.github.io/help/search/citations-and-references)
[^ads-viz]: NASA ADS. Visualize Results. ADS Help. [adsabs.github.io/help/actions/visualize](https://adsabs.github.io/help/actions/visualize)
[^ads-myads]: NASA ADS. Introducing the New myADS. ADS Blog. [ui.adsabs.harvard.edu/blog/the_new_myADS](https://ui.adsabs.harvard.edu/blog/the_new_myADS)
[^ads-bibcode]: NASA ADS. The ADS Bibcode. ADS Help. [adsabs.github.io/help/actions/bibcode](https://adsabs.github.io/help/actions/bibcode)
[^inspire-api]: INSPIRE Collaboration. INSPIRE REST API. GitHub inspirehep/rest-api-doc. [github.com/inspirehep/rest-api-doc](https://github.com/inspirehep/rest-api-doc/blob/master/README.md)
[^refextract]: INSPIRE Collaboration. refextract README. GitHub. [github.com/inspirehep/refextract](https://github.com/inspirehep/refextract)
[^selftest]: 本报告内标注「实测」的 INSPIRE/zbMATH API 响应，原始 JSON 存于 `tmp/citation-survey/ads-inspire/`，2026-09-19。
