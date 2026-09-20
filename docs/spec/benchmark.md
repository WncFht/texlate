# 评测套件规范 —— 评测器矩阵与分层契约

> spec/ 层唯一事实源：与 `bench/`、`tests/` 代码现状对齐。语料底材（各层口径/构建管线/治理）见 `spec/corpus.md`；单点调研证据以 `research/` 档案为准，本文不复述实测数字。

## 1. 总览：B1–B7 评测器

每个评测器对准管线一段 + 组合层。底材 = corpus 各层（`spec/corpus.md`），合成破坏案例各自生成[^suite]。

| # | 评测器 | 测哪段 | 落点脚本 | 底材 | 核心指标 |
| --- | --- | --- | --- | --- | --- |
| B1 | parsebench | 解析段 | `bench/py/parsebench.py` | corpus `extracted/` 全层 + fixtures | ok / identity / leak / dead·orphan / 漏斗 |
| B2 | fixtures | 解析段单元级 | `bench/py/fixture_assert.py` + `tests/test_bench_regression.py` | `bench/fixtures/*.tex` 手造 | 陷阱断言通过率 |
| B3 | compilebench | 编译段 + fixloop | `bench/py/compilebench_v3.py` + `bench/py/fixloop_bench.py` | corpus `raw.*` blob | clean/pdf~/FAIL、救回率、规则触发谱 |
| B4 | xlatbench | 翻译段 | `bench/py/xlatbench.py` + `bench/py/qualbench.py` | corpus chunk 抽样 | 硬契约率 / 延迟 / token 经济 / LLM-judge 质量 |
| B5 | e2ebench | 全链组合 | `bench/py/e2e_mock_bench.py` + `bench/py/e2e_real_bench.py` | corpus 子集 | 环节成功率漏斗 + 终态分布 |
| B6 | validbench | 校验段 | `bench/py/validbench.py` | 语料 chunk 变异生成 | 检出率 / error-FP / 延迟 |
| B7 | alignbench | 阅读体验锚点 | `bench/py/alignbench.py` | en/zh 编译产物对 | named-dest 保留率 / 链权 |

依赖序：`corpus → B1 → B4 → {B3, B5} → B7`；B2/B6 独立（合成输入）[^suite]。

## 2. 分层契约（TIERS）

`bench/TIERS.md` 定义"一个问题该在哪层被抓"——修复不算完，直到它能看见的最便宜那层被钉住[^tiers]：

| 层 | 入口 | 底材 | 量级 | 时机 |
| --- | --- | --- | --- | --- |
| L0 单元/断言 | `uv run pytest tests/`（含 `test_bench_regression.py` fixture 断言矩阵；契约产出走 `fixture_assert.py`） | 合成输入 + `bench/fixtures/` | 秒级/单文件 | 每 commit、CI 硬门 |
| L1 机制覆盖 | `uv run python bench/py/parsebench.py --corpus <root>` | corpus 主库全层（v1/v2/m1k/iclr 层已并入） | 分钟级 | 解析/归一化改动后、开批前 |
| L2 子集回归 | `bench/py/stagerun.py {parse,xlat,compile,fixloop} --n N --seed S` 或 `--ids` 定点 | `mechanisms.jsonl` 台账 + 分层 manifest | 分钟–小时 | stage 改动、新机制落账后定向重放 |
| L3 全量集成 | stagerun 全层全臂 + fixloop + sabotage 两臂 → `gate_scorecard.py` + `triage.py`（操作单 `bench/py/runbook_loop.md`） | corpus 全层 | 过夜 | 里程碑门、发版前 |

四条规则：能低不高（L0 能钉的不许只在高层撞见，批量发现的真坑沉淀回 L0）；逐层语义（每层绿只证明该层契约成立）；跨层不重复（同一断言不钉两层）；量级兑现（估时以 `runbook_loop.md` 为准，层级归属争议按"cheapest tier that can see it"裁决）[^tiers]。

## 3. 逐库评测协议（PROTOCOL）

外部 LaTeX 库选型期的四项对比协议（原 `bench/PROTOCOL.md`，2026-09-20 退役删除）[^protocol]：解析鲁棒性（corpus 全部 .tex，30s 超时）、陷阱断言（fixtures 逐条分类核对）、round-trip 保真（parse→serialize→原文对比，strict/normalized/diverged）、泄漏率（可译块内含 `$`/`\cite`/`\ref`/`\begin{` 的块占比）；报告落 `results/{lib}-report.md`。**注记**：M0 后 `parsebench.py` 是 `texlate.latex` 产品管线的正式评测器，逐库对比层只适用于选型期。

