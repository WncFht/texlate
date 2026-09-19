r"""optfix lane (2026-09-20): singlesweep 选项/驱动松弛三臂钉。

格面 (tmp/lane-singlesweep/mech_buckets.json, stagerun-m1k-2026-09-19):

- ``hyperref_driver_neutralize`` 扩臂 —— 2609.20135 webofc.cls 两未盖形:
  ``\newcommand\woc@driver{dvips}`` (newcommand 族间接指派, 旧 ``\def`` 单族
  不收) 与 ``\RequirePackage[\ifnum\pdfoutput=\z@ dvips,\else pdftex,\fi
  unicode=true,...]{hyperref}`` (选项括号内 ``\if*`` 双支裸驱动词 —— 驱动词
  无逗号前驱故括号三套够不着)。第一处覆写 ``xetex``, 第二处整条件塌成
  ``xetex,``。
- ``microtype_expansion_off`` —— 2310.02541: microtype ``expansion`` 族在
  XeTeX 下恒不工作 (microtype-xetex.def:874), ``expansion=true`` → ``false``;
  ``activate={..}`` 复合键无显式 expansion 键时尾补 ``,expansion=false``。
- ``xy_option_load`` —— 2607.14648: 群载 ``{..,xypic}`` 未开 curve 扩展,
  ``\ar@/_1pc/`` 钩形炸 "only available when curve extension loaded";
  ``\xyoption{<ext>}`` (xy.tex:1944 原生请求宏) 装载点后插补载。

覆盖确认 (无新码): pkg_order_hyperxmp_relocate 收 2105.00033
hyperxmp↔hyperref 序对 (acmart.cls:494-497 \let 三明治形); undefine_for_redef
包装载点清先定义臂收 2509.13676 ``\eth already defined at amssymb load``。
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
    """regex_rewrite/condition/builtin 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _apply(
    rule: Rule,
    tmp_path: Path,
    pay: str = "",
    err_head: str = "",
) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        rule, _ctx(tmp_path, err_head), _Eng(), pay, ErrReport()
    )


# ═════════════════════════ hyperref_driver_neutralize 扩臂 ═════════════════════

_WEBOCS_ERR = (
    "hyperref.sty:4072: Package hyperref Error: Wrong DVI mode driver option "
    "`dvips',\n"
)


def test_driver_newcommand_assignment(tmp_path: Path) -> None:
    """webofc.cls:154 实形: \\newcommand\\woc@driver{dvips} → {xetex}。"""
    cls = tmp_path / "webofc.cls"
    cls.write_text(
        "\\ifnum\\pdfoutput=\\z@\n"
        "  \\newcommand\\woc@driver{dvips}\n"
        "\\else\n"
        "  \\newcommand\\woc@driver{pdftex}\n"
        "\\fi\n"
        "\\RequirePackage[dvips]{hyperref}\n",
        encoding="utf-8",
    )
    ok, note = _apply(_rule("hyperref_driver_neutralize"), tmp_path)
    assert ok, note
    t = cls.read_text()
    assert "\\newcommand\\woc@driver{xetex}" in t
    assert "{dvips}" not in t
    assert "{pdftex}" not in t


def test_driver_newcommand_braced_cs(tmp_path: Path) -> None:
    """\\newcommand{\\cs}{drv} 花括号 cs 形与 \\def 旧形同愈。"""
    cls = tmp_path / "a.cls"
    cls.write_text(
        "\\newcommand{\\woc@driver}{dvips}\n"
        "\\def\\x@driver{pdftex}\n"
        "\\RequirePackage[dvips]{hyperref}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(_rule("hyperref_driver_neutralize"), tmp_path)
    assert ok
    t = cls.read_text()
    assert "\\newcommand{\\woc@driver}{xetex}" in t
    assert "\\def\\x@driver{xetex}" in t


def test_driver_inline_ifnum_conditional(tmp_path: Path) -> None:
    """webofc.cls:177 实形: 括号内 \\ifnum 双支裸驱动词 → xetex, 邻键全留。"""
    cls = tmp_path / "webofc.cls"
    cls.write_text(
        "\\RequirePackage[%\n"
        "  \\ifnum\\pdfoutput=\\z@\n"
        "    dvips,\n"
        "  \\else\n"
        "    pdftex,\n"
        "  \\fi\n"
        "  unicode=true,\n"
        "  \\if@online\n"
        "    bookmarks=true,\n"
        "  \\else\n"
        "    bookmarks=false,\n"
        "  \\fi\n"
        "  \\ifnum\\pdfoutput=\\z@\n"
        "    breaklinks=true,\n"
        "  \\fi\n"
        "  bookmarksnumbered=false\n"
        "]\n"
        "{hyperref}\n",
        encoding="utf-8",
    )
    ok, note = _apply(_rule("hyperref_driver_neutralize"), tmp_path)
    assert ok, note
    t = cls.read_text()
    assert "dvips" not in t
    assert "pdftex" not in t
    assert "xetex," in t
    # 非驱动键条件与单支条件原样保留
    assert "\\if@online" in t
    assert "bookmarks=true" in t
    assert "breaklinks=true" in t


def test_driver_conditional_outside_bracket_untouched(tmp_path: Path) -> None:
    """bracket 外同形 \\if 双支驱动词 (正文排版条件) 不收 —— `[^\\]]` 锚。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\ifnum\\pdfoutput=\\z@\n"
        "  dvips,\n"
        "\\else\n"
        "  pdftex,\n"
        "\\fi\n"
        "\\begin{document}x\\end{document}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(_rule("hyperref_driver_neutralize"), tmp_path)
    # 无 bracket 内驱动词/指派 → 本规则整体 applied=False
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert "dvips," in t


def test_driver_condition_gate_newcommand_form(tmp_path: Path) -> None:
    """source_contains 新支: 仅 newcommand 指派 + cs 引用括号即放行。"""
    (tmp_path / "main.tex").write_text(
        "\\newcommand\\woc@driver{dvips}\n"
        "\\RequirePackage[\\woc@driver]{hyperref}\n",
        encoding="utf-8",
    )
    ctx = _ctx(tmp_path)
    rule = _rule("hyperref_driver_neutralize")
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, _Eng(), "dvips"
    )
    assert ok, why


def test_driver_condition_gate_clean_doc_rejects(tmp_path: Path) -> None:
    """干净文档无驱动词 → source_contains 拒 (other 桶不盲点火)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{amsmath}\n", encoding="utf-8"
    )
    ctx = _ctx(tmp_path)
    rule = _rule("hyperref_driver_neutralize")
    ok, _ = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, ctx, _Eng(), None
    )
    assert not ok


