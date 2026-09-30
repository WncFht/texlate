r"""命令族常量表（纯数据，零逻辑）。

原型 ``miniscanner.py`` 常量区的扶正搬迁（含 discard 修正后的终值），
外加重写新增表：``ARG_TRANSPARENT_ENVS`` / ``CHUNK_ARG_SPEC`` /
``\\if`` 两档分族 / 回压常数。

拆分：实现体按域拆进同包五叶——``tables_names``（阈值 + 环境族 +
命令族名表 + ``CHUNK_ARG_SPEC`` + model 兼容再出口五名）、
``tables_scan``（``\\if`` 两档 + 扫描层共享表 + ``PAIR_BLOCK_*`` +
``strip_fname_quotes``）、``tables_tail``（``BOUNDARY_TAIL``/
``DIMEN_TAIL_KIND``/``BOX_TAIL_NAMES``/``TRANSPARENT_HEAD_SPEC``
尾参 spec 表）、``tables_argspec``（``data/argspec.json`` 装载 +
``argspec_lookup*`` 两路查表）、``tables_colspec``（列型前导启发
``looks_like_colspec``）。本文件是 PEP 562 惰性门面（同
``compile.normalize`` 形制）——平名经 ``_LEAF_EXPORTS`` 映射回叶子，
``__getattr__`` 首访解析并缓存，``tables.X`` 公共面与
``from ... import X`` 属性读面不变。叶子间互引走全路径直跨，
不经本门面。monkeypatch 锚点注意：setattr 只遮蔽门面不改叶子——
patch 须指向叶子模块同名。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.latex.tables_argspec import (
        argspec_lookup,
        argspec_lookup_env,
        argspec_tables,
        cache,
        json,
        resources,
    )
    from texlate.latex.tables_colspec import (
        _COLSPEC_CHARS,
        _COLSPEC_COLS,
        _COLSPEC_CS_RX,
        _COLSPEC_GROUP_RX,
        _COLSPEC_STAR_RX,
        looks_like_colspec,
    )
    from texlate.latex.tables_names import (
        _DEAD_ENVS,
        _VERBATIM_ENVS,
        ACCENT_CHARS,
        ARG_TRANSPARENT_ENVS,
        BOUNDARY_NAMES,
        BUDGET,
        CHUNK_ARG_NAMES,
        CHUNK_ARG_SPEC,
        CHUNK_MAX,
        CHUNK_MIN,
        CITE_NAMES,
        DEF_NAMES,
        ENV_MANDATORY_ARG,
        FONT_SWITCHES,
        INLINE_LITERAL_CMDS,
        INPUT_CMDS,
        MATH_ENVS,
        MAX_GEN,
        MAX_INPUTS,
        OPT_FMT_CHARS,
        OPT_POS_LETTERS,
        PROTECT_BLOCK_NAMES,
        PROTECT_NAMES,
        PROTECTED_ENVS,
        REF_NAMES,
        TRANSPARENT_NAMES,
        VERBATIM_ENVS,
        ArgSpec,
        ArgspecEntry,
        annotations,
    )
    from texlate.latex.tables_scan import (
        _WS_CHARS,
        COND_RX,
        FILENAME_CHARS,
        IF_CONST,
        IF_CONST_FALSE,
        IMPORT2_CMDS,
        INPUT_SCAN_CMDS,
        PAIR_BLOCK_ALL,
        PAIR_BLOCK_CMDS,
        PROTECTED_PARAM_CMDS,
        re,
        strip_fname_quotes,
    )
    from texlate.latex.tables_tail import (
        BOUNDARY_TAIL,
        BOX_TAIL_NAMES,
        DIMEN_TAIL_KIND,
        TRANSPARENT_HEAD_SPEC,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "tables_argspec": (
        "argspec_lookup",
        "argspec_lookup_env",
        "argspec_tables",
        "cache",
        "json",
        "resources",
    ),
    "tables_colspec": (
        "_COLSPEC_CHARS",
        "_COLSPEC_COLS",
        "_COLSPEC_CS_RX",
        "_COLSPEC_GROUP_RX",
        "_COLSPEC_STAR_RX",
        "looks_like_colspec",
    ),
    "tables_names": (
        "ACCENT_CHARS",
        "ARG_TRANSPARENT_ENVS",
        "ArgSpec",
        "ArgspecEntry",
        "BOUNDARY_NAMES",
        "BUDGET",
        "CHUNK_ARG_NAMES",
        "CHUNK_ARG_SPEC",
        "CHUNK_MAX",
        "CHUNK_MIN",
        "CITE_NAMES",
        "DEF_NAMES",
        "ENV_MANDATORY_ARG",
        "FONT_SWITCHES",
        "INLINE_LITERAL_CMDS",
        "INPUT_CMDS",
        "MATH_ENVS",
        "MAX_GEN",
        "MAX_INPUTS",
        "OPT_FMT_CHARS",
        "OPT_POS_LETTERS",
        "PROTECTED_ENVS",
        "PROTECT_BLOCK_NAMES",
        "PROTECT_NAMES",
        "REF_NAMES",
        "TRANSPARENT_NAMES",
        "VERBATIM_ENVS",
        "_DEAD_ENVS",
        "_VERBATIM_ENVS",
        "annotations",
    ),
    "tables_scan": (
        "COND_RX",
        "FILENAME_CHARS",
        "IF_CONST",
        "IF_CONST_FALSE",
        "IMPORT2_CMDS",
        "INPUT_SCAN_CMDS",
        "PAIR_BLOCK_ALL",
        "PAIR_BLOCK_CMDS",
        "PROTECTED_PARAM_CMDS",
        "_WS_CHARS",
        "re",
        "strip_fname_quotes",
    ),
    "tables_tail": (
        "BOUNDARY_TAIL",
        "BOX_TAIL_NAMES",
        "DIMEN_TAIL_KIND",
        "TRANSPARENT_HEAD_SPEC",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__；键集 = _LAZY 键集，
# 新增导出两侧同步（``_export_drift`` 是三表同步闸）。
__all__ = [
    "ACCENT_CHARS",
    "ARG_TRANSPARENT_ENVS",
    "BOUNDARY_NAMES",
    "BOUNDARY_TAIL",
    "BOX_TAIL_NAMES",
    "BUDGET",
    "CHUNK_ARG_NAMES",
    "CHUNK_ARG_SPEC",
    "CHUNK_MAX",
    "CHUNK_MIN",
    "CITE_NAMES",
    "COND_RX",
    "DEF_NAMES",
    "DIMEN_TAIL_KIND",
    "ENV_MANDATORY_ARG",
    "FILENAME_CHARS",
    "FONT_SWITCHES",
    "IF_CONST",
    "IF_CONST_FALSE",
    "IMPORT2_CMDS",
    "INLINE_LITERAL_CMDS",
    "INPUT_CMDS",
    "INPUT_SCAN_CMDS",
    "MATH_ENVS",
    "MAX_GEN",
    "MAX_INPUTS",
    "OPT_FMT_CHARS",
    "OPT_POS_LETTERS",
    "PAIR_BLOCK_ALL",
    "PAIR_BLOCK_CMDS",
    "PROTECTED_ENVS",
    "PROTECTED_PARAM_CMDS",
    "PROTECT_BLOCK_NAMES",
    "PROTECT_NAMES",
    "REF_NAMES",
    "TRANSPARENT_HEAD_SPEC",
    "TRANSPARENT_NAMES",
    "VERBATIM_ENVS",
    "_COLSPEC_CHARS",
    "_COLSPEC_COLS",
    "_COLSPEC_CS_RX",
    "_COLSPEC_GROUP_RX",
    "_COLSPEC_STAR_RX",
    "_DEAD_ENVS",
    "_VERBATIM_ENVS",
    "_WS_CHARS",
    "ArgSpec",
    "ArgspecEntry",
    "annotations",
    "argspec_lookup",
    "argspec_lookup_env",
    "argspec_tables",
    "cache",
    "json",
    "looks_like_colspec",
    "re",
    "resources",
    "strip_fname_quotes",
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

    - ``_LAZY`` 键全进 ``__all__``；
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链（``_LEAF_EXPORTS``
      配名叶子不提供）与幽灵条在此曝，是首访 ``AttributeError`` 唯一
      的提前闸；
    - 本地公共名（本模块定义的函数/类/dict）全进 ``__all__``。

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
