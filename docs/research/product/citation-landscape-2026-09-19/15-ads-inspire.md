# Lane 15：NASA ADS 与 INSPIRE-HEP（引用关系做成一等公民查询语义的两个先例）

> **结论**：两个「单一机构自建全领域引用图谱+发现层」的最佳先例——ADS 的 Solr 二阶算子（citations/references/similar/trending/useful/reviews/topn 组合子）是发现层 API 设计的完整范本，oracle_service 的「阅读历史+文本相似+时间截断」是可照搬的极简个性化配方；INSPIRE 的引用边三件套（记录链接+原始串+curated 标志）与 BAI 作者消歧是策展级数据的存储范式，但其 `refersto:`/`citedby:` 命名与直觉相反，自建时应避免。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## NASA ADS

Smithsonian Astrophysical Observatory 在 NASA 资助下运营，覆盖天文/物理及 arXiv 预印本，1300 万+ 记录，同时追踪**引用与使用量**两类信号[^ads-home]。API token 免费（账号设置页生成），限流按端点独立计算、响应头公示额度（search 示例 5000/day，bigquery ~100 次/日每次 ≤2000 bibcode）[^adsapi-readme][^adsapi-notebook]。

### Solr 二阶算子（本 lane 核心发现）

ADS 查询语法 = Apache Solr + 一组二阶算子：先用普通查询取论文集合，算子把集合沿引用/使用/文本关系**变换成另一个集合**[^ads-second-order]。

| 算子 | 语义 | 底层信号 |
| --- | --- | --- |
| `citations(query)` | 引用了结果集的论文 | 引用图入边 |
| `references(query)` | 被结果集引用的论文 | 引用图出边 |
| `similar(query)` | 按结果集合并摘要做文本相似（排除自身） | 摘要文本 |
| `trending(query)` | 该集合的读者最近还在读什么（按频次） | 共读/使用量日志 |
| `useful(query)` | 集合参考文献按被引频次聚合 → 「该领域的方法基石」 | 文献耦合聚合 |
| `reviews(query)` | 引用集合的论文按频次聚合 → 「最 extensive 的综述」 | 共被引聚合 |
| `topn(N, query, sort)` | 取前 N，可嵌套 | 通用截断 |

发现语义拆解：`useful` ≈ 文献耦合的聚合版、`reviews` ≈ 共被引的聚合版、`trending` 是 ADS 独有（需要自家读者日志，别家抄不了）、`similar` 是纯文本线。官方惯用法：`similar(旧集查询) entdate:[NOW-7DAYS TO *]`——算子排除一阶结果，拼 disjoint 时间区间即「相似于旧集的新文」[^ads-citref]。

### oracle_service：个性化推荐极简配方

ADS 开源组件中的 Recommender 即 `oracle_service`[^adsapi-openapi]。`/readhist` 端点是**查询拼装器**：输入匿名 reader ID，产出 Solr 查询串 `(similar(topn(10, reader:<id>, entry_date desc)) entdate:[NOW-5DAYS TO *])`——取该用户最近读 10 篇 → 合并摘要文本相似 → 限近 5 天入库[^adsapi-oracle]。参数 num_docs/cutoff_days/top_n_reads/sort 可调，function 可取 similar/trending/useful/reviews。没有独立模型或索引——**个性化 feed = 阅读历史 + 文本相似 + 时间截断**，可直接照搬。同服务 `/matchdoc` 逐字段打分合并 confidence，用于判定 arXiv 版与出版版是否同一篇（dedup 场景）。

### 可视化与 myADS

- **Paper Network**：按共享参考文献（bibliographic coupling）聚类论文，组名用组内标题共享独特词标注；组内展示「最高被引」和「最常被引的参考文献」（后者能发现未进结果集的相关文献）[^ads-viz]。
- **Results Graph**：日期×引用数×recent views（近 90 天访问数）散点——recent views 可挖出「引用还没起来的新晋热文」。
- **myADS**：四类通知中 General 类**把任意合法 ADS 查询存为日/周推送**，系统自动追加 `entdate:[NOW-7DAYS TO NOW]` 时间截断只推增量——「通知=持久化查询+自动截断」的实现 trick 直接可用[^ads-myads]。

bibcode 为定长 19 字符 `YYYYJJJJJVVVVMPPPPA`，arXiv 预印本映射为刊名位 `arXiv`（如 `2017arXiv170603762V`）；官方明示 modern bibcode 语义勿依赖[^ads-bibcode]。

## INSPIRE-HEP

高能物理社区库（SPIRES 血统可溯至 1960s），Invenio3 架构、CERN/DESY/Fermilab/SLAC/IHEP/CNRS 合营。`collection:citeable` 实测 1,537,238 条（2026-09-19）——规模只有 ADS 十分之一，但**引用数据是策展级精度**。

API 免鉴权：每 IP 先放 50 突发后 2 req/s，超限 429+`x-retry-in`；`size` 上限 1000、搜索最多翻 10000 条[^inspire-api]。**双标识符直通**：`literature/{recid}` 内部 ID 与 `arxiv/{id}`、`doi/{doi}`、`orcid/{id}` 外部 ID——实测 `GET /api/arxiv/1706.03762` 与 `GET /api/arxiv/hep-th/9901001`（老 ID）均 200。搜索语法 literature 走 SPIRES 兼容（`a E.Witten.1` BAI、`topcite 1000+`、`eprint:`）。

