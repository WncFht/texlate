r"""T0 版面质检电池（layoutqc stage 的检测本体）。

输入全是现成产物：splice 树的 ``<stem>.pdf/.log/.txlm``、build-base 树
的同三件套、src 源树（env_inventory 期望面）。零 LLM、零重编——词面
pymupdf 优先（clip-aware，缺席退 pdftotext -bbox）+ poppler 子进程
（pdfimages -list）+ 日志正则 + marks 查表。

每个 check 返 findings（``{sig, …}`` 逐条）+ metrics 计数；汇总成
``{findings, metrics}`` 由 stage 挂 verdict/sig/errors。设计口径见
docs/dev/layoutqc.md §4 T0 表。

阈值集中 ``_layoutqc_thresh`` 叶——校准集（§7.4）出来前全是先验值，
sig 即分桶键，阈值漂移只改一处。

拆分: 实现体按检测通道拆进同包私有叶 —— ``_layoutqc_thresh`` (阈值/
检测 regex/sig 集常量区), ``_layoutqc_pagekit`` (跨通道共享页判定件:
poppler 子进程包/folio/结构头/verso 豁免), ``_layoutqc_logcheck``
(编译日志信号), ``_layoutqc_markcheck`` (marks 查表), ``_layoutqc_geocheck``
(pymupdf/poppler 词面 + bbox 几何), ``_layoutqc_textcheck`` (纯文本
残英/退化/断链 + bib 尾截 + 骨架件), ``_layoutqc_rastercheck`` (T1
渲染子进程 + pdfimages + raster 对拍), ``_layoutqc_assemble``
(qc_paper 总装 + tier 门档); 本文件是 PEP 562 惰性门面 (同
``kernel.vault``/``kernel.importer`` 形制) —— 平名经 ``_LEAF_EXPORTS``
映射回叶子, ``__getattr__`` 首访解析并缓存, ``from specs._layoutqc
import X`` 与属性读面与拆分前逐名等价; HEAD 期模块属性面 (stdlib
模块名/texlate 顶层绑定) 同样惰性解析。叶子间互引走全路径直跨
(``specs._layoutqc_*``), 不经本门面。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解，F401 以 __all__ re-export 豁免;
    # 私有惰性名不在此列 (不在 __all__, 无 F822 需，导入反吃 F401)。
    import json
    import re
    import statistics
    import subprocess
    from collections import Counter
    from contextlib import suppress
    from pathlib import Path
    from typing import Final

    from specs._layoutqc_assemble import qc_paper
    from specs._layoutqc_thresh import (
        BLANK_INK_MAX,
        BROKEN_BARE_W,
        BROKEN_REFS_MIN,
        CURVES_INK_MIN,
        DEGEN_FFFD_FUSE,
        DEGEN_NGRAM,
        DEGEN_NGRAM_MAX,
        DEGEN_PERIODIC_MIN_LINES,
        EMPTY_PAGE_CHARS,
        EMPTY_PAGE_MAX,
        FLOAT_OVERSIZE_WARN_PT,
        FRONTMATTER_PAGES,
        HEADER_LOST_FRAC,
        HEADER_MIN_FRAC,
        HEADER_ZONE_FRAC,
        INK_DROP_RATIO,
        INK_SELF_OUTLIER,
        INKBLOB_CC_MIN,
        KEEP_DPI,
        KEEP_TIMEOUT,
        MARGIN_BREACH_MIN,
        MARGIN_BREACH_PT,
        OVERFULL_COUNT,
        OVERFULL_COUNT_MIN_PT,
        OVERFULL_MAX_PT,
        OVERFULL_VBOX_FLOOR_PT,
        OVERLAP_GRAZE_HI,
        OVERLAP_GRAZE_IY,
        OVERLAP_IOU,
        OVERLAP_MIN_PAIRS,
        PAGE_RATIO_HI,
        PAGE_RATIO_LO,
        POPPLER_TIMEOUT,
        PT2BP,
        RASTER_DPI,
        RASTER_TIMEOUT,
        RESIDUAL_EN_FURNITURE,
        RESIDUAL_EN_HEAVY_FRAC,
        RESIDUAL_EN_MASS_LINES,
        RESIDUAL_EN_MIN_FRAC,
        RESIDUAL_EN_MIN_LINES,
        SKELETON_LCS_MIN,
        TABLE_RULE_LOST,
        TOFU_MIN_PAGE,
        VOID_FRAC_MIN,
        VOID_FRAME_ART_MIN,
        VOID_FRAME_MIN_FRAC,
        VOID_INT_INK_MIN,
        WIDOW_INK_MAX,
    )
    from texlate.compile.marks import (
        compare_marks,
        env_inventory,
        env_sequence,
        parse_txlm,
    )
    from texlate.textutil import VERBATIM_ENVS

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_layoutqc_assemble": (
        "_tier_of",
        "qc_paper",
    ),
    "_layoutqc_geocheck": (
        "_bbox_pages",
        "_bbox_pages_mupdf",
        "_bbox_scan",
        "_math_tok",
        "_page_frames",
        "_page_word_stats",
        "_sym_tok",
        "_textblock",
        "_word_overlap_pairs",
        "_zh_tok",
    ),
    "_layoutqc_logcheck": (
        "_frontmatter_lines",
        "_logscan",
    ),
    "_layoutqc_markcheck": ("_marks_scan",),
    "_layoutqc_pagekit": (
        "_folio_val",
        "_run",
        "_struct_head",
        "_verso_blank",
    ),
    "_layoutqc_rastercheck": (
        "_images_per_page",
        "_raster_pages",
        "_raster_scan",
    ),
    "_layoutqc_textcheck": (
        "_bib_cluster_cut",
        "_fwd_anchor_cluster",
        "_lcs",
        "_plain_scan",
        "_refs_cut",
        "_skeleton",
        "_tail_bib_cluster",
    ),
    "_layoutqc_thresh": (
        "BLANK_INK_MAX",
        "BROKEN_BARE_W",
        "BROKEN_REFS_MIN",
        "CURVES_INK_MIN",
        "DEGEN_FFFD_FUSE",
        "DEGEN_NGRAM",
        "DEGEN_NGRAM_MAX",
        "DEGEN_PERIODIC_MIN_LINES",
        "EMPTY_PAGE_CHARS",
        "EMPTY_PAGE_MAX",
        "FLOAT_OVERSIZE_WARN_PT",
        "FRONTMATTER_PAGES",
        "HEADER_LOST_FRAC",
        "HEADER_MIN_FRAC",
        "HEADER_ZONE_FRAC",
        "INKBLOB_CC_MIN",
        "INK_DROP_RATIO",
        "INK_SELF_OUTLIER",
        "KEEP_DPI",
        "KEEP_TIMEOUT",
        "MARGIN_BREACH_MIN",
        "MARGIN_BREACH_PT",
        "OVERFULL_COUNT",
        "OVERFULL_COUNT_MIN_PT",
        "OVERFULL_MAX_PT",
        "OVERFULL_VBOX_FLOOR_PT",
        "OVERLAP_GRAZE_HI",
        "OVERLAP_GRAZE_IY",
        "OVERLAP_IOU",
        "OVERLAP_MIN_PAIRS",
        "PAGE_RATIO_HI",
        "PAGE_RATIO_LO",
        "POPPLER_TIMEOUT",
        "PT2BP",
        "RASTER_DPI",
        "RASTER_TIMEOUT",
        "RESIDUAL_EN_FURNITURE",
        "RESIDUAL_EN_HEAVY_FRAC",
        "RESIDUAL_EN_MASS_LINES",
        "RESIDUAL_EN_MIN_FRAC",
        "RESIDUAL_EN_MIN_LINES",
        "SKELETON_LCS_MIN",
        "TABLE_RULE_LOST",
        "TOFU_MIN_PAGE",
        "VOID_FRAME_ART_MIN",
        "VOID_FRAME_MIN_FRAC",
        "VOID_FRAC_MIN",
        "VOID_INT_INK_MIN",
        "WIDOW_INK_MAX",
        "_ASCII_LINE_RX",
        "_ASCII_RUN_GAP",
        "_ASCII_RUN_MIN",
        "_BIB_AY_RX",
        "_BIB_CORRO_RX",
        "_BIB_ID_RX",
        "_BIB_LINE_RX",
        "_BIB_MARK_RX",
        "_BIB_NUM_RX",
        "_BIB_TAGNUM_RX",
        "_BLANKPAGE_RX",
        "_BROKEN_BRK_RX",
        "_BROKEN_REF_RX",
        "_CJK_PUNCT_L",
        "_CJK_PUNCT_R",
        "_CJK_RX",
        "_DIGIT_RX",
        "_FLOAT_FIT_RX",
        "_FLOAT_LOST_RX",
        "_FLOAT_OVERSIZE_RX",
        "_FOLIO_RX",
        "_FRAME_CLUSTER_MAX",
        "_HARD_SIGS",
        "_INFO_SIGS",
        "_MATH_RX",
        "_NEWLABEL_RX",
        "_NONCHAR_RX",
        "_NORM_RX",
        "_OUTPUT_ACTIVE_RX",
        "_OVERFULL_LINE_RX",
        "_OVERFULL_RX",
        "_PERIODIC_RX",
        "_RASTER_CHILD",
        "_RASTER_PY",
        "_REFS_HEAD_RX",
        "_ROMAN_DIGIT",
        "_SKELETON_RX",
        "_STRUCT_HEAD_RX",
        "_TEX_CMD_RX",
        "_TEX_HAY_MAX",
        "_TITLE_ARG_RX",
        "_UNDEF_KEY_RX",
        "_UNDEF_WHITE_RX",
        "_VERB_ENV_RX",
        "_WARN_SIGS",
        "_WORD_CHAR_RX",
        "_WORD_RX",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# HEAD 单件期模块属性面——stdlib 模块名与 texlate 顶层绑定也按名惰性解析，
# ``_layoutqc.re``/``_layoutqc.parse_txlm`` 等读面 (含 setattr 型 monkeypatch
# 缝，patch 落在共享 module 对象上) 与拆分前逐名等价。
_STDLIB_MODS = ("json", "re", "statistics", "subprocess")
_EXTRA_BINDINGS = {
    "Counter": "collections",
    "Final": "typing",
    "Path": "pathlib",
    "suppress": "contextlib",
}
_TEXLATE_EXPORTS = {
    "_MARK_ENVS": "texlate.compile.marks",
    "_keep_verbatim_run": "texlate.textutil",
    "VERBATIM_ENVS": "texlate.textutil",
    "compare_marks": "texlate.compile.marks",
    "env_inventory": "texlate.compile.marks",
    "env_sequence": "texlate.compile.marks",
    "parse_txlm": "texlate.compile.marks",
}

# 字面列表——拆分前 ``import *`` 面 (无 __all__ 期全量非下划线名) 逐名保留;
# 私有名经 _LAZY 进属性读面不进 __all__。ruff F401 re-export 判定要静态
# __all__; ``_export_drift`` 是三表同步闸。
__all__ = [
    "BLANK_INK_MAX",
    "BROKEN_BARE_W",
    "BROKEN_REFS_MIN",
    "CURVES_INK_MIN",
    "DEGEN_FFFD_FUSE",
    "DEGEN_NGRAM",
    "DEGEN_NGRAM_MAX",
    "DEGEN_PERIODIC_MIN_LINES",
    "EMPTY_PAGE_CHARS",
    "EMPTY_PAGE_MAX",
    "FLOAT_OVERSIZE_WARN_PT",
    "FRONTMATTER_PAGES",
    "HEADER_LOST_FRAC",
    "HEADER_MIN_FRAC",
    "HEADER_ZONE_FRAC",
    "INKBLOB_CC_MIN",
    "INK_DROP_RATIO",
    "INK_SELF_OUTLIER",
    "KEEP_DPI",
    "KEEP_TIMEOUT",
    "MARGIN_BREACH_MIN",
    "MARGIN_BREACH_PT",
    "OVERFULL_COUNT",
    "OVERFULL_COUNT_MIN_PT",
    "OVERFULL_MAX_PT",
    "OVERFULL_VBOX_FLOOR_PT",
    "OVERLAP_GRAZE_HI",
    "OVERLAP_GRAZE_IY",
    "OVERLAP_IOU",
    "OVERLAP_MIN_PAIRS",
    "PAGE_RATIO_HI",
    "PAGE_RATIO_LO",
    "POPPLER_TIMEOUT",
    "PT2BP",
    "RASTER_DPI",
    "RASTER_TIMEOUT",
    "RESIDUAL_EN_FURNITURE",
    "RESIDUAL_EN_HEAVY_FRAC",
    "RESIDUAL_EN_MASS_LINES",
    "RESIDUAL_EN_MIN_FRAC",
    "RESIDUAL_EN_MIN_LINES",
    "SKELETON_LCS_MIN",
    "TABLE_RULE_LOST",
    "TOFU_MIN_PAGE",
    "VERBATIM_ENVS",
    "VOID_FRAC_MIN",
    "VOID_FRAME_ART_MIN",
    "VOID_FRAME_MIN_FRAC",
    "VOID_INT_INK_MIN",
    "WIDOW_INK_MAX",
    "Counter",
    "Final",
    "Path",
    "compare_marks",
    "env_inventory",
    "env_sequence",
    "json",
    "parse_txlm",
    "qc_paper",
    "re",
    "statistics",
    "subprocess",
    "suppress",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性 / stdlib 绑定 / texlate 顶层名。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"specs.{leaf}"), name)
        globals()[name] = value
        return value
    if name in _STDLIB_MODS:
        value = importlib.import_module(name)
        globals()[name] = value
        return value
    extra = _EXTRA_BINDINGS.get(name)
    if extra is not None:
        value = getattr(importlib.import_module(extra), name)
        globals()[name] = value
        return value
    texmod = _TEXLATE_EXPORTS.get(name)
    if texmod is not None:
        value = getattr(importlib.import_module(texmod), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(
        set(globals())
        | set(__all__)
        | set(_LAZY)
        | set(_STDLIB_MODS)
        | set(_EXTRA_BINDINGS)
        | set(_TEXLATE_EXPORTS)
    )


def _export_drift() -> list[str]:
    """``_LAZY``/``__all__``/叶子实体三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。逐名 ``getattr`` 实解：叶子断链
    (``_LEAF_EXPORTS`` 配名叶子不提供) 与幽灵条 (解析不到任何叶子或绑
    定) 在此曝，是首访 ``AttributeError`` 唯一的提前闸。审计实载全部
    叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = []
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    for name in _LAZY:
        try:
            getattr(mod, name)
        except Exception as exc:
            drift.append(f"_LEAF_EXPORTS entry {name} does not resolve: {exc}")
    for name in __all__:
        if name in _LAZY:
            continue  # 已解
        try:
            getattr(mod, name)
        except Exception as exc:
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and name not in _STDLIB_MODS
        and name not in _EXTRA_BINDINGS
        and name not in _TEXLATE_EXPORTS
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
