# 引用图谱论文发现生态全景调研

> **结论**：「引用图谱发现」赛道真实存在但无人做到完全形态——空白点 = 「全 arXiv 量级、语句级边质量、算子化查询面、实时新鲜度」四者合一；LaTeX 源侧抽取是唯一能同时解锁边质量与新鲜度的路径，是 texlate 的结构性优势。数据底座以 OpenAlex 快照为主干即可零成本起步。
> **状态**：时点证据（2026-09-19 口径）——产品机制逆向为对第三方服务的时点观察，仅供互操作参考；数据源规模与价格随时间漂移，引用前复核。
> **日期**：2026-09-19

调研问题：**基于引用数与引用图谱做论文推荐/发现，现在有哪些应用、服务、网站、工具，它们具体怎么做的；要做一个「完全形态」应该怎么做。**方法：20 个并行调研 lane（数据源实测、产品逆向、开源源码阅读、算法文献、工程成本核算），覆盖 40+ 产品与工具、10+ 个数据集源、30+ 篇关键文献；关键断言均以 API/端点实测或官方文档取证（2026-09-19）。各 lane 完整报告在 `citation-landscape-2026-09-19/` 目录（01–20 编号），本文是汇总与结论。

## 一句话结论

「引用图谱发现」赛道真实存在且已被多家产品验证，但**没有一家做到完全形态**——现有产品各自只占住光谱的一段：Connected Papers 做了图可视化但只给 40 节点静态图，Inciteful 算法栈最全但只是单 seed 局部图，scite 做到了语句级但壁垒在出版商协议，Undermind 做了引用链 agent 但黑盒收费，Scinapse 押注全图但产品形态仍是搜索框。**空白点 = 「全 arXiv 量级、语句级边质量、算子化查询面、实时新鲜度」四者合一**——而 LaTeX 源侧抽取是唯一能同时解锁边质量与新鲜度的路径，这是自建方的结构性优势。

## 生态分层地图

这个生态可以切成四层，每层都有玩家但层间几乎不打通：

| 层         | 玩家                                                                                                | 干什么                              |
| ---------- | --------------------------------------------------------------------------------------------------- | ----------------------------------- |
| 数据层     | OpenAlex、S2、OpenCitations、OpenAIRE、Crossref、OAG/AMiner、领域库（ADS/INSPIRE/iCite）            | 生产/聚合引用边与元数据，卖或送数据 |
| 发现产品层 | Connected Papers、ResearchRabbit、Litmaps、Inciteful、scite、Undermind、Scinapse                    | 面向最终用户的「找相关论文」        |
| 平台推荐层 | Google Scholar、Semantic Scholar、ResearchGate、Mendeley、ACM/IEEE                                  | 大平台内置的推荐 feed（非独立产品） |
| 工具层     | Citation Gecko、LCN、Zotero Cita、Scholia、litstudy、VOSviewer、CiteSpace、Argo Scholar、paperscape | 开源/本地化的引用图分析与可视化     |

**值得注意的结构性事实**：数据层三家巨头（OpenAlex/S2/OpenCitations）自己都不做面向用户的发现产品——OpenAlex 的 `related_works` 实测是主题相似且大面积悬空不可用，S2 的 Recommendations API 只给近 3 个月池。发现产品全部要从数据层买/嫖原料再自己算。**这意味着「发现层」是一个真实的、未被数据巨头吞掉的中间市场。**

## 数据源全景

能拿到引用边的开放源共 7 家，按「边规模 × 许可 × arXiv 适配」排：

