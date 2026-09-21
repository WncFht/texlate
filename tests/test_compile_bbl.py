"""use_bundled_bibliography 的 .bbl 复用注入——粒度/边界/幂等探针/读失败降级。

``\\bibliography{x}`` → ``\\input{<词干>.bbl}`` 的充要条件与形态覆盖
（docs/spec/translate.md §3.1 树级手术链 ``use_bundled_bibliography`` 条）。
"""

from pathlib import Path

import pytest

from texlate.compile.normalize import normalize_project, use_bundled_bibliography


# 11. bundled .bbl
def test_bundled_bibliography(tmp_path: Path) -> None:
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "\\bibliography{refs}\n\\end{document}"
    )
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )
    out = use_bundled_bibliography(main.read_text(), main)
    assert r"\input{main.bbl}" in out


def test_bundled_bibliography_bib_present_noop(tmp_path: Path) -> None:
    main = tmp_path / "main.tex"
    main.write_text("\\bibliography{refs}")
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )
    (tmp_path / "refs.bib").write_text("@article{a,title={t}}")
    assert use_bundled_bibliography(main.read_text(), main) == "\\bibliography{refs}"


def test_bundled_bibliography_verbatim_immune(tmp_path: Path) -> None:
    """lstlisting 里展示的 \\bibliography 示例不得被改写（verbatim 体遮盖）。"""
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{lstlisting}\n\\bibliography{refs}\n\\end{lstlisting}\n"
        "\\end{document}"
    )
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )
    assert use_bundled_bibliography(main.read_text(), main) == main.read_text()


def test_bundled_bibliography_multiple_bibliography_only_first(
    tmp_path: Path,
) -> None:
    """多只缺库 `\bibliography` 只替换首个——单份 .bbl 不能重复排版。"""
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "\\bibliography{goneA}\ntext\n\\bibliography{goneB}\n\\end{document}"
    )
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )
    out = use_bundled_bibliography(main.read_text(), main)
    assert out.count(r"\input{main.bbl}") == 1
    assert r"\bibliography{goneB}" in out  # 第二只保留原状


def test_bundled_bibliography_bib_searched_at_compile_cwd(tmp_path: Path) -> None:
    """`.bib` 存在性按编译 cwd 判——refs.bib 在 main 目录时 sub 文件不重写。"""
    sub = tmp_path / "chaps"
    sub.mkdir()
    one = sub / "one.tex"
    one.write_text("body\n\\bibliography{refs}\n")
    (tmp_path / "refs.bib").write_text("@article{a,title={t}}")
    (sub / "one.bbl").write_text("\\begin{thebibliography}{9}\\end{thebibliography}")
    # cwd=None → 退回声明文件目录（chaps/refs.bib 缺席 → 重写）
    out = use_bundled_bibliography(one.read_text(), one)
    assert r"\input{one.bbl}" in out
    # cwd=tmp_path（main 目录）→ refs.bib 在场 → 不重写
    out2 = use_bundled_bibliography(one.read_text(), one, cwd=tmp_path)
    assert out2 == one.read_text()


