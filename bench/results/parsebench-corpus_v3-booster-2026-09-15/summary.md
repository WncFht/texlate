# parsebench summary — corpus_v3

- papers: 187   files (.tex): 1388   wall: 21.6s
- parse ok: **1388/1388** (100.0%)   errors: 0   measure_errors: 0
- identity: strict **1388** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **19/51966** chunks = 0.04%   hits={'dollar': 19}
- chunk chars: median 227.0   p90 853
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 0
- scan/validate warnings: {'unclosed_env': 83, 'missing_input': 103, 'unpaired_dollar': 10, 'env_mismatch': 2, 'def_parse_fail': 179, 'stray_end': 8, 'if_unterminated': 1}
- flatten coverage: 960 reached / 365 orphan tex / 63 rootless   (触及率 72.5%)

## funnel

| stage | n |
|---|---|
| fetched (manifest rows) | 200 |
| source ok | 200 |
| papers discovered | 187 |
| .tex files | 1388 |
| rooted papers | 181 (multi_doc 25, rootless 6) |
| parse ok | 1388 |
| identity | strict 1388 / normalized 0 / diverged 0 |
| translatable chunks | 51966 |
| leaked chunks | 19 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 0 |
| flatten reached / orphan / rootless | 960 / 365 / 63 |

## gates (docs/09 §8)

| gate | value | 门槛 | verdict |
|---|---|---|---|
| parse ok (file) | 100.0% CI [99.72, 100.00] | 100% & Wilson lb ≥99.5% | PASS |
| strict identity | 100.00% CI [99.72, 100.00] | ≥99.5% | PASS |
| leak rate (chunk) | 0.040% CI [0.023, 0.057] | ≤0.15% | PASS |
| dead/orphan | 0 (chunk 0 + protect 0 + orphan 0) | =0 | PASS |
| flatten coverage | 72.5% (960/1325) | ≥99% † | BELOW |

† coverage 口径勘误 (docs/09 §8 表下): orphan 大头是 e-print 内未被主文件 \input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; v3 实测 ~93%.

## 统计口径 (docs/09 §7.2)

- 权重: 等权退化 (语料无 stratum_cell 或 frame 计数缺失) = raw pooled; bootstrap: 簇键 cluster_id‖yymm‖pid, B=2000, seed=20260915 (无簇键即逐篇 iid)
| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |
|---|---|---|---|---|---|
| parse ok (file) | 100.000% (1388/1388) | 100.000% | 100.000% | [99.724, 100.000] | [100.000, 100.000] |
| strict identity | 100.000% (1388/1388) | 100.000% | 100.000% | [99.724, 100.000] | [100.000, 100.000] |
| leak (chunk) | 0.040% (19/51966) | 0.037% | 0.021% | [0.023, 0.057] | [0.016, 0.061] |
| flatten coverage | 72.45% (960/1325) | 72.45% | 94.97% | — | [58.30, 87.07] |

## leak detail

