% texlate vendored stub — 原许可禁分发，最小兼容面
% memo-l.cls 替身：memoir+amsaddr 混合书稿类 (IMS 讲义系，TL 无)
% → memoir 底 + ams frontmatter polyfill。自 shim_map memo-l.cls
% 条迁移 (1003.0348 实证面: \frontmatter、\address/\email/\thanks
% 前置收集、\subjclass[2000]{...}、\keywords{...}、\onehalfspacing)。
% 增量: \RequirePackage{amsthm}——1003.0348 preamble 用
% \theoremstyle{definition}/{remark} + \begin{proof}×15 而稿自身
% 不装 amsthm，yaml 原 needs 面 (memoir+setspace) 无此件 →
% \theoremstyle Undefined。amsthm TL 在场恒可载；稿自装幂等。
% 本 stub 在场则 shim_map memo-l.cls 条成死配置（vendored 预检
% 先于 missing_file 落件，同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{memo-l}[2026/09/28 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{memo-l.cls is a compatibility shim -> memoir + ams-addr polyfills}
\LoadClassWithOptions{memoir}
\RequirePackage{setspace}
\RequirePackage{amsthm}
\let\memol@subj\@empty
\let\memol@keys\@empty
\providecommand{\address}[1]{\g@addto@macro\@author{\\ {\normalsize\itshape\begin{tabular}[t]{@{}c@{}}#1\end{tabular}}}}
\providecommand{\email}[1]{\g@addto@macro\@author{\\ {\footnotesize\texttt{#1}}}}
\providecommand{\subjclass}[2][2000]{\gdef\memol@subj{\par\noindent{\footnotesize #1 \textit{Mathematics Subject Classification.} #2}\par}}
\providecommand{\keywords}[1]{\gdef\memol@keys{\par\noindent{\footnotesize\textbf{Keywords:} #1}\par}}
\renewcommand{\thanks}[1]{\g@addto@macro\@author{\\ {\footnotesize #1}}}
\let\memol@mk\maketitle
\renewcommand{\maketitle}{\memol@mk
  \ifx\memol@subj\@empty\else\memol@subj\fi
  \ifx\memol@keys\@empty\else\memol@keys\fi}
\endinput
