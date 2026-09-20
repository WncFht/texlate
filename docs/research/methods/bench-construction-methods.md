# Benchmark 语料构建方法学 —— 20 个先例的抽样、规模论证与发布形态

> **结论**：学术界的惯例是「能全量就全量、不能全量就随机抽 n≈100–600 人工核验」，几乎没有 benchmark 论文给 n 写统计论证；断言型评估（olmOCR-bench）走「按失败模式分桶×每桶配额」，画像/多样性评估（OmniDocBench、Image2Struct、DocGenome）走「大池→聚类/分层→均衡配额」——两阶段月簇 + 特征配额与 OmniDocBench 同构、n 与 Image2Struct 同量级（都 ~1,200），先例链完整。n 的统计论证（Wilson/rule-of-three/deff）文献里无人做过，是可引用的空白点。
> **状态**：现行方法学依据（2026-09-14 文献口径）。设计侧已落地：corpus_v3 的 core ~1,000 + booster ~200 正是「核心概率样本 + 对抗配额补强」两桶形态，构建脚本见主仓 `bench/py/corpus/build_corpus_v3.py` 等；语料后续扩为 8 层 13,266 篇层化体系（2026-09-19 口径）。
> **日期**：2026-09-14（2026-09-20 迁入重编）

设计对象：从 arXiv 月度 bulk tar（月=簇）两阶段抽样——先选 ~30 个月簇、再簇内按特征分层配额 ~35 篇，总 n≈1,200（1,000 核心 + 200 补强）。本文件只答「语料怎么选、n 怎么论证、怎么发布」三问；底材授权、分层键与指标口径见 corpus 域各件。

## 1. 同类 benchmark 语料构建对比

第一梯队（arXiv 生态与工程类 benchmark）：

| benchmark | n | 抽样方式 | 分层 | 评估集授权 | 启示 |
| --- | --- | --- | --- | --- | --- |
| arXMLiv / ar5iv-dataset[^arxmliv] | 全量 1.58M (2020) / 2.17M (2024) | 不抽样——全 arXiv 人口，按 LaTeXML severity 分包 | severity 四态即「难度分层」 | 2020 版 SIGMathLing NDA；2024 版 C-UDA-1.0 | 全量先例；「按工具失败 severity 分层发布」是难度标签的招牌做法 |
| unarXive 2020[^unarxive20] | 全量 149 万源工程；核验子样本：300 匹配 ref / 100 篇 / 150 引用对 / 每学科 300 引用上下文 | 主体不抽样；质量核验一律 random sample，未论证 n | 引用上下文核验按学科分层（CS/math/phys/other 各 300） | 2022 open subset = permissive-only (CC-BY-SA)；2024 open (CC-BY-4.0) | 教科书范例：全量跑管线 + 小随机样本人工核验 + Wilson/Jeffreys CI；「每分层各 300」是分层人工核验直接先例 |
| S2ORC[^s2orc] | 81.1M 论文；核验 500 簇 title/author、200 篇 inline-citation、600 bib-link（500 GROBID + 100 LaTeX 通道单列） | 随机抽样人工核验，未论证 n | bib-link 按解析通道分层 | ODC-BY | 「每通道抽固定配额核验」（500+100）= 按子总体配额 |
| Nougat[^nougat] | 训练集 8.2M 页；测试集 n 未披露 | 训练页经 SVM+fuzzy 页切分过滤（接受率 ~47%）；测试集抽样方式未写 | 未说明 | 测试集无独立 license 声明 | 反面先例：顶会论文也可以不报测试集 n——不该学 |
| olmOCR-bench[^olmocr] | 1,403 docs / 7,010 test cases | 非概率、按弱点选题：7 类文档 + 每类定制获取 + LLM 辅助造断言 + 人工 review | 7 类对抗桶，桶大小差 15 倍（522→36）；macro-average 按桶 | ODC-BY-1.0 + 使用约束；URL 级去污染 | 与 trap fixtures 同构的断言范式 + 难度驱动分桶先例；桶不均 + macro-avg 直接可抄 |
| BabelDOC bench[^babeldoc] | 200 页 = 80 学术 + 60 技术文档 + 60 专利；消融再抽 80 代表页 | curated 非随机配额；消融按页型再分层 | 领域 3 桶 + 消融按页型 | 未独立声明 | 小而明说的配额分层；n 无论证是常态 |
| Image2Struct[^image2struct] | LaTeX 子集 4 任务 × 300 = 1,200 实例（+wild 52） | arXiv 源码抽样：OAI 元数据→直采；窗口限 2024-01~02 防泄漏；「max 40 instances on a single day」时间摊薄；毒性过滤 + 渲染非空白 + 图像 hash 跨任务去重 | 8 个 arXiv 学科×结构平衡 | Apache-2.0；renewable stream 设计 | 最近先例：同样 ~1,200、同样 arXiv 源码抽、时间维度强制摊薄（40/天上限 = 月簇内配额上限的直接先例）、hash 钉内容 |
| SWE-bench[^swebench] | 2,294 instances / 12 repos | 3 段漏斗：93,139 PR → 11,407 → 2,294（execution 过滤） | 按 repo（隐式，repo=簇） | 公开 | 「来源对象=簇」先例：12 repo ≈ 月簇；n 无统计论证是漏斗产物；Lite 300 子集 = dev 子集砍小版先例 |
| HumanEval[^humaneval] | 164 题 | 手写（规避训练污染） | — | MIT | n 无论证；手写即免责 |

