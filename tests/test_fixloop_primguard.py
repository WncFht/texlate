"""pdftex_prim_guard 单行 def 站点孤 \\fi 修复单测 (lane-primguard)。

实证背景: guard(50) 两臂正则贪婪 —— 花括号臂 ``[^\\n]*\\}`` 取行内末枚
``}``, 赋值臂 ``[^\\n%]*`` 吃到 EOL。单行 def 站点
``\\def\\f{\\pdfobj{<</N 1>>}}`` / ``\\def\\f{\\pdfoutput=1}`` 的外层 ``}``
被吞 → ``\\fi`` 落出宏体外 → 孤 ``\\fi`` (Extra \\fi / Incomplete
\\ifdefined 破坏级; primarg 85c99f4 期审计实证输出形态, spotcolor.sty:34
真站点是多行 def 故幸存 —— 纯脆弱性, 任何单行 braced/赋值 def 内站点必炸)。

修形: regex 引擎递归平衡花括号
``(?<bal>\\{(?:\\\\[{}%]|%[^\\n]*|(?&bal)|[^{}])*\\})`` —— 转义
``\\{|\\}|\\%`` 与行注释内括号不计配对 (TeX 词法同构), 跨行实参收编
(旧 ``[^\\n]`` 弃守面)。赋值臂 value = (escape|bal|非括号非注释|孤{)*,
裸 ``}`` 必停 —— 单层/多层 def、注释 ``}``、escape 全谱正确; 不可闭合
``{`` 走孤 ``{`` 兜底, 维持旧形 "整行吞" (xetex 跳读面干净, 不把开口组
漏回排版流)。
"""

from pathlib import Path

from _fixloopkit import apply, rs

from texlate.compile.fixloop import actions
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport

_MAIN = (
    "\\documentclass{article}\n\\usepackage{somepkg}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)


def _ctx(tmp_path: Path, main: str = _MAIN) -> LoopCtx:
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _apply_guard(ctx: LoopCtx, payload: str = "pdfobj") -> tuple[bool, str]:
    return apply("pdftex_prim_guard", ctx, payload)


def _match(
    ctx: LoopCtx, pay: str, rep: ErrReport, cat: str = "pdftex_prim"
) -> Rule | None:
    hit, _note = actions._match_apply(  # noqa: SLF001 - 路由行为直驱
        rs(), ctx, None, cat, pay, rep
    )
    return hit


def _out(ctx: LoopCtx) -> str:
    return (ctx.wdir / "main.tex").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 缺陷类: 单行 def 站点
def test_braced_arm_single_line_def_no_orphan(tmp_path: Path) -> None:
    """``\\def\\f{\\pdfobj{<</N 1>>}}`` —— ``\\fi`` 落宏体内, 外层 ``}`` 不吞。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{\\pdfobj{<</N 1>>}}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    out = _out(ctx)
    assert "\\def\\f{\\ifdefined\\pdfobj\\pdfobj{<</N 1>>}\\fi}" in out
    # 外层 def 的 } 保留在 \fi 之后 —— 孤 \fi 不再落宏体外
    assert "\\ifdefined\\pdfobj\\pdfobj{<</N 1>>}\\fi" in out
    assert "\\pdfobj{<</N 1>>}\\fi}" in out


def test_assign_arm_single_line_def_no_orphan(tmp_path: Path) -> None:
    """``\\def\\f{\\pdfoutput=1}`` —— 赋值臂同缺陷: ``}`` 不可进 value。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{\\pdfoutput=1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx, "pdfoutput")
    assert ok, note
    out = _out(ctx)
    assert "\\def\\f{\\ifdefined\\pdfoutput\\pdfoutput=1\\fi}" in out


