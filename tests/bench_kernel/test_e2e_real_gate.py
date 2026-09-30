"""e2e_real fixloop wanted 闸——跨 run layoutqc 质检账补票。

编译 clean 但版面有重缺陷（layout:overfull/float_lost、重越界）的格子
靠上一轮 run 立的 layoutqc ``sig_counts`` 进修复环；layoutqc topo 在
fixloop 之后，本 run 内账未立是设计内口径（本轮质检喂下一轮修复）。

全离线：records 账用真 Index+ 事件投影；命中路径落到 splice 缺席的
no_splice 闸证明过了 not_wanted；wanted 全程面再 monkeypatch 引擎
三件套（_make_engine/fixloop/XelatexEngine/judge_dict）钉
metrics.qc_wanted.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from kernel import events
from kernel.ctx import Ctx
from kernel.index import Index
from kernel.runs import RunDir
from specs import e2e_real as er

_IDC = "2101.00001"
_RUN = "e2e_real/2026-01-01/s"


def _rec(
    idx: Index, seq: int, stage: str, status: str, metrics: dict | None = None
) -> None:
    """投一条 records 账（run/seq 任意——_last_done 是全域口径）。"""
    idx.apply_event(
        events.make_event(
            events.T_CELL,
            run=_RUN,
            seq=seq,
            id=_IDC,
            idc=_IDC,
            arm=er.ARM,
            up="-",
            variant=er.EPOCH,
            stage=stage,
            status=status,
            metrics=metrics or {},
        )
    )


def _ctx(idx: Index, tmp_path: Path, *, fixloop_mode: str = "onfail") -> Ctx:
    rd = RunDir(path=tmp_path / "run", kind="e2e_real", date="2026-01-01", slug="s")
    cell = {
        "id": _IDC,
        "idc": _IDC,
        "arm": er.ARM,
        "up": "-",
        "variant": er.EPOCH,
        "stage": "fixloop",
        "run_params": {"fixloop": fixloop_mode, "timeout": 5.0},
    }
    return Ctx(_RUN, cell, idx, er.spec, rundir=rd)


def _seed_ok_chain(idx: Index) -> None:
    """route ok + compile clean——_want_fix(onfail) 必拒的基底。"""
    _rec(idx, 1, "route", "ok", {"main_rel": "main.tex"})
    _rec(
        idx,
        2,
        "compile",
        "clean",
        {"main_rel": "main.tex", "verdict": {"status": "clean"}},
    )


# ---------------------------------------------------------------- _qc_wanted


def test_qc_wanted_hits_and_thresholds(
    broot: Path,  # noqa: ARG001 -- fixture 副作用（TEXLATE_BENCH_ROOT 隔离）
    tmp_path: Path,
) -> None:
    idx = Index()
    ctx = _ctx(idx, tmp_path)
    # 无 layoutqc 账 → 空
    assert er._qc_wanted(ctx) == {}  # noqa: SLF001
    _rec(
        idx,
        3,
        "layoutqc",
        "ok",
        {"sig_counts": {"layout:overfull": 1, "geo_margin_breach": 2}},
    )
    # overfull≥1 命中；margin_breach 2<3 不命中
    assert er._qc_wanted(ctx) == {"layout:overfull": 1}  # noqa: SLF001
    _rec(
        idx,
        4,
        "layoutqc",
        "ok",
        {"sig_counts": {"geo_margin_breach": 3, "geo_text_overlap": 4}},
    )
    # 末条 DONE 胜——新一轮 counts 全覆盖
    assert er._qc_wanted(ctx) == {  # noqa: SLF001
        "geo_margin_breach": 3,
        "geo_text_overlap": 4,
    }


def test_qc_wanted_misses(
    broot: Path,  # noqa: ARG001 -- fixture 副作用
    tmp_path: Path,
) -> None:
    idx = Index()
    ctx = _ctx(idx, tmp_path)
    _rec(idx, 3, "layoutqc", "ok", {"sig_counts": {"layout:float_fit": 9}})
    assert er._qc_wanted(ctx) == {}  # noqa: SLF001
    _rec(idx, 4, "layoutqc", "clean", {"sig_counts": {}})
    assert er._qc_wanted(ctx) == {}  # noqa: SLF001
    _rec(idx, 5, "layoutqc", "ok", {"sig_counts": "garbage"})
    assert er._qc_wanted(ctx) == {}  # noqa: SLF001 -- 非 dict 形态不炸


def test_qc_wanted_declined_row_no_shadow(
    broot: Path,  # noqa: ARG001 -- fixture 副作用
    tmp_path: Path,
) -> None:
    """declined 闸行（reject 占 DONE 位、无 sig_counts）不遮蔽早先
    真账——钉末条 ok 而非末条 DONE（verify 实证遮蔽回归）。"""
    idx = Index()
    ctx = _ctx(idx, tmp_path)
    _rec(idx, 3, "layoutqc", "ok", {"sig_counts": {"layout:overfull": 5}})
    _rec(idx, 4, "layoutqc", "reject", {"gate": "qc_no_input"})
    assert er._qc_wanted(ctx) == {"layout:overfull": 5}  # noqa: SLF001


# ---------------------------------------------------------------- wanted 闸


def test_fixloop_qc_rescue_overfull(
    broot: Path,  # noqa: ARG001 -- fixture 副作用
    tmp_path: Path,
) -> None:
    """compile clean + 上轮 overfull → 不 decline，过 wanted 闸走正常路
    （splice 缺席落 no_splice skip——证明闸门放行而非真跑修复）。"""
    idx = Index()
    _seed_ok_chain(idx)
    _rec(idx, 3, "layoutqc", "ok", {"sig_counts": {"layout:overfull": 5}})
    out = er._fixloop(_ctx(idx, tmp_path))  # noqa: SLF001
    assert out["status"] == "skip"
    assert out["errors"][0]["code"] == "no_splice"


def test_fixloop_qc_rescue_needs_hit(
    broot: Path,  # noqa: ARG001 -- fixture 副作用
    tmp_path: Path,
) -> None:
    """质检账在但无重缺陷命中 → 仍 declined:not_wanted。"""
    idx = Index()
    _seed_ok_chain(idx)
    _rec(idx, 3, "layoutqc", "ok", {"sig_counts": {"geo_margin_breach": 2}})
    out = er._fixloop(_ctx(idx, tmp_path))  # noqa: SLF001
    assert out["status"] == "reject"
    assert out["sig"] == "declined:not_wanted"


def test_fixloop_clean_no_qc_declines(
    broot: Path,  # noqa: ARG001 -- fixture 副作用
    tmp_path: Path,
) -> None:
    """compile clean + 无质检账 → declined:not_wanted（原口径不破）。"""
    idx = Index()
    _seed_ok_chain(idx)
    out = er._fixloop(_ctx(idx, tmp_path))  # noqa: SLF001
    assert out["status"] == "reject"
    assert out["sig"] == "declined:not_wanted"


def test_fixloop_qc_rescue_never_mode_refuses(
    broot: Path,  # noqa: ARG001 -- fixture 副作用
    tmp_path: Path,
) -> None:
    """mode=never 仍拒——质检补票是 onfail 限定。"""
    idx = Index()
    _seed_ok_chain(idx)
    _rec(idx, 3, "layoutqc", "ok", {"sig_counts": {"layout:float_lost": 2}})
    out = er._fixloop(_ctx(idx, tmp_path, fixloop_mode="never"))  # noqa: SLF001
    assert out["status"] == "reject"
    assert out["sig"] == "declined:not_wanted"


def test_fixloop_qc_rescue_reject_at_refuses(
    broot: Path,  # noqa: ARG001 -- fixture 副作用
    tmp_path: Path,
) -> None:
    """compile clean 但 reject_at='inject' → inject 拒绝口径本就是
    「不救」，qc 补票不越权。"""
    idx = Index()
    _rec(idx, 1, "route", "ok", {"main_rel": "main.tex"})
    _rec(
        idx,
        2,
        "compile",
        "clean",
        {
            "main_rel": "main.tex",
            "verdict": {"status": "clean"},
            "reject_at": "inject",
        },
    )
    _rec(idx, 3, "layoutqc", "ok", {"sig_counts": {"layout:overfull": 5}})
    out = er._fixloop(_ctx(idx, tmp_path))  # noqa: SLF001
    assert out["status"] == "reject"
    assert out["sig"] == "declined:not_wanted"


def test_fixloop_qc_rescue_compile_reject_refuses(
    broot: Path,  # noqa: ARG001 -- fixture 副作用
    tmp_path: Path,
) -> None:
    """compile reject（上游链死形态）不吃 qc 补票——修 vault 里上一轮
    splice 不是本 run 该干的活。"""
    idx = Index()
    _rec(idx, 1, "route", "ok", {"main_rel": "main.tex"})
    _rec(idx, 2, "compile", "reject", {"main_rel": "main.tex"})
    _rec(idx, 3, "layoutqc", "ok", {"sig_counts": {"layout:overfull": 5}})
    out = er._fixloop(_ctx(idx, tmp_path))  # noqa: SLF001
    assert out["status"] == "reject"
    assert out["sig"] == "declined:not_wanted"


def test_fixloop_qc_wanted_in_metrics(
    broot: Path,  # noqa: ARG001 -- fixture 副作用
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命中放行后 metrics.qc_wanted 记 {sig: count}——走完全程面
    （引擎三件套替身化，复判钉 clean）。"""
    idx = Index()
    _seed_ok_chain(idx)
    _rec(idx, 3, "layoutqc", "ok", {"sig_counts": {"layout:float_lost": 2}})
    ctx = _ctx(idx, tmp_path)
    # splice.real@v1 物化——跳过 vault restore 支
    splice = ctx.paper_dir() / "splice.real@v1"
    splice.mkdir(parents=True)
    (splice / "main.tex").write_text("\\documentclass{article}\n")

    monkeypatch.setattr(er.flb, "_make_engine", lambda *_a, **_k: None)
    monkeypatch.setattr(
        er,
        "fixloop",
        lambda *_a, **_k: {"verdict": "clean", "rounds": [], "actions": []},
    )
    monkeypatch.setattr(
        er,
        "XelatexEngine",
        lambda **_kw: SimpleNamespace(compile=lambda *_a, **_k: None),
    )
    monkeypatch.setattr(
        er.benchlib,
        "judge_dict",
        lambda _res, **_kw: {"verdict": {"status": "clean"}, "compile": {}},
    )
    out = er._fixloop(ctx)  # noqa: SLF001
    assert out["status"] == "clean"
    assert out["metrics"]["qc_wanted"] == {"layout:float_lost": 2}
    assert out["metrics"]["fixloop_ran"] is True