第二梯队（文档解析/OCR 评估集；已修正三个流传的错误 arXiv ID）：

| benchmark | n | 抽样方式 | 分层 | 评估集授权 | 启示 |
| --- | --- | --- | --- | --- | --- |
| OCRBench[^ocrbench] | 1,000 人工核验 QA，5 任务 × 29 子数据集 | 聚合既有数据集而非新抽样；3,000 候选→人工修到 1,000 | 按任务类型 | 数据集 license 未声明 | 「汇聚现有集 + 人工修」是 OCR 评估主流造法 |
| OCRBench v2[^ocrbenchv2] | 10,000 QA 公开 + 1,500 图私有测试集 | 人工收割 81 个数据集 + 私有数据 | 23 任务 / 8 能力 / 31 scenarios | license 未明 | 私有 held-out 集是防污染新惯例 |
| CC-OCR[^ccocr] | 7,058 图 / 39 子集；41% 真实应用来源 | 三源：既有集 + 重标注 + 新采 | 4 轨硬配额：MultiScene 2,750 / Multilingual 150×10 语言 / DocParsing 800 / KIE 2,008 | 数据 license 未明 | 每语言等配额（150×10）是「层内等配额」先例 |
| OmniDocBench[^omnidoc] | 论文版 981 页；repo 已长至 v1.6=1,651 页/10 类 | 两阶段：200k+ 初始 PDF → ResNet-50 特征 + Faiss 聚类 → 抽 6,000 视觉多样页 → 标注属性 → 再均衡到 981 | 9 页型 × 5 版面 × 语言 × 特标 | 代码 Apache-2.0；数据 research-only | 直接先例：harvest big → 聚类多样抽 → 属性均衡；benchmark 可持续生长 |
| GOT-OCR 2.0[^gotocr] | 马赛克小集（400 场景图 + 90 页格式 + 100 乐谱 + 180 几何等） | 自建 + 复用拼装；全部测试数据 strict text similarity filtering vs 训练集 | 按模态/任务 | 未明 | 拼装式评估是常态；训练/测试相似度过滤 = 去污染声明 |
| Fox[^fox] | 112 en + 100 zh 页 + 200 合成页 | 便利采样 | 语言 × 栏数 | 未明 | 双语×版面配额的最小示例 |
| DocBench[^docbench] | 229 PDF / 1,102 问题，5 域 4 题型 | 域配额 + top-k 权威性准则（arXiv NLP 高引池） | 5 域固定配额 + ≤20 QA/篇 | 数据 license 未明 | 域配额+top-k 权威过滤是便利配额增强版 |
| READoc[^readoc] | 3,576 篇 = arXiv 1,009 + GitHub 1,224 + Zenodo 1,343 | 逐源规则过滤；arXiv 侧明示「无 LaTeX 或主文件不明→剔」 | 源 × 学科 × 语言 | 具体 license 未明 | arXiv 源可用性预过滤先例——入池谓词有同行表述可抄 |
| Marker[^marker] | 三代：6 篇便利集 → 2,138 单页/11 类 → 直接采用 olmOCR-bench | Era1 LaTeX 源当 GT；Era2 CC 爬取+LLM judge；Era3 弃自建改用 Ai2 集 | 11 文档类型 / 55 语言 | HF license 字段空 | 工具作者评估演化路径：便利→自建配额→采用标准集；「建成即被收编」的生态现实 |
| im2latex-100k[^im2latex] | 103,556 公式对 | arXiv TeX 源（2003 KDD cup hep-*）→ 正则抽公式 80 万+ → 过滤 → ~10 万 | 无 | 公开 | arXiv LaTeX 源派生评估集的正典祖先；n=过滤剩余 |
| DocGenome[^docgenome] | 全量 500K arXiv；评估集 1,004 篇/9K 页 | 预处理提编译率；评估集「uniformly across disciplines」且只取 Tier-1——明示 eval 与全集同学科分布 | 8 主学科/153 子学科；质量 Tier 分级 | CC BY 4.0 | 分层评估集 + 质量分层先例：先全量分级再按比例抽评估子集，与「先画像再分层配额」同构 |
| UniMERNet[^unimer] | UniMER-1M 训练对；UniMER-Test=23,789 | 公式源 89% arXiv；SCE 桶 1,000 页→6k 公式框→Mathpix+人工→pHash 去重→4,744 | 按场景三桶 | 未明 | 训练/测试同源不同桶；pHash 去重惯例 |
| TeXpert[^texpert] | 440 条 NL→LaTeX（250/150/40 难度三级） | 原子命令采自 Overleaf 模板；人工写 prompt+LLM 精修+核验 | 难度 3 级配额 | MIT | 难度分层配额 |
| DeTikZify[^detikzify] | DaTikZv2 = 360k+ TikZ 程序 | arXiv 源挖掘 TikZ | — | — | 又一条 arXiv 源派生语料 |

