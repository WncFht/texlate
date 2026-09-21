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
      index. Refused while the kernel is active (locks.kernel_idle() when
      kernel.locks is available, else an NB-flock probe on the
      .kernel-active sentinel — the design's authoritative liveness proof).
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
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from kernel import events, paths

INDEX_SCHEMA_V = 1

# Synthetic cell-projection states for non-terminal lifecycle events.
_STATUS_QUEUED = "queued"
_STATUS_STARTED = "started"

# Terminal statuses: instrument DONE set ∪ kernel-internal terminal statuses.
_TERMINAL = events.STATUS_DONE | events.STATUS_KERNEL

# Terminal statuses that count toward the paid pool (§3.6): only bytes that
# actually cost money and succeeded (ok | partial). reject/fail/fault/
# dirty_pdf are "attempted-unpaid" and must NOT join the pool.
_PAID_OK = frozenset({"ok", "partial"})

# vault_meta verdicts whose bytes count as present for the dedup oracle.
# §3.8: primary/quarantine/alt all dedup-hit; pending is treated as no-bytes;
# tombstone is a regen_gate hard stop (handled upstream, excluded here).
# "verified"/"adopted" cover asset-state vocabulary projected into verdicts.
_VAULT_BYTES_OK = frozenset(
    {"verified", "primary", "alt", "quar", "quarantine", "adopted"}
)

# Asset kinds that are vault-managed bytes (pdf/report are work-tree artifacts).
_VAULT_KINDS = frozenset({"zh", "splice", "state"})

# meta keys reset to "0" on rebuild (schema_v is preserved).
_META_COUNTERS = (
    "sealed_gen", "watermark", "dedup_skip", "quarantine",
    "runless_seq", "bad_lines",
)

# Every projection table wiped by rebuild (meta is handled separately).
_PROJECTION_TABLES = (
    "events", "dedupe", "cells", "records", "eval_records", "cases",
    "assets", "claims", "paid_slots", "vault_meta", "papers", "runs",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS events (
    line_no     INTEGER,
    run_seq     INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    payload_sha TEXT NOT NULL,
    payload     TEXT NOT NULL,
    ts          REAL,
    type        TEXT,
    PRIMARY KEY (run_seq, seq)
);
CREATE TABLE IF NOT EXISTS dedupe (
    payload_sha TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS cells (
    idc      TEXT NOT NULL,
    arm      TEXT NOT NULL,
    up       TEXT NOT NULL,
    variant  TEXT NOT NULL,
    stage    TEXT NOT NULL,
    last_run TEXT,
    last_seq INTEGER,
    status   TEXT,
    cat      TEXT,
    fp       TEXT,
    ts       REAL,
    PRIMARY KEY (idc, arm, up, variant, stage)
);
CREATE TABLE IF NOT EXISTS records (
    run TEXT, seq INTEGER, id TEXT, idc TEXT, arm TEXT, up TEXT,
    variant TEXT, stage TEXT, status TEXT, cat TEXT, sig TEXT, code TEXT,
    fp TEXT, dur_s REAL, metrics TEXT, errors TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS eval_records (
    run TEXT, seq INTEGER, id TEXT, idc TEXT, arm TEXT, up TEXT,
    variant TEXT, stage TEXT, status TEXT, cat TEXT, sig TEXT, code TEXT,
    fp TEXT, dur_s REAL, metrics TEXT, errors TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS cases (
    run TEXT, seq INTEGER, id TEXT, idc TEXT, payload TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS assets (
    idc TEXT, arm TEXT, variant TEXT, kind TEXT, path TEXT, sha TEXT,
    bytes INTEGER, state TEXT, run TEXT, seq INTEGER, ts REAL
);
CREATE TABLE IF NOT EXISTS claims (
    idc TEXT, arm TEXT, variant TEXT, run TEXT, seq INTEGER,
    op TEXT, slot TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS paid_slots (
    slot TEXT PRIMARY KEY,
    idc TEXT, arm TEXT, variant TEXT, run TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS vault_meta (
    idc     TEXT NOT NULL,
    arm     TEXT NOT NULL,
    variant TEXT NOT NULL,
    altseq  TEXT NOT NULL DEFAULT '0',
    zone    TEXT,
    verdict TEXT,
    path    TEXT,
    sha     TEXT,
    ts      REAL,
    PRIMARY KEY (idc, arm, variant, altseq)
);
CREATE TABLE IF NOT EXISTS papers (
    idc    TEXT PRIMARY KEY,
    id_raw TEXT,
    src    TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    run       TEXT PRIMARY KEY,
    run_seq   INTEGER,
    kind      TEXT,
    date      TEXT,
    slug      TEXT,
    spec_hash TEXT,
    ts_start  REAL
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_records_cell
    ON records(idc, arm, up, variant, stage);
CREATE INDEX IF NOT EXISTS idx_claims_key ON claims(idc, arm, variant);
"""


def _j(val):
    """JSON-encode a payload column (metrics/errors); NULL stays NULL."""
    if val is None:
        return None
    return json.dumps(val, ensure_ascii=False, sort_keys=True)


def _tail_newline_offset(path: Path) -> int:
    """Byte offset just past the last '\\n' in file; 0 if none/missing."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return 0
    if size == 0:
        return 0
    pos = size
    with open(path, "rb") as f:
        while pos > 0:
            step = min(pos, 65536)
            pos -= step
            f.seek(pos)
            buf = f.read(step)
            i = buf.rfind(b"\n")
            if i >= 0:
                return pos + i + 1
    return 0


def _kernel_idle() -> bool:
    """True when no kernel is running — locks.kernel_idle() when the locks
    module is available, else an NB-flock probe on the .kernel-active
    sentinel (a dead kernel's flock is always released, so the probe is the
    authoritative life/death proof)."""
    try:
        from kernel import locks  # type: ignore[import-not-found]
    except ImportError:
        locks = None
    fn = getattr(locks, "kernel_idle", None) if locks is not None else None
    if fn is not None:
        return bool(fn())
    p = paths.kernel_active_path()
    if not p.exists():
        return True
    fd = os.open(p, os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


class Index:
    """The sole query surface over the ledger. Pure projection — may be
    wiped and rebuilt at any time."""

    def __init__(self, path=None, *, eval_stages=None, force_schema=False):
        self.path = Path(path) if path is not None else paths.index_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.eval_stages = frozenset(eval_stages or ())
        self.conn = sqlite3.connect(str(self.path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._line_no_hwm = 0
        self._init_schema(force=force_schema)

    # -- schema ---------------------------------------------------------------

    def _init_schema(self, *, force: bool) -> None:
        # Create-missing first so a torn create can never leave meta without
        # its sibling tables (the txn seeder reads events).
        self.conn.executescript(_SCHEMA)
        v = self._meta_get("schema_v")
        if v is not None and v != str(INDEX_SCHEMA_V):
            if not force:
                raise RuntimeError(
                    f"index schema_v {v} != {INDEX_SCHEMA_V} — "
                    "run rebuild_index() to recreate"
                )
            self._drop_all()
            self.conn.executescript(_SCHEMA)
        for k in _META_COUNTERS:
            self._meta_set_default(k, "0")
        self._meta_set_default("schema_v", str(INDEX_SCHEMA_V))

    def _drop_all(self) -> None:
        with self._txn():
            for t in _PROJECTION_TABLES + ("meta",):
                self.conn.execute(f"DROP TABLE IF EXISTS {t}")

    # -- meta ------------------------------------------------------------------

    def _meta_get(self, key: str, default=None):
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key=?", (key,)
        ).fetchone()
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

    # -- apply -------------------------------------------------------------------

    def apply_event(self, ev: dict) -> str:
        """Apply one ledger event. Returns 'applied' | 'replay' | 'quarantined'."""
        with self._txn():
            return self._apply_one(ev)

    def apply_events(self, evs) -> int:
        """Batched apply in a single transaction. Returns rows newly applied."""
        applied = 0
        with self._txn():
            for ev in evs:
                if self._apply_one(ev) == "applied":
                    applied += 1
        return applied

    def _key_of(self, ev: dict, *, runless: bool) -> tuple[int, int]:
        """Resolve the (run_seq, seq) dedup key.

        run events: explicit run_seq, else resolve via the runs table
        (run_registered precedes its cells in ledger order).
        run-less events: run_seq=-1 + index-assigned seq from a meta counter.
        Events with a run_seq but no seq (run_registered itself) also draw
        from the counter — assigned seqs are NEGATIVE so they can never
        collide with a minted seq on the same run_seq.
        """
        run_seq = ev.get("run_seq")
        if run_seq is None and not runless:
            run = ev.get("run")
            if run is not None:
                row = self.conn.execute(
                    "SELECT run_seq FROM runs WHERE run=?", (run,)
                ).fetchone()
                run_seq = row["run_seq"] if row else None
        if run_seq is None:
            run_seq = -1
        seq = ev.get("seq")
        if seq is None:
            seq = -self._meta_incr("runless_seq")
        return int(run_seq), int(seq)

    def _apply_one(self, ev: dict, *, runless: bool = False) -> str:
        if not isinstance(ev, dict):
            raise TypeError(f"event must be a dict, got {type(ev).__name__}")
        sha = events.content_hash(ev)
        if self.conn.execute(
            "SELECT 1 FROM dedupe WHERE payload_sha=?", (sha,)
        ).fetchone():
            self._meta_incr("dedup_skip")
            return "replay"
        run_seq, seq = self._key_of(ev, runless=runless)
        res = self.conn.execute(
            "INSERT OR IGNORE INTO events"
            "(line_no,run_seq,seq,payload_sha,payload,ts,type)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                self._next_line_no(), run_seq, seq, sha,
                events.dumps(ev), ev.get("ts"), ev.get("type"),
            ),
        )
        if res.rowcount == 0:
            # (run_seq,seq) already present — compare payload (§3.10.5).
            row = self.conn.execute(
                "SELECT payload_sha FROM events WHERE run_seq=? AND seq=?",
                (run_seq, seq),
            ).fetchone()
            if row is not None and row["payload_sha"] == sha:
                self._meta_incr("dedup_skip")
                self.conn.execute(
                    "INSERT OR IGNORE INTO dedupe(payload_sha) VALUES (?)", (sha,)
                )
                return "replay"
            self._quarantine(
                ev, sha, run_seq, seq, row["payload_sha"] if row else None
            )
            # Mark the rejected payload too: replays of it must not re-quarantine.
            self.conn.execute(
                "INSERT OR IGNORE INTO dedupe(payload_sha) VALUES (?)", (sha,)
            )
            return "quarantined"
        self.conn.execute(
            "INSERT INTO dedupe(payload_sha) VALUES (?)", (sha,)
        )
        self._project(ev, run_seq, seq)
        return "applied"

    def _quarantine(self, ev, sha, run_seq, seq, existing_sha) -> None:
        """Append a corruption row to ledger/quarantine.jsonl.

        Single O_APPEND os.write mirrors the torn-tail contract; index never
        takes ledger/.lock (it may be called from inside the emit critical
        section — taking it would deadlock).
        """
        rec = {
            "type": "index_conflict",
            "reason": "seq_conflict",
            "run_seq": run_seq,
            "seq": seq,
            "payload_sha": sha,
            "existing_sha": existing_sha,
            "payload": events.dumps(ev),
            "ts": round(time.time(), 3),
        }
        line = (events.dumps(rec) + "\n").encode("utf-8")
        qp = paths.quarantine_path()
        qp.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(qp, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._meta_incr("quarantine")

    # -- projections --------------------------------------------------------------

    def _project(self, ev: dict, run_seq: int, seq: int) -> None:
        t = ev.get("type")
        # Projection gate: only events carrying their REQUIRED key set feed
        # typed tables; everything still lands in the events mirror.
        req = events.REQUIRED.get(t)
        if req is not None and not req <= ev.keys():
            return
        cur = self.conn
        if t in (events.T_CELL_QUEUED, events.T_CELL_STARTED, events.T_CELL):
            self._proj_cell(cur, ev, t)
        elif t == events.T_CLAIM:
            self._proj_claim(cur, ev)
        elif t == events.T_ASSET:
            self._proj_asset(cur, ev)
        elif t == events.T_TOMBSTONE:
            self._upsert_vault_meta(cur, ev, verdict="tombstone",
                                    zone=ev.get("zone", "quar"))
        elif t == events.T_RUN_REGISTERED:
            cur.execute(
                "INSERT INTO runs(run,run_seq,kind,date,slug,spec_hash,ts_start)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(run) DO UPDATE SET"
                "  run_seq=excluded.run_seq, kind=excluded.kind,"
                "  date=excluded.date, slug=excluded.slug,"
                "  spec_hash=excluded.spec_hash, ts_start=excluded.ts_start",
                (
                    ev.get("run"), ev.get("run_seq"), ev.get("kind"),
                    ev.get("date"), ev.get("slug"), ev.get("spec_hash"),
                    ev.get("ts_start", ev.get("ts")),
                ),
            )
        # papers alias table: any event carrying both spellings (§3.2).
        if ev.get("id") and ev.get("idc"):
            src = ev.get("import_src") or ev.get("run") or "ledger"
            cur.execute(
                "INSERT OR IGNORE INTO papers(idc,id_raw,src) VALUES (?,?,?)",
                (ev["idc"], ev["id"], src),
            )

    def _proj_cell(self, cur, ev: dict, t: str) -> None:
        if t == events.T_CELL_QUEUED:
            status = _STATUS_QUEUED
        elif t == events.T_CELL_STARTED:
            status = _STATUS_STARTED
        else:
            status = ev.get("status")
        cur.execute(
            "INSERT INTO cells"
            "(idc,arm,up,variant,stage,last_run,last_seq,status,cat,fp,ts)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(idc,arm,up,variant,stage) DO UPDATE SET"
            "  last_run=excluded.last_run, last_seq=excluded.last_seq,"
            "  status=excluded.status, cat=excluded.cat,"
            "  fp=excluded.fp, ts=excluded.ts",
            (
                ev.get("idc"), ev.get("arm"), ev.get("up"), ev.get("variant"),
                ev.get("stage"), ev.get("run"), ev.get("seq"), status,
                ev.get("cat"), ev.get("fp"), ev.get("ts"),
            ),
        )
        if t == events.T_CELL_QUEUED:
            cur.execute(
                "INSERT INTO cases(run,seq,id,idc,payload,ts)"
                " VALUES (?,?,?,?,?,?)",
                (ev.get("run"), ev.get("seq"), ev.get("id"), ev.get("idc"),
                 events.dumps(ev), ev.get("ts")),
            )
        elif t == events.T_CELL:
            row = (
                ev.get("run"), ev.get("seq"), ev.get("id"), ev.get("idc"),
                ev.get("arm"), ev.get("up"), ev.get("variant"), ev.get("stage"),
                ev.get("status"), ev.get("cat"), ev.get("sig"), ev.get("code"),
                ev.get("fp"), ev.get("dur_s"), _j(ev.get("metrics")),
                _j(ev.get("errors")), ev.get("ts"),
            )
            cur.execute(
                "INSERT INTO records"
                "(run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
                " fp,dur_s,metrics,errors,ts)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row,
            )
            # eval lane: stage declared eval by the caller, or a row the
            # caller tagged eval=1 (import paths bypass the cell whitelist).
            if ev.get("stage") in self.eval_stages or ev.get("eval"):
                cur.execute(
                    "INSERT INTO eval_records"
                    "(run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
                    " fp,dur_s,metrics,errors,ts)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row,
                )

    def _proj_claim(self, cur, ev: dict) -> None:
        cur.execute(
            "INSERT INTO claims(idc,arm,variant,run,seq,op,slot,ts)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (ev.get("idc"), ev.get("arm"), ev.get("variant"), ev.get("run"),
             ev.get("seq"), ev.get("op"), ev.get("slot"), ev.get("ts")),
        )
        slot = ev.get("slot")
        if slot is None:
            return
        if ev.get("op") == "acquire":
            cur.execute(
                "INSERT INTO paid_slots(slot,idc,arm,variant,run,ts)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(slot) DO UPDATE SET"
                "  idc=excluded.idc, arm=excluded.arm,"
                "  variant=excluded.variant, run=excluded.run, ts=excluded.ts",
                (slot, ev.get("idc"), ev.get("arm"), ev.get("variant"),
                 ev.get("run"), ev.get("ts")),
            )
        elif ev.get("op") in ("release", "reap"):
            cur.execute("DELETE FROM paid_slots WHERE slot=?", (slot,))

    def _proj_asset(self, cur, ev: dict) -> None:
        cur.execute(
            "INSERT INTO assets"
            "(idc,arm,variant,kind,path,sha,bytes,state,run,seq,ts)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ev.get("idc"), ev.get("arm"), ev.get("variant"), ev.get("kind"),
             ev.get("path"), ev.get("sha"), ev.get("bytes"), ev.get("state"),
             ev.get("run"), ev.get("seq"), ev.get("ts")),
        )
        # Vault-managed byte kinds also feed the vault_meta credential view;
        # verdict is explicit when carried, else mapped from asset state.
        if ev.get("kind") in _VAULT_KINDS:
            self._upsert_vault_meta(
                cur, ev,
                verdict=ev.get("verdict") or ev.get("state"),
                zone=ev.get("zone"),
            )

    def _upsert_vault_meta(self, cur, ev: dict, *, verdict, zone) -> None:
        cur.execute(
            "INSERT INTO vault_meta"
            "(idc,arm,variant,altseq,zone,verdict,path,sha,ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(idc,arm,variant,altseq) DO UPDATE SET"
            "  zone=excluded.zone, verdict=excluded.verdict,"
            "  path=excluded.path, sha=excluded.sha, ts=excluded.ts",
            (ev.get("idc"), ev.get("arm"), ev.get("variant"),
             str(ev.get("altseq", "0")), zone, verdict,
             ev.get("path"), ev.get("sha"), ev.get("ts")),
        )

    # -- ingest --------------------------------------------------------------------

    def tail_ingest(self) -> int:
        """Consume complete lines from events.jsonl past the stored watermark.

        Watermark = offset just past the last swallowed '\\n'; an unterminated
        tail is left for the next pass. A shrunken file (locked
        truncate+rewrite) resets the watermark to 0 — dedupe-by-sha keeps the
        replay idempotent. Returns rows newly applied.
        """
        ep = paths.events_path()
        watermark = int(self._meta_get("watermark", "0") or 0)
        try:
            size = ep.stat().st_size
        except FileNotFoundError:
            return 0
        if watermark > size:
            watermark = 0
        with open(ep, "rb") as f:
            f.seek(watermark)
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return 0
        evs, bad = [], 0
        for line in data[: end + 1].split(b"\n"):
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:  # JSONDecodeError + UnicodeDecodeError
                bad += 1
                continue
            if not isinstance(ev, dict):
                bad += 1  # valid JSON, wrong shape — same skip-and-warn contract
                continue
            evs.append(ev)
        applied = self.apply_events(evs)
        with self._txn():
            if bad:
                self._meta_incr("bad_lines", bad)
            self._meta_set("watermark", str(watermark + end + 1))
        return applied

    # -- rebuild ---------------------------------------------------------------------

    def _iter_all_events(self):
        """Yield ledger events in authoritative append order.

        Prefers kernel.ledger.iter_all_events() (covers sealed segments +
        hot tail) when the ledger module is available; falls back to the
        hot-tail file via events.iter_jsonl. Items may be dicts or tuples
        carrying the dict — normalized here.
        """
        try:
            from kernel import ledger  # type: ignore[import-not-found]
        except ImportError:
            ledger = None
        it = getattr(ledger, "iter_all_events", None) if ledger else None
        if it is not None:
            for item in it():
                yield _norm_iter_item(item)
            return
        for _lineno, ev, _raw in events.iter_jsonl(paths.events_path()):
            yield ev

    def _ledger_watermark(self) -> int:
        try:
            from kernel import ledger  # type: ignore[import-not-found]
        except ImportError:
            ledger = None
        fn = getattr(ledger, "watermark_offset", None) if ledger else None
        if fn is not None:
            return int(fn())
        return _tail_newline_offset(paths.events_path())

    def rebuild(self) -> int:
        """Wipe all projection tables and replay the ledger in one txn.

        Refused while the kernel is active — claims are rebuilt from events
        and the rebuild window would have no live lease (§3.2). On success:
        sealed_gen += 1, watermark = fsync'd tail offset, .index-dirty
        cleared AFTER commit (a crash mid-rebuild rolls back to the old
        consistent index and leaves the flag alone). Returns rows applied.
        """
        if not _kernel_idle():
            raise RuntimeError(
                "kernel active — index rebuild refused "
                "(claims/done projections would go blind mid-run)"
            )
        applied = 0
        with self._txn():
            for t in _PROJECTION_TABLES:
                self.conn.execute(f"DELETE FROM {t}")
            for k in _META_COUNTERS:
                if k != "sealed_gen":  # generation only moves forward
                    self._meta_set(k, "0")
            self._line_no_hwm = 0
            for ev in self._iter_all_events():
                if ev is None:
                    self._meta_incr("bad_lines")
                    continue
                if self._apply_one(ev) == "applied":
                    applied += 1
            self._meta_incr("sealed_gen")
            self._meta_set("watermark", str(self._ledger_watermark()))
        # Commit succeeded — the index is sealed again; only now clear dirty.
        try:
            paths.index_dirty_path().unlink()
        except FileNotFoundError:
            pass
        return applied

    # -- queries --------------------------------------------------------------------

    def sealed_state(self) -> tuple[int, int]:
        """(sealed_gen, watermark) — the pair a run snapshots at startup."""
        return (
            int(self._meta_get("sealed_gen", "0") or 0),
            int(self._meta_get("watermark", "0") or 0),
        )

    def check_sealed(self, gen: int, min_offset: int) -> bool:
        """Fail-closed oracle input (§3.10.6): generation must match AND the
        index must have swallowed at least min_offset bytes AND no
        .index-dirty flag. False = caller must NOT issue 'absent→放行'."""
        if self.dirty():
            return False
        gen_now, watermark = self.sealed_state()
        return gen_now == int(gen) and watermark >= int(min_offset)

    def done(self, idc, arm, up, variant, stage, runs=None) -> bool:
        """Terminal status in cells for (idc,arm,up,variant,stage).

        Terminal = DONE ∪ KERNEL statuses — dedup/claimed/lost/unpaid_gate
        are terminal too (fail-closed direction for paid cells). When runs
        is given, the cell's latest state must come from one of those runs
        (needs-eval domain = this run ∪ spec.foreign_runs).
        """
        row = self.conn.execute(
            "SELECT status, last_run FROM cells"
            " WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=?",
            (idc, arm, up, variant, stage),
        ).fetchone()
        if row is None or row["status"] not in _TERMINAL:
            return False
        if runs is not None:
            if isinstance(runs, str):
                runs = {runs}
            if row["last_run"] not in runs:
                return False
        return True

    def last_cell(self, idc, arm, up, variant, stage) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM cells"
            " WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=?",
            (idc, arm, up, variant, stage),
        ).fetchone()
        return dict(row) if row else None

    def paid_pool(self) -> set[tuple]:
        """(idc,arm,variant) whose latest cell state is terminal ok|partial —
        the index leg of the paid dedup domain for plan snapshots (§3.10.6).
        Arm paidness is spec-side; callers intersect with their paid arms."""
        return {
            (r["idc"], r["arm"], r["variant"])
            for r in self.conn.execute(
                "SELECT DISTINCT idc,arm,variant FROM cells"
                " WHERE status IN ('ok','partial')"
            )
        }

    def vault_bytes_ok(self) -> set[tuple]:
        """(idc,arm,variant) with verified vault bytes (§3.8 dedup-hit
        verdicts: verified/primary/alt/quar/quarantine/adopted)."""
        marks = ",".join("?" for _ in _VAULT_BYTES_OK)
        return {
            (r["idc"], r["arm"], r["variant"])
            for r in self.conn.execute(
                f"SELECT DISTINCT idc,arm,variant FROM vault_meta"
                f" WHERE verdict IN ({marks})",
                tuple(sorted(_VAULT_BYTES_OK)),
            )
        }

    def active_claims(self) -> set[tuple]:
        """(idc,arm,variant) whose latest claim op is 'acquire'."""
        return {
            (r["idc"], r["arm"], r["variant"])
            for r in self.conn.execute(
                "SELECT c.idc, c.arm, c.variant FROM claims c"
                " WHERE c.op='acquire' AND c.rowid ="
                " (SELECT MAX(rowid) FROM claims c2"
                "  WHERE c2.idc=c.idc AND c2.arm=c.arm"
                "  AND c2.variant=c.variant)"
            )
        }

    def dedup_skip_count(self) -> int:
        return int(self._meta_get("dedup_skip", "0") or 0)

    def quarantine_count(self) -> int:
        return int(self._meta_get("quarantine", "0") or 0)

    # -- dirty flag -----------------------------------------------------------------

    def note_dirty(self, reason: str = "") -> None:
        """Set ledger/.index-dirty — emit path calls this when its sqlite
        write failed after the ledger line landed (§3.10.6 ③)."""
        p = paths.index_dirty_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f"{round(time.time(), 3)} {reason}\n", encoding="utf-8"
        )

    def dirty(self) -> bool:
        return paths.index_dirty_path().exists()

    # -- lifecycle --------------------------------------------------------------------

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def _norm_iter_item(item):
    """Normalize an iter_all_events item to an event dict (or None).

    Accepts dicts, (lineno, ev, raw) tuples like events.iter_jsonl yields,
    and (offset, ev) pairs — picks the dict member.
    """
    if isinstance(item, dict):
        return item
    if isinstance(item, (tuple, list)):
        for part in reversed(item):
            if isinstance(part, dict):
                return part
    return None


def rebuild_index(path=None) -> Index:
    """Open (tolerating schema-version drift) + rebuild + return the Index."""
    idx = Index(path, force_schema=True)
    idx.rebuild()
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
