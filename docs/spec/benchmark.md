# 评测套件规范 —— 评测器矩阵与分层契约

> spec/ 层唯一事实源：与 `bench/`、`tests/` 代码现状对齐。语料底材（各层口径/构建管线/治理）见 `spec/corpus.md`；单点调研证据以 `research/` 档案为准，本文不复述实测数字。
> **Wave-F 口径（2026-09-23 起）**：旧 `bench/py/*.py` 驱动脚本全数退役，评测器一律改写为 kernel spec（`bench/py/specs/<名>.py`），统一入口 `uv run python bench/py/bench run <spec> [k=v …]`；产出契约由 `bench/results/` 目录改为 trizone 四区（§7）。逐件映射见 `dev/archive/benches-2026-09-20.md` Wave-F 注记与 `dev/tools-runbook.md` §3.5。

## 1. 总览：B1–B7 评测器

每个评测器对准管线一段 + 组合层。底材 = corpus 各层（`spec/corpus.md`），合成破坏案例各自生成[^suite]。

| #   | 评测器       | 测哪段           | spec（`bench run <名>`）                           | 底材                                | 核心指标                                      |
| --- | ------------ | ---------------- | -------------------------------------------------- | ----------------------------------- | --------------------------------------------- |
| B1  | parsebench   | 解析段           | `specs/parsebench.py`                              | corpus `extracted/` 全层 + fixtures | ok / identity / leak / dead·orphan / 漏斗     |
| B2  | fixtures     | 解析段单元级     | `specs/fixture_assert.py` + `tests/` 断言矩阵      | `bench/fixtures/*.tex` 手造         | 陷阱断言通过率                                |
| B3  | compilebench | 编译段 + fixloop | `specs/compilebench.py` + `specs/fixloop_bench.py` | corpus `raw.*` blob                 | clean/pdf~/FAIL、救回率、规则触发谱           |
| B4  | xlatbench    | 翻译段           | `specs/xlatbench.py` + `specs/qualbench.py`        | corpus chunk 抽样                   | 硬契约率 / 延迟 / token 经济 / LLM-judge 质量 |
| B5  | e2ebench     | 全链组合         | `specs/e2e_mock.py` + `specs/e2e_real.py`          | corpus 子集                         | 环节成功率漏斗 + 终态分布                     |
| B6  | validbench   | 校验段           | `specs/validbench.py`                              | 语料 chunk 变异生成                 | 检出率 / error-FP / 延迟                      |
| B7  | alignbench   | 阅读体验锚点     | `specs/alignbench.py`                              | en/zh 编译产物对                    | named-dest 保留率 / 链权                      |

依赖序：`corpus_* → B1 → B4 → {B3, B5} → B7`；B2/B6 独立（合成输入）[^suite]。

矩阵外 spec（同一 kernel 入口，不属 B 编号）：管线自检 `soak`（生产五段链串行）/`smoke`（checkout 自检）/`census`（湖审计）/`errsweep`（错误沉淀清扫）/`paid_stub`（付费门零花费自检）/`quality`（质量面代理 rescore）；专题 `gullet`（展开机实测）/`wrapfloat`（绕排碰撞）；语料构建 `frame_build`/`corpus_v3`/`corpus_layers`/`corpus_expand`/`corpus_hot`/`corpus_sw`。全名册 `bench spec list` 直出。

## 2. 分层契约（TIERS）

`bench/TIERS.md` 定义"一个问题该在哪层被抓"——修复不算完，直到它能看见的最便宜那层被钉住[^tiers]：