## 2. 统计方法菜单（设计论证用）

全部经 Crossref/PubMed/ProjectEuclid/WHO-IRIS 逐条核验（含 DOI）；流传的错误 DOI 已在注里标出。

| 方法 | 出处（核验过） | 适用场景 | 用法 |
| --- | --- | --- | --- |
| Wilson score interval | Wilson 1927[^wilson27]；Brown, Cai & DasGupta 2001[^brown01]（「we recommend the Wilson interval or the equal-tailed Jeffreys prior interval for small n」） | 单比例 CI；n 小或 p 近 0/1 不崩 | 逐桶 verdict 率报 CI；unarXive Table 4 示范引用姿势（Wilson+Jeffreys 双报 @0.95/0.99） |
| Rule of three | Hanley & Lippman-Hand 1983[^hanley83]（流传的 `...053033` 是错 DOI）；Jovanovic & Levy 1997[^jovanovic97]；Eypasch et al. 1995（rule-of-three 命名者）[^eypasch95] | 零事件时 95% 上界 = $1-0.05^{1/n}\approx 3/n$ | 某陷阱在配额桶中 0 出现 → 真实发生率 <3/n_桶；35/桶 ⇒ 上界 8.6% |
| 稀有事件检出 $n\geq\ln(1-\alpha)/\ln(1-p)$ | Nielsen & Landauer 1993[^nielsen93]（Poisson 检出模型，摘要明示用于规划评估规模）；验收抽样传统 ISO 2859-1 / ANSI/ASQ Z1.4 | 「至少见一次 p% 事件」的把握 | 桶内 35 篇 ⇒ 对 p≥8.5% 事件 ≥95% 检出把握；反推配额下限 |
| 设计效应 deff = $1+(m-1)\rho$ | Kish 1965[^kish65]（原文用 roh）；Cochran 1977[^cochran77]（簇抽样 ch.9–10、两阶段 ch.11–12、$n_0=z^2pq/e^2$ ch.4、事后分层 §5A） | 整群 vs SRS 有效样本量 | 论证「30 簇×35」优于「15×70」：deff 随 m 线性涨；$n_{eff}=n/deff$ |
| 「簇多优于簇大」+ 30 簇惯例 | WHO EPI：Henderson & Sundaresan 1982[^henderson82]（30 簇×7=210；83% 调查 95%CI 在 ±10% 内）；Lemeshow & Robinson 1985[^lemeshow85]；WHO 2018 手册[^who18]；CRT 侧 Kahan et al. 2016[^kahan16]（minimum 30–40 clusters，approximate guideline）；Hemming et al. 2011[^hemming11] | 簇数下限 + 簇内量权衡 | ~30 月簇对齐 EPI 惯例 + Kahan 数值指引；注意 EPI 是 30×7，30×35 的簇内量比惯例大 |
| 事后分层加权 | Holt & Smith 1979[^holt79]；Little 1993[^little93]；Cochran 1977 §5A | 配额/不等比分配下池化 | 池化总率 $=\sum_h W_h\hat{p}_h$，$W_h$=人口层占比（语料画像快照离线可算） |
| 分层抽样正典 + 配额批判 | Neyman 1934[^neyman34]（分层 + purposive selection 批判原点）；Neyman allocation $n_h\propto N_h\sigma_h$ | 分层合理性；配额法定位 | 特征配额必须声明「配额内随机抽取」（层内概率样本），否则落 Neyman 批判的 purposive 旧辙；等配额 vs Neyman 分配要写理由（各桶要最小检出能力 → 等配额是 deliberate 设计） |
| Reservoir sampling | Vitter 1985[^vitter85] | 流式等概率单趟抽 | 流式配额抽样的正典引证 |
| 误差边际 $n=z^2p(1-p)/e^2$ | Cochran 1977 ch.4 | 按目标误差定 n | n=1,200 ⇒ ±2.8%（p=0.5 最坏档）；核心 1,000 ⇒ ±3.1% |
| ML eval 功效 | Card et al. 2020[^card20]（underpowered 在 NLP 文献里常见；2000 句测试集 ≈75% power for 1-BLEU）；Dror et al. 2018[^dror18] | NLP 测试集功效分析 | 「test-set size 该做功效论证」的方法学旗；勿误引训练侧文献 |