| 源                      | 引用边规模                                      | 许可       | 获取方式                                                    | arXiv 适配                                  | 关键缺陷                                                                                                                    |
| ----------------------- | ----------------------------------------------- | ---------- | ----------------------------------------------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **OpenAlex**            | ~2.4B（估）                                     | **CC0**    | 季度快照 745GB 免账号 S3 + 计费 API                         | arXiv source 324 万 works、61% 带 refs      | 仅 31% works 有 refs；无 arXiv 原生 ID 字段（走 `10.48550` DOI 或 location 反查）；头部论文有合并事故；related_works 不可用 |
| **Semantic Scholar**    | **2.4B**（带 intent/influential/contexts 属性） | ODC-BY     | datasets API 分片下载（citations 255GB）+ 需 key 的在线 API | 覆盖好、externalIds 含 ArXiv                | 无 key 实测持续 429；license 非 CC0                                                                                         |
| **OpenCitations Index** | **2.56B**                                       | **CC0**    | 69GB dump + REST 180rpm                                     | arXiv 实体仅入边无出边（经 `10.48550` DOI） | 需 arXiv↔DOI 对齐；dump 滞后 ~5 个月                                                                                        |
| **OpenAIRE Graph**      | 2.35B（product_Cites）                          | **CC0**    | Zenodo 半年 dump ~321GB                                     | 聚合多源含 arXiv                            | 边型需逐条核、知名度低被低估                                                                                                |
| **OAG v3.3（AMiner）**  | v3.2 口径 12.7 亿                               | ODC-BY     | 阿里云 OSS 直链免鉴权 117.6GB                               | **无 arXiv id 字段**，doi/标题自匹配        | 年更无 diff；v3 起失去 MAG 半边校核                                                                                         |
| Crossref                | 8166 万 works 寄存 refs                         | 开放元数据 | REST 10rps + 年度公开 dump                                  | 出版 DOI 为主                               | cited-by 会员专属；寄存率 ~50% 是瓶颈                                                                                       |
| Wikidata P2860          | ~3.1 亿声明                                     | CC0        | SPARQL/dump                                                 | 稀疏（arXiv ~104 万）                       | 边密度不足撑不起全覆盖                                                                                                      |

化石与补充：MAG 2021-09 遗档（Zenodo，PaperReferences 40.5GB 边表）作历史桥；**unarXive 2022（1.9M arXiv 篇、63M refs、28M 已链 OpenAlex、permissive 子集直下）是 arXiv 引用图的现成冷启动资产**；fatcat refcat 数十亿边 CC0 但项目停滞；Lens 专有不可再分发只能当查询后端；INSPIRE-HEP/ADS/iCite/zbMATH 是领域策展源（精度高、覆盖窄）。

**arXiv 出边的全局性缺口**（三个 lane 独立实测确认）：arXiv 不向 Crossref/DataCite 寄存参考文献，所以在所有 DOI 中心源里 arXiv 实体**只有入边没有出边**。paperscape 当年自建抽取的 arXiv 内匹配率也只有 38%。手里有 LaTeX 源就能把这个缺口变成独有资产——`.bbl`/`\bibitem` 解析精度接近无损（S2ORC/unarXive 实证「near-perfect」），而 PDF 侧 GROBID 天花板只有 0.87–0.90 F1。

## 产品机制逆向：他们具体怎么算的

### 图遍历系（引用图是核心资产）

**Connected Papers**（以色列 4 人团队，2019）：每篇论文的图 = 以其为中心的 **co-citation + bibliographic coupling** 双指标（API 返回里每节点带 `cit_with_start`/`ref_with_start` 两个分数），固定 ~40 个节点（`total_nodes:40 num_neighbors:5 num_commons:10`），spring 布局 2000 次迭代。最反直觉的工程设计：**不是实时算——全库月度重算预生成静态图**（响应带 `corpus_date` 与 `valid_until`+30 天），数据底座是 S2 语料；图数据用自研 CPGR 二进制格式（"CPGR" magic + u32 status + u32 len + zlib(JSON)）下发。所有端点免鉴权 CORS `*`——`POST graph/<s2id>` 免费建图。Prior works = 图内被引最多者，Derivative works = 引用图内节点最多者。

