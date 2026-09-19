% texlate vendored stub — 原许可禁分发，最小兼容面
% aa.cls 替身：A&A 类（© EDP Sciences，不在 TL，aanda 继任类亦不在）→
% article + A&A 宏面 polyfill。自 shim_map aa.cls 条迁移（0905.4439
% \abstract 五段命令、astro-ph/0307062 旧单参形、2401.17274 natbib
% numbers 宽容侧、1206.0719 期刊缩写满表实证）。
% 本 stub 在场则 shim_map aa.cls 条成死配置（vendored 预检先于 missing_file 落件，
% 同 jinstpub/tcilatex/axodraw 先例）。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{aa}[2026/09/19 texlate stub — original not redistributable]
\ClassWarningNoLine{texlate-stub}{aa.cls is a compatibility shim -> article + A&A polyfills}
% 选项机面补齐 (aafidelity 0905-0919 普查): 真身 aa.cls v6.1-v9.2
% 默认 {a4paper,twoside,twocolumn,fleqn,final,10pt,runningheads}
% —— 原 \LoadClassWithOptions 裸转发, 稿裸 \documentclass{aa}×44
% + []×14 格吃 article 默认 onecolumn/oneside/letterpaper 栏型
% 失真; referee×42 无双距稿面。参照件 bench/corpus_v3/
% {0806.4088,1206.0403,2211.04497,2606.30286}/extracted +
% corpus/1502.01589 五版选项节比对。
% wrapper 机制 (latex.ltx \@process@ptions): cls 级
% ProcessOptions 只查 \@curroptions 不带 \@classoptionslist
% —— 全局选项不会自暨嵌套 \LoadClass, 一切用户选项须显式
% 转发 (尾部 catch-all); 且 article 按声明序执行,
% onecolumn/oneside/leqno 均先于默认侧声明 (article.cls
% :96<:98/:84<:86/:99<:100) → 默认侧若与用户臂同入
% article 选项表必败, 故默认经条件臂注入 (用户臂立 flag
% 抑对应默认)。aa 专名 no-op 吞位消 Unused-option 警告
% (不转 article —— 转了会被 article OptionNotUsed 重新
% 记名); 未声明名经 catch-all 转 article 后仍由其
% OptionNotUsed 记名警告 —— 与真身 bibyear/usenatbibs 等
% 未声明名行为一致。referee 臂 = onecolumn + 双距 (真身
% v7.0 :1334 \baselinestretch{1.5}+\onecolumn);
% \linespread 须 AtBeginDocument 延后 —— article.cls:116
% \renewcommand\baselinestretch{} 会抹掉 \LoadClass 前设置。
\newif\ifaa@onecol \newif\ifaa@oneside \newif\ifaa@leqno
\DeclareOption{onecolumn}{\aa@onecoltrue\PassOptionsToClass{onecolumn}{article}}
\DeclareOption{oneside}{\aa@onesidetrue\PassOptionsToClass{oneside}{article}}
\DeclareOption{leqno}{\aa@leqnotrue\PassOptionsToClass{leqno}{article}}
\DeclareOption{referee}{\aa@onecoltrue\PassOptionsToClass{onecolumn}{article}%
\AtBeginDocument{\linespread{1.5}\normalsize}}
\DeclareOption{showoverfull}{\AtBeginDocument{\setlength\overfullrule{5pt}}}
\DeclareOption{hideoverfull}{}
\DeclareOption{letter}{}\DeclareOption{onlletter}{}
\DeclareOption{online}{}\DeclareOption{contents}{}
\DeclareOption{contentsAut}{}\DeclareOption{rnote}{}
\DeclareOption{longauth}{}\DeclareOption{longfn}{}
\DeclareOption{wideboxfn}{}\DeclareOption{oldversion}{}
\DeclareOption{traditabstract}{}\DeclareOption{structabstract}{}
\DeclareOption{runningheads}{}\DeclareOption{envcountreset}{}
\DeclareOption{envcountsect}{}\DeclareOption{ascii}{}
\DeclareOption{latin1}{}\DeclareOption{latin9}{}
\DeclareOption{ansinews}{}\DeclareOption{applemac}{}
\DeclareOption{utf8}{}\DeclareOption{cm}{}
\DeclareOption{bibauthoryear}{}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\ifaa@onecol\else\PassOptionsToClass{twocolumn}{article}\fi
\ifaa@oneside\else\PassOptionsToClass{twoside}{article}\fi
\ifaa@leqno\else\PassOptionsToClass{fleqn}{article}\fi
\PassOptionsToClass{a4paper}{article}
\LoadClass{article}
% 真身 aa.cls 内置 natbib (\citep/\citeyear 面, 2401.17274 实证)。
% 默认 author-year 对空 \bibitem{} (0905.4439: 45 条无 label
% 无引用的裸书目) 自写 aux 次轮回读炸 "Bibliography not
% compatible with author-year citations"; numbers 模式对
% author-year 形与裸形 bibitem 通吃 → shim 取宽容侧
\RequirePackage[numbers]{natbib}
% thebibliography 内 &→\&: 期稿 \bibitem[.. & ..] 裸 & 惯例
% (0104331 de Thije & Katgert misplaced-& 实证) —— env 组内
% \catcode 激活即收, env 外 tabular 不受影响。
% AtBeginDocument+gdef 外套 —— hook 组内 \let/\def 须 global,
% 且能捕获 natbib \renewenvironment 后的最终 env 版。
% ifincsname 护臂 (1003.0851/1003.4471/astro-ph/0103009 endcsresid 实证):
% cite/bibitem key 内裸 & (Rieke&Lebofsky, ADS bibcode 1990A&A...231...19S)
% 在 env 内读成 active-& → natbib 建 b@<key>\@extra@binfo csname 吞入
% \& (\char"26 chardef 不可展) → Missing \endcsname。\ifincsname 下
% \string& 产 cat12-& 字符, 与 doc 体 cat4-& 同字节 → b@ 名一致;
% 离开 csname 仍 \& 保排版面。
\begingroup\catcode`\&=\active\gdef&{\ifincsname\string&\else\&\fi}\endgroup
\AtBeginDocument{\global\let\aa@thebibliography\thebibliography
\gdef\thebibliography{\catcode`\&=\active\aa@thebibliography}}
% aux 回读臂 (enddocument 与次轮 begindocument 两次 \@input 实证):
% \bibitem 的 \write 把 key 内 active-& 烤成字面 \& → \bibcite{K\&K}
% 回读建 b@ csname 再吞 chardef → 同式 Missing \endcsname 自毒。
% 读侧消洗件 \aa@sanl@bel: key 参内 \&→cat12-& 字符/\protect→∅,
% csname 收裸 & 字节; label/data 参原样过 —— aux 存形 {Rieke \& Lebo}
% 排版面不回归。挂 begindocument/before: kernel \@input{jobname.aux}
% 早于 begindocument hook (latex.ltx 9489<9512), AtBeginDocument 太晚;
% 该点亦保证后载 natbib 的最终 \bibcite 版被捕。
% \@newl@bel 罩 kernel \bibcite/\newlabel r@ 两路; \@testdef 罩
% enddocument 复读 (\let\@newl@bel\@testdef); \NAT@testdef 罩 natbib
% enddocument 复读 (\let\bibcite\NAT@testdef 收回本件包过的版本)。
\begingroup\catcode`\&=12 \gdef\aa@bibamp{&}\endgroup
\def\aa@sanl@bel#1#2{%
\begingroup\let\protect\@empty\let\&\aa@bibamp
\edef\aa@tmp{\endgroup\noexpand#1{#2}}\aa@tmp}
\AddToHook{begindocument/before}{%
\global\let\aa@bibcite\bibcite \gdef\bibcite{\aa@sanl@bel\aa@bibcite}%
\global\let\aa@newl@bel\@newl@bel \gdef\@newl@bel#1{\aa@sanl@bel{\aa@newl@bel#1}}%
\global\let\aa@testdef\@testdef \gdef\@testdef#1{\aa@sanl@bel{\aa@testdef#1}}%
\@ifundefined{NAT@testdef}{}{\global\let\aa@NAT@testdef\NAT@testdef
\gdef\NAT@testdef{\aa@sanl@bel\aa@NAT@testdef}}}
\providecommand{\inst}[1]{\textsuperscript{\,#1}}
\providecommand{\offprints}[1]{}
\providecommand{\mail}[1]{}
\providecommand{\object}[1]{}
\providecommand{\authorrunning}[1]{}
\providecommand{\titlerunning}[1]{}
\providecommand{\subtitle}[1]{}
\providecommand{\keywords}[1]{\par\noindent\textbf{Key words.} #1\par}
% \abstract 新旧两式通吃: 旧 aa.dem 单参形 (内含 \keywords
% 段 —— astro-ph/0307062·0501187·0501259 三格实证) / 新 aanda
% {context}{aims}{methods}{results}{conclusions} 五段形。
% 原 [5] 在旧稿上把紧随的 \par/\maketitle/\section 吞成参数:
% \@sect 组内 \@@par 落进 expl3 hook 名 csname →
% Missing \endcsname ×100 风暴。改单参 + peek 续组并入 —
% 非组 token (\maketitle/\section) 原样回主流。
\providecommand{\abstract}{}
\renewcommand{\abstract}[1]{\begin{quotation}\noindent\textbf{Abstract.} #1\aa@absorb}
\ExplSyntaxOn
\cs_new_protected:Npn \aa@absorb {
  \peek_catcode_ignore_spaces:NTF \c_group_begin_token
    { \aa@absorbgo } { \end{quotation} } }
\cs_new_protected:Npn \aa@absorbgo #1 { \par #1 \aa@absorb }
\ExplSyntaxOff
% \institute 收地址块 (内含 \and) —— \maketitle 后兜底输出防丢内容
\def\aa@institute{}
\providecommand{\institute}[1]{\gdef\aa@institute{#1}}
\let\aa@maketitle\maketitle
\renewcommand{\maketitle}{\aa@maketitle\par\begingroup\ifx\aa@institute\@empty\else{\footnotesize\let\and\\\aa@institute\par}\fi\endgroup}
% 天文记号 (\la/\ga 用 \leq/\geq 近似 —— 不引 amssymb 依赖)
\providecommand{\ion}[2]{#1~#2}
\providecommand{\sun}{\ensuremath{\odot}}
\providecommand{\degr}{\ensuremath{{}^\circ}}
\providecommand{\arcmin}{\ensuremath{'}}
\providecommand{\arcsec}{\ensuremath{''}}
\providecommand{\la}{\ensuremath{\leq}}
\providecommand{\ga}{\ensuremath{\geq}}
% 批八 (loop1 残盘实证): aa-shim 格 \email(2格)/\acknowledgements
% (4格, env+cs 两形均见)/\thesaurus 仍 undefined_cs —— 真身 aa.cls
% 作者面补位 (acknowledgements 作无号小节头, thesaurus 吞码表)
\providecommand{\email}[1]{\texttt{#1}}
\providecommand{\acknowledgements}{\par\medskip\noindent\textbf{Acknowledgements.}\space}
\providecommand{\thesaurus}[1]{}
% C-bucket 残盘 (aa_cls_surface 3 格): \sidecaption 版式指示
% cs (figure* 内裸调, 1003.4471 实证) → noop; \fm/\fs/\fd/
% \fh/\fdg/\farcm/\farcs/\fp 角分角秒族 (0501259 实测
% \farcm×6/\farcs×59) —— apjprepr 同款抄值; 期刊缩写全表
% (\apj/\mnras/\aap 系 bibitem 内高频, 1206.0719 满表命中)。
\providecommand{\sidecaption}{}
\providecommand{\fd}{\hbox{$.\!\!^{\rm d}$}}
\providecommand{\fh}{\hbox{$.\!\!^{\rm h}$}}
\providecommand{\fm}{\hbox{$.\!\!^{\rm m}$}}
\providecommand{\fs}{\hbox{$.\!\!^{\rm s}$}}
\providecommand{\fdg}{\hbox{$.\!\!^\circ$}}
\providecommand{\farcm}{\hbox{$.\mkern-4mu^\prime$}}
\providecommand{\farcs}{\hbox{$.\!\!^{\prime\prime}$}}
\providecommand{\fp}{\hbox{$.\!\!^{\scriptscriptstyle\rm p}$}}
\providecommand{\aj}{AJ}
\providecommand{\araa}{ARA\&A}
\providecommand{\apj}{ApJ}
\providecommand{\apjl}{ApJ}
\providecommand{\apjs}{ApJS}
\providecommand{\ao}{Appl.~Opt.}
\providecommand{\apss}{Ap\&SS}
\providecommand{\aap}{A\&A}
\providecommand{\aapr}{A\&A~Rev.}
\providecommand{\aaps}{A\&AS}
\providecommand{\azh}{AZh}
\providecommand{\baas}{BAAS}
\providecommand{\jrasc}{JRASC}
\providecommand{\memras}{MmRAS}
\providecommand{\mnras}{MNRAS}
\providecommand{\pra}{Phys.~Rev.~A}
\providecommand{\prb}{Phys.~Rev.~B}
\providecommand{\prc}{Phys.~Rev.~C}
\providecommand{\prd}{Phys.~Rev.~D}
\providecommand{\pre}{Phys.~Rev.~E}
\providecommand{\prl}{Phys.~Rev.~Lett.}
\providecommand{\pasp}{PASP}
\providecommand{\pasj}{PASJ}
\providecommand{\qjras}{QJRAS}
\providecommand{\skytel}{S\&T}
\providecommand{\solphys}{Sol.~Phys.}
\providecommand{\sovast}{Soviet~Ast.}
\providecommand{\ssr}{Space~Sci.~Rev.}
\providecommand{\zap}{ZAp}
\providecommand{\nat}{Nature}
\providecommand{\iaucirc}{IAU~Circ.}
\providecommand{\aplett}{Astrophys.~Lett.}
\providecommand{\apspr}{Astrophys.~Space~Phys.~Res.}
\providecommand{\bain}{Bull.~Astron.~Inst.~Netherlands}
\providecommand{\fcp}{Fund.~Cosmic~Phys.}
\providecommand{\gca}{Geochim.~Cosmochim.~Acta}
\providecommand{\grl}{Geophys.~Res.~Lett.}
\providecommand{\jcp}{J.~Chem.~Phys.}
\providecommand{\jgr}{J.~Geophys.~Res.}
\providecommand{\jqsrt}{J.~Quant.~Spec.~Radiat.~Transf.}
\providecommand{\memsai}{Mem.~Soc.~Astron.~Italiana}
\providecommand{\nphysa}{Nucl.~Phys.~A}
\providecommand{\physrep}{Phys.~Rep.}
\providecommand{\physscr}{Phys.~Scr}
\providecommand{\planss}{Planet.~Space~Sci.}
\providecommand{\procspie}{Proc.~SPIE}
\providecommand{\astap}{A\&A}
\providecommand{\apjlett}{ApJ}
\providecommand{\apjsupp}{ApJS}
\providecommand{\applopt}{Appl.~Opt.}
\endinput
