# Lane 17：引用推荐算法文献谱系

> **结论**：方法选型有四层文献对照实验背书——核心图用 BC+直接引用双轨（BC 冷启动最优且聚类准确性冠军、直接引用前沿侦测最快），排序用局部 PageRank+时间衰减（CiteRank d≈0.5/τ≈2.6yr）加领域归一化副排序，质量层用引用上下文加权（~85% 引用是装饰性的、mention count 是 top 判别特征），护栏层打自引 flag 防博弈。
> **状态**：时点证据（2026-09-19 口径）
> **日期**：2026-09-19

## 三种引用关联基本型

**书目耦合 BC**（Kessler 1963）：共享 ≥1 条参考文献即耦合，强度=共享参考文献数[^kessler63]。两个决定性性质：**发表时刻即固定**、**对新论文 day-0 可用**（刚上线零被引但参考文献列表完整）。

**共被引 CC**（Small 1973；Marshakova 同年独立提出）：被同一后续论文同引即共被引[^small73][^marshakova73]。Marshakova 给出贯穿领域的定性框架：**BC 是回顾性的（作者成文时的知识结构，静态），CC 是前瞻性的（共同体后来如何理解两文关系，随新文献持续重估）**——CC 对经典配对越陈越准，对新论文是冷启动盲区。

**直接引用**：ISI 1988 年就把 BC 做成产品功能 Related Records——「引用图→相似论文」的第一次工业化[^relrec]。

**对照实验**（两篇大样本、口径互补不矛盾）：Boyack & Klavans 2010（215 万篇）聚类准确性 **BC > CC > 直接引用**，BC+文本混合最好[^boyack10]；Shibata et al. 2009 新兴前沿侦测速度 **直接引用 > BC > CC**[^shibata09]——BC 画得准、直引发现得早。

## 评测与分类学

Beel et al. 2016（200+ 篇综述）：推荐方法分布**内容过滤 55%/协同过滤 18%/图方法 16%**，81% 系统完全不做用户建模[^beel16]。Färber & Jatowt 2020 的任务二分更有用：**local/context-aware（稿件占位符处该引什么）vs global（种子论文→相关集）**——发现类产品做的是 global[^farber20]。**评测代理任务事实标准**：abstract→reference-list 重建+citation holdout，指标 P/R/F1@k、NDCG、MAP、MRR（Bethard & Jurafsky 2010 确立，learning-to-retrieve MAP 28.7 比 TF-IDF +12.8）[^bethard10]——不需要用户行为即可离线评测。

## 引用上下文：从「引了」到「怎么引的」

- **CPA**（Gipp & Beel 2009）：两篇被引文献在引用方正文中出现位置越近关联越强——位置加权共被引；论文内 mention 次数、同句/同段是免费高质量信号（前提是有引用方全文）[^gipp09]。
- **意图分类**：Teufel 2006 首个监督 citation function 分类[^teufel06]；Jurgens et al. 2018 的 6 类 citation frame（background/motivation/uses/extends/compares/future）经远程监督扩到 134k 条且能预测未来引用量[^jurgens18]；scite 的 smart citations 是该谱系工业化形态。
- **influential citation**：Valenzuela/Ha/Etzioni 2015 监督分类器 P65@R90，是 S2 `isInfluential` 字段的产品基础[^valenzuela15]；**Pride & Knoth 2017：只有 10.3–17.9% 的引用真正 influential**，其余仪式性/装饰性，判别 top 特征是正文内 mention 次数与被引摘要相似度[^pride17]。含义重大：原始引用数把 ~85% 装饰引用与 15% 实质引用等权——能用上下文特征给边加权的系统有结构性质量优势。

## 影响力与归一化度量

