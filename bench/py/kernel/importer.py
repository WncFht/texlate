"""Phase 1 import pipeline — legacy data plane -> trizone ledger.

Implements the import scope of docs/dev/bench-redesign-v2-trizone.md §6
Phase 1 with the §3.3 ordering contract and the §3.10.7 canon gate:

- Sources: bench.db (records/eval_records/cases/cells tables), worktree
  records*.jsonl / cases.jsonl files, and the zh-store manifest.jsonl +
  byte census.
- Idempotent by line-content hash: every emitted event is deterministic
  (timestamps come from row data, never wall clock), so a re-import
  produces identical payload_shas and is filtered against the index
  dedupe table BEFORE hitting the ledger. Quarantine rows get the same
  treatment via a sha-set over quarantine.jsonl.
- Secrets are redacted on the way in (R1): the gateway key substring
  '240127', tailscale 100.64.0.0/10 addresses, and auth-ish JSON field
  values are replaced with {"$redact": sha256_of_original} so the ledger
  keeps verifiability without keeping the secret.
- Canon gate (§3.10.7): canon_id() Ok -> event carries idc;
  Ambig/Invalid -> the whole row goes to ledger/quarantine.jsonl.
- Ordering (§3.3): runs sort by (run_meta.started_at -> dir mtime ->
  run name); run_seq is minted in that order so the (run_seq, seq)
  total order approximates chronology. Order-sensitive cell keys (same
  key, multiple terminal statuses) are reported to quarantine and
  resolved CONSERVATIVE: paid cells prefer done-ish terminal
  (ok|partial|clean — protects quota), free cells prefer non-terminal
  (protects truth — the cell reruns).
- Writes go through ledger.emit_batch in ~5000-event chunks (never
  per-row emit() — the 197k-line/7min trap) and index.apply_events in
  the same chunks. Ledger stays the source of truth; the index is
  disposable.

Known simplifications (flagged, not hidden):
- Paidness is an ARM property here: PAID_ARMS = {"real"}. bench.db has
  no per-stage paid flag; arm=='real' is the gateway arm.
- eval_records/cases/cells rows become stage='<table>' cell events with
  the whole (redacted) raw payload in metrics; status = row.status /
  raw.status / 'ok'. A non-vocab status maps to 'fault' + the original
  in metrics._orig_status (fail-loud, never silently retriable).
- records rows with NULL status map to 'fault' (conservative terminal);
  case-type rows default to 'ok' (the row's existence IS the record).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from kernel import events, fsutil, idnorm, ledger, paths
from kernel.events import iter_jsonl
from kernel.fsutil import dir_size

# ---------------------------------------------------------------------------
# Tunables / vocab
# ---------------------------------------------------------------------------

EMIT_CHUNK = 5000

# bench.db has no paid flag per stage; the gateway arm is 'real'.
PAID_ARMS = frozenset({"real"})

# scan_root sweep patterns: flat ledgers + case files + recovered
# eval/cells ledgers; stagerun stage files (records/{stage}.jsonl)
# are picked up via records/ dir contents in import_all.
_SCAN_PATTERNS = ("records*.jsonl", "cases.jsonl",
                  "eval-records*.jsonl", "cells*.jsonl")

# Conservative-resolution preference sets (§3.3).
_DONE_ISH = frozenset({"ok", "partial", "clean"})
_NEG_TERM = frozenset({"fail", "fault", "reject", "dirty_pdf"})

# --- secret patterns --------------------------------------------------------
# The known gateway key prefix — substring scan, wherever it appears.
_KEY_SUBSTR = "240127"
# tailscale 100.64.0.0/10 — needs all four octets so plain floats like
# "seconds": 100.6 never match. No leading \b: an IP embedded in a token
# ('node100.64.1.5') is still the IP.
_TAILSCALE_RE = re.compile(
    r"100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])"
    r"\.(?:[0-9]{1,3})\.(?:[0-9]{1,3})\b"
)
# Auth-ish JSON field names — normalized (separators stripped, lowered) so
# "api-key"/"api_key"/"apikey" all hit. Deliberately exact-match: 'tokens',
# 'prompt_tokens', 'file_cache_key', 'dedup_key' are legit metric fields.
_AUTH_KEYS_RAW = frozenset({
    "authorization", "api_key", "apikey", "x-api-key", "token",
    "access_token", "refresh_token", "id_token", "passwd", "password",
    "secret", "client_secret", "auth", "bearer", "cookie", "set-cookie",
    "private_key", "credentials", "session_key", "gateway_key",
    "auth_token", "api_secret", "secret_key", "session_token",
    "bearer_token", "app_key", "private_token",
})
_SEP_RE = re.compile(r"[-_.\s]+")
_AUTH_KEYS = frozenset(_SEP_RE.sub("", k) for k in _AUTH_KEYS_RAW)

# Exported per the module contract — introspectable redaction surface.
SECRET_PATTERNS = {
    "substrings": (_KEY_SUBSTR,),
    "regexes": (_TAILSCALE_RE,),
    "auth_keys": _AUTH_KEYS,
}

_DB_TABLES = ("records", "eval_records", "cases", "cells")

_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def _parse_ts(val) -> float | None:
    """ISO-ish string or epoch number -> epoch float. Naive = UTC."""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str) or not val.strip():
        return None
    s = val.strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._-")
    return s or "run"


def _json_or_raw(text):
    """Parse a JSON text column; return the raw string when not JSON."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _jcanon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


# ---------------------------------------------------------------------------
# Redaction (R1 — secrets never reach the ledger)
# ---------------------------------------------------------------------------

def _authish(key) -> bool:
    return isinstance(key, str) and _SEP_RE.sub("", key).lower() in _AUTH_KEYS


def _scalar_secret(s: str) -> bool:
    return _KEY_SUBSTR in s or bool(_TAILSCALE_RE.search(s))


def _redact_str(s: str) -> str:
    """Scalar redaction for fields that must stay strings (identity/vocab
    fields like run/stage/arm) — in-place placeholder, deterministic so a
    whole run's rows still group under one (mangled) name."""
    if isinstance(s, str) and _scalar_secret(s):
        return f"$redact-{_sha(s)[:16]}"
    return s


def redact(obj) -> tuple:
    """Deep-redact secrets out of an imported payload.

    Returns (redacted_copy, n_redactions). Any scalar containing the
    gateway-key substring or a tailscale IP is replaced wholesale with
    {"$redact": sha256_of_original}; a dict entry whose KEY is auth-ish
    (authorization/api_key/token/passwd/…) loses its entire value the
    same way. sha256 keeps the original verifiable without keeping it.

    Dict KEYS are scanned too — a secret used as a key is still a secret —
    and non-JSON-native values (bytes, sets, …) are replaced by a
    content-free placeholder so one hostile column can't wedge the import.
    """
    n = 0

    def walk(o):
        nonlocal n
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                kk = k if isinstance(k, str) else str(k)
                if _authish(kk):
                    # key NAME is vocabulary ('api_key'), not a secret —
                    # keep it readable, drop the whole value
                    n += 1
                    out[kk] = {"$redact": _sha(_jcanon(v))}
                elif _scalar_secret(kk):
                    # the key ITSELF is the secret (a dict keyed by a token
                    # or a tailscale host) — rename, drop the value
                    n += 1
                    out[f"$redact:{_sha(kk)[:16]}"] = {
                        "$redact": _sha(_jcanon(v))}
                else:
                    out[kk] = walk(v)
            return out
        if isinstance(o, (list, tuple)):
            return [walk(x) for x in o]
        if isinstance(o, str):
            if _scalar_secret(o):
                n += 1
                return {"$redact": _sha(o)}
            return o
        if isinstance(o, bool):
            return o
        if isinstance(o, (int, float)):
            s = repr(o) if isinstance(o, float) else str(o)
            if _KEY_SUBSTR in s:
                n += 1
                return {"$redact": _sha(s)}
            return o
        if isinstance(o, (bytes, bytearray)):
            n += 1
            return {"$nonjson": "bytes", "len": len(o),
                    "sha256": hashlib.sha256(bytes(o)).hexdigest()}
        if o is None:
            return o
        # sets, datetimes, other non-JSON scalars — never ship content,
        # keep a verifiable fingerprint
        n += 1
        return {"$nonjson": type(o).__name__,
                "sha256": _sha(repr(o)[:8192])}

    return walk(obj), n


# ---------------------------------------------------------------------------
# Quarantine (ledger/quarantine.jsonl — forensic, append-only, deduped by sha)
# ---------------------------------------------------------------------------

def _load_quar_shas() -> set[str]:
    seen = set()
    p = paths.quarantine_path()
    if p.exists():
        with open(p, "rb") as f:
            for raw_ln in f:
                ln = raw_ln.rstrip(b"\n")
                if ln:
                    seen.add(hashlib.sha256(ln).hexdigest())
    return seen


def _append_quar(row: dict, seen: set[str], dry: bool) -> bool:
    """Append one quarantine row (single O_APPEND write + fsync, same
    torn-tail contract as index._quarantine). Deduped by line sha so a
    re-import doesn't re-spam identical rows."""
    line = (events.dumps(row) + "\n").encode("utf-8")
    sha = hashlib.sha256(line.rstrip(b"\n")).hexdigest()
    if sha in seen:
        return False
    seen.add(sha)
    if dry:
        return True
    p = paths.quarantine_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


