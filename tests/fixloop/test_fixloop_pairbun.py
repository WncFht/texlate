"""pairbun lane pins — 2026-09-20 singtail mechanism-pair bundle.

Four arms:
  * ``float_opt_h_pkgload`` USAGE widened for ``\\def\\fps@<env>{...H}``
    cls-default spec (1107.0117 PoS.cls).
  * ``float_opt_cs_expand`` builtin: cs-valued float opt sites inlined to
    the literal spec resolved from ``\\def\\cs{spec}`` (0712.0315 cimento.cls).
  * ``graphics_kv_strip_obsolete`` REWRITE_FN: strip ``type=/ext=/read=``
    era graphicx keys (0812.0324/0812.0365).
  * ``find_vendored_shadows`` + ``_probe_tree`` neutral-cwd: probe no longer
    self-hits wdir files when process cwd lands inside wdir (0905.2435/
    0905.4369 seki era bundle).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from texlate.compile.engine._xelatex import XelatexEngine
from texlate.compile.fixloop.builtins import REWRITE_FNS, TRANSFORM_FNS
from texlate.compile.fixloop.builtins.vendored import find_vendored_shadows
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.fixloop.ruleset import Ruleset


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


_CIMENTO_CLS = r"""
\def\fps@table{tb}
\def\ftype@table{2}
\newenvironment{table}[1][\fps@table]{%
  \@float{table}[#1]\protect\small
}{\end@float}
\def\fps@figure{tbp}
"""

_DOC = "\\documentclass{x}\n\\begin{document}\n\\begin{table}x\\end{table}\n"


def test_float_opt_cs_expand_env_default(tmp_path: Path) -> None:
    """``\\newenvironment{env}[n][\\cs]`` default → literal spec (cimento 实证)."""
    (tmp_path / "cimento.cls").write_text(_CIMENTO_CLS)
    (tmp_path / "main.tex").write_text(_DOC)
    ctx = _ctx(tmp_path)
    ok, note = TRANSFORM_FNS["float_opt_cs_expand"](ctx, None, None, {})
    assert ok, note
    out = (tmp_path / "cimento.cls").read_text()
    assert "\\newenvironment{table}[1][tb]" in out
    assert "\\def\\fps@table{tb}" in out  # def 站不消


def test_float_opt_cs_expand_begin_site(tmp_path: Path) -> None:
    """``\\begin{env}[\\cs]`` 显式站位同样内联。"""
    (tmp_path / "main.tex").write_text(
        "\\def\\put@fig{!ht}\n\\begin{figure}[\\put@fig]x\\end{figure}\n"
    )
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["float_opt_cs_expand"](ctx, None, None, {})
    assert ok
    assert "\\begin{figure}[!ht]" in (tmp_path / "main.tex").read_text()


def test_float_opt_cs_expand_nonspec_rejected(tmp_path: Path) -> None:
    """spec 非 ``!htbpH`` 字符 → 保守不改 (非浮体 opt)。"""
    src = "\\def\\foo{zz9}\n\\begin{env}[\\foo]x\n"
    (tmp_path / "main.tex").write_text(src)
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["float_opt_cs_expand"](ctx, None, None, {})
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_float_opt_cs_expand_multidef_rejected(tmp_path: Path) -> None:
    """同名 cs 多定义 → 不可解 → 不动。"""
    src = "\\def\\fps@x{tb}\n\\def\\fps@x{H}\n\\newenvironment{e}[1][\\fps@x]{a}{b}\n"
    (tmp_path / "main.tex").write_text(src)
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["float_opt_cs_expand"](ctx, None, None, {})
    assert not ok
    assert (tmp_path / "main.tex").read_text() == src


def test_float_opt_cs_expand_undef_rejected(tmp_path: Path) -> None:
    """cs 无 def 可解 → 不动 (盲替换必死)。"""
    src = "\\newenvironment{e}[1][\\nosuchcs]{a}{b}\n"
    (tmp_path / "main.tex").write_text(src)
    ctx = _ctx(tmp_path)
    ok, _ = TRANSFORM_FNS["float_opt_cs_expand"](ctx, None, None, {})
    assert not ok


def test_graphics_kv_strip_obsolete_members() -> None:
    """成员级剥 type=/ext=/read=; subtype= 不沾; 剥空摘括号。"""
    fn = REWRITE_FNS["graphics_kv_strip_obsolete"]
    rx = re.compile(r"(\\includegraphics\*?)\s*\[([^\]\n]*)\]")
    m = rx.search(
        r"\includegraphics[type=pdf,ext=.pdf,read=.pdf,width=0.3\textwidth]{x}"
    )
    assert m
    assert fn(m) == r"\includegraphics[width=0.3\textwidth]"
    m = rx.search(r"\includegraphics*[type=eps]{y}")
    assert m
    assert fn(m) == r"\includegraphics*"
    m = rx.search(r"\includegraphics[width=1cm,subtype=z,breadth=2]{z}")
    assert m
    assert fn(m) == r"\includegraphics[width=1cm,subtype=z,breadth=2]"


_OLD_GFX = "\\ProvidesPackage{graphics}[2001/07/07 v1.0n]\n\\def\\x{}\n"
_NEW_GFX = "\\ProvidesPackage{graphics}[2024/08/06 v1.4g]\n\\def\\x{}\n"


class _CwdHonestEng:
    """probe_file 按真实引擎语义：``safe_is_file(cwd|Path.cwd()/fname)`` 直查
    先行，miss 再 texmf 树——cwd=wdir 时 vendored 自件即 self-hit。"""

    name = "xelatex"

    def __init__(self, texmf: Path) -> None:
        self.texmf = texmf

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        base = cwd if cwd is not None else Path.cwd()
        if (base / fname).is_file():
            return str(base / fname)
        p = self.texmf / fname
        return str(p) if p.is_file() else None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def test_find_vendored_shadows_inside_wdir_cwd(
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """进程 cwd 落 wdir 内仍检出遮蔽 (seki 15 era 件 self-hit 死面回归)。"""
    (tmp_path / "graphics.sty").write_text(_OLD_GFX)
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n")
    texmf = tmp_path_factory.mktemp("texmf")  # 须在 wdir 外——is_relative_to 闸
    (texmf / "graphics.sty").write_text(_NEW_GFX)
    eng = _CwdHonestEng(texmf)
    ctx = _ctx(tmp_path)
    monkeypatch.chdir(tmp_path)  # 复刻 fixloop worker 进程 cwd==wdir
    found = find_vendored_shadows(ctx, eng, (".sty", ".cls"))
    assert [f.name for f, *_ in found] == ["graphics.sty"]
    _, ld, sd, _prov = found[0]
    assert ld == (2001, 7, 7)
    assert sd == (2024, 8, 6)


@pytest.mark.skipif(not shutil.which("kpsewhich"), reason="kpsewhich unavailable")
def test_probe_tree_excludes_process_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真实引擎：``_probe_tree`` 的 kpsewhich ``.`` 元素不再毒化树解。"""
    (tmp_path / "graphics.sty").write_text(_OLD_GFX)
    monkeypatch.chdir(tmp_path)  # 进程 cwd==wdir (旧代码此处 self-hit)
    eng = XelatexEngine()
    hit = eng.probe_file("graphics.sty", cwd=Path("/"))
    assert hit is not None
    assert not Path(hit).resolve().is_relative_to(tmp_path)
    # memo 进树面纯件——非 wdir 径
    cached = next(iter(eng._probe_cache.values()), None)  # noqa: SLF001
    assert cached is None or not Path(cached).resolve().is_relative_to(tmp_path)


def test_float_opt_h_pkgload_fpsdef_usage() -> None:
    """``float_opt_h_pkgload`` USAGE 臂接 ``\\def\\fps@<env>{...H}`` 默认 spec。"""
    rule = next(r for r in Ruleset.load().rules if r.id == "float_opt_h_pkgload")
    sc = re.compile(rule.condition["source_contains"])
    pos = "\\documentclass{PoS}\n\\usepackage{x}\n\\def\\fps@figure{Htbp}\n"
    assert sc.search(pos)
    neg = pos.replace("{Htbp}", "{tbp}")
    assert not sc.search(neg)
    loaded = pos.replace("\\def\\fps@figure{Htbp}", "\\usepackage{float}\n")
    assert not sc.search(loaded)
