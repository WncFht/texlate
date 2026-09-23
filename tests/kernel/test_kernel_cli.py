"""Tests for kernel/cli.py — the bench command surface (§2.1).

Wave-C sibling modules (kernel.kernel / kernel.spec / kernel.sweep /
kernel.doctor) are faked through sys.modules for dispatch tests; tests
that need the real implementation are guarded by find_spec and activate
automatically once those modules land.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import types
from pathlib import Path

import pytest
from kernel import cli, events, ledger, locks, paths, runs

REPO = Path(__file__).resolve().parents[2]
BENCH_PY = REPO / "bench" / "py"


def _have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError, AttributeError):
        return False


HAS_KERNEL = _have("kernel.kernel")
HAS_SPEC = _have("kernel.spec")
HAS_SWEEP = _have("kernel.sweep")


def _fake(name: str, **attrs: object) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


def _cell(idc: str, stage: str = "xlat") -> dict:
    return {
        "id": idc, "idc": idc, "arm": "a", "up": "-", "variant": "-",
        "stage": stage, "needs": [], "fp_input": None,
    }


def _emit(rd: runs.RunDir, seq: int, idc: str, status: str | None = None) -> dict:
    if status is None:
        ev = events.make_event(
            events.T_CELL_QUEUED, run=rd.run, seq=seq, id=idc, idc=idc,
            arm="a", up="-", variant="-", stage="xlat",
        )
    else:
        ev = events.make_event(
            events.T_CELL, run=rd.run, seq=seq, id=idc, idc=idc,
            arm="a", up="-", variant="-", stage="xlat", status=status,
        )
    ledger.emit(ev, run_dir=rd.path)
    return ev


# --- init / spec list / stubs ------------------------------------------------------


def test_init_creates_layout(broot: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["init"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "bench root" in out
    for p in (
        paths.ledger_dir(), paths.runs_dir(), paths.vault_dir(),
        paths.lake_dir(), paths.locks_dir(), paths.backup_dir(),
    ):
        assert p.is_dir()
    assert paths.events_path().exists()
    assert paths.seqfile_path().exists()


def test_spec_list_finds_specs(broot: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["spec", "list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "smoke.py" in out
    assert "kind=smoke" in out
    assert "paid_stub.py" in out
    assert "kind=paid_stub" in out


@pytest.mark.parametrize("name", ["triage", "gate", "dossier"])
def test_verbs_bare_invocation_exit_2(broot: Path, capsys: pytest.CaptureFixture, name: str) -> None:
    """verbs landed under bench/py/verbs/ — bare invocation is a usage refusal.

    triage's required ``run`` positional exits via argparse ``SystemExit(2)``;
    gate/dossier refuse inside ``main()`` with ``EXIT_REFUSED``.
    """
    if name == "triage":
        with pytest.raises(SystemExit) as exc:
            cli.main([name])
        assert exc.value.code == cli.EXIT_REFUSED
    else:
        assert cli.main([name]) == cli.EXIT_REFUSED
    assert capsys.readouterr().err


# --- status ------------------------------------------------------------------------


def test_status_empty_root(broot: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["status"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "runs: 0" in out


def test_status_tail_and_run_and_id(broot: Path, capsys: pytest.CaptureFixture) -> None:
    rd = runs.create_run("soak", date="2026-09-21",
                         spec_dict={"kind": "soak"})
    _emit(rd, 1, "9901.00001")
    _emit(rd, 2, "9901.00001", status="ok")

    assert cli.main(["status", "--tail", "1"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "cell" in out
    assert "status=ok" in out

    assert cli.main(["status", "--run", rd.run]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert rd.run in out
    assert "9901.00001" in out
    assert "xlat" in out

    assert cli.main(["status", "--id", "9901.00001"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "idc: 9901.00001" in out
    assert "xlat" in out


def test_status_id_canon_invalid_still_ok(broot: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["status", "--id", "smoke/0001"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "canon" in out  # non-ok canon verdict surfaced, not hidden


# --- vault -------------------------------------------------------------------------


def test_vault_verify_empty_ok(broot: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["vault", "verify", "--level", "stat"]) == cli.EXIT_OK
    assert "metas=0" in capsys.readouterr().out


def test_vault_adopt_and_tombstone(broot: Path, tmp_path: Path) -> None:
    donor = tmp_path / "orphan-bytes"
    donor.mkdir()
    (donor / "out.pdf").write_bytes(b"orphan pdf")
    assert cli.main([
        "vault", "adopt", str(donor), "--idc", "9901.00001",
    ]) == cli.EXIT_OK
    # the orphan bytes became a declared quar-zone copy inside the vault
    assert any(paths.vault_dir().rglob("out.pdf"))

    assert cli.main([
        "vault", "tombstone", "9901.00002", "--arm", "a",
        "--kind", "zh", "--reason", "lost in test",
    ]) == cli.EXIT_OK


def test_vault_restore_empty_fails(broot: Path, tmp_path: Path) -> None:
    rc = cli.main([
        "vault", "restore", "9901.00001", "--arm", "a",
        "--dest", str(tmp_path / "restored"),
    ])
    assert rc == cli.EXIT_FAIL


# --- ledger -------------------------------------------------------------------------


def test_ledger_tail_ingest_and_rebuild(broot: Path, capsys: pytest.CaptureFixture) -> None:
    rd = runs.create_run("soak", date="2026-09-21",
                         spec_dict={"kind": "soak"})
    _emit(rd, 1, "9901.00001")
    _emit(rd, 2, "9901.00001", status="ok")

    assert cli.main(["ledger", "tail-ingest"]) == cli.EXIT_OK
    assert "applied=" in capsys.readouterr().out

    assert cli.main(["ledger", "rebuild-index"]) == cli.EXIT_OK
    assert "rebuild-index" in capsys.readouterr().out


def test_ledger_ingest_external_dry(broot: Path, tmp_path: Path,
                                  capsys: pytest.CaptureFixture) -> None:
    src = tmp_path / "ext.jsonl"
    src.write_text(
        json.dumps({"id": "9901.00001", "stage": "xlat",
                    "status": "ok"}) + "\n",
        encoding="utf-8",
    )
    assert cli.main([
        "ledger", "ingest", "--external", str(src), "--dry",
    ]) == cli.EXIT_OK
    assert capsys.readouterr().out.strip()  # stats json printed


def test_ledger_import_missing_path(broot: Path) -> None:
    assert cli.main(["ledger", "import", "no/such/file.jsonl"]) == cli.EXIT_REFUSED


# --- lake ----------------------------------------------------------------------------


def test_lake_status_register_evict(broot: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["lake", "status"]) == cli.EXIT_OK
    assert "cells=" in capsys.readouterr().out

    assert cli.main(["lake", "register", "9901.00001"]) == cli.EXIT_OK
    assert "9901.00001" in capsys.readouterr().out

    # canon-invalid ids are refused, not silently skeleton'd
    assert cli.main(["lake", "register", "smoke/0001"]) == cli.EXIT_FAIL

    assert cli.main(["lake", "evict", "--to-free", "1K"]) == cli.EXIT_OK


# --- backup / prune -------------------------------------------------------------------


def test_backup_writes_tar_without_index(broot: Path, capsys: pytest.CaptureFixture) -> None:
    rd = runs.create_run("soak", date="2026-09-21",
                         spec_dict={"kind": "soak"})
    _emit(rd, 1, "9901.00001")

    assert cli.main(["backup"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "backup:" in out
    assert "payload" in out
    tars = list(paths.backup_dir().glob("bench-backup-*.tar"))
    assert len(tars) == 1
    with tarfile.open(tars[0]) as tf:
        names = tf.getnames()
    assert any(n.endswith("ledger/events.jsonl") for n in names)
    assert not any("index.sqlite" in n for n in names)


def test_prune_keeps_list_and_cell_trees(broot: Path) -> None:
    rd = runs.create_run("soak", date="2026-09-21",
                         spec_dict={"kind": "soak"})
    (rd.path / "report.md").write_text("# report\n")
    (rd.path / "junk.tmp").write_text("junk")
    cell = rd.work("9901.00001")
    (cell / "src").mkdir(parents=True)
    (cell / "src" / "main.tex").write_text("\\hi")

    assert cli.main([
        "prune", "--run", rd.run, "--keep", "report,events",
    ]) == cli.EXIT_OK
    assert (rd.path / "report.md").exists()
    assert (rd.path / "events.jsonl").exists()
    assert (rd.path / ".lock").exists()       # immortal lock file
    assert (rd.path / "heartbeat").exists()
    assert not (rd.path / "junk.tmp").exists()
    assert not cell.exists()
    assert not (rd.path / "spec.json").exists()  # not in keep-list
    assert not (rd.path / "work").exists()


def test_prune_blocks_paid_shaped_cell(broot: Path) -> None:
    rd = runs.create_run("soak", date="2026-09-21",
                         spec_dict={"kind": "soak"})
    cell = rd.work("9901.00002")
    (cell / "zh.mock").mkdir(parents=True)
    (cell / "zh.mock" / "out.pdf").write_bytes(b"paid bytes")

    rc = cli.main(["prune", "--run", rd.run, "--keep", "events"])
    assert rc == cli.EXIT_FAIL
    assert cell.exists()  # unharvested paid bytes survive the prune


def test_prune_unknown_keep_token(broot: Path) -> None:
    rd = runs.create_run("soak", date="2026-09-21",
                         spec_dict={"kind": "soak"})
    assert cli.main([
        "prune", "--run", rd.run, "--keep", "nonsense",
    ]) == cli.EXIT_REFUSED


# --- doctor / fsck / sweep --------------------------------------------------------------


def test_doctor_clean_root(broot: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                           capsys: pytest.CaptureFixture) -> None:
    # the real doctor's stray scan targets the repo checkout — point it at
    # an empty stand-in so the verdict reflects the clean tmp root only
    empty_bench = tmp_path / "repo-bench"
    empty_bench.mkdir()
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(empty_bench))
    assert cli.main(["doctor"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "[ok]" in out
    assert "[FAIL]" not in out


def test_doctor_switch_ok_reports_verdict(broot: Path, tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    # drain verdict depends on live repo state (lane writers, errsweep
    # worktrees, kernel-active) — the CLI must faithfully report whichever
    # verdict the gate returns; both spellings are correct plumbing
    empty_bench = tmp_path / "repo-bench"
    empty_bench.mkdir()
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(empty_bench))
    rc = cli.main(["doctor", "--switch-ok"])
    out = capsys.readouterr().out
    assert rc in (cli.EXIT_OK, cli.EXIT_FAIL)
    assert "SWITCH-" in out


def test_fsck_clean_root(broot: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["fsck"]) == cli.EXIT_OK


def test_sweep_fake_module(broot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setitem(
        sys.modules, "kernel.sweep",
        _fake("kernel.sweep",
              sweep=lambda light=False: {"light": light, "zombies": 0}),
    )
    assert cli.main(["sweep", "--light"]) == cli.EXIT_OK
    assert '"zombies": 0' in capsys.readouterr().out


@pytest.mark.skipif(HAS_SWEEP, reason="kernel.sweep landed — real module used")
def test_sweep_unavailable_exit_2(broot: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["sweep"]) == cli.EXIT_REFUSED
    assert "unavailable" in capsys.readouterr().err


# --- run / plan dispatch ---------------------------------------------------------------


def test_run_dispatches_kernel_run(broot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    order: list[str] = []
    seen: dict = {}

    def fake_run(spec_or_path: str, params: dict | None = None, **kw: object) -> dict:
        order.append("run")
        seen["spec"] = spec_or_path
        seen["params"] = params
        seen["kw"] = kw
        return {"run": "smoke/2026-09-21/smoke", "run_seq": 1,
                "counts": {"ok": 9}, "cost_usd": 0.0, "ok": True}

    monkeypatch.setitem(
        sys.modules, "kernel.kernel",
        _fake("kernel.kernel", run=fake_run, plan=lambda *_a, **_k: {}),
    )
    monkeypatch.setitem(
        sys.modules, "kernel.sweep",
        _fake("kernel.sweep",
              sweep=lambda light=False: order.append("sweep")
              or {"light": light}),
    )
    rc = cli.main([
        "run", "smoke", "--param", "note=hi", "x=1",
        "--max-cost", "1.5", "--jobs", "2", "--resume",
    ])
    assert rc == 0
    assert order == ["sweep", "run"]          # §2.4: sweep before the write
    assert seen["params"] == {"note": "hi", "x": "1"}
    assert seen["spec"].endswith("specs/smoke.py")
    kw = seen["kw"]
    want_cost, want_jobs = 1.5, 2
    assert kw["max_cost"] == want_cost
    assert kw["jobs"] == want_jobs
    assert kw["resume"] is True
    assert '"ok": true' in capsys.readouterr().out


def test_run_not_ok_exit_1(broot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules, "kernel.kernel",
        _fake("kernel.kernel",
              run=lambda *_a, **_k: {"ok": False, "counts": {}}),
    )
    assert cli.main(["run", "smoke"]) == cli.EXIT_FAIL


def test_run_bad_param_refused(broot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules, "kernel.kernel",
        _fake("kernel.kernel", run=lambda *_a, **_k: {"ok": True}),
    )
    assert cli.main(["run", "smoke", "notkv"]) == cli.EXIT_REFUSED


def test_run_unknown_spec(broot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules, "kernel.kernel",
        _fake("kernel.kernel", run=lambda *_a, **_k: {"ok": True}),
    )
    assert cli.main(["run", "no-such-spec-xyz"]) == cli.EXIT_REFUSED


@pytest.mark.skipif(HAS_KERNEL, reason="kernel.kernel landed — real path runs")
def test_run_unavailable_exit_2(broot: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["run", "smoke"]) == cli.EXIT_REFUSED
    assert "unavailable" in capsys.readouterr().err


def test_plan_prints_buckets(broot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    def fake_plan(spec_or_path: str, params: dict | None = None, **kw: object) -> dict:
        return {
            "quote": {
                "new": 3, "reuse": 1, "missing": 1, "claimed": 0,
                "attempted": 0, "unsealed": 0, "total": 5,
                "regen_decisions": ["9901.00002: missing bytes"],
            },
            "cells": [{"id": "9901.00001"}, {"id": "9901.00002"}],
        }

    monkeypatch.setitem(
        sys.modules, "kernel.kernel",
        _fake("kernel.kernel", plan=fake_plan),
    )
    assert cli.main(["plan", "smoke"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    for bucket in ("new", "reuse", "missing", "claimed", "attempted"):
        assert bucket in out
    assert "regen decision" in out
    assert "would run: 2" in out


def test_pause_refuses_paid_run_only(broot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """PAUSE is a paid-spend fence (§6 Phase-3 rescope): paid specs refuse,
    free specs and plan run straight through."""
    called = []
    monkeypatch.setitem(
        sys.modules, "kernel.kernel",
        _fake("kernel.kernel",
              run=lambda *_a, **_k: called.append("run") or {"ok": True},
              plan=lambda *_a, **_k: called.append("plan") or {}),
    )
    paths.pause_path().write_text("stop the world\n")
    assert locks.pause_engaged()
    # plan is never refused — it produces the first-fire coverage report
    assert cli.main(["plan", "smoke"]) == cli.EXIT_OK
    # a free spec runs straight through the fence
    assert cli.main(["run", "smoke"]) == cli.EXIT_OK
    assert called == ["plan", "run"]
    # a paid spec refuses BEFORE dispatch — nothing executes under PAUSE
    assert cli.main(["run", "paid_stub"]) == cli.EXIT_REFUSED
    assert called == ["plan", "run"]
    assert "PAUSE" in capsys.readouterr().err


def test_pause_fails_closed_on_unprovable_spec(broot: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """paidness=None (spec won't even load) is refused under PAUSE."""
    called = []
    monkeypatch.setitem(
        sys.modules, "kernel.kernel",
        _fake("kernel.kernel",
              run=lambda *_a, **_k: called.append("run") or {"ok": True}),
    )
    broken = broot / "broken_spec.py"
    broken.write_text("raise RuntimeError('import-time boom')\n")
    paths.pause_path().touch()
    assert cli.main(["run", str(broken)]) == cli.EXIT_REFUSED
    assert called == []
    assert "PAUSE" in capsys.readouterr().err


# --- detach -----------------------------------------------------------------------------


def test_detach_paid_spec_requires_max_cost(broot: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setitem(
        sys.modules, "kernel.kernel",
        _fake("kernel.kernel", run=lambda *_a, **_k: {"ok": True}),
    )
    paid_spec = types.SimpleNamespace(
        stages=[types.SimpleNamespace(paid=True)])
    monkeypatch.setitem(
        sys.modules, "kernel.spec",
        _fake("kernel.spec", load_spec=lambda _p: paid_spec),
    )
    spawned = []
    monkeypatch.setattr(
        locks, "detach_with_lock",
        lambda *_a, **_k: spawned.append((_a, _k)) or types.SimpleNamespace(
            pid=4242),
    )
    # §3.6: detach on a paid spec without --max-cost is refused pre-spawn
    assert cli.main(["run", "smoke", "--detach"]) == cli.EXIT_REFUSED
    assert spawned == []
    assert "--max-cost" in capsys.readouterr().err

    assert cli.main(["run", "smoke", "--detach", "--max-cost", "5"]) == cli.EXIT_OK
    assert len(spawned) == 1
    argv = spawned[0][0][0]
    assert "--detach" not in argv           # child re-execs without the flag
    assert "--max-cost" in argv
    assert "detached: pid=4242" in capsys.readouterr().out


# --- derive ---------------------------------------------------------------------


def test_derive_balanced_run(broot: Path, capsys: pytest.CaptureFixture) -> None:
    rd = runs.create_run("soak", date="2026-09-21",
                         spec_dict={"kind": "soak"})
    runs.freeze_plan(rd, [_cell("9901.00001")])
    _emit(rd, 1, "9901.00001")
    _emit(rd, 2, "9901.00001", status="ok")

    assert cli.main(["derive", "--run", rd.run]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "ok=True" in out
    assert "derived:" in out
    proj = rd.derived() / "projected"
    assert (proj / "report.md").is_file()
    assert (proj / "cells.jsonl").is_file()
    assert (proj / "cases.jsonl").is_file()


def test_derive_unknown_run(broot: Path) -> None:
    assert cli.main(["derive", "--run", "nope/2026-01-01/none"]) == cli.EXIT_REFUSED


# --- entry points ------------------------------------------------------------------------


def _sub_env(root: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BENCH_PY)
    env[paths.ENV_ROOT] = str(root)
    return env


def test_python_dash_m_kernel(broot: Path, tmp_path: Path) -> None:
    other = tmp_path / "subroot"
    res = subprocess.run(
        [sys.executable, "-m", "kernel", "init"],
        env=_sub_env(other), capture_output=True, text=True, timeout=60, check=False,
    )
    assert res.returncode == cli.EXIT_OK, res.stderr
    assert (other / "ledger").is_dir()


def test_bench_shim_executable(broot: Path, tmp_path: Path) -> None:
    shim = BENCH_PY / "bench"
    assert shim.is_file()
    assert os.access(shim, os.X_OK)
    assert shim.read_bytes().startswith(b"#!/usr/bin/env python3")
    other = tmp_path / "shimroot"
    res = subprocess.run(  # noqa: S603 — argv is a constructed list, no shell
        [str(shim), "init"], env=_sub_env(other),
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert res.returncode == cli.EXIT_OK, res.stderr
    assert (other / "ledger").is_dir()


# --- conditional end-to-end (activates when wave-C siblings land) --------------------------


@pytest.mark.skipif(not (HAS_KERNEL and HAS_SPEC),
                    reason="kernel.kernel/kernel.spec not yet landed")
def test_smoke_spec_end_to_end(broot: Path, capsys: pytest.CaptureFixture) -> None:
    spec_path = BENCH_PY / "specs" / "smoke.py"
    rc = cli.main(["run", str(spec_path)])
    out = capsys.readouterr().out
    assert rc == cli.EXIT_OK, out
    # the full event trail exists in the ledger
    evs = [e for _ln, e, _raw in events.iter_jsonl(paths.events_path())
           if e is not None]
    types_seen = {e["type"] for e in evs}
    assert "run_registered" in types_seen
    assert "cell_queued" in types_seen
    assert "cell" in types_seen
    # status reports the cells
    assert cli.main(["status", "--tail", "5"]) == cli.EXIT_OK
    assert "9901.0000" in capsys.readouterr().out
