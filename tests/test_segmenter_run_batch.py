r"""fix#9 cut-2 文本 run 批量化 pin——``_dispatch`` gen=0 文本头快进。

不变量：批量化 = 纯优化快路——``_text_run_end`` 返回 ``None`` 即落回
``_rappend_tok`` 逐 token 路径，产品输出与不批量化逐字节等价。等价口径
= protected_tex/vtex/chunks(content+context)/ph_map/warnings 全等；
``_FORCE_OFF``（``_text_run_end`` 恒 ``None``）即关闭开关。

钉点：

- 等价横扫：ws 折叠/注释 gap/``~``/括号/math/未知 cs 探针回放/子扫
  ``_ListSource`` 臂/猫码切换——开关对照全等。
- 猫码切换：``\catcode`` 改表后 run 正则按 ``cats._v`` 重建——``@``
  IGNORED 化后 ``a@b`` surface 不含 ``@``（旧缓存会漏）。
- 回放守卫：``m.i != t.pos[2]`` 或 ``tokbuf`` 非空 → ``None``（逐 token）。
- ``_ListSource`` 臂：space 夹心须原字节 ``" "`` + 后继相接文本头。
- ``>CHUNK_MAX`` 连续文本：run 单项化后切点前移到项尾——分段变少、
  identity/校验不变（``_split_bounds`` snap 语义的已记录取舍）。
- ACTIVE ``~`` 不批化：``~`` 永不进 run 内部（只能作 run 头）。
"""

from __future__ import annotations

import pytest
from conftest import DOC, check_invariants

from texlate.latex import parse_tex, reconstruct
from texlate.latex.gullet import Gullet
from texlate.latex.model import ScanResult, ScanState
from texlate.latex.mouth import CatTable, Mouth
from texlate.latex.placeholder import PlaceholderIssuer
from texlate.latex.segmenter import Segmenter
from texlate.latex.segmenter._common import _ListSource
from texlate.latex.segmenter.core import _Core
from texlate.latex.segmenter.mainloop import _MainLoop


def _digest(res: ScanResult) -> tuple:
    """等价口径五元组。"""
    return (
        res.protected_tex,
        res.vtex,
        [(c.content, c.context) for c in res.chunks],
        sorted(res.ph_map.items()),
        [(w.kind, w.pos, w.detail) for w in res.warnings],
    )


def _force_off(_self: object, _t: object, _src: object) -> None:
    """``_text_run_end`` 关闭桩——恒 ``None`` 强制逐 token fallback。"""


def _scan_pair(tex: str) -> tuple[ScanResult, ScanResult]:
    """同输入跑 batched / 强制 fallback 两臂。"""
    res_new = parse_tex(tex)
    orig = _MainLoop._text_run_end  # noqa: SLF001 — pin 的就是这条快路
    try:
        _MainLoop._text_run_end = _force_off  # noqa: SLF001
        res_old = parse_tex(tex)
    finally:
        _MainLoop._text_run_end = orig  # noqa: SLF001
    return res_new, res_old


def _seg_for(g: Gullet) -> Segmenter:
    """挂到 ``g`` file_texts 的裸分段器（``_text_run_end`` 单元钉用）。"""
    state = ScanState(
        issuer=PlaceholderIssuer(),
        ph_map={},
        chunks=[],
        macros=g.macros,
        inputs=[],
        warnings=[],
    )
    seg = Segmenter(state)
    seg.file_texts = g.file_texts
    return seg


# ------------------------------------------------------------- 等价横扫

_EQUIV_BODIES = [
    "Plain words in a row here.",  # 基线 run
    "a  b   c   dddd",  # 折叠空白边界——space token 后还有折叠字节
    "a\tb c",  # \t 是 space catcode：surface " " ≠ 原字节 "\t"
    "lead words % a comment\ntrail words here",  # 注释 gap
    "foo~bar baz quux",  # ACTIVE ``~`` 断 run
    "pre { inner words here } post words",  # 括号组界
    "text $x+y$ more words follow",  # math 断 run
    "text \\emph{arg words here} tail words",  # cs + 透明参
    "one \\zzunknown two three four",  # 未知 cs 探针回放边界
    "\\footnote{foot note words here} after text",  # chunk-arg _ListSource 子扫
    "\\section{Section Title Words} body text follows",  # 同上另一路
    "a\\ b c",  # 控制空格 cs
    "x {\\catcode`@=9 a@b c} y@z w",  # @ → IGNORED：run 集内剔除
    "{\\makeatletter a@b c\\makeatother} d e",  # makeatletter 组内 LETTER
    "end of para.\n\nNext para words here.",  # eol_par 段界
    "text with_trail^sup&align#param chars",  # sub/super/align/param 字符
]


