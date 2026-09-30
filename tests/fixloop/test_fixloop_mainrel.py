r"""main_rel 显式主档 + ``find_main_tex``/``LoopCtx.tex_files`` 探测钉 (#191)。

译后 splice 树 CJK 主档易被 ``language_rank`` 降权误选 standalone 英文档
——显式 ``main_rel`` 胜出、缺件回退 ``main_fallback`` 留痕;
``find_main_tex`` 标名档先于语种档、宽松档认 ``.TEX``;
``tex_files`` 扩展名匹配大小写不敏感 (``.TEX``/``.STY`` 进 source_blob)。
"""

from pathlib import Path

from _fixloopkit import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.engine import LoopCtx, find_main_tex


def test_find_main_tex_loose_tier_uppercase(tmp_path: Path) -> None:
    r"""宽松档同样认 ``.TEX``——缺 ``\begin{document}`` 的待修工程不再落空。"""
    (tmp_path / "BROKEN.TEX").write_text(
        "\\documentclass{article}\nbody without begin-document\n",
        encoding="utf-8",
    )
    assert find_main_tex(tmp_path) == tmp_path / "BROKEN.TEX"


# ---------------------------------------------------------------- main_rel 指定主档 (#191)
def test_main_rel_overrides_language_demotion(tmp_path: Path) -> None:
    r"""ds209diag #191: 译后 splice 树 CJK 主档被 ``language_rank`` 降权,
    ``find_main_tex`` 误选 standalone 英文档——显式 ``main_rel`` 必须胜出。
    主档用非标名 (paper_zh.tex)：标名档排序已先于语种档, 盖不了此面。"""
    (tmp_path / "paper_zh.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "你好世界你好世界你好世界\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "tab1.tex").write_text(
        "\\documentclass{standalone}\n\\begin{document}\n"
        "English table body\n\\end{document}\n",
        encoding="utf-8",
    )
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True}])
    # 自动探测复现误选 (CJK 主档输给 standalone 英文档)
    assert find_main_tex(tmp_path) == tmp_path / "tab1.tex"
    cell = fixloop(tmp_path, eng, main_rel="paper_zh.tex")
    assert cell["main"] == "paper_zh.tex"
    assert cell["main_fallback"] is None
    assert cell["verdict"] == "clean"


def test_find_main_tex_canonical_name_beats_language(tmp_path: Path) -> None:
    r"""标名档先于语种档：译后树 ``main.tex`` (CJK 众数) 仍胜 standalone
    英文档——ds209diag #191 的 detect 侧修复 (main_rel 是调用方侧保险)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "你好世界你好世界你好世界\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "tab1.tex").write_text(
        "\\documentclass{standalone}\n\\begin{document}\n"
        "English table body\n\\end{document}\n",
        encoding="utf-8",
    )
    assert find_main_tex(tmp_path) == tmp_path / "main.tex"


def test_main_rel_missing_falls_back(tmp_path: Path) -> None:
    """指定主档缺件 → 回退 ``find_main_tex`` 且 ``main_fallback`` 留痕。"""
    make_proj(tmp_path)
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, main_rel="ghost.tex")
    assert cell["main"] == "main.tex"
    assert cell["main_fallback"] == "ghost.tex"
    assert cell["verdict"] == "clean"
    assert any("ghost.tex" in a for a in cell["advisories"])


def test_main_rel_docclass_less_honored(tmp_path: Path) -> None:
    r"""指定档无 ``\documentclass`` 也照用——缺 dc 正是待修形态, 信调用方。"""
    make_proj(tmp_path)
    (tmp_path / "frag.tex").write_text("broken body fragment\n", encoding="utf-8")
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, main_rel="frag.tex")
    assert cell["main"] == "frag.tex"
    assert cell["verdict"] == "clean"


def test_ctx_tex_files_case_insensitive(tmp_path: Path) -> None:
    r"""``LoopCtx.tex_files`` 扩展名匹配大小写不敏感——``.TEX`` 进 source_blob。"""
    (tmp_path / "PAPER.TEX").write_text("x", encoding="utf-8")
    (tmp_path / "a.tex").write_text("x", encoding="utf-8")
    (tmp_path / "STYLE.STY").write_text("x", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    assert {p.name for p in ctx.tex_files()} == {"PAPER.TEX", "a.tex", "STYLE.STY"}
