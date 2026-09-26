# 翻译质量评估方法 —— MQM/ESA/GEMBA 文献与 qualbench 改造方案

> **结论**：无参考译文场景主线只能走 reference-free judge/QE 路线。推荐协议 = gemba_esa 式两步单发——judge 一次调用同时产出 `{errors:[{span, category, severity, note}], score: 0-100}`，主分取声明分（ESA 实证直评优于衍生），衍生分只做自洽校验；judge≠translator 按 chunk 级 meta.model 强制；统计口径用 paper 簇 block bootstrap CI + tie-calibrated pairwise accuracy。
> **状态**：现行方法已落地。qualbench.py 即 ESA 两步单发实现（`protocol_v=esa2`、record 带 stated100/derived100/score_delta、resume key 并入 protocol_v），配套 `bench/py/report/qual{sample,stats,freeze,anchor,drift}.py` 五件套（抽样/统计/冻结回归/人锚/漂移监控）；主仓 `bench/py/qualbench.py` 为准。
> **日期**：2026-09-18（2026-09-20 迁入重编）

约束前提：无参考译文（arXiv 论文无人翻好的对照），reference-based 指标（BLEU/chrF/COMET/COMETKiwi-ref）天然不适用主线；judge 池限免费档模型；同一篇内 chunk 相互不独立，统计须按文档聚类。

## 1. 动机证据

qualbench 旧协议是 1–5 直评 + 六类 flag 的 LLM-judge（untranslated_spans / placeholder_broken / term_inconsistency / over_translation / hallucinated_content / grammar），judge 输出 `{"score": 1-5, "flags": [...], "note": ...}` 严格 JSON。存量两个批次（n=360、n=293，均 swe-2-medium 自评 swe-2-medium 译文）分数高度堆顶：5 分占比均 ≈87%，4 分 ~10%，≤3 分零星——直评 1–5 在自评组合下几乎无区分度。这既是「直评太粗」也是「judge 与被评同型」两个问题的合并症状，文献对两者各有现成证据。

## 2. 人类标注协议：MQM 与 ESA

MQM 的人类标注规格由 Freitag et al. 2021 的 WMT 大尺度实验定稿：类目为 Accuracy/Fluency/Terminology/Style/Locale 外加 Non-translation；严重度只留 Major/Minor/Neutral（Critical 因标注者间主观差异太大被刻意去掉）；运营权重 minor=1、major=5、fluency/punctuation 类 minor=0.1、non-translation=25，且每段最多记 5 个错误——权重是按重采样稳定性在 major∈[1,10] 扫出来的，不是拟合值[^freitag21]。需要澄清：社区常引的「4.8」不在此文，它出自 ESA 论文附录 B.1——作者扫 minor/major 权重比去拟合标注者的 0–100 直评分，得 `Seg.Score = −1·#minor − 4.8·#major`，「very close to the originally proposed 1:5」[^esa24]。即 4.8 是「衍生分拟合直评分」的产物，不是独立的黄金权重。

ESA（Error Span Annotation）是 WMT24 起取代 MQM 成为官方人类协议的两步法：标注者先在译文里标错误 span（major/minor 两档 + omission 专用 tag），再给该段打 0–100 分——主分取直评分，不是由 span 衍生的，论文明确警告 −5·#maj−1·#min 衍生公式不随段长缩放（长段被线性罚分压垮）[^esa24]。ESA 相对 MQM 的实测：标注者间一致 tau-c 0.254 vs 0.116，错误召回 66.6% vs 40.1%，快 ~32%，专家 MQM 单段成本最高 ~10×，而两者给出的系统排名 94.9% 一致[^esa24]。其 AI 变体 ESA^AI 让 LLM 先预填错误 span、人类只做核实，标注时间从 71s/段降到 31s/段、预算省 ~25%[^esaai24]——这正是「judge 预标 + 人审锚定」半自动流程的直接先例。ESA 已是 WMT 官方协议：WMT24 General MT 全部 11 个语向（含 ja→zh、en→zh）用它，产出的显著性簇比 DA+SQM 多 37% 而标注量减半[^wmt24general]；WMT25 的 15 个语向里 13 个用 ESA[^wmt25general]。

