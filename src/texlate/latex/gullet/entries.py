r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：表项类型 + scope 宏表。"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
from typing import (
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from texlate.latex.mouth import (
        Tok,
    )

# ------------------------------------------------------------------ 表项类型


@dataclass(slots=True)
class Arg:
    """参数槽（``MacroDef.spec`` 项；调用点读取顺序即列表序，§4.1/§8.4）。"""

    kind: str  # 'm'|'o'|'star'|'delim'|'until_group'|'literal_match'
    delim: list[Tok] = field(default_factory=list)  # delim/literal_match 目标序列
    default: list[Tok] | None = None  # 'o' 缺省值 token
    open: str = "["  # 'o' 自定界 opener（xparse d<>/g 用）
    close: str = "]"
    char: str = "*"  # 'star' 期待字符
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
    body_role: str = ""  # "": 散文体 | "math"（before 尾开数学推断）


Entry = MacroDef | Alias | IfCond | IfSetter


class ArgMismatch(Exception):  # noqa: N818 — 规格 §3.5 定名（非 Error 语义而是控制流信号）
    """调用点参数不匹配（§3.5）：调用方 ``unread(trace)`` 后回吐触发 token。"""


# ------------------------------------------------------------------ 宏表


class ScopeMacroTable:
    r"""命令/环境 scope 链（§8.5）。

    scope 事件由**分段器**驱动回报（本层只提供链与查写），唯二例外是
    ``\begingroup``/``\bgroup``/``\endgroup``/``\egroup``——cs 形原语由
    gullet ``_exec_prim`` 在分派点直接推弹（含 ``gen>0`` 展开产物，
    宏体里的组原语走同一漏斗）：

    - **推**：``lbrace``/``\bgroup``/``\begingroup``/``\begin{env}``/数学开
      （``$``/``$$``/``\(``/``\[``/math-env）——含 ``gen>0`` 的 ``\begin``
      展开产物，宏展开的 ``\begin`` 同样开环境作用域；
    - **弹**：``rbrace``/``\egroup``/``\endgroup``/``\end{env}``/数学闭，
      组内对称推弹即安全；
    - **不产事件**：参数括号——gullet ``_invoke`` 读参消费的分界 token 与
      分段器自身 ``_args`` 消费的 ``{…}``/``[…]`` 都不推弹（TeX 语义同：
      实参组不建作用域）。

    ``\\gdef/\\xdef/\\global`` 写底帧。
    """

    def __init__(self) -> None:
        """底帧 = 全局帧。"""
        self.scopes: list[dict[str, Entry]] = [{}]
        self.env_scopes: list[dict[str, EnvDef]] = [{}]

    def push_scope(self) -> None:
        r"""分段器回报组/环境/数学开（``{``/``\bgroup``/``\begingroup``/``\begin``/``$``族）。"""
        self.scopes.append({})
        self.env_scopes.append({})

    def pop_scope(self) -> None:
        r"""分段器回报组/环境/数学闭（``}``/``\egroup``/``\endgroup``/``\end``/``$``族）；底帧不可弹。"""
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

    def env_sig(self, target: str) -> frozenset:
        r"""Target env 端点宏签名（v1 ``_env_sig`` scope 版）：全链快照。

        ``(name, kind, scope_depth)`` 三元组集——迟到 ``\def`` 登记/改义/
        scope 弹出使墓标事件面失真即作废（分段器 ``_EnvDeadTok.sig`` 键）。
        """
        out = set()
        for depth_i, scope in enumerate(self.scopes):
            for name, entry in scope.items():
                m = self.resolve(entry)
                kind = getattr(m, "kind", "")
                if (
                    kind in ("env_begin", "env_end")
                    and getattr(m, "target_env", "").rstrip("*") == target
                ):
                    out.add((name, kind, depth_i))
        return frozenset(out)
