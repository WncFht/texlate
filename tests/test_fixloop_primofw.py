"""fileset 外报错站点 → pdftex_prim/glyphtounicode condition 拓宽单测 (lane-primofw)。

实证背景: axessibility.sty:349-352 四连块 (``\\pdfcompresslevel=0`` /
``\\pdfoptionpdfminorversion=6`` / ``\\input{glyphtounicode}`` /
``\\pdfgentounicode=1``) 落在系统 texmf 件 —— 报错站点不在 ``ctx.tex_files``
内。旧 condition 只认 wdir 源证据 (``prim_read_form`` /
``source_contains glyphtounicode``) → polyfill/shadow 两臂弃守; guard(50)
的 ``_patch_files`` 同样只扫 fileset → 0-edit 弃守 → unfixable (census ~7 格)。

拓宽面: 新 condition 原语 ``err_outside_fileset`` —— ``rep.file_stack[-1]``
内层帧 (runaway 空栈回退 ``popped_files[-1]``) 经 ``is_project_file`` 判
工程外即过。只挂在 arm 不需缺失证据处: guard 仍正确弃守 (patch 不了
看不见的件), polyfill (主文件头注入) 与 glyphtounicode_shadow (wdir 落
stub, TeX 文件解析序 cwd 先截获) 皆 fileset 无关。

arm 形修正 (偏离原 spec, 实证驱动): 整数值原语 (``_PRIM_COUNTISH``)
polyfill 走 ``\\newcount\\<prim>\\<prim>=1`` —— ``\\chardef`` 形对写型站点
``\\prim=val`` 变排版字符 + ``=val`` 文本 → Missing ``\\begin{document}``
转嫁错类 (tmp/lane-primofw/t3.tex 真 xelatex 实证); ``\\newcount`` 同点
全真接管 (t4.tex 过到下一错误)。读型 ``\\ifnum\\<prim>`` 读寄存器初值 1
与旧 ``\\chardef=1`` 同义, 无回归。
"""

from pathlib import Path

from texlate.compile.fixloop import (
    Ruleset,
    _builtins_shim,
    actions,
    builtins,
    load_ruleset,
)
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport

# 系统 texmf 帧 token (file_stack_at 实录形态: 相对帧 ./ 前缀, 系统帧绝对)。
_AXS_STY = "/usr/share/texmf-dist/tex/latex/axessibility/axessibility.sty"
_GLYPH_TEX = "/usr/share/texmf-dist/tex/generic/pdftex/glyphtounicode.tex"

_MAIN = (
    "\\documentclass{article}\n\\usepackage{somepkg}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)


def _rs() -> Ruleset:
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _rep_sty() -> ErrReport:
    """axessibility.sty:349 形 —— 内层帧系统 texmf sty (写型站点)。"""
    return ErrReport(file_stack=["./main.tex", _AXS_STY])


def _rep_glyph() -> ErrReport:
    """``\\input{glyphtounicode}`` 真件内 ``\\pdfglyphtounicode`` 站点形。"""
    return ErrReport(file_stack=["./main.tex", _AXS_STY, _GLYPH_TEX])


def _ctx(tmp_path: Path, main: str = _MAIN) -> LoopCtx:
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _match(
    ctx: LoopCtx, pay: str, rep: ErrReport, cat: str = "pdftex_prim"
) -> Rule | None:
    rule, _note = actions._match_apply(  # noqa: SLF001 - 路由行为直驱
        _rs(), ctx, None, cat, pay, rep
    )
    return rule


# ---------------------------------------------------------------- 接线
def test_widened_conditions_carry_err_outside_fileset() -> None:
    """两臂 condition.any 各挂 err_outside_fileset 备选。"""
    for rid in ("pdftex_prim_polyfill", "glyphtounicode_shadow"):
        cond = _rule(rid).condition
        assert {"err_outside_fileset": True} in cond["any"], rid


def test_new_prims_registered_countish() -> None:
    """pdfoptionpdfminorversion/pdfobjcompresslevel 进 PDFTEX_PRIMS + 整型集。

    axessibility.sty:350 第二枚写型原语 —— 缺注册 round-2 即弃守。
    """
    for prim in ("pdfoptionpdfminorversion", "pdfobjcompresslevel"):
        assert prim in builtins.PDFTEX_PRIMS, prim
        assert prim in _builtins_shim._PRIM_COUNTISH, prim  # noqa: SLF001


# ---------------------------------------------------------------- condition 闸
def test_cond_err_outside_fileset_system_site_passes(tmp_path: Path) -> None:
    """file_stack 内层帧 = 系统 texmf 件 → err_outside_fileset 过。"""
    ctx = _ctx(tmp_path)
    rule = _rule("pdftex_prim_polyfill")
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, None, "pdfcompresslevel", _rep_sty()
    )
    assert ok, why


def test_cond_err_outside_fileset_popped_fallback(tmp_path: Path) -> None:
    """runaway 空栈 → popped_files[-1] 回退帧判 (同 _requester_paths 口径)。"""
    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=[], popped_files=["./main.tex", _AXS_STY])
    rule = _rule("pdftex_prim_polyfill")
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, None, "pdfcompresslevel", rep
    )
    assert ok, why


def test_cond_err_outside_fileset_project_site_declines(tmp_path: Path) -> None:
    """内层帧相对/工程内件 + 源无读型 → 仍拒 (拓宽不放行 fileset 内件)。"""
    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=["./main.tex", "./pkg/mypkg.sty"])
    rule = _rule("pdftex_prim_polyfill")
    ok, _why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, None, "pdfcompresslevel", rep
    )
    assert not ok


