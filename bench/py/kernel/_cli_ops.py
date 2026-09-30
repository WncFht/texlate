"""kernel._cli_ops — derive/sweep/prune/backup 运维动词叶 (kernel.cli 拆分叶).

- ``_cmd_derive``     — 重放 run 的 report/projection, 不重跑格 (§2.1)
- ``_cmd_sweep``      — 收割机 (§2.4 reaper)
- ``_cmd_prune``      — run dir 收敛到 keep-list; work/ 格树过
                        runs.remove_cell_tree 单删闸 (paid 形无 vault
                        副本担保拒删), checkpoint-only 格可缩壳
- ``_cmd_backup``     — 最小备份单元 tar (§3.10.1: ledger + vault
                        meta/manifest + lake durable + run keep-tier;
                        vault payload 字节与工作树刻意不入)

剪枝机件: ``_PRUNE_KEEP``/``_PRUNE_ALWAYS``/``_PAID_TREE_PREFIXES``/
``_CHECKPOINT_DIRS``/``_cell_has_paid_bytes``/``_cell_shrinkable``。
门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import shutil
import tarfile
import time
from typing import TYPE_CHECKING

from kernel import events, idnorm, lake, locks, paths, report, runs, vault
from kernel._cli_common import (
    EXIT_FAIL,
    EXIT_OK,
    EXIT_REFUSED,
    _err,
    _open_index,
    _pre_write,
    _print_json,
    _rundir_of,
    _try_sweep,
)

if TYPE_CHECKING:
    from pathlib import Path


def _cmd_derive(args) -> int:
    """Re-run the report/projection for a run — no cell re-execution (§2.1)."""
    _pre_write()
    rd = _rundir_of(args.run)
    if rd is None:
        return EXIT_REFUSED
    rep = runs.accounting_check(rd)
    print(
        f"accounting: plan={rep['plan']} queued={rep['queued']}"
        f" terminal={rep['terminal']} ok={rep['ok']}"
    )
    for k in ("missing_terminal", "extra_queued", "dup_terminal", "extra_terminal"):
        if rep[k]:
            print(f"  {k}: {rep[k]}")
    out = args.out or (rd.derived() / "projected")
    idx = _open_index()
    try:
        res = report.build_run_report(idx, rd.path, out, accounting=rep)
    finally:
        idx.close()
    print(
        f"derived: out={out} rows={res.get('rows')} files={len(res.get('files', []))}"
    )
    return EXIT_OK if rep["ok"] else EXIT_FAIL


def _cmd_sweep(args) -> int:
    rep, err = _try_sweep(light=args.light)
    if rep is None:
        _err(f"sweep: unavailable or failed ({err})")
        return EXIT_REFUSED
    _print_json(rep)
    return EXIT_OK


_PRUNE_KEEP = {
    "report": ("report.md",),
    "events": ("events.jsonl",),
    "spec": ("spec.json",),
    "env": ("spec_env.json",),
    "plan": ("plan.json",),
    "cases": ("cases.jsonl",),
    "invocations": ("invocations.jsonl",),
    "work": ("work",),
    "derived": ("derived",),
}
# Never deleted regardless of keep-list: the immortal lock file (R21) and the
# heartbeat (structural — a stale mtime IS the zombie evidence).
_PRUNE_ALWAYS = {".lock", "heartbeat"}

#: work/ cell dir prefixes that may hold paid bytes — vault byte kinds plus
#: the "xlat-state" checkpoint spelling (see _CHECKPOINT_DIRS).
_PAID_TREE_PREFIXES = (*sorted(events.VAULT_BYTE_KINDS), "xlat-state")


def _cell_has_paid_bytes(cell: Path) -> bool:
    """Conservative paid-shape probe: zh/splice/state/xlat-state trees that
    carry any file mean paid bytes may live here (fail-closed)."""
    try:
        for e in cell.iterdir():
            if not e.is_dir():
                continue
            base = e.name.split(".", 1)[0].split("@", 1)[0]
            if base not in _PAID_TREE_PREFIXES:
                continue
            if any(p.is_file() for p in e.rglob("*")):
                return True
    except OSError:
        return True  # unreadable tree — treat as paid, refuse to guess
    return False


# ``state.{arm}[@{variant}]`` is the real cell-side spelling of the
# xlat-state paid checkpoint (vault kind name vs work-tree dirname) — both
# spellings ride the shrink keep-glob and this gate.
_CHECKPOINT_DIRS = ("xlat-state", "state")


def _cell_shrinkable(cell: Path) -> bool:
    """Checkpoint-only paid shape: every paid-prefixed dir carrying files is
    a chunk checkpoint (``xlat-state.*`` / ``state.*``) — no zh/splice
    product trees. Shrinking such a cell keeps the paid checkpoint while
    freeing the rebuildable bulk; a cell with un-vaulted zh/splice product
    must stay whole for a later harvest."""
    try:
        for e in cell.iterdir():
            if not e.is_dir():
                continue
            base = e.name.split(".", 1)[0].split("@", 1)[0]
            if (
                base in _PAID_TREE_PREFIXES
                and base not in _CHECKPOINT_DIRS
                and any(p.is_file() for p in e.rglob("*"))
            ):
                return False
    except OSError:
        return False
    return True


def _cmd_prune(args) -> int:
    """Reduce a run dir to its keep-list (§2.1 prune).

    work/ cells go through runs.remove_cell_tree — the single delete verb,
    which refuses a paid-shaped tree that no vault copy vouches for.
    """
    _pre_write()
    rd = _rundir_of(args.run)
    if rd is None:
        return EXIT_REFUSED
    keep = {t.strip() for t in str(args.keep).split(",") if t.strip()}
    unknown = keep - set(_PRUNE_KEEP)
    if unknown:
        _err(
            f"prune: unknown keep tokens {sorted(unknown)}"
            f" (allowed: {sorted(_PRUNE_KEEP)})"
        )
        return EXIT_REFUSED
    keep_names = set(_PRUNE_ALWAYS)
    for t in keep:
        keep_names.update(_PRUNE_KEEP[t])

    blocked = 0
    try:
        lock_ctx = rd.lock(blocking=False)
        lock_ctx.__enter__()
    except locks.WouldBlock:
        _err(
            f"prune: {rd.run} is live (run.lock held) — refusing to "
            "delete a running archive (R21)"
        )
        return EXIT_REFUSED
    try:
        for entry in sorted(rd.path.iterdir()):
            if entry.name in keep_names:
                print(f"  keep    {entry.name}")
                continue
            if entry.name == "work":
                for cell in sorted(entry.iterdir()):
                    if not cell.is_dir() or cell.name.startswith((".", "_")):
                        continue
                    sid = cell.name
                    idc = idnorm.idc_from_safe(sid)

                    def vault_check(sid=sid, idc=idc, cell=cell):
                        if not _cell_has_paid_bytes(cell):
                            return True
                        try:
                            return any(r.get("bytes_ok") for r in vault.query(idc))
                        except Exception:
                            return False

                    try:
                        runs.remove_cell_tree(rd, sid, vault_check=vault_check)
                        print(f"  pruned  work/{sid}")
                    except runs.BlockedDelete as exc:
                        blocked += 1
                        shrunk = False
                        if _cell_shrinkable(cell):
                            try:
                                with locks.flock(
                                    rd.cell_lock_path(sid),
                                    exclusive=True,
                                    blocking=False,
                                ):
                                    lake.shrink_shell(cell)
                                    shrunk = True
                            except locks.WouldBlock:
                                pass  # live cell — the lock IS the refusal
                        _err(
                            f"  blocked work/{sid}: {exc}"
                            + (" — shrunk to shell" if shrunk else "")
                        )
                if not blocked:
                    # cells gone or none — drop the remaining tree (_texmf
                    # shared cache et al.; all rebuildable)
                    shutil.rmtree(entry)
                continue
            if entry.name == "events.jsonl":
                _err(
                    "  warning: removing the run events shard — the ledger "
                    "keeps the sole remaining copy (dual-write redundancy "
                    "ends)"
                )
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            print(f"  pruned  {entry.name}")
    finally:
        lock_ctx.__exit__(None, None, None)
    if blocked:
        _err(f"prune: {blocked} cell tree(s) blocked (unharvested paid bytes)")
        return EXIT_FAIL
    return EXIT_OK


def _cmd_backup(_args) -> int:
    """Minimal backup unit (§3.10.1): ledger + vault meta/manifest + lake
    durable + run keep-tier files, as a plain tar under backup/.

    Scope note: vault PAYLOAD bytes (zh/splice/state trees), work trees,
    derived/, and the rebuildable index.sqlite are deliberately excluded —
    the paid bytes' second copy is restic/rsync territory, not this tar.
    """
    _pre_write()
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out = paths.backup_dir() / f"bench-backup-{ts}.tar"
    root = paths.root()
    members: list[Path] = []

    def add_tree(base: Path, *, skip=()) -> None:
        if not base.is_dir():
            return
        for p in sorted(base.rglob("*")):
            if any(p.match(s) for s in skip):
                continue
            members.append(p)

    # ledger — everything except the disposable index projection.
    add_tree(
        paths.ledger_dir(),
        skip=("index.sqlite", "index.sqlite-*", "*.lock"),
    )
    # vault meta + manifest — the credential layer, not the payload.
    add_tree(paths.vault_meta_dir())
    if paths.vault_manifest_path().is_file():
        members.append(paths.vault_manifest_path())
    # lake durable + the catalog projection (rebuildable, small).
    add_tree(paths.lake_durable_dir())
    if paths.lake_catalog_path().is_file():
        members.append(paths.lake_catalog_path())
    # run keep-tier files only — never work/ or derived/.
    keep_files = {
        "spec.json",
        "spec_env.json",
        "plan.json",
        "events.jsonl",
        "cases.jsonl",
        "invocations.jsonl",
        "report.md",
    }
    rbase = paths.runs_dir()
    if rbase.is_dir():
        members.extend(
            p for p in sorted(rbase.rglob("*")) if p.is_file() and p.name in keep_files
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(out, "w") as tf:
        for p in members:
            try:
                tf.add(p, arcname=p.relative_to(root), recursive=False)
                n += 1
            except (OSError, ValueError) as exc:
                _err(f"backup: skipped {p} ({exc})")
    print(
        f"backup: {out} ({out.stat().st_size} bytes, {n} member(s))\n"
        "scope: ledger + vault meta/manifest + lake durable/catalog +"
        " run keep-tier; vault payload bytes and work trees excluded"
    )
    return EXIT_OK
