"""bench 评测 harness 账/记分口径回归（bench-harness-audit 实证锚点）。

覆盖 gate_scorecard 终态合成与缺口公式、benchlib 原子写/账读、
e2e_mock 种子回退与崩残键、triage 状态词汇边界、compilebench_v3 报告
容忍度、build_corpus_v3 fetch_one 腐文件重抓。bench/py 纯 stdlib 目经
pyproject pythonpath 直进；重 import 链（texlate.*）importorskip 延迟。
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from typing import TYPE_CHECKING

import benchlib
import pytest
import triage

from texlate.compile.engine import CompRes, parse_log

if TYPE_CHECKING:
    from pathlib import Path

N_CLEAN_CELLS = 89
N_TEX_FILES = 2


def _rec(pid: str, status: str, **over: object) -> dict:
    rec = {"id": pid, "stage": "compile", "arm": "zh", "status": status, "sig": ""}
    rec.update(over)
    return rec


# ---------------------------------------------------------------- gate_scorecard
def test_pick_final_upstream_mismatch_dropped() -> None:
    """fixloop 记录 upstream 与 compile 不一致 → 陈旧作废（跨上游波次防串）。"""
    gate_scorecard = pytest.importorskip("gate_scorecard")
    c = _rec("p1", "fail", upstream="u1")
    f = {
        "id": "p1",
        "status": "clean",
        "upstream": "u2",
        "metrics": {"compile_status_before": "fail"},
    }
    stage, r, drop = gate_scorecard.pick_final(c, f)
    assert (stage, r["status"], drop) == ("compile", "fail", "upstream_mismatch")
    # 同 upstream 正常生效；任一侧缺 upstream 字段不判陈旧（史前排无此字段）
    f2 = {**f, "upstream": "u1"}
    assert gate_scorecard.pick_final(c, f2)[:2] == ("fixloop", f2)
    f3 = {k: v for k, v in f.items() if k != "upstream"}
    assert gate_scorecard.pick_final(c, f3)[:2] == ("fixloop", f3)


def test_gate_scorecard_empty_and_gap(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空 records 不除零；100 格 89 pdf → need +1（非 +2 浮点/取整 off-by-one）。"""
    gate_scorecard = pytest.importorskip("gate_scorecard")
    monkeypatch.setattr(sys, "argv", ["gate_scorecard", str(tmp_path)])
    assert gate_scorecard.main() == 0
    assert "cells=0" in capsys.readouterr().out

    recdir = tmp_path / "records"
    recdir.mkdir()
    with (recdir / "compile.jsonl").open("w") as f:
        for i in range(100):
            st = "clean" if i < N_CLEAN_CELLS else "fail"
            f.write(json.dumps(_rec(f"p{i}", st)) + "\n")
    monkeypatch.setattr(sys, "argv", ["gate_scorecard", str(recdir)])
    assert gate_scorecard.main() == 0
    assert "need +1" in capsys.readouterr().out

    # 全 reject → excl-reject 行不除零（直接省略该行）
    with (recdir / "compile.jsonl").open("w") as f:
        for i in range(5):
            f.write(json.dumps(_rec(f"r{i}", "reject")) + "\n")
    monkeypatch.setattr(sys, "argv", ["gate_scorecard", str(recdir)])
    assert gate_scorecard.main() == 0
    assert "excl-reject" not in capsys.readouterr().out


