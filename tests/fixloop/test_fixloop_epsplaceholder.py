"""graphic_missing_placeholder — missing_file 的 PS 族图档真缺件 → EPS 占位落盘.

failmine3 #164a (8 格): graphic_ext_relax 剥扩展名后图档仍不在 tar —
修复不是改源而是补档 (xbb_pregen 旁件同形)。占位文件统一可解
``\\includegraphics``/``\\epsfig{file=X.eps}``/宏定义位 ``#1.eps`` 三形态。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from _fixloopkit import mk_ctx_files

from texlate.compile.fixloop.builtins import graphic_missing_placeholder
from texlate.compile.fixloop.ruleset import load_ruleset

if TYPE_CHECKING:
    from pathlib import Path

_MAIN = (
    "\\documentclass{article}\n\\usepackage{graphicx}\n"
    "\\begin{document}\n\\includegraphics{FIGS/plot.eps}\n\\end{document}\n"
)


def test_eps_payload_writes_placeholder_in_subdir(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": _MAIN})
    ok, note = graphic_missing_placeholder(ctx, None, "FIGS/plot.eps", {})
    assert ok, note
    out = tmp_path / "FIGS/plot.eps"
    assert out.is_file()
    assert out.read_text(encoding="utf-8").startswith("%!PS-Adobe")
    assert "%%BoundingBox:" in out.read_text(encoding="utf-8")


def test_non_ps_suffix_refused(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": "x\n"})
    ok, note = graphic_missing_placeholder(ctx, None, "foo.sty", {})
    assert not ok
    assert "not a known graphic ext" in note
    assert not (tmp_path / "foo.sty").exists()


def test_extless_payload_needs_live_graphic_ref(tmp_path: Path) -> None:
    ctx = mk_ctx_files(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{bar_plot}\n\\end{document}\n"
            )
        },
    )
    ok, note = graphic_missing_placeholder(ctx, None, "bar_plot", {})
    assert ok, note
    assert (tmp_path / "bar_plot.eps").is_file()


def test_extless_without_live_ref_refused(tmp_path: Path) -> None:
    # \input{chap2} 缺件 payload 是 extless —— 无图形引用作证时绝不落假图
    ctx = mk_ctx_files(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                "\\input{chap2}\n\\end{document}\n"
            )
        },
    )
    ok, note = graphic_missing_placeholder(ctx, None, "chap2", {})
    assert not ok
    assert "no live graphic ref" in note
    assert not (tmp_path / "chap2.eps").exists()


def test_epsfig_kv_form_counts_as_live_ref(tmp_path: Path) -> None:
    ctx = mk_ctx_files(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{epsfig}\n"
                "\\begin{document}\n\\epsfig{file=img/fig.eps,height=3cm}\n"
                "\\end{document}\n"
            )
        },
    )
    ok, note = graphic_missing_placeholder(ctx, None, "img/fig", {})
    assert ok, note
    assert (tmp_path / "img/fig.eps").is_file()


def test_commented_ref_does_not_count(tmp_path: Path) -> None:
    # mask_tex 遮盖视图: 注释内 \includegraphics 不作存活证据
    ctx = mk_ctx_files(
        tmp_path,
        {"main.tex": "% \\includegraphics{ghost}\nx\n"},
    )
    ok, _note = graphic_missing_placeholder(ctx, None, "ghost", {})
    assert not ok
    assert not (tmp_path / "ghost.eps").exists()


def test_path_traversal_refused(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": "x\n"})
    ok, note = graphic_missing_placeholder(ctx, None, "../evil.eps", {})
    assert not ok
    assert "traversal" in note
    assert not (tmp_path.parent / "evil.eps").exists()


def test_existing_file_not_clobbered(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": "x\n", "a.eps": "real content"})
    ok, _note = graphic_missing_placeholder(ctx, None, "a.eps", {})
    assert not ok
    assert (tmp_path / "a.eps").read_text() == "real content"


def test_empty_payload_refused(tmp_path: Path) -> None:
    ctx = mk_ctx_files(tmp_path, {"main.tex": "x\n"})
    ok, note = graphic_missing_placeholder(ctx, None, "", {})
    assert not ok
    assert "no graphic payload" in note


def test_rule_sits_between_includepdf_stub_and_repair() -> None:
    ids = [r.id for r in load_ruleset().phase("loop")]
    i_stub = ids.index("includepdf_missing_stub")
    i_ph = ids.index("graphic_missing_placeholder")
    i_rep = ids.index("graphic_repair")
    assert i_stub < i_ph < i_rep
    rules = {r.id: r for r in load_ruleset().phase("loop")}
    when = rules["graphic_missing_placeholder"].when
    # failmine4-covgap: missing_graphic (xetex "Unable to load" 措辞) 双臂化
    assert when == {
        "any": [
            {"category": "missing_file", "payload_required": True},
            {"category": "missing_graphic", "payload_required": True},
        ]
    }
