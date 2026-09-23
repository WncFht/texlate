# BENCHES — bench/ 全量普查表

> 2026-09-20 全仓普查产物（17 路 census + 3 路对抗 verify，逐项 grep 反引 + git log 取证）。与 `tools-runbook.md` 互补：runbook 记「手法」，本表记「每个 bench 是什么 / 怎么跑 / 吃什么吐什么 / 成本 / 状态」。
>
> **状态口径**：`active` = 现役（被引用/有产出）；`one-shot` = 已完成使命、留作复现；`asset` = 数据/文档资产；`broken` = 当前跑不了（注明原因）；`dead` = 已死/被取代。
> **时效注记**：普查时点另一 lane 正在做语料重拆分（`bench/corpus*` 分库 staged-rename）与 bench 瘦身（`nightwatch.py`、`compilebench_v2.py`、`stage_timing.py`、`bench/py/scratch/` 已在 worktree 删除、未提交）；下文以 † 标注在飞删除件，留档备查。`bench/results/` 于 2026-09-20 归零重建，存活口径见 `bench/RETENTION.md`。
>
> **后注（2026-09-22）**：trizone-ledger v2 新内核已落地 `bench/py/kernel/`（设计 `bench-redesign-v2-trizone.md`——绿地口径不设兼容面，架构图 `assets/trizone-arch.svg`），日更 soak 链 2026-09-21 退役。
>
> **后注（2026-09-23 Wave-F）**：设计 §5.3 删除清单已执行——旧 harness（stagerun 族/评测器脚本/分析脚本/benchlib/corpus build_*/report/）全部删除，`bench/results/` 与 `bench/work_*/` 产物目录清零，run 产物迁仓外 `$TEXLATE_BENCH_ROOT/runs/`。继任面 = `specs/`（`bench run <spec>`）+ `verbs/`（`bench <verb>`）+ `kernel/`，逐件对应见 `tools-runbook.md` §3。下文各分节详录为删除前普查原文，保留作 forensic 记录；总表「状态」列已刷新为 Wave-F 终态（`已删 → 继任件`）。

## 总表

