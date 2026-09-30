r"""``latex.segmenter._common_tail`` — 非文本尾参扫（``_common`` god-file 机械拆分叶）。

裸操作数/赋值形命令的 dimension 尾：``\\vskip3pt``、``\\[5pt]``、
``\\font\\cs=cmr10 at 12pt`` 的非文本槽位不在 ``{}`` 组内——操作数
``[+-]? FACTOR* BASE`` 正则机 + ``_OPERAND_SCAN_STOP`` 扫描终止符集 +
``_TAIL_RX`` 六种别尾扫 + ``\\`` opt dimen 参两形。
"""

from __future__ import annotations

import re

from texlate.latex.tables import (
    BOUNDARY_NAMES,
    BOX_TAIL_NAMES,
    CHUNK_ARG_NAMES,
    CITE_NAMES,
    DEF_NAMES,
    FONT_SWITCHES,
    INLINE_LITERAL_CMDS,
    INPUT_CMDS,
    PAIR_BLOCK_ALL,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    REF_NAMES,
    TRANSPARENT_HEAD_SPEC,
    TRANSPARENT_NAMES,
)

# ---------------------------------------------------------------- 非文本尾参扫
# 裸操作数/赋值形命令的 dimension 尾（loop1 slots 修复）：``\vskip3pt``、
# ``\\[5pt]``、``\hangindent=.5em``、``\vrule width 2pt``、``\font\cs=cmr10
# at 12pt`` 的非文本槽位不在 ``{}`` 组内——探针与组参规则都够不着，单位
# 字母裸进 surface 即被翻译（illegal_unit 主错因）。原子 = cs 操作数
# （``\hskip \labelsep``）或 NUM+UNIT——UNIT 硬性要求（裸数字不是
# dimension）。UNIT 不做字母词界前瞻：TeX 单位扫描是定长关键字匹配，
# ``10ptReceived`` = ``10pt`` + ``Received`` 文本（physics/9901057 实证——
# ``\baselineskip=10pt`` 后紧跟 Received 无空格，前瞻拒配曾致整尾漏进
# surface）。``1in`` 后 ``put`` 等同理。
_DIMEN_NUM = r"(?:\d+[.,]\d*|[.,]\d+|\d+|\.)"
_DIMEN_UNIT = (
    r"(?:true[ \t]*)?"
    r"(?:filll|fill|fil|pt|pc|in|bp|cm|mm|dd|cc|sp|em|ex|mu|zw|zh|px|Q|H)"
)
# 尾参间隙：TeX 空白语义——空格/制表/单换行/``%`` 行注释皆可分隔操作数
# （``\hskip\n 1em`` 2105.00030、``\\\n[8pt]`` hep-ph/0307181、
# ``\\[0pt%\n]`` 1511.06628 实证）；``\n\n`` 段界不跨（par 后是正文）。
# 原子组：三选一首字符互斥（ws/`%`/`\n`），但 ``%[^\n]*`` 变长片在
# ``(?:W)*`` 外层星号下对 ``%%%%``/``%====`` 注释墙有 2^N 重分段——
# ATOM 失配即 ReDoS（illegal_unit 波 held6 实证：老论文头部注释横幅）。
# ``(?>`` 提交单次选择消重分段，语义不变。
_WS_NOPAR = r"(?>[^\S\n]|%[^\n]*|\n(?![ \t\n]*\n))"
# cs 名带 ``(?![a-zA-Z@])`` 边界：切片窗可能切在名中（``_TAIL_CAP``），
# 无边界则 ``\\foo``|``bar`` 斩名半吞。
# 尾参操作数 = ``[+-]? FACTOR* BASE``（TeX ``<number>/<dimen>/<glue>``
# 扫描的因子×基复合）：FACTOR = cs 内部量或裸数（``4\fontdimen``、
# ``\BIBentryALTinterwordstretchfactor\fontdimen``、``0.5\baselineskip``
# 的前件）；BASE = ``NUM[ \t]*UNIT``（物理单位）/``'oct``/``"hex``/cs/
# 裸数。``\fontdimen2\font``/``4\fontdimen3\font``/``\count0`` 皆此形
# （M1-B 残漏实证：natbib ``\BIBentryALTinterwordspacing`` 展开体、
# ``\multiply\ione by 10`` 族）。两硬界：项间零间隙（邻接才成链——
# ``\vskip1em \section`` 的空格断链防误吃下行命令）；NUMUNIT 必为链尾
# （物理单位后 TeX 只续 plus/minus——``2pt\foo`` 的 ``\foo`` 不收）。
# ``\input`` 族文件参命令永不作操作数 cs——TeX 数/胶扫遇不可展开
# ``\input`` 即止（xetex 实证 ``\count0=5000\input{f}``：数=5000、
# ``\input`` 随后照常执行），吃进 FACTOR/BASE 会把 ``{file}`` 组孤儿
# 化裸落 surface 被译（2403.00100 ``\clubpenalty=5000\input{...}``）。
# ``\include``/``\import``/``\subfile``/``\@input`` 等同带文件参族全排；
# ``\endinput`` 同类（换源哨兵语义亦不可被操作数吞掉）。本表推广到
# 全部扫描终止符：TeX 数/胶扫遇**不可展开命令**即止，下列 cs 永不
# 是操作数值——吃进只把其后随参孤儿化：``{file}``/``{key}`` 机器参
# （``\setbox0=\hbox{`` 盒体 corpus 493 命中/216 篇、``\message{``
# 日志载荷、``\end{env}`` 环境名破对）、断链裸尾（``\vskip3pt
# plus1pt`` 的 ``plus1pt``、``\setlength\parskip{3pt}`` 的 ``{3pt}``）、
# 结构子（``\par``/``\item``/``\fi``/``\begin``）。排除后各 cs 回本族
# 分派（boundary/protect/cond/透明/探针）自收其参；赋值 ``=`` 由
# arith 臂裸收——rval 是终止符时 ``=`` 不裸落 surface。
# KEEP 侧（仍是合法操作数不排）：寄存器/内部量（``\count``/``\dimen``/
# ``\skip``/``\muskip``/``\toks``/``\baselineskip``/``\fontdimen``/
# ``\skewchar``/``\hyphenchar``/``\catcode`` 族/``\font``）、盒引用
# （``\box``/``\copy``/``\lastbox``/``\vsplit``/``\hsplit``）、数/胶
# 产生子（``\the``/``\number``/``\romannumeral``/``\numexpr``/
# ``\dimexpr`` 族）——``\setbox0=\box1``/``\multiply\i by\count0``/
# ``\vskip0.5\baselineskip`` 的 cs 因子照吃。
_OPERAND_SCAN_STOP = frozenset(
    INPUT_CMDS
    | DEF_NAMES
    | BOUNDARY_NAMES
    | PROTECT_NAMES
    | CITE_NAMES
    | REF_NAMES
    | CHUNK_ARG_NAMES
    | PROTECT_BLOCK_NAMES
    | TRANSPARENT_NAMES
    | PAIR_BLOCK_ALL
    | INLINE_LITERAL_CMDS
    | FONT_SWITCHES
    | BOX_TAIL_NAMES
    | set(TRANSPARENT_HEAD_SPEC)
    | {
        "endinput",
        # 赋值运算符头——``=``/``by`` 前件永不作操作数值
        "advance",
        "multiply",
        "divide",
        "setbox",
        "chardef",
        "mathchardef",
        "countdef",
        "dimendef",
        "skipdef",
        "muskipdef",
        "toksdef",
        "let",
        "futurelet",
        "afterassignment",
        "aftergroup",
        "expandafter",
        "noexpand",
        "global",
        "long",
        "outer",
        "protected",
        "newif",
        # 胶/kern/位移命令——尾参自带 dimen 扫，吃进反断链漏单位
        "kern",
        "mkern",
        "mskip",
        "vglue",
        "hglue",
        "hfil",
        "vfil",
        "hss",
        "vss",
        "hfilneg",
        "filneg",
        "moveleft",
        "moveright",
        "raise",
        "lower",
        "unskip",
        "unpenalty",
        "unkern",
        "removelastskip",
        # 罚分/断行命令
        "penalty",
        "break",
        "nobreak",
        "allowbreak",
        "eject",
        "supereject",
        "goodbreak",
        "smallbreak",
        "medbreak",
        "bigbreak",
        "filbreak",
        # 规则/leaders
        "hrule",
        "vrule",
        "leaders",
        "cleaders",
        "xleaders",
        # 对齐
        "halign",
        "valign",
        "ialign",
        "cr",
        "crcr",
        "omit",
        "span",
        "hidewidth",
        "noalign",
        "multispan",
        # 插入/调整/输出
        "insert",
        "vadjust",
        "topinsert",
        "midinsert",
        "pageinsert",
        "endinsert",
        "shipout",
        "dump",
        "bye",
        # I/O 与日志/标记载荷——``{..}``/``=file`` 机器参非排版文
        "openin",
        "openout",
        "closein",
        "closeout",
        "read",
        "readline",
        "write",
        "immediate",
        "message",
        "errmessage",
        "wlog",
        "typeout",
        "special",
        "mark",
        "marks",
        "topmark",
        "firstmark",
        "botmark",
        "splitfirstmark",
        "splitbotmark",
        "show",
        "showthe",
        "showbox",
        "showlists",
        "showgroups",
        "showifs",
        "showtokens",
        "meaning",
        "string",
        "jobname",
        "fontname",
        # pdfTeX/LuaTeX 参数原语（``\pdfoutput``/``\pdfpagewidth`` 等
        # 内部量不在列——仍是合法操作数）
        "pdfliteral",
        "pdfobj",
        "pdfdest",
        "pdfannot",
        "pdfoutline",
        "pdfxform",
        "pdfsavepos",
        "savepos",
        "pdfcolorstack",
        "pdfstartlink",
        "pdfendlink",
        "pdfthread",
        "pdfaction",
        "pdffontattr",
        "pdfform",
        "pdfrefxform",
        "pdfximage",
        "pdfrefximage",
        "pdfincludechars",
        "pdfglyphtounicode",
        "pdfprimitive",
        "pdfextension",
        "pdfnames",
        "pdfcatalog",
        "pdftrailer",
        "pdfinfo",
        "pdfescapestring",
        "pdfmatch",
        "directlua",
        "latelua",
        "luaescapestring",
        # 展开/大小写/串化产生子——产物非数即终止
        "unexpanded",
        "detokenize",
        "scantokens",
        "expanded",
        "uppercase",
        "lowercase",
        "csname",
        "endcsname",
        "magstep",
        "magstephalf",
        # 结构/段落/条件关键子（``\if*`` 全族由前瞻模式盖）
        "par",
        "indent",
        "noindent",
        "leavevmode",
        "end",
        "begin",
        "item",
        "else",
        "or",
        "fi",
        "begingroup",
        "endgroup",
        "bgroup",
        "egroup",
        "discretionary",
        "hyphenation",
        "patterns",
        "noboundary",
        "verb",
        "lstinline",
        # 数学结构子/定界/分式/字母命令
        "eqno",
        "leqno",
        "over",
        "atop",
        "above",
        "overwithdelims",
        "atopwithdelims",
        "abovewithdelims",
        "choose",
        "mathchoice",
        "mathpalette",
        "mathop",
        "mathrel",
        "mathbin",
        "mathord",
        "mathopen",
        "mathclose",
        "mathpunct",
        "mathinner",
        "limits",
        "nolimits",
        "displaylimits",
        "displaystyle",
        "textstyle",
        "scriptstyle",
        "scriptscriptstyle",
        "nonscript",
        "phantom",
        "hphantom",
        "vphantom",
        "smash",
        "sqrt",
        "root",
        "matrix",
        "pmatrix",
        "bordermatrix",
        "cases",
        "eqalign",
        "eqalignno",
        "leqalignno",
        "displaylines",
        "left",
        "right",
        "middle",
        "big",
        "Big",
        "bigg",
        "Bigg",
        "bigl",
        "bigr",
        "Bigl",
        "Bigr",
        "bigm",
        "Bigm",
        "biggl",
        "biggr",
        "Biggl",
        "Biggr",
        "frac",
        "dfrac",
        "tfrac",
        "binom",
        "dbinom",
        "tbinom",
        "cfrac",
        "overline",
        "overbrace",
        "underbrace",
        "overset",
        "underset",
        "stackrel",
        "mathrm",
        "mathbf",
        "mathit",
        "mathsf",
        "mathtt",
        "mathcal",
        "mathbb",
        "mathfrak",
        "mathscr",
        "mathnormal",
        "boldsymbol",
        "bm",
        "pmb",
        "text",
        "intertext",
        "operatorname",
        # 字符/符号与盒命令（盒引用 ``\box``/``\copy``/``\lastbox``/
        # ``\vsplit`` 是 ``\setbox`` 合法 rval 不排）
        "char",
        "mathchar",
        "accent",
        "symbol",
        "unhbox",
        "unvbox",
        "unhcopy",
        "unvcopy",
        "rlap",
        "llap",
        "line",
        "rule",
        # LaTeX 内核声明/NFSS/计数器产生子/杂项命令
        "newlength",
        "newfont",
        "DeclareRobustCommand",
        "DeclareTextCommand",
        "DeclareTextSymbol",
        "DeclareTextAccent",
        "DeclareMathSymbol",
        "DeclareMathDelimiter",
        "DeclareOption",
        "ProcessOptions",
        "LoadClass",
        "PassOptionsToPackage",
        "ProvidesPackage",
        "ProvidesFile",
        "ProvidesClass",
        "NeedsTeXFormat",
        "CheckCommand",
        "IfFileExists",
        "AtBeginDocument",
        "AtEndDocument",
        "AtEndOfPackage",
        "selectfont",
        "fontencoding",
        "fontfamily",
        "fontseries",
        "fontshape",
        "fontsize",
        "usefont",
        "definecolor",
        "color",
        "pagecolor",
        "fcolorbox",
        "epsfig",
        "psfig",
        "multicolumn",
        "multirow",
        "sloppy",
        "fussy",
        "raggedright",
        "raggedleft",
        "raggedbottom",
        "flushbottom",
        "enlargethispage",
        "addpenalty",
        "addvspace",
        "protect",
        "value",
        "arabic",
        "roman",
        "Roman",
        "alph",
        "Alph",
        "fnsymbol",
        "thepage",
        "baselinestretch",
        "arraystretch",
        "textfraction",
        "topfraction",
        "bottomfraction",
        "floatpagefraction",
        "dbltopfraction",
        "dblfloatpagefraction",
    }
)
_OPERAND_CS = (
    r"\\(?!(?:"
    + "|".join(sorted(_OPERAND_SCAN_STOP, key=len, reverse=True))
    + r"|if[a-zA-Z@]*)"
    + r"(?![a-zA-Z@]))[a-zA-Z@]+(?![a-zA-Z@])"
)
_OPERAND_FACTOR = r"(?:" + _OPERAND_CS + "|" + _DIMEN_NUM + r")"
_OPERAND_BASE = (
    _DIMEN_NUM
    + r"[ \t]*"
    + _DIMEN_UNIT
    + r"|'[0-7]+|\"[0-9A-Fa-f]+|"
    + _OPERAND_CS
    + r"|"
    + _DIMEN_NUM
)
_TAIL_OPERAND = (
    r"(?:"
    + _WS_NOPAR
    + r")*[+-]?(?:"
    + _WS_NOPAR
    + r")*(?:"
    + _OPERAND_FACTOR
    + r")*(?:"
    + _OPERAND_BASE
    + r")"
)
# 扫描终止符：TeX 数/胶扫描遇 ``\relax`` 即停——``1em plus..\relax``/``=1\relax``
# 是惯用收束形，尾随 ``\relax`` 随操作数同收（裸 ``\relax`` 留在表面会被
# INLINE_LITERAL 原样进 chunk）。``(?![a-zA-Z@])`` 防 ``\relaxX`` 长名腰斩。
_TAIL_RELAX = r"(?:(?:" + _WS_NOPAR + r")*\\relax(?![a-zA-Z@]))?"
_TAIL_RX = {
    # skip/dimen：``[=]?<operand> [plus|minus <operand>]* [\relax]``
    "dimen": re.compile(
        r"(?:"
        + _WS_NOPAR
        + r")*=?"
        + _TAIL_OPERAND
        + r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:plus|minus)(?![a-zA-Z])"
        + _TAIL_OPERAND
        + r")*"
        + _TAIL_RELAX
    ),
    # 计数器赋值/操作数：``[=]?<operand> [\relax]``（``\hangafter 1`` 无等
    # 号形同收——operand 的裸数项即原 count 形）
    "count": re.compile(r"(?:" + _WS_NOPAR + r")*=?" + _TAIL_OPERAND + _TAIL_RELAX),
    # ``\hrule``/``\vrule``：``(width|height|depth [=]?<operand>)+``
    "rule": re.compile(
        r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:width|height|depth)(?![a-zA-Z])(?:"
        + _WS_NOPAR
        + r")*=?"
        + _TAIL_OPERAND
        + r")+"
        + _TAIL_RELAX
    ),
    # ``\font\cs=name [at <operand>|scaled NUM]``
    "font": re.compile(
        r"(?:" + _WS_NOPAR + r")*\\[a-zA-Z@]+[ \t]*=?[ \t]*[A-Za-z0-9._/-]+"
        r"(?:[ \t]+at(?![a-zA-Z])[ \t]*"
        + _TAIL_OPERAND
        + r"|[ \t]+scaled(?![a-zA-Z])[ \t]*[+-]?"
        + _DIMEN_NUM
        + r")?"
        + _TAIL_RELAX
    ),
    # 通用赋值：``=<operand>``（``\foo=2pt``/``\foo=2`` 的 ``=N`` 永不
    # 可能是散文——count 形兜底一切表外名，``\hangafter=1`` 同收）
    "assign": re.compile(r"(?:" + _WS_NOPAR + r")*=" + _TAIL_OPERAND + _TAIL_RELAX),
    # 算术/寄存器赋值双操作数：``\multiply\I by 10``/``\advance\D by \G``/
    # ``\divide\I by 2``、``\skewchar\F='77``/``\hyphenchar\F=45``/
    # ``\fontdimen2\font=5pt``/``\countdef\I=5``/``\count0=5``/
    # ``\setbox0=\hbox to3cm``——``by``/``=`` 间隔可省（``\advance\X\Y``），
    # rvalue 后允许 glue 尾（``\advance\S by -2pt plus1pt``）与盒规格尾
    # （``\setbox`` 的 ``\hbox to<dim>``——``to`` 裸落被译的实证在
    # hep-th/9703214、``by`` 在 math/9901091）。
    "arith": re.compile(
        r"(?:"
        + _WS_NOPAR
        + r")*"
        + _TAIL_OPERAND
        + r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:(?:by(?![a-zA-Z])|=)"
        + _TAIL_OPERAND
        + r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:plus|minus)(?![a-zA-Z])"
        + _TAIL_OPERAND
        + r")*|=)"
        + r")?"
        + r"(?:(?:"
        + _WS_NOPAR
        + r")*(?:to|spread)(?![a-zA-Z])"
        + _TAIL_OPERAND
        + r")?"
        + _TAIL_RELAX
    ),
    # 盒规格：``\vbox to3cm{..}``/``\vtop spread-2pt``——``to|spread`` 必在
    # （纯 ``\vbox{..}`` 无尾参，留给常规探针）；``\hbox`` 同形但走
    # 主流透明档前的截获（体文要续扫进 chunk）。
    "boxspec": re.compile(
        r"(?:"
        + _WS_NOPAR
        + r")*(?:to|spread)(?![a-zA-Z])"
        + _TAIL_OPERAND
        + _TAIL_RELAX
    ),
}
# ``\\[5pt]``/``\\*[2em]`` 的可选 dimen 参（``\\`` 走单字符字面行，
# ``[5pt]`` 裸落 surface → illegal_unit——slots① 第二形态）；``\\`` 与
# ``[`` 间允许单换行/注释（``\\\n[8pt]``/``\\[0pt%\n]`` 同收）。
_BSBS_OPT_RX = re.compile(
    r"\*?(?:" + _WS_NOPAR + r")*\[" + _TAIL_OPERAND + r"(?:" + _WS_NOPAR + r")*\]"
)
# 组内 ``\\`` opt 参的内容判据（``_grp_bsbs`` 的 fullmatch 版）
_GRP_BSBS_CONTENT_RX = re.compile(
    r"[ \t]*[+-]?[ \t]*(?:"
    + _OPERAND_FACTOR
    + r")*(?:"
    + _OPERAND_BASE
    + r")(?:[ \t\n]*|%[^\n]*)*"
)
# 组内尾参扫的 surface join 字符窗上限
_GRP_TAIL_CAP = 96
# 主路尾参扫的字节窗上限——尾参物理上数十字节级（数+单位+plus/minus 项），
# 窗帽让任何未来正则病灶代价有界（held6 ReDoS 教训：嵌 _WS_NOPAR 的匹配
# 一律不裸跑全文 haystack）
_TAIL_CAP = 512
