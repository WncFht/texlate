# parsebench summary — corpus_v2

- papers: 138   files (.tex): 224   wall: 34.0s
- parse ok: **224/224** (100.0%)   errors: 0   measure_errors: 0
- identity: strict **224** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **2/17426** chunks = 0.01%   hits={'dollar': 2}
- chunk chars: median 203.0   p90 801
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 0
- scan/validate warnings: {'def_parse_fail': 40, 'missing_input': 11}
- flatten coverage: 210 reached / 14 orphan tex / 0 rootless   (触及率 93.8%)

## funnel

| stage | n |
|---|---|
| fetched (manifest rows) | 217 |
| source ok | 139 |
| papers discovered | 138 |
| .tex files | 224 |
| rooted papers | 138 (multi_doc 3, rootless 0) |
| parse ok | 224 |
| identity | strict 224 / normalized 0 / diverged 0 |
| translatable chunks | 17426 |
| leaked chunks | 2 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 0 |
| flatten reached / orphan / rootless | 210 / 14 / 0 |

## gates (docs/09 §8)

| gate | value | 门槛 | verdict |
|---|---|---|---|
| parse ok (file) | 100.0% CI [98.31, 100.00] | 100% & Wilson lb ≥99.5% | PASS(low-n) |
| strict identity | 100.00% CI [98.31, 100.00] | ≥99.5% | PASS |
| leak rate (chunk) | 0.010% CI [0.003, 0.042] | ≤0.15% | PASS |
| dead/orphan | 0 (chunk 0 + protect 0 + orphan 0) | =0 | PASS |
| flatten coverage | 93.8% (210/224) | ≥99% † | BELOW |

† coverage 口径勘误 (docs/09 §8 表下): orphan 大头是 e-print 内未被主文件 \input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; v3 实测 ~93%.

## v1 vs v2 — segmenter.parse_tex_v2

| 指标 | v1 (scanner) | v2 (segmenter) |
|---|---|---|
| parse ok | 224/224 | 224/224 |
| identity strict/normalized/diverged | 224/0/0 | 224/0/0 |
| translatable chunks | 17426 | 14822 |
| leaked chunks | 2 | 351 |
| Σ chunks | 17426 | 14822 |
| Σ placeholders | 95875 | 109161 |
| wall ms p50 / p95 | 9 / 80 | 47 / 254 |
| vtex_vs_src 展开足迹 | — | strict 224 / normalized 0 / diverged 0 |
| v2 warn_kinds | — | {'dead_ph': 1897, 'missing_input': 10, 'def_parse_fail': 11, 'stray_end': 2} |

### v1↔v2 差异文件 (163/224)

