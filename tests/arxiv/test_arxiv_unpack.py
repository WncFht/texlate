import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from conftest import make_tar, tar_reg

from texlate.arxiv.sniff import BlobKind, sniff
from texlate.arxiv.unpack import (
    STUB_PREFIX,
    UnpackError,
    unpack_single,
    unpack_sniffed,
    unpack_tar,
    write_manifest,
)

CORPUS = Path(__file__).resolve().parents[2] / "bench" / "corpus"
_MANIFEST_V2 = CORPUS / "manifest_v2.jsonl"

BLOBS = (
    sorted(
        b
        for line in _MANIFEST_V2.read_text().splitlines()
        for b in (CORPUS / json.loads(line)["id"]).glob("raw.*")
    )
    if _MANIFEST_V2.is_file()
    else []
)


def _warn_kinds(warnings: list[str]) -> set[str]:
    return {w.split(":", 1)[0] for w in warnings}


def _fix_ustar_checksum(raw: bytearray, off: int) -> None:
    """重算 ``off`` 处 ustar 头 checksum（直改 raw 头字段后封头必备）。"""
    chksum = (
        sum(raw[off : off + 148]) + sum(b"        ") + sum(raw[off + 156 : off + 512])
    )
    raw[off + 148 : off + 156] = f"{chksum:06o}\x00 ".encode()


