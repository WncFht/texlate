"""sitehoist 落点口径单测: ``_resolve_site`` 单源化 + 残余 wdir-drop 位归位。

背景: 编译 cwd = ``main_path().parent`` 且无 TEXINPUTS 根注入 —— 凡往
"wdir 根" 平铺 stub/vendor/遮蔽件的落点, 对嵌套 main 稿
(``templates/arxiv/main.tex``) 不可见 (2609.19664 fired-unfixed 实证,
vendorcwd 车道盘点残余)。本文件钉:

- ``_resolve_site`` 落点 = ``main_dir/<rel>``; main 未知退 wdir 根
  (flat-main DECLINE 兜底); ``main_rel`` 怪径逃出 wdir → None;
- 各落点消费位 (``_scan_vendored`` / ``legacy_pkg_shim`` /
  ``svjour_clo_stub`` / ``bundled_class_shadow`` / ``generated_stub``)
  嵌套稿落 main_dir, 平铺稿仍落 wdir 根;
- dep 在场判同口径: 只在 wdir 根的 dep 对嵌套 main 不可见 → 不算
  在场 (假在场会跳过 install 链, 件永远缺);
- run_tool ``{main_dir}`` 占位 (``mnras_texmf_shadow_drop``): 嵌套稿
  解析位病件退役 + vendor 补丁件平铺都落 main_dir; 怪径退 ``.``。
"""

from pathlib import Path, PurePosixPath

from _fixloopkit import (
    EngStub,
    mk_ctx,
    mk_vendor,
    mnras_buggy_cls,
    rule,
    sh_runner,
)

from texlate.compile.fixloop import actions, builtins
from texlate.compile.fixloop.builtins import TRANSFORM_FNS, common, vendored
from texlate.compile.fixloop.builtins.common import _resolve_site
from texlate.compile.fixloop.engine import LoopCtx, _apply_scan_install
from texlate.compile.logparse import ErrReport


def _nested(wdir: Path) -> Path:
    """嵌套 main 布局: ``wdir/templates/arxiv/main.tex`` → 返回 main_dir。

    幂等: main.tex 已在 (调用方先写定制内容) 不覆写。
    """
    d = wdir / "templates" / "arxiv"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "main.tex"
    if not f.exists():
        f.write_text(
            "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
            encoding="utf-8",
        )
    return d


def _nested_ctx(wdir: Path) -> LoopCtx:
    _nested(wdir)
    return mk_ctx(wdir, "templates/arxiv/main.tex")


class _EngNoInstall(EngStub):
    """probe 全缺 / install 全败的最小引擎替身 (安装链才有得走)。"""

    def __init__(self) -> None:
        self.install_calls: list[str] = []

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:  # noqa: ARG002
        self.install_calls.append(fname)
        return False


# ---------------------------------------------------------------- _resolve_site 本体
def test_resolve_site_flat_lands_wdir(tmp_path: Path) -> None:
    """平铺 main: 解析位 = wdir 根。"""
    ctx = mk_ctx(tmp_path)
    assert _resolve_site(ctx, PurePosixPath("x.sty")) == tmp_path / "x.sty"


def test_resolve_site_nested_lands_main_dir(tmp_path: Path) -> None:
    """嵌套 main: 解析位 = main_dir。"""
    ctx = _nested_ctx(tmp_path)
    assert _resolve_site(ctx, PurePosixPath("x.sty")) == (
        tmp_path / "templates" / "arxiv" / "x.sty"
    )


def test_resolve_site_unknown_main_falls_back_wdir(tmp_path: Path) -> None:
    """main_rel 未定 → wdir 根 (flat-main DECLINE 兜底语义)。"""
    ctx = mk_ctx(tmp_path, None)
    assert _resolve_site(ctx, PurePosixPath("x.sty")) == tmp_path / "x.sty"


