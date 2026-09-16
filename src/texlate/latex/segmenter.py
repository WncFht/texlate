r"""Segmenter——``next_expanded()`` token 流的消费者（M1 接线，S1 骨架）。

契约见 ``docs/research/latex/segmenter-integration.md``。要点：

- **vtex**：叙事序虚拟文本。一切 piece/chunk/span 用 vtex 坐标；
  ``file_texts[fid][a:b]`` 经 :meth:`Segmenter._cover_to` 追加映射，
  间隙字节（注释/折叠空白）随覆盖自动进 vtex——Mouth 吞注释后
  identity 不破的机制。
- **run 双轨**：``_run`` 项 = ``(surface, ident, vspan)``——surface 进
  chunk.content/译文面；ident 进 identity 面（gen=0 项 = vtex 切片、
  ph 项 = token 自身、展开组 = ``[[EXPAND_n]]``）。
- **chunk identity**：run 含展开组时 ``ph_map["[[CHUNK_k]]"]`` 登记为
  identity 串——``expand()`` 的 ``trans → ph_map → content`` 优先级
  自动回原文（docs/07 §9 伪码同序），零 schema 变更。
- **展开组**：``gen>0`` 连续同 ``origin`` token 为一组；组内 gen=0
  arg token（pos 落调用区间内）同属。surface 正常流过分段，identity
  收拢为一个 ``[[EXPAND_n]]``。

S1 骨架：主循环 + 覆盖账本 + run 双轨 + math/env/verbatim/verb/cite-ref
保护子集 + scope/math_depth 回报。
S2 分派移植：v1 ``_dispatch_cmd`` 19 行逐行 token 化——``_args_tok``
（argspec s/o/d/m/e 全字母 + 单 token/零宽缺省）、chunk-arg 子扫、
``\\href`` 拆分、PROTECT_BLOCK/``\\item``/BOUNDARY_TAIL/未知命令保护、
``\\[``/``\\(`` 定界数学、``\\end{document}`` 截停、in_arg 环境路径、
env_begin/end 宏端点配对。``\\if`` 界标档回放、F12 墓标在 S4。
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple, Protocol

from texlate.latex.gullet import ArgMismatch, Gullet, IfSetter, MacroDef
from texlate.latex.macro_table import parse_argspec
from texlate.latex.model import (
    ArgSpec,
    Chunk,
    PhType,
    Piece,
    PieceKind,
    ScanResult,
    ScanState,
    ScanWarning,
    Span,
    env_opt_is_format,
    match_brace,
    unescaped_dollar_odd,
)
from texlate.latex.placeholder import PH_RX, PlaceholderIssuer
from texlate.latex.tables import (
    ACCENT_CHARS,
    ARG_TRANSPARENT_ENVS,
    BOUNDARY_NAMES,
    BOUNDARY_TAIL,
    CHUNK_ARG_NAMES,
    CHUNK_ARG_SPEC,
    CHUNK_MAX,
    CHUNK_MIN,
    CITE_NAMES,
    COND_RX,
    ENV_MANDATORY_ARG,
    FILENAME_CHARS,
    FONT_SWITCHES,
    INLINE_LITERAL_CMDS,
    INPUT_CMDS,
    INPUT_SCAN_CMDS,
    MATH_ENVS,
    MAX_GEN,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    PROTECTED_ENVS,
    REF_NAMES,
    TRANSPARENT_NAMES,
    VERBATIM_ENVS,
    argspec_lookup,
    argspec_lookup_env,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.latex.model import ArgspecEntry
    from texlate.latex.mouth import Tok

# 与 scanner.py 同源逐字：可译性口径随 v1（``+`` 折叠会把临界 run 压过
# CHUNK_MIN 阈值 → chunk 召回降，验收门不许）
_CLEAN_CMD_RX = re.compile(r"\\[a-zA-Z@]+\*?|\\[^a-zA-Z]")
_CLEAN_NONALPHA_RX = re.compile(r"[^a-zA-Z]")
_LEAD_WS_RX = re.compile(r"\s*")
_TRAIL_WS_RX = re.compile(r"\s*$")
_COMMENT_GAP_RX = re.compile(r"%[^\n]*")
# 参数体内裸 ``%`` 注释（``\%`` 转义由 ``\\.`` 分支先吃掉）——in_arg 渲染串
# 的 ``%`` 必为真注释（token 层已证非 \verb/url 体内）
_ARG_COMMENT_RX = re.compile(r"\\.|%[^\n]*")
# —— 与 scanner.py 同源的保护/豁免表（S2 scanner 退役时合入 tables.py）
_LETTER_TAIL_RX = re.compile(r"\\[a-zA-Z@]+\Z")
# math-debt 豁免：verbatim/url/href 体内的 ``$`` 是死字符非 mathshift。
_DEBT_EXEMPT = frozenset({PhType.VERB, PhType.COMMENT, PhType.URL, PhType.HREF})
_PROTECT_TYP = {
    "includegraphics": PhType.GRAPHICS,
    "url": PhType.URL,
    "path": PhType.URL,
    "label": PhType.LABEL,
    "bibliography": PhType.BIB,
    "bibliographystyle": PhType.BIB,
    "bibitem": PhType.BIB,
}
# 组内再生保护段的配对前瞻上限（env/math/delim 扫描步数）
_GRP_SCAN_CAP = 4000

# 包加载命令：已加载包名集入 ``ScanState.pkgs`` → argspec 门控输入。
# 全部已在 BOUNDARY_NAMES（非 preamble 文档走 row 14 字面档时同步登记）。
_PKG_CMDS = frozenset(
    {"usepackage", "RequirePackage", "documentclass", "documentstyle"}
)
_PKG_ARG_SPEC = [ArgSpec("o"), ArgSpec("m")]


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


# ------------------------------------------------------------------ token 源


class TokenSource(Protocol):
    """分段器输入抽象——gullet（顶层）或 token 列表（in_arg 子扫）。"""

    def next_expanded(self) -> Tok | None:
        """拉下一枚展开后 token；耗尽 ``None``。"""
        ...

    def read(self) -> Tok | None:
        """原始（不展开）拉取——前瞻/收集用。"""
        ...

    def unread(self, toks: list[Tok]) -> None:
        """回吐前端。"""
        ...

    def skip_past(self, fid: int, end: int) -> None:
        """``fid`` 源对齐到 ``end``——raw 消费段内 token 残骸剔除。"""
        ...


class _ListSource:
    """in_arg 子扫的 token 列表源（token 已展开，read==next_expanded）。

    ``deque`` 而非 list：大体 env/arg 子扫下 ``pop(0)`` 是 O(n)
    memmove——2410.17998 实测 2.4M 次出队吃掉 22s。
    """

    def __init__(self, toks: list[Tok]) -> None:
        """持有待发 token 队列。"""
        self._q = deque(toks)
        # ``_collect_group`` 扫到队尾未配对的 open 位 (pos, gen)：token 列
        # 构造即定（unread 只回放已见 token、skip_past 只删），「无配对」
        # 判终身成立——同 open 的后续探针 O(1) fast-fail，不再 O(尾长) 重扫
        # （2410.17998 实测 145 次失败重扫 = 18.6M/19M token 拉取）。
        self._unmatched_open: set[tuple[tuple[int, int, int], int]] = set()

    def next_expanded(self) -> Tok | None:
        """队首出队。"""
        return self._q.popleft() if self._q else None

    def read(self) -> Tok | None:
        """同 next_expanded（子扫内不再有展开副作用）。"""
        return self.next_expanded()

    def unread(self, toks: list[Tok]) -> None:
        """回插队首（保序）。"""
        self._q.extendleft(reversed(toks))

    def skip_past(self, fid: int, end: int) -> None:
        r"""丢弃 ``pos`` 完全落在 ``end`` 前的队首 token（raw 消费对齐）。

        ``\verb`` 定界体/verbatim env 体在文件字节上找闭合，其间的
        token 早已展开入队——不剔除会被二次分派（体内 ``\end`` 假命中）。
        """
        while self._q and self._q[0].pos[0] == fid and self._q[0].pos[2] <= end:
            self._q.popleft()


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
    """token 版 ``ArgSpan``：content/full 的文件区间 + 去括号内容 token。

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