| bench                | 路径                                                                                        | 一句话用途                                                                                                                                      | 成本                 | 状态                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | -------------------------------------------------------------------------------------- |
| stagerun             | `bench/py/stagerun.py` + `stagerun_lib.py` + `stage_{ingest,parse,xlat,compile,fixloop}.py` | 五段批跑 DAG：ingest→parse→xlat→compile→fixloop，records jsonl 断点续跑                                                                         | LLM网关+LaTeX+重算力 | 已删 Wave-F → `specs/soak.py` + spec 套                                                |
| stage_timing †       | `bench/py/stage_timing.py`                                                                  | records 分位/慢纸计时报告 → `_timing/{json,md}`                                                                                                 | 无                   | 已删（09-20 在飞删除）                                                                 |
| status_panel         | `bench/py/status_panel.py`                                                                  | :8766 只读状态面板（进度漏斗/看板/进程/磁盘/台账）                                                                                              | 无                   | active——Wave-D 已改指 kernel runs/index                                                |
| task_ping            | `bench/py/task_ping.py`                                                                     | 原子写 tasks.d/<slug>.json 心跳看板                                                                                                             | 无                   | active                                                                                 |
| preflight_batch      | `bench/py/preflight_batch.py`                                                               | 批跑前一票闸：import 走查+mock链+磁盘+manifest+工具链+网关鉴权                                                                                  | 网络                 | 已删 Wave-F → `bench doctor`+`bench plan`                                              |
| wave                 | `bench/py/wave.py`                                                                          | 修复波编排：id 集解析→records 快照→stagerun 命令链→postmortem→scorecard                                                                         | LaTeX+网络           | 已删 Wave-F → `bench run`+`rundiff`+`gate`                                             |
| nightwatch †         | `bench/py/nightwatch.py`                                                                    | 隔夜批 watchdog 报告                                                                                                                            | 无                   | 已删（无人调用、无定时器）                                                             |
| parsebench (B1)      | `bench/py/parsebench.py`                                                                    | 产品解析器语料评测：ok/ms/identity/leak/死占位，分层加权+CI                                                                                     | 重算力               | 已删 Wave-F → `specs/parsebench.py`                                                    |
| fixture_assert (B2)  | `bench/py/fixture_assert.py`                                                                | 陷阱断言矩阵（@Tnn）跑产品解析器出 contract 输出                                                                                                | 无                   | 已删 Wave-F → `specs/fixture_assert.py`                                                |
| compilebench_v3 (B3) | `bench/py/compilebench_v3.py`                                                               | 语料 base 臂直接编译基线，双引擎                                                                                                                | LaTeX+重算力         | 已删 Wave-F → `specs/compilebench.py`                                                  |
| compilebench_v2 †    | `bench/py/compilebench_v2.py`                                                               | 旧版 B3（头注自标 LEGACY）                                                                                                                      | —                    | 已删                                                                                   |
| fixloop_bench        | `bench/py/fixloop_bench.py`                                                                 | B3 fixloop 营救率 + stagerun/e2e 复用的修复配方库                                                                                               | 网络+LaTeX+重算力    | 已删 Wave-F → `specs/fixloop_bench.py`（配方面入 `specs/_fixloop.py`）                 |
| xlatbench (B4a)      | `bench/py/xlatbench.py`                                                                     | 翻译硬契约回归：语料分块+S1–S4 陷阱→网关→L0 判                                                                                                  | LLM网关              | 已删 Wave-F → `specs/xlatbench.py`                                                     |
| qualbench (B4b)      | `bench/py/qualbench.py`                                                                     | 翻译质量臂：ESA 协议 LLM judge 打分+聚合                                                                                                        | LLM网关              | 已删 Wave-F → `specs/qualbench.py`                                                     |
| e2e_mock (B5-A)      | `bench/py/e2e_mock_bench.py`                                                                | mock 翻译全链 e2e + B/C 破坏注入单源                                                                                                            | LaTeX+重算力         | 已删 Wave-F → `specs/e2e_mock.py`                                                      |
| e2e_real (B5-B/D)    | `bench/py/e2e_real_bench.py`                                                                | 真网关 e2e（批量已让位 stagerun，留 lib+单篇冒烟）                                                                                              | LLM网关+LaTeX        | 已删 Wave-F → `specs/e2e_real.py`                                                      |
| validbench (B6)      | `bench/py/validbench.py`                                                                    | 校验器 bench：10 类腐化变异测 L0/L1 检出/FP/延迟                                                                                                | 重算力               | 已删 Wave-F → `specs/validbench.py`                                                    |
| alignbench (B7)      | `bench/py/alignbench.py`                                                                    | named-dest 锚点保留率评测（en/zh PDF 对）                                                                                                       | 无/LaTeX             | 已删 Wave-F → `specs/alignbench.py`                                                    |
| gullet_bench         | `bench/py/gullet_bench.py`                                                                  | gullet 展开流探针：计时/steps/warning/if-eval/不动点回填                                                                                        | 重算力               | 已删 Wave-F → `specs/gullet.py`                                                        |
| wrapfloat_bench      | `bench/py/wrapfloat_bench.py`                                                               | wrapfig 环绕碰撞检测（poppler bbox）                                                                                                            | LaTeX                | 已删 Wave-F → `specs/wrapfloat.py`                                                     |
| benchlib             | `bench/py/benchlib.py`                                                                      | bench 共享库：records IO/verdict_sig/judge_dict/层枚举（~30 importers）                                                                         | 无                   | 已删 Wave-F → `specs/_benchlite.py`                                                    |
| translators_bench    | `bench/py/translators_bench.py`                                                             | xlat 臂适配层：mock/sabotage/perturb 工厂+台账                                                                                                  | 无                   | active——`specs/_sabotage.py`/`e2e_mock` 引用                                           |
| triage               | `bench/py/triage.py`                                                                        | records 后处理：签名聚类→tickets+趋势+report                                                                                                    | 无                   | 已删 Wave-F → `bench triage`                                                           |
| rundiff              | `bench/py/rundiff.py`                                                                       | 两 run 逐格迁移比较器（transition 矩阵）                                                                                                        | 无                   | 已删 Wave-F → `bench rundiff`                                                          |
| harvest              | `bench/py/harvest.py`                                                                       | zh-store 收割器：终判 compile-clean → primary、已译非 clean → `_quarantine/`、落选 → `_alt/`（move 语义）+ manifest.jsonl 索引/`--reindex` 重建 | 无                   | 已删 Wave-F                                                                            |
| gate_scorecard       | `bench/py/gate_scorecard.py`                                                                | M2 出门记分卡：end-state/union 语义成功率+新鲜度闸                                                                                              | 无                   | 已删 Wave-F → `bench gate`                                                             |
| gwpilot              | `bench/py/gwpilot.py`                                                                       | 机会型批跑驱动：JSONL 队列续跑 + serve 模式并发闸代理                                                                                           | LLM网关              | 已删 Wave-F（裁决 drop：定死单网关后多租户调度面失效）                                 |
| quality_proxies      | `bench/py/quality_proxies.py`                                                               | S5 事后质量代理：leak/term/landmark 三系指标侧车                                                                                                | 无                   | 已删 Wave-F → `specs/quality.py`                                                       |
| qualanchor           | `bench/py/report/qualanchor.py`                                                             | ESA^AI 人工评审包生成+收割（judge 校准）                                                                                                        | 无                   | 已删 Wave-F                                                                            |
| qualdrift            | `bench/py/report/qualdrift.py`                                                              | judge 漂移哨兵：frozen-300 重判+漂移闸                                                                                                          | LLM网关              | 已删 Wave-F                                                                            |
| qualfreeze           | `bench/py/report/qualfreeze.py`                                                             | frozen-300 pinset 抽取+四信号分布漂移闸                                                                                                         | 无                   | 已删 Wave-F                                                                            |
| qualsample           | `bench/py/report/qualsample.py`                                                             | qualbench 分层基线采样器                                                                                                                        | 无                   | 已删 Wave-F                                                                            |
| qualstats            | `bench/py/report/qualstats.py`                                                              | qual 统计臂：block bootstrap CI+pairacc+report                                                                                                  | 无                   | 已删 Wave-F                                                                            |
| defect_ledger        | `bench/py/report/defect_ledger.py`                                                          | 缺陷底账：fuzz+手工 P0–P2+test pin 合并 jsonl/md                                                                                                | 无                   | 已删 Wave-F                                                                            |
| dossier              | `bench/py/report/dossier.py`                                                                | 单 id 全链档案：签名→证据→历史→规则链                                                                                                           | 无                   | 已删 Wave-F → `bench dossier`（run 档案口径）                                          |
| mech_ids             | `bench/py/report/mech_ids.py`                                                               | 机制标签↔id 双向索引+规则反查+覆盖审计                                                                                                          | 无                   | 已删 Wave-F                                                                            |
| mech_backfill        | `bench/py/report/mech_backfill.py`                                                          | manifest mech_tags 回填器                                                                                                                       | 无                   | 已删 Wave-F                                                                            |
| layout_bench         | `bench/py/report/layout_bench.py`                                                           | en↔zh 版面损伤挖掘：overfull/ink/特征→leaderboard                                                                                               | 重算力               | 已删 Wave-F                                                                            |
| l2_attr_probe        | `bench/py/report/l2_attr_probe.py`                                                          | L2 归因 _l2_localize 分布级探针                                                                                                                 | 重算力               | 已删 Wave-F                                                                            |
| extract_l2_fixture   | `bench/py/report/extract_l2_fixture.py`                                                     | 真实 log→tests/fixtures/logs 入库件生成器                                                                                                       | 无                   | 已删 Wave-F                                                                            |
| export_realbook      | `bench/py/report/export_realbook.py`                                                        | 真书 EPUB 双语插译 OCF 级回归                                                                                                                   | 无                   | 已删 Wave-F                                                                            |
| bench_pylatexenc     | `bench/py/report/bench_pylatexenc.py`                                                       | pylatexenc 横评（选型期已结案→archive 候选）                                                                                                    | 重算力               | 已删 Wave-F                                                                            |
| ieeA_bench           | `bench/py/report/ieeA_bench.py`                                                             | ieeA 参考实现横评（已结案→archive 候选）                                                                                                        | 重算力               | 已删 Wave-F                                                                            |
| plastex_bench        | `bench/py/report/plastex_bench.py`                                                          | plasTeX 横评（已结案→archive 候选）                                                                                                             | 重算力               | 已删 Wave-F                                                                            |
| texsoup_bench        | `bench/py/report/texsoup_bench.py`                                                          | TexSoup 横评（已结案→archive 候选）                                                                                                             | 重算力               | 已删 Wave-F                                                                            |
| texsoup_diverge      | `bench/py/report/texsoup_diverge.py`                                                        | texsoup 输出发散点一次性分析（→archive 候选）                                                                                                   | 无                   | 已删 Wave-F                                                                            |
| v2_diff              | `bench/py/report/v2_diff.py`                                                                | v1↔v2 双跑 diff（v1 已退役→空转，archive 候选）                                                                                                 | 重算力               | 已删 Wave-F                                                                            |
| build_corpus_v3      | `bench/py/corpus/build_corpus_v3.py`                                                        | v3 语料主构建+其他 builder 的共享库                                                                                                             | 网络+重算力          | 已删 Wave-F → `specs/corpus_v3.py`                                                     |
| build_corpus_layers  | `bench/py/corpus/build_corpus_layers.py`                                                    | holdout/dev_vol/dev_failmine/dev_recent 加层器                                                                                                  | 网络+重算力          | 已删 Wave-F → `specs/corpus_layers.py`                                                 |
| build_corpus_expand  | `bench/py/corpus/build_corpus_expand.py`                                                    | expand 层 +3866：失败率偏置采样+回填通道                                                                                                        | 网络+重算力          | 已删 Wave-F → `specs/corpus_expand.py`                                                 |
| build_sw_layer       | `bench/py/corpus/build_sw_layer.py`                                                         | scholarweave HF parquet 渠道适配（唯一 2025+ 免费批量源）                                                                                       | 网络+重算力          | 已删 Wave-F → `specs/corpus_sw.py`                                                     |
| build_hot_layer      | `bench/py/corpus/build_hot_layer.py`                                                        | hot 层：OpenAlex 高引+近期随机                                                                                                                  | 网络                 | 已删 Wave-F → `specs/corpus_hot.py`                                                    |
| build_corpus_m1k     | `bench/py/corpus/build_corpus_m1k.py`                                                       | m1k 评测语料 4 层 997 篇构建                                                                                                                    | 网络                 | 已删 Wave-F（manifest 留存）                                                           |
| build_corpus_v2      | `bench/py/corpus/build_corpus_v2.py`                                                        | v2 分层随机构建（产出已并入统一语料）                                                                                                           | 网络                 | 已删 Wave-F                                                                            |
| iclr 家族 ×6         | `bench/py/iclr_{fetch,map,pdf,pdf_sections,sections,stats}.py`                              | ICLR 章节长度研究管线（暂停至 10 月，续跑手册见 research）                                                                                      | 网络+重算力          | active（暂停）                                                                         |
| bench-lu             | `bench/ts/bench-lu.js`                                                                      | latex-utensils v7 横评（robustness/陷阱/round-trip/leak）                                                                                       | 重算力               | one-shot（套件保留）                                                                   |
| bench-tsl            | `bench/ts/bench-tsl.js`                                                                     | tree-sitter-latex 0.6.0 横评 + L1 同语法邻接                                                                                                    | 重算力               | one-shot（套件保留）                                                                   |
| ul_corpus            | `bench/ts/ul_corpus.js`                                                                     | unified-latex 语料横评（worker_threads）                                                                                                        | 重算力               | one-shot（套件保留）                                                                   |
| ul_tricky            | `bench/ts/ul_tricky.js`                                                                     | unified-latex @Tnn 陷阱断言                                                                                                                     | 无                   | one-shot（套件保留）                                                                   |
| ts libs              | `bench/ts/{common,ul_common,ul_worker}.js` + `package.json`                                 | 套件共享件 + npm 依赖清单（node_modules 是 L1 校验器硬依赖）                                                                                    | 网络                 | active                                                                                 |
| fixtures             | `bench/fixtures/`                                                                           | 陷阱 .tex 语料（@Tnn，字节即语义，禁格式化）                                                                                                    | —                    | asset·保护区                                                                           |
| frame                | `bench/frame/`                                                                              | 语料规划资产：universe parquet+item-index+分层配额（91M）                                                                                       | —                    | asset——`specs/frame_build.py` 可再生                                                   |
| PROTOCOL             | `bench/PROTOCOL.md`                                                                         | per-库评测协议                                                                                                                                  | —                    | 已删 2026-09-20                                                                        |
| TIERS                | `bench/TIERS.md`                                                                            | L0–L3 验证分层契约                                                                                                                              | —                    | asset·治理                                                                             |
| RETENTION            | `bench/RETENTION.md`                                                                        | results/ 留存契约                                                                                                                               | —                    | 已删 Wave-F（results/ 清零，契约失效）                                                 |
| results/*            | `bench/results/`                                                                            | run 产物目录                                                                                                                                    | —                    | 已删 Wave-F——账本入 `backup/phase0-20260922`，新产物落仓外 `$TEXLATE_BENCH_ROOT/runs/` |
| work_*               | `bench/work_{e2ereal,gwpilot,iclr,m1k,v3}`                                                  | 各管线工作区（gitignored）                                                                                                                      | —                    | 已删 Wave-F（spec 工作区在 runs/ 内）                                                  |
| .venv_babeldoc       | `bench/py/.venv_babeldoc/`                                                                  | babeldoc 对照实验专用 venv（664M macOS 原生件，bin/python 在 Linux 悬空）                                                                       | —                    | **已删** 2026-09-20（机制位保留，按需重建）                                            |

## 语料管线（bench/py/corpus/）

### build_corpus_v3.py — 语料主构建管线（`spec/corpus.md` S1–S5）

- **运行**：`uv run python bench/py/corpus/build_corpus_v3.py <plan|probe|fetch|zipsum|scan|frame-lookup|sample|extract|extract-booster|qc>`（extract 需 texlate.arxiv 走 uv；frame-lookup 需 pyarrow；其余纯 stdlib）
- **输入**：`bench/frame/{cluster_pick.json,item-index.csv,tiger-files.csv,frame.parquet}`、archive.org chunk tars、HF TIGER-Lab/arxiv-latex-5T
- **输出**：`bench/corpus/{id}/` cells、`manifest.jsonl`、`manifest_booster.jsonl`、`MANIFEST.md`、`bench/work_v3/` 状态
- **成本**：网络+重算力。**状态**：active——同时是 layers/expand/sw_layer/mech_backfill 的共享库（`import b3`），tests/test_bench_harness.py 单测。

### build_corpus_layers.py — 加层器（holdout/dev_vol/dev_failmine/dev_recent）

- **运行**：`python3 bench/py/corpus/build_corpus_layers.py plan|scan|extract|qc --layer <L>`；recent 臂 `uv run ... recent --layer X --ids-file bench/work_v3/sw/assign_*.jsonl`
- **输入**：bench/frame 索引、现有 manifest、n100 失败率结果、sw assign 清单、IA/TIGER tars
- **输出**：corpus cells + `manifest_{holdout,dev_vol,dev_failmine,dev_recent}.jsonl` + `bench/work_v3/{layer}/` 池+qc.md
- **成本**：网络+重算力。**状态**：active——语料 append-only 加层标准通道（import b3+bx）。

### build_corpus_expand.py — expand 层管线（+3866 篇）

- **运行**：`python3 bench/py/corpus/build_corpus_expand.py <plan|scan|extract|fetch-ids|qc>`（extract/fetch-ids 需 uv）
- **输入**：core/booster/expand manifest、work_v3 扫描池、frame 索引、n100 结果、`--ids-file` 孤儿清单
- **输出**：corpus cells + `manifest_expand.jsonl` + `bench/work_v3/expand/` 池+qc.md
- **成本**：网络+重算力。**状态**：active——fetch-ids 是机制主导的孤儿回填常驻通道；build_corpus_layers `import bx`。

### build_sw_layer.py — scholarweave HF 渠道适配

- **运行**：`env -i PATH=$PATH HOME=$HOME uv run --with pyarrow --with "fsspec[http]" python bench/py/corpus/build_sw_layer.py footers|pool|assign|rehydrate`（**必须 env -i**——ssh 泄漏的代理会打挂 HF SSL）
- **输入**：HF scholarweave/arxiv-latex 47 parquet shards（range-GET 列投影）
- **输出**：corpus cells（figures_stripped）、`manifest_dev_recent.jsonl` 行、`bench/work_v3/sw/` 状态
- **成本**：网络+重算力。**状态**：active——唯一免费 2025+ 批量 LaTeX 源且月度更新，可复跑新 row-group。

### build_hot_layer.py — hot 层构建（高引+近期）

- **运行**：`uv run python bench/py/corpus/build_hot_layer.py candidates|fetch|report`
- **输入**：OpenAlex API（source S4306400194）、arxiv.org/src、pin 缓存
- **输出**：corpus cells + `manifest_hot.jsonl` + `bench/work_v3/hot/`
- **成本**：网络。**状态**：one-shot——166 篇 hot 批已收官（MANIFEST 注「不再排续跑」），留作未来刷新通道。

### build_corpus_m1k.py — m1k 评测语料构建（4 层 997 篇）

- **运行**：`uv run python bench/py/corpus/build_corpus_m1k.py all`（或 select|materialize|emit）
- **输入**：corpus_daily 09-18 层、alphaXiv /papers/v3/feed、work_iclr/{map,accepted}.jsonl、dev 层、pin 缓存
- **输出**：corpus cells + `manifest_m1k-{recent,axhot,iclr,v3}.jsonl` + `bench/work_m1k/`
- **成本**：网络。**状态**：one-shot——997 篇已交付（b04379e7），manifest 受保护。

### build_corpus_v2.py — v2 分层随机构建（已并入统一语料）

- **运行**：`python3 bench/py/corpus/build_corpus_v2.py`（纯 stdlib，progress_v2.json 断点续跑）
- **输入**：tmp/exp/arxiv-serial2/ id 清单、arxiv.org/src
- **输出**：corpus cells + `manifest_v2.jsonl` + MANIFEST_v2.md
- **成本**：网络。**状态**：one-shot——产出层已合入统一语料，脚本留作 lineage 复现。

### bench/frame/ — 语料规划资产（91M）

universe `frame.parquet`、IA `item-index.csv`、TIGER `tiger-files.csv`、`cluster_pick.json`、strata/allocation/counts CSV——所有 v3 系 builder 的采样宇宙 + parsebench 后分层权重输入。gitignored 但活跃（09-19 索引刚重建）。**状态**：asset·keep。

### bench/queue/ — gwpilot 投递区（已删）

gwpilot JSONL 任务队列投递位；`night.jsonl` 已于 release 清理删除。**状态**：已删 Wave-F——gwpilot 裁决 drop，投递区一并清除。

## 批跑 DAG 与运维（stagerun 家族 + 监控编排）

### stagerun.py + stagerun_lib.py + stage_*.py — 五段批跑 DAG（现役主力）

- **运行**：`uv run python bench/py/stagerun.py {ingest|parse|xlat --arm mock|real|sabotage-b|sabotage-c|perturb|compile --arm zh|base|fixloop --on ...} [--layers ... --ids ... --jobs N --tag T --dir D]`（env：`TEXLATE_SRC/TEXLATE_CORPUS/TEXLATE_BASE_URL/TEXLATE_API_KEY`，real 臂默认内部 OpenAI 兼容网关）
- **输入**：corpus manifest 各层行、corpus/{id}/extracted、work/{id}/ 中间树、records/*.jsonl 续跑门
- **输出**：`bench/results/stagerun-<tag>-<date>/{records/*.jsonl, run_meta.json, cases.jsonl, work/{id}/{src,zh,splice,build-base,_texmf,parse.json,xlat-*.jsonl}}`
- **成本**：LLM 网关+LaTeX+重算力。**状态**：active——`stagerun_lib` 为内核（RecLog 追加/canon_id 归一/dedup_wids/run_meta），五个 `stage_*` 为段驱动：ingest（copytree）、parse（route+normalize+parse_file，原子 swap）、xlat（asyncio XlatPipeline+网关信号量+破坏臂）、compile（zh splice/base build-base+judge）、fixloop（--on 选格+yaml 规则修+_texmf 冷 usertree+重判）。run 收尾经 `harvest.py` 收割译文入 zh-store 后 work/ 可整删。
- †`stage_timing.py`（records 分位计时报告→`_timing/`）：普查窗口内被在飞 reorg 自 worktree 删除（index 留 HEAD 副本），本行留档。

### status_panel.py — :8766 只读状态面板（存活件）

- **运行**：`setsid nohup python3 bench/py/status_panel.py >> $TEXLATE_BENCH_ROOT/state/status-panel/run.log 2>&1 &`（stdlib-only；`PANEL_PORT` 默认 8766；停：`kill $(cat .../panel.pid)`）
- **输入**：`$TEXLATE_BENCH_ROOT/runs/**` records+run.log、tasks.d/*.json、agent session 状态文件、`bench gate --json`、ps/df/free/du/pdftotext、HANDOFF/overseer 台账
- **输出**：:8766 HTML（+/healthz）+ panel.pid + rate-state.json
- **成本**：无。**状态**：active——Wave-D 已把数据源改指 kernel runs/index；task_ping 生态的看板聚合器。

### task_ping.py — 看板心跳写入 CLI（存活件）

- **运行**：`python3 bench/py/task_ping.py <name> --status running --done N --total M [--note/--owner/--pid | --finish|--remove|--list]`
- **输出**：`$TEXLATE_BENCH_ROOT/state/status-panel/tasks.d/<slug>.json`（tmp+os.replace 原子写）
- **状态**：active——任何 agent/脚本可调用报进度。

### preflight_batch.py — 批跑前一票闸

- **运行**：`uv run python bench/py/preflight_batch.py [--no-net --min-free-gb 50 --layers ... --base-url ... --model ...]`
- **覆盖**：texlate import 走查+离线 mock 链+磁盘水位+manifest/extracted 普查+xelatex/tectonic/pdftotext PATH+网关 /v1/models 鉴权
- **成本**：网络。**状态**：active——runbook §0 强制闸，exit 1 拦批。

### wave.py — 修复波编排壳（runbook_loop §1–§5）

- **运行**：`uv run python bench/py/wave.py {run IDS.txt|--mech B01,W45|--rule R [... --go] | postmortem [RUN_DIR] [--deep --dossier-top 30] | scorecard [RUN_DIR|records] [--require-frozen --save]}`
- **输入**：ids 文件/--mech/--rule 选择器、run records、report/{mech_ids,dossier}.py、rundiff、gate_scorecard、stagerun.py
- **输出**：`bench/results/wave-<tag>-<date>/{ids.txt,before/,run_meta.json,wave.json,rundiff.md,postmortem.{md,json}}` + scorecard-history
- **成本**：LaTeX+网络。**状态**：active——fixloop 台账管线的波次调度（report/ 拆分后 mech_ids/dossier 路径已于 73bdff0b 重指修复）。

### †nightwatch.py — 隔夜 watchdog（已在飞删除）

单发 watchdog 报告（gwpilot 队列×停滞探测×孤儿 fd）。worktree 已删（index 留 HEAD）：无调用者、无定时器、其 gwpilot 队列 lane 已退役——删除既成事实由在飞 lane 提交。

## B 系列评测器（`spec/benchmark.md` §B1–B7 + 专项）

### parsebench.py（B1）— 解析鲁棒性评测

- **运行**：`uv run python bench/py/parsebench.py --corpus bench/corpus [--out DIR]`
- **输入**：corpus/{id}/extracted + manifest*.jsonl（stratum_cell/cluster_id/layer）+ frame strata-era-cat.csv
- **输出**：`bench/results/parsebench-{corpus}-{date}/{files.jsonl,papers.json,summary.md}`
- **成本**：重算力。**状态**：active——corpus identity 100%/leak 0.040% 现役口径产出者；quality_proxies 引其 LEAK_PATTERNS。

### fixture_assert.py（B2）— 陷阱断言 runner

- **运行**：`uv run python bench/py/fixture_assert.py --out DIR`
- **输入**：bench/fixtures/*.tex + tests/test_bench_regression.py 断言函数（98-case 矩阵 contract 输出路径）
- **输出**：`OUT/{cases.jsonl,cells.json,summary.md}`。**成本**：无。**状态**：active。

### compilebench_v3.py（B3）— base 臂编译基线

- **运行**：`uv run python bench/py/compilebench_v3.py [--gen-sample|--report]`
- **输入**：manifest*.jsonl（stratum_cell 比例采样）+ extracted；可选 v2 cells.json 对比
- **输出**：`bench/results/compilebench-v3-*-{date}/{sample.json,cases.jsonl,cells.json,summary.md}`；工作区 `bench/work_compile_v3`
- **成本**：LaTeX+重算力+网络。**状态**：active——test_bench_harness importorskip 目标。（†compilebench_v2 已在飞删除：头注自标 LEGACY。）

### fixloop_bench.py — B3 fixloop 营救率 + 修复配方单源

- **运行**：`uv run python bench/py/fixloop_bench.py [--only SUBSTR] [--report]`
- **输入**：compilebench-corpusv2 cells + corpus extracted + tlmgr --usermode/TLNET(TUNA)/tectonic
- **输出**：`bench/results/fixloop-corpusv2-*/{cases.jsonl,cells.jsonl,cells.json,summary.md}` + `bench/work_fixloop_v2/`
- **成本**：网络+LaTeX+重算力。**状态**：active——stage_fixloop.py:17/e2e_real_bench.py:74 复用其配方库（TUNA pin/冷 usertree/TlpdbIndex/CaseSink）。

### xlatbench.py（B4a）— 翻译硬契约回归

- **运行**：`uv run python bench/py/xlatbench.py run --models swe-2-medium,glm-5-2 [--runs 2 --docs N --per-kind 8 --seed 0 --where layer=core --out DIR --resume]`；另有 report/rejudge/samples 子命令（env `TEXLATE_BASE_URL/TEXLATE_API_KEY`）
- **输入**：corpus manifest+extracted、bench/fixtures/xlat-traps.tex（@Xn）、网关 chat completions
- **输出**：`DIR/results.jsonl`（逐调用判定+prompt_sha）+ 报表
- **成本**：LLM 网关。**状态**：active——test_bench_regression.py:501 pin 其 S1–S4 形。

### qualbench.py（B4b）— ESA 协议质量评测

- **运行**：`uv run python bench/py/qualbench.py run --judge-model swe-2-max [--n N --papers 5 --per-paper 6 --source state|corpus|manifest --concurrency 4 --mock-judge --out DIR]`；另有 pairs/report
- **输入**：xlat state.json 树/corpus/qualsample sample.jsonl；judge 走网关 httpx
- **输出**：`DIR/{records.jsonl,report.md,run_meta.json}`
- **成本**：LLM 网关。**状态**：active——test_qualbench_esa + report/qualsample.py:54 引用。

### e2e_mock_bench.py（B5-A）— mock 全链 e2e + 破坏注入单源

- **运行**：`uv run python bench/py/e2e_mock_bench.py [--only SUBSTR --conditions base-xel,pipe-xel,... --corpus bench/corpus --layers core,hot --sample N --seed S --tag NAME]`
- **输入**：corpus manifest+extracted、产品链 texlate.e2e/pipecore、可选 TEXLATE_SRC 快照
- **输出**：`bench/results/e2emock-<tag>-<date>/{records.jsonl,results.json,matrix.md,summary.md}` + `bench/work_e2emock/`
- **成本**：LaTeX+重算力。**状态**：active——Mode B/C 注入实现被 translators_bench.py:60 继承；tests/test_sabotage_arms.py:25 pin。

### e2e_real_bench.py（B5-B/D）— 真网关 e2e（批量已让位 stagerun）

- **运行**：单篇冒烟 `uv run python bench/py/e2e_real_bench.py --ids 0707.1206`；批量 `--n 40 --seed 42 [--model ... --concurrency 10 --base onfail --fixloop onfail]`（env `TEXLATE_GATEWAY_KEY`）
- **输入**：corpus manifest+extracted、内部网关、fixloop_bench 配方、可选 TEXLATE_SRC 快照
- **输出**：`bench/results/e2e-real-<tag>-<date>/{records,results,matrix,summary,run_meta}` + `bench/work_e2ereal/` + `_xlat_state/`
- **成本**：LLM 网关+LaTeX+重算力。**状态**：active——demo.sh:63 用户演示调用；status_panel 追踪其进程。

### validbench.py（B6）— 校验器 bench

- **运行**：`uv run python bench/py/validbench.py [--corpus DIR --max-per-paper N --check --no-l1 --replay cases.jsonl]`（L1 需 bench/ts/node_modules）
- **输入**：corpus extracted 主 .tex（texlate.latex.parse_file）、可选 spike cases 回放、ts node 依赖
- **输出**：`OUT/{cases.jsonl,probes.jsonl,cells.json,summary.md}`
- **成本**：重算力。**状态**：active——记录门 1503 pairs 100%/0FP/0.374ms。

### alignbench.py（B7）— named-dest 锚点保留率

- **运行**：`uv run --with pypdf python bench/py/alignbench.py --pairs pairs.jsonl | --a-dir A --b-dir B | --selftest | --e2e-real WORK --records results.json [--check --rescue-en --corpus C --jobs N]`
- **输入**：en/zh PDF 对（B3/B5/e2e-real 产物树）+ run records；--rescue-en 需 corpus+xelatex
- **输出**：`OUT/{pairs.jsonl,cells.json,summary.md}`（+rescue.jsonl）
- **成本**：无（rescue 时 LaTeX）。**状态**：active——src/texlate/align.py 同源移植其 pairs/heights。

### gullet_bench.py — gullet 展开流专项探针

- **运行**：`uv run python bench/py/gullet_bench.py [--n 60 --seed N --out DIR]`
- **输入**：corpus manifest+extracted（locate+decode_tex）
- **输出**：`<out>/rows.jsonl` + 终端汇总（默认 bench/results/gullet-corpus-2026-09-15/）
- **成本**：重算力。**状态**：active——gullet 内部件（_tok_eq/ArgMismatch/process_if trig 签名）唯一消费契约。

### wrapfloat_bench.py — wrapfig 环绕碰撞检测

- **运行**：`uv run python bench/py/wrapfloat_bench.py [--corpus N]`
- **输入**：自造 fixture + corpus{,_daily} wrapfig 论文 + poppler pdftohtml/pdftotext + tectonic
- **输出**：`bench/results/wrapfloat-{date}/{cases.jsonl,corpus.json,summary.md,work/}`
- **成本**：LaTeX。**状态**：active——compile/layout.py:157 demote_wrapfloats 的验证台。

### benchlib.py — bench 共享库（~30 importers）

records jsonl 容错读写、原子写、safe_id/copytree_ignore、TUNA_TLNET pin、verdict_sig/judge_dict/fixloop_attr/fixloop_sig、层枚举。纯 stdlib，系统 python3 可载。**状态**：active——全体 stage__/stagerun_lib/triage/gate_scorecard/e2e__/各 bench + 3 test 文件引用。

## 翻译质量评估（B4b 下游 qual 家族 + 代理件）

### quality_proxies.py — S5 事后质量代理侧车

- **运行**：`uv run python bench/py/quality_proxies.py bench/results/<run> [--jobs 8 --limit N --ids ... --manifest PATH --out PATH]`
- **输入**：run 的 work/{id}/xlat-state/{arm}/state.json + compile 树（_.tex/_.bbl）+ records；terms/landmark 经 texlate.xlat.glossary/texlate.align
- **输出**：`<run>/quality-metrics.jsonl` 侧车（不动 records/）
- **状态**：active——被 stage_xlat.py:27/stage_compile.py:19 引用（TERM_ARMS+landmark 接线）。

### translators_bench.py — stagerun xlat 臂适配层

- **运行**：`uv run python bench/py/translators_bench.py`（self-check；本体是 stage_xlat 的 make_translator 库）
- **产出**：mock/sabotage-b/sabotage-c/perturb 臂工厂 + .ledger/.finalize 破坏台账（含 _replan 确定性回放）
- **状态**：active——stage_xlat.py:29 + test_sabotage_arms.py:24 引用。

### report/qualsample.py — 分层基线采样器

- **运行**：`uv run python bench/py/report/qualsample.py [--dry-run --seed S --papers N --chunks N --out DIR]`
- **输入**：stagerun-rt1/e2e_real 的 xlat state.json 池
- **输出**：sample.jsonl（para tertile+caption/section_title 配额）+ sample_meta.json
- **状态**：active——qualbench --source manifest 的指定上游（qualbench.py:45）。

### report/qualanchor.py — ESA^AI 人工评审包

- **运行**：`uv run python bench/py/report/qualanchor.py sample RECORDS.jsonl --fulltext sample.jsonl --n 200 --seed S --out DIR` / `harvest DIR`
- **输出**：盲审包（index.tsv/items/review/*.json/manifest.jsonl）→ harvest.jsonl
- **状态**：active——judge-vs-人校准链；anchor200 包已产出。

### report/qualfreeze.py — frozen-300 pinset + 漂移闸

- **运行**：`uv run python bench/py/report/qualfreeze.py freeze --records R --out F --sample S` / `check --baseline B --new N --frozen F --out gate_report.json`
- **输出**：frozen300.jsonl；check 四信号（KS/flag z/kind-mean Δ/contested Δ）exit 0/3/2
- **状态**：active——回归批硬闸，被 qualdrift 子进程调用。

### report/qualdrift.py — judge 漂移哨兵

- **运行**：`uv run python bench/py/report/qualdrift.py run --baseline <records.jsonl> --frozen <frozen300.jsonl> [--concurrency N --mock-judge]` / `history`
- **输出**：`bench/results/qualdrift-<date>/{run.log,gate_report}` + `qualdrift-history.jsonl` 趋势台账
- **成本**：LLM 网关。**状态**：active——每回归批前置哨兵（overseer-selfimp 09-18 规约）。

### report/qualstats.py — qual 统计臂

- **运行**：`uv run python bench/py/report/qualstats.py {ci DIR|pairacc A B [--key-mode]|report DIR}`（纯 stdlib）
- **输出**：ci.json/acc23 对 acc+CI/report.md
- **状态**：active——qualbase 基线 CI 与 qualanchor harvest 的指定消费者。

## 台账与诊断（bench/py/ + report/）

### triage.py — records 签名聚类→工单

- **运行**：`python3 bench/py/triage.py all DIR`（或 records|metrics|report DIR；--selftest；纯 stdlib+可选 pyyaml）
- **输出**：`DIR/{tickets.jsonl,tickets-legacy.jsonl,report.md}` + 全局 `bench/results/metrics.jsonl` 趋势
- **状态**：active——rundiff.py:28/report/dossier.py:54 import；3 test pin。

### rundiff.py — 双 run 逐格迁移比较

- **运行**：`python3 bench/py/rundiff.py DIR_A DIR_B [--stage compile --deep --json]`
- **状态**：active——test_bench_rundiff + wave.py postmortem 调用。

### gate_scorecard.py — M2 出门记分卡

- **运行**：`python3 bench/py/gate_scorecard.py [records_dir] [--json --require-frozen --write-window S --arm zh --upstream mock]`（违反冻结 exit 3）
- **状态**：active——3 test 文件 import + wave.py scorecard 子命令 + status_panel 聚合。

### gwpilot.py — 机会型批跑驱动 + serve 并发闸

- **运行**：`python3 bench/py/gwpilot.py run bench/queue/<q>.jsonl [--follow --max-load 8 --retry-failed]`；`serve [--port 3398]`；`status`；脱管 `setsid nohup ... &`
- **输入**：bench/queue/*.jsonl（{id,sh,env}）、GWPILOT_BG_KEY/bg.token、上游网关
- **输出**：`<q>.state.json`、`bench/work_gwpilot/logs/<q>/<id>.log`、`results/gwpilot/run.log`、X-Gate-* 遥测
- **成本**：LLM 网关。**状态**：active——spec 在 `bench/py/gwpilot.md`；无在跑进程但机制现役（09-18 fg/bg 落地）。

### report/defect_ledger.py — 缺陷底账

- **运行**：`python3 bench/py/report/defect_ledger.py --json|--md|--check|--write`
- **输入**：tmp/*-fuzz findings + roadmap inputs/defect-ledger.md + tests pin 扫描
- **输出**：stdout 报告；--write → tmp/defect-ledger/ledger.jsonl
- **状态**：active——runbook 波工具行；输入 lane 全在。

### report/dossier.py — 单 id 全链档案

- **运行**：`uv run python bench/py/report/dossier.py <id> [--run DIR|--diff DIR|--all-runs|--json]`
- **输入**：results/*/records+cases+work 树 + fixloop rules 分类 + cbucket vendor 清单
- **状态**：active——wave postmortem 的 dossier-join 子进程。

### report/mech_ids.py — 机制标签↔id 双向索引

- **运行**：`python3 bench/py/report/mech_ids.py <tags...>|--rule R|--coverage|--paper ID [--out F --validate --plus-random N --seed S]`
- **输出**：id 表/--out 喂 `wave.py run <ids-file>`；--coverage 覆盖+孤儿审计
- **状态**：active——ruleset.py:410 指定其 --validate 为机制覆盖官方口径。

### report/mech_backfill.py — manifest mech_tags 回填

- **运行**：`python3 bench/py/report/mech_backfill.py manifest.jsonl [--dry-run|--report out.json|--compute-missing-features F]`
- **状态**：active——manifest/提名/mechanisms 增长即重跑（daily soak 持续增量）。

### report/layout_bench.py — 版面损伤挖掘

- **运行**：`python3 bench/py/report/layout_bench.py {metrics|features|ink|report} ...`（stdlib+poppler）
- **输入**：work/{sid}/ 的 build-base+splice .log、src/*.tex、en/zh PDF 对
- **输出**：metrics/features/ink jsonl + report.md leaderboard
- **状态**：active——唯一版面损伤测量线；09-18 研究留有残余缺陷清单待复测。

### report/l2_attr_probe.py — L2 归因分布级探针

- **运行**：`uv run python bench/py/report/l2_attr_probe.py`（RESULTS_JSON 常量需重指到 archive）
- **输入**：e2e-real-n100 results.json + work_e2ereal trees +_xlat_state + corpus
- **输出**：`bench/results/l2-attr-probe-*/{probe.jsonl,cases.jsonl,summary.md}`
- **状态**：active——_l2_localize 唯一分布级验证件；e2e_real_bench.py:776 为其保契约。

### report/extract_l2_fixture.py — L2 log fixture 生成器

- **运行**：`uv run python bench/py/report/extract_l2_fixture.py SRC --name NAME [--strip-prefix P --no-cut --first-error-only --verify --manifest P --outdir D]`
- **输出**：tests/fixtures/logs/NAME.log + manifest.jsonl 行
- **状态**：active——入库 fixture 的指定生产线（9 logs+manifest 已交付）。

### report/export_realbook.py — 真书 EPUB 回归

- **运行**：`uv run python bench/py/report/export_realbook.py <epub...> [--outdir DIR]`
- **状态**：active——export/ 产品 lane 唯一 OCF 级真书回归件。

## 一次性横评（选型期已结案 → archive 候选）

以下六件 `bench/py/report/` 脚本由 `tools-runbook.md` 官宣「外部库横评（选型期已结案）」，运行依赖（pylatexenc/TexSoup/plasTeX/ieeA）已全部不在当前环境，产出已归档 `bench/archive-2026-09-20/results/`：

| 脚本                  | 运行                                                             | 结案依据                                   |
| --------------------- | ---------------------------------------------------------------- | ------------------------------------------ |
| `bench_pylatexenc.py` | `python3 bench/py/report/bench_pylatexenc.py {parse              | fixtures                                   | roundtrip | extract | damage | newcmd | all}` | PROTOCOL 四项横评；pylatexenc 不在任何 env |
| `ieeA_bench.py`       | `PYTHONPATH=tmp/refs/ieeA python3 bench/py/report/ieeA_bench.py` | 参考实现横评；ieeA 仅存 tmp/refs clone     |
| `plastex_bench.py`    | `python3 bench/py/report/plastex_bench.py`                       | plasTeX 横评+宏展开参考；dep 不在 env      |
| `texsoup_bench.py`    | `python3 bench/py/report/texsoup_bench.py`                       | TexSoup 四项横评；dep 不在 env             |
| `texsoup_diverge.py`  | `python3 bench/py/report/texsoup_diverge.py`                     | texsoup 发散点一次性分析；输入 json 已归档 |
| `v2_diff.py`          | `uv run python bench/py/report/v2_diff.py [--n N --seed S]`      | v1 scanner 已退役（474dfa91）→ diff 空转   |

另有 †`bench/py/scratch/`（encoding_probe、perf_tail×2）三件：已于 d39a1b23（09-18 release 清理）删除并 gitignore，留档。

## ICLR 章节长度研究管线（暂停至 10 月）

续跑手册：`research/corpus/2026-09-19-iclr章节长度.md`。六件套均 active（暂停态，2026-09-20 新提交 67996754）：

| 脚本                   | 运行                                                                                                 | 输入→输出                                         |
| ---------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `iclr_map.py`          | `uv run python bench/py/iclr_map.py [--phase oa                                                      | s2                                                | all --limit N]`（OPENALEX_API_KEY 在 paper-search skill .env） | accepted.jsonl→`work_iclr/map.jsonl`（orid→arxiv_id） |
| `iclr_fetch.py`        | `setsid nohup uv run python bench/py/iclr_fetch.py`（trial `--limit 30`）                            | map 行→`bench/corpus/{arxiv_id}/`+fetch.jsonl     |
| `iclr_pdf.py`          | `uv run python bench/py/iclr_pdf.py [--limit N]`（OPENREVIEW_USER/PASS）                             | 无 arxiv_id 行→`bench/corpus_iclr_pdf/{orid}.pdf` |
| `iclr_sections.py`     | `uv run python bench/py/iclr_sections.py --corpus bench/corpus --out bench/work_iclr/sections.jsonl` | LaTeX 臂章节分桶（17 canon buckets）              |
| `iclr_pdf_sections.py` | `uv run python bench/py/iclr_pdf_sections.py [--limit N]`（需 poppler）                              | PDF 臂分桶→sections_pdf.jsonl                     |
| `iclr_stats.py`        | `uv run python bench/py/iclr_stats.py [--md out.md]`                                                 | 双臂 join→stats.json 分布+校准比                  |

## JS 侧 bench（bench/ts/）

套件整体：选型期横评已结案但 2026-09-17 刻意加固（7b3e5b57）保留，`package.json` 的 node_modules 是产品 L1 校验器硬依赖（src/texlate/validate/l1.py 经 `TEXLATE_TS_NODE_PATH` 消费 + CI `npm ci --prefix bench/ts`）。**注意**：脚本内 CORPUS 指向统一后 ~14k 篇语料，重跑成本远高于选型期。

- **依赖**：`cd bench/ts && npm ci`（latex-utensils ^7、unified-latex-util-* ^1.8.4、tree-sitter ^0.25.1、@pfoerster/tree-sitter-latex ^0.6.0）
- `bench-lu.js`：`node bench-lu.js` → latex-utensils 四项横评 → `results/latex-utensils-{parse,traps,roundtrip,leak}.json`
- `bench-tsl.js`：`node bench-tsl.js` → tree-sitter-latex ERROR/MISSING/陷阱/校验器评估 → `results/tree-sitter-latex-*.json`
- `ul_corpus.js`：`node ul_corpus.js` → unified-latex worker_threads 全语料+round-trip+leak → `results/unified-latex-*.json`
- `ul_tricky.js`：`node ul_tricky.js` → unified-latex @Tnn 断言 → `results/unified-latex-tricky.json`
- 共享件：`common.js`（路径/@Tnn 提取）、`ul_common.js`（AST walk/translatable-blocks）、`ul_worker.js`（worker）

## 资产、产物与工作区

| 项                                            | 说明                                                                                                                                 | 状态                                                                                                                                 |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| `bench/fixtures/`                             | 陷阱 .tex 语料 92K（tricky*@Tnn/xlat-traps），字节即语义                                                                             | **保护区**·asset                                                                                                                     |
| `bench/PROTOCOL.md`                           | per-库评测协议（四项横评+报告格式）                                                                                                  | **已删** 2026-09-20（选型期协议退役，原文见 git 历史）                                                                               |
| `bench/TIERS.md`                              | L0–L3 验证分层契约                                                                                                                   | 治理·keep                                                                                                                            |
| `bench/RETENTION.md`                          | results/ 留存契约（归零后存活口径+删除谓词）                                                                                         | **已删** Wave-F——results/ 清零后契约失效                                                                                             |
| `bench/results/`（全部）                      | 09-20 归零后存活 run 目录（soak-09-18 / stagerun-overnite-09-20 / zhstore-verify-09-20 / stagerun-smk-unified-09-19 / status-panel） | **已删** Wave-F——89M 账本树已入 `$TEXLATE_BENCH_ROOT/backup/phase0-20260922`；看板状态改落 `$TEXLATE_BENCH_ROOT/state/status-panel/` |
| `bench/work_daily`                            | daily-soak 工作区（lock+log）                                                                                                        | **已删** 2026-09-21——daily-soak 链路退役（timer 拆除、脚本与 daily_arxiv.py 已删）                                                   |
| `bench/work_*`（e2ereal/gwpilot/iclr/m1k/v3） | 各管线工作区                                                                                                                         | **已删** Wave-F——spec 工作区在 run 目录内；work_iclr 早前已删（续跑重导见 `research/corpus/2026-09-19-iclr章节长度.md`）             |
| `bench/py/.venv_babeldoc`                     | babeldoc 对照 venv 664M——macOS 原生件，bin/python 在 Linux 悬空                                                                      | 现 absent·机制位（09-20 清理已删；如需重建 `uv venv bench/py/.venv_babeldoc --python 3.12 && uv pip install babeldoc`）              |
| †`bench/py/.venv`                             | 54M macOS 原生横评 venv（无 bin/python，彻底 broken）                                                                                | **已删**                                                                                                                             |
