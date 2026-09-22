"""Tests for kernel.cas — object store layout, link_out, refcount GC."""
from __future__ import annotations

import errno
import hashlib
import os
import stat
import time
from pathlib import Path

import pytest

from kernel import cas, fsutil, paths


def _age(path: Path, seconds: float) -> None:
    """Push a file's atime/mtime `seconds` into the past (owner may utime a
    0444 file — only the mtime field changes, the fuse stays)."""
    old = time.time() - seconds
    os.utime(path, ns=(int(old * 1e9), int(old * 1e9)))


# --- layout / validation ---------------------------------------------------------


def test_object_path_fanout(broot):
    sha = "ab" + "cd" + "e" * 60
    assert cas.object_path(sha) == \
        paths.lake_objects_dir() / "blob" / "ab" / "cd" / sha
    assert cas.object_path(sha, kind="file") == \
        paths.lake_objects_dir() / "file" / "ab" / "cd" / sha


def test_object_path_rejects_traversal_and_bad_sha(broot):
    for bad in ("../escape", "a/b", "zz" * 32, "short", ""):
        with pytest.raises(ValueError):
            cas.object_path(bad)
    with pytest.raises(ValueError):
        cas.object_path("ab" * 32, kind="a/b")


# --- store -------------------------------------------------------------------------


def test_store_bytes_roundtrip_and_mode(broot):
    sha = cas.store_bytes(b"payload")
    assert sha == hashlib.sha256(b"payload").hexdigest()
    obj = cas.object_path(sha)
    assert obj.read_bytes() == b"payload"
    assert stat.S_IMODE(obj.stat().st_mode) == 0o444  # born 0444
    assert obj.parent.name == sha[2:4]                 # two-level fanout
    assert obj.parent.parent.name == sha[:2]


def test_store_bytes_idempotent(broot):
    assert cas.store_bytes(b"same") == cas.store_bytes(b"same")
    assert cas.stat()["blob"]["n"] == 1


def test_store_dedup_hit_refreshes_liveness(broot):
    sha = cas.store_bytes(b"aged")
    obj = cas.object_path(sha)
    _age(obj, 2 * 86400)                     # unlinked and past grace
    cas.store_bytes(b"aged")                 # dedup hit — bytes are live again
    assert obj.stat().st_mtime > time.time() - 60
    assert cas.gc_sweep(grace_s=86400) == []  # fresh grace window
    assert cas.has(sha)


def test_store_file_roundtrip_and_src_untouched(broot, tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"file-bytes" * 200)
    sha = cas.store_file(src)
    obj = cas.object_path(sha, kind="file")
    assert sha == hashlib.sha256(src.read_bytes()).hexdigest()
    assert obj.read_bytes() == src.read_bytes()
    assert stat.S_IMODE(obj.stat().st_mode) == 0o444
    # stored by COPY — src must never share the frozen inode
    assert os.stat(obj).st_ino != os.stat(src).st_ino
    assert stat.S_IMODE(src.stat().st_mode) & stat.S_IWUSR


def test_store_file_idempotent(broot, tmp_path):
    src = tmp_path / "f"
    src.write_bytes(b"x")
    assert cas.store_file(src) == cas.store_file(src)
    assert cas.stat()["file"]["n"] == 1


def test_store_file_rejects_special_and_missing(broot, tmp_path):
    os.mkfifo(tmp_path / "pipe")  # hashing a fifo would block forever
    with pytest.raises(ValueError, match="special file"):
        cas.store_file(tmp_path / "pipe")
    with pytest.raises(FileNotFoundError):
        cas.store_file(tmp_path / "missing")


def test_has(broot):
    sha = cas.store_bytes(b"q")
    assert cas.has(sha)
    assert not cas.has("f" * 64)


# --- link_out -----------------------------------------------------------------------


def test_link_out_shares_object_inode(broot, tmp_path):
    sha = cas.store_bytes(b"linkme")
    dst = tmp_path / "proj" / "x.bin"
    cas.link_out(sha, dst)
    assert dst.read_bytes() == b"linkme"
    obj = cas.object_path(sha)
    assert os.stat(dst).st_ino == os.stat(obj).st_ino
    assert stat.S_IMODE(dst.stat().st_mode) == 0o444  # fuse carried by the inode
    assert fsutil.nlink(obj) == 2                      # refcount grew


def test_link_out_idempotent(broot, tmp_path):
    sha = cas.store_bytes(b"z")
    dst = tmp_path / "x"
    cas.link_out(sha, dst)
    cas.link_out(sha, dst)  # same inode → no-op, no extra link churn
    assert fsutil.nlink(cas.object_path(sha)) == 2


