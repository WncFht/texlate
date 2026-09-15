# validbench — B6 校验段基准

- date: 2026-09-15 06:14Z · wall 1.7s
- papers: 7/7 used (parse_fail 0) · pairs 313
- cases: 1636 (clean 313 + corrupted 1323) + probes 14
- **gates**: corruption100%=✅ · 0errorFP=✅ · probes=✅ · L0≤1ms=✅ (摊薄 0.9987ms/对 · 逐对 p50 0.664 p95 2.8664 max 11.6274)

## L0 检出率（kind × level）

| kind | level | n | detected | rate | suggest | 触发规则(error) |
|---|---|---|---|---|---|---|
| c01_drop_rbrace | ph | 44 | 44 | 100.0% | 0 | brace:44 |
| c01_drop_rbrace | raw | 133 | 133 | 100.0% | 0 | brace:133, key:76, env:3 |
| c02_drop_dollar | raw | 70 | 70 | 100.0% | 0 | math:70 |
| c03_rename_end | raw | 23 | 23 | 100.0% | 0 | env:23 |
| c04_drop_end | raw | 23 | 23 | 100.0% | 0 | env:23 |
| c05_drop_ph | ph | 138 | 138 | 100.0% | 0 | placeholder:138 |
| c06_typo_ph | ph | 138 | 138 | 100.0% | 135 | placeholder:138 |
| c07_unpair_lbrack | raw | 6 | 6 | 100.0% | 0 | math:6 |
| c08_halluc_macro | ph | 175 | 175 | 100.0% | 0 | macro:175, placeholder:17 |
| c08_halluc_macro | raw | 138 | 138 | 100.0% | 0 | macro:138, key:13, env:2 |
| c09_drop_key | raw | 122 | 122 | 100.0% | 0 | key:122 |
| c10_extra_ph | ph | 175 | 175 | 100.0% | 1 | placeholder:175 |
| c10_extra_ph | raw | 138 | 138 | 100.0% | 0 | placeholder:138, key:14, math:3, env:2 |
| clean | ph | 175 | 0 | 0.0% | 0 | - |
| clean | raw | 138 | 0 | 0.0% | 0 | - |

## 干净对

- n=313 · error-FP=0 · warn-only=2

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

## L1

skipped: --no-l1

## 漏检

(none)

## 延迟（L0 逐对计时，ms）

| level | n | mean | p50 | p95 | max |
|---|---|---|---|---|---|
| ph | 845 | 0.7816 | 0.5827 | 2.376 | 4.1945 |
| raw | 791 | 1.2215 | 0.7785 | 3.4323 | 11.6274 |

