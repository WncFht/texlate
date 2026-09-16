# parsebench summary — corpus_v3

- papers: 35   files (.tex): 36   wall: 39.7s
- parse ok: **36/36** (100.0%)   errors: 0   measure_errors: 0
- identity: strict **36** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **0/4190** chunks = 0.00%   hits={}
- chunk chars: median 196.0   p90 811
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 0
- scan/validate warnings: {'unclosed_env': 22, 'stray_end': 17, 'def_parse_fail': 2, 'missing_input': 1}
- flatten coverage: 36 reached / 0 orphan tex / 0 rootless   (触及率 100.0%)

## funnel

| stage | n |
|---|---|
| fetched (manifest rows) | 1000 |
| source ok | 1000 |
| papers discovered | 35 |
| .tex files | 36 |
| rooted papers | 35 (multi_doc 0, rootless 0) |
| parse ok | 36 |
| identity | strict 36 / normalized 0 / diverged 0 |
| translatable chunks | 4190 |
| leaked chunks | 0 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 0 |
| flatten reached / orphan / rootless | 36 / 0 / 0 |

## gates (docs/09 §8)

| gate | value | 门槛 | verdict |
|---|---|---|---|
| parse ok (file) | 100.0% CI [90.36, 100.00] | 100% & Wilson lb ≥99.5% | PASS(low-n) |
| strict identity | 100.00% CI [90.36, 100.00] | ≥99.5% | PASS |
| leak rate (chunk) | 0.000% CI [0.000, 0.092] | ≤0.15% | PASS |
| dead/orphan | 0 (chunk 0 + protect 0 + orphan 0) | =0 | PASS |
| flatten coverage | 100.0% (36/36) | ≥99% † | PASS |

† coverage 口径勘误 (docs/09 §8 表下): orphan 大头是 e-print 内未被主文件 \input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; v3 实测 ~93%.

## v1 vs v2 — segmenter.parse_tex_v2

| 指标 | v1 (scanner) | v2 (segmenter) |
|---|---|---|
| parse ok | 36/36 | 36/36 |
| identity strict/normalized/diverged | 36/0/0 | 36/0/0 |
| translatable chunks | 4190 | 4044 |
| leaked chunks | 0 | 0 |
| Σ chunks | 4190 | 4044 |
| Σ placeholders | 23195 | 26338 |
| wall ms p50 / p95 | 15 / 1202 | 77 / 2108 |
| vtex_vs_src 展开足迹 | — | strict 34 / normalized 0 / diverged 2 |
| v2 warn_kinds | — | {'stray_end': 17, 'missing_input': 1} |

### v1↔v2 差异文件 (23/36)

| file | v1 id | v2 id | chunks | leaked | ms | vtex_vs_src | flags |
|---|---|---|---|---|---|---|---|
| 0707.0005/extracted/main.tex | strict | strict | 167→132 | 0→0 | 633.0→1368.4 | strict | chunks |
| 0707.0476/extracted/fpc_arxiv.tex | strict | strict | 118→117 | 0→0 | 21.7→120.0 | strict | chunks |
| 0707.0795/extracted/main.tex | strict | strict | 144→140 | 0→0 | 23.2→97.4 | strict | chunks |
| 0707.1255/extracted/Athron_Peter.tex | strict | strict | 35→33 | 0→0 | 4.3→24.6 | diverged | chunks |
| 0707.1345/extracted/fcalura_accept.tex | strict | strict | 43→51 | 0→0 | 18.4→133.7 | strict | chunks |
| 0707.1511/extracted/amalgam_final.tex | strict | strict | 89→83 | 0→0 | 22.8→74.8 | strict | chunks |
| 0707.1626/extracted/main.tex | strict | strict | 134→160 | 0→0 | 557.0→1139.9 | strict | chunks |
| 0707.1778/extracted/preprint.tex | strict | strict | 91→101 | 0→0 | 13.8→86.9 | strict | chunks |
| 0707.2108/extracted/pmeyerxi.TEX | strict | strict | 696→682 | 0→0 | 187.4→428.0 | diverged | chunks |
| 0707.2125/extracted/main.tex | strict | strict | 147→108 | 0→0 | 20.5→72.3 | strict | chunks |
| 0707.2152/extracted/paper.tex | strict | strict | 55→43 | 0→0 | 5.8→35.0 | strict | chunks |
| 0707.2234/extracted/brownian-revised.tex | strict | strict | 117→125 | 0→0 | 30.1→147.3 | strict | chunks |
| 0707.2318/extracted/MPhilThesis.tex | strict | strict | 305→291 | 0→0 | 55.5→187.3 | strict | chunks |
| 0707.2680/extracted/migliori.tex | strict | strict | 21→19 | 0→0 | 5.7→26.7 | strict | chunks |
| 0707.2833/extracted/Iftomm_Chablat_Wenger_Merlet.tex | strict | strict | 93→92 | 0→0 | 364.9→720.8 | strict | chunks |
| 0707.2833/extracted/macros.tex | strict | strict | 1→0 | 0→0 | 3.1→3.5 | strict | chunks |
| 0707.3086/extracted/main.tex | strict | strict | 46→37 | 0→0 | 6.5→40.1 | strict | chunks |
| 0707.3223/extracted/ms.tex | strict | strict | 26→25 | 0→0 | 9.4→53.1 | strict | chunks |
| 0707.3247/extracted/Revised2.tex | strict | strict | 84→69 | 0→0 | 9.9→49.9 | strict | chunks |
| 0707.3283/extracted/manus.tex | strict | strict | 41→31 | 0→0 | 8.3→45.6 | strict | chunks |
| 0707.3889/extracted/khiTxenon-v0-HAL.tex | strict | strict | 246→248 | 0→0 | 1626.7→3446.9 | strict | chunks |
| 0707.4134/extracted/article.tex | strict | strict | 92→87 | 0→0 | 13.0→56.1 | strict | chunks |
| 0707.4465/extracted/cizallanals.tex | strict | strict | 149→120 | 0→0 | 33.8→110.5 | strict | chunks |

