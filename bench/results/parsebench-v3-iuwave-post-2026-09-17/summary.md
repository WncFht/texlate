# parsebench summary — corpus_v3

- papers: 1000   files (.tex): 1955   wall: 890.6s
- parse ok: **1955/1955** (100.0%)   errors: 0   measure_errors: 0
- identity: strict **1955** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **57/136052** chunks = 0.04%   hits={'dollar': 57}
- chunk chars: median 210.0   p90 875
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 0
- scan/validate warnings: {'unclosed_env': 79, 'stray_end': 69, 'def_parse_fail': 295, 'missing_input': 159, 'unpaired_dollar': 172, 'debt_repair': 4, 'env_mismatch': 1}
- flatten coverage: 1838 reached / 107 orphan tex / 10 rootless   (触及率 94.5%)

## funnel

| stage | n |
|---|---|
| fetched (manifest rows) | 1000 |
| source ok | 1000 |
| papers discovered | 1000 |
| .tex files | 1955 |
| rooted papers | 995 (multi_doc 32, rootless 5) |
| parse ok | 1955 |
| identity | strict 1955 / normalized 0 / diverged 0 |
| translatable chunks | 136052 |
| leaked chunks | 57 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 0 |
| flatten reached / orphan / rootless | 1838 / 107 / 10 |

## gates (docs/09 §8)

| gate | value | 门槛 | verdict |
|---|---|---|---|
| parse ok (file) | 100.0% CI [99.80, 100.00] | 100% & Wilson lb ≥99.5% | PASS |
| strict identity | 100.00% CI [99.80, 100.00] | ≥99.5% | PASS |
| leak rate (chunk) | 0.040% CI [0.032, 0.054] | ≤0.15% | PASS |
| dead/orphan | 0 (chunk 0 + protect 0 + orphan 0) | =0 | PASS |
| flatten coverage | 94.5% (1838/1945) | ≥99% † | BELOW |

† coverage 口径勘误 (docs/09 §8 表下): orphan 大头是 e-print 内未被主文件 \input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; v3 实测 ~93%.

## 统计口径 (docs/09 §7.2)

- 权重: post-strat w=N_cell/n_cell (核心层), 1000/1000 篇有权; bootstrap: 簇键 cluster_id‖yymm‖pid, B=2000, seed=20260915 (无簇键即逐篇 iid)
| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |
|---|---|---|---|---|---|
| parse ok (file) | 100.000% (1955/1955) | 100.000% | 100.000% | [99.804, 100.000] | [100.000, 100.000] |
| strict identity | 100.000% (1955/1955) | 100.000% | 100.000% | [99.804, 100.000] | [100.000, 100.000] |
| leak (chunk) | 0.040% (57/136052) | 0.052% | 0.048% | [0.032, 0.054] | [0.022, 0.065] |
| flatten coverage | 94.50% (1838/1945) | 93.68% | 98.82% | — | [92.10, 96.91] |

## leak detail

| file | leaked/trans | hits | leaked-chunk snippets |
|---|---|---|---|
| 0806.0463/extracted/per2.tex | 1/866 | dollar | ['dollar'] `We set
$L_t:=
\det p_{[[MACRO_2583]]!}\left({\cal E} \otimes p_X^* (\beta 
+ t [` |
| 1109.1801/extracted/network_science_conf.tex | 1/101 | dollar | ['dollar'] `Finally, the fact that our proposed approach enables us to find \emph{optimal} s` |
| 1206.2231/extracted/TriangleTiling1.tex | 2/285 | dollar | ['dollar'] `Only after completing the work in this paper did I encounter
 Soifer's book [[CI`<br>['dollar'] `Soifer's ``Problem 6.6'' is also a \$25 \Erdos\ problem:  Find (and classify) al` |
