r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：表项类型 + scope 宏表。"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)
from typing import (
    TYPE_CHECKING,
)

from texlate.latex.model import (
    ArgSpec,
    MacroKind,
)
from texlate.latex.mouth import (
    CatTable,
    Mouth,
    Tok,
)

if TYPE_CHECKING:
    from texlate.latex.macro_table import (
        MacroTable as _FlatMacroTable,
    )

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


def _spec_to_args(spec: list[ArgSpec]) -> list[Arg]:
    """``ArgSpec``（v1 字节层签名）→ ``Arg``（gullet 读参槽）映射。

    ``t`` 试字符归 ``star``（缺席不算失配——literal_match 会 raise）；
    ``d``/``D`` 即定界可选 → ``o`` 带自定界括号；``r``/``R`` 定界强制
    → ``delim``（闭符单 token）；``v``/``b`` 无对位 → ``m`` 近似。
    """
    out: list[Arg] = []
    for s in spec:
        k = s.kind
        if k == "m" or k in ("v", "b"):
            out.append(Arg("m"))
        elif k in ("o", "O"):
            d = (
                [Tok("other", ch, (-1, -1, -1)) for ch in s.default]
                if s.default is not None
                else None
            )
            out.append(Arg("o", default=d))
        elif k == "s":
            out.append(Arg("star"))
        elif k == "t":
            out.append(Arg("star", char=s.delim[0] if s.delim else "*"))
        elif k in ("d", "D"):
            out.append(
                Arg(
                    "o",
                    open=s.delim[0] if s.delim else "[",
                    close=s.delim[-1] if s.delim else "]",
                )
            )
        elif k in ("r", "R"):
            out.append(
                Arg(
                    "delim",
                    delim=[Tok("other", s.delim[-1], (-1, -1, -1))]
                    if s.delim
                    else [Tok("rbrace", "}", (-1, -1, -1))],
                )
            )
        elif k == "e":
            out.append(
                Arg(
                    "e",
                    delim=[Tok("other", ch, (-1, -1, -1)) for ch in s.delim],
                )
            )
    return out


def export_flat_macros(flat: _FlatMacroTable) -> ScopeMacroTable:
    r"""v1 平表 ``macro_table.MacroTable`` → scope 链表（``ScanResult.macros`` 单型收敛）。

    ``MacroEntry`` → ``MacroDef``：OPAQUE→``opaque``、TRANSPARENT→
    ``transparent_inline``（体含文本不展开、调用点保护分流——与 gullet
    pass-through 语义同）、ENV_BEGIN/ENV_END→同名端点、LITERAL→
    ``IfSetter``（``\\Xtrue``/``\\Xfalse`` 旗标语义）。body 经 ``Mouth``
    重词法成 token 列（file_id=-1 虚源——导出表只供查询面，body 不再
    上流连）。``envs`` 同理进 ``env_scopes`` 底帧。
    """
    out = ScopeMacroTable()
    for name, e in flat.cmds.items():
        if e.kind is MacroKind.LITERAL:
            # \Xtrue/\Xfalse：注册即 IfSetter（v2 \newif 同态）
            if name.endswith("false"):
                out.set(name, IfSetter(name[:-5], value=False), scope="global")
            else:
                out.set(name, IfSetter(name[:-4], value=True), scope="global")
            continue
        kind = {
            MacroKind.OPAQUE: "opaque",
            MacroKind.TRANSPARENT: "transparent_inline",
            MacroKind.ENV_BEGIN: "env_begin",
            MacroKind.ENV_END: "env_end",
        }[e.kind]
        body = list(Mouth(e.body, -1, CatTable())) if e.body else []
        out.set(
            name,
            MacroDef(
                name=name,
                spec=_spec_to_args(e.spec),
                body=body,
                kind=kind,
                target_env=e.target_env,
                protect_args=e.protect_args,
                scope="global",
                src=(-1, e.def_site, e.def_site),
            ),
            scope="global",
        )
    for name, e in flat.envs.items():
        out.set_env(
            EnvDef(
                name=name,
                spec=[Arg("m")] * e.nargs,
                kind="protected" if e.kind == "protected" else "transparent",
                body_role=e.body_role,
            ),
            scope="global",
        )
    return out
