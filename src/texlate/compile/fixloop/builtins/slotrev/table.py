r"""builtins.slotrev.table — 扩展机位表 ``_SLOTREV_EXTRA_RXS`` (slotrev 拆分)。

judge ``_MACHINE_SLOT_RXS`` 不盖的机位头族, 逐 ``(kind, rx)``; rx 捕获
组全为机位实参候选, 同一文件 src/zh 双侧命中数必须相等否则整 kind 跳。
不改 judge 表: verdict 面 (``paired_slot_diff``/``machine_slot_audit``)
行为字节级不变。词法件单源在 ``slotrev.lex``。
"""

from __future__ import annotations

import re

from texlate.compile.fixloop.builtins.slotrev.lex import (
    _ARG,
    _ARGB,
    _ARGNL,
    _BGM,
    _GAP,
    _OPT,
    _OPTB,
    _OPTC,
)
from texlate.textutil import CMD_BOUNDARY

__all__ = [
    "CMD_BOUNDARY",
    "_SLOTREV_EXTRA_RXS",
    "re",
]

#: 扩展机位表 —— judge ``_MACHINE_SLOT_RXS`` 不盖的机位头族，逐
#: ``(kind, rx)``; rx 捕获组全为机位实参候选，同一文件 src/zh 双侧
#: 命中数必须相等否则整 kind 跳。不改 judge 表：verdict 面
#: (``paired_slot_diff``/``machine_slot_audit``) 行为字节级不变。
_SLOTREV_EXTRA_RXS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # \begin{env}[opt]{mand}×≤4 —— 未注册 env 尾随机参
    # (translatedabstract{french}/Mizar{x,Y,A} 实证锚点); opt 位与
    # 尾随 mand 参全收。末臂 ``|_OPTC`` 收 opt-only 站
    # (\begin{tikzpicture}[kv] 类)。mand 参用 ``_ARGNL`` 跨行容忍 —
    # 参内字面换行合法 (2609.19556 ``{General\ninstructions}``: src
    # 站捕不进 → envarg 26≠28 整跳，7 站 zh 参全漏)。
    (
        "envarg",
        re.compile(
            r"\\begin\s*\{[^{}\n]*\}"
            + _GAP
            + r"(?:(?:"
            + _OPTC
            + _GAP
            + r")?"
            + _ARGNL
            + r"(?:"
            + _GAP
            + _ARGNL
            + r")?"
            + r"(?:"
            + _GAP
            + _ARGNL
            + r")?"
            + r"(?:"
            + _GAP
            + _ARGNL
            + r")?"
            + r"|"
            + _OPTC
            + r")"
        ),
    ),
    # \color/\textcolor/\pagecolor/\rowcolor [model]?{name}
    (
        "color",
        re.compile(
            r"\\(?:color|textcolor|pagecolor|rowcolor)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # \colorbox[model]?{color}{text} —— 参 0 (text 是散文不碰)
    (
        "colorbox",
        re.compile(r"\\colorbox" + CMD_BOUNDARY + r"\s*(?:" + _OPT + r"\s*)?" + _ARG),
    ),
    # \fcolorbox[model]?{frame}{bg}{text} —— 前两色参
    (
        "fcolorbox",
        re.compile(
            r"\\fcolorbox"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \definecolor/\providecolor/\xdefinecolor/\preparecolor ——
    # {name}{model}{spec} 三参全机位
    (
        "defcolor",
        re.compile(
            r"\\(?:definecolor|providecolor|xdefinecolor|preparecolor)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \colorlet[model]?{new}{expr} —— 两参
    (
        "colorlet",
        re.compile(
            r"\\colorlet"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # 计数器名参 0: \setcounter/\addtocounter/\refstepcounter/\stepcounter/
    # \value/\arabic/\roman/\Roman/\alph/\Alph/\fnsymbol/\usecounter
    (
        "counter",
        re.compile(
            r"\\(?:setcounter|addtocounter|refstepcounter|stepcounter|value|"
            r"arabic|roman|Roman|alph|Alph|fnsymbol|usecounter)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
        ),
    ),
    # \newcounter{name}[within] —— within 也是计数名
    (
        "newcounter",
        re.compile(
            r"\\newcounter" + CMD_BOUNDARY + r"\s*" + _ARG + r"(?:\s*" + _OPTC + r")?"
        ),
    ),
    # \counterwithin/\counterwithout/\numberwithin/\numberwithout {x}{y}
    (
        "counterw",
        re.compile(
            r"\\(?:counterwithin|counterwithout|numberwithin|numberwithout)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # etoolbox \newtoggle/\providetoggle/\toggletrue/\togglefalse —— 名参
    (
        "toggle",
        re.compile(
            r"\\(?:newtoggle|providetoggle|toggletrue|togglefalse)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
        ),
    ),
    # \iftoggle{name}{t}{f} —— 参 0 (分支是散文不碰)
    (
        "iftoggle",
        re.compile(r"\\iftoggle" + CMD_BOUNDARY + r"\s*" + _ARG),
    ),
    # \setkeys/\kvsetkeys [opt]?{fam}{list} —— fam 参 0 (list 太宽不收)
    (
        "setkeys",
        re.compile(
            r"\\(?:setkeys|kvsetkeys)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # kv 头族 [opt]?{kv-list}: opt 与整 kv 参都按原子 revert (kv 串
    # 逗号等号在 ident 白名单内; 含散文值 ⇒ 空格破 ident 自动不碰)
    (
        "kv",
        re.compile(
            r"\\(?:hypersetup|pgfkeys|pgfqkeys|psset|tikzset|forestset|"
            r"tcbset|lstset|sisetup|ctexset|xeCJKsetup|setlist|"
            r"captionsetup|subcaptionsetup|geometry|newgeometry|"
            r"ExecuteOptions|ProcessOptions|ProcessOptionsX|"
            r"ExecuteBibliographyOptions|DeclareKeys|SetKeys)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPTC
            + r"\s*)?"
            + _ARG
        ),
    ),
    # expl3 \keys_set:nn/\keys_define:nn {module}{kv} —— 双机位参
    (
        "expl3kv",
        re.compile(
            r"\\(?:keys_set:nn|keys_define:nn|keys_precompile:nnN?)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # mathpartir/bussproofs \inferrule/\infer [*] [kv-opt] —— opt 位整
    # kv 串即机位 (left/right/lab/vfraction 键表; 值可含 cs 调用
    # ``left = \rlabel{Rec}`` 与空格 → spec 同域可打印 ASCII, 严格
    # ident 拒)。kv 行不盖：premise/conclusion mand 参多层花括号跨行
    # ``_ARG`` 吃不进致 opt 亦漏捕; 故 opt-only 行独立于 kv 表。
    # 1708.07366 ``\inferrule*[这是译文 = \rlabel{Rec}]`` 实证锚点。
    (
        "inferkv",
        re.compile(r"\\infer(?:rule)?" + CMD_BOUNDARY + r"\*?\s*" + _OPTC),
    ),
    # \footnote/\footnotemark/\footnotetext [n] —— opt 标号机参
    # (mand 参是散文不碰)
    (
        "footopt",
        re.compile(
            r"\\(?:footnote|footnotemark|footnotetext)" + CMD_BOUNDARY + r"\s*" + _OPTC
        ),
    ),
    # \usepackage/\RequirePackage*/\documentclass/\documentstyle/
    # \LoadClass* [opt]?{name} —— opt+ 名两参 (还原实名供 static_precheck
    # 装包扫描收)
    (
        "pkg",
        re.compile(
            r"\\(?:usepackage|RequirePackage|RequirePackageWithOptions|"
            r"documentclass|documentstyle|LoadClass|LoadClassWithOptions)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPTC
            + r"\s*)?"
            + _ARG
        ),
    ),
    # \PassOptionsToPackage/\PassOptionsToClass {opts}{pkg}
    (
        "passopt",
        re.compile(
            r"\\PassOptionsTo(?:Package|Class)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \newenvironment/\renewenvironment/\provideenvironment/\newtheorem/
    # \newcolumntype/\NewEnviron/\RenewEnviron/\DeclareFloatingEnvironment
    # —— 声明名参 0 (后随 [n]/{before}/{after}/{Text} 散文位不碰)
    (
        "envdecl",
        re.compile(
            r"\\(?:newenvironment|renewenvironment|provideenvironment|"
            r"newtheorem|newcolumntype|NewEnviron|RenewEnviron|"
            r"DeclareFloatingEnvironment)" + CMD_BOUNDARY + r"\*?\s*" + _ARG
        ),
    ),
    # \newglossaryentry/\newacronym/\lstdefinelanguage —— 键/名参 0
    (
        "decl",
        re.compile(
            r"\\(?:newglossaryentry|newacronym|lstdefinelanguage)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # babel/polyglossia 语言名：\selectlanguage/\setdefaultlanguage/
    # \setmainlanguage/\setotherlanguage/\setotherlanguages/
    # \foreignlanguage [opt]?{lang} —— foreignlanguage 参 1 散文不碰
    (
        "lang",
        re.compile(
            r"\\(?:selectlanguage|setdefaultlanguage|setmainlanguage|"
            r"setotherlanguage|setotherlanguages|foreignlanguage)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPTC
            + r"\s*)?"
            + _ARG
        ),
    ),
    # fontspec 族 —— 字体名参 (loose ident 许空格/'/()/&);
    # \newfontfamily\cs{Font} 间置 \cs 经 (?:\\[a-zA-Z@]+\s*)? 收
    (
        "font",
        re.compile(
            r"\\(?:setmainfont|setsansfont|setmonofont|setmathrm|"
            r"setmathsf|setmathtt|setboldmathrm|setoperatorfont|"
            r"setCJKmainfont|setCJKsansfont|setCJKmonofont|fontspec|"
            r"newfontfamily|newfontface|defaultfontfeatures|"
            r"addfontfeatures|addfontfeature)"
            + CMD_BOUNDARY
            + r"\s*(?:\\[a-zA-Z@]+\s*)?(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # \bibliographystyle{style}
    (
        "bibstyle",
        re.compile(r"\\bibliographystyle" + CMD_BOUNDARY + r"\s*" + _ARG),
    ),
    # \usetikzlibrary/\usepgflibrary/\usepgfganttlibrary/\usepgfplotslibrary
    (
        "libs",
        re.compile(
            r"\\use(?:tikzlibrary|pgflibrary|pgfganttlibrary|pgfplotslibrary)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
        ),
    ),
    # 单参机名族：\pagenumbering/\pagestyle/\thispagestyle/\theoremstyle/
    # \mathversion/\citestyle + beamer \use*theme 族
    (
        "name",
        re.compile(
            r"\\(?:pagenumbering|pagestyle|thispagestyle|theoremstyle|"
            r"mathversion|citestyle|usetheme|usecolortheme|usefonttheme|"
            r"useoutertheme|useinnertheme)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # 文件路径单参族：\InputIfFileExists/\IfFileExists/\ProvidesFile/
    # \ProvidesPackage/\ProvidesClass/\ProvidesExplPackage/
    # \lstinputlisting/\verbatiminput/\VerbatimInput/\includeverbatim/
    # \includepdf/\includesvg/\includeonly/\includestandalone/
    # \externaldocument/\tikzsetnextfilename/\nobibliography
    (
        "filearg",
        re.compile(
            r"\\(?:InputIfFileExists|IfFileExists|ProvidesFile|"
            r"ProvidesPackage|ProvidesClass|ProvidesExplPackage|"
            r"lstinputlisting|verbatiminput|VerbatimInput|includeverbatim|"
            r"includepdf|includesvg|includeonly|includestandalone|"
            r"externaldocument|tikzsetnextfilename|nobibliography)"
            + CMD_BOUNDARY
            + r"\*?\s*"
            + _ARG
        ),
    ),
    # \import/\subimport/\includefrom/\subincludefrom/\inputminted {dir}{file}
    (
        "import",
        re.compile(
            r"\\(?:import|subimport|includefrom|subincludefrom|inputminted)"
            + CMD_BOUNDARY
            + r"\*?\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \addcontentsline/\addtocontents {toc}{level/entry} —— 前两机位参
    # (tocline 文本参不碰)
    (
        "tocline",
        re.compile(
            r"\\(?:addcontentsline|addtocontents)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
            + r"\s*"
            + _ARG
        ),
    ),
    # \url/\href/\nolinkurl/\email/\doi/\orcidlink 参 0 (href 参 1 散文不碰)
    (
        "url",
        re.compile(
            r"\\(?:url|href|nolinkurl|email|doi|orcidlink)"
            + CMD_BOUNDARY
            + r"\s*"
            + _ARG
        ),
    ),
    # \hyperref[label]{text} —— opt label (text 散文不碰)
    (
        "hyperref",
        re.compile(r"\\hyperref" + CMD_BOUNDARY + r"\s*" + _OPTC),
    ),
    # 交叉引用扩展族 (judge ref 行只盖 label/ref/eqref/pageref/autoref):
    # \cref/\Cref/\crefrange/\cpageref/\vref/\vpageref/\nameref/\refeq/
    # \subref/\itemref/\footref/\thmref —— 键参 0
    (
        "refx",
        re.compile(
            r"\\(?:cref|Cref|crefrange|Crefrange|cpageref|vref|vpageref|"
            r"nameref|refeq|subref|itemref|footref|thmref)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPT
            + r"\s*)*"
            + _ARG
        ),
    ),
    # glossaries/acronym 引用族 —— 键参 0 (\glssee 参 1 也是键表但随行)
    (
        "gls",
        re.compile(
            r"\\(?:ac|acs|acf|acl|acp|acrfull|acrshort|acrlong|acrshortpl|"
            r"acrlongpl|acrfullpl|gls|glspl|Gls|Glspl|glslink|glsdisp|"
            r"glssee|glsadd|glsdesc|glsxtrshort|glsxtrlong|glsxtrfull)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPT
            + r"\s*)*"
            + _ARG
        ),
    ),
    # minted \mintinline/\mint/\newmintinline/\newmint {lang} —— 语言名参
    (
        "mint",
        re.compile(
            r"\\(?:mintinline|mint|newmintinline|newmint)"
            + CMD_BOUNDARY
            + r"\*?\s*(?:"
            + _OPT
            + r"\s*)?"
            + _ARG
        ),
    ),
    # \newfloat{name}{placement}{ext} (float 包) —— 三参全机位
    (
        "newfloat",
        re.compile(
            r"\\newfloat" + CMD_BOUNDARY + r"\s*" + _ARG + r"\s*" + _ARG + r"\s*" + _ARG
        ),
    ),
    # ── 2026-09-19 arrayresid 车道：列 spec 机位 ──
    # envarg 同位收 spec 参但严格 ident 拒收真实 spec (|/空格/\@/</>/!/*
    # 全不在白名单; \textwidth 含反斜杠同理) —— 1502.01845 ``\betb``
    # 实证外，env-arg 位 zh 化 spec 是本族结构性盲区。spec-env 的参位
    # 即机位断言 (该位恒为机参，内核拒 CJK → 参含 CJK 必为译污),
    # ident 放宽到可打印 ASCII+ 空白 (``_IDENT_SPEC_RX``)。
    # ``\begin{tabular}`` 系首参 spec; tabularx/tabulary/xltabular/
    # NiceTabularX 系 ``{dimen}{spec}`` 双参全机位 (dimen 被译同样炸)。
    # 2026-09-20 zhleakimpl: spec 参 ``_ARG``→``_ARGB`` —— ``>{...}``/
    # ``!{...}`` 嵌组与跨行 spec (2609.20179 xltabular 多行 ``>{...}
    # p{0.13\textwidth}...X`` 实证) ``_ARG`` 结构上捕不进，本族第二
    # 盲区; env 表同步补：xtabular 回单参臂 (xtab.sty
    # ``\@supertabular[#1]#2`` 实测单 mand 参，原双参臂名单位置错)、
    # tabu/longtabu (``to``/``spread`` 形天然不匹配，裸 ``{spec}``
    # 形同盖)、tabularray ``tblr/longtblr/talltblr/booktabs/
    # longtabs/talltabs`` (``O{} m`` 签名)、nicematrix ``NiceArray``
    # 系/``NiceTabular`` (``O{} m``; ``NiceMatrix`` 系签名 ``!O{}``
    # 无显式 spec 参位，``{...}`` 可能为首格散文 → 不收，错位
    # revert 比不复原更糟)。
    (
        "colspec",
        re.compile(
            r"\\begin\s*\{(?:tabular|array|deluxetable|smalldeluxetable|"
            r"sidewaysdeluxetable|sidewaystable|supertabular|mpsupertabular|"
            r"longtable|xtabular|tabu|longtabu|tblr|longtblr|talltblr|"
            r"booktabs|longtabs|talltabs|NiceTabular|NiceArray|"
            r"pNiceArray|bNiceArray|BNiceArray|vNiceArray|VNiceArray)\*?\}"
            + _GAP
            + r"(?:"
            + _OPT
            + _GAP
            + r")?"
            + _ARGB
        ),
    ),
    (
        "colspec",
        re.compile(
            r"\\begin\s*\{(?:tabularx|tabulary|xltabular|tabular\*|array\*|"
            r"NiceTabularX|NiceTabular\*)\}"
            + _GAP
            + r"(?:"
            + _OPT
            + _GAP
            + r")?"
            + _ARG
            + _GAP
            + r"(?:"
            + _OPT
            + _GAP
            + r")?"
            + _ARGB
        ),
    ),
    # \multicolumn{n}{spec}{text} —— n+spec 双机位 (text 散文不碰);
    # spec 位 ``>{...}``/``!{...}`` 嵌组同盲区，``_ARGB`` 收。
    (
        "colspec_mc",
        re.compile(r"\\multicolumn\*?" + CMD_BOUNDARY + r"\s*" + _ARG + r"\s*" + _ARGB),
    ),
    # \newcolumntype{name}[n]{spec} —— spec 参 (name 参 envdecl 已盖;
    # spec 内 ``>{...}``/``#n`` 嵌组 ``_ARGB`` 收)。
    (
        "colspec_nt",
        re.compile(
            r"\\newcolumntype\*?"
            + CMD_BOUNDARY
            + r"\s*"
            + r"\{[^{}\n]*\}\s*(?:\[[^\]\n]*\]\s*)?"
            + _ARGB
        ),
    ),
    # ── 2026-09-20 primgap: 原语 cs 与 ``{``-组之间 gap 机位 ──
    # 捕获面与全表其他 kind 正交 —— 既有行捕获组全在 ``{}``/``[]``/
    # ``\csname`` 体内，此 kind 收 ``\vadjust 这是译文{\vskip 1pt}``
    # (2609.19815) / ``\leaders\hbox 这是译文{...}`` (2609.20633 ×12)
    # 形：译面把原语 keyword/dimen 尾巴 (``pre``/``to .55em``/
    # ``spread 2pt``/``16``/``12``) 落上 chunk → 写在 cs 与 ``{``
    # 之间 (slotleak 车道裁决)。域 = 必需下接 ``{`` 的
    # 原语族; gap 域 spec ident (可打印 ASCII, 含空格/反斜杠)。
    # ``\leaders\hbox to .55em{`` 复合站 finditer 不重叠 → 单命中，
    # gap 值即 ``\hbox to .55em`` 整串。空 gap (``\hbox{``) 双侧
    # 同形无害; zh 侧宏展开倍增调用站致计数分歧 → unique-src 广播
    # (``_BROADCAST_KINDS``)。
    (
        "primgap",
        re.compile(
            r"\\(?:hbox|vbox|vtop|vadjust|insert|noalign|leaders|cleaders|"
            r"xleaders|marks|mark|uppercase|lowercase|message|errmessage|"
            r"write|special|output|everypar|everymath|everydisplay|"
            r"everyhbox|everyvbox|everyjob|everycr|everyeof|toks)"
            + CMD_BOUNDARY
            + r"\s*([^{}\n]*?)\{"
        ),
    ),
    # ── 2026-09-20 slotfix: tcb 族 kv 选项组机位 ──
    # ``\begin{tcblisting}{enhanced,\n breakable,\n listing options={...}}``
    # 形 (2609.20423 实证：跨行 + 嵌套 ``{}`` 选项组整组 zh 化 →
    # ``/tcb/这是译文`` pgfkeys 错) —— ``_ARG`` 吃不进换行与嵌组，
    # 严格/宽松 ident 均拒带空白 kv → 独立 kind: ``_ARGB``/``_OPTB``
    # 平衡组捕获 (≤2/≤1 层嵌套，空行截断) + kvnl ident (可打印
    # ASCII+``\t\n\r``, 且须含 ``=``/``,``/``#`` kv 形 —— 防
    # ``\begin{tcolorbox}`` 后散文 ``{multi\nline prose}`` 误收)。
    # ``{}``/``[]`` 双头形同盖 (tcblisting ``{opts}`` 必填形，tcolorbox
    # ``[opts]`` 常形); envarg 对单行平参同位重扫 → 同位改写去重无害。
    (
        "tcbopt",
        re.compile(
            r"\\begin\s*\{(?:tcolorbox|tcblisting|tcbox|tcbposter|tcbraster|"
            r"tcboxedraster|tcbitemize|tcbverbatimwrite|tcboxed)\*?\}"
            + _GAP
            + r"(?:"
            + _ARGB
            + r"|"
            + _OPTB
            + r")"
        ),
    ),
    # ``\newtcblisting``/``\newtcolorbox``/``\newtcbox`` (new/renew/
    # provide + xparse ``\NewTCBListing``/``\NewTCBox``/``\NewTColorBox``
    # 系) def 尾选项组 —— ``{name}[n]{opts}``/``{name}{spec}{opts}``
    # 的末组即 kv 机位 (``#n`` 形参位同域，2609.19556
    # ``\newtcblisting{promptbox}[2]{...#1...#2}`` 实证锚点); 名参与
    # 中置 ``[n]``/``[default]``/``{spec}`` 组只吃不捕。
    (
        "tcbopt",
        re.compile(
            r"\\(?:(?:new|renew|provide)(?:tcblisting|tcolorbox|tcbox)|"
            r"(?:New|Renew|Provide|Declare)(?:TCBListing|TColorBox|TCBox))"
            + CMD_BOUNDARY
            + r"\s*(?:\[[^\]\n]*\]\s*)?"
            + r"\{[^{}\n]*\}"
            + r"(?:\s*(?:\[[^\]\n]*\]|"
            + _BGM
            + r"))*"
            + r"\s*"
            + _ARGB
        ),
    ),
    # ── 2026-09-20 zhleakimpl: pgfplots 数据表机位 ──
    # ``\pgfplotstableread{内联数值表}\cs`` 整参 zh 化 (2609.19828 实证：
    # 头行 ``gpus cells dofs ...`` ×9 + ``7.045e-03`` 的 ``e`` →
    # ``这是译文``, 下游 pgfplots "too many columns" → 100-error
    # abort)。数据参位恒为机位 (内联表/csname/文件名/kv 皆机器引用 →
    # 含 CJK 必译污): ``_ARGB`` 平衡组收跨行数据 + spec 域 ident —
    # 纯数值表无 ``=``,``/``#``, kvnl 形断言会拒收，故不加 kv 门控
    # (勿并入 ``_IDENT_KVNL_KINDS``)。``[]`` 头 (``[col sep=...]``)
    # 同机位 ``_OPTB`` 捕。
    (
        "pgtable",
        re.compile(
            r"\\(?:pgfplotstableread|pgfplotstablecreate|"
            r"pgfplotstabletypeset|pgfplotstablecopy|"
            r"pgfplotstabletranspose|pgfplotstablevertcat|"
            r"pgfplotstablesave|pgfplotstableset|"
            r"pgfplotsinvokeforeach)"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPTB
            + r"\s*)?"
            + _ARGB
        ),
    ),
    # ``\addplot[opts] table[opts]{data}`` 系 —— 数据源 keyword
    # (table/file/coordinates/expression/function/gnuplot/shell/
    # graphics) 可缺省：pgfplots 语法上 ``\addplot`` 后 ``{...}``
    # 只能是数据/表达式 plot spec (非散文位), 裸 ``{expr}`` 同盖
    # (2609.19828 roofline ``\addplot[opt]{3.6*x}`` 实证); keyword
    # 门控仍防 ``\addplot[opt] 散文{...}`` 误收。``\addplot3``/
    # ``\addplot+`` 变体同收; tikz ``\draw plot table`` 的 ``plot``
    # 是裸词非 cs, 结构上不盖。
    (
        "pgtable",
        re.compile(
            r"\\addplot3?\+?"
            + CMD_BOUNDARY
            + r"\s*(?:"
            + _OPTB
            + r"\s*)?"
            + r"(?:(?:table|file|coordinates|expression|function|"
            r"gnuplot|shell|graphics)\s*(?:" + _OPTB + r"\s*)?)?" + _ARGB
        ),
    ),
)