def test_resolve_site_escape_declines(tmp_path: Path) -> None:
    """main_rel 怪径逃出 wdir → None (不落件不炸)。"""
    ctx = mk_ctx(tmp_path, "../outside/main.tex")
    assert _resolve_site(ctx, PurePosixPath("x.sty")) is None


def test_resolve_site_single_source() -> None:
    """门面回引与 vendored 叶同指 builtins.common 单源。"""
    assert builtins._resolve_site is common._resolve_site  # noqa: SLF001
    assert vendored._resolve_site is common._resolve_site  # noqa: SLF001


# ---------------------------------------------------------------- _scan_vendored 落点
def _scan_params(root: Path) -> dict:
    return {
        "dir": str(root),
        "vendored": True,
        "scan_patterns": [
            {
                "regex": r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}",
                "split": ",",
                "suffix": ".sty",
            }
        ],
    }


def test_scan_vendored_nested_drops_main_dir(tmp_path: Path) -> None:
    """嵌套稿: vendored 兜底件落 main_dir, 不落 wdir 根。"""
    main_dir = _nested(tmp_path)
    (main_dir / "main.tex").write_text("\\usepackage{eqsecnum}\n", encoding="utf-8")
    root = mk_vendor(tmp_path)
    (root / "stubs" / "eqsecnum.sty").write_text("\\ProvidesPackage{eqsecnum}\n")
    ctx, eng = mk_ctx(tmp_path, "templates/arxiv/main.tex"), _EngNoInstall()
    ok, note = _apply_scan_install(ctx, eng, _scan_params(root))
    assert ok, note
    assert (main_dir / "eqsecnum.sty").is_file()
    assert not (tmp_path / "eqsecnum.sty").exists()


def test_scan_vendored_flat_drops_wdir(tmp_path: Path) -> None:
    """平铺稿回归: 落点仍 = wdir 根。"""
    (tmp_path / "main.tex").write_text("\\usepackage{eqsecnum}\n", encoding="utf-8")
    root = mk_vendor(tmp_path)
    (root / "stubs" / "eqsecnum.sty").write_text("x", encoding="utf-8")
    ctx, eng = mk_ctx(tmp_path), _EngNoInstall()
    ok, _ = _apply_scan_install(ctx, eng, _scan_params(root))
    assert ok
    assert (tmp_path / "eqsecnum.sty").is_file()


# ---------------------------------------------------------------- legacy_pkg_shim
_SHIM_PARAMS = {
    "shim_map": {"aastex.cls": {"loads": "emulateapj", "needs": ["revtex4-1.cls"]}}
}


def test_legacy_pkg_shim_nested_lands_main_dir(tmp_path: Path) -> None:
    """嵌套稿: stub 落 main_dir; 解析位已有 dep → 不走 install 链。"""
    main_dir = _nested(tmp_path)
    (main_dir / "revtex4-1.cls").write_text("% real\n", encoding="utf-8")
    ctx, eng = _nested_ctx(tmp_path), _EngNoInstall()
    ok, note = TRANSFORM_FNS["legacy_pkg_shim"](ctx, eng, "aastex.cls", _SHIM_PARAMS)
    assert ok, note
    assert (main_dir / "aastex.cls").is_file()
    assert not (tmp_path / "aastex.cls").exists()
    assert eng.install_calls == []


def test_legacy_pkg_shim_wdir_dep_invisible_nested(tmp_path: Path) -> None:
    """dep 只在 wdir 根 → 嵌套稿不可见 → 不算在场, 回 install 链。"""
    _nested(tmp_path)
    (tmp_path / "revtex4-1.cls").write_text("% real\n", encoding="utf-8")
    ctx, eng = _nested_ctx(tmp_path), _EngNoInstall()
    ok, note = TRANSFORM_FNS["legacy_pkg_shim"](ctx, eng, "aastex.cls", _SHIM_PARAMS)
    assert ok, note
    assert eng.install_calls == ["revtex4-1.cls"]
    assert "deps still missing" in note


