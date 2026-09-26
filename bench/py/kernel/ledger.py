"""Sole write path for ledger/events.jsonl + seal machinery.

Implements the §3.3 write contract and §3.10.5 scale bounds of
docs/spec/bench-trizone.md — every line maps to an attack:

- flock(ledger/.lock, LOCK_EX) for the whole critical section; the lock file
  is created once and NEVER unlinked (flock pins the inode).
- Torn-tail heal before every append: a lockless intruder can only inject
  whole lines, but an interrupted append can leave a partial last line —
  the file is truncated back to just past its last '\\n' before writing.
- ONE os.write syscall per line (per batch) + fsync; the fd never outlives
  the lock hold, so >8KB lines can never tear.
- Dual-write to run_dir/events.jsonl inside the same critical section —
  ledger lost → rebuild from run dirs; run dir lost → ledger has the ledger.
- sink (derived-index apply) runs inside the lock AFTER fsync; on failure we
  touch ledger/.index-dirty (fail-closed, §3.10.6) and continue — the event
  is durable, the index is rebuildable.

Seals (§3.10.5): the hot tail rotates when it exceeds max_bytes OR its oldest
event is older than max_age. Segments land in sealed/ as
events-<first_seq>-<last_seq>-<ts>.jsonl (zero-padded so name-sort equals
chronological order) with a zstd -19 sidecar and a seals.jsonl hash-chain
row (prev_seal_sha links each row to the previous zst). Raw segments are
deleted by seal_gc only after the .zst decodes back to the identical bytes
and the grace age passes — the "index watermark passed" leg is NOT
implementable yet (no index module exists); callers must gate on it
externally until then.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator

from kernel import paths
from kernel.events import (
    T_RUN_REGISTERED,
    EventError,
    dumps,
    iter_jsonl,
    make_event,
    maybe_offload,
    validate,
)

_HEAL_CHUNK = 64 * 1024
_SCANBACK_WINDOW = 8 * 1024 * 1024
_SEQ_NAME_WIDTH = 8  # zero-pad seq fields so name-sort == chronological
_HASH_CHAIN_GENESIS = "0" * 64

DEFAULT_SEAL_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_SEAL_MAX_AGE_S = 30 * 86400
SEAL_GC_MIN_AGE_S = 7 * 86400

_RUN_EVENTS_NAME = "events.jsonl"


def _bin(name: str) -> str:
    """Resolve an external binary on PATH — fail loud when absent."""
    resolved = shutil.which(name)
    if resolved is None:
        msg = f"required binary {name!r} not found on PATH"
        raise RuntimeError(msg)
    return resolved


# --- low-level append machinery -------------------------------------------------


@contextmanager
def _ledger_lock() -> Iterator[None]:
    """Hold LOCK_EX on the immortal ledger/.lock for the critical section.

    A fresh fd per hold: flock locks ride the open file description, so
    concurrent threads/processes each queue on their own fd.
    """
    fd = os.open(paths.ledger_lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except BaseException:
        os.close(fd)
        raise
    try:
        yield
    finally:
        os.close(fd)  # close releases the flock


def _healed_size(fd: int, size: int) -> int:
    """Byte offset just past the last b'\\n' in fd; 0 if the file has none.

    Scans backwards in chunks — O(one chunk) for a clean tail, O(file) only
    for a pathological newline-free file.
    """
    pos = size
    while pos > 0:
        n = min(_HEAL_CHUNK, pos)
        pos -= n
        buf = os.pread(fd, n, pos)
        idx = buf.rfind(b"\n")
        if idx != -1:
            return pos + idx + 1
    return 0


def _fsync_dir(d: Path) -> None:
    """Best-effort fsync of a directory fd — dirent durability after
    create/rename/unlink. Never raises."""
    try:
        fd = os.open(d, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _append_payload_locked(path: Path, payload: bytes) -> int:
    """Heal torn tail, append payload in ONE syscall, fsync. Return base offset.

    Caller must hold the ledger lock. A short write raises OSError — the torn
    remnant is healed away by the next append.
    """
    existed = path.exists()
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        size = os.fstat(fd).st_size
        offset = _healed_size(fd, size) if size else 0
        if offset != size:
            os.ftruncate(fd, offset)
        if payload:
            n = os.write(fd, payload)
            if n != len(payload):
                msg = f"short write {n}/{len(payload)} on {path}"
                raise OSError(msg)
        os.fsync(fd)
    finally:
        os.close(fd)
    if not existed:
        _fsync_dir(path.parent)
    return offset


def _apply_sink(sink, ev: dict) -> None:
    """Index apply inside the lock. Failure touches .index-dirty (fail-closed)
    and is swallowed — the event is already durable, the index rebuildable."""
    if sink is None:
        return
    try:
        sink(ev)
    except Exception:
        paths.index_dirty_path().touch(exist_ok=True)


def _emit_lines_locked(lines: list[bytes], run_dir) -> list[int]:
    """Append pre-serialized lines to the hot tail (one write, one fsync),
    then dual-write to run_dir/events.jsonl in the same critical section.
    Returns each line's byte offset in the hot tail. Caller holds the lock."""
    payload = b"".join(lines)
    base = _append_payload_locked(paths.events_path(), payload)
    offsets = []
    pos = base
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    if run_dir is not None:
        rdir = Path(run_dir)
        try:
            rdir.mkdir(parents=True, exist_ok=True)
            _append_payload_locked(rdir / _RUN_EVENTS_NAME, payload)
        except OSError:
            # The hot tail is already durable — a failed shard write must
            # not abort the emit (caller would retry and double-write the
            # ledger). The shard is a mirror, rebuildable from the ledger;
            # flag the run dir so doctor surfaces the gap.
            with suppress(OSError):
                (rdir / ".shard-dirty").touch()
    return offsets


