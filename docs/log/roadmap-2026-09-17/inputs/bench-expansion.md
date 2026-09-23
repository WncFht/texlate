# bench 扩展输入件 —— 语料盘点 / 扩规模路径 / 度量改进 / 排序建议

> **结论**：bench 扩展侦察：bulk 取源无瓶颈、real 臂网关是唯一规模瓶颈且有 promo 死线；10k 无结构障碍、50k 需先定磁盘治理。
> **状态**：时点证据（2026-09-17 口径）
> **日期**：2026-09-17（2026-09-20 迁入重编）

> roadmap-2026-09-17 输入件之一。口径：只读盘点，所有断言带 file:line 或实测出处；项目终极目标是「所有 arXiv 论文干净翻译」，语料/bench 演进守「加层不删层」约定（docs/09-benchmark-corpus.md:29）。

## 1. 现状盘点

### 1.1 语料四层结构（corpus_v3，合计 5,133 篇）

| 层      | 量    | 清单                                                 | 抽样框 / 渠道                                                                                                                                                                         | 回答的问题                           |
| ------- | ----- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| core    | 1,000 | `manifest.jsonl`                                     | frame.parquet 30 月簇 × cat_group 最大余数法配额（build_corpus_v3.py:892-917）；IA `arxiv-bulk` + HF `TIGER-Lab/arxiv-latex-5T` 双通道（build_corpus_v3.py:61-66），零 arxiv.org 请求 | 「全 arXiv 均匀成功率多少」          |
| booster | 200   | `manifest_booster.jsonl` + `booster_selection.jsonl` | agent 策展机制配额（B01-07 锚 + T/W 族拾遗），逐文件 `mech_tags` 多标签                                                                                                               | 「已知坑处理了吗」                   |
| expand  | 3,800 | `manifest_expand.jsonl`                              | 故障率加权（LAMBDA=1.0，build_corpus_expand.py:65）+ 30% 旧池复用（REUSE_FRAC=0.3，:66）；成员级 Range-GET 不落整 tar；QC 3800/3800 sha 全过（corpus-expand-qc-2026-09-16/QC.md）     | 「故障密度高的区域摸透了吗」         |
| hot     | 133   | `manifest_hot.jsonl`                                 | OpenAlex `S4306400194`（build_hot_layer.py:61）：hot-cite 2024-01-01+ 按 cited_by_count 降序（:133-134）+ hot-recent 2025-06-01+ sample=（:170）；走产品 e-print 通道取源             | 「真实用户负载（近期高引）表现如何」 |

总账见 `bench/corpus_v3/MANIFEST.md:4`（清单文件列）与 :7（5133 合计追记）；docs/09:29 同日勘误确认四层 1000+200+133+3800。上游另有 `bench/corpus/`（39 篇手挑陷阱，PROTOCOL.md:11）与 `bench/corpus_v2/`（139 篇分层随机）两个历史层，均保留不入新框。

抽样宇宙 `frame.parquet` = 3,164,528 行（docs/09:47），年代带分布 a≤2006 400,888 / b 07-11 325,304 / c 12-16 493,421 / d 17-20 598,334 / e 21-25 1,104,329 / f 2026+ 242k 不进样（docs/09:60）。时代漂移显著：a 带 hep-phys 37%、cs 仅 1.9% → e 带 cs 40% 反超（docs/09:60）——**cs 异质性风险集中在 d/e 带，恰是 expand/hot 主补方向**。

### 1.2 机制台账（mechanisms.jsonl，144 条）

144 条 = B01-07 配额锚 + T 族 fixture 种子 + W 族 found-in-wild；实测构成：kind 分布 found-in-wild 109 / known-trap 34 / suspected 1，status 分布 covered 25 / partial 119，examples 提名合计 309 id、13 条空（mechanism-subset-selection-2026-09-17.md:12）。消费端 `mech_ids.py` 已落：tag∩booster_selection ∪ registry examples → id 文件喂 stagerun `--ids`（mech_ids.py:30-42），rules.yaml 39 条规则已带 `mechanisms:` 声明字段（commit a9bcd5b）。

### 1.3 覆盖缺口（相对 arXiv 真实分布）

1. **逐文件机制标签只有 booster 200 格**。core/hot/expand 三层无 per-file mech_tags，只有 mechanisms.jsonl 的 309 个薄提名 id（mechanism-subset-selection-2026-09-17.md:15-19）；evidence 是自然语言 regex/feature 描述非可执行检测器，features.jsonl 在 bench/work_v3 staging 侧未沉淀——「改机制 X→跑覆盖 X 的子集」目前只能在 200 格上闭环。
2. **f 带（2026+，242k 行）完全未进样**（docs/09:54）。核心层止于 2412（TIGER 截止，docs/09:123），2025-2026 新稿只靠 hot-recent 36 篇代表——最新 LaTeX 生态（新宏包、新工作流）是净盲区。
3. **hot 层只完成 133/160**：hot-cite 目标 120 实得 97，hot-recent 目标 40 实得 36（MANIFEST.md:1043-1060）；pdf_only 跳过是真实负载固有类（docs/09:123）但缺口本身未补。
4. **eligible 口径排除 pdf_only/format∉{tar,gz}**（build_corpus_v3.py:776）——arXiv 全量里约 5% pdf-only 稿件（docs/09:62 按 ~5% 折损预留）不在任何层的抽样框内；它们恰是产品线上会遇到的无源稿。
5. id 月 ≠ v1 月（3.1% 偏移，docs/09:62）等 frame 坑已在构造期绕过，不是缺口但属复用 frame 时的既定纪律。

