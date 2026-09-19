r"""missmath 道 (task #215, 2026-09-19): Missing-$/{/number + Extra-\or 钉。

格面: stagerun-loop3 四族残件。
- ``revtex4_array_swap_guard`` 闸扩 (aastex6|aas\b): 包装类内载 revtex4-1
  → 同款 array v2.6n 校验失败换旧协议 → Extra \or (2306.06307/2111.00046/
  1907.00128)。
- ``verdate_pad``: aa.cls ``\def\filedate{2014/12/1}`` 日字段单段 → kernel
  ``\@parse@version`` 第4参吞 ``\@nil`` → Undefined-cs + Missing= + Missing
  number 三联 (1511.06717/1706.00225 同一份 doc-shipped cls)。
- ``endcomment_tail_split``: verbatim.sty comment env 要 ``\end{comment}``
  独占行, splice 黏尾被静默丢弃 → env 失衡 Missing$ (1803.00136)。
- ``missingdollar_blankline``: 数学区空白行 → ``\par`` → Missing$,
  file:NNN 报错行即空白行 (1306.0006/math-0408122/hep-th-0104212/
  1404.0082, 4/4 实证)。
- ``ifnum_typeout_banner``: ``\ifnum \typeout{}`` 横幅 hack → error-
  recovery 等价 ``\ifnum0=0`` (0905.0664/1206.0445 同模板逐字)。
"""

from functools import lru_cache
from pathlib import Path

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.fixloop.logparse import ErrReport


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _ctx(tmp_path: Path, err_head: str = "") -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


class _Eng:
    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _apply(rule: Rule, tmp_path: Path, err_head: str = "") -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        rule, _ctx(tmp_path, err_head), _Eng(), None, ErrReport()
    )


def _cond(rule: Rule, tmp_path: Path, err_head: str = "") -> tuple[bool, str]:
    return actions._cond_ok(  # noqa: SLF001 - 闸语义断言
        rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), None
    )


# ─────────────────────────────── 注册面 ───────────────────────────────
def test_rules_registered() -> None:
    for rid, order in {
        "verdate_pad": 199.2,
        "endcomment_tail_split": 199.3,
        "missingdollar_blankline": 199.4,
        "ifnum_typeout_banner": 199.5,
    }.items():
        rule = _rule(rid)
        assert rule.order == order, rid


# ─────────────────────────────── verdate_pad ───────────────────────────────
def test_verdate_condition_gate(tmp_path: Path) -> None:
    """无畸形日期 → condition 拒; 有 + Missing= ctx → 过。"""
    rule = _rule("verdate_pad")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    ok, _ = _cond(
        rule, tmp_path, "Missing = inserted for \\ifnum\nl.2 \\begin{document}"
    )
    assert not ok
    (tmp_path / "aa.cls").write_text("\\def\\filedate{2014/12/1}\n")
    ok, why = _cond(
        rule, tmp_path, "Missing = inserted for \\ifnum\nl.2 \\begin{document}"
    )
    assert ok, why


def test_verdate_any_category() -> None:
    """when any: undefined_cs (\\@nil payload) 与 syntax 两臂皆入。"""
    rule = _rule("verdate_pad")
    cands = rule.when.get("any")
    assert cands is not None
    cats = {c.get("category") for c in cands}
    assert {"undefined_cs", "syntax"} <= cats


def test_verdate_pads_single_digit_fields(tmp_path: Path) -> None:
    """日/月单段补两位: filedate 定义位 + Provides 尾括 + 请求尾括。"""
    (tmp_path / "aa.cls").write_text(
        "\\def\\filedate{2014/12/1}\n"
        "\\ProvidesClass{aa}[\\filedate{} v1.0 cls]\n"
    )
    (tmp_path / "main.tex").write_text(
        "\\documentclass{aa}\n"
        "\\usepackage{foo}[2005/2/22]\n"
        "\\usepackage{bar}[1999/10/05]\n"  # 良形不动
    )
    ok, note = _apply(_rule("verdate_pad"), tmp_path)
    assert ok, note
    cls = (tmp_path / "aa.cls").read_text()
    assert "\\def\\filedate{2014/12/01}" in cls
    tex = (tmp_path / "main.tex").read_text()
    assert "{foo}[2005/02/22]" in tex
    assert "{bar}[1999/10/05]" in tex


