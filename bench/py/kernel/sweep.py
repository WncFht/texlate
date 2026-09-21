"""Sweep — the reaper, with an owner (design §2.4, §3.10.1, §3.5, §3.10.4).

``bench sweep`` runs a light pass at the start of every write command plus
the full pass on its hourly timer. Duties:

1. **Zombie runs** (§3.10.1): heartbeat stale (>10min) AND run.lock NB-free
   → per-cell ``cell.lock`` NB recheck — a held cell lock means a LIVE cell
   and is never reaped — then emit ``lost`` terminal events for unfinished
   cells, reap their claim leases (op='reap' audit row, which also clears
   the paid_slots projection = the "paid_slot release"), and note it.
2. **Pending vault metas** older than the pending timeout (§3.5): promote
   via ``vault.promote`` — verdict computed from the index (clean evidence
   → primary, failure-only → quar, none → alt) — or tombstone when the
   committed bytes are not intact (abort evidence). Pending metas owned by
   a still-active run are left to that run's own reconcile.
3. **Orphan bytes** (§3.10.4, §3.10.9): vault meta-less dirs and lake dirs
   with no events → adopt to quarantine + note. Meta-less dirs get the
   hardened predicate — sibling metas, manifest rows, and a minimum age
   gate adoption; anything failing a leg is REPORTED, never deleted.
   Deletion is never a sweep verb.
4. **Harvest-pending queue** (§2.4): index DONE cells that touched the
   vault domain (claim or vault-asset events) but have no intact vault
   bytes → first-class alarm list + warn note. "done but bytes gone" is a
   queue, not an invisible hole.
5. **Permanently-failed cells** past age → tombstone events; the error
   rows stay on the books.

Concurrency: the whole sweep runs under a single NB flock
(``locks/sweep.lock``) inside a ``kernel_active_hold`` SH hold — a second
concurrent sweep returns early, and ``bench doctor --switch-ok`` correctly
reports the kernel busy while a sweep is in flight. The reaper is built
from nonblocking probes only (lock-order discipline, §3.10.6): it never
blocking-acquires a cell/claim lock, so a live worker is always proof of
life, never a deadlock.

Thresholds are module constants so callers/tests can tune them:

    ZOMBIE_AGE_S            heartbeat staleness (§3.10.1: 15s touch, >10min)
    PENDING_META_AGE_S      pending meta grace before sweep reconciles
    ORPHAN_AGE_S            meta-less dirs younger than this may be an
                            in-flight commit — report only
    FAIL_TOMBSTONE_AGE_S    permanently-failed cells past this age
"""
from __future__ import annotations

import time
from pathlib import Path

from kernel import claims, dedup, events, index, lake, ledger, locks, paths
from kernel import runs, vault
from kernel.idnorm import idc_from_safe, safe_id

__all__ = [
    "FAIL_TOMBSTONE_AGE_S",
    "ORPHAN_AGE_S",
    "PENDING_META_AGE_S",
    "ZOMBIE_AGE_S",
    "sweep",
]

ZOMBIE_AGE_S = 600.0                 # §3.10.1: heartbeat stops >10min
PENDING_META_AGE_S = 15 * 60.0       # older than the zombie window
ORPHAN_AGE_S = 3600.0                # meta-less dir commit grace
FAIL_TOMBSTONE_AGE_S = 7 * 86400.0   # permafail → tombstone age

_CLEAN_STATUSES = frozenset({"ok", "partial", "clean"})
_FAIL_STATUSES = frozenset({"fail", "fault", "dirty_pdf", "reject"})
_VAULT_KINDS = frozenset({"zh", "splice", "state"})


def _sweep_lock_path() -> Path:
    return paths.locks_dir() / "sweep.lock"


def _note(text: str, level: str = "info") -> None:
    """Emit a global sweep note (run='sweep', seq=None → runless event with
    an index-assigned negative seq). Run-scoped notes go through
    runs._emit_note so they dual-write into the run's shard."""
    ev = events.make_event(
        events.T_NOTE, run="sweep", seq=None, text=text, level=level,
    )
    ledger.emit(ev)


def _open_index() -> index.Index | None:
    """Open the derived index when it exists; never create it as a side
    effect of sweeping (read-side purity — a fresh root simply has no
    projections yet)."""
    if not paths.index_path().exists():
        return None
    try:
        return index.Index()
    except Exception:
        return None


# --- duty 1: zombies ---------------------------------------------------------------

