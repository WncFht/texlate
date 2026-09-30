r"""driverdef 车道 (2026-09-19): ``hyperref_driver_neutralize`` def 间接指派臂。

2403.00013 (kaist-ucs.cls) 形: cls 内部 ``\ifpdf``/``\if@dvips`` 条件选支
``\def\@drivername{pdftex|dvipdfmx|dvips}`` 后 ``\RequirePackage[\@drivername]
{graphicx,xcolor}`` —— 驱动词藏在 ``\def`` 值里, 选项括号面只见 cs 名,
旧闸 ``\[..\b(drv)\b..\]`` 够不着 → hyperref 炸 ``Wrong DVI mode driver
option `dvipdfmx'`` (fixloop 零命中, best_effort_pdf 52 错)。根修 = def 值
直接覆写 ``xetex`` (xelatex/tectonic 下无论哪支条件命中都须是 xetex),
与括号剥词臂语义一致 (xetex 家族下这些驱动本就走不通)。
"""

from collections.abc import Callable
from pathlib import Path

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport


class _Eng:
    """regex_rewrite/condition 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


_DRV_ERR = "! Package hyperref Error: Wrong DVI mode driver option `dvipdfmx',"


def _ctx(tmp_path: Path, err_head: str = _DRV_ERR) -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


def _lane(
    rid: str,
    pay: str | None,
) -> tuple[
    Callable[[], Rule],
    Callable[[Path], tuple[bool, str]],
    Callable[..., tuple[bool, str]],
]:
    """rid+payload 参数化的 ``_rule``/``_apply``/``_cond`` 三件套——driver 臂同构直驱面。"""

    def _rule() -> Rule:
        return next(r for r in load_ruleset().rules if r.id == rid)

    def _apply(tmp_path: Path) -> tuple[bool, str]:
        return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
            _rule(), _ctx(tmp_path), _Eng(), pay, ErrReport()
        )

    def _cond(tmp_path: Path, err_head: str = _DRV_ERR) -> tuple[bool, str]:
        rule = _rule()
        return actions._cond_ok(  # noqa: SLF001
            rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), pay
        )

    return _rule, _apply, _cond


_rule, _apply, _cond = _lane("hyperref_driver_neutralize", "dvipdfmx")


_KAIST_CLS = (
    "\\RequirePackage[nonfrench]{dhucs}\n"
    "\\RequirePackage{ifpdf}\n"
    "\\ifpdf\n"
    "\\def\\@drivername{pdftex}\n"
    "\\else\n"
    "\\def\\@drivername{dvipdfmx}\n"
    "\\fi\n"
    "\\if@dvips\n"
    "\\def\\@drivername{dvips}\n"
    "\\fi\n"
    "\\RequirePackage[\\@drivername]{graphicx,xcolor}\n"
)


def test_driverdef_rule_registered() -> None:
    rule = _rule()
    assert rule.order == 181  # noqa: PLR2004 - schema 断言值
    assert rule.action["kind"] == "regex_rewrite"
    rw_pats = [rw["pattern"] for rw in rule.action["params"]["rewrites"]]
    assert any("def" in p and "driver" in p for p in rw_pats)


def test_driverdef_cond_passes_def_form(tmp_path: Path) -> None:
    """kaist-ucs 形：括号面无驱动词，def 指派存在 → 闸放行。"""
    (tmp_path / "main.tex").write_text("\\documentclass{kaist-ucs}\nx\n")
    (tmp_path / "kaist-ucs.cls").write_text(_KAIST_CLS)
    ok, why = _cond(tmp_path)
    assert ok, why


def test_driverdef_cond_passes_def_variants(tmp_path: Path) -> None:
    """\\gdef/\\edef/\\xdef + cs 名含 driver 前缀/后缀变体均过闸。"""
    for dfn in (
        "\\gdef\\mydriverset{dvips}",
        "\\edef\\predriver{pdftex}",
        "\\xdef\\@drivername{dvipdfmx}",
    ):
        (tmp_path / "main.tex").write_text(f"\\documentclass{{article}}\n{dfn}\n")
        ok, why = _cond(tmp_path)
        assert ok, f"{dfn}: {why}"


def test_driverdef_cond_still_passes_bracket_form(tmp_path: Path) -> None:
    """括号字面驱动词旧路径回归：[dvipdfmx] 依旧放行。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage[dvipdfmx]{hyperref}\n"
    )
    ok, why = _cond(tmp_path)
    assert ok, why


