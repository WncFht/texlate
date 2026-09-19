# 引用推荐算法文献谱系

本报告梳理「基于引用数与引用图谱做论文推荐/发现」的学术方法谱系：从 1963 年文献耦合的奠基定义，到引用上下文 NLP、PageRank 系影响力度量、神经混合推荐系统，再到数据质量与博弈问题。所有关键断言（venue、年份、页码、样本量、头条数字）均已逐条 WebSearch 复核（2026-09-19）；未能独立复核处标注「未验证」。证据备忘底稿在 `tmp/citation-survey/lit-citation-rec/evidence-notes.txt`。

## 1. 奠基：三种引用关联基本型（1956–1990s）

### 1.1 书目耦合（bibliographic coupling, BC）

Kessler 1963 年在 *American Documentation* 定义：两篇论文共享 ≥1 条参考文献即构成耦合，耦合强度 = 共享参考文献数[^kessler63]。BC 的两个决定性性质：**在发表时刻即固定**（参考文献列表出生时就有），以及**对新论文天然可用**——一篇刚上线的论文零被引，但它的参考文献列表完整，BC 图谱对它 day-0 全开。更早的思想渊源可追到 Fano 1956 的「共提及」概念与 Rosengren 1968 的社会学耦合实验[^fano56][^rosengren68]；Weinberg 1974 做了早期系统综述[^weinberg74]。

### 1.2 共被引（co-citation, CC）

Small 1973 年在 *JASIS* 定义：两篇论文被同一篇后续论文同时引用即共被引，强度 = 共同引用它们的论文数[^small73]。同年苏联 VINITI 的 Marshakova 独立提出同一构造，并明确给出了贯穿整个领域的定性框架：**bibliographic coupling 是回顾性的（retrospective），co-citation 是前瞻性的（prospective / forward-looking）**[^marshakova73]。CC 与 BC 互补：BC 静态、表达作者成文时的知识结构；CC 动态、表达学术共同体后来如何理解两篇论文的关系——它会随新文献不断重估，对「经典配对」越收越准，但对新论文是冷启动盲区（没有 incoming citations 就没有 CC 边）。

### 1.3 直接引用与产品化史前史

第三种基本型是直接引用边本身。ISI 早在 1988 年就把 BC 做成了产品功能「Related Records」——以共享参考文献数排序的相关论文列表，Garfield 在散文里明确用 retrospective/forward-looking 对照两种方法[^relrec]。这是「引用图谱 → 相似论文」的第一次工业化。

### 1.4 两种评测口径的对照实验

三项基本型谁更好，取决于评测目标，两篇大样本对照实验给出互补答案：

- **图谱准确性口径**：Boyack & Klavans 2010 在 215 万篇文章上系统比较 CC / BC / 直接引用及混合方案，聚类准确性排序为 **BC > CC > 直接引用**，且 BC+文本混合最好[^boyack10]。
- **新兴前沿侦测口径**：Shibata et al. 2009 问的是「谁先发现新兴研究前沿」，结论是**直接引用最快、BC 次之、CC 最差**——CC 的惯性强，前沿已经形成才反映得出来[^shibata09]。

两个结论不矛盾：BC 胜在「画得准」，直接引用胜在「发现得早」。这直接决定了自建层的选型逻辑（见 §7）。

## 2. 综述与分类学

高引综述给出了领域地形图，五篇足够覆盖：