def _shard_state(rdir: Path) -> dict:
    """One tolerant pass over a run's events.jsonl shard.

    Returns {queued, started, terminal, claims} keyed dicts; claims maps
    (idc,arm,variant) -> the LAST claim event in shard order."""
    queued: dict[tuple, dict] = {}
    started: dict[tuple, dict] = {}
    terminal: dict[tuple, dict] = {}
    claim_ops: dict[tuple, dict] = {}
    shard = rdir / "events.jsonl"
    if shard.exists():
        for _ln, ev, _raw in events.iter_jsonl(shard):
            if not isinstance(ev, dict):
                continue
            t = ev.get("type")
            if t == events.T_CELL_QUEUED:
                queued[runs._cell_key(ev)] = ev
            elif t == events.T_CELL_STARTED:
                started[runs._cell_key(ev)] = ev
            elif events.is_terminal_cell(ev):
                terminal[runs._cell_key(ev)] = ev
            elif t == events.T_CLAIM:
                ckey = (
                    str(ev.get("idc") or ev.get("id")),
                    str(ev.get("arm") or "-"),
                    str(ev.get("variant") or "-"),
                )
                claim_ops[ckey] = ev
    return {
        "queued": queued, "started": started,
        "terminal": terminal, "claims": claim_ops,
    }


def _emit_lost(rd: runs.RunDir, ev0: dict) -> None:
    """Emit the kernel 'lost' terminal for one unfinished cell (§3.10.1)."""
    ev = events.make_event(
        events.T_CELL, run=rd.run, seq=runs._kernel_seq(rd),
        id=ev0.get("id") or ev0.get("idc"), idc=ev0.get("idc") or ev0.get("id"),
        arm=ev0.get("arm"), up=ev0.get("up"), variant=ev0.get("variant"),
        stage=ev0.get("stage"), status="lost",
        errors=[{"cat": "zombie",
                 "msg": "run heartbeat stale + run.lock free; cell lock NB-free"}],
    )
    ledger.emit(ev, run_dir=rd.path)


def _emit_claim_reap(rd: runs.RunDir | None, run: str, idc: str,
                     arm: str, variant: str, slot=None, ev_id=None) -> None:
    """Emit the op='reap' claim audit row; the slot field clears the
    paid_slots projection (the ledger-side 'paid_slot release')."""
    seq = runs._kernel_seq(rd) if rd is not None else None
    ev = events.make_event(
        events.T_CLAIM, run=run, seq=seq,
        id=ev_id or idc, idc=idc, arm=arm, variant=variant,
        op="reap", slot=slot,
    )
    ledger.emit(ev, run_dir=rd.path if rd is not None else None)


def _reap_zombie(rd: runs.RunDir, report: dict) -> None:
    """Reap one zombie run: 'lost' terminals + claim reaps + note."""
    st = _shard_state(rd.path)
    unfinished = {
        k: ev for k, ev in {**st["queued"], **st["started"]}.items()
        if k not in st["terminal"]
    }
    reaped, alive = [], []
    for key, ev0 in sorted(unfinished.items(), key=lambda kv: repr(kv[0])):
        idc = key[0]
        sid = safe_id(idc)
        # §3.10.1: per-cell cell.lock NB recheck — a held lock is a LIVE
        # cell (split-brain: run.lock died but a detached worker kept the
        # cell lock). Locked = alive, never reaped.
        if not locks.lock_free(rd.cell_lock_path(sid)):
            alive.append(key)
            continue
        _emit_lost(rd, ev0)
        reaped.append(key)
    claims_reaped = []
    for (idc, arm, variant), cev in sorted(
            st["claims"].items(), key=lambda kv: repr(kv[0])):
        if cev.get("op") != "acquire":
            continue
        if not locks.lock_free(claims.claim_lock_path(idc, arm, variant)):
            continue  # live claimant — never reap
        _emit_claim_reap(
            rd, rd.run, idc, arm, variant,
            slot=cev.get("slot"), ev_id=cev.get("id"))
        claims_reaped.append((idc, arm, variant))
        report["reaped_claims"].append(
            {"idc": idc, "arm": arm, "variant": variant, "run": rd.run})
    entry = {"run": rd.run, "lost_cells": len(reaped),
             "live_cells": len(alive), "claims_reaped": len(claims_reaped)}
    report["zombies"].append(entry)
    runs._emit_note(
        rd,
        f"zombie run {rd.run}: {len(reaped)} cells lost, "
        f"{len(alive)} live-locked cells skipped, "
        f"{len(claims_reaped)} claims reaped",
        level="warn")


