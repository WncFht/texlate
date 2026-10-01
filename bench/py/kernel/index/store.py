"""index 存储底座 mixin —— sqlite 句柄/schema 建表与迁移/meta 计数器/写事务。

- ``__init__`` — WAL + NORMAL + busy_timeout=30000 的连接契约 (宽限给
  批量写者：14k-event emit_batch sink 磨满单写者槽时 5s 超时曾失守)。
- ``_schema_current``/``_init_schema``/``_drop_all`` — 稳态零写只读探针 +
  create-missing 先行 + additive ALTER/INDEX 免版本号迁移。
- ``_meta_*`` — meta kv 读写与计数器。
- ``_txn``/``_next_line_no`` — BEGIN IMMEDIATE 单写者事务 + events
  line_no 高水位续号。
- ``close``/``__enter__``/``__exit__`` — conn 生命周期。

只被 ``index.core.Index`` 继承; 不 import 兄弟叶 (常量走 ``index.common``)。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from kernel import paths
from kernel.index.common import (
    _META_COUNTERS,
    _PROJECTION_TABLES,
    _SCHEMA,
    INDEX_SCHEMA_V,
)


class _StoreMixin:
    def __init__(self, path=None, *, eval_stages=None, force_schema=False):
        self.path = Path(path) if path is not None else paths.index_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.eval_stages = frozenset(eval_stages or ())
        self.conn = sqlite3.connect(str(self.path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        # Generous writer patience: batch writers (import drivers, tail_ingest
        # during a run) legitimately share the single WAL writer slot, and a
        # near-saturated writer starves short-timeout openers (observed: a
        # 14k-event emit_batch sink grind failed a concurrent Index() open at
        # the 5s mark).
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._line_no_hwm = 0
        self._init_schema(force=force_schema)

    # -- schema ---------------------------------------------------------------

    def _schema_current(self) -> bool:
        """Read-only probe: True when meta exists at the current schema_v
        with every counter key and the claims.fate column already present.

        WAL readers never block, so a steady-state Index() open performs
        ZERO writes and cannot collide with a live writer — init writes only
        run when something is actually missing (first open, migration).
        """
        try:
            if self._meta_get("schema_v") != str(INDEX_SCHEMA_V):
                return False
            keys = {r["key"] for r in self.conn.execute("SELECT key FROM meta")}
            if any(k not in keys for k in _META_COUNTERS):
                return False
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(claims)")}
            if "fate" not in cols:
                return False
            ccols = {r["name"] for r in self.conn.execute("PRAGMA table_info(cases)")}
            if "stage" not in ccols:
                return False
            idxs = {r["name"] for r in self.conn.execute("PRAGMA index_list(events)")}
        except sqlite3.OperationalError:
            return False
        else:
            return "idx_events_line_no" in idxs

    def _init_schema(self, *, force: bool) -> None:
        if not force and self._schema_current():
            return
        # Create-missing first so a torn create can never leave meta without
        # its sibling tables (the txn seeder reads events).
        self.conn.executescript(_SCHEMA)
        v = self._meta_get("schema_v")
        if v is not None and v != str(INDEX_SCHEMA_V):
            if not force:
                msg = (
                    f"index schema_v {v} != {INDEX_SCHEMA_V} — "
                    "run rebuild_index() to recreate"
                )
                raise RuntimeError(msg)
            self._drop_all()
            self.conn.executescript(_SCHEMA)
        for k in _META_COUNTERS:
            self._meta_set_default(k, "0")
        self._meta_set_default("schema_v", str(INDEX_SCHEMA_V))
        # Additive post-v1 columns — guarded ALTER, no schema bump (the
        # column is nullable; replay and old rows are unaffected).
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(claims)")}
        if "fate" not in cols:
            self.conn.execute("ALTER TABLE claims ADD COLUMN fate TEXT")
        # cases.stage — additive, no schema bump (nullable; a rebuild
        # backfills it for every row since both sources carry stage).
        ccols = {r["name"] for r in self.conn.execute("PRAGMA table_info(cases)")}
        if "stage" not in ccols:
            self.conn.execute("ALTER TABLE cases ADD COLUMN stage TEXT")
        # idx_events_line_no — additive, no schema bump. Without it every
        # _txn's MAX(line_no) full-scans the events mirror (observed: a
        # per-event sink ground at ~2.5GB/s of page reads on a 500k-row
        # table); indexed, the probe is O(log n).
        idxs = {r["name"] for r in self.conn.execute("PRAGMA index_list(events)")}
        if "idx_events_line_no" not in idxs:
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_line_no ON events(line_no)"
            )

    def _drop_all(self) -> None:
        with self._txn():
            for t in (*_PROJECTION_TABLES, "meta"):
                self.conn.execute(f"DROP TABLE IF EXISTS {t}")

    # -- meta ------------------------------------------------------------------

    def _meta_get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def _meta_set(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def _meta_set_default(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key,value) VALUES (?,?)",
            (key, str(value)),
        )

    def _meta_incr(self, key: str, delta: int = 1) -> int:
        v = int(self._meta_get(key, "0") or 0) + delta
        self._meta_set(key, str(v))
        return v

    # -- transactions -----------------------------------------------------------

    @contextmanager
    def _txn(self):
        """Single-writer transaction. BEGIN IMMEDIATE so a second writer
        fails fast under busy_timeout rather than deadlocking mid-batch."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._line_no_hwm = self.conn.execute(
                "SELECT COALESCE(MAX(line_no),0) FROM events"
            ).fetchone()[0]
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def _next_line_no(self) -> int:
        self._line_no_hwm += 1
        return self._line_no_hwm

    # -- lifecycle --------------------------------------------------------------------

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