| 层           | 入口                                                                                            | 底材                                       | 量级        | 时机                             |
| ------------ | ----------------------------------------------------------------------------------------------- | ------------------------------------------ | ----------- | -------------------------------- |
| L0 单元/断言 | `uv run pytest tests/`（fixture 断言矩阵与 `fixture_assert` spec 共享 `specs/_fixture_matrix`） | 合成输入 + `bench/fixtures/`               | 秒级/单文件 | 每 commit、CI 硬门               |
| L1 机制覆盖  | `bench run parsebench`（湖格全层逐 .tex 测量）                                                  | corpus 主库全层（v1/v2/m1k/iclr 层已并入） | 分钟级      | 解析/归一化改动后、开批前        |
| L2 子集回归  | `bench run <spec> ids=<id,…>` 或 `n=<N>`/`seed=<S>` 抽样（各 spec 合法键见文件头 docstring）    | ledger records 台账 + 分层 manifest        | 分钟–小时   | stage 改动、新机制落账后定向重放 |
| L3 全量集成  | `bench run` 全层全臂 + fixloop + sabotage 两臂 → `bench gate` 终判 + `bench triage` 聚类分诊    | corpus 全层                                | 过夜        | 里程碑门、发版前                 |

四条规则：能低不高（L0 能钉的不许只在高层撞见，批量发现的真坑沉淀回 L0）；逐层语义（每层绿只证明该层契约成立）；跨层不重复（同一断言不钉两层）；量级兑现（估时以 `bench plan <spec>` 预报与各 spec docstring 为准，层级归属争议按"cheapest tier that can see it"裁决）[^tiers]。

## 3. 逐库评测协议（PROTOCOL）

外部 LaTeX 库选型期的四项对比协议（原 `bench/PROTOCOL.md`，2026-09-20 退役删除）[^protocol]：解析鲁棒性（corpus 全部 .tex，30s 超时）、陷阱断言（fixtures 逐条分类核对）、round-trip 保真（parse→serialize→原文对比，strict/normalized/diverged）、泄漏率（可译块内含 `$`/`\cite`/`\ref`/`\begin{` 的块占比）。**注记**：M0 后 `parsebench` spec 是 `texlate.latex` 产品管线的正式评测器，逐库对比层只适用于选型期。

## 4. 各评测器规格

### 4.1 B1 · parsebench —— 解析段基准

`specs/parsebench.py` 对湖格内每篇逐 .tex 测量：decode_tex + flatten_inputs + parse_file 走产品路径，parse ok/error/ms（30s 超时）、chunk 数与字符中位/p90/max、泄漏率（`$`/`\cite`/`\ref`/`\begin{`/`\if`/`\input` 六组正则 + 逐条 examples）、round-trip 三档（strict/normalized/diverged + first_diff + quick_ratio）、fake-translation splice 死占位符/孤儿 chunk、vtex_vs_src 展开足迹、bug1 ph_tail 探针、warn_kinds、unresolved_inputs[^parsebench]。

逐论文聚合：主文件定位（多根标 multi_doc）、class 名/选项、tex 数/总大小/非 UTF-8、**路由标签**（reject/xelatex/minted/non-utf8/no-hyperref——B3 的静态路由金标准）、孤儿 tex 清单、stratum_cell/cluster_id/事后分层权重。泄漏逐条人工归因写回 `mechanisms.jsonl` 台账（benchmark→语料反馈环）[^parsebench]。

门槛（M0 gate）：parse ok 100% / strict identity ≥99.5% / leak ≤0.15%（chunk 级 CI 上界）/ dead·orphan 0 / flatten 覆盖按"排除 unreferenced 后触及率"口径[^v3plan]。

### 4.2 B2 · fixtures —— 陷阱断言集

底材 `bench/fixtures/`（**逐字节即语义——永不格式化/润色**，不进 format 链）[^protocol]：