- **PageRank 系**：Chen et al. 2007 在 35.3 万篇 PR 论文上捞出低被引高 PageRank 的「gems」[^chen07]；**CiteRank**（Walker et al. 2007）——论文有年龄故 teleport 偏好新论文（τ≈2.6 年）、**damping d≈0.5** 而非 Web 的 0.85（无环图上高 damping 会让概率质量堆积在祖先节点）[^walker07]；ArticleRank（Li & Willett 2009）分母改「自身出度+全网平均出度」修正领域/年代偏置[^liwillett09]。定位：不是发现方法，是候选集内排序的现成武器。
- **场归一化**：Radicchi et al. 2008（PNAS）领域内均值重标 cf=c/c₀ 后各学科分布坍缩为通用曲线——「除以领域均值」类指标的理论合法性[^radicchi08]；RCR 的领域用每篇论文自己的共被引网定义（NIH iCite 基于它）[^hutchins16]；FWCI=实际引用/同年同类同学科期望。归一化不产发现，是跨学科榜单的**排序公平性层**。

## 数据质量与博弈

- **自引**：WoS 2016 全库量化——作者自引约占 5% 均值，但尾部极端（1822 人自引比 >0.5）[^kacem20]；按口径与领域 5–15% 区间[^szell20]。**建边时必须打 self-citation flag（作者交集非空），排序/计数可选剔除**。
- **胁迫引用**：~1/5 受访作者报告经历过编辑/审稿人胁迫引用[^wilhite12]——边的生成动机本身有噪声。
- **抽取管线是第一道门**：ParsCit 参考文献串精确匹配仅 ~40%、GROBID 更好仍有损；**unarXive 是决定性对照——从 arXiv LaTeX 源直抽得干净全文+2920 万条结构化 citation context（含位置）**[^unarxive]。LaTeX 源侧抽取在边质量与 context 覆盖上对 PDF 管线是结构性优势——有 LaTeX 源的自建方免费红利，PDF 侧玩家补不平。
- **模型会作弊**：Citeomatic（Bhagavatula et al. 2018）实证——metadata 特征让模型学到「作者爱引自己」捷径，必须显式去自引偏置[^bhag18]。

## 选型四层建议（按依赖递增）

1. **核心图=BC+直接引用双轨**：BC 唯一 day-0 可用且准确性最高、直引前沿侦测最快，都只需参考文献列表、成本倒排 join 级；CC 不进新论文路径，只对存量老文 lazily 增强。
2. **排序层=候选集内局部 PageRank+时间衰减**：CiteRank 式 age-biased teleport（τ≈2.6yr、d≈0.5）压「老而不重要」；副排序暴露原始被引+RCR 式归一化分。
3. **质量层=引用上下文加权**：有全文的边提 mention count、CPA 位置邻近做边权，有余力上 Jurgens 6-frame 意图分类——把「引用数」升级成「影响力引用数」；LaTeX 源抽取是该层天然优势。
4. **护栏=自引与博弈治理**：边上打作者交集 flag、计数排序默认剔/降自引；神经/metadata 模型显式除自引偏置；评测用 citation holdout+abstract→reference-list 重建。

## 结论

一句话：BC 打底保冷启动，直接引用保前沿速度，局部衰减 PageRank 管排序，上下文特征管质量，自引 flag 管博弈——每层都有对照实验背书，成本递增可逐层落地。

### 参考文献