# ═════════════════════════ microtype_expansion_off ═════════════════════════

_MT_ERR = (
    "main.tex:323: Package microtype Error: Font expansion does not work with "
    "xetex.\n"
)


def test_microtype_expansion_multiline_flip(tmp_path: Path) -> None:
    """2310.02541 实形: 多行括号 expansion=true → false, 邻键全留。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage{hyperref}\n"
        "%\\usepackage[protrusion=false,expansion=true]{microtype}\n"
        "%\\usepackage[activate={true,nocompatibility},final]{microtype}\n"
        "\\usepackage[    protrusion=true,\n"
        "expansion=true,\n"
        "final,\n"
        "babel\n"
        "]{microtype}\n",
        encoding="utf-8",
    )
    ok, note = _apply(
        _rule("microtype_expansion_off"), tmp_path, err_head=_MT_ERR
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "expansion=false," in t
    assert "protrusion=true" in t
    assert "babel\n]{microtype}" in t
    # masked 面: 注释内候选配置不动
    assert "%\\usepackage[protrusion=false,expansion=true]{microtype}" in t
    assert "%\\usepackage[activate={true,nocompatibility},final]{microtype}" in t


def test_microtype_expansion_passoptions(tmp_path: Path) -> None:
    """\\PassOptionsToPackage{expansion=true}{microtype} 大括号形同愈。"""
    (tmp_path / "main.tex").write_text(
        "\\PassOptionsToPackage{protrusion,expansion=true}{microtype}\n"
        "\\usepackage{microtype}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(_rule("microtype_expansion_off"), tmp_path, err_head=_MT_ERR)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\PassOptionsToPackage{protrusion,expansion=false}{microtype}" in t


def test_microtype_activate_fallback(tmp_path: Path) -> None:
    """activate 复合键且无显式 expansion 键 → 尾补 ,expansion=false。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage[activate={true,nocompatibility},final]{microtype}\n",
        encoding="utf-8",
    )
    ok, _ = _apply(_rule("microtype_expansion_off"), tmp_path, err_head=_MT_ERR)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "activate={true,nocompatibility},final,expansion=false]" in t


def test_microtype_expansion_false_noop(tmp_path: Path) -> None:
    """expansion=false 已备 → applied=False 不重复点火。"""
    src = "\\usepackage[expansion=false]{microtype}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply(_rule("microtype_expansion_off"), tmp_path, err_head=_MT_ERR)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_microtype_other_pkg_bracket_untouched(tmp_path: Path) -> None:
    """expansion 键在他包括号不动 —— `]{microtype}` 后缀绑定。"""
    src = "\\usepackage[expansion=true]{otherpkg}\n\\usepackage{microtype}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply(_rule("microtype_expansion_off"), tmp_path, err_head=_MT_ERR)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_microtype_condition_gate(tmp_path: Path) -> None:
    """ctx_suggests 闸: err_head 无 'expansion does not work' → 拒。"""
    rule = _rule("microtype_expansion_off")
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, "! some other error"), _Eng(), None
    )
    assert not ok, why
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, _MT_ERR), _Eng(), None
    )
    assert ok, why


# ═════════════════════════ xy_option_load ════════════════════════════════════

