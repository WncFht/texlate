# 评测协议与分层契约

本仓的评测体系由 `bench/TIERS.md`（一个问题该在哪一层被抓）与 `docs/spec/benchmark.md`（B1–B7 评测器规格）定义；外部库选型期的逐库横评协议 `bench/PROTOCOL.md` 已于 2026-09-20 退役删除（原文见 git 历史）。本文把现行契约重整为公开口径：先讲四层验证契约，再讲语料与陷阱夹具的底材纪律，最后是 bench 产物落盘的工具链关系。各 spec/动词的逐件清单见 `dev/tools-runbook.md` §3。

> **2026-09-23 Wave-F 注记**：trizone-ledger v2 迁移收口，旧 harness（stagerun/stage__/各评测器脚本/triage/rundiff/gate_scorecard/benchlib/corpus build__/report/）全部删除，继任面 = `bench/py/specs/*.py`（`uv run python bench/py/bench run <spec>` 跑批）+ `bench/py/verbs/*.py`（`bench <verb>` 分析）+ `bench/py/kernel/`（账本与调度）。run 产物不再落仓内——`$TEXLATE_BENCH_ROOT/runs/<kind>/<date>/<slug>/`（仓外账本根，git 天然不碰）。

## 1. 分层契约：什么问题在哪级验证

核心原则一句话：修复不算完，直到它能看见的最便宜那层被钉住；更高层只接低层结构性看不见的东西。

| 层           | 入口                                                                                                                              | 底材                                                                           | 量级                     | 时机                                  |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------ | ------------------------------------- |
| L0 单元/断言 | `uv run pytest tests/`（含 fixture 断言矩阵；契约产出走 `bench run fixture_assert`）                                              | 合成输入 + `bench/fixtures/*.tex`（@Tnn/@Wnn/@Xn，逐字节即语义）               | 秒级/单文件，分钟级/全套 | 每 commit、CI 硬门                    |
| L1 机制覆盖  | `uv run python bench/py/bench run parsebench`                                                                                     | `bench/corpus/` 统一物理根（v1 手挑陷阱 + v2 渠道敏感 + 分层全量各层）         | 分钟级                   | 解析/扫描/归一化改动后，开批前        |
| L2 子集回归  | `uv run python bench/py/bench run soak ids=<csv>` 或 `n=<N> seed=<S>` 类参数定点子集                                              | corpus `mechanisms.jsonl` 机制台账 + 分层 manifest                             | 分钟–小时                | 管线 stage 改动、新机制落账后定向重放 |
| L3 全量集成  | `bench run` 全层 spec 套（soak/e2e_mock/e2e_real 等）→ `bench gate` + `bench triage`（估时口径 `bench plan <spec>` 逐 spec 报价） | corpus 全层（core/booster/expand/hot/dev_*/holdout，规模以 manifest 实数为准） | 过夜级                   | 里程碑门、发版前                      |

问题类型到层级的首选映射：

| 问题类型                                 | 首选层       | 说明                                                                               |
| ---------------------------------------- | ------------ | ---------------------------------------------------------------------------------- |
| 纯函数/codec/mask/正则/边界逻辑          | L0           | 合成输入当场钉                                                                     |
| 日志判定（分类/红线/verdict）            | L0 + L3      | 合成 log 钉语义；真 `-file-line-error` log 只有 L3 生产面见得到                    |
| 解析机制（新坑/回归坑）                  | L0 → L1 → L2 | 最小复现 fixture 化登记 @Tnn；L1 确认分布面；`mechanisms.jsonl` 落账后 L2 定向重放 |
| 翻译臂/台账契约（mock/sabotage/perturb） | L0 + L2      | 台账谓词单测钉口径；臂行为用 L2 子集跑真 records                                   |
| 编译/fixloop 规则触发                    | L0 + L2/L3   | 合成 log 钉判定；救回率/规则谱只在批量上有意义                                     |
| 逃逸面/对抗闸（sabotage/gate 红线）      | L2 + L3      | sabotage 臂分钟级台账；`escaped>0` 是 L3 硬门                                      |
| resume/StateStore/跨进程状态             | L2           | index 落账 + `(idc,arm,variant)` dedup/resume 语义跨运行才成立，L0 测不到          |
| 性能/规模/并发/资源闸                    | L3           | 低层无代表性负载                                                                   |
| 接口漂移（harness↔产品）                 | L0 + L2      | 绑定/spy 钉接线；真跑是 L2 起                                                      |

四条规则。其一「能低不高」：L0 能钉的（合成输入可复现）不许只在 L2/L3 靠批量撞见——批量发现的每个真坑都要沉淀回 L0 断言或 fixture。其二「逐层语义」：每层绿只证明该层契约成立，不证明下层问题不存在（L0 全绿 ≠ 分布面无漂；L3 闸过 ≠ 单点逻辑无残余）。其三「跨层不重复」：同一断言不重复钉在两层——高层存在的理由是低层看不见（规模/真料/跨进程），看得见的归低层。其四「量级兑现」：估时以 `bench plan <spec>` 的逐 spec 报价（plan.json 冻结格数 + dedup 桶）为准；层级归属争议按「cheapest tier that can see it」裁决。

## 2. 评测协议：每个库/管线测什么

这套四项评测最初用于外部 LaTeX 解析库选型（pylatexenc/TexSoup/plasTeX/latex-utensils/unified-latex/tree-sitter-latex 等，选型期已结案，横评脚本已随 Wave-F 删除、`bench/ts/` 保留）；同一框架现在是 `texlate.latex` 产品管线的正式评测口径，由 `bench/py/specs/parsebench.py` 承载。

