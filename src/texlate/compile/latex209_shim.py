r"""compile.latex209_shim — compat 垫块字符串叶 (compile.latex209 域缝叶)。

转换产物注入的 TeX 垫块文本：``COMPAT_SHIM`` 通用 209 残留补位、
``_PRE_CLASS_SHIM`` 内核浮体寄存器（``\documentclass`` 之前执行）、
``_MULTICOLS_SHIM`` 剥包环境透传、``REVTEX209_CORE``/``_REVTEX209_SHIM``
revtex4-2 删除面 polyfill（与 fixloop ``_REVTEX209_POLYFILL`` 同义，
共享负载核 ``REVTEX209_CORE`` 单源在本叶）。
"""

from __future__ import annotations

#: 209 内建残留的 compat 块——随转换产物注入，全部幂等/守护式定义。
#: 后半块是 209 时代序言面残留：``\ifnfssone``/``\ifnfsstwo``/
#: ``\ifCUPmtlplainloaded``（mn→mnras 稿序言的 CUP 三闸模板：oldfss 已置
#: false 跳 ``{\rm}`` 支；nfssone/nfsstwo 皆置 false——mnras.cls:214-343
#: 已原生吸收 ``\rmn``/``\mathbfss``/``\upi``/``\leqslant`` 全套模板宏，
#: 任一支进真都会 ``\newcommand`` 撞类定义硬错；CUPmtlplainloaded 由
#: mnras.cls:1707 自携，守护只为无类补给的文稿——astro-ph/9901066 实证）；
#: 旧字体开关 ``\rm``..``\sc``（article.cls:490-496
#: 逐字面——elsarticle/瘦 .cls 壳一条不声明，随源 .sty 体在装载期就消费
#: ``\bf``/``\it``：aipproc.sty:74-84,331-334,1189+,1409+，astro-ph/0104245
#: 实证）；``\cal`` 取 latex209.def:290 本家形（amsart.cls:452 系注释掉的
#: compat-only 残留，math-ph/0408053 实证）；plain/lfonts 字体系
#: ``\tenrm``/``\*mi``（hep-th/9901066 ``\tenrm``、hep-th/9703214
#: ``\skewchar\fivmi`` 全族实证）；``\theorembodyfont``→amsthm
#: ``\thm@bodyfont`` 转寄（math/9901046 ``\theorembodyfont{\sl}`` 实证）；
#: ``\address``/``\collab``/``\abstracts`` 渲染型透传（sprocl/elsart 时代
#: 命令，gr-qc/9901019、hep-ex/9703017、hep-ph/0104302 实证——全在正文位
#: 调用，序言位调用形态无实证不收吞参形）。
COMPAT_SHIM = r"""% texlate: LaTeX 2.09 compatibility shim
\usepackage{latexsym}
\providecommand{\vruleheight}{\vrule height}
\providecommand{\tightenlines}{}
\newif\ifoldfss
\makeatletter
\newif\if@floats
\makeatother
\ifx\footheight\undefined\newlength{\footheight}\fi
% 209 revtex d 列 (decimal) → 兜底为居中列; \newcolumntype 撞已注册列型
% 会报错, 须以 array 内部注册点 \NC@find@<char> 的 \@ifundefined 守护。
% d→c 而非 dcolumn D 列: 胞元含裸 $ 对时 D 列数学包壳翻转出 math 报错。
\makeatletter
\@ifundefined{NC@find@d}{\RequirePackage{array}\newcolumntype{d}{c}}{}
\@ifundefined{ifnfssone}{\newif\ifnfssone}{}
\@ifundefined{ifnfsstwo}{\newif\ifnfsstwo}{}
\@ifundefined{ifCUPmtlplainloaded}{\newif\ifCUPmtlplainloaded}{}
\@ifundefined{rm}{\DeclareOldFontCommand{\rm}{\normalfont\rmfamily}{\mathrm}}{}
\@ifundefined{sf}{\DeclareOldFontCommand{\sf}{\normalfont\sffamily}{\mathsf}}{}
\@ifundefined{tt}{\DeclareOldFontCommand{\tt}{\normalfont\ttfamily}{\mathtt}}{}
\@ifundefined{bf}{\DeclareOldFontCommand{\bf}{\normalfont\bfseries}{\mathbf}}{}
\@ifundefined{it}{\DeclareOldFontCommand{\it}{\normalfont\itshape}{\mathit}}{}
\@ifundefined{sl}{\DeclareOldFontCommand{\sl}{\normalfont\slshape}{\@nomath\sl}}{}
\@ifundefined{sc}{\DeclareOldFontCommand{\sc}{\normalfont\scshape}{\@nomath\sc}}{}
\@ifundefined{cal}{\DeclareSymbolFontAlphabet{\cal}{symbols}}{}
\@ifundefined{tenrm}{\font\tenrm=cmr10}{}
\@ifundefined{fivmi}{\font\fivmi=cmmi5}{}
\@ifundefined{sixmi}{\font\sixmi=cmmi6}{}
\@ifundefined{sevmi}{\font\sevmi=cmmi7}{}
\@ifundefined{egtmi}{\font\egtmi=cmmi8}{}
\@ifundefined{ninmi}{\font\ninmi=cmmi9}{}
\@ifundefined{tenmi}{\font\tenmi=cmmi10}{}
\@ifundefined{elvmi}{\font\elvmi=cmmi10 scaled\magstephalf}{}
\@ifundefined{twlmi}{\font\twlmi=cmmi10 scaled\magstep1}{}
\@ifundefined{frtnmi}{\font\frtnmi=cmmi10 scaled\magstep2}{}
\@ifundefined{svtnmi}{\font\svtnmi=cmmi10 scaled\magstep3}{}
\@ifundefined{twtymi}{\font\twtymi=cmmi10 scaled\magstep4}{}
\@ifundefined{theorembodyfont}{\def\theorembodyfont#1{\@ifundefined{thm@bodyfont}{}{\thm@bodyfont{#1}}}}{}
\@ifundefined{address}{\providecommand{\address}[1]{#1}}{}
\@ifundefined{collab}{\providecommand{\collab}[1]{#1}}{}
\@ifundefined{abstracts}{\providecommand{\abstracts}[1]{#1}}{}
% plain-TeX 移植残留家族——209 稿常整段搬 plain 宏（hep-th/9703214
% \supereject/\hang/\textindent/\centerline×12/\ninepoint/\sevenrm/
% \sevenbf/\tenbf/\pageno/\advancepageno/\makefootline/\leftline/
% \pagebody/\almostshipout 全调用实证；\<x>fam 是 plain \newfam 数学族
% 寄存器，tcilatex/AMS-\text 机 \csname<x>fam\endcsname 动态消费，
% quant-ph/9703040 \bffam/\slfam 50 击实证——随族须给 \textfont 赋值
% 否则 \the\textfont 读空族照样炸）
\@ifundefined{supereject}{\def\supereject{\par\penalty-\@MM}}{}
\@ifundefined{leftline}{\long\def\leftline#1{\hbox to\hsize{#1\hss}}}{}
\@ifundefined{centerline}{\long\def\centerline#1{\hbox to\hsize{\hss#1\hss}}}{}
\@ifundefined{hang}{\def\hang{\hangindent\parindent\hangafter\@ne}}{}
\@ifundefined{textindent}{\def\textindent#1{\indent\llap{#1\enspace}\ignorespaces}}{}
\@ifundefined{footline}{\newtoks\footline}{}
\@ifundefined{makefootline}{\def\makefootline{\baselineskip24pt\hbox to\hsize{\the\footline}}}{}
\@ifundefined{pagebody}{\def\pagebody{\vbox to\vsize{\unvbox\@cclv}}}{}
\@ifundefined{almostshipout}{\def\almostshipout#1{\shipout\vbox{#1}}}{}
\@ifundefined{pageno}{\countdef\pageno=\z@}{}
\@ifundefined{advancepageno}{\def\advancepageno{\ifnum\pageno<\z@\global\advance\pageno\m@ne\else\global\advance\pageno\@ne\fi}}{}
\@ifundefined{ninepoint}{\def\ninepoint{\fontsize{9}{11}\selectfont}}{}
\@ifundefined{fivebf}{\font\fivebf=cmbx5}{}
\@ifundefined{sevenrm}{\font\sevenrm=cmr7}{}
\@ifundefined{sevenbf}{\font\sevenbf=cmbx7}{}
\@ifundefined{tenbf}{\font\tenbf=cmbx10}{}
\@ifundefined{tenit}{\font\tenit=cmti10}{}
\@ifundefined{tensl}{\font\tensl=cmsl10}{}
\@ifundefined{bffam}{\newfam\bffam\textfont\bffam=\tenbf\scriptfont\bffam=\sevenbf\scriptscriptfont\bffam=\fivebf}{}
\@ifundefined{itfam}{\newfam\itfam\textfont\itfam=\tenit}{}
\@ifundefined{slfam}{\newfam\slfam\textfont\slfam=\tensl}{}
% multicol 机寄存器——文稿可自携 ``multicols`` 定义不走剥包路
% （revpre:262-273 自携体裸消费 ``\col@number``，cond-mat/9910148 实证；
% ltxgrid ``\ifnum\col@number>\@ne`` 亦读），故分配件放通用块而非
% ``_MULTICOLS_SHIM`` 的环境闸内。``\multicolsep`` 同理（正文裸赋值，
% rnbc8.tex:314）。
\@ifundefined{col@number}{\newcount\col@number}{}
\@ifundefined{multicolsep}{\newlength{\multicolsep}}{}
\@ifundefined{@kludgeins}{\newinsert\@kludgeins}{}
% 209 类环境代供的草稿寄存器——随源 .sty 裸消费不自分配：prx.sty:49-61
% ``\@makethincaption`` 体 ``\setbox\@testboxa``/``\outertabfalse``/
% ``\@testboxb`` + ``\ifdim\wd\@testboxa``（cond-mat/9910148，每 fcaption
% 6 起 undefined + ``\wd`` 缺数级联实证）；``\outertab`` 是 ``\newif`` 旗。
\@ifundefined{@testboxa}{\newbox\@testboxa}{}
\@ifundefined{@testboxb}{\newbox\@testboxb}{}
\@ifundefined{ifoutertab}{\newif\ifoutertab}{}
\makeatother"""


