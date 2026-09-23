"""seqpos.py 单测——归一化/行聚/双栏/匹配两遍 + 合成 PDF 端到端。

合成 PDF 构造与 test_align 同款：pypdf 空白页 + 手写内容流
（``BT /F1 Tf Td (..) Tj ET`` + ``/TLXC << /MCID 50000+seq >> BDC``）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from texlate.server import seqpos as M  # noqa: N812 -- 测试惯例模块别名

if TYPE_CHECKING:
    from pathlib import Path


def _mk_pdf(
    path: Path,
    pages: list[list[tuple[float, float, str]]],
    marks: dict[int, tuple[int, float, float]] | None = None,
) -> Path:
    """pages: 每页 [(x, y, text)]，y 底向上；marks: seq→(page_idx, x, y)。"""
    w = PdfWriter()
    marks = marks or {}
    for pi, lines in enumerate(pages):
        page = w.add_blank_page(width=612, height=792)
        # BDC 须在 BT/Tm 之后——visitor_operand_before 的活 tm 才有真位
        # （真 zh.pdf 的 reconstruct 注锚同构：BDC 紧贴 Tj 前）
        marks_at = {(mx, my): seq for seq, (mp, mx, my) in marks.items() if mp == pi}
        ops = []
        for x, y, t in lines:
            bdc = (
                f"/TLXC << /MCID {50000 + marks_at[(x, y)]} >> BDC "
                if (x, y) in marks_at
                else ""
            )
            emc = " EMC" if bdc else ""
            ops.append(f"BT /F1 10 Tf 1 0 0 1 {x} {y} Tm {bdc}({t}) Tj{emc} ET")
        stream = DecodedStreamObject()
        stream.set_data(" ".join(ops).encode())
        content_ref = w._add_object(stream)  # noqa: SLF001 -- pypdf 无公开注册
        page[NameObject("/Contents")] = content_ref
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Font"),
                                NameObject("/Subtype"): NameObject("/Type1"),
                                NameObject("/BaseFont"): NameObject("/Helvetica"),
                            }
                        )
                    }
                )
            }
        )
    with path.open("wb") as fh:
        w.write(fh)
    return path


class TestNorm:
    def test_norm_strips_punct_case_ligature(self) -> None:
        assert M._norm_chars("Fi- nal: Text!") == "finaltext"  # noqa: SLF001 -- 白盒钉归一化
        assert M._norm_chars("ﬁle") == "file"  # noqa: SLF001 -- NFKD 连字折叠
        assert M._norm_chars("Café") == "cafe"  # noqa: SLF001 -- combining 剥 + lower

    def test_tex_strip_port(self) -> None:
        s = M._tex_strip(  # noqa: SLF001 -- 白盒钉前端 port 语义
            r"See \cite{a} $x^2$ [[EQ_3]] \textbf{hi} \% done \\"
        )
        # cite 命令+数学+掩码+textbf 壳全剥，\% 留字面 %，\\ 变空格
        n = M._norm_chars(s)  # noqa: SLF001 -- 同上
        assert "cite" not in n
        assert "x" not in n
        assert "EQ" not in n
        assert "hi" in n
        assert "%" not in n  # % 非 alnum 归一剥


class TestMatchSide:
    STREAM = "".join(f"chunk{i}textwithuniquemarker{i:03d}padding" for i in range(20))

    def _needles(self, seqs: list[int]) -> list[tuple[int, str]]:
        return [(s, f"chunk{s}textwithuniquemarker{s:03d}padding") for s in seqs]

    def test_sequential_hits(self) -> None:
        off = M._match_side(self._needles(list(range(6))), self.STREAM)  # noqa: SLF001 -- 白盒钉两遍匹配
        want = {s: self.STREAM.index(f"chunk{s}text") for s in range(6)}
        assert off == want

    def test_marked_out_of_order(self) -> None:
        """marked seq 只吃先验带——seq0 真位在 seq1 后（浮动体出序）合法。"""
        # 构造：seq1 文本在流中先于 seq0
        stream = "chunk1aaa" + "x" * 100 + "chunk0bbb"
        needles = [(0, "chunk0bbb"), (1, "chunk1aaa")]
        prior = {0: 100, 1: 0}
        off = M._match_side(needles, stream, prior)  # noqa: SLF001 -- 同上
        assert off[0] == stream.index("chunk0bbb")
        assert off[1] == 0

    def test_prior_band_excludes_far_false_anchor(self) -> None:
        """相似文本出现在带外 → miss 不误锚（seq174 实证面）。"""
        stream = "targetneedleAAA" + "z" * 50000 + "targetneedleAAA"
        prior = {0: 51000}
        off = M._match_side([(0, "targetneedleAAA")], stream, prior)  # noqa: SLF001
        assert off[0] == stream.rindex("targetneedleAAA")

    def test_inverted_bracket_window(self) -> None:
        """lo_known 邻位窗倒置（浮动锚）→ 退化局部窗仍能命中（seq161 实证）。"""
        stream = "a" * 100 + "mytarget" + "b" * 100
        # 前邻 offset=180 后邻 offset=10 —— 倒置
        off = M._match_side(  # noqa: SLF001
            [(5, "mytarget")], stream, lo_known={4: 180, 6: 10}
        )
        assert off[5] == 100  # noqa: PLR2004 -- 钉字面 offset

    def test_zero_gram_slots_skipped(self) -> None:
        """needle 多个 6-gram 缺席时仍用其余稀 gram 锚定（seq20 实证）。"""
        stream = ("abcdefghij" * 8) + "q" * 3000
        # 三段 10 字腐坏 → ≥8 个缺席 gram；真位覆盖 ~62/80 ≥ 0.55 阈
        needle = (
            "abcdefghij" * 2
            + "Z" * 10
            + "abcdefghij" * 2
            + "Z" * 10
            + "abcdefghij" * 2
            + "Z" * 10
            + "abcdefghij"
        )
        off = M._match_side([(0, needle)], stream)  # noqa: SLF001
        assert off.get(0) == 0

    def test_short_needle_find_fallback(self) -> None:
        stream = "zz" + "ab" + "zz"
        off = M._match_side([(0, "ab")], stream)  # noqa: SLF001
        assert off[0] == 2  # noqa: PLR2004 -- 钉字面 offset


class TestReadingOrder:
    def test_two_column_split(self) -> None:
        lines = []
        # 左栏 3 行 右栏 3 行 + 通栏标题 1 行
        for i, y in enumerate([700, 680, 660]):
            lines.append([y, [(50, f"L{i}")], 50, 250])
        for i, y in enumerate([700, 680, 660]):
            lines.append([y, [(350, f"R{i}")], 350, 560])
        lines.insert(0, [720, [(50, "TITLE")], 50, 560])
        out = M._reading_order(lines, 612)  # noqa: SLF001 -- 白盒钉栏切
        seq = ["".join(t for _, t in ln[1]) for ln in out]
        assert seq == ["TITLE", "L0", "L1", "L2", "R0", "R1", "R2"]

    def test_single_column_passthrough(self) -> None:
        lines = [[700 - i * 20, [(50, f"L{i}")], 50, 500] for i in range(4)]
        out = M._reading_order(lines, 612)  # noqa: SLF001
        assert [ln[1][0][1] for ln in out] == ["L0", "L1", "L2", "L3"]


class TestOffsetAt:
    def test_nearest_bound(self) -> None:
        bounds = [(0, 1, 0.1), (50, 1, 0.3), (100, 2, 0.1)]
        keys = [(b[1], b[2]) for b in bounds]
        assert M._offset_at(bounds, keys, 1, 0.25) == 50  # noqa: SLF001, PLR2004 -- 钉字面界
        assert M._offset_at(bounds, keys, 2, 0.05) == 100  # noqa: SLF001, PLR2004


class TestEndToEnd:
    def test_compute_seqpos_synthetic(self, tmp_path: Path) -> None:
        en = _mk_pdf(
            tmp_path / "en.pdf",
            [[(72, 700, "Alpha intro text"), (72, 660, "Beta body text")]],
        )
        zh = _mk_pdf(
            tmp_path / "zh.pdf",
            [[(72, 700, "Zh alpha text"), (72, 660, "Zh beta text")]],
            marks={0: (0, 72, 700)},
        )
        chunks = [
            {"seq": 0, "en": "Alpha intro text", "zh": "Zh alpha text"},
            {"seq": 1, "en": "Beta body text", "zh": "Zh beta text"},
        ]
        sp = M.compute_seqpos(en, zh, chunks)
        assert set(sp) == {"0", "1"}
        # seq0 zh 走 mark（y=700 → frac≈(792-706)/792≈0.108）
        assert sp["0"]["t"]["page"] == 1
        assert abs(sp["0"]["t"]["fraction"] - 0.1086) < 0.01  # noqa: PLR2004 -- 钉字面 frac
        # seq1 zh 走匹配；en 两侧都在第 1 页
        assert sp["0"]["o"]["page"] == 1
        assert sp["1"]["o"]["page"] == 1
        assert sp["0"]["o"]["fraction"] < sp["1"]["o"]["fraction"]

    def test_seqpos_for_task_cache(self, tmp_path: Path) -> None:
        _mk_pdf(tmp_path / "en.pdf", [[(72, 700, "Alpha intro text")]])
        _mk_pdf(
            tmp_path / "zh.pdf",
            [[(72, 700, "Zh alpha text")]],
            marks={0: (0, 72, 700)},
        )
        dual = {"chunks": [{"seq": 0, "en": "Alpha intro text", "zh": "Zh alpha text"}]}
        (tmp_path / "dual.json").write_text(json.dumps(dual))
        sp = M.seqpos_for_task(tmp_path, dual)
        assert sp is not None
        assert sp["0"]["t"]["page"] == 1
        assert (tmp_path / "seqpos.json").is_file()
        # 二调走缓存（同结果即可——mtime 闸语义在文件存在+版本钉）
        sp2 = M.seqpos_for_task(tmp_path, dual)
        assert sp2 == sp

    def test_seqpos_for_task_missing_inputs(self, tmp_path: Path) -> None:
        assert M.seqpos_for_task(tmp_path, {"chunks": []}) is None
        got = M.seqpos_for_task(
            tmp_path, {"chunks": [{"seq": 0, "en": "x", "zh": "y"}]}
        )
        assert got is None
