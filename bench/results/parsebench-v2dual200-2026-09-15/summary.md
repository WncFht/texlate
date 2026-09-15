# parsebench summary — corpus_v3

- papers: 170   files (.tex): 214   wall: 21.9s
- parse ok: **214/214** (100.0%)   errors: 0   measure_errors: 0
- identity: strict **214** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **1/21351** chunks = 0.00%   hits={'dollar': 1}
- chunk chars: median 194   p90 830
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 0
- scan/validate warnings: {'unclosed_env': 22, 'stray_end': 27, 'def_parse_fail': 78, 'missing_input': 10, 'unpaired_dollar': 2}
- flatten coverage: 203 reached / 4 orphan tex / 7 rootless   (触及率 98.1%)

## funnel

| stage | n |
|---|---|
| fetched (manifest rows) | 1000 |
| source ok | 1000 |
| papers discovered | 170 |
| .tex files | 214 |
| rooted papers | 168 (multi_doc 0, rootless 2) |
| parse ok | 214 |
| identity | strict 214 / normalized 0 / diverged 0 |
| translatable chunks | 21351 |
| leaked chunks | 1 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 0 |
| flatten reached / orphan / rootless | 203 / 4 / 7 |

## gates (docs/09 §8)

| gate | value | 门槛 | verdict |
|---|---|---|---|
| parse ok (file) | 100.0% CI [98.24, 100.00] | 100% & Wilson lb ≥99.5% | PASS(low-n) |
| strict identity | 100.00% CI [98.24, 100.00] | ≥99.5% | PASS |
| leak rate (chunk) | 0.000% CI [0.001, 0.027] | ≤0.15% | PASS |
| dead/orphan | 0 (chunk 0 + protect 0 + orphan 0) | =0 | PASS |
| flatten coverage | 98.1% (203/207) | ≥99% † | BELOW |

† coverage 口径勘误 (docs/09 §8 表下): orphan 大头是 e-print 内未被主文件 \input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; v3 实测 ~93%.

## v1 vs v2 — segmenter.parse_tex_v2

| 指标 | v1 (scanner) | v2 (segmenter) |
|---|---|---|
| parse ok | 214/214 | 214/214 |
| identity strict/normalized/diverged | 214/0/0 | 214/0/0 |
| translatable chunks | 21351 | 22101 |
| leaked chunks | 1 | 3396 |
| Σ chunks | 21351 | 22101 |
| Σ placeholders | 134429 | 125014 |
| wall ms p50 / p95 | 9 / 42 | 41 / 153 |
| vtex_vs_src 展开足迹 | — | strict 214 / normalized 0 / diverged 0 |
| v2 warn_kinds | — | {'dead_ph': 4501, 'missing_input': 9, 'unpaired_dollar': 3, 'def_parse_fail': 2, 'unclosed_env': 1} |

### v1↔v2 差异文件 (182/214)

