r"""``export.epub`` 双语插译测试——手工最小 EPUB zip，不碰真书/真网关。

覆盖：spine+manifest 枚举、克隆插译 + ``texlate-zh``/语言章、marker 往返
（``<code>`` 保护行内元素）、NCX ``原文 / 译文``、mimetype-first-ZIP_STORED
出包、``dc:language`` 重写、DRM/fixed-layout/畸形拒翻、StateStore 断点续跑。
"""

from __future__ import annotations

import re
import zipfile
from typing import TYPE_CHECKING

import pytest
from _exportkit import _CONTAINER_XML, _XHTML_TMPL, _epub, _epub_zip, _opf, _write_epub
from bs4 import BeautifulSoup
from lxml import etree

from texlate.export import epub as epub_mod
from texlate.export import sniff_format
from texlate.export.common import DrmError, FixedLayoutError, MalformedEpubError
from texlate.export.epub import iter_units, load_epub, translate_epub
from texlate.export.rights import check_epub
from texlate.xlat.pipeline import MockTranslator
from texlate.xlat.state import ChunkRecord, StateStore

if TYPE_CHECKING:
    from pathlib import Path

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


def _epub_raw(xhtml: str) -> bytes:
    """整篇 xhtml 原文进包——绕过 ``_epub`` 的 ``<body>`` 模板，畸形文档专用。"""
    return _epub_zip(
        {
            "META-INF/container.xml": _CONTAINER_XML,
            "OEBPS/content.opf": _opf(["ch1.xhtml"], ncx=False),
            "OEBPS/ch1.xhtml": xhtml,
        }
    )


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


def test_dc_language_with_attributes(tmp_path: Path) -> None:
    """``<dc:language xsi:type="...">la</dc:language>``——语言码是标签名子串。

    回归：``replace(文本)`` 会先命中 ``language`` 里的 ``la`` 把元素改残
    （``dc:zh-CNnguage``，真书 Liber Esther 语系 ``la`` 实测复现）——改写必须
    走 match span 而非字符串替换。
    """
    opf = _opf(["ch1.xhtml"], ncx=False).replace(
        "<dc:language>en</dc:language>",
        '<dc:language xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:type="dcterms:RFC4646">la</dc:language>',
    )
    src = _write_epub(
        tmp_path,
        _epub_zip(
            {
                "META-INF/container.xml": _CONTAINER_XML,
                "OEBPS/content.opf": opf,
                "OEBPS/ch1.xhtml": _XHTML_TMPL.format(body="<p>Textus unus.</p>"),
            }
        ),
    )
    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator())
    with zipfile.ZipFile(dst) as z:
        out_opf = z.read("OEBPS/content.opf")
    root = etree.fromstring(out_opf)  # 必须仍是合法 XML
    langs = [
        el.text
        for el in root.iter()
        if isinstance(el.tag, str) and el.tag.rsplit("}", 1)[-1] == "language"
    ]
    assert langs[0] == "zh-CN"
    assert b"zh-CNnguage" not in out_opf


def test_literal_marker_no_collision(tmp_path: Path) -> None:
    """源文逐字印着 ``[[IMG_1]]`` 时，``<img>`` 的占位符必须换号。

    调和侧：``[[IMG_1]]`` 是书自有字面文本（不许洗不许动），``[[IMG_2]]`` 才是
    发出的 marker——写回只把 ``[[IMG_2]]`` 换成 ``<img>`` 克隆。
    """
    src = _write_epub(
        tmp_path,
        _epub(
            {"ch1.xhtml": ('<p>Read [[IMG_1]] then <img src="x.png"/> done here.</p>')},
            ncx=False,
            extra={"OEBPS/x.png": b"\x89PNG"},
        ),
    )
    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator())
    with zipfile.ZipFile(dst) as z:
        soup = BeautifulSoup(z.read("OEBPS/ch1.xhtml"), "html.parser")
    zh = soup.select_one(".texlate-zh")
    assert zh is not None
    assert "[[IMG_1]]" in zh.get_text()  # 字面 token 原样保留
    assert "[[IMG_2]]" not in zh.get_text()  # marker 不落字面
    assert zh.find("img") is not None  # marker 落点 = <img> 克隆
    assert len(soup.find_all("img")) == 2  # noqa: PLR2004 -- 原文 + 译文克隆各一


