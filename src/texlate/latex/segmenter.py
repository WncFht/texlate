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

S1 范围：主循环 + 覆盖账本 + run 双轨 + math/env/verbatim/verb/cite-ref
保护子集 + boundary 粗分派 + scope/math_depth 回报。``\if`` 界标档、
argspec 细分、math-debt、F12 墓标移植在 S2+。
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from texlate.latex.gullet import Gullet
from texlate.latex.macro_table import MacroTable
from texlate.latex.model import (
    Chunk,
    PhType,
    Piece,
    PieceKind,
    ScanResult,
    ScanState,
    ScanWarning,
    Span,
    unescaped_dollar_odd,
)
from texlate.latex.placeholder import PH_RX, PlaceholderIssuer
from texlate.latex.tables import (
    BOUNDARY_NAMES,
    CHUNK_MAX,
    CHUNK_MIN,
    CITE_NAMES,
    FONT_SWITCHES,
    INLINE_LITERAL_CMDS,
    MATH_ENVS,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    PROTECTED_ENVS,
    REF_NAMES,
    VERBATIM_ENVS,
)

if TYPE_CHECKING:
    from texlate.latex.mouth import Tok

_CLEAN_CMD_RX = re.compile(r"\\[a-zA-Z@]+\*?")
_CLEAN_NONALPHA_RX = re.compile(r"[^a-zA-Z]+")
_LEAD_WS_RX = re.compile(r"\s*")
_TRAIL_WS_RX = re.compile(r"\s*$")
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


class _ListSource:
    """in_arg 子扫的 token 列表源（token 已展开，read==next_expanded）。"""

    def __init__(self, toks: list[Tok]) -> None:
        """持有待发 token 队列。"""
        self._q = list(toks)

    def next_expanded(self) -> Tok | None:
        """队首出队。"""
        return self._q.pop(0) if self._q else None

    def read(self) -> Tok | None:
        """同 next_expanded（子扫内不再有展开副作用）。"""
        return self.next_expanded()

    def unread(self, toks: list[Tok]) -> None:
        """回插队首（保序）。"""
        self._q[:0] = toks


# ------------------------------------------------------------------ segmenter


@dataclass(slots=True)
class _RunItem:
    """run 双轨项：surface 进译文面，ident 进 identity 面。"""

    surface: str
    ident: str
    vstart: int  # 本项覆盖的 vtex 区间起点（ph 项 = token 落位）
    vend: int