| 文件                | 标记族 | 内容                                                                                                   |
| ------------------- | ------ | ------------------------------------------------------------------------------------------------------ |
| `tricky.tex`        | `@Tnn` | T01–T29 单点陷阱 26 条断言 + `_meta` 残留计数 info 行（T14 在 multi、T15/T28 未分配）                  |
| `tricky-209.tex`    | —      | LaTeX 2.09 旧式组合 3 条（`\beq/\eeq`、`\documentstyle`、`\def`）+ parse_ok                            |
| `tricky-multi/`     | T14    | `\input/\include` 展平 4 条（注释掉的 `\input` 不得展开）                                              |
| `tricky-w.tex`      | `@Wnn` | 野机制 11 条（W11/W15/W50/W67/W75/W82/W83/W84/W90/W91/W92），`@Wnn` ↔ `mechanisms.jsonl` 台账行        |
| `tricky-w73/`       | W73    | `\input{../}` 路径逃逸两向断言（根内照常 resolved inline / 出根行为钉死），目标件 `escape-outside.tex` |
| `tricky-wenc.tex`   | W72    | 混合编码字节件（合法 UTF-8 + 孤立 latin1 字节共存）                                                    |
| `tricky-dollar.tex` | `@Dnn` | dollar 族 10 条（corpus `$`-leak 归因亚型钉）                                                          |
| `tricky-mask.tex`   | `@Mnn` | MASK 族 11 条（W07/W11/W84/W92 机制钉——docclass/usepackage 跨行夹注释等）                              |
| `xlat-traps.tex`    | `@Xn`  | 翻译硬契约压力形 @X1–X4（遮蔽输出与 xlatbench S1–S4 逐字一致）                                         |

断言矩阵与 pytest 单源共享 `specs/_fixture_matrix`——spec 在 load 时（主线程）完成全部 fixture 的 parse+ 双重建（SIGALRM 护栏只在主线程合法），stage fn 只做断言核对 + 计时落盘[^fixtureassert]。**生长机制**：parsebench 归因与台账 `found-in-wild` 条目达 `covered` 后 → 最小复现提取 + `@Xnn` 登记为永久断言，只增不减[^protocol][^suite]。

### 4.3 B3 · compilebench —— 编译段 + fixloop 基准

测归一化 + 注入 + 引擎 + 修复循环的真实救回能力。底材必须字节级保真渠道（图/.bst/.bbl 齐全才可编——scholarweave 有损源在此被排除的根因）+ B1 路由标签作静态路由金标准[^suite]。

- `specs/compilebench.py`：每格 = (paper × cond × engine)——`arm` = cond（`baseline` 原文直编 / `zh` normalize+prepare_chinese(ctex) 后直编），`variant` = `{engine}@{EPOCH}`；判定走产品 `engine_for` + `compile.judge`，冷 TEXMF 沙箱（每篇独立 TEXMFHOME/VAR/CONFIG，同 paper 各格经 same_id_serial 串行共享），回答"语料源文件本身多大比例能编出 PDF"（pipe 臂天花板基准）[^compilebench]。
- `specs/fixloop_bench.py`：paper × 引擎格 → 产品化 `texlate.compile.fixloop.fixloop`（编译→logparse→taxonomy→yaml 规则修复→重编，≤ruleset max_rounds=8 轮），逐格 verdict + baseline 对拍字段进 eval_records；verdict_sig 归因口径 = 首错 cat、构成众数超首错时改挂众数[^fixloop]。

指标：clean 率（分 condition/引擎/时代带）、救回率（fail→clean|pdf~）、规则 fires/rescues、stuck/unfixable 率、修复轮数分布。门槛（M2 出口）：200 篇语料 zh 条件编译成功率 ≥90%；reject 判定正确率 100%（路由标签对拍）；无回归（clean 格不被规则改脏）[^suite]。

### 4.4 B4 · xlatbench —— 翻译段基准

两子层[^suite]：

