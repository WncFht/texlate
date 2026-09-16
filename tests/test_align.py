"""align.py 单测——合成 PDF 钉 named dests（alignbench selftest 同款构造）。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    Destination,
    DictionaryObject,
    Fit,
    FloatObject,
    NameObject,
    NullObject,
    NumberObject,
    TextStringObject,
)

from texlate import align
from texlate.align import build_alignment, extract_landmarks

if TYPE_CHECKING:
    from pathlib import Path

PAGE_H = 792.0  # letter 页高，FitH y=页顶
NP = 6  # 通用页数
IMG = bytes(range(64)) * 3  # 同字节 → 同 graphic signature（跨 PDF 匹配）


def _mk_pdf(path: Path, dests: list[tuple[str, int]], npages: int = NP) -> Path:
    """npages 空白页 + named destinations（FitH y=页顶）。"""
    w = PdfWriter()
    for _ in range(npages):
        w.add_blank_page(width=612, height=PAGE_H)
    for name, page in dests:
        w.add_named_destination_object(
            Destination(
                name, w.pages[page].indirect_reference, Fit.fit_horizontally(PAGE_H)
            )
        )
    with path.open("wb") as fh:
        w.write(fh)
    return path


def _mk_fig_pdf(
    path: Path,
    dests: list[tuple[str, int, float]],
    arts: list[tuple[int, tuple[float, float, float, float], bytes]],
    npages: int = NP,
) -> Path:
    """npages 空白页 + FitH 指定 y 的 named dests + 图像 XObject 落点。

    arts: ``(page_idx, (x, y, w, h), img_bytes)``——content stream 落
    ``q w 0 0 h x y cm /ImN Do Q``；img_bytes 逐字节相同则 signature 相同。
    """
    w = PdfWriter()
    for _ in range(npages):
        w.add_blank_page(width=612, height=PAGE_H)
    by_page: dict[int, list[tuple[int, tuple[float, float, float, float], bytes]]] = {}
    for i, (pidx, box, payload) in enumerate(arts):
        by_page.setdefault(pidx, []).append((i, box, payload))
    for pidx, items in by_page.items():
        xobj: dict[NameObject, DecodedStreamObject] = {}
        ops = []
        for i, (x, y, aw, ah), payload in items:
            img = DecodedStreamObject()
            img.set_data(payload)
            img.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(8),
                    NameObject("/Height"): NumberObject(8),
                    NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                }
            )
            xobj[NameObject(f"/Im{i}")] = img
            ops.append(f"q {aw} 0 0 {ah} {x} {y} cm /Im{i} Do Q")
        cs = DecodedStreamObject()
        cs.set_data(" ".join(ops).encode())
        page = w.pages[pidx]
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject(xobj)}
        )
        page[NameObject("/Contents")] = cs
    for name, pidx, top in dests:
        w.add_named_destination_object(
            Destination(
                name, w.pages[pidx].indirect_reference, Fit.fit_horizontally(top)
            )
        )
    with path.open("wb") as fh:
        w.write(fh)
    return path


def test_extract_landmarks_basic(tmp_path: Path) -> None:
    dests = [("section.1", 0), ("figure.1", 2)]
    pdf = _mk_pdf(tmp_path / "a.pdf", dests)
    lm = extract_landmarks(pdf)
    assert lm["npages"] == NP
    assert lm["heights"] == [1.0] * NP
    assert lm["dests"]["section.1"]["page"] == 1
    # FitH y=792=页顶 → 底向上 yfrac=1.0
    assert lm["dests"]["section.1"]["yfrac"] == pytest.approx(1.0)


def test_build_alignment_keep(tmp_path: Path) -> None:
    dests = [(f"section.{i}", i - 1) for i in range(1, 5)] + [
        (f"figure.{i}", i + 1) for i in range(1, 4)
    ]
    a = _mk_pdf(tmp_path / "a.pdf", dests)
    b = _mk_pdf(tmp_path / "b.pdf", dests)
    al = build_alignment(a, b)
    assert al["kind"] == "landmarks"
    assert len(al["pairs"]) == len(dests)
    assert al["pairs"][0]["id"] == "section.1"
    # 顶锚 fraction 翻转为自顶向下 0.0
    assert al["pairs"][0]["original"]["fraction"] == pytest.approx(0.0)
    assert al["pairs"][0]["original"]["page"] == 1


def test_build_alignment_shift_still_monotonic(tmp_path: Path) -> None:
    base = [(f"section.{i}", i - 1) for i in range(1, 5)]
    a = _mk_pdf(tmp_path / "a.pdf", base, npages=5)
    b = _mk_pdf(tmp_path / "b.pdf", [(n, p + 1) for n, p in base])
    al = build_alignment(a, b)
    assert al["kind"] == "landmarks"
    assert len(al["pairs"]) == len(base)
    assert all(
        p["translated"]["page"] == p["original"]["page"] + 1 for p in al["pairs"]
    )


def test_build_alignment_drops_out_of_order(tmp_path: Path) -> None:
    a_dests = [("section.1", 0), ("figure.1", 1), ("section.2", 2)]
    # zh 侧 figure.1（权 10 < section 12）被顶到末页 → 链取 [s1,s2] 弃 figure
    b_dests = [("section.1", 0), ("section.2", 2), ("figure.1", 5)]
    a = _mk_pdf(tmp_path / "a.pdf", a_dests, npages=4)
    b = _mk_pdf(tmp_path / "b.pdf", b_dests)
    al = build_alignment(a, b)
    assert al["kind"] == "landmarks"
    assert [p["id"] for p in al["pairs"]] == ["section.1", "section.2"]


def test_build_alignment_no_common_falls_back(tmp_path: Path) -> None:
    a = _mk_pdf(tmp_path / "a.pdf", [("section.1", 0)], npages=3)
    b = _mk_pdf(tmp_path / "b.pdf", [("other.9", 0)], npages=3)
    al = build_alignment(a, b)
    assert al["kind"] == "pages"
    assert al["heights"]["original"] == [1.0, 1.0, 1.0]


def test_build_alignment_corrupt_pdf_falls_back(tmp_path: Path) -> None:
    a = _mk_pdf(tmp_path / "a.pdf", [("section.1", 0)], npages=3)
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 truncated garbage")
    assert build_alignment(a, bad)["kind"] == "pages"


def test_page_anchors_excluded(tmp_path: Path) -> None:
    pdf = _mk_pdf(
        tmp_path / "a.pdf", [("page.1", 0), ("page.2", 1), ("section.1", 1)], npages=3
    )
    lm = extract_landmarks(pdf)
    assert list(lm["dests"]) == ["section.1"]


# ------------------------------------------------------------------ regions
# 图形落点约定：cm (x,y,w,h) → 用户空间矩形 x..x+w / y..y+h；fraction 自顶向下。
# art (100,500,400,200) → 顶 (792-700)/792≈0.1162、底 (792-500)/792≈0.3687；
# caption FitH 480 → fraction 0.3939，距底缘 0.025 < 0.065 归属成立。


def test_regions_matched_figure(tmp_path: Path) -> None:
    """双侧同 artwork + caption 邻近 → regions 产出图形纵向区间。"""
    dests = [("section.1", 0, PAGE_H), ("figure.1", 1, 480.0)]
    arts = [(1, (100.0, 500.0, 400.0, 200.0), IMG)]
    a = _mk_fig_pdf(tmp_path / "a.pdf", dests, arts)
    b = _mk_fig_pdf(tmp_path / "b.pdf", dests, arts)
    al = build_alignment(a, b)
    assert al["kind"] == "landmarks"
    assert len(al["regions"]) == 1
    reg = al["regions"][0]
    assert reg["id"] == "figure.1"
    for side in ("original", "translated"):
        rc = reg[side]
        assert rc["page"] == 2  # noqa: PLR2004 -- 钉的是字面页号
        assert rc["start"] == pytest.approx(0.1162, abs=1e-3)
        # 下缘 = max(图形底, caption+pad) = 0.3939+0.025
        assert rc["end"] == pytest.approx(0.4189, abs=1e-3)
        assert 0 <= rc["start"] < rc["end"] <= 1


def test_regions_floated_figure_survives_chain_drop(tmp_path: Path) -> None:
    """图浮动出序被单调链丢弃，但 regions 仍按 artwork 配对产出。"""
    a_dests = [
        ("section.1", 0, PAGE_H),
        ("figure.1", 1, 480.0),
        ("section.2", 2, PAGE_H),
    ]
    b_dests = [
        ("section.1", 0, PAGE_H),
        ("section.2", 2, PAGE_H),
        ("figure.1", 5, 180.0),  # 漂到末页 → 出序 → pairs 丢弃
    ]
    a = _mk_fig_pdf(
        tmp_path / "a.pdf", a_dests, [(1, (100.0, 500.0, 400.0, 200.0), IMG)]
    )
    b = _mk_fig_pdf(
        tmp_path / "b.pdf", b_dests, [(5, (100.0, 200.0, 300.0, 150.0), IMG)]
    )
    al = build_alignment(a, b)
    assert al["kind"] == "landmarks"
    assert [p["id"] for p in al["pairs"]] == ["section.1", "section.2"]
    assert len(al["regions"]) == 1
    reg = al["regions"][0]
    assert reg["id"] == "figure.1"
    assert reg["original"]["page"] == 2  # noqa: PLR2004 -- 同上
    assert reg["translated"]["page"] == 6  # noqa: PLR2004 -- 同上
    # zh 侧图形 (100,200,300,150)：顶 (792-350)/792≈0.5581、底 (792-200)/792≈0.7475
    # caption FitH 180 → 0.7727；end = max(0.7475, 0.7727+0.025) = 0.7977
    assert reg["translated"]["start"] == pytest.approx(0.5581, abs=1e-3)
    assert reg["translated"]["end"] == pytest.approx(0.7977, abs=1e-3)


def test_regions_ambiguous_art_skipped(tmp_path: Path) -> None:
    """同页两块相同 artwork 都在归属容差内 → 歧义不产出（texglot 语义）。"""
    dests = [("figure.1", 0, 480.0)]
    arts = [
        (0, (100.0, 500.0, 400.0, 200.0), IMG),
        (0, (100.0, 340.0, 400.0, 150.0), IMG),  # 同字节第二块，顶缘 0.381 邻近
    ]
    a = _mk_fig_pdf(tmp_path / "a.pdf", dests, arts)
    b = _mk_fig_pdf(tmp_path / "b.pdf", dests, arts)
    al = build_alignment(a, b)
    assert al["kind"] == "landmarks"
    assert al["regions"] == []


def test_regions_no_art_near_caption(tmp_path: Path) -> None:
    """caption 距图形上下缘超 0.065（如 tikz 矢量图无 XObject）→ 无 region。"""
    dests = [("figure.1", 0, 100.0)]  # caption fraction 0.8737 远离图形
    arts = [(0, (100.0, 500.0, 400.0, 200.0), IMG)]
    a = _mk_fig_pdf(tmp_path / "a.pdf", dests, arts)
    b = _mk_fig_pdf(tmp_path / "b.pdf", dests, arts)
    al = build_alignment(a, b)
    assert al["kind"] == "landmarks"
    assert al["regions"] == []


def test_regions_different_art_no_match(tmp_path: Path) -> None:
    """双侧 artwork 字节不同 → signature 不匹配 → 无 region。"""
    dests = [("figure.1", 0, 480.0)]
    a = _mk_fig_pdf(tmp_path / "a.pdf", dests, [(0, (100.0, 500.0, 400.0, 200.0), IMG)])
    b = _mk_fig_pdf(
        tmp_path / "b.pdf",
        dests,
        [(0, (100.0, 500.0, 400.0, 200.0), bytes(range(64, 128)) * 3)],
    )
    al = build_alignment(a, b)
    assert al["regions"] == []


def test_regions_only_figure_anchors(tmp_path: Path) -> None:
    """region 归属只认 figure.*/subfigure.*——table 锚邻近 artwork 不产出。"""
    dests = [("table.1", 0, 480.0)]
    arts = [(0, (100.0, 500.0, 400.0, 200.0), IMG)]
    a = _mk_fig_pdf(tmp_path / "a.pdf", dests, arts)
    b = _mk_fig_pdf(tmp_path / "b.pdf", dests, arts)
    al = build_alignment(a, b)
    assert al["kind"] == "landmarks"
    assert al["regions"] == []


# ---------------------------------------------------------------- 残余审计补充
# writer 会把 parent /Resources 拍平进页对象、把 /Top 强转 FloatObject——
# 继承/畸形形态靠 reader 侧手术与 duck-type stub 构造。


class _StubPage:
    def __init__(self, height: float = PAGE_H) -> None:
        self.mediabox = SimpleNamespace(height=height)


class _BadBoxPage:
    @property
    def mediabox(self) -> object:
        msg = "corrupt mediabox"
        raise ValueError(msg)


class _StubReader:
    """duck-type PdfReader——畸形 /Top 经 writer 写不出（强转 FloatObject）。"""

    def __init__(self, dests: dict[str, Any], pages: list[object]) -> None:
        self._dests = dests
        self.pages = pages

    @property
    def named_destinations(self) -> dict[str, Any]:
        return self._dests

    @staticmethod
    def get_destination_page_number(dest: object) -> int:
        return int(dest["__p"])  # type: ignore[index]


def test_no_top_anchor_sorts_as_page_top(tmp_path: Path) -> None:
    """无 /Top 锚（/Fit 整页）按页顶排序——与 _pos 输出 fraction 0.0 自洽。

    修复前 _order_key 把 None 当页底（-0.0），同页 fraction 序列 0.495→0.0
    非单调；修复后 whole.1 排序在 section.1 之前，fraction 非降。
    """

    def mk(p: Path) -> Path:
        w = PdfWriter()
        for _ in range(3):
            w.add_blank_page(width=612, height=PAGE_H)
        w.add_named_destination_object(
            Destination("whole.1", w.pages[0].indirect_reference, Fit.fit())
        )
        w.add_named_destination_object(
            Destination(
                "section.1",
                w.pages[0].indirect_reference,
                Fit.fit_horizontally(400.0),
            )
        )
        with p.open("wb") as fh:
            w.write(fh)
        return p

    al = build_alignment(mk(tmp_path / "a.pdf"), mk(tmp_path / "b.pdf"))
    assert [p["id"] for p in al["pairs"]] == ["whole.1", "section.1"]
    fracs = [p["original"]["fraction"] for p in al["pairs"]]
    assert fracs == sorted(fracs)
    assert fracs[0] == 0.0


def test_malformed_top_falls_back_to_page_top() -> None:
    """畸形 /Top（文本/Null/间接）只丢精度不丢锚——按页顶（yfrac None）。"""
    dests = {
        "weird.1": DictionaryObject(
            {"/Top": TextStringObject("junk"), "__p": NumberObject(0)}
        ),
        "null.1": DictionaryObject({"/Top": NullObject(), "__p": NumberObject(1)}),
        "over.1": DictionaryObject(
            {"/Top": FloatObject(900.0), "__p": NumberObject(0)}
        ),
    }
    lm = align._reader_landmarks(  # noqa: SLF001 -- 白盒钉私有提取逻辑
        _StubReader(dests, [_StubPage(), _StubPage()])
    )
    assert lm["npages"] == 2  # noqa: PLR2004 -- 桩页数即断言对象
    assert lm["dests"]["weird.1"]["yfrac"] is None
    assert lm["dests"]["weird.1"]["page"] == 1
    assert lm["dests"]["null.1"]["yfrac"] is None
    # 越界 /Top（900 > 792 页高）钳到 0..1
    assert lm["dests"]["over.1"]["yfrac"] == 1.0


def test_mediabox_garbage_page_falls_back() -> None:
    """单页 mediabox 解析炸/nan → 该页高度回退 792，npages 与页序不动。"""
    pages = [_StubPage(), _BadBoxPage(), _StubPage(float("nan"))]
    lm = align._reader_landmarks(_StubReader({}, pages))  # noqa: SLF001 -- 同上
    assert lm["npages"] == 3  # noqa: PLR2004 -- 同上
    # 全部回退 792 → 归一化后仍全 1.0
    assert lm["heights"] == [1.0, 1.0, 1.0]


def test_regions_inherited_resources(tmp_path: Path) -> None:
    """/Resources 只在父节点的页也能扫到 XObject（get_inherited）。"""
    dests = [("figure.1", 0, 480.0)]
    arts = [(0, (100.0, 500.0, 400.0, 200.0), IMG)]
    a = _mk_fig_pdf(tmp_path / "a.pdf", dests, arts)
    r = PdfReader(str(a))
    pg = r.pages[0]
    # 手术成继承形态：页级 /Resources 挪到父节点（writer 写出时会拍平，
    # 真实继承形态只能从 reader 对象图构造）
    pg["/Parent"].get_object()[NameObject("/Resources")] = pg["/Resources"]
    del pg["/Resources"]
    regions = align._graphic_regions(pg)  # noqa: SLF001 -- 白盒钉私有扫描逻辑
    assert len(regions) == 1
    assert regions[0]["start"] == pytest.approx(0.1162, abs=1e-3)


def test_regions_broken_art_sibling_survives(tmp_path: Path) -> None:
    """同页一块畸形 XObject（Do 指向非流对象）不拖死正常 artwork。"""
    dests = [("figure.1", 0, 480.0)]
    arts = [(0, (100.0, 500.0, 400.0, 200.0), IMG)]
    a = _mk_fig_pdf(tmp_path / "a.pdf", dests, arts)
    r = PdfReader(str(a))
    pg = r.pages[0]
    xobj = pg["/Resources"].get_object()["/XObject"].get_object()
    xobj[NameObject("/Bad")] = NumberObject(42)  # Do 落点解析对它必炸
    cs = DecodedStreamObject()
    cs.set_data(b"q 400 0 0 200 100 500 cm /Im0 Do Q q 50 0 0 50 0 0 cm /Bad Do Q")
    pg[NameObject("/Contents")] = cs
    regions = align._graphic_regions(pg)  # noqa: SLF001 -- 同上
    assert len(regions) == 1
    assert regions[0]["start"] == pytest.approx(0.1162, abs=1e-3)


def test_regions_malformed_ops_lose_only_themselves(tmp_path: Path) -> None:
    """畸形 ``cm`` 参数与非名 ``Do`` operand 只丢各自算子，不拖整页 regions。

    回归：``float(operand)`` 的 ValueError 与 ``ArrayObject in dict`` 的
    TypeError 都在算子分派层外炸——一条坏流让整页 figure 区间全丢。
    """
    dests = [("figure.1", 0, 480.0)]
    arts = [(0, (100.0, 500.0, 400.0, 200.0), IMG)]
    a = _mk_fig_pdf(tmp_path / "a.pdf", dests, arts)
    r = PdfReader(str(a))
    pg = r.pages[0]
    cs = DecodedStreamObject()
    # 坏 cm（字符串 operand）→ 矩阵不变；[/Arr] Do → 非名 operand 跳过；
    # /Im0 仍按好 cm 落点 (100,500,400,200)。
    cs.set_data(b"q (junk) 0 0 1 10 20 cm q 400 0 0 200 100 500 cm [/Arr] Do /Im0 Do Q")
    pg[NameObject("/Contents")] = cs
    regions = align._graphic_regions(pg)  # noqa: SLF001 -- 白盒钉私有扫描逻辑
    assert len(regions) == 1
    assert regions[0]["start"] == pytest.approx(0.1162, abs=1e-3)


def test_chain_keeps_duplicate_positions(tmp_path: Path) -> None:
    """同页同 ``/Top`` 的锚点（key 完全相等）不构成乱序——``<=`` 链全收。"""
    dests = [("figure.1", 0, 600.0), ("figure.2", 0, 600.0), ("section.1", 1, 700.0)]
    a = _mk_fig_pdf(tmp_path / "a.pdf", dests, [])
    b = _mk_fig_pdf(tmp_path / "b.pdf", dests, [])
    al = build_alignment(a, b)
    assert al["kind"] == "landmarks"
    ids = [p["id"] for p in al["pairs"]]
    assert ids == ["figure.1", "figure.2", "section.1"]
