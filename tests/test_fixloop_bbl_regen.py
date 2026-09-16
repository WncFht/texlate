"""bbl_regen 内建 —— bundled 旧版 .bbl 撞新 biblatex, biber 就地重生成。

实证根因 (2009.11064): e-print 捆绑 biber <3.3 格式 .bbl, TL biblatex 3.21
拒载 —— ``\\sortlist`` undefined at ms.bbl:21 / ``File 'ms.bbl' is wrong
format version``; .bcf+.bib 在场 → ``biber <stem>`` 重生成 (输出落 .bcf
同目录)。biber 缺席/超时/失败 → False fail-safe。
"""

from pathlib import Path

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop.builtins import bbl_regen
from texlate.compile.fixloop.engine import LoopCtx, RunFn


def _ctx(tmp_path: Path, runner: RunFn | None = None) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=runner
    )


def _biber_ok(argv: list[str], _timeout: int, wdir: Path) -> tuple:
    """模拟 biber: 落 ``<stem>.bbl``, rc=0。"""
    (wdir / f"{argv[1]}.bbl").write_text("% regen", encoding="utf-8")
    return 0, "INFO - This is Biber 2.22", 0.5, False


def _biber_fail(_argv: list[str], _timeout: int, _wdir: Path) -> tuple:
    return 1, "ERROR - biber died", 0.5, False


def test_bbl_regen_ok(tmp_path: Path) -> None:
    """2009.11064 形: ms.bcf 在场, ``biber ms`` rc=0 → True + .bbl 落地。"""
    (tmp_path / "ms.bcf").write_text("<bcf/>", encoding="utf-8")
    (tmp_path / "ms.bib").write_text("@book{a}", encoding="utf-8")
    calls: list[list[str]] = []

    def _spy(argv: list[str], t: int, w: Path) -> tuple:
        calls.append(argv)
        return _biber_ok(argv, t, w)

    ok, note = bbl_regen(_ctx(tmp_path, runner=_spy), None, "\\sortlist", {})
    assert ok
    assert calls == [["biber", "ms"]]
    assert "ms.bcf" in note
    assert (tmp_path / "ms.bbl").read_text(encoding="utf-8") == "% regen"


def test_bbl_regen_biber_fail(tmp_path: Path) -> None:
    """biber rc≠0 → False, note 带 rc。"""
    (tmp_path / "ms.bcf").write_text("<bcf/>", encoding="utf-8")
    ok, note = bbl_regen(_ctx(tmp_path, runner=_biber_fail), None, None, {})
    assert not ok
    assert "rc=1" in note


def test_bbl_regen_no_bcf(tmp_path: Path) -> None:
    """无 .bcf → False 且 run_tool 不跑。"""
    calls: list[list[str]] = []

    def _spy(argv: list[str], _t: int, _w: Path) -> tuple:
        calls.append(argv)
        return 0, "", 0.1, False

    ok, note = bbl_regen(_ctx(tmp_path, runner=_spy), None, None, {})
    assert not ok
    assert "no .bcf" in note
    assert not calls


def test_bbl_regen_timeout_fails(tmp_path: Path) -> None:
    """biber 超时 (rc=None, to=True) → False。"""
    (tmp_path / "ms.bcf").write_text("<bcf/>", encoding="utf-8")

    def _to(_argv: list[str], _t: int, _w: Path) -> tuple:
        return None, "", 60.0, True

    ok, note = bbl_regen(_ctx(tmp_path, runner=_to), None, None, {})
    assert not ok
    assert "timeout" in note


def test_bbl_regen_multi_bcf_partial(tmp_path: Path) -> None:
    """多 .bcf → 逐 stem 尝试; 一成一败 → True (applied-anything), note 记败。"""
    (tmp_path / "a.bcf").write_text("<bcf/>", encoding="utf-8")
    (tmp_path / "b.bcf").write_text("<bcf/>", encoding="utf-8")
    calls: list[list[str]] = []

    def _mixed(argv: list[str], _t: int, w: Path) -> tuple:
        calls.append(argv)
        if argv[1] == "a":
            return _biber_ok(argv, _t, w)
        return 2, "boom", 0.1, False

    ok, note = bbl_regen(_ctx(tmp_path, runner=_mixed), None, None, {})
    assert ok
    assert calls == [["biber", "a"], ["biber", "b"]]
    assert "rc=2" in note
    assert (tmp_path / "a.bbl").is_file()


def test_bbl_regen_nested_bcf(tmp_path: Path) -> None:
    """嵌套 .bcf → argv 传 wdir 相对 stem, .bbl 落 .bcf 同目录。"""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "ms.bcf").write_text("<bcf/>", encoding="utf-8")
    calls: list[list[str]] = []

    def _spy(argv: list[str], _t: int, w: Path) -> tuple:
        calls.append(argv)
        return _biber_ok(argv, _t, w)

    ok, _note = bbl_regen(_ctx(tmp_path, runner=_spy), None, None, {})
    assert ok
    assert calls == [["biber", "sub/ms"]]
    assert (tmp_path / "sub" / "ms.bbl").is_file()


def test_bbl_regen_registered() -> None:
    """注册进 TRANSFORM_FNS (rules.yaml function: 面)。"""
    assert builtins.TRANSFORM_FNS["bbl_regen"] is bbl_regen
