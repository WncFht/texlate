r"""_builtins_slotrev — zh 机位实参 revert (slotrevert lane, task#188)。

机制 (tmp/lane-zhleak/notes.md): segmenter 把未注册机位实参 (csname 体 /
未注册 env 尾随参等) 放上 chunk 翻译字面量面 → zh 化后 splice 写回
机位 → ``Undefined color '这是译文'``/``No counter``/``can't find file``
族。本叶做决定性 revert: ``judge.py`` ``_MACHINE_SLOT_RXS`` + 本叶扩展
表在 ``mask_tex`` 等长遮盖视图 (``_DEAD_TAIL_RX`` 死尾截断同口径) 上
定位机位实参, 对 ``params.baseline_dir`` pristine 树逐文件做 per-kind
序号对齐配对 —— baseline 参纯 ASCII 标识符 ∧ zh 参含 CJK ∧ 两侧
相异 → zh 参位字节换回 baseline 参。``\section{标题}`` 等文位结构上
不在机位表内永不被碰; 某 kind 双侧命中数分歧 → 该 kind 整跳防错位
回写 (LLM 臆造/丢参时错位 revert 比不复原更糟), 唯 ``primgap`` kind
(原语 cs 与 ``{``-组之间 gap —— ``\vadjust 这是译文{``/``\leaders\hbox
这是译文{`` 面) 分歧时先判 unique-src 广播: src 全 gap 值唯一 ∧ 过
ident → 写进 zh 全部 CJK gap 站 (宏展开把 def 站机位倍增到调用站);
``baseline_dir`` 缺席/非目录 → False 空转 (standalone precheck 挂点
不注入 baseline)。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.textutil import CITE_FAMILY_RE, CJK_RX, CMD_BOUNDARY, mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

#: ``compile.probe._DEAD_TAIL_RE``/``judge._DEAD_TAIL_RX`` 同口径死尾截断:
#: ``\end{document}``/``\endinput`` 之后同形 token 非活 slot。
_DEAD_TAIL_RX = re.compile(r"\\end\s*\{document\}|\\endinput\b")

#: 同命令相邻实参间空白 (跨行随意); 仅 envarg 尾随参用受限 _GAP。
_ARG = r"\{([^{}\n]*)\}"
_OPT = r"\[[^\]\n]*\]"  # opt 位只吃不捕 (非 revert 面)
_OPTC = r"\[([^\]\n]*)\]"  # opt 位捕获 (revert 面: 计数/包选项/label)
#: envarg 尾随参 gap: 同行空白 + 至多一个换行 —— 空行=\par 截断 arg
#: 扫描 (TeX 无 \long 参扫描语义), 防 ``\begin{env}`` 后散文 ``{word}``
#: 误收。
_GAP = r"[^\S\n]*(?:\n[^\S\n]*)?"
#: 平衡组扫描单元 —— 非 ``{}`` 字符且非空行首 ``\n``: 空行=\par 截断 arg
#: 扫描 (同 _GAP 口径), 单 ``\n`` 是合法 arg token (2609.19556
#: ``{General\ninstructions}`` 实证: src 参带字面换行 ``_ARG`` 捕不进 →
#: 计数分歧整 kind 跳)。``\r`` 入空白列护 CRLF 空行判。
_NBC = r"(?:(?!\n[ \t\r]*\n)[^{}])"
#: 换行容忍实参 —— envarg 尾随参跨行组; 嵌套 ``{}`` 仍不收 (由 _ARGB 面盖)。
_ARGNL = r"\{(" + _NBC + r"*)\}"
#: 平衡组体 (非捕获, ≤1 层嵌套) —— 中置参/组内嵌套单元。
_BGM = r"\{(?:" + _NBC + r"|\{" + _NBC + r"*\})*\}"
#: 平衡组实参 (捕获, ≤2 层嵌套 + 跨行) —— tcb kv 选项组
#: (``listing options={...}`` 值自带 ``{}`` 组)。
_ARGB = r"\{((?:" + _NBC + r"|" + _BGM + r")*)\}"
#: 平衡方括 opt 实参 (捕获, ≤1 层嵌套 + 跨行) —— tcolorbox ``[kv]`` 头。
_OPTB = r"\[((?:(?!\n[ \t\r]*\n)[^\[\]]|\[[^\[\]\n]*\])*)\]"

#: 扩展机位表 —— judge ``_MACHINE_SLOT_RXS`` 不盖的机位头族, 逐
#: ``(kind, rx)``; rx 捕获组全为机位实参候选, 同一文件 src/zh 双侧
#: 命中数必须相等否则整 kind 跳。不改 judge 表: verdict 面
#: (``paired_slot_diff``/``machine_slot_audit``) 行为字节级不变。
_SLOTREV_EXTRA_RXS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # \begin{env}[opt]{mand}×≤4 —— 未注册 env 尾随机参
    # (translatedabstract{french}/Mizar{x,Y,A} 实证锚点); opt 位与
    # 尾随 mand 参全收。末臂 ``|_OPTC`` 收 opt-only 站
    # (\begin{tikzpicture}[kv] 类)。mand 参用 ``_ARGNL`` 跨行容忍 —
    # 参内字面换行合法 (2609.19556 ``{General\ninstructions}``: src
    # 站捕不进 → envarg 26≠28 整跳, 7 站 zh 参全漏)。
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
    # \colorbox[model]?{color}{text} —— 参0 (text 是散文不碰)
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
    # 计数器名参0: \setcounter/\addtocounter/\refstepcounter/\stepcounter/
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
    # \iftoggle{name}{t}{f} —— 参0 (分支是散文不碰)
    (
        "iftoggle",
        re.compile(r"\\iftoggle" + CMD_BOUNDARY + r"\s*" + _ARG),
    ),
    # \setkeys/\kvsetkeys [opt]?{fam}{list} —— fam 参0 (list 太宽不收)
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
    # ident 拒)。kv 行不盖: premise/conclusion mand 参多层花括号跨行
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
    # \LoadClass* [opt]?{name} —— opt+名两参 (还原实名供 static_precheck
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
    # —— 声明名参0 (后随 [n]/{before}/{after}/{Text} 散文位不碰)
    (
        "envdecl",
        re.compile(
            r"\\(?:newenvironment|renewenvironment|provideenvironment|"
            r"newtheorem|newcolumntype|NewEnviron|RenewEnviron|"
            r"DeclareFloatingEnvironment)" + CMD_BOUNDARY + r"\*?\s*" + _ARG
        ),
    ),
    # \newglossaryentry/\newacronym/\lstdefinelanguage —— 键/名参0
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
    # babel/polyglossia 语言名: \selectlanguage/\setdefaultlanguage/
    # \setmainlanguage/\setotherlanguage/\setotherlanguages/
    # \foreignlanguage [opt]?{lang} —— foreignlanguage 参1 散文不碰
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
    # 单参机名族: \pagenumbering/\pagestyle/\thispagestyle/\theoremstyle/
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
    # 文件路径单参族: \InputIfFileExists/\IfFileExists/\ProvidesFile/
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
    # \url/\href/\nolinkurl/\email/\doi/\orcidlink 参0 (href 参1 散文不碰)
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
    # \subref/\itemref/\footref/\thmref —— 键参0
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
    # glossaries/acronym 引用族 —— 键参0 (\glssee 参1 也是键表但随行)
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
    # ── 2026-09-19 arrayresid lane: 列 spec 机位 ──
    # envarg 同位收 spec 参但严格 ident 拒收真实 spec (|/空格/\@/</>/!/*
    # 全不在白名单; \textwidth 含反斜杠同理) —— 1502.01845 ``\betb``
    # 实证外, env-arg 位 zh 化 spec 是本族结构性盲区。spec-env 的参位
    # 即机位断言 (该位恒为机参, 内核拒 CJK → 参含 CJK 必为译污),
    # ident 放宽到可打印 ASCII。``\begin{tabular}`` 系首参 spec;
    # tabularx/tabulary/xtabular/tabular*/array* 系 ``{dimen}{spec}``
    # 双参全机位 (dimen 被译同样炸)。
    (
        "colspec",
        re.compile(
            r"\\begin\s*\{(?:tabular|array|deluxetable|smalldeluxetable|"
            r"sidewaysdeluxetable|sidewaystable|supertabular|longtable)\*?\}"
            + _GAP
            + r"(?:"
            + _OPT
            + _GAP
            + r")?"
            + _ARG
        ),
    ),
    (
        "colspec",
        re.compile(
            r"\\begin\s*\{(?:tabularx|tabulary|xtabular|tabular\*|array\*)\}"
            + _GAP
            + r"(?:"
            + _OPT
            + _GAP
            + r")?"
            + _ARG
            + _GAP
            + _ARG
        ),
    ),
    # \multicolumn{n}{spec}{text} —— n+spec 双机位 (text 散文不碰)
    (
        "colspec_mc",
        re.compile(r"\\multicolumn\*?" + CMD_BOUNDARY + r"\s*" + _ARG + r"\s*" + _ARG),
    ),
    # \newcolumntype{name}[n]{spec} —— spec 参 (name 参 envdecl 已盖;
    # spec 内 ``>{...}`` 花括号结构 ``_ARG`` 吃不进, 只护无括号形)
    (
        "colspec_nt",
        re.compile(
            r"\\newcolumntype\*?"
            + CMD_BOUNDARY
            + r"\s*"
            + r"\{[^{}\n]*\}\s*(?:\[[^\]\n]*\]\s*)?"
            + _ARG
        ),
    ),
    # ── 2026-09-20 primgap: 原语 cs 与 ``{``-组之间 gap 机位 ──
    # 捕获面与全表其他 kind 正交 —— 既有行捕获组全在 ``{}``/``[]``/
    # ``\csname`` 体内, 此 kind 收 ``\vadjust 这是译文{\vskip 1pt}``
    # (2609.19815) / ``\leaders\hbox 这是译文{...}`` (2609.20633 ×12)
    # 形: 译面把原语 keyword/dimen 尾巴 (``pre``/``to .55em``/
    # ``spread 2pt``/``16``/``12``) 落上 chunk → 写在 cs 与 ``{``
    # 之间 (tmp/lane-slotleak/verdict.md)。域 = 必需下接 ``{`` 的
    # 原语族; gap 域 spec ident (可打印 ASCII, 含空格/反斜杠)。
    # ``\leaders\hbox to .55em{`` 复合站 finditer 不重叠 → 单命中,
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
    # 形 (2609.20423 实证: 跨行+嵌套 ``{}`` 选项组整组 zh 化 →
    # ``/tcb/这是译文`` pgfkeys 错) —— ``_ARG`` 吃不进换行与嵌组,
    # 严格/宽松 ident 均拒带空白 kv → 独立 kind: ``_ARGB``/``_OPTB``
    # 平衡组捕获 (≤2/≤1 层嵌套, 空行截断) + kvnl ident (可打印
    # ASCII+``\t\n\r``, 且须含 ``=``/``,``/``#`` kv 形 —— 防
    # ``\begin{tcolorbox}`` 后散文 ``{multi\nline prose}`` 误收)。
    # ``{}``/``[]`` 双头形同盖 (tcblisting ``{opts}`` 必填形, tcolorbox
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
    # 的末组即 kv 机位 (``#n`` 形参位同域, 2609.19556
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
)

#: 严格 ident 白名单 —— 机位实参 (键/名/路径/kv 串/csv) 的字符域。
_IDENT_STRICT_RX = re.compile(r"[A-Za-z0-9@._/:+*!,=~-]+")
#: 宽松 ident —— 仅 font kind: 字体名含空格/'/()/& ("Times New Roman")。
_IDENT_LOOSE_RX = re.compile(r"[A-Za-z0-9@._/:+*!,=~ '()&-]+")
_IDENT_LOOSE_KINDS = frozenset({"font"})
#: spec ident —— 列 spec/dimen 参的字符域: 可打印 ASCII (| 空格
#: @ < > ! * 反斜杠全收; {} 结构上 ``_ARG`` 已排)。spec 位自带
#: 机位断言, 不复用严格白名单 (1502.01845 实证: 真 spec 恒被它拒)。
_IDENT_SPEC_RX = re.compile(r"[ -~]+")
#: spec 系 kind 前缀 —— colspec/colspec_mc/colspec_nt/colspec_holder:*。
_IDENT_SPEC_PREFIX = "colspec"
#: spec 同域 (可打印 ASCII) 的散 kind —— inferkv: opt kv 值含 cs 调用
#: (``\rlabel{Rec}``) 与空格, 严格/宽松 ident 均拒; 该位恒为
#: mathpartir kv 键表机位, CJK 即译污。primgap: 原语 pre-``{`` gap
#: 含空格/反斜杠 (``to .55em``/``\hbox to .55em``/``spread 2pt``)。
_IDENT_SPEC_KINDS = frozenset({"inferkv", "primgap"})
#: kvnl ident —— tcb kv 选项组字符域: 可打印 ASCII + ``\t\n\r`` (跨行
#: kv 串含嵌组/``#n`` 形参); 须同时含 ``=``/``,``/``#`` kv 形, 防
#: ``\begin{tcolorbox}`` 后散文 ``{multi\nline prose}`` 组误收 —
#: kvnl 白名单放得太宽, 纯散文 ASCII 组也能 fullmatch, 靠 kv 形断言
#: 兜底 (错位 revert 比不复原更糟; ``{listing only}`` 裸键站宁可漏)。
_IDENT_KVNL_RX = re.compile(r"[\t\n\r -~]+")
_KVNL_SHAPE_RX = re.compile(r"[=,#]")
_IDENT_KVNL_KINDS = frozenset({"tcbopt"})

#: unique-src 广播适用 kind —— 计数分歧时若 src 侧该 kind 全部 gap 值
#: 唯一且过 ident, 广播至 zh 侧全部含 CJK gap 站 (宏展开把单一 def 站
#: 机位倍增到调用站: 2609.20633 ``\tocdots`` def 1 站 ``\hbox to .55em``
#: vs zh ``\leaders\hbox`` 字面量调用站 ×14 实证)。仅 gap 恒为 TeX
#: keyword/dimen 机料的 primgap 启用 —— 其余 kind 计数分歧仍整跳
#: (错位 revert 比不复原更糟); src 多值/空集 → 同样整跳。
_BROADCAST_KINDS = frozenset({"primgap"})

#: note 面站点/分歧条目封顶 (与 judge._MACHINE_SLOT_MAX 同量级)。
_NOTE_CAP = 20


def _is_ident(arg: str, kind: str) -> bool:
    """机位标识符谓词。

    font 类用宽松名单 (字体名含空格), colspec 系用可打印 ASCII
    (spec/dimen 形), tcbopt 用 kvnl (可打印 ASCII+空白 ∧ kv 形),
    其余严格。
    """
    if kind in _IDENT_KVNL_KINDS:
        return (
            _IDENT_KVNL_RX.fullmatch(arg) is not None
            and _KVNL_SHAPE_RX.search(arg) is not None
        )
    if kind.startswith(_IDENT_SPEC_PREFIX) or kind in _IDENT_SPEC_KINDS:
        return _IDENT_SPEC_RX.fullmatch(arg) is not None
    rx = _IDENT_LOOSE_RX if kind in _IDENT_LOOSE_KINDS else _IDENT_STRICT_RX
    return rx.fullmatch(arg) is not None


#: doc 自定义 spec-holder 宏探测 —— def 体以 spec-env ``\begin`` 收尾
#: 即 ``\X{spec}`` 等价 ``\begin{ENV}{spec}`` (1502.01845 ``\betb``
#: = ``\begin{center}\begin{tabular}`` 实证, 参被译 → kernel "Illegal
#: character in array arg.")。[n] 形参表宏不收 (带参宏 {} 实参被 #n
#: 消费不进 token 流); ``\newcommand{\cs}``/``\newcommand\cs`` 双形 +
#: def/edef/gdef/xdef 族同盖。体一层花括号嵌套封顶 (``{center}``/
#: ``{tabular}`` 内层组)。
_HOLDER_DEF_RX = re.compile(
    r"\\(?:newcommand\*?|renewcommand\*?|providecommand\*?|"
    r"DeclareRobustCommand\*?|def|gdef|edef|xdef)"
    r"\s*\{?\\([A-Za-z@]+)\}?\s*"
    r"\{((?:[^{}]|\{[^{}]*\})*)\}"
)
#: def 体尾部 spec-env ``\begin`` 断言 (可带 ``[pos]`` 尾巴)。
_HOLDER_TAIL_RX = re.compile(
    r"\\begin\s*\{(?:tabular|array|deluxetable|smalldeluxetable|"
    r"sidewaysdeluxetable|sidewaystable|supertabular|longtable|"
    r"tabularx|tabulary|xtabular)\*?\}\s*(?:\[[^\]\n]*\]\s*)?$"
)
#: 每文件 spec-holder 名发现上限 (防宏农场文 noise kinds 刷屏)。
_HOLDER_CAP = 8


def _holder_rxs(src: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    r"""``src`` 文内 spec-holder 宏 → per-name ``(colspec_holder:X, rx)`` 表。

    ``mask_tex`` 视图扫描 (注释/逐字内 def 不算); 调用站 rx 吃可选
    ``[opt]`` 后首 ``{}`` 参 —— def 自体因体含花括号天然不匹配
    (``_ARG`` 吃不进 ``{}`` 体)。
    """
    view = mask_tex(src)
    dead = _DEAD_TAIL_RX.search(view)
    if dead is not None:
        view = view[: dead.start()]
    out: list[tuple[str, re.Pattern[str]]] = []
    seen: set[str] = set()
    for m in _HOLDER_DEF_RX.finditer(view):
        name, body = m.group(1), m.group(2)
        if name in seen or not _HOLDER_TAIL_RX.search(body):
            continue
        seen.add(name)
        rx = re.compile(
            r"\\" + re.escape(name) + CMD_BOUNDARY + r"\s*(?:\[[^\]\n]*\]\s*)?" + _ARG
        )
        out.append((f"colspec_holder:{name}", rx))
        if len(out) >= _HOLDER_CAP:
            break
    return tuple(out)


def _slot_spans(
    src: str, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> list[tuple[str, int, int]]:
    r"""单文件源文机位命中 → ``(kind, start, end)`` 序对 (原文 offset)。

    ``judge._slot_args`` 同口径的 ``mask_tex`` 视图 + 死尾截断, 每 match
    全部非 None 捕获组各自入列, 但保留位置供回写 —— arg 切片区间为
    ``src[start:end]``。
    """
    view = mask_tex(src)
    dead = _DEAD_TAIL_RX.search(view)
    if dead is not None:
        view = view[: dead.start()]
    hits: list[tuple[str, int, int]] = []
    for kind, rx in rxs:
        for m in rx.finditer(view):
            hits.extend(
                (kind, m.start(i), m.end(i))
                for i, g in enumerate(m.groups(), start=1)
                if g is not None
            )
    return hits


def _by_kind(hits: list[tuple[str, int, int]]) -> dict[str, list[tuple[int, int]]]:
    """命中按 kind 归桶, 桶内保文档序 (表行序→finditer 序)。"""
    d: dict[str, list[tuple[int, int]]] = {}
    for kind, s, e in hits:
        d.setdefault(kind, []).append((s, e))
    return d


def _broadcast_value(kind: str, ss: list[tuple[int, int]], src: str) -> str | None:
    """unique-src 广播值 → 唯一 gap 值 或 None。

    ``_BROADCAST_KINDS`` 内 kind 计数分歧时调用: src 侧全部命中值唯一
    ∧ 过 ``_is_ident`` → 返回该值供 zh 侧 CJK gap 广播; 多值/空集/非
    机料 → None (维持整跳, 错位 revert 比不复原更糟)。
    """
    if kind not in _BROADCAST_KINDS or not ss:
        return None
    vals = {src[s:e] for s, e in ss}
    if len(vals) != 1:
        return None
    (val,) = vals
    return val if _is_ident(val, kind) else None


def _revert_file(
    src: str, zh: str, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> tuple[str, int, list[str]]:
    r"""单文件 src/zh 配对 revert → ``(新 zh 文本, 改写数, 分歧项)``。

    per-kind 序号对齐: k-th zh 命中 ↔ k-th src 命中; 三条件全中才改 —
    双侧相异 ∧ zh 参含 CJK ∧ src 参纯 ident (ASCII 白名单)。改集按
    起始位降序右→左应用, 同位/重叠第二刀跳 (envarg↔restatable 等同位
    多行扫重)。kind 双侧命中数分歧 → 该 kind 整跳记入 ``分歧项``;
    ``_BROADCAST_KINDS`` 内 kind (primgap) 先经 ``_broadcast_value``
    判 unique-src 广播 —— src gap 值唯一则写进 zh 全部 CJK gap 站,
    多值/空集才回退整跳。spec-holder 动态行由 ``src`` def 体逐文件
    现查 (``_holder_rxs``)。
    """
    rxs = (*rxs, *_holder_rxs(src))
    src_by = _by_kind(_slot_spans(src, rxs))
    zh_by = _by_kind(_slot_spans(zh, rxs))
    if not zh_by:
        return zh, 0, []
    edits: list[tuple[int, int, str]] = []
    skipped: list[str] = []
    kinds = list(zh_by) + [k for k in src_by if k not in zh_by]
    for kind in kinds:
        ss, zs = src_by.get(kind, []), zh_by.get(kind, [])
        if len(ss) != len(zs):
            val = _broadcast_value(kind, ss, src)
            if val is None:
                skipped.append(f"{kind}({len(ss)}!={len(zs)})")
                continue
            edits.extend((z0, z1, val) for z0, z1 in zs if CJK_RX.search(zh[z0:z1]))
            skipped.append(f"{kind}({len(ss)}→{len(zs)} broadcast)")
            continue
        for (s0, s1), (z0, z1) in zip(ss, zs, strict=True):
            sarg, zarg = src[s0:s1], zh[z0:z1]
            if sarg == zarg or not CJK_RX.search(zarg) or not _is_ident(sarg, kind):
                continue
            edits.append((z0, z1, sarg))
    n = 0
    floor = len(zh) + 1
    for z0, z1, sarg in sorted(edits, key=lambda t: (-t[0], -t[1])):
        if z1 > floor:
            continue
        zh = zh[:z0] + sarg + zh[z1:]
        floor = z0
        n += 1
    return zh, n, skipped


def _full_rxs() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """机位全表: judge ``_MACHINE_SLOT_RXS`` + cite 族 + 本叶扩展行。"""
    from texlate.compile.judge import (  # noqa: PLC0415  # 延迟: fixloop 链重
        _MACHINE_SLOT_RXS,
    )

    return (*_MACHINE_SLOT_RXS, ("cite", CITE_FAMILY_RE), *_SLOTREV_EXTRA_RXS)


def _revert_tree(
    ctx: LoopCtx, base_root: Path, rxs: tuple[tuple[str, re.Pattern[str]], ...]
) -> tuple[list[str], list[str], int]:
    """逐 ``*.tex`` 与 baseline 同名件配对 revert → (件条目, 分歧项, 改数)。"""
    reverted: list[str] = []
    skipped: list[str] = []
    n_args = 0
    for f in ctx.tex_files((".tex",)):
        rel = f.relative_to(ctx.wdir).as_posix()
        zh = ctx.read(f)
        if zh is None:
            continue
        try:
            src = (base_root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if src == zh:
            continue
        new_text, n, sk = _revert_file(src, zh, rxs)
        skipped.extend(f"{rel}:{s}" for s in sk)
        if n:
            ctx.write(f, new_text)
            reverted.append(f"{rel}×{n}")
            n_args += n
    return reverted, skipped, n_args


def slot_arg_revert(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""把 zh 化机位实参按 ``params.baseline_dir`` pristine 树配对还原。

    precheck 位一次性跑 (L2 resplice 之后的首个耐写入点): 逐 ``*.tex``
    与 baseline 同名件做 per-kind 序号对齐配对, ``src`` 参为纯 ASCII
    标识符而 ``zh`` 参含 CJK → zh 参位换回 src 字节 (``ctx.write``
    记账写)。空转判据自证幂等 —— 机位参无 CJK 即不重扫写。
    """
    del eng, payload
    base_dir = params.get("baseline_dir")
    if not base_dir:
        return False, "no baseline_dir param"
    base_root = Path(str(base_dir))
    if not base_root.is_dir():
        return False, f"baseline_dir not a directory: {base_root}"
    reverted, skipped, n_args = _revert_tree(ctx, base_root, _full_rxs())
    if not reverted:
        note = "no zh machine-slot args to revert"
        if skipped:
            note += f"; divergent: {', '.join(skipped[:_NOTE_CAP])}"
        return False, note
    note = f"reverted {n_args} args in {len(reverted)} files: "
    note += ", ".join(reverted[:_NOTE_CAP])
    if len(reverted) > _NOTE_CAP:
        note += f" +{len(reverted) - _NOTE_CAP} files"
    if skipped:
        note += f"; divergent: {', '.join(skipped[:_NOTE_CAP])}"
    return True, note
