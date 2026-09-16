"""probe.py 单测：声明依赖三分支解析 + 路由信号 + compiled_dependencies 差分。

``target_probe`` 用小型假 workdir（本地 sty/cls/子目录 input + 注入的迷你
TlpdbIndex）覆盖 local/tl_pkg/missing 三分支；``deps_diff``/``dep_seen``
打 .fls/.mk 权威集对期望集的差分语义（真缺失 vs 路径/时序问题）。
"""

from pathlib import Path

from texlate.compile.fixloop.ctan import TlpdbIndex
from texlate.compile.probe import (
    dep_seen,
    deps_diff,
    target_probe,
)

_INDEX = TlpdbIndex(
    {
        "amsmath.sty": ["amsmath"],
        "article.cls": ["latex"],
        "bbm.sty": ["bbm"],
        "hyperref.sty": ["hyperref"],
        "minted.sty": ["minted"],
        "pstricks.sty": ["pstricks"],
        "revtex4-2.cls": ["revtex"],
    }
)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_three_way_resolution(tmp_path: Path) -> None:
    """local / tl_pkg / missing 三分支 + transitive \\input 跟进。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{myclass}\n"
        "\\usepackage{amsmath,localpkg}\n"
        "\\usepackage{totallybogus}\n"
        "\\input{macros}\n"
        "\\input{absent}\n"
        "\\begin{document}Hi\\end{document}\n",
    )
    _write(tmp_path, "myclass.cls", "\\LoadClass{article}\n")
    _write(tmp_path, "localpkg.sty", "\\ProvidesPackage{localpkg}\n")
    _write(tmp_path, "macros.tex", "\\usepackage{hyperref}\n\\def\\x{1}\n")

    rep = target_probe(tmp_path, "main.tex", _INDEX)
    by_name = {d.fname: d for d in rep.deps}
    assert by_name["myclass.cls"].resolved == "local"
    assert by_name["myclass.cls"].detail == "myclass.cls"
    assert by_name["amsmath.sty"].resolved == "tl_pkg"
    assert by_name["amsmath.sty"].detail == "amsmath"
    assert by_name["localpkg.sty"].resolved == "local"
    assert by_name["totallybogus.sty"].resolved == "missing"
    assert by_name["macros.tex"].resolved == "local"
    assert by_name["absent.tex"].resolved == "missing"
    # transitive：macros.tex 里的 hyperref 也被解析（索引命中）
    assert by_name["hyperref.sty"].resolved == "tl_pkg"
    assert by_name["hyperref.sty"].declared_in == "macros.tex"
    assert rep.missing == ["absent.tex", "totallybogus.sty"]
    assert rep.tl_packages == ["amsmath", "hyperref"]
    assert rep.inputs == ["main.tex", "macros.tex"]
    assert rep.index_available


def test_masked_declarations_ignored(tmp_path: Path) -> None:
    """注释/verbatim 内的假声明不产生依赖项。"""
    _write(
        tmp_path,
        "main.tex",
        "% \\usepackage{ghostpkg}\n"
        "\\begin{verbatim}\n\\usepackage{verbpkg}\n\\end{verbatim}\n"
        "\\usepackage{amsmath}\n"
        "\\begin{document}x\\end{document}\n",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert [d.fname for d in rep.deps] == ["amsmath.sty"]


def test_body_usepackage_not_scanned(tmp_path: Path) -> None:
    """\\begin{document} 之后的 \\usepackage 不是 preamble 声明。"""
    _write(
        tmp_path,
        "main.tex",
        "\\usepackage{amsmath}\n"
        "\\begin{document}\n"
        "正文 \\usepackage{latepkg} 提及\n"
        "\\end{document}\n",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert [d.fname for d in rep.deps] == ["amsmath.sty"]


def test_subdir_input_relative_to_declaring_file(tmp_path: Path) -> None:
    """\\input 按声明文件目录解析（子目录文件声明相对路径）。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\input{chaps/one}\n"
        "\\begin{document}x\\end{document}\n",
    )
    _write(tmp_path, "chaps/one.tex", "\\input{shared}\n内容\n")
    _write(tmp_path, "chaps/shared.tex", "\\usepackage{totallybogus}\n")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert rep.inputs == ["main.tex", "chaps/one.tex", "chaps/shared.tex"]
    assert rep.missing == ["totallybogus.sty"]


