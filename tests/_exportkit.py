"""export 测试公共 EPUB zip 骨架——``_CONTAINER_XML``/``_NCX_XML``/``_XHTML_TMPL``
+ ``_opf``/``_epub_zip``/``_epub``/``_zip_only``/``_write_epub`` 套件。

``test_cli_export``/``test_export_epub``/``test_export_glossary``/
``test_fuzz_export``/``test_fuzz_export2``/``test_fuzz_cli`` 逐文件复刻的
最小合法 EPUB 构造件归此一处（沿用 ``_fixloopkit``/``_workerkit``/
``_tarkit`` 抽取先例）。``_opf``/``_epub`` 取 ``test_export_epub`` 超集
签名——``ncx=`` 缺省 True 产 manifest ``toc.ncx`` 项 + ``OEBPS/toc.ncx``
成员；无 NCX 的消费方（``test_cli_export`` 臂）显式 ``ncx=False``，
产出与旧无-ncx 件逐字节同体（成员序：mimetype 首件 ZIP_STORED →
container.xml → content.opf → 章节 → extra）。

异形件仍留各文件本地：``test_fuzz_export2._opf`` 是
``(items: list[tuple], spine, extra)`` 字节形签名、``test_fuzz_export``
的 ``_opf``/``_write_epub(tmp, name, members)``/``_ncx`` 是生成器件、
``test_export_glossary._epub(body)``/``_write_epub(tmp, body)`` 是单章
简形、``test_fuzz_cli._OPF``/``_XHTML`` 是单行定死体——签名/粒度不同，
不并入本件。
"""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_NCX_XML = """<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1"><navLabel><text>Chapter One</text></navLabel>
      <content src="ch1.xhtml"/></navPoint>
  </navMap>
</ncx>
"""

_XHTML_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>t</title></head>
<body>{body}</body>
</html>
"""


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


def _epub_zip(members: dict[str, bytes | str], *, mimetype: bool = True) -> bytes:
    """最小 EPUB zip 构造：``mimetype`` 恒首件且 ZIP_STORED（规范要求）。

    其余成员按 dict 序写入；``mimetype=False`` 造缺首件的畸形包。
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if mimetype:
            z.writestr(
                "mimetype",
                "application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
        for name, blob in members.items():
            z.writestr(name, blob)
    return buf.getvalue()


def _epub(
    chapters: dict[str, str],
    *,
    ncx: bool = True,
    extra: dict[str, bytes | str] | None = None,
    fixed: bool = False,
) -> bytes:
    """最小合法 EPUB zip：mimetype + container + OPF + spine 章节（可选 NCX）。"""
    members: dict[str, bytes | str] = {
        "META-INF/container.xml": _CONTAINER_XML,
        "OEBPS/content.opf": _opf(list(chapters), ncx=ncx, fixed=fixed),
    }
    for name, body in chapters.items():
        members[f"OEBPS/{name}"] = _XHTML_TMPL.format(body=body)
    if ncx:
        members["OEBPS/toc.ncx"] = _NCX_XML
    members.update(extra or {})
    return _epub_zip(members)


def _zip_only(members: dict[str, bytes | str]) -> bytes:
    """裸 zip（嗅探用例的阴性/畸形输入）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, blob in members.items():
            z.writestr(name, blob)
    return buf.getvalue()


def _write_epub(tmp_path: Path, blob: bytes, name: str = "book.epub") -> Path:
    src = tmp_path / name
    src.write_bytes(blob)
    return src