## 3. 数据集论文写作惯例：授权与钉版

### 3.1「发清单不发内容」先例（manifest/pointer-only distribution）

| 先例 | 做法 | 启示 |
| --- | --- | --- |
| LAION-5B[^laion] | 只发 parquet 元数据（URL+CLIP 分+flag），图片由用户自取——「URLs not images」，承袭 YFCC100M/CC 系谱 | 「发 arXiv ID 清单 + 重建脚本，让用户从 arXiv bulk 自取」有直接先例 |
| Tweet-ID hydration[^tweetid] | ToS 禁发原文 → 只发 tweet ID 用户水合；删除即自动失效 | 同构先例：ID 清单是合规分发形态；教训是上游 API 断供后语料不可重建——arXiv bulk 是 S3 requester-pays 静态 tar，断供风险低得多 |
| unarXive 2022 open subset[^unarxive22] | 逐字先例：permissively licensed 子集（165k，9%）open access，全集走 Zenodo restricted access | 「按 license 切两版发行」在 arXiv 生态有逐字先例；2024 版整集转 CC-BY-4.0 |

### 3.2 钉版（reproducible pinning）惯例

- 版本化 DOI：Zenodo record 逐版 DOI（unarXive 3385851→4313164→7752754→17431595）；S2ORC 按 release 版本发行。→ manifest 钉到 (arXiv ID, version 号) + 语料自身版本 DOI。
- per-item content hash：unarXive JSONL 每行带 `_source_hash` 字段——arXiv 生态「清单+hash」钉版直接先例。
- arXiv 版本即不可变单元：arXiv ID+vN 内容冻结（license 按版本授予且不可撤销）——`(id, version, sha256)` 三元组即可完全钉死输入。
- Datasheets for Datasets[^datasheets]：数据集发布文档模板（动机/构成/采集过程含抽样方式一节/预处理/用途/分发/维护）——语料文档的结构模板，「Collection Process」节正是放两阶段抽样描述的位置。
- Data Provenance Initiative[^dataprov]：审计 ~1,800 文本数据集，大量 license 缺失/标错/收紧 → 支撑「逐篇记 license 字段」的惯例论证。

