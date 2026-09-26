# HANDOFF-2026-09-16 数字核验证据（audit-m0 数据核实维度）

> **结论**：交接数字全账复核：HANDOFF 声明值与 bench/results 实物逐项对上，仅 3 处口径注记。
> **状态**：时点证据（2026-09-16 口径）
> **日期**：2026-09-16（2026-09-20 迁入重编）
>
> 方法：直接开 `bench/results/` 下 json/jsonl 重算，不抄 summary 文本。
> verdict = MATCH / MATCH*（口径注记）/ MISMATCH / NOT_FOUND。

## §3.1 终码 — parsebench-v2prod-final-2026-09-15（files.jsonl n=1955）

| 声明                                  | 实测（原始字段）                                                                 | verdict              |
| ------------------------------------- | -------------------------------------------------------------------------------- | -------------------- |
| identity strict 1955/1955 对 res.vtex | `Σ v2.identity`: strict 1955 / normalized 0 / diverged 0                         | MATCH                |
| leak 0.046% 持平 v1                   | `Σ v2.leak.n_leaked=58 / Σ n_translatable=124772` = 0.0465%；v1 57/135170=0.042% | MATCH                |
| unresolved 111                        | `Σ len(v2.unresolved_inputs)=111`（35 文件非零；v1 同为 111）                    | MATCH                |
| dead_ph 0                             | `v2.warn_kinds` 无 dead_ph 键；`v2.fake` residue_chunk_ph/protect/orphan 全 0    | MATCH                |
| pytest 1090 passed / 16 skipped       | 本机复跑 `uv run pytest tests/ -q`：1090 passed, 16 skipped, 30.98s              | MATCH                |
| 85 文件 >500ms，max 8.4s；v1 max 4.7s | `v2.wall_ms`>500 计 85，max 8393.2ms；v1 max 4703.3ms                            | MATCH                |
| e2e_mock 冒烟干净                     | e2emock-v2prod-smoke results.json：leftover_ph=0、fault=0（2 篇小冒烟）          | MATCH*（n=2 仅冒烟） |

注：prod-final `v2.vtex_vs_src` = strict 1906 / normalized 17 / diverged 32——交接只声称
identity 对 res.vtex strict，未声称 vtex_vs_src 全 strict，不冲突但值得知悉（F12 墓标
拉取使 vtex 与 src 足迹分离）。s3c/s4 两跑 vtex_vs_src 才是全 strict 1955。
prod-final `v2.warn_kinds.def_parse_fail=14`（交接未对终码声称此数）。

## §2.1 S3 验收 — parsebench-v2full-s3c-2026-09-15（files.jsonl n=1955）

| 声明                                                  | 实测                                                                              | verdict |
| ----------------------------------------------------- | --------------------------------------------------------------------------------- | ------- |
| v2 identity strict 1955/0/0；vtex_vs_src strict 1955  | 两字段 Counter 均 strict×1955                                                     | MATCH   |
| dead_ph 18345→0                                       | 基线 parsebench-v2full1955-2026-09-16 `v2.warn_kinds.dead_ph=18345`；s3c 无此键=0 | MATCH   |
| orphan chunks 0                                       | `v2.fake.n_orphan_chunks` Σ=0                                                     | MATCH   |
| v2 leak 90 = dollar 61 + conditional 27 + begin_env 2 | `Σ n_leaked=90`，hits={'dollar':61,'conditional':27,'begin_env':2}                | MATCH   |
| v1 同族 leak 57                                       | v1 leak 57/135170（summary）                                                      | MATCH   |
| 性能 v2 p50 35 / p95 285（v1 7/202）                  | nearest-rank 重算：v2 35.4/285.2，v1 7.0/202.1                                    | MATCH   |
| v2 def_parse_fail 15 vs v1 293                        | `v2.warn_kinds.def_parse_fail=15`；v1 warn_kinds=293                              | MATCH   |

## 性能（审计口径对应 s4 跑）— parsebench-v2full-s4-2026-09-15

| 声明                                | 实测                                      | verdict |
| ----------------------------------- | ----------------------------------------- | ------- |
| v2 p50 36ms / p95 292ms vs v1 7/202 | nearest-rank：v2 35.9/292.5；v1 7.1/202.3 | MATCH   |

s4 旁证：`v2.leak` hits={dollar:61, begin_env:2}（conditional 27 已被 S4 收掉，
63=61+2 与"界标档"叙事一致）；v2 unresolved_inputs=0。

