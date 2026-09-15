# fixloop bench — corpus_v2 40 篇无偏样本 × 产品化规则库

- 日期: 2026-09-16 01:10
- 规则库: `/home/fanghaotian/src/texlate/src/texlate/compile/fixloop/rules.yaml` (31 规则, max_rounds=8)
- 口径: 每篇独立冷 `_texmf` usertree (xelatex) / pin bundle+ctan_fetch (tectonic); 无 sandbox-exec; fixloop 直跑 (无 normalize/inject 前置)
- 对照: baseline = compilebench-corpusv2 同批样本原文直编 (clean/pdf~/FAIL)

## 1. 总救回率

| 引擎 | n | baseline clean/pdf~/FAIL | fixloop clean/ok~/dirty/fail/rej | FAIL→pdf | FAIL→clean层 |
|---|---|---|---|---|---|
| xelatex | 13 | 3/1/9 | 3/0/1/2/7 | 0/9 | 0/9 |
| tectonic | 13 | 3/6/4 | 0/0/0/13/0 | 0/4 | 0/4 |

**union (任一引擎)**: baseline pdf 9/13 → fixloop pdf 4/13, clean层 3/13

## 2. baseline → fixloop 转移矩阵

### xelatex

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| clean (3) | 3 | 0 | 0 | 0 | 0 |
| pdf~ (1) | 0 | 0 | 1 | 0 | 0 |
| FAIL (9) | 0 | 0 | 0 | 2 | 7 |

### tectonic

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| clean (3) | 0 | 0 | 0 | 3 | 0 |
| pdf~ (6) | 0 | 0 | 0 | 6 | 0 |
| FAIL (4) | 0 | 0 | 0 | 4 | 0 |

## 3. baseline 失败类别 × 救回 (仅 baseline=FAIL 格)

| 类别 | 引擎 | 格数 | 出pdf | clean层 | 未救回 paper (终态类别) |
|---|---|---|---|---|---|
| missing_file | xelatex | 8 | 0 | 0 | cond-mat/9910214(missing_file); astro-ph/9910044(missing_file); astro-ph/9703198(missing_file); astro-ph/9703134(missing_file); hep-ph/9910373(missing_file); hep-th/9703173(missing_file); nucl-th/0111058(missing_file); 0806.0904(unfixable:missing_file) |
| missing_file | tectonic | 3 | 0 | 0 | astro-ph/9703198(unfixable:other); astro-ph/9703134(unfixable:other); 0806.0904(unfixable:other) |
| already_def | xelatex | 1 | 0 | 0 | q-alg/9703046(unfixable:already_def) |
| already_def | tectonic | 1 | 0 | 0 | q-alg/9703046(unfixable:other) |

## 4. 规则命中分布 (actions 计数; round=0 precheck, -1 gate)

| 规则 | xelatex | tectonic | 所在格出pdf数 |
|---|---|---|---|
| latex209_reject (gate) | 0 | 0 | 0 |
| pstricks_dvips_preflight (gate) | 0 | 0 | 0 |
| pstricks_route (precheck) | 0 | 0 | 0 |
| static_precheck (precheck) | 13 | 0 | 4 |
| install_file (loop) | 1 | 0 | 0 |
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

### xelatex 装包榜 (tlmgr --usermode, file 级)

| 文件 | 格数 |
|---|---|
| epsf.sty | 1 |

## 5. 未救回格 (verdict 非 clean/ok~/dirty, 按终态类别聚类)

| paper | eng | verdict | 终态cat | 轮数 | log_excerpt |
|---|---|---|---|---|---|
| 0806.0904 | xelatex | unfixable:missing_file | — | 3 | ! LaTeX Error: File `geom.sty' not found. ! LaTeX Error: File `geom.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 0806.0904 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| astro-ph/9703134 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| astro-ph/9703198 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| astro-ph/9910044 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| cond-mat/0111097 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| cond-mat/9703223 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| cond-mat/9910214 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| hep-ph/9703402 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| hep-ph/9910373 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| hep-th/9703099 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| hep-th/9703173 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| nucl-th/0111058 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| q-alg/9703046 | xelatex | unfixable:already_def | — | 2 | /usr/share/texmf-dist/tex/latex/amsmath/amstex.sty:319: LaTeX Error: Command \negmedspace already defined. /usr/share/texmf-dist/tex/latex/a |
| q-alg/9703046 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| astro-ph/9703134 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `aaspp4.sty' not found. ! LaTeX Error: File `aaspp4.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| astro-ph/9703198 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `crckapb.cls' not found. ! LaTeX Error: File `crckapb.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| astro-ph/9910044 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `laa.cls' not found. ! LaTeX Error: File `laa.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new name. |
| cond-mat/9910214 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| hep-ph/9910373 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| hep-th/9703173 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| nucl-th/0111058 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |

## 6. 回归 (baseline 已出 pdf → fixloop 反而无 pdf)

| paper | eng | baseline | fixloop verdict |
|---|---|---|---|
| cond-mat/9910214 | tectonic | pdf~ | unfixable:other |
| astro-ph/9910044 | tectonic | pdf~ | unfixable:other |
| hep-ph/9910373 | tectonic | pdf~ | unfixable:other |
| hep-th/9703173 | tectonic | pdf~ | unfixable:other |
| cond-mat/9703223 | tectonic | clean | unfixable:other |
| hep-th/9703099 | tectonic | clean | unfixable:other |
| nucl-th/0111058 | tectonic | pdf~ | unfixable:other |
| hep-ph/9703402 | tectonic | clean | unfixable:other |
| cond-mat/0111097 | tectonic | pdf~ | unfixable:other |

## 7. 逐格明细

| paper | band | tags | route | xel: base→fix(轮/装包) | tec: base→fix |
|---|---|---|---|---|---|
| 0806.0904 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 3r/1i | FAIL→unfixable:other 2r/0i |
| astro-ph/9703134 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i | FAIL→unfixable:other 2r/0i |
| astro-ph/9703198 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i | FAIL→unfixable:other 2r/0i |
| astro-ph/9910044 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i | pdf~→unfixable:other 2r/0i |
| cond-mat/0111097 | a | — | xelatex/tectonic | pdf~→best_effort_pdf 2r/0i | pdf~→unfixable:other 2r/0i |
| cond-mat/9703223 | a | — | xelatex/tectonic | clean→clean 1r/0i | clean→unfixable:other 2r/0i |
| cond-mat/9910214 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i | pdf~→unfixable:other 2r/0i |
| hep-ph/9703402 | a | — | xelatex/tectonic | clean→clean 1r/0i | clean→unfixable:other 2r/0i |
| hep-ph/9910373 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i | pdf~→unfixable:other 2r/0i |
| hep-th/9703099 | a | — | xelatex/tectonic | clean→clean 1r/0i | clean→unfixable:other 2r/0i |
| hep-th/9703173 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i | pdf~→unfixable:other 2r/0i |
| nucl-th/0111058 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i | pdf~→unfixable:other 2r/0i |
| q-alg/9703046 | a | — | xelatex/tectonic | FAIL→unfixable:already_def 2r/0i | FAIL→unfixable:other 2r/0i |