def test_legacy_pkg_shim_flat_dep_present_skips_install(tmp_path: Path) -> None:
    """平铺稿回归: dep 在 wdir 根 = 解析位在场 → 不走 install 链。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    (tmp_path / "revtex4-1.cls").write_text("% real\n", encoding="utf-8")
    ctx, eng = mk_ctx(tmp_path), _EngNoInstall()
    ok, _ = TRANSFORM_FNS["legacy_pkg_shim"](ctx, eng, "aastex.cls", _SHIM_PARAMS)
    assert ok
    assert eng.install_calls == []
    assert (tmp_path / "aastex.cls").is_file()


# ---------------------------------------------------------------- svjour_clo_stub
def test_svjour_clo_stub_nested_lands_main_dir(tmp_path: Path) -> None:
    """嵌套稿: ``sv<opt>.clo`` noop stub 落 main_dir。"""
    main_dir = _nested(tmp_path)
    (main_dir / "main.tex").write_text(
        "\\documentclass[smallextended]{svjour}\n", encoding="utf-8"
    )
    ctx = _nested_ctx(tmp_path)
    ok, note = TRANSFORM_FNS["svjour_clo_stub"](ctx, None, None, {})
    assert ok, note
    assert (main_dir / "svsmallextended.clo").is_file()
    assert not (tmp_path / "svsmallextended.clo").exists()


def test_svjour_clo_stub_flat_lands_wdir(tmp_path: Path) -> None:
    """平铺稿回归: ``sv<opt>.clo`` 落 wdir 根。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass[smallextended]{svjour}\n", encoding="utf-8"
    )
    ctx = mk_ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["svjour_clo_stub"](ctx, None, None, {})
    assert ok
    assert (tmp_path / "svsmallextended.clo").is_file()


# ---------------------------------------------------------------- bundled_class_shadow
_SHADOW_PARAMS = {
    "cs_set": ["actaa"],
    "target": "aastex.cls",
    "body": "% shadow stub\n",
    "needs": ["emulateapj.cls"],
}


def test_bundled_class_shadow_nested_lands_main_dir(tmp_path: Path) -> None:
    """嵌套稿: 遮蔽 stub 落 main_dir; wdir 无 dep → 依赖回 install 链。"""
    main_dir = _nested(tmp_path)
    ctx, eng = _nested_ctx(tmp_path), _EngNoInstall()
    ok, note = TRANSFORM_FNS["bundled_class_shadow"](
        ctx, eng, "\\actaa", _SHADOW_PARAMS
    )
    assert ok, note
    assert (main_dir / "aastex.cls").is_file()
    assert not (tmp_path / "aastex.cls").exists()
    assert eng.install_calls == ["emulateapj.cls"]


def test_bundled_class_shadow_wdir_dep_invisible_nested(tmp_path: Path) -> None:
    """dep 只埋 wdir 根: 嵌套稿下不算在场 (与 legacy_pkg_shim 同口径)。"""
    _nested(tmp_path)
    (tmp_path / "emulateapj.cls").write_text("% real\n", encoding="utf-8")
    ctx, eng = _nested_ctx(tmp_path), _EngNoInstall()
    ok, _ = TRANSFORM_FNS["bundled_class_shadow"](ctx, eng, "\\actaa", _SHADOW_PARAMS)
    assert ok
    assert eng.install_calls == ["emulateapj.cls"]


# ---------------------------------------------------------------- generated_stub
def test_generated_stub_nested_lands_main_dir(tmp_path: Path) -> None:
    """嵌套稿: 覆盖层占位 stub 落 main_dir。"""
    main_dir = _nested(tmp_path)
    ctx = _nested_ctx(tmp_path)
    ok, note = TRANSFORM_FNS["generated_stub"](ctx, None, "fig.pstex_t", {})
    assert ok, note
    assert (main_dir / "fig.pstex_t").is_file()
    assert not (tmp_path / "fig.pstex_t").exists()


