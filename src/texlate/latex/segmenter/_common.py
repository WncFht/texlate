r"""``latex/segmenter`` 共享层——常量/helper/数据类（原模块级原样搬移）。"""

from __future__ import annotations

import re
from bisect import (
    bisect_left,
)
from collections import (
    deque,
)
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    TYPE_CHECKING,
    NamedTuple,
    Protocol,
)

from texlate.latex.macro_table import (
    parse_argspec,
)
from texlate.latex.model import (
    ArgSpec,
    PhType,
    Span,
)
from texlate.latex.placeholder import (
    PH_RX,
)
from texlate.latex.tables import (
    ACCENT_CHARS,
    BOUNDARY_NAMES,
    BOX_TAIL_NAMES,
    CHUNK_ARG_NAMES,
    CHUNK_MAX,
    CITE_NAMES,
    COND_RX,
    DEF_NAMES,
    DIMEN_TAIL_KIND,
    ENV_MANDATORY_ARG,
    FONT_SWITCHES,
    INLINE_LITERAL_CMDS,
    INPUT_CMDS,
    INPUT_SCAN_CMDS,
    MATH_ENVS,
    PAIR_BLOCK_ALL,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    PROTECTED_ENVS,
    REF_NAMES,
    TRANSPARENT_HEAD_SPEC,
    TRANSPARENT_NAMES,
    VERBATIM_ENVS,
)
from texlate.textutil import (
    BEGIN_DOC_RX,
    DOCCLASS_RX,
    mask_tex,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.latex.gullet import (
        Arg,
        EnvDef,
        ScopeMacroTable,
    )
    from texlate.latex.model import ArgspecEntry
    from texlate.latex.mouth import (
        Mouth,
        Tok,
    )

# ---------------------------------------------------------------- 表常量
# 原 ``segmenter/tables.py``（scanner v1/segmenter v2 双臂单源）——v1 退役后
# 收回本模块直接定义；args/core/env/group/mainloop/pending 仍经本模块取。

_CLEAN_CMD_RX = re.compile(r"\\[a-zA-Z@]+\*?|\\[^a-zA-Z]")
_CLEAN_NONALPHA_RX = re.compile(r"[^a-zA-Z]")
_LEAD_WS_RX = re.compile(r"\s*")
_TRAIL_WS_RX = re.compile(r"\s*$")

_PROTECT_TYP = {
    "includegraphics": PhType.GRAPHICS,
    "url": PhType.URL,
    "path": PhType.URL,
    "label": PhType.LABEL,
    "bibliography": PhType.BIB,
    "bibliographystyle": PhType.BIB,
    "bibitem": PhType.BIB,
}

_CHUNK_SPEC_CACHE: dict[str, list[ArgSpec]] = {}


def _chunk_spec_cached(spec_str: str) -> list[ArgSpec]:
    """``CHUNK_ARG_SPEC`` 签名串 → ``list[ArgSpec]``（解析一次缓存）。"""
    if spec_str not in _CHUNK_SPEC_CACHE:
        _CHUNK_SPEC_CACHE[spec_str] = parse_argspec(spec_str)
    return _CHUNK_SPEC_CACHE[spec_str]


_COMMENT_GAP_RX = re.compile(r"%[^\n]*")
# 参数体内裸 ``%`` 注释（``\%`` 转义由 ``\\.`` 分支先吃掉）——in_arg 渲染串
# 的 ``%`` 必为真注释（token 层已证非 \verb/url 体内）
_ARG_COMMENT_RX = re.compile(r"\\.|%[^\n]*")


# 组内再生保护段的配对前瞻上限（env/math/delim 扫描步数）
_GRP_SCAN_CAP = 4000
#: 组内 consumed marker 的非副作用白名单（input 换源 / if 选支回放）；
#: 其余 tag（def 族/let/catcode/newif/ifundefined…）都在展开时改过宏表，
#: surface 无法再生其副作用——命中即整组回 literal（_close_group）。
_GRP_FLOW_TAGS = ("input:", "input_tag:", "endinput", "if:", "fi:")

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

# ---- 跨边界待绑参（key-arg 泄漏修复）：展开组尾 cs 的调用点参数吸回组内 ----
# ``\def\r{\ref}``+``\r{key}``：``\ref`` 是展开产物（pos=定义体、origin=
# 调用区间），``{key}`` 是 gen=0 调用点 token（pos==origin 末——`_in_group`
# 的 ``a < o[2]`` 开区间把它挡在组外）→ 无吸纳则 ``{key}`` 落 chunk 被译。
# 槽形字母 → ``_slot_elem`` 归一投影成 ``_WSpec``——列扫走参本体只有一份
# （``group._walk_spec_toks``：``_slots_walk_toks``/``_grp_call_end``/
# ``_grp_probe_end``/``_grp_spec_args_end``/``_grp_spec_walk`` 共用）；
# 流侧拉取对价是 ``pending._absorb_slots``（read/unread 账本不同构，不统一）：
#   s   = 紧邻 ``*``（不跳 ws——``\ref *{k}`` 的星不是星参，call_end 同规）
#   o   = ws + ``[..]`` 平衡组（可选——失配过给下一槽）
#   m   = ws + ``{..}`` 平衡组（失配即调用终止）
#   e   = ws + ``{..}``|``[..]`` 任选一组（hyperref 首参形；失配终止）
#   a   = accent 参（``{..}``|单 letter/other|单字符名 cs；失配终止）
#   b   = ws + ``[dimen]``（``\\`` 尾参；内容须 fullmatch _GRP_BSBS_CONTENT_RX）
#   n   = ws + 单 cs token 或 ``{..}``/``[..]`` 组（``\setlength\parskip``
#         裸名参；强制——失配即调用终止）
#   dXY = ws + ``X..Y`` 定界对（argspec d/D/r/R；可选——失配过槽）
#   tC  = ws + 单测试字符（argspec t；可选）
_PEND_CALL1 = ("s", "o", "o", "o", "m")  # ``_grp_call_end`` mand=1 形
_PEND_CALL2 = ("s", "o", "o", "o", "m", "m")  # inputminted 双 ``{m}``
_PEND_PROBE = ("o", "m", "m", "m", "m", "m", "m")  # ``_grp_probe_end`` 形
_SLOT_PAIR_LEN = 3  # ``dXY`` 槽宽（d + 开/闭定界符）
_SLOT_TEST_LEN = 2  # ``tC`` 槽宽（t + 测试字符）

# ---- ``_pend_spec_of`` 槽列 ↔ ``_grp_scan``/``_grp_bsbs``/``_grp_call_end``
# 走参元的同形单源：名→槽形改动只改一处（``_slot_elem`` 逐位归一投影进
# ``_walk_spec_toks``）。
_HYPERREF_SLOTS: tuple[str, ...] = ("s", "e")  # hyperref 行（key,text 首参形）
_BSBS_SLOTS: tuple[str, ...] = ("s", "b")  # ``\\`` 行（``group._grp_bsbs`` 同形）
_ACCENT_SLOTS: tuple[str, ...] = ("a",)  # accent 行


def _cond_slots(name: str) -> list[str]:
    r"""``\iftoggle`` 族名/表达式槽列——``_pend_spec_of``/``_grp_scan`` COND 行同形。"""
    return ["m"] * _COND_GROUP_ARGS.get(name, 0)


def _call_slots(tail: list[str]) -> list[str]:
    r"""``_grp_call_end`` 整调用形槽列：``["s","o","o","o"]`` 前缀 + 强制参尾列。

    ``_pend_spec_of`` cite-ref/boundary/argspec 整调用行与组内
    ``_grp_call_end`` 同形（``_PEND_CALL*``/``_pend_call_slots`` 同族）。
    """
    return ["s", "o", "o", "o", *tail]


# 字符串宏体尾 cs 提取（``_keyarg_tail`` 的 str-body 臂）
_KEYARG_TAIL_RX = re.compile(r"\\([a-zA-Z@]+)\s*$")
_KEYARG_TAIL_DEPTH = 4  # ``\a``→``\b``→``\ref`` 别名链递归上限（防环）

# 数学内正文参命令：``{..}`` 参重进文本态，体内 ``$`` 属组内配对、不关外
# 层数学——``_on_math`` 体扫遇此族整参跳扫（``\text{...$x$...}`` 在内层
# ``$`` 截断外层 = 0806.3472 ``missing_character`` 残留面）。``parbox`` 类
# 多参命令不在列（正文非首参，定序跳扫够不着）。
_MATH_TEXTARG_OPT_CAP = 2  # ``makebox``/``framebox`` 式 ``[opt]`` 前缀上限
_MATH_TEXTARG = frozenset(
    {
        "text",
        "intertext",
        "shortintertext",
        "mbox",
        "hbox",
        "fbox",
        "makebox",
        "framebox",
        "emph",
        "textnormal",
        "textrm",
        "textit",
        "textbf",
        "textsf",
        "texttt",
        "textsc",
        "textsl",
        "textup",
        "textmd",
    }
)


def _cite_ref_type(name: str) -> PhType | None:
    r"""cite/ref 词族 → ``PhType``（``_dispatch`` 6/7 行与 ``_group_surface`` 共用）。

    ``href``/``hyperref`` 带可译 text 参不在 REF 列——``*ref`` 后缀规则会把
    ``[label]{text}`` 的 text 整吞进 ``[[REF]]``（两处分派必须同一排除集，
    单边漂移即丢 text 参）。
    """
    if name in CITE_NAMES or name.startswith("cite"):
        return PhType.CITE
    if name in REF_NAMES or (
        name.endswith("ref")
        and name not in TRANSPARENT_NAMES
        and name not in ("href", "hyperref")
    ):
        return PhType.REF
    return None


def _accent_cs(name: str) -> bool:
    r"""Accent 族行谓词：``\c{c}``/``\~n`` 单参保护——``_DISPATCH_FAMS``/``_GRP_SURFACE_FAMS``/``_PEND_SPEC_FAMS`` 三表与 ``_dispatch`` 16c 行同判据。"""
    return len(name) == 1 and name in ACCENT_CHARS


def _inline_lit_cs(name: str) -> bool:
    r"""行内字面行谓词：符号/品牌/旧式字体开关/无参单字符命令——三镜像表与 ``_dispatch`` 17 行同判据。"""
    return (
        name in INLINE_LITERAL_CMDS
        or name in FONT_SWITCHES
        or (len(name) == 1 and not name.isalpha())
    )


# ------------------------------------------------------------------ 分派族表

# 行匹配判据小常量——三面投影共享（原 mainloop/pending 各自本地定义重份）。
_VERB_LIKE = ("verb", "verb*", "lstinline")
_ENV_CS = ("begin", "end")
_MATH_OPEN_CS = ("[", "(")
_MATH_CLOSE_CS = ("]", ")")
_MATH_DELIM_CS = ("[", "(", "]", ")")

#: 族 tag → 行判据单源：名集 | ``str`` 单名 | 谓词 | ``None`` 动态行
#: （宏表/argspec/探针裁决——名级不可静态判定）。三面分派表
#: ``mainloop._DISPATCH_FAMS``/``pending._GRP_SURFACE_FAMS``/
#: ``pending._PEND_SPEC_FAMS`` 共享本绑定——各面**行序**是分派语义
#: 不可约（主流 ``math-open`` 殿后而组面抢先），绑定才是共享数据；
#: 新族只在本表登记一次，各面 ``_fams`` 序列表自行取舍。
_FAM_BIND: dict[str, object] = {
    "verb": _VERB_LIKE,
    "env": _ENV_CS,
    "cite-ref": _cite_ref_type,
    "protect": PROTECT_NAMES,
    "href": "href",
    "hyperref": "hyperref",
    "input-scan": INPUT_SCAN_CMDS,
    "chunk-arg": CHUNK_ARG_NAMES,
    "protect-block": PROTECT_BLOCK_NAMES,
    "transparent-head": TRANSPARENT_HEAD_SPEC,
    "box-tail": BOX_TAIL_NAMES,
    "transparent": TRANSPARENT_NAMES,
    "boundary": BOUNDARY_NAMES,
    "endinput": "endinput",
    "cond": COND_RX.match,
    "math-open": _MATH_OPEN_CS,
    "math-close": _MATH_CLOSE_CS,
    "math-delim": _MATH_DELIM_CS,
    "bsbs": "\\",
    "accent": _accent_cs,
    "inline-literal": _inline_lit_cs,
    "macro": None,  # 主流 row18：gullet 宏表 env_begin/env_end/opaque/math
    "env-macro": None,  # 组内对价：env_begin/env_end 宏端点
    "opaque": None,  # 组内对价：opaque/math 宏 spec 走参（_grp_spec_walk 余量臂）
    "pair-block": PAIR_BLOCK_ALL,  # cs 对界 DSL 块（W29 pinlabel）
    "argspec": None,
    "keyarg": None,  # _keyarg_tail 宏体尾 key-arg（pend 面独有）
    "tail": DIMEN_TAIL_KIND,  # 非 BOUNDARY 的 dimen/assign 尾参（组面独有）
    "unknown": None,  # 主流 row19：尾参扫→keyarg→argspec→探针→逐字
    "probe": None,  # 组面终端：_grp_probe_end → CMD/逐字
}


def _fams(*order: str) -> tuple[tuple[str, object], ...]:
    """族序列表 → 行投影：``(tag, _FAM_BIND[tag])``——未登记 tag 即 KeyError。"""
    return tuple((tag, _FAM_BIND[tag]) for tag in order)


def _pend_call_slots(name: str) -> list[str]:
    r"""Key-arg 名 → 待绑参槽列（``_grp_call_end`` 同形）。

    ``url``/``path`` 只认 ``{..}`` 形（定界形参无法 token 配对回吸）。
    """
    if name in ("url", "path"):
        return ["m"]
    return list(_PEND_CALL2 if name == "inputminted" else _PEND_CALL1)


def _pend_slot_of(s: ArgSpec) -> str | None:  # noqa: PLR0911 — 槽字母各一分支，平铺即映射表
    r"""``ArgSpec`` → 待绑参槽字母；``e``/``b``/无 delim 形 → ``None``（槽形截尾）。"""
    k = s.kind
    if k in ("m", "v"):
        return "m"
    if k == "n":
        return "n"
    if k in ("o", "O"):
        return "o"
    if k == "s":
        return "s"
    if k == "t" and s.delim:
        return "t" + s.delim[0]
    if k in ("d", "D", "r", "R") and s.delim:
        return "d" + s.delim[0] + s.delim[-1]
    return None


# ------------------------------------------------- 归一走参元（_walk_spec_toks）
# 物化 token 列上的 spec 走参曾是五份平行实现（``_slots_walk_toks`` 槽字母、
# ``_grp_call_end``/``_grp_probe_end`` 定形槽列、``_grp_spec_args_end`` argspec、
# ``_grp_spec_walk`` gullet Arg+ka 尾段）——三字母表到 ``_WSpec`` 的投影单源
# 化后，走参本体只剩 ``group._walk_spec_toks`` 一份。流侧（read/unread 账本）
# 对价仍是 ``_absorb_slots``/``_absorb_spec``/``_args_tok``——拉取/回放语义
# 不同构（fid/gen 界、ws 计入消费位），不做强行统一。


class _WSpec(NamedTuple):
    r"""归一走参元——三字母表（slot/``ArgSpec``/gullet ``Arg``）的公共槽型。

    ``kind``：``star``=``*`` 可选修饰、``opt``=``[..]`` 可选组、``mand``=
    ``{..}`` 强制组、``egrp``=``{..}``|``[..]`` 任选强制组（slot ``e``/
    hyperref 首参形）、``name``=cs 单 token 或组（``n`` 裸名参）、``marg``=
    ``m``/``v``（组或单 token、cs 止）、``bsbs``=``\\`` 的 ``[dimen]``
    （内容闸）、``accent``=``\c{c}`` 单参、``test``=``t`` 测试字符、
    ``dpair``=``d/D/r/R`` 定界对、``embell``=``e{^_}`` 逐枚修饰参、
    ``dseq``=滑窗定界参、``ugroup``=``#{`` 读到 ``lbrace`` 不消费、
    ``zero``=零宽位。
    """

    kind: str
    ws: bool = True  # 前置 space 跳读——slot ``s``/``_grp_call_end`` ``*`` 唯 False
    req: bool = False  # ``dpair`` r/R 强制位：开符失配即整走终止（d/D/槽 d 过槽）
    single_ok: bool = True  # ``marg`` 单 token 参闸（主流 ``allow_single_token``）
    role: str = "skip"  # ``text``/``opt-text`` → 不消费停界（主流回吐同位）
    env: str | None = None  # ``opt``/``dpair`` 的 ``env_opt_is_format`` 闸
    cont_ok: bool = (
        False  # 组未闭 → ``_grp_open_tail`` 跨界续扫态（spec_walk/ka-``o`` 面）
    )
    no_cs: bool = False  # ``test`` 的 cs 禁配——slot ``tC`` 有、``_grp_spec_args_end`` 无（原判差保留）
    open_c: str = ""
    close_c: str = ""
    test_c: str = ""
    e_chars: tuple[str, ...] = ()  # ``embell`` 修饰符表（``e{^_}`` 的逐枚序）
    delim_toks: tuple[Tok, ...] = ()  # ``dseq`` 滑窗目标列（gullet ``Arg.delim`` 原样）


class _WalkRes(NamedTuple):
    r"""``_walk_spec_toks`` 走参结果——三列扫面各自投影自身约定。"""

    end: int  # 实消费后界
    cand: list[
        tuple[int, int, int]
    ]  # (实参序, ``{``/``[`` 位, 闭后位)——``opt``/``marg``/``bsbs`` 组参
    rem: int | None  # toks 走尽/真跨界时未完元下标；``None`` = 走完或失配终止
    cont: (
        tuple | None
    )  # 跨界续扫态 ``("grp",族,残深)``/``("delim",尾列)``/``("e-arg",)``
    e_rest: tuple[str, ...] | None  # ``embell`` 走尽残符列（``_PendRem`` ``e`` 残件料）


_SLOT_ELEMS: dict[tuple[str, bool], _WSpec] = {}


def _slot_elem(s: str, *, cont_ok: bool = False) -> _WSpec:  # noqa: C901 — 槽字母各一分支，平铺即映射表
    r"""待绑参槽字母 → ``_WSpec``（上方槽形表的归一投影；``(槽, cont_ok)`` 缓存）。

    ``cont_ok`` 只给 ``_grp_spec_walk`` 的 ka-``o`` 槽——``[`` 组未闭承
    ``_grp_open_tail`` 跨界续收态；``_slots_walk_toks`` 面未闭即终止。
    """
    key = (s, cont_ok)
    el = _SLOT_ELEMS.get(key)
    if el is None:
        if s == "s":
            el = _WSpec("star", ws=False)
        elif s == "o":
            el = _WSpec("opt", cont_ok=cont_ok)
        elif s == "b":
            el = _WSpec("bsbs")
        elif s == "m":
            el = _WSpec("mand", cont_ok=cont_ok)
        elif s == "n":
            el = _WSpec("name")
        elif s == "e":
            el = _WSpec("egrp", cont_ok=cont_ok)
        elif s == "a":
            el = _WSpec("accent")
        elif s.startswith("d") and len(s) == _SLOT_PAIR_LEN:
            el = _WSpec("dpair", open_c=s[1], close_c=s[2])
        elif s.startswith("t") and len(s) == _SLOT_TEST_LEN:
            el = _WSpec("test", test_c=s[1], no_cs=True)
        else:
            el = _WSpec("zero")  # 未识槽字母——保守零宽（不产生消费）
        _SLOT_ELEMS[key] = el
    return el


def _aspec_elem(  # noqa: PLR0911 — 字母各一分支，平铺即映射表
    s: ArgSpec, role: str, env: str | None, *, single_ok: bool
) -> _WSpec:
    r"""``ArgSpec`` → ``_WSpec``（``_grp_spec_args_end`` 归一投影）。

    ``e``/``b``/``u``/``g``/无 delim 形 → ``zero``——组内不消费的原判
    （这些字母只在 ``_args_tok`` 流侧有对价）。
    """
    k = s.kind
    if k in ("m", "v"):
        return _WSpec("marg", single_ok=single_ok, role=role)
    if k == "n":
        return _WSpec("name", role=role)
    if k in ("o", "O"):
        return _WSpec("opt", role=role, env=env)
    if k == "s":
        return _WSpec("star")
    if k == "t" and s.delim:
        return _WSpec("test", test_c=s.delim[0])
    if k in ("d", "D", "r", "R") and s.delim:
        return _WSpec(
            "dpair",
            req=k in ("r", "R"),
            open_c=s.delim[0],
            close_c=s.delim[-1],
            role=role,
            env=env if s.delim != "<>" else None,  # ``d<>`` 叠层恒版式——原判豁免
        )
    return _WSpec("zero")


def _gspec_elem(a: Arg) -> _WSpec:  # noqa: PLR0911 — 字母各一分支，平铺即映射表
    r"""Gullet ``Arg`` → ``_WSpec``（``_grp_spec_walk`` 归一投影）。

    ``literal_match``/``eq``/空 delim/``brace_after`` 形 → ``zero``。
    ``m``/``o`` 组未闭承 ``_grp_open_tail`` 跨界续收态（``cont_ok``）。
    """
    k = a.kind
    if k == "m":
        return _WSpec("marg", cont_ok=True)
    if k == "o":
        return _WSpec("opt", cont_ok=True)
    if k == "star":
        return _WSpec("star")
    if k == "e" and a.delim:
        return _WSpec("embell", e_chars=tuple(dict.fromkeys(d.text for d in a.delim)))
    if k == "delim" and a.delim:
        return _WSpec("dseq", delim_toks=tuple(a.delim))
    if k == "until_group":
        return _WSpec("ugroup")
    return _WSpec("zero")


def _env_ph_type(
    env: str, ae: ArgspecEntry | None = None, reg: EnvDef | None = None
) -> PhType | None:
    r"""Env 名 → 保护 ``PhType``（math/verbatim/protected 三族分类单源）。

    ``_group_surface``/``_handle_env_begin`` 共用——三族集合两两不相交，
    判定序无关；``ae.body_role``/``reg.body_role`` 分别是 argspec env 条目
    与用户 ``\newenvironment`` 登记的同名分类（verbatim/math/protect 逐项
    对映）。族表名优先——body_role 不覆盖既有族表分类。
    """
    roles = (
        ae.body_role if ae is not None else "",
        reg.body_role if reg is not None else "",
    )
    if env in VERBATIM_ENVS or "verbatim" in roles:
        return PhType.VERB
    if env in MATH_ENVS or "math" in roles:
        return PhType.MATH
    if env in PROTECTED_ENVS or "protect" in roles:
        return PhType.ENV
    return None


def _env_mand_count(env: str, reg: object | None) -> int:
    r"""``\begin`` 尾参强制 ``{m}`` 数：``ENV_MANDATORY_ARG`` ∪ 登记 ``spec`` 的 ``m`` 槽数。"""
    mand = 1 if env in ENV_MANDATORY_ARG else 0
    if reg is not None:
        mand = max(
            mand,
            sum(1 for a in getattr(reg, "spec", ()) if a.kind == "m"),
        )
    return mand


def _scan_envtag(
    pull: Callable[[], Tok | None], surf: Callable[[Tok], str]
) -> tuple[str, Tok] | None:
    r"""``{name}`` 组扫描单源——``_env_name``（流侧）/``_grp_envtag``（组内）双本归一。

    ``pull`` 取下一枚 token（流侧 ``src.read`` 版须同步记 consumed，组内
    为下标游标）；``surf`` 即 ``_tok_surface``。前扫跨 space 与
    ``eol_par``（断行 env tag 收名），须 ``lbrace`` 起头；名内
    ``eol_par``/EOF 即失败（``None``——``pull`` 侧已拉 token 由调用方
    按自身账本回放）。名内花括号按深度配对；名取 ``strip`` 后串
    （主流 ``_env_name`` 原判——组内对价同步收 strip 口径）。
    """
    open_t = pull()
    while open_t is not None and open_t.kind in ("space", "eol_par"):
        open_t = pull()
    if open_t is None or open_t.kind != "lbrace":
        return None
    depth = 1
    parts: list[str] = []
    while True:
        x = pull()
        if x is None:
            return None
        if x.kind == "eol_par":
            return None
        if x.kind == "lbrace":
            depth += 1
        elif x.kind == "rbrace":
            depth -= 1
            if depth == 0:
                return "".join(parts).strip(), x
        parts.append(surf(x))


# ------------------------------------------------------------- 散文参门控
# 调用点散文参判定的单源管线：流侧 ``_opaque_arg_prose``（``file_texts``
# 切片喂 ``_prose_text_hit``）、组内 ``_prose_arg_hit``/``_grp_opaque_args``
# （``_grp_surfs`` join 喂同一管线）、``_grp_arg_prose``（token 级重建文本
# 直喂 ``_prose_word_hit``）三面共享本节判据。

# ``{key=val,..}``/``{flag,key=..}`` 起头的 keyval 组形状——键名字符面取宽
# （字母数字 ``_@*.-``），逗号前缀只收裸键位，``{散文}``/``{key 散文}`` 不中。
_KEYVAL_GROUP_RX = re.compile(r"\s*(?:[\w@*.\-]+[ \t]*,[ \t]*)*[\w@*.\-]+[ \t]*=")

# 逗号分隔机读名单形状——``\usetikzlibrary{arrows, automata, backgrounds,
# calendar}``/``\includeonly{ch1, ch2}``/``\bibliography{r1.bib, r2.bib}`` 类
# 标识符/文件名/路径列：≥4 连词判据会被 ``a, b, c, d`` 误判成散文，抠出
# 翻译会把库名/包名/文件名译断。纯名单槽位逐项 ``[\w@*.\-/]+`` 逗号相连
# 才收——真散文词间缺逗号即不中（``{word, word, word}`` 散文罕见，宁漏
# 不译名单）。
_COMMA_LIST_RX = re.compile(r"\s*[\w@*.\-/]+\s*(?:,\s*[\w@*.\-/]+\s*)*,?\s*")

# ``{..}`` 组判形前的 ``%`` 注释剥离——keyval/名单组常以注释行起头
# （``\lstdefinelanguage{lean}{\n% c\nmathescape=false,..}``），裸套
# ``_KEYVAL_GROUP_RX``/``_COMMA_LIST_RX`` 在 ``%`` 处即断 → 组判成散文
# → 键位译成 ``这是译文`` → ``Package keyval Error``（2105.00041
# lstlean.tex 实证）。``\%`` 转义不剥。
_KV_COMMENT_RX = re.compile(r"(?<!\\)%[^\n\r]*")


# 键值/裸键逗号列判形（``_KEYVAL_GROUP_RX`` 的宽口径版）：tikz/pgf 键值列常
# 裸键起头或全裸键——``[rectangle, draw, text width=8em, text centered,
# rounded corners, minimum height=4em]``（2009.03715）、``[draw, -latex]``、
# ``[black!10]``、``[orcid=,email=]``（2410.17963/2403.01255 实证）。逐项
# 逗号切分后：任一项 ``key=`` 形（``text width=8em`` 的 ``width=``、
# ``key =v`` 的空格皆中）即键值列；或全项皆机读键 token——``-latex``
# 箭头名、``blue!50`` 色阶、``/`` 路径键、``.`` 缀名皆收——亦判键值列。
# ``[see Fig. 1]``/``{散文}`` 单项含空格且无 ``=`` 不中；``_KEYVAL_GROUP_RX``
# 锚定形被本判据完全覆盖（首项 ``key=`` 即任一项 ``key=`` 的特例）。
_KEYVAL_ITEM_RX = re.compile(r"[\w@*.\-/!]+[ \t]*=")
_KEY_TOKEN_RX = re.compile(r"[\w@*.\-/!]+")


def _kv_list_shaped(ftext: str, cs: int, ce: int) -> bool:
    r"""``ftext[cs:ce]`` 剥注释后是否键值/裸键逗号列（宽口径）。"""
    items = _KV_COMMENT_RX.sub(" ", ftext[cs:ce]).split(",")
    return any(_KEYVAL_ITEM_RX.search(it) for it in items) or all(
        bool(it.strip()) and _KEY_TOKEN_RX.fullmatch(it.strip()) is not None
        for it in items
    )


# 参内零宽命令整调用剥除——``\index``/``\label`` 不产生可见文本，但其
# ``{..}`` 组在词链判据里当隔墙（``{inflation \index{x} and the epoch}``
# 左右各不到 4 词被误判非散文，W85 实形）。判形前整段剔走让词链连通；
# 抠出后 ``_subscan_render`` 仍照常把 ``\index`` 折 ``[[CMD]]`` 保真。
_ZERO_WIDTH_ARG_RX = re.compile(r"\\(?:index|label)\s*(?:\[[^\]\n]*\]\s*)?\{[^{}]*\}")

# opaque 宏 ``{..}`` 参的调用点散文判据（gullet-at scout 口径）：检测文本先
# 剔 ``%`` 注释与 cs（``\emph`` 类名不计词），再要 ≥4 个 ``[A-Za-z]{2,}``
# 连词（容标点分隔）、非全大写缩写列——``\sortbibitem{KEY}``/``\bibinfo{f}``
# 的 cite-key/字段名参天然不命中，逐参内容判定（参位白名单会断 key 链）。
_OPAQUE_ARG_STRIP_RX = re.compile(r"%[^\n]*|\\[A-Za-z@]+|\\.")
_OPAQUE_ARG_PROSE_RX = re.compile(
    r"[A-Za-z]{2,}(?:[ \t]*[,;:'’\-–—()/&]*[ \t\n]+[A-Za-z]{2,}){3,}"
)
_OPAQUE_ARG_WORD_RX = re.compile(r"[A-Za-z]{2,}")

#: 吞块宏名闸（opaque 臂 + 探针臂同罩）：``\comment{...}`` 按惯例是隐藏批注
#: 宏（comment.sty / 作者自定义 ``\newcommand{\comment}[1]{}``），参内散文
#: 抬进译文面会把源 PDF 本不显示的内部注记印进译文 PDF（W50 语义）。
#: ``todo``/``fixme``/``note`` 不收——todonotes/fixme 包默认内联渲染参数，
#: 误收会把真可见文本藏起来；``comment`` 是唯一不歧义的吞块约定名。
_SWALLOW_ARG_NAMES = frozenset({"comment"})

#: 死文本参名闸（changes 族 W27）：``\deleted``/``\removed`` 参是被删
#: 文本——抠出翻译会把终稿不显示的删改内容印进译文面。与吞块闸不同：
#: 吞块是源文本就隐藏，死文本是修订标记语义下的非终稿内容。
_DEAD_ARG_NAMES = frozenset({"deleted", "removed"})

#: 尾参死文本名闸：``\replaced{新}{旧}`` 首参（新文本）可见可译、
#: 次参起（``{旧}``）是被替换的死文本不译——只放首个实参。
_DEAD_TAIL_NAMES = frozenset({"replaced"})


def _prose_word_hit(text: str) -> bool:
    r"""剔净文本的词链判据：≥4 个 ``[A-Za-z]{2,}`` 连词、非全大写 → 散文。

    ``_grp_arg_prose``（token 级重建文本——cs token 已剔为空白、注释
    在 token 流本无）直喂本判据；文本口径走 ``_prose_text_hit``。
    """
    for mm in _OPAQUE_ARG_PROSE_RX.finditer(text):
        words = _OPAQUE_ARG_WORD_RX.findall(mm.group(0))
        if len(words) >= 4 and not all(  # noqa: PLR2004 - scout 散文判据连词下限
            w == w.upper() for w in words
        ):
            return True
    return False


def _prose_text_hit(text: str) -> bool:
    r"""参内容文本 → 散文判中（形状门 + 词链判据；名闸在 ``_prose_arg_hit``）。

    ``key=`` 起头的 keyval 组、逗号分隔机读名单、裸键起头/全裸键键值列
    （``{rectangle, draw, text width=8em}`` 面）皆是机读槽位——键位/库
    名抬进译文面即断链炸面（``\setkeys`` 同规）；``\index``/``\label``
    零宽调用先剥除不当词链隔墙，剔注释+cs 后过词链判据。
    """
    stripped = _KV_COMMENT_RX.sub(" ", text)
    if _KEYVAL_GROUP_RX.match(stripped) is not None:
        return False  # ``{key=..}`` 组——键位非散文，整参保持 opaque
    if _COMMA_LIST_RX.fullmatch(stripped):
        return False  # 逗号名单（库/包/文件列）——机读槽位不挖
    if _kv_list_shaped(text, 0, len(text)):
        return False  # 裸键起头/全裸键键值列——宽口径键值判形同罩
    text = _ZERO_WIDTH_ARG_RX.sub(" ", text)
    text = _OPAQUE_ARG_STRIP_RX.sub(" ", text)
    return _prose_word_hit(text)


def _prose_arg_hit(name: str, nth: int, text: str) -> bool:
    r"""散文参判定的单源管线（渲染文本口径）——名闸 + 形状门 + 词链判据。

    流侧对价 = ``_opaque_arg_prose``（``file_texts[fid][cs:ce]`` 切片喂同
    管线）；组内 ``text`` = ``_grp_surfs`` join——gen>0 token 无本段字节，
    token 级重建文本走同一判据集。``_SWALLOW_ARG_NAMES``（吞块 W50）/
    ``_DEAD_ARG_NAMES``（被删死文本）整调用不挖；``_DEAD_TAIL_NAMES``
    只放首参——``\replaced{新}{旧}`` 的 ``{旧}`` 是被替换死文本不译。
    """
    if name in _SWALLOW_ARG_NAMES or name in _DEAD_ARG_NAMES:
        return False
    if name in _DEAD_TAIL_NAMES and nth != 0:
        return False
    return _prose_text_hit(text)


#: ``if*`` 界标路径的名/表达式槽组数——etoolbox/boolexpr/biblatex 测试族
#: 的首 N 个 ``{..}`` 是机器槽（toggle/bool/cs/field/比较元），不是散文；
#: 吸收进界标覆盖后 ``{T}{F}`` 支仍留 surface 照译。``\newif`` 旗标
#: （``\ifdraft``/``\ifmmode`` 等）与 ``\ifx`` 比较没有花括号参——不入表。
_COND_GROUP_ARGS = {
    "iftoggle": 1,
    "ifbool": 1,
    "ifboolexpr": 1,
    "ifboolexpe": 1,
    "ifthenelse": 1,
    "ifcsdef": 1,
    "ifcsundef": 1,
    "ifcsempty": 1,
    "ifcsvoid": 1,
    "ifcsmacro": 1,
    "ifstrempty": 1,
    "ifblank": 1,
    "ifnumodd": 1,
    "ifundef": 1,
    "ifdefempty": 1,
    "ifdefvoid": 1,
    "iffieldundef": 1,
    "iflistundef": 1,
    "ifnameundef": 1,
    "ifentrytype": 1,
    "ifentryseen": 1,
    "ifkeyword": 1,
    "ifcategory": 1,
    "ifnodedefined": 1,
    "ifundefined": 1,
    "ifstrequal": 2,
    "ifcsstring": 2,
    "ifdefstring": 2,
    "ifdefequal": 2,
    "ifnumequal": 2,
    "ifnumgreater": 2,
    "ifnumless": 2,
    "ifdimequal": 2,
    "ifdimgreater": 2,
    "ifdimless": 2,
    "ifnumcomp": 3,
    "ifdimcomp": 3,
}


def _pick_cut(s: str, i: int, hard: int) -> int:  # noqa: C901 — 切点优先级链，平铺即 §3.8 规则序
    r"""切点优先级链（§3.8）：``[[X_n]]`` 尾 > 段界 ``\n\n`` > 句读空白 > 硬切。

    返回相对 ``i`` 的切长。硬切兜底：找横跨 ``hard`` 的占位符切到它尾后
    （scanner-audit F7——ph 不腰斩）。``_split_bounds``/``_split_rendered``
    共用（v1 ``_split_core`` 是同源字节版）。
    """
    window = s[i:hard]
    cut = -1
    for m in PH_RX.finditer(window):  # 占位符尾是最安全切点
        cut = m.end()
    if cut <= 0:
        ws = window.rfind("\n\n")
        if ws > 0:
            cut = ws + 2
    if cut <= 0:
        for ch in (". ", "} ", " "):
            ws = window.rfind(ch)
            if ws > CHUNK_MAX // 2:
                cut = ws + len(ch)
                break
    if cut <= 0:
        # 硬切：找横跨 hard 的 token 切到它尾后（scanner-audit F7）
        cut = hard - i
        for m in PH_RX.finditer(s, i):
            if m.start() >= hard:
                break
            if m.end() > hard:
                cut = m.end() - i
                break
    return cut


# ------------------------------------------------------------------ vtex


class _Vtex:
    r"""叙事序虚拟文本：``(fid,a,b)`` 源区间按到达序追加为连续坐标。

    ``parts``/``base`` 只增；``slice(a,b)`` 取 vtex 区间内容。
    """

    def __init__(self) -> None:
        """空文档。"""
        self.parts: list[str] = []
        self.base: list[int] = []  # parts[k] 的 vtex 终点

    def __len__(self) -> int:
        """当前 vtex 总长。"""
        return self.base[-1] if self.base else 0

    def cover(self, text: str) -> Span:
        """追加一段源文本，返回其 vtex 区间。"""
        start = len(self)
        self.parts.append(text)
        self.base.append(start + len(text))
        return Span(start, start + len(text))

    def slice(self, a: int, b: int) -> str:
        """``vtex[a:b]``——跨 part 区间逐段收集。"""
        if b <= a:
            return ""
        k = bisect_left(self.base, a + 1)
        out: list[str] = []
        while k < len(self.parts):
            lo = self.base[k - 1] if k else 0
            hi = self.base[k]
            if lo >= b:
                break
            out.append(self.parts[k][max(a, lo) - lo : min(b, hi) - lo])
            if hi >= b:
                break
            k += 1
        return "".join(out)

    def text(self) -> str:
        """全量物化（``res.vtex`` 语义位）。"""
        return "".join(self.parts)


# ------------------------------------------------------------------ token 源

# 可发起文本 run 的 token kind——gen==0 源 token 专属（展开产物 gen>0 走组路）。
_TEXT_RUN_HEADS = frozenset({"letter", "other", "param", "active"})


class TokenSource(Protocol):
    r"""分段器输入抽象——``Gullet``（顶层展开源）或 ``_ListSource``（in_arg 子扫）。

    拉取契约外还有一层**能力面**：展开源独有 live 栈/宏表/前瞻展开，
    固定回放源以 ``None``/``False``/``(False, None)`` 作答——消费侧按
    本表编程，不做 ``isinstance`` 类型特判。
    """

    # ---- 展开源能力面（_ListSource 恒定缺省） ----
    macros: ScopeMacroTable | None  # 宏表（ListSource=None——查名回落 state.macros）
    pop_seq: int  # 栈弹事件钟（ListSource 恒 0）
    push_seq: int  # 栈压事件钟（ListSource 恒 0）
    unmatched_open: set[tuple[tuple[int, int, int], int]] | None
    """``_collect_group`` 无配对 memo；展开流无界不可 memo → Gullet 恒 ``None``。"""
    eof_pops: bool
    """``read()`` 耗尽是否已弹栈——``True`` 时 ``unread`` 会建 file_id<0 合成源。"""

    # ---- 拉取契约 ----

    def next_expanded(self) -> Tok | None:
        """拉下一枚展开后 token；耗尽 ``None``。"""
        ...

    def read(self) -> Tok | None:
        """原始（不展开）拉取——前瞻/收集用。"""
        ...

    def unread(self, toks: list[Tok]) -> None:
        """回吐前端。"""
        ...

    def skip_past(self, fid: int, end: int) -> bool:
        """``fid`` 源对齐到 ``end``——raw 消费段内 token 残骸剔除；成功 ``True``。"""
        ...

    # ---- scope 回报（§4：分段器驱动宏表/catcode 推弹；回放源无展开态 = no-op）----

    def scope_push(self) -> None:
        """组开回报。"""
        ...

    def scope_pop(self) -> None:
        """组闭回报。"""
        ...

    # ---- 展开源能力面（_ListSource 各臂缺省实现） ----

    def live_inputs(self) -> list[Mouth] | None:
        """Live 输入栈快照（弹栈尾盖/ph 懒采样用）；``None`` = 非展开源。"""
        ...

    def env_sig(self, target: str) -> frozenset:
        """Target env 端点宏签名（墓标作废键）；回放源签名恒空集。"""
        ...

    def input_expand(self, t: Tok) -> tuple[bool, Tok | None]:
        r"""前瞻臂 ``\input`` 族展开 → ``(handled, hit)``；无能力 → ``(False, None)``。"""
        ...

    def text_run_end(self, t: Tok, files: list[str]) -> int | None:
        """gen=0 文本头起的连续 run 末位快扫；不可批 → ``None``。"""
        ...


class _ListSource:
    """in_arg 子扫的 token 列表源（token 已展开，read==next_expanded）。

    ``deque`` 而非 list：大体 env/arg 子扫下 ``pop(0)`` 是 O(n)
    memmove——2410.17998 实测 2.4M 次出队吃掉 22s。
    """

    # ---- ``TokenSource`` 能力面缺省值：固定回放源无展开态 ----
    macros: ScopeMacroTable | None = None
    pop_seq = 0
    push_seq = 0
    eof_pops = False  # 耗尽即真 EOF——``unread`` 回插队首、无合成源问题

    def __init__(self, toks: list[Tok]) -> None:
        """持有待发 token 队列。"""
        self._q = deque(toks)
        # ``_collect_group`` 扫到队尾未配对的 open 位 (pos, gen)：token 列
        # 构造即定（unread 只回放已见 token、skip_past 只删），「无配对」
        # 判终身成立——同 open 的后续探针 O(1) fast-fail，不再 O(尾长) 重扫
        # （2410.17998 实测 145 次失败重扫 = 18.6M/19M token 拉取）。
        self.unmatched_open: set[tuple[tuple[int, int, int], int]] = set()

    def next_expanded(self) -> Tok | None:
        """队首出队。"""
        return self._q.popleft() if self._q else None

    def read(self) -> Tok | None:
        """同 next_expanded（子扫内不再有展开副作用）。"""
        return self.next_expanded()

    def unread(self, toks: list[Tok]) -> None:
        """回插队首（保序）。"""
        self._q.extendleft(reversed(toks))

    def skip_past(self, fid: int, end: int) -> bool:
        r"""丢弃 ``pos`` 完全落在 ``end`` 前的队首 token（raw 消费对齐）。

        ``\verb`` 定界体/verbatim env 体在文件字节上找闭合，其间的
        token 早已展开入队——不剔除会被二次分派（体内 ``\end`` 假命中）。
        对齐总能达成（失配 token 丢弃即齐），恒 ``True``。
        """
        while self._q and self._q[0].pos[0] == fid and self._q[0].pos[2] <= end:
            self._q.popleft()
        return True

    def scope_push(self) -> None:
        """no-op：子扫回放已展开 token，组界不进宏表/catcode。"""

    def scope_pop(self) -> None:
        """no-op：同上。"""

    def live_inputs(self) -> list[Mouth] | None:
        """``None``：回放源无 Mouth 栈（弹栈尾盖/ph 懒采样主扫专属）。"""
        return None

    def env_sig(self, target: str) -> frozenset:
        r"""空集：子扫 token 列固定、宏表在重放内不突变，墓标签名恒自洽。"""
        del target
        return frozenset()

    def input_expand(self, t: Tok) -> tuple[bool, Tok | None]:
        r"""无展开能力：恒 ``(False, None)``——``\input`` cs 按普通体 token 收。"""
        del t
        return False, None

    def text_run_end(self, t: Tok, files: list[str]) -> int | None:
        r"""Deque 队首 gen==0、``pos`` 严格相接的文本 token 出队合并 → run 末位。

        space 仅作夹心项——原字节须恒 ``" "``（``\t`` 等的 surface 渲染不同）
        且后继须为相接文本头（run 以 ws 收尾会破 ``_slice_items`` lead/trail
        strip——item 粒度剥不进内部）。无后继可并 → ``None``。
        """
        fid, _a, end = t.pos
        q = self._q
        kinds = _TEXT_RUN_HEADS | {"space"}
        i, n = 0, len(q)
        while i < n:
            nxt = q[i]
            if (
                nxt.gen != 0
                or nxt.kind not in kinds
                or nxt.pos[0] != fid
                or nxt.pos[1] != end
            ):
                break
            if nxt.kind == "space":
                n2 = q[i + 1] if i + 1 < n else None
                if (
                    files[fid][nxt.pos[1] : nxt.pos[2]] != " "
                    or n2 is None
                    or n2.gen != 0
                    or n2.kind not in _TEXT_RUN_HEADS
                    or n2.pos[0] != fid
                    or n2.pos[1] != nxt.pos[2]
                ):
                    break
            end = nxt.pos[2]
            i += 1
        for _ in range(i):
            q.popleft()
        return end if end > t.pos[2] else None


def _pull_cursor(
    src: TokenSource, fid: int, pulled: list[Tok], committed: Callable[[], int]
) -> tuple[Callable[[Tok | None], None], Callable[[], Tok | None]]:
    r"""流侧拉参游标 ``(unpull, peek)`` 闭包对——``_absorb_slots``/``_absorb_spec`` 共享。

    ``pulled`` = 已拉 token 全列，``committed()`` 取当前提交水位（调用方传
    ``lambda: committed`` 活引用——水位随消费推进须逐次取新值，快照即
    死数）。``unpull`` 把未提交尾段（可选 ``x`` 附尾）``unread`` 回放并
    截断；``peek`` 跳 space 入账，界 token（``eol_par``/``gen>0``/异 fid）
    与 EOF 回放不消费、返 ``None``。
    """

    def unpull(x: Tok | None = None) -> None:
        tail = pulled[committed() :]
        if x is not None:
            tail = [*tail, x]
        if tail:
            src.unread(tail)
        del pulled[committed() :]

    def peek() -> Tok | None:
        while True:
            x = src.read()
            if x is None:
                return None
            if x.kind == "space":
                pulled.append(x)
                continue
            if x.kind == "eol_par" or x.gen > 0 or x.pos[0] != fid:
                src.unread([x])
                return None
            return x

    return unpull, peek


# ------------------------------------------------------------------ segmenter


@dataclass(slots=True)
class _RunItem:
    """run 双轨项：surface 进译文面，ident 进 identity 面。"""

    surface: str
    ident: str
    vstart: int  # 本项覆盖的 vtex 区间起点（ph 项 = token 落位）
    vend: int


class _EnvDeadTok(NamedTuple):
    r"""``_find_env_end`` 失败墓标（F12 token 版）：同 target 后续查询免重扫。

    事件位 = 失败扫描 ``collected`` 内的**拉取序号**（seq——天然跨 fid
    全序；不用源侧游标计数器：展开消费/``process_if`` 选支丢弃/unread
    重拉会复用游标槽位，pos 锚才稳定）。查询定位 = 本次 ``\begin`` tag
    首 token 的 ``pos`` 在 ``begin_pos`` 命中（失败扫描到过 EOF，本查询
    tag 必已录；verbatim 跳读区内的除外——未录即落正常扫描）。盈余判据
    ``S(seq)`` 与 v1 ``_EnvDead`` 同式；命中后按 ``end_tag`` 文件区间
    ``(fid, tag_start, tag_end)`` 回放拉取（end_ret 的 token 版）。
    """

    sig: frozenset  # target 端点宏签名（scope 链快照——迟到 \def 即废标）
    begins: list[int]  # \begin{target}/env_begin 宏事件 seq
    begin_pos: list[tuple[int, int, int]]  # 各事件首 token pos（查询锚）
    bidx: dict[tuple[int, int, int], int]  # begin_pos → begins 下标
    ends: list[int]  # \end{target}/env_end 宏事件 seq
    end_tag: list[tuple[int, int, int]]  # (fid, tag_start, tag_end) 回放界
    s_end: list[int]  # S(ends[k]) = bisect_left(begins, ends[k]) - k


@dataclass(slots=True)
class _ArgTok:
    """token 版参数区间记录：content/full 的文件区间 + 去括号内容 token。

    ``all_toks`` = 本参数消费的全部 token（含括号/定界符）——调用方放弃
    参数路径时整体 ``unread`` 回放（字节版 ``pos`` 不前进的等价物）。
    缺省可选参 = 零宽占位（``fs==fe``，``all_toks`` 空），保 spec 位序。
    """

    fid: int
    cs: int  # content 起点（去括号）
    ce: int
    fs: int  # full 起点（含括号；单 token 参数 fs==cs 且 fe==ce）
    fe: int
    toks: list[Tok] = field(default_factory=list)  # 去括号内容 token
    all_toks: list[Tok] = field(default_factory=list)
    spec: ArgSpec | None = None

    @classmethod
    def group(  # noqa: PLR0913, PLR0917 — 组参记录构造面（fid/开闭符/内体/回吐/spec）六件原位
        cls,
        fid: int,
        open_t: Tok,
        closer: Tok,
        inner: list[Tok],
        pulled: list[Tok],
        spec: ArgSpec,
    ) -> _ArgTok:
        r"""组参记录：content 去括号区间、full 含括号、``all_toks`` 含前后 ws+括号。"""
        return cls(
            fid,
            open_t.pos[2],
            closer.pos[1],
            open_t.pos[1],
            closer.pos[2],
            inner,
            [*pulled, open_t, *inner, closer],
            spec,
        )

    @classmethod
    def single(cls, fid: int, x: Tok, pulled: list[Tok], spec: ArgSpec) -> _ArgTok:
        r"""单 token 参记录：``fs==cs``/``fe==ce``，``all_toks`` 含前置 ws。"""
        return cls(fid, x.pos[1], x.pos[2], x.pos[1], x.pos[2], [x], [*pulled, x], spec)

    @classmethod
    def empty(cls, fid: int, end: int, spec: ArgSpec) -> _ArgTok:
        r"""零宽占位参记录：可选参缺席，``fs==fe`` 占 spec 位序。"""
        return cls(fid, end, end, end, end, spec=spec)


def _verb_delim_tok(t: Tok) -> bool:
    r"""``\verb``/``\url`` 定界 token 判据（主版 verbatim 支三面镜像同判据）。

    cs token 恒可（其定界字符即 ``\``）；其余须单字符、非字母数字、不在
    ``" \t\n\r%{}[]"`` 排除集。
    """
    return t.kind == "cs" or (
        len(t.text) == 1 and not t.text.isalnum() and t.text not in " \t\n\r%{}[]"
    )


def _doc_begin_of(tex0: str) -> int:
    r"""fid-0 ``\\begin{document}`` 的 ``\\begin`` 起点（v1 mask 视图双门同规则）。"""
    masked = mask_tex(tex0)
    mdoc = BEGIN_DOC_RX.search(masked)
    mpream = DOCCLASS_RX.search(masked)
    return mdoc.start() if (mpream and mdoc) else -1
