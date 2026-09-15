# 文献调研：学界如何度量 LaTeX 解析/转换/文本抽取质量

> 目的：为 bench 指标集（成功率/泄漏率/identity/chunk 统计/trap 断言/verdict 分级/锚点保留率）找学理依据与命名惯例。
> 调研日期：2026-09-14。约束：未访问任何 arxiv.org 资源；全部一手来源为 ACL Anthology、Springer、IEEE/OpenAlex 摘要、项目官方文档与源码。

## 0. 一句话结论

学界度量此问题的三条主线恰好覆盖我们指标集的每一块：(a) **severity 分级成功率**（LaTeXML/arXMLiv：Info/Warn/Error/Fatal 消息级 + 文档级四态，官方口径 "error-free 75%"）；(b) **逐阶段漏斗率 + 小样本人工核验带 Wilson/Jeffreys CI**（unarXive 是教科书范例）；(c) **逐条可机检"事实"断言 + 分桶通过率 + ±CI**（olmOCR-bench 的 unit-test 范式，与我们 trap fixtures 完全同构）。我们的 verdict 分级、trap 断言、identity 检查在学界都有成熟先例可直接引用命名。

## 1. 各工作度量口径总表

| 工作                                                                                 | 度量对象                      | 核心指标名                                                                                                                                                                                                              | 报告口径                                                                                                                                                                                                                          | 样本/语料                                           | 分层                                                              | CI/统计                                                              |
| ------------------------------------------------------------------------------------ | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------- |
| **LaTeXML / arXMLiv**（Miller; Ginev; Stamerjohanns/Kohlhase 系）                    | LaTeX→XML/HTML 转换           | 消息 severity：Info/Warn/Error/Fatal；文档状态 = 遭遇的最高 severity；批量报告四态：clean(no problem)/warning/error/fatal                                                                                               | 官方口径："error-free HTML 75%，目标 90%"（arXiv HTML，Ginev 2026 摘要）；逐版本 build report                                                                                                                                     | 全 arXiv（~1.9M+ 篇）                               | 按 LaTeXML 版本、按年份                                           | 无 CI（N 极大，报原始占比）                                          |
| **unarXive 2020**（Saier & Färber, Scientometrics）                                  | LaTeX→plain text→引用标注管线 | 逐阶段保留率（funnel）；reference→MAG 匹配率；人工核验 accuracy                                                                                                                                                         | 漏斗：1,378,096 sources→1,283,584 plain text (93.1%)→1,139,790 含引用标记 (82.7%)→39.7M 参考文献串、63.6M 引用标记；匹配率 42.64%（2018 子集 59.39%）                                                                             | 149 万 arXiv 源文档                                 | 按年份（2018 vs 全集）、按学科                                    | **Wilson + Jeffreys CI @0.95/0.99**（Table 4），300 样本 3 错 → ≥96% |
| **unarXive 2022**（JCDL'23）                                                         | 同上升级版                    | 语料覆盖统计                                                                                                                                                                                                            | 1.9M 篇结构化全文、63M refs（28M 链 OpenAlex）、134M in-text 标记（65M 链）                                                                                                                                                       | ~2.4M arXiv                                         | —                                                                 | 正文不可得（IEEE 闭源），摘要级                                      |
| **S2ORC**（Lo et al., ACL'20）                                                       | PDF(GROBID)/LaTeX→结构化全文  | 字段覆盖率；字段级 accuracy（title exact-match、authors 全序匹配）；bib-linking accuracy                                                                                                                                | 81.1M 篇→8.1M GROBID 全文 (10.0%)+1.5M LaTeX (1.8%)；PDF 预过滤漏斗（PyPDF2 error 0.54M、>50 页 2.27M、横向页 0.28M、PDFAlto error 0.21M）；人工评 500 簇 title 0.93/authors 0.89；600 bib-link GROBID 1.00/0.96、LaTeX 1.00/0.92 | 200M 簇→81.1M 篇                                    | 按来源（arXiv/PMC/publisher）、按解析通道（PDF vs LaTeX）         | 无 CI；抽样人工评（500/600 簇）                                      |
| **GROBID**（Lopez 系，官方 eval 文档）                                               | PDF header/引用/全文抽取      | 字段级 P/R/F1 + instance 级（整条 citation 全对才算）                                                                                                                                                                   | 四种文本匹配档：**strict**（exact match）/**soft**（忽略标点大小写空格）/**relative Levenshtein**/**Ratcliff-Obershelp**；authors 集合级（全员 + 顺序对才算）                                                                     | PMC_sample_1943、bioRxiv-2000、PLOS_1000、eLife_984 | 按字段（title/authors/abstract/keywords/citation 各字段）、按语料 | 无 CI；明示"非绝对质量，是版本间回归追踪"                            |
| **Nougat**（Blecher et al., ICLR'24）                                                | PDF→markup OCR                | **normalized edit distance**（ED/max(len)）、BLEU、METEOR、token 级 P/R/F1                                                                                                                                              | 逐页算分后取均值（`metrics.py`）；软相似度路线代表                                                                                                                                                                                | arXiv 页测试集                                      | —                                                                 | 论文正文未取得（OpenReview 拦），指标名据源码确认                    |
| **olmOCR / olmOCR-bench**（AllenAI, "olmOCR 2: Unit Test Rewards for Document OCR"） | PDF→text 抽取                 | **unit-test 式事实断言**：TextPresence(PRESENT/ABSENT)/TextOrder/Format/Table/Math/Footnote/Baseline 七类                                                                                                               | 分桶通过率表（ArXiv/Old scans math/Tables/Old scans/Headers&footers/Multi column/Long tiny text/Base）+ Overall **±CI**（如 72.0±1.1）                                                                                            | **7,000+ test cases / 1,400 documents**             | 按文档类型分桶                                                    | **报 CI（±1.0 量级）**                                               |
| **BabelDOC**（ACL'26 demo）                                                          | PDF 翻译保版式                | **BIoU**（源/译版面 bbox IoU，同 parser 双侧解析 + 阅读顺序 + 空间近邻匹配后逐页均值）；Likert 1–5 四维：Layout Fidelity/Translation Precision/Visual Aesthetics/Terminology Consistency；**UTB/page**（未译文本块/页） | 200 页 benchmark（80 学术 +60 技术文档 +60 专利）；3 标注员盲评 + Gemini-2.5-Flash judge；消融 60 页按页型分层（formula-heavy/多栏表格/术语密集）                                                                                 | 200 页                                              | 按领域 3 桶、消融按页型                                           | 无 CI                                                                |
| **PDFMathTranslate**（EMNLP'25 demo）                                                | PDF 翻译保版式                | 无保真度量；仅能力矩阵 ✓（Layout/Formula/Bilingual/OCR/Batch）+ 速度 sec/page                                                                                                                                           | 定性对比表                                                                                                                                                                                                                        | —                                                   | —                                                                 | 无                                                                   |
| **LaTeXTrans**（NiuTrans, arXiv 2508.18791 + repo）                                  | LaTeX 翻译（多 agent）        | COMETKIWI（wmt22-cometkiwi-da，篇级 system_score）；LLM-judge 4 维 0–10（Faithfulness/Fluency/Terminology&Formatting/Coherence）；**fc_score = clamp(100−10·errors−2·warnings+20·编译成功，0,100)**（数 .log 行）       | ~50 篇 arXiv × deepseek-v3/gpt-4o                                                                                                                                                                                                 | ~50 篇                                              | 按后端模型                                                        | 无 CI                                                                |
| **MathTranslate**（SUSYUSTC）                                                        | LaTeX 翻译                    | **无定量评测**；定性声明"math perfectly kept"；有 test_latex/ 目录 + issues.md 已知问题清单                                                                                                                             | —                                                                                                                                                                                                                                 | —                                                   | —                                                                 | —                                                                    |
| **texglot**（Mengqi-Lei）                                                            | LaTeX 翻译                    | 无定量评测；管线内自检"protected markers/structure/target language"不合→重试→失败保留原文段+exit 1 标记需复核                                                                                                           | —                                                                                                                                                                                                                                 | —                                                   | —                                                                 | —                                                                    |

