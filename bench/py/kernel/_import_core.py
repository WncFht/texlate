"""kernel._import_core — 导入管线共享机件 (kernel.importer 拆分叶).

所有源域共用的导入骨架: tunables/词表、密钥子串识别与 ``redact`` 深脱
敏 (R1 — secrets never reach the ledger)、quarantine.jsonl sha 去重追加、
status/canon 闸 (§3.10.7)、import run 注册 (``_ensure_import_run`` +
``.lock`` R21)、行规整 (``_norm_db_record``/``_norm_db_raw``/
``_norm_jsonl_row`` 三源归一 rec)、rec→事件转换 (``_rec_to_event``)、
保守序解析 (``_resolve_order`` — paid 保 done-ish/free 保 retriable) 与
``emit_batch`` 分块幂等落账 (``_commit``)。

源域叶 ``_import_records``/``_import_zhstore``/``_import_lake`` 只含各自
源的驱动逻辑, 机件一律从本叶取。门面回引名单见 ``importer._LEAF_EXPORTS``;
未回引的私名请直引本模块 (monkeypatch 锚亦归本叶, setattr 门面无效)。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from kernel import events, idnorm, ledger, paths
from kernel.events import iter_jsonl

# ---------------------------------------------------------------------------
# Tunables / vocab
# ---------------------------------------------------------------------------

EMIT_CHUNK = 5000

# bench.db has no paid flag per stage; the gateway arm is 'real'.
PAID_ARMS = frozenset({"real"})

# Conservative-resolution preference sets (§3.3).
_DONE_ISH = frozenset({"ok", "partial", "clean"})
_NEG_TERM = frozenset({"fail", "fault", "reject", "dirty_pdf"})


# --- secret patterns --------------------------------------------------------
# Key material resolves from the live env at call time — no key literal
# belongs in source. TEXLATE_REDACT_SUBSTR takes a comma-list of extra scrub
# substrings (rotated/dead keys, deploy strings). <4 chars is too promiscuous
# for a substring scan.
def _secret_substrings() -> tuple:
    subs: list = []
    for name in ("TEXLATE_API_KEY", "TEXLATE_GATEWAY_KEY"):
        v = os.environ.get(name, "").strip()
        if len(v) >= 4 and v not in subs:
            subs.append(v)
    for tok in os.environ.get("TEXLATE_REDACT_SUBSTR", "").split(","):
        t = tok.strip()
        if len(t) >= 4 and t not in subs:
            subs.append(t)
    return tuple(subs)


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
_AUTH_KEYS_RAW = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "x-api-key",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "passwd",
        "password",
        "secret",
        "client_secret",
        "auth",
        "bearer",
        "cookie",
        "set-cookie",
        "private_key",
        "credentials",
        "session_key",
        "gateway_key",
        "auth_token",
        "api_secret",
        "secret_key",
        "session_token",
        "bearer_token",
        "app_key",
        "private_token",
    }
)
_SEP_RE = re.compile(r"[-_.\s]+")
_AUTH_KEYS = frozenset(_SEP_RE.sub("", k) for k in _AUTH_KEYS_RAW)

# Exported per the module contract — introspectable redaction surface.
# "substrings" is an import-time snapshot; checks call _secret_substrings()
# live so env changes mid-process still apply.
SECRET_PATTERNS = {
    "substrings": _secret_substrings(),
    "regexes": (_TAILSCALE_RE,),
    "auth_keys": _AUTH_KEYS,
}


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
    return events.dumps(obj, default=str)


# ---------------------------------------------------------------------------
# Redaction (R1 — secrets never reach the ledger)
# ---------------------------------------------------------------------------


def _authish(key) -> bool:
    return isinstance(key, str) and _SEP_RE.sub("", key).lower() in _AUTH_KEYS


def _scalar_secret(s: str) -> bool:
    return any(sub in s for sub in _secret_substrings()) or bool(
        _TAILSCALE_RE.search(s)
    )


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
                    out[f"$redact:{_sha(kk)[:16]}"] = {"$redact": _sha(_jcanon(v))}
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
            if any(sub in s for sub in _secret_substrings()):
                n += 1
                return {"$redact": _sha(s)}
            return o
        if isinstance(o, (bytes, bytearray)):
            n += 1
            return {
                "$nonjson": "bytes",
                "len": len(o),
                "sha256": hashlib.sha256(bytes(o)).hexdigest(),
            }
        if o is None:
            return o
        # sets, datetimes, other non-JSON scalars — never ship content,
        # keep a verifiable fingerprint
        n += 1
        return {"$nonjson": type(o).__name__, "sha256": _sha(repr(o)[:8192])}

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


def _ensure_import_run(
    index, run_name: str, *, date: str, slug: str, spec_hash: str, dry: bool
):
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
            {k: v for k, v in row.items() if k not in ("rec_id", "run_id")}
        ),
    }


def _norm_jsonl_row(
    row: dict, *, fname: str, file_ts: float, stage_map: dict | None
) -> dict:
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


def _rec_to_event(
    rec: dict,
    *,
    run_name: str,
    run_seq: int,
    registry,
    src: str,
    stats: dict,
    quar: list,
):
    """Normalized rec -> cell event (seq=0 placeholder), or None when the
    row routes to quarantine (appended to `quar`)."""
    id_raw = rec.get("id")
    # the source db's own adjudication (id_canon) outranks re-resolving the
    # raw spelling; absent it, gate on id as before.
    res = _canon_gate(rec.get("canon_hint") or id_raw, registry)
    if not res.ok:
        payload, n_red = redact(rec)
        stats["redacted"] += n_red
        quar_row, n_red2 = redact(
            {
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
            }
        )
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

    status, orig = _status_of(rec.get("status"), default=rec["default_status"])
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
        a key-substring-shaped float (e.g. the numeric prefix inside a
        longer number), and any non-numeric value drops out
        here rather than tripping schema-quarantine for the whole row."""
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        if any(sub in repr(v) for sub in _secret_substrings()):
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
        quar_row, n_red = redact(
            {
                "type": "import_quarantine",
                "src": src,
                "run": run_name,
                "reason": f"schema:{exc}",
                "canon_state": res.state,
                "id": id_raw,
                "dedup_sha": _sha(rec["dedup_sig"]),
                "payload": {"id": id_raw, "stage": rec["stage"], "status": status},
                "ts": rec["ts"],
            }
        )
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