### 3.3 可再分发子集圈定

CC0+publicdomain+CC-BY(3.0/4.0)+CC-BY-SA ≈ 64.1 万篇可公开发布源码；NC 系 +16.1 万（内部可用，公开发布存疑）——语料授权分布明细见 corpus 域授权调研件。先例组合：unarXive（CC 子集单独 open 发布）+ LAION（pointer-only）→ 发布形态三选一：① CC 子集全文 + 非 CC 仅 ID；② 全量仅 ID manifest + 重建脚本；③ 全量 internal-only。

## 4. 设计点 → 先例映射

| 设计点 | 判定 | 引证支撑 |
| --- | --- | --- |
| n=1,200（1,000 核心 + 200 补强） | 有锚点 | 误差边际：n=1,000 时 p=0.5 的 95% 边际 ±3.1%、n=1,200 ⇒ ±2.8%[^cochran77]。同行量级：olmOCR-bench 1,403 / SWE-bench 2,294 / S2ORC 核验 500–600。+200 补强桶照抄 olmOCR「弱点驱动桶」模式——核心样本走概率、补强样本走对抗配额，两读法分开报告 |
| ~30 月簇 | 有惯例 | 整群抽样「簇数优先于簇内量」：deff=$1+(m-1)\rho$[^kish65] + Kahan 30–40 簇指引[^kahan16]。30 簇对齐 WHO EPI（30×7=210，83% 调查 95%CI≤±10%）[^henderson82]。领域直接先例：Image2Struct「max 40/day to induce temporal diversity」[^image2struct]。arXiv 侧：月是 bulk tar 原生物理分块（`arXiv_src_YYMM_NNN.tar`）⇒ 月簇同时是统计设计与下载成本最优 |
| 簇内 ~35 配额 | 可算 | 稀有事件：35/簇 ⇒ 对 p≥8.5% 的簇内事件 ≥95% 把握至少见 1 次[^nielsen93]；0 出现时报 3/35≈8.6% 上界[^hanley83] |
| 簇内按特征分层配额（docclass 族/多文件/编码/年代 TeX 方言） | 配额制先例 | olmOCR 按文档类型不等比配额 + macro-avg；CC-OCR 每语言等配额 150×10；DocBench 域配额+top-k；OmniDocBench 属性均衡；DocGenome「eval 与全集同分布」；BabelDOC 200=80+60+60；unarXive/S2ORC「每分层各抽固定 n 人工核验」。每类保证最小配额是共同手法 |
| 事后分层加权池化 | 统计正典 | 不等比分配下池化必须加权：$\hat{p}_{st}=\sum_h W_h\hat{p}_h$[^holt79][^cochran77]。$W_h$ 用全量快照特征占比 |
| 逐桶报率 + Wilson CI | 领域先例 | unarXive Table 4 即 Wilson+Jeffreys @0.95/0.99 双报，明示引 Brown et al. 2001——照抄报告格式即可 |
| 评估集授权 | 先例三选一 | ① CC 子集全文 + 其余仅 ID（unarXive 2022 逐字先例）；② 全量仅 manifest+重建脚本（LAION/tweet-ID）；③ 全量 internal。推荐 ②+① 混合 |
| 钉版 | 惯例齐全 | (id,version,sha256) manifest + Zenodo DOI 版（unarXive `_source_hash` 先例）；Datasheets 模板写「Collection Process」节 |

## 5. 风险与先例空白