- **Beel et al. 2016**（IJDL，200+ 篇文献）：推荐方法分布为**内容过滤 55% / 协同过滤 18% / 图方法 16%**，其余为混合；**81% 的系统完全不做用户建模**，评测几乎全是离线代理任务[^beel16]。这篇是「领域全貌」锚点。
- **Bai et al. 2019**（IEEE Access）：四类方法分类学，公开问题点名 cold-start、数据稀疏、serendipity[^bai19]。
- **Färber & Jatowt 2020**（IJDL）：把引用推荐切成 **local/context-aware（给定稿件中占位符上下文推荐该处该引什么）vs global（给定种子论文推荐相关集）** 两个任务族，并系统梳理可用数据集（CiteSeerX、ACL Anthology、unarXive 等）[^farber20]。做产品选型时这个二分比方法分类更有用——绝大多数发现类产品做的是 global，scite/写作助手类做的是 local。
- **arXiv:2508.08828**（覆盖 2021–2024，沿用 Kreutz 2022 方法学）：深度学习/LLM 时代的承接综述[^arxiv2508]。
- **MDPI Information 2025**（PRISMA，252 篇）：主张推荐系统利用**细粒度引用知识**（引用位置、上下文、所在节、引用意图），并呼吁评测超越 accuracy 纳入 novelty/diversity/serendipity[^mdpi25]。

**评测代理任务的事实标准**：把论文摘要（或正文）当输入、被遮盖的参考文献列表当 ground truth 的「abstract→reference-list 重建」，辅以 citation holdout；指标为 Precision/Recall/F1@k、NDCG、MAP、MRR（由 Bethard & Jurafsky 等确立，见 §5）[^bethard10]。这个任务不需要用户行为数据即可离线评测，是自建层 benchmark 的可行起点。

## 3. 引用上下文方法：从「引了」到「怎么引的」

只看「A 引 B」这条边是稀疏而粗糙的信号；引用上下文（citation context）把每条边展开成特征向量，是引用图谱从「计数」走向「语义」的分支。

### 3.1 位置与邻近度

Gipp & Beel 2009 提出 **Citation Proximity Analysis（CPA）**：两篇被引文献在引用方的正文中出现位置越近，关联越强——把扁平共被引升级成位置加权共被引[^gipp09]。论文内 mention 次数、是否同句/同段出现，都是免费的高质量信号——但前提是能拿到引用方的全文。

### 3.2 引用功能/意图分类

- **Teufel 2006**（EMNLP）：首个系统的 citation function 监督分类，12 类功能方案（Weak/CoCo/Neut/PModi/…），自建 CFC 语料 161 篇[^teufel06]。
- **Athar & Teufel 2012**（NAACL）：context-enhanced 引用情感检测——关键发现是**只看引用句不足以判情感，要扩上下文窗口**，对负面引用尤其如此；ACL 语料 8,736 条引用[^athar12]。
- **Jurgens et al. 2018**（TACL）：6 类 citation frame（background/motivation/uses/extends/compares/future），~2k 人工标注 + 远程监督扩展到 **134k 条引用**，且 citation frame 能预测论文未来引用量；数据在 GitHub 开源[^jurgens18]。这条线证明意图分类可以规模化。

产品端 scite.ai 的 smart citations（supporting/mentioning/contrasting 三分类）就是这条谱系的工业化形态——具体产品细节归 scite lane，此处只需确认其学术根源。

### 3.3 影响力引用：大多数引用是「凑数」的

Valenzuela, Ha & Etzioni 2015（AAAI workshop，Semantic Scholar 团队）提出监督分类器识别「meaningful/influential citations」，P65@R90，后来直接成为 S2 API 里 `isInfluential` 字段与影响力计数的产品基础[^valenzuela15]。Pride & Knoth 2017（ISSI）做了更严格的量化：**只有 10.3–17.9% 的引用是真正 influential**，其余是仪式性/装饰性引用；判别 top 特征是**正文内 mention 次数**与**被引摘要相似度**；同时警告 PDF 抽取管线的方差会直接污染这些特征[^pride17]。

对推荐系统的含义重大：**原始引用数把 ~85% 的装饰性引用与 15% 的实质引用等权对待**——任何用引用数排序的系统都在放大噪声。能用 mention count/上下文特征给边加权的系统（哪怕只是启发式）就有结构性质量优势。

## 4. 影响力与归一化度量

