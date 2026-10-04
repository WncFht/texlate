"""pinlabel_pdfximage_emulate 单测 (undef13 车道，task #219)。

机理 (1907.10349 holomorphic.tex:426 / 2403.00097 l.657 实证):
pinlabel.sty ``\\scan@header`` 的 .pdf 分支调 ``\\pdfximage cropbox{file}``
+ ``\\pdfximagebbox\\pdflastximage <1..4>`` 量 bbox —— 站点在 texmf
系统件 (fileset 外), file-line 错误却归 splice 内 ``\\includegraphics``
行 → err_outside_fileset=false; doc 源无字面 ``\\pdfximage`` →
prim_read_form/source_contains 皆不见 → guard(50)/polyfill(51) 条件
够不到，是 pdftex_prim 链上唯一盲区。

臂：cs_targeted_fix ``polyfill_pre`` 在 docclass 行前注 ``\\ifdefined``
守卫块 —— ``\\pdfximage`` 用 ``\\XeTeXpdffile`` 盒量真实 PDF 自然尺寸，
``\\pdfximagebbox`` 回 0bp/0bp/\\wd/\\ht (cropbox 原点近似，pinlabel
只取差值算缩放故全真)。真 xelatex 复现 + 翻正实证：
undef13 车道 repro-1907/emulate5 (4 枚 \\pinlabel 全落位)。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport

_RULE_ID = "pinlabel_pdfximage_emulate"

_MAIN = (
    "\\documentclass{amsart}\n"
    "\\usepackage{graphicx}\n"
    "\\usepackage{pinlabel}\n"
    "\\begin{document}\n"
    "\\begin{figure}\n"
    "\\labellist\n"
    "\\pinlabel a) at 30 200\n"
    "\\pinlabel $|v|=0$ at 40 0\n"
    "\\endlabellist\n"
    "\\includegraphics[height=3.5cm]{fig}\n"
    "\\end{figure}\n"
    "\\end{document}\n"
)


def _rs() -> Ruleset:
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _ctx(tmp_path: Path, main: str = _MAIN) -> LoopCtx:
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _match(
    ctx: LoopCtx, pay: str, rep: ErrReport, cat: str = "pdftex_prim"
) -> tuple[Rule | None, str]:
    return actions._match_apply(_rs(), ctx, None, cat, pay, rep)  # noqa: SLF001


# ----------------------------------------------------------------- 路由层
def test_route_pinlabel_cell_to_emulate_arm(tmp_path: Path) -> None:
    """pinlabel 装载稿 + pdftex_prim|pdfximage → 本臂中，docclass 行前排块。"""
    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=["./main.tex"])
    rule, _note = _match(ctx, "pdfximage", rep)
    assert rule is not None
    assert rule.id == _RULE_ID
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\pdfximage\\else" in out
    assert "\\def\\pdfximage#1#{\\texlatepdfximageload}" in out
    assert "\\chardef\\pdflastximage=1" in out
    assert "\\def\\pdfximagebbox#1#2{\\ifcase#2" in out
    # 注入点恒在 docclass 行前 —— pinlabel 于 preamble 装载，先备先觉。
    assert out.index("\\ifdefined\\pdfximage") < out.index("\\documentclass")


def test_route_non_pinlabel_pdfprim_not_stolen(tmp_path: Path) -> None:
    """无 pinlabel 证据的 pdfximage/pdfoutput 格 → 条件闸拒，让位常链。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    rep = ErrReport(file_stack=["./main.tex"])
    # pdfximage payload 但源无 pinlabel 证据：本臂闸拒 → 常链亦无可
    # 接站点 (guard 无 fileset 内字面 prim/polyfill 三臂皆拒) → None。
    rule, _note = _match(ctx, "pdfximage", rep)
    assert rule is None or rule.id != _RULE_ID
    assert any(d.startswith(f"{_RULE_ID}: cond skip") for d in ctx.declined)


def test_route_other_payload_passes_through(tmp_path: Path) -> None:
    """pinlabel 稿上非 pdfximage payload → builtin 表不中单格，不吃别人饭。"""
    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=["./main.tex"])
    # pdfcatalog: _CS_FIX_TABLE/overlay 无键 → 本臂 applied=False 让位。
    rule, _note = _match(ctx, "pdfcatalog", rep)
    assert rule is None or rule.id != _RULE_ID


def test_refire_idempotent(tmp_path: Path) -> None:
    """二次派发同标记 → snippet 已在文，本臂 applied=False 不再中。"""
    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=["./main.tex"])
    rule1, _ = _match(ctx, "pdfximage", rep)
    assert rule1 is not None
    assert rule1.id == _RULE_ID
    rule2, _ = _match(ctx, "pdfximage", rep)
    assert rule2 is None or rule2.id != _RULE_ID
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert out.count("\\ifdefined\\pdfximage") == 1


# ----------------------------------------------------------------- 条件闸
def test_cond_pinlabel_source_gate(tmp_path: Path) -> None:
    """source_contains 闸：装载形与裸词形双确认。"""
    rule = _rule(_RULE_ID)
    ctx = _ctx(tmp_path)
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, None, "pdfximage", ErrReport()
    )
    assert ok, why
    ctx2 = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    ok2, _ = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx2, None, "pdfximage", ErrReport()
    )
    assert not ok2


# ----------------------------------------------------------------- 真编译钉
_XELATEX = shutil.which("xelatex")
_KPSEWHICH = shutil.which("kpsewhich")


def _have_pinlabel() -> bool:
    if _KPSEWHICH is None:
        return False
    return (
        subprocess.run(  # noqa: S603
            [_KPSEWHICH, "pinlabel.sty"],
            capture_output=True,
            timeout=30,
            check=False,
        ).returncode
        == 0
    )


@pytest.mark.integration
@pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")
def test_real_xelatex_repro_and_fix(tmp_path: Path) -> None:
    """全真链钉：无 polyfill → Undefined \\pdfximage; 注入后 → 零 '!' 错。

    fig.pdf 由 xelatex 自身产出 (保证 xdvipdfmx 可解析); 未修态复现
    真稿标记 (l.N 行归 \\includegraphics), 修复态要求零错 + PDF 出。
    """
    # kpsewhich 探针进测试体——收集期不跑子进程 (deselect 零开销)
    if not _have_pinlabel():
        pytest.skip("pinlabel.sty not in texmf")
    (tmp_path / "figsrc.tex").write_text(
        "\\documentclass{article}\n\\usepackage{graphicx}\n"
        "\\begin{document}\n\\rule{2cm}{2cm}\n\\end{document}\n",
        encoding="utf-8",
    )
    subprocess.run(  # noqa: S603
        [_XELATEX, "-interaction=nonstopmode", "figsrc.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert (tmp_path / "figsrc.pdf").is_file()
    (tmp_path / "figsrc.pdf").rename(tmp_path / "fig.pdf")

    (tmp_path / "main.tex").write_text(_MAIN, encoding="utf-8")
    subprocess.run(  # noqa: S603
        [_XELATEX, "-interaction=nonstopmode", "main.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    log = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    assert "Undefined control sequence" in log
    assert "\\pdfximage" in log  # 未修态全真复现真稿标记

    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=["./main.tex"])
    rule, _note = _match(ctx, "pdfximage", rep)
    assert rule is not None
    assert rule.id == _RULE_ID

    subprocess.run(  # noqa: S603
        [_XELATEX, "-interaction=nonstopmode", "main.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    log2 = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    n_err = len(re.findall(r"^! ", log2, re.MULTILINE))
    assert n_err == 0, f"emulation 注入后仍 {n_err} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