## 3. LLM-as-judge 路线：GEMBA 家族与错误标注式变体

GEMBA（Kocmi & Federmann, EAMT 2023）是第一个证明 GPT 级 LLM 能当 SOTA MT 评委的工作：四个 zero-shot prompt 变体（0–100 直评 DA/SQM、1–5 星、五分类），在 WMT22 上以系统级两两准确率 89.8%（带参考）/87.6%（无参考）压过 MetricX-XXL 的 85.0%，段级「仅略落后」最佳指标[^gemba23]。GEMBA-MQM（WMT23）改成固定 3-shot、让 GPT-4 在译文里标 MQM 式错误 span（critical/major/minor 三档，权重 25/5/1，段分 = −Σ 权重和）[^gembamqm23]。结果有重要的双面性：系统排名任务 96.5% 拿第 1（XCOMET-Ensemble 95.2%、MetricX-23 93.4%、CometKiwi 93.2%），但综合 meta-eval 0.802 只落第 3 簇（XCOMET-Ensemble 0.825）；在 MQM22 上 GEMBA-DA 直评（89.8%）反而微胜 GEMBA-MQM（89.4%）[^gembamqm23][^wmt23metrics]。直接读法：span 标注式在「排系统」和「找错」上更强，但综合段级相关性并不必然赢直评。一个对协议设计直接的细节：GEMBA-MQM 的类目表里 locale-convention 被作者删除，因为 GPT 会滥用它（在捷克文里把 Euros 标为 locale 错误）[^gembamqm23]——映射 convention 类目时必须给窄定义 + 枚举实例，否则同样的滥用会出现在 placeholder/over-translation 上。

WMT24 的 gemba_esa 条目把两者缝起来——先按 ESA 协议收集 MQM 错误 span，再赋最终分，是该届 prompt-based、reference-free 指标里最强的（0.711，第 2 簇）[^wmt24metrics]。独立复线的证据同向：EAPrompt（Findings ACL 2024）用「先识别 major/minor 错误→计数→推分」两阶段 prompt，在 WMT22 上系统级与段级双胜 GEMBA 式直评[^eaprompt24]；AutoMQM（WMT23）让 PaLM-2 标 span 后算法聚合（major −5、minor −1），段级胜过打分式 prompt，预测 span 覆盖人类 major 错误词的 >50%[^automqm23]；ThinMQM（NeurIPS 2025）在 reasoning 模型上确认「规则聚合错误 span ≥ 让模型再折算成分数」，且 reasoning 模型对简单样本会过度思考、虚高分[^thinmqm25]。反向警示同样充分：MQM-APE（COLING 2025）证明原始 LLM 错误标注系统性过预测——需要后置校验（post-edit 验证每个错误修了是否真变好）滤掉无影响错误[^mqmape25]；Rubric-MQM 指出 GEMBA-MQM 有 label bias 且对接近完美的译文评不动[^rubricmqm25]；LitEval-Corpus 发现 GEMBA-MQM 是文学 MT 最好自动指标却仍分不出人工翻译与直译 LLM 译文（9.6% vs 94.4%），即 span 标注式对文体/直译腔欠敏感[^liteval25]；WMT25 评测任务的总评是 LLM 自动评分员在系统级强、段级仍输给 YiSi-1/chrF/BERTScore 等参考基线，且 span 检出与严重度分类始终是 auto-rater 的短板[^wmt25eval]；DFKI 挑战集上 LLM-prompt 系在细粒度语言错误类目平均只有 69.7%，低于 chrF，只在 negation 上最好（97.4%）[^dfki24]。多智能体方向（M-MAD 按 MQM 维度分头辩论[^mmad25]、HiMATE 层级代理[^himate25]、InstructScore 蒸馏 7B[^instructscore23]）证明单发 judge 还有提升空间，但现阶段属超配。

