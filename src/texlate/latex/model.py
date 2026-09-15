"""latex 管线核心数据结构（纯数据层，不反向依赖）。

规格：docs/07-latex-pipeline.md §2。区间一律半开 ``[start, end)``，
相对**当前 scan 输入串**的偏移；子扫描器经 ``base`` 换算全局偏移。
"""

from __future__ import annotations

import re
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
    EXPAND = auto()  # 展开组 identity 面（segmenter：体=调用点 vtex 切片）


@dataclass(slots=True)
class Chunk:
    """可译段。content 为渲染形（可内嵌 ``[[TYPE_n]]``）。"""

    id: int
    content: str
    context: str = (
        "para"  # "para"|"item"|chunk-arg 命令名（"paragraph" 专指 \paragraph 节题）
    )
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
    delim: str = ""  # d/D/r/R/t 的定界符（'<>'）或 e 的 token 表（'^_'）
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
    #   letters_cut|expansion_overflow|if_unterminated|missing_input|
    #   gen_overflow|ph_collision|env_mismatch
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
    # 叙事序虚拟文本（segmenter 版恒 == 单文件入参；多文件 = flatten 同构）。
    # pieces/chunk.span 的坐标系；v1 字节 scanner 下留空（坐标即原 tex）。
    vtex: str = ""


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
    ph_reserved: set[str] = field(
        default_factory=set
    )  # 源文自带 [[X_n]] 形字面 → 签发避让


# ---------------------------------------------------------------- 字符级原语
# 单遍逐字符扫描的共享低层工具（macro_table / scanner / flatten 三方消费）。

_WS = " \t\n\r"
_PAR_BREAK_RX = re.compile(r"\n[ \t\r]*\n")


def ws_skip(tex: str, i: int) -> int:
    r"""跳过 `` \\t\\n\\r``，返回下一个非空白位置。"""
    n = len(tex)
    while i < n and tex[i] in _WS:
        i += 1
    return i


def ws_skip_arg(tex: str, i: int) -> int:
    r"""参数读取专用 ws_skip：不跨段落边界；``%`` 注释透明跳过。

    TeX 不定界参数扫描只跳 space token——``\\n[ \\t\\r]*\\n`` 即 ``\\par``，
    停在 ``\\par`` 涉及的 ``\\n`` 处（调用方看到空白字符 → 参数不成立）。
    ``%`` 吃掉到行尾**含换行**；吃注释后处新行态——紧跟的空行仍是
    ``\\par``（``\\section% c\\n\\n{T}`` 不取参，``\\section% c\\n{T}`` 取参）。
    停止位约定：``\\par`` 对内任一 ``\\n`` 位置重入本函数仍停（幂等）——
    ``_args`` 按参数项循环从停止位重扫（scanner-audit F4-par 修复）。
    scanner-audit F4：此前遇 ``%`` 即停 → ``\\cite%\\n{key}`` 参数错位泄漏。
    """
    n = len(tex)
    while i < n:
        c = tex[i]
        if c == "%":
            k = tex.find("\n", i)
            if k < 0:
                return n
            i = k + 1
            continue  # 新行态交给 \n 分支统一判（含下方后向检查）
        if c not in _WS:
            return i
        if c == "\n":
            k = i + 1
            while k < n and tex[k] in " \t\r":
                k += 1
            if k < n and tex[k] == "\n":
                return i
            # 幂等：本 \n 是某 par 对的后一个换行（前向已看不到配对首 \n）
            # ——回看前一非空白若为 \n 同样停住
            k = i - 1
            while k >= 0 and tex[k] in " \t\r":
                k -= 1
            if k >= 0 and tex[k] == "\n":
                return i
        i += 1
    return i


