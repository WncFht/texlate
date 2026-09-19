# 文献计量工具箱调研

对「科学计量/文献计量」工具链做了一轮调研：重点把 VOSviewer、CiteSpace、CitNetExplorer 三大件的算法栈拆到公式级，外加 Bibliometrix、Publish or Perish、pybliometrics 与一众配套小件。这些工具多数是给「离线数据集 + 桌面交互」设计的，但其中的网络构造、归一化、布局、聚类、时序分析方法几乎可以原样移植到一个引用图谱发现的 web 服务上。

## 总览：工具谱系与定位

文献计量工具按输出形态大致分三类[^epi2020]：通用计量与绩效分析（Publish or Perish、Sci2、pySciSci、pybliometrics）、科学图谱映射（VOSviewer、CiteSpace、CitNetExplorer、SciMAT、bibliometrix）、以及专项小件（CRExplorer、HistCite、ScientoPy、metaknowledge）。三者的共同工作流高度一致：**数据库导出（WoS 格式为事实标准）→ 引用/共现矩阵 → 归一化 → 网络构建 → 布局 + 聚类 → 可视化探索**。CiteSpace 的做法最能说明问题——它内部把一切数据源（Scopus/CNKI/CSSCI/Lens/Dimensions/PubMed/arXiv/ADS/NSF）先转换为 WoS 字段格式再分析[^citespace-notes]；bibliometrix 的数据框列名同样沿用 WoS Field Tag 编码[^bibliometrix-cran]。这暗示一条工程结论：**进入分析层之前先统一到一个规范 schema，是所有严肃工具的共同选择**。

| 工具 | 形态 | 数据源 | 开源 | 核心网络类型 |
| --- | --- | --- | --- | --- |
| VOSviewer 1.6.x | Java 桌面 | WoS/Scopus/Dimensions/Lens/PubMed 文件 + OpenAlex/Crossref/EuropePMC API + Semantic Scholar/OpenCitations/Wikidata（DOI 集）+ RIS | 闭源免费 | 5 种全 |
| VOSviewer Online | React web | VOSviewer JSON（viewer） | MIT | 同上（只读渲染） |
| CiteSpace 7.x | Java 桌面（现收费 $65–155/年） | WoS 原生 + Scopus/CNKI/CSSCI/Lens/Dimensions/PubMed/arXiv/ADS/NSF 转换 | 闭源 | 文档共被引 + 混合网络 |
| CitNetExplorer | Java 桌面 | WoS | 闭源免费 | 直接引用网（时间轴） |
| bibliometrix + biblioshiny | R 包 + Shiny | WoS/Scopus/PubMed/OpenAlex/Lens/Dimensions/Cochrane + OpenAlex/PubMed API | GPL-3 | 全谱 + thematic map |
| Publish or Perish 8 | 桌面 + CLI | Google Scholar/Crossref/OpenCitations/Scopus/WoS/PubMed | 闭源免费 | 无图——指标面板 |
| pybliometrics | Python 库 | Scopus API | MIT | 无——数据访问层 |
| pySciSci | Python 库 | MAG/OpenAlex 等 | MIT | 关系表 + SciSci 度量 |

## VOSviewer：归一化 → 布局 → 聚类的完整管线

VOSviewer 是 CWTS（莱顿大学）van Eck 与 Waltman 开发的 Java 桌面程序，2010 年发表软件综述[^vaneck2010]，最新 1.6.21（2026-06-12）已支持 OpenAlex API key 认证与基于 OpenAlex 数据的 keyword/topic 共现图[^vos-home]。它是本 lane 里算法文档最完备的工具——所有技术细节都有对应论文。

### 支持的网络类型与输入

