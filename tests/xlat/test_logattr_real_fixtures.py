"""logattr 真 log fixture 回归 —— tests/fixtures/logs/ 入库件 + manifest.json 逐行断言。

fixture 由 ``bench/py/report/extract_logfix_fixture.py`` 从 gitignored work 目录抽取
（strip 私路径前缀 → 无括弧行裁切 → 重放栈对拍），干净 clone 必跑、不得加
skip 门。manifest.json 每行即该件的断言面——字段由 extractor 对**裁后件**
实算生成，不落手写漂移。

语义重形态（eof_file runaway 归因 / ``==>`` 复述剔除 / fileline-only 零
``^!`` 假干净）另有 dedicated 用例钉死，不只靠 manifest 泛断言。
"""

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.logparse import parse_log as fl_parse_log
from texlate.validate.logattr import parse_log

LOGS = Path(__file__).resolve().parents[1] / "fixtures" / "logs"
REPO = Path(__file__).resolve().parents[2]
_ROWS: list[dict] = json.loads((LOGS / "manifest.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO。"""
    return load_ruleset()


@pytest.mark.parametrize("row", _ROWS, ids=[r["file"] for r in _ROWS])
def test_manifest_row(row: dict) -> None:
    """manifest 每行声明字段逐断言（值以裁后件实算为准）。"""
    pr = row["project_root"]
    # pathlib 右操作数优先：绝对 project_root 会静默吃掉 REPO 前缀，
    # 干净 clone 上 sys_hits 归因被悄然改写——repo-relative 硬门槛拦早。
    assert pr is None or not Path(pr).is_absolute(), (
        f"{row['file']}: project_root must be repo-relative, got {pr!r}"
    )
    root = REPO / pr if pr else None
    if root is not None:
        assert root.is_relative_to(REPO), (
            f"{row['file']}: project_root {pr!r} escapes repo"
        )
        assert root.is_dir(), f"{row['file']}: project_root {pr!r} does not exist"
    v = parse_log(LOGS / row["file"], project_root=root)
    assert not v.log_missing
    assert v.engine == row["engine"]
    assert v.n_errors == row["n_errors"]
    assert v.ok == row["ok"]

    fe_exp = row["first_error"]
    if fe_exp is None:
        assert v.first_error is None
    else:
        fe = v.first_error
        assert fe is not None
        assert fe_exp["head_contains"] in fe.head
        assert fe.tex_file == fe_exp["tex_file"]
        assert fe.tex_line == fe_exp["tex_line"]
        assert fe.eof_file == fe_exp["eof_file"]
        got_suffix = fe.file_stack[-1] if fe.file_stack else None
        assert got_suffix == fe_exp["stack_suffix"]

    w_exp = row["warnings"]
    wc = v.warnings
    for cls, n in w_exp["by_class_min"].items():
        assert wc.by_class.get(cls, 0) >= n
    for cls in w_exp["redline_contains"]:
        assert any(r.startswith(f"{cls}:") for r in wc.redlines)
    for hit in w_exp["sys_hits_contains"]:
        assert hit in wc.sys_hits
    assert wc.cjk_missing >= w_exp["cjk_missing_min"]

    assert (v.tail[-1] if v.tail else None) == row["tail_last"]

    fx = row["fixloop"]
    rep = fl_parse_log(LOGS / row["file"], _rs().warn_patterns)
    assert rep.n_bang == fx["n_bang"]
    cat, pay = _rs().taxonomy.classify(rep)
    assert (cat, pay) == (fx["category"], fx["payload"])


def _text(name: str) -> str:
    return (LOGS / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 语义重形态


def test_runaway_eof_file_attribution() -> None:
    """runaway 错：``)`` 先弹肇事文件，``!`` 行报父文件续行——``eof_file``
    是唯一定位信号（``^!`` 格式无 file:line 锚，tex_file 为 None）。"""
    v = parse_log(LOGS / "xelatex-runaway-eof.log")
    fe = v.first_error
    assert fe is not None
    assert "File ended while scanning" in fe.head
    assert fe.tex_file is None
    assert fe.eof_file == "./plb-rev.tex"


def test_fatal_summary_fileline_not_counted() -> None:
    """``file:line: ==> Fatal error`` 复述尾行不计错——同一失败的复述，
    多计一次会让 n_errors 失真。"""
    text = _text("pdftex-fatal-summary.log")
    assert re.search(r"^\S+\.\w+:\d+:\s*==>", text, re.MULTILINE)  # 真例行在场
    v = parse_log(LOGS / "pdftex-fatal-summary.log")
    assert all("==>" not in e.head for e in v.errors)


def test_fileline_only_zero_bang() -> None:
    """全文零 ``^!`` 仍 n_errors>0——只数 ``!`` 会把真失败判假干净。"""
    text = _text("pdftex-fileline-only-bib.log")
    assert not re.search(r"^!", text, re.MULTILINE)
    v = parse_log(LOGS / "pdftex-fileline-only-bib.log")
    assert v.n_errors > 0
    assert not v.ok


def test_tectonic_engine_none() -> None:
    """tectonic log 无 ``This is`` 标记行——engine=None 不得误判。"""
    for name in ("tectonic-bare-stack.log", "tectonic-citation-warn.log"):
        assert parse_log(LOGS / name).engine is None


def test_manifest_covers_all_fixtures() -> None:
    """入库 .log 必须有 manifest 行——孤儿 fixture 会静默逃掉断言面。"""
    on_disk = {p.name for p in LOGS.glob("*.log")}
    declared = {r["file"] for r in _ROWS}
    assert declared == on_disk, f"diff: {declared ^ on_disk}"


def test_fixtures_no_private_paths() -> None:
    """入库硬门槛：fixture 全件（含 manifest.json）不得含 /home/ /Users/ 私路径。"""
    for p in sorted(LOGS.iterdir()):
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8")
        assert "/home/" not in text, p.name
        assert "/Users/" not in text, p.name
