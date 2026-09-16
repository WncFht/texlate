# fixloop 回放基线 — n100 cases × 当前 rules.yaml

- 日期: 2026-09-16 13:43
- cases 源: `bench/results/e2e-real-n100-postcutover-2026-09-16/cases.jsonl` (40 格, cond=pipe-fix, xelatex)
- src 快照: `tmp/exp/src-snapshot-replay` (rules.yaml sha256 见 run_meta)
- 口径: pipe-xel 前置态拷贝 + 每格冷 usertree + tlpdb 索引 + TUNA (复刻 e2e pipe_fix_condition)
- 回放墙钟: 185s, jobs=4

## 三门总览

- 门① 救回 (started_fail=18): **12/18** 出 pdf
- 门② 回归 (曾 clean/acceptable=23): **0 格被改脏**
- 全格回放后出 pdf: 34/40
- API 交叉校验 (replay_all ReplayResult vs 重建行): live 40 格, 0 处不一致 

## verdict 迁移矩阵 (before → after)

| before \ after | acceptable_pdf | best_effort_pdf | clean | unfixable:latex209 | unfixable:missing_file | unfixable:other |
|---|---|---|---|---|---|---|
| acceptable_pdf | 3 | 0 | 1 | 0 | 0 | 0 |
| best_effort_pdf | 0 | 4 | 0 | 0 | 0 | 0 |
| clean | 1 | 0 | 18 | 0 | 0 | 0 |
| unfixable:latex209 | 0 | 0 | 0 | 3 | 0 | 0 |
| unfixable:missing_file | 4 | 1 | 2 | 0 | 1 | 0 |
| unfixable:other | 0 | 0 | 0 | 0 | 0 | 2 |

## per-rule 贡献排序 (回放 fires / rescued_cells; orig=n100 原跑 actions 计数)

| rule | phase | status | fires | rescued_cells | orig_fires | suggested |
|---|---|---|---|---|---|---|
| static_precheck | precheck | None | 40 | 34 | 40 | — |
| legacy_pkg_shim | loop | validated | 9 | 7 | 0 | — |
| install_file | loop | None | 3 | 2 | 2 | — |
| cs_targeted_fix | loop | validated | 1 | 1 | 0 | — |
| aastex_bundle_shadow | loop | validated | 0 | 0 | 0 | — |
| eps_route | loop | validated | 0 | 0 | 0 | — |
| eps_to_pdf | loop | validated | 0 | 0 | 0 | — |
| hyphenation_sane | loop | None | 0 | 0 | 0 | — |
| inputenc_strip | loop | validated | 0 | 0 | 0 | — |
| install_sysfont | loop | None | 0 | 0 | 0 | — |
| install_tfm | loop | None | 0 | 0 | 0 | — |
| microtype_off | loop | None | 0 | 0 | 0 | — |
| pdftex_prim_guard | loop | None | 0 | 0 | 0 | — |
| pstricks_route | precheck | None | 0 | 0 | 0 | — |
| px_to_bp | loop | None | 0 | 0 | 0 | — |
| soul_cjk_mbox | loop | None | 0 | 0 | 0 | — |
| undefined_cs_guess | loop | stub | 0 | 0 | 0 | — |

## 翻盘格归因 (unfixable → 出 pdf)

| corpus | before | after | 立功规则 (非 precheck actions) |
|---|---|---|---|
| 0905.4439 | unfixable:missing_file | acceptable_pdf | legacy_pkg_shim |
| 1306.2177 | unfixable:missing_file | acceptable_pdf | legacy_pkg_shim |
| 1306.5813 | unfixable:missing_file | clean | legacy_pkg_shim |
| 2105.03750 | unfixable:missing_file | acceptable_pdf | legacy_pkg_shim, install_file |
| 2211.04574 | unfixable:missing_file | best_effort_pdf | legacy_pkg_shim |
| hep-lat--0111009 | unfixable:missing_file | acceptable_pdf | legacy_pkg_shim |
| hep-ph--0111218 | unfixable:missing_file | clean | legacy_pkg_shim |

## 仍未救回格 (unfixable → 无 pdf)

| corpus | before | after | 回放 actions |
|---|---|---|---|
| 0707.4465 | unfixable:missing_file | unfixable:missing_file | legacy_pkg_shim, _best_effort_pass |
| 1803.08927 | unfixable:latex209 | unfixable:latex209 | _best_effort_pass |
| 1803.09046 | unfixable:latex209 | unfixable:latex209 | _best_effort_pass |
| 2203.04385 | unfixable:latex209 | unfixable:latex209 | _best_effort_pass |
| 2308.12712 | unfixable:other | unfixable:other | _best_effort_pass |
| hep-ph--9910403 | unfixable:other | unfixable:other | _best_effort_pass |

## 格内降级 (clean → 非 clean, 门② 外但值得记录)

| corpus | before | after |
|---|---|---|
| 1511.02820 | clean | acceptable_pdf |

## fires==0 疑似死规则 (29/33, 仅本 40 格样本口径)

| rule | phase | status |
|---|---|---|
| aastex_bundle_shadow | loop | validated |
| aux_purge_regen | loop | proposed |
| bbl_stub_shadow | loop | proposed |
| eps_route | loop | validated |
| eps_to_pdf | loop | validated |
| font_sub_shim | loop | proposed |
| hyphenation_sane | loop | None |
| inputenc_strip | loop | validated |
| install_sysfont | loop | None |
| install_tfm | loop | None |
| journal_cs_polyfill | loop | proposed |
| latex209_reject | gate | proposed |
| microtype_off | loop | None |
| minted_frozencache | loop | proposed |
| minted_v3_rewrite | loop | proposed |
| missing_char_fix | loop | proposed |
| missing_pfb_updmap | loop | proposed |
| non_utf8_source | loop | proposed |
| option_clash_merge | loop | proposed |
| pdftex_prim_guard | loop | None |
| pdftex_prim_polyfill | loop | proposed |
| pstricks_dvips_preflight | gate | proposed |
| pstricks_route | precheck | None |
| px_to_bp | loop | None |
| soul_cjk_mbox | loop | None |
| thm_sibling_strip | loop | proposed |
| times_to_newtx | loop | proposed |
| undefined_cs_guess | loop | stub |
| vendored_sty_shadow | loop | proposed |

## 回归格清单 (门② 命中, 0)

无。

## triage 队列 (当前 cases 口径, 13 格)

| corpus | verdict | rounds | 末轮cat |
|---|---|---|---|
| 0707.4465 | unfixable:missing_file | 2 | missing_file |
| 0905.4439 | unfixable:missing_file | 2 | missing_file |
| 1306.2177 | unfixable:missing_file | 2 | missing_file |
| 1306.5813 | unfixable:missing_file | 2 | missing_file |
| 1803.08927 | unfixable:latex209 | 2 | latex209 |
| 1803.09046 | unfixable:latex209 | 2 | latex209 |
| 2105.03750 | unfixable:missing_file | 2 | missing_file |
| 2203.04385 | unfixable:latex209 | 2 | latex209 |
| 2211.04574 | unfixable:missing_file | 2 | missing_file |
| 2308.12712 | unfixable:other | 2 | other |
| hep-lat--0111009 | unfixable:missing_file | 2 | missing_file |
| hep-ph--0111218 | unfixable:missing_file | 2 | missing_file |
| hep-ph--9910403 | unfixable:other | 2 | other |

