# fixloop bench — corpus_v3 175 篇 × 产品化规则库 (zh 注入臂)

- 日期: 2026-09-16 10:18
- 规则库: `/home/fanghaotian/src/texlate/src/texlate/compile/fixloop/rules.yaml` (31 规则, max_rounds=8)
- 口径: 每篇独立冷 `_texmf` usertree (xelatex) / pin bundle+ctan_fetch (tectonic); 无 sandbox-exec; fixloop 前 normalize_project + prepare_chinese(ctex) 注入
- 对照: baseline = /home/fanghaotian/src/texlate/bench/results/compilebench-v3-zh-2026-09-16/cases.jsonl (clean/pdf~/FAIL)

## 1. 总救回率

| 引擎 | n | baseline clean/pdf~/FAIL | fixloop clean/ok~/dirty/fail/rej | FAIL→pdf | FAIL→clean层 |
|---|---|---|---|---|---|
| xelatex | 175 | 48/6/108 | 104/32/7/19/13 | 89/108 | 84/108 |
| tectonic | 175 | 62/40/60 | 95/41/2/22/15 | 39/60 | 39/60 |

**union (任一引擎)**: baseline pdf 120/175 → fixloop pdf 151/175, clean层 150/175

## 2. baseline → fixloop 转移矩阵

### xelatex

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| clean (48) | 45 | 1 | 2 | 0 | 0 |
| pdf~ (6) | 5 | 1 | 0 | 0 | 0 |
| FAIL (108) | 54 | 30 | 5 | 19 | 0 |

### tectonic

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| clean (62) | 55 | 6 | 0 | 0 | 1 |
| pdf~ (40) | 4 | 32 | 2 | 1 | 1 |
| FAIL (60) | 36 | 3 | 0 | 21 | 0 |

## 3. baseline 失败类别 × 救回 (仅 baseline=FAIL 格)

| 类别 | 引擎 | 格数 | 出pdf | clean层 | 未救回 paper (终态类别) |
|---|---|---|---|---|---|
| missing_file | xelatex | 106 | 88 | 84 | astro-ph/0501590(unfixable:missing_file); hep-lat/0111059(unfixable:missing_file); physics/0307021(unfixable:missing_file); 1012.1143(unfixable:missing_file); 1109.6007(unfixable:missing_file); 1109.5364(unfixable:missing_file); 0905.4371(unfixable:undefined_cs); 1206.5620(unfixable:missing_file) |
| eps_image | tectonic | 46 | 39 | 39 | cond-mat/0307744(unfixable:other); quant-ph/0111094(unfixable:other); 1003.4522(unfixable:other); 1012.1206(unfixable:other); 1012.5273(unfixable:other); 1109.5963(unfixable:other); 2403.15102(unfixable:other) |
| missing_file | tectonic | 11 | 0 | 0 | astro-ph/0501590(unfixable:missing_file); hep-lat/0111059(unfixable:missing_file); physics/0307021(unfixable:missing_file); 1012.1143(unfixable:missing_file); 1109.6007(unfixable:missing_file); 0806.4589(unfixable:other); 1109.5364(unfixable:missing_file); 1206.5620(unfixable:missing_file) |
| clean | tectonic | 3 | 0 | 0 | 1404.5668(unfixable:other); 2403.15075(unfixable:other); 2105.03798(unfixable:other) |
| latex209 | xelatex | 1 | 0 | 0 | 2211.04503(unfixable:latex209) |
| undefined_cs | xelatex | 1 | 1 | 0 | — |

## 4. 规则命中分布 (actions 计数; round=0 precheck, -1 gate)

