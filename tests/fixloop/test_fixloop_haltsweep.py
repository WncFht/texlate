"""graphic_missing_placeholder 源侧枚举 —— halt_on_error 多缺件一轮补齐。

haltsweep 普查 (8 格：1206.0213/1404.6041/2501.01329/2501.01402/
2501.01425/2509.14901/2603.08153/2604.03907): fixloop 编译 halt_on_error
下每轮 log 只曝首个缺图件，``_LOG_MISS_GFX_RE`` 扫臂实际逐轮单补
(2501.01425 烧 8 轮 max_rounds, 余 3 件 log 从未触及)。``_enum_missing_graphics``
对全工程活 ``\\includegraphics``/epsfig 族字面 arg 做静态解析，一轮尽列缺件。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from _fixloopkit import mk_ctx_files

from texlate.compile.fixloop.builtins import graphic_missing_placeholder

if TYPE_CHECKING:
    from pathlib import Path

_MAIN = (
    "\\documentclass{article}\n\\usepackage{graphicx}\n"
    "\\begin{document}\n\\includegraphics{Figs/logo.jpg}\n"
    "\\input{sec/body}\n\\end{document}\n"
)
_BODY = (
    "\\includegraphics{Figs/teaser.pdf}\n"
    "\\includegraphics[width=0.5\\linewidth]{Figs/net.pdf}\n"
    "\\epsfig{file=Figs/old.eps,height=3cm}\n"
    "% \\includegraphics{Figs/commented.pdf}\n"
)


def test_single_round_stubs_all_missing_across_files(tmp_path: Path) -> None:
    """halt_on_error 只曝 logo.jpg —— 枚举补全余下 3 件 (跨文件 + kv 形)."""
    ctx = mk_ctx_files(
        tmp_path,
        {"main.tex": _MAIN, "sec/body.tex": _BODY},
    )
    ok, note = graphic_missing_placeholder(ctx, None, "Figs/logo.jpg", {})
    assert ok, note
    for rel in (
        "Figs/logo.jpg",
        "Figs/teaser.pdf",
        "Figs/net.pdf",
        "Figs/old.eps",
    ):
        assert (tmp_path / rel).is_file(), rel
    assert "commented.pdf" not in note
    assert not (tmp_path / "Figs/commented.pdf").exists()


def test_extless_ref_stubbed_as_eps(tmp_path: Path) -> None:
    ctx = mk_ctx_files(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{Figs/a.pdf}\n"
                "\\includegraphics{Figs/b_plot}\n\\end{document}\n"
            )
        },
    )
    ok, _note = graphic_missing_placeholder(ctx, None, "Figs/a.pdf", {})
    assert ok
    assert (tmp_path / "Figs/a.pdf").is_file()
    assert (tmp_path / "Figs/b_plot.eps").is_file()


def test_filedir_and_graphicspath_resolution_skip(tmp_path: Path) -> None:
    """filedir (sec/ 旁件) 与 \\graphicspath 命中的引用不算缺件 —— 不误占位."""
    ctx = mk_ctx_files(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\graphicspath{{gsp/}}\n\\begin{document}\n"
                "\\includegraphics{Figs/miss.pdf}\n\\input{sec/x}\n"
                "\\end{document}\n"
            ),
            "sec/x.tex": (
                "\\includegraphics{side.pdf}\n\\includegraphics{gs_ok.png}\n"
            ),
            "sec/side.pdf": "real",
            "gsp/gs_ok.png": "real",
        },
    )
    ok, _note = graphic_missing_placeholder(ctx, None, "Figs/miss.pdf", {})
    assert ok
    assert (tmp_path / "Figs/miss.pdf").is_file()
    assert not (tmp_path / "side.pdf").exists()
    assert not (tmp_path / "gs_ok.png").exists()
    assert not (tmp_path / "gs_ok.png.eps").exists()


def test_macro_arg_skipped_stays_log_driven(tmp_path: Path) -> None:
    """``\\imgdir/x.pdf`` 宏拼名静态不可判 —— 枚举不收，不落怪名占位."""
    ctx = mk_ctx_files(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\newcommand{\\imgdir}{Figs}\n\\begin{document}\n"
                "\\includegraphics{Figs/miss.pdf}\n"
                "\\includegraphics{\\imgdir/x.pdf}\n\\end{document}\n"
            )
        },
    )
    ok, _note = graphic_missing_placeholder(ctx, None, "Figs/miss.pdf", {})
    assert ok
    assert (tmp_path / "Figs/miss.pdf").is_file()
    assert not (tmp_path / "imgdir").exists()


def test_probe_file_texmf_hit_not_stubbed(tmp_path: Path) -> None:
    """带后缀 arg 盘 miss 但 kpathsea 树可解 (mwe 族) → 跳过不遮蔽."""

    class _Eng:
        def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
            del cwd
            return (
                "/texmf/mwe/example-image.pdf" if fname == "example-image.pdf" else None
            )

    ctx = mk_ctx_files(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\usepackage{graphicx}\n"
                "\\begin{document}\n\\includegraphics{Figs/miss.pdf}\n"
                "\\includegraphics{example-image.pdf}\n\\end{document}\n"
            )
        },
    )
    ok, _note = graphic_missing_placeholder(ctx, _Eng(), "Figs/miss.pdf", {})
    assert ok
    assert (tmp_path / "Figs/miss.pdf").is_file()
    assert not (tmp_path / "example-image.pdf").exists()