**Inciteful**（单人开发者，Rust 后端）：**本赛道算法栈最全、架构最透明的实现**。OpenAlex 子集入库；每个 seed 查询实时建 depth-2 局部图（典型 1–5 万节点），然后**物化成一个独立 SQLite 库**（papers/authors/FTS5/metadata 四表，缓存 24h），前端所有榜单通过 HTTP 发裸 SQL 查这个库。指标五件套全标准算法：**PageRank（重要性）+ Adamic/Adar（耦合相似，共同引用按 1/log 被引 加权）+ Salton 余弦（共被引）+ BFS distance + num_citing（综述识别）**，零 ML。多 seed 用「虚拟节点」trick（造一个 cites 全部 seed 的节点，相似度相对它算）。Literature Connector = 全图双向 BFS 找最短路径。API 面 `graph.incitefulmed.com` 完全免鉴权实测可用（连 `SELECT sqlite_version()` 都执行）——生产上不该照搬裸 SQL 暴露，但「每查询物化视图」的 schema 设计可直接当模板。

**ResearchRabbit**（2021 西雅图，2025-05 被 Litmaps 收购）：310M+ 语料（Crossref+S2+OpenAlex 去重，周更）。算法 = seeds（≤50 免费/≤300 付费）→ 候选扩展（1–2 跳直引 + 共享 refs + 共享被引 + 共享作者 + 语义相似）→ **connectedness 归一化排序**——核心无 LLM。Swift 后端（CodingKeys 报错为证），全端点鉴权无公共 API，免费档功能完整。

**Litmaps**（新西兰 2016，收购 RR 后同源整合）：270M+ 语料。文章记录内嵌 `forwardEdges`/`backwardEdges` 整数数组 + 多源 ID 数组（openAlexIds/magIds/semanticScholarCorpusIds/dois/arxivIds）。三种算法模式：`shallow`（共享引用/被引，默认）、`authorFiltration`、`semantic`（LLM）。异步 search job API（POST→searchResultId→轮询）；**Monitor = 把搜索配置存下来对新论文定期重跑**——「持久化发现查询」的工业化形态。Swift 后端；api.litmaps.com 有免鉴权读端点。实测发现语料混有 spam 记录——自建方需要质量门。

**Scinapse / Pluto Labs**（首尔）：**唯一全押引用图的商业产品**。自研 agent 跑在 2.5 亿 + 引用图上，官网明写定位「Text embeddings find the right topic but miss the specific research agenda」。其 arXiv:2605.07158 论文是本调研最重要的实证：358 万篇论文上建增广图（直引 + BC≥3 Salton 加权剔热门 + CC≥3 剔综述型，共 1.53 亿边），Leiden CPM 两级社区（L1 子领域/L2 研究议程）；**四个 SOTA embedding 在 L2 议程级 top-10 同区率仅 15–21%，而「BM25 + 被引数重排」这种刻意简单的探针就能拿 59.6% top-1 L2 命中**。即：embedding 找得到同主题，找不到同议程——引用图路线的理论背书。

### 语句级系（引用边的信息密度天花板）

**scite.ai**（2018 纽约，2023 被 Research Solutions $14.8M 收购）：把「A 引 B」升级成「**带上下文 + 意图分类 + 章节位置的语句级三元组**」。管线四步全开源件拼装：全文双轨获取（Unpaywall 收割 + **30+ 出版商全文索引协议**——这是真壁垒）→ GROBID（PDF）/Pub2TEI（XML）抽引注 → biblio-glutton 匹配 DOI（PDF 源 ~70%、XML ~95% 端到端）→ **SciBERT 三分类**（supporting/mentioning/contrasting，~5 万条双人专家标注，disputing 稀有类 F 0.59；全部十几亿条语句推理跑在单台 GTX 1080Ti 上）。资产：32M+ 全文源、1.6B 语句、190M 元数据。设计精华：tally（语句数）与 citingPublications（出版物数）双口径分离、按引注所在章节统计、editorial notices 四源聚合、SJI 期刊榜（USI 公式）、67 端点 API + MCP server。**复制性评估：管线可全复刻，且 LaTeX 源侧引注定位零误差——有 LaTeX 者做语句级图比 scite 的 PDF 路径天然更准**；缺口只剩全文覆盖（OA ~30%）与标注数据（2026 年可 LLM 蒸馏替代）。

### 大平台内置推荐（通用配方）

