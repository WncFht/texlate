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
       no verified leg. A committed meta verdict whose declared bytes are
       physically gone also lands here — that is §3.6's third state
       (付过费但字节没了), not a silent skip and never an ungated re-pay.
       quar verdicts sit in BOTH sets on purpose: §3.8
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
from kernel.idnorm import canon_id

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
    "manifest_kind_evidence",
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


# has_* legacy flag spellings -> the kind each speaks for.
_FLAG_KINDS = {"has_zh": "zh", "has_splice": "splice", "has_state": "state"}


def _row_kind_statements(row, val: bool) -> list:
    """Kinds one byte-statement row vouches for (val True) or kills
    (val False): 'kinds'/'dirs' (harvest), 'kind' (tombstone),
    'moved'/'missing' (promote), 'assets' keys matching the statement's
    polarity, and has_<kind> flags matching it. Empty => the row is
    kind-AGNOSTIC (legacy shape) and folds on the altseq axis only."""
    kinds: list[str] = []
    for fld in ("kinds", "moved", "missing"):
        v = row.get(fld)
        if isinstance(v, (list, tuple)):
            kinds.extend(str(k) for k in v)
    v = row.get("dirs")
    if isinstance(v, dict):
        kinds.extend(str(k) for k in v)
    v = row.get("kind")
    if isinstance(v, str) and v:
        kinds.append(v)
    v = row.get("assets")
    if isinstance(v, dict):
        kinds.extend(str(k) for k, vv in v.items() if bool(vv) == val)
    for fld, kind in _FLAG_KINDS.items():
        if fld in row and bool(row[fld]) == val:
            kinds.append(kind)
    return list(dict.fromkeys(kinds))


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


def _manifest_fold(path=None, max_rows: int = _MANIFEST_TAIL_ROWS) -> dict:
    """Per-cell byte evidence from the manifest tail, split two ways:

    "alt"   kind-agnostic statements keyed by altseq — last-row-wins per
            copy (§3.10.4: a demote kills only its own altseq).
    "kind"  per-kind statements keyed by (kind, altseq) -> (pos, val).
    "wild"  per-kind altseq-free statements -> (pos, val); the tombstone
            shape, which kills the kind cell-wide unless a LATER
            altseq-scoped row re-asserts it.

    pos is the row's ordinal in the tail stream — the ordering that lets
    a harvest re-seal a kind a tombstone previously killed.
    """
    p = Path(path) if path is not None else paths.vault_manifest_path()
    evidence: dict[tuple, dict] = {}
    pos = 0
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
        pos += 1
        entry = evidence.setdefault(
            key, {"alt": {}, "kind": {}, "wild": {}})
        kinds = _row_kind_statements(row, val)
        altseq = row.get("altseq")
        if not kinds:
            a = str(altseq if altseq is not None else "0") or "0"
            entry["alt"][a] = val
            continue
        for kind in kinds:
            if altseq is None:
                entry["wild"][kind] = (pos, val)
            else:
                entry["kind"].setdefault(kind, {})[str(altseq)] = (pos, val)
    return evidence


def _resolve_kinds(entry: dict) -> tuple[set, set]:
    """(alive, dead) kind sets for one cell's folded evidence.

    A kind is alive iff some altseq's latest statement is True — where a
    wildcard tombstone counts as a statement against every altseq at its
    position, so only a LATER altseq row revives the kind.
    """
    alive, dead = set(), set()
    for kind in set(entry["kind"]) | set(entry["wild"]):
        per_alt = entry["kind"].get(kind, {})
        w = entry["wild"].get(kind)
        if per_alt:
            vals = [
                v if (w is None or p > w[0]) else w[1]
                for p, v in per_alt.values()
            ]
        else:
            vals = [w[1]] if w else []
        (alive if any(vals) else dead).add(kind)
    return alive, dead


