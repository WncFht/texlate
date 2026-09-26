"""Tests for lake.evict_cell (the ``bench lake evict-done`` primitive) and
the TEXLATE_BENCH_MIN_FREE_GB fetch gate in lake.hydrate.

Every test runs against an isolated $TEXLATE_BENCH_ROOT via `broot`.
"""

from __future__ import annotations

import json
import shutil
import typing
from typing import TYPE_CHECKING

import pytest
from kernel import events, lake, paths

if TYPE_CHECKING:
    from pathlib import Path

IDC = "2101.00001"


def _mk_cell(
    idc: str,
    payload: dict[str, bytes] | None,
    meta: dict | None = None,
    source: str = "arxiv",
    raw: dict[str, bytes] | None = None,
) -> Path:
    """Same hand-materialized cell shape as test_lake.py: extracted/
    payload, raw/ canonical bytes, meta.json verbatim."""
    d = lake.cell_dir(idc, source)
    if payload:
        for rel, data in payload.items():
            p = d / "extracted" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    if raw:
        for rel, data in raw.items():
            p = d / "raw" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    if meta is not None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps(meta))
    return d


def _lake_events() -> list[dict]:
    return [
        e
        for _ln, e, _raw in events.iter_jsonl(paths.events_path())
        if e is not None and e["type"] == "lake_cell"
    ]


def _hydrated_cell(idc: str = IDC, *, state: str = "hydrated") -> Path:
    d = _mk_cell(
        idc, {"e.bin": b"E" * 64}, meta={"n_files": 1}, raw={"raw.tar.gz": b"R" * 64}
    )
    lake.LakeCatalog.load().set(idc, state, source="arxiv", manifested=True)
    return d


# --- evict_cell ---------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_evict_cell_full_eviction_keeps_shell() -> None:
    d = _hydrated_cell()
    (d / "files.txt").write_text("e.bin\n")
    (d / "mtree.txt").write_text("{}")

    res = lake.evict_cell(IDC)

    assert res["result"] == "evicted"
    assert not (d / "extracted").exists()
    assert not (d / "raw").exists()
    # meta.json + bookkeeping survive — an evicted cell is a shell, not a gap
    assert (d / "meta.json").exists()
    assert (d / "files.txt").exists()
    assert (d / "mtree.txt").exists()
    cat = lake.LakeCatalog.load()
    assert cat.state(IDC) == "evicted"
    row = cat.rows()[IDC]
    assert row["n_files"] == 0  # payload honestly re-counted
    assert _lake_events()[-1]["state"] == "evicted"
    assert res["freed"] > 0
    assert set(res["removed"]) == {d / "extracted", d / "raw"}


@pytest.mark.usefixtures("broot")
def test_evict_cell_keep_raw_drops_to_raw_only() -> None:
    d = _hydrated_cell()

    res = lake.evict_cell(IDC, keep_raw=True)

    assert res["result"] == "raw_only"
    assert not (d / "extracted").exists()
    assert (d / "raw" / "raw.tar.gz").exists()
    assert lake.LakeCatalog.load().state(IDC) == "raw_only"
    assert _lake_events()[-1]["state"] == "raw_only"


@pytest.mark.usefixtures("broot")
def test_evict_cell_keep_raw_without_raw_is_evicted() -> None:
    d = _mk_cell(IDC, {"e.bin": b"E"}, meta={"n_files": 1})  # no raw layer
    lake.LakeCatalog.load().set(IDC, "hydrated", manifested=True)

    res = lake.evict_cell(IDC, keep_raw=True)

    assert res["result"] == "evicted"
    assert not (d / "extracted").exists()
    assert lake.LakeCatalog.load().state(IDC) == "evicted"


@pytest.mark.usefixtures("broot")
def test_evict_cell_idempotent_and_absent_skipped() -> None:
    _hydrated_cell()
    lake.evict_cell(IDC)
    n_events = len(_lake_events())

    res = lake.evict_cell(IDC)  # already evicted, nothing left
    assert res["result"] == "skipped"
    res = lake.evict_cell("9999.99999")  # absent — never existed
    assert res["result"] == "skipped"
    assert res["reason"] == "absent"
    assert len(_lake_events()) == n_events  # no rows written on skip


