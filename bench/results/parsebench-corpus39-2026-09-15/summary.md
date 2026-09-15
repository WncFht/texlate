# parsebench summary — corpus

- papers: 39   files (.tex): 256   wall: 103.7s
- parse ok: **256/256** (100.0%)   errors: 0
- identity: strict **256** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **25/23400** chunks = 0.11%   hits={'dollar': 18, 'begin_env': 3, 'conditional': 4}
- chunk chars: median 178.0   p90 656
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 5333
- flatten coverage: 207 reached / 49 orphan tex / 0 rootless

## funnel

| stage | n |
|---|---|
| papers discovered | 39 |
| .tex files | 256 |
| rooted papers | 39 (multi_doc 3, rootless 0) |
| parse ok | 256 |
| identity | strict 256 / normalized 0 / diverged 0 |
| translatable chunks | 23400 |
| leaked chunks | 25 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 5333 |
| flatten reached / orphan / rootless | 207 / 49 / 0 |

## leak detail

| file | leaked/trans | hits | leaked-chunk snippets |
|---|---|---|---|
| 0807.3917/main.tex | 1/313 | dollar | ['dollar'] `The decision functions [[MATH_597]] defined above resemble ML decision functions` |
| 1507.02284/sieve.tex | 1/110 | dollar | ['dollar'] `A simple example for which we imagine we have samples of [[MATH_144]] drawn from` |
| 1612.09375/cfnt.tex | 1/362 | dollar | ['dollar'] `[[LABEL_458]] 
Given any set [[MATH_459]], one can build the [[CMD_460]][[MATH_4` |
| 1612.09375/intro.tex | 1/74 | dollar | ['dollar'] `spaces [[MATH_139]], [[MATH_140]] and [[MATH_141]], a [[CMD_142]]om U \times V \` |
| 1612.09375/sets.tex | 1/208 | dollar | ['dollar'] `[[LABEL_318]]
The [[CMD_319]]ta\from \Set \to \Set \times \Set[[MATH_320]]\Delta` |
| 1906.08237/exp.tex | 1/31 | dollar | ['dollar'] `\small
%    A single model XLNet outperforms human and the best ensemble by 7.6 ` |
| 1906.08237/neurips_2019.tex | 1/162 | dollar | ['dollar'] `\small
%    A single model XLNet outperforms human and the best ensemble by 7.6 ` |
| 2003.08934/arxiv_submission.tex | 1/107 | dollar | ['dollar'] `Our method quantitatively outperforms prior work on datasets of both synthetic a` |
| 2003.08934/resultstable.tex | 1/1 | dollar | ['dollar'] `Our method quantitatively outperforms prior work on datasets of both synthetic a` |
| 2201.05989/paper.tex | 2/175 | dollar | ['dollar'] `However, the dense grid is wasteful in two ways. First, it allocates as many fea`<br>['dollar'] `[[LABEL_447]]%
    Approximating an RGB image of resolution [[CMD_448]]es[[MATH_` |
| 2501.14787/psets/Pset1sol.tex | 2/26 | dollar,begin_env | ['begin_env'] `[[MATH_65]], where the inputs [[MATH_66]] are vectors, the outputs are scalars, `<br>['dollar'] `[[MATH_140]], with vector inputs [[MATH_141]] and matrix outputs [[MATH_142]].  ` |
| 2602.19229/arxiv.tex | 2/316 | dollar | ['dollar'] `[[CMD_1084]]mC{[[MATH_1085]]}
    [[CMD_1086]] \in \UniAnaRuleSet_\omega[[MATH_1`<br>['dollar'] `[[LABEL_1575]]
For 
an [[CMD_1576]]perA_0[[MATH_1577]]\omega[[MATH_1578]]T_{\ome` |
| 2602.19229/tex/structure.tex | 2/310 | dollar | ['dollar'] `[[CMD_1061]]mC{[[MATH_1062]]}
    [[CMD_1063]] \in \UniAnaRuleSet_\omega[[MATH_1`<br>['dollar'] `[[LABEL_1552]]
For 
an [[CMD_1553]]perA_0[[MATH_1554]]\omega[[MATH_1555]]T_{\ome` |
| 2602.19229/tex/ub-flew-calculus.tex | 1/70 | dollar | ['dollar'] `[[CMD_149]]mC{[[MATH_150]]}
    [[CMD_151]] \in \UniAnaRuleSet_\omega[[MATH_152]` |
| 2602.19229/tex/ub-flew-proof-search.tex | 1/62 | dollar | ['dollar'] `[[LABEL_114]]
For 
an [[CMD_115]]perA_0[[MATH_116]]\omega[[MATH_117]]T_{\omega}(` |
| 2609.08578/Paper-with-appendices.tex | 3/937 | begin_env,conditional | ['conditional'] `The definition of the general rules for identity
  types, with support for arbit`<br>['conditional'] `This definition
  is based on a suggestion from \ifAnonymous{[\emph{name omitted`<br>['begin_env'] `The
  functions are η-expanded to give them suitable types:
  \begin{code}[hide]` |
| 2609.08578/Paper.processed.tex | 3/937 | begin_env,conditional | ['conditional'] `The definition of the general rules for identity
  types, with support for arbit`<br>['conditional'] `This definition
  is based on a suggestion from \ifAnonymous{[\emph{name omitted`<br>['begin_env'] `The
  functions are η-expanded to give them suitable types:
  \begin{code}[hide]` |

## per-paper

| paper | class | options | roots | tags | tex | ok | strict | leak% | orphan-tex |
|---|---|---|---|---|---|---|---|---|---|
| 0807.3917 | IEEEtran | journal,letterpaper,final,twocolumn | 1 | xelatex, non-utf8, no-hyperref | 11 | 11 | 11 | 0.31 | 0 |
| 0906.1291 | revtex4 | aps,pre,nofootinbib,showpacs,tightenlines,preprint,titlepage,amsmath | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0906.4725 | iopart | — | 1 | non-utf8, no-hyperref | 3 | 3 | 3 | 0.00 | 1 |
| 1106.1445 | book | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1111.4914 | amsart | a4paper, reqno, 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1207.7214 | elsarticle | final,3p,times,twocolumn | 1 | xelatex | 2 | 2 | 2 | 0.00 | 0 |
| 1207.7235 | cms-tdr | 11pt,twoside,a4paper,cmspaper,final | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1403.3985 | revtex4-1 | prd,reprint,showpacs,superscriptaddress,bibnotes | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 1412.6980 | article | a4paper | 1 | — | 1 | 1 | 1 | — | 0 |
| 1502.01589 | aa | traditabstract,longauth | 1 | — | 35 | 35 | 35 | 0.00 | 33 |
| 1507.02284 | article | — | 1 | — | 1 | 1 | 1 | 0.91 | 0 |
| 1511.06432 | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1512.03385 | article | 10pt,twocolumn,letterpaper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1612.09375 | cambridge7A | spanningrule | 1 | — | 18 | 18 | 18 | 0.08 | 0 |
| 1706.03762 | article | — | 1 | — | 10 | 10 | 10 | 0.00 | 2 |
| 1712.01208 | article | 11pt | 1 | — | 12 | 12 | 12 | 0.00 | 3 |
| 1801.02634 | aastex61 | modern | 1 | no-hyperref | 5 | 5 | 5 | 0.00 | 1 |
| 1810.04805 | article | 11pt,a4paper | 1 | no-hyperref | 20 | 20 | 20 | 0.00 | 0 |
| 1902.03178 | quantumarticle | a4paper,onecolumn,superscriptaddress,11pt,accepted=2020-04-27 | 1 | — | 6 | 6 | 6 | 0.00 | 5 |
| 1906.08237 | article | — | 1 | — | 10 | 10 | 10 | 0.62 | 0 |
| 2003.08934 | llncs | runningheads | 1 | no-hyperref | 9 | 9 | 9 | 1.63 | 0 |
| 2005.11401 | article | — | 1 | — | 10 | 10 | 10 | 0.00 | 1 |
| 2106.09685 | article | — | 1 | — | 3 | 3 | 3 | 0.00 | 0 |
| 2201.05989 | acmart (×2) | acmtog,authorversion,nonacm | 2 | no-hyperref | 18 | 18 | 18 | 0.97 | 0 |
| 2203.02155 | article | — | 1 | — | 6 | 6 | 6 | 0.00 | 0 |
| 2305.14335 | IEEEtran | journal | 1 | — | 7 | 7 | 7 | 0.00 | 0 |
| 2308.07483 | revtex4-2 | aip, cp, amsmath,amssymb, reprint, | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2501.14787 | article (×5) | — | 5 | minted | 20 | 20 | 20 | 0.14 | 0 |
| 2512.03164 | amsart | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2602.06617 | article | 10pt,leqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2602.09511 | amsart | 12pt,french | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2602.19229 | acmart | manuscript,natbib=false,nonacm | 1 | — | 12 | 12 | 12 | 0.63 | 1 |
| 2606.31863 | eptcs | submission,copyright,creativecommons | 1 | — | 3 | 3 | 3 | 0.00 | 1 |
| 2609.06443 | subfiles (×12) | main.tex | 12 | — | 13 | 13 | 13 | 0.00 | 0 |
| 2609.08578 | acmart | acmsmall, screen, authorversion, nonacm | 1 | no-hyperref | 5 | 5 | 5 | 0.31 | 1 |
| 2609.09529 | elsarticle | final,12pt,times | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2609.11777 | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9901001 | ptptex | epsf,seceq,preprint | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0404188 | amsart | 12pt,a4paper,reqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |

## by class

| class | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| IEEEtran | 2 | 18 | 100.0 | 100.0 | 0.20 |
| aa | 1 | 35 | 100.0 | 100.0 | 0.00 |
| aastex61 | 1 | 5 | 100.0 | 100.0 | 0.00 |
| acmart | 3 | 35 | 100.0 | 100.0 | 0.45 |
| amsart | 4 | 4 | 100.0 | 100.0 | 0.00 |
| article | 14 | 97 | 100.0 | 100.0 | 0.10 |
| book | 1 | 1 | 100.0 | 100.0 | 0.00 |
| cambridge7A | 1 | 18 | 100.0 | 100.0 | 0.08 |
| cms-tdr | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsarticle | 2 | 3 | 100.0 | 100.0 | 0.00 |
| eptcs | 1 | 3 | 100.0 | 100.0 | 0.00 |
| iopart | 1 | 3 | 100.0 | 100.0 | 0.00 |
| llncs | 1 | 9 | 100.0 | 100.0 | 1.63 |
| ptptex | 1 | 1 | 100.0 | 100.0 | 0.00 |
| quantumarticle | 1 | 6 | 100.0 | 100.0 | 0.00 |
| revtex4 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| revtex4-1 | 1 | 2 | 100.0 | 100.0 | 0.00 |
| revtex4-2 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| subfiles | 1 | 13 | 100.0 | 100.0 | 0.00 |