| file | leaked/trans | hits | leaked-chunk snippets |
|---|---|---|---|
| 0806.0302/extracted/fp420.tex | 1/970 | dollar | ['dollar'] `For the GASTOF detectors, a single photon counter, such as Boston
Electronics SP` |
| 0806.0302/extracted/fp420time-agb.tex | 1/68 | dollar | ['dollar'] `For the GASTOF detectors, a single photon counter, such as Boston
Electronics SP` |
| 1012.5411/extracted/doc/latex/revtex/aps/apsguide4-1.tex | 1/94 | dollar | ['dollar'] `In general, all math markup and the standard math environments from
\LaTeXe\ are` |
| 1706.02464/extracted/broadband_optics/Lens_Alumina.tex | 1/10 | dollar | ['dollar'] `Alumina is a suitable lens material for CMB polarimetry applications due to its ` |
| 1706.02464/extracted/broadband_optics/optics_cmbs4.tex | 1/400 | dollar | ['dollar'] `Alumina is a suitable lens material for CMB polarimetry applications due to its ` |
| 1706.02464/extracted/ms.tex | 1/1080 | dollar | ['dollar'] `Alumina is a suitable lens material for CMB polarimetry applications due to its ` |
| 1803.08835/extracted/text.tex | 1/86 | dollar | ['dollar'] `[[BIB_236]]
D.~C. Cabra, A.~Honecker, P.~Pujol, Magnetization plateaux in \${{N}` |
| 1907.03655/extracted/StakeDag.tex | 1/385 | dollar | ['dollar'] `PoS has a clear benefit (over PoW) since
any node can join the network with even` |
| 1907.03655/extracted/related.tex | 1/38 | dollar | ['dollar'] `PoS has a clear benefit (over PoW) since
any node can join the network with even` |
| 2009.11064/extracted/1-Intro.tex | 1/10 | dollar | ['dollar'] `Consumer credit has exponentially grown over the last few decades, largely spurr` |
| 2009.11064/extracted/ms.tex | 1/94 | dollar | ['dollar'] `Consumer credit has exponentially grown over the last few decades, largely spurr` |
| 2105.11405/extracted/main.tex | 1/204 | dollar | ['dollar'] `The results of the estimates performed point out to mixed results. We find
that ` |
| cs/0501042/extracted/metaschema/implementing-dexa.tex | 3/135 | dollar | ['dollar'] `Second, the exemplary use of the above metaschema for defining a rule is shown b`<br>['dollar'] `\quad \=\quad \=\quad \=\quad \=\quad \=\quad \=\quad \=\quad \=\quad \=\quad \k`<br>['dollar'] `\>[[MATH_393]]\textbf{action} lang=``http://www.w3.org/1999/XSL/Transform"[[MATH` |
| cs/0501042/extracted/metaschema/realizingaxs.tex | 3/30 | dollar | ['dollar'] `Second, the exemplary use of the above metaschema for defining a rule is shown b`<br>['dollar'] `\quad \=\quad \=\quad \=\quad \=\quad \=\quad \=\quad \=\quad \=\quad \=\quad \k`<br>['dollar'] `\>[[MATH_48]]\textbf{action} lang=``http://www.w3.org/1999/XSL/Transform"[[MATH_` |
| math/0111109/extracted/patchy3.tex | 1/353 | dollar | ['dollar'] `Moreover, since
[[MATH_970]] is a classical solution of \, 
[[MATH_971]] \,
on  ` |

## per-paper

