r"""``\subfile``/standalone 子档（``\documentclass[..]{subfiles|standalone}``）前导块闸。

2310.16788 实案：母档 ``\subfile{child}`` 吞掉子件 ``\documentclass`` 至
``\begin{document}`` 区间，声明行**之前**的文本在母档 body 语境执行——
归一化臂前置的 ``\PassOptionsToPackage{no-math}{fontspec}``（:1）与
XETEX_COMPATIBILITY 内 ``\PassOptionsToClass{...}{quantumarticle}``（:14）
落 body 即 "Can be used only in preamble"（birds_eye_view/side_view 两档
各 2 err 慢性票）。standalone 类图件同机理（2609.19210 tikz_picture:1、
2609.20069 fig_grindability:1——standalone 包补丁 ``\input``/``\includestandalone``
拉入时声明行前的注入行落母档 body）。闸：子档不注含 preamble-only cs
的前导块；PIXEL 仅 ``\ifdefined``/``\newdimen``（body 合法）放行保
``\pdfpxdimen`` 覆盖；母档与独立文档照旧全注。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.compile.normalize import (
    PIXEL_COMPATIBILITY,
    normalize_engine,
    normalize_project,
)

if TYPE_CHECKING:
    from pathlib import Path

_CHILD = (
    "\\documentclass[../root.tex]{subfiles}\n"
    "\\usepackage{graphicx}\n"
    "\\begin{document}\n"
    "child body\n"
    "\\end{document}\n"
)

_STANDALONE_CHILD = (
    "\\documentclass[tikz,border=4pt]{standalone}\n"
    "\\usepackage{tikz}\n"
    "\\begin{document}\n"
    "\\tikz\\draw(0,0)--(1,1);\n"
    "\\end{document}\n"
)


def test_subfiles_child_no_preamble_prologue() -> None:
    """xelatex 子档：含 preamble-only cs 的前置块全闸。"""
    out = normalize_engine(_CHILD, "xelatex")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" not in out
    assert "\\providecommand{\\DeclareUnicodeCharacter}" not in out
    assert "allowfontchangeintitle" not in out


def test_subfiles_child_tectonic_no_prologue() -> None:
    """tectonic 子档：XETEX/TECTONIC/fontspec 前置全闸。"""
    out = normalize_engine(_CHILD, "tectonic")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" not in out
    assert "\\providecommand{\\DeclareUnicodeCharacter}" not in out
    assert "dsrom" not in out  # TECTONIC_FONT_COMPATIBILITY 字体名标记


def test_subfiles_child_keeps_pixel() -> None:
    """子档 body 用 ``\\pdfpxdimen``：PIXEL 块（body 合法）仍前置保覆盖。"""
    child = _CHILD.replace("child body", "child \\pdfpxdimen body")
    out = normalize_engine(child, "xelatex")
    assert out.startswith(PIXEL_COMPATIBILITY.splitlines()[0])
    assert "\\newdimen\\pdfpxdimen" in out
    assert "\\PassOptionsToPackage{no-math}{fontspec}" not in out


def test_subfiles_child_body_surgeries_still_run() -> None:
    """闸只关前置块：子档 in-place 手术（inputenc 剥离等）照旧。"""
    child = _CHILD.replace("\\usepackage{graphicx}", "\\usepackage{graphicx,inputenc}")
    out = normalize_engine(child, "xelatex")
    assert "inputenc" not in out
    assert "\\usepackage{graphicx}" in out


def test_normal_doc_prologue_unaffected() -> None:
    """独立文档（非子档标记）前导块照旧全注。"""
    doc = _CHILD.replace("{subfiles}", "{article}")
    out = normalize_engine(doc, "xelatex")
    assert out.startswith("\\PassOptionsToPackage{no-math}{fontspec}\n")
    assert "\\providecommand{\\DeclareUnicodeCharacter}" in out


def test_subfiles_marker_in_comment_not_gated() -> None:
    """注释里的 ``\\documentclass{subfiles}`` 不算标记——遮盖视图判定。"""
    doc = (
        "% \\documentclass{subfiles}\n"
        "\\documentclass{article}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    out = normalize_engine(doc, "xelatex")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" in out


def test_subfiles_marker_in_macro_body_not_gated() -> None:
    """``\\def`` 体内 depth>0 的 ``\\documentclass{subfiles}`` 非声明点。"""
    doc = (
        "\\documentclass{article}\n"
        "\\def\\x{\\documentclass{subfiles}}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    out = normalize_engine(doc, "xelatex")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" in out


def test_standalone_child_no_preamble_prologue() -> None:
    """``[tikz]{standalone}`` 图件子档：含 preamble-only cs 的前置块全闸。"""
    out = normalize_engine(_STANDALONE_CHILD, "xelatex")
    assert out.startswith("\\documentclass[tikz,border=4pt]{standalone}")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" not in out
    assert "\\providecommand{\\DeclareUnicodeCharacter}" not in out
    assert "allowfontchangeintitle" not in out


def test_standalone_child_tectonic_no_prologue() -> None:
    """tectonic standalone 子档：XETEX/TECTONIC/fontspec 前置全闸。"""
    out = normalize_engine(_STANDALONE_CHILD, "tectonic")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" not in out
    assert "\\providecommand{\\DeclareUnicodeCharacter}" not in out
    assert "dsrom" not in out


def test_standalone_child_keeps_pixel() -> None:
    """standalone 子档 body 用 ``\\pdfpxdimen``：PIXEL 块仍前置保覆盖。"""
    child = _STANDALONE_CHILD.replace("\\tikz\\draw(0,0)--(1,1);", "w=10\\pdfpxdimen")
    out = normalize_engine(child, "xelatex")
    assert out.startswith(PIXEL_COMPATIBILITY.splitlines()[0])
    assert "\\newdimen\\pdfpxdimen" in out
    assert "\\PassOptionsToPackage{no-math}{fontspec}" not in out


def test_standalone_bare_class_gated() -> None:
    """无选项 ``\\documentclass{standalone}`` 同样入闸。"""
    doc = _STANDALONE_CHILD.replace("[tikz,border=4pt]", "")
    out = normalize_engine(doc, "xelatex")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" not in out


def test_project_level_child_gated(tmp_path: Path) -> None:
    """工程级：root 母档全注 + images 下子档零前置。"""
    (tmp_path / "images").mkdir()
    (tmp_path / "root.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage{subfiles}\n"
        "\\begin{document}\n"
        "\\subfile{images/child}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "images" / "child.tex").write_text(_CHILD, encoding="utf-8")
    normalize_project(tmp_path, "xelatex", "root.tex")
    child = (tmp_path / "images" / "child.tex").read_text(encoding="utf-8")
    root = (tmp_path / "root.tex").read_text(encoding="utf-8")
    assert "\\PassOptionsToPackage{no-math}{fontspec}" not in child
    assert "\\providecommand{\\DeclareUnicodeCharacter}" not in child
    assert "\\PassOptionsToPackage{no-math}{fontspec}" in root