def test_img_marker_restored(tmp_path: Path) -> None:
    """段中 ``<img>`` 变 ``[[IMG_n]]`` marker，译文落点克隆回图片元素。"""
    src = _write_epub(
        tmp_path,
        _epub(
            {"ch1.xhtml": '<p>See <img src="pic.png"/> inside this line.</p>'},
            ncx=False,
            extra={"OEBPS/pic.png": b"\x89PNG"},
        ),
    )
    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator())
    with zipfile.ZipFile(dst) as z:
        soup = BeautifulSoup(z.read("OEBPS/ch1.xhtml"), "html.parser")
    imgs = soup.find_all("img")
    assert len(imgs) == 2  # noqa: PLR2004 -- 源图 + 译文图
    zh = soup.select_one(".texlate-zh")
    assert zh.find("img") is not None
    assert "[[" not in zh.get_text()


def test_figcaption_inline_append(tmp_path: Path) -> None:
    """``<figcaption>`` 是受限容器——译文 ``<br/><span>`` 追加进内部，不产兄弟。"""
    src = _write_epub(
        tmp_path,
        _epub(
            {
                "ch1.xhtml": (
                    "<figure><img src='i.png'/>"
                    "<figcaption>A caption for the figure.</figcaption></figure>"
                )
            },
            ncx=False,
            extra={"OEBPS/i.png": b"\x89PNG"},
        ),
    )
    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator())
    with zipfile.ZipFile(dst) as z:
        soup = BeautifulSoup(z.read("OEBPS/ch1.xhtml"), "html.parser")
    assert len(soup.find_all("figcaption")) == 1
    cap = soup.find("figcaption")
    zh = cap.find("span", class_="texlate-zh")
    assert zh is not None
    assert "这是译文" in zh.get_text()
    assert zh.parent is cap  # 译文在容器内部


def test_entities_and_stray_ampersand(tmp_path: Path) -> None:
    """命名实体归一化送模型；裸 ``&``/伪实体不炸管线、输出仍良构。"""
    src = _write_epub(
        tmp_path,
        _epub(
            {
                "ch1.xhtml": (
                    "<p>Caf&eacute; au&nbsp;lait &mdash; rich taste.</p>"
                    "<p>Tom &amp; Jerry &bogus; stay literal.</p>"
                )
            },
            ncx=False,
        ),
    )
    dst = tmp_path / "out.epub"
    report = translate_epub(src, dst, MockTranslator())
    assert report.translated == 2  # noqa: PLR2004 -- 两段都插译
    with zipfile.ZipFile(dst) as z:
        raw = z.read("OEBPS/ch1.xhtml")
        soup = BeautifulSoup(raw, "html.parser")
    assert len(soup.select(".texlate-zh")) == 2  # noqa: PLR2004 -- 两段各一
    assert "Caf" in soup.get_text()  # 原文仍在


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
    assert ch1.count("<code>") == 2  # noqa: PLR2004 -- 原文一份 + 译文克隆一份
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
    store = StateStore(
        state_dir, model="export", pipeline_version="export-epub-2026-10"
    )
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