## 2. 要点细节

### 2.1 LaTeXML/arXMLiv：severity 分级成功率的正典

- **消息级 severity**（LaTeXML 手册 App.E "Error Codes"）：`Info / Warn / Error / Fatal`。
    - Warn = "result may not be as good as it can be, but most likely properly formed"；
    - Error = "more serious, likely to lead to a malformed result"，处理后继续以收集多错；
    - Fatal = "unlikely that processing can continue"（含 `too_many_errors`：默认 >100 条 Error 自动 Fatal，源码 `MAX_ERRORS=100`）。
- **消息格式** `severity:category:object summary` + 缩进的 source locator；category 开放集合：undefined/expected/unexpected/not_parsed/missing_file/latex/misdefined/malformed/internal/I-O/perl。**设计意图逐字**：消息"slightly structured to allow unattended processing of documents to classify the degree of success"——即为批量跑语料时按文档归类成功度而生（`Common/Error.pm` 中 `$state->noteStatus(...)` 按遭遇的最高 severity 记文档状态）。
- **官方口径**：arXiv HTML 服务（LaTeXML 驱动）目前 **75% error-free，目标 90%**（Ginev, "Scaling Accessible Mathematics on arXiv: HTML Conversion and MathML 4", 2026 摘要）；另有 ~6,000 条用户报告近半已修的运维口径。
- **自测惯例**：`t/` 下 ~30 个 Test::More `.t` 按子系统分（tokenize/expansion/digestion/math/structure/babel/tikz/latexmlpost…），每个跑 `.tex` fixture 与入库的期望 `.xml` **串等比较**——"解析对了"=输出 XML 与 gold 逐字节/规范化相等。

