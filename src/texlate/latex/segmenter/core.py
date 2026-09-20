r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。"""

from __future__ import annotations

from bisect import (
    bisect_left,
    bisect_right,
)
from typing import TYPE_CHECKING

from texlate.latex.model import (
    Chunk,
    PhType,
    Piece,
    PieceKind,
    ScanState,
    ScanWarning,
    Span,
)
from texlate.latex.placeholder import (
    PH_RX,
)
from texlate.latex.tables import (
    CHUNK_MAX,
    CHUNK_MIN,
)

from texlate.textutil import (
    needs_seam_space,
)
from ._common import (
    _CLEAN_CMD_RX,
    _CLEAN_NONALPHA_RX,
    _COMMENT_GAP_RX,
    _LEAD_WS_RX,
    _TRAIL_WS_RX,
    TokenSource,
    _EnvDeadTok,
    _pick_cut,
    _RunItem,
    _Vtex,
)

if TYPE_CHECKING:
    from texlate.latex.mouth import (
        Tok,
    )
    from texlate.latex.segmenter import Segmenter

r"""``Segmenter`` 状态与账本核——覆盖/run/piece/flush/展开组。"""


class _Core:
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
        self.force_chunk = False
        self._run: list[_RunItem] = []
        self._run_start: int | None = None  # run 首个覆盖的 vtex 位
        self._run_has_expand = False
        self._open_origin: tuple[int, int, int] | None = None  # 展开组调用区间
        self._open_vspan: Span | None = None  # 该组在 vtex 的落位
        self._open_toks: list[Tok] = []  # 组成员 token（surface 收组时产）
        self._open_side_effect = False  # 组内展开执行过副作用（def 族/let/…）
        self._run_pending: dict[str, str] = {}  # 组内 surface ph（chunk 化才入 ph_map）
        self._stop = False  # \end{document}/\endinput 顶层截停
        self._env_dead: dict[str, _EnvDeadTok] = {}  # F12 未闭合 env 墓标
        self._doc_begin = -1  # fid-0 上 \begin{document} 的 \begin 起点（-1=无）
        self._doc_opened = False  # \begin{document} 已过（任意 fid——防 preamble 重入）
        self._preamble = False  # preamble 档：token 照过 gullet、分段全 literal
        self._ph_scan_n = 0  # file_texts 已采样 [[X_n]] 字面保留集的前缀长
        self._run_brace = 0  # 当前 run 内 dispatch 级 {−} 深度（孤 } 判据）

    def spawn(
        self, *, in_arg: bool | None = None, mined: bool | None = None
    ) -> Segmenter:
        """子分段器：共享 state/vt/cons/file_texts，env_stack 拷贝，gen+1。

        覆盖账本共享 = 子扫覆盖直落父 vtex 区间（连续无断）；``pieces``
        独立——子产出经 ``join(p.text)`` 渲染串回父层消费，不与父
        pieces 平铺（v1 ``spawn`` 同构，契约 §6 in_arg 子扫）。
        """
        sub = type(self)(
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
        ``cons0`` = 覆盖前锚：调用方在 ``_cover_to`` 前先取
        ``self._cons(fid)`` 快照再盖（pre-cover 唯一形态——post-cover
        锚账本已随间隙剖分改版移除，见 ``_cover_gap``）。
        """
        if cons0 < 0 or tok_start <= cons0:
            return ""
        gap = _COMMENT_GAP_RX.sub("", self.file_texts[fid][cons0:tok_start])
        return " " if gap and not gap.strip() else ""

    def _cover_gap(self, fid: int, tok_start: int) -> None:
        r"""调用点前间隙字节 → 独立字面 run 项（cover + 挂项一步）。

        保护段/调用点的 cover 一律先过此闸：``\\ie \\cite{a}`` 的被吞空格、
        ``%`` 注释这类非 token 字节不再并入 ph 体——surface 取
        ``_gap_surface`` 渲染形（``" "``/``""``）、ident 持原字节。不剖
        则该空格只上 surface 轨：in_arg/mined 子扫渲染走 ident 轨会丢
        （v1 渲染面有空格——``\\section{A\\foo \\cite{x}}`` 曾渲成
        ``A\\foo[[CITE_1]]``，v1 为 ``A\\foo [[CITE_1]]``）。
        """
        cons0 = self._cons(fid)
        if tok_start <= cons0:
            return
        gap, text = self._cover_text(fid, tok_start)
        self._rappend(self._gap_surface(fid, cons0, tok_start), text, gap)

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
            and needs_seam_space(body, self.file_texts[cut[0]][cut[1]])
        ):
            self.state.warnings.append(
                ScanWarning("letters_cut", len(self.vt), body[-40:])
            )
        return self.state.issuer.new(
            typ, body, self.state.ph_map, self.state.ph_reserved
        )

    def _rappend_ph(self, ph: str, vspan: Span) -> None:
        r"""Ph 项进 run（surface=ident=占位符）。

        调用点前的间隙字节由调用方 ``_cover_gap`` 先剖成独立字面项——
        此处 vspan 头即构造首字节，ph 体与 v1 逐字节一致。
        """
        if not ph:
            return  # 空 body（零宽回放）——无项可挂
        self._rappend(ph, ph, vspan)

    def _rappend(self, surface: str, ident: str, vspan: Span) -> None:
        r"""追加 run 项（surface/ident 双轨 + 覆盖位）。

        项界接缝守卫（``_cat_surf``/``seg_join`` 同族——run 项边是它俩
        都够不着的残留面）：前项尾落 ``\letters`` 控制词形且本项以字母
        起头 → 补 ``" "``。csname 合成/乱序 token 的 ``\w after`` 形中
        ``\w`` 与 ``after`` 分属两项、gap 字节 ``\w `` 被前项 cover 代记
        （``_gap_surface`` 对非全白 gap 只产 ``""``），不补则 surface
        熔成 ``\endtabularafter`` 假 cs。ident 侧同判——两条轨都按
        「``\letters`` 尾 + 字母头」各自补位。
        """
        if self._run:
            prev = self._run[-1]
            if needs_seam_space(prev.surface, surface):
                surface = " " + surface
            if needs_seam_space(prev.ident, ident):
                ident = " " + ident
        if self._run_start is None:
            self._run_start = vspan.start
        self._run.append(_RunItem(surface, ident, vspan.start, vspan.end))

    def _rappend_tok(self, t: Tok) -> None:
        r"""gen=0 文本 token：覆盖 gap+本体；surface=渲染形，ident=vtex 切片。

        新 run 首项的前间隙（``\cs`` 吞空格/``%`` 注释）剖成独立 LITERAL
        piece——折进首项 surface 会留前导空格进 chunk，下游译文去首尾
        空白后命令名与文本粘连（``\item FSU``→``\itemFSU``，real-LLM
        5 格实证；``\par%note\ni)`` 的注释间隙同形）。
        """
        fid, _a, b = t.pos
        cons0 = self._cons(fid)
        if self._run_start is None and t.pos[1] > cons0:
            vgap = self._cover_to(fid, t.pos[1])
            self._emit(vgap.start, vgap.end)
            vspan, ident = self._cover_text(fid, b)
            self._rappend(self._tok_surface(t), ident, vspan)
            return
        vspan, ident = self._cover_text(fid, b)
        self._rappend(
            self._gap_surface(fid, cons0, t.pos[1]) + self._tok_surface(t),
            ident,
            vspan,
        )

    def _rappend_text_run(self, fid: int, a: int, end: int) -> None:
        r"""连续文本 run ``[a,end)`` 一次合并进 run——``_rappend_tok`` 的批量形。

        surface=ident=原字节切片：run 集内 catcode 恒产「surface=原字符」
        token、内部夹心空格的原字节恒为 ``" "``（space token surface 同值），
        逐 token 拼接与本切片逐字节相等。分派侧保证 run 首/尾非 ws——
        ``_slice_items`` 的 lead/trail strip 是 surface 坐标系，切不进
        item 内部，ws 进首/尾会漏 strip（proto 实测 protected_tex −1 字符）。
        """
        cons0 = self._cons(fid)
        if self._run_start is None and a > cons0:
            vgap = self._cover_to(fid, a)
            self._emit(vgap.start, vgap.end)
            vspan, ident = self._cover_text(fid, end)
            self._rappend(self.file_texts[fid][a:end], ident, vspan)
            return
        vspan, ident = self._cover_text(fid, end)
        self._rappend(
            self._gap_surface(fid, cons0, a) + self.file_texts[fid][a:end],
            ident,
            vspan,
        )

    def _protect_span(
        self,
        typ: PhType,
        fid: int,
        tok_start: int,
        end: int,
        *,
        src: TokenSource | None = None,
    ) -> Span:
        r"""「盖间隙 → 盖到 ``end`` → ph 进 run」三连合写（~30 手抄点的共用缝）。

        ``_cover_gap`` 对连续区间自 no-op——无间隙调用点（prose 循环内
        ``_cover_to`` 直起者）同形直调；ph 体经 ``_cover_text`` 顺路带回，
        省 ``vt.slice`` 反查。``src`` 非空时尾接 ``skip_past`` resync——
        ``\\verb``/verbatim 定界体等 raw 消费段剔除 token 残骸，其 ``end``
        恒与覆盖尾同位。返回 ``vspan``——``\\end``/unpaired-dollar 等调用点
        复用 ``vspan.start`` 作 ``_env_pop``/告警/``_emit`` 锚位。
        """
        self._cover_gap(fid, tok_start)
        vspan, body = self._cover_text(fid, end)
        self._rappend_ph(self._ph(typ, body), vspan)
        if src is not None:
            src.skip_past(fid, end)
        return vspan

    def _cover_ph(
        self, fid: int, end: int, typ: PhType, gap: Tok | None = None
    ) -> Span:
        r"""「盖间隙 → 盖到 ``end`` → ph 进 run」三连合写（run 侧 ph 发射缝）。

        ``gap`` 非空 = 调用点前 ``_cover_gap`` 先剖间隙字面项（``_protect_span``
        同型直委）；prose 循环等 ``_cover_to`` 直起位无前隙可剖，传 ``None``
        跳过剖分——ph 体经 ``_cover_text`` 顺路带回，省 ``vt.slice`` 反查。
        返回 ``vspan``——``_skip_past``/``_emit`` 等锚位复用。
        """
        if gap is not None:
            return self._protect_span(typ, fid, gap.pos[1], end)
        vspan, body = self._cover_text(fid, end)
        self._rappend_ph(self._ph(typ, body), vspan)
        return vspan

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

    def _preamble_lit_flush(self) -> None:
        """已盖未发的前缀 → 一条 LITERAL 密铺。

        preamble 档 ``_cover_to`` 只记账不发 piece——档内首次 emit 前必须
        先把覆盖前沿补一条 literal，否则 piece 平铺从中段起头、前缀静默丢。
        """
        start = self.pieces[-1].span.end if self.pieces else 0
        if len(self.vt) > start:
            self._emit(start, len(self.vt))

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
        """登记 chunk 返回 ``[[CHUNK_id]]``；``ident≠content`` 时入 ph_map。

        源文自带 ``[[CHUNK_n]]`` 形字面时补死位跳号——``chunks[id]`` 索引
        对齐约束下只能塞空 chunk（碰撞本身已由 ``ph_collision`` 报告）。
        """
        cid = len(self.state.chunks)
        while f"[[CHUNK_{cid}]]" in self.state.ph_reserved:
            # 死位 content = token 自身：expand 环防护把它展开回字面 → 撞号
            # 字面在 chunk 内容里也逐字还原（identity 不破）
            self.state.chunks.append(
                Chunk(
                    id=cid,
                    content=f"[[CHUNK_{cid}]]",
                    span=Span(gspan.start, gspan.start),
                )
            )
            cid += 1
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

    def _warn_expand_tail_drop(self, items: list[_RunItem]) -> None:
        r"""Literal 冲刷丢空 ident 项非白 surface → ``expand_tail_dropped`` 留痕。

        空 ident 项（组内 ``eol_par`` 尾段等）的 surface 在 literal 路径
        整段蒸发——调用点字节由 EXPAND ident 兜底可编译，但译文面不可见。
        此静默曾是 ``\\@iiiparbox`` runaway 族放大器；Option D 已让整组
        同 run 同沉浮，残留只在整组合体 sub-``CHUNK_MIN`` 时触发。
        """
        for it in items:
            if not it.ident and it.surface.strip():
                self.state.warnings.append(
                    ScanWarning(
                        "expand_tail_dropped", it.vstart, it.surface.strip()[:60]
                    )
                )
                return

    def _flush_run(self, end_pos: int) -> None:
        """Run → chunk piece / literal piece（§3.8 + 双轨 identity）。"""
        items = self._run
        self._run = []
        rs = self._run_start
        self._run_start = None
        has_expand = self._run_has_expand
        self._run_has_expand = False
        self._run_brace = 0
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
            self._warn_expand_tail_drop(items)
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
        context = (
            "item"
            if force
            else "abstract"
            if self.env_stack and self.env_stack[-1] == "abstract"
            else "para"
        )
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
    def _split_bounds(
        s: str, bounds: list[int], lo: int, hi: int
    ) -> list[tuple[int, int]]:
        """``s[lo:hi]`` 超大二次切分——返回 surface 区间列，切点 snap 项界。

        切点落在项 ``k`` 内部时该项整体归前段（取 vend=bounds[k+1]）——
        展开组/ph token 永不腰斩（契约 §2）。``bounds`` = surface 前缀和。
        切点优先级链本体在 ``_pick_cut``（与 ``_split_rendered`` 共用）。
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
            g = i + _pick_cut(s, i, hard)
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
        self._cover_gap(fid, a)  # 调用点前间隙 → 字面 run 项（不进 EXPAND 体）
        vspan = self._cover_to(fid, b)
        self._open_origin = (fid, a, b)
        self._open_vspan = vspan
        self._open_toks = []
        self._open_side_effect = False

    def _close_group(self) -> None:
        """收组：surface 进 run 一项，ident = ``[[EXPAND_n]]``（体=调用切片）。

        注意 ``Span.__len__`` = 区间长——零宽 span 为 falsy，判空必须用
        ``is None``（``or`` 会把 ``Span(x,x)`` 落成 ``Span(0,0)``）。
        ``_group_surface`` 返回 ``None`` 与 ``_open_side_effect`` 同走
        literal 兜底（surface 再生不出等价语义的两种情况）。
        """
        if self._open_origin is None or self._open_vspan is None:
            return
        vspan = self._open_vspan
        segs = self._group_surface() if not self._open_side_effect else None
        if segs is None:
            # 组内展开执行过副作用（def 族/let/catcode/newif…——consumed
            # marker 不回放），或组内 ``\begin``{保护族 env} 无配对
            # ``\end``（R7/J3——surface 物质化一个永无配对的开 tag 比
            # 原样回字面更糟）：surface 骨架再生不出等价语义，整组回
            # literal——顶层 _on_consumed 同款 "def 串不落 chunk"。
            self._flush_run(vspan.start)
            self._emit(vspan.start, vspan.end)
            self._open_origin = None
            self._open_vspan = None
            self._open_toks = []
            self._open_side_effect = False
            return
        # 零宽 vspan = callsite 已盖（\end{tabular}→\@checkend 之类内层展开）——
        # 体恒空、identity 无需占位；签发只会零宽 run literal 冲刷时被
        # ``_emit_text`` 连 piece 带 token 丢掉 → dead_ph
        ph = (
            self._ph(PhType.EXPAND, self.vt.slice(vspan.start, vspan.end))
            if vspan.end > vspan.start
            else ""
        )
        self._rappend(segs[0], ph, vspan)
        self._run_has_expand = True
        for seg in segs[1:]:
            # eol_par 段界 → 同 run 内 ``\n\n`` 段落分隔（全或无发射）：
            # 逐段冲刷把空 ident 尾段挂下一 run，literal 路径只渲 ident
            # → ``}``/``\end{env}`` 等结构字节静默蒸发（9910403 族）。
            # ident 空串——调用点字节已由 EXPAND 项计过（§3）。
            if seg:
                self._rappend("\n\n" + seg, "", Span(vspan.end, vspan.end))
        self._open_origin = None
        self._open_vspan = None
        self._open_toks = []

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
