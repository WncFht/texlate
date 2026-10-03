"""Tests for kernel.fsutil — durability, projection protocols, mtree."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import sys
from typing import TYPE_CHECKING

import pytest
from kernel import fsutil

if TYPE_CHECKING:
    from pathlib import Path

#: 保险丝只读模式——a-w 提交后叶子/目录的位样
_FUSE_MODE = 0o444
#: 一条额外硬链后的 inode 引用计数
_NLINK_LINKED = 2
#: 各用例 fixture 源树的文件数——farm/copy 返回值即物化叶数
_N_SRC_FILES = 2


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


# --- atomic_write / fsync_dir -------------------------------------------------


def test_atomic_write_content_and_no_litter(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    fsutil.atomic_write(target, b"payload-bytes")
    assert target.read_bytes() == b"payload-bytes"
    assert [p.name for p in tmp_path.iterdir()] == ["out.bin"]  # no tmp litter


def test_atomic_write_replaces_existing(tmp_path: Path) -> None:
    target = tmp_path / "f"
    fsutil.atomic_write(target, b"old")
    fsutil.atomic_write(target, b"new")
    assert target.read_bytes() == b"new"


def test_atomic_write_mode_born_readonly(tmp_path: Path) -> None:
    target = tmp_path / "ro"
    fsutil.atomic_write(target, b"x", mode=_FUSE_MODE)
    assert stat.S_IMODE(target.stat().st_mode) == _FUSE_MODE


def test_atomic_write_cleans_tmp_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fsync"))
    )
    with pytest.raises(OSError, match="fsync"):
        fsutil.atomic_write(tmp_path / "f", b"data")
    assert not (tmp_path / "f").exists()
    assert list(tmp_path.iterdir()) == []


def test_fsync_dir(tmp_path: Path) -> None:
    fsutil.fsync_dir(tmp_path)  # must not raise


# --- has_nonwritable / nlink / dir_size ----------------------------------------


def test_has_nonwritable_finds_0444_file(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a.txt": b"a", "sub/b.txt": b"b"})
    ro = t / "sub" / "b.txt"
    ro.chmod(_FUSE_MODE)
    assert fsutil.has_nonwritable(t) == [ro]


def test_has_nonwritable_clean_tree(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a": b"1", "d/b": b"2"})
    assert fsutil.has_nonwritable(t) == []


def test_has_nonwritable_flags_readonly_dir(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"d/f": b"x"})
    (t / "d").chmod(0o555)
    try:
        assert fsutil.has_nonwritable(t) == [t / "d"]
    finally:
        (t / "d").chmod(0o755)  # restore so tmp teardown can clean


def test_has_nonwritable_flags_readonly_root(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"f": b"x"})
    t.chmod(0o555)  # vault commit's `chmod -R a-w` locks dirs too
    try:
        assert fsutil.has_nonwritable(t) == [t]
    finally:
        t.chmod(0o755)


def test_nlink(tmp_path: Path) -> None:
    f = tmp_path / "f"
    f.write_bytes(b"x")
    assert fsutil.nlink(f) == 1
    os.link(f, tmp_path / "g")
    assert fsutil.nlink(f) == _NLINK_LINKED


def test_dir_size_apparent(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a": b"12345", "d/b": b"678"})
    assert fsutil.dir_size(t) == 8  # noqa: PLR2004 -- 断言字面量（5+3 apparent 字节）


def test_dir_size_counts_hardlinks_per_path(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a": b"1234"})
    os.link(t / "a", t / "b")
    assert fsutil.dir_size(t) == 8  # noqa: PLR2004 -- 断言字面量（两路径各 4 字节）


# --- hardlink_farm ---------------------------------------------------------------


def test_hardlink_farm_shares_inodes(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a.txt": b"alpha", "sub/b.bin": b"\x00\x01"})
    dst = tmp_path / "dst"
    assert fsutil.hardlink_farm(src, dst) == _N_SRC_FILES
    for rel in ("a.txt", "sub/b.bin"):
        s, d = src / rel, dst / rel
        assert d.read_bytes() == s.read_bytes()
        assert s.stat().st_ino == d.stat().st_ino  # same inode


def test_hardlink_farm_carries_0444_fuse(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"ro": b"x"})
    (src / "ro").chmod(_FUSE_MODE)
    dst = tmp_path / "dst"
    fsutil.hardlink_farm(src, dst)
    assert stat.S_IMODE((dst / "ro").stat().st_mode) == _FUSE_MODE


def test_hardlink_farm_skips_already_materialized(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a": b"1", "b": b"22"})
    dst = tmp_path / "dst"
    fsutil.hardlink_farm(src, dst)
    assert fsutil.hardlink_farm(src, dst) == 0  # same (size,mtime) → skip


def test_hardlink_farm_relinks_replaced_source(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a": b"1"})
    dst = tmp_path / "dst"
    fsutil.hardlink_farm(src, dst)
    (src / "a").unlink()  # new inode, not an in-place write
    (src / "a").write_bytes(b"longer-content")
    assert fsutil.hardlink_farm(src, dst) == 1
    assert (dst / "a").read_bytes() == b"longer-content"
    assert (src / "a").stat().st_ino == (dst / "a").stat().st_ino


def test_hardlink_farm_exdev_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _tree(tmp_path / "src", {"a": b"data", "d/b": b"xx"})
    dst = tmp_path / "dst"

    def exdev(*_a: object, **_k: object) -> None:
        raise OSError(errno.EXDEV, "cross-device link disallowed")

    monkeypatch.setattr(os, "link", exdev)
    assert fsutil.hardlink_farm(src, dst) == _N_SRC_FILES
    for rel in ("a", "d/b"):
        s, d = src / rel, dst / rel
        assert d.read_bytes() == s.read_bytes()
        assert s.stat().st_ino != d.stat().st_ino  # real copy
        assert stat.S_IMODE(d.stat().st_mode) & 0o222 == 0  # still read-only
        assert d.stat().st_mtime == s.stat().st_mtime  # mtime preserved


def test_hardlink_farm_exdev_copy_skipped_on_refarm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = _tree(tmp_path / "src", {"a": b"data"})
    dst = tmp_path / "dst"
    monkeypatch.setattr(
        os, "link", lambda *_a, **_k: (_ for _ in ()).throw(OSError(errno.EXDEV, "x"))
    )
    fsutil.hardlink_farm(src, dst)
    monkeypatch.undo()  # real os.link again; (size,mtime) match must skip
    assert fsutil.hardlink_farm(src, dst) == 0


def test_hardlink_farm_drift_raises_before_touching_dst(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a": b"1", "b": b"2"})
    mtree = fsutil.build_mtree(src)
    (src / "b").write_bytes(b"changed-content")  # size+mtime drift
    dst = tmp_path / "dst"
    with pytest.raises(fsutil.DriftError) as excinfo:
        fsutil.hardlink_farm(src, dst, mtree=mtree)
    assert excinfo.value.drifted == ["b"]
    assert not dst.exists()  # verify ran before any mutation


def test_hardlink_farm_missing_source_file_drifts(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a": b"1"})
    mtree = fsutil.build_mtree(src)
    (src / "a").unlink()
    with pytest.raises(fsutil.DriftError):
        fsutil.hardlink_farm(src, tmp_path / "dst", mtree=mtree)


def test_hardlink_farm_mtree_as_path(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a": b"1"})
    m = fsutil.write_mtree(src)
    dst = tmp_path / "dst"
    # verify passes (self-manifest is not drift) and the projection carries
    # mtree.txt along like any other file — 2 leaves materialized.
    assert fsutil.hardlink_farm(src, dst, mtree=src / "mtree.txt") == _N_SRC_FILES
    assert (dst / "mtree.txt").exists()
    assert m["a"]["size"] == 1


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo 缺席平台")
def test_hardlink_farm_raises_on_special_file(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"ok": b"1"})
    os.mkfifo(src / "pipe")
    with pytest.raises(ValueError, match="special file"):
        fsutil.hardlink_farm(src, tmp_path / "dst")


# --- copy_mutating ----------------------------------------------------------------


def test_copy_mutating_delivers_writable_from_0444(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"ro.txt": b"locked", "sub/ro2.txt": b"y"})
    for f in (src / "ro.txt", src / "sub" / "ro2.txt"):
        f.chmod(_FUSE_MODE)
    dst = tmp_path / "dst"
    assert fsutil.copy_mutating(src, dst) == _N_SRC_FILES
    for rel in ("ro.txt", "sub/ro2.txt"):
        s, d = src / rel, dst / rel
        assert d.read_bytes() == s.read_bytes()
        assert stat.S_IMODE(d.stat().st_mode) & stat.S_IWUSR  # owner-writable
        assert d.stat().st_ino != s.stat().st_ino  # copy, not link
        d.write_bytes(b"mutated")  # provably writable


def test_copy_mutating_overwrites_stale_dst(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"a": b"new"})
    dst = _tree(tmp_path / "dst", {"a": b"old", "keep/b": b"k"})
    assert fsutil.copy_mutating(src, dst) == 1
    assert (dst / "a").read_bytes() == b"new"
    assert (dst / "keep" / "b").read_bytes() == b"k"  # unrelated files untouched


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="win32 readonly 文件不可 unlink——POSIX fuse 语义不可表达",
)
def test_copy_mutating_never_chmods_shared_inode(tmp_path: Path) -> None:
    # dst leaf is a hardlink to a 0444 pool inode — chmod'ing it would melt the
    # fuse for every alias (the §3.10.2 ban). copy_mutating must unlink instead.
    pool = _tree(tmp_path / "pool", {"obj": b"pool-bytes"})
    (pool / "obj").chmod(_FUSE_MODE)
    src = _tree(tmp_path / "src", {"f": b"fresh"})
    dst = tmp_path / "dst"
    dst.mkdir()
    os.link(pool / "obj", dst / "f")
    fsutil.copy_mutating(src, dst)
    assert (dst / "f").read_bytes() == b"fresh"
    assert (dst / "f").stat().st_ino != (pool / "obj").stat().st_ino
    assert (pool / "obj").read_bytes() == b"pool-bytes"
    assert stat.S_IMODE((pool / "obj").stat().st_mode) == _FUSE_MODE  # fuse intact


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo 缺席平台")
def test_copy_mutating_raises_on_special_file(tmp_path: Path) -> None:
    src = _tree(tmp_path / "src", {"ok": b"1"})
    os.mkfifo(src / "pipe")  # copyfile on a fifo would block — refuse loudly
    with pytest.raises(ValueError, match="special file"):
        fsutil.copy_mutating(src, tmp_path / "dst")


# --- mtree -------------------------------------------------------------------------


def test_build_mtree_basic(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a": b"12345", "sub/b": b"xy"})
    m = fsutil.build_mtree(t)
    assert set(m) == {"a", "sub/b"}
    assert m["a"]["size"] == 5  # noqa: PLR2004 -- 断言字面量（b"12345" 五字节）
    assert m["a"]["mtime"] == (t / "a").stat().st_mtime
    assert "sha256" not in m["a"]


def test_build_mtree_with_sha(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a": b"hello"})
    m = fsutil.build_mtree(t, with_sha=True)
    assert m["a"]["sha256"] == hashlib.sha256(b"hello").hexdigest()


def test_write_mtree_roundtrip_and_self_exclusion(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a": b"1", "d/b": b"2"})
    m = fsutil.write_mtree(t, with_sha=True)
    assert (t / "mtree.txt").exists()
    assert "mtree.txt" not in m  # manifest must not describe itself
    assert fsutil.verify_mtree(t, m) == []  # dict form
    assert fsutil.verify_mtree(t, t / "mtree.txt") == []  # file form — the
    # self-manifest file in the tree is metadata, not unmanifested payload


def test_verify_mtree_detects_all_drift_kinds(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a": b"1", "b": b"2"})
    m = fsutil.build_mtree(t)
    (t / "a").write_bytes(b"much longer")  # size drift
    (t / "b").unlink()  # missing
    (t / "extra").write_bytes(b"x")  # unmanifested payload
    assert fsutil.verify_mtree(t, m) == ["a", "b", "extra"]


def test_verify_mtree_resha_catches_same_size_same_mtime_swap(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a": b"AAAA"})
    m = fsutil.build_mtree(t, with_sha=True)
    st = (t / "a").stat()
    (t / "a").write_bytes(b"BBBB")
    os.utime(t / "a", ns=(st.st_atime_ns, st.st_mtime_ns))  # forged stat identity
    assert fsutil.verify_mtree(t, m) == []  # stat-level passes
    assert fsutil.verify_mtree(t, m, resha_sample=1.0) == ["a"]  # sha catches it


def test_verify_mtree_empty_tree(tmp_path: Path) -> None:
    t = tmp_path / "empty"
    t.mkdir()
    assert fsutil.build_mtree(t) == {}
    assert fsutil.verify_mtree(t, {}) == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo 缺席平台")
def test_verify_mtree_flags_special_file(tmp_path: Path) -> None:
    t = _tree(tmp_path / "t", {"a": b"1", "b": b"2"})
    m = fsutil.build_mtree(t)
    (t / "a").unlink()
    os.mkfifo(t / "a")  # manifest entry became a special file
    os.mkfifo(t / "sneaky")  # unmanifested special file
    assert fsutil.verify_mtree(t, m) == ["a", "sneaky"]