def manifest_kind_evidence(path=None, max_rows: int = _MANIFEST_TAIL_ROWS) -> dict:
    """(idc,arm,variant) -> {"alive": set, "dead": set, "ag": bool}.

    The kind-aware manifest leg: which kinds have surviving byte evidence,
    which have last-statement loss, and whether any kind-agnostic row
    asserts bytes. check() intersects the paid stage's mutates against
    'alive' — a {state}-only harvest must not mint 'verified' for a cell
    whose paid product (zh) is tombstoned or never sealed."""
    out: dict[tuple, dict] = {}
    for key, entry in _manifest_fold(path, max_rows).items():
        alive, dead = _resolve_kinds(entry)
        ag_seen = bool(entry["alt"])
        out[key] = {"alive": alive, "dead": dead,
                    "ag": any(entry["alt"].values()),
                    "ag_dead": ag_seen and not any(entry["alt"].values())}
    return out


def manifest_tail(path=None, max_rows: int = _MANIFEST_TAIL_ROWS) -> set[tuple]:
    """(idc,arm,variant) set with surviving byte evidence and no dead kind.

    Reads the last ~5000 rows of vault/manifest.jsonl tolerantly (bad lines
    skipped — the iter_jsonl read-side contract). Per §3.10.4 last-row-wins
    is evaluated per altseq AND per kind: a demote kills only its own
    copy's evidence, a tombstone kills only its own kind's. A cell whose
    manifest record shows a dead kind is NOT 'verified' — partial loss is
    §3.6's third state, decided by the missing leg, never silently skipped.
    """
    out: set[tuple] = set()
    for key, ev in manifest_kind_evidence(path, max_rows).items():
        if (ev["ag"] or ev["alive"]) and not ev["dead"]:
            out.add(key)
    return out


# -- vault meta scan (durable verified leg ②) --------------------------------------


