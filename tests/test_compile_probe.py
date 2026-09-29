"""probe.py 单测：声明依赖三分支解析 + 路由信号 + compiled_dependencies 差分。

``target_probe`` 用小型假 workdir（本地 sty/cls/子目录 input + 注入的迷你
TlpdbIndex）覆盖 local/tl_pkg/missing 三分支；``deps_diff``/``dep_seen``
打 .fls/.mk 权威集对期望集的差分语义（真缺失 vs 路径/时序问题）。
"""

from pathlib import Path

from conftest import _write

from texlate.compile.ctan import TlpdbIndex
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
    }
)


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


def test_subdir_input_resolves_at_compile_cwd(tmp_path: Path) -> None:
    r"""`\input` 按编译 cwd（main 目录）解析——声明文件自身目录不在搜索路径。

    xelatex TL2026 + tectonic 0.15 实证：`chaps/one.tex` 里 `\input{shared}`
    找 `cwd/shared.tex` 而非 `chaps/shared.tex`（`File 'shared.tex' not
    found`）——探针须复刻该解析模型，否则 missing 预判漏报。
    """
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\input{chaps/one}\n"
        "\\begin{document}x\\end{document}\n",
    )
    _write(tmp_path, "chaps/one.tex", "\\input{shared}\n内容\n")
    _write(tmp_path, "chaps/shared.tex", "\\usepackage{totallybogus}\n")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    # chaps/shared.tex 引擎读不到：不进 inputs、不报其内部声明；
    # cwd 下无 shared.tex → shared.tex 记 missing（真缺失预判）。
    assert rep.inputs == ["main.tex", "chaps/one.tex"]
    assert rep.missing == ["shared.tex"]
    assert "totallybogus.sty" not in [d.fname for d in rep.deps]

    _write(tmp_path, "shared.tex", "\\usepackage{totallybogus}\n")
    rep2 = target_probe(tmp_path, "main.tex", _INDEX)
    assert rep2.inputs == ["main.tex", "chaps/one.tex", "shared.tex"]
    assert rep2.missing == ["totallybogus.sty"]


def test_input_if_file_exists_missing_not_predicted(tmp_path: Path) -> None:
    r"""`\InputIfFileExists{ghost}` 缺席走 else 分支——非 missing_file。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\InputIfFileExists{localcfg}{}{}\n"
        "\\input{absent}\n\\begin{document}x\\end{document}\n",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    by_name = {d.fname: d for d in rep.deps}
    assert by_name["localcfg.tex"].resolved == "missing"
    assert rep.missing == ["absent.tex"]


def test_dead_tail_input_not_scanned(tmp_path: Path) -> None:
    r"""`\end{document}`/`\endinput` 死尾里的 `\input` 引擎不读、探针不报。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\input{stub}\n"
        "\\begin{document}x\\end{document}\n\\input{afterdoc}\n",
    )
    _write(tmp_path, "stub.tex", "body\n\\endinput\n\\input{afterendinput}\n")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert rep.inputs == ["main.tex", "stub.tex"]
    assert rep.missing == []


def test_main_outside_root_empty_report(tmp_path: Path) -> None:
    """main_rel 越出 work_dir → 空报告 + 注记（此前静默空inputs无解释）。"""
    work = tmp_path / "work"
    work.mkdir()
    _write(work, "main.tex", "\\documentclass{article}\n")
    _write(
        tmp_path,
        "outside.tex",
        "\\documentclass{article}\n\\begin{document}x\\end{document}\n",
    )
    rep = target_probe(work, "../outside.tex", _INDEX)
    assert rep.inputs == []
    assert any("越出" in n for n in rep.notes)


def test_circular_input_terminates(tmp_path: Path) -> None:
    r"""A↔B 循环 `\input`：visited 去重保证 BFS 终止、inputs 无重复。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\input{a}\n\\begin{document}x\\end{document}\n",
    )
    _write(tmp_path, "a.tex", "\\input{b}\n")
    _write(tmp_path, "b.tex", "\\input{a}\n\\input{main}\n")
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert rep.inputs == ["main.tex", "a.tex", "b.tex"]


def test_clean_name_filters_noise_tokens(tmp_path: Path) -> None:
    r"""`\input{\cs}` / `\input @tempb` 噪声 token 被滤——不进 deps/missing。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\input{\\foo}\n"
        "\\input @tempb\n"
        "\\begin{document}x\\end{document}\n",
    )
    rep = target_probe(tmp_path, "main.tex", _INDEX)
    assert [d for d in rep.deps if d.kind == "input"] == []
    assert rep.missing == []


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


def test_deps_diff_authoritative() -> None:
    """expected vs recorded 差分：seen/unseen/extra + saw() basename 兜底。"""
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
