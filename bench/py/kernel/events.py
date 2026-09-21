"""Event schema for ledger/events.jsonl — the sole source of truth.

Ten event types (design §3.1 + run_registered + lake_cell):

    run_registered {run, run_seq, kind, date, slug, spec_hash, ts_start}
    cell_queued    {run, seq, id, idc, arm, up, variant, stage, needs, fp_input}
    cell_started   {run, seq, id, idc, arm, up, variant, stage, claim_id, attempt}
    cell           {run, seq, id, idc, arm, up, variant, stage, status, dur_s,
                    metrics, errors, sig, code, fp}
    claim          {run, seq, id, idc, arm, variant, op, slot}
    asset          {run, seq, id, idc, arm, variant, kind, path, sha, bytes, state}
    tombstone      {id, idc, arm, variant, kind, reason, lost_run, ts}
    note           {run, seq, id?, text, level}
    finished       {run, seq, wall_s, counts, cost_usd}
    lake_cell      {id, idc, state, source, bytes, ts}

Rules baked here:
    - `id` is the writer's original spelling, `idc` the canon form — both always
      present on cell/asset/claim/tombstone rows.
    - Optional top-level keys whitelist (anything else is rejected):
      {queue_wait_s, auth_tripped, attempt}
    - metrics/errors payloads >4KB are offloaded to run derived/blobs/<sha>.json
      and replaced with {"$blob": sha, "$bytes": n}.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

SCHEMA_V = 1

T_RUN_REGISTERED = "run_registered"
T_CELL_QUEUED = "cell_queued"
T_CELL_STARTED = "cell_started"
T_CELL = "cell"
T_CLAIM = "claim"
T_ASSET = "asset"
T_TOMBSTONE = "tombstone"
T_NOTE = "note"
T_FINISHED = "finished"
T_LAKE_CELL = "lake_cell"

EVENT_TYPES = frozenset({
    T_RUN_REGISTERED, T_CELL_QUEUED, T_CELL_STARTED, T_CELL, T_CLAIM,
    T_ASSET, T_TOMBSTONE, T_NOTE, T_FINISHED, T_LAKE_CELL,
})

REQUIRED: dict[str, frozenset[str]] = {
    T_RUN_REGISTERED: frozenset({"run", "run_seq", "kind", "date", "slug", "spec_hash", "ts_start"}),
    T_CELL_QUEUED: frozenset({"run", "seq", "id", "idc", "arm", "up", "variant", "stage"}),
    T_CELL_STARTED: frozenset({"run", "seq", "id", "idc", "arm", "up", "variant", "stage"}),
    T_CELL: frozenset({"run", "seq", "id", "idc", "arm", "up", "variant", "stage", "status"}),
    T_CLAIM: frozenset({"run", "seq", "id", "idc", "arm", "variant", "op"}),
    T_ASSET: frozenset({"run", "seq", "id", "idc", "arm", "variant", "kind", "path", "state"}),
    T_TOMBSTONE: frozenset({"id", "idc", "arm", "variant", "kind", "reason"}),
    T_NOTE: frozenset({"run", "seq", "text", "level"}),
    T_FINISHED: frozenset({"run", "seq", "wall_s", "counts"}),
    T_LAKE_CELL: frozenset({"id", "idc", "state"}),
}

# Optional top-level keys whitelisted by the spec (§3.1); anything else is rejected.
OPTIONAL_WHITELIST = frozenset({"queue_wait_s", "auth_tripped", "attempt"})

# Keys every event may carry regardless of type.
COMMON_KEYS = frozenset({"type", "ts", "v", "run_seq", "import_src", "canon_drift_of"})

# Per-type optional keys — the extra-key whitelist applies to EVERY event
# type, not just cells. Registry-adjudication vocabulary (tail7/tail/cat/
# archive/resolved/resolve) is deliberately absent everywhere: a hostile
# ledger row carrying those keys would feed PapersRegistry._feed_row.
OPTIONAL_KEYS: dict[str, frozenset[str]] = {
    T_RUN_REGISTERED: frozenset(),
    T_CELL_QUEUED: frozenset({"needs", "fp_input"}),
    T_CELL_STARTED: frozenset({"claim_id"}),
    T_CELL: frozenset({
        "dur_s", "metrics", "errors", "sig", "code", "fp", "cat", "eval",
    }),
    T_CLAIM: frozenset({"slot", "fate"}),
    T_ASSET: frozenset({
        "sha", "bytes", "zone", "verdict", "altseq", "model", "source_run",
    }),
    T_TOMBSTONE: frozenset({"lost_run", "zone", "source_run"}),
    T_NOTE: frozenset({
        "id", "idc", "arm", "up", "variant", "stage", "kind", "safe_id",
    }),
    T_FINISHED: frozenset({"cost_usd", "accounting_ok"}),
    T_LAKE_CELL: frozenset({"source", "bytes"}),
}

# Status vocabulary (§3.1). DONE = terminal; RETRIABLE = may retry as a new attempt.
STATUS_DONE = frozenset({"ok", "partial", "clean", "fail", "reject", "fault", "dirty_pdf"})
STATUS_RETRIABLE = frozenset({"skip", "error"})
# Kernel-internal terminal statuses that never came from the instrument.
STATUS_KERNEL = frozenset({"dedup", "claimed", "lost", "unpaid_gate"})
ALL_STATUSES = STATUS_DONE | STATUS_RETRIABLE | STATUS_KERNEL

# Sub-classification carried in `cat` (errors[0].cat keeps its own semantics —
# 'upstream' there is the triage-exempt / fixloop-filter / retriable triple-use flag).
CATS = frozenset({
    "claimed", "regen_gate", "upstream-lost", "index_unsealed", "canon_drift",
    "orphan_adopt", "pause", "auth_dead", "budget", "paid_pool", "no_bulk_route",
})

CLAIM_OPS = frozenset({"acquire", "release", "reap"})
ASSET_KINDS = frozenset({"zh", "splice", "state", "pdf", "report"})
ASSET_STATES = frozenset({"pending", "verified", "tombstone", "adopted", "staged"})
LAKE_STATES = frozenset({
    "skeleton", "hydrating", "hydrated", "pinned", "raw_only", "failed", "evicted",
})
NOTE_LEVELS = frozenset({"info", "warn", "error"})

BLOB_OFFLOAD_THRESHOLD = 4 * 1024


class EventError(ValueError):
    pass


def make_event(etype: str, **kw) -> dict:
    """Construct + validate an event. `ts` and `v` filled automatically."""
    if etype not in EVENT_TYPES:
        raise EventError(f"unknown event type {etype!r}")
    ev = {"type": etype, "v": SCHEMA_V, "ts": kw.pop("ts", round(time.time(), 3))}
    ev.update(kw)
    validate(ev)
    return ev


def _type_ok(v, *types) -> bool:
    return v is None or (isinstance(v, types) and not isinstance(v, bool))


def validate(ev: dict) -> None:
    etype = ev.get("type")
    if etype not in EVENT_TYPES:
        raise EventError(f"bad event type {etype!r}: {ev!r}")
    missing = REQUIRED[etype] - ev.keys()
    if missing:
        raise EventError(f"{etype} missing keys {sorted(missing)}: {ev!r}")
    extra = (set(ev) - REQUIRED[etype] - OPTIONAL_WHITELIST - COMMON_KEYS
             - OPTIONAL_KEYS[etype])
    if extra:
        raise EventError(
            f"{etype} event has non-whitelisted keys {sorted(extra)}")
    if ev.get("v") != SCHEMA_V:
        raise EventError(f"bad schema v {ev.get('v')!r}")
    for k in ("seq", "run_seq"):
        if not _type_ok(ev.get(k), int):
            raise EventError(f"{etype} {k} must be int|None: {ev.get(k)!r}")
    if etype == T_CELL:
        if ev.get("status") not in ALL_STATUSES:
            raise EventError(f"unknown cell status {ev.get('status')!r}")
        for k in ("id", "idc", "arm", "up", "variant", "stage"):
            if not isinstance(ev.get(k), str):
                raise EventError(f"cell {k} must be str: {ev.get(k)!r}")
        if not _type_ok(ev.get("metrics"), dict):
            raise EventError("cell metrics must be dict|None")
        if not _type_ok(ev.get("errors"), list):
            raise EventError("cell errors must be list|None")
        if not _type_ok(ev.get("dur_s"), int, float):
            raise EventError("cell dur_s must be number|None")
        for k in ("sig", "code", "fp"):
            if not _type_ok(ev.get(k), str):
                raise EventError(f"cell {k} must be str|None")
        cat = ev.get("cat")
        if cat is not None and cat not in CATS:
            raise EventError(f"unknown cell cat {cat!r}")
        evl = ev.get("eval")
        if evl is not None and not isinstance(evl, (int, bool)):
            raise EventError("cell eval must be int/bool|None")
    if etype == T_CLAIM and ev.get("op") not in CLAIM_OPS:
        raise EventError(f"bad claim op {ev.get('op')!r}")
    if etype == T_ASSET:
        if ev.get("kind") not in ASSET_KINDS:
            raise EventError(f"bad asset kind {ev.get('kind')!r}")
        if ev.get("state") not in ASSET_STATES:
            raise EventError(f"bad asset state {ev.get('state')!r}")
    if etype == T_LAKE_CELL and ev.get("state") not in LAKE_STATES:
        raise EventError(f"bad lake state {ev.get('state')!r}")
    if etype == T_NOTE and ev.get("level") not in NOTE_LEVELS:
        raise EventError(f"bad note level {ev.get('level')!r}")


def dumps(ev: dict) -> str:
    """Canonical single-line serialization (deterministic for hashing)."""
    return json.dumps(ev, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(ev: dict) -> str:
    return hashlib.sha256(dumps(ev).encode("utf-8")).hexdigest()


def maybe_offload(ev: dict, blob_dir: Path | None) -> dict:
    """Offload oversized metrics/errors payloads to blob_dir/<sha>.json.

    Returns the (possibly rewritten) event. No-op when blob_dir is None or
    payloads are under the threshold. Blobs are content-addressed and the
    write is atomic — a truncated blob is healed on the next offload, never
    pinned by a bare exists() check.
    """
    if blob_dir is None:
        return ev
    from kernel import fsutil
    ev = dict(ev)
    for field in ("metrics", "errors"):
        val = ev.get(field)
        if val is None or (isinstance(val, dict) and "$blob" in val):
            continue
        try:
            raw = json.dumps(
                val, ensure_ascii=False, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError):
            continue  # unserializable payload stays inline; dumps() in the
            # emit path surfaces the failure at write time, as before
        if len(raw) <= BLOB_OFFLOAD_THRESHOLD:
            continue
        sha = hashlib.sha256(raw).hexdigest()
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / f"{sha}.json"
        try:
            if blob_path.stat().st_size == len(raw):
                pass  # intact content-addressed blob — nothing to do
            else:
                fsutil.atomic_write(blob_path, raw)  # heal a truncated blob
        except OSError:
            fsutil.atomic_write(blob_path, raw)
        ev[field] = {"$blob": sha, "$bytes": len(raw)}
    return ev


def iter_jsonl(path: Path):
    """Tolerant reader: yields (lineno, event|None, raw_line).

    Bad lines yield event=None so callers can count/quarantine them — the
    read-side contract is skip-and-warn, never crash on a torn line.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                yield lineno, json.loads(line), line
            except json.JSONDecodeError:
                yield lineno, None, line


def is_terminal_cell(ev: dict) -> bool:
    """A cell event is terminal iff its status is not retriable."""
    return ev.get("type") == T_CELL and ev.get("status") in STATUS_DONE | STATUS_KERNEL
