"""fontspec_kernel_shadow_retire 内建 —— 稿自带 fontspec 套件内核 skew 退役。

实证根因 (scale50 批, 2026-09-25, t_c32920e49e7f1f70 / DQI-Kit):
稿自带 fontspec v2.9h (2026/08/11) 套件喂 LaTeX2e 2021-11-15 核 →
``\\SetKeys``/``__fontspec`` 原语 undefined 连锁爆, fontspec 初始化全灭
→ CJK 字体永不配 → zh.pdf 文本层 U+FFFF 死层 (exit 0 + status=ok 假绿)。
``vendored_shadow_isolate`` 的 ld<sd 只收旧向遮蔽, 新向 skew 是盲区;
fontspec 是内核耦合件, 双向跨版本 vendor 均无安全面 → 签名复核 +
系统/bundle 递补自证后整族 ``.fixloop-iso`` 退役。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins.vendored import (
    fontspec_kernel_shadow_retire,
)
from texlate.compile.fixloop.engine import LoopCtx

_SKEW = "! Undefined control sequence.\nl.45 \\SetKeys[fontspec]{fontsize=11pt}\n"
_SUITE = (
    "fontspec.sty",
    "fontspec-xetex.sty",
    "fontspec.cfg",
    "fontspec.lua",
)


class _FakeEng:
    """probe_file 命中系统副本 / filemap 收编——双臂可配。"""

    def __init__(self, *, probe: str | None, filemap: list[str]) -> None:
        self._probe = probe
        self._filemap = filemap
        self.ctan_fetch = None

    def probe_file(self, name: str, cwd: Path | None = None) -> str | None:
        del name, cwd
        return self._probe

    def filemap(self, name: str) -> list[str]:
        del name
        return self._filemap


def _ctx(tmp_path: Path, *, err_head: str = "") -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", err_head=err_head
    )


def _seed(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{fontspec}\n", encoding="utf-8"
    )
    for name in _SUITE:
        (tmp_path / name).write_text(f"% vendored {name}\n", encoding="utf-8")


def test_retire_suite_on_skew_signature(tmp_path: Path) -> None:
    """签名在 err_head + 套件在盘 + 系统有递补 → 整族 .fixloop-iso。"""
    _seed(tmp_path)
    eng = _FakeEng(
        probe="/usr/share/texmf-dist/tex/latex/fontspec/fontspec.sty",
        filemap=[],
    )
    ok, note = fontspec_kernel_shadow_retire(
        _ctx(tmp_path, err_head=_SKEW), eng, None, {"suffix": ".fixloop-iso"}
    )
    assert ok
    assert "fontspec.sty" in note
    for name in _SUITE:
        assert not (tmp_path / name).exists()
        assert (tmp_path / f"{name}.fixloop-iso").is_file()


def test_signature_in_log_fallback(tmp_path: Path) -> None:
    """err_head 空 → ``_fixloop_log`` 全文兜底同收签名。"""
    _seed(tmp_path)
    (tmp_path / "main.log").write_text("preamble\n" * 50 + _SKEW, encoding="utf-8")
    eng = _FakeEng(probe="/x/fontspec.sty", filemap=[])
    ok, _ = fontspec_kernel_shadow_retire(
        _ctx(tmp_path), eng, None, {"suffix": ".fixloop-iso"}
    )
    assert ok


def test_tectonic_bundle_fallback(tmp_path: Path) -> None:
    """tectonic probe 恒 None → filemap/bundle 收录即递补自证。"""
    _seed(tmp_path)
    eng = _FakeEng(probe=None, filemap=["fontspec"])
    ok, _ = fontspec_kernel_shadow_retire(
        _ctx(tmp_path, err_head=_SKEW), eng, None, {"suffix": ".fixloop-iso"}
    )
    assert ok


def test_no_signature_safe(tmp_path: Path) -> None:
    """无关错文 → False 让位后续规则 (套件在盘也不动)。"""
    _seed(tmp_path)
    eng = _FakeEng(probe="/x/fontspec.sty", filemap=[])
    ok, note = fontspec_kernel_shadow_retire(
        _ctx(tmp_path, err_head="! Undefined control sequence.\nl.7 \\oops\n"),
        eng,
        None,
        {"suffix": ".fixloop-iso"},
    )
    assert not ok
    assert "no fontspec kernel-skew" in note
    assert (tmp_path / "fontspec.sty").is_file()


def test_no_replacement_safe(tmp_path: Path) -> None:
    """签名在但系统/bundle 双无递补 → 不退 (退即造 missing_file)。"""
    _seed(tmp_path)
    eng = _FakeEng(probe=None, filemap=[])
    ok, note = fontspec_kernel_shadow_retire(
        _ctx(tmp_path, err_head=_SKEW), eng, None, {"suffix": ".fixloop-iso"}
    )
    assert not ok
    assert "递补" in note
    assert (tmp_path / "fontspec.sty").is_file()


def test_signature_no_suite_safe(tmp_path: Path) -> None:
    """签名在但 wdir 无 fontspec 件 (系统 fontspec 自身炸) → False。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    eng = _FakeEng(probe="/x/fontspec.sty", filemap=[])
    ok, note = fontspec_kernel_shadow_retire(
        _ctx(tmp_path, err_head=_SKEW), eng, None, {"suffix": ".fixloop-iso"}
    )
    assert not ok
    assert "无 fontspec 套件" in note


def test_registered() -> None:
    """注册进 TRANSFORM_FNS (rules/*.yaml function: 面)。"""
    assert builtins.TRANSFORM_FNS["fontspec_kernel_shadow_retire"] is (
        fontspec_kernel_shadow_retire
    )