| paper | class | options | roots | tags | tex | ok | strict | leak% | orphan-tex |
|---|---|---|---|---|---|---|---|---|---|
| 0707.0167/extracted | article | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1206/extracted | — | — | 0 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.1954/extracted | IEEEtran1.6b | draftcls,onecolumn,12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0707.3972/extracted | report (×3) | — | 3 | reject, xelatex, no-hyperref | 79 | 79 | 79 | 0.00 | 30 |
| 0707.4206/extracted | elsart | letter,seceqn,secthm | 1 | xelatex, no-hyperref | 16 | 16 | 16 | 0.00 | 3 |
| 0806.0302/extracted | cernrep | — | 1 | xelatex | 18 | 18 | 18 | 0.10 | 0 |
| 0806.1415/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 15 | 15 | 15 | 0.00 | 0 |
| 0806.1728/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.3923/extracted | revtex4 | twocolumn,prb,nofootinbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0806.4130/extracted | article | — | 1 | xelatex, no-hyperref | 3 | 3 | 3 | 0.00 | 2 |
| 0905.1566/extracted | llncs | runningheads | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 0905.1619/extracted | elsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.1718/extracted | article | 12pt,titlepage | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 1 |
| 0905.2120/extracted | itrspaper | final | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 0905.2435/extracted | \whatSEKIDOCUMENTCLASS | twoside,12pt | 1 | xelatex, no-hyperref | 4 | 4 | 4 | 0.00 | 3 |
| 0905.4200/extracted | llncs | oribibl | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4368/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4369/extracted | \whatSEKIDOCUMENTCLASS | twoside,12pt | 1 | xelatex, no-hyperref | 4 | 4 | 4 | 0.00 | 3 |
| 0905.4700/extracted | IEEEtran | letterpaper, journal | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1003.2165/extracted | llncs | — | 1 | xelatex, non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1003.4800/extracted | eptcs | copyright,creativecommons,noderivs,noncommercial | 1 | no-hyperref | 4 | 4 | 4 | 0.00 | 1 |
| 1012.1026/extracted | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.1032/extracted | amsart | 12pt | 1 | — | 3 | 3 | 3 | 0.00 | 0 |
| 1012.1313/extracted | article | 12pt | 1 | no-hyperref | 8 | 8 | 8 | 0.00 | 0 |
| 1012.1340/extracted | article | 12pt | 1 | no-hyperref | 8 | 8 | 8 | 0.00 | 0 |
| 1012.1587/extracted | article | 12pt | 1 | no-hyperref | 5 | 5 | 5 | 0.00 | 0 |
| 1012.5223/extracted | revtex4-1 | aps,prd,twocolumn,showpacs,nofootinbib | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5359/extracted | aa | traditabstract | 1 | xelatex, no-hyperref | 4 | 4 | 4 | 0.00 | 0 |
| 1012.5411/extracted | revtex4-1 (×10) | reprint, amssymb, amsmath, aip,cha, | 10 | xelatex, non-utf8 | 11 | 11 | 11 | 0.11 | 1 |
| 1012.5679/extracted | aa | structabstract | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.2031/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 6 | 6 | 6 | 0.00 | 0 |
| 1109.2086/extracted | article | 12pi,epsfig,elsart | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.2284/extracted | mn2e | usenatbib,usegraphicx,useAMS | 1 | xelatex, no-hyperref | 4 | 4 | 4 | 0.00 | 0 |
| 1109.2354/extracted | aipproc (×2) | cmfonts | 2 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1109.2501/extracted | cernphprep | ALICE,manyauthors,12pt | 1 | — | 6 | 6 | 6 | 0.00 | 0 |
| 1109.5595/extracted | aa | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5732/extracted | article (×7) | twoside,11pt,letterpaper | 7 | reject, xelatex, no-hyperref | 44 | 44 | 44 | 0.00 | 21 |
| 1206.5420/extracted | article (×4) | 12pt | 4 | non-utf8, no-hyperref | 4 | 4 | 4 | 0.00 | 0 |
| 1206.5715/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2127/extracted | amsart | 11pt,notitlepage,a4paper,reqno,ps | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6242/extracted | amsart (×2) | 12pt,oneside | 2 | — | 270 | 270 | 270 | 0.00 | 176 |
| 1404.2268/extracted | llncs | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2471/extracted | article | a4paper,11pt,english,oneside | 1 | xelatex, no-hyperref | 12 | 12 | 12 | 0.00 | 2 |
| 1404.5809/extracted | article | 11pt | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5828/extracted | IEEEtran | 12pt,draftcls,onecolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.01978/extracted | revtex4 | aps,prc,twocolumn,superscriptaddress,nofootinbib | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1502.02023/extracted | article | 11pt,a4paper | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06414/extracted | revtex4-1 | aps, pra, twocolumn, groupedaddress, showpacs, floatfix, amsmath, amssymb, | 1 | xelatex | 1 | 1 | 1 | — | 0 |
| 1502.06597/extracted | emulateapj | apj | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02747/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02851/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06717/extracted | aa | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06728/extracted | elsarticle | preprint,5p,twocolumn | 1 | xelatex, no-hyperref | 7 | 7 | 7 | 0.00 | 0 |
| 1511.06770/extracted | mn2e (×2) | useAMS,usenatbib,twoside | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1608.02223/extracted | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02435/extracted | spie | — | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02624/extracted | revtex4-1 | aip, jcp, showpacs, superscriptaddress, preprint ,11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.07004/extracted | revtex4-1 | preprint, showpacs, amsmath,amssymb, showkeys aps, | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02389/extracted | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02393/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02400/extracted | acmart | sigplan,10pt | 1 | no-hyperref | 9 | 9 | 9 | 0.00 | 0 |
| 1706.02464/extracted | tcibook (×2) | titlepage | 2 | — | 97 | 97 | 97 | 0.09 | 11 |
| 1706.02509/extracted | acmart | sigconf | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02513/extracted | article | twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02613/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02637/extracted | article | a4paper | 1 | — | 1 | 1 | 1 | — | 0 |
| 1706.02737/extracted | article | a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02759/extracted | article | preprint,12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02769/extracted | IEEEtran | 10pt, conference | 1 | — | 10 | 10 | 10 | 0.00 | 1 |
| 1706.07759/extracted | revtex4 | aps,epsf,amsfonts,floats,twocolumn,amssymb,amsmath,groupedaddress,showpacs,floatfix,nofootinbib | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07855/extracted | revtex4-1 | prb,preprint | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07863/extracted | IEEEtran | journal | 1 | non-utf8 | 23 | 23 | 23 | 0.00 | 3 |
| 1706.07890/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.02892/extracted | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.02900/extracted | IEEEtran | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.02902/extracted | memoir | 10pt,twoside,openright | 1 | — | 19 | 19 | 19 | 0.00 | 0 |
| 1803.02944/extracted | IEEEtran | journal,twocolumn,10pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.02950/extracted | IEEEtran | journal,12pt,onecolumn,draftclsnofoot | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.02985/extracted | standalone (×12) | — | 12 | no-hyperref | 24 | 24 | 24 | 0.00 | 0 |
| 1803.03089/extracted | article | 12pt,letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03145/extracted | IEEEtran | conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03158/extracted | mystyle | a4paper,UKenglish | 1 | — | 16 | 16 | 16 | 0.00 | 0 |
| 1803.03168/extracted | elsarticle (×2) | final,3p,times | 2 | xelatex, non-utf8 | 2 | 2 | 2 | 0.00 | 0 |
| 1803.03185/extracted | acmart (×2) | sigconf | 2 | — | 53 | 53 | 53 | 0.00 | 41 |
| 1803.03221/extracted | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.08835/extracted | elsarticle | final,onecolumn,3p,times,sort&compress | 1 | — | 1 | 1 | 1 | 1.16 | 0 |
| 1803.08868/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.09100/extracted | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03451/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03455/extracted | osajnl | 9pt,twocolumn,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03579/extracted | article | a4paper,final,12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03643/extracted | article | 11pt,letterpaper | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1811.10096/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10109/extracted | IEEEtran | conference | 1 | — | 12 | 12 | 12 | 0.00 | 0 |
| 1907.03655/extracted | article | — | 1 | no-hyperref | 8 | 8 | 8 | 0.26 | 0 |
| 1907.03672/extracted | amsart (×2) | 12pt | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1907.03756/extracted | IEEEtran (×2) | conference | 2 | xelatex | 19 | 19 | 19 | 0.00 | 2 |
| 1907.10317/extracted | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10349/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10381/extracted | eptcs | submission,copyright,creativecommons | 1 | non-utf8, no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| 2003.03461/extracted | article (×2) | — | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2003.03561/extracted | revtex4-1 | pra,twocolumn,showpacs,superscriptaddress,preprintnumbers,amsmath,amssymb,aps | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10664/extracted | IEEEtran (×2) | conference | 2 | xelatex | 17 | 17 | 17 | 0.00 | 4 |
| 2003.10737/extracted | IEEEtran | draftclsnofoot,onecolumn | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10931/extracted | IEEEtran | conference | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10973/extracted | article | 11pt | 1 | — | 4 | 4 | 4 | 0.00 | 0 |
| 2009.03719/extracted | article | 11pt, oneside | 1 | — | 19 | 19 | 19 | 0.00 | 5 |
| 2009.03740/extracted | acmart | 10pt,sigconf,letterpaper | 1 | no-hyperref | 14 | 14 | 14 | 0.00 | 3 |
| 2009.03754/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.11007/extracted | article (×2) | a4paper,12pt | 2 | — | 11 | 11 | 11 | 0.00 | 1 |
| 2009.11064/extracted | article | a4paper, 11pt, final | 1 | — | 9 | 9 | 9 | 1.04 | 0 |
| 2105.03746/extracted | article (×4) | — | 4 | — | 6 | 6 | 6 | 0.00 | 0 |
| 2105.03820/extracted | revtex4-1 | reprint, aps, | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11374/extracted | — | — | 0 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11376/extracted | IEEEtran | english | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11390/extracted | amsart | 11pt | 1 | minted | 3 | 3 | 3 | 0.00 | 0 |
| 2105.11405/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.49 | 0 |
| 2105.11472/extracted | mnras (×4) | twocolumn,usenatbib | 4 | no-hyperref | 4 | 4 | 4 | 0.00 | 0 |
| 2203.04295/extracted | llncs (×2) | runningheads | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2203.04310/extracted | IEEEtran | journal,comsoc | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04356/extracted | article (×2) | 11pt | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2203.12985/extracted | IEEEtran | 10pt,journal,compsoc | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.12986/extracted | iopart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13097/extracted | elsarticle | review | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13106/extracted | ws-ijmpe | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04465/extracted | revtex4-2 | aps,pra,nofootinbib,floatfix,preprintnumbers,tightenlines,11pt,superscriptaddress | 1 | — | 6 | 6 | 6 | 0.00 | 0 |
| 2211.04505/extracted | sn-jnl (×4) | sn-nature,Numbered | 4 | xelatex, non-utf8 | 7 | 7 | 7 | 0.00 | 1 |
| 2211.04540/extracted | IEEEtran | conference, 10pt | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 2211.12985/extracted | amsart | 11pt | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13002/extracted | scrartcl (×2) | parskip=half, twoside=false | 2 | — | 32 | 32 | 32 | 0.00 | 4 |
| 2211.13021/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13028/extracted | siamart220329 | onefignum,onetabnum,final | 1 | no-hyperref | 18 | 18 | 18 | 0.00 | 1 |
| 2308.04222/extracted | book | a4paper,12pt | 1 | — | 15 | 15 | 15 | 0.00 | 0 |
| 2308.04228/extracted | — | — | 0 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12676/extracted | article | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.05490/extracted | article (×2) | — | 2 | xelatex | 38 | 38 | 38 | 0.00 | 22 |
| 2403.05529/extracted | article | — | 1 | xelatex | 13 | 13 | 13 | 0.00 | 0 |
| 2403.05546/extracted | ieeeconf | a4paper, 10pt, conference | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15072/extracted | elsarticle | final,5p,times,twocolumn | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15145/extracted | IEEEtran | journal,10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15158/extracted | revtex4 | prd,showpacs,amsmath,amssymb,superscriptaddress,nofootinbib,showkeys | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.06008/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | non-utf8, no-hyperref | 8 | 8 | 8 | 0.00 | 0 |
| 2410.06020/extracted | article | — | 1 | — | 21 | 21 | 21 | 0.00 | 6 |
| 2410.06037/extracted | article | 12pt,a4paper,english | 1 | no-hyperref | 22 | 22 | 22 | 0.00 | 13 |
| 2410.17921/extracted | appolb | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17928/extracted | acmart | nonacm,sigplan | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17962/extracted | article | ecta,12pt, a4paper, english, leqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17973/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.18017/extracted | scrartcl (×2) | a4paper | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| astro-ph/0111599 | article | aasms4 | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307377 | mn | psfig,amssymb | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0605227 | iopart | 12pt | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9703184 | article | 11pt,moriond,psfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9910247 | — | — | 0 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9910477 | article | 11pt,aaspp4 | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0501221 | article | — | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| cond-mat/9703030 | revtex | preprint,prb,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9703084 | — | — | 0 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9910148 | revtex | prx,amssymb,prb,aps,pstricks,epsfig,twoside | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cs/0501042 | — | — | 0 | xelatex, non-utf8, no-hyperref | 58 | 58 | 58 | 0.32 | 0 |
| cs/0605127 | article | 12pt,titlepage | 1 | non-utf8, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| gr-qc/0307019 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ex/0307068 | ./LaTeX/zeus/zeus_paper (×7) | zpreprint,zbstepj | 7 | xelatex, non-utf8, no-hyperref | 55 | 55 | 55 | 0.00 | 2 |
| hep-ex/0605023 | revtex4 | aps,twocolumn,prl,superscriptaddress,showpacs | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| hep-ph/0111328 | svmult | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0501170 | article | dvips,12pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910434 | article | epsf | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910555 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703214 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9910234 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math-ph/0111031 | article | 11pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0111107 | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0111109 | amsppt | — | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.28 | 0 |
| math/0111238 | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0307008 | amsart | 12pt,leqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| math/0501228 | article | amssymb,amstex | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0501455 | amsppt | — | 1 | reject, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0605284 | amsart | reqno, 12pt | 1 | xelatex, non-utf8, no-hyperref | 5 | 5 | 5 | 0.00 | 0 |
| math/9910058 | amsart | 12pt,reqno | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/9910162 | 709 | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-ex/0111004 | report | 11pt,letterpaper | 1 | xelatex, non-utf8, no-hyperref | 14 | 14 | 14 | 0.00 | 0 |
| nucl-ex/0501017 | scrreprt | BCOR2.0cm,DIV14,twoside,12pt, abstracton,smallheadings,cleardoubleempty, openright,pagesize,abstractoff,bibtotoc | 1 | non-utf8 | 16 | 16 | 16 | 0.00 | 1 |
| nucl-th/0111010 | article | epsfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/9703052 | revtex | preprint,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| physics/0307013 | revtex | 12pt,epsf,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| physics/0501018 | revtex4 | pre,showpacs,preprintnumbers | 1 | non-utf8, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| physics/0501058 | article | aipmod,eqalign,graphicx,times | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |

## by class

| class | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| ./LaTeX/zeus/zeus_paper | 1 | 55 | 100.0 | 100.0 | 0.00 |
| 709 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| IEEEtran | 18 | 94 | 100.0 | 100.0 | 0.00 |
| IEEEtran1.6b | 1 | 1 | 100.0 | 100.0 | 0.00 |
| \whatSEKIDOCUMENTCLASS | 2 | 8 | 100.0 | 100.0 | 0.00 |
| aa | 4 | 7 | 100.0 | 100.0 | 0.00 |
| aastex | 2 | 21 | 100.0 | 100.0 | 0.00 |
| acmart | 5 | 78 | 100.0 | 100.0 | 0.00 |
| aipproc | 1 | 2 | 100.0 | 100.0 | 0.00 |
| amsart | 12 | 290 | 100.0 | 100.0 | 0.00 |
| amsppt | 11 | 11 | 100.0 | 100.0 | 0.05 |
| appolb | 1 | 1 | 100.0 | 100.0 | 0.00 |
| article | 61 | 286 | 100.0 | 100.0 | 0.04 |
| book | 1 | 15 | 100.0 | 100.0 | 0.00 |
| cernphprep | 1 | 6 | 100.0 | 100.0 | 0.00 |
| cernrep | 1 | 18 | 100.0 | 100.0 | 0.10 |
| elsart | 2 | 17 | 100.0 | 100.0 | 0.00 |
| elsarticle | 5 | 12 | 100.0 | 100.0 | 0.11 |
| emulateapj | 1 | 1 | 100.0 | 100.0 | 0.00 |
| eptcs | 2 | 6 | 100.0 | 100.0 | 0.00 |
| ieeeconf | 2 | 9 | 100.0 | 100.0 | 0.00 |
| iopart | 2 | 2 | 100.0 | 100.0 | 0.00 |
| itrspaper | 1 | 2 | 100.0 | 100.0 | 0.00 |
| llncs | 5 | 7 | 100.0 | 100.0 | 0.00 |
| memoir | 1 | 19 | 100.0 | 100.0 | 0.00 |
| mn | 1 | 1 | 100.0 | 100.0 | 0.00 |
| mn2e | 2 | 6 | 100.0 | 100.0 | 0.00 |
| mnras | 1 | 4 | 100.0 | 100.0 | 0.00 |
| mystyle | 1 | 16 | 100.0 | 100.0 | 0.00 |
| osajnl | 1 | 1 | 100.0 | 100.0 | 0.00 |
| report | 2 | 93 | 100.0 | 100.0 | 0.00 |
| revtex | 4 | 4 | 100.0 | 100.0 | 0.00 |
| revtex4 | 6 | 8 | 100.0 | 100.0 | 0.00 |
| revtex4-1 | 8 | 18 | 100.0 | 100.0 | 0.06 |
| revtex4-2 | 1 | 6 | 100.0 | 100.0 | 0.00 |
| scrartcl | 2 | 34 | 100.0 | 100.0 | 0.00 |
| scrreprt | 1 | 16 | 100.0 | 100.0 | 0.00 |
| siamart220329 | 1 | 18 | 100.0 | 100.0 | 0.00 |
| sn-jnl | 1 | 7 | 100.0 | 100.0 | 0.00 |
| spie | 1 | 1 | 100.0 | 100.0 | 0.00 |
| standalone | 1 | 24 | 100.0 | 100.0 | 0.00 |
| svmult | 1 | 1 | 100.0 | 100.0 | 0.00 |
| tcibook | 1 | 97 | 100.0 | 100.0 | 0.09 |
| ws-ijmpe | 1 | 1 | 100.0 | 100.0 | 0.00 |
| — | 6 | 63 | 100.0 | 100.0 | 0.29 |

