"""kernel.vault.io — 小 IO 机件与 meta/manifest 读写 (kernel.vault 拆分叶).

sentinel 闸 (R5 mount proof)、fsync 三连、0444 fuse/解 fuse、文件迭代、
meta 容错读 + atomic 写、manifest.jsonl 锁内追加与全表容错读、meta/*.json
逐份扫描 (``_iter_metas``/``_iter_metas_for``)。无判定语义——所有
"好不好" 的断言在 ``vault.intact``, 本叶只出物理动作与读写件。
"""

from __future__ import annotations

import glob
import json
import os
import stat
from pathlib import Path

from kernel import events, fsutil, idnorm, ledger, paths
from kernel.vault.cred import _META_SUFFIX, VaultError, parse_meta_key


def _require_sentinel() -> None:
    """R5: refuse vault writes when the mount proof is absent — an empty
    mount point must never silently swallow paid bytes."""
    if not paths.vault_sentinel_path().exists():
        msg = (
            f"vault sentinel {paths.vault_sentinel_path()} missing — "
            "refusing to write into a possibly-unmounted vault dir"
        )
        raise VaultError(msg)


def _fsync_file(p: Path) -> None:
    fd = os.open(p, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_tree(root: Path) -> None:
    """fsync every file and dir under root, then root itself."""
    for p, kind in fsutil._iter_tree(root):
        if kind == "file":
            _fsync_file(p)
        elif kind == "dir":
            fsutil.fsync_dir(p)
    fsutil.fsync_dir(root)


def _fsync_ancestors(leaf_parent: Path) -> None:
    """fsync a dir and every ancestor up to and including the vault root —
    dirent durability for the whole sid/kind/quar chain a rename may have
    just created."""
    p = Path(leaf_parent)
    vault = paths.vault_dir()
    while True:
        fsutil.fsync_dir(p)
        if p in (vault, p.parent):
            break
        p = p.parent


def _chmod_readonly_tree(root: Path, include_root: bool = True) -> dict:
    """``chmod -R a-w`` — the vault fuse. Files share the work source's
    inode, so this deliberately makes the work-side copy read-only too.

    ``include_root=False`` leaves the tree root writable: rename(2) must
    rewrite the moved dir's ``..`` entry and refuses a read-only source dir,
    so the top dir is fused only AFTER it lands in place (nested dirs' ``..``
    does not change — they stay fused throughout).

    Returns ``{posix-rel: orig_mode}`` for every node whose write bits were
    actually cleared — the rollback map an aborted commit uses to restore
    the shared source inodes. Already-fused nodes are skipped, so a
    re-harvest of an earlier commit's fused source stays fused (idempotent)."""
    root = Path(root)
    changed: dict[str, int] = {}
    for p, kind in fsutil._iter_tree(root):
        if kind == "link":
            continue
        st = p.stat(follow_symlinks=False)
        mode = stat.S_IMODE(st.st_mode)
        if mode & 0o222:
            os.chmod(p, mode & ~0o222)
            changed[p.relative_to(root).as_posix()] = mode
    if include_root:
        st = root.stat()
        mode = stat.S_IMODE(st.st_mode)
        if mode & 0o222:
            os.chmod(root, mode & ~0o222)
            changed["."] = mode
    return changed


def _unfuse_dirs(root: Path) -> None:
    """Lift the a-w fuse on root and every dir under it — used only for
    aborting a commit this process created (rollback cleanup), never for
    mutating committed bytes."""
    root = Path(root)
    for p, kind in fsutil._iter_tree(root):
        if kind == "dir":
            st = p.stat(follow_symlinks=False)
            os.chmod(p, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
    if root.exists():
        st = root.stat()
        os.chmod(root, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)


def _iter_files(root: Path) -> list[tuple[Path, str]]:
    """(abspath, posix-rel) for every regular file under root, sorted."""
    out = []
    for p, kind in fsutil._iter_tree(Path(root)):
        if kind == "file":
            out.append((p, p.relative_to(root).as_posix()))
    return sorted(out, key=lambda t: t[1])


def _non_regular(root: Path) -> list[Path]:
    """Entries that are neither regular file nor dir — symlinks and special
    files are refused loudly (vault holds regular bytes only)."""
    return [p for p, kind in fsutil._iter_tree(Path(root)) if kind in ("link", "other")]


def _read_meta(path: Path) -> dict | None:
    """Tolerant meta read — None on missing/unparseable/wrong shape.
    atomic_write means readers never see a torn meta anyway; None marks
    corruption, never a partial write."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_meta(path: Path, meta: dict) -> None:
    payload = (
        json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    fsutil.atomic_write(path, payload)


def _append_manifest_locked(row: dict) -> None:
    """Append one manifest row inside vault/.lock. Reuses the ledger's
    append primitive — same torn-tail heal + single-write + fsync contract."""
    line = (events.dumps(row) + "\n").encode("utf-8")
    ledger._append_payload_locked(paths.vault_manifest_path(), line)


def _iter_metas():
    """Yield (meta_path, key_tuple|None, content|None) over meta/*.json.
    key is the filename-parsed credential (authoritative); content is the
    parsed JSON (None when unparseable)."""
    d = paths.vault_meta_dir()
    if not d.is_dir():
        return
    for mp in sorted(d.glob(f"*{_META_SUFFIX}")):
        try:
            key = parse_meta_key(mp.name)
        except ValueError:
            key = None
        yield mp, key, _read_meta(mp)


def _iter_metas_for(idc: str):
    """_iter_metas scoped to one cell: esc(safe_id(idc)) is the first
    dot-component of every meta filename, so 'esc.*.json' is an exact
    pre-filter — same row set as the full scan, without paying it."""
    d = paths.vault_meta_dir()
    if not d.is_dir():
        return
    esc = glob.escape(idnorm.escape_component(idnorm.safe_id(idc)))
    for mp in sorted(d.glob(f"{esc}.*{_META_SUFFIX}")):
        try:
            key = parse_meta_key(mp.name)
        except ValueError:
            key = None
        yield mp, key, _read_meta(mp)


def manifest_rows() -> list[dict]:
    """All parseable manifest.jsonl rows in append order (tolerant read)."""
    return [
        r
        for _ln, r, _raw in events.iter_jsonl(paths.vault_manifest_path())
        if isinstance(r, dict)
    ]
