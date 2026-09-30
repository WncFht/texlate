r"""builtins.common — fixloop builtins 跨域共享原语 (C3 builtins/__init__.py 拆分叶子)。

跨域 helper 单源: ``mask_tex`` 遮盖视图匹配 / 逐 tex 文件映射 / ``\\usepackage``
剥载 / ``\\documentclass`` 缝后注入 / pdfTeX 原语清单 (ruleset._FAMILY_TOKENS
与 pdftex_prim_polyfill 双侧消费)。只做 helper/常量, 不含注册表条目本体。

w8 拆叶: 实现体按域拆进十个 ``_common_*`` 私有兄弟叶, 本文件化纯
PEP 562 惰性门面 (同 ``csfix``/``gfx_missing`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子, ``__getattr__`` 首访解析并缓存,
``common.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意: patch 叶子不 patch 门面 —— ``common.name``
读到的恒是叶子对象, 但 ``setattr(common, ...)`` 只遮蔽门面不改
叶子内部互引。叶子间互引走全路径直跨
(``texlate.compile.fixloop.builtins._common_<叶>``), 不经本门面。

叶谱: ``_common_prims`` pdfTeX 原语清单 / ``_common_pkgload``
``\\usepackage`` 剥载 / ``_common_cslet`` ``\\let`` 清位件 /
``_common_misc`` 文本杂件 (ws/brace/utf8/advise) / ``_common_fprint``
注入指纹+标记写 / ``_common_sites`` 站点定位+逐文件映射 /
``_common_inject`` docclass/anchor/begindoc 注入 / ``_common_log``
fixloop log 读取+mc 解析 / ``_common_mc`` main-font CJK 计划表 /
``_common_tree`` wdir 指纹+工程文件枚举。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.builtins._common_cslet import (
        _AT_LETTER_POST,
        _AT_LETTER_PRE,
        _AT_LETTER_SEG,
        _UNDEF_MARK,
        _exact_restore_wrap,
        _let_cs,
        _undefine_cs,
    )
    from texlate.compile.fixloop.builtins._common_fprint import (
        _FINGERPRINT_RE,
        _LEGACY_INJECTED_HEADS,
        _fingerprint,
        _inject_write,
        _injected_state,
        _mark_injected,
        hashlib,
    )
    from texlate.compile.fixloop.builtins._common_inject import (
        BEGIN_DOC_RX,
        _inject_after_docclass,
        _inject_before_anchor,
        _inject_before_begindoc,
        cast,
        find_docclass_ends,
        iter_depth0,
    )
    from texlate.compile.fixloop.builtins._common_log import (
        _compile_log_text,
        _fixloop_log,
        _iter_log_candidates,
        _mc_parse_log,
        _mc_seen,
    )
    from texlate.compile.fixloop.builtins._common_mc import (
        _CJK_FONT_RE,
        _FB_FONT,
        _MATH_SHIM_CS,
        _MC_TABLE,
        _fb_font_body,
        _fb_preamble_lines,
        _mc_chr,
        _mc_hit,
        _mc_plan,
        _mc_table,
    )
    from texlate.compile.fixloop.builtins._common_misc import (
        _advise,
        _brace_end,
        _index_candidates,
        _read_utf8,
        _skip_ws,
    )
    from texlate.compile.fixloop.builtins._common_pkgload import (
        _LOAD_SITE_RE,
        _PKG_LOAD_HEAD_SRC,
        _PKG_LOAD_RE,
        _PKG_LOAD_SRC,
        _USE_RE,
        _drop_pkg_loads,
        _load_elems,
        _pkg_list_re,
        re,
    )
    from texlate.compile.fixloop.builtins._common_prims import PDFTEX_PRIMS
    from texlate.compile.fixloop.builtins._common_sites import (
        Path,
        PurePosixPath,
        _is_live,
        _live_matches,
        _map_tex_files,
        _resolve_site,
        _safe_rel,
        _splice,
        mask_tex,
        safe_rel,
    )
    from texlate.compile.fixloop.builtins._common_tree import (
        _PDF_SANITIZE_SKIP_DIRS,
        _fp_diff,
        _in_wdir,
        _wdir_fingerprint,
        _wdir_project_files,
        safe_is_file,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_common_cslet": (
        "_AT_LETTER_POST",
        "_AT_LETTER_PRE",
        "_AT_LETTER_SEG",
        "_UNDEF_MARK",
        "_exact_restore_wrap",
        "_let_cs",
        "_undefine_cs",
    ),
    "_common_fprint": (
        "_FINGERPRINT_RE",
        "_LEGACY_INJECTED_HEADS",
        "_fingerprint",
        "_inject_write",
        "_injected_state",
        "_mark_injected",
        "hashlib",
    ),
    "_common_inject": (
        "BEGIN_DOC_RX",
        "_inject_after_docclass",
        "_inject_before_anchor",
        "_inject_before_begindoc",
        "cast",
        "find_docclass_ends",
        "iter_depth0",
    ),
    "_common_log": (
        "_compile_log_text",
        "_fixloop_log",
        "_iter_log_candidates",
        "_mc_parse_log",
        "_mc_seen",
    ),
    "_common_mc": (
        "_CJK_FONT_RE",
        "_FB_FONT",
        "_MATH_SHIM_CS",
        "_MC_TABLE",
        "_fb_font_body",
        "_fb_preamble_lines",
        "_mc_chr",
        "_mc_hit",
        "_mc_plan",
        "_mc_table",
    ),
    "_common_misc": (
        "_advise",
        "_brace_end",
        "_index_candidates",
        "_read_utf8",
        "_skip_ws",
    ),
    "_common_pkgload": (
        "_LOAD_SITE_RE",
        "_PKG_LOAD_HEAD_SRC",
        "_PKG_LOAD_RE",
        "_PKG_LOAD_SRC",
        "_USE_RE",
        "_drop_pkg_loads",
        "_load_elems",
        "_pkg_list_re",
        "re",
    ),
    "_common_prims": ("PDFTEX_PRIMS",),
    "_common_sites": (
        "Path",
        "PurePosixPath",
        "_is_live",
        "_live_matches",
        "_map_tex_files",
        "_resolve_site",
        "_safe_rel",
        "_splice",
        "mask_tex",
        "safe_rel",
    ),
    "_common_tree": (
        "_PDF_SANITIZE_SKIP_DIRS",
        "_fp_diff",
        "_in_wdir",
        "_wdir_fingerprint",
        "_wdir_project_files",
        "safe_is_file",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集,
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "BEGIN_DOC_RX",
    "PDFTEX_PRIMS",
    "_AT_LETTER_POST",
    "_AT_LETTER_PRE",
    "_AT_LETTER_SEG",
    "_CJK_FONT_RE",
    "_FB_FONT",
    "_FINGERPRINT_RE",
    "_LEGACY_INJECTED_HEADS",
    "_LOAD_SITE_RE",
    "_MATH_SHIM_CS",
    "_MC_TABLE",
    "_PDF_SANITIZE_SKIP_DIRS",
    "_PKG_LOAD_HEAD_SRC",
    "_PKG_LOAD_RE",
    "_PKG_LOAD_SRC",
    "_UNDEF_MARK",
    "_USE_RE",
    "Path",
    "PurePosixPath",
    "_advise",
    "_brace_end",
    "_compile_log_text",
    "_drop_pkg_loads",
    "_exact_restore_wrap",
    "_fb_font_body",
    "_fb_preamble_lines",
    "_fingerprint",
    "_fixloop_log",
    "_fp_diff",
    "_in_wdir",
    "_index_candidates",
    "_inject_after_docclass",
    "_inject_before_anchor",
    "_inject_before_begindoc",
    "_inject_write",
    "_injected_state",
    "_is_live",
    "_iter_log_candidates",
    "_let_cs",
    "_live_matches",
    "_load_elems",
    "_map_tex_files",
    "_mark_injected",
    "_mc_chr",
    "_mc_hit",
    "_mc_parse_log",
    "_mc_plan",
    "_mc_seen",
    "_mc_table",
    "_pkg_list_re",
    "_read_utf8",
    "_resolve_site",
    "_safe_rel",
    "_skip_ws",
    "_splice",
    "_undefine_cs",
    "_wdir_fingerprint",
    "_wdir_project_files",
    "cast",
    "find_docclass_ends",
    "hashlib",
    "iter_depth0",
    "mask_tex",
    "re",
    "safe_is_file",
    "safe_rel",
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

    空表 = 同步, 测试断言 ``== []`` 即可。三向覆盖:

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝, 是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子, 只供测试调用, 装载期不自检。
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
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移, 非首错即死
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
