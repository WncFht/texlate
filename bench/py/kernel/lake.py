"""Lake zone — the rebuildable corpus (design §3.10.3 lazy three-state
machine, §3.10.1 capacity budget, R9 fetch-storm guard).

Layout::

    lake/corpus/{source}/{safe_id}/    cell tree
        raw/        canonical layer (payload as fetched — may be absent
                    after a raw-tier eviction)
        extracted/  re-derivable projection — evicted FIRST
        meta.json   commit marker: {n_files, ...}
        files.txt / mtree.txt          optional bookkeeping (not payload)
    lake/corpus/catalog.jsonl          dynamic state book — the projection
                                       of ledger lake_cell events; last
                                       row wins per idc
    lake/tmp/rebuild/{run_seq}/{safe_id}.stage/
                                       atomic build area — a cell is
                                       constructed whole here, then
                                       rename()'d into place (§3.10.8:
                                       "物化真原子化")
    lake/.locks/{safe_id}.lock         per-cell flock — never unlinked (R21)

State machine: ``skeleton → hydrating → hydrated ⇄ pinned`` plus tiered
``raw_only`` (extracted evicted, raw kept — local re-extract is free) and
``failed`` (manifest-seeded stub/pdf_only/fetch_error, never in the fetch
set). ``manifested:false`` marks orphan cells — first eviction candidates.

Pin is a FIELD (``pinned:true`` on the catalog row) anchored by a
cell-side ``PINNED`` marker file — never a state: ``state=='pinned'``
silently un-pins on the next ``set()`` (the merge carries fields, not the
replaced state), so the file is the truth the row projects and every
byte-deleting verb (evict tiers, shrink_shell, remove_cell_tree, orphan
adoption) must consult the marker, not just the row.

Read predicate (THE consumer gate, §3.10.3): ``is_complete`` = cell dir
exists ∧ meta.json parseable ∧ meta.n_files == actual payload file count —
half trees NEVER satisfy, so a paid cell never projects a torn corpus entry.

Concurrency: hydrate takes ``.locks/{safe_id}.lock`` LOCK_EX (blocking) and
re-checks completeness inside the lock — two concurrent hydrations of the
same cell degrade to one-fetch-one-wait ("同格两 run 同拉退化为一拉一等").
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import tarfile
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

from kernel import events, fsutil, ledger, locks, paths, vault
from kernel.events import iter_jsonl, make_event
from kernel.idnorm import safe_id

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = [
    "PIN_MARKER",
    "DiskPressureError",
    "LakeCatalog",
    "admit",
    "cell_dir",
    "cell_pinned",
    "evict",
    "evict_cell",
    "hydrate",
    "is_complete",
    "lake_lock",
    "pin",
    "register_skeleton",
    "shrink_shell",
    "unpin",
]

_HEAL_CHUNK = 64 * 1024

#: Pin truth file — lives at the cell dir root (``{cell}/PINNED`` for lake
#: cells, ``work/{safe_id}/PINNED`` for run cells). Every byte-deleting verb
#: honors it; the catalog ``pinned`` field is its ledger-replayable
#: projection, not the source of truth.
PIN_MARKER = "PINNED"

# Bookkeeping files that are never counted as cell payload. PIN_MARKER is
# bookkeeping by definition — without the exclusion a pinned cell's payload
# count inflates by one and is_complete can never vouch for it again.
_BOOKKEEP = {"meta.json", "mtree.txt", "files.txt", PIN_MARKER}

_ENV_LAKE_CAP_GB = "TEXLATE_LAKE_CAP_GB"
_ENV_LAKE_FLOOR_GB = "TEXLATE_LAKE_FLOOR_GB"
_ENV_MIN_FREE_GB = "TEXLATE_BENCH_MIN_FREE_GB"
_GIB = 1024 ** 3

# Files kept by shrink_shell on a terminal cell (§3.10.1 shell set).
# ``xlat-state.*``/``state.*`` directories are additionally preserved — the
# chunk-level paid checkpoint is prune-exempt until vaulted (§3.10.1
# revision + R17: losing it re-burns paid quota on resume). The cell-side
# dir is ``state.{arm}[@{variant}]`` (xlat-state is the vault kind name);
# both spellings ride the glob. PIN_MARKER rides the keep set so a shrink
# can never eat the pin marker (measured gap), though a pinned cell
# short-circuits shrink_shell before the keep-list is even consulted.
_SHELL_KEEP_EXACT = frozenset({
    "receipt.json", "parse.json", ".xlat-arm.json", ".lock", PIN_MARKER,
})
_SHELL_KEEP_GLOB = (
    "xlat-*.jsonl",
    "xlat-state", "xlat-state.*",
    "state", "state.*",
)


# --- small append helper ---------------------------------------------------------

def _append_line(path: Path, payload: bytes) -> None:
    """Heal torn tail, append payload in ONE os.write, fsync — same contract
    as the ledger path, serialized through ``lake/.locks/.catalog.lock``:
    different cells' writers append the shared catalog concurrently, and an
    unlocked heal-truncate can clip a racing writer's fresh line."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    catalog_lock = paths.lake_locks_dir() / ".catalog.lock"
    with locks.flock(catalog_lock, exclusive=True, blocking=True):
        existed = path.exists()
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            size = os.fstat(fd).st_size
            offset = size
            pos = size
            while pos > 0:
                n = min(_HEAL_CHUNK, pos)
                pos -= n
                buf = os.pread(fd, n, pos)
                idx = buf.rfind(b"\n")
                if idx != -1:
                    offset = pos + idx + 1
                    break
            else:
                offset = 0
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
        fsutil.fsync_dir(path.parent)


