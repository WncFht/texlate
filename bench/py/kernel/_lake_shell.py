"""lake 壳层叶 —— shrink_shell 终态格瘦身 (§3.10.1 shell set)。

原 ``kernel.lake`` 顶层「terminal-cell shell」段 + ``_SHELL_KEEP_*``
常量。门面回引名单见 ``kernel.lake._LEAF_EXPORTS``; monkeypatch 锚点
归本叶。
"""

from __future__ import annotations

import shutil
from contextlib import suppress
from pathlib import Path

from kernel import fsutil
from kernel._lake_cell import PIN_MARKER, cell_pinned

# Files kept by shrink_shell on a terminal cell (§3.10.1 shell set).
# ``xlat-state.*``/``state.*`` directories are additionally preserved — the
# chunk-level paid checkpoint is prune-exempt until vaulted (§3.10.1
# revision + R17: losing it re-burns paid quota on resume). The cell-side
# dir is ``state.{arm}[@{variant}]`` (xlat-state is the vault kind name);
# both spellings ride the glob. PIN_MARKER rides the keep set so a shrink
# can never eat the pin marker (measured gap), though a pinned cell
# short-circuits shrink_shell before the keep-list is even consulted.
_SHELL_KEEP_EXACT = frozenset(
    {
        "receipt.json",
        "parse.json",
        ".xlat-arm.json",
        ".lock",
        PIN_MARKER,
    }
)
_SHELL_KEEP_GLOB = (
    "xlat-*.jsonl",
    "xlat-state",
    "xlat-state.*",
    "state",
    "state.*",
)


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
