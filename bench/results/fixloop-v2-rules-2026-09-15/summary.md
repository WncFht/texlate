# fixloop bench — corpus_v2 40 篇无偏样本 × 产品化规则库

- 日期: 2026-09-15 17:20
- 规则库: `/Users/fanghaotian/src/texlate/src/texlate/compile/fixloop/rules.yaml` (29 规则, max_rounds=8)
- 口径: 每篇独立冷 `_texmf` usertree (xelatex) / pin bundle+ctan_fetch (tectonic); 无 sandbox-exec; fixloop 直跑 (无 normalize/inject 前置)
- 对照: baseline = compilebench-corpusv2 同批样本原文直编 (clean/pdf~/FAIL)

## 1. 总救回率

| 引擎 | n | baseline clean/pdf~/FAIL | fixloop clean/ok~/dirty/fail/rej | FAIL→pdf | FAIL→clean层 |
|---|---|---|---|---|---|
| xelatex | 40 | 4/2/34 | 22/9/0/4/5 | 26/34 | 26/34 |
| tectonic | 40 | 8/16/16 | 19/8/4/4/5 | 12/16 | 11/16 |

**union (任一引擎)**: baseline pdf 26/40 → fixloop pdf 34/40, clean层 33/40

## 2. baseline → fixloop 转移矩阵

### xelatex

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| clean (4) | 4 | 0 | 0 | 0 | 0 |
| pdf~ (2) | 0 | 1 | 0 | 1 | 0 |
| FAIL (34) | 18 | 8 | 0 | 3 | 5 |

### tectonic

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| clean (8) | 7 | 1 | 0 | 0 | 0 |
| pdf~ (16) | 1 | 7 | 3 | 0 | 5 |
| FAIL (16) | 11 | 0 | 1 | 4 | 0 |

## 3. baseline 失败类别 × 救回 (仅 baseline=FAIL 格)

| 类别 | 引擎 | 格数 | 出pdf | clean层 | 未救回 paper (终态类别) |
|---|---|---|---|---|---|
| missing_file | xelatex | 34 | 26 | 26 | astro-ph/9702009(missing_file); cond-mat/9601002(missing_file); gr-qc/0012020(missing_file); nucl-th/0104042(missing_file); quant-ph/9712026(missing_file); 1505.00491(other); 0912.5174(other); 1909.05039(undefined_cs) |
| ps_image | tectonic | 9 | 9 | 9 | — |
| undefined_cs | tectonic | 2 | 1 | 1 | 1909.05039(undefined_cs) |
| bib_error | tectonic | 1 | 1 | 1 | — |
| missing_file | tectonic | 1 | 0 | 0 | 1608.04155(missing_file) |
| pdftex_prim | tectonic | 1 | 0 | 0 | 1801.06287(pdftex_prim) |
| syntax | tectonic | 1 | 0 | 0 | 2002.05660(syntax) |
| missing_pfb | tectonic | 1 | 1 | 0 | — |

## 4. 规则命中分布 (actions 计数; round=0 precheck, -1 gate)

| 规则 | xelatex | tectonic | 所在格出pdf数 |
|---|---|---|---|
| latex209_reject (gate) | 0 | 0 | 0 |
| pstricks_dvips_preflight (gate) | 0 | 0 | 0 |
| pstricks_route (precheck) | 0 | 0 | 0 |
| static_precheck (precheck) | 40 | 0 | 31 |
| install_file (loop) | 16 | 0 | 9 |
| legacy_pkg_shim (loop) | 1 | 0 | 1 |
| install_tfm (loop) | 12 | 0 | 7 |
| eps_to_pdf (loop) | 0 | 11 | 11 |
| eps_route (loop) | 0 | 0 | 0 |
| install_sysfont (loop) | 0 | 0 | 0 |
| missing_pfb_updmap (loop) | 0 | 0 | 0 |
| font_sub_shim (loop) | 0 | 1 | 1 |
| pdftex_prim_guard (loop) | 2 | 1 | 1 |
| pdftex_prim_polyfill (loop) | 0 | 0 | 0 |
| px_to_bp (loop) | 0 | 0 | 0 |
| microtype_off (loop) | 0 | 0 | 0 |
| times_to_newtx (loop) | 0 | 0 | 0 |
| hyphenation_sane (loop) | 0 | 0 | 0 |
| non_utf8_source (loop) | 1 | 0 | 1 |
| soul_cjk_mbox (loop) | 0 | 0 | 0 |
| thm_sibling_strip (loop) | 0 | 0 | 0 |
| option_clash_merge (loop) | 0 | 0 | 0 |
| minted_frozencache (loop) | 0 | 0 | 0 |
| minted_v3_rewrite (loop) | 0 | 0 | 0 |
| bbl_stub_shadow (loop) | 0 | 3 | 3 |
| vendored_sty_shadow (loop) | 0 | 0 | 0 |
| aastex_bundle_shadow (loop) | 0 | 1 | 1 |
| journal_cs_polyfill (loop) | 0 | 0 | 0 |
| undefined_cs_guess (loop) | 0 | 0 | 0 |

### xelatex 装包榜 (tlmgr --usermode, file 级)

