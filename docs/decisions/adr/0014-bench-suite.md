# ADR-0014 评测套件：B1–B7 评测器矩阵 + L0–L3 分层契约 + mock/real 双臂

> **状态**：现行
> **日期**：2026-09-15（bench 协议与评测器矩阵定案）| 更新 2026-09-19（real 臂改滚动探针）

## 上下文

「干净翻译率」不能靠手感：需要可复算的评测器矩阵（每个评测器测什么、用什么料）、分层验证契约（一个问题该在哪层被抓——修复不算完，直到它能看见的最便宜那层被钉住）、以及不烧 token 的回归手段。外部库选型期的逐库 bench 与产品管线的持续评测是两套东西，要分开。

## 裁决

- **评测器矩阵 B1–B7**（规格主仓 `docs/10`，编号档撤编后继 `docs/spec/benchmark.md`——两边 B 编号口径不同，以 spec 现行表为准）：B1 parsebench v2 = `texlate.latex` 产品管线正式评测器（identity/leak 双指标，产出三件套）；B2 fixture 断言矩阵（`bench/fixtures/*.tex` 逐字节即语义，`@Tnn`/`@Wnn`/`@Xn` 陷阱标记，found-in-wild→covered→fixture 生长）；B3 批量 stagerun（records/{stage}.jsonl append + resume）；B4 sabotage 对抗臂（逃逸面，`escaped>0` 是硬门）；B5 编译/fixloop 批量；B6 覆盖簿记（`eval_coverage.json`）；B7 e2e 集成。
- **分层契约 L0–L3**（`bench/TIERS.md`）：L0 单元/断言（pytest + fixture，秒级，CI 硬门）→ L1 机制覆盖（parsebench 全语料，分钟级）→ L2 子集回归（stagerun 分层 + mechanisms.jsonl 定向重放）→ L3 全量集成（全层全臂 + scorecard + triage，过夜间量级）。四规则：能低不高、逐层语义（高层绿不证明下层无问题）、跨层不重复、量级兑现。
- **mock/real 双臂**：`xlat/mock.py` MockTranslator 确定性占位译文使全链无 token 回归；real 臂打网关真模型。n=200 对照实证 mock≈real（判分一致率 98.5%）→ **裁决 mock 全量跑、real 改滚动分层探针**（每波 200–300 格优先打 hot/expand 缺口），省 token 又保真负载校准。
- **scorecard 判分**：`gate_scorecard.py` 聚合 records → union pdf/clean/fail 三口径；clean 判定三件套（编译过 + 红线零逃逸 + CJK 真在 PDF 里）；`triage.py` 出操作单。
- **harness 纪律**：bench 底材原样不改写；records/ids 混存 raw 与 canon 两形 id，一切匹配双侧归一；`bench/results/` 是脚本重写区（格式化链全划出）。

## 理由

- 「能低不高」：L0 能钉的不许只在 L2/L3 靠批量撞见——批量发现的每个真坑沉淀回 L0 断言或 fixture，规则库厚度才单调增长。
- mock≈real 98.5% 一致率意味着评测口径与模型无关层（解析/拼接/编译/fixloop）可用零成本臂全量覆盖；real 臂只须回答「模型面有没有漂」。
- 证据：主仓 `bench/PROTOCOL.md`（2026-09-20 退役删除，原文见 git 历史）、`bench/TIERS.md`、`docs/10`（编号档撤编后继 `docs/spec/benchmark.md`）；调研档案 `research/methods/2026-09-19-bench-metrics-corpusv3.md`、`research/methods/bench-construction-methods.md`。

## 演变

- 2026-09-15：M0 后 parsebench v2 转正为产品管线评测器；选型期逐库对比层（pylatexenc/TexSoup/plasTeX/latex-utensils/unified-latex/tree-sitter）退役为一次性资产，断言矩阵移植 `tests/test_bench_regression.py`。
- 2026-09-19：real 臂降档滚动探针（promo 死线与 mock 平价实证双重驱动）；同日全量基线定格——scorecard 5124 格 union pdf 97.89%、clean 84.99%（2026-09-18 口径）。
- corpus 载体演进见 ADR-0013；语料根合一后 L1–L3 均指向统一物理根。
- 2026-09-23（Wave-F/trizone-ledger v2）：旧 harness 全删（stagerun/逐评测器脚本/gate_scorecard/triage/rundiff/benchlib/runbook_loop/preflight_batch）；继任面 = `bench/py/specs/*.py`（`bench run <spec>` 起批）+ `bench/py/verbs/*.py`（`bench <verb>` 分析）+ `bench/py/kernel/`（账本与调度）；run 产物落仓外 `$TEXLATE_BENCH_ROOT/runs/`。

## 现状

实现落位：评测器 = `bench/py/specs/`——`parsebench`（B1）、`fixture_assert`（B2 契约产出）、`compilebench`/`fixloop_bench`（B5）、`xlatbench`/`qualbench`/`e2e_mock`/`e2e_real`/`soak` 等批量与子集入口（B3 stagerun 语义由 kernel run + index records 承接，sabotage 对抗臂单源 `specs/_sabotage.py` 经 e2e_mock 承载）；L3 收口 = `bench gate`（gate_scorecard 继任）+ `bench triage`；估时报价 `bench plan <spec>`（runbook_loop.md 继任）；批前闸 = `bench run` 内建 spec preflight + paid `--max-cost` 闸（preflight_batch 继任）。`tests/test_bench_regression.py` fixture 断言矩阵（72 条 dict 断言 / 133 pytest 用例）是 L0 硬门。最新定格指标：identity 100% / leak 0.040%（parsebench，3937 文件时点）、union pdf 97.89% / clean 84.99%（scorecard 基线，5124 格，2026-09-18 口径）。
