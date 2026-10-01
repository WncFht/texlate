r"""builtins.gfx_missing — missing_graphic 缺图域修复原语 (C3 再拆分叶子)。

``builtins.graphics`` 同源分叶: 转换/驱动预检族 (eps→pdf 全量转换、
svg/xbb/pdf-asset、pstricks 预检) 留原叶, 本叶收「引用在盘但引擎喊缺 /
真缺件占位」一族 —— ci 大小写改名 ``graphic_case_link`` / 在盘拒载分级
修复 ``graphic_repair`` / ``\includepdf`` 缺件占位
``includepdf_missing_stub`` / 真缺件格式占位 ``graphic_missing_placeholder``
(含宏间接 ``#N`` 引用复核与 halt_on_error 源侧枚举) / raster-伪装
``.pdf`` 改名 ``raster_pdf_rename`` / xdvipdfmx 驱动期缺图
``driver_missing_image_stub``。

共享原语 (``_iter_project_files`` 排除面扫描 / ``_norm_graphic_name`` /
``_EPS_EXTS`` / ``_NUMERIC_EXT_RE`` / ``_try_gs_redistill`` gs 重蒸馏 /
``_pdf_asset_targets``) 仍留 ``builtins.graphics`` 单源, 叶子顶行回引
—— 依赖单向 (gfx_missing 叶 → graphics) 无环; 反向
``builtins.graphics.X`` 读面经彼侧 ``__getattr__`` 惰性回引本叶,
``builtins`` 门面 ``_LAZY`` 表与 ``from builtins.graphics import X``
测试面不需改。

C5 拆叶: 实现体按修复臂拆进同包九叶, 本文件化纯
PEP 562 惰性门面 (同 ``fixloop/engine`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子, ``__getattr__`` 首访解析并缓存,
``gfx_missing.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意: patch 叶子不 patch 门面 —— ``gfx_missing.name``
读到的恒是叶子对象, 但 ``setattr(gfx_missing, ...)`` 只遮蔽门面不改
叶子内部互引。叶子间互引走全路径直跨
(``texlate.compile.fixloop.builtins.gfx_missing.<叶>``), 不经本门面;
测试若 patch ``builtins.gfx_missing.<name>`` 面, 同此规则落对应叶子。

叶谱: ``gfx_missing.assets`` 占位字节资产 (EPS/PNG/PDF/JPEG) /
``gfx_missing.caselink`` ci 大小写改名 ``graphic_case_link`` /
``gfx_missing.repair`` 在盘拒载分级修复 ``graphic_repair`` /
``gfx_missing.incpdf`` ``\includepdf`` 缺件占位 / ``gfx_missing.refscan``
宏间接 ``#N`` 引用复核件 / ``gfx_missing.enum`` halt_on_error 源侧枚举 /
``gfx_missing.stub`` 真缺件格式占位 ``graphic_missing_placeholder`` /
``gfx_missing.raster`` raster-伪装 ``.pdf`` 改名 / ``gfx_missing.driver``
xdvipdfmx 驱动期缺图占位。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.builtins.gfx_missing.assets import (
        _EPS_PLACEHOLDER,
        _JPEG_PLACEHOLDER,
        _PDF_PLACEHOLDER,
        _PNG_PLACEHOLDER,
    )
    from texlate.compile.fixloop.builtins.gfx_missing.caselink import (
        _GRAPHIC_EXTS,
        _INCLUDE_GFX_RE,
        _INCLUDE_PDF_RE,
        _NUMERIC_EXT_RE,
        _debrace_sweep,
        _find_graphic_ci,
        _graphic_ref_hit,
        _iter_project_files,
        _norm_graphic_name,
        _rewrite_case_refs,
        graphic_case_link,
        safe_is_file,
    )
    from texlate.compile.fixloop.builtins.gfx_missing.driver import (
        _DRV_IMG_MISS_RE,
        driver_missing_image_stub,
    )
    from texlate.compile.fixloop.builtins.gfx_missing.enum import (
        _ENUM_ARG_BAD_RE,
        _GRAPHICSPATH_RE,
        _GSPATH_DIR_RE,
        _LOG_MISS_GFX_RE,
        _disk_hit,
        _enum_missing_graphics,
        _graphicspath_dirs,
        _ProjectScan,
    )
    from texlate.compile.fixloop.builtins.gfx_missing.incpdf import (
        _live_matches,
        includepdf_missing_stub,
    )
    from texlate.compile.fixloop.builtins.gfx_missing.raster import (
        _RASTER_MAGICS,
        _map_tex_files,
        _mislabeled_pdf_targets,
        _pdf_asset_targets,
        _rewrite_mislabeled_refs,
        _sniff_raster_ext,
        raster_pdf_rename,
    )
    from texlate.compile.fixloop.builtins.gfx_missing.refscan import (
        _EPS_KV_RE,
        _GFX_ARG_RE,
        _GFX_DEF_NC_RE,
        _GFX_DEF_PRIM_RE,
        _GFX_OPT_ARG_RE,
        _GFX_PARAM_REF_RE,
        _KV_FILE_RE,
        _gfx_call_args,
        _gfx_macro_templates,
        _gfx_resolve_hit,
        _gfx_template_items,
        _has_live_graphic_ref,
        _macro_graphic_ref_hit,
        mask_tex,
    )
    from texlate.compile.fixloop.builtins.gfx_missing.repair import (
        _opt_dim,
        _stub_graphic_refs,
        _try_gs_redistill,
        graphic_repair,
    )
    from texlate.compile.fixloop.builtins.gfx_missing.stub import (
        _EPS_EXTS,
        _fixloop_log,
        _stub_graphic_at,
        _stub_sweep,
        graphic_missing_placeholder,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "assets": (
        "_EPS_PLACEHOLDER",
        "_JPEG_PLACEHOLDER",
        "_PDF_PLACEHOLDER",
        "_PNG_PLACEHOLDER",
    ),
    "caselink": (
        "_GRAPHIC_EXTS",
        "_INCLUDE_GFX_RE",
        "_INCLUDE_PDF_RE",
        "_NUMERIC_EXT_RE",
        "_debrace_sweep",
        "_find_graphic_ci",
        "_graphic_ref_hit",
        "_iter_project_files",
        "_norm_graphic_name",
        "_rewrite_case_refs",
        "graphic_case_link",
        "safe_is_file",
    ),
    "driver": (
        "_DRV_IMG_MISS_RE",
        "driver_missing_image_stub",
    ),
    "enum": (
        "_ENUM_ARG_BAD_RE",
        "_GRAPHICSPATH_RE",
        "_GSPATH_DIR_RE",
        "_LOG_MISS_GFX_RE",
        "_ProjectScan",
        "_disk_hit",
        "_enum_missing_graphics",
        "_graphicspath_dirs",
    ),
    "incpdf": (
        "_live_matches",
        "includepdf_missing_stub",
    ),
    "raster": (
        "_RASTER_MAGICS",
        "_map_tex_files",
        "_mislabeled_pdf_targets",
        "_pdf_asset_targets",
        "_rewrite_mislabeled_refs",
        "_sniff_raster_ext",
        "raster_pdf_rename",
    ),
    "refscan": (
        "_EPS_KV_RE",
        "_GFX_ARG_RE",
        "_GFX_DEF_NC_RE",
        "_GFX_DEF_PRIM_RE",
        "_GFX_OPT_ARG_RE",
        "_GFX_PARAM_REF_RE",
        "_KV_FILE_RE",
        "_gfx_call_args",
        "_gfx_macro_templates",
        "_gfx_resolve_hit",
        "_gfx_template_items",
        "_has_live_graphic_ref",
        "_macro_graphic_ref_hit",
        "mask_tex",
    ),
    "repair": (
        "_opt_dim",
        "_stub_graphic_refs",
        "_try_gs_redistill",
        "graphic_repair",
    ),
    "stub": (
        "_EPS_EXTS",
        "_fixloop_log",
        "_stub_graphic_at",
        "_stub_sweep",
        "graphic_missing_placeholder",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "_DRV_IMG_MISS_RE",
    "_ENUM_ARG_BAD_RE",
    "_EPS_EXTS",
    "_EPS_KV_RE",
    "_EPS_PLACEHOLDER",
    "_GFX_ARG_RE",
    "_GFX_DEF_NC_RE",
    "_GFX_DEF_PRIM_RE",
    "_GFX_OPT_ARG_RE",
    "_GFX_PARAM_REF_RE",
    "_GRAPHICSPATH_RE",
    "_GRAPHIC_EXTS",
    "_GSPATH_DIR_RE",
    "_INCLUDE_GFX_RE",
    "_INCLUDE_PDF_RE",
    "_JPEG_PLACEHOLDER",
    "_KV_FILE_RE",
    "_LOG_MISS_GFX_RE",
    "_NUMERIC_EXT_RE",
    "_PDF_PLACEHOLDER",
    "_PNG_PLACEHOLDER",
    "_RASTER_MAGICS",
    "_ProjectScan",
    "_debrace_sweep",
    "_disk_hit",
    "_enum_missing_graphics",
    "_find_graphic_ci",
    "_fixloop_log",
    "_gfx_call_args",
    "_gfx_macro_templates",
    "_gfx_resolve_hit",
    "_gfx_template_items",
    "_graphic_ref_hit",
    "_graphicspath_dirs",
    "_has_live_graphic_ref",
    "_iter_project_files",
    "_live_matches",
    "_macro_graphic_ref_hit",
    "_map_tex_files",
    "_mislabeled_pdf_targets",
    "_norm_graphic_name",
    "_opt_dim",
    "_pdf_asset_targets",
    "_rewrite_case_refs",
    "_rewrite_mislabeled_refs",
    "_sniff_raster_ext",
    "_stub_graphic_at",
    "_stub_graphic_refs",
    "_stub_sweep",
    "_try_gs_redistill",
    "driver_missing_image_stub",
    "graphic_case_link",
    "graphic_missing_placeholder",
    "graphic_repair",
    "includepdf_missing_stub",
    "mask_tex",
    "raster_pdf_rename",
    "safe_is_file",
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
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
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
