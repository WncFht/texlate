"""inject.py 中文注入与主文件定位的单测。"""

from pathlib import Path

import pytest

from texlate.compile.inject import (
    CTEX_LINE,
    FLOAT_SIZING,
    TABLE_FITTING,
    InjectRejectError,
    _resolve_input,
    classify_no_main,
    find_docclass_end,
    find_docclass_ends,
    find_main_tex,
    inject_cjk,
    inject_float_sizing,
    prepare_chinese,
)


def test_find_docclass_end_simple() -> None:
    tex = "\\documentclass{article}\nstuff\n"
    hit = find_docclass_end(tex)
    assert hit is not None
    pos, lineno, cmd = hit
    assert cmd == "documentclass"
    assert lineno == 1
    assert tex[:pos].endswith("}")


def test_find_docclass_end_options() -> None:
    tex = "\\documentclass[12pt,a4paper]{amsart}\nx\n"
    hit = find_docclass_end(tex)
    assert hit is not None
    _pos, lineno, _cmd = hit
    assert lineno == 1


def test_find_docclass_end_commented_out() -> None:
    """注释掉的 \\documentclass 不作锚点（1712.01208 形态）。"""
    tex = "% \\documentclass{IEEEtran}\n\\documentclass{acmart}\nx\n"
    hit = find_docclass_end(tex)
    assert hit is not None
    _pos, lineno, _cmd = hit
    assert lineno == 2  # noqa: PLR2004 - 第二行的 docclass 才是锚点


def test_find_docclass_end_multiline_revtex() -> None:
    """revtex4-2 五选一注释穿插形态（2308.07483）。"""
    tex = "\\documentclass[%\n %aip,%\n %jmp,%\n aps,prl,reprint]{revtex4-2}\nbody\n"
    hit = find_docclass_end(tex)
    assert hit is not None
    _pos, lineno, cmd = hit
    assert cmd == "documentclass"
    assert lineno == 4  # noqa: PLR2004 - revtex 五选一注释形态的收尾行号


def test_inject_cjk_ctex() -> None:
    tex = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}"
    out, info = inject_cjk(tex)
    assert info["status"] == "injected"
    assert info["mode"] == "ctex"
    assert CTEX_LINE in out
    assert out.index(CTEX_LINE) > out.index("\\documentclass{article}")
    assert out.index(CTEX_LINE) < out.index("\\begin{document}")


def test_inject_cjk_acmart_baselinestretch_guard() -> None:
    """ctex 模式在 usepackage 行后即插 acmart \\baselinestretch 归位守卫。

    acmart.cls 类载快照 ``\\ACM@origbaselinestretch`` 并 ``\\AtEndDocument``
    ``\\ifx`` 比对；ctex 默认 scheme=chinese 自补 ``\\linespread{1.3}``
    （ctex-scheme-chinese.def → ctex.sty）触发 Class Error
    （soak-2026-09-18 zh-only 49 格，base 臂 0）。守卫以快照 cs 名
    自靶向——唯 acmart 系定义；非 acmart 档 ``\\ifcsname`` 假空转，
    xecjk 模式不携带。
    """
    guard = (
        "\\ifcsname ACM@origbaselinestretch\\endcsname"
        "\\expandafter\\let\\expandafter\\baselinestretch"
        "\\csname ACM@origbaselinestretch\\endcsname\\fi"
    )
    tex = "\\documentclass[sigconf]{acmart}\n\\begin{document}\nx\\end{document}"
    out, info = inject_cjk(tex)
    assert info["mode"] == "ctex"
    assert guard in out
    assert out.index(CTEX_LINE) < out.index(guard) < out.index("\\begin{document}")

    out_xe, info_xe = inject_cjk(tex, mode="xecjk")
    assert info_xe["mode"] == "xecjk"
    assert guard not in out_xe


def test_inject_cjk_already_present() -> None:
    tex = "\\documentclass{ctexart}\n\\begin{document}\nx\\end{document}"
    out, info = inject_cjk(tex)
    assert info["status"] == "already"
    assert out == tex


