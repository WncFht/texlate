"""Content-addressable store — lake/objects/{kind}/{aa}/{bb}/{sha256} (§3.10.2).

Objects are born 0444 (chmod on tmp before rename — no writable window): the
inode mode is the write-fuse for every read-only projection that hardlinks
them. kinds: ``blob`` = raw payloads, ``file`` = member files; any other
simple token is accepted for future kinds.

GC is the filesystem-native refcount: an object with nlink==1 (no projection
references it) whose mtime is older than the grace window is swept. The grace
window covers the store→link publish gap, so objects are never reaped between
birth and first projection.

Never *link into* the CAS: ``store_file`` copies bytes in (a hardlink would
make the caller's file share the soon-to-be-0444 inode). ``link_out`` links
out of it — dst may share the object inode, and is NEVER chmod'd; on EXDEV it
gets its own copy which is made read-only to preserve projection semantics.
"""
from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import stat as statmod
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from . import fsutil, locks, paths

_SHA_RE = re.compile(r"[0-9a-f]{64}")
_KIND_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
_OBJ_MODE = 0o444


@contextmanager
def _cas_lock(exclusive: bool):
    """Whole-pool guard closing the nlink TOCTOU: reference paths (link_out,
    dedup hits) hold SH so gc cannot unlink an inode between the caller's
    stat and its link/refresh; gc_sweep takes EX per candidate so its own
    stat→unlink is atomic against a racing reference."""
    with locks.flock(paths.lake_locks_dir() / "cas.lock",
                     exclusive=exclusive, blocking=True):
        yield


def object_path(sha: str, kind: str = "blob") -> Path:
    """``objects/{kind}/{sha[:2]}/{sha[2:4]}/{sha}`` — validates sha/kind so a
    caller-supplied sha can never escape the objects dir (no '/' or '..')."""
    if not _SHA_RE.fullmatch(sha):
        raise ValueError(f"bad sha256 {sha!r}: expected 64 lowercase hex")
    if not _KIND_RE.fullmatch(kind):
        raise ValueError(f"bad object kind {kind!r}")
    return paths.lake_objects_dir() / kind / sha[:2] / sha[2:4] / sha


def has(sha: str, kind: str = "blob") -> bool:
    return object_path(sha, kind).exists()


def _refresh(obj: Path) -> None:
    """Touch mtime on a dedup hit — re-store asserts the bytes are live again,
    so the object gets a fresh grace window and gc cannot reap it in the
    store→link gap. Owner may utime a 0444 file."""
    try:
        os.utime(obj, None)
    except OSError:
        pass  # refresh is best-effort; a vanished object is gc's business


def store_bytes(data: bytes, kind: str = "blob") -> str:
    """Idempotent store: existing object → refresh its liveness and return the
    sha. New object is written durably (atomic_write) and born 0444."""
    sha = hashlib.sha256(data).hexdigest()
    obj = object_path(sha, kind)
    with _cas_lock(exclusive=False):
        if obj.exists():
            _refresh(obj)
            return sha
    obj.parent.mkdir(parents=True, exist_ok=True)
    fsutil.atomic_write(obj, data, mode=_OBJ_MODE)
    return sha


