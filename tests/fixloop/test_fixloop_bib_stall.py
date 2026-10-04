"""tectonic_bib_stall_route 内建 —— tectonic bib 管线双盲区路由。

实证根因 (scale50 批，2026-09-25):

- **bibtex 挂死臂** (t_0c9a/2609.20470, t_dce88/2609.19713): tectonic 0.15
  内嵌 Rust bibtex 特定输入死循环——tex pass 出 xdv 后
  ``note: Running BibTeX on main.aux`` 即无输出烧满 240s 墙钟落
  ``timeout``; 系统 bibtex 同 .aux 秒过，病根只在 tectonic 内嵌件。
- **bbl 在席缺 .bib 臂** (t_a4ae/2510.22418): tectonic 不看 ``.bbl`` 在席，
  aux 有 citation 即跑 biber → ``! can't open path `references.bib'``
  落 ``other`` 硬毙; xelatex ``_bib_pass`` 文件态触发、bbl 在席跳过。

builtin 不改源只发 ``REJECT: route=xelatex`` 令牌，repair 跨引擎臂换编。
标记复核两级：``err_head`` 快径 → ``_fixloop_log`` 全文兜底 (挂死锚看
末 4KB 尾窗——kill 前末位管线 note 即死因位置)。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins.bib import tectonic_bib_stall_route
from texlate.compile.fixloop.engine import LoopCtx

_STALL_TAIL = (
    "Output written on main.xdv (25 pages, 460964 bytes).\n"
    "Transcript written on main.log.\n"
    "note: Running BibTeX on main.aux ...\n"
)
_BIB_OPEN = "! can't open path `references.bib'\ncaused by: not found\n"


def _ctx(tmp_path: Path, *, err_head: str = "") -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="tectonic", main_rel="main.tex", err_head=err_head
    )


def _write_log(tmp_path: Path, text: str) -> None:
    (tmp_path / "main.log").write_text(text, encoding="utf-8")


def test_stall_tail_in_log(tmp_path: Path) -> None:
    """挂死锚在 log 尾窗 → True + ``REJECT: route=xelatex`` 令牌。"""
    _write_log(tmp_path, "preamble\n" * 50 + _STALL_TAIL)
    ok, note = tectonic_bib_stall_route(_ctx(tmp_path), None, None, {})
    assert ok
    assert "REJECT: route=xelatex" in note
    assert "bibtex stall" in note


def test_stall_tail_in_err_head(tmp_path: Path) -> None:
    """err_head 快径同收挂死锚。"""
    ok, note = tectonic_bib_stall_route(
        _ctx(tmp_path, err_head=_STALL_TAIL), None, None, {}
    )
    assert ok
    assert "REJECT: route=xelatex" in note


def test_mid_log_bibtex_not_tail_is_safe(tmp_path: Path) -> None:
    """``Running BibTeX`` 之后还有产出行 → 非死因位置 → False。

    尾锚必须钉在 log 末——bibtex 跑完继续 xdvipdfmx 的健康编译其
    ``Running BibTeX`` 行后另有 note, 不误中。
    """
    healthy = (
        _STALL_TAIL
        + "note: Running xdvipdfmx ...\n"
        + "note: Writing `out/main.pdf` (1.2 MiB)\n"
    )
    _write_log(tmp_path, healthy)
    ok, note = tectonic_bib_stall_route(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no tectonic bib-stall" in note


def test_cant_open_bib_with_bbl(tmp_path: Path) -> None:
    """``can't open path .bib`` + wdir 有 .bbl → 路由令牌。"""
    (tmp_path / "main.bbl").write_text("\\begin{thebibliography}{9}\n")
    _write_log(tmp_path, "junk\n" + _BIB_OPEN)
    ok, note = tectonic_bib_stall_route(_ctx(tmp_path), None, None, {})
    assert ok
    assert "REJECT: route=xelatex" in note
    assert "references.bib" in note


def test_cant_open_bib_no_bbl_safe(tmp_path: Path) -> None:
    """缺 .bib 且无 .bbl → biber 缺料属实非本路由面 → False。"""
    _write_log(tmp_path, _BIB_OPEN)
    ok, _note = tectonic_bib_stall_route(_ctx(tmp_path), None, None, {})
    assert not ok


def test_no_signature_false(tmp_path: Path) -> None:
    """无关 log → False 让位后续规则。"""
    _write_log(tmp_path, "! Undefined control sequence.\nl.7 \\oops\n")
    ok, note = tectonic_bib_stall_route(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no tectonic bib-stall" in note


def test_registered() -> None:
    """注册进 TRANSFORM_FNS (rules/*.yaml function: 面)。"""
    assert builtins.TRANSFORM_FNS["tectonic_bib_stall_route"] is (
        tectonic_bib_stall_route
    )
