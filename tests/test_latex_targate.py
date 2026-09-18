r"""latex 层 tar 伪装 .tex 闸（``_tar_disguised`` 宿于 ``textutil.encoding``）。

``test_inject_targate.py`` 的翻译臂姊妹闸：inject 侧挡「tar 被当文本 tex
消费」，本闸挡 parse→reconstruct 写回面——``decode_tex`` 永不抛（latin-1
兜底），tar 成员文本里的 ``\documentclass``/散文会让伪装件被
``scan_tex_tree`` 枚举进翻译集、被 ``\input`` 展平内联，splice 写回即
腐蚀 blob。逐点验证：枚举跳过（三桶皆不入）、直读入口按 OSError 拒、
展平不内联成员文本；文本里 ``ustar`` 字样不假阳（chksum 轻校验挡）。
"""

from __future__ import annotations

import errno
import io
import tarfile
from typing import TYPE_CHECKING

import pytest

from texlate.latex.api import parse_file, parse_file_v1, scan_tex_tree
from texlate.latex.flatten import flatten_inputs

if TYPE_CHECKING:
    from pathlib import Path

_DOC = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
#: 过散文门需 ≥3 distinct 功能词（prose._MIN_FUNCWORDS）。
_PROSE = (
    "\\documentclass{article}\n\\begin{document}\n"
    "This paper studies the theory and the practice of these systems with care.\n"
    "\\end{document}\n"
)


def _tar_blob(*members: tuple[str, bytes]) -> bytes:
    """ustar blob——成员文本默认含 dc/bd 文档形态（latin-1 解出即假阳面）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in members or [
            ("inner/doc.tex", _DOC.encode()),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_scan_tex_tree_skips_tar(tmp_path: Path) -> None:
    """tar 伪装 .tex 与真稿同树：真稿进 parsed，伪装件三桶皆不入、逐字节不动。"""
    blob = _tar_blob()
    (tmp_path / "bundle.tex").write_bytes(blob)
    (tmp_path / "paper.tex").write_text(_PROSE, encoding="utf-8")
    tree = scan_tex_tree(tmp_path)
    assert [rel for _f, rel, _res in tree.parsed] == ["paper.tex"]
    assert "bundle.tex" not in tree.support
    assert [rel for rel, _exc in tree.fault] == []
    assert (tmp_path / "bundle.tex").read_bytes() == blob


def test_scan_tex_tree_only_tar(tmp_path: Path) -> None:
    """唯一 .tex 是 tar：parsed/support/fault 全空——跳过是有意排除而非失败。"""
    (tmp_path / "main.tex").write_bytes(_tar_blob())
    tree = scan_tex_tree(tmp_path)
    assert tree.parsed == []
    assert tree.support == []
    assert tree.fault == []


def test_parse_file_rejects_tar(tmp_path: Path) -> None:
    """直读入口（v2 默认 + v1 回退臂）对 tar main 按 OSError 拒——写回面堵死。"""
    (tmp_path / "blob.tex").write_bytes(_tar_blob())
    with pytest.raises(OSError, match="tar archive") as excinfo:
        parse_file(tmp_path / "blob.tex")
    assert excinfo.value.errno == errno.EINVAL
    with pytest.raises(OSError, match="tar archive") as excinfo_v1:
        parse_file_v1(tmp_path / "blob.tex")
    assert excinfo_v1.value.errno == errno.EINVAL


def test_flatten_inputs_skips_tar(tmp_path: Path) -> None:
    """``\\input`` 命中 tar：成员文本不内联，命令按字面回吐（非展开面）。"""
    blob = _tar_blob(
        ("chap/inner.tex", b"MEMBERPROSE \\documentclass{article}\n"),
    )
    (tmp_path / "chap.tex").write_bytes(blob)
    out = flatten_inputs(
        "\\documentclass{article}\n\\begin{document}\n\\input{chap}\n\\end{document}\n",
        str(tmp_path),
    )
    assert "\\input{chap}" in out
    assert "MEMBERPROSE" not in out  # 成员字节永不得进展平输出
    assert out.count("\\documentclass") == 1  # 成员 dc 不得混入


def test_flatten_inputs_real_still_inlines(tmp_path: Path) -> None:
    """对照臂：真 .tex 成员照常内联——闸不误伤正常 ``\\input`` 展开。"""
    (tmp_path / "chap.tex").write_text("real body text\n", encoding="utf-8")
    out = flatten_inputs("head\n\\input{chap}\ntail\n", str(tmp_path))
    assert "real body text" in out


def test_ustar_text_no_false_positive(tmp_path: Path) -> None:
    """正文含 ``ustar`` 字样（恰落魔数偏移 257）：chksum 校验挡假阳。"""
    head = b"\\documentclass{article}\n"
    blob = head + b"x" * (257 - len(head)) + b"ustar\n" + _PROSE.encode()
    assert blob[257:262] == b"ustar"  # 魔数落正位——纯文本照过闸
    (tmp_path / "main.tex").write_bytes(blob)
    res = parse_file(tmp_path / "main.tex", flatten=False)
    assert res is not None
    tree = scan_tex_tree(tmp_path)
    assert [rel for _f, rel, _res in tree.parsed] == ["main.tex"]
