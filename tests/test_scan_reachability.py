"""``scan_tex_tree(main=)`` 闭包裁剪 + ``input_dyn`` 动态名信号（t_6648 幽灵件实证）。

幽灵形态：e-print tarball 嵌整份复件论文（``dup/main.tex``），主文件链
永不引用——闭包外 parsed 件剔 ``unreachable`` 并入 ``support``（原文
保留）；fail-open 四闸（解析崩/动态名/漏网名 basename 配对/定位失败）
任一命中即全量保留——误剔方向 = 真内容不译，恒保守。
"""

from pathlib import Path

from texlate.latex.api import parse_tex, scan_tex_tree
from texlate.pipecore import scan_tree

_MAIN = "\\documentclass{article}\n\\begin{document}\n%CMD%\n\\end{document}\n"
_PROSE = (
    "The quick brown fox jumps over the lazy dog, and it is one "
    "of the best of them all. " * 3
)
_ONE = _PROSE
_GHOST = (
    "\\documentclass{article}\n\\begin{document}\n" + _PROSE + "\n\\end{document}\n"
)
_SUBFILE = (
    "\\documentclass[../main.tex]{subfiles}\n\\begin{document}\n"
    + _PROSE
    + "\n\\end{document}\n"
)


def _mk_tree(root: Path, cmd: str = "\\input{chap/one}") -> None:
    """三件套：骨架 main + chap/one（散文碎片）+ dup/main（复件论文幽灵）。"""
    (root / "chap").mkdir(parents=True)
    (root / "dup").mkdir()
    (root / "main.tex").write_text(_MAIN.replace("%CMD%", cmd), encoding="utf-8")
    (root / "chap" / "one.tex").write_text(_ONE, encoding="utf-8")
    (root / "dup" / "main.tex").write_text(_GHOST, encoding="utf-8")


def _rels(tree) -> list[str]:  # noqa: ANN001 -- TexTreeScan 内部面
    return [rel for _f, rel, _s in tree.parsed]


def test_unreachable_ghost_dropped(tmp_path: Path) -> None:
    """t_6648 形态：闭包外复件论文 → unreachable+support，不进 parsed。"""
    _mk_tree(tmp_path)
    tree = scan_tex_tree(tmp_path, main=tmp_path / "main.tex")
    assert _rels(tree) == ["chap/one.tex"]
    assert tree.unreachable == ["dup/main.tex"]
    assert "dup/main.tex" in tree.support


def test_no_main_keeps_all(tmp_path: Path) -> None:
    """``main=None`` 不做闭包——历史全量语义不变。"""
    _mk_tree(tmp_path)
    tree = scan_tex_tree(tmp_path)
    assert _rels(tree) == ["chap/one.tex", "dup/main.tex"]
    assert tree.unreachable == []


def test_dyn_input_failopen(tmp_path: Path) -> None:
    """``\\input{\\cs}`` 动态名 → ``input_dyn`` 信号 → 闭包不可证全量保留。"""
    _mk_tree(tmp_path, cmd="\\input{\\chapfile}\n\\input{chap/one}")
    tree = scan_tex_tree(tmp_path, main=tmp_path / "main.tex")
    assert _rels(tree) == ["chap/one.tex", "dup/main.tex"]
    assert tree.unreachable == []


def test_unresolved_name_keeps_basename(tmp_path: Path) -> None:
    """漏网字面名 ``\\input{missing/one}`` 与 ``chap/one.tex`` basename 配对
    → 保守保命（深度拒/真缺失不可分，过保方向）；幽灵照剔。"""
    _mk_tree(tmp_path, cmd="\\input{missing/one}")
    tree = scan_tex_tree(tmp_path, main=tmp_path / "main.tex")
    assert _rels(tree) == ["chap/one.tex"]
    assert tree.unreachable == ["dup/main.tex"]


def test_subfile_docclass_kept(tmp_path: Path) -> None:
    """subfiles 包形态：子文件自带 ``\\documentclass`` 但经 ``\\subfile`` 可达——
    docclass 不是剔出证据，闭包成员资格才是（gullet 真解析臂）。"""
    _mk_tree(tmp_path, cmd="\\input{chap/one}\n\\subfile{chap/two}")
    (tmp_path / "chap" / "two.tex").write_text(_SUBFILE, encoding="utf-8")
    tree = scan_tex_tree(tmp_path, main=tmp_path / "main.tex")
    assert _rels(tree) == ["chap/one.tex", "chap/two.tex"]
    assert tree.unreachable == ["dup/main.tex"]


def test_skeleton_main_not_parsed_but_children_kept(tmp_path: Path) -> None:
    """骨架 main（无散文）本就不入 parsed——闭包裁剪不受影响，可达碎片照留。"""
    _mk_tree(tmp_path)
    tree = scan_tex_tree(tmp_path, main=tmp_path / "main.tex")
    assert "main.tex" not in _rels(tree)  # 无散文 → support 桶
    assert "chap/one.tex" in _rels(tree)


def test_main_missing_failopen(tmp_path: Path) -> None:
    """main 缺席/不可读 → 闭包不可证 → 全量保留。"""
    _mk_tree(tmp_path)
    ghost_main = tmp_path / "dup" / "main.tex"
    tree = scan_tex_tree(tmp_path, main=tmp_path / "nonexistent.tex")
    assert _rels(tree) == ["chap/one.tex", "dup/main.tex"]
    tree2 = scan_tex_tree(tmp_path, main=ghost_main)
    # 幽灵作 main 时闭包 = 幽灵自身——真 main/chap 反成不可达：fail-open 不适用，
    # 但此场景只说明「传错 main 后果自负」——worker 侧 main_rel 恒经检出。
    assert "dup/main.tex" in _rels(tree2)


def test_input_dyn_units() -> None:
    """``input_dyn`` 计数：braced/bare-cs/fname 含 cs/in-arg 四位命中；
    字面名记 ``inputs[]`` 不计 dyn。"""
    assert parse_tex(r"x \input{\cs} y").input_dyn == 1
    assert parse_tex(r"x \input \cs y").input_dyn == 1
    assert parse_tex(r"x \input{a\b} y").input_dyn == 1
    assert parse_tex(r"\section{t \input{\y} z}").input_dyn == 1
    r = parse_tex(r"x \input{literal} y")
    assert r.input_dyn == 0
    assert [name for _p, name in r.inputs] == ["literal"]


def test_import_dyn_dir(tmp_path: Path) -> None:
    """``\\import{\\csdir}{file}`` 动态目录——file 纵字面闭包亦不可证。"""
    _mk_tree(tmp_path, cmd="\\import{\\csdir}{file}\n\\input{chap/one}")
    tree = scan_tex_tree(tmp_path, main=tmp_path / "main.tex")
    assert _rels(tree) == ["chap/one.tex", "dup/main.tex"]
    assert tree.unreachable == []


def test_pipecore_scan_tree_auto_main(tmp_path: Path) -> None:
    """e2e 臂 ``pipecore.scan_tree`` 缺省 ``find_main_tex`` 自检出——
    worker/e2e 闭包口径同源（检出失败即不裁）。"""
    _mk_tree(tmp_path)
    scans, chunks, fault, support = scan_tree(tmp_path)
    scan_files = [f.name for f, _res in scans]
    assert "one.tex" in scan_files
    assert all(f.parent.name != "dup" for f, _res in scans)
    assert "dup/main.tex" in support
    assert not fault
    assert chunks  # one.tex 的散文块在场
