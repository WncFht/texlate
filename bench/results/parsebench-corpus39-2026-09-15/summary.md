# parsebench summary — corpus

- papers: 39   files (.tex): 256   wall: 9.0s
- parse ok: **256/256** (100.0%)   errors: 0   measure_errors: 0
- identity: strict **256** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **1/23928** chunks = 0.00%   hits={'dollar': 1}
- chunk chars: median 188.0   p90 698
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 0
- scan/validate warnings: {'unclosed_env': 74, 'def_parse_fail': 307, 'missing_input': 2, 'unpaired_dollar': 1}
- flatten coverage: 240 reached / 16 orphan tex / 0 rootless   (触及率 93.8%)

## funnel

| stage | n |
|---|---|
| papers discovered | 39 |
| .tex files | 256 |
| rooted papers | 39 (multi_doc 3, rootless 0) |
| parse ok | 256 |
| identity | strict 256 / normalized 0 / diverged 0 |
| translatable chunks | 23928 |
| leaked chunks | 1 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 0 |
| flatten reached / orphan / rootless | 240 / 16 / 0 |

## gates (docs/09 §8)

| gate | value | 门槛 | verdict |
|---|---|---|---|
| parse ok (file) | 100.0% CI [98.52, 100.00] | 100% & Wilson lb ≥99.5% | PASS(low-n) |
| strict identity | 100.00% CI [98.52, 100.00] | ≥99.5% | PASS |
| leak rate (chunk) | 0.000% CI [0.001, 0.024] | ≤0.15% | PASS |
| dead/orphan | 0 (chunk 0 + protect 0 + orphan 0) | =0 | PASS |
| flatten coverage | 93.8% (240/256) | ≥99% † | BELOW |

† coverage 口径勘误 (docs/09 §8 表下): orphan 大头是 e-print 内未被主文件 \input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; v3 实测 ~93%.

## 统计口径 (docs/09 §7.2)

- 权重: 等权退化 (语料无 stratum_cell 或 frame 计数缺失) = raw pooled; bootstrap: 簇键 cluster_id‖yymm‖pid, B=2000, seed=20260915 (无簇键即逐篇 iid)
| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |
|---|---|---|---|---|---|
| parse ok (file) | 100.000% (256/256) | 100.000% | 100.000% | [98.522, 100.000] | [100.000, 100.000] |
| strict identity | 100.000% (256/256) | 100.000% | 100.000% | [98.522, 100.000] | [100.000, 100.000] |
| leak (chunk) | 0.000% (1/23928) | 0.004% | 0.002% | [0.001, 0.024] | [0.000, 0.015] |
| flatten coverage | 93.75% (240/256) | 93.75% | 93.50% | — | [87.50, 97.93] |

## leak detail

| file | leaked/trans | hits | leaked-chunk snippets |
|---|---|---|---|
| 2501.14787/psets/Pset1sol.tex | 1/25 | dollar | ['dollar'] `[[MATH_140]], with vector inputs [[MATH_141]] and matrix outputs [[MATH_142]].  ` |

## per-paper