## 4. 各评测器规格

### 4.1 B1 · parsebench —— 解析段基准

逐 .tex 测量：parse ok/error/ms（30s 超时）、chunk 数与字符中位/p90、泄漏率（`$`/`\cite`/`\ref`/`\begin{`/`\if`/`\input` 六组正则）、round-trip 三档（strict/normalized/diverged + 首差异位）、flatten→vtex 展开足迹、fake-translation 死占位符/孤儿 chunk、scan/validate warnings、flatten 覆盖（是否被主文件 `\input` 图触及）[^parsebench]。

逐论文聚合：主文件定位（多根标 multi_doc）、class 名/选项、tex 数/总大小/非 UTF-8、**路由标签**（reject/xelatex/minted/non-utf8/no-hyperref——B3 的静态路由金标准）、孤儿 tex 清单、stratum_cell/cluster_id/事后分层权重。manifest 非空即抽样框（`--manifest` 切层）；泄漏逐条人工归因写回 `mechanisms.jsonl` 台账（benchmark→语料反馈环）[^parsebench]。

门槛（M0 gate）：parse ok 100% / strict identity ≥99.5% / leak ≤0.15%（chunk 级 CI 上界）/ dead·orphan 0 / flatten 覆盖按"排除 unreferenced 后触及率"口径[^v3plan]。

### 4.2 B2 · fixtures —— 陷阱断言集

底材 `bench/fixtures/`（**逐字节即语义——永不格式化/润色**，不进 format 链）[^protocol]：

| 文件 | 标记族 | 内容 |
| --- | --- | --- |
| `tricky.tex` | `@Tnn` | T01–T29 单点陷阱 26 条断言 + `_meta` 残留计数 info 行（T14 在 multi、T15/T28 未分配） |
| `tricky-209.tex` | — | LaTeX 2.09 旧式组合 3 条（`\beq/\eeq`、`\documentstyle`、`\def`）+ parse_ok |
| `tricky-multi/` | T14 | `\input/\include` 展平 4 条（注释掉的 `\input` 不得展开） |
| `tricky-w.tex` | `@Wnn` | 野机制 11 条（W11/W15/W50/W67/W75/W82/W83/W84/W90/W91/W92），`@Wnn` ↔ `mechanisms.jsonl` 台账行 |
| `tricky-w73/` | W73 | `\input{../}` 路径逃逸两向断言（根内照常 resolved inline / 出根行为钉死），目标件 `escape-outside.tex` |
| `tricky-wenc.tex` | W72 | 混合编码字节件（合法 UTF-8 + 孤立 latin1 字节共存） |
| `tricky-dollar.tex` | `@Dnn` | dollar 族 10 条（corpus `$`-leak 归因亚型钉） |
| `tricky-mask.tex` | `@Mnn` | MASK 族 11 条（W07/W11/W84/W92 机制钉——docclass/usepackage 跨行夹注释等） |
| `xlat-traps.tex` | `@Xn` | 翻译硬契约压力形 @X1–X4（遮蔽输出与 xlatbench S1–S4 逐字一致） |

断言函数 `assert_tricky`/`assert_209`/`assert_multi`/`assert_xlat`/W·D·M 各组在 `tests/test_bench_regression.py`（跑在 `texlate.latex` 产品解析器上）与 `fixture_assert.py` 共享——后者只做计时执行 + 契约三件套落盘。**生长机制**：parsebench 归因与台账 `found-in-wild` 条目达 `covered` 后 → 最小复现提取 + `@Xnn` 登记为永久断言，只增不减[^protocol][^suite]。

### 4.3 B3 · compilebench —— 编译段 + fixloop 基准

测归一化 + 注入 + 引擎 + 修复循环的真实救回能力。底材必须字节级保真渠道（图/.bst/.bbl 齐全才可编——scholarweave 有损源在此被排除的根因）+ B1 路由标签作静态路由金标准[^suite]。

- `compilebench_v3.py`：base 臂分层抽样 × 原文直编 × 双引擎（xelatex/tectonic），引擎与判定走产品实现（`engine_for` + `compile.judge`），回答"语料源文件本身多大比例能编出 PDF"（pipe 臂天花板基准）。
- `fixloop_bench.py`：paper × 引擎格 → 产品化 `fixloop`（编译→logparse→taxonomy→yaml 规则修复→重编，轮数上限按 meta），记录每轮 `{cat,pay,rule,result}` → 落 `cases.jsonl` 沉淀机制；verdict_sig 归因口径 = 首错 cat、构成众数超首错时改挂众数[^fixloop]。

