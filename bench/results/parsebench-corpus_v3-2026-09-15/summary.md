# parsebench summary — corpus_v3

- papers: 1000   files (.tex): 1955   wall: 230.7s
- parse ok: **1954/1955** (100.0%)   errors: 1
- identity: strict **1954** / normalized 0 / diverged 0 (strict-rate 100.0%)
- leak: **196/135990** chunks = 0.14%   hits={'dollar': 160, 'begin_env': 6, 'cite_family': 25, 'ref_family': 14, 'conditional': 1}
- chunk chars: median 211.0   p90 873
- fake-translation: dead CHUNK ph 0   dead protect ph 0   orphan chunks 0   bug1 ph-tail 10487
- flatten coverage: 1821 reached / 124 orphan tex / 10 rootless

## funnel

| stage | n |
|---|---|
| manifest rows | 1000 |
| source ok (manifest) | 0 |
| papers discovered | 1000 |
| .tex files | 1955 |
| rooted papers | 995 (multi_doc 32, rootless 5) |
| parse ok | 1954 |
| identity | strict 1954 / normalized 0 / diverged 0 |
| translatable chunks | 135990 |
| leaked chunks | 196 |
| dead CHUNK ph | 0 |
| dead protect ph | 0 |
| orphan chunks | 0 |
| bug1 ph-tail | 10487 |
| flatten reached / orphan / rootless | 1821 / 124 / 10 |

## parse errors

| file | error | wall_ms |
|---|---|---|
| 0905.4371/extracted/pstricks.tex | IndexError: list index out of range | 9.7 |

## leak detail

| file | leaked/trans | hits | leaked-chunk snippets |
|---|---|---|---|
| 0806.0463/extracted/per2.tex | 2/865 | dollar,begin_env | ['begin_env'] `\subjclass[2000]{Primary 14D21; Secondary 16G20}

\begin{abstract}
This is the s`<br>['dollar'] `We set
$L_t:=
\det p_{[[MACRO_2582]]!}\left({\cal E} \otimes p_X^* (\beta 
+ t [` |
| 0905.4503/extracted/ms.tex | 1/272 | dollar | ['dollar'] `[[CMD_1014]]ecaption{ED[[MATH_1015]]CS Composite LFs}
[[CMD_1016]]tdata
[[CMD_10` |
| 1003.4527/extracted/groh_etacar_highvel_accepted_version_astroph.tex | 34/173 | dollar | ['dollar'] `Spectroscopic observations of the near-infrared [[CMD_62]]mbda[[MATH_63]]-8~\kms`<br>['dollar'] `While previous spectroscopic observations of [[CMD_69]]mbda[[MATH_70]]R\simeq700`<br>['dollar'] `This paper is organized as follows. Sect. [[REF_84]] describes the near-infrared`<br>['dollar'] `to calculate the phases [[MATH_101]] across a given spectroscopic cycle [[MATH_1`<br>['dollar'] `Spatially resolved spectra of Eta Car were recorded with the CRyogenic high-reso` (+29 more) |
| 1109.1664/extracted/main_8.tex | 1/214 | dollar | ['dollar'] `Magnitude of the acceleration measured by an accelerometer placed at the hips of` |
| 1109.1801/extracted/network_science_conf.tex | 1/101 | dollar | ['dollar'] `Finally, the fact that our proposed approach enables us to find \emph{optimal} s` |
| 1109.5754/extracted/resub_f.tex | 2/59 | dollar,cite_family,ref_family | ['ref_family'] `(Color online) Self-consistent energy surfaces of 
[[MATH_62]]Ba (a) and [[MATH_`<br>['dollar', 'cite_family'] `(Color online) The energy ratios (a) [[MATH_175]] and (b) [[MATH_176]], 
and (c)` |
| 1206.2231/extracted/TriangleTiling1.tex | 2/283 | dollar | ['dollar'] `Only after completing the work in this paper did I encounter
 Soifer's book [[CI`<br>['dollar'] `Soifer's ``Problem 6.6'' is also a \$25 \Erdos\ problem:  Find (and classify) al` |
| 1206.5428/extracted/sextupole-v1-4.tex | 1/190 | ref_family | ['ref_family'] `[[LABEL_413]]
%Left: 
%The data histogram for 0-5\% central \auau collisions fro` |
| 1206.5595/extracted/main0115.tex | 1/122 | dollar | ['dollar'] `
(a) [[MATH_513]] for muon {tracks,} 
(b) [[MATH_514]] and (c) [[MATH_515]] for ` |
| 1206.5628/extracted/ArticleSarahLemler.tex | 1/180 | dollar | ['dollar'] `$$[[MACRO_463]]{\tilde X}(t)=[[MATH_464]]=[[CMD_465]]thbb{R}^{n\times(M+N)}$$` |
| 1306.2365/extracted/BAYESIAN_SOLUTION_UQ_FOR_DES_FINAL_29May.tex | 3/184 | dollar | ['dollar'] `Draw one sample from the forward model ([[REF_295]]) using a probabilistic solve`<br>['dollar'] `Sampling  [[MATH_385]] from the probabilistic solver evaluated over the grid [[M`<br>['dollar'] `
Sampling  [[MATH_761]]  from the probabilistic solver evaluated over the grid [` |
| 1306.5846/extracted/snowmassWP.tex | 1/18 | dollar | ['dollar'] `The PINGU design and construction follows closely that of IceCube,
with similar ` |
| 1306.6224/extracted/prelims.tex | 1/23 | dollar | ['dollar'] `A \emph{signature [[MATH_3]]} is a set of symbols [[MATH_4]] each having a fixed` |
| 1502.06256/extracted/kucherov-arxiv-update.tex | 1/127 | ref_family | ['ref_family'] `Classification of {\em Bacillus licheniformis} reads
  against {\em Bacillus ant` |