五种网络全支持：合著（co-authorship，作者/机构/国家三个层级）、共现（co-occurrence，关键词与标题摘要术语）、引用（citation，直接引用边）、文献耦合（bibliographic coupling，共享参考文献越多越相似）、共被引（co-citation，被同一文献引用越多越相似）[^vos-features][^vos-manual165]。输入分三路：数据库导出文件（WoS/Scopus/Dimensions/Lens/PubMed）、文献管理器文件（RIS/EndNote/RefWorks）、以及在线 API 交互查询——桌面版可直接查询 OpenAlex、Crossref、Europe PMC 的 API，Semantic Scholar、OpenCitations、Wikidata 则用于给定 DOI 集的网络构建[^vos-features]。实测 features 页（2026-09-19）明确写着 "These APIs can be queried interactively in VOSviewer"[^vos-features]。

### 归一化：association strength

VOSviewer 把所有网络按无向处理。建图第一步是对链接强度做归一化，默认用 **association strength**[^vaneck2009]：

$$s_{ij} = \frac{c_{ij}}{w_i \cdot w_j}$$

其中 $c_{ij}$ 是项目 $i,j$ 的共现/链接数，$w_i,w_j$ 是两者的总出现数或总链接数。其解释是「实际共现次数与独立假设下期望共现次数之比」，等价于 proximity index / probabilistic affinity index，作者专门论证过它优于 cosine 与 Jaccard[^vos-proc2009]。可选归一化还有三种：不归一化（不推荐）、fractionalization（对应同篇论文 Eq.13）、LinLog/modularity（与 LinLog 布局、modularity 聚类同源，不做额外归一化）[^vos-online-cp]。

另有一层 counting method 的选择：full counting（每个共现计 1）vs fractional counting（共著 N 个作者时每个作者计 1/N，引用多参考文献的论文时权重被摊薄）——用于抑制「高产出/高引用/多作者」节点的支配效应[^perianes2016]。

### 布局：VOS mapping technique

布局目标函数为：给定归一化相似度 $s_{ij}$，最小化

$$V(x_1,\dots,x_n) = \sum_{i&lt;j} s_{ij} \|x_i - x_j\|^2$$

约束条件是所有节点对的平均距离等于 1[^vos-chapter]。即「高相似节点靠近、低相似节点远离」的加权多维缩放（MDS 近亲），用 SMACOF 求解[^hal-chapter]。实际调参暴露为 Attraction/Repulsion 两个整数参数（推荐 2/1 或 2/0、1/0）[^vos-online-cp]。

### 聚类：参数化模块度 + SLM

聚类与布局是「统一框架」：同一吸引-排斥原理下，聚类等价于最大化带分辨率参数 γ 的加权模块度函数[^waltman2010unified]：

$$V(x) = \sum_{i&lt;j} \delta(x_i, x_j)\left(c_{ij} - \gamma \frac{w_{ij}}{2m}\right)$$

γ 越大簇越多。优化器不是 Louvain 而是其改进版 **Smart Local Moving（SLM）**——在每个簇内移动局部子网络而非单节点，收敛质量更好[^waltman2013slm]。暴露参数：clustering resolution、min cluster size、merge small clusters。该公式同时也给 LinLog 布局提供了一个统一解释。

### 术语图 NLP 与可视化

共现术语图带一层 NLP：从标题/摘要抽词后，用「relevance score」区分相关/非相关术语，剔除通用词[^vos-features]。可视化三视图：network visualization、overlay visualization（按年份/分数着色看演化）、density visualization；Google Maps 式缩放 + 智能标签防重叠。

### VOSviewer Online

app.vosviewer.com 的 web 版是**纯 viewer**：不开源数据源查询，消费 VOSviewer JSON 文件（桌面版 Share 上传后自动打开），MIT 协议开源（`neesjanvaneck/VOSviewer-Online`），技术栈 React + Material-UI + D3，并以 npm 包 `vosviewer-online` 提供 `&lt;VOSviewerOnline data={...} parameters={...} /&gt;` 组件供第三方嵌入[^vos-online-gh]——Dimensions 和 Zeta Alpha 的资助配置就在仓库里，说明这套组件已被商用平台复用。

