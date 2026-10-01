"""lake 格内省叶 —— cell 路径/pin 标记/meta 读谓词/载荷计数/per-cell flock。

原 ``kernel.lake`` 顶层「paths / cell introspection」「locks」两段 +
``PIN_MARKER``/``_BOOKKEEP`` 常量。门面回引名单见
``kernel.lake._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from kernel import fsutil, locks, paths
from kernel.idnorm import safe_id

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Pin truth file — lives at the cell dir root (``{cell}/PINNED`` for lake
#: cells, ``work/{safe_id}/PINNED`` for run cells). Every byte-deleting verb
#: honors it; the catalog ``pinned`` field is its ledger-replayable
#: projection, not the source of truth.
PIN_MARKER = "PINNED"

# Bookkeeping files that are never counted as cell payload. PIN_MARKER is
# bookkeeping by definition — without the exclusion a pinned cell's payload
# count inflates by one and is_complete can never vouch for it again.
_BOOKKEEP = {"meta.json", "mtree.txt", "files.txt", PIN_MARKER}


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


@contextmanager
def lake_lock(safe: str) -> Iterator[int]:
    """Hold LOCK_EX (blocking) on ``lake/.locks/{safe_id}.lock``.

    The per-cell serializer: hydrate/evict hold it exclusively, read-only
    projections may hold it shared. The lock file is immortal (R21).
    """
    lock_path = paths.lake_locks_dir() / f"{safe}.lock"
    with locks.flock(lock_path, exclusive=True, blocking=True) as fd:
        yield fd
