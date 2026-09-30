r"""pst 车道 (2026-09-19): pstricks 族两缺陷——wrapper+core 一体件与 pstcol noxcolor。

- ``vendored_shadow_isolate`` 同名 .tex 核伴船退役 (defect-A): X.sty 确证
  更旧退役后, 同目录稿自带 X.tex (wrapper ``\input{X}`` 的 core) 若系统
  有现行副本且双侧日期面确证更旧 → 一并 ``.fixloop-iso``。0707.4206 实
  证: vendored pstricks.tex v1.15/2006 留盘配系统 pstricks.sty v0.75 →
  ``\pst@cntm`` undefined。保守闸: 系统无递补 / 日期面无证 / 本引擎注
  入件 / probe 命中 wdir 内 —— 缺一不碰。
- ``_provides_date`` ``\def\filedate{YYYY/MM/DD}`` 兜底 (pst-* 核日期面
  约定, pstricks.tex v1.15 实证)。
- ``pstcol_pstricks_rewrite`` 规则 (defect-B): pstcol.sty 体内
  ``\PassOptionsToPackage{noxcolor}{pstricks}`` 硬压 color 路径 → 现代
  pst-* 核 (pstricks-add.tex ``\colorlet``) 必炸 → usepackage 组内
  pstcol 枚名换 pstricks (xcolor 自动续载, 选项续传)。1003.2152 实证。
"""

from pathlib import Path

from _fixloopkit import ShadowEng, proj_texmf

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop.builtins import (
    _provides_date,
    vendored_shadow_isolate,
)
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


_OLD_STY = "\\ProvidesPackage{pstricks}[2006/08/10 v0.32 old wrapper]\n"
_NEW_STY = "\\ProvidesPackage{pstricks}[2024/02/02 v0.75 new wrapper]\n"
_OLD_CORE = "\\def\\fileversion{1.15}\n\\def\\filedate{2006/12/22}\n"
_NEW_CORE = "\\def\\fileversion{3.22A}\n\\def\\filedate{2025/12/13}\n"


def _isolate_params() -> dict:
    return {"exts": (".sty", ".cls"), "suffix": ".fixloop-iso"}


# ------------------------------------------------------- _provides_date filedate 兜底


def test_provides_date_filedate_fallback() -> None:
    """pst-* 核约定：无 \\ProvidesX 时 ``\\def\\filedate`` 取日期面。"""
    assert _provides_date(_OLD_CORE) == (2006, 12, 22)
    assert _provides_date(_NEW_CORE) == (2025, 12, 13)


def test_provides_date_literal_wins_over_filedate() -> None:
    """\\ProvidesPackage 字面日期优先，filedate 只兜底不抢先。"""
    t = _NEW_STY + _OLD_CORE
    assert _provides_date(t) == (2024, 2, 2)


def test_provides_date_no_face_still_none() -> None:
    assert _provides_date("\\def\\fileversion{1.15}\n") is None


# ------------------------------------------------------- paired .tex 核伴船退役


def test_paired_tex_core_retired_with_wrapper(tmp_path: Path) -> None:
    """0707.4206 形：旧 sty+ 旧 tex 同退役 —— wrapper/core 一体不混栈。"""
    wdir, texmf = proj_texmf(tmp_path)
    (texmf / "pstricks.sty").write_text(_NEW_STY, encoding="utf-8")
    (texmf / "pstricks.tex").write_text(_NEW_CORE, encoding="utf-8")
    (wdir / "pstricks.sty").write_text(_OLD_STY, encoding="utf-8")
    (wdir / "pstricks.tex").write_text(_OLD_CORE, encoding="utf-8")
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), ShadowEng(texmf), None, _isolate_params()
    )
    assert ok, note
    assert (wdir / "pstricks.sty.fixloop-iso").is_file()
    assert (wdir / "pstricks.tex.fixloop-iso").is_file()
    assert "paired core" in note


def test_paired_core_no_system_replacement_stays(tmp_path: Path) -> None:
    """系统无 .tex 核可递补 → rename 即造 missing_file, 保守保留。"""
    wdir, texmf = proj_texmf(tmp_path)
    (texmf / "pstricks.sty").write_text(_NEW_STY, encoding="utf-8")
    (wdir / "pstricks.sty").write_text(_OLD_STY, encoding="utf-8")
    (wdir / "pstricks.tex").write_text(_OLD_CORE, encoding="utf-8")
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), ShadowEng(texmf), None, _isolate_params()
    )
    assert ok, note
    assert (wdir / "pstricks.sty.fixloop-iso").is_file()
    assert (wdir / "pstricks.tex").is_file()  # 核留盘
    assert "paired core" not in note


def test_paired_core_probe_inside_wdir_not_shadow(tmp_path: Path) -> None:
    """probe 命中 wdir 内副本 (kpsewhich cwd 毒化) → 非遮蔽证据，保留。"""
    wdir, texmf = proj_texmf(tmp_path)
    (texmf / "pstricks.sty").write_text(_NEW_STY, encoding="utf-8")
    (wdir / "pstricks.sty").write_text(_OLD_STY, encoding="utf-8")
    (wdir / "pstricks.tex").write_text(_OLD_CORE, encoding="utf-8")
    eng = ShadowEng(texmf, extra={"pstricks.tex": wdir / "pstricks.tex"})
    ok, note = vendored_shadow_isolate(_ctx(wdir), eng, None, _isolate_params())
    assert ok, note
    assert (wdir / "pstricks.tex").is_file()


