"""tests/kernel/test_dedup.py — fail-closed paid-gate oracle (§3.6/§3.10.6).

Covers: snapshot captures all three frozen legs; unsealed index (dirty
flag or watermark behind) -> 'unsealed' for every input, even verified
ones; live claim -> 'claimed'; the three durable verified legs (manifest
tail / paid_pool snapshot / vault meta files); tombstone & quar verdict
-> 'missing'; clean -> 'absent'; quote() bucket partition +
regen_decisions; regen_allowed's four-condition gate; attempted_unpaid.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from kernel import events, idnorm, paths, vault
from kernel.claims import ClaimLease
from kernel.dedup import (
    ABSENT,
    CLAIMED,
    MISSING,
    UNSEALED,
    VERIFIED,
    DedupOracle,
    attempted_unpaid,
    manifest_tail,
    tombstoned,
)
from kernel.index import Index

if TYPE_CHECKING:
    from pathlib import Path

IDC = "cs/2401.00001"
IDC2 = "hep-ph/9901223"
ARM = "zh"
V = "-"


# -- helpers ---------------------------------------------------------------------


def _append(evs: list[dict]) -> int:
    """Append events to the hot-tail ledger; returns bytes written."""
    p = paths.events_path()
    n = 0
    with p.open("a", encoding="utf-8") as f:
        for ev in evs:
            line = events.dumps(ev) + "\n"
            f.write(line)
            n += len(line.encode("utf-8"))
    return n


def _cell(  # noqa: PLR0913, PLR0917 -- 参数面即契约（cell 事件字段面）
    seq: int,
    run: str = "r1",
    idc: str = IDC,
    status: str = "ok",
    stage: str = "xlat",
    arm: str = ARM,
    **kw: object,
) -> dict:
    kw.setdefault("id", idc)
    return events.make_event(
        events.T_CELL,
        run=run,
        seq=seq,
        idc=idc,
        arm=arm,
        up="-",
        variant="-",
        stage=stage,
        status=status,
        dur_s=1.5,
        sig="cat:pay",
        code="deadbeef",
        fp="fp1",
        **kw,
    )


def _asset(
    seq: int,
    idc: str = IDC,
    kind: str = "zh",
    state: str = "verified",
    run: str = "r1",
    **kw: object,
) -> dict:
    kw.setdefault("id", idc)
    return events.make_event(
        events.T_ASSET,
        run=run,
        seq=seq,
        idc=idc,
        arm=ARM,
        variant="-",
        kind=kind,
        path=f"vault/{kind}/{idc}",
        sha="sha1",
        bytes=123,
        state=state,
        **kw,
    )


def _tombstone(idc: str = IDC, kind: str = "zh", **kw: object) -> dict:
    kw.setdefault("id", idc)
    return events.make_event(
        events.T_TOMBSTONE,
        idc=idc,
        arm=ARM,
        variant="-",
        kind=kind,
        reason="lost bytes",
        lost_run="r0",
        **kw,
    )


def _sealed_index(broot: Path) -> Index:  # noqa: ARG001 -- fixture 副作用（要求隔离 BENCH_ROOT 已就位）
    """Index rebuilt (sealed) over the current ledger."""
    idx = Index()
    idx.rebuild()
    return idx


def _write_manifest(rows: list[dict]) -> None:
    p = paths.vault_manifest_path()
    with p.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, sort_keys=True) + "\n" for r in rows)


def _manifest_row(idc: str, arm: str = ARM, variant: str = V, **kw: object) -> dict:
    row = {"idc": idc, "arm": arm, "variant": variant, "zone": "primary"}
    row.update(kw)
    return row


def _write_meta(  # noqa: PLR0913, PLR0917 -- 参数面即契约（§3.10.4 meta 六元组）
    idc: str,
    arm: str = ARM,
    variant: str = V,
    altseq: str | None = None,
    body: dict | None = None,
    name: str | None = None,
) -> Path:
    """Write a vault/meta file in the §3.10.4 layout; returns its path."""
    if name is None:
        name = idnorm.escape_component(idnorm.safe_id(idc))
        name += "." + idnorm.escape_component(arm)
        if variant != "-":
            name += "@" + idnorm.escape_component(variant)
        if altseq is not None:
            name += "." + idnorm.escape_component(str(altseq))
        name += ".json"
    rec = {"idc": idc, "arm": arm, "variant": variant}
    if body:
        rec.update(body)
    p = paths.vault_meta_dir() / name
    p.write_text(json.dumps(rec), encoding="utf-8")
    return p


def _commit_copy(  # noqa: PLR0913, PLR0917 -- 参数面即契约（vault copy 六元组）
    idc: str,
    arm: str = ARM,
    variant: str = V,
    altseq: str = "0",
    verdict: str = "primary",
    kinds: tuple[str, ...] = ("zh",),
) -> Path:
    """A physically committed vault copy: real leaf bytes + a real-shaped
    meta (zone/verdict/files={kind:[{path,size}]}), filename via
    vault.meta_key — what harvest actually leaves on disk."""
    zone = "quar" if verdict in ("quar", "quarantine") else "primary"
    sid = idnorm.safe_id(idc)
    key = vault.dir_key(arm, variant, altseq)
    files = {}
    for kind in kinds:
        root = (
            (paths.vault_dir() / "quar" / kind)
            if zone == "quar"
            else paths.vault_dir() / kind
        )
        leaf = root / sid / key
        leaf.mkdir(parents=True, exist_ok=True)
        payload = f"bytes-{idc}-{kind}".encode()
        (leaf / f"{kind}.bin").write_bytes(payload)
        files[kind] = [
            {"path": f"{kind}.bin", "size": len(payload), "sha256": "0" * 64}
        ]
    body = {
        "idc": idc,
        "arm": arm,
        "variant": variant,
        "altseq": altseq,
        "zone": zone,
        "verdict": verdict,
        "files": files,
    }
    return _write_meta(
        idc,
        arm,
        variant,
        altseq=altseq,
        body=body,
        name=vault.meta_key(idc, arm, variant, altseq),
    )


# -- snapshot ----------------------------------------------------------------------


def test_snapshot_captures_all_three_legs(broot: Path) -> None:
    _append([_cell(1, status="ok")])
    _write_manifest([_manifest_row(IDC2, bytes_ok=True)])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)

    gen, wm = idx.sealed_state()
    assert oracle.sealed_gen == gen == 1
    # min_offset covers the fsync'd ledger tail at snapshot time
    assert oracle.min_offset >= wm > 0
    assert (IDC2, ARM, V) in oracle.manifest_tail
    assert (IDC, ARM, V) in oracle.paid_pool_snap
    assert oracle.sealed()
    idx.close()


def test_snapshot_empty_bench_is_sealed_absent(broot: Path) -> None:
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.sealed()
    assert oracle.check(IDC, ARM) == ABSENT
    idx.close()


# -- unsealed gate -------------------------------------------------------------------


def test_dirty_index_unseals_everything(broot: Path) -> None:
    """Even a manifest-verified cell answers 'unsealed' on a dirty index —
    the seal failure is the alarm that must surface (§3.10.6 ③)."""
    _write_manifest([_manifest_row(IDC, bytes_ok=True)])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check(IDC, ARM) == VERIFIED  # baseline: durable leg works
    idx.note_dirty("test")
    for idc in (IDC, IDC2, "a/9"):
        assert oracle.check(idc) == UNSEALED
    idx.close()


def test_watermark_behind_unseals(broot: Path) -> None:
    """A snapshot whose min_offset covers bytes the index has not ingested
    heals itself: check() runs ONE catch-up tail_ingest before declaring
    unsealed — the seal only stays broken when the index still cannot
    cover the durable tail (dirty flag, gen mismatch, a shrunken
    post-rotation file)."""
    _append([_cell(1, status="ok")])
    idx = _sealed_index(broot)
    _append([_tombstone(IDC2)])  # durable bytes the index has NOT seen
    oracle = DedupOracle.snapshot(idx)  # min_offset includes the tombstone
    # first check catches the index up — verdicts come from real evidence,
    # not a stale-watermark stall
    assert oracle.check(IDC, ARM) == VERIFIED
    assert oracle.check(IDC2, ARM) == MISSING  # tombstone now visible
    idx.close()


def test_gen_mismatch_unseals(broot: Path) -> None:
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    idx.rebuild()  # bumps sealed_gen
    assert oracle.check(IDC, ARM) == UNSEALED
    idx.close()


def test_unsealed_beats_claimed(broot: Path) -> None:
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    lease = ClaimLease(IDC, ARM, V)
    assert lease.acquire()
    try:
        idx.note_dirty("x")
        assert oracle.check(IDC, ARM) == UNSEALED
    finally:
        lease.release()
    idx.close()


# -- claimed -------------------------------------------------------------------------


def test_live_claim_returns_claimed(broot: Path) -> None:
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    lease = ClaimLease(IDC, ARM, V)
    assert lease.acquire()
    try:
        assert oracle.check(IDC, ARM) == CLAIMED
    finally:
        lease.release()
    assert oracle.check(IDC, ARM) == ABSENT
    idx.close()


def test_claimed_beats_verified(broot: Path) -> None:
    """A live claim outranks even durable verified evidence — someone is
    actively re-doing the cell (check order: claimed before verified)."""
    _append([_cell(1, status="ok")])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check(IDC, ARM) == VERIFIED
    lease = ClaimLease(IDC, ARM, V)
    assert lease.acquire()
    try:
        assert oracle.check(IDC, ARM) == CLAIMED
    finally:
        lease.release()
    idx.close()


# -- verified legs ---------------------------------------------------------------------


def test_verified_via_paid_pool_snapshot(broot: Path) -> None:
    _append(
        [
            _cell(1, idc="a/1", status="ok"),
            _cell(2, idc="a/2", status="partial"),
            _cell(3, idc="a/3", status="clean"),  # terminal but not paid-pool
        ]
    )
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("a/1", ARM) == VERIFIED
    assert oracle.check("a/2", ARM) == VERIFIED
    assert oracle.check("a/3", ARM) != VERIFIED  # clean ∉ paid pool
    idx.close()


def test_verified_via_manifest_tail(broot: Path) -> None:
    _write_manifest(
        [
            _manifest_row("a/1", bytes_ok=True),
            _manifest_row("a/2", assets={"zh": "p", "splice": None}),
            _manifest_row("a/3", has_splice=True),  # legacy row shape
            _manifest_row("a/4", bytes_ok=False),  # demoted — no bytes
            {"garbage": True},
        ]
    )
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("a/1", ARM) == VERIFIED
    assert oracle.check("a/2", ARM) == VERIFIED
    assert oracle.check("a/3", ARM) == VERIFIED
    assert oracle.check("a/4", ARM) == ABSENT  # demote row won
    idx.close()


def test_manifest_tail_last_row_wins_per_altseq(broot: Path) -> None:
    """A demote row only kills its own altseq's evidence (§3.10.4)."""
    _write_manifest(
        [
            _manifest_row("a/1", altseq="0", bytes_ok=True),
            _manifest_row("a/1", altseq="1", bytes_ok=True),
            _manifest_row("a/1", altseq="1", bytes_ok=False),  # demote alt 1 only
            _manifest_row("a/2", bytes_ok=True),
            _manifest_row("a/2", bytes_ok=False),  # demote sole copy
        ]
    )
    tail = manifest_tail(paths.vault_manifest_path())
    assert ("a/1", ARM, V) in tail  # altseq 0 still alive
    assert ("a/2", ARM, V) not in tail
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("a/1", ARM) == VERIFIED
    assert oracle.check("a/2", ARM) == ABSENT
    idx.close()


