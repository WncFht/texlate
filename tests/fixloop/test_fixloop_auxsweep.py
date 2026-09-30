r"""aux/toc 截断件清场 + 构造名 ``\input`` 依赖面钉。

被杀编译驻留的 ``\citation{`` 半行 aux (1511.06744 型) → r1 编译前清扫、
末轮 return 前清场; 行界齐整/转义花括号件不动; ``.toc`` 同机制。
``\input sv\X``/``\InputIfFileExists{aip-\X.tex}`` 构造名在
static_precheck 扫描与 ``_dep_stems`` 双侧不产依赖噪音。
"""

from pathlib import Path

from _fixloopkit import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import fixloop
from texlate.compile.fixloop.engine import _dep_stems


# ---------------------------------------------------------------- aux 截断清场
def test_aux_sweep_entry_poison(tmp_path: Path) -> None:
    r"""1511.06744 型: 被杀编译驻留的 ``\citation{`` 半行 aux → r1 编译前清扫。"""
    proj = make_proj(tmp_path)
    (proj / "main.aux").write_text("\\relax \n\\citation{", encoding="utf-8")
    cell = fixloop(proj, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert cell["verdict"] == "clean"
    assert not (proj / "main.aux").exists()
    assert any("aux-sweep" in e and "main.aux" in e for e in cell["log"])


def test_aux_sweep_midloop(tmp_path: Path) -> None:
    """round1 崩留截断 aux → round2 编译前清，不毒化后续轮。"""
    proj = make_proj(tmp_path)
    eng = MockEngine(
        [
            {
                "log": "! LaTeX Error: File `zhnumber.sty' not found.\n",
                "aux": "\\citation{",
            },
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"zhnumber.sty"},
    )
    cell = fixloop(proj, eng)
    assert cell["verdict"] == "clean"
    assert not (proj / "main.aux").exists()
    assert any("aux-sweep" in e for e in cell["log"])


def test_aux_sweep_healthy_kept(tmp_path: Path) -> None:
    """完整 aux (尾换行 + 花括号闭合) 不动——行界齐整缺行同。"""
    proj = make_proj(tmp_path)
    good = "\\relax \n\\citation{key1}\n\\newlabel{sec}{{1}{1}}\n"
    (proj / "main.aux").write_text(good, encoding="utf-8")
    cell = fixloop(proj, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert cell["verdict"] == "clean"
    assert (proj / "main.aux").read_text(encoding="utf-8") == good


def test_aux_sweep_escaped_braces_healthy(tmp_path: Path) -> None:
    r"""``\{``/``\}`` 转义不计深——含转义的健康 aux 不误删。"""
    proj = make_proj(tmp_path)
    good = "\\newlabel{a}{{\\{x\\}}{1}}\n"
    (proj / "main.aux").write_text(good, encoding="utf-8")
    fixloop(proj, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert (proj / "main.aux").exists()


def test_aux_sweep_toc_family(tmp_path: Path) -> None:
    r"""``.toc`` 同机制件: 截断 ``\contentsline`` 半行一样毒。"""
    proj = make_proj(tmp_path)
    (proj / "main.toc").write_text("\\contentsline{section}{", encoding="utf-8")
    fixloop(proj, MockEngine([{"log": CLEAN_LOG, "pdf": True}]))
    assert not (proj / "main.toc").exists()


def test_aux_sweep_final_round_leftover(tmp_path: Path) -> None:
    """末轮被杀留截断 aux → return 前清场，格后 post 复判不吃毒。"""
    proj = make_proj(tmp_path)
    eng = MockEngine([{"log": "partial\n", "timed_out": True, "aux": "\\citation{"}])
    cell = fixloop(proj, eng)
    assert cell["verdict"] == "unfixable:timeout"
    assert not (proj / "main.aux").exists()
    assert any("final aux-sweep" in e for e in cell["log"])


def test_static_precheck_skips_constructed_input(tmp_path: Path) -> None:
    r"""``\input sv\X``/``\InputIfFileExists{aip-\X.tex}`` 构造名不产 sv.tex/aip-.tex 噪音。"""
    main = (
        "\\documentclass{article}\n"
        "\\input sv\\CurrentOption.clo\n"
        "\\InputIfFileExists{aip-\\CurrentOption.tex}{}{}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    eng = MockEngine(
        [{"log": CLEAN_LOG, "pdf": True}],
        installable={"sv.tex", "aip-.tex", "sv\\CurrentOption.clo"},
        available={"article.cls"},
    )
    cell = fixloop(make_proj(tmp_path, main), eng)
    assert cell["verdict"] == "clean"
    assert not eng.install_calls


def test_dep_stems_constructed_names_skipped(tmp_path: Path) -> None:
    r"""``_dep_stems``: 构造名/裸名 \ 截断不产 stem, 真名照收。"""
    f = tmp_path / "m.tex"
    f.write_text(
        "\\input aip-\\CurrentOption.tex\n"
        "\\input {sv\\CurrentOption.clo}\n"
        "\\input realdep\n"
        "\\input sub/fig\n",
        encoding="utf-8",
    )
    assert _dep_stems(f) == ["realdep", "sub/fig"]
