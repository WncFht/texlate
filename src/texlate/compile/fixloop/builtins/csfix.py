r"""builtins.csfix — undefined_cs/already_def 按 cs 名打靶修复原语 (C3 拆分)。

``cs_targeted_fix``: cs→修复表 (strip_pkg/usepackage/cs_map/polyfill 组合序,
``engines.{eng}`` 子表覆盖) + glue-残骸前缀拆分兜底; ``undefine_for_redef``:
already_def ``\\let\\X\\@undefined`` 让位注入 (寄存器/盒型分配名护栏)。

C5 拆叶: 实现体按修复域拆进九个 ``_csfix_*`` 私有兄弟叶, 本文件化纯
PEP 562 惰性门面 (同 ``fixloop/engine`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子, ``__getattr__`` 首访解析并缓存,
``csfix.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意: patch 叶子不 patch 门面 —— ``csfix.name``
读到的恒是叶子对象, 但 ``setattr(csfix, ...)`` 只遮蔽门面不改
叶子内部互引。叶子间互引走全路径直跨
(``texlate.compile.fixloop.builtins._csfix_<叶>``), 不经本门面。

叶谱: ``_csfix_table`` cs→修复表数据 (sortlist/cref polyfill 串) /
``_csfix_alloc`` 分配名护栏 + docclass 锚位 / ``_csfix_target``
``cs_targeted_fix`` 主臂 (表应用/glue 拆分/usepackage 确保) /
``_csfix_sites`` already_def 站点前置清位面 / ``_csfix_pkg``
pkg-missing 站点扩清 / ``_csfix_abd`` AtBeginDocument 推迟件 /
``_csfix_redef`` ``undefine_for_redef`` 主臂 / ``_csfix_ctlseq``
ctl-seq 撞名扫描+清位 / ``_csfix_clobber`` primitive 撞名改绑。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.builtins._csfix_abd import (
        _ABD_ERR_FILE_RE,
        _abd_deferred,
        _abd_hook_clear,
        find_docclass_ends,
    )
    from texlate.compile.fixloop.builtins._csfix_alloc import (
        _ALLOC_BRACE_RE,
        _ALLOC_CS_RE,
        DOCCLASS_RX,
        _allocated_cs_names,
        _inject_before_anchor,
        _inject_before_docclass,
    )
    from texlate.compile.fixloop.builtins._csfix_clobber import (
        _CLOBBER_DEF_KINDS,
        primitive_clobber_rename,
    )
    from texlate.compile.fixloop.builtins._csfix_ctlseq import (
        _CJK_SEAM_MARKS,
        _CTLSEQ_DEF_RE,
        _CTLSEQ_ERRFILE_RE,
        _CTLSEQ_FILE_HEADS,
        _CTLSEQ_RESERVED,
        PDFTEX_PRIMS,
        _ctlseq_collided,
        ctlseq_undefine,
    )
    from texlate.compile.fixloop.builtins._csfix_pkg import (
        _LOAD_SITE_RE,
        _PKG_ERR_FILE_RE,
        _load_elems,
        _pkg_err_stems,
        _undefine_pkg_sites,
    )
    from texlate.compile.fixloop.builtins._csfix_redef import (
        _ALREADY_DEF_CS_RE,
        _fixloop_log,
        undefine_for_redef,
    )
    from texlate.compile.fixloop.builtins._csfix_sites import (
        _IFN_ROUTED_CMDS,
        _PROVIDE_SITE_CMDS,
        _RESERVED_UNDEFINABLE,
        _SITE_DEF_CMDS,
        _endstar_name,
        _let_cs,
        _live_matches,
        _prepend_sites_in_text,
        _redef_site_map,
        _site_clear_line,
        _splice,
        _undefine_cs,
        _undefine_sites,
    )
    from texlate.compile.fixloop.builtins._csfix_table import (
        _CRT_CREF_SPLITTER_FIX,
        _CS_FIX_TABLE,
        _SORTLIST_BBL_POLYFILL,
    )
    from texlate.compile.fixloop.builtins._csfix_target import (
        _SPLIT_GUARD,
        _SPLIT_HEADS,
        _SPLIT_REST_MAX,
        _drop_pkg_loads,
        _ensure_usepackage,
        _guard_snippet,
        _inject_after_docclass,
        _map_tex_files,
        _rewrite_cs_map,
        _split_glued_cs,
        cs_targeted_fix,
        mask_tex,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_csfix_abd": (
        "_ABD_ERR_FILE_RE",
        "_abd_deferred",
        "_abd_hook_clear",
        "find_docclass_ends",
    ),
    "_csfix_alloc": (
        "DOCCLASS_RX",
        "_ALLOC_BRACE_RE",
        "_ALLOC_CS_RE",
        "_allocated_cs_names",
        "_inject_before_anchor",
        "_inject_before_docclass",
    ),
    "_csfix_clobber": (
        "_CLOBBER_DEF_KINDS",
        "primitive_clobber_rename",
    ),
    "_csfix_ctlseq": (
        "PDFTEX_PRIMS",
        "_CJK_SEAM_MARKS",
        "_CTLSEQ_DEF_RE",
        "_CTLSEQ_ERRFILE_RE",
        "_CTLSEQ_FILE_HEADS",
        "_CTLSEQ_RESERVED",
        "_ctlseq_collided",
        "ctlseq_undefine",
    ),
    "_csfix_pkg": (
        "_LOAD_SITE_RE",
        "_PKG_ERR_FILE_RE",
        "_load_elems",
        "_pkg_err_stems",
        "_undefine_pkg_sites",
    ),
    "_csfix_redef": (
        "_ALREADY_DEF_CS_RE",
        "_fixloop_log",
        "undefine_for_redef",
    ),
    "_csfix_sites": (
        "_IFN_ROUTED_CMDS",
        "_PROVIDE_SITE_CMDS",
        "_RESERVED_UNDEFINABLE",
        "_SITE_DEF_CMDS",
        "_endstar_name",
        "_let_cs",
        "_live_matches",
        "_prepend_sites_in_text",
        "_redef_site_map",
        "_site_clear_line",
        "_splice",
        "_undefine_cs",
        "_undefine_sites",
    ),
    "_csfix_table": (
        "_CRT_CREF_SPLITTER_FIX",
        "_CS_FIX_TABLE",
        "_SORTLIST_BBL_POLYFILL",
    ),
    "_csfix_target": (
        "_SPLIT_GUARD",
        "_SPLIT_HEADS",
        "_SPLIT_REST_MAX",
        "_drop_pkg_loads",
        "_ensure_usepackage",
        "_guard_snippet",
        "_inject_after_docclass",
        "_map_tex_files",
        "_rewrite_cs_map",
        "_split_glued_cs",
        "cs_targeted_fix",
        "mask_tex",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集,
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "DOCCLASS_RX",
    "PDFTEX_PRIMS",
    "_ABD_ERR_FILE_RE",
    "_ALLOC_BRACE_RE",
    "_ALLOC_CS_RE",
    "_ALREADY_DEF_CS_RE",
    "_CJK_SEAM_MARKS",
    "_CLOBBER_DEF_KINDS",
    "_CRT_CREF_SPLITTER_FIX",
    "_CS_FIX_TABLE",
    "_CTLSEQ_DEF_RE",
    "_CTLSEQ_ERRFILE_RE",
    "_CTLSEQ_FILE_HEADS",
    "_CTLSEQ_RESERVED",
    "_IFN_ROUTED_CMDS",
    "_LOAD_SITE_RE",
    "_PKG_ERR_FILE_RE",
    "_PROVIDE_SITE_CMDS",
    "_RESERVED_UNDEFINABLE",
    "_SITE_DEF_CMDS",
    "_SORTLIST_BBL_POLYFILL",
    "_SPLIT_GUARD",
    "_SPLIT_HEADS",
    "_SPLIT_REST_MAX",
    "_abd_deferred",
    "_abd_hook_clear",
    "_allocated_cs_names",
    "_ctlseq_collided",
    "_drop_pkg_loads",
    "_endstar_name",
    "_ensure_usepackage",
    "_fixloop_log",
    "_guard_snippet",
    "_inject_after_docclass",
    "_inject_before_anchor",
    "_inject_before_docclass",
    "_let_cs",
    "_live_matches",
    "_load_elems",
    "_map_tex_files",
    "_pkg_err_stems",
    "_prepend_sites_in_text",
    "_redef_site_map",
    "_rewrite_cs_map",
    "_site_clear_line",
    "_splice",
    "_split_glued_cs",
    "_undefine_cs",
    "_undefine_pkg_sites",
    "_undefine_sites",
    "cs_targeted_fix",
    "ctlseq_undefine",
    "find_docclass_ends",
    "mask_tex",
    "primitive_clobber_rename",
    "undefine_for_redef",
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