def test_manifest_tail_tolerates_torn_and_bad_rows(
    broot: Path,  # noqa: ARG001 -- fixture 副作用（BENCH_ROOT 隔离）
) -> None:
    p = paths.vault_manifest_path()
    with p.open("a", encoding="utf-8") as f:
        f.write('{"idc":"a/1","arm":"zh","variant":"-","bytes_ok":true}\n')
        f.write("{not json\n")
        f.write('{"idc":"a/2","arm":"zh","variant":"-","bytes_ok":true')  # torn tail
    tail = manifest_tail(p)
    assert tail == {("a/1", "zh", "-")}


def test_verified_via_vault_meta_file(broot: Path) -> None:
    _commit_copy("cs/0601023", verdict="primary")
    _commit_copy("cs/0601024", verdict="quar")  # quar + bytes = §3.8 dedup hit
    _write_meta(
        "cs/0601033",
        body={
            "verdict": "pending",  # pending ≠ bytes
            "assets": {"zh": "x.pdf"},
        },
    )
    _write_meta(
        "cs/0601034", body={"verdict": "primary", "assets": {}}
    )  # no declared bytes
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("cs/0601023", ARM) == VERIFIED
    assert oracle.check("cs/0601024", ARM) == VERIFIED  # quar + bytes verifies
    assert oracle.check("cs/0601033", ARM) != VERIFIED  # pending = no-bytes
    assert oracle.check("cs/0601034", ARM) != VERIFIED  # no assets declared
    idx.close()