- **B4a 硬契约层** `specs/xlatbench.py`：对内部 OpenAI 兼容网关模型集跑分层抽样 LaTeX 段落翻译，逐格过 L0 validator + E22 硬契约判定落 metrics；样例帧沉为 spec 常量（`--where/--docs/--per-kind/--seed/--models/--runs` 不再可达——改常量=改 bench 定义，code_sha/spec_hash 自动换版），非 holdout 切片 union、canon 去重、跨 cluster 轮转、chunk 按 context-kind 分桶等距取，尾部挂 S1–S4 合成压力（与 `xlat-traps.tex` @Xn 遮蔽输出逐字一致）。指标排序：硬契约率 → ord 软信号 → 延迟 p50/p95 → reasoning 开销 → token 经济；分析动词 `bench xlat-report`（模型榜）/`bench xlat-rejudge`（存 src/zh 本地重判，免网关）读 eval_records[^xlatbench]。
- **B4b 质量层** `specs/qualbench.py`：LLM-judge 对 (src_en, zh) chunk 对打 ESA esa2 协议 errors[] + stated100/derived100 双分 + 派生六类 flag（漏译/错译/术语不一致/格式破坏/幻觉/语言混杂），contested 触发二裁；格模型 = 一 frame 行（paper, chunk_id, judge）一格，`variant=esa2@{EPOCH}|{judge}|{chunk_id}`，`dedup_key=(idc,arm,variant)`；judge 模型与被评模型解耦。分析动词 `bench qual-report`[^qualbench]。

门槛（M1 出口）：100 篇真实翻译端到端 ≥85%；硬契约率大样本不回退；L0 检出率不回退[^suite]。

### 4.5 B5 · e2ebench —— 端到端组合基准

测全链组合后的逐环节成功率——单段绿不等于组合绿。harness 复用产品模块 `texlate.e2e`/`pipecore`（CLI `texlate run` 与 bench 同路径），翻译走 `XlatPipeline` + L0 校验器产品 API[^suite]。

- `specs/e2e_mock.py`：每 paper × 每条件一格跑产品全链（route → normalize → MockTranslator → ctex 注入 → 编译 → judge → precheck→L2→fixloop）；`variant=cond` 四臂：`base-xel`/`pipe-xel`/`pipe-tec`/`base-tec`（归因臂，同 run pipe-tec clean 时 skip 抑制）。破坏语义由 `tests/_translators.py` 臂工厂承载（sabotage-b 幻觉注入 / sabotage-c 位置扰动 ~10% / perturb），带台账 `.ledger`/`.finalize` 逐块归因。已知盲区：`MockTranslator._PROSE_RUN_RX` 只认 ASCII 散文 run，非 ASCII 散文原样回显——mock 臂对含此类散文的语料过估"忠实"，真译臂不受影响[^e2emock]。
- `specs/e2e_real.py`：Mode D 真实臂——route → xlat(paid) → compile → fixloop → base → layoutqc 六段链，翻译走内部 OpenAI 兼容网关（`TEXLATE_BASE_URL`/`TEXLATE_API_KEY` env）全产品链；run 参数 `ids/only/model/concurrency/timeout/oversize_cap/no_probe`；`fixloop` 臂位 = fail + misschar/error 级 partial（inject reject 不救），`base` 臂为归因对拍，`layoutqc` 为最后变异段（产物进 vault 触发 harvest）[^e2ereal]。

产出**漏斗看板**：route/xlat/compile/fixloop/layoutqc 逐段终态分布 + reject_at 归因。门槛：mock A 全绿（PDF+identity+ 零残留占位 + 中文实际渲染）；mock B 破坏 100% 编译前捕获；Mode D 成功率即产品 SLA 观测点[^suite]。

### 4.6 B6 · validbench —— 校验段基准