def _scan_vault_meta(idc: str, arm: str, variant: str):
    """Durable meta-dir scan for one cell -> (bytes_ok, missing, io_error).

    Delegates iteration+parse+intactness to vault.query — the single meta
    implementation — so the §3.10.4 filename-authoritative credential and
    the physical intactness stat live in exactly one place. vault's
    bytes_ok requires every declared asset present non-empty ON DISK: a
    committed verdict whose bytes vanished is §3.6's third state and
    folds into missing evidence, never a verified skip. A meta whose
    filename claims this cell but whose body is unreadable is broken
    commit-marker evidence — missing-side (spend-refusing), not absent.
    """
    from kernel import vault  # lazy: heavy module; keeps import graph one-way
    try:
        rows = vault.query(idc, _norm(arm), _norm(variant))
    except ValueError:
        return False, False, False  # non-canon idc can never own vault bytes
    except OSError:
        return False, False, True
    bytes_ok = miss = False
    for row in rows:
        if row.get("_parse_error"):
            miss = True
            continue
        verdict = str(row.get("verdict") or row.get("state") or "").lower()
        if verdict in BYTES_OK_VERDICTS:
            if row.get("bytes_ok"):
                bytes_ok = True
            else:
                miss = True
        if verdict in MISSING_VERDICTS:
            miss = True
    return bytes_ok, miss, False


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

    Reads `records` (T_CELL-only terminal history), NOT `cells` — the
    cells projection is masked by queued/started mid-run, which would
    silently empty this bucket right when a rerun is being planned.
    """
    rows = index.conn.execute(
        "SELECT status, cat FROM records r"
        " WHERE r.idc=? AND r.arm=? AND r.variant=?"
        " AND r.rowid IN (SELECT MAX(rowid) FROM records"
        "               WHERE idc=? AND arm=? AND variant=?"
        "               GROUP BY up, stage)",
        (idc, _norm(arm), _norm(variant), idc, _norm(arm), _norm(variant)),
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


def _events_tail_tag() -> str:
    """``st_dev:st_ino`` of the hot tail — the inode identity min_offset
    belongs to. A seal rotates the tail into a segment and recreates it, so
    a snapshot's offset is only comparable while the inode survives."""
    try:
        st = paths.events_path().stat()
    except FileNotFoundError:
        return ""
    return f"{st.st_dev}:{st.st_ino}"


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
        min_tag: str | None = None,
        kind_evidence: dict | None = None,
    ):
        self.index = index
        self.manifest_tail = frozenset(manifest_tail or ())
        self.paid_pool_snap = frozenset(paid_pool_snap or ())
        self.sealed_gen = int(sealed_gen)
        self.min_offset = int(min_offset)
        # inode identity of the file min_offset was measured on — a seal
        # rotates the tail away whole, after which offset comparison alone
        # is meaningless (check_sealed falls back to segment coverage).
        self.min_tag = min_tag
        # key -> {"alive","dead","ag"} per-kind manifest evidence; None for
        # hand-built oracles (kind-blind legacy legs only).
        self.kind_evidence = kind_evidence or {}

    @classmethod
    def snapshot(cls, index, paid_stages=None) -> "DedupOracle":
        """Capture the run-start oracle (§3.10.6 ②).

        sealed_gen/min_offset come from index.sealed_state() — lifted to
        the live fsync'd ledger tail so a snapshot taken before
        tail_ingest catches up reads 'unsealed' instead of trusting a
        behind-watermark projection. manifest_tail parses the last ~5000
        vault manifest rows tolerantly; paid_pool_snap freezes
        index.paid_pool(paid_stages) — PASS the spec's paid stage names,
        else a free stage's ok mints verified evidence for paid cells.
        """
        gen, wm = index.sealed_state()
        kinds = manifest_kind_evidence()
        return cls(
            index,
            manifest_tail={
                k for k, ev in kinds.items()
                if (ev["ag"] or ev["alive"]) and not ev["dead"]
            },
            paid_pool_snap=index.paid_pool(stages=paid_stages),
            sealed_gen=gen,
            min_offset=max(wm, _events_tail_offset()),
            min_tag=_events_tail_tag(),
            kind_evidence=kinds,
        )

    # -- seal gate -----------------------------------------------------------------

    def _sealed_now(self) -> bool:
        """check_sealed with ONE catch-up ingest first.

        Events landing between run-start tail_ingest and snapshot leave
        watermark < min_offset forever — without the catch-up every paid
        cell degrades to 'unsealed' under ordinary ledger traffic. One
        re-ingest consumes what the snapshot already priced in; a writer
        that outruns even the catch-up still reads unsealed (fail-closed).
        """
        if self.index.dirty():
            return False
        if self.index.check_sealed(
                self.sealed_gen, self.min_offset, self.min_tag):
            return True
        try:
            self.index.tail_ingest()
        except Exception:
            pass
        return self.index.check_sealed(
            self.sealed_gen, self.min_offset, self.min_tag)

    def sealed(self) -> bool:
        """Seal predicate as check() evaluates it right now."""
        return self._sealed_now()

    # -- per-cell verdict ------------------------------------------------------------

    def check(self, idc, arm: str = "-", variant: str = "-",
              stage_paid: bool = True, need_kinds=None) -> str:
        """Five-state paid-gate verdict — ORDER IS THE CONTRACT.

        stage_paid marks whether the caller's stage is paid; the oracle's
        evidence is paidness-agnostic (claims and bytes mean the same
        thing either way) — the flag is carried for quote()'s attempted
        bucketing and the caller's §3.8 interpretation.

        need_kinds = the calling stage's declared mutates — the paid
        product kinds. When given, 'verified' requires the manifest's
        per-kind evidence to cover every needed kind (a {state}-only
        harvest must not dedup a cell whose zh is tombstoned or was
        never sealed), and a manifest-dead needed kind vetoes the
        paid_pool/meta legs too. Kind-agnostic rows vouch no named kind
        — ambiguous evidence resolves toward spend, never toward skip.
        """
        idc, arm, variant = str(idc), _norm(arm), _norm(variant)
        key = (idc, arm, variant)

        # 1. unsealed — first, even when durable legs say verified. A stale
        #    index can't be trusted about tombstones; the seal failure is
        #    the alarm that must surface (retriable-terminal upstream).
        if not self._sealed_now():
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
        if self._verified(key, meta_ok, need_kinds):
            return VERIFIED

        # 4. missing — tombstone/quar evidence with no verified leg.
        if meta_missing or self._missing_evidence(idc, arm, variant):
            return MISSING

        # 4.5 release-verified — a lifecycle claim row released with
        #     fate='verified' is durable class evidence the paid commit ran
        #     to terminal and its harvest fired. It sits AFTER missing so
        #     tombstones keep winning for identity keys, BEFORE absent so
        #     a spent cell never re-burns on a byte-evidence gap.
        if self._release_verified(idc, arm, variant):
            return VERIFIED

        # 5. absent — reachable only because the index is sealed.
        return ABSENT

    def _release_verified(self, idc, arm, variant) -> bool:
        """Latest lifecycle claim row for the key is release/fate=verified.

        Reads the sealed index's claims projection — under the seal the
        projection is proven current to min_offset, so this is durable
        class-level evidence, not the advisory live-index read the other
        verified legs ban. A key whose latest lifecycle row is 'acquire'
        (claim still open, or re-opened) is not verified evidence here.
        """
        row = self.index.conn.execute(
            "SELECT op, fate FROM claims"
            " WHERE idc=? AND arm=? AND variant=? AND slot IS NULL"
            " ORDER BY rowid DESC LIMIT 1",
            (idc, arm, variant),
        ).fetchone()
        return bool(
            row and row["op"] == "release" and row["fate"] == "verified"
        )

    def _verified(self, key, meta_ok: bool, need_kinds) -> bool:
        """The verified legs under kind-aware adjudication.

        need_kinds given: manifest must prove every needed kind alive;
        the pool/meta legs then verify only when no needed kind is
        manifest-dead (a paid-ok row or physically-intact meta must not
        resurrect a declared-dead product). need_kinds None: the flat
        manifest_tail set (surviving evidence with no dead kind) plus
        pool/meta vetoed by ANY dead kind — fail-closed partial loss.
        """
        ev = self.kind_evidence.get(key)
        alive = ev["alive"] if ev else set()
        dead = ev["dead"] if ev else set()
        ag_dead = bool(ev and ev["ag_dead"])
        need = {str(k) for k in need_kinds} if need_kinds else None
        if need:
            if need <= alive:
                return True
            pool_meta = key in self.paid_pool_snap or meta_ok
            return pool_meta and not (need & dead) and not ag_dead
        if key in self.manifest_tail:
            return True
        return (key in self.paid_pool_snap or meta_ok) and not dead

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
            "SELECT status, cat FROM records"
            " WHERE idc=? AND arm=? AND variant=?",
            (idc, arm, variant),
        ):
            # records = T_CELL-only terminal history — never masked by a
            # live run's queued/started the way the cells projection is.
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
            idc, arm, variant, paid, need = _cell_spec(c)
            key = (idc, arm, variant)
            res = self.check(idc, arm, variant, stage_paid=paid,
                             need_kinds=need)
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


def _cell_spec(cell) -> tuple[str, str, str, bool, object]:
    """Normalize a plan-cell spec -> (idc, arm, variant, stage_paid,
    need_kinds).

    dict:   {idc|id, arm?, variant?, stage_paid?|paid?, need_kinds?}
    tuple:  (idc,arm) | (idc,arm,variant) | (idc,arm,up,variant,stage,...)
    """
    if isinstance(cell, dict):
        idc = cell.get("idc")
        if not isinstance(idc, str) or not idc:
            idc = _canon(cell.get("id")) or cell.get("id")
        paid = cell.get("stage_paid", cell.get("paid", True))
        return (str(idc), _norm(cell.get("arm")),
                _norm(cell.get("variant")), bool(paid),
                cell.get("need_kinds"))
    seq = list(cell)
    idc = str(seq[0])
    arm = _norm(seq[1] if len(seq) > 1 else "-")
    if len(seq) >= 4:
        variant = _norm(seq[3])  # full cell key: (idc,arm,up,variant,stage,...)
    else:
        variant = _norm(seq[2] if len(seq) > 2 else "-")
    return idc, arm, variant, True, None