| file | v1 id | v2 id | chunks | leaked | ms | vtex_vs_src | flags |
|---|---|---|---|---|---|---|---|
| 0707.0005/extracted/main.tex | strict | strict | 167→119 | 0→45 | 26.7→92.7 | strict | chunks,leak |
| 0707.0476/extracted/fpc_arxiv.tex | strict | strict | 118→118 | 0→13 | 14.4→81.1 | strict | leak |
| 0707.0687/extracted/Gai_Vico_Equense07.tex | strict | strict | 44→37 | 0→1 | 3.2→17.2 | strict | chunks,leak |
| 0707.0795/extracted/main.tex | strict | strict | 144→221 | 0→74 | 17.9→59.3 | strict | chunks,leak |
| 0707.1255/extracted/Athron_Peter.tex | strict | strict | 35→28 | 0→1 | 3.2→13.4 | strict | chunks,leak |
| 0707.1345/extracted/fcalura_accept.tex | strict | strict | 43→39 | 0→2 | 13.4→94.2 | strict | chunks,leak |
| 0707.1511/extracted/amalgam_final.tex | strict | strict | 89→70 | 0→22 | 9.6→43.2 | strict | chunks,leak |
| 0707.1626/extracted/main.tex | strict | strict | 134→149 | 0→59 | 26.2→69.2 | strict | chunks,leak |
| 0707.1778/extracted/preprint.tex | strict | strict | 91→94 | 0→4 | 10.1→52.6 | strict | chunks,leak |
| 0707.2108/extracted/pmeyerxi.TEX | strict | strict | 696→737 | 0→108 | 103.1→247.3 | strict | chunks,leak |
| 0707.2125/extracted/main.tex | strict | strict | 147→161 | 0→26 | 15.4→48.1 | strict | chunks,leak |
| 0707.2152/extracted/paper.tex | strict | strict | 55→53 | 0→3 | 4.3→20.7 | strict | chunks,leak |
| 0707.2234/extracted/brownian-revised.tex | strict | strict | 117→163 | 0→48 | 22.0→93.4 | strict | chunks,leak |
| 0707.2318/extracted/MPhilThesis.tex | strict | strict | 305→327 | 0→4 | 41.5→97.9 | strict | chunks,leak |
| 0707.2680/extracted/migliori.tex | strict | strict | 21→9 | 0→3 | 4.1→14.4 | strict | chunks,leak |
| 0707.2833/extracted/Iftomm_Chablat_Wenger_Merlet.tex | strict | strict | 93→82 | 0→11 | 10.2→37.2 | strict | chunks,leak |
| 0707.2833/extracted/macros.tex | strict | strict | 1→0 | 0→0 | 1.4→2.4 | strict | chunks |
| 0707.2897/extracted/form_factors_v3.tex | strict | strict | 168→158 | 0→17 | 17.4→73.5 | strict | chunks,leak |
| 0707.2951/extracted/ms.tex | strict | strict | 82→84 | 0→4 | 10.6→64.5 | strict | chunks,leak |
| 0707.3086/extracted/main.tex | strict | strict | 46→45 | 0→2 | 4.9→24.7 | strict | chunks,leak |
| 0707.3223/extracted/ms.tex | strict | strict | 26→16 | 0→0 | 5.5→31.8 | strict | chunks |
| 0707.3247/extracted/Revised2.tex | strict | strict | 84→95 | 0→3 | 7.3→29.3 | strict | chunks,leak |
| 0707.3283/extracted/manus.tex | strict | strict | 41→45 | 0→1 | 6.0→27.2 | strict | chunks,leak |
| 0707.3379/extracted/Schildknecht_Dieter.tex | strict | strict | 16→19 | 0→10 | 2.9→13.2 | strict | chunks,leak |
| 0707.3434/extracted/rotation10.tex | strict | strict | 93→118 | 0→3 | 18.8→76.1 | strict | chunks,leak |
| 0707.3889/extracted/khiTxenon-v0-HAL.tex | strict | strict | 246→295 | 0→2 | 51.6→180.5 | strict | chunks,leak |
| 0707.3950/extracted/main.tex | strict | strict | 85→106 | 0→20 | 7.5→24.6 | strict | chunks,leak |
| 0707.4134/extracted/article.tex | strict | strict | 92→85 | 0→17 | 8.1→34.0 | strict | chunks,leak |
| 0707.4363/extracted/main.tex | strict | strict | 91→85 | 0→2 | 7.1→34.7 | strict | chunks,leak |
| 0707.4407/extracted/pseudoscalar14a.tex | strict | strict | 218→250 | 0→2 | 39.9→94.8 | strict | chunks,leak |
| 0707.4451/extracted/main.tex | strict | strict | 189→211 | 0→46 | 15.8→63.0 | strict | chunks,leak |
| 0707.4465/extracted/cizallanals.tex | strict | strict | 149→116 | 0→52 | 13.8→66.1 | strict | chunks,leak |
| 0707.4481/extracted/ms.tex | strict | strict | 70→52 | 0→10 | 9.1→42.3 | strict | chunks,leak |
| 0707.4577/extracted/egghe3.tex | strict | strict | 70→61 | 0→1 | 7.8→43.6 | strict | chunks,leak |
| 0707.4643/extracted/ActiveLogConcave.tex | strict | strict | 79→78 | 0→4 | 12.1→39.9 | strict | chunks,leak |
| 0806.0027/extracted/ldos.tex | strict | strict | 45→51 | 0→1 | 5.3→26.2 | strict | chunks,leak |
| 0806.0433/extracted/EnumerationsforPermutationsbyCircularDescentSets.TEX | strict | strict | 87→90 | 0→30 | 11.4→40.9 | strict | chunks,leak |
| 0806.0463/extracted/per2.tex | strict | strict | 867→780 | 1→331 | 68.3→194.6 | strict | chunks,leak |
| 0806.0489/extracted/Fieldtransform_Tretyakov.tex | strict | strict | 89→88 | 0→33 | 9.8→36.5 | strict | chunks,leak |
| 0806.0588/extracted/eqkpz3.tex | strict | strict | 94→98 | 0→2 | 7.9→40.7 | strict | chunks,leak |
| 0806.0627/extracted/4697_2var_dlxtbl.tex | strict | strict | 4→6 | 0→1 | 3.8→10.9 | strict | chunks,leak |
| 0806.0627/extracted/4697_flarevar_dlxtbl.tex | strict | strict | 1→2 | 0→1 | 1.2→4.5 | strict | chunks,leak |
| 0806.0627/extracted/ms.tex | strict | strict | 76→70 | 0→3 | 20.5→95.6 | strict | chunks,leak |
| 0806.0645/extracted/Damanik-Gorodetski.tex | strict | strict | 163→175 | 0→35 | 14.0→55.3 | strict | chunks,leak |
| 0806.0880/extracted/main.tex | strict | strict | 56→63 | 0→14 | 5.3→27.2 | strict | chunks,leak |
| 0806.0899/extracted/main.tex | strict | strict | 129→79 | 0→20 | 12.5→60.9 | strict | chunks,leak |
| 0806.0904/extracted/involutions.tex | strict | strict | 56→64 | 0→13 | 10.6→43.6 | strict | chunks,leak |
| 0806.0982/extracted/genpar.tex | strict | strict | 114→125 | 0→15 | 10.4→53.6 | strict | chunks,leak |
| 0806.1019/extracted/ros22.tex | strict | strict | 397→196 | 0→78 | 38.1→145.1 | strict | chunks,leak |
| 0806.1079/extracted/main.tex | strict | strict | 280→243 | 0→25 | 32.0→112.0 | strict | chunks,leak |
| 0806.1274/extracted/paper18.tex | strict | strict | 17→21 | 0→2 | 5.0→29.5 | strict | chunks,leak |
| 0806.1406/extracted/rps_viscosity.tex | strict | strict | 48→41 | 0→2 | 5.0→23.8 | strict | chunks,leak |
| 0806.1498/extracted/main-fin2.tex | strict | strict | 193→151 | 0→38 | 29.7→146.5 | strict | chunks,leak |
| 0806.1562/extracted/ZRS_PRB_arxiv.tex | strict | strict | 107→136 | 0→1 | 18.1→92.8 | strict | chunks,leak |
| 0806.1589/extracted/ms.tex | strict | strict | 149→124 | 0→7 | 11.0→55.1 | strict | chunks,leak |
| 0806.1602/extracted/new_paper_forinjectivity_MM2.tex | strict | strict | 225→252 | 0→26 | 20.9→117.4 | strict | chunks,leak |
| 0806.1839/extracted/TZX.tex | strict | strict | 172→156 | 0→2 | 14.4→63.5 | strict | chunks,leak |
| 0806.1867/extracted/pairsep.tex | strict | strict | 148→164 | 0→66 | 19.7→80.5 | strict | chunks,leak |
| 0806.3824/extracted/main.tex | strict | strict | 150→240 | 0→55 | 26.3→97.5 | strict | chunks,leak |
| 0806.4088/extracted/9986.tex | strict | strict | 84→60 | 0→4 | 17.4→69.2 | strict | chunks,leak |
| … | +122 more | | | | | | |