1. 没有任何 benchmark 论文给 n 做统计功效论证——SWE-bench n 是漏斗剩余、Nougat 连 n 都不报、olmOCR/OmniDocBench n 由「凑得动 + 均衡」决定、im2latex n=过滤剩余。要写 n 论证只能引统计文献 + Card et al. 2020 作「应该论证」的方法学背书——本身是空白点，写得好反而是卖点。
2. 「月=簇」的两阶段抽样无完全同构先例，但三段先例可拼：OmniDocBench 的「大池→聚类→均衡」两阶段（视觉簇，非时间簇）；Image2Struct 的「每时间桶配额上限」（40/天）；arXiv bulk 的 yymm 物理分块。措辞建议：写成「two-stage cluster sampling with months as PSUs (primary sampling units)，配额按特征分层」——术语对齐抽样文献（PSU/SSU），不自创名词。
3. ρ（月间 ICC）无文献值：deff 论证需要 ρ 估计——TeX 特性（docclass 年代、包流行度）存在月间漂移相关但量未知。可用跨年月的语料子集估关键特征的 ρ 上界（如 docclass=revtex 的月间方差分量），哪怕粗糙也足以论证「m 小优于簇大」。
4. 事后分层在 NLP benchmark 里几乎无人做：olmOCR 用 macro-avg（等权桶）、DocGenome 用「eval 与全集同分布」（比例分配规避加权）——两种口径都报（per-stratum 率 + 加权池化率），避免被审「加权益处不明」。
5. 补强桶不可入池化估计——olmOCR 惯例是对抗桶单列 macro-avg 不混入主分布；报告须明示核心（概率样本，可加权泛化）与补强（非概率，只报桶内率）的估计语义差。olmOCR 另有可抄的公平性声明：「bench built after the model, to prevent unfairly iterating on the benchmark」。
6. license 逐篇判定是抽样前必做项：配额若先抽后判 license，non-exclusive 占 ~46–60% 会吃掉近半配额；先例做法（unarXive）是先按 license 切层再抽——分层键含 license 不只是法务需要，也是抽样效率需要。
7. 去污染声明是新基准论文标配：olmOCR URL 级 dedup vs 训练集、OCRBench v2 私有 held-out 集、GOT-OCR 文本相似度过滤、Image2Struct 窗口后置采集。对应物：training-cutoff 后窗 / 与 fixture 的 hash 去重 / 明说语料未进任何模型训练集。
8. 数据集 license 全行业 sloppy（多数未声明），但点名声明者给了模板：olmOCR ODC-BY-1.0、DocGenome CC-BY-4.0、OmniDocBench「research only」、TeXpert MIT——明示 (id,version,hash) manifest + CC 子集正文即优于领域默认水位。

### 参考文献

