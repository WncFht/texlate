"""pdfprim 车道单测：`pdf@` 别名族 polyfill + \\pdfoutput=0 初值 + 门塌陷。

arm-A (pdftex-prim-under-xetex, 真缺口 = `pdf@` 族): breakurl/pdfmark/
pdftexcmds 系包体在 pdftex 下自导原语绑定，xelatex 全缺; 报错站点在
包体宏展开帧 (file_stack 归 doc → err_outside_fileset 不中), fileset
源无字面 (source_contains 不中) → ``payload_pattern:"@"`` 臂直放行
polyfill。@-名注入文本裹 ``_AT_LETTER_PRE/POST`` exact-restore @=11
对 + 裸形 ``\\ifdefined\\<prim>\\else<def>\\<prim>\\fi`` —— ``\\csname``/
``\\ifcsname`` 形不可用 (未定义名冻结 ``\\relax`` → ``\\newbox``/
``\\newcount`` 的 ``\\@ifdefinable`` 闸 already-defined)。

arm-B (pdftex-gated-codepath): ``\\if<letters>pdf`` 开关族与
``\\ifx\\pdfoutput\\undefined`` 存在探针把能力段锁进死臂 →
``pdftex_gate_collapse``(52) 塌 ``\\iftrue`` (pdf 臂 = 能力臂 / undefined
真臂 = xetex 诚实臂，门消解后对 polyfill 注入的 ``\\pdfoutput`` 定义
免疫 —— 0712.1016 自产缺陷根修); ``\\pdfoutput`` 初值 ``=0`` 保持
``\\ifnum`` 值探针诚实假。dedup 收窄到 ``\\@ifdefinable`` 闸系定义位
(``\\newX``/``\\newcommand`` 族): 头注再 ``\\newcount`` 会撞稿自带
定义位成 already-defined; ``\\def``/``\\let``/``\\chardef`` 重绑无闸不收。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.fixloop import (
    Ruleset,
    actions,
    builtins,
    load_ruleset,
)
from texlate.compile.fixloop.builtins import pdfprim
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport

_XELATEX = shutil.which("xelatex")
_COMPILE = pytest.mark.skipif(_XELATEX is None, reason="xelatex not installed")

_MAIN = (
    "\\documentclass{article}\n\\usepackage{somepkg}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)


def _rs() -> Ruleset:
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _ctx(tmp_path: Path, main: str = _MAIN) -> LoopCtx:
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _match(ctx: LoopCtx, cat: str, pay: str | None, rep: ErrReport) -> Rule | None:
    rule, _note = actions._match_apply(  # noqa: SLF001 - 路由行为直驱
        _rs(), ctx, None, cat, pay, rep
    )
    return rule


# ---------------------------------------------------------------- 注册/接线
def test_at_family_tables_registered_disjoint() -> None:
    """`pdf@` 族入 PDFTEX_PRIMS; box/toks/count/argful 四臂互斥。"""
    at_names = {p for p in builtins.PDFTEX_PRIMS if "@" in p}
    assert "pdf@box" in at_names
    assert "pdf@addtoksx" in at_names
    assert frozenset({"pdf@box"}) == pdfprim._PRIM_BOXISH  # noqa: SLF001
    buckets = [
        pdfprim._PRIM_COUNTISH,  # noqa: SLF001
        pdfprim._PRIM_TOKSISH,  # noqa: SLF001
        pdfprim._PRIM_DIMENISH,  # noqa: SLF001
        pdfprim._PRIM_BOXISH,  # noqa: SLF001
        set(pdfprim._PRIM_ARGFUL),  # noqa: SLF001
    ]
    for i, a in enumerate(buckets):
        for b in buckets[i + 1 :]:
            assert not (set(a) & set(b))
    for prim in at_names:
        assert any(prim in b for b in buckets), prim


def test_polyfill_condition_carries_payload_pattern_arm() -> None:
    """polyfill condition.any 挂 payload_pattern:@ 臂。"""
    cond = _rule("pdftex_prim_polyfill").condition
    assert {"payload_pattern": "@"} in cond["any"]


def test_cond_payload_pattern_dispatch(tmp_path: Path) -> None:
    """payload_pattern 键：`@` 中 `pdf@box`, 不中 `pdfoutput`。"""
    ctx = _ctx(tmp_path)
    rule = _rule("pdftex_prim_polyfill")
    ok, why = actions._cond_ok(  # noqa: SLF001
        {"payload_pattern": "@"}, rule, ctx, None, "pdf@box", ErrReport()
    )
    assert ok, why
    ok, _why = actions._cond_ok(  # noqa: SLF001
        {"payload_pattern": "@"}, rule, ctx, None, "pdfoutput", ErrReport()
    )
    assert not ok


def test_cond_at_payload_no_source_evidence_passes(tmp_path: Path) -> None:
    """fileset 内站点 + 源无字面 → `pdf@` payload 仍放行 (定义上即包内宏)。"""
    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=["./main.tex"])
    rule = _rule("pdftex_prim_polyfill")
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, None, "pdf@box", rep
    )
    assert ok, why


# ---------------------------------------------------------------- @-族 arm 直驱
def test_arm_pdfatbox_newbox_wrapped(tmp_path: Path) -> None:
    """``pdf@box`` → AT_LETTER 包裹内 ``\\newbox`` (breakurl ``\\sbox`` 全真)。"""
    ctx = _ctx(tmp_path)
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdf@box", {})
    assert ok, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\pdf@box\\else\\newbox\\pdf@box\\fi" in out
    assert "\\catcode 64=11" in out  # exact-restore @=11 包裹在
    assert "\\TeXlateAtRestore" in out
    assert out.index("\\ifdefined\\pdf@box") < out.index("\\documentclass")


def test_arm_at_family_arm_dispatch(tmp_path: Path) -> None:
    """@-族分派：box/toks/count/argful/条件五形各落本臂。"""
    cases = {
        "pdf@box": "\\newbox\\pdf@box",
        "pdf@toks": "\\newtoks\\pdf@toks",
        "pdf@defaulttoks": "\\newtoks\\pdf@defaulttoks",
        "pdf@draftmode": "\\newcount\\pdf@draftmode\\pdf@draftmode=1",
        "pdf@lastxpos": "\\newcount\\pdf@lastxpos",
        "pdf@addtoksx": "\\protected\\long\\def\\pdf@addtoksx#1{}",
        "pdf@strcmp": "\\protected\\long\\def\\pdf@strcmp#1#2{}",
        "pdf@filesize": "\\protected\\long\\def\\pdf@filesize#1{}",
        "pdf@ifdraftmode": "\\csname pdf@ifdraftmode\\expandafter\\endcsname",
    }
    for prim, want in cases.items():
        sub = tmp_path / prim.replace("@", "_")
        sub.mkdir()
        ctx = _ctx(sub)
        ok, note = builtins.pdftex_prim_polyfill(ctx, None, prim, {})
        assert ok, (prim, note)
        out = (sub / "main.tex").read_text(encoding="utf-8")
        assert want in out, (prim, out[:200])
        assert "\\catcode 64=11" in out, prim  # 全族同裹 @=11


def test_arm_at_name_refire_declines(tmp_path: Path) -> None:
    """@-名注入后再火 → ``\\ifdefined\\pdf@box`` 标记拒 (already guarded)。"""
    ctx = _ctx(tmp_path)
    ok, _ = builtins.pdftex_prim_polyfill(ctx, None, "pdf@box", {})
    assert ok
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdf@box", {})
    assert not ok
    assert "already guarded" in note


# ---------------------------------------------------------------- \\pdfoutput=0
def test_arm_pdfoutput_init_zero(tmp_path: Path) -> None:
    """``\\pdfoutput`` 初值 ``=0`` —— ``\\ifnum\\pdfoutput>0`` 值探针诚实假。

    存在探针 ``\\ifx\\pdfoutput\\undefined`` 定义即翻臂是固有面 (gate
    collapse 先塌 fileset 内探针; texmf 内探针由 =0 初值保持非 pdf 臂)。
    """
    ctx = _ctx(tmp_path)
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdfoutput", {})
    assert ok, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\pdfoutput\\else\\newcount\\pdfoutput\\pdfoutput=0\\fi" in out


def test_arm_countish_default_init_one(tmp_path: Path) -> None:
    """缺省初值仍 ``=1`` —— 其它 countish 回归 (读型与旧 chardef 同义)。"""
    ctx = _ctx(tmp_path)
    ok, _ = builtins.pdftex_prim_polyfill(ctx, None, "pdfcompresslevel", {})
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\newcount\\pdfcompresslevel\\pdfcompresslevel=1" in out


def test_arm_pdftexversion_init_140(tmp_path: Path) -> None:
    """``\\pdftexversion`` 初值 ``=140`` —— TL2025 pdftex 1.40.x 对齐。

    缺省 ``=1`` 把 ``\\ifnum\\pdftexversion<120`` 版本探针翻成真臂：
    microtype 系版本闸静默退役 (0812.1138 docsty 实证受害)。
    """
    ctx = _ctx(tmp_path)
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdftexversion", {})
    assert ok, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert (
        "\\ifdefined\\pdftexversion\\else\\newcount\\pdftexversion"
        "\\pdftexversion=140\\fi" in out
    )


@_COMPILE
def test_pdftexversion_ifnum_semantics_real_xelatex(tmp_path: Path) -> None:
    """真 xelatex: 注入后 ``>120`` 探针走真臂、``<120`` 走假臂。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\begin{document}\n"
        "\\ifnum\\pdftexversion>120 \\typeout{PRIMVERDICT-A yes}"
        "\\else\\typeout{PRIMVERDICT-A no}\\fi\n"
        "\\ifnum\\pdftexversion<120 \\typeout{PRIMVERDICT-B yes}"
        "\\else\\typeout{PRIMVERDICT-B no}\\fi\n"
        "x\n\\end{document}\n",
    )
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdftexversion", {})
    assert ok, note
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [_XELATEX, "-interaction=nonstopmode", "main.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    log = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    assert "PRIMVERDICT-A yes" in log
    assert "PRIMVERDICT-B no" in log


# ---------------------------------------------------------------- dedup 收窄
def test_dedup_alloc_def_site_declines(tmp_path: Path) -> None:
    """稿自带 ``\\newcount\\pdfoutput`` → 拒注 (撞位会 already-defined)。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\newcount\\pdfoutput\\pdfoutput=1\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdfoutput", {})
    assert not ok
    assert "already defined" in note


def test_dedup_newcommand_def_site_declines(tmp_path: Path) -> None:
    """``\\newcommand{\\pdfoutput}`` 花括号定义位同拒。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\newcommand{\\pdfoutput}{1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdfoutput", {})
    assert not ok
    assert "already defined" in note


def test_dedup_def_site_still_injects(tmp_path: Path) -> None:
    """``\\def\\pdfoutput`` 重绑无 already-defined 闸 → 不拒 (死定义不丢修)。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\pdfoutput{1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdfoutput", {})
    assert ok, note


def test_dedup_commented_def_ignored(tmp_path: Path) -> None:
    """注释内 ``\\newcount\\pdfoutput`` (遮盖面不可见) → 不拒。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n% \\newcount\\pdfoutput\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdfoutput", {})
    assert ok, note


# ---------------------------------------------------------------- 路由层
def test_route_at_payload_polyfill(tmp_path: Path) -> None:
    """``pdftex_prim|pdf@box`` 源无字面 + fileset 内站点 → polyfill 接住。"""
    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=["./main.tex"])
    rule = _match(ctx, "pdftex_prim", "pdf@box", rep)
    assert rule is not None
    assert rule.id == "pdftex_prim_polyfill"
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\newbox\\pdf@box" in out
    assert any(d.startswith("pdftex_prim_guard:") for d in ctx.declined)


def test_route_at_payload_guardable_site_guard_first(tmp_path: Path) -> None:
    """fileset .sty 内赋值形字面站点 → guard(50) 先修 (有站点不注头)。

    操作数位站点 (``\\sbox\\pdf@box``) guard 的 ``(?<![\\\\a-zA-Z])``
    lookbehind 本就豁免 —— 包裹 ``\\sbox\\ifdefined..`` 会毁掉 cs 操作数;
    行首赋值形 ``\\pdf@draftmode=1`` 是可包站点。
    """
    ctx = _ctx(tmp_path)
    (tmp_path / "pkg.sty").write_text(
        "\\ProvidesPackage{pkg}\n\\pdf@draftmode=1\n", encoding="utf-8"
    )
    rep = ErrReport(file_stack=["./main.tex"])
    rule = _match(ctx, "pdftex_prim", "pdf@draftmode", rep)
    assert rule is not None
    assert rule.id == "pdftex_prim_guard"
    out = (tmp_path / "pkg.sty").read_text(encoding="utf-8")
    assert "\\ifdefined\\pdf@draftmode\\pdf@draftmode=1\\fi" in out


# ---------------------------------------------------------------- 门塌陷规则
_GATE = "\\documentclass{article}\n\\ifpdf A\\else B\\fi\n\\begin{document}\nx\n\\end{document}\n"


def _apply_collapse(ctx: LoopCtx) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 规则动作直驱
        _rule("pdftex_gate_collapse"), ctx, None, None, ErrReport()
    )


