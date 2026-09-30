"""取参型 pdfTeX 原语吞参 noop 臂单测 (primarg 车道)。

实证背景：spotcolor.sty (1907.10410/2410.00012 ieeeaccess 族 e-print
伴船件) :34-62 连用 ``\\pdfobj{dict}`` / ``\\pdfrefobj\\thecolorprofile`` /
``\\pdfliteral{op}`` —— ``\\pdfrefobj\\<reg>`` 无花括号形 guard 两
pattern (``\\prim=`` / ``\\prim{``) 都包不到，fileset 内站点
``err_outside_fileset`` 又不中 → polyfill 以 ``\\protected\\def`` 吞参
noop 兜底 (primarg 探针 argful 真 xelatex 实测：实参消费、零排版
残留; ``\\pdfifprimitive`` 绑 ``\\iffalse`` 正确走 else 臂)。

臂形分派：``_PRIM_COUNTISH``→``\\newcount`` /
``_PRIM_TOKSISH``→``\\newtoks`` / ``_PRIM_DIMENISH``→``\\newdimen`` /
``_PRIM_ARGFUL``→``\\protected\\def<sig>`` (``@iffalse`` 哨兵→
``\\let→\\iffalse``) / 余项→``\\chardef`` 旧形。
"""

from pathlib import Path

from texlate.compile.fixloop import (
    Ruleset,
    actions,
    builtins,
    load_ruleset,
)
from texlate.compile.fixloop.builtins import pdfprim
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport

#: 合成 file_stack 帧 token —— texmf 系统件径形字符串道具，只供
#: err_outside_fileset 的 texmf 正则归类，从不读盘 (非宿主机路径依赖)。
_SYS_STY_FRAME = "/usr/share/texmf-dist/tex/latex/axessibility/axessibility.sty"

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


def _match(
    ctx: LoopCtx, pay: str, rep: ErrReport, cat: str = "pdftex_prim"
) -> Rule | None:
    rule, _note = actions._match_apply(  # noqa: SLF001 - 路由行为直驱
        _rs(), ctx, None, cat, pay, rep
    )
    return rule


# ---------------------------------------------------------------- 接线/注册
def test_polyfill_condition_carries_arg_site_arm() -> None:
    """polyfill condition.any 挂 source_contains 取参站点臂。"""
    cond = _rule("pdftex_prim_polyfill").condition
    assert {"source_contains": "\\\\{payload}(?![a-zA-Z@])"} in cond["any"]


def test_argful_tables_registered_and_disjoint() -> None:
    """argful/toksish/dimenish 三表全注册进 PDFTEX_PRIMS 且与 countish 互斥。"""
    allnew = set(pdfprim._PRIM_ARGFUL) | pdfprim._PRIM_TOKSISH | pdfprim._PRIM_DIMENISH  # noqa: SLF001
    for prim in allnew:
        assert prim in builtins.PDFTEX_PRIMS, prim
    assert not (set(pdfprim._PRIM_ARGFUL) & pdfprim._PRIM_COUNTISH)  # noqa: SLF001
    assert not (pdfprim._PRIM_TOKSISH & pdfprim._PRIM_COUNTISH)  # noqa: SLF001
    assert not (pdfprim._PRIM_DIMENISH & pdfprim._PRIM_COUNTISH)  # noqa: SLF001
    for prim in ("pdfobj", "pdfliteral", "pdfrefobj", "pdfcatalog", "pdfximage"):
        assert pdfprim._PRIM_ARGFUL[prim] == "#1", prim  # noqa: SLF001


# ---------------------------------------------------------------- condition 闸
def test_cond_arg_site_in_fileset_passes(tmp_path: Path) -> None:
    """源内 ``\\pdfrefobj\\thecolor`` (prim+cs 无花括号) → 新臂放行。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{\\pdfrefobj\\thecolor}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rule = _rule("pdftex_prim_polyfill")
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, None, "pdfrefobj", ErrReport()
    )
    assert ok, why


def test_cond_arg_site_prefix_name_declines(tmp_path: Path) -> None:
    """``\\pdfobjcompresslevel`` 前缀撞名不误中 ``pdfobj`` payload (lookahead)。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfobjcompresslevel=3\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rule = _rule("pdftex_prim_polyfill")
    ok, _why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, None, "pdfobj", ErrReport()
    )
    assert not ok


def test_cond_arg_site_absent_declines(tmp_path: Path) -> None:
    """源无 payload 原语 + fileset 内站点 → 三臂全拒。"""
    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=["./main.tex"])
    rule = _rule("pdftex_prim_polyfill")
    ok, _why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, None, "pdfrefobj", rep
    )
    assert not ok