## by era

| era | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| new | 149 | 1203 | 100.0 | 100.0 | 0.03 |
| old | 38 | 185 | 100.0 | 100.0 | 0.09 |

## by archive

| archive | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| astro-ph | 6 | 6 | 100.0 | 100.0 | 0.00 |
| cond-mat | 4 | 5 | 100.0 | 100.0 | 0.00 |
| cs | 2 | 60 | 100.0 | 100.0 | 0.31 |
| gr-qc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| hep-ex | 2 | 57 | 100.0 | 100.0 | 0.00 |
| hep-ph | 4 | 4 | 100.0 | 100.0 | 0.00 |
| hep-th | 2 | 2 | 100.0 | 100.0 | 0.00 |
| math | 9 | 13 | 100.0 | 100.0 | 0.06 |
| math-ph | 1 | 1 | 100.0 | 100.0 | 0.00 |
| nucl-ex | 2 | 30 | 100.0 | 100.0 | 0.00 |
| nucl-th | 2 | 2 | 100.0 | 100.0 | 0.00 |
| physics | 3 | 4 | 100.0 | 100.0 | 0.00 |
| — | 149 | 1203 | 100.0 | 100.0 | 0.03 |

## by stratum_cell

| stratum_cell | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| booster|a_pre2007 | 38 | 185 | 100.0 | 100.0 | 0.09 |
| booster|b_2007_11 | 37 | 266 | 100.0 | 100.0 | 0.02 |
| booster|c_2012_16 | 21 | 311 | 100.0 | 100.0 | 0.00 |
| booster|d_2017_20 | 53 | 405 | 100.0 | 100.0 | 0.05 |
| booster|e_2021_25 | 38 | 221 | 100.0 | 100.0 | 0.01 |