| 文件 | 格数 |
|---|---|
| subfigure.sty | 10 |
| revtex4.cls | 10 |
| rsfs10.tfm | 7 |
| epsf.sty | 5 |
| algpseudocode.sty | 5 |
| algorithm.sty | 5 |
| txfonts.sty | 4 |
| IEEEtran.cls | 4 |
| emulateapj.cls | 3 |
| algorithmic.sty | 3 |
| enumitem.sty | 3 |
| revtex4-1.cls | 2 |
| titlesec.sty | 2 |
| fullpage.sty | 2 |
| wrapfig.sty | 2 |
| algorithm2e.sty | 2 |
| authblk.sty | 2 |
| bbm.sty | 2 |
| ifoddpage.sty | 2 |
| relsize.sty | 2 |
| diagbox.sty | 2 |
| pict2e.sty | 2 |
| a4wide.sty | 1 |
| harvard.sty | 1 |
| srcltx.sty | 1 |
| citeref.sty | 1 |
| accents.sty | 1 |
| overpic.sty | 1 |
| epic.sty | 1 |
| dashrule.sty | 1 |

## 5. 未救回格 (verdict 非 clean/ok~/dirty, 按终态类别聚类)

| paper | eng | verdict | 终态cat | 轮数 | log_excerpt |
|---|---|---|---|---|---|
| 1608.04155 | tectonic | unfixable:missing_file | missing_file | 1 | ! LaTeX Error: File `example2c.eps' not found. ! LaTeX Error: File `example2c.eps' not found.  See the LaTeX manual or LaTeX Companion for e |
| astro-ph/9702009 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `psfig.sty' not found. ! LaTeX Error: File `psfig.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new n |
| astro-ph/9702009 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `psfig.sty' not found.. ! ! LaTeX Error: File `psfig.sty' not found.. \saved@missingfileerror ...ile `#1.#2' not found |
| cond-mat/9601002 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| cond-mat/9601002 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `revtex.cls' not found.. ! ! LaTeX Error: File `revtex.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not fou |
| gr-qc/0012020 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| gr-qc/0012020 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `revtex.cls' not found.. ! ! LaTeX Error: File `revtex.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not fou |
| nucl-th/0104042 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| nucl-th/0104042 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `revtex.cls' not found.. ! ! LaTeX Error: File `revtex.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not fou |
| quant-ph/9712026 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| quant-ph/9712026 | tectonic | reject:latex209_reject | missing_file | 1 | ! ! LaTeX Error: File `revtex.cls' not found.. ! ! LaTeX Error: File `revtex.cls' not found.. \saved@missingfileerror ...ile `#1.#2' not fou |
| 0912.5174 | xelatex | unfixable:other | other | 1 | /usr/local/texlive/2026basic/texmf-dist/tex/latex/base/inputenc.sty:164: Package inputenc Error: inputenc is not designed for xetex or luate |
| 1505.00491 | xelatex | unfixable:other | other | 1 | /Users/fanghaotian/src/texlate/bench/work_fixloop_v2/1505.00491/xelatex/HPNP2015_ejchun.tex:85: Argument of \@gobble has an extra }. /Users/ |
| astro-ph/0306068 | xelatex | unfixable:other | other | 2 | /Users/fanghaotian/src/texlate/bench/work_fixloop_v2/astro-ph/0306068/xelatex/hamann.tex:80: Extra }, or forgotten $. /Users/fanghaotian/src |
| 1801.06287 | tectonic | unfixable:pdftex_prim | pdftex_prim | 2 | ! Undefined control sequence. ! Undefined control sequence. <argument> \ifnum \pdfshellescape                                    >0 \edef \G |
| 2002.05660 | tectonic | unfixable:syntax | syntax | 1 | ! Paragraph ended before \@tempa was complete. ! Paragraph ended before \@tempa was complete. <to be read again>                     \par  l |
| 1909.05039 | xelatex | unfixable:undefined_cs | undefined_cs | 4 | /Users/fanghaotian/src/texlate/bench/work_fixloop_v2/1909.05039/xelatex/IZWI_xmm2015_rev1.tex:201: Undefined control sequence. /Users/fangha |
| 1909.05039 | tectonic | unfixable:undefined_cs | undefined_cs | 1 | ! Undefined control sequence. ! Undefined control sequence. \__hook shipout/firstpage ...geHook \headerps@out                                |

## 6. 回归 (baseline 已出 pdf → fixloop 反而无 pdf)

| paper | eng | baseline | fixloop verdict |
|---|---|---|---|
| astro-ph/9702009 | tectonic | pdf~ | reject:latex209_reject |
| cond-mat/9601002 | tectonic | pdf~ | reject:latex209_reject |
| gr-qc/0012020 | tectonic | pdf~ | reject:latex209_reject |
| nucl-th/0104042 | tectonic | pdf~ | reject:latex209_reject |
| quant-ph/9712026 | tectonic | pdf~ | reject:latex209_reject |
| astro-ph/0306068 | xelatex | pdf~ | unfixable:other |

## 7. 逐格明细

