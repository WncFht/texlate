"""Doctor + fsck — the assert surface (design §1, §3.10.5, §3.10.6, §3.10.9).

``bench doctor`` is the read-side health oracle: every check is
independent, every failure is reported (never silently fixed), and the
only write verbs ``fix=True`` allows are the safe ones — reaping
lock-free stale claims and catching the derived index up via tail_ingest.
Nothing here ever deletes bytes: stray dirs are REPORTED with an adopt
offer (§3.10.9 "报告+收编 绝不删除"), meta-less vault dirs are reported
per the hardened predicate (§3.10.4).

Checks:

    layout          ensure_layout artifacts present: zone dirs, both
                    sentinels, immortal lock files, seqfile parses, and
                    vault↔staging same-volume (§1 hard constraint)
    root_location   warn-only: $TEXLATE_BENCH_ROOT inside a git checkout
                    is a §1 violation but can never gate (test roots live
                    under repo tmp/ by design)
    stray_dirs      scan the repo's bench/ for runtime dirs that must not
                    live in a checkout (results*, work_*, zh-store*,
                    archive-*, zone names) → REPORT + adopt offer, NEVER
                    delete. Repo bench dir: $TEXLATE_REPO_BENCH override,
                    else derived from this file's location
    lock_invariants immortal lock files exist (ledger/.lock, vault/.lock,
                    every run .lock); claim leases held-by-dead (index
                    'acquire' vs free flock) are reported / fix-reaped
    ledger          events.jsonl parses (bad lines counted);
                    seqfile == max(events.run_seq) == max(runs.jsonl) per
                    §3.10.5 — the seqfile stores the LAST minted run_seq
                    (high-water), so all three agree on a clean root;
                    index ahead of the ledger = corruption, index behind
                    = staleness detail only
    index           .index-dirty absent (fail-closed §3.10.6 ③);
                    watermark-vs-ledger lag, >24h staleness and non-zero
                    dedup_skip are surfaced as warnings (the dedup
                    oracle's own seal gate is the hard boundary)
    paid            §3.10.6 ⑤ reconciliation — claim-gated paid-ok cells
                    vs manifest bytes_ok keys vs the index paid_pool leg;
                    divergence = the bypass alarm → fail
    capacity        ledger hot tail <512MB hard gate; lake cap watermark
                    and fs free floor as warnings
    queues          quarantine/adjudication row counts surfaced
    switch_ok       only with switch_ok=True: the §3.10.9 drain gate —
                    kernel_idle() AND no active runs AND no PAUSE AND no
                    live lane-* tmp writers AND no live errsweep worktree.
                    detail is the single line 'SWITCH-OK' when clear, so
                    scripts can grep for it

``fsck(defer_edges=False)`` is the deeper pass: vault verify('stat'),
lake catalog-vs-dirs reconciliation, claims-vs-locks, and dangling
from_run edges in plan.json needs (skipped with defer_edges).
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from kernel import claims, dedup, events, index, lake, ledger, locks, paths
from kernel import runs, vault
from kernel.idnorm import idc_from_safe

__all__ = [
    "LEDGER_HOT_TAIL_MAX",
    "doctor",
    "fsck",
]

LEDGER_HOT_TAIL_MAX = 512 * 1024 * 1024   # §3.10.1 hot-tail hard gate
_FS_FLOOR_GB = 27.0                        # §3.10.1 fs_avail reserve
_LANE_FRESH_S = 600.0                      # lane/errsweep liveness window

_PAID_OK = frozenset({"ok", "partial"})

# bench/ entries that are runtime data dirs — they must never live inside
# the checkout (§1 "仓库内只留" list).
_STRAY_PREFIXES = ("results", "work_", "zh-store", "archive-", "daily")
_STRAY_NAMES = frozenset({
    "runs", "vault", "lake", "ledger", "locks", "objects", "tmp",
    ".staging", "state", "cache", "records", "corpus_daily", "out",
    "build", "quar", "meta",
})
# Tracked, known-good bench/ dirs — anything else directory-shaped is
# listed as 'review' in the detail without failing the check.
_BENCH_ALLOW = frozenset({
    "py", "corpus", "fixtures", "nominations", "specs", "frame", "ts",
    "docs", "data", "report", "__pycache__",
})


def _repo_root() -> Path:
    """The git checkout containing this kernel — bench/py/kernel/doctor.py."""
    return Path(__file__).resolve().parents[3]


def _repo_bench_dir() -> Path:
    """The repo's bench/ dir for the stray scan — $TEXLATE_REPO_BENCH wins
    so tests and foreign checkouts can point the check elsewhere."""
    override = os.environ.get("TEXLATE_REPO_BENCH")
    if override:
        return Path(override).expanduser().resolve()
    return _repo_root() / "bench"


def _check(checks: list, name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})


def _open_index() -> index.Index | None:
    if not paths.index_path().exists():
        return None
    try:
        return index.Index()
    except Exception:
        return None


# --- individual checks ---------------------------------------------------------------

def _check_layout(checks: list) -> None:
    problems = []
    r = paths.root()
    if not r.is_dir():
        _check(checks, "layout", False, f"root missing: {r}")
        return
    for d in (paths.ledger_dir(), paths.runs_dir(), paths.vault_dir(),
              paths.lake_dir(), paths.locks_dir()):
        if not d.is_dir():
            problems.append(f"missing zone dir {d}")
    for s in (paths.ledger_sentinel_path(), paths.vault_sentinel_path()):
        if not s.exists():
            problems.append(f"missing sentinel {s}")
    for f in (paths.ledger_lock_path(), paths.vault_lock_path(),
              paths.events_path(), paths.runs_jsonl_path()):
        if not f.exists():
            problems.append(f"missing {f}")
    try:
        int(paths.seqfile_path().read_text().strip() or "0")
    except (OSError, ValueError) as e:
        problems.append(f"seqfile unreadable: {e}")
    try:
        paths.assert_vault_same_volume()
    except (RuntimeError, OSError) as e:
        problems.append(str(e))
    _check(checks, "layout", not problems,
           "; ".join(problems) if problems else "zones + sentinels + same-volume ok")


def _check_root_location(checks: list) -> None:
    """Warn-only — a root inside a git checkout is a §1 violation but can
    never gate (test roots legitimately live under repo tmp/)."""
    r = paths.root()
    hit = None
    for p in (r, *r.parents):
        if (p / ".git").exists():
            hit = p
            break
    _check(checks, "root_location", True,
           "ok" if hit is None else
           f"warn: root {r} is inside git checkout {hit} — "
           "§1 requires the data plane outside any checkout")


def _check_stray_dirs(checks: list) -> None:
    bench = _repo_bench_dir()
    if not bench.is_dir():
        _check(checks, "stray_dirs", True,
               f"repo bench dir absent ({bench}) — nothing to scan")
        return
    stray, review = [], []
    for entry in sorted(bench.iterdir()):
        if not entry.is_dir() or entry.name.startswith("__"):
            continue
        name = entry.name
        hit = (
            name in _STRAY_NAMES
            or any(name.startswith(p) for p in _STRAY_PREFIXES)
        )
        if hit:
            stray.append(name)
        elif name not in _BENCH_ALLOW:
            review.append(name)
    detail = (
        f"stray runtime dirs in {bench}: {stray} — report+adopt via "
        f"'bench vault adopt', NEVER delete (§3.10.9)"
        if stray else "no stray dirs"
    )
    if review:
        detail += f"; unrecognized dirs to review: {review}"
    _check(checks, "stray_dirs", not stray, detail)


def _stale_claims(idx: index.Index | None) -> list[tuple]:
    """(idc,arm,variant) the index shows acquire-open while the flock is
    free — held-by-dead leases awaiting a reap audit row."""
    if idx is None:
        return []
    out = []
    for idc, arm, variant in sorted(idx.active_claims()):
        if locks.lock_free(claims.claim_lock_path(idc, arm, variant)):
            out.append((idc, arm, variant))
    return out


def _check_lock_invariants(checks: list, idx: index.Index | None) -> list:
    problems = []
    for f in (paths.ledger_lock_path(), paths.vault_lock_path()):
        if not f.exists():
            problems.append(f"immortal lock file missing: {f}")
    base = paths.runs_dir()
    if base.is_dir():
        for rdir in sorted(base.glob("*/*/*")):
            if rdir.is_dir() and not (rdir / ".lock").exists():
                problems.append(f"run .lock unlinked: {rdir}")
    stale = _stale_claims(idx)
    if stale:
        problems.append(f"{len(stale)} claim leases held-by-dead: "
                        f"{[f'{i}.{a}@{v}' for i, a, v in stale][:5]}")
    _check(checks, "lock_invariants", not problems,
           "; ".join(problems) if problems else "locks immortal + no stale claims")
    return stale


def _max_run_seq_events() -> int:
    """Max run_seq over run_registered events (sealed + hot tail)."""
    best = 0
    for _src, _off, ev in ledger.iter_all_events():
        if isinstance(ev, dict) and ev.get("type") == events.T_RUN_REGISTERED:
            seq = ev.get("run_seq")
            if isinstance(seq, int) and not isinstance(seq, bool):
                best = max(best, seq)
    return best


def _max_run_seq_runs_jsonl() -> tuple[int, int]:
    """(max run_seq, bad-line count) over ledger/runs.jsonl."""
    best, bad = 0, 0
    for _ln, row, _raw in events.iter_jsonl(paths.runs_jsonl_path()):
        if not isinstance(row, dict):
            bad += 1
            continue
        seq = row.get("run_seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            best = max(best, seq)
    return best, bad


def _shard_dirty_runs() -> list[str]:
    """Run dirs carrying a .shard-dirty flag — a shard write failed after
    the hot tail committed, so that run's mirror is incomplete until the
    run dir is rebuilt (the ledger hot tail itself is authoritative and
    unaffected)."""
    base = paths.runs_dir()
    if not base.is_dir():
        return []
    out = []
    for rdir in sorted(base.glob("*/*/*")):
        if rdir.is_dir() and (rdir / ".shard-dirty").exists():
            rel = rdir.relative_to(base)
            out.append("/".join(rel.parts))
    return out


def _check_ledger(checks: list, idx: index.Index | None) -> None:
    problems = []
    bad = 0
    ep = paths.events_path()
    if ep.exists():
        for _ln, ev, _raw in events.iter_jsonl(ep):
            if ev is None:
                bad += 1
    if bad:
        problems.append(f"{bad} unparseable lines in events.jsonl "
                        "(quarantine material)")
    dirty_shards = _shard_dirty_runs()
    if dirty_shards:
        problems.append(
            f"{len(dirty_shards)} run dir(s) flagged .shard-dirty — "
            f"shard mirror incomplete (rebuild the run): "
            f"{dirty_shards[:5]}")
    try:
        seq_val = int(paths.seqfile_path().read_text().strip() or "0")
    except (OSError, ValueError) as e:
        _check(checks, "ledger", False,
               f"seqfile corrupt: {e}; {bad} bad lines")
        return
    ev_max = _max_run_seq_events()
    rj_max, rj_bad = _max_run_seq_runs_jsonl()
    if rj_bad:
        problems.append(f"{rj_bad} unparseable lines in runs.jsonl")
    # §3.10.5: seqfile is the mint high-water — it stores the LAST minted
    # run_seq, so a consistent root has seqfile == events max == runs max
    # (all zero on a fresh root).
    if not (seq_val == ev_max == rj_max):
        problems.append(
            f"run_seq divergence: seqfile={seq_val} events.max={ev_max} "
            f"runs.jsonl.max={rj_max} (§3.10.5 mint invariant)")
    idx_max = None
    if idx is not None:
        idx_max = idx.conn.execute(
            "SELECT COALESCE(MAX(run_seq),0) AS m FROM runs"
        ).fetchone()["m"]
        if idx_max > ev_max:
            problems.append(
                f"index runs.max={idx_max} AHEAD of ledger {ev_max} — "
                "projection corruption")
    detail = "; ".join(problems) if problems else (
        f"events parses clean; seqfile=events=runs.jsonl at {seq_val}")
    if idx_max is not None:
        detail += f"; index runs.max={idx_max}"
    _check(checks, "ledger", not problems, detail)


def _check_index(checks: list, idx: index.Index | None) -> None:
    if idx is None:
        _check(checks, "index", True, "index.sqlite absent — no ingest yet")
        return
    warnings = []
    dirty = idx.dirty()
    gen, wm = idx.sealed_state()
    ledger_wm = ledger.watermark_offset()
    if wm < ledger_wm:
        warnings.append(
            f"index watermark {wm} behind ledger tail {ledger_wm} "
            f"({ledger_wm - wm}B uningested — run tail_ingest)")
    try:
        age = time.time() - paths.index_path().stat().st_mtime
        if age > 86400:
            warnings.append(f"index file stale ({age / 3600:.1f}h old)")
    except OSError:
        pass
    skips = idx.dedup_skip_count()
    if skips:
        warnings.append(
            f"dedup_skip={skips} non-zero outside replay window (§3.10.5)")
    ok = not dirty
    detail = "fail: .index-dirty present (§3.10.6 ③)" if dirty else \
        f"sealed_gen={gen} watermark={wm}"
    if warnings:
        detail += "; warn: " + "; ".join(warnings)
    _check(checks, "index", ok, detail)


def _scan_paid_evidence() -> tuple[set, set]:
    """Ledger-scan legs of the §3.10.6 ⑤ reconciliation.

    Returns (claimed_keys, paid_ok_keys): (idc,arm,variant) tuples that
    ever acquire-claimed, and those with a terminal ok|partial cell event.
    import_src rows are excluded — imported history legitimately predates
    the claim machinery."""
    claimed: set = set()
    paid_ok: set = set()
    for _src, _off, ev in ledger.iter_all_events():
        if not isinstance(ev, dict) or ev.get("import_src"):
            continue
        t = ev.get("type")
        if t == events.T_CLAIM and ev.get("op") == "acquire":
            claimed.add((str(ev.get("idc") or ev.get("id")),
                         str(ev.get("arm")), str(ev.get("variant"))))
        elif events.is_terminal_cell(ev) and ev.get("status") in _PAID_OK:
            paid_ok.add((str(ev.get("idc") or ev.get("id")),
                         str(ev.get("arm")), str(ev.get("variant"))))
    return claimed, paid_ok


def _manifest_paid_keys() -> set:
    """Manifest-tail keys asserting bytes, minus adopt/tombstone ops —
    adopted orphans are bytes nobody paid for, so they are not pool
    members (the §3.10.6 reconciliation is about the PAID pool only)."""
    out = set()
    for raw in dedup._read_tail_lines(paths.vault_manifest_path(),
                                      dedup._MANIFEST_TAIL_ROWS):
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        if row.get("op") in ("adopt", "tombstone"):
            continue
        key = dedup._row_key(row)
        if key is None:
            continue
        if dedup._manifest_bytes_value(row) is True:
            out.add(key)
    return out


def _check_paid(checks: list, idx: index.Index | None) -> None:
    claimed, paid_ok = _scan_paid_evidence()
    pool = paid_ok & claimed          # paid cells that ended ok|partial
    manifest_keys = _manifest_paid_keys()
    detail_parts = [
        f"paid-ok cells={len(pool)} manifest-bytes={len(manifest_keys)}"
    ]
    if idx is not None:
        idx_claimed = {
            (r["idc"], r["arm"], r["variant"]) for r in idx.conn.execute(
                "SELECT DISTINCT idc,arm,variant FROM claims"
                " WHERE op='acquire' AND slot IS NULL")
        }
        idx_pool = idx.paid_pool() & idx_claimed
        detail_parts.append(f"index paid-pool={len(idx_pool)}")
        if idx.dirty():
            _check(checks, "paid", False,
                   "fail: cannot reconcile on .index-dirty index; "
                   + "; ".join(detail_parts))
            return
    missing_bytes = sorted(pool - manifest_keys, key=repr)
    unpaid = manifest_keys - pool
    # Census-seeded copies carry meta.import_src — migration bytes whose
    # payment predates the claim machinery (the ledger-side mirror of
    # _scan_paid_evidence's import_src exclusion). Exempt from the bypass
    # alarm, but counted so the exemption is never silent.
    seeded = set()
    for _mp, mkey, meta in vault._iter_metas():
        if mkey is not None and meta and meta.get("import_src"):
            seeded.add(mkey[:3])
    seeded_unpaid = unpaid & seeded
    unpaid_bytes = sorted(unpaid - seeded_unpaid, key=repr)
    if seeded_unpaid:
        detail_parts.append(f"seeded-exempt={len(seeded_unpaid)}")
    problems = []
    if missing_bytes:
        problems.append(
            f"{len(missing_bytes)} paid-ok cells without manifest bytes "
            f"(harvest never landed / bytes lost): "
            f"{[f'{i}.{a}@{v}' for i, a, v in missing_bytes][:5]}")
    if unpaid_bytes:
        problems.append(
            f"{len(unpaid_bytes)} manifest byte keys with no paid-ok cell "
            f"(bypass alarm — bytes nobody paid for): "
            f"{[f'{i}.{a}@{v}' for i, a, v in unpaid_bytes][:5]}")
    _check(checks, "paid", not problems,
           "; ".join(problems + detail_parts) if problems
           else "; ".join(detail_parts) + " — reconciled")


def _check_capacity(checks: list) -> None:
    problems, warnings = [], []
    try:
        hot = paths.events_path().stat().st_size
    except OSError:
        hot = 0
    if hot >= LEDGER_HOT_TAIL_MAX:
        problems.append(
            f"ledger hot tail {hot}B >= {LEDGER_HOT_TAIL_MAX}B hard gate "
            "(§3.10.1 — emit-side rotate should have fired)")
    lake_root = paths.lake_dir()
    used = 0
    if lake_root.is_dir():
        from kernel import fsutil
        used = fsutil.dir_size(lake_root)
    cap_gb = float(os.environ.get("TEXLATE_LAKE_CAP_GB", "100"))
    if used > cap_gb * 1024 ** 3:
        warnings.append(f"lake {used / 1024 ** 3:.1f}GiB over "
                        f"{cap_gb}GiB watermark — evict")
    try:
        free = shutil.disk_usage(lake_root if lake_root.is_dir()
                                 else paths.root()).free
        if free < _FS_FLOOR_GB * 1024 ** 3:
            warnings.append(f"fs free {free / 1024 ** 3:.1f}GiB under "
                            f"{_FS_FLOOR_GB}GiB floor")
    except OSError:
        warnings.append("fs free space unstat-able")
    ok = not problems
    detail = "; ".join(problems + warnings) if (problems or warnings) else \
        f"hot tail {hot}B <512MB; lake/cap + fs floor ok"
    _check(checks, "capacity", ok, detail)


def _check_queues(checks: list, idx: index.Index | None) -> None:
    def _lines(p: Path) -> int:
        if not p.exists():
            return 0
        return sum(1 for _ln, _ev, _raw in events.iter_jsonl(p))

    quar = _lines(paths.quarantine_path())
    adj = _lines(paths.adjudication_path())
    parts = [f"quarantine={quar}", f"adjudication={adj}"]
    if idx is not None:
        parts.append(f"index_quarantine={idx.quarantine_count()}")
    _check(checks, "queues", True, "; ".join(parts))


# --- switch-ok (§3.10.9 drain gate) ----------------------------------------------------

def _live_lane_writers(now: float) -> list[str]:
    """lane-* dirs under the scratch zones with a LIVE writer: a held
    .lock or a fresh (<_LANE_FRESH_S) heartbeat. Legacy archive lanes have
    neither and are correctly silent."""
    out = []
    bases = [paths.lake_tmp_dir(), _repo_root() / "tmp"]
    for base in bases:
        if not base.is_dir():
            continue
        for d in sorted(base.glob("lane-*")):
            if not d.is_dir():
                continue
            lock = d / ".lock"
            if lock.exists() and not locks.lock_free(lock):
                out.append(str(d))
                continue
            hb = d / "heartbeat"
            if hb.exists():
                age = locks.heartbeat_age(hb)
                if age is not None and age < _LANE_FRESH_S:
                    out.append(str(d))
    return out


def _live_errsweep_worktrees(now: float) -> list[str]:
    """errsweep/<date> worktrees under the repo root with activity fresher
    than the liveness window (shallow mtime scan — cheap and enough for a
    drain gate)."""
    base = _repo_root() / "errsweep"
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        try:
            newest = max(
                [d.stat().st_mtime]
                + [p.stat().st_mtime for p in d.iterdir()]
            )
        except OSError:
            continue
        if now - newest < _LANE_FRESH_S:
            out.append(str(d))
    return out


def _check_switch_ok(checks: list) -> None:
    blocked = []
    if not locks.kernel_idle():
        blocked.append("kernel-active held (a runner is alive)")
    active = runs.active_runs()
    if active:
        blocked.append(f"{len(active)} active runs: "
                       f"{[a['run'] for a in active][:5]}")
    if locks.pause_engaged():
        blocked.append("PAUSE engaged")
    now = time.time()
    lanes = _live_lane_writers(now)
    if lanes:
        blocked.append(f"live lane writers: {lanes[:5]}")
    err = _live_errsweep_worktrees(now)
    if err:
        blocked.append(f"live errsweep worktrees: {err[:5]}")
    _check(checks, "switch_ok", not blocked,
           "SWITCH-OK" if not blocked else "blocked: " + "; ".join(blocked))


# --- entry points ---------------------------------------------------------------------

def doctor(fix: bool = False, switch_ok: bool = False) -> dict:
    """Run all health checks; return {checks: [{name,ok,detail}], ok}.

    fix=True performs only the safe repairs: reap lock-free stale claims
    (the light sweep's job) and catch a lagging index up via tail_ingest.
    Everything else stays report-only — doctor never deletes bytes.
    """
    checks: list = []
    fixed: list = []

    _check_layout(checks)
    _check_root_location(checks)
    _check_stray_dirs(checks)
    idx = _open_index()
    try:
        stale = _check_lock_invariants(checks, idx)
        _check_ledger(checks, idx)
        _check_index(checks, idx)
        _check_paid(checks, idx)
        _check_capacity(checks)
        _check_queues(checks, idx)
        if switch_ok:
            _check_switch_ok(checks)
        if fix:
            if stale:
                from kernel import sweep as _sweep
                rep = _sweep.sweep(light=True)
                fixed.append(
                    f"reaped {len(rep['reaped_claims'])} stale claims "
                    "via light sweep")
            if idx is not None:
                gen_wm = idx.sealed_state()[1]
                if gen_wm < ledger.watermark_offset():
                    applied = idx.tail_ingest()
                    fixed.append(f"tail_ingest applied {applied} events")
    finally:
        if idx is not None:
            idx.close()
    ok = all(c["ok"] for c in checks)
    return {"checks": checks, "ok": ok, "fixed": fixed}


def fsck(defer_edges: bool = False) -> dict:
    """Deeper consistency pass; same {checks, ok} report shape.

    - vault verify('stat'): declared files present + size-exact;
      meta_missing/extra are warn-level (the hardened predicate owns them)
    - lake catalog vs dirs: hydrated/pinned/raw_only/skeleton rows whose
      cell dir vanished → fail; uncataloged dirs → warn
    - claims vs locks: acquire-open lease with a free flock → fail
    - from_run edges: plan.json needs entries referencing other runs —
      missing run → fail; run present but cell undone → warn
      (defer_edges=True skips this leg entirely)
    """
    checks: list = []

    # -- vault stat-level verify --------------------------------------------------
    rep = vault.verify("stat")
    problems = []
    warnings = []
    if rep["bad"]:
        problems.append(f"{len(rep['bad'])} bad files "
                        f"(size/sha/missing): "
                        f"{[b.get('reason') for b in rep['bad']][:5]}")
    if rep["meta_bad"]:
        problems.append(f"{len(rep['meta_bad'])} unparseable/"
                        f"credential-mismatched metas")
    if rep["meta_missing"]:
        warnings.append(f"{len(rep['meta_missing'])} meta-less dirs "
                        "(report-level per §3.10.4)")
    if rep["extra"]:
        warnings.append(f"{len(rep['extra'])} undeclared files inside "
                        "covered leaves")
    _check(checks, "vault_stat", not problems,
           "; ".join(problems + warnings) if (problems or warnings)
           else f"{rep['metas']} metas, {rep['checked']} files, "
                f"{rep['inodes']} inodes — clean")

    # -- lake catalog vs dirs ------------------------------------------------------
    cat = lake.LakeCatalog.load()
    rows = cat.rows()
    dirless = []
    for idc, row in sorted(rows.items()):
        if row.get("state") in ("hydrated", "pinned", "raw_only",
                                "skeleton"):
            d = lake.cell_dir(idc, row.get("source", "arxiv"))
            if not d.is_dir():
                dirless.append(idc)
    uncataloged = []
    corpus = paths.lake_corpus_dir()
    if corpus.is_dir():
        for source_dir in sorted(corpus.iterdir()):
            if not source_dir.is_dir() or source_dir.name.startswith("."):
                continue
            for cell in sorted(source_dir.iterdir()):
                if cell.is_dir() and not cell.name.startswith("."):
                    if idc_from_safe(cell.name) not in rows:
                        uncataloged.append(str(cell))
    problems = []
    warnings = []
    if dirless:
        problems.append(f"{len(dirless)} catalog rows state hydrated/"
                        f"skeleton with no cell dir: {dirless[:5]}")
    if uncataloged:
        warnings.append(f"{len(uncataloged)} lake dirs with no catalog "
                        f"row (orphans — sweep adopts)")
    _check(checks, "lake_catalog", not problems,
           "; ".join(problems + warnings) if (problems or warnings)
           else f"{len(rows)} catalog rows vs dirs — consistent")

    # -- claims vs locks ------------------------------------------------------------
    idx = _open_index()
    try:
        stale = _stale_claims(idx)
    finally:
        if idx is not None:
            idx.close()
    _check(checks, "claims_locks", not stale,
           f"{len(stale)} acquire-open claims with free flocks: "
           f"{stale[:5]}" if stale else
           ("no index — skipped" if idx is None else
            "every open claim has a live flock"))

    # -- from_run edges ---------------------------------------------------------------
    if not defer_edges:
        problems = []
        warnings = []
        known_runs = set()
        for _ln, row, _raw in events.iter_jsonl(paths.runs_jsonl_path()):
            if isinstance(row, dict) and isinstance(row.get("run"), str):
                known_runs.add(row["run"])
        idx2 = _open_index()
        try:
            base = paths.runs_dir()
            for rdir in sorted(base.glob("*/*/*")) if base.is_dir() else []:
                plan = rdir / "plan.json"
                if not plan.exists():
                    continue
                try:
                    cells = json.loads(
                        plan.read_text(encoding="utf-8")).get("cells", [])
                except (OSError, ValueError):
                    problems.append(f"unparseable plan: {plan}")
                    continue
                rel = rdir.relative_to(base)
                run_id = "/".join(rel.parts)
                for c in cells:
                    for need in c.get("needs") or []:
                        ref = None
                        if isinstance(need, dict):
                            ref = need.get("run") or need.get("from_run")
                        elif isinstance(need, str) and need.startswith("run:"):
                            ref = need[4:]
                        if not ref or ref == run_id:
                            continue
                        if ref not in known_runs:
                            problems.append(
                                f"{run_id}: need references missing run "
                                f"{ref!r} (dangling from_run edge)")
                        elif idx2 is not None and isinstance(need, dict):
                            ok_done = idx2.done(
                                need.get("idc") or need.get("id"),
                                need.get("arm", "-"), need.get("up", "-"),
                                need.get("variant", "-"),
                                need.get("stage", "-"), runs=[ref])
                            if not ok_done:
                                warnings.append(
                                    f"{run_id}: need {need.get('idc')}."
                                    f"{need.get('stage','-')} not done "
                                    f"in {ref}")
        finally:
            if idx2 is not None:
                idx2.close()
        _check(checks, "from_run_edges", not problems,
               "; ".join(problems + warnings) if (problems or warnings)
               else "no dangling from_run edges")

    ok = all(c["ok"] for c in checks)
    return {"checks": checks, "ok": ok}
