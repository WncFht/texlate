"""cases — cases.jsonl 沉淀 / triage / 回放三门 单测 (docs/spec/compile.md)。"""

from functools import lru_cache
from pathlib import Path

from texlate.compile.fixloop import CaseSink, Ruleset, load_cases, load_ruleset
from texlate.compile.fixloop.cases import (
    replay_all,
    replay_case,
    stats_backfill,
    triage,
)
from texlate.compile.fixloop.engine import fixloop


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO（坏 yaml 报 test fail 而非 collection error）。"""
    return load_ruleset()


MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n"
CLEAN_LOG = "This is pdfTeX\nOutput written on main.pdf (1 page).\n"


class _Res:
    def __init__(self, wdir: Path, main: str, log: str, *, pdf: bool) -> None:
        stem = Path(main).stem
        self.log_path = wdir / f"{stem}.log"
        self.log_path.write_text(log)
        self.pdf = wdir / f"{stem}.pdf" if pdf else None
        if self.pdf:
            self.pdf.write_bytes(b"%PDF-fake")
        self.pdf_bytes = self.pdf.stat().st_size if self.pdf else 0
        self.timed_out = False
        self.seconds = 0.01
        self.stdout_tail = ""

    @property
    def has_pdf(self) -> bool:
        return bool(self.pdf and self.pdf_bytes)


class _Eng:
    """script: (log, pdf) 序列。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr"})

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.n = 0

    def compile(self, wdir: Path, main: str, passes: int = 2, **_kw: object) -> _Res:
        del passes, _kw  # mock 不需要
        i = min(self.n, len(self.script) - 1)
        self.n += 1
        log, pdf = self.script[i]
        return _Res(Path(wdir), main, log, pdf=pdf)

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (Path(cwd) / fname).is_file():
            return str(Path(cwd) / fname)
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related  # mock 一律装不上
        return False

    def rebuild_fontmaps(self) -> bool:
        return True

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


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
    (tmp_path / "main.tex").write_text(L209_TEX)
    sink = CaseSink(tmp_path / "cases.jsonl")
    cell = fixloop(tmp_path, _Eng([(L209_LOG, False)]), ruleset=_rs(), case_sink=sink)
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
    (tmp_path / "main.tex").write_text(MAIN_TEX)
    case = {
        "corpus": "p",
        "cond": "c",
        "verdict": "unfixable:missing_file",
        "started_fail": True,
    }
    res = replay_case(case, tmp_path, _Eng([(CLEAN_LOG, True)]), _rs())
    assert res.verdict_after == "clean"
    assert res.gate1_rescued is True


def test_replay_case_fail_stays(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(MAIN_TEX)
    case = {"corpus": "p", "cond": "c", "verdict": "unfixable:x", "started_fail": True}
    eng = _Eng([("! Bizarre\n", False)])
    res = replay_case(case, tmp_path, eng, _rs())
    assert res.gate1_rescued is False
    assert res.verdict_after.startswith("unfixable")


def test_replay_all_gate2_regression(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(MAIN_TEX)
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
        engine_factory=lambda _c: _Eng([(CLEAN_LOG, True)]),
        ruleset=_rs(),
    )
    assert len(results) == 2  # noqa: PLR2004
    assert all(not r.regressed for r in results)
    assert results[1].gate1_rescued is True

    # 曾 clean 的格被改坏 → regressed (底板兜回入口 pdf 也算: 树死了)
    results = replay_all(
        [clean_case],
        resolve_proj=lambda _c: tmp_path,
        engine_factory=lambda _c: _Eng([("! File `x.sty' not found.\n", False)]),
        ruleset=_rs(),
    )
    assert results[0].regressed is True
    assert results[0].floor_restored is True
    assert results[0].verdict_after == "acceptable_pdf"


def test_replay_all_skips_missing_proj(tmp_path: Path) -> None:
    results = replay_all(
        [{"corpus": "ghost", "verdict": "unfixable:x"}],
        resolve_proj=lambda _c: tmp_path / "absent",
        engine_factory=lambda _c: _Eng([(CLEAN_LOG, True)]),
        ruleset=_rs(),
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
    (tmp_path / "main.tex").write_text(MAIN_TEX)
    path = tmp_path / "out" / "cases.jsonl"
    sink = CaseSink(path)
    fixloop(
        tmp_path,
        _Eng([("! LaTeX Error: File `x.sty' not found.\n", False)]),
        ruleset=_rs(),
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
    (tmp_path / "main.tex").write_text(MAIN_TEX)
    path = tmp_path / "out" / "cases.jsonl"
    fixloop(
        tmp_path,
        _Eng([("! LaTeX Error: File `x.sty' not found.\n", False)]),
        ruleset=_rs(),
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