def test_verdate_idempotent(tmp_path: Path) -> None:
    """良形日期 int→02d 自同 —— 二跑零改写。"""
    (tmp_path / "x.sty").write_text(
        "\\ProvidesPackage{x}[2020/01/02 v1 ok]\n"
    )
    rule = _rule("verdate_pad")
    _apply(rule, tmp_path)
    before = (tmp_path / "x.sty").read_text()
    _apply(rule, tmp_path)
    assert (tmp_path / "x.sty").read_text() == before
    assert "2020/01/02" in before


# ─────────────────────────── endcomment_tail_split ───────────────────────────
def test_endcomment_condition_gate(tmp_path: Path) -> None:
    """Missing$ ctx + 黏尾字面 → 过; 独占行 → 拒。"""
    rule = _rule("endcomment_tail_split")
    (tmp_path / "main.tex").write_text(
        "\\begin{comment}\nx\n\\end{comment}\n\\begin{align}y\\end{align}\n"
    )
    ok, _ = _cond(rule, tmp_path, "Missing $ inserted.\nl.5 x")
    assert not ok
    (tmp_path / "main.tex").write_text(
        "\\end{comment}译文 \\begin{align}\n"
    )
    ok, why = _cond(rule, tmp_path, "Missing $ inserted.\nl.680 x")
    assert ok, why


def test_endcomment_splits_cs_tail(tmp_path: Path) -> None:
    """含 \\ 的尾拆行; \\end{comment} 独占。"""
    (tmp_path / "main.tex").write_text(
        "\\end{comment}这是译文 \\begin{align}\nE=mc^2\\end{align}\n"
    )
    ok, note = _apply(_rule("endcomment_tail_split"), tmp_path)
    assert ok, note
    lines = (tmp_path / "main.tex").read_text().split("\n")
    assert lines[0] == "\\end{comment}"
    assert lines[1] == "这是译文 \\begin{align}"


def test_endcomment_leaves_comment_and_prose_tails(tmp_path: Path) -> None:
    """% 头注释尾与纯散文尾不动 (verbatim 丢弃它们无 Missing$ 产出)。"""
    (tmp_path / "main.tex").write_text(
        "\\end{comment} % keep this comment\n"
        "\\end{comment} trailing prose\n"
    )
    _apply(_rule("endcomment_tail_split"), tmp_path)
    t = (tmp_path / "main.tex").read_text()
    assert "\\end{comment} % keep this comment\n" in t
    assert "\\end{comment} trailing prose\n" in t