# ---------------------------------------------------------------------------
# Status + canon gates
# ---------------------------------------------------------------------------

def _status_of(raw_status, *, default: str) -> tuple[str, str | None]:
    """Map a source status to the kernel vocab.

    -> (status, orig_status | None). Unknown non-empty statuses become
    'fault' (fail-loud terminal, never silently retriable) and the
    original is preserved for metrics._orig_status.
    """
    s = raw_status if isinstance(raw_status, str) else ""
    if s in events.STATUS_KERNEL:
        # Kernel-internal masks (dedup/claimed/lost/unpaid_gate) are
        # projections, not work outcomes — a source row carrying one would
        # land as a terminal mask and falsely gate retries. Fail loud.
        return "fault", s
    if s in events.ALL_STATUSES:
        return s, None
    if not s:
        return default, None
    return "fault", s


def _canon_gate(id_raw, registry) -> idnorm.CanonResult:
    try:
        return idnorm.canon_id(id_raw, registry)
    except Exception:
        # canon_id is total/pure by contract — but an import must never die
        # on a hostile id; treat any failure as invalid.
        return idnorm.CanonResult(idnorm.INVALID, reason="invalid:exception")


# ---------------------------------------------------------------------------
# Run registration
# ---------------------------------------------------------------------------

def _first_shard_event(rdir: Path):
    """First parseable event of a run-dir events.jsonl shard — the
    run_registered line mint_run_seq wrote. None when absent/empty."""
    p = Path(rdir) / "events.jsonl"
    if not p.exists():
        return None
    try:
        for _ln, ev, _raw in iter_jsonl(p):
            if ev is not None:
                return ev
    except OSError:
        return None
    return None


def _ensure_import_run(index, run_name: str, *, date: str, slug: str,
                       spec_hash: str, dry: bool):
    """Resolve the run's run_seq, minting once.

    -> (run_seq, run_dir, minted_now, rr_event | None)

    rr_event is the ledger's own run_registered line — already written by
    mint (or recovered from the shard after a crash) so it must be
    applied to the index but NEVER re-emitted to the ledger.
    """
    rdir = paths.run_dir("import", date, slug)

    def _ret(run_seq: int, minted: bool, rr_ev):
        # The run .lock is minted once and never unlinked (R21) — import
        # runs mint through ledger.mint_run_seq, not runs.mint, so the
        # immortal lock file is the importer's own job. Touch on every
        # non-dry resolution: self-heals dirs minted before this rule.
        if rdir.is_dir():
            (rdir / ".lock").touch()
        return run_seq, rdir, minted, rr_ev

    if index is not None:
        row = index.conn.execute(
            "SELECT run_seq, kind, date, slug FROM runs WHERE run=?",
            (run_name,),
        ).fetchone()
        if row is not None:
            # rebuild the shard dir from the MINTED (kind,date,slug) — a
            # re-import after the source's date moved must land in the
            # run's original shard, not split events across two dirs.
            if all(isinstance(row[k], str) for k in ("kind", "date", "slug")):
                rdir = paths.run_dir(row["kind"], row["date"], row["slug"])
            return _ret(int(row["run_seq"]), False, None)
    # Ledger-side recovery: the shard exists => a previous mint happened
    # (e.g. a crash between mint and index-apply). Reuse, never re-mint.
    # Gate on the run_registered SHAPE — a shard whose first line is a
    # stray cell event (torn rr write, reused dir) must not crash on a
    # missing run_seq or bind the wrong run's identity.
    rr = _first_shard_event(rdir)
    if (
        rr is not None
        and rr.get("type") == events.T_RUN_REGISTERED
        and rr.get("run") == run_name
        and isinstance(rr.get("run_seq"), int)
        and not isinstance(rr.get("run_seq"), bool)
    ):
        return _ret(int(rr["run_seq"]), False, rr)
    if dry:
        return -1, rdir, False, None
    run_seq = ledger.mint_run_seq(run_name, "import", date, slug, spec_hash)
    return _ret(run_seq, True, _first_shard_event(rdir))


# ---------------------------------------------------------------------------
# Row normalization — every source becomes the same `rec` shape:
#   {id, arm, up, variant, stage, status, dur_s, metrics, errors, sig,
#    code, queue_wait_s, ts, default_status, dedup_sig}
# ---------------------------------------------------------------------------

def _norm_db_record(row: dict, run_ts: float) -> dict:
    metrics = _json_or_raw(row.get("metrics"))
    errors = _json_or_raw(row.get("errors"))
    ts = None
    if isinstance(metrics, dict):
        ts = _parse_ts(metrics.get("xlat_ts") or metrics.get("ts"))
    sig = {k: v for k, v in row.items() if k not in ("rec_id", "run_id")}
    return {
        "id": row.get("id"),
        # the db's own adjudication column beats re-deriving canon from the
        # raw spelling — a bare tail the legacy pipeline already resolved
        # must not fall back to bare-tail-unknown quarantine.
        "canon_hint": row.get("id_canon") or None,
        "arm": row.get("arm") or "-",
        "up": row.get("upstream") or "-",
        "variant": "-",
        "stage": row.get("stage") or "records",
        "status": row.get("status"),
        "dur_s": row.get("dur_s"),
        "metrics": metrics,
        "errors": errors,
        "sig": row.get("sig"),
        "code": row.get("code") or None,
        "queue_wait_s": row.get("queue_wait_s"),
        "ts": ts if ts is not None else run_ts,
        "default_status": "fault",
        "dedup_sig": _jcanon(sig),
    }


def _norm_db_raw(table: str, row: dict, run_ts: float) -> dict:
    payload = _json_or_raw(row.get("raw"))
    if not isinstance(payload, dict):
        payload = {"_unparsed": payload}
    id_raw = (
        row.get("paper")
        or row.get("corpus")
        or payload.get("id")
        or payload.get("corpus")
        or payload.get("paper")
    )
    ts = _parse_ts(payload.get("ts")) or _parse_ts(row.get("ts"))
    return {
        "id": id_raw,
        "arm": payload.get("arm") or row.get("arm") or "-",
        "up": payload.get("upstream") or row.get("upstream") or "-",
        "variant": payload.get("variant") or row.get("variant") or "-",
        "stage": row.get("stage") or table,
        "status": row.get("status") or payload.get("status"),
        "dur_s": row.get("seconds") or payload.get("seconds"),
        "metrics": payload,
        "errors": payload.get("errors"),
        "sig": payload.get("sig"),
        "code": payload.get("code"),
        "queue_wait_s": payload.get("queue_wait_s"),
        "ts": ts if ts is not None else run_ts,
        "default_status": "ok",
        "eval": table == "eval_records",
        # every row column belongs to the dedup signature — two rows sharing
        # a raw payload but differing in status/seconds must both land, else
        # the later status update is silently dropped.
        "dedup_sig": _jcanon(
            {k: v for k, v in row.items()
             if k not in ("rec_id", "run_id")}),
    }


def _norm_jsonl_row(row: dict, *, fname: str, file_ts: float,
                    stage_map: dict | None) -> dict:
    """A worktree records*/cases line -> normalized rec.

    Case-shaped lines (no 'id', has 'corpus') keep their payload in
    metrics with status 'ok'; record lines map field-for-field.
    """
    stage_map = stage_map or {}
    is_case = ("id" not in row and "corpus" in row) or fname == "cases.jsonl"
    ts = _parse_ts(row.get("ts")) or _parse_ts(row.get("xlat_ts"))
    if is_case:
        return {
            "id": row.get("corpus") or row.get("id"),
            "arm": row.get("arm") or "-",
            "up": row.get("upstream") or "-",
            "variant": row.get("variant") or "-",
            "stage": row.get("stage") or "cases",
            "status": row.get("status"),
            "dur_s": row.get("dur_s") or row.get("seconds"),
            "metrics": row,
            "errors": row.get("errors"),
            "sig": row.get("sig"),
            "code": row.get("code"),
            "queue_wait_s": row.get("queue_wait_s"),
            "ts": ts if ts is not None else file_ts,
            "default_status": "ok",
            "dedup_sig": _jcanon(row),
        }
    stage = row.get("stage") or stage_map.get(fname) or stage_map.get("*")
    default_status = "fault"
    if stage is None:
        if fname.startswith("eval-records"):
            # eval/cells recovery ledgers: row existence IS the record
            # (same convention as the bench.db eval_records/cells tables).
            stage, default_status = "eval_records", "ok"
        elif fname.startswith("cells"):
            stage, default_status = "cells", "ok"
        else:
            stage = "records"
    return {
        "id": row.get("id"),
        "arm": row.get("arm") or "-",
        "up": row.get("upstream") or "-",
        "variant": row.get("variant") or "-",
        "stage": stage,
        "status": row.get("status"),
        "dur_s": row.get("dur_s") or row.get("seconds"),
        "eval": fname.startswith("eval-records")
        or row.get("eval") in (True, 1),  # strict: "false"/"0" strings are
        # not eval flags — bool() on a data field misroutes the row
        "metrics": row.get("metrics") if "metrics" in row else row,
        "errors": row.get("errors"),
        "sig": row.get("sig"),
        "code": row.get("code"),
        "queue_wait_s": row.get("queue_wait_s"),
        "ts": ts if ts is not None else file_ts,
        "default_status": default_status,
        "dedup_sig": _jcanon(row),
    }


