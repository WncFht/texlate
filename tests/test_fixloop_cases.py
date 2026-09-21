"""cases — cases.jsonl 沉淀 / triage / 回放三门 单测 (docs/spec/compile.md)。"""

from pathlib import Path

from _fixloopkit import rs
from test_fixloop_loop import CLEAN_LOG, MockEngine, make_proj

from texlate.compile.fixloop import CaseSink, load_cases
from texlate.compile.fixloop.cases import (
    replay_all,
    replay_case,
    stats_backfill,
    triage,
)
from texlate.compile.fixloop.engine import fixloop


def _cell(verdict: str, **kw: object) -> dict:
    cell = {
        "project": "1706.03762",
        "cond": "ctex",
        "engine": "xelatex",
        "main": "main.tex",
        "verdict": verdict,
        "final_pdf": verdict in ("clean", "acceptable_pdf", "dirty_pdf"),
        "final_errors": 0,
        "started_fail": True,
        "rounds": [
            {
                "round": 1,
                "category": "missing_file",
                "payload": "x.sty",
                "pdf": False,
                "n_errors": 1,
                "warnings": [],
            }
        ],
        "actions": [{"round": 1, "rule": "install_file", "detail": "installed x.sty"}],
        "installed": ["x.sty"],
        "advisories": [],
        "log_excerpt": "! File `x.sty' not found",
    }
    cell.update(kw)
    return cell