def test_inject_cjk_substring_ctex_not_present() -> None:
    """宏名内嵌 "ctex"（\\impactex、sectex）不算 CJK 已支持——

    裸子串匹配会误判 already → 跳过注入 → 整篇中文静默缺失。
    """
    tex = (
        "\\documentclass{article}\n\\newcommand{\\impactex}[1]{#1}\n"
        "\\begin{document}\nx\\end{document}"
    )
    out, info = inject_cjk(tex)
    assert info["status"] == "injected"
    assert CTEX_LINE in out


def test_inject_cjk_ctexproc_literal_not_present() -> None:
    r"""``\def\CTeXPreproc{Created by ctex v0.2.12...}`` 宏体字面量假阳——

    loop1 A 桶实证签名（0806.0756/1803.00139/2211.04532）：旧裸子串
    判 already → 整跳注入。包/类语境正则要求族名落在
    usepackage/documentclass 花括号内。
    """
    tex = (
        "\\def\\CTeXPreproc{Created by ctex v0.2.12, don't edit!}\n"
        "\\documentclass{elsarticle}\n\\begin{document}\nx\\end{document}"
    )
    out, info = inject_cjk(tex)
    assert info["status"] == "injected"
    assert CTEX_LINE in out


def test_inject_cjk_ctext_macro_not_present() -> None:
    r"""``\DeclareRobustCommand{\ctext}`` 自定义宏名假阳（2111.00102 实证）。"""
    tex = (
        "\\documentclass{article}\n"
        "\\DeclareRobustCommand{\\ctext}[2]{{\\sethlcolor{#1}\\hl{#2}}}\n"
        "\\begin{document}\nx\\end{document}"
    )
    _out, info = inject_cjk(tex)
    assert info["status"] == "injected"


def test_inject_cjk_mactex_pkg_not_present() -> None:
    r"""包名内嵌 ctex（``\usepackage{mactex}``）不判已有。"""
    tex = (
        "\\documentclass{article}\n\\usepackage{mactex}\n"
        "\\begin{document}\nx\\end{document}"
    )
    _out, info = inject_cjk(tex)
    assert info["status"] == "injected"


def test_inject_cjk_detects_real_cjk_variants() -> None:
    """真 CJK 机制各形态仍判 already（不放丢正面）。"""
    for tex in (
        "\\documentclass{ctexart}\n\\begin{document}\nx\\end{document}",
        "\\documentclass[UTF8]{ctexbook}\n\\begin{document}\nx\\end{document}",
        "\\documentclass{article}\n\\usepackage{xeCJK}\n\\begin{document}\nx\\end{document}",
        "\\documentclass{article}\n\\RequirePackage{CJKutf8}\n\\begin{document}\nx\\end{document}",
        "\\documentclass{article}\n\\usepackage{xeCJK}\n\\setCJKmainfont{SimSun}\n\\begin{document}\nx\\end{document}",
        "\\documentclass{article}\n\\usepackage{CJK}\n\\begin{document}\n\\begin{CJK}{UTF8}{gbsn}x\\end{CJK}\\end{document}",
    ):
        _out, info = inject_cjk(tex)
        assert info["status"] == "already", tex[:60]


def test_find_docclass_ends_branch_selected() -> None:
    r"""``\ifpdf A \else B \fi`` 双 docclass → 两缝都返回（sigma 系形态 1306.6164）。"""
    tex = (
        "\\RequirePackage{ifpdf}\n\\ifpdf\n\\documentclass[pdftex]{sigma}\n"
        "\\else\n\\documentclass{sigma}\n\\fi\n\\begin{document}\nx\\end{document}"
    )
    hits = find_docclass_ends(tex)
    assert len(hits) == 2  # noqa: PLR2004 - 双分支各一缝
    out, info = inject_cjk(tex)
    assert info["status"] == "injected"
    assert info["seams"] == 2  # noqa: PLR2004
    assert out.count("TeXlateCJKloaded") >= 2  # noqa: PLR2004 - 幂等哨兵随块落两臂