测 L0/L1 校验器对 LLM 破坏的检出能力（校验器本身必须被语料验证）。底材：湖格主文件抽干净 chunk → ph 层（含 `[[TYPE_n]]` 占位符）/raw 层（不动点展开回原文）两层 src↔zh 对，zh = 构造性伪译文；变异器施加 10 类破坏（c01 丢 `}`/c02 丢 `$`/c03–c04 env 破坏/c05–c06·c10 占位符类/c07 `\[` 不配对/c08 幻觉宏/c09 cite key）+ 对抗手工探针（合法改写/不平衡继承/占位符换序/全角占位符等边界逐条断言）。格分两族 item：`vb_run`（每湖格一格，subprocess 30s 隔离 parse——SIGALRM 在 worker 线程非法）与对抗探针族[^validbench]。

指标：检出率（按破坏类分列命中规则）、error-FP（干净对）、warn-only 率、延迟/对、lev≤2 修复建议率；L1 tree-sitter 层同口径（绝对/相对判定分开报）。门槛：10 类破坏 100% 检出、干净对 0 error-FP、L0 ≤1ms/对；新破坏类随真实 LLM 失败沉淀（B4 产出反向喂 B6）[^suite]。

### 4.7 B7 · alignbench —— 锚点保留基准

测 zh 重编译后 named-destination 锚点保留率（对照阅读器滚动同步质量上限）：pypdf 提双侧 named destinations → 同名配对 → 保留率 + 最大权值单调链（section 12/图表 10/equation 4/cite 2，`page.*` 权 0）；无 hyperref 工程走退化路径断言。格模型 = 一 (论文，rel pdf) 对子一格（id 免 canon，eval_records 车道），对子来源 `TEXLATE_ALIGN_PAIRS` env → pairs.jsonl；同 paper 格 same_id_serial 共享 `paper_dir/_texmf` 冷 usertree + `workspace()/en` 编译备忘[^alignbench]。

门槛：有 hyperref 对保留率 ≥95%；**保留率 <95% 本身可当 zh 编译完整性探针**；分段器联动案例（`\input/\include/\label/\bibitem` 进 chunk 连锅端型）沉淀回 B2 fixtures[^suite]。

## 5. 内核与批驱动（trizone-ledger v2）

`bench/py/kernel/` 是唯一批驱动（设计 `spec/bench-trizone.md`，架构图 `spec/assets/trizone-arch.svg`；旧 stagerun 五阶段驱动已随 Wave-F 删除）。模型：spec 声明 stage 链 + items 帧 + `needs` 依赖 + `mutates` 产物 kinds；kernel 逐格走 dedup（非付费段看上格终态）/ 付费预言机（`dedup.check` 五态：UNSEALED/CLAIMED/VERIFIED/MISSING/ABSENT，付费段须显式 `dedup_key`）→ needs 闸 → executor 执行 → records/metrics 落 ledger，产物 harvest 进 vault[^trizone]。

配套面：`bench plan <spec>` 格数/估时预报 + dedup 覆盖报价；`bench doctor` 环境/工具链/网关批前闸（旧 preflight_batch 职责）；`bench status` 账本直读面板；分析动词族 `bench triage`/`rundiff`/`gate`/`dossier`/`xlat-report`/`xlat-rejudge`/`qual-report`/`booster-select`（`bench/py/verbs/`，逐件职责见 `dev/tools-runbook.md` §3.2）[^trizone]。

付费纪律：付费 spec 强制 `--max-cost`；`$ROOT/PAUSE` 存在时 `run`/`plan` 拒跑；`ctx.gateway()` 惰性构造即付费断言（claim + paid slot + PAUSE/AUTH_DEAD 前置全检）。翻译臂工厂 `tests/_translators.py` 保留（mock/sabotage-b/sabotage-c/perturb + 破坏台账面，被 `specs/_sabotage.py` 与 `e2e_mock` 引用）[^translators]。

专题件：`gullet`（展开机抽干流实测门）、`wrapfloat`（wrapfig 绕排碰撞 + 降级修复验证，poppler bbox 交集信号）、`iclr_*.py`（ICLR 语料映射/取源/章节管线，`corpus` iclr 层支撑件）。

## 6. bench/ts —— JS 侧库评测

