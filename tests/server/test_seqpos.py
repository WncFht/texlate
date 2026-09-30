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


def _write_pdf(path: Path, pages_ops: list[list[str]]) -> Path:
    """裸 ops 流 → 单字体 PDF（嵌套 BDC/乱序 EMC 等非常规构造走这里）。"""
    w = PdfWriter()
    for ops in pages_ops:
        page = w.add_blank_page(width=612, height=792)
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


def _mk_pdf(
    path: Path,
    pages: list[list[tuple[float, float, str]]],
    marks: dict[int, tuple[int, float, float] | list[tuple[int, float, float]]]
    | None = None,
) -> Path:
    """pages: 每页 [(x, y, text)]，y 底向上。

    marks: seq→(page_idx, x, y)，或 seq→列表——同 MCID 双 BDC（hyperref/
    TOC 重放）的构造面。
    """
    marks = marks or {}
    pages_ops: list[list[str]] = []
    for pi, lines in enumerate(pages):
        # BDC 须在 BT/Tm 之后——visitor_operand_before 的活 tm 才有真位
        # （真 zh.pdf 的 reconstruct 注锚同构：BDC 紧贴 Tj 前）
        marks_at: dict[tuple[float, float], int] = {}
        for seq, spec in marks.items():
            for mp, mx, my in spec if isinstance(spec, list) else [spec]:
                if mp == pi:
                    marks_at[(mx, my)] = seq
        ops = []
        for x, y, t in lines:
            bdc = (
                f"/TLXC << /MCID {50000 + marks_at[(x, y)]} >> BDC "
                if (x, y) in marks_at
                else ""
            )
            # EMC 前的 0 0 Td 在标内冲刷 Tj——pypdf 否则拖到 ET 才发
            # visitor_text，栈已弹 → occurrence 拿不到 fraction/chars
            emc = " 0 0 Td EMC" if bdc else ""
            ops.append(f"BT /F1 10 Tf 1 0 0 1 {x} {y} Tm {bdc}({t}) Tj{emc} ET")
        pages_ops.append(ops)
    return _write_pdf(path, pages_ops)


