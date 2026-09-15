# parsebench summary — corpus_v3

- papers: 200   files (.tex): 416   wall: 7.4s
- parse ok: **416/416** (100.0%)   errors: 0   measure_errors: 0
- identity: strict **416** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **4/31373** chunks = 0.01%   hits={'dollar': 4}
- chunk chars: median 194   p90 795
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 0
- scan/validate warnings: {'unclosed_env': 105, 'stray_end': 11, 'missing_input': 42, 'def_parse_fail': 163, 'unpaired_dollar': 3, 'env_mismatch': 1}
- flatten coverage: 360 reached / 48 orphan tex / 8 rootless   (触及率 88.2%)

## funnel

| stage | n |
|---|---|
| fetched (manifest rows) | 1000 |
| source ok | 1000 |
| papers discovered | 200 |
| .tex files | 416 |
| rooted papers | 197 (multi_doc 2, rootless 3) |
| parse ok | 416 |
| identity | strict 416 / normalized 0 / diverged 0 |
| translatable chunks | 31373 |
| leaked chunks | 4 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 0 |
| flatten reached / orphan / rootless | 360 / 48 / 8 |

## gates (docs/09 §8)

| gate | value | 门槛 | verdict |
|---|---|---|---|
| parse ok (file) | 100.0% CI [99.09, 100.00] | 100% & Wilson lb ≥99.5% | PASS(low-n) |
| strict identity | 100.00% CI [99.09, 100.00] | ≥99.5% | PASS |
| leak rate (chunk) | 0.010% CI [0.005, 0.033] | ≤0.15% | PASS |
| dead/orphan | 0 (chunk 0 + protect 0 + orphan 0) | =0 | PASS |
| flatten coverage | 88.2% (360/408) | ≥99% † | BELOW |

† coverage 口径勘误 (docs/09 §8 表下): orphan 大头是 e-print 内未被主文件 \input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; v3 实测 ~93%.

## 统计口径 (docs/09 §7.2)

- 权重: post-strat w=N_cell/n_cell (核心层), 170/200 篇有权, 30 篇无 stratum_cell/非核心层 → 剔除加权列; bootstrap: 簇键 cluster_id‖yymm‖pid, B=2000, seed=20260915 (无簇键即逐篇 iid)
| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |
|---|---|---|---|---|---|
| parse ok (file) | 100.000% (416/416) | 100.000% | 100.000% | [99.085, 100.000] | [100.000, 100.000] |
| strict identity | 100.000% (416/416) | 100.000% | 100.000% | [99.085, 100.000] | [100.000, 100.000] |
| leak (chunk) | 0.010% (4/31373) | 0.005% | 0.002% | [0.005, 0.033] | [0.000, 0.032] |
| flatten coverage | 88.24% (360/408) | 98.02% | 97.42% | — | [77.42, 97.00] |

## leak detail

| file | leaked/trans | hits | leaked-chunk snippets |
|---|---|---|---|
| 0806.0302/extracted/fp420.tex | 1/970 | dollar | ['dollar'] `For the GASTOF detectors, a single photon counter, such as Boston
Electronics SP` |
| 0806.0302/extracted/fp420time-agb.tex | 1/68 | dollar | ['dollar'] `For the GASTOF detectors, a single photon counter, such as Boston
Electronics SP` |
| 0806.0463/extracted/per2.tex | 1/867 | dollar | ['dollar'] `We set
$L_t:=
\det p_{[[MACRO_2582]]!}\left({\cal E} \otimes p_X^* (\beta 
+ t [` |
| 1012.5411/extracted/doc/latex/revtex/aps/apsguide4-1.tex | 1/94 | dollar | ['dollar'] `In general, all math markup and the standard math environments from
\LaTeXe\ are` |

## per-paper