def _append_row(path: Path, row: dict) -> None:
    line = json.dumps(
        row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    _append_line(path, line)


# --- paths / cell introspection -----------------------------------------------------

def cell_dir(idc: str, source: str = "arxiv") -> Path:
    """``lake/corpus/{source}/{safe_id}`` — pure path math."""
    return paths.lake_corpus_dir() / source / safe_id(idc)


def cell_pinned(cell: Path) -> bool:
    """Cell-side pin truth: ``{cell}/PINNED`` exists."""
    return (Path(cell) / PIN_MARKER).exists()


def _read_meta(cell: Path) -> dict:
    """Parse cell meta.json; {} on any error (a torn meta is no meta)."""
    try:
        meta = json.loads((cell / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _payload_count(cell: Path) -> int:
    """Actual payload file count under a cell dir: every regular file except
    top-level bookkeeping names and anything under ``raw/`` (the canonical
    layer is not the extracted projection this count audits)."""
    cell = Path(cell)
    n = 0
    if not cell.is_dir():
        return 0
    for p, kind in fsutil._iter_tree(cell):
        if kind != "file":
            continue
        rel = p.relative_to(cell)
        if rel.parts[0] == "raw":
            continue
        if len(rel.parts) == 1 and rel.name in _BOOKKEEP:
            continue
        n += 1
    return n


def is_complete(idc: str, source: str = "arxiv") -> bool:
    """THE read predicate: dir exists ∧ meta.json parseable ∧
    meta.n_files == actual payload file count. Half trees never satisfy —
    a torn cell falls back to the same-lease self-hydration path instead of
    projecting partial bytes into a paid stage."""
    d = cell_dir(idc, source)
    if not d.is_dir():
        return False
    n_files = _read_meta(d).get("n_files")
    if not isinstance(n_files, int) or isinstance(n_files, bool):
        return False
    # zero-payload is not completeness — n_files=0 tautologically matches an
    # empty tree. The catalog records that outcome as 'empty'; the read
    # predicate must never vouch for it.
    return n_files > 0 and n_files == _payload_count(d)


# --- locks ------------------------------------------------------------------------------


@contextmanager
def lake_lock(safe: str) -> Iterator[int]:
    """Hold LOCK_EX (blocking) on ``lake/.locks/{safe_id}.lock``.

    The per-cell serializer: hydrate/evict hold it exclusively, read-only
    projections may hold it shared. The lock file is immortal (R21).
    """
    lock_path = paths.lake_locks_dir() / f"{safe}.lock"
    with locks.flock(lock_path, exclusive=True, blocking=True) as fd:
        yield fd


# --- catalog (the dynamic state book) ----------------------------------------------------


class LakeCatalog:
    """catalog.jsonl — per-idc lake state, last row wins.

    Written rows are self-contained: every ``set``/``mark_used`` merges the
    new keys onto the stored row before appending, so a single append both
    carries the full projected state and keeps the file append-only.
    """

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    @classmethod
    def load(cls) -> LakeCatalog:
        """Tolerantly parse catalog.jsonl — bad lines are skipped, last row
        wins per idc (the file is a rebuildable projection of lake_cell
        events, never a second source of truth)."""
        cat = cls()
        p = paths.lake_catalog_path()
        if not p.exists():
            return cat
        for _ln, row, _raw in iter_jsonl(p):
            if not isinstance(row, dict):
                continue
            idc = row.get("idc")
            if not isinstance(idc, str) or not idc:
                continue
            cat._rows[idc] = row
        return cat

    def rows(self) -> dict:
        """``{idc: row}`` projection — shallow copy, safe to mutate."""
        return dict(self._rows)

    def state(self, idc: str) -> str:
        """Current state string; ``'absent'`` for unknown cells."""
        return self._rows.get(idc, {}).get("state", "absent")

    def set(self, idc: str, state: str, sink=None, run_dir=None,
            **kw) -> dict:
        """Transition ``idc`` to ``state``: emit the ledger lake_cell event
        FIRST, then append the merged row to catalog.jsonl — the catalog is
        declared a projection of the event stream, so a crash between the
        two must leave a replayable event, never a catalog row with no
        history. The merge base is re-read from the file itself: a catalog
        instance loaded once goes stale the moment another writer appends,
        and merging onto stale state silently clobbers the interleaved
        row's fields. Returns the stored row."""
        row = {**_latest_row(idc), "idc": idc, "state": state,
               "ts": round(time.time(), 3), **kw}
        ledger.emit(_lake_event(row), run_dir=run_dir, sink=sink)
        _append_row(paths.lake_catalog_path(), row)
        self._rows[idc] = row
        return row

    def set_bulk(self, updates, sink=None, run_dir=None) -> list:
        """Import-scale variant of ``set``: one file rescan + one
        emit_batch + one catalog append for the whole ``updates`` iterable
        of ``(idc, state, kw)`` triples, instead of per-row work (the
        per-row file rescan in ``set`` is O(n²) over a 10⁴-row seeding).

        Same crash order as ``set`` — all events land on the ledger before
        any catalog row — and the same non-atomic merge window (fresh file
        state read once up front; a concurrent writer interleaving between
        the rescan and the append can lose fields, identical to ``set``).
        Returns the stored rows."""
        updates = list(updates)
        if not updates:
            return []
        p = paths.lake_catalog_path()
        latest: dict[str, dict] = {}
        if p.exists():
            for _ln, row, _raw in iter_jsonl(p):
                if isinstance(row, dict) and isinstance(row.get("idc"), str):
                    latest[row["idc"]] = row
        now = round(time.time(), 3)
        rows = []
        for idc, state, kw in updates:
            row = {**latest.get(idc, {}), "idc": idc, "state": state,
                   "ts": now, **kw}
            rows.append(row)
            latest[idc] = row
        ledger.emit_batch(
            [_lake_event(r) for r in rows], run_dir=run_dir, sink=sink
        )
        payload = b"".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8") + b"\n"
            for r in rows
        )
        _append_line(p, payload)
        for r in rows:
            self._rows[r["idc"]] = r
        return rows

    def mark_used(self, idc: str) -> dict:
        """Cheap last_used_at touch (LRU feed, §3.10.3): append-only row,
        no ledger event — usage churn is bookkeeping, not history."""
        row = {**_latest_row(idc), "idc": idc,
               "last_used_at": round(time.time(), 3)}
        _append_row(paths.lake_catalog_path(), row)
        self._rows[idc] = row
        return row

    def pin(self, idc: str, source: str = "arxiv", sink=None,
            run_dir=None) -> dict:
        """Pin a cell against eviction: marker file first (the truth), then
        a catalog row with ``pinned=True`` — state left as-is (pin is a
        field, never a state; ``state=='pinned'`` un-pins on the next set).

        Both writes fail toward pinned: a crash between them leaves either
        the marker (still honored by every delete verb's file check) or
        marker + row. Pinning an absent cell anchors an empty dir holding
        just the marker — state ``skeleton``, ``manifested=False`` (nothing
        manifested it; the pin itself exempts it from orphan eviction).
        """
        # state/source come from the on-disk latest row, not self._rows —
        # a stale catalog instance must never clobber the true state with
        # the 'absent' fallback (same freshness rule set() applies to its
        # merge base). The row's source wins over the arg: it names the
        # dir where the bytes actually live, and rewriting it would orphan
        # the real cell while marking an empty one.
        latest = _latest_row(idc)
        state = latest.get("state", "absent")
        source = str(latest.get("source") or source)
        d = cell_dir(idc, source)
        d.mkdir(parents=True, exist_ok=True)
        marker = d / PIN_MARKER
        if not marker.exists():
            fsutil.atomic_write(marker, b"pinned\n")
        if state == "absent":
            return self.set(idc, "skeleton", source=source, pinned=True,
                            manifested=False, sink=sink, run_dir=run_dir)
        return self.set(idc, state, source=source, pinned=True,
                        sink=sink, run_dir=run_dir)

    def unpin(self, idc: str, source: str = "arxiv", sink=None,
              run_dir=None) -> dict | None:
        """Lift the pin: remove the marker first, then project
        ``pinned=False`` — a crash between the two leaves the row pinned
        (fail-safe: still protected until the next set reconciles).
        Unpinning an absent, unmarked cell is a no-op returning None."""
        latest = _latest_row(idc)
        state = latest.get("state", "absent")
        source = str(latest.get("source") or source)
        d = cell_dir(idc, source)
        with suppress(FileNotFoundError):
            (d / PIN_MARKER).unlink()
        if state == "absent":
            return None
        return self.set(idc, state, source=source, pinned=False,
                        sink=sink, run_dir=run_dir)


# --- skeleton ---------------------------------------------------------------------------


def _lake_event(row: dict) -> dict:
    """Catalog row -> T_LAKE_CELL event (the catalog's ledger projection).

    Forwards the volatile fields — pinned/manifested/orphan/regen_cost/
    last_used_at — so a catalog rebuild replaying lake_cell events loses
    nothing the row carried (they are whitelisted OPTIONAL_KEYS; absent
    keys stay absent rather than being defaulted into the event).
    """
    ev_kw = {"source": row.get("source", "arxiv")}
    for k in ("bytes", "pinned", "manifested", "orphan", "regen_cost",
              "last_used_at"):
        if row.get(k) is not None:
            ev_kw[k] = row[k]
    return make_event(
        events.T_LAKE_CELL, id=row["idc"], idc=row["idc"],
        state=row["state"], **ev_kw
    )


def _latest_row(idc: str) -> dict:
    """Last catalog.jsonl row for ``idc``, read fresh from disk — the merge
    base for ``set``/``mark_used``. Rows are never deleted (append-only), so
    the last match wins. An absent catalog means no rows at all."""
    latest: dict = {}
    p = paths.lake_catalog_path()
    if not p.exists():
        return latest
    for _ln, row, _raw in iter_jsonl(p):
        if isinstance(row, dict) and row.get("idc") == idc:
            latest = row
    return latest


def register_skeleton(idc: str, source: str = "arxiv",
                      meta: dict | None = None) -> Path:
    """Register a manifested cell with no bytes: create the (empty) cell dir
    and a 'skeleton' catalog row. ``meta`` merges extra catalog fields —
    it is NOT written as meta.json, so the skeleton can never satisfy the
    is_complete read predicate."""
    d = cell_dir(idc, source)
    d.mkdir(parents=True, exist_ok=True)
    cat = LakeCatalog.load()
    cat.set(idc, "skeleton", source=source, manifested=True, **(meta or {}))
    return d


# --- pin verbs --------------------------------------------------------------------


def pin(idc: str, source: str = "arxiv", sink=None, run_dir=None) -> dict:
    """Module-level ``LakeCatalog().pin`` — see the method for semantics."""
    return LakeCatalog.load().pin(idc, source=source, sink=sink,
                                  run_dir=run_dir)


def unpin(idc: str, source: str = "arxiv", sink=None,
          run_dir=None) -> dict | None:
    """Module-level ``LakeCatalog().unpin`` — see the method for semantics."""
    return LakeCatalog.load().unpin(idc, source=source, sink=sink,
                                    run_dir=run_dir)


# --- hydration ----------------------------------------------------------------------------


def _populate_from_raw(raw_dir: Path, dst: Path) -> None:
    """Rebuild an extracted projection from the cell's canonical raw layer.

    - raw is a multi-entry tree → hardlink_farm the whole tree (the sw /
      repacked-text case — zero-copy read-only projection).
    - raw holds exactly one archive file → tarfile-extract (filter='data',
      stdlib safe extraction).
    - raw holds one non-tar ``*.gz`` → gzip single-file decompress
      (arXiv old-style members are gzipped single payloads).
    - raw holds one plain file → hardlink it across (EXDEV → copyfile via
      the farm fallback path is unnecessary for a single leaf; os.link is
      attempted first).
    """
    entries = sorted(raw_dir.iterdir())
    dst.mkdir(parents=True, exist_ok=True)
    if len(entries) == 1 and entries[0].is_file():
        f = entries[0]
        if tarfile.is_tarfile(f):
            with tarfile.open(f) as tf:
                tf.extractall(dst, filter="data")
            return
        if f.suffix == ".gz":
            with gzip.open(f, "rb") as fi:
                data = fi.read()
            out = dst / f.stem
            out.write_bytes(data)
            return
        try:
            os.link(f, dst / f.name)
        except OSError:
            shutil.copyfile(f, dst / f.name)
        return
    fsutil.hardlink_farm(raw_dir, dst)


def _publish_stage(stage: Path, dest: Path) -> bool:
    """Whole-dir rename of a built stage into ``dest``.

    Returns False when dest is already a COMPLETE cell — first wins, the
    existing tree is kept and our stage is discarded (§3.10.8 "已占 dest
    拒 rename 先者胜"). An occupied-but-incomplete dest (torn/skeleton) is
    ours to finish: it is removed and our stage lands.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        dest.unlink()  # a link is never a cell — clear it before publish
    elif dest.exists():
        meta = _read_meta(dest)
        n_files = meta.get("n_files")
        if (
            isinstance(n_files, int)
            and not isinstance(n_files, bool)
            and n_files > 0
            and n_files == _payload_count(dest)
        ):
            return False
        # The PINNED marker rides the torn tree into rmtree — carry it
        # across the rename so a re-hydrate can never silently un-pin.
        keep_pin = cell_pinned(dest)
        shutil.rmtree(dest)
    else:
        keep_pin = False
    os.rename(stage, dest)
    if keep_pin:
        (dest / PIN_MARKER).write_bytes(b"pinned\n")
    fsutil.fsync_dir(dest.parent)
    return True


def hydrate(idc: str, fetch_fn: Callable | None = None,
            source: str = "arxiv", run_seq: int = 0) -> Path | None:
    """Materialize one cell; returns the cell dir, or None when the cell is
    lazy-unfetchable (no fetch_fn and no local raw to re-extract).

    Protocol (§3.10.3/§3.10.8):

    1. Fast path: ``is_complete`` outside the lock → return.
    2. ``.locks/{safe_id}.lock`` LOCK_EX → re-check inside the lock
       (double-check — a concurrent hydrator's finished cell is reused,
       never re-fetched: two same-cell hydrations degrade to one-fetch
       one-wait).
    3. Build whole-cell in ``lake/tmp/rebuild/{run_seq}/{safe}.stage``:
       ``fetch_fn(idc, stage)`` when provided — it must populate
       ``{stage}/extracted/`` (payload) and may populate ``{stage}/raw/``
       and return a dict of extra meta fields — else, when the existing
       cell still holds ``raw/``, re-extract locally at zero network cost
       (the raw_only tier's way back to hydrated). A new fetch first
       passes the DiskPressureError free-space gate; the local re-extract
       is exempt.
    4. meta.json via atomic_write, then whole-dir rename into place.
    5. Catalog row + lake_cell event 'hydrated'.
    """
    d = cell_dir(idc, source)
    if is_complete(idc, source):
        return d
    sid = safe_id(idc)
    with lake_lock(sid):
        # Double-check inside the lock — whoever held it before us may have
        # finished the hydration while we queued.
        if is_complete(idc, source):
            return d
        cat = LakeCatalog.load()
        if cat.state(idc) == "empty":
            # a recorded zero-payload answer — a legitimately empty fetch is
            # durable state, not a reason to fetch-storm the network again
            return d
        old_meta = _read_meta(d)
        raw_dir = d / "raw"

        if fetch_fn is None and raw_dir.is_dir():
            # raw_only → hydrated, in-place: extracted.stage inside the cell
            # then rename (no payload-risking window on the canonical layer).
            cat.set(idc, "hydrating", source=source)
            stage_e = d / "extracted.stage"
            if stage_e.exists():
                shutil.rmtree(stage_e)
            stage_e.mkdir(parents=True)
            _populate_from_raw(raw_dir, stage_e)
            vault.cas_link_tree(stage_e)
            ex = d / "extracted"
            if ex.is_symlink():
                ex.unlink()  # never a projection dir — clear it
            elif ex.exists():
                shutil.rmtree(ex)  # torn half-tree — replaced atomically
            os.rename(stage_e, ex)
            n = _payload_count(d)
            meta = {**old_meta, "idc": idc, "source": source,
                    "n_files": n, "hydrated_at": round(time.time(), 3),
                    "run_seq": run_seq, "rebuilt_from": "raw"}
            fsutil.atomic_write(
                d / "meta.json",
                json.dumps(meta, ensure_ascii=False, sort_keys=True,
                           indent=2).encode("utf-8"),
            )
            cat.set(idc, "empty" if n == 0 else "hydrated", source=source,
                    n_files=n, bytes=fsutil.dir_size(d), manifested=True,
                    last_used_at=round(time.time(), 3))
            return d

        if fetch_fn is None:
            return None  # lazy-unfetchable: nothing local, no fetcher

        _check_fetch_headroom()
        cat.set(idc, "hydrating", source=source)
        stage = (paths.lake_tmp_dir() / "rebuild" / str(run_seq)
                 / f"{sid}.stage")
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        try:
            ret = fetch_fn(idc, stage)
            meta_extra = dict(ret) if isinstance(ret, dict) else {}
            ex_dir = stage / "extracted"
            if ex_dir.is_dir():
                vault.cas_link_tree(ex_dir)
            n = _payload_count(stage)
            meta = {**old_meta, "idc": idc, "source": source,
                    "n_files": n, "hydrated_at": round(time.time(), 3),
                    "run_seq": run_seq, **meta_extra}
            fsutil.atomic_write(
                stage / "meta.json",
                json.dumps(meta, ensure_ascii=False, sort_keys=True,
                           indent=2).encode("utf-8"),
            )
            if not _publish_stage(stage, d):
                shutil.rmtree(stage, ignore_errors=True)
                return d  # first wins — existing complete cell kept
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        cat.set(idc, "empty" if n == 0 else "hydrated", source=source,
                n_files=n, bytes=fsutil.dir_size(d), manifested=True,
                last_used_at=round(time.time(), 3))
        return d


# --- capacity gate ---------------------------------------------------------------------------


def admit(n_bytes: int, cap_gb: float | None = None,
          floor_gb: float | None = None) -> bool:
    """Admission control for lake writes (§3.10.1, R9).

    Two gates, both must pass:

    - cap: lake zone apparent bytes + ``n_bytes`` ≤
      ``TEXLATE_LAKE_CAP_GB`` GiB (default 100 — a watermark, not a target;
      the lake stays lazy).
    - fs floor: filesystem free space minus ``n_bytes`` must leave ≥
      ``TEXLATE_LAKE_FLOOR_GB`` GiB (default 27 = the §3.10.1
      ``fs_avail−25GB−2GB`` reserve: 25G vault + 2G ledger).
    """
    if cap_gb is None:
        cap_gb = float(os.environ.get(_ENV_LAKE_CAP_GB, "100"))
    if floor_gb is None:
        floor_gb = float(os.environ.get(_ENV_LAKE_FLOOR_GB, "27"))
    lake = paths.lake_dir()
    used = fsutil.dir_size(lake) if lake.exists() else 0
    if used + n_bytes > cap_gb * _GIB:
        return False
    try:
        free = shutil.disk_usage(lake).free
    except OSError:
        lake.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(lake).free
    return free - n_bytes >= floor_gb * _GIB


class DiskPressureError(Exception):
    """Retriable free-space gate: raised by ``hydrate`` before starting a
    NEW network fetch when the lake filesystem has less than
    ``TEXLATE_BENCH_MIN_FREE_GB`` GiB free (default 60). A plain
    exception surfaces through stage.fn as cell status ``error`` —
    STATUS_RETRIABLE, never ``fault`` — so the run retries once headroom
    returns, and the lookahead prefetcher logs it as a warn note.

    Two deliberate exemptions:

    - the local raw_only→hydrated re-extract is never gated: no fetch_fn,
      no network, and its bytes are mostly hardlink-shared with the raw
      layer it re-projects;
    - a filesystem whose TOTAL capacity is below the floor can never
      satisfy the watermark — the gate would be a permanent deadlock,
      not backpressure — so scratch roots (tmpfs test dirs, small CI
      volumes) skip it by construction. Per-write absolute protection on
      those stays with ``admit``'s fs-floor leg."""


def _check_fetch_headroom() -> None:
    """The DiskPressureError gate — see the class docstring."""
    lake = paths.lake_dir()
    try:
        usage = shutil.disk_usage(lake)
    except OSError:
        lake.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(lake)
    floor = float(os.environ.get(_ENV_MIN_FREE_GB, "60")) * _GIB
    if usage.total < floor:
        return
    if usage.free < floor:
        msg = (
            f"lake disk pressure: {usage.free / _GIB:.1f} GiB free < "
            f"{floor / _GIB:.1f} GiB floor ({_ENV_MIN_FREE_GB}) — "
            "refusing new fetch"
        )
        raise DiskPressureError(msg)


# --- eviction ----------------------------------------------------------------------------------


def _pinned(row: dict) -> bool:
    """Pin read predicate, three legs (any one suffices):

    - ``pinned`` field — the projected truth (survives mark_used/state
      transitions through the row merge);
    - ``state=='pinned'`` — read-compat for存量 rows written before pin
      became a field;
    - the ``PINNED`` marker file in the cell dir — the on-disk truth that
      outlives a catalog rebuild that lost the field.
    """
    if bool(row.get("pinned")) or row.get("state") == "pinned":
        return True
    idc = row.get("idc")
    if not isinstance(idc, str) or not idc:
        return False
    return cell_pinned(cell_dir(idc, row.get("source") or "arxiv"))


def _freeable_size(root: Path) -> int:
    """Bytes an rmtree of ``root`` actually returns to the fs: only inodes
    whose EVERY alias lives under root count. An inode with aliases
    elsewhere (CAS objects, sibling cells sharing hardlinks) survives the
    delete — counting it would over-report freed space and drive eviction
    past its target while the real footprint stays."""
    counts: dict[tuple, int] = {}
    sizes: dict[tuple, int] = {}
    links: dict[tuple, int] = {}
    for p, kind in fsutil._iter_tree(Path(root)):
        if kind != "file":
            continue
        try:
            st = p.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        key = (st.st_dev, st.st_ino)
        counts[key] = counts.get(key, 0) + 1
        sizes[key] = st.st_size
        links[key] = st.st_nlink
    return sum(sizes[k] for k, n in counts.items() if n == links[k])


def evict(target_free_bytes: int, catalog: LakeCatalog | None = None) -> list:
    """LRU eviction toward ``target_free_bytes`` freed; returns removed paths.

    Tier order (§3.10.3 — always extracted projection before raw):

    1. orphans (``manifested:false`` rows) — whole cell dir, first.
    2. extracted/ projection of every non-pinned cell — LRU oldest first;
       the cell drops to ``raw_only`` (or ``evicted`` when it has no raw).
    3. raw/ of every non-pinned cell — except ``regen_cost='network'``
       tagged rows (sw figures_stripped / stub / pdf_only: their raw is a
       repacked tree or a network-only regen, never a free local one).

    Pinned rows and the durable zone are never touched. Each deletion runs
    under the cell's own lake_lock (a racing hydrate can never publish into
    a half-deleted tree), counts only inodes the delete truly frees, and
    updates the catalog (thereby emitting lake_cell events) so the state
    book always reflects the surviving tier.
    """
    cat = catalog or LakeCatalog.load()
    rows = cat.rows()

    def lru(r: dict) -> float:
        return r.get("last_used_at") or 0.0

    def cdir_of(r: dict) -> Path:
        return cell_dir(r["idc"], r.get("source", "arxiv"))

    freed = 0
    removed: list[Path] = []

    def done() -> bool:
        return freed >= target_free_bytes

    # Tier 0 — orphans first (manifested:false), LRU order.
    orphans = sorted(
        (r for r in rows.values() if not r.get("manifested", True)), key=lru
    )
    for r in orphans:
        if done():
            break
        if _pinned(r):
            continue
        d = cdir_of(r)
        with lake_lock(safe_id(r["idc"])):
            if not d.exists():
                continue
            freed += _freeable_size(d)
            shutil.rmtree(d)
            removed.append(d)
            cat.set(r["idc"], "evicted", source=r.get("source", "arxiv"))

    # Tier 1 — extracted projection (LRU), cells drop to raw_only.
    tier1 = sorted(
        (r for r in rows.values()
         if r.get("manifested", True) and not _pinned(r)), key=lru,
    )
    for r in tier1:
        if done():
            break
        ex = cdir_of(r) / "extracted"
        with lake_lock(safe_id(r["idc"])):
            if not ex.is_dir():
                continue
            freed += _freeable_size(ex)
            shutil.rmtree(ex)
            removed.append(ex)
            state = "raw_only" if (cdir_of(r) / "raw").exists() else "evicted"
            cat.set(r["idc"], state, source=r.get("source", "arxiv"))

    # Tier 2 — raw payload (LRU); regen_cost=network rows keep their raw.
    tier2 = sorted(
        (r for r in rows.values()
         if r.get("manifested", True) and not _pinned(r)
         and r.get("regen_cost") != "network"), key=lru,
    )
    for r in tier2:
        if done():
            break
        raw = cdir_of(r) / "raw"
        with lake_lock(safe_id(r["idc"])):
            if not raw.exists():
                continue
            freed += _freeable_size(raw)
            shutil.rmtree(raw)
            removed.append(raw)
            state = ("hydrated" if (cdir_of(r) / "extracted").is_dir()
                     else "evicted")
            cat.set(r["idc"], state, source=r.get("source", "arxiv"))

    return removed


def evict_cell(
    idc: str, *, keep_raw: bool = False, source: str = "arxiv", sink=None, run_dir=None
) -> dict:
    """Per-cell eviction — the ``bench lake evict-done`` primitive.

    Deletes the cell's re-derivable surfaces: the ``extracted/``
    projection (plus a leftover ``extracted.stage`` from a torn in-place
    rebuild), and ``raw/`` unless ``keep_raw``. The catalog drops to
    ``raw_only`` (canonical bytes kept — local re-extract is free) or
    ``evicted``. ``meta.json`` and the bookkeeping/pin files always stay:
    an evicted cell remains a shell recording what was once there.
    Surfaces not on the known-rebuildable list are never touched — an
    unexpected file survives rather than betting it regenerates.

    The state flip goes through ``LakeCatalog.set`` — ledger event first,
    catalog row second — so a crash mid-evict replays to the same
    conclusion. All deletion runs under the cell's lake_lock (a racing
    hydrate can never publish into a half-deleted tree). Idempotent: a
    cell with nothing left to delete whose state already matches the
    outcome — or an absent cell with no dir — returns
    ``{"result": "skipped"}`` without writing a row; a pinned cell is
    likewise skipped (the PINNED marker is the truth, consulted via
    ``_pinned``'s three legs).

    Returns ``{idc, result, removed, freed}`` — ``result`` is
    ``"evicted"``/``"raw_only"``/``"skipped"`` (skipped carries a
    ``reason``).
    """
    cat = LakeCatalog.load()
    sid = safe_id(idc)
    with lake_lock(sid):
        latest = _latest_row(idc)
        state = latest.get("state", "absent")
        source = str(latest.get("source") or source)
        d = cell_dir(idc, source)
        # _pinned's marker leg needs a row idc — an orphan dir (no row)
        # carrying a PINNED file is covered by the direct cell check
        if _pinned(latest) or cell_pinned(d):
            return {
                "idc": idc,
                "result": "skipped",
                "reason": "pinned",
                "removed": [],
                "freed": 0,
            }
        targets = [d / "extracted", d / "extracted.stage"]
        if not keep_raw:
            targets.append(d / "raw")
        present = [t for t in targets if t.is_symlink() or t.exists()]
        new_state = "raw_only" if keep_raw and (d / "raw").exists() else "evicted"
        if not present and (
            state == new_state or (state == "absent" and not d.exists())
        ):
            return {
                "idc": idc,
                "result": "skipped",
                "reason": state,
                "removed": [],
                "freed": 0,
            }
        freed = 0
        removed: list[Path] = []
        for t in present:
            freed += _freeable_size(t)
            if t.is_symlink() or t.is_file():
                t.unlink()
            else:
                shutil.rmtree(t)
            removed.append(t)
        cat.set(
            idc,
            new_state,
            source=source,
            n_files=_payload_count(d),
            bytes=fsutil.dir_size(d),
            sink=sink,
            run_dir=run_dir,
        )
        return {"idc": idc, "result": new_state, "removed": removed, "freed": freed}


# --- terminal-cell shell ----------------------------------------------------------------------


def shrink_shell(work_cell_dir) -> None:
    """Reduce a terminal cell tree to its shell (§3.10.1): keep only
    ``{receipt.json, parse.json, xlat-*.jsonl, .xlat-arm.json, .lock}``
    plus ``xlat-state.*``/``state.*`` dirs (the paid chunk checkpoint —
    prune-exempt until vaulted, R17; the cell-side spelling is
    ``state.{arm}[@{variant}]``). Everything else — zh/splice/src@/
    build.* trees — is deleted. The cell dir itself stays.

    Called by prune/sweep AFTER terminal status; NOT a delete verb for the
    cell root (that is remove_cell_tree's job).

    A ``PINNED`` marker exempts the whole tree: pin protects bytes, not
    just the marker, so a pinned cell is left whole (the marker also rides
    the keep-list, belt-and-suspenders, if the early return is ever lost).
    """
    d = Path(work_cell_dir)
    if not d.is_dir():
        return
    if cell_pinned(d):
        return
    for entry in d.iterdir():
        name = entry.name
        if name in _SHELL_KEEP_EXACT:
            continue
        if any(entry.match(g) for g in _SHELL_KEEP_GLOB):
            continue
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    with suppress(OSError):
        fsutil.fsync_dir(d)