引用数是最浅的度量；PageRank 系与场归一化指标提供了排序层的第二、第三档。

### 4.1 PageRank 家族在引用图上的适配

- **Chen et al. 2007**（J. Informetrics）：PageRank 跑在 35.3 万篇 Physical Review 论文的引用图上，能把**低被引但高 PageRank 的「gems」**（如 Wigner–Seitz 元胞法原文）捞到顶部——引用数排不到前列、但持续被高影响力论文引用的奠基工作[^chen07]。
- **Walker et al. 2007**（CiteRank，JSTAT）：引用网络与 Web 的本质差异在于**论文有年龄**——随机游走者模型假设读者按近期文献的引用向后跳，故 teleport 偏好新论文（时间常数 τ≈2.6 年），damping 取 **d≈0.5** 而非 Web 的 0.85/1/6[^walker07]。「引用网络需要更低 damping」在 Eigenfactor 文献里也被独立确认——无环/近无环图上高 damping 会让概率质量堆积在祖先节点。
- **Li & Willett 2009**（ArticleRank，Aslib Proceedings）：修正 PageRank 对「平均参考文献数高的领域/年代」的偏置，分母改为**自身出度 + 全网平均出度**[^liwillett09]。
- **Eigenfactor**（Bergstrom 2007 / West et al. 2008）：期刊级随机游走，转移矩阵 P = αH′ + (1−α)a·eᵀ，teleport 向量按文章类型加权；免费发布于 eigenfactor.org[^eigenfactor]。
- **SARA**（Radicchi et al. 2009）：把 PageRank 的功劳从论文扩散到作者——论文→作者按贡献均分信用，在 PR 1893–2006 档案上排物理学家优于原始引用数[^radicchi09]。

对推荐的意义：PageRank 系不是发现方法本身，但它是**候选集内排序**的现成武器——在 BC/共被引捞出的候选集上跑带 CiteRank 式时间衰减的局部 PageRank，能同时压住「老而不重要」与「新而无据」两端。

### 4.2 场归一化：跨领域可比性

- **Radicchi et al. 2008**（PNAS）：各学科引用分布形状不同，但用领域内均值重标 cf = c/c₀ 后分布坍缩为通用曲线——为一切「除以领域均值」的指标提供了理论合法性[^radicchi08]。
- **RCR**（Hutchins et al. 2016，PLoS Biology）：Relative Citation Ratio 的领域定义最有趣——**每篇论文的领域用它自己的共被引网络定义**，而非期刊分类表；NIH 的 iCite 工具即基于它，数据底座是 Open Citation Collection（2019 年 PLoS Biol 单独发文）[^hutchins16][^occ19]。亦有批评指出其领域定义不透明、对引文结构不稳定[^rcrcrit]。
- **FWCI**（SciVal/Elsevier）：field-weighted citation impact = 实际引用 / 同年同文献类型同学科的期望引用，常用 3 年窗[^fwci]。

归一化指标不产发现，但它是**排序公平性**层：跨领域推荐列表必须归一化，否则数学/生物医学生的引用体量差会把榜单变成单一学科榜。

## 5. 混合与神经推荐系统谱系

- **McNee et al. 2002**（CSCW）：引用推荐+协同过滤的鼻祖——把论文当 user、参考文献当 rating，在 18.6 万篇 ResearchIndex（CiteSeer 前身）上验证 citation-CF 与文本互补；后续落地为 TechLens（2004）[^mcnee02][^techlens]。
- **He et al. 2010**（WWW）：context-aware 引用推荐的开山——输入是稿件里带占位符的上下文，输出是该处该引的论文；CiteSeerX 数据[^he10]。
- **Bethard & Jurafsky 2010**（CIKM，"Who should I cite"）：learning-to-retrieve 特征模型，abstract→reference-list 重建 MAP 28.7，比 TF-IDF 基线 +12.8[^bethard10]。
- **Ebesu & Fang 2017**（SIGIR，NCN）：encoder-decoder 神经引用网络，学作者特定+上下文表示；Refseer 评测 450 万引用对[^ebesu17]。
- **Bhagavatula et al. 2018**（NAACL，Citeomatic）：内容 embedding 候选生成 + 重排两段式管线，F1@20 +18%、MRR +22%；**关键反面教材——metadata 特征（作者/期刊）让模型学到自引捷径**，必须显式去偏；底座 OpenCorpus 700 万篇[^bhag18]。

