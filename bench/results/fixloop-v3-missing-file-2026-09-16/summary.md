# fixloop bench — corpus_v2 40 篇无偏样本 × 产品化规则库

- 日期: 2026-09-16 01:10
- 规则库: `/home/fanghaotian/src/texlate/src/texlate/compile/fixloop/rules.yaml` (31 规则, max_rounds=8)
- 口径: 每篇独立冷 `_texmf` usertree (xelatex) / pin bundle+ctan_fetch (tectonic); 无 sandbox-exec; fixloop 直跑 (无 normalize/inject 前置)
- 对照: baseline = compilebench-corpusv2 同批样本原文直编 (clean/pdf~/FAIL)

## 1. 总救回率

| 引擎 | n | baseline clean/pdf~/FAIL | fixloop clean/ok~/dirty/fail/rej | FAIL→pdf | FAIL→clean层 |
|---|---|---|---|---|---|
| xelatex | 111 | 0/1/110 | 2/0/1/101/7 | 2/110 | 2/110 |

**union (任一引擎)**: baseline pdf 1/111 → fixloop pdf 3/111, clean层 2/111

## 2. baseline → fixloop 转移矩阵

### xelatex

| baseline \ fixloop | clean | ok~ | pdf~ | fail | reject |
|---|---|---|---|---|---|
| pdf~ (1) | 0 | 0 | 1 | 0 | 0 |
| FAIL (110) | 2 | 0 | 0 | 101 | 7 |

## 3. baseline 失败类别 × 救回 (仅 baseline=FAIL 格)

| 类别 | 引擎 | 格数 | 出pdf | clean层 | 未救回 paper (终态类别) |
|---|---|---|---|---|---|
| missing_file | xelatex | 110 | 2 | 2 | astro-ph/9703198(missing_file); cond-mat/0307578(unfixable:missing_file); astro-ph/0501439(unfixable:missing_file); astro-ph/0501590(unfixable:missing_file); astro-ph/9910044(missing_file); cond-mat/9910214(missing_file); astro-ph/9703134(missing_file); hep-ph/0111245(unfixable:missing_file) |

## 4. 规则命中分布 (actions 计数; round=0 precheck, -1 gate)

| 规则 | xelatex | tectonic | 所在格出pdf数 |
|---|---|---|---|
| latex209_reject (gate) | 0 | 0 | 0 |
| pstricks_dvips_preflight (gate) | 0 | 0 | 0 |
| pstricks_route (precheck) | 0 | 0 | 0 |
| static_precheck (precheck) | 111 | 0 | 3 |
| install_file (loop) | 0 | 0 | 0 |
| legacy_pkg_shim (loop) | 2 | 0 | 1 |
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
| inputenc_strip (loop) | 2 | 0 | 0 |
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
| revtex4.cls | 1 |

## 5. 未救回格 (verdict 非 clean/ok~/dirty, 按终态类别聚类)