## §2.3 e2e — e2e-real-n100-2026-09-15/results.json（100 篇，91 执行）

| 声明                          | 实测                                                                                                                                    | verdict |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| chunk ok 10715/10718 = 99.97% | `Σ translate.ok=10715 / Σ chunks=10718`（partial 3、fault 0、skipped 0）                                                                | MATCH   |
| splice 残留 1524 / 7 篇       | `Σ leftover_ph=1524`；2403.15096(572) 2403.15118(236) 1608.02516(212) 2105.03750(205) 1206.5602(204) 2308.12712(53) physics/9703012(42) | MATCH   |
| 复验全归零                    | e2e-verify-residue-2026-09-16/results.json：7 篇 leftover_ph 全 0（chunk ok 1225/1226）                                                 | MATCH   |
| pipe-xel clean 28/91          | verdict.status=clean ×28（fail 44、partial 19，共 91）                                                                                  | MATCH   |

## §2.2 compilebench-v4 + fixloop 臂（cells.json 逐格重算）

| 声明                                  | 实测                                                                                                                                     | verdict |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| 联合 pdf 127/172→154/172（89.5%）     | baseline union pdf=127（180 样本）；fixloop pdf 层 verdict（clean/acceptable/best_effort/dirty）union=154/172=89.53%；折算 154/180=85.6% | MATCH*  |
| xel missing_file 109 FAIL→84 pdf      | baseline xel verdict=FAIL∧cat=missing_file 计 109 格，其中 `final_pdf`=84                                                                | MATCH   |
| tlmgr 89 格真装包                     | 109 格中 `installed` 非空=89 格（全类别口径则为 101 格/183 文件）                                                                        | MATCH*  |
| eps_image 45→37 pdf                   | tec baseline FAIL∧eps_image=45，`final_pdf`=37                                                                                           | MATCH   |
| documentstyle 假阳性 3 篇双引擎 clean | latex209_suspect 13 篇中双 clean：cond-mat/9703223、hep-ph/9703402、hep-th/9703099                                                       | MATCH   |
| baseline 臂仅 1 格判定更正迁移        | v3↔v4 join 180 篇：唯一 verdict 迁移=1404.5668 xel clean→pdf~（killed_signal）；另 6 格→no_main_tex（mask_tex bug 3 篇×2 引擎）          | MATCH   |

*口径注记 A：fixloop `final_pdf` union 实为 159——5 格 tec `reject:latex209_reject`
（astro-ph/9910044、cond-mat/9910214、hep-ph/9910373、hep-th/9703173、nucl-th/0111058）
留有残 pdf。154 按 verdict 层（gate 拒不算救回）计，与 summary-diff-v3 §3"回归 7 格"
叙事自洽；按字面 pdf 产物计则为 159/172=92.4%。
*口径注记 B：compilebench-v4 summary.md §4 表 xel missing_file 格数写 110（含 1 格
pdf~），§7 与交接用 109（仅 FAIL）——同一文档内 110/109 并见，FAIL 口径 109 正确。

## §2.2 fixloop-v3-missing-file-r2-2026-09-16（cells.json 111 篇）

| 声明                                       | 实测                                                                                                          | verdict |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------- | ------- |
| missing_file 111 篇子集 union pdf 1→85/111 | baseline pdf 层 1/111 → fixloop union `final_pdf`=85/111；xel `installed` 非空 90 格（与 diff-v3"90 装"一致） | MATCH   |

## §2.2 mask_tex overshoot 修复 — 涉事 3 篇

| 声明                                                             | 实测                                                                                                            | verdict |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ------- |
| 3 篇（2003.03510、1608.06693、quant-ph/0111094）抽查 strict 全过 | prod-final files.jsonl：2003.03510 strict、1608.06693 strict、quant-ph/0111094 两文件 strict（v1+v2 均 strict） | MATCH*  |

*parsebench-maskfix-probe-2026-09-15 目录本身只含 2 篇（quant-ph/0111094 +
astro-ph/0111094，3 文件全 strict）——命名探针只覆盖 3 篇中的 1 篇，另 2 篇证据在
prod-final 全量跑内。

## 结论

声明数字全部 MATCH，无 MISMATCH/NOT_FOUND。三处口径注记（fixloop union pdf
159 vs 154、"89 格真装包"为 missing_file 子集口径、maskfix 探针只覆盖 1/3 篇）
不改变声明正确性，但读者按字面 `final_pdf` 重算会得到 159。
