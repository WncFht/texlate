"""latex 管线核心数据结构 + 扫描层共享常量（数据层，不反向依赖）。

规格：docs/spec/latex-pipeline.md。区间一律半开 ``[start, end)``，
相对**当前 scan 输入串**的偏移；子扫描器经 ``base`` 换算全局偏移。

字符级扫描原语（``ws_skip``/``match_brace``/…）已扶正于 ``chars.py``
（零依赖叶）——下方 eager 再出口只为保旧 ``from .model import X``
调用面：``model → chars`` 是单向边，依赖图无环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

# 兼容再出口：字符原语扶正于 ``chars.py``（零依赖叶），旧
# ``from texlate.latex.model import ws_skip`` 调用面不破坏——
# model→chars 单向边，无环。
from texlate.latex.chars import (  # noqa: F401
    env_name_at,
    has_par_break,
    match_brace,
    match_bracket,
    read_cmd_name,
    skip_verb_at,
    unescaped_dollar_odd,
    ws_skip,
    ws_skip_arg,
)

if TYPE_CHECKING:
    from texlate.latex.gullet import ScopeMacroTable
    from texlate.latex.mouth import Tok
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


class MacroKind(Enum):
    """宏三分类（登记时一次判定，调用点零分析）。"""

    ENV_BEGIN = auto()  # 体 ≡ \begin{X}
    ENV_END = auto()  # 体 ≡ \end{X}
    OPAQUE = auto()  # 体无自然文本 → 整调用 [[MACRO]]
    TRANSPARENT = auto()  # 体含自然文本 → 参数按位分流（protect_args）
    LITERAL = auto()  # \newif 注册的 \Xtrue/\Xfalse 等


@dataclass(slots=True)
class ArgSpec:
    """xparse 参数签名项（docs/spec/latex-pipeline.md）。"""

    kind: str  # 'm'|'o'|'O'|'s'|'d'|'D'|'r'|'R'|'v'|'e'|'t'|'b'|'n'|'u'|'g'
    delim: str = ""  # d/D/r/R/t 的定界符（'<>'）或 e 的 token 表（'^_'）
    default: str | None = None  # O/D/R 的默认值
    delim_toks: tuple[Tok, ...] = ()  # 'u' 专用：gullet ``Arg.delim`` 原样携带


@dataclass(frozen=True, slots=True)
class ArgspecEntry:
    r"""``data/argspec.json`` 一行：CTAN 宏/环境的包归属 + xparse 签名 + 参数角色。

    ``arg_roles`` 与 ``signature`` token 位序对齐：``text``/``opt-text``
    可译、``key``/``verbatim``/``skip`` 保护。``policy`` 兜底行为：
    ``chunk-arg | transparent | key | verbatim | protect | boundary |
    literal``（env 侧 ``body_role``: ``text | verbatim | math |
    protect``）。``guessed`` = 签名是族规则推断（source 含
    ``guessed-signature``），命中可审计回滚。``also_in`` = 跨包
    重名登记（同名亦由这些包提供）。
    """

    name: str
    package: str
    signature: str = ""
    arg_roles: tuple[str, ...] = ()
    policy: str = "protect"
    body_role: str = ""
    guessed: bool = False
    also_in: frozenset[str] = frozenset()


@dataclass(slots=True)
class ScanWarning:
    """可观测性（泄漏类 bug 的第一手线索）。"""

    kind: str  # unclosed_env|unpaired_dollar|stray_end|debt_repair|def_parse_fail|
    #   letters_cut|expansion_overflow|if_unterminated|missing_input|
    #   gen_overflow|ph_collision|env_mismatch|argspec_shadowed|expand_tail_dropped|
    #   keyarg_unbound
    pos: int
    detail: str


@dataclass(slots=True)
class ScanResult:
    """扫描产物。"""

    protected_tex: str
    chunks: list[Chunk]
    ph_map: dict[str, str]  # "[[TYPE_n]]" → 原文段（可内嵌占位符）
    macros: ScopeMacroTable  # scope 链单一表示
    pieces: list[Piece] = field(default_factory=list)
    inputs: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[ScanWarning] = field(default_factory=list)
    # 叙事序虚拟文本（segmenter 版恒 == 单文件入参；多文件 = flatten 同构）。
    # pieces/chunk.span 的坐标系。
    vtex: str = ""
    # 源文自带 ``[[X_n]]`` 形字面集（签发避让的另一半）：字面原样过 pieces
    # 进 protected_tex——validate_result 据此豁免 dangling_ph/chunk_ref
    # 误报（S2：只活在 ScanState 时消费方区分不了保留字面与真悬空）。
    ph_reserved: set[str] = field(default_factory=set)


@dataclass(slots=True)
class ScanState:
    r"""一切可变状态的共享容器（spawn 只共享这一个引用，W7 扶正）。

    ``pkgs`` 由 v2 segmenter 写（``\usepackage``/``\RequirePackage``/
    ``\documentclass`` 已加载包名）——**无消费方**：argspec 查表不
    按包门控（``tables.argspec_lookup*`` 的 ``_pkgs`` 是死参），字段
    按观测仪表刻意保留（包名集可审计/调试），非门控输入。
    """

    issuer: PlaceholderIssuer
    ph_map: dict[str, str]
    chunks: list[Chunk]
    macros: ScopeMacroTable
    inputs: list[tuple[int, str]]
    warnings: list[ScanWarning]
    ph_reserved: set[str] = field(
        default_factory=set
    )  # 源文自带 [[X_n]] 形字面 → 签发避让
    pkgs: set[str] = field(default_factory=set)
    #: preamble 前置发射白名单（{"abstract","title","author"} 子集）——
    #: ``\begin{document}`` 前命中的项照常 emit chunk，未登记项维持
    #: preamble 整段盖过（缺省空集 = 历史行为）。
    front_matter: frozenset[str] = frozenset()


# ---------------------------------------------------------------- 扫描层共享常量
# env 可选参版式判定的查表数据——纯常量本就归数据层（曾挂 tables.py，
# ``env_opt_is_format`` 函数内延迟 import 兜 model↔tables 环；常量上移
# 后 model 对 tables 零引用，环消失而非被按调用点压住）。tables.py
# 同名再出口保旧调用面。

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

OPT_FMT_CHARS = frozenset("=*\\#|!~,()<>:;")  # 版式参特征（kv/装饰/分组）
OPT_POS_LETTERS = frozenset("htbpHTBPclrmb")  # 浮动位 htbp + 列型 lcrmpb


def env_opt_is_format(env: str, content: str) -> bool:
    r"""``\begin{env}[opt]`` 的 ``[opt]``：版式参（吃掉）还是标题正文（放行）。

    scanner-audit F6：docs/spec/latex-pipeline.md 原规格无条件吞 ``[opt]`` → theorem/
    lemma/proof 类环境标题永不进 chunk（corpus 命中 8.3%，召回缺口）。
    判定（corpus 实测分布校准）：

    - 列表容器 env（itemize/enumerate 等）的 opt 恒为版式
      （``[noitemsep]``/``[label=…]``）——无条件吃；
    - 其余看内容：空 / 数字开头 / 纯位置字母 / 含 ``=*\#|!~,()<>:;``
      → 版式；否则当正文放行（回落主流进 chunk，标题恢复可译）。
    """
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