### 2.2 unarXive 2020：管线评估方法论样板（最值得整段借）

- **工具选型矩阵**（Table 3）：plasTeX/TexSoup/opendetex/GrabCite/LaTeXML/Tralics × {output type, **Robust** (Y/N), usable as-is}——Robust 的操作化定义 = "在 arXiv 测试输入上能产生输出的比例"（"half of the tools failed to produce any output for a large amount of arXiv documents"）。顺手一记：GrabCite 自报能解析 arXiv CS 的 78.5%。
- **逐阶段漏斗**：source docs → 解包源文件 → plain text（93.1%）→ 含引用标记（82.7%）→ 参考文献串/引用标记绝对计数。每阶段报"上一步的保留率 + 全体的累计率"。
- **失败归因分解**：reference 匹配率 42.64% 的失败被拆成 31.32% 未抽取到 ID/DOI/标题 + 26.04% 有标题但 MAG 无匹配；识别渠道分解 ParsCit-title 52.60%/DOI 28.31%/arXiv-ID 19.09%。
- **静默退化量化先例**：不做 natbib `\citep` 归一化时，引用标记→bib 匹配率从 30% 掉到 5%（565,613 条样本上实测）——与我们 BUG1（`_args` 吃 `\` 而 identity 盲）同类现象的文献化表达。
- **人工核验样本+CI**（Table 4 是 Wilson/Jeffreys 并列的范例表）：300 条匹配 ref 抽 3 错 → accuracy ≥96%，报 Wilson 与 Jeffreys 区间 @0.95 与 @0.99 两档置信度（例：Wilson .95 ≈ [0.971, 0.997]）。其他人工样本：100 篇核 ParsCit 漏标题（99% 确实无标题）、150 对独家链接（unarXive 4 无效 vs MAG 8 无效）、100 篇 MAG 零引用文档、每学科 300 条 citation context 供标注。
- **占位符同构**：`{{formula:uuid}}`/`{{cite:uuid}}` 正文内占位 + `ref_entries`/`bib_entries` 侧表——与我们 `[[MATH_n]]` 方案同一模式，可引为同行做法。

### 2.3 S2ORC：大规模抽取的"覆盖率 + 抽样字段 accuracy"路线

- **两级漏斗**：簇→论文的全局过滤（无标题 20k、无作者 0.3M、<100 字符、非英语 15.2M）；PDF 侧预过滤（PyPDF2 error 0.54M、>50 页 2.27M、页面宽>高 0.28M、PDFAlto error 0.21M）——"先报丢弃原因分布再报留存"的写法。
- **字段 accuracy 判据**（附录 D）：title = 与 PDF 标题 exact match（容许大小写/特殊字符"γ"vs"gamma"/空白）；authors = 全部作者按序出现（容许表面变体）。抽样 500 簇人工评 → 0.93/0.89；600 条 bib-link → GROBID title 1.00/authors 0.96，LaTeX 通道 1.00/0.92。
- **通道对比口径**：LaTeX 通道的引用/章节/公式检出"near-perfect"（定性断言），PDF 通道靠 GROBID（外部报告 inline-citation F1≈0.89，自抽 200 篇复测"comparable"）。

### 2.4 GROBID：字段级 P/R/F1 与匹配档位词汇

- 字段级（title/authors/abstract/keywords/citation 各字段）与 instance 级（整条 header/citation 全对才算）P/R/F1；`authors` 是**集合级**（全员 + 顺序）。
- 文本字段四档匹配：**strict（exact）/ soft（忽略标点大小写空格）/ relative Levenshtein / Ratcliff-Obershelp**——我们 identity 三档（identical/normalized/diverged）的学理对应就是 strict/soft/diverged。
- 诚实性惯例：明示 gold 噪声压低分数（mixed-citation、区间引用端点、缺 affiliation 链）、"eval 是版本间回归追踪而非绝对质量"——报告里值得照抄的免责句式。

### 2.5 olmOCR-bench：与 trap fixtures 同构的"unit-test 事实"范式

- **设计宣言**（README 逐字可引）：每条 fact "very simple, unambiguous, and machine-checkable, similar to a unit test"；**明确拒绝 edit-distance 类软度量**——会罚"不同但正确"的输出，且把换 x/y 这类致命单字符错当成微小编辑。
- 七类 test：`TextPresenceTest`（PRESENT：某句须出现 / ABSENT：某串须不出现）、`TextOrderTest`（两事实的相对顺序）、`FormatTest`、`TableTest`、`MathTest`（KaTeX 渲染对齐）、`FootnoteTest`、`BaselineTest`（全文启发式）。
- 报告：8 个文档类型桶的通过率 + Overall 带 ±CI（72.0±1.1 量级）；7,000+ 断言 / 1,400 文档；分桶理由 = 难度分层。

### 2.6 翻译管线同行：两极分化

- **定量端**：BabelDOC（BIoU + 4 维 Likert + UTB/page + 200 页分层 + 3 人盲评 + LLM-judge）；LaTeXTrans（COMETKIWI QE + 4 维 LLM-judge + **fc_score 编译健康分**——数 .log 的 Error/Warning 行加权扣分、编译成功 +20，与我们 verdict 的"错误计数独立于 PDF 产出"同思想，但它是软分数非硬门）。
- **定性端**：PDFMathTranslate 只有能力矩阵 ✓+速度；MathTranslate/texglot 零定量。texglot 的"校验不过→重试→保留原文+exit code 标记"与我们 validator+ 降级思路一致。
- **可借新指标**：BabelDOC 的 **UTB（Untranslated Text Blocks）/page**——真实翻译阶段"残留未译块率"的官方命名；BIoU 对纯 TeX 路线不可直接搬，但"同 parser 解析双侧产物再对齐"的方法论可移植到 zh/en 双 PDF 的段落对齐。

### 2.7 解析器自测惯例（对"解析对了"的判定）

| 项目              | 测试形态                                                                                                                                                                                              |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LaTeXML           | `t/*.t` ~30 个 Test::More，按子系统分；`.tex`→XML 输出与入库 gold `.xml` 等值比较；`.tt` 标记 TODO 测试                                                                                               |
| plasTeX           | `unittests/` pytest，按特性一文件一主题（NewCommands/Tokenizer/Verbatim/Encoding/Crossref…）+ `benchmarks/` + FunctionalTests 整文档                                                                  |
| tree-sitter-latex | `test/corpus/*.txt` 标准 tree-sitter corpus（输入 + 期望 S-expr），按构造分文件（commands/counters/environments/groups/includes/issues/math/sections/text/trivia）+ `examples/` 真实文件 + `benches/` |
| 共性              | **curated 最小输入 + 期望输出快照等值**为主；真实语料冒烟（arXMLiv 是唯一的"全量真实语料"先例）；无 fuzzing 传统                                                                                      |

## 3. 统计口径惯例

- **大 N 漏斗率报原始百分比、不报 CI**（arXMLiv/S2ORC/unarXive 漏斗均如此）——N≥1e5 时区间无意义。
- **小样本人工核验必报 CI**：unarXive 用 **Wilson score interval + Jeffreys interval 并列 @0.95/0.99**（300 样本）；olmOCR-bench 对通过率报 ±CI（约 95% 置信，~±1 个百分点量级）。→ 我们的人工评估与语料通过率都应带 **Wilson 95% CI**。
- **分层报告是默认动作**：按文档类型（olmOCR 8 桶）、领域（BabelDOC 3 域）、年份（unarXive 2018 子集）、解析通道（S2ORC PDF vs LaTeX）、字段（GROBID）。→ 我们的分层轴天然存在：docclass/语言/年代/文件规模。
- **失败归因分解**：报"失败原因分布"而不仅是失败率（unarXive 的 31%/26% 拆解、S2ORC 的 PDF 丢弃原因表）。
- **定性判据写成可复现操作定义**：S2ORC 附录把"title 正确"写成 exact-match+ 容许变体表——我们的 trap 期望列（"保护/可译/不崩"）已是此风格，可再补匹配容差说明。

## 4. 推荐我们的指标名 + 报告口径

对照已有指标（`bench/PROTOCOL.md` + `docs/05` E 系列），逐条给学理命名与增补：

| 我们的口径                                | 推荐学名/写法                                                                                                                               | 依据                                                                                                                  |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 解析成功率（binary ok/fail）              | **severity 分级状态分布**：{clean / warning / error / fatal 或 clean/degraded/failed}，文档状态=最高 severity；报漏斗式逐阶段保留率         | LaTeXML 四态 + arXiv 官方 "error-free 75%" 口径 + unarXive 漏斗；"出 PDF≠成功"已被 LaTeXML warn/error 区分和 E10 实证 |
| verdict（clean/pdf~/FAIL）                | 保留三级但映射到 severity 词汇；编译健康若需软分，可引 LaTeXTrans **fc_score** 作对照                                                       | LaTeXTrans fc_score=100−10e−2w+20·compiled                                                                            |
| 泄漏率                                    | **leakage rate = 含受保护记号痕迹的可译块占比**；补失败归因分解（按残留 token 类型分桶，如 unarXive 的 31%/26% 拆法）                       | unarXive natbib 30%→5% 静默退化先例——证明必须独立于端到端指标单测                                                     |
| trap 断言                                 | **unit-test 式 fact 断言 + 分桶通过率 + Wilson/自助 CI**；报告话术借 olmOCR"simple, unambiguous, machine-checkable, similar to a unit test" | olmOCR-bench 7,000 facts/1,400 docs；逐桶报而非只报总分                                                               |
| identity（identical/normalized/diverged） | 三档改名为 **strict / soft / diverged match**（soft=仅空白差异）                                                                            | GROBID strict/soft 匹配档；等值比较是全部解析器测试的通用判据                                                         |
| chunk 统计                                | **coverage 表 + p50/p90 分布**（我们 E20 已做）；补"每篇 chunks/chars 的桶间对比"                                                           | S2ORC Table 4 逐元素均值、E20 percentile 惯例一致                                                                     |
| 占位符守恒                                | **placeholder/marker fidelity**：守恒率、leftover 率、幻觉率分报三个数                                                                      | unarXive `{{cite:uuid}}` 同构；E21 已实测"0 丢失 0 幻觉"两分量——沿用                                                  |
| 锚点保留率                                | **landmark/anchor retention rate**，分层报退化占比（无 hyperref 源=合理 0）                                                                 | S2ORC 覆盖率表的"适用子集"写法                                                                                        |
| （缺）真实翻译残留                        | **UTB/page 或 untranslated-block rate**：译文后仍含源语/占位的块比例                                                                        | BabelDOC UTB/page                                                                                                     |
| （缺）人工核验                            | 小样本（~300）逐条人工判 + **Wilson 95% CI**；抽样分层按 chunk-kind                                                                         | unarXive Table 4 范式                                                                                                 |
| （缺）软相似度兜底                        | 对非 identity 情形报 **normalized edit distance**（ED/max len），避免只用 diff 大小                                                         | Nougat 指标名                                                                                                         |
| （缺）通道/难度分层                       | 报告固定分层轴：docclass 家族 / 语言（含 LaTeX 2.09）/ 单文件 vs 多文件 / 规模桶                                                            | olmOCR 8 桶 + S2ORC 通道分层                                                                                          |

**学界有而我们缺的**：① per-stage funnel 统一成一张表（各阶段保留率×累计率）；② 失败归因分解列（不是失败率而是失败构成 100% 分解）；③ 人工核验样本的 Wilson CI；④ 非 identity 情形的 normalized-ED 软度量；⑤ 真实翻译阶段的 UTB 残留率；⑥ gold 噪声免责条款（GROBID 式："回归追踪而非绝对质量"）。

## 5. 来源

- LaTeXML manual, Appendix E "Error Codes" & `Common/Error.pm` — https://math.nist.gov/~BMiller/LaTeXML/manual/errorcodes/ ; https://github.com/brucemiller/LaTeXML
- Ginev, "Scaling Accessible Mathematics on arXiv: HTML Conversion and MathML 4" (2026), arXiv:2605.16562 — 摘要经 OpenAlex
- Stamerjohanns, Kohlhase, Ginev, David, Miller, "Transforming Large Collections of Scientific Publications to XML", Mathematics in Computer Science 3 (2010) — DOI 10.1007/s11786-010-0024-7（闭源，仅作引用锚点）
- Saier & Färber, "unarXive: a large scholarly data set…", Scientometrics 125 (2020) — DOI 10.1007/s11192-020-03382-z（OA，已读全文）
- Saier et al., "unarXive 2022…", JCDL 2023 — DOI 10.1109/jcdl57899.2023.00020（闭源；摘要+GitHub README 统计）https://github.com/IllDepence/unarXive
- Lo et al., "S2ORC: The Semantic Scholar Open Research Corpus", ACL 2020 — aclanthology.org/2020.acl-main.447（已读全文）
- GROBID end-to-end evaluation docs — https://grobid.readthedocs.io/en/latest/End-to-end-evaluation/
- Blecher et al., "Nougat: Neural Optical Understanding for Academic Documents", ICLR 2024 — OpenReview forum fUtxNAKpdV（正文被拦；指标名据 https://github.com/facebookresearch/nougat `metrics.py`）
- allenai/olmocr + olmOCR-bench README/tests.py — https://github.com/allenai/olmocr（"olmOCR 2: Unit Test Rewards for Document OCR", arXiv:2510.19817）
- BabelDOC, ACL 2026 demo — aclanthology.org/2026.acl-demo.25（已读全文）
- PDFMathTranslate, EMNLP 2025 demo — aclanthology.org/2025.emnlp-demos.71（已读全文）
- LaTeXTrans — https://github.com/NiuTrans/LaTeXTrans（paper: arXiv:2508.18791，摘要经 OpenAlex；评测脚本 `evaluation/scripts/`）
- MathTranslate — https://github.com/SUSYUSTC/MathTranslate
- texglot — https://github.com/Mengqi-Lei/texglot
- 解析器测试目录：brucemiller/LaTeXML `t/`、plastex/plastex `unittests/`、latex-lsp/tree-sitter-latex `test/corpus/`

## 6. 未竟事项（如需补）

- unarXive 2022 正文（IEEE 闭源）的逐阶段表；arXMLiv 各年度 build report 的历史成功率曲线（arxmliv.kwarc.info 当前不可达）；Stamerjohanns 2010 正文数字（74% 一带的历史口径未一手核实）。
- Nougat 论文正文的指标数值（OpenReview/镜像均被拦；已确认指标名）。
