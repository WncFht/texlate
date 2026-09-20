r"""``\documentclass`` 缝后早期定义锚（``normalize.XETEX_EARLY_DEFS``）。

2609.19376 实案：``\begin{document}`` 藏在 ``\input{hpca-template}`` 子件
内——main.tex 零 bd，``preamble_ok`` 闸把含
``\providecommand{\DeclareUnicodeCharacter}`` 的兼容块整段关在 main 外；
子件文件顶注入位=组合 preamble 中段（main.tex:80 ``\input`` 点），
main.tex:40 的调用先于定义 → undefined_cs → partial。

修：preamble 消费的仿真定义从文件顶兼容块拆出，走 docclass 缝后锚
（inject.find_docclass_ends/_splice_after_seams），不挂 bd/子档闸；
``\documentstyle`` 缝滤除（209 无 ``\providecommand``）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.compile.normalize import (
    XETEX_COMPATIBILITY,
    XETEX_EARLY_DEFS,
    normalize_engine,
    normalize_project,
)

if TYPE_CHECKING:
    from pathlib import Path

_DEF = r"\providecommand{\DeclareUnicodeCharacter}"
_CALL = r"\DeclareUnicodeCharacter{2717}{\ding{55}}"


def test_defs_split_from_tail_compat() -> None:
    """仿真定义只在早期段——文件顶兼容块不再携带。"""
    assert _DEF not in XETEX_COMPATIBILITY
    assert _DEF in XETEX_EARLY_DEFS


def test_bd_hidden_in_input_child() -> None:
    """复现 2609.19376：docclass+中段调用、bd 藏 ``\\input`` 子件——定义先于调用。"""
    doc = (
        "\\documentclass{article}\n"
        "\\usepackage{amsmath}\n"
        "\\usepackage[utf8]{inputenc}\n" + _CALL + "\n\\input{preamble-tail}\n"
    )
    out = normalize_engine(doc, "xelatex")
    assert _DEF in out
    assert out.index("\\documentclass") < out.index(_DEF) < out.index(_CALL)


def test_project_level_bd_in_child(tmp_path: Path) -> None:
    """工程级复现：bd 在 ``\\input`` 子件，main.tex 拿到早期定义。"""
    (tmp_path / "preamble-tail.tex").write_text(
        "\\begin{document}\nbody\n\\end{document}\n", encoding="utf-8"
    )
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n" + _CALL + "\n\\input{preamble-tail}\n",
        encoding="utf-8",
    )
    normalize_project(tmp_path, "xelatex", "main.tex")
    main = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert main.index(_DEF) < main.index(_CALL)


def test_normal_doc_defs_after_docclass() -> None:
    """常规 doc：定义落 docclass 缝后、首个 preamble 调用之前。"""
    doc = (
        "\\documentclass{article}\n"
        "\\usepackage{amsmath}\n" + _CALL + "\n\\begin{document}\nx\n\\end{document}\n"
    )
    out = normalize_engine(doc, "xelatex")
    dc_end = out.index("{article}") + len("{article}")
    assert dc_end < out.index(_DEF) < out.index(_CALL)


def test_rerun_no_double_insert() -> None:
    """二次归一化不重插——块级 ``not in text`` 幂等闸。"""
    doc = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    once = normalize_engine(doc, "xelatex")
    twice = normalize_engine(once, "xelatex")
    assert once == twice
    assert twice.count(_DEF) == 1


def test_documentstyle_seam_filtered() -> None:
    """``\\documentstyle`` 缝不注——209 无 ``\\providecommand``，latex209 不受影响。"""
    doc = "\\documentstyle{article}\n\\begin{document}\nx\n\\end{document}\n"
    out = normalize_engine(doc, "xelatex")
    assert _DEF not in out


def test_multi_seam_defs_at_each() -> None:
    """``\\ifpdf`` 双 docclass：两缝各落一份（``\\providecommand`` 运行时幂等）。"""
    doc = (
        "\\ifpdf\\documentclass{article}\\else\\documentclass{report}\\fi\n"
        + _CALL
        + "\n\\begin{document}\nx\n\\end{document}\n"
    )
    out = normalize_engine(doc, "xelatex")
    assert out.count(_DEF) == out.count("\\documentclass")
    assert out.index(_DEF) < out.index(_CALL)


def test_subdoc_child_gated() -> None:
    """subfiles 子档：同 preamble_ok 口径闸——docclass→bd 区段被母档吞没，调用永不执行。"""
    child = (
        "\\documentclass[../root.tex]{subfiles}\n"
        "\\usepackage{graphicx}\n"
        "\\begin{document}\nchild\n\\end{document}\n"
    )
    out = normalize_engine(child, "xelatex")
    assert _DEF not in out


def test_no_docclass_seam_no_defs() -> None:
    """bd 有而 docclass 缺席（纯 ``\\input`` 载体形）：无缝不注——定义归母档缝位。"""
    frag = "\\begin{document}\nx\n\\end{document}\n"
    out = normalize_engine(frag, "xelatex")
    assert _DEF not in out


def test_support_file_no_defs() -> None:
    """支持件（doc_source=False）含 docclass 字样也不注——其调用归装载文档的缝位。"""
    sty = "\\documentclass{article}\n" + _CALL + "\n"
    out = normalize_engine(sty, "xelatex", doc_source=False)
    assert _DEF not in out