| 平台                          | 配方                                                                                                                                           | 引用图用法                                                                        |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Google Scholar                | Related articles（引用数是最重排序因子）+ My updates（**用你的论文列表当 profile**：内容 + 引用图 + 时间漂移 + 合作者四信号）+ citation alerts | 核心信号之一                                                                      |
| Semantic Scholar              | Recommendations API（正负例 paperIds，≤500）+ Research Feeds（folder=正例、not-relevant=负例，日更）                                           | SPECTER 系 embedding——**引用图被蒸馏成训练信号**而非在线特征；推荐池只限近 3 个月 |
| MAG（已停运，最完整公开配方） | 全库 1.6 亿篇逐篇预计算静态推荐列表，CcB（共被引）+CB（内容）加权混合，novelty–authority 旋钮                                                  | 共被引支路与人工评分强相关                                                        |
| Mendeley                      | 用户文库 co-readership 协同过滤，混合最佳 ~70% precision                                                                                       | 引用=弱信号，readership=主信号                                                    |
| NASA ADS                      | **8 种二阶算子**（见下）+ oracle_service 个性化                                                                                                | 算子级暴露，设计最优雅                                                            |
| ResearchGate/ACM/IEEE         | 内容 + 社交网 + 共读混合                                                                                                                       | 引用仅成分之一                                                                    |

**ADS 二阶算子是引用图查询语言的最佳设计范本**：`citations(q)`/`references(q)`（集合沿边变换）、`useful(q)`（集合的参考文献按频次聚合→领域方法基石≈耦合聚合）、`reviews(q)`（引用集合者按频次聚合→综述≈共被引聚合）、`similar(q)`（文本）、`trending(q)`（读者共读——ADS 独有，需使用日志）、`topn(N,q)` 嵌套组合；`entdate` 时间截断 + 持久化查询 = myADS 通知。这套「集合→算子→集合」的代数完全可以在自建图上复刻。

### AI 检索系（对照组）

Elicit（138M）、Consensus（220M）、SciSpace（280M）、Keenious（OpenAlex 精选 181M）四家把引用只当**标量质量信号**（被引数/FWCI/SJR 进重排），图结构零使用。**Undermind** 是例外：agentic 迭代探索显式**沿引用链追踪**（embedding 召回候选→LLM 决定沿哪些 citation trail 滚→capture-recapture 估计覆盖率），证明「LLM 推理 × 引用链」是可产品化的形态。

### 开源与工具系（可直接抄的实现）

- **Citation Gecko**：~600 行纯前端闭环——seeds→Crossref 批量 metadata+refs→OpenCitations 逐 DOI citations→本地图→**`seedsCitedBy`（被多少 seed 引=奠基作）/`seedsCited`（引了多少 seed=同领域新作）双指标排序**，零 embedding。
- **Local Citation Network**：四源抽象层（OpenAlex `cites:`/`cited_by:` 过滤批查、S2 batch ≤500 ids 且有 citations≤9999 坑、Crossref 仅出边）、Top Cited/Top Citing 局部计数排序、**完整度量化指标**（有 refs 的 seed 占比）、按年份分层布局、RICS 间接引用扩展（coCited/coCiting 两档）。
- **Zotero Cita**：4 indexer（OC Meta/Index v2、OpenAlex——记得把 `10.48550/arxiv.*` 映射回 arXiv ID、S2 search/match 标题解析、Crossref）+ PID 消歧匹配器（ID 冲突否决 + 年差≤1+ 首作者）+ 剔除自引边 + **可写回 Wikidata P2860**。
- **Scholia**：证明「一个 SPARQL 端点 + 模板化查询页」即可撑起学术画像站；P2860 是唯一可写回的开放边源，CiTO 是唯一大规模引用意图标注。
- **litstudy**：BC/CC/耦合/共著网络的最小正确实现（各 ~40 行 networkx）。
- **paperscape**：**史上唯一做到全 arXiv 规模的引用图地图**（2011 至今活）：每日 arXiv TeX/PDF 自抽边（抽取代码闭源，arXiv 内匹配率 38%）、Barnes-Hut N-body 三力布局（C 实现 MIT 开源，`M=0.2+0.2·cites`）、Go 瓦片服务、按年 CSV dump 公开。证明全 arXiv 引用图不仅可行还能服务 15 年。
- **文献计量桌面工具**：VOSviewer（association strength 归一化 `s_ij=c_ij/(w_i·w_j)`、SLM 聚类、原生 OpenAlex API）、CiteSpace（Kleinberg burst、betweenness、sigma、LLR 标注、Pathfinder 剪枝、timeline 视图）、CitNetExplorer（百万级时间分层下钻）、bibliometrix、CRExplorer（RPYS）——11 项可移植算法清单见 14 号报告。

