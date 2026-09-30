r"""命令族常量表（纯数据，零逻辑）。

原型 ``miniscanner.py`` 常量区的扶正搬迁（含 discard 修正后的终值），
外加重写新增表：``ARG_TRANSPARENT_ENVS`` / ``CHUNK_ARG_SPEC`` /
``\\if`` 两档分族 / 回压常数。
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources

# 三常量 = 兼容再出口：定义已上归 model 数据层
# （``ARG_TRANSPARENT_ENVS`` 为 repair_l2/segmenter 旧调用面保持）。
from texlate.latex.model import (  # noqa: F401
    ARG_TRANSPARENT_ENVS,
    OPT_FMT_CHARS,
    OPT_POS_LETTERS,
    ArgSpec,
    ArgspecEntry,
)
from texlate.textutil import DEAD_ENVS as _DEAD_ENVS
from texlate.textutil import VERBATIM_ENVS as _VERBATIM_ENVS

# ---------------------------------------------------------------- 阈值

CHUNK_MIN = 20  # flush_run 可译性阈值（去命令/非字母后字符数）
CHUNK_MAX = (
    4000  # 原子 chunk 上限（超阈值二次切分，docs/spec/latex-pipeline.md 硬要求）
)
BUDGET = 100_000  # 每文档展开步数上限（docs/spec/latex-pipeline.md）
MAX_GEN = 32  # 子扫描/展开代数上限（正常宏嵌套 ≤4 代，8 倍余量）
MAX_INPUTS = 8  # \\input 展平深度上限

# ---------------------------------------------------------------- 环境族

# 数学环境族 → [[MATH_n]]（含 * 变体）
MATH_ENVS = {
    "equation",
    "align",
    "gather",
    "multline",
    "flalign",
    "alignat",
    "eqnarray",
    "subequations",
    "IEEEeqnarray",
    "dmath",
    "empheq",
    "math",
    "displaymath",
    "cases",
    "split",
    "gathered",
    "aligned",
    "alignedat",
    "array",
    "matrix",
    "pmatrix",
    "bmatrix",
    "vmatrix",
    "Bmatrix",
    "smallmatrix",
    "equationarray",
    "xxalignat",
}
MATH_ENVS |= {e + "*" for e in list(MATH_ENVS)}

# 逐字环境：整体跳过，% 不是注释，内部不挖 caption
# 名单单源在 texlate.textutil（逐字族 ∪ 失活族——对 scanner 都是不透体）
VERBATIM_ENVS = set(_VERBATIM_ENVS) | set(_DEAD_ENVS)

# 保护环境：整段 → [[ENV_n]]，但内部递归挖 \caption/\footnote 为 chunk
PROTECTED_ENVS = {
    "figure",
    "figure*",
    "table",
    "table*",
    "tabular",
    "tabularx",
    "tabulary",
    "longtable",
    "sidewaystable",
    "wraptable",
    "wrapfigure",
    "algorithm",
    "algorithm2e",
    "algorithmic",
    "algorithmicx",
    "tikzpicture",
    "pgfpicture",
    "picture",
    "pspicture",
    "epic",
    "eepic",
    "labellist",  # pinlabel ``\begin{labellist}`` env 形（cs 对形见 PAIR_BLOCK_CMDS）
}

# \begin 后要吞掉强制 {arg} 的环境（宽/格式参数，非文本）
ENV_MANDATORY_ARG = {
    "minipage",
    "parbox",
    "tabular",
    "tabularx",
    "tabulary",
    "array",
    "list",
    "thebibliography",
    "subfigure",
    "wrapfigure",
    "wraptable",
}

# ---------------------------------------------------------------- 命令族

# 参数挖为独立 chunk 的命令（不受 20 字符阈值限制）
CHUNK_ARG_NAMES = {
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "subparagraph",
    "chapter",
    "part",
    "sect",
    "subsect",  # ptptex 旧式
    "caption",
    "subcaption",
    "captionof",
    "tablecaption",  # aastex deluxetable/planotable 标题（保护环境内挖掘面）
    "tablenotetext",  # aastex 表注 ``{mark}{text}``——note 文可译
    "tablecomments",  # aastex 表尾注 ``{text}``
    "pinlabel",  # pinlabel ``\pinlabel {tex} [pos] at x y`` 标签文
    "title",
    "subtitle",
    "thanks",
    "footnote",
    "footnotetext",
    "abst",
    "keywords",
}

# chunk-arg 命令的参数形状：name → (argspec 串, 可译参数下标)。
# 未登记默认 ("om", 1) = [opt]?{arg}（原型行为）。
CHUNK_ARG_SPEC: dict[str, tuple[str, int]] = {
    "captionof": ("mom", 2),  # \captionof{type}[lof]{text}
    # title/subtitle/thanks/abst/keywords：``"m"`` 会把 ``[opt]`` 短标题
    # 当真参数、``{长标题}`` 连花括号落正文（scanner-audit F2，corpus 6.4%
    # 命中——acmart/sigconf ``\title[短]{长}`` 是标准用法）→ ``"om",1``。
    "title": ("om", 1),
    "subtitle": ("om", 1),
    "thanks": ("om", 1),
    "abst": ("om", 1),
    "keywords": ("om", 1),
    "footnote": ("om", 1),
    "footnotetext": ("om", 1),
    "caption": ("om", 1),
    "subcaption": ("om", 1),
    # ``\tablenotetext{a}{note}``：mark 参随前缀进字面段，{note} 可译
    "tablenotetext": ("mm", 1),
    # ``\pinlabel {tex} [pos] at x y``：只拉 ``{tex}``——``[pos]``/``at x y``
    # 留流内（labellist 块内随 ENV 体保护；``mo`` 会拉出 ``[ ]`` 却不覆盖
    # 成 identity 洞——可译参必须是消费位序的最后一个参）
    "pinlabel": ("m", 0),
    "tablecomments": ("m", 0),
}

# 整块保护命令（\author{..} 等 → [[AUTHOR_n]]）
PROTECT_BLOCK_NAMES = {
    "author",
    "inst",
    "address",
    "affiliation",
    "date",
    "markboth",
    "markright",
    "preprintnumber",
    "recdate",
    "publishedin",
    "institute",
    "email",
    "orcid",
}

# cite/ref 两族（词族匹配见 dispatch_cmd 第 6/7 行）
CITE_NAMES = {
    "cite",
    "citep",
    "citet",
    "citealp",
    "citealt",
    "citeauthor",
    "citeyear",
    "citeyearpar",
    "citetext",
    "citeonline",
    "parencite",
    "textcite",
    "footcite",
    "smartcite",
    "supercite",
    "autocite",
    "fullcite",
    "shortcite",
    "citeN",
    "citeasnoun",
    "citenum",
    "nocite",
    "upcite",
    "citeyearnp",
}
REF_NAMES = {
    "ref",
    "eqref",
    "autoref",
    "cref",
    "Cref",
    "crefrange",
    "cpageref",
    "pageref",
    "nameref",
    "vref",
    "vpageref",
    "fref",
    "Fref",
    "subref",
    "labelcref",
    "labelpageref",
}
PROTECT_NAMES = {
    "label",
    "url",
    "includegraphics",
    "bibliography",
    "bibliographystyle",
    "index",
    "gls",
    "Gls",
    "doi",
    "path",
    "includepdf",
    "bibitem",
    "inputminted",
    "lstinputlisting",
    "verbatiminput",
}

# 透明命令：参数内联扫描（inner text 进入当前 run/chunk）
TRANSPARENT_NAMES = {
    "emph",
    "textbf",
    "textit",
    "textsc",
    "textsl",
    "textsf",
    "texttt",
    "textrm",
    "textmd",
    "textup",
    "textnormal",
    "underline",
    "mbox",
    "hbox",
    "fbox",
    "makebox",
    "framebox",
    "textcolor",
    "colorbox",
    "hl",
    "sout",
    "uline",
    "uwave",
    "noindent",
    "footnotemark",
}

# 行级字面命令：文本 run 的硬边界，本体逐字保留
BOUNDARY_NAMES = {
    "item",
    "maketitle",
    "centering",
    "centerline",
    "hline",
    "toprule",
    "midrule",
    "bottomrule",
    "cline",
    "cmidrule",
    "newpage",
    "clearpage",
    "cleardoublepage",
    "pagebreak",
    "linebreak",
    "nopagebreak",
    "tableofcontents",
    "listoffigures",
    "listoftables",
    "appendix",
    "vspace",
    "hspace",
    "vfill",
    "hfill",
    "vskip",
    "hskip",
    "smallskip",
    "medskip",
    "bigskip",
    "indent",
    "par",
    "newline",
    "columnbreak",
    "balance",
    "onecolumn",
    "twocolumn",
    "newcounter",
    "setcounter",
    "addtocounter",
    # 寄存器声明原语：``\newskip\footskip`` 裸 cs 名参不收则下一个
    # ``\footskip14pt`` 的首枚 ``\footskip`` 被当操作数吃掉、``14pt``
    # 孤悬漏单位字母（hep-th/9703214:768 实证）。``\newif`` 由 gullet
    # 登记（IfSetter）不在此列。
    "newskip",
    "newdimen",
    "newcount",
    "newbox",
    "newtoks",
    "newmuskip",
    "newinsert",
    "newlanguage",
    "newfam",
    "newhelp",
    "newread",
    "newwrite",
    "setlength",
    "addtolength",
    "settowidth",
    "settoheight",
    "settodepth",
    "setstretch",
    "pagestyle",
    "thispagestyle",
    "pagenumbering",
    "makeatletter",
    "makeatother",
    "frontmatter",
    "mainmatter",
    "backmatter",
    "documentclass",
    "documentstyle",
    "usepackage",
    "RequirePackage",
    "newtheorem",
}

# 零参/单字符安全字面命令（行内，不破 run）：重音、符号、品牌名
ACCENT_CHARS = set("'`^\"~=.uvHrtcdbkz")
INLINE_LITERAL_CMDS = {
    "LaTeX",
    "TeX",
    "LaTeXe",
    "today",
    "quad",
    "qquad",
    "ldots",
    "dots",
    "dotsb",
    "dotsc",
    "dotsm",
    "textasciitilde",
    "textasciicircum",
    "textbackslash",
    "textdegree",
    "dag",
    "dagger",
    "ddag",
    "ddagger",
    "S",
    "P",
    "copyright",
    "pounds",
    "aa",
    "AA",
    "ae",
    "AE",
    "oe",
    "OE",
    "o",
    "O",
    "l",
    "L",
    "ss",
    "i",
    "j",
    "enspace",
    "thinspace",
    "negthinspace",
    "enskip",
    "relax",
    "textquoteright",
}

# 旧式 2.09 字体开关：无参，行内字面
FONT_SWITCHES = {
    "rm",
    "bf",
    "it",
    "sl",
    "sf",
    "tt",
    "sc",
    "em",
    "cal",
    "mit",
    "tiny",
    "scriptsize",
    "footnotesize",
    "small",
    "normalsize",
    "large",
    "Large",
    "LARGE",
    "huge",
    "Huge",
    "HUGE",
    "normalfont",
    "bfseries",
    "mdseries",
    "itshape",
    "slshape",
    "scshape",
    "upshape",
    "ttfamily",
    "sffamily",
    "rmfamily",
}

# 定义命令（分派表第 2 行；整段 LITERAL + 登记宏表）
DEF_NAMES = {
    "newcommand",
    "renewcommand",
    "providecommand",
    "def",
    "gdef",
    "edef",
    "xdef",
    "NewDocumentCommand",
    "RenewDocumentCommand",
    "ProvideDocumentCommand",
    "DeclareDocumentCommand",
    "DeclareMathOperator",
    "newenvironment",
    "renewenvironment",
}

# \input 展平触发面（docs/spec/latex-pipeline.md，flatten.py 消费）
INPUT_CMDS = {
    "input",
    "@input",  # \makeatletter 下 \@input 内部形（gullet catcode 路径）
    "include",
    "InputIfFileExists",
    "subfile",
    "import",
    "subimport",
    "includestandalone",
    "CatchFileBetweenTags",
}

# ---------------------------------------------------------------- \if 两档

COND_RX = re.compile(r"^(if[a-zA-Z@]*|else|fi|or)$")

# 恒值 \if 族（可求值，docs/spec/latex-pipeline.md）
# 真值以 plasTeX 为准（Primitives.py:247-258 硬编码 ifvmode=False/
# ifhmode=True——展开语境恒按"正在水平排版"处理）；此前写反会让
# 顶层 \ifhmode/\ifvmode 选中死分支进 chunk。
IF_CONST_FALSE = {"ifeof", "ifinner", "ifvoid", "ifhbox", "ifvbox"}
IF_CONST = {"ifhmode": True, "ifvmode": False}

# 保护位参数启发：#i 落在这些命令参数位 → 该位 [[KEY]]
PROTECTED_PARAM_CMDS = CITE_NAMES | REF_NAMES | {"label", "url", "includegraphics"}

_WS_CHARS = " \t\n"

# ---------------------------------------------------------------- 扫描层共享表

# scan 层登记的 \input 触发面（gullet 未解析成功时记 inputs[]）。
# 与 ``INPUT_CMDS`` 的差 = ``CatchFileBetweenTags``：其形为
# ``\CatchFileBetweenTags\cs{file}{tag}``，只由 gullet ``_do_input``/
# flatten 的 tag 区提取处理；scan 层 ``_handle_input_cs`` 只认
# ``{file}``/import 双参/裸名三形——登记进来会把 ``{file}`` 位读错。
INPUT_SCAN_CMDS = {
    "input",
    "@input",  # 字节层 read_cmd_name 的 \@input 特判形
    "include",
    "InputIfFileExists",
    "subfile",
    "includestandalone",
    "import",
    "subimport",
}

# ``\import{dir}{file}``/``\subimport{dir}{file}`` 双参族——``INPUT_CMDS``/
# ``INPUT_SCAN_CMDS`` 成员中唯二吃两参的名（``{dir}`` 前缀拼 ``{file}``）。
# gullet ``_do_input``、flatten、segmenter 主流/组内四路同款 tuple 的单源；
# segmenter ``grpscan._IMPORT2`` 旧私有名废弃，一律归本表。
IMPORT2_CMDS = ("import", "subimport")

FILENAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
)


def strip_fname_quotes(fname: str) -> str:
    r"""剥一层成对双引号——``"a b.tex"`` → ``a b.tex``。

    web2c 引号文件名约定（``\input{"a b.tex"}``/``\input"a b.tex"``，带空格
    文件名）；latexpand ``$ARGQUOTED`` 同款。不成对的引号按字面名处理。
    """
    if fname.startswith('"') and fname.endswith('"') and len(fname) > 1:
        return fname[1:-1]
    return fname


# cs 对界 DSL 块（非 ``\begin/\end`` 形）：开 cs 名 → 闭 cs 名。
# ``\labellist…\endlabellist``（pinlabel，W29）——体按保护环境走
# ``_env_with_mined`` mined 子扫：``\pinlabel {tex}`` 标签文照挖、
# ``at x y`` 坐标脚手架不外泄进 chunk。闭名 cs 孤现 → ``[[CMD]]``。
PAIR_BLOCK_CMDS: dict[str, str] = {
    "labellist": "endlabellist",
}
PAIR_BLOCK_ALL = frozenset(PAIR_BLOCK_CMDS) | frozenset(PAIR_BLOCK_CMDS.values())

# BOUNDARY 命令的结构尾参表（audit 次要 3）：``\cline{1-2}``/``\vspace*{1em}``
# 这类非文本参消费进 LITERAL 段——否则 ``{1-2}`` 落正文成 chunk 被翻译。
# 只列结构参；``\item[o]`` 的 label、``\newtheorem`` 标题是可译文本不收。
BOUNDARY_TAIL: dict[str, list[ArgSpec]] = {
    "cline": [ArgSpec("m")],
    "cmidrule": [ArgSpec("o"), ArgSpec("d", delim="()"), ArgSpec("m")],
    "toprule": [ArgSpec("o")],
    "midrule": [ArgSpec("o")],
    "bottomrule": [ArgSpec("o")],
    "pagebreak": [ArgSpec("o")],
    "linebreak": [ArgSpec("o")],
    "nopagebreak": [ArgSpec("o")],
    "twocolumn": [ArgSpec("o")],
    "vspace": [ArgSpec("s"), ArgSpec("m")],
    "hspace": [ArgSpec("s"), ArgSpec("m")],
    "newcounter": [ArgSpec("m"), ArgSpec("o")],
    "setcounter": [ArgSpec("m"), ArgSpec("m")],
    "addtocounter": [ArgSpec("m"), ArgSpec("m")],
    # 寄存器族首参是裸 cs 名——``n`` 槽直收 cs token 或 {}/[] 组（``m``
    # 不跨 ``\``）；``setcounter``/``addtocounter`` 首参是计数器名留 ``m``
    "setlength": [ArgSpec("n"), ArgSpec("m")],
    "addtolength": [ArgSpec("n"), ArgSpec("m")],
    # ``\newX\cs`` 声明族：裸 cs 名参同 ``setlength`` 首参走 ``n`` 槽
    "newskip": [ArgSpec("n")],
    "newdimen": [ArgSpec("n")],
    "newcount": [ArgSpec("n")],
    "newbox": [ArgSpec("n")],
    "newtoks": [ArgSpec("n")],
    "newmuskip": [ArgSpec("n")],
    "newinsert": [ArgSpec("n")],
    "newlanguage": [ArgSpec("n")],
    "newfam": [ArgSpec("n")],
    "newhelp": [ArgSpec("n")],
    "newread": [ArgSpec("n")],
    "newwrite": [ArgSpec("n")],
    "settowidth": [ArgSpec("n"), ArgSpec("m")],
    "settoheight": [ArgSpec("n"), ArgSpec("m")],
    "settodepth": [ArgSpec("n"), ArgSpec("m")],
    "setstretch": [ArgSpec("m")],
    "pagestyle": [ArgSpec("m")],
    "thispagestyle": [ArgSpec("m")],
    "pagenumbering": [ArgSpec("m")],
    "documentclass": [ArgSpec("o"), ArgSpec("m")],
    "documentstyle": [ArgSpec("o"), ArgSpec("m")],
    "usepackage": [ArgSpec("o"), ArgSpec("m")],
    "RequirePackage": [ArgSpec("o"), ArgSpec("m")],
}

# 裸操作数/赋值形命令的尾参种别（loop1 slots 修复）：``\vskip3pt``、
# ``\hangindent=.5em``、``\vrule width 2pt``、``\font\cs=cmr10 at 12pt``
# 这类非文本槽位在 ``{}`` 组外——BOUNDARY_TAIL 的组参规则与未知命令
# 探针都够不着，单位字母裸进 surface 即被翻译（illegal_unit 主错因）。
# segmenter 按种别做字节/token 尾扫整体保护：
#   "dimen" — ``[=]?<atom> [plus <atom>] [minus <atom>]``（glue/dimen 寄存器
#             与 skip 原语同式——刚性名多收 plus/minus 无害，该形本就非法）；
#   "rule"  — ``\hrule``/``\vrule`` 的 ``width|height|depth <atom>`` 序；
#   "font"  — ``\font\cs=name [at <atom>|scaled <num>]``。
# 表外未知名走 ``_ASSIGN_TAIL_RX`` 通用 ``=<atom>`` 赋值扫——``\foo=2pt``
# 的 ``=2pt`` 在散文语境不可能是文本。
DIMEN_TAIL_KIND: dict[str, str] = {
    # skip/glue 寄存器与原语
    "vskip": "dimen",
    "hskip": "dimen",
    "mskip": "dimen",
    "vglue": "dimen",
    "hglue": "dimen",
    "spaceskip": "dimen",
    "xspaceskip": "dimen",
    "leftskip": "dimen",
    "rightskip": "dimen",
    "topskip": "dimen",
    "lineskip": "dimen",
    "lineskiplimit": "dimen",
    "baselineskip": "dimen",
    "parskip": "dimen",
    "parfillskip": "dimen",
    "smallskipamount": "dimen",
    "medskipamount": "dimen",
    "bigskipamount": "dimen",
    "jot": "dimen",
    "abovedisplayskip": "dimen",
    "belowdisplayskip": "dimen",
    "abovedisplayshortskip": "dimen",
    "belowdisplayshortskip": "dimen",
    # LaTeX length 寄存器（rubber length = skip）
    "itemsep": "dimen",
    "labelsep": "dimen",
    "labelwidth": "dimen",
    "labelindent": "dimen",
    "tabcolsep": "dimen",
    "arraycolsep": "dimen",
    "textfloatsep": "dimen",
    "floatsep": "dimen",
    "intextsep": "dimen",
    "dblfloatsep": "dimen",
    "dbltextfloatsep": "dimen",
    "topsep": "dimen",
    "partopsep": "dimen",
    "parsep": "dimen",
    "columnsep": "dimen",
    # 刚性 dimen 与位移/字号参
    "kern": "dimen",
    "mkern": "dimen",
    "parindent": "dimen",
    "hangindent": "dimen",
    "hsize": "dimen",
    "vsize": "dimen",
    "textwidth": "dimen",
    "textheight": "dimen",
    "linewidth": "dimen",
    "columnwidth": "dimen",
    "mathsurround": "dimen",
    "emergencystretch": "dimen",
    "moveleft": "dimen",
    "moveright": "dimen",
    "raise": "dimen",
    "lower": "dimen",
    "oddsidemargin": "dimen",
    "evensidemargin": "dimen",
    "topmargin": "dimen",
    "headheight": "dimen",
    "headsep": "dimen",
    "footskip": "dimen",
    "marginparwidth": "dimen",
    "marginparsep": "dimen",
    "paperwidth": "dimen",
    "paperheight": "dimen",
    "prevdepth": "dimen",
    "pagegoal": "dimen",
    "hoffset": "dimen",
    "voffset": "dimen",
    # 计数器/罚分/坏度/追踪寄存器——尾参是裸整数无单位（``\hangafter=1``/
    # ``\tolerance 800``/``\hbadness=10000``），通用 ``assign`` 只罩
    # ``=<atom>``；``=N`` 形由 assign 的 count 兜底（表外名同规），本族
    # 额外买无等号形 ``\hangafter 1``（illegal_unit 波 A 簇实证）。
    "hangafter": "count",
    "looseness": "count",
    "tolerance": "count",
    "pretolerance": "count",
    "hbadness": "count",
    "vbadness": "count",
    "badness": "count",
    "mag": "count",
    "spacefactor": "count",
    "interdisplaylinepenalty": "count",
    "interlinepenalty": "count",
    "interlinepenalties": "count",
    "widowpenalty": "count",
    "widowpenalties": "count",
    "clubpenalty": "count",
    "clubpenalties": "count",
    "displaywidowpenalty": "count",
    "displaywidowpenalties": "count",
    "predisplaypenalty": "count",
    "postdisplaypenalty": "count",
    "interfootnotelinepenalty": "count",
    "brokenpenalty": "count",
    "hyphenpenalty": "count",
    "exhyphenpenalty": "count",
    "binoppenalty": "count",
    "relpenalty": "count",
    "linepenalty": "count",
    "adjdemerits": "count",
    "doublehyphendemerits": "count",
    "finalhyphendemerits": "count",
    "floatingpenalty": "count",
    "outputpenalty": "count",
    "insertpenalties": "count",
    "maxdeadcycles": "count",
    "day": "count",
    "month": "count",
    "year": "count",
    "time": "count",
    "tracingmacros": "count",
    "tracingonline": "count",
    "tracingoutput": "count",
    "tracingstats": "count",
    "tracingcommands": "count",
    "tracinglostchars": "count",
    "tracingparagraphs": "count",
    "tracingpages": "count",
    "showboxbreadth": "count",
    "showboxdepth": "count",
    "errorcontextlines": "count",
    "pausing": "count",
    "holdinginserts": "count",
    "globaldefs": "count",
    "escapechar": "count",
    "endlinechar": "count",
    "newlinechar": "count",
    "uchyph": "count",
    "lefthyphenmin": "count",
    "righthyphenmin": "count",
    "delimiterfactor": "count",
    "defaulthyphenchar": "count",
    "defaultskewchar": "count",
    # 算术/寄存器赋值双操作数：``<op><lval>[by|=]<rval>``——``by``/``=``
    # 间隔关键字裸落 surface 即被译（math/9901091 ``\multiply\ione by 10``
    # 5843 errs 实证；``\skewchar\fivmi='77``/``\setbox0=\hbox to3cm``
    # 同构——rvalue 盒原语再叠 ``to|spread`` 尾由 arith 形自带）。
    "advance": "arith",
    "multiply": "arith",
    "divide": "arith",
    "setbox": "arith",
    "count": "arith",
    "dimen": "arith",
    "skip": "arith",
    "muskip": "arith",
    "toks": "arith",
    "chardef": "arith",
    "mathchardef": "arith",
    "countdef": "arith",
    "dimendef": "arith",
    "skipdef": "arith",
    "muskipdef": "arith",
    "toksdef": "arith",
    "skewchar": "arith",
    "hyphenchar": "arith",
    "fontdimen": "arith",
    # 规则与字体声明
    "hrule": "rule",
    "vrule": "rule",
    "font": "font",
}

# 盒规格尾参（``to|spread <dim>``）命令——``\hbox`` 是透明名（体文续扫），
# ``\vbox``/``\vtop``/``\vcenter`` 走未知命令路；四者同享 boxspec 尾扫，
# ``to``/``spread`` 关键字+dimen 不落 surface（hep-th/9703214 ``\hbox
# to\hsize{`` 的 ``to`` 被译实证）。主分派在透明/未知两路前截获。
BOX_TAIL_NAMES = {"hbox", "vbox", "vtop", "vcenter"}

# 头参非文本、尾参可译的透明命令（loop1 slots③）：``\textcolor{red}{text}``
# 的 ``{red}``/``[model]`` 进 [[CMD]]、``{text}`` 留主流——argspec 同名条目
# 是 chunk-arg policy 但 ``textcolor`` 只挂 xcolor 包（文档靠 color/类定义
# 引入时门控失效），族表先行为确定性修正。
#
# graphicx/内核盒族同理且更强：argspec ``chunk-arg`` 的 in_arg 臂把字面
# 参段裸字节并进 run surface（``\multirow{5}{*}{\rotatebox[origin=c]{90}``
# 的 ``[origin=c]`` 进 chunk 被译——2310.16788 实证），本表 in_arg/组内
# 两路都是 spec 驱动 ``[[CMD]]``，确定性盖过签名表。spec 只列到头参为
# 止——其后 ``{text}`` 组随主流可译。``\makebox``/``\framebox`` 的
# picture-mode ``(x,y)`` 参不收：``(`` 前导在散文里撞真括号（picture
# 环境体本就整段保护，不吃这门）。
TRANSPARENT_HEAD_SPEC: dict[str, list[ArgSpec]] = {
    "textcolor": [ArgSpec("o"), ArgSpec("m")],
    "colorbox": [ArgSpec("o"), ArgSpec("m")],
    # \resizebox*{w}{h}{text}（graphicx，* 变体同形）
    "resizebox": [ArgSpec("s"), ArgSpec("m"), ArgSpec("m")],
    # \scalebox{h}[v]{text}
    "scalebox": [ArgSpec("m"), ArgSpec("o")],
    # \rotatebox[origin]{ang}{text}
    "rotatebox": [ArgSpec("o"), ArgSpec("m")],
    # \raisebox{lift}[above][below]{text}
    "raisebox": [ArgSpec("m"), ArgSpec("o"), ArgSpec("o")],
    # \makebox[w][pos]{text} / \framebox[w][pos]{text}
    "makebox": [ArgSpec("o"), ArgSpec("o")],
    "framebox": [ArgSpec("o"), ArgSpec("o")],
    # \parbox[pos][h][ipos]{w}{text}
    "parbox": [ArgSpec("o"), ArgSpec("o"), ArgSpec("o"), ArgSpec("m")],
    # \savebox{cmd}[w][pos]{text} / \sbox{cmd}{text} / \usebox{cmd}
    "savebox": [ArgSpec("m"), ArgSpec("o"), ArgSpec("o")],
    "sbox": [ArgSpec("m")],
    "usebox": [ArgSpec("m")],
    # titlesec/titletoc 族：全结构参无 text 位——spec 驱动三路径全收
    # （BOUNDARY_TAIL 组内/参内路只数 mand 个数，``m o m m m m o`` 交错
    # 签名在那两条路漏尾参）。签名以 titlesec.sty/titletoc.sty 实测为准：
    # titleformat = 星变体 cmd+fmt 两参 / 全形 cmd shape fmt label sep
    # before after。
    "titleformat": [
        ArgSpec("s"),
        ArgSpec("m"),
        ArgSpec("o"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("o"),
    ],
    # \titlespacing*{cmd}{left}{before}{after}[right]（``s``+4×``m``+
    # 尾 ``o``——.sty ``\ttl@spacing@i`` 是四强制参，mission 手抄三参少一）
    "titlespacing": [
        ArgSpec("s"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("o"),
    ],
    # \titlelabel{fmt} / \titleclass{cmd}[super]{class}——``[super]``
    # 在两序都出现过（.sty 读序 opt-在-class-前，文档常写反），双 ``o`` 盖
    "titlelabel": [ArgSpec("m")],
    "titleclass": [ArgSpec("m"), ArgSpec("o"), ArgSpec("m"), ArgSpec("o")],
    # \titlecontents{sec}[left]{above}{num}{nonum}{filler}[below][after]
    "titlecontents": [
        ArgSpec("s"),
        ArgSpec("m"),
        ArgSpec("o"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("m"),
        ArgSpec("o"),
        ArgSpec("o"),
    ],
}

# ---------------------------------------------------------------- argspec.json


@cache
def argspec_tables() -> tuple[dict[str, ArgspecEntry], dict[str, ArgspecEntry]]:
    r"""``data/argspec.json`` → ``(macros, envs)`` 两张 ``name → ArgspecEntry`` 表。

    懒加载 + 进程级缓存（~500KB JSON 只在首个未知 cs 命中时读一次）。
    条目照抄 JSON 字段；``guessed`` = source 含 ``guessed-signature``
    （族规则推断签名，审计可回滚）；``also_in`` 收跨包重名登记。

    包门史话（两 ``argspec_lookup*`` 共用前提）：查表曾按
    ``ScanState.pkgs`` 门控，但 ``pkgs`` 只收**本文件**
    ``\\usepackage``/``\\documentclass``——工程按 ``\\input`` 拆开后
    体文件查不到导言区包名，包门必假阴 → 门控已退役，两侧查表
    均不按包过滤（``pkgs`` 收集端已拆，``ScanState.pkgs`` 只剩
    ClassVar 空集保读口形态——外部测试钉死）。
    """
    raw = resources.files("texlate.latex").joinpath("data/argspec.json")
    data = json.loads(raw.read_text(encoding="utf-8"))
    macros: dict[str, ArgspecEntry] = {}
    envs: dict[str, ArgspecEntry] = {}
    for key, dst in (("macros", macros), ("environments", envs)):
        for name, e in data.get(key, {}).items():
            dst[name] = ArgspecEntry(
                name=name,
                package=e.get("package", ""),
                signature=e.get("signature", ""),
                arg_roles=tuple(e.get("arg_roles", ())),
                policy=e.get("policy", "protect"),
                body_role=e.get("body_role", ""),
                guessed="guessed-signature" in e.get("source", ()),
                also_in=frozenset(e.get("also_in", "").split()),
            )
    return macros, envs


def argspec_lookup(name: str, _pkgs: set[str]) -> ArgspecEntry | None:
    r"""未知控制序列查表——不按包门控（``argspec_lookup_env`` 同规）。

    门控退役史话见 ``argspec_tables``。用户 ``\\newcommand``/``\\def``
    撞名由调用方先短路：主流 ``_handle_unknown_cs`` 仅 ``m is None``
    才查表（``_resolve_macro``
    命中 gullet 宏表即跳过；可展开用户宏 gullet 先行吃掉到不了分段
    器），cite/ref 词族按名先行、签名只决定保护参目。不吃签名会把
    key 参漏成散文送译——``\\crefrange{a}{b}`` 第二参、``\\joref``
    尾四组实证泄漏 → cleveref ``\\cref@resetstack`` 递归炸栈
    （2105.00111）。``text``/``opt-text`` 角色参回吐主流不受影响；
    最坏形态 = 未加载包同名 cs 按签名多吞若干组（有界少译，无腐蚀
    面）。``_pkgs`` 死参——旧门控签名留位（调用面仍传
    ``state.pkgs``），不读。
    """
    return argspec_tables()[0].get(name)


def argspec_lookup_env(name: str, _pkgs: set[str]) -> ArgspecEntry | None:
    r"""``argspec_lookup`` 的环境侧同名物（``\\begin{X}`` 的 X）——不按包门控。

    ``\\begin{X}`` 出现本身即工程已供 X 的证据（X 无内核/恒激活族
    提供方；用户 ``\\newenvironment`` 撞名由调用方 ``_argspec_env``
    的 ``reg`` 先短路，到不了此层）。不吃签名会把 env-name/key 参
    漏成散文送译——thmtools ``restatable`` 实证：
    ``\\begin{restatable}{theorem}{main}`` 的两参进 chunk 被译成
    ``{这是译文}{这是译文}`` → cleveref ``\\cref@resetstack`` 递归炸栈
    （2105.00111）。``text``/``opt-text`` 角色参回吐主流不受影响；
    最坏形态 = 未定义/撞名 env 按签名多吞若干组（有界少译，无腐蚀
    面）。``_pkgs`` 死参——旧门控签名留位（调用面仍传
    ``state.pkgs``），不读。
    """
    return argspec_tables()[1].get(name)


# ---------------------------------------------------------------- 列型前导启发

_COLSPEC_CS_RX = re.compile(r"\\[a-zA-Z@]+\*?|\\.")
#: 剥内层花括号组——``*`` 紧随的 ``{n}`` 是 array-repeat 计数，剥了 ``*``
#: 成孤儿、star 配对永死（``*{2}{p{3cm}}`` 剥 ``{2}`` 后 spec 不再可达）。
_COLSPEC_GROUP_RX = re.compile(r"(?<!\*)\{[^{}]*\}")
#: array-repeat ``*{n}{spec}``：``{spec}`` 组剥空前先解卷——列字母全在
#: 被剥组内会让纯 ``*`` 重复型漏判（``{*{3}{c}|l}`` → ``*|l`` 无列字母）。
#: 解卷只需一份 spec 内容（判型不判展开次数）；``[^{}]*`` 界使内层
#: ``*{m}{…}`` 先匹配、不动点迭代逐层外卷。
_COLSPEC_STAR_RX = re.compile(r"\*\{\d+\}\{([^{}]*)\}")
# 列型字母族：array ``lcrpmb`` + tabularx ``X`` + ragged2e ``LCRJ`` +
# dcolumn ``D`` + siunitx ``Ss`` + array ``wW``；修饰 ``|><@!*`` 与
# dcolumn 数字/标点载荷（``D{,}{.}{2}`` 内组剥空后残留位）。
_COLSPEC_COLS = frozenset("lcrpmbXLCRJDwWs")
_COLSPEC_CHARS = _COLSPEC_COLS | frozenset("|><@!*.,:;-+= \t0123456789")


def looks_like_colspec(content: str) -> bool:
    r"""``{...}`` 参内容是否形似列型前导（``{cc}``/``{>{\raggedright}p{4cm}}`` 族）。

    未注册环境 ``\begin{env}{preamble}`` 的第一参：剥掉 cs 名与内层
    花括号组后只剩列型字符且含至少一个列型字母 → 判列参吃掉；否则
    回吐随主流进 chunk。``*{n}{spec}`` 纯重复型先解卷 spec 再走同判。
    ``{Title}`` 形含表外字母自然落空；``{c}``/``{l}`` 单字母文本参是
    已知误伤面（代价低于列参裸泄，罕见——真 ``tabular`` 族走
    ``ENV_MANDATORY_ARG`` 不经此路）。
    """
    s = _COLSPEC_CS_RX.sub("", content)
    while True:
        # star 解卷优先——同迭代剥组会吃掉刚解出的 spec 组（``*{2}{cl}``
        # 中态），嵌套 ``*{m}{…}`` 须等多一轮才能被 star 看见；
        # ``*{n}`` 的计数组不剥（剥了 ``*`` 成孤儿，star 配对永死）
        s2 = _COLSPEC_STAR_RX.sub(r"\1", s)
        if s2 != s:
            s = s2
            continue
        s3 = _COLSPEC_GROUP_RX.sub("", s)
        if s3 == s:
            break
        s = s3
    s = s.strip()
    if not s or any(c not in _COLSPEC_CHARS for c in s):
        return False
    return any(c in _COLSPEC_COLS for c in s)