# --- public write API -------------------------------------------------------------


def _offload_for(ev: dict, run_dir) -> dict:
    """Run-scoped blob offload — the >4KB metrics/errors contract (§3.1)
    covers every writer, kernel cells included. The $blob-rewritten form is
    what the ledger stores AND what the sink applies, so the index never
    diverges from the ledger."""
    if run_dir is None:
        return ev
    return maybe_offload(ev, Path(run_dir) / "derived" / "blobs")


def emit(ev: dict, run_dir: Path | None = None, sink=None) -> int:
    """Validate + durably append one event. Sole write path for events.jsonl.

    Returns the byte offset of the written line in the hot tail.
    """
    ev = _offload_for(ev, run_dir)
    validate(ev)
    line = dumps(ev).encode("utf-8") + b"\n"
    with _ledger_lock():
        offsets = _emit_lines_locked([line], run_dir)
        _apply_sink(sink, ev)
        return offsets[0]


def emit_batch(events: list[dict], run_dir: Path | None = None, sink=None) -> list[int]:
    """Append a whole batch under one lock hold with one fsync per file.

    All events are validated BEFORE the lock is taken — a batch never lands
    partially due to a late validation error. Returns per-line offsets.
    """
    lines = []
    out_evs = []
    for raw_ev in events:
        ev = _offload_for(raw_ev, run_dir)
        validate(ev)
        out_evs.append(ev)
        lines.append(dumps(ev).encode("utf-8") + b"\n")
    if not lines:
        return []
    with _ledger_lock():
        offsets = _emit_lines_locked(lines, run_dir)
        for ev in out_evs:
            _apply_sink(sink, ev)
        return offsets


def append_run_row(row: dict) -> int:
    """Append one row to runs.jsonl under the ledger lock.

    runs.jsonl is a report-only projection — it is NEVER a minting input.
    Returns the byte offset of the written line.
    """
    line = json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    with _ledger_lock():
        return _append_payload_locked(paths.runs_jsonl_path(), line)


# --- run_seq minting ---------------------------------------------------------------


def _read_seqfile() -> int:
    """seqfile high-water; missing file reads as 0, garbage fails loud."""
    try:
        return int(paths.seqfile_path().read_text().strip() or "0")
    except FileNotFoundError:
        return 0