| paper | class | options | roots | tags | tex | ok | strict | leak% | orphan-tex |
|---|---|---|---|---|---|---|---|---|---|
| 0807.3917 | IEEEtran | journal,letterpaper,final,twocolumn | 1 | xelatex, non-utf8, no-hyperref | 11 | 11 | 11 | 0.00 | 0 |
| 0906.1291 | revtex4 | aps,pre,nofootinbib,showpacs,tightenlines,preprint,titlepage,amsmath | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0906.4725 | iopart | — | 1 | non-utf8, no-hyperref | 3 | 3 | 3 | 0.00 | 1 |
| 1106.1445 | book | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1111.4914 | amsart | a4paper, reqno, 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1207.7214 | elsarticle | final,3p,times,twocolumn | 1 | xelatex | 2 | 2 | 2 | 0.00 | 0 |
| 1207.7235 | cms-tdr | 11pt,twoside,a4paper,cmspaper,final | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1403.3985 | revtex4-1 | prd,reprint,showpacs,superscriptaddress,bibnotes | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 1412.6980 | article | a4paper | 1 | — | 1 | 1 | 1 | — | 0 |
| 1502.01589 | aa | traditabstract,longauth | 1 | — | 35 | 35 | 35 | 0.00 | 0 |
| 1507.02284 | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06432 | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1512.03385 | article | 10pt,twocolumn,letterpaper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1612.09375 | cambridge7A | spanningrule | 1 | — | 18 | 18 | 18 | 0.00 | 0 |
| 1706.03762 | article | — | 1 | — | 10 | 10 | 10 | 0.00 | 2 |
| 1712.01208 | article | 11pt | 1 | — | 12 | 12 | 12 | 0.00 | 3 |
| 1801.02634 | aastex61 | modern | 1 | no-hyperref | 5 | 5 | 5 | 0.00 | 1 |
| 1810.04805 | article | 11pt,a4paper | 1 | no-hyperref | 20 | 20 | 20 | 0.00 | 0 |
| 1902.03178 | quantumarticle | a4paper,onecolumn,superscriptaddress,11pt,accepted=2020-04-27 | 1 | — | 6 | 6 | 6 | 0.00 | 5 |
| 1906.08237 | article | — | 1 | — | 10 | 10 | 10 | 0.00 | 0 |
| 2003.08934 | llncs | runningheads | 1 | no-hyperref | 9 | 9 | 9 | 0.00 | 0 |
| 2005.11401 | article | — | 1 | — | 10 | 10 | 10 | 0.00 | 1 |
| 2106.09685 | article | — | 1 | — | 3 | 3 | 3 | 0.00 | 0 |
| 2201.05989 | acmart (×2) | acmtog,authorversion,nonacm | 2 | no-hyperref | 18 | 18 | 18 | 0.00 | 0 |
| 2203.02155 | article | — | 1 | — | 6 | 6 | 6 | 0.00 | 0 |
| 2305.14335 | IEEEtran | journal | 1 | — | 7 | 7 | 7 | 0.00 | 0 |
| 2308.07483 | revtex4-2 | aip, cp, amsmath,amssymb, reprint, | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2501.14787 | article (×5) | — | 5 | minted | 20 | 20 | 20 | 0.07 | 0 |
| 2512.03164 | amsart | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2602.06617 | article | 10pt,leqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2602.09511 | amsart | 12pt,french | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2602.19229 | acmart | manuscript,natbib=false,nonacm | 1 | — | 12 | 12 | 12 | 0.00 | 1 |
| 2606.31863 | eptcs | submission,copyright,creativecommons | 1 | — | 3 | 3 | 3 | 0.00 | 1 |
| 2609.06443 | subfiles (×12) | main.tex | 12 | — | 13 | 13 | 13 | 0.00 | 0 |
| 2609.08578 | acmart | acmsmall, screen, authorversion, nonacm | 1 | no-hyperref | 5 | 5 | 5 | 0.00 | 1 |
| 2609.09529 | elsarticle | final,12pt,times | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2609.11777 | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9901001 | ptptex | epsf,seceq,preprint | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0404188 | amsart | 12pt,a4paper,reqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |

## by class

| class | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| IEEEtran | 2 | 18 | 100.0 | 100.0 | 0.00 |
| aa | 1 | 35 | 100.0 | 100.0 | 0.00 |
| aastex61 | 1 | 5 | 100.0 | 100.0 | 0.00 |
| acmart | 3 | 35 | 100.0 | 100.0 | 0.00 |
| amsart | 4 | 4 | 100.0 | 100.0 | 0.00 |
| article | 14 | 97 | 100.0 | 100.0 | 0.02 |
| book | 1 | 1 | 100.0 | 100.0 | 0.00 |
| cambridge7A | 1 | 18 | 100.0 | 100.0 | 0.00 |
| cms-tdr | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsarticle | 2 | 3 | 100.0 | 100.0 | 0.00 |
| eptcs | 1 | 3 | 100.0 | 100.0 | 0.00 |
| iopart | 1 | 3 | 100.0 | 100.0 | 0.00 |
| llncs | 1 | 9 | 100.0 | 100.0 | 0.00 |
| ptptex | 1 | 1 | 100.0 | 100.0 | 0.00 |
| quantumarticle | 1 | 6 | 100.0 | 100.0 | 0.00 |
| revtex4 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| revtex4-1 | 1 | 2 | 100.0 | 100.0 | 0.00 |
| revtex4-2 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| subfiles | 1 | 13 | 100.0 | 100.0 | 0.00 |