指标：clean 率（分 condition/引擎/时代带）、救回率（fail→clean|pdf~）、规则 fires/rescues、stuck/unfixable 率、修复轮数分布。门槛（M2 出口）：200 篇语料 zh 条件编译成功率 ≥90%；reject 判定正确率 100%（路由标签对拍）；无回归（clean 格不被规则改脏）[^suite]。

### 4.4 B4 · xlatbench —— 翻译段基准

两子层[^suite]：

- **B4a 硬契约层** `xlatbench.py`：对内部 OpenAI 兼容网关模型集跑分层抽样 LaTeX 段落翻译，逐调用过 L0 validator + 三条增强判定；样例池按 `--where` 切 manifest 层、`--docs N` 跨 cluster 轮转、chunk 按 context-kind 分桶等距取，尾部挂 S1–S4 合成压力（与 `xlat-traps.tex` @Xn 遮蔽输出逐字一致，`assert_xlat` 钉住产品口径）。指标排序：硬契约率 → ord 软信号 → 延迟 p50/p95 → reasoning 开销 → token 经济。用途：模型选型/白名单刷新 + prompt 措辞回归（bump prompt_version 必跑）[^xlatbench]。
- **B4b 质量层** `qualbench.py`：LLM-judge 对 (src_en, zh) chunk 对打 ESA 协议 errors[] + stated100 分 + 派生六类 flag（漏译/错译/术语不一致/格式破坏/幻觉/语言混杂），按 paper/model/kind 聚合；judge 模型与被评模型解耦（`--judge-model`），支持离线 mock judge 全链自检[^qualbench]。

门槛（M1 出口）：100 篇真实翻译端到端 ≥85%；硬契约率大样本不回退；L0 检出率不回退[^suite]。

### 4.5 B5 · e2ebench —— 端到端组合基准

测全链组合后的逐环节成功率——单段绿不等于组合绿。harness 复用产品模块 `texlate.e2e`（`mock_translate_tree`/`pipe_condition`/`base_condition`，CLI `texlate run` 与 bench 同路径），翻译走 `XlatPipeline` + L0 校验器产品 API[^suite]。

- `e2e_mock_bench.py`：Mode A 位置忠实 mock（注入 ctex + 占位译文 + splice + 编译，验机械链路）；Mode B 幻觉 mock（注入占位符丢失/幻觉，验校验链兜底）；Mode C 位置扰动 mock（随机移位 ~10% 占位符，量化 splice 鲁棒性）；每 Mode 双引擎臂（pipe-xel/pipe-tec + base 归因臂）。已知盲区登记：`MockTranslator._PROSE_RUN_RX` 只认 ASCII 散文 run，非 ASCII 散文原样回显——mock 臂对含此类散文的语料过估"忠实"，真译臂不受影响[^suite]。
- `e2e_real_bench.py`：Mode D 真实臂——`GatewayTranslator(ChatClient)` 走内部 OpenAI 兼容网关（`TEXLATE_BASE_URL`/`TEXLATE_API_KEY` env），route→normalize→L0→splice→prepare_chinese→compile→judge 全产品链；`--fixloop onfail|always|never` pipe-fix 救回臂（产物树 copy → fixloop → 复判，union 取较优；`_want_fix` 谓词 = fail + misschar/error 级 partial，inject reject 不救）[^e2ereal]。

产出**漏斗看板**：下载/解包/定位/解析/翻译/校验/编译每环节成功率 + 终态分布（done/partial/fault/degraded_*）。门槛：mock A 全绿（PDF+identity+零残留占位+中文实际渲染）；mock B 破坏 100% 编译前捕获；Mode D 成功率即产品 SLA 观测点[^suite]。

### 4.6 B6 · validbench —— 校验段基准

测 L0/L1 校验器对 LLM 破坏的检出能力（校验器本身必须被语料验证）。底材：corpus 主文件抽干净 chunk → ph 层（含 `[[TYPE_n]]` 占位符）/raw 层（不动点展开回原文）两层 src↔zh 对，zh = 构造性伪译文；变异器施加 10 类破坏（c01 丢 `}`/c02 丢 `$`/c03–c04 env 破坏/c05–c06·c10 占位符类/c07 `\[` 不配对/c08 幻觉宏/c09 cite key——逐 (pair,level,kind) 落 `cases.jsonl`）+ 对抗手工探针（合法改写/不平衡继承/占位符换序/全角占位符等边界逐条断言）[^validbench]。

