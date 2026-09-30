"""lake 台账叶 —— catalog.jsonl 动态状态簿 (LakeCatalog) + 骨架登记 +
pin/unpin 模块级动词。

原 ``kernel.lake`` 顶层「small append helper」「catalog」「skeleton」
「pin verbs」四段。``LakeCatalog.__module__`` 钉回 ``kernel.lake``
保持 repr/pickle 引用路径不变。门面回引名单见
``kernel.lake._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import time
from contextlib import suppress
from typing import TYPE_CHECKING

from kernel import events, fsutil, ledger, locks, paths
from kernel._lake_cell import PIN_MARKER, cell_dir
from kernel.events import iter_jsonl, make_event

if TYPE_CHECKING:
    from pathlib import Path


def _append_line(path: Path, payload: bytes) -> None:
    """``kernel.fsutil.healed_append`` — same contract as the ledger path,
    serialized through ``lake/.locks/.catalog.lock``: different cells'
    writers append the shared catalog concurrently, and an unlocked
    heal-truncate can clip a racing writer's fresh line."""
    catalog_lock = paths.lake_locks_dir() / ".catalog.lock"
    with locks.flock(catalog_lock, exclusive=True, blocking=True):
        fsutil.healed_append(path, payload)


def _append_row(path: Path, row: dict) -> None:
    line = events.dumps(row).encode("utf-8") + b"\n"
    _append_line(path, line)


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

    def set(self, idc: str, state: str, sink=None, run_dir=None, **kw) -> dict:
        """Transition ``idc`` to ``state``: emit the ledger lake_cell event
        FIRST, then append the merged row to catalog.jsonl — the catalog is
        declared a projection of the event stream, so a crash between the
        two must leave a replayable event, never a catalog row with no
        history. The merge base is re-read from the file itself: a catalog
        instance loaded once goes stale the moment another writer appends,
        and merging onto stale state silently clobbers the interleaved
        row's fields. Returns the stored row."""
        row = {
            **_latest_row(idc),
            "idc": idc,
            "state": state,
            "ts": round(time.time(), 3),
            **kw,
        }
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
            row = {**latest.get(idc, {}), "idc": idc, "state": state, "ts": now, **kw}
            rows.append(row)
            latest[idc] = row
        ledger.emit_batch([_lake_event(r) for r in rows], run_dir=run_dir, sink=sink)
        payload = b"".join(events.dumps(r).encode("utf-8") + b"\n" for r in rows)
        _append_line(p, payload)
        for r in rows:
            self._rows[r["idc"]] = r
        return rows

    def mark_used(self, idc: str) -> dict:
        """Cheap last_used_at touch (LRU feed, §3.10.3): append-only row,
        no ledger event — usage churn is bookkeeping, not history."""
        row = {**_latest_row(idc), "idc": idc, "last_used_at": round(time.time(), 3)}
        _append_row(paths.lake_catalog_path(), row)
        self._rows[idc] = row
        return row

    def pin(self, idc: str, source: str = "arxiv", sink=None, run_dir=None) -> dict:
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
            return self.set(
                idc,
                "skeleton",
                source=source,
                pinned=True,
                manifested=False,
                sink=sink,
                run_dir=run_dir,
            )
        return self.set(
            idc, state, source=source, pinned=True, sink=sink, run_dir=run_dir
        )

    def unpin(
        self, idc: str, source: str = "arxiv", sink=None, run_dir=None
    ) -> dict | None:
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
        return self.set(
            idc, state, source=source, pinned=False, sink=sink, run_dir=run_dir
        )


LakeCatalog.__module__ = "kernel.lake"


def _lake_event(row: dict) -> dict:
    """Catalog row -> T_LAKE_CELL event (the catalog's ledger projection).

    Forwards the volatile fields — pinned/manifested/orphan/regen_cost/
    last_used_at — so a catalog rebuild replaying lake_cell events loses
    nothing the row carried (they are whitelisted OPTIONAL_KEYS; absent
    keys stay absent rather than being defaulted into the event).
    """
    ev_kw = {"source": row.get("source", "arxiv")}
    for k in ("bytes", "pinned", "manifested", "orphan", "regen_cost", "last_used_at"):
        if row.get(k) is not None:
            ev_kw[k] = row[k]
    return make_event(
        events.T_LAKE_CELL, id=row["idc"], idc=row["idc"], state=row["state"], **ev_kw
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


def register_skeleton(
    idc: str, source: str = "arxiv", meta: dict | None = None
) -> Path:
    """Register a manifested cell with no bytes: create the (empty) cell dir
    and a 'skeleton' catalog row. ``meta`` merges extra catalog fields —
    it is NOT written as meta.json, so the skeleton can never satisfy the
    is_complete read predicate."""
    d = cell_dir(idc, source)
    d.mkdir(parents=True, exist_ok=True)
    cat = LakeCatalog.load()
    cat.set(idc, "skeleton", source=source, manifested=True, **(meta or {}))
    return d


def pin(idc: str, source: str = "arxiv", sink=None, run_dir=None) -> dict:
    """Module-level ``LakeCatalog().pin`` — see the method for semantics."""
    return LakeCatalog.load().pin(idc, source=source, sink=sink, run_dir=run_dir)


def unpin(idc: str, source: str = "arxiv", sink=None, run_dir=None) -> dict | None:
    """Module-level ``LakeCatalog().unpin`` — see the method for semantics."""
    return LakeCatalog.load().unpin(idc, source=source, sink=sink, run_dir=run_dir)