class Segmenter:
    r"""token 流 → pieces/chunks。单遍正向、绝不抛异常（铁律 1）。"""

    def __init__(
        self,
        state: ScanState,
        *,
        in_arg: bool = False,
        mined: bool = False,
        gen: int = 0,
    ) -> None:
        r"""共享 ``state``；``in_arg`` 子扫 = run 全 literal + 嵌套内联。

        ``mined`` = 保护环境体挖掘扫（v1 ``MINED_ONLY``）：run 全 literal
        但分派照常——``\\caption`` 照产 chunk（``in_arg`` 则内联不产）。
        """
        self.state = state
        self.in_arg = in_arg
        self.mined = mined
        self.gen = gen  # 子扫代数（MAX_GEN 回压，v1 同值语义）
        self.vt = _Vtex()
        self.cons: dict[int, int] = {}  # fid → 文件内已消费位
        self.file_texts: list[str] = []  # fid → 源文本（gullet.file_texts 对齐）
        self.pieces: list[Piece] = []
        self.env_stack: list[str] = []
        self.math_debt: list[int] = []
        self.force_chunk = False
        self._run: list[_RunItem] = []
        self._run_start: int | None = None  # run 首个覆盖的 vtex 位
        self._run_has_expand = False
        self._open_origin: tuple[int, int, int] | None = None  # 展开组调用区间
        self._open_vspan: Span | None = None  # 该组在 vtex 的落位
        self._open_toks: list[Tok] = []  # 组成员 token（surface 收组时产）
        self._open_pfx = ""  # 展开组调用点前的间隙 surface 前缀
        self._run_pending: dict[str, str] = {}  # 组内 surface ph（chunk 化才入 ph_map）
        self._cov_origin: dict[int, int] = {}  # fid → 上次 _cover_to 的 pre-cons
        self._stop = False  # \end{document}/\endinput 顶层截停
        self._env_dead: dict[str, _EnvDeadTok] = {}  # F12 未闭合 env 墓标
        self._doc_begin = -1  # fid-0 上 \begin{document} 的 \begin 起点（-1=无）
        self._preamble = False  # preamble 档：token 照过 gullet、分段全 literal

    def spawn(
        self, *, in_arg: bool | None = None, mined: bool | None = None
    ) -> Segmenter:
        """子分段器：共享 state/vt/cons/file_texts，env_stack 拷贝，gen+1。

        覆盖账本共享 = 子扫覆盖直落父 vtex 区间（连续无断）；``pieces``
        独立——子产出经 ``join(p.text)`` 渲染串回父层消费，不与父
        pieces 平铺（v1 ``spawn`` 同构，契约 §6 in_arg 子扫）。
        """
        sub = Segmenter(
            self.state,
            in_arg=self.in_arg if in_arg is None else in_arg,
            mined=self.mined if mined is None else mined,
            gen=self.gen + 1,
        )
        sub.vt = self.vt
        sub.cons = self.cons
        sub.file_texts = self.file_texts
        sub.env_stack = list(self.env_stack)
        return sub

    # ------------------------------------------------------------ 覆盖账本

    def _cons(self, fid: int) -> int:
        """文件 fid 的消费前沿。"""
        return self.cons.get(fid, 0)

    def _cover_to(self, fid: int, end: int) -> Span:
        """``file_texts[fid][cons:end]`` 记入 vtex，返回其 vtex 区间。"""
        sp, _text = self._cover_text(fid, end)
        return sp

    def _cover_text(self, fid: int, end: int) -> tuple[Span, str]:
        """``_cover_to`` + 返回所盖文本。

        省掉刚盖段的 ``vt.slice`` 反查（bisect+join 逐 token 开销，
        pdotaph2 815K 次）。
        """
        a = self._cons(fid)
        if end <= a:
            # 已覆盖（回放/乱序）——零宽，锚在当前 vtex 末（不是文件位 a！）
            return Span(len(self.vt), len(self.vt)), ""
        self._cov_origin[fid] = a  # 间隙 surface 前缀判定的锚（_gap_surface）
        text = self.file_texts[fid][a:end]
        sp = self.vt.cover(text)
        self.cons[fid] = end
        return sp, text

    def _gap_surface(self, fid: int, cons0: int, tok_start: int) -> str:
        r"""Token 前间隙字节的 surface 前缀（``" "`` 或 ``""``）。

        Mouth 三类字节不成 token：``\cs`` 后空格（控制词吞空格规则）、
        折叠连续空白、``%`` 注释。它们随覆盖进 vtex/ident 但 surface
        永不可见——v1 字节扫会把其中空白扫进 run（``\ie x`` →
        ``\ie x`` 而非 ``\iex``）。规则：去注释后纯空白且非空 → ``" "``。
        ``cons0`` = 覆盖前锚：post-cover 路径用 ``_cov_origin[fid]``，
        pre-cover 路径先取 ``self._cons(fid)`` 再 ``_cover_to``。
        """
        if cons0 < 0 or tok_start <= cons0:
            return ""
        gap = _COMMENT_GAP_RX.sub("", self.file_texts[fid][cons0:tok_start])
        return " " if gap and not gap.strip() else ""

    # ------------------------------------------------------------ run 双轨

    def _ph(self, typ: PhType, body: str, cut: tuple[int, int] | None = None) -> str:
        r"""签发占位符（body → ph_map，避开 ``ph_reserved`` 碰撞）。

        ``cut`` = 体尾源位 ``(fid, pos)``：体以 ``\\letters`` 收尾且源串
        后继仍是字母 → ``letters_cut`` 信号（§11 断言的 token 版）。
        """
        if body == "":
            # 零宽 _cover_to（回放/乱序 token 的字节早已覆盖）——无字节可保护，
            # 直登记必成 dead_ph；调用方见 "" 应跳过挂项
            return ""
        if (
            cut is not None
            and cut[1] < len(self.file_texts[cut[0]])
            and self.file_texts[cut[0]][cut[1]].isalpha()
            and _LETTER_TAIL_RX.search(body)
        ):
            self.state.warnings.append(
                ScanWarning("letters_cut", len(self.vt), body[-40:])
            )
        return self.state.issuer.new(
            typ, body, self.state.ph_map, self.state.ph_reserved
        )

    def _rappend_ph(
        self, typ: PhType, ph: str, vspan: Span, tok: Tok | None = None
    ) -> None:
        r"""Ph 项进 run（math-debt 记账：体含奇数 ``$`` 压栈）。

        ``tok`` = 触发的 cs/mathshift token——给 surface 补间隙前缀
        （``\ie \cite{a}`` 的被吞空格，见 ``_gap_surface``）。
        """
        if not ph:
            return  # 空 body（零宽回放）——无项可挂
        pfx = (
            self._gap_surface(
                tok.pos[0], self._cov_origin.get(tok.pos[0], -1), tok.pos[1]
            )
            if tok is not None
            else ""
        )
        self._rappend(pfx + ph, ph, vspan)
        if typ not in _DEBT_EXEMPT and unescaped_dollar_odd(self.state.ph_map[ph]):
            self.math_debt.append(len(self._run) - 1)

    def _rappend(self, surface: str, ident: str, vspan: Span) -> None:
        """追加 run 项（surface/ident 双轨 + 覆盖位）。"""
        if self._run_start is None:
            self._run_start = vspan.start
        self._run.append(_RunItem(surface, ident, vspan.start, vspan.end))

    def _rappend_tok(self, t: Tok) -> None:
        """gen=0 文本 token：覆盖 gap+本体；surface=渲染形，ident=vtex 切片。"""
        fid, _a, b = t.pos
        cons0 = self._cons(fid)
        vspan, ident = self._cover_text(fid, b)
        self._rappend(
            self._gap_surface(fid, cons0, t.pos[1]) + self._tok_surface(t),
            ident,
            vspan,
        )

    # ------------------------------------------------------------ piece 发射

    def _emit(self, vstart: int, vend: int) -> None:
        """LITERAL piece 覆盖 vtex 区间。"""
        if vend > vstart:
            self.pieces.append(
                Piece(
                    PieceKind.LITERAL,
                    Span(vstart, vend),
                    self.vt.slice(vstart, vend),
                    self.env_stack[-1] if self.env_stack else None,
                )
            )

    def _emit_text(self, vstart: int, vend: int, text: str) -> None:
        """LITERAL piece（显式文本——含 ``[[X_n]]`` 的 ident 渲染）。"""
        if vend > vstart:
            self.pieces.append(
                Piece(
                    PieceKind.LITERAL,
                    Span(vstart, vend),
                    text,
                    self.env_stack[-1] if self.env_stack else None,
                )
            )

    def _emit_ph(self, typ: PhType, vstart: int, vend: int, body: str) -> None:
        """独立 PROTECTED piece。"""
        ph = self._ph(typ, body)
        if not ph:
            return  # 零宽覆盖（回放）——piece 无文本可载
        self.pieces.append(
            Piece(
                PieceKind.PROTECTED,
                Span(vstart, vend),
                ph,
                self.env_stack[-1] if self.env_stack else None,
            )
        )

    def _new_chunk(self, content: str, context: str, gspan: Span, ident: str) -> str:
        """登记 chunk 返回 ``[[CHUNK_id]]``；``ident≠content`` 时入 ph_map。"""
        cid = len(self.state.chunks)
        self.state.chunks.append(
            Chunk(
                id=cid,
                content=content,
                context=context,
                span=gspan,
                env=self.env_stack[-1] if self.env_stack else None,
                placeholders=PH_RX.findall(content),
            )
        )
        token = f"[[CHUNK_{cid}]]"
        if ident != content:
            # 展开组在 content 物化了非原文字节——identity 经 ph_map
            # 优先级回 ident 串（§9 expand: trans→ph_map→content）
            self.state.ph_map[token] = ident
        return token

    # ------------------------------------------------------------ flush

    def _flush_run(self, end_pos: int) -> None:
        """Run → chunk piece / literal piece（§3.8 + 双轨 identity）。"""
        items = self._run
        self._run = []
        rs = self._run_start
        self._run_start = None
        self.math_debt.clear()
        has_expand = self._run_has_expand
        self._run_has_expand = False
        pending = self._run_pending
        self._run_pending = {}
        if rs is None or not items:
            self._run_pending.update(pending)  # 未消费归还（防御）
            return
        s = "".join(it.surface for it in items)
        ident = "".join(it.ident for it in items)
        re_ = end_pos
        if not s.strip() or self.in_arg or self.mined:
            self._emit_text(rs, re_, self._lit_text(items, ident, re_))
            self._pending_settle(pending, s, register=False)
            return
        lead = len(_LEAD_WS_RX.match(s).group(0))
        trail_m = _TRAIL_WS_RX.search(s)
        trail = len(trail_m.group(0)) if trail_m else 0
        hi = len(s) - trail
        clean = PH_RX.sub(" ", s[lead:hi])
        clean = _CLEAN_CMD_RX.sub(" ", clean)
        clean = _CLEAN_NONALPHA_RX.sub(" ", clean).strip()
        force = self.force_chunk
        self.force_chunk = False
        if len(clean) < CHUNK_MIN and not (force and clean):
            self._emit_text(rs, re_, self._lit_text(items, ident, re_))
            self._pending_settle(pending, s, register=False)
            return
        if has_expand:
            # 含展开组的 run 跳过 lead/trail 剥离——整 run 进 content（§2）
            lead, hi = 0, len(s)
        bounds = [0]
        for it in items:
            bounds.append(bounds[-1] + len(it.surface))
        parts = self._split_bounds(s, bounds, lead, hi)
        slices = [self._slice_items(items, bounds, p0, p1, hi) for p0, p1 in parts]
        # gspan = 分段项界并集——零宽项（surface==""，归段规则见 _slice_items）
        # 的 callsite 字节随段折入，否则尾部 _emit 把同段字节 raw 再发一遍
        core_vs, core_ve = slices[0][2], slices[-1][3]
        if core_vs < 0 or core_ve < 0:
            self._emit_text(rs, re_, self._lit_text(items, ident, re_))
            self._pending_settle(pending, s, register=False)
            return
        if core_vs > rs:
            self._emit(rs, core_vs)
        gspan = Span(core_vs, core_ve)
        context = "item" if force else "para"
        self._pending_settle(pending, s, register=True)
        refs = [
            self._new_chunk(part_s, context, Span(pvs, pve), part_i)
            for part_s, part_i, pvs, pve in slices
        ]
        self.pieces.append(
            Piece(
                PieceKind.CHUNK_REF,
                gspan,
                "".join(refs),
                self.env_stack[-1] if self.env_stack else None,
            )
        )
        if core_ve < re_:
            self._emit(core_ve, re_)

    def _pending_settle(
        self, pending: dict[str, str], s: str, *, register: bool
    ) -> None:
        """组内 surface ph 清算。

        本 run ``s`` 引用者登记（chunk）或丢弃（literal——surface 不可见）；
        未引用者（eol_par 后段未挂项）归还 ``_run_pending`` 待下一 flush。
        """
        for tok, body in pending.items():
            if tok in s:
                if register:
                    self.state.ph_map[tok] = body
            else:
                self._run_pending[tok] = body

    def _lit_text(self, items: list[_RunItem], ident: str, re_: int) -> str:
        """LITERAL piece 文本 = ``ident`` + 项覆盖界外的尾随 vtex 切片。

        ``re_``（冲刷边界）可越过末项 vend——其间是已盖未挂项的 gap
        字节（尾随注释/EOF 空白），须并进 piece 文本否则平铺虽在、字节丢。
        """
        extent = max(it.vend for it in items)
        if re_ > extent:
            return ident + self.vt.slice(extent, re_)
        return ident

    @staticmethod
    def _slice_items(
        items: list[_RunItem], bounds: list[int], lo: int, hi: int, end: int
    ) -> tuple[str, str, int, int]:
        """Surface ``[lo,hi)``（项界对齐）→ ``(surface, ident, vstart, vend)``。

        零宽项（``surface==""``——eol_par 首段可为空）按 ``lo<=acc<hi`` 归段，
        恰在 ``end`` 的归末段；否则其 ident 双侧段都不收 → dead_ph。
        ``bounds`` = surface 前缀和（``bounds[i]`` = 项 i 的 acc）。命中项充要
        ``bounds[i+1]>lo``（或零宽 ``bounds[i]>=lo``）且 ``bounds[i]<hi``
        （末段放 ``bounds[i]==hi==end``）——bisect 窄化扫描窗，去掉每段对
        全列的 O(n) 重扫（zwanenburg：281 段 × 全列 → 8.9M 项访）。
        """
        i_lo = min(bisect_right(bounds, lo) - 1, bisect_left(bounds, lo))
        i_hi = bisect_right(bounds, hi) if hi == end else bisect_left(bounds, hi)
        i_hi = min(i_hi, len(items))
        acc = bounds[i_lo]
        out_s: list[str] = []
        out_i: list[str] = []
        vs = ve = -1
        for it in items[i_lo:i_hi]:
            nxt = acc + len(it.surface)
            keep = nxt > lo and acc < hi
            if not it.surface and acc >= lo and (acc < hi or acc == hi == end):
                keep = True
            if keep:
                out_s.append(it.surface)
                out_i.append(it.ident)
                if vs < 0:
                    vs = it.vstart
                ve = it.vend
            acc = nxt
        return "".join(out_s), "".join(out_i), vs, ve

    @staticmethod
    def _split_bounds(  # noqa: C901, PLR0912 — 切点优先级链，平铺即 §3.8 规则序
        s: str, bounds: list[int], lo: int, hi: int
    ) -> list[tuple[int, int]]:
        """``s[lo:hi]`` 超大二次切分——返回 surface 区间列，切点 snap 项界。

        切点落在项 ``k`` 内部时该项整体归前段（取 vend=bounds[k+1]）——
        展开组/ph token 永不腰斩（契约 §2）。``bounds`` = surface 前缀和。
        """
        if hi - lo <= CHUNK_MAX:
            return [(lo, hi)]
        parts: list[tuple[int, int]] = []
        i = lo
        while i < hi:
            hard = min(i + CHUNK_MAX, hi)
            if hard >= hi:
                parts.append((i, hi))
                break
            window = s[i:hard]
            cut = -1
            for m in PH_RX.finditer(window):
                cut = m.end()
            if cut <= 0:
                ws = window.rfind("\n\n")
                if ws > 0:
                    cut = ws + 2
            if cut <= 0:
                for ch in (". ", "} ", " "):
                    ws = window.rfind(ch)
                    if ws > CHUNK_MAX // 2:
                        cut = ws + len(ch)
                        break
            if cut <= 0:
                cut = hard - i
                for m in PH_RX.finditer(s, i):
                    if m.start() >= hard:
                        break
                    if m.end() > hard:
                        cut = m.end() - i
                        break
            g = i + cut
            k = bisect_left(bounds, g)
            # 恰落项界不切；项内则归前段（含切点项的 vend）
            snap = g if bounds[k] == g else min(bounds[k], hi)
            parts.append((i, snap))
            i = snap
        return [p for p in parts if p[1] > p[0]]

    # ------------------------------------------------------------ 展开组

    def _open_group(self, t: Tok) -> None:
        """开展开组：覆盖调用区间 → vtex；组内 token 收 surface。"""
        fid, a, b = t.src
        pfx = self._gap_surface(fid, self._cons(fid), a)  # 调用点前间隙
        vspan = self._cover_to(fid, b)
        self._open_origin = (fid, a, b)
        self._open_vspan = vspan
        self._open_toks = []
        self._open_pfx = pfx

    def _close_group(self) -> None:
        """收组：surface 进 run 一项，ident = ``[[EXPAND_n]]``（体=调用切片）。

        注意 ``Span.__len__`` = 区间长——零宽 span 为 falsy，判空必须用
        ``is None``（``or`` 会把 ``Span(x,x)`` 落成 ``Span(0,0)``）。
        """
        if self._open_origin is None or self._open_vspan is None:
            return
        segs = self._group_surface()
        vspan = self._open_vspan
        # 零宽 vspan = callsite 已盖（\end{tabular}→\@checkend 之类内层展开）——
        # 体恒空、identity 无需占位；签发只会零宽 run literal 冲刷时被
        # ``_emit_text`` 连 piece 带 token 丢掉 → dead_ph
        ph = (
            self._ph(PhType.EXPAND, self.vt.slice(vspan.start, vspan.end))
            if vspan.end > vspan.start
            else ""
        )
        self._rappend(self._open_pfx + segs[0], ph, vspan)
        self._run_has_expand = True
        for seg in segs[1:]:
            # eol_par 虚拟分段符：前半（含 EXPAND 项）冲刷，后半挂下一 run
            # （ident 空串——调用点字节已由 EXPAND 项计过，§3）
            self._flush_run(vspan.end)
            if seg:
                self._rappend(seg, "", Span(vspan.end, vspan.end))
                self._run_has_expand = True
        self._open_origin = None
        self._open_vspan = None
        self._open_toks = []
        self._open_pfx = ""

    def _in_group(self, t: Tok) -> bool:
        r"""``t`` 是否属当前展开组（gen>0 同 origin / gen=0 落调用区间内）。

        gen>0 加一条嵌套包含：``origin`` 落在本组调用区间内的展开产物
        （arg token 被 gullet 再展开的 ``\\Nrx`` 族）同属本组——surface
        并入、identity 由本组 ``[[EXPAND]]`` 调用切片兜底；否则内层展开
        会把外层组提前关闭，其后 arg token 裸落顶层 dispatch（已盖字节
        二次分派 → 零宽 ENV + 前缀复制，1803.09012 diverged 根因）。
        """
        o = self._open_origin
        if o is None:
            return False
        if t.gen > 0:
            org = t.origin
            if org is None:
                return False
            return org == o or (org[0] == o[0] and o[1] <= org[1] and org[2] <= o[2])
        fid, a, _b = t.pos
        return fid == o[0] and o[1] <= a < o[2]

    # -------------------------------------------------------- 组内再生保护段

    def _grp_ph(self, typ: PhType, body: str) -> str:
        r"""组内 surface ph：先挂 ``_run_pending``。

        run 转 chunk 才入 ``ph_map``——literal 冲刷只渲染 ident，surface
        ph 若直登记必成 dead_ph。
        """
        return self.state.issuer.new(
            typ, body, self._run_pending, self.state.ph_reserved
        )

    def _grp_surfs(self, toks: list[Tok]) -> str:
        return "".join(self._tok_surface(t) for t in toks)

    def _grp_envtag(self, toks: list[Tok], i: int) -> tuple[str, int] | None:
        r"""``\\begin``/``\\end`` + ws + ``{name}`` → ``(name, j_end)``；失配 None。"""
        n = len(toks)
        j = i + 1
        while j < n and toks[j].kind == "space":
            j += 1
        if j >= n or toks[j].kind != "lbrace":
            return None
        depth = 1
        j += 1
        parts: list[str] = []
        while j < n:
            x = toks[j]
            if x.kind == "eol_par":
                return None
            if x.kind == "lbrace":
                depth += 1
            elif x.kind == "rbrace":
                depth -= 1
                if depth == 0:
                    return "".join(parts), j + 1
            parts.append(self._tok_surface(x))
            j += 1
        return None

    def _grp_env_macro(self, t: Tok) -> tuple[str, str] | None:
        r"""组内 env_begin/env_end 宏端点 → ``(kind, target_env)``；非宏 None。"""
        m = self.state.macros.resolve(self.state.macros.lookup(t.text))
        kind = getattr(m, "kind", "")
        if kind in ("env_begin", "env_end"):
            return kind, getattr(m, "target_env", "")
        return None

    def _grp_find_env_end(self, toks: list[Tok], i: int, env: str) -> int | None:
        r"""``i`` 起找配对 ``\\end{env}``（同名 begin/宏端点计深度）→ j_end。"""
        target = env.rstrip("*")
        depth = 1
        j = i
        while j < len(toks) and j - i < _GRP_SCAN_CAP:
            x = toks[j]
            if x.kind == "cs" and x.text in ("begin", "end"):
                hit = self._grp_envtag(toks, j)
                if hit is not None:
                    n2, e = hit
                    if n2.rstrip("*") == target:
                        depth += 1 if x.text == "begin" else -1
                        if depth == 0:
                            return e
                    j = e
                    continue
            elif x.kind == "cs":
                em = self._grp_env_macro(x)
                if em is not None and em[1].rstrip("*") == target:
                    depth += 1 if em[0] == "env_begin" else -1
                    if depth == 0:
                        return j + 1
            j += 1
        return None

    def _grp_math_end(self, toks: list[Tok], i: int) -> int | None:
        r"""Mathshift 配对（``$$`` 双 token 形）→ 闭界 j（含）；未中 None。"""
        dbl = i + 1 < len(toks) and toks[i + 1].kind == "mathshift"
        j = i + 2 if dbl else i + 1
        n = len(toks)
        while j < n and j - i < _GRP_SCAN_CAP:
            if toks[j].kind == "mathshift":
                if dbl:
                    if j + 1 < n and toks[j + 1].kind == "mathshift":
                        return j + 2
                    j += 1
                    continue
                return j + 1
            j += 1
        return None

    def _grp_delim_end(self, toks: list[Tok], i: int, want: str) -> int | None:
        r"""``\\[``/``\\(`` 配对 ``\\]``/``\\)`` → j_end；未中 None。"""
        j = i + 1
        n = len(toks)
        while j < n and j - i < _GRP_SCAN_CAP:
            x = toks[j]
            if x.kind == "cs" and x.text == want:
                return j + 1
            j += 1
        return None

    @staticmethod
    def _grp_bal(  # noqa: C901 — 两定界族各一段，平铺即规则
        toks: list[Tok], i: int, *, brace: bool
    ) -> int | None:
        """``{…}``/``[…]`` 平衡组 → 闭界 j（含）；``eol_par``/EOF 止 None。"""
        depth = 0
        for j in range(i, len(toks)):
            x = toks[j]
            if x.kind == "eol_par":
                return None
            if brace:
                if x.kind == "lbrace":
                    depth += 1
                elif x.kind == "rbrace":
                    depth -= 1
                    if depth == 0:
                        return j + 1
            elif x.kind == "other":
                if x.text == "[":
                    depth += 1
                elif x.text == "]":
                    depth -= 1
                    if depth == 0:
                        return j + 1
        return None

    def _grp_call_end(self, toks: list[Tok], i: int, mand: int) -> int:
        r"""Cs + ``*``? + ``[opt]``≤3 + ``{arg}``≤mand → j_end（``_protect_cs`` 镜像）。"""
        n = len(toks)
        j = i + 1
        if j < n and toks[j].kind == "other" and toks[j].text == "*":
            j += 1
        for _ in range(3):
            k = j
            while k < n and toks[k].kind == "space":
                k += 1
            if k < n and toks[k].kind == "other" and toks[k].text == "[":
                e = self._grp_bal(toks, k, brace=False)
                if e is None:
                    break
                j = e
                continue
            break
        for _ in range(mand):
            k = j
            while k < n and toks[k].kind == "space":
                k += 1
            if k < n and toks[k].kind == "lbrace":
                e = self._grp_bal(toks, k, brace=True)
                if e is None:
                    break
                j = e
                continue
            break
        return j

    def _group_surface(self) -> list[str]:  # noqa: C901, PLR0912, PLR0915 — 组内保护段分派平铺（§3 再生保护段）
        r"""组成员 token → surface 段：结构命令再生保护段产 ph。

        展开表面里的 ``\\begin/\\end{env}``（math/verb/protected 整段、
        其余 tag）、``$…$``/``\\[…\\]``/``\\(…\\)``、cite/ref/PROTECT 族整
        调用、``\\if`` 族——ph 体 = 展开表面切片（vtex 无对应字节，
        identity 由本组 ``[[EXPAND]]``/``ph_map[CHUNK]`` 兜底）。
        ``eol_par`` = 虚拟分段符：切段边界、自身不产字节（§3）。
        返回 ``list[str]``——段间边界处 ``_close_group`` 做 run 冲刷。
        """
        toks = self._open_toks
        segs: list[str] = []
        out: list[str] = []
        i, n = 0, len(toks)
        while i < n:
            t = toks[i]
            if t.kind == "eol_par":
                segs.append("".join(out))
                out = []
                i += 1
                continue
            if t.kind == "mathshift":
                j = self._grp_math_end(toks, i)
                if j is None:
                    out.append(self._tok_surface(t))
                    i += 1
                    continue
                out.append(self._grp_ph(PhType.MATH, self._grp_surfs(toks[i:j])))
                i = j
                continue
            if t.kind != "cs":
                out.append(self._tok_surface(t))
                i += 1
                continue
            name = t.text
            if name in ("begin", "end"):
                hit = self._grp_envtag(toks, i)
                if hit is None:
                    out.append(self._grp_ph(PhType.ENVTAG, self._tok_surface(t)))
                    i += 1
                    continue
                env, j = hit
                if name == "begin":
                    typ = (
                        PhType.MATH
                        if env in MATH_ENVS
                        else PhType.VERB
                        if env in VERBATIM_ENVS
                        else PhType.ENV
                        if env in PROTECTED_ENVS
                        else None
                    )
                    if typ is not None:
                        e = self._grp_find_env_end(toks, j, env)
                        if e is not None:
                            out.append(self._grp_ph(typ, self._grp_surfs(toks[i:e])))
                            i = e
                            continue
                out.append(self._grp_ph(PhType.ENVTAG, self._grp_surfs(toks[i:j])))
                i = j
                continue
            if name in ("[", "("):
                j = self._grp_delim_end(toks, i, "]" if name == "[" else ")")
                if j is not None:
                    out.append(self._grp_ph(PhType.MATH, self._grp_surfs(toks[i:j])))
                    i = j
                    continue
                out.append(self._tok_surface(t))
                i += 1
                continue
            if name in CITE_NAMES or name.startswith("cite"):
                j = self._grp_call_end(toks, i, 1)
                out.append(self._grp_ph(PhType.CITE, self._grp_surfs(toks[i:j])))
                i = j
                continue
            if name in REF_NAMES or (
                name.endswith("ref")
                and name not in TRANSPARENT_NAMES
                and name != "href"
            ):
                j = self._grp_call_end(toks, i, 1)
                out.append(self._grp_ph(PhType.REF, self._grp_surfs(toks[i:j])))
                i = j
                continue
            if name in PROTECT_NAMES:
                j = self._grp_call_end(toks, i, 2 if name == "inputminted" else 1)
                out.append(
                    self._grp_ph(
                        _PROTECT_TYP.get(name, PhType.CMD),
                        self._grp_surfs(toks[i:j]),
                    )
                )
                i = j
                continue
            if name in ("if", "else", "fi", "or") or (
                name.startswith("if") and name[2:].isalpha()
            ):
                out.append(self._grp_ph(PhType.COND, self._tok_surface(t)))
                i += 1
                continue
            if name in ("input", "include"):
                j = self._grp_call_end(toks, i, 1)
                out.append(self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j])))
                i = j
                continue
            em = self._grp_env_macro(t)
            if em is not None:
                ek, eenv = em
                typ = (
                    (
                        PhType.MATH
                        if eenv in MATH_ENVS
                        else PhType.VERB
                        if eenv in VERBATIM_ENVS
                        else PhType.ENV
                        if eenv in PROTECTED_ENVS
                        else None
                    )
                    if ek == "env_begin"
                    else None
                )
                e = (
                    self._grp_find_env_end(toks, i + 1, eenv)
                    if typ is not None
                    else None
                )
                if e is not None:
                    out.append(self._grp_ph(typ, self._grp_surfs(toks[i:e])))
                    i = e
                    continue
                out.append(self._grp_ph(PhType.ENVTAG, self._tok_surface(t)))
                i += 1
                continue
            out.append(self._tok_surface(t))
            i += 1
        segs.append("".join(out))
        return segs

    # ------------------------------------------------------------ 主循环

    def scan(self, src: TokenSource, files: list[str], doc_begin: int = -1) -> None:  # noqa: C901, PLR0912, PLR0915 — preamble/consumed/组界/dispatch 四态平铺即主循环
        r"""消费 ``src`` 至耗尽。``files`` = fid→源文本表（gullet.file_texts）。

        ``doc_begin`` = fid-0 上 ``\\begin{document}`` 的 ``\\begin`` 起点
        （api mask 视图判定，<0 = 无 preamble）：>0 时进 preamble 档——
        token 照常过 gullet（``\\def`` 登记/``\\if`` 求值/``\\input`` 内联
        全生效），分段侧一律 LITERAL 到该边界（v1 整段 ``_emit`` 对价）。
        """
        self.file_texts = files
        self._doc_begin = doc_begin
        self._preamble = doc_begin >= 0 and not self.in_arg
        v0 = len(self.vt)  # 扫描起点——子扫全命中已盖区时不回补前缀
        gullet_inputs = getattr(src, "inputs", None)
        live_srcs = (
            {id(m): m.file_id for m in gullet_inputs}
            if gullet_inputs is not None
            else None
        )
        # 栈成员变更事件门：``_pop_seq``/``_push_seq`` 不变即 live 快照不失真
        # （fid 进出栈唯一通道是 read() 弹栈 / push_source / unread 合成源，
        # 均计数）——免每 token 重建 dict diff（pdotaph2 986K 次重建省掉）。
        stack_ck = (
            (src._pop_seq, src._push_seq)  # noqa: SLF001 — §4 契约面：同模块事件钟
            if live_srcs is not None
            else (0, 0)
        )
        while not self._stop:
            t = src.next_expanded()
            if (
                live_srcs is not None
                and (
                    src._pop_seq,  # noqa: SLF001
                    src._push_seq,  # noqa: SLF001
                )
                != stack_ck
            ):
                stack_ck = (src._pop_seq, src._push_seq)  # noqa: SLF001
                # 子文件源耗尽被 read() 弹栈：尾部不成 token 的字节（注释/
                # 空白尾）补盖 + 零宽 run 项（surface="" 不落译文面，ident
                # 随归属 piece 进 identity）——v1 flatten 保留这些字节。
                # \endinput 主动截停的尾巴不盖（flatten 同语义丢弃）。
                cur = {id(m): m.file_id for m in gullet_inputs}
                endinput = (
                    t.pos[0]
                    if t is not None
                    and t.kind == "consumed"
                    and t.text.partition(":")[0] == "endinput"
                    else -1
                )
                for k, fid in reversed(list(live_srcs.items())):
                    if k not in cur and fid >= 0 and fid != endinput:
                        vspan = self._cover_to(fid, len(files[fid]))
                        # preamble 档只盖不入队——emit 推迟整段兜底，run 项
                        # 会冲刷出与 preamble piece 重叠的 piece
                        if vspan.end > vspan.start and not self._preamble:
                            self._rappend(
                                "", self.vt.slice(vspan.start, vspan.end), vspan
                            )
                live_srcs = cur
            if t is None:
                break
            if self._preamble:
                if self._cons(0) > self._doc_begin:
                    # 覆盖已越过 \begin 起点——命中落在 def 体/if 死支等
                    # 整体消费区内（token 永不到主流）→ preamble literal 收尾
                    self._emit(
                        self.pieces[-1].span.end if self.pieces else 0,
                        len(self.vt),
                    )
                    self._preamble = False
                else:
                    self._preamble_tok(t, src)
                    continue
            if t.kind == "consumed":
                if self._in_group(t):
                    # 组内 marker（gen>0）：消费的是定义体区段（早已覆盖），
                    # 不是流边界——组界不破；input 型仍记 inputs[]。
                    tag, _, name = t.text.partition(":")
                    if tag in ("input", "input_tag"):
                        path = name.rpartition(":")[0] if tag == "input_tag" else name
                        self.state.inputs.append((len(self.vt), path))
                    continue
                self._close_group()
                self._on_consumed(t)
                continue
            if self._in_group(t):
                self._open_toks.append(t)
                continue
            if t.gen > 0:
                self._close_group()
                self._open_group(t)
                self._open_toks.append(t)
                continue
            self._close_group()
            self._dispatch(t, src)
        self._close_group()
        # 流耗尽 ≠ 覆盖完备：主文件尾部（尾随注释/空白不产 token）补盖进
        # vtex——单文件 identity 的收口。\\endinput 截停的子文件尾巴不盖
        # （flatten 语义：\\endinput 后字节不进输出）。
        if files and not self.in_arg and not self.mined:
            self._cover_to(0, len(files[0]))
        self._flush_run(len(self.vt))
        # flush 后仍可能有 vtex 尾巴无 piece 承接（纯注释/空白尾不产 run
        # 项）——补 LITERAL 保 pieces 平铺不变式。
        tail_from = self.pieces[-1].span.end if self.pieces else v0
        if tail_from < len(self.vt):
            self._emit(max(tail_from, v0), len(self.vt))

    def _preamble_tok(self, t: Tok, src: TokenSource) -> None:
        r"""Preamble 档单 token：覆盖进 vtex 不 emit。

        emit 推迟到 ``\\begin{document}`` 检出或 EOF 的 tail emit——整段
        一条 LITERAL piece。``input:``/``input_tag:`` marker 保持调用点
        排除 + ``inputs[]`` 登记；gen>0 token 只盖调用点（origin），本体
        字节属已盖定义区。
        """
        fid, a, b = t.pos
        if t.kind == "consumed":
            tag, _, name = t.text.partition(":")
            if tag in ("input", "input_tag"):
                path = name.rpartition(":")[0] if tag == "input_tag" else name
                self.state.inputs.append((len(self.vt), path))
                self._cover_to(fid, a)  # 调用点前间隙（注释/空白）照常进 vtex
                self._cons_bump(fid, b)
            else:
                self._cover_to(fid, b)
            return
        if t.kind == "cs" and t.text == "begin" and t.gen == 0:
            env, close_t, consumed = self._env_name(src)
            if env == "document" and close_t is not None:
                self._cover_to(fid, close_t.pos[2])
                start = self.pieces[-1].span.end if self.pieces else 0
                self._emit(start, len(self.vt))
                self._preamble = False
                return
            src.unread(consumed)
            self._cover_to(fid, b)
            return
        if t.kind == "cs" and t.text in _PKG_CMDS and t.gen == 0:
            # preamble 包声明：抽出 ``{pkg}`` 名单登记 argspec 门控；
            # 参数 token 回放照走 preamble 覆盖（含 \input 进来的声明）。
            args, _e = self._args_tok(src, fid, _PKG_ARG_SPEC, b)
            self._note_pkgs(args)
            self._unread_args(src, args)
            self._cover_to(fid, b)
            return
        if t.gen > 0:
            if t.origin is not None:
                self._cover_to(t.origin[0], t.origin[2])
            return
        self._cover_to(fid, b)

    @staticmethod
    def _tok_surface(t: Tok) -> str:
        """Token → surface 文本（展开组内渲染规则）。"""
        if t.kind == "cs":
            return "\\" + t.text
        if t.kind == "eol_par":
            return "\n\n"
        return t.text

    def _on_consumed(self, t: Tok) -> None:
        r"""``consumed`` marker：gullet 静默消费区间的显形（契约 §4）。

        ``text`` = ``tag:name``——``input:path`` 记 ``inputs[]`` 且调用点
        字节不进 vtex（输出物不含 ``\\input`` 行）；其余 flush+LITERAL
        盖区间（def 串不落 chunk，否则译文会删 def）。
        """
        fid, a, b = t.pos
        tag, _, name = t.text.partition(":")
        self._flush_run(len(self.vt))
        if tag in ("input", "input_tag"):
            path = name.rpartition(":")[0] if tag == "input_tag" else name
            self.state.inputs.append((len(self.vt), path))
            # 调用点前间隙（注释/空白）照常进 vtex——_cons_bump 只跳调用本体
            vspan = self._cover_to(fid, a)
            self._emit(vspan.start, vspan.end)
            self._cons_bump(fid, b)
        else:
            vspan = self._cover_to(fid, b)
            self._emit(vspan.start, vspan.end)

    def _cons_bump(self, fid: int, end: int) -> None:
        r"""``\\input`` 调用点字节只推进 cons 不进 vtex（输出不含该行）。"""
        if end > self._cons(fid):
            self.cons[fid] = end

    def _note_pkgs(self, args: list[_ArgTok]) -> None:
        r"""包加载命令已消费的 ``m`` 参 → 包名集入 ``state.pkgs``。

        ``\\usepackage{a,b}`` 逗号名单拆分；参未实消费（零宽占位）跳过。
        """
        for a in args:
            if a.spec is not None and a.spec.kind == "m" and a.fe > a.fs:
                for raw in "".join(x.text for x in a.toks).split(","):
                    nm = raw.strip()
                    if nm:
                        self.state.pkgs.add(nm)

    # ------------------------------------------------------------ 分派

    def _dispatch(self, t: Tok, src: TokenSource) -> None:  # noqa: C901, PLR0911, PLR0912, PLR0915 — §3.2 分派表 19 行平铺，顺序即语义
        r"""cs/结构 token 主分派——v1 ``_dispatch_cmd`` 的 token 版逐行移植。"""
        fid, _a, b = t.pos
        if t.kind == "cs":
            name = t.text
            # 1. \verb|..|/\lstinline 定界形（EOL 上限，W9/W10）
            if name in ("verb", "verb*", "lstinline"):
                self._handle_verb(t, src)
                return
            # 2/3. \def/\newif 族：gullet 消费发 consumed marker（主流首段
            #   处理）——漏网到此 = _ListSource 子扫内定义命令 → 落未知路径
            # 4. \begin{env}
            if name == "begin":
                self._handle_env_begin(t, src)
                return
            # 5. \end{env}
            if name == "end":
                self._handle_env_end(t, src)
                return
            # 6. cite 族 → [[CITE]] 进 run
            if name in CITE_NAMES or name.startswith("cite"):
                self._protect_cs(t, src, PhType.CITE, mand=1)
                return
            # 7. ref 族 → [[REF]]（排除 href 与 TRANSPARENT；hyperref 带
            #    可译 text 参，交 row19 → argspec chunk-arg——``*ref`` 后缀
            #    规则的 mand=1 会吞 ``[label]{text}`` 的 text 进 [[REF]]）
            if name in REF_NAMES or (
                name.endswith("ref")
                and name not in TRANSPARENT_NAMES
                and name not in ("href", "hyperref")
            ):
                self._protect_cs(t, src, PhType.REF, mand=1)
                return
            # 8. PROTECT_NAMES → 类型映射；url/path 认逐字定界形
            if name in PROTECT_NAMES:
                self._protect_cs(
                    t,
                    src,
                    _PROTECT_TYP.get(name, PhType.CMD),
                    mand=2 if name == "inputminted" else 1,
                    verbatim=name in ("url", "path"),
                )
                return
            # 9. \href{url}{text}：url→[[HREF]]，text 继续扫
            if name == "href":
                self._handle_href(t, src)
                return
            # 10. \input 族漏网（gullet 未解析成功）：LITERAL + inputs[]
            if name in INPUT_SCAN_CMDS:
                self._handle_input_cs(t, src, name)
                return
            # 11. chunk 参数命令
            if name in CHUNK_ARG_NAMES:
                self._handle_chunk_arg(t, src, name)
                return
            # 12. 整块保护（\author{..} → [[AUTHOR]]）
            if name in PROTECT_BLOCK_NAMES:
                self._handle_protect_block(t, src)
                return
            # 13. 透明命令：命令名进 run，参数随主流
            if name in TRANSPARENT_NAMES:
                self._rappend_tok(t)
                return
            # 14. 边界命令：文本 run 硬边界 + BOUNDARY_TAIL 结构尾参
            if name in BOUNDARY_NAMES:
                self._handle_boundary(t, src, name)
                return
            # 14b. \endinput 漏网（子扫内/未消费）：顶层截停
            if name == "endinput":
                self._handle_endinput(t, src)
                return
            # 15. 条件命令 \if*/\else/\fi/\or + \Xtrue/\Xfalse（IfSetter）
            #     + if* 宏调用——可求值支已被 gullet 消费成 if:/fi: marker
            #     夹心；到此者全走 _handle_cond 界标档（§8.6）
            m = self._resolve_macro(src, name)
            if isinstance(m, IfSetter) or COND_RX.match(name):
                self._handle_cond(t, src, name, m)
                return
            # 16. 数学定界 \[ \(；孤 \] \) 字面
            if name == "[":
                self._on_math_delim(t, src, "]")
                return
            if name == "(":
                self._on_math_delim(t, src, ")")
                return
            if name in ("]", ")"):
                self._rappend_tok(t)
                return
            # 17. 行内字面（重音/符号/品牌/旧式字体开关/单字符命令）
            if (
                name in INLINE_LITERAL_CMDS
                or name in FONT_SWITCHES
                or (len(name) == 1 and (name in ACCENT_CHARS or not name.isalpha()))
            ):
                self._rappend_tok(t)
                return
            # 18. gullet 宏表命中：env_begin/env_end 宏端点走 \begin/\end
            #     同路（target_env 已知免读 {env} 组；_find_env_end 认宏
            #     端点事件）；opaque/math（体无文本不展开——math 即 v1
            #     OPAQUE 含数学特征的那半）→ 整调用 [[MACRO]]
            kind = getattr(m, "kind", "")
            if kind == "env_begin":
                self._handle_env_begin(t, src, m)
                return
            if kind == "env_end":
                self._handle_env_end(t, src, m)
                return
            if kind in ("opaque", "math"):
                self._handle_opaque_macro(t, src, m)
                return
            # 19. 未知命令：宏表未命中先查 argspec 表（包签名驱动分派），
            #     表外再走 {/[ 探针 → [[CMD]]；否则逐字进 run
            self._handle_unknown_cs(t, src, name, m)
            return
        if t.kind == "mathshift":
            self._on_math(t, src)
            return
        if t.kind == "eol_par":
            cons0 = self._cons(fid)
            vspan, ident = self._cover_text(fid, b)
            self._rappend(
                self._gap_surface(fid, cons0, t.pos[1]) + "\n\n",
                ident,
                vspan,
            )
            self._flush_run(vspan.end)
            return
        if t.kind == "lbrace":
            self._scope_push(src)
            self._rappend_tok(t)
            return
        if t.kind == "rbrace":
            self._rappend_tok(t)
            self._scope_pop(src)
            return
        # letter/other/space/active/param/杂项 → run
        self._rappend_tok(t)

    def _scope_push(self, src: TokenSource) -> None:
        """组开 → ``gullet.macros.push_scope``（契约 §4 回报）。"""
        if isinstance(src, Gullet):
            src.macros.push_scope()

    def _scope_pop(self, src: TokenSource) -> None:
        """组闭 → ``pop_scope``（底帧不弹由 MacroTable 兜底）。"""
        if isinstance(src, Gullet):
            src.macros.pop_scope()

    def _math_depth(self, src: TokenSource, delta: int) -> None:
        r"""``\\ifmmode`` 求值数据源——数学环境进出回报。"""
        if isinstance(src, Gullet):
            src.math_depth += delta

    # ------------------------------------------------------------ math

    def _on_math(self, t: Tok, src: TokenSource) -> None:  # noqa: C901 — $$ 邻接/闭符/debt 分支平铺即 §3.3
        r"""``$``/``$$`` 配对：拉 token 到同窗 mathshift 止（``$$``=紧邻双 token）。"""
        fid, _a, b = t.pos
        disp = False
        nxt = src.read()
        if (
            nxt is not None
            and nxt.kind == "mathshift"
            and nxt.pos[0] == fid
            and nxt.pos[1] == b
        ):
            disp = True
        elif nxt is not None:
            src.unread([nxt])
        body: list[Tok] = []
        end_tok: Tok | None = None
        while True:
            x = src.read()
            if x is None:
                break
            if x.kind == "eol_par":
                src.unread([x])  # 段落边界不吞——回吐由主流断段
                break
            if x.kind == "mathshift":
                if not disp:
                    end_tok = x
                    break
                n2 = src.read()
                if (
                    n2 is not None
                    and n2.kind == "mathshift"
                    and n2.pos[0] == fid
                    and n2.pos[1] == x.pos[2]
                ):
                    end_tok = n2
                    break
                if n2 is not None:
                    src.unread([n2])
                body.append(x)
                continue
            body.append(x)
        if end_tok is None:
            cons0 = self._cons(fid)
            vspan = self._cover_to(fid, b)
            self._rappend(
                self._gap_surface(fid, cons0, t.pos[1]) + t.text,
                self.vt.slice(vspan.start, vspan.end),
                vspan,
            )
            self.state.warnings.append(ScanWarning("unpaired_dollar", vspan.start, "$"))
            if body:
                src.unread(body)
            return
        eb = end_tok.pos[2]
        vspan = self._cover_to(fid, eb)
        self._math_depth(src, 0)  # 体内 token 已消费，math_depth 进出相抵
        ph = self._ph(PhType.MATH, self.vt.slice(vspan.start, vspan.end))
        self._rappend_ph(PhType.MATH, ph, vspan, t)

    # ------------------------------------------------------------ verb

    def _handle_verb(self, t: Tok, src: TokenSource) -> None:  # noqa: C901, PLR0912 — verb 三形各一支，平铺即 W9/W10
        r"""``\\verb|..|``/``\\verb*``/``\\lstinline[opt]|..|``/``{...}`` 配对形。

        定界符 = 命令后首个非空白 token；``{..}`` 配对形按平衡组收；
        文件字节搜闭合（EOL 上限）+ ``skip_past`` resync（W9）。
        """
        fid, _a, b = t.pos
        name = t.text
        pulled: list[Tok] = []  # 命令后拉出的全部 token（abort 整体回放）
        d = src.read()
        if d is not None:
            pulled.append(d)
        if d is not None and name.startswith("verb") and d.text == "*":
            d = src.read()  # \verb* 星号吃掉（v1 裸位判定，无 ws_skip）
            if d is not None:
                pulled.append(d)
        if name == "lstinline":
            # v1 此处 ws_skip（全空白含 \n\n）非 ws_skip_arg
            while d is not None and d.kind in ("space", "eol_par"):
                d = src.read()
                if d is not None:
                    pulled.append(d)
            if d is not None and d.kind == "other" and d.text == "[":
                hit = self._collect_group(src, d, brace=False)
                if hit is not None:
                    inner, closer = hit
                    pulled.extend(inner)
                    pulled.append(closer)
                    d = self._read_skipws(src, pulled)
                    if d is not None:
                        pulled.append(d)
                # hit None：组 token 已回吐且仍在 pulled——``[`` 落定界符路径
        if d is None or d.kind in ("space", "eol_par"):
            src.unread(pulled)
            self._rappend_tok(t)
            return
        if d.kind == "lbrace":
            # \verb{...} 配对形：字节级逐字配对（``%`` 不作注释，v1
            # match_brace(verbatim=True) 同）——token 收集会被 ``%``
            # 吃掉闭括号直排 EOF
            e = match_brace(self.file_texts[fid], d.pos[1], verbatim=True)
            if e is None:
                src.unread(pulled)  # 未消费任何组 token——全量回放（含 d）
                self._rappend_tok(t)
                return
            vspan = self._cover_to(fid, e)
            self._rappend_ph(
                PhType.VERB,
                self._ph(PhType.VERB, self.vt.slice(vspan.start, vspan.end)),
                vspan,
                t,
            )
            self._skip_past(src, fid, e)
            return
        # 定界符 = token 的文件首字符（cs → ``\``；多字符 token 取首字符，
        # 与 v1 单字符 ``d = tex[k]`` 语义一致）
        delim = self.file_texts[fid][d.pos[1]]
        ftext = self.file_texts[fid]
        close = ftext.find(delim, d.pos[1] + 1)
        eol = ftext.find("\n", d.pos[1] + 1)
        if close < 0 or (0 <= eol < close):
            cons0 = self._cons(fid)
            vspan = self._cover_to(fid, b)
            self._rappend(
                self._gap_surface(fid, cons0, t.pos[1]) + "\\" + name,
                self.vt.slice(vspan.start, vspan.end),
                vspan,
            )
            src.unread(pulled)
            return
        end = close + 1
        vspan = self._cover_to(fid, end)
        self._rappend_ph(
            PhType.VERB,
            self._ph(PhType.VERB, self.vt.slice(vspan.start, vspan.end)),
            vspan,
            t,
        )
        self._skip_past(src, fid, end)

    def _skip_past(self, src: TokenSource, fid: int, end: int) -> None:
        """Resync ``fid`` 源到 ``end``——raw 区段不经 token 流（契约 §4）。

        调 ``gullet.skip_past`` 真 API（tokbuf 残骸剔除 + 栈深找 fid +
        i 只前进）；``_ListSource`` 丢队首已覆盖 token（子扫同源语义）。
        失败时 gullet 已记 ``verb_resync_failed``，分段器不退化——位置
        已对齐，后续 token 照常（与今日无 verb 处理等价）。
        """
        src.skip_past(fid, end)

    # ------------------------------------------------------------ env

    def _env_name(self, src: TokenSource) -> tuple[str | None, Tok | None, list[Tok]]:
        r"""``{env}`` 组收集：返回 (env 名, rbrace token, 全消费 token 列)。

        v1 ``env_name_at`` 用 ``ws_skip_arg``——space token 跳过、
        ``eol_par`` 即停（par 边界不跨）；名内花括号按 ``match_brace``
        深度配对。失败返回 ``(None, None, consumed)``——调用方负责
        ``unread(consumed)``（v1 返回 ``i`` 原位重扫的等价物）。
        """
        consumed: list[Tok] = []
        open_t = src.read()
        while open_t is not None and open_t.kind == "space":
            consumed.append(open_t)
            open_t = src.read()
        if open_t is not None:
            consumed.append(open_t)
        if open_t is None or open_t.kind != "lbrace":
            return None, None, consumed
        name_toks: list[Tok] = []
        depth = 1
        while True:
            x = src.read()
            if x is None:
                return None, None, consumed
            consumed.append(x)
            if x.kind == "lbrace":
                depth += 1
            elif x.kind == "rbrace":
                depth -= 1
                if depth == 0:
                    name = "".join(t2.text for t2 in name_toks).strip()
                    return name, x, consumed
            name_toks.append(x)

    def _handle_env_begin(  # noqa: C901, PLR0911, PLR0912, PLR0915 — §3.5 环境四分类各一段，平铺即规则表
        self, t: Tok, src: TokenSource, m: MacroDef | None = None
    ) -> None:
        r"""``\begin{env}`` token 版：verbatim/math/protected/transparent。

        ``m`` 非空 = env_begin 宏端点（``\beq`` 形）：env 取
        ``m.target_env``、tag 区间 = cs 本体（无 ``{env}`` 组可读）。
        """
        fid, _a, _b = t.pos
        if m is None:
            env, close_t, consumed = self._env_name(src)
            if env is None or close_t is None:
                src.unread(consumed)
                self._rappend_tok(t)
                return
        else:
            env, close_t = m.target_env, t
        reg = src.macros.lookup_env(env) if isinstance(src, Gullet) else None
        # 环境表未命中且族表全不知 → argspec env 条目：body_role 决定体路由
        # （verbatim/math/protect 走同名路径；text 落下方透明尾）。族表已
        # 知的 env（含 ARG_TRANSPARENT/ENV_MANDATORY_ARG）不交给 argspec——
        # 既有语义钉死（如 thebibliography 透明体 @X1 trap），数据侧
        # body_role 不覆盖族表分类。
        ae = (
            argspec_lookup_env(env, self.state.pkgs)
            if reg is None
            and env not in VERBATIM_ENVS
            and env not in MATH_ENVS
            and env not in PROTECTED_ENVS
            and env not in ARG_TRANSPARENT_ENVS
            and env not in ENV_MANDATORY_ARG
            else None
        )
        v_begin = self._cover_to(fid, close_t.pos[2])
        if env in VERBATIM_ENVS or (ae is not None and ae.body_role == "verbatim"):
            self._flush_run(v_begin.start)
            if m is not None:
                # 宏端点的 \end 面是 \eev 形宏事件——无 \end{env} 字面可
                # find，走 token 级配对（体照常按 raw token 扫描收集，
                # 渲染直切 vt 字节 = 字面）
                hit = self._find_env_end(src, env, t.pos)
                if hit is None:
                    self._emit(v_begin.start, v_begin.end)
                    self.state.warnings.append(
                        ScanWarning("unclosed_env", v_begin.start, env)
                    )
                    return
                _tag, last, _body = hit
                vspan = self._cover_to(last.pos[0], last.pos[2])
                self._emit_ph(
                    PhType.VERB,
                    v_begin.start,
                    vspan.end,
                    self.vt.slice(v_begin.start, vspan.end),
                )
                return
            pat = "\\end{" + env + "}"
            if env.startswith("filecontents"):
                # filecontents 逐行读体、end 行首独占才算闭合（kernel 语义）——
                # 裸 find 会被体内 PostScript/注释里的行中 \end decoy 截短（W26）
                rx = re.compile(rf"(?m)^[ \t]*{re.escape(pat)}")
                fm = rx.search(self.file_texts[fid], close_t.pos[2])
                k = -1 if fm is None else fm.end() - len(pat)
            else:
                k = self.file_texts[fid].find(pat, close_t.pos[2])
            if k < 0:
                self._emit(v_begin.start, v_begin.end)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", v_begin.start, env)
                )
                return
            end = k + len(pat)
            vspan = self._cover_to(fid, end)
            self._emit_ph(
                PhType.VERB,
                v_begin.start,
                vspan.end,
                self.vt.slice(v_begin.start, vspan.end),
            )
            self._skip_past(src, fid, end)
            return
        if env in MATH_ENVS or (ae is not None and ae.body_role == "math"):
            hit = self._find_env_end(src, env, t.pos)
            if hit is None:
                self._flush_run(v_begin.start)
                self._emit(v_begin.start, v_begin.end)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", v_begin.start, env)
                )
                return
            _tag, last, _body = hit
            vspan = self._cover_to(last.pos[0], last.pos[2])
            # v1：math env ph 进 run（行内数学嵌段语义），非独立 piece
            self._rappend_ph(
                PhType.MATH,
                self._ph(PhType.MATH, self.vt.slice(v_begin.start, vspan.end)),
                Span(v_begin.start, vspan.end),
                t,
            )
            self._math_depth(src, 0)
            return
        if (
            env in PROTECTED_ENVS
            or (reg is not None and reg.kind == "protected")
            or (ae is not None and ae.body_role == "protect")
        ):
            hit = self._find_env_end(src, env, t.pos)
            if hit is None:
                self._flush_run(v_begin.start)
                self._emit(v_begin.start, v_begin.end)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", v_begin.start, env)
                )
                return
            tag, last, body_toks = hit
            self._flush_run(v_begin.start)
            body, vend = self._env_with_mined(
                env=env, vbegin=v_begin, tag=tag, last=last, body_toks=body_toks
            )
            self._emit_ph(PhType.ENV, v_begin.start, vend, body)
            return
        # transparent/未知/注册透明 env
        if self.in_arg:
            transparent = (
                env in ARG_TRANSPARENT_ENVS
                or (reg is not None and reg.kind in ("transparent", "theorem"))
                or ae is not None  # 到尾段即 body_role=text 的 argspec env
            )
            if transparent:
                end = self._eat_env_args(src, fid, close_t.pos[2], env, reg, ae)
                vspan = self._cover_to(fid, end)
                self._rappend_ph(
                    PhType.ENVTAG,
                    self._ph(PhType.ENVTAG, self.vt.slice(v_begin.start, vspan.end)),
                    Span(v_begin.start, vspan.end),
                    t,
                )
                self.env_stack.append(env)
                self._scope_push(src)
                return
            # in_arg 未知/结构环境 → 整段 [[ENV]] 进 run（v1 泄漏 C2 修复）
            hit = self._find_env_end(src, env, t.pos)
            if hit is None:
                self._rappend_ph(
                    PhType.ENVTAG,
                    self._ph(PhType.ENVTAG, self.vt.slice(v_begin.start, v_begin.end)),
                    v_begin,
                    t,
                )
                self.state.warnings.append(
                    ScanWarning("unclosed_env", v_begin.start, env)
                )
                return
            tag, last, body_toks = hit
            body, vend = self._env_with_mined(
                env=env, vbegin=v_begin, tag=tag, last=last, body_toks=body_toks
            )
            self._rappend_ph(
                PhType.ENV, self._ph(PhType.ENV, body), Span(v_begin.start, vend), t
            )
            return
        self._flush_run(v_begin.start)
        end = self._eat_env_args(src, fid, close_t.pos[2], env, reg, ae)
        vrow = self._cover_to(fid, end)
        self._emit(v_begin.start, vrow.end)  # \begin 行（含吃掉的环境参）literal
        self.env_stack.append(env)
        self._scope_push(src)

    def _handle_env_end(
        self, t: Tok, src: TokenSource, m: MacroDef | None = None
    ) -> None:
        r"""``\end{env}``：in_arg→ENVTAG；``\end{document}``→顶层截停。

        ``m`` 非空 = env_end 宏端点（``\eeq`` 形）：env 取
        ``m.target_env``、tag 区间 = cs 本体。
        """
        fid, _a, _b = t.pos
        if m is None:
            env, close_t, consumed = self._env_name(src)
            if env is None or close_t is None:
                src.unread(consumed)
                self._rappend_tok(t)
                return
        else:
            env, close_t = m.target_env, t
        vspan = self._cover_to(fid, close_t.pos[2])
        if self.in_arg:
            self._rappend_ph(
                PhType.ENVTAG,
                self._ph(PhType.ENVTAG, self.vt.slice(vspan.start, vspan.end)),
                vspan,
                t,
            )
            for _ in range(self._env_pop(env, vspan.start)):
                self._scope_pop(src)
            return
        self._flush_run(vspan.start)
        self._emit(vspan.start, vspan.end)
        if env == "document" and not self.in_arg:
            # \end{document} 之后全逐字（顶层截停，v1 row5）
            tail = self._cover_to(fid, len(self.file_texts[fid]))
            self._emit(vspan.end, tail.end)
            self._stop = True
            return
        for _ in range(self._env_pop(env, vspan.start)):
            self._scope_pop(src)

    def _env_pop(self, env: str, vpos: int) -> int:
        r"""v1 ``_env_pop`` 移植：弹 env 栈，返回弹出数（= scope_pop 次数）。

        栈顶即 target → 1；深匹配 → 隐式弹中间层 + ``env_mismatch``；
        栈空/无匹配 → ``stray_end`` + 0。
        """
        target = env.rstrip("*")
        if self.env_stack and self.env_stack[-1].rstrip("*") == target:
            self.env_stack.pop()
            return 1
        if target in {e.rstrip("*") for e in self.env_stack}:
            popped: list[str] = []
            while self.env_stack and self.env_stack[-1].rstrip("*") != target:
                popped.append(self.env_stack.pop())
            if self.env_stack:
                self.env_stack.pop()
            self.state.warnings.append(
                ScanWarning("env_mismatch", vpos, f"\\end{{{env}}} 隐式关闭 {popped}")
            )
            return len(popped) + 1
        self.state.warnings.append(ScanWarning("stray_end", vpos, f"\\end{{{env}}}"))
        return 0

    def _eat_env_args(  # noqa: C901, PLR0912, PLR0913, PLR0917 — opt/mand 两段判定平铺即 v1 行序
        self,
        src: TokenSource,
        fid: int,
        pos: int,
        env: str,
        reg: object | None,
        ae: ArgspecEntry | None = None,
    ) -> int:
        r"""``\begin`` 行尾 token 版：版式 ``[opt]`` + 强制 ``{arg}`` 数。

        ``[opt]`` 内容过 ``env_opt_is_format``——版式参吃掉进 LITERAL，
        定理类标题正文回吐随主流进 chunk（F6 修复语义）。mand =
        ``ENV_MANDATORY_ARG`` ∪ 登记 ``spec`` 的 ``m`` 槽数。v1
        ``ws_skip_arg`` 结果恒入 ``pos``——ws token 拉出即消费（字节
        随 ``_cover_to`` 进 begin 行），只参数 token 未中才 ``unread``。
        ``ae`` 非空且带签名 → :meth:`_eat_env_args_spec` 签名驱动版。
        """
        if ae is not None and ae.signature:
            return self._eat_env_args_spec(src, fid, pos, env, ae)
        pulled: list[Tok] = []
        x = self._peek_nonspace(src, pulled)
        if x is None:
            if pulled:
                pos = pulled[-1].pos[2]  # par/EOF 前 ws 已消费（v1 pos 过 ws）
        elif x.kind == "other" and x.text == "[":
            hit = self._collect_group(src, x, brace=False)
            if hit is None:
                return x.pos[1]  # `[` 未闭——组已回吐主流重扫；ws 在 pos 内
            inner, closer = hit
            content = self.file_texts[fid][x.pos[2] : closer.pos[1]]
            if env_opt_is_format(env, content):
                pos = closer.pos[2]
            else:
                src.unread([x, *inner, closer])  # 标题正文回吐进 chunk
                return x.pos[1]
        else:
            src.unread([x])
            pos = x.pos[1]
        mand = 1 if env in ENV_MANDATORY_ARG else 0
        if reg is not None:
            mand = max(
                mand,
                sum(1 for a in getattr(reg, "spec", ()) if a.kind == "m"),
            )
        for _ in range(mand):
            p2: list[Tok] = []
            x = self._peek_nonspace(src, p2)
            if x is None:
                if p2:
                    pos = p2[-1].pos[2]
                break
            if x.kind != "lbrace":
                src.unread([x])
                pos = x.pos[1]
                break
            hit = self._collect_group(src, x, brace=True)
            if hit is None:
                pos = x.pos[1]  # `{` 未闭已回吐；ws 消费进 pos
                break
            pos = hit[1].pos[2]
        return pos

    def _eat_env_args_spec(
        self, src: TokenSource, fid: int, pos: int, env: str, e: ArgspecEntry
    ) -> int:
        r"""Argspec 签名驱动的 ``\begin`` 尾参：非文本参吃掉进 LITERAL。

        ``text``/``opt-text`` 角色参回吐主流——beamer
        ``\\begin{frame}{Title}`` 的 ``d{}`` 标题吃进字面段就永不进
        chunk（今日 ``{title}`` 组随正文流的召回面不能回退）。可选位
        （``o``/``O``/``d``/``D``）仍过 ``env_opt_is_format``——数据里
        ``skip`` 角色对 ``[opt]`` 只是「非文本」缺省标注，定理标题
        ``[Name]`` 不归其管（F6 语义保持）。
        """
        spec = _chunk_spec_cached(e.signature)
        args, _end = self._args_tok(src, fid, spec, pos, allow_single_token=True)
        eat_end = pos
        for k, a in enumerate(args):
            if a.fe <= a.fs:
                continue  # 零宽占位（all_toks 空）
            kind = a.spec.kind if a.spec is not None else ""
            role = e.arg_roles[k] if k < len(e.arg_roles) else "skip"
            if kind in ("o", "O", "d", "D"):
                # 可选位：role=text 的定界参是标题（frame ``{Title}``）
                # 直接回吐——``env_opt_is_format`` 会把单字符标题误判
                # 成位置字母；``d<>`` 叠层 spec 恒版式（``+-`` 内容不在
                # 版式字符表）；其余角色过版式判定（``skip`` 对 ``[opt]``
                # 只是缺省标注，定理 ``[Name]`` 不归其管——F6 语义保持）。
                content = self.file_texts[fid][a.cs : a.ce]
                if role == "text" or (
                    a.spec.delim != "<>" and not env_opt_is_format(env, content)
                ):
                    self._unread_args(src, args[k:])
                    return eat_end
                eat_end = a.fe
                continue
            if role in ("text", "opt-text"):
                self._unread_args(src, args[k:])
                return eat_end
            eat_end = a.fe
        return eat_end

    def _env_with_mined(
        self,
        *,
        env: str,
        vbegin: Span,
        tag: Tok,
        last: Tok,
        body_toks: list[Tok],
    ) -> tuple[str, int]:
        r"""保护环境体 → in_arg 子扫挖 caption/footnote → 渲染体。

        返回 ``(body, vend)``：body = begin 行切片 + mined 渲染 + end tag
        切片（``_env_with_mined`` token 版）；vend = ``\end{env}`` 后 vtex 位。
        体 token 已被 ``_find_env_end`` 消费——子扫 ``_ListSource`` 重放
        只负责渲染，覆盖经共享 vt/cons 直落父区间。
        """
        if self.gen >= MAX_GEN:
            self.state.warnings.append(
                ScanWarning("gen_overflow", vbegin.start, f"env:{env}")
            )
            vend = self._cover_to(last.pos[0], last.pos[2])
            return self.vt.slice(vbegin.start, vend.end), vend.end
        # v1 ``MINED_ONLY + in_arg=False``：run 全 literal 但分派照常——
        # \caption 照产 chunk（in_arg=True 会内联化不产，T12 回归）
        sub = self.spawn(in_arg=False, mined=True)
        sub.env_stack.append(env)
        sub.scan(_ListSource(body_toks), self.file_texts)
        sub_end = len(self.vt)  # 子扫 pieces 平铺到此（scan 尾部兜底保证）
        self._cover_to(tag.pos[0], tag.pos[1])  # 子扫丢 token 的体尾字节兜底
        vend = self._cover_to(last.pos[0], last.pos[2])
        rendered = "".join(p.text for p in sub.pieces)
        if sub_end < vend.start:
            # 已盖未挂 piece 的残余字节（peek 吞掉的尾空白/杂项 token）——
            # 不进 rendered 则 ENV 体丢字节，identity 破（F-尾丢）
            rendered += self.vt.slice(sub_end, vend.start)
        return (
            self.vt.slice(vbegin.start, vbegin.end)
            + rendered
            + self.vt.slice(vend.start, vend.end)
        ), vend.end

    def _resolve_macro(self, src: TokenSource, name: str) -> object | None:
        r"""宏表查名（``Alias`` 解一层）。

        Gullet 源查 ``src.macros``；``_ListSource`` 子扫查共享的
        ``state.macros``——同一张表，v1 平表在子扫内可查的对应物
        （in_arg/env 体里的 ``\\beq`` 端点宏也命中）。时点近似：表
        反映的是子扫启动位的 scope 态，体内迟定义不回看。
        """
        tab = src.macros if isinstance(src, Gullet) else self.state.macros
        return tab.resolve(tab.lookup(name))

    @staticmethod
    def _env_sig_tok(src: TokenSource, target: str) -> frozenset:
        r"""Target env 端点宏签名（v1 ``_env_sig`` token 版）。

        gullet scope 链全量快照 ``(name, kind, scope_depth)``——迟到
        ``\def`` 登记/改义/scope 弹出使墓标事件面失真即作废。
        ``_ListSource`` → 空集：子扫 token 列固定、宏表在重放内不突变，
        单次扫描内墓标自洽（墓标本体也不跨子扫共享）。
        """
        if not isinstance(src, Gullet):
            return frozenset()
        out = set()
        for depth_i, scope in enumerate(src.macros.scopes):
            for name, entry in scope.items():
                m = src.macros.resolve(entry)
                kind = getattr(m, "kind", "")
                if (
                    kind in ("env_begin", "env_end")
                    and getattr(m, "target_env", "").rstrip("*") == target
                ):
                    out.add((name, kind, depth_i))
        return frozenset(out)

    def _replay_dead(
        self, src: TokenSource, tag_span: tuple[int, int, int]
    ) -> tuple[Tok, Tok, list[Tok]] | None:
        r"""墓标命中回放：拉到 end tag 末 token，tag 前 token 归 body。

        ``tag_span`` = ``(fid, tag_start, tag_end)``——回放期事件 token 与
        录制期同一批（raw 流子集保序）。失效检测：同 fid raw token 越过
        ``tag_end``（end tag 已被中间展开/消费吃掉）、tag 区被外来 token
        打断、tag 首 token 缺失、流尽——一律回吐已拉 token 返回 None，
        由 ``_find_env_end`` 正常续扫（事件重录，墓标保持完备）。
        """
        tfid, ts, te = tag_span
        pulled: list[Tok] = []
        body: list[Tok] = []
        tag: list[Tok] = []
        ok = False
        while True:
            x = src.read()
            if x is None:
                break
            pulled.append(x)
            raw_here = x.kind != "consumed" and x.gen == 0 and x.pos[0] == tfid
            if raw_here and x.pos[1] >= te:
                break  # 越过 tag 末——end tag 已被消费，墓标失效
            if raw_here and x.pos[1] >= ts:
                tag.append(x)
                if x.pos[2] == te:
                    ok = tag[0].pos[1] == ts
                    break
                continue
            if tag:
                break  # tag 区间被外来 token（展开注入等）打断——失效
            body.append(x)
        if ok:
            return tag[0], tag[-1], body
        src.unread(pulled)
        return None

    def _find_env_end(  # noqa: C901, PLR0912, PLR0915 — begin/end/verb/宏端点四分支单遍查找
        self, src: TokenSource, env: str, qpos: tuple[int, int, int]
    ) -> tuple[Tok, Tok, list[Tok]] | None:
        r"""Token 版 env 配对（``read()`` 原始流——前瞻不触发展开副作用）。

        命中返回 ``(end_cs_or_macro_tok, 末位 token, body_toks)``——tag
        起点 = 首元 ``pos[1]``、体 token 列供 ``_env_with_mined`` 重放；
        未命中回吐全部已收 token 返回 None。
        ``*`` 两侧归一（泄漏 C1）；verb 定界体/嵌套 verbatim env 体内
        假 ``\end`` 不计（v1 ``skip_verb_at``/VERBATIM 跳的 token 版）。

        F12：未闭合扫描把端点事件存 ``_env_dead`` 墓标（``_EnvDeadTok``
        ——seq+pos 锚，详见类 docstring）；同 target、签名未变的后续查询
        按盈余相等直答 + 文件区间回放，不再 O(n) 重扫到 EOF。
        ``qpos`` = 本次 ``\begin`` tag 首 token 的 pos。
        """
        target = env.rstrip("*")
        sig = self._env_sig_tok(src, target)
        dead = self._env_dead.get(target)
        if dead is not None and dead.sig == sig:
            k_q = dead.bidx.get(qpos, -1)
            if k_q >= 0:
                qs = dead.begins[k_q]
                sj = (k_q + 1) - bisect_left(dead.ends, qs)
                for k in range(bisect_left(dead.ends, qs), len(dead.ends)):
                    if dead.s_end[k] == sj:
                        hit = self._replay_dead(src, dead.end_tag[k])
                        if hit is not None:
                            return hit
                        break  # 失效已回吐 → 落正常扫描（事件重录）
                else:
                    return None  # 事件流完备——无配对即真未闭合
        collected: list[Tok] = []
        begins: list[int] = []
        begin_pos: list[tuple[int, int, int]] = []
        ends: list[int] = []
        end_tag: list[tuple[int, int, int]] = []
        depth = 1
        while True:
            x = src.read()
            if x is None:
                src.unread(collected)
                self._env_dead[target] = _EnvDeadTok(
                    sig,
                    begins,
                    begin_pos,
                    {p: i for i, p in enumerate(begin_pos)},
                    ends,
                    end_tag,
                    [bisect_left(begins, e) - k for k, e in enumerate(ends)],
                )
                return None
            collected.append(x)
            if x.kind != "cs":
                continue
            seq = len(collected) - 1  # 事件位 = tag 首 token 的拉取序号
            if x.text in ("verb", "verb*", "lstinline"):
                self._skip_verb_toks(src, collected)
                continue
            if isinstance(src, Gullet) and x.text in INPUT_CMDS:
                # 前瞻 read() 不触发展开——\input 族收进 body_toks 会随
                # _ListSource 子扫漏网成 literal（v1 flatten 先内联）。
                # 交回 gullet 正常展开：marker 顶替已入列的 cs（pos 覆盖
                # 整调用）、新源 token 由后续 read() 照常进 collected。
                try:
                    hit = src._do_input(x, x.text)  # noqa: SLF001 — §4 契约面：前瞻展开经 gullet 内部入口
                except ArgMismatch:
                    # 流尽（\input{ 未闭合）——残参回放走漏网路，cs 留 literal
                    src.unread(src._trace)  # noqa: SLF001 — ArgMismatch 回吐协议（§3.5）
                    hit = None
                if hit is not None and hit is not x:
                    collected[-1] = hit
                continue
            if x.text in ("begin", "end"):
                n, c, grp = self._env_name(src)
                if n is None or c is None:
                    # 失败 token 回吐重分派——grp 里可能藏着真 \end{target}
                    # （``\begin \end{figure}`` 形），v1 pos 不动等价
                    src.unread(grp)
                    continue
                collected.extend(grp)
                if n.rstrip("*") != target:
                    if n in VERBATIM_ENVS and x.text == "begin":
                        self._skip_verbatim_env_toks(src, n, collected)
                    continue
                if x.text == "begin":
                    depth += 1
                    begins.append(seq)
                    begin_pos.append(x.pos)
                else:
                    depth -= 1
                    if depth == 0:
                        body = collected[: -(1 + len(grp))]
                        return x, c, body
                    ends.append(seq)
                    end_tag.append((x.pos[0], x.pos[1], c.pos[2]))
                continue
            m = self._resolve_macro(src, x.text)
            kind = getattr(m, "kind", "")
            tgt = getattr(m, "target_env", "")
            if kind in ("env_begin", "env_end") and tgt.rstrip("*") == target:
                if kind == "env_begin":
                    depth += 1
                    begins.append(seq)
                    begin_pos.append(x.pos)
                else:
                    depth -= 1
                    if depth == 0:
                        return x, x, collected[:-1]
                    ends.append(seq)
                    end_tag.append((x.pos[0], x.pos[1], x.pos[2]))

    def _skip_verb_toks(  # noqa: C901 — 定界三形平铺
        self, src: TokenSource, collected: list[Tok]
    ) -> None:
        r"""``\verb``/``\lstinline`` 定界体 token 跳读（假 ``\end`` 不计）。

        定界符 = 下一 token 文本；同符再现或 ``eol_par``/EOF 止——字节版
        ``skip_verb_at`` 的 token 近似（配对 ``{..}`` 形按单 token 近似，
        组内 ``\end`` 误计风险与字节版同阶、可接受）。
        """
        d = src.read()
        if d is not None:
            collected.append(d)
        if d is None:
            return
        if d.kind == "other" and d.text == "*":
            d = src.read()
            if d is not None:
                collected.append(d)
            if d is None:
                return
        if d.kind == "lbrace":
            hit = self._collect_group(src, d, brace=True)
            if hit is not None:
                inner, closer = hit
                collected.extend(inner)
                collected.append(closer)
            return
        delim = d.text
        while True:
            x = src.read()
            if x is None:
                return
            collected.append(x)
            if x.kind == "eol_par" or x.text == delim:
                return

    def _skip_verbatim_env_toks(
        self, src: TokenSource, env: str, collected: list[Tok]
    ) -> None:
        r"""嵌套 verbatim env 体整段跳读（体内 ``\end{target}`` 是字面）。"""
        depth = 1
        while True:
            x = src.read()
            if x is None:
                return
            collected.append(x)
            if x.kind != "cs" or x.text not in ("begin", "end"):
                continue
            n, c, grp = self._env_name(src)
            if n is None or c is None:
                src.unread(grp)  # 回吐重分派（同 _find_env_end）
                continue
            collected.extend(grp)
            if n != env:
                continue
            depth += 1 if x.text == "begin" else -1
            if depth == 0:
                return

    # ------------------------------------------------------------ 参数读取（token 版 _args）

    @staticmethod
    def _peek_nonspace(src: TokenSource, pulled: list[Tok]) -> Tok | None:
        r"""拉下一非 space token；跳过的 space token 追加进 ``pulled``。

        ``eol_par``/EOF → None（eol_par 立即回吐——``\\par`` 是不定界参数
        边界，同 ``ws_skip_arg`` 的 par 停语义）。``pulled`` 约定：space
        token 拉出即失主流——参数命中时其字节在覆盖区间内（``pulled``
        并进 ``all_toks`` 或随调用点覆盖），放弃路径必须
        ``src.unread([*pulled, x])`` 全量回放（字节版「pos 停在不匹配
        位、空白由主流重扫」的等价物，否则 ``\\cite{a} more`` 的空格
        从 surface 消失）。
        """
        while True:
            x = src.read()
            if x is None:
                return None
            if x.kind == "space":
                pulled.append(x)
                continue
            if x.kind == "eol_par":
                src.unread([x])
                return None
            return x

    @staticmethod
    def _read_skipws(src: TokenSource, pulled: list[Tok]) -> Tok | None:
        r"""``ws_skip``（全空白含 ``\n\n``）的 token 版。

        ``\lstinline``/``\import`` 第二参等 v1 用 ``ws_skip`` 而非
        ``ws_skip_arg`` 的位点。读过的 ws token 进 ``pulled``，
        返回首个非空白 token（不 append）。
        """
        while True:
            x = src.read()
            if x is None:
                return None
            if x.kind in ("space", "eol_par"):
                pulled.append(x)
                continue
            return x

    @staticmethod
    def _collect_group(
        src: TokenSource, open_t: Tok, *, brace: bool
    ) -> tuple[list[Tok], Tok] | None:
        r"""``open_t``（lbrace/``[``）之后拉配对组 → ``(inner_toks, closer)``。

        EOF 截断 → 已拉 token（含 open_t）全部回吐、返 None——调用方按
        参数不匹配处理（字节版 ``match_brace`` 返 None 且 ``pos`` 不动
        的等价物）。``eol_par`` 在组内是普通内容 token（``match_brace``
        不判段界），继续收集。

        ``_unmatched_open``（源侧可选挂载，``_ListSource`` 有）：扫到流尽
        仍未归零时，深度栈上残留的 open 全是「整流无配对」——配对关系按
        栈唯一，记入 memo；同 open 再探直返（回吐 open_t 与实扫失败同态）。
        """
        dead = getattr(src, "_unmatched_open", None)
        if dead is not None and (open_t.pos, open_t.gen) in dead:
            src.unread([open_t])
            return None
        pulled = [open_t]
        inner: list[Tok] = []
        opens: list[tuple[tuple[int, int, int], int]] = [(open_t.pos, open_t.gen)]
        depth = 1
        while True:
            x = src.read()
            if x is None:
                if dead is not None:
                    dead.update(opens)
                src.unread(pulled)
                return None
            pulled.append(x)
            if brace:
                is_open = x.kind == "lbrace"
                is_close = x.kind == "rbrace"
            else:
                is_open = x.kind == "other" and x.text == "["
                is_close = x.kind == "other" and x.text == "]"
            if is_open:
                depth += 1
                opens.append((x.pos, x.gen))
            if is_close:
                depth -= 1
                if depth == 0:
                    return inner, x
                opens.pop()
            inner.append(x)

    def _args_tok(  # noqa: C901, PLR0912, PLR0913, PLR0915 — argspec 字母各一分支，平铺即 §5.3 表
        self,
        src: TokenSource,
        fid: int,
        spec: list[ArgSpec] | int,
        pos0: int,
        *,
        has_opt: bool = False,
        allow_single_token: bool = True,
    ) -> tuple[list[_ArgTok], int]:
        r"""v1 ``_args`` 的 token 版：按 argspec 从 ``read()`` 流读参。

        ``pos0`` = cs 名后文件位（零消费时零宽锚点）。返回 ``(args, end)``，
        ``end`` = 最后消费位。每参前置 ws token 记进 ``pulled``——命中并入
        ``all_toks``（放弃路径 ``_unread_args`` 一并回放，与 v1「pos 不动
        全量重扫」等价）；未中连同目标 token 一起 ``unread``。
        """
        items = [ArgSpec("m")] * spec if isinstance(spec, int) else list(spec)
        if has_opt:
            items = [ArgSpec("o"), *items]
        out: list[_ArgTok] = []
        end = pos0
        for s in items:
            pulled: list[Tok] = []
            x = self._peek_nonspace(src, pulled)
            if x is None:
                # par/EOF 停：ws 回放主流重扫（v1 主循环从 end 续读）
                src.unread(pulled)
                out.append(_ArgTok(fid, end, end, end, end, spec=s))
                continue
            if s.kind in ("m", "v"):
                if x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                    hit = self._collect_group(src, x, brace=x.kind == "lbrace")
                    if hit is None:
                        # 组 token 已回吐；ws 回放（v1 pos 停原位的等价物）
                        src.unread(pulled)
                        break
                    inner, closer = hit
                    out.append(
                        _ArgTok(
                            fid,
                            x.pos[2],
                            closer.pos[1],
                            x.pos[1],
                            closer.pos[2],
                            inner,
                            [*pulled, x, *inner, closer],
                            s,
                        )
                    )
                    end = closer.pos[2]
                elif x.kind == "cs" or not allow_single_token:
                    # 单 token 参数不跨 '\'（BUG1）；禁用即停
                    src.unread([*pulled, x])
                    break
                else:
                    out.append(
                        _ArgTok(
                            fid,
                            x.pos[1],
                            x.pos[2],
                            x.pos[1],
                            x.pos[2],
                            [x],
                            [*pulled, x],
                            s,
                        )
                    )
                    end = x.pos[2]
            elif s.kind in ("o", "O"):
                if x.kind == "other" and x.text == "[":
                    hit = self._collect_group(src, x, brace=False)
                    if hit is None:
                        src.unread(pulled)
                        break
                    inner, closer = hit
                    out.append(
                        _ArgTok(
                            fid,
                            x.pos[2],
                            closer.pos[1],
                            x.pos[1],
                            closer.pos[2],
                            inner,
                            [*pulled, x, *inner, closer],
                            s,
                        )
                    )
                    end = closer.pos[2]
                else:
                    src.unread([*pulled, x])
                    out.append(_ArgTok(fid, end, end, end, end, spec=s))
            elif s.kind == "s":
                if x.kind == "other" and x.text == "*":
                    out.append(
                        _ArgTok(
                            fid,
                            x.pos[1],
                            x.pos[2],
                            x.pos[1],
                            x.pos[2],
                            [x],
                            [*pulled, x],
                            s,
                        )
                    )
                    end = x.pos[2]
                else:
                    src.unread([*pulled, x])
                    out.append(_ArgTok(fid, end, end, end, end, spec=s))
            elif s.kind == "t" and s.delim:
                if x.text == s.delim[0]:
                    out.append(
                        _ArgTok(
                            fid,
                            x.pos[1],
                            x.pos[2],
                            x.pos[1],
                            x.pos[2],
                            [x],
                            [*pulled, x],
                            s,
                        )
                    )
                    end = x.pos[2]
                else:
                    src.unread([*pulled, x])
                    out.append(_ArgTok(fid, end, end, end, end, spec=s))
            elif s.kind in ("d", "D", "r", "R") and s.delim:
                op, cl = s.delim[0], s.delim[-1]
                if x.text != op:
                    src.unread([*pulled, x])
                    if s.kind in ("r", "R"):
                        break  # 定界强制缺失 → 参数不匹配，停读
                    out.append(_ArgTok(fid, end, end, end, end, spec=s))
                    continue
                dtoks = [x]
                inner = []
                closer = None
                while True:
                    y = src.read()
                    if y is None:
                        break
                    dtoks.append(y)
                    if y.text == cl:
                        closer = y
                        break
                    inner.append(y)
                if closer is None:
                    src.unread([*pulled, *dtoks])
                    break
                out.append(
                    _ArgTok(
                        fid,
                        x.pos[2],
                        closer.pos[1],
                        x.pos[1],
                        closer.pos[2],
                        inner,
                        [*pulled, *dtoks],
                        s,
                    )
                )
                end = closer.pos[2]
            elif s.kind == "e":
                # 修饰参 ``e{^_}``：逐个 token 试吃 ``X{arg}``/``X<tok>``，
                # 整段并作一个 ArgTok（F10 位序修复的 token 版）
                es = end
                src.unread([*pulled, x])  # 归一：候选判读在循环内逐轮做
                etoks: list[Tok] = []
                inner = []
                if s.delim:
                    rest = list(dict.fromkeys(s.delim))
                    while rest:
                        ip: list[Tok] = []
                        y = self._peek_nonspace(src, ip)
                        if y is None or y.kind == "cs" or y.text not in rest:
                            src.unread([*ip, *([y] if y is not None else [])])
                            break
                        etoks.extend(ip)
                        etoks.append(y)
                        inner.append(y)
                        rest.remove(y.text)
                        end = y.pos[2]
                        jp: list[Tok] = []
                        z = self._peek_nonspace(src, jp)
                        if z is not None and z.kind == "lbrace":
                            hit = self._collect_group(src, z, brace=True)
                            if hit is not None:
                                g_inner, g_close = hit
                                etoks.extend([*jp, z, *g_inner, g_close])
                                inner.extend([z, *g_inner, g_close])
                                end = g_close.pos[2]
                            else:
                                src.unread(jp)  # 组 token 已回吐
                        elif z is not None and z.kind != "cs":
                            etoks.extend(jp)
                            etoks.append(z)
                            inner.append(z)
                            end = z.pos[2]
                        else:
                            src.unread([*jp, *([z] if z is not None else [])])
                out.append(_ArgTok(fid, es, end, es, end, inner, etoks, s))
            else:
                # 'b'/无 delim 的 dDrRt/未知：不消费但占零宽位
                src.unread([*pulled, x])
                out.append(_ArgTok(fid, end, end, end, end, spec=s))
        return out, end

    # ------------------------------------------------------------ 保护调用

    def _protect_cs(  # noqa: C901, PLR0915 — *?/定界/[opt]×3/{arg}×mand 平铺即 _protect_call
        self,
        t: Tok,
        src: TokenSource,
        typ: PhType,
        *,
        mand: int = 3,
        verbatim: bool = False,
    ) -> None:
        r"""命令 + ``*?`` + ``[opt]*`` + ``{args}*`` 整段 → ``[[typ_n]]`` 进 run。

        ``mand`` = ``{...}`` 组上限（v1 ``_protect_call`` 同参）：cite/ref/
        protect 族全是单 key 签名传 1——``\cite{a}{b}`` 的 ``{b}`` 是正文
        不是参数，吞进去就永不进 chunk（audit 次要 2）。
        """
        fid, _a, b = t.pos
        end = b
        # v1 ``_protect_call``：``*``/定界符都查 ``tex[pos]`` 裸位——不 ws_skip
        x = src.read()
        if x is not None and x.kind == "other" and x.text == "*":
            end = x.pos[2]
            x = src.read()
        if verbatim and x is not None:
            # ``\url<delim>…<delim>`` 定界形（url.sty 同 \verb 规则，
            # EOL 上限——scanner-audit F11）。cs token 的定界字符 = `\`。
            d = "\\" if x.kind == "cs" else x.text
            if len(d) == 1 and not d.isalnum() and d not in " \t\n\r%{}[]":
                ftext = self.file_texts[fid]
                e = ftext.find(d, x.pos[1] + 1)
                eol = ftext.find("\n", x.pos[1] + 1)
                lim = eol if eol >= 0 else len(ftext)
                end = e + 1 if 0 <= e < lim else lim
                vspan = self._cover_to(fid, end)
                self._rappend_ph(
                    typ,
                    self._ph(typ, self.vt.slice(vspan.start, vspan.end)),
                    vspan,
                    t,
                )
                self._skip_past(src, fid, end)
                return
        if x is not None:
            src.unread([x])  # 未消费位回吐——opt/mand 走 ws_skip peek
        pulled: list[Tok] = []
        for _ in range(3):
            x = self._peek_nonspace(src, pulled)
            if x is not None and x.kind == "other" and x.text == "[":
                hit = self._collect_group(src, x, brace=False)
                if hit is not None:
                    end = hit[1].pos[2]
                    pulled.clear()
                    continue
                src.unread(pulled)  # 组 token 已回吐；ws 回放
                pulled.clear()
                break
            src.unread([*pulled, *([x] if x is not None else [])])
            pulled.clear()
            break
        for _ in range(mand):
            x = self._peek_nonspace(src, pulled)
            if x is not None and x.kind == "lbrace":
                if verbatim:
                    # url/path 逐字参：``%`` 不作注释——字节级配对 +
                    # resync；token 收集会被 ``%`` 吃掉闭括号直排 EOF
                    e = match_brace(self.file_texts[fid], x.pos[1], verbatim=True)
                    if e is None:
                        src.unread([*pulled, x])
                        pulled.clear()
                        break
                    end = e
                    pulled.clear()  # ws/lbrace 已在覆盖区间内——不回放
                    self._skip_past(src, fid, e)
                    continue
                hit = self._collect_group(src, x, brace=True)
                if hit is None:
                    src.unread(pulled)  # 组 token 已回吐
                    pulled.clear()
                    break
                end = hit[1].pos[2]
                pulled.clear()
                continue
            src.unread([*pulled, *([x] if x is not None else [])])
            pulled.clear()
            break
        vspan = self._cover_to(fid, end)
        self._rappend_ph(
            typ, self._ph(typ, self.vt.slice(vspan.start, vspan.end)), vspan, t
        )

    # ------------------------------------------------------------ 各行 handler

    def _handle_href(self, t: Tok, src: TokenSource) -> None:
        r"""``\href{url}{text}``：url→``[[HREF]]``，``{text}`` 留主流续扫。

        url 参按逐字读（``%`` 不作注释，v1 ``match_brace(verbatim=True)``
        同）——token 收集会被 ``%`` 吃掉闭括号直排 EOF。
        """
        fid, _a, _b = t.pos
        pulled: list[Tok] = []
        x = self._peek_nonspace(src, pulled)
        if x is not None and x.kind == "lbrace":
            e = match_brace(self.file_texts[fid], x.pos[1], verbatim=True)
            if e is not None:
                vpre = self._cover_to(fid, x.pos[1])  # \href + 间隙进 run
                self._rappend(
                    self.vt.slice(vpre.start, vpre.end),
                    self.vt.slice(vpre.start, vpre.end),
                    vpre,
                )
                vph = self._cover_to(fid, e)
                self._rappend_ph(
                    PhType.HREF,
                    self._ph(PhType.HREF, self.vt.slice(vph.start, vph.end)),
                    vph,
                    t,
                )
                self._skip_past(src, fid, e)
                return
            src.unread([*pulled, x])  # 未配对——全量回放重扫（v1 回 j）
            self._rappend_tok(t)
            return
        src.unread([*pulled, *([x] if x is not None else [])])
        self._rappend_tok(t)

    def _handle_input_cs(  # noqa: C901, PLR0912 — 三形平铺（{file}/import 双参/裸名）
        self, t: Tok, src: TokenSource, name: str
    ) -> None:
        r"""``\input`` 族漏网（gullet 未解析成功）：literal + ``inputs[]``。

        in_arg → ``[[CMD]]`` 进 run（v1 row10）。``{file}``/``import`` 双参/
        裸文件名三形。
        """
        fid, _a, b = t.pos
        if self.in_arg:
            self._protect_cs(t, src, PhType.CMD)
            return
        end = b
        fname = ""
        pulled: list[Tok] = []
        x = self._peek_nonspace(src, pulled)
        if x is not None and x.kind == "lbrace":
            hit = self._collect_group(src, x, brace=True)
            if hit is not None:
                _inner, closer = hit
                end = closer.pos[2]
                if name in ("import", "subimport"):
                    # v1 此处 ws_skip（全空白）非 ws_skip_arg——跨 \n\n
                    p2: list[Tok] = []
                    y = self._read_skipws(src, p2)
                    if y is not None and y.kind == "lbrace":
                        hit2 = self._collect_group(src, y, brace=True)
                        if hit2 is not None:
                            _inner2, closer2 = hit2
                            fname = self.file_texts[fid][
                                y.pos[2] : closer2.pos[1]
                            ].strip()
                            end = closer2.pos[2]
                        else:
                            src.unread(p2)  # 组 token 已回吐
                    else:
                        src.unread([*p2, *([y] if y is not None else [])])
                else:
                    fname = self.file_texts[fid][x.pos[2] : closer.pos[1]].strip()
            else:
                src.unread(pulled)  # 组已回吐；ws 回放（v1 end=j 重扫）
        elif (
            x is not None
            and x.kind in ("letter", "other")
            and all(c in FILENAME_CHARS for c in x.text)
        ):
            # 裸文件名形（\input path/to）：连吃 FILENAME_CHARS token
            fname_toks = [x]
            while True:
                y = src.read()
                if (
                    y is not None
                    and y.kind in ("letter", "other")
                    and all(c in FILENAME_CHARS for c in y.text)
                ):
                    fname_toks.append(y)
                else:
                    if y is not None:
                        src.unread([y])
                    break
            fname = "".join(t2.text for t2 in fname_toks)
            end = fname_toks[-1].pos[2]
        else:
            src.unread([*pulled, *([x] if x is not None else [])])
        vspan = self._cover_to(fid, end)
        self._flush_run(vspan.start)
        self._emit(vspan.start, vspan.end)
        if fname and "\\" not in fname:
            # 含 cs 的动态文件名（\@journal\substyle@ext）非字面路径，
            # 非输入尝试——不记 inputs[]（gullet 侧同款过滤）
            self.state.inputs.append((vspan.start, fname))

    def _handle_chunk_arg(self, t: Tok, src: TokenSource, name: str) -> None:
        r"""``\section[opt]{arg}`` token 版：前缀 LITERAL，arg → 独立 chunk。

        v1 ``_handle_chunk_arg`` 逐行移植：arg token 经 ``_args_tok`` 拉出
        （消费位入覆盖账），内容 token 喂 ``_ListSource`` 子扫——渲染串含
        ``[[X_n]]`` 自解析（ident=part 直传 ``_new_chunk``）。
        """
        fid, _a, b = t.pos
        cons0 = self._cons(fid)  # 覆盖前锚——in_arg 内联形的 gap 前缀用
        # v1：``pos = ws_skip_arg(j)`` 后先吃 ``*``（``\section*{T}``），
        # 未中回吐走 ``_args_tok`` 的 peek 重拉
        pulled: list[Tok] = []
        x = self._peek_nonspace(src, pulled)
        if x is not None and x.kind == "other" and x.text == "*":
            b = x.pos[2]
        else:
            src.unread([*pulled, *([x] if x is not None else [])])
        spec_str, tidx = CHUNK_ARG_SPEC.get(name, ("om", 1))
        spec = _chunk_spec_cached(spec_str)
        args, _end = self._args_tok(src, fid, spec, b, allow_single_token=True)
        # 可译参数：spec 位序取 tidx，越界退最后实参（零宽缺省参不算）
        real = [a for a in args if a.fe > a.fs]
        target: _ArgTok | None = None
        if tidx < len(args) and args[tidx].fe > args[tidx].fs:
            target = args[tidx]
        elif real:
            target = real[-1]
        if target is not None and self.gen >= MAX_GEN:
            self.state.warnings.append(
                ScanWarning("gen_overflow", len(self.vt), f"chunk:{name}")
            )
        if (
            target is None
            or (target.cs, target.ce) == (target.fs, target.fe)
            or self.gen >= MAX_GEN
        ):
            # 无 {..} 参数 / 单 token 参数 / 超代数 → 命令名逐字；
            # 已拉参数 token 回放主流（字节版返回 j 的等价物）
            self._unread_args(src, args)
            self._rappend_tok(t)
            return
        if not self.file_texts[fid][target.cs : target.ce].strip():
            # 空参数 → 整调用（含括号）逐字进 run
            vspan = self._cover_to(fid, target.fe)
            self._rappend(
                self.vt.slice(vspan.start, vspan.end),
                self.vt.slice(vspan.start, vspan.end),
                vspan,
            )
            return
        # 前缀覆盖到 content 起（\section[opt]{ 一段）；内文子扫共享覆盖账
        vpre = self._cover_to(fid, target.cs)
        sub = self.spawn(in_arg=True)
        sub.scan(_ListSource(list(target.toks)), self.file_texts)
        sub_end = len(self.vt)  # 子扫 pieces 平铺到此（scan 尾部兜底保证）
        self._cover_to(fid, target.ce)  # 子扫丢 token 的尾字节兜底
        vce = len(self.vt)
        rendered = "".join(p.text for p in sub.pieces)
        if sub_end < vce:
            # 已盖未挂 piece 的残余字节（子扫丢弃的尾空白 token 等）——
            # 不进 rendered 则 ph/chunk 体丢字节，identity 破（F-尾丢）
            rendered += self.vt.slice(sub_end, vce)
        # 参数内 ``%`` 注释 → ``[[COMMENT]]``（v1 机制 B）——ident 轨道保
        # 原字节（identity），content/译文面只见占位符
        rendered = _ARG_COMMENT_RX.sub(
            lambda m: (
                m.group(0)
                if m.group(0).startswith("\\")
                else self._ph(PhType.COMMENT, m.group(0))
            ),
            rendered,
        )
        vclose = self._cover_to(fid, target.fe)
        if self.in_arg:
            # 嵌套 chunk-arg 内联化：前缀+渲染+闭括号并入父 run
            text = (
                self.vt.slice(vpre.start, vpre.end)
                + rendered
                + self.vt.slice(vclose.start, vclose.end)
            )
            self._rappend(
                self._gap_surface(fid, cons0, t.pos[1]) + text,
                text,
                Span(vpre.start, vclose.end),
            )
            return
        self._flush_run(vpre.start)
        self._emit(vpre.start, vpre.end)  # \section{ 前缀
        gspan = Span(vpre.end, vce)
        refs = "".join(
            self._new_chunk(part, name, gspan, part)
            for part in self._split_rendered(rendered)
        )
        self.pieces.append(
            Piece(
                PieceKind.CHUNK_REF,
                gspan,
                refs,
                self.env_stack[-1] if self.env_stack else None,
            )
        )
        self._emit(vclose.start, vclose.end)  # } 闭括号

    @staticmethod
    def _unread_args(src: TokenSource, args: list[_ArgTok]) -> None:
        """``_args_tok`` 放弃路径：全部 ``all_toks`` 按拉取序回放。"""
        toks = [x for a in args for x in a.all_toks]
        if toks:
            src.unread(toks)

    @staticmethod
    def _split_rendered(core: str) -> list[str]:  # noqa: C901, PLR0912 — 切点优先级链，平铺即 §3.8 规则序
        """渲染串二次切分——v1 ``_split_core`` 原样（``[[X_n]]`` 边界优先）。"""
        if len(core) <= CHUNK_MAX:
            return [core]
        parts: list[str] = []
        i, n = 0, len(core)
        while i < n:
            hard = min(i + CHUNK_MAX, n)
            if hard >= n:
                parts.append(core[i:])
                break
            window = core[i:hard]
            cut = -1
            for m in PH_RX.finditer(window):  # 占位符尾是最安全切点
                cut = m.end()
            if cut <= 0:
                ws = window.rfind("\n\n")
                if ws > 0:
                    cut = ws + 2
            if cut <= 0:
                for ch in (". ", "} ", " "):
                    ws = window.rfind(ch)
                    if ws > CHUNK_MAX // 2:
                        cut = ws + len(ch)
                        break
            if cut <= 0:
                # 硬切：找横跨 hard 的 token 切到它尾后（scanner-audit F7）
                cut = hard - i
                for m in PH_RX.finditer(core, i):
                    if m.start() >= hard:
                        break
                    if m.end() > hard:
                        cut = m.end() - i
                        break
            parts.append(core[i : i + cut])
            i += cut
        return parts

    def _handle_protect_block(self, t: Tok, src: TokenSource) -> None:
        r"""``\author[opt]{..}`` 整块保护 → ``[[AUTHOR]]``（v1 row12）。"""
        fid, _a, b = t.pos
        end = b
        pulled: list[Tok] = []
        opt_toks: list[Tok] = []  # 已吃 ``[opt]``——``{`` 未中时随 abort 回放
        x = self._peek_nonspace(src, pulled)
        if x is not None and x.kind == "other" and x.text == "[":
            hit = self._collect_group(src, x, brace=False)
            if hit is not None:
                inner, closer = hit
                end = closer.pos[2]
                opt_toks = [*pulled, x, *inner, closer]
                pulled.clear()
                x = self._peek_nonspace(src, pulled)
            else:
                src.unread(pulled)  # 组已回吐
                pulled.clear()
                x = None
        if x is not None and x.kind == "lbrace":
            hit = self._collect_group(src, x, brace=True)
            if hit is not None:
                end = hit[1].pos[2]
                opt_toks = []
            else:
                src.unread(pulled)  # `{` 组已回吐；opt 段随下方回放
            pulled.clear()
            x = None
        src.unread([*opt_toks, *pulled, *([x] if x is not None else [])])
        vspan = self._cover_to(fid, end)
        body = self.vt.slice(vspan.start, vspan.end)
        if self.in_arg:
            self._rappend_ph(PhType.AUTHOR, self._ph(PhType.AUTHOR, body), vspan, t)
            return
        self._flush_run(vspan.start)
        self._emit_ph(PhType.AUTHOR, vspan.start, vspan.end, body)

    def _handle_boundary(self, t: Tok, src: TokenSource, name: str) -> None:
        r"""边界命令：flush + LITERAL（含 ``BOUNDARY_TAIL`` 结构尾参）。

        ``\item`` 置 ``force_chunk``（label ``[o]`` 不收——可译文本留 run）。
        in_arg → ``[[CMD]]`` 进 run（v1 row14）。
        """
        fid, _a, b = t.pos
        if self.in_arg:
            self._protect_cs(t, src, PhType.CMD)
            return
        end = b
        spec = BOUNDARY_TAIL.get(name)
        if spec is not None:
            args, e2 = self._args_tok(src, fid, spec, b)
            if any(a.fe > a.fs for a in args):
                end = e2
                if name in _PKG_CMDS:
                    # 无 preamble 文档（无 \begin{document}）：包声明走
                    # 字面档时同步登记 argspec 门控
                    self._note_pkgs(args)
            else:
                self._unread_args(src, args)
        vspan = self._cover_to(fid, end)
        self._flush_run(vspan.start)
        self._emit(vspan.start, vspan.end)
        if name == "item":
            self.force_chunk = True  # item 文本恒可译

    def _handle_endinput(self, t: Tok, src: TokenSource) -> None:
        r"""``\endinput`` 漏网档：顶层 flush + 本文件余下逐字 + 截停。"""
        fid, _a, _b = t.pos
        if self.in_arg:
            self._protect_cs(t, src, PhType.CMD)
            return
        vspan = self._cover_to(fid, len(self.file_texts[fid]))
        self._flush_run(vspan.start)
        self._emit(vspan.start, vspan.end)
        self._stop = True

    def _on_math_delim(self, t: Tok, src: TokenSource, closer: str) -> None:
        r"""``\[``/``\(`` 定界数学：token 拉取闭符 → ``[[MATH]]`` 进 run。"""
        fid, _a, _b = t.pos
        e = self._find_math_close_tok(src, closer)
        if e is not None:
            vspan = self._cover_to(fid, e)
            self._rappend_ph(
                PhType.MATH,
                self._ph(PhType.MATH, self.vt.slice(vspan.start, vspan.end)),
                vspan,
                t,
            )
            self._math_depth(src, 0)
            return
        self._rappend_tok(t)

    @staticmethod
    def _find_math_close_tok(src: TokenSource, closer: str) -> int | None:
        r"""``\]``/``\)`` 闭符 token 拉取：``eol_par``/EOF → 回吐放弃。

        字节版 ``_find_math_close`` 的 token 等价：注释已由 Mouth 吞掉；
        ``eol_par`` = 段界逃逸信号（假闭合不吃进 MATH）。
        """
        pulled: list[Tok] = []
        while True:
            x = src.read()
            if x is None or x.kind == "eol_par":
                if x is not None:
                    pulled.append(x)
                src.unread(pulled)
                return None
            pulled.append(x)
            if x.kind == "cs" and x.text == closer:
                return x.pos[2]

    def _handle_cond(
        self, t: Tok, src: TokenSource, name: str, m: object | None
    ) -> None:
        r"""``\if`` 两档界标（v1 ``_handle_cond`` token 版，§8.6）。

        可求值 ``\if`` 已被 gullet ``process_if`` 消费成 ``if:``/``fi:``
        marker 夹心，不到此。到此者：

        - ``if*`` MacroDef（``\ifAnonymous{T}{F}`` 双参调用形）→ 整调用
          ``[[COND]]``（in_arg）/``[[CMD]]`` 保护（v1 ``_protect_call``——
          透明分流会把命令名放进 run surface → conditional 泄漏）；
        - 不可求值 ``\ifX``（``\ifx`` 宏比较/未知 if*/溢界 IfCond）→
          条件段已被 gullet 按语法吃掉（字节成 gap），界标 LITERAL 盖
          ``\ifX`` + 条件区（``read()`` 窥下一 raw token 取起点后回吐）；
          **双支自流**——``\else``/``\fi`` 各自再到此出 LITERAL 界标，
          与 v1 收集+回放的逐 piece 序列等价（嵌套免计深、verb 体假
          ``\fi`` 由 verb 处理器 ``skip_past`` 天然挡）；
        - 裸 ``\else/\or/\fi`` 散件 / ``\Xtrue``/``\Xfalse``（IfSetter，
          旗标 gullet 已写）→ flush + LITERAL 盖本体；
        - in_arg 一律 ``[[COND]]`` 进 run（``if*`` 同窥位盖条件区）。
        """
        if isinstance(m, MacroDef):
            self._protect_cs(t, src, PhType.COND if self.in_arg else PhType.CMD)
            return
        fid, _a, b = t.pos
        end = b
        if name.startswith("if"):
            nxt = src.read()
            if nxt is not None:
                src.unread([nxt])
                # 条件区 = [b, nxt.start)：gen>0/跨 fid 窥物不算（非本段字节）
                if nxt.gen == 0 and nxt.pos[0] == fid:
                    end = nxt.pos[1]
        if self.in_arg:
            vspan = self._cover_to(fid, end)
            self._rappend_ph(
                PhType.COND,
                self._ph(PhType.COND, self.vt.slice(vspan.start, vspan.end)),
                vspan,
                t,
            )
            return
        self._flush_run(len(self.vt))
        vspan = self._cover_to(fid, end)
        self._emit(vspan.start, vspan.end)

    def _handle_opaque_macro(self, t: Tok, src: TokenSource, m: object) -> None:
        r"""Opaque 宏（gullet 判定体无文本不展开）：按 spec 读参 → ``[[MACRO]]``。

        gullet ``Arg`` → ``ArgSpec`` 映射：``m``→m、``o``→o、``star``→s、
        ``e``→e（delim toks → 字符表），其余（delim/until_group 等）→ 零宽占位。
        """
        fid, _a, b = t.pos
        gspec = [
            ArgSpec("m")
            if a.kind == "m"
            else ArgSpec("o")
            if a.kind == "o"
            else ArgSpec("s")
            if a.kind == "star"
            else ArgSpec("e", delim="".join(x.text for x in a.delim))
            if a.kind == "e"
            else ArgSpec("b")
            for a in getattr(m, "spec", [])
        ]
        _args, end = self._args_tok(src, fid, gspec, b, allow_single_token=True)
        vspan = self._cover_to(fid, end)
        self._rappend_ph(
            PhType.MACRO,
            self._ph(PhType.MACRO, self.vt.slice(vspan.start, vspan.end)),
            vspan,
            t,
        )

    def _handle_unknown_cs(
        self, t: Tok, src: TokenSource, name: str = "", m: object | None = None
    ) -> None:
        r"""未知命令（v1 row19）：argspec 表兜底 + ``{``/``[`` 探针。

        宏表未命中（``m is None``）先查 ``argspec_lookup``——已加载包
        的签名驱动 policy 分派；表外维持探针：参数命中 → ``[[CMD]]``
        进 run，否则逐字。``allow_single_token=False``（泄漏机制 A：
        禁单 token 参——``\foo x`` 的 ``x`` 是正文）；参数搜索不跨
        ``eol_par``。
        """
        fid, _a, b = t.pos
        if m is None:
            e = argspec_lookup(name or t.text, self.state.pkgs)
            if e is not None:
                self._handle_argspec_cs(t, src, e)
                return
        args, end = self._args_tok(
            src, fid, 6, b, has_opt=True, allow_single_token=False
        )
        if any(a.fe > a.fs for a in args):
            vspan = self._cover_to(fid, end)
            self._rappend_ph(
                PhType.CMD,
                self._ph(PhType.CMD, self.vt.slice(vspan.start, vspan.end)),
                vspan,
                t,
            )
            return
        self._unread_args(src, args)
        self._rappend_tok(t)

    def _handle_argspec_cs(  # noqa: PLR0911 — policy 分派早退平铺，顺序即语义
        self, t: Tok, src: TokenSource, e: ArgspecEntry
    ) -> None:
        r"""Argspec 表命中分派：policy → literal/boundary/protect/chunk-arg。

        签名即权威（与探针不同：参数读 ``e.signature`` 位序，角色表
        ``e.arg_roles`` 对齐）。``literal``/``transparent`` 名进 run
        参数随主流；``boundary`` flush+LITERAL；``protect``/``key``/
        ``verbatim``（+in_arg 的 boundary）整调用 ``[[CMD]]``；
        ``chunk-arg`` 走 :meth:`_emit_argspec_chunks`。

        ``transparent``/``boundary`` 当前全条目被同名族表先截获——此路
        不可达；到达即表/族漂移，记 ``argspec_shadowed`` 告警但语义照旧。
        """
        fid, _a, b = t.pos
        if e.policy == "verbatim":
            # verbatim policy：逐字读参（ctan-argspec 定界式约定）——``%``/``#``
            # 等在参数里是字面（``\hyperbaseurl{..%20..}``），走 ``\url``/``\path``
            # 同款字节级配对；token 流会被 ``%`` 吃掉闭括号直排 EOF。
            spec = _chunk_spec_cached(e.signature)
            mand = sum(s.kind in ("m", "v") for s in spec)
            self._protect_cs(t, src, PhType.CMD, mand=mand, verbatim=True)
            return
        if e.policy == "literal":
            self._rappend_tok(t)
            return
        if e.policy in ("transparent", "boundary"):
            self.state.warnings.append(
                ScanWarning("argspec_shadowed", len(self.vt), e.name)
            )
            if e.policy == "transparent":
                self._rappend_tok(t)
                return
        spec = _chunk_spec_cached(e.signature)
        args, end = self._args_tok(src, fid, spec, b, allow_single_token=True)
        if e.policy == "chunk-arg":
            self._emit_argspec_chunks(t, src, e, args, end, b)
            return
        if not any(a.fe > a.fs for a in args):
            self._unread_args(src, args)
            if e.policy == "boundary" and not self.in_arg:
                vspan = self._cover_to(fid, b)
                self._flush_run(vspan.start)
                self._emit(vspan.start, vspan.end)
                return
            if e.policy in ("protect", "key", "verbatim"):
                # 签名零参/参数缺席但本体仍要保护（\printindex 类）——
                # 裸名进 run 会被译文面当真词处理
                vspan = self._cover_to(fid, b)
                self._rappend_ph(
                    PhType.CMD,
                    self._ph(PhType.CMD, self.vt.slice(vspan.start, vspan.end)),
                    vspan,
                    t,
                )
                return
            self._rappend_tok(t)
            return
        vspan = self._cover_to(fid, end)
        if e.policy == "boundary" and not self.in_arg:
            self._flush_run(vspan.start)
            self._emit(vspan.start, vspan.end)
            return
        self._rappend_ph(
            PhType.CMD,
            self._ph(PhType.CMD, self.vt.slice(vspan.start, vspan.end)),
            vspan,
            t,
        )

    def _emit_argspec_chunks(  # noqa: C901, PLR0912, PLR0913, PLR0915, PLR0917 — 参序 literal/chunk 交替平铺即 _handle_chunk_arg 多参推广
        self,
        t: Tok,
        src: TokenSource,
        e: ArgspecEntry,
        args: list[_ArgTok],
        end: int,
        b: int,
    ) -> None:
        r"""chunk-arg policy：``text``/``opt-text`` 角色参 → 独立 chunk。

        ``_handle_chunk_arg`` 的推广：consumed 参按位序「字面段（含
        括号与非文本参）→ 子扫渲染 → CHUNK_REF」交替发射；单 token
        文本参起截停回吐主流（泄漏机制 A 同判）。无文本参但有消费
        → 整调用 ``[[CMD]]``；零消费 → 名进 run。
        """
        fid = t.pos[0]
        cons0 = self._cons(fid)
        consumed = [a for a in args if a.fe > a.fs]
        cut = len(args)
        for k, a in enumerate(args):
            if a.fe <= a.fs:
                continue
            role = e.arg_roles[k] if k < len(e.arg_roles) else "skip"
            if role in ("text", "opt-text") and (a.cs, a.ce) == (a.fs, a.fe):
                cut = k
                break
        if cut < len(args):
            self._unread_args(src, args[cut:])
            consumed = [a for a in args[:cut] if a.fe > a.fs]
            end = consumed[-1].fe if consumed else b
        if not consumed:
            self._rappend_tok(t)
            return
        text_k = {
            k
            for k, a in enumerate(args[:cut])
            if a.fe > a.fs
            and (e.arg_roles[k] if k < len(e.arg_roles) else "skip")
            in ("text", "opt-text")
        }
        if text_k and self.gen >= MAX_GEN:
            self.state.warnings.append(
                ScanWarning("gen_overflow", len(self.vt), f"chunk:{e.name}")
            )
            text_k = set()
        if not text_k:
            vspan = self._cover_to(fid, end)
            self._rappend_ph(
                PhType.CMD,
                self._ph(PhType.CMD, self.vt.slice(vspan.start, vspan.end)),
                vspan,
                t,
            )
            return
        # 参序 op 列：("lit", end) 覆盖到 end；("arg", _ArgTok) 子扫文本参。
        # 非文本参/括号字节随相邻 lit 段覆盖——首 op 恒为 lit（text_k 非空）。
        ops: list[tuple[str, int | _ArgTok]] = []
        for k, a in enumerate(args[:cut]):
            if a.fe <= a.fs:
                continue
            if k in text_k and self.file_texts[fid][a.cs : a.ce].strip():
                ops.append(("lit", a.cs))
                ops.append(("arg", a))
            # else：参数字节并入下一段 lit 覆盖
        ops.append(("lit", end))
        if self.in_arg:
            texts: list[str] = []
            vstart = -1
            for op, x in ops:
                if op == "lit":
                    v = self._cover_to(fid, int(x))
                    if vstart < 0:
                        vstart = v.start
                    texts.append(self.vt.slice(v.start, v.end))
                    continue
                texts.append(self._subscan_render(x))
            text = "".join(texts)
            if vstart >= 0:
                self._rappend(
                    self._gap_surface(fid, cons0, t.pos[1]) + text,
                    text,
                    Span(vstart, len(self.vt)),
                )
            return
        v0 = self._cover_to(fid, int(ops[0][1]))
        self._flush_run(v0.start)
        self._emit(v0.start, v0.end)
        cur_v = v0.end
        for op, x in ops[1:]:
            if op == "lit":
                v = self._cover_to(fid, int(x))
                self._emit(v.start, v.end)
                cur_v = v.end
                continue
            rendered = self._subscan_render(x)
            gspan = Span(cur_v, len(self.vt))
            refs = "".join(
                self._new_chunk(part, e.name, gspan, part)
                for part in self._split_rendered(rendered)
            )
            self.pieces.append(
                Piece(
                    PieceKind.CHUNK_REF,
                    gspan,
                    refs,
                    self.env_stack[-1] if self.env_stack else None,
                )
            )
            cur_v = gspan.end

    def _subscan_render(self, a: _ArgTok) -> str:
        r"""文本参内容 token → in_arg 子扫渲染串（含尾字节兜底 + 注释 ph）。

        ``_handle_chunk_arg`` 的子扫段抽出：覆盖经共享 vt/cons 直落父
        区间（``a.cs`` 前的字面段由调用方先盖），``a.ce`` 内残余字节
        补盖进渲染串（F-尾丢同款）。
        """
        fid = a.fid
        sub = self.spawn(in_arg=True)
        sub.scan(_ListSource(list(a.toks)), self.file_texts)
        sub_end = len(self.vt)
        self._cover_to(fid, a.ce)
        rendered = "".join(p.text for p in sub.pieces)
        if sub_end < len(self.vt):
            rendered += self.vt.slice(sub_end, len(self.vt))
        return self._arg_comment_ph(rendered)

    def _arg_comment_ph(self, rendered: str) -> str:
        r"""渲染串内裸 ``%`` 注释 → ``[[COMMENT]]``（机制 B 同款）。"""
        return _ARG_COMMENT_RX.sub(
            lambda m: (
                m.group(0)
                if m.group(0).startswith("\\")
                else self._ph(PhType.COMMENT, m.group(0))
            ),
            rendered,
        )


