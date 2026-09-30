r"""builtins.layoutfix — qc-wanted 版面/字符面修复原语 (impl-builtins lane)。

``warn_overfull`` 驱动的版面钳 builtin 族 (qc_replay 2026-09-27 普查):

- ``tabular_fit``: 表族盒宽钳到 ``\linewidth`` —— 源级跨度
  ``adjustbox{max width=\linewidth,max totalheight=\textheight}`` 包
  (inject 侧 ``TABLE_FITTING`` 成对钩法 0930 拔除后本 builtin 是表族
  钳宽唯一面) + 可断页表族 (longtable 系) env/begin 局部收缩
  + 列声明 ``p{\textwidth}``/表域负 ``\hspace``/绝对宽 minipage 文本臂。
- ``math_run_break``: 行内数学断点 penalty 清零 + para_loosen 强剂量。
- ``display_math_shrink``: 编号对齐族 env/before 字号+muskip 收缩 +
  ``$$``/``\[`` 无编号 display ``\adjustbox`` 包。
- ``gfx_width_clamp``: ``\includegraphics`` ``max width`` 钳 (adjustbox
  export 直通) + 相邻图组宽和收缩 + 字面超宽 ``width=N\linewidth`` 改写。
- ``fffd_context_fix``: 字面 U+FFFD 邻域分派替换 (CJK 间 ``{}``/页码
  ``--``/拉丁名断点 ``'``/``\'``/兜底 ``{}``) —— 替掉 char_table
  ``fffd_repl('-')`` 的无语境连字符 (``许-多``/``C-orcoles`` 错修实证)。

注册表接线在 ``builtins/__init__.py`` 门面 (``_LEAF_EXPORTS``/``_TRANSFORM_KEYS``/
``__all__``/TYPE_CHECKING 四表) —— 本叶只供函数本体, 名表合同即注册键。

w8 拆叶: 实现体按修复域拆进七个 ``_lfx_*`` 私有兄弟叶, 本文件化纯
PEP 562 惰性门面 (同 ``csfix``/``gfx_missing`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子, ``__getattr__`` 首访解析并缓存,
``layoutfix.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意: patch 叶子不 patch 门面 —— ``layoutfix.name``
读到的恒是叶子对象, 但 ``setattr(layoutfix, ...)`` 只遮蔽门面不改
叶子内部互引。叶子间互引走全路径直跨
(``texlate.compile.fixloop.builtins._lfx_<叶>``), 不经本门面。

叶谱: ``layoutfix.core`` env 跨度/overfull 幅度/编辑回放通用件 /
``layoutfix.tabular`` ``tabular_fit``+``legacy_clamp_purge`` 主臂 /
``layoutfix.mathrun`` ``math_run_break`` / ``layoutfix.display``
``display_math_shrink`` / ``layoutfix.gfxw`` ``gfx_width_clamp`` /
``layoutfix.fffd`` ``fffd_context_fix`` / ``layoutfix.secskip``
``section_skip_floor``。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.builtins.layoutfix.core import (
        _ENV_TOKEN_RX,
        _OVF_PT_RX,
        _env_spans,
        _in_spans,
        _max_overfull_pt,
        _span_marks,
        bisect_right,
        re,
    )
    from texlate.compile.fixloop.builtins.layoutfix.display import (
        _DD_BRACKET_RX,
        _DD_DOLLAR_RX,
        _DISP_ANY_RX,
        _DISP_SHRINK_ENVS,
        _display_snippet,
        _display_wrap_edits,
        display_math_shrink,
    )
    from texlate.compile.fixloop.builtins.layoutfix.fffd import (
        _FFFD_RUN_RX,
        _fffd_repl,
        _fffd_text_edits,
        fffd_context_fix,
        is_cjk_cp,
    )
    from texlate.compile.fixloop.builtins.layoutfix.gfxw import (
        _GFX_CALL_RX,
        _GFX_GLUE_RX,
        _GFX_PAIR_MIN,
        _GFX_PAIR_SUM,
        _RELWIDE_RX,
        _ensure_adjustbox_export,
        _gfx_call_edits,
        _gfx_pair_edits,
        _gfx_relwide_edits,
        _pkg_list_re,
        gfx_width_clamp,
    )
    from texlate.compile.fixloop.builtins.layoutfix.mathrun import (
        _LOOSEN_MARK,
        _LOOSEN_UP_RX,
        _MATHRUN_SNIPPET,
        _MATHRUN_STRONG,
        math_run_break,
    )
    from texlate.compile.fixloop.builtins.layoutfix.secskip import (
        _AFTERSKIP_FLOOR_PT,
        _AFTERSKIP_TARGET,
        _DIMEN_PT,
        _STARTSEC_RX,
        _section_skip_floor_text,
        section_skip_floor,
    )
    from texlate.compile.fixloop.builtins.layoutfix.tabular import (
        _LEGACY_CLAMP_RX,
        _LEGACY_HOOK_RX,
        _MATH_ENVS,
        _MATH_INLINE_RX,
        _MINIPAGE_CLAMP_PT,
        _MINIPAGE_ENV_RX,
        _MINIPAGE_RX,
        _MINIPAGE_UNIT_PT,
        _PCOL_KEEP_FACTOR,
        _PCOL_SPEC_RX,
        _TAB_BOX_ENVS,
        _TAB_FLOW_ANY_RX,
        _TAB_FLOW_ENVS,
        _TAB_NEGHSPACE_RX,
        _TAB_SPAN_ENVS,
        Any,
        _fixloop_log,
        _inject_before_begindoc,
        _is_live,
        _map_tex_files,
        _math_marks,
        _splice,
        _strip_legacy_clamp,
        _tabular_box_edits,
        _tabular_snippet,
        _tabular_text_edits,
        legacy_clamp_purge,
        mask_tex,
        tabular_fit,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "core": (
        "_ENV_TOKEN_RX",
        "_OVF_PT_RX",
        "_env_spans",
        "_in_spans",
        "_max_overfull_pt",
        "_span_marks",
        "bisect_right",
        "re",
    ),
    "display": (
        "_DD_BRACKET_RX",
        "_DD_DOLLAR_RX",
        "_DISP_ANY_RX",
        "_DISP_SHRINK_ENVS",
        "_display_snippet",
        "_display_wrap_edits",
        "display_math_shrink",
    ),
    "fffd": (
        "_FFFD_RUN_RX",
        "_fffd_repl",
        "_fffd_text_edits",
        "fffd_context_fix",
        "is_cjk_cp",
    ),
    "gfxw": (
        "_GFX_CALL_RX",
        "_GFX_GLUE_RX",
        "_GFX_PAIR_MIN",
        "_GFX_PAIR_SUM",
        "_RELWIDE_RX",
        "_ensure_adjustbox_export",
        "_gfx_call_edits",
        "_gfx_pair_edits",
        "_gfx_relwide_edits",
        "_pkg_list_re",
        "gfx_width_clamp",
    ),
    "mathrun": (
        "_LOOSEN_MARK",
        "_LOOSEN_UP_RX",
        "_MATHRUN_SNIPPET",
        "_MATHRUN_STRONG",
        "math_run_break",
    ),
    "secskip": (
        "_AFTERSKIP_FLOOR_PT",
        "_AFTERSKIP_TARGET",
        "_DIMEN_PT",
        "_STARTSEC_RX",
        "_section_skip_floor_text",
        "section_skip_floor",
    ),
    "tabular": (
        "Any",
        "_LEGACY_CLAMP_RX",
        "_LEGACY_HOOK_RX",
        "_MATH_ENVS",
        "_MATH_INLINE_RX",
        "_MINIPAGE_CLAMP_PT",
        "_MINIPAGE_ENV_RX",
        "_MINIPAGE_RX",
        "_MINIPAGE_UNIT_PT",
        "_PCOL_KEEP_FACTOR",
        "_PCOL_SPEC_RX",
        "_TAB_BOX_ENVS",
        "_TAB_FLOW_ANY_RX",
        "_TAB_FLOW_ENVS",
        "_TAB_NEGHSPACE_RX",
        "_TAB_SPAN_ENVS",
        "_fixloop_log",
        "_inject_before_begindoc",
        "_is_live",
        "_map_tex_files",
        "_math_marks",
        "_splice",
        "_strip_legacy_clamp",
        "_tabular_box_edits",
        "_tabular_snippet",
        "_tabular_text_edits",
        "legacy_clamp_purge",
        "mask_tex",
        "tabular_fit",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "_AFTERSKIP_FLOOR_PT",
    "_AFTERSKIP_TARGET",
    "_DD_BRACKET_RX",
    "_DD_DOLLAR_RX",
    "_DIMEN_PT",
    "_DISP_ANY_RX",
    "_DISP_SHRINK_ENVS",
    "_ENV_TOKEN_RX",
    "_FFFD_RUN_RX",
    "_GFX_CALL_RX",
    "_GFX_GLUE_RX",
    "_GFX_PAIR_MIN",
    "_GFX_PAIR_SUM",
    "_LEGACY_CLAMP_RX",
    "_LEGACY_HOOK_RX",
    "_LOOSEN_MARK",
    "_LOOSEN_UP_RX",
    "_MATHRUN_SNIPPET",
    "_MATHRUN_STRONG",
    "_MATH_ENVS",
    "_MATH_INLINE_RX",
    "_MINIPAGE_CLAMP_PT",
    "_MINIPAGE_ENV_RX",
    "_MINIPAGE_RX",
    "_MINIPAGE_UNIT_PT",
    "_OVF_PT_RX",
    "_PCOL_KEEP_FACTOR",
    "_PCOL_SPEC_RX",
    "_RELWIDE_RX",
    "_STARTSEC_RX",
    "_TAB_BOX_ENVS",
    "_TAB_FLOW_ANY_RX",
    "_TAB_FLOW_ENVS",
    "_TAB_NEGHSPACE_RX",
    "_TAB_SPAN_ENVS",
    "Any",
    "_display_snippet",
    "_display_wrap_edits",
    "_ensure_adjustbox_export",
    "_env_spans",
    "_fffd_repl",
    "_fffd_text_edits",
    "_fixloop_log",
    "_gfx_call_edits",
    "_gfx_pair_edits",
    "_gfx_relwide_edits",
    "_in_spans",
    "_inject_before_begindoc",
    "_is_live",
    "_map_tex_files",
    "_math_marks",
    "_max_overfull_pt",
    "_pkg_list_re",
    "_section_skip_floor_text",
    "_span_marks",
    "_splice",
    "_strip_legacy_clamp",
    "_tabular_box_edits",
    "_tabular_snippet",
    "_tabular_text_edits",
    "bisect_right",
    "display_math_shrink",
    "fffd_context_fix",
    "gfx_width_clamp",
    "is_cjk_cp",
    "legacy_clamp_purge",
    "mask_tex",
    "math_run_break",
    "re",
    "section_skip_floor",
    "tabular_fit",
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