def test_cond_err_outside_fileset_no_rep_fails_closed(tmp_path: Path) -> None:
    """rep=None (直驱/旧调用面) 与空栈证据 → fail-closed。"""
    ctx = _ctx(tmp_path)
    cond = {"err_outside_fileset": True}
    rule = _rule("pdftex_prim_polyfill")
    ok, _ = actions._cond_ok(cond, rule, ctx, None, "pdfcompresslevel", None)  # noqa: SLF001
    assert not ok
    ok, _ = actions._cond_ok(  # noqa: SLF001
        cond, rule, ctx, None, "pdfcompresslevel", ErrReport()
    )
    assert not ok


# ---------------------------------------------------------------- 路由层
def test_route_out_of_fileset_write_site_to_polyfill(tmp_path: Path) -> None:
    """axessibility 形: 源无 prim → guard/shadow 弃守 → polyfill 接住注入。"""
    ctx = _ctx(tmp_path)
    rule = _match(ctx, "pdfcompresslevel", _rep_sty())
    assert rule is not None
    assert rule.id == "pdftex_prim_polyfill"
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    # 整型原语 → \\newcount 形 (非 spec 旧述 \\chardef —— 见模块 docstring)
    assert (
        "\\ifdefined\\pdfcompresslevel\\else\\newcount\\pdfcompresslevel"
        "\\pdfcompresslevel=1\\fi" in out
    )
    # 恒头注入: sty 内使用发生在 \\usepackage 加载期间, docclass 行后太晚
    assert out.index("\\ifdefined\\pdfcompresslevel") < out.index("\\documentclass")
    # guard 正确弃守 (fileset 外件不可 patch) + shadow cs_set 不收
    assert any(d.startswith("pdftex_prim_guard:") for d in ctx.declined)
    assert any(d.startswith("glyphtounicode_shadow:") for d in ctx.declined)


def test_route_second_prim_round_polyfill(tmp_path: Path) -> None:
    """axessibility :350 形: pdfoptionpdfminorversion 同路 polyfill。"""
    ctx = _ctx(tmp_path)
    rule = _match(ctx, "pdfoptionpdfminorversion", _rep_sty())
    assert rule is not None
    assert rule.id == "pdftex_prim_polyfill"
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\newcount\\pdfoptionpdfminorversion" in out


def test_route_glyphtounicode_payload_to_shadow(tmp_path: Path) -> None:
    """源无 glyphtounicode 引用 + 站点系统 glyphtounicode.tex → shadow 落 stub。"""
    ctx = _ctx(tmp_path)
    rule = _match(ctx, "pdfglyphtounicode", _rep_glyph())
    assert rule is not None
    assert rule.id == "glyphtounicode_shadow"
    stub = (tmp_path / "glyphtounicode.tex").read_text(encoding="utf-8")
    assert "\\def\\pdfglyphtounicode#1#2{}" in stub
    assert "\\newcount\\pdfgentounicode" in stub


def test_route_in_fileset_read_form_unchanged(tmp_path: Path) -> None:
    """回归: wdir 源 ``\\ifnum\\pdfoutput`` 读型 → 旧 prim_read_form 臂仍通。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\ifnum\\pdfoutput=0 x\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rule = _match(ctx, "pdfoutput", ErrReport())  # 空 rep: 不走新臂
    assert rule is not None
    assert rule.id == "pdftex_prim_polyfill"
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\newcount\\pdfoutput" in out


def test_route_in_fileset_write_form_guard_first(tmp_path: Path) -> None:
    """回归: wdir 源 \\\\pdfoutput=1 写型 → guard(50) 先修, polyfill 不抢。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfoutput=1\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rule = _match(ctx, "pdfoutput", ErrReport())
    assert rule is not None
    assert rule.id == "pdftex_prim_guard"
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\pdfoutput\\pdfoutput=1\\fi" in out


def test_route_shadow_still_prefers_source_evidence(tmp_path: Path) -> None:
    """回归: 源含 glyphtounicode 引用链 + 工程内站点 → shadow 旧臂仍通。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\input{glyphtounicode}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rep = ErrReport(file_stack=["./main.tex"])  # 工程内站点
    rule = _match(ctx, "pdfglyphtounicode", rep)
    assert rule is not None
    assert rule.id == "glyphtounicode_shadow"
    assert (tmp_path / "glyphtounicode.tex").is_file()


# ---------------------------------------------------------------- arm 直驱
def test_guard_arm_declines_out_of_fileset(tmp_path: Path) -> None:
    """guard 对 fileset 外站点 0-edit 弃守 (patch 面只有 ctx.tex_files)。"""
    ctx = _ctx(tmp_path)
    ok, note = actions._apply(  # noqa: SLF001
        _rule("pdftex_prim_guard"), ctx, None, "pdfcompresslevel", _rep_sty()
    )
    assert not ok
    assert "0 files" in note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == _MAIN


def test_polyfill_arm_countish_newcount_else_chardef(tmp_path: Path) -> None:
    """arm 形分派: 整型 → ``\\newcount`` 全真接管; 非整型 → ``\\chardef`` 旧形。"""
    ctx = _ctx(tmp_path)
    ok, _ = builtins.pdftex_prim_polyfill(ctx, None, "pdfcompresslevel", {})
    assert ok
    ok, _ = builtins.pdftex_prim_polyfill(ctx, None, "pdftexrevision", {})
    assert ok
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\newcount\\pdfcompresslevel\\pdfcompresslevel=1\\fi" in out
    assert "\\chardef\\pdftexrevision=1\\fi" in out