def test_collapse_ifpdf_family(tmp_path: Path) -> None:
    """``\\ifpdf``/``\\ifCLASSINFOpdf``/``\\if@pdf`` → ``\\iftrue`` (能力臂)。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n"
        "\\ifpdf A\\else B\\fi\n"
        "\\ifCLASSINFOpdf \\usepackage[pdftex]{graphicx}\\fi\n"
        "\\makeatletter\\if@pdf C\\fi\\makeatother\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_collapse(ctx)
    assert ok, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\iftrue A\\else B\\fi" in out
    assert "\\iftrue \\usepackage[pdftex]{graphicx}\\fi" in out
    assert "\\iftrue C\\fi" in out


def test_collapse_ifx_pdfoutput_probe(tmp_path: Path) -> None:
    """``\\ifx\\pdfoutput\\<undef>`` 双向 → ``\\iftrue`` (undefined 真臂诚实)。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n"
        "\\ifx\\pdfoutput\\undefined A\\else B\\fi\n"
        "\\ifx\\undefined\\pdfoutput C\\else D\\fi\n"
        "\\ifx\\pdfoutput\\@undefined E\\fi\n"
        "\\ifx\\pdfoutput\\relax F\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_collapse(ctx)
    assert ok, note
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\iftrue A\\else B\\fi" in out
    assert "\\iftrue C\\else D\\fi" in out
    assert "\\iftrue E\\fi" in out
    assert "\\iftrue F\\fi" in out