def test_paired_core_no_date_face_stays(tmp_path: Path) -> None:
    """vendored 核无日期面 → 新旧无证，盲删必死，保留。"""
    wdir, texmf = proj_texmf(tmp_path)
    (texmf / "pstricks.sty").write_text(_NEW_STY, encoding="utf-8")
    (texmf / "pstricks.tex").write_text(_NEW_CORE, encoding="utf-8")
    (wdir / "pstricks.sty").write_text(_OLD_STY, encoding="utf-8")
    (wdir / "pstricks.tex").write_text(
        "% hand-rolled core, no date\n", encoding="utf-8"
    )
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), ShadowEng(texmf), None, _isolate_params()
    )
    assert ok, note
    assert (wdir / "pstricks.tex").is_file()
    assert "paired core" not in note


def test_paired_core_vendored_newer_stays(tmp_path: Path) -> None:
    """vendored 核比系统新 (奇异混栈) → 不降级，保留。"""
    wdir, texmf = proj_texmf(tmp_path)
    (texmf / "pstricks.sty").write_text(_NEW_STY, encoding="utf-8")
    (texmf / "pstricks.tex").write_text(_OLD_CORE, encoding="utf-8")
    (wdir / "pstricks.sty").write_text(_OLD_STY, encoding="utf-8")
    (wdir / "pstricks.tex").write_text(_NEW_CORE, encoding="utf-8")
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), ShadowEng(texmf), None, _isolate_params()
    )
    assert ok, note
    assert (wdir / "pstricks.tex").is_file()
    assert "paired core" not in note


def test_paired_core_injected_file_stays(tmp_path: Path) -> None:
    """同名核是本引擎注入件 (指纹认亲) → 退役即自拆台，保留。"""
    wdir, texmf = proj_texmf(tmp_path)
    (texmf / "pstricks.sty").write_text(_NEW_STY, encoding="utf-8")
    (texmf / "pstricks.tex").write_text(_NEW_CORE, encoding="utf-8")
    (wdir / "pstricks.sty").write_text(_OLD_STY, encoding="utf-8")
    (wdir / "pstricks.tex").write_text(
        "% texlate-fixloop-injected: 0123abcdef45\n" + _OLD_CORE, encoding="utf-8"
    )
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), ShadowEng(texmf), None, _isolate_params()
    )
    assert ok, note
    assert (wdir / "pstricks.tex").is_file()
    assert "paired core" not in note


def test_paired_core_absent_clean(tmp_path: Path) -> None:
    """无同名核 → 正常退役 wrapper, note 无 paired 段。"""
    wdir, texmf = proj_texmf(tmp_path)
    (texmf / "pstricks.sty").write_text(_NEW_STY, encoding="utf-8")
    (wdir / "pstricks.sty").write_text(_OLD_STY, encoding="utf-8")
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), ShadowEng(texmf), None, _isolate_params()
    )
    assert ok, note
    assert "paired core" not in note


# ------------------------------------------------------- pstcol_pstricks_rewrite 规则


def _pstcol_rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "pstcol_pstricks_rewrite")


def test_pstcol_rule_registered() -> None:
    rule = _pstcol_rule()
    assert rule.order == 185  # noqa: PLR2004 - schema 断言值
    assert rule.action["kind"] == "regex_rewrite"
    assert "pstcol" in rule.condition["source_contains"]


def _apply_pstcol(tmp_path: Path) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _pstcol_rule(),
        LoopCtx(wdir=tmp_path, engine_name="xelatex"),
        ShadowEng(tmp_path / "texmf"),
        None,
        ErrReport(),
    )


def test_pstcol_rewrite_group_forms(tmp_path: Path) -> None:
    """1003.2152 形：组内枚名换 pstricks; 选项/混排/RequirePackage 全覆盖。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage{pstcol,pst-plot,pst-3d}\n"
        "\\usepackage[usenames]{pstcol}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg.sty").write_text(
        "\\RequirePackage{ pstcol ,x}\n", encoding="utf-8"
    )
    ok, note = _apply_pstcol(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{pstricks,pst-plot,pst-3d}" in t
    assert "\\usepackage[usenames]{pstricks}" in t
    assert "\\RequirePackage{ pstricks ,x}" in (tmp_path / "pkg.sty").read_text()


def test_pstcol_rewrite_masked_comment_untouched(tmp_path: Path) -> None:
    """masked 面：注释内假装载不改写 (match_surface: masked opt-in)。"""
    (tmp_path / "main.tex").write_text(
        "% \\usepackage{pstcol}\n\\usepackage{pstcol}\n", encoding="utf-8"
    )
    ok, _ = _apply_pstcol(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert t == "% \\usepackage{pstcol}\n\\usepackage{pstricks}\n"


def test_pstcol_rewrite_no_false_token(tmp_path: Path) -> None:
    """x-pstcol / pstcol2 非 pstcol 枚名 —— 不动。"""
    (tmp_path / "main.tex").write_text(
        "\\usepackage{x-pstcol}\n\\usepackage{pstcol2}\n", encoding="utf-8"
    )
    ok, _ = _apply_pstcol(tmp_path)
    assert not ok  # 零命中 → False (rewrite in 0 files)
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{x-pstcol}" in t
    assert "\\usepackage{pstcol2}" in t