## 4. 神经 QE 备选与 zh 覆盖现实

reference-free 的神经 QE 里：COMETKiwi-22（InfoXLM-Large ~560M，0–1 分，CPU 可跑）与 COMETKiwi-23（XLM-R XL 3.5B / XXL 10.7B）是 WMT22/23 QE 双冠，但权重 CC-BY-NC-SA-4.0——只能内部 bench，不能进产品[^cometkiwi22][^cometkiwi23]；XCOMET-QE（TACL 2024）独一份地产出词级错误 span + MQM 严重度 + 分，同许可限制[^xcomet24]；MetricX-24（mT5 系，预测 0–25 MQM 罚分，L/XL/XXL 三档）是唯一 Apache-2.0 可商用的 learned QE，但论文自陈盲区：不可靠检测欠翻、重复、标点缺失与「流利但不相关」的译文[^metricx24]——而 placeholder/untranslated 恰有两路免费确定性信号兜底，正好错位互补。zh 覆盖上没有任何 en→zh 的人类 MQM 评测集：最近证据是 WMT23 QE 在 zh→en 对 MQM 评测（COMETKiwi-23 第一）、WMT24 覆盖 ja→zh（MetricX-24-QE 在 zh 目标侧 sys-SPA 0.863/seg-acc 0.527）[^wmt23metrics][^wmt24metrics]。结论：神经 QE 可作三角校验臂（尤其 XCOMET-QE 的 span 输出与 judge 互证），但其 en→zh 校准同样无公开金标，不能替代自建的 ~200 段人工锚定集。

reference-based 指标的整体衰落有官方排名背书：WMT24 metrics 共 26 个参评，BLEU/spBLEU/chrF 官方排名第 23/22/20 位（BLEU 0.589、chrF 0.608 垫底区），榜首 MetaMetrics-MT 0.725、MetricX-24-Hybrid 0.721、XCOMET 0.719，reference-free 最强为 MetricX-24-Hybrid-QE 0.714 与 gemba_esa 0.711[^wmt24metrics]。另一条对本场景更致命的证据：WMT23 上 zh→en 人类参考译文质量差直接压低了所有 reference-based 指标的相关性——参考译文本身有噪时 reference-based 全线失真，而本场景根本没有参考，这正是主线只能走 judge/QE 的又一支撑[^wmt23metrics]。

## 5. judge 偏差与统计口径

自偏好偏差是被实证钉死的：Panickssery et al.（NeurIPS 2024）证明 LLM 评委能识别自己的生成（GPT-4 自识别 73.5%）且自识别与自偏好线性相关，偏差是机制性的而非风格偏好[^panickssery24]；Liu et al.「Narcissistic Evaluators」在 20×20 生成器×评委矩阵上复现，且 reference-free 设定下偏差更明显——正好是本场景设定[^narcissistic24]；Wataoka et al. 给出机制解释：评委偏好对自己困惑度低的文本，同家族模型的输出风格彼此熟悉，意味着同家族不同尺寸的 judge 只能部分缓解（消除了「这是我写的」识别，消不掉「这像我写的」熟悉度）[^wataoka24]。没有任何论文直接验证「换家族 judge 完全消除偏差」，但从机制链推断是当前最优可用缓解；同家族异尺寸 + 人工锚定实测残余偏差是当时的退路。其余需控制的 judge 偏差：位置偏差（成对比较需交换序）与冗长偏差[^mtbench23]、reasoning 模型对易例的过度思考[^thinmqm25]、LLM 对长段的罚分累积[^esa24][^penlength25]。

