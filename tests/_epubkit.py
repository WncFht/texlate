"""export 测试最小 EPUB 构造件——``CONTAINER_XML``/``XHTML_TMPL``/``opf``/``epub_zip``/``minimal_epub``/``write_epub``。

``test_cli_export``/``test_export_epub``/``test_export_glossary``/
``test_export_epub_serialize``/``test_export_zip_guard``/``test_fuzz_cli``/
``test_server_upload`` 七处各自复刻的「mimetype STORED 首件 +
container.xml + content.opf + spine 章节」脚手架归此一处（沿用
``_fixloopkit`` 先例：只抽不写回——既有文件保持原样，新测试文件从这里
取件）：

- ``CONTAINER_XML``/``XHTML_TMPL``：canonical 容器描述与 ``{body}``
  章节模板——四文件逐字节同体。
- ``NCX_XML``：``test_export_epub`` 臂的 toc.ncx 成员载荷。
- ``opf``：package 文档生成——manifest/spine 随 ``chapters`` 序；
  ``fixed`` 注 ``rendition:layout=pre-paginated``、``ncx`` 追加
  toc.ncx manifest item、``version`` 覆盖 OPF 2.0/3.0 两形
  （zip_guard ``_wepub`` 臂用 ``"2.0"``）。
- ``epub_zip``：成员表 → zip 字节，``mimetype`` 恒首件 ZIP_STORED
  （OCF 硬约束）；``mimetype=False`` 造缺首件的畸形包。
- ``minimal_epub``：最小合法 EPUB——``chapters`` 每篇按
  ``XHTML_TMPL`` 裹体、``extra`` 追加裸成员、``ncx=True`` 时附
  ``NCX_XML`` 成员。
- ``write_epub``：``tmp_path/name`` 落盘返回路径。
"""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: canonical OCF 容器描述——``OEBPS/content.opf`` 单 rootfile。
CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

#: 章节文档壳——``{body}`` 槽填正文片段。
XHTML_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>t</title></head>
<body>{body}</body>
</html>
"""

#: EPUB2 导航件——``ncx=True`` 时随包附 ``OEBPS/toc.ncx``。
NCX_XML = """<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
    <navPoint id="np1"><navLabel><text>Chapter One</text></navLabel>
      <content src="ch1.xhtml"/></navPoint>
  </navMap>
</ncx>
"""


def opf(
    chapters: list[str],
    *,
    fixed: bool = False,
    ncx: bool = False,
    version: str = "3.0",
) -> str:
    """``OEBPS/content.opf``——manifest/spine 按 ``chapters`` 序逐项编号 ``c{i}``。

    ``fixed`` 注 ``rendition:layout=pre-paginated``（fixed-layout 拒绝臂）；
    ``ncx`` 在 manifest 尾追加 toc.ncx item（``ncx=False`` 时输出与
    无 ncx 形逐字节同体）；``version`` 写进 ``<package version=…>``
    （``"3.0"``/``"2.0"`` 两形参数化）。
    """
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
<package xmlns="http://www.idpf.org/2007/opf" version="{version}" unique-identifier="bid">
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


def epub_zip(members: dict[str, bytes | str], *, mimetype: bool = True) -> bytes:
    """成员表 → zip 字节：``mimetype`` 恒首件且 ZIP_STORED（规范要求）。

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


def minimal_epub(
    chapters: dict[str, str],
    *,
    extra: dict[str, bytes | str] | None = None,
    fixed: bool = False,
    ncx: bool = False,
    version: str = "3.0",
) -> bytes:
    """最小合法 EPUB zip：mimetype + container + OPF + spine 章节。

    ``chapters`` 篇名 → 正文片段，逐篇按 ``XHTML_TMPL`` 裹体落
    ``OEBPS/{name}``；``extra`` 追加裸成员（原名原样）；
    ``fixed``/``ncx``/``version`` 透传 ``opf``，``ncx=True`` 时附
    ``OEBPS/toc.ncx`` 成员。
    """
    members: dict[str, bytes | str] = {
        "META-INF/container.xml": CONTAINER_XML,
        "OEBPS/content.opf": opf(list(chapters), fixed=fixed, ncx=ncx, version=version),
    }
    for name, body in chapters.items():
        members[f"OEBPS/{name}"] = XHTML_TMPL.format(body=body)
    if ncx:
        members["OEBPS/toc.ncx"] = NCX_XML
    members.update(extra or {})
    return epub_zip(members)


def write_epub(tmp_path: Path, blob: bytes, name: str = "book.epub") -> Path:
    """``tmp_path/name`` 落盘 epub 字节，返回路径。"""
    src = tmp_path / name
    src.write_bytes(blob)
    return src
