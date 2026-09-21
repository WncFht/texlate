"""Paid-gate dedup oracle — the fail-closed brain (design §3.6, §3.10.6).

This module exists to kill one failure mode: any projection gap that answers
"not paid yet" while paid bytes or paid history exist. Every evidentiary gap
resolves toward REFUSING spend, never toward allowing it.

Verdicts (check()):

    unsealed  index generation/watermark/dirty gate failed — retriable-
              terminal + alarm, NEVER proceeds (§3.10.6 ①③)
    claimed   live claim lease held by another runner — skip, not an error
    verified  durable evidence of paid bytes — dedup skip
    missing   tombstone/quar evidence with no verified leg — regen_gate
              hard stop upstream; the id never auto-enters a run set
    absent    no evidence anywhere — proceed, and ONLY ever issued on a
              sealed index

Check order is the contract (implemented exactly as listed in §3.10.6):

    1. unsealed FIRST, before every other answer — even a manifest row that
       says verified. Tradeoff: a durable 'verified' skipped behind an
       unsealed index errs toward re-pay... but the seal failure is itself
       the alarm condition that must surface, and a stale index cannot be
       trusted about tombstones (the answer that PROTECTS the wallet).
       Uniform 'unsealed' keeps that signal loud; the claim lease remains
       the true spend mutex underneath.
    2. claimed — flock NB probe, the authoritative life/death proof; NB
       only, never blocking (leaf-lock position, §3.10.6 lock order).
    3. verified — DURABLE legs only: manifest-tail bytes_ok rows, vault
       meta files on disk, the frozen paid_pool snapshot. The live index
       (incl. index.vault_bytes_ok()) is advisory and deliberately NOT a
       verified leg — a lagging projection must never be the reason we
       skip a burn, and equally never the reason we burn again.
    4. missing — tombstone/quar evidence (index vault_meta, last-cell
       lost/regen_gate/upstream-lost markers, durable meta verdicts) AND
       no verified leg. quar verdicts sit in BOTH sets on purpose: §3.8
       makes quarantine a dedup hit when bytes exist (verified leg fires
       first), while a quar verdict with no byte evidence is precisely
       §3.6's missing∪quarantine hard stop.
    5. absent — issued only because the index is sealed.

attempted-unpaid (§3.6): paid-arm cells whose terminal status is
reject/fail/fault/dirty_pdf never join the paid pool and never auto-rerun.
check() answers 'absent' for them — the runner's index.done() leg already
treats those statuses as terminal before the oracle is consulted; the
oracle's job is the bytes-domain three-state. quote() buckets them
'attempted' explicitly so plan-time never schedules and --regen never
redeems them.

regen (§3.6): tombstoned ids ship as a decision list, never a run set.
--regen needs ALL of --sel hit + --max-cost set + --yes + --allow-regen;
--rerun/--recode have NO power over paid cells.
"""
from __future__ import annotations

import json
from pathlib import Path

from kernel import claims, paths
from kernel.idnorm import canon_id, idc_from_safe, unescape_component

__all__ = [
    "ABSENT",
    "ATTEMPTED_UNPAID",
    "BYTES_OK_VERDICTS",
    "CLAIMED",
    "MISSING",
    "MISSING_VERDICTS",
    "UNSEALED",
    "VERIFIED",
    "DedupOracle",
    "attempted_unpaid",
    "manifest_tail",
    "tombstoned",
]

# -- verdict vocabulary ---------------------------------------------------------

VERIFIED = "verified"
ABSENT = "absent"
MISSING = "missing"
CLAIMED = "claimed"
UNSEALED = "unsealed"

# vault_meta verdicts whose bytes count as present — mirrors
# index._VAULT_BYTES_OK (§3.8 dedup-hit verdicts). 'pending'/'staged' are
# deliberately absent: pending is treated as no-bytes; the claim lease is
# what blocks a double-burn on staged bytes.
BYTES_OK_VERDICTS = frozenset(
    {"verified", "primary", "alt", "quar", "quarantine", "adopted"}
)

# Verdicts counted as missing-side evidence. quar/quarantine appear in BOTH
# sets: check order (verified before missing) decides which reading wins —
# bytes-backed quar verifies, bytes-less quar hard-stops.
MISSING_VERDICTS = frozenset({"tombstone", "quar", "quarantine", "lost"})

