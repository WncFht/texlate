"""lake 淘汰叶 —— _pinned 三腿谓词/_freeable_size inode 实释放账/
evict LRU 三层淘汰/evict_cell 单格原语。

原 ``kernel.lake`` 顶层「eviction」段。门面回引名单见
``kernel.lake._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from kernel import fsutil
from kernel._lake_catalog import LakeCatalog, _latest_row
from kernel._lake_cell import (
    _payload_count,
    cell_dir,
    cell_pinned,
    lake_lock,
)
from kernel.idnorm import safe_id


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
        (r for r in rows.values() if r.get("manifested", True) and not _pinned(r)),
        key=lru,
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
        (
            r
            for r in rows.values()
            if r.get("manifested", True)
            and not _pinned(r)
            and r.get("regen_cost") != "network"
        ),
        key=lru,
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
            state = "hydrated" if (cdir_of(r) / "extracted").is_dir() else "evicted"
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
