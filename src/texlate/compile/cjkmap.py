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
    from pypdf._page import PageObject
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
    if not isinstance(system, dict):
        # dict.get 不解引用——间接引用的 CIDSystemInfo 先 get_object
        system = system.get_object()
    return system.get("/Registry") == "Adobe" and system.get("/Ordering") == "GB1"


def _page_resources(page: PageObject) -> list[object]:
    """页有效 ``/Resources`` 链——页自身 + 各 ``/Pages`` 祖先节点全收。

    ``/Resources`` 是 PDF 可继承属性，但空/稀疏页级表不遮蔽祖先的共享
    字体表（产出器常把 GB1 字体挂 ``/Pages`` 做全文档共享）——逐层收集
    而非取最近一层。畸形父链/环按截断处理：已收部分照常返回。
    """
    out: list[object] = []
    node: object = page
    ancestry: set[int] = set()
    while isinstance(node, dict) and id(node) not in ancestry:
        ancestry.add(id(node))
        res = node.get("/Resources")
        if res:
            out.append(res)
        node = node.get("/Parent")
        if node is not None:
            try:
                node = node.get_object()
            except (AttributeError, KeyError, IndexError, TypeError):
                break
    return out


def _iter_group_members(group: object, seen: set[int]) -> Iterator[DictionaryObject]:
    """资源子表（``/Font``/``/XObject`` 值）成员走查，id 去重记入 ``seen``。

    子表值本身可以是 IndirectObject——``dict.get`` 不解引用，须显式
    ``get_object`` 后才能 ``.values()``；畸形段/坏成员各自坍弃，不穿透。
    """
    try:
        group = group.get_object() if group else {}
    except (AttributeError, KeyError, IndexError, TypeError):
        return
    if not isinstance(group, dict):
        return
    for ref in group.values():
        try:
            obj = ref.get_object()
        except (AttributeError, KeyError, IndexError, TypeError):
            continue
        if id(obj) not in seen:
            seen.add(id(obj))
            yield obj


def _iter_pdf_fonts(writer: PdfWriter) -> Iterator[DictionaryObject]:
    """按页树 ``/Resources``（含 XObject 递归）走查字体对象，id 去重。

    资源级容错与 per-font 同粒度：畸形 ``/Resources``/``/Font``/``/XObject``
    段各自坍弃，不穿透生成器拖垮整篇注入。
    """
    seen: set[int] = set()
    pending = [res for page in writer.pages for res in _page_resources(page)]
    while pending:
        res = pending.pop()
        if not res:
            continue
        try:
            res = res.get_object()
        except (AttributeError, KeyError, IndexError, TypeError):
            continue
        if not isinstance(res, dict) or id(res) in seen:
            continue
        seen.add(id(res))
        yield from _iter_group_members(res.get("/Font", {}), seen)
        # XObject /Resources 常是 IndirectObject——原样入 pending，下轮
        # get_object 解引用；非 dict XObject 无资源可挖。
        pending.extend(
            xo.get("/Resources") if isinstance(xo, dict) else None
            for xo in _iter_group_members(res.get("/XObject", {}), seen)
        )


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
            try:
                needs = _font_needs_gb1_cmap(font)
            except (AttributeError, KeyError, IndexError, TypeError):
                continue  # 结构异常的单字体不拖垮整篇注入
            if not needs:
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
            try:
                writer.write(tmp)
            except BaseException:
                tmp.unlink(missing_ok=True)  # 半截产物不留孤儿
                raise
    finally:
        writer.close()
    if count:
        tmp.replace(pdf)
    return count
