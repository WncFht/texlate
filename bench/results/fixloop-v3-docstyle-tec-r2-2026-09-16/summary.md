# fixloop bench — corpus_v2 40 篇无偏样本 × 产品化规则库

- 日期: 2026-09-16 01:31
- 规则库: `/home/fanghaotian/src/texlate/src/texlate/compile/fixloop/rules.yaml` (31 规则, max_rounds=8)
- 口径: 每篇独立冷 `_texmf` usertree (xelatex) / pin bundle+ctan_fetch (tectonic); 无 sandbox-exec; fixloop 直跑 (无 normalize/inject 前置)
- 对照: baseline = compilebench-corpusv2 同批样本原文直编 (clean/pdf~/FAIL)

## 1. 总救回率

| 引擎 | n | baseline clean/pdf~/FAIL | fixloop clean/ok~/dirty/fail/rej | FAIL→pdf | FAIL→clean层 |
|---|---|---|---|---|---|
| tectonic | 13 | 3/6/4 | 3/1/0/2/7 | 0/4 | 0/4 |

**union (任一引擎)**: baseline pdf 9/13 → fixloop pdf 4/13, clean层 4/13

## 2. baseline → fixloop 转移矩阵

### tectonic

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| clean (3) | 3 | 0 | 0 | 0 | 0 |
| pdf~ (6) | 0 | 1 | 0 | 0 | 5 |
| FAIL (4) | 0 | 0 | 0 | 2 | 2 |

## 3. baseline 失败类别 × 救回 (仅 baseline=FAIL 格)

| 类别 | 引擎 | 格数 | 出pdf | clean层 | 未救回 paper (终态类别) |
|---|---|---|---|---|---|
| missing_file | tectonic | 3 | 0 | 0 | astro-ph/9703198(missing_file); astro-ph/9703134(missing_file); 0806.0904(unfixable:missing_file) |
| already_def | tectonic | 1 | 0 | 0 | q-alg/9703046(unfixable:already_def) |

## 4. 规则命中分布 (actions 计数; round=0 precheck, -1 gate)

| 规则 | xelatex | tectonic | 所在格出pdf数 |
|---|---|---|---|
| latex209_reject (gate) | 0 | 0 | 0 |
| pstricks_dvips_preflight (gate) | 0 | 0 | 0 |
| pstricks_route (precheck) | 0 | 0 | 0 |
| static_precheck (precheck) | 0 | 0 | 0 |
| install_file (loop) | 0 | 0 | 0 |
| legacy_pkg_shim (loop) | 0 | 0 | 0 |
| install_tfm (loop) | 0 | 0 | 0 |
| eps_to_pdf (loop) | 0 | 0 | 0 |
| eps_route (loop) | 0 | 0 | 0 |
| install_sysfont (loop) | 0 | 0 | 0 |
| missing_pfb_updmap (loop) | 0 | 0 | 0 |
| font_sub_shim (loop) | 0 | 0 | 0 |
| pdftex_prim_guard (loop) | 0 | 0 | 0 |
| pdftex_prim_polyfill (loop) | 0 | 0 | 0 |
| px_to_bp (loop) | 0 | 0 | 0 |
| microtype_off (loop) | 0 | 0 | 0 |
| times_to_newtx (loop) | 0 | 0 | 0 |
| hyphenation_sane (loop) | 0 | 0 | 0 |
| inputenc_strip (loop) | 0 | 0 | 0 |
| non_utf8_source (loop) | 0 | 0 | 0 |
| soul_cjk_mbox (loop) | 0 | 0 | 0 |
| thm_sibling_strip (loop) | 0 | 0 | 0 |
| option_clash_merge (loop) | 0 | 0 | 0 |
| minted_frozencache (loop) | 0 | 0 | 0 |
| minted_v3_rewrite (loop) | 0 | 0 | 0 |
| bbl_stub_shadow (loop) | 0 | 0 | 0 |
| vendored_sty_shadow (loop) | 0 | 0 | 0 |
| aastex_bundle_shadow (loop) | 0 | 0 | 0 |
| journal_cs_polyfill (loop) | 0 | 0 | 0 |
| cs_targeted_fix (loop) | 0 | 0 | 0 |
| undefined_cs_guess (loop) | 0 | 0 | 0 |

