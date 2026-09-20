% texlate vendored stub — 原许可禁分发，最小兼容面
% ifacconf.cls S1 替身：IFAC 会议 documentclass (© IFAC, elsevier 系
% 衍生直发, 不在 CTAN/TL —— kpsewhich 零命中实证) → stub。面按真件
% (corpus/2212.00149 随稿 1732 行本) + corpus 实调用对账 (7 稿同款):
% \begin{document} 后 frontmatter env 收 \title/\author[L]/\thanks[L]/
% \address[L]/abstract/keyword, \endfrontmatter 吐块; thm 族/pf/ack/
% algorithm float 由 AtBeginDocument 守卫式补 (稿自义/包提供优先)。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{ifacconf}[2026/09/20 texlate stub — original not redistributable]
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\LoadClass{article}
\PackageWarningNoLine{texlate-stub}{ifacconf.cls is a compatibility shim}

% —— frontmatter 存值面 ——
\def\@ifacaddr{}
\newif\if@ifacauth
\newsavebox{\ifac@fmA}\newsavebox{\ifac@fmK}
% \thanksref{label} 在 \title 参内标脚位 (真件 fnsymbol 族);
% stub 单记 * 近似
\providecommand{\thanksref}[1]{\textsuperscript{*}}
% \address[L]{aff} 标签参吞, 逐调累积成行块, \endfrontmatter 附印
\providecommand{\address}[2][]{\g@addto@macro\@ifacaddr{\par#2}}
% frontmatter env: \author[L] 多调累积 (真件同款签名; 首调覆 article
% "No \author" 占位), \thanks[L]{t} 静默收 \@thanks —— 脚位标记由
% \thanksref 担, 顶层裸调不吐 stray mark; abstract/keyword 局部改义
% 收盒保印序 (article 序: 标题块 → 地址 → 摘要 → 关键词);
% \endfrontmatter \maketitle 后按序吐块 —— 真件 \endfrontmatter
% 同款一次性排版职责
\newenvironment{frontmatter}{%
  \@ifacauthfalse
  \renewcommand{\author}[2][]{%
    \if@ifacauth\g@addto@macro\@author{\and##2}%
    \else\gdef\@author{##2}\@ifacauthtrue\fi}%
  \renewcommand{\thanks}[2][]{%
    \protected@xdef\@thanks{\@thanks\protect\footnotetext[\the\c@footnote]{##2}}}%
  \renewenvironment{abstract}{%
    \lrbox{\ifac@fmA}\begin{minipage}{\textwidth}\small
    {\bfseries\abstractname}\enspace\ignorespaces}%
    {\end{minipage}\endlrbox}%
  \newenvironment{keyword}{%
    \lrbox{\ifac@fmK}\begin{minipage}{\textwidth}\small
    {\itshape Key words: }\ignorespaces}%
    {\end{minipage}\endlrbox}%
}{\maketitle
  \ifx\@ifacaddr\@empty\else\par\noindent{\small\itshape\@ifacaddr}\par\fi
  \ifvoid\ifac@fmA\else\par\noindent\usebox{\ifac@fmA}\par\fi
  \ifvoid\ifac@fmK\else\par\noindent\usebox{\ifac@fmK}\par\fi}

% —— thm 族 + pf/ack/algorithm/NoHyper (真件 cls :631-674 同款名表,
%    稿自义/包提供胜出 —— 守卫后评, 防撞同名) ——
\AtBeginDocument{%
  \@ifundefined{thm}{\newtheorem{thm}{Theorem}}{}%
  \@ifundefined{cor}{\newtheorem{cor}[thm]{Corollary}}{}%
  \@ifundefined{lem}{\newtheorem{lem}[thm]{Lemma}}{}%
  \@ifundefined{claim}{\newtheorem{claim}[thm]{Claim}}{}%
  \@ifundefined{axiom}{\newtheorem{axiom}[thm]{Axiom}}{}%
  \@ifundefined{conj}{\newtheorem{conj}[thm]{Conjecture}}{}%
  \@ifundefined{fact}{\newtheorem{fact}[thm]{Fact}}{}%
  \@ifundefined{hypo}{\newtheorem{hypo}[thm]{Hypothesis}}{}%
  \@ifundefined{assum}{\newtheorem{assum}[thm]{Assumption}}{}%
  \@ifundefined{prop}{\newtheorem{prop}[thm]{Proposition}}{}%
  \@ifundefined{crit}{\newtheorem{crit}[thm]{Criterion}}{}%
  \@ifundefined{defn}{\newtheorem{defn}[thm]{Definition}}{}%
  \@ifundefined{exmp}{\newtheorem{exmp}[thm]{Example}}{}%
  \@ifundefined{rem}{\newtheorem{rem}[thm]{Remark}}{}%
  \@ifundefined{prob}{\newtheorem{prob}[thm]{Problem}}{}%
  \@ifundefined{prin}{\newtheorem{prin}[thm]{Principle}}{}%
  \@ifundefined{alg}{\newtheorem{alg}{Algorithm}}{}%
  \@ifundefined{note}{\newtheorem{note}{Note}}{}%
  \@ifundefined{summ}{\newtheorem{summ}{Summary}}{}%
  \@ifundefined{case}{\newtheorem{case}{Case}}{}%
  \@ifundefined{pf}{%
    \@namedef{pf}{\par\noindent\textbf{Proof.}\enspace}%
    \@namedef{endpf}{\par}}{}%
  \@ifundefined{ack}{%
    \@namedef{ack}{\section*{Acknowledgements}}%
    \@namedef{endack}{}}{}%
  \@ifundefined{algorithm}{%
    \newcounter{algorithm}%
    \def\thealgorithm{\@arabic\c@algorithm}%
    \def\fnum@algorithm{Algorithm \thealgorithm}%
    \@namedef{algorithm}{\@float{algorithm}}%
    \@namedef{endalgorithm}{\end@float}}{}%
  \@ifundefined{NoHyper}{\@namedef{NoHyper}{}\@namedef{endNoHyper}{}}{}%
}
\endinput
