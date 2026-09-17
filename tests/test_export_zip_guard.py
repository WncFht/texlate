r"""export zip 入口加固钉——A11 成员限量读 + A12 docx ``RecursionError`` 护栏。

- ``sniff_format`` mimetype 嗅探走 ``zf.open`` 有界读（≤64B）——
  ``ZipFile.read`` 全量解压路径不许再被调用（上传 EPUB 是不可信面，
  inflate 炸弹）；成员 deflate 流坏归 ``None``，``zlib.error`` 不裸逃。
- ``rights.check_epub`` 的 ``encryption.xml`` 按 1MB 闸（仿
  ``share._MANIFEST_MAX``）截断读——超限声明、成员级坏 CRC、坏
  deflate 流同判 ``"drm"``（"读不懂的声明按有害读"），不抛不穿。
- ``translate_docx`` 枚举/驱动两段的 ``RecursionError`` 折进
  ``UnsupportedFormatError``（epub 侧 ``MalformedEpubError`` 同款契约）。
"""

from __future__ import annotations

import struct
import zipfile
from typing import TYPE_CHECKING, NoReturn

import pytest
from docx import Document

from texlate.export import sniff_format
from texlate.export.common import UnsupportedFormatError
from texlate.export.docx import translate_docx
from texlate.export.rights import check_epub
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from pathlib import Path

_ENC = "META-INF/encryption.xml"
_FONT_OBF = "http://www.idpf.org/2008/embedding"


def _wzip(
    path: Path,
    members: dict[str, bytes],
    *,
    compress: int = zipfile.ZIP_DEFLATED,
) -> Path:
    """写 zip（成员序 = dict 序），``compress`` 控制全体成员压缩法。"""
    with zipfile.ZipFile(path, "w", compression=compress) as z:
        for name, blob in members.items():
            z.writestr(name, blob)
    return path


def _encdoc(inner: bytes) -> bytes:
    return (
        b'<?xml version="1.0"?>'
        b'<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        b'xmlns:enc="http://www.w3.org/2001/04/xmlenc#">' + inner + b"</encryption>"
    )


def _ed(alg: str) -> bytes:
    return (
        b"<enc:EncryptedData>"
        + f'<enc:EncryptionMethod Algorithm="{alg}"/>'.encode()
        + b'<enc:CipherData><enc:CipherReference URI=""/></enc:CipherData>'
        + b"</enc:EncryptedData>"
    )


def _corrupt_member(path: Path, name: str) -> None:
    """翻转成员压缩数据中段 16B——CRC 必失配，deflate 流通常也坏。"""
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo(name)
    blob = bytearray(path.read_bytes())
    off = info.header_offset
    assert blob[off : off + 4] == b"PK\x03\x04"
    fn_len, ex_len = struct.unpack_from("<HH", blob, off + 26)
    start = off + 30 + fn_len + ex_len
    mid = start + info.compress_size // 2
    for i in range(mid, min(mid + 16, start + info.compress_size)):
        blob[i] ^= 0xFF
    path.write_bytes(bytes(blob))


def _boom(*_a: object, **_k: object) -> NoReturn:
    raise RecursionError


def _make_docx(path: Path) -> Path:
    doc = Document()
    doc.add_paragraph("Body paragraph text.")
    doc.save(str(path))
    return path


# ---------------------------------------------------------------- sniff_format


def test_sniff_mimetype_uses_bounded_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """嗅探只读 mimetype 头 64B——``ZipFile.read`` 全量解压路径被禁调用。"""
    src = _wzip(tmp_path / "b.epub", {"mimetype": b"application/epub+zip"})
    calls: list[int] = []
    real_read = zipfile.ZipExtFile.read

    def _spy(self: zipfile.ZipExtFile, n: int = -1) -> bytes:
        calls.append(n)
        return real_read(self, n)

    def _no_full_read(*_a: object, **_k: object) -> NoReturn:
        msg = "zf.read 全量解压路径被调用"
        raise AssertionError(msg)

    monkeypatch.setattr(zipfile.ZipFile, "read", _no_full_read)
    monkeypatch.setattr(zipfile.ZipExtFile, "read", _spy)
    assert sniff_format(src) == "epub"
    cap = 64
    assert calls
    assert all(0 < n <= cap for n in calls)


