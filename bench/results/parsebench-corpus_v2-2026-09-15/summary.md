# parsebench summary — corpus_v2

- papers: 138   files (.tex): 224   wall: 6.9s
- parse ok: **224/224** (100.0%)   errors: 0   measure_errors: 0
- identity: strict **224** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **2/17495** chunks = 0.01%   hits={'dollar': 2}
- chunk chars: median 201   p90 799
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 0
- scan/validate warnings: {'def_parse_fail': 67, 'missing_input': 11, 'debt_repair': 2}
- flatten coverage: 208 reached / 16 orphan tex / 0 rootless   (触及率 92.9%)

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
| translatable chunks | 17495 |
| leaked chunks | 2 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 0 |
| flatten reached / orphan / rootless | 208 / 16 / 0 |

## gates (docs/09 §8)

| gate | value | 门槛 | verdict |
|---|---|---|---|
| parse ok (file) | 100.0% CI [98.31, 100.00] | 100% & Wilson lb ≥99.5% | PASS(low-n) |
| strict identity | 100.00% CI [98.31, 100.00] | ≥99.5% | PASS |
| leak rate (chunk) | 0.010% CI [0.003, 0.042] | ≤0.15% | PASS |
| dead/orphan | 0 (chunk 0 + protect 0 + orphan 0) | =0 | PASS |
| flatten coverage | 92.9% (208/224) | ≥99% † | BELOW |

† coverage 口径勘误 (docs/09 §8 表下): orphan 大头是 e-print 内未被主文件 \input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; v3 实测 ~93%.

## 统计口径 (docs/09 §7.2)

- 权重: 等权退化 (语料无 stratum_cell 或 frame 计数缺失) = raw pooled; bootstrap: 簇键 cluster_id‖yymm‖pid, B=2000, seed=20260915 (无簇键即逐篇 iid)
| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |
|---|---|---|---|---|---|
| parse ok (file) | 100.000% (224/224) | 100.000% | 100.000% | [98.314, 100.000] | [100.000, 100.000] |
| strict identity | 100.000% (224/224) | 100.000% | 100.000% | [98.314, 100.000] | [100.000, 100.000] |
| leak (chunk) | 0.010% (2/17495) | 0.011% | 0.012% | [0.003, 0.042] | [0.000, 0.038] |
| flatten coverage | 92.86% (208/224) | 92.86% | 98.88% | — | [83.90, 99.48] |

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
| 2312.11468/extracted | MRM (×2) | AMA,STIX2COL | 2 | no-hyperref | 4 | 4 | 4 | 0.00 | 2 |
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