def test_driverdef_cond_declines_no_driver(tmp_path: Path) -> None:
    """无括号驱动词亦无 def 指派 → 闸拒。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{hyperref}\n"
        "\\def\\@drivername{customdrv}\n"
    )
    ok, _ = _cond(tmp_path)
    assert not ok


def test_driverdef_cond_declines_non_driver_def(tmp_path: Path) -> None:
    """def 值非驱动词 (\\def\\videodriver{foo}) → 第三交替不命中。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\def\\videodriver{custom}\n"
    )
    ok, _ = _cond(tmp_path)
    assert not ok


def test_driverdef_apply_rewrites_all_branches(tmp_path: Path) -> None:
    """if/else/fi 三支 def 全覆写 xetex; 其余行原样。"""
    (tmp_path / "kaist-ucs.cls").write_text(_KAIST_CLS)
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "kaist-ucs.cls").read_text()
    assert "\\def\\@drivername{xetex}" in t
    assert "dvipdfmx" not in t
    assert "pdftex}" not in t
    assert "{dvips}" not in t
    assert "\\RequirePackage[\\@drivername]{graphicx,xcolor}" in t


def test_driverdef_apply_gdef_edef(tmp_path: Path) -> None:
    """\\gdef/\\edef 变体同覆写。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\gdef\\maindriver{dvips}\n"
        "\\edef\\driverselect{pdftex}\n"
    )
    ok, _ = _apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\gdef\\maindriver{xetex}" in t
    assert "\\edef\\driverselect{xetex}" in t


def test_driverdef_apply_leaves_non_driver_defs(tmp_path: Path) -> None:
    """非驱动值 def 不动：\\def\\@drivername{custom} 原样保留。"""
    src = "\\documentclass{article}\n\\def\\@drivername{customdrv}\n"
    (tmp_path / "main.tex").write_text(src)
    ok, _ = _apply(tmp_path)
    # 无驱动词命中 → applied=False (改写面零命中)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_driverdef_apply_cs_without_driver_substr_untouched(
    tmp_path: Path,
) -> None:
    """cs 名不含 driver 子串的 def 不命中 (\\def\\foo{dvips} 保守拒)。"""
    src = "\\documentclass{article}\n\\def\\foo{dvips}\n"
    (tmp_path / "main.tex").write_text(src)
    ok, _ = _apply(tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_driverdef_apply_bracket_and_def_together(tmp_path: Path) -> None:
    """括号 + def 混合面一遍过：[dvips]→[], \\def\\@drivername{dvipdfmx}→xetex。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[dvips]{article}\n\\def\\@drivername{dvipdfmx}\n"
        "\\usepackage[\\@drivername]{graphicx}\n"
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\documentclass[]{article}" not in t  # 空括号清扫后无 [] 残留
    assert "\\documentclass{article}" in t
    assert "\\def\\@drivername{xetex}" in t


