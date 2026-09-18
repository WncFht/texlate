"""wave-4 (cbucket-vendored-inventory + mn2e doc-only, 2026-09-17):

- ``vendored_fetch`` builtin: off-CTAN 缺件 basename 查 ``vendor/{files,stubs}``
  (files 真件优先于 stubs), payload 相对径落 wdir; ``..``/绝对/NUL 闸;
  未收 → decline 落 ``legacy_pkg_shim`` 兜底。规则位 order 11.5
  (install_file 之后、legacy_pkg_shim 之前)。
- ``XelatexEngine._relocate_doc_only``: mnras 类包把 ``mn2e.cls`` 归档进
  ``doc/latex/...`` 文档树 (TEXINPUTS 外), tlmgr 与 usertree overlay 落
  同一位 → basename 恰一命中搬进 ``tex/latex/`` 复核。
"""

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

from texlate.compile.engine import XelatexEngine
from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, _apply_scan_install


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO。"""
    return load_ruleset()


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


def _vendor(tmp_path: Path) -> Path:
    root = tmp_path / "vendor"
    (root / "files").mkdir(parents=True)
    (root / "stubs").mkdir(parents=True)
    return root


def _fetch(ctx: LoopCtx, payload: str, root: Path) -> tuple[bool, str]:
    return TRANSFORM_FNS["vendored_fetch"](ctx, None, payload, {"dir": str(root)})


# ------------------------------------------------------- 规则注册与排序


def test_vendored_fetch_rule_registered() -> None:
    rule = next(r for r in _rs().rules if r.id == "vendored_fetch")
    assert rule.order == 11.5  # noqa: PLR2004 - schema 断言值
    assert rule.when["category"] == "missing_file"
    assert rule.when["payload_required"] is True
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "vendored_fetch"


def test_vendored_fetch_sorts_between_install_and_shim() -> None:
    """loop 序: install_file(10) < vendored_fetch(11.5) < legacy_pkg_shim(12)。"""
    ids = [r.id for r in _rs().phase("loop")]
    assert ids.index("install_file") < ids.index("vendored_fetch")
    assert ids.index("vendored_fetch") < ids.index("legacy_pkg_shim")


# ------------------------------------------------------- vendored_fetch 本体


def test_vendored_fetch_files_tier(tmp_path: Path) -> None:
    """files/ 真件命中 → 平铺 wdir, note 标 [files]。"""
    root = _vendor(tmp_path)
    (root / "files" / "aastex.cls").write_text("% real aastex\n", encoding="utf-8")
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, note = _fetch(ctx, "aastex.cls", root)
    assert ok, note
    assert "vendored[files]" in note
    # 落盘件携指纹行头 (L10 注入件指纹闸) —— 本体在末位
    assert (ctx.wdir / "aastex.cls").read_text().endswith("% real aastex\n")


def test_vendored_fetch_stubs_fallback(tmp_path: Path) -> None:
    """files/ 无件 → stubs/ 递补, note 标 [stubs]。"""
    root = _vendor(tmp_path)
    (root / "stubs" / "slashbox.sty").write_text("% stub\n", encoding="utf-8")
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, note = _fetch(ctx, "slashbox.sty", root)
    assert ok, note
    assert "vendored[stubs]" in note
    assert (ctx.wdir / "slashbox.sty").is_file()


def test_vendored_fetch_files_precedence(tmp_path: Path) -> None:
    """同名件 files/ 优先于 stubs/ (真件 > stub)。"""
    root = _vendor(tmp_path)
    (root / "files" / "x.sty").write_text("real\n", encoding="utf-8")
    (root / "stubs" / "x.sty").write_text("stub\n", encoding="utf-8")
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, _ = _fetch(ctx, "x.sty", root)
    assert ok
    assert (ctx.wdir / "x.sty").read_text().endswith("real\n")


def test_vendored_fetch_preserves_payload_relpath(tmp_path: Path) -> None:
    """``\\input{sub/x}`` 期径: payload 相对径落 wdir/sub/x.sty。"""
    root = _vendor(tmp_path)
    (root / "files" / "x.sty").write_text("% x\n", encoding="utf-8")
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, _ = _fetch(ctx, "sub/x.sty", root)
    assert ok
    assert (ctx.wdir / "sub" / "x.sty").is_file()


def test_vendored_fetch_declines_unknown(tmp_path: Path) -> None:
    """未收件 → False decline (loop 继续落 legacy_pkg_shim)。"""
    root = _vendor(tmp_path)
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    ok, note = _fetch(ctx, "nonexistent.sty", root)
    assert not ok
    assert "not vendored" in note


def test_vendored_fetch_path_guards(tmp_path: Path) -> None:
    """.. 穿越 / 绝对径 / NUL / 空 payload 全拒。"""
    root = _vendor(tmp_path)
    (root / "files" / "x.sty").write_text("% x\n", encoding="utf-8")
    ctx = _ctx(tmp_path / "w")
    ctx.wdir.mkdir()
    for bad in ("../x.sty", "a/../../x.sty", "/etc/x.sty", "x\x00.sty", "", "  "):
        ok, note = _fetch(ctx, bad, root)
        assert not ok, bad
        assert "unsafe" in note or "not vendored" in note
    assert not (tmp_path / "x.sty").exists()  # 没泄出 wdir


# ------------------------------------------------------- _relocate_doc_only


def _eng_probe_hit() -> XelatexEngine:
    eng = XelatexEngine()
    eng.probe_file = lambda fname, *, cwd=None: f"/hit/{fname}"  # noqa: ARG005
    return eng


def test_relocate_doc_only_moves_unique_hit(tmp_path: Path) -> None:
    """mn2e 形: doc/latex/mnras/LEGACY/mn2e.cls → tex/latex/mn2e.cls。"""
    home = tmp_path / "texmf"
    legacy = home / "doc" / "latex" / "mnras" / "LEGACY"
    legacy.mkdir(parents=True)
    (legacy / "mn2e.cls").write_text("% mn2e\n", encoding="utf-8")
    eng = _eng_probe_hit()
    assert eng._relocate_doc_only("mn2e.cls", home)  # noqa: SLF001 - 白盒钉私有搬迁
    dest = home / "tex" / "latex" / "mn2e.cls"
    assert dest.read_text() == "% mn2e\n"
    assert (legacy / "mn2e.cls").is_file()  # 原件保留 (copy 非 move)


def test_relocate_doc_only_no_doc_tree(tmp_path: Path) -> None:
    home = tmp_path / "texmf"
    home.mkdir()
    eng = _eng_probe_hit()
    assert not eng._relocate_doc_only("mn2e.cls", home)  # noqa: SLF001 - 同上


def test_relocate_doc_only_ambiguous_declines(tmp_path: Path) -> None:
    """basename 多命中属歧义 —— 不猜, decline。"""
    home = tmp_path / "texmf"
    for sub in ("doc/latex/a", "doc/latex/b"):
        d = home / sub
        d.mkdir(parents=True)
        (d / "mn2e.cls").write_text("% copy\n", encoding="utf-8")
    eng = _eng_probe_hit()
    assert not eng._relocate_doc_only("mn2e.cls", home)  # noqa: SLF001 - 同上
    assert not (home / "tex" / "latex" / "mn2e.cls").exists()


def test_relocate_doc_only_probe_miss_reports_false(tmp_path: Path) -> None:
    """搬进 tex/latex 后 kpsewhich 仍 miss → False (复核是真值)。"""
    home = tmp_path / "texmf"
    d = home / "doc" / "latex" / "mnras"
    d.mkdir(parents=True)
    (d / "mn2e.cls").write_text("% mn2e\n", encoding="utf-8")
    eng = XelatexEngine()
    eng.probe_file = lambda fname, *, cwd=None: None  # noqa: ARG005
    assert not eng._relocate_doc_only("mn2e.cls", home)  # noqa: SLF001 - 同上
    assert (home / "tex" / "latex" / "mn2e.cls").is_file()  # 搬了但复核没过


# ------------------------------------------------------- scan_install vendored 兜底


class _EngNoInstall:
    """probe 全缺 / install 全败的最小引擎替身 (vendored 兜底才有得走)。"""

    name = "xelatex"

    def __init__(self) -> None:
        self.install_calls: list[str] = []

    def probe_file(self, fname: str, cwd: Path | None = None) -> None:  # noqa: ARG002
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:  # noqa: ARG002
        self.install_calls.append(fname)
        return False


def _scan_params(root: Path, **kw: object) -> dict:
    p = {
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
    p.update(kw)
    return p


def test_scan_install_vendored_fallback(tmp_path: Path) -> None:
    """static_precheck vendored 臂: install 全链败 → basename 查件落 wdir。

    round-0 预检落件不依赖 first-error 序位 (hep-ph/0104121 机制缝:
    doc-local fixes.sty 的 undefined_cs 抢在 missing_file 前)。
    """
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{eqsecnum}\n"
    )
    root = _vendor(tmp_path)
    (root / "stubs" / "eqsecnum.sty").write_text("\\ProvidesPackage{eqsecnum}\n")
    ctx, eng = _ctx(tmp_path), _EngNoInstall()
    ok, note = _apply_scan_install(ctx, eng, _scan_params(root))
    assert ok
    assert (tmp_path / "eqsecnum.sty").is_file()
    assert "eqsecnum.sty" in ctx.installed
    assert "vendored ['eqsecnum.sty']" in note


def test_scan_install_vendored_flag_off(tmp_path: Path) -> None:
    """params.vendored 缺省/False → 不落件, note 无 vendored 段。"""
    (tmp_path / "main.tex").write_text("\\usepackage{eqsecnum}\n")
    root = _vendor(tmp_path)
    (root / "stubs" / "eqsecnum.sty").write_text("x")
    ctx, eng = _ctx(tmp_path), _EngNoInstall()
    p = {k: v for k, v in _scan_params(root).items() if k != "vendored"}
    ok, note = _apply_scan_install(ctx, eng, p)
    assert ok
    assert not (tmp_path / "eqsecnum.sty").exists()
    assert "vendored" not in note


def test_scan_install_vendored_traversal_guard(tmp_path: Path) -> None:
    """扫出 ``../escape`` 构造名 → vendored 守卫拒落, 不泄出 wdir。"""
    (tmp_path / "main.tex").write_text("\\usepackage{../escape}\n")
    root = _vendor(tmp_path)
    (root / "stubs" / "escape.sty").write_text("x")
    ctx, eng = _ctx(tmp_path), _EngNoInstall()
    ok, _ = _apply_scan_install(ctx, eng, _scan_params(root))
    assert ok
    assert not (tmp_path.parent / "escape.sty").exists()
    assert "escape.sty" not in ctx.installed


def test_scan_install_vendored_dep_fanout(tmp_path: Path) -> None:
    """vendored 落件依赖闭包预装: 落件内 \\RequirePackage → install 种子。"""
    (tmp_path / "main.tex").write_text("\\usepackage{eqsecnum}\n")
    root = _vendor(tmp_path)
    (root / "stubs" / "eqsecnum.sty").write_text(
        "\\ProvidesPackage{eqsecnum}\n\\RequirePackage{auxdep}\n"
    )
    ctx, eng = _ctx(tmp_path), _EngNoInstall()
    ok, _ = _apply_scan_install(ctx, eng, _scan_params(root))
    assert ok
    assert "auxdep.sty" in eng.install_calls  # 落件依赖喂回装包链


# ------------------------------------------------------- diagrams stub 富化 (M1-B)


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_diagrams_stub_enriched_surface(tmp_path: Path) -> None:
    """stub 富化面真编译钉：options 吞掉 / &-\\-\\cr 分隔降级 / \\newarrow
    自定义族 / {diagram} 嵌 {equation} / plain 式 —— 全零 ``!`` 错。

    实证基线 1206.1835: 裸 stub 172 errs (misplaced &×88 + \\cr×22
    + unknown-option×2 + \\newarrow/\\xyoption undef + 域错级联)。
    """
    stub = (
        Path(__file__).resolve().parent.parent
        / "src/texlate/compile/fixloop/vendor/stubs/diagrams.sty"
    )
    shutil.copy(stub, tmp_path / "diagrams.sty")
    (tmp_path / "main.tex").write_text(
        r"""% !TeX program = xelatex
\documentclass{article}
\usepackage{amsmath}
\usepackage[PostScript=dvips,noPS]{diagrams}
\xyoption{all}
\newarrow{Equalto}{=}{=}{=}{=}{=}
\begin{document}
text
\begin{diagram}
A &\rTo^{f}& B \cr
\dTo_{g} && \dEqualto \cr
C &\rEqualto& D \cr
\end{diagram}
\begin{equation}\begin{diagram}
X &\rTo& Y \\ \dTo && \dTo \\ Z &\rTo& W
\end{diagram}\end{equation}
\diagram E &\rTo& F \cr G &\dTo& H \enddiagram
\end{document}
""",
        encoding="utf-8",
    )
    xelatex = shutil.which("xelatex")
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [xelatex, "-interaction=nonstopmode", "main.tex"],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    log = (tmp_path / "main.log").read_text(encoding="utf-8", errors="replace")
    n_err = len(re.findall(r"^! ", log, re.MULTILINE))
    assert n_err == 0, f"stub 富化后仍 {n_err} 个 '!' 错"
    assert (tmp_path / "main.pdf").is_file()