def test_partial_kind_meta_does_not_verify_uncovered_needs(broot: Path) -> None:
    """retry39 regression: a {state}-only harvest (xlat checkpoint sealed,
    zh never produced) must NOT mint 'verified' for a stage whose
    need_kinds span zh+state — the meta only vouches kinds it declares.
    The scalar meta_ok leg used to pass this through, deduping xlat while
    no DONE row and no zh bytes existed: every downstream stage
    needs-skipped forever (compile skip needs / fixloop upstream-error).
    """
    _commit_copy("cs/0601040", verdict="primary", kinds=("state",))
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    # full need span: zh never sealed and nothing is dead -> absent, so
    # the paid cell re-runs (resuming from the state checkpoint)
    assert oracle.check("cs/0601040", ARM, need_kinds={"zh", "state"}) == ABSENT
    # a stage needing only the sealed kind still verifies
    assert oracle.check("cs/0601040", ARM, need_kinds={"state"}) == VERIFIED
    # callers without need_kinds keep the cell-level leg
    assert oracle.check("cs/0601040", ARM) == VERIFIED
    idx.close()


def test_split_kinds_across_copies_verify(broot: Path) -> None:
    """Two intact copies each declaring a different needed kind union to
    full coverage — kind coverage is per-cell, not per-copy."""
    _commit_copy("cs/0601041", verdict="primary", altseq="0", kinds=("zh",))
    _commit_copy("cs/0601041", verdict="alt", altseq="1", kinds=("state",))
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("cs/0601041", ARM, need_kinds={"zh", "state"}) == VERIFIED
    idx.close()