# ---------------------------------------------------------------- sink / load / triage
def test_sink_record_and_load(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    sink = CaseSink(path)
    sink.record(_cell("clean"), corpus_id="p1", cond="ctex", engine="xelatex")
    sink.record(_cell("unfixable:soul_err", project="p2"))
    cases = load_cases(path)
    assert len(cases) == 2  # noqa: PLR2004
    assert cases[0]["corpus"] == "p1"
    assert cases[0]["cond"] == "ctex"
    assert cases[1]["corpus"] == "p2"
    assert cases[0]["rounds"][0]["cat"] == "missing_file"
    assert cases[0]["actions"][0]["rule"] == "install_file"


L209_TEX = "\\documentstyle{article}\n\\begin{document}\nhi\n\\end{document}\n"
L209_LOG = (
    "! LaTeX Error: \\documentstyle not supported outside compatibility mode.\n"
    "l.1 \\documentstyle{article}\n"
)


def test_gate_reject_records_gate_fired(tmp_path: Path) -> None:
    """gate 相 REJECT 不进 ``actions``——``gate_fired`` 单列载拒绝规则。

    rules_fired 是「动作跑过」面; REJECT 是终止决策不跑动作列 (gate/loop
    相 append 在判 REJECT 之后), ``gate_fired`` 是 census/stats 的互补面。
    """
    make_proj(tmp_path, L209_TEX)
    sink = CaseSink(tmp_path / "cases.jsonl")
    cell = fixloop(
        tmp_path,
        MockEngine([{"log": L209_LOG, "pdf": False}]),
        ruleset=rs(),
        case_sink=sink,
    )
    assert cell["verdict"] == "reject:latex209_reject"
    assert cell["reject_route"] == "latex+dvips"
    assert cell["gate_fired"] == ["latex209_reject"]
    fired = [a["rule"] for a in cell["actions"]]
    assert "latex209_reject" not in fired
    case = load_cases(tmp_path / "cases.jsonl")[0]
    assert case["gate_fired"] == ["latex209_reject"]
    # 非拒绝格: gate_fired 恒在、为空
    sink2 = CaseSink(tmp_path / "c2.jsonl")
    sink2.record(_cell("clean"))
    assert load_cases(tmp_path / "c2.jsonl")[0]["gate_fired"] == []


def test_load_cases_missing_file(tmp_path: Path) -> None:
    assert load_cases(tmp_path / "nope.jsonl") == []


def test_triage_filters_failure_verdicts() -> None:
    cases = [
        {"verdict": "clean"},
        {"verdict": "acceptable_pdf"},
        {"verdict": "unfixable:soul_err"},
        {"verdict": "stuck"},
        {"verdict": "dirty_pdf"},
        {"verdict": "max_rounds"},
        {"verdict": "no_errors_no_pdf"},
        {"verdict": "reject:latex209_reject"},
    ]
    queued = [c["verdict"] for c in triage(cases)]
    assert queued == [
        "unfixable:soul_err",
        "stuck",
        "dirty_pdf",
        "max_rounds",
        "no_errors_no_pdf",
    ]


# ---------------------------------------------------------------- 回放门 ①②
def test_replay_case_gate1(tmp_path: Path) -> None:
    make_proj(tmp_path)
    case = {
        "corpus": "p",
        "cond": "c",
        "verdict": "unfixable:missing_file",
        "started_fail": True,
    }
    res = replay_case(
        case, tmp_path, MockEngine([{"log": CLEAN_LOG, "pdf": True}]), rs()
    )
    assert res.verdict_after == "clean"
    assert res.gate1_rescued is True


def test_replay_case_fail_stays(tmp_path: Path) -> None:
    make_proj(tmp_path)
    case = {"corpus": "p", "cond": "c", "verdict": "unfixable:x", "started_fail": True}
    eng = MockEngine([{"log": "! Bizarre\n", "pdf": False}])
    res = replay_case(case, tmp_path, eng, rs())
    assert res.gate1_rescued is False
    assert res.verdict_after.startswith("unfixable")


def test_replay_all_gate2_regression(tmp_path: Path) -> None:
    make_proj(tmp_path)
    clean_case = {"corpus": "a", "cond": "c", "verdict": "clean", "started_fail": False}
    fail_case = {
        "corpus": "b",
        "cond": "c",
        "verdict": "unfixable:x",
        "started_fail": True,
    }

    # 两轮都修好 → 无回归
    results = replay_all(
        [clean_case, fail_case],
        resolve_proj=lambda _c: tmp_path,
        engine_factory=lambda _c: MockEngine([{"log": CLEAN_LOG, "pdf": True}]),
        ruleset=rs(),
    )
    assert len(results) == 2  # noqa: PLR2004
    assert all(not r.regressed for r in results)
    assert results[1].gate1_rescued is True

    # 曾 clean 的格被改坏 → regressed (底板兜回入口 pdf 也算: 树死了)
    results = replay_all(
        [clean_case],
        resolve_proj=lambda _c: tmp_path,
        engine_factory=lambda _c: MockEngine(
            [{"log": "! File `x.sty' not found.\n", "pdf": False}]
        ),
        ruleset=rs(),
    )
    assert results[0].regressed is True
    assert results[0].floor_restored is True
    assert results[0].verdict_after == "acceptable_pdf"


def test_replay_all_skips_missing_proj(tmp_path: Path) -> None:
    results = replay_all(
        [{"corpus": "ghost", "verdict": "unfixable:x"}],
        resolve_proj=lambda _c: tmp_path / "absent",
        engine_factory=lambda _c: MockEngine([{"log": CLEAN_LOG, "pdf": True}]),
        ruleset=rs(),
    )
    assert results == []


# ---------------------------------------------------------------- 回放门 ③ stats 回填
def test_stats_backfill_counts_and_promotes() -> None:
    raw = {
        "rules": [
            {"id": "install_file", "stats": {"status": "proposed"}},
            {"id": "dead_rule", "stats": {"status": "proposed"}},
        ]
    }
    cells = [
        _cell("clean", actions=[{"rule": "install_file"}, {"rule": "install_file"}]),
        _cell(
            "unfixable:x",
            project="q",
            final_pdf=False,
            actions=[{"rule": "install_file"}],
        ),
    ]
    out = stats_backfill(raw, cells)
    rules = {r["id"]: r for r in out["rules"]}
    assert rules["install_file"]["stats"]["fires"] == 3  # noqa: PLR2004 - 两格共3次
    assert rules["install_file"]["stats"]["rescued_cells"] == 1
    assert rules["install_file"]["stats"]["status_suggested"] == "active"
    assert rules["dead_rule"]["stats"]["fires"] == 0
    assert "status_suggested" not in rules["dead_rule"]["stats"]


def test_fixloop_writes_case_via_sink(tmp_path: Path) -> None:
    make_proj(tmp_path)
    path = tmp_path / "out" / "cases.jsonl"
    sink = CaseSink(path)
    fixloop(
        tmp_path,
        MockEngine([{"log": "! LaTeX Error: File `x.sty' not found.\n", "pdf": False}]),
        ruleset=rs(),
        corpus_id="corp",
        cond="zh",
        case_sink=sink,
    )
    cases = load_cases(path)
    assert len(cases) == 1
    assert cases[0]["corpus"] == "corp"
    assert cases[0]["cond"] == "zh"
    assert cases[0]["verdict"] == "unfixable:missing_file"
    assert cases[0]["log_excerpt"]


def test_fixloop_case_records_rules_declined(tmp_path: Path) -> None:
    """when 命中但拒修的规则物化 ``rules_declined``/``decline_notes``。

    ``rules_fired`` (actions 列) 的互补面：install_file 装不上 +
    vendored_fetch 查无件 → 两轮重复 decline 去重后各一条；
    已应用规则 (legacy_pkg_shim) 经 applied 闸在前, 不进拒修面。
    """
    make_proj(tmp_path)
    path = tmp_path / "out" / "cases.jsonl"
    fixloop(
        tmp_path,
        MockEngine([{"log": "! LaTeX Error: File `x.sty' not found.\n", "pdf": False}]),
        ruleset=rs(),
        corpus_id="corp",
        cond="zh",
        case_sink=CaseSink(path),
    )
    (cell,) = load_cases(path)
    assert cell["verdict"] == "unfixable:missing_file"
    assert "install_file" in cell["rules_declined"]
    assert "vendored_fetch" in cell["rules_declined"]
    assert len(cell["decline_notes"]) == len(set(cell["decline_notes"]))  # 跨轮去重
    fired = {a["rule"] for a in cell["actions"]}
    assert not (fired & set(cell["rules_declined"]))