# ---------------------------------------------------------------------------
# rec -> event, order resolution, commit
# ---------------------------------------------------------------------------

def _rec_to_event(rec: dict, *, run_name: str, run_seq: int,
                  registry, src: str, stats: dict, quar: list):
    """Normalized rec -> cell event (seq=0 placeholder), or None when the
    row routes to quarantine (appended to `quar`)."""
    id_raw = rec.get("id")
    # the source db's own adjudication (id_canon) outranks re-resolving the
    # raw spelling; absent it, gate on id as before.
    res = _canon_gate(rec.get("canon_hint") or id_raw, registry)
    if not res.ok:
        payload, n_red = redact(rec)
        stats["redacted"] += n_red
        quar_row, n_red2 = redact({
            "type": "import_quarantine",
            "src": src,
            "run": run_name,
            "reason": "canon",
            "canon_state": res.state,
            "canon_reason": res.reason,
            "candidates": res.candidates,
            "id": id_raw,
            "dedup_sha": _sha(rec["dedup_sig"]),
            "payload": payload,
            "ts": rec["ts"],
        })
        stats["redacted"] += n_red2
        quar.append(quar_row)
        stats["quarantined"] += 1
        return None

    metrics, n1 = redact(rec.get("metrics"))
    errors, n2 = redact(rec.get("errors"))
    sig, n3 = redact(rec.get("sig"))
    code, n4 = redact(rec.get("code"))
    stats["redacted"] += n1 + n2 + n3 + n4

    # Identity/vocab fields are redacted IN PLACE (scalar placeholder, not
    # the dict form) — a secret inside run/stage/arm/up/variant/id still
    # counts, but the row survives and stays groupable under its mangled
    # key instead of wedging the schema.
    run_clean = _redact_str(run_name)
    if run_clean != run_name:
        stats["redacted"] += 1
    id_clean = _redact_str(id_raw) if isinstance(id_raw, str) else id_raw
    if id_clean != id_raw:
        stats["redacted"] += 1
    vocab = {}
    for k in ("arm", "up", "variant", "stage"):
        v = rec.get(k)
        if isinstance(v, str) and _scalar_secret(v):
            stats["redacted"] += 1
            v = _redact_str(v)
        vocab[k] = v

    status, orig = _status_of(rec.get("status"),
                              default=rec["default_status"])
    if orig is not None:
        if isinstance(metrics, dict):
            metrics = dict(metrics)
            metrics["_orig_status"] = orig
        else:
            metrics = {"_orig_status": orig, "_metrics": metrics}

    # §3.10.7 canon_drift: the frozen hint lands, but when the raw id
    # re-resolves to a DIFFERENT idc (or can't reproduce the frozen value
    # at all) the divergence is stamped on the row — fail-loud, not silent.
    drift = None
    hint = rec.get("canon_hint")
    if hint and isinstance(id_raw, str) and id_raw != hint:
        raw_res = _canon_gate(id_raw, registry)
        if not raw_res.ok or raw_res.idc != res.idc:
            drift = raw_res.idc if raw_res.ok else str(id_raw)

    def _num_field(v):
        """Numeric event fields (dur_s/queue_wait_s): a float can smuggle
        the key substring (240127.0), and any non-numeric value drops out
        here rather than tripping schema-quarantine for the whole row."""
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        if _KEY_SUBSTR in repr(v):
            stats["redacted"] += 1
            return None
        return v

    ev = {
        "type": events.T_CELL,
        "v": events.SCHEMA_V,
        "ts": rec["ts"],
        "run": run_clean,
        "run_seq": run_seq,
        "seq": 0,
        "id": id_clean,
        "idc": res.idc,
        "arm": vocab["arm"],
        "up": vocab["up"],
        "variant": vocab["variant"],
        "stage": vocab["stage"],
        "status": status,
        "dur_s": _num_field(rec.get("dur_s")),
        "metrics": metrics,
        "errors": errors,
        "sig": sig,
        "code": code,
        "fp": None,
        "import_src": src,
    }
    if drift is not None:
        ev["canon_drift_of"] = drift
    if rec.get("eval"):
        ev["eval"] = 1
    qw = rec.get("queue_wait_s")
    if isinstance(qw, str):
        qw, nqw = redact(qw)
        stats["redacted"] += nqw
    qw = _num_field(qw)
    if qw is not None:
        ev["queue_wait_s"] = qw
    try:
        events.validate(ev)
    except events.EventError as exc:
        quar_row, n_red = redact({
            "type": "import_quarantine",
            "src": src,
            "run": run_name,
            "reason": f"schema:{exc}",
            "canon_state": res.state,
            "id": id_raw,
            "dedup_sha": _sha(rec["dedup_sig"]),
            "payload": {"id": id_raw, "stage": rec["stage"],
                        "status": status},
            "ts": rec["ts"],
        })
        stats["redacted"] += n_red
        quar.append(quar_row)
        stats["quarantined"] += 1
        return None
    return ev


def _preferred_last(group: list, paid: bool):
    """The event that must land LAST for a conservative projection.

    paid arm -> done-ish terminal (ok|partial|clean) protects quota; with
    none, a negative terminal (fail|fault|…) still protects it — falling
    back to a RETRIABLE row would rerun a paid cell and burn quota.
    free -> retriable (skip|error) prefers rerun, else a negative
    terminal over a positive one.
    """
    if paid:
        cand = [e for e in group if e.get("status") in _DONE_ISH]
        if cand:
            return cand[-1]
        cand = [e for e in group if e.get("status") in _NEG_TERM]
        if cand:
            return cand[-1]
        return group[-1]
    cand = [e for e in group if e.get("status") in events.STATUS_RETRIABLE]
    if cand:
        return cand[-1]
    cand = [e for e in group if e.get("status") in _NEG_TERM]
    if cand:
        return cand[-1]
    return group[-1]


def _resolve_order(evs: list, *, run_name: str, src: str, stats: dict,
                   quar: list) -> list:
    """Group by cell key; for keys with multiple distinct statuses move
    the conservative pick to the end and report the key to quarantine."""
    groups: dict = {}
    order: list = []
    for ev in evs:
        k = (ev["idc"], ev["arm"], ev["up"], ev["variant"], ev["stage"])
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(ev)
    out = []
    for k in order:
        g = groups[k]
        statuses = [e.get("status") for e in g]
        if len(g) > 1 and len(set(statuses)) > 1:
            paid = k[1] in PAID_ARMS
            pref = _preferred_last(g, paid)
            g = [e for e in g if e is not pref] + [pref]
            quar_row, n_red = redact({
                "type": "import_order_sensitive",
                "src": src,
                "run": run_name,
                "idc": k[0], "arm": k[1], "up": k[2],
                "variant": k[3], "stage": k[4],
                "n": len(g),
                "statuses": sorted(set(statuses), key=repr),
                "chosen": pref.get("status"),
                "paid": paid,
            })
            stats["redacted"] += n_red
            quar.append(quar_row)
            stats["order_sensitive"] += 1
        out.extend(g)
    return out


def _known_shas(index, evs: list) -> set:
    """payload_shas already in the index dedupe table — the emit filter
    that makes the LEDGER idempotent, not just the index."""
    if index is None or not evs:
        return set()
    shas = [events.content_hash(e) for e in evs]
    known = set()
    for i in range(0, len(shas), 900):
        part = shas[i:i + 900]
        marks = ",".join("?" * len(part))
        for row in index.conn.execute(
            f"SELECT payload_sha FROM dedupe WHERE payload_sha IN ({marks})",  # noqa: S608 -- marks 是 "?"*n 占位符，本模块内构造
            part,
        ):
            known.add(row[0])
    return known


def _commit(evs: list, *, rdir: Path | None, index, stats: dict,
            dry: bool) -> None:
    """emit_batch + apply_events in chunks of EMIT_CHUNK.

    Events whose payload_sha the index already knows are skipped on BOTH
    paths — re-import of an already-applied batch lands zero new ledger
    lines and zero new index rows.

    metrics/errors payloads >4KB are offloaded to the run's derived/blobs
    BEFORE hashing — the ledger stores (and the index dedupes) the
    $blob-rewritten form, so the filter must hash that same form. Dry runs
    skip offload (no filesystem writes) — their dup accounting can
    under-report vs a real re-import; cosmetic only.
    """
    if not evs:
        return
    if dry:
        known = _known_shas(index, evs)
        stats["dup_skipped"] += sum(
            1 for e in evs if events.content_hash(e) in known)
        return
    blob_dir = Path(rdir) / "derived" / "blobs" if rdir is not None else None
    evs = [events.maybe_offload(e, blob_dir) for e in evs]
    known = _known_shas(index, evs)
    # dedupe against the index AND within this batch — two source rows
    # differing only in fields that never reach the event produce identical
    # content_hash; both would otherwise land as duplicate ledger lines.
    new = []
    for e in evs:
        h = events.content_hash(e)
        if h in known:
            continue
        known.add(h)
        new.append(e)
    stats["dup_skipped"] += len(evs) - len(new)
    for i in range(0, len(new), EMIT_CHUNK):
        chunk = new[i:i + EMIT_CHUNK]
        ledger.emit_batch(chunk, run_dir=rdir)
        stats["emitted"] += len(chunk)
        if index is not None:
            applied = index.apply_events(chunk)
            stats["applied"] += applied
            stats["index_rejected"] += len(chunk) - applied