def test_collapse_def_sites_protected(tmp_path: Path) -> None:
    """定义位豁免：``\\newif``/``\\def``/``\\let``/``\\newcommand`` 目标不塌。"""
    src = (
        "\\documentclass{article}\n"
        "\\newif\\ifpdf\n\\def\\ifpdf{x}\n\\let\\ifpdf\\iftrue\n"
        "\\let\\x\\ifpdf\n\\newcommand{\\ifpdf}{y}\n"
        "\\ifpdf A\\else B\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    ctx = _ctx(tmp_path, src)
    ok, _ = _apply_collapse(ctx)
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    # 定义位原样
    assert "\\newif\\ifpdf" in out
    assert "\\def\\ifpdf{x}" in out
    assert "\\let\\ifpdf\\iftrue" in out
    assert "\\let\\x\\ifpdf" in out
    assert "\\newcommand{\\ifpdf}{y}" in out
    # 使用位照塌
    assert "\\iftrue A\\else B\\fi" in out


def test_collapse_operand_positions_protected(tmp_path: Path) -> None:
    """操作数位豁免：``\\ifx\\ifpdf``/``\\ifcat\\ifpdf``/``\\ifdefined\\ifpdf`` 不塌。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n"
        "\\ifx\\ifpdf\\undefined A\\fi\n"
        "\\ifcat\\ifpdf\\relax B\\fi\n"
        "\\ifdefined\\ifpdf C\\fi\n"
        "\\ifpdf D\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply_collapse(ctx)
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifx\\ifpdf\\undefined A\\fi" in out
    assert "\\ifcat\\ifpdf\\relax B\\fi" in out
    assert "\\ifdefined\\ifpdf C\\fi" in out
    assert "\\iftrue D\\fi" in out


def test_collapse_body_site_collapses(tmp_path: Path) -> None:
    """宏体内门照塌 (``\\def\\f{\\ifpdf..}`` —— def 目标是 \\f 不是门)。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{\\ifpdf A\\else B\\fi}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply_collapse(ctx)
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\def\\f{\\iftrue A\\else B\\fi}" in out


def test_collapse_non_gate_ifs_untouched(tmp_path: Path) -> None:
    """``\\ifpdftrue``/``\\ifpdffalse``/``\\ifpdftex``/``\\ifpdfoutput`` 不中。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n"
        "\\ifpdftrue A\\fi\n\\ifpdffalse B\\fi\n\\ifpdftex C\\fi\n"
        "\\ifpdfoutput D\\fi\n\\ifpdf E\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply_collapse(ctx)
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifpdftrue A\\fi" in out
    assert "\\ifpdffalse B\\fi" in out
    assert "\\ifpdftex C\\fi" in out
    assert "\\ifpdfoutput D\\fi" in out
    assert "\\iftrue E\\fi" in out


def test_collapse_value_existence_probes_untouched(tmp_path: Path) -> None:
    """``\\ifnum\\pdfoutput``/``\\ifdefined\\pdfoutput``/``\\ifcsname`` 不改写。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n"
        "\\ifnum\\pdfoutput>0 A\\else B\\fi\n"
        "\\ifdefined\\pdfoutput C\\fi\n"
        "\\ifcsname pdfoutput\\endcsname D\\fi\n"
        "\\ifpdf E\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply_collapse(ctx)
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifnum\\pdfoutput>0 A\\else B\\fi" in out
    assert "\\ifdefined\\pdfoutput C\\fi" in out
    assert "\\ifcsname pdfoutput\\endcsname D\\fi" in out
    assert "\\iftrue E\\fi" in out


def test_collapse_masked_regions_untouched(tmp_path: Path) -> None:
    """注释内门 (遮盖面) 不塌 —— 但条件臂仍见 \\ifpdf 活体门。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n% \\ifpdf dead\\fi\n\\ifpdf A\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply_collapse(ctx)
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "% \\ifpdf dead\\fi" in out
    assert "\\iftrue A\\fi" in out


def test_collapse_own_injection_immune(tmp_path: Path) -> None:
    """自注入 ``\\ifdefined\\pdfoutput\\else\\newcount..\\fi`` 不被塌陷。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n"
        "\\ifdefined\\pdfoutput\\else\\newcount\\pdfoutput\\pdfoutput=0\\fi\n"
        "\\ifpdf A\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply_collapse(ctx)
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\pdfoutput\\else\\newcount\\pdfoutput\\pdfoutput=0\\fi" in out
    assert "\\iftrue A\\fi" in out


def test_collapse_idempotent(tmp_path: Path) -> None:
    """塌后无 \\if*pdf 活体 → 条件臂失配弃守，幂等。"""
    ctx = _ctx(tmp_path, _GATE)
    ok, _ = _apply_collapse(ctx)
    assert ok
    ok, _note = _apply_collapse(ctx)
    assert not ok


def test_collapse_sty_file_covered(tmp_path: Path) -> None:
    """exts 盖 .sty —— dtrt.sty 形 ``\\ifpdf`` 门照塌。"""
    ctx = _ctx(tmp_path)
    (tmp_path / "dtrt.sty").write_text(
        "\\ProvidesPackage{dtrt}\n\\usepackage{ifpdf}\n"
        "\\ifpdf\\usepackage[pagebackref]{hyperref}\\fi\n",
        encoding="utf-8",
    )
    ok, _ = _apply_collapse(ctx)
    assert ok
    out = (tmp_path / "dtrt.sty").read_text(encoding="utf-8")
    assert "\\iftrue\\usepackage[pagebackref]{hyperref}\\fi" in out


def test_route_collapse_on_undefined_cs(tmp_path: Path) -> None:
    """``undefined_cs|includegraphics`` + ``\\ifCLASSINFOpdf`` 门 → collapse 先接。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n"
        "\\ifCLASSINFOpdf \\usepackage[pdftex]{graphicx}\\fi\n"
        "\\begin{document}\n\\includegraphics{f}\n\\end{document}\n",
    )
    rule = _match(ctx, "undefined_cs", "includegraphics", ErrReport())
    assert rule is not None
    assert rule.id == "pdftex_gate_collapse"
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\iftrue \\usepackage[pdftex]{graphicx}\\fi" in out


def test_route_collapse_on_other(tmp_path: Path) -> None:
    """``other`` 失守面 (GenericError 型) + ``\\ifx\\pdfoutput`` 门 → collapse。

    门内带 ``[pdftex]`` 驱动词时 driver_opt_strip(48) 先于 collapse 剥词
    (更外科的修复 —— 两修链式收敛); 本格门内无驱动词直落 collapse。
    """
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\ifx\\pdfoutput\\undefined\\else"
        "\\pdfcompresslevel=9\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rule = _match(ctx, "other", "GenericError", ErrReport())
    assert rule is not None
    assert rule.id == "pdftex_gate_collapse"


def test_route_collapse_no_gate_declines(tmp_path: Path) -> None:
    """无门源 → collapse 条件臂弃守让位 (不耗轮)。"""
    ctx = _ctx(tmp_path)
    rule = _rule("pdftex_gate_collapse")
    ok, _why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, None, None, ErrReport()
    )
    assert not ok


def test_collapse_0712_selfdefect_shape(tmp_path: Path) -> None:
    """snc.tex:25 真形 —— ``\\ifx\\pdfoutput\\undefined\\else`` 塌后 pdf 臂死。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\newif\\ifhepph\\hepphtrue\n"
        "\\ifhepph\\else\\ifx\\pdfoutput\\undefined\\else\n"
        "\\pdfcompresslevel=9\n\\usepackage[pdftex]{hyperref}\n\\fi\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply_collapse(ctx)
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifhepph\\else\\iftrue\\else" in out
    # hyperref[pdftex] 块成死臂 (\\else 臂在 \\iftrue 下不执行)
    assert "\\iftrue\\else\n\\pdfcompresslevel=9" in out
