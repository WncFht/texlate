"""Tests for kernel/sweep.py — the reaper (zombie runs, claim reaps,
pending-meta reconcile, orphan adoption, harvest-pending, tombstones).

Every test runs against an isolated $TEXLATE_BENCH_ROOT via `broot`.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from kernel import claims, events, index, lake, ledger, locks, paths, runs, sweep, vault
from kernel.idnorm import safe_id


def _make_zombie_run(
    kind: str = "soak", slug: str = "z1", cells: tuple[str, ...] = ("2401.00001",)
) -> runs.RunDir:
    """A registered run with queued+started cells, a stale heartbeat and a
    free run.lock — the §3.10.1 zombie signature."""
    rd = runs.create_run(kind, slug=slug, date="2026-09-21")
    runs.freeze_plan(
        rd,
        [
            {
                "id": c,
                "idc": c,
                "arm": "zh",
                "up": "-",
                "variant": "-",
                "stage": "xlat",
                "needs": [],
                "fp_input": None,
            }
            for c in cells
        ],
    )
    for i, c in enumerate(cells):
        ledger.emit(
            events.make_event(
                events.T_CELL_QUEUED,
                run=rd.run,
                seq=10 + i,
                id=c,
                idc=c,
                arm="zh",
                up="-",
                variant="-",
                stage="xlat",
            ),
            run_dir=rd.path,
        )
        ledger.emit(
            events.make_event(
                events.T_CELL_STARTED,
                run=rd.run,
                seq=20 + i,
                id=c,
                idc=c,
                arm="zh",
                up="-",
                variant="-",
                stage="xlat",
            ),
            run_dir=rd.path,
        )
    old = time.time() - 3600
    os.utime(rd.heartbeat_path(), (old, old))
    return rd


def _shard(rd: runs.RunDir) -> list[dict]:
    return [e for _ln, e, _raw in events.iter_jsonl(rd.events_path()) if e is not None]


def _ledger_events(etype: str | None = None) -> list[dict]:
    out = []
    for _ln, ev, _raw in events.iter_jsonl(paths.events_path()):
        if ev is None:
            continue
        if etype is None or ev.get("type") == etype:
            out.append(ev)
    return out


def _vault_src(tmp_path: Path, name: str = "zh.mock") -> Path:
    d = tmp_path / "vault-src" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "out.txt").write_text("translated bytes")
    return d


def _cell_event(run: str, seq: int, idc: str, status: str) -> dict:
    return events.make_event(
        events.T_CELL,
        run=run,
        seq=seq,
        id=idc,
        idc=idc,
        arm="zh",
        up="-",
        variant="-",
        stage="xlat",
        status=status,
    )


def _claim_acquire(run: str, seq: int, idc: str) -> dict:
    # lifecycle claims carry no slot — slot is the paid_slots mirror stream
    return events.make_event(
        events.T_CLAIM,
        run=run,
        seq=seq,
        id=idc,
        idc=idc,
        arm="zh",
        variant="-",
        op="acquire",
    )


# --- zombies ----------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_sweep_reaps_zombie_run() -> None:
    rd = _make_zombie_run()
    # a live claim lease left behind by the dead runner
    ledger.emit(_claim_acquire(rd.run, 30, "2401.00001"), run_dir=rd.path)

    rep = sweep.sweep()
    assert [z["run"] for z in rep["zombies"]] == [rd.run]
    assert rep["zombies"][0]["lost_cells"] == 1
    # 'lost' terminal landed in both ledger and the run shard
    lost = [
        e for e in _shard(rd) if e.get("type") == "cell" and e.get("status") == "lost"
    ]
    assert len(lost) == 1
    assert lost[0]["idc"] == "2401.00001"
    assert lost[0]["seq"] < 0  # kernel negative seq
    # claim reaped (audit event) — the projection also clears the key's
    # paid_slots mirror rows
    reaps = [
        e for e in _shard(rd) if e.get("type") == "claim" and e.get("op") == "reap"
    ]
    assert len(reaps) == 1
    assert reaps[0]["idc"] == "2401.00001"
    assert rep["reaped_claims"][0]["idc"] == "2401.00001"
    # zombie note present
    notes = [e for e in _shard(rd) if e.get("type") == "note"]
    assert any("zombie" in n["text"] for n in notes)


@pytest.mark.usefixtures("broot")
def test_sweep_locked_cell_survives() -> None:
    rd = _make_zombie_run()
    sid = safe_id("2401.00001")
    # a live worker still holds the cell lock — split-brain, never reap
    with runs.cell_lock(rd, sid):
        rep = sweep.sweep()
    assert rep["zombies"][0]["lost_cells"] == 0
    assert rep["zombies"][0]["live_cells"] == 1
    lost = [
        e for e in _shard(rd) if e.get("type") == "cell" and e.get("status") == "lost"
    ]
    assert lost == []


@pytest.mark.usefixtures("broot")
def test_sweep_fresh_run_is_not_a_zombie() -> None:
    rd = _make_zombie_run()
    rd.heartbeat_touch()  # fresh heartbeat
    rep = sweep.sweep()
    assert rep["zombies"] == []


@pytest.mark.usefixtures("broot")
def test_sweep_light_still_reaps_zombies() -> None:
    rd = _make_zombie_run()
    rep = sweep.sweep(light=True)
    assert [z["run"] for z in rep["zombies"]] == [rd.run]
    # housekeeping duties are skipped in the light pass
    assert rep["promoted"] == []
    assert rep["adopted"] == []
    assert rep["harvest_pending"] == []
    assert rep["tombstoned"] == []


@pytest.mark.usefixtures("broot")
def test_sweep_concurrent_returns_skipped() -> None:
    with locks.flock(
        sweep._sweep_lock_path(),  # noqa: SLF001 -- 钉私有面：并发互斥锁路径无公共等价
        exclusive=True,
    ):
        rep = sweep.sweep()
    assert rep.get("skipped")


@pytest.mark.usefixtures("broot")
def test_sweep_stale_claim_reaped_when_run_dir_gone() -> None:
    """Index shows acquire-open, flock free, run dir missing entirely —
    the dead-claimant case the zombie pass cannot see."""
    idx = index.Index()
    idx.apply_event(_claim_acquire("r/2026-09-20/gone", 1, "2401.00011"))
    idx.close()
    rep = sweep.sweep(light=True)
    assert rep["reaped_claims"][0]["idc"] == "2401.00011"
    reaps = [e for e in _ledger_events("claim") if e.get("op") == "reap"]
    assert len(reaps) == 1
    assert reaps[0]["idc"] == "2401.00011"


@pytest.mark.usefixtures("broot")
def test_sweep_live_claim_lock_vetoes_reap() -> None:
    idx = index.Index()
    idx.apply_event(_claim_acquire("r/2026-09-20/x", 1, "2401.00012"))
    idx.close()
    # someone still holds the claim flock — alive, never reap
    with locks.flock(claims.claim_lock_path("2401.00012", "zh", "-")):
        rep = sweep.sweep(light=True)
    assert rep["reaped_claims"] == []


# --- pending metas ------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_sweep_pending_meta_promotes_with_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _vault_src(tmp_path)
    mpath = vault.harvest(
        "2401.00001", "zh", "-", {"zh": src}, source_run="adhoc/2026-09-20/x"
    )
    assert mpath.exists()
    # index says the cell ended clean → verdict primary
    idx = index.Index()
    idx.apply_event(_cell_event("adhoc/2026-09-20/x", 1, "2401.00001", "ok"))
    idx.close()
    rep = sweep.sweep()  # fresh meta: not yet due
    assert rep["promoted"] == []
    monkeypatch.setattr(sweep, "PENDING_META_AGE_S", 0)
    rep = sweep.sweep()
    assert [p["verdict"] for p in rep["promoted"]] == ["primary"]
    rows = vault.query("2401.00001", "zh", "-")
    assert rows[0]["zone"] == "primary"
    assert rows[0]["verdict"] == "primary"


@pytest.mark.usefixtures("broot")
def test_sweep_pending_meta_alt_without_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _vault_src(tmp_path)
    vault.harvest("2401.00002", "zh", "-", {"zh": src}, source_run="adhoc/2026-09-20/x")
    monkeypatch.setattr(sweep, "PENDING_META_AGE_S", 0)
    rep = sweep.sweep()
    assert [p["verdict"] for p in rep["promoted"]] == ["alt"]
    rows = vault.query("2401.00002", "zh", "-")
    assert rows[0]["zone"] == "primary"
    assert rows[0]["verdict"] == "alt"


@pytest.mark.usefixtures("broot")
def test_sweep_pending_meta_failure_evidence_goes_quar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _vault_src(tmp_path)
    vault.harvest("2401.00013", "zh", "-", {"zh": src}, source_run="adhoc/2026-09-20/x")
    idx = index.Index()
    idx.apply_event(_cell_event("adhoc/2026-09-20/x", 1, "2401.00013", "fail"))
    idx.close()
    monkeypatch.setattr(sweep, "PENDING_META_AGE_S", 0)
    rep = sweep.sweep()
    assert [p["verdict"] for p in rep["promoted"]] == ["quar"]
    rows = vault.query("2401.00013", "zh", "-")
    assert rows[0]["zone"] == "quar"
    assert rows[0]["verdict"] == "quar"


@pytest.mark.usefixtures("broot")
def test_sweep_pending_meta_tombstones_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _vault_src(tmp_path)
    mpath = vault.harvest(
        "2401.00003", "zh", "-", {"zh": src}, source_run="adhoc/2026-09-20/x"
    )
    meta = json.loads(mpath.read_text())
    leaf = vault.leaf_dir("pending", "zh", "2401.00003", "zh", "-", meta["altseq"])
    # destroy the committed bytes — the abort evidence the tombstone owns
    for p in sorted(leaf.rglob("*"), reverse=True):
        p.chmod(0o644)
    leaf.chmod(0o755)
    shutil.rmtree(leaf)
    monkeypatch.setattr(sweep, "PENDING_META_AGE_S", 0)
    rep = sweep.sweep()
    assert rep["promoted"] == []
    assert rep["tombstoned"][0]["idc"] == "2401.00003"
    assert rep["tombstoned"][0]["reason"] == "pending_abort"
    tombs = _ledger_events("tombstone")
    assert any(t["idc"] == "2401.00003" for t in tombs)


@pytest.mark.usefixtures("broot")
def test_sweep_pending_meta_owned_by_active_run_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rd = runs.create_run("soak", slug="live", date="2026-09-21")
    rd.heartbeat_touch()
    src = _vault_src(tmp_path)
    vault.harvest("2401.00014", "zh", "-", {"zh": src}, source_run=rd.run)
    monkeypatch.setattr(sweep, "PENDING_META_AGE_S", 0)
    with rd.lock():  # fresh + locked = active
        rep = sweep.sweep()
    assert rep["promoted"] == []
    rows = vault.query("2401.00014", "zh", "-")
    assert rows[0]["zone"] == "pending"


# --- orphans ------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_sweep_meta_less_dir_adopted_then_report_only() -> None:
    sid = safe_id("2401.00004")
    leaf = paths.vault_dir() / "zh" / sid / "zh"
    leaf.mkdir(parents=True)
    (leaf / "b.bin").write_bytes(b"orphan bytes")
    old = time.time() - 7200
    os.utime(leaf, (old, old))

    rep = sweep.sweep()
    assert [a["idc"] for a in rep["adopted"]] == ["2401.00004"]
    assert leaf.exists()  # adopt never deletes
    rows = vault.query("2401.00004", "zh", "-")
    assert rows
    assert all(r["verdict"] == "quar" for r in rows)

    rep2 = sweep.sweep()
    assert rep2["adopted"] == []  # sibling meta now blocks
    assert rep2["meta_less"][0]["reason"] == "sibling_meta"


@pytest.mark.usefixtures("broot")
def test_sweep_young_meta_less_dir_report_only() -> None:
    sid = safe_id("2401.00005")
    leaf = paths.vault_dir() / "zh" / sid / "zh"
    leaf.mkdir(parents=True)
    (leaf / "b.bin").write_bytes(b"fresh")
    rep = sweep.sweep()
    assert rep["adopted"] == []
    assert rep["meta_less"][0]["reason"] == "young"


@pytest.mark.usefixtures("broot")
def test_sweep_lake_orphan_adopted_into_catalog() -> None:
    cell = paths.lake_corpus_dir() / "arxiv" / safe_id("2401.00006")
    (cell / "raw").mkdir(parents=True)
    (cell / "raw" / "payload.txt").write_text("payload")
    rep = sweep.sweep()
    assert rep["lake_orphans"][0]["idc"] == "2401.00006"
    cat = lake.LakeCatalog.load()
    assert cat.state("2401.00006") == "skeleton"
    assert cat.rows()["2401.00006"]["manifested"] is False


@pytest.mark.usefixtures("broot")
def test_sweep_lake_cataloged_dir_not_orphan() -> None:
    cell = paths.lake_corpus_dir() / "arxiv" / safe_id("2401.00015")
    (cell / "raw").mkdir(parents=True)
    cat = lake.LakeCatalog.load()
    cat.set("2401.00015", "hydrated", source="arxiv")
    rep = sweep.sweep()
    assert rep["lake_orphans"] == []


# --- harvest-pending ------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_sweep_harvest_pending_flags_done_without_bytes() -> None:
    idx = index.Index()
    idx.apply_event(_claim_acquire("r/2026-09-20/x", 1, "2401.00007"))
    idx.apply_event(_cell_event("r/2026-09-20/x", 2, "2401.00007", "ok"))
    idx.close()
    rep = sweep.sweep()
    keys = [(h["idc"], h["arm"], h["variant"]) for h in rep["harvest_pending"]]
    assert keys == [("2401.00007", "zh", "-")]
    notes = _ledger_events("note")
    assert any("harvest-pending" in n["text"] for n in notes)


@pytest.mark.usefixtures("broot")
def test_sweep_harvest_pending_silent_when_bytes_ok(tmp_path: Path) -> None:
    src = _vault_src(tmp_path)
    vault.harvest("2401.00008", "zh", "-", {"zh": src}, source_run="adhoc/2026-09-20/x")
    idx = index.Index()
    idx.apply_event(_claim_acquire("r/2026-09-20/x", 1, "2401.00008"))
    idx.apply_event(_cell_event("r/2026-09-20/x", 2, "2401.00008", "ok"))
    idx.close()
    rep = sweep.sweep()
    assert rep["harvest_pending"] == []


@pytest.mark.usefixtures("broot")
def test_sweep_harvest_pending_silent_when_tombstoned() -> None:
    vault.tombstone("2401.00016", "zh", "-", "zh", reason="test")
    idx = index.Index()
    idx.apply_event(_claim_acquire("r/2026-09-20/x", 1, "2401.00016"))
    idx.apply_event(_cell_event("r/2026-09-20/x", 2, "2401.00016", "ok"))
    for _src, _off, ev in ledger.iter_all_events():
        if isinstance(ev, dict) and ev.get("type") == "tombstone":
            idx.apply_event(ev)
    idx.close()
    rep = sweep.sweep()
    assert rep["harvest_pending"] == []


# --- permafail tombstones -------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_sweep_permafail_tombstones_old_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idx = index.Index()
    idx.apply_event(_cell_event("r/2026-09-20/x", 1, "2401.00009", "fail"))
    idx.close()
    monkeypatch.setattr(sweep, "FAIL_TOMBSTONE_AGE_S", 0)
    rep = sweep.sweep()
    assert rep["tombstoned"][0]["idc"] == "2401.00009"
    assert rep["tombstoned"][0]["reason"].startswith("permafail:")
    tombs = _ledger_events("tombstone")
    assert any(t["idc"] == "2401.00009" and t["kind"] == "cell" for t in tombs)


@pytest.mark.usefixtures("broot")
def test_sweep_permafail_skips_redeemed_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    idx = index.Index()
    idx.apply_event(_cell_event("r/2026-09-20/x", 1, "2401.00010", "fail"))
    idx.apply_event(_cell_event("r/2026-09-20/y", 2, "2401.00010", "ok"))
    idx.close()
    monkeypatch.setattr(sweep, "FAIL_TOMBSTONE_AGE_S", 0)
    rep = sweep.sweep()
    assert rep["tombstoned"] == []


@pytest.mark.usefixtures("broot")
def test_sweep_permafail_skips_young_failures() -> None:
    idx = index.Index()
    idx.apply_event(_cell_event("r/2026-09-20/x", 1, "2401.00017", "fail"))
    idx.close()
    rep = sweep.sweep()  # default 7d age gate
    assert rep["tombstoned"] == []


@pytest.mark.usefixtures("broot")
def test_sweep_permafail_regen_gate_not_an_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idx = index.Index()
    idx.apply_event(
        events.make_event(
            events.T_CELL,
            run="r/2026-09-20/x",
            seq=1,
            id="2401.00018",
            idc="2401.00018",
            arm="zh",
            up="-",
            variant="-",
            stage="xlat",
            status="dedup",
            cat="regen_gate",
        )
    )
    idx.close()
    monkeypatch.setattr(sweep, "FAIL_TOMBSTONE_AGE_S", 0)
    rep = sweep.sweep()
    assert rep["tombstoned"] == []


# --- duty 6: ledger seal ------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_sweep_full_pass_seals_aged_tail() -> None:
    """The full pass is the §3.10.5 driver — an over-age tail rotates into
    sealed/ and the hot tail is recreated empty."""
    old = events.make_event(
        events.T_NOTE,
        run="r",
        seq=1,
        text="old",
        level="info",
        ts=time.time() - 40 * 86400,
    )
    ledger.emit(old)

    rep = sweep.sweep(light=True)
    assert rep["sealed"] == []  # light pass never seals
    assert paths.events_path().stat().st_size > 0

    rep = sweep.sweep()
    assert len(rep["sealed"]) == 1
    zst = paths.sealed_dir() / rep["sealed"][0]
    assert zst.exists()
    # fresh seal — the raw survives the same pass's gc on age alone
    assert Path(str(zst)[: -len(".zst")]).exists()
    assert rep["seal_gc"] == []
    assert paths.events_path().exists()
    assert paths.events_path().stat().st_size == 0


@pytest.mark.usefixtures("broot")
def test_sweep_seal_gc_requires_index_replay() -> None:
    """seal_gc's watermark leg is Index.sealed_done(): a verified, aged raw
    segment is deleted only once the index reports it replayed — and with
    no index open at all nothing is deletable."""
    ledger.emit(
        events.make_event(
            events.T_NOTE,
            run="r",
            seq=1,
            text="old",
            level="info",
            ts=time.time() - 40 * 86400,
        )
    )
    # pre-age the seals row so age + zst-verification both pass and only
    # the watermark leg decides
    aged = time.time() - 8 * 86400
    zst = ledger.seal_if_needed(now_ts=aged, max_bytes=1)
    assert zst is not None
    raw = Path(str(zst)[: -len(".zst")])
    assert raw.exists()

    # no index.db → _open_index() returns None → ingested=set() → kept
    rep = sweep.sweep()
    assert rep["seal_gc"] == []
    assert raw.exists()

    # replay the segment into the index — the next sweep may delete
    idx = index.Index()
    try:
        idx.tail_ingest()
        assert raw.name in idx.sealed_done()
    finally:
        idx.close()
    rep = sweep.sweep()
    assert rep["seal_gc"] == [raw.name]
    assert not raw.exists()
    assert zst.exists()  # the compressed anchor survives gc