def _flush_quar(quar: list, seen: set, stats: dict, dry: bool) -> None:
    for row in quar:
        if _append_quar(row, seen, dry):
            stats["quar_written"] += 1


def _stats() -> dict:
    return {
        "rows": 0, "events": 0, "emitted": 0, "applied": 0,
        "dup_skipped": 0, "quarantined": 0, "quar_written": 0,
        "redacted": 0, "order_sensitive": 0, "runs": 0, "runs_minted": 0,
        "bad_lines": 0, "index_rejected": 0,
    }


# ---------------------------------------------------------------------------
# bench.db
# ---------------------------------------------------------------------------

def _run_sort_key(run: dict):
    """(started_at -> dir mtime -> run name) per §3.3. Timestamps sort
    NUMERICALLY — a lexical repr() inverts across digit-width boundaries
    and mixed ISO spellings (' ' vs 'T' separator) misorder."""
    ca = _parse_ts(run.get("created_at"))
    name = str(run.get("name") or "")
    if ca is not None:
        return (0, ca, name)
    p = run.get("path")
    if p:
        try:
            return (1, float(Path(p).stat().st_mtime), name)
        except OSError:
            pass
    return (2, 0.0, name)


def _run_date(run: dict) -> str:
    ca = run.get("created_at")
    if isinstance(ca, str) and len(ca) >= 10:
        return ca[:10]
    m = _DATE_RE.search(str(run.get("name") or ""))
    if m:
        return m.group(1)
    p = run.get("path")
    if p:
        try:
            mt = Path(p).stat().st_mtime
            return datetime.fromtimestamp(mt, tz=UTC).strftime(
                "%Y-%m-%d")
        except OSError:
            pass
    return "undated"


def _prepare_run(rows, *, run_name: str, run_seq: int,
                 registry, src: str, stats: dict,
                 quar: list, norm_fn) -> list:
    """rows -> resolved cell events with seq assigned."""
    prepared = []
    seen_sig = set()
    for row in rows:
        rec = norm_fn(row)
        sig = _sha(rec["dedup_sig"])
        if sig in seen_sig:
            stats["dup_skipped"] += 1
            continue
        seen_sig.add(sig)
        ev = _rec_to_event(rec, run_name=run_name, run_seq=run_seq,
                           registry=registry, src=src, stats=stats,
                           quar=quar)
        if ev is not None:
            prepared.append(ev)
    evs = _resolve_order(prepared, run_name=run_name, src=src,
                         stats=stats, quar=quar)
    for i, ev in enumerate(evs, 1):
        ev["seq"] = i
    stats["events"] += len(evs)
    return evs


def import_benchdb(db_path, index, registry=None, dry: bool = False) -> dict:
    """Import all five bench.db tables as per-(table,run) ledger runs.

    Run identity: 'import-<table>-r<run_id>-<slugified name>' — run_id is
    in the name because the db reuses names across source='live'/'archive'
    (e.g. two distinct 'soak-2026-09-18' runs). Runs are minted in
    (created_at -> path mtime -> name) order so run_seq approximates
    chronology.
    """
    stats = _stats()
    db_path = str(db_path)
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        existing = {
            r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        runs = {}
        if "runs" in existing:
            runs = {
                r["run_id"]: dict(r)
                for r in db.execute(
                    "SELECT run_id,name,source,kind,path,created_at"
                    " FROM runs")
            }
        groups = []
        for table in _DB_TABLES:
            if table not in existing:
                continue
            for (rid,) in db.execute(
                    f"SELECT DISTINCT run_id FROM {table}"):  # noqa: S608 -- table 来自 _DB_TABLES 白名单迭代
                run = runs.get(rid) or {
                    "run_id": rid, "name": f"run-{rid}", "created_at": None,
                    "path": None, "kind": "?", "source": "?"}
                groups.append((_run_sort_key(run), table, rid))
        groups.sort(key=lambda g: (g[0], g[1], g[2]))

        quar_seen = _load_quar_shas()
        for _sk, table, rid in groups:
            run = runs.get(rid) or {"name": f"run-{rid}"}
            base = str(run.get("name") or f"run-{rid}")
            run_name = f"import-{table}-r{rid}-{_slugify(base)}"
            date = _run_date(run)
            slug = _slugify(f"{table}-r{rid}-{base}")
            run_ts = _parse_ts(run.get("created_at")) or 0.0
            run_seq, rdir, minted, rr = _ensure_import_run(
                index, run_name, date=date, slug=slug,
                spec_hash=f"benchdb:{table}:{rid}", dry=dry)
            stats["runs"] += 1
            stats["runs_minted"] += int(minted)
            quar: list = []
            if rr is not None and index is not None and not dry:
                index.apply_events([rr])

            if table == "records":
                norm_fn = lambda row, _ts=run_ts: _norm_db_record(row, _ts)  # noqa: E731
            else:
                norm_fn = lambda row, _t=table, _ts=run_ts: _norm_db_raw(  # noqa: E731
                    _t, row, _ts)

            def rows(_table=table, _rid=rid):
                for r in db.execute(
                        f"SELECT * FROM {_table} WHERE run_id=?"  # noqa: S608 -- _table 来自 _DB_TABLES 白名单
                        " ORDER BY rec_id", (_rid,)):
                    stats["rows"] += 1
                    yield dict(r)

            evs = _prepare_run(rows(), run_name=run_name,
                               run_seq=run_seq,
                               registry=registry, src="benchdb",
                               stats=stats, quar=quar, norm_fn=norm_fn)
            _commit(evs, rdir=rdir, index=index, stats=stats, dry=dry)
            _flush_quar(quar, quar_seen, stats, dry)
    finally:
        db.close()
    return stats


# ---------------------------------------------------------------------------
# worktree jsonl files
# ---------------------------------------------------------------------------

def _run_meta_ts(rdir: Path) -> float | None:
    """started_at analog from a worktree run_meta.json (best effort)."""
    p = Path(rdir) / "run_meta.json"
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(meta, dict):
        for k in ("started_at", "ts_start", "start", "ts", "created_at"):
            ts = _parse_ts(meta.get(k))
            if ts is not None:
                return ts
    return None


def import_jsonl_file(path, run, stage_map=None, index=None, registry=None,
                      dry: bool = False) -> dict:
    """Import one worktree records*.jsonl / cases.jsonl file.

    `run` is the ledger run name (str) or a Path to the source run dir
    (name derived as import-<dirname>, started_at from run_meta.json).
    File order is preserved; identical lines pre-deduped.
    """
    stats = _stats()
    path = Path(path)
    if isinstance(run, Path):
        src_dir = run
        run_name = f"import-{_slugify(src_dir.name)}"
    else:
        src_dir = path.parent
        run_name = (
            str(run) if run
            else f"import-{_slugify(path.parent.name)}-{_slugify(path.stem)}"
        )
    file_ts = path.stat().st_mtime
    ts_start = _run_meta_ts(src_dir) or file_ts
    date = datetime.fromtimestamp(ts_start, tz=UTC).strftime(
        "%Y-%m-%d")
    slug = _slugify(run_name.removeprefix("import-"))
    run_seq, rdir, minted, rr = _ensure_import_run(
        index, run_name, date=date, slug=slug,
        spec_hash=f"jsonl:{path.name}", dry=dry)
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)

    quar: list = []
    quar_seen = _load_quar_shas()
    if rr is not None and index is not None and not dry:
        index.apply_events([rr])

    def norm_fn(row):
        return _norm_jsonl_row(row, fname=path.name, file_ts=file_ts,
                               stage_map=stage_map)

    def rows():
        for _ln, ev, raw in iter_jsonl(path):
            stats["rows"] += 1
            if ev is None or not isinstance(ev, dict):
                reason = "bad_line" if ev is None else "non_object"
                payload, n_red = redact(raw if ev is None else ev)
                stats["redacted"] += n_red
                quar.append({
                    "type": "import_quarantine", "src": "jsonl",
                    "run": run_name, "reason": reason,
                    "payload": payload,
                    "dedup_sha": _sha(raw), "ts": file_ts,
                })
                stats["quarantined"] += 1
                stats["bad_lines"] += 1
                continue
            yield ev

    evs = _prepare_run(rows(), run_name=run_name, run_seq=run_seq,
                       registry=registry, src="jsonl",
                       stats=stats, quar=quar, norm_fn=norm_fn)
    _commit(evs, rdir=rdir, index=index, stats=stats, dry=dry)
    _flush_quar(quar, quar_seen, stats, dry)
    return stats


# ---------------------------------------------------------------------------
# zh-store manifest + byte census
# ---------------------------------------------------------------------------

_ZONE_VERDICT = {
    "primary": "primary",
    "alt": "alt",
    "quarantine": "quarantine",
    "_quarantine": "quarantine",
}


def _tree_has_file(d: Path) -> bool:
    try:
        for _root, _dirs, files in os.walk(d):
            if files:
                return True
    except OSError:
        return False
    return False


_QUAR_CONTAINERS = ("_quarantine", "quarantine")