def test_find_docclass_ends_macro_body_skipped() -> None:
    r"""``\newcommand{\ds}{\documentstyle}`` 宏体内命中不是真声明点（1706.07796）。"""
    tex = "\\newcommand{\\ds}{\\documentstyle}\n\\documentclass{article}\nx\n"
    hits = find_docclass_ends(tex)
    assert len(hits) == 1
    assert hits[0][2] == "documentclass"


def test_find_docclass_ends_macro_body_only() -> None:
    """唯一 docclass 在宏体内 → 无可用缝 → no-docline（而非注进死代码）。"""
    tex = "\\newcommand{\\ds}{\\documentstyle{article}}\ntext\n"
    _out, info = inject_cjk(tex)
    assert info["status"] == "no-docline"


def test_find_docclass_ends_single_line_conditional() -> None:
    r"""单行 ``\ifpdf\documentclass{a}\else\documentclass{b}\fi`` → 两臂各一缝（``}`` 后即插）。"""
    tex = "\\ifpdf\\documentclass{a}\\else\\documentclass{b}\\fi\n\\begin{document}x\n"
    hits = find_docclass_ends(tex)
    assert len(hits) == 2  # noqa: PLR2004 -- 臂内 close 缝各一，哨兵兜双执行


def test_inject_cjk_branch_block_idempotent() -> None:
    r"""逐缝注入块被 ``\ifdefined\TeXlateCJKloaded`` 哨兵包裹（活臂执行一次）。"""
    tex = (
        "\\ifpdf\n\\documentclass{a}\n\\else\n\\documentclass{b}\n\\fi\n"
        "\\begin{document}\nx\\end{document}"
    )
    out, _info = inject_cjk(tex)
    assert "\\ifdefined\\TeXlateCJKloaded\\else" in out
    assert "\\def\\TeXlateCJKloaded{1}" in out
    # 两臂各一份
    assert out.count("\\ifdefined\\TeXlateCJKloaded\\else") == 2  # noqa: PLR2004


def test_inject_cjk_documentstyle_reject() -> None:
    r"""ds@ 选项机类（ias）升级器不可转——inject 层维持拒，reason 注明机制。

    可转类（article/revtex/ptptex 等）走 latex209.upgrade_209 升级，
    见 test_latex209.py。
    """
    tex = "\\documentstyle{ias}\n\\begin{document}\nx\\end{document}"
    with pytest.raises(InjectRejectError) as exc:
        inject_cjk(tex)
    assert exc.value.reason == "latex209_ds_at"


def test_inject_cjk_xecjk_mode() -> None:
    tex = "\\documentclass{article}\n\\begin{document}\nx\\end{document}"
    out, info = inject_cjk(tex, mode="xecjk")
    assert info["mode"] == "xecjk"
    assert "xeCJK" in out
    assert "FandolSong" in out


def test_inject_cjk_no_docline() -> None:
    _out, info = inject_cjk("no documentclass here")
    assert info["status"] == "no-docline"


def test_find_main_tex(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}"
    )
    (tmp_path / "macros.tex").write_text("\\def\\a{1}\n")
    found = find_main_tex(tmp_path)
    assert found == tmp_path / "main.tex"


def test_find_main_tex_none(tmp_path: Path) -> None:
    (tmp_path / "frag.tex").write_text("just a fragment")
    assert find_main_tex(tmp_path) is None


def test_classify_no_main_latex209(tmp_path: Path) -> None:
    r"""``\documentstyle`` 独存（无 ``\documentclass``）→ latex209。"""
    (tmp_path / "paper.tex").write_text(
        "\\documentstyle{amsppt}\n\\topmatter\n\\endtopmatter\n\\document\nx\n"
    )
    assert classify_no_main(tmp_path) == "latex209"


def test_classify_no_main_plain_tex(tmp_path: Path) -> None:
    r"""plain-TeX 指纹（``\magnification``/``\input harvmac``/``\bye``）→ plain_tex。"""
    (tmp_path / "note.tex").write_text(
        "\\magnification=1200\n\\input harvmac\ntext\n\\bye\n"
    )
    assert classify_no_main(tmp_path) == "plain_tex"