| 规则 | xelatex | tectonic | 所在格出pdf数 |
|---|---|---|---|
| latex209_reject (gate) | 0 | 0 | 0 |
| pstricks_dvips_preflight (gate) | 0 | 0 | 0 |
| pstricks_route (precheck) | 0 | 2 | 0 |
| static_precheck (precheck) | 162 | 0 | 143 |
| install_file (loop) | 10 | 1 | 6 |
| legacy_pkg_shim (loop) | 2 | 1 | 2 |
| install_tfm (loop) | 0 | 0 | 0 |
| eps_to_pdf (loop) | 0 | 41 | 39 |
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
| revtex4.cls | 31 |
| algorithm.sty | 20 |
| revtex4-1.cls | 15 |
| ulem.sty | 13 |
| algorithmic.sty | 12 |
| algpseudocode.sty | 11 |
| epsf.sty | 10 |
| soul.sty | 8 |
| IEEEtran.cls | 6 |
| algorithm2e.sty | 5 |
| llncs.cls | 4 |
| algorithmicx.sty | 4 |
| elsarticle.cls | 4 |
| stmaryrd.sty | 4 |
| siunitx.sty | 3 |
| physics.sty | 3 |
| pstricks.sty | 2 |
| nth.sty | 2 |
| accents.sty | 2 |
| feynmp.sty | 1 |
| mhchem.sty | 1 |
| chemgreek.sty | 1 |
| ascmac.sty | 1 |
| textgreek.sty | 1 |
| tracklang.sty | 1 |
| pseudocode.sty | 1 |
| eqnarray.sty | 1 |
| listofitems.sty | 1 |
| mathdots.sty | 1 |
| auto-pst-pdf.sty | 1 |

## 5. 未救回格 (verdict 非 clean/ok~/dirty, 按终态类别聚类)

