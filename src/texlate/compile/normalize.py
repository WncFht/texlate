r"""归一化层：pdfTeX 时代源码 → XeTeX/tectonic 可编译形态的无条件手术。

docs/spec/compile.md 十二项清单逐条实现；**条件手术（microtype_off/times→newtx 等错误
驱动修复）留给 fixloop，两边不得重复改同一处**（docs/spec/compile.md 分工铁律）。

所有定位打在 :func:`mask.visible_tex` 遮蔽视图上，编辑逆序回放到原文，
删除类编辑补回换行保持行号稳定（编译错误可回溯源文件行号）。

移植自 texglot `app/compiler.py`（normalize_engine 系），实证依据见
docs/research/latex/texglot-patterns.md §1.1–1.6。

支持件字节转码/净化（PS 注释/aux/intermediate/catch-all）与系统包遮蔽
两切面已拆至 sibling 模块 ``transcode.py``/``shadow.py``，本件回引。

god-split: 实现体按域拆进同包 8 叶——``normalize_text``（清单 1–10 文件内
文本手术：comment 行尾/float 位置/pdfTeX 特性/px 单位/手工断词/编码剥离/
驱动 token/legacy CJK）、``normalize_blocks``（PIXEL/XETEX/TECTONIC 兼容
前导块 + XETEX_EARLY_DEFS ``\documentclass`` 缝注入）、``normalize_latin``
（显式 Type1 拉丁字体 → TeX Gyre Unicode 等价物）、``normalize_guard``
（字节面前置守卫：NUL 探测窗/Mac 引导垃圾剥除）、``normalize_bbl``
（bundled .bbl 书目替换 + ``\auto@bib`` 解除）、``normalize_paths``
（``../`` 越界引用 rebase + source_path_violations 审计）、
``normalize_junk``（bundled 垃圾件 stub 覆写）、``normalize_main``
（``normalize_engine``/``_normalize_tex_files``/``normalize_project``
主编排 + ``_DOC_SOURCE_SUFFIXES`` + ``log``）。本文件是 PEP 562 惰性门面
（同 ``l0``/``seqpos/__init__`` 形制）——平名经 ``_LEAF_EXPORTS`` 映射回
叶子，``__getattr__`` 首访解析并缓存，``normalize.X`` 公共面与
``from ... import X``/``normalize._x`` 属性读面不变。各叶 ``log`` 钉死
``texlate.compile.normalize``——消息面（``record.name``）不变。叶子间
互引走全路径直跨，不经本门面。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.normalize_bbl import (
        _AUTOBIB_DISARM,
        CMD_BOUNDARY,
        decode_tex,
        use_bundled_bibliography,
    )
    from texlate.compile.normalize_blocks import (
        PIXEL_COMPATIBILITY,
        SUBDOC_CHILD_RX,
        TECTONIC_FONT_COMPATIBILITY,
        XETEX_COMPATIBILITY,
        XETEX_EARLY_DEFS,
        _splice_after_seams,
        _splice_early_defs,
        annotations,
        find_docclass_ends,
        iter_depth0,
    )
    from texlate.compile.normalize_guard import (
        _LEAD_ANCHOR_RX,
        _LEAD_JUNK_WINDOW,
        _PROLOGUE_NUL_WINDOW,
        _prologue_ok,
        _strip_lead_junk,
    )
    from texlate.compile.normalize_junk import (
        JUNK_FILE_MARKERS,
        JUNK_FILE_STUBS,
        _neutralize_junk_files,
    )
    from texlate.compile.normalize_latin import (
        DOCCLASS_OPTS_RX,
        LEGACY_LATIN_FAMILIES,
        _latin_family_block,
        _latin_font_edits,
        _tex_sources,
        prepare_legacy_latin_fonts,
    )
    from texlate.compile.normalize_main import (
        _DOC_SOURCE_SUFFIXES,
        _hidden_path,
        _normalize_tex_files,
        _record_verdict,
        _shadow_broken_system_packages,
        _tar_disguised,
        _transcode_support_files,
        decode_tex_with,
        log,
        logging,
        normalize_engine,
        normalize_project,
    )
    from texlate.compile.normalize_paths import (
        AUX_BIB_SUFFIXES,
        TEX_SOURCE_SUFFIXES,
        Path,
        _apply_rebase_edits,
        _is_within,
        _iter_files,
        _read_tex,
        _read_tex_path,
        os,
        rebase_project_paths,
        safe_is_file,
        safe_resolve,
        source_path_violations,
    )
    from texlate.compile.normalize_text import (
        _DRIVER_SCOPE_RX,
        _DRIVER_TOKEN_RX,
        _DRIVER_TOKENS,
        _MANUAL_HYPHEN_RX,
        _TABBING_ENV_RX,
        _USEPACKAGE_NAMES_RX,
        BEGIN_DOC_RX,
        PDFTEX_OUTPUT_SETTINGS,
        Final,
        _filter_usepackage_names,
        apply_edits,
        group_end,
        normalize_comment_terminators,
        normalize_float_positions,
        normalize_legacy_cjk,
        normalize_manual_hyphens,
        normalize_pdf_primitives,
        normalize_pdftex_features,
        normalize_pixel_dimensions,
        re,
        strip_input_encodings,
        visible_tex,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "normalize_bbl": (
        "CMD_BOUNDARY",
        "_AUTOBIB_DISARM",
        "decode_tex",
        "use_bundled_bibliography",
    ),
    "normalize_blocks": (
        "PIXEL_COMPATIBILITY",
        "SUBDOC_CHILD_RX",
        "TECTONIC_FONT_COMPATIBILITY",
        "XETEX_COMPATIBILITY",
        "XETEX_EARLY_DEFS",
        "_splice_after_seams",
        "_splice_early_defs",
        "annotations",
        "find_docclass_ends",
        "iter_depth0",
    ),
    "normalize_guard": (
        "_LEAD_ANCHOR_RX",
        "_LEAD_JUNK_WINDOW",
        "_PROLOGUE_NUL_WINDOW",
        "_prologue_ok",
        "_strip_lead_junk",
    ),
    "normalize_junk": (
        "JUNK_FILE_MARKERS",
        "JUNK_FILE_STUBS",
        "_neutralize_junk_files",
    ),
    "normalize_latin": (
        "DOCCLASS_OPTS_RX",
        "LEGACY_LATIN_FAMILIES",
        "_latin_family_block",
        "_latin_font_edits",
        "_tex_sources",
        "prepare_legacy_latin_fonts",
    ),
    "normalize_main": (
        "TYPE_CHECKING",
        "_DOC_SOURCE_SUFFIXES",
        "_hidden_path",
        "_normalize_tex_files",
        "_record_verdict",
        "_shadow_broken_system_packages",
        "_tar_disguised",
        "_transcode_support_files",
        "decode_tex_with",
        "log",
        "logging",
        "normalize_engine",
        "normalize_project",
    ),
    "normalize_paths": (
        "AUX_BIB_SUFFIXES",
        "TEX_SOURCE_SUFFIXES",
        "Path",
        "_apply_rebase_edits",
        "_is_within",
        "_iter_files",
        "_read_tex",
        "_read_tex_path",
        "os",
        "rebase_project_paths",
        "safe_is_file",
        "safe_resolve",
        "source_path_violations",
    ),
    "normalize_text": (
        "BEGIN_DOC_RX",
        "PDFTEX_OUTPUT_SETTINGS",
        "Final",
        "_DRIVER_SCOPE_RX",
        "_DRIVER_TOKENS",
        "_DRIVER_TOKEN_RX",
        "_MANUAL_HYPHEN_RX",
        "_TABBING_ENV_RX",
        "_USEPACKAGE_NAMES_RX",
        "_filter_usepackage_names",
        "apply_edits",
        "group_end",
        "normalize_comment_terminators",
        "normalize_float_positions",
        "normalize_legacy_cjk",
        "normalize_manual_hyphens",
        "normalize_pdf_primitives",
        "normalize_pdftex_features",
        "normalize_pixel_dimensions",
        "re",
        "strip_input_encodings",
        "visible_tex",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "AUX_BIB_SUFFIXES",
    "BEGIN_DOC_RX",
    "CMD_BOUNDARY",
    "DOCCLASS_OPTS_RX",
    "JUNK_FILE_MARKERS",
    "JUNK_FILE_STUBS",
    "LEGACY_LATIN_FAMILIES",
    "PDFTEX_OUTPUT_SETTINGS",
    "PIXEL_COMPATIBILITY",
    "SUBDOC_CHILD_RX",
    "TECTONIC_FONT_COMPATIBILITY",
    "TEX_SOURCE_SUFFIXES",
    "TYPE_CHECKING",
    "XETEX_COMPATIBILITY",
    "XETEX_EARLY_DEFS",
    "_AUTOBIB_DISARM",
    "_DOC_SOURCE_SUFFIXES",
    "_DRIVER_SCOPE_RX",
    "_DRIVER_TOKENS",
    "_DRIVER_TOKEN_RX",
    "_LEAD_ANCHOR_RX",
    "_LEAD_JUNK_WINDOW",
    "_MANUAL_HYPHEN_RX",
    "_PROLOGUE_NUL_WINDOW",
    "_TABBING_ENV_RX",
    "_USEPACKAGE_NAMES_RX",
    "Final",
    "Path",
    "_apply_rebase_edits",
    "_filter_usepackage_names",
    "_hidden_path",
    "_is_within",
    "_iter_files",
    "_latin_family_block",
    "_latin_font_edits",
    "_neutralize_junk_files",
    "_normalize_tex_files",
    "_prologue_ok",
    "_read_tex",
    "_read_tex_path",
    "_record_verdict",
    "_shadow_broken_system_packages",
    "_splice_after_seams",
    "_splice_early_defs",
    "_strip_lead_junk",
    "_tar_disguised",
    "_tex_sources",
    "_transcode_support_files",
    "annotations",
    "apply_edits",
    "decode_tex",
    "decode_tex_with",
    "find_docclass_ends",
    "group_end",
    "iter_depth0",
    "log",
    "logging",
    "normalize_comment_terminators",
    "normalize_engine",
    "normalize_float_positions",
    "normalize_legacy_cjk",
    "normalize_manual_hyphens",
    "normalize_pdf_primitives",
    "normalize_pdftex_features",
    "normalize_pixel_dimensions",
    "normalize_project",
    "os",
    "prepare_legacy_latin_fonts",
    "re",
    "rebase_project_paths",
    "safe_is_file",
    "safe_resolve",
    "source_path_violations",
    "strip_input_encodings",
    "use_bundled_bibliography",
    "visible_tex",
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