@pytest.mark.parametrize(
    ("xhtml", "warns"),
    [
        ("Bare prose at the document root, no markup at all.", False),
        (
            '<?xml version="1.0"?><p>A wrapped paragraph.</p>Stray text at root.',
            False,
        ),
        (
            '<?xml version="1.0"?><html><p>A wrapped paragraph.</p>Loose text under html.</html>',
            True,
        ),
        ('<?xml version="1.0"?><html>Only text directly under html.</html>', True),
    ],
    ids=["bare-text", "stray-root-text", "html-stray-text", "html-only-text"],
)
def test_no_body_doc_anchored_not_clone(
    tmp_path: Path, xhtml: str, *, warns: bool
) -> None:
    """无 ``<body>`` 的畸形 xhtml：owner 退到 ``<html>``/文档根，锚定插译不抛。

    回归：克隆路径对 BeautifulSoup 根 ``insert_after`` 抛 ``NotImplementedError``
    （bs4 4.15 显式拒实现），对 ``<html>`` 则造出第二个顶层元素——document 级
    owner 一律改走锚定并在 ``report.warnings`` 留痕。裸文本/多顶层成员的文档由
    ``_sanitize_dom`` 套 ``<html><body>`` 补出 body——走正常 owner 路无 warning。
    """
    src = _write_epub(tmp_path, _epub_raw(xhtml))
    dst = tmp_path / "out.epub"
    report = translate_epub(src, dst, MockTranslator())
    assert report.fault == 0
    assert report.translated == report.units
    assert any("no <body>" in w for w in report.warnings) is warns
    with zipfile.ZipFile(dst) as z:
        soup = BeautifulSoup(z.read("OEBPS/ch1.xhtml"), "html.parser")
    assert soup.select_one(".texlate-zh") is not None
    assert len(soup.find_all("html")) <= 1  # 克隆路径不许造出第二个顶层 <html>


# ---------------------------------------------------------------- 审计增量
# percent-href / 成员 CRC / 控制字符 / decl 改写 / mimetype 兜底 / nav landmark


def _opf_href(href: str) -> str:
    return f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bid">test-book</dc:identifier>
    <dc:title>Test</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="c0" href="{href}" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c0"/>
  </spine>