def test_driverdef_apply_whitespace_in_braces(tmp_path: Path) -> None:
    """值域空白容忍：\\def\\@drivername{ dvipdfmx } → {xetex}。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\def\\@drivername  { dvipdfmx }\n"
    )
    ok, _ = _apply(tmp_path)
    assert ok
    assert "\\def\\@drivername  {xetex}" in (tmp_path / "main.tex").read_text()


def test_driverdef_ruleset_loads() -> None:
    """本文件钉的三条 driver 规则全在库（规模地板已被甩开，改在场钉）。"""
    ids = {r.id for r in load_ruleset().rules}
    assert {
        "hyperref_driver_neutralize",
        "pdftex_driver_opt_strip",
        "iftex_engine_guard_neutralize",
    } <= ids


# ────────────────────────────────────────────────────────────────
# pdftex_driver_opt_strip (55-prim order 48): [pdftex] 驱动选项残存 →
# xelatex 载 pdftex.def → \pdfcolorstack undefined → chardef 残值排字
# (loop3-1206.0240 ^^@×179 / 1706.07495 ^^@×106 多包括号面;
# 1306.0294 vendored cfg \ExecuteOptions{pdftex} 形 ^^A×20)。
# ────────────────────────────────────────────────────────────────


_opt_rule, _opt_apply, _opt_cond = _lane("pdftex_driver_opt_strip", "pdfcolorstack")


def test_pdftexopt_rule_registered() -> None:
    rule = _opt_rule()
    assert rule.order == 48  # noqa: PLR2004 - 先于 guard(50)/polyfill(51) 根修
    assert rule.action["kind"] == "regex_rewrite"
    rw_pats = [rw["pattern"] for rw in rule.action["params"]["rewrites"]]
    assert any("ExecuteOptions" in p for p in rw_pats)
    exts = rule.action["params"]["exts"]
    assert ".cfg" in exts  # vendored color.cfg/graphics.cfg 站点面


def test_pdftexopt_cond_passes_usepackage_site(tmp_path: Path) -> None:
    """1206.0240 形：\\usepackage[pdftex]{graphicx,color} → 闸放行。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage[pdftex]{graphicx,color}\n"
    )
    ok, why = _opt_cond(tmp_path)
    assert ok, why


def test_pdftexopt_cond_passes_sty_mention_for_cfg_cell(tmp_path: Path) -> None:
    """1306.0294 形：source_blob(.sty 可见) 内 pdftex 字样放行 cfg 改写面。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    (tmp_path / "geometry.sty").write_text("\\def\\Gm@pdftex{pdftex}\n")
    ok, why = _opt_cond(tmp_path)
    assert ok, why


def test_pdftexopt_cond_declines_no_pdftex(tmp_path: Path) -> None:
    """源内无 pdftex 字样 → 闸拒。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage[svgnames]{xcolor}\n"
    )
    ok, _ = _opt_cond(tmp_path)
    assert not ok


def test_pdftexopt_apply_strips_multipkg_bracket(tmp_path: Path) -> None:
    """多包括号主案：[pdftex]{graphicx,color} → 裸装载 (graphicx 自侦 xetex)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage[pdftex]{graphicx,color}\n"
    )
    ok, note = _opt_apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{graphicx,color}" in t
    assert "pdftex" not in t


def test_pdftexopt_apply_strips_mid_bracket(tmp_path: Path) -> None:
    """括号中段：[hyperindex, pdftex,colorlinks] → 驱动词独剥。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage[hyperindex, pdftex,colorlinks=true,backref]{hyperref}\n"
    )
    ok, _ = _opt_apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "pdftex" not in t
    assert "hyperindex" in t
    assert "colorlinks=true" in t


def test_pdftexopt_apply_executeoptions_cfg(tmp_path: Path) -> None:
    """vendored cfg 选支：\\ExecuteOptions{pdftex} → {xetex} (兄弟选项保全)。"""
    cfg = (
        "\\@ifundefined{pdfoutput}%\n"
        "  {\\let\\pdfoutput\\@undefined\n   \\ExecuteOptions{dvips}}%\n"
        "  {\\ifcase\\pdfoutput\n      \\ExecuteOptions{dvips}%\n"
        "   \\else\n      \\ExecuteOptions{pdftex}%\n   \\fi}%\n"
    )
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    (tmp_path / "color.cfg").write_text(cfg)
    (tmp_path / "geometry.sty").write_text("\\def\\Gm@pdftex{pdftex}\n")
    ok, note = _opt_apply(tmp_path)
    assert ok, note
    t = (tmp_path / "color.cfg").read_text()
    assert "\\ExecuteOptions{xetex}" in t
    assert "pdftex" not in t
    # .sty 内非选项面 pdftex 字样 (\def\Gm@pdftex{pdftex}) 不在改写形内 → 原样
    assert "\\def\\Gm@pdftex{pdftex}" in (tmp_path / "geometry.sty").read_text()