def _resolve_order(
    evs: list, *, run_name: str, src: str, stats: dict, quar: list
) -> list:
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
            quar_row, n_red = redact(
                {
                    "type": "import_order_sensitive",
                    "src": src,
                    "run": run_name,
                    "idc": k[0],
                    "arm": k[1],
                    "up": k[2],
                    "variant": k[3],
                    "stage": k[4],
                    "n": len(g),
                    "statuses": sorted(set(statuses), key=repr),
                    "chosen": pref.get("status"),
                    "paid": paid,
                }
            )
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
        part = shas[i : i + 900]
        marks = ",".join("?" * len(part))
        for row in index.conn.execute(
            f"SELECT payload_sha FROM dedupe WHERE payload_sha IN ({marks})",  # noqa: S608 -- marks 是 "?"*n 占位符，本模块内构造
            part,
        ):
            known.add(row[0])
    return known


def _commit(evs: list, *, rdir: Path | None, index, stats: dict, dry: bool) -> None:
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
        stats["dup_skipped"] += sum(1 for e in evs if events.content_hash(e) in known)
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
        chunk = new[i : i + EMIT_CHUNK]
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
        "rows": 0,
        "events": 0,
        "emitted": 0,
        "applied": 0,
        "dup_skipped": 0,
        "quarantined": 0,
        "quar_written": 0,
        "redacted": 0,
        "order_sensitive": 0,
        "runs": 0,
        "runs_minted": 0,
        "bad_lines": 0,
        "index_rejected": 0,
    }


def _prepare_run(
    rows,
    *,
    run_name: str,
    run_seq: int,
    registry,
    src: str,
    stats: dict,
    quar: list,
    norm_fn,
) -> list:
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
        ev = _rec_to_event(
            rec,
            run_name=run_name,
            run_seq=run_seq,
            registry=registry,
            src=src,
            stats=stats,
            quar=quar,
        )
        if ev is not None:
            prepared.append(ev)
    evs = _resolve_order(prepared, run_name=run_name, src=src, stats=stats, quar=quar)
    for i, ev in enumerate(evs, 1):
        ev["seq"] = i
    stats["events"] += len(evs)
    return evs