# Paid-arm terminal statuses that mean "we tried, it did not translate" —
# §3.6 attempted-unpaid bucket: not paid-pool, not default-rerun, never
# auto-regen.
ATTEMPTED_UNPAID = frozenset({"reject", "fail", "fault", "dirty_pdf"})

# last-cell states that are themselves bytes-lost / gate-stop evidence.
MISSING_CELL_STATUSES = frozenset({"lost", "unpaid_gate"})
MISSING_CATS = frozenset({"regen_gate", "upstream-lost"})

# manifest/meta zone spellings that assert byte loss.
LOSS_ZONES = frozenset({"tombstone", "lost", "missing"})

_MANIFEST_TAIL_ROWS = 5000        # §3.10.6 ②: ~5k tail rows, hashed at run start
_MANIFEST_WINDOW = 4 * 1024 * 1024  # byte window covering ~5k manifest rows


# -- small helpers ---------------------------------------------------------------


def _norm(v, default: str = "-") -> str:
    return default if v is None or v == "" else str(v)


def _canon(raw):
    """canon_id().idc when resolvable without a registry, else None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        res = canon_id(raw.strip())
    except Exception:
        return None
    return res.idc if res.ok else None


def _row_key(row) -> tuple[str, str, str] | None:
    """(idc, arm, variant) from a manifest/meta row dict; None if no id."""
    idc = row.get("idc")
    if not isinstance(idc, str) or not idc:
        idc = _canon(row.get("id") or row.get("resolved"))
    if not isinstance(idc, str) or not idc:
        return None
    return idc, _norm(row.get("arm")), _norm(row.get("variant"))


# -- manifest tail (durable verified leg ①) ----------------------------------------


def _manifest_bytes_value(row):
    """Byte-evidence tri-state for one manifest row.

    True  row asserts paid bytes present (bytes_ok, or declared assets)
    False row asserts loss/demote (explicit bytes_ok:false, loss zone)
    None  row carries no byte statement — does not fold (a promote note
          must not erase an earlier bytes_ok row)
    """
    if "bytes_ok" in row:
        return bool(row["bytes_ok"])
    zone = str(row.get("zone") or "").lower()
    if zone in LOSS_ZONES:
        return False
    assets = row.get("assets")
    if isinstance(assets, dict):
        return any(bool(v) for v in assets.values())
    if isinstance(assets, (list, tuple)):
        return len(assets) > 0
    flags = [row.get(k) for k in ("has_zh", "has_splice", "has_state") if k in row]
    if flags:
        return any(bool(v) for v in flags)
    return None


def _read_tail_lines(path: Path, max_rows: int) -> list[bytes]:
    """Last ~max_rows newline-terminated lines; tolerant of a torn head."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size == 0:
        return []
    with open(path, "rb") as f:
        f.seek(max(0, size - _MANIFEST_WINDOW))
        data = f.read()
    lines = data.split(b"\n")
    if size > _MANIFEST_WINDOW:
        lines = lines[1:]  # first element is a torn line — drop it
    rows = [ln for ln in lines if ln.strip()]
    return rows[-max_rows:]


def manifest_tail(path=None, max_rows: int = _MANIFEST_TAIL_ROWS) -> set[tuple]:
    """(idc,arm,variant) set whose LAST manifest row per altseq asserts bytes.

    Reads the last ~5000 rows of vault/manifest.jsonl tolerantly (bad lines
    skipped — the iter_jsonl read-side contract). Per §3.10.4 last-row-wins
    is evaluated per altseq: a demote row only kills its own copy's
    evidence. Rows with no byte statement (metadata-only) never erase a
    prior bytes_ok row.
    """
    p = Path(path) if path is not None else paths.vault_manifest_path()
    evidence: dict[tuple, bool] = {}
    for raw in _read_tail_lines(p, max_rows):
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        key = _row_key(row)
        if key is None:
            continue
        val = _manifest_bytes_value(row)
        if val is None:
            continue
        altseq = str(row.get("altseq", "0") or "0")
        evidence[(*key, altseq)] = val
    return {k[:3] for k, v in evidence.items() if v}


# -- vault meta scan (durable verified leg ②) --------------------------------------


