r"""xbbpregen lane (2026-09-19): ``xbb_pregen`` extractbb .xbb 缓存预生成规则。

2105.00151 (IEICE 模板 ``\usepackage[dvipdfmx]{graphicx,xcolor}``) 形: doc
强指 dvipdfmx 驱动 → dvipdfmx.def ``\Gread@extractbb@aux`` 对 pdf/png 族
先 ``\openin <stem>.xbb``, miss 退 ``"|extractbb -O <file>"`` pipe →
沙箱 ``shell_escape=f`` 下 pipe 死 → ``Cannot run pipe command`` +
``<stem>.xbb (no BoundingBox)`` 每图一对 (13 图 26 错)。修复 = 全量
extractbb 可图形 ``extractbb -x`` 预生成 ``<stem>.xbb`` 旁文件 —— 缓存在
盘非空即被 TeX 直读, pipe 臂整体跳过 (本机 ``shell_escape=f`` xelatex
实测: .xbb 预生成后双错清零)。
"""

import os
import shutil
from pathlib import Path

import pytest

from texlate.compile.fixloop import actions, builtins, load_ruleset
from texlate.compile.fixloop.builtins import xbb_pregen
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.fixloop.logparse import ErrReport


class _Eng:
    """builtin_transform/condition 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


_PIPE_ERR = "LaTeX Error: Cannot run pipe command. Try --shell-escape"
_XBB_ERR = "LaTeX Error: Cannot determine size of graphic in fig1.xbb (no BoundingBox)."
_ERR_HEAD = _PIPE_ERR + "\n" + _XBB_ERR


def _ctx(
    tmp_path: Path, err_head: str = _ERR_HEAD, runner: object = None
) -> LoopCtx:
    ctx = LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=runner
    )
    ctx.err_head = err_head
    return ctx


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "xbb_pregen")


def _apply(tmp_path: Path, runner: object = None) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(tmp_path, runner=runner), _Eng(), None, ErrReport()
    )


def _cond(tmp_path: Path, err_head: str = _ERR_HEAD) -> tuple[bool, str]:
    rule = _rule()
    return actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), None
    )


def _which_extractbb(name: str) -> str | None:
    return "/usr/bin/extractbb" if name == "extractbb" else None


def _which_none(_name: str) -> None:
    return None


def _extractbb_ok(argv: list[str], _timeout: int, wdir: Path) -> tuple:
    """假 extractbb -x: ``<src 剥尾>.xbb`` 写伪 bbox, rc=0 (argv 是 wdir 相对径)。"""
    (wdir / argv[-1]).with_suffix(".xbb").write_text(
        "%%Title: t\n%%BoundingBox: 0 0 612 792\n", encoding="utf-8"
    )
    return 0, "", 0.05, False


def _extractbb_fail(argv: list[str], _timeout: int, wdir: Path) -> tuple:
    """假 extractbb 败形: 写真 extractbb 同款空 .xbb 毒件, rc=1。"""
    (wdir / argv[-1]).with_suffix(".xbb").write_bytes(b"")
    return 1, "reading image failed", 0.05, False


# ─────────────────────────── rule 注册 / 闸 ───────────────────────────


def test_xbbpregen_rule_registered() -> None:
    rule = _rule()
    assert rule.order == 15.5  # noqa: PLR2004 - schema 断言值
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "xbb_pregen"
    assert builtins.TRANSFORM_FNS["xbb_pregen"] is xbb_pregen


def test_xbbpregen_cond_fires_paired_sig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pipe + xbb 双签 err_head → 闸放行。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    ok, why = _cond(tmp_path)
    assert ok, why


def test_xbbpregen_cond_fires_pipe_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """仅 pipe 半签 (xbb 错在 err_head 8 行窗外) → 交替仍放行。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    ok, why = _cond(tmp_path, _PIPE_ERR)
    assert ok, why