| paper | eng | verdict | 终态cat | 轮数 | log_excerpt |
|---|---|---|---|---|---|
| 0806.0904 | xelatex | reject:inject_latex209 | — | 0 |  |
| 0806.0904 | tectonic | reject:inject_latex209 | — | 0 |  |
| 0806.4589 | tectonic | unfixable:other | — | 3 | ! pdf: image inclusion failed for "diag1.1" (page=1). ! pdf: image inclusion failed for "diag1.1" (page=1). |
| 0905.4371 | xelatex | unfixable:undefined_cs | — | 2 | /home/fanghaotian/src/texlate/bench/work_fixloop_zh/0905.4371/_texmf/home/tex/latex/pstricks/pstricks.sty:242: Undefined control sequence. / |
| 0905.4371 | tectonic | reject:pstricks_route | — | 0 |  |
| 1003.4522 | tectonic | unfixable:other | — | 2 | ms.tex:271: Underfull \hbox (badness 1024) in paragraph at lines 240--271 ms.tex:271: Underfull \hbox (badness 1024) in paragraph at lines 2 |
| 1012.1143 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `aipproc.cls' not found. ! LaTeX Error: File `aipproc.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1012.1143 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `aipproc.cls' not found.. ! ! LaTeX Error: File `aipproc.cls' not found.. \@missingfileerror ...or: File `#1.#2' not f |
| 1012.1206 | tectonic | unfixable:other | — | 2 | ! LaTeX Error: Unknown float option `H'. ! LaTeX Error: Unknown float option `H'.  See the LaTeX manual or LaTeX Companion for explanation.  |
| 1012.5273 | tectonic | unfixable:other | — | 3 | ! pdf: image inclusion failed for "zeromode.pdf". ! pdf: image inclusion failed for "zeromode.pdf". |
| 1109.5364 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `slashbox.sty' not found. ! LaTeX Error: File `slashbox.sty' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 1109.5364 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `slashbox.sty' not found.. ! ! LaTeX Error: File `slashbox.sty' not found.. \@missingfileerror ...or: File `#1.#2' not |
| 1109.5963 | tectonic | unfixable:other | — | 2 | ! Package hyperref Error: Wrong DVI mode driver option `hypertex', ! Package hyperref Error: Wrong DVI mode driver option `hypertex', (hyper |
| 1109.6007 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `mn2e.cls' not found. ! LaTeX Error: File `mn2e.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1109.6007 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `mn2e.cls' not found.. ! ! LaTeX Error: File `mn2e.cls' not found.. \@missingfileerror ...or: File `#1.#2' not found.} |
| 1206.5620 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `mn2e.cls' not found. ! LaTeX Error: File `mn2e.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1206.5620 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `mn2e.cls' not found.. ! ! LaTeX Error: File `mn2e.cls' not found.. \@missingfileerror ...or: File `#1.#2' not found.} |
| 1306.2177 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `aipcheck.tex' not found. ! LaTeX Error: File `aipcheck.tex' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 1306.2177 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `aipcheck.tex' not found.. ! ! LaTeX Error: File `aipcheck.tex' not found.. \@missingfileerror ...or: File `#1.#2' not |
| 1404.5668 | tectonic | unfixable:other | — | 2 | ! pdf_link_obj(): passed invalid object. ! pdf_link_obj(): passed invalid object. |
| 1404.6180 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `svjour.cls' not found. ! LaTeX Error: File `svjour.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| 1404.6180 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `svjour.cls' not found.. ! ! LaTeX Error: File `svjour.cls' not found.. \@missingfileerror ...or: File `#1.#2' not fou |
| 1608.06693 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `svglov3.clo' not found. ! LaTeX Error: File `svglov3.clo' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1608.06693 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `svglov3.clo' not found.. ! ! LaTeX Error: File `svglov3.clo' not found.. \@missingfileerror ...or: File `#1.#2' not f |
| 1706.02568 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `epsf.tex' not found. ! LaTeX Error: File `epsf.tex' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1706.02694 | xelatex | unfixable:other | — | 3 | /home/fanghaotian/src/texlate/bench/work_fixloop_zh/1706.02694/_texmf/home/tex/latex/textgreek/textgreek.sty:39: Package textgreek Error: Ca |
| 1803.08846 | tectonic | reject:pstricks_route | — | 0 |  |
| 2105.03750 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `aastex63.cls' not found. ! LaTeX Error: File `aastex63.cls' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 2105.03798 | tectonic | unfixable:other | — | 2 | ! can't open path `linked_zotero.bib` ! can't open path `linked_zotero.bib` caused by: not found |
| 2211.04503 | xelatex | unfixable:latex209 | — | 2 | (/home/fanghaotian/src/texlate/bench/work_fixloop_zh/2211.04503/xelatex/aastex631.cls Document Class: aastex631 2020/12/20 Version 6.3.1d/AA |
| 2308.04217 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `binhex.tex' not found. ! LaTeX Error: File `binhex.tex' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| 2308.12712 | xelatex | unfixable:other | — | 2 | /usr/share/texmf-dist/tex/latex/hyperxmp/hyperxmp.sty:279: Package hyperxmp Error: hyperref must be loaded before hyperxmp. /usr/share/texmf |
| 2403.15075 | tectonic | unfixable:other | — | 2 | ! the external tool exited with an error code; its stdout was: ! the external tool exited with an error code; its stdout was:  ============= |
| 2403.15102 | tectonic | unfixable:other | — | 2 | ! Unable to load picture or PDF file 'img/sf_08_VX.pdf'. ! Unable to load picture or PDF file 'img/sf_08_VX.pdf'. <to be read again>         |
| 2410.05959 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `binhex.tex' not found. ! LaTeX Error: File `binhex.tex' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| 2410.06028 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `binhex.tex' not found. ! LaTeX Error: File `binhex.tex' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| astro-ph/0501590 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `espcrc2.sty' not found. ! LaTeX Error: File `espcrc2.sty' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| astro-ph/0501590 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `espcrc2.sty' not found.. ! ! LaTeX Error: File `espcrc2.sty' not found.. \@missingfileerror ...or: File `#1.#2' not f |
| astro-ph/0605290 | tectonic | unfixable:other | — | 3 | s5308.tex:1245: Underfull \vbox (badness 10000) has occurred while \output is active s5308.tex:1245: Underfull \vbox (badness 10000) has occ |
| astro-ph/9703134 | xelatex | reject:inject_latex209 | — | 0 |  |
| astro-ph/9703134 | tectonic | reject:inject_latex209 | — | 0 |  |
| astro-ph/9703198 | xelatex | reject:inject_latex209 | — | 0 |  |
| astro-ph/9703198 | tectonic | reject:inject_latex209 | — | 0 |  |
| astro-ph/9910044 | xelatex | reject:inject_latex209 | — | 0 |  |
| astro-ph/9910044 | tectonic | reject:inject_latex209 | — | 0 |  |
| cond-mat/0111097 | xelatex | reject:inject_latex209 | — | 0 |  |
| cond-mat/0111097 | tectonic | reject:inject_latex209 | — | 0 |  |
| cond-mat/0307744 | tectonic | unfixable:other | — | 3 | ! Text line contains an invalid character. ! Text line contains an invalid character. <read 2> x^^9c^^9d\»®m¹q��W^^9cp^^T                    |
| cond-mat/9703223 | xelatex | reject:inject_latex209 | — | 0 |  |
| cond-mat/9703223 | tectonic | reject:inject_latex209 | — | 0 |  |
| cond-mat/9910214 | xelatex | reject:inject_latex209 | — | 0 |  |
| cond-mat/9910214 | tectonic | reject:inject_latex209 | — | 0 |  |
| hep-lat/0111059 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `elsart.cls' not found. ! LaTeX Error: File `elsart.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| hep-lat/0111059 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `elsart.cls' not found.. ! ! LaTeX Error: File `elsart.cls' not found.. \@missingfileerror ...or: File `#1.#2' not fou |
| hep-ph/9703402 | xelatex | reject:inject_latex209 | — | 0 |  |
| hep-ph/9703402 | tectonic | reject:inject_latex209 | — | 0 |  |
| hep-ph/9910373 | xelatex | reject:inject_latex209 | — | 0 |  |
| hep-ph/9910373 | tectonic | reject:inject_latex209 | — | 0 |  |
| hep-th/9703099 | xelatex | reject:inject_latex209 | — | 0 |  |
| hep-th/9703099 | tectonic | reject:inject_latex209 | — | 0 |  |
| hep-th/9703173 | xelatex | reject:inject_latex209 | — | 0 |  |
| hep-th/9703173 | tectonic | reject:inject_latex209 | — | 0 |  |
| nucl-th/0111058 | xelatex | reject:inject_latex209 | — | 0 |  |
| nucl-th/0111058 | tectonic | reject:inject_latex209 | — | 0 |  |
| physics/0307021 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `tcilatex.tex' not found. ! LaTeX Error: File `tcilatex.tex' not found.  Type X to quit or <RETURN> to proceed, or enter |
| physics/0307021 | tectonic | unfixable:missing_file | — | 2 | ! ! LaTeX Error: File `tcilatex.tex' not found.. ! ! LaTeX Error: File `tcilatex.tex' not found.. \@missingfileerror ...or: File `#1.#2' not |
| q-alg/9703046 | xelatex | reject:inject_latex209 | — | 0 |  |
| q-alg/9703046 | tectonic | reject:inject_latex209 | — | 0 |  |
| quant-ph/0111094 | tectonic | unfixable:other | — | 2 | ! pdf: image inclusion failed for "interfr1.1" (page=1). ! pdf: image inclusion failed for "interfr1.1" (page=1). |

## 6. 回归 (baseline 已出 pdf → fixloop 反而无 pdf)

| paper | eng | baseline | fixloop verdict |
|---|---|---|---|
| astro-ph/0605290 | tectonic | pdf~ | unfixable:other |
| 0905.4371 | tectonic | pdf~ | reject:pstricks_route |
| 1803.08846 | tectonic | clean | reject:pstricks_route |

## 7. 逐格明细

| paper | band | tags | route | xel: base→fix(轮/装包) | tec: base→fix |
|---|---|---|---|---|---|
| 0707.1511 | b | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | FAIL→clean 2r/0i |
| 0707.2125 | b | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 0707.2833 | b | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| 0707.3950 | b | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 0707.4363 | b | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/1i | FAIL→clean 2r/0i |
| 0707.4451 | b | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 0806.0904 | b | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| 0806.4589 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→unfixable:other 3r/1i |
| 0905.4208 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 0905.4371 | b | — | xelatex/tectonic | FAIL→unfixable:undefined_cs 2r/1i | pdf~→reject:pstricks_route 0r/0i |
| 1003.1735 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 1003.1906 | b | — | xelatex/tectonic | clean→best_effort_pdf 2r/0i | clean→acceptable_pdf 1r/0i |
| 1003.2091 | b | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| 1003.4522 | b | — | xelatex/tectonic | FAIL→clean 3r/2i | FAIL→unfixable:other 2r/0i |
| 1003.5338 | b | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1003.5495 | b | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| 1003.5531 | b | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1003.5546 | b | — | xelatex/tectonic | FAIL→acceptable_pdf 4r/2i | FAIL→clean 2r/0i |
| 1012.1124 | b | — | xelatex/tectonic | pdf~→clean 1r/1i | pdf~→clean 1r/0i |
| 1012.1143 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | FAIL→unfixable:missing_file 2r/0i |
| 1012.1177 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1012.1206 | b | — | xelatex/tectonic | clean→acceptable_pdf 1r/0i | FAIL→unfixable:other 2r/0i |
| 1012.1740 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 1012.5086 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 1012.5145 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1012.5273 | b | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→unfixable:other 3r/0i |
| 1012.5491 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1109.1664 | b | — | xelatex/tectonic | clean→clean 1r/1i | clean→clean 1r/0i |
| 1109.1801 | b | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/4i | pdf~→acceptable_pdf 1r/0i |
| 1109.2059 | b | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1109.5364 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/1i | FAIL→unfixable:missing_file 2r/0i |
| 1109.5682 | b | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1109.5931 | b | — | xelatex/tectonic | FAIL→best_effort_pdf 2r/2i | pdf~→acceptable_pdf 1r/0i |
| 1109.5963 | b | — | xelatex/tectonic | FAIL→best_effort_pdf 2r/1i | FAIL→unfixable:other 2r/0i |
| 1109.6007 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | FAIL→unfixable:missing_file 2r/0i |
| 1206.1653 | c | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | pdf~→acceptable_pdf 1r/0i |
| 1206.1808 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1206.1993 | c | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/1i | pdf~→acceptable_pdf 1r/0i |
| 1206.5375 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1206.5620 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | FAIL→unfixable:missing_file 2r/0i |
| 1206.5628 | c | — | xelatex/tectonic | FAIL→best_effort_pdf 2r/1i | pdf~→acceptable_pdf 1r/0i |
| 1206.5796 | c | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1206.5832 | c | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1306.2177 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | FAIL→unfixable:missing_file 2r/0i |
| 1306.2183 | c | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 1306.5749 | c | — | xelatex/tectonic | FAIL→clean 1r/2i | clean→clean 1r/0i |
| 1306.6147 | c | — | xelatex/tectonic | FAIL→clean 1r/2i | FAIL→clean 2r/0i |
| 1306.6222 | c | — | xelatex/tectonic | FAIL→clean 1r/2i | FAIL→clean 2r/0i |
| 1404.2112 | c | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| 1404.2164 | c | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| 1404.2362 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1404.5668 | c | — | xelatex/tectonic | pdf~→clean 1r/0i | FAIL→unfixable:other 2r/0i |
| 1404.5685 | c | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→acceptable_pdf 2r/0i |
| 1404.6154 | c | — | xelatex/tectonic | FAIL→clean 2r/2i | clean→clean 1r/0i |
| 1404.6180 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | FAIL→unfixable:missing_file 2r/0i |
| 1502.02155 | c | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/3i | pdf~→acceptable_pdf 1r/0i |
| 1502.02285 | c | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 1502.06096 | c | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | pdf~→acceptable_pdf 1r/0i |
| 1502.06131 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1502.06256 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1502.06459 | c | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 1502.06541 | c | — | xelatex/tectonic | pdf~→acceptable_pdf 1r/0i | pdf~→dirty_pdf 1r/0i |
| 1511.06628 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1608.02354 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1608.02550 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1608.02645 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1608.02651 | c | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1608.06693 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | FAIL→unfixable:missing_file 2r/0i |
| 1608.06769 | c | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | pdf~→acceptable_pdf 1r/0i |
| 1608.07013 | c | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | FAIL→clean 2r/0i |
| 1608.07066 | c | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→acceptable_pdf 1r/0i |
| 1706.02550 | d | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1706.02567 | d | — | xelatex/tectonic | FAIL→clean 1r/1i | pdf~→acceptable_pdf 1r/0i |
| 1706.02568 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | clean→clean 1r/0i |
| 1706.02657 | d | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| 1706.02671 | d | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 1706.02694 | d | — | xelatex/tectonic | FAIL→unfixable:other 3r/3i | pdf~→clean 1r/0i |
| 1706.02695 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/3i | pdf~→acceptable_pdf 1r/0i |
| 1706.07493 | d | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1706.07613 | d | — | xelatex/tectonic | FAIL→clean 1r/2i | clean→clean 1r/0i |
| 1803.02897 | d | — | xelatex/tectonic | FAIL→clean 1r/2i | clean→acceptable_pdf 1r/0i |
| 1803.02918 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/4i | pdf~→acceptable_pdf 1r/0i |
| 1803.02994 | d | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 1803.03110 | d | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1803.03235 | d | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 1803.03249 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | pdf~→acceptable_pdf 1r/0i |
| 1803.08846 | d | — | xelatex/tectonic | clean→clean 1r/3i | clean→reject:pstricks_route 0r/0i |
| 1811.03615 | d | — | xelatex/tectonic | FAIL→clean 2r/2i | pdf~→acceptable_pdf 1r/0i |
| 1811.03619 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/4i | pdf~→acceptable_pdf 1r/0i |
| 1811.03624 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/1i | clean→clean 1r/0i |
| 1811.10012 | d | — | xelatex/tectonic | FAIL→clean 1r/3i | FAIL→clean 2r/0i |
| 1811.10029 | d | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 1811.10050 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | FAIL→acceptable_pdf 2r/0i |
| 1811.10148 | d | — | xelatex/tectonic | clean→clean 1r/1i | FAIL→clean 2r/0i |
| 1907.03602 | d | — | xelatex/tectonic | FAIL→clean 1r/2i | clean→clean 1r/0i |
| 1907.03821 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/3i | pdf~→acceptable_pdf 1r/0i |
| 1907.03868 | d | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 2003.03387 | d | — | xelatex/tectonic | FAIL→clean 1r/1i | pdf~→dirty_pdf 1r/0i |
| 2003.03479 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/3i | pdf~→acceptable_pdf 1r/0i |
| 2003.03510 | d | — | xelatex/tectonic | clean→clean 1r/2i | pdf~→acceptable_pdf 1r/0i |
| 2003.10723 | d | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| 2009.03673 | d | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| 2009.03686 | d | — | xelatex/tectonic | FAIL→clean 1r/2i | clean→clean 1r/0i |
| 2009.03699 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | pdf~→acceptable_pdf 1r/0i |
| 2009.03736 | d | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | pdf~→acceptable_pdf 1r/0i |
| 2009.10977 | d | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 2105.03750 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | clean→clean 1r/0i |
| 2105.03798 | e | — | xelatex/tectonic | FAIL→clean 1r/2i | FAIL→unfixable:other 2r/0i |
| 2105.03943 | e | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 2105.11393 | e | — | xelatex/tectonic | FAIL→clean 1r/2i | clean→clean 1r/0i |
| 2203.04298 | e | — | xelatex/tectonic | clean→clean 1r/0i | pdf~→acceptable_pdf 1r/0i |
| 2203.12999 | e | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 2203.13055 | e | — | xelatex/tectonic | FAIL→best_effort_pdf 2r/3i | clean→acceptable_pdf 1r/0i |
| 2203.13064 | e | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 2203.13079 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/3i | pdf~→acceptable_pdf 1r/0i |
| 2211.04450 | e | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 2211.04453 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/6i | pdf~→acceptable_pdf 1r/0i |
| 2211.04457 | e | — | xelatex/tectonic | FAIL→clean 1r/3i | pdf~→acceptable_pdf 1r/0i |
| 2211.04503 | e | — | xelatex/tectonic | FAIL→unfixable:latex209 2r/4i | pdf~→acceptable_pdf 1r/0i |
| 2211.04515 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | pdf~→acceptable_pdf 1r/0i |
| 2211.12986 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | FAIL→acceptable_pdf 2r/0i |
| 2308.04174 | e | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 2308.04188 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/1i | pdf~→acceptable_pdf 1r/0i |
| 2308.04212 | e | — | xelatex/tectonic | FAIL→best_effort_pdf 2r/5i | pdf~→acceptable_pdf 1r/0i |
| 2308.04217 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | pdf~→acceptable_pdf 1r/0i |
| 2308.04280 | e | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 2308.12610 | e | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| 2308.12712 | e | — | xelatex/tectonic | FAIL→unfixable:other 2r/1i | clean→acceptable_pdf 1r/0i |
| 2403.05454 | e | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 2403.05463 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/4i | pdf~→acceptable_pdf 1r/0i |
| 2403.05475 | e | — | xelatex/tectonic | clean→best_effort_pdf 2r/0i | clean→clean 1r/0i |
| 2403.05550 | e | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 2403.15075 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/2i | FAIL→unfixable:other 2r/0i |
| 2403.15096 | e | — | xelatex/tectonic | pdf~→clean 1r/0i | pdf~→clean 1r/0i |
| 2403.15102 | e | — | xelatex/tectonic | clean→clean 1r/1i | FAIL→unfixable:other 2r/0i |
| 2403.15126 | e | — | xelatex/tectonic | FAIL→clean 1r/1i | clean→clean 1r/0i |
| 2403.15129 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/3i | pdf~→acceptable_pdf 1r/0i |
| 2403.15170 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 1r/1i | pdf~→acceptable_pdf 1r/0i |
| 2410.05959 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | FAIL→clean 2r/0i |
| 2410.06028 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | clean→acceptable_pdf 1r/0i |
| 2410.17992 | e | — | xelatex/tectonic | FAIL→acceptable_pdf 2r/8i | pdf~→acceptable_pdf 1r/0i |
| astro-ph/0501439 | a | — | xelatex/tectonic | FAIL→clean 3r/2i | FAIL→clean 2r/0i |
| astro-ph/0501590 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | FAIL→unfixable:missing_file 2r/0i |
| astro-ph/0605290 | a | — | xelatex/tectonic | FAIL→clean 2r/0i | pdf~→unfixable:other 3r/0i |
| astro-ph/0605361 | a | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| astro-ph/9703134 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| astro-ph/9703198 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| astro-ph/9910044 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| cond-mat/0111097 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| cond-mat/0307578 | a | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| cond-mat/0307744 | a | — | xelatex/tectonic | FAIL→clean 1r/2i | FAIL→unfixable:other 3r/0i |
| cond-mat/0501109 | a | — | xelatex/tectonic | pdf~→clean 1r/0i | FAIL→clean 2r/0i |
| cond-mat/0605032 | a | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| cond-mat/9703223 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| cond-mat/9910214 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| cs/0307009 | a | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| hep-lat/0111059 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i | FAIL→unfixable:missing_file 2r/0i |
| hep-ph/0111245 | a | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| hep-ph/0605178 | a | — | xelatex/tectonic | FAIL→clean 1r/2i | clean→clean 1r/0i |
| hep-ph/9703402 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| hep-ph/9910373 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| hep-ph/9910443 | a | — | xelatex/tectonic | pdf~→clean 1r/0i | pdf~→clean 1r/0i |
| hep-th/0501161 | a | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| hep-th/9703099 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| hep-th/9703173 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| math/0307077 | a | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| math/0307301 | a | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| math/0501060 | a | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→clean 2r/0i |
| math/0605628 | a | — | xelatex/tectonic | clean→clean 1r/0i | clean→clean 1r/0i |
| nucl-th/0111058 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| physics/0307021 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/1i | FAIL→unfixable:missing_file 2r/0i |
| physics/0605206 | a | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |
| q-alg/9703046 | a | — | xelatex/tectonic | reject→reject:inject_latex209 0r/0i | reject→reject:inject_latex209 0r/0i |
| quant-ph/0111094 | a | — | xelatex/tectonic | clean→clean 1r/0i | FAIL→unfixable:other 2r/0i |
| quant-ph/0605205 | a | — | xelatex/tectonic | FAIL→clean 1r/1i | FAIL→clean 2r/0i |

