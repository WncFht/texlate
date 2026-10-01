"""index 装配叶 —— Index = 五个子域 mixin 组合 + 模块级入口函数。

``Index`` 的方法面 = ``_StoreMixin`` (conn/schema/meta/txn) +
``_ApplyMixin`` (事件应用/dedupe/quarantine) + ``_ProjMixin`` (类型投影)
+ ``_ReplayMixin`` (sealed/tail/rebuild) + ``_QueryMixin`` (oracle/dedup
域/dirty), 全部经实例 MRO 互调，叶间零互引。``Index.__module__`` 钉回
``kernel.index`` 保持 repr/pickle 引用路径不变。

入口函数：``rebuild_index`` (force_schema 容忍版本漂移 + 全量重放)、
``open_index`` (读侧标准入口 — tail_ingest 失败只警告照返陈旧投影，
读面永不因撕裂尾失败)、``ingest_runless`` (run-less 事件写入，
dedupe 仍按原样 payload_sha)。
"""

from __future__ import annotations

import sys

from kernel.index.apply import _ApplyMixin
from kernel.index.proj import _ProjMixin
from kernel.index.query import _QueryMixin
from kernel.index.replay import _ReplayMixin
from kernel.index.store import _StoreMixin


class Index(_StoreMixin, _ApplyMixin, _ProjMixin, _ReplayMixin, _QueryMixin):
    """The sole query surface over the ledger. Pure projection — may be
    wiped and rebuilt at any time."""


Index.__module__ = "kernel.index"


def rebuild_index(path=None) -> Index:
    """Open (tolerating schema-version drift) + rebuild + return the Index."""
    idx = Index(path, force_schema=True)
    idx.rebuild()
    return idx


def open_index(path=None, *, warn=None) -> Index:
    """Index + tail_ingest — the standard read-side entry point.

    A failed ingest is reported via ``warn`` and the (stale) projection is
    returned anyway — reading must never fail on a torn ledger tail.
    ``warn=None`` degrades to a bare stderr print. doctor/sweep's
    exists-or-None flavor is a different contract (read-side purity) and
    stays local to those modules.
    """
    idx = Index(path)
    try:
        idx.tail_ingest()
    except Exception as exc:
        msg = f"note: tail_ingest failed ({exc}) — index may be stale"
        if warn is not None:
            warn(msg)
        else:
            print(msg, file=sys.stderr)
    return idx


def ingest_runless(ev: dict, idx: Index | None = None) -> str:
    """Apply a ledger event that carries no (run_seq, seq) key — tombstones,
    lake_cells, backfilled rows. Stored under run_seq=-1 with an
    index-assigned seq; dedupe is still keyed on payload_sha (computed on the
    event as given, so it matches the ledger line's hash)."""
    own = idx is None
    if own:
        idx = Index()
    try:
        with idx._txn():
            return idx._apply_one(dict(ev), runless=True)
    finally:
        if own:
            idx.close()