def test_signal_pstricks_prefers_xelatex(tmp_path: Path) -> None:
    """pstricks 声明 → prefer_engine=xelatex（xdvipdfmx 硬墙）。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage{pstricks}\n"
        "\\begin{document}x\\end{document}\n",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert rep.prefer_engine == "xelatex"
    assert any("pstricks" in n for n in rep.notes)


def test_signal_eps_input_prefers_xelatex(tmp_path: Path) -> None:
    """.eps 声明输入 → prefer_engine=xelatex。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\input{plot.eps}\n"
        "\\begin{document}x\\end{document}\n",
    )
    _write(tmp_path, "plot.eps", "%!PS-Adobe\n")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert rep.prefer_engine == "xelatex"


def test_signal_minted_shell_escape_and_frozencache(tmp_path: Path) -> None:
    """minted → -shell-escape；frozencache 在源 → tectonic 优先无 flag。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage{minted}\n"
        "\\begin{document}x\\end{document}\n",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert "-shell-escape" in rep.flags
    assert rep.prefer_engine != "xelatex"

    _write(
        tmp_path,
        "frozen.tex",
        "\\documentclass{article}\n\\usepackage[frozencache]{minted}\n"
        "\\begin{document}x\\end{document}\n",
    )
    rep2 = target_probe(tmp_path, "frozen.tex", _INDEX)
    assert rep2.prefer_engine == "tectonic"
    assert "-shell-escape" not in rep2.flags


def test_signal_bitmap_font_note_only(tmp_path: Path) -> None:
    """bbm 位图字体包 → tectonic 高风险 note，不直接改路由。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\usepackage{bbm}\n"
        "\\begin{document}x\\end{document}\n",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert rep.prefer_engine is None
    assert any("高风险" in n for n in rep.notes)


def test_documentstyle_latex209_note(tmp_path: Path) -> None:
    """\\documentstyle → latex209_suspect note。"""
    _write(tmp_path, "main.tex", "\\documentstyle{article}\nx\n")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert any("latex209_suspect" in n for n in rep.notes)


def test_missing_main_empty_report(tmp_path: Path) -> None:
    """主文件缺席 → 空报告 + note，不抛。"""
    rep = target_probe(tmp_path, "nope.tex", _INDEX)
    assert rep.deps == []
    assert rep.inputs == []
    assert any("nope.tex" in n for n in rep.notes)


def test_deps_diff_authoritative(tmp_path: Path) -> None:
    """expected vs recorded 差分：seen/unseen/extra + saw() basename 兜底。"""
    del tmp_path
    diff = deps_diff(
        ["main.tex", "macros.tex", "gone.sty"],
        ["main.tex", "macros.tex", "extra.def"],
    )
    assert diff.authoritative
    assert diff.seen == ["macros.tex", "main.tex"]
    assert diff.unseen == ["gone.sty"]
    assert diff.extra == ["extra.def"]
    assert diff.saw("main.tex") is True
    assert diff.saw("gone.sty") is False


def test_deps_diff_no_record() -> None:
    """recorded=None → authoritative=False，saw→None（不可判而非 False）。"""
    diff = deps_diff(["main.tex"], None)
    assert not diff.authoritative
    assert diff.unseen == ["main.tex"]
    assert diff.seen == []
    assert diff.saw("main.tex") is None


def test_dep_seen_basename_and_none() -> None:
    """fixloop 诊断消费点：basename 匹配 .fls 的 root 相对路径。"""
    recorded = ["sub/foo.sty", "main.tex"]
    assert dep_seen(recorded, "foo.sty") is True
    assert dep_seen(recorded, "sub/foo.sty") is True
    assert dep_seen(recorded, "bar.sty") is False
    assert dep_seen(None, "foo.sty") is None