#: 2.09 内核浮体间距寄存器——latex209.def:167-168 在 compat 入口（类/样式
#: 装载之前）分配；2e 内核不分配，209 时代类体在装载期就裸赋值消费
#: （aipproc.sty:207/213 ``\@maxsep 20pt``/``\@dblmaxsep 20pt``,
#: astro-ph/0104245）。必须在 ``\documentclass`` 之前执行——COMPAT_SHIM 落
#: 在 docclass 行后，类装载缝已过，寄存器来不及定义。
_PRE_CLASS_SHIM = r"""% texlate: LaTeX 2.09 kernel registers (pre-class)
\makeatletter
\@ifundefined{@maxsep}{\newdimen\@maxsep}{}
\@ifundefined{@dblmaxsep}{\newdimen\@dblmaxsep}{}
\makeatother"""


#: ``multicols``/``multicols*`` 透传环境——multicol 被剥后正文 ``\begin{multicols}{n}``
#: 仍需可解析（209 revtex 单栏时代作者常用它裹整个正文凑双栏；revtex4-2 的
#: ltxgrid 已接管分页，列数参弃之）。``\newcount\col@number`` 置 0 中和
#: ltxgrid longtable 分支 ``\ifnum\col@number>\@ne`` 的缺数软错。
#: 分配件（``\col@number``/``\multicolsep``）已上移到 COMPAT_SHIM 通用
#: 块——自携 ``multicols`` 定义的文稿不经剥包路也消费寄存器
#: （cond-mat/9910148 实证），本块只剩环境透传。
_MULTICOLS_SHIM = r"""% texlate: multicol incompatible with target class — env passthrough
\makeatletter
\ifx\multicols\@undefined
\newenvironment{multicols}[1]{}{}
\newenvironment{multicols*}[1]{}{}
\fi
\makeatother"""