## CiteSpace：时序 + 结构的双重视角

陈超美（Chaomei Chen）开发的 Java 应用，理论基础是「research front（施引文献）↔ intellectual base（被引文献）」的时变对偶[^chen2006]。曾长期免费，现已商业化：Standard $65 / Intermediate $110 / Advanced $155（1–2 年授权），Advanced 版含 "GPT-augmented cluster summarization"[^podia]。

### 分析对象与核心指标

主打**文档共被引网络（DCA）**——节点是被引文献，边是共被引强度；也支持作者共被引、混合节点（term/机构/国家）与混合边类型[^citespace-home]。三个支柱指标[^chen2006jasist]：

- **Kleinberg burst detection**：把引文流建模为多状态自动机，相邻 burst 级别对应指数增长的事件率。参数 α 控制状态切换代价（α 小→burst 多），γ 控制级间增长率，min duration 控制最短持续时间[^podia-burst]。用于发现「被引突然飙升」的论文/术语——这是探测新兴前沿的直接信号。
- **Betweenness centrality（Freeman）**：高中介中心性节点画紫色环，标记「范式转移的潜在转折点」[^chen2006jasist]。
- **Sigma**：综合中心性与 burst 的标量指标（(centrality+1)^burstness 型），用于单值排序高潜论文[^podia]。

### 网络剪枝与视图

- **Pathfinder 剪枝**：三角不等式检验——若一条直接边不强于替代多跳路径则删除，保时序生长模式优于 MST[^chen2006jasist]。这是处理稠密共被引网的关键。
- **cluster view / time-zone view / timeline view**：同一共被引网的三种投影；timeline view 把簇按时间横向展开，直接读出每个子领域的兴衰[^citespace-scopus]。
- **簇自动标注**：从施引文献的标题/摘要/关键词抽词，用 **LLR（对数似然比）**、LSI、MI 三种算法给簇打标签——LLR 默认且效果最好[^chen2010]。silhouette 值评簇同质性。
- **Dual-map overlay**：期刊级双图叠加——左图施引期刊组合、右图被引期刊组合，弧线显示学科间引用流向[^podia]。
- **Structural Variation Analysis（SVA）**：加入一篇论文前后簇间连接导致的模块度变化率，用于预测论文的「变革潜力」[^podia]；**cascading citation expansion**：沿引用链多级扩张检索。
- **数据源**：WoS 原生格式；Scopus（RIS 转换）、CNKI、CSSCI、Lens、Dimensions、PubMed、arXiv、ADS、NSF、Derwent 统一转换为 WoS 格式[^citespace-notes]。

## CitNetExplorer：直接引用网的时间轴探索

van Eck &amp; Waltman 2014 年发布[^vaneck2014cne]，继承 Garfield HistCite 的「算法史学」（algorithmic historiography）路线——**直接引用网 + 时间轴布局**：纵轴按出版年分层，横轴按引用关联度排布，揭示领域发展脉络[^vos-chapter]。HistCite 只能处理数百篇、默认画 top-30 被引；CitNetExplorer 能撑**百万级**节点[^vaneck2014cne]。

核心交互范式是 **drill-down + expansion**：从百万篇全图逐层下钻到百篇子网（如 scientometrics → h-index 专题），再按引用紧密度反向扩张补齐相关文献[^vaneck2014cne]。分析件包括：连通分量提取、Waltman–Van Eck 2012 模块度聚类（出版物级学科分类体系同方法）、core publications（网内被引 ≥ 阈值）、**论文间最短/最长引用路径**。输入吃 WoS 导出文件。

## bibliometrix / biblioshiny：可编程的全流程管线

