r"""driverdef lane (2026-09-19): ``hyperref_driver_neutralize`` def 间接指派臂。

2403.00013 (kaist-ucs.cls) 形: cls 内部 ``\ifpdf``/``\if@dvips`` 条件选支
``\def\@drivername{pdftex|dvipdfmx|dvips}`` 后 ``\RequirePackage[\@drivername]
{graphicx,xcolor}`` —— 驱动词藏在 ``\def`` 值里, 选项括号面只见 cs 名,
旧闸 ``\[..\b(drv)\b..\]`` 够不着 → hyperref 炸 ``Wrong DVI mode driver
option `dvipdfmx'`` (fixloop 零命中, best_effort_pdf 52 错)。根修 = def 值
直接覆写 ``xetex`` (xelatex/tectonic 下无论哪支条件命中都须是 xetex),
与括号剥词臂语义一致 (xetex 家族下这些驱动本就走不通)。
"""

from pathlib import Path

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.fixloop.logparse import ErrReport


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


def _rule() -> Rule:
    return next(
        r for r in load_ruleset().rules if r.id == "hyperref_driver_neutralize"
    )


def _apply(tmp_path: Path) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(tmp_path), _Eng(), "dvipdfmx", ErrReport()
    )


def _cond(tmp_path: Path, err_head: str = _DRV_ERR) -> tuple[bool, str]:
    rule = _rule()
    return actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), "dvipdfmx"
    )


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
    """kaist-ucs 形: 括号面无驱动词, def 指派存在 → 闸放行。"""
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
    """括号字面驱动词旧路径回归: [dvipdfmx] 依旧放行。"""
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
    """非驱动值 def 不动: \\def\\@drivername{custom} 原样保留。"""
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
    """括号 + def 混合面一遍过: [dvips]→[], \\def\\@drivername{dvipdfmx}→xetex。"""
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
    """值域空白容忍: \\def\\@drivername{ dvipdfmx } → {xetex}。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\def\\@drivername  { dvipdfmx }\n"
    )
    ok, _ = _apply(tmp_path)
    assert ok
    assert "\\def\\@drivername  {xetex}" in (
        tmp_path / "main.tex"
    ).read_text()


def test_driverdef_ruleset_loads() -> None:
    rs = load_ruleset()
    assert len(rs.rules) >= 113  # noqa: PLR2004 - 库规模断言