| 1306.5846/extracted/snowmassWP.tex | 1/13 | dollar | ['dollar'] `The PINGU design and construction follows closely that of IceCube,
with similar ` |
| 1608.06914/extracted/activationv1.tex | 1/111 | dollar | ['dollar'] `\textit{Proof:} The negativity monogamy scores with the first party as the nodal` |
| 1706.07676/extracted/main.tex | 1/154 | dollar | ['dollar'] `[[LABEL_140]]
Given the sequence
[[MATH_142]][[CMD_143]]_{p-1}[[CMD_144]],[[MATH` |
| 1803.03106/extracted/acino_encryption_jocn.tex | 1/53 | dollar | ['dollar'] `[[CMD_2]]proliferation has increased exponentially in the last two decades, and ` |
| 1803.03191/extracted/main.tex | 1/169 | dollar | ['dollar'] `OSNs 
possess features that enable 
them to be an effective platform 
for spread` |
| 1811.10195/extracted/BullBearBalance - ArXiv/main.tex | 4/98 | dollar | ['dollar'] `Social media is of particular interest due to the high volume and velocity of ac`<br>['dollar'] `Social media data were provided by PsychSignal [[CITE_10]], which operates a cus`<br>['dollar'] `\textbf{Probability distribution of tweet volume.} There is a wide discrepancy b`<br>['dollar'] `Figures [[REF_95]] and [[REF_96]] compare the relationship between the volume of` |
| 1811.10195/extracted/main.tex | 4/98 | dollar | ['dollar'] `Social media is of particular interest due to the high volume and velocity of ac`<br>['dollar'] `Social media data were provided by PsychSignal [[CITE_10]], which operates a cus`<br>['dollar'] `\textbf{Probability distribution of tweet volume.} There is a wide discrepancy b`<br>['dollar'] `Figures [[REF_95]] and [[REF_96]] compare the relationship between the volume of` |
| 1907.03697/extracted/nips_2018.tex | 1/28 | dollar | ['dollar'] `[[LABEL_21]]
In this paper, we aim to demonstrate an application of AI that can ` |
| 1907.10351/extracted/paper.tex | 1/108 | dollar | ['dollar'] `Consider the scalar wave equation
 [[MATH_56]]
where [[MATH_57]] is a smooth fun` |
| 2009.10990/extracted/iaai-arxiv.tex | 6/111 | dollar | ['dollar'] `The recent explosion of available electronic health record (EHR) and insurance c`<br>['dollar'] `The following example shows the utility and limitation of this perspective. Cons`<br>['dollar'] `Group X: each member is enrolled for 10 months - the pmpm cost equals \$1 millio`<br>['dollar'] `Group Y: each member is enrolled for five months - the pmpm cost equals \$1 mill`<br>['dollar'] `Group Z: each member is enrolled for five months and one member costs \$900,000,` (+1 more) |
| 2105.03900/extracted/main.tex | 1/298 | dollar | ['dollar'] `the associated [[MATH_249]]-sectorial operators [[MATH_250]] and [[MATH_251]] ar` |
| 2203.13012/extracted/Modern fundamentals of amplitudes/chapter-1.tex | 1/316 | dollar | ['dollar'] `To have a taste of  form factors,  we now  compute that  of the on-shell Lagrang` |
| 2203.13012/extracted/chapter-1.tex | 1/316 | dollar | ['dollar'] `To have a taste of  form factors,  we now  compute that  of the on-shell Lagrang` |
| 2203.13064/extracted/main.tex | 3/119 | dollar | ['dollar'] `As in GECToR, our primary edit operations are encoded by the following tags: \te`<br>['dollar'] `The final stage is inference tweaks [[CITE_93]] for balancing between the model'`<br>['dollar'] `Most of the tag-encoded edits are token-specific, e.g., \textit{\$APPEND\_it}, \` |
| 2211.04509/extracted/main.tex | 5/176 | dollar | ['dollar'] `Chronic diseases are a dire global problem with grand societal and economic impa`<br>['dollar'] `The prediction performance improvement brings prominent economic value. Depressi`<br>['dollar'] `Beyond improving true positives, minimizing false positives deserves special att`<br>['dollar'] `\href[[HREF_688]]{Depression Cost the US \$326 Billion Per Year Pre-Pandemic, a `<br>['dollar'] `Compared to the baseline models, the annual net benefit that our model brings (\` |
| 2211.04533/extracted/main.tex | 1/105 | dollar | ['dollar'] `Participants were instructed to categorize images in the psychophysics dataset a` |
| 2211.04534/extracted/GOAL arxiv/sample-authordraft.tex | 1/119 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2211.04534/extracted/GOAL arxiv/sample-lualatex.tex | 1/119 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2211.04534/extracted/GOAL arxiv/sample-sigconf-i13n.tex | 1/122 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2211.04534/extracted/GOAL arxiv/sample-sigconf.tex | 1/119 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2211.04534/extracted/GOAL arxiv/sample-xelatex.tex | 1/119 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2308.04282/extracted/periodograms.tex | 1/190 | dollar | ['dollar'] `In the simulation with Gaussian white noise, the transits can be seen visually i` |
| 2410.05969/extracted/DeepNetCounterfeit.tex | 2/77 | dollar | ['dollar'] `Counterfeit drugs, medical systems, and their associated effects are responsible`<br>['dollar'] `The true costs of counterfeits are much higher than direct loss to legitimate ma` |
| 2410.05969/extracted/_paper.tex | 2/55 | dollar | ['dollar'] `Counterfeit drugs, medical systems, and their associated effects are responsible`<br>['dollar'] `The true costs of counterfeits are much higher than direct loss to legitimate ma` |
| 2410.05969/extracted/sec/1_The_problem_of_counterfeit_products.tex | 2/6 | dollar | ['dollar'] `Counterfeit drugs, medical systems, and their associated effects are responsible`<br>['dollar'] `The true costs of counterfeits are much higher than direct loss to legitimate ma` |
| 2410.17903/extracted/Biconservative_MCGL_hypersurfaces.tex | 1/53 | dollar | ['dollar'] `[[CITE_57]][[LABEL_58]]
		Let [[MATH_59]] be a Lorentzian hypersurface, [[MATH_6` |
| cond-mat/0111300/extracted/ART-REVIEW-102501.tex | 1/263 | dollar | ['dollar'] `Traditionally however, magnetic materials have been studied using 
all-electron ` |
| hep-th/9910028/extracted/main.tex | 5/77 | dollar | ['dollar'] `We now return to the   relation between the argument of [\strom] that N=4
supers`<br>['dollar'] `Given [[MATH_432]] almost complex structures satisfying \clif,
the products
[[MA`<br>['dollar'] `The models with [[MATH_475]] supersymmetry can be written in [[MATH_476]] supers`<br>['dollar'] `Real [[MATH_518]] matrices satisfying \clif\ can be constructed from the basic
r`<br>['dollar'] `Performing the [[MATH_555]] integral gives the [[MATH_556]] superspace action
[[` |
| math/0605790/extracted/main.tex | 1/199 | dollar | ['dollar'] `Let [[MATH_492]]. Then we have for
all [[MATH_493]], [[MATH_494]] and all
[[MATH` |

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
| 1109.1708/extracted | revtex4 | prb,twocolumn,showpacs,preprintnumbers,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1773/extracted | amsart | 12pt, reqno | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1792/extracted | amsart | 11pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1801/extracted | IEEEtran | conference | 1 | non-utf8, no-hyperref | 3 | 3 | 3 | 0.85 | 0 |
| 1109.1822/extracted | article | a4paper,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1872/extracted | article | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1915/extracted | cfm2011 | — | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.2053/extracted | ./emulateapj | iop, numberedappendix | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.2059/extracted | revtex4 | twocolumn,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.2205/extracted | revtex4 | twoside,slac_one | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 1 |
| 1109.2247/extracted | article | — | 1 | reject, no-hyperref | 16 | 16 | 16 | 0.00 | 2 |
| 1109.2316/extracted | amsart | oneside,english,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1109.2475/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5232/extracted | revtex4 | twocolumn,showpacs,superscriptaddress,showpacs,floatfix | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5307/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5364/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5404/extracted | amsart | a4paper,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5481/extracted | spie | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5522/extracted | llncs | a4paper,10pt | 1 | non-utf8, no-hyperref | 15 | 15 | 15 | 0.00 | 0 |
| 1109.5631/extracted | aastex | 12pt,preprint | 1 | xelatex, non-utf8, no-hyperref | 6 | 6 | 6 | 0.00 | 0 |
| 1109.5682/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5705/extracted | amsart | 12pt,oneside,english | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5754/extracted | revtex4-1 | twocolumn,showpacs,amsmath,amssymb,superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5757/extracted | emulateapj | twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5931/extracted | article | 11pt,letterpaper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5940/extracted | revtex4 | english,aps,amsmath,amssymb,prl,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.5963/extracted | revtex4 | a4paper,12pt,preprint,amsmath,showpacs, nofootinbib,superscriptaddress | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1109.6007/extracted | mn2e | useAMS,usenatbib,usegraphicx | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.6012/extracted | iopart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.6050/extracted | amsart | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1206.1631/extracted | aachanged | traditabstract | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.1634/extracted | IEEEtran | onecolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.1653/extracted | IEEEtran | 10pt,conference,compsocconf,letterpaper | 1 | no-hyperref | 8 | 8 | 8 | 0.00 | 0 |
| 1206.1808/extracted | article | leqno,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.1901/extracted | mybookalone | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.1940/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.1993/extracted | llncs | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2015/extracted | article | a4paper,11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2018/extracted | iopart | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2036/extracted | aipproc | ,final | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2072/extracted | amsart | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2111/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2156/extracted | revtex4 | showpacs,preprintnumbers,amsmath,amssymb,12pt,floatfix,epsfig | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2194/extracted | revtex4-1 | aps,prl,showpacs,twocolumn,amsmath,amssymb,10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2231/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.70 | 0 |
| 1206.2233/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2250/extracted | revtex4 | aps,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5202/extracted | revtex4-1 | rmp,twocolumn,aps | 1 | no-hyperref | 10 | 10 | 10 | 0.00 | 1 |
| 1206.5217/extracted | revtex4 | aps, prl, twocolumn, showpacs, superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5375/extracted | article | 12pt,fleqn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5428/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5536/extracted | article | a4paper,twoside | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5595/extracted | revtex4 | aps,prl,preprint,tightenlines,superscriptaddress,showpacs,byrevtex,subfigure | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5602/extracted | article | a4paper,12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5620/extracted | mn2e | useAMS,usenatbib,onecolumn,letterpaper | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5628/extracted | article | reqno,11pt | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5646/extracted | revtex4-1 | aps,prb,amsmath,amssymb,reprint,showpacs | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5673/extracted | article | twoside | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5702/extracted | revtex4 | twocolumn,preprintnumbers,amsmath,amssymb,superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5762/extracted | article | 11pt,onecolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5796/extracted | revtex4 | groupedaddress,nofootinbib,showpacs,eqsecnum | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5832/extracted | revtex4 | preprint,eqsecnum,superscriptaddress | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5852/extracted | emulateapj | iop | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5921/extracted | revtex4 | prl,twocolumn,showpacs,superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1306.1932/extracted | appolb | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2067/extracted | article | a4paper,12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2148/extracted | aa | structabstract | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2165/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2177/extracted | aipproc | ,final | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2183/extracted | revtex4 | prb,twocolumn,superscriptaddress,preprintnumbers,amsmath,amssymb | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2280/extracted | article | 10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2289/extracted | revtex4 | preprint,12pt,preprintnumbers,amsmath,amssymb,floatfix,endfloats* | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2356/extracted | acmsmall | prodmode,acmcsur | 1 | no-hyperref | 20 | 20 | 20 | 0.00 | 10 |
| 1306.2365/extracted | article | 10pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1306.2498/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5694/extracted | revtex4 | onecolumn, oneside, floats, aps, prd, nobibnotes, nofootinbib, amsmath, amssymb, amsfonts, amscd, superscriptaddress, eqsecnum | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5717/extracted | revtex4 | aps,pra,amsmath,superscriptaddress,reprint,floatfix,notitlepage,balancelastpage,twocolumn,showpacs,reprint | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5749/extracted | revtex4-1 | aps,prl,twocolumn,amsmath,amssymb,amsfonts | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5771/extracted | mn2e | useAMS,usenatbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5799/extracted | mn2e | useAMS,usenatbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5813/extracted | iopart | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5826/extracted | emulateapj | english | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5846/extracted | elsarticle | 10pt | 1 | no-hyperref | 2 | 2 | 2 | 7.69 | 0 |
| 1306.5866/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5977/extracted | elsarticle | preprint | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1306.5997/extracted | article | 12pt,epsfig,rotating | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6078/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6139/extracted | revtex4 | aps,prb,twocolumn,groupedaddress,showpacs | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6147/extracted | revtex4 | prl,twocolumn,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6161/extracted | amsart | reqno,11pt, fleqn | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6164/extracted | sigma | pdftex | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6198/extracted | IEEEtran | 11pt,draftcls,onecolumn | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 1306.6219/extracted | PoS | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6222/extracted | elsarticle | preprint,authoryear,11pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6224/extracted | llncs | envcountsame,envcountsect,runningheads | 1 | — | 15 | 15 | 15 | 0.00 | 2 |
| 1306.6253/extracted | article | a4paper,12pt,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.6270/extracted | article | twoside,leqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2112/extracted | mn2e | useAMS,usenatbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2121/extracted | article | a4paper,10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2137/extracted | revtex4-1 | aps,prd,10pt,twocolumn,preprintnumbers,nofootinbib,superscriptaddress,a4paper,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2164/extracted | aa | — | 1 | xelatex, non-utf8, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1404.2225/extracted | amsart | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2230/extracted | revtex4 | aps,prb,twocolumn,superscriptaddress,showpacs,showkeys,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2259/extracted | IEEEtran | journal | 1 | no-hyperref | 7 | 7 | 7 | 0.00 | 0 |
| 1404.2362/extracted | amsart | 10pt, twoside | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2384/extracted | revtex4-1 | preprint,prl,aps,superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2402/extracted | article | a4paper,12pt,amsart,frenchb | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.2528/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5668/extracted | article (×2) | letterpaper | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1404.5685/extracted | revtex4 (×2) | prl,reprint,twocolumn,showpacs,preprintnumbers,amsmath,amssymb,amsfonts,superscriptaddress | 2 | non-utf8, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1404.5697/extracted | revtex4 | prc,nofootinbib,showpacs,twocolumn | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5720/extracted | revtex4-1 | aip,rsi,reprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5780/extracted | article | 12TP,draft | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5830/extracted | revtex4 | twocolumn,aps,prl,superscriptaddress,showpacs,secnumroman,showkeys | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5834/extracted | elsarticle | final,5p,times,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5841/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5881/extracted | article | 11pt | 1 | reject, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5889/extracted | IEEEtran | journal,onecolumn,draftclsnofoot | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5900/extracted | amsart | reqno,a4paper,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5912/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5936/extracted | amsart | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5940/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5949/extracted | aastex | preprint2 | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.5993/extracted | article | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.6031/extracted | article | 10pt,twocolumn,letterpaper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1404.6037/extracted | llncs | runningheads | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 1404.6133/extracted | revtex4-1 | aps,prl,twocolumn,superscriptaddress,showpacs,preprintnumbers | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1404.6147/extracted | mn2e | useAMS,usenatbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.6154/extracted | article | 8.5pt,twoside,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1404.6180/extracted | svjour | epj | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.01820/extracted | revtex4 | 12pt, prd,onecolumn,floatfix,letterpaper,amsmath,amssymb,nofootinbib,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.01845/extracted | revtex4 | prd,floatfix,showpacs,preprintnumbers,nofootinbib,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.01857/extracted | revtex4-1 | aps, prb, reprint | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1502.01863/extracted | article | 12pt,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.01959/extracted | llncs | runningheads,a4paper | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.02141/extracted | tMOP2e | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.02155/extracted | article | 11pt,letterpaper | 1 | — | 14 | 14 | 14 | 0.00 | 1 |
| 1502.02163/extracted | elsarticle | preprint,12pt,sort&compress | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.02190/extracted | amsart | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.02236/extracted | sig-alternate | — | 1 | no-hyperref | 14 | 14 | 14 | 0.00 | 1 |
| 1502.02247/extracted | IEEEtran | 10pt, onecolumn, twoside | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.02268/extracted | article | — | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 1502.02285/extracted | revtex4-1 | draft,aps,prl,preprint,showpacs,amsmath,amssymb | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.02333/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1502.02338/extracted | revtex4 | twocolumn,prb,preprintnumbers,amsmath,amssymb,sectsty | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06013/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06096/extracted | report | a4paper,11,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06126/extracted | revtex4 | aps,prd,superscriptaddress,showpacs | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06131/extracted | amsart | letterpaper,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06245/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06256/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06281/extracted | revtex4-1 | aps,pra,reprint,twocolumns,showpacs | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06284/extracted | amsart | — | 1 | — | 16 | 16 | 16 | 0.00 | 0 |
| 1502.06342/extracted | amsart | reqno,12pt,a4paper | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06406/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06421/extracted | revtex4-1 | aip,jap,preprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06426/extracted | emulateapj | apj | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06459/extracted | revtex4-1 | aps, pra, a4paper,twocolumn, showpacs,10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06500/extracted | article | a4paper,twoside,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06527/extracted | revtex4 | aps,prl,twocolumn,groupedaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06541/extracted | iopart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06608/extracted | mn2e | useAMS,usenatbib,fleqn | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1502.06611/extracted | emulateapj | iop,revtex4 | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06612/extracted | aastex | preprint | 1 | xelatex, non-utf8, no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 1511.02567/extracted | amsart | 11pt, reqno | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02659/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02672/extracted | article | 11pt,a4paper | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02676/extracted | revtex4 | nofootinbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02683/extracted | article | 10pt,twocolumn,letterpaper | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02686/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02730/extracted | revtex4-1 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb,prl | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02761/extracted | revtex4 | aps | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02799/extracted | article | 10pt,twocolumn,letterpaper | 1 | — | 7 | 7 | 7 | 0.00 | 0 |
| 1511.02818/extracted | article | 10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02820/extracted | revtex4 | showpacs,preprintnumbers, amsmath,amssymb, aps, prd, lengthcheck, letterpaper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02825/extracted | IEEEtran | 10pt,conference,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02858/extracted | revtex4-1 | aps,prd,twocolumn,nofootinbib,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02862/extracted | emulateapj | iop, revtex4 | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02908/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02930/extracted | article | a4paper | 1 | — | 1 | 1 | 1 | — | 0 |
| 1511.02943/extracted | revtex4-1 | 10pt,twocolumn,superscriptaddress,floafix,nobalancelastpage | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06628/extracted | amsart | 12pt, reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06689/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06706/extracted | elsarticle | english,3p,floatfix | 1 | xelatex, non-utf8 | 19 | 19 | 19 | 0.00 | 0 |
| 1511.06725/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06740/extracted | article (×2) | 11pt,a4paper | 2 | non-utf8, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1511.06744/extracted | article | — | 1 | — | 21 | 21 | 21 | 0.00 | 0 |
| 1511.06763/extracted | mn2e | useAMS,usenatbib,usegraphicx | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06765/extracted | aastex | preprint2 | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06783/extracted | article (×2) | 10pt,twocolumn,letterpaper | 2 | xelatex | 5 | 5 | 5 | 0.00 | 0 |
| 1511.06847/extracted | article | 11pt,epsfig,epsf | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06857/extracted | amsart | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06865/extracted | amsart | 12pt,a4paper | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06879/extracted | revtex4 | pre,twocolumn,groupedaddress,showpacs,nofootinbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06943/extracted | article | 12pt,a4paper,fleqn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06963/extracted | elsarticle | 5p | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06971/extracted | IEEEtran | english | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02289/extracted | sig-alternate-05-2015 | — | 1 | no-hyperref | 12 | 12 | 12 | 0.00 | 0 |
| 1608.02314/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02317/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02331/extracted | webofc | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02354/extracted | article | 11pt,draft | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02390/extracted | revtex4-1 | aps,prb,preprint,a4paper,showpacs | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02516/extracted | amsart | reqno, 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02550/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02556/extracted | scrartcl | a4paper,11pt,headings=big,DIV=12 | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02611/extracted | sig-alternate | — | 1 | no-hyperref | 13 | 13 | 13 | 0.00 | 5 |
| 1608.02631/extracted | elsarticle | preprint,authoryear,12pt | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02645/extracted | spie | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02651/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.02680/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | no-hyperref | 28 | 28 | 28 | 0.00 | 15 |
| 1608.02685/extracted | agutex2015 | jgrga | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06646/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06693/extracted | svjour3 | 12pt,smallextended,numbook,runningheads | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06705/extracted | article | reqno,11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06723/extracted | elsarticle | review | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06760/extracted | cernphprep | a4paper,manyauthors,nocleardouble,COMPASS | 1 | — | 10 | 10 | 10 | 0.00 | 0 |
| 1608.06769/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06785/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06793/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06833/extracted | revtex4-1 | aps,prd,reprint,groupedaddress,onecolumn,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06845/extracted | jmlr | wcp | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06896/extracted | article | 12pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.06914/extracted | revtex4-1 | aps,twocolumn,pra | 1 | — | 1 | 1 | 1 | 0.90 | 0 |
| 1608.06992/extracted | emulateapj | 12pt, preprint,numberedappendix | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.07013/extracted | revtex4 | floats,onecolumn,superscriptaddress,floatfix | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.07022/extracted | llncs | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.07066/extracted | article | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1608.07077/extracted | revtex4-1 | aps,prb,preprint,showpacs,showkeys,superscriptaddress,amsmath,amssymb,floatfix,author-numerical,nofootinbib | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1608.07091/extracted | iopart | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02360/extracted | amsart | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02372/extracted | iopart | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02424/extracted | iopart | letterpaper | 1 | minted, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02457/extracted | revtex4-1 | prl,showpacs,superscriptaddress,twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02477/extracted | jpconf | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02532/extracted | aastex6 | preprint2 | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02550/extracted | revtex4-1 | pre,twocolumn,showpacs | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02567/extracted | elsarticle | review | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02568/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02588/extracted | revtex4-1 | aps,reprint,twocolumn,showpacs,preprintnumbers,amsmath,amssymb,nofootinbib,superscriptaddress,showkeys | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02609/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02630/extracted | eptcs | submission | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02656/extracted | revtex4-1 | reprint, showpacs, amsmath,amssymb, aps, prl, | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02657/extracted | revtex4 | 10pt,prd,nofootinbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02671/extracted | amsart | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02694/extracted | article | 11pt,twoside | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02695/extracted | IEEEtran | journal | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02729/extracted | mnras | a4paper,fleqn,usenatbib,useAMS | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02730/extracted | article | 11pt,letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.02733/extracted | article | letterpaper,11pt | 1 | — | 6 | 6 | 6 | 0.00 | 0 |
| 1706.07493/extracted | amsart | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07510/extracted | amsart | a4paper,11pt | 1 | xelatex | 5 | 5 | 5 | 0.00 | 0 |
| 1706.07519/extracted | article | letterpaper,10pt | 1 | no-hyperref | 12 | 12 | 12 | 0.00 | 2 |
| 1706.07613/extracted | IEEEtran | journal | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07670/extracted | amsart | 11pt,twoside | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07675/extracted | amsart | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07676/extracted | revtex4-1 | aip,cha,reprint | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.65 | 0 |
| 1706.07690/extracted | llncs | runningheads,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07704/extracted | revtex4-1 | twocolumn,floatfix,nofootinbib,amsmath,amssymb, aps,prl,floatfix | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07773/extracted | iopart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07871/extracted | emulateapj | iop | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07886/extracted | article | — | 1 | — | 1 | 1 | 1 | — | 0 |
| 1706.07924/extracted | amsart | reqno,11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1706.07927/extracted | IEEEtran_doc_class | conference,10pt,a4paper,twocolumn,oneside | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1803.02897/extracted | revtex4-1 | aps,prd,showpacs,nofootinbib,superscriptaddress,preprintnumbers,twocolumn | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.02918/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.02921/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.02993/extracted | revtex4 | pra,twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.02994/extracted | article | letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03001/extracted | revtex4 | amsfonts,amsmath,prd,preprint,nofootinbib | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03014/extracted | mnras | a4paper,fleqn,usenatbib | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03036/extracted | revtex4 | prb,twocolumn,showpacs,superscriptaddress,nofootinbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03082/extracted | amsart | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03090/extracted | revtex4-1 | aps,twocolumn,amssymb,amsfonts,amsmath,showpacs,final,prl | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03106/extracted | IEEEtran | journal | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 1.89 | 0 |
| 1803.03110/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03111/extracted | aer | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03191/extracted | article | a4paper | 1 | — | 1 | 1 | 1 | 0.59 | 0 |
| 1803.03210/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03212/extracted | revtex4-1 | floatfix, superscriptaddress, reprint, showpacs, aip, apl, 10pt | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03235/extracted | revtex4-1 | aps,twocolumn,showpacs,superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03248/extracted | article | letterpaper,11pt | 1 | — | 8 | 8 | 8 | 0.00 | 0 |
| 1803.03249/extracted | article | letterpaper,11pt,oneside,onecolumn | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.03254/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.08836/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.08846/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.08870/extracted | article | english,12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.08873/extracted | PoS | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.08883/extracted | revtex4-1 | reprint,showpacs,aps,superscriptaddress,pra | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.08927/extracted | aastex61 | twocolumn,tighten | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.08946/extracted | revtex4-1 | aps,pra,twocolumn,a4paper,superscriptaddress,longbibliography,nofootinbib,notitlepage | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.08959/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.09008/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.09012/extracted | IEEEtran | 12pt, draftclsnofoot, onecolumn | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1803.09046/extracted | aastex61 | twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1803.09056/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1803.09074/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03412/extracted | IEEEtran | 10pt, journal,final,compsoc | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03459/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03472/extracted | article | a4paper,11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03483/extracted | revtex4-1 | preprint, amsmath,amssymb, prb, | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03495/extracted | aastex62 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03517/extracted | APS | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03539/extracted | IEEEtran | journal | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03553/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03558/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03559/extracted | acmsmall | acmtoms | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03569/extracted | llncs | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03588/extracted | article | 12pt,final,math=serif | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03607/extracted | revtex4-1 | a4paper, preprint, superscriptaddress, groupedaddress, runinaddress, showpacs, amsmath,amssymb, aps, prb, showkeys | 1 | xelatex | 18 | 18 | 18 | 0.00 | 0 |
| 1811.03615/extracted | revtex4-1 | aps,prd,preprintnumbers,nofootinbib,twocolumn,superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03619/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03624/extracted | revtex4-1 | amsmath,amssymb,superscriptaddress,notitlepage,twocolumn,nofootinbib | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03697/extracted | article | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03722/extracted | revtex4-1 | prl, twocolumn,superscriptaddress,nofootinbib, amsmath,amssymb, aps, | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.03728/extracted | article | twocolumn | 1 | — | 15 | 15 | 15 | 0.00 | 4 |
| 1811.09974/extracted | article | letterpaper | 1 | no-hyperref | 7 | 7 | 7 | 0.00 | 0 |
| 1811.10012/extracted | revtex4-1 | aps, prd, twocolumn, lengthcheck, superscriptaddress, showpacs, nofootinbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10026/extracted | svjour3 | smallextended | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10029/extracted | article | 10pt,letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10050/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10086/extracted | amsart | 11pt | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10103/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10148/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10189/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10195/extracted | IEEEtran (×2) | conference, onecolumn | 2 | — | 2 | 2 | 2 | 4.08 | 0 |
| 1811.10208/extracted | revtex4-1 | aps,pra,reprint,showpacs | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10235/extracted | revtex4-1 | pra,superscriptaddress,reprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10239/extracted | revtex4-1 | 10pt,aps,prl,showpacs,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10271/extracted | amsart | — | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03592/extracted | llncs | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03601/extracted | amsart | a4paper,leqno,centertags,fleqn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03602/extracted | revtex4 | aps,prl,twocolumn,groupedaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03607/extracted | revtex4-1 | reprint, superscriptaddress, amsmath,amssymb, aps, prx | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03650/extracted | amsart | 11pt,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03665/extracted | elsarticle | review | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03697/extracted | article | — | 1 | — | 1 | 1 | 1 | 3.57 | 0 |
| 1907.03735/extracted | revtex4-1 | 10pt,aps,twocolumn,prl,floatfix,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03745/extracted | revtex4-1 | twocolumn,nofootinbib | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03750/extracted | article | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03815/extracted | revtex4-2 | aps,prl,reprint,nofootinbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03816/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03821/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03824/extracted | amsart | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.03850/extracted | lipics-v2019 | numberwithinsect,a4paper,UKenglish,cleveref,autoref | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 2 |
| 1907.03868/extracted | llncs (×2) | runningheads | 2 | — | 12 | 12 | 12 | 0.00 | 1 |
| 1907.03923/extracted | amsart | a4paper,12pt,oneside,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10324/extracted | neuthist18 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10343/extracted | article | 10pt,twocolumn,letterpaper | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10345/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10351/extracted | elsarticle | review | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.93 | 0 |
| 1907.10373/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10378/extracted | amsart | 11pt, a4paper, twoside,leqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10382/extracted | article | a4paper,11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10392/extracted | svjour3 | smallcondensed | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10434/extracted | revtex4-1 | aps,prl,reprint,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10440/extracted | scrbook | a4paper, titlepage, bibliography=totoc, 12pt, BCOR17mm, DIV12, headinclude, footinclude=false | 1 | — | 9 | 9 | 9 | 0.00 | 0 |
| 1907.10453/extracted | llncs | runningheads | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10454/extracted | IEEEtran | 10pt,journal,compsoc | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10457/extracted | frontiersSCNS | utf8 | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10480/extracted | llncs | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10515/extracted | acmart | sigconf | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10522/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10567/extracted | revtex4-1 | amsmath,superscriptaddress,showpacs,prb,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03387/extracted | revtex4 | letterpaper,amsmath, amssymb,aps,prd,nofootinbib, singlecolumn, superscriptaddress,altaffilsymbol | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03388/extracted | mnras (×2) | fleqn,usenatbib | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2003.03423/extracted | article | letterpaper,twocolumn,10pt | 1 | no-hyperref | 12 | 12 | 12 | 0.00 | 1 |
| 2003.03430/extracted | revtex4-1 | twocolumn,10pt,amsmath,amssymb,aps,pra,superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03437/extracted | svjour3 | numbook,envcountreset,final | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03462/extracted | article | twoside | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2003.03463/extracted | article | — | 1 | — | 11 | 11 | 11 | 0.00 | 1 |
| 2003.03479/extracted | llncs | runningheads | 1 | no-hyperref | 9 | 9 | 9 | 0.00 | 0 |
| 2003.03485/extracted | article | letterpaper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03503/extracted | revtex4-2 | reprint, superscriptaddress, amsmath,amssymb, aps, | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03508/extracted | standalone (×14) | tikz | 14 | no-hyperref | 14 | 14 | 14 | 0.00 | 0 |
| 2003.03510/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03512/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03526/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03533/extracted | wlscirep | fleqn,11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03545/extracted | ecai | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03579/extracted | article | 11pt,a4paper,twoside,groupcitations | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10673/extracted | revtex4-1 | 10pt,onecolumn,amsmath,amssymb,floatfix, notitlepage | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10721/extracted | amsart | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10723/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10727/extracted | article | a4paper, 11pt | 1 | — | 3 | 3 | 3 | 0.00 | 0 |
| 2003.10741/extracted | revtex4-1 | reprint,superscriptaddress,amssymb,amsmath,aps,showpacs,10pt,floatfix,pra,longbibliography | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10754/extracted | article | 11pt,a4paper | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10792/extracted | mnras | fleqn,usenatbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10818/extracted | jps-cp | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10830/extracted | IEEEtran | journal,letter,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10868/extracted | elsarticle | review | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10897/extracted | article | twoside | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10906/extracted | revtex4 | aps,preprint,amsmath,amssymb,11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10917/extracted | revtex4-1 | 10pt,aps,prd,twocolumn,notitlepage,bibnotes,longbibliography, floatfix,showpacs,citeautoscript,superscriptaddress | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10925/extracted | article | twocolumn, switch | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10959/extracted | llncs | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.10969/extracted | revtex4-1 | prd,reprint,showpacs,nofootinbib | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2009.03605/extracted | article | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03627/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03641/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03670/extracted | revtex4-1 | aps,prapplied,reprint,showkeys,superscriptaddress,floatfix | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03672/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03673/extracted | article | 11pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03681/extracted | IEEEtran | conference | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03685/extracted | article | a4paper, 12pt | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03686/extracted | revtex4-1 | aps,prc,twocolumn,floatfix,showpacs,a4paper, nofootinbib,amsmath,amssymb | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03699/extracted | article | — | 1 | — | 6 | 6 | 6 | 0.00 | 0 |
| 2009.03701/extracted | article | oneside, 12pt, a4paper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03707/extracted | vgtc | preprint | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03736/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03743/extracted | IEEEtran | conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03750/extracted | IEEEtran | journal | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03767/extracted | IEEEtran | letterpaper, 10 pt, journal, twoside | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03781/extracted | article | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03783/extracted | IEEEtran | journal | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03805/extracted | revtex4-1 | 12pt, reprint, onecolumn, tightenlines, superscriptaddress, notitlepage, preprintnumbers, nofootinbib, amsmath,amssymb,amsthm, aps, eqsecnum, | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.03810/extracted | jaa | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.10925/extracted | aastex63 (×2) | twocolumn | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2009.10977/extracted | article | a4paper,12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.10990/extracted | article | letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 5.41 | 0 |
| 2009.11002/extracted | mnras | useAMS,usenatbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2009.11013/extracted | IEEEtran (×3) | conference | 3 | xelatex | 3 | 3 | 3 | 0.00 | 0 |
| 2009.11016/extracted | article | letterpaper | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2009.11026/extracted | revtex4-1 | aps,prl,twocolumn,amsmath,amssymb,showpacs,superscriptaddress,notitlepage,longbibliography | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.11040/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2009.11042/extracted | article | letterpaper | 1 | — | 9 | 9 | 9 | 0.00 | 1 |
| 2009.11053/extracted | book (×18) | 11pt,a4paper,oneside,openright | 18 | — | 18 | 18 | 18 | 0.00 | 0 |
| 2009.11072/extracted | IEEEtran | 10pt,journal, compsoc | 1 | no-hyperref | 6 | 6 | 6 | 0.00 | 0 |
| 2009.11090/extracted | llncs | runningheads | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| 2009.11125/extracted | iopart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03729/extracted | revtex4-2 | twocolumn,english,aps,prb,twocolum,superscriptaddress,bibnotes,amsmath,amssymb,floatfix | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03730/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03733/extracted | article | — | 1 | — | 8 | 8 | 8 | 0.00 | 0 |
| 2105.03740/extracted | revtex4-2 | amsmath,amssymb,prx,superscriptaddress,reprint,showpacs,longbibliography | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03750/extracted | aastex63 | twocolumn,times | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03753/extracted | lipics-v2021 | a4paper,UKenglish,cleveref, autoref, thm-restate | 1 | no-hyperref | 8 | 8 | 8 | 0.00 | 0 |
| 2105.03772/extracted | aastex61 | preprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03779/extracted | revtex4 | amsmath, amsfonts, superscriptaddress, twocolumn, prl | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03798/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03806/extracted | article | 12pt,english | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03808/extracted | amsart | 12pt,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03813/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03827/extracted | cvpr | final | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2105.03835/extracted | article (×2) | — | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2105.03858/extracted | IEEEtran | journal,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03883/extracted | IEEEtran | conference | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03900/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.34 | 0 |
| 2105.03922/extracted | article | english | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03923/extracted | article | — | 1 | — | 9 | 9 | 9 | 0.00 | 0 |
| 2105.03934/extracted | cas-dc | a4paper,fleqn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03940/extracted | amsart | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03943/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03955/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11393/extracted | revtex4-1 | prl,twocolumn,showpacs,floatfix,amsmath,amssymb,superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11398/extracted | amsart | 10pt | 1 | xelatex | 1 | 1 | 1 | — | 0 |
| 2105.11413/extracted | revtex4-1 | aps,twocolumn,superscriptaddress,nofootinbib,pre | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11432/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11438/extracted | svjour3 | twocolumn | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2105.11462/extracted | article | letterpaper,11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11479/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11481/extracted | revtex4-1 | showpacs, oneside, twocolumn, amsmath, amssymb, prl, nofootinbib, superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11487/extracted | amsart | 11 | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11488/extracted | aastex62 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11495/extracted | revtex4 | twocolumn,aps,prl,showpacs,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04298/extracted | llncs | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04333/extracted | aastex63 | twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04336/extracted | mnras | fleqn,usenatbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04341/extracted | article (×3) | a4paper,11pt | 3 | — | 3 | 3 | 3 | 0.00 | 0 |
| 2203.04345/extracted | article | 12pt,bezier | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04361/extracted | ifacconf | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04376/extracted | IEEEtran | conference | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04381/extracted | IEEEtran | journal | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04383/extracted | article | 10pt | 1 | — | 7 | 7 | 7 | 0.00 | 0 |
| 2203.04385/extracted | aastex62_reep | preprint2,tighten | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04392/extracted | amsart | 11pt,twoside | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.12983/extracted | article | 10pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.12991/extracted | revtex4-2 | aps,prb,superscriptaddress,showkeys | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.12997/extracted | article | 10pt,twocolumn,letterpaper | 1 | — | 28 | 28 | 28 | 0.00 | 1 |
| 2203.12999/extracted | llncs | runningheads | 1 | xelatex | 2 | 2 | 2 | 0.00 | 1 |
| 2203.13007/extracted | svjour | epj,nopacs | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13012/extracted | iopart (×2) | 12pt | 2 | — | 4 | 4 | 4 | 0.32 | 2 |
| 2203.13024/extracted | iopart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13026/extracted | iopart | 12pt | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13031/extracted | article | 10pt,twocolumn,letterpaper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13039/extracted | amsart | 11pt,3p, times, reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13055/extracted | cvpr | final | 1 | — | 8 | 8 | 8 | 0.00 | 1 |
| 2203.13058/extracted | amsart | a4paper,12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13060/extracted | IEEEtran | 10pt,journal,comsoc | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13064/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 2.52 | 0 |
| 2203.13079/extracted | jpconf | a4paper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13085/extracted | article | 10pt,twocolumn,letterpaper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13087/extracted | revtex4-1 | preprint, floatfix, longbibliography, amsmath,amssymb, aps, pre, | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13095/extracted | acmartmod | sigconf | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13102/extracted | revtex4 | twocolumn,aps,prb,superscriptaddress,floatfix | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13107/extracted | article | a4paper,11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13109/extracted | amsart | 11pt,letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.13113/extracted | article | 12pt, english | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04441/extracted | article | JHEP,11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04445/extracted | IEEEtran | conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04450/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04452/extracted | revtex4-2 | aps,pre,superscriptaddress,showkeys,citeautoscript | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04453/extracted | elsarticle | final,authoryear,3p,times | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2211.04456/extracted | scrartcl | a4paper, 11pt | 1 | — | 3 | 3 | 3 | 0.00 | 0 |
| 2211.04457/extracted | revtex4-2 (×2) | reprint, superscriptaddress, floatfix, amsmath,amssymb, aps, | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2211.04462/extracted | article | 11pt,a4paper | 1 | — | 14 | 14 | 14 | 0.00 | 11 |
| 2211.04467/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04473/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04495/extracted | mnras | fleqn,usenatbib | 1 | no-hyperref | 12 | 12 | 12 | 0.00 | 1 |
| 2211.04503/extracted | aastex3 (×4) | twocolumn | 4 | no-hyperref | 4 | 4 | 4 | 0.00 | 0 |
| 2211.04509/extracted | informs3b | mnsc | 1 | — | 1 | 1 | 1 | 2.84 | 0 |
| 2211.04515/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04517/extracted | IEEEtran (×2) | letterpaper, 10 pt, journal, twoside | 2 | — | 4 | 4 | 4 | 0.00 | 0 |
| 2211.04533/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.95 | 0 |
| 2211.04534/extracted | acmart (×8) | sigconf | 8 | no-hyperref | 8 | 8 | 8 | 0.47 | 0 |
| 2211.04539/extracted | article (×2) | — | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2211.04559/extracted | article | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04574/extracted | mnras (×2) | fleqn,usenatbib | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2211.12986/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.12990/extracted | article | — | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2211.12997/extracted | pnas-new (×3) | 9pt,twocolumn,twoside,lineno | 3 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 2211.13004/extracted | acmart | acmsmall,10pt, nonacm | 1 | no-hyperref | 11 | 11 | 11 | 0.00 | 0 |
| 2211.13012/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13013/extracted | revtex4 | prd,letterpaper,twocolumn,preprintnumbers,nofootinbib | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13019/extracted | ifacconf (×2) | — | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2211.13022/extracted | revtex4-1 | aip,a4paper,onecolumn, amsmath,amssymb, reprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13033/extracted | amsart | 12pt,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13040/extracted | optica-article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13041/extracted | article | 10pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13046/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13053/extracted | IEEEtran | 10pt,conference | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04153/extracted | mnras | useAMS,usenatbib,onecolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04174/extracted | article | 11pt,english | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04188/extracted | IEEEtran | conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04189/extracted | IEEEtran | conference | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04193/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04194/extracted | pro12 | twoside,final | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04199/extracted | revtex4 | aps,prb,preprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04212/extracted | WileyNJD-v2 | AMA,STIX1COL | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04217/extracted | article | a4paper,11pt | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 2308.04223/extracted | IEEEtran | journal | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04250/extracted | revtex4-1 | prx,twocolumn,superscriptaddress,longbibliography | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04265/extracted | article | — | 1 | — | 8 | 8 | 8 | 0.00 | 0 |
| 2308.04273/extracted | revtex4 | prd,showkeys,floatfix,twocolumn,amsmath,amssymb,floatfix | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04278/extracted | IEEEtran | journal | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04280/extracted | revtex4-1 | twocolumn,superscriptaddress,amsmath,amssymb,showpacs,prl | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.04282/extracted | aastex631 | twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.53 | 0 |
| 2308.04287/extracted | autart | onecolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12594/extracted | amsart | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12597/extracted | revtex4-2 | reprint, floatfix,superscriptaddress, longbibliography,amsmath,amssymb,aps,prx,showkeys, | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2308.12600/extracted | llncs | runningheads | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12608/extracted | article | letterpaper | 1 | no-hyperref | 22 | 22 | 22 | 0.00 | 0 |
| 2308.12610/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12612/extracted | acmart | acmsmall,pdftex | 1 | xelatex, no-hyperref | 10 | 10 | 10 | 0.00 | 0 |
| 2308.12641/extracted | article | 12pt | 1 | xelatex, no-hyperref | 6 | 6 | 6 | 0.00 | 0 |
| 2308.12647/extracted | elsarticle | 3p | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12649/extracted | article | — | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2308.12655/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12657/extracted | achemso (×2) | journal=jacsat,manuscript=article | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2308.12661/extracted | article | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2308.12667/extracted | article | a4paper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12669/extracted | revtex4 | nofootinbib,floatfix,superscriptaddress,twocolumn | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12707/extracted | IEEEtran | conference | 1 | no-hyperref | 5 | 5 | 5 | 0.00 | 0 |
| 2308.12711/extracted | article | 11pt | 1 | — | 29 | 29 | 29 | 0.00 | 6 |
| 2308.12712/extracted | acmart | sigconf | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| 2403.05441/extracted | elsarticle | final,5p,times,twocolumn,authoryear | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.05444/extracted | article (×2) | a4paper,12pt | 2 | xelatex, no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 2403.05449/extracted | amsart | 12pt,reqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.05454/extracted | amsart | 11pt,oneside,english,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.05456/extracted | amsart | 12pt,a4paper,reqno | 1 | — | 2 | 2 | 2 | 0.00 | 1 |
| 2403.05463/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.05475/extracted | amsart | a4paper,12pt,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.05477/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | no-hyperref | 8 | 8 | 8 | 0.00 | 0 |
| 2403.05497/extracted | SciPost | submission, Phys | 1 | — | 5 | 5 | 5 | 0.00 | 0 |
| 2403.05500/extracted | IEEEtran | lettersize,journal | 1 | — | 15 | 15 | 15 | 0.00 | 0 |
| 2403.05509/extracted | revtex4-2 | twocolumn,aps,prl,amsmath,amssymb,color,longbibliography,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.05532/extracted | llncs | runningheads | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.05550/extracted | elsarticle | preprint,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.05553/extracted | wlscirep | fleqn,10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15075/extracted | IEEEtran (×6) | conference | 6 | no-hyperref | 7 | 7 | 7 | 0.00 | 1 |
| 2403.15078/extracted | IEEEtran (×2) | a4paper, conference | 2 | — | 10 | 10 | 10 | 0.00 | 0 |
| 2403.15079/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15085/extracted | atlasdoc | cernpreprint, atlasdraft=false, UKenglish, texmf, orcidlogo | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2403.15089/extracted | llncs | runningheads | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15093/extracted | atlasdoc | PAPER, atlasdraft=false, UKenglish, cernpreprint, texmf, orcidlogo | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2403.15096/extracted | amsart | 12pt,reqno,twoside,a4paper | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15098/extracted | llncs | runningheads | 1 | — | 4 | 4 | 4 | 0.00 | 2 |
| 2403.15102/extracted | ieeeconf (×2) | letterpaper, 10 pt, conference | 2 | xelatex | 8 | 8 | 8 | 0.00 | 0 |
| 2403.15111/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15118/extracted | aa | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15119/extracted | IEEEtran | 10pt,journal,compsoc | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15126/extracted | article | 11pt,a4paper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15129/extracted | elsarticle | preprint,12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15149/extracted | acmart | sigconf,screen | 1 | no-hyperref | 17 | 17 | 17 | 0.00 | 2 |
| 2403.15156/extracted | IEEEtran | conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15160/extracted | amsart | 12pt,a4paper,reqno | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15162/extracted | article | 12pt, | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15170/extracted | IEEEtran | a4paper, 10pt, conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.05957/extracted | revtex4 | aps,prl,groupedaddress,superscriptaddress,twocolumn | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.05959/extracted | article | a4paper,11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.05969/extracted | article | 10pt,twocolumn,letterpaper | 1 | no-hyperref | 11 | 11 | 11 | 2.87 | 0 |
| 2410.05972/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.05981/extracted | revtex4-2 | reprint, superscriptaddress, showpacs, amsmath,amssymb, prl, | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.05985/extracted | article | — | 1 | — | 10 | 10 | 10 | 0.00 | 1 |
| 2410.05995/extracted | revtex4-2 | aps,pra,twocolumn,superscriptaddress,10pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.05999/extracted | elsarticle | preprint,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.06004/extracted | IEEEtran | journal | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.06007/extracted | article | — | 1 | — | 28 | 28 | 28 | 0.00 | 4 |
| 2410.06025/extracted | article | — | 1 | — | 18 | 18 | 18 | 0.00 | 0 |
| 2410.06028/extracted | acmart | sigconf, anonymous=false | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 2410.06035/extracted | amsart | reqno,centertags,11pt,a4paper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.06040/extracted | IEEEtran | conference,onecolumn | 1 | — | 33 | 33 | 33 | 0.00 | 4 |
| 2410.17902/extracted | amsart | a4paper, svgnames, 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17903/extracted | amsart | leqno,12pt | 1 | no-hyperref | 1 | 1 | 1 | 1.89 | 0 |
| 2410.17916/extracted | aa | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17923/extracted | article | a4paper,10pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17931/extracted | IEEEtran | conference | 1 | no-hyperref | 9 | 9 | 9 | 0.00 | 0 |
| 2410.17941/extracted | article | — | 1 | — | 4 | 4 | 4 | 0.00 | 1 |
| 2410.17949/extracted | article | a4paper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17952/extracted | article | 11pt | 1 | no-hyperref | 15 | 15 | 15 | 0.00 | 0 |
| 2410.17958/extracted | article | 11pt | 1 | no-hyperref | 11 | 11 | 11 | 0.00 | 2 |
| 2410.17961/extracted | article (×2) | — | 2 | — | 27 | 27 | 27 | 0.00 | 3 |
| 2410.17967/extracted | IEEEtran | journal | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17978/extracted | amsart | reqno,11pt,a4 | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17983/extracted | ieeeconf (×2) | letterpaper, 10 pt, conference | 2 | no-hyperref | 17 | 17 | 17 | 0.00 | 4 |
| 2410.17984/extracted | aa | structabstract | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17992/extracted | quantumarticle | a4paper,twocolumn,11pt,unpublished | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17998/extracted | article | twoside | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.18001/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.18015/extracted | revtex4-2 | prb,twocolumn,showpacs,amsmath,amssymb,superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.18024/extracted | compositionalityarticle | a4paper,onecolumn,superscriptaddress,10pt,shorttitle=papers | 1 | — | 4 | 4 | 4 | 0.00 | 3 |
| astro-ph/0111038 | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111094 | revtex4 | twocolumn,showpacs,superscriptaddress,prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111197 | article | 12pt,epsf,aaspp4 | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111213 | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111323 | aa | — | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111411 | aa | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307007 | article | 11pt,newpasp,twoside,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307009 | aa | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307042 | book | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307059 | revtex4 | twocolumn,pre,aps,nofootinbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307121 | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307344 | aastex | 12pt,preprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0501073 | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb,aps,prd,nofootinbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0501080 | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0501398 | emulateapj | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0501439 | emulateapj | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0501590 | article | fleqn,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0501599 | mn2e | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0501608 | aa | letterpaper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0605290 | aa | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0605325 | mn2e | useAMS,usenatbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0605352 | mn2e | useAMS,usenatbib,referee | 1 | xelatex, no-hyperref | 5 | 5 | 5 | 0.00 | 0 |
| astro-ph/0605355 | aastex | 12pt,preprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0605361 | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0605441 | article | 10pt,a4paper,twoside | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9703134 | article | 11pt,aaspp4 | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9703152 | article | psfig,apjprepr,amssym,flushrt | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9703185 | revtex | eqsecnum,aps,twocolumn | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9703198 | crckapb | editedvolume | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9703201 | revtex | 12pt,prd,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9910044 | laa | referee | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9910131 | article | 11pt,epsfig,aaspp4 | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9910280 | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9910297 | crckapb | editedvolume,psfig | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9910309 | elsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9910332 | article | 11pt,paspconf,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/9910488 | mn | psfig,harvard | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| chao-dyn/9703017 | article | 12pt,dina4,ams,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| chao-dyn/9910021 | article | twoside,fleqn,psfig,espcrc2 | 1 | reject, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| cond-mat/0111036 | revtex | pre,aps,multicol,epsfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0111097 | jpsj | epsfig,seceq,twocolumn | 1 | reject, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0111297 | revtex | multicol,epsf,prl,aps | 1 | reject, xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0111300 | revtex4 | twocolumn,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.38 | 0 |
| cond-mat/0111406 | revtex | prb,aps,epsfig,graphicx,tabularx, multicol | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0111543 | revtex4 | aps,prb,superscriptaddress,twocolumn,floatfix,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0307035 | revtex4 | aps,prl,twocolumn,showpacs,groupedaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0307193 | article (×2) | 12pt | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| cond-mat/0307206 | revtex | prl,aps,psfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0307221 | revtex | prl,aps,multicol,psfig | 1 | reject, xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0307508 | elsart3 | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0307578 | revtex4 | aps,prb,twocolumn,citeautoscript | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0307655 | revtex4 | twocolumn,english,showpacs | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0307744 | revtex4 | twocolumn,aps | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0501109 | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0501128 | revtex | prl,aps,epsf,floats | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0501293 | article | 10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0501437 | revtex4 | amssymb,amsmath,twocolumn,preprintnumbers,prb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0501475 | revtex4 | prl,twocolumn,superscriptaddress, showpacs,groupeaddress,preprintnumbers,amsmath,amssymb,tightenlines | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0501478 | revtex4 | aps,prl,showpacs,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0501604 | revtex4 (×2) | prb,preprint,showpacs,preprintnumbers,amssymb | 2 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| cond-mat/0605032 | article | 10pt,letterpaper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0605100 | revtex4 | twocolumn,showpacs,superscriptaddress,amsmath,amssymb,prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0605196 | revtex4 | amsmath, preprintnumbers, sort&compress, twocolumn | 1 | non-utf8, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| cond-mat/0605249 | revtex4 | twocolumn,showpacs,aps,prb | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0605308 | revtex4 | aps,prl,twocolumn,superscriptaddress,showpacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/0605429 | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9703021 | revtex | prl,aps,epsf | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9703161 | revtex | preprint,eqsecnum,aps,amssymb | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9703176 | article | fullpage,11pt,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9703220 | revtex | aps,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9703221 | article | epsf | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9703223 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9910002 | revtex | epsfig,aps,prl,multicol | 1 | reject, xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9910116 | revtex | floats,amssymb,aps,prl,epsfig | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9910214 | revtex | aps,multicol,epsfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9910246 | revtex | preprint, aps, epsfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9910284 | revtex | aps,pre,epsf,floats | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9910395 | revtex | twocolumn,prb,aps,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cond-mat/9910442 | revtex | aps,pra,prabib,amsfonts,amssymb,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cs/0111043 | article | 11pt, twoside, a4paper | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cs/0307009 | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cs/0501020 | svjour | global | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| cs/0605043 | article | — | 1 | no-hyperref | 8 | 8 | 8 | 0.00 | 0 |
| gr-qc/0605005 | revtex4 | preprint,aps,amsmath | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ex/0501017 | iopart | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ex/0501022 | jpconf | letterpaper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ex/0605086 | article | 11pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-lat/0111009 | article | fleqn,twoside | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-lat/0111059 | cpcauth | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0111050 | revtex4 | preprint,showpacs,preprintnumbers,amsmath,amssymb | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0111218 | article | fleqn,twoside | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0111245 | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0111248 | aipproc (×2) | cmfonts | 2 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| hep-ph/0111281 | revtex | aps, epsf, psfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0111383 | article | 12pt,epsfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0111415 | ws-p8-50x6-00 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0307118 | revtex | prd,aps,preprint,epsfig | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0307177 | article | 12pt | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| hep-ph/0307234 | article | 12pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0307255 | Rinton-P9x6 | — | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| hep-ph/0501163 | svjour | epj,final | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0605135 | svjour | epj,nopacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0605149 | article | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| hep-ph/0605178 | revtex4 | aps,prl,twocolumn,epsfig,preprintnumbers,superscriptaddress,10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0605288 | article | 12pt,dvips | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9703202 | — | — | 0 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9703228 | article | epsfig,12pt | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9703272 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9703300 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9703402 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910332 | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910335 | revtex | preprint,prl,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910373 | revtex | preprint,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910403 | article | dvips,12pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910443 | hep99 | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910488 | revtex | preprint,tighten,aps,psfig | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0111076 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0111079 | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0307008 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0307148 | JHEP3 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0307152 | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0307203 | article | 10pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0307279 | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0307296 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0501153 | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0501161 | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0501177 | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0501195 | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0501198 | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0501238 | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0605038 | article | 12pt,lettersize | 1 | xelatex, non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/0605233 | revtex4 | english,amsmath,amssymb,prd,letter,showpacs,showkeys | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703013 | revtex | preprint,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703073 | — | — | 0 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703086 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703099 | article | 11pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703117 | elsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703173 | revtex | aps,prl | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703180 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703203 | article | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9910028 | — | — | 0 | no-hyperref | 1 | 1 | 1 | 6.49 | 0 |
| hep-th/9910044 | article | sprocl | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9910113 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9910156 | iopart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9910215 | article | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math-ph/0501022 | iopart | 10pt | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math-ph/9910046 | article | 11pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0111203 | article | 12pt,amssymb,graphicx | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0111235 | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0111275 | amsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0111324 | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0307077 | amsart | — | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0307107 | amsart | 11pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0307197 | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0307301 | article | 10 pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0307402 | article | a4paper,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0501060 | article | 11pt | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| math/0501104 | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0501227 | article | 11pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0501396 | amsart | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0501428 | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0605135 | amsart | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0605144 | article | english,12pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0605267 | amsart | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0605301 | article | 12 | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0605340 | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0605628 | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/0605790 | article | a4paper,12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.50 | 0 |
| math/9703222 | amsart | 11pt,amstex | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/9910113 | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/9910177 | gtart | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| nucl-ex/9910015 | article | 12pt,twoside,fleqn,amssymb,epsfig,espcrc1,graphicx | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/0111058 | revtex | prc,epsfig,aps | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/0307063 | article | 12pt, graphicx | 1 | reject, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/0501044 | revtex4 | preprint,tightenlines,prc,bibnotes,showpacs,noshowkeys,nofootinbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/0605055 | revtex4 | preprint,aps,showpacs,showkeys,tightenlines,superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/9703003 | revtex | eqsecnum,aps,preprint | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/9703017 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| physics/0111119 | article | — | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| physics/0111206 | revtex | aps,amsfonts,twocolumn,prl,floats,epsfig | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| physics/0307021 | revtex4 | aps,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| physics/0605204 | article | 12pt,dvips | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| physics/0605206 | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| physics/9703012 | article | a4paper,twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| q-alg/9703036 | article | — | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| q-alg/9703046 | article | amstex,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0111094 | article | 12pt | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| quant-ph/0111127 | revtex4 | preprint,showpacs,preprintnumbers,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0307197 | revtex4 | aps,pra,twocolumn,groupedaddress,amsmath,amssymb | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0307209 | revtex4 | a4paper,twocolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0501054 | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0501111 | article | twopage,11pt | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0605071 | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0605205 | revtex4 | pra,preprint,aps,floats | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/9703040 | article | 12pt,qqa4lart | 1 | reject, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| quant-ph/9910018 | revtex | prl,aps,twocolumn | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/9910059 | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| solv-int/9703005 | article | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| solv-int/9703010 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| solv-int/9910006 | article | 11pt,a4 | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |

## by class

| class | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| ./emulateapj | 1 | 1 | 100.0 | 100.0 | 0.00 |
| APS | 1 | 1 | 100.0 | 100.0 | 0.00 |
| IEEEtran | 51 | 153 | 100.0 | 100.0 | 0.13 |
| IEEEtran_doc_class | 1 | 2 | 100.0 | 100.0 | 0.00 |
| JHEP3 | 2 | 2 | 100.0 | 100.0 | 0.00 |
| PoS | 4 | 5 | 100.0 | 100.0 | 0.00 |
| Rinton-P9x6 | 1 | 2 | 100.0 | 100.0 | 0.00 |
| SciPost | 1 | 5 | 100.0 | 100.0 | 0.00 |
| WileyNJD-v2 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aa | 13 | 14 | 100.0 | 100.0 | 0.00 |
| aachanged | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aastex | 18 | 25 | 100.0 | 100.0 | 0.00 |
| aastex3 | 1 | 4 | 100.0 | 100.0 | 0.00 |
| aastex6 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aastex61 | 3 | 3 | 100.0 | 100.0 | 0.00 |
| aastex62 | 2 | 2 | 100.0 | 100.0 | 0.00 |
| aastex62_reep | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aastex63 | 3 | 4 | 100.0 | 100.0 | 0.00 |
| aastex631 | 1 | 1 | 100.0 | 100.0 | 0.53 |
| achemso | 1 | 2 | 100.0 | 100.0 | 0.00 |
| acmart | 7 | 52 | 100.0 | 100.0 | 0.21 |
| acmartmod | 1 | 1 | 100.0 | 100.0 | 0.00 |
| acmsmall | 2 | 21 | 100.0 | 100.0 | 0.00 |
| aer | 1 | 1 | 100.0 | 100.0 | 0.00 |
| agutex2015 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aims | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aipproc | 5 | 6 | 100.0 | 100.0 | 0.00 |
| amsart | 108 | 129 | 100.0 | 100.0 | 0.01 |
| amsppt | 1 | 1 | 100.0 | 100.0 | 0.00 |
| an | 1 | 1 | 100.0 | 100.0 | 0.00 |
| appolb | 1 | 1 | 100.0 | 100.0 | 0.00 |
| article | 331 | 738 | 100.0 | 100.0 | 0.05 |
| arximspdf | 1 | 1 | 100.0 | 100.0 | 0.00 |
| atlasdoc | 2 | 4 | 100.0 | 100.0 | 0.00 |
| autart | 1 | 1 | 100.0 | 100.0 | 0.00 |
| birkjour | 2 | 2 | 100.0 | 100.0 | 0.00 |
| book | 3 | 45 | 100.0 | 100.0 | 0.00 |
| cas-dc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| cernphprep | 1 | 10 | 100.0 | 100.0 | 0.00 |
| cfm2011 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| compositionalityarticle | 1 | 4 | 100.0 | 100.0 | 0.00 |
| cpcauth | 1 | 1 | 100.0 | 100.0 | 0.00 |
| crckapb | 2 | 2 | 100.0 | 100.0 | 0.00 |
| cvpr | 2 | 10 | 100.0 | 100.0 | 0.00 |
| dis07 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ecai | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsart | 3 | 3 | 100.0 | 100.0 | 0.00 |
| elsart3 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsarticle | 20 | 41 | 100.0 | 100.0 | 0.06 |
| emulateapj | 16 | 23 | 100.0 | 100.0 | 0.00 |
| eptcs | 2 | 3 | 100.0 | 100.0 | 0.00 |
| frontiersSCNS | 1 | 1 | 100.0 | 100.0 | 0.00 |
| gtart | 1 | 2 | 100.0 | 100.0 | 0.00 |
| hep99 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ieeeconf | 9 | 66 | 100.0 | 100.0 | 0.00 |
| ifacconf | 2 | 3 | 100.0 | 100.0 | 0.00 |
| imsart | 2 | 2 | 100.0 | 100.0 | 0.00 |
| informs3b | 1 | 1 | 100.0 | 100.0 | 2.84 |
| iopart | 17 | 20 | 100.0 | 100.0 | 0.07 |
| ismdproc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jaa | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jac | 1 | 2 | 100.0 | 100.0 | 0.00 |
| jmlr | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jpconf | 5 | 5 | 100.0 | 100.0 | 0.00 |
| jps-cp | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jpsj | 1 | 1 | 100.0 | 100.0 | 0.00 |
| laa | 1 | 1 | 100.0 | 100.0 | 0.00 |
| lipics-v2019 | 1 | 3 | 100.0 | 100.0 | 0.00 |
| lipics-v2021 | 1 | 8 | 100.0 | 100.0 | 0.00 |
| llncs | 22 | 76 | 100.0 | 100.0 | 0.00 |
| mn | 1 | 1 | 100.0 | 100.0 | 0.00 |
| mn2e | 13 | 18 | 100.0 | 100.0 | 0.00 |
| mnras | 9 | 22 | 100.0 | 100.0 | 0.00 |
| mybookalone | 1 | 1 | 100.0 | 100.0 | 0.00 |
| neuthist18 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| optica-article | 1 | 1 | 100.0 | 100.0 | 0.00 |
| pasj00 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| pnas-new | 1 | 3 | 100.0 | 100.0 | 0.00 |
| pro12 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| quantumarticle | 1 | 1 | 100.0 | 100.0 | 0.00 |
| report | 2 | 2 | 100.0 | 100.0 | 0.00 |
| revtex | 29 | 29 | 100.0 | 100.0 | 0.00 |
| revtex4 | 126 | 133 | 100.0 | 100.0 | 0.01 |
| revtex4-1 | 67 | 94 | 100.0 | 100.0 | 0.03 |
| revtex4-2 | 12 | 14 | 100.0 | 100.0 | 0.00 |
| scrartcl | 2 | 4 | 100.0 | 100.0 | 0.00 |
| scrbook | 1 | 9 | 100.0 | 100.0 | 0.00 |
| sig-alternate | 2 | 27 | 100.0 | 100.0 | 0.00 |
| sig-alternate-05-2015 | 1 | 12 | 100.0 | 100.0 | 0.00 |
| sigma | 1 | 1 | 100.0 | 100.0 | 0.00 |
| spie | 3 | 3 | 100.0 | 100.0 | 0.00 |
| standalone | 1 | 14 | 100.0 | 100.0 | 0.00 |
| svjour | 6 | 6 | 100.0 | 100.0 | 0.00 |
| svjour3 | 5 | 6 | 100.0 | 100.0 | 0.00 |
| tMOP2e | 1 | 1 | 100.0 | 100.0 | 0.00 |
| vgtc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| webofc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| wlscirep | 2 | 2 | 100.0 | 100.0 | 0.00 |
| ws-p8-50x6-00 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ws-procs9x6 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| — | 5 | 10 | 100.0 | 100.0 | 1.40 |

## by era

| era | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| new | 800 | 1731 | 100.0 | 100.0 | 0.04 |
| old | 200 | 224 | 100.0 | 100.0 | 0.03 |

## by archive

| archive | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| astro-ph | 37 | 41 | 100.0 | 100.0 | 0.00 |
| chao-dyn | 2 | 3 | 100.0 | 100.0 | 0.00 |
| cond-mat | 40 | 43 | 100.0 | 100.0 | 0.03 |
| cs | 4 | 11 | 100.0 | 100.0 | 0.00 |
| gr-qc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| hep-ex | 3 | 3 | 100.0 | 100.0 | 0.00 |
| hep-lat | 2 | 2 | 100.0 | 100.0 | 0.00 |
| hep-ph | 27 | 31 | 100.0 | 100.0 | 0.00 |
| hep-th | 29 | 29 | 100.0 | 100.0 | 0.13 |
| math | 24 | 25 | 100.0 | 100.0 | 0.02 |
| math-ph | 2 | 2 | 100.0 | 100.0 | 0.00 |
| nucl-ex | 1 | 1 | 100.0 | 100.0 | 0.00 |
| nucl-th | 6 | 6 | 100.0 | 100.0 | 0.00 |
| physics | 6 | 8 | 100.0 | 100.0 | 0.00 |
| q-alg | 2 | 2 | 100.0 | 100.0 | 0.00 |
| quant-ph | 11 | 13 | 100.0 | 100.0 | 0.00 |
| solv-int | 3 | 3 | 100.0 | 100.0 | 0.00 |
| — | 800 | 1731 | 100.0 | 100.0 | 0.04 |

## by stratum_cell

| stratum_cell | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| a_pre2007|astro-ph | 37 | 41 | 100.0 | 100.0 | 0.00 |
| a_pre2007|cond-mat | 40 | 43 | 100.0 | 100.0 | 0.03 |
| a_pre2007|cs | 4 | 11 | 100.0 | 100.0 | 0.00 |
| a_pre2007|hep-phys | 73 | 80 | 100.0 | 100.0 | 0.06 |
| a_pre2007|math | 28 | 29 | 100.0 | 100.0 | 0.02 |
| a_pre2007|nucl | 7 | 7 | 100.0 | 100.0 | 0.00 |
| a_pre2007|quant-ph | 11 | 13 | 100.0 | 100.0 | 0.00 |
| b_2007_11|astro-ph | 32 | 44 | 100.0 | 100.0 | 0.00 |
| b_2007_11|cond-mat | 32 | 32 | 100.0 | 100.0 | 0.00 |
| b_2007_11|cs | 15 | 52 | 100.0 | 100.0 | 0.00 |
| b_2007_11|eess-stat-etc | 6 | 6 | 100.0 | 100.0 | 0.00 |
| b_2007_11|hep-phys | 51 | 81 | 100.0 | 100.0 | 0.00 |
| b_2007_11|math | 48 | 51 | 100.0 | 100.0 | 0.03 |
| b_2007_11|nucl | 6 | 6 | 100.0 | 100.0 | 0.00 |
| b_2007_11|quant-ph | 10 | 10 | 100.0 | 100.0 | 0.00 |
| c_2012_16|astro-ph | 26 | 31 | 100.0 | 100.0 | 0.03 |
| c_2012_16|cond-mat | 26 | 54 | 100.0 | 100.0 | 0.00 |
| c_2012_16|cs | 31 | 189 | 100.0 | 100.0 | 0.00 |
| c_2012_16|eess-stat-etc | 9 | 9 | 100.0 | 100.0 | 0.00 |
| c_2012_16|hep-phys | 43 | 53 | 100.0 | 100.0 | 0.00 |
| c_2012_16|math | 53 | 69 | 100.0 | 100.0 | 0.02 |
| c_2012_16|nucl | 3 | 3 | 100.0 | 100.0 | 0.00 |
| c_2012_16|quant-ph | 9 | 9 | 100.0 | 100.0 | 0.13 |
| d_2017_20|astro-ph | 19 | 21 | 100.0 | 100.0 | 0.00 |
| d_2017_20|cond-mat | 21 | 38 | 100.0 | 100.0 | 0.00 |
| d_2017_20|cs | 52 | 155 | 100.0 | 100.0 | 0.09 |
| d_2017_20|eess-stat-etc | 19 | 44 | 100.0 | 100.0 | 0.39 |
| d_2017_20|hep-phys | 35 | 61 | 100.0 | 100.0 | 0.00 |
| d_2017_20|math | 46 | 48 | 100.0 | 100.0 | 0.03 |
| d_2017_20|nucl | 2 | 2 | 100.0 | 100.0 | 0.00 |
| d_2017_20|quant-ph | 6 | 6 | 100.0 | 100.0 | 0.00 |
| e_2021_25|astro-ph | 16 | 31 | 100.0 | 100.0 | 0.04 |
| e_2021_25|cond-mat | 16 | 20 | 100.0 | 100.0 | 0.00 |
| e_2021_25|cs | 79 | 488 | 100.0 | 100.0 | 0.13 |
| e_2021_25|eess-stat-etc | 18 | 27 | 100.0 | 100.0 | 0.00 |
| e_2021_25|hep-phys | 28 | 37 | 100.0 | 100.0 | 0.05 |
| e_2021_25|math | 36 | 45 | 100.0 | 100.0 | 0.03 |
| e_2021_25|quant-ph | 7 | 9 | 100.0 | 100.0 | 0.00 |

## by cluster_id

| cluster_id | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| C01 | 34 | 35 | 100.0 | 100.0 | 0.00 |
| C02 | 33 | 35 | 100.0 | 100.0 | 0.16 |
| C03 | 33 | 37 | 100.0 | 100.0 | 0.03 |
| C04 | 34 | 37 | 100.0 | 100.0 | 0.00 |
| C05 | 33 | 34 | 100.0 | 100.0 | 0.00 |
| C06 | 33 | 46 | 100.0 | 100.0 | 0.02 |
| C07 | 34 | 35 | 100.0 | 100.0 | 0.00 |
| C08 | 33 | 38 | 100.0 | 100.0 | 0.02 |
| C09 | 33 | 34 | 100.0 | 100.0 | 0.00 |
| C10 | 34 | 68 | 100.0 | 100.0 | 0.00 |
| C11 | 33 | 36 | 100.0 | 100.0 | 0.00 |
| C12 | 33 | 71 | 100.0 | 100.0 | 0.02 |
| C13 | 34 | 50 | 100.0 | 100.0 | 0.03 |
| C14 | 33 | 70 | 100.0 | 100.0 | 0.02 |
| C15 | 33 | 44 | 100.0 | 100.0 | 0.00 |
| C16 | 34 | 79 | 100.0 | 100.0 | 0.00 |
| C17 | 33 | 82 | 100.0 | 100.0 | 0.00 |
| C18 | 33 | 92 | 100.0 | 100.0 | 0.02 |
| C19 | 34 | 55 | 100.0 | 100.0 | 0.02 |
| C20 | 33 | 41 | 100.0 | 100.0 | 0.06 |
| C21 | 33 | 71 | 100.0 | 100.0 | 0.22 |
| C22 | 34 | 55 | 100.0 | 100.0 | 0.05 |
| C23 | 33 | 80 | 100.0 | 100.0 | 0.00 |
| C24 | 33 | 73 | 100.0 | 100.0 | 0.14 |
| C25 | 34 | 59 | 100.0 | 100.0 | 0.02 |
| C26 | 33 | 79 | 100.0 | 100.0 | 0.09 |
| C27 | 33 | 90 | 100.0 | 100.0 | 0.20 |
| C28 | 34 | 115 | 100.0 | 100.0 | 0.02 |
| C29 | 33 | 104 | 100.0 | 100.0 | 0.00 |
| C30 | 33 | 210 | 100.0 | 100.0 | 0.11 |

## by layer

| layer | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| core | 1000 | 1955 | 100.0 | 100.0 | 0.04 |
