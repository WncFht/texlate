r"""``export.epub`` 双语插译测试——手工最小 EPUB zip，不碰真书/真网关。

覆盖：spine+manifest 枚举、克隆插译 + ``texlate-zh``/语言章、marker 往返
（``<code>`` 保护行内元素）、NCX ``原文 / 译文``、mimetype-first-ZIP_STORED
出包、``dc:language`` 重写、DRM/fixed-layout/畸形拒翻、StateStore 断点续跑。
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import TYPE_CHECKING

import pytest
from bs4 import BeautifulSoup

from texlate.export.common import DrmError, FixedLayoutError, MalformedEpubError
from texlate.export.epub import iter_units, load_epub, translate_epub
from texlate.export.rights import check_epub
from texlate.xlat.pipeline import MockTranslator
from texlate.xlat.state import ChunkRecord, StateStore

if TYPE_CHECKING:
    from pathlib import Path

CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

NCX_XML = """<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1"><navLabel><text>Chapter One</text></navLabel>
      <content src="ch1.xhtml"/></navPoint>
  </navMap>
</ncx>
"""

XHTML_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>t</title></head>
<body>{body}</body>
</html>
"""

FONT_OBFUSCATED_ENCRYPTION = """<?xml version="1.0"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedData>
    <enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>
    <enc:CipherData><enc:CipherReference URI="OEBPS/font.ttf"/></enc:CipherData>
  </enc:EncryptedData>
</encryption>
"""

AES_ENCRYPTION = FONT_OBFUSCATED_ENCRYPTION.replace(
    "http://www.idpf.org/2008/embedding",
    "http://www.w3.org/2001/04/xmlenc#aes256-cbc",
)


def _opf(chapters: list[str], *, ncx: bool = True, fixed: bool = False) -> str:
    items = "\n".join(
        f'    <item id="c{i}" href="{name}" media-type="application/xhtml+xml"/>'
        for i, name in enumerate(chapters)
    )
    refs = "\n".join(f'    <itemref idref="c{i}"/>' for i in range(len(chapters)))
    ncx_item = (
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        if ncx
        else ""
    )
    layout = (
        '    <meta property="rendition:layout">pre-paginated</meta>\n' if fixed else ""
    )
    return f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bid">test-book</dc:identifier>
    <dc:title>Test</dc:title>
    <dc:language>en</dc:language>
{layout}  </metadata>
  <manifest>
{items}
{ncx_item}  </manifest>
  <spine>
{refs}
  </spine>
