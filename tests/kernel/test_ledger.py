"""Tests for kernel/ledger.py — the sole events.jsonl write path + seals.

Every test runs against an isolated $TEXLATE_BENCH_ROOT via the `broot`
fixture (see conftest.py). Files stay KB-scale — /tmp is quota-sensitive.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from kernel import events, ledger, paths

KIND = "xlat"
DATE = "2026-09-21"


def _note(seq: int, text: str = "n", run: str = "r1") -> dict:
    return events.make_event(events.T_NOTE, run=run, seq=seq, text=text, level="info")


def _cell(seq: int, run: str = "r1") -> dict:
    return events.make_event(
        events.T_CELL,
        run=run,
        seq=seq,
        id="2401.00001",
        idc="2401.00001",
        arm="zh",
        up="-",
        variant="-",
        stage="xlat",
        status="ok",
    )


def _lines(path: Path) -> list[bytes]:
    return [ln for ln in path.read_bytes().split(b"\n") if ln]


def _parsed(path: Path) -> list[dict]:
    return [ev for _ln, ev, _raw in events.iter_jsonl(path) if ev is not None]


def _mint(slug: str, run: str | None = None) -> int:
    return ledger.mint_run_seq(run or slug, KIND, DATE, slug, "spechash")


# --- emit / iter round-trip -------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_emit_iter_roundtrip_ordering() -> None:
    evs = [_note(i, f"n{i}") for i in range(5)]
    offsets = [ledger.emit(ev) for ev in evs]
    assert offsets == sorted(offsets)
    assert offsets[0] == 0
    got = _parsed(paths.events_path())
    assert [events.dumps(g) for g in got] == [events.dumps(e) for e in evs]


@pytest.mark.usefixtures("broot")
def test_emit_returns_byte_offset_of_line() -> None:
    ev1, ev2 = _note(1), _note(2)
    off1 = ledger.emit(ev1)
    off2 = ledger.emit(ev2)
    data = paths.events_path().read_bytes()
    assert off1 == 0
    assert off2 == len(events.dumps(ev1)) + 1
    assert data[off2:].startswith(events.dumps(ev2).encode())


@pytest.mark.usefixtures("broot")
def test_emit_rejects_invalid_event() -> None:
    with pytest.raises(events.EventError):
        ledger.emit({"type": "bogus"})
    # nothing was written
    assert paths.events_path().stat().st_size == 0


# --- torn-tail heal -----------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_torn_tail_heals_partial_line() -> None:
    p = paths.events_path()
    good = events.dumps(_note(1)).encode() + b"\n"
    p.write_bytes(good + b'{"type":"note","seq":12')  # interrupted append
    ev2 = _note(2)
    off = ledger.emit(ev2)
    assert off == len(good)
    assert p.read_bytes() == good + events.dumps(ev2).encode() + b"\n"
    # every line parses
    assert len(_parsed(p)) == 2  # noqa: PLR2004 -- 断言字面量


@pytest.mark.usefixtures("broot")
def test_torn_tail_no_newline_at_all_truncates_to_zero() -> None:
    p = paths.events_path()
    p.write_bytes(b'{"type":"note","seq":12')  # whole file is one torn line
    ev = _note(1)
    off = ledger.emit(ev)
    assert off == 0
    assert p.read_bytes() == events.dumps(ev).encode() + b"\n"


@pytest.mark.usefixtures("broot")
def test_clean_tail_needs_no_heal() -> None:
    ev = _note(1)
    ledger.emit(ev)
    before = paths.events_path().read_bytes()
    ledger.emit(_note(2))
    data = paths.events_path().read_bytes()
    assert data[: len(before)] == before  # nothing was truncated


# --- dual-write ----------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_dual_write_to_run_dir() -> None:
    rdir = paths.run_dir(KIND, DATE, "dual1")
    evs = [_note(i) for i in range(3)]
    for ev in evs:
        ledger.emit(ev, run_dir=rdir)
    shard = rdir / "events.jsonl"
    assert shard.read_bytes() == paths.events_path().read_bytes()


@pytest.mark.usefixtures("broot")
def test_dual_write_torn_shard_also_heals() -> None:
    rdir = paths.run_dir(KIND, DATE, "dual2")
    rdir.mkdir(parents=True)
    shard = rdir / "events.jsonl"
    shard.write_bytes(b'{"torn":')  # partial line in the shard
    ev = _note(1)
    ledger.emit(ev, run_dir=rdir)
    assert shard.read_bytes() == events.dumps(ev).encode() + b"\n"


@pytest.mark.usefixtures("broot")
def test_emit_batch_dual_write() -> None:
    rdir = paths.run_dir(KIND, DATE, "dual3")
    evs = [_note(i) for i in range(4)]
    ledger.emit_batch(evs, run_dir=rdir)
    assert (rdir / "events.jsonl").read_bytes() == paths.events_path().read_bytes()


# --- emit_batch ----------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_emit_batch_all_lines_present() -> None:
    evs = [_cell(i) for i in range(10)]
    offsets = ledger.emit_batch(evs)
    assert len(offsets) == len(evs)
    assert offsets == sorted(offsets)
    got = _parsed(paths.events_path())
    assert [events.dumps(g) for g in got] == [events.dumps(e) for e in evs]
    # each returned offset points at its own line start
    data = paths.events_path().read_bytes()
    for off, ev in zip(offsets, evs, strict=True):
        raw = events.dumps(ev).encode()
        assert data[off : off + len(raw)] == raw


@pytest.mark.usefixtures("broot")
def test_emit_batch_empty_returns_empty() -> None:
    assert ledger.emit_batch([]) == []


@pytest.mark.usefixtures("broot")
def test_emit_batch_validates_all_before_writing() -> None:
    evs = [_note(1), {"type": "bogus"}, _note(2)]
    with pytest.raises(events.EventError):
        ledger.emit_batch(evs)
    assert paths.events_path().stat().st_size == 0  # no partial batch


# --- sink ----------------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_sink_applies_inside_lock_and_failure_marks_dirty() -> None:
    seen = []
    ledger.emit(_note(1), sink=seen.append)
    assert len(seen) == 1

    flag = paths.index_dirty_path()
    assert not flag.exists()

    def boom(_ev: dict) -> None:
        msg = "index exploded"
        raise RuntimeError(msg)

    # sink failure does NOT propagate — event is durable, flag is touched
    off = ledger.emit(_note(2), sink=boom)
    assert flag.exists()
    assert off > 0
    assert len(_parsed(paths.events_path())) == 2  # noqa: PLR2004 -- 断言字面量


@pytest.mark.usefixtures("broot")
def test_emit_batch_sink_failures_isolated_per_event() -> None:
    seen = []

    def flaky(ev: dict) -> None:
        if ev["seq"] == 2:  # noqa: PLR2004 -- 测试桩内嵌字面量
            msg = "one bad apply"
            raise RuntimeError(msg)
        seen.append(ev["seq"])

    ledger.emit_batch([_note(1), _note(2), _note(3)], sink=flaky)
    assert seen == [1, 3]
    assert paths.index_dirty_path().exists()
    assert len(_parsed(paths.events_path())) == 3  # noqa: PLR2004 -- 断言字面量


# --- run_seq minting ------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_mint_run_seq_monotonic() -> None:
    n1 = _mint("m1")
    n2 = _mint("m2")
    n3 = _mint("m3")
    assert (n1, n2, n3) == (1, 2, 3)
    assert int(paths.seqfile_path().read_text().strip()) == 3  # noqa: PLR2004 -- 断言字面量


@pytest.mark.usefixtures("broot")
def test_mint_emits_run_registered_and_dual_writes() -> None:
    n = _mint("mreg")
    got = _parsed(paths.events_path())
    reg = [ev for ev in got if ev["type"] == "run_registered"]
    assert len(reg) == 1
    ev = reg[0]
    assert ev["run_seq"] == n
    assert ev["run"] == "mreg"
    assert ev["kind"] == KIND
    # dual-written into the run dir shard
    shard = paths.run_dir(KIND, DATE, "mreg") / "events.jsonl"
    assert [e["run_seq"] for e in _parsed(shard)] == [n]


@pytest.mark.usefixtures("broot")
def test_mint_survives_seqfile_deletion_via_scanback() -> None:
    n1 = _mint("del1")
    _mint("del2")
    paths.seqfile_path().unlink()
    n3 = _mint("del3")
    assert n3 == n1 + 2  # scanback over the hot tail recovered the high-water


@pytest.mark.usefixtures("broot")
def test_mint_ignores_runs_jsonl() -> None:
    # A report row claiming run_seq=999 must not influence minting.
    ledger.append_run_row({"run": "ghost", "run_seq": 999, "fake": True})
    assert _mint("real1") == 1


@pytest.mark.usefixtures("broot")
def test_scanback_ignores_non_run_registered_run_seq() -> None:
    # A note carrying a foreign run_seq must not feed the mint max.
    ev = events.make_event(
        events.T_NOTE, run="r", seq=1, text="x", level="info", run_seq=999
    )
    ledger.emit(ev)
    assert ledger.scanback_max_run_seq() == 0
    assert _mint("nb1") == 1


@pytest.mark.usefixtures("broot")
def test_scanback_tolerates_bad_lines() -> None:
    _mint("sb1")
    p = paths.events_path()
    with p.open("ab") as f:
        f.write(b"this is not json\n")
    assert ledger.scanback_max_run_seq() == 1


@pytest.mark.usefixtures("broot")
def test_scanback_finds_seq_beyond_window(monkeypatch: pytest.MonkeyPatch) -> None:
    _mint("old")
    # shrink the window so the run_registered falls out of the tail window —
    # the fallback full forward scan must still find it
    window = 64
    monkeypatch.setattr("kernel.ledger._SCANBACK_WINDOW", window)
    for i in range(20):
        ledger.emit(_note(i, "f" * 512))
    assert paths.events_path().stat().st_size > window
    assert ledger.scanback_max_run_seq() == 1


@pytest.mark.usefixtures("broot")
def test_scanback_sees_sealed_segments_when_tail_empty() -> None:
    n = _mint("sealed1")
    zst = ledger.seal_if_needed(max_bytes=1)
    assert zst is not None
    assert paths.events_path().stat().st_size == 0  # tail empty after seal
    assert ledger.scanback_max_run_seq() == n


@pytest.mark.usefixtures("broot")
def test_append_run_row_report_only() -> None:
    off = ledger.append_run_row({"run": "r1", "run_seq": 1, "status": "done"})
    assert off == 0
    rows = _parsed(paths.runs_jsonl_path())
    assert rows == [{"run": "r1", "run_seq": 1, "status": "done"}]


# --- watermark ------------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_watermark_offset_exact() -> None:
    assert ledger.watermark_offset() == 0
    ev = _note(1)
    off = ledger.emit(ev)
    wm = ledger.watermark_offset()
    assert wm == off + len(events.dumps(ev)) + 1
    assert wm == paths.events_path().stat().st_size


@pytest.mark.usefixtures("broot")
def test_watermark_stops_at_torn_tail() -> None:
    ev = _note(1)
    ledger.emit(ev)
    clean = paths.events_path().stat().st_size
    with paths.events_path().open("ab") as f:
        f.write(b'{"partial":true')  # lockless torn append
    assert ledger.watermark_offset() == clean


# --- sealing ----------------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_seal_rotation_produces_zst_chain_and_empty_tail() -> None:
    n1 = _mint("s1")
    for i in range(4):
        ledger.emit(_cell(i))
    n2 = _mint("s2")
    ts = time.time()
    zst = ledger.seal_if_needed(now_ts=ts, max_bytes=1)

    assert zst is not None
    assert zst.exists()
    assert zst.name == f"events-{n1:08d}-{n2:08d}-{int(ts)}.jsonl.zst"
    # raw segment kept alongside the zst until gc
    raw = Path(str(zst)[: -len(".zst")])
    assert raw.exists()
    # hot tail recreated empty
    assert paths.events_path().exists()
    assert paths.events_path().stat().st_size == 0

    rows = _parsed(paths.seals_path())
    assert len(rows) == 1
    row = rows[0]
    assert row["file"] == zst.name
    assert row["prev_seal_sha"] == "0" * 64  # genesis
    assert row["zst_sha"] == hashlib.sha256(zst.read_bytes()).hexdigest()
    assert row["raw_sha"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert row["lines"] == 6  # noqa: PLR2004 -- 断言字面量（2 run_registered + 4 cells）
    assert row["bytes"] == raw.stat().st_size

    # second seal links the hash chain
    ledger.emit(_note(99))
    zst2 = ledger.seal_if_needed(now_ts=ts + 1, max_bytes=1)
    assert zst2 is not None
    rows = _parsed(paths.seals_path())
    assert len(rows) == 2  # noqa: PLR2004 -- 断言字面量
    assert rows[1]["prev_seal_sha"] == rows[0]["zst_sha"]


@pytest.mark.usefixtures("broot")
def test_iter_all_events_spans_sealed_and_hot() -> None:
    _mint("ord1")
    for i in range(3):
        ledger.emit(_note(i))
    zst = ledger.seal_if_needed(now_ts=time.time(), max_bytes=1)
    assert zst is not None
    for i in range(3, 6):
        ledger.emit(_note(i))

    items = list(ledger.iter_all_events())
    names = [s for s, _o, _e in items]
    # the surviving raw segment is preferred over its .zst while both exist
    # — either name labels the same segment
    sealed_src = {zst.name, zst.name.removesuffix(".zst")}
    assert names[0] in sealed_src
    assert names[-1] == "events.jsonl"
    # authoritative order: sealed segment first, then hot tail
    boundary = names.index("events.jsonl")
    assert set(names[:boundary]) == {names[0]}
    got = [e for _s, _o, e in items if e]
    seqs = [e.get("seq") for e in got if e.get("type") == "note"]
    assert seqs == [0, 1, 2, 3, 4, 5]
    # offsets are per-source byte offsets, monotonic within each source
    per_src: dict[str, list[int]] = {}
    for s, o, _e in items:
        per_src.setdefault(s, []).append(o)
    for offs in per_src.values():
        assert offs == sorted(offs)


@pytest.mark.usefixtures("broot")
def test_iter_all_events_yields_none_on_bad_lines() -> None:
    ledger.emit(_note(1))
    with paths.events_path().open("ab") as f:
        f.write(b"garbage line\n")
    ledger.emit(_note(2))
    items = list(ledger.iter_all_events())
    evs = [e for _s, _o, e in items]
    assert evs[1] is None
    assert evs[0] is not None
    assert evs[2] is not None


@pytest.mark.usefixtures("broot")
def test_seal_age_trigger() -> None:
    old = events.make_event(
        events.T_NOTE,
        run="r",
        seq=1,
        text="old",
        level="info",
        ts=time.time() - 40 * 86400,
    )
    ledger.emit(old)
    zst = ledger.seal_if_needed(max_age_s=30 * 86400)
    assert zst is not None


@pytest.mark.usefixtures("broot")
def test_seal_not_needed_returns_none() -> None:
    ledger.emit(_note(1))  # fresh, small
    assert ledger.seal_if_needed() is None


@pytest.mark.usefixtures("broot")
def test_seal_empty_tail_never_seals() -> None:
    assert ledger.seal_if_needed(max_bytes=1) is None


@pytest.mark.usefixtures("broot")
def test_recover_interrupted_seal() -> None:
    """A crashed seal (raw segment, no .zst, no seals row) is completed on the
    next seal_if_needed pass — zst produced, hash-chain row appended."""
    for i in range(3):
        ledger.emit(_cell(i))
    # simulate crash between rename and compress
    sdir = paths.sealed_dir()
    orphan = sdir / "events-00000000-00000000-111.jsonl"
    paths.events_path().rename(orphan)
    # recovery runs inside the next seal_if_needed lock hold, before the
    # seal-needed check — returns None yet still completes the crashed seal
    assert ledger.seal_if_needed() is None
    zst = Path(str(orphan) + ".zst")
    assert zst.exists()
    rows = _parsed(paths.seals_path())
    assert len(rows) == 1
    assert rows[0]["file"] == zst.name
    # hot tail recreated
    assert paths.events_path().exists()
    # and iter_all reads the recovered segment (raw preferred while it
    # survives alongside the .zst)
    assert any(s in (zst.name, orphan.name) for s, _o, _e in ledger.iter_all_events())


@pytest.mark.usefixtures("broot")
def test_recover_drops_corrupt_partial_zst() -> None:
    for i in range(2):
        ledger.emit(_cell(i))
    sdir = paths.sealed_dir()
    orphan = sdir / "events-00000000-00000000-222.jsonl"
    paths.events_path().rename(orphan)
    Path(str(orphan) + ".zst").write_bytes(b"not a zstd frame")
    assert ledger.seal_if_needed() is None  # recovery completes the seal
    zst = Path(str(orphan) + ".zst")
    rows = _parsed(paths.seals_path())
    assert len(rows) == 1
    # the recompressed zst faithfully encodes the raw segment
    assert rows[0]["zst_sha"] == hashlib.sha256(zst.read_bytes()).hexdigest()
    assert rows[0]["raw_sha"] == hashlib.sha256(orphan.read_bytes()).hexdigest()
    seg_evs = [
        e for s, _o, e in ledger.iter_all_events() if s in (zst.name, orphan.name)
    ]
    assert len([e for e in seg_evs if e]) == 2  # noqa: PLR2004 -- 断言字面量


# --- seal_gc ----------------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_seal_gc_deletes_verified_aged_raw() -> None:
    for i in range(3):
        ledger.emit(_cell(i))
    ts = time.time()
    zst = ledger.seal_if_needed(now_ts=ts, max_bytes=1)
    assert zst is not None
    raw = Path(str(zst)[: -len(".zst")])

    # too young — kept
    assert ledger.seal_gc(now_ts=ts) == []
    assert raw.exists()
    # aged past grace — raw deleted, zst kept, still readable
    deleted = ledger.seal_gc(now_ts=ts + 8 * 86400)
    assert deleted == [raw]
    assert not raw.exists()
    assert zst.exists()
    assert any(s == zst.name for s, _o, _e in ledger.iter_all_events())


@pytest.mark.usefixtures("broot")
def test_seal_gc_keeps_unverified() -> None:
    for i in range(2):
        ledger.emit(_cell(i))
    ts = time.time()
    zst = ledger.seal_if_needed(now_ts=ts, max_bytes=1)
    assert zst is not None
    raw = Path(str(zst)[: -len(".zst")])
    zst.write_bytes(b"corrupted")  # tamper — must block deletion
    assert ledger.seal_gc(now_ts=ts + 8 * 86400) == []
    assert raw.exists()


@pytest.mark.usefixtures("broot")
def test_seal_gc_skips_unsealed_raw() -> None:
    # a raw segment with no seals row (interrupted seal) is never gc'd
    sdir = paths.sealed_dir()
    orphan = sdir / "events-00000001-00000001-999.jsonl"
    orphan.write_bytes(events.dumps(_note(1)).encode() + b"\n")
    assert ledger.seal_gc(now_ts=time.time() + 30 * 86400) == []
    assert orphan.exists()


# --- concurrency ------------------------------------------------------------------------


@pytest.mark.usefixtures("broot")
def test_concurrent_emits_serialize() -> None:
    """Two threads appending >4KB lines must produce zero interleaved bytes:
    every line in the file parses as exactly one emitted event."""
    big_a = ["A" * 4096 + str(i) for i in range(8)]
    big_b = ["B" * 4096 + str(i) for i in range(8)]
    errors = []

    def worker(texts: list) -> None:
        try:
            for t in texts:
                ledger.emit(_note(1, t))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=worker, args=(big_a,))
    t2 = threading.Thread(target=worker, args=(big_b,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors
    lines = _lines(paths.events_path())
    assert len(lines) == len(big_a) + len(big_b)
    texts = set()
    for ln in lines:
        ev = json.loads(ln)  # raises if bytes interleaved
        texts.add(ev["text"])
    assert texts == set(big_a) | set(big_b)


@pytest.mark.usefixtures("broot")
def test_concurrent_mints_unique() -> None:
    seqs = []
    errs = []

    def worker(i: int) -> None:
        try:
            seqs.append(_mint(f"cm{i}"))
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs
    assert sorted(seqs) == [1, 2, 3, 4, 5, 6]