def has_par_break(s: str) -> bool:
    r"""``s`` 内含段落边界（``\\n`` + 空白* + ``\\n``，与主循环 §3.1.4 同判据）。"""
    return bool(_PAR_BREAK_RX.search(s))


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
    r"""``tex[i]=='['`` → 匹配 ``']'`` 的后一位；允许内嵌 ``{..}`` 组与注释。

    迭代实现（原为自递归）：``[`` 嵌套用深度计数——规则与递归版逐条同构
    （``{`` 组整跳、``%``→EOL、``\\\\`` 跳双），但深嵌套不再爆栈
    （铁律 1「绝不抛异常」；scanner-audit F1：``[``×1500 曾 RecursionError）。
    """
    if i >= len(tex) or tex[i] != "[":
        return None
    j, n = i + 1, len(tex)
    depth = 1
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
            depth += 1
            j += 1
            continue
        if c == "%":
            k = tex.find("\n", j)
            j = n if k < 0 else k + 1
            continue
        if c == "]":
            depth -= 1
            if depth == 0:
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
    r"""``{name}`` 读取：ws 后 ``{env}`` → (名, ``}`` 后一位)；否则 (None, i)。

    ``\\begin/\\end`` 的参数读取同样不跨段落边界（ws_skip_arg）。
    """
    pos = ws_skip_arg(tex, i)
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


def env_opt_is_format(env: str, content: str) -> bool:
    r"""``\begin{env}[opt]`` 的 ``[opt]``：版式参（吃掉）还是标题正文（放行）。

    scanner-audit F6：docs/07 §3.5 原规格无条件吞 ``[opt]`` → theorem/
    lemma/proof 类环境标题永不进 chunk（corpus_v3 命中 8.3%，召回缺口）。
    判定（corpus 实测分布校准）：

    - 列表容器 env（itemize/enumerate 等）的 opt 恒为版式
      （``[noitemsep]``/``[label=…]``）——无条件吃；
    - 其余看内容：空 / 数字开头 / 纯位置字母 / 含 ``=*\#|!~,()<>:;``
      → 版式；否则当正文放行（回落主流进 chunk，标题恢复可译）。

    实现注：``ARG_TRANSPARENT_ENVS``/``OPT_*`` 常量在 tables.py——此处
    本地判定以避免 model→tables 反向依赖（model 是纯数据层）。
    """
    from texlate.latex.tables import (  # noqa: PLC0415 — 延迟破环：model 不入 tables 的 import 链
        ARG_TRANSPARENT_ENVS,
        OPT_FMT_CHARS,
        OPT_POS_LETTERS,
    )

    if env in ARG_TRANSPARENT_ENVS:
        return True
    s = content.strip()
    if not s:
        return True  # ``[]`` 空参
    if s[0].isdigit():
        return True  # ``[1]``/``[1.]`` 编号参
    if all(ch in OPT_POS_LETTERS for ch in s):
        return True  # ``[t]``/``[htb]``/``[mr]`` 位置参
    return any(ch in OPT_FMT_CHARS for ch in s)


def skip_verb_at(tex: str, name: str, j: int) -> int | None:
    r"""``\\verb``/``\\lstinline`` 定界体跳过：返回体后一位；非定界形 → None。

    ``j`` = 命令名后一位。``\\verb*?``、``\\lstinline[opt]``
    前缀与 ``{...}`` 配对形都认；定界符搜索上限 = 下一 ``\\n``（W9）。
    scanner/flatten/_find_env_end/_process_if 四处共用同一判据。
    """
    n = len(tex)
    k = j
    if name == "verb" and k < n and tex[k] == "*":
        k += 1
    if name == "lstinline":
        k = ws_skip(tex, k)
        if k < n and tex[k] == "[":
            e2 = match_bracket(tex, k)
            if e2:
                k = ws_skip(tex, e2)
    if k < n:
        d = tex[k]
        if d == "{":
            e = match_brace(tex, k, verbatim=True)
            if e:
                return e
        elif d not in _WS:
            eol = tex.find("\n", k + 1)
            limit = n if eol < 0 else eol
            e = tex.find(d, k + 1, limit)
            if e > 0:
                return e + 1
    return None