谱系之外的边界注记：SPECTER/SciNCL 这一支「用引用关系构造文档 embedding 训练目标」的表示学习线属于 embedding lane 的领地；从本报告视角只需记住——**引用图既可做离散相似度，也可当 embedding 的监督信号**，两者在 Citeomatic 式两段式管线里汇合。

## 6. 数据质量与博弈

### 6.1 自引：规模与分布形态

WoS 2016 全库量化（Kacem et al. 2020，*Scientometrics*）：38.56 万作者、324 万篇论文、9080 万条引用中，**作者自引约占 5%**；75% 的自引作者比例 <0.1，但有 1822 人比值 >0.5[^kacem20]。文献汇总（Szell/Clarivate 高被引学者数据）：自引占比按口径与领域在 **5–15%** 区间——物理 ~15%、社科 ~6%、人文 ~3%；共作者口径（13–15%）高于严格第一作者口径（5–11%）；HCR 群体 modal 自引份额 5–7%，领域中位数 7.4–11.3%[^szell20]。高影响期刊队列研究（PLOS One 2011）：作者自引 6.5%、期刊自引 1.1%[^plos11]。

结论：自引是长尾现象——均值不高但尾部极端，**建边时必须在边上打 self-citation flag（作者交集非空），排序/计数时可选剔除**，否则 h 指数式刷分路径会污染推荐。

### 6.2 胁迫引用与治理

Wilhite & Fong 2012（*Science*，封面文章）：约 **1/5** 受访作者报告经历过编辑/审稿人胁迫性引用要求，目标是资历浅、合著者少的论文[^wilhite12]。Clarivate 的治理工具是 JCR 对异常自引/引用堆叠（citation stacking）期刊的压制（suppression）[^wilhite12]。对推荐系统：引用边的「生成动机」本身有噪声源，编辑胁迫产生的边在语义上近似装饰性引用——这又回到 §3.3 的 influential-citation 加权逻辑。

### 6.3 抽取管线是数据质量的第一道门

Pride & Knoth 明确指出 PDF 抽取方差污染上下文特征[^pride17]；历史上 ParsCit 对参考文献串的精确匹配率仅 ~40%，GROBID 更好但仍是有损管线。**unarXive**（Saier & Färber 2020，*Scientometrics*；unarXive 2022/JCDL 2023 更新）是决定性的对照证据：**从 arXiv LaTeX 源直接抽取，拿到的是干净全文 + 2920 万条结构化 citation context（含位置信息），并与 MAG 对齐**[^unarxive]。LaTeX 源侧抽取在引用边质量、citation context 覆盖率上对 PDF 管线是结构性优势——这一点对拥有 LaTeX 源的自建方是免费红利，也是 PDF 侧玩家（Connected Papers、scite 等）无法用纯解析补平的差距。

### 6.4 模型会学会作弊

Citeomatic 的实证教训单列强调：推荐模型一旦拿到作者/期刊 metadata，就会学到「作者爱引自己」的捷径[^bhag18]。自建管线要么在边上先除自引、要么把自引做成显式特征，不能放任 metadata 泄漏。

## 7. 方法→输入→冷启动→成本对照表

