% texlate vendored stub — 原许可禁分发，最小兼容面
% svjour.cls 替身：Springer 期刊类老版（© Springer，不在 TL）→
% article + svjour 宏面 polyfill。自 shim_map svjour.cls 条迁移（1404.6180
% \documentclass[epj]{svjour} 实证；\abstract cmd/env 双形分派；
% theorem/proof 预置基座；biblatex v2.8 bbl polyfill——1706.00221
% MaxDiss.bbl 格式偏斜的 \sortlist/\entry/\name/\field 直排版）。
% 稿自带 svjour.cls 缺 .clo 伴船的情形由 svjour_clo_stub 规则管，不吃本条。
% 本 stub 在场则 shim_map svjour.cls 条成死配置（vendored 预检先于 missing_file 落件，
% 同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{svjour}[texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{svjour.cls is a compatibility shim -> article + svjour polyfills}
\LoadClassWithOptions{article}
\RequirePackage{amssymb}
\RequirePackage{keyval}
\providecommand{\journalname}[1]{}
\providecommand{\titlerunning}[1]{}
\providecommand{\authorrunning}[1]{}
\providecommand{\mail}[1]{}
\providecommand{\offprints}[1]{}
\providecommand{\communicated}[1]{}
\providecommand{\dedication}[1]{}
\providecommand{\submitted}[1]{}
\providecommand{\email}[1]{\texttt{#1}}
\providecommand{\inst}[1]{\textsuperscript{#1}}
\providecommand{\keywords}[1]{\par\noindent\textbf{Keywords:} #1\par}
\providecommand{\PACS}[1]{{\let\and\quad\par\noindent\textbf{PACS:} #1\par}}
\providecommand{\MSC}[1]{{\let\and\quad\par\noindent\textbf{MSC:} #1\par}}
\providecommand{\subclass}[1]{}
\providecommand{\CR}[1]{}
\def\svj@extra{}
\providecommand{\institute}[1]{\g@addto@macro\svj@extra{{\let\and\quad\footnotesize #1}\par}}
\providecommand{\subtitle}[1]{\g@addto@macro\svj@extra{{\large #1}\par}}
\@ifundefined{ack}{\newenvironment{ack}{\par\noindent\textbf{Acknowledgements.}\space}{\par}}{}
\@ifundefined{acknowledgement}{\newenvironment{acknowledgement}{\par\noindent\textbf{Acknowledgement.}\space}{\par}}{}
% theorem/proof 基座 (真件预置族): doc \newtheorem{defn}[theorem]
% 依赖共享计数器 —— 预置 theorem env + counter (2104.00026)
\@ifundefined{theorem}{\newtheorem{theorem}{Theorem}}{}
\providecommand{\proofname}{Proof}
\@ifundefined{proof}{\newenvironment{proof}{\par\noindent\textbf{\proofname.}\space}{\qed\par}}{}
\providecommand{\qed}{\hfill$\square$}
% \abstract cmd/env 双形: \begin{abstract} 走原 env-begin
% (\@ifnextchar 见到 env 体首 token 非 { → 老路), \abstract{txt}
% 走包装 (2104.00026 cmd 形 / 1706.00221 env 形两证)
\let\svj@oldabs\abstract
\let\svj@oldendabs\endabstract
\def\svj@abscmd#1{\svj@oldabs #1\svj@oldendabs}
\renewcommand{\abstract}{\@ifnextchar\bgroup{\svj@abscmd}{\svj@oldabs}}
\let\svj@maketitle\maketitle
\renewcommand{\maketitle}{\svj@maketitle\begingroup\svj@extra\par\endgroup}
% ── biblatex v2.8 bbl polyfill (格式偏斜保底) ──
% \list/\entry/\field/\name 只准活在 \sortlist 组内 ——
% 内核 \list 是所有 list 系环境的基底, 全局重定义全崩
\def\svj@fld@title{title}\def\svj@fld@booktitle{booktitle}
\def\svj@fld@jtitle{journaltitle}\def\svj@fld@year{year}
\def\svj@fld@vol{volume}\def\svj@fld@num{number}
\def\svj@fld@pages{pages}\def\svj@fld@note{note}
\def\svj@fld@series{series}\def\svj@fld@school{school}
\def\svj@fld@inst{institution}\def\svj@fld@org{organization}
\def\svj@fldemit#1#2{\def\svj@fk{#1}%
  \ifx\svj@fk\svj@fld@title\textit{#2} \fi
  \ifx\svj@fk\svj@fld@booktitle\textit{#2} \fi
  \ifx\svj@fk\svj@fld@jtitle#2 \fi
  \ifx\svj@fk\svj@fld@year#2 \fi
  \ifx\svj@fk\svj@fld@vol#2 \fi
  \ifx\svj@fk\svj@fld@num#2 \fi
  \ifx\svj@fk\svj@fld@pages#2 \fi
  \ifx\svj@fk\svj@fld@note#2 \fi
  \ifx\svj@fk\svj@fld@series#2 \fi
  \ifx\svj@fk\svj@fld@school#2 \fi
  \ifx\svj@fk\svj@fld@inst#2 \fi
  \ifx\svj@fk\svj@fld@org#2 \fi}
% \name 第 4 参 {{hash}{k=v..}} 序列: 逐元素 keyval 解出
% prefix/given/family/suffix 直印 (遍历用 \def+\ifx 宏比较 —
% 裸 \ifx 比多 token 实参会吞首 token 毁流)
\define@key{svjn}{family}{\def\svj@fam{#1}}
\define@key{svjn}{given}{\def\svj@giv{#1}}
\define@key{svjn}{prefix}{\def\svj@pre{#1}}
\define@key{svjn}{suffix}{\def\svj@suf{#1}}
\define@key{svjn}{familyi}{}\define@key{svjn}{giveni}{}
\define@key{svjn}{prefixi}{}\define@key{svjn}{suffixi}{}
\define@key{svjn}{hash}{}\define@key{svjn}{useprefix}{}
\define@key{svjn}{usehash}{}\define@key{svjn}{gender}{}
\def\svj@nil{\svj@nil}
\def\svj@nelt#1#2{\let\svj@fam\@empty\let\svj@giv\@empty
  \let\svj@pre\@empty\let\svj@suf\@empty
  \setkeys{svjn}{#2}%
  \ifx\svj@pre\@empty\else\svj@pre~\fi
  \ifx\svj@giv\@empty\else\svj@giv~\fi
  \ifx\svj@fam\@empty\else\svj@fam\fi
  \ifx\svj@suf\@empty\else, \svj@suf\fi, }
\def\svj@nwalk#1{\def\svj@cur{#1}\ifx\svj@cur\svj@nil
  \else\svj@nelt#1\expandafter\svj@nwalk\fi}
% bib*/sortlist 面让位真 biblatex: 整面缓到 AtBeginDocument ——
% cls 装载期先 provide 会抢占 biblatex 后到的 \newcommand 名
% (bibinitdelim/bibnamedelim*/bibrangedash/revsdnamepunct,
%  1706.00221 实证 already_def×6); \begin{document} 期 biblatex
% 已就位 → provide 自动 no-op, 未装时 polyfill 兜底 (bbl 总在
% 正文 \printbibliography 才读)。注意 AtBeginDocument 存储链
% (\xdef 经由) 吃掉一层 # —— 组内 \def 用 ## 而非 #### (实测)。
\AtBeginDocument{%
  \providecommand{\bibinitperiod}{.}%
  \providecommand{\bibinitdelim}{}%
  \providecommand{\bibnamedelima}{ }%
  \providecommand{\bibnamedelimb}{ }%
  \providecommand{\bibnamedelimd}{ }%
  \providecommand{\bibrangedash}{--}%
  \providecommand{\revsdnamepunct}{,}%
  % \current@color 双兜底: xcolor AtBeginDocument 有
  % \let\default@color\current@color 快照 (条目级 \normalcolor
  % 会再 \let\current@color\default@color 回放) —— 此 arm 必须
  % 在快照前 (cls 最先注册 hook, 序天然满足)
  \@ifundefined{current@color}{\global\@namedef{current@color}{gray 0}}{}%
  \@ifundefined{default@color}{\global\@namedef{default@color}{gray 0}}{}%
  \providecommand{\sortlist}[2][]{\par\subsection*{\refname}%
    % biblatex 条目级 \set@color 推栈依赖 \current@color ——
    % color+xcolor 双载偏斜下 hook 期值仍被后 \let 回 undefined,
    % 在 bbl 入口当场兜底 (1706.00221 实测); 灰度 0 = xetex
    % normalcolor 同款值
    \@ifundefined{current@color}{\def\current@color{gray 0}}{}%
    \begingroup\parindent=\z@\parskip=\itemsep
    \def\list##1##2##3{##3 }%
    \def\entry##1##2##3{\par\hangindent=1.5em\hangafter=1\noindent}%
    \def\endentry{}%
    \def\strng##1##2{}%
    \def\name##1##2##3##4{\svj@nwalk##4\svj@nil}%
    \def\field##1##2{\svj@fldemit{##1}{##2}}}%
  % \end* 名被内核 \@ifdefinable 保留 (\newcommand/\providecommand
  % 恒炸 "already defined") —— 经 \@namedef 旁路, 保 provide 语义
  \@ifundefined{endsortlist}{\@namedef{endsortlist}{\par\endgroup}}{}%
}
\endinput
