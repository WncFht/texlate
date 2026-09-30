"""seq 级 PDF 位置对位——``GET /reader`` 响应注入 ``seqpos`` 字段。

zh.pdf 有 TLXC 标记（``BDC /MCID=50000+seq``，``latex/reconstruct.py`` 注锚）→
pypdf ``visitor_operand_before`` 直读精确点锚；en.pdf（base 编译链无标记）
与未标记 zh seq 走文本匹配：chunk 文本 texstrip+alnum 归一成 needle，PDF
``extract_text`` 聚行成归一化字符流（行界记 page/fraction）。匹配两遍——
光标窗口快路建单调骨架，漏跑段在相邻命中夹逼的流区间内 6-gram 锚定补缺
（浮动体出序/字体丢空格粘连都能救回）。行界记 ``(char_off,page,frac,x,x1)``
——x/x1 是段左右缘页宽分位，栏判定/阅读序键 ``(page,col,frac)`` 的原料
+ 宽行 snap 幅面。
结果缓存 ``task_dir/seqpos.json``，
输入件 mtime 更新即重算；dual.json 本体不动（``?version=sha256`` 不可变）。

god-split: 实现体按域拆进 ``seqpos/`` 子包 4 叶 (facade=__init__), 本文
件是 PEP 562 惰性门面 (同 ``fixloop/builtins/__init__`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``seqpos.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意：patch 叶子不 patch 门面 (docs/dev/seams.md §1)
——``facade.name`` 读到的恒是叶子对象，但 ``setattr(facade, ...)`` 只
遮蔽门面不改叶子内部互引。叶子间互引走全路径直跨
(``texlate.server.seqpos.<叶>``), 不经本门面。
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.server.seqpos.assemble import (
        _CACHE,
        _MARK_COV,
        _MARK_FALLBACK_CHARS,
        _MARK_FB_CHARS_LO,
        _MARK_FB_COV,
        _MARK_FB_MAXFRAC,
        _MARK_REPLAY_PAGES,
        _ORPHAN_CHARS,
        _ORPHAN_MIN_ND,
        _ORPHAN_PAGES,
        _ROW_EPS,
        _ROW_EPSX,
        _VERSION,
        _interp_t,
        _mark_trusted,
        _nd_unmatchable,
        _needles,
        _pos_at,
        _row_extent,
        compute_seqpos,
        seqpos_for_task,
    )
    from texlate.server.seqpos.docorder import (
        _INPUT_RX,
        _dfs_flat,
        _doc_order,
        _read_tex,
    )
    from texlate.server.seqpos.match import (
        _CAND_CAP,
        _CITE_GAP,
        _COL_SPLIT_X,
        _COV_MID,
        _COV_SHORT,
        _GAP_WORD_RX,
        _GRAM,
        _GRAM_FREQ,
        _JUMP_CAP,
        _MARK_HEAD_BLK,
        _MARK_HEAD_COV,
        _MARK_HEAD_LEAD,
        _MARK_HEAD_N,
        _MARK_HEAD_SKIP,
        _PASSC_COV,
        _SKIP_PROBE_MIN,
        _gram_index,
        _head_ok,
        _match_all,
        _match_bounded,
        _match_side,
        _min_cov,
        _offset_at,
        _skips_pending,
        _sm_cov,
        _text_cov,
    )
    from texlate.server.seqpos.stream import (
        _ASC,
        _BDC_ARGC,
        _CJK_MIN,
        _COL_MIN_LINES,
        _GUTTER_MIN_SIDE,
        _GUTTER_MIN_W,
        _LINE_TOL,
        _MARK_FTOL,
        _MARK_XTOL_PT,
        _TEX_STRIP,
        _char_stream,
        _char_stream_pypdf,
        _cluster_lines,
        _est_w,
        _font_cache_ctx,
        _mark_text_geom,
        _marks_layer,
        _norm_chars,
        _reading_order,
        _tex_strip,
        _text_layer,
    )

log = logging.getLogger(__name__)

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "assemble": (
        "_CACHE",
        "_MARK_COV",
        "_MARK_FALLBACK_CHARS",
        "_MARK_FB_CHARS_LO",
        "_MARK_FB_COV",
        "_MARK_FB_MAXFRAC",
        "_MARK_REPLAY_PAGES",
        "_ORPHAN_CHARS",
        "_ORPHAN_MIN_ND",
        "_ORPHAN_PAGES",
        "_ROW_EPS",
        "_ROW_EPSX",
        "_VERSION",
        "_interp_t",
        "_mark_trusted",
        "_nd_unmatchable",
        "_needles",
        "_pos_at",
        "_row_extent",
        "compute_seqpos",
        "seqpos_for_task",
    ),
    "docorder": (
        "_INPUT_RX",
        "_dfs_flat",
        "_doc_order",
        "_read_tex",
    ),
    "match": (
        "_CAND_CAP",
        "_CITE_GAP",
        "_COL_SPLIT_X",
        "_COV_MID",
        "_COV_SHORT",
        "_GAP_WORD_RX",
        "_GRAM",
        "_GRAM_FREQ",
        "_JUMP_CAP",
        "_MARK_HEAD_BLK",
        "_MARK_HEAD_COV",
        "_MARK_HEAD_LEAD",
        "_MARK_HEAD_N",
        "_MARK_HEAD_SKIP",
        "_PASSC_COV",
        "_SKIP_PROBE_MIN",
        "_gram_index",
        "_head_ok",
        "_match_all",
        "_match_bounded",
        "_match_side",
        "_min_cov",
        "_offset_at",
        "_skips_pending",
        "_sm_cov",
        "_text_cov",
    ),
    "stream": (
        "_ASC",
        "_BDC_ARGC",
        "_CJK_MIN",
        "_COL_MIN_LINES",
        "_GUTTER_MIN_SIDE",
        "_GUTTER_MIN_W",
        "_LINE_TOL",
        "_MARK_FTOL",
        "_MARK_XTOL_PT",
        "_TEX_STRIP",
        "_char_stream",
        "_char_stream_pypdf",
        "_cluster_lines",
        "_est_w",
        "_font_cache_ctx",
        "_mark_text_geom",
        "_marks_layer",
        "_norm_chars",
        "_reading_order",
        "_tex_strip",
        "_text_layer",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "_ASC",
    "_BDC_ARGC",
    "_CACHE",
    "_CAND_CAP",
    "_CITE_GAP",
    "_CJK_MIN",
    "_COL_MIN_LINES",
    "_COL_SPLIT_X",
    "_COV_MID",
    "_COV_SHORT",
    "_GAP_WORD_RX",
    "_GRAM",
    "_GRAM_FREQ",
    "_GUTTER_MIN_SIDE",
    "_GUTTER_MIN_W",
    "_INPUT_RX",
    "_JUMP_CAP",
    "_LINE_TOL",
    "_MARK_COV",
    "_MARK_FALLBACK_CHARS",
    "_MARK_FB_CHARS_LO",
    "_MARK_FB_COV",
    "_MARK_FB_MAXFRAC",
    "_MARK_FTOL",
    "_MARK_HEAD_BLK",
    "_MARK_HEAD_COV",
    "_MARK_HEAD_LEAD",
    "_MARK_HEAD_N",
    "_MARK_HEAD_SKIP",
    "_MARK_REPLAY_PAGES",
    "_MARK_XTOL_PT",
    "_ORPHAN_CHARS",
    "_ORPHAN_MIN_ND",
    "_ORPHAN_PAGES",
    "_PASSC_COV",
    "_ROW_EPS",
    "_ROW_EPSX",
    "_SKIP_PROBE_MIN",
    "_TEX_STRIP",
    "_VERSION",
    "_char_stream",
    "_char_stream_pypdf",
    "_cluster_lines",
    "_dfs_flat",
    "_doc_order",
    "_est_w",
    "_font_cache_ctx",
    "_gram_index",
    "_head_ok",
    "_interp_t",
    "_mark_text_geom",
    "_mark_trusted",
    "_marks_layer",
    "_match_all",
    "_match_bounded",
    "_match_side",
    "_min_cov",
    "_nd_unmatchable",
    "_needles",
    "_norm_chars",
    "_offset_at",
    "_pos_at",
    "_read_tex",
    "_reading_order",
    "_row_extent",
    "_skips_pending",
    "_sm_cov",
    "_tex_strip",
    "_text_cov",
    "_text_layer",
    "compute_seqpos",
    "seqpos_for_task",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{__package__}.{leaf}"), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖：

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝，是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and (
            isinstance(v, dict)
            or (callable(v) and getattr(v, "__module__", None) == __name__)
        )
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
