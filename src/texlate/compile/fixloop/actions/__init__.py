"""actions —— fixloop 动作解释器簇 (C2 自 engine.py 拆出).

``when``/``condition`` 评估 + 7 种 ``action.kind`` 分派 + 依赖闭包安装
+ ``_match_apply`` 规则匹配 (原型 ``pick_and_apply``)。

C5 拆叶：实现体按域拆进四个 ``_actions_*`` 私有兄弟叶，本文件化纯
PEP 562 惰性门面 (同 ``fixloop/engine`` 形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``actions.X`` 公共面与 ``from ... import X``/``M._x`` 属性读面不变。
monkeypatch 锚点注意：patch 叶子不 patch 门面 (docs/dev/seams.md §1)
——``actions.name`` 读到的恒是叶子对象，但 ``setattr(actions, ...)``
只遮蔽门面不改叶子内部互引。叶子间互引走全路径直跨
(``texlate.compile.fixloop._actions_<叶>``), 不经本门面。

叶谱：``actions.cond`` when/condition 评估+cond 快照簇 /
``actions.rewrite`` regex_rewrite 时限替换机制 /
``actions.install`` scan_install/install_file+依赖闭包 /
``actions.disp`` kind 分派+_match_apply+ 派发窗落件同步。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from texlate.compile.fixloop.actions.cond import (
        _SOURCE_BLOB_EXTS,
        _cond_blob,
        _cond_files,
        _cond_ok,
        _cond_shadows,
        _cond_snap,
        _cond_snap_reset,
        _err_site_outside,
        _main_dir_rel,
        _package_version,
        _stem_sibling,
        _substitute,
        _when_ok,
    )
    from texlate.compile.fixloop.actions.disp import (
        _REJECT_PREFIX,
        _apply,
        _apply_landed,
        _apply_window,
        _is_misschar_rule,
        _landing_sync,
        _match_apply,
        _mc_delta,
    )
    from texlate.compile.fixloop.actions.install import (
        _COMMENT_CUT_RE,
        _DEP_DECL_RE,
        _DEP_INPUT_RE,
        _REQ_ANCHOR_RE,
        _apply_install_file,
        _apply_scan_install,
        _dep_fanout,
        _dep_stems,
        _fd_case_variants,
        _filemap_candidates,
        _install_dep_closure,
        _probe,
        _relink_misplaced,
        _requester_paths,
        _scan_names,
        _scan_vendored,
        _try_install_dep,
    )
    from texlate.compile.fixloop.actions.rewrite import (
        _SUB_TIMEOUT_S,
        _bounded_sub,
        _compile_rewrites,
        _masked_sub,
        _patch_files,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "cond": (
        "_SOURCE_BLOB_EXTS",
        "_cond_blob",
        "_cond_files",
        "_cond_ok",
        "_cond_shadows",
        "_cond_snap",
        "_cond_snap_reset",
        "_err_site_outside",
        "_main_dir_rel",
        "_package_version",
        "_stem_sibling",
        "_substitute",
        "_when_ok",
    ),
    "disp": (
        "_REJECT_PREFIX",
        "_apply",
        "_apply_landed",
        "_apply_window",
        "_is_misschar_rule",
        "_landing_sync",
        "_match_apply",
        "_mc_delta",
    ),
    "install": (
        "_COMMENT_CUT_RE",
        "_DEP_DECL_RE",
        "_DEP_INPUT_RE",
        "_REQ_ANCHOR_RE",
        "_apply_install_file",
        "_apply_scan_install",
        "_dep_fanout",
        "_dep_stems",
        "_fd_case_variants",
        "_filemap_candidates",
        "_install_dep_closure",
        "_probe",
        "_relink_misplaced",
        "_requester_paths",
        "_scan_names",
        "_scan_vendored",
        "_try_install_dep",
    ),
    "rewrite": (
        "_SUB_TIMEOUT_S",
        "_bounded_sub",
        "_compile_rewrites",
        "_masked_sub",
        "_patch_files",
    ),
}

_LAZY: dict[str, str] = {
    name: leaf for leaf, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "_COMMENT_CUT_RE",
    "_DEP_DECL_RE",
    "_DEP_INPUT_RE",
    "_REJECT_PREFIX",
    "_REQ_ANCHOR_RE",
    "_SOURCE_BLOB_EXTS",
    "_SUB_TIMEOUT_S",
    "_apply",
    "_apply_install_file",
    "_apply_landed",
    "_apply_scan_install",
    "_apply_window",
    "_bounded_sub",
    "_compile_rewrites",
    "_cond_blob",
    "_cond_files",
    "_cond_ok",
    "_cond_shadows",
    "_cond_snap",
    "_cond_snap_reset",
    "_dep_fanout",
    "_dep_stems",
    "_err_site_outside",
    "_fd_case_variants",
    "_filemap_candidates",
    "_install_dep_closure",
    "_is_misschar_rule",
    "_landing_sync",
    "_main_dir_rel",
    "_masked_sub",
    "_match_apply",
    "_mc_delta",
    "_package_version",
    "_patch_files",
    "_probe",
    "_relink_misplaced",
    "_requester_paths",
    "_scan_names",
    "_scan_vendored",
    "_stem_sibling",
    "_substitute",
    "_try_install_dep",
    "_when_ok",
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
