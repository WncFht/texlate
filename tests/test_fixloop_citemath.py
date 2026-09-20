r"""citemath 匝道 (task #79): ``cite_in_math_mbox`` 规则 + ``invalid_in_math`` 分类钉。

natbib ``\@citex`` 未定义引用标记 ``{\reset@font\bfseries ?}`` 无盒裸置 →
数学域内 ``\cite`` 展开撞 ``\not@math@alphabet`` →
``Command \bfseries invalid in math mode`` 硬错且自续 (halt_on_error 死在
thebibliography 前, ``\bibcite`` 不落 .aux; gr-qc/9901082 实证,
tmp/lane-citemath/EVIDENCE.md)。修复 = ``latex209.wrap_math_cites`` 把
数学域内裸 cite 族调用裹进 ``\mbox{}`` (kernel 原语, 无 amsmath 依赖)。
同签名可由字面 ``{\bfseries X}`` 数学域误用触发——无 cite token 命中时
transform 返回 applied=False 自然 decline。
"""

from pathlib import Path

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport, Taxonomy


class _Eng:
    """builtin_transform 路径的最小引擎替身。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "cite_in_math_mbox")


def _apply(tmp_path: Path, pay: str | None = "bfseries") -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(tmp_path), _Eng(), pay, ErrReport()
    )


def _roundtrip(tmp_path: Path, body: str) -> str:
    (tmp_path / "main.tex").write_text(
        f"\\documentclass{{article}}\n\\begin{{document}}\n{body}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    return (tmp_path / "main.tex").read_text()


def _taxonomy() -> Taxonomy:
    return load_ruleset().taxonomy


# ─── taxonomy 路由 ───


def test_citemath_taxonomy_routes_signature() -> None:
    r"""``Command \X invalid in math mode`` → invalid_in_math, payload=cs 名。"""
    tax = _taxonomy()
    rep = ErrReport(
        first="! LaTeX Error: Command \\bfseries invalid in math mode.",
        ctx="l.42 $\\phi^i_{\\pm}=0 \\cite{HawMos}.$",
    )
    assert tax.classify(rep) == ("invalid_in_math", "bfseries")
    rep2 = ErrReport(first="! LaTeX Error: Command \\itshape invalid in math mode.")
    assert tax.classify(rep2) == ("invalid_in_math", "itshape")


def test_citemath_taxonomy_not_captured_by_syntax() -> None:
    r"""同句式不被 syntax 交替 (``improper`` 等) 抢先——invalid_in_math 先评。"""
    tax = _taxonomy()
    rep = ErrReport(
        first="! LaTeX Error: Command \\bfseries invalid in math mode.",
        ctx="l.1 x",
    )
    cat, _ = tax.classify(rep)
    assert cat == "invalid_in_math"
    assert cat != "syntax"


def test_citemath_taxonomy_other_unrelated_unchanged() -> None:
    """普通 LaTeX Error 仍落旧路由——新条目不抢面。"""
    tax = _taxonomy()
    rep = ErrReport(first="! LaTeX Error: Environment proof undefined.", ctx="l.5")
    assert tax.classify(rep)[0] == "env_undefined"


def test_citemath_taxonomy_warning_line_no_hijack() -> None:
    r"""ctx8 窗内 ``LaTeX (Font )?Warning: Command \X invalid in math mode``
    软警告不抢签——``LaTeX Error:`` 前缀锚 (loop1 多格带 \r/\small 警告)。"""
    tax = _taxonomy()
    for warn in (
        "LaTeX Warning: Command \\r invalid in math mode on input line 272.",
        "LaTeX Font Warning: Command \\small invalid in math mode on input line 9.",
    ):
        rep = ErrReport(
            first="! LaTeX Error: Environment proof undefined.",
            ctx=f"l.5 x\n{warn}",
        )
        assert tax.classify(rep)[0] == "env_undefined", warn


# ─── 规则注册 ───


def test_citemath_rule_registered() -> None:
    rule = _rule()
    assert rule.order == 105  # noqa: PLR2004 - schema 断言值
    assert rule.phase == "loop"
    assert rule.when["category"] == "invalid_in_math"
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "cite_in_math_mbox"
    assert rule.action["params"]["exts"] == [".tex"]


def test_citemath_when_gate_declines_other_categories(tmp_path: Path) -> None:
    rule = _rule()
    ctx = _ctx(tmp_path)
    assert actions._when_ok(rule.when, "invalid_in_math", "bfseries", ctx)  # noqa: SLF001
    for cat in ("syntax", "other", "undefined_cs", None):
        assert not actions._when_ok(rule.when, cat, None, ctx)  # noqa: SLF001


# ─── 命中面 ───


def test_citemath_wrap_dollar_cite(tmp_path: Path) -> None:
    r"""gr-qc/9901082 实证签名: ``$`` 内裸 ``\cite`` → ``\mbox{\cite}``。"""
    out = _roundtrip(tmp_path, "$\\phi^i_{\\pm}=0 \\cite{HawMos}.$")
    assert "\\mbox{\\cite{HawMos}}" in out


def test_citemath_wrap_equation_env(tmp_path: Path) -> None:
    r"""数学环境体内裸 ``\citep`` 同裹。"""
    out = _roundtrip(tmp_path, "\\begin{equation}\nx = \\citep{a}\n\\end{equation}")
    assert "\\mbox{\\citep{a}}" in out


def test_citemath_wrap_optional_args(tmp_path: Path) -> None:
    r"""``*`` + ``[pre][post]`` 可选参整段搬进盒内。"""
    out = _roundtrip(tmp_path, "$\\citet*[see][\\S5]{key}$")
    assert "\\mbox{\\citet*[see][\\S5]{key}}" in out


def test_citemath_wrap_multi_site(tmp_path: Path) -> None:
    """同一文件多数学域各裹各的。"""
    out = _roundtrip(tmp_path, "$\\cite{a}$ text $\\citep{b}$")
    assert "\\mbox{\\cite{a}}" in out
    assert "\\mbox{\\citep{b}}" in out


def test_citemath_wrap_multi_file(tmp_path: Path) -> None:
    """跨 .tex 文件各命中。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "$\\cite{a}$\n\\input{sub}\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "sub.tex").write_text("$\\citep{b}$\n", encoding="utf-8")
    ok, note = _apply(tmp_path)
    assert ok, note
    assert "\\mbox{\\cite{a}}" in (tmp_path / "main.tex").read_text()
    assert "\\mbox{\\citep{b}}" in (tmp_path / "sub.tex").read_text()


