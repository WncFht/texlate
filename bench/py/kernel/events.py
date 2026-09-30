"""Event schema for ledger/events.jsonl — the sole source of truth.

Eleven event types (design §3.1 + run_registered + lake_cell + case):

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
    lake_cell      {id, idc, state, source, bytes, pinned, manifested,
                    orphan, regen_cost, last_used_at, ts}
    case           {run, seq, id, idc, arm, up, variant, stage, payload}
                   — author per-sample eval rows (Ctx.emit_case); buffered
                   in the cell's terminal batch so a crashed cell leaves
                   no orphan cases, and projected into index ``cases``.

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
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
T_CASE = "case"

EVENT_TYPES = frozenset(
    {
        T_RUN_REGISTERED,
        T_CELL_QUEUED,
        T_CELL_STARTED,
        T_CELL,
        T_CLAIM,
        T_ASSET,
        T_TOMBSTONE,
        T_NOTE,
        T_FINISHED,
        T_LAKE_CELL,
        T_CASE,
    }
)

REQUIRED: dict[str, frozenset[str]] = {
    T_RUN_REGISTERED: frozenset(
        {"run", "run_seq", "kind", "date", "slug", "spec_hash", "ts_start"}
    ),
    T_CELL_QUEUED: frozenset(
        {"run", "seq", "id", "idc", "arm", "up", "variant", "stage"}
    ),
    T_CELL_STARTED: frozenset(
        {"run", "seq", "id", "idc", "arm", "up", "variant", "stage"}
    ),
    T_CELL: frozenset(
        {"run", "seq", "id", "idc", "arm", "up", "variant", "stage", "status"}
    ),
    T_CLAIM: frozenset({"run", "seq", "id", "idc", "arm", "variant", "op"}),
    T_ASSET: frozenset(
        {"run", "seq", "id", "idc", "arm", "variant", "kind", "path", "state"}
    ),
    T_TOMBSTONE: frozenset({"id", "idc", "arm", "variant", "kind", "reason"}),
    T_NOTE: frozenset({"run", "seq", "text", "level"}),
    T_FINISHED: frozenset({"run", "seq", "wall_s", "counts"}),
    T_LAKE_CELL: frozenset({"id", "idc", "state"}),
    T_CASE: frozenset({"run", "seq", "id", "idc", "payload"}),
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
    T_CELL: frozenset(
        {
            "dur_s",
            "metrics",
            "errors",
            "sig",
            "code",
            "fp",
            "cat",
            "eval",
        }
    ),
    T_CLAIM: frozenset({"slot", "fate"}),
    T_ASSET: frozenset(
        {
            "sha",
            "bytes",
            "zone",
            "verdict",
            "altseq",
            "model",
            "source_run",
        }
    ),
    T_TOMBSTONE: frozenset({"lost_run", "zone", "source_run"}),
    T_NOTE: frozenset(
        {
            "id",
            "idc",
            "arm",
            "up",
            "variant",
            "stage",
            "kind",
            "safe_id",
        }
    ),
    T_FINISHED: frozenset({"cost_usd", "accounting_ok"}),
    T_LAKE_CELL: frozenset(
        {
            "source",
            "bytes",
            "pinned",
            "manifested",
            "orphan",
            "regen_cost",
            "last_used_at",
        }
    ),
    T_CASE: frozenset({"arm", "up", "variant", "stage"}),
}

# Status vocabulary (§3.1). DONE = terminal; RETRIABLE = may retry as a new attempt.
STATUS_DONE = frozenset(
    {"ok", "partial", "clean", "fail", "reject", "fault", "dirty_pdf"}
)
STATUS_RETRIABLE = frozenset({"skip", "error"})
# Kernel-internal terminal statuses that never came from the instrument.
STATUS_KERNEL = frozenset({"dedup", "claimed", "lost", "unpaid_gate"})
ALL_STATUSES = STATUS_DONE | STATUS_RETRIABLE | STATUS_KERNEL

# Verdict-class subsets of DONE (§3.5): CLEAN statuses may vouch a pending
# copy for primary; FAIL = attempted-but-not-clean terminals. The paid-pool
# set {"ok","partial"} is deliberately narrower (doctor._PAID_OK) — 'clean'
# is an eval/compile verdict that carries no paid-byte proof.
STATUS_CLEAN = frozenset({"ok", "partial", "clean"})
STATUS_FAIL = STATUS_DONE - STATUS_CLEAN

#: 状态序数表 (高=好): fixloop_degraded 跨段退化判定与 rundiff 逐格迁移共用;
#: 表外词 (skip/error/...) 一律按 -1 计。
STATUS_RANK = {"clean": 3, "ok": 3, "partial": 2, "fail": 1, "reject": 0}

#: fixloop 终态词 → core 单 (规则面之外的引擎缺口)。
TERMINAL_WORDS = {"stuck", "max_rounds"}

# Sub-classification carried in `cat` (errors[0].cat keeps its own semantics —
# 'upstream' there is the triage-exempt / fixloop-filter / retriable triple-use flag).
CATS = frozenset(
    {
        "claimed",
        "regen_gate",
        "upstream-lost",
        "index_unsealed",
        "canon_drift",
        "orphan_adopt",
        "pause",
        "auth_dead",
        "budget",
        "paid_pool",
        "no_bulk_route",
    }
)

CLAIM_OPS = frozenset({"acquire", "release", "reap"})
ASSET_KINDS = frozenset({"zh", "splice", "state", "layoutqc", "pdf", "report"})
#: Vault-managed kinds (pdf/report are work-tree artifacts, never vaulted).
VAULT_KINDS = frozenset({"zh", "splice", "state", "layoutqc"})
#: Product-byte kinds the dedup/index layers track (layoutqc is qc sideband).
VAULT_BYTE_KINDS = frozenset({"zh", "splice", "state"})
ASSET_STATES = frozenset({"pending", "verified", "tombstone", "adopted", "staged"})
LAKE_STATES = frozenset(
    {
        "skeleton",
        "hydrating",
        "hydrated",
        "pinned",
        "raw_only",
        "failed",
        "evicted",
        "empty",
    }
)
NOTE_LEVELS = frozenset({"info", "warn", "error"})

BLOB_OFFLOAD_THRESHOLD = 4 * 1024


class EventError(ValueError):
    pass


def make_event(etype: str, **kw) -> dict:
    """Construct + validate an event. `ts` and `v` filled automatically."""
    if etype not in EVENT_TYPES:
        msg = f"unknown event type {etype!r}"
        raise EventError(msg)
    ev = {"type": etype, "v": SCHEMA_V, "ts": kw.pop("ts", round(time.time(), 3))}
    ev.update(kw)
    validate(ev)
    return ev


def _type_ok(v, *types) -> bool:
    return v is None or (isinstance(v, types) and not isinstance(v, bool))


# Required string fields per type — a structural field that is present but
# the wrong type (run=None, id=42, arm=["x"]) is as corrupting as a missing
# one: projections key on them.
_STR_REQ: dict[str, tuple[str, ...]] = {
    T_RUN_REGISTERED: ("run", "kind", "date", "slug", "spec_hash"),
    T_CELL_QUEUED: ("run", "id", "idc", "arm", "up", "variant", "stage"),
    T_CELL_STARTED: ("run", "id", "idc", "arm", "up", "variant", "stage"),
    T_CELL: ("run", "id", "idc", "arm", "up", "variant", "stage"),
    T_CLAIM: ("run", "id", "idc", "arm", "variant"),
    T_ASSET: ("run", "id", "idc", "arm", "variant", "kind", "path", "state"),
    T_TOMBSTONE: ("id", "idc", "arm", "variant", "kind", "reason"),
    T_NOTE: ("run", "text"),
    T_FINISHED: ("run",),
    T_LAKE_CELL: ("id", "idc", "state"),
    T_CASE: ("run", "id", "idc"),
}

# Optional string fields per type (None allowed).
_STR_OPT: dict[str, tuple[str, ...]] = {
    T_CELL_STARTED: ("claim_id",),
    T_CELL: ("sig", "code", "fp"),
    T_CLAIM: ("slot", "fate"),
    T_ASSET: ("sha", "zone", "verdict", "model", "source_run", "altseq"),
    T_TOMBSTONE: ("lost_run", "zone", "source_run"),
    T_NOTE: ("id", "idc", "arm", "up", "variant", "stage", "kind", "safe_id"),
    T_LAKE_CELL: ("source", "regen_cost"),
    T_CASE: ("arm", "up", "variant", "stage"),
}

# Optional numeric fields (int|float, bool excluded by _type_ok).
_NUM_OPT: dict[str, tuple[str, ...]] = {
    T_RUN_REGISTERED: ("ts_start",),
    T_CELL: ("dur_s",),
    T_FINISHED: ("cost_usd",),
    T_ASSET: ("bytes",),
    T_LAKE_CELL: ("bytes", "last_used_at"),
}


def validate(ev: dict) -> None:
    etype = ev.get("type")
    if etype not in EVENT_TYPES:
        msg = f"bad event type {etype!r}: {ev!r}"
        raise EventError(msg)
    missing = REQUIRED[etype] - ev.keys()
    if missing:
        msg = f"{etype} missing keys {sorted(missing)}: {ev!r}"
        raise EventError(msg)
    extra = (
        set(ev)
        - REQUIRED[etype]
        - OPTIONAL_WHITELIST
        - COMMON_KEYS
        - OPTIONAL_KEYS[etype]
    )
    if extra:
        msg = f"{etype} event has non-whitelisted keys {sorted(extra)}"
        raise EventError(msg)
    if ev.get("v") != SCHEMA_V:
        msg = f"bad schema v {ev.get('v')!r}"
        raise EventError(msg)
    for k in ("seq", "run_seq"):
        if not _type_ok(ev.get(k), int):
            msg = f"{etype} {k} must be int|None: {ev.get(k)!r}"
            raise EventError(msg)
    if not _type_ok(ev.get("ts"), int, float):
        msg = f"{etype} ts must be number|None: {ev.get('ts')!r}"
        raise EventError(msg)
    if not _type_ok(ev.get("queue_wait_s"), int, float):
        msg = "queue_wait_s must be number|None"
        raise EventError(msg)
    if not _type_ok(ev.get("attempt"), int):
        msg = "attempt must be int|None"
        raise EventError(msg)
    for k in ("import_src", "canon_drift_of"):
        if not _type_ok(ev.get(k), str):
            msg = f"{etype} {k} must be str|None"
            raise EventError(msg)
    at = ev.get("auth_tripped")
    if at is not None and not isinstance(at, (bool, int)):
        msg = "auth_tripped must be bool|int|None"
        raise EventError(msg)
    for k in _STR_REQ[etype]:
        if not isinstance(ev.get(k), str):
            msg = f"{etype} {k} must be str: {ev.get(k)!r}"
            raise EventError(msg)
    for k in _STR_OPT.get(etype, ()):
        if not _type_ok(ev.get(k), str):
            msg = f"{etype} {k} must be str|None"
            raise EventError(msg)
    for k in _NUM_OPT.get(etype, ()):
        if not _type_ok(ev.get(k), int, float):
            msg = f"{etype} {k} must be number|None"
            raise EventError(msg)
    if etype == T_CELL_QUEUED and not _type_ok(ev.get("needs"), list):
        msg = "cell_queued needs must be list|None"
        raise EventError(msg)
    if etype == T_FINISHED:
        if not isinstance(ev.get("wall_s"), (int, float)) or isinstance(
            ev.get("wall_s"), bool
        ):
            msg = "finished wall_s must be number"
            raise EventError(msg)
        if not isinstance(ev.get("counts"), dict):
            msg = "finished counts must be dict"
            raise EventError(msg)
        ao = ev.get("accounting_ok")
        if ao is not None and not isinstance(ao, (bool, int)):
            msg = "accounting_ok must be bool|int|None"
            raise EventError(msg)
    if etype == T_CELL:
        if ev.get("status") not in ALL_STATUSES:
            msg = f"unknown cell status {ev.get('status')!r}"
            raise EventError(msg)
        if not _type_ok(ev.get("metrics"), dict):
            msg = "cell metrics must be dict|None"
            raise EventError(msg)
        if not _type_ok(ev.get("errors"), list):
            msg = "cell errors must be list|None"
            raise EventError(msg)
        cat = ev.get("cat")
        if cat is not None and cat not in CATS:
            msg = f"unknown cell cat {cat!r}"
            raise EventError(msg)
        evl = ev.get("eval")
        if evl is not None and not isinstance(evl, (int, bool)):
            msg = "cell eval must be int/bool|None"
            raise EventError(msg)
    if etype == T_CLAIM and ev.get("op") not in CLAIM_OPS:
        msg = f"bad claim op {ev.get('op')!r}"
        raise EventError(msg)
    if etype == T_ASSET:
        if ev.get("kind") not in ASSET_KINDS:
            msg = f"bad asset kind {ev.get('kind')!r}"
            raise EventError(msg)
        if ev.get("state") not in ASSET_STATES:
            msg = f"bad asset state {ev.get('state')!r}"
            raise EventError(msg)
    if etype == T_LAKE_CELL:
        if ev.get("state") not in LAKE_STATES:
            msg = f"bad lake state {ev.get('state')!r}"
            raise EventError(msg)
        for k in ("pinned", "manifested", "orphan"):
            if ev.get(k) is not None and not isinstance(ev.get(k), bool):
                msg = f"lake_cell {k} must be bool|None"
                raise EventError(msg)
    if etype == T_NOTE and ev.get("level") not in NOTE_LEVELS:
        msg = f"bad note level {ev.get('level')!r}"
        raise EventError(msg)
    if etype == T_CASE and not isinstance(ev.get("payload"), dict):
        msg = "case payload must be a dict"
        raise EventError(msg)


def dumps(ev: dict, *, default=None) -> str:
    """Canonical single-line serialization (deterministic for hashing).

    ``default`` passes through to ``json.dumps`` — importer rows carry
    arbitrary scraped values that need ``default=str`` coercion."""
    return json.dumps(
        ev, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=default
    )


def content_hash(ev: dict) -> str:
    return hashlib.sha256(dumps(ev).encode("utf-8")).hexdigest()


_BLOB_SHA_RE = re.compile(r"[0-9a-f]{64}")


def is_blob_marker(val) -> bool:
    """Well-formed offload marker — exactly {"$blob": <64-hex>, "$bytes":
    int}. A dict that merely CONTAINS a "$blob" key is payload, not a
    marker: letting it pass would keep an attacker-chosen blob reference
    inline for export to resolve."""
    return (
        isinstance(val, dict)
        and set(val) == {"$blob", "$bytes"}
        and isinstance(val["$blob"], str)
        and _BLOB_SHA_RE.fullmatch(val["$blob"]) is not None
        and isinstance(val["$bytes"], int)
        and not isinstance(val["$bytes"], bool)
    )


def maybe_offload(ev: dict, blob_dir: Path | None) -> dict:
    """Offload oversized metrics/errors payloads to blob_dir/<sha>.json.

    Returns the (possibly rewritten) event. No-op when blob_dir is None or
    payloads are under the threshold. Blobs are content-addressed and the
    write is atomic — an existing blob is trusted only after its bytes
    re-hash to the marker sha, so truncation AND same-size corruption both
    heal on the next offload.
    """
    if blob_dir is None:
        return ev
    from kernel import fsutil

    ev = dict(ev)
    for field in ("metrics", "errors"):
        val = ev.get(field)
        if val is None or is_blob_marker(val):
            continue
        try:
            raw = json.dumps(val, ensure_ascii=False, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError):
            continue  # unserializable payload stays inline; dumps() in the
            # emit path surfaces the failure at write time, as before
        if len(raw) <= BLOB_OFFLOAD_THRESHOLD:
            continue
        sha = hashlib.sha256(raw).hexdigest()
        blob_dir.mkdir(parents=True, exist_ok=True)
        blob_path = blob_dir / f"{sha}.json"
        try:
            intact = fsutil._sha256_file(blob_path) == sha
        except OSError:
            intact = False
        if not intact:
            fsutil.atomic_write(blob_path, raw)
        ev[field] = {"$blob": sha, "$bytes": len(raw)}
    return ev


def iter_jsonl(path: Path):
    """Tolerant reader: yields (lineno, event|None, raw_line).

    Bad lines yield event=None so callers can count/quarantine them — the
    read-side contract is skip-and-warn, never crash on a torn line.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        for lineno, raw_line in enumerate(f, 1):
            line = raw_line.rstrip("\n")
            if not line:
                continue
            try:
                yield lineno, json.loads(line), line
            except json.JSONDecodeError:
                yield lineno, None, line


def is_terminal_cell(ev: dict) -> bool:
    """A cell event is terminal iff its status is not retriable."""
    return ev.get("type") == T_CELL and ev.get("status") in STATUS_DONE | STATUS_KERNEL
