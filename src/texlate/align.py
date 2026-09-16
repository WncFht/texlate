"""dual.json ``alignment`` 段产出——en/zh PDF named-dest 锚点对齐（web-layer §5.4）。

阅读器滚动同步的锚点映射（texglot 方案）：双 PDF 各抽 hyperref named
destinations（``section.N``/``figure.N``/``cite.*`` 等），按锚点名配对后
取**最大权单调子序列**——乱序锚会让前端二分插值错向，宁丢勿乱。
页内 ``fraction`` 一律自顶向下 0..1；PDF ``/Top`` 是底向上坐标，这里翻转。
无公共锚时退化 ``kind="pages"``（前端同页码映射）。

``regions`` 处理图浮动跨界漂移：named dest 只是点锚，块界靠扫页面
content stream 的 XObject 图形（``Do`` 算子落点）——同一 artwork 在双侧
以 sha256 graphic signature 匹配（drawing 命令流/图像原始字节，不解像素），
``figure.*``/``subfigure.*`` 锚点 caption 位置归属图形（边缘 0.065 容差），
唯一匹配才产出区间。浮动出序被单调链丢掉的 figure 在这里仍能拿到区间，
前端 regions 优先于 pairs 插值（alignment.ts）。

pairs/heights 移植自 ``bench/py/alignbench.py``（B7 同源逻辑，那边是评测
verdict，这边是产出侧 payload）；regions 移植自 texglot
``app/figure_alignment.py``。
"""

from __future__ import annotations

import hashlib
import logging
import re
from io import BytesIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from pypdf import PdfReader
    from pypdf._page import PageObject
    from pypdf.generic import DictionaryObject

__all__ = ["build_alignment", "extract_landmarks"]

log = logging.getLogger(__name__)

#: hyperref 自动页锚 ``page.N``——只是页码，对锚点同步无信息量，单列不计。
_PAGE_ANCHOR_RX = re.compile(r"^page\.\d+$")

#: 类别权重（docs/10 §B7）：section 12 / 图表 10 / equation 4 / cite 2，
#: 与评测侧同表——链越"像目录序"权越高。
_WEIGHT = {
    "section": 12,
    "figtable": 10,
    "equation": 4,
    "cite": 2,
    "footnote": 1,
    "other": 1,
}


def _category(name: str) -> str:
    n = name.lower()
    if n.startswith(
        ("section", "subsection", "subsubsection", "chapter", "part", "paragraph")
    ):
        return "section"
    if n.startswith(("figure", "fig", "table", "tab")):
        return "figtable"
    if n.startswith(("equation", "eq")):
        return "equation"
    if n.startswith("cite"):
        return "cite"
    if n.startswith(("footnote", "hfootnote")):
        return "footnote"
    return "other"


def _dest_page(r: object, dest: object) -> int | None:
    """Dest → 0-based 页号；坏 dest 当缺锚（None），不让整篇作废。"""
    try:
        return r.get_destination_page_number(dest)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 -- pypdf 内部异常类型发散
        log.debug("named dest 页号解析失败，按缺锚丢弃: %s", e)
        return None


def extract_landmarks(path: Path) -> dict[str, Any]:
    """抽一份 PDF 的锚点视图（``_reader_landmarks`` 的路径入口）。"""
    from pypdf import PdfReader  # noqa: PLC0415 -- 重依赖惰性加载

    return _reader_landmarks(PdfReader(str(path)))


def _reader_landmarks(r: PdfReader) -> dict[str, Any]:
    """从已打开的 reader 抽锚点视图。

    返回 ``{"dests": {name: {"page","yfrac","fit"}}, "heights": [...],
    "npages": int}``；``yfrac`` 是**底向上** 0..1（PDF 原生坐标），heights
    归一化到首页高（首页=1.0）。page.N 锚不入 dests。
    """
    raw_heights = [float(p.mediabox.height) or 792.0 for p in r.pages]
    h0 = raw_heights[0] if raw_heights else 1.0
    heights = [h / h0 for h in raw_heights]
    dests: dict[str, dict[str, Any]] = {}
    for name, dest in r.named_destinations.items():
        if _PAGE_ANCHOR_RX.match(name):
            continue
        page = _dest_page(r, dest)
        if page is None or page < 0 or page >= len(raw_heights):
            continue
        top = dest.get("/Top")
        yfrac = float(top) / raw_heights[page] if top is not None else None
        dests[name] = {
            "page": page + 1,  # 对外 1-based（web Pos.page 语义）
            "yfrac": yfrac,
            "fit": str(dest.get("/Type", "?")),
        }
    return {"dests": dests, "heights": heights, "npages": len(raw_heights)}