@pytest.mark.parametrize("body", _EQUIV_BODIES)
def test_batched_equals_fallback(body: str) -> None:
    """run 边界族：批量化臂与强制逐 token 臂输出逐字节全等。"""
    tex = DOC % body
    res_new, res_old = _scan_pair(tex)
    check_invariants(res_new, tex)
    assert _digest(res_new) == _digest(res_old)


# ------------------------------------------------------------- 猫码切换


def test_catcode_switch_invalidates_run_rx() -> None:
    r"""``\catcode`@=9`` 后 ``@`` 进 IGNORED——``a@b`` surface 须为 ``ab``。

    旧正则缓存不重建会把 ``@`` 当文本批进 surface（``a@b``≠``ab`` 静默错切）。
    """
    res, res_old = _scan_pair(
        DOC % "lead {\\catcode`@=9 inside a@b and more text words} tail."
    )
    assert _digest(res) == _digest(res_old)
    joined = " ".join(c.content for c in res.chunks)
    assert "inside ab and more" in joined  # @ 被 IGNORED 吞掉
    assert "a@b" not in joined


def test_catcode_into_active_exits_run_set() -> None:
    r"""``\catcode`z=13`` 把 ``z`` 改 ACTIVE——出 run 集，run 在 ``z`` 前断。

    旧缓存会把 ``z`` 继续当文本批进 run（surface 同值但项界合并错切）。
    """
    res, res_old = _scan_pair(
        DOC % "lead {\\catcode`z=13 inside azb and more text words} tail."
    )
    assert _digest(res) == _digest(res_old)


# ------------------------------------------------------------- 回放守卫


def test_tokbuf_replay_forces_fallback() -> None:
    r"""``unread`` 回压的 token：``m.i`` 已领先 → 守卫拒批（除最新鲜那枚）。"""
    g = Gullet()
    g.push_source("abcdef x", "")
    seg = _seg_for(g)
    toks = [g.read() for _ in range(3)]  # a,b,c——产出后 m.i=3
    g.unread(toks)
    ta = g.read()
    assert seg._text_run_end(ta, g) is None  # noqa: SLF001 — tokbuf=[b,c] 且 i=3≠1
    tb = g.read()
    assert seg._text_run_end(tb, g) is None  # noqa: SLF001 — tokbuf=[c] 且 i=3≠2
    tc = g.read()
    # tokbuf 排空 + i==pos[2]——'c' 是最新鲜 token，run "def x" 照常批
    assert seg._text_run_end(tc, g) == len("abcdef x")  # noqa: SLF001


def test_non_top_mouth_token_falls_back() -> None:
    r"""``file_id`` 与栈顶 Mouth 不同（回放合成源/异 fid token）→ 拒批。"""
    g = Gullet()
    g.push_source("abcdef", "")
    seg = _seg_for(g)
    t = g.read()  # 'a' [0,1)
    m = g.inputs[-1]
    m.i = 5  # 模拟 i 已前进（拉参预读）——i≠t.pos[2] → None
    assert seg._text_run_end(t, g) is None  # noqa: SLF001


# ------------------------------------------------------------- _ListSource 臂


def _list_src(tex: str) -> _ListSource:
    return _ListSource(list(Mouth(tex, 0, CatTable())))


def test_listsource_merges_contiguous_with_inner_space() -> None:
    """``ab cd``：内部单空格（原字节 ``" "``）夹心并入——run 盖到 5。"""
    g = Gullet()
    g.push_source("ab cd", "")
    seg = _seg_for(g)
    src = _list_src("ab cd")
    head = src.next_expanded()  # 'a'
    assert seg._text_run_end(head, src) == len("ab cd")  # noqa: SLF001
    assert src.next_expanded() is None  # b,sp,c,d 全出队合并