def _zh_dir_candidates(bytes_root: Path, row: dict, idc: str) -> list:
    """Possible byte dirs for a manifest row, preferred first."""
    sid = idnorm.safe_id(idc)
    raw = str(row.get("id") or "")
    zone = row.get("zone")
    cands = []
    if zone in ("quarantine", "_quarantine"):
        cands.extend(
            bytes_root / cont / n
            for cont in _QUAR_CONTAINERS
            for n in dict.fromkeys((raw, sid)) if n)
    cands.extend(bytes_root / n for n in dict.fromkeys((raw, sid)) if n)
    cands.extend(
        bytes_root / cont / n
        for cont in _QUAR_CONTAINERS
        for n in dict.fromkeys((raw, sid)) if n)
    seen = set()
    out = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def import_zhstore(manifest_path, bytes_root, index, registry=None,
                   dry: bool = False) -> dict:
    """Manifest rows -> asset events (verified when declared bytes exist,
    tombstone when missing); census dirs without rows -> orphan report.

    Byte lookup prefers row['id'] then safe_id(idc) under bytes_root,
    with the _quarantine/ subtree consulted first for quarantine zones.
    Adopting orphans is Phase 2's job — here they are only counted +
    noted, never claimed.
    """
    stats = _stats()
    manifest_path = Path(manifest_path)
    bytes_root = Path(bytes_root)
    run_name = "import-zhstore"
    file_ts = manifest_path.stat().st_mtime
    date = datetime.fromtimestamp(file_ts, tz=UTC).strftime(
        "%Y-%m-%d")
    run_seq, rdir, minted, rr = _ensure_import_run(
        index, run_name, date=date, slug="zhstore",
        spec_hash="zhstore-manifest", dry=dry)
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)

    quar: list = []
    quar_seen = _load_quar_shas()
    evs: list = []
    seq = 0
    referenced: set[str] = set()
    orphans: list = []
    undeclared: list = []

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    for _ln, row, raw in iter_jsonl(manifest_path):
        stats["rows"] += 1
        if row is None:
            payload, n_red = redact(raw)
            stats["redacted"] += n_red
            quar.append({
                "type": "import_quarantine", "src": "zhstore",
                "run": run_name, "reason": "bad_line",
                "payload": payload,
                "dedup_sha": _sha(raw), "ts": file_ts,
            })
            stats["quarantined"] += 1
            stats["bad_lines"] += 1
            continue
        if not isinstance(row, dict):
            payload, n_red = redact(row)
            stats["redacted"] += n_red
            quar.append({
                "type": "import_quarantine", "src": "zhstore",
                "run": run_name, "reason": "non_object",
                "payload": payload,
                "dedup_sha": _sha(raw), "ts": file_ts,
            })
            stats["quarantined"] += 1
            stats["bad_lines"] += 1
            continue
        id_raw = row.get("id")
        if id_raw is not None:
            referenced.add(str(id_raw))
        res = _canon_gate(id_raw, registry)
        ts = _parse_ts(row.get("moved_at")) or _parse_ts(
            row.get("xlat_ts")) or file_ts
        if not res.ok:
            payload, n_red = redact(row)
            stats["redacted"] += n_red
            quar_row, n_red2 = redact({
                "type": "import_quarantine", "src": "zhstore",
                "run": run_name, "reason": "canon",
                "canon_state": res.state, "canon_reason": res.reason,
                "candidates": res.candidates, "id": id_raw,
                "payload": payload,
                "dedup_sha": _sha(raw), "ts": ts,
            })
            stats["redacted"] += n_red2
            quar.append(quar_row)
            stats["quarantined"] += 1
            continue
        idc = res.idc
        referenced.add(idnorm.safe_id(idc))
        zone_key = str(row.get("zone") or "primary")
        zone = _ZONE_VERDICT.get(zone_key)
        if zone is None:
            # unknown zone is fail-closed: an uninterpretable zone must
            # never promote bytes into the dedup-hit set.
            quar_row, n_red = redact({
                "type": "import_quarantine", "src": "zhstore",
                "run": run_name, "reason": "zone_unknown",
                "id": id_raw, "payload": {"zone": row.get("zone")},
                "dedup_sha": _sha(raw), "ts": ts,
            })
            stats["redacted"] += n_red
            quar.append(quar_row)
            stats["quarantined"] += 1
            continue
        def _clean(v, default: str) -> str:
            """Manifest string fields are data-controlled — a secret in
            arm/model/source_run must not reach the ledger verbatim."""
            s = str(v) if v is not None else default
            if isinstance(s, str) and _scalar_secret(s):
                stats["redacted"] += 1
                s = _redact_str(s)
            return s

        arm = _clean(row.get("arm"), "-")
        model = _clean(row.get("model"), "")
        source_run = _clean(row.get("source_run"), "")
        altseq = _clean(row.get("altseq"), "0")
        id_clean = _clean(id_raw, str(id_raw)) if id_raw is not None else None
        base = None
        for cand in _zh_dir_candidates(bytes_root, row, idc):
            if cand.is_dir():
                base = cand
                break
        for kind in ("zh", "splice"):
            declared = bool(row.get(f"has_{kind}"))
            kdir = base / kind if base is not None else None
            has_bytes = (
                kdir is not None and kdir.is_dir() and _tree_has_file(kdir)
            )
            if not declared:
                if has_bytes:
                    undeclared.append(f"{id_raw}/{kind}")
                continue
            if has_bytes:
                try:
                    rel = kdir.relative_to(bytes_root).as_posix()
                except ValueError:
                    rel = str(kdir)
                evs.append({
                    "type": events.T_ASSET,
                    "v": events.SCHEMA_V,
                    "ts": ts,
                    "run": run_name,
                    "run_seq": run_seq,
                    "seq": next_seq(),
                    "id": id_clean,
                    "idc": idc,
                    "arm": arm,
                    "variant": "-",
                    "kind": kind,
                    "path": rel,
                    "sha": None,
                    "bytes": dir_size(kdir),
                    "state": "verified",
                    "zone": zone,
                    "verdict": zone,
                    "altseq": altseq,
                    "model": model,
                    "source_run": source_run,
                    "import_src": "zhstore",
                })
            else:
                evs.append({
                    "type": events.T_TOMBSTONE,
                    "v": events.SCHEMA_V,
                    "ts": ts,
                    "id": id_clean,
                    "idc": idc,
                    "arm": arm,
                    "variant": "-",
                    "kind": kind,
                    "reason": "zhstore_declared_missing",
                    "lost_run": source_run or "zhstore",
                    "zone": zone,
                    "import_src": "zhstore",
                })
            stats["events"] += 1

    # Byte census: payload dirs present without a manifest row. Report
    # only — Phase 2's adopt owns them (design: report+收编, never delete).
    census = []
    for container in [bytes_root] + [bytes_root / c
                                     for c in _QUAR_CONTAINERS]:
        if not container.is_dir():
            continue
        for child in sorted(container.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if container == bytes_root and child.name in _QUAR_CONTAINERS:
                continue  # the quarantine containers themselves, not payload
            census.append((container, child.name))
    for container, name in census:
        if name not in referenced:
            try:
                orphans.append(
                    str((container / name).relative_to(bytes_root)))
            except ValueError:
                orphans.append(name)
    if orphans:
        evs.append({
            "type": events.T_NOTE,
            "v": events.SCHEMA_V,
            "ts": file_ts,
            "run": run_name,
            "run_seq": run_seq,
            "seq": next_seq(),
            "text": f"zhstore census: {len(orphans)} orphan byte dirs "
                    "without manifest rows (adopt deferred to Phase 2)",
            "level": "warn",
            "import_src": "zhstore",
        })
        stats["events"] += 1
    if undeclared:
        evs.append({
            "type": events.T_NOTE,
            "v": events.SCHEMA_V,
            "ts": file_ts,
            "run": run_name,
            "run_seq": run_seq,
            "seq": next_seq(),
            "text": f"zhstore census: {len(undeclared)} dirs hold bytes "
                    "for kinds the manifest does not declare",
            "level": "warn",
            "import_src": "zhstore",
        })
        stats["events"] += 1

    if rr is not None and index is not None and not dry:
        index.apply_events([rr])
    _commit(evs, rdir=rdir, index=index, stats=stats, dry=dry)
    _flush_quar(quar, quar_seen, stats, dry)
    stats["orphans"] = len(orphans)
    stats["orphan_dirs"] = orphans
    stats["undeclared_bytes"] = undeclared
    return stats


# ---------------------------------------------------------------------------
# Phase 2 — vault seeding (live-byte census, §3.10.9)
# ---------------------------------------------------------------------------

# zh-store kinds the census harvests — 'state' (xlat-state) joins the
# manifest-declared pair only when a state/ subtree physically exists.
_VAULT_SCAN_KINDS = ("zh", "splice", "state")


def _provenance(base: Path, stats: dict) -> dict | None:
    """zh-store <id>/provenance.json -> redacted dict for meta['provenance']."""
    p = base / "provenance.json"
    if not p.is_file():
        return None
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stats["errors"] += 1
        return None
    out, n = redact(obj)
    stats["redacted"] += n
    return out if isinstance(out, dict) else {"_raw": out}


def seed_vault_zhstore(manifest_path, bytes_root, index, registry=None,
                       dry: bool = False) -> dict:
    """Phase-2 live-byte census: physically seed zh-store bytes into vault.

    This is a byte census, not a manifest replay (§3.10.9): the disk is
    walked and reconciled three ways against the manifest rows.

    - Row + bytes present -> vault.harvest() the non-empty {zh,splice,
      state} subtrees. The physical container beats the claimed zone:
      anything found under _quarantine/ lands quar/quar regardless of the
      manifest's zone field. primary rows land primary/verified (the
      census itself is the verification — harvest sha256s every file into
      files.sha256). alt rows land alt/alt.
    - Row declared but bytes absent -> already tombstoned by
      import_zhstore; counted as still_missing, nothing re-emitted.
    - Dir on disk whose id never canon-resolves (no manifest row, or a
      canon-fail row like *.bak-mock) -> noncanon_bytes report. The vault
      _check_idc gate refuses them by design; mock/junk payloads never
      enter the paid-byte store. They stay in place for the operator.
    - provenance.json (per-id) merges into the harvested meta under
      'provenance'.
    - Manifest rows may carry an optional ``pinned`` field (append-only,
      last-wins — harvest.py's reindex propagates it from a row's
      provenance.json). It is tolerated and passed through into the
      harvested meta verbatim; no delete verb consumes it yet (schema
      placeholder).

    Idempotent: a (idc, arm, '-') copy that already bytes_ok and declares
    every on-disk kind is skipped, so a crashed census re-run continues
    without duplicating copies (altseq bumps) or events.
    """
    from kernel import vault  # local: keeps the ledger-only import cheap

    stats = _stats()
    stats.update({"harvested": 0, "kinds_harvested": 0, "bytes": 0,
                  "already": 0, "still_missing": 0, "partial": 0,
                  "orphan_dirs": [], "noncanon_dirs": [], "conflicts": []})
    manifest_path = Path(manifest_path)
    bytes_root = Path(bytes_root)
    file_ts = manifest_path.stat().st_mtime
    date = datetime.fromtimestamp(file_ts, tz=UTC).strftime(
        "%Y-%m-%d")
    run_name = "import-zhstore-vault-seed"
    run_seq, rdir, minted, rr = _ensure_import_run(
        index, run_name, date=date, slug="vault-seed",
        spec_hash="zhstore-vault-seed", dry=dry)
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)
    if rr is not None and index is not None and not dry:
        index.apply_events([rr])
    sink = index.apply_event if index is not None else None

    seq = 0

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    def _in_quar(base: Path) -> bool:
        for cont in _QUAR_CONTAINERS:
            try:
                base.relative_to(bytes_root / cont)
            except ValueError:
                continue
            else:
                return True
        return False

    def _patch_meta(mpath: Path, base: Path, adopted: bool,
                    row: dict | None = None) -> None:
        meta = vault._read_meta(mpath) or {}
        prov = _provenance(base, stats)
        if prov:
            meta["provenance"] = prov
        if adopted:
            meta["adopted_from"] = str(base)
        # import_src marks migration-seeded bytes: payment predates the
        # claim machinery, so doctor's paid reconciliation exempts them
        # (the meta-plane mirror of the events' import_src convention).
        meta["import_src"] = run_name
        if row is not None and row.get("pinned"):
            # zh-store manifest `pinned` — tolerated passthrough into the
            # vault meta (placeholder: no delete verb consumes it yet).
            meta["pinned"] = True
        vault._write_meta(mpath, meta)
        stats["bytes"] += int(meta.get("bytes") or 0)

    # -- pass 1: manifest rows (last-wins per id, file order = claim order) --
    rows_by_id: dict[str, dict] = {}
    for _ln, row, _raw in iter_jsonl(manifest_path):
        if isinstance(row, dict) and row.get("id"):
            rows_by_id[str(row["id"])] = row
    stats["rows"] = len(rows_by_id)

    claimed_dirs: set[Path] = set()

    for raw_id, row in rows_by_id.items():
        res = _canon_gate(raw_id, registry)
        # resolve the physical dir even for canon-fail rows (dir name is
        # the manifest id spelled verbatim, e.g. *.bak-mock)
        if res.ok:
            cands = _zh_dir_candidates(bytes_root, row, res.idc)
        else:
            cands = [bytes_root / raw_id] + [
                bytes_root / cont / raw_id for cont in _QUAR_CONTAINERS]
        base = next((c for c in cands if c.is_dir()), None)
        if base is None:
            # byte-less row — tombstone already on the ledger
            if res.ok:
                stats["still_missing"] += 1
            continue
        claimed_dirs.add(base)
        assets = {k: base / k for k in _VAULT_SCAN_KINDS
                  if (base / k).is_dir() and _tree_has_file(base / k)}
        if not res.ok:
            if assets:
                stats["noncanon_dirs"].append(
                    str(base.relative_to(bytes_root)))
            continue
        if not assets:
            stats["still_missing"] += 1
            continue
        idc = res.idc
        arm = str(row.get("arm") or "-")
        # kinds the manifest claims but the dir does not carry -> partial
        declared = {k for k in ("zh", "splice") if row.get(f"has_{k}")}
        if declared - set(assets):
            stats["partial"] += 1
        # idempotency: an intact copy declaring every on-disk kind already
        # vouches for this cell — re-runs must not mint altseq duplicates.
        covered = set()
        for m in vault.query(idc, arm, "-"):
            if m.get("bytes_ok") and isinstance(m.get("files"), dict):
                covered.update(m["files"].keys())
        if covered and set(assets) <= covered:
            stats["already"] += 1
            # converge metas on re-run — a copy committed before the
            # provenance/import_src merge picks the markers up here
            # (vault-plane rewrite only; the ledger stays quiet).
            prov = _provenance(base, stats)
            for m in vault.query(idc, arm, "-"):
                if not m.get("bytes_ok") or not m.get("meta_path"):
                    continue
                meta = vault._read_meta(Path(m["meta_path"])) or {}
                changed = False
                if prov and "provenance" not in meta:
                    meta["provenance"] = prov
                    changed = True
                if meta.get("import_src") != run_name:
                    meta["import_src"] = run_name
                    changed = True
                if row.get("pinned") and not meta.get("pinned"):
                    meta["pinned"] = True
                    changed = True
                if changed and not dry:
                    vault._write_meta(Path(m["meta_path"]), meta)
            continue
        if _in_quar(base):
            zone = verdict = "quar"
        else:
            zone = _ZONE_VERDICT.get(str(row.get("zone") or "primary"),
                                     "quar")
            verdict = {"primary": "verified", "alt": "alt",
                       "quarantine": "quar"}[zone]
        if dry:
            stats["harvested"] += 1
            stats["kinds_harvested"] += len(assets)
            continue
        try:
            mpath = vault.harvest(
                idc, arm, "-", assets,
                source_run=str(row.get("source_run") or "zhstore"),
                zone=zone, verdict=verdict,
                model=str(row.get("model") or "") or None,
                id=str(row.get("id") or idc),
                seq=next_seq, run_dir=rdir, sink=sink)
        except vault.DestOccupied as exc:
            stats["conflicts"].append(f"{idc}: {exc}")
            stats["errors"] += 1
            continue
        _patch_meta(mpath, base, adopted=False, row=row)
        stats["harvested"] += 1
        stats["kinds_harvested"] += len(assets)
        stats["events"] += len(assets)
        stats["emitted"] += len(assets)
        if index is not None:
            stats["applied"] += len(assets)

    # -- pass 2: byte dirs with no canon-resolvable row -> quar --
    containers = [("", bytes_root)] + [
        (c, bytes_root / c) for c in _QUAR_CONTAINERS]
    for cont, cdir in containers:
        if not cdir.is_dir():
            continue
        for child in sorted(cdir.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not cont and child.name in _QUAR_CONTAINERS:
                continue
            if child in claimed_dirs:
                continue
            assets = {k: child / k for k in _VAULT_SCAN_KINDS
                      if (child / k).is_dir() and _tree_has_file(child / k)}
            if not assets:
                continue
            stats["orphan_dirs"].append(
                str(child.relative_to(bytes_root)))
            res = _canon_gate(idnorm.idc_from_safe(child.name), registry)
            if not res.ok:
                stats["noncanon_dirs"].append(
                    str(child.relative_to(bytes_root)))
                continue
            # the dir carries no arm identity of its own — an intact copy
            # covering its kinds under ANY arm already vouches for it
            covered = set()
            for m in vault.query(res.idc):
                if m.get("bytes_ok") and isinstance(m.get("files"), dict):
                    covered.update(m["files"].keys())
            if covered and set(assets) <= covered:
                stats["already"] += 1
                continue
            if dry:
                stats["harvested"] += 1
                continue
            prov = _provenance(child, stats) or {}
            try:
                mpath = vault.harvest(
                    res.idc, str(prov.get("arm") or "-"), "-", assets,
                    source_run=str(prov.get("source_run") or "orphan"),
                    zone="quar", verdict="quar",
                    model=str(prov.get("model") or "") or None,
                    id=child.name, seq=next_seq, run_dir=rdir, sink=sink)
            except vault.DestOccupied as exc:
                stats["conflicts"].append(f"{child.name}: {exc}")
                stats["errors"] += 1
                continue
            _patch_meta(mpath, child, adopted=True)
            stats["harvested"] += 1
            stats["kinds_harvested"] += len(assets)
            stats["events"] += len(assets)
            stats["emitted"] += len(assets)
            if index is not None:
                stats["applied"] += len(assets)

    # -- census note (the summary row lives on the ledger, not stdout) --
    # gated on harvested alone: a quiet re-run (noncanon dirs still sit on
    # disk by design) must not append an identical note every census.
    if not dry and stats["harvested"]:
        ev = events.make_event(
            events.T_NOTE, run=run_name,
            run_seq=run_seq, seq=next_seq(), level="info",
            text=(f"vault seed census: {stats['harvested']} copies "
                  f"harvested, {stats['already']} already present, "
                  f"{stats['still_missing']} still missing, "
                  f"{len(stats['orphan_dirs'])} orphan dirs, "
                  f"{len(stats['noncanon_dirs'])} noncanon byte dirs"))
        ledger.emit(ev, run_dir=rdir, sink=sink)
        stats["events"] += 1
    return stats


# ---------------------------------------------------------------------------
# Lake zone — manifest seeding + on-disk corpus absorb (Phase 3, §3.10)
# ---------------------------------------------------------------------------

class _BatchSink:
    """Sink adapter for bulk emits: ledger.emit/_batch apply the sink
    per event inside the ledger lock; index.apply_event commits per call,
    so a 10⁴-event seeding would fsync 10⁴ times while holding the lock.
    Buffer instead and flush once through ``index.apply_events`` — one
    transaction, and the ledger lock is released right after the fsync.
    A crash between ledger-append and flush only leaves the disposable
    index behind — tail_ingest heals it."""

    def __init__(self, index):
        self.index = index
        self.evs: list[dict] = []

    def __call__(self, ev: dict) -> None:
        self.evs.append(ev)

    def flush(self) -> int:
        """One apply_events transaction; returns rows applied. Raises —
        a failed flush is loud to the operator (the ledger is already
        durable, the index rebuilds)."""
        if not self.evs:
            return 0
        n = self.index.apply_events(self.evs)
        self.evs.clear()
        return n


# A manifest row records a fetch dead end worth remembering as 'failed'
# (never in the fetch set): an explicit non-ok status, or a stub payload
# (IA placeholder bytes, not a real tree).
_LAKE_BAD_FORMATS = frozenset({"stub"})


def _lake_row_failed(row: dict) -> bool:
    st = row.get("status")
    if isinstance(st, str) and st and st != "ok":
        return True
    return row.get("format") in _LAKE_BAD_FORMATS


def _manifest_files(manifest_paths) -> list[Path]:
    """Expand a mixed list of manifest files/dirs into concrete
    manifest*.jsonl paths (dirs contribute their glob, sorted)."""
    out: list[Path] = []
    for mpath in manifest_paths or []:
        mp = Path(mpath)
        if mp.is_dir():
            out.extend(sorted(mp.glob("manifest*.jsonl")))
        elif mp.is_file():
            out.append(mp)
    return out


def register_lake_manifests(manifest_paths, index, registry=None,
                            dry: bool = False) -> dict:
    """Seed the lake catalog from corpus manifests (Phase 3).

    Every row canon-gates to an idc; per idc the seed is:

    - ``failed``   — EVERY row for the id is a fetch dead end
                     (status ∉ {None,'ok'} or format=='stub'); tagged
                     ``regen_cost='network'`` since reviving the cell needs
                     the wire.
    - ``skeleton`` — otherwise (manifested, no bytes); the cell dir is
                     created as the anchor.

    Idempotent: an idc whose catalog state is not 'absent' is never
    downgraded — only missing layer/channel memberships merge in (a
    re-run with unchanged manifests appends nothing). Canon failures go
    to quarantine. Catalog rows + lake_cell events land via ONE
    ``LakeCatalog.set_bulk`` (O(1) file rescans, one emit_batch into the
    import run's shard).
    """
    from kernel import lake  # local: keeps the ledger-only import cheap

    stats = _stats()
    stats.update({"manifests": 0, "seeded_skeleton": 0, "seeded_failed": 0,
                  "skipped_present": 0, "meta_merged": 0,
                  "noncanon_ids": []})
    files = _manifest_files(manifest_paths)
    stats["manifests"] = len(files)
    if not files:
        stats["errors"] = 1
        return stats
    date = datetime.fromtimestamp(
        max(f.stat().st_mtime for f in files), tz=UTC
    ).strftime("%Y-%m-%d")
    run_name = "import-lake-register"
    run_seq, rdir, minted, rr = _ensure_import_run(
        index, run_name, date=date, slug="lake-register",
        spec_hash="lake-register", dry=dry)
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)
    if rr is not None and index is not None and not dry:
        index.apply_events([rr])
    sink = _BatchSink(index) if index is not None else None

    quar_seen = _load_quar_shas()
    # per-idc merge: last-wins scalars, union on layer/channel, and a
    # failed seed only when EVERY row is a dead end (a mixed history means
    # a fetch could still succeed -> honest state is skeleton).
    merged: dict[str, dict] = {}
    for f in files:
        for _ln, row, _raw in iter_jsonl(f):
            if not isinstance(row, dict) or not row.get("id"):
                stats["bad_lines"] += 1
                continue
            stats["rows"] += 1
            res = _canon_gate(row["id"], registry)
            if not res.ok:
                stats["quarantined"] += 1
                if len(stats["noncanon_ids"]) < 100:
                    stats["noncanon_ids"].append(str(row["id"]))
                _append_quar({
                    "src": "lake-register", "file": f.name,
                    "reason": res.reason, "row": row}, quar_seen, dry)
                continue
            acc = merged.setdefault(
                res.idc, {"layers": set(), "channels": set(),
                          "any_ok": False, "any_bad": False})
            if row.get("layer"):
                acc["layers"].add(str(row["layer"]))
            if row.get("channel"):
                acc["channels"].add(str(row["channel"]))
            if _lake_row_failed(row):
                acc["any_bad"] = True
            else:
                acc["any_ok"] = True

    cat = lake.LakeCatalog.load()
    cat_rows = cat.rows()
    updates = []
    for idc, acc in merged.items():
        layers = sorted(acc["layers"])
        channels = sorted(acc["channels"])
        cur = cat.state(idc)
        if cur == "absent":
            failed = acc["any_bad"] and not acc["any_ok"]
            kw = {"source": "arxiv", "manifested": True,
                  "layers": layers, "channels": channels}
            if failed:
                kw["regen_cost"] = "network"
                stats["seeded_failed"] += 1
            else:
                stats["seeded_skeleton"] += 1
            updates.append((idc, "failed" if failed else "skeleton", kw))
            if not dry and not failed:
                # skeletons anchor an (empty) cell dir; failed seeds are
                # catalog-only — nothing on disk to anchor.
                lake.cell_dir(idc, "arxiv").mkdir(parents=True,
                                                  exist_ok=True)
            continue
        base = cat_rows.get(idc) or {}
        new_layers = sorted(set(base.get("layers") or []) | acc["layers"])
        new_channels = sorted(
            set(base.get("channels") or []) | acc["channels"])
        if (new_layers != (base.get("layers") or [])
                or new_channels != (base.get("channels") or [])):
            updates.append((idc, cur,
                            {"layers": new_layers, "channels": new_channels}))
            stats["meta_merged"] += 1
        else:
            stats["skipped_present"] += 1

    if not dry:
        cat.set_bulk(updates, sink=sink, run_dir=rdir)
        stats["emitted"] = stats["events"] = len(updates)
        if updates:
            ev = events.make_event(
                events.T_NOTE, run=run_name, run_seq=run_seq, seq=1,
                level="info",
                text=(f"lake register: {stats['seeded_skeleton']} skeletons, "
                      f"{stats['seeded_failed']} failed seeds, "
                      f"{stats['meta_merged']} membership merges, "
                      f"{stats['skipped_present']} already present, "
                      f"{stats['quarantined']} quarantined"))
            ledger.emit(ev, run_dir=rdir, sink=sink)
            stats["events"] += 1
        if sink is not None:
            stats["applied"] = sink.flush()
    else:
        stats["events"] = len(updates)
    return stats