def test_committed_but_bytes_gone_is_missing(broot: Path) -> None:
    """Meta verdict=primary whose declared files are absent on disk is
    §3.6's third state (付过费但字节没了) -> missing -> regen gate, never
    a silent verified skip and never an ungated re-pay."""
    _commit_copy("cs/0601025", verdict="primary")
    leaf = paths.vault_dir() / "zh" / "cs--0601025" / "zh"
    for f in leaf.iterdir():
        f.unlink()
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("cs/0601025", ARM) == MISSING
    idx.close()


def test_unparseable_meta_body_is_missing_evidence(broot: Path) -> None:
    """Filename claims our cell but body unreadable = broken commit
    marker — missing-side evidence (spend-refusing), never 'absent'."""
    p = _write_meta("cs/0601026", body={"verdict": "primary"})
    p.write_text("{not json", encoding="utf-8")
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("cs/0601026", ARM) == MISSING
    idx.close()


def test_verified_legs_are_durable_not_live_index(broot: Path) -> None:
    """index.vault_bytes_ok()/live cells are advisory: an oracle built
    WITHOUT frozen legs answers 'absent' even though the index says ok —
    verified is only ever minted from durable/frozen facts."""
    _append([_cell(1, status="ok"), _asset(2, state="verified")])
    idx = _sealed_index(broot)
    assert (IDC, ARM, V) in idx.vault_bytes_ok()
    oracle = DedupOracle(
        idx,
        manifest_tail=None,
        paid_pool_snap=None,
        sealed_gen=idx.sealed_state()[0],
        min_offset=idx.sealed_state()[1],
    )
    assert oracle.check(IDC, ARM) == ABSENT
    # ...and the same cell with a frozen leg verifies
    oracle2 = DedupOracle.snapshot(idx)
    assert oracle2.check(IDC, ARM) == VERIFIED
    idx.close()


# -- missing -------------------------------------------------------------------------


def test_tombstone_event_means_missing(broot: Path) -> None:
    _append([_tombstone(IDC)])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert tombstoned(idx, IDC, ARM, V)
    assert oracle.check(IDC, ARM) == MISSING
    idx.close()


def test_quar_verdict_means_missing(broot: Path) -> None:
    """quar verdict + no byte evidence = §3.6 missing∪quarantine hard stop."""
    _append([_asset(1, idc="a/1", state="pending", verdict="quar")])
    _write_meta("cs/0601035", body={"verdict": "quar", "assets": {}})
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("a/1", ARM) == MISSING  # index vault_meta quar verdict
    assert oracle.check("cs/0601035", ARM) == MISSING  # durable meta quar verdict
    idx.close()


