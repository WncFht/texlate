"""layoutqc 电池 + marks 真值层单测（docs/dev/layoutqc.md §4）。

纯函数面：parse_txlm/env_inventory/compare_marks/_logscan/_plain_scan/
_textblock/_word_overlap_pairs/_lcs/_marks_scan。集成面（xelatex 实编 +
.txlm 发射）走 ``test_marks_e2e``，引擎缺席 skipif。
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from specs._layoutqc import (
    _bbox_scan,
    _lcs,
    _logscan,
    _marks_scan,
    _plain_scan,
    _raster_scan,
    _skeleton,
    _textblock,
    _tier_of,
    _word_overlap_pairs,
    qc_paper,
)
from specs._raster_child import _ranges, _void_frac

from texlate.compile import marks
from texlate.compile.marks import (
    compare_marks,
    env_inventory,
    inject_layout_marks,
    parse_txlm,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------- marks 解析


def _txlm(tmp: Path, lines: list[str]) -> Path:
    p = tmp / "m.txlm"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_parse_txlm_geom_and_dedupe(tmp_path: Path) -> None:
    p = _txlm(
        tmp_path,
        [
            (
                "GEOM pw=614.295pt ph=794.96pt tw=345.0pt th=550.0pt tm=16.0pt "
                "hh=12.0pt hs=18.0pt ho=0.0pt vo=0.0pt oi=62.0pt cs=10.0pt"
            ),
            "MARK figure-1-b x=100 y=200 p=1",
            "MARK figure-1-b x=999 y=999 p=1",  # keep-first
            "MARK figure-1-e x=150 y=250 p=2",
            "garbage line",
        ],
    )
    r = parse_txlm(p)
    assert r["geom"]["pw"] == pytest.approx(614.295)
    assert r["geom"]["hs"] == pytest.approx(18.0)
    assert r["marks"]["figure-1-b@1"]["x"] == 100  # noqa: PLR2004 -- 首个胜（坐标字面量即规格）
    assert r["marks"]["figure-1-e@2"]["p"] == 2  # noqa: PLR2004


def test_parse_txlm_missing(tmp_path: Path) -> None:
    r = parse_txlm(tmp_path / "nope.txlm")
    assert r["marks"] == {}
    assert r["geom"] == {}


# ---------------------------------------------------------------- env 清点


def test_env_inventory_counts(tmp_path: Path) -> None:
    (tmp_path / "a.tex").write_text(
        "\\begin{figure}x\\end{figure}\n% \\begin{table}commented\\end{table}\n"
        "\\begin{wrapfigure}{r}{0.4\\textwidth}y\\end{wrapfigure}\n"
        "\\begin{figure}z\\end{figure}\n",
        encoding="utf-8",
    )
    inv = env_inventory(tmp_path)
    assert inv["figure"] == 2  # noqa: PLR2004
    assert inv["wrapfigure"] == 1
    assert "table" not in inv  # 注释面不可见


# ---------------------------------------------------------------- 注入幂等/闸门


def test_inject_gate_no_envs(tmp_path: Path) -> None:
    (tmp_path / "m.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\ntext only\n\\end{document}\n",
        encoding="utf-8",
    )
    assert inject_layout_marks(tmp_path) == 0


def test_inject_inserts_and_idempotent(tmp_path: Path) -> None:
    (tmp_path / "m.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{figure}x\\end{figure}\n\\end{document}\n",
        encoding="utf-8",
    )
    assert inject_layout_marks(tmp_path) == 1
    text = (tmp_path / "m.tex").read_text(encoding="utf-8")
    assert "TeXlateMark" in text
    assert "txlm@out" in text
    assert inject_layout_marks(tmp_path) == 0  # 哨兵幂等


def test_marks_block_end_hook_bakes_env_name() -> None:
    """env/<name>/end 触发点 \\@currenvir 可能已恢复外层名
    （2609.20793 maketitle 内 tabular 读出 center → \\the\\relax +
    center-0-e 毒化）——end 钩子须注册期烙名，不得自取 currenvir。"""
    block = marks.LAYOUT_MARKS
    assert "\\txlm@e{#1}" in block
    assert "AddToHook{env/#1/end}" in block
    # end 路径不再引用 \@currenvir——只允许出现在 begin 钩子定义里
    end_ctx = block.split("\\def\\txlm@e", 1)[1].split("\\def", 1)[0]
    assert "\\@currenvir" not in end_ctx


# ---------------------------------------------------------------- compare_marks


def _mk_marks(items: list[tuple[str, int, int, int]]) -> dict:
    """[(uid,x,y,p)] → parse_txlm 形（uid@p 键）。"""
    marks = {}
    for uid, x, y, p in items:
        marks[f"{uid}@{p}"] = {"uid": uid, "x": x, "y": y, "p": p}
    return {"marks": marks, "geom": {}, "lines": len(items)}


def test_compare_offpage() -> None:
    zh = _mk_marks([("figure-1-e", -(10**7), 10**8, 1)])
    zh["geom"] = {"pw": 600, "ph": 800}
    out = compare_marks(zh, None)
    assert [f["sig"] for f in out] == ["layout:offpage"]


def test_compare_offpage_inner_env_ignored() -> None:
    """内层 env（tabular/minipage/textblock）可居变换容器，savepos
    报变换前坐标——offpage 不吃它们（2402.07927 tikz 旋转树实证）。"""
    zh = _mk_marks([("tabular-3-b", 75_000_000, 20_000_000, 1)])
    zh["geom"] = {"pw": 600, "ph": 800}
    assert compare_marks(zh, None) == []


def test_compare_drift_and_lost_by_index() -> None:
    # base 两浮体声明序 [fig1, fig2]；zh demote 改名后序 [fig1, fig2]
    base = _mk_marks(
        [
            ("wrapfigure-1-b", 0, 0, 1),
            ("figure-1-b", 0, 0, 1),
            ("wrapfigure-1-e", 0, 0, 2),
            ("figure-1-e", 0, 0, 2),
        ]
    )
    zh = _mk_marks(
        [
            ("figure-1-b", 0, 0, 1),
            ("figure-2-b", 0, 0, 1),
            ("figure-1-e", 0, 0, 5),  # wrapfig→figure-1，漂到 p5
            # figure-2-e 缺席 → lost_element
        ]
    )
    sigs = {f["sig"] for f in compare_marks(zh, base)}
    assert "layout:lost_element" in sigs
    # <3 对：页数比外推——base 10 页 zh 5 页，fig1 base_p=2 期望 p1，
    # 实测 p5 → 漂移 +4 报警
    sigs = {f["sig"] for f in compare_marks(zh, base, zh_pages=5, base_pages=10)}
    assert "layout:float_drift" in sigs
    drift = next(
        f
        for f in compare_marks(zh, base, zh_pages=5, base_pages=10)
        if f["sig"] == "layout:float_drift"
    )
    assert drift["zh_uid"] == "figure-1"
    assert drift["dp"] == 3  # noqa: PLR2004 -- 实测p5-基准p2


def test_compare_drift_median_trend() -> None:
    """≥3 对走 Theil-Sen 趋势：统一平移（dp=-5）下离群者报警；
    比例压缩（zh_p≈0.7·base_p 渐变）不报警——2512.01407 实证。"""
    base = _mk_marks(
        [
            ("figure-1-b", 0, 0, 1),
            ("figure-2-b", 0, 0, 1),
            ("figure-3-b", 0, 0, 1),
            ("figure-4-b", 0, 0, 1),
            ("figure-1-e", 0, 0, 10),
            ("figure-2-e", 0, 0, 11),
            ("figure-3-e", 0, 0, 12),
            ("figure-4-e", 0, 0, 13),
        ]
    )
    zh = _mk_marks(
        [
            ("figure-1-b", 0, 0, 1),
            ("figure-2-b", 0, 0, 1),
            ("figure-3-b", 0, 0, 1),
            ("figure-4-b", 0, 0, 1),
            ("figure-1-e", 0, 0, 5),
            ("figure-2-e", 0, 0, 6),
            ("figure-3-e", 0, 0, 7),
            ("figure-4-e", 0, 0, 2),  # fig4 前移
        ]
    )
    out = compare_marks(zh, base)
    drifts = [f for f in out if f["sig"] == "layout:float_drift"]
    # 斜率=1 平移趋势下 fig4 期望 p8 实测 p2，dev=-6 报警
    assert [f["zh_uid"] for f in drifts] == ["figure-4"]
    assert drifts[0]["expect_p"] == 8  # noqa: PLR2004 -- 斜率1平移趋势期望页
    # 比例压缩面：zh_p = round(0.7 * base_p)，整体趋势合法 → 零报警
    zh2 = _mk_marks(
        [
            ("figure-1-b", 0, 0, 1),
            ("figure-2-b", 0, 0, 1),
            ("figure-3-b", 0, 0, 1),
            ("figure-4-b", 0, 0, 1),
            ("figure-1-e", 0, 0, 7),
            ("figure-2-e", 0, 0, 8),
            ("figure-3-e", 0, 0, 8),
            ("figure-4-e", 0, 0, 9),
        ]
    )
    out2 = compare_marks(zh2, base)
    assert not any(f["sig"] == "layout:float_drift" for f in out2)


def test_compare_order_inversion() -> None:
    base = _mk_marks(
        [
            ("figure-1-b", 0, 0, 1),
            ("figure-2-b", 0, 0, 1),
            ("figure-1-e", 0, 100, 2),
            ("figure-2-e", 0, 50, 3),
        ]
    )
    zh = _mk_marks(
        [
            ("figure-1-b", 0, 0, 1),
            ("figure-2-b", 0, 0, 1),
            ("figure-1-e", 0, 50, 4),
            ("figure-2-e", 0, 100, 2),  # 跨页序倒
        ]
    )
    out = compare_marks(zh, base)
    inv = [f for f in out if f["sig"] == "layout:order_inversion"]
    assert inv
    assert inv[0]["base_order"] != inv[0]["zh_order"]
    assert inv[0]["pairs"] == [("figure-1", "figure-2")]


def test_compare_order_inversion_same_page_ok() -> None:
    """同页倒置 = 双栏栏位伪影（右栏顶 vs 左栏底），不报警。"""
    base = _mk_marks(
        [
            ("figure-1-b", 0, 0, 1),
            ("figure-2-b", 0, 0, 1),
            ("figure-1-e", 0, 100, 2),
            ("figure-2-e", 0, 50, 3),
        ]
    )
    zh = _mk_marks(
        [
            ("figure-1-b", 0, 0, 1),
            ("figure-2-b", 0, 0, 1),
            ("figure-1-e", 0, 50, 2),
            ("figure-2-e", 0, 100, 2),  # 同页序倒
        ]
    )
    out = compare_marks(zh, base)
    assert not any(f["sig"] == "layout:order_inversion" for f in out)


def test_compare_seq_mismatch() -> None:
    base = _mk_marks([("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1)])
    zh = _mk_marks([("figure-1-b", 0, 0, 1)])
    out = compare_marks(zh, base)
    assert any(f["sig"] == "layout:float_seq_mismatch" for f in out)


# ---------------------------------------------------------------- 日志信号


def test_logscan_overfull_and_fit() -> None:
    log = (
        "Overfull \\hbox (60.5pt too wide) in paragraph\n"
        "Overfull \\vbox (12pt too high)\n"
        "TeXlate-Float-Fit: figure-3 shrunk\n"
        "LaTeX Warning: Float too large for page by 20.4pt\n"
        "LaTeX Warning: Float too large for page by 80.4pt\n"
        "LaTeX Warning: Float(s) lost\n"
    )
    f, m = _logscan(log)
    sigs = {x["sig"] for x in f}
    assert m["overfull_n"] == 2  # noqa: PLR2004
    assert m["overfull_max_pt"] == 60.5  # noqa: PLR2004 -- 越界点数即规格
    assert m["overfull_vbox_n"] == 1
    assert m["float_oversize_n"] == 2  # noqa: PLR2004
    assert m["float_oversize_max_pt"] == 80.4  # noqa: PLR2004
    # 单 sig 制：任一命中 ≥60pt 或裸 hit → 升 big 档
    assert sigs == {
        "layout:overfull",
        "layout:float_fit",
        "layout:float_oversize_big",
        "layout:float_lost",
    }


def test_logscan_quiet() -> None:
    f, m = _logscan("This is XeTeX, Version 3.14\nOutput written.\n")
    assert f == []
    assert m["overfull_n"] == 0


# ---------------------------------------------------------------- 文本层


def test_plain_residual_en_and_degenerate() -> None:
    # en 行须互异——同行复现 ≥4 次会被 furniture 剔除；低 frac 轻档
    en = "\n".join(
        f"This is english sentence {i} left untranslated here." for i in range(30)
    )
    zh = "".join(f"第{i}段中文正常翻译内容充实。\n" for i in range(240))
    f, m = _plain_scan(zh + en + "\n")
    assert m["residual_en_lines"] == 30  # noqa: PLR2004 -- 注入行数即规格
    assert any(x["sig"] == "xlat_residual_en" for x in f)


def test_plain_residual_en_noise_floor() -> None:
    """少量合法英文行（作者块/术语/语料例句）不触发——2512.01407 实证
    13 行标题页英文全是 frontmatter+algorithm+表头，阈值提到
    ≥25行且≥2%（或绝对质量 ≥60 行）后不再报警。"""
    # en 行互异——同一行复现 ≥4 次会被 furniture 剔除计不到 13
    en_block = "\n".join(
        f"Author {i} Sac-Morane, Katerina Ioannidou, Some University" for i in range(13)
    )
    text = "中文内容正常翻译，这段文字很长很长很长。\n" * 520 + en_block + "\n"
    f, m = _plain_scan(text)
    assert m["residual_en_lines"] == 13  # noqa: PLR2004 -- 2512.01407 实证行数
    assert not any(x["sig"] == "xlat_residual_en" for x in f)


def test_plain_residual_en_furniture_and_heavy() -> None:
    """归一后全文复现 ≥4 次的行 = 页眉页脚 furniture 剔除（running
    head 每页复现是合法面）；frac≥0.15 升 xlat_residual_en_heavy
    （半译出货档），低 frac 维持轻档。"""
    head = "Journal of Testing Volume 12 Issue 3"
    zh_block = "".join(f"第{i}段中文译文内容各不相同。\n" for i in range(20))
    # running head 每页复现 → furniture 剔除后残英清零
    f, m = _plain_scan((head + "\n" + zh_block) * 6)
    assert m["residual_en_lines"] == 0
    assert not any(x["sig"].startswith("xlat_residual_en") for x in f)
    # 非 furniture 英文行（各只现 1 次）仍计；frac≥0.15 → heavy 档
    en_block = "\n".join(
        f"English leftover sentence number {i} remains here." for i in range(30)
    )
    f2, m2 = _plain_scan(zh_block + en_block + "\n" + zh_block)
    assert m2["residual_en_lines"] == 30  # noqa: PLR2004 -- 注入行数即规格
    heavy = next(x for x in f2 if x["sig"] == "xlat_residual_en_heavy")
    assert heavy["frac"] >= 0.15  # noqa: PLR2004 -- heavy 阈即规格
    # 低 frac（≥0.02 且 ≥25 行）维持轻档
    f3, m3 = _plain_scan(zh_block * 9 + en_block + "\n")
    assert m3["residual_en_lines"] == 30  # noqa: PLR2004
    lite = next(x for x in f3 if x["sig"] == "xlat_residual_en")
    assert lite["frac"] < 0.15  # noqa: PLR2004


def test_plain_degenerate_ngram() -> None:
    # 获胜 n-gram 须含 ≥1 CJK token——纯拉丁/数学记号周期重复是
    # 合法内容（1404.0028 Mandelstam 表 rep=183 实证），点火口径
    # top_ngram_rep 只数 CJK 族 gram，top_ngram_rep_all 记账全量。
    text = " ".join(["abcde"] * 60)  # 非 CJK 5-gram 大量重复
    f, m = _plain_scan(text)
    assert m["top_ngram_rep"] == 0
    assert m["top_ngram_rep_all"] > 20  # noqa: PLR2004
    assert not any(x["sig"] == "vis_degenerate" for x in f)
    text_cjk = " ".join(["这是译文占位重复"] * 60)
    f2, m2 = _plain_scan(text_cjk)
    assert m2["top_ngram_rep"] > 20  # noqa: PLR2004 -- ngram 退化阈即规格
    assert any(x["sig"] == "vis_degenerate" for x in f2)
    # 纯符号连珠（散点 marker ●/○）不算退化——1706.02386 实证
    text3 = "".join(f"第{i}段正常中文内容各不相同。\n" for i in range(30)) + " ".join(
        ["●"] * 400
    )
    _f3, m3 = _plain_scan(text3)
    assert m3["top_ngram_rep"] <= 20  # noqa: PLR2004


def test_plain_fffd() -> None:
    # log 缺席臂：net≥DEGEN_FFFD_FUSE 保险丝仍发（或 tex 字面量佐证）
    f, m = _plain_scan("正常文本 � 出现\n" * 3)
    assert m["fffd"] == 3  # noqa: PLR2004
    assert any(x["sig"] == "vis_degenerate" for x in f)
    # log 在档 + missing=0 + tex 无字面 FFFD → 嵌入图 ToUnicode 伪影，
    # 压（2302.00024 FFFD×39 实证）；missing>0 则 net≤2 也发
    # （1306.2279 人名缺口 net=2 实证）。
    clean_log = "This is XeTeX\nOutput written.\n"
    # 行须互异——同行 CJK 复现会被 ngram 臂抢先点火
    big = "".join(f"第{i}段正常文本 � 出现\n" for i in range(40))
    f2, _m2 = _plain_scan(big, zh_log=clean_log)
    assert not any(x["sig"] == "vis_degenerate" for x in f2)
    miss_log = "Missing character: There is no ć in font\n" * 2
    two = "".join(f"第{i}段正常文本 � 出现\n" for i in range(2))
    f3, m3 = _plain_scan(two, zh_log=miss_log)
    assert m3["missing_chars"] == 2  # noqa: PLR2004
    assert any(x["sig"] == "vis_degenerate" for x in f3)
    f4, _m4 = _plain_scan("正常文本 � 出现\n", zh_log=clean_log, tex_fffd=True)
    assert any(x["sig"] == "vis_degenerate" for x in f4)


def test_plain_broken_refs() -> None:
    """断链引用 ?? run——每 run 计一位点；≥8 位点报警（2505.21476
    正文 646 ?? 字符实证）。修辞双问号/全角？？不过阈。"""
    text = "正常中文正文。\n" * 10 + "见文献 [??] 与图 ??，式 (??)。\n" * 5
    f, m = _plain_scan(text)
    assert m["broken_refs"] == 15  # noqa: PLR2004 -- 5 行 x 3 位点
    assert any(x["sig"] == "xlat_broken_refs" for x in f)
    # 偶发修辞 ??/??? 凑不满位点阈；全角？？天然不匹配
    f2, m2 = _plain_scan("真的吗?? 不对??? 是全角？？问号。\n" * 3)
    assert m2["broken_refs"] == 6  # noqa: PLR2004 -- 3 行 x 2 run
    assert not any(x["sig"] == "xlat_broken_refs" for x in f2)
    # natbib 面：括内单 (?) 也是断链位点（2602.09703 实证）
    f3, m3 = _plain_scan("Shami Corpus (?) 与 UFAL (?)、DoDa (?)。\n" * 4)
    assert m3["broken_refs"] == 12  # noqa: PLR2004 -- 4 行 x 3 位点
    assert any(x["sig"] == "xlat_broken_refs" for x in f3)


def test_plain_periodic_placeholder() -> None:
    """行内短周期连珠 = CJK 占位/mock 译文签名——2609.19244 实证
    top_rep=46 被 running-head 放阈放走，行内连珠才是真签名。
    发射口径=CJK 单元行数 ≥20（mock 洪水 ≥377；图区刻度/括号
    stretch 的非 CJK 连珠 ≤16 且不计 CJK 面，0928 簇裁定）。"""
    spam = "这是译文这是译文这是译文这是译文这是译文这是译文这是译文"
    text = "正常中文正文段落。\n" * 5 + (spam + "\n") * 4 + "又一段正常内容。\n" * 5
    f, m = _plain_scan(text)
    assert m["degen_periodic_lines"] == 4  # noqa: PLR2004
    assert m["degen_periodic_cjk"] == 4  # noqa: PLR2004
    assert not any(x["sig"] == "vis_degenerate" for x in f)  # <20 行阈
    flood = (spam + "\n") * 25
    f2, m2 = _plain_scan(flood)
    assert m2["degen_periodic_cjk"] == 25  # noqa: PLR2004
    assert any(x["sig"] == "vis_degenerate" for x in f2)
    # 非 CJK 周期单元（括号 stretch / 图区刻度）不计入发射口径
    glyph = "looooooooooooooooooooooooooooooooooooon\n"
    _f3, m3 = _plain_scan("正常中文段落。\n" * 3 + glyph * 30)
    assert m3["degen_periodic_cjk"] == 0
    assert not any(x["sig"] == "vis_degenerate" for x in _f3)
    # 单两行修辞性重复不过阈；无词字符单元（……/====）不算
    legit = (
        "正常段落。\n" * 6
        + "他说哈哈哈哈哈哈哈哈哈哈地笑。\n"
        + "分隔 ………………………… 与 ======== 行。\n"
        + "收尾。\n" * 4
    )
    _f4, m4 = _plain_scan(legit)
    assert m4["degen_periodic_lines"] <= 2  # noqa: PLR2004


# ---------------------------------------------------------------- 几何


def test_textblock_geom_vs_fallback() -> None:
    # A4 真值：\paperwidth=597.51pt vs mediabox 595.28bp——pt→bp 换算
    # 后等价，geom 分支命中（letter=614.295pt/612bp 同理）。
    geom = {
        "pw": 597.508,
        "ph": 845.047,
        "tw": 345.0,
        "th": 550.0,
        "tm": 16.0,
        "hh": 12.0,
        "hs": 18.0,
        "ho": 0.0,
        "vo": 0.0,
        "oi": 62.0,
        "cs": 10.0,
    }
    pt2bp = 72.0 / 72.27
    left, t, r, _b = _textblock(geom, 595.28, 841.89)
    assert left == pytest.approx((72.27 + 62.0) * pt2bp, abs=0.01)
    assert t == pytest.approx((72.27 + 16 + 12 + 18) * pt2bp, abs=0.01)
    assert r == pytest.approx(left + 345.0 * pt2bp, abs=0.01)
    # 纸型真失配（letter 稿出 A4 mediabox）→ fallback 92% 页框
    l2, _t2, _r2, _b2 = _textblock(geom, 612.0, 792.0)
    assert l2 == pytest.approx(612.0 * 0.04)


def test_bbox_paper_mismatch_units() -> None:
    letter_geom = {"pw": 614.295, "ph": 794.97}
    ok, _m = _bbox_scan([{"w": 612.0, "h": 792.0, "words": []}], letter_geom, {})
    assert not any(f["sig"] == "layout:paper_mismatch" for f in ok)
    bad, _m = _bbox_scan([{"w": 595.28, "h": 841.89, "words": []}], letter_geom, {})
    assert any(f["sig"] == "layout:paper_mismatch" for f in bad)


def test_margin_breach_ascii_run_exempt() -> None:
    """≥4 词 x 序连续 ASCII 段的越界豁免（verbatim 附录/列表行溢出
    归 en 原文同形）；双栏邻栏 CJK 不拖回（CJK 词天然断跑）、
    不足 4 词的短英文段仍计。"""
    # geom={} → fallback 92% 框：r≈587.5，x1>591.5 的词越右界
    ascii_run = [(595.0 + i * 20, 400, 610.0 + i * 20, 412, f"w{i}") for i in range(4)]
    f, _m = _bbox_scan([{"w": 612.0, "h": 792.0, "words": ascii_run}], {}, {})
    assert not any(x["sig"] == "geo_margin_breach" for x in f)
    # 同横带另有 CJK 词（双栏左栏 zh/右栏 en 列表形）不拖回——
    # ASCII 跑自成一段仍豁免
    mixed = [(50, 400, 80, 412, "中文"), *ascii_run]
    f2, _m2 = _bbox_scan([{"w": 612.0, "h": 792.0, "words": mixed}], {}, {})
    assert not any(x["sig"] == "geo_margin_breach" for x in f2)
    # 3 词短跑不足阈 → 全计
    f3, _m3 = _bbox_scan([{"w": 612.0, "h": 792.0, "words": ascii_run[:3]}], {}, {})
    breach = [x for x in f3 if x["sig"] == "geo_margin_breach"]
    assert len(breach) == 1
    assert breach[0]["words"] == 3  # noqa: PLR2004
    # CJK 词嵌跑内断跑——4 越界英文词劈成两条 2 词短跑全计（夹缝
    # 的 CJK 词自身越界也照计）
    broken = [*ascii_run[:2], (632, 400, 640, 412, "中"), *ascii_run[2:]]
    f4, _m4 = _bbox_scan([{"w": 612.0, "h": 792.0, "words": broken}], {}, {})
    breach4 = [x for x in f4 if x["sig"] == "geo_margin_breach"]
    assert len(breach4) == 1
    assert breach4[0]["words"] == 5  # noqa: PLR2004


def test_plain_residual_en_refs_tail_cut() -> None:
    en_ref = "Smith J and Doe K. Some english reference entry here."
    text = "正常中文正文。\n" * 8 + "References\n" + (en_ref + "\n") * 30
    f, m = _plain_scan(text)
    assert m["residual_en_lines"] == 0
    assert m["en_tail_cut"] == 8  # noqa: PLR2004 -- 正文 8 行后参考尾截断
    assert not any(x["sig"] == "xlat_residual_en" for x in f)


def test_word_overlap_pairs() -> None:
    # 两行部分 x 重叠、y 中心差 > 半高 → 跨行重叠对（token >4 字符且
    # x 互不包含——逃逸堆叠豁免；en×en 须 base 侧 cjk_gate=False 才计）
    words = [
        (100, 100, 160, 112, "alpha"),
        (120, 106, 180, 120, "bravo"),  # 与 alpha 跨行重叠（cy 差 7 > 6）
        (300, 100, 360, 112, "charlie"),  # 远离
    ]
    assert _word_overlap_pairs(words, cjk_gate=False) >= 1
    assert _word_overlap_pairs(words) == 0  # en×en 被 zh 侧闸剔
    # 同行相邻词不重叠
    same_line = [(100, 100, 160, 112, "alpha"), (162, 100, 240, 112, "bravo")]
    assert _word_overlap_pairs(same_line, cjk_gate=False) == 0


def test_word_overlap_math_symbols_skipped() -> None:
    """数学符号 token（≤2 字符纯符号）不参与重叠对——堆叠公式
    \\stackrel{iid}{\\sim} 的 iid×∼ 对就是这么炸出来的；CJK 是
    alnum 不受影响，真重叠仍计。"""
    words = [
        (100, 100, 160, 112, "iid"),
        (100, 107, 160, 119, "∼"),  # 与 iid 跨行重叠但符号 → 剔
        (100, 107, 160, 119, "±"),
        (100, 107, 160, 119, "→"),
    ]
    assert _word_overlap_pairs(words) == 0
    cjk = [(100, 100, 160, 112, "中"), (100, 107, 160, 119, "文")]
    assert _word_overlap_pairs(cjk) == 1


def test_lcs_and_skeleton() -> None:
    assert _lcs(["a", "b", "c"], ["a", "x", "c"]) == 2  # noqa: PLR2004
    sk = _skeleton("见文献 [12] 与 arXiv:2401.01234，页码 3.14")
    assert "[12]" in sk
    assert any("arXiv" in s for s in sk)


# ---------------------------------------------------------------- marks_scan 记账


def test_marks_scan_coverage_and_dropped(tmp_path: Path) -> None:
    splice = tmp_path / "splice"
    src = tmp_path / "src"
    splice.mkdir()
    src.mkdir()
    (splice / "m.tex").write_text(
        "\\begin{figure}a\\end{figure}\\begin{figure}b\\end{figure}", encoding="utf-8"
    )
    (src / "m.tex").write_text(
        "\\begin{figure}a\\end{figure}\\begin{wrapfigure}w\\end{wrapfigure}",
        encoding="utf-8",
    )
    tx = _txlm(
        splice,
        [
            "GEOM pw=600pt ph=800pt",
            "MARK figure-1-b x=1 y=1 p=1",
            "MARK figure-1-e x=1 y=1 p=1",
            "MARK figure-2-b x=1 y=1 p=1",
            "MARK figure-2-e x=1 y=1 p=1",
        ],
    )
    f, _m = _marks_scan(tx, None, splice, src)
    sigs = {x["sig"] for x in f}
    # wrapfigure demote→figure（figure 计数 1→2 增长）→ 非 dropped
    assert "layout:dropped_env" not in sigs
    # splice envs 全部有 marks → 无 coverage gap
    assert "layout:marks_coverage" not in sigs


def test_marks_scan_dropped_env(tmp_path: Path) -> None:
    splice = tmp_path / "splice"
    src = tmp_path / "src"
    splice.mkdir()
    src.mkdir()
    (splice / "m.tex").write_text("\\begin{figure}a\\end{figure}", encoding="utf-8")
    (src / "m.tex").write_text(
        "\\begin{figure}a\\end{figure}\\begin{table}t\\end{table}", encoding="utf-8"
    )
    tx = _txlm(
        splice,
        [
            "GEOM pw=600pt ph=800pt",
            "MARK figure-1-b x=1 y=1 p=1",
            "MARK figure-1-e x=1 y=1 p=1",
        ],
    )
    f, _m = _marks_scan(tx, None, splice, src)
    dropped = next(x for x in f if x["sig"] == "layout:dropped_env")
    assert dropped["envs"] == {"table": 1}


def test_marks_absent(tmp_path: Path) -> None:
    f, _m = _marks_scan(tmp_path / "none.txlm", None, None, None)
    assert f == [{"sig": "layout:marks_absent", "side": "zh"}]


def test_marks_absent_base_silent(tmp_path: Path) -> None:
    """base_txlm=None（未建对照臂）不出 finding——臂编不编是参数
    选择（base=onfail 时 clean 不建臂）只记 metrics；但臂已建而
    txlm 缺席/零 mark 仍是注入链断，照报；zh 缺席仍是真洞。"""
    d = tmp_path / "d"
    d.mkdir()
    tx = _txlm(
        d,
        [
            "GEOM pw=600pt ph=800pt",
            "MARK figure-1-b x=1 y=1 p=1",
            "MARK figure-1-e x=1 y=1 p=1",
        ],
    )
    f, m = _marks_scan(tx, None, None, None)
    assert not any(x["sig"] == "layout:marks_absent" for x in f)
    assert m["base_marks"] == 0
    # 臂建而零 mark → 注入链断报警
    btx = _txlm(tmp_path, ["GEOM pw=600pt ph=800pt"])
    f2, m2 = _marks_scan(tx, btx, None, None)
    assert any(x["sig"] == "layout:marks_absent" and x["side"] == "base" for x in f2)
    assert m2["base_marks"] == 0
    # 臂建而 txlm 缺席 → 同口径报警
    f3, _m3 = _marks_scan(tx, tmp_path / "absent.txlm", None, None)
    assert any(x["sig"] == "layout:marks_absent" and x["side"] == "base" for x in f3)


# ---------------------------------------------------------------- tier 门档


def test_tier_classification() -> None:
    assert _tier_of([]) == "clean"
    assert _tier_of([{"sig": "layout:float_fit"}]) == "clean"  # INFO 不抬档
    assert _tier_of([{"sig": "layout:marks_absent"}]) == "clean"  # 存量 INFO
    # marks_era（双臂注入编译）下 marks_absent 升 WARN
    assert _tier_of([{"sig": "layout:marks_absent"}], marks_era=True) == "warn"
    assert _tier_of([{"sig": "xlat_residual_en"}]) == "warn"
    assert _tier_of([{"sig": "some_future_sig"}]) == "warn"  # 未分类保守 WARN
    assert _tier_of([{"sig": "xlat_residual_en"}, {"sig": "vis_degenerate"}]) == "hard"
    assert _tier_of([{"sig": "layout:no_pdf"}]) == "hard"
    assert _tier_of([{"sig": "layout:pdf_corrupt"}]) == "hard"


# ---------------------------------------------------------------- raster 对拍


def _pg(**kw: float) -> dict:
    d = {
        "ink": 0.05,
        "dark_cc": 0.01,
        "tofu": 0,
        "rules": 0,
        "void_frac": 0.0,
        "void_int": 0.0,
        "cols": 2,
    }
    d.update(kw)
    return d


def test_raster_tofu_cluster() -> None:
    f, m = _raster_scan([_pg(tofu=2), _pg(tofu=7)], None)
    sigs = {x["sig"] for x in f}
    assert "vis_tofu_box" in sigs
    tofu = next(x for x in f if x["sig"] == "vis_tofu_box")
    assert tofu["pages"] == [2]  # p1 只有 2 框不够簇阈
    assert m["tofu_pages"] == [2]


def test_raster_table_rules_lost() -> None:
    zh = [_pg(rules=1), _pg(rules=1)]
    base = [_pg(rules=6), _pg(rules=5)]
    f, m = _raster_scan(zh, base)
    lost = [x for x in f if x["sig"] == "geo_table_lost"]
    assert lost
    assert lost[0]["zh"] == 2  # noqa: PLR2004 -- 2 vs 11 <60%
    assert m["rules_base"] == 11  # noqa: PLR2004
    # base 少规则（<3）不构成对拍面 → 不报
    f2, _m2 = _raster_scan(zh, [_pg(rules=2), _pg(rules=0)])
    assert not any(x["sig"] == "geo_table_lost" for x in f2)
    # 同规则数（图内轴线两臂同构）→ 不报
    f3, _m3 = _raster_scan(zh, [_pg(rules=1), _pg(rules=1)])
    assert not any(x["sig"] == "geo_table_lost" for x in f3)


def test_raster_ink_drop_profile() -> None:
    """逐页墨量回归：矢量图掉图页（ink 崩到 base 邻窗 35% 下）报警；
    ±2 页窗吃 reflow 错位，末页豁免。"""
    zh = [_pg(ink=0.3), _pg(ink=0.02), _pg(ink=0.3)]
    base = [_pg(ink=0.3), _pg(ink=0.32), _pg(ink=0.28)]
    f, _m = _raster_scan(zh, base)
    drop = [x for x in f if x["sig"] == "regress_ink_profile"]
    assert drop
    assert drop[0]["pages"] == [2]
    # 末页 ink 崩不警（收尾留白合法）
    zh2 = [_pg(ink=0.3), _pg(ink=0.01)]
    f2, _m2 = _raster_scan(zh2, base[:2])
    assert not any(x["sig"] == "regress_ink_profile" for x in f2)
    # base 邻窗本身稀墨（<8%）不报——整体轻墨稿无局部洞语义
    zh3 = [_pg(ink=0.02), _pg(ink=0.03)]
    base3 = [_pg(ink=0.05), _pg(ink=0.04)]
    f3, _m3 = _raster_scan(zh3, base3)
    assert not any(x["sig"] == "regress_ink_profile" for x in f3)


def test_raster_ink_drop_self_outlier_gate() -> None:
    """zh 内部离群闸：比 base 邻窗稀、但在自身文档内非离群（≥ 全 zh
    页中位数×0.25）的重排错位页不再报；真离群低点仍报。"""
    base = [_pg(ink=0.3), _pg(ink=0.3), _pg(ink=0.3)]
    # 整体轻墨稿：中位 0.04，p2=0.02 < 0.3×0.35 但 ≥ 0.04×0.25 → 非离群
    zh = [_pg(ink=0.04), _pg(ink=0.02), _pg(ink=0.04)]
    f, _m = _raster_scan(zh, base)
    assert not any(x["sig"] == "regress_ink_profile" for x in f)
    # 中位 0.3 稿中 p2=0.02 < 0.075 → 自身离群 + 比 base 稀 → 报
    zh2 = [_pg(ink=0.3), _pg(ink=0.02), _pg(ink=0.3)]
    f2, _m2 = _raster_scan(zh2, base)
    drop = [x for x in f2 if x["sig"] == "regress_ink_profile"]
    assert len(drop) == 1
    assert drop[0]["pages"] == [2]


def test_raster_ink_blob_suppressed_on_image_pages() -> None:
    """含位图页的大 dark CC 是内容（星系格/照片）非泼溅——
    0812.1022 银河格实证；无位图页仍报警。"""
    pages = [_pg(dark_cc=0.43)]
    f, _m = _raster_scan(pages, None, {1: 3})
    assert not any(x["sig"] == "vis_ink_blob" for x in f)
    f2, _m2 = _raster_scan(pages, None, {})
    assert any(x["sig"] == "vis_ink_blob" for x in f2)


def test_raster_child_void_frac_maxrect() -> None:
    """_void_frac 直方图最大矩形：旧栈存索引、弹出高度不回传，
    有墨页也虚报 1.0（2403.05234 实证）。(左界,高) 对栈修复验证。"""

    class _FakeImg:
        def __init__(self, white: list[list[bool]]) -> None:
            self._w = white

        @property
        def size(self) -> tuple[int, int]:
            return (len(self._w[0]), len(self._w))

        def load(self) -> object:
            w = self._w

            class _Px:
                def __getitem__(self, xy: tuple[int, int]) -> int:
                    x, y = xy
                    return 255 if w[y][x] else 0

            return _Px()

    rows = [[True] * 20 for _ in range(20)]
    for y in range(8, 12):
        for x in range(8, 12):
            rows[y][x] = False  # 居中 4x4 墨块
    vf, vi, vink = _void_frac(_FakeImg(rows))
    assert vf == pytest.approx(0.4)  # 最大白矩形=全宽条带 20x8
    assert vi == 0.0  # 白区连通贴边→内部洞为零
    assert vink == 0.0  # 无内部白块 → 墨率零
    rows2 = [[True] * 20 for _ in range(20)]
    rows2[10][10] = False  # 单墨像素：满行带或满列带
    vf2, _vi2, vink2 = _void_frac(_FakeImg(rows2))
    assert vf2 == pytest.approx(0.5)  # 20x10=200/400，绝不虚报 1.0
    assert vink2 == 0.0
    # 框内墨率口径：墨框封出的白腔装着内容 → 内腔 bbox 内墨率>0
    # （tcolorbox/listing 封印框非掉图洞，0928 blank_void 簇裁定）。
    rows3 = [[True] * 20 for _ in range(20)]
    for k in range(6, 14):
        rows3[6][k] = rows3[13][k] = rows3[k][6] = rows3[k][13] = False  # 8x8 墨框
    for y in range(9, 11):
        for x in range(9, 11):
            rows3[y][x] = False  # 框内 2x2 墨块=内容
    _vf3, vi3, vink3 = _void_frac(_FakeImg(rows3))
    assert vi3 > 0  # 内腔是最大内部白块
    assert vink3 > 0  # 其 bbox 内带着 2x2 内容墨


def test_raster_child_page_ranges() -> None:
    assert _ranges([3, 4, 5, 9, 11, 12]) == [(3, 5), (9, 9), (11, 12)]
    assert _ranges([]) == []


def test_qc_paper_contract_no_pdf(tmp_path: Path) -> None:
    """空目录跑 qc_paper：no_pdf→hard、tier/flagged/sig_counts
    三契约键在位（§11.2）。"""
    splice = tmp_path / "splice"
    splice.mkdir()
    (splice / "m.tex").write_text("x", encoding="utf-8")
    qc = qc_paper(splice_dir=splice, main_rel="m.tex")
    assert qc["qc_tier"] == "hard"  # layout:no_pdf
    assert qc["sig_counts"]["layout:no_pdf"] == 1
    assert qc["flagged_pages"] == []
    assert "marks" in qc["metrics"]


# ------------------------------------------------------------- 批次2豁免/降级


def test_logscan_output_routine_accept() -> None:
    """\\output 例程内溢出（页眉页脚家具 hbox + 超高 vbox）→
    layout:overfull_output INFO 记账不抬档（overfull 簇 0928
    accept_as_is：0905.0081/2602.19447 headfoot、2212.00138/
    2609.19695 超高 vbox 实证）；同格正文域溢出仍走
    layout:overfull（1306.0005 figure 段分层实证）。"""
    log = (
        "Overfull \\hbox (213.80302pt too wide) has occurred "
        "while \\output is active\n"
        "Overfull \\vbox (722.7pt too high) has occurred "
        "while \\output is active []\n"
        "Overfull \\vbox (42.0pt too high) has occurred "
        "while \\output is active []\n"
    )
    f, m = _logscan(log)
    assert {x["sig"] for x in f} == {"layout:overfull_output"}
    out = f[0]
    assert out["n"] == 3  # noqa: PLR2004 -- (h,213.8)+(v,722.7)+(v,42.0)
    assert out["vbox_n"] == 2  # noqa: PLR2004
    assert out["max_pt"] == 722.7  # noqa: PLR2004
    assert m["overfull_n"] == 3  # noqa: PLR2004 -- metrics 全量记账
    assert m["overfull_output_n"] == 3  # noqa: PLR2004
    assert _tier_of(f) == "clean"  # INFO 不抬 dirty 档
    # 混合格：正文溢出 + 例程家具——两 sig 分层各记
    f2, _m2 = _logscan(
        "Overfull \\hbox (55.0pt too wide) in paragraph at lines 12--13\n" + log
    )
    sigs = {x["sig"] for x in f2}
    assert sigs == {"layout:overfull", "layout:overfull_output"}
    body = next(x for x in f2 if x["sig"] == "layout:overfull")
    assert body["n"] == 1
    assert _tier_of(f2) == "warn"  # 正文溢出仍是 WARN 面


def test_logscan_output_active_no_cross_tag() -> None:
    """相邻条目防误染：正文条目 160 字符窗口内出现下一条
    ``while \\output is active`` 时不得吞并进例程面——语境段在
    下一条 Overfull 起头截断。"""
    log = (
        "Overfull \\hbox (60.0pt too wide) in paragraph at lines 9--10\n"
        "Overfull \\hbox (62.5pt too wide) has occurred\n"
        "while \\output is active\n"  # 79 列折行变体
    )
    f, _m = _logscan(log)
    sigs = {x["sig"] for x in f}
    assert sigs == {"layout:overfull", "layout:overfull_output"}
    assert next(x for x in f if x["sig"] == "layout:overfull")["n"] == 1


def test_tier_batch2_demoted_sigs() -> None:
    # 0928 裁定 demote：trim-size special 单页偏离 + accept_as_is
    assert _tier_of([{"sig": "layout:paper_mismatch"}]) == "clean"
    assert _tier_of([{"sig": "layout:overfull_output"}]) == "clean"


def test_raster_void_bitmap_page_exempt() -> None:
    """位图图版页的白色内腔（提示词截图白区）非掉图洞——2509.05091
    实证：void_int 过阈+void_ink=0 但页含位图 → 压；无位图同形仍报
    （outlines-only 真洞簇）。"""
    pages = [_pg(), _pg(void_int=0.5, void_ink=0.0), _pg()]
    f, _m = _raster_scan(pages, None, {2: 1})
    assert not any(x["sig"] == "vis_void" for x in f)
    f2, _m2 = _raster_scan(pages, None, {})
    assert any(x["sig"] == "vis_void" and x["page"] == 2 for x in f2)  # noqa: PLR2004


def test_verso_struct_head_numbered_isbn() -> None:
    """编号章头/colophon 页首（_STRUCT_HEAD_RX 0928 扩展：1503.00131
    的 ``2. 预备知识``/``ISBN …`` 五族）→ 空页豁免；普通页首不免。"""
    body = "正文内容足够长的一页文字。\n"  # 须 ≥EMPTY_PAGE_CHARS 免入空页计
    text = "\fISBN 978-88-95767-78-9\n版权信息页若干说明文字。\f" + body
    _f, m = _plain_scan(text)
    assert m["empty_pages_eff"] == 0
    text2 = "\f2. 预备知识\n本章从基础概念开始讲起。\f" + body
    _f2, m2 = _plain_scan(text2)
    assert m2["empty_pages_eff"] == 0
    text3 = "\f随便一段正文开头叙述背景若干文字。\f" + body
    _f3, m3 = _plain_scan(text3)
    assert m3["empty_pages_eff"] == 1


def test_verso_doc_title_head() -> None:
    """标题页首行即 \\title 本身——页首 squash 与 doc_title 互为
    前缀即 verso（1503.00131 无关键字标题头实证）；doc_title 缺席
    或错配不免。"""
    title = "整体双曲时空上阿贝尔规范理论中的局域性"
    text = (
        "封面占位内容足够的标题页文字。\f第二页内容页文字也足够。\f\f"
        + title
        + "\n作者某某与单位信息。\n"
    )
    _f, m = _plain_scan(text, doc_title=title)
    assert m["empty_pages_eff"] == 0
    _f2, m2 = _plain_scan(text)  # 无 doc_title → 无豁免证据
    assert m2["empty_pages_eff"] == 1
    _f3, m3 = _plain_scan(text, doc_title="完全无关的另一篇标题文本")
    assert m3["empty_pages_eff"] == 1


def test_verso_frontmatter_twoside() -> None:
    """twoside 前 10 页空页=frontmatter 全域 verso 授权（1812.00314
    roman 偏移击穿 PDF 序数判实证）；同页位 oneside 不豁免，
    frontmatter 域外（≥10）非 verso 位也不免。"""
    pages = ["封面内容页文字若干。\n", "出版信息页文字若干。\n", ""] + [
        f"第{i}页正文内容若干文字。\n" for i in range(10)
    ]
    text_twoside = "\f".join(pages)
    _f, m = _plain_scan(text_twoside, twoside=True)
    assert m["empty_pages_eff"] == 0  # pi=2 < FRONTMATTER_PAGES
    _f2, m2 = _plain_scan(text_twoside, twoside=False)
    assert m2["empty_pages_eff"] == 1  # oneside 无 frontmatter 授权
    # pi=10 出 frontmatter 域 + 序数非偶 + 页首非结构 → 计
    pages2 = [f"第{i}页正文内容若干文字。\n" for i in range(10)] + [
        "",
        "普通续页内容若干文字。\n",
    ]
    _f3, m3 = _plain_scan("\f".join(pages2), twoside=True)
    assert m3["empty_pages_eff"] == 1


def test_verso_titlepage_blank() -> None:
    """p2 空 + p1 非空 → 扉页后 verso（plain/raster 两臂同口径，
    1503.00131 p2 实证）；p1 亦空时此臂不发。"""
    _f, m = _plain_scan("封面文字内容足够长。\f\f第三页正文内容足够多。\n")
    assert m["empty_pages_eff"] == 0
    _f2, m2 = _plain_scan("\f\f第三页正文内容足够多。\n")
    assert m2["empty_pages_eff"] == 2  # noqa: PLR2004 -- p1 亦空臂不发，两空页全计


def test_raster_blank_doc_title_head() -> None:
    """raster 侧同证：零墨页下一非白页首行=doc_title → verso 压；
    doc_title 缺席 → vis_blank_page 照报。"""
    pages = [_pg(ink=0.0005), _pg()]
    txts = ["", "整体双曲时空上阿贝尔规范理论中的局域性\n作者某某与单位。\n"]
    f, _m = _raster_scan(
        pages,
        None,
        zh_text_pages=txts,
        doc_title="整体双曲时空上阿贝尔规范理论中的局域性",
    )
    assert not any(x["sig"] == "vis_blank_page" for x in f)
    f2, _m2 = _raster_scan(pages, None, zh_text_pages=txts)
    assert any(x["sig"] == "vis_blank_page" for x in f2)


# ---------------------------------------------------------------- 集成（xelatex）


@pytest.mark.skipif(not shutil.which("xelatex"), reason="xelatex 缺席")
def test_marks_e2e_real_compile(tmp_path: Path) -> None:
    """实编：注入→xelatex→.txlm 含 GEOM+MARK，页码 1-based。"""
    # 尾部必须有实文本——浮体独占末页 galley 时 b whatsit 不触发
    # page builder 会丢 b-mark（marks.py compare 改走 env_sequence
    # 声明序兜底此边例）
    (tmp_path / "m.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "p1 text \\newpage\n"
        "\\begin{figure}[b]\\rule{2cm}{2cm}\\end{figure}\n"
        "trailing text\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    assert inject_layout_marks(tmp_path) == 1
    r = subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [shutil.which("xelatex") or "xelatex", "-interaction=nonstopmode", "m.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert r.returncode == 0
    res = parse_txlm(tmp_path / "m.txlm")
    assert res["geom"].get("pw")
    e = res["marks"].get("figure-1-e@2") or res["marks"].get("figure-1-e@1")
    assert e is not None
    assert e["p"] in (1, 2)
    # b/e 同 uid 成对
    assert any(k.startswith("figure-1-b@") for k in res["marks"])