def _write_seqfile(n: int) -> None:
    """In-place truncate+rewrite + fsync (§3.3 rewrite verb — never os.replace)."""
    fd = os.open(paths.seqfile_path(), os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{n}\n".encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _run_seq_of_event(ev) -> int:
    if isinstance(ev, dict) and ev.get("type") == T_RUN_REGISTERED:
        seq = ev.get("run_seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            return seq
    return 0


def _parse_line(raw: bytes):
    """json.loads a raw line — tolerant per iter_jsonl contract. None on bad."""
    try:
        ev = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    return ev if isinstance(ev, dict) else None


def _run_seq_of_raw(raw: bytes) -> int:
    return _run_seq_of_event(_parse_line(raw))


def scanback_max_run_seq() -> int:
    """Max run_seq over run_registered events, per §3.10.5 minting rules.

    Reads the last ~8MB of the hot tail backwards-window; falls back to a
    full forward scan when the window holds no run_registered. Tolerant of
    unparseable lines per the iter_jsonl contract. If the hot tail has no
    run_registered at all (e.g. it was just sealed), sealed segments are
    consulted so a lost seqfile right after a seal cannot mint a colliding
    seq — a strict extension of the spec's hot-tail wording, same direction.
    """
    p = paths.events_path()
    if p.exists():
        size = p.stat().st_size
        window = min(size, _SCANBACK_WINDOW)
        best = 0
        if window:
            with open(p, "rb") as f:
                f.seek(size - window)
                tail = f.read()
            lines = tail.split(b"\n")
            if size > window:
                lines = lines[1:]  # first element is a partial line
            for raw in lines:
                seq = _run_seq_of_raw(raw)
                if seq:
                    best = max(best, seq)
            if best:
                return best
        if size > window:
            # Window held no run_registered — full forward scan.
            for _ln, ev, _raw in iter_jsonl(p):
                seq = _run_seq_of_event(ev)
                if seq:
                    best = max(best, seq)
            if best:
                return best
    # Hot tail yielded nothing — consult sealed segments (crash-recovery leg).
    best = 0
    for _name, _off, ev in iter_sealed_events():
        seq = _run_seq_of_event(ev)
        if seq:
            best = max(best, seq)
    return best


def mint_run_seq(run: str, kind: str, date: str, slug: str, spec_hash: str) -> int:
    """Mint the next run_seq under the ledger lock (§3.10.5).

    n = max(seqfile high-water, scanback max run_seq) + 1. The seqfile is
    authoritative; runs.jsonl is never consulted. seqfile write and the
    run_registered event land in the same lock window — a crash between them
    leaves the seqfile ahead of events (gap, never a collision).
    """
    with _ledger_lock():
        n = max(_read_seqfile(), scanback_max_run_seq()) + 1
        _write_seqfile(n)
        ev = make_event(
            T_RUN_REGISTERED,
            run=run,
            run_seq=n,
            kind=kind,
            date=date,
            slug=slug,
            spec_hash=spec_hash,
            ts_start=round(time.time(), 3),
        )
        rdir = paths.run_dir(kind, date, slug)
        # The (kind,date,slug) triple alone names the run dir — two runs
        # sharing it would interleave one shard (two run_registered rows,
        # merged cells/cases/work). Refuse when the shard is already bound:
        # a run_registered line is the dir's ownership marker.
        shard = rdir / _RUN_EVENTS_NAME
        if shard.is_file():
            for _ln, prev, _raw in iter_jsonl(shard):
                if isinstance(prev, dict) and prev.get("type") == T_RUN_REGISTERED:
                    msg = (
                        f"{rdir} shard already bound to run "
                                                f"{prev.get('run')!r} (run_seq="
                                                f"{prev.get('run_seq')!r}) — refusing to share a "
                                                "shard across runs"
                    )
                    raise EventError(
                        msg
                    )
        _emit_lines_locked([dumps(ev).encode("utf-8") + b"\n"], rdir)
        # runs.jsonl is report-only but the §3.10.5 doctor invariant expects
        # mint parity — every mint (real-run AND import-run path) appends
        # its row in the same lock window.
        row = {
            "run": run, "run_seq": n, "kind": kind, "date": date,
            "slug": slug, "spec_hash": spec_hash,
            "ts_start": ev["ts_start"],
        }
        _append_payload_locked(
            paths.runs_jsonl_path(),
            json.dumps(row, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8") + b"\n")
        _fsync_dir(rdir)  # dirent durability for the freshly created run dir
        return n


# --- read side ----------------------------------------------------------------------


def watermark_offset() -> int:
    """Byte offset just past the last '\\n' in events.jsonl — the tail-ingest
    high-water mark (§3.2). 0 when the hot tail is missing or empty."""
    p = paths.events_path()
    if not p.exists():
        return 0
    fd = os.open(p, os.O_RDONLY)
    try:
        size = os.fstat(fd).st_size
        return _healed_size(fd, size) if size else 0
    finally:
        os.close(fd)


def events_file_age() -> float:
    """mtime-based age of the hot tail in seconds; 0 when missing."""
    try:
        return time.time() - paths.events_path().stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _iter_events_file(path: Path):
    """Yield (path.name, byte_offset, ev|None) per non-empty line."""
    off = 0
    with open(path, "rb") as f:
        for line in f:
            start = off
            off += len(line)
            body = line.rstrip(b"\n")
            if not body:
                continue
            yield path.name, start, _parse_line(body)


def _iter_zst(seg: Path):
    """Yield (seg.name, decompressed_byte_offset, ev|None) via zstdcat."""
    proc = subprocess.Popen(
        [_bin("zstdcat"), str(seg)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    off = 0
    completed = False
    try:
        for line in proc.stdout:
            start = off
            off += len(line)
            body = line.rstrip(b"\n")
            if not body:
                continue
            yield seg.name, start, _parse_line(body)
        completed = True
    finally:
        if not completed and proc.poll() is None:
            proc.kill()  # consumer abandoned the generator mid-stream
        proc.stdout.close()
        rc = proc.wait()
    if completed and rc != 0:
        msg = f"zstdcat rc={rc} on {seg}"
        raise RuntimeError(msg)


def _sealed_segments(sdir: Path) -> list[str]:
    """Segment stems (``events-*.jsonl``) present in sealed/, sorted — a raw
    segment and its ``.zst`` product share the stem."""
    names: set = set()
    for p in sdir.iterdir():
        n = p.name
        if n.endswith(".jsonl.zst"):
            names.add(n[: -len(".zst")])
        elif n.endswith(".jsonl"):
            names.add(n)
    return sorted(names)


def zst_verified(zst: Path) -> bool:
    """Does the .zst decode to bytes matching its seals-row ``raw_sha``?

    seal_gc deletes the raw only after _zst_decodes_to passes, so a row'd
    zst carries the raw's sha as its anchor — decode-and-hash beats trusting
    a clean exit code (rc=0 garbage passthrough is a real hazard). No seals
    row → False: the zst is unanchored, and a raw sibling (interrupted seal)
    is the preferred source anyway.
    """
    want = None
    for r in _read_seal_rows():
        if r.get("file") == Path(zst).name:
            want = r.get("raw_sha")
            break
    if not isinstance(want, str) or not want:
        return False
    try:
        proc = subprocess.Popen(
            [_bin("zstdcat"), str(zst)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, RuntimeError):
        return False
    assert proc.stdout is not None
    h = hashlib.sha256()
    try:
        for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
            h.update(chunk)
    finally:
        proc.stdout.close()
        rc = proc.wait()
    return rc == 0 and h.hexdigest() == want


def iter_sealed_events():
    """Yield (source_name, offset, ev|None) over sealed segments only, in
    name-sort (== chronological) order.

    The raw ``.jsonl`` wins when present (it IS the renamed hot tail —
    byte-exact and cheaper than decoding). A ``.zst`` is read only after
    zst_verified passes against its seals-row raw_sha; an unanchored or
    corrupt segment is skipped, never trusted silently.
    """
    sdir = paths.sealed_dir()
    if not sdir.is_dir():
        return
    for stem in _sealed_segments(sdir):
        raw = sdir / stem
        zst = Path(str(raw) + ".zst")
        if raw.exists():
            yield from _iter_events_file(raw)
        elif zst.exists() and zst_verified(zst):
            yield from _iter_zst(zst)


def iter_all_events():
    """Yield (source_name, offset, ev|None) in authoritative append order:
    sealed segments (raw preferred, verified .zst otherwise), then the hot
    tail events.jsonl.

    offset is the byte offset of the line start within that source (the
    decompressed stream for sealed segments). Unparseable lines yield
    ev=None per the iter_jsonl contract — skip-and-warn, never crash.
    """
    yield from iter_sealed_events()
    hot = paths.events_path()
    if hot.exists():
        yield from _iter_events_file(hot)


# --- sealing ------------------------------------------------------------------------


class _SegStats(NamedTuple):
    lines: int
    nbytes: int
    sha256: str
    first_seq: int
    last_seq: int


def _scan_segment(path: Path) -> _SegStats:
    """One streaming pass: sha256, non-empty line count, run_seq coverage."""
    h = hashlib.sha256()
    lines = 0
    nbytes = 0
    seqs = []
    with open(path, "rb") as f:
        for line in f:
            nbytes += len(line)
            h.update(line)
            body = line.rstrip(b"\n")
            if not body:
                continue
            lines += 1
            ev = _parse_line(body)
            if ev is None:
                continue
            seq = ev.get("run_seq")
            if isinstance(seq, int) and not isinstance(seq, bool):
                seqs.append(seq)
    return _SegStats(
        lines=lines,
        nbytes=nbytes,
        sha256=h.hexdigest(),
        first_seq=min(seqs) if seqs else -1,
        last_seq=max(seqs) if seqs else -1,
    )


def _oldest_event_ts(path: Path):
    """ts of the first parseable event, or None (caller falls back to mtime)."""
    try:
        with open(path, "rb") as f:
            for line in f:
                body = line.rstrip(b"\n")
                if not body:
                    continue
                ev = _parse_line(body)
                if ev is None:
                    continue
                ts = ev.get("ts")
                return ts if isinstance(ts, (int, float)) else None
    except FileNotFoundError:
        return None
    return None


def _seal_needed(now: float, max_bytes: int, max_age_s: float) -> bool:
    p = paths.events_path()
    try:
        st = p.stat()
    except FileNotFoundError:
        return False
    if st.st_size == 0:
        return False
    if st.st_size > max_bytes:
        return True
    oldest = _oldest_event_ts(p)
    if oldest is None:
        oldest = st.st_mtime  # no parseable ts — file age is the proxy
    return (now - oldest) > max_age_s


def _free_segment_name(sdir: Path, first_seq: int, last_seq: int, now: float) -> Path:
    """events-<first>-<last>-<ts>.jsonl, zero-padded; .N suffix on collision."""
    base = (
        f"events-{first_seq:0{_SEQ_NAME_WIDTH}d}-"
        f"{last_seq:0{_SEQ_NAME_WIDTH}d}-{int(now)}"
    )
    cand = sdir / f"{base}.jsonl"
    i = 0
    while cand.exists() or Path(str(cand) + ".zst").exists():
        i += 1
        cand = sdir / f"{base}.{i}.jsonl"
    return cand


def _zstd_compress(raw: Path) -> Path:
    """zstd -19, keep the raw segment. Returns the .jsonl.zst path."""
    zst = Path(str(raw) + ".zst")
    subprocess.run(
        [_bin("zstd"), "-q", "-19", "-k", "-f", str(raw)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not zst.exists():
        msg = f"zstd produced no output for {raw}"
        raise RuntimeError(msg)
    return zst


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _zst_decodes_to(zst: Path, raw: Path) -> bool:
    """Strongest verify: the .zst decompresses to the exact raw bytes."""
    try:
        proc = subprocess.Popen(
            [_bin("zstdcat"), str(zst)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, RuntimeError):
        return False
    assert proc.stdout is not None
    h = hashlib.sha256()
    try:
        for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
            h.update(chunk)
    finally:
        proc.stdout.close()
        rc = proc.wait()
    if rc != 0:
        return False
    return h.hexdigest() == _sha256_file(raw)


def _read_seal_rows() -> list[dict]:
    """All parseable seals.jsonl rows, in file order (tolerant read)."""
    rows = []
    p = paths.seals_path()
    if not p.exists():
        return rows
    for _ln, row, _raw in iter_jsonl(p):
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _last_seal_zst_sha() -> str:
    rows = _read_seal_rows()
    if rows:
        sha = rows[-1].get("zst_sha")
        if isinstance(sha, str):
            return sha
    return _HASH_CHAIN_GENESIS


def _append_jsonl_row(path: Path, row: dict) -> int:
    line = json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    return _append_payload_locked(path, line)


def _seals_row_for(zst: Path, stats: _SegStats, ts: float) -> dict:
    return {
        "file": zst.name,
        "raw_sha": stats.sha256,
        "zst_sha": _sha256_file(zst),
        "prev_seal_sha": _last_seal_zst_sha(),
        "lines": stats.lines,
        "bytes": stats.nbytes,
        "ts": ts,
    }


def _recreate_hot_tail(hot: Path) -> None:
    fd = os.open(hot, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _recover_interrupted_seals() -> None:
    """Finish seals that crashed mid-flight (caller holds the ledger lock).

    A raw .jsonl in sealed/ whose .zst has no seals.jsonl row is an
    interrupted seal — the hash chain never recorded it. Recompress when the
    .zst is missing or fails to decode back to the raw bytes, then append
    the missing row. Also recreates the hot tail if the crash hit between
    the rename and the recreate.
    """
    sdir = paths.sealed_dir()
    if not sdir.is_dir():
        return
    sealed_names = {
        r.get("file") for r in _read_seal_rows() if isinstance(r.get("file"), str)
    }
    for raw in sorted(sdir.glob("*.jsonl")):
        zst = Path(str(raw) + ".zst")
        if zst.name in sealed_names:
            continue  # fully sealed — awaiting seal_gc
        if zst.exists() and not _zst_decodes_to(zst, raw):
            zst.unlink()  # partial/corrupt product of the crashed compress
        if not zst.exists():
            _zstd_compress(raw)
        if not _zst_decodes_to(zst, raw):
            msg = f"sealed segment {zst} fails verification"
            raise RuntimeError(msg)
        _append_jsonl_row(
            paths.seals_path(),
            _seals_row_for(zst, _scan_segment(raw), time.time()),
        )
        sealed_names.add(zst.name)
    if not paths.events_path().exists():
        _recreate_hot_tail(paths.events_path())


def seal_if_needed(
    now_ts: float | None = None,
    max_bytes: int = DEFAULT_SEAL_MAX_BYTES,
    max_age_s: float = DEFAULT_SEAL_MAX_AGE_S,
) -> Path | None:
    """Rotate the hot tail into sealed/ when it exceeds size or age bounds.

    Double-trigger per §3.10.5: size > max_bytes OR oldest event older than
    max_age_s. Whole operation under the ledger lock: rename → zstd -19 →
    seals.jsonl hash-chain row → recreate empty tail. Returns the .jsonl.zst
    path, or None when no seal was needed.
    """
    now = time.time() if now_ts is None else float(now_ts)
    with _ledger_lock():
        _recover_interrupted_seals()
        if not _seal_needed(now, max_bytes, max_age_s):
            return None
        hot = paths.events_path()
        stats = _scan_segment(hot)
        # Segments with no run_seq-carrying events borrow the seqfile
        # high-water so name-sort stays chronological.
        hw = _read_seqfile()
        first = stats.first_seq if stats.first_seq >= 0 else hw
        last = stats.last_seq if stats.last_seq >= 0 else hw
        sdir = paths.sealed_dir()
        sdir.mkdir(parents=True, exist_ok=True)
        raw_dst = _free_segment_name(sdir, first, last, now)
        os.rename(hot, raw_dst)
        try:
            zst = _zstd_compress(raw_dst)
            _append_jsonl_row(
                paths.seals_path(), _seals_row_for(zst, stats, now)
            )
        finally:
            _recreate_hot_tail(hot)  # emitters must never see a missing tail
        _fsync_dir(paths.ledger_dir())
        _fsync_dir(sdir)
        return zst


def seal_gc(now_ts: float | None = None, min_age_s: float = SEAL_GC_MIN_AGE_S,
            *, ingested: set | None = None) -> list[Path]:
    """Delete raw sealed .jsonl segments whose .zst is verified and aged out.

    Per §3.10.5 a raw segment is deletable when its .zst is verified, the
    index watermark has passed it, and it is older than the grace age. The
    watermark leg arrives via ``ingested`` — stem names the index reports
    fully replayed (``Index.sealed_done()``); None means the caller asserts
    coverage. Returns the deleted raw paths.
    """
    now = time.time() if now_ts is None else float(now_ts)
    deleted: list[Path] = []
    with _ledger_lock():
        sdir = paths.sealed_dir()
        if not sdir.is_dir():
            return []
        rows = {
            r.get("file"): r
            for r in _read_seal_rows()
            if isinstance(r.get("file"), str)
        }
        for raw in sorted(sdir.glob("*.jsonl")):
            zst = Path(str(raw) + ".zst")
            row = rows.get(zst.name)
            if row is None or not zst.exists():
                continue  # not a completed seal — recovery's job, never gc's
            if ingested is not None and raw.name not in ingested:
                continue  # index hasn't replayed this segment yet
            ts = row.get("ts")
            age_base = ts if isinstance(ts, (int, float)) else raw.stat().st_mtime
            if now - age_base <= min_age_s:
                continue
            if not _zst_decodes_to(zst, raw):
                continue
            raw.unlink()
            deleted.append(raw)
        if deleted:
            _fsync_dir(sdir)
    return deleted