def test_sniff_corrupt_mimetype_member_is_none(tmp_path: Path) -> None:
    """DEFLATE 流坏的 mimetype 成员 → ``None``——``zlib.error``/坏 CRC 入兜，不裸逃。"""
    src = _wzip(tmp_path / "c.epub", {"mimetype": b"application/epub+zip"})
    _corrupt_member(src, "mimetype")
    assert sniff_format(src) is None


# ---------------------------------------------------------------- check_epub


def test_encryption_xml_over_cap_is_drm(tmp_path: Path) -> None:
    """``encryption.xml`` 超 1MB 闸 → ``"drm"``——成员本体是合法字体混淆
    声明（无闸读全量会判 ``"ok"``），超限即"读不懂的声明"按有害读。"""
    big = _encdoc(b"<!--" + b"x" * (2 << 20) + b"-->" + _ed(_FONT_OBF))
    src = _wzip(tmp_path / "e.epub", {_ENC: big})
    assert check_epub(src) == "drm"


def test_encryption_xml_read_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """声明体有界读钉：每次 ``fp.read`` 的 ``n`` ≤ 闸 +1，不许全量解压。"""
    src = _wzip(tmp_path / "f.epub", {_ENC: _encdoc(_ed(_FONT_OBF))})
    calls: list[int] = []
    real_read = zipfile.ZipExtFile.read

    def _spy(self: zipfile.ZipExtFile, n: int = -1) -> bytes:
        calls.append(n)
        return real_read(self, n)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", _spy)
    assert check_epub(src) == "ok"
    cap = (1 << 20) + 1
    assert calls
    assert all(0 < n <= cap for n in calls)


def test_encryption_xml_member_crc_failure_is_drm(tmp_path: Path) -> None:
    """成员级坏 CRC 的 ``encryption.xml`` → ``"drm"``——此前 ``BadZipFile``
    漏进外层归 ``"ok"``，与"读不懂按有害读"契约相悖。"""
    src = _wzip(
        tmp_path / "g.epub",
        {_ENC: _encdoc(_ed(_FONT_OBF))},
        compress=zipfile.ZIP_STORED,
    )
    _corrupt_member(src, _ENC)
    assert check_epub(src) == "drm"


def test_encryption_xml_bad_deflate_is_drm(tmp_path: Path) -> None:
    """DEFLATE 流中段坏的 ``encryption.xml`` → ``"drm"``——``zlib.error``
    不再裸逃（``check_epub`` "绝不抛"不变量）。"""
    src = _wzip(tmp_path / "h.epub", {_ENC: _encdoc(_ed(_FONT_OBF))})
    _corrupt_member(src, _ENC)
    assert check_epub(src) == "drm"


# ---------------------------------------------------------------- docx 递归闸


def test_translate_docx_iter_units_recursion_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """枚举段 ``RecursionError`` → ``UnsupportedFormatError``，不裸逃。"""
    src = _make_docx(tmp_path / "in.docx")
    monkeypatch.setattr("texlate.export.docx.iter_units", _boom)
    with pytest.raises(UnsupportedFormatError, match="嵌套过深"):
        translate_docx(src, tmp_path / "out.docx", MockTranslator())


def test_translate_docx_pipeline_recursion_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """驱动段（``insert_after`` deepcopy/序列化）``RecursionError`` 同折。"""
    src = _make_docx(tmp_path / "in.docx")
    monkeypatch.setattr("texlate.export.docx.drive_pipeline", _boom)
    with pytest.raises(UnsupportedFormatError, match="嵌套过深"):
        translate_docx(src, tmp_path / "out.docx", MockTranslator())
