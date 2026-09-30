r"""``latex.segmenter._common.rec`` — 记录型与 env/vtex helper（``_common`` god-file 机械拆分叶）。

``_Vtex`` 叙事序虚拟文本 + ``_RunItem``/``_EnvDeadTok``/``_ArgTok`` run/
墓标/参数记录型 + env 族三件（``_env_ph_type``/``_env_mand_count``/
``_scan_envtag``）+ ``_verb_delim_tok``/``_doc_begin_of`` 散件。
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

from texlate.latex.model import ArgSpec, PhType, Span
from texlate.latex.tables import (
    ENV_MANDATORY_ARG,
    MATH_ENVS,
    PROTECTED_ENVS,
    VERBATIM_ENVS,
)
from texlate.textutil import BEGIN_DOC_RX, DOCCLASS_RX, mask_tex

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.latex.gullet import EnvDef
    from texlate.latex.model import ArgspecEntry
    from texlate.latex.mouth import Tok


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
