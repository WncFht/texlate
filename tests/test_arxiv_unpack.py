import gzip
import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from texlate.arxiv.sniff import BlobKind, sniff
from texlate.arxiv.unpack import (
    STUB_PREFIX,
    unpack_single,
    unpack_sniffed,
    unpack_tar,
    write_manifest,
)

CORPUS_V2 = Path(__file__).resolve().parent.parent / "bench" / "corpus_v2"

BLOBS = sorted(CORPUS_V2.rglob("raw.*")) if CORPUS_V2.exists() else []


def _make_tar(members: list[tuple[tarfile.TarInfo, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _reg(name: str, size: int, **kw: object) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    for k, v in kw.items():
        setattr(info, k, v)
    return info


def _warn_kinds(warnings: list[str]) -> set[str]:
    return {w.split(":", 1)[0] for w in warnings}


@pytest.mark.skipif(not BLOBS, reason="corpus_v2 not present")
@pytest.mark.parametrize("blob", BLOBS, ids=[b.parent.name for b in BLOBS])
def test_unpack_corpus(blob: Path, tmp_path: Path) -> None:
    """139 个真实包全量解包：零逃逸 + mtree 清单与落盘字节 sha256 逐一对拍。"""
    s = sniff(blob.read_bytes())
    dest = tmp_path / "extracted"
    res = unpack_sniffed(s, dest, stem_hint="arXiv-testv1.tar.gz")
    assert res.n_files > 0
    dest_resolved = dest.resolve()
    for m in res.members:
        if m.kind in ("file", "hardlink"):
            on_disk = dest / m.path
            assert on_disk.resolve().is_relative_to(dest_resolved)
            assert hashlib.sha256(on_disk.read_bytes()).hexdigest() == m.sha256
            assert on_disk.stat().st_size == m.size
        elif m.kind == "symlink":
            link = dest / m.path
            assert link.is_symlink()
            # 链接目标必须仍在树内（resolve 后不越界）
            assert link.resolve().is_relative_to(dest_resolved)
    write_manifest(res, tmp_path)
    mtree = (tmp_path / "mtree.txt").read_text(encoding="utf-8").splitlines()
    assert len(mtree) == len(res.members)
    files_txt = (tmp_path / "files.txt").read_text(encoding="utf-8").splitlines()
    assert files_txt == res.files
    # 全语料每包 ≥1 个 TeX 源（.tex/.ltx/.latex；0203009 即 article.latex）
    assert res.tex_files >= 1


def test_reject_dotdot(tmp_path: Path) -> None:
    payload = _make_tar(
        [
            (_reg("../evil.tex", 5), b"xxxxx"),
            (_reg("a/../../deep.tex", 5), b"xxxxx"),
            (_reg("ok.tex", 5), b"xxxxx"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["ok.tex"]
    assert not (tmp_path.parent / "evil.tex").exists()
    assert "reject_path" in _warn_kinds(res.warnings)


def test_reject_absolute_and_drive(tmp_path: Path) -> None:
    payload = _make_tar(
        [
            (_reg("/etc/passwd", 3), b"xxx"),
            (_reg("C:/win/evil.tex", 3), b"xxx"),
            (_reg("sub/./ok.tex", 3), b"xxx"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["sub/ok.tex"]
    assert "reject_path" in _warn_kinds(res.warnings)


def test_nul_truncated_and_dotdot_normalized(tmp_path: Path) -> None:
    """tarfile 把成员名截断在首个 NUL——`a\\x00b.tex` 落盘为 `a`（不逃逸）。

    ``./././bare.tex`` 的 ``./`` 前缀剥离后正常落盘。
    """
    payload = _make_tar(
        [
            (_reg("a\x00b.tex", 3), b"xxx"),
            (_reg("./././bare.tex", 3), b"xxx"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["a", "bare.tex"]


def test_symlink_escape_rejected_in_tree_kept(tmp_path: Path) -> None:
    good = _reg("figs", 0)
    good.type = tarfile.DIRTYPE
    sym_ok = tarfile.TarInfo("figs/link.tex")
    sym_ok.type = tarfile.SYMTYPE
    sym_ok.linkname = "../real.tex"
    sym_bad = tarfile.TarInfo("evil.tex")
    sym_bad.type = tarfile.SYMTYPE
    sym_bad.linkname = "../../etc/passwd"
    payload = _make_tar(
        [(good, b""), (_reg("real.tex", 4), b"xxxx"), (sym_ok, b""), (sym_bad, b"")]
    )
    res = unpack_tar(payload, tmp_path)
    assert "reject_link" in _warn_kinds(res.warnings)
    assert "link_kept" in _warn_kinds(res.warnings)
    assert (tmp_path / "figs/link.tex").is_symlink()
    assert (tmp_path / "figs/link.tex").resolve() == (tmp_path / "real.tex").resolve()


def test_hardlink_materialized_and_dangling(tmp_path: Path) -> None:
    hl_ok = tarfile.TarInfo("dup.tex")
    hl_ok.type = tarfile.LNKTYPE
    hl_ok.linkname = "real.tex"
    hl_bad = tarfile.TarInfo("lost.tex")
    hl_bad.type = tarfile.LNKTYPE
    hl_bad.linkname = "ghost.tex"
    payload = _make_tar([(hl_ok, b""), (hl_bad, b""), (_reg("real.tex", 6), b"abcdef")])
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "dup.tex").read_bytes() == b"abcdef"
    kinds = _warn_kinds(res.warnings)
    assert "hardlink_materialized" in kinds
    assert "hardlink_dangling" in kinds


def test_reject_special_and_setuid(tmp_path: Path) -> None:
    fifo = tarfile.TarInfo("pipe")
    fifo.type = tarfile.FIFOTYPE
    suid = _reg("suid.tex", 3, mode=0o4755)
    payload = _make_tar([(fifo, b""), (suid, b"xxx"), (_reg("ok.tex", 3), b"xxx")])
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["ok.tex"]
    kinds = _warn_kinds(res.warnings)
    assert "reject_special" in kinds
    assert "reject_setuid" in kinds


def test_casefold_rename_and_dup(tmp_path: Path) -> None:
    payload = _make_tar(
        [
            (_reg("Fig1.eps", 2), b"aa"),
            (_reg("fig1.eps", 2), b"bb"),
            (_reg("Fig1.eps", 2), b"cc"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    kinds = _warn_kinds(res.warnings)
    assert "casefold_rename" in kinds
    assert "dup_member_overwrite" in kinds
    assert (tmp_path / "Fig1.eps").exists()
    renamed = [f for f in res.files if "~c" in f]
    assert len(renamed) == 1


def test_stub_marking(tmp_path: Path) -> None:
    auto_body = STUB_PREFIX + b" rest" + b"x" * 100
    big_body = b"y" * 200
    payload = _make_tar(
        [
            (_reg("tiny.tex", 10), b"0123456789"),
            (_reg("auto.tex", len(auto_body)), auto_body),
            (_reg("big.tex", len(big_body)), big_body),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert set(res.stub_files) == {"tiny.tex", "auto.tex"}
    assert "big.tex" not in res.stub_files


def test_file_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """不实体化 100MB——把上限压到 8B，10B 文件即触发拒绝。"""
    monkeypatch.setattr("texlate.arxiv.unpack.MAX_FILE_BYTES", 8)
    big_body = b"0123456789"
    payload = _make_tar(
        [
            (_reg("huge.bin", len(big_body)), big_body),
            (_reg("ok.tex", 3), b"xxx"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["ok.tex"]
    assert "reject_filesize" in _warn_kinds(res.warnings)


def test_unpack_single_names(tmp_path: Path) -> None:
    body = b"\\documentclass{article}\n" + b"x" * 500
    res = unpack_single(body, tmp_path, stem_hint="arXiv-hep-th9901001v2.gz")
    assert res.files == ["hep-th9901001v2.tex"]
    assert (tmp_path / res.files[0]).read_bytes() == body


def test_unpack_sniffed_dispatch(tmp_path: Path) -> None:
    body = b"\\documentclass{article}\n" + b"y" * 300
    s = sniff(gzip.compress(body))
    assert s.kind is BlobKind.SINGLE
    res = unpack_sniffed(s, tmp_path, stem_hint="arXiv-0807.5094v1.gz")
    assert res.files == ["0807.5094v1.tex"]


def test_absolute_and_drive_linkname_rejected(tmp_path: Path) -> None:
    """linkname 本体校验：绝对路径经 _link_rel 归一化会折成 in-tree——必须查原始串。

    归一化只做包内相对解析：``figs/x -> /etc/passwd`` 被算成 ``figs/etc/passwd``
    放行，但 ``symlink_to`` 用原始绝对路径，落盘即逃逸链接。
    """
    sym = tarfile.TarInfo("evil.tex")
    sym.type = tarfile.SYMTYPE
    sym.linkname = "/etc/passwd"
    hl = tarfile.TarInfo("hl.tex")
    hl.type = tarfile.LNKTYPE
    hl.linkname = "/etc/hosts"
    drv = tarfile.TarInfo("drv.tex")
    drv.type = tarfile.SYMTYPE
    drv.linkname = "C:/win/x"
    payload = _make_tar(
        [(sym, b""), (hl, b""), (drv, b""), (_reg("ok.tex", 3), b"xxx")]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["ok.tex"]
    assert not (tmp_path / "evil.tex").exists()
    assert "reject_link" in _warn_kinds(res.warnings)
    assert not any(m.kind in ("symlink", "hardlink") for m in res.members)


def test_file_over_symlink_replaces_link(tmp_path: Path) -> None:
    """后到同名 file 覆盖 symlink：先摘链再写，不穿链改写链接目标。"""
    sym = tarfile.TarInfo("a.tex")
    sym.type = tarfile.SYMTYPE
    sym.linkname = "b.tex"
    payload = _make_tar(
        [(_reg("b.tex", 3), b"old"), (sym, b""), (_reg("a.tex", 3), b"new")]
    )
    res = unpack_tar(payload, tmp_path)
    assert not (tmp_path / "a.tex").is_symlink()
    assert (tmp_path / "a.tex").read_bytes() == b"new"
    assert (tmp_path / "b.tex").read_bytes() == b"old"
    assert [m.path for m in res.members].count("a.tex") == 1
    assert "dup_member_overwrite" in _warn_kinds(res.warnings)