### 中文生态（空白即机会）

AMiner（智谱/清华 KEG）：引用关系按次卖 ¥0.10/call，图谱能力全进了自家搜索/画像，**没有独立引用发现产品线**；OAG 数据集免费给（见数据源表）。X-MOL = 期刊订阅推送器（无引用图）；文献鸟 Stork 的 citenet 是中文世界**唯一产品化的引用网络发现件**（关键词→实时引用网，x 轴=时间、节点=领域内归一化被引、Top N% 过滤，¥800/年）。**中文侧没有 Connected Papers 级产品，「引用图谱发现」对中文用户反而是未被既有习惯绑架的新鲜卖点。**

## 算法谱系与证据强度

文献 lane 把方法学证据链完整复核了一遍（30+ 断言逐条核），核心结论：

**三种基本图关联型的性能分工**（Boyack & Klavans 2010 在 215 万篇上的对照实验 + Shibata 2009 前沿侦测口径）：

| 方法            | 输入         | 新论文冷启动             | 强项                 | 弱项                 |
| --------------- | ------------ | ------------------------ | -------------------- | -------------------- |
| **书目耦合 BC** | 参考文献列表 | **优**（发表即有全量边） | 聚类准确性冠军       | 静态、不反映后续评价 |
| **共被引 CC**   | incoming 边  | **差**（无被引=无边）    | 经典配对越陈越准     | 前沿侦测最慢         |
| **直接引用**    | 引用边       | 差（incoming=0）         | **新兴前沿侦测最快** | 稀疏                 |

**排序与质量层的证据**：

- PageRank 在引用图上要改参：CiteRank 证明需 **d≈0.5 + 年龄偏向 teleport（τ≈2.6 年）**——论文有年龄，老节点会天然堆积概率质量；ArticleRank 修正出度偏置。局部子图 PageRank 是候选集排序的现成武器。
- **~85% 的引用是装饰性的**（Pride & Knoth：真正 influential 仅 10.3–17.9%；S2 的 `isInfluential` 字段即此谱系产品化）。判别 top 特征 = 正文 mention 次数与被引摘要相似度——**这又回到「有全文者的边可以带权重，纯元数据玩家不能」**。
- 自引全库均值 ~5% 但尾部极端（1822 名作者 >50%）——建边时必须打 `author_sc` flag（OpenCitations 白送这个字段），排序可选剔除；Citeomatic 实证 metadata 特征会让模型学到自引捷径，必须显式去偏。
- 跨领域榜单必须场归一化（RCR/FWCI 型除以同领域期望），否则引用体量差把榜单变成单一学科榜。
- 评测代理任务事实标准：**abstract→reference-list 重建**（被遮 refs 当 ground truth）+ citation holdout，指标 P/R/F1@k + MRR——不需要用户行为数据即可离线 benchmark。

## 工程现实：规模根本不是问题

工程 lane 用实测 manifest 与采样把成本算穿了：

**arXiv 子图（~316 万节点）是单机问题**：arXiv 内边估 40–70M 条 → u32 边表 ~560MB、CSR ~300MB；SPECTER 768 维向量 f32 全量 ~9.8GB（f16/量化 2.5–5GB）；topK 预计算（top50×全节点）~2GB 一晚跑完。**一台 32GB RAM VPS（$40–80/月）同时扛图查询+ANN+API**。