[^arxmliv]: Stamerjohanns, Kohlhase, Ginev, David, Miller. Transforming Large Collections of Scientific Publications to XML. Mathematics in Computer Science 3, 2010. [doi.org/10.1007/s11786-010-0024-7](https://doi.org/10.1007/s11786-010-0024-7)；ar5iv 2024 版见 [ar5iv.labs.arxiv.org](https://ar5iv.labs.arxiv.org)
[^unarxive20]: Saier, Färber. unarXive: a large scholarly data set with publications' full-text, annotated in-text citations, and links to metadata. Scientometrics 125:3085–3108, 2020. [doi.org/10.1007/s11192-020-03382-z](https://doi.org/10.1007/s11192-020-03382-z)
[^unarxive22]: Saier, Krause, Färber. unarXive 2022: All arXiv Publications Pre-Processed for NLP. JCDL 2023. [arXiv:2303.14957](https://arxiv.org/abs/2303.14957)
[^s2orc]: Lo et al. S2ORC: The Semantic Scholar Open Research Corpus. ACL 2020. [aclanthology.org/2020.acl-main.447](https://aclanthology.org/2020.acl-main.447/)
[^nougat]: Blecher et al. Nougat: Neural Optical Understanding for Academic Documents. ICLR 2024. [arXiv:2308.13418](https://arxiv.org/abs/2308.13418)
[^olmocr]: Poznanski et al. olmOCR: Unlocking Trillions of Tokens in PDFs with Vision Language Models. Ai2 2025. [arXiv:2502.18443](https://arxiv.org/abs/2502.18443)；RLVR 后续 TR [arXiv:2510.19817](https://arxiv.org/abs/2510.19817)
[^babeldoc]: BabelDOC: Yet Another Document Translator. ACL 2026 demo. [aclanthology.org/2026.acl-demo.25](https://aclanthology.org/2026.acl-demo.25/)
[^image2struct]: Roberts et al. Image2Struct: Benchmarking Structure Extraction for Vision-Language Models. NeurIPS 2024 D&B. [arXiv:2410.22456](https://arxiv.org/abs/2410.22456)
[^swebench]: Jimenez et al. SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024. [arXiv:2310.06770](https://arxiv.org/abs/2310.06770)
[^humaneval]: Chen et al. Evaluating Large Language Models Trained on Code. 2021. [arXiv:2107.03374](https://arxiv.org/abs/2107.03374)
[^ocrbench]: Liu et al. OCRBench: On the Hidden Mystery of OCR in Large Multimodal Models. 2023. [arXiv:2305.07895](https://arxiv.org/abs/2305.07895)
[^ocrbenchv2]: Fu et al. OCRBench v2: An Improved Benchmark for Evaluating Large Multimodal Models on Visual Text Localization and Reasoning. 2025. [arXiv:2501.00321](https://arxiv.org/abs/2501.00321)
[^ccocr]: Yang et al. CC-OCR: A Comprehensive and Challenging OCR Benchmark for Evaluating Large Multimodal Models in Literacy. 2024. [arXiv:2412.02210](https://arxiv.org/abs/2412.02210)
[^omnidoc]: Ouyang et al. OmniDocBench: Benchmarking Diverse PDF Document Parsing with Comprehensive Annotations. 2024. [arXiv:2412.07626](https://arxiv.org/abs/2412.07626)
[^gotocr]: Wei et al. General OCR Theory: Towards OCR-2.0 via a Unified End-to-end Model. 2024. [arXiv:2409.01704](https://arxiv.org/abs/2409.01704)
[^fox]: Liu, Wei et al. Focused on Accuracy and Reliability: Fox (无正式题名简写). 2024. [arXiv:2405.14295](https://arxiv.org/abs/2405.14295)
[^docbench]: Zou, Yu et al. DocBench: Benchmarking Document Parsing and Understanding. 2024. [arXiv:2407.10701](https://arxiv.org/abs/2407.10701)
[^readoc]: Li et al. READoc: A Unified Benchmark for Generative Document Understanding. 2024. [arXiv:2409.05137](https://arxiv.org/abs/2409.05137)
[^marker]: datalab-to. Marker benchmark 演化（无论文）. [github.com/datalab-to/marker](https://github.com/datalab-to/marker)
[^im2latex]: Deng et al. Image-to-Markup Generation with Coarse-to-Fine Attention. ICML 2017. [arXiv:1609.04938](https://arxiv.org/abs/1609.04938)
[^docgenome]: Shanghai AI Lab. DocGenome: An Open Large-scale Scientific Document Benchmark for Training and Testing Multi-modal Large Language Models. 2024. [arXiv:2406.11633](https://arxiv.org/abs/2406.11633)
[^unimer]: Wang et al. UniMERNet: A Universal Network for Real-World Mathematical Expression Recognition. 2024. [arXiv:2404.15254](https://arxiv.org/abs/2404.15254)
[^texpert]: TeXpert: A Benchmark for Evaluating LLMs on LaTeX Code Generation. ACL SDP 2025. [aclanthology.org/2025.sdp-1.2](https://aclanthology.org/2025.sdp-1.2/)
[^detikzify]: DeTikZify: Synthesizing Graphics Programs for Scientific Figures and Sketches with TikZ. NeurIPS 2024. [arXiv:2405.15306](https://arxiv.org/abs/2405.15306)
[^wilson27]: Wilson. Probable Inference, the Law of Succession, and Statistical Inference. JASA 22(158):209–212, 1927. [doi.org/10.1080/01621459.1927.10502953](https://doi.org/10.1080/01621459.1927.10502953)
[^brown01]: Brown, Cai, DasGupta. Interval Estimation for a Binomial Proportion. Statistical Science 16(2):101–133, 2001. [doi.org/10.1214/ss/1009213286](https://doi.org/10.1214/ss/1009213286)
[^hanley83]: Hanley, Lippman-Hand. If Nothing Goes Wrong, Is Everything All Right? Interpreting Zero Numerators. JAMA 249(13):1743–5, 1983. [doi.org/10.1001/jama.1983.03330370053031](https://doi.org/10.1001/jama.1983.03330370053031)
[^jovanovic97]: Jovanovic, Levy. A Look at the Rule of Three. American Statistician 51(2):137–9, 1997. [doi.org/10.1080/00031305.1997.10473947](https://doi.org/10.1080/00031305.1997.10473947)
[^eypasch95]: Eypasch et al. Probability of Adverse Events That Have Not Yet Occurred. BMJ 311:619–20, 1995.
[^nielsen93]: Nielsen, Landauer. A Mathematical Model of the Finding of Usability Problems. CHI 1993:206–213. [doi.org/10.1145/169059.169166](https://doi.org/10.1145/169059.169166)
[^kish65]: Kish. Survey Sampling. Wiley, 1965.
[^cochran77]: Cochran. Sampling Techniques, 3rd ed. Wiley, 1977.
[^henderson82]: Henderson, Sundaresan. Cluster Sampling to Assess Immunization Coverage. Bulletin of the WHO 60(2):253–60, 1982.
[^lemeshow85]: Lemeshow, Robinson. Surveys to Measure Programme Coverage and Impact. World Health Statistics Quarterly 38(1):65–75, 1985.
[^who18]: WHO. Vaccination Coverage Cluster Surveys: Reference Manual. WHO IRIS 10665/272820, 2018.
[^kahan16]: Kahan et al. Increased Risk of Type II Errors When Using Cluster-Level Summary Statistics. Trials 17:438, 2016.
[^hemming11]: Hemming et al. Sample Size Calculations for Cluster Randomised Trials. BMC Medical Research Methodology 11:102, 2011.
[^holt79]: Holt, Smith. Post Stratification. JRSS-A 142(1):33–46, 1979. [jstor.org/stable/2344652](https://www.jstor.org/stable/2344652)
[^little93]: Little. Post-Stratification: A Modeler's Perspective. JASA 88(423):1001–12, 1993. [doi.org/10.1080/01621459.1993.10476368](https://doi.org/10.1080/01621459.1993.10476368)
[^neyman34]: Neyman. On the Two Different Aspects of the Representative Method. JRSS 97(4):558–625, 1934.
[^vitter85]: Vitter. Random Sampling with a Reservoir. ACM TOMS 11(1):37–57, 1985. [doi.org/10.1145/3147.3165](https://doi.org/10.1145/3147.3165)
[^card20]: Card, Henderson, Khandelwal, Jia, Mahowald, Jurafsky. With Little Power Comes Great Responsibility. EMNLP 2020. [aclanthology.org/2020.emnlp-main.745](https://aclanthology.org/2020.emnlp-main.745/)
[^dror18]: Dror et al. The Hitchhiker's Guide to Testing Statistical Significance in Natural Language Processing. ACL 2018. [aclanthology.org/P18-1128](https://aclanthology.org/P18-1128/)
[^laion]: Schuhmann et al. LAION-5B: An Open Large-scale Dataset for Training Next Generation Image-Text Models. NeurIPS 2022 D&B. [arXiv:2210.08402](https://arxiv.org/abs/2210.08402)
[^tweetid]: Chen, Lerman, Ferrara. Tracking Social Media Discourse About the COVID-19 Pandemic. JMIR 2020.
[^datasheets]: Gebru et al. Datasheets for Datasets. CACM 64(12):86–92, 2021. [arXiv:1803.09010](https://arxiv.org/abs/1803.09010)
[^dataprov]: Longpre et al. The Data Provenance Initiative: A Large Scale Audit of Dataset Licensing & Attribution in AI. NeurIPS 2023 D&B. [arXiv:2310.16787](https://arxiv.org/abs/2310.16787)