def _order_key(d: dict[str, Any]) -> tuple[int, float]:
    """阅读序 key：页号 + 页内自顶向下（底向上 yfrac 越大越靠前）。"""
    return (d["page"], -(d["yfrac"] if d["yfrac"] is not None else 0.0))


def _monotonic_chain(commons: list[tuple[str, dict, dict]]) -> list[str]:
    """按 original 序排序，取 translated 侧 key 非降的最大权子序列（O(n²) DP）。"""
    items = sorted(commons, key=lambda t: _order_key(t[1]))
    bkeys = [_order_key(it[2]) for it in items]
    wts = [_WEIGHT[_category(it[0])] for it in items]
    n = len(items)
    dp = wts[:]
    par = [-1] * n
    for i in range(n):
        for j in range(i):
            if bkeys[j] <= bkeys[i] and dp[j] + wts[i] > dp[i]:
                dp[i] = dp[j] + wts[i]
                par[i] = j
    if n == 0:
        return []
    i = max(range(n), key=lambda k: dp[k])
    chain: list[str] = []
    while i >= 0:
        chain.append(items[i][0])
        i = par[i]
    chain.reverse()
    return chain


def _pos(d: dict[str, Any]) -> dict[str, Any]:
    """Dest 视图 → §5.4 Pos：fraction 翻转为自顶向下 0..1。"""
    y = d["yfrac"]
    return {"page": d["page"], "fraction": round(1.0 - y, 5) if y is not None else 0.0}


# ------------------------------------------------------------------ regions
# texglot figure_alignment 移植：named dest 是点锚，figure 浮动块的真实纵向
# 跨度要扫页面 content stream 的 XObject 落点（q/cm/Do/Q 矩阵追踪），同一
# artwork 双侧用 graphic signature 配对——不解像素，Form 比对 drawing 命令
# 流、Image 比对元数据+原始存储字节。

#: region 只挂在 figure 锚上（texglot 同口径）——同名锚归属避免 logo/重复图互咬。
_REGION_PREFIX = ("figure.", "subfigure.")

#: caption 锚点到图形上下缘的最大距离（页高占比），超了说明这锚不是这块图。
_CAPTION_TOLERANCE = 0.065

#: 区间下缘外扩——caption 文本行在图形下方占一点页高。
_CAPTION_PAD = 0.025

#: 过小图形不算 figure 主体（图标/装饰线），宽/高页占比门槛。
_MIN_ART_W = 0.10
_MIN_ART_H = 0.04


def _multiply(first: tuple[float, ...], second: tuple[float, ...]) -> tuple[float, ...]:
    """两个 PDF 仿射矩阵 (a,b,c,d,e,f) 相乘：first × second。"""
    a, b, c, d, e, f = first
    aa, bb, cc, dd, ee, ff = second
    return (
        a * aa + b * cc,
        a * bb + b * dd,
        c * aa + d * cc,
        c * bb + d * dd,
        e * aa + f * cc + ee,
        e * bb + f * dd + ff,
    )


def _direct_metadata(value: Any) -> Any:  # noqa: ANN401 -- pypdf 对象图递归天然 Any
    """元数据字典规范化：剥掉 indirect 引用——对象号只在单 PDF 内有意义，跨文档签名必须解引用后比对。"""
    from pypdf.generic import (  # noqa: PLC0415 -- 重依赖惰性加载
        ArrayObject,
        DictionaryObject,
        IndirectObject,
        StreamObject,
    )

    if isinstance(value, (IndirectObject, StreamObject)):
        raise NotImplementedError
    if isinstance(value, DictionaryObject):
        return DictionaryObject(
            {key: _direct_metadata(item) for key, item in sorted(value.items())}
        )
    if isinstance(value, ArrayObject):
        return ArrayObject(_direct_metadata(item) for item in value)
    return value