| file | v1 id | v2 id | chunks | leaked | ms | vtex_vs_src | flags |
|---|---|---|---|---|---|---|---|
| 0807.5094/extracted/0807.5094v1.tex | strict | strict | 61→60 | 0→0 | 7.0→26.8 | strict | chunks |
| 0808.0678/extracted/CrNbSe-p4r.tex | strict | strict | 64→59 | 0→0 | 7.7→48.2 | strict | chunks |
| 0808.2596/extracted/0808.2596v1.tex | strict | strict | 175→178 | 0→0 | 21.2→84.8 | strict | chunks |
| 0808.2824/extracted/0528.tex | strict | strict | 113→110 | 0→0 | 11.6→74.5 | strict | chunks |
| 0810.0013/extracted/0810.0013v1.tex | strict | strict | 57→54 | 0→0 | 7.5→37.8 | strict | chunks |
| 0810.0187/extracted/Incompressibility.tex | strict | strict | 87→85 | 0→0 | 10.3→50.8 | strict | chunks |
| 0812.4521/extracted/rPLA.tex | strict | strict | 30→27 | 0→0 | 11.1→62.7 | strict | chunks |
| 0903.0543/extracted/unitlearn_PRA.tex | strict | strict | 48→45 | 0→0 | 11.8→58.5 | strict | chunks |
| 0903.0667/extracted/LeptophilicHiggs.tex | strict | strict | 142→120 | 0→0 | 25.8→128.9 | strict | chunks |
| 0905.4345/extracted/llwi09.tex | strict | strict | 36→31 | 0→0 | 6.6→24.9 | strict | chunks |
| 0908.3240/extracted/0908.3240v3.tex | strict | strict | 170→169 | 0→0 | 387.4→483.2 | strict | chunks |
| 0909.3990/extracted/mixmc.tex | strict | strict | 46→39 | 0→9 | 6.5→29.3 | strict | chunks,leak |
| 0912.2867/extracted/manuscript-v7-SV-PMO-AK.tex | strict | strict | 55→35 | 0→0 | 6.8→38.6 | strict | chunks |
| 1002.4948/extracted/1002.4948v1.tex | strict | strict | 43→42 | 0→0 | 6.3→32.1 | strict | chunks |
| 1005.0504/extracted/manuscript.tex | strict | strict | 213→97 | 0→0 | 27.5→114.1 | strict | chunks |
| 1009.5340/extracted/SW_hybridscan_v2.tex | strict | strict | 50→44 | 0→0 | 11.7→66.0 | strict | chunks |
| 1011.1566/extracted/Final_Manuscript-arXiv.tex | strict | strict | 147→132 | 0→0 | 79.6→145.6 | strict | chunks |
| 1011.5681/extracted/AMO08.tex | strict | strict | 254→0 | 0→0 | 58.6→86.9 | strict | chunks |
| 1012.0641/extracted/ms.tex | strict | strict | 109→92 | 0→0 | 13.0→83.1 | strict | chunks |
| 1103.2779/extracted/1103.2779v2.tex | strict | strict | 41→38 | 0→0 | 7.9→41.2 | strict | chunks |
| 1104.0866/extracted/2nd1136ptp.tex | strict | strict | 69→71 | 0→0 | 14.4→61.9 | strict | chunks |
| 1104.3956/extracted/1104.3956v1.tex | strict | strict | 113→110 | 0→0 | 13.5→45.5 | strict | chunks |
| 1106.5915/extracted/aap797.tex | strict | strict | 270→130 | 0→0 | 41.1→115.5 | strict | chunks |
| 1107.4465/extracted/analysis.tex | strict | strict | 21→20 | 0→0 | 2.6→16.2 | strict | chunks |
| 1107.4465/extracted/introduction.tex | strict | strict | 9→8 | 0→0 | 1.7→7.9 | strict | chunks |
| 1107.4465/extracted/normalization.tex | strict | strict | 10→7 | 0→0 | 1.4→9.2 | strict | chunks |
| 1107.4465/extracted/paper.tex | strict | strict | 75→61 | 0→0 | 31.5→101.7 | strict | chunks |
| 1107.4465/extracted/results.tex | strict | strict | 14→5 | 0→0 | 3.7→15.5 | strict | chunks |
| 1107.4465/extracted/systematics.tex | strict | strict | 8→7 | 0→0 | 2.4→12.2 | strict | chunks |
| 1111.3582/extracted/acat2011.tex | strict | strict | 64→36 | 0→0 | 6.1→36.7 | strict | chunks |
| 1203.4711/extracted/lmdmcv.tex | strict | strict | 121→101 | 0→8 | 19.5→123.1 | strict | chunks,leak |
| 1204.1276/extracted/sabato13a.tex | strict | strict | 189→187 | 0→48 | 31.5→132.1 | strict | chunks,leak |
| 1205.3871/extracted/1205.3871v2.tex | strict | strict | 125→118 | 0→0 | 13.6→62.9 | strict | chunks |
| 1206.1214/extracted/1206.1214v1.tex | strict | strict | 109→106 | 0→0 | 9.8→47.3 | strict | chunks |
| 1206.6992/extracted/realequibordv1.tex | strict | strict | 90→86 | 0→0 | 13.9→59.1 | strict | chunks |
| 1304.2607/extracted/1304.2607v1.tex | strict | strict | 462→347 | 0→0 | 46.0→170.7 | strict | chunks |
| 1305.6815/extracted/hyper.tex | strict | strict | 160→143 | 0→0 | 18.9→90.2 | strict | chunks |
| 1308.0304/extracted/cosmiccensorship-solo.tex | strict | strict | 184→150 | 0→0 | 22.0→156.7 | strict | chunks |
| 1308.6422/extracted/streaming_reference_arxiv.tex | strict | strict | 93→88 | 0→0 | 12.3→71.3 | strict | chunks |
| 1312.0738/extracted/QDISS.tex | strict | strict | 77→69 | 0→0 | 8.0→44.0 | strict | chunks |
| 1401.3072/extracted/1401.3072v2.tex | strict | strict | 95→90 | 0→0 | 19.8→62.4 | strict | chunks |
| 1404.4155/extracted/1404.4155v1.tex | strict | strict | 83→87 | 0→18 | 12.3→44.5 | strict | chunks,leak |
| 1404.7186/extracted/Theta3_CGTA.tex | strict | strict | 76→62 | 0→23 | 9.2→47.9 | strict | chunks,leak |
| 1405.1125/extracted/nonsurjective_-_sigma.tex | strict | strict | 206→192 | 0→0 | 40.9→158.7 | strict | chunks |
| 1406.1994/extracted/finalv5.tex | strict | strict | 126→103 | 0→6 | 191.0→257.7 | strict | chunks,leak |
| 1406.7856/extracted/Moore_Primary_Beam_Steering_JINST.tex | strict | strict | 44→32 | 0→0 | 7.6→35.6 | strict | chunks |
| 1408.0444/extracted/1408.0444v3.tex | strict | strict | 180→174 | 0→0 | 25.7→94.5 | strict | chunks |
| 1409.6539/extracted/pubversionmatrixmodelrevisit.tex | strict | strict | 203→188 | 0→61 | 336.6→442.2 | strict | chunks,leak |
| 1503.02052/extracted/ms.tex | strict | strict | 72→40 | 0→14 | 12.2→56.4 | strict | chunks,leak |
| 1504.05670/extracted/arxiv.tex | strict | strict | 140→127 | 0→0 | 19.1→79.8 | strict | chunks |
| 1505.00491/extracted/HPNP2015_ejchun.tex | strict | strict | 82→48 | 0→5 | 8.7→31.8 | strict | chunks,leak |
| 1506.08661/extracted/TobeSubmitted.tex | strict | strict | 252→223 | 0→0 | 28.5→123.0 | strict | chunks |
| 1508.03368/extracted/U22_v1.tex | strict | strict | 80→54 | 0→0 | 12.0→63.7 | strict | chunks |
| 1607.00497/extracted/_final_ePrint_ECU_identification.tex | strict | strict | 91→79 | 0→0 | 17.7→120.7 | strict | chunks |
| 1608.04155/extracted/Cascade.tex | strict | strict | 70→62 | 0→0 | 25.3→59.6 | strict | chunks |
| 1608.07663/extracted/measurementcostPRE_resubarxiv.tex | strict | strict | 168→89 | 0→0 | 28.3→65.2 | strict | chunks |
| 1609.01652/extracted/xor_entanglement.tex | strict | strict | 103→102 | 0→0 | 14.7→63.1 | strict | chunks |
| 1703.07978/extracted/1703.07978v2.tex | strict | strict | 351→211 | 0→0 | 76.2→203.1 | strict | chunks |
| 1705.05733/extracted/paper_v5.tex | strict | strict | 96→88 | 0→0 | 21.0→126.8 | strict | chunks |
| 1706.07406/extracted/allOrNothingSubset4.tex | strict | strict | 73→63 | 0→0 | 7.2→30.9 | strict | chunks |
| … | +103 more | | | | | | |

