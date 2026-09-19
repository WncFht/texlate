"""wrapromote —— fragment 误判主档 ``\\input`` wrapper 提升单测。

实证背景 (relocatemiss 诊断, failmine4 soak-2026-09-18 2609.19170):
``find_main_tex`` pass-1 只收字面 ``\\documentclass`` 件 —— 根目录 9 行
裸 ``\\input`` 编排壳 ``retd_jmlr_jmlr_candidate_20260828.tex`` 永不入
池; 池内只剩 ``sections/00_preamble.tex`` fragment (止于 ``\\maketitle``,
无 ``\\end{document}`` 无 ``\\input``) → 编译 ``! Emergency stop /
*** (job aborted, no legal \\end found)``。``main_wrapper_promote``
扫 wdir 找 ``\\input`` 闭包吞现 main 且达 ``\\end{document}`` 的 wrapper
翻 ``ctx.io.main_rel`` —— 修复层换 main, 不动 inject 探测面。
"""

from pathlib import Path

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, Rule

_RULE = "main_wrapper_promote"

_FRAGMENT = (
    "\\documentclass{article}\n\\begin{document}\n\\title{T}\\maketitle\nbody text\n"
)
_CONCLUSION = "tail\\par\n\\end{document}\n"
_WRAPPER = (
    "\\input{sections/00_preamble}\n"
    "\\input{sections/01_intro}\n"
    "\\input{sections/08_conclusion}\n"
)
_INTRO = "intro body\n"


class _EngStub:
    """builtin 直驱引擎替身 —— ``main_wrapper_promote`` ``del eng`` 不触引擎面。"""

    def probe_file(self, fname: str, cwd: Path | None = None) -> None:
        del fname, cwd

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False


def _rule(rid: str) -> Rule:
    return next(r for r in load_ruleset().rules if r.id == rid)


def _ctx(tmp_path: Path, main_rel: str | None) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel=main_rel)


def _promote(ctx: LoopCtx) -> tuple[bool, str]:
    return TRANSFORM_FNS[_RULE](ctx, _EngStub(), None, {})


def _mk_cell(tmp_path: Path, *, wrapper: bool = True) -> None:
    sec = tmp_path / "sections"
    sec.mkdir()
    (sec / "00_preamble.tex").write_text(_FRAGMENT, encoding="utf-8")
    (sec / "01_intro.tex").write_text(_INTRO, encoding="utf-8")
    (sec / "08_conclusion.tex").write_text(_CONCLUSION, encoding="utf-8")
    if wrapper:
        (tmp_path / "retd.tex").write_text(_WRAPPER, encoding="utf-8")


def test_wrapper_promote_flips_main(tmp_path: Path) -> None:
    """fragment main + 单 wrapper → applied, main_rel 翻到 wrapper。"""
    _mk_cell(tmp_path)
    ctx = _ctx(tmp_path, "sections/00_preamble.tex")
    applied, note = _promote(ctx)
    assert applied, note
    assert ctx.io.main_rel == "retd.tex"
    assert any("main_wrapper_promote" in a for a in ctx.ledger.advisories)


def test_wrapper_promote_no_wrapper_abstain(tmp_path: Path) -> None:
    """fragment main 无 wrapper 吞 → 让位 (无救)。"""
    _mk_cell(tmp_path, wrapper=False)
    ctx = _ctx(tmp_path, "sections/00_preamble.tex")
    applied, note = _promote(ctx)
    assert not applied
    assert "no \\end{document}-reaching wrapper" in note
    assert ctx.io.main_rel == "sections/00_preamble.tex"


def test_wrapper_promote_ambiguous_abstain(tmp_path: Path) -> None:
    """双合格 wrapper → 歧义让位, main_rel 不动。"""
    _mk_cell(tmp_path)
    (tmp_path / "alt.tex").write_text(
        "\\input{sections/00_preamble}\n\\input{sections/08_conclusion}\n",
        encoding="utf-8",
    )
    ctx = _ctx(tmp_path, "sections/00_preamble.tex")
    applied, note = _promote(ctx)
    assert not applied
    assert "ambiguous" in note
    assert ctx.io.main_rel == "sections/00_preamble.tex"


def test_wrapper_promote_main_with_end_abstain(tmp_path: Path) -> None:
    """现 main 闭包已达 \\end{document} → 非 fragment 误判, 让位。"""
    _mk_cell(tmp_path)
    sec = tmp_path / "sections"
    (sec / "00_preamble.tex").write_text(
        _FRAGMENT + "\\input{sections/08_conclusion}\n", encoding="utf-8"
    )
    ctx = _ctx(tmp_path, "sections/00_preamble.tex")
    applied, note = _promote(ctx)
    assert not applied
    assert "already reaches" in note
    assert ctx.io.main_rel == "sections/00_preamble.tex"


def test_rule_wrapromote_dispatch(tmp_path: Path) -> None:
    """wired 规则: emergency + ``no legal \\end found`` 签名即过闸。"""
    rule = _rule(_RULE)
    ctx = _ctx(tmp_path, "main.tex")
    assert actions._when_ok(rule.when, "emergency", None, ctx)  # noqa: SLF001
    assert not actions._when_ok(rule.when, "missing_file", "x.sty", ctx)  # noqa: SLF001
    ctx.err_head = (
        "! Emergency stop.\n<*> retd.tex\n*** (job aborted, no legal \\end found)\n"
    )
    ok, why = actions._cond_ok(rule.condition, rule, ctx, _EngStub(), None)  # noqa: SLF001
    assert ok, why
    ctx.err_head = "! Emergency stop.\n<*> x.tex\n"
    ok, _why = actions._cond_ok(rule.condition, rule, ctx, _EngStub(), None)  # noqa: SLF001
    assert not ok