def _sweep_zombies(report: dict) -> None:
    base = paths.runs_dir()
    if not base.is_dir():
        return
    for rdir in sorted(base.glob("*/*/*")):
        if not rdir.is_dir():
            continue
        age = locks.heartbeat_age(rdir / "heartbeat")
        stale = age is None or age >= ZOMBIE_AGE_S
        if not stale:
            continue
        if not locks.lock_free(rdir / ".lock"):
            continue  # lock held — alive regardless of heartbeat
        kind, date, slug = rdir.relative_to(base).parts
        rd = runs.load_run(kind, date, slug)
        if rd.run_seq == 0:
            # Half-created dir (crash between mkdir and mint): no
            # registration, no shard — note it, nothing to reap.
            _note(f"unregistered run dir {rdir} (no run_registered event)",
                  level="warn")
            report["errors"].append(f"unregistered run dir: {rdir}")
            continue
        _reap_zombie(rd, report)


def _sweep_stale_claims(idx: index.Index | None, report: dict) -> None:
    """Reap claim leases whose lock is free while the index still shows an
    open acquire — covers dead claimants whose run dirs are gone entirely.

    When the claiming run's shard exists it is the authority: an index that
    lags a release must not produce a spurious reap, so shard-visible
    releases veto the reap.
    """
    if idx is None:
        return
    for idc, arm, variant in sorted(idx.active_claims()):
        lpath = claims.claim_lock_path(idc, arm, variant)
        if not locks.lock_free(lpath):
            continue  # live holder
        row = idx.conn.execute(
            "SELECT run, slot FROM claims"
            " WHERE idc=? AND arm=? AND variant=?"
            " ORDER BY rowid DESC LIMIT 1",
            (idc, arm, variant),
        ).fetchone()
        run = row["run"] if row else "sweep"
        slot = row["slot"] if row else None
        rd = None
        if isinstance(run, str) and run.count("/") == 2:
            try:
                rd = runs.load_run(*run.split("/"))
            except FileNotFoundError:
                rd = None
        if rd is not None:
            st = _shard_state(rd.path)
            last = st["claims"].get((idc, arm, variant))
            if last is not None and last.get("op") != "acquire":
                continue  # shard says released — index is just behind
        try:
            _emit_claim_reap(rd, run, idc, arm, variant, slot=slot)
            report["reaped_claims"].append(
                {"idc": idc, "arm": arm, "variant": variant, "run": run})
        except events.EventError as e:
            report["errors"].append(f"claim reap {idc}/{arm}/{variant}: {e}")


# --- duty 2: pending metas ------------------------------------------------------------

def _verdict_for(idx: index.Index | None, idc: str, arm: str,
                 variant: str) -> tuple[str, str]:
    """(zone, verdict) for a pending meta from index cell evidence (§3.5
    cross-run pick_final, last-clean-wins):
    any clean-ish terminal → primary; failure-only → quar; no evidence →
    alt (bytes stay dedup-visible as a non-primary copy)."""
    if idx is None:
        return "primary", "alt"
    rows = idx.conn.execute(
        "SELECT status FROM cells WHERE idc=? AND arm=? AND variant=?",
        (idc, arm, variant),
    ).fetchall()
    statuses = {r["status"] for r in rows}
    if statuses & _CLEAN_STATUSES:
        return "primary", "primary"
    if statuses & _FAIL_STATUSES:
        return "quar", "quar"
    return "primary", "alt"


def _sweep_pending_metas(idx: index.Index | None, active: set[str],
                         report: dict, now: float) -> None:
    for meta in vault.pending_metas():
        ts = meta.get("ts")
        age = now - ts if isinstance(ts, (int, float)) else float("inf")
        if age < PENDING_META_AGE_S:
            continue
        src_run = meta.get("source_run") or ""
        if src_run in active:
            continue  # a live run's own reconcile owns its pending metas
        idc, arm = meta["idc"], meta["arm"]
        variant, altseq = meta["variant"], meta["altseq"]
        try:
            if not vault.bytes_ok(idc, arm, variant, altseq):
                # abort evidence: commit landed but declared bytes are not
                # intact → the copy is lost, tombstone it (§3.1 first-class).
                for k in meta.get("kinds") or ["zh"]:
                    vault.tombstone(
                        idc, arm, variant, k, reason="pending_abort",
                        lost_run=src_run)
                report["tombstoned"].append({
                    "idc": idc, "arm": arm, "variant": variant,
                    "reason": "pending_abort"})
                _note(
                    f"pending meta {idc}.{arm}@{variant}.{altseq} bytes "
                    f"incomplete — tombstoned (abort evidence)",
                    level="warn")
                continue
            zone, verdict = _verdict_for(idx, idc, arm, variant)
            vault.promote(idc, arm, variant, altseq, zone, verdict,
                          source_run="sweep")
            report["promoted"].append({
                "idc": idc, "arm": arm, "variant": variant,
                "altseq": altseq, "verdict": verdict, "zone": zone})
        except (vault.VaultError, ValueError, OSError) as e:
            report["errors"].append(
                f"pending meta {idc}.{arm}@{variant}.{altseq}: {e}")


