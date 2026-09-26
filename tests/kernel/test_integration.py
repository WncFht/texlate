"""End-to-end integration proof — the ten-scenario contract (Wave D).

Runs the SHIPPED specs (bench/py/specs/smoke.py, paid_stub.py) through the
kernel plus the ``bench`` CLI subprocess surface. Assertions encode the
design contract (docs/spec/bench-trizone.md §3.x), not observed
behavior — blocks tagged CONTRACT-VIOLATION pin defects the current kernel
gets wrong and are expected to fail until the kernel is fixed.

Layout order puts the fully-green scenarios first so ``pytest -x`` covers
maximum contract surface before the first defect demonstration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import write_verify_stamp
from kernel import (
    doctor,
    events,
    index as indexmod,
    kernel,
    ledger,
    locks,
    paid,
    paths,
    report,
    runs,
    spec as specmod,
    vault,
)

BENCH_PY = Path(__file__).resolve().parents[2] / "bench" / "py"
SMOKE_SPEC = BENCH_PY / "specs" / "smoke.py"
PAID_SPEC = BENCH_PY / "specs" / "paid_stub.py"
SHIM = BENCH_PY / "bench"

DATE = "2026-09-22"
SMOKE_IDS = ("9901.00001", "9901.00002", "9901.00003")
# paid_stub items are (id, arm, up, variant) with arm='a'
PAID_IDS = ("9901.00001", "9901.00002")
PAID_KEYS = sorted((("9901.00001", "a", "-"), ("9901.00002", "a", "-")))


# --- helpers -------------------------------------------------------------------


def _quiet(**kw):
    kw.setdefault("emit", lambda *a, **k: None)
    return kw


def _shard(rd) -> list[dict]:
    return [
        e for _ln, e, _raw in events.iter_jsonl(rd.events_path()) if isinstance(e, dict)
    ]


def _typed(rd, etype: str) -> list[dict]:
    return [e for e in _shard(rd) if e.get("type") == etype]


def _cells(rd, stage: str | None = None) -> list[dict]:
    return [
        e for e in _typed(rd, events.T_CELL) if stage is None or e.get("stage") == stage
    ]


def _cell(rd, idc: str, stage: str) -> dict | None:
    rows = [e for e in _cells(rd, stage) if e.get("idc") == idc]
    return rows[-1] if rows else None


class _FakeClient:
    """Gateway client double — counts chat() calls, thread-safe.

    paid_stub's xlat calls ``gw.request("chat", model=..., messages=...)``
    which lands on ``client.chat(model=..., messages=...)``.
    """

    def __init__(self, latency_s: float = 0.0):
        self.calls = 0
        self.latency_s = latency_s
        self._lock = threading.Lock()

    def chat(self, model=None, messages=None, **_kw):
        if self.latency_s:
            time.sleep(self.latency_s)  # held inside claim + paid_slot
        with self._lock:
            self.calls += 1
        return {"usage": {"in_tok": 100, "out_tok": 50}, "text": "ok"}


def _factory(client, counter: list | None = None) -> paid.GatewayFactory:
    """GatewayFactory over a client double; counter[0] tracks client builds."""

    def make(_ctx=None):
        if counter is not None:
            counter[0] += 1
        return client

    return paid.GatewayFactory(make, prices={"in": 1e-6, "out": 2e-6})


def _switch_root(monkeypatch, root: Path) -> Path:
    """Point the whole zone at a second isolated root (paths read env live)."""
    monkeypatch.setenv(paths.ENV_ROOT, str(root))
    paths.ensure_layout()
    write_verify_stamp()
    return root


# --- scenario 1: smoke spec end to end ------------------------------------------


def test_s01_smoke_spec_end_to_end(broot, tmp_path):
    """spec load -> plan -> queued/started/terminal per cell -> accounting
    ok -> export --legacy records/{stage}.jsonl matching the cells."""
    res = kernel.run(str(SMOKE_SPEC), date=DATE, slug="s1", **_quiet())
    assert res["ok"] is True
    assert res["cells"] == 9  # 3 ids x 3 stages
    assert res["counts"].get("ok") == 9
    assert res["accounting"]["ok"] is True

    rd = runs.load_run("smoke", DATE, "s1")
    types = [e["type"] for e in _shard(rd)]
    assert types.count("run_registered") == 1
    assert types.count("cell_queued") == 9
    assert types.count("cell_started") == 9
    assert types.count("cell") == 9
    assert all(e["status"] == "ok" for e in _cells(rd))
    assert "finished" in types
    acct = runs.accounting_check(rd)
    assert acct["ok"] is True and acct["terminal"] == 9

    # derive: native report projection -> cells.jsonl + report.md + cases.jsonl
    idx = indexmod.Index()
    try:
        idx.tail_ingest()
        out_dir = tmp_path / "derived"
        report.build_run_report(idx, res["run"], str(out_dir))
    finally:
        idx.close()
    cells_f = out_dir / "cells.jsonl"
    assert cells_f.is_file()
    rows = [
        json.loads(ln)
        for ln in cells_f.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(rows) == 9, f"cells.jsonl: {len(rows)} rows"
    for stage in ("ingest", "transform", "report"):
        stage_rows = [r for r in rows if r["stage"] == stage]
        assert len(stage_rows) == 3, f"{stage}: {len(stage_rows)} rows"
        assert {r["id"] for r in stage_rows} == set(SMOKE_IDS)
        assert all(r["status"] == "ok" for r in stage_rows)
    rep_rows = [r for r in rows if r["stage"] == "report"]
    assert all(r["metrics"].get("chars") for r in rep_rows)
    rep_md = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "status tally" in rep_md
    assert (out_dir / "cases.jsonl").is_file()


# --- scenario 2: resume is a done-set no-op --------------------------------------


def test_s02_resume_done_set(broot):
    """resume=True on a fully-terminal run queues and finishes zero cells."""
    r1 = kernel.run(str(SMOKE_SPEC), date=DATE, slug="rs", **_quiet())
    assert r1["ok"] is True
    rd = runs.load_run("smoke", DATE, "rs")
    n_queued = len(_typed(rd, events.T_CELL_QUEUED))
    n_terminal = len(_cells(rd))

    r2 = kernel.run(str(SMOKE_SPEC), resume=True, date=DATE, slug="rs", **_quiet())
    assert r2["ok"] is True
    # zero new ledger rows for cells — the shard is unchanged
    assert len(_typed(rd, events.T_CELL_QUEUED)) == n_queued
    assert len(_cells(rd)) == n_terminal
    # every cell short-circuited on this-run terminal state
    assert r2["counts"] == {"already-terminal": 9}
    # and the append-only shard keeps the equation balanced
    assert runs.accounting_check(rd)["ok"] is True


# --- scenario 7: concurrent double-run pays exactly once -------------------------


def test_s07_concurrent_double_run_single_payer(broot):
    """Two kernel.run invocations racing the same paid cells: the claim
    flock serializes them — exactly one acquire-winning sequence per paid
    key, total spend = one pass (no double burn)."""
    client = _FakeClient(latency_s=0.05)  # hold the claim through chat()
    results: dict[str, dict] = {}
    errors: list = []
    gate = threading.Barrier(3)

    def worker(slug):
        try:
            gate.wait(timeout=30)
            results[slug] = kernel.run(
                str(PAID_SPEC),
                date=DATE,
                slug=slug,
                max_cost=5.0,
                gateway_factory=_factory(client),
                jobs=2,
                **_quiet(),
            )
        except BaseException as exc:  # noqa: BLE001 - collected, asserted
            errors.append((slug, exc))

    threads = [
        threading.Thread(target=worker, args=(s,), daemon=True) for s in ("ccA", "ccB")
    ]
    for t in threads:
        t.start()
    gate.wait(timeout=30)
    for t in threads:
        t.join(timeout=120)
    assert all(not t.is_alive() for t in threads), "a kernel.run deadlocked"
    assert not errors, f"runner crashed: {errors!r}"
    assert set(results) == {"ccA", "ccB"}

    rd_a = runs.load_run("paid_stub", DATE, "ccA")
    rd_b = runs.load_run("paid_stub", DATE, "ccB")
    claims = _typed(rd_a, events.T_CLAIM) + _typed(rd_b, events.T_CLAIM)
    # lifecycle stream only — slot-carrying events are the paid_slots
    # mirror (one take/drop pair per request), not claim ownership
    acquires = [e for e in claims if e.get("op") == "acquire" and e.get("slot") is None]
    releases = [e for e in claims if e.get("op") == "release" and e.get("slot") is None]
    # at most one acquire-winning sequence per (idc,arm,variant)
    acq_keys = sorted((e["idc"], e["arm"], e["variant"]) for e in acquires)
    assert acq_keys == PAID_KEYS
    assert len(releases) == 2
    # the wallet-side proof: exactly one paid request per xlat cell-key
    assert client.calls == 2
    xlat = _cells(rd_a, "xlat") + _cells(rd_b, "xlat")
    assert len(xlat) == 4
    for e in xlat:
        assert e["status"] in ("ok", "claimed", "dedup"), e
    for idc in PAID_IDS:
        assert sum(1 for e in xlat if e["idc"] == idc and e["status"] == "ok") == 1, (
            f"{idc}: not exactly one paying run"
        )


# --- scenario 8: accounting equation violation is named --------------------------


def test_s08_accounting_equation_detects_gap(broot):
    """Fabricate a missing terminal (plan cell + cell_queued, no terminal)
    -> accounting_check.ok False and the gap is named."""
    res = kernel.run(str(SMOKE_SPEC), date=DATE, slug="acct", **_quiet())
    assert res["accounting"]["ok"] is True
    rd = runs.load_run("smoke", DATE, "acct")

    pp = rd.plan_path()
    plan = json.loads(pp.read_text(encoding="utf-8"))
    plan["cells"].append(
        {
            "id": "9901.00999",
            "idc": "9901.00999",
            "arm": "-",
            "up": "-",
            "variant": "-",
            "stage": "xlat",
            "needs": [],
            "fp_input": None,
        }
    )
    pp.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    ledger.emit(
        events.make_event(
            events.T_CELL_QUEUED,
            run=rd.run,
            seq=-1,
            id="9901.00999",
            idc="9901.00999",
            arm="-",
            up="-",
            variant="-",
            stage="xlat",
        ),
        run_dir=rd.path,
    )

    acct = runs.accounting_check(rd)
    assert acct["ok"] is False
    assert ("9901.00999", "-", "-", "-", "xlat") in acct["missing_terminal"]
    assert acct["extra_queued"] == []  # in-plan: named as missing, not extra
    assert acct["dup_terminal"] == []
    assert acct["extra_terminal"] == []


# --- scenario 10: CLI subprocess surface ------------------------------------------


def test_s10_cli_subprocess_surface(broot, tmp_path):
    """`bench` shim end-to-end against $TEXLATE_BENCH_ROOT: init, spec list,
    plan, run, status, derive, doctor — sane exit codes."""
    repo_bench = tmp_path / "repo-bench"
    repo_bench.mkdir()  # keeps doctor's stray-dir scan off the real bench/
    env = dict(os.environ)
    env["TEXLATE_BENCH_ROOT"] = str(broot)
    env["TEXLATE_REPO_BENCH"] = str(repo_bench)
    for k in (
        "TEXLATE_LEDGER_ROOT",
        "TEXLATE_RUNS_ROOT",
        "TEXLATE_VAULT_ROOT",
        "TEXLATE_LAKE_ROOT",
    ):
        env.pop(k, None)
    env["PYTHONPATH"] = (str(BENCH_PY) + os.pathsep + env.get("PYTHONPATH", "")).rstrip(
        os.pathsep
    )

    def cli(*args):
        return subprocess.run(
            [sys.executable, str(SHIM), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    r = cli("init")
    assert r.returncode == 0, r.stderr
    assert "layout OK" in r.stdout

    # also covers `python -m kernel` (kernel/__main__.py)
    r = subprocess.run(
        [sys.executable, "-m", "kernel", "spec", "list"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "smoke" in r.stdout and "paid_stub" in r.stdout

    r = cli("spec", "list")
    assert r.returncode == 0, r.stderr
    assert "smoke" in r.stdout

    r = cli("plan", "smoke")
    assert r.returncode == 0, r.stderr
    assert "plan" in r.stdout

    r = cli("run", "smoke", "--date", DATE, "--slug", "cli1")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert '"ok": true' in r.stdout

    r = cli("status")
    assert r.returncode == 0, r.stderr
    assert "smoke/2026-09-22/cli1" in r.stdout

    r = cli("status", "--run", "smoke/2026-09-22/cli1")
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout

    r = cli("status", "--id", "9901.00001")
    assert r.returncode == 0, r.stderr
    assert "ingest" in r.stdout

    # CLI-level PAUSE gate (§6 Phase-3 rescope — a paid-spend fence):
    # paid specs refuse (exit 2); free specs and plan run straight through.
    pause = Path(broot) / "PAUSE"
    pause.touch()
    try:
        r = cli("run", "paid_stub", "--date", DATE, "--slug", "paused")
        assert r.returncode == 2, f"{r.stdout}\n{r.stderr}"
        assert "PAUSE" in r.stderr
        r = cli("plan", "smoke")
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        r = cli("run", "smoke", "--date", DATE, "--slug", "freeok")
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    finally:
        pause.unlink()
    assert not (Path(broot) / "runs" / "paid_stub" / DATE / "paused").exists()

    # paid spec without --max-cost — the §3.6 fuse refusal (exit != 0),
    # and the refusal lands BEFORE the run dir materializes
    r = cli("run", "paid_stub", "--date", DATE, "--slug", "nofuse")
    assert r.returncode != 0, f"{r.stdout}\n{r.stderr}"
    assert "max-cost" in r.stderr
    assert not (Path(broot) / "runs" / "paid_stub").exists()

    # the dry-run quote needs no budget — five buckets print fine
    r = cli("plan", "paid_stub", "--max-cost", "5")
    assert r.returncode == 0, r.stderr
    assert "quote" in r.stdout

    out_dir = tmp_path / "cli-derived"
    r = cli("derive", "--run", "smoke/2026-09-22/cli1", "--out", str(out_dir))
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    for f in ("cells.jsonl", "cases.jsonl", "report.md"):
        assert (out_dir / f).is_file()

    r = cli("doctor")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"


# --- scenario 3: paid_stub end to end ---------------------------------------------


def test_s03_paid_stub_end_to_end(broot, tmp_path, monkeypatch):
    """Paid path over the shipped stub: pay once (usage metered, claim
    acquire+release audited, asset rows), second run dedups with zero new
    paid requests."""
    client = _FakeClient()
    fn_calls = [0]
    factory = _factory(client, fn_calls)

    r1 = kernel.run(
        str(PAID_SPEC),
        date=DATE,
        slug="p1",
        max_cost=5.0,
        gateway_factory=factory,
        **_quiet(),
    )
    assert r1["ok"] is True
    rd1 = runs.load_run("paid_stub", DATE, "p1")
    cells = _cells(rd1)
    assert len(cells) == 6  # 2 ids x 3 stages
    assert all(e["status"] == "ok" for e in cells)
    assert client.calls == 2  # one paid request per xlat cell
    assert fn_calls == [1]  # the lazy client was built exactly once
    assert factory.meter.requests() == 2
    # usage recorded through the token accountant:
    # 2 x (100*1e-6 + 50*2e-6) = 0.0004
    assert abs(factory.meter.spent() - 0.0004) < 1e-9
    claims = _typed(rd1, events.T_CLAIM)
    for idc in PAID_IDS:
        ops = [e["op"] for e in claims if e["idc"] == idc and e.get("slot") is None]
        assert ops == ["acquire", "release"], (idc, ops)
    assert all(
        e.get("fate") == "verified"
        for e in claims
        if e["op"] == "release" and e.get("slot") is None
    )

    # second run on the same cells: dedup skip, ZERO new paid requests
    r2 = kernel.run(
        str(PAID_SPEC),
        date=DATE,
        slug="p2",
        max_cost=5.0,
        gateway_factory=factory,
        **_quiet(),
    )
    assert r2["ok"] is True
    rd2 = runs.load_run("paid_stub", DATE, "p2")
    cells2 = _cells(rd2)
    assert len(cells2) == 6
    assert all(e["status"] == "dedup" for e in cells2)
    assert client.calls == 2  # unchanged — nothing re-paid
    assert fn_calls == [1]  # factory call count stayed 1-run's worth

    # §3.5 contract: a paid run's bytes land in the vault — the xlat
    # terminal's harvest emits T_ASSET rows (xlat declares mutates=["zh"]
    # and writes via ctx.asset_dir("zh")), and doctor's §3.10.6⑤ paid
    # reconciliation finds every paid-ok key covered by manifest bytes_ok.
    assets = _typed(rd1, events.T_ASSET)
    assert assets, "paid run emitted no asset rows — harvest never ran"
    # (keeps the stray-dir scan off the real repo bench/)
    monkeypatch.setenv("TEXLATE_REPO_BENCH", str(tmp_path / "repo-bench"))
    rep = doctor.doctor()
    paid_check = next(c for c in rep["checks"] if c["name"] == "paid")
    assert paid_check["ok"] is True, paid_check["detail"]
    assert "without manifest bytes" not in paid_check["detail"]


# --- scenario 4: tombstoned cell + the 4-flag regen gate ----------------------------


def test_s04_tombstone_regen_gate(broot, tmp_path, monkeypatch):
    """Tombstoned paid cell: bare run -> reject/regen_gate; the full
    --allow-regen + --sel + --max-cost + --yes gate -> proceeds."""
    client = _FakeClient()
    factory = _factory(client)

    # tombstone one paid key BEFORE any run — evidence with no DONE history
    vault.tombstone("9901.00001", "a", "-", "zh", "test-lost")

    # plan-side of the regen contract (§3.6): the tombstoned key surfaces in
    # the 'missing' bucket + regen_decisions — never auto-entered as 'new'.
    q = kernel.plan(str(PAID_SPEC), **_quiet())
    assert q["sealed"] is True
    assert ("9901.00001", "a", "-") in q["quote"]["buckets"]["missing"]
    assert ("9901.00001", "a", "-") in q["regen_decisions"]
    assert ("9901.00002", "a", "-") in q["quote"]["buckets"]["new"]

    kernel.run(
        str(PAID_SPEC),
        date=DATE,
        slug="rg1",
        max_cost=5.0,
        gateway_factory=factory,
        **_quiet(),
    )
    rd1 = runs.load_run("paid_stub", DATE, "rg1")
    x1 = _cell(rd1, "9901.00001", "xlat")
    assert x1["status"] == "reject" and x1["cat"] == "regen_gate"
    assert _cell(rd1, "9901.00002", "xlat")["status"] == "ok"
    assert client.calls == 1  # only the untombstoned twin paid

    # the 4-flag gate DOES fire — proven on a fresh root where the
    # tombstoned cell still has no DONE/KERNEL outcome history
    _switch_root(monkeypatch, tmp_path / "broot2")
    vault.tombstone("9901.00001", "a", "-", "zh", "test-lost")
    client2 = _FakeClient()
    r3 = kernel.run(
        str(PAID_SPEC),
        date=DATE,
        slug="rg3",
        max_cost=5.0,
        allow_regen=True,
        sel="*",
        yes=True,
        gateway_factory=_factory(client2),
        **_quiet(),
    )
    rd3 = runs.load_run("paid_stub", DATE, "rg3")
    assert _cell(rd3, "9901.00001", "xlat")["status"] == "ok"
    assert client2.calls == 2  # regen authorized -> paid again

    # CONTRACT-VIOLATION (the regen dead door): back on the first root the
    # SAME authorization must proceed — but 'reject' is in STATUS_DONE, so
    # step-2 records dedup masks the cell before the oracle's regen gate is
    # ever consulted. The tombstoned cell can never be regenerated.
    monkeypatch.setenv(paths.ENV_ROOT, str(broot))
    kernel.run(
        str(PAID_SPEC),
        date=DATE,
        slug="rg2",
        max_cost=5.0,
        allow_regen=True,
        sel="*",
        yes=True,
        gateway_factory=factory,
        **_quiet(),
    )
    rd2 = runs.load_run("paid_stub", DATE, "rg2")
    x2 = _cell(rd2, "9901.00001", "xlat")
    assert x2["status"] == "ok", (
        f"4-flag regen on a regen_gate-rejected cell must re-pay; got "
        f"{x2['status']!r} — records dedup masks the regen gate"
    )
    assert client.calls == 2


# --- scenario 5: PAUSE holds cells, clear releases --------------------------------


def test_s05_pause_gate(broot, tmp_path, monkeypatch):
    """PAUSE engaged -> paid cells refuse without spending; cleared ->
    the same run resumes and pays."""
    client = _FakeClient()
    factory = _factory(client)

    paths.pause_path().touch()
    kernel.run(
        str(PAID_SPEC),
        date=DATE,
        slug="pz1",
        max_cost=5.0,
        gateway_factory=factory,
        **_quiet(),
    )
    rd1 = runs.load_run("paid_stub", DATE, "pz1")
    # §6 Phase-3 rescope — PAUSE fences PAID spend only: free ingest cells
    # run to ok under the fence, paid xlat cells hit the per-cell pause
    # gate, and report cells skip on the unmet need. Nothing is spent.
    for e in _cells(rd1, "ingest"):
        assert e["status"] == "ok"
    for e in _cells(rd1, "xlat"):
        assert e["status"] == "error" and e["cat"] == "pause"
    for e in _cells(rd1, "report"):
        assert e["status"] == "skip"
    assert client.calls == 0

    paths.pause_path().unlink()
    r2 = kernel.run(
        str(PAID_SPEC),
        resume=True,
        date=DATE,
        slug="pz1",
        max_cost=5.0,
        gateway_factory=factory,
        **_quiet(),
    )
    assert r2["ok"] is True
    assert client.calls == 2  # proceed: both paid cells pay
    assert sum(1 for e in _cells(rd1) if e["status"] == "ok") == 6
    assert runs.accounting_check(rd1)["ok"] is True

    # CONTRACT-VIOLATION probe — the state a mid-run crash leaves behind:
    # ingest DONE in records but its product died with the work tree, and
    # the paid cell never ran. The honest answer is now fault/upstream-lost:
    # records dedup trusts the ingest terminal (no silent re-run-and-heal),
    # _product_ok finds no durable 'state' bytes anywhere, and needs_eval
    # hard-stops the paid cell BEFORE the pause gate — diagnosed loss beats
    # a generic hold, and still zero spend. A 'dedup' here would mean the
    # oracle minted verified bytes that never existed; an error/pause would
    # hide real upstream loss behind a retriable hold.
    _switch_root(monkeypatch, tmp_path / "broot2")
    spec = specmod.load_spec(str(PAID_SPEC))
    rd = runs.create_run(
        "paid_stub",
        slug="pg",
        date=DATE,
        spec_dict=spec.to_dict(),
        spec_hash=specmod.spec_hash(spec),
    )
    pre = []
    seq = -1
    for idc in PAID_IDS:
        pre.append(
            events.make_event(
                events.T_CELL_QUEUED,
                run=rd.run,
                seq=seq,
                id=idc,
                idc=idc,
                arm="a",
                up="-",
                variant="-",
                stage="ingest",
            )
        )
        pre.append(
            events.make_event(
                events.T_CELL,
                run=rd.run,
                seq=seq - 1,
                id=idc,
                idc=idc,
                arm="a",
                up="-",
                variant="-",
                stage="ingest",
                status="ok",
            )
        )
        seq -= 2
    ledger.emit_batch(pre, run_dir=rd.path)
    paths.pause_path().touch()
    client2 = _FakeClient()
    kernel.run(
        str(PAID_SPEC),
        resume=True,
        date=DATE,
        slug="pg",
        max_cost=5.0,
        gateway_factory=_factory(client2),
        **_quiet(),
    )
    assert client2.calls == 0  # nothing burned — and the loss is diagnosed
    for e in _cells(rd, "xlat"):
        assert e["status"] == "fault" and e.get("cat") == "upstream-lost", (
            f"paid cell whose upstream terminal lost its product must land "
            f"fault/upstream-lost — got {e['status']!r} "
            f"cat={e.get('cat')!r}: 'dedup' means verified bytes minted "
            "from nothing, 'error/pause' hides real loss behind a hold"
        )


# --- scenario 6: unsealed index refuses spend -------------------------------------


def test_s06_index_unsealed_no_spend(broot):
    """Dirty the index -> paid cells land error/index_unsealed with zero
    spend; rebuild seals -> resume pays."""
    client = _FakeClient()
    factory = _factory(client)

    paths.index_dirty_path().touch()  # poison the seal (§3.10.6 ③)
    # §6 Phase-3 first-fire gate: a paid spec under an unsealed index
    # refuses the RUN at pre-flight (coverage.json keeps the evidence);
    # the per-cell index_unsealed path remains for mid-run seal loss.
    with pytest.raises(kernel.RunError):
        kernel.run(
            str(PAID_SPEC),
            date=DATE,
            slug="iu1",
            max_cost=5.0,
            gateway_factory=factory,
            **_quiet(),
        )
    rd1 = runs.load_run("paid_stub", DATE, "iu1")
    assert _cells(rd1) == []  # refused before any cell ran
    assert _typed(rd1, events.T_CELL_QUEUED) == []  # or even queued
    cov = json.loads((rd1.derived() / "coverage.json").read_text(encoding="utf-8"))
    assert cov["sealed"] is False
    assert client.calls == 0  # fail-closed: zero spend while unsealed

    # recovery path: rebuild the projection (kernel idle -> allowed), then
    # resume — the paid cells must pay their first-ever request.
    idx = indexmod.Index()
    try:
        idx.rebuild()
    finally:
        idx.close()
    assert not paths.index_dirty_path().exists()

    # CONTRACT-VIOLATION (paid_pool leak — same defect as s05): ingest's
    # ok rows put (idc,arm,variant) into the frozen paid pool, so the
    # resumed xlat cells dedup instead of paying — permanently.
    kernel.run(
        str(PAID_SPEC),
        resume=True,
        date=DATE,
        slug="iu1",
        max_cost=5.0,
        gateway_factory=factory,
        **_quiet(),
    )
    assert client.calls == 2, (
        f"resume after index rebuild must pay the never-paid cells; "
        f"calls={client.calls} — a FREE stage's ok was counted as "
        "paid-verified bytes"
    )


def test_s06b_first_fire_gate_stamp(broot):
    """§6 Phase-3 首火闸: no fresh vault-verify stamp -> the paid spec
    refuses at the gate (coverage.json keeps the evidence, zero spend);
    a fresh stamp -> the refused run resumes and pays."""
    client = _FakeClient()
    paths.vault_verify_stamp_path().unlink()  # broot stamped; remove it
    with pytest.raises(kernel.RunError):
        kernel.run(
            str(PAID_SPEC),
            date=DATE,
            slug="ff1",
            max_cost=5.0,
            gateway_factory=_factory(client),
            **_quiet(),
        )
    rd = runs.load_run("paid_stub", DATE, "ff1")
    cov = json.loads((rd.derived() / "coverage.json").read_text(encoding="utf-8"))
    assert cov["verify_fresh"] is False and cov["sealed"] is True
    assert _cells(rd) == [] and client.calls == 0

    write_verify_stamp()  # `bench vault verify` clean-pass evidence
    kernel.run(
        str(PAID_SPEC),
        resume=True,
        date=DATE,
        slug="ff1",
        max_cost=5.0,
        gateway_factory=_factory(client),
        **_quiet(),
    )
    assert client.calls == 2


# --- scenario 9: AUTH_DEAD refuses pre-flight --------------------------------------


def test_s09_auth_dead_preflight_refusal(broot):
    """AUTH_DEAD sentinel -> paid cells refuse before the claim/factory;
    cleared -> resume pays."""
    client = _FakeClient()
    fn_calls = [0]
    factory = _factory(client, fn_calls)

    locks.trip_auth_dead("test-trip")
    try:
        kernel.run(
            str(PAID_SPEC),
            date=DATE,
            slug="ad1",
            max_cost=5.0,
            gateway_factory=factory,
            **_quiet(),
        )
        rd1 = runs.load_run("paid_stub", DATE, "ad1")
        for e in _cells(rd1, "xlat"):
            assert e["status"] == "error" and e["cat"] == "auth_dead"
        assert client.calls == 0  # refused pre-flight…
        assert fn_calls == [0]  # …before the client was even built
    finally:
        locks.clear_auth_dead()

    # CONTRACT-VIOLATION (same paid_pool leak): resume should pay; ingest's
    # ok rows poison the oracle's verified leg instead.
    kernel.run(
        str(PAID_SPEC),
        resume=True,
        date=DATE,
        slug="ad1",
        max_cost=5.0,
        gateway_factory=factory,
        **_quiet(),
    )
    assert client.calls == 2, (
        f"resume after AUTH_DEAD clears must pay; calls={client.calls} — "
        "a FREE stage's ok was counted as paid-verified bytes"
    )
