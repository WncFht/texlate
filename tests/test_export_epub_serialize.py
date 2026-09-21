r"""``export.epub`` OPF ``dc:language`` 外科改写 + QName 净化回归。

- ``_restamp_opf`` 的 elif 补元素分支（``xmlns:dc`` 已声明、无 ``dc:language``
  → ``</metadata>`` 前插入）与负例（``xmlns:dc`` 缺席——含 ``xmlns:dcterms``
  前缀撞脸——→ OPF 逐字节不动）；
- 自闭合 ``<dc:language/>`` 原地展开为目标语言，不落 elif 再产第二条；
- ``_sanitize_dom`` 对非法 QName（``xmlns:0x``/``a:b:c``/未绑定前缀属性）
  整形后产出必须 strict-parse。
"""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

import pytest
from bs4 import BeautifulSoup
from lxml import etree

from texlate.export.epub import _sanitize_dom, translate_epub
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from pathlib import Path

CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

XHTML_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>t</title></head>
<body>{body}</body>
</html>
"""

_DC_XMLNS = ' xmlns:dc="http://purl.org/dc/elements/1.1/"'


def _opf(metadata: str, *, metadata_attrs: str = _DC_XMLNS) -> str:
    return f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid">
  <metadata{metadata_attrs}>
{metadata}
  </metadata>
  <manifest>
    <item id="c0" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c0"/>
  </spine>
</package>
"""


def _run_opf(tmp_path: Path, opf: str) -> bytes:
    """最小 EPUB（单章 + 给定 OPF）跑全链，返回出包 OPF 字节。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr(
            "OEBPS/ch1.xhtml",
            XHTML_TMPL.format(body="<p>Hello translatable paragraph.</p>"),
        )
    src = tmp_path / "book.epub"
    src.write_bytes(buf.getvalue())
    dst = tmp_path / "out.epub"
    translate_epub(src, dst, MockTranslator())
    with zipfile.ZipFile(dst) as z:
        return z.read("OEBPS/content.opf")


def test_dc_language_inserted_when_missing(tmp_path: Path) -> None:
    """``xmlns:dc`` 已声明但无 ``dc:language`` → elif 在 ``</metadata>`` 前补元素。"""
    opf = _opf(
        '    <dc:identifier id="bid">test-book</dc:identifier>\n'
        "    <dc:title>Test</dc:title>"
    )
    out = _run_opf(tmp_path, opf).decode("utf-8")
    assert "<dc:language>zh-CN</dc:language></metadata>" in out
    etree.fromstring(out.encode())  # 插入后仍合法 XML


@pytest.mark.parametrize(
    ("metadata_attrs", "metadata"),
    [
        # metadata 无 dc 系声明——``</metadata>`` 在场但 ``xmlns:dc`` 缺席
        ("", '    <meta property="x">y</meta>'),
        # 前缀撞脸：``xmlns:dcterms`` 的字符串前缀是 ``xmlns:dc``——子串判定
        # 不许把它当 dc 已声明（插 ``<dc:language>`` 而未绑定 = 非法 XML）
        (
            ' xmlns:dcterms="http://purl.org/dc/terms/"',
            "    <dcterms:modified>2020-01-01T00:00:00Z</dcterms:modified>",
        ),
    ],
    ids=["no-dc-xmlns", "dcterms-lookalike"],
)
def test_dc_language_absent_dc_prefix_unchanged(
    tmp_path: Path, metadata_attrs: str, metadata: str
) -> None:
    """``xmlns:dc`` 未绑定 → OPF 逐字节不动（裸 ``<dc:language>`` 是非法 XML）。"""
    opf = _opf(metadata, metadata_attrs=metadata_attrs)
    out = _run_opf(tmp_path, opf)
    assert out == opf.encode("utf-8")
    etree.fromstring(out)  # 原 OPF 本就合法


def test_dc_language_self_closing_expanded(tmp_path: Path) -> None:
    """``<dc:language/>`` 自闭合形 → 原地展开为目标语言，不产第二条元素。"""
    opf = _opf(
        '    <dc:identifier id="bid">test-book</dc:identifier>\n'
        "    <dc:language/>\n"
        "    <dc:title>Test</dc:title>"
    )
    out = _run_opf(tmp_path, opf).decode("utf-8")
    # 旧行为：自闭合不匹配正则 → elif 再插一条 → 两个 dc:language（一空一实）
    assert out.count("<dc:language") == 1
    assert out.count("</dc:language>") == 1
    assert "<dc:language>zh-CN</dc:language>" in out
    etree.fromstring(out.encode())


@pytest.mark.parametrize(
    "doc",
    [
        # 非法 xmlns 声明（数字起首 local）+ 其前缀属性 + 多冒号 tag/attr 名
        '<html><body><a:b:c xmlns:0x="u" 0x:y="1" a:b:c="2" xmlns:p="v" p:q="3"/></body></html>',
        # 未绑定前缀 tag/attr → 取本地名
        '<html><body><foo:bar baz:qux="1"/><p qq:z="2">x</p></body></html>',
        # xmlns local 自身带冒号——非法声明连同其前缀属性一并剥除
        '<html><body><p xmlns:a:b="u" a:c="1">x</p></body></html>',
    ],
    ids=["illegal-decl-multi-colon", "unbound-prefix", "double-colon-decl"],
)
def test_illegal_qnames_sanitized(doc: str) -> None:
    """宽容构造的非法 QName 经 ``_sanitize_dom`` 整形 → 输出 strict-parse。"""
    soup = BeautifulSoup(doc, "html.parser")
    _sanitize_dom(soup)
    etree.fromstring(str(soup).encode())


def test_bound_prefix_qnames_preserved() -> None:
    """已绑定前缀的 QName 保留 ``prefix:local`` 形态（含 xmlns 声明本身）。"""
    soup = BeautifulSoup(
        '<html><body><x:sec xmlns:x="urn:x"><x:p x:id="1"/></x:sec></body></html>',
        "html.parser",
    )
    _sanitize_dom(soup)
    out = str(soup)
    etree.fromstring(out.encode())
    assert 'xmlns:x="urn:x"' in out
    assert "x:sec" in out
    assert "x:p" in out
    assert 'x:id="1"' in out