@pytest.mark.slow
@pytest.mark.skipif(not BLOBS, reason="corpus not present")
@pytest.mark.parametrize("blob", BLOBS, ids=[b.parent.name for b in BLOBS])
def test_unpack_corpus(blob: Path, tmp_path: Path) -> None:
    """manifest_v2 全量真实包解包：零逃逸 + mtree 清单与落盘字节 sha256 逐一对拍。"""
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
    payload = make_tar(
        [
            (tar_reg("../evil.tex", 5), b"xxxxx"),
            (tar_reg("a/../../deep.tex", 5), b"xxxxx"),
            (tar_reg("ok.tex", 5), b"xxxxx"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["ok.tex"]
    assert not (tmp_path.parent / "evil.tex").exists()
    assert "reject_path" in _warn_kinds(res.warnings)


def test_reject_absolute_and_drive(tmp_path: Path) -> None:
    payload = make_tar(
        [
            (tar_reg("/etc/passwd", 3), b"xxx"),
            (tar_reg("C:/win/evil.tex", 3), b"xxx"),
            (tar_reg("sub/./ok.tex", 3), b"xxx"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["sub/ok.tex"]
    assert "reject_path" in _warn_kinds(res.warnings)


def test_nul_truncated_and_dotdot_normalized(tmp_path: Path) -> None:
    """tarfile 把成员名截断在首个 NUL——`a\\x00b.tex` 落盘为 `a`（不逃逸）。

    ``./././bare.tex`` 的 ``./`` 前缀剥离后正常落盘。
    """
    payload = make_tar(
        [
            (tar_reg("a\x00b.tex", 3), b"xxx"),
            (tar_reg("./././bare.tex", 3), b"xxx"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["a", "bare.tex"]


def test_symlink_escape_rejected_in_tree_kept(tmp_path: Path) -> None:
    good = tar_reg("figs", 0)
    good.type = tarfile.DIRTYPE
    sym_ok = tarfile.TarInfo("figs/link.tex")
    sym_ok.type = tarfile.SYMTYPE
    sym_ok.linkname = "../real.tex"
    sym_bad = tarfile.TarInfo("evil.tex")
    sym_bad.type = tarfile.SYMTYPE
    sym_bad.linkname = "../../etc/passwd"
    payload = make_tar(
        [(good, b""), (tar_reg("real.tex", 4), b"xxxx"), (sym_ok, b""), (sym_bad, b"")]
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
    payload = make_tar(
        [(hl_ok, b""), (hl_bad, b""), (tar_reg("real.tex", 6), b"abcdef")]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "dup.tex").read_bytes() == b"abcdef"
    kinds = _warn_kinds(res.warnings)
    assert "hardlink_materialized" in kinds
    assert "hardlink_dangling" in kinds


def test_reject_special_and_setuid(tmp_path: Path) -> None:
    fifo = tarfile.TarInfo("pipe")
    fifo.type = tarfile.FIFOTYPE
    suid = tar_reg("suid.tex", 3, mode=0o4755)
    payload = make_tar([(fifo, b""), (suid, b"xxx"), (tar_reg("ok.tex", 3), b"xxx")])
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["ok.tex"]
    kinds = _warn_kinds(res.warnings)
    assert "reject_special" in kinds
    assert "reject_setuid" in kinds


def test_casefold_rename_and_dup(tmp_path: Path) -> None:
    payload = make_tar(
        [
            (tar_reg("Fig1.eps", 2), b"aa"),
            (tar_reg("fig1.eps", 2), b"bb"),
            (tar_reg("Fig1.eps", 2), b"cc"),
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
    payload = make_tar(
        [
            (tar_reg("tiny.tex", 10), b"0123456789"),
            (tar_reg("auto.tex", len(auto_body)), auto_body),
            (tar_reg("big.tex", len(big_body)), big_body),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert set(res.stub_files) == {"tiny.tex", "auto.tex"}
    assert "big.tex" not in res.stub_files


def test_file_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """不实体化 100MB——把上限压到 8B，10B 文件即触发拒绝。"""
    monkeypatch.setattr("texlate.arxiv.unpack.MAX_FILE_BYTES", 8)
    big_body = b"0123456789"
    payload = make_tar(
        [
            (tar_reg("huge.bin", len(big_body)), big_body),
            (tar_reg("ok.tex", 3), b"xxx"),
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
    payload = make_tar(
        [(sym, b""), (hl, b""), (drv, b""), (tar_reg("ok.tex", 3), b"xxx")]
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
    payload = make_tar(
        [(tar_reg("b.tex", 3), b"old"), (sym, b""), (tar_reg("a.tex", 3), b"new")]
    )
    res = unpack_tar(payload, tmp_path)
    assert not (tmp_path / "a.tex").is_symlink()
    assert (tmp_path / "a.tex").read_bytes() == b"new"
    assert (tmp_path / "b.tex").read_bytes() == b"old"
    assert [m.path for m in res.members].count("a.tex") == 1
    assert "dup_member_overwrite" in _warn_kinds(res.warnings)


def test_control_char_member_names_rejected(tmp_path: Path) -> None:
    """成员名带 ``\\t``/``\\n``：POSIX 能落盘但 TSV manifest（files.txt/mtree.txt）
    行列结构被破坏（phantom 行）——按路径非法拒绝。"""
    payload = make_tar(
        [
            (tar_reg("a\tb.tex", 3), b"xxx"),
            (tar_reg("c\nd.tex", 3), b"xxx"),
            (tar_reg("e\rf.tex", 3), b"xxx"),
            (tar_reg("ok.tex", 3), b"xxx"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["ok.tex"]
    assert _warn_kinds(res.warnings) >= {"reject_path"}
    write_manifest(res, tmp_path)
    # manifest 行列不被污染：每行恰一条成员
    assert (tmp_path / "files.txt").read_text().splitlines() == ["ok.tex"]
    assert len((tmp_path / "mtree.txt").read_text().splitlines()) == 1


def test_control_char_linkname_rejected(tmp_path: Path) -> None:
    """linkname 带 ``\\t``/``\\n`` 同样污染 mtree ``-> target`` 列——拒绝。"""
    sym = tarfile.TarInfo("ln.tex")
    sym.type = tarfile.SYMTYPE
    sym.linkname = "real\ttex"
    sym2 = tarfile.TarInfo("ln2.tex")
    sym2.type = tarfile.SYMTYPE
    sym2.linkname = "real\ntex"
    payload = make_tar([(sym, b""), (sym2, b""), (tar_reg("ok.tex", 3), b"xxx")])
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["ok.tex"]
    assert not any(m.kind in ("symlink", "hardlink") for m in res.members)
    assert "reject_link" in _warn_kinds(res.warnings)


def test_file_then_child_member_skipped(tmp_path: Path) -> None:
    """``foo``（file）后出现 ``foo/bar.tex``——mkdir 撞文件会 FileExistsError
    整包流产；按成员级 ``reject_dir_clash`` 告警跳过。"""
    payload = make_tar(
        [
            (tar_reg("foo", 3), b"abc"),
            (tar_reg("foo/bar.tex", 3), b"def"),
            (tar_reg("ok.tex", 3), b"xxx"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "foo").read_bytes() == b"abc"
    assert not (tmp_path / "foo").is_dir()
    assert "reject_dir_clash" in _warn_kinds(res.warnings)
    assert "ok.tex" in res.files


def test_dir_member_parent_is_file_skipped(tmp_path: Path) -> None:
    """``foo``（file）后出现 ``foo/bar``（dir 成员）——同 clash 路径。"""
    d = tarfile.TarInfo("foo/bar")
    d.type = tarfile.DIRTYPE
    payload = make_tar(
        [(tar_reg("foo", 3), b"abc"), (d, b""), (tar_reg("ok.tex", 3), b"xxx")]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "foo").is_file()
    assert "reject_dir_clash" in _warn_kinds(res.warnings)
    assert "ok.tex" in res.files


def test_symlink_member_over_dir_clash(tmp_path: Path) -> None:
    """symlink 成员名撞上隐式目录（文件父级 mkdir 产生、不在 ``seen``）：
    ``target.unlink()`` 会 IsADirectoryError——按 clash 告警跳过不崩。"""
    sym = tarfile.TarInfo("sub")
    sym.type = tarfile.SYMTYPE
    sym.linkname = "ok.tex"
    payload = make_tar(
        [(tar_reg("sub/x.tex", 3), b"xxx"), (tar_reg("ok.tex", 3), b"xxx"), (sym, b"")]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "sub").is_dir()
    assert not (tmp_path / "sub").is_symlink()
    assert "reject_dir_clash" in _warn_kinds(res.warnings)


def test_non_utf8_member_name_rejected(tmp_path: Path) -> None:
    """非 UTF-8 原名（tarfile surrogateescape → 代理区）按 ``reject_path`` 拒。

    此前代理区名能落盘，但 write_manifest / meta.json 写 utf-8 时炸
    UnicodeEncodeError——拒绝即拒绝，告警文本经 ``_safe`` 转义可编码。
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        info = tar_reg("ok.tex", 3)
        tf.addfile(info, io.BytesIO(b"xxx"))
    raw = bytearray(buf.getvalue())
    raw[0:7] = b"caf\xe9.te"  # ustar name 头段塞 raw 0xE9（非法 UTF-8）
    _fix_ustar_checksum(raw, 0)
    res = unpack_tar(bytes(raw), tmp_path)
    assert res.files == []
    assert "reject_path" in _warn_kinds(res.warnings)
    # manifest 不再被代理区名炸掉
    write_manifest(res, tmp_path)
    assert (tmp_path / "files.txt").read_text() == ""
    # 告警串本身可 utf-8/json 编码（含转义后的代理区）
    for w in res.warnings:
        w.encode("utf-8")


def test_corrupt_mid_header_raises(tmp_path: Path) -> None:
    """成员头 checksum 坏在中途：tarfile 静默停枚举（errorlevel=2 也不抛）。

    尾部残余非零字节 = 有成员未交付——mtree 会谎报完整，按损坏归档 UnpackError。
    """
    payload = bytearray(
        make_tar([(tar_reg(n, 5), b"x" * 5) for n in ("a.tex", "b.tex", "c.tex")])
    )
    payload[1024 + 148 : 1024 + 150] = b"99"  # b.tex 头 checksum
    with pytest.raises(UnpackError, match="corrupt member stream"):
        unpack_tar(bytes(payload), tmp_path)


def test_dup_symlink_last_wins(tmp_path: Path) -> None:
    """同名 symlink 成员重复：last-wins + ``dup_member_overwrite``。

    修复前无条件改名出 ``x~c2`` 幽灵成员、旧链接残留——与 file 的
    ``_claim`` 语义对齐后只留最后一条。
    """
    s1 = tarfile.TarInfo("x.tex")
    s1.type = tarfile.SYMTYPE
    s1.linkname = "a.tex"
    s2 = tarfile.TarInfo("x.tex")
    s2.type = tarfile.SYMTYPE
    s2.linkname = "b.tex"
    payload = make_tar(
        [
            (tar_reg("a.tex", 3), b"aaa"),
            (tar_reg("b.tex", 3), b"bbb"),
            (s1, b""),
            (s2, b""),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert "dup_member_overwrite" in _warn_kinds(res.warnings)
    assert (tmp_path / "x.tex").readlink() == Path("b.tex")
    assert not (tmp_path / "x~c2.tex").exists()
    assert not (tmp_path / "x~c2.tex").is_symlink()
    assert [m.path for m in res.members].count("x.tex") == 1


def test_symlink_over_file_replaces_and_mtree_consistent(tmp_path: Path) -> None:
    """file x 在前、symlink x 在后：last-wins 换成链接，mtree 摘旧 file 条目。"""
    s = tarfile.TarInfo("x.tex")
    s.type = tarfile.SYMTYPE
    s.linkname = "a.tex"
    payload = make_tar(
        [(tar_reg("a.tex", 3), b"aaa"), (tar_reg("x.tex", 5), b"filex"), (s, b"")]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "x.tex").is_symlink()
    assert (tmp_path / "x.tex").readlink() == Path("a.tex")
    entries = [m for m in res.members if m.path == "x.tex"]
    assert len(entries) == 1
    assert entries[0].kind == "symlink"
    assert "x.tex" not in res.files  # symlink 不计入 files


def test_hardlink_does_not_clobber_later_file(tmp_path: Path) -> None:
    """hardlink x→y 在前、file x 在后：延迟物化不得反盖后到成员。

    修复前 ``_finish_links`` 无条件物化，x.tex 落成 y 的内容而非 file 的。
    """
    h = tarfile.TarInfo("x.tex")
    h.type = tarfile.LNKTYPE
    h.linkname = "y.tex"
    payload = make_tar(
        [(h, b""), (tar_reg("x.tex", 4), b"FILE"), (tar_reg("y.tex", 4), b"HLNK")]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "x.tex").read_bytes() == b"FILE"
    kinds = {m.path: m.kind for m in res.members}
    assert kinds["x.tex"] == "file"


def test_later_hardlink_still_materializes(tmp_path: Path) -> None:
    """file x 在前、hardlink x→y 在后：后到 hardlink 正常物化覆盖（last-wins）。"""
    h = tarfile.TarInfo("x.tex")
    h.type = tarfile.LNKTYPE
    h.linkname = "y.tex"
    payload = make_tar(
        [(tar_reg("x.tex", 4), b"FILE"), (h, b""), (tar_reg("y.tex", 4), b"HLNK")]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "x.tex").read_bytes() == b"HLNK"
    kinds = {m.path: m.kind for m in res.members}
    assert kinds["x.tex"] == "hardlink"


def test_long_member_name_member_level_reject(tmp_path: Path) -> None:
    """PAX longname >255B：ENAMETOOLONG 不再整包流产，成员级 ``reject_io``。"""
    long_name = "d/" + "x" * 300 + ".tex"
    payload = make_tar(
        [(tar_reg(long_name, 3), b"xxx"), (tar_reg("ok.tex", 3), b"xxx")]
    )
    res = unpack_tar(payload, tmp_path)
    assert res.files == ["ok.tex"]
    assert "reject_io" in _warn_kinds(res.warnings)


def test_dangling_symlink_parent_member_reject(tmp_path: Path) -> None:
    """保留的 dangling symlink（d→ghost）作父级：成员 ``d/x.tex`` 的
    mkdir 撞 EEXIST——成员级 ``reject_io`` 而非整包 OSError。"""
    s = tarfile.TarInfo("d")
    s.type = tarfile.SYMTYPE
    s.linkname = "ghost"
    payload = make_tar(
        [(s, b""), (tar_reg("d/x.tex", 3), b"xxx"), (tar_reg("ok.tex", 3), b"xxx")]
    )
    res = unpack_tar(payload, tmp_path)
    assert "ok.tex" in res.files
    assert "d/x.tex" not in res.files
    assert "reject_io" in _warn_kinds(res.warnings)


def test_dir_member_over_file_warns(tmp_path: Path) -> None:
    """file x 在前、dir 成员 x 在后：此前静默幂等返回，现按 ``reject_dir_clash``
    告警——与 file-over-dir 对称（先到者保）。"""
    d = tarfile.TarInfo("x")
    d.type = tarfile.DIRTYPE
    payload = make_tar(
        [(tar_reg("x", 3), b"abc"), (d, b""), (tar_reg("ok.tex", 3), b"xxx")]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "x").is_file()
    assert "reject_dir_clash" in _warn_kinds(res.warnings)


def test_surrogate_linkname_rejected(tmp_path: Path) -> None:
    """linkname 带代理区（非 UTF-8 原名）——kept 后 mtree ``-> target`` 会炸
    编码，按 ``reject_link`` 拒。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        tf.addfile(tar_reg("ok.tex", 3), io.BytesIO(b"xxx"))
        s = tarfile.TarInfo("ln.tex")
        s.type = tarfile.SYMTYPE
        s.linkname = "tgt"  # 占位，下面替换成 raw 0xE9
        tf.addfile(s, io.BytesIO(b""))
    raw = bytearray(buf.getvalue())
    # ln.tex 是第 2 个成员：ok 头 (512)+数据 (512)、ln 头在 offset 1024；
    # ustar linkname 字段在头内 offset 157
    raw[1024 + 157 : 1024 + 160] = b"t\xe9t"
    _fix_ustar_checksum(raw, 1024)
    res = unpack_tar(bytes(raw), tmp_path)
    assert res.files == ["ok.tex"]
    assert not any(m.kind == "symlink" for m in res.members)
    assert "reject_link" in _warn_kinds(res.warnings)
    for w in res.warnings:
        w.encode("utf-8")
