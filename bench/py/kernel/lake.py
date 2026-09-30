"""Lake zone — the rebuildable corpus (design §3.10.3 lazy three-state
machine, §3.10.1 capacity budget, R9 fetch-storm guard).

Layout::

    lake/corpus/{source}/{safe_id}/    cell tree
        raw/        canonical layer (payload as fetched — may be absent
                    after a raw-tier eviction)
        extracted/  re-derivable projection — evicted FIRST
        meta.json   commit marker: {n_files, ...}
        files.txt / mtree.txt          optional bookkeeping (not payload)
    lake/corpus/catalog.jsonl          dynamic state book — the projection
                                       of ledger lake_cell events; last
                                       row wins per idc
    lake/tmp/rebuild/{run_seq}/{safe_id}.stage/
                                       atomic build area — a cell is
                                       constructed whole here, then
                                       rename()'d into place (§3.10.8:
                                       "物化真原子化")
    lake/.locks/{safe_id}.lock         per-cell flock — never unlinked (R21)

State machine: ``skeleton → hydrating → hydrated ⇄ pinned`` plus tiered
``raw_only`` (extracted evicted, raw kept — local re-extract is free) and
``failed`` (manifest-seeded stub/pdf_only/fetch_error, never in the fetch
set). ``manifested:false`` marks orphan cells — first eviction candidates.

Pin is a FIELD (``pinned:true`` on the catalog row) anchored by a
cell-side ``PINNED`` marker file — never a state: ``state=='pinned'``
silently un-pins on the next ``set()`` (the merge carries fields, not the
replaced state), so the file is the truth the row projects and every
byte-deleting verb (evict tiers, shrink_shell, remove_cell_tree, orphan
adoption) must consult the marker, not just the row.

Read predicate (THE consumer gate, §3.10.3): ``is_complete`` = cell dir
exists ∧ meta.json parseable ∧ meta.n_files == actual payload file count —
half trees NEVER satisfy, so a paid cell never projects a torn corpus entry.

Concurrency: hydrate takes ``.locks/{safe_id}.lock`` LOCK_EX (blocking) and
re-checks completeness inside the lock — two concurrent hydrations of the
same cell degrade to one-fetch-one-wait ("同格两 run 同拉退化为一拉一等").

拆分: 实现体按子域下沉同包私有叶 —— ``_lake_cell`` (PIN_MARKER/_BOOKKEEP/
cell_dir/cell_pinned/_read_meta/_payload_count/is_complete/lake_lock)、
``_lake_catalog`` (catalog append 助手/_lake_event/_latest_row/
LakeCatalog/register_skeleton/pin/unpin 模块动词)、``_lake_gate``
(env 常量/admit/DiskPressureError/_check_fetch_headroom)、
``_lake_hydrate`` (_populate_from_raw/_publish_stage/hydrate)、
``_lake_evict`` (_pinned/_freeable_size/evict/evict_cell)、
``_lake_shell`` (_SHELL_KEEP_*/shrink_shell)。本文件是 PEP 562 惰性门面
(同 ``kernel.index``/``kernel.vault`` 门面形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子, ``__getattr__`` 首访解析并缓存,
``from kernel import lake`` / ``lake._pinned`` 等公私名面不变
(``LakeCatalog``/``DiskPressureError`` 的 ``__module__`` 已钉回本模块)。
stdlib/kernel 顶层绑定名 (``lake.shutil``/``lake.paths`` 等) 经
``_STDLIB_MODS``/``_EXTRA_BINDINGS``/``_MODULE_ATTRS``/``_KERNEL_EXPORTS``
惰性映射, 读面与拆分前逐名等价。叶间互引走全路径直跨
(``kernel._lake_cell`` 等), 不经本门面。monkeypatch 锚点注意: 测试
``setattr(shutil, "disk_usage", ...)`` 打在共享模块对象上照常生效;
``setattr`` 写真门面名只对「经 ``lake.X`` 属性读的消费方」生效。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解, F401 以 __all__ re-export 豁免;
    # 私有惰性名不在此列 (不在 __all__, 无 F822 需, 导入反吃 F401)。
    from kernel._lake_catalog import LakeCatalog, pin, register_skeleton, unpin
    from kernel._lake_cell import (
        PIN_MARKER,
        cell_dir,
        cell_pinned,
        is_complete,
        lake_lock,
    )
    from kernel._lake_evict import evict, evict_cell
    from kernel._lake_gate import DiskPressureError, admit
    from kernel._lake_hydrate import hydrate
    from kernel._lake_shell import shrink_shell

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_lake_cell": (
        "PIN_MARKER",
        "_BOOKKEEP",
        "cell_dir",
        "cell_pinned",
        "is_complete",
        "lake_lock",
        "_payload_count",
        "_read_meta",
    ),
    "_lake_catalog": (
        "LakeCatalog",
        "_append_line",
        "_append_row",
        "_lake_event",
        "_latest_row",
        "pin",
        "register_skeleton",
        "unpin",
    ),
    "_lake_gate": (
        "DiskPressureError",
        "_ENV_LAKE_CAP_GB",
        "_ENV_LAKE_FLOOR_GB",
        "_ENV_MIN_FREE_GB",
        "_GIB",
        "_check_fetch_headroom",
        "admit",
    ),
    "_lake_hydrate": (
        "hydrate",
        "_populate_from_raw",
        "_publish_stage",
    ),
    "_lake_evict": (
        "evict",
        "evict_cell",
        "_freeable_size",
        "_pinned",
    ),
    "_lake_shell": (
        "shrink_shell",
        "_SHELL_KEEP_EXACT",
        "_SHELL_KEEP_GLOB",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# HEAD 单件期模块属性面——stdlib 模块名与 kernel 顶层绑定也按名惰性解析,
# 读面 (含 setattr 型 monkeypatch 缝, patch 落在共享 module 对象上) 与拆分
# 前逐名等价。
_STDLIB_MODS = ("gzip", "json", "os", "shutil", "tarfile", "time")
_EXTRA_BINDINGS = {
    "Path": "pathlib",
    "TYPE_CHECKING": "typing",
    "contextmanager": "contextlib",
    "suppress": "contextlib",
}
_MODULE_ATTRS = {
    "events": "kernel.events",
    "fsutil": "kernel.fsutil",
    "ledger": "kernel.ledger",
    "locks": "kernel.locks",
    "paths": "kernel.paths",
    "vault": "kernel.vault",
}
_KERNEL_EXPORTS = {
    "iter_jsonl": "kernel.events",
    "make_event": "kernel.events",
    "safe_id": "kernel.idnorm",
}

# 字面列表——拆分前 __all__ 逐字保留 (公共名面); 私有叶名与绑定名经
# _LAZY/映射表进属性读面不进 __all__。ruff F401 re-export 判定要静态
# __all__; ``_export_drift`` 是三表同步闸。
__all__ = [
    "PIN_MARKER",
    "DiskPressureError",
    "LakeCatalog",
    "admit",
    "cell_dir",
    "cell_pinned",
    "evict",
    "evict_cell",
    "hydrate",
    "is_complete",
    "lake_lock",
    "pin",
    "register_skeleton",
    "shrink_shell",
    "unpin",
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
    kern = _KERNEL_EXPORTS.get(name)
    if kern is not None:
        value = getattr(importlib.import_module(kern), name)
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
        | set(_KERNEL_EXPORTS)
    )


def _export_drift() -> list[str]:
    """``_LAZY``/``__all__``/叶子实体三表同步审计 → 漂移描述表。

    空表 = 同步, 测试断言 ``== []`` 即可。逐名 ``getattr`` 实解: 叶子断链
    (``_LEAF_EXPORTS`` 配名叶子不提供) 与幽灵条 (解析不到任何叶子或绑
    定) 在此曝, 是首访 ``AttributeError`` 唯一的提前闸。审计实载全部
    叶子, 只供测试调用, 装载期不自检。
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
        and name not in _MODULE_ATTRS
        and name not in _KERNEL_EXPORTS
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
