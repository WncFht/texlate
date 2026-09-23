"""layoutqc 电池 + marks 真值层单测（docs/dev/layoutqc-plan.md §4）。

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
    p = _txlm(tmp_path, [
        ("GEOM pw=614.295pt ph=794.96pt tw=345.0pt th=550.0pt tm=16.0pt "
         "hh=12.0pt hs=18.0pt ho=0.0pt vo=0.0pt oi=62.0pt cs=10.0pt"),
        "MARK figure-1-b x=100 y=200 p=1",
        "MARK figure-1-b x=999 y=999 p=1",  # keep-first
        "MARK figure-1-e x=150 y=250 p=2",
        "garbage line",
    ])
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
        encoding="utf-8")
    inv = env_inventory(tmp_path)
    assert inv["figure"] == 2  # noqa: PLR2004
    assert inv["wrapfigure"] == 1
    assert "table" not in inv  # 注释面不可见


# ---------------------------------------------------------------- 注入幂等/闸门


def test_inject_gate_no_envs(tmp_path: Path) -> None:
    (tmp_path / "m.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\ntext only\n"
        "\\end{document}\n", encoding="utf-8")
    assert inject_layout_marks(tmp_path) == 0


def test_inject_inserts_and_idempotent(tmp_path: Path) -> None:
    (tmp_path / "m.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{figure}x\\end{figure}\n\\end{document}\n",
        encoding="utf-8")
    assert inject_layout_marks(tmp_path) == 1
    text = (tmp_path / "m.tex").read_text(encoding="utf-8")
    assert "TeXlateMark" in text
    assert "txlm@out" in text
    assert inject_layout_marks(tmp_path) == 0  # 哨兵幂等


# ---------------------------------------------------------------- compare_marks


def _mk_marks(items: list[tuple[str, int, int, int]]) -> dict:
    """[(uid,x,y,p)] → parse_txlm 形（uid@p 键）。"""
    marks = {}
    for uid, x, y, p in items:
        marks[f"{uid}@{p}"] = {"uid": uid, "x": x, "y": y, "p": p}
    return {"marks": marks, "geom": {}, "lines": len(items)}


def test_compare_offpage() -> None:
    zh = _mk_marks([("figure-1-e", -10**7, 10**8, 1)])
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
    base = _mk_marks([
        ("wrapfigure-1-b", 0, 0, 1), ("figure-1-b", 0, 0, 1),
        ("wrapfigure-1-e", 0, 0, 2), ("figure-1-e", 0, 0, 2),
    ])
    zh = _mk_marks([
        ("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1),
        ("figure-1-e", 0, 0, 5),  # wrapfig→figure-1，漂到 p5
        # figure-2-e 缺席 → lost_element
    ])
    sigs = {f["sig"] for f in compare_marks(zh, base)}
    assert "layout:lost_element" in sigs
    # <3 对：页数比外推——base 10 页 zh 5 页，fig1 base_p=2 期望 p1，
    # 实测 p5 → 漂移 +4 报警
    sigs = {f["sig"] for f in compare_marks(
        zh, base, zh_pages=5, base_pages=10)}
    assert "layout:float_drift" in sigs
    drift = next(f for f in compare_marks(
        zh, base, zh_pages=5, base_pages=10)
        if f["sig"] == "layout:float_drift")
    assert drift["zh_uid"] == "figure-1"
    assert drift["dp"] == 3  # noqa: PLR2004 -- 实测p5-基准p2


def test_compare_drift_median_trend() -> None:
    """≥3 对走 Theil-Sen 趋势：统一平移（dp=-5）下离群者报警；
    比例压缩（zh_p≈0.7·base_p 渐变）不报警——2512.01407 实证。"""
    base = _mk_marks([
        ("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1),
        ("figure-3-b", 0, 0, 1), ("figure-4-b", 0, 0, 1),
        ("figure-1-e", 0, 0, 10), ("figure-2-e", 0, 0, 11),
        ("figure-3-e", 0, 0, 12), ("figure-4-e", 0, 0, 13),
    ])
    zh = _mk_marks([
        ("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1),
        ("figure-3-b", 0, 0, 1), ("figure-4-b", 0, 0, 1),
        ("figure-1-e", 0, 0, 5), ("figure-2-e", 0, 0, 6),
        ("figure-3-e", 0, 0, 7), ("figure-4-e", 0, 0, 2),  # fig4 前移
    ])
    out = compare_marks(zh, base)
    drifts = [f for f in out if f["sig"] == "layout:float_drift"]
    # 斜率=1 平移趋势下 fig4 期望 p8 实测 p2，dev=-6 报警
    assert [f["zh_uid"] for f in drifts] == ["figure-4"]
    assert drifts[0]["expect_p"] == 8  # noqa: PLR2004 -- 斜率1平移趋势期望页
    # 比例压缩面：zh_p = round(0.7 * base_p)，整体趋势合法 → 零报警
    zh2 = _mk_marks([
        ("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1),
        ("figure-3-b", 0, 0, 1), ("figure-4-b", 0, 0, 1),
        ("figure-1-e", 0, 0, 7), ("figure-2-e", 0, 0, 8),
        ("figure-3-e", 0, 0, 8), ("figure-4-e", 0, 0, 9),
    ])
    out2 = compare_marks(zh2, base)
    assert not any(f["sig"] == "layout:float_drift" for f in out2)


def test_compare_order_inversion() -> None:
    base = _mk_marks([
        ("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1),
        ("figure-1-e", 0, 100, 2), ("figure-2-e", 0, 50, 3),
    ])
    zh = _mk_marks([
        ("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1),
        ("figure-1-e", 0, 50, 4), ("figure-2-e", 0, 100, 2),  # 跨页序倒
    ])
    out = compare_marks(zh, base)
    inv = [f for f in out if f["sig"] == "layout:order_inversion"]
    assert inv
    assert inv[0]["base_order"] != inv[0]["zh_order"]
    assert inv[0]["pairs"] == [("figure-1", "figure-2")]


def test_compare_order_inversion_same_page_ok() -> None:
    """同页倒置 = 双栏栏位伪影（右栏顶 vs 左栏底），不报警。"""
    base = _mk_marks([
        ("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1),
        ("figure-1-e", 0, 100, 2), ("figure-2-e", 0, 50, 3),
    ])
    zh = _mk_marks([
        ("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1),
        ("figure-1-e", 0, 50, 2), ("figure-2-e", 0, 100, 2),  # 同页序倒
    ])
    out = compare_marks(zh, base)
    assert not any(f["sig"] == "layout:order_inversion" for f in out)


def test_compare_seq_mismatch() -> None:
    base = _mk_marks([("figure-1-b", 0, 0, 1), ("figure-2-b", 0, 0, 1)])
    zh = _mk_marks([("figure-1-b", 0, 0, 1)])
    out = compare_marks(zh, base)
    assert any(f["sig"] == "layout:float_seq_mismatch" for f in out)


# ---------------------------------------------------------------- 日志信号


def test_logscan_overfull_and_fit() -> None:
    log = ("Overfull \\hbox (60.5pt too wide) in paragraph\n"
           "Overfull \\vbox (12pt too high)\n"
           "TeXlate-Float-Fit: figure-3 shrunk\n"
           "LaTeX Warning: Float too large for page\n")
    f, m = _logscan(log)
    sigs = {x["sig"] for x in f}
    assert m["overfull_n"] == 2  # noqa: PLR2004
    assert m["overfull_max_pt"] == 60.5  # noqa: PLR2004 -- 越界点数即规格
    assert m["overfull_vbox_n"] == 1
    assert sigs == {"layout:overfull", "layout:float_fit",
                    "layout:float_lost"}


def test_logscan_quiet() -> None:
    f, m = _logscan("This is XeTeX, Version 3.14\nOutput written.\n")
    assert f == []
    assert m["overfull_n"] == 0


# ---------------------------------------------------------------- 文本层


def test_plain_residual_en_and_degenerate() -> None:
    en_line = "This is a fully english sentence left untranslated here."
    text = ("中文内容正常翻译。\n" + en_line + "\n") * 30
    f, m = _plain_scan(text)
    assert m["residual_en_lines"] >= 30  # noqa: PLR2004 -- 30 次循环注入的下界
    assert any(x["sig"] == "xlat_residual_en" for x in f)


def test_plain_residual_en_noise_floor() -> None:
    """少量合法英文行（作者块/术语/语料例句）不触发——2512.01407 实证
    13 行标题页英文全是 frontmatter+algorithm+表头，阈值提到
    ≥25行且≥2%（或绝对质量 ≥60 行）后不再报警。"""
    en_line = "Alexandre Sac-Morane, Katerina Ioannidou, Duke University"
    text = ("中文内容正常翻译，这段文字很长很长很长。\n" * 40
            + en_line + "\n") * 13
    f, m = _plain_scan(text)
    assert m["residual_en_lines"] == 13  # noqa: PLR2004 -- 2512.01407 实证行数
    assert not any(x["sig"] == "xlat_residual_en" for x in f)


def test_plain_degenerate_ngram() -> None:
    text = " ".join(["abcde"] * 60)  # 5-gram 大量重复
    f, m = _plain_scan(text)
    assert m["top_ngram_rep"] > 20  # noqa: PLR2004 -- ngram 退化阈即规格
    assert any(x["sig"] == "vis_degenerate" for x in f)
    # 纯符号连珠（散点 marker ●/○）不算退化——1706.02386 实证
    text2 = "".join(f"第{i}段正常中文内容各不相同。\n" for i in range(30)) \
        + " ".join(["●"] * 400)
    _f2, m2 = _plain_scan(text2)
    assert m2["top_ngram_rep"] <= 20  # noqa: PLR2004


def test_plain_fffd() -> None:
    f, m = _plain_scan("正常文本 � 出现\n" * 3)
    assert m["fffd"] == 3  # noqa: PLR2004
    assert any(x["sig"] == "vis_degenerate" for x in f)


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


def test_plain_periodic_placeholder() -> None:
    """行内短周期连珠 = CJK 占位/mock 译文签名——2609.19244 实证
    top_rep=46 被 running-head 放阈放走，行内连珠才是真签名。"""
    spam = "这是译文这是译文这是译文这是译文这是译文这是译文这是译文"
    text = "正常中文正文段落。\n" * 5 + (spam + "\n") * 4 \
        + "又一段正常内容。\n" * 5
    f, m = _plain_scan(text)
    assert m["degen_periodic_lines"] == 4  # noqa: PLR2004
    assert any(x["sig"] == "vis_degenerate" for x in f)
    # 单两行修辞性重复不过阈；无词字符单元（……/====）不算
    legit = "正常段落。\n" * 6 + "他说哈哈哈哈哈哈哈哈哈哈地笑。\n" \
        + "分隔 ………………………… 与 ======== 行。\n" + "收尾。\n" * 4
    _f2, m2 = _plain_scan(legit)
    assert m2["degen_periodic_lines"] <= 2  # noqa: PLR2004


# ---------------------------------------------------------------- 几何


def test_textblock_geom_vs_fallback() -> None:
    # A4 真值：\paperwidth=597.51pt vs mediabox 595.28bp——pt→bp 换算
    # 后等价，geom 分支命中（letter=614.295pt/612bp 同理）。
    geom = {"pw": 597.508, "ph": 845.047, "tw": 345.0, "th": 550.0,
            "tm": 16.0, "hh": 12.0, "hs": 18.0, "ho": 0.0, "vo": 0.0,
            "oi": 62.0, "cs": 10.0}
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
    ok, _m = _bbox_scan([{"w": 612.0, "h": 792.0, "words": []}],
                        letter_geom, {})
    assert not any(f["sig"] == "layout:paper_mismatch" for f in ok)
    bad, _m = _bbox_scan([{"w": 595.28, "h": 841.89, "words": []}],
                         letter_geom, {})
    assert any(f["sig"] == "layout:paper_mismatch" for f in bad)


def test_plain_residual_en_refs_tail_cut() -> None:
    en_ref = "Smith J and Doe K. Some english reference entry here."
    text = ("正常中文正文。\n" * 8
            + "References\n" + (en_ref + "\n") * 30)
    f, m = _plain_scan(text)
    assert m["residual_en_lines"] == 0
    assert m["en_tail_cut"] == 8  # noqa: PLR2004 -- 正文 8 行后参考尾截断
    assert not any(x["sig"] == "xlat_residual_en" for x in f)


def test_word_overlap_pairs() -> None:
    # 两行同 x 区间、y 中心差 > 半高 → 跨行重叠对
    words = [
        (100, 100, 160, 112, "a"),
        (100, 107, 160, 119, "b"),  # 与 a 跨行重叠（cy 差 7 > 半高 6）
        (300, 100, 360, 112, "c"),  # 远离
    ]
    assert _word_overlap_pairs(words) >= 1
    # 同行相邻词不重叠
    same_line = [(100, 100, 160, 112, "a"), (162, 100, 220, 112, "b")]
    assert _word_overlap_pairs(same_line) == 0


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
        "\\begin{figure}a\\end{figure}\\begin{figure}b\\end{figure}",
        encoding="utf-8")
    (src / "m.tex").write_text(
        "\\begin{figure}a\\end{figure}\\begin{wrapfigure}w\\end{wrapfigure}",
        encoding="utf-8")
    tx = _txlm(splice, [
        "GEOM pw=600pt ph=800pt",
        "MARK figure-1-b x=1 y=1 p=1", "MARK figure-1-e x=1 y=1 p=1",
        "MARK figure-2-b x=1 y=1 p=1", "MARK figure-2-e x=1 y=1 p=1",
    ])
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
    (splice / "m.tex").write_text("\\begin{figure}a\\end{figure}",
                                  encoding="utf-8")
    (src / "m.tex").write_text(
        "\\begin{figure}a\\end{figure}\\begin{table}t\\end{table}",
        encoding="utf-8")
    tx = _txlm(splice, ["GEOM pw=600pt ph=800pt",
                        "MARK figure-1-b x=1 y=1 p=1",
                        "MARK figure-1-e x=1 y=1 p=1"])
    f, _m = _marks_scan(tx, None, splice, src)
    dropped = next(x for x in f if x["sig"] == "layout:dropped_env")
    assert dropped["envs"] == {"table": 1}


def test_marks_absent(tmp_path: Path) -> None:
    f, _m = _marks_scan(tmp_path / "none.txlm", None, None, None)
    assert f == [{"sig": "layout:marks_absent", "side": "zh"}]


# ---------------------------------------------------------------- tier 门档


def test_tier_classification() -> None:
    assert _tier_of([]) == "clean"
    assert _tier_of([{"sig": "layout:float_fit"}]) == "clean"  # INFO 不抬档
    assert _tier_of([{"sig": "layout:marks_absent"}]) == "clean"  # 存量 INFO
    # marks_era（双臂注入编译）下 marks_absent 升 WARN
    assert _tier_of([{"sig": "layout:marks_absent"}],
                    marks_era=True) == "warn"
    assert _tier_of([{"sig": "xlat_residual_en"}]) == "warn"
    assert _tier_of([{"sig": "some_future_sig"}]) == "warn"  # 未分类保守 WARN
    assert _tier_of([{"sig": "xlat_residual_en"},
                     {"sig": "vis_degenerate"}]) == "hard"
    assert _tier_of([{"sig": "layout:no_pdf"}]) == "hard"
    assert _tier_of([{"sig": "layout:pdf_corrupt"}]) == "hard"


# ---------------------------------------------------------------- raster 对拍


def _pg(**kw: float) -> dict:
    d = {"ink": 0.05, "dark_cc": 0.01, "tofu": 0, "rules": 0,
         "void_frac": 0.0, "void_int": 0.0, "cols": 2}
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
            rows[y][x] = False            # 居中 4x4 墨块
    vf, vi = _void_frac(_FakeImg(rows))
    assert vf == pytest.approx(0.4)       # 最大白矩形=全宽条带 20x8
    assert vi == 0.0                      # 白区连通贴边→内部洞为零
    rows2 = [[True] * 20 for _ in range(20)]
    rows2[10][10] = False                 # 单墨像素：满行带或满列带
    vf2, _vi2 = _void_frac(_FakeImg(rows2))
    assert vf2 == pytest.approx(0.5)      # 20x10=200/400，绝不虚报 1.0


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
        "\\end{document}\n", encoding="utf-8")
    assert inject_layout_marks(tmp_path) == 1
    r = subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [shutil.which("xelatex") or "xelatex",
         "-interaction=nonstopmode", "m.tex"],
        cwd=tmp_path, capture_output=True, timeout=120, check=False)
    assert r.returncode == 0
    res = parse_txlm(tmp_path / "m.txlm")
    assert res["geom"].get("pw")
    e = res["marks"].get("figure-1-e@2") or res["marks"].get("figure-1-e@1")
    assert e is not None
    assert e["p"] in (1, 2)
    # b/e 同 uid 成对
    assert any(k.startswith("figure-1-b@") for k in res["marks"])
