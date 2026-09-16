r"""命令族常量表（纯数据，零逻辑）。

spike ``miniscanner.py`` 常量区的扶正搬迁（含 discard 修正后的终值），
外加重写新增表：``ARG_TRANSPARENT_ENVS`` / ``CHUNK_ARG_SPEC`` /
``\\if`` 两档分族 / 回压常数。
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources

from texlate.latex.model import ArgSpec, ArgspecEntry
from texlate.textutil import DEAD_ENVS as _DEAD_ENVS
from texlate.textutil import VERBATIM_ENVS as _VERBATIM_ENVS

# ---------------------------------------------------------------- 阈值

CHUNK_MIN = 20  # flush_run 可译性阈值（去命令/非字母后字符数）
CHUNK_MAX = 4000  # 原子 chunk 上限（超阈值二次切分，docs/07 §3.8 硬要求）
BUDGET = 100_000  # 每文档展开步数上限（docs/07 §8.2）
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
}

# in_arg 下的透明容器环境白名单（纯容器 → begin/end 行 [[ENVTAG]]，
# 内部 item 文本照常挖；其余未知 env in_arg → 整段 [[ENV]]，修泄漏 C2）
ARG_TRANSPARENT_ENVS = {
    "itemize",
    "enumerate",
    "description",
    "center",
    "flushleft",
    "flushright",
    "quote",
    "quotation",
    "verse",
    "abstract",
    "minipage",
    "list",
    "trivlist",
    "sloppypar",
    "document",
}
ARG_TRANSPARENT_ENVS |= {e + "*" for e in list(ARG_TRANSPARENT_ENVS)}

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
    "title",
    "subtitle",
    "thanks",
    "footnote",
    "footnotetext",
    "abst",
    "keywords",
}

# chunk-arg 命令的参数形状：name → (argspec 串, 可译参数下标)。
# 未登记默认 ("om", 1) = [opt]?{arg}（spike 原行为）。
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
    "setlength",
    "addtolength",
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
ACCENT_CHARS = set("'`^\"~=.uvHtcdbkz")
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

# \input 展平触发面（docs/07 §7，flatten.py 消费）
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

# 恒值 \if 族（可求值，docs/07 §8.6）
# 真值以 plasTeX 为准（Primitives.py:247-258 硬编码 ifvmode=False/
# ifhmode=True——展开语境恒按"正在水平排版"处理）；此前写反会让
# 顶层 \ifhmode/\ifvmode 选中死分支进 chunk。
IF_CONST_FALSE = {"ifeof", "ifinner", "ifvoid", "ifhbox", "ifvbox"}
IF_CONST = {"ifhmode": True, "ifvmode": False}

# 保护位参数启发：#i 落在这些命令参数位 → 该位 [[KEY]]
PROTECTED_PARAM_CMDS = CITE_NAMES | REF_NAMES | {"label", "url", "includegraphics"}

_WS_CHARS = " \t\n"

# ---------------------------------------------------------------- 扫描层共享表

# scan 层登记的 \input 触发面（gullet 未解析成功时记 inputs[]）
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

FILENAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
)

OPT_FMT_CHARS = frozenset("=*\\#|!~,()<>:;")  # 版式参特征（kv/装饰/分组）
OPT_POS_LETTERS = frozenset("htbpHTBPclrmb")  # 浮动位 htbp + 列型 lcrmpb

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
    "setlength": [ArgSpec("m"), ArgSpec("m")],
    "addtolength": [ArgSpec("m"), ArgSpec("m")],
    "setstretch": [ArgSpec("m")],
    "pagestyle": [ArgSpec("m")],
    "thispagestyle": [ArgSpec("m")],
    "pagenumbering": [ArgSpec("m")],
    "documentclass": [ArgSpec("o"), ArgSpec("m")],
    "documentstyle": [ArgSpec("o"), ArgSpec("m")],
    "usepackage": [ArgSpec("o"), ArgSpec("m")],
    "RequirePackage": [ArgSpec("o"), ArgSpec("m")],
}

# ---------------------------------------------------------------- argspec.json

# 非真实 ``\usepackage`` 的包名：内核命令 + 合成来源族，无条件激活。
# 真实包名（beamer/exam/hyperref/…）须 ``ScanState.pkgs`` 命中才启用——
# 否则 ``\frame``/``\partlabel`` 这类包私有名会误吃普通文档参数。
ARGSPEC_ALWAYS_PKGS = frozenset(
    {
        "latex2e",
        "manual",
        "miniscanner",
        "math-literal",
        "latex-literal",
        "single-char",
        "parser-primitive",
        "latex-utensils",
    }
)


@cache
def argspec_tables() -> tuple[dict[str, ArgspecEntry], dict[str, ArgspecEntry]]:
    """``data/argspec.json`` → ``(macros, envs)`` 两张 ``name → ArgspecEntry`` 表。

    懒加载 + 进程级缓存（~500KB JSON 只在首个未知 cs 命中时读一次）。
    条目照抄 JSON 字段；``guessed`` = source 含 ``guessed-signature``
    （族规则推断签名，审计可回滚）；``also_in`` 收跨包重名登记。
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


def argspec_lookup(name: str, pkgs: set[str]) -> ArgspecEntry | None:
    r"""未知控制序列查表：``package``/``also_in`` 命中已加载包 ∪ 恒激活族。"""
    e = argspec_tables()[0].get(name)
    if e is None:
        return None
    allowed = pkgs | ARGSPEC_ALWAYS_PKGS
    if e.package in allowed or e.also_in & allowed:
        return e
    return None


def argspec_lookup_env(name: str, pkgs: set[str]) -> ArgspecEntry | None:
    r"""``argspec_lookup`` 的环境侧同名物（``\\begin{X}`` 的 X）。"""
    e = argspec_tables()[1].get(name)
    if e is None:
        return None
    allowed = pkgs | ARGSPEC_ALWAYS_PKGS
    if e.package in allowed or e.also_in & allowed:
        return e
    return None