@pytest.mark.usefixtures("broot")
def test_evict_cell_pinned_untouched() -> None:
    d = _hydrated_cell()
    (d / lake.PIN_MARKER).write_bytes(b"pinned\n")

    res = lake.evict_cell(IDC)

    assert res["result"] == "skipped"
    assert res["reason"] == "pinned"
    assert (d / "extracted").exists()
    assert (d / "raw").exists()
    assert lake.LakeCatalog.load().state(IDC) == "hydrated"


@pytest.mark.usefixtures("broot")
def test_evict_cell_orphan_dir_without_row() -> None:
    # bytes on disk, no catalog row — still evictable (and the eviction
    # then leaves the state book honest)
    d = _mk_cell(IDC, {"e.bin": b"E"}, meta={"n_files": 1}, raw={"r.bin": b"R"})

    res = lake.evict_cell(IDC)

    assert res["result"] == "evicted"
    assert not (d / "extracted").exists()
    assert not (d / "raw").exists()
    assert lake.LakeCatalog.load().state(IDC) == "evicted"


@pytest.mark.usefixtures("broot")
def test_evict_cell_orphan_pinned_marker_respected() -> None:
    # orphan dir carrying a PINNED marker but no catalog row — _pinned's
    # marker leg needs a row idc, so the direct cell check must catch it
    d = _mk_cell(IDC, {"e.bin": b"E"}, raw={"r.bin": b"R"})
    (d / lake.PIN_MARKER).write_bytes(b"pinned\n")

    res = lake.evict_cell(IDC)

    assert res["result"] == "skipped"
    assert res["reason"] == "pinned"
    assert (d / "extracted").exists()
    assert (d / "raw").exists()


@pytest.mark.usefixtures("broot")
def test_evict_cell_cleans_stray_extracted_under_raw_only() -> None:
    d = _hydrated_cell(state="raw_only")

    res = lake.evict_cell(IDC, keep_raw=True)

    assert res["result"] == "raw_only"
    assert not (d / "extracted").exists()
    assert (d / "raw").exists()
    # a second pass is a true no-op
    assert lake.evict_cell(IDC, keep_raw=True)["result"] == "skipped"


def test_evict_cell_removes_torn_stage_and_symlink(broot: Path) -> None:
    d = _hydrated_cell()
    stage = d / "extracted.stage"
    (stage / "sub").mkdir(parents=True)
    (stage / "sub" / "x").write_bytes(b"x")
    # extracted/ as a symlink: the link is dropped, its target survives
    outside = broot / "elsewhere"
    outside.mkdir()
    (outside / "keep.bin").write_bytes(b"keep")
    shutil.rmtree(d / "extracted")
    (d / "extracted").symlink_to(outside)

    res = lake.evict_cell(IDC)

    assert res["result"] == "evicted"
    assert not stage.exists()
    assert not (d / "extracted").exists()
    assert not (d / "extracted").is_symlink()
    assert (outside / "keep.bin").exists()  # link target never followed
    assert not (d / "raw").exists()


@pytest.mark.usefixtures("broot")
def test_evict_cell_row_source_wins_over_arg() -> None:
    d = _mk_cell("sw/0001", {"e.bin": b"E"}, meta={"n_files": 1}, source="sw")
    lake.LakeCatalog.load().set("sw/0001", "hydrated", source="sw", manifested=True)

    res = lake.evict_cell("sw/0001")  # default source=arxiv loses to row

    assert res["result"] == "evicted"
    assert not (d / "extracted").exists()
    assert lake.LakeCatalog.load().rows()["sw/0001"]["source"] == "sw"


# --- fetch free-space gate ------------------------------------------------------------


class _Usage(typing.NamedTuple):
    total: int
    used: int
    free: int