| paper | eng | verdict | 终态cat | 轮数 | log_excerpt |
|---|---|---|---|---|---|
| 0707.1511 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `ulem.sty' not found. ! LaTeX Error: File `ulem.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 0707.4363 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 0806.0904 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `epsf.sty' not found. ! LaTeX Error: File `epsf.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 0806.4589 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `feynmp.sty' not found. ! LaTeX Error: File `feynmp.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| 0905.4208 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 0905.4371 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `pstricks.sty' not found. ! LaTeX Error: File `pstricks.sty' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 1003.1735 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1003.4522 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1003.5546 | xelatex | unfixable:missing_file | — | 3 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1012.1143 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `aipproc.cls' not found. ! LaTeX Error: File `aipproc.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1012.1177 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `epsf.sty' not found. ! LaTeX Error: File `epsf.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1012.1740 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1012.5086 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1012.5145 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1012.5491 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1109.1801 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `IEEEtran.cls' not found. ! LaTeX Error: File `IEEEtran.cls' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 1109.2059 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1109.5364 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1109.5931 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm.sty' not found. ! LaTeX Error: File `algorithm.sty' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1109.5963 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1109.6007 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `mn2e.cls' not found. ! LaTeX Error: File `mn2e.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1206.1653 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `IEEEtran.cls' not found. ! LaTeX Error: File `IEEEtran.cls' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 1206.1993 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `llncs.cls' not found. ! LaTeX Error: File `llncs.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new n |
| 1206.5620 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `mn2e.cls' not found. ! LaTeX Error: File `mn2e.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1206.5628 | xelatex | unfixable:other | — | 3 | /usr/share/texmf-dist/tex/generic/babel/babel.sty:4330: Package babel Error: Unknown option 'french'. /usr/share/texmf-dist/tex/generic/babe |
| 1206.5796 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1206.5832 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1306.2177 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `aipcheck.tex' not found. ! LaTeX Error: File `aipcheck.tex' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 1306.2183 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1306.5749 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1306.6147 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1306.6222 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `elsarticle.cls' not found. ! LaTeX Error: File `elsarticle.cls' not found.  Type X to quit or <RETURN> to proceed, or e |
| 1404.5685 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1404.6154 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `mhchem.sty' not found. ! LaTeX Error: File `mhchem.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| 1404.6180 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `svjour.cls' not found. ! LaTeX Error: File `svjour.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| 1502.02155 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm.sty' not found. ! LaTeX Error: File `algorithm.sty' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1502.02285 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1502.06096 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm.sty' not found. ! LaTeX Error: File `algorithm.sty' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1502.06459 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1608.06693 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `svglov3.clo' not found. ! LaTeX Error: File `svglov3.clo' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1608.06769 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithmic.sty' not found. ! LaTeX Error: File `algorithmic.sty' not found.  Type X to quit or <RETURN> to proceed, or |
| 1608.07013 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1608.07066 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `ulem.sty' not found. ! LaTeX Error: File `ulem.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1706.02550 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1706.02567 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `elsarticle.cls' not found. ! LaTeX Error: File `elsarticle.cls' not found.  Type X to quit or <RETURN> to proceed, or e |
| 1706.02568 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `epsf.tex' not found. ! LaTeX Error: File `epsf.tex' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1706.02657 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1706.02671 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `mathdots.sty' not found. ! LaTeX Error: File `mathdots.sty' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 1706.02694 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `tracklang.sty' not found. ! LaTeX Error: File `tracklang.sty' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1706.02695 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `IEEEtran.cls' not found. ! LaTeX Error: File `IEEEtran.cls' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 1706.07613 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `IEEEtran.cls' not found. ! LaTeX Error: File `IEEEtran.cls' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 1803.02897 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1803.02994 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `soul.sty' not found. ! LaTeX Error: File `soul.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1803.03235 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1803.03249 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm.sty' not found. ! LaTeX Error: File `algorithm.sty' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1811.03615 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1811.03624 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1811.10012 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1811.10050 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm.sty' not found. ! LaTeX Error: File `algorithm.sty' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 1907.03602 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 1907.03821 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `soul.sty' not found. ! LaTeX Error: File `soul.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 1907.03868 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `llncs.cls' not found. ! LaTeX Error: File `llncs.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new n |
| 2003.03387 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 2009.03686 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 2009.03699 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `eqnarray.sty' not found. ! LaTeX Error: File `eqnarray.sty' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 2009.03736 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm.sty' not found. ! LaTeX Error: File `algorithm.sty' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 2009.10977 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `soul.sty' not found. ! LaTeX Error: File `soul.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 2105.03750 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `aastex63.cls' not found. ! LaTeX Error: File `aastex63.cls' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 2105.11393 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 2203.13055 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `nth.sty' not found. ! LaTeX Error: File `nth.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new name. |
| 2203.13079 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm.sty' not found. ! LaTeX Error: File `algorithm.sty' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 2211.04450 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `delimset.sty' not found. ! LaTeX Error: File `delimset.sty' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 2211.04453 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `elsarticle.cls' not found. ! LaTeX Error: File `elsarticle.cls' not found.  Type X to quit or <RETURN> to proceed, or e |
| 2211.04457 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-2.cls' not found. ! LaTeX Error: File `revtex4-2.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 2211.04515 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm2e.sty' not found. ! LaTeX Error: File `algorithm2e.sty' not found.  Type X to quit or <RETURN> to proceed, or |
| 2211.12986 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm2e.sty' not found. ! LaTeX Error: File `algorithm2e.sty' not found.  Type X to quit or <RETURN> to proceed, or |
| 2308.04174 | xelatex | unfixable:missing_file | — | 3 | ! LaTeX Error: File `accents.sty' not found. ! LaTeX Error: File `accents.sty' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| 2308.04188 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithmic.sty' not found. ! LaTeX Error: File `algorithmic.sty' not found.  Type X to quit or <RETURN> to proceed, or |
| 2308.04217 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `binhex.tex' not found. ! LaTeX Error: File `binhex.tex' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| 2308.04280 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4-1.cls' not found. ! LaTeX Error: File `revtex4-1.cls' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 2308.12712 | xelatex | unfixable:other | — | 2 | /usr/share/texmf-dist/tex/latex/hyperxmp/hyperxmp.sty:279: Package hyperxmp Error: hyperref must be loaded before hyperxmp. /usr/share/texmf |
| 2403.05454 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `stmaryrd.sty' not found. ! LaTeX Error: File `stmaryrd.sty' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 2403.05463 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `stmaryrd.sty' not found. ! LaTeX Error: File `stmaryrd.sty' not found.  Type X to quit or <RETURN> to proceed, or enter |
| 2403.05550 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `elsarticle.cls' not found. ! LaTeX Error: File `elsarticle.cls' not found.  Type X to quit or <RETURN> to proceed, or e |
| 2403.15075 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithmic.sty' not found. ! LaTeX Error: File `algorithmic.sty' not found.  Type X to quit or <RETURN> to proceed, or |
| 2403.15126 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `ulem.sty' not found. ! LaTeX Error: File `ulem.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| 2403.15129 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithm.sty' not found. ! LaTeX Error: File `algorithm.sty' not found.  Type X to quit or <RETURN> to proceed, or ent |
| 2403.15170 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `algorithmic.sty' not found. ! LaTeX Error: File `algorithmic.sty' not found.  Type X to quit or <RETURN> to proceed, or |
| 2410.05959 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `binhex.tex' not found. ! LaTeX Error: File `binhex.tex' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| 2410.06028 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `binhex.tex' not found. ! LaTeX Error: File `binhex.tex' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| 2410.17992 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `quantumarticle.cls' not found. ! LaTeX Error: File `quantumarticle.cls' not found.  Type X to quit or <RETURN> to proce |
| astro-ph/0501439 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| astro-ph/0501590 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `espcrc2.sty' not found. ! LaTeX Error: File `espcrc2.sty' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| cond-mat/0307578 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| hep-lat/0111059 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `elsart.cls' not found. ! LaTeX Error: File `elsart.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| hep-ph/0111245 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `epsf.sty' not found. ! LaTeX Error: File `epsf.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| hep-ph/0605178 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| math/0307077 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `epsf.sty' not found. ! LaTeX Error: File `epsf.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new nam |
| physics/0307021 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| physics/0605206 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| quant-ph/0605205 | xelatex | unfixable:missing_file | — | 2 | ! LaTeX Error: File `revtex4.cls' not found. ! LaTeX Error: File `revtex4.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| astro-ph/9703134 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `aaspp4.sty' not found. ! LaTeX Error: File `aaspp4.sty' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| astro-ph/9703198 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `crckapb.cls' not found. ! LaTeX Error: File `crckapb.cls' not found.  Type X to quit or <RETURN> to proceed, or enter n |
| astro-ph/9910044 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `laa.cls' not found. ! LaTeX Error: File `laa.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new name. |
| cond-mat/9910214 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| hep-ph/9910373 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| hep-th/9703173 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |
| nucl-th/0111058 | xelatex | reject:latex209_reject | missing_file | 1 | ! LaTeX Error: File `revtex.cls' not found. ! LaTeX Error: File `revtex.cls' not found.  Type X to quit or <RETURN> to proceed, or enter new |