## 统计口径 (docs/09 §7.2)

- 权重: post-strat w=N_cell/n_cell (核心层), 35/35 篇有权; bootstrap: 簇键 cluster_id‖yymm‖pid, B=2000, seed=20260915 (无簇键即逐篇 iid)
| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |
|---|---|---|---|---|---|
| parse ok (file) | 100.000% (36/36) | 100.000% | 100.000% | [90.358, 100.000] | [100.000, 100.000] |
| strict identity | 100.000% (36/36) | 100.000% | 100.000% | [90.358, 100.000] | [100.000, 100.000] |
| leak (chunk) | 0.000% (0/4190) | 0.000% | 0.000% | [0.000, 0.092] | [0.000, 0.000] |
| flatten coverage | 100.00% (36/36) | 100.00% | 100.00% | — | [100.00, 100.00] |

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

## by class

| class | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| IEEEtran | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aastex | 4 | 4 | 100.0 | 100.0 | 0.00 |
| aipproc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| amsart | 4 | 4 | 100.0 | 100.0 | 0.00 |
| article | 8 | 9 | 100.0 | 100.0 | 0.00 |
| dis07 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsart | 1 | 1 | 100.0 | 100.0 | 0.00 |
| emulateapj | 1 | 1 | 100.0 | 100.0 | 0.00 |
| iopart | 1 | 1 | 100.0 | 100.0 | 0.00 |
| report | 1 | 1 | 100.0 | 100.0 | 0.00 |
| revtex4 | 11 | 11 | 100.0 | 100.0 | 0.00 |
| ws-procs9x6 | 1 | 1 | 100.0 | 100.0 | 0.00 |

## by era

| era | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| new | 35 | 36 | 100.0 | 100.0 | 0.00 |

## by stratum_cell

| stratum_cell | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| b_2007_11|astro-ph | 6 | 6 | 100.0 | 100.0 | 0.00 |
| b_2007_11|cond-mat | 7 | 7 | 100.0 | 100.0 | 0.00 |
| b_2007_11|cs | 2 | 3 | 100.0 | 100.0 | 0.00 |
| b_2007_11|eess-stat-etc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| b_2007_11|hep-phys | 9 | 9 | 100.0 | 100.0 | 0.00 |
| b_2007_11|math | 7 | 7 | 100.0 | 100.0 | 0.00 |
| b_2007_11|nucl | 1 | 1 | 100.0 | 100.0 | 0.00 |
| b_2007_11|quant-ph | 2 | 2 | 100.0 | 100.0 | 0.00 |

## by cluster_id

| cluster_id | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| C07 | 34 | 35 | 100.0 | 100.0 | 0.00 |
| C08 | 1 | 1 | 100.0 | 100.0 | 0.00 |

## by layer

| layer | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| core | 35 | 36 | 100.0 | 100.0 | 0.00 |
