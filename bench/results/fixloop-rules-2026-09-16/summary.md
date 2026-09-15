# fixloop bench — corpus_v2 40 篇无偏样本 × 产品化规则库

- 日期: 2026-09-16 01:11
- 规则库: `/home/fanghaotian/src/texlate/src/texlate/compile/fixloop/rules.yaml` (31 规则, max_rounds=8)
- 口径: 每篇独立冷 `_texmf` usertree (xelatex) / pin bundle+ctan_fetch (tectonic); 无 sandbox-exec; fixloop 直跑 (无 normalize/inject 前置)
- 对照: baseline = compilebench-corpusv2 同批样本原文直编 (clean/pdf~/FAIL)

## 1. 总救回率

| 引擎 | n | baseline clean/pdf~/FAIL | fixloop clean/ok~/dirty/fail/rej | FAIL→pdf | FAIL→clean层 |
|---|---|---|---|---|---|
| xelatex | 8 | 1/1/3 | 6/0/2/0/0 | 3/3 | 1/3 |
| tectonic | 8 | 1/3/1 | 0/0/0/8/0 | 0/1 | 0/1 |

**union (任一引擎)**: baseline pdf 4/8 → fixloop pdf 8/8, clean层 6/8

## 2. baseline → fixloop 转移矩阵

### xelatex

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| clean (1) | 1 | 0 | 0 | 0 | 0 |
| pdf~ (1) | 1 | 0 | 0 | 0 | 0 |
| FAIL (3) | 1 | 0 | 2 | 0 | 0 |
| None (3) | 3 | 0 | 0 | 0 | 0 |

### tectonic

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| clean (1) | 0 | 0 | 0 | 1 | 0 |
| pdf~ (3) | 0 | 0 | 0 | 3 | 0 |
| FAIL (1) | 0 | 0 | 0 | 1 | 0 |
| None (3) | 0 | 0 | 0 | 3 | 0 |

## 3. baseline 失败类别 × 救回 (仅 baseline=FAIL 格)

| 类别 | 引擎 | 格数 | 出pdf | clean层 | 未救回 paper (终态类别) |
|---|---|---|---|---|---|
| missing_file | xelatex | 3 | 3 | 1 | — |
| eps_image | tectonic | 1 | 0 | 0 | 1206.5832(unfixable:other) |

## 4. 规则命中分布 (actions 计数; round=0 precheck, -1 gate)

| 规则 | xelatex | tectonic | 所在格出pdf数 |
|---|---|---|---|
| latex209_reject (gate) | 0 | 0 | 0 |
| pstricks_dvips_preflight (gate) | 0 | 0 | 0 |
| pstricks_route (precheck) | 0 | 0 | 0 |
| static_precheck (precheck) | 8 | 0 | 8 |
| install_file (loop) | 2 | 0 | 1 |
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
| inputenc_strip (loop) | 5 | 0 | 5 |
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
| cs_targeted_fix (loop) | 1 | 0 | 1 |
| undefined_cs_guess (loop) | 0 | 0 | 0 |

### xelatex 装包榜 (tlmgr --usermode, file 级)

| 文件 | 格数 |
|---|---|
| revtex4.cls | 4 |
| epsf.sty | 1 |
| algorithm2e.sty | 1 |
| accents.sty | 1 |

## 5. 未救回格 (verdict 非 clean/ok~/dirty, 按终态类别聚类)

| paper | eng | verdict | 终态cat | 轮数 | log_excerpt |
|---|---|---|---|---|---|
| 1012.1124 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| 1206.5628 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| 1206.5832 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| 1608.02354 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| 1909.05039 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| 2007.02320 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| 2301.01267 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |
| 2308.04174 | tectonic | unfixable:other | — | 2 | ! No such file or directory (os error 2) ! No such file or directory (os error 2) |

## 6. 回归 (baseline 已出 pdf → fixloop 反而无 pdf)

| paper | eng | baseline | fixloop verdict |
|---|---|---|---|
| 1608.02354 | tectonic | clean | unfixable:other |
| 1206.5628 | tectonic | pdf~ | unfixable:other |
| 1012.1124 | tectonic | pdf~ | unfixable:other |
| 2308.04174 | tectonic | pdf~ | unfixable:other |

## 7. 逐格明细

| paper | band | tags | route | xel: base→fix(轮/装包) | tec: base→fix |
|---|---|---|---|---|---|
| 1012.1124 | b | — | xelatex/tectonic | pdf~→clean 2r/1i | pdf~→unfixable:other 2r/0i |
| 1206.5628 | c | — | xelatex/tectonic | FAIL→best_effort_pdf 3r/1i | pdf~→unfixable:other 2r/0i |
| 1206.5832 | c | — | xelatex/tectonic | FAIL→clean 2r/1i | FAIL→unfixable:other 2r/0i |
| 1608.02354 | c | — | xelatex/tectonic | clean→clean 2r/0i | clean→unfixable:other 2r/0i |
| 1909.05039 | None | — | — | ?→clean 4r/2i | ?→unfixable:other 2r/0i |
| 2007.02320 | None | — | — | ?→clean 1r/1i | ?→unfixable:other 2r/0i |
| 2301.01267 | None | — | — | ?→clean 1r/0i | ?→unfixable:other 2r/0i |
| 2308.04174 | e | — | xelatex/tectonic | FAIL→best_effort_pdf 3r/1i | pdf~→unfixable:other 2r/0i |

