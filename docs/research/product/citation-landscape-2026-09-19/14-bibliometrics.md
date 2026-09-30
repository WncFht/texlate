# Lane 14：文献计量工具箱（VOSviewer / CiteSpace / CitNetExplorer / bibliometrix / PoP）

> **结论**：三大件的算法栈全部有论文级文档、可拆到公式级——association strength 归一化、VOS 布局（加权 MDS/SMACOF）、SLM 模块度聚类、Kleinberg burst、Pathfinder 剪枝、LLR 簇自动标注、时间轴 drill-down——几乎可原样移植到引用图谱发现 web 服务；「进分析层先把各源数据统一到一个规范 schema」是所有严肃工具的共同选择。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## 谱系与共同工作流

文献计量工具按输出形态分三类[^epi2020]：通用计量与绩效分析（Publish or Perish、Sci2、pySciSci、pybliometrics）、科学图谱映射（VOSviewer、CiteSpace、CitNetExplorer、bibliometrix）、专项小件（CRExplorer、HistCite 等）。共同工作流高度一致：**数据库导出（WoS 格式为事实标准）→ 引用/共现矩阵 → 归一化 → 网络构建 → 布局 + 聚类 → 可视化探索**。CiteSpace 内部把一切数据源（Scopus/CNKI/CSSCI/Lens/Dimensions/PubMed/arXiv/ADS/NSF）先转换为 WoS 字段格式再分析[^citespace-notes]；bibliometrix 数据框列名同样沿用 WoS Field Tag 编码[^bibliometrix-cran]。

## VOSviewer：归一化 → 布局 → 聚类的完整管线

CWTS（莱顿）van Eck 与 Waltman 开发的 Java 桌面程序，算法文档最完备[^vaneck2010]。五种网络全支持：合著、共现、直接引用、文献耦合、共被引；输入三路：数据库导出文件、文献管理器文件、在线 API（桌面版可交互查询 OpenAlex/Crossref/Europe PMC，S2/OpenCitations/Wikidata 用于给定 DOI 集构图）[^vos-features]。

**归一化**默认 association strength[^vaneck2009]：$s_{ij} = c_{ij}/(w_i \cdot w_j)$——实际共现与独立假设下期望共现之比，等价 probabilistic affinity index，作者论证过优于 cosine 与 Jaccard；另有 full vs fractional counting 选择（fractional 把多作者/多引用摊薄，抑制高产出节点支配）[^perianes2016]。

**布局** = VOS mapping：最小化 $V = \sum_{i<j} s_{ij}\|x_i - x_j\|^2$（约束平均距离=1）的加权 MDS，SMACOF 求解；暴露为 Attraction/Repulsion 两整数参数[^vos-chapter][^hal-chapter]。

**聚类**与布局统一框架：最大化带分辨率参数 γ 的加权模块度，优化器用 **Smart Local Moving（SLM）**——簇内移动局部子网络而非单节点，比 Louvain 收敛质量好[^waltman2010unified][^waltman2013slm]。

**VOSviewer Online**（app.vosviewer.com）是纯 viewer：MIT 开源、React+D3，npm 包 `vosviewer-online` 提供 `<VOSviewerOnline data={...} parameters={...} />` 组件供第三方嵌入——Dimensions、Zeta Alpha 已在复用[^vos-online-gh]。VOSviewer 参数细节经 VOSviewer Online 官方文档站与手册文本交叉验证[^vos-online-cp][^vos-manual165]。

## CiteSpace：时序 + 结构双视角

陈超美开发，理论框架「research front（施引）↔ intellectual base（被引）」时变对偶[^chen2006]；现已收费（$65–155/年）[^podia]。主打**文档共被引网络（DCA）**，三支柱指标[^chen2006jasist]：

- **Kleinberg burst detection**：引文流建模为多状态自动机，探测「被引突然飙升」——新兴前沿的直接信号；参数 α（状态切换代价）、γ（级间增长率）、min duration[^podia-burst]。
- **Betweenness centrality**：高中介节点标紫环=「范式转移潜在转折点」。
- **Sigma**：(centrality+1)^burstness 型综合标量，单值排序高潜论文。

配套件：**Pathfinder 剪枝**（三角不等式检验，直接边不强于多跳路径则删，处理稠密共被引网）；**timeline/time-zone/cluster 三视图**；簇自动标注用施引文献标题/摘要做 **LLR（对数似然比）** 抽词（默认且效果最好）[^chen2010]；Dual-map overlay 期刊级学科流向；**SVA**（加一篇论文前后模块度变化率，预测变革潜力）。