#: ``\twocolumn``/``\@makecol``/``\pacs`` 三行共享负载核——本模块
#: ``_REVTEX209_SHIM`` 与 fixloop ``_REVTEX209_POLYFILL``（builtins/shim.py）
#: 的同义 TeX 件单源（fixloop 已同链 import ``wrap_math_cites``/
#: ``upgrade_209``）。两站各自在核前后配自己的包装/守卫行：SHIM 加
#: ``\makeatletter`` 对 + ``frontmatter@init`` 守护臂 + ``\wideabs``/
#: ``\abstract`` 复活钩；POLYFILL 加 ``_AT_LETTER_PRE``/``_AT_LETTER_POST``
#: exact-restore + 裸 ``\frontmatter@init`` 臂——共享负载单源消漂移面。
#: ``\pacs`` 取 ``\long\def``：实参可含空行/``\and``（revpacs 残案——
#: 非 ``\long`` 版撞 "Paragraph ended before \pacs"），代价为零；
#: ``\AtBeginDocument`` 参数内单 ``#1``——hook 逐字存 token（f3f013d2），
#: ``##`` 双写会字面留下炸 "Parameters must be numbered consecutively"。
REVTEX209_CORE = (
    "\\providecommand{\\twocolumn}[1][]{#1}\n"
    "\\@ifundefined{@makecol}"
    "{\\def\\@makecol{\\setbox\\@outputbox\\vbox{\\unvbox\\@cclv}}}{}\n"
    "\\AtBeginDocument{\\long\\def\\pacs#1{\\par\\noindent\\textbf{PACS:} #1\\par}}\n"
)