def test_classify_no_main_garbage(tmp_path: Path) -> None:
    """无 TeX/LaTeX 结构（HTML 伪装/纯文本）→ garbage。"""
    (tmp_path / "page.tex").write_text("<html><body>not tex</body></html>\n")
    assert classify_no_main(tmp_path) == "garbage"


def test_classify_no_main_empty_dir(tmp_path: Path) -> None:
    """零 ``.tex`` 树 → garbage（无任何可判结构）。"""
    assert classify_no_main(tmp_path) == "garbage"


def test_classify_no_main_ambiguous_dc(tmp_path: Path) -> None:
    r"""``\documentclass`` 可见但 ``\begin{document}`` 无 → None 存疑不归上游。"""
    (tmp_path / "frag.tex").write_text("\\documentclass{article}\nno body env\n")
    assert classify_no_main(tmp_path) is None


def test_classify_no_main_ambiguous_bd(tmp_path: Path) -> None:
    r"""``\begin{document}`` 可见但 dc/ds 无 → None（LaTeX 残件存疑）。"""
    (tmp_path / "body.tex").write_text("\\begin{document}\nx\n\\end{document}\n")
    assert classify_no_main(tmp_path) is None


def test_classify_no_main_masked(tmp_path: Path) -> None:
    r"""dc/ds 仅在注释内 → 遮盖视图不计，仍按指纹归 plain_tex。"""
    (tmp_path / "doc.tex").write_text(
        "% \\documentclass{article}\n% \\documentstyle{amsart}\n\\input phyzzx\n\\bye\n"
    )
    assert classify_no_main(tmp_path) == "plain_tex"


def test_find_main_tex_body_mass_beats_standalone(tmp_path: Path) -> None:
    r"""E 桶 1803.02985：standalone 图档字面 body 更厚也输 include 编排壳。

    thesis 壳 literal body 仅几条 ``\include``（~80 字符），standalone
    tikz 图 body 更厚——按闭包内容量取 thesis。
    """
    (tmp_path / "fig_standalone.tex").write_text(
        "\\documentclass{standalone}\n\\usepackage{tikz}\n"
        "\\begin{document}\n\\begin{tikzpicture}\n"
        + "\\draw (0,0) -- (1,1) node{label}; % pad\n" * 12
        + "\\end{tikzpicture}\n\\end{document}\n"
    )
    (tmp_path / "chap_one.tex").write_text(
        "\\chapter{One}\n" + "Body text of chapter one. " * 60
    )
    (tmp_path / "chap_two.tex").write_text(
        "\\chapter{Two}\n" + "Body text of chapter two. " * 60
    )
    (tmp_path / "thesis.tex").write_text(
        "\\documentclass{book}\n\\begin{document}\n"
        "\\include{chap_one}\n\\include{chap_two}\n\\end{document}\n"
    )
    assert find_main_tex(tmp_path) == tmp_path / "thesis.tex"


def test_find_main_tex_body_mass_transitive(tmp_path: Path) -> None:
    r"""``\input`` 闭包传递：main → chapter → section 二级也计入质量。"""
    (tmp_path / "deep.tex").write_text("deep section content. " * 80)
    (tmp_path / "chap.tex").write_text("\\input{deep}\nchapter text. " * 40)
    (tmp_path / "thick_fig.tex").write_text(
        "\\documentclass{standalone}\n\\begin{document}\n"
        + "figure body filler " * 50
        + "\\end{document}\n"
    )
    (tmp_path / "paper_main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{chap}\n\\end{document}\n"
    )
    assert find_main_tex(tmp_path) == tmp_path / "paper_main.tex"