def store_file(src, kind: str = "file") -> str:
    """Hash-then-copy, streaming both ways (constant memory — payloads can be
    large). The object inode is a fresh copy, never a link to the caller's
    file, and it is born 0444.

    Dedup hits skip the copy entirely (one read) and refresh the object's
    grace window. On a miss the tmp file is hashed *as it is written* and
    committed under that sha — if src races the copy, the stored object still
    matches its name (the CAS invariant); a mismatched pre-hash is abandoned.
    """
    src = Path(src)
    src_st = src.stat()  # FileNotFoundError on a missing src — loud is right
    if not statmod.S_ISREG(src_st.st_mode):
        raise ValueError(f"cannot store special file: {src}")  # fifo would block
    pre_sha = fsutil._sha256_file(src)
    pre_obj = object_path(pre_sha, kind)
    with _cas_lock(exclusive=False):
        if pre_obj.exists():
            _refresh(pre_obj)
            return pre_sha
    pre_obj.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(pre_obj.parent), prefix=f".{pre_sha}.",
                               suffix=".tmp")
    try:
        os.fchmod(fd, _OBJ_MODE)  # before the write so fsync covers the mode
        h = hashlib.sha256()
        with os.fdopen(fd, "wb") as fo, open(src, "rb") as fi:
            while True:
                chunk = fi.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                fo.write(chunk)
            fo.flush()
            os.fsync(fo.fileno())
        sha = h.hexdigest()  # sha of the bytes actually written
        obj = object_path(sha, kind)
        with _cas_lock(exclusive=False):
            if obj.exists():
                os.unlink(tmp)  # raced content already stored — discard
                _refresh(obj)
                return sha
        obj.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, obj)
        fsutil.fsync_dir(obj.parent)
        return sha
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def link_out(sha: str, dst, kind: str = "blob") -> Path:
    """Hardlink object ``sha`` to ``dst`` (read-only projection leaf).

    - dst already sharing the object inode → no-op.
    - other existing dst leaf → unlinked (NEVER chmod'd — it may be another
      CAS link whose inode must stay 0444) then re-linked.
    - EXDEV → copyfile + mtime restore + chmod a-w on the fresh inode.
    - missing object → FileNotFoundError from stat.

    Runs under the pool's SH lock so gc_sweep cannot unlink the object
    between the stat and the link (nlink check is a TOCTOU without it).
    """
    src = object_path(sha, kind)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with _cas_lock(exclusive=False):
        src_st = src.stat()  # FileNotFoundError when object absent — loud is right
        try:
            dst_st = dst.stat()
        except FileNotFoundError:
            dst_st = None
        if dst_st is not None and dst_st.st_dev == src_st.st_dev \
                and dst_st.st_ino == src_st.st_ino:
            return dst  # already the same inode
        if dst_st is not None or dst.is_symlink():
            dst.unlink()
        try:
            os.link(src, dst)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            shutil.copyfile(src, dst)
            os.utime(dst, ns=(src_st.st_atime_ns, src_st.st_mtime_ns))
            dst_st2 = dst.stat()
            os.chmod(dst, statmod.S_IMODE(dst_st2.st_mode) & ~0o222)
    return dst


def gc_sweep(grace_s: float = 86400) -> list[Path]:
    """Reap objects with nlink==1 AND mtime older than ``grace_s`` seconds.

    nlink==1 means no projection references the inode (the refcount GC runs
    on); the grace window covers the store→first-link publish gap and keeps
    freshly stored objects alive. Also prunes the emptied fanout dirs and any
    stale non-dir litter (tmp files, stray symlinks) past grace. Returns
    removed paths.

    Each candidate is re-stat'd under the pool's EX lock: a racing link_out
    that bumped nlink after our unlocked peek is seen, never swept.
    """
    base = paths.lake_objects_dir()
    removed: list[Path] = []
    if not base.exists():
        return removed
    cutoff = time.time() - grace_s
    for p, kind in fsutil._iter_tree(base):
        if kind == "dir":
            continue
        try:
            st = p.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue  # a concurrent sweep already took it
        if st.st_nlink != 1 or st.st_mtime >= cutoff:
            continue
        with _cas_lock(exclusive=True):
            # re-check under EX — a link_out racing the unlocked peek has
            # already bumped nlink, so only still-dead inodes are unlinked
            try:
                st = p.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if st.st_nlink != 1 or st.st_mtime >= cutoff:
                continue
            try:
                p.unlink()
            except FileNotFoundError:
                continue
        removed.append(p)
        for d in (p.parent, p.parent.parent):  # prune emptied bb/aa dirs
            try:
                d.rmdir()
            except OSError:
                break
    return removed


def stat() -> dict:
    """Per-kind object census: ``{"<kind>": {"n": int, "bytes": int}}``
    over the whole objects dir (kind = the first path segment —
    objects/{blob,file}/…)."""
    base = paths.lake_objects_dir()
    out: dict[str, dict] = {}
    if base.exists():
        for p, kind in fsutil._iter_tree(base):
            if kind != "file":
                continue
            rel = p.relative_to(base).parts
            k = rel[0] if len(rel) > 1 else "?"
            slot = out.setdefault(k, {"n": 0, "bytes": 0})
            try:
                slot["bytes"] += p.stat(follow_symlinks=False).st_size
            except FileNotFoundError:
                continue  # raced with a sweep — skip, census is approximate
            slot["n"] += 1
    return out
