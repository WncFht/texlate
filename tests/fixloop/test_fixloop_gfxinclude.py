"""graphics_include_strip — ``\\include/\\input{*.<gfx>}`` 笔误剥除.

docclsstack 车道 (math/0501227): preamble 期 ``\\include{triangle_dots.eps}``
把 EPS 头按 TeX 源展开 → Missing \\begin{document} + Missing-$ 爆流
(411 syntax 错)。单参 input 族命令只可能吸 TeX 源——花括号目标落图形
扩展名 (.eps/.pdf/.png 系) 时该行必错, 剥除零语义损失。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from _fixloopkit import mk_ctx_files

from texlate.compile.fixloop.builtins.misc import graphics_include_strip

if TYPE_CHECKING:
    from pathlib import Path

_MAIN = (
    "\\documentclass{article}\n\\usepackage{graphicx}\n"
    "\\include{triangle_dots.eps}\n\\begin{document}\n"
    "Body \\includegraphics[width=0.5\\textwidth]{triangle_dots}.\n"
    "\\end{document}\n"
)


def test_eps_include_stripped(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": _MAIN})
    ok, note = graphics_include_strip(ctx, None, None, {})
    assert ok, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\include{triangle_dots.eps}" not in out
    assert "\\includegraphics[width=0.5\\textwidth]{triangle_dots}" in out


def test_tex_target_inputs_kept(tmp_path: Path) -> None:
    src = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\input{chap1}\n\\include{chap2.tex}\n\\InputIfFileExists{chap3}{x}{y}\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": src})
    ok, _note = graphics_include_strip(ctx, None, None, {})
    assert not ok
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == src


def test_all_gfx_exts_stripped(tmp_path: Path) -> None:
    src = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\input{a.pdf} \\input{b.png} \\input{c.jpg} \\input{d.ps} \\input{e.svg}\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": src})
    ok, note = graphics_include_strip(ctx, None, None, {})
    assert ok, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    for ext in ("a.pdf", "b.png", "c.jpg", "d.ps", "e.svg"):
        assert ext not in out


def test_commented_and_verbatim_sites_untouched(tmp_path: Path) -> None:
    src = (
        "\\documentclass{article}\n\\begin{document}\n"
        "% \\include{commented.eps}\n"
        "\\begin{verbatim}\n\\input{inverb.png}\n\\end{verbatim}\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": src})
    ok, _note = graphics_include_strip(ctx, None, None, {})
    assert not ok
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == src


def test_line_remainder_preserved(tmp_path: Path) -> None:
    src = (
        "\\documentclass{article}\n\\begin{document}\n"
        "before \\input{fig.eps} after\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": src})
    ok, _note = graphics_include_strip(ctx, None, None, {})
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "before  after" in out


def test_gfx_exts_param_override_replaces_default(tmp_path: Path) -> None:
    """``params.gfx_exts`` 整表顶替 ``_GFX_INPUT_EXTS`` (replace 非 union):

    覆盖后 ``.xyz`` 进剥离面而默认 ``.eps`` 反而不再命中——钉死
    ``params.get(key) or <default>`` 逃生舱的语义向。
    """
    src = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\input{a.xyz} \\input{b.eps}\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": src})
    ok, note = graphics_include_strip(ctx, None, None, {"gfx_exts": {".xyz"}})
    assert ok, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "a.xyz" not in out
    assert "\\input{b.eps}" in out