def test_find_main_tex_name_bonus_above_mass(tmp_path: Path) -> None:
    r"""main/paper/ms 名仍在 body 量之上——退化 main.tex 不致被厚图档翻盘。"""
    (tmp_path / "bigfig.tex").write_text(
        "\\documentclass{standalone}\n\\begin{document}\n"
        + "huge figure content " * 60
        + "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert find_main_tex(tmp_path) == tmp_path / "main.tex"


def test_find_main_tex_body_mass_input_cycle(tmp_path: Path) -> None:
    r"""``\\input`` 环引不死循环——visited 集收口。"""
    (tmp_path / "a.tex").write_text("\\input{b}\nalpha text. " * 40)
    (tmp_path / "b.tex").write_text("\\input{a}\nbeta text. " * 40)
    (tmp_path / "doc.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{a}\n\\end{document}\n"
    )
    assert find_main_tex(tmp_path) == tmp_path / "doc.tex"


def test_find_main_tex_mass_same_bucket_keeps_size(tmp_path: Path) -> None:
    r"""同量级 body 不由 mass 仲裁——supp 险胜正文的翻盘被位数桶拦住。

    1907.00012 形态：补充材料文档 body 比正文厚 ~1.8× 但同十进制位数桶 →
    回退文件大小（注释填充令正文文件更大，mass 不计注释）。
    """
    (tmp_path / "supp_doc.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        + "supplemental section content " * 80
        + "\\end{document}\n"
    )
    (tmp_path / "conference.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        + "main paper body text " * 60
        + "\\end{document}\n"
        + "% trailing comment padding to keep file bigger\n" * 200
    )
    assert find_main_tex(tmp_path) == tmp_path / "conference.tex"


def test_find_main_tex_depth_above_mass(tmp_path: Path) -> None:
    r"""目录深度仍在 body 量之上——深层厚文档不翻盘浅层候选（1012.5411 形态）。"""
    sub = tmp_path / "doc" / "latex" / "guide"
    sub.mkdir(parents=True)
    (sub / "guide_doc.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        + "deep bundled documentation text " * 60
        + "\\end{document}\n"
    )
    (tmp_path / "short_paper.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert find_main_tex(tmp_path) == tmp_path / "short_paper.tex"


@pytest.mark.parametrize("name", ["MAIN.TEX", "main.Tex", "Paper.TEX"])
def test_find_main_tex_uppercase_ext(tmp_path: Path, name: str) -> None:
    r"""大写/混写扩展名主文件入候选——``rglob("*.tex")`` 大小写盲点修复
    （corpus_v3 loop1 6 cells parse reject ``no_main_tex``）。"""
    (tmp_path / name).write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}"
    )
    (tmp_path / "macros.tex").write_text("\\def\\a{1}\n")
    assert find_main_tex(tmp_path) == tmp_path / name


def test_find_main_tex_uppercase_is_candidate(tmp_path: Path) -> None:
    r"""``.TEX`` 与 ``.tex`` 同场竞技：mass 量级差按既有规则仲裁出 ``.TEX``。"""
    (tmp_path / "a.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    (tmp_path / "B.TEX").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        + "much larger body text " * 80
        + "\\end{document}\n"
    )
    assert find_main_tex(tmp_path) == tmp_path / "B.TEX"


def test_find_main_tex_uppercase_ranking_unchanged(tmp_path: Path) -> None:
    r"""``main.tex`` 名加成对厚 ``.TEX`` 候选依旧生效——修复不改既有排序。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    (tmp_path / "B.TEX").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        + "much larger body text " * 80
        + "\\end{document}\n"
    )
    assert find_main_tex(tmp_path) == tmp_path / "main.tex"


def test_find_main_tex_bd_in_input_child(tmp_path: Path) -> None:
    r"""编排壳 main：``\documentclass`` 本体 + bd 落 ``\input`` 子文件（cs/0408015）。

    ``main.tex`` 只拉 ``body.tex``，``\begin{document}`` 在下游——
    旧谓词要求 bd 在本体 → 整工程 no_main_tex。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{tacmconf}\n\\usepackage{graphicx}\n\\input{body}\n"
    )
    (tmp_path / "body.tex").write_text(
        "\\begin{document}\nreal paper body " * 20 + "\n\\end{document}\n"
    )
    assert find_main_tex(tmp_path) == tmp_path / "main.tex"


