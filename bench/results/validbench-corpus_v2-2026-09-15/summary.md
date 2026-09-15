# validbench — B6 校验段基准

- date: 2026-09-15 06:45Z · wall 7.3s
- papers: 137/139 used (parse_fail 0) · pairs 1503
- cases: 7867 (clean 1503 + corrupted 6364) + probes 14
- **gates**: corruption100%=✅ · 0errorFP=✅ · probes=✅ · L0≤1ms=✅ (摊薄 0.374ms/对 · 逐对 p50 0.2462 p95 1.0261 max 5.181)

## L0 检出率（kind × level）

| kind | level | n | detected | rate | suggest | 触发规则(error) |
|---|---|---|---|---|---|---|
| c01_drop_rbrace | ph | 222 | 222 | 100.0% | 0 | brace:222, macro:3 |
| c01_drop_rbrace | raw | 609 | 609 | 100.0% | 0 | brace:609, key:244, env:20, macro:1 |
| c02_drop_dollar | raw | 466 | 466 | 100.0% | 0 | math:466 |
| c03_rename_end | raw | 110 | 110 | 100.0% | 0 | env:110 |
| c04_drop_end | raw | 110 | 110 | 100.0% | 0 | env:110 |
| c05_drop_ph | ph | 685 | 685 | 100.0% | 0 | placeholder:685 |
| c06_typo_ph | ph | 685 | 685 | 100.0% | 672 | placeholder:685 |
| c07_unpair_lbrack | raw | 19 | 19 | 100.0% | 0 | math:19 |
| c08_halluc_macro | ph | 818 | 818 | 100.0% | 13 | macro:818, placeholder:146 |
| c08_halluc_macro | raw | 685 | 685 | 100.0% | 0 | macro:685, key:58, env:8 |
| c09_drop_key | raw | 452 | 452 | 100.0% | 0 | key:452, macro:2 |
| c10_extra_ph | ph | 818 | 818 | 100.0% | 19 | placeholder:818, math:3, macro:1 |
| c10_extra_ph | raw | 685 | 685 | 100.0% | 0 | placeholder:685, key:59, math:26, env:7, macro:2 |
| clean | ph | 818 | 0 | 0.0% | 0 | - |
| clean | raw | 685 | 0 | 0.0% | 0 | - |

## 干净对

- n=1503 · error-FP=0 · warn-only=11

## 对抗探针

| probe | expect_ok | got | err | warn | verdict |
|---|---|---|---|---|---|
| probe/emph_drop | True | True | 0 | 2 | pass |
| probe/src_imbalance | True | True | 0 | 0 | pass |
| probe/ph_reorder | True | True | 0 | 1 | pass |
| probe/cite_space | True | True | 0 | 0 | pass |
| probe/cite_key_missing | False | False | 1 | 0 | pass |
| probe/fullwidth_ph | False | False | 1 | 0 | pass |
| probe/bibitem_anchor | False | False | 1 | 0 | pass |
| probe/cs_dropped | False | False | 1 | 1 | pass |
| probe/fused_cs | False | False | 2 | 0 | pass |
| probe/odd_dollar_inherited | True | True | 0 | 1 | pass |
| probe/halluc_key | True | True | 0 | 3 | pass |
| probe/cite_optarg_drop | True | True | 0 | 0 | pass |
| probe/env_inherited | True | True | 0 | 0 | pass |
| probe/display_unpaired | False | False | 1 | 0 | pass |

## L1（tree-sitter, baseline-relative）

- clean: n=1503 · FP(rel)=0 · FP(abs)=74 · parse_ms {'n': 7867, 'mean': 0.0509, 'p50': 0.036, 'p95': 0.136, 'max': 0.649}

| kind | level | n | det(rel) | det(abs) |
|---|---|---|---|---|
| c01_drop_rbrace | ph | 222 | 219 | 219 |
| c01_drop_rbrace | raw | 609 | 607 | 607 |
| c02_drop_dollar | raw | 466 | 465 | 466 |
| c03_rename_end | raw | 110 | 110 | 110 |
| c04_drop_end | raw | 110 | 110 | 110 |
| c05_drop_ph | ph | 685 | 685 | 685 |
| c06_typo_ph | ph | 685 | 685 | 685 |
| c07_unpair_lbrack | raw | 19 | 19 | 19 |
| c08_halluc_macro | ph | 818 | 146 | 155 |
| c08_halluc_macro | raw | 685 | 25 | 84 |
| c09_drop_key | raw | 452 | 1 | 29 |
| c10_extra_ph | ph | 818 | 818 | 818 |
| c10_extra_ph | raw | 685 | 685 | 685 |
| clean | ph | 818 | 0 | 12 |
| clean | raw | 685 | 0 | 62 |

## 漏检

(none)

## 延迟（L0 逐对计时，ms）

| level | n | mean | p50 | p95 | max |
|---|---|---|---|---|---|
| ph | 4046 | 0.3056 | 0.2043 | 0.8259 | 2.1209 |
| raw | 3821 | 0.4427 | 0.3097 | 1.1875 | 5.181 |