def test_bundled_bibliography_space_target_bare_input_not_filled(
    tmp_path: Path,
) -> None:
    """target 含空白 + 裸 ``\\input`` 不算已填充——TeX 扫名止于空白读不到全名。

    braced 形同 target 仍算已填充（读到 ``}`` 收，空白是合法名字成分）。
    """
    main = tmp_path / "my main.tex"
    (tmp_path / "my main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )
    # 裸名形：TeX 只读 ``my``——probe 不得报已填充，bibliography 照常替换
    main.write_text("\\input my main.bbl\n\\bibliography{refs}\n")
    out = use_bundled_bibliography(main.read_text(), main)
    assert "\\bibliography{refs}" not in out
    # braced 形：完整名可达——幂等不改
    main.write_text("\\input{my main.bbl}\n\\bibliography{refs}\n")
    out2 = use_bundled_bibliography(main.read_text(), main)
    assert out2 == main.read_text()


# ------------------------------------------- bundled .bbl 粒度与边界（wave3）


def _mk_bbl(tmp_path: Path) -> Path:
    (tmp_path / "main.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}\n"
    )
    return tmp_path / "main.tex"


def _deny_bytes(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """让 ``target`` 的 ``read_bytes`` 抛 EACCES（chmod 在 root/ACL 环境会失效）。"""
    real_read = Path.read_bytes

    def _patched(self: Path) -> bytes:
        if self == target:
            raise PermissionError(13, "EACCES")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", _patched)


def test_bbl_unreadable_skips_bib_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bbl 在但读不动 → 书目步返回原文而非抛 OSError。"""
    main = _mk_bbl(tmp_path)
    main.write_text("\\bibliography{gone}\n")
    _deny_bytes(monkeypatch, tmp_path / "main.bbl")
    assert use_bundled_bibliography(main.read_text(), main) == main.read_text()


def test_normalize_project_bbl_eacces_keeps_other_surgery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工程级实证：bbl 读失败不再连坐——转码手术仍落盘、``\\bibliography`` 保留。"""
    main = tmp_path / "main.tex"
    main.write_bytes("caf\xe9\n\\bibliography{gone}\n".encode("latin-1"))
    (tmp_path / "main.bbl").write_text("\\begin{thebibliography}{9}x\n")
    _deny_bytes(monkeypatch, tmp_path / "main.bbl")
    stats = normalize_project(tmp_path, "xelatex", "main.tex")
    assert stats["rewritten"] == 1  # 转码手术没丢
    text = main.read_text()
    assert "café" in text
    assert r"\bibliography{gone}" in text  # 书目步跳过——未注入 \input


@pytest.mark.parametrize(
    "prior",
    [
        r"\input{main.bbl}",
        r"\input{./main.bbl}",
        r"\input { ./main.bbl }",
        r'\input"main.bbl"',
        r'\input"./main.bbl"',
        r"\input main.bbl",
        r"\input ./main.bbl",
        "\\input\tmain.bbl",
        r"\input main.bbl\relax",
        r"\input main.bbl trailing",
    ],
)
def test_bbl_input_probe_variants(tmp_path: Path, prior: str) -> None:
    """已注入形态（``./`` 前缀、引号形、裸名形）被幂等探针认出——不再二次注入。"""
    main = _mk_bbl(tmp_path)
    main.write_text("\\bibliography{gone}\n" + prior + "\n")
    assert use_bundled_bibliography(main.read_text(), main) == main.read_text()


@pytest.mark.parametrize(
    "prior",
    [
        r'\input{main.bbl"',  # { 开 " 收——失配对，\@iinput 扫描错读不出本 bbl
        r'\input"main.bbl}',  # " 开 } 收——同理
        r"\input{main.bbl",  # 未闭合组
        r'\input"main.bbl',  # 未闭合引号
        r"\input main.bblx",  # 前缀撞名——真读的是 main.bblx（异文件）
        r"\input main.bbl}",  # } 是文件名成分——真读 main.bbl}
        r"\input main.bbl]",
        r"\input main.bbl_x",
        r'\input main.bbl"x"',  # " 切引号模——拼出 main.bblx
        r"\input main.bbl'x'",
        r"\inputmain.bbl",  # 控制词 \inputmain 不是 \input
    ],
)
def test_bbl_input_probe_noninput_forms_still_inject(
    tmp_path: Path, prior: str
) -> None:
    """失配对/前缀撞名/假 ``\\input`` 均非真输入——``\\bibliography`` 照换不误。"""
    main = _mk_bbl(tmp_path)
    main.write_text("\\bibliography{gone}\n" + prior + "\n")
    out = use_bundled_bibliography(main.read_text(), main)
    assert out.startswith(
        "\\ifcsname auto\\string@bib\\endcsname"
        "\\expandafter\\let\\csname auto\\string@bib\\expandafter\\endcsname"
        "\\csname \\string@empty\\endcsname\\fi\n\\input{main.bbl}\n"
    )


def test_bbl_input_probe_other_file_still_injects(tmp_path: Path) -> None:
    """``\\input{other.bbl}`` 不是本 bbl——书目位照换不误。"""
    main = _mk_bbl(tmp_path)
    main.write_text("\\bibliography{gone}\n\\input{other.bbl}\n")
    out = use_bundled_bibliography(main.read_text(), main)
    assert r"\input{main.bbl}" in out


def test_bbl_bibliography_parent_ref_counts_as_missing(tmp_path: Path) -> None:
    """``\\bibliography{../outside/x}``：盘上在也按缺席计（openin_any=p 够不着）。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.bib").write_text("@article{a,title={t}}\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.bbl").write_text("\\begin{thebibliography}{9}y\n")
    main = proj / "main.tex"
    main.write_text("\\bibliography{../outside/x}\n")
    out = use_bundled_bibliography(main.read_text(), main)
    assert out == (
        "\\ifcsname auto\\string@bib\\endcsname"
        "\\expandafter\\let\\csname auto\\string@bib\\expandafter\\endcsname"
        "\\csname \\string@empty\\endcsname\\fi\n\\input{main.bbl}\n"
    )


def test_bbl_bibliography_absolute_ref_counts_as_missing(tmp_path: Path) -> None:
    """绝对路径 .bib 盘上存在也按缺席计——同 openin_any=p 口径。"""
    bib = tmp_path / "real.bib"
    bib.write_text("@article{a,title={t}}\n")
    main = _mk_bbl(tmp_path)
    main.write_text(f"\\bibliography{{{bib}}}\n")
    out = use_bundled_bibliography(main.read_text(), main)
    assert r"\input{main.bbl}" in out
