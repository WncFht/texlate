"""GB1→UCS2 ToUnicode CMap 注入（docs/08 §3.3 注入层步骤）。

xelatex/tectonic 出的 zh.pdf 里 ctex+fandol 是真 CID-keyed GB1 字体且不落
ToUnicode——poppler 靠嵌入字体自身 cmap 能抽，pypdf/极简阅读器直抽即乱码
（复制/检索失效）。``embed_cjk_mappings`` 给命中条件的 Type0 字体挂共享
``Adobe-GB1-UCS2`` cmap 流。

server worker 与 e2e/cli 管线共用本模块；CMap 资源随包分发在
``compile/cmaps/``。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject

#: ``embed_cjk_mappings`` 注入的 GB1→UCS2 CMap（Adobe 官方资源，BSD 许可
#: ——与 poppler ``cMap/Adobe-GB1/Adobe-GB1-UCS2`` 逐字节一致，随包分发）
_GB1_UCS2_CMAP = Path(__file__).resolve().parent / "cmaps" / "Adobe-GB1-UCS2"


def _font_needs_gb1_cmap(font: DictionaryObject) -> bool:
    """Type0 字体命中注入条件与否。

    无 ToUnicode ∧ Identity-H/V 编码 ∧ CIDSystemInfo 为 Adobe/GB1。
    Ordering 非 GB1 的 Identity-keyed 字体挂 GB1 cmap 反而写错映射——跳过。
    """
    if (
        font.get("/ToUnicode")
        or not font.get("/DescendantFonts")
        or font.get("/Encoding") not in ("/Identity-H", "/Identity-V")
    ):
        return False
    child = font["/DescendantFonts"][0].get_object()
    system = child.get("/CIDSystemInfo", {})
    return system.get("/Registry") == "Adobe" and system.get("/Ordering") == "GB1"


def _iter_pdf_fonts(writer: PdfWriter) -> Iterator[DictionaryObject]:
    """按页树 ``/Resources``（含 XObject 递归）走查字体对象，id 去重。"""
    seen: set[int] = set()
    pending = [page.get("/Resources") for page in writer.pages]
    while pending:
        res = pending.pop()
        if not res:
            continue
        res = res.get_object()
        # /Font 与 /XObject 的值本身可以是 IndirectObject——
        # dict.get 不解引用，IndirectObject.values() 即 AttributeError，
        # 上抛被调用方 best-effort 壳吞成一行 log → ToUnicode 静默全丢
        fonts = res.get("/Font", {})
        fonts = fonts.get_object() if fonts else {}
        if isinstance(fonts, dict):
            for ref in fonts.values():
                font = ref.get_object()
                if id(font) not in seen:
                    seen.add(id(font))
                    yield font
        xobjs = res.get("/XObject", {})
        xobjs = xobjs.get_object() if xobjs else {}
        if isinstance(xobjs, dict):
            for ref in xobjs.values():
                obj = ref.get_object()
                if id(obj) not in seen:
                    seen.add(id(obj))
                    pending.append(obj.get("/Resources"))


def embed_cjk_mappings(pdf: Path) -> int:
    """给 ``Identity-H``/Adobe-GB1 无 ToUnicode 的 CID 字体注 ``Adobe-GB1-UCS2`` cmap（docs/08 §3.3）。

    xelatex/tectonic 出的 zh.pdf 里 ctex+fandol 是真 CID-keyed GB1 字体
    且不落 ToUnicode——poppler 靠嵌入字体自身 cmap 能抽，pypdf/极简
    阅读器直抽即乱码（复制/检索失效）。按页树 ``/Resources``（含
    XObject 递归）走查 Type0 字体，命中条件全齐（无 ToUnicode ∧
    Identity-H/V 编码 ∧ CIDSystemInfo 为 Adobe/GB1）才挂共享 cmap
    流——Ordering 非 GB1 的 Identity-keyed 字体注它反而写错映射，
    不碰。改写经临时文件原子替换。返回注入字体数。
    """
    from pypdf import PdfWriter  # noqa: PLC0415 -- 重依赖惰性加载
    from pypdf.generic import (  # noqa: PLC0415
        DecodedStreamObject,
        NameObject,
    )

    writer = PdfWriter(clone_from=pdf)
    count = 0
    cmap_ref = None

    try:
        for font in _iter_pdf_fonts(writer):
            if not _font_needs_gb1_cmap(font):
                continue
            if cmap_ref is None:
                stream = DecodedStreamObject()
                stream.set_data(_GB1_UCS2_CMAP.read_bytes())
                cmap_ref = writer._add_object(  # noqa: SLF001 -- pypdf 无公开 add-raw-stream API
                    stream.flate_encode()
                )
            font[NameObject("/ToUnicode")] = cmap_ref
            count += 1
        if count:
            tmp = pdf.with_suffix(".mapped.pdf")
            writer.write(tmp)
    finally:
        writer.close()
    if count:
        tmp.replace(pdf)
    return count
