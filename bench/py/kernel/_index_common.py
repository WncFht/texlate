"""index 共享底层 —— schema 常量/DDL 全文 + 跨叶共享探针 (原 kernel.index 顶层常量区)。

- ``INDEX_SCHEMA_V`` / ``_SCHEMA`` — 投影 schema 版本与建表 DDL 全文。
- ``_STATUS_QUEUED`` / ``_STATUS_STARTED`` / ``_TERMINAL`` — cells 投影的
  合成状态与终态集 (DONE ∪ KERNEL)。
- ``_VAULT_BYTES_OK`` / ``_VAULT_KINDS`` — dedup oracle 的 vault
  verdict/kind 域 (§3.8)。
- ``_META_COUNTERS`` / ``_PROJECTION_TABLES`` — rebuild 复位面。
- ``_j`` — metrics/errors JSON 列编码; ``_file_tag`` — events.jsonl
  inode 身份 (byte watermark 只对原 inode 有意义); ``_sealed_segment_names``
  — sealed/ 段名集; ``_kernel_idle`` — .kernel-active NB-flock 活性探针。
  消费方横跨 store/replay/query 三叶, 落公共叶免环; 本叶不 import 兄弟叶。
"""

from __future__ import annotations

import json
from pathlib import Path

from kernel import events, paths

INDEX_SCHEMA_V = 1

# Synthetic cell-projection states for non-terminal lifecycle events.
_STATUS_QUEUED = "queued"
_STATUS_STARTED = "started"

# Terminal statuses: instrument DONE set ∪ kernel-internal terminal statuses.
_TERMINAL = events.STATUS_DONE | events.STATUS_KERNEL

# vault_meta verdicts whose bytes count as present for the dedup oracle.
# §3.8: primary/quarantine/alt all dedup-hit; pending is treated as no-bytes;
# tombstone is a regen_gate hard stop (handled upstream, excluded here).
# "verified"/"adopted" cover asset-state vocabulary projected into verdicts.
_VAULT_BYTES_OK = frozenset(
    {"verified", "primary", "alt", "quar", "quarantine", "adopted"}
)

# Asset kinds that are vault-managed bytes (pdf/report are work-tree artifacts,
# layoutqc is qc sideband — neither joins the dedup projection).
_VAULT_KINDS = events.VAULT_BYTE_KINDS

# meta keys reset to "0" on rebuild (schema_v is preserved).
_META_COUNTERS = (
    "sealed_gen",
    "watermark",
    "dedup_skip",
    "quarantine",
    "runless_seq",
    "bad_lines",
)

# Every projection table wiped by rebuild (meta is handled separately).
_PROJECTION_TABLES = (
    "events",
    "dedupe",
    "cells",
    "records",
    "eval_records",
    "cases",
    "assets",
    "claims",
    "paid_slots",
    "vault_meta",
    "papers",
    "runs",
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
    run TEXT, seq INTEGER, id TEXT, idc TEXT, stage TEXT,
    payload TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS assets (
    idc TEXT, arm TEXT, variant TEXT, kind TEXT, path TEXT, sha TEXT,
    bytes INTEGER, state TEXT, run TEXT, seq INTEGER, ts REAL
);
CREATE TABLE IF NOT EXISTS claims (
    idc TEXT, arm TEXT, variant TEXT, run TEXT, seq INTEGER,
    op TEXT, slot TEXT, fate TEXT, ts REAL
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
CREATE INDEX IF NOT EXISTS idx_events_line_no ON events(line_no);
CREATE INDEX IF NOT EXISTS idx_records_cell
    ON records(idc, arm, up, variant, stage);
CREATE INDEX IF NOT EXISTS idx_claims_key ON claims(idc, arm, variant);
"""


def _j(val):
    """JSON-encode a payload column (metrics/errors); NULL stays NULL."""
    if val is None:
        return None
    return json.dumps(val, ensure_ascii=False, sort_keys=True)


def _file_tag(path: Path) -> str:
    """``st_dev:st_ino`` — the inode identity a byte watermark belongs to.

    Byte offsets are only meaningful against the inode they were measured
    on: a seal renames the hot tail away and recreates it, so a stored
    watermark compared against a different inode silently misaligns.
    Empty string when the file is absent.
    """
    try:
        st = Path(path).stat()
    except OSError:
        return ""
    return f"{st.st_dev}:{st.st_ino}"


def _sealed_segment_names() -> set:
    """Segment stems (``events-*.jsonl``) present in sealed/ — a raw
    segment and its ``.zst`` product share the stem."""
    sdir = paths.sealed_dir()
    names: set = set()
    if not sdir.is_dir():
        return names
    for p in sdir.iterdir():
        n = p.name
        if n.endswith(".jsonl.zst"):
            names.add(n[: -len(".zst")])
        elif n.endswith(".jsonl"):
            names.add(n)
    return names


def _kernel_idle() -> bool:
    """True when no kernel is running — an NB-flock probe on the
    .kernel-active sentinel (a dead kernel's flock is always released, so the
    probe is the authoritative life/death proof)."""
    from kernel import locks

    return locks.kernel_idle()