`bench/ts/` 是选型期 JS 生态对比评测（独立 `package.json`、CommonJS、自带 `node_modules`）：`bench-lu.js`（latex-utensils 四项全测）、`bench-tsl.js`（tree-sitter-latex：ERROR/MISSING 节点定位 + 增量重解析演示 + validator 评估）、`ul_*.js`（unified-latex：corpus 鲁棒性 worker 隔离 + tricky 断言 + round-trip/leak）。协议同 §3 四项[^protocol]。

## 7. 产出契约与留痕纪律（trizone 四区）

1. **四区布局**（`$TEXLATE_BENCH_ROOT`，缺省取 XDG data 目录下 `texlate-bench/`；各区可经 `TEXLATE_{LEDGER,RUNS,VAULT,LAKE}_ROOT` 独立换挂载）[^trizone]：
    - `ledger/` —— append-only `events.jsonl` + `index.sqlite` 物化索引 + `sealed/` 封存段；records/metrics/eval_records/cases 全部落账。
    - `runs/` —— `runs/<spec>/<date>/<slug>/work/{idc}/` 逐格工作树 + run_meta；格间中间产物经 workdir 传递。
    - `vault/` —— 不可再生产物保险库：`vault/{kind}/{sid}/{arm,variant,altseq}/` 物理叶（kind ∈ zh/splice/state/layoutqc）+ `meta/` 描述文件 + `manifest.jsonl` + `quar/` 隔离区；付费译文与成品树的唯一归并处（继任旧 `bench/zh-store/`）。
    - `lake/` —— 可重建语料湖：`corpus/{source}/{sid}/` cell（extracted/raw/meta）+ `objects/` CAS 存储 + `catalog.jsonl` 状态机 + `durable/` 构建中间件。
2. **保留策略**（P3，`kernel/vault.py`/`cli.py`/`lake.py`）：splice 叶 slim 即焚（留主干同名 pdf+arm+log）；≥`CAS_LINK_FLOOR`(256KiB) 叶文件 CAS 硬链去重；prune 遇含付费资产的 blocked cell 按 `_SHELL_KEEP_GLOB` 收壳而非整格保留；corpus TARS 下载件即焚。动词：`bench vault slim|cas-link|verify|restore|adopt|tombstone|seed`、`bench prune`、`bench lake {status,evict,…}`[^retention]。
3. `runs/`、`vault/`、`lake/`、`ledger/` 全量在 format/lint 链外；fresh clone 不存在属预期——规范只引用其"结论已摘要进正文"的口径，不作依赖链接。
4. 留痕/保留谓词：付费产物（vault zh/splice/state 叶）不可再生不删；lake cell 可经 CAS + catalog 重建，evict 分 tier（orphan → extracted 投影 → raw）；账本 `sealed/` 段封存后不再重写。
5. 统计报告：核心层加权池化 + 宏平均双口径并列；CI = Wilson + 月簇稳健 bootstrap（簇重抽样敏感性）[^v3plan]。

## 8. 门槛汇总

| 里程碑 | 门      | 指标                                                                                  |
| ------ | ------- | ------------------------------------------------------------------------------------- |
| M0     | B1+B2   | parse ok 100% / identity ≥99.5% / leak ≤0.15% / dead·orphan 0 / fixtures 断言矩阵全绿 |
| M0–M1  | B6      | 10 类破坏 100% 检出 / 干净对 0 error-FP                                               |
| M1     | B4a+B4b | 硬契约率基线不回退 / 100 篇真实翻译端到端 ≥85%                                        |
| M2     | B3      | 200 篇 zh 条件编译 ≥90% / reject 判定 100% / 无回归                                   |
| 常驻   | B5      | mock A 全绿 / mock B 破坏 100% 编译前捕获 / L3 `escaped>0` 硬门                       |
| M3     | B7      | hyperref 对锚点保留率 ≥95% / 退化路径不崩                                             |