class TestNorm:
    def test_norm_strips_punct_case_ligature(self) -> None:
        assert M._norm_chars("Fi- nal: Text!") == "finaltext"  # noqa: SLF001 -- 白盒钉归一化
        assert M._norm_chars("ﬁle") == "file"  # noqa: SLF001 -- NFKD 连字折叠
        assert M._norm_chars("Café") == "cafe"  # noqa: SLF001 -- combining 剥 + lower

    def test_tex_strip_port(self) -> None:
        s = M._tex_strip(  # noqa: SLF001 -- 白盒钉前端 port 语义
            r"See \cite{a} $x^2$ [[EQ_3]] \textbf{hi} \% done \\"
        )
        # cite 命令 + 数学 + 掩码+textbf 壳全剥，\% 留字面 %，\\ 变空格
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

    def test_prev_end_not_starved_by_out_of_order_hit(self) -> None:
        """命中位 <prev_end 的出序锚不拖光标——prev_end 只在 p>=prev_end 推进。"""
        # seq1(marked) 命中 p=5 但针长 2000——旧逻辑 prev_end 被尾块拖到
        # 2005，seq2 真位 10 落在窗口 [1705,+] 外饿死；守卫后 prev_end
        # 停 10，seq2 窗口 [0,4040] 正常命中
        nd1 = "x" * 5 + "w" * 10 + "a" * 1985
        stream = "x" * 10 + "w" * 10 + "a" * 1995 + "z" * 50
        needles = [(0, "x" * 10), (1, nd1), (2, "w" * 10)]
        off = M._match_side(needles, stream, prior={1: 5})  # noqa: SLF001
        assert off[2] == stream.index("w" * 10)

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
        """needle 多个 6-gram 缺席时仍用其余稀 gram 锚定（seq20 实证）。

        新判据要最长单块 ≥0.3·ln——腐坏段集中中部，保 50 字最长块。
        """
        stream = ("abcdefghij" * 7) + "q" * 3000
        # 中部 10 字腐坏 → ≥8 个缺席 gram；真位覆盖 70/80、最长块 50
        needle = "abcdefghij" * 5 + "Z" * 10 + "abcdefghij" * 2
        off = M._match_side([(0, needle)], stream)  # noqa: SLF001
        assert off.get(0) == 0

    def test_fragmented_cov_rejected(self) -> None:
        """碎块凑数拒收：高 sum-cov 但最长块 <0.3·ln → miss（跨页假锚实证）。"""
        # needle 切成 4 段各 20 字、段间噪声——窗口内每段各自命中
        # （sum-cov≈0.8）但最长块 20 < 0.3×86≈26 → 拒
        seg = "abcdefghij" * 2
        needle = (seg + "ZZ") * 3 + seg + "ZZ"  # 4×20 + 8 = 88
        stream = "x" * 50 + (seg + "qq") * 3 + seg + "y" * 50
        off = M._match_side([(0, needle)], stream)  # noqa: SLF001
        assert 0 not in off

    def test_short_needle_find_fallback(self) -> None:
        stream = "zz" + "ab" + "zz"
        off = M._match_side([(0, "ab")], stream)  # noqa: SLF001
        assert off[0] == 2  # noqa: PLR2004 -- 钉字面 offset

    def test_float_jump_does_not_starve_following(self) -> None:
        """浮动针跨跳不饿死后续针——命中越过 pending 针真位时 prev_end 不跟。

        t_d7c669e8 实证：seq39 命中 16474（真浮动位），prev_end 推过
        seq43/44 的真位 14338/14887 → 双双饿死/错锚。探针见 seq40 的
        gram 在跳段内 → 光标留 14436，43/44 正常命中。
        """
        stream = (
            "seqAAAA"
            + "a" * 50
            + "seqCccc"
            + "c" * 30  # seqC 真位在 B 之前
            + "seqDddd"
            + "d" * 30
            + "z" * 1500  # 鸿沟（图表/公式区）
            + "seqBbbb"
            + "b" * 30  # seqB 浮动落在 D 之后
            + "seqEeee"
            + "e" * 30
        )
        needles = [
            (0, "seqAAAA" + "a" * 50),
            (1, "seqBbbb" + "b" * 30),  # 浮动针——针序在 C/D 前
            (2, "seqCccc" + "c" * 30),
            (3, "seqDddd" + "d" * 30),
            (4, "seqEeee" + "e" * 30),
        ]
        off = M._match_side(needles, stream)  # noqa: SLF001
        assert off[2] == stream.index("seqCccc")
        assert off[3] == stream.index("seqDddd")
        assert off[1] == stream.index("seqBbbb")
        assert off[4] == stream.index("seqEeee")

    def test_real_gap_still_advances_cursor(self) -> None:
        """跳段无 pending 针（真鸿沟）→ 光标照推——探针不饿死正常推进。"""
        stream = (
            "seqAAAA"
            + "a" * 50
            + "z" * 1500  # 鸿沟内无任何针的文本
            + "seqBbbb"
            + "b" * 30
            + "seqCccc"
            + "c" * 30
        )
        needles = [
            (0, "seqAAAA" + "a" * 50),
            (1, "seqBbbb" + "b" * 30),
            (2, "seqCccc" + "c" * 30),
        ]
        off = M._match_side(needles, stream)  # noqa: SLF001
        assert off[1] == stream.index("seqBbbb")
        assert off[2] == stream.index("seqCccc")


