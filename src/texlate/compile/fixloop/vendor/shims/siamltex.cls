% texlate vendored stub — 原许可禁分发，最小兼容面
% siamltex.cls 替身：SIAM 老 LaTeX2e 类 (© SIAM，不在 TL) →
% article + SIAM polyfill + 独有定理机。自 shim_map siamltex.cls
% 条迁移 (1503.00411 实证; 真身 corpus/1102.0075 随稿抄值)：
% onethmnum 选项切平排/[section] 排; theorem 持 counter,
% lemma/corollary/proposition/definition [theorem] 联号; proof
% 是 \def 命令对非 env; \@begintheorem 系 scshape 头 + \it 体。
% siamart 不共享此面——真 siamart 走 amsthm, 稿多自备 \newtheorem,
% 预定义必撞 (0807.5094 No counter 'theorem' 实证)。
% 本 stub 在场则 shim_map siamltex.cls 条成死配置（vendored 预检
% 先于 missing_file 落件，同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{siamltex}[2026/09/28 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{siamltex.cls is a compatibility shim -> article + SIAM polyfills}
\newif\if@onethmnum\@onethmnumfalse
\DeclareOption{onethmnum}{\@onethmnumtrue}
\ProcessOptions\relax
\LoadClassWithOptions{article}
\providecommand{\slugger}[5]{}
\providecommand{\shorttitle}[1]{}
\providecommand{\shortauthor}[1]{}
\providecommand{\PII}[1]{}
\@ifundefined{keywords}{\newenvironment{keywords}{\par\noindent\textbf{Keywords:}\space}{\par}}{}
\@ifundefined{AMS}{\newenvironment{AMS}{\par\noindent\textbf{AMS subject classifications:}\space}{\par}}{}
\def\@begintheorem#1#2{\par\bgroup{\scshape #1\ #2. }\it\ignorespaces}
\def\@opargbegintheorem#1#2#3{\par\bgroup%
   {\scshape #1\ #2\ ({\upshape #3}). }\it\ignorespaces}
\def\@endtheorem{\egroup}
\def\proof{\par{\it Proof}. \ignorespaces}
\def\endproof{\vbox{\hrule height0.6pt\hbox{%
   \vrule height1.3ex width0.6pt\hskip0.8ex
   \vrule width0.6pt}\hrule height0.6pt}}
\if@onethmnum
  \newtheorem{theorem}{Theorem}
\else
  \newtheorem{theorem}{Theorem}[section]
\fi
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{corollary}[theorem]{Corollary}
\newtheorem{proposition}[theorem]{Proposition}
\newtheorem{definition}[theorem]{Definition}
% clsfidcen 补面 (siamltex ~11 格; 真件 corpus/2511.16127 随稿
% 抄形): mathop 族真件 \operator@font 是 amsopn 私有 → \mathrm
% 降级; \sameauthor/\URL verbatim; romannum/remunerate list env +
% AM abssec 降级; \Appendix = \secdef 换 \section + Alpha 编号
% (:521-547)
\providecommand{\const}{\mathop{\mathrm{const}}\nolimits}
\providecommand{\diag}{\mathop{\mathrm{diag}}\nolimits}
\providecommand{\grad}{\mathop{\mathrm{grad}}\nolimits}
\providecommand{\Range}{\mathop{\mathrm{Range}}\nolimits}
\providecommand{\rank}{\mathop{\mathrm{rank}}\nolimits}
\providecommand{\supp}{\mathop{\mathrm{supp}}\nolimits}
\providecommand{\sameauthor}{\leavevmode\vrule height 2pt depth -1.6pt width 23pt}
\providecommand{\URL}{\protect\\ \hspace*{15.37pt}http://www.siam.org/journals/}
\providecommand{\AMname}{AMS subject classification}
\@ifundefined{AM}{\newenvironment{AM}{\par\noindent\textbf{\AMname.}\space}{\par}}{}
\@ifundefined{c@rmnum}{\newcounter{rmnum}}{}
\@ifundefined{romannum}{\newenvironment{romannum}
   {\begin{list}{{\upshape (\roman{rmnum})}}{\usecounter{rmnum}
    \setlength{\leftmargin}{0pt}\setlength{\itemindent}{42pt}}}{\end{list}}}{}
\@ifundefined{c@muni}{\newcounter{muni}}{}
\@ifundefined{remunerate}{\newenvironment{remunerate}
   {\begin{list}{{\upshape \arabic{muni}.}}{\usecounter{muni}
    \setlength{\leftmargin}{0pt}\setlength{\itemindent}{38pt}}}{\end{list}}}{}
\providecommand{\Append}[2][?]{\refstepcounter{section}%
  {\vskip 1.3ex \@plus .5ex \@minus .2ex
   \reset@font\normalsize\bfseries\appendixname\ \thesection. #2.}}
\providecommand{\sAppend}[1]{\refstepcounter{section}%
  {\vskip 1.3ex \@plus .5ex \@minus .2ex
   \reset@font\normalsize\bfseries\appendixname. #1.}}
\providecommand{\Appendix}{\renewcommand{\section}{\secdef\Append\sAppend}%
  \setcounter{section}{0}\setcounter{subsection}{0}%
  \renewcommand\thesection{\Alph{section}}}
\endinput