**全图（2.4B 边、2–3.3 亿节点）也只是一台大内存机器的问题**：边表 parquet ~20GB、内存 CSR 10–20GB RAM；745GB OpenAlex jsonl 抽边单机 4–10 小时。**不要上 Neo4j**——邻接遍历用 CSR/DuckDB 便宜两个数量级，只有多跳图算法才值图库，而本场景用不上。

**更新成本**：OpenAlex works 文件按 `updated_date` 分区（实测 2446 个分区），季度增量只重下新分区（几十 GB 级），不必全量重导。新论文出边滞后用 LaTeX 自抽补（每篇 <0.1 CPU·s，把「新论文无 similar」窗口从数周压到零）。

**三路线成本模型**：A 全自建（快照免费 + 一次性算力，风险=快照新鲜度）；B 全骑托管 API（零设施但 OpenAlex 免费档 ~1 万 list 调用/天拉全 arXiv 要 32 天、S2 无 key 实测不可用、`related_works` 黑盒且残破——**对方改算法即死**）；C 混合（快照打底 + 自抽边补新+API 兜底）。**唯一没有硬依赖风险的是 C。**

## 完全形态应该怎么做

综合 20 个 lane 的证据，给出可辩护的五层架构：

### 1. 数据底座：OpenAlex 快照为主干，三源交叉校验

- **主干 = OpenAlex 季度快照**（CC0、745GB、免账号、`updated_date` 分区天然增量）：取 works 的 `referenced_works`/`cited_by_count`/元数据，过滤 arXiv source（S4306400194）+ `10.48550` DOI 映射出自图。
- **校验与补全 = OpenCitations Index**（CC0、边自带 `author_sc`/`journal_sc` 自引标志——白拿）+ OpenAIRE product_Cites（备选第二源）。
- **增强 = S2 datasets**：citations 的 intent/influential/contexts 属性（全 2.4B 边带属性的独一份）、embeddings-specter_v2（按 paper-ids join 回 arXiv 子集，只取 ~3M 条 ~10GB 而非全量 840GB；单篇还有 `fields=embedding.specter_v2` 白嫖通道）。需申请免费 API key——匿名共享池实测 429 命中率 >80%，不可做生产依赖；S2 新论文收录延迟 ≤10 天。
- **冷启动 = unarXive permissive 子集**（1.9M 篇 63M refs 已链 OpenAlex）——今天就能下，先建图再迭代。
- **独有资产 = LaTeX 自抽边**（`.bbl`/`\bibitem` 直解，不必走 LaTeX 全转换）：填 arXiv 出边缺口 + 新论文即时入图 + **语句级引文上下文**（mention 位置/次数/章节）——这是相对所有 PDF 侧玩家与纯元数据玩家的结构性优势，也直接是语句级图层的原料。

### 2. 核心算法栈：BC 打底 + 直引保速 + CC 懒算

- **BC（bibliographic coupling）为核心相似度**：新论文 day-0 可用、聚类准确性文献冠军；实现=ref-list 倒排 join，Adamic/Adar 加权（共享冷门引用权重高）比裸计数好。
- **直接引用边保留双向**：出边=相似候选源、入边=被引追踪与前沿侦测（新前沿侦测最快信号）。
- **CC 只做懒增强**：对存量老论文按需算（Inciteful 的 Salton 共被引分就是局部算），不进新论文路径。
- **embedding 为补充召回**：SPECTER2 proximity 向量 ANN topK 兜语义模糊查询与无边冷启动；注意 Pluto 实证 embedding 在议程粒度只有 15–21%——做召回不做裁决。**最终分 = α·BC/Adamic-Adar + β·共被引/Salton + γ·cosine + 被引数质量项**。

### 3. 排序与质量层