## 2. 扩规模路径（10k / 50k 账）

### 2.1 取源：bulk 通道无瓶颈，e-print 通道有硬限

core/expand 走 IA tar + TIGER-5T，**不触 arxiv.org**（build_corpus_v3.py:61-66），expand 层 3800 篇约一天落齐。瓶颈只在走产品 `acquire_source` 的 e-print 通道：`RateLimiter` GAP_SECONDS=3.05/host、DAILY_BUDGET=180、2×429/406 熔断 park 30min 翻倍至 2h（src/texlate/arxiv/ratelimit.py:39-47, 263），hot 层因此按 `--limit 85`/日续跑（build_hot_layer.py:24）。结论：**10k/50k 均匀扩展继续走 bulk 通道即可；只有「必须钉版 e-print」的增补（hot 类、版本敏感性抽查）受 180/日限**——50k 全走 e-print 需 ~278 天，走 bulk 无此约束。

### 2.2 real 臂网关：真正的规模瓶颈，且有死线

- 实测吞吐：realn200 conc20 墙钟 **90.0 s/格 ≈ 40-72 格/h**（realn200-2026-09-17/report.md:11）；小格 chunk 数填不满 20 worker 是非线性主因。
- 死线：swe-2-medium 免费 promo **2026-10-16 到期**（gateway 调研结论，`docs/research/gateway/2026-09-16-free-tokens.md`，本机存档未入库）；到期后免费池须重测。
- 独立限流面：上游账号级 429 drip 与本地并发闸是两个面，降并发无用、retry 阶梯空转是正确姿势（网关逆向文档实证）。
- 备用路径：本机第二内部网关（独立实例、max_rpm 80）；免注册 keyless 源（llm7/pollinations）不稳定只配当 fallback；高 ROI 付费/注册源（ModelScope 2000req/日、glm-4.7-flash、SiliconFlow Hunyuan-MT-7B 等）均需用户一次性注册。
- 账本：10k 全 real ≈ 140-250h 连续 conc20；50k ≈ 700-1250h——单一 promo 窗口（剩 ~29 天）内跑不完。**全量 real 不可行也不必要**：realn200 实证 mock/real 两臂 union pdf 同为 98.5%、零净回归（report.md:21,75），「mock 全量 + real 滚动探针」设计已被数据支持。

### 2.3 算力与磁盘

- stagerun 5k 规模估时（runbook_loop.md:50）：parse ~30min、xlat mock <1h、**compile zh+base ~7h、fixloop ~2500 格 ~7h**——逐段线性外推 50k 是 ~70h+70h 量级，12C 单机可扛但需波次切分；>30min 批一律 setsid 脱管（runbook_loop.md:72，harness 看门狗三连杀实证）。
- 磁盘现状：corpus_v3 20G + work_v3 28G + results 45G，卷余 363G/917G。按 core+expand 均重 ~4MB/篇估，50k 原始 blob ~185G；work/{id}/ 树（src/zh/splice/build-base/_texmf 五件套）与 results records/cases 同阶放大——**50k 需先定 work 树剪枝/归档纪律**（splice 现场留 fail 格、clean 格只留 records），否则 363G 不够。
- scorecard/triage 本身纯扫 records，O(分钟) 非瓶颈。

### 2.4 规模结论

到 10k：取源、mock 链、compile/fixloop 都是小时 - 天级，无结构障碍；real 臂只能探针化。到 50k：磁盘治理与 real 臂预算要提前设计，bulk 取源仍不构成瓶颈。

## 3. 度量改进

### 3.1 mock ↔ real 可比性

终末指标（union pdf/clean）两臂已对齐（98.5% vs 98.5%，realn200 report.md:21）。**体积类指标存在口径断点**：`translate_tree` 在 a08dda3 之前无文件闸，real 臂把 REVTeX dump/support 件也送译，chunk 体积类指标虚高、修复前后 run 不可直接比（report.md:55-59, scout-notes.md:37-44）。做跨波对比时须按 commit 切口径段。

### 3.2 verdict 组成签名（首错类别遮 bulk）