## 统计口径 (docs/09 §7.2)

- 权重: post-strat w=N_cell/n_cell (核心层), 170/170 篇有权; bootstrap: 簇键 cluster_id‖yymm‖pid, B=2000, seed=20260915 (无簇键即逐篇 iid)
| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |
|---|---|---|---|---|---|
| parse ok (file) | 100.000% (214/214) | 100.000% | 100.000% | [98.237, 100.000] | [100.000, 100.000] |
| strict identity | 100.000% (214/214) | 100.000% | 100.000% | [98.237, 100.000] | [100.000, 100.000] |
| leak (chunk) | 0.000% (1/21351) | 0.005% | 0.001% | [0.001, 0.027] | [0.000, 0.014] |
| flatten coverage | 98.07% (203/207) | 98.02% | 99.01% | — | [96.15, 100.00] |

## leak detail

| file | leaked/trans | hits | leaked-chunk snippets |
|---|---|---|---|
| 0806.0463/extracted/per2.tex | 1/867 | dollar | ['dollar'] `We set
$L_t:=
\det p_{[[MACRO_2582]]!}\left({\cal E} \otimes p_X^* (\beta 
+ t [` |

## per-paper

| paper | class | options | roots | tags | tex | ok | strict | leak% | orphan-tex |
|---|---|---|---|---|---|---|---|---|---|
| 0707.0005/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.0476/extracted | IEEEtran | 11pt, onecolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.0687/extracted | ws-procs9x6 | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.0795/extracted | amsart | 10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1255/extracted | aipproc | ,final | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1345/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1511/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1626/extracted | article | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1778/extracted | aastex | 10pt,preprint2,longnamesfirst | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.2108/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.2125/extracted | amsart | reqno,fleqn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.2152/extracted | iopart | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.2234/extracted | revtex4 | twocolumn,pre,showpacs,floatfix,eqsecnum | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.2318/extracted | report | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.2680/extracted | article | 11pt,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.2833/extracted | article | twocolumn,10,a4paper | 1 | xelatex, non-utf8, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 0707.2897/extracted | revtex4 | 12pt,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.2951/extracted | aastex | preprint2 | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.3086/extracted | revtex4 | twocolumn,showpacs,amsmath,amssymb | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.3223/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.3247/extracted | revtex4 | twocolumn,showpacs,preprintnumbers | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.3283/extracted | revtex4 | aps,showpacs,twocolumn,floats,prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.3379/extracted | dis07 | twoside | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.3434/extracted | revtex4 | twocolumn | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.3889/extracted | revtex4 | twocolumn,english,showpacs,aps,pre,secnumarabic | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 0707.3950/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4134/extracted | amsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4363/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb,prb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4407/extracted | revtex4 | preprint,showpacs,showkeys | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4451/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4465/extracted | elsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4481/extracted | emulateapj | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4577/extracted | revtex4 | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4643/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0027/extracted | revtex4 | twocolumn,floatfix,amsmath,prl,aps,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0433/extracted | article | 12pt,dvipdfm | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0463/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.12 | 0 |
| 0806.0489/extracted | iopart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0588/extracted | revtex4 | preprint,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0627/extracted | emulateapj | — | 1 | xelatex, no-hyperref | 6 | 6 | 6 | 0.00 | 0 |
| 0806.0645/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0880/extracted | amsart | reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0899/extracted | article | leqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0904/extracted | article | 12pt | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0982/extracted | revtex4 | aps,twocolumn,superscriptaddress,showpacs,amsmath | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1019/extracted | JHEP3 | 12pt,notoc | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1079/extracted | article | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1274/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1406/extracted | mn2e | useAMS,usenatbib,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1498/extracted | article | 12pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1562/extracted | revtex4 | twocolumn,english,prb | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1589/extracted | emulateapj | apj | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1602/extracted | llncs | a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1839/extracted | revtex4 | prb,twocolumn,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1867/extracted | article | a4paper,10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.3824/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4088/extracted | aa | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4146/extracted | revtex4 | superscriptaddress,pra | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4301/extracted | revtex4 | aps,prl,showpacs,twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4436/extracted | revtex4 | aps,pre,preprint,superscriptaddress,showpacs,showkeys | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4446/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4458/extracted | revtex4 | aps,showpacs,manuscript,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4544/extracted | mn2e | useAMS,usenatbib,usegraphicx | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4589/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4779/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4858/extracted | article | 11pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4948/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1426/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1675/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1680/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1757/extracted | pasj00 | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1767/extracted | revtex4 | aps,prb,10pt,twocolumn,groupedaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1807/extracted | an | mathleft | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2055/extracted | revtex4 | preprin,showpacs,preprintnumbers,eqsecnum,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2090/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2095/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2110/extracted | revtex4 | onecolumn,showpacs,amsmath,amssymb | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2137/extracted | article | a4paper,10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2231/extracted | amsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2328/extracted | article | 10pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2394/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2486/extracted | revtex4 | twocolumn, showkeys, showpacs, preprintnumbers,amsmath,amssymb, prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4010/extracted | amsart | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4208/extracted | revtex4 | prd, twocolumn, showpacs, superscriptaddress, amsmath, amssymb | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4294/extracted | aastex | 12pt,manuscript | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4316/extracted | revtex4 | onecolumn,manuscript | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4371/extracted | amsart | 12pt,a4paper | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| 0905.4380/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4427/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb,prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4439/extracted | aa | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4476/extracted | article | 11 pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4503/extracted | emulateapj | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4556/extracted | revtex4 | aps,prl,twocolumn,showpacs,superscriptaddress,preprintnumbers,amsmath,amssymb | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4656/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4781/extracted | revtex4 | aps,preprint,groupedaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4793/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4796/extracted | revtex4 | aps,floats,pre,showpacs,twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4873/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4874/extracted | imsart | dvips,aap | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4907/extracted | jpconf | letterpaper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.1122/extracted | birkjour | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1003.1273/extracted | — | — | 0 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.1318/extracted | revtex4 | twocolumn,english,aps,prb,showpacs,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.1383/extracted | revtex4 | twocolumn,superscriptaddress,showpacs,preprintnumbers,amsmath,amssymb,aps,prb | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1003.1464/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.1717/extracted | emulateapj | — | 1 | xelatex, no-hyperref | 3 | 3 | 3 | 0.00 | 2 |
| 1003.1735/extracted | revtex4 | twocolumn,prl | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.1741/extracted | — | — | 0 | no-hyperref | 6 | 6 | 6 | 0.00 | 0 |
| 1003.1752/extracted | revtex4 | showpacs,twocolumn,preprintnumbers,amsmath,amssymb,aps,prl,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.1906/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.2091/extracted | elsarticle | final,5p,times,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.2152/extracted | amsart | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.2182/extracted | PoS | — | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1003.4383/extracted | revtex4 | 12pt,aps,nofootinbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4522/extracted | emulateapj | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4523/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4527/extracted | aa | oldversion | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4562/extracted | eptcs | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| 1003.4720/extracted | revtex4 | preprint,aps,12pt,preprintnumbers,eqsecnum,nofootinbib,superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4727/extracted | article | 10pt,letterpaper,twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4807/extracted | article | epsfig,11pt | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5011/extracted | revtex4-1 | aps,prb,twocolumn,superscriptaddress,showpacs | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5014/extracted | revtex4 | aps,prb,showpacs,groupedaddress,floatfix,nofootinbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5141/extracted | amsart | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5240/extracted | arximspdf | aop,citesort,MSNbibl,noautosecdot,dvips | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5306/extracted | article | twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5338/extracted | article | 10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5394/extracted | revtex4 | aps,prd,groupedaddress,showpacs,showkeys,nofootinbib | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5474/extracted | IEEEtran | 12pt,draftcls,onecolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5486/extracted | jpconf | a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5495/extracted | amsart | showpacs,11pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5531/extracted | amsart | 11pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.5534/extracted | book | 10pt | 1 | non-utf8, no-hyperref | 26 | 26 | 26 | 0.00 | 0 |
| 1003.5546/extracted | aastex | preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1124/extracted | article | 10pt,a4paper,english | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1143/extracted | aipproc | ,final | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1149/extracted | amsart | a4paper, 12pt, leqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1167/extracted | revtex4 | aps,twocolumn,showpacs,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1177/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1195/extracted | ismdproc | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1206/extracted | PoS | cits | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1303/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1321/extracted | spie | a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1334/extracted | jac | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1012.1389/extracted | article | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1395/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1584/extracted | article | 12pt,aaspp4 | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1738/extracted | birkjour | — | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1739/extracted | revtex4 | aps,nofootinbib,twocolumn | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1740/extracted | revtex4-1 | prl,twocolumn,showpacs,superscriptaddress,floatfix | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1814/extracted | article | 11pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1816/extracted | revtex4 | pra,twocolumn,showpacs,floatfix | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1830/extracted | revtex4 | slac_one | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.2012/extracted | imsart | ejs | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5057/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5068/extracted | svjour | epjH | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5086/extracted | revtex4-1 | aps,prb,preprint,groupedaddress,superscriptaddress, amsmath,amssymb, aps,floatfix, showpacs | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5145/extracted | revtex4 | aps,prl,twocolumn,showpacs,superscriptaddress | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 1012.5197/extracted | IEEEtran | 12pt,draftclsnofoot, perreview, onecolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5220/extracted | article | 10pt,a4paper,oneside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5273/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5491/extracted | revtex4 | aps,preprint,showpacs, showkeys | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5538/extracted | amsart | reqno,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5612/extracted | article | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5773/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5832/extracted | amsart | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5842/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1664/extracted | aims | — | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1677/extracted | article | 12pt,a4paper,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1707/extracted | revtex4-1 | letterpaper,nofootinbib,prd,amsmath,twocolumn | 1 | — | 1 | 1 | 1 | 0.00 | 0 |