统计口径上社区惯例清晰：MT 评测显著性用 bootstrap 重采样（Koehn 2004 确立，300 句测试集即有功效）[^koehn04]；段级指标元评官方口径是 tie-calibrated pairwise accuracy（Deutsch et al. 2023 的 acc23，WMT22 起采用——Kendall 变体可被操纵且易 NaN）[^tiesmatter23]；官方工具 mt-metrics-eval 的显著性用 block bootstrap（k_block=100，块=文档级分组）——同文档内 segment 相关，必须整篇一起重采样[^mtme]；系统级报告用 pairwise accuracy（WMT24 起弃 Pearson 换 soft pairwise accuracy）[^wmt24metrics]。锚定集规模的社区先例：WMT22 人类 MQM 每系统 ~1.3k–1.9k segment[^tiesmatter23]、SummEval 1.6k 条[^summeval21]；「Navigating the Metrics Maze」的 delta-accuracy 框架证明精度差-准确率曲线比 p 值对测试集规模更稳健——对 ~1200 chunk 基线的规模论证是直接可搬的方法[^metricsmaze24]。功效分析规范见 Card et al. 2020[^card20]；Krippendorff α 是 span 标注一致性的标准度量。

## 6. 方案对比：直评 1–5 vs span 标注式

证据收敛后的图景：系统级两者打平（GEMBA-DA 89.8% ≈ GEMBA-MQM 89.4%）[^gembamqm23]；段级与可解释性 span 式占优（EAPrompt 双胜[^eaprompt24]、AutoMQM 段级胜[^automqm23]、错误可审计可直接映射六 flag、可接 ESA^AI 人审流程[^esaai24]）；代价是系统性坑位更多——过预测错误[^mqmape25]、convention 类目滥用[^gembamqm23]、长段罚分不缩放[^esa24][^penlength25]、文体盲区[^liteval25]、token 与解析成本数倍。对 flag 产出是刚需（修复闭环要吃 flag）的场景，直评省下的只是 token，丢掉的是可审计性与下游消费面。

本机 n=3 冒烟复现了文献图景：直评臂三对全给 5 分零 flag，MQM 臂在其中一对标出「approached→能够被到达」的真错译（minor，直评漏掉）；换用更强的 judge 后直评臂在同一段降到 4 分并在 note 里点名同一处生硬——judge 强度本身比协议形态更能决定直评检出率；span 臂给出 2 条 minor，ESA 臂 stated=92 vs derived=99——两个模型上 stated 都系统性低于 derived，衍生分偏乐观，正好支持「主分取 stated、derived 只作自洽校验」的设计。引文块两模型双臂零误报，convention 类目首轮没有复发 GEMBA-MQM 的滥用坑。

推荐协议 = gemba_esa 式两步单发：judge 一次调用同时产出 `{errors:[{span, category, severity, note}], score: 0-100}`；主分取声明分（ESA 实证直评优于衍生[^esa24]），衍生分（−1/−5/−25，每段≤5 错误封顶[^freitag21]）只做自洽校验——`|stated − derived|` 超阈值即触发第二意见。这比纯 GEMBA-MQM 多一个免费的一致性信号，又比纯直评多可审计 span；WMT24 prompt 系第一名 gemba_esa 正是此形态[^wmt24metrics]。

## 7. 落地清单（已实施，以 qualbench.py 现状为准）