class TestReadingOrder:
    def test_two_column_split(self) -> None:
        lines = []
        # 左栏 5 行 右栏 5 行（够 _COL_MIN_LINES 才真检缝）+ 通栏标题
        for i, y in enumerate([700, 685, 670, 655, 640]):
            lines.append([y, [(50, f"L{i}", 200)], 50, 250, 10])
        for i, y in enumerate([700, 685, 670, 655, 640]):
            lines.append([y, [(350, f"R{i}", 210)], 350, 560, 10])
        lines.insert(0, [720, [(50, "TITLE", 510)], 50, 560, 14])
        out, gut = M._reading_order(lines, 612)  # noqa: SLF001 -- 白盒钉栏切
        assert gut is not None
        seq = ["".join(p[1] for p in ln[1]) for ln in out]
        assert seq == [
            "TITLE",
            "L0",
            "L1",
            "L2",
            "L3",
            "L4",
            "R0",
            "R1",
            "R2",
            "R3",
            "R4",
        ]

    def test_single_column_passthrough(self) -> None:
        lines = [[700 - i * 20, [(50, f"L{i}", 450)], 50, 500, 10] for i in range(4)]
        out, gut = M._reading_order(lines, 612)  # noqa: SLF001
        assert gut is None
        assert [ln[1][0][1] for ln in out] == ["L0", "L1", "L2", "L3"]

    def test_merged_row_split_at_gutter(self) -> None:
        """同基线左右栏合并行 → 缝带拆成两条独立行（part 级穿线计数）。"""
        lines = []
        for i in range(10):
            y = 720 - i * 20
            # 一行两个 part：左栏段 + 右栏段（_cluster_lines 合并态）
            lines.append([y, [(60, f"L{i}", 50), (340, f"R{i}", 50)], 60, 390, 10])
        out, gut = M._reading_order(lines, 612)  # noqa: SLF001
        assert gut is not None
        seq = ["".join(p[1] for p in ln[1]) for ln in out]
        assert seq == [*(f"L{i}" for i in range(10)), *(f"R{i}" for i in range(10))]
        # 拆出的右栏行自带 x0
        right = next(ln for ln in out if ln[1][0][1] == "R0")
        assert right[2] == 340  # noqa: PLR2004 -- 钉字面 x0

    def test_straddling_part_not_split(self) -> None:
        """单个 part 自身跨缝（通栏标题 run）不拆——整行判 span 区界。"""
        lines = []
        for i in range(10):
            y = 720 - i * 20
            lines.append([y, [(60, f"L{i}", 50), (340, f"R{i}", 50)], 60, 390, 10])
        # 通栏标题行：一个 part 横跨缝带 + 一个右侧 part——含跨缝 part 不拆
        lines.insert(0, [760, [(60, "TITLEWIDE", 400), (500, "T2", 30)], 60, 530, 14])
        out, gut = M._reading_order(lines, 612)  # noqa: SLF001
        assert gut is not None
        title = out[0]
        assert "".join(p[1] for p in title[1]) == "TITLEWIDET2"

    def test_phantom_gutter_rejected(self) -> None:
        """单栏 ragged 页 + 右浮动行的假缝不成立——浮动行不沉底重排。"""
        # 12 条左对齐正文（x 50..280）+ 2 条右浮动落款（420..520）：
        # 280..420 零穿线撑出假缝；无闸时 sig 被划右栏排页尾
        lines = [[720 - i * 40, [(50, f"T{i}", 230)], 50, 280, 10] for i in range(6)]
        lines.append([500, [(420, "sig1", 100)], 420, 520, 10])
        lines += [
            [400 - i * 40, [(50, f"T{6 + i}", 230)], 50, 280, 10] for i in range(6)
        ]
        lines.append([140, [(420, "sig2", 100)], 420, 520, 10])
        out, gut = M._reading_order(lines, 612)  # noqa: SLF001
        assert gut is None
        assert [ln[1][0][1] for ln in out] == [
            *(f"T{i}" for i in range(6)),
            "sig1",
            *(f"T{i}" for i in range(6, 12)),
            "sig2",
        ]


