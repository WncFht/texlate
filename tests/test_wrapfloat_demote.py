r"""``demote_wrapfloats``（inject.py zh 侧 wrapfloat 降级）单测面。

动机：wrapfig 绕排落点依赖后续段落行数，译文缩短必然漂移——2609.19101 zh p6
wrapfigure 压 ``table[b]`` + caption 裁出版心双亚型实证；bench/py/wrapfloat_bench
合成复现。降级 ``figure[!htb]``+``minipage{原宽}`` 是根修：浮体永不重叠/裁切。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.compile.inject import (
    _demote_wrapfloats_text,
    demote_wrapfloats,
    prepare_chinese,
)

if TYPE_CHECKING:
    from pathlib import Path

_PRE = "\\documentclass{article}\n\\usepackage{wrapfig,graphicx}\n\\begin{document}\n"


def test_basic_wrapfigure_to_figure_minipage() -> None:
    tex = _PRE + (
        "\\begin{wrapfigure}{r}{0.5\\textwidth}\n"
        "  \\centering\n"
        "  \\includegraphics[width=0.98\\linewidth]{f.pdf}\n"
        "  \\caption{cap}\n"
        "  \\label{fig:x}\n"
        "\\end{wrapfigure}\n"
        "tail\n\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == 1
    assert (
        "\\begin{figure}[!htb]\\centering\\begin{minipage}{0.5\\textwidth}\n"
        "  \\centering\n"
        "  \\includegraphics[width=0.98\\linewidth]{f.pdf}\n"
        "  \\caption{cap}\n"
        "  \\label{fig:x}\n"
        "\\end{minipage}\\end{figure}\n"
    ) in out
    assert "wrapfigure" not in out


def test_optional_args_consumed() -> None:
    tex = _PRE + (
        "\\begin{wrapfigure}[12]{r}[3pt]{0.4\\textwidth}\n"
        "x\n\\end{wrapfigure}\n\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == 1
    assert "\\begin{figure}[!htb]\\centering\\begin{minipage}{0.4\\textwidth}" in out
    assert "[12]" not in out
    assert "[3pt]" not in out


def test_starred_and_wraptable() -> None:
    tex = _PRE + (
        "\\begin{wrapfigure*}{o}{0.8\\textwidth}\na\n\\end{wrapfigure*}\n"
        "\\begin{wraptable}{l}{3cm}\nb\n\\end{wraptable}\n"
        "\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == tex.count("\\begin{wrap")
    assert "\\begin{figure*}[!tb]\\centering\\begin{minipage}{0.8\\textwidth}" in out
    assert "\\end{minipage}\\end{figure*}" in out
    assert "\\begin{table}[!htb]\\centering\\begin{minipage}{3cm}" in out
    assert "\\end{minipage}\\end{table}" in out


def test_wrapfloat_passthrough_type() -> None:
    tex = _PRE + (
        "\\begin{wrapfloat}{algorithm}{r}{0.4\\textwidth}\nx\n\\end{wrapfloat}\n"
        "\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == 1
    assert "\\begin{algorithm}[!htb]\\centering\\begin{minipage}{0.4\\textwidth}" in out


def test_zero_width_no_minipage() -> None:
    tex = _PRE + (
        "\\begin{wrapfigure}{r}{0pt}\nx\n\\end{wrapfigure}\n\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == 1
    assert "\\begin{figure}[!htb]\\centering\n" in out
    assert "minipage" not in out


def test_comment_and_verbatim_untouched() -> None:
    tex = _PRE + (
        "% \\begin{wrapfigure}{r}{0.5\\textwidth} kept comment\n"
        "\\begin{verbatim}\n"
        "\\begin{wrapfigure}{r}{0.5\\textwidth}\n\\end{wrapfigure}\n"
        "\\end{verbatim}\n"
        "\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == 0
    assert out == tex


def test_nested_env_skipped() -> None:
    """盒内 wrapfig（itemize/minipage 等）降级成浮体会变 outer-par 错——跳过。"""
    tex = _PRE + (
        "\\begin{itemize}\\item a\n"
        "\\begin{wrapfigure}{r}{0.5\\textwidth}\nx\n\\end{wrapfigure}\n"
        "\\end{itemize}\n\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == 0
    assert out == tex


def test_malformed_missing_width_skipped() -> None:
    tex = _PRE + "\\begin{wrapfigure}{r}\nx\n\\end{wrapfigure}\n\\end{document}\n"
    out, n = _demote_wrapfloats_text(tex)
    assert n == 0
    assert out == tex


def test_idempotent() -> None:
    tex = _PRE + (
        "\\begin{wrapfigure}{r}{0.5\\textwidth}\nx\n\\end{wrapfigure}\n"
        "\\end{document}\n"
    )
    once, _ = _demote_wrapfloats_text(tex)
    twice, n2 = _demote_wrapfloats_text(once)
    assert twice == once
    assert n2 == 0


def test_line_count_stable() -> None:
    """替换补回换行——降级后行号与降级前对齐（编译错误可回溯源行号）。"""
    tex = _PRE + (
        "a\n\\begin{wrapfigure}{r}{0.5\\textwidth}\n"
        "x\n\\end{wrapfigure}\nb\n\\end{document}\n"
    )
    out, _ = _demote_wrapfloats_text(tex)
    assert out.count("\n") == tex.count("\n")


def test_neg_vspace_scrubbed() -> None:
    """负 \\vspace/\\hspace/\\vskip 是 wrapfig 收区 hack——进浮体盒即溢出。"""
    tex = _PRE + (
        "\\begin{wrapfigure}{r}{0.5\\textwidth}\n"
        "  \\centering\n"
        "  \\vspace{-10pt}\n"
        "  \\hspace*{-6mm}\n"
        "  \\includegraphics{f.pdf}\n"
        "  \\caption{cap tail\n"
        "  \\vspace*{-24pt}\n"
        "  \\vskip-3pt\n"
        "  }\n"
        "\\end{wrapfigure}\n\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == 1
    assert "\\vspace" not in out
    assert "\\hspace" not in out
    assert "\\vskip" not in out
    assert "\\caption{cap tail" in out


def test_pos_vspace_kept() -> None:
    """正 \\vspace 在浮体内是无害间距——保留。"""
    tex = _PRE + (
        "\\begin{wrapfigure}{r}{0.5\\textwidth}\n"
        "  \\vspace{4pt}\n"
        "  \\includegraphics{f.pdf}\n"
        "\\end{wrapfigure}\n\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == 1
    assert "\\vspace{4pt}" in out


def test_vspace_outside_env_untouched() -> None:
    """负 vspace 只扫降级体内部——环境外（如正文手动调距）不动。"""
    tex = _PRE + (
        "para\\vspace{-5pt}\n"
        "\\begin{wrapfigure}{r}{0.5\\textwidth}\nx\n\\end{wrapfigure}\n"
        "tail\\vspace{-3pt}\n\\end{document}\n"
    )
    out, n = _demote_wrapfloats_text(tex)
    assert n == 1
    assert "para\\vspace{-5pt}" in out
    assert "tail\\vspace{-3pt}" in out


def test_root_walk_and_suffix_gate(tmp_path: Path) -> None:
    """rglob 走全树 .tex/.ltx；.sty 内的 wrapfig 不属正文面不碰。"""
    (tmp_path / "sections").mkdir()
    sec = tmp_path / "sections" / "a.tex"
    sec.write_text(
        "\\begin{wrapfigure}{r}{0.5\\textwidth}\nx\n\\end{wrapfigure}\n",
        encoding="utf-8",
    )
    sty = tmp_path / "pkg.sty"
    sty.write_text(
        "\\begin{wrapfigure}{r}{0.5\\textwidth}\nx\n\\end{wrapfigure}\n",
        encoding="utf-8",
    )
    n = demote_wrapfloats(tmp_path)
    assert n == 1
    assert "wrapfigure" not in sec.read_text()
    assert "wrapfigure" in sty.read_text()


def test_prepare_chinese_integration(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        _PRE
        + "\\begin{wrapfigure}{r}{0.5\\textwidth}\nx\n\\end{wrapfigure}\n"
        + "\\end{document}\n",
        encoding="utf-8",
    )
    info = prepare_chinese(tmp_path, "main.tex")
    assert info["wrapfloats_demoted"] == 1
    assert "wrapfigure" not in (tmp_path / "main.tex").read_text()


def test_prepare_chinese_demote_off(tmp_path: Path) -> None:
    src = (
        _PRE
        + "\\begin{wrapfigure}{r}{0.5\\textwidth}\nx\n\\end{wrapfigure}\n"
        + "\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    info = prepare_chinese(tmp_path, "main.tex", demote_wrap=False)
    assert "wrapfloats_demoted" not in info
    assert "wrapfigure" in (tmp_path / "main.tex").read_text()
