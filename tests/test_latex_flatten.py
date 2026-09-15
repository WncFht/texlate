r"""flatten_inputs 的单测：``\input`` 八形态、壳剥离、tag 提取、防环（§7）。"""

from pathlib import Path
from typing import TYPE_CHECKING

from texlate.latex.flatten import flatten_inputs, strip_doc_shell

if TYPE_CHECKING:
    from texlate.latex.model import ScanWarning


def _w(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_input_brace(tmp_path: Path) -> None:
    _w(tmp_path, "chap.tex", "CHAP CONTENT")
    out = flatten_inputs("A\n\\input{chap}\nB", str(tmp_path))
    assert "CHAP CONTENT" in out


def test_input_bare_filename(tmp_path: Path) -> None:
    r"""裸文件名形 ``\input chap``（无花括号）。"""
    _w(tmp_path, "chap2.tex", "BARE CONTENT")
    out = flatten_inputs("A\n\\input chap2\nB", str(tmp_path))
    assert "BARE CONTENT" in out


def test_include(tmp_path: Path) -> None:
    _w(tmp_path, "inc.tex", "INC CONTENT")
    out = flatten_inputs("\\include{inc}", str(tmp_path))
    assert "INC CONTENT" in out


def test_input_if_file_exists(tmp_path: Path) -> None:
    r"""``\InputIfFileExists{f}{then}{else}``：只消费 file 参数，then/else 留流内。"""
    _w(tmp_path, "opt.tex", "OPT CONTENT")
    out = flatten_inputs("\\InputIfFileExists{opt}{THENPART}{ELSEPART}", str(tmp_path))
    assert "OPT CONTENT" in out
    assert "THENPART" in out
    assert "ELSEPART" in out


def test_import_subdir(tmp_path: Path) -> None:
    r"""``\import{dir/}{file}``：相对子目录解析。"""
    _w(tmp_path / "sub", "deep.tex", "DEEP CONTENT")
    out = flatten_inputs("\\import{sub/}{deep}", str(tmp_path))
    assert "DEEP CONTENT" in out


def test_subfile_strips_doc_shell(tmp_path: Path) -> None:
    r"""``\subfile`` 展开剥 document 壳——壳内正文见光，壳外 preamble 丢弃。"""
    _w(
        tmp_path,
        "sub.tex",
        "\\documentclass{article}\n\\begin{document}\nSUB BODY\n\\end{document}\n",
    )
    out = flatten_inputs("MAIN\n\\subfile{sub}\nEND", str(tmp_path))
    assert "SUB BODY" in out
    assert "documentclass" not in out


def test_includestandalone_same_shell(tmp_path: Path) -> None:
    _w(
        tmp_path,
        "sa.tex",
        "\\documentclass{article}\n\\begin{document}\nSA BODY\n\\end{document}",
    )
    out = flatten_inputs("\\includestandalone{sa}", str(tmp_path))
    assert "SA BODY" in out
    assert "documentclass" not in out


def test_catchfilebetweentags(tmp_path: Path) -> None:
    r"""``\CatchFileBetweenTags\cs{f}{tag}`` 提取 ``%<*tag>``…``%</tag>`` 区。"""
    _w(tmp_path, "tags.tex", "PRE\n%<*mytag>\nTAGGED BODY\n%</mytag>\nPOST\n")
    out = flatten_inputs("\\CatchFileBetweenTags\\cs{tags}{mytag}", str(tmp_path))
    assert "TAGGED BODY" in out
    assert "PRE" not in out


def test_comment_input_not_expanded(tmp_path: Path) -> None:
    r"""注释掉的 ``\input`` 不展开（铁律 3）。"""
    _w(tmp_path, "ghost.tex", "GHOST MUST NOT APPEAR")
    out = flatten_inputs("A\n% \\input{ghost}\nB", str(tmp_path))
    assert "GHOST" not in out


def test_verbatim_input_not_expanded(tmp_path: Path) -> None:
    r"""verbatim 环境内的 ``\input`` 不展开。"""
    _w(tmp_path, "ghost2.tex", "GHOST2 MUST NOT APPEAR")
    out = flatten_inputs(
        "\\begin{verbatim}\n\\input{ghost2}\n\\end{verbatim}", str(tmp_path)
    )
    assert "GHOST2" not in out


def test_nested_input_resolves_vs_subdir(tmp_path: Path) -> None:
    r"""嵌套 ``\input``：先相对 including 文件目录，再回退项目根。"""
    _w(tmp_path / "sub", "a.tex", "\\input{b}\nA-END")
    _w(tmp_path / "sub", "b.tex", "B CONTENT")
    out = flatten_inputs("\\input{sub/a}", str(tmp_path))
    assert "B CONTENT" in out
    assert "A-END" in out


def test_root_dir_fallback(tmp_path: Path) -> None:
    r"""including 目录找不到 → 回退 root_dir。"""
    _w(tmp_path / "sub", "a.tex", "\\input{rootonly}\n")
    _w(tmp_path, "rootonly.tex", "ROOT CONTENT")
    out = flatten_inputs("\\input{sub/a}", str(tmp_path / "sub"), str(tmp_path))
    assert "ROOT CONTENT" in out


def test_seen_blocks_reinclude(tmp_path: Path) -> None:
    r"""W12 钉行为：同一文件二次 ``\input`` 被 ``_seen`` 跳过（防环优先）。"""
    _w(tmp_path, "dup.tex", "DUP CONTENT")
    out = flatten_inputs("\\input{dup}\nmid\n\\input{dup}", str(tmp_path))
    assert out.count("DUP CONTENT") == 1


def test_cycle_protected(tmp_path: Path) -> None:
    r"""a↔b 互引断环不挂死。"""
    _w(tmp_path, "a.tex", "A\\input{b}")
    _w(tmp_path, "b.tex", "B\\input{a}")
    out = flatten_inputs("\\input{a}\n\\input{a}", str(tmp_path))
    assert "A" in out
    assert "B" in out


def test_uppercase_tex_extension(tmp_path: Path) -> None:
    r"""``.TEX`` 大写扩展名在野存在（corpus_v3）——大小写敏感 FS 上也要命中。"""
    _w(tmp_path, "up.TEX", "UPPER CONTENT")
    out = flatten_inputs("\\input{up}", str(tmp_path))
    assert "UPPER CONTENT" in out


def test_missing_input_warning(tmp_path: Path) -> None:
    warns: list[ScanWarning] = []
    out = flatten_inputs("\\input{nonexistent}", str(tmp_path), warnings=warns)
    assert "\\input{nonexistent}" in out  # 找不到 → 原文保留
    assert any(w.kind == "missing_input" for w in warns)


def test_depth_cap() -> None:
    r"""``MAX_INPUTS`` 深度上限：超限原样返回。"""
    deep = "\\input{x}" * 1
    out = flatten_inputs(deep, "/nonexistent-dir", depth=99)
    assert out == deep


def test_strip_doc_shell_no_begin() -> None:
    assert strip_doc_shell("plain body") == "plain body"


def test_strip_doc_shell_no_end() -> None:
    out = strip_doc_shell("pre\\begin{document}BODY")
    assert out == "BODY"