def _meta_key_from_name(name: str) -> tuple | None:
    """Filename-derived (idc,arm,variant,altseq); None when unparseable.

    Layout (§3.10.4): ``{safe_id}.{arm}[@{variant}][.{altseq}].json`` with
    every component percent-escaped — literal '.'/'@' are separators,
    in-component ones are %2E/%40. Split on raw separators FIRST, then
    unescape, or an escaped '@' inside arm would fake a variant split.
    """
    stem = name.removesuffix(".json")
    raw = stem.split(".")
    if len(raw) < 2:
        return None
    seg_arm, _, seg_var = raw[1].partition("@")
    idc = idc_from_safe(unescape_component(raw[0]))
    arm = unescape_component(seg_arm)
    variant = unescape_component(seg_var) if seg_var else "-"
    altseq = unescape_component(raw[2]) if len(raw) > 2 else "0"
    if not idc:
        return None
    return idc, _norm(arm), _norm(variant), altseq


def _meta_declares_bytes(rec) -> bool:
    """meta declares ≥1 vault asset non-empty (§3.5 dedup 判据).

    Tolerant across meta shapes: an assets dict/list, has_* flags, direct
    zh/splice/state fields, or a files/blobs list.
    """
    assets = rec.get("assets")
    if isinstance(assets, dict):
        return any(bool(assets.get(k)) for k in ("zh", "splice", "state"))
    if isinstance(assets, (list, tuple)):
        return bool(assets)
    flags = [rec.get(k) for k in ("has_zh", "has_splice", "has_state") if k in rec]
    if flags:
        return any(bool(v) for v in flags)
    if any(rec.get(k) for k in ("zh", "splice", "state")):
        return True
    files = rec.get("files") or rec.get("blobs")
    return isinstance(files, (list, tuple)) and bool(files)


def _scan_vault_meta(idc: str, arm: str, variant: str):
    """Durable meta-dir scan for one cell -> (bytes_ok, missing, io_error).

    Filename prefilter keeps JSON parses to candidate files; a file whose
    name does not parse gets body-checked (anomaly direction is spend-
    blocking either way). Per-file parse failures skip per the tolerant
    read contract — meta 可解析 is part of the §3.5 dedup criterion, so an
    unreadable meta simply is not byte evidence.
    """
    d = paths.vault_meta_dir()
    target = (idc, _norm(arm), _norm(variant))
    bytes_ok = miss = io_error = False
    try:
        files = sorted(d.rglob("*.json"))
    except OSError:
        return False, False, True
    for p in files:
        key = _meta_key_from_name(p.name)
        if key is not None and key[:3] != target:
            continue  # filename says: not our cell — body can't help
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(rec, dict):
            continue
        bkey = _row_key(rec) or (key[:3] if key else None)
        if bkey != target:
            continue
        verdict = str(rec.get("verdict") or rec.get("state") or "").lower()
        if verdict in BYTES_OK_VERDICTS and _meta_declares_bytes(rec):
            bytes_ok = True
        if verdict in MISSING_VERDICTS:
            miss = True
    return bytes_ok, miss, io_error


# -- index-side evidence (only ever read under a seal) -----------------------------


def tombstoned(index, idc, arm, variant) -> bool:
    """Tombstone events present for the cell (index vault_meta projection).

    Tombstone events and tombstone-state assets both project to
    vault_meta verdict='tombstone' (§3.2); 'lost' covers the sweep's
    lost-marker form.
    """
    row = index.conn.execute(
        "SELECT 1 FROM vault_meta"
        " WHERE idc=? AND arm=? AND variant=?"
        " AND verdict IN ('tombstone','lost') LIMIT 1",
        (idc, _norm(arm), _norm(variant)),
    ).fetchone()
    return row is not None


def attempted_unpaid(index, idc, arm, variant) -> bool:
    """Paid-arm terminal in {reject,fail,fault,dirty_pdf} (§3.6 bucket).

    True when some stage's LAST state is an attempted-unpaid status and no
    stage's last state is ok|partial (a later success already puts the cell
    in the paid pool — attempted must not stick). regen_gate rejects are
    gate artifacts, not instrument attempts — excluded.
    """
    rows = index.conn.execute(
        "SELECT status, cat FROM cells WHERE idc=? AND arm=? AND variant=?",
        (idc, _norm(arm), _norm(variant)),
    ).fetchall()
    if any(r["status"] in ("ok", "partial") for r in rows):
        return False
    return any(
        r["status"] in ATTEMPTED_UNPAID and r["cat"] != "regen_gate"
        for r in rows
    )


