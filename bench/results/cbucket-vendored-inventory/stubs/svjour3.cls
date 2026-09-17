% texlate vendored stub — 原许可禁分发，最小兼容面
% svjour3.cls S1 替身：© Springer "仅限 Springer 期刊投稿使用"不可 vendored。
% 骨架=article + SVJour frontmatter/期刊 cs no-op；真件的 *.clo 伴生
% （svglov3.clo 等 journal-option 件）由 \journalopt 路由全吞，防二级
% missing_file；旁落 svglov3.clo no-op 同档防直 \input。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{svjour3}[texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{svjour3.cls is a compatibility shim}

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
\providecommand{\PACS}[1]{\gdef\@pacs{#1}}
\providecommand{\keywords}[1]{\gdef\@keywords{#1}}
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
