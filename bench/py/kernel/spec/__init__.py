"""Spec v2 authoring surface + compile-time checks (design §4).

A bench is one ``.py`` file exporting a ``spec`` object::

    spec = Spec(
        kind="soak",
        params={"ruleset": Param(default="hard18"), "n": Param(int, required=True)},
        stages=[
            Stage("ingest", fn=do_ingest, status_class={"ok": "terminal"}),
            Stage("xlat", fn=do_xlat, needs=[("ingest", {"ok"})], paid=True,
                  status_class={"ok": "terminal", "error": "retriable"}),
        ],
        items=items,                # iterable of (id, arm, up, variant)
        freeze_plan=True,
        executor="thread",
    )

Rules baked here:

- ``compile_checks`` runs at load AND at run start — stage names unique,
  needs/on targets exist, the needs DAG is acyclic, every stage's
  ``status_class`` covers 'ok' plus every status downstream stages accept,
  DONE statuses are never mapped to 'retriable' (§3.1: "禁把伪终态映进
  RETRIABLE"), paid stages carry a dedup_key (stage or spec level), item
  (id,arm,up,variant,stage) keys are unique, params schema has real types.
- ``status_class`` maps an instrument-returned status to
  terminal|retriable|upstream. 'upstream' means the errors[0].cat='upstream'
  triage-exempt marker — retriable for accounting, flagged for triage.
  An unclassified status at runtime lands 'fault' + note, never a silent
  retry (§3.1 fail-loud).
- fp params: selector knobs (n/seed/jobs/layer/run) are auto-excluded from
  the fp params component (§3.4) — ``Param(fp=True)`` on one is a compile
  error; ``fp=False`` elsewhere just pins the exclusion.
- items may be dicts, tuples (id[,arm[,up[,variant[,stage]]]]) or bare ids;
  a callable/generator is materialized ONCE into spec.items at check time.

拆分：实现体按职责下沉同包私有叶 —— ``spec.base`` (词表常量/SC_* 预设/
SpecError/Param/_norm_need/Stage/Spec/norm_item)、``spec.checks``
(topo_stages/compile_checks)、``spec.hash`` (_iter_dep_files/code_sha/
spec_hash/cell_fp —— §3.4 指纹面逐字保留)、``spec.load`` (load_spec)。
本文件是 PEP 562 惰性门面 (同 ``kernel.index``/``kernel.vault`` 门面
形制) —— 平名经 ``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访
解析并缓存，``from kernel.spec import Spec`` / ``specmod.code_sha``
等公私名面不变 (``Spec``/``Stage``/``Param``/``SpecError`` 的
``__module__`` 已钉回本模块)。stdlib/kernel 顶层绑定名
(``spec.hashlib``/``spec.events`` 等) 经
``_STDLIB_MODS``/``_EXTRA_BINDINGS``/``_MODULE_ATTRS`` 惰性映射。
叶间互引走全路径直跨 (``kernel.spec.base`` 等), 不经本门面。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解，F401 以 __all__ re-export 豁免;
    # 私有惰性名不在此列 (不在 __all__, 无 F822 需，导入反吃 F401)。
    from kernel.spec.base import (
        DEFAULT_STATUS_CLASS,
        EVAL_LAYERS,
        EXECUTORS,
        PARAM_TYPES,
        SC_OK_FAIL,
        SC_OK_ONLY,
        SC_OK_PARTIAL,
        SC_OK_REJECT,
        SC_SPECTRUM_UP,
        SELECTOR_PARAMS,
        STATUS_CLASSES,
        Param,
        Spec,
        SpecError,
        Stage,
    )
    from kernel.spec.checks import compile_checks, topo_stages
    from kernel.spec.hash import cell_fp, code_sha, spec_hash
    from kernel.spec.load import load_spec

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "base": (
        "DEFAULT_STATUS_CLASS",
        "EVAL_LAYERS",
        "EXECUTORS",
        "PARAM_TYPES",
        "SC_OK_FAIL",
        "SC_OK_ONLY",
        "SC_OK_PARTIAL",
        "SC_OK_REJECT",
        "SC_SPECTRUM_UP",
        "SELECTOR_PARAMS",
        "STATUS_CLASSES",
        "Spec",
        "SpecError",
        "Stage",
        "Param",
        "_FN_STATUSES",
        "_MUTATE_KINDS",
        "_NAME_RE",
        "_RUN_RE",
        "_STAGE_RE",
        "_norm_need",
        "norm_item",
    ),
    "checks": (
        "compile_checks",
        "topo_stages",
    ),
    "hash": (
        "cell_fp",
        "code_sha",
        "spec_hash",
        "_iter_dep_files",
    ),
    "load": ("load_spec",),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# HEAD 单件期模块属性面——stdlib 模块名与 kernel 顶层绑定也按名惰性解析，
# 读面与拆分前逐名等价。
_STDLIB_MODS = ("hashlib", "importlib", "inspect", "re", "sys")
_EXTRA_BINDINGS = {
    "Path": "pathlib",
}
_MODULE_ATTRS = {
    "events": "kernel.events",
}

# 字面列表——拆分前 __all__ 逐字保留 (公共名面); 私有叶名与绑定名经
# _LAZY/映射表进属性读面不进 __all__。ruff F401 re-export 判定要静态
# __all__; ``_export_drift`` 是三表同步闸。
__all__ = [
    "DEFAULT_STATUS_CLASS",
    "EVAL_LAYERS",
    "EXECUTORS",
    "PARAM_TYPES",
    "SC_OK_FAIL",
    "SC_OK_ONLY",
    "SC_OK_PARTIAL",
    "SC_OK_REJECT",
    "SC_SPECTRUM_UP",
    "SELECTOR_PARAMS",
    "STATUS_CLASSES",
    "Param",
    "Spec",
    "SpecError",
    "Stage",
    "cell_fp",
    "code_sha",
    "compile_checks",
    "load_spec",
    "spec_hash",
    "topo_stages",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性 / stdlib 绑定 / kernel 顶层名。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{__package__}.{leaf}"), name)
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
    mod_path = _MODULE_ATTRS.get(name)
    if mod_path is not None:
        value = importlib.import_module(mod_path)
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
        | set(_MODULE_ATTRS)
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
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
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
        and name not in _MODULE_ATTRS
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
