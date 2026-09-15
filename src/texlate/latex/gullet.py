r"""Gullet：回压式不动点展开（plasTeX ``TeX.__iter__`` TeX.py:281-340 的移植）。

宏展开的**唯一**发生地：拉取 Mouth 原始 token → 命中宏表/原语则按预编译
spec 读参 → 代入 → 推回流前端（不动点，不 return）。移植位逐条对
``docs/research/latex/expansion-design.md`` §12 表；行为规格 docs/07 §8。

与 plasTeX 的刻意分歧（规格内留档项）：

- ``\def`` 参数文本**定义时**编译为 ``spec``（§5.2）——plasTeX 每次调用重走
  参数文本（``Definition.invoke __init__.py:1177`` 起）；语义等价，省每调用解析。
- 定界参数支持**多 token** 定界序列（``#1 abc`` 的 ``abc`` 整体是 delim）；
  plasTeX 只逐单 token 匹配（``__init__.py:1214``）——多 token 更贴 TeX。
- ``\if`` 两档（§8.6）：可求值 → ``process_if`` 只推回选中支；不可求值 →
  条件按语法消费 + ``\ifX`` 界标 token 直交分段器，**两分支都进**（召回优先）。
  ``\ifhmode/\ifvmode`` 常量取 plasTeX 真值 True/False——``tables.py``
  ``IF_CONST`` 写反了（本文件不消费它）。
- 参数不匹配 → ``raise ArgMismatch`` + 全部已读 token 回吐（§3.5）；
  plasTeX 只 log.info 然后 break 继续（``__init__.py:1226``）——"继续"会
  默吞参数字节，对 splice 模型更危险。
- 三级限制（plasTeX 无任何限制）：``gen>MAX_GEN`` 不再展开 / ``steps>BUDGET``
  全停 / ``inputs>MAX_INPUTS`` 拒压栈。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from texlate.latex.flatten import strip_doc_shell
from texlate.latex.macro_table import (
    body_has_text,
    classify_body,
    protected_param_positions,
)
from texlate.latex.model import MacroKind, ScanWarning
from texlate.latex.mouth import CC_LETTER, CC_OTHER, CatTable, Mouth, Tok
from texlate.latex.tables import (
    BOUNDARY_NAMES,
    BUDGET,
    CHUNK_ARG_NAMES,
    CITE_NAMES,
    DEF_NAMES,
    FONT_SWITCHES,
    INLINE_LITERAL_CMDS,
    INPUT_CMDS,
    MAX_GEN,
    MAX_INPUTS,
    PROTECT_NAMES,
    REF_NAMES,
    TRANSPARENT_NAMES,
)
from texlate.textutil import decode_tex

__all__ = [
    "Alias",
    "Arg",
    "ArgMismatch",
    "EnvDef",
    "Gullet",
    "IfCond",
    "IfSetter",
    "MacroDef",
    "MacroTable",
    "expand_def",
]


# ------------------------------------------------------------------ 表项类型


@dataclass(slots=True)
class Arg:
    """参数槽（``MacroDef.spec`` 项；调用点读取顺序即列表序，§4.1/§8.4）。"""

    kind: str  # 'm'|'o'|'star'|'eq'|'delim'|'until_group'|'literal_match'
    delim: list[Tok] = field(default_factory=list)  # delim/literal_match 目标序列
    default: list[Tok] | None = None  # 'o' 缺省值 token
    open: str = "["  # 'o' 自定界 opener（xparse d<>/g 用）
    close: str = "]"
    char: str = "*"  # 'star'/'eq' 期待字符
    brace_after: bool = False  # `\def\foo#1 abc#{`：delim 命中后仍要求 `{` 回吐


@dataclass(slots=True)
class MacroDef:
    r"""登记宏（``\def``/``\newcommand`` 族统一表示，§4.1）。"""

    name: str
    spec: list[Arg] = field(default_factory=list)
    body: list[Tok] = field(default_factory=list)
    kind: str = (
        "opaque"  # env_begin|env_end|math|opaque|transparent_inline|transparent_expand
    )
    target_env: str = ""  # env_begin/env_end 专用
    protect_args: tuple[bool, ...] = ()
    scope: str = "local"  # local|global（\gdef/\xdef/\global → global）
    src: tuple[int, int, int] = (-1, -1, -1)  # (file_id, def_start, def_end)


@dataclass(slots=True)
class Alias:
    r"""``\let`` 快照（§8）。

    目标为当时的 MacroDef/IfCond/IfSetter 引用、字面 token（``\let\a=%``）
    或原语名 str；``None`` = 定义时未解析到。
    """

    target: MacroDef | IfCond | IfSetter | Tok | str | None


@dataclass(slots=True)
class IfCond:
    r"""``\newif`` 注册的 ``\ifX``：查 ``ifflags[flag]`` 求值。"""

    flag: str


@dataclass(slots=True)
class IfSetter:
    r"""``\Xtrue``/``\Xfalse``：流过时写 ``ifflags``，token 本体原样交分段器。"""

    flag: str
    value: bool


@dataclass(slots=True)
class EnvDef:
    r"""``\newenvironment``/``\newtheorem`` 登记（``env_scopes`` 表项）。"""

    name: str
    spec: list[Arg] = field(default_factory=list)
    before: list[Tok] = field(default_factory=list)
    after: list[Tok] = field(default_factory=list)
    caption: list[Tok] = field(default_factory=list)  # \newtheorem 的标题
    kind: str = "transparent"  # transparent|protected|theorem


Entry = MacroDef | Alias | IfCond | IfSetter


class ArgMismatch(Exception):  # noqa: N818 — 规格 §3.5 定名（非 Error 语义而是控制流信号）
    """调用点参数不匹配（§3.5）：调用方 ``unread(trace)`` 后回吐触发 token。"""


# ------------------------------------------------------------------ 宏表


class MacroTable:
    r"""命令/环境 scope 链（§8.5）。

    ``{``/``\\bgroup``/``\\begin{env}`` 推、``}``/``\\end`` 弹——由**分段器**
    驱动回报；本层只提供链与查写。``\\gdef/\\xdef/\\global`` 写底帧。
    """

    def __init__(self) -> None:
        """底帧 = 全局帧。"""
        self.scopes: list[dict[str, Entry]] = [{}]
        self.env_scopes: list[dict[str, EnvDef]] = [{}]

    def push_scope(self) -> None:
        """分段器回报组/环境开始。"""
        self.scopes.append({})
        self.env_scopes.append({})

    def pop_scope(self) -> None:
        """分段器回报组/环境结束；底帧不可弹。"""
        if len(self.scopes) > 1:
            self.scopes.pop()
            self.env_scopes.pop()

    def lookup(self, name: str) -> Entry | None:
        """自顶向下查命令表。"""
        for s in reversed(self.scopes):
            e = s.get(name)
            if e is not None:
                return e
        return None

    def lookup_env(self, name: str) -> EnvDef | None:
        """自顶向下查环境表。"""
        for s in reversed(self.env_scopes):
            e = s.get(name)
            if e is not None:
                return e
        return None

    def set(self, name: str, entry: Entry, scope: str = "local") -> None:
        """``global`` → 底帧；否则顶帧（LaTeX 语义，§8.5）。"""
        self.scopes[0 if scope == "global" else -1][name] = entry

    def setdefault(self, name: str, entry: Entry) -> None:
        r"""``\providecommand``：全链查无 → 写顶帧。"""
        if self.lookup(name) is None:
            self.set(name, entry)

    def set_env(self, entry: EnvDef, scope: str = "local") -> None:
        """环境表写入。"""
        self.env_scopes[0 if scope == "global" else -1][entry.name] = entry

    @staticmethod
    def resolve(entry: Entry | None) -> MacroDef | IfCond | IfSetter | Tok | str | None:
        """``Alias`` 解引用一层（快照语义）；其余原样返回。"""
        return entry.target if isinstance(entry, Alias) else entry


# ------------------------------------------------------------------ 常量

# 原语集（§8.2 expandables；if* 另由 startswith('if') 兜）
_PRIMS = {
    "def",
    "edef",
    "gdef",
    "xdef",
    "long",
    "outer",
    "global",
    "newcommand",
    "renewcommand",
    "providecommand",
    "DeclareRobustCommand",
    "newenvironment",
    "renewenvironment",
    "newtheorem",
    "DeclareMathOperator",
    "NewDocumentCommand",
    "RenewDocumentCommand",
    "ProvideDocumentCommand",
    "DeclareDocumentCommand",
    "let",
    "newif",
    "makeatletter",
    "makeatother",
    "catcode",
    "input",
    "include",
    "InputIfFileExists",
    "subfile",
    "import",
    "subimport",
    "includestandalone",
    "CatchFileBetweenTags",
    "endinput",
    "expandafter",
    "csname",
    "endcsname",
    "noexpand",
    "ifundefined",
    "@ifundefined",
    "par",
    "else",
    "or",
    "fi",
    "iftrue",
    "iffalse",
    "ifmmode",
    "ifnum",
    "ifodd",
    "ifdim",
    "ifcase",
    "ifdefined",
    "if",
    "ifcat",
    "ifx",
    "ifcsname",
    "ifeof",
    "ifvoid",
    "ifhbox",
    "ifvbox",
    "ifinner",
    "ifhmode",
    "ifvmode",
}

# gullet 真展开的宏 kind（其余 pass-through 交分段器保护调用点，§6.2）
_EXPAND_KINDS = {"env_begin", "env_end", "transparent_expand"}

# \ifdefined/ifundefined 的"已定义"判定补充集：内建命令名（§8.6 可求值档）
_BUILTINS = (
    CITE_NAMES
    | REF_NAMES
    | PROTECT_NAMES
    | TRANSPARENT_NAMES
    | BOUNDARY_NAMES
    | INLINE_LITERAL_CMDS
    | FONT_SWITCHES
    | CHUNK_ARG_NAMES
    | DEF_NAMES
    | INPUT_CMDS
    | _PRIMS
    | {
        "begin",
        "end",
        "item",
        "verb",
        "lstinline",
        "href",
        "section",
        "subsection",
        "footnote",
        "caption",
        "includegraphics",
        "bibliography",
        "bibliographystyle",
        "maketitle",
        "documentclass",
        "usepackage",
        "hline",
        "multicolumn",
        "cline",
        "eqref",
    }
)

# 数学特征 cs 名（§6.1 math 判定；无文本 + 含特征 → math）
_MATH_CS = {
    "ensuremath",
    "mathbb",
    "mathrm",
    "mathbf",
    "mathit",
    "mathsf",
    "mathtt",
    "mathcal",
    "mathfrak",
    "mathscr",
    "operatorname",
    "frac",
    "dfrac",
    "tfrac",
    "cfrac",
    "sqrt",
    "sum",
    "prod",
    "coprod",
    "int",
    "iint",
    "iiint",
    "oint",
    "lim",
    "sup",
    "inf",
    "max",
    "min",
    "limsup",
    "liminf",
    "sin",
    "cos",
    "tan",
    "cot",
    "sec",
    "csc",
    "arcsin",
    "arccos",
    "arctan",
    "sinh",
    "cosh",
    "tanh",
    "log",
    "ln",
    "lg",
    "exp",
    "det",
    "dim",
    "ker",
    "deg",
    "gcd",
    "hom",
    "Pr",
    "arg",
    "mod",
    "bmod",
    "pmod",
    "cdot",
    "cdots",
    "ldots",
    "dots",
    "dotsb",
    "dotsc",
    "times",
    "div",
    "pm",
    "mp",
    "cup",
    "cap",
    "setminus",
    "smallsetminus",
    "in",
    "notin",
    "ni",
    "subset",
    "supset",
    "subseteq",
    "supseteq",
    "sqsubseteq",
    "sqsupseteq",
    "to",
    "mapsto",
    "rightarrow",
    "leftarrow",
    "Rightarrow",
    "Leftarrow",
    "leftrightarrow",
    "Leftrightarrow",
    "longrightarrow",
    "longleftarrow",
    "uparrow",
    "downarrow",
    "updownarrow",
    "infty",
    "partial",
    "nabla",
    "forall",
    "exists",
    "nexists",
    "neg",
    "lnot",
    "land",
    "lor",
    "wedge",
    "vee",
    "oplus",
    "otimes",
    "odot",
    "ominus",
    "oslash",
    "circ",
    "bullet",
    "ast",
    "dagger",
    "ddagger",
    "le",
    "leq",
    "ge",
    "geq",
    "ne",
    "neq",
    "equiv",
    "cong",
    "simeq",
    "approx",
    "sim",
    "propto",
    "prec",
    "succ",
    "preceq",
    "succeq",
    "ll",
    "gg",
    "parallel",
    "perp",
    "models",
    "vdash",
    "dashv",
    "lfloor",
    "rfloor",
    "lceil",
    "rceil",
    "langle",
    "rangle",
    "vert",
    "Vert",
    "backslash",
    "left",
    "right",
    "big",
    "Big",
    "bigg",
    "Bigg",
    "bigl",
    "bigr",
    "Bigl",
    "Bigr",
    "limits",
    "nolimits",
    "overline",
    "overbrace",
    "underbrace",
    "hat",
    "widehat",
    "tilde",
    "widetilde",
    "bar",
    "vec",
    "dot",
    "ddot",
    "overrightarrow",
    "overleftarrow",
    "stackrel",
    "overset",
    "underset",
    "substack",
    "binom",
    "boxed",
    "boldsymbol",
    "bm",
    "pmb",
    "displaystyle",
    "textstyle",
    "nonumber",
    "tag",
    "hbar",
    "ell",
    "Re",
    "Im",
    "wp",
    "aleph",
    "beth",
    "prime",
    "emptyset",
    "varnothing",
    "angle",
    "top",
    "bot",
    "flat",
    "natural",
    "sharp",
    "clubsuit",
    "diamondsuit",
    "heartsuit",
    "spadesuit",
    "surd",
    "imath",
    "jmath",
    "degree",
    "mathbin",
    "mathrel",
    "mathop",
    "mathord",
    "hspace",
    "vspace",
    "quad",
    "qquad",
    "thinspace",
    "enspace",
    "mathchoice",
    "xrightarrow",
    "xleftarrow",
    "xmapsto",
    "hookrightarrow",
    "twoheadrightarrow",
    "rightleftharpoons",
    "restriction",
    "colon",
    "ltimes",
    "rtimes",
    "bowtie",
    "asymp",
    "triangleq",
    "coloneqq",
    "eqqcolon",
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "varepsilon",
    "zeta",
    "eta",
    "theta",
    "vartheta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "pi",
    "varpi",
    "rho",
    "varrho",
    "sigma",
    "varsigma",
    "tau",
    "upsilon",
    "phi",
    "varphi",
    "chi",
    "psi",
    "omega",
    "Gamma",
    "Delta",
    "Theta",
    "Lambda",
    "Xi",
    "Pi",
    "Sigma",
    "Upsilon",
    "Phi",
    "Psi",
    "Omega",
}

# `\(`/`\)`/`\[`/`\]` 单字符 cs 也是数学特征
_MATH_CS |= {"(", ")", "[", "]"}

_FILENAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
)

_DIGITS = frozenset("0123456789")
_REL_CHARS = {"<", ">", "="}


def _surface(toks: list[Tok] | tuple[Tok, ...]) -> str:
    r"""Token 表面文本：cs → ``\name``，其余 → ``text``（分类/名拼接用）。

    cs 后紧邻 letter token 补一个空格——``\text foo`` 源里被吸收的空白
    在 token 流里已不存在，不补则 ``\textfoo`` 被 ``_STRIP_CS_RX`` 整体
    当命令名剥掉，含文本的体误判 opaque（``\begin{`` 不受影响：
    lbrace 非 letter）。
    """
    parts: list[str] = []
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind == "cs":
            parts.append("\\" + t.text)
            if i + 1 < n and toks[i + 1].kind == "letter":
                parts.append(" ")
        else:
            parts.append(t.text)
    return "".join(parts)


def _tok_eq(a: Tok, b: Tok) -> bool:
    """Token 结构相等（kind+text；忽略 pos/gen——plasTeX ``t == a`` 同义）。"""
    return a.kind == b.kind and a.text == b.text


def expand_def(
    body: list[Tok], params: dict[int, list[Tok] | None], trig: Tok
) -> list[Tok]:
    r"""``#n`` 代入（``expandDef __init__.py:1096-1127`` 直接移植）。

    - ``##`` → 字面 ``#``；``#``+数字 → ``params[k]``（参数 token 保持自身
      pos/gen——它们是真实源 token）；``#``+非数字 → 容忍为字面 ``#``
      （plasTeX ``int(t)`` 会崩，我们选择不崩）；
    - ``previous == 'ifx'`` 时参数外包 ``{ }``（``__init__.py:1116`` 同款 hack）；
    - 体产出的 token 打 ``gen=trig.gen+1``、``origin=最外层调用点``。
    """
    gen = trig.gen + 1
    origin = trig.origin or trig.pos
    out: list[Tok] = []
    i, n = 0, len(body)
    prev_name = ""
    while i < n:
        t = body[i]
        if t.kind != "param":
            out.append(Tok(t.kind, t.text, t.pos, gen, origin, t.xprotect))
            prev_name = t.text
            i += 1
            continue
        nxt = body[i + 1] if i + 1 < n else None
        if nxt is None:
            out.append(Tok("param", t.text, t.pos, gen, origin))
            prev_name = t.text
            i += 1
            continue
        if nxt.kind == "param":  # '##' → 字面 #
            out.append(Tok("param", nxt.text, nxt.pos, gen, origin))
            prev_name = nxt.text
            i += 2
            continue
        if nxt.text.isdigit():
            v = params.get(int(nxt.text))
            if v:
                if prev_name == "ifx":  # ifx hack：参数包组
                    out.append(Tok("lbrace", "{", t.pos, gen, origin))
                    out.extend(v)
                    out.append(Tok("rbrace", "}", t.pos, gen, origin))
                else:
                    out.extend(v)
            i += 2
            prev_name = nxt.text
            continue
        # '#' + 非数字非'#' → 字面 #，下一 token 下轮正常处理
        out.append(Tok("param", t.text, t.pos, gen, origin))
        prev_name = t.text
        i += 1
    return out


# ------------------------------------------------------------------ Gullet


class Gullet:
    r"""回压式不动点展开器（``TeX.__iter__`` 移植）。

    用法：``Gullet(tex, root_dir=dir)`` 或 ``Gullet()`` + ``push_source``；
    ``next_expanded()`` 逐枚取展开后 token 直到 ``None``。
    """

    def __init__(
        self,
        text: str = "",
        *,
        root_dir: str = "",
        cats: CatTable | None = None,
        macros: MacroTable | None = None,
    ) -> None:
        """``text`` 顶层源（可空）；``cats``/``macros`` 可注入共享。"""
        self.cats = cats if cats is not None else CatTable()
        self.macros = macros if macros is not None else MacroTable()
        self.inputs: list[Mouth] = []  # 输入栈 = TeX.inputs (TeX.py:72)
        self.file_texts: list[str] = []  # file_id → 源文本
        self.file_paths: list[str] = []  # file_id → 路径（'' = 内存源）
        self.ifflags: dict[str, bool] = {}  # \newif 旗标
        self.math_depth = 0  # 分段器回报 → \ifmmode 求值
        self.steps = 0
        self.overflow = False  # 是否已记 expansion_overflow
        self.warnings: list[ScanWarning] = []
        self.root_dir = root_dir
        self._seen: set[str] = set()  # \input 绝对路径祖先栈（W12：进栈压、弹栈撤）
        self._seen_fid: dict[int, str] = {}  # file_id → 已登记绝对路径
        self._trace: list[Tok] = []  # 当前 invoke 已消费 token（回吐用）
        if text:
            self.push_source(text, "")

    # ------------------------------------------------------------ 源栈

    def push_source(self, text: str, path: str = "") -> int:
        """压新输入源，返回其 ``file_id``；有路径即入 ``_seen`` 祖先栈。"""
        fid = len(self.file_texts)
        self.file_texts.append(text)
        self.file_paths.append(path)
        self.inputs.append(Mouth(text, fid, self.cats))
        if path:
            r = str(Path(path).resolve())
            self._seen.add(r)
            self._seen_fid[fid] = r
        return fid

    def read(self) -> Tok | None:
        """拉原始 token（``itertokens`` TeX.py:249-279）：栈顶耗尽即弹。"""
        while self.inputs:
            t = self.inputs[-1].next()
            if t is not None:
                return t
            m = self.inputs.pop()
            r = self._seen_fid.pop(m.file_id, None)
            if r is not None:
                self._seen.discard(r)  # 祖先栈回撤：兄弟位合法重包含不断
        return None

    def unread(self, toks: list[Tok] | tuple[Tok, ...]) -> None:
        """推回前端（``pushTokens`` TeX.py:455-467）：栈空 → 新建 token 源。"""
        if not toks:
            return
        if not self.inputs:
            self.inputs.append(Mouth.from_tokens(list(toks), self.cats))
        else:
            self.inputs[-1].push_tokens(list(toks))

    # ------------------------------------------------------------ 主循环

    def next_expanded(self) -> Tok | None:  # noqa: C901, PLR0911, PLR0912 — 分派顺序即 §8.2/§8.6（宏表先行）
        r"""展开主循环（``TeX.__iter__`` TeX.py:281-340）。

        拉原始 token → 非 cs 直交 → cs 查宏表（先行：``\ifb`` 单位宏 /
        ``\ifAnonymous{T}{F}`` 双参宏不落入 if 族）→ 命中且可展开则读参代入
        推回（不 return，不动点）；否则查原语；都不中 → 直交分段器。
        """
        while True:
            t = self.read()
            if t is None:
                return None
            if t.kind != "cs":
                return t
            if t.xprotect:
                t.xprotect = False  # \noexpand 打标：见标跳过一次展开
                return t
            name = t.text
            entry = self.macros.lookup(name)
            if entry is not None:
                r = self.macros.resolve(entry)
                if isinstance(r, MacroDef):
                    if r.kind in _EXPAND_KINDS and self._can_expand(t):
                        self.steps += 1
                        self._trace = []
                        try:
                            out = self._invoke(t, r)
                        except ArgMismatch:
                            self.unread(self._trace)
                            return t  # §3.5：回吐已读 + \name 本体交出
                        self.unread(out)
                        continue
                    return t  # opaque/math/inline/literal → 调用点保护
                if isinstance(r, IfCond):
                    if not self._can_expand(t):
                        return t
                    self.steps += 1
                    self.process_if(self.ifflags.get(r.flag, False))
                    continue
                if isinstance(r, IfSetter):
                    self.ifflags[r.flag] = r.value
                    return t
                if isinstance(r, Tok):  # \let 字面别名 → 以触发位交出
                    return Tok(r.kind, r.text, t.pos, t.gen, t.origin)
                if isinstance(r, str):  # \let 到原语名 → 换名走原语分派
                    t = Tok("cs", r, t.pos, t.gen, t.origin)
                    name = r
                else:
                    return t  # Alias(None)：定义时未解析 → 未知命令
            if name in _PRIMS or name.startswith("if"):
                if not self._can_expand(t):
                    return t
                self.steps += 1
                out = self._exec_prim(t)
                if out is None:
                    continue
                return out
            return t  # LaTeX 内建/未知 cs → 分段器按 argspec 表处理

    def _can_expand(self, t: Tok) -> bool:
        """三级限制：``gen>MAX_GEN``/``steps>BUDGET`` → 不再展开（§3.4）。"""
        if t.gen >= MAX_GEN:
            if not self.overflow:
                self.overflow = True
                self._warn("gen_overflow", t, f"gen>={MAX_GEN} unexpanded")
            return False
        if self.steps >= BUDGET:
            if not self.overflow:
                self.overflow = True
                self._warn("expansion_overflow", t, f"steps>{BUDGET}")
            return False
        return True

    def __iter__(self) -> Gullet:
        """迭代协议：``next_expanded() → None`` 耗尽。"""
        return self

    def __next__(self) -> Tok:
        """``next_expanded() → None`` 时 ``StopIteration``。"""
        t = self.next_expanded()
        if t is None:
            raise StopIteration
        return t

    def expand_all(self) -> list[Tok]:
        """抽干展开流（测试/分段器喂流便利）。"""
        out: list[Tok] = []
        while True:
            t = self.next_expanded()
            if t is None:
                return out
            out.append(t)

    def _warn(self, kind: str, t: Tok | None, detail: str) -> None:
        """登记 ``ScanWarning``；pos 取 token 起点（无 token → 0）。"""
        pos = t.pos[1] if t is not None else 0
        self.warnings.append(ScanWarning(kind, pos, detail))

    # ------------------------------------------------------------ 参数读取
    # 全部走 read()（原始未展开流，TeX.py:704-714 同构）；消费计入 trace。

    def _rt(self, trace: list[Tok]) -> Tok | None:
        """``read()`` + 消费计入 ``trace``（回吐账户）。"""
        t = self.read()
        if t is not None:
            trace.append(t)
        return t

    def _rt_skip(self, trace: list[Tok]) -> Tok | None:
        """``_rt`` 跳过 space token（eol_par 不跳——不定界参不跨段）。"""
        while True:
            t = self._rt(trace)
            if t is None or t.kind != "space":
                return t

    def _pushback(self, trace: list[Tok], t: Tok) -> None:
        """已读 token 回吐流且销账（防 unread(trace) 双份）。"""
        trace.pop()
        self.unread([t])

    def _read_undelimited(self, trace: list[Tok]) -> list[Tok]:
        r"""不定界参（``readToken`` TeX.py:786-841）。

        跳前导空白后：``{`` → 平衡组（剥外层括号）；``$`` → 到下一 ``$`` 止
        （含两端）；``eol_par`` → 回吐 + mismatch；其余 → 单 token。
        """
        t = self._rt_skip(trace)
        if t is None:
            raise ArgMismatch
        if t.kind == "lbrace":
            return self._read_balanced(trace)
        if t.kind == "mathshift":
            out = [t]
            while True:
                t2 = self._rt(trace)
                if t2 is None:
                    return out
                out.append(t2)
                if t2.kind == "mathshift":
                    return out
        if t.kind == "eol_par":
            self._pushback(trace, t)
            raise ArgMismatch
        return [t]

    def _read_balanced(self, trace: list[Tok]) -> list[Tok]:
        """``{`` 已消费 → 收到配对 ``}`` 止（内层含括号，外层剥掉）。"""
        out: list[Tok] = []
        level = 1
        while True:
            t = self._rt(trace)
            if t is None:
                return out  # 流尽：容忍返回已收（调用方判 group 完整性）
            if t.kind == "lbrace":
                level += 1
            elif t.kind == "rbrace":
                level -= 1
                if level == 0:
                    return out
            out.append(t)

    def _read_grouping(  # noqa: C901 — 自定界组三类开符合一
        self, trace: list[Tok], open_c: str, close_c: str
    ) -> list[Tok] | None:
        r"""``[..]``/``<..>`` 可选参（``readGrouping`` TeX.py:863-908）。

        首非空白 token 非 opener → 回吐 + ``None``（缺席）；读到 close 止
        （配对计数；定界 token 消费不入参）。流尽 → ``ArgMismatch``。
        """
        t = self._rt_skip(trace)
        if t is None:
            return None
        if open_c == "{":
            if t.kind != "lbrace":
                self._pushback(trace, t)
                return None
        elif t.kind == "cs" or t.text != open_c:
            self._pushback(trace, t)
            return None
        out: list[Tok] = []
        level = 1
        while True:
            t2 = self._rt(trace)
            if t2 is None:
                raise ArgMismatch
            if t2.kind != "cs":
                if t2.text == open_c and (open_c != "{" or t2.kind == "lbrace"):
                    level += 1
                elif t2.text == close_c or (close_c == "}" and t2.kind == "rbrace"):
                    level -= 1
                    if level == 0:
                        return out
            out.append(t2)

    def _read_delimited(self, trace: list[Tok], delim: list[Tok]) -> list[Tok]:
        r"""定界参（``__init__.py:1211-1219``）：读到后缀==``delim`` 止。

        定界 token 消费不入参；``{`` 起平衡组整组入参（**含括号**——组内
        定界符不匹配，比 plasTeX 逐 token 判定更贴 TeX）。流尽 → mismatch。
        """
        out: list[Tok] = []
        k = len(delim)
        while True:
            t = self._rt(trace)
            if t is None:
                raise ArgMismatch
            if t.kind == "lbrace":
                grp = self._read_balanced(trace)
                out.append(t)
                out.extend(grp)
                # 组闭合括号补回（grp 不含外层}）
                out.append(Tok("rbrace", "}", grp[-1].pos if grp else t.pos))
                continue
            out.append(t)
            if len(out) >= k and all(_tok_eq(out[-k + j], delim[j]) for j in range(k)):
                del out[-k:]
                return out

    def _read_until_lbrace(self, trace: list[Tok]) -> list[Tok]:
        r"""``#{`` 型：读到 ``lbrace`` 回吐不消费（``__init__.py:1196-1205``）。"""
        out: list[Tok] = []
        while True:
            t = self._rt(trace)
            if t is None:
                raise ArgMismatch
            if t.kind == "lbrace":
                self._pushback(trace, t)
                return out
            out.append(t)

    def _read_star(self, trace: list[Tok], char: str) -> list[Tok]:
        """``*``/``tX`` 可选修饰：命中 → ``[tok]``；否则回吐 + ``[]``。"""
        t = self._rt_skip(trace)
        if t is not None and t.kind != "cs" and t.text == char:
            return [t]
        if t is not None:
            self._pushback(trace, t)
        return []

    def _read_eq(self, trace: list[Tok]) -> None:
        r"""``\let\a=\b`` 的可选 ``=``：不占参数位。"""
        t = self._rt_skip(trace)
        if t is not None and (t.kind == "cs" or t.text != "="):
            self._pushback(trace, t)

    # ------------------------------------------------------------ invoke

    def _invoke(  # noqa: C901, PLR0912 — spec 参数型平铺即 §4.1 表
        self, trig: Tok, m: MacroDef
    ) -> list[Tok]:
        r"""按 ``spec`` 读参 + ``expand_def`` 代入（§5.3/§5.4 统一）。

        ``literal_match``/``eq`` 不占参数位；``o`` 缺席 → ``default``
        （None → 代入时该 ``#i`` 不产出）。``ArgMismatch`` 由调用方回吐。
        """
        if not m.spec:
            return expand_def(m.body, {}, trig)
        trace = self._trace
        params: dict[int, list[Tok] | None] = {}
        slot = 0
        for a in m.spec:
            k = a.kind
            if k == "literal_match":
                t = self._rt(trace)
                if t is None or not _tok_eq(t, a.delim[0]):
                    raise ArgMismatch
                continue
            if k == "eq":
                self._read_eq(trace)
                continue
            slot += 1
            if k == "m":
                params[slot] = self._read_undelimited(trace)
            elif k == "o":
                params[slot] = self._read_grouping(trace, a.open, a.close)
                if params[slot] is None:
                    params[slot] = a.default
            elif k == "star":
                params[slot] = self._read_star(trace, a.char)
            elif k == "delim":
                params[slot] = self._read_delimited(trace, a.delim)
                if a.brace_after:  # `#1 abc#{`：delim 后还需 `{`，读一回吐
                    t2 = self._rt(trace)
                    if t2 is not None:
                        self._pushback(trace, t2)
            elif k == "until_group":
                params[slot] = self._read_until_lbrace(trace)
            else:
                raise ArgMismatch
        return expand_def(m.body, params, trig)

    # ------------------------------------------------------------ 原语分派

    def _exec_prim(self, t: Tok) -> Tok | None:  # noqa: C901, PLR0911, PLR0912 — 原语表平铺即 §8.2 expandables 集
        """原语执行：``Tok`` → 直交分段器；``None`` → 已处理继续循环。"""
        name = t.text
        if name in ("def", "edef", "gdef", "xdef"):
            return self._do_def(
                t,
                global_=name in ("gdef", "xdef"),
                eager=name in ("edef", "xdef"),
            )
        if name in ("long", "outer", "global"):
            return self._do_prefix(t, name)
        if name in (
            "newcommand",
            "renewcommand",
            "providecommand",
            "DeclareRobustCommand",
        ):
            return self._do_newcmd(t, name)
        if name in ("newenvironment", "renewenvironment"):
            return self._do_newenv(t)
        if name == "newtheorem":
            return self._do_newtheorem(t)
        if name == "DeclareMathOperator":
            return self._do_mathop(t)
        if name in (
            "NewDocumentCommand",
            "RenewDocumentCommand",
            "ProvideDocumentCommand",
            "DeclareDocumentCommand",
        ):
            return self._do_xparse(t, name)
        if name == "let":
            return self._do_let(t)
        if name == "newif":
            return self._do_newif(t)
        if name == "makeatletter":
            self.cats.set("@", CC_LETTER)
            return t
        if name == "makeatother":
            self.cats.set("@", CC_OTHER)
            return t
        if name == "catcode":
            return self._do_catcode(t)
        if name == "endinput":
            if self.inputs:
                self.inputs.pop()
            return None
        if name in INPUT_CMDS:
            return self._do_input(t, name)
        if name == "expandafter":
            return self._do_expandafter(t)
        if name == "csname":
            return self._do_csname(t)
        if name == "noexpand":
            t2 = self.read()
            if t2 is not None:
                t2.xprotect = True
                self.unread([t2])
            return None
        if name in ("ifundefined", "@ifundefined"):
            return self._do_ifundefined(t)
        if name == "par":
            return Tok("eol_par", "par", t.pos, t.gen, t.origin)
        if name.startswith("if"):
            return self._do_if(t)
        return t  # else/or/fi/endcsname 散件 → 界标 literal

    # ------------------------------------------------------------ \def 族

    def _do_def(self, trig: Tok, *, global_: bool, eager: bool = False) -> Tok | None:
        r"""``\def\name<参数文本>{体}``（``DefCommand`` Primitives.py:127-168）。

        参数文本 = ``\name`` 与首个 ``{`` 间全部 token，定义时编译为 spec；
        ``##`` 检出后体/参数文本同折叠一层（Primitives.py:146-160）。
        ``\edef/\xdef``（``eager``）先对体跑一遍展开再登记（哨兵界标法）。
        """
        trace = self._trace = []
        nt = self._rt_skip(trace)
        if nt is None or nt.kind not in ("cs", "active"):
            return self._def_fail(trig, trace, "def name not cs")
        mname = nt.text
        # 参数文本：到首个 lbrace 止（brace 入账不归参数文本）
        ptext: list[Tok] = []
        brace: Tok | None = None
        while True:
            a = self._rt(trace)
            if a is None or a.kind == "lbrace":
                brace = a
                break
            ptext.append(a)
        if brace is None:
            return self._def_fail(trig, trace, "param text unterminated")
        body = self._read_balanced(trace)
        if not trace or trace[-1].kind != "rbrace":
            return self._def_fail(trig, trace, "def body unterminated")
        spec = self._compile_param_text(ptext, has_brace=True)
        if spec is None:
            return self._def_fail(trig, trace, "param text illegal")
        if self._has_double_hash(ptext):
            # `##` 在**参数文本**（非体）出现 → 该 def 写深了一层，ptext+体同折
            # （Primitives.py:146-160 的判定域是 args；体里的 ## 归 expand_def 管）
            ptext = self._fold_hashes(ptext)
            body = self._fold_hashes(body)
            spec = self._compile_param_text(ptext, has_brace=True)
            if spec is None:
                return self._def_fail(trig, trace, "param text illegal")
        if eager:
            body = self._expand_eager(body)
        kind, target, protect = self._classify(body, self._param_count(spec))
        self.macros.set(
            mname,
            MacroDef(
                name=mname,
                spec=spec,
                body=body,
                kind=kind,
                target_env=target,
                protect_args=protect,
                scope="global" if global_ else "local",
                src=(trig.pos[0], trig.pos[1], self._trace_end(trace)),
            ),
            "global" if global_ else "local",
        )
        return None

    def _expand_eager(self, body: list[Tok]) -> list[Tok]:
        r"""``\edef/\xdef`` 体即时展开：体 + 哨兵推回，抽展开流到哨兵止。

        哨兵 kind 非 cs、不在任何分派面 → 必然原样浮出；``\noexpand`` 打标
        的 token 带 ``xprotect`` 存进体（调用点再展开时见标跳一次）。
        """
        sentinel = Tok("_edef_end", "", (-1, -1, -1))
        self.unread([*body, sentinel])
        out: list[Tok] = []
        while True:
            t = self.next_expanded()
            if t is None or t is sentinel:
                return out
            out.append(t)

    @staticmethod
    def _trace_end(trace: list[Tok]) -> int:
        """Trace 末 token 的 end（def 登记 src 用）。"""
        return trace[-1].pos[2] if trace else -1

    def _def_fail(self, trig: Tok, trace: list[Tok], why: str) -> Tok:
        r"""定义解析失败（§3.5）：不登记 + 全部回吐 + ``\def`` 本体交出。"""
        self._warn("def_parse_fail", trig, why)
        self.unread(trace)
        return trig

    def _do_prefix(self, trig: Tok, name: str) -> Tok | None:
        r"""``\long/\outer/\global`` 前缀：链到 def 族才生效，否则原样交出。"""
        trace = self._trace = []
        seen_global = name == "global"
        while True:
            t = self._rt_skip(trace)
            if t is None:
                self.unread(trace)
                return trig
            if t.kind == "cs" and t.text in ("long", "outer", "global"):
                seen_global = seen_global or t.text == "global"
                continue
            if t.kind == "cs" and t.text in ("def", "edef", "gdef", "xdef"):
                return self._do_def(
                    t,
                    global_=seen_global or t.text in ("gdef", "xdef"),
                    eager=t.text in ("edef", "xdef"),
                )
            self.unread(trace)
            return trig

    @staticmethod
    def _has_double_hash(toks: list[Tok]) -> bool:
        """检测相邻 ``##``（嵌套定义标记）。"""
        return any(a.kind == "param" and b.kind == "param" for a, b in pairwise(toks))

    @staticmethod
    def _fold_hashes(toks: list[Tok]) -> list[Tok]:
        r"""``##`` 折叠一层（Primitives.py:146-160）：每段 ``#`` 连跑去一。

        k 个连续 ``#`` + 非 ``#`` → k−1 个 ``#`` 留下。
        """
        out: list[Tok] = []
        run = 0
        for t in toks:
            if t.kind == "param":
                run += 1
                out.append(t)
            else:
                if run > 1:
                    out.pop()
                run = 0
                out.append(t)
        return out

    @staticmethod
    def _param_count(spec: list[Arg]) -> int:
        """参数位数（``literal_match``/``eq`` 不占位）。"""
        return sum(1 for a in spec if a.kind not in ("literal_match", "eq"))

    def _compile_param_text(  # noqa: C901, PLR0912 — 参数文本文法平铺即 §8.4 表
        self, ptext: list[Tok], *, has_brace: bool
    ) -> list[Arg] | None:
        r"""``\def`` 参数文本 → ``list[Arg]``（§8.4/§5.2 编译表）。

        ``#``+数字 → 新参数槽；``#``+``#`` → 跳过；``#``+流末（且参数文本
        止于 ``{``）→ 前一槽 ``until_group``；非 ``#`` 有槽 → 追加 delim；
        非 ``#`` 无槽 → ``literal_match``；尾随槽 → ``'m'``。
        """
        spec: list[Arg] = []
        pending: Arg | None = None
        i, n = 0, len(ptext)
        while i < n:
            a = ptext[i]
            if a.kind != "param":
                if pending is not None:
                    pending.kind = "delim"
                    pending.delim.append(a)
                else:
                    spec.append(Arg("literal_match", delim=[a]))
                i += 1
                continue
            nxt = ptext[i + 1] if i + 1 < n else None
            if nxt is None:
                # 尾随裸 '#'（参数文本止于 '{'）：TeX `#{` 语义——
                # pending 无 delim → until_group；有 delim → 保留 +
                # brace_after（`#1 abc#{` 的 abc 定界不丢）
                if has_brace:
                    if pending is None:
                        spec.append(Arg("until_group"))
                    elif pending.kind == "delim" and pending.delim:
                        pending.brace_after = True
                    else:
                        pending.kind = "until_group"
                    i += 1
                    continue
                return None
            if nxt.kind == "param":  # '##' → 跳过（折叠残留容忍）
                i += 2
                continue
            if nxt.kind == "lbrace":  # '#{' 同尾随形（防御：正常不可达）
                if pending is None:
                    spec.append(Arg("until_group"))
                elif pending.kind == "delim" and pending.delim:
                    pending.brace_after = True
                else:
                    pending.kind = "until_group"
                i += 2
                continue
            if nxt.kind != "cs" and len(nxt.text) == 1 and nxt.text.isdigit():
                pending = Arg("m")
                spec.append(pending)
                i += 2
                continue
            return None  # '#' + 其他 → 参数文本非法
        return spec

    # ------------------------------------------------------------ \newcommand 族

    def _eat_star(self, trace: list[Tok]) -> None:
        r"""``\newcommand*`` 等的可选 ``*``：吃掉或回吐（仅占位不产参数）。"""
        t = self._rt_skip(trace)
        if t is not None and (t.kind == "cs" or t.text != "*"):
            self._pushback(trace, t)

    def _read_def_name(self, trace: list[Tok]) -> str | None:
        r"""``{\cmd}`` 或 ``\cmd`` 读宏名（``name:cs``）。"""
        t = self._rt_skip(trace)
        if t is None:
            return None
        if t.kind == "cs":
            return t.text
        if t.kind == "lbrace":
            inner = self._read_balanced(trace)
            for x in inner:
                if x.kind == "cs":
                    return x.text
            return ""
        return None

    def _read_opt_int(self, trace: list[Tok]) -> tuple[int | None, list[Tok] | None]:
        """可选 ``[n]``：返回 ``(int 值, 原始 token 列)``；缺席 ``(None, None)``。"""
        grp = self._read_grouping(trace, "[", "]")
        if grp is None:
            return None, None
        txt = _surface(grp).strip()
        try:
            return int(txt or 0), grp
        except ValueError:
            return 0, grp

    def _do_newcmd(self, trig: Tok, name: str) -> Tok | None:
        r"""``\newcommand[*]{\n}[N][d]{B}``（``Definitions.py:15-24``）。

        ``*`` 只吃 token；``[N][d]`` 同在 → ``spec=[o(d)]+m×(N-1)``——
        N **含**可选位（plasTeX ``nargs-1`` ``__init__.py:1145-1147``）。
        """
        trace = self._trace = []
        self._eat_star(trace)
        mname = self._read_def_name(trace)
        if mname is None:
            return self._def_fail(trig, trace, "newcommand name")
        nargs, _ = self._read_opt_int(trace)
        default = self._read_grouping(trace, "[", "]")  # 缺省值是 token 列非 int
        n = nargs or 0
        brace = self._rt_skip(trace)
        if brace is None or brace.kind != "lbrace":
            return self._def_fail(trig, trace, "newcommand body")
        body = self._read_balanced(trace)
        spec: list[Arg] = []
        if default is not None:
            spec.append(Arg("o", default=default))
            n = max(n - 1, 0)
        spec.extend(Arg("m") for _ in range(n))
        kind, target, protect = self._classify(body, self._param_count(spec))
        entry = MacroDef(
            name=mname,
            spec=spec,
            body=body,
            kind=kind,
            target_env=target,
            protect_args=protect,
            src=(trig.pos[0], trig.pos[1], self._trace_end(trace)),
        )
        if name == "providecommand":
            self.macros.setdefault(mname, entry)
        else:
            self.macros.set(mname, entry)
        return None

    def _do_newenv(self, trig: Tok) -> Tok | None:
        r"""``\newenvironment[*]{env}[N][d]{before}{after}``（Definitions.py:42-51）。"""
        trace = self._trace = []
        self._eat_star(trace)
        envname = self._read_env_name(trace)
        if envname is None:
            return self._def_fail(trig, trace, "newenvironment name")
        nargs, _ = self._read_opt_int(trace)
        default = self._read_grouping(trace, "[", "]")
        before = self._read_grouping(trace, "{", "}")
        if before is None:
            return self._def_fail(trig, trace, "newenvironment before")
        after = self._read_grouping(trace, "{", "}")
        if after is None:
            return self._def_fail(trig, trace, "newenvironment after")
        spec: list[Arg] = []
        n = nargs or 0
        if default is not None:
            spec.append(Arg("o", default=default))
            n = max(n - 1, 0)
        spec.extend(Arg("m") for _ in range(n))
        kind = "transparent"  # env 保护性归分段器按 ENV 表裁决（v1 一律 transparent）
        self.macros.set_env(
            EnvDef(name=envname, spec=spec, before=before, after=after, kind=kind)
        )
        return None

    def _read_env_name(self, trace: list[Tok]) -> str | None:
        """``{env}`` 读环境名（``name:str``）。"""
        grp = self._read_grouping(trace, "{", "}")
        if grp is None:
            return None
        return _surface(grp).strip()

    def _do_newtheorem(self, trig: Tok) -> Tok | None:
        r"""``\newtheorem{n}[c]{cap}[w]``（Definitions.py:61-90）→ 定理类 env。"""
        trace = self._trace = []
        self._eat_star(trace)
        envname = self._read_env_name(trace)
        if envname is None:
            return self._def_fail(trig, trace, "newtheorem name")
        self._read_grouping(trace, "[", "]")  # [counter] 吃掉不用
        cap = self._read_grouping(trace, "{", "}")
        if cap is None:
            return self._def_fail(trig, trace, "newtheorem caption")
        self._read_grouping(trace, "[", "]")  # [within]
        self.macros.set_env(
            EnvDef(name=envname, spec=[Arg("o")], caption=cap, kind="theorem")
        )
        return None

    def _do_mathop(self, trig: Tok) -> Tok | None:
        r"""``\DeclareMathOperator[*]{\n}{B}`` → 体包 ``\operatorname{B}``（amsmath.py:111-123）。"""
        trace = self._trace = []
        self._eat_star(trace)
        mname = self._read_def_name(trace)
        if mname is None:
            return self._def_fail(trig, trace, "DeclareMathOperator name")
        grp = self._read_grouping(trace, "{", "}")
        if grp is None:
            return self._def_fail(trig, trace, "DeclareMathOperator body")
        body = [
            Tok("cs", "operatorname", trig.pos),
            Tok("lbrace", "{", trig.pos),
            *grp,
            Tok("rbrace", "}", trig.pos),
        ]
        self.macros.set(
            mname,
            MacroDef(
                name=mname,
                spec=[],
                body=body,
                kind="math",
                src=(trig.pos[0], trig.pos[1], self._trace_end(trace)),
            ),
        )
        return None

    def _do_xparse(self, trig: Tok, name: str) -> Tok | None:
        r"""``\NewDocumentCommand{\n}{spec}{B}``（§4.3 xparse 子集）。

        spec 含 ``v/b/e/E/x`` → 整条不登记（体原样回吐走字面）。
        """
        trace = self._trace = []
        mname = self._read_def_name(trace)
        if mname is None:
            return self._def_fail(trig, trace, "xparse name")
        spec_grp = self._read_grouping(trace, "{", "}")
        if spec_grp is None:
            return self._def_fail(trig, trace, "xparse spec")
        spec = self._parse_xparse(_surface(spec_grp))
        if spec is None:
            return self._def_fail(trig, trace, "xparse unsupported spec")
        body = self._read_grouping(trace, "{", "}")
        if body is None:
            return self._def_fail(trig, trace, "xparse body")
        kind, target, protect = self._classify(body, self._param_count(spec))
        entry = MacroDef(
            name=mname,
            spec=spec,
            body=body,
            kind=kind,
            target_env=target,
            protect_args=protect,
            src=(trig.pos[0], trig.pos[1], self._trace_end(trace)),
        )
        if name == "ProvideDocumentCommand":
            self.macros.setdefault(mname, entry)
        else:
            self.macros.set(mname, entry)
        return None

    def _parse_xparse(self, s: str) -> list[Arg] | None:  # noqa: C901, PLR0912, PLR0915 — spec 字母平铺即 §4.3 表
        """Xparse spec 串 → ``list[Arg]``；不支持字母 → ``None``。"""
        out: list[Arg] = []
        i, n = 0, len(s)

        def _braced(j: int) -> tuple[str | None, int]:
            """``{..}`` 取内容（不配对括号）。"""
            if j < n and s[j] == "{":
                e = s.find("}", j + 1)
                if e >= 0:
                    return s[j + 1 : e], e + 1
            return None, j

        while i < n:
            ch = s[i]
            i += 1
            if ch in " \t\n+":
                continue
            if ch == "m":
                out.append(Arg("m"))
            elif ch == "o":
                out.append(Arg("o"))
            elif ch == "O":
                d, i = _braced(i)
                out.append(Arg("o", default=self._lex(d or "")))
            elif ch == "s":
                out.append(Arg("star", char="*"))
            elif ch == "t":
                if i < n:
                    out.append(Arg("star", char=s[i]))
                    i += 1
                else:
                    out.append(Arg("star"))
            elif ch in "dD":
                if i + 1 < n:
                    a = Arg("o", open=s[i], close=s[i + 1])
                    i += 2
                    if ch == "D":
                        d, i = _braced(i)
                        a.default = self._lex(d or "")
                    out.append(a)
                else:
                    return None
            elif ch in "rR":
                if i + 1 < n:
                    open_c, close_c = s[i], s[i + 1]
                    i += 2
                    if ch == "r":
                        # r<> 必填：literal_match 开符 + delim 收内容（只占一槽）
                        out.append(
                            Arg(
                                "literal_match",
                                delim=[Tok("other", open_c, (-1, -1, -1))],
                            )
                        )
                        out.append(
                            Arg(
                                "delim",
                                delim=[Tok("other", close_c, (-1, -1, -1))],
                            )
                        )
                    else:
                        # R<> 带缺省 → 等价 'o' 自定界
                        a = Arg("o", open=open_c, close=close_c)
                        d, i = _braced(i)
                        a.default = self._lex(d or "")
                        out.append(a)
                else:
                    return None
            elif ch == "u":
                d, i = _braced(i)
                if d is None:
                    return None
                out.append(Arg("delim", delim=self._lex(d)))
            elif ch == "g":
                out.append(Arg("o", open="{", close="}"))
            elif ch == "l":
                out.append(Arg("until_group"))
            elif ch in "vbeEx":
                return None  # 不支持的参数型 → 整条不登记
            else:
                continue  # 未知字母跳过（容错）
        return out

    def _lex(self, s: str) -> list[Tok]:
        """字面串 → token 列（xparse 默认值/``u{}`` 定界用；共享 cats）。"""
        return list(Mouth(s, -1, self.cats))

    # ------------------------------------------------------------ \let/\newif/\catcode

    def _do_let(self, trig: Tok) -> Tok | None:
        r"""``\let\a[=]\b``（Primitives.py:369-374 + Context.py:1175-1193）。

        cs 目标 → 当时表项**快照**（MacroDef/IfCond/IfSetter/原语名 str /
        None）；非 cs → 字面 token 别名。
        """
        trace = self._trace = []
        nt = self._rt_skip(trace)
        if nt is None or nt.kind not in ("cs", "active"):
            self.unread(trace)
            return trig
        self._read_eq(trace)
        src = self._rt_skip(trace)
        if src is None:
            self.unread(trace)
            return trig
        if src.kind == "cs":
            e = self.macros.lookup(src.text)
            if e is not None:
                tgt = self.macros.resolve(e)
            elif src.text in _PRIMS or src.text.startswith("if"):
                tgt = src.text  # 原语名引用
            else:
                tgt = None
            self.macros.set(nt.text, Alias(tgt))
        else:
            self.macros.set(nt.text, Alias(src))
        return None

    def _do_newif(self, trig: Tok) -> Tok | None:
        r"""``\newif\ifX`` 三项登记（Context.newif Context.py:1008-1041）。

        ``\ifX`` → ``IfCond`` 求值项；``\Xtrue``/``\Xfalse`` → ``IfSetter``
        写 ``ifflags[flag]``，token 本体原样交分段器。
        """
        trace = self._trace = []
        nt = self._rt_skip(trace)
        if nt is None or nt.kind != "cs" or not nt.text.startswith("if"):
            self.unread(trace)
            self._warn("def_parse_fail", trig, "newif name")
            return trig
        flag = nt.text[2:]
        self.ifflags[flag] = False
        self.macros.set(nt.text, IfCond(flag))
        self.macros.set(flag + "true", IfSetter(flag, value=True))
        self.macros.set(flag + "false", IfSetter(flag, value=False))
        return None

    def _do_catcode(self, trig: Tok) -> Tok | None:
        r"""``\catcode`<ch>=<num>``（Primitives.py:401-411）。"""
        trace = self._trace = []
        t = self._rt_skip(trace)
        if t is None or t.text != "`":
            self.unread(trace)
            return trig
        ct = self._rt(trace)
        if ct is None:
            self.unread(trace)
            return trig
        ch = ct.text[0] if ct.text else "\x00"
        eq = self._rt_skip(trace)
        if eq is not None and eq.text != "=":
            self._pushback(trace, eq)  # '=' 可选
        v = self._read_number()
        if v is None:
            self.unread(trace)
            return trig
        self.cats.set(ch, int(v) & 15)
        return None

    # ------------------------------------------------------------ \input 族

    def _do_input(self, trig: Tok, name: str) -> Tok | None:  # noqa: C901, PLR0911, PLR0912, PLR0915 — 八形态参数语法平铺即 §7 触发面
        r"""``\input`` 族：解析文件名 → 压新 Mouth 进 ``inputs``（§10）。

        失败（不存在/超深/已见）→ warning + 参数回吐 + ``\input`` 本体交出。
        """
        trace = self._trace = []
        shell = False
        tag: str | None = None
        fname: str | None = None
        if name in ("input", "include"):
            if name == "input":
                # 先试 {file}，再试裸文件名（[A-Za-z0-9._/-]+ 至空白/反斜杠）
                grp = self._read_grouping(trace, "{", "}")
                if grp is not None:
                    fname = _surface(grp).strip()
                else:
                    fname = self._read_bare_filename(trace)
            else:
                grp = self._read_grouping(trace, "{", "}")
                if grp is None:
                    self.unread(trace)
                    return trig
                fname = _surface(grp).strip()
        elif name in ("subfile", "includestandalone"):
            grp = self._read_grouping(trace, "{", "}")
            if grp is None:
                self.unread(trace)
                return trig
            fname, shell = _surface(grp).strip(), True
        elif name in ("import", "subimport"):
            g1 = self._read_grouping(trace, "{", "}")
            g2 = self._read_grouping(trace, "{", "}") if g1 is not None else None
            if g1 is None or g2 is None:
                self.unread(trace)
                return trig
            sub = _surface(g1).strip()
            fn = _surface(g2).strip()
            fname = str(Path(sub) / fn) if sub else fn
        elif name == "InputIfFileExists":
            grp = self._read_grouping(trace, "{", "}")
            if grp is None:
                self.unread(trace)
                return trig
            fname = _surface(grp).strip()  # {then}{else} 留在流内
        elif name == "CatchFileBetweenTags":
            t = self._rt_skip(trace)
            if t is not None and t.kind != "cs":
                self._pushback(trace, t)
            g1 = self._read_grouping(trace, "{", "}")
            g2 = self._read_grouping(trace, "{", "}") if g1 is not None else None
            if g1 is None or g2 is None:
                self.unread(trace)
                return trig
            fname, tag = _surface(g1).strip(), _surface(g2).strip()
        if not fname:
            self.unread(trace)
            return trig
        file_dir = self._file_dir_of(trig)
        hit = self._resolve_input(fname, file_dir, self.root_dir)
        if hit is None or str(Path(hit).resolve()) in self._seen:
            if hit is None:
                self._warn("missing_input", trig, f"{name}:{fname}")
            self.unread(trace)
            return trig
        if len(self.inputs) > MAX_INPUTS:
            self._warn("missing_input", trig, f"depth>{MAX_INPUTS}:{fname}")
            self.unread(trace)
            return trig
        try:
            sub = decode_tex(Path(hit).read_bytes())
        except OSError:
            self._warn("missing_input", trig, f"{name}:{fname}")
            self.unread(trace)
            return trig
        if shell:
            sub = strip_doc_shell(sub)
        if tag is not None:
            region = self._extract_tag_region(sub, tag)
            if region is None:
                self._warn("missing_input", trig, f"tag:{tag}@{fname}")
                self.unread(trace)
                return trig
            sub = region
        self.push_source(sub, hit)
        return None

    def _read_bare_filename(self, trace: list[Tok]) -> str | None:
        r"""``\input file`` 裸名形：``[A-Za-z0-9._/-]+`` 至空白/反斜杠。"""
        chars: list[str] = []
        while True:
            t = self._rt(trace)
            if t is None:
                break
            if t.kind in ("letter", "other") and t.text in _FILENAME_CHARS:
                chars.append(t.text)
                continue
            self._pushback(trace, t)
            break
        return "".join(chars) or None

    def _file_dir_of(self, t: Tok) -> str:
        r"""Token 所在文件的目录（``\input`` 查找序第一级）。"""
        fid = t.pos[0]
        if 0 <= fid < len(self.file_paths) and self.file_paths[fid]:
            return str(Path(self.file_paths[fid]).parent)
        return self.root_dir or "."

    @staticmethod
    def _resolve_input(  # noqa: C901 — 查找序四级候选平铺即 §7 语义
        fname: str, file_dir: str, root_dir: str
    ) -> str | None:
        """查找序：including 目录 → 根目录 → basename 补 ``.tex`` → 裸名。"""
        cands = (
            [fname]
            if fname.lower().endswith(".tex")
            else [fname, fname + ".tex", fname + ".TEX"]
        )
        for d in (file_dir, root_dir):
            if not d:
                continue
            for c in cands:
                p = Path(d) / c
                if p.exists():
                    return str(p)
        stem = Path(fname).name
        for d in (file_dir, root_dir):
            if not d:
                continue
            for ext in (".tex", ".TEX"):
                p = Path(d) / (stem + ext)
                if p.exists():
                    return str(p)
        for d in (file_dir, root_dir):
            if not d:
                continue
            p = Path(d) / fname
            if p.exists():
                return str(p)
        return None

    @staticmethod
    def _extract_tag_region(tex: str, tag: str) -> str | None:
        r"""``\CatchFileBetweenTags`` 标签区：``%<*tag>`` … ``%</tag>``。"""
        start_rx = re.compile(r"%\s*<\*?" + re.escape(tag) + r">")
        end_rx = re.compile(r"%\s*</" + re.escape(tag) + r">")
        s = start_rx.search(tex)
        if not s:
            return None
        e = end_rx.search(tex, s.end())
        return tex[s.end() : e.start() if e else len(tex)]

    # ------------------------------------------------------------ expandafter/csname/ifundefined

    def _do_expandafter(self, _trig: Tok) -> Tok | None:
        r"""``\expandafter\t1\t2``：``t2`` 展开一次再推回（Primitives.py:495-512）。

        推回序为 ``[t1]+展开结果``；触发 token 本体已消费不回吐（gap literal）。
        """
        t1 = self.read()
        t2 = self.read()
        if t1 is None:
            self.unread([t2] if t2 is not None else [])
            return None
        if t2 is None:
            self.unread([t1])
            return None
        expanded = self._expand_once(t2)
        self.unread([t1, *expanded])
        return None

    def _expand_once(self, t: Tok) -> list[Tok]:  # noqa: PLR0911 — 表项/原语各态一分支
        r"""单步展开（``\expandafter`` 用）：宏 → 读参代入；其余 → ``[t]``。"""
        if t.kind != "cs":
            return [t]
        e = self.macros.lookup(t.text)
        r = self.macros.resolve(e)
        if isinstance(r, MacroDef):
            if r.kind not in _EXPAND_KINDS or not self._can_expand(t):
                return [t]
            self._trace = []
            try:
                return self._invoke(t, r)
            except ArgMismatch:
                self.unread(self._trace)
                return [t]
        if isinstance(r, str):
            return self._expand_once(Tok("cs", r, t.pos, t.gen, t.origin))
        if r is None and t.text == "csname":
            return [self._read_csname()]
        return [t]

    def _do_csname(self, _trig: Tok) -> Tok | None:
        r"""``\csname..\endcsname`` → 合成 cs token 推回（Primitives.py:413-424）。"""
        self.unread([self._read_csname()])
        return None

    def _read_csname(self) -> Tok:
        r"""读到 ``\endcsname`` 合成 cs；流尽 → 空名 cs（容忍）。"""
        name: list[str] = []
        start: tuple[int, int, int] | None = None
        while True:
            t = self.read()
            if t is None:
                break
            if start is None:
                start = t.pos
            if t.kind == "cs" and t.text == "endcsname":
                break
            name.append(str(t))
        pos = start if start is not None else (-1, -1, -1)
        return Tok("cs", "".join(name), pos)

    def _do_ifundefined(self, _trig: Tok) -> Tok | None:
        r"""``\@ifundefined{name}{T}{F}`` 选支推回（Base/LaTeX ``__init__.py:36-45``）。

        ``name`` 已定义（宏表/原语/内建名集）→ 推 ``F``；否则推 ``T``。
        """
        trace = self._trace = []
        name = self._read_env_name(trace)
        if name is None:
            t = self._rt_skip(trace)
            name = t.text if t is not None and t.kind == "cs" else ""
        if name is None:
            name = ""
        t_arg = self._read_grouping(trace, "{", "}")
        f_arg = self._read_grouping(trace, "{", "}")
        t_arg = t_arg or []
        f_arg = f_arg or []
        defined = (
            self.macros.lookup(name) is not None or name in _PRIMS or name in _BUILTINS
        )
        self.unread(f_arg if defined else t_arg)
        return None

    # ------------------------------------------------------------ \if 族

    def _do_if(self, t: Tok) -> Tok | None:
        r"""``\if`` 两档（§8.6/§7.1）。

        可求值 → ``process_if(which)`` 只推回选中支；不可求值 → 条件已按
        语法消费（→ gap literal）+ ``\ifX`` 本体作界标直交分段器，两分支
        照常进流（召回优先，编译端 TeX 自决）。
        """
        which = self._eval_if(t.text)
        if which is None:
            return t
        self.process_if(which)
        return None

    def _eval_if(self, name: str) -> bool | int | None:  # noqa: C901, PLR0911, PLR0912 — 可求值族平铺即 §8.6 表
        r"""``\if`` 条件求值：``None`` → 界标档。条件 token 无条件消费。"""
        if name == "iftrue":
            return True
        if name == "iffalse":
            return False
        if name == "ifmmode":
            return self.math_depth > 0
        if name == "ifhmode":
            return True  # plasTeX 常量（Primitives.py:253-257）；tables.IF_CONST 写反了不消费
        if name == "ifvmode":
            return False  # 同上（Primitives.py:247-251）
        if name == "ifinner":
            return False
        if name in ("ifeof", "ifvoid", "ifhbox", "ifvbox"):
            self._read_number()  # 寄存器号吃掉（\ifeof0）
            return False
        if name in ("ifnum", "ifdim"):
            v1 = self._read_number()
            rel = self._read_relation()
            v2 = self._read_number()
            if v1 is None or v2 is None or rel is None:
                return None
            if rel == "<":
                return v1 < v2
            if rel == ">":
                return v1 > v2
            return v1 == v2
        if name == "ifodd":
            v = self._read_number()
            return (int(v) % 2 == 1) if v is not None else None
        if name == "ifcase":
            v = self._read_number()
            # process_if 的 int 槽要真 int——_read_number 为 ifdim 统一返回 float
            return int(v) if v is not None and v >= 0 else None
        if name in ("if", "ifcat"):
            t1 = self._read_if_tok()
            t2 = self._read_if_tok()
            if t1 is None or t2 is None or t1.kind == "cs" or t2.kind == "cs":
                return None
            if name == "if":
                return _tok_eq(t1, t2)
            return t1.text.isalpha() == t2.text.isalpha()  # ifcat：字母类粗粒度
        if name == "ifx":
            t1 = self._read_if_tok()
            t2 = self._read_if_tok()
            if t1 is None or t2 is None:
                return None
            if t1.kind == "cs" or t2.kind == "cs":
                if t1.kind == "cs" and t2.kind == "cs" and t1.text == t2.text:
                    return True
                return None  # 宏比较 → 界标（召回优先）
            return _tok_eq(t1, t2)
        if name == "ifdefined":
            t = self._read_if_tok()
            if t is None or t.kind != "cs":
                return None
            return (
                True
                if self.macros.lookup(t.text) is not None
                or t.text in _PRIMS
                or t.text in _BUILTINS
                else None
            )
        if name == "ifcsname":
            toks: list[Tok] = []
            while True:
                x = self.read()
                if x is None:
                    return None
                if x.kind == "cs" and x.text == "endcsname":
                    break
                toks.append(x)
            cname = _surface(toks).strip()
            return (
                True
                if self.macros.lookup(cname) is not None or cname in _BUILTINS
                else None
            )
        return None  # 未知 if* → 界标

    def _read_if_tok(self) -> Tok | None:
        r"""``\if/\ifx`` 的一个比较 token（跳过空白）。"""
        while True:
            t = self.read()
            if t is None or t.kind != "space":
                return t

    def _read_relation(self) -> str | None:
        """``<``/``>``/``=`` 关系符（非符 → 回吐）。"""
        t = self._read_if_tok()
        if t is not None and t.kind != "cs" and t.text in _REL_CHARS:
            return t.text
        if t is not None:
            self.unread([t])
        return None

    def _read_number(self) -> float | None:  # noqa: C901, PLR0911, PLR0912, PLR0915 — TeX <number> 各形态一分支
        r"""读 TeX 数（``readInteger`` TeX.py:1592-1643 砍半）。

        可选符号 + 数字串 / ``'77`` 八进制 / ``"ff`` 十六进制 / ``` `` `x`` 字符码 /
        ``\cs`` 寄存器（消费但不求值）/ ``{..}`` 组（同）。不可求值 → ``None``。
        """
        sign = 1.0
        while True:
            t = self.read()
            if t is None:
                return None
            if t.kind == "space":
                continue
            if t.kind != "cs" and t.text == "+":
                continue
            if t.kind != "cs" and t.text == "-":
                sign = -sign
                continue
            break
        if t.kind != "cs" and t.text and t.text in _DIGITS:
            digits = [t.text]
            while True:
                t2 = self.read()
                if t2 is None:
                    break
                if t2.kind != "cs" and t2.text in _DIGITS:
                    digits.append(t2.text)
                    continue
                self.unread([t2])
                break
            return sign * int("".join(digits))
        if t.kind != "cs" and t.text == "'":  # 八进制
            digits = []
            while True:
                t2 = self.read()
                if t2 is None:
                    break
                if t2.kind != "cs" and t2.text in "01234567":
                    digits.append(t2.text)
                    continue
                self.unread([t2])
                break
            return sign * int("".join(digits) or "0", 8)
        if t.kind != "cs" and t.text == '"':  # 十六进制
            digits = []
            while True:
                t2 = self.read()
                if t2 is None:
                    break
                if t2.kind != "cs" and t2.text.lower() in "0123456789abcdef":
                    digits.append(t2.text)
                    continue
                self.unread([t2])
                break
            return sign * int("".join(digits) or "0", 16)
        if t.kind != "cs" and t.text == "`":  # 字符码
            t2 = self.read()
            if t2 is None:
                return None
            return sign * ord(t2.text[0] if t2.text else "\x00")
        if t.kind == "lbrace":
            trace: list[Tok] = [t]
            self._read_balanced(trace)  # 组：消费不求值
            return None
        if t.kind == "cs":
            # 寄存器/内部量：消费下标数/`x/{group}，不求值
            t2 = self.read()
            if t2 is None:
                return None
            if t2.kind != "cs" and t2.text in _DIGITS:
                while True:
                    t3 = self.read()
                    if t3 is None:
                        break
                    if t3.kind != "cs" and t3.text in _DIGITS:
                        continue
                    self.unread([t3])
                    break
                return None
            if t2.kind != "cs" and t2.text == "`":
                self.read()
                return None
            if t2.kind == "lbrace":
                trace = [t2]
                self._read_balanced(trace)
                return None
            self.unread([t2])
            return None
        self.unread([t])
        return None

    def process_if(  # noqa: C901 — 案例收集循环分支平铺即 TeX.py:531-585
        self,
        which: bool | int,  # noqa: FBT001 — \ifcase 值与 True/False 同槽（plasTeX which 同形）
    ) -> None:
        r"""``processIfContent`` 移植（TeX.py:531-585）。

        原始流收集 case 到 ``\fi``（``\else/\or`` 分案例；任何真 ``if*``
        计嵌套——但宏表里的 ``if*`` **MacroDef 不计**，``\newif\ifX`` 整对
        保留）；收尾 ``\fi`` 不推回，只 ``unread(选中支)``。
        """
        cases: list[list[Tok]] = [[]]
        else_idx: int | None = None  # \else 支索引（\ifcase 超界回落地）
        nesting = 0
        terminated = False
        while True:
            t = self.read()
            if t is None:
                break
            name = t.text if t.kind == "cs" else ""
            if name == "newif":
                cases[-1].append(t)
                nxt = self.read()
                if nxt is not None:
                    cases[-1].append(nxt)
                continue
            if name.startswith("if"):
                r = self.macros.resolve(self.macros.lookup(name))
                if isinstance(r, (MacroDef, Tok)):
                    cases[-1].append(t)  # 用户宏 if* → 不计嵌套（scanner 同款修正）
                    continue
                cases[-1].append(t)
                nesting += 1
                continue
            if name == "fi":
                if not nesting:
                    terminated = True
                    break
                cases[-1].append(t)
                nesting -= 1
                continue
            if not nesting and name in ("else", "or"):
                if name == "else":
                    else_idx = len(cases)
                cases.append([])
                continue
            cases[-1].append(t)
        if not terminated:
            self._warn("if_unterminated", None, "if")
        cases.append([])  # 无 else 支的默认（TeX.py:582）
        idx = (
            which
            if isinstance(which, int) and not isinstance(which, bool)
            else (0 if which else 1)
        )
        if idx >= len(cases):
            # \ifcase 超界 → \else 支；无 \else → 追加的空支
            # （plasTeX 此处 IndexError 裸奔；TeX 语义 = else 支）
            idx = else_idx if else_idx is not None else len(cases) - 1
        self.unread(cases[idx])

    # ------------------------------------------------------------ 分类

    def _classify(
        self, body: list[Tok], nargs: int
    ) -> tuple[str, str, tuple[bool, ...]]:
        r"""定义时分类（§6.1 + §6.2 二分）。

        ``env_begin/env_end`` → ``classify_body`` 表面全匹配；
        无文本 → ``math``（含数学特征）/``opaque``；
        有文本 → ``transparent_expand``（体去 ``#i`` 位仍有文本）
        /``transparent_inline``。
        """
        surf = _surface(body)
        mk, target = classify_body(surf)
        if mk is MacroKind.ENV_BEGIN:
            return "env_begin", target, ()
        if mk is MacroKind.ENV_END:
            return "env_end", target, ()
        if not body_has_text(surf):
            return ("math" if self._has_math(body) else "opaque"), "", ()
        rest = _surface(self._strip_param_refs(body))
        kind = "transparent_expand" if body_has_text(rest) else "transparent_inline"
        return kind, "", protected_param_positions(surf, nargs)

    @staticmethod
    def _has_math(body: list[Tok]) -> bool:
        r"""体含数学特征：``$``/``^``/``_``/``\(``/``\[``/数学 cs 名。"""
        for t in body:
            if t.kind == "mathshift":
                return True
            if t.kind == "cs" and t.text in _MATH_CS:
                return True
            if t.kind != "cs" and t.text in ("^", "_"):
                return True
        return False

    @staticmethod
    def _strip_param_refs(body: list[Tok]) -> list[Tok]:
        """去 ``#n`` 参数引用对（§6.2 判据：体文本是否全经参数位进入）。"""
        out: list[Tok] = []
        i, n = 0, len(body)
        while i < n:
            t = body[i]
            if t.kind == "param" and i + 1 < n and body[i + 1].text.isdigit():
                i += 2
                continue
            out.append(t)
            i += 1
        return out