def _fake_disk(
    monkeypatch: pytest.MonkeyPatch, *, free_gib: float, total_gib: float = 200.0
) -> None:
    """Make the gate see a real-size volume at ``free_gib`` headroom.

    tmpfs test roots (~16 GiB) sit below the default 60 GiB floor by
    construction — the gate skips filesystems whose total capacity can
    never meet the watermark — so the refusal path needs a faked
    ``shutil.disk_usage``, not just a big env floor.
    """

    def fake(_p: object) -> _Usage:
        return _Usage(int(total_gib * 2**30), 0, int(free_gib * 2**30))

    monkeypatch.setattr(shutil, "disk_usage", fake)


@pytest.mark.usefixtures("broot")
def test_hydrate_fetch_gate_refuses_under_pressure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_disk(monkeypatch, free_gib=4)  # < 60 GiB default floor
    lake.register_skeleton(IDC)
    calls = []

    def fetch(_idc: str, _stage: Path) -> None:
        calls.append(_stage)

    with pytest.raises(lake.DiskPressureError):
        lake.hydrate(IDC, fetch_fn=fetch, run_seq=1)

    assert not calls  # the fetch never started
    # the catalog never flipped to hydrating — the cell keeps its prior
    # state so the gate is a clean retriable refusal
    assert lake.LakeCatalog.load().state(IDC) == "skeleton"
    stage = paths.lake_tmp_dir() / "rebuild" / "1" / f"{IDC}.stage"
    assert not stage.exists()


@pytest.mark.usefixtures("broot")
def test_hydrate_fetch_gate_passes_with_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_disk(monkeypatch, free_gib=200)

    def fetch(_idc: str, stage: Path) -> None:
        ex = stage / "extracted"
        ex.mkdir(parents=True)
        (ex / "a.tex").write_bytes(b"tex")

    got = lake.hydrate(IDC, fetch_fn=fetch)
    assert got == lake.cell_dir(IDC)
    assert lake.is_complete(IDC)
    assert lake.LakeCatalog.load().state(IDC) == "hydrated"


@pytest.mark.usefixtures("broot")
def test_hydrate_fetch_gate_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_disk(monkeypatch, free_gib=4)
    monkeypatch.setenv("TEXLATE_BENCH_MIN_FREE_GB", "1")  # 4 GiB free passes

    def fetch(_idc: str, stage: Path) -> None:
        ex = stage / "extracted"
        ex.mkdir(parents=True)
        (ex / "a.tex").write_bytes(b"tex")

    assert lake.hydrate(IDC, fetch_fn=fetch) == lake.cell_dir(IDC)


@pytest.mark.usefixtures("broot")
def test_hydrate_gate_vacuous_below_floor_sized_fs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a filesystem smaller than the floor can never meet the watermark —
    # the gate steps aside instead of deadlocking (tmpfs roots rely on it)
    _fake_disk(monkeypatch, free_gib=1, total_gib=16)

    def fetch(_idc: str, stage: Path) -> None:
        ex = stage / "extracted"
        ex.mkdir(parents=True)
        (ex / "a.tex").write_bytes(b"tex")

    assert lake.hydrate(IDC, fetch_fn=fetch) == lake.cell_dir(IDC)


@pytest.mark.usefixtures("broot")
def test_hydrate_raw_reextract_exempt_from_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_disk(monkeypatch, free_gib=4)
    d = _mk_cell(IDC, {}, meta={"n_files": 1}, raw={"a.tex": b"aa", "sub/b.bib": b"bb"})

    got = lake.hydrate(IDC)  # no fetch_fn — local path

    assert got == d
    assert (d / "extracted" / "a.tex").read_bytes() == b"aa"
    assert lake.is_complete(IDC)


@pytest.mark.usefixtures("broot")
def test_hydrate_complete_cell_never_touches_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_disk(monkeypatch, free_gib=4)
    d = _mk_cell(IDC, {"a.tex": b"aa"}, meta={"n_files": 1})

    def fetch(_idc: str, _stage: Path) -> None:
        pytest.fail("fetch must not run")

    assert lake.hydrate(IDC, fetch_fn=fetch) == d