def test_xbbpregen_cond_fires_xbb_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """仅 xbb 半签 (pipe 错未进 err_head) → 交替仍放行。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    ok, why = _cond(tmp_path, _XBB_ERR)
    assert ok, why


def test_xbbpregen_cond_declines_unrelated_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无关 other 类目错 → ctx_suggests 拒。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    ok, _why = _cond(tmp_path, "LaTeX Error: Something else entirely")
    assert not ok


def test_xbbpregen_cond_declines_no_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """extractbb 缺席 → tool_available 拒。"""
    monkeypatch.setattr(shutil, "which", _which_none)
    ok, why = _cond(tmp_path)
    assert not ok
    assert "extractbb" in why


# ─────────────────────────── builtin 行为 ───────────────────────────


def test_xbbpregen_generates_xbb_for_all_graphics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全量图形一轮齐转 (13 图场景): pdf/png/jpg 多扩展名多目录各出 .xbb。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    (tmp_path / "img").mkdir()
    for rel in ("fig1.pdf", "img/fig2.png", "img/FIG3.JPG"):
        (tmp_path / rel).write_bytes(b"%fake-graphic")
    (tmp_path / "main.tex").write_text("\\includegraphics{fig1.pdf}\n")
    (tmp_path / "notes.txt").write_text("not a graphic")  # 非图形面不扰
    ok, note = _apply(tmp_path, runner=_extractbb_ok)
    assert ok, note
    assert "3 new/3" in note
    for rel in ("fig1.xbb", "img/fig2.xbb", "img/FIG3.xbb"):
        assert (tmp_path / rel).is_file(), rel


def test_xbbpregen_idempotent_second_fire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """二次触火: .xbb 非空且不旧于源 → 全 fresh → False 让位。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    (tmp_path / "fig1.pdf").write_bytes(b"%fake")
    ctx = _ctx(tmp_path, runner=_extractbb_ok)
    ok1, _n1 = xbb_pregen(ctx, _Eng(), None, {})
    ok2, note2 = xbb_pregen(ctx, _Eng(), None, {})
    assert ok1
    assert not ok2
    assert "already fresh" in note2


def test_xbbpregen_regenerates_stale_xbb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """源图比 .xbb 新 → 重生成 (旧缓存不短路)。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    src = tmp_path / "fig1.pdf"
    src.write_bytes(b"%fake")
    xbb = tmp_path / "fig1.xbb"
    xbb.write_bytes(b"%%BoundingBox: 0 0 1 1\n")
    # 压 .xbb mtime 于源图之前 —— 旧缓存须重转
    old = src.stat().st_mtime - 10
    os.utime(xbb, (old, old))
    calls: list[list[str]] = []

    def _spy(argv: list[str], _t: int, _w: Path) -> tuple:
        calls.append(argv)
        return _extractbb_ok(argv, _t, _w)

    ok, note = _apply(tmp_path, runner=_spy)
    assert ok, note
    # argv 末位是 wdir 相对径 (openout_any=p 下绝对径被 extractbb 拒写)
    assert calls == [[_which_extractbb("extractbb"), "-x", "fig1.pdf"]]


def test_xbbpregen_failure_cleans_poison_xbb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """extractbb 败 → 空 .xbb 毒件清掉 (留它 ``\\ifeof`` 仍走 pipe), False 不谎报。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    (tmp_path / "fig1.pdf").write_bytes(b"%corrupt")
    ok, note = _apply(tmp_path, runner=_extractbb_fail)
    assert not ok
    assert "0 generated" in note
    assert not (tmp_path / "fig1.xbb").exists()


def test_xbbpregen_no_graphics_in_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """err_head stem 在盘无对应图形且工程零图形件 → False。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    (tmp_path / "main.tex").write_text("\\includegraphics{fig1.pdf}\n")
    ok, note = _apply(tmp_path, runner=_extractbb_ok)
    assert not ok
    assert "no extractbb-capable" in note


def test_xbbpregen_err_head_stem_resolves_graphic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """err_head 裸 stem 回映: ``fig1.xbb`` → ``fig1.pdf`` (扩展名枚举兜底)。"""
    monkeypatch.setattr(shutil, "which", _which_extractbb)
    # 扩展名不在 _XBB_EXTS 面外回映 —— stem 探件臂仍能补目标
    (tmp_path / "fig1.pdf").write_bytes(b"%fake")
    ok, note = _apply(tmp_path, runner=_extractbb_ok)
    assert ok, note
    assert (tmp_path / "fig1.xbb").is_file()


def test_xbbpregen_no_extractbb_builtin_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """builtin 直调 (绕闸): extractbb 缺席 → False (condition 之外再保险)。"""
    monkeypatch.setattr(shutil, "which", _which_none)
    (tmp_path / "fig1.pdf").write_bytes(b"%fake")
    ok, note = xbb_pregen(_ctx(tmp_path), _Eng(), None, {})
    assert not ok
    assert "no extractbb" in note


def test_xbbpregen_ruleset_loads() -> None:
    rs = load_ruleset()
    assert len(rs.rules) >= 114  # noqa: PLR2004 - 库规模断言