R 包（GPL-3），Aria &amp; Cuccurullo 2017 JOI 论文[^aria2017]，是本 lane 开源可编程性最强的一件。数据流是矩阵代数式的：**Document × Attribute 二分矩阵 → 矩阵乘法得 Bibliographic Matrix → 共被引/耦合/合著/共词网络**，再喂 igraph/MCS 等[^bibliometrix-site]。新版 biblioshiny 按 SAAS 方法论（Search→Appraisal→Analysis→Synthesis）组织 Shiny 应用[^biblioshiny]：

- 数据管理：WoS/Scopus/PubMed/OpenAlex/Lens/Dimensions/Cochrane 导入转换；**OpenAlex 与 PubMed 走 API 直连**（openalexR/pubmedR 依赖，实测于 CRAN refman）[^bibliometrix-cran]；跨库 citation matching 对齐参考文献；自动生成 **PRISMA 流程图**保证选样可审计。
- 三层指标：Sources（Bradford 定律）、Authors（h-index/Lotka）、Documents（引文分析、**RPYS**、趋势主题）；Life Cycle Analysis 用 logistic 增长模型判领域所处阶段（萌发/增长/成熟/饱和）[^biblioshiny]。
- 知识结构三视角：conceptual（共词 + **thematic map**：Callon 式 centrality×density 四象限战略图 + thematic evolution 时序演化）、intellectual（文档/作者/期刊共被引 + historiograph + 文献耦合）、social（合著网 + 世界地图）[^biblioshiny]。
- 全文侧扩展：citation function analysis（background/method/comparison/critique 四类）、TF-IDF/RAKE/YAKE 抽词、IMRaD 结构分析、Biblio AI 摘要[^biblioshiny]。

## Publish or Perish / pybliometrics：指标与访问层

Publish or Perish（Anne-Wil Harzing，2006 起）不做图，做的是**指标面板**：一次检索返回 h-index、g-index、e-index、hI-index 三种个人变体（含 hI,norm 按作者数归一被引）、hI,annual（年均增量，修正学科与资历差异）、hA-index、AWCR 年龄加权等[^pop-metrics]。数据源覆盖 Google Scholar(+Profile)、Crossref、OpenCitations、Scopus、WoS、PubMed；带本地缓存减少 API 压力；有命令行版[^pop-cli]。对 web 服务的启示在**指标清单本身**——h/g/AWCR/hI,norm 这套面板是「引用数」展示的成熟参照系。

pybliometrics（Rose &amp; Kitchin, JOSS 2019）是 Scopus REST API 的面向对象 Python 封装：Search/Citation Overview/Author Retrieval/Abstract Retrieval 四类 API + 本地缓存[^pybliometrics]。同生态还有 streamlit 单文件应用 ScopusLit 可作形态参考[^scopuslit]。

## 配套小件与通用底座

- **CRExplorer**：RPYS（Reference Publication Year Spectroscopy，参考文献出版年谱）专用工具——按参考文献年份分布找领域历史根，并做 cited reference 消歧（同一 CR 在 WoS 里有多变体，是真实痛点）[^crexplorer]。
- **ScientoPy**：Python 开源，主题趋势分析 + 强预处理（WoS/Scopus 清洗合并）[^epi2020]。
- **Sci2 Tool**（Indiana CIShell）：150+ 算法的模块化工具箱，temporal/geospatial/topical/network 四分析轴，可插拔插件体系[^sci2]。
- **SciMAT**：预处理与 thematic evolution 强[^epi2020]；**BibExcel** 老牌预处理件。
- **pySciSci**（Barabási 组）：Python 科学学包，把 MAG/OpenAlex 等库建成 pub2ref/pub2author/pub2field 关系表，提供职业生涯级度量（hot streak 等）[^pyscisci]。
- **HistCite**（Garfield）：CitNetExplorer 前身，algorithmic historiography 概念源头[^vaneck2014cne]。
- **metaknowledge**（Python，JOI 2017）、**BiblioTools**、**Citan**：R/Python 库层补充[^pyscisci]。
- 通用网络工具：**Gephi**（OpenOrd/ForceAtlas2 布局对超大图更实用）、**Pajek**——VOSviewer 支持导出 GML/Pajek 互通[^vos-manual165]。

