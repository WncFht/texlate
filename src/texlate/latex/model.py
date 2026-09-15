"""latex 管线核心数据结构（纯数据层，不反向依赖）。

规格：docs/07-latex-pipeline.md §2。区间一律半开 ``[start, end)``，
相对**当前 scan 输入串**的偏移；子扫描器经 ``base`` 换算全局偏移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.latex.macro_table import MacroTable
    from texlate.latex.placeholder import PlaceholderIssuer


@dataclass(slots=True)
class Span:
    """半开字节区间 ``[start, end)``。"""

    start: int
    end: int

    def __len__(self) -> int:
        """区间长度 ``end - start``。"""
        return self.end - self.start


class PieceKind(Enum):
    """Piece 三态。"""

    LITERAL = auto()  # 逐字段：注释/preamble/边界命令/环境 tag/宏定义/兜底
    PROTECTED = auto()  # [[TYPE_n]]，本体在 ph_map
    CHUNK_REF = auto()  # [[CHUNK_n]]，本体在 chunks[i]


@dataclass(slots=True)
class Piece:
    """pieces 无缝平铺 ``[0, n)`` —— 头号不变式。

    text 是 protected_tex 中的渲染形：LITERAL=tex[span]，其余=占位符串。
    """

    kind: PieceKind
    span: Span
    text: str
    env: str | None = None


class PhType(Enum):
    """``[[TYPE_n]]`` 的 TYPE 全枚举（CHUNK 不在此列：走 chunks[] 而非 ph_map）。"""

    MATH = auto()
    VERB = auto()
    ENV = auto()
    CITE = auto()
    REF = auto()
    LABEL = auto()
    URL = auto()
    GRAPHICS = auto()
    BIB = auto()
    CMD = auto()
    HREF = auto()
    MACRO = auto()
    KEY = auto()
    AUTHOR = auto()
    COMMENT = auto()  # in_arg 注释（泄漏 B 修复）
    COND = auto()  # in_arg 条件式（泄漏 D 修复）
    ENVTAG = auto()  # in_arg 透明环境 begin/end 行


@dataclass(slots=True)
class Chunk:
    """可译段。content 为渲染形（可内嵌 ``[[TYPE_n]]``）。"""

    id: int
    content: str
    context: str = "paragraph"  # "paragraph" | "item" | chunk-arg 命令名
    span: Span = field(default_factory=lambda: Span(0, 0))
    env: str | None = None
    placeholders: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ArgSpan:
    """一次参数读取的结果（替代 spike 的匿名四元组 ``(cs,ce,fs,fe)``）。"""

    content: Span  # 去括号内容区间
    full: Span  # 含括号整段（单 token 参数时 content==full）
    spec: ArgSpec | None = None


class MacroKind(Enum):
    """宏三分类（登记时一次判定，调用点零分析）。"""

    ENV_BEGIN = auto()  # 体 ≡ \begin{X}
    ENV_END = auto()  # 体 ≡ \end{X}
    OPAQUE = auto()  # 体无自然文本 → 整调用 [[MACRO]]
    TRANSPARENT = auto()  # 体含自然文本 → 参数按位分流（protect_args）
    LITERAL = auto()  # \newif 注册的 \Xtrue/\Xfalse 等


@dataclass(slots=True)
class ArgSpec:
    """xparse 参数签名项（docs/07 §5.2）。"""

    kind: str  # 'm'|'o'|'O'|'s'|'d'|'D'|'r'|'R'|'v'|'e'|'t'|'b'
    delim: str = ""  # d/D/r/R/t 的定界符，如 '<>'
    default: str | None = None  # O/D/R 的默认值


@dataclass(slots=True)
class MacroEntry:
    """宏表条目（spike ``Macro`` 的 argspec 化扶正）。"""

    name: str
    spec: list[ArgSpec] = field(default_factory=list)
    kind: MacroKind = MacroKind.TRANSPARENT
    target_env: str = ""  # ENV_BEGIN/ENV_END 专用
    protect_args: tuple[bool, ...] = ()  # TRANSPARENT：参数位 → [[KEY]]
    body: str = ""
    def_site: int = -1  # 定义点偏移（全局，调试/审计用）


@dataclass(slots=True)
class EnvEntry:
    r"""``\newenvironment`` 登记（spike ``env:`` 前缀死代码的扶正，W6）。"""

    name: str
    nargs: int = 0
    kind: str = "transparent"  # "protected" | "transparent"（启发式）


@dataclass(slots=True)
class ScanWarning:
    """可观测性（泄漏类 bug 的第一手线索）。"""

    kind: str  # unclosed_env|unpaired_dollar|stray_end|debt_repair|def_parse_fail|
    #   letters_cut|expansion_overflow|if_unterminated|missing_input
    pos: int
    detail: str


@dataclass(slots=True)
class ScanResult:
    """扫描产物。"""

    protected_tex: str
    chunks: list[Chunk]
    ph_map: dict[str, str]  # "[[TYPE_n]]" → 原文段（可内嵌占位符）
    macros: MacroTable
    pieces: list[Piece] = field(default_factory=list)
    inputs: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[ScanWarning] = field(default_factory=list)


class ScanMode(Enum):
    """扫描模式。"""

    NORMAL = auto()
    MINED_ONLY = auto()  # 保护环境/参数内部：run 全 literal，只挖 chunk-arg


@dataclass(slots=True)
class ScanState:
    r"""一切可变状态的共享容器（spawn 只共享这一个引用，W7 扶正）。

    ``ifflags`` 是 ``\\newif`` 旗标表（\\\\if 两档求值用，docs/07 §8.2/§8.6）。
    ``steps`` 是展开步数回压计数（BUDGET，docs/07 §8.2/§8.3）。
    """

    issuer: PlaceholderIssuer
    ph_map: dict[str, str]
    chunks: list[Chunk]
    macros: MacroTable
    inputs: list[tuple[int, str]]
    warnings: list[ScanWarning]
    ifflags: dict[str, bool] = field(default_factory=dict)
    steps: int = 0


# ---------------------------------------------------------------- 字符级原语
# 单遍逐字符扫描的共享低层工具（macro_table / scanner / flatten 三方消费）。

_WS = " \t\n"


def ws_skip(tex: str, i: int) -> int:
    r"""跳过 `` \\t\\n``，返回下一个非空白位置。"""
    n = len(tex)
    while i < n and tex[i] in _WS:
        i += 1
    return i


def match_brace(tex: str, i: int, *, verbatim: bool = False) -> int | None:
    r"""``tex[i]=='{'`` → 匹配 ``'}'`` 的后一位；未闭 → None。

    verbatim=False 时 ``%..EOL`` 内括号不计（TeX 语义）；``\\X`` 跳两字符。
    """
    if i >= len(tex) or tex[i] != "{":
        return None
    depth, j, n = 1, i + 1, len(tex)
    while j < n:
        c = tex[j]
        if c == "\\":
            j += 2
            continue
        if c == "%" and not verbatim:
            k = tex.find("\n", j)
            j = n if k < 0 else k + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return None


def match_bracket(tex: str, i: int) -> int | None:
    """``tex[i]=='['`` → 匹配 ``']'`` 的后一位；允许内嵌 ``{..}`` 组与注释。"""
    if i >= len(tex) or tex[i] != "[":
        return None
    j, n = i + 1, len(tex)
    while j < n:
        c = tex[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            e = match_brace(tex, j)
            j = e or j + 1
            continue
        if c == "[":
            e = match_bracket(tex, j)
            j = e or j + 1
            continue
        if c == "%":
            k = tex.find("\n", j)
            j = n if k < 0 else k + 1
            continue
        if c == "]":
            return j + 1
        j += 1
    return None


def read_cmd_name(tex: str, i: int) -> tuple[str, int]:
    r"""``tex[i]=='\\\\'`` → (名字, 命令后一位)。字母+``@`` 串或非字母单字符。"""
    j = i + 1
    n = len(tex)
    if j < n and tex[j].isalpha():
        k = j
        while k < n and (tex[k].isalpha() or tex[k] == "@"):
            k += 1
        return tex[j:k], k
    if j < n:
        return tex[j], j + 1
    return "", j


def env_name_at(tex: str, i: int) -> tuple[str | None, int]:
    """``{name}`` 读取：ws 后 ``{env}`` → (名, ``}`` 后一位)；否则 (None, i)。"""
    pos = ws_skip(tex, i)
    if pos < len(tex) and tex[pos] == "{":
        e = match_brace(tex, pos)
        if e:
            return tex[pos + 1 : e - 1].strip(), e
    return None, i


def unescaped_dollar_odd(body: str) -> bool:
    """``body`` 内未转义 ``$`` 计数为奇 → True（math-debt 判据）。"""
    odd = False
    i, n = 0, len(body)
    while i < n:
        if body[i] == "\\":
            i += 2
            continue
        if body[i] == "$":
            odd = not odd
        i += 1
    return odd