# ---------------------------------------------------------------- 路由层
def test_route_unbraced_arg_site_to_argful_noop(tmp_path: Path) -> None:
    """fileset 内 ``\\pdfrefobj\\thecolor`` → guard 弃守 → polyfill 吞参 noop。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\newcount\\thecolor\n"
        "\\def\\f{\\pdfrefobj\\thecolor}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rule = _match(ctx, "pdfrefobj", ErrReport())
    assert rule is not None
    assert rule.id == "pdftex_prim_polyfill"
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert (
        "\\ifdefined\\pdfrefobj\\else\\protected\\long\\def\\pdfrefobj#1{}\\fi" in out
    )
    # 恒头注入：cls/sty 内使用发生在装载期间，docclass 行后太晚
    assert out.index("\\ifdefined\\pdfrefobj") < out.index("\\documentclass")
    assert any(d.startswith("pdftex_prim_guard:") for d in ctx.declined)


def test_route_argprim_outside_fileset(tmp_path: Path) -> None:
    """系统 sty 帧 + pdfcatalog payload → err_outside_fileset 臂 → argful noop。"""
    ctx = _ctx(tmp_path)
    rep = ErrReport(file_stack=["./main.tex", _SYS_STY_FRAME])
    rule = _match(ctx, "pdfcatalog", rep)
    assert rule is not None
    assert rule.id == "pdftex_prim_polyfill"
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\protected\\long\\def\\pdfcatalog#1{}" in out


def test_route_braced_arg_site_guard_first(tmp_path: Path) -> None:
    """回归：fileset 内 ``\\pdfobj{dict}`` 花括号形 → guard(50) 仍先修。

    站点取 spotcolor.sty:34 真形 —— 实参 ``}`` 是本行末枚 ``}``
    (guard ``[^\\n]*\\}`` 贪婪锚，单行嵌套 ``\\def\\f{\\pdfobj{..}}``
    会把 ``\\fi`` 落出宏体外，系 guard 侧先存缺陷不在本臂面)。
    """
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{%\n  \\pdfobj{<</N 1>>}%\n}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rule = _match(ctx, "pdfobj", ErrReport())
    assert rule is not None
    assert rule.id == "pdftex_prim_guard"
    out = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\ifdefined\\pdfobj\\pdfobj{<</N 1>>}\\fi" in out


# ---------------------------------------------------------------- 臂直驱
def test_arm_argful_signature_table(tmp_path: Path) -> None:
    """臂分派：单参/双参/零参/条件四形 + 寄存器两臂 + chardef 兜底。"""
    cases = {
        "pdfobj": "\\protected\\long\\def\\pdfobj#1{}",
        "pdfrefobj": "\\protected\\long\\def\\pdfrefobj#1{}",
        "pdfliteral": "\\protected\\long\\def\\pdfliteral#1{}",
        "pdfcatalog": "\\protected\\long\\def\\pdfcatalog#1{}",
        "pdfximage": "\\protected\\long\\def\\pdfximage#1{}",
        "pdfglyphtounicode": "\\protected\\long\\def\\pdfglyphtounicode#1#2{}",
        "pdfincludechars": "\\protected\\long\\def\\pdfincludechars#1#2{}",
        "pdfendlink": "\\protected\\def\\pdfendlink{}",
        "pdfsavepos": "\\protected\\def\\pdfsavepos{}",
        "pdfifprimitive": (
            "\\expandafter\\let\\csname pdfifprimitive\\expandafter\\endcsname"
            "\\csname iffalse\\endcsname"
        ),
        "pdfpageresources": "\\newtoks\\pdfpageresources",
        "pdfpagesattr": "\\newtoks\\pdfpagesattr",
        "pdfhorigin": "\\newdimen\\pdfhorigin",
        "pdfpxdimen": "\\newdimen\\pdfpxdimen",
        "pdfcompresslevel": "\\newcount\\pdfcompresslevel",
        "pdftexrevision": "\\chardef\\pdftexrevision=1",
    }
    for prim, want in cases.items():
        sub = tmp_path / prim
        sub.mkdir()
        ctx = _ctx(sub)
        ok, note = builtins.pdftex_prim_polyfill(ctx, None, prim, {})
        assert ok, (prim, note)
        out = (ctx.wdir / "main.tex").read_text(encoding="utf-8")
        assert want in out, (prim, out[:200])
        assert out.startswith(f"\\ifdefined\\{prim}\\else"), prim


def test_arm_argful_idempotent(tmp_path: Path) -> None:
    """``\\ifdefined\\<prim>`` 幂等闸：同 prim 二轮注入拒 (already guarded)。"""
    ctx = _ctx(tmp_path)
    ok, _ = builtins.pdftex_prim_polyfill(ctx, None, "pdfobj", {})
    assert ok
    ok, note = builtins.pdftex_prim_polyfill(ctx, None, "pdfobj", {})
    assert not ok
    assert "already guarded" in note