def _graphic_signature(obj: DictionaryObject) -> str:
    """Artwork 跨文档等价签名：不解像素。

    /Form 含 drawing 命令流，比解码后字节；/Image 比元数据（去 /Length）
    + 原始存储字节（``StreamObject.get_data`` 基类方法绕过解码，大图不炸
    内存）。元数据里带 indirect 值的图无法跨文档签名（texglot 原语义）。
    """
    from pypdf.generic import (  # noqa: PLC0415 -- 重依赖惰性加载
        DictionaryObject,
        StreamObject,
    )

    if obj.get("/Subtype") == "/Form":
        return hashlib.sha256(obj.get_data()).hexdigest()
    metadata = DictionaryObject(
        {
            key: _direct_metadata(value)
            for key, value in sorted(obj.items())
            if key != "/Length"
        }
    )
    stream = BytesIO()
    metadata.write_to_stream(stream)
    signature = hashlib.sha256(stream.getbuffer())
    signature.update(StreamObject.get_data(obj))
    return signature.hexdigest()


def _graphic_regions(  # noqa: C901, PLR0912 -- content-stream 算子分派即分支表
    page: PageObject,
) -> list[dict[str, Any]]:
    """扫一页 content stream，产出每个大图形的 ``{"signature","start","end"}``。

    ``start``/``end`` 是该图形在该页的自顶向下 0..1 纵向跨度（cropbox 基准，
    处理 /Rotate）。追踪 q/Q 栈与 cm 级联得 CTM，Do 算子的 XObject 按
    BBox×Matrix 求落点矩形；过小的图形（图标、装饰线）不计。
    """
    from pypdf.errors import PyPdfError  # noqa: PLC0415 -- 重依赖惰性加载
    from pypdf.generic import DictionaryObject  # noqa: PLC0415

    res = (page.get("/Resources") or DictionaryObject()).get_object()
    resources = (res.get("/XObject") or DictionaryObject()).get_object()
    if not resources:
        return []
    stream = page.get_contents()
    if stream is None:
        return []
    box = page.cropbox
    width, height = float(box.width), float(box.height)
    rotation = int(page.get("/Rotate", 0)) % 360
    matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack: list[tuple[float, ...]] = []
    result: list[dict[str, Any]] = []
    for args, op in stream.operations:
        if op == b"q":
            stack.append(matrix)
        elif op == b"Q":
            matrix = stack.pop() if stack else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        elif op == b"cm" and len(args) == 6:  # noqa: PLR2004 -- cm 算子六参
            matrix = _multiply(tuple(float(n) for n in args), matrix)
        elif op == b"Do" and args and args[0] in resources:
            obj = resources[args[0]].get_object()
            if obj.get("/Subtype") not in ("/Form", "/Image"):
                continue
            bounds = obj.get("/BBox", (0, 0, 1, 1))
            transform = _multiply(
                tuple(float(n) for n in obj.get("/Matrix", (1, 0, 0, 1, 0, 0))),
                matrix,
            )
            a, b, c, d, e, f = transform
            points = [
                (a * x + c * y + e, b * x + d * y + f)
                for x, y in (
                    (float(bounds[0]), float(bounds[1])),
                    (float(bounds[0]), float(bounds[3])),
                    (float(bounds[2]), float(bounds[1])),
                    (float(bounds[2]), float(bounds[3])),
                )
            ]
            xs, ys = zip(*points, strict=True)
            if (max(xs) - min(xs)) / width < _MIN_ART_W or (
                max(ys) - min(ys)
            ) / height < _MIN_ART_H:
                continue
            match rotation:
                case 90:
                    values = [(x - float(box.left)) / width for x in xs]
                case 180:
                    values = [(y - float(box.bottom)) / height for y in ys]
                case 270:
                    values = [1 - (x - float(box.left)) / width for x in xs]
                case _:
                    values = [(float(box.top) - y) / height for y in ys]
            top, bottom = max(0.0, min(values)), min(1.0, max(values))
            if bottom <= top:
                continue
            try:
                signature = _graphic_signature(obj)
            except (PyPdfError, NotImplementedError):
                # 带 indirect 元数据/解码超限的 artwork 签不了名——只丢这块图。
                continue
            result.append({"signature": signature, "start": top, "end": bottom})
    return result