| 1502.06541/extracted/NeutrinosLHCv3.tex | 3/125 | dollar,cite_family | ['dollar', 'cite_family'] `Limits on the mixing between the electron neutrino and a single heavy neutrino i`<br>['dollar', 'cite_family'] `Limits on the mixing between the muon neutrino and a single heavy neutrino in th`<br>['dollar', 'cite_family'] `Limits on the mixing between the tau neutrino and a single heavy neutrino in the` |
| 1511.02862/extracted/main.tex | 1/159 | dollar | ['dollar'] `[[CMD_207]]\log(M_{[[CMD_208]]ol) = 9.3-10.2[[MATH_209]] 0.3 < z < 0.6 [[MATH_21` |
| 1511.06706/extracted/TEX_FILES/aa.tex | 1/16 | cite_family | ['cite_family'] `(Color online) (a) Single-particle band structure of the
AA-stacked bilayer
grap` |
| 1511.06706/extracted/TEX_FILES/fqhe.tex | 1/6 | cite_family | ['cite_family'] `(Color online)  Observation of fractional quantum Hall effect at
[[MATH_30]]~K.
` |
| 1511.06706/extracted/TEX_FILES/magnet.tex | 1/45 | cite_family | ['cite_family'] `(Color online) Experimental observation of the integer
quantum Hall effect in AB` |
| 1511.06706/extracted/TEX_FILES/meso.tex | 2/56 | cite_family | ['cite_family'] `Dispersion relation for localized bands near a particular Dirac
point. The two s`<br>['cite_family'] `Photodetector based on gapped AB bilayer graphene. In panel (a)
[[MATH_225]] is ` |
| 1511.06706/extracted/TEX_FILES/transport.tex | 2/50 | cite_family | ['cite_family'] `Experimental data for the minimum conductivity: The blue and red
curves demonstr`<br>['cite_family'] `
Scaling property of the minimum conductivity of the AB bilayer graphene, as
des` |
| 1511.06706/extracted/breview.tex | 7/1064 | cite_family | ['cite_family'] `(Color online) (a) Single-particle band structure of the
AA-stacked bilayer
grap`<br>['cite_family'] `(Color online) Experimental observation of the integer
quantum Hall effect in AB`<br>['cite_family'] `(Color online)  Observation of fractional quantum Hall effect at
[[MATH_1307]]~K`<br>['cite_family'] `Dispersion relation for localized bands near a particular Dirac
point. The two s`<br>['cite_family'] `Photodetector based on gapped AB bilayer graphene. In panel (a)
[[MATH_1597]] is` (+2 more) |
| 1608.06760/extracted/dataanalysis.tex | 1/24 | dollar | ['dollar'] `Probabilities of RICH identification of [[MATH_81]], K[[MATH_82]] and p as [[MAT` |
| 1608.06760/extracted/results.tex | 1/19 | dollar,ref_family | ['dollar', 'ref_family'] `Multiplicities for [[MATH_59]] shown vs [[MATH_60]] for the nine [[MATH_61]] ran` |
| 1608.06769/extracted/ms.tex | 1/150 | dollar | ['dollar'] `Posterior density of infection [[MATH_480]] and removal [[MATH_481]] rates 
%$(\` |
| 1608.06914/extracted/activationv1.tex | 1/111 | dollar | ['dollar'] `\textit{Proof:} The negativity monogamy scores with the first party as the nodal` |
| 1706.02656/extracted/main.tex | 1/35 | dollar,cite_family | ['dollar', 'cite_family'] `(a) Residual stresses are both necessary and sufficient for rigidity.   Histogra` |
| 1706.07676/extracted/main.tex | 1/153 | dollar | ['dollar'] `[i)] \  [[MATH_460]], i.e.
   [[MATH_461]]{[[CMD_462]]ots [[CMD_463]]}}$` |
| 1803.03106/extracted/acino_encryption_jocn.tex | 1/50 | dollar | ['dollar'] `[[CMD_2]]iferation has increased exponentially in the last two decades, and it i` |
| 1803.03191/extracted/main.tex | 1/169 | dollar | ['dollar'] `OSNs 
possess features that enable 
them to be an effective platform 
for spread` |
| 1811.09974/extracted/src/proposed.tex | 1/24 | dollar | ['dollar'] `The structure of Temporal Bilinear module. %Here the dimension of output $\mathb` |
| 1811.09974/extracted/tbn.tex | 1/69 | dollar | ['dollar'] `The structure of Temporal Bilinear module. %Here the dimension of output $\mathb` |
| 1811.10195/extracted/BullBearBalance - ArXiv/main.tex | 5/100 | dollar | ['dollar'] `Social media is of particular interest due to the high volume and velocity of ac`<br>['dollar'] `Social media data were provided by PsychSignal [[CITE_10]], which operates a cus`<br>['dollar'] `\textbf{Probability distribution of tweet volume.} There is a wide discrepancy b`<br>['dollar'] `Figures [[REF_95]] and [[REF_96]] compare the relationship between the volume of`<br>['dollar'] `\textbf{Autocorrelation Plots.} Plots for the features used to calculate [[MATH_` |
| 1811.10195/extracted/main.tex | 5/100 | dollar | ['dollar'] `Social media is of particular interest due to the high volume and velocity of ac`<br>['dollar'] `Social media data were provided by PsychSignal [[CITE_10]], which operates a cus`<br>['dollar'] `\textbf{Probability distribution of tweet volume.} There is a wide discrepancy b`<br>['dollar'] `Figures [[REF_95]] and [[REF_96]] compare the relationship between the volume of`<br>['dollar'] `\textbf{Autocorrelation Plots.} Plots for the features used to calculate [[MATH_` |
| 1907.03697/extracted/nips_2018.tex | 1/28 | dollar | ['dollar'] `[[LABEL_21]]
In this paper, we aim to demonstrate an application of AI that can ` |
| 1907.03923/extracted/v3.tex | 1/243 | dollar | ['dollar'] `[[CMD_257]] the natural numbers [[MATH_258]] with the maximal coarse structure a` |
| 1907.10351/extracted/paper.tex | 1/109 | dollar | ['dollar'] `Consider the scalar wave equation
 [[MATH_52]]
where [[MATH_53]] is a smooth fun` |
| 1907.10382/extracted/main.tex | 2/76 | dollar | ['dollar'] `The parameters obtained starting at a charging voltage V[[CMD_109]]~kV are as fo`<br>['dollar'] `Finally, the lifetime of the investigated thyristor triggered in the impact-ioni` |
| 1907.10453/extracted/samplepaper.tex | 1/138 | dollar | ['dollar'] `Second day, %30min.$>$length$>$2hours. 
        30min[[MATH_204]]length[[MATH_20` |
| 2003.03387/extracted/main.tex | 2/157 | dollar | ['dollar'] `Constraints at 68[[MATH_393]] C.L. on the cosmological parameters 
%($\omega_\ma`<br>['dollar'] `Constraints at 68[[MATH_446]] C.L. on the cosmological parameters
% ($\omega_0$,` |
| 2003.03437/extracted/fpba-arxiv-latex-file-02-03-20.tex | 1/81 | dollar | ['dollar'] `[[LABEL_133]]
The following statements are equivalent: 
[[CMD_134]] minimizes [[` |
| 2003.03462/extracted/main.tex | 1/107 | dollar | ['dollar'] `
        A large number of basis functions is required to accurately capture the` |
| 2003.03485/extracted/arxiv.tex | 1/147 | dollar | ['dollar'] `
Number of training pairs and sampling
% Increasing the samples $l$, and number ` |
| 2003.03512/extracted/draft_ver5_arXiv.tex | 1/209 | dollar | ['dollar'] `%\vbox{
\baselineskip 14pt
\hfill \hbox{\normalsize EPHOU-20-003}\\ 
\hfill \hbo` |
| 2003.03533/extracted/scirep-template.tex | 1/113 | dollar | ['dollar'] `
\textbf{Permuted MNIST learning task.}
Binarized neural network learning six ta` |
| 2003.10959/extracted/eccv2020submission.tex | 1/71 | ref_family | ['ref_family'] `\textbf{NGA.} (\textbf{top}) Pretrained Network. (\textbf{bottom}) Grafted Netwo` |
| 2009.10990/extracted/iaai-arxiv.tex | 6/111 | dollar | ['dollar'] `The recent explosion of available electronic health record (EHR) and insurance c`<br>['dollar'] `The following example shows the utility and limitation of this perspective. Cons`<br>['dollar'] `Group X: each member is enrolled for 10 months - the pmpm cost equals \$1 millio`<br>['dollar'] `Group Y: each member is enrolled for five months - the pmpm cost equals \$1 mill`<br>['dollar'] `Group Z: each member is enrolled for five months and one member costs \$900,000,` (+1 more) |
| 2009.11042/extracted/main.tex | 1/121 | dollar | ['dollar'] `\small {\bf Impact of content representation.} We evaluate DM-Font, \ours withou` |
| 2009.11042/extracted/tables/abl_content.tex | 1/1 | dollar | ['dollar'] `\small {\bf Impact of content representation.} We evaluate DM-Font, \ours withou` |
| 2009.11042/extracted/tables/ablation_tables.tex | 1/3 | dollar | ['dollar'] `\small {\bf Impact of objective functions.}
We measure the accuracy metrics with` |
| 2105.03753/extracted/algorithm-constrained-clustering.tex | 1/49 | dollar | ['dollar'] `[[LABEL_186]][[CITE_187]]
Let [[MATH_188]] be independent 0-1 random variables w` |
| 2105.03753/extracted/column-outliers-full.tex | 1/270 | dollar | ['dollar'] `[[LABEL_928]][[CITE_929]]
Let [[MATH_930]] be independent 0-1 random variables w` |
| 2105.03798/extracted/purity_arxiv1.tex | 4/354 | dollar | ['dollar'] `Let [[MATH_171]] be a subset of a group [[MATH_172]]. The set of orders \wrt [[M`<br>['dollar'] `Recall that, for an alphabet [[MATH_1439]], we write [[MATH_1440]] the [[CMD_144`<br>['dollar'] `If a graph (or automaton) [[MATH_1492]] can be obtained by identifying a vertex `<br>['dollar'] `The interpretation of subgroups as automata (and their computability in the fini` |
| 2105.03923/extracted/body/mainbody.tex | 1/40 | dollar,cite_family | ['dollar', 'cite_family'] `\small 
GPI with function approximation. 
% \haiyan{where the ideal policy is de` |
| 2105.03923/extracted/iclr2023_conference.tex | 1/166 | dollar,cite_family | ['dollar', 'cite_family'] `\small 
GPI with function approximation. 
% \haiyan{where the ideal policy is de` |
| 2105.11398/extracted/Streufert-Gm.tex | 1/464 | dollar | ['dollar'] `At the same time, the existence of a player transformation is a restrictive assu` |
| 2105.11488/extracted/ms.tex | 2/232 | cite_family,ref_family | ['ref_family'] `
%Same as in Fig.~\ref{fig:map_psc2} but for all sources in the LBC FOV of Peg~I`<br>['cite_family'] `[[MATH_867]], [[MATH_868]] CMDs showing stellar sources within five times the r[` |
| 2203.04336/extracted/publication_revision_2.tex | 1/233 | dollar | ['dollar'] `Time evolution of the volume-weighted average and rms of the thermal electron de` |
| 2203.13012/extracted/Modern fundamentals of amplitudes/chapter-1.tex | 1/314 | dollar | ['dollar'] `Flipping the helicity sends [[MATH_345]], and a minus sign  arises from the diff` |
| 2203.13012/extracted/chapter-1.tex | 1/314 | dollar | ['dollar'] `Flipping the helicity sends [[MATH_345]], and a minus sign  arises from the diff` |
| 2203.13064/extracted/main.tex | 3/118 | dollar | ['dollar'] `As in GECToR, our primary edit operations are encoded by the following tags: \te`<br>['dollar'] `The final stage is inference tweaks [[CITE_93]] for balancing between the model'`<br>['dollar'] `Most of the tag-encoded edits are token-specific, e.g., \textit{\$APPEND\_it}, \` |
| 2211.04509/extracted/main.tex | 5/179 | dollar | ['dollar'] `Chronic diseases are a dire global problem with grand societal and economic impa`<br>['dollar'] `The prediction performance improvement brings prominent economic value. Depressi`<br>['dollar'] `Beyond improving true positives, minimizing false positives deserves special att`<br>['dollar'] `\href[[HREF_685]]{Depression Cost the US \$326 Billion Per Year Pre-Pandemic, a `<br>['dollar'] `Compared to the baseline models, the annual net benefit that our model brings (\` |
| 2211.04533/extracted/main.tex | 1/105 | dollar | ['dollar'] `Participants were instructed to categorize images in the psychophysics dataset a` |
| 2211.04534/extracted/GOAL arxiv/sample-authordraft.tex | 1/122 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2211.04534/extracted/GOAL arxiv/sample-lualatex.tex | 1/122 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2211.04534/extracted/GOAL arxiv/sample-sigconf-i13n.tex | 1/127 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2211.04534/extracted/GOAL arxiv/sample-sigconf.tex | 1/122 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2211.04534/extracted/GOAL arxiv/sample-xelatex.tex | 1/122 | dollar | ['dollar'] `A formula that appears in the running text is called an inline or
in-text formul` |
| 2211.13004/extracted/paper.tex | 1/210 | begin_env | ['begin_env'] `
  In order to lift this restriction, local pattern matches have to be first lam` |
| 2211.13004/extracted/xtorization.tex | 1/17 | begin_env | ['begin_env'] `
  In order to lift this restriction, local pattern matches have to be first lam` |
| 2211.13040/extracted/sintraproposal.tex | 1/36 | dollar | ['dollar'] `Computationally-obtained track resolutions for a northbound LEO test circular or` |
| 2308.04282/extracted/periodograms.tex | 1/190 | dollar | ['dollar'] `In the simulation with Gaussian white noise, the transits can be seen visually i` |
| 2308.12612/extracted/main.tex | 1/193 | cite_family,ref_family | ['cite_family', 'ref_family'] `\ins{In contrast, \tech{} can identify this log sequence as anomalous regardless` |
| 2403.05463/extracted/templateArxiv.tex | 2/168 | dollar,cite_family | ['dollar'] `Flow past a wind turbine% at $Re_c=103600$
`<br>['cite_family'] `Horizontal profiles of mean streamwise velocity deficit at three downstream posi` |
| 2403.15085/extracted/ANA-STDM-2019-24-PAPER.tex | 1/140 | dollar | ['dollar'] `[[CMD_645]]xtrm{\scriptsize 103}[[MATH_646]]^\textrm{\scriptsize 16}[[MATH_647]]` |
| 2403.15085/extracted/atlas_authlist.tex | 1/3 | dollar | ['dollar'] `[[CMD_2]]xtrm{\scriptsize 103}[[MATH_3]]^\textrm{\scriptsize 16}[[MATH_4]]^\text` |
| 2403.15093/extracted/ANA-STDM-2018-43-PAPER.tex | 1/183 | dollar | ['dollar'] `[[CMD_690]]xtrm{\scriptsize 103}[[MATH_691]]^\textrm{\scriptsize 16}[[MATH_692]]` |
| 2403.15093/extracted/atlas_authlist.tex | 1/3 | dollar | ['dollar'] `[[CMD_2]]xtrm{\scriptsize 103}[[MATH_3]]^\textrm{\scriptsize 16}[[MATH_4]]^\text` |
| 2403.15096/extracted/main.tex | 1/580 | dollar | ['dollar'] `\cdot \; \sigma_{\chi}^{-1}\Big( e^{\,-\hbar\,m\,T_i^-} \! , \, e^{\,-\hbar\,T_j` |
| 2410.05969/extracted/DeepNetCounterfeit.tex | 2/77 | dollar | ['dollar'] `Counterfeit drugs, medical systems, and their associated effects are responsible`<br>['dollar'] `The true costs of counterfeits are much higher than direct loss to legitimate ma` |
| 2410.05969/extracted/_paper.tex | 2/55 | dollar | ['dollar'] `Counterfeit drugs, medical systems, and their associated effects are responsible`<br>['dollar'] `The true costs of counterfeits are much higher than direct loss to legitimate ma` |
| 2410.05969/extracted/sec/1_The_problem_of_counterfeit_products.tex | 2/6 | dollar | ['dollar'] `Counterfeit drugs, medical systems, and their associated effects are responsible`<br>['dollar'] `The true costs of counterfeits are much higher than direct loss to legitimate ma` |
| 2410.05981/extracted/PRL_tang.tex | 3/28 | dollar | ['dollar'] `(a) Peak amplitude [[MATH_95]] of the bistable nonlinear states as a function of`<br>['dollar'] `(a) Peak amplitude [[MATH_108]] of the bullet breathers 
%with ${{\mathcal P}=0.`<br>['dollar'] `(a) Isosurface of the noisy input. (b) Excitation of the bulk bullets (with maxi` |
| 2410.06040/extracted/figures/fig_sqrtm-error-vs-hidden-size.tex | 1/1 | dollar | ['dollar'] `
        Estimated error ratio of the square root of the auto-correlation matrix` |
| 2410.17916/extracted/main.tex | 1/158 | cite_family | ['cite_family'] `The evolution of the luminosity function (LF). In green, we show the prediction ` |
| 2410.18024/extracted/main.tex | 1/205 | dollar | ['dollar'] `& [[MACRO_760]]{B} &                    \\
			L(X) [[CMD_761]]   & L(Y) [[CMD_76` |
| astro-ph/0307059/extracted/paper.tex | 1/116 | dollar | ['dollar'] `
Summary of runs with [[MATH_90]] (thus [[MATH_91]]) and forcing at
[[MATH_92]].` |
| astro-ph/0307121/extracted/ms.tex | 4/99 | dollar | ['dollar'] `Only 4 magnetic DB stars were known prior to the SDSS: LB8827 has
[[MATH_75]]~MG`<br>['dollar'] `Like LHS~2534, the spectrum of SDSS J0157+0033 shows a feature at
5893~\AA\ whic`<br>['dollar'] `The key clues to a magnetic interpretation of SDSS J1036+6522 are the triplets
c`<br>['dollar'] `G\"ansicke et al. (2002) interpret the broad depressions near [[MACRO_166]]\ and` |
| astro-ph/9703152/extracted/erospp.tex | 7/143 | ref_family | ['ref_family'] `Nonlinear turbulent diffusion of a magnetic flux tube. 
Shown are snapshots of t`<br>['ref_family'] `
The area enclosed within the current sheet as a function of time. 
The cases [[`<br>['ref_family'] `
Current sheet velocity [[MATH_142]] as a function of [[MATH_143]]
for models wi`<br>['ref_family'] `
Inverse of current sheet velocity [[MATH_149]] as a function of
[[MATH_150]] fo`<br>['ref_family'] `
[[LABEL_175]]
Same as in Fig.~1
%\ref{fig1} 
but with a Gaussian profile as ini` (+2 more) |
| cond-mat/0111300/extracted/ART-REVIEW-102501.tex | 1/263 | dollar | ['dollar'] `Traditionally however, magnetic materials have been studied using 
all-electron ` |
| cond-mat/0605196/extracted/20050401rbp_arxiv.tex | 2/63 | dollar | ['dollar'] `Atom pair states in 1D. (a) Energy spectrum of the 1D Hamiltonian for
[[MATH_115`<br>['dollar'] ` Quasi-momentum distribution of atoms in the lattice.
Images (a) - (c) show abso` |
| hep-ph/0111218/extracted/ContrTrento_17_11_01.tex | 1/85 | dollar | ['dollar'] `\it Projected statistical 
          accuracies for the measurement of [[MATH_66` |
| hep-ph/0307177/extracted/susyewpo_hepph.tex | 2/183 | dollar,conditional | ['dollar', 'conditional'] `Current and anticipated future experimental uncertainties for 
[[MATH_86]], [[MA`<br>['dollar'] `Recently the leading \twol\ corrections to 
[[MATH_148]] at [[CMD_149]] [[CMD_15` |
| hep-ph/9703202/extracted/pap.tex | 3/125 | dollar | ['dollar'] `The partition function for an ideal gas of massless fermions at
temperature [[MA`<br>['dollar'] `We will use the notation~[[CMD_214]] [[MACRO_215]]= { f (r) \over r g } , \qquad`<br>['dollar'] `The Lagrangian for the background gauge fields
then becomes [[MATH_527]] where [` |
| hep-ph/9910335/extracted/main.tex | 1/135 | dollar | ['dollar'] `\baselineskip 18pt Obviously, the proof of eq. (15) presented here relies
on the` |
| hep-th/0605038/extracted/SDrel.tex | 1/467 | begin_env | ['begin_env'] `
\begin{flushright}
{\small NSF-KITP-05-120}
\\
\vspace{-6mm}
{\small Imperial/T` |
| hep-th/9910028/extracted/main.tex | 5/79 | dollar | ['dollar'] `We now return to the   relation between the argument of [\strom] that N=4
supers`<br>['dollar'] `Given [[MATH_419]] almost complex structures satisfying \clif,
the products
[[MA`<br>['dollar'] `The models with [[MATH_462]] supersymmetry can be written in [[MATH_463]] supers`<br>['dollar'] `Real [[MATH_505]] matrices satisfying \clif\ can be constructed from the basic
r`<br>['dollar'] `Performing the [[MATH_542]] integral gives the [[MATH_543]] superspace action
[[` |
| math/0605790/extracted/main.tex | 1/197 | dollar | ['dollar'] `Let [[MATH_491]]. Then we have for
all [[MATH_492]], [[MATH_493]] and all
[[MATH` |
| nucl-th/0307063/extracted/FIERZ11.tex | 1/96 | begin_env | ['begin_env'] `\begin{eqnarray}
[[MACRO_112]]_{sq}^{(3)}=3[[MACRO_113]]^2-\frac34(\sn^2+\sp^2+\` |
| quant-ph/0501111/extracted/lokajicek.tex | 1/185 | begin_env | ['begin_env'] `
\begin{flushright}
\small{FZU-D 20040565 \\[5mm]}
\end{flushright}
Quantum theo` |

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
| 0806.0463/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.23 | 0 |
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
| 0905.4371/extracted | amsart | 12pt,a4paper | 1 | xelatex, no-hyperref | 2 | 1 | 1 | 0.00 | 1 |
| 0905.4380/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4427/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb,prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4439/extracted | aa | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4476/extracted | article | 11 pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 0905.4503/extracted | emulateapj | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.37 | 0 |
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
| 1003.4527/extracted | aa | oldversion | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 19.65 | 0 |
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
| 1012.5145/extracted | revtex4 | aps,prl,twocolumn,showpacs,superscriptaddress | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 2 |
| 1012.5197/extracted | IEEEtran | 12pt,draftclsnofoot, perreview, onecolumn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5220/extracted | article | 10pt,a4paper,oneside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5273/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5491/extracted | revtex4 | aps,preprint,showpacs, showkeys | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5538/extracted | amsart | reqno,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5612/extracted | article | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5773/extracted | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5832/extracted | amsart | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1012.5842/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1109.1664/extracted | aims | — | 1 | non-utf8 | 1 | 1 | 1 | 0.47 | 0 |
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
| 1109.5754/extracted | revtex4-1 | twocolumn,showpacs,amsmath,amssymb,superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 3.39 | 0 |
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
| 1206.2231/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.71 | 0 |
| 1206.2233/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1206.2250/extracted | revtex4 | aps,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5202/extracted | revtex4-1 | rmp,twocolumn,aps | 1 | no-hyperref | 10 | 10 | 10 | 0.00 | 1 |
| 1206.5217/extracted | revtex4 | aps, prl, twocolumn, showpacs, superscriptaddress | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5375/extracted | article | 12pt,fleqn | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5428/extracted | revtex4 | twocolumn,showpacs,preprintnumbers,amsmath,amssymb,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.53 | 0 |
| 1206.5536/extracted | article | a4paper,twoside | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5595/extracted | revtex4 | aps,prl,preprint,tightenlines,superscriptaddress,showpacs,byrevtex,subfigure | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.82 | 0 |
| 1206.5602/extracted | article | a4paper,12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5620/extracted | mn2e | useAMS,usenatbib,onecolumn,letterpaper | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1206.5628/extracted | article | reqno,11pt | 1 | non-utf8 | 1 | 1 | 1 | 0.56 | 0 |
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
| 1306.2365/extracted | article | 10pt | 1 | — | 1 | 1 | 1 | 1.63 | 0 |
| 1306.2498/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5694/extracted | revtex4 | onecolumn, oneside, floats, aps, prd, nobibnotes, nofootinbib, amsmath, amssymb, amsfonts, amscd, superscriptaddress, eqsecnum | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5717/extracted | revtex4 | aps,pra,amsmath,superscriptaddress,reprint,floatfix,notitlepage,balancelastpage,twocolumn,showpacs,reprint | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5749/extracted | revtex4-1 | aps,prl,twocolumn,amsmath,amssymb,amsfonts | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5771/extracted | mn2e | useAMS,usenatbib | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5799/extracted | mn2e | useAMS,usenatbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5813/extracted | iopart | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5826/extracted | emulateapj | english | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1306.5846/extracted | elsarticle | 10pt | 1 | no-hyperref | 2 | 2 | 2 | 4.55 | 0 |
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
| 1306.6224/extracted | llncs | envcountsame,envcountsect,runningheads | 1 | — | 15 | 15 | 15 | 0.27 | 2 |
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
| 1502.06256/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.79 | 0 |
| 1502.06281/extracted | revtex4-1 | aps,pra,reprint,twocolumns,showpacs | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06284/extracted | amsart | — | 1 | — | 16 | 16 | 16 | 0.00 | 0 |
| 1502.06342/extracted | amsart | reqno,12pt,a4paper | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06406/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06421/extracted | revtex4-1 | aip,jap,preprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06426/extracted | emulateapj | apj | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06459/extracted | revtex4-1 | aps, pra, a4paper,twocolumn, showpacs,10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06500/extracted | article | a4paper,twoside,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06527/extracted | revtex4 | aps,prl,twocolumn,groupedaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1502.06541/extracted | iopart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 2.40 | 0 |
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
| 1511.02862/extracted | emulateapj | iop, revtex4 | 1 | no-hyperref | 1 | 1 | 1 | 0.63 | 0 |
| 1511.02908/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.02930/extracted | article | a4paper | 1 | — | 1 | 1 | 1 | — | 0 |
| 1511.02943/extracted | revtex4-1 | 10pt,twocolumn,superscriptaddress,floafix,nobalancelastpage | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06628/extracted | amsart | 12pt, reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06689/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06706/extracted | elsarticle | english,3p,floatfix | 1 | xelatex, non-utf8 | 19 | 19 | 19 | 0.84 | 0 |
| 1511.06725/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06740/extracted | article (×2) | 11pt,a4paper | 2 | non-utf8, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 1511.06744/extracted | article | — | 1 | — | 21 | 21 | 21 | 0.00 | 0 |
| 1511.06763/extracted | mn2e | useAMS,usenatbib,usegraphicx | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06765/extracted | aastex | preprint2 | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1511.06783/extracted | article (×2) | 10pt,twocolumn,letterpaper | 2 | xelatex | 5 | 5 | 5 | 0.00 | 3 |
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
| 1608.06760/extracted | cernphprep | a4paper,manyauthors,nocleardouble,COMPASS | 1 | — | 10 | 10 | 10 | 1.15 | 8 |
| 1608.06769/extracted | article | 12pt | 1 | — | 1 | 1 | 1 | 0.67 | 0 |
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
| 1706.02656/extracted | revtex4-1 | reprint, showpacs, amsmath,amssymb, aps, prl, | 1 | — | 1 | 1 | 1 | 2.86 | 0 |
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
| 1803.03106/extracted | IEEEtran | journal | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 2.00 | 0 |
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
| 1811.09974/extracted | article | letterpaper | 1 | no-hyperref | 7 | 7 | 7 | 1.47 | 0 |
| 1811.10012/extracted | revtex4-1 | aps, prd, twocolumn, lengthcheck, superscriptaddress, showpacs, nofootinbib | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10026/extracted | svjour3 | smallextended | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10029/extracted | article | 10pt,letterpaper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10050/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10086/extracted | amsart | 11pt | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10103/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10148/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10189/extracted | article | 12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1811.10195/extracted | IEEEtran (×2) | conference, onecolumn | 2 | — | 2 | 2 | 2 | 5.00 | 0 |
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
| 1907.03923/extracted | amsart | a4paper,12pt,oneside,reqno | 1 | — | 1 | 1 | 1 | 0.41 | 0 |
| 1907.10324/extracted | neuthist18 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10343/extracted | article | 10pt,twocolumn,letterpaper | 1 | xelatex | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10345/extracted | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10351/extracted | elsarticle | review | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.92 | 0 |
| 1907.10373/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10378/extracted | amsart | 11pt, a4paper, twoside,leqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10382/extracted | article | a4paper,11pt | 1 | no-hyperref | 1 | 1 | 1 | 2.63 | 0 |
| 1907.10392/extracted | svjour3 | smallcondensed | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10434/extracted | revtex4-1 | aps,prl,reprint,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10440/extracted | scrbook | a4paper, titlepage, bibliography=totoc, 12pt, BCOR17mm, DIV12, headinclude, footinclude=false | 1 | — | 9 | 9 | 9 | 0.00 | 0 |
| 1907.10453/extracted | llncs | runningheads | 1 | — | 1 | 1 | 1 | 0.72 | 0 |
| 1907.10454/extracted | IEEEtran | 10pt,journal,compsoc | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10457/extracted | frontiersSCNS | utf8 | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10480/extracted | llncs | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10515/extracted | acmart | sigconf | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10522/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 1907.10567/extracted | revtex4-1 | amsmath,superscriptaddress,showpacs,prb,twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03387/extracted | revtex4 | letterpaper,amsmath, amssymb,aps,prd,nofootinbib, singlecolumn, superscriptaddress,altaffilsymbol | 1 | no-hyperref | 1 | 1 | 1 | 1.27 | 0 |
| 2003.03388/extracted | mnras (×2) | fleqn,usenatbib | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2003.03423/extracted | article | letterpaper,twocolumn,10pt | 1 | no-hyperref | 12 | 12 | 12 | 0.00 | 1 |
| 2003.03430/extracted | revtex4-1 | twocolumn,10pt,amsmath,amssymb,aps,pra,superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03437/extracted | svjour3 | numbook,envcountreset,final | 1 | no-hyperref | 1 | 1 | 1 | 1.23 | 0 |
| 2003.03462/extracted | article | twoside | 1 | — | 2 | 2 | 2 | 0.93 | 0 |
| 2003.03463/extracted | article | — | 1 | — | 11 | 11 | 11 | 0.00 | 1 |
| 2003.03479/extracted | llncs | runningheads | 1 | no-hyperref | 9 | 9 | 9 | 0.00 | 0 |
| 2003.03485/extracted | article | letterpaper | 1 | — | 1 | 1 | 1 | 0.68 | 0 |
| 2003.03503/extracted | revtex4-2 | reprint, superscriptaddress, amsmath,amssymb, aps, | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03508/extracted | standalone (×14) | tikz | 14 | no-hyperref | 14 | 14 | 14 | 0.00 | 0 |
| 2003.03510/extracted | amsart | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03512/extracted | article | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.48 | 0 |
| 2003.03526/extracted | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2003.03533/extracted | wlscirep | fleqn,11pt | 1 | — | 1 | 1 | 1 | 0.88 | 0 |
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
| 2003.10959/extracted | llncs | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 1.41 | 0 |
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
| 2009.11042/extracted | article | letterpaper | 1 | — | 9 | 9 | 9 | 2.29 | 1 |
| 2009.11053/extracted | book (×18) | 11pt,a4paper,oneside,openright | 18 | — | 18 | 18 | 18 | 0.00 | 0 |
| 2009.11072/extracted | IEEEtran | 10pt,journal, compsoc | 1 | no-hyperref | 6 | 6 | 6 | 0.00 | 0 |
| 2009.11090/extracted | llncs | runningheads | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| 2009.11125/extracted | iopart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03729/extracted | revtex4-2 | twocolumn,english,aps,prb,twocolum,superscriptaddress,bibnotes,amsmath,amssymb,floatfix | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03730/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03733/extracted | article | — | 1 | — | 8 | 8 | 8 | 0.00 | 0 |
| 2105.03740/extracted | revtex4-2 | amsmath,amssymb,prx,superscriptaddress,reprint,showpacs,longbibliography | 1 | non-utf8 | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03750/extracted | aastex63 | twocolumn,times | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03753/extracted | lipics-v2021 | a4paper,UKenglish,cleveref, autoref, thm-restate | 1 | no-hyperref | 8 | 8 | 8 | 0.37 | 0 |
| 2105.03772/extracted | aastex61 | preprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03779/extracted | revtex4 | amsmath, amsfonts, superscriptaddress, twocolumn, prl | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03798/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 1.13 | 0 |
| 2105.03806/extracted | article | 12pt,english | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03808/extracted | amsart | 12pt,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03813/extracted | ieeeconf | letterpaper, 10 pt, conference | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03827/extracted | cvpr | final | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2105.03835/extracted | article (×2) | — | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2105.03858/extracted | IEEEtran | journal,twoside | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03883/extracted | IEEEtran | conference | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03900/extracted | amsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03922/extracted | article | english | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03923/extracted | article | — | 1 | — | 9 | 9 | 9 | 0.61 | 0 |
| 2105.03934/extracted | cas-dc | a4paper,fleqn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03940/extracted | amsart | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03943/extracted | article | 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.03955/extracted | amsart | 12pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11393/extracted | revtex4-1 | prl,twocolumn,showpacs,floatfix,amsmath,amssymb,superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11398/extracted | amsart | 10pt | 1 | xelatex | 1 | 1 | 1 | 0.22 | 0 |
| 2105.11413/extracted | revtex4-1 | aps,twocolumn,superscriptaddress,nofootinbib,pre | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11432/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11438/extracted | svjour3 | twocolumn | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2105.11462/extracted | article | letterpaper,11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11479/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11481/extracted | revtex4-1 | showpacs, oneside, twocolumn, amsmath, amssymb, prl, nofootinbib, superscriptaddress | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11487/extracted | amsart | 11 | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2105.11488/extracted | aastex62 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.86 | 0 |
| 2105.11495/extracted | revtex4 | twocolumn,aps,prl,showpacs,superscriptaddress | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04298/extracted | llncs | runningheads | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04333/extracted | aastex63 | twocolumn | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2203.04336/extracted | mnras | fleqn,usenatbib | 1 | no-hyperref | 1 | 1 | 1 | 0.43 | 0 |
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
| 2203.13064/extracted | article | 11pt | 1 | no-hyperref | 1 | 1 | 1 | 2.54 | 0 |
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
| 2211.04509/extracted | informs3b | mnsc | 1 | — | 1 | 1 | 1 | 2.79 | 0 |
| 2211.04515/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04517/extracted | IEEEtran (×2) | letterpaper, 10 pt, journal, twoside | 2 | — | 4 | 4 | 4 | 0.00 | 0 |
| 2211.04533/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.95 | 0 |
| 2211.04534/extracted | acmart (×8) | sigconf | 8 | no-hyperref | 8 | 8 | 8 | 0.46 | 0 |
| 2211.04539/extracted | article (×2) | — | 2 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2211.04559/extracted | article | 12pt,a4paper | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.04574/extracted | mnras (×2) | fleqn,usenatbib | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2211.12986/extracted | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.12990/extracted | article | — | 1 | — | 2 | 2 | 2 | 0.00 | 0 |
| 2211.12997/extracted | pnas-new (×3) | 9pt,twocolumn,twoside,lineno | 3 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 2211.13004/extracted | acmart | acmsmall,10pt, nonacm | 1 | no-hyperref | 11 | 11 | 11 | 0.49 | 0 |
| 2211.13012/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13013/extracted | revtex4 | prd,letterpaper,twocolumn,preprintnumbers,nofootinbib | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13019/extracted | ifacconf (×2) | — | 2 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| 2211.13022/extracted | revtex4-1 | aip,a4paper,onecolumn, amsmath,amssymb, reprint | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13033/extracted | amsart | 12pt,reqno | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2211.13040/extracted | optica-article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 2.78 | 0 |
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
| 2308.12597/extracted | revtex4-2 | reprint, floatfix,superscriptaddress, longbibliography,amsmath,amssymb,aps,prx,showkeys, | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| 2308.12600/extracted | llncs | runningheads | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12608/extracted | article | letterpaper | 1 | no-hyperref | 22 | 22 | 22 | 0.00 | 0 |
| 2308.12610/extracted | article | — | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2308.12612/extracted | acmart | acmsmall,pdftex | 1 | xelatex, no-hyperref | 10 | 10 | 10 | 0.27 | 0 |
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
| 2403.05463/extracted | article | — | 1 | — | 1 | 1 | 1 | 1.19 | 0 |
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
| 2403.15085/extracted | atlasdoc | cernpreprint, atlasdraft=false, UKenglish, texmf, orcidlogo | 1 | no-hyperref | 2 | 2 | 2 | 1.40 | 0 |
| 2403.15089/extracted | llncs | runningheads | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2403.15093/extracted | atlasdoc | PAPER, atlasdraft=false, UKenglish, cernpreprint, texmf, orcidlogo | 1 | no-hyperref | 2 | 2 | 2 | 1.08 | 0 |
| 2403.15096/extracted | amsart | 12pt,reqno,twoside,a4paper | 1 | non-utf8 | 1 | 1 | 1 | 0.17 | 0 |
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
| 2410.05981/extracted | revtex4-2 | reprint, superscriptaddress, showpacs, amsmath,amssymb, prl, | 1 | — | 1 | 1 | 1 | 10.71 | 0 |
| 2410.05985/extracted | article | — | 1 | — | 10 | 10 | 10 | 0.00 | 1 |
| 2410.05995/extracted | revtex4-2 | aps,pra,twocolumn,superscriptaddress,10pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.05999/extracted | elsarticle | preprint,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.06004/extracted | IEEEtran | journal | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.06007/extracted | article | — | 1 | — | 28 | 28 | 28 | 0.00 | 4 |
| 2410.06025/extracted | article | — | 1 | — | 18 | 18 | 18 | 0.00 | 0 |
| 2410.06028/extracted | acmart | sigconf, anonymous=false | 1 | no-hyperref | 3 | 3 | 3 | 0.00 | 0 |
| 2410.06035/extracted | amsart | reqno,centertags,11pt,a4paper | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.06040/extracted | IEEEtran | conference,onecolumn | 1 | — | 33 | 33 | 33 | 0.26 | 4 |
| 2410.17902/extracted | amsart | a4paper, svgnames, 11pt | 1 | — | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17903/extracted | amsart | leqno,12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| 2410.17916/extracted | aa | — | 1 | — | 1 | 1 | 1 | 0.63 | 0 |
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
| 2410.18024/extracted | compositionalityarticle | a4paper,onecolumn,superscriptaddress,10pt,shorttitle=papers | 1 | — | 4 | 4 | 4 | 0.30 | 3 |
| astro-ph/0111038 | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111094 | revtex4 | twocolumn,showpacs,superscriptaddress,prl | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111197 | article | 12pt,epsf,aaspp4 | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111213 | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111323 | aa | — | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0111411 | aa | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307007 | article | 11pt,newpasp,twoside,epsf | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307009 | aa | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307042 | book | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| astro-ph/0307059 | revtex4 | twocolumn,pre,aps,nofootinbib | 1 | no-hyperref | 1 | 1 | 1 | 0.86 | 0 |
| astro-ph/0307121 | aastex | 12pt,preprint | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 4.04 | 0 |
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
| astro-ph/9703152 | article | psfig,apjprepr,amssym,flushrt | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 4.90 | 0 |
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
| cond-mat/0605196 | revtex4 | amsmath, preprintnumbers, sort&compress, twocolumn | 1 | non-utf8, no-hyperref | 2 | 2 | 2 | 2.08 | 0 |
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
| hep-ph/0111218 | article | fleqn,twoside | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 1.18 | 0 |
| hep-ph/0111245 | article | 12pt | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0111248 | aipproc (×2) | cmfonts | 2 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| hep-ph/0111281 | revtex | aps, epsf, psfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0111383 | article | 12pt,epsfig | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0111415 | ws-p8-50x6-00 | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0307118 | revtex | prd,aps,preprint,epsfig | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0307177 | article | 12pt | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 1.09 | 1 |
| hep-ph/0307234 | article | 12pt,a4paper | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0307255 | Rinton-P9x6 | — | 1 | xelatex, no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| hep-ph/0501163 | svjour | epj,final | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0605135 | svjour | epj,nopacs | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0605149 | article | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 0 |
| hep-ph/0605178 | revtex4 | aps,prl,twocolumn,epsfig,preprintnumbers,superscriptaddress,10pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/0605288 | article | 12pt,dvips | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9703202 | — | — | 0 | no-hyperref | 1 | 1 | 1 | 2.40 | 0 |
| hep-ph/9703228 | article | epsfig,12pt | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9703272 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9703300 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9703402 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910332 | article | — | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-ph/9910335 | revtex | preprint,prl,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.74 | 0 |
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
| hep-th/0605038 | article | 12pt,lettersize | 1 | xelatex, non-utf8 | 1 | 1 | 1 | 0.21 | 0 |
| hep-th/0605233 | revtex4 | english,amsmath,amssymb,prd,letter,showpacs,showkeys | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703013 | revtex | preprint,aps | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703073 | — | — | 0 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703086 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703099 | article | 11pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703117 | elsart | 12pt | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703173 | revtex | aps,prl | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703180 | article | 12pt | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9703203 | article | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| hep-th/9910028 | — | — | 0 | no-hyperref | 1 | 1 | 1 | 6.33 | 0 |
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
| math/0605790 | article | a4paper,12pt | 1 | non-utf8, no-hyperref | 1 | 1 | 1 | 0.51 | 0 |
| math/9703222 | amsart | 11pt,amstex | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/9910113 | amsppt | — | 1 | reject, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| math/9910177 | gtart | — | 1 | no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
| nucl-ex/9910015 | article | 12pt,twoside,fleqn,amssymb,epsfig,espcrc1,graphicx | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/0111058 | revtex | prc,epsfig,aps | 1 | reject, xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| nucl-th/0307063 | article | 12pt, graphicx | 1 | reject, non-utf8, no-hyperref | 1 | 1 | 1 | 1.04 | 0 |
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
| quant-ph/0501111 | article | twopage,11pt | 1 | xelatex, non-utf8, no-hyperref | 1 | 1 | 1 | 0.54 | 0 |
| quant-ph/0605071 | article | — | 1 | xelatex, no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/0605205 | revtex4 | pra,preprint,aps,floats | 1 | no-hyperref | 1 | 1 | 1 | 0.00 | 0 |
| quant-ph/9703040 | article | 12pt,qqa4lart | 1 | reject, no-hyperref | 2 | 2 | 2 | 0.00 | 1 |
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
| IEEEtran | 51 | 153 | 100.0 | 100.0 | 0.17 |
| IEEEtran_doc_class | 1 | 2 | 100.0 | 100.0 | 0.00 |
| JHEP3 | 2 | 2 | 100.0 | 100.0 | 0.00 |
| PoS | 4 | 5 | 100.0 | 100.0 | 0.00 |
| Rinton-P9x6 | 1 | 2 | 100.0 | 100.0 | 0.00 |
| SciPost | 1 | 5 | 100.0 | 100.0 | 0.00 |
| WileyNJD-v2 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aa | 13 | 14 | 100.0 | 100.0 | 2.42 |
| aachanged | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aastex | 18 | 25 | 100.0 | 100.0 | 0.25 |
| aastex3 | 1 | 4 | 100.0 | 100.0 | 0.00 |
| aastex6 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aastex61 | 3 | 3 | 100.0 | 100.0 | 0.00 |
| aastex62 | 2 | 2 | 100.0 | 100.0 | 0.59 |
| aastex62_reep | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aastex63 | 3 | 4 | 100.0 | 100.0 | 0.00 |
| aastex631 | 1 | 1 | 100.0 | 100.0 | 0.53 |
| achemso | 1 | 2 | 100.0 | 100.0 | 0.00 |
| acmart | 7 | 52 | 100.0 | 100.0 | 0.34 |
| acmartmod | 1 | 1 | 100.0 | 100.0 | 0.00 |
| acmsmall | 2 | 21 | 100.0 | 100.0 | 0.00 |
| aer | 1 | 1 | 100.0 | 100.0 | 0.00 |
| agutex2015 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| aims | 1 | 1 | 100.0 | 100.0 | 0.47 |
| aipproc | 5 | 6 | 100.0 | 100.0 | 0.00 |
| amsart | 108 | 129 | 99.2 | 100.0 | 0.02 |
| amsppt | 1 | 1 | 100.0 | 100.0 | 0.00 |
| an | 1 | 1 | 100.0 | 100.0 | 0.00 |
| appolb | 1 | 1 | 100.0 | 100.0 | 0.00 |
| article | 331 | 738 | 100.0 | 100.0 | 0.13 |
| arximspdf | 1 | 1 | 100.0 | 100.0 | 0.00 |
| atlasdoc | 2 | 4 | 100.0 | 100.0 | 1.22 |
| autart | 1 | 1 | 100.0 | 100.0 | 0.00 |
| birkjour | 2 | 2 | 100.0 | 100.0 | 0.00 |
| book | 3 | 45 | 100.0 | 100.0 | 0.00 |
| cas-dc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| cernphprep | 1 | 10 | 100.0 | 100.0 | 1.15 |
| cfm2011 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| compositionalityarticle | 1 | 4 | 100.0 | 100.0 | 0.30 |
| cpcauth | 1 | 1 | 100.0 | 100.0 | 0.00 |
| crckapb | 2 | 2 | 100.0 | 100.0 | 0.00 |
| cvpr | 2 | 10 | 100.0 | 100.0 | 0.00 |
| dis07 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ecai | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsart | 3 | 3 | 100.0 | 100.0 | 0.00 |
| elsart3 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| elsarticle | 20 | 41 | 100.0 | 100.0 | 0.41 |
| emulateapj | 16 | 23 | 100.0 | 100.0 | 0.09 |
| eptcs | 2 | 3 | 100.0 | 100.0 | 0.00 |
| frontiersSCNS | 1 | 1 | 100.0 | 100.0 | 0.00 |
| gtart | 1 | 2 | 100.0 | 100.0 | 0.00 |
| hep99 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ieeeconf | 9 | 66 | 100.0 | 100.0 | 0.00 |
| ifacconf | 2 | 3 | 100.0 | 100.0 | 0.00 |
| imsart | 2 | 2 | 100.0 | 100.0 | 0.00 |
| informs3b | 1 | 1 | 100.0 | 100.0 | 2.79 |
| iopart | 17 | 20 | 100.0 | 100.0 | 0.16 |
| ismdproc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jaa | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jac | 1 | 2 | 100.0 | 100.0 | 0.00 |
| jmlr | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jpconf | 5 | 5 | 100.0 | 100.0 | 0.00 |
| jps-cp | 1 | 1 | 100.0 | 100.0 | 0.00 |
| jpsj | 1 | 1 | 100.0 | 100.0 | 0.00 |
| laa | 1 | 1 | 100.0 | 100.0 | 0.00 |
| lipics-v2019 | 1 | 3 | 100.0 | 100.0 | 0.00 |
| lipics-v2021 | 1 | 8 | 100.0 | 100.0 | 0.37 |
| llncs | 22 | 76 | 100.0 | 100.0 | 0.09 |
| mn | 1 | 1 | 100.0 | 100.0 | 0.00 |
| mn2e | 13 | 18 | 100.0 | 100.0 | 0.00 |
| mnras | 9 | 22 | 100.0 | 100.0 | 0.06 |
| mybookalone | 1 | 1 | 100.0 | 100.0 | 0.00 |
| neuthist18 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| optica-article | 1 | 1 | 100.0 | 100.0 | 2.78 |
| pasj00 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| pnas-new | 1 | 3 | 100.0 | 100.0 | 0.00 |
| pro12 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| quantumarticle | 1 | 1 | 100.0 | 100.0 | 0.00 |
| report | 2 | 2 | 100.0 | 100.0 | 0.00 |
| revtex | 29 | 29 | 100.0 | 100.0 | 0.05 |
| revtex4 | 126 | 133 | 100.0 | 100.0 | 0.08 |
| revtex4-1 | 67 | 94 | 100.0 | 100.0 | 0.08 |
| revtex4-2 | 12 | 14 | 100.0 | 100.0 | 0.38 |
| scrartcl | 2 | 4 | 100.0 | 100.0 | 0.00 |
| scrbook | 1 | 9 | 100.0 | 100.0 | 0.00 |
| sig-alternate | 2 | 27 | 100.0 | 100.0 | 0.00 |
| sig-alternate-05-2015 | 1 | 12 | 100.0 | 100.0 | 0.00 |
| sigma | 1 | 1 | 100.0 | 100.0 | 0.00 |
| spie | 3 | 3 | 100.0 | 100.0 | 0.00 |
| standalone | 1 | 14 | 100.0 | 100.0 | 0.00 |
| svjour | 6 | 6 | 100.0 | 100.0 | 0.00 |
| svjour3 | 5 | 6 | 100.0 | 100.0 | 0.15 |
| tMOP2e | 1 | 1 | 100.0 | 100.0 | 0.00 |
| vgtc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| webofc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| wlscirep | 2 | 2 | 100.0 | 100.0 | 0.63 |
| ws-p8-50x6-00 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| ws-procs9x6 | 1 | 1 | 100.0 | 100.0 | 0.00 |
| — | 5 | 10 | 100.0 | 100.0 | 2.27 |

## by era

| era | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| new | 800 | 1731 | 99.9 | 100.0 | 0.14 |
| old | 200 | 224 | 100.0 | 100.0 | 0.15 |

## by archive

| archive | papers | files | ok% | ident% | leak% |
|---|---|---|---|---|---|
| astro-ph | 37 | 41 | 100.0 | 100.0 | 0.39 |
| chao-dyn | 2 | 3 | 100.0 | 100.0 | 0.00 |
| cond-mat | 40 | 43 | 100.0 | 100.0 | 0.10 |
| cs | 4 | 11 | 100.0 | 100.0 | 0.00 |
| gr-qc | 1 | 1 | 100.0 | 100.0 | 0.00 |
| hep-ex | 3 | 3 | 100.0 | 100.0 | 0.00 |
| hep-lat | 2 | 2 | 100.0 | 100.0 | 0.00 |
| hep-ph | 27 | 31 | 100.0 | 100.0 | 0.25 |
| hep-th | 29 | 29 | 100.0 | 100.0 | 0.16 |
| math | 24 | 25 | 100.0 | 100.0 | 0.02 |
| math-ph | 2 | 2 | 100.0 | 100.0 | 0.00 |
| nucl-ex | 1 | 1 | 100.0 | 100.0 | 0.00 |
| nucl-th | 6 | 6 | 100.0 | 100.0 | 0.18 |
| physics | 6 | 8 | 100.0 | 100.0 | 0.00 |
| q-alg | 2 | 2 | 100.0 | 100.0 | 0.00 |
| quant-ph | 11 | 13 | 100.0 | 100.0 | 0.14 |
| solv-int | 3 | 3 | 100.0 | 100.0 | 0.00 |
| — | 800 | 1731 | 99.9 | 100.0 | 0.14 |