def test_lost_cell_means_missing(broot: Path) -> None:
    _append([_cell(1, idc="a/1", status="lost")])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("a/1", ARM) == MISSING
    idx.close()


def test_verified_leg_beats_missing_evidence(broot: Path) -> None:
    """tombstone evidence + durable bytes -> verified wins (check order):
    per-altseq reality is 'one copy lost, one copy alive'."""
    _append([_tombstone(IDC)])
    _write_manifest([_manifest_row(IDC, bytes_ok=True)])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check(IDC, ARM) == VERIFIED
    idx.close()


def test_missing_never_implied_by_paid_attempt(broot: Path) -> None:
    """A reject/fail cell with NO tombstone evidence is 'absent' in the
    bytes domain — the attempted-unpaid bucket is quote()'s business."""
    _append([_cell(1, idc="a/1", status="reject")])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("a/1", ARM) == ABSENT
    idx.close()


# -- attempted_unpaid ------------------------------------------------------------------


def test_attempted_unpaid_classification(broot: Path) -> None:
    _append(
        [
            _cell(1, idc="a/1", status="reject"),
            _cell(2, idc="a/2", status="fail"),
            _cell(3, idc="a/3", status="fault"),
            _cell(4, idc="a/4", status="dirty_pdf"),
            _cell(5, idc="a/5", status="ok"),
            _cell(6, idc="a/5", status="reject", stage="fixloop"),
            _cell(7, idc="a/6", status="error"),  # retriable — not attempted
            _cell(8, idc="a/7", status="reject", cat="regen_gate"),  # gate artifact
        ]
    )
    idx = _sealed_index(broot)
    for idc in ("a/1", "a/2", "a/3", "a/4"):
        assert attempted_unpaid(idx, idc, ARM, V), idc
    assert not attempted_unpaid(idx, "a/5", ARM, V)  # ok exists → recovered
    assert not attempted_unpaid(idx, "a/6", ARM, V)  # error is retriable
    assert not attempted_unpaid(idx, "a/7", ARM, V)  # regen_gate ≠ attempt
    assert not attempted_unpaid(idx, "a/8", ARM, V)  # never seen
    idx.close()


# -- quote -------------------------------------------------------------------------------


def test_quote_partitions_mixed_set(broot: Path) -> None:
    _append(
        [
            _cell(1, idc="a/1", status="ok"),  # reuse (paid pool)
            _cell(2, idc="a/2", status="partial"),  # reuse
            _cell(3, idc="a/4", status="reject"),  # attempted
            _tombstone(idc="a/3"),  # missing
        ]
    )
    _write_manifest([_manifest_row("a/5", bytes_ok=True)])  # reuse via manifest
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)

    lease = ClaimLease("a/6", ARM, V)
    assert lease.acquire()
    try:
        cells = [
            ("a/1", ARM, V),
            ("a/2", ARM, V),
            ("a/3", ARM, V),
            ("a/4", ARM, V),
            ("a/5", ARM, V),
            ("a/6", ARM, V),
            ("a/7", ARM, V),  # brand new
            {"idc": "a/8", "arm": ARM, "variant": V},  # dict form
        ]
        rep = oracle.quote(cells)
    finally:
        lease.release()

    assert rep["sealed"]
    assert rep["total"] == len(cells)
    for b in ("new", "reuse", "missing", "claimed", "attempted", "unsealed"):
        assert isinstance(rep[b], int)
        assert isinstance(rep["buckets"][b], list)
    # partition: every input cell in exactly one bucket
    flat = sorted(k for keys in rep["buckets"].values() for k in keys)
    assert len(flat) == len(cells)

    assert rep["buckets"]["reuse"] == [
        ("a/1", ARM, V),
        ("a/2", ARM, V),
        ("a/5", ARM, V),
    ]
    assert rep["buckets"]["missing"] == [("a/3", ARM, V)]
    assert rep["buckets"]["claimed"] == [("a/6", ARM, V)]
    assert rep["buckets"]["attempted"] == [("a/4", ARM, V)]
    assert rep["buckets"]["new"] == [("a/7", ARM, V), ("a/8", ARM, V)]
    assert rep["buckets"]["unsealed"] == []
    # regen_decisions lists ONLY missing ids
    assert rep["regen_decisions"] == [("a/3", ARM, V)]
    idx.close()


