r"""endsfix lane (task #213, 2026-09-19): Missing \endcsname 双修钉。

格面 (endcsdiag 普查, tmp/lane-endcsdiag/report.md):

1. misschar 回退块早于 xeCJK/ctex 装载活化字符 —— ``_fb_snippet_lines``
   发在 ``\documentclass`` 后的 ``\newunicodechar`` 逐字激活把 CJK 带
   缺字 (xeCJK punct 默认表码位 U+30FB 等) 置成 ``\protected`` 活动字,
   后装的 xeCJK ``\keys_set`` punct 表 ``\tl_new:c`` csname 化时吞到
   ``\protect`` → Missing \endcsname (2609.19944/2410.18001)。修 =
   逐字行整体收 ``\AtBeginDocument`` (begindocument 钩先于
   ``\@onlypreamble`` 废名执行, ``\newunicodechar`` 钩内仍合法;
   latex.ltx ``\document`` 序实测)。(virgin xelatex 实测:
   旧形炸 xeCJK.sty:4544 ``<to be read again> \protect``, 新形
   clean 且 ``\catcode`・=\active`` 生效。)

2. ``babel_preclass_rawopts_seed`` (rules/75-syntax.yaml:199): 稿首
   ``\RequirePackage[british]{babel}`` 先于 ``\documentclass`` 时
   ``\@raw@classoptionslist`` 尚是 kernel ``\relax`` (latex.ltx:18355,
   首个 class 选项处理才 ``\gdef``) → babel.sty:4230 把它当 1-项
   clist 迭代 → 文件名 csname 吞不可展开 token。修 = 预载 babel
   行头 csname 形 ``\def\@raw@classoptionslist{}`` (0806.3242,
   loop1→loop3 持续; 实编收口: 播种后 virgin xelatex clean)。
"""

from functools import lru_cache
from pathlib import Path

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop._builtins_misschar import _fb_snippet_lines
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.fixloop.logparse import ErrReport, parse_text

_ENDCS_ERR = (
    "! Missing \\endcsname inserted.\n"
    "<to be read again>\n"
    "                   \\protect\n"
    "l.4544   }\n"
)

_BABEL_ENDCS_ERR = (
    "! Missing endcsname inserted.\n"
    "<to be read again>\n"
    "                   @raw@classoptionslist\n"
    "l.4259   \\fi}\n"
)


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _rule(rid: str) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _ctx(tmp_path: Path, err_head: str = "") -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


def _classify(text: str) -> tuple[str | None, str | None]:
    return _rs().taxonomy.classify(parse_text(text, _rs().warn_patterns))