# ─────────────────────────── missingdollar_blankline ───────────────────────────
def _mk_blank_cell(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\[\n"
        "a = b\n"
        "\n"
        "c = d\n"
        "\\]\n"
        "\\end{document}\n"
    )
    (tmp_path / "main.log").write_text(
        "./main.tex:5: Missing $ inserted.\n<inserted text>\n $\nl.5\n"
    )


def test_blankline_comments_reported_run(tmp_path: Path) -> None:
    """file:NNN=空白行 → 该行注 %。"""
    _mk_blank_cell(tmp_path)
    ok, note = _apply(_rule("missingdollar_blankline"), tmp_path)
    assert ok, note
    lines = (tmp_path / "main.tex").read_text().split("\n")
    assert lines[4] == "% fixloop: blank line in math"
    assert lines[3] == "a = b"
    assert lines[5] == "c = d"


def test_blankline_contiguous_run(tmp_path: Path) -> None:
    """连续空白段 (1404.0082 671-672 实证) 一次全注。"""
    (tmp_path / "main.tex").write_text("x\n\n\n\ny\n")
    (tmp_path / "main.log").write_text("./main.tex:2: Missing $ inserted.\n")
    _apply(_rule("missingdollar_blankline"), tmp_path)
    lines = (tmp_path / "main.tex").read_text().split("\n")
    assert lines[1:4] == ["% fixloop: blank line in math"] * 3
    assert lines[0] == "x" and lines[4] == "y"


def test_blankline_nonblank_site_noop(tmp_path: Path) -> None:
    """报错行非空白 (机制不符, 如黏尾) → 零触碰。"""
    (tmp_path / "main.tex").write_text("x\n\\end{comment}尾 \\begin{align}\ny\n")
    (tmp_path / "main.log").write_text("./main.tex:2: Missing $ inserted.\n")
    _apply(_rule("missingdollar_blankline"), tmp_path)
    assert "\\end{comment}尾 \\begin{align}" in (tmp_path / "main.tex").read_text()


def test_blankline_no_log_noop(tmp_path: Path) -> None:
    """无 .log → 站点零 → noop。"""
    (tmp_path / "main.tex").write_text("x\n\ny\n")
    _apply(_rule("missingdollar_blankline"), tmp_path)
    assert (tmp_path / "main.tex").read_text() == "x\n\ny\n"


# ─────────────────────────── ifnum_typeout_banner ───────────────────────────
def test_ifnum_condition_gate(tmp_path: Path) -> None:
    """Missing number ctx + \\ifnum\\typeout 字面 → 过; 无字面 → 拒。"""
    rule = _rule("ifnum_typeout_banner")
    (tmp_path / "main.tex").write_text("\\ifnum0=0 \\typeout{x}\\fi\n")
    ok, _ = _cond(rule, tmp_path, "Missing number, treated as zero.\nl.1")
    assert not ok
    (tmp_path / "main.tex").write_text(
        "\\ifnum \\typeout{}\\typeout{banner }\\typeout{} \\fi\n"
    )
    ok, why = _cond(rule, tmp_path, "Missing number, treated as zero.\nl.1")
    assert ok, why


def test_ifnum_rewrites_to_zero_eq_zero(tmp_path: Path) -> None:
    """\\ifnum \\typeout → \\ifnum0=0 \\typeout (恢复语义恒真横幅)。"""
    (tmp_path / "main.tex").write_text(
        "\\ifnum \\typeout{}\\typeout{radiative corrections }\\typeout{} "
        "\\vskip3mm\\centerline{x}\\vskip3mm \\fi\n"
    )
    ok, note = _apply(_rule("ifnum_typeout_banner"), tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\ifnum0=0 \\typeout{}" in t
    assert "\\ifnum \\typeout" not in t


def test_ifnum_leaves_wellformed(tmp_path: Path) -> None:
    """已有操作数的 \\ifnum 不动。"""
    (tmp_path / "main.tex").write_text(
        "\\ifnum\\value{page}>0 \\typeout{x}\\fi\n"
    )
    _apply(_rule("ifnum_typeout_banner"), tmp_path)
    assert "\\ifnum\\value{page}>0" in (tmp_path / "main.tex").read_text()


# ───────────────────── revtex4_array_swap_guard 闸扩 ─────────────────────
def test_or_guard_gate_wrapper_classes(tmp_path: Path) -> None:
    """aastex6x/aas 包装类过闸 (内载 revtex4-1); article 拒。"""
    rule = _rule("revtex4_array_swap_guard")
    for doccls in ("aastex63", "aastex62", "aas", "revtex4-1", "revtex4"):
        (tmp_path / "main.tex").write_text(
            f"\\documentclass{{{doccls}}}\n", encoding="utf-8"
        )
        ok, why = _cond(rule, tmp_path, "Extra \\or.\nl.10 \\begin{tabular}")
        assert ok, f"{doccls}: {why}"
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    ok, _ = _cond(rule, tmp_path, "Extra \\or.\nl.10 x")
    assert not ok


def test_or_guard_gate_option_brackets(tmp_path: Path) -> None:
    """带选项的 \\documentclass[opt]{aastex631} 同过。"""
    rule = _rule("revtex4_array_swap_guard")
    (tmp_path / "main.tex").write_text(
        "\\documentclass[twocolumn]{aastex631}\n"
    )
    ok, why = _cond(rule, tmp_path, "Extra \\or.\nl.10 x")
    assert ok, why