def test_generated_stub_escapes_wdir_declines(tmp_path: Path) -> None:
    """main_rel 怪径逃出 wdir → DECLINE (不落件不炸, 交后续规则)。"""
    ctx = mk_ctx(tmp_path, "../outside/main.tex")
    ok, note = TRANSFORM_FNS["generated_stub"](ctx, None, "fig.pstex_t", {})
    assert not ok
    assert "escapes wdir" in note


# ---------------------------------------------------------------- {main_dir} 占位
def test_substitute_main_dir_nested(tmp_path: Path) -> None:
    """嵌套稿: ``{main_dir}`` → main_dir 相对 wdir 的 posix 径。"""
    ctx = _nested_ctx(tmp_path)
    out = actions._substitute('md="{main_dir}"', None, ctx)  # noqa: SLF001
    assert out == 'md="templates/arxiv"'


def test_substitute_main_dir_fallbacks(tmp_path: Path) -> None:
    """平铺/main 未知/怪径逃出/无 ctx → ``.`` (wdir 根兜底, DECLINE 口径)。"""
    assert actions._substitute("{main_dir}", None, mk_ctx(tmp_path)) == "."  # noqa: SLF001
    assert actions._substitute("{main_dir}", None, mk_ctx(tmp_path, None)) == "."  # noqa: SLF001
    assert actions._substitute("{main_dir}", None, mk_ctx(tmp_path, "../x.tex")) == "."  # noqa: SLF001
    assert actions._substitute("{main_dir}", None, None) == "."  # noqa: SLF001


def test_substitute_payload_unchanged(tmp_path: Path) -> None:
    """``{payload}`` 语义不变; ``{main_dir}`` 与 ``{payload}`` 可同串共存。"""
    ctx = _nested_ctx(tmp_path)
    out = actions._substitute("{payload}@{main_dir}", "x.sty", ctx)  # noqa: SLF001
    assert out == "x.sty@templates/arxiv"


# ---------------------------------------------------------------- mnras run_tool 臂
_MNRAS_RULE_ID = "mnras_texmf_shadow_drop"


def test_mnras_drop_nested_lands_main_dir(tmp_path: Path) -> None:
    """``{main_dir}`` 占位: 嵌套稿解析位病件退役 + vendor 补丁件同位递补。"""
    main_dir = _nested(tmp_path)
    (main_dir / "mnras.cls").write_text(mnras_buggy_cls(), encoding="utf-8")
    ctx = LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel="templates/arxiv/main.tex",
        runner=sh_runner,
    )
    ok, note = actions._apply(  # noqa: SLF001 - 直驱动作臂白盒钉
        rule(_MNRAS_RULE_ID), ctx, None, None, ErrReport()
    )
    assert ok, note
    assert (main_dir / "mnras.cls.fixloop-iso").read_text(
        encoding="utf-8"
    ) == mnras_buggy_cls()
    dropped = (main_dir / "mnras.cls").read_text(encoding="utf-8")
    assert "texlate patch" in dropped
    assert not (tmp_path / "mnras.cls").exists()


def test_mnras_drop_flat_lands_wdir(tmp_path: Path) -> None:
    """平铺稿回归: ``md='.'`` → 退役+平铺仍落 wdir 根。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    (tmp_path / "mnras.cls").write_text(mnras_buggy_cls(), encoding="utf-8")
    ctx = LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=sh_runner
    )
    ok, note = actions._apply(  # noqa: SLF001 - 同上
        rule(_MNRAS_RULE_ID), ctx, None, None, ErrReport()
    )
    assert ok, note
    assert (tmp_path / "mnras.cls.fixloop-iso").read_text(
        encoding="utf-8"
    ) == mnras_buggy_cls()
    assert "texlate patch" in (tmp_path / "mnras.cls").read_text(encoding="utf-8")