| paper | class | options | roots | tags | tex | ok | strict | leak% | orphan-tex |
|---|---|---|---|---|---|---|---|---|---|
| 0707.0005/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.0167/extracted | article | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.0476/extracted | IEEEtran | 11pt, onecolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.0687/extracted | ws-procs9x6 | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.0795/extracted | amsart | 10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1206/extracted | — | — | 0 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1255/extracted | aipproc | ,final | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1345/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1511/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1626/extracted | article | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1778/extracted | aastex | 10pt,preprint2,longnamesfirst | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1954/extracted | IEEEtran1.6b | draftcls,onecolumn,12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
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
| 0707.3972/extracted | report (×3) | — | 3 | reject, xelatex, no-hyperref | 79 | 79 | 79 | 0.00 | 30 |
| 0707.4134/extracted | amsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4206/extracted | elsart | letter,seceqn,secthm | 1 | xelatex, no-hyperref | 16 | 16 | 16 | 0.00 | 3 |
| 0707.4363/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb,prb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4407/extracted | revtex4 | preprint,showpacs,showkeys | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4451/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4465/extracted | elsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4481/extracted | emulateapj | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4577/extracted | revtex4 | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.4643/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0027/extracted | revtex4 | twocolumn,floatfix,amsmath,prl,aps,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.0302/extracted | cernrep | — | 1 | xelatex | 18 | 18 | 18 | 0.10 | 0 |
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
| 0806.1415/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 15 | 15 | 15 | 0.00 | 0 |
| 0806.1498/extracted | article | 12pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1562/extracted | revtex4 | twocolumn,english,prb | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1589/extracted | emulateapj | apj | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1602/extracted | llncs | a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1728/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1839/extracted | revtex4 | prb,twocolumn,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.1867/extracted | article | a4paper,10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.3824/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.3923/extracted | revtex4 | twocolumn,prb,nofootinbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4088/extracted | aa | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4130/extracted | article | — | 1 | xelatex, no-hyperref | 3 | 3 | 3 | 0.00 | 2 |
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
| 0905.1566/extracted | llncs | runningheads | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 0905.1619/extracted | elsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1675/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1680/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1718/extracted | article | 12pt,titlepage | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 1 |
| 0905.1757/extracted | pasj00 | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1767/extracted | revtex4 | aps,prb,10pt,twocolumn,groupedaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1807/extracted | an | mathleft | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2055/extracted | revtex4 | preprin,showpacs,preprintnumbers,eqsecnum,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2090/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2095/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2110/extracted | revtex4 | onecolumn,showpacs,amsmath,amssymb | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2120/extracted | itrspaper | final | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 0905.2137/extracted | article | a4paper,10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2231/extracted | amsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2328/extracted | article | 10pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2394/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.2435/extracted | \whatSEKIDOCUMENTCLASS | twoside,12pt | 1 | xelatex, no-hyperref | 4 | 4 | 4 | 0.00 | 3 |
| 0905.2486/extracted | revtex4 | twocolumn, showkeys, showpacs, preprintnumbers,amsmath,amssymb, prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4010/extracted | amsart | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4200/extracted | llncs | oribibl | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4208/extracted | revtex4 | prd, twocolumn, showpacs, superscriptaddress, amsmath, amssymb | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4294/extracted | aastex | 12pt,manuscript | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4316/extracted | revtex4 | onecolumn,manuscript | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4368/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4369/extracted | \whatSEKIDOCUMENTCLASS | twoside,12pt | 1 | xelatex, no-hyperref | 4 | 4 | 4 | 0.00 | 3 |
| 0905.4371/extracted | amsart | 12pt,a4paper | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| 0905.4380/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4427/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb,prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4439/extracted | aa | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4476/extracted | article | 11 pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4503/extracted | emulateapj | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4556/extracted | revtex4 | aps,prl,twocolumn,showpacs,superscriptaddress,preprintnumbers,amsmath,amssymb | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4656/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4700/extracted | IEEEtran | letterpaper, journal | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
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
| 1003.2165/extracted | llncs | — | 1 | xelatex, non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1003.2182/extracted | PoS | — | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1003.4383/extracted | revtex4 | 12pt,aps,nofootinbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4522/extracted | emulateapj | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4523/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4527/extracted | aa | oldversion | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4562/extracted | eptcs | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| 1003.4720/extracted | revtex4 | preprint,aps,12pt,preprintnumbers,eqsecnum,nofootinbib,superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4727/extracted | article | 10pt,letterpaper,twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4800/extracted | eptcs | copyright,creativecommons,noderivs,noncommercial | 1 | no-hyperref | 4 | 4 | 4 | 0.00 | 1 |
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
| 1012.1026/extracted | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1032/extracted | amsart | 12pt | 1 | — | 3 | 3 | 3 | 0.00 | 0 |
| 1012.1124/extracted | article | 10pt,a4paper,english | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1143/extracted | aipproc | ,final | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1149/extracted | amsart | a4paper, 12pt, leqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1167/extracted | revtex4 | aps,twocolumn,showpacs,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1177/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1195/extracted | ismdproc | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1206/extracted | PoS | cits | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1303/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1313/extracted | article | 12pt | 1 | no-hyperref | 8 | 8 | 8 | 0.00 | 0 |
| 1012.1321/extracted | spie | a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1334/extracted | jac | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1012.1340/extracted | article | 12pt | 1 | no-hyperref | 8 | 8 | 8 | 0.00 | 0 |
| 1012.1389/extracted | article | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1395/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1584/extracted | article | 12pt,aaspp4 | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1587/extracted | article | 12pt | 1 | no-hyperref | 5 | 5 | 5 | 0.00 | 0 |
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
| 1012.5223/extracted | revtex4-1 | aps,prd,twocolumn,showpacs,nofootinbib | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5273/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5359/extracted | aa | traditabstract | 1 | xelatex, no-hyperref | 4 | 4 | 4 | 0.00 | 0 |
| 1012.5411/extracted | revtex4-1 (×10) | reprint, amssymb, amsmath, aip,cha, | 10 | xelatex, non-utf8 | 11 | 11 | 11 | 0.11 | 1 |
| 1012.5491/extracted | revtex4 | aps,preprint,showpacs, showkeys | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5538/extracted | amsart | reqno,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5612/extracted | article | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5679/extracted | aa | structabstract | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5773/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5832/extracted | amsart | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5842/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1664/extracted | aims | — | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1677/extracted | article | 12pt,a4paper,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1707/extracted | revtex4-1 | letterpaper,nofootinbib,prd,amsmath,twocolumn | 1 | — | 1 | 1 | 1 | 0.00 | 0 |