| 方法 | 必需输入 | 新论文冷启动 | 动态性 | 计算成本 | 关键证据/备注 |
| --- | --- | --- | --- | --- | --- |
| 书目耦合 BC | 各论文参考文献列表 | **优**——发表即有全量 BC 边 | 静态，增量追加 | 低（ref-list join/倒排） | 聚类准确性冠军[^boyack10]；ISI 1988 已产品化[^relrec] |
| 共被引 CC | incoming citation 边 | **差**——无被引即无边 | 动态，持续重估 | 中（随引用累积增重） | 前沿侦测最慢[^shibata09]；经典配对越陈越准 |
| 直接引用 | 引用边 | **差**（incoming 为零） | 最快反映新前沿 | 低 | 新兴前沿侦测冠军[^shibata09] |
| 引用上下文（CPA/mention count） | 引用方全文 | 部分（可给 outgoing 加权） | 随新引用方累积 | 中–高（全文 NLP 一遍） | mention count 是 influential 判别 top 特征[^pride17] |
| 引用意图/功能分类 | 引用上下文 + 标注/远程监督 | 同上 | 同上 | 高（分类器推理） | 6-frame 可扩到 134k 条[^jurgens18]；scite 产品化 |
| influential citation 加权 | 上下文特征 + 摘要 | 部分 | 同上 | 中 | 85% 引用是装饰性的[^pride17][^valenzuela15] |
| PageRank 系（含 CiteRank/ArticleRank） | 全引用图 + 论文年龄 | 新论文无 incoming → 分低 | 全局需重算；局部子图便宜 | 全局高/局部低 | gems 打捞[^chen07]；d≈0.5 + 年龄 teleport[^walker07][^liwillett09] |
| 场归一化（RCR/FWCI 型） | 引用数 + 领域定义 | 需累积窗 | 年度级更新 | 低（聚合统计） | 排序公平性层，非发现方法[^hutchins16][^fwci] |
| CF-over-citations | 用户-论文或论文-参考文献矩阵 | 受稀疏性限制 | 增量 | 中 | 鼻祖[^mcnee02]；无用户行为时退化为 BC 变体 |
| 神经混合（NCN/Citeomatic 型） | 文本 + 上下文 + metadata | **优**（内容兜底） | 需重训/增量索引 | 高（GPU） | 离线指标 SOTA[^ebesu17][^bhag18]；自引偏置陷阱 |
| 文本 embedding（SPECTER 系） | 标题/摘要（+引用信号训练） | **优** | 推理便宜、训练贵 | 中 | 边界：归 embedding lane |

## 方法选型建议

基于谱系证据，给一个「完全形态」自建引用发现层的可辩护选型（与具体产品无关，按依赖递增分四层）：

1. **核心图 = BC + 直接引用双轨**。BC 是唯一对新论文 day-0 可用且准确性最高的图相似度[^boyack10][^kessler63]；直接引用边是最快的前沿侦测信号[^shibata09]。两者都只需参考文献列表，成本是倒排 join 级别。CC 不建为核心——它对存量老论文可当按需增强（对已有 citers 的子图 lazily 算），但永远不该进新论文路径。
2. **排序层 = 候选集内局部 PageRank + 时间衰减**。在 BC/direct 捞出的候选集上跑 CiteRank 式 age-biased teleport（τ≈2.6yr、d≈0.5）[^walker07]，修正老论文天然占优；同时暴露原始引用数 + 一个 RCR 式「除以同领域同期望值」的归一化分[^hutchins16][^radicchi08]做副排序——跨学科榜单必须归一化。
3. **质量分层 = 引用上下文加权**。凡能拿到引用方全文的边，提取 mention count、位置邻近度（CPA[^gipp09]）做边权；有余力再上 Jurgens 式 6-frame 意图分类[^jurgens18]——这一层把「引用数」升级成「影响力引用数」，是按 Pride & Knoth 的 10–18% 结论[^pride17]对装饰性引用去噪的唯一手段，也是和纯元数据玩家拉开差距的档位。**LaTeX 源抽取是该层的天然优势**（unarXive 实证[^unarxive]）：PDF 侧玩家补不平。
4. **护栏 = 自引与博弈治理**。建边时给每条边打作者交集 flag，计数/排序默认剔除或降权自引（全库均值 ~5%，但尾部 >50%[^kacem20][^szell20]）；神经/metadata 模型显式除自引偏置[^bhag18]。评测 harness 用 citation holdout + abstract→reference-list 重建代理任务，指标 P/R/F1@k + MRR[^bethard10]。