def test_listsource_space_tail_not_merged() -> None:
    """``ab ``：space 是 run 尾（无后继文本头）——不并入，run 止于 ``b``。"""
    g = Gullet()
    g.push_source("ab ", "")
    seg = _seg_for(g)
    src = _list_src("ab ")
    head = src.next_expanded()
    assert seg._text_run_end(head, src) == len("ab")  # noqa: SLF001 — 'b' 并入即停


def test_listsource_tab_space_not_merged() -> None:
    r"""``a\tb``：space token 原字节 ``\t``≠``" "``——不并入（surface 会偏）。"""
    g = Gullet()
    g.push_source("a\tb", "")
    seg = _seg_for(g)
    src = _list_src("a\tb")
    head = src.next_expanded()  # 'a'
    assert seg._text_run_end(head, src) is None  # noqa: SLF001


def test_listsource_folded_gap_not_merged() -> None:
    """``a  b``：第二空格被折叠不产 token——``b`` 的 ``pos`` 不接 → 停。"""
    g = Gullet()
    g.push_source("a  b", "")
    seg = _seg_for(g)
    src = _list_src("a  b")
    head = src.next_expanded()  # 'a'
    assert seg._text_run_end(head, src) is None  # noqa: SLF001


# ------------------------------------------------------------- 边界语义


def test_active_tilde_never_inside_run() -> None:
    r"""``~`` 剔出 run 集：run 项含 ``~`` 时 ``~`` 必在项首（只能当头）。"""
    surfaces: list[str] = []
    orig = _Core._rappend  # noqa: SLF001

    def spy(self, surface: str, ident: str, vspan: object) -> None:  # noqa: ANN001
        surfaces.append(surface)
        orig(self, surface, ident, vspan)

    tex = DOC % "aa~bb cc~dd"
    _Core._rappend = spy  # noqa: SLF001
    try:
        res = parse_tex(tex)
    finally:
        _Core._rappend = orig  # noqa: SLF001
    check_invariants(res, tex)
    for s in surfaces:
        if "~" in s:
            assert s.startswith("~"), s  # ~ 出现在 run 项内部 = 批化越界


def test_over_chunkmax_single_run() -> None:
    """>CHUNK_MAX 连续文本 run 单项化：切点 snap 到项尾——一段一 chunk。"""
    body = "Alpha " * 750 + "omega."  # ~4506 字符纯文本 run（单空格夹心）
    tex = DOC % body
    res_new, res_old = _scan_pair(tex)
    check_invariants(res_new, tex)
    assert reconstruct(res_new) == tex
    # snap 到项界：批量化臂整 run 一个 chunk；逐 token 臂按项界前移切分
    assert len(res_new.chunks) == 1
    assert len(res_old.chunks) > len(res_new.chunks)
    assert res_new.chunks[0].content == body + " " or res_new.chunks[0].content == body


def test_batch_actually_skips_tokenization() -> None:
    """批量化真在推进：文本段内字符不物化 token——``Mouth.next`` 计数暴降。"""
    tex = DOC % ("word " * 60 + "end.")
    calls = 0
    orig_next = Mouth.next
    orig_end = _MainLoop._text_run_end  # noqa: SLF001

    def spy(self: Mouth) -> object:
        nonlocal calls
        calls += 1
        return orig_next(self)

    Mouth.next = spy  # type: ignore[method-assign]
    try:
        res_new = parse_tex(tex)
        batched_calls = calls
        calls = 0
        _MainLoop._text_run_end = _force_off  # noqa: SLF001
        res_old = parse_tex(tex)
        base_calls = calls
    finally:
        Mouth.next = orig_next  # type: ignore[method-assign]
        _MainLoop._text_run_end = orig_end  # noqa: SLF001
    assert _digest(res_new) == _digest(res_old)
    assert batched_calls < base_calls * 0.5  # 300+ token 文本段应省大半
