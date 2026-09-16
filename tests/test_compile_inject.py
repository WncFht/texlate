"""inject.py 中文注入与主文件定位的单测。"""

from pathlib import Path

import pytest

from texlate.compile.inject import (
    CTEX_LINE,
    FLOAT_SIZING,
    InjectRejectError,
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
    r"""单行 ``\ifpdf\documentclass{a}\else\documentclass{b}\fi`` → 去重后一缝（行尾）。"""
    tex = "\\ifpdf\\documentclass{a}\\else\\documentclass{b}\\fi\n\\begin{document}x\n"
    hits = find_docclass_ends(tex)
    assert len(hits) == 1


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