# --- duty 3: orphan bytes ---------------------------------------------------------------

def _manifest_mentions(sid_key: str, rows: list[dict]) -> bool:
    """True when some manifest row references the leaf path ``sid/key``."""
    for row in rows:
        path = row.get("path")
        if isinstance(path, str) and path.endswith(sid_key):
            return True
        dirs = row.get("dirs")
        if isinstance(dirs, dict):
            for v in dirs.values():
                if isinstance(v, str) and v.endswith(sid_key):
                    return True
    return False


def _sweep_vault_orphans(report: dict, now: float) -> None:
    mani = None
    for leaf in vault.find_meta_less_dirs():
        try:
            rel = leaf.relative_to(paths.vault_dir())
        except ValueError:
            continue
        parts = rel.parts
        try:
            if parts[0] == "quar":
                kind, sid, key = parts[1], parts[2], parts[3]
            else:
                kind, sid, key = parts[0], parts[1], parts[2]
            arm, variant, altseq = vault.parse_dir_key(key)
        except (IndexError, ValueError):
            report["meta_less"].append(
                {"path": str(leaf), "reason": "unparseable"})
            continue
        idc = idc_from_safe(sid)
        entry = {"path": str(leaf), "idc": idc, "arm": arm,
                 "variant": variant, "altseq": altseq, "kind": kind}
        # Hardened predicate (§3.10.4): meta-less ≠ orphan.
        try:
            siblings = vault.query(idc, arm, variant)
        except ValueError:
            siblings = []
        if siblings:
            entry["reason"] = "sibling_meta"
            report["meta_less"].append(entry)
            continue
        try:
            age = now - leaf.stat().st_mtime
        except OSError:
            entry["reason"] = "stat_failed"
            report["meta_less"].append(entry)
            continue
        if age < ORPHAN_AGE_S:
            entry["reason"] = "young"
            report["meta_less"].append(entry)
            continue
        if mani is None:
            mani = vault.manifest_rows()
        if _manifest_mentions(f"{sid}/{key}", mani):
            entry["reason"] = "manifested"
            report["meta_less"].append(entry)
            continue
        try:
            dst = vault.adopt(leaf, idc, arm, variant,
                              reason="meta_less_orphan", kind=kind)
            entry["adopted_to"] = str(dst)
            report["adopted"].append(entry)
        except (vault.VaultError, ValueError, OSError) as e:
            entry["reason"] = f"adopt_failed: {e}"
            report["meta_less"].append(entry)


def _sweep_lake_orphans(report: dict) -> None:
    """Lake cell dirs with no catalog row and no lake_cell event → adopt
    into the catalog (state 'skeleton', manifested:false — first eviction
    candidates), never into the vault: lake bytes are free/rebuildable."""
    corpus = paths.lake_corpus_dir()
    if not corpus.is_dir():
        return
    cat = lake.LakeCatalog.load()
    rows = cat.rows()
    ledger_idcs: set[str] = set()
    for _src, _off, ev in ledger.iter_all_events():
        if isinstance(ev, dict) and ev.get("type") == events.T_LAKE_CELL:
            idc = ev.get("idc")
            if isinstance(idc, str):
                ledger_idcs.add(idc)
    for source_dir in sorted(corpus.iterdir()):
        if not source_dir.is_dir() or source_dir.name.startswith("."):
            continue
        for cell in sorted(source_dir.iterdir()):
            if not cell.is_dir() or cell.name.startswith("."):
                continue
            idc = idc_from_safe(cell.name)
            if idc in rows or idc in ledger_idcs:
                continue
            cat.set(idc, "skeleton", source=source_dir.name,
                    manifested=False, orphan=True)
            report["lake_orphans"].append(
                {"path": str(cell), "idc": idc})
    if report["lake_orphans"]:
        _note(f"{len(report['lake_orphans'])} lake orphan cell dirs "
              "adopted into catalog (manifested:false)", level="warn")


# --- duty 4: harvest-pending ---------------------------------------------------------