def _events_tail_offset() -> int:
    """fsync'd ledger tail offset at call time (§3.10.6 min_offset basis)."""
    try:
        from kernel import ledger  # type: ignore[import-not-found]
    except ImportError:
        ledger = None
    fn = getattr(ledger, "watermark_offset", None) if ledger is not None else None
    if fn is not None:
        return int(fn())
    p = paths.events_path()
    try:
        size = p.stat().st_size
    except FileNotFoundError:
        return 0
    if size == 0:
        return 0
    with open(p, "rb") as f:
        pos = size
        while pos > 0:
            step = min(65536, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step)
            i = buf.rfind(b"\n")
            if i >= 0:
                return pos + i + 1
    return 0


# -- the oracle --------------------------------------------------------------------


class DedupOracle:
    """Fail-closed paid-dedup oracle, snapshotted at run start (§3.10.6).

    Holds three frozen legs — manifest tail bytes_ok set, paid_pool
    snapshot, sealed (gen, min_offset) — plus the live index it re-checks
    the seal against on every call. Frozen legs are the anti-gap: they are
    durable facts captured once, so a projection that goes stale mid-run
    cannot silently downgrade a 'verified' into an 'absent'.
    """

    def __init__(
        self,
        index,
        manifest_tail: set[tuple] | None = None,
        paid_pool_snap: set[tuple] | None = None,
        sealed_gen: int = 0,
        min_offset: int = 0,
    ):
        self.index = index
        self.manifest_tail = frozenset(manifest_tail or ())
        self.paid_pool_snap = frozenset(paid_pool_snap or ())
        self.sealed_gen = int(sealed_gen)
        self.min_offset = int(min_offset)

    @classmethod
    def snapshot(cls, index) -> "DedupOracle":
        """Capture the run-start oracle (§3.10.6 ②).

        sealed_gen/min_offset come from index.sealed_state() — lifted to
        the live fsync'd ledger tail so a snapshot taken before
        tail_ingest catches up reads 'unsealed' instead of trusting a
        behind-watermark projection. manifest_tail parses the last ~5000
        vault manifest rows tolerantly; paid_pool_snap freezes
        index.paid_pool() for the plan.
        """
        gen, wm = index.sealed_state()
        return cls(
            index,
            manifest_tail=manifest_tail(),
            paid_pool_snap=index.paid_pool(),
            sealed_gen=gen,
            min_offset=max(wm, _events_tail_offset()),
        )

    # -- seal gate -----------------------------------------------------------------

    def sealed(self) -> bool:
        """Seal predicate as check() evaluates it right now."""
        return not self.index.dirty() and self.index.check_sealed(
            self.sealed_gen, self.min_offset
        )

    # -- per-cell verdict ------------------------------------------------------------

    def check(self, idc, arm: str = "-", variant: str = "-",
              stage_paid: bool = True) -> str:
        """Five-state paid-gate verdict — ORDER IS THE CONTRACT.

        stage_paid marks whether the caller's stage is paid; the oracle's
        evidence is paidness-agnostic (claims and bytes mean the same
        thing either way) — the flag is carried for quote()'s attempted
        bucketing and the caller's §3.8 interpretation.
        """
        idc, arm, variant = str(idc), _norm(arm), _norm(variant)
        key = (idc, arm, variant)

        # 1. unsealed — first, even when durable legs say verified. A stale
        #    index can't be trusted about tombstones; the seal failure is
        #    the alarm that must surface (retriable-terminal upstream).
        if self.index.dirty() or not self.index.check_sealed(
            self.sealed_gen, self.min_offset
        ):
            return UNSEALED

        # 2. claimed — flock NB probe only; an un-probe-able claim is an
        #    indeterminate state, which resolves to 'unsealed' (the one
        #    non-committal answer) rather than ever greenlighting spend.
        try:
            if claims.ClaimLease(idc, arm, variant).held_by_other():
                return CLAIMED
        except OSError:
            return UNSEALED

        # 3. verified — durable/frozen legs only: manifest tail bytes_ok,
        #    vault meta on disk, the frozen paid_pool snapshot. The live
        #    index is advisory, never a verified leg.
        meta_ok, meta_missing, meta_io_error = _scan_vault_meta(idc, arm, variant)
        if meta_io_error:
            return UNSEALED
        if key in self.manifest_tail or key in self.paid_pool_snap or meta_ok:
            return VERIFIED

        # 4. missing — tombstone/quar evidence with no verified leg.
        if meta_missing or self._missing_evidence(idc, arm, variant):
            return MISSING

        # 5. absent — reachable only because the index is sealed.
        return ABSENT

    def _missing_evidence(self, idc, arm, variant) -> bool:
        """Index-side tombstone/quar/lost evidence (seal already passed)."""
        if tombstoned(self.index, idc, arm, variant):
            return True
        row = self.index.conn.execute(
            "SELECT 1 FROM vault_meta"
            " WHERE idc=? AND arm=? AND variant=?"
            " AND verdict IN ('quar','quarantine') LIMIT 1",
            (idc, arm, variant),
        ).fetchone()
        if row is not None:
            return True
        for r in self.index.conn.execute(
            "SELECT status, cat FROM cells WHERE idc=? AND arm=? AND variant=?",
            (idc, arm, variant),
        ):
            if r["status"] in MISSING_CELL_STATUSES or r["cat"] in MISSING_CATS:
                return True
        return False

    # -- plan-time report -------------------------------------------------------------

    def quote(self, cells) -> dict:
        """Five-bucket plan report + regen decision list.

        cells: iterable of (idc,arm[,variant]) tuples, full cell-key tuples
        (idc,arm,up,variant,stage[,...]), or dicts carrying idc/id, arm,
        variant, and optionally stage_paid|paid.

        Buckets: new (absent, runnable), reuse (verified), missing
        (tombstone/quar — the regen_decisions list, never auto-entered),
        claimed (live lease), attempted (paid-arm terminal unpaid — never
        default-rerun, never regen-redeemed). 'unsealed' is a sixth bucket
        carrying cells the seal gate refused to classify — under a sealed
        index it is always empty, so the spec'd five partition the input.
        """
        buckets: dict[str, list] = {
            k: [] for k in ("new", "reuse", "missing", "claimed", "attempted", "unsealed")
        }
        for c in cells:
            idc, arm, variant, paid = _cell_spec(c)
            key = (idc, arm, variant)
            res = self.check(idc, arm, variant, stage_paid=paid)
            if res == VERIFIED:
                buckets["reuse"].append(key)
            elif res == CLAIMED:
                buckets["claimed"].append(key)
            elif res == MISSING:
                buckets["missing"].append(key)
            elif res == UNSEALED:
                buckets["unsealed"].append(key)
            elif paid and attempted_unpaid(self.index, idc, arm, variant):
                buckets["attempted"].append(key)
            else:
                buckets["new"].append(key)
        counts = {k: len(v) for k, v in buckets.items()}
        return {
            **counts,
            "total": len(buckets["new"]) + len(buckets["reuse"])
            + len(buckets["missing"]) + len(buckets["claimed"])
            + len(buckets["attempted"]) + len(buckets["unsealed"]),
            "buckets": buckets,
            "regen_decisions": sorted(buckets["missing"]),
            "sealed": self.sealed(),
        }

    # -- regen gate ---------------------------------------------------------------------

    def regen_allowed(self, idc, arm, variant, allow_regen: bool,
                      sel_hit: bool, max_cost, yes: bool) -> bool:
        """--regen needs ALL FOUR: allow_regen flag + --sel hit on this cell
        + --max-cost set + --yes. --rerun/--recode have NO power over paid
        cells — this is the only door (§3.6). The cell identity pins which
        regen_decisions entry is being authorized; intersecting with the
        missing list is the caller's job."""
        return bool(
            allow_regen
            and sel_hit
            and max_cost is not None
            and yes
        )


def _cell_spec(cell) -> tuple[str, str, str, bool]:
    """Normalize a plan-cell spec -> (idc, arm, variant, stage_paid).

    dict:   {idc|id, arm?, variant?, stage_paid?|paid?}
    tuple:  (idc,arm) | (idc,arm,variant) | (idc,arm,up,variant,stage,...)
    """
    if isinstance(cell, dict):
        idc = cell.get("idc")
        if not isinstance(idc, str) or not idc:
            idc = _canon(cell.get("id")) or cell.get("id")
        paid = cell.get("stage_paid", cell.get("paid", True))
        return str(idc), _norm(cell.get("arm")), _norm(cell.get("variant")), bool(paid)
    seq = list(cell)
    idc = str(seq[0])
    arm = _norm(seq[1] if len(seq) > 1 else "-")
    if len(seq) >= 4:
        variant = _norm(seq[3])  # full cell key: (idc,arm,up,variant,stage,...)
    else:
        variant = _norm(seq[2] if len(seq) > 2 else "-")
    return idc, arm, variant, True
