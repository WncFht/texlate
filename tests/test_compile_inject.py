"""inject.py 中文注入与主文件定位的单测。"""

from pathlib import Path

import pytest

from texlate.compile.inject import (
    CTEX_LINE,
    FLOAT_SIZING,
    InjectRejectError,
    find_docclass_end,
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


def test_inject_cjk_documentstyle_reject() -> None:
    tex = "\\documentstyle{ptptex}\n\\begin{document}\nx\\end{document}"
    with pytest.raises(InjectRejectError):
        inject_cjk(tex)


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
