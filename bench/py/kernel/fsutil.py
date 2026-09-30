"""Filesystem primitives for the trizone data plane (design §3.10.2/§3.10.4).

Two projection protocols, kept structurally distinct:

- ``hardlink_farm`` — READ-ONLY projection. Recreates a source tree via
  ``os.link`` so every file shares the source inode (0444 objects stay 0444:
  the inode itself is the write-fuse). Cross-device (EXDEV) falls back to
  copyfile + ``chmod a-w`` so the projection is read-only even when it cannot
  share the inode. NEVER chmods a dst file — it may be a shared CAS inode;
  stale dst entries are unlinked and re-materialized instead.
- ``copy_mutating`` — MUTATING projection. ``shutil.copyfile`` every file
  (mode stripped by fresh creation) then ``chmod u+w``, so a 0444 source is
  delivered writable. Also never chmods dst before unlinking — dst may be a
  hardlink into the object pool from a prior read-only projection.

Crash protocol: ``atomic_write`` = tmp-in-same-dir + fsync + ``os.replace`` +
dir fsync. ``verify_mtree``/``build_mtree`` implement the stat-level
(size,mtime) drift oracle the lake uses before projecting a cell, with an
optional sha256 re-sample on top.

``dir_size`` reports *apparent* size (sum of ``st_size`` over regular files):
hardlinked aliases are counted once per path, not once per inode — the number
answers "how many bytes would this tree occupy materialized alone", which is
what capacity accounting wants. ``st_blocks``-based dedup-aware sizing is a
deliberate non-goal here.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import random
import shutil
import stat
import tempfile
from pathlib import Path

MTREE_NAME = "mtree.txt"


class DriftError(Exception):
    """Source tree does not match its manifest (size/mtime/ship drift)."""

    def __init__(self, drifted):
        self.drifted = sorted(drifted)
        preview = ", ".join(self.drifted[:5])
        if len(self.drifted) > 5:
            preview += f", … +{len(self.drifted) - 5} more"
        super().__init__(f"mtree drift on {len(self.drifted)} path(s): {preview}")


# --- durability ---------------------------------------------------------------

#: torn-tail 愈合的倒扫块大小——lake/runs/ledger 三处 append 路径共用。
HEAL_CHUNK = 64 * 1024


def fsync_dir(path) -> None:
    """fsync a directory so a rename/create inside it is durable."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data: bytes, mode: int | None = None) -> None:
    """Durable whole-file write: tmp in same dir → fsync → os.replace → dir fsync.

    撞名警示：``src/texlate/textutil/osutil.py`` 有同名 ``atomic_write``——
    产品侧轻量口径（str|bytes/mkdir 自理/无 fsync），与本件刻意分层勿合并。

    ``mode`` (optional) is fchmod'd on the tmp fd *before* the content write,
    so the destination is born with that mode (CAS objects use mode=0o444,
    no writable window) and the single fsync covers content and mode alike.
    Parent dir must already exist.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        if mode is not None:
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# --- tree walking ---------------------------------------------------------------


def _iter_tree(root: Path):
    """Yield ``(path, kind)`` for every entry under ``root`` (dirs before their
    children), kind in {"dir", "file", "link", "other"}. "other" = fifo,
    socket, device — projections refuse them loudly rather than hang or
    silently mis-materialize. Deterministic name order."""
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as it:
            entries = sorted(it, key=lambda e: e.name)
        dirs = []
        for e in entries:
            p = Path(e.path)
            if e.is_symlink():
                yield p, "link"
            elif e.is_dir(follow_symlinks=False):
                yield p, "dir"
                dirs.append(p)
            elif e.is_file(follow_symlinks=False):
                yield p, "file"
            else:
                yield p, "other"
        stack.extend(reversed(dirs))


def _sha256_file(path: Path, _buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_buf), b""):
            h.update(chunk)
    return h.hexdigest()


# --- gates -----------------------------------------------------------------------


def has_nonwritable(tree) -> list[Path]:
    """Entries lacking owner-write under ``tree`` — files *and* directories,
    plus the tree root itself (a read-only root blocks entry creation, which
    is exactly what the vault commit's ``chmod -R a-w`` produces).

    Kernel gate for mutating trees (§3.10.2): a tree containing any 0444 file
    or 0555 dir must refuse to run — a read-only dir blocks mutation just as
    hard as a read-only file. Symlinks are skipped (their mode is meaningless).
    Returns absolute paths, sorted.
    """
    tree = Path(tree)
    out = []
    root_st = tree.stat()  # FileNotFoundError on a missing tree — loud is right
    if stat.S_ISDIR(root_st.st_mode) and not root_st.st_mode & stat.S_IWUSR:
        out.append(tree)
    for p, kind in _iter_tree(tree):
        if kind == "link":
            continue
        st = p.stat(follow_symlinks=False)
        if not st.st_mode & stat.S_IWUSR:
            out.append(p)
    return sorted(out)


def nlink(path) -> int:
    """Link count of the inode behind ``path`` (the filesystem-native refcount
    the CAS GC uses: nlink==1 = no projection references it)."""
    return os.stat(path, follow_symlinks=False).st_nlink


def dir_size(tree) -> int:
    """Apparent size: sum of st_size over regular files under ``tree``.

    NOT dedup-aware — each path contributes its full size even when it shares
    an inode. This is the materialized-alone footprint, which is what capacity
    and eviction accounting want; per-inode accounting is a separate concern.
    """
    total = 0
    for p, kind in _iter_tree(Path(tree)):
        if kind == "file":
            total += p.stat(follow_symlinks=False).st_size
    return total


# --- mtree (size,mtime[,sha256] manifest) -----------------------------------------


def build_mtree(tree, with_sha: bool = False) -> dict:
    """``{relpath: entry}`` over all regular files and symlinks under
    ``tree``. File entries are ``{"size": int, "mtime": float[, "sha256":
    str]}``; symlink entries are ``{"link": target}``. Keys sorted; relpaths
    are posix-style. ``mtree.txt`` at the tree root is included if present —
    callers writing a self-manifest strip it (see ``write_mtree``)."""
    tree = Path(tree)
    out = {}
    for p, kind in _iter_tree(tree):
        rel = p.relative_to(tree).as_posix()
        if kind == "link":
            out[rel] = {"link": os.readlink(p)}
            continue
        if kind != "file":
            continue
        st = p.stat(follow_symlinks=False)
        ent = {"size": st.st_size, "mtime": st.st_mtime}
        if with_sha:
            ent["sha256"] = _sha256_file(p)
        out[rel] = ent
    return dict(sorted(out.items()))


def write_mtree(tree, with_sha: bool = False) -> dict:
    """Build the tree's mtree and atomically write it to ``tree/mtree.txt``
    (JSON, canonical key order). The manifest excludes itself. Returns the
    mtree dict."""
    tree = Path(tree)
    mtree = build_mtree(tree, with_sha=with_sha)
    mtree.pop(MTREE_NAME, None)  # never let the manifest describe itself
    payload = json.dumps(
        mtree, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    atomic_write(tree / MTREE_NAME, payload)
    return mtree


def _load_mtree(mtree) -> dict:
    if isinstance(mtree, (str, Path)):
        return json.loads(Path(mtree).read_text(encoding="utf-8"))
    return dict(mtree)


def verify_mtree(tree, mtree, resha_sample: float = 0.0) -> list[str]:
    """Stat-level drift check of ``tree`` against ``mtree`` (dict or path to a
    JSON mtree file). Returns sorted drifted relpaths — empty means clean.

    Drift = file in manifest but missing/size/mtime mismatch, symlink entry
    whose target changed, file present in tree but absent from manifest
    (unmanifested payload — except the self-manifest ``mtree.txt`` at root,
    which is metadata, not payload), or the wrong node kind where an entry
    was expected (a planted symlink or special file where a regular file was
    manifested, or vice versa).
    ``resha_sample`` in [0,1]: files that pass stat-level are re-hashed with
    that probability and must match the entry's ``sha256`` (entries without a
    recorded sha256 are skipped — nothing to check against).
    """
    tree = Path(tree)
    expected = _load_mtree(mtree)
    actual = {}
    for p, kind in _iter_tree(tree):
        if kind in ("file", "link", "other"):
            actual[p.relative_to(tree).as_posix()] = (p, kind)

    drifted = set()
    rng = random.random
    for rel, ent in expected.items():
        got = actual.pop(rel, None)
        if got is None:
            drifted.add(rel)
            continue
        p, kind = got
        if "link" in ent:
            # manifest says symlink: kind must still be a symlink with the
            # same target — a regular file or a retargeted link is drift
            if kind != "link" or os.readlink(p) != ent["link"]:
                drifted.add(rel)
            continue
        if kind != "file":  # manifested file is now a link or special file
            drifted.add(rel)
            continue
        st = p.stat(follow_symlinks=False)
        if st.st_size != ent["size"] or st.st_mtime != ent["mtime"]:
            drifted.add(rel)
            continue
        if (
            resha_sample > 0.0
            and rng() < resha_sample
            and "sha256" in ent
            and _sha256_file(p) != ent["sha256"]
        ):
            drifted.add(rel)

    for rel in actual:  # unmanifested payload
        if rel != MTREE_NAME:
            drifted.add(rel)
    return sorted(drifted)


# --- projections --------------------------------------------------------------------


def _fresh_dst(dst: Path) -> None:
    """Remove an existing dst leaf without ever chmod'ing it — it may be a
    hardlink into the object pool, where adding a write bit would melt the
    0444 fuse for every alias (§3.10.2 explicit ban)."""
    if dst.is_symlink() or dst.exists():
        dst.unlink()


def _chmod_readonly(path: Path) -> None:
    st = path.stat(follow_symlinks=False)
    os.chmod(path, stat.S_IMODE(st.st_mode) & ~0o222)


def hardlink_farm(src, dst, mtree=None) -> int:
    """Read-only projection: recreate ``src`` tree at ``dst`` via os.link.

    - ``mtree`` (dict or JSON path, optional): stat-level pre-verify of the
      *source* tree — any drift raises DriftError before dst is touched.
    - dst files already present with matching (size, mtime) are skipped.
    - stale/mismatched dst leaves are unlinked (never chmod'd) and redone.
    - EXDEV (cross-device) falls back to copyfile + mtime restore + chmod a-w,
      so the projection stays read-only when it cannot share the inode.
    - Returns the number of files newly materialized (links + fallback copies).
    """
    src = Path(src)
    dst = Path(dst)
    if mtree is not None:
        drifted = verify_mtree(src, mtree)
        if drifted:
            raise DriftError(drifted)

    dst.mkdir(parents=True, exist_ok=True)
    made = 0
    for p, kind in _iter_tree(src):
        rel = p.relative_to(src)
        target = dst / rel
        if kind == "dir":
            target.mkdir(parents=True, exist_ok=True)
            continue
        if kind == "link":
            _fresh_dst(target)
            os.symlink(os.readlink(p), target)
            made += 1
            continue
        if kind == "other":
            msg = f"special file cannot be projected: {p}"
            raise ValueError(msg)

        s_st = p.stat(follow_symlinks=False)
        t_st = None
        if not target.is_symlink():
            try:
                t_st = target.stat()
            except FileNotFoundError:
                t_st = None
        if (
            t_st is not None
            and stat.S_ISREG(t_st.st_mode)
            and t_st.st_size == s_st.st_size
            and t_st.st_mtime == s_st.st_mtime
        ):
            continue  # already materialized
        _fresh_dst(target)
        try:
            os.link(p, target)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            shutil.copyfile(p, target)
            # restore src mtime so the (size,mtime) skip-check keeps working
            # across mechanisms; the copy is then made read-only like a link.
            os.utime(target, ns=(s_st.st_atime_ns, s_st.st_mtime_ns))
            _chmod_readonly(target)
        made += 1
    return made


def copy_mutating(src, dst) -> int:
    """Mutating projection: copyfile every file under ``src`` into ``dst``,
    delivering each dst file owner-writable (``chmod u+w`` after copy — mode is
    NOT preserved, so a 0444 source still yields a writable tree).

    Existing dst leaves are unlinked first (never chmod'd — a dst that is a
    hardlink into the object pool must not have its shared inode touched).
    Dirs are mkdir'd, symlinks recreated. Returns files materialized.
    """
    src = Path(src)
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    made = 0
    for p, kind in _iter_tree(src):
        rel = p.relative_to(src)
        target = dst / rel
        if kind == "dir":
            target.mkdir(parents=True, exist_ok=True)
            continue
        if kind == "link":
            _fresh_dst(target)
            os.symlink(os.readlink(p), target)
            made += 1
            continue
        if kind == "other":
            msg = f"special file cannot be projected: {p}"
            raise ValueError(msg)
        _fresh_dst(target)
        shutil.copyfile(p, target)
        st = target.stat()
        os.chmod(target, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)
        made += 1
    return made