指标：检出率（按破坏类分列命中规则）、error-FP（干净对）、warn-only 率、延迟/对、lev≤2 修复建议率；L1 tree-sitter 层同口径（绝对/相对判定分开报）。门槛：10 类破坏 100% 检出、干净对 0 error-FP、L0 ≤1ms/对；新破坏类随真实 LLM 失败沉淀（B4 产出反向喂 B6）[^suite]。

### 4.7 B7 · alignbench —— 锚点保留基准

测 zh 重编译后 named-destination 锚点保留率（对照阅读器滚动同步质量上限）：pypdf 提双侧 named destinations → 同名配对 → 保留率 + 最大权值单调链（section 12/图表 10/equation 4/cite 2，`page.*` 权 0）；无 hyperref 工程走退化路径断言[^alignbench]。

门槛：有 hyperref 对保留率 ≥95%；**保留率 <95% 本身可当 zh 编译完整性探针**；分段器联动案例（`\input/\include/\label/\bibitem` 进 chunk 连锅端型）沉淀回 B2 fixtures[^suite]。

## 5. stagerun 批量驱动与套件外件

`bench/py/stagerun.py` 是五阶段批量驱动（`ingest → parse → xlat → compile → fixloop` 各一子命令、独立 executor、append 式 `records/{stage}.jsonl`、按 `(id,arm,upstream)` resume）；论文流过 DAG 靠 `work/{id}/` 中间产物树而非内存对象；`--layers` 切语料层、`--sem` 全局信号量压网关 in-flight、id 全链路 `canon_id` 归一[^stagerun]。各 stage 实现件：`stage_ingest.py`（corpus 物化副本 → `work/{id}/src/`）、`stage_parse.py`（route+normalize+parse_file → `zh/` + `parse.json`）、`stage_xlat.py`（XlatPipeline → `zh/` 就地翻译 + `xlat-{arm}.jsonl` 明细 + auth 断路器）、`stage_compile.py`（splice+inject+compile+judge，`--arm zh|base`）、`stage_fixloop.py`（非 clean 格就地修复 + post 复判）[^stagerun]。

配套件：`translators_bench.py`（xlat 臂工厂：arm ∈ `{mock, sabotage-b, sabotage-c, perturb, real}`，sabotage/perturb 带台账 `.ledger`/`.finalize` 逐块归因，注入实现以 `e2e_mock_bench` Mode B/C 为唯一事实源）；`triage.py`（records → `tickets.jsonl` 签名聚类 + `metrics.jsonl` 跨 run 趋势）；`gate_scorecard.py`（M2 门记分卡：end-state 末段胜 / union best-of 双口径并列）；`rundiff.py`（两 run 逐格迁移矩阵：degraded/improved/added/removed）；`wave.py`（修复波编排壳：`--mech`/`--rule` 反查 id → 开波，选样/对账/记分一律 subprocess 调既有脚本零重实现）；`preflight_batch.py`（批前一票闸：import walk + mock 链 + 磁盘 + manifest + 工具链 + 网关认证）；`quality_proxies.py`（后算器：leak_* 送译残留比率 / term_* 术语一致率，复用 `parsebench.LEAK_PATTERNS` 同口径）；`status_panel.py` + `task_ping.py`（本机只读状态面板 + 任务看板上报件）[^stagerun][^translators]。

另有专题/底层评测件：`gullet_bench.py`（展开机抽干流实测门）、`wrapfloat_bench.py`（wrapfig 绕排碰撞检出 + 降级修复验证，poppler bbox 交集信号）、`iclr_*.py`（ICLR 语料映射/取源/章节管线，`corpus_m1k` iclr 层与 `corpus_iclr_pdf` 的支撑件）。

## 6. bench/ts —— JS 侧库评测

`bench/ts/` 是选型期 JS 生态对比评测（独立 `package.json`、CommonJS、自带 `node_modules`）：`bench-lu.js`（latex-utensils 四项全测）、`bench-tsl.js`（tree-sitter-latex：ERROR/MISSING 节点定位 + 增量重解析演示 + validator 评估）、`ul_*.js`（unified-latex：corpus 鲁棒性 worker 隔离 + tricky 断言 + round-trip/leak）。协议同 §3 四项[^protocol]。

## 7. 产出契约与留痕纪律

