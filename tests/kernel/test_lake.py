"""Tests for kernel/lake.py — the rebuildable corpus zone: catalog book,
is_complete read predicate, locked hydration, admission control, tiered
eviction, and the terminal-cell shell.

Every test runs against an isolated $TEXLATE_BENCH_ROOT via `broot`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from kernel import events, lake, paths
from kernel.idnorm import safe_id

IDC = "2101.00001"


def _mk_cell(
    idc: str,
    payload: dict[str, bytes],
    meta: dict | None = None,
    source: str = "arxiv",
    raw: dict[str, bytes] | None = None,
) -> Path:
    """Hand-materialize a lake cell: payload under extracted/, canonical
    bytes under raw/, meta.json verbatim."""
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


def _catalog_rows() -> list[dict]:
    p = paths.lake_catalog_path()
    if not p.exists():
        return []
    return [r for _ln, r, _raw in events.iter_jsonl(p) if r is not None]


def _lake_events() -> list[dict]:
    return [
        e
        for _ln, e, _raw in events.iter_jsonl(paths.events_path())
        if e is not None and e["type"] == "lake_cell"
    ]


# --- LakeCatalog ---------------------------------------------------------------------


def test_catalog_absent_set_mark_used_last_wins(broot: Path) -> None:
    cat = lake.LakeCatalog.load()
    assert cat.state(IDC) == "absent"
    assert cat.rows() == {}

    cat.set(IDC, "skeleton", source="arxiv")
    assert cat.state(IDC) == "skeleton"
    cat.mark_used(IDC)
    cat.set(IDC, "hydrated", n_files=3)

    # last row wins across reload
    cat2 = lake.LakeCatalog.load()
    assert cat2.state(IDC) == "hydrated"
    row = cat2.rows()[IDC]
    assert row["n_files"] == 3
    assert row["source"] == "arxiv"
    assert row["last_used_at"] > 0  # mark_used survived the merge

    # every set() emitted a lake_cell event; mark_used did not
    evs = _lake_events()
    states = [e["state"] for e in evs]
    assert states == ["skeleton", "hydrated"]
    assert all(e["idc"] == IDC and e["id"] == IDC for e in evs)


def test_catalog_load_tolerates_bad_lines(broot: Path) -> None:
    cat = lake.LakeCatalog.load()
    cat.set(IDC, "hydrated")
    with paths.lake_catalog_path().open("ab") as f:
        f.write(b"this is not json\n")
    cat2 = lake.LakeCatalog.load()
    assert cat2.state(IDC) == "hydrated"


# --- cell_dir / is_complete -------------------------------------------------------------


def test_cell_dir_uses_safe_id(broot: Path) -> None:
    d = lake.cell_dir("cond-mat/9601002")
    assert d == paths.lake_corpus_dir() / "arxiv" / "cond-mat--9601002"
    d2 = lake.cell_dir("2101.00001", source="sw")
    assert d2 == paths.lake_corpus_dir() / "sw" / "2101.00001"


def test_is_complete_true_on_consistent_cell(broot: Path) -> None:
    _mk_cell(IDC, {"a.tex": b"aa", "sub/b.bib": b"bb"}, meta={"n_files": 2})
    assert lake.is_complete(IDC)


def test_is_complete_false_on_half_tree(broot: Path) -> None:
    d = _mk_cell(IDC, {"a.tex": b"aa", "b.bib": b"bb"}, meta={"n_files": 2})
    # crash tore the tree: one payload file vanished
    (d / "extracted" / "b.bib").unlink()
    assert not lake.is_complete(IDC)
    # meta claims more than present
    (d / "meta.json").write_text(json.dumps({"n_files": 5}))
    assert not lake.is_complete(IDC)


def test_is_complete_false_when_meta_unparseable_or_missing(broot: Path) -> None:
    d = _mk_cell(IDC, {"a.tex": b"aa"}, meta={"n_files": 1})
    (d / "meta.json").write_text("{torn")
    assert not lake.is_complete(IDC)
    (d / "meta.json").unlink()
    assert not lake.is_complete(IDC)


def test_is_complete_false_when_dir_missing(broot: Path) -> None:
    assert not lake.is_complete("9999.99999")


def test_is_complete_counts_only_payload(broot: Path) -> None:
    # bookkeeping files (meta/mtree/files.txt) and raw/ are not payload
    d = _mk_cell(
        IDC, {"a.tex": b"aa"}, meta={"n_files": 1}, raw={"payload.bin": b"raw"}
    )
    (d / "files.txt").write_text("a.tex\n")
    (d / "mtree.txt").write_text("{}")
    assert lake.is_complete(IDC)


# --- skeleton ----------------------------------------------------------------------------


def test_register_skeleton_manifested_no_bytes(broot: Path) -> None:
    d = lake.register_skeleton(IDC)
    assert d.is_dir()
    assert lake.LakeCatalog.load().state(IDC) == "skeleton"
    # a skeleton must never satisfy the read predicate
    assert not lake.is_complete(IDC)
    assert _lake_events()[-1]["state"] == "skeleton"


# --- hydrate ---------------------------------------------------------------------------------


def test_hydrate_fetch_builds_complete_cell(broot: Path) -> None:
    def fetch(idc: str, stage: Path) -> dict:
        assert idc == IDC  # fetcher receives the cell's idc
        ex = stage / "extracted"
        ex.mkdir(parents=True)
        (ex / "a.tex").write_bytes(b"tex")
        (ex / "b.bib").write_bytes(b"bib")
        return {"unpack_ver": "v1"}

    got = lake.hydrate(IDC, fetch_fn=fetch, run_seq=7)
    assert got == lake.cell_dir(IDC)
    assert lake.is_complete(IDC)
    meta = json.loads((got / "meta.json").read_text())
    assert meta["n_files"] == 2 and meta["run_seq"] == 7
    assert meta["unpack_ver"] == "v1"  # fetch_fn's extra meta merged in
    assert lake.LakeCatalog.load().state(IDC) == "hydrated"
    assert _lake_events()[-1]["state"] == "hydrated"
    # staging dir cleaned up
    stage = paths.lake_tmp_dir() / "rebuild" / "7" / f"{safe_id(IDC)}.stage"
    assert not stage.exists()


def test_hydrate_double_check_under_lock_no_refetch(broot: Path) -> None:
    calls = []

    def fetch(_idc: str, stage: Path) -> None:
        calls.append(stage)
        ex = stage / "extracted"
        ex.mkdir(parents=True)
        (ex / "a.tex").write_bytes(b"tex")

    lake.hydrate(IDC, fetch_fn=fetch)
    assert len(calls) == 1
    # second hydrate: the cell is already complete — fetch must not run again
    got = lake.hydrate(IDC, fetch_fn=fetch)
    assert got == lake.cell_dir(IDC)
    assert len(calls) == 1


def test_hydrate_dest_occupied_first_wins(broot: Path) -> None:
    # a complete cell already occupies the destination
    d = _mk_cell(IDC, {"orig.tex": b"original"}, meta={"n_files": 1})
    calls = []

    def fetch(_idc: str, stage: Path) -> None:
        calls.append(stage)
        ex = stage / "extracted"
        ex.mkdir(parents=True)
        (ex / "new.tex").write_bytes(b"new")

    got = lake.hydrate(IDC, fetch_fn=fetch)
    assert got == d
    assert not calls  # existing winner never re-fetched
    assert (d / "extracted" / "orig.tex").exists()
    assert not (d / "extracted" / "new.tex").exists()


def test_hydrate_replaces_torn_dest(broot: Path) -> None:
    # occupied but INCOMPLETE dest is the hydrator's to finish
    d = _mk_cell(IDC, {"half.tex": b"half"}, meta={"n_files": 9})

    def fetch(_idc: str, stage: Path) -> None:
        ex = stage / "extracted"
        ex.mkdir(parents=True)
        (ex / "full.tex").write_bytes(b"full")

    got = lake.hydrate(IDC, fetch_fn=fetch)
    assert got == d
    assert (d / "extracted" / "full.tex").exists()
    assert not (d / "extracted" / "half.tex").exists()
    assert lake.is_complete(IDC)


def test_hydrate_lazy_unfetchable_returns_none(broot: Path) -> None:
    lake.register_skeleton(IDC)
    assert lake.hydrate(IDC) is None  # no fetch_fn, no raw — lazy
    assert lake.hydrate("9999.99999") is None


def test_hydrate_raw_only_reextracts_locally(broot: Path) -> None:
    # raw tree on disk, extracted evicted — zero-network rebuild
    d = _mk_cell(IDC, {}, meta={"n_files": 0}, raw={"a.tex": b"aa", "sub/b.bib": b"bb"})
    (d / "meta.json").write_text(json.dumps({"n_files": 99, "stale": True}))
    got = lake.hydrate(IDC)  # no fetch_fn — raw path
    assert got == d
    assert (d / "extracted" / "a.tex").read_bytes() == b"aa"
    assert (d / "extracted" / "sub" / "b.bib").read_bytes() == b"bb"
    # raw layer kept alongside the rebuilt projection
    assert (d / "raw" / "a.tex").exists()
    assert lake.is_complete(IDC)
    meta = json.loads((d / "meta.json").read_text())
    assert meta["n_files"] == 2 and meta["rebuilt_from"] == "raw"
    assert meta["stale"] is True  # old meta fields preserved


def test_hydrate_fetch_failure_cleans_stage_and_raises(broot: Path) -> None:
    def boom(_idc: str, stage: Path) -> None:
        (stage / "extracted").mkdir(parents=True)
        (stage / "extracted" / "x").write_bytes(b"x")
        raise RuntimeError("fetch exploded")

    with pytest.raises(RuntimeError, match="fetch exploded"):
        lake.hydrate(IDC, fetch_fn=boom, run_seq=3)
    stage = paths.lake_tmp_dir() / "rebuild" / "3" / f"{safe_id(IDC)}.stage"
    assert not stage.exists()
    assert not lake.is_complete(IDC)


# --- admit ----------------------------------------------------------------------------------


def test_admit_cap_gate(broot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXLATE_LAKE_CAP_GB", "0")
    assert not lake.admit(1)  # zero cap admits nothing
    monkeypatch.setenv("TEXLATE_LAKE_CAP_GB", "100")
    monkeypatch.setenv("TEXLATE_LAKE_FLOOR_GB", "0")  # neutralize fs leg
    assert lake.admit(1024)
    assert not lake.admit(101 * 1024**3)  # beyond the cap


def test_admit_floor_gate(broot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEXLATE_LAKE_CAP_GB", "100")
    # absurd floor: nothing admissible
    monkeypatch.setenv("TEXLATE_LAKE_FLOOR_GB", str(10**9))
    assert not lake.admit(1)


# --- evict ------------------------------------------------------------------------------------


def _evict_cell(
    broot: Path,
    idc: str,
    *,
    last_used: float,
    manifested: bool = True,
    pinned: bool = False,
    regen_cost: str | None = None,
    state: str = "hydrated",
) -> Path:
    """Register a hydrated-ish cell: extracted+raw payload + meta + catalog row."""
    d = _mk_cell(
        idc,
        {"e.bin": b"E" * 64},
        meta={"n_files": 1},
        raw={"r.bin": b"R" * 64},
    )
    cat = lake.LakeCatalog.load()
    cat.set(
        idc,
        state,
        source="arxiv",
        manifested=manifested,
        pinned=pinned,
        regen_cost=regen_cost,
        last_used_at=last_used,
    )
    return d


def test_evict_orphans_first_then_extracted(broot: Path) -> None:
    orphan = _evict_cell(broot, "2101.00010", last_used=10, manifested=False)
    a = _evict_cell(broot, "2101.00011", last_used=20)
    b = _evict_cell(broot, "2101.00012", last_used=30)

    removed = lake.evict(1)  # smallest target still takes the orphan first
    assert removed == [orphan]
    assert not orphan.exists()
    assert (a / "extracted").exists() and (b / "extracted").exists()
    assert lake.LakeCatalog.load().state("2101.00010") == "evicted"


def test_evict_extracted_before_raw_lru_order(broot: Path) -> None:
    a = _evict_cell(broot, "2101.00020", last_used=10)  # oldest
    b = _evict_cell(broot, "2101.00021", last_used=20)
    cat = lake.LakeCatalog.load()

    # target = exactly one extracted tree: only the LRU cell's projection goes
    ex_size = (a / "extracted" / "e.bin").stat().st_size
    removed = lake.evict(ex_size, catalog=cat)
    assert removed == [a / "extracted"]
    assert not (a / "extracted").exists()
    assert (a / "raw").exists()  # raw survives tier 1
    assert cat.state("2101.00020") == "raw_only"
    assert (b / "extracted").exists() and cat.state("2101.00021") == "hydrated"


def test_evict_full_tiers_pinned_and_network_untouched(broot: Path) -> None:
    a = _evict_cell(broot, "2101.00030", last_used=10)
    pin = _evict_cell(broot, "2101.00031", last_used=20, pinned=True)
    net = _evict_cell(broot, "2101.00032", last_used=30, regen_cost="network")
    cat = lake.LakeCatalog.load()

    lake.evict(10**9, catalog=cat)  # way past everything
    # a: extracted then raw both evicted
    assert not (a / "extracted").exists() and not (a / "raw").exists()
    assert cat.state("2101.00030") == "evicted"
    # net: extracted projection evicted (tier order), raw KEPT (network regen)
    assert not (net / "extracted").exists()
    assert (net / "raw").exists()
    assert cat.state("2101.00032") == "raw_only"
    # pinned: fully untouched
    assert (pin / "extracted").exists() and (pin / "raw").exists()
    assert cat.state("2101.00031") == "hydrated"


def test_evict_returns_removed_paths(broot: Path) -> None:
    a = _evict_cell(broot, "2101.00040", last_used=10)
    removed = lake.evict(10**9)
    assert set(removed) == {a / "extracted", a / "raw"}
    # lake_cell events recorded each tier transition
    states = [e["state"] for e in _lake_events()]
    assert "raw_only" in states and "evicted" in states


# --- shrink_shell --------------------------------------------------------------------------------


def test_shrink_shell_keeps_shell_set_only(broot: Path) -> None:
    cell = broot / "wcell"
    kept = ["receipt.json", "parse.json", "xlat-zh.jsonl", ".xlat-arm.json", ".lock"]
    for name in kept:
        cell.mkdir(parents=True, exist_ok=True)
        (cell / name).write_bytes(b"k")
    # paid checkpoint dirs are prune-exempt (R17) — kept under both
    # spellings: xlat-state.* (vault-kind name) and state.{arm}@v /
    # bare state/ (real cell-side dirnames)
    (cell / "xlat-state.zh").mkdir()
    (cell / "xlat-state.zh" / "seg-0001.json").write_bytes(b"state")
    (cell / "state.real@v1").mkdir()
    (cell / "state.real@v1" / "state.json").write_bytes(b"ckpt")
    (cell / "state").mkdir()
    (cell / "state" / "store.json").write_bytes(b"store")
    # everything else goes
    for name in ["zh.mock", "splice.mock", "build.x", "src"]:
        (cell / name).mkdir()
        (cell / name / "junk.bin").write_bytes(b"j")
    (cell / "misc.txt").write_bytes(b"m")

    lake.shrink_shell(cell)

    for name in kept:
        assert (cell / name).exists(), name
    assert (cell / "xlat-state.zh" / "seg-0001.json").exists()
    assert (cell / "state.real@v1" / "state.json").exists()
    assert (cell / "state" / "store.json").exists()
    survivors = {p.name for p in cell.iterdir()}
    assert survivors == set(kept) | {"xlat-state.zh", "state.real@v1", "state"}


def test_shrink_shell_missing_dir_noop(broot: Path) -> None:
    lake.shrink_shell(broot / "ghost")  # must not raise
