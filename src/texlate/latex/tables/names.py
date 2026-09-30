r"""``latex.tables.names`` — 阈值/环境族/命令族名表（``tables`` god-file 机械拆分叶）。

原型 ``miniscanner.py`` 常量区的扶正搬迁（含 discard 修正后的终值）：
CHUNK/BUDGET/MAX_* 阈值、MATH/VERBATIM/PROTECTED env 族、chunk-arg/
protect-block/cite/ref/protect/transparent/boundary/accent/inline-literal/
font-switch/def/input 命令族名表 + ``CHUNK_ARG_SPEC`` 参数形状表。
model 数据层五名兼容再出口（``ARG_TRANSPARENT_ENVS`` 等）驻本叶。
"""

from __future__ import annotations

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

# chunk-arg 命令的参数形状：name → (argspec 串，可译参数下标)。
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