**引用图数据形态**（对自建管线最有参考价值）：literature 记录的 `metadata.references[]` 每条含 `record.$ref`（被引记录 API 链接）+ `reference`（原始解析字段 journal_title/volume/page/texkey/raw_ref）+ `curated_relation` 布尔位——**引用边以「被引记录链接+原始字符串+策展标志」三件套存储**；`citation_count` 与 `citation_count_without_self_citations` 双计数直接挂在记录上。搜索算子两个，**语义命名与直觉相反**（实测确认）：`refersto:recid:N` = 引用了 N 的论文（=N 的被引数）、`citedby:recid:N` = N 引用的论文——自建时此命名应避免。

作者消歧：authors 记录含 INSPIRE BAI（`Edward.Witten.1`）、ORCID 等多 schema 标识 + `positions[]` 机构 $ref 互链 + `advisors` 师承——作者-机构边与论文-引用边同构存储，图连成一体。

**refextract**（`inspirehep/refextract`，GPLv2）：HEP 参考文献抽取库，API 三个（`extract_journal_reference`/`extract_references_from_file/url`），底层 pdftotext+规则/知识库匹配路线非神经网络；macOS 装不了，官方建议 Docker[^refextract]。抽取后由 INSPIRE 管线按 texkey/期刊坐标匹配 recid 写入 `record.$ref`。

zbMATH Open REST API 免鉴权可用、记录含作者码与 review 文本，但引用边覆盖远不及 ADS/INSPIRE；MathSciNet 付费墙无开放 API。

## 可借鉴算子清单

| 算子/功能 | 所需数据 | 实现提示 |
| --- | --- | --- |
| `citations(q)`/`references(q)` | 引用图 | 边表 join，最易实现 |
| `useful(q)`/`reviews(q)` | 引用图 | BC/CC 的聚合形式 → 方法基石/综述 |
| `similar(q)` | 摘要+向量 | embedding ANN 或 Solr MoreLikeThis |
| `trending(q)`、recent views | **使用量日志** | 无日志源做不了；可用公开页浏览计数替代 |
| `topn(N,q,sort)` 嵌套 | 通用 | 组合子模式值得照搬 |
| Paper Network | 引用图+标题 | coupling 矩阵+社区检测+TF-IDF 标注 |
| 通知=持久化查询 | 图+调度器 | `entdate` 自动截断 trick |
| curated_relation 标志 | 策展流程 | 引用边带 provenance 是专业库通行做法 |

## 结论

ADS 的独特壁垒是 readership 数据（trending/myADS 个性化都靠它），INSPIRE 的独特壁垒是策展精度与 BAI 消歧；两者之外——引用图算子组合子、coupling 聚类、持久化查询通知——全部可在自建引用图上复刻。

### 参考文献

[^ads-home]: SAO/NASA ADS. ADS Home Page. [ui.adsabs.harvard.edu](https://ui.adsabs.harvard.edu)
[^adsapi-readme]: NASA ADS. adsabs-dev-api README. [github.com/adsabs/adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api/blob/master/README.md)
[^adsapi-notebook]: NASA ADS. Search API (Python) notebook. [github.com/adsabs/adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api/blob/master/API_documentation_Python/Search_API_Python.ipynb)
[^adsapi-openapi]: NASA ADS. openapi_public.yaml. [github.com/adsabs/adsabs-dev-api](https://github.com/adsabs/adsabs-dev-api/blob/2e221c0f/openapi/openapi_public.yaml)
[^ads-second-order]: NASA ADS. Second-Order Queries. [adsabs.github.io/help/search/second-order](https://adsabs.github.io/help/search/second-order)
[^ads-citref]: NASA ADS. Citations and References Operators. [adsabs.github.io/help/search/citations-and-references](https://adsabs.github.io/help/search/citations-and-references)
[^adsapi-oracle]: NASA ADS. oracle_service README. [github.com/adsabs/oracle_service](https://github.com/adsabs/oracle_service/blob/master/README.md)
[^ads-viz]: NASA ADS. Visualize Results. [adsabs.github.io/help/actions/visualize](https://adsabs.github.io/help/actions/visualize)
[^ads-myads]: NASA ADS. Introducing the New myADS. [ui.adsabs.harvard.edu/blog/the_new_myADS](https://ui.adsabs.harvard.edu/blog/the_new_myADS)
[^ads-bibcode]: NASA ADS. The ADS Bibcode. [adsabs.github.io/help/actions/bibcode](https://adsabs.github.io/help/actions/bibcode)
[^inspire-api]: INSPIRE Collaboration. INSPIRE REST API. [github.com/inspirehep/rest-api-doc](https://github.com/inspirehep/rest-api-doc/blob/master/README.md)
[^refextract]: INSPIRE Collaboration. refextract README. [github.com/inspirehep/refextract](https://github.com/inspirehep/refextract)