- judge prompt：ESA 式两步协议——先列错误 span（span 须为译文逐字子串）再赋 0–100 分。类目表 = 六 flag 的 MQM 化：`untranslated_spans→accuracy-omission`（整段未翻单列 non-translation=critical）、`hallucinated_content→accuracy-addition`、`term_inconsistency→terminology`、`over_translation→convention-do_not_translate`（窄定义枚举：人名/引文条目/数学与命令被翻，防 GEMBA-MQM 的 locale 滥用覆辙）、`placeholder_broken→convention-placeholder`（major 起、多处损坏升 critical）、`grammar→fluency-grammar`，外加 `fluency-register`（学术腔/直译腔，report-only 不计罚分——LitEval 证据表明此类判断最不可信，先入人审校准再谈入分）[^liteval25][^gembamqm23]。severity 三档沿用 minor/major/critical，但 critical 只许枚举的致命类目（整段未翻、占位符结构报废、增译翻转含义）——Freitag 弃 critical 是因为人类标注不稳，LLM 同样需要收窄触发面[^freitag21]。
- 分数与 record 面：主分 0–100（GEMBA-DA/ESA 口径），1–5 由分带映射保留报表兼容（如 ≥95→5）；record 增列 `errors[]`（含 span_verified=span 是否为译文子串）、`stated100`、`derived100`、`score_delta`；records.jsonl 的 key 并入协议版本（`{model}|{paper}|{chunk}|{judge}|{protocol_v}`）——防旧协议分数静默截留新协议产出。确定性信号（ph_missing/ph_invented/en_residue）升格为仲裁器：ph 缺失但 judge 未报 convention-placeholder ⇒ 判 judge 漏检进 contested，不再信 judge 的干净票。
- judge 路由：主 judge 与被评模型异尺寸；第二意见触发规则：|stated−derived|>15、stated≤55（≈直评 ≤2）、任一 critical、确定性信号矛盾、或与复评分歧。与被评同型的模型永不任 judge——judge≠translator 按 chunk 级 meta.model 强制。judge 侧参数：temperature 0.1、max_tokens ≥8192（reasoning 模型思考烧预算）。
- 抽样分层：基线 ~1200 chunk 从已 finished 译文池抽——~300–400 篇 × 3–4 chunk 优于少数论文多抽：文档即 bootstrap 聚类单元，簇多 CI 才窄（同 deff 论证）。kind 配额：para 按长度三分层（Penalizing Length 警示要求长度分层看分数行为[^penlength25]），caption/section_title 各保底 ~150 保证单层可下结论。冻结回归子集 = 从基线里钉 ~300 chunk + 钉 protocol_version + 钉 judge 模型，门禁指标 = 分数分布漂移 + flag 率 + per-kind 均值，不走逐 chunk 比对（judge 有随机性，阈值留给 CI）。
- 人工锚定 ~200 chunk：走 ESA^AI 半标注流——judge 预标 span、人核改判 + 给 0–100[^esaai24]。校准产出四件：stated-score 与人分的 Pearson/Spearman、pairwise accuracy（acc23 口径[^tiesmatter23]）、judge−人 分类别 Δ（重点看 convention 与 register 两类的系统性偏差）、错误 span 的 precision/recall。门槛不设硬 Pearson（文献无此惯例，WMT 用相对排名[^wmt24metrics]），内部门禁建议：系统级排名与人判一致 + 段级 pairwise acc ≥0.65 + 无对同系模型输出的系统性高分（残余自偏好实测面）。
- 统计与报告：report 带 block bootstrap 95% CI——按 paper 整簇重采样 B=1000（mt-metrics-eval 惯例[^mtme]），均值/per-kind 均带 CI；臂间对比（换 prompt 版本、换翻译模型）用 pairwise accuracy 而非均值差，对齐 WMT 官方口径[^wmt24metrics]。成本折算：judge 面约为翻译臂消耗的 ~2%。
- 风险与开放项：同家族 judge 池是结构性弱点——跨家族三角臂待非本系模型可用后补；XCOMET-QE/MetricX-24-QE 可作非 LLM 对照（前者许可限内部、后者 Apache-2.0 可留，但都有已知盲区[^xcomet24][^metricx24]）；WMT25 段级 LLM judge 仍输参考基线意味着 chunk 级个别分不可全信——回归门禁用分布与聚合量，不用单分[^wmt25eval]；span 过预测建议先记录不滤（MQM-APE 的 post-edit 校验是二阶段成本[^mqmape25]），待人审锚定量化过预测率再决定是否加校验臂。

### 参考文献