def test_quote_unsealed_reports_everything_unsealed(broot: Path) -> None:
    _append([_cell(1, idc="a/1", status="ok")])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    idx.note_dirty("boom")
    rep = oracle.quote([("a/1", ARM, V), ("a/2", ARM, V)])
    assert not rep["sealed"]
    assert rep["unsealed"] == 2  # noqa: PLR2004 -- 断言字面量（两个入格全 unsealed）
    assert rep["new"] == 0
    assert rep["reuse"] == 0
    assert rep["regen_decisions"] == []
    idx.close()


def test_quote_attempted_needs_paid_flag(broot: Path) -> None:
    """Free-stage cells with fail statuses are cheap to rerun -> 'new',
    not 'attempted' (the attempted bucket is a paid-cell concept)."""
    _append([_cell(1, idc="a/1", status="fail")])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    rep = oracle.quote(
        [
            {"idc": "a/1", "arm": ARM, "variant": V, "stage_paid": False},
            {"idc": "a/1", "arm": ARM, "variant": V, "stage_paid": True},
        ]
    )
    assert rep["buckets"]["new"] == [("a/1", ARM, V)]
    assert rep["buckets"]["attempted"] == [("a/1", ARM, V)]
    idx.close()


# -- regen gate ---------------------------------------------------------------------------


def test_regen_allowed_requires_all_four(broot: Path) -> None:
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    base = {
        "idc": IDC,
        "arm": ARM,
        "variant": V,
        "allow_regen": True,
        "sel_hit": True,
        "max_cost": 1.0,
        "yes": True,
    }
    assert oracle.regen_allowed(**base)
    for kill in ("allow_regen", "sel_hit", "max_cost", "yes"):
        kw = dict(base)
        kw[kill] = False if kill != "max_cost" else None
        assert not oracle.regen_allowed(**kw), kill
    # --rerun/--recode shaped intent has no regen power
    assert not oracle.regen_allowed(
        IDC, ARM, V, allow_regen=False, sel_hit=True, max_cost=1.0, yes=True
    )
    idx.close()


def test_missing_cells_are_the_regen_decision_list(broot: Path) -> None:
    """regen_decisions == missing bucket exactly; tombstoned ids never
    auto-enter a run set — they wait for the human's --regen (§3.6)."""
    _append([_tombstone(idc="a/3"), _tombstone(idc="a/4")])
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    rep = oracle.quote([("a/3", ARM, V), ("a/4", ARM, V), ("a/5", ARM, V)])
    assert rep["regen_decisions"] == [("a/3", ARM, V), ("a/4", ARM, V)]
    assert rep["new"] == 1  # only the clean absent cell is runnable
    idx.close()


# -- meta filename parsing ----------------------------------------------------------------


def test_meta_scan_variant_and_altseq_names(broot: Path) -> None:
    """Variant/altseq name forms parse back to the right cell key."""
    _commit_copy("cs/0601027", variant="rep3", verdict="primary")
    _commit_copy("cs/0601028", altseq="2", verdict="primary")
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("cs/0601027", ARM, "rep3") == VERIFIED
    assert oracle.check("cs/0601027", ARM) != VERIFIED  # variant ≠ = different cell
    assert oracle.check("cs/0601028", ARM) == VERIFIED  # any altseq copy verifies
    idx.close()


def test_unparseable_meta_name_contributes_nothing(broot: Path) -> None:
    """The filename is the authoritative credential (§3.10.4): a meta
    whose name does not parse is invisible to the oracle — its body can
    never greenlight a skip; doctor's meta-less report owns the anomaly."""
    _write_meta(
        "cs/0601029",
        name="strange-name.json",
        body={"verdict": "verified", "files": {"zh": [{"path": "x", "size": 1}]}},
    )
    idx = _sealed_index(broot)
    oracle = DedupOracle.snapshot(idx)
    assert oracle.check("cs/0601029", ARM) == ABSENT
    idx.close()


def test_oracle_without_snapshot_is_unsealed_when_index_lags(broot: Path) -> None:
    """Hand-built oracle with min_offset beyond the index watermark must
    not greenlight — the seal check is fail-closed by construction."""
    _append([_cell(1, status="ok")])
    idx = _sealed_index(broot)
    gen, wm = idx.sealed_state()
    oracle = DedupOracle(
        idx,
        manifest_tail={(IDC, ARM, V)},
        paid_pool_snap={(IDC, ARM, V)},
        sealed_gen=gen,
        min_offset=wm + 1,
    )
    assert oracle.check(IDC, ARM) == UNSEALED
    idx.close()