## CitNetExplorer：直接引用网的时间轴探索

van Eck & Waltman 2014，继承 HistCite「algorithmic historiography」路线：**直接引用网 + 时间轴布局**，纵轴出版年分层、横轴引用关联度[^vaneck2014cne]。HistCite 只能数百篇，CitNetExplorer 撑**百万级**节点。核心交互 **drill-down + expansion**：全图逐层下钻到子网再反向扩张补齐；分析件含连通分量、模块度聚类、core publications、论文间最短/最长引用路径。

## bibliometrix / biblioshiny：可编程全流程

R 包（GPL-3），开源可编程性最强[^aria2017]。数据流矩阵代数式：Document×Attribute 二分矩阵→矩阵乘法→各类网络[^bibliometrix-site]。biblioshiny 按 SAAS 方法论组织：WoS/Scopus/OpenAlex/Lens 等导入（OpenAlex/PubMed 走 API 直连）、跨库 citation matching、**自动生成 PRISMA 流程图保证选样可审计**；指标三层含 RPYS 与 Life Cycle logistic 阶段判定；thematic map 四象限战略图[^biblioshiny][^bibliometrix-cran]。

## 指标面板与小件

**Publish or Perish** 不做图做指标面板：h/g/e-index、hI 族（hI,norm 按作者数归一）、hI,annual（年均增量修正学科资历差）、AWCR 年龄加权——这套清单本身就是「引用数展示」的成熟需求文档[^pop-metrics]。**CRExplorer** 是 RPYS（参考文献出版年谱找领域历史根）专用工具，附带 **cited-reference 消歧**——同一 CR 在库里有多写法变体是真实噪声源[^crexplorer]。pybliometrics/pySciSci（均 MIT）是数据访问与关系表层[^pybliometrics][^pyscisci]。

## 可移植算法清单

按优先级：①三边构造（直引/耦合/共被引分开建）+ association strength 归一化；②VOS 布局（万级以下 SMACOF 够用，更大退 OpenOrd）；③SLM 模块度聚类 + LLR 自动标簇名；④时序三件套（Kleinberg burst / RPYS / timeline view）；⑤betweenness+sigma+SVA 转折点发现；⑥CitNetExplorer 时间轴 drill-down 交互范式；⑦PoP 指标面板清单；⑧规范 schema 先行（web 服务应以 OpenAlex work 模型为规范层）；⑨cited-reference 消歧（自抽边必须配 CR 标准化）；⑩PRISMA 式可审计管线；⑪VOSviewer Online 的「React 组件+JSON 格式」最小嵌入形态。

**许可证边界**：VOSviewer 桌面、CiteSpace、CitNetExplorer、PoP 均闭源，只能借算法（论文全公开）不可复用代码；可代码级复用的只有 VOSviewer Online（MIT）、bibliometrix（GPL-3）、pybliometrics/pySciSci（MIT）。

## 结论

文献计量界三十年积累的「归一化→布局→聚类→时序」方法栈是本调研里算法密度最高、文档最完备的可移植资产；工程上只需记住两条：schema 先统一到规范记录模型，以及引用边要配 CR 消歧与 full/fractional 口径选择。

### 参考文献