## 6. 回归 (baseline 已出 pdf → fixloop 反而无 pdf)

无。

## 7. 逐格明细

| paper | band | tags | route | xel: base→fix(轮/装包) | tec: base→fix |
|---|---|---|---|---|---|
| 0707.1511 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 0707.4363 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 0806.0904 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 0806.4589 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 0905.4208 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 0905.4371 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1003.1735 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1003.1906 | b | — | xelatex/tectonic | pdf~→best_effort_pdf 2r/0i |
| 1003.4522 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1003.5546 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 3r/0i |
| 1012.1143 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1012.1177 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1012.1740 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1012.5086 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1012.5145 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1012.5491 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1109.1801 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1109.2059 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1109.5364 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1109.5931 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1109.5963 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1109.6007 | b | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1206.1653 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1206.1993 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1206.5620 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1206.5628 | c | — | xelatex/tectonic | FAIL→unfixable:other 3r/0i |
| 1206.5796 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1206.5832 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1306.2177 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1306.2183 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1306.5749 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1306.6147 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1306.6222 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1404.5685 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1404.6154 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1404.6180 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1502.02155 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1502.02285 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1502.06096 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1502.06459 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1608.06693 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1608.06769 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1608.07013 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1608.07066 | c | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1706.02550 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1706.02567 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1706.02568 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1706.02657 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1706.02671 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1706.02694 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1706.02695 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1706.07613 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1803.02897 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1803.02994 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1803.03235 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1803.03249 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1811.03615 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1811.03624 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1811.10012 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1811.10050 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1907.03602 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1907.03821 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 1907.03868 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2003.03387 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2009.03686 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2009.03699 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2009.03736 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2009.10977 | d | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2105.03750 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2105.11393 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2203.13055 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2203.13079 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2211.04450 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2211.04453 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2211.04457 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2211.04515 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2211.12986 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2308.04174 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 3r/0i |
| 2308.04188 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2308.04217 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2308.04280 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2308.12712 | e | — | xelatex/tectonic | FAIL→unfixable:other 2r/0i |
| 2403.05454 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2403.05463 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2403.05550 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2403.15075 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2403.15126 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2403.15129 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2403.15170 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2410.05959 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2410.06028 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| 2410.17992 | e | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| astro-ph/0501439 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| astro-ph/0501590 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| astro-ph/0605290 | a | — | xelatex/tectonic | FAIL→clean 2r/0i |
| astro-ph/9703134 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i |
| astro-ph/9703198 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i |
| astro-ph/9910044 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i |
| cond-mat/0307578 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| cond-mat/0307744 | a | — | xelatex/tectonic | FAIL→clean 1r/2i |
| cond-mat/9910214 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i |
| hep-lat/0111059 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| hep-ph/0111245 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| hep-ph/0605178 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| hep-ph/9910373 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i |
| hep-th/9703173 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i |
| math/0307077 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| nucl-th/0111058 | a | — | xelatex/tectonic | FAIL→reject:latex209_reject 1r/0i |
| physics/0307021 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| physics/0605206 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |
| quant-ph/0605205 | a | — | xelatex/tectonic | FAIL→unfixable:missing_file 2r/0i |

