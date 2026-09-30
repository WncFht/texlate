"""Derived query index — ledger/index.sqlite (design §3.2, §3.10.5, §3.10.6).

index.sqlite is a pure projection of ledger/events.jsonl: disposable,
versioned, rebuildable. The ledger is the sole source of truth — every row
here can be reproduced by replaying the ledger.

Contract baked in:

    - Write order is always events.jsonl (flock + fsync) first, sqlite second;
      this module is the second writer and owns no ledger writes except
      quarantine rows (see below).
    - tail_ingest() advances a byte watermark = offset just past the last
      swallowed ``\\n``. Never file size, never mid-line: a torn tail is
      re-read once the writer finishes the line.
    - (run_seq, seq) is the idempotent dedup key for run events. Run-less
      events (tombstone, lake_cell, ingest_runless) are stored under
      run_seq=-1 with an index-assigned seq. A separate dedupe table keyed
      by payload_sha covers EVERY row, so replay is idempotent across key
      forms and across truncate-rewrites.
    - (run_seq,seq) conflict: identical payload_sha = replay → dedup_skip++;
      different payload = ledger corruption → row appended to
      ledger/quarantine.jsonl + counter, apply does NOT raise (stays
      idempotent; the offending payload is marked in dedupe so replays of
      it don't spam quarantine).
    - rebuild() wipes every projection table and replays the ledger in ONE
      transaction, so a crash mid-rebuild rolls back to the old consistent
      index. Refused while the kernel is active (locks.kernel_idle() — the
      NB-flock probe on the .kernel-active sentinel is the design's
      authoritative liveness proof).
      On success: sealed_gen += 1, watermark = fsync'd tail offset,
      .index-dirty cleared AFTER commit.
    - check_sealed() is a fail-closed oracle INPUT for the paid gate (§3.10.6):
      wrong generation, watermark below the caller's fsync offset, or
      .index-dirty present → False. It never guesses; the mutex lives in the
      claim flock files, not here.
    - cells projection is last-write-wins in ledger append order
      (events.rowid is the authoritative total order per §3.10.5).

Statuses: done() treats DONE ∪ KERNEL as terminal — a cell marked
dedup/claimed/lost/unpaid_gate must never re-enter a run set (fail-closed
direction for paid cells).

拆分：实现体按子域下沉同包私有叶 —— ``_index_common`` (schema 常量/
DDL 全文/``_j``/inode tag/sealed 段名集/kernel 活性探针)、
``_index_store`` (``_StoreMixin``: sqlite 句柄/schema 建表与 additive
迁移/meta 计数器/_txn 单写者事务/close)、``_index_apply``
(``_ApplyMixin``: apply/_key_of/_apply_one/_quarantine)、``_index_proj``
(``_ProjMixin``: _project 路由/_proj_cell/_proj_claim/_proj_asset/
_upsert_vault_meta)、``_index_replay`` (``_ReplayMixin``: sealed 段摄入/
tail_ingest/_iter_all_events/rebuild + ``_norm_iter_item``)、
``_index_query`` (``_QueryMixin``: sealed_state/check_sealed/done/
paid_pool/active_claims 等读面 + dirty 旗)、``_index_core``
(``Index`` 五 mixin 装配 + ``rebuild_index``/``open_index``/
``ingest_runless`` 入口)。本文件是 PEP 562 惰性门面 (同
``importer``/``kernel.kernel``/``cli`` 门面形制) —— 平名经
``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析并缓存，
``kernel.index.Index`` / ``from kernel.index import ingest_runless``
等公私名面不变 (``Index.__module__`` 已钉回本模块)。
monkeypatch 锚点注意：测试 setattr patch 到门面名上只对「经
``index.X`` 属性读的消费方」生效 (setattr 写真全局遮蔽 ``__getattr__``);
Index 方法的 patch 须指到叶子 mixin (如
``kernel._index_apply._ApplyMixin._apply_one``) 或 ``Index`` 本体
(类属性遮蔽 MRO 依旧生效)。
"""

from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kernel._index_common import (
        _META_COUNTERS,
        _PROJECTION_TABLES,
        _SCHEMA,
        _STATUS_QUEUED,
        _STATUS_STARTED,
        _TERMINAL,
        _VAULT_BYTES_OK,
        _VAULT_KINDS,
        INDEX_SCHEMA_V,
        _file_tag,
        _j,
        _kernel_idle,
        _sealed_segment_names,
    )
    from kernel._index_core import (
        Index,
        ingest_runless,
        open_index,
        rebuild_index,
    )
    from kernel._index_replay import _norm_iter_item

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_index_common": (
        "INDEX_SCHEMA_V",
        "_META_COUNTERS",
        "_PROJECTION_TABLES",
        "_SCHEMA",
        "_STATUS_QUEUED",
        "_STATUS_STARTED",
        "_TERMINAL",
        "_VAULT_BYTES_OK",
        "_VAULT_KINDS",
        "_file_tag",
        "_j",
        "_kernel_idle",
        "_sealed_segment_names",
    ),
    "_index_replay": ("_norm_iter_item",),
    "_index_core": (
        "Index",
        "ingest_runless",
        "open_index",
        "rebuild_index",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__; 键集 = _LAZY 键集，
# 新增导出两侧同步 (``_export_drift`` 是三表同步闸)。
__all__ = [
    "INDEX_SCHEMA_V",
    "_META_COUNTERS",
    "_PROJECTION_TABLES",
    "_SCHEMA",
    "_STATUS_QUEUED",
    "_STATUS_STARTED",
    "_TERMINAL",
    "_VAULT_BYTES_OK",
    "_VAULT_KINDS",
    "Index",
    "_file_tag",
    "_j",
    "_kernel_idle",
    "_norm_iter_item",
    "_sealed_segment_names",
    "ingest_runless",
    "open_index",
    "rebuild_index",
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
        except Exception as exc:  # 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