def test_pdftexopt_apply_comment_only_site_declines(tmp_path: Path) -> None:
    """masked 面：仅注释内 [pdftex] → 不改写不耗火 (applied=False)。"""
    src = "\\documentclass{article}\n%\\usepackage[pdftex]{graphicx}\n"
    (tmp_path / "main.tex").write_text(src)
    ok, _ = _opt_apply(tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_pdftexopt_apply_passopts_brace_form(tmp_path: Path) -> None:
    """PassOptionsToPackage{pdftex}{graphicx} 首参剥词。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\PassOptionsToPackage{pdftex}{graphicx}\n"
    )
    ok, _ = _opt_apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\PassOptionsToPackage{}{graphicx}" in t


def test_pdftexopt_apply_leaves_non_driver_opts(tmp_path: Path) -> None:
    """对照：非驱动选项 [svgnames] 与无括号装载原样。"""
    src = (
        "\\documentclass{article}\n"
        "\\usepackage[svgnames]{xcolor}\n\\usepackage{graphicx}\n"
    )
    (tmp_path / "main.tex").write_text(src)
    ok, _ = _opt_apply(tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


# ────────────────────────────────────────────────────────────────
# drvopt-ext (2026-09-19): opt_strip 词闸拓宽 (pdftex→驱动词表) +
# def 臂 [Dd]river 大小写 + \\newcommand 族指派臂。
# 实证面：aa.cls/webofc.cls \\newcommand\\<cs>driver{dvips|pdftex}
# 条件选支 (~12 distinct cells); xcolor.sty \\def\\GinDriver{hypertex}
# (3 cells); maple2e.sty \\edef\\Driver{dvips 系} (1 cell)。
# ────────────────────────────────────────────────────────────────

_AA_CLS = (
    "\\ifx\\pdfoutput\\undefined\\newcount\\pdfoutput\\fi\n"
    "\\ifnum\\pdfoutput=\\z@\n"
    "  \\newcommand\\aa@driver{dvips}\n"
    "\\else\n"
    "  \\newcommand\\aa@driver{pdftex}\n"
    "\\fi\n"
    "\\RequirePackage[\\aa@driver,a4paper]{geometry}\n"
)


def test_pdftexopt_cond_passes_dvips_only_cell(tmp_path: Path) -> None:
    """词闸拓宽：无 pdftex 字样仅 dvips 的格 (hep-lat 形) 放行。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage[dvips]{graphicx,color}\n"
    )
    ok, why = _opt_cond(tmp_path)
    assert ok, why


def test_pdftexopt_cond_passes_hypertex_only_cell(tmp_path: Path) -> None:
    """词闸拓宽：xcolor.sty \\GinDriver{hypertex} 格 (0806.4130 形) 放行。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    (tmp_path / "xcolor.sty").write_text("\\def\\GinDriver{hypertex}\n")
    ok, why = _opt_cond(tmp_path)
    assert ok, why


def test_pdftexopt_cond_declines_driverless(tmp_path: Path) -> None:
    """对照：无任何驱动词 → 闸拒 (拓宽后仍守)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage[svgnames]{xcolor}\n"
        "\\newcommand{\\mydriver}{custom}\n"
    )
    ok, _ = _opt_cond(tmp_path)
    assert not ok


def test_pdftexopt_apply_newcommand_both_branches(tmp_path: Path) -> None:
    """aa.cls 形：\\newcommand\\aa@driver{dvips}/{pdftex} 两支全覆写 xetex。"""
    (tmp_path / "aa.cls").write_text(_AA_CLS)
    ok, note = _opt_apply(tmp_path)
    assert ok, note
    t = (tmp_path / "aa.cls").read_text()
    assert "\\newcommand\\aa@driver{xetex}" in t
    assert "{dvips}" not in t
    assert "{pdftex}" not in t
    assert "\\RequirePackage[\\aa@driver,a4paper]{geometry}" in t