> 编号口径：本表 M0–M3 为里程碑门（对应 `decisions/background.md` 阶段线 M0→M4）；`log/roadmap-2026-09-17/ROADMAP.md` 中期工单另用 **MT1–MT10**，两套编号独立勿混。
>
> 现状指标（2026-09-24 时点）：见 [log/2026-09-24 磁盘策略落地与探针批指标](../log/2026-09-24-磁盘策略落地与探针批指标.md)——260 帧探针批 layoutqc 评估通过 42.7%、累计花费 $48.20、四区磁盘基线与已知缺口。

### 参考文献

[^suite]: 仓内证据件 `docs/10-benchmark-suite.md`（旧规格原文，逐门证据矩阵见 [spec0910](../log/audit-2026-09-16/spec0910.md)）。

[^tiers]: 仓内证据件 `bench/TIERS.md`（验证分层契约原文）。

[^protocol]: `bench/PROTOCOL.md`（逐库评测协议原文）已于 2026-09-20 退役删除，原文见 git 历史；陷阱断言登记以 `bench/py/specs/_fixture_matrix.py` 的矩阵定义为准。

[^v3plan]: 仓内证据件 [v3-plan](../research/corpus/v3-plan.md) §7–8（指标口径与门槛论证）与 [parsebench-v1](../research/corpus/parsebench-v1.md)。

[^parsebench]: 仓内证据件 `bench/py/specs/parsebench.py` 模块 docstring 与 [parse-metrics-literature](../research/methods/parse-metrics-literature.md)。

[^fixtureassert]: 仓内证据件 `bench/py/specs/fixture_assert.py` 与 `bench/py/specs/_fixture_matrix.py`（断言矩阵单源）。

[^compilebench]: 仓内证据件 `bench/py/specs/compilebench.py` docstring（格模型/冷 TEXMF 沙箱口径）。

[^fixloop]: 仓内证据件 `bench/py/specs/fixloop_bench.py` docstring 与 [fixloop-rules](../research/latex/fixloop-rules.md)。

[^xlatbench]: 仓内证据件 `bench/py/specs/xlatbench.py` docstring 与 [model-selection](../research/model-selection.md)（338 调用方法实证）。

[^qualbench]: 仓内证据件 `bench/py/specs/qualbench.py` docstring（ESA esa2 协议 + 六类 flag 口径）。

[^e2emock]: 仓内证据件 `bench/py/specs/e2e_mock.py` docstring（四臂条件 + 破坏语义）与 [e2e-mock-pipeline](../research/product/2026-09-14-e2e-mock-pipeline.md)。

[^e2ereal]: 仓内证据件 `bench/py/specs/e2e_real.py` docstring 与 [hardening-notes](../research/product/2026-09-16-hardening-notes.md)（§2 pipe-fix `onfail` 语义）。

[^validbench]: 仓内证据件 `bench/py/specs/validbench.py` docstring 与 [validator-rules](../research/latex/validator-rules.md)、[validator-ts](../research/latex/validator-ts.md)。

[^alignbench]: 仓内证据件 `bench/py/specs/alignbench.py` docstring 与 [alignment-probe](../research/latex/alignment-probe.md)。

[^trizone]: 仓内证据件 [bench-redesign-v2-trizone](../spec/bench-trizone.md)（四区/事件/预言机/付费门设计）与 `bench/py/kernel/` 模块 docstrings。

[^translators]: 仓内证据件 `tests/_translators.py` docstring（臂工厂与台账 schema）。

[^retention]: 仓内证据件 `bench/py/kernel/vault.py`（`slim_splice`/`cas_link_*`/`CAS_LINK_FLOOR`）、`kernel/cli.py::_cell_shrinkable`、`kernel/lake.py::shrink_shell` 与 [2026-09-24 磁盘策略落地](../log/2026-09-24-磁盘策略落地与探针批指标.md)。