[^epi2020]: Moral-Muñoz J.A. et al. Software tools for conducting bibliometric analysis in science. _Profesional de la información_ 2020. [doi.org/10.3145/epi.2020.ene.03](https://doi.org/10.3145/epi.2020.ene.03)

[^citespace-notes]: CiteSpace 数据处理笔记（数据源转换至 WoS 格式清单）. [programmersought.com](https://www.programmersought.com/article/67413375716/)

[^bibliometrix-cran]: Help for package 'bibliometrix' (CRAN refman, v5.4.1). [cran.r-project.org](https://cran.r-project.org/web/packages/bibliometrix/refman/bibliometrix.html)

[^vaneck2010]: van Eck N.J., Waltman L. Software survey: VOSviewer, a computer program for bibliometric mapping. _Scientometrics_ 84, 523–538, 2010.

[^vos-features]: VOSviewer Features/Highlights 页（2026-09-19 实测）. [vosviewer.com/features/highlights/](https://www.vosviewer.com/features/highlights/)

[^vaneck2009]: Van Eck N.J., Waltman L. How to normalize cooccurrence data? _JASIST_ 60(8), 1635–1651, 2009.

[^perianes2016]: Perianes-Rodriguez A., Waltman L., van Eck N.J. Constructing bibliometric networks: full vs fractional counting. arXiv:1607.02452, 2016.

[^vos-chapter]: Waltman L., van Eck N.J. Visualizing bibliometric networks. [vosviewer.com/download/f-x2.pdf](https://www.vosviewer.com/download/f-x2.pdf)

[^hal-chapter]: Bibliometric network analysis chapter（SMACOF 求解 VOS 目标）. [hal.science](https://hal.science/hal-03408373v1/preview/493186_1_En_3_Chapter.pdf)

[^waltman2010unified]: Waltman L., van Eck N.J., Noyons E.C.M. A unified approach to mapping and clustering of bibliometric networks. _Journal of Informetrics_ 4, 629–635, 2010.

[^waltman2013slm]: Waltman L., van Eck N.J. A smart local moving algorithm for large-scale modularity-based community detection. _EPJ B_ 86, 2013.

[^vos-online-cp]: VOSviewer Online Docs — Control panel. [app.vosviewer.com/docs/user-interface/control-panel/](https://app.vosviewer.com/docs/user-interface/control-panel/)

[^vos-manual165]: Manual for VOSviewer 1.6.5/1.6.21. [1.6.5 PDF](https://www.vosviewer.com/documentation/Manual_VOSviewer_1.6.5.pdf) + [1.6.21 PDF](https://www.vosviewer.com/documentation/Manual_VOSviewer_1.6.21.pdf)

[^vos-online-gh]: neesjanvaneck/VOSviewer-Online（MIT、npm 包）. [github.com/neesjanvaneck/vosviewer-online](https://github.com/neesjanvaneck/vosviewer-online)

[^chen2006]: Chen C. CiteSpace II: Visualization and knowledge discovery in bibliographic databases. [pmc.ncbi.nlm.nih.gov/articles/PMC1560567](https://pmc.ncbi.nlm.nih.gov/articles/PMC1560567/)

[^chen2006jasist]: Chen C. CiteSpace II: Detecting and visualizing emerging trends and transient patterns in scientific literature. _JASIST_ 57(3), 359–377, 2006.

[^podia]: CiteSpace Podia 站（版本与价格，2026-09-19 实测）. [citespace.podia.com](https://citespace.podia.com/)

[^podia-burst]: CiteSpace Glossary — Burstness. [citespace.podia.com/glossary-burstness](https://citespace.podia.com/glossary-burstness)

[^chen2010]: Chen C., Ibekwe-SanJuan F., Hou J. The structure and dynamics of co-citation clusters. _JASIST_ 61(7), 1386–1409, 2010.

[^vaneck2014cne]: van Eck N.J., Waltman L. CitNetExplorer. _Journal of Informetrics_ 8(4), 802–823, 2014. [arxiv.org/pdf/1404.5322](https://arxiv.org/pdf/1404.5322)

[^aria2017]: Aria M., Cuccurullo C. bibliometrix: An R-tool for comprehensive science mapping analysis. _Journal of Informetrics_ 11(4), 959–975, 2017.

[^bibliometrix-site]: massimoaria/bibliometrix README. [github.com/massimoaria/bibliometrix](https://github.com/massimoaria/bibliometrix)

[^biblioshiny]: Biblioshiny 官方页（SAAS 工作流、OpenAlex/PubMed API、PRISMA）. [bibliometrix.org/biblioshiny/](https://www.bibliometrix.org/biblioshiny/)

[^pop-metrics]: Publish or Perish — Citation metrics. [harzing.com](https://harzing.com/resources/publish-or-perish/manual/using/query-results/metrics)

[^pybliometrics]: Rose M.E., Kitchin J.R. pybliometrics: Scriptable bibliometrics using a Python interface to Scopus. _SoftwareX_ 10, 2019.

[^crexplorer]: Thor A., Marx W., Leydesdorff L., Bornmann L. Introducing CitedReferencesExplorer. _Journal of Informetrics_ 10(2), 503–515, 2016.

[^pyscisci]: Gates A.J. et al. Reproducible science of science at scale: pySciSci. [barabasi.com](https://barabasi.com/media/2023-Gates-Reproducible-science.pdf)