### 2.1 解析鲁棒性（corpus 全部 .tex）

逐文件记录成功/失败（异常类型）/耗时，30s 超时。产出落 `$TEXLATE_BENCH_ROOT/runs/parsebench/<date>/<slug>/`：records 经 index 可查，报表类产物在 `derived/`。

### 2.2 陷阱断言（fixtures）

逐条检查分类是否符合「段落级提取 + 保护 + 重建」管线的期望：`% @Tnn` 标记的每个构造都要么整体保护（数学/引用 key/verbatim/宏定义绝不进可译块）、要么内部文本可译（caption/footnote/item/长标题/强调文本）、要么展平（`\input`/`\include`，注释掉的不展开）、要么不崩（`\ifdraft`、`\bibliography`、`\makeatletter` 区）。断言矩阵随产品解析器演进，以 `tests/test_bench_regression.py` 与 `bench/py/specs/fixture_assert.py` 为准。

### 2.3 Round-trip 保真（corpus 主文件）

parse→serialize→与原文对比：identical / normalized（仅空白差异）/ diverged（报告差异位置和大小）。只测声称支持序列化的库；产品管线的对应口径是 vtex 重建逐字节对比。

### 2.4 泄漏率（corpus 全部文件）

提取可译段落块后，统计块内含 `$`、`\cite`、`\ref`、`\begin{` 等数学/保护标记的块比例 = 泄漏率，越低越好。产品口径把泄漏正则扩到六组（`$`、`\cite`、`\ref`、`\begin{`、`\if`、`\input`），实测量级见主仓审计报告。

## 3. 底材纪律

### 3.1 `bench/fixtures/` — 逐字节即语义

fixtures 是陷阱构造语料：`tricky.tex`（@Tnn 主集）、`tricky-209.tex`（LaTeX 2.09 旧格式）、`tricky-multi/` 与 `tricky-w73/`（`\input` 多文件与路径逃逸）、`tricky-w.tex`/`tricky-wenc.tex`/`tricky-dollar.tex`/`tricky-mask.tex`（野外机制与编码/遮蔽陷阱）、`xlat-traps.tex`（翻译层 @Xn）、`escape-outside.tex`（根外逃逸目标件）。每个陷阱由 `% @Tnn`/`% @Wnn`/`% @Xn` 注释标记定位。

**字节即语义**：这些文件的每一个字节都是测试输入——空白、注释位置、未配平括号都是构造的一部分。任何格式化、润色、自动修复都会改变语义，所以 `*.tex` 整体不进格式化工具链，也不许顺手「修正」fixture 内容。新陷阱从野外发现生长：found-in-wild → 断言覆盖 → fixture 化登记（@Wnn 系列就是这条生长线的产物）。

### 3.2 `bench/corpus/` — 统一语料物理根

全部钉版语料在一个物理根下按层组织，层名归 manifest 管：`manifest.jsonl`（core 均匀层）+ `manifest_booster.jsonl`（补强）+ `manifest_expand.jsonl`（扩库增量）+ `manifest_hot.jsonl`（高引近期）+ `manifest_dev_*.jsonl`（修复训练层）+ `manifest_holdout.jsonl`（留出评测层，EVAL_ONLY 治理——dev 枚举不碰它，防 dev==eval 污染）+ `mechanisms.jsonl`（机制台账，L2 定向重放的依据）。层规模随扩库续增，口径以 `bench/corpus/MANIFEST.md` 与各 manifest 实数为准。语料数据 gitignored；构建管线是 `bench/py/specs/corpus_*.py` 谱系（`bench run corpus_v3` / `corpus_layers` / `corpus_sw` 等）。

历史旁根：`bench/corpus_daily/`（日更 soak 滚动窗口）已于 2026-09-21 退役删除（timer/脚本/语料全清）；`bench/corpus_iclr_pdf/`（ICLR PDF 产物，非 e-print 树）仍在。

### 3.3 run 产物面 — 仓外账本根

旧 `bench/results/` 目录已随 Wave-F 删除：run 产物整体迁出仓库，落 `$TEXLATE_BENCH_ROOT/runs/<kind>/<date>/<slug>/`（`runs/` 元格 + `derived/` 报表），索引是账本根下的 sqlite（`bench status` / `bench doctor` 可直查）。仓内不再有「重跑即覆盖」的产出目录需要工具链豁免；gitignored 数据面全部出仓——语料载荷在 `lake/corpus/`、不可再生真译与成品在 `vault/`（继任旧 `bench/zh-store/`）。

## 4. 产出契约与记账

批跑侧的统一契约：每格一行 append 进 run 目录 `records/<stage>.jsonl` 并同步入 index——行落账即 done，崩了同参重启按 `(idc, arm, variant)` 键 dedup/resume 续跑；上游缺口以 needs/needs-skip 标注进账本。分析侧动词：`bench triage`（records 聚成签名待修榜 + 趋势）、`bench rundiff`（两次 run 逐格迁移矩阵）、`bench gate`（出口门记分卡）、`bench dossier`（单格/单 id 全剖面）、`bench xlat-report`/`xlat-rejudge`/`qual-report`/`booster-select`（翻译/质量臂报表与重判）。估时与格数预报走 `bench plan <spec>`；具体参数在各 spec/verb 文件头 docstring。
