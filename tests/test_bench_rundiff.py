"""rundiff 两 run 逐格迁移：矩阵计数、degraded/improved/added/removed、--stage、末条胜去重。

合成 records/{stage}.jsonl 目录对，不经 stagerun——rundiff 只依赖
triage.load_records 与 STATUS_RANK，纯 stdlib 可测。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

BENCH_PY = Path(__file__).resolve().parents[1] / "bench" / "py"
sys.path.insert(0, str(BENCH_PY))

import rundiff  # noqa: E402


def _rec(pid: str, stage: str, status: str, **over: object) -> dict:
    rec = {
        "id": pid,
        "stage": stage,
        "arm": "zh",
        "upstream": "mock",
        "status": status,
        "dur_s": 1.0,
        "metrics": {},
        "errors": [],
        "sig": "",
    }
    rec.update(over)
    return rec


def _write_run(root: Path, name: str, stage_rows: dict) -> Path:
    rdir = root / name
    (rdir / "records").mkdir(parents=True)
    for stage, rows in stage_rows.items():
        with (rdir / "records" / f"{stage}.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return rdir


def _two_runs(tmp_path: Path) -> tuple[Path, Path]:
    a = _write_run(
        tmp_path,
        "runA",
        {
            "compile": [
                _rec("a1", "compile", "ok"),
                _rec("a2", "compile", "fail", sig="missing_file:x.cls"),
                _rec("a3", "compile", "partial"),
                _rec("gone", "compile", "ok"),
                {"note": "no-id row ignored"},
            ],
            "xlat": [_rec("a1", "xlat", "ok", arm="mock", upstream="")],
        },
    )
    b = _write_run(
        tmp_path,
        "runB",
        {
            "compile": [
                _rec("a1", "compile", "ok"),
                _rec("a2", "compile", "ok"),
                _rec("a3", "compile", "fail", sig="undefined_cs:\\x"),
                _rec("new1", "compile", "fail", sig="missing_file:y.sty"),
            ],
            "xlat": [
                _rec("a1", "xlat", "fail", arm="mock", upstream="", sig="auth:401")
            ],
            "parse": [_rec("a1", "parse", "ok", arm="-", upstream="")],
        },
    )
    return a, b


# ---------------------------------------------------------------- 矩阵计数
def test_migration_matrix_counts(tmp_path: Path) -> None:
    a, b = _two_runs(tmp_path)
    cells_a, cells_b = rundiff.stage_cells(a), rundiff.stage_cells(b)
    # 无 id 行不成格键
    assert sorted(k[0] for k in cells_a["compile"]) == ["a1", "a2", "a3", "gone"]
    d = rundiff.diff_stage(cells_a["compile"], cells_b["compile"])
    assert d["matrix"] == {
        ("ok", "ok"): 1,  # a1 不动
        ("fail", "ok"): 1,  # a2 修复
        ("partial", "fail"): 1,  # a3 退化
        ("ok", rundiff.ABSENT): 1,  # gone 消失
        (rundiff.ABSENT, "fail"): 1,  # new1 新增
    }


# ---------------------------------------------------------------- 名单
def test_degraded_improved_added_removed(tmp_path: Path) -> None:
    a, b = _two_runs(tmp_path)
    d = rundiff.diff_stage(
        rundiff.stage_cells(a)["compile"], rundiff.stage_cells(b)["compile"]
    )
    assert [e["id"] for e in d["degraded"]] == ["a3"]
    deg = d["degraded"][0]
    assert (deg["a"], deg["b"]) == ("partial", "fail")
    assert deg["sig_b"] == "undefined_cs:\\x"  # 退化看 B 侧 sig
    assert [e["id"] for e in d["improved"]] == ["a2"]
    assert d["improved"][0]["sig_a"] == "missing_file:x.cls"  # 改善看 A 侧 sig
    assert [e["id"] for e in d["same"]] == ["a1"]
    assert [e["id"] for e in d["added"]] == ["new1"]
    assert d["added"][0]["b"] == "fail"
    assert d["added"][0]["sig"] == "missing_file:y.sty"
    assert [e["id"] for e in d["removed"]] == ["gone"]
    assert d["removed"][0]["a"] == "ok"


# ---------------------------------------------------------------- 两侧末条胜去重
def test_last_wins_both_sides(tmp_path: Path) -> None:
    a = _write_run(
        tmp_path,
        "runA",
        {
            "compile": [
                _rec("p", "compile", "fail", sig="missing_file:a.cls"),
                _rec("p", "compile", "ok"),  # resume 末条胜
            ]
        },
    )
    b = _write_run(
        tmp_path,
        "runB",
        {
            "compile": [
                _rec("p", "compile", "ok"),
                _rec("p", "compile", "fail", sig="undefined_cs:\\z"),  # rerun 末条胜
            ]
        },
    )
    cells_a = rundiff.stage_cells(a)["compile"]
    cells_b = rundiff.stage_cells(b)["compile"]
    assert len(cells_a) == len(cells_b) == 1
    d = rundiff.diff_stage(cells_a, cells_b)
    assert d["matrix"] == {("ok", "fail"): 1}
    assert [e["id"] for e in d["degraded"]] == ["p"]


# ---------------------------------------------------------------- stage 过滤 / 默认交集
def test_stage_filter_and_default_intersection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = _two_runs(tmp_path)
    assert rundiff.main([str(a), str(b), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    # parse 只在 B 侧 → 默认交集不比
    assert sorted(out["stages"]) == ["compile", "xlat"]
    assert out["stages"]["compile"]["counts"] == {
        "same": 1,
        "improved": 1,
        "degraded": 1,
        "added": 1,
        "removed": 1,
    }
    # 显式 --stage 可比单侧 stage: 全算 added
    assert rundiff.main([str(a), str(b), "--stage", "parse", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert list(out["stages"]) == ["parse"]
    assert out["stages"]["parse"]["counts"]["added"] == 1
    # xlat 全格退化 ok→fail (rank 3→1)
    assert rundiff.main([str(a), str(b), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in out["stages"]["xlat"]["degraded"]] == ["a1"]


# ---------------------------------------------------------------- 自比零迁移
def test_self_diff_zero_migration(tmp_path: Path) -> None:
    a, _ = _two_runs(tmp_path)
    cells = rundiff.stage_cells(a)["compile"]
    d = rundiff.diff_stage(cells, cells)
    assert not d["degraded"]
    assert not d["improved"]
    assert not d["added"]
    assert not d["removed"]
    assert all(sa == sb for sa, sb in d["matrix"])  # 全对角


# ---------------------------------------------------------------- markdown 输出
def test_markdown_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a, b = _two_runs(tmp_path)
    assert rundiff.main([str(a), str(b)]) == 0
    md = capsys.readouterr().out
    assert "| A \\ B |" in md
    assert "### degraded (1)" in md
    assert "### improved (1)" in md
    assert "### added in B (1)" in md
    assert "### removed in B (1)" in md
    assert "a3 (zh/mock)" in md  # 非默认 arm/upstream 进标签
    assert "missing_file:y.sty" in md
    assert "## parse" not in md  # 单侧 stage 不进默认对比