## by class

| class | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| IEEEtran | 4 | 4 | 100.0 | 100.0 | 0.00 |
| IEEEtran1.6b | 1 | 1 | 100.0 | 100.0 | 0.00 |
| JHEP3 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| PoS | 2 | 3 | 100.0 | 100.0 | 0.00 |
| \whatSEKIDOCUMENTCLASS | 2 | 8 | 100.0 | 100.0 | 0.00 |
| aa | 5 | 8 | 100.0 | 100.0 | 0.00 |
| aastex | 8 | 22 | 100.0 | 100.0 | 0.00 |
| aims | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aipproc | 2 | 2 | 100.0 | 100.0 | 0.00 |
| amsart | 23 | 26 | 100.0 | 100.0 | 0.02 |
| amsppt | 1 | 1 | 100.0 | 100.0 | 0.00 |
| an | 1 | 1 | 100.0 | 100.0 | 0.00 |
| article | 55 | 78 | 100.0 | 100.0 | 0.00 |
| arximspdf | 1 | 1 | 100.0 | 100.0 | 0.00 |
| birkjour | 2 | 2 | 100.0 | 100.0 | 0.00 |
| book | 1 | 26 | 100.0 | 100.0 | 0.00 |
| cernrep | 1 | 18 | 100.0 | 100.0 | 0.10 |
| dis07 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsart | 3 | 18 | 100.0 | 100.0 | 0.00 |
| elsarticle | 1 | 1 | 100.0 | 100.0 | 0.00 |
| emulateapj | 6 | 13 | 100.0 | 100.0 | 0.00 |
| eptcs | 2 | 6 | 100.0 | 100.0 | 0.00 |
| imsart | 2 | 2 | 100.0 | 100.0 | 0.00 |
| iopart | 2 | 2 | 100.0 | 100.0 | 0.00 |
| ismdproc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| itrspaper | 1 | 2 | 100.0 | 100.0 | 0.00 |
| jac | 1 | 2 | 100.0 | 100.0 | 0.00 |
| jpconf | 2 | 2 | 100.0 | 100.0 | 0.00 |
| llncs | 4 | 5 | 100.0 | 100.0 | 0.00 |
| mn2e | 2 | 2 | 100.0 | 100.0 | 0.00 |
| pasj00 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| report | 2 | 80 | 100.0 | 100.0 | 0.00 |
| revtex4 | 46 | 48 | 100.0 | 100.0 | 0.00 |
| revtex4-1 | 6 | 16 | 100.0 | 100.0 | 0.08 |
| spie | 1 | 1 | 100.0 | 100.0 | 0.00 |
| svjour | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ws-procs9x6 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| — | 3 | 8 | 100.0 | 100.0 | 0.00 |

## by era

| era | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| new | 170 | 214 | 100.0 | 100.0 | 0.00 |
| — | 30 | 202 | 100.0 | 100.0 | 0.03 |

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
| — | 30 | 202 | 100.0 | 100.0 | 0.03 |

## by cluster_id

| cluster_id | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| C07 | 34 | 35 | 100.0 | 100.0 | 0.00 |
| C08 | 33 | 38 | 100.0 | 100.0 | 0.02 |
| C09 | 33 | 34 | 100.0 | 100.0 | 0.00 |
| C10 | 34 | 68 | 100.0 | 100.0 | 0.00 |
| C11 | 33 | 36 | 100.0 | 100.0 | 0.00 |
| C12 | 3 | 3 | 100.0 | 100.0 | 0.00 |
| — | 30 | 202 | 100.0 | 100.0 | 0.03 |

## by layer

| layer | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| core | 170 | 214 | 100.0 | 100.0 | 0.00 |
| — | 30 | 202 | 100.0 | 100.0 | 0.03 |
