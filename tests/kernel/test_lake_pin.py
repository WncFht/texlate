"""Tests for the M3 pin + CAS GC pack — cell-side PINNED marker semantics.

Pin truth is the ``{cell}/PINNED`` marker file; the catalog ``pinned``
field is its ledger-replayable projection (lake_cell events carry it, so a
catalog rebuild loses nothing). Every byte-deleting verb — lake.evict's
three tiers, shrink_shell, runs.remove_cell_tree — consults the marker;
``state=='pinned'`` stays read-compat for存量 rows. ``bench sweep``'s full
pass tail-drives ``cas.gc_sweep`` (24h grace) and reports ``cas_swept``.

Every test runs against an isolated $TEXLATE_BENCH_ROOT via `broot`.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from kernel import cas, cli, events, lake, paths, runs, sweep
from kernel.idnorm import safe_id
from kernel.importer import import_zhstore, seed_vault_zhstore
from kernel.index import Index
from kernel import vault

IDC = "2101.00001"


def _mk_cell(idc: str, payload: dict[str, bytes], meta: dict | None = None,
             source: str = "arxiv", raw: dict[str, bytes] | None = None
             ) -> Path:
    """Hand-materialize a lake cell (same shape as test_lake's helper)."""
    d = lake.cell_dir(idc, source)
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


def _evict_cell(idc: str, *, last_used: float, manifested: bool = True,
                pinned: bool = False) -> Path:
    """Hydrated-ish cell with extracted+raw payload and a catalog row."""
    d = _mk_cell(idc, {"e.bin": b"E" * 64}, meta={"n_files": 1},
                 raw={"r.bin": b"R" * 64})
    lake.LakeCatalog.load().set(
        idc, "hydrated", source="arxiv", manifested=manifested,
        pinned=pinned, last_used_at=last_used)
    return d


def _catalog_rows() -> list[dict]:
    p = paths.lake_catalog_path()
    if not p.exists():
        return []
    return [r for _ln, r, _raw in events.iter_jsonl(p) if r is not None]


def _lake_events() -> list[dict]:
    return [
        e for _ln, e, _raw in events.iter_jsonl(paths.events_path())
        if e is not None and e["type"] == "lake_cell"
    ]


def _shard(rd: runs.RunDir) -> list[dict]:
    return [e for _ln, e, _raw in events.iter_jsonl(rd.events_path())
            if e is not None]


# --- pin / unpin verbs ------------------------------------------------------------


def test_pin_unpin_roundtrip(broot: Path) -> None:
    row = lake.pin(IDC)
    d = lake.cell_dir(IDC)
    assert lake.cell_pinned(d)
    assert (d / lake.PIN_MARKER).read_bytes() == b"pinned\n"
    # absent cell pins as skeleton + manifested:False (nothing manifested it)
    assert row["pinned"] is True
    assert row["state"] == "skeleton"
    assert row["manifested"] is False
    # the field is on the ledger event — replay survives
    ev = _lake_events()[-1]
    assert ev["pinned"] is True and ev["state"] == "skeleton"

    row2 = lake.unpin(IDC)
    assert row2 is not None and row2["pinned"] is False
    assert not lake.cell_pinned(d)
    assert _lake_events()[-1]["pinned"] is False
    # catalog row keeps last-wins projection on disk too
    assert _catalog_rows()[-1]["pinned"] is False


def test_unpin_absent_is_noop(broot: Path) -> None:
    assert lake.unpin("9999.99999") is None
    assert not lake.cell_dir("9999.99999").exists()


def test_pin_preserves_row_source(broot: Path) -> None:
    """The row's source names the dir where the bytes live — pinning a
    sw cell with the default arxiv arg must mark the SW cell, never
    rewrite the row's source (that would orphan the real bytes)."""
    d = _mk_cell(IDC, {"a.tex": b"aa"}, meta={"n_files": 1}, source="sw")
    lake.LakeCatalog.load().set(IDC, "hydrated", source="sw")
    lake.pin(IDC)                            # default source="arxiv"
    assert lake.cell_pinned(d)               # marker in the sw dir
    assert not lake.cell_pinned(lake.cell_dir(IDC, "arxiv"))
    row = lake.LakeCatalog.load().rows()[IDC]
    assert row["source"] == "sw" and row["pinned"] is True


def test_pin_survives_mark_used_and_state_transitions(broot: Path) -> None:
    """The durability arm: pinned is a FIELD — mark_used/set() merge it
    forward, never clear it (spike: state=='pinned' would silently un-pin
    on the next set; the field does not)."""
    _mk_cell(IDC, {"a.tex": b"aa"}, meta={"n_files": 1})
    cat = lake.LakeCatalog.load()
    cat.set(IDC, "hydrated", n_files=1)
    cat.pin(IDC)
    cat.mark_used(IDC)                       # append-only row, no event
    cat.set(IDC, "raw_only")                 # state churn keeps the field
    row = lake.LakeCatalog.load().rows()[IDC]
    assert row["pinned"] is True
    assert row["state"] == "raw_only"
    assert row["last_used_at"] > 0
    assert lake._pinned(row)


def test_state_pinned_row_is_read_compat(broot: Path) -> None:
    """存量 rows written with state=='pinned' still count as pinned."""
    _mk_cell(IDC, {"a.tex": b"aa"}, meta={"n_files": 1},
             raw={"r.bin": b"rr"})
    cat = lake.LakeCatalog.load()
    cat.set(IDC, "pinned")                   # legacy spelling, no field
    row = cat.rows()[IDC]
    assert "pinned" not in row               # field absent entirely...
    assert lake._pinned(row)                 # ...state leg still pins


def test_marker_only_cell_counts_pinned(broot: Path) -> None:
    """A PINNED file overrides even a ``pinned:false`` catalog field —
    the marker is the truth, the field only its projection."""
    d = _evict_cell(IDC, last_used=10)
    (d / lake.PIN_MARKER).write_bytes(b"pinned\n")
    row = lake.LakeCatalog.load().rows()[IDC]
    assert row["pinned"] is False            # field says unpinned...
    assert lake._pinned(row)                 # ...marker says otherwise


def test_is_complete_unaffected_by_marker(broot: Path) -> None:
    """PINNED is bookkeeping: it must never count as payload."""
    d = _mk_cell(IDC, {"a.tex": b"aa"}, meta={"n_files": 1})
    (d / lake.PIN_MARKER).write_bytes(b"pinned\n")
    assert lake.is_complete(IDC)


def test_hydrate_preserves_pin_marker(broot: Path) -> None:
    """Re-hydrating a torn pinned cell carries the marker across the
    stage→dest rename (rmtree would otherwise eat it)."""
    lake.pin(IDC)                            # dir = {PINNED}, skeleton row
    d = lake.cell_dir(IDC)

    def fetch(_idc: str, stage: Path) -> None:
        (stage / "extracted").mkdir(parents=True)
        (stage / "extracted" / "a.tex").write_bytes(b"tex")

    got = lake.hydrate(IDC, fetch_fn=fetch)
    assert got == d
    assert lake.cell_pinned(d)               # marker rode the rename
    assert lake.is_complete(IDC)
    row = lake.LakeCatalog.load().rows()[IDC]
    assert row["state"] == "hydrated" and row["pinned"] is True


# --- evict honors pin (all three tiers) --------------------------------------------


def test_evict_skips_pinned_all_tiers(broot: Path) -> None:
    plain = _evict_cell("2101.00020", last_used=10)
    field = _evict_cell("2101.00021", last_used=20, pinned=True)
    mark = _evict_cell("2101.00022", last_used=30)
    (mark / lake.PIN_MARKER).write_bytes(b"pinned\n")   # marker-only pin
    legacy = _evict_cell("2101.00023", last_used=40)
    lake.LakeCatalog.load().set("2101.00023", "pinned")  # state-compat pin
    orphan = _evict_cell("2101.00024", last_used=50, manifested=False)
    (orphan / lake.PIN_MARKER).write_bytes(b"pinned\n")  # tier-0 pinned

    cat = lake.LakeCatalog.load()
    lake.evict(10**9, catalog=cat)           # way past everything

    # plain cell fully evicted (extracted + raw)
    assert not (plain / "extracted").exists()
    assert not (plain / "raw").exists()
    assert cat.state("2101.00020") == "evicted"
    # every pin flavor left its whole tree untouched
    for idc, d in (("2101.00021", field), ("2101.00022", mark),
                   ("2101.00023", legacy), ("2101.00024", orphan)):
        assert (d / "extracted").exists() and (d / "raw").exists(), idc
    assert cat.state("2101.00024") == "hydrated"   # never marked evicted


def test_unpin_makes_cell_evictable(broot: Path) -> None:
    d = _evict_cell(IDC, last_used=10)
    lake.pin(IDC)
    lake.unpin(IDC)
    assert not lake.cell_pinned(d)
    removed = lake.evict(10**9)
    assert (d / "extracted") in removed or not (d / "extracted").exists()
    assert lake.LakeCatalog.load().state(IDC) == "evicted"


# --- shrink_shell + remove_cell_tree honor the marker --------------------------------


def _work_cell(broot: Path, name: str = "wcell") -> Path:
    cell = broot / name
    for n in ("receipt.json", "parse.json", ".xlat-arm.json"):
        cell.mkdir(parents=True, exist_ok=True)
        (cell / n).write_bytes(b"k")
    (cell / "zh.mock").mkdir()
    (cell / "zh.mock" / "out.pdf").write_bytes(b"paid")
    (cell / "junk").mkdir()
    (cell / "junk" / "x.bin").write_bytes(b"j")
    return cell


def test_shrink_shell_noop_on_pinned_cell(broot: Path) -> None:
    cell = _work_cell(broot)
    (cell / lake.PIN_MARKER).write_bytes(b"pinned\n")
    before = {p.name for p in cell.iterdir()}
    lake.shrink_shell(cell)
    after = {p.name for p in cell.iterdir()}
    assert after == before                   # pin protects the whole tree
    assert (cell / "junk" / "x.bin").exists()


def test_remove_cell_tree_refuses_pinned(broot: Path) -> None:
    rd = runs.create_run("soak", date="2026-09-21")
    cell = rd.work("2401--00001")
    (cell / "zh.mock").mkdir(parents=True)
    (cell / "zh.mock" / "out.pdf").write_bytes(b"paid bytes")
    (cell / lake.PIN_MARKER).write_bytes(b"pinned\n")
    # refusal is unconditional — even with paid bytes vaulted
    with pytest.raises(runs.BlockedDelete):
        runs.remove_cell_tree(rd, "2401--00001", vault_check=lambda: True)
    assert cell.exists() and (cell / lake.PIN_MARKER).exists()
    notes = [e for e in _shard(rd) if e["type"] == "note"]
    assert notes and notes[0]["level"] == "warn"
    assert "PINNED" in notes[0]["text"]
    # lifting the pin frees the delete (vault_check now the only gate)
    (cell / lake.PIN_MARKER).unlink()
    runs.remove_cell_tree(rd, "2401--00001", vault_check=lambda: True)
    assert not cell.exists()


# --- catalog replay preserves the volatile fields ------------------------------------


def test_lake_cell_event_carries_volatile_fields(broot: Path) -> None:
    """_lake_event forwards pinned/manifested/orphan/regen_cost/
    last_used_at — a catalog rebuild replaying lake_cell events loses
    nothing the row carried."""
    cat = lake.LakeCatalog.load()
    cat.set(IDC, "hydrated", source="arxiv", bytes=123, pinned=True,
            manifested=False, orphan=True, regen_cost="network",
            last_used_at=42.5)
    ev = _lake_events()[-1]
    assert ev["pinned"] is True
    assert ev["manifested"] is False
    assert ev["orphan"] is True
    assert ev["regen_cost"] == "network"
    assert ev["last_used_at"] == 42.5
    assert ev["bytes"] == 123
    # simulate a replay rebuild: last-wins fold over the event stream
    rebuilt: dict[str, dict] = {}
    for e in _lake_events():
        rebuilt[e["idc"]] = e
    for k in ("pinned", "manifested", "orphan", "regen_cost",
              "last_used_at", "bytes"):
        assert rebuilt[IDC][k] == ev[k]


def test_lake_cell_event_rejects_nonbool_flags(broot: Path) -> None:
    with pytest.raises(events.EventError):
        events.make_event(events.T_LAKE_CELL, id=IDC, idc=IDC,
                          state="hydrated", pinned="yes")


# --- sweep tail: CAS GC ---------------------------------------------------------------


def test_sweep_full_pass_runs_cas_gc(broot: Path) -> None:
    stale_sha = cas.store_bytes(b"stale-bytes")
    fresh_sha = cas.store_bytes(b"fresh-bytes")
    stale_obj = cas.object_path(stale_sha)
    old = time.time() - 2 * sweep.CAS_GC_GRACE_S
    os.utime(stale_obj, (old, old))          # past the 24h grace

    rep = sweep.sweep(light=True)            # light pass skips the duty
    assert rep["cas_swept"] == []
    assert stale_obj.exists()

    rep = sweep.sweep()
    assert rep["cas_swept"] == [stale_obj.name]
    assert not stale_obj.exists()
    assert cas.has(fresh_sha)                # inside grace — kept


def test_sweep_lake_orphan_adoption_keeps_pin(broot: Path) -> None:
    """A PINNED marker on an un-cataloged cell dir is re-projected into
    the adopted row — catalog rebuild honors the file-side truth."""
    cell = paths.lake_corpus_dir() / "arxiv" / safe_id("2401.00006")
    cell.mkdir(parents=True)
    (cell / lake.PIN_MARKER).write_bytes(b"pinned\n")
    rep = sweep.sweep()
    assert rep["lake_orphans"][0]["idc"] == "2401.00006"
    row = lake.LakeCatalog.load().rows()["2401.00006"]
    assert row["state"] == "skeleton"
    assert row["manifested"] is False
    assert row["orphan"] is True
    assert row["pinned"] is True             # marker truth re-projected


# --- CLI verbs ------------------------------------------------------------------------


def test_cli_pin_unpin_status(broot: Path,
                              capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["lake", "pin", "2101.00001"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "pinned 2101.00001" in out
    d = lake.cell_dir("2101.00001")
    assert lake.cell_pinned(d)
    # catalog field landed too
    assert lake.LakeCatalog.load().rows()["2101.00001"]["pinned"] is True

    (d / "extracted").mkdir(parents=True)
    (d / "extracted" / "a.bin").write_bytes(b"A" * 32)
    assert cli.main(["lake", "status"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "pinned=1" in out
    assert "pinned_bytes=" in out

    assert cli.main(["lake", "unpin", "2101.00001"]) == cli.EXIT_OK
    assert "unpinned 2101.00001" in capsys.readouterr().out
    assert not lake.cell_pinned(d)
    assert lake.LakeCatalog.load().rows()["2101.00001"]["pinned"] is False


def test_cli_pin_bad_id_fails(broot: Path,
                              capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["lake", "pin", "smoke/0001"]) == cli.EXIT_FAIL
    capsys.readouterr()
    # canon-fail leaves no marker, no row
    assert not lake.LakeCatalog.load().rows()
    # a bad id among good ones still pins the good ones
    assert cli.main(["lake", "pin", "2101.00002", "smoke/0001"]
                    ) == cli.EXIT_FAIL
    assert lake.cell_pinned(lake.cell_dir("2101.00002"))


def test_cli_unpin_absent_reports(broot: Path,
                                capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["lake", "unpin", "2101.00009"]) == cli.EXIT_OK
    assert "not pinned" in capsys.readouterr().out


# --- zh-store manifest `pinned` placeholder --------------------------------------------


def test_zhstore_pinned_passthrough(broot: Path, tmp_path: Path) -> None:
    """Manifest rows may carry optional ``pinned`` — import tolerates it,
    the vault census passes it into the harvested meta verbatim."""
    zh = tmp_path / "zh-store"
    (zh / "0712.0031" / "zh").mkdir(parents=True)
    (zh / "0712.0031" / "zh" / "main.pdf").write_bytes(b"%PDF-p")
    (zh / "0712.0032" / "zh").mkdir(parents=True)
    (zh / "0712.0032" / "zh" / "m.pdf").write_bytes(b"%PDF-np")
    rows = [
        {"id": "0712.0031", "arm": "real", "has_zh": True,
         "has_splice": False, "zone": "primary", "pinned": True},
        {"id": "0712.0032", "arm": "real", "has_zh": True,
         "has_splice": False, "zone": "primary"},
    ]
    manifest = zh / "manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    index = Index()
    stats = import_zhstore(manifest, zh, index)   # extra field tolerated
    assert stats["rows"] == 2 and stats["quarantined"] == 0

    stats = seed_vault_zhstore(manifest, zh, index)
    assert stats["harvested"] == 2
    pinned_meta = vault.query("0712.0031", "real", "-")[0]
    assert pinned_meta["pinned"] is True
    plain_meta = vault.query("0712.0032", "real", "-")[0]
    assert "pinned" not in plain_meta          # absent stays absent
