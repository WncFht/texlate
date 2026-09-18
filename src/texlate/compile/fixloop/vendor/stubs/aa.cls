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
\LoadClassWithOptions{article}
% 真身 aa.cls 内置 natbib (\citep/\citeyear 面, 2401.17274 实证)。
% 默认 author-year 对空 \bibitem{} (0905.4439: 45 条无 label
% 无引用的裸书目) 自写 aux 次轮回读炸 "Bibliography not
% compatible with author-year citations"; numbers 模式对
% author-year 形与裸形 bibitem 通吃 → shim 取宽容侧
\RequirePackage[numbers]{natbib}
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