#: revtex 2.09 文稿面 polyfill——revtex4-2 刻意删掉的 209 面整块补回。
#: 与 fixloop ``_REVTEX209_POLYFILL``（builtins/shim.py）同义 + 三个
#: 实证扩件；共享负载行（``\twocolumn``/``\@makecol``/``\pacs``）单源在
#: ``REVTEX209_CORE`` 随 init 臂后直接展开——``\AtBeginDocument`` 注册的
#: ``\pacs`` 迟延至 ``\begin{document}``，核内行序无语义；partial 稿不进
#: fixloop（``--on fail`` 门），补位只能在这里。
#: - ``\frontmatter@init``：209 稿序言裸调 ``\author``/``\address`` 时
#:   ``\collaboration@sw``（cls:2145 在 init 内出生）未定义连锁炸
#:   ``\@argswap``/``\add@AUCO@grp``（cond-mat/9901276 等 8 格实证）；
#:   执行后自封防 init 重入。
#: - ``\twocolumn``（行体在 ``REVTEX209_CORE``）：cls:4512
#:   ``\let\twocolumn\@undefined``；209 稿用
#:   ``\twocolumn[\hsize\textwidth...]`` 宽头习惯（cond-mat/0501128:218），
#:   ``[1][]{#1}` 吞可选宽头参透传正文。
#: - ``\@makecol``（行体在 ``REVTEX209_CORE``）：cls:3912 同批删；
#:   ltxgrid 接管前兜底原 kernel 形。
#: - ``\wideabs``：revtex 3.1 宽摘要命令（hep-ph/0104029 等 5 格实证）。
#: - ``\abstract``/``\endabstract``：cls:2685 ``\frontmatter@maketitle``
#:   内清理删——``\maketitle`` 之后正文调用位必死（hep-ph/0104029
#:   ``\maketitle``:40→``\input{abstract}``:44、cond-mat/9901276
#:   ``\maketitle``:11→``\begin{abstract}``:13 实证）。双位补：shim 期
#:   ``\@ifundefined`` 兜未武装的前置调用；``\appdef`` 挂
#:   ``\frontmatter@maketitle`` 尾在清理后 ``\gdef`` 复活兜后置调用
#:   （init 先行时 cls:3143 ``\let@environment`` 武装真环境优先）；
#:   双 ``\appdef`` 因 init 路由用 ``\let`` 拷贝宏体——``\maketitle``
#:   持旧副本不吃后挂补丁，直挂调用名本身（cls:2702 hyperref 复位
#:   缝则经 frontmatter@maketitle 那份复得）。
#: - ``\pacs``（行体在 ``REVTEX209_CORE``）：``\AtBeginDocument`` 重定义
#:   压过 cls "must be used before ``\maketitle``" 闸门（多格二次错误
#:   实证）；``\long`` 因实参可含空行。
_REVTEX209_SHIM = (
    "% texlate: revtex 2.09 surface polyfill (revtex4-2 deletes the 209 surface)\n"
    "\\makeatletter\n"
    "\\@ifundefined{frontmatter@init}{}{\\frontmatter@init\\let\\frontmatter@init\\relax}\n"
    + REVTEX209_CORE
    + "\\providecommand{\\wideabs}[1]{#1}\n"
    "\\@ifundefined{abstract}{\\def\\abstract{\\par}}{}\n"
    "\\@ifundefined{endabstract}{\\def\\endabstract{\\par}}{}\n"
    "\\@ifundefined{frontmatter@maketitle}{}{\\appdef\\frontmatter@maketitle{\\@ifundefined{abstract}{\\gdef\\abstract{\\par}}{}\\@ifundefined{endabstract}{\\gdef\\endabstract{\\par}}{}}}\n"
    "\\@ifundefined{maketitle}{}{\\appdef\\maketitle{\\@ifundefined{abstract}{\\gdef\\abstract{\\par}}{}\\@ifundefined{endabstract}{\\gdef\\endabstract{\\par}}{}}}\n"
    "\\makeatother"
)