def test_citemath_idempotent(tmp_path: Path) -> None:
    r"""已裹调用居 ``\mbox`` 文本域不再命中 → 第二轮 applied=False。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n$\\cite{a}$\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert ok
    ok, _ = _apply(tmp_path)
    assert not ok


# ─── decline / 豁免面 ───


def test_citemath_declines_literal_bfseries(tmp_path: Path) -> None:
    r"""同签名可由字面 ``{\bfseries X}`` 触发——无 cite token → applied=False。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "${\\bfseries X} + 1$\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert not ok
    assert "no bare cite-family" in note
    assert "\\mbox" not in (tmp_path / "main.tex").read_text()


def test_citemath_declines_text_mode_cite(tmp_path: Path) -> None:
    r"""文本域 ``\cite`` 本就合法——不动, applied=False。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "see \\cite{a} end\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert not ok
    assert "\\mbox" not in (tmp_path / "main.tex").read_text()


def test_citemath_declines_no_math(tmp_path: Path) -> None:
    """无数学域文档 → 0 改写。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "plain text only\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert not ok


def test_citemath_mbox_arg_exempt(tmp_path: Path) -> None:
    r"""``\mbox``/``\text`` 实参内 cite 居文本域——不二裹。"""
    src = "$x + \\mbox{\\cite{a}} + \\text{\\citep{b}}$"
    (tmp_path / "main.tex").write_text(
        f"\\documentclass{{article}}\n\\begin{{document}}\n{src}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert not ok
    assert src in (tmp_path / "main.tex").read_text()


def test_citemath_comment_shielded(tmp_path: Path) -> None:
    r"""注释内同形不参与 (visible_tex 遮蔽面)。"""
    out = _roundtrip(tmp_path, "$a % \\cite{x}\n + b$\n% $\\cite{y}$\n$\\cite{z}$")
    assert "\\mbox{\\cite{z}}" in out
    assert "\\mbox{\\cite{x}" not in out
    assert "\\mbox{\\cite{y}" not in out


def test_citemath_ref_eqref_untouched(tmp_path: Path) -> None:
    r"""``\ref``/``\eqref`` 走 ``\nfss@text`` 本就安全——不收。"""
    out = _roundtrip(tmp_path, "$x \\ref{a} \\eqref{b} \\cite{c}$")
    assert "\\mbox{\\cite{c}}" in out
    assert "\\mbox{\\ref" not in out
    assert "\\mbox{\\eqref" not in out


def test_citemath_cite_no_key_untouched(tmp_path: Path) -> None:
    r"""缺 ``{key}`` 的残缺 ``\cite`` 不裹。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "$x + \\cite + y$\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(tmp_path)
    assert not ok


def test_citemath_ruleset_loads() -> None:
    rs = load_ruleset()
    ids = [r.id for r in rs.rules]
    assert len(ids) == len(set(ids))
    assert "cite_in_math_mbox" in ids
    assert "invalid_in_math" in {e["id"] for e, _p in rs.taxonomy.head}