def test_pdftexopt_apply_newcommand_braced_cs(tmp_path: Path) -> None:
    """primaldual 形：\\newcommand{\\mydriver}/{\\renewcommand} 花括号 cs 面。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\newcommand{\\mydriver}{hypertex}\n"
        "\\renewcommand{\\mydriver}{pdftex}\n"
    )
    ok, _ = _opt_apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\newcommand{\\mydriver}{xetex}" in t
    assert "\\renewcommand{\\mydriver}{xetex}" in t


def test_pdftexopt_apply_gindriver_capital(tmp_path: Path) -> None:
    """xcolor.sty \\def\\GinDriver{hypertex}: [Dd]river 大写臂覆写。"""
    (tmp_path / "xcolor.sty").write_text("\\def\\GinDriver{hypertex}\n")
    ok, _ = _opt_apply(tmp_path)
    assert ok
    assert "\\def\\GinDriver{xetex}" in (tmp_path / "xcolor.sty").read_text()


def test_pdftexopt_apply_edef_driver_capital(tmp_path: Path) -> None:
    """maple2e.sty \\edef\\Driver{dvips}: edef+ 大写 Driver 同覆写。"""
    (tmp_path / "maple2e.sty").write_text("\\edef\\Driver{dvips}\n")
    ok, _ = _opt_apply(tmp_path)
    assert ok
    assert "\\edef\\Driver{xetex}" in (tmp_path / "maple2e.sty").read_text()


def test_pdftexopt_apply_newcommand_non_driver_untouched(tmp_path: Path) -> None:
    """保守面：\\newcommand\\driver{custom} 非驱动值不改写。"""
    src = "\\documentclass{article}\n\\newcommand{\\mydriver}{custom}\n"
    (tmp_path / "main.tex").write_text(src)
    ok, _ = _opt_apply(tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


# ────────────────────────────────────────────────────────────────
# iftex_engine_guard_neutralize (55-prim order 47): doc 伴船 sty/tex
# 内 \\Require<X>TeX iftex 引擎守卫 → xelatex \\read Emergency stop
# (soak-2026-09-18 aaai2027.sty:59 ×15, unfixable:emergency)。
# ────────────────────────────────────────────────────────────────


_guard_rule, _guard_apply, _guard_cond = _lane("iftex_engine_guard_neutralize", None)


def test_iftexguard_rule_registered() -> None:
    rule = _guard_rule()
    assert rule.order == 47  # noqa: PLR2004 - 致死签先拆，opt_strip(48) 前
    assert rule.action["kind"] == "regex_rewrite"


def test_iftexguard_cond_passes_aaai_sty(tmp_path: Path) -> None:
    """aaai2027.sty 形：\\RequirePDFTeX 在 .sty → 闸放行。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    (tmp_path / "aaai2027.sty").write_text("\\RequirePackage{iftex}\n\\RequirePDFTeX\n")
    ok, why = _guard_cond(tmp_path)
    assert ok, why


def test_iftexguard_cond_passes_tex_site(tmp_path: Path) -> None:
    """主文件内 \\RequireLuaTeX 变体同放行 (族级词形)。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n\\RequireLuaTeX\n")
    ok, why = _guard_cond(tmp_path)
    assert ok, why


def test_iftexguard_cond_declines_no_guard(tmp_path: Path) -> None:
    """无 \\Require<X>TeX 词形 → 闸拒。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{iftex}\n"
    )
    ok, _ = _guard_cond(tmp_path)
    assert not ok