def _legacy_raw_files(cell: Path, meta: dict) -> list[Path]:
    """Locate the canonical raw payload of a legacy corpus cell: the
    meta-declared ``raw_file`` first, then raw.* probes, then a raw/ dir's
    own entries. Returns [] when the cell carries no raw tier."""
    rf = meta.get("raw_file")
    if isinstance(rf, str) and rf and "/" not in rf:
        p = cell / rf
        if p.is_file():
            return [p]
    for name in ("raw.tar.gz", "raw.tgz", "raw.gz", "raw.pdf", "raw.tex",
                 "raw"):
        p = cell / name
        if p.is_file():
            return [p]
    rawdir = cell / "raw"
    if rawdir.is_dir():
        return sorted(p for p in rawdir.iterdir() if p.is_file())
    return []


def absorb_corpus(bytes_root, index, registry=None, manifests=None,
                  dry: bool = False, source: str = "arxiv") -> dict:
    """CAS-ify a legacy corpus tree into ``lake/corpus/{source}/`` (Phase 3).

    Per cell dir (both '0707.0978' and 'astro-ph--0605048' spellings pass
    the same canon gate):

    - raw payload  -> ``cas.store_file(kind='blob')`` -> link_out into
      ``stage/raw/``
    - extracted/** -> ``cas.store_file(kind='file')`` -> link_out into
      ``stage/extracted/`` (read-only 0444 projection; shared .sty/.cls
      inodes dedup across cells for free)
    - meta.json    -> merged with idc/source/n_files/raw_sha256/
      absorbed_from/absorb markers, written fresh (bookkeeping, not CAS)
    - files.txt / mtree.txt -> CAS'd and linked as top-level bookkeeping

    The cell is built whole under ``lake/tmp/rebuild/absorb-{seq}/`` and
    published by first-wins rename under the cell's ``lake_lock`` — a
    racing hydrate/absorb can never interleave a half tree. Catalog:
    'hydrated' when extracted payload exists, 'raw_only' for raw-only
    cells; ``manifested`` reflects membership in the supplied manifest id
    set (unmanifested cells are the first eviction candidates).

    Idempotent: is_complete (or a live raw_only tier) skips the rebuild,
    and a missing catalog row on an already-complete cell is re-seeded —
    a crash between publish and the bulk catalog write self-heals on the
    next run. The SOURCE tree is never modified (store_file always copies
    in, never links).
    """
    from kernel import cas, lake

    stats = _stats()
    stats.update({"absorbed": 0, "already": 0, "raw_only": 0,
                  "no_payload": [], "noncanon_dirs": [],
                  "objs_stored": 0, "bytes_in": 0})
    bytes_root = Path(bytes_root)
    manifested = None
    if manifests:
        manifested = set()
        for f in _manifest_files(manifests):
            for _ln, row, _raw in iter_jsonl(f):
                if isinstance(row, dict) and row.get("id"):
                    res = _canon_gate(row["id"], registry)
                    if res.ok:
                        manifested.add(res.idc)
    run_seq, rdir, minted, rr = _ensure_import_run(
        index, "import-lake-absorb", date=datetime.now(
            tz=UTC).strftime("%Y-%m-%d"),
        slug="corpus-absorb", spec_hash="corpus-absorb", dry=dry)
    stats["runs"] += 1
    stats["runs_minted"] += int(minted)
    if rr is not None and index is not None and not dry:
        index.apply_events([rr])
    sink = _BatchSink(index) if index is not None else None

    cat = lake.LakeCatalog.load()
    pending: list[tuple[str, str, dict]] = []
    stage_root = paths.lake_tmp_dir() / "rebuild" / f"absorb-{run_seq}"

    def catalog_kw(idc, n_files, nbytes, state):
        kw = {"source": source, "n_files": n_files, "bytes": nbytes,
              "absorbed_from": str(bytes_root)}
        if manifested is not None:
            kw["manifested"] = idc in manifested
        return kw

    for child in sorted(bytes_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        res = _canon_gate(child.name, registry)
        if not res.ok:
            stats["noncanon_dirs"].append(child.name)
            continue
        idc = res.idc
        sid = idnorm.safe_id(idc)
        dest = lake.cell_dir(idc, source)
        cur = cat.state(idc)
        if lake.is_complete(idc, source) or (
                cur == "raw_only" and (dest / "raw").exists()):
            stats["already"] += 1
            if cur == "absent":
                # published but never catalogued (crashed absorb) — heal
                meta = lake._read_meta(dest)
                n = meta.get("n_files") or 0
                pending.append((idc, "hydrated",
                                catalog_kw(idc, n, dir_size(dest), cur)))
            continue

        meta = lake._read_meta(child)
        raws = _legacy_raw_files(child, meta)
        exdir = child / "extracted"
        extracted = sorted(
            p for p in exdir.rglob("*") if p.is_file()
        ) if exdir.is_dir() else []
        if not raws and not extracted:
            stats["no_payload"].append(child.name)
            continue
        stats["bytes_in"] += dir_size(child)
        if dry:
            stats["absorbed"] += 1
            stats["raw_only"] += int(not extracted)
            continue

        stage = stage_root / f"{sid}.stage"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        raw_shas = []
        for rf in raws:
            sha = cas.store_file(rf, kind="blob")
            cas.link_out(sha, stage / "raw" / rf.name, kind="blob")
            raw_shas.append(sha)
            stats["objs_stored"] += 1
        for f in extracted:
            rel = f.relative_to(exdir)
            sha = cas.store_file(f, kind="file")
            cas.link_out(sha, stage / "extracted" / rel, kind="file")
            stats["objs_stored"] += 1
        for keep in ("files.txt", "mtree.txt"):
            bk = child / keep
            if bk.is_file():
                sha = cas.store_file(bk, kind="file")
                cas.link_out(sha, stage / keep, kind="file")
        n = lake._payload_count(stage)
        new_meta = {
            **meta, "idc": idc, "source": source, "n_files": n,
            "raw_sha256": raw_shas[0] if len(raw_shas) == 1 else raw_shas,
            "absorbed_from": str(child), "absorb": True,
            "hydrated_at": round(time.time(), 3), "run_seq": run_seq,
        }
        fsutil.atomic_write(
            stage / "meta.json",
            json.dumps(new_meta, ensure_ascii=False, sort_keys=True,
                       indent=2).encode("utf-8"),
        )
        with lake.lake_lock(sid):
            if lake.is_complete(idc, source):
                shutil.rmtree(stage, ignore_errors=True)
                stats["already"] += 1
                continue
            won = lake._publish_stage(stage, dest)
        if not won:
            shutil.rmtree(stage, ignore_errors=True)
            stats["already"] += 1
            continue
        state = "hydrated" if extracted else "raw_only"
        stats["absorbed"] += 1
        stats["raw_only"] += int(not extracted)
        pending.append(
            (idc, state, catalog_kw(idc, n, dir_size(dest), state)))

    if not dry and pending:
        cat.set_bulk(pending, sink=sink, run_dir=rdir)
        stats["emitted"] = stats["events"] = len(pending)
        ev = events.make_event(
            events.T_NOTE, run="import-lake-absorb", run_seq=run_seq, seq=1,
            level="info",
            text=(f"corpus absorb: {stats['absorbed']} cells "
                  f"({stats['raw_only']} raw_only), {stats['already']} "
                  f"already present, {len(stats['noncanon_dirs'])} "
                  f"noncanon dirs, {stats['objs_stored']} objects"))
        ledger.emit(ev, run_dir=rdir, sink=sink)
        stats["events"] += 1
        if sink is not None:
            stats["applied"] = sink.flush()
    elif dry:
        stats["events"] = len(pending)
    return stats


# ---------------------------------------------------------------------------
# Umbrella
# ---------------------------------------------------------------------------

def import_all(sources: dict, index, registry=None, dry: bool = False) -> dict:
    """Drive every configured source and merge counters.

    sources keys:
        benchdb     -> path to bench.db
        jsonl_files -> iterable of records*.jsonl/cases.jsonl paths
        scan_root   -> dir; every records*.jsonl/cases.jsonl under it is
                       imported, one ledger run per file
        zhstore     -> {"manifest": path, "bytes_root": path} or a
                       (manifest, bytes_root) tuple
    """
    total = _stats()
    total["per_source"] = {}

    def merge(key, res):
        total["per_source"][key] = res
        for k, v in res.items():
            if isinstance(v, int) and k in total:
                total[k] += v

    if sources.get("benchdb"):
        merge("benchdb", import_benchdb(sources["benchdb"], index,
                                        registry=registry, dry=dry))

    # jsonl files: one ledger run per FILE — per-file seqs can never
    # collide on (run_seq, seq). Explicit files get a name-derived run;
    # scan_root files carry their scan-relative path so two same-named
    # files in different dirs stay distinct.
    files = [(Path(f), None) for f in sources.get("jsonl_files") or []]
    scan = sources.get("scan_root")
    if scan:
        scan = Path(scan)
        seen: set[Path] = set()

        def _add(f: Path) -> None:
            if not f.is_file() or f in seen:
                return
            seen.add(f)
            rel = f.relative_to(scan).with_suffix("").as_posix()
            files.append((f, f"import-{_slugify(rel)}"))

        for pat in _SCAN_PATTERNS:
            for f in sorted(scan.rglob(pat)):
                _add(f)
        # stagerun stage ledgers live as records/{stage}.jsonl — the
        # stage name is the file stem, so the records-dir sweep is the
        # only way "records jsonl 全扫" actually reaches them.
        for d in sorted(scan.rglob("records")):
            if d.is_dir():
                for f in sorted(d.glob("*.jsonl")):
                    _add(f)
    acc = _stats()
    for f, run_name in files:
        stage_map = (
            {f.name: f.stem} if f.parent.name == "records" else None
        )
        r = import_jsonl_file(f, run=run_name, index=index,
                              stage_map=stage_map,
                              registry=registry, dry=dry)
        for k, v in r.items():
            if isinstance(v, int) and k in acc:
                acc[k] += v
    if files:
        merge("jsonl", acc)

    if sources.get("zhstore"):
        zs = sources["zhstore"]
        if isinstance(zs, dict):
            mpath, broot_ = zs["manifest"], zs["bytes_root"]
        else:
            mpath, broot_ = zs
        merge("zhstore", import_zhstore(mpath, broot_, index,
                                        registry=registry, dry=dry))
    return total


__all__ = [
    "EMIT_CHUNK",
    "PAID_ARMS",
    "SECRET_PATTERNS",
    "absorb_corpus",
    "import_all",
    "import_benchdb",
    "import_jsonl_file",
    "import_zhstore",
    "redact",
    "register_lake_manifests",
]
