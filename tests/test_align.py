"""align.py 单测——合成 PDF 钉 named dests（alignbench selftest 同款构造）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    Destination,
    DictionaryObject,
    Fit,
    NameObject,
    NumberObject,
)

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