class _Eng:
    """regex_rewrite/condition 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _apply(
    rule: Rule, tmp_path: Path, err_head: str = "", pay: str | None = None
) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        rule, _ctx(tmp_path, err_head), _Eng(), pay, ErrReport()
    )


# ═══════════════════ item 1: misschar 逐字块 \AtBeginDocument 迟延 ═══════════════════


def test_fb_snippet_head_lines_stable() -> None:
    """头部四行 (marker/usepackage/fontspec 守卫/fontfamily) 补丁前后不变。"""
    lines = _fb_snippet_lines([0x0100], "Noto Serif")
    assert lines[:4] == [
        "% fixloop: per-char font fallback via newunicodechar",
        "\\usepackage{newunicodechar}",
        "\\ifdefined\\newfontfamily\\else\\usepackage{fontspec}\\fi",
        "\\ifdefined\\txlatefallback\\else\\newfontfamily\\txlatefallback{Noto Serif}\\fi",
    ]


def test_fb_snippet_chars_emitted() -> None:
    """逐字 ``\\newunicodechar{X}`` 行仍产出 (dedupe 键 ``\\newunicodechar{c}`` 不变)。"""
    lines = _fb_snippet_lines([0x0100, 0x0416, 0x30FB], "Noto Serif", "txlatecjkfb")
    blob = "\n".join(lines)
    assert "\\newunicodechar{Ā}" in blob
    assert "\\newunicodechar{Ж}" in blob
    assert "\\newunicodechar{・}" in blob
    assert "{\\txlatecjkfb ・}" in blob


def test_fb_snippet_math_escape_preserved() -> None:
    """替换体 ``\\ifmmode\\mbox`` 数学逃逸模板不随迟延改变。"""
    lines = _fb_snippet_lines([0x00C0], "FandolSong")
    assert any(
        ln == "\\newunicodechar{À}{\\ifmmode\\mbox{\\txlatefallback À}"
        "\\else{\\txlatefallback À}\\fi}"
        for ln in lines
    )


def test_fb_snippet_deferred_postpatch_contract() -> None:
    """全部 ``\\newunicodechar`` 行落在单个 ``\\AtBeginDocument{...}``
    内; ``\\usepackage``/``\\newfontfamily`` 行留在钩外导言区。"""
    got = _fb_snippet_lines([0x0100, 0x30FB], "Noto Serif", "txlatecjkfb")
    text = "\n".join(got)
    assert "\\AtBeginDocument{%" in text
    assert text.index("\\AtBeginDocument{%") < text.index("\\newunicodechar{Ā}")
    assert "\\usepackage{newunicodechar}" not in text.split("\\AtBeginDocument", 1)[1]
    acts = [ln for ln in got if ln.startswith("\\newunicodechar")]
    assert len(acts) == 2  # noqa: PLR2004 - 钉双码位契约
    tail = text.split("\\AtBeginDocument{%", 1)[1]
    assert all(ln in tail for ln in acts)


def test_fb_snippet_deferred_empty_acts_no_hook() -> None:
    """无可映射码位时不应空挂 ``\\AtBeginDocument{}``。"""
    got = _fb_snippet_lines([], "Noto Serif")
    assert not any("\\AtBeginDocument" in ln for ln in got)


# ═══════════════ item 2: babel_preclass_rawopts_seed (75-syntax:199) ═══════════════


def test_taxonomy_missing_endcsname_is_syntax() -> None:
    """Missing endcsname (带/不带反斜两形) → syntax 类。"""
    cat, _pay = _classify(_ENDCS_ERR)
    assert cat == "syntax"
    cat, _pay = _classify(_BABEL_ENDCS_ERR)
    assert cat == "syntax"


def test_rawopts_rule_registered() -> None:
    rule = _rule("babel_preclass_rawopts_seed")
    assert rule.order == 199  # noqa: PLR2004 - schema 断言值
    assert rule.when["category"] == "syntax"
    assert "endcsname" in rule.condition["ctx_suggests"]
    assert "babel" in rule.condition["source_contains"]
    assert rule.action["kind"] == "regex_rewrite"
    rw = rule.action["params"]["rewrites"][0]
    assert rw["match_surface"] == "masked"
    assert "@raw@classoptionslist" in rw["repl"]


def test_rawopts_seed_before_requirepackage(tmp_path: Path) -> None:
    """0806.3242 形: 播种落在 \\RequirePackage[british]{babel} 行头, 原行保留。"""
    (tmp_path / "main.tex").write_text(
        "\\RequirePackage[british]{babel}\n"
        "\\documentclass{amsart}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(_rule("babel_preclass_rawopts_seed"), tmp_path, _BABEL_ENDCS_ERR)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t.startswith("\\expandafter\\def\\csname @raw@classoptionslist\\endcsname{}")
    assert t.index("@raw@classoptionslist") < t.index(
        "\\RequirePackage[british]{babel}"
    )
    assert "\\RequirePackage[british]{babel}" in t
    assert "% fixloop: babel pre-class raw-opts seed" in t


def test_rawopts_seed_bare_and_group_forms(tmp_path: Path) -> None:
    """无表形 {babel} 与组载 {babel,geometry} 同盖。"""
    (tmp_path / "main.tex").write_text(
        "\\RequirePackage{babel}\n"
        "\\RequirePackage{babel,geometry}\n"
        "\\documentclass{article}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(_rule("babel_preclass_rawopts_seed"), tmp_path, _BABEL_ENDCS_ERR)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert t.count("@raw@classoptionslist") == 2  # noqa: PLR2004 - 两装载行各一种子


def test_rawopts_postclass_requirepackage_declines(tmp_path: Path) -> None:
    """\\documentclass 之后才 \\RequirePackage{babel} → 非本机制, applied=False。"""
    src = (
        "\\documentclass{article}\n"
        "\\RequirePackage{babel}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply(_rule("babel_preclass_rawopts_seed"), tmp_path, _BABEL_ENDCS_ERR)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_rawopts_commented_load_declines(tmp_path: Path) -> None:
    """masked 面: 注释掉的预载 babel 不锚 (假阳性面零改写)。"""
    src = (
        "% \\RequirePackage[british]{babel}\n"
        "\\documentclass{amsart}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply(_rule("babel_preclass_rawopts_seed"), tmp_path, _BABEL_ENDCS_ERR)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_rawopts_no_documentclass_declines(tmp_path: Path) -> None:
    """残缺稿无 \\documentclass → lookahead 失败, applied=False (保守不收)。"""
    src = "\\RequirePackage[british]{babel}\nx\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply(_rule("babel_preclass_rawopts_seed"), tmp_path, _BABEL_ENDCS_ERR)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_rawopts_condition_ctx_gate(tmp_path: Path) -> None:
    """ctx_suggests 闸: err_head 无 Missing endcsname → condition 拒。"""
    rule = _rule("babel_preclass_rawopts_seed")
    (tmp_path / "main.tex").write_text(
        "\\RequirePackage[british]{babel}\n\\documentclass{amsart}\n"
    )
    ctx = _ctx(tmp_path, "! Undefined control sequence.\nl.5 \\foo")
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, _Eng(), None
    )
    assert not ok, why


def test_rawopts_condition_source_gate(tmp_path: Path) -> None:
    """source_contains 闸: 源无预载 babel 形 (仅 post-class usepackage) → 拒。"""
    rule = _rule("babel_preclass_rawopts_seed")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage[british]{babel}\n"
    )
    ctx = _ctx(tmp_path, _BABEL_ENDCS_ERR)
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, _Eng(), None
    )
    assert not ok, why


def test_rawopts_condition_positive(tmp_path: Path) -> None:
    """双闸同过: endcsname 错 + 预载 babel 形 → condition 放行。"""
    rule = _rule("babel_preclass_rawopts_seed")
    (tmp_path / "main.tex").write_text(
        "\\RequirePackage[british]{babel}\n\\documentclass{amsart}\n"
    )
    ctx = _ctx(tmp_path, _BABEL_ENDCS_ERR)
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, _Eng(), None
    )
    assert ok, why


def test_rawopts_match_apply_routes(tmp_path: Path) -> None:
    """整链: syntax 类 + endcsname err + 预载 babel 源 → 本规则点火播种。"""
    (tmp_path / "main.tex").write_text(
        "\\RequirePackage[british]{babel}\n"
        "\\documentclass{amsart}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ctx = _ctx(tmp_path, _BABEL_ENDCS_ERR)
    rule, note = actions._match_apply(  # noqa: SLF001
        _rs(), ctx, _Eng(), "syntax", None, ErrReport()
    )
    assert rule is not None, note
    assert rule.id == "babel_preclass_rawopts_seed"
    assert "@raw@classoptionslist" in (tmp_path / "main.tex").read_text()
