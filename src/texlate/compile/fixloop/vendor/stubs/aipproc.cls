% texlate vendored stub — 原许可禁分发，最小兼容面
% aipproc.cls 替身：AIP 会议文集老类（© AIP，不在 TL）→ article +
% AIP frontmatter polyfill。自 shim_map aipproc.cls 条迁移（1306.2177
% 实证：\layoutstyle/\keywords/\pacs + 双参 keyval
% \author{Name}{address={...}}；astro-ph/0104134 \address 单参散调）。
% 本 stub 在场则 shim_map aipproc.cls 条成死配置（vendored 预检先于 missing_file 落件，
% 同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{aipproc}[texlate stub — original not redistributable]
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
\renewcommand{\author}[2]{%
  \setkeys{fixaip@a}{#2}%
  \ifx\fixaip@authors\@empty
    \gdef\fixaip@authors{#1\ifx\fixaip@addr\@empty\else\\{\footnotesize\fixaip@addr}\fi}%
  \else
    \g@addto@macro\fixaip@authors{\and #1\ifx\fixaip@addr\@empty\else\\{\footnotesize\fixaip@addr}\fi}%
  \fi
  \def\fixaip@addr{}}
% 真身 aipproc.cls 的致谢环境 (AIPacknowledgments 版式头) —
% 1306.2177 实证: 无头容器即可, 语义=不带号小节
\newenvironment{theacknowledgments}
  {\par\noindent\textbf{Acknowledgments.}\space}{\par}
% 批八 (astro-ph/0104134 实证): elsart 式 \address{...} 单参
% 散调 —— aipproc 双参 keyval \author 不盖, 脚注块保文
\providecommand{\address}[1]{\par{\footnotesize #1\par}}
\endinput