def test_find_main_tex_bd_transitive_two_hops(tmp_path: Path) -> None:
    r"""bd 隔两跳也算：``main → mid → leaf`` 传递闭包内命中即收。"""
    (tmp_path / "leaf.tex").write_text(
        "\\begin{document}\ndeep content " * 30 + "\n\\end{document}\n"
    )
    (tmp_path / "mid.tex").write_text("\\input{leaf}\nmid wrapping text\n")
    (tmp_path / "paper.tex").write_text("\\documentclass{article}\n\\input{mid}\n")
    assert find_main_tex(tmp_path) == tmp_path / "paper.tex"


def test_find_main_tex_closure_without_bd_rejected(tmp_path: Path) -> None:
    r"""dc 文件的 ``\input`` 闭包无 bd → 仍拒（闭包放宽不放丢 bd 判据）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input{macros}\n\\input{styles}\n"
    )
    (tmp_path / "macros.tex").write_text("\\def\\a{1}\n\\def\\b{2}\n")
    (tmp_path / "styles.tex").write_text("\\input{macros}\n\\def\\c{3}\n")
    assert find_main_tex(tmp_path) is None


def test_find_main_tex_commented_input_not_followed(tmp_path: Path) -> None:
    r"""注释掉的 ``\input``/bd 不计——遮盖视图内不可见。

    ``main.tex`` 的 ``%\input{body}`` 被抹除 → body.tex 不可达；
    ``supp.tex`` 活 ``\input{chap}`` 但 chap 内 bd 整行注释 → 同样无 bd。
    """
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n% \\input{body}\n")
    (tmp_path / "body.tex").write_text("\\begin{document}\nx\n\\end{document}\n")
    (tmp_path / "supp.tex").write_text("\\documentclass{article}\n\\input{chap}\n")
    (tmp_path / "chap.tex").write_text(
        "% \\begin{document}\nchapter text\n% \\end{document}\n"
    )
    assert find_main_tex(tmp_path) is None


def test_find_main_tex_seki_cover_admitted_via_closure(tmp_path: Path) -> None:
    r"""SEKI 双子形态（0905.2435/0905.4369）W99 二遍：闭包供 dc → 收录。

    封面 ``seki-deckblatt-3.tex`` 有 dc 但不 ``\input`` 正文；``pdf.tex``
    拉 ``body``（含 bd）却自己没有 dc——W99 起 dc 判据放宽到 ``\input``
    闭包（helper 宏参类名形态），``body.tex`` 本体 bd + 闭包 dc 双准入池；
    同为候选时 ``body`` 体量更大压过 ``pdf`` 壳当选。
    """
    (tmp_path / "seki-deckblatt-3.tex").write_text(
        "\\newcommand\\makecover{%\n\\documentclass[twoside,12pt]{\\whatSEKI}\n}\n"
    )
    (tmp_path / "body.tex").write_text(
        "\\input seki-deckblatt-3\n"
        "\\begin{document}\nbody " * 40 + "\n\\end{document}\n"
    )
    (tmp_path / "pdf.tex").write_text(
        "%&latex\n\\newcommand\\SEKImasterusepackages{}\n\\input body\n"
    )
    assert find_main_tex(tmp_path) == tmp_path / "body.tex"


def test_inject_float_sizing_uppercase_ext(tmp_path: Path) -> None:
    r"""``.TEX`` 主文件的 figure 工程也触发 FLOAT_SIZING 注入。"""
    (tmp_path / "PAPER.TEX").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{figure}x\\end{figure}\n\\end{document}"
    )
    assert inject_float_sizing(tmp_path) == 1


def test_inject_float_sizing_only_with_floats(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}"
    )
    assert inject_float_sizing(plain) == 0

    withfig = tmp_path / "withfig"
    withfig.mkdir()
    (withfig / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{figure}x\\end{figure}\n\\end{document}"
    )
    assert inject_float_sizing(withfig) == 1
    assert FLOAT_SIZING.strip().splitlines()[0] in (withfig / "main.tex").read_text()


def test_prepare_chinese(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\\end{document}"
    )
    info = prepare_chinese(tmp_path, "main.tex")
    assert info["status"] == "injected"
    out = (tmp_path / "main.tex").read_text()
    assert CTEX_LINE in out


def test_find_main_tex_template_options_demoted(tmp_path: Path) -> None:
    r"""1206.0565：``\documentclass[\optionlist]{cls}`` 算选项=类文档模板档。

    类发行捆绑包 (aipproc.dtx/.ins/.cls 同树) 的 guide 档 body 量比真论文
    还大——字面选项优先于质量/大小键。
    """
    (tmp_path / "aipguide.tex").write_text(
        "\\documentclass[\\optionlist]{aipproc}\n\\begin{document}\n"
        + "class guide prose " * 200
        + "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "poster_duerr_arxiv.tex").write_text(
        "\\documentclass[sort&compress]{aipproc}\n\\begin{document}\n"
        "real paper body\n\\end{document}\n",
        encoding="utf-8",
    )
    assert find_main_tex(tmp_path) == tmp_path / "poster_duerr_arxiv.tex"


def test_find_main_tex_literal_opts_undemoted(tmp_path: Path) -> None:
    r"""字面选项档不受模板键影响——``[12pt,twocolumn]`` 无 ``\`` 照常竞争。"""
    (tmp_path / "real.tex").write_text(
        "\\documentclass[12pt,twocolumn]{article}\n\\begin{document}\n"
        + "paper " * 100
        + "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "small.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    assert find_main_tex(tmp_path) == tmp_path / "real.tex"


# ---------------------------------------------------------------- 审计修复面
def test_find_main_tex_spaced_begin_document(tmp_path: Path) -> None:
    r"""``\begin {document}``（cs 与花括号间空白是合法 TeX）——body 量口径
    与检测正则 ``\\begin\s*\{document\}`` 对齐；字面 split 切不到会把
    前导区虚抬成 body，薄壳挤掉真 main。"""
    padded = "\\documentclass{article}\n" + "\\def\\pad{}\n" * 300
    (tmp_path / "a.tex").write_text(
        padded + "\\begin {document}\nhi\n\\end{document}\n", encoding="utf-8"
    )
    (tmp_path / "b.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        + "word " * 400
        + "\n\\end{document}\n",
        encoding="utf-8",
    )
    assert find_main_tex(tmp_path) == tmp_path / "b.tex"


def test_prepare_chinese_already_cjk_gets_table_fitting(tmp_path: Path) -> None:
    """已含 CJK 的工程（status=already）同样补 threeparttable 溢宽钩子——
    旧码只在 status=injected 分支挂 TABLE_FITTING。"""
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{ctexart}\n\\usepackage{threeparttable}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    info = prepare_chinese(tmp_path, "main.tex", float_sizing=False)
    assert info["status"] == "already"
    text = main.read_text(encoding="utf-8")
    assert TABLE_FITTING.strip() in text
    assert text.index("max width=\\linewidth") < text.index("\\begin{document}")
    before = main.read_text(encoding="utf-8")
    prepare_chinese(tmp_path, "main.tex", float_sizing=False)  # 幂等：不重复注入
    assert main.read_text(encoding="utf-8") == before


def test_resolve_input_giant_name_returns_none(tmp_path: Path) -> None:
    r"""``\input{<300字符>}`` → ENAMETOOLONG 按不可解析计（文档可控面防御）。"""
    assert _resolve_input(tmp_path, tmp_path, "a" * 300) is None


def test_resolve_input_symlink_loop_returns_none(tmp_path: Path) -> None:
    r"""symlink loop → ``resolve()`` RuntimeError → None（不炸 inject_cjk）。"""
    (tmp_path / "loop.tex").symlink_to("loop.tex")
    assert _resolve_input(tmp_path, tmp_path, "loop") is None