## by class

| class | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| IEEEtran | 3 | 3 | 100.0 | 100.0 | 0.00 |
| JHEP3 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| PoS | 2 | 3 | 100.0 | 100.0 | 0.00 |
| aa | 3 | 3 | 100.0 | 100.0 | 0.00 |
| aastex | 7 | 7 | 100.0 | 100.0 | 0.00 |
| aims | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aipproc | 2 | 2 | 100.0 | 100.0 | 0.00 |
| amsart | 22 | 23 | 100.0 | 100.0 | 0.02 |
| an | 1 | 1 | 100.0 | 100.0 | 0.00 |
| article | 47 | 48 | 100.0 | 100.0 | 0.00 |
| arximspdf | 1 | 1 | 100.0 | 100.0 | 0.00 |
| birkjour | 2 | 2 | 100.0 | 100.0 | 0.00 |
| book | 1 | 26 | 100.0 | 100.0 | 0.00 |
| dis07 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsart | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsarticle | 1 | 1 | 100.0 | 100.0 | 0.00 |
| emulateapj | 6 | 13 | 100.0 | 100.0 | 0.00 |
| eptcs | 1 | 2 | 100.0 | 100.0 | 0.00 |
| imsart | 2 | 2 | 100.0 | 100.0 | 0.00 |
| iopart | 2 | 2 | 100.0 | 100.0 | 0.00 |
| ismdproc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jac | 1 | 2 | 100.0 | 100.0 | 0.00 |
| jpconf | 2 | 2 | 100.0 | 100.0 | 0.00 |
| llncs | 1 | 1 | 100.0 | 100.0 | 0.00 |
| mn2e | 2 | 2 | 100.0 | 100.0 | 0.00 |
| pasj00 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| report | 1 | 1 | 100.0 | 100.0 | 0.00 |
| revtex4 | 45 | 47 | 100.0 | 100.0 | 0.00 |
| revtex4-1 | 4 | 4 | 100.0 | 100.0 | 0.00 |
| spie | 1 | 1 | 100.0 | 100.0 | 0.00 |
| svjour | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ws-procs9x6 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| — | 2 | 7 | 100.0 | 100.0 | 0.00 |