def test_link_out_exdev_fallback(broot, tmp_path, monkeypatch):
    sha = cas.store_bytes(b"crossdev")
    dst = tmp_path / "x"
    monkeypatch.setattr(os, "link",
                        lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EXDEV, "x")))
    cas.link_out(sha, dst)
    obj = cas.object_path(sha)
    assert dst.read_bytes() == b"crossdev"
    assert os.stat(dst).st_ino != os.stat(obj).st_ino      # own copy
    assert stat.S_IMODE(dst.stat().st_mode) & 0o222 == 0   # still read-only
    assert dst.stat().st_mtime == obj.stat().st_mtime      # stat identity kept


def test_link_out_replaces_stale_without_touching_fuse(broot, tmp_path):
    sha_a = cas.store_bytes(b"AAA")
    sha_b = cas.store_bytes(b"BBBBB")
    dst = tmp_path / "x"
    cas.link_out(sha_a, dst)
    cas.link_out(sha_b, dst)  # dst was a 0444 link — must unlink, never chmod
    assert dst.read_bytes() == b"BBBBB"
    obj_a = cas.object_path(sha_a)
    assert stat.S_IMODE(obj_a.stat().st_mode) == 0o444  # object A fuse intact
    assert fsutil.nlink(obj_a) == 1
    assert os.stat(dst).st_ino == os.stat(cas.object_path(sha_b)).st_ino


def test_link_out_missing_object_raises(broot, tmp_path):
    with pytest.raises(FileNotFoundError):
        cas.link_out("a" * 64, tmp_path / "x")


# --- gc_sweep ------------------------------------------------------------------------


def test_gc_respects_grace_window(broot):
    sha = cas.store_bytes(b"young")  # nlink==1 but freshly stored
    assert cas.gc_sweep(grace_s=86400) == []
    assert cas.has(sha)
    obj = cas.object_path(sha)
    _age(obj, 2 * 86400)
    assert cas.gc_sweep(grace_s=86400) == [obj]
    assert not cas.has(sha)


def test_gc_skips_objects_with_links(broot, tmp_path):
    sha = cas.store_bytes(b"referenced")
    cas.link_out(sha, tmp_path / "proj")
    obj = cas.object_path(sha)
    _age(obj, 2 * 86400)  # ancient, but nlink==2 → alive
    assert cas.gc_sweep(grace_s=86400) == []
    assert cas.has(sha)
    assert (tmp_path / "proj").read_bytes() == b"referenced"


def test_gc_only_sweeps_past_grace(broot):
    fresh = cas.store_bytes(b"fresh")
    stale = cas.store_bytes(b"stale")
    _age(cas.object_path(stale), 90)
    removed = cas.gc_sweep(grace_s=60)
    assert removed == [cas.object_path(stale)]
    assert cas.has(fresh) and not cas.has(stale)


def test_gc_prunes_emptied_fanout_dirs(broot):
    sha = cas.store_bytes(b"x")
    _age(cas.object_path(sha), 10)
    cas.gc_sweep(grace_s=1)
    assert not (paths.lake_objects_dir() / "blob" / sha[:2]).exists()
    assert (paths.lake_objects_dir() / "blob").exists()  # kind dir itself stays


def test_gc_isolates_kinds(broot, tmp_path):
    f = tmp_path / "f"
    f.write_bytes(b"kind-bytes")
    sha_file = cas.store_file(f)                     # kind="file"
    _age(cas.object_path(sha_file, kind="file"), 10)
    sha_blob = cas.store_bytes(b"keep")
    removed = cas.gc_sweep(grace_s=1)
    assert removed == [cas.object_path(sha_file, kind="file")]
    assert cas.has(sha_blob)


# --- stat ----------------------------------------------------------------------------


def test_stat_counts_objects_and_bytes(broot, tmp_path):
    assert cas.stat() == {}
    cas.store_bytes(b"12345678")                     # 8 B blob
    f = tmp_path / "f"
    f.write_bytes(b"12")
    cas.store_file(f)                                # 2 B file
    assert cas.stat() == {
        "blob": {"n": 1, "bytes": 8},
        "file": {"n": 1, "bytes": 2},
    }
    # a projection outside the objects dir does not inflate the census
    cas.link_out(hashlib.sha256(b"12345678").hexdigest(), tmp_path / "p")
    assert cas.stat()["blob"]["n"] == 1