_XY_ERR = (
    "largeaffinesymplectic.tex:2401: Xy-pic error: Forms @/.../, @(...), and "
    "@`{...}, only available when curve\n"
    "extension loaded.\n"
)


def test_xy_rule_registered() -> None:
    """规则面: builtin_transform xy_option_load, other+syntax 双臂。"""
    rule = _rule("xy_option_load")
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "xy_option_load"
    cats = [c["category"] for c in rule.when["any"]]
    assert "other" in cats
    assert "syntax" in cats


def test_xy_group_load_inject(tmp_path: Path) -> None:
    """2607.14648 实形: 群载 {..,xypic} 后插 \\xyoption{curve}。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage{amsmath, amsfonts, amscd, amssymb, amsthm, enumerate, xypic}\n"
        "\\begin{document}\\xymatrix{A \\ar@/_1pc/[r] & B}\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(_rule("xy_option_load"), tmp_path, err_head=_XY_ERR)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "xypic}\n\\xyoption{curve}" in t


def test_xy_bare_xy_pkg(tmp_path: Path) -> None:
    """\\usepackage{xy} 独载形同愈 (xy.sty 直载面)。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage{xy}\n", encoding="utf-8"
    )
    ok, _ = _apply(_rule("xy_option_load"), tmp_path, err_head=_XY_ERR)
    assert ok
    assert "\\xyoption{curve}" in (tmp_path / "main.tex").read_text()


def test_xy_feature_phrasings(tmp_path: Path) -> None:
    """xygraph 系 'feature not loaded' 句式 → matrix/poly/arc 名归一。"""
    for head, ext in [
        ("Xy-pic error: matrix feature not loaded", "matrix"),
        ("Xy-pic error: poly(gon) feature not loaded", "poly"),
        ("Xy-pic error: (ellipse+)arc feature not loaded", "arc"),
    ]:
        d = tmp_path / ext
        d.mkdir()
        (d / "main.tex").write_text("\\usepackage{xypic}\n", encoding="utf-8")
        ok, note = _apply(_rule("xy_option_load"), d, err_head=head + "\n")
        assert ok, (head, note)
        assert f"\\xyoption{{{ext}}}" in (d / "main.tex").read_text()


def test_xy_idempotent_live_loaded(tmp_path: Path) -> None:
    """live \\xyoption{curve} 已备 → applied=False。"""
    src = "\\usepackage{xypic}\n\\xyoption{curve}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply(_rule("xy_option_load"), tmp_path, err_head=_XY_ERR)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_xy_commented_xyoption_still_injects(tmp_path: Path) -> None:
    """注释内 \\xyoption{curve} 不算已载 —— live 面仍补插。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage{xypic}\n% \\xyoption{curve}\n", encoding="utf-8"
    )
    ok, _ = _apply(_rule("xy_option_load"), tmp_path, err_head=_XY_ERR)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "xypic}\n\\xyoption{curve}" in t
    assert "% \\xyoption{curve}" in t


def test_xy_no_load_site_noop(tmp_path: Path) -> None:
    """工程无 xy/xypic 装载点 → applied=False (err 有签名也无处挂)。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage{amsmath}\n", encoding="utf-8"
    )
    ok, _ = _apply(_rule("xy_option_load"), tmp_path, err_head=_XY_ERR)
    assert not ok


def test_xy_no_error_noop(tmp_path: Path) -> None:
    """err_head/log 无扩展缺失句式 → applied=False。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage{xypic}\n", encoding="utf-8"
    )
    ok, _ = _apply(_rule("xy_option_load"), tmp_path, err_head="! unrelated")
    assert not ok


def test_xy_commented_load_untouched(tmp_path: Path) -> None:
    """masked 面: 注释内假装载点不挂 —— 唯一 xypic 站是死站 → applied=False。"""
    src = "% \\usepackage{xypic}\n\\usepackage{amsmath}\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, _ = _apply(_rule("xy_option_load"), tmp_path, err_head=_XY_ERR)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


# ════════════════════════ 既有臂覆盖钉 (无新码) ════════════════════════════════


def test_hyperxmp_relocate_covers_let_sandwich(tmp_path: Path) -> None:
    """2105.00033 覆盖钉: acmart.cls hyperxmp→\\let 三明治→hyperref 序对下沉。"""
    (tmp_path / "acmart.cls").write_text(
        "\\RequirePackage{hyperxmp}\n"
        "\\let\\ACM@lr@list\\@empty\n"
        "\\let\\ACM@layout\\@empty\n"
        "\\RequirePackage[bookmarksnumbered,unicode]{hyperref}\n",
        encoding="utf-8",
    )
    ok, note = _apply(
        _rule("pkg_order_hyperxmp_relocate"), tmp_path, pay="hyperxmp"
    )
    assert ok, note
    t = (tmp_path / "acmart.cls").read_text()
    assert t.index("{hyperref}") < t.index("{hyperxmp}")
    assert "\\let\\ACM@lr@list\\@empty" in t