## 可移植算法清单

把一个「完整形态」的引用图谱发现 web 服务与上述工具对照，值得直接移植的按优先级：

1. **三边构造 + association strength 归一化**：直接引用、文献耦合、共被引三种边分开建，相似度统一用 $s_{ij}=c_{ij}/(w_i w_j)$——比 cosine/Jaccard 有论文级论证，且与聚类天然配套[^vaneck2009]。
2. **VOS 布局（加权 MDS）或力导图**：万级节点以下 SMACOF 完全够；更大规模可退 OpenOrd。Attraction/Repulsion 两参数已是最小调参面[^vos-chapter]。
3. **SLM 模块度聚类 + 分辨率参数 + min cluster size**：比裸 Louvain 多一个「局部移动」改进，有现成 Java/R 实现参照；LLR 从施引文献抽词自动标簇名是 CiteSpace 最被低估的可移植件[^chen2010][^waltman2013slm]。
4. **时序分析三件套**：Kleinberg burst（探测新兴前沿，α/γ/min-duration 三参数）、RPYS（历史根）、timeline/timezone view——把「引用图谱」从静态图升维成「领域演化史」[^podia-burst][^crexplorer]。
5. **中介中心性 + sigma + SVA**：转折点发现——betweenness 标紫环、sigma 单值排序、SVA 预测变革潜力，三个成本都很低[^chen2006jasist][^podia]。
6. **CitNetExplorer 交互范式**：时间轴分层布局 + drill-down/expansion + 最短/最长路径——直接引用网的最优交互模型，百万级可扩展[^vaneck2014cne]。
7. **指标面板**：h/g/e/hI,norm/hI,annual/AWCR + 领域归一化被引——PoP 的指标清单即需求文档[^pop-metrics]。
8. **WoS-schema 规范化**：所有工具最终都收敛到「一个规范记录模型 + 各源转换器」；web 服务应以 OpenAlex work 模型为规范层[^citespace-notes][^bibliometrix-cran]。
9. **cited-reference 消歧**：CRExplorer 证明同一条参考文献的写法变体是真实噪声源——自建引用边（如从 LaTeX/PDF 全文抽取）必须配 CR 标准化[^crexplorer]。
10. **可审计数据管线**：biblioshiny 的 PRISMA 流程图、filter 白名单、citation matching 记录——复现性就是可信度[^biblioshiny]。
11. **嵌入式可视化交付**：VOSviewer Online 证明「React 组件 + JSON 网络格式」是最小可嵌入形态；`&lt;VOSviewerOnline data={...}&gt;` 模式可直接抄[^vos-online-gh]。

许可证边界：VOSviewer 桌面、CiteSpace、CitNetExplorer、PoP 均闭源（CiteSpace 已收费），只能借鉴算法（论文全公开）不可复用代码；**VOSviewer Online（MIT）、bibliometrix（GPL-3）、pybliometrics/pySciSci（MIT）** 是仅有的可代码级复用件。

## 探针产物

- `tmp/citation-survey/bibliometrics/vos-features.html` / `vos-features.txt`：VOSviewer features 页原文（2026-09-19 实测），数据源与网络类型断言出处。
- `tmp/citation-survey/bibliometrics/vos-manual.pdf`：手册 PDF——实测 vosviewer.com 在本机代理下 TLS 不稳（多次 000/SSL EOF），改经 VOSviewer Online 官方文档站（app.vosviewer.com/docs，fetch 成功）与手册 1.6.5 镜像文本交叉验证参数细节[^vos-online-cp][^vos-manual165]。
- 其余断言均经 WebSearch/WebFetch 命中官方页面或论文原文，见参考文献。

### 参考文献

