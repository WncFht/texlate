"""svjour_clo_stub 内建 —— svjour.cls 零 .clo 伴船, noop stub 救 ClassError。

实证根因 (0905.0193): e-print 捆绑 svjour.cls (2003, Springer) 但零 .clo
伴船且 svjour 不在 TeX Live → ``\\documentclass[epj,nopacs]{svjour}`` 每选项
``\\InputIfFileExists{sv<opt>.clo}`` 落空 → ``\\journalopt`` 停 ``\\@empty``
→ ``\\ClassError{No valid journal specified}`` + ``\\stop``。
"""

from pathlib import Path

from _fixloopkit import mk_ctx

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins import svjour_clo_stub

_DOC_END = "\n\\begin{document}x\\end{document}\n"


def _main(tmp_path: Path, docclass: str) -> None:
    (tmp_path / "main.tex").write_text(docclass + _DOC_END, encoding="utf-8")


def test_svjour_clo_stub_happy(tmp_path: Path) -> None:
    r"""``\documentclass[epj,nopacs]{svjour}`` → svepj.clo + svnopacs.clo 落地。"""
    _main(tmp_path, "\\documentclass[epj,nopacs]{svjour}")
    ok, note = svjour_clo_stub(mk_ctx(tmp_path), None, None, {})
    assert ok
    assert "svepj.clo" in note
    assert "svnopacs.clo" in note
    assert "\\endinput" in (tmp_path / "svepj.clo").read_text(encoding="utf-8")
    assert "\\endinput" in (tmp_path / "svnopacs.clo").read_text(encoding="utf-8")


def test_svjour_clo_stub_preserves_existing(tmp_path: Path) -> None:
    """盘上真 .clo 不覆盖 (svepj.clo 哨兵原样), 只补缺件。"""
    _main(tmp_path, "\\documentclass[epj,nopacs]{svjour}")
    sentinel = "% real bundled clo\n"
    (tmp_path / "svepj.clo").write_text(sentinel, encoding="utf-8")
    ok, note = svjour_clo_stub(mk_ctx(tmp_path), None, None, {})
    assert ok
    assert (tmp_path / "svepj.clo").read_text(encoding="utf-8") == sentinel
    assert (tmp_path / "svnopacs.clo").is_file()
    assert "svnopacs.clo" in note


def test_svjour_clo_stub_no_options(tmp_path: Path) -> None:
    r"""``\documentclass{svjour}`` 无选项 → False, 不落 .clo。"""
    _main(tmp_path, "\\documentclass{svjour}")
    ok, note = svjour_clo_stub(mk_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no documentclass options" in note
    assert not list(tmp_path.glob("*.clo"))


def test_svjour_clo_stub_no_docclass(tmp_path: Path) -> None:
    r"""主文件无 ``\documentclass`` → False。"""
    (tmp_path / "main.tex").write_text(_DOC_END, encoding="utf-8")
    ok, _note = svjour_clo_stub(mk_ctx(tmp_path), None, None, {})
    assert not ok


def test_svjour_clo_stub_whitespace(tmp_path: Path) -> None:
    r"""选项表跨行/带空白 → 照常拆分, svepj.clo + svdraft.clo 落地。"""
    _main(tmp_path, "\\documentclass[\n epj , draft\n]{svjour}")
    ok, _note = svjour_clo_stub(mk_ctx(tmp_path), None, None, {})
    assert ok
    assert (tmp_path / "svepj.clo").is_file()
    assert (tmp_path / "svdraft.clo").is_file()


def test_svjour_clo_stub_skips_separator_options(tmp_path: Path) -> None:
    r"""``\documentclass[a/b,epj,x\y]{svjour}``——含 ``/``/``\`` 的选项跳过,
    svepj.clo 照常落地; 无 ``sva/`` 子目录、无反斜杠名文件
    (无此守卫时 ``_inject_write`` 的 ``mkdir(parents=True)`` 会真造 ``sva/``)。"""
    _main(tmp_path, "\\documentclass[a/b,epj,x\\y]{svjour}")
    ok, note = svjour_clo_stub(mk_ctx(tmp_path), None, None, {})
    assert ok
    assert "svepj.clo" in note
    assert (tmp_path / "svepj.clo").is_file()
    assert not (tmp_path / "sva").exists()
    assert not (tmp_path / "svx\\y.clo").exists()


def test_svjour_clo_stub_registered() -> None:
    """注册进 TRANSFORM_FNS (rules.yaml function: 面)。"""
    assert builtins.TRANSFORM_FNS["svjour_clo_stub"] is svjour_clo_stub