</package>
"""


def test_percent_encoded_href_resolves(tmp_path: Path) -> None:
    """manifest ``href="ch%201.xhtml"`` 指成员 ``ch 1.xhtml``——URI 必须 decode。

    回归：``posixpath.join`` 原样拼 ``%20`` 找不到成员 → 整本被
    ``manifest 里没有可翻的 xhtml 文档`` 拒掉。真书（InDesign/转换器产物）
    空格/非 ASCII 文件名普遍 percent-encoded。
    """
    src = _write_epub(
        tmp_path,
        _epub_zip(
            {
                "META-INF/container.xml": _CONTAINER_XML,
                "OEBPS/content.opf": _opf_href("ch%201.xhtml"),
                "OEBPS/ch 1.xhtml": _XHTML_TMPL.format(body="<p>Spaced name doc.</p>"),
            }
        ),
    )
    dst = tmp_path / "out.epub"
    report = translate_epub(src, dst, MockTranslator())
    assert report.translated == 1
    with zipfile.ZipFile(dst) as z:
        ch1 = z.read("OEBPS/ch 1.xhtml").decode("utf-8")
    assert "这是译文" in ch1


def test_corrupt_member_raises_malformed(tmp_path: Path) -> None:
    """成员级坏 CRC → ``MalformedEpubError``（ExportError 族），不是裸 BadZipFile。

    回归：``zf.read(info)`` 在校验 try 外——坏成员直接穿透 CLI 的
    ``except ExportError`` 变 traceback。
    """
    blob = bytearray(_epub({"ch1.xhtml": "<p>Hello world paragraph here.</p>"}))
    blob[blob.find(b"Hello")] = ord("X")  # 数据字节翻转 → CRC 必失配
    src = _write_epub(tmp_path, bytes(blob))
    with pytest.raises(MalformedEpubError, match="CRC"):
        translate_epub(src, tmp_path / "out.epub", MockTranslator())


class _CtrlTranslator:
    """译文带 XML 非法控制字符——插入侧必须剥除。"""

    async def translate(self, **_kw: object) -> str:
        return "译\x0b文\x01控\x00制"


def test_control_chars_in_translation_stripped(tmp_path: Path) -> None:
    """模型回 \\x0b/\\x01/\\x00 → \\x0b 归一 \\n、\\x01/\\x00 剥除——输出 XHTML 仍是合法 XML。"""
    src = _write_epub(
        tmp_path,
        _epub({"ch1.xhtml": "<p>Clean source paragraph.</p>"}, ncx=False),
    )
    dst = tmp_path / "out.epub"
    report = translate_epub(src, dst, _CtrlTranslator())
    assert report.translated == 1
    with zipfile.ZipFile(dst) as z:
        raw = z.read("OEBPS/ch1.xhtml")
    etree.fromstring(raw)  # 不抛即合法
    assert b"\x0b" not in raw
    assert b"\x00" not in raw
    assert "译\n文控制" in raw.decode("utf-8")


def test_control_chars_in_source_cleaned_on_write(tmp_path: Path) -> None:
    """源文带控制字符（输入已非法）→ 出包序列化剥除——产出物比输入更合法。"""
    src = _write_epub(
        tmp_path,
        _epub_raw(
            '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
            "<body><p>Text with \x0b control inside.</p></body></html>"
        ),
    )
    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator())
    with zipfile.ZipFile(dst) as z:
        raw = z.read("OEBPS/ch1.xhtml")
    assert b"\x0b" not in raw
    etree.fromstring(raw)


def test_non_utf8_decl_restamped(tmp_path: Path) -> None:
    """源声明 ISO-8859-1、内容是 utf-8 → 输出 decl 必须改写 utf-8。

    回归：bs4 只改写 ``<meta charset>``，``<?xml encoding?>`` PI 原样透传——
    声明说谎让严格 XML 阅读器按 latin-1 解 utf-8 字节（mojibake/拒绝）。
    """
    latin = _XHTML_TMPL.format(body="<p>Caf\xe9 latin text here.</p>").replace(
        'encoding="utf-8"', 'encoding="ISO-8859-1"'
    )
    src = _write_epub(
        tmp_path,
        _epub_zip(
            {
                "META-INF/container.xml": _CONTAINER_XML,
                "OEBPS/content.opf": _opf(["ch1.xhtml"], ncx=False),
                "OEBPS/ch1.xhtml": latin.encode("latin-1"),
            }
        ),
    )
    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator())
    with zipfile.ZipFile(dst) as z:
        raw = z.read("OEBPS/ch1.xhtml")
    assert raw.startswith(b'<?xml version="1.0" encoding="utf-8"?>')
    etree.fromstring(raw)  # 按声明解 utf-8 必须成立
    assert "Café" in raw.decode("utf-8")


def test_missing_mimetype_gets_canonical(tmp_path: Path) -> None:
    """输入缺 mimetype（畸形但可翻）→ 产出补规范首件，出包是合法 EPUB。"""
    src = _write_epub(
        tmp_path,
        _epub_zip(
            {
                "META-INF/container.xml": _CONTAINER_XML,
                "OEBPS/content.opf": _opf(["ch1.xhtml"], ncx=False),
                "OEBPS/ch1.xhtml": _XHTML_TMPL.format(body="<p>No mimetype.</p>"),
            },
            mimetype=False,
        ),
    )
    dst = tmp_path / "out.epub"
    report = translate_epub(src, dst, MockTranslator())
    assert report.translated == 1
    with zipfile.ZipFile(dst) as z:
        infos = z.infolist()
    assert infos[0].filename == "mimetype"
    assert infos[0].compress_type == zipfile.ZIP_STORED


def test_nav_stray_text_no_dup_landmark(tmp_path: Path) -> None:
    """``<nav epub:type="doc-toc">`` 直挂文本 → owner=nav——克隆路径会把
    epub:type 复制成第二个 landmark。改走受限容器内部追加。"""
    nav_body = (
        '<nav epub:type="doc-toc" xmlns:epub="http://www.idpf.org/2007/ops">'
        "Stray nav heading text<ol><li><a href='c1.xhtml'>Ch One</a></li></ol></nav>"
    )
    src = _write_epub(
        tmp_path,
        _epub_zip(
            {
                "META-INF/container.xml": _CONTAINER_XML,
                "OEBPS/content.opf": _opf(["c1.xhtml"], ncx=False).replace(
                    "</manifest>",
                    '    <item id="nav" href="nav.xhtml"'
                    ' media-type="application/xhtml+xml" properties="nav"/>\n'
                    "  </manifest>",
                ),
                "OEBPS/nav.xhtml": _XHTML_TMPL.format(body=nav_body),
                "OEBPS/c1.xhtml": _XHTML_TMPL.format(
                    body="<p>Chapter content paragraph.</p>"
                ),
            }
        ),
    )
    dst = tmp_path / "out.epub"
    report = translate_epub(src, dst, MockTranslator())
    assert report.fault == 0
    with zipfile.ZipFile(dst) as z:
        soup = BeautifulSoup(z.read("OEBPS/nav.xhtml"), "html.parser")
    navs = soup.find_all("nav")
    assert len(navs) == 1  # 不许出现第二个 doc-toc landmark
    assert navs[0].find("span", class_="texlate-zh") is not None


def test_hostile_target_lang_no_opf_injection(tmp_path: Path) -> None:
    """``target_lang`` 带 XML 元字符 → 不写 OPF（正则替换面无转义层）。"""
    src = _write_epub(
        tmp_path, _epub({"ch1.xhtml": "<p>Some text paragraph.</p>"}, ncx=False)
    )
    dst = tmp_path / "out.epub"
    report = translate_epub(src, dst, MockTranslator(), target_lang='zh<x="1">')
    assert report.translated == 1
    with zipfile.ZipFile(dst) as z:
        opf = z.read("OEBPS/content.opf")
    etree.fromstring(opf)  # OPF 仍合法——注入没发生
    assert b"zh<" not in opf


def test_sniff_unsupported_compression_method(tmp_path: Path) -> None:
    """未知压缩方法的 zip 条目 → sniff 返回 None 而非裸 NotImplementedError。"""
    blob = bytearray(_epub_zip({"META-INF/container.xml": "<x/>"}))
    blob[8] = 99  # local header compress_type
    blob[9] = 0
    cd = blob.find(b"PK\x01\x02")
    while cd != -1:
        nlen = int.from_bytes(blob[cd + 28 : cd + 30], "little")
        if bytes(blob[cd + 46 : cd + 46 + nlen]) == b"mimetype":
            blob[cd + 10] = 99
            blob[cd + 11] = 0
        cd = blob.find(b"PK\x01\x02", cd + 1)
    src = tmp_path / "weird.epub"
    src.write_bytes(bytes(blob))
    assert sniff_format(src) is None


# ------------------------------------------------- _sanitize_dom raw-text 转义


@pytest.mark.parametrize("tag", ["script", "style"])
def test_sanitize_dom_raw_text_entity_idempotent(tag: str) -> None:
    """``&amp;`` 过 ``_sanitize_dom`` 不再翻倍；二次净化输出逐字节不变。"""
    src = f'<html><body><{tag}>a = "&amp;" && b < c;</{tag}></body></html>'
    soup = BeautifulSoup(src, "html.parser")
    epub_mod._sanitize_dom(soup)  # noqa: SLF001 -- 白盒钉净化契约
    out = str(soup.find(tag))
    assert 'a = "&amp;"' in out  # 源实体不翻倍
    assert "&amp;amp;" not in out
    assert "&amp;&amp;" in out  # 裸 & 仍转义
    assert "&lt; c;" in out  # < 防提前终结
    # texlate 产出重进管线：逐字节幂等（不再累积 amp;）
    soup2 = BeautifulSoup(out, "html.parser")
    epub_mod._sanitize_dom(soup2)  # noqa: SLF001
    assert str(soup2.find(tag)) == out


def test_sanitize_dom_script_xml_semantics() -> None:
    """合法 XHTML ``&amp;`` 净化后 XML 解析仍得 ``&``——语义不变。"""
    soup = BeautifulSoup(
        '<html><body><script>a = "&amp;";</script></body></html>',
        "html.parser",
    )
    epub_mod._sanitize_dom(soup)  # noqa: SLF001
    root = etree.fromstring(str(soup).encode())
    script = root.find(".//script")
    assert script is not None
    assert script.text == 'a = "&";'


def test_sanitize_dom_raw_text_bogus_entity_literal() -> None:
    """非预定义实体转字面量：``&bogus;``/``&nbsp;`` 输出仍是良构 XML。"""
    soup = BeautifulSoup(
        "<html><body><script>a = '&bogus;' + '&nbsp;';</script></body></html>",
        "html.parser",
    )
    epub_mod._sanitize_dom(soup)  # noqa: SLF001
    root = etree.fromstring(str(soup).encode())
    text = root.find(".//script").text
    assert "&bogus;" in text
    assert "&nbsp;" in text