def _match_figure_regions(
    readers: dict[str, PdfReader], commons: list[tuple[str, dict, dict]]
) -> list[dict[str, Any]]:
    """公共 figure 锚点 → ``regions[]``（§5.4 ``{page,start,end}`` 双侧区间）。

    候选取**全部公共锚**而非单调链成员——浮动出序被链丢掉的 figure 恰是
    regions 要救的场景。归属判定：锚点 caption fraction 距图形上下缘
    0.065 内；双侧候选图形按 signature 配对，**唯一匹配才产出**（重复
    artwork 歧义交给 pairs 普通插值，texglot 原语义）。
    """
    cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
    regions: list[dict[str, Any]] = []
    for name, da, db in commons:
        if not name.startswith(_REGION_PREFIX):
            continue
        if da["yfrac"] is None or db["yfrac"] is None:
            continue
        sides: dict[str, list[dict[str, Any]]] = {}
        for side, d in (("original", da), ("translated", db)):
            key = (side, d["page"])
            if key not in cache:
                try:
                    cache[key] = _graphic_regions(readers[side].pages[d["page"] - 1])
                except Exception as e:  # noqa: BLE001 -- 单页 content stream 解析崩只丢该页 regions
                    log.debug("graphic regions 扫描失败 %s p%s: %s", side, d["page"], e)
                    cache[key] = []
            caption = min(1.0, max(0.0, 1.0 - d["yfrac"]))
            sides[side] = [
                region
                for region in cache[key]
                if min(abs(region["start"] - caption), abs(region["end"] - caption))
                < _CAPTION_TOLERANCE
            ]
        matches = [
            (left, right)
            for left in sides["original"]
            for right in sides["translated"]
            if left["signature"] == right["signature"]
        ]
        if len(matches) != 1:
            continue
        region_pair: dict[str, Any] = {"id": name}
        for side, d, region in (
            ("original", da, matches[0][0]),
            ("translated", db, matches[0][1]),
        ):
            caption = min(1.0, max(0.0, 1.0 - d["yfrac"]))
            region_pair[side] = {
                "page": d["page"],
                "start": round(min(region["start"], caption), 5),
                "end": round(min(1.0, max(region["end"], caption + _CAPTION_PAD)), 5),
            }
        regions.append(region_pair)
    regions.sort(key=lambda r: (r["original"]["page"], r["original"]["start"]))
    return regions


def build_alignment(en_pdf: Path, zh_pdf: Path) -> dict[str, Any]:
    """产出 dual.json 的 ``alignment`` 段。

    有公共锚 → ``{"kind":"landmarks","heights":{...},"pairs":[...],
    "regions":[...]}``，pairs 为 original 序的单调链（乱序锚丢弃）、
    regions 为 figure 浮动块双侧区间（候选取全部公共锚，不受链丢弃影响）；
    无公共锚 → ``{"kind":"pages","heights":{...}}`` 让前端退同页映射。
    PDF 损坏/读不动按无锚处理——阅读器降级比任务失败便宜；双侧独立
    抽取，一侧坏掉仍回存活侧的真实 ``heights``（缺席侧前端按每页 1 计）。
    """
    try:
        from pypdf import PdfReader  # noqa: PLC0415 -- 重依赖惰性加载
    except Exception:  # noqa: BLE001 -- pypdf 缺席 → 连 heights 也抽不出
        return {"kind": "pages"}
    readers: dict[str, PdfReader] = {}
    marks: dict[str, dict[str, Any]] = {}
    for side, pdf in (("original", en_pdf), ("translated", zh_pdf)):
        try:
            r = PdfReader(str(pdf))
            marks[side] = _reader_landmarks(r)
            readers[side] = r
        except Exception as e:  # noqa: BLE001 -- 截断/加密 PDF 只丢该侧同步精度
            log.debug("landmark extraction failed for %s: %s", pdf, e)
    ea, eb = marks.get("original"), marks.get("translated")
    if ea is None or eb is None:
        return {
            "kind": "pages",
            "heights": {s: m["heights"] for s, m in marks.items()},
        }
    heights = {"original": ea["heights"], "translated": eb["heights"]}
    commons = [
        (n, ea["dests"][n], eb["dests"][n])
        for n in sorted(set(ea["dests"]) & set(eb["dests"]))
    ]
    chain = _monotonic_chain(commons)
    if not chain:
        return {"kind": "pages", "heights": heights}
    lut = {n: (a, b) for n, a, b in commons}
    pairs = [
        {
            "id": n,
            "original": _pos(lut[n][0]),
            "translated": _pos(lut[n][1]),
        }
        for n in chain
    ]
    regions = _match_figure_regions(readers, commons)
    return {
        "kind": "landmarks",
        "heights": heights,
        "pairs": pairs,
        "regions": regions,
    }