## 统计口径 (docs/09 §7.2)

- 权重: 等权退化 (语料无 stratum_cell 或 frame 计数缺失) = raw pooled; bootstrap: 簇键 cluster_id‖yymm‖pid, B=2000, seed=20260915 (无簇键即逐篇 iid)
| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |
|---|---|---|---|---|---|
| parse ok (file) | 100.000% (224/224) | 100.000% | 100.000% | [98.314, 100.000] | [100.000, 100.000] |
| strict identity | 100.000% (224/224) | 100.000% | 100.000% | [98.314, 100.000] | [100.000, 100.000] |
| leak (chunk) | 0.010% (2/17426) | 0.011% | 0.012% | [0.003, 0.042] | [0.000, 0.038] |
| flatten coverage | 93.75% (210/224) | 93.75% | 99.25% | — | [84.98, 100.00] |

## leak detail

| file | leaked/trans | hits | leaked-chunk snippets |
|---|---|---|---|
| 2207.12086/extracted/experiments.tex | 1/21 | dollar | ['dollar'] `\textit{adult}: this dataset is the collection of individual data
of their incom` |
| 2207.12086/extracted/main_aciids.tex | 1/67 | dollar | ['dollar'] `\textit{adult}: this dataset is the collection of individual data
of their incom` |

