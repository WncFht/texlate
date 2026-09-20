% texlate vendored stub — 原许可禁分发，最小兼容面
% JHEP3.cls 替身：SISSA 高能类（© SISSA/IOP，不在 TL）→ article +
% 真 JHEP3.cls 面（corpus/0806.2278 随稿件抄值）。自 shim_map JHEP3.cls
% 条迁移（sissa_body 共享体：\author 单参多调用累积 \long 宏；
% \auto@maketitle 的 \AtBeginDocument emit 同款；0905.1170 amssymb 实证）。
% 与 JHEP.cls stub 同体。
% 本 stub 在场则 shim_map JHEP3.cls 条成死配置（vendored 预检先于 missing_file 落件，
% 同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{JHEP3}[2026/09/19 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{JHEP3.cls is a compatibility shim -> article + SISSA polyfills}
\LoadClassWithOptions{article}
\RequirePackage{amssymb}
% 存值位: \let 初始化保证 \ifx\@empty 判定真 (\gdef 短参 store
% 同款; \renewcommand 产出 \long 宏永远 \ifx-不等 \@empty)
\let\sissa@abstract\@empty
\let\sissa@keywords\@empty
\let\sissa@preprint\@empty
\let\sissa@received\@empty
\let\sissa@revised\@empty
\let\sissa@accepted\@empty
\let\sissa@dedicated\@empty
\let\sissa@subheader\@empty
\let\sissa@collaboration\@empty
\let\sissa@proceeding\@empty
\let\sissa@arxivnumber\@empty
\def\sissa@affils{}
\providecommand{\abstract}{}
\renewcommand{\abstract}[1]{\gdef\sissa@abstract{#1}}
\providecommand{\keywords}[1]{\gdef\sissa@keywords{#1}}
\providecommand{\preprint}[1]{\gdef\sissa@preprint{#1}}
\providecommand{\received}[1]{\gdef\sissa@received{#1}}
\providecommand{\revised}[1]{\gdef\sissa@revised{#1}}
\providecommand{\accepted}[1]{\gdef\sissa@accepted{#1}}
\providecommand{\dedicated}[1]{\gdef\sissa@dedicated{#1}}
\providecommand{\subheader}[1]{\gdef\sissa@subheader{#1}}
\providecommand{\collaboration}[1]{\gdef\sissa@collaboration{#1}}
\providecommand{\collaborationImg}[2][]{\gdef\sissa@collaboration{#2}}
\providecommand{\proceeding}[1]{\gdef\sissa@proceeding{#1}}
\providecommand{\arxivnumber}[1]{\gdef\sissa@arxivnumber{#1}}
\providecommand{\affiliation}[2][]{\g@addto@macro\sissa@affils{\par#2}}
\providecommand{\JHEPspecialurl}[1]{}
\providecommand{\JHEP}[1]{}
% \href 降级为打印第二参 (真件是 pdf-link 版; 1308.0304 \href×107 实证)。
% eprint 档号族真件 \href{xxx.lanl.gov/abs/X/#1}{\tt X/#1} → {\tt X/#1}
% 打印面 (\Math 两参 math.AG/n 形, \arXivid 现代 arXiv 号)。
\providecommand{\href}[2]{#2}
\providecommand{\hepth}[1]{\texttt{hep-th/#1}}
\providecommand{\hepph}[1]{\texttt{hep-ph/#1}}
\providecommand{\heplat}[1]{\texttt{hep-lat/#1}}
\providecommand{\hepex}[1]{\texttt{hep-ex/#1}}
\providecommand{\nuclth}[1]{\texttt{nucl-th/#1}}
\providecommand{\nuclex}[1]{\texttt{nucl-ex/#1}}
\providecommand{\grqc}[1]{\texttt{gr-qc/#1}}
\providecommand{\qalg}[1]{\texttt{q-alg/#1}}
\providecommand{\accphys}[1]{\texttt{accphys/#1}}
\providecommand{\alggeom}[1]{\texttt{alg-geom/#1}}
\providecommand{\astroph}[1]{\texttt{astro-ph/#1}}
\providecommand{\chaodyn}[1]{\texttt{chao-dyn/#1}}
\providecommand{\condmat}[1]{\texttt{cond-mat/#1}}
\providecommand{\nlinsys}[1]{\texttt{nlin-sys/#1}}
\providecommand{\quantph}[1]{\texttt{quant-ph/#1}}
\providecommand{\solvint}[1]{\texttt{solv-int/#1}}
\providecommand{\suprcon}[1]{\texttt{supr-con/#1}}
\providecommand{\Math}[2]{\texttt{math.#1/#2}}
\providecommand{\arXivid}[1]{\texttt{arXiv:#1}}
\providecommand{\email}[1]{\texttt{#1}}
\providecommand{\emailAdd}[1]{\g@addto@macro\sissa@affils{\par\texttt{#1}}}
\providecommand{\note}[2][]{\thanks{#2}}
\providecommand{\speaker}[1]{}
\providecommand{\conference}[1]{}
\providecommand{\acknowledgments}{\section*{Acknowledgments}}
\providecommand{\acknowledgements}{\section*{Acknowledgements}}
\providecommand{\xtumfont}[1]{\textsc{#1}}
\providecommand{\notoc}{}
\providecommand{\compress}{}
\providecommand{\toccontinuous}{}
\providecommand{\beforetochook}{}
\providecommand{\afterLogoSpace}{}\providecommand{\afterSubheaderSpace}{}
\providecommand{\afterProceedingsSpace}{}\providecommand{\afterTitleSpace}{}
\providecommand{\afterRuleSpace}{}\providecommand{\afterCollaborationSpace}{}
\providecommand{\afterCollaborationImgSpace}{}
\providecommand{\afterAuthorSpace}{}\providecommand{\afterAffiliationSpace}{}
\providecommand{\afterEmailSpace}{}\providecommand{\afterXtumSpace}{}
\providecommand{\afterAbstractSpace}{}\providecommand{\afterKeywordsSpace}{}
\providecommand{\afterArxivSpace}{}\providecommand{\afterDedicatedSpace}{}
\providecommand{\afterTocSpace}{}\providecommand{\afterTocRuleSpace}{}
\providecommand{\correctionref}[3]{\gdef\sissa@dedicated{Erratum #1 #3}}
\providecommand{\erratum}[4][ibid.~]{Erratum #1{\bfseries#2} (#3) #4}
\providecommand{\addendum}[4][ibid.~]{Addendum #1{\bfseries#2} (#3) #4}
\providecommand{\ibid}[3]{ibid.~{\bfseries#1} (#2) #3}
% \author 单参多调用累积: 块内含 \\ + \email/\thanks/\it 全保留,
% article maketitle tabular 内逐块换行输出
\newif\if@sissaauth\@sissaauthfalse
\renewcommand{\author}[1]{%
  \if@sissaauth\g@addto@macro\@author{\\#1}%
  \else\gdef\@author{#1}\@sissaauthtrue\fi}
% \@maketitle 段落式重定义 (真件 flushleft 作者块同款): article 原版
% tabular{c} 囚 \begin{itemize}/\bigskip → Not allowed in LR mode
% (0712.1912 实证); 段落组内 \\ 续排、块级内容全存活。
\def\@maketitle{%
  \begin{flushleft}%
    {\LARGE\sffamily\bfseries\@title\par}%
    \vskip1.5em%
    {\normalsize\bfseries\sffamily\@author\par}%
    \vskip1em%
    {\large\@date\par}%
  \end{flushleft}\par\vskip1.5em}
% JHEP3 floatflt 系 float 速记 → 标准 env 降级 (可选参数是
% 版式词非 placement, 一律 [htbp])
\providecommand{\FIGURE}[2][]{\begin{figure}[htbp]\centering#2\end{figure}}
\providecommand{\TABLE}[2][]{\begin{table}[htbp]\centering#2\end{table}}
\providecommand{\EPSFIGURE}[3][]{\begin{figure}[htbp]\centering
  \@ifundefined{includegraphics}{}{\includegraphics{#2}}\caption{#3}\end{figure}}
\providecommand{\DOUBLEFIGURE}[5][]{\begin{figure}[htbp]\centering
  \@ifundefined{includegraphics}{}{\includegraphics{#2}\hfil\includegraphics{#3}}%
  \caption{#4}\par{\small#5}\end{figure}}
\providecommand{\TABULAR}[4][]{\begin{table}[htbp]\centering\begin{tabular}{#2}#3\end{tabular}\caption{#4}\end{table}}
\providecommand{\DOUBLETABLE}[5][]{\begin{table}[htbp]\centering#2\caption{#4}\end{table}%
  \begin{table}[htbp]\centering#3\caption{#5}\end{table}}
% \auto@maketitle: emit 在 AtBeginDocument (真件同款), 随后冻结
% \maketitle —— 稿显式调用成 no-op, 不调也不丢 frontmatter
\let\sissa@mk\maketitle
\AtBeginDocument{%
  \ifx\sissa@preprint\@empty\else\noindent{\footnotesize\sissa@preprint}\par\fi
  \sissa@mk
  \ifx\sissa@collaboration\@empty\else\par\noindent{\itshape\sissa@collaboration}\par\fi
  \ifx\sissa@affils\@empty\else\par\noindent{\small\sissa@affils}\par\fi
  \ifx\sissa@dedicated\@empty\else\par\noindent{\itshape\sissa@dedicated}\par\fi
  \ifx\sissa@proceeding\@empty\else\par\noindent{\small\itshape\sissa@proceeding}\par\fi
  \ifx\sissa@abstract\@empty\else\begin{quote}\textbf{\abstractname.}\enspace\sissa@abstract\end{quote}\fi
  \ifx\sissa@keywords\@empty\else\par\noindent\textbf{Keywords:} \sissa@keywords\par\fi
  \ifx\sissa@arxivnumber\@empty\else\par\noindent{\small arXiv:\sissa@arxivnumber}\par\fi
  \ifx\sissa@subheader\@empty\else\par\noindent{\small\sissa@subheader}\par\fi
  \begingroup
    \def\sissa@dline{}\def\sissa@sep{}%
    \ifx\sissa@received\@empty\else\gdef\sissa@sep{~}\fi
    \ifx\sissa@revised\@empty\else\ifx\sissa@received\@empty\else\def\sissa@sep{; }\fi\fi
    \ifx\sissa@received\@empty\else Received \sissa@received\sissa@sep\fi
    \ifx\sissa@revised\@empty\else revised \sissa@revised;\space\fi
    \ifx\sissa@accepted\@empty\else accepted \sissa@accepted\fi
  \endgroup\par
  \let\maketitle\relax}
\providecommand{\ps@myplain}{\let\@mkboth\@gobbletwo
  \let\@oddhead\@empty\def\@oddfoot{\hfil-- \thepage\ --\hfil}%
  \let\@evenhead\@oddhead\let\@evenfoot\@oddfoot}
% JHEP3 三参期刊宏族 (hep-th/0408134 实证 \bibitem 五连):
% \npb{76}{1974}{310} → "Nucl.~Phys.~B 76 (1974) 310"。
% \@ifnextchar\bgroup 双态分派: 带 brace = 全引文排版,
% 裸调 = 缩写直印——与 aas4_body 式 0 参缩写面同形兼容,
% 不撞 (本 body 原无期刊缩写定义, 0408134 全三参形)。
\def\sissa@jrnl#1{\@ifnextchar\bgroup{\sissa@jrnl@x{#1}}{#1}}
\def\sissa@jrnl@x#1#2#3#4{#1 {\bfseries#2} (#3) #4}
\providecommand{\npb}{\sissa@jrnl{Nucl.~Phys.~B}}
\providecommand{\plb}{\sissa@jrnl{Phys.~Lett.~B}}
\providecommand{\prl}{\sissa@jrnl{Phys.~Rev.~Lett.}}
\providecommand{\prd}{\sissa@jrnl{Phys.~Rev.~D}}
\providecommand{\pre}{\sissa@jrnl{Phys.~Rev.~E}}
\providecommand{\pra}{\sissa@jrnl{Phys.~Rev.~A}}
\providecommand{\prb}{\sissa@jrnl{Phys.~Rev.~B}}
\providecommand{\prc}{\sissa@jrnl{Phys.~Rev.~C}}
\providecommand{\pr}{\sissa@jrnl{Phys.~Rev.}}
\providecommand{\epjc}{\sissa@jrnl{Eur.~Phys.~J.~C}}
\providecommand{\zpc}{\sissa@jrnl{Z.~Phys.~C}}
\providecommand{\jphg}{\sissa@jrnl{J.~Phys.~G}}
\providecommand{\tmp}{\sissa@jrnl{Theor.~Math.~Phys.}}
\providecommand{\ijmpa}{\sissa@jrnl{Int.~J.~Mod.~Phys.~A}}
\providecommand{\mpla}{\sissa@jrnl{Mod.~Phys.~Lett.~A}}
\providecommand{\cqg}{\sissa@jrnl{Class.~Quant.~Grav.}}
\providecommand{\physrep}{\sissa@jrnl{Phys.~Rep.}}
\providecommand{\rmp}{\sissa@jrnl{Rev.~Mod.~Phys.}}
\providecommand{\cmp}{\sissa@jrnl{Commun.~Math.~Phys.}}
\providecommand{\ncim}{\sissa@jrnl{Nuovo~Cim.}}
\providecommand{\jhep}{\sissa@jrnl{JHEP}}
\providecommand{\jcap}{\sissa@jrnl{JCAP}}
% ── 批十一 (clsfidcen 普查 ~10 格): \sissa@jrnl 期刊缩写补员 + \newjournal/\PrHEP ──
% 打印名按真件 JHEP3.cls @spires 表 (corpus/1003.0694 随稿) 抄值;
% 双态分派沿用: 带 brace → "名 vol (yr) pg" 引文形, 裸调 → 缩写直印。
\providecommand{\ap}{\sissa@jrnl{Ann.~Phys.~(NY)}}
\providecommand{\ptp}{\sissa@jrnl{Prog.~Theor.~Phys.}}
\providecommand{\ptps}{\sissa@jrnl{Prog.~Theor.~Phys.~Suppl.}}
\providecommand{\prep}{\sissa@jrnl{Phys.~Rept.}}
\providecommand{\atmp}{\sissa@jrnl{Adv.~Theor.~Math.~Phys.}}
\providecommand{\adnp}{\sissa@jrnl{Adv.~Nucl.~Phys.}}
\providecommand{\npps}{\sissa@jrnl{Nucl.~Phys.~Proc.~Suppl.}}
\providecommand{\ppnp}{\sissa@jrnl{Prog.~Part.~Nucl.~Phys.}}
\providecommand{\app}{\sissa@jrnl{Astropart.~Phys.}}
\providecommand{\apj}{\sissa@jrnl{Astrophys.~J.}}
\providecommand{\am}{\sissa@jrnl{Ann.~Math.}}
\providecommand{\nc}{\sissa@jrnl{Nuovo~Cim.}}
% \newjournal{name}{spires-code}{vol}{yr}{pg}: 真件走 @spires 链接
% (:1683), 降级丢 code 参打印引文形 (引文序 vol/yr/pg 不变)
\providecommand{\newjournal}[5]{{\itshape #1 }{\bfseries #3} (#4) #5}
% \PrHEP 真件是 dvipdf \special logo 件 (:1714); 非 dvipdf 分支
% \let\PrHEP\gobble (:1729) —— shim 取 noop 同款
\providecommand{\PrHEP}[1]{}
\endinput
