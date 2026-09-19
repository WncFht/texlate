% texlate vendored stub — 原许可禁分发，最小兼容面
% imsart.cls S1 替身：VTEX/IMS 直发、许可核不到 → stub。IMS 期刊
% class 骨架=article + frontmatter 系 cs/env 面。
% C-bucket 补面（1012.2012/1206.1960/1811.10292 三格 Misplaced \crcr
% 实证）：稿面为 \begin{frontmatter}\author{\fnms…\snm…\ead[…]{…}}
% \address[…]{…\printead{…}}\and\author{…}\end{frontmatter}——裸 \and
% 在 article 下只在 \maketitle tabular 内合法（核内 \and→\endtabular
% →\crcr），frontmatter 体内局部降为 \relax；作者块宏面 \fnms/\snm/
% \inits/\degs/\ead/\corref/\printead/\thanksref 按真件 imsart.sty
% 语义收（\corref 真件即 noop）；作者/地址累积，\end{frontmatter}
% 吐 title/authors/addresses 块（真件 frontmatter 尾隐含排版，稿多无
% \maketitle 显调）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{imsart}[2026/09/19 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{imsart.cls is a compatibility shim}

\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\LoadClass[10pt]{article}

% —— IMS frontmatter 面 ——
% 作者/地址累积仓（\end{frontmatter} 一次吐）
\def\@imsaddr{}
% \@title/\@author 核内默认是报错宏（No \title/\author given）——
% frontmatter 尾吐前要清成空，免得没设 \title 的稿反被 emit 炸
\gdef\@title{}
\gdef\@author{}
% \author[opts]{name} 多次调用累积（真件单作者单 \author 制；
% ", " 连接——不用 \and：env 内 \and 已驯化、\@author 也可能进
% 非 tabular 位）
\renewcommand{\author}[2][]{%
  \ifx\@author\@empty\gdef\@author{#2}\else\g@addto@macro\@author{, #2}\fi}
% \address[opts]{…} 累积地址块；\\ 保留——吐在正文段落域合法
% （article 原生无 \address → providecommand 不设 \renewcommand）
\providecommand{\address}[2][]{\g@addto@macro\@imsaddr{\par{\footnotesize #2}}}
\providecommand{\affiliation}[1]{\gdef\@affiliation{#1}}
\providecommand{\email}[1]{\gdef\@email{#1}}
\providecommand{\keyword}[1]{\gdef\@keywords{#1}}
\providecommand{\keywords}[1]{\keyword{#1}}
\providecommand{\amsclass}[1]{\gdef\@amsclass{#1}}
\providecommand{\received}[1]{}
\providecommand{\revised}[1]{}
\providecommand{\accepted}[1]{}
\providecommand{\publishedonline}[1]{}
\providecommand{\corresp}[1]{}
\providecommand{\thankstext}[2]{}
\providecommand{\dedication}[1]{}
\providecommand{\runtitle}[1]{\gdef\@runtitle{#1}}
\providecommand{\runauthor}[1]{\gdef\@runauthor{#1}}
\def\@runtitle{}\def\@runauthor{}\def\@affiliation{}\def\@email{}\def\@keywords{}\def\@amsclass{}
% —— 作者块宏面（真件 imsart.sty:1291/716 实证：\fnms/\snm/\inits/\degs
%    passthrough、\corref noop；\ead[keys]{addr} 真件走 keyval，
%    stub 出地址本体） ——
\providecommand{\fnms}[1]{#1}
\providecommand{\snm}[1]{#1}
\providecommand{\inits}[1]{#1}
\providecommand{\degs}[1]{#1}
\providecommand{\roles}[1]{#1}
\providecommand{\corref}[1]{}
\providecommand{\ead}[2][]{\texttt{#2}}
\providecommand{\thanksref}[1]{\textsuperscript{#1}}
% \printead[*][opt]{ref}：真件按 label 回印存址；stub 邮件已由 \ead
% 内联出，此处吞参 noop
\providecommand{\printead}{\@ifstar\texlate@ims@pe\texlate@ims@pe}
\def\texlate@ims@pe{\@ifnextchar[{\texlate@ims@pea}{\texlate@ims@pea[]}}
\def\texlate@ims@pea[#1]#2{}
% \arxiv{id}：真件 imsart 有 arXiv 号位 (frontmatter 收)，stub 以
% AtBeginDocument 包印 —— preamble/in-doc 双安全 (1003.1513 实证:
% transductionPap1.tex:166 \arxiv{math.PR/0000512} 无 stub 提供 → undefined_cs)
\providecommand{\arxiv}[1]{\AtBeginDocument{\par\noindent{\footnotesize arXiv:#1}\par}}
% —— frontmatter/aug env：真件 \end{frontmatter} 隐含排版头块；stub
%    begin 驯化 \and（作者块分隔符），end 吐 title/authors/address ——
\newenvironment{frontmatter}{\let\and\relax}{\texlate@ims@emit}
\newenvironment{aug}{\let\and\relax}{}
\def\texlate@ims@emit{%
  \par\vspace{1em}{\Large\bfseries\@title\par}\vspace{.5em}%
  {\@author\par}%
  \ifx\@imsaddr\@empty\else\vspace{.5em}\@imsaddr\fi
  \par\vspace{1em}}
\endinput