class Segmenter:
    r"""token 流 → pieces/chunks。单遍正向、绝不抛异常（铁律 1）。"""

    def __init__(self, state: ScanState, *, in_arg: bool = False) -> None:
        """共享 ``state``；``in_arg`` 子扫 = run 全 literal、只挖 chunk-arg。"""
        self.state = state
        self.in_arg = in_arg
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
        self._open_surface: list[str] = []

    # ------------------------------------------------------------ 覆盖账本

    def _cons(self, fid: int) -> int:
        """文件 fid 的消费前沿。"""
        return self.cons.get(fid, 0)

    def _cover_to(self, fid: int, end: int) -> Span:
        """``file_texts[fid][cons:end]`` 记入 vtex，返回其 vtex 区间。"""
        a = self._cons(fid)
        if end <= a:
            # 已覆盖（回放/乱序）——零宽，锚在当前 vtex 末（不是文件位 a！）
            return Span(len(self.vt), len(self.vt))
        sp = self.vt.cover(self.file_texts[fid][a:end])
        self.cons[fid] = end
        return sp

    # ------------------------------------------------------------ run 双轨

    def _ph(self, typ: PhType, body: str, cut: tuple[int, int] | None = None) -> str:
        r"""签发占位符（body → ph_map，避开 ``ph_reserved`` 碰撞）。

        ``cut`` = 体尾源位 ``(fid, pos)``：体以 ``\\letters`` 收尾且源串
        后继仍是字母 → ``letters_cut`` 信号（§11 断言的 token 版）。
        """
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

    def _rappend_ph(self, typ: PhType, ph: str, vspan: Span) -> None:
        """Ph 项进 run（math-debt 记账：体含奇数 ``$`` 压栈）。"""
        if self._run_start is None:
            self._run_start = vspan.start
        self._run.append(_RunItem(ph, ph, vspan.start, vspan.end))
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
        vspan = self._cover_to(fid, b)
        self._rappend(
            self._tok_surface(t), self.vt.slice(vspan.start, vspan.end), vspan
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
        if rs is None or not items:
            return
        s = "".join(it.surface for it in items)
        ident = "".join(it.ident for it in items)
        re_ = end_pos
        if not s.strip() or self.in_arg:
            self._emit_text(rs, re_, self._lit_text(items, ident, re_))
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
            return
        if has_expand:
            # 含展开组的 run 跳过 lead/trail 剥离——整 run 进 content（§2）
            lead, hi = 0, len(s)
        core_vs = self._vpos_at(items, lead, "start")
        core_ve = self._vpos_at(items, hi, "end")
        if core_vs is None or core_ve is None:
            self._emit_text(rs, re_, self._lit_text(items, ident, re_))
            return
        if core_vs > rs:
            self._emit(rs, core_vs)
        gspan = Span(core_vs, core_ve)
        context = "item" if force else "para"
        refs = []
        for p0, p1 in self._split_bounds(s, items, lead, hi):
            part_s, part_i, pvs, pve = self._slice_items(items, p0, p1)
            refs.append(self._new_chunk(part_s, context, Span(pvs, pve), part_i))
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
    def _vpos_at(items: list[_RunItem], off: int, side: str) -> int | None:
        """Surface 偏移 ``off`` 落点的 vtex 位（snap 到含它的项界）。

        ``start`` 取 ``off`` 之后首个项的 vstart；``end`` 取含 ``off``
        项的 vend——项界两侧归属相反，切开即劈项。
        """
        acc = 0
        for it in items:
            nxt = acc + len(it.surface)
            if (side == "start" and off < nxt) or (side == "end" and off <= nxt):
                return it.vstart if side == "start" else it.vend
            acc = nxt
        return None

    @staticmethod
    def _slice_items(
        items: list[_RunItem], lo: int, hi: int
    ) -> tuple[str, str, int, int]:
        """Surface ``[lo,hi)``（项界对齐）→ ``(surface, ident, vstart, vend)``。"""
        acc = 0
        out_s: list[str] = []
        out_i: list[str] = []
        vs = ve = -1
        for it in items:
            nxt = acc + len(it.surface)
            if nxt > lo and acc < hi:
                out_s.append(it.surface)
                out_i.append(it.ident)
                if vs < 0:
                    vs = it.vstart
                ve = it.vend
            acc = nxt
        return "".join(out_s), "".join(out_i), vs, ve

    @staticmethod
    def _split_bounds(  # noqa: C901, PLR0912 — 切点优先级链，平铺即 §3.8 规则序
        s: str, items: list[_RunItem], lo: int, hi: int
    ) -> list[tuple[int, int]]:
        """``s[lo:hi]`` 超大二次切分——返回 surface 区间列，切点 snap 项界。

        切点落在项 ``k`` 内部时该项整体归前段（取 vend=bounds[k+1]）——
        展开组/ph token 永不腰斩（契约 §2）。
        """
        if hi - lo <= CHUNK_MAX:
            return [(lo, hi)]
        bounds = [0]
        for it in items:
            bounds.append(bounds[-1] + len(it.surface))
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
        vspan = self._cover_to(fid, b)
        self._open_origin = (fid, a, b)
        self._open_vspan = vspan
        self._open_surface = []

    def _close_group(self) -> None:
        """收组：surface 进 run 一项，ident = ``[[EXPAND_n]]``（体=调用切片）。

        注意 ``Span.__len__`` = 区间长——零宽 span 为 falsy，判空必须用
        ``is None``（``or`` 会把 ``Span(x,x)`` 落成 ``Span(0,0)``）。
        """
        if self._open_origin is None or self._open_vspan is None:
            return
        surface = "".join(self._open_surface)
        vspan = self._open_vspan
        ph = self._ph(PhType.EXPAND, self.vt.slice(vspan.start, vspan.end))
        self._rappend(surface, ph, vspan)
        self._run_has_expand = True
        self._open_origin = None
        self._open_vspan = None
        self._open_surface = []

    def _in_group(self, t: Tok) -> bool:
        """``t`` 是否属当前展开组（gen>0 同 origin / gen=0 落调用区间内）。"""
        o = self._open_origin
        if o is None:
            return False
        if t.gen > 0:
            return t.origin == o
        fid, a, _b = t.pos
        return fid == o[0] and o[1] <= a < o[2]

    # ------------------------------------------------------------ 主循环

    def scan(self, src: TokenSource, files: list[str]) -> None:
        """消费 ``src`` 至耗尽。``files`` = fid→源文本表（gullet.file_texts）。"""
        self.file_texts = files
        while True:
            t = src.next_expanded()
            if t is None:
                break
            if t.kind == "consumed":
                if self._in_group(t):
                    # 组内 marker（gen>0）：消费的是定义体区段（早已覆盖），
                    # 不是流边界——组界不破；input 型仍记 inputs[]。
                    tag, _, name = t.text.partition(":")
                    if tag == "input":
                        self.state.inputs.append((len(self.vt), name))
                    continue
                self._close_group()
                self._on_consumed(t)
                continue
            if self._in_group(t):
                self._open_surface.append(self._tok_surface(t))
                continue
            if t.gen > 0:
                self._close_group()
                self._open_group(t)
                self._open_surface.append(self._tok_surface(t))
                continue
            self._close_group()
            self._dispatch(t, src)
        self._close_group()
        # 流耗尽 ≠ 覆盖完备：主文件尾部（尾随注释/空白不产 token）补盖进
        # vtex——单文件 identity 的收口。\\endinput 截停的子文件尾巴不盖
        # （flatten 语义：\\endinput 后字节不进输出）。
        if files and not self.in_arg:
            self._cover_to(0, len(files[0]))
        self._flush_run(len(self.vt))
        # flush 后仍可能有 vtex 尾巴无 piece 承接（纯注释/空白尾不产 run
        # 项）——补 LITERAL 保 pieces 平铺不变式。
        tail_from = self.pieces[-1].span.end if self.pieces else 0
        if tail_from < len(self.vt):
            self._emit(tail_from, len(self.vt))

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
        fid, _a, b = t.pos
        tag, _, name = t.text.partition(":")
        self._flush_run(len(self.vt))
        if tag == "input":
            self.state.inputs.append((len(self.vt), name))
            self._cons_bump(fid, b)
        else:
            vspan = self._cover_to(fid, b)
            self._emit(vspan.start, vspan.end)

    def _cons_bump(self, fid: int, end: int) -> None:
        r"""``\\input`` 调用点字节只推进 cons 不进 vtex（输出不含该行）。"""
        if end > self._cons(fid):
            self.cons[fid] = end

    # ------------------------------------------------------------ 分派

    def _dispatch(self, t: Tok, src: TokenSource) -> None:  # noqa: C901, PLR0911, PLR0912 — 分派表平铺即 §3.2
        """cs/结构 token 主分派（S1 保护子集）。"""
        fid, _a, b = t.pos
        if t.kind == "cs":
            name = t.text
            if name in ("verb", "verb*", "lstinline"):
                self._handle_verb(t, src)
                return
            if name == "begin":
                self._handle_env_begin(t, src)
                return
            if name == "end":
                self._handle_env_end(t, src)
                return
            if name in CITE_NAMES or name.startswith("cite"):
                self._protect_cs(t, src, PhType.CITE)
                return
            if name in REF_NAMES or (name.endswith("ref") and name != "href"):
                self._protect_cs(t, src, PhType.REF)
                return
            if name in PROTECT_NAMES:
                self._protect_cs(t, src, _PROTECT_TYP.get(name, PhType.CMD))
                return
            if name in BOUNDARY_NAMES or name in PROTECT_BLOCK_NAMES:
                vspan = self._cover_to(fid, b)
                self._flush_run(vspan.start)
                self._emit(vspan.start, vspan.end)
                return
            if name in INLINE_LITERAL_CMDS or name in FONT_SWITCHES:
                self._rappend_tok(t)
                return
            if name in ("bgroup", "begingroup"):
                self._scope_push(src)
                self._rappend_tok(t)
                return
            if name in ("egroup", "endgroup"):
                self._scope_pop(src)
                self._rappend_tok(t)
                return
            # 未知/其余 cs（TRANSPARENT/CHUNK_ARG/macro/unknown）S2 细分——
            # 名字先进 run（参数由主流续扫，等价 in-run 语义）
            self._rappend_tok(t)
            return
        if t.kind == "mathshift":
            self._on_math(t, src)
            return
        if t.kind == "eol_par":
            vspan = self._cover_to(fid, b)
            self._rappend("\n\n", self.vt.slice(vspan.start, vspan.end), vspan)
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
            vspan = self._cover_to(fid, b)
            self._rappend(t.text, self.vt.slice(vspan.start, vspan.end), vspan)
            self.state.warnings.append(ScanWarning("unpaired_dollar", vspan.start, "$"))
            if body:
                src.unread(body)
            return
        eb = end_tok.pos[2]
        vspan = self._cover_to(fid, eb)
        self._math_depth(src, 0)  # 体内 token 已消费，math_depth 进出相抵
        ph = self._ph(PhType.MATH, self.vt.slice(vspan.start, vspan.end))
        self._rappend_ph(PhType.MATH, ph, vspan)

    # ------------------------------------------------------------ verb

    def _handle_verb(self, t: Tok, src: TokenSource) -> None:
        r"""``\\verb|..|``/``\\lstinline``：定界 token → 字节搜闭合 + resync。"""
        fid, _a, b = t.pos
        d = src.read()
        if d is not None and d.kind == "other" and d.text == "*":
            d = src.read()  # \verb* 星号吃掉
        if d is None:
            self._rappend_tok(t)
            return
        # 可跳空白/token 界不严格要求（verb 定界即下一字符）
        delim = d.text
        ftext = self.file_texts[fid]
        close = ftext.find(delim, d.pos[2])
        eol = ftext.find("\n", d.pos[2])
        if close < 0 or (0 <= eol < close):
            vspan = self._cover_to(fid, b)
            self._rappend(t.text, self.vt.slice(vspan.start, vspan.end), vspan)
            src.unread([d])
            return
        end = close + len(delim)
        vspan = self._cover_to(fid, end)
        self._rappend_ph(
            PhType.VERB,
            self._ph(PhType.VERB, self.vt.slice(vspan.start, vspan.end)),
            vspan,
        )
        self._skip_past(src, fid, end)

    def _skip_past(self, src: TokenSource, fid: int, end: int) -> None:
        """Resync ``fid`` 源到 ``end``——raw 区段不经 token 流（契约 §4）。

        调 ``gullet.skip_past`` 真 API（tokbuf 残骸剔除 + 栈深找 fid +
        i 只前进）；失败时 gullet 已记 ``verb_resync_failed``，分段器
        不退化——位置已对齐，后续 token 照常（与今日无 verb 处理等价）。
        """
        if isinstance(src, Gullet):
            src.skip_past(fid, end)

    # ------------------------------------------------------------ env

    def _env_name(self, src: TokenSource) -> tuple[str | None, Tok | None, list[Tok]]:
        """``{env}`` 组收集：返回 (env 名, rbrace token, 全消费 token 列)。"""
        consumed: list[Tok] = []
        open_t = src.read()
        if open_t is not None:
            consumed.append(open_t)
        if open_t is None or open_t.kind != "lbrace":
            return None, None, consumed
        name_toks: list[Tok] = []
        while True:
            x = src.read()
            if x is None:
                return None, None, consumed
            consumed.append(x)
            if x.kind == "rbrace":
                name = "".join(t2.text for t2 in name_toks).strip()
                return name, x, consumed
            name_toks.append(x)

    def _handle_env_begin(self, t: Tok, src: TokenSource) -> None:
        r"""``\begin{env}`` token 版：verbatim/math/protected/transparent。"""
        fid, _a, _b = t.pos
        env, close_t, consumed = self._env_name(src)
        if env is None or close_t is None:
            src.unread(consumed)
            self._rappend_tok(t)
            return
        v_begin = self._cover_to(fid, close_t.pos[2])
        if env in VERBATIM_ENVS:
            self._flush_run(v_begin.start)
            pat = "\\end{" + env + "}"
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
        if env in MATH_ENVS or env in PROTECTED_ENVS:
            hit = self._find_env_end(src, env)
            if hit is None:
                self._flush_run(v_begin.start)
                self._emit(v_begin.start, v_begin.end)
                self.state.warnings.append(
                    ScanWarning("unclosed_env", v_begin.start, env)
                )
                return
            end_tok = hit
            e_fid, _ea, eb = end_tok.pos
            vspan = self._cover_to(e_fid, eb)
            self._flush_run(v_begin.start)
            typ = PhType.MATH if env in MATH_ENVS else PhType.ENV
            self._emit_ph(
                typ,
                v_begin.start,
                vspan.end,
                self.vt.slice(v_begin.start, vspan.end),
            )
            return
        # transparent/未知 env：begin 行进 run（体由主流续扫）
        self._rappend(
            "\\begin{" + env + "}",
            self.vt.slice(v_begin.start, v_begin.end),
            v_begin,
        )
        self.env_stack.append(env)
        self._scope_push(src)

    def _handle_env_end(self, t: Tok, src: TokenSource) -> None:
        r"""``\end{env}``：弹 env 栈 + literal 边界 + scope pop。"""
        fid, _a, _b = t.pos
        env, close_t, consumed = self._env_name(src)
        if env is None or close_t is None:
            src.unread(consumed)
            self._rappend_tok(t)
            return
        vspan = self._cover_to(fid, close_t.pos[2])
        self._flush_run(vspan.start)
        self._emit(vspan.start, vspan.end)
        if env in self.env_stack:
            while self.env_stack and self.env_stack[-1] != env:
                self.env_stack.pop()
            if self.env_stack:
                self.env_stack.pop()
        self._scope_pop(src)

    def _find_env_end(self, src: TokenSource, env: str) -> Tok | None:
        r"""Token 版 env 配对（``read()`` 原始流——前瞻不触发展开副作用）。

        命中返回 ``\end{env}`` 的 rbrace token（消费了全部 body token）；
        未命中回吐全部已收 token 返回 None（调用方从 begin 后续扫）。
        TODO(S2)：F12 墓标移植——事件位改拉取序号（跨 fid 全序）。
        """
        target = env.rstrip("*")
        collected: list[Tok] = []
        depth = 1
        while True:
            x = src.read()
            if x is None:
                src.unread(collected)
                return None
            collected.append(x)
            if x.kind != "cs":
                continue
            if x.text in ("begin", "end"):
                n, c, grp = self._env_name(src)
                collected.extend(grp)
                if n is None or c is None:
                    continue
                if n.rstrip("*") != target:
                    continue
                if x.text == "begin":
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        return c

    # ------------------------------------------------------------ 保护调用

    def _protect_cs(self, t: Tok, src: TokenSource, typ: PhType) -> None:
        r"""``\cite``/``\ref``/``\label`` 族：``*``/``[opt]``/``{args}`` 全消费。"""
        fid, _a, b = t.pos
        end = b
        x = src.read()
        if x is not None and x.kind == "other" and x.text == "*":
            end = x.pos[2]
            x = src.read()
        if x is not None and x.kind == "other" and x.text == "[":
            ge = self._bracket_end(src)
            if ge is not None:
                end = ge
                x = src.read()
        while x is not None and x.kind == "lbrace":
            ge = self._brace_end(src)
            if ge is None:
                break
            end = ge
            x = src.read()
        if x is not None:
            src.unread([x])
        vspan = self._cover_to(fid, end)
        self._rappend_ph(
            typ, self._ph(typ, self.vt.slice(vspan.start, vspan.end)), vspan
        )

    def _brace_end(self, src: TokenSource) -> int | None:
        """平衡组：``{`` 起 → 配对 ``}`` 的 pos.end（token 级 match_brace）。"""
        depth = 1
        while True:
            x = src.read()
            if x is None:
                return None
            if x.kind == "lbrace":
                depth += 1
            elif x.kind == "rbrace":
                depth -= 1
                if depth == 0:
                    return x.pos[2]

    def _bracket_end(self, src: TokenSource) -> int | None:
        """``[`` 起 → 配对 ``]`` 的 pos.end（token 级 match_bracket）。"""
        depth = 1
        while True:
            x = src.read()
            if x is None:
                return None
            if x.kind == "other" and x.text == "[":
                depth += 1
            elif x.kind == "other" and x.text == "]":
                depth -= 1
                if depth == 0:
                    return x.pos[2]


def parse_tex_v2(tex: str) -> ScanResult:
    r"""``parse_tex`` 的 token 流版（S1 骨架入口——双跑对照用）。

    ``\begin{document}`` preamble 判定沿用 api 的 mask 视图规则；
    preamble 区段照流过 gullet（def/if 生效）但分段全 literal——S2 接线。
    """
    state = ScanState(
        issuer=PlaceholderIssuer(),
        ph_map={},
        chunks=[],
        macros=MacroTable(),
        inputs=[],
        warnings=[],
    )
    g = Gullet(tex)
    seg = Segmenter(state)
    seg.scan(g, g.file_texts)
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
