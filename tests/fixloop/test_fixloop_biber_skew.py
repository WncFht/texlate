"""biber_biblatex_skew_route 内建 —— tectonic bundle biblatex ↔ 系统 biber bcf 错配路由。

实证根因 (task t_c9249919e8d7a13f, 2026-09-18): tectonic 0.15 bundle 钉
biblatex 3.17 (bcf 3.8) 但外调 biber 走系统 PATH (2.22 要 bcf 3.11) ——
bundle 内无解，builtin 不改源只发 ``REJECT: route=xelatex`` 令牌，由
repair 跨引擎臂换编。签名复核两级：``err_head`` 快径 → ``_fixloop_log``
全文兜底（外部工具 stdout dump 在 log 内位置不钉死）。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins.bib import biber_biblatex_skew_route
from texlate.compile.fixloop.engine import LoopCtx

_SKEW = "Found biblatex control file version 3.8, expected version 3.11.\n"


def _ctx(tmp_path: Path, *, err_head: str = "") -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="tectonic", main_rel="main.tex", err_head=err_head
    )


def test_skew_in_err_head(tmp_path: Path) -> None:
    """签名在 err_head 快径命中 → True + ``REJECT: route=xelatex`` 令牌。"""
    ctx = _ctx(tmp_path, err_head=f"! the external tool exited\n{_SKEW}")
    ok, note = biber_biblatex_skew_route(ctx, None, None, {})
    assert ok
    assert "REJECT: route=xelatex" in note
    assert "3.8" in note
    assert "3.11" in note


def test_skew_in_log_fallback(tmp_path: Path) -> None:
    """err_head 未盖到（dump 超出 head 窗）→ ``_tect_out/{stem}.log`` 全文兜底同收。"""
    tect = tmp_path / "_tect_out"
    tect.mkdir()
    (tect / "main.log").write_text(
        "! the external tool exited with an error code; its stdout was:\n"
        + "filler\n" * 20
        + _SKEW,
        encoding="utf-8",
    )
    ok, note = biber_biblatex_skew_route(_ctx(tmp_path), None, None, {})
    assert ok
    assert "REJECT: route=xelatex" in note


def test_skew_bare_log_fallback(tmp_path: Path) -> None:
    """xelatex 形态 ``{stem}.log`` 亦收（兜底序列首位）。"""
    (tmp_path / "main.log").write_text(f"junk\n{_SKEW}", encoding="utf-8")
    ok, _note = biber_biblatex_skew_route(_ctx(tmp_path), None, None, {})
    assert ok


def test_no_signature_false(tmp_path: Path) -> None:
    """无签名 → False 让位后续 other 规则。"""
    (tmp_path / "main.log").write_text(
        "! Undefined control sequence.\nl.7 \\oops\n", encoding="utf-8"
    )
    ok, note = biber_biblatex_skew_route(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no biber/biblatex skew" in note


def test_custom_route_param(tmp_path: Path) -> None:
    """``params.route`` 覆盖默认 xelatex —— note 令牌跟随。"""
    ctx = _ctx(tmp_path, err_head=_SKEW)
    ok, note = biber_biblatex_skew_route(ctx, None, None, {"route": "dvips"})
    assert ok
    assert "REJECT: route=dvips" in note


def test_skew_rglob_arm_nested_log(tmp_path: Path) -> None:
    """stem 两候选均缺 → ``sorted(wdir.rglob("*.log"))`` 首非空兜底收签名。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "x.log").write_text(f"junk\n{_SKEW}", encoding="utf-8")
    ok, _note = biber_biblatex_skew_route(_ctx(tmp_path), None, None, {})
    assert ok


def test_skew_stale_main_log_shadows_tect_out(tmp_path: Path) -> None:
    """``{stem}.log`` 先于 ``_tect_out/{stem}.log`` —— 陈旧 main.log 遮罩
    新鲜 _tect_out 签名即拒（pin 现行候选优先级）。"""
    (tmp_path / "main.log").write_text("stale no-skew\n", encoding="utf-8")
    tect = tmp_path / "_tect_out"
    tect.mkdir()
    (tect / "main.log").write_text(f"dump\n{_SKEW}", encoding="utf-8")
    ok, note = biber_biblatex_skew_route(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no biber/biblatex skew" in note


def test_registered() -> None:
    """注册进 TRANSFORM_FNS (rules/*.yaml function: 面)。"""
    assert builtins.TRANSFORM_FNS["biber_biblatex_skew_route"] is (
        biber_biblatex_skew_route
    )