| paper | band | tags | route | xel: base→fix(轮/装包) | tec: base→fix |
|---|---|---|---|---|---|
| 0812.4521 | b | xelatex | xelatex/tectonic | pdf~→acceptable_pdf 1r/0i | pdf~→dirty_pdf 1r/0i |
| 0903.0543 | b | xelatex | xelatex/tectonic | FAIL→clean 2r/3i | FAIL→clean 2r/0i |
| 0909.3990 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 0912.2867 | b | — | xelatex/tectonic | FAIL→clean 1r/2i | clean→clean 1r/0i |
| 0912.5174 | b | non-utf8 | xelatex/tectonic | FAIL→unfixable:other 1r/3i | pdf~→acceptable_pdf 1r/0i |
| 1005.0504 | b | xelatex | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1009.5340 | b | xelatex | xelatex/tectonic | clean→clean 1r/2i | FAIL→clean 2r/0i |
| 1011.5681 | b | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1206.0671 | c | non-utf8 | xelatex/tectonic | FAIL→clean 3r/3i | pdf~→acceptable_pdf 1r/0i |
| 1404.7186 | c | — | xelatex/tectonic | FAIL→clean 1r/3i | clean→clean 1r/0i |
| 1406.1994 | c | non-utf8 | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1503.02052 | c | xelatex | xelatex/tectonic | FAIL→clean 3r/3i | FAIL→clean 2r/0i |
| 1505.00491 | c | xelatex | xelatex/tectonic | FAIL→unfixable:other 1r/2i | pdf~→dirty_pdf 1r/0i |
| 1607.00497 | c | — | xelatex/tectonic | FAIL→clean 1r/5i | clean→clean 2r/0i |
| 1608.04155 | c | xelatex | xelatex/tectonic | FAIL→acceptable_pdf 2r/6i | FAIL→unfixable:missing_file 1r/0i |
| 1609.01652 | c | — | xelatex/tectonic | FAIL→acceptable_pdf 4r/5i | pdf~→acceptable_pdf 1r/0i |
| 1801.06287 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 3r/4i | FAIL→unfixable:pdftex_prim 2r/0i |
| 1806.06690 | d | xelatex | xelatex/tectonic | FAIL→clean 4r/4i | FAIL→clean 3r/0i |
| 1902.11112 | d | xelatex | xelatex/tectonic | FAIL→clean 2r/3i | FAIL→clean 2r/0i |
| 1905.07704 | d | — | xelatex/tectonic | clean→clean 1r/1i | clean→clean 1r/0i |
| 1909.05039 | d | — | xelatex/tectonic | FAIL→unfixable:undefined_cs 4r/6i | FAIL→unfixable:undefined_cs 1r/0i |
| 1910.12800 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 3r/13i | pdf~→acceptable_pdf 1r/0i |
| 2002.05660 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 3r/8i | FAIL→unfixable:syntax 1r/0i |
| 2007.02320 | d | — | xelatex/tectonic | FAIL→clean 1r/3i | pdf~→dirty_pdf 1r/0i |
| 2104.00776 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/5i | pdf~→acceptable_pdf 1r/0i |
| 2104.02882 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 3r/7i | pdf~→acceptable_pdf 2r/0i |
| 2109.12648 | e | — | xelatex/tectonic | FAIL→clean 3r/9i | clean→acceptable_pdf 1r/0i |
| 2110.10462 | e | — | xelatex/tectonic | FAIL→clean 2r/3i | clean→clean 1r/0i |
| 2201.04035 | e | — | xelatex/tectonic | FAIL→clean 1r/2i | pdf~→clean 1r/0i |
| 2301.01267 | e | — | xelatex/tectonic | FAIL→clean 3r/6i | FAIL→dirty_pdf 2r/0i |
| 2506.07410 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 3r/6i | pdf~→acceptable_pdf 1r/0i |
| astro-ph/0306068 | a | — | xelatex/tectonic | pdf~→unfixable:other 2r/1i | FAIL→clean 2r/0i |
| astro-ph/9702009 | a | reject | latex209_documentstyle | FAIL→reject:latex209_reject 1r/0i | pdf~→reject:latex209_reject 1r/0i |
| cond-mat/0202090 | a | xelatex | xelatex/tectonic | FAIL→clean 1r/3i | FAIL→clean 2r/0i |
| cond-mat/9601002 | a | reject | latex209_documentstyle | FAIL→reject:latex209_reject 1r/0i | pdf~→reject:latex209_reject 1r/0i |
| gr-qc/0012020 | a | reject | latex209_documentstyle | FAIL→reject:latex209_reject 1r/0i | pdf~→reject:latex209_reject 1r/0i |
| hep-ex/0406065 | a | xelatex | xelatex/tectonic | FAIL→clean 1r/2i | FAIL→clean 3r/0i |
| hep-th/0508095 | a | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| nucl-th/0104042 | a | reject,xelatex | latex209_documentstyle | FAIL→reject:latex209_reject 1r/0i | pdf~→reject:latex209_reject 1r/0i |
| quant-ph/9712026 | a | reject | latex209_documentstyle | FAIL→reject:latex209_reject 1r/0i | pdf~→reject:latex209_reject 1r/0i |