def test_braced_arm_nested_def_no_orphan(tmp_path: Path) -> None:
    """``\\def\\g{\\def\\f{\\pdfobj{a}}}`` —— 两层外层 ``}`` 全保留。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\g{\\def\\f{\\pdfobj{a}}}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    out = _out(ctx)
    assert "\\def\\g{\\def\\f{\\ifdefined\\pdfobj\\pdfobj{a}\\fi}}" in out


def test_braced_arm_trailing_tokens_in_def(tmp_path: Path) -> None:
    """``\\def\\f{\\pdfobj{a}\\more}`` —— ``\\fi`` 落 ``\\more`` 前, def 闭合法。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{\\pdfobj{a}\\more}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    assert "\\def\\f{\\ifdefined\\pdfobj\\pdfobj{a}\\fi\\more}" in _out(ctx)


def test_assign_arm_edef_site(tmp_path: Path) -> None:
    """``\\edef\\x{\\pdfoutput=1}`` —— edef 体同形正确。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\edef\\x{\\pdfoutput=1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx, "pdfoutput")
    assert ok, note
    assert "\\edef\\x{\\ifdefined\\pdfoutput\\pdfoutput=1\\fi}" in _out(ctx)


# ---------------------------------------------------------------- 回归: 常规/多行站点
def test_braced_arm_multi_line_def_still_wrapped(tmp_path: Path) -> None:
    """spotcolor.sty:34 真形 (多行 def, 实参独占行) —— 多行站点不回归。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{%\n  \\pdfobj{<</N 1>>}%\n}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    assert "\\ifdefined\\pdfobj\\pdfobj{<</N 1>>}\\fi%" in _out(ctx)


def test_braced_arm_top_level_unchanged(tmp_path: Path) -> None:
    """顶层 ``\\pdfobj{dict}`` —— 基本形不回归。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfobj{<</N 1>>}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    assert "\\ifdefined\\pdfobj\\pdfobj{<</N 1>>}\\fi" in _out(ctx)


def test_assign_arm_top_level_unchanged(tmp_path: Path) -> None:
    """顶层 ``\\pdfoutput=1`` —— 基本形不回归。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfoutput=1\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx, "pdfoutput")
    assert ok, note
    assert "\\ifdefined\\pdfoutput\\pdfoutput=1\\fi" in _out(ctx)


def test_assign_arm_multi_line_def_still_wrapped(tmp_path: Path) -> None:
    """多行 def 内赋值站点 —— 赋值臂跨行 def 不回归。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{%\n\\pdfoutput=1\n}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx, "pdfoutput")
    assert ok, note
    assert "\\ifdefined\\pdfoutput\\pdfoutput=1\\fi\n}" in _out(ctx)


# ---------------------------------------------------------------- 新覆盖与边界
def test_braced_arm_multiline_arg_now_wrapped(tmp_path: Path) -> None:
    """跨行实参 ``\\pdfobj{<<\\n/N 1\\n>>}`` —— 旧 ``[^\\n]`` 弃守面收编。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfobj{<<\n/N 1\n>>}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    assert "\\ifdefined\\pdfobj\\pdfobj{<<\n/N 1\n>>}\\fi" in _out(ctx)


def test_braced_arm_nested_brace_arg(tmp_path: Path) -> None:
    """嵌套花括号实参 ``\\pdfobj{<</X {a}>>}`` —— 真平衡, 不停内层 ``}``。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfobj{<</X {a}>>}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    assert "\\ifdefined\\pdfobj\\pdfobj{<</X {a}>>}\\fi" in _out(ctx)


def test_braced_arm_siblings_wrapped_separately(tmp_path: Path) -> None:
    """同行两站点 —— 各包各 (旧形一大包跨到末枚 ``}``, 新形精确逐枚)。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfobj{a} \\pdfobj{b}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    out = _out(ctx)
    assert (
        "\\ifdefined\\pdfobj\\pdfobj{a}\\fi \\ifdefined\\pdfobj\\pdfobj{b}\\fi" in out
    )