class TestOffsetAt:
    def test_same_col_nearest(self) -> None:
        # (char_off, page, frac, x, x1)——候选=同页同栏 |Δfrac| 最小者
        bounds = [
            (0, 1, 0.1, 0.1, 0.4),
            (50, 1, 0.3, 0.6, 0.9),
            (100, 2, 0.1, 0.1, 0.4),
        ]
        # x=0.6(右栏) 目标 frac0.15：全页最近是 frac0.1 界，同栏只取右栏界
        assert M._offset_at(bounds, 1, 0.15, 0.6) == 50  # noqa: SLF001, PLR2004
        # x 缺席 → 退化全页最近
        assert M._offset_at(bounds, 1, 0.15) == 0  # noqa: SLF001
        assert M._offset_at(bounds, 2, 0.05) == 100  # noqa: SLF001, PLR2004


class TestInterpT:
    def test_beyond_last_landmark_returns_none(self) -> None:
        """超末地标不钳位塌缩——t 置缺省走单侧 emit 兜底。"""
        pairs = [
            {
                "original": {"page": 1, "fraction": 0.1},
                "translated": {"page": 1, "fraction": 0.2},
            }
        ]
        assert M._interp_t(pairs, {"page": 9, "fraction": 0.9}) is None  # noqa: SLF001

    def test_intra_segment_kept(self) -> None:
        pairs = [
            {
                "original": {"page": 1, "fraction": 0.0},
                "translated": {"page": 1, "fraction": 0.0},
            },
            {
                "original": {"page": 3, "fraction": 0.0},
                "translated": {"page": 4, "fraction": 0.0},
            },
        ]
        got = M._interp_t(pairs, {"page": 2, "fraction": 0.0})  # noqa: SLF001
        assert got == {"page": 2, "fraction": 0.5}

    def test_interp_t_propagates_x(self) -> None:
        """zh_dead 插值 Pos 沿用 o_pos 的 x——同模板栏结构近似。"""
        pairs = [
            {
                "original": {"page": 1, "fraction": 0.0},
                "translated": {"page": 1, "fraction": 0.0},
            },
            {
                "original": {"page": 3, "fraction": 0.0},
                "translated": {"page": 4, "fraction": 0.0},
            },
        ]
        got = M._interp_t(pairs, {"page": 2, "fraction": 0.0, "x": 0.6})  # noqa: SLF001
        assert got == {"page": 2, "fraction": 0.5, "x": 0.6}