## per-paper

| paper | class | options | roots | tags | tex | ok | strict | leak% | orphan-tex |
|---|---|---|---|---|---|---|---|---|---|
| 0807.5094/extracted | siamltex | 10pt,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0808.0678/extracted | revtex4 | prb,showpacs,floatfix,twocolumn,superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0808.2596/extracted | amsart | 11pt,reqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0808.2824/extracted | aa | tradiabstract | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0810.0013/extracted | revtex4 | prl,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0810.0187/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0812.4521/extracted | elsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0903.0543/extracted | revtex4 | aps,pra,twocolumn,showpacs | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 0903.0667/extracted | article | 11pt,epsf,epsfig | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4345/extracted | jpconf | letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0908.3240/extracted | amsart | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0909.3990/extracted | revtex4 | twocolumn,showpacs,superscriptaddress,amsmath,amssymb,pre | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0912.2867/extracted | revtex4 | prl,twocolumn,a4paper,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0912.5174/extracted | article | a4paper,12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1002.4948/extracted | article | twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1005.0504/extracted | revtex4-1 | aps,floatfix,preprintnumbers,amsmath,amssymb,amsfonts,final, sort, compress,12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1009.5340/extracted | elsarticle | preprint,12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1011.1566/extracted | IEEEtran | journal,twocolumn,final | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1011.5681/extracted | article | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1012.0641/extracted | emulateapj | useAMS | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1103.2779/extracted | revtex4 | pra,twocolumn,showpacs,preprintnumbers | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1104.0866/extracted | ptptex | seceq | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1104.3956/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1106.5915/extracted | arximspdf | aap,MSNbibl,seceqn,citesort,dvips | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1107.4465/extracted | revtex4 | nofootinbib,twocolumn,showpacs,aps,prd | 1 | xelatex, no-hyperref | 17 | 17 | 17 | 0.00 | 1 |
| 1111.3582/extracted | jpconf | a4paper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1202.4109/extracted | amsart | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1203.4711/extracted | mn2e | useAMS,usenatbib,letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1204.1276/extracted | article | twoside,11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1205.3871/extracted | amsart | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.0671/extracted | revtex4 | aps,twocolumn,showpacs | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.1214/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.6992/extracted | gtpart | microtype | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1304.2607/extracted | amsart | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1305.6815/extracted | article | 11pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1308.0304/extracted | JHEP3 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1308.6422/extracted | pnastwo | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1312.0738/extracted | revtex4 | aps,twocolumn,pra,superscriptaddress,showpacs,tightenlines | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1401.3072/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.4155/extracted | amsart | a4paper,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.7186/extracted | article | letterpaper,11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1405.1125/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1406.1994/extracted | article | 12pt | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1406.7856/extracted | JINST | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1408.0444/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1409.6539/extracted | article | a4paper, 11pt | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1503.02052/extracted | emulateapj | apjl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1504.05670/extracted | IEEEtran | conference,letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1505.00491/extracted | revtex4 | a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1506.08661/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1508.03368/extracted | revtex4-1 | aps,pre,twocolumn,groupedaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1607.00497/extracted | IEEEtran | journal,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.04155/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.07663/extracted | revtex4-1 | twocolumn,showpacs,superscriptaddress,groupedaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1609.01652/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1703.07978/extracted | amsart | reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1705.05733/extracted | aa | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07406/extracted | article | a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07641/extracted | article | twoside,a4paper,11pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1708.07366/extracted | llncs | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1711.07167/extracted | webofc | epj | 1 | — | 2 | 2 | 2 | 0.00 | 1 |
| 1801.06287/extracted | IEEEtran | conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1806.06690/extracted | aastex | preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1808.08677/extracted | revtex4-1 | aps,twocolumn,showpacs,preprintnumbers,floatfix,nofootinbib | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1810.08238/extracted | amsart | a4paper,reqno,12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1902.11112/extracted | ctr_summer | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1905.07704/extracted | article | 11pt,a4paper,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1909.00216/extracted | llncs | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1909.05039/extracted | emulateapj | manuscript | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1910.12800/extracted | geophysics | manuscript | 1 | — | 6 | 6 | 6 | 0.00 | 0 |
| 1911.11639/extracted | revtex4-1 | reprint, superscriptaddress, amsmath,amssymb, aps, prx, longbibliography | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2002.05660/extracted | colt2020 | anon | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2005.12908/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2007.02320/extracted | revtex4 | article,onecolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2007.10128/extracted | amsart | 11pt,a4paper,reqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2101.07948/extracted | acmart (×3) | sigplan,review,anonymous | 3 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 2101.08358/extracted | article (×2) | — | 2 | — | 3 | 3 | 3 | 0.00 | 0 |
| 2104.00776/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2104.02882/extracted | article | a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2106.15467/extracted | IEEEtran | 10pt,journal,compsoc | 1 | — | 14 | 14 | 14 | 0.00 | 0 |
| 2109.12648/extracted | revtex4-1 | twocolumn,aps,prxquantum,reprint,showpacs,superscriptaddress,longbibliography | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2110.10462/extracted | ws-ijmpa | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2201.04035/extracted | webofc | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2205.11592/extracted | revtex4-2 | aps,pre,amsmath,singlecolumn,showpacs,11pt | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 2207.12086/extracted | llncs | a4paper,conference | 1 | no-hyperref | 7 | 7 | 7 | 1.60 | 0 |
| 2210.15358/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2301.01267/extracted | article | 11pt,a4paper | 1 | — | 4 | 4 | 4 | 0.00 | 0 |
| 2303.07696/extracted | lipics-v2021 | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2310.00050/extracted | revtex4-2 | aps,prd,nofootinbib,superscriptaddress,noshowkeys,10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2311.11296/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2312.11468/extracted | MRM (×2) | AMA,STIX2COL | 2 | no-hyperref | 4 | 4 | 4 | 0.00 | 0 |
| 2405.17379/extracted | article | — | 1 | no-hyperref | 25 | 25 | 25 | 0.00 | 12 |
| 2408.09337/extracted | amsart | a4paper,11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2409.09329/extracted | IEEEtran | conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2411.06261/extracted | article | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2412.20694/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2502.03125/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2506.07410/extracted | extarticle | a4paper,12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2605.15481/extracted | optica-article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2606.27966/extracted | llncs | runningheads,10pt | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2608.01215/extracted | revtex4 | nofootinbib,prd,superscriptaddress,twocolumn | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2608.28496/extracted | article | 11pt | 1 | — | 7 | 7 | 7 | 0.00 | 0 |
| astro-ph/0305034 | aastex | preprint2 | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0305062 | aastex | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0306016 | aa | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0306068 | caps | cup5b | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9702009 | article | sprocl,psfig | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9702045 | lamuphys | — | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0202090 | revtex4 | aps,prb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0610061 | revtex4 | aps,prl,twocolumn,superscriptaddress,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9601002 | revtex | prb,aps,twocolumn | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9601069 | revtex | aps,preprint | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cs/0509040 | bmc_article | 10pt, a4paper | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cs/0509053 | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| gr-qc/0012020 | revtex | aps,prd | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| gr-qc/0110019 | iopart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| gr-qc/0110048 | revtex | aps,floats,epsf | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| gr-qc/0609005 | aipproc | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ex/0008012 | test | epsfig,12pt | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ex/0406065 | elsart | — | 1 | xelatex, no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| hep-ex/9702005 | revtex | eqsecnum,aps,smc,floats,twocolumn,psfig | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0411093 | article | 10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0605044 | hnp06 | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0212074 | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0212096 | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0508001 | revtex4 | aps,prd,preprint,amsmath,amssymb, nofootinbib,eqsecnum,showpacs,preprint,tightenlines | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0508095 | pi2005 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0606045 | revtex4 | aps,preprint,nofootinbib,eqsecnum | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0606096 | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0306026 | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/9810010 | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/0104042 | revtex | twocolumn,prc,aps,epsfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/0104081 | article | 12pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0207080 | article | 12pt, a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0207092 | revtex4 | amsmath,pra,twocolumn,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/9709059 | article | apalike,11pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/9712017 | revtex | aps,pra,multicol,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/9712026 | revtex | preprint,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |

## by class

| class | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| IEEEtran | 6 | 19 | 100.0 | 100.0 | 0.00 |
| JHEP3 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| JINST | 1 | 1 | 100.0 | 100.0 | 0.00 |
| MRM | 1 | 4 | 100.0 | 100.0 | 0.00 |
| aa | 3 | 3 | 100.0 | 100.0 | 0.00 |
| aastex | 3 | 3 | 100.0 | 100.0 | 0.00 |
| acmart | 1 | 3 | 100.0 | 100.0 | 0.00 |
| aipproc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| amsart | 16 | 16 | 100.0 | 100.0 | 0.00 |
| article | 36 | 72 | 100.0 | 100.0 | 0.00 |
| arximspdf | 1 | 1 | 100.0 | 100.0 | 0.00 |
| bmc_article | 1 | 1 | 100.0 | 100.0 | 0.00 |
| caps | 1 | 1 | 100.0 | 100.0 | 0.00 |
| colt2020 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ctr_summer | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsart | 2 | 4 | 100.0 | 100.0 | 0.00 |
| elsarticle | 1 | 1 | 100.0 | 100.0 | 0.00 |
| emulateapj | 3 | 3 | 100.0 | 100.0 | 0.00 |
| extarticle | 1 | 1 | 100.0 | 100.0 | 0.00 |
| geophysics | 1 | 6 | 100.0 | 100.0 | 0.00 |
| gtpart | 1 | 1 | 100.0 | 100.0 | 0.00 |
| hnp06 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ieeeconf | 2 | 2 | 100.0 | 100.0 | 0.00 |
| iopart | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jpconf | 2 | 2 | 100.0 | 100.0 | 0.00 |
| lamuphys | 1 | 1 | 100.0 | 100.0 | 0.00 |
| lipics-v2021 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| llncs | 4 | 11 | 100.0 | 100.0 | 0.32 |
| mn2e | 1 | 1 | 100.0 | 100.0 | 0.00 |
| optica-article | 1 | 1 | 100.0 | 100.0 | 0.00 |
| pi2005 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| pnastwo | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ptptex | 1 | 1 | 100.0 | 100.0 | 0.00 |
| revtex | 8 | 8 | 100.0 | 100.0 | 0.00 |
| revtex4 | 17 | 33 | 100.0 | 100.0 | 0.00 |
| revtex4-1 | 6 | 7 | 100.0 | 100.0 | 0.00 |
| revtex4-2 | 2 | 2 | 100.0 | 100.0 | 0.00 |
| siamltex | 1 | 1 | 100.0 | 100.0 | 0.00 |
| test | 1 | 1 | 100.0 | 100.0 | 0.00 |
| webofc | 2 | 3 | 100.0 | 100.0 | 0.00 |
| ws-ijmpa | 1 | 1 | 100.0 | 100.0 | 0.00 |

## by era

| era | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| new | 102 | 186 | 100.0 | 100.0 | 0.01 |
| old | 36 | 38 | 100.0 | 100.0 | 0.00 |

## by archive

| archive | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| astro-ph | 6 | 6 | 100.0 | 100.0 | 0.00 |
| cond-mat | 4 | 4 | 100.0 | 100.0 | 0.00 |
| cs | 2 | 2 | 100.0 | 100.0 | 0.00 |
| gr-qc | 4 | 4 | 100.0 | 100.0 | 0.00 |
| hep-ex | 3 | 5 | 100.0 | 100.0 | 0.00 |
| hep-ph | 2 | 2 | 100.0 | 100.0 | 0.00 |
| hep-th | 6 | 6 | 100.0 | 100.0 | 0.00 |
| math | 2 | 2 | 100.0 | 100.0 | 0.00 |
| nucl-th | 2 | 2 | 100.0 | 100.0 | 0.00 |
| quant-ph | 5 | 5 | 100.0 | 100.0 | 0.00 |
| — | 102 | 186 | 100.0 | 100.0 | 0.01 |
