# corpus_v3 全量综合测试指标总表（2026-09-19）

> **结论**：corpus_v3 8 层 13,266 篇全量综合测试——解析臂全绿（parse ok 100.0%、strict identity 99.99%、leak 0.004%），编译基线 union pdf 90.4%，zh 注入臂反超 baseline +16pt（normalize 修复源缺陷），e2e_real 零管线引入回归，stagerun 全 DAG union-pdf 98.75% / clean 88.75%（M2 ≥90% 门样本口径 PASS）。gate FAIL 仅两处（均在 parsebench）：dead protect ph=3（门=0）与 flatten 93.7%<99%（已知 errata）。
> **状态**：时点证据（2026-09-19 口径）。各臂结果目录在主仓评测产物存档区（`bench/results/` 轮次目录），本表为读数汇总。
> **日期**：2026-09-19（2026-09-20 迁入重编）

语料：corpus_v3 8 层 / 13,266 篇 / 46GB。完整性审计全绿：sha256 13,266/13,266、0 重复 id、0 缺 cell/meta/raw、13 个 stub cell 为 B07 边界形态有意构造、`dev_layers()` 实测排除 holdout（EVAL_ONLY 治理生效）。

网关面：内部 OpenAI 兼容网关批量档（翻译臂中等模型；judge 强模型 + 二裁弱一档），全程无 401/403，批量队列 ~120s in-gate 排队在 p95 延迟可见。

## 逐臂指标

| 臂 | 规模 | 核心指标 | 门槛对比 |
| --- | --- | --- | --- |
| 完整性审计 | 13,266 cells | sha256 13,266/13,266 · 0 dup · 0 missing | — |
| parsebench (B1) | 13,253 篇 / 28,904 .tex / 1,647.8s | parse ok 100.0%(1 err) · strict identity 99.99%(28,899 strict/3 norm/1 diverged) · leak 0.004%(76/1,845,338) · expand footprint strict 28,105/norm 259/diverged 539 · flatten 93.7% | identity ≥99.5% PASS · leak ≤0.15% PASS · dead protect ph=3 FAIL（门=0）· flatten 93.7%<99% FAIL（已知 errata） |
| compilebench baseline (B3) | 500 格 ×2 引擎 | xelatex 56.3% clean / 80.3% pdf · tectonic 38.6% / 62.4% · 联合 pdf 90.4% | — |
| compilebench zh-arm | 500 格 | xelatex 72.4% clean / 85.4% pdf（+16pt vs baseline，normalize 修复源缺陷）· tectonic 45.7% / 59.8% | — |
| fixloop (corpus_v2 40) | 80 格 | xelatex 34 FAIL→25 救回 74% · tectonic 1/16（eps_route reject 主导）· union pdf 26→32/40 | — |
| alignbench (B7) | 812 对 | 门全过；但 765/812 对 named-dests=0，真实覆盖仅 42 个 hyperref 对（retention p50 1.0） | 覆盖不足，指标口径需复核 |
| e2e_mock (B5) | corpus39 | pipe-xel 33/39 clean vs base-xel 19/39（管线净正）· 引入回归 1+2 | — |
| e2e_real (B5) | n=24 + n=60 | n=60：58/58 翻译 · chunk ok 6,053/7,580（partial 43/fault 8）· splice 残留 0 PASS · pipe-xel clean 43/fail 7/partial 6 · fixloop 再救 13 格 · 0 管线引入回归 | — |
| xlatbench (B4) | 271 样本 | hard_ok 94% · http_err 0 · 延迟 p50 4.2s / p95 29.7s（批量队列可见） | — |
| qualbench (B4b) | 324 篇 / 1,937 chunk | judge 强模型：mean 94.0 / median 95，≥90 占 90.6% · contested 5.5%(106) · critical 仅 1（non-translation） | — |
| gullet | 200 文档 | 199/200 展开成功 · median 39.6ms / 19 steps · 1 locate/decode 边界错 | — |
| stagerun 全 DAG | 80 篇跨层 | ingest 80 → parse 79 ok → xlat 76 ok+3 partial → compile zh 50 clean/19 partial/10 fail → fixloop 21 格全救回（13 clean+8 partial）· union pdf 79/80=98.75% · clean 71/80=88.75% | M2 union-pdf ≥90% PASS（样本口径） |

## 失败类分布（归因要点）

- e2e_real n=60 编译失败类：missing_file×7、missing_graphic×3、killed_by_signal×3、driver_fatal×3——语料源缺资产为主，非管线引入。
- xlatbench 失败类：cs_dropped 居首，comment_eof、ph_miss 次之；ord_soft 78。
- qualbench flag 榜：term_inconsistency 229、grammar 197、mistranslation 132、fluency_register 99、hallucinated_content 66；per-kind section_title 96.9 > caption 93.2 > para 92.2。
- fixloop tectonic 臂死穴：eps_route reject（EPS 图源 tectonic 无解，xelatex 是唯一出路）；与 tectonic↔biber 版本错配同属 tectonic 短板。

## 已知缺口 / 跟进项

1. dead protect ph=3——parsebench 唯一非 errata gate FAIL，值小但门为 0，需归因。
2. flatten 93.7% < 99%——已知 errata，orphan tex 清单在 papers.json。
3. alignbench 覆盖薄——多数产物无 named-dests，保留率实际只在 42 对上有意义。
4. xlat cs_dropped——翻译臂头号失败类，待归因是 prompt 侧还是网关侧丢 cs。
5. stagerun scorecard 口径——records 混存首轮欠采的 989 条 stale skip 行，原始读数 7.4% 失真；按 ingest 样本口径重算为 98.75%。工具层可加 `--since` 或按样本集过滤。
6. 未测臂：translators_bench、validbench (B6)、nightwatch、rundiff、triage、stage_timing、wave、status_panel（多为监控/辅助工具，本轮未覆盖）。

## 过程教训（工具层）

manifest.parent 必须等于语料根（xlatbench）、`--per-kind` 是全局限额、pgrep 自匹配须用 `[x]pattern` 括号形、compilebench `--gen-sample` 分段设计、e2e 同 `--tag` 冻结样本须换 tag/seed、gullet `--out` 续跑会留 stale err 行须换新目录、stagerun 下游阶段须传 `--ids` 防跨层欠采、共享 index commit 须私有 `GIT_INDEX_FILE`。