## 5. 未救回格 (verdict 非 clean/ok~/dirty, 按终态类别聚类)

| paper | eng | verdict | 终态cat | 轮数 | log_excerpt |
|---|---|---|---|---|---|
| 0806.0904 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `geom.sty' not found.. ! ! LaTeX Error: File `geom.sty' not found.. \saved@missingfileerror ...ile `#1.#2' not found.} |
| q-alg/9703046 | tectonic | unfixable:already_def | — | 2 | ! LaTeX Error: Command \negmedspace already defined. ! LaTeX Error: Command \negmedspace already defined.                Or name \end... ill |
| astro-ph/9703134 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `aaspp4.sty' not found.. ! ! LaTeX Error: File `aaspp4.sty' not found.. \saved@missingfileerror ...ile `#1.#2' not fou |
| astro-ph/9703198 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `crckapb.cls' not found.. ! ! LaTeX Error: File `crckapb.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not f |
| astro-ph/9910044 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `laa.cls' not found.. ! ! LaTeX Error: File `laa.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not found.}   |
| cond-mat/9910214 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `revtex.cls' not found.. ! ! LaTeX Error: File `revtex.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not fou |
| hep-ph/9910373 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `revtex.cls' not found.. ! ! LaTeX Error: File `revtex.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not fou |
| hep-th/9703173 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `revtex.cls' not found.. ! ! LaTeX Error: File `revtex.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not fou |
| nucl-th/0111058 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `revtex.cls' not found.. ! ! LaTeX Error: File `revtex.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not fou |

## 6. 回归 (baseline 已出 pdf → fixloop 反而无 pdf)

| paper | eng | baseline | fixloop verdict |
|---|---|---|---|
| hep-ph/9910373 | tectonic | pdf~ | reject:latex209_reject |
| hep-th/9703173 | tectonic | pdf~ | reject:latex209_reject |
| astro-ph/9910044 | tectonic | pdf~ | reject:latex209_reject |
| cond-mat/9910214 | tectonic | pdf~ | reject:latex209_reject |
| nucl-th/0111058 | tectonic | pdf~ | reject:latex209_reject |

## 7. 逐格明细

| paper | band | tags | route | xel: base→fix(轮/装包) | tec: base→fix |
|---|---|---|---|---|---|
| 0806.0904 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| astro-ph/9703134 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i |
| astro-ph/9703198 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i |
| astro-ph/9910044 | a | — | xelatex/tectonic | pdf~→reject:latex209_reject 1r/0i |
| cond-mat/0111097 | a | — | xelatex/tectonic | pdf~→acceptable_pdf 1r/0i |
| cond-mat/9703223 | a | — | xelatex/tectonic | clean→clean 1r/0i |
| cond-mat/9910214 | a | — | xelatex/tectonic | pdf~→reject:latex209_reject 1r/0i |
| hep-ph/9703402 | a | — | xelatex/tectonic | clean→clean 1r/0i |
| hep-ph/9910373 | a | — | xelatex/tectonic | pdf~→reject:latex209_reject 1r/0i |
| hep-th/9703099 | a | — | xelatex/tectonic | clean→clean 1r/0i |
| hep-th/9703173 | a | — | xelatex/tectonic | pdf~→reject:latex209_reject 1r/0i |
| nucl-th/0111058 | a | — | xelatex/tectonic | pdf~→reject:latex209_reject 1r/0i |
| q-alg/9703046 | a | — | xelatex/tectonic | FAIL→unfixable:already_def 2r/0i |

