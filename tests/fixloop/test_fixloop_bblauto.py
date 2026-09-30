"""revtex `\\auto@bib` disarm emit —— `\\bibliography` → `\\input` 两改放点。

实证根因 (bblmath census, 5 cells): revtex 系（revtex4-x/emulateapj/aastex）
``\\bibliography`` 顺带 ``\\auto@bib@empty`` 解除 end-doc ``\\auto@bib``
探测；裸 ``\\input`` 改写丢失该解除 → ``\\test@bbl@sw`` 在 ``\\vbox`` 中把
``\\bibitem`` 必需组 cite key 当正文排印（``_``/``&``/``$`` → Missing$ →
invalid-in-math 级联；探测为真再三读 → 重复书目/Lonely \\item/env_mismatch）。
emit-site 在 ``\\input`` 前补 disarm 行; ``\\ifcsname``
守卫使非 revtex 工程运行时零操作。fixloop ``bbl_stub_rewrite`` 与
normalize ``use_bundled_bibliography`` 双侧统一 csname-let 形
(零字面 ``@``, 2105.11398 def-体预读实证)。
"""

from pathlib import Path

from texlate.compile.fixloop._builtins_bib import bbl_stub_rewrite
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.normalize import use_bundled_bibliography

#: 双侧统一 csname-let 形 (零字面 ``@``) —— normalize
#: ``use_bundled_bibliography`` 与 fixloop ``bbl_stub_rewrite`` 同文。
_DISARM_NORM = (
    r"\ifcsname auto\string@bib\endcsname"
    r"\expandafter\let\csname auto\string@bib\expandafter\endcsname"
    r"\csname \string@empty\endcsname\fi"
)
_DISARM_FIXLOOP = _DISARM_NORM


def _doc(docclass: str = "revtex4-1") -> str:
    return (
        f"\\documentclass{{{docclass}}}\n\\begin{{document}}\nx\n"
        "\\bibliography{refs}\n\\end{document}"
    )


def _bbl(tmp_path: Path, stem: str = "main") -> None:
    (tmp_path / f"{stem}.bbl").write_text(
        "\\begin{thebibliography}{9}\\end{thebibliography}"
    )


def test_disarm_emitted_before_input_revtex(tmp_path: Path) -> None:
    """revtex 形: ``\\bibliography`` 改写 → disarm 行紧贴 ``\\input`` 之前。"""
    main = tmp_path / "main.tex"
    main.write_text(_doc("revtex4-1"))
    _bbl(tmp_path)
    out = use_bundled_bibliography(main.read_text(), main)
    assert f"{_DISARM_NORM}\n\\input{{main.bbl}}" in out
    assert "\\bibliography" not in out


def test_disarm_emitted_non_revtex_same_text(tmp_path: Path) -> None:
    """非 revtex（article）同样落 disarm 文本——运行时 ``\\ifcsname`` 守卫。"""
    main = tmp_path / "main.tex"
    main.write_text(_doc("article"))
    _bbl(tmp_path)
    out = use_bundled_bibliography(main.read_text(), main)
    assert f"{_DISARM_NORM}\n\\input{{main.bbl}}" in out


def test_disarm_idempotent_second_pass(tmp_path: Path) -> None:
    """二跑幂等: 已含 ``\\input{main.bbl}`` → 整体不再改, disarm 不重复落。"""
    main = tmp_path / "main.tex"
    main.write_text(_doc())
    _bbl(tmp_path)
    once = use_bundled_bibliography(main.read_text(), main)
    twice = use_bundled_bibliography(once, main)
    assert twice == once
    assert twice.count(_DISARM_NORM) == 1


def test_bbl_stub_rewrite_emits_disarm(tmp_path: Path) -> None:
    """fixloop ``bbl_stub_rewrite`` 改写同样补 disarm（tectonic stub 臂）。"""
    (tmp_path / "main.tex").write_text(_doc())
    _bbl(tmp_path)
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ok, _note = bbl_stub_rewrite(ctx, None, None, {})
    assert ok
    out = (tmp_path / "main.tex").read_text()
    assert f"{_DISARM_FIXLOOP}\n\\input{{main.bbl}}" in out
    assert "\\bibliography" not in out