- 候选集内**局部 PageRank（d≈0.5、年龄偏向 teleport τ≈2.6yr）**压「老而不重要」；副排序暴露原始被引数 + 场归一化分（除以同领域同年期望）。
- **语句级加权是差异化档位**：凡 LaTeX 源可抽的边带 mention count/位置/章节——先把「引用数」升级成「影响力引用数」（Pride&Knoth 的 10–18% 去噪逻辑）；有余力再上 LLM 蒸馏的 supporting/mentioning/contrasting 意图分类（scite 当年 5 万人标，今天成本骤降）。
- **护栏**：边打自引 flag（OC 数据白送 + 作者交集自算），排序默认剔除或降权；spam/合并事故记录需要质量门（Litmaps 语料实测有 spam；OpenAlex 头部论文有合并事故，名文要走兜底校验）。

### 4. 产品形态：照抄已验证的三个件

- **类似 Inciteful 的 per-seed 物化视图**：seed（支持多 seed 虚拟节点）→ 局部图 → Similar/Important/Review/Recent 分栏榜 + 作者/机构/期刊聚合榜；schema 先行富字段后补。
- **ADS 式算子查询语言**：`citations/references/useful/reviews/similar/topn` 集合变换 + `entdate` 时间截断——既是 power-user API 也是通知系统的底座（持久化查询 + 自动时间窗=Litmaps Monitor/myADS 的通用形态）。
- **Connector**：全图双向 BFS 最短路径（Inciteful 实测「没见过连不上的」，arXiv 图密度更高只会更短）。
- 图谱可视化参照 LCN 分层时间布局 + paperscape 的 Barnes-Hut 全图（若做全网地图）。

### 5. 分阶段路线

| 阶段          | 内容                                                                                                      | 验证什么                 |
| ------------- | --------------------------------------------------------------------------------------------------------- | ------------------------ |
| MVP（1–2 周） | unarXive 子集 + OpenAlex works 分区拉取 → arXiv 子图落 parquet/DuckDB → `similar(paper)=BC+耦合 topK` API | 边质量与覆盖是否够撑体验 |
| 排序层        | 加 Adamic/Adar+Salton+局部 PageRank+ 归一化分；citation holdout benchmark 上线                            | 排序是否显著优于裸被引数 |
| 新鲜度        | LaTeX 自抽边管线（增量 CSR/WAL→定期 bake）；新论文 day-0 similar                                          | 独家能力上线             |
| 语句级        | LaTeX 引文上下文抽取→mention count 边权→LLM 意图分类                                                      | 全赛道最高边质量         |
| 产品面        | per-seed 视图 + 算子 API + connector + Monitor                                                            | 完整形态                 |

**定价/壁垒判断**：数据底座全免费（CC0/ODC-BY），壁垒只剩两个——**LaTeX 语句级边资产**（PDF 玩家补不平）与**新鲜度**（自抽边让新论文即时可推荐，快照玩家滞后数月）。这与 scite 靠出版商协议建壁垒是同构打法，只是我们的协议是 arXiv 源码本身。

## 附录：lane 报告索引