_CHUNK_SPEC_CACHE: dict[str, list[ArgSpec]] = {}


def _chunk_spec_cached(spec_str: str) -> list[ArgSpec]:
    """``CHUNK_ARG_SPEC`` 签名串 → ``list[ArgSpec]``（解析一次缓存）。"""
    if spec_str not in _CHUNK_SPEC_CACHE:
        _CHUNK_SPEC_CACHE[spec_str] = parse_argspec(spec_str)
    return _CHUNK_SPEC_CACHE[spec_str]


_PREAMBLE_RX = re.compile(r"\\(documentclass|documentstyle)(?![a-zA-Z])")
_DOC_BEGIN_RX = re.compile(r"\\begin\s*\{document\}")


def _doc_begin_of(tex0: str) -> int:
    r"""fid-0 ``\\begin{document}`` 的 ``\\begin`` 起点（v1 mask 视图双门同规则）。"""
    masked = mask_tex(tex0)
    mdoc = _DOC_BEGIN_RX.search(masked)
    mpream = _PREAMBLE_RX.search(masked)
    return mdoc.start() if (mpream and mdoc) else -1


def scan_v2(g: Gullet) -> ScanResult:
    r"""v2 产品核：消费 ``g`` 的展开流 → ``ScanResult``。

    ``res.macros`` = gullet scope 链（平表 MacroTable 退役）；
    ``res.inputs`` = (vpos, path) 输入事件流（解析成功 = 绝对路径，
    漏网 = 原始文件名——``missing_input`` warning 同步登记）；
    ``gullet.warnings`` 尾并入（pos 已 fid 化前缀）。
    """
    state = ScanState(
        issuer=PlaceholderIssuer(),
        ph_map={},
        chunks=[],
        macros=g.macros,
        inputs=[],
        warnings=[],
    )
    if g.file_texts:
        # 源文自带 [[X_n]] 形字面 → 签发避让（v1 parse_tex 同检）
        reserved = PH_RX.findall(g.file_texts[0])
        if reserved:
            state.ph_reserved.update(reserved)
            state.warnings.append(
                ScanWarning("ph_collision", 0, f"{len(reserved)} 处 [[X_n]] 形字面")
            )
    seg = Segmenter(state)
    seg.scan(
        g,
        g.file_texts,
        doc_begin=_doc_begin_of(g.file_texts[0]) if g.file_texts else -1,
    )
    return ScanResult(
        protected_tex="".join(p.text for p in seg.pieces),
        chunks=state.chunks,
        ph_map=state.ph_map,
        macros=state.macros,
        pieces=seg.pieces,
        inputs=state.inputs,
        warnings=[*state.warnings, *g.warnings],
        vtex=seg.vt.text(),
    )


def parse_tex_v2(tex: str) -> ScanResult:
    r"""``parse_tex`` 的 token 流版：内存源 Gullet。

    无路径无 root——``\\input`` 恒不解析。产品文件入口是
    ``api.parse_file``。
    """
    return scan_v2(Gullet(tex))
