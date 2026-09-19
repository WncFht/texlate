% texlate vendored stub — 原许可禁分发，最小兼容面
% aipproc.cls 替身：AIP 会议文集老类（© AIP，不在 TL）→ article +
% AIP frontmatter polyfill。自 shim_map aipproc.cls 条迁移（1306.2177
% 实证：\layoutstyle/\keywords/\pacs + 双参 keyval
% \author{Name}{address={...}}；astro-ph/0104134 \address 单参散调）。
% 本 stub 在场则 shim_map aipproc.cls 条成死配置（vendored 预检先于 missing_file 落件，
% 同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{aipproc}[2026/09/19 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{aipproc.cls is a compatibility shim -> article + AIP polyfills}
\LoadClassWithOptions{article}
\RequirePackage{keyval}
% 真件装载面 (1109.2354 随稿抄值): calc/ifthen/graphicx[final]/url —
% AIP 稿 \includegraphics/\url 由类提供, 缺则 undefined_cs; aipxfm/
% mathtime 字体件属 AIP 私有字体 (不在 TL), 不补。
\RequirePackage{calc}
\RequirePackage{ifthen}
\RequirePackage[final]{graphicx}
\RequirePackage{url}
\providecommand{\layoutstyle}[1]{}
\providecommand{\classification}[1]{}
\providecommand{\keywords}[1]{\par\noindent\textbf{Keywords:} #1\par}
\providecommand{\pacs}[1]{\par\noindent\textbf{PACS:} #1\par}
\def\fixaip@addr{}
\define@key{fixaip@a}{address}{\gdef\fixaip@addr{#1}}
\define@key{fixaip@a}{altaddress}{\gdef\fixaip@addr{#1}}
\define@key{fixaip@a}{email}{}
\define@key{fixaip@a}{homepage}{}
\def\fixaip@authors{}
\def\@author{\fixaip@authors}
% \author 双签名（真件两代分歧）：新 aipproc.cls（1306.2177 实证）
% 双参 keyval \author{Name}{address={...}}；老 REVTeX3 系 aipproc.sty
% （astro-ph/0104007 随稿实证 \def\author#1）单参 \author{names} +
% 散调 \address{}。次参仅当紧随 { 组存在时消费——2 参硬吃后随
% \address cs 致 \setkeys 展开炸 \csname/keyval（0104007 :250
% Missing \endcsname + Extra \endcsname + keyval Error 级联实证）。
\renewcommand{\author}[1]{%
  \@ifnextchar\bgroup{\fixaip@author@kv{#1}}{\fixaip@author@plain{#1}}}
\def\fixaip@author@kv#1#2{%
  \setkeys{fixaip@a}{#2}%
  \fixaip@author@add{#1\ifx\fixaip@addr\@empty\else\\{\footnotesize\begin{tabular}[t]{@{}c@{}}\fixaip@addr\end{tabular}}\fi}%
  \def\fixaip@addr{}}
\def\fixaip@author@plain#1{\fixaip@author@add{#1}}
\def\fixaip@author@add#1{%
  \ifx\fixaip@authors\@empty
    \gdef\fixaip@authors{#1}%
  \else
    \g@addto@macro\fixaip@authors{\and #1}%
  \fi}
% 真身 aipproc.cls 的致谢环境 (AIPacknowledgments 版式头) —
% 1306.2177 实证: 无头容器即可, 语义=不带号小节
\newenvironment{theacknowledgments}
  {\par\noindent\textbf{Acknowledgments.}\space}{\par}
% 批八 (astro-ph/0104134 实证): elsart 式 \address{...} 单参
% 散调 —— aipproc 双参 keyval \author 不盖, 脚注块保文
\providecommand{\address}[1]{\par{\footnotesize #1\par}}
% —— references env（老 REVTeX3 系真件抄值，0104007 实证
%    env_undefined + \@listctr×12 级联——每 \bibitem 在 list 外炸）：
%    \section* REFERENCES + enumiv \list，\bibitem 由 kernel 在
%    enumiv list 内工作；\@biblabel 真件式 {n.}（真件 L1426 同值，
%    覆盖 article [n]）。真件 \thebibliography→\references 单向别名
%    不盖 article 本体 env ——
\def\@biblabel#1{#1.}
\newenvironment{references}{%
  \section*{REFERENCES}%
  \list{\@biblabel{\arabic{enumiv}}}{%
    \settowidth\labelwidth{\@biblabel{99}}%
    \labelsep1ex
    \leftmargin\labelwidth\advance\leftmargin\labelsep
    \itemsep\z@\parsep\z@
    \usecounter{enumiv}%
    \let\p@enumiv\@empty
    \def\theenumiv{\arabic{enumiv}}}%
  \footnotesize\let\newblock\relax\sloppy
  \clubpenalty4000 \widowpenalty4000 \sfcode`\.=1000\relax}
  {\def\@noitemerr{\@warning{Empty `references' environment}}%
   \endlist}
% —— 老 REVTeX3 系散件（真件同署，0104007 稿面注释调用——他稿
%    活调防 undefined_cs）：running-head 存值 + 致谢 env ——
\providecommand{\righthead}[1]{\gdef\@oddhead{\reset@font\it\hfil\uppercase{#1}\hfil}}
\providecommand{\lefthead}[1]{\gdef\@evenhead{\reset@font\it\hfil\uppercase{#1}\hfil}}
\newenvironment{acknowledgments}{\section*{ACKNOWLEDGMENTS}}{\par}
\endinput