## by cluster_id

| cluster_id | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| C01 | 5 | 5 | 100.0 | 100.0 | 0.00 |
| C02 | 8 | 8 | 100.0 | 100.0 | 0.00 |
| C03 | 8 | 21 | 100.0 | 100.0 | 0.04 |
| C04 | 5 | 59 | 100.0 | 100.0 | 0.00 |
| C05 | 8 | 82 | 100.0 | 100.0 | 0.17 |
| C06 | 4 | 10 | 100.0 | 100.0 | 0.00 |
| C07 | 5 | 98 | 100.0 | 100.0 | 0.00 |
| C08 | 5 | 38 | 100.0 | 100.0 | 0.08 |
| C09 | 9 | 19 | 100.0 | 100.0 | 0.00 |
| C10 | 2 | 5 | 100.0 | 100.0 | 0.00 |
| C11 | 9 | 42 | 100.0 | 100.0 | 0.04 |
| C12 | 7 | 64 | 100.0 | 100.0 | 0.00 |
| C13 | 2 | 5 | 100.0 | 100.0 | 0.00 |
| C14 | 2 | 271 | 100.0 | 100.0 | 0.00 |
| C15 | 4 | 15 | 100.0 | 100.0 | 0.00 |
| C16 | 4 | 4 | 100.0 | 100.0 | 0.00 |
| C17 | 5 | 12 | 100.0 | 100.0 | 0.00 |
| C18 | 4 | 4 | 100.0 | 100.0 | 0.00 |
| C19 | 15 | 150 | 100.0 | 100.0 | 0.06 |
| C20 | 15 | 124 | 100.0 | 100.0 | 0.01 |
| C21 | 6 | 18 | 100.0 | 100.0 | 0.00 |
| C22 | 6 | 33 | 100.0 | 100.0 | 0.11 |
| C23 | 6 | 26 | 100.0 | 100.0 | 0.00 |
| C24 | 5 | 54 | 100.0 | 100.0 | 0.16 |
| C25 | 7 | 17 | 100.0 | 100.0 | 0.06 |
| C26 | 7 | 9 | 100.0 | 100.0 | 0.00 |
| C27 | 7 | 66 | 100.0 | 100.0 | 0.00 |
| C28 | 3 | 17 | 100.0 | 100.0 | 0.00 |
| C29 | 6 | 55 | 100.0 | 100.0 | 0.00 |
| C30 | 8 | 57 | 100.0 | 100.0 | 0.00 |

## by layer

| layer | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| booster | 187 | 1388 | 100.0 | 100.0 | 0.04 |