verdict.category 取首错类别独占归因：quant-ph/9703040 的 110 错里 108 是 `missing_number`（`\bffam` 旧字体宏族），illegal_unit 只是 first_error（illegal-unit-scout-2026-09-17/report.md:129）。同报告另实证 90 个 illegal_unit id 全是上游 mask、真族 ≈1%（report.md:3）——首错签名会把上游伤错误归到编译族。改进面现成：judge 已产 `error_cats`/`n_errors` 组成，records 的 errors[] 薄（仅 {code,cat,payload}）、first_error 原文埋 metrics 深处不被 triage 消费（still-manual-audit-2026-09-17.md:11-12）；最大缺口是把 fixloop 内部 first_error→taxonomy 分类器物化进 records，M2/M6 待人工面可塌掉大半（syntax 166+errors>3 140+other 131 可细分归路，still-manual-audit:21,56-58）。

### 3.3 翻译质量面代理指标（verdict 目前只有编译健康面）

verdict-proxy-spec-2026-09-17.md 已定三候选口径与接线点，全部可先纯后算校准阈值再谈进 verdict：

| 指标                                       | 输入                                     | 全量后算成本                           | 现状缺口                                               |
| ------------------------------------------ | ---------------------------------------- | -------------------------------------- | ------------------------------------------------------ |
| `leak_*`（送译前展开残留，六族正则）       | state.json `results[].source`            | <5min/5117 格（spec:47-49）            | 无——随时可跑                                           |
| `term_hit_rate`（术语表一致，real 臂限定） | state.json source+translation + glossary | <10min（spec:50）                      | `term_dict.json` 未接线，pipeline 未落盘（spec:31）    |
| `landmark_density`（zh pdf 锚点存活）      | zh pdf + 源树计数                        | ~1-1.5h 串行 / jobs8 ~10min（spec:51） | 无条件，可直接常态开                                   |
| `alignment_pairs`（en↔zh 名级配对）        | base pdf + zh pdf                        | 依赖 base 覆盖（spec:52）              | **loop1 build-base 覆盖=0**（spec:17），须先补 base 臂 |

风险纪律（spec:56-60）：先 metrics 观测字段不进 status/reasons；mock 臂 term 恒 null、leak 两臂同义，聚合按臂过滤。

### 3.4 增量 scorecard 与波间漂移

机制已齐：records 按 (id,arm,upstream) 末条胜 + code-stamp resume（stagerun_lib RecLog）；`rundiff.py` 已能出 A→B 迁移矩阵（improved/degraded/absent）；`gate_scorecard.py` 给出 union pdf/clean/GATE≥0.90（gate_scorecard.py:26）。当前 loop1 实测 cells=5117、pdf 97.89%、clean 84.76%、PASS——对比 HANDOFF-2026-09-16 快照 89.1%（§6.5）说明波次落地持续推高分数，**缺的只是「每波跑一次 rundiff+scorecard 快照」的固化节奏**，以及在分桶时并列展示 error_cats 构成防首错遮 bulk（§3.2）。

## 4. 排序建议（按信息增益/工作量比）

| #   | 项                                                                                                                                                                                   | 工作量                          | 预期信息增益                                                                                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **error_cats 组成签名 + first_error→taxonomy 物化进 records**：复用 fixloop 分类器，records errors[] 增厚+dossier evidence 上提（still-manual-audit M1/M2）                          | ~0.5-1d（分类器已存在，差导出） | 待人工归因面塌大半（syntax 166+errors>3 140+other 131）；消除首错遮 bulk 的归因错配（9703040 实证）                             |
| 2   | **质量面代理指标全量后算校准**（leak/term/landmark_density 三件套，纯读 state.json+ 现有 pdf，零改码）                                                                               | <1d 脚本 + ~1.5h 算             | 打开 M3 静默伤探测面（309 格 clean+warning 无签名可挂）；为「干净翻译」提供编译之外的第二轴证据；顺手补 term_dict.json 一行接线 |
| 3   | **base 臂补跑（compile --arm base 全量）**                                                                                                                                           | ~1.5h/5k 算 + 半条 runbook 命令 | build-base 覆盖 0→全：解锁 alignment_pairs；给出源健康基线，区分「源烂」与「管线引入」两类 fail                                 |
| 4   | **机制标签全层回填**：features.jsonl staging 沉淀 + evidence 规则改写为可执行检测器 → core/hot/expand 逐文件 mech_tags                                                               | ~1-2d（检测器重写为主）         | 机制子集选样从 booster-200 闭环扩到全 5133；「改规则→跑覆盖机制格」在 expand 高密度区生效；partial 119 条机制的覆盖缺口变可测   |
| 5   | **real 臂滚动探针 + promo 死线前排产**：固定每波分层抽 n≈200-300（hot/expand 加权——realn200 里 hot 仅 2 格），10-16 前优先把 real 覆盖缺口层跑完；post-promo 切备用内部网关 或注册源 | ~0.5d 设计 + 窗口期排产         | 保住唯一的真模型回归面；在免费额度内把「近期高引」这个最贴产品的层拿到 real 证据                                                |

另：50k 扩展落地前需要先定 work 树剪枝纪律（§2.3），属排产纪律而非独立项，并入对应波次 runbook 即可。