def test_braced_arm_escaped_brace_in_arg(tmp_path: Path) -> None:
    """``\\pdfobj{a\\}b}`` —— 转义 ``\\}`` 不当组闭, 实参取 TeX 真界。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfobj{a\\}b}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    assert "\\ifdefined\\pdfobj\\pdfobj{a\\}b}\\fi" in _out(ctx)


def test_braced_arm_comment_brace_not_counted(tmp_path: Path) -> None:
    """注释内 ``}`` 不计配对 —— ``\\pdfobj{a % }`` 的 ``}`` 非实参闭。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfobj{a % }\n b}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx)
    assert ok, note
    assert "\\ifdefined\\pdfobj\\pdfobj{a % }\n b}\\fi" in _out(ctx)


def test_braced_arm_unclosed_abstains(tmp_path: Path) -> None:
    """``\\pdfobj{`` 不可闭合 —— 花括号臂弃守 (与旧形同), guard 0-edit。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfobj{\n\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _note = _apply_guard(ctx)
    assert not ok
    assert "\\pdfobj{\n" in _out(ctx)


def test_assign_arm_braced_value(tmp_path: Path) -> None:
    """``\\pdfpageresources={/MediaBox [0 0 1 2]}`` —— 值内平衡组整吞。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfpageresources={/MediaBox [0 0 1 2]}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx, "pdfpageresources")
    assert ok, note
    out = _out(ctx)
    assert (
        "\\ifdefined\\pdfpageresources\\pdfpageresources={/MediaBox [0 0 1 2]}\\fi"
        in out
    )


def test_assign_arm_value_stops_before_comment(tmp_path: Path) -> None:
    """``\\pdfoutput=1 % c`` —— value 止于 ``%``, ``\\fi`` 落注释前。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfoutput=1 % c\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx, "pdfoutput")
    assert ok, note
    assert "\\ifdefined\\pdfoutput\\pdfoutput=1 \\fi% c" in _out(ctx)


def test_assign_arm_unclosed_brace_fallback(tmp_path: Path) -> None:
    """``\\pdfpageresources={abc`` 孤 ``{`` —— 兜底吃字面量整行吞 (旧形
    语义保持: xetex 跳读区含开口组亦干净, 不漏回排版流)。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfpageresources={abc\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, note = _apply_guard(ctx, "pdfpageresources")
    assert ok, note
    assert "\\ifdefined\\pdfpageresources\\pdfpageresources={abc\\fi" in _out(ctx)


# ---------------------------------------------------------------- 幂等/路由
def test_guard_idempotent(tmp_path: Path) -> None:
    """已包站点不二次套娃 —— lookbehind 挡 ``\\ifdefined\\<prim>`` 与
    ``\\ifdefined`` 后第二枚 (字母紧邻)。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\pdfobj{a}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply_guard(ctx)
    assert ok
    first = _out(ctx)
    ok, _ = _apply_guard(ctx)
    assert not ok  # 二轮 0-edit 弃守
    assert _out(ctx) == first


def test_route_single_line_def_guard_first(tmp_path: Path) -> None:
    """路由层: 单行 def 站点仍由 guard(50) 先修, polyfill 不抢。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{\\pdfobj{<</N 1>>}}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rule = _match(ctx, "pdfobj", ErrReport())
    assert rule is not None
    assert rule.id == "pdftex_prim_guard"
    assert "\\def\\f{\\ifdefined\\pdfobj\\pdfobj{<</N 1>>}\\fi}" in _out(ctx)


def test_route_single_line_assign_def_guard_first(tmp_path: Path) -> None:
    """路由层: 单行赋值 def 站点同由 guard 先修。"""
    ctx = _ctx(
        tmp_path,
        "\\documentclass{article}\n\\def\\f{\\pdfoutput=1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    rule = _match(ctx, "pdfoutput", ErrReport())
    assert rule is not None
    assert rule.id == "pdftex_prim_guard"
    assert "\\def\\f{\\ifdefined\\pdfoutput\\pdfoutput=1\\fi}" in _out(ctx)
