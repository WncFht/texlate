"""align.py 单测——合成 PDF 钉 named dests（alignbench selftest 同款构造）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pypdf import PdfWriter
from pypdf.generic import Destination, Fit

from texlate.align import build_alignment, extract_landmarks

if TYPE_CHECKING:
    from pathlib import Path

PAGE_H = 792.0  # letter 页高，FitH y=页顶
NP = 6  # 通用页数


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