# ---------------------------------------------------------------- benchlib
def test_atomic_write_text_replaces(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    benchlib.atomic_write_text(p, '{"a": 1}')
    benchlib.atomic_write_text(p, '{"a": 2}')
    assert json.loads(p.read_text()) == {"a": 2}
    assert not (tmp_path / "x.json.tmp").exists()


def test_judge_dict_has_warnings_hit() -> None:
    """judge_dict verdict 与 e2e._tail_dict 对齐补 warnings_hit。"""
    res = CompRes(engine="xelatex")
    res.log = parse_log("! Undefined control sequence.\nl.1 \\x\n")
    tail = benchlib.judge_dict(res, expect_cjk=False)
    assert "warnings_hit" in tail["verdict"]


def test_verdict_serializers_key_parity() -> None:
    """judge_dict 与 e2e._tail_dict verdict 键集恒同——单边加字段即漂移。"""
    from texlate import e2e  # noqa: PLC0415 -- 延迟到用点: 本仓产品模块重链
    from texlate.compile.judge import judge  # noqa: PLC0415 -- 同上

    res = CompRes(engine="xelatex")
    res.log = parse_log("! Undefined control sequence.\nl.1 \\x\n")
    v = judge(res, expect_cjk=False)
    a = benchlib.judge_dict(res, expect_cjk=False)["verdict"]
    b = e2e._tail_dict(res, v)["verdict"]  # noqa: SLF001 - 序列化器键集对拍
    assert set(a) == set(b)
    assert a["error_cats"] == {"undefined_cs": 1}


def test_judge_dict_has_l2_attr(tmp_path: Path) -> None:
    """judge_dict tail 带 canonical ``l2_attr`` 归因载荷——stagerun 落
    ``metrics.l2_attr`` 的 records 聚类原料；无 log 时同形零命中不炸。"""
    log = tmp_path / "main.log"
    log.write_text(
        "(./main.tex\n"
        "LaTeX Warning: Reference `r' undefined on input line 3.\n"
        "./main.tex:9: Undefined control sequence.\nl.9 \\x\n)\n",
        encoding="utf-8",
    )
    res = CompRes(engine="xelatex")
    res.log_path = log
    res.workdir = tmp_path
    attr = benchlib.judge_dict(res, expect_cjk=False)["l2_attr"]
    assert attr["n_errors"] == 1
    assert attr["warn_by_class"] == {"reference": 1}
    assert [h["kind"] for h in attr["hits"]] == ["reference", "error"]
    json.dumps(attr)  # records jsonl 落账可序列化
    bare = benchlib.judge_dict(CompRes(engine="xelatex"), expect_cjk=False)
    assert bare["l2_attr"]["log_missing"] is True
    assert bare["l2_attr"]["hits"] == []


def test_judge_dict_has_taxonomy(tmp_path: Path) -> None:
    """judge_dict tail 带 fixloop taxonomy 二级分类——M1 物化位
    (still-manual-audit): stagerun 落 ``metrics.taxonomy`` /
    fixloop post 落 ``metrics.post.taxonomy``, dossier 细分聚合桶直读。"""
    log = tmp_path / "main.log"
    log.write_text(
        "./main.tex:9: Undefined control sequence.\nl.9 \\foo\n",
        encoding="utf-8",
    )
    res = CompRes(engine="xelatex")
    res.log_path = log
    res.workdir = tmp_path
    tax = benchlib.judge_dict(res, expect_cjk=False)["taxonomy"]
    assert tax["cat"] == "undefined_cs"
    assert tax["pay"] == "foo"  # payload 是 cs 名 (无前导反斜杠)
    json.dumps(tax)  # records jsonl 落账可序列化
    bare = benchlib.judge_dict(CompRes(engine="xelatex"), expect_cjk=False)
    assert bare["taxonomy"]["cat"] in ("clean", "other", None)


# ---------------------------------------------------------------- e2e_mock 种子
def test_e2e_mock_seed_fallback(tmp_path: Path) -> None:
    """账全坏行 → results.json 兜底；快照坏 → 空种子不崩。"""
    m = pytest.importorskip("e2e_mock_bench")
    rec = tmp_path / "records.jsonl"
    out = tmp_path / "results.json"

    rec.write_text('{"id": "a", "pipe-xel": {"verdict": {"status": "clean"}}}\n')
    out.write_text(json.dumps({"b": {"old": True}}))
    # 账有好行 → 账胜
    assert list(m.seed_results(rec, out)) == ["a"]
    # 账全坏行 → 回退 results.json
    rec.write_text('{"id": "a", "pi')
    assert list(m.seed_results(rec, out)) == ["b"]
    # 快照也坏 → 空
    out.write_text("{corrupt")
    assert m.seed_results(rec, out) == {}
    # 快照是 list（形状错）→ 空而非 TypeError 下游
    out.write_text("[1,2]")
    assert m.seed_results(rec, out) == {}


# ---------------------------------------------------------------- triage 状态词
def test_pipeline_introduced_excludes_skip_error(tmp_path: Path) -> None:
    """zh 侧 skip/reject/error 不算管线引入回归——上游门/harness 崩非翻译缺陷。"""
    recs = [
        _rec("p_skip", "skip", arm="zh"),
        _rec("p_err", "error", arm="zh"),
        _rec("p_fail", "fail", arm="zh"),
        _rec("p_skip", "ok", arm="base", stage="compile"),
        _rec("p_err", "ok", arm="base", stage="compile"),
        _rec("p_fail", "ok", arm="base", stage="compile"),
    ]
    line = triage.compute_metrics(tmp_path, recs, None)
    pipes = [r["id"] for r in line["regressions"] if r["kind"] == "pipeline_introduced"]
    assert pipes == ["p_fail"]
    assert "skipped_oversize" in triage.SKIP_STATUS
    assert "bench_error" in triage.SKIP_STATUS


# ---------------------------------------------------------------- compilebench_v3
def test_cbv3_report_torn_cases_no_cells(tmp_path: Path) -> None:
    """cases.jsonl 截尾行跳过 + cells.json 缺 → n_papers=0 不除零。"""
    cbv3 = pytest.importorskip("compilebench_v3")
    out = tmp_path / "o"
    out.mkdir()
    with (out / "cases.jsonl").open("w") as f:
        f.write(
            json.dumps(
                {
                    "paper_id": "a",
                    "engine": "xelatex",
                    "verdict": "clean",
                    "pdf": True,
                }
            )
            + "\n"
        )
        f.write('{"paper_id": "b", "eng')
    args = Namespace(
        out=out,
        corpus=tmp_path / "corpus",
        work=tmp_path / "work",
        jobs=1,
        sample_n=0,
        seed=0,
        condition="baseline",
        engines="xelatex",
        v2_cells=None,
    )
    cbv3.report(args)
    summary = (out / "summary.md").read_text()
    assert "联合覆盖" in summary


# ---------------------------------------------------------------- build_corpus_v3
def test_fetch_one_corrupt_final_refetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """final 尺寸错（腐文件）+ 无 .part → 删 final 从头重抓，而非续传错位字节。"""
    b3 = pytest.importorskip("build_corpus_v3")
    tars = tmp_path / "tars"
    tars.mkdir()
    monkeypatch.setattr(b3, "TARS", tars)
    final = tars / "it.tar"
    final.write_bytes(b"12345")  # 5B != size=10，腐 final

    seen: dict[str, int] = {}

    def fake_dl(c: dict, part: Path, have: int) -> None:
        seen["have"] = have
        part.write_bytes(b"x" * (c["size"] - have))

    monkeypatch.setattr(b3, "stream_download", fake_dl)
    monkeypatch.setattr(b3, "verify_chunk", lambda *_a: "sha")
    c = {
        "item": "it",
        "size": 10,
        "channel": "ia",
        "url": "http://x",
        "state": "pending",
    }
    out = b3.fetch_one(c)
    assert out["state"] == "done"
    assert seen["have"] == 0  # 从头重抓，非从 final 尺寸续传
    assert final.read_bytes() == b"x" * 10

    # 正确尺寸 final 快路不受影响
    final.write_bytes(b"y" * 10)
    c2 = {**c, "state": "pending"}
    out2 = b3.fetch_one(c2)
    assert out2["state"] == "done"
    assert final.read_bytes() == b"y" * 10
    assert seen["have"] == 0  # 未再触发下载


def test_expand_manifest_row_from_meta(tmp_path: Path) -> None:
    """extracted 在而 manifest 缺 → meta.json 回补行（含 main_tex_sha256 重算）。"""
    be = pytest.importorskip("build_corpus_expand")
    dest = tmp_path / "2401.00001"
    (dest / "extracted").mkdir(parents=True)
    (dest / "extracted" / "main.tex").write_text("\\documentclass{article}")
    meta = {
        "arxiv_id": "2401.00001",
        "era": "new",
        "archive": None,
        "yymm": "2401",
        "cluster_id": "c",
        "layer": "expand",
        "stratum_cell": "a_1991_99|cs",
        "cat_group": "cs",
        "license_class": "ok",
        "channel": "ia",
        "item": "it",
        "member": "2401/2401.00001.tar",
        "raw_sha256": "abc",
        "format": "tar",
        "n_files": 3,
        "tex_files": N_TEX_FILES,
        "bytes": 100,
        "features": {"tex_roots": ["main.tex"]},
        "pick_reason": "expand_quota:x",
        "pool": "new",
    }
    (dest / "meta.json").write_text(json.dumps(meta))
    row = be.manifest_row_from_meta(dest)
    assert row["id"] == "2401.00001"
    assert row["blob_sha256"] == "abc"
    assert row["n_tex"] == N_TEX_FILES
    assert row["main_tex_sha256"] is not None
    # meta 坏 → None（落回重抓自愈路径）
    (dest / "meta.json").write_text("{corrupt")
    assert be.manifest_row_from_meta(dest) is None
