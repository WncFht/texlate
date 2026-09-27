"""Tests for kernel/doctor.py — the assert surface (health checks, the
§3.10.9 switch-ok drain gate, fix-mode safe repairs) and fsck.

Every test runs against an isolated $TEXLATE_BENCH_ROOT via `broot`.
TEXLATE_REPO_BENCH redirects the stray-dir scan at a fake repo bench dir so
the real checkout's contents can never flake a test.
"""

from __future__ import annotations

from pathlib import Path

from kernel import doctor, events, index, lake, ledger, locks, paths, runs, vault


def _check(rep: dict, name: str) -> dict:
    return next(c for c in rep["checks"] if c["name"] == name)


def _names(rep: dict) -> set:
    return {c["name"] for c in rep["checks"]}


def _fake_bench(tmp_path: Path, entries=()) -> Path:
    rb = tmp_path / "repo-bench"
    for e in entries:
        (rb / e).mkdir(parents=True, exist_ok=True)
    rb.mkdir(parents=True, exist_ok=True)
    return rb


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


# --- green path -------------------------------------------------------------------


def test_doctor_clean_root_all_green(broot: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(
        "TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path, ("py", "corpus")))
    )
    rep = doctor.doctor()
    assert rep["ok"] is True, rep["checks"]
    assert _names(rep) == {
        "layout",
        "root_location",
        "stray_dirs",
        "lock_invariants",
        "ledger",
        "index",
        "paid",
        "capacity",
        "cache",
        "queues",
    }
    # root_location is warn-only — it can never gate (test roots live
    # inside the checkout by design)
    assert _check(rep, "root_location")["ok"] is True
    assert "reconciled" in _check(rep, "paid")["detail"]


# --- individual failure detectors ------------------------------------------------


def test_doctor_missing_sentinel_fails_layout(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    paths.vault_sentinel_path().unlink()
    rep = doctor.doctor()
    assert _check(rep, "layout")["ok"] is False
    assert "sentinel" in _check(rep, "layout")["detail"]
    assert rep["ok"] is False


def test_doctor_seqfile_divergence_fails(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    runs.create_run("soak", slug="s1", date="2026-09-21")  # seqfile -> 1
    paths.seqfile_path().write_text("99\n")
    rep = doctor.doctor()
    c = _check(rep, "ledger")
    assert c["ok"] is False and "divergence" in c["detail"]


def test_doctor_unparseable_ledger_line_fails(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    with open(paths.events_path(), "a", encoding="utf-8") as f:
        f.write("{not json}\n")
    rep = doctor.doctor()
    c = _check(rep, "ledger")
    assert c["ok"] is False and "unparseable" in c["detail"]


def test_doctor_dirty_index_fails_index_and_paid(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    idx = index.Index()
    idx.note_dirty("test trip")
    idx.close()
    rep = doctor.doctor()
    assert _check(rep, "index")["ok"] is False
    assert ".index-dirty" in _check(rep, "index")["detail"]
    # §3.10.6 ③ fail-closed: paid reconciliation refuses a dirty index
    assert _check(rep, "paid")["ok"] is False


def test_doctor_index_lag_warns_but_passes(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    ledger.emit(
        events.make_event(events.T_NOTE, run="x", seq=None, text="hi", level="info")
    )
    idx = index.Index()  # fresh: watermark 0, ledger >0
    idx.close()
    rep = doctor.doctor()
    c = _check(rep, "index")
    assert c["ok"] is True and "behind" in c["detail"]


def test_doctor_run_lock_unlinked_fails(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    rd = runs.create_run("soak", slug="s1", date="2026-09-21")
    (rd.path / ".lock").unlink()  # immortal lock violated
    rep = doctor.doctor()
    c = _check(rep, "lock_invariants")
    assert c["ok"] is False and ".lock" in c["detail"]


def test_doctor_stale_claim_flagged_then_fix_reaps(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    idx = index.Index()
    idx.apply_event(_claim_acquire("r/2026-09-20/gone", 1, "2401.00020"))
    idx.close()
    rep = doctor.doctor()
    c = _check(rep, "lock_invariants")
    assert c["ok"] is False and "held-by-dead" in c["detail"]

    rep2 = doctor.doctor(fix=True)
    assert any("reaped 1" in f for f in rep2["fixed"])
    reaps = [
        e
        for _ln, e, _raw in events.iter_jsonl(paths.events_path())
        if isinstance(e, dict) and e.get("type") == "claim" and e.get("op") == "reap"
    ]
    assert len(reaps) == 1 and reaps[0]["idc"] == "2401.00020"


# --- stray dirs (report, never delete) ----------------------------------------------


def test_doctor_stray_dir_detected_never_deleted(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    rb = _fake_bench(tmp_path, ("results", "py"))
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(rb))
    rep = doctor.doctor()
    c = _check(rep, "stray_dirs")
    assert c["ok"] is False and "results" in c["detail"]
    assert (rb / "results").is_dir()  # reported, not deleted


def test_doctor_stray_unknown_dir_reviewed_not_failed(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    rb = _fake_bench(tmp_path, ("mystery",))
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(rb))
    rep = doctor.doctor()
    c = _check(rep, "stray_dirs")
    assert c["ok"] is True and "mystery" in c["detail"]


# --- paid reconciliation (§3.10.6 ⑤) ----------------------------------------------


def test_doctor_paid_ok_cell_without_bytes_fails(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    ledger.emit(_claim_acquire("r/2026-09-20/x", 1, "2401.00021"))
    ledger.emit(_cell_event("r/2026-09-20/x", 2, "2401.00021", "ok"))
    rep = doctor.doctor()
    c = _check(rep, "paid")
    assert c["ok"] is False and "without manifest bytes" in c["detail"]


def test_doctor_paid_reconciles_after_harvest(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    ledger.emit(_claim_acquire("r/2026-09-20/x", 1, "2401.00022"))
    ledger.emit(_cell_event("r/2026-09-20/x", 2, "2401.00022", "ok"))
    assert _check(doctor.doctor(), "paid")["ok"] is False
    src = tmp_path / "src" / "zh.mock"
    src.mkdir(parents=True)
    (src / "o.txt").write_text("bytes")
    vault.harvest("2401.00022", "zh", "-", {"zh": src}, source_run="r/2026-09-20/x")
    rep = doctor.doctor()
    assert _check(rep, "paid")["ok"] is True


def test_doctor_paid_unpaid_bytes_is_bypass_alarm(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    """Manifest bytes with no claim-gated paid-ok cell → the alarm leg."""
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    src = tmp_path / "src" / "zh.mock"
    src.mkdir(parents=True)
    (src / "o.txt").write_text("bytes")
    vault.harvest("2401.00023", "zh", "-", {"zh": src})
    rep = doctor.doctor()
    c = _check(rep, "paid")
    assert c["ok"] is False and "bypass" in c["detail"]


# --- switch-ok (§3.10.9 drain gate) ----------------------------------------------


def test_doctor_switch_ok_blocked_while_kernel_held(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    monkeypatch.setattr(doctor, "_repo_root", lambda: tmp_path)
    with locks.kernel_active_hold():
        rep = doctor.doctor(switch_ok=True)
    c = _check(rep, "switch_ok")
    assert c["ok"] is False and "kernel-active" in c["detail"]
    assert rep["ok"] is False


def test_doctor_switch_ok_clear_when_idle(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    monkeypatch.setattr(doctor, "_repo_root", lambda: tmp_path)
    rep = doctor.doctor(switch_ok=True)
    c = _check(rep, "switch_ok")
    assert c["ok"] is True and c["detail"] == "SWITCH-OK"
    assert rep["ok"] is True


def test_doctor_switch_ok_blocked_by_active_run(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    monkeypatch.setattr(doctor, "_repo_root", lambda: tmp_path)
    rd = runs.create_run("soak", slug="live", date="2026-09-21")
    rd.heartbeat_touch()
    with rd.lock():  # fresh + locked = active
        rep = doctor.doctor(switch_ok=True)
    c = _check(rep, "switch_ok")
    assert c["ok"] is False and "active runs" in c["detail"]


def test_doctor_switch_ok_blocked_by_live_lane(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    monkeypatch.setattr(doctor, "_repo_root", lambda: tmp_path)
    lane = tmp_path / "tmp" / "lane-soaktest"
    lane.mkdir(parents=True)
    (lane / "heartbeat").touch()  # fresh heartbeat = live writer
    rep = doctor.doctor(switch_ok=True)
    c = _check(rep, "switch_ok")
    assert c["ok"] is False and "lane" in c["detail"]


def test_doctor_switch_ok_blocked_by_pause(
    broot: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(_fake_bench(tmp_path)))
    monkeypatch.setattr(doctor, "_repo_root", lambda: tmp_path)
    paths.pause_path().touch()
    rep = doctor.doctor(switch_ok=True)
    c = _check(rep, "switch_ok")
    assert c["ok"] is False and "PAUSE" in c["detail"]


# --- fsck ----------------------------------------------------------------------------


def test_fsck_clean_root(broot: Path) -> None:
    rep = doctor.fsck()
    assert rep["ok"] is True, rep["checks"]
    assert "vault_stat" in _names(rep) and "lake_catalog" in _names(rep)
    assert "claims_locks" in _names(rep) and "from_run_edges" in _names(rep)


def test_fsck_meta_less_dir_warns_not_fails(broot: Path) -> None:
    leaf = paths.vault_dir() / "zh" / "2401.00024" / "zh"
    leaf.mkdir(parents=True)
    (leaf / "b.bin").write_bytes(b"orphan")
    rep = doctor.fsck()
    c = _check(rep, "vault_stat")
    assert c["ok"] is True and "meta-less" in c["detail"]


def test_fsck_dirless_catalog_row_fails(broot: Path) -> None:
    cat = lake.LakeCatalog.load()
    cat.set("2401.00025", "hydrated", source="arxiv")
    rep = doctor.fsck()
    c = _check(rep, "lake_catalog")
    assert c["ok"] is False and "2401.00025" in c["detail"]
    assert rep["ok"] is False


def test_fsck_dangling_from_run_edge_fails(broot: Path) -> None:
    rd = runs.create_run("soak", slug="edge", date="2026-09-21")
    runs.freeze_plan(
        rd,
        [
            {
                "id": "2401.00026",
                "idc": "2401.00026",
                "arm": "zh",
                "up": "-",
                "variant": "-",
                "stage": "xlat",
                "needs": [
                    {"run": "ghost/2026-01-01/x", "idc": "2401.00027", "stage": "xlat"}
                ],
                "fp_input": None,
            }
        ],
    )
    rep = doctor.fsck()
    c = _check(rep, "from_run_edges")
    assert c["ok"] is False and "ghost/2026-01-01/x" in c["detail"]
    # defer_edges skips the leg entirely
    rep2 = doctor.fsck(defer_edges=True)
    assert "from_run_edges" not in _names(rep2)


def test_fsck_stale_claim_fails_claims_locks(broot: Path) -> None:
    idx = index.Index()
    idx.apply_event(_claim_acquire("r/2026-09-20/gone", 1, "2401.00028"))
    idx.close()
    rep = doctor.fsck()
    c = _check(rep, "claims_locks")
    assert c["ok"] is False and "2401.00028" in c["detail"]