def _sweep_harvest_pending(idx: index.Index | None, report: dict) -> None:
    """DONE cells with vault intent but no intact bytes → alarm queue."""
    if idx is None:
        return
    intent: set[tuple] = set()
    for r in idx.conn.execute(
            "SELECT DISTINCT idc, arm, variant FROM claims WHERE op='acquire'"):
        intent.add((r["idc"], r["arm"], r["variant"]))
    marks = ",".join("?" for _ in _VAULT_KINDS)
    for r in idx.conn.execute(
            f"SELECT DISTINCT idc, arm, variant FROM assets"
            f" WHERE kind IN ({marks})", tuple(sorted(_VAULT_KINDS))):
        intent.add((r["idc"], r["arm"], r["variant"]))
    if not intent:
        return
    done_keys: dict[tuple, list] = {}
    for r in idx.conn.execute(
            "SELECT idc, arm, variant, stage, status FROM cells"
            " WHERE status IN ('ok','partial','clean')"):
        done_keys.setdefault((r["idc"], r["arm"], r["variant"]),
                             []).append(r["stage"])
    tail = dedup.manifest_tail()
    for key in sorted(intent):
        if key not in done_keys:
            continue  # no terminal-clean evidence — nothing owed yet
        idc, arm, variant = key
        try:
            if vault.bytes_ok(idc, arm, variant):
                continue
        except ValueError:
            pass  # odd id — fall through to the alarm
        if key in tail:
            continue  # durable manifest leg vouches for the bytes
        if dedup.tombstoned(idx, idc, arm, variant):
            continue  # loss is already registered
        report["harvest_pending"].append(
            {"idc": idc, "arm": arm, "variant": variant,
             "stages": sorted(done_keys[key])})
    if report["harvest_pending"]:
        _note(f"harvest-pending: {len(report['harvest_pending'])} DONE "
              "cells have no intact vault bytes (done but bytes gone)",
              level="warn")


# --- duty 5: permafail tombstones -----------------------------------------------------

def _sweep_permafail(idx: index.Index | None, report: dict,
                     now: float) -> None:
    if idx is None:
        return
    rows = idx.conn.execute(
        "SELECT idc, arm, variant, status, cat, ts, last_run FROM cells"
    ).fetchall()
    by_key: dict[tuple, list] = {}
    for r in rows:
        by_key.setdefault((r["idc"], r["arm"], r["variant"]), []).append(r)
    pool = idx.paid_pool()
    for key, rs in sorted(by_key.items()):
        if key in pool:
            continue  # a later success already redeemed the cell
        failing = [
            r for r in rs
            if r["status"] in dedup.ATTEMPTED_UNPAID
            and r["cat"] != "regen_gate"  # gate artifact, not an attempt
        ]
        if not failing:
            continue
        newest = max(
            (r["ts"] for r in rs if isinstance(r["ts"], (int, float))),
            default=0.0,
        )
        if now - newest < FAIL_TOMBSTONE_AGE_S:
            continue
        idc, arm, variant = key
        if dedup.tombstoned(idx, idc, arm, variant):
            continue  # already registered
        status = sorted({r["status"] for r in failing})
        lost_run = failing[-1]["last_run"] or ""
        try:
            vault.tombstone(idc, arm, variant, "cell",
                            reason=f"permafail:{','.join(status)}",
                            lost_run=lost_run)
            report["tombstoned"].append({
                "idc": idc, "arm": arm, "variant": variant,
                "reason": f"permafail:{','.join(status)}"})
        except (vault.VaultError, ValueError) as e:
            report["errors"].append(f"permafail tombstone {key}: {e}")


# --- entry point ----------------------------------------------------------------------

def sweep(light: bool = False) -> dict:
    """Run the reaper. light=True is the fast auto-pass at write-command
    start: zombies + stale claims only (the duties that keep claim/slot
    truth before a new run pays). The full pass adds pending-meta
    reconcile, orphan adoption, harvest-pending and permafail tombstones.
    """
    report: dict = {
        "light": bool(light),
        "zombies": [], "reaped_claims": [], "promoted": [],
        "adopted": [], "harvest_pending": [], "tombstoned": [],
        "meta_less": [], "lake_orphans": [], "errors": [],
    }
    try:
        with locks.flock(_sweep_lock_path(), exclusive=True, blocking=False):
            with locks.kernel_active_hold():
                now = time.time()
                idx = _open_index()
                try:
                    _sweep_zombies(report)
                    _sweep_stale_claims(idx, report)
                    if light:
                        return report
                    active = {
                        a["run"] for a in runs.active_runs()
                    }
                    _sweep_pending_metas(idx, active, report, now)
                    _sweep_vault_orphans(report, now)
                    _sweep_lake_orphans(report)
                    _sweep_harvest_pending(idx, report)
                    _sweep_permafail(idx, report, now)
                finally:
                    if idx is not None:
                        idx.close()
    except locks.WouldBlock:
        report["skipped"] = "another sweep holds locks/sweep.lock"
    return report