## by era

| era | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| new | 170 | 214 | 100.0 | 100.0 | 0.00 |

## by stratum_cell

| stratum_cell | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| b_2007_11|astro-ph | 26 | 33 | 100.0 | 100.0 | 0.00 |
| b_2007_11|cond-mat | 27 | 27 | 100.0 | 100.0 | 0.00 |
| b_2007_11|cs | 12 | 20 | 100.0 | 100.0 | 0.00 |
| b_2007_11|eess-stat-etc | 5 | 5 | 100.0 | 100.0 | 0.00 |
| b_2007_11|hep-phys | 45 | 73 | 100.0 | 100.0 | 0.00 |
| b_2007_11|math | 41 | 42 | 100.0 | 100.0 | 0.01 |
| b_2007_11|nucl | 5 | 5 | 100.0 | 100.0 | 0.00 |
| b_2007_11|quant-ph | 9 | 9 | 100.0 | 100.0 | 0.00 |

## by cluster_id

| cluster_id | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| C07 | 34 | 35 | 100.0 | 100.0 | 0.00 |
| C08 | 33 | 38 | 100.0 | 100.0 | 0.02 |
| C09 | 33 | 34 | 100.0 | 100.0 | 0.00 |
| C10 | 34 | 68 | 100.0 | 100.0 | 0.00 |
| C11 | 33 | 36 | 100.0 | 100.0 | 0.00 |
| C12 | 3 | 3 | 100.0 | 100.0 | 0.00 |

## by layer

| layer | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| core | 170 | 214 | 100.0 | 100.0 | 0.00 |
