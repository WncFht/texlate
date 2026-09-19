% texlate vendored stub — 原许可禁分发，最小兼容面
% svjour3.cls S1 替身：© Springer "仅限 Springer 期刊投稿使用"不可 vendored。
% 骨架=article + SVJour frontmatter/期刊 cs no-op；真件的 *.clo 伴生
% （svglov3.clo 等 journal-option 件）由 \journalopt 路由全吞，防二级
% missing_file；旁落 svglov3.clo no-op 同档防直 \input。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{svjour3}[2026/09/19 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{svjour3.cls is a compatibility shim}

% 真件 natbib 类选项面 (corpus/1811.03539 实证 svjour3.cls:67-74):
% \documentclass[natbib]{svjour3} → AtEndOfClass 装 natbib+版式参数;
% 星号转发会把 natbib 当未知 option 丢给 article 静默吞掉 → \citep
% undefined。先于星号声明, 照真件抄值。
\DeclareOption{natbib}{%
\AtEndOfClass{\RequirePackage{natbib}%
\setlength{\bibhang}{\parindent}%
\let\bibfont=\small
\def\@biblabel#1{#1.}%
\newcommand{\etal}{et al.}%
\bibpunct{(}{)}{;}{a}{}{,}}}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\LoadClass[10pt,twoside]{article}

% --- journal-option 路由：真件 \input{sv<opt>.clo}，stub 一律 no-op ---
\providecommand{\journalopt}{}
\let\validfor\@undefined

% --- SVJour frontmatter ---
\providecommand{\journalname}[1]{}
\providecommand{\journal}[1]{}
\providecommand{\titlerunning}[1]{\gdef\@titlerunning{#1}}
\providecommand{\authorrunning}[1]{\gdef\@authorrunning{#1}}
\providecommand{\institute}[1]{\gdef\@institute{#1}}
\providecommand{\email}[1]{\gdef\@email{#1}}
\providecommand{\mail}[1]{\email{#1}}
\providecommand{\subtitle}[1]{\gdef\@subtitle{#1}}
\providecommand{\dedication}[1]{\gdef\@dedication{#1}}
\providecommand{\communicated}[1]{}
\providecommand{\datein}{}
\providecommand{\offprints}[1]{}
% --- 分类行打印面（真件 1306.0443 随稿 svjour3.cls:300-317 语义抄值：
%    \keywords/\subclass/\PACS 均为即时打印块，体内 \and 局部重绑为
%    "·" 分隔——稿面 \subclass{90C31\and 90C25} 靠此成立） ---
\providecommand{\svj@andsep}{\ifhmode\unskip\nobreak\fi\ $\cdot$\ }
\providecommand{\PACS}[1]{\par\medskip\noindent\textbf{PACS}\enspace{\let\and\svj@andsep\ignorespaces #1\par}}
\providecommand{\subclassname}{{\bfseries Mathematics Subject Classification}\enspace}
\providecommand{\subclass}[1]{\par\medskip\noindent\subclassname{\let\and\svj@andsep\ignorespaces #1\par}}
\providecommand{\keywords}[1]{\par\medskip\noindent\textbf{Keywords}\enspace{\let\and\svj@andsep\ignorespaces #1\par}}
\providecommand{\keyword}[1]{\keywords{#1}}
\providecommand{\acknowledgement}[1]{\gdef\@acknowledgement{#1}}
\providecommand{\ackname}{Acknowledgements}
\providecommand{\thesaurus}[1]{}
\providecommand{\MSC}[1]{}
\providecommand{\CRCP}[1]{}
\providecommand{\subtitleparagraph}[1]{\paragraph{#1}}
\def\@titlerunning{}\def\@authorrunning{}\def\@subtitle{}\def\@dedication{}
\def\@institute{}\def\@email{}\def\@pacs{}\def\@keywords{}\def\@acknowledgement{}

% --- 结构 env ---
\renewenvironment{abstract}{\par\noindent\textbf{\abstractname.}\enspace\ignorespaces}{\par}
\newenvironment{acknowledgements}{\par\noindent\textbf{\ackname.}\enspace\ignorespaces}{\par}
\providecommand{\inst}[1]{\textsuperscript{#1}}
\providecommand{\at}{}
\providecommand{\andname}{\quad}
\providecommand{\runend}{}

% --- bbl 排序件 noop（svjour 系 .bbl 散调 \sortlist…\endsortlist） ---
\providecommand{\sortlist}[2][]{}
% \end* 名受 \@ifdefinable 保护（"name \end... illegal"）——只能 csname 直 def
\expandafter\def\csname endsortlist\endcsname{}

% --- theorem 面：真件 \spnewtheorem 机（svjour3.cls:786-922）的
%    三式签名映射进 kernel \newtheorem——
%    \spnewtheorem{name}{cap}[within]{capf}{bodyf}（within 式）
%    \spnewtheorem{name}[like]{cap}{capf}{bodyf}（同计数器式）
%    \spnewtheorem*{name}{cap}{capf}{bodyf}（不编号式）
%    字体两参丢弃（版式降级），cap/body 保留 ---
\providecommand{\spnewtheorem}{\@ifstar\texlate@svj@uthm\texlate@svj@thm}
\def\texlate@svj@thm#1{\@ifnextchar[{\texlate@svj@thmA{#1}}{\texlate@svj@thmB{#1}}}
\def\texlate@svj@thmA#1[#2]#3#4#5{\newtheorem{#1}[#2]{#3}}
\def\texlate@svj@thmB#1#2{\@ifnextchar[{\texlate@svj@thmC{#1}{#2}}{\texlate@svj@thmD{#1}{#2}}}
\def\texlate@svj@thmC#1#2[#3]#4#5{\newtheorem{#1}{#2}[#3]}
\def\texlate@svj@thmD#1#2#3#4{\newtheorem{#1}{#2}}
\def\texlate@svj@uthm#1#2#3#4{\@ifundefined{#1}%
  {\newenvironment{#1}{\par\noindent{\bfseries#2}\enspace\ignorespaces}{\par}}{}}
% --- 预定义 env 集（真件 svjour3 自带；不预定义则稿 \begin{theorem}
%    炸 "No counter 'theorem'" / "Environment … undefined"。全走
%    \@ifundefined 守卫。proof 不预定义：amsthm 后到 \newenvironment{proof}
%    会撞已定义） ---
\@ifundefined{theorem}{\newtheorem{theorem}{Theorem}[section]}{}
\@ifundefined{lemma}{\newtheorem{lemma}[theorem]{Lemma}}{}
\@ifundefined{corollary}{\newtheorem{corollary}[theorem]{Corollary}}{}
\@ifundefined{proposition}{\newtheorem{proposition}[theorem]{Proposition}}{}
\@ifundefined{definition}{\newtheorem{definition}[theorem]{Definition}}{}
\@ifundefined{example}{\newtheorem{example}[theorem]{Example}}{}
\@ifundefined{remark}{\newtheorem{remark}[theorem]{Remark}}{}
\@ifundefined{conjecture}{\newtheorem{conjecture}[theorem]{Conjecture}}{}
\@ifundefined{claim}{\newtheorem{claim}[theorem]{Claim}}{}
\endinput