</package>
"""


def _epub(
    chapters: dict[str, str],
    *,
    ncx: bool = True,
    extra: dict[str, bytes | str] | None = None,
    fixed: bool = False,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("OEBPS/content.opf", _opf(list(chapters), ncx=ncx, fixed=fixed))
        for name, body in chapters.items():
            z.writestr(f"OEBPS/{name}", XHTML_TMPL.format(body=body))
        if ncx:
            z.writestr("OEBPS/toc.ncx", NCX_XML)
        for name, blob in (extra or {}).items():
            z.writestr(name, blob)
    return buf.getvalue()


def _write_epub(tmp_path: Path, blob: bytes, name: str = "book.epub") -> Path:
    src = tmp_path / name
    src.write_bytes(blob)
    return src


class _EchoTranslator:
    """原样回显（剥掉批行 ``[n]`` 前缀）——译文 == 原文走 unchanged 分支。"""

    async def translate(self, **_kw: object) -> str:
        user = str(_kw["user"])
        return "\n".join(re.sub(r"^\[\d+\]\s?", "", ln) for ln in user.split("\n"))


def test_translate_epub_bilingual(tmp_path: Path) -> None:
    src = _write_epub(
        tmp_path,
        _epub(
            {
                "ch1.xhtml": (
                    '<p id="p1">Hello world this is a paragraph.</p>'
                    "<p>Second paragraph follows here.</p>"
                )
            }
        ),
    )
    dst = tmp_path / "out.epub"
    report = translate_epub(src, dst, MockTranslator())

    assert report.format == "epub"
    assert report.units >= 3  # noqa: PLR2004 -- 两个段落 + NCX 目录标签
    assert report.translated == report.units
    assert report.fault == 0

    with zipfile.ZipFile(dst) as z:
        infos = z.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        ch1 = z.read("OEBPS/ch1.xhtml").decode("utf-8")
        opf = z.read("OEBPS/content.opf").decode("utf-8")
        ncx = z.read("OEBPS/toc.ncx").decode("utf-8")

    # 原文保留 + 译文克隆插后 + 区分色 class
    assert "Hello world this is a paragraph." in ch1
    assert "这是译文" in ch1
    assert "texlate-zh" in ch1
    # 克隆剥 id：源 id 恰好一份
    assert ch1.count('id="p1"') == 1
    assert "<dc:language>zh-CN</dc:language>" in opf
    # NCX navLabel → 原文 / 译文
    assert "Chapter One / " in ncx
    assert "这是译文" in ncx


def test_marker_roundtrip(tmp_path: Path) -> None:
    src = _write_epub(
        tmp_path,
        _epub(
            {"ch1.xhtml": "<p>See <code>inline code</code> here please.</p>"},
            ncx=False,
        ),
    )
    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator())
    with zipfile.ZipFile(dst) as z:
        ch1 = z.read("OEBPS/ch1.xhtml").decode("utf-8")
    # 原文 <code> 一份 + 译文里 marker 落点克隆一份
    assert ch1.count("<code>") == 2  # noqa: PLR2004 -- 原文一份+译文克隆一份
    assert "这是译文" in ch1


def test_echo_translation_not_duplicated(tmp_path: Path) -> None:
    src = _write_epub(
        tmp_path,
        _epub({"ch1.xhtml": "<p>Only paragraph stays same.</p>"}, ncx=False),
    )
    dst = tmp_path / "out.epub"
    report = translate_epub(src, dst, _EchoTranslator())
    assert report.unchanged == report.units
    assert report.translated == 0
    with zipfile.ZipFile(dst) as z:
        ch1 = z.read("OEBPS/ch1.xhtml").decode("utf-8")
    assert "texlate-zh" not in ch1
    assert ch1.count("Only paragraph stays same.") == 1


def test_drm_refused(tmp_path: Path) -> None:
    for extra, name in [
        ({"META-INF/rights.xml": "<rights/>"}, "rights.epub"),
        ({"META-INF/license.lcpl": b"{}"}, "lcp.epub"),
        ({"META-INF/encryption.xml": AES_ENCRYPTION}, "aes.epub"),
    ]:
        src = _write_epub(
            tmp_path,
            _epub({"ch1.xhtml": "<p>x</p>"}, ncx=False, extra=extra),
            name,
        )
        assert check_epub(src) == "drm"
        with pytest.raises(DrmError):
            translate_epub(src, tmp_path / f"{name}.out.epub", MockTranslator())


def test_font_obfuscation_is_not_drm(tmp_path: Path) -> None:
    src = _write_epub(
        tmp_path,
        _epub(
            {"ch1.xhtml": "<p>Body text stays readable.</p>"},
            ncx=False,
            extra={"META-INF/encryption.xml": FONT_OBFUSCATED_ENCRYPTION},
        ),
    )
    assert check_epub(src) == "ok"
    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator())
    assert dst.exists()


def test_fixed_layout_refused(tmp_path: Path) -> None:
    src = _write_epub(tmp_path, _epub({"ch1.xhtml": "<p>x</p>"}, ncx=False, fixed=True))
    with pytest.raises(FixedLayoutError):
        translate_epub(src, tmp_path / "out.epub", MockTranslator())


def test_malformed_refused(tmp_path: Path) -> None:
    src = tmp_path / "junk.epub"
    src.write_bytes(b"not a zip at all")
    assert check_epub(src) == "ok"  # 不替下游报错
    with pytest.raises(MalformedEpubError):
        translate_epub(src, tmp_path / "out.epub", MockTranslator())


def test_resume_from_state(tmp_path: Path) -> None:
    body = (
        "<p>First paragraph of the chapter.</p>"
        "<p>Second paragraph of the chapter.</p>"
        "<p>Third paragraph of the chapter.</p>"
    )
    src = _write_epub(tmp_path, _epub({"ch1.xhtml": body}, ncx=False))
    state_dir = tmp_path / "resume.state"

    # 预置断点：除最后一单元外全部已完成（job_id/源文按 iter_units 口径复算）
    book = load_epub(src)
    soups = {p: BeautifulSoup(book.members[p], "html.parser") for p in book.doc_paths}
    units = list(iter_units(book, soups))
    assert len(units) == 3  # noqa: PLR2004 -- 三段正文
    store = StateStore(state_dir, model="export", pipeline_version="export-epub-1")
    store.start(len(units))
    for u in units[:-1]:
        store.record(
            ChunkRecord(
                chunk_id=u.job_id,
                source=u.text,
                translation="预置译文",
                status="ok",
                kind="para",
            )
        )
    store.flush()

    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator(), state_dir=state_dir)
    with zipfile.ZipFile(dst) as z:
        ch1 = z.read("OEBPS/ch1.xhtml").decode("utf-8")
    assert "预置译文" in ch1  # 断点译文回放
    assert "这是译文" in ch1  # 剩余单元实跑
    assert not state_dir.exists()  # 成功即清理