def test_iftexguard_apply_neutralizes_pdftex(tmp_path: Path) -> None:
    """主案：\\RequirePDFTeX → \\relax, 上下文行原样。"""
    (tmp_path / "aaai2027.sty").write_text(
        "\\RequirePackage{iftex}\n\\RequirePDFTeX\n\\RequirePackage{newtxtext}\n"
    )
    ok, note = _guard_apply(tmp_path)
    assert ok, note
    t = (tmp_path / "aaai2027.sty").read_text()
    assert "\\relax" in t
    assert "\\RequirePDFTeX" not in t
    assert "\\RequirePackage{iftex}" in t
    assert "\\RequirePackage{newtxtext}" in t


def test_iftexguard_apply_family_members(tmp_path: Path) -> None:
    """族级：LuaTeX/pTeX/VTeX 守卫同中和 (xelatex 下全拉闸)。"""
    guards = ("LuaTeX", "pTeX", "VTeX")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n" + "".join(f"\\Require{g}\n" for g in guards)
    )
    ok, _ = _guard_apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    for g in guards:
        assert f"Require{g}" not in t
    assert t.count("\\relax") == len(guards)


def test_iftexguard_apply_passing_guard_same_semantics(tmp_path: Path) -> None:
    """\\RequireXeTeX/\\RequireTUTeX (xelatex 下本通过) 换 \\relax 语义恒等。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n\\RequireXeTeX\n")
    ok, _ = _guard_apply(tmp_path)
    assert ok
    assert "\\relax" in (tmp_path / "main.tex").read_text()


def test_iftexguard_apply_comment_only_declines(tmp_path: Path) -> None:
    """masked 面：仅注释内 \\RequirePDFTeX → applied=False。"""
    src = "\\documentclass{article}\n%\\RequirePDFTeX\n"
    (tmp_path / "main.tex").write_text(src)
    ok, _ = _guard_apply(tmp_path)
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_iftexguard_apply_inline_midline(tmp_path: Path) -> None:
    """行中嵌：\\A\\RequirePDFTeX\\B → \\relax 不伤邻 token。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\RequirePackage{iftex}\\RequirePDFTeX\\relax\n"
    )
    ok, _ = _guard_apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\RequirePackage{iftex}\\relax\\relax" in t


def test_iftexguard_apply_skips_def_target_sites(tmp_path: Path) -> None:
    """def-target 位豁免：\\def\\RequirePDFTeX 不换 —— 置换会成 \\def\\relax 灾。"""
    (tmp_path / "aaai2027.sty").write_text(
        "\\RequirePackage{iftex}\n"
        "\\def\\RequirePDFTeX{\\errmessage{need pdftex}\\endinput}\n"
        "\\newcommand{\\RequireLuaTeX}{\\errmessage{need luatex}}\n"
        "\\let\\RequireVTeX\\relax\n"
    )
    ok, note = _guard_apply(tmp_path)
    assert not ok, note
    t = (tmp_path / "aaai2027.sty").read_text()
    assert "\\def\\RequirePDFTeX{" in t
    assert "\\newcommand{\\RequireLuaTeX}" in t
    assert "\\let\\RequireVTeX\\relax" in t


def test_iftexguard_apply_def_body_use_site_neutralized(tmp_path: Path) -> None:
    """def 体内裹站仍是 use 站：\\def\\myguard{\\RequirePDFTeX} → \\relax。"""
    (tmp_path / "aaai2027.sty").write_text(
        "\\RequirePackage{iftex}\n\\def\\myguard{\\RequirePDFTeX}\n"
    )
    ok, note = _guard_apply(tmp_path)
    assert ok, note
    t = (tmp_path / "aaai2027.sty").read_text()
    assert "\\def\\myguard{\\relax}" in t
    assert "\\RequirePDFTeX" not in t


def test_iftexguard_apply_non_tex_suffix_family(tmp_path: Path) -> None:
    """非 TeX 尾闸名：pTeXng/HINT/Prote 同中和。"""
    guards = ("pTeXng", "HINT", "Prote")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n" + "".join(f"\\Require{g}\n" for g in guards)
    )
    ok, _ = _guard_apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    for g in guards:
        assert f"Require{g}" not in t
    assert t.count("\\relax") == len(guards)