| 编号 | 文件                     | 内容                                                                                          |
| ---- | ------------------------ | --------------------------------------------------------------------------------------------- |
| 01   | `01-openalex.md`         | OpenAlex 实测：体量/字段/freemium 计费转向/快照分区/related_works 不可用证据                  |
| 02   | `02-s2.md`               | Semantic Scholar 三层 API 全实测：边属性模型/embedding 白嫖通道/匿名池 429 证据/数据集 schema |
| 03   | `03-opencitations.md`    | OpenCitations Index/Crossref/Lens/OpenAIRE/Wikidata：边规模、API、arXiv 缺口实测              |
| 04   | `04-domain.md`           | INSPIRE-HEP/ADS/iCite/EuropePMC/zbMATH 领域库                                                 |
| 05   | `05-arxiv-pipe.md`       | arXiv 五渠道 + GROBID vs LaTeX 抽取管线横评 + unarXive/refcat 资产                            |
| 06   | `06-connected-papers.md` | Connected Papers 全逆向（算法参数/CPGR 格式/免鉴权端点）                                      |
| 07   | `07-researchrabbit.md`   | ResearchRabbit 逆向（seed→扩展→connectedness，Swift 后端）                                    |
| 08   | `08-litmaps.md`          | Litmaps 逆向（内嵌边数组/三算法模式/Monitor）                                                 |
| 09   | `09-inciteful.md`        | Inciteful 全逆向（per-query SQLite/SQL-over-HTTP/五指标栈/BFS connector）                     |
| 10   | `10-oss-tools.md`        | Gecko/LCN/Zotero Cita/Scholia/litstudy 源码级画像 + OC v2 实测                                |
| 11   | `11-scite.md`            | scite 全逆向（管线四步/标注与模型演进/67 端点 API/收购细节）                                  |
| 12   | `12-ai-search.md`        | Elicit/Consensus/Undermind/SciSpace/Keenious/Scinapse 对照                                    |
| 13   | `13-platform-recsys.md`  | Scholar/S2/MAG/ResearchGate/Mendeley/ADS/ACM 推荐配方                                         |
| 14   | `14-bibliometrics.md`    | VOSviewer/CiteSpace/CitNetExplorer/bibliometrix 等桌面工具                                    |
| 15   | `15-ads-inspire.md`      | ADS 二阶算子全表 + oracle_service + INSPIRE 策展引用数据                                      |
| 16   | `16-arxiv-maps.md`       | paperscape/arxiv-sanity/Argo Scholar/GitHub 小件                                              |
| 17   | `17-citation-rec.md`     | 算法文献谱系（BC/CC/直引对照实验、PageRank 系、上下文加权、自引治理）                         |
| 18   | `18-embeddings.md`       | SPECTER2/SciNCL/ProNE/CBF×GB ensemble + S2 数据集实测清单                                     |
| 19   | `19-china.md`            | AMiner/OAG/X-MOL/文献鸟/中文引文库 + MAG 遗档                                                 |
| 20   | `20-engineering.md`      | 规模核算：arXiv 子图单机/全图大内存机/三路线成本模型                                          |

## 附录：调研任务书

本报告是下述调研任务的产出归档，任务书原文要点留存备查。

调研背景：texlate（开源「arXiv LaTeX 源 → LLM 段落级翻译 → ctex 重编译中文 PDF」项目，产品代码 `src/texlate/`）的产品方向扩展为「不止翻译，还要基于引用数与引用图谱做论文推荐/发现」——目标是最终拥有类似 alphaXiv similar-papers、Connected Papers 那一档的发现层能力。本轮是纯调研，为后续架构决策供弹药。

已验证可直接引用的前提：alphaXiv 的 references/overview 等富产物覆盖率很低（随机论文 ~7–20%，老 ID 0%），只能机会型白嫖——逆向细节见同目录 `2026-09-19-alphaxiv-reverse.md`；texlate 有每篇论文的 LaTeX 源（`.bbl`/`.bib`/`\bibitem`），引用边可自抽——这是相对 PDF 侧玩家的结构优势。

调研范围三块：**数据源层**（OpenAlex、Semantic Scholar API+datasets/S2ORC、OpenCitations、Crossref、arXiv 官方渠道、INSPIRE-HEP/ADS/PubMed/DBLP 领域库、Lens.org 等——谁有引用边、被引数、arXiv ID 含 `astro-ph/` 老 ID、bulk dump、license、更新延迟）；**算法与产品层**（Connected Papers、ResearchRabbit、Litmaps、Inciteful、scite.ai、alphaXiv 各自怎么算「相关论文」：co-citation / bibliographic coupling / SPECTER 类 embedding / 混合；托管推荐 API 现状；可直接用的 embedding 资产）；**工程层**（全 arXiv ~250 万篇上亿边规模的 bulk dump 体量、存储形态、预计算 vs 按需、更新节奏；S2ORC / OpenAlex snapshot / GROBID 现成管线角色；「自建全图 / 骑托管 API / 混合」三条路线真实成本对比）。

方法要求：WebSearch/WebFetch 调研 + `curl` 直接探 API 验证（限流、字段、覆盖率主张尽量实测，不抄二手数字）；实测验证过的标实测，查不到的标「未验证」；报告必须落到「texlate 下一步该怎么走」的具体建议上。
