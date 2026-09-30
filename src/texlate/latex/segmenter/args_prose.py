r"""``latex/segmenter.args_prose`` — 散文参挖掘 + 子扫渲染（``args`` god-file 机械拆分叶）。

散文门三臂共用判定面：``_opaque_arg_prose`` 调用点逐参判据（组参
剔注释+cs 后 ≥4 连词即散文）→ ``_prose_args_of`` 调用点名闸 →
``_prose_args_gated`` ``gen_overflow`` 闸 → ``_emit_prose_args``
「``{`` 前结构进 ``[[typ]]`` + 参内容子扫渲 surface」逐枚发射。
``_subscan_render``/``_rappend_subscan``/``_arg_comment_ph`` 是
``_handle_chunk_arg``/``_emit_argspec_chunks`` 共用的子扫渲面；
``_PROSE_BLOCK_*`` 白名单驱动 ``_mine_prose_block``（protect-block
第三臂，界外项核销）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from texlate.latex.model import PhType, ScanWarning, Span
from texlate.latex.tables import MAX_GEN

from ._common import (
    _ARG_COMMENT_RX,
    _DEAD_ARG_NAMES,
    _DEAD_TAIL_NAMES,
    _SWALLOW_ARG_NAMES,
    TokenSource,
    _ArgTok,
    _ListSource,
    _prose_text_hit,
)
from .args_read import _ArgsRead

if TYPE_CHECKING:
    from texlate.latex.model import ScanState
    from texlate.latex.mouth import Tok
    from texlate.latex.segmenter import Segmenter

    from ._common import _Vtex

#: protect-block 散文白名单：``\markright``/``\markboth`` 运行头与
#: ``\address``/``\institute``/``\affiliation`` 机构隶属段装的是真散文
#: （界外项「protect-block 第三臂同型蒸发」核销）。``\author`` 不入——
#: ``\and`` 连名过 4 词门会把人名抬进译文面（专名翻译有害 + W56 内嵌
#: 图面）；``\date``/``\email``/``\orcid``/``\recdate``/``\publishedin``
#: 等是日期/标识元数据非散文槽位，词链门天然不中也无需挖。
_PROSE_BLOCK_NAMES = frozenset(
    {"markright", "markboth", "address", "institute", "affiliation"}
)

#: 白名单名的实参位上限——``\markboth{l}{r}`` 双参，其余单参；超限的
#: ``{..}`` 组不是实参，不收（防 ``\markright{h} {散文段落}`` 误吞正文组）。
_PROSE_BLOCK_ARITY = {
    "markright": 1,
    "markboth": 2,
    "address": 1,
    "institute": 1,
    "affiliation": 1,
}

#: 参内块级信号 cs 名——任一出现即判该参为排版体而非数据槽（探针臂
#: ``_arg_body_shaped`` 用）。env 界标/``\item``/节题皆不可能当真参数值。
_BODY_CS_NAMES = frozenset(
    {
        "begin",
        "end",
        "item",
        "section",
        "subsection",
        "subsubsection",
        "paragraph",
        "subparagraph",
        "chapter",
        "part",
    }
)


class _ArgsProse(_ArgsRead):
    # ------------------------------------------------------------ 宿主契约（ty 静态面）
    # god-class 机械拆分的静态代价：``Segmenter``（``__init__.py``）经 mixin
    # 链注入的状态/方法在本文件孤检时对 ty 不可见——``TYPE_CHECKING`` 声明
    # 即契约，签名与宿主 mixin（``core.py``/``mainloop.py``/``pending.py``）
    # 定义保持一致；宿主签名改动时同步此处。
    if TYPE_CHECKING:
        # ``_Core.__init__`` 注入的状态
        state: ScanState
        gen: int
        vt: _Vtex
        file_texts: list[str]

        # ``_Core``/``_MainLoop``/``_Pending`` 提供的方法
        def spawn(
            self, *, in_arg: bool | None = None, mined: bool | None = None
        ) -> Segmenter: ...
        def _cover_to(self, fid: int, end: int) -> Span: ...
        def _cover_gap(self, fid: int, tok_start: int) -> None: ...
        def _cover_ph(
            self, fid: int, end: int, typ: PhType, gap: Tok | None = None
        ) -> Span: ...
        def _ph(
            self, typ: PhType, body: str, cut: tuple[int, int] | None = None
        ) -> str: ...
        def _rappend(self, surface: str, ident: str, vspan: Span) -> None: ...

    # ------------------------------------------------------------ 散文参挖掘 + 子扫渲染

    def _mine_prose_block(self, t: Tok, src: TokenSource, fid: int, b: int) -> bool:
        r"""``_PROSE_BLOCK_NAMES`` 白名单名的散文参挖掘（第三臂，界外项核销）。

        ``\markright``/``\markboth`` 运行头与 ``\address``/``\institute``/
        ``\affiliation`` 隶属段的实参装的是真散文——整调用折 ``[[AUTHOR]]``
        会蒸发译文面（``_handle_protect_block`` 与 opaque 蒸发同型）。
        实参逐参过共享判据（``_prose_args_of`` → ``_opaque_arg_prose``，
        位上限 ``_PROSE_BLOCK_ARITY`` 防尾随正文组误吞）：命中即探针臂同款
        发射——``[[CMD]]`` 分段护结构 + 子扫渲进 run surface；无命中 /
        ``gen`` 触底 → 全参回放返 False，调用方走 ``[[AUTHOR]]`` 原路径。
        ``\author`` 不入白名单：``\and`` 连名过词链门会把人名抬进译文面。
        """
        args, end = self._args_tok(
            src, fid, _PROSE_BLOCK_ARITY[t.text], b, allow_single_token=False
        )
        prose_args = self._prose_args_gated(t.text, t, fid, args, "block")
        if not prose_args:
            self._unread_args(src, args)
            return False
        self._cover_gap(fid, t.pos[1])
        self._emit_prose_args(fid, prose_args, PhType.CMD)
        self._cover_ph(fid, end, PhType.CMD)
        return True

    @staticmethod
    def _arg_body_shaped(a: _ArgTok) -> bool:
        r"""参 token 流是否块级排版体（而非参数槽）。

        ``eol_par`` 空行（TeX ``\long`` 语义多段参）或
        ``\begin``/``\end``/``\item``/节题 cs 任一即体。
        """
        for x in a.all_toks:
            if x.kind == "eol_par":
                return True
            if x.kind == "cs" and x.text in _BODY_CS_NAMES:
                return True
        return False

    def _opaque_arg_prose(self, fid: int, a: _ArgTok) -> bool:
        r"""Opaque 宏 ``{..}``/``[..]`` 组参的调用点散文门（gullet-at scout 口径）。

        只认本 fid 实消费的 ``{``/``[``-open 组参：跨 fid 组字节切片判不了形
        （``_keyval_tail_end`` 同款守门）、``d<>``/``e``/``r()``/``t``/单 token
        参不是散文槽位。``[``-open 可选参同挖——``\subfigure[长 caption]{..}``
        的 opt 散文是真翻译料，``[width=2cm]``/``[see]`` 由形状门/词链挡住。
        ``key=`` 起头的 keyval 组不挖——``{pdftitle={长标题}}`` 值内散文会连
        ``key=`` 键位一起抬进译文面（``_keyval_tail_end`` 同款形状门，
        ``\setkeys`` 炸面）；逗号分隔机读名单同罩——``{arrows, automata,
        backgrounds, calendar}`` 类库/包/文件列抠出翻译即断链（1907.03868
        实遇）。``\index``/``\label`` 整调用判形前剥除——零宽标记不当隔墙
        （W85 参内嵌句面）。内容剔注释+cs 后 ≥4 连词即散文。
        """
        if a.fe <= a.fs or a.cs <= a.fs:
            return False  # 未消费占位 / 单 token 参
        if any(x.pos[0] != fid for x in a.all_toks):
            return False  # 跨 fid 组——``file_texts[fid]`` 切片错位，保持 opaque
        if self.file_texts[fid][a.fs] not in "{[":
            return False  # ``d<>``/``e``/``r()``/``t`` 定界参非散文槽位
        content = self.file_texts[fid][a.cs : a.ce]
        return _prose_text_hit(content)

    def _prose_args_of(self, name: str, fid: int, args: list[_ArgTok]) -> list[_ArgTok]:
        r"""调用点名闸 + 逐参散文门——三臂（opaque/探针/argspec）抠出判定单源。

        ``_SWALLOW_ARG_NAMES``（吞块）/``_DEAD_ARG_NAMES``（被删死文本）
        整调用不挖；``_DEAD_TAIL_NAMES`` 只放首个实参——``\replaced{新}{旧}``
        的 ``{旧}`` 是被替换死文本不译。序数按实消费参计（``[o]`` 占位
        不计位——``\replaced`` 无 ``[o]`` 签名，参序即实序）。
        """
        if name in _SWALLOW_ARG_NAMES or name in _DEAD_ARG_NAMES:
            return []
        tail_dead = name in _DEAD_TAIL_NAMES
        out: list[_ArgTok] = []
        nth = 0
        for a in args:
            if a.fe <= a.fs:
                continue  # 未消费占位不占实参序
            if (not tail_dead or nth == 0) and self._opaque_arg_prose(fid, a):
                out.append(a)
            nth += 1
        return out

    def _prose_args_gated(
        self, name: str, t: Tok, fid: int, args: list[_ArgTok], tag: str
    ) -> list[_ArgTok]:
        r"""``_prose_args_of`` + ``gen_overflow`` 闸二连——三臂共用判定面。

        子扫代数触底时散文参不挖、整调用维持 protect/opaque 原文
        （``_handle_chunk_arg`` 同款回压：宁可不译也不超代数）；``tag``
        即告警 detail 前缀（``block``/``opaque``/``probe``/``argspec``）。
        """
        prose_args = self._prose_args_of(name, fid, args)
        if prose_args and self.gen >= MAX_GEN:
            self.state.warnings.append(
                ScanWarning("gen_overflow", len(self.vt), f"{tag}:{t.text}")
            )
            prose_args = []
        return prose_args

    def _emit_prose_args(
        self, fid: int, prose_args: list[_ArgTok], typ: PhType
    ) -> None:
        r"""散文参逐枚「``{`` 前结构进 ``[[typ]]`` + 参内容子扫渲 surface」发射。

        ``_cover_to(a.cs)`` 不含前隙——调用方先 ``_cover_gap`` 剖命令前
        间隙字面项；``_rappend_subscan`` 的 vmark 不复用位（逐枚只渲不锚）。
        """
        for a in prose_args:
            self._cover_ph(fid, a.cs, typ)
            self._rappend_subscan(a, len(self.vt))

    def _rappend_subscan(self, a: _ArgTok, vmark: int) -> int:
        r"""子扫渲染串进 run（``[vmark, vt 末)`` 区间记账）→ 新 vmark。

        ``_emit_argspec_chunks`` 的 op 循环锚位推进同款——``vmark`` 是
        上一 op 落定后的 vt 位，返回 ``len(self.vt)`` 供下一 op 复用。
        """
        rendered = self._subscan_render(a)
        self._rappend(rendered, rendered, Span(vmark, len(self.vt)))
        return len(self.vt)

    def _subscan_render(self, a: _ArgTok) -> str:
        r"""文本参内容 token → in_arg 子扫渲染串（含尾字节兜底 + 注释 ph）。

        ``_handle_chunk_arg`` 的子扫段抽出：覆盖经共享 vt/cons 直落父
        区间（``a.cs`` 前的字面段由调用方先盖），``a.ce`` 内残余字节
        补盖进渲染串（F-尾丢同款）。
        """
        fid = a.fid
        sub = self.spawn(in_arg=True)
        sub.scan(cast("TokenSource", _ListSource(list(a.toks))), self.file_texts)
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