[^epi2020]: Moral-Muñoz J.A. et al. Software tools for conducting bibliometric analysis in science: An up-to-date review. *Profesional de la información* 2020. [doi.org/10.3145/epi.2020.ene.03](https://doi.org/10.3145/epi.2020.ene.03)
[^citespace-notes]: CiteSpace 数据处理笔记（数据源转换至 WoS 格式清单）. [programmersought.com](https://www.programmersought.com/article/67413375716/)
[^bibliometrix-cran]: Help for package 'bibliometrix' (CRAN refman, v5.4.1). [cran.r-project.org](https://cran.r-project.org/web/packages/bibliometrix/refman/bibliometrix.html)
[^vaneck2010]: van Eck N.J., Waltman L. Software survey: VOSviewer, a computer program for bibliometric mapping. *Scientometrics* 84, 523–538, 2010.
[^vos-home]: VOSviewer 官网（1.6.21 release notes，OpenAlex API key 与 keyword co-occurrence）. [vosviewer.com](https://www.vosviewer.com//)
[^vos-features]: VOSviewer Features/Highlights 页（2026-09-19 实测）. [vosviewer.com/features/highlights/](https://www.vosviewer.com/features/highlights/)
[^vos-manual165]: Manual for VOSviewer 1.6.5/1.6.21. [vosviewer.com/documentation/](https://www.vosviewer.com/documentation/Manual_VOSviewer_1.6.5.pdf)
[^vaneck2009]: Van Eck N.J., Waltman L. How to normalize cooccurrence data? An analysis of some well-known similarity measures. *JASIST* 60(8), 1635–1651, 2009.
[^vos-proc2009]: van Eck N.J., Waltman L. VOSviewer: A computer program for bibliometric mapping. *ISSI 2009 proceedings*. [issi-society.org](https://www.issi-society.org/proceedings/issi_2009/ISSI2009-proc-vol2_Aug2009_batch2-paper-15.pdf)
[^perianes2016]: Perianes-Rodriguez A., Waltman L., van Eck N.J. Constructing bibliometric networks: A comparison between full and fractional counting. arXiv:1607.02452, 2016.
[^vos-chapter]: Waltman L., van Eck N.J. Visualizing bibliometric networks (chapter, VOSviewer/CitNetExplorer 技术附录). [vosviewer.com/download/f-x2.pdf](https://www.vosviewer.com/download/f-x2.pdf)
[^hal-chapter]: Bibliometric network analysis chapter（SMACOF 求解 VOS 目标的描述）. [hal.science](https://hal.science/hal-03408373v1/preview/493186_1_En_3_Chapter.pdf)
[^waltman2010unified]: Waltman L., van Eck N.J., Noyons E.C.M. A unified approach to mapping and clustering of bibliometric networks. *Journal of Informetrics* 4, 629–635, 2010. [scholarlypublications.universiteitleiden.nl](https://scholarlypublications.universiteitleiden.nl/access/item%3A2885478/view)
[^waltman2013slm]: Waltman L., van Eck N.J. A smart local moving algorithm for large-scale modularity-based community detection. *EPJ B* 86, 2013.
[^vos-online-cp]: VOSviewer Online Docs — Control panel（normalization/attraction/repulsion 参数原文）. [app.vosviewer.com/docs/user-interface/control-panel/](https://app.vosviewer.com/docs/user-interface/control-panel/)
[^vos-online-gh]: neesjanvaneck/VOSviewer-Online（MIT、vosviewer-online npm 包）. [github.com/neesjanvaneck/vosviewer-online](https://github.com/neesjanvaneck/vosviewer-online)
[^chen2006]: Chen C. CiteSpace II: Visualization and knowledge discovery in bibliographic databases. *JASIST/PMC1560567*. [pmc.ncbi.nlm.nih.gov](https://pmc.ncbi.nlm.nih.gov/articles/PMC1560567/)
[^citespace-home]: CiteSpace 官网（功能与数据源说明）. [cluster.ischool.drexel.edu/~cchen/citespace/](http://cluster.ischool.drexel.edu/~cchen/citespace/)
[^chen2006jasist]: Chen C. CiteSpace II: Detecting and visualizing emerging trends and transient patterns in scientific literature. *JASIST* 57(3), 359–377, 2006. [cluster.cis.drexel.edu](http://cluster.cis.drexel.edu/%7Ecchen/citespace/doc/jasist2006.pdf)
[^podia]: CiteSpace Podia 站（版本与价格，2026-09-19 实测）. [citespace.podia.com](https://citespace.podia.com/)
[^podia-burst]: CiteSpace Glossary — Burstness（Kleinberg 参数 α/γ/min-duration）. [citespace.podia.com/glossary-burstness](https://citespace.podia.com/glossary-burstness)
[^chen2010]: Chen C., Ibekwe-SanJuan F., Hou J. The structure and dynamics of co-citation clusters: A multiple-perspective co-citation analysis. *JASIST* 61(7), 1386–1409, 2010.
[^citespace-scopus]: CiteSpace Blog: How to Handle Scopus Data in CiteSpace. [sourceforge.net/p/citespace/blog/2019/07/scopus/](https://sourceforge.net/p/citespace/blog/2019/07/scopus/)
[^vaneck2014cne]: van Eck N.J., Waltman L. CitNetExplorer: A new software tool for analyzing and visualizing citation networks. *Journal of Informetrics* 8(4), 802–823, 2014. [arxiv.org/pdf/1404.5322](https://arxiv.org/pdf/1404.5322)
[^aria2017]: Aria M., Cuccurullo C. bibliometrix: An R-tool for comprehensive science mapping analysis. *Journal of Informetrics* 11(4), 959–975, 2017.
[^biblioshiny]: Biblioshiny — Bibliometrix 官方页（SAAS 工作流、OpenAlex/PubMed API、citation matching、PRISMA）. [bibliometrix.org/biblioshiny/](https://www.bibliometrix.org/biblioshiny/)
[^bibliometrix-site]: massimoaria/bibliometrix GitHub README. [github.com/massimoaria/bibliometrix](https://github.com/massimoaria/bibliometrix)
[^pop-metrics]: Publish or Perish — Citation metrics（h/g/e/hI 族指标定义）. [harzing.com/resources/publish-or-perish/manual/using/query-results/metrics](https://harzing.com/resources/publish-or-perish/manual/using/query-results/metrics)
[^pop-cli]: Publish or Perish command line tools（数据源选项与缓存）. [harzing.com/resources/publish-or-perish/command-line](https://harzing.com/resources/publish-or-perish/command-line)
[^pybliometrics]: Rose M.E., Kitchin J.R. pybliometrics: Scriptable bibliometrics using a Python interface to Scopus. *SoftwareX* 10, 2019.
[^scopuslit]: odarroyo/ScopusLit（Streamlit+pybliometrics 对照功能表）. [github.com/odarroyo/ScopusLit](https://github.com/odarroyo/ScopusLit)
[^crexplorer]: Thor A., Marx W., Leydesdorff L., Bornmann L. Introducing CitedReferencesExplorer (CRExplorer). *Journal of Informetrics* 10(2), 503–515, 2016. [ideas.repec.org](https://ideas.repec.org/a/eee/infome/v10y2016i2p503-515.html)
[^sci2]: Sci2 Team. Science of Science (Sci2) Tool handout（算法清单）. [sci2.cns.iu.edu/docs/Sci2_Handout.pdf](https://sci2.cns.iu.edu/docs/Sci2_Handout.pdf)
[^pyscisci]: Gates A.J. et al. Reproducible science of science at scale: pySciSci（关系表设计与生态对比）. [barabasi.com](https://barabasi.com/media/2023-Gates-Reproducible-science.pdf)