[^kessler63]: Kessler, M.M. Bibliographic coupling between scientific papers. American Documentation 14(1):10-25, 1963. [doi.org/10.1002/asi.5090140103](https://doi.org/10.1002/asi.5090140103)
[^small73]: Small, H. Co-citation in the scientific literature. JASIS 24(4):265-269, 1973. [doi.org/10.1002/asi.4630240406](https://doi.org/10.1002/asi.4630240406)
[^marshakova73]: Marshakova, I.V. System of document connections based on references. 1973. [en.wikipedia.org/wiki/Co-citation](https://en.wikipedia.org/wiki/Co-citation)
[^relrec]: Garfield, E. Related Records / ISI 实践. [clarivate.com](https://clarivate.com/academia-government/scientific-and-academic-research/research-discovery-and-workflow-solutions/webofscience-platform/)
[^boyack10]: Boyack, K.W. & Klavans, R. Co-citation analysis, bibliographic coupling, and direct citation. JASIST 61(12):2389-2404, 2010. [doi.org/10.1002/asi.21419](https://doi.org/10.1002/asi.21419)
[^shibata09]: Shibata, N. et al. Detecting emerging research fronts based on topological measures. JASIST 60(3):571-580, 2009. [doi.org/10.1002/asi.21030](https://doi.org/10.1002/asi.21030)
[^beel16]: Beel, J. et al. Research-paper recommender systems: a literature survey. IJDL 17(4):305-338, 2016. [doi.org/10.1007/s00799-015-0156-0](https://doi.org/10.1007/s00799-015-0156-0)
[^farber20]: Färber, M. & Jatowt, A. Citation recommendation: approaches and datasets. IJDL 2020. [arxiv.org/abs/2002.06961](https://arxiv.org/abs/2002.06961)
[^bethard10]: Bethard, S. & Jurafsky, D. Who should I cite. CIKM 2010. [doi.org/10.1145/1871437.1871517](https://doi.org/10.1145/1871437.1871517)
[^gipp09]: Gipp, B. & Beel, J. Citation Proximity Analysis (CPA). ISSI 2009. [gipp.com](https://www.gipp.com/pub/issi09_gipp_beel.pdf)
[^teufel06]: Teufel, S. et al. Automatic classification of citation function. EMNLP 2006. [aclanthology.org/W06-1613](https://aclanthology.org/W06-1613/)
[^jurgens18]: Jurgens, D. et al. Measuring the evolution of a scientific field through citation frames. TACL 6:391-406, 2018. [aclanthology.org/Q18-1028](https://aclanthology.org/Q18-1028/)
[^valenzuela15]: Valenzuela, M., Ha, V. & Etzioni, O. Identifying meaningful citations. AAAI Workshop 2015. [aaai.org](https://aaai.org/ocs/index.php/WS/AAAIW15/paper/view/10185)
[^pride17]: Pride, D. & Knoth, P. Incidental or influential? ISSI 2017. [oro.open.ac.uk/50405](https://oro.open.ac.uk/50405/)
[^chen07]: Chen, P. et al. Finding scientific gems with Google's PageRank algorithm. Journal of Informetrics 1(1):8-15, 2007.
[^walker07]: Walker, D. et al. Ranking scientific publications using a model of network traffic (CiteRank). JSTAT P06010, 2007.
[^liwillett09]: Li, J. & Willett, P. ArticleRank. Aslib Proceedings 61(6):605-618, 2009.
[^radicchi08]: Radicchi, F. et al. Universality of citation distributions. PNAS 105(45):17268-17272, 2008.
[^hutchins16]: Hutchins, B.I. et al. The NIH Open Citation Collection / Relative Citation Ratio. PLoS Biology 14(7):e1002541, 2016.
[^kacem20]: Kacem, A., Flatt, J.W. & Mayr, P. Tracking self-citations in academic publishing. Scientometrics 123:1157-1165, 2020.
[^szell20]: Szell, M. / Clarivate 团队. How much is too much? Scientometrics 2020. [doi.org/10.1007/s11192-020-03417-5](https://doi.org/10.1007/s11192-020-03417-5)
[^wilhite12]: Wilhite, A.W. & Fong, E.A. Coercive citation in academic publishing. Science 335(6068):542-543, 2012.
[^unarxive]: Saier, T. & Färber, M. unarXive. Scientometrics 125:3085-3108, 2020（2022 更新）. [doi.org/10.1007/s11192-020-03382-z](https://doi.org/10.1007/s11192-020-03382-z)
[^bhag18]: Bhagavatula, C. et al. Content-based citation recommendation (Citeomatic). NAACL 2018. [aclanthology.org/N18-1022](https://aclanthology.org/N18-1022/)
