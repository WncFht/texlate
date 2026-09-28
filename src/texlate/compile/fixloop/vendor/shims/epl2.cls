% texlate vendored stub — 原许可禁分发，最小兼容面
% epl2.cls 替身：EPL (Europhysics Letters) 二号类 (© EDP，不在
% TL) → article + epl frontmatter/bbl-struct 面。自 shim_map
% epl2.cls 条迁移 (1503.00248 实证)。增量: \RequirePackage{graphicx}
% —— 稿 \graphicspath{{../figures/}} 在类缺席时流落 p1 文本
% (1503.00248 diag 实证)；graphicx TL 在场恒可载。
% 本 stub 在场则 shim_map epl2.cls 条成死配置（vendored 预检
% 先于 missing_file 落件，同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{epl2}[2026/09/28 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{epl2.cls is a compatibility shim -> article + epl polyfills}
\LoadClassWithOptions{article}
\RequirePackage{graphicx}
% ── frontmatter 存值 (PRE 调用, \maketitle 包装吐) ──
\let\epl@abstract\@empty
\let\epl@inst\@empty
\def\epl@pacs{}
\providecommand{\abstract}{}
\renewcommand{\abstract}[1]{\gdef\epl@abstract{#1}}
\providecommand{\institute}[1]{\gdef\epl@inst{#1}}
\providecommand{\pacs}[2]{\g@addto@macro\epl@pacs{\par\noindent\textbf{PACS:} #1\quad #2\par}}
\providecommand{\inst}[1]{\textsuperscript{#1}}
\providecommand{\shorttitle}[1]{}
\providecommand{\shortauthor}[1]{}
\providecommand{\shortinstitute}[1]{}
\providecommand{\email}[1]{\texttt{#1}}
\let\epl@mk\maketitle
\renewcommand{\maketitle}{\epl@mk
  \ifx\epl@inst\@empty\else\par\noindent{\small\epl@inst}\par\fi
  \ifx\epl@abstract\@empty\else\begin{quote}\textbf{Abstract.}---\enspace\epl@abstract\end{quote}\fi
  \epl@pacs}
% ── acknowledgments 双形: \newenvironment 的 begin 段即排版体 ——
% 裸 \acknowledgments 调用与 \begin{...} 环境两形通吃
% (0905.1214 cs 形 / 1003.0792 env 形实证)。\stars 真件里是
% \acknowledgments 别名。
\newenvironment{acknowledgments}{\par\medskip\noindent\textbf{Acknowledgments.}\space}{\par}
\newenvironment{acknowledgements}{\par\medskip\noindent\textbf{Acknowledgements.}\space}{\par}
\providecommand{\stars}{\par\medskip\noindent\textbf{Acknowledgments.}\space}
\providecommand{\shrinkacknowledgments}[1]{}
\providecommand{\enlargeacknowledgments}[1]{}
% ── bbl-struct 宏族 (真件抄值): \bibitem 前置复位 + \ifepl@book ──
\newif\ifepl@book\epl@bookfalse
\newif\ifepl@gotand\epl@gotandfalse
\let\epl@org@bibitem\bibitem
\def\bibitem{\epl@bookfalse\epl@org@bibitem}
\providecommand{\Name}[1]{{\let\and\epl@and\scshape #1},}
\providecommand{\Review}[1]{\epl@bookfalse{\itshape #1},}
\providecommand{\REVIEW}[4]{\Review{#1} \Vol{#2} \Year{#3} \Page{#4}}
\providecommand{\Book}[1]{\epl@booktrue{\itshape #1}}
\providecommand{\Vol}[1]{\ifepl@book\else{\bfseries #1}\fi}
\providecommand{\Year}[1]{\ifepl@book\else(#1)\fi}
\providecommand{\Page}[1]{\ifepl@book\else p.~#1\fi}
\providecommand{\Pages}[1]{\ifepl@book\else pp.~#1\fi}
\providecommand{\Publ}[1]{\ifepl@book\unskip\ \fi{\normalfont(#1)}}
\providecommand{\Editor}[1]{\epl@gotandfalse{\let\and\epl@and\normalfont #1}, ed.}
\providecommand{\Section}[1]{#1}
\providecommand{\SAME}[3]{}
\def\epl@and{\unskip\ and\ }
\let\And\and
\endinput