1. **统一三件套**：每个评测器落 `bench/results/{name}-{corpus}-{date}/`——`files|cases.jsonl` 逐单元明细 + `summary.md` 漏斗/归因 + `papers|cells.json` 聚合；stagerun 系 run 目录为 `records/` + `work/{id}/` + `cases.jsonl` + `run_meta.json` 五件[^suite][^stagerun]。
2. `bench/results/` 划出 format/lint 链（改写型 formatter 与 check 类链都不覆盖），报告由脚本全权重写；fresh clone 不存在属预期——规范只引用其"结论已摘要进正文"的口径，不作依赖链接。
3. 留痕/保留谓词：real 臂 `zh/`（付费译文不可再生）与 `splice/`（时间点保真 + replay 播种源）不删，已归并提取至 `bench/zh-store/`（`spec/corpus.md` §8）；`src/`/`build-base/`/`_texmf/` 可重建已删；账本层镜像归档 `bench/archive-2026-09-20/`[^retention]。
4. 统计报告：核心层加权池化 + 宏平均双口径并列；CI = Wilson + 月簇稳健 bootstrap（簇重抽样敏感性）[^v3plan]。

## 8. 门槛汇总

| 里程碑 | 门 | 指标 |
| --- | --- | --- |
| M0 | B1+B2 | parse ok 100% / identity ≥99.5% / leak ≤0.15% / dead·orphan 0 / fixtures 断言矩阵全绿 |
| M0–M1 | B6 | 10 类破坏 100% 检出 / 干净对 0 error-FP |
| M1 | B4a+B4b | 硬契约率基线不回退 / 100 篇真实翻译端到端 ≥85% |
| M2 | B3 | 200 篇 zh 条件编译 ≥90% / reject 判定 100% / 无回归 |
| 常驻 | B5 | mock A 全绿 / mock B 破坏 100% 编译前捕获 / L3 `escaped>0` 硬门 |
| M3 | B7 | hyperref 对锚点保留率 ≥95% / 退化路径不崩 |

> 编号口径：本表 M0–M3 为里程碑门（对应 `decisions/background.md` 阶段线 M0→M4）；`log/roadmap-2026-09-17/ROADMAP.md` 中期工单另用 **MT1–MT10**，两套编号独立勿混。

### 参考文献

[^suite]: 仓内证据件 `docs/10-benchmark-suite.md`（旧规格原文，逐门证据矩阵见 [spec0910](../log/audit-2026-09-16/spec0910.md)）。
[^tiers]: 仓内证据件 `bench/TIERS.md`（验证分层契约原文）。
[^protocol]: `bench/PROTOCOL.md`（逐库评测协议原文）已于 2026-09-20 退役删除，原文见 git 历史；陷阱断言登记以 `tests/test_bench_regression.py` 的 TRICKY_IDS 为准。
[^v3plan]: 仓内证据件 [v3-plan](../research/corpus/v3-plan.md) §7–8（指标口径与门槛论证）与 [parsebench-v1](../research/corpus/parsebench-v1.md)。
[^parsebench]: 仓内证据件 `bench/py/parsebench.py` 模块 docstring 与 [parse-metrics-literature](../research/methods/parse-metrics-literature.md)。
[^fixloop]: 仓内证据件 `bench/py/{compilebench_v3,fixloop_bench}.py` docstring 与 [fixloop-rules](../research/latex/fixloop-rules.md)。
[^xlatbench]: 仓内证据件 `bench/py/xlatbench.py` docstring 与 [model-selection](../research/model-selection.md)（338 调用方法实证）。
[^qualbench]: 仓内证据件 `bench/py/qualbench.py` docstring（ESA 协议 + 六类 flag 口径）。
[^e2ereal]: 仓内证据件 `bench/py/e2e_real_bench.py` docstring 与 [hardening-notes](../research/product/2026-09-16-hardening-notes.md)（§2 pipe-fix `onfail` 语义）、[e2e-mock-pipeline](../research/product/e2e-mock-pipeline.md)。
[^validbench]: 仓内证据件 `bench/py/validbench.py` docstring 与 [validator-rules](../research/latex/validator-rules.md)、[validator-ts](../research/latex/validator-ts.md)。
[^alignbench]: 仓内证据件 `bench/py/alignbench.py` docstring 与 [alignment-probe](../research/latex/alignment-probe.md)。
[^stagerun]: 仓内证据件 `bench/py/stagerun.py` 模块 docstring 与 [hardening-notes](../research/product/2026-09-16-hardening-notes.md)（§1 stagerun 分阶段批量架构）、`bench/py/runbook_loop.md`。
[^translators]: 仓内证据件 `bench/py/translators_bench.py` docstring（臂工厂与台账 schema）。
[^retention]: 仓内证据件 `bench/RETENTION.md` 与 `bench/archive-2026-09-20/README.md`（2026-09-20 归零重启口径；RETENTION.md 正随库重组迁移，以落库后位置为准）。