[^freitag21]: Freitag, Foster, Grangier, Ratnakar, Tan, Macherey. Experts, Errors, and Context: A Large-Scale Study of Human Evaluation for Machine Translation. TACL 2021. [arXiv:2104.14478](https://arxiv.org/abs/2104.14478)

[^esa24]: Kocmi, Zouhar, Avramidis, Grundkiewicz, Karpinska, Popović, Sachan, Shmatova. Error Span Annotation: A Balanced Approach for Human Evaluation of Machine Translation. WMT 2024. [aclanthology.org/2024.wmt-1.131](https://aclanthology.org/2024.wmt-1.131/)

[^esaai24]: Zouhar et al. ESA^AI: LLM-assisted Error Span Annotation. 2024. [arXiv:2406.12419](https://arxiv.org/abs/2406.12419)

[^wmt24general]: Kocmi et al. The LLM Era Is Here but MT Is Not Solved Yet: WMT24 General MT Findings. WMT 2024. [aclanthology.org/2024.wmt-1.1](https://aclanthology.org/2024.wmt-1.1/)

[^wmt25general]: WMT25 General MT Findings（ESA for 13/15 pairs）. WMT 2025. [aclanthology.org/2025.wmt-1.22](https://aclanthology.org/2025.wmt-1.22/)

[^gemba23]: Kocmi, Federmann. Large Language Models Are State-of-the-Art Evaluators of Translation Quality. EAMT 2023. [arXiv:2302.14520](https://arxiv.org/abs/2302.14520)

[^gembamqm23]: Kocmi, Federmann. GEMBA-MQM: Detecting Translation Quality Error Spans with GPT-4. WMT 2023. [arXiv:2310.13988](https://arxiv.org/abs/2310.13988)

[^wmt23metrics]: Freitag et al. Results of WMT23 Metrics Shared Task: Metrics Might Be Guilty but References Are Not Innocent. WMT 2023. [aclanthology.org/2023.wmt-1.51](https://aclanthology.org/2023.wmt-1.51/)

[^wmt24metrics]: Freitag et al. Are LLMs Breaking MT Metrics? Results of the WMT24 Metrics Shared Task. WMT 2024. [aclanthology.org/2024.wmt-1.2](https://aclanthology.org/2024.wmt-1.2/)

[^wmt25eval]: Lavie et al. Findings of the WMT25 Shared Task on Automated Translation Evaluation Systems. WMT 2025. [aclanthology.org/2025.wmt-1.24](https://aclanthology.org/2025.wmt-1.24/)

[^eaprompt24]: Lu, Qiu, Ding, Zhang, Kocmi, Tao. Error Analysis Prompting Enables Human-Like Translation Evaluation. Findings of ACL 2024. [arXiv:2303.13809](https://arxiv.org/abs/2303.13809)

[^automqm23]: Fernandes et al. The Devil Is in the Errors: Leveraging Large Language Models for Fine-grained Machine Translation Evaluation (AutoMQM). WMT 2023. [arXiv:2308.07286](https://arxiv.org/abs/2308.07286)

[^thinmqm25]: Zhan, Huang, Yang, Chao, Yang, Wong. ThinMQM: Efficient MQM Evaluation with Reasoning Models. NeurIPS 2025. [arXiv:2510.20780](https://arxiv.org/abs/2510.20780)

[^mqmape25]: Lu et al. MQM-APE: Toward High-Quality Error Annotation Predictors for MT Evaluation. COLING 2025. [aclanthology.org/2025.coling-main.374](https://aclanthology.org/2025.coling-main.374/)

[^rubricmqm25]: Kim. Rubric-MQM: Improving LLM-based MT Evaluation with Rubric-style Prompting. ACL 2025 Industry. [aclanthology.org/2025.acl-industry.12](https://aclanthology.org/2025.acl-industry.12/)

[^liteval25]: LitEval-Corpus: Evaluating Literary MT — GEMBA-MQM cannot separate human from literal LLM translations. NAACL 2025. [aclanthology.org/2025.naacl-long.548](https://aclanthology.org/2025.naacl-long.548/)

[^mmad25]: Feng et al. M-MAD: Multidimensional Multi-Agent Debate for MT Evaluation. ACL 2025. [arXiv:2412.20127](https://arxiv.org/abs/2412.20127)

[^himate25]: HiMATE: Hierarchical Multi-Agent Translation Evaluation. Findings of EMNLP 2025. [aclanthology.org/2025.findings-emnlp.593](https://aclanthology.org/2025.findings-emnlp.593/)

[^instructscore23]: Xu et al. INSTRUCTSCORE: Towards Explainable Text Generation Evaluation. EMNLP 2023. [arXiv:2305.14282](https://arxiv.org/abs/2305.14282)

[^cometkiwi22]: Rei et al. CometKiwi: IST-Unbabel 2022 Submission for the Quality Estimation Shared Task. WMT 2022. [arXiv:2209.06243](https://arxiv.org/abs/2209.06243)

[^cometkiwi23]: Rei et al. Scaling up CometKiwi: WMT23 QE Submission. WMT 2023. [arXiv:2309.11925](https://arxiv.org/abs/2309.11925)

[^xcomet24]: Guerreiro et al. xCOMET: Transparent Machine Translation Evaluation through Fine-grained Error Detection. TACL 2024. [arXiv:2310.10482](https://arxiv.org/abs/2310.10482)

[^metricx24]: Juraska, Deutsch, Finkelstein, Freitag. MetricX-24: The Google Submission to the WMT 2024 Metrics Shared Task. WMT 2024. [aclanthology.org/2024.wmt-1.35](https://aclanthology.org/2024.wmt-1.35/)

[^panickssery24]: Panickssery, Bowman, Feng. LLM Evaluators Recognize and Favor Their Own Generations. NeurIPS 2024. [arXiv:2404.13076](https://arxiv.org/abs/2404.13076)

[^narcissistic24]: Liu, Moosavi, Lin. LLMs as Narcissistic Evaluators. Findings of ACL 2024. [arXiv:2311.09766](https://arxiv.org/abs/2311.09766)

[^wataoka24]: Wataoka, Takahashi, Ri. Self-Preference Bias in LLM-as-a-Judge. NeurIPS 2024 workshop. [arXiv:2410.21819](https://arxiv.org/abs/2410.21819)

[^mtbench23]: Zheng et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. NeurIPS 2023 D&B. [arXiv:2306.05685](https://arxiv.org/abs/2306.05685)

[^koehn04]: Koehn. Statistical Significance Tests for Machine Translation Evaluation. EMNLP 2004. [aclanthology.org/W04-3250](https://aclanthology.org/W04-3250/)

[^tiesmatter23]: Deutsch, Foster, Freitag. Ties Matter: Meta-Evaluating Modern Metrics with Pairwise Accuracy and Tie Calibration. EMNLP 2023. [arXiv:2305.14324](https://arxiv.org/abs/2305.14324)

[^mtme]: Google Research. mt-metrics-eval — WMT metrics meta-evaluation tooling（block bootstrap, k_block=100）. [github.com/google-research/mt-metrics-eval](https://github.com/google-research/mt-metrics-eval)

[^metricsmaze24]: Kocmi, Zouhar, Federmann, Post. Navigating the Metrics Maze: Reconciling Score Magnitudes and Accuracies. ACL 2024. [arXiv:2401.06760](https://arxiv.org/abs/2401.06760)

[^summeval21]: Fabbri et al. SummEval: Re-evaluating Summarization Evaluation. TACL 2021. [arXiv:2011.06161](https://arxiv.org/abs/2011.06161)

[^card20]: Card, Henderson, Khandelwal, Jia, Mahowald, Jurafsky. With Little Power Comes Great Responsibility. EMNLP 2020. [aclanthology.org/2020.emnlp-main.745](https://aclanthology.org/2020.emnlp-main.745/)

[^dfki24]: DFKI Challenge Set submission, WMT24 Metrics（LLM-prompt avg 69.7% on fine-grained categories）. WMT 2024. [aclanthology.org/2024.wmt-1.37](https://aclanthology.org/2024.wmt-1.37/)

[^penlength25]: Penalizing Length: MQM linear penalty accumulation penalizes long translations. 2025. [arXiv:2510.22028](https://arxiv.org/abs/2510.22028)