class TestSmCov:
    def test_empty_needle_no_divzero(self) -> None:
        """空 needle 不再 ZeroDivisionError——返回全零四元组。"""
        assert M._sm_cov("abc", 0, 3, "") == (0.0, 0, 0, 0)  # noqa: SLF001


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
        # seq0 zh 走 mark——锚=标内首 run 行顶（y=700+asc8 → frac=1-708/792，x=72/612）
        assert sp["0"]["t"]["page"] == 1
        assert abs(sp["0"]["t"]["fraction"] - (1 - 708 / 792)) < 0.001  # noqa: PLR2004
        assert abs(sp["0"]["t"]["x"] - 72 / 612) < 0.001  # noqa: PLR2004
        # seq1 zh 走匹配；en 两侧都在第 1 页；Pos 全带 x
        assert sp["0"]["o"]["page"] == 1
        assert sp["1"]["o"]["page"] == 1
        assert "x" in sp["0"]["o"]
        assert "x" in sp["1"]["t"]
        assert sp["0"]["o"]["fraction"] < sp["1"]["o"]["fraction"]

    def test_nested_bdc_emc_stack(self, tmp_path: Path) -> None:
        """嵌套/外来 BDC 不击穿归属：Span 内文本归 TLXC mark（栈语义）。

        pypdf 在 Td/Tm 才冲刷累积文本——行内穿插的 BDC/EMC 与 Tj 合并；
        每行后补 Td 让各行在标记开闭期间各触发一次 visitor_text。
        """
        zh = _write_pdf(
            tmp_path / "zh.pdf",
            [
                [
                    (
                        "BT /F1 10 Tf 1 0 0 1 72 700 Tm "
                        "/TLXC << /MCID 50000 >> BDC (Inner1) Tj "
                        "0 -20 Td /Span << /MCID 7 >> BDC (Inner2) Tj "
                        "0 -20 Td EMC (Outer3) Tj 0 -20 Td EMC ET"
                    )
                ]
            ],
        )
        _s, _b, marks = M._char_stream(zh, collect_marks=True)  # noqa: SLF001
        occ = marks[0][0]
        # 外来 Span BDC 压 None——Inner1/2/3 都归属外层 TLXC
        # （单标量 cur_mark 在首个 EMC 即丢标，Outer3 会漏记）。
        # pymupdf 文本面下 occ["text"] 是归一流切片（几何回填）——
        # 大小写/标点剥除是 ``_text_cov`` 的输入口径，钉归一等价。
        assert occ["text"] == M._norm_chars("Inner1Inner2Outer3")  # noqa: SLF001
        assert occ["chars"] == 18  # noqa: PLR2004 -- 钉字面裹字形数
        assert abs(occ["fraction"] - (1 - 708 / 792)) < 1e-4  # noqa: PLR2004

    def test_mark_dup_occurrence_prefers_later(self, tmp_path: Path) -> None:
        """同 MCID 双 BDC（TOC 重放）→ 可信集取末个——真标在正文页。

        occ1（目录页）标内文本 cov=1.0 反而高于 occ2（0.82）——取末个
        而非最高分，正文真标在后（TOC 在前真标在后实证）。
        """
        en = _mk_pdf(tmp_path / "en.pdf", [[(72, 700, "Alpha intro text")]])
        zh = _write_pdf(
            tmp_path / "zh.pdf",
            [
                [
                    (
                        "BT /F1 10 Tf 1 0 0 1 72 700 Tm "
                        "/TLXC << /MCID 50000 >> BDC (Real) Tj "
                        "0 -20 Td (section heading here 5) Tj "
                        "0 -20 Td (tail) Tj EMC ET"
                    )
                ],
                [
                    (
                        "BT /F1 10 Tf 1 0 0 1 72 700 Tm "
                        "/TLXC << /MCID 50000 >> BDC (Real) Tj "
                        "0 -20 Td (section heading) Tj "
                        "0 -20 Td (x) Tj EMC ET"
                    )
                ],
            ],
        )
        chunks = [
            {"seq": 0, "en": "Alpha intro text", "zh": "Real section heading here"}
        ]
        sp = M.compute_seqpos(en, zh, chunks)
        assert sp["0"]["t"]["page"] == 2  # noqa: PLR2004 -- 钉字面页码

    def test_untrusted_mark_snaps_to_real_pos(self, tmp_path: Path) -> None:
        """裹 2 字形且文本对不上针的孤儿 BDC → ±5 页语义 snap 到真位。"""
        en = _mk_pdf(tmp_path / "en.pdf", [[(72, 700, "Alpha intro text")]])
        zh = _mk_pdf(
            tmp_path / "zh.pdf",
            [
                [(72, 700, "Xx")],  # p1 孤儿 BDC 沉底（标内文本≠针）
                [(72, 700, "True content words here")],  # p2 真文
            ],
            marks={0: (0, 72, 700)},
        )
        chunks = [{"seq": 0, "en": "Alpha intro text", "zh": "True content words here"}]
        sp = M.compute_seqpos(en, zh, chunks)
        assert sp["0"]["t"]["page"] == 2  # noqa: PLR2004
        assert abs(sp["0"]["t"]["x"] - 72 / 612) < 0.001  # noqa: PLR2004

    def test_snap_tail_hit_keeps_mark_pos(self, tmp_path: Path) -> None:
        """snap 命中只裹针腹不裹针头 → 拒换锚，实标兜底留原位。

        a7c5 zh seq1 实证：异文窗 SM 凑分命中（标顶已是真位），命中位
        针头缺席——拖位方向比留标更坏。p2 只放针腹（针头 'found'
        缺席 → 命中实块 b=5 > SKIP），投影起点落在臆造空间。
        """
        en = _mk_pdf(tmp_path / "en.pdf", [[(72, 700, "Alpha intro text")]])
        zh = _write_pdf(
            tmp_path / "zh.pdf",
            [
                [
                    # p1 标裹异文（24 字形 ≥8 + fr<0.92 → 兜底留位）
                    (
                        "BT /F1 10 Tf 1 0 0 1 72 700 Tm "
                        "/TLXC << /MCID 50000 >> BDC "
                        "(A wrapped fragment of twenty) Tj 0 -20 Td EMC ET"
                    ),
                ],
                [
                    # p2 针腹残段：cov 0.89 过阈命中，但针头缺席
                    (
                        "BT /F1 10 Tf 1 0 0 1 72 700 Tm "
                        "(Cleaned open cluster tables via anonymous ftp site) Tj ET"
                    ),
                ],
            ],
        )
        chunks = [
            {
                "seq": 0,
                "en": "Alpha intro text",
                "zh": "Found cleaned open cluster tables via anonymous ftp site",
            }
        ]
        sp = M.compute_seqpos(en, zh, chunks)
        # snap 尾锚被拒 → 实标兜底回 p1 原位
        assert sp["0"]["t"]["page"] == 1
        assert abs(sp["0"]["t"]["fraction"] - (1 - 708 / 792)) < 0.001  # noqa: PLR2004

    def test_dup_occ_embedded_needle_dropped(self, tmp_path: Path) -> None:
        """同 MCID 双 occurrence：引文汤裹标题针的深嵌 occurrence 剔出
        可信集——bbb seq0 实证（标题 verbatim 进引文行，末个优先曾选
        错到引文行）。针起点投影 >LEAD → 只留针起自标的纯 occurrence。"""
        en = _mk_pdf(tmp_path / "en.pdf", [[(72, 700, "Alpha intro text")]])
        zh = _write_pdf(
            tmp_path / "zh.pdf",
            [
                [
                    # y=700 纯 occurrence：标内文本即针
                    (
                        "BT /F1 10 Tf 1 0 0 1 72 700 Tm "
                        "/TLXC << /MCID 50000 >> BDC (The Real Title) Tj "
                        "0 -20 Td EMC ET"
                    ),
                    # y=500 深嵌 occurrence：针 verbatim 嵌在引文行里
                    (
                        "BT /F1 10 Tf 1 0 0 1 72 500 Tm "
                        "/TLXC << /MCID 50000 >> BDC "
                        "(Cited in Doe twenty twenty four The Real Title end) Tj "
                        "0 -20 Td EMC ET"
                    ),
                ],
            ],
        )
        chunks = [{"seq": 0, "en": "Alpha intro text", "zh": "The Real Title"}]
        sp = M.compute_seqpos(en, zh, chunks)
        # 旧末个优先选 y=500 引文行；纯化后只剩 y=700 标题 occurrence
        assert abs(sp["0"]["t"]["fraction"] - (1 - 708 / 792)) < 0.001  # noqa: PLR2004

    def test_running_head_replay_dropped(self, tmp_path: Path) -> None:
        """同 fraction 跨 ≥3 页的 occurrence = 页眉 replay 全剔——
        a7c5 seq0 实证（``\\title`` 宏标被运行头逐页回放，末个优先
        曾把 seq0 锚到末页页眉）。剔光后 seq 落 needle 路找回真位。"""
        en = _mk_pdf(
            tmp_path / "en.pdf",
            [[(72, 700, "Alpha intro text")]],
        )
        zh = _write_pdf(
            tmp_path / "zh.pdf",
            [
                # p1 真标：标题行（fr 0.106）
                [
                    (
                        "BT /F1 10 Tf 1 0 0 1 72 700 Tm "
                        "/TLXC << /MCID 50000 >> BDC (The census title here) Tj "
                        "0 -20 Td EMC ET"
                    ),
                ],
                # p2/p3/p4 页眉 replay：'authors + title' 逐页同 y 重打
                *[
                    [
                        (
                            "BT /F1 10 Tf 1 0 0 1 72 750 Tm "
                            "/TLXC << /MCID 50000 >> BDC "
                            "(Doe twenty four The census title here) Tj "
                            "0 -20 Td EMC ET"
                        ),
                    ]
                    for _p in range(3)
                ],
            ],
        )
        chunks = [{"seq": 0, "en": "Alpha intro text", "zh": "The census title here"}]
        sp = M.compute_seqpos(en, zh, chunks)
        # 旧末个→p4 页眉 fr0.045；剔出后剩 p1 真标 fr0.106
        assert sp["0"]["t"]["page"] == 1
        assert abs(sp["0"]["t"]["fraction"] - (1 - 708 / 792)) < 0.001  # noqa: PLR2004

    def test_single_side_emit(self, tmp_path: Path) -> None:
        """o/t 任一命中即入库——缺侧键缺席而非整条丢（无标记任务实证）。"""
        en = _mk_pdf(
            tmp_path / "en.pdf",
            [[(72, 700, "Alpha intro text"), (72, 660, "Beta body text")]],
        )
        zh = _mk_pdf(
            tmp_path / "zh.pdf",
            [[(72, 700, "Zh alpha text"), (72, 660, "Gamma tail text")]],
        )
        chunks = [
            {"seq": 0, "en": "Alpha intro text", "zh": "Zh alpha text"},
            {"seq": 1, "en": "Beta body text", "zh": ""},  # 仅 o 命中
            {"seq": 2, "en": "", "zh": "Gamma tail text"},  # 仅 t 命中
        ]
        sp = M.compute_seqpos(en, zh, chunks)
        assert set(sp) == {"0", "1", "2"}
        assert "o" in sp["1"]
        assert "t" not in sp["1"]
        assert "t" in sp["2"]
        assert "o" not in sp["2"]

    def test_char_stream_two_column_rows_split(self, tmp_path: Path) -> None:
        """同基线左右栏合并行 → 流内先左栏到底再右栏，各段 bounds 自带 x。"""
        rows = []
        for i in range(10):
            y = 720 - i * 20
            rows.append((60, y, f"Left{i}text"))
            rows.append((340, y, f"Right{i}text"))
        pdf = _mk_pdf(tmp_path / "dual.pdf", [rows])
        stream, bounds, marks = M._char_stream(pdf)  # noqa: SLF001
        assert marks == {}
        assert stream.index("left9text") < stream.index("right0text")
        assert len(bounds) == 20  # noqa: PLR2004 -- 10 合并行 × 2 段
        assert abs(bounds[0][3] - 60 / 612) < 1e-3  # noqa: PLR2004 -- 左栏 x
        assert abs(bounds[10][3] - 340 / 612) < 1e-3  # noqa: PLR2004 -- 右栏 x
        # x1 = 行右缘（x0 + est_w）：左栏行右缘 < 中缝、右栏行右缘近页右
        assert bounds[0][4] < bounds[10][3] < bounds[10][4] <= 1.0

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
        # 二调走缓存（同结果即可——mtime 闸语义在文件存在 + 版本钉）
        sp2 = M.seqpos_for_task(tmp_path, dual)
        assert sp2 == sp

    def test_seqpos_for_task_missing_inputs(self, tmp_path: Path) -> None:
        assert M.seqpos_for_task(tmp_path, {"chunks": []}) is None
        got = M.seqpos_for_task(
            tmp_path, {"chunks": [{"seq": 0, "en": "x", "zh": "y"}]}
        )
        assert got is None
