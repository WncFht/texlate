r"""伪装二进制/非 UTF-8 支持件的注入闸（``normalize.py`` 字节面判定）。

0707.0382 实案：``AMSbsy.sty`` 实为 1MB tar blob——``decode_tex`` 永不抛
（latin-1 兜底），成员文本里的 ``\begin{document}`` 让 ``has_document``
命中，归一化臂把 ``\PassOptionsToPackage{no-math}{fontspec}`` +
XETEX_COMPATIBILITY 前置块
前置进 blob，``ustar`` 魔数被推离偏移 257，下游 fixloop 只能靠扫描窗
找回。上游字节面闸：tar 魔数命中件逐字节不动；非 strict-UTF-8 或含
NUL 的支持件不做兼容前导块注入（转码与其余手术照旧——全树 tex 源
落 UTF-8 是 invalid_utf8 防线不变量）。
"""

from __future__ import annotations

import io
import tarfile
from typing import TYPE_CHECKING

from texlate.compile.normalize import normalize_project

if TYPE_CHECKING:
    from pathlib import Path


def _tar_blob() -> bytes:
    """含 ``\\begin{document}`` 成员的 ustar blob——``has_document`` 命中形态。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        member = (
            b"\\documentclass{article}\n\\begin{document}\n"
            b"member \\usepackage{inputenc}\n\\end{document}\n"
        )
        info = tarfile.TarInfo("inner/doc.tex")
        info.size = len(member)
        tf.addfile(info, io.BytesIO(member))
    return buf.getvalue()


def test_tar_blob_sty_byte_identical(tmp_path: Path) -> None:
    """tar 伪装 .sty：prologue 不注、转码不写——逐字节原样留 fixloop 解包臂。"""
    blob = _tar_blob()
    (tmp_path / "AMSbsy.sty").write_bytes(blob)
    stats = normalize_project(tmp_path, "xelatex")
    assert (tmp_path / "AMSbsy.sty").read_bytes() == blob
    assert stats["rewritten"] == 0


def test_tar_blob_displaced_magic_still_gated(tmp_path: Path) -> None:
    """曾被前置文本推位的 tar（ustar 离 257）重扫仍按 tar 判——不二次腐蚀。"""
    mutated = b"% texlate prologue\n" * 40 + _tar_blob()
    assert mutated[257:262] != b"ustar"
    (tmp_path / "AMSbsy.sty").write_bytes(mutated)
    normalize_project(tmp_path, "xelatex")
    assert (tmp_path / "AMSbsy.sty").read_bytes() == mutated


def test_text_sty_with_document_gets_prologue(tmp_path: Path) -> None:
    """strict-UTF-8 文档形 .sty（含 bd）：现行语义保留——兼容前导块照注。"""
    src = (
        b"% doc-like sty\n\\begin{document}\n\\usepackage{inputenc}\n"
        b"x\n\\end{document}\n"
    )
    (tmp_path / "weird.sty").write_bytes(src)
    normalize_project(tmp_path, "xelatex")
    out = (tmp_path / "weird.sty").read_text(encoding="utf-8")
    assert out.startswith("\\PassOptionsToPackage{no-math}{fontspec}\n")
    assert "\\TeXlatePstObject" in out


def test_nonutf8_sty_no_prologue(tmp_path: Path) -> None:
    """latin-1 .sty：转码 UTF-8 照旧，兼容前导块不注（非 strict-UTF-8）。"""
    src = "% caf\xe9 latin\n\\begin{document}\nx\n\\end{document}\n".encode("latin-1")
    (tmp_path / "latin.sty").write_bytes(src)
    normalize_project(tmp_path, "xelatex")
    out = (tmp_path / "latin.sty").read_text(encoding="utf-8")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" not in out
    assert "\\providecommand{\\DeclareUnicodeCharacter}" not in out


def test_nul_blob_sty_no_prologue(tmp_path: Path) -> None:
    """ASCII+NUL 的 .sty（strict-UTF-8 也解得出）：NUL 即非文本证据，不注。"""
    src = b"\\begin{document}\nx\n\\end{document}\n" + b"\x00" * 8
    (tmp_path / "bin.sty").write_bytes(src)
    normalize_project(tmp_path, "xelatex")
    out = (tmp_path / "bin.sty").read_bytes()
    assert b"\\PassOptionsToPackage{no-math}{fontspec}" not in out
    assert b"\\providecommand{\\DeclareUnicodeCharacter}" not in out


def test_nonutf8_tex_doc_keeps_prologue(tmp_path: Path) -> None:
    """非 UTF-8 文档源仍注前导块——GBK 老稿转码后同权拿 XeTeX 兼容 shim。"""
    src = "\\documentclass{article}\n\\begin{document}\n汉\n\\end{document}\n".encode(
        "gbk"
    )
    (tmp_path / "main.tex").write_bytes(src)
    normalize_project(tmp_path, "xelatex", "main.tex")
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" in out