一句话：BC 打底保冷启动，直接引用保前沿速度，局部衰减 PageRank 管排序，上下文特征管质量，自引 flag 管博弈——每一层都有文献对照实验背书，且成本递增、可逐层落地。

## 探针产物

- 证据备忘：`tmp/citation-survey/lit-citation-rec/evidence-notes.txt`（全部 30+ 条断言的 venue/页码/样本量/头条数字，逐条 WebSearch 复核于 2026-09-19）。
- 本报告未做 API 实测（纯文献 lane）；文献条目的事实核验方式 = WebSearch 命中出版社/期刊页与摘要原文，凡未命中一手来源者均已在正文标注或弃用。
- 边界划分：SPECTER/SciNCL 表示学习归 embedding lane；scite.ai 产品细节归 scite lane；OpenAlex/S2 API 字段与限额归数据源 lane。

### 参考文献

[^kessler63]: Kessler, M.M. Bibliographic coupling between scientific papers. American Documentation 14(1):10-25, 1963. [doi.org/10.1002/asi.5090140103](https://doi.org/10.1002/asi.5090140103)
[^small73]: Small, H. Co-citation in the scientific literature: a new measure of the relationship between two documents. JASIS 24(4):265-269, 1973. [doi.org/10.1002/asi.4630240406](https://doi.org/10.1002/asi.4630240406)
[^marshakova73]: Marshakova, I.V. System of document connections based on references. Nauchno-Tekhnicheskaya Informatsiya Ser.2 (6):3-8, 1973. [英文综述见 en.wikipedia.org/wiki/Co-citation](https://en.wikipedia.org/wiki/Co-citation)
[^fano56]: Fano, R.M. The technical literature: sources and channels. 1956 会议文献；与 Rosengren 1968 共为 coupling 前身，见 [en.wikipedia.org/wiki/Bibliographic_coupling](https://en.wikipedia.org/wiki/Bibliographic_coupling)
[^rosengren68]: Rosengren, K.E. Sociological aspects of the literary system. 1968. [同上](https://en.wikipedia.org/wiki/Bibliographic_coupling)
[^weinberg74]: Weinberg, B.H. Bibliographic coupling: a review. Information Storage and Retrieval 10(5-6):189-196, 1974. [doi.org/10.1016/0020-0271(74)90058-8](https://doi.org/10.1016/0020-0271(74)90058-8)
[^relrec]: Garfield, E. Related Records / bibliographic coupling 产品化散文与 ISI 实践. [clarivate.com 相关 essay 与 webofscience 文档](https://clarivate.com/academia-government/scientific-and-academic-research/research-discovery-and-workflow-solutions/webofscience-platform/)
[^boyack10]: Boyack, K.W. & Klavans, R. Co-citation analysis, bibliographic coupling, and direct citation: which citation approach represents the research front most accurately? JASIST 61(12):2389-2404, 2010. [doi.org/10.1002/asi.21419](https://doi.org/10.1002/asi.21419)
[^shibata09]: Shibata, N. et al. Detecting emerging research fronts based on topological measures in citation networks of scientific publications. JASIST 60(3):571-580, 2009. [doi.org/10.1002/asi.21030](https://doi.org/10.1002/asi.21030)
[^beel16]: Beel, J. et al. Research-paper recommender systems: a literature survey. International Journal on Digital Libraries 17(4):305-338, 2016. [doi.org/10.1007/s00799-015-0156-0](https://doi.org/10.1007/s00799-015-0156-0)
[^bai19]: Bai, X. et al. Scientific paper recommendation: a survey. IEEE Access 7:9324-9339, 2019. [doi.org/10.1109/ACCESS.2018.2890388](https://doi.org/10.1109/ACCESS.2018.2890388)
[^farber20]: Färber, M. & Jatowt, A. Citation recommendation: approaches and datasets. IJDL 2020 / arXiv:2002.06961. [arxiv.org/abs/2002.06961](https://arxiv.org/abs/2002.06961)
[^arxiv2508]: Recent Advances and Trends in Research Paper Recommender Systems. arXiv:2508.08828, 2025. [arxiv.org/abs/2508.08828](https://arxiv.org/abs/2508.08828)
[^mdpi25]: A Review on Scholarly Publication Recommender Systems. Information 12(4):108, 2025. [mdpi.com/2078-2489/12/4/108](https://www.mdpi.com/2078-2489/12/4/108)
[^gipp09]: Gipp, B. & Beel, J. Citation Proximity Analysis (CPA) — a new approach for identifying related work based on co-citation analysis. ISSI 2009. [gipp.com 论文页](https://www.gipp.com/pub/issi09_gipp_beel.pdf)
[^teufel06]: Teufel, S., Siddharthan, A. & Tidhar, D. Automatic classification of citation function. EMNLP 2006. [aclanthology.org/W06-1613](https://aclanthology.org/W06-1613/)
[^athar12]: Athar, A. & Teufel, S. Context-enhanced citation sentiment detection. NAACL 2012. [aclanthology.org/N12-1041](https://aclanthology.org/N12-1041/)
[^jurgens18]: Jurgens, D. et al. Measuring the evolution of a scientific field through citation frames. TACL 6:391-406, 2018. [aclanthology.org/Q18-1028](https://aclanthology.org/Q18-1028/)
[^valenzuela15]: Valenzuela, M., Ha, V. & Etzioni, O. Identifying meaningful citations. AAAI Workshop 2015. [aaai.org/ocs/index.php/WS/AAAIW15/paper/view/10185](https://aaai.org/ocs/index.php/WS/AAAIW15/paper/view/10185)
[^pride17]: Pride, D. & Knoth, P. Incidental or influential? — challenges in automatic detection of citation importance. ISSI 2017. [oro.open.ac.uk/50405](https://oro.open.ac.uk/50405/)
[^chen07]: Chen, P., Xie, H., Maslov, S. & Redner, S. Finding scientific gems with Google's PageRank algorithm. Journal of Informetrics 1(1):8-15, 2007. [doi.org/10.1016/j.joi.2006.06.001](https://doi.org/10.1016/j.joi.2006.06.001)
[^walker07]: Walker, D. et al. Ranking scientific publications using a model of network traffic (CiteRank). JSTAT P06010, 2007. [iopscience.iop.org/article/10.1088/1742-5468/2007/06/P06010](https://iopscience.iop.org/article/10.1088/1742-5468/2007/06/P06010)
[^liwillett09]: Li, J. & Willett, P. ArticleRank: a PageRank-based alternative to numbers of citations for analysing citation networks. Aslib Proceedings 61(6):605-618, 2009. [doi.org/10.1108/00012530911005544](https://doi.org/10.1108/00012530911005544)
[^eigenfactor]: West, J.D., Bergstrom, T.C. & Bergstrom, C.T. The Eigenfactor metrics: a network approach to assessing scholarly journals. / Bergstrom 2007. [eigenfactor.org](http://www.eigenfactor.org/)
[^radicchi09]: Radicchi, F. et al. Diffusion of scientific credits and the ranking of scientists. PRE 80, 056103, 2009. [doi.org/10.1103/PhysRevE.80.056103](https://doi.org/10.1103/PhysRevE.80.056103)
[^radicchi08]: Radicchi, F., Fortunato, S. & Castellano, C. Universality of citation distributions: toward an objective measure of scientific impact. PNAS 105(45):17268-17272, 2008. [doi.org/10.1073/pnas.0806977105](https://doi.org/10.1073/pnas.0806977105)
[^hutchins16]: Hutchins, B.I. et al. The NIH Open Citation Collection: a public access, broad coverage resource. / Relative Citation Ratio. PLoS Biology 14(7):e1002541, 2016. [doi.org/10.1371/journal.pbio.1002541](https://doi.org/10.1371/journal.pbio.1002541)
[^occ19]: Hutchins, B.I. et al. The NIH Open Citation Collection. PLoS Biology 17(1):e3000385, 2019. [doi.org/10.1371/journal.pbio.3000385](https://doi.org/10.1371/journal.pbio.3000385)
[^rcrcrit]: Waltman, L. et al. / Ioannidis, J.P.A. et al. 对 RCR 的方法学批评. PLoS Biology pbio.2002536, 2017. [doi.org/10.1371/journal.pbio.2002536](https://doi.org/10.1371/journal.pbio.2002536)
[^fwci]: Elsevier. Field-Weighted Citation Impact (FWCI) 定义. SciVal 文档. [elsevier.com/products/scival/metrics](https://www.elsevier.com/products/scival/metrics)
[^mcnee02]: McNee, S.M. et al. On the recommending of citations for research papers. CSCW 2002. [doi.org/10.1145/587078.587096](https://doi.org/10.1145/587078.587096)
[^techlens]: McNee, S.M. et al. TechLens 研究与落地. Grouplens, U. Minnesota, 2004. [grouplens.org](https://grouplens.org/)
[^he10]: He, Q. et al. Context-aware citation recommendation. WWW 2010. [doi.org/10.1145/1772690.1772734](https://doi.org/10.1145/1772690.1772734)
[^bethard10]: Bethard, S. & Jurafsky, D. Who should I cite: learning literature search models from citation behavior. CIKM 2010. [doi.org/10.1145/1871437.1871517](https://doi.org/10.1145/1871437.1871517)
[^ebesu17]: Ebesu, T. & Fang, Y. Neural citation network for context-aware citation recommendation (NCN). SIGIR 2017. [doi.org/10.1145/3077136.3080730](https://doi.org/10.1145/3077136.3080730)
[^bhag18]: Bhagavatula, C. et al. Content-based citation recommendation (Citeomatic). NAACL 2018. [aclanthology.org/N18-1022](https://aclanthology.org/N18-1022/)
[^wilhite12]: Wilhite, A.W. & Fong, E.A. Coercive citation in academic publishing. Science 335(6068):542-543, 2012. [doi.org/10.1126/science.1212540](https://doi.org/10.1126/science.1212540)
[^kacem20]: Kacem, A., Flatt, J.W. & Mayr, P. Tracking self-citations in academic publishing. Scientometrics 123:1157-1165, 2020. [doi.org/10.1007/s11192-020-03413-9](https://doi.org/10.1007/s11192-020-03413-9)
[^szell20]: Szell, M. / Clarivate 团队. How much is too much? The difference between research influence and self-citation excess. Scientometrics 2020. [doi.org/10.1007/s11192-020-03417-5](https://doi.org/10.1007/s11192-020-03417-5)
[^plos11]: Ioannidis, J.P.A. et al. 高影响医学期刊自引队列研究. PLoS ONE 6(7):e20885, 2011. [doi.org/10.1371/journal.pone.0020885](https://doi.org/10.1371/journal.pone.0020885)
[^unarxive]: Saier, T. & Färber, M. unarXive: a large scholarly data set with publications' full-text, annotated in-text citations, and links to metadata. Scientometrics 125:3085-3108, 2020（2022/JCDL 2023 更新）. [doi.org/10.1007/s11192-020-03382-z](https://doi.org/10.1007/s11192-020-03382-z)
