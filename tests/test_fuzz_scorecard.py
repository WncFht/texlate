"""verdict/scorecard 聚合面 fuzz——benchlib.verdict_sig / gate_scorecard / triage 归桶。

不变量清单（确定性 + 计数守恒 + 桶唯一）：

- ``verdict_sig``：同输入同 sig；``status ∈ {clean, None, 缺席}`` → 恒空
  sig；显式 category（非 None/clean/other）+ 真值 payload 下 reasons
  乱序/复制/first_error 均不改变 sig；派生 cat 取 reasons 头（顺序即语
  义，钉住）；``missing_character`` 出现在任一 reason 即压倒派生头；
  ``missing_character[×x]N`` → ``missing_character:xN``（x/× 同归一）；
  ``error_cats`` 构成在场时众数 cat 错误量严格大于首错 cat 则 sig 改挂
  众数（payload 取 ``error_pay`` 首见值），平票仍归首错。
- ``gate_scorecard.last_records``：同 str id 末行胜；非 str/空 id 丢弃；
  upstream 缺失/None/空串按 mock；arm_mismatch 错误行剔除。
- ``pick_final`` 真值表封闭：fix 接管 iff c.status∈COMPILED ∧ upstream
  相容 ∧ 新鲜度过门——``metrics.compile_fp`` 为真值 str 时按指纹比对
  （同态陈旧拦 ``fp_mismatch``），否则回退 ``compile_status_before``
  状态等值（``no_csb``/``stale``）；drop_reason ∈ {None,
  over_noncompiled, no_csb, stale, fp_mismatch, upstream_mismatch}。
- ``compile_fp``：同记录同指纹；status/sig/first_error/code 变 → 变；
  计时字段(seconds/dur_s)变 → 不变；脏 metrics 不崩。
- ``gate_scorecard.main``：Σ end == cells；pdf ≤ cells；clean ≤ pdf；
  need = max(0, ceil(0.9·total − pdf − ε))。union 口径：Σ uni == cells；
  union_pdf ≥ end_pdf ∧ union_clean ≥ end_clean（best-of ≥ 末段胜）。
- ``--json``：stdout 可被 ``json.loads`` 消化；两口径 dist 各自守恒。
- ``triage.load_records``：守恒——输出行数 == Σ 文件（唯一 (id,arm,
  upstream) 键数 + 无 id dict 行数）；同键末条胜；非 dict/坏 json/截尾
  UTF-8 行跳过；stage 缺省取文件名。
- ``record_sig``/``build_tickets``：每记录恰归一 (stage,sig) 桶；
  Σ count == 非豁免记录数（ok/skip 无 sig 无 errors 豁免 + upstream 门
  skip 豁免）；票按 (-count,stage,signature) 排序；sig_id 唯一；
  example_ids ≤ MAX_EXAMPLES 去重保序。
- ``compute_metrics``：逐 cell Σ by_status == total；ok ≤ total；skip ≤
  total；rescued ≤ attempted；rate ∈ [0,1]；pipeline_introduced ⊆
  compile zh 非 ok/skip/error ∧ base ok 的 id。
- 真实 records 变异回放：字段值级变异下聚合不崩且守恒。
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import benchlib
import gate_scorecard
import pytest
import triage
from _fuzzkit import fuzz_rng

if TYPE_CHECKING:
    import random

_SEED = 20260917
_ITERS = 300
_N_CELLS = 200
_SAMPLE_PER_FILE = 80
_SAMPLE_CAP = 400
_GATE_SAMPLE = 150
_RESULTS = Path(__file__).resolve().parents[1] / "bench" / "results"

# ---------------------------------------------------------------- pools
_VSTATUS = ["clean", "fail", "partial", "reject", "other"]
_VCAT = [
    None,
    "clean",
    "other",
    "missing_file",
    "missing_character",
    "undefined_cs",
    "syntax",
    "babel_opt",
    "illegal_unit",
    "warn",
    "capacity",
]
_REASON_TOK = [
    "no_pdf",
    "missing_character×3",
    "missing_characterx12",
    "first_error=syntax: brace mismatch",
    "first_error=missing_file: gone",
    "cjk_chars=0",
    "errors>3",
    "warn:invalid_utf8",
    "nullfont_misschar",
    "",
    "   ",
]
_PAYLOAD = [None, "", "aastex.cls", "x.sty", "pst-node", "实", 0, 17]
_FIRST_ERROR = [
    None,
    "",
    "! LaTeX Error: File `aastex.cls' not found.",
    "File `uft8.def' not found",
    "! Undefined control sequence.",
    "Missing character: There is no 实 in font",
]
_REC_STATUS = [
    "ok",
    "clean",
    "done",
    "fail",
    "partial",
    "skip",
    "skipped",
    "reject",
    "rejected",
    "upstream_fail",
    "error",
    "bench_error",
    "skipped_oversize",
    "stuck",
    "max_rounds",
    "acceptable_pdf",
    "best_effort_pdf",
    "dirty_pdf",
    "unfixable:x",
    "",
    "?",
]
_SIG_POOL = [
    "",
    "missing_file:aastex.cls",
    "missing_character:x4",
    "missing_character",
    "undefined_cs:\\foo",
    "syntax",
    "unfixable:missing_file:pst-node",
    "upstream:parse=reject",
    "inject:latex209",
    "xlat:fault=3 skipped=0",
    "harness:BrokenProcessPool",
    "nosig:fail",
    "verdict:fail",
    "stub_format:a.gz",
    "auth:401",
    "warn:invalid_utf8",
    "a:b:c",
    ":",
]
_ERRORS_POOL = [
    [],
    [{"code": "upstream_gate", "cat": "upstream", "payload": "parse=reject"}],
    [{"code": "missing_file", "cat": "missing_file", "payload": "a.cls"}],
    [{"code": "leftover_ph", "cat": "xlat", "payload": "3"}],
    [{"code": "chunks_bad", "cat": "xlat", "payload": "fault=2 skipped=1"}],
    [{"code": "auth", "cat": "auth", "payload": "401"}],
    [{"code": "harness:Broken", "cat": "harness", "payload": "Broken('x')"}],
    [{"code": "unfixable:syntax", "cat": None, "payload": ""}],
    ["non-dict-entry"],
]
_MUT_SCALAR = [None, "", 0, 5, -1, 1.5, "abc", "实", "x" * 300, [], {}, {"k": 1}]


def _rand_verdict(rng: random.Random) -> dict:
    return {
        "status": rng.choice(_VSTATUS),
        "category": rng.choice(_VCAT),
        "payload": rng.choice(_PAYLOAD),
        "reasons": [rng.choice(_REASON_TOK) for _ in range(rng.randrange(4))],
    }


def _rec(pid: str, stage: str, status: object, **over: object) -> dict:
    r = {
        "id": pid,
        "stage": stage,
        "arm": "-",
        "upstream": "",
        "status": status,
        "dur_s": 1.0,
        "metrics": {},
        "errors": [],
        "sig": "",
    }
    r.update(over)
    return r


def _write_jsonl(path: Path, rows: list) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False))
            f.write("\n")


# ================================================================ verdict_sig
def test_verdict_sig_deterministic() -> None:
    """等值输入（json 深拷贝）→ 同 sig；返回恒为 str。"""
    rng = fuzz_rng(_SEED)
    for _ in range(_ITERS):
        v = _rand_verdict(rng)
        fe = rng.choice(_FIRST_ERROR)
        s1 = benchlib.verdict_sig(v, fe)
        s2 = benchlib.verdict_sig(json.loads(json.dumps(v)), fe)
        assert isinstance(s1, str)
        assert s1 == s2


def test_verdict_sig_clean_blackout() -> None:
    """status clean/None/缺席 → 恒空 sig，其余字段噪声免疫。"""
    rng = fuzz_rng(_SEED + 1)
    for _ in range(_ITERS):
        v = _rand_verdict(rng)
        pick = rng.randrange(3)
        if pick == 0:
            v["status"] = "clean"
        elif pick == 1:
            v["status"] = None
        else:
            v.pop("status", None)
        assert benchlib.verdict_sig(v, rng.choice(_FIRST_ERROR)) == ""


def test_verdict_sig_explicit_cat_reason_order_insensitive() -> None:
    """显式 cat + 真值 str payload → sig == cat:payload，reasons/first_error 无关。"""
    rng = fuzz_rng(_SEED + 2)
    for _ in range(_ITERS):
        cat = rng.choice(["missing_file", "undefined_cs", "syntax", "babel_opt"])
        pay = rng.choice(["a.cls", "x.sty", "\\foo", "实"])
        reasons = [rng.choice(_REASON_TOK) for _ in range(rng.randrange(1, 4))]
        v = {
            "status": "fail",
            "category": cat,
            "payload": pay,
            "reasons": reasons,
        }
        want = f"{cat}:{pay}".rstrip(":")
        assert benchlib.verdict_sig(v, rng.choice(_FIRST_ERROR)) == want
        v2 = dict(v, reasons=[*reversed(reasons), *reasons])
        assert benchlib.verdict_sig(v2, rng.choice(_FIRST_ERROR)) == want


def test_verdict_sig_derived_head_order_sensitive() -> None:
    """派生 cat 取 reasons 头——乱序改 sig（语义钉住：顺序即信息，非缺陷）。

    missing_character 是例外：出现在任一 reason 即压倒派生头。
    """
    v = {
        "status": "fail",
        "category": None,
        "reasons": ["first_error=syntax: x", "warn:y"],
    }
    v2 = {
        "status": "fail",
        "category": None,
        "reasons": ["warn:y", "first_error=syntax: x"],
    }
    assert benchlib.verdict_sig(v) == "syntax"
    # head 整 token 作 cat（含冒号原样保留）
    assert benchlib.verdict_sig(v2) == "warn:y"
    for tail in ([], ["warn:y"], ["first_error=syntax: x"]):
        v3 = {
            "status": "fail",
            "category": None,
            "reasons": [*tail, "missing_character×7"],
        }
        assert benchlib.verdict_sig(v3) == "missing_character:x7"


def test_verdict_sig_mc_count_norm() -> None:
    """``missing_character[×x]N`` → ``xN``；前导零不归一（x03 ≠ x3）；
    显式 payload 压正则回补。"""
    for tok, want in (
        ("missing_character×3", "x3"),
        ("missing_characterx3", "x3"),
        ("missing_character×18", "x18"),
        ("missing_character×03", "x03"),
    ):
        v = {"status": "fail", "category": None, "reasons": [tok]}
        assert benchlib.verdict_sig(v) == f"missing_character:{want}"
    v = {
        "status": "fail",
        "category": "missing_character",
        "payload": "实",
        "reasons": ["missing_character×3"],
    }
    assert benchlib.verdict_sig(v) == "missing_character:实"


def test_verdict_sig_first_error_regex_fill() -> None:
    """missing_file/missing_character payload 空 → 正则回补 payload。"""
    v = {
        "status": "fail",
        "category": "missing_file",
        "payload": None,
        "reasons": ["no_pdf"],
    }
    fe = "! LaTeX Error: File `x.cls' not found."
    assert benchlib.verdict_sig(v, fe) == "missing_file:x.cls"
    assert benchlib.verdict_sig(v, "no match") == "missing_file"
    assert benchlib.verdict_sig(v, "") == "missing_file"
    assert benchlib.verdict_sig(v) == "missing_file"
    # 显式 missing_character + 空 payload → joined reasons 正则（首个匹配胜
    # ——多计数 reason 时顺序仍敏感，沿用派生头语义）
    v2 = {
        "status": "fail",
        "category": "missing_character",
        "payload": "",
        "reasons": ["missing_character×2", "missing_character×9"],
    }
    assert benchlib.verdict_sig(v2) == "missing_character:x2"


def test_verdict_sig_edge_shapes() -> None:
    """边界形状不崩：空 verdict、空 reasons、tuple reasons、falsy cat。"""
    assert benchlib.verdict_sig({}) == ""
    assert benchlib.verdict_sig({"status": "fail", "reasons": []}) == "verdict:fail"
    assert benchlib.verdict_sig({"status": "fail", "category": ""}) == "verdict:fail"
    sig = benchlib.verdict_sig(
        {"status": "fail", "category": None, "reasons": ("warn:y",)}
    )
    assert isinstance(sig, str)


@pytest.mark.parametrize(
    "bad_fe", [{"f": 1}, ["x"], 5, True], ids=["dict", "list", "int", "bool"]
)
def test_verdict_sig_nonstr_first_error(bad_fe: object) -> None:
    v = {
        "status": "fail",
        "category": "missing_file",
        "payload": None,
        "reasons": ["no_pdf"],
    }
    assert benchlib.verdict_sig(v, bad_fe).startswith("missing_file")


@pytest.mark.parametrize("bad_reasons", [5, 3.14, True], ids=["int", "float", "bool"])
def test_verdict_sig_noniterable_reasons(bad_reasons: object) -> None:
    v = {"status": "fail", "category": None, "reasons": bad_reasons}
    assert isinstance(benchlib.verdict_sig(v), str)


def test_verdict_sig_string_reasons() -> None:
    v = {"status": "fail", "category": None, "reasons": "missing_character×3"}
    sig = benchlib.verdict_sig(v)
    # 两种合理修法都接受：按单条 reason 解析 / 拒绝非 list 退 verdict:fail
    assert sig in {"missing_character:x3", "verdict:fail"}


def test_verdict_sig_bulk_dominant_override() -> None:
    """首错遮 bulk 纠偏：众数 cat 错误量严格大于首错 → sig 挂众数。

    quant-ph/9703040 实证锚点：110 错中 108 syntax（Missing number
    行裸分类落 syntax），category 却是自恢复的 illegal_unit——首错
    sig 会误导分桶归因。
    """
    v = {
        "status": "fail",
        "category": "illegal_unit",
        "payload": "24ptA",
        "error_cats": {"illegal_unit": 1, "syntax": 108},
    }
    assert benchlib.verdict_sig(v) == "syntax"


def test_verdict_sig_bulk_dominant_pay() -> None:
    """众数 payload 取 error_pay 首见值（缺失/非 str → 裸 cat）。"""
    v = {
        "status": "fail",
        "category": "illegal_unit",
        "error_cats": {"illegal_unit": 1, "missing_file": 3},
        "error_pay": {"missing_file": "aa.sty"},
    }
    assert benchlib.verdict_sig(v) == "missing_file:aa.sty"
    v2 = {**v, "error_pay": {"missing_file": 5}}
    assert benchlib.verdict_sig(v2) == "missing_file"
    v3 = {k: x for k, x in v.items() if k != "error_pay"}
    assert benchlib.verdict_sig(v3) == "missing_file"


def test_verdict_sig_bulk_tie_keeps_first() -> None:
    """平票仍归首错——TeX 级联中首错是因果上游，等量不翻案。"""
    v = {
        "status": "fail",
        "category": "illegal_unit",
        "payload": "24ptA",
        "error_cats": {"illegal_unit": 1, "syntax": 1},
    }
    assert benchlib.verdict_sig(v) == "illegal_unit:24ptA"


def test_verdict_sig_bulk_same_cat_noop() -> None:
    """众数==首错 cat → sig 不变（payload 仍取 verdict.payload 权威对）。"""
    v = {
        "status": "fail",
        "category": "undefined_cs",
        "payload": "\\x",
        "error_cats": {"undefined_cs": 5, "other": 2},
    }
    assert benchlib.verdict_sig(v) == "undefined_cs:\\x"


def test_verdict_sig_bulk_malformed_cats() -> None:
    """error_cats 非 dict/脏键值 → 回退首错路径不崩。"""
    v = {"status": "fail", "category": "illegal_unit"}
    assert benchlib.verdict_sig({**v, "error_cats": "junk"}) == "illegal_unit"
    v2 = {**v, "error_cats": {5: 3, "ok": "x", None: 1, "z": True}}
    assert benchlib.verdict_sig(v2) == "illegal_unit"


def test_verdict_sig_bulk_clean_blackout() -> None:
    """clean/无 status 下 error_cats 也不出 sig。"""
    assert benchlib.verdict_sig({"status": "clean", "error_cats": {"x": 5}}) == ""


def test_verdict_sig_bulk_meta_cat_no_override() -> None:
    """derived meta 词不在错误行构成中 → 众数无权顶包（wave4 MED 回归钉）。

    category 缺席/other 时 cat 由 reasons 派生——killed_by_signal/no_pdf/
    missing_character 是 verdict 级归因而非错误行 cat，``bulk.get(cat,0)``
    恒 0 会让任意众数把根因桶洗成级联错桶（信号杀死被 syntax 顶包正是
    本 feature 意图的反面）。
    """
    killed = {
        "status": "fail",
        "category": "other",
        "reasons": ["killed_by_signal:9", "no_pdf"],
        "error_cats": {"syntax": 40},
    }
    assert benchlib.verdict_sig(killed) == "killed_by_signal:9"
    nopdf = {
        "status": "fail",
        "reasons": ["no_pdf"],
        "error_cats": {"undefined_cs": 7},
    }
    assert benchlib.verdict_sig(nopdf) == "no_pdf"
    mc = {
        "status": "partial",
        "reasons": ["missing_character×3"],
        "error_cats": {"undefined_cs": 5},
    }
    assert benchlib.verdict_sig(mc) == "missing_character:x3"


def test_verdict_sig_bulk_derived_first_error_still_competes() -> None:
    """derived ``first_error=X`` 的 X 是真错误行 cat——在构成中照常纠偏。"""
    v = {
        "status": "fail",
        "category": "other",
        "reasons": ["first_error=syntax:\\foo"],
        "error_cats": {"syntax": 1, "undefined_cs": 9},
        "error_pay": {"undefined_cs": "\\bad"},
    }
    assert benchlib.verdict_sig(v) == "undefined_cs:\\bad"


# ================================================================ gate_scorecard
def test_gate_last_records_filters(tmp_path: Path) -> None:
    """末行胜 + arm/upstream/arm_mismatch/id 过滤矩阵（输出行数可预言）。"""
    rows = [
        {"id": "a", "arm": "zh", "status": "fail"},
        {"id": "a", "arm": "zh", "status": "clean"},  # 末条胜
        {"id": "a", "arm": "base", "status": "fail"},  # arm 过滤
        {"id": "b", "arm": "zh", "status": "fail", "upstream": "real"},
        {
            "id": "c",
            "arm": "zh",
            "status": "fail",
            "errors": [{"code": "arm_mismatch"}],
        },
        {"id": 5, "arm": "zh", "status": "fail"},  # 非 str id 丢
        {"id": "", "arm": "zh", "status": "fail"},  # 空 id 丢
        {"id": None, "arm": "zh", "status": "fail"},  # None id 丢
        "{broken json",  # 坏行跳过
        "",
        {},  # 空 dict 行：无 id → 丢
        {"id": "d", "arm": "zh", "status": "fail", "upstream": None},
        {"id": "e", "arm": "zh", "status": "fail", "upstream": ""},
    ]
    _write_jsonl(tmp_path / "compile.jsonl", rows)
    last = gate_scorecard.last_records(
        tmp_path / "compile.jsonl", arm="zh", upstream="mock"
    )
    assert sorted(last) == ["a", "d", "e"]
    assert last["a"]["status"] == "clean"
    # upstream=None 全收（除 arm_mismatch/坏 id/坏 json）
    last_all = gate_scorecard.last_records(
        tmp_path / "compile.jsonl", arm="zh", upstream=None
    )
    assert sorted(last_all) == ["a", "b", "d", "e"]
    last_real = gate_scorecard.last_records(
        tmp_path / "compile.jsonl", arm="zh", upstream="real"
    )
    assert sorted(last_real) == ["b"]


def test_gate_last_records_fuzz_conservation(tmp_path: Path) -> None:
    """随机行流 → 输出行数 == 去重后可预言数；每个存活 id 取末行。"""
    rng = fuzz_rng(_SEED + 10)
    rows: list = []
    oracle: dict[str, dict] = {}
    for i in range(_ITERS):
        pid = rng.choice(["a", "b", "c", "d", "e", "5", "", None])
        r = {
            "id": pid,
            "arm": rng.choice(["zh", "zh", "zh", "base"]),
            "status": rng.choice(_REC_STATUS),
            "upstream": rng.choice(["mock", "mock", "real", "", None]),
            "errors": rng.choice([[], [{"code": "arm_mismatch"}]]),
            "n": i,
        }
        rows.append(r)
        # mock 口径 oracle 独立复算
        if (
            r["arm"] == "zh"
            and (r["upstream"] or "mock") == "mock"
            and not any(e.get("code") == "arm_mismatch" for e in r["errors"])
            and isinstance(pid, str)
            and pid
        ):
            oracle[pid] = r
    _write_jsonl(tmp_path / "compile.jsonl", rows)
    last = gate_scorecard.last_records(
        tmp_path / "compile.jsonl", arm="zh", upstream="mock"
    )
    assert len(last) == len(oracle)
    for pid, r in oracle.items():
        assert last[pid]["n"] == r["n"]


def test_pick_final_truth_table() -> None:
    """drop_reason 封闭 + 终态 record 归属（compile/fixloop）。"""
    f_base = {
        "id": "p",
        "status": "clean",
        "metrics": {"compile_status_before": "fail"},
    }
    # 与循环内 _rec("p","compile","fail",upstream="u1") 同形的指纹
    fp_hit = gate_scorecard.compile_fp(_rec("p", "compile", "fail", upstream="u1"))
    cases = [
        # (c_status, fix 记录, 期望 stage, 期望 drop)
        ("fail", None, "compile", None),
        ("reject", f_base, "compile", "over_noncompiled"),
        ("skip", f_base, "compile", "over_noncompiled"),
        ("error", f_base, "compile", "over_noncompiled"),
        ("fail", {"id": "p", "status": "clean"}, "compile", "no_csb"),
        ("fail", {"id": "p", "status": "clean", "metrics": {}}, "compile", "no_csb"),
        (
            "fail",
            {
                "id": "p",
                "status": "clean",
                "metrics": {"compile_status_before": "partial"},
            },
            "compile",
            "stale",
        ),
        (
            "fail",
            {
                "id": "p",
                "status": "clean",
                "metrics": {"compile_status_before": "fail"},
                "upstream": "u2",
            },
            "compile",
            "upstream_mismatch",
        ),
        ("fail", f_base, "fixloop", None),
        ("fail", {**f_base, "upstream": ""}, "fixloop", None),  # 单侧空不判
        # compile_fp 指纹路径：匹配接管 / 失配 fp_mismatch / 匹配仍查 upstream
        (
            "fail",
            {"id": "p", "status": "clean", "metrics": {"compile_fp": fp_hit}},
            "fixloop",
            None,
        ),
        (
            "fail",
            {"id": "p", "status": "clean", "metrics": {"compile_fp": "f" * 16}},
            "compile",
            "fp_mismatch",
        ),
        (
            "fail",
            {
                "id": "p",
                "status": "clean",
                "upstream": "u2",
                "metrics": {"compile_fp": fp_hit},
            },
            "compile",
            "upstream_mismatch",
        ),
    ]
    for c_status, f, want_stage, want_drop in cases:
        c = _rec("p", "compile", c_status, upstream="u1")
        stage, r, drop = gate_scorecard.pick_final(c, f)
        assert stage == want_stage, (c_status, f)
        assert drop == want_drop, (c_status, f)
        assert r is (f if stage == "fixloop" else c)


def _gate_run(
    tmp_path: Path,
    comp_rows: list,
    fix_rows: list,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int | None, int | None, int | None, str]:
    """写 records 跑 main() → (cells, pdf, clean, stdout)。"""
    recdir = tmp_path / "records"
    recdir.mkdir(exist_ok=True)
    _write_jsonl(recdir / "compile.jsonl", comp_rows)
    _write_jsonl(recdir / "fixloop.jsonl", fix_rows)
    monkeypatch.setattr(sys, "argv", ["gate_scorecard", str(recdir)])
    assert gate_scorecard.main() == 0
    out = capsys.readouterr().out
    head = next((x for x in out.splitlines() if x.startswith("cells=")), "")
    cells = pdf = clean = None
    if head:
        vals = {
            k: int(v) for p in head.split() if "=" in p for k, v in [p.split("=", 1)]
        }
        cells = vals["cells"]
        pdf = vals.get("pdf")
        clean = vals.get("clean")
    return cells, pdf, clean, out


def test_gate_main_conservation_fuzz(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """随机 compile/fixloop 格 → Σ end == cells ∧ pdf ≤ cells ∧ clean ≤ pdf。

    终态按 pick_final 文档语义独立复算（csb 匹配 + upstream 相容才接管）。
    """
    rng = fuzz_rng(_SEED + 11)
    comp_rows: list = []
    fix_by_id: dict[str, dict] = {}
    for i in range(_N_CELLS):
        pid = f"p{i}"
        cst = rng.choice(["clean", "partial", "fail", "reject", "skip"])
        comp_rows.append({"id": pid, "arm": "zh", "upstream": "mock", "status": cst})
        if rng.randrange(3):
            continue  # 无 fixloop 记录
        csb = rng.choice([cst, "fail", "partial", None])
        f: dict = {
            "id": pid,
            "upstream": rng.choice(["mock", "real", ""]),
            "status": rng.choice(_REC_STATUS),
        }
        if csb is not None or rng.randrange(2):
            f["metrics"] = {} if csb is None else {"compile_status_before": csb}
        fix_by_id[pid] = f
    exp_end: Counter = Counter()
    for c in comp_rows:
        end_stage, end_status = "compile", c["status"] or "?"
        f = fix_by_id.get(c["id"])
        if f is not None and c["status"] in gate_scorecard.COMPILED:
            csb = (f.get("metrics") or {}).get("compile_status_before")
            cu, fu = c.get("upstream"), f.get("upstream")
            if csb == c["status"] and not (cu and fu and cu != fu):
                end_stage = "fixloop"
                end_status = f["status"] or "?"
        exp_end[f"{end_stage}:{end_status}"] += 1
    cells, pdf, clean, _out = _gate_run(
        tmp_path, comp_rows, list(fix_by_id.values()), capsys, monkeypatch
    )
    assert cells == _N_CELLS
    assert pdf == sum(
        v for k, v in exp_end.items() if k.split(":")[1] in ("clean", "partial")
    )
    assert clean == sum(v for k, v in exp_end.items() if k.split(":")[1] == "clean")
    assert clean <= pdf <= cells


@pytest.mark.parametrize(
    "case",
    [
        (10, 9, "PASS"),  # 恰门槛
        (10, 8, "need +1"),
        (3, 2, "need +1"),
        (100, 90, "PASS"),
        (7, 6, "need +1"),  # 6.3 → need 1（ceil 后 6+1=7 ≥ 6.3）
    ],
    ids=["exact90", "below", "small", "exact100", "ceil_edge"],
)
def test_gate_boundary_need(
    case: tuple[int, int, str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """need = max(0, ceil(0.9·total − pdf − ε))——门槛边界不漂。"""
    n_total, n_pdf, want = case
    comp_rows = [
        {
            "id": f"p{i}",
            "arm": "zh",
            "upstream": "mock",
            "status": "clean" if i < n_pdf else "fail",
        }
        for i in range(n_total)
    ]
    _cells, _pdf, _clean, out = _gate_run(tmp_path, comp_rows, [], capsys, monkeypatch)
    assert want in out


def test_gate_last_records_truncated_utf8(tmp_path: Path) -> None:
    p = tmp_path / "compile.jsonl"
    p.write_bytes(b'{"id":"a","arm":"zh","status":"fail"}\n{"id":"b","\xe4\xb8')
    last = gate_scorecard.last_records(p, arm="zh", upstream="mock")
    assert list(last) == ["a"]


@pytest.mark.parametrize(
    "line",
    ["5", '"id"', "[1,2]", "null", "3.14", "true"],
    ids=["int", "str", "list", "null", "float", "bool"],
)
def test_gate_last_records_nondict_line(tmp_path: Path, line: str) -> None:
    p = tmp_path / "compile.jsonl"
    p.write_text(
        f'{line}\n{{"id":"a","arm":"zh","status":"clean"}}\n', encoding="utf-8"
    )
    last = gate_scorecard.last_records(p, arm="zh", upstream="mock")
    assert list(last) == ["a"]


@pytest.mark.parametrize(
    "errs",
    [["x"], [5], [None], "arm_mismatch", [{"code": "ok"}, "x"]],
    ids=["str", "int", "none", "errors_str", "mixed_tail"],
)
def test_gate_errors_nondict(tmp_path: Path, errs: object) -> None:
    p = tmp_path / "compile.jsonl"
    rec = {"id": "a", "arm": "zh", "status": "clean", "errors": errs}
    p.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    last = gate_scorecard.last_records(p, arm="zh", upstream="mock")
    assert list(last) == ["a"]


@pytest.mark.parametrize(
    "bad_metrics", ["x", [1], 5, True], ids=["str", "list", "int", "bool"]
)
def test_pick_final_nondict_metrics(bad_metrics: object) -> None:
    c = _rec("p", "compile", "fail")
    f = {"id": "p", "status": "clean", "metrics": bad_metrics}
    stage, _r, drop = gate_scorecard.pick_final(c, f)
    # 合理终态：metrics 视为缺 → no_csb（compile 自留）
    assert (stage, drop) == ("compile", "no_csb")


# ---------------------------------------------------------------- 指纹校验
def test_compile_fp_stability() -> None:
    """指纹确定性 + 同态陈旧敏感 + 计时噪声免疫。"""
    c = _rec(
        "p",
        "compile",
        "fail",
        sig="syntax:x",
        code="abc123",
        metrics={
            "compile": {"first_error": "! brace", "seconds": 1.5},
            "verdict": {"category": "syntax", "payload": "b"},
        },
    )
    fp = gate_scorecard.compile_fp(c)
    assert fp == gate_scorecard.compile_fp(json.loads(json.dumps(c)))
    # 同 status 异 sig/first_error → 指纹变（status 等值放行的盲区即此）
    c2 = json.loads(json.dumps(c))
    c2["sig"] = "missing_file:a.cls"
    assert gate_scorecard.compile_fp(c2) != fp
    c3 = json.loads(json.dumps(c))
    c3["metrics"]["compile"]["first_error"] = "! other"
    assert gate_scorecard.compile_fp(c3) != fp
    # 计时字段非 verdict 语义——seconds/dur_s 变而指纹不变
    c4 = json.loads(json.dumps(c))
    c4["metrics"]["compile"]["seconds"] = 99
    c4["dur_s"] = 42.0
    assert gate_scorecard.compile_fp(c4) == fp
    c5 = json.loads(json.dumps(c))
    c5["status"] = "partial"
    assert gate_scorecard.compile_fp(c5) != fp
    # 脏输入面：metrics 非 dict / 空记录 → 不崩仍出摘要
    assert isinstance(
        gate_scorecard.compile_fp(_rec("p", "compile", "fail", metrics="junk")),
        str,
    )
    assert isinstance(gate_scorecard.compile_fp({}), str)


def test_pick_final_fingerprint_path() -> None:
    """``compile_fp`` 在场 → 指纹级校验：匹配接管 / 不匹配 ``fp_mismatch``。

    同态陈旧锚点：compile 重跑 status 不变 sig 已换——csb 等值放行而
    指纹拦下。fp 非 str/空值 → 视为缺席回退 legacy csb 路径。
    """
    c = _rec("p", "compile", "fail", sig="syntax:brace", code="abc")
    good = {
        "id": "p",
        "status": "clean",
        "metrics": {"compile_fp": gate_scorecard.compile_fp(c)},
    }
    stage, r, drop = gate_scorecard.pick_final(c, good)
    assert (stage, drop) == ("fixloop", None)
    assert r is good
    bad = {
        "id": "p",
        "status": "clean",
        "metrics": {"compile_fp": "f" * 16},
    }
    assert gate_scorecard.pick_final(c, bad)[:2] == ("compile", c)
    assert gate_scorecard.pick_final(c, bad)[2] == "fp_mismatch"
    # 同态陈旧：status 仍 fail 但 sig 已换 → 旧指纹不匹配即拦
    c2 = dict(c, sig="missing_file:a.cls")
    assert gate_scorecard.pick_final(c2, good)[2] == "fp_mismatch"
    for junk in (5, None, "", [], {}, True):
        f = {
            "id": "p",
            "status": "clean",
            "metrics": {"compile_fp": junk, "compile_status_before": "fail"},
        }
        assert gate_scorecard.pick_final(c, f)[0] == "fixloop", junk


def test_gate_union_best_of(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """union=best-of：fix 回退格(c partial→post fail) union 记 partial 而
    end-state 记 fail——两口径读数差即 fixloop 回退面。"""
    recdir = tmp_path / "records"
    recdir.mkdir()
    comp = [
        {"id": "a", "arm": "zh", "upstream": "mock", "status": "partial"},
        {"id": "b", "arm": "zh", "upstream": "mock", "status": "fail"},
    ]
    fix = [
        {
            "id": "a",
            "status": "fail",
            "upstream": "mock",
            "metrics": {"compile_status_before": "partial", "floor_restored": True},
        },
        {
            "id": "b",
            "status": "clean",
            "upstream": "mock",
            "metrics": {"compile_status_before": "fail"},
        },
    ]
    _write_jsonl(recdir / "compile.jsonl", comp)
    _write_jsonl(recdir / "fixloop.jsonl", fix)
    monkeypatch.setattr(sys, "argv", ["gate_scorecard", str(recdir), "--json"])
    assert gate_scorecard.main() == 0
    d = json.loads(capsys.readouterr().out)
    assert d["schema"] == "gate_scorecard/v3"
    assert d["cells"] == len(comp)
    # a: end=fixloop:fail(回退)，union=compile partial → pdf；b: fix clean
    want_end_pdf, want_uni_pdf = 1, 2
    assert d["end_state"]["pdf"] == want_end_pdf
    assert d["end_state"]["clean"] == want_end_pdf
    assert d["union"]["pdf"] == want_uni_pdf
    assert d["union"]["clean"] == want_end_pdf
    assert d["lift"] == {
        "cells": 1,
        "pdf": 1,
        "clean": 0,
        "transitions": {"partial->fail": 1},
    }
    assert d["union"]["source"] == {"compile": 1, "fixloop": 1}
    assert d["csb_check"] == {"legacy_status": len(comp)}
    # a: fix 底板兜回(pdf 文件在盘)但 post 仍判 fail → 虚低面计数
    assert d["floor_restored"] == 1
    assert d["floor_restored_nopdf"] == 1
    # 文本面也出两口径（regression：名实不符即旧版把末段胜印成 union）
    monkeypatch.setattr(sys, "argv", ["gate_scorecard", str(recdir)])
    assert gate_scorecard.main() == 0
    out = capsys.readouterr().out
    assert "union:" in out
    assert "[end-state]" in out
    assert "partial->fail" in out


def _oracle_fresh(c: dict, f: dict) -> bool:
    """pick_final 新鲜度判定的独立 oracle——post/fp/csb/upstream 四闸。

    与 pick_final 同构（window_stale 是调用侧注入——无 run_meta 空集，
    oracle 不复制）：post.status 相悖 / fp 失配 / fp 匹配但 csb 相悖 /
    无 fp 时 csb 缺席或失配 → 不新鲜。
    """
    if c["status"] not in gate_scorecard.COMPILED:
        return False
    m = f.get("metrics")
    if not isinstance(m, dict):
        m = {}
    post = m.get("post")
    if isinstance(post, dict):
        ps = post.get("status")
        if isinstance(ps, str) and ps and ps != f.get("status"):
            return False
    fp = m.get("compile_fp")
    if isinstance(fp, str) and fp:
        if fp != gate_scorecard.compile_fp(c):
            return False
        csb = m.get("compile_status_before")
        if csb is not None and csb != c["status"]:
            return False
    else:
        csb = m.get("compile_status_before")
        if csb is None or csb != c["status"]:
            return False
    cu, fu = c.get("upstream"), f.get("upstream")
    return not (cu and fu and cu != fu)


def _rand_fix(rng: random.Random, c: dict) -> dict:
    """随机 fixloop 记录：csb 三态 + compile_fp 三态（真值/错值/垃圾）。"""
    f: dict = {
        "id": c["id"],
        "upstream": rng.choice(["mock", "real", ""]),
        "status": rng.choice(_REC_STATUS),
    }
    m: dict = {}
    csb = rng.choice([c["status"], "fail", "partial", None])
    if csb is not None or rng.randrange(2):
        m["compile_status_before"] = csb
    fp_kind = rng.choice(["hit", "miss", "junk", "absent"])
    if fp_kind == "hit":
        m["compile_fp"] = gate_scorecard.compile_fp(c)
    elif fp_kind == "miss":
        m["compile_fp"] = "f" * 16
    elif fp_kind == "junk":
        m["compile_fp"] = rng.choice([5, None, "", []])
    if m:
        f["metrics"] = m
    return f


def test_gate_union_conservation_fuzz(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """union 口径 fuzz 守恒：Σuni==cells ∧ union_pdf ≥ end_pdf ∧
    union_clean ≥ end_clean；逐格 union rank ≥ end rank。"""
    rng = fuzz_rng(_SEED + 41)
    comp_rows: list = []
    fix_by_id: dict[str, dict] = {}
    for i in range(_N_CELLS):
        pid = f"p{i}"
        cst = rng.choice(["clean", "partial", "fail", "reject", "skip"])
        comp_rows.append(
            {
                "id": pid,
                "arm": "zh",
                "upstream": "mock",
                "status": cst,
                "sig": rng.choice(_SIG_POOL),
            }
        )
        if not rng.randrange(3):
            fix_by_id[pid] = _rand_fix(rng, comp_rows[-1])
    exp_end: Counter = Counter()
    exp_uni: Counter = Counter()
    for c in comp_rows:
        end_stage, end_status = "compile", c["status"] or "?"
        f = fix_by_id.get(c["id"])
        uni_status = c["status"] or "?"
        if f is not None and _oracle_fresh(c, f):
            end_stage, end_status = "fixloop", f["status"] or "?"
            fs = f["status"] or "?"
            if benchlib.STATUS_RANK.get(str(fs), -1) > benchlib.STATUS_RANK.get(
                str(c["status"] or "?"), -1
            ):
                uni_status = fs
        exp_end[(end_stage, end_status)] += 1
        exp_uni[uni_status] += 1
    recdir = tmp_path / "records"
    recdir.mkdir()
    _write_jsonl(recdir / "compile.jsonl", comp_rows)
    _write_jsonl(recdir / "fixloop.jsonl", list(fix_by_id.values()))
    monkeypatch.setattr(sys, "argv", ["gate_scorecard", str(recdir), "--json"])
    assert gate_scorecard.main() == 0
    d = json.loads(capsys.readouterr().out)
    assert d["cells"] == _N_CELLS
    assert sum(d["end_state"]["dist"].values()) == _N_CELLS
    assert sum(d["union"]["dist"].values()) == _N_CELLS
    assert d["end_state"]["pdf"] == sum(
        v for (_st, s), v in exp_end.items() if s in ("clean", "partial")
    )
    assert d["union"]["pdf"] == sum(
        v for k, v in exp_uni.items() if k in ("clean", "partial")
    )
    assert d["union"]["pdf"] >= d["end_state"]["pdf"]
    assert d["union"]["clean"] >= d["end_state"]["clean"]


@pytest.mark.parametrize(
    "bad_metrics", ["x", [1], 5, True], ids=["str", "list", "int", "bool"]
)
def test_compute_metrics_nondict_metrics(tmp_path: Path, bad_metrics: object) -> None:
    recs = [_rec("p", "fixloop", "fail", arm="fix", metrics=bad_metrics)]
    line = triage.compute_metrics(tmp_path, recs, None)
    assert isinstance(line["wall_s"], float)


# ================================================================ benchlib 账读
def test_benchlib_iter_jsonl_truncated_utf8(tmp_path: Path) -> None:
    p = tmp_path / "r.jsonl"
    p.write_bytes(b'{"id":"a"}\n{"id":"b","\xe4\xb8')
    assert [r["id"] for r in benchlib.iter_jsonl(p)] == ["a"]


@pytest.mark.parametrize(
    "line",
    ["5", '"id"', '["id"]', "null", "true", "3.14"],
    ids=["int", "str_hit", "list_hit", "null", "bool", "float"],
)
def test_benchlib_load_records_nondict(tmp_path: Path, line: str) -> None:
    p = tmp_path / "r.jsonl"
    p.write_text(f'{line}\n{{"id":"a","v":1}}\n', encoding="utf-8")
    assert list(benchlib.load_records(p)) == ["a"]


def test_benchlib_load_records_benign_lines(tmp_path: Path) -> None:
    """容错面钉住：坏 json/空行/无 key dict/不含 key 的 str 行都跳过不崩。"""
    p = tmp_path / "r.jsonl"
    p.write_text(
        '{bad\n\n"nokey"\n{"k":1}\n{"id":"a","v":1}\n{"id":"a","v":2}\n',
        encoding="utf-8",
    )
    out = benchlib.load_records(p)
    assert out == {"a": {"id": "a", "v": 2}}  # 末行胜


@pytest.mark.parametrize(
    ("errors", "want"),
    [
        (["oops"], ""),
        (5, ""),
        (None, ""),
        ([{"cat": "c", "payload": "p"}], "c:p"),
    ],
    ids=["str_entry", "int_nonlist", "none", "ok"],
)
def test_benchlib_errors_sig_guards(errors: object, want: str) -> None:
    """errors_sig 边界形状不崩：非 list/非 dict 首元 → 空 sig。"""
    assert benchlib.errors_sig(errors) == want


# ================================================================ triage 归桶
def test_load_records_conservation_fuzz(tmp_path: Path) -> None:
    """守恒：Σ 文件（唯一 (id,arm,upstream) 键 + 无 id dict 行）== 输出长度；
    同键末条胜。"""
    rng = fuzz_rng(_SEED + 20)
    rdir = tmp_path / "records"
    rdir.mkdir()
    total_oracle = 0
    last_val: dict[tuple, int] = {}
    for stage in ("compile", "xlat", "fixloop"):
        lines: list[str] = []
        seen: dict[tuple, int] = {}
        noid = 0
        for i in range(_SAMPLE_PER_FILE):
            kind = rng.choice(
                ["broken", "nonstr", "noid", "rec", "rec", "rec", "rec", "rec"]
            )
            if kind == "broken":
                lines.append("{broken")
            elif kind == "nonstr":
                lines.append("5")  # 非 dict json——triage 容忍
            elif kind == "noid":
                lines.append(json.dumps({"note": f"noid-{i}"}))
                noid += 1
            else:
                rec = _rec(
                    rng.choice(["a", "b", "c", "d"]),
                    stage,
                    rng.choice(_REC_STATUS),
                    arm=rng.choice(["zh", "base", "-"]),
                    upstream=rng.choice(["", "mock", "real"]),
                    sig=rng.choice(_SIG_POOL),
                    errors=rng.choice(_ERRORS_POOL),
                )
                rec["n"] = i
                lines.append(json.dumps(rec, ensure_ascii=False))
                key = (
                    rec["id"],
                    str(rec["arm"] or "-"),
                    str(rec["upstream"] or ""),
                )
                seen[key] = i
        _write_jsonl(rdir / f"{stage}.jsonl", lines)
        total_oracle += len(seen) + noid
        for k, i in seen.items():
            last_val[(stage, *k)] = i
    recs = triage.load_records(tmp_path)
    assert len(recs) == total_oracle
    for r in recs:
        if "n" in r:
            key = (
                r["stage"],
                str(r.get("id")),
                str(r.get("arm") or "-"),
                str(r.get("upstream") or ""),
            )
            assert r["n"] == last_val[key]
        else:
            assert "note" in r
    assert all(r["stage"] in {"compile", "xlat", "fixloop"} for r in recs)


def test_record_sig_deterministic_fuzz() -> None:
    """record_sig 确定性 + 恒 str；空 sig → errors[0] 合成 → nosig:status 兜底。"""
    rng = fuzz_rng(_SEED + 21)
    for _ in range(_ITERS):
        rec = _rec(
            "p",
            rng.choice(["compile", "xlat", "fixloop"]),
            rng.choice(_REC_STATUS),
            sig=rng.choice(_SIG_POOL),
            errors=rng.choice(_ERRORS_POOL),
        )
        s1 = triage.record_sig(rec)
        s2 = triage.record_sig(json.loads(json.dumps(rec)))
        assert isinstance(s1, str)
        assert s1 == s2
    assert triage.record_sig(_rec("p", "s", "fail")) == "nosig:fail"
    assert triage.record_sig(_rec("p", "s", "")) == "nosig:unknown"
    r = _rec("p", "s", "fail", errors=[{"code": "c", "cat": "k", "payload": "v"}])
    assert triage.record_sig(r) == "k:v"


def _ticketed(recs: list[dict]) -> list[dict]:
    """build_tickets 豁免谓词的独立 oracle（errors 恒 list 场景）。"""
    out = []
    for r in recs:
        st = str(r.get("status") or "")
        has_sig = bool(str(r.get("sig") or "").strip())
        has_err = bool(r.get("errors"))
        if st in triage.OK_STATUS | triage.SKIP_STATUS and not (has_sig or has_err):
            continue
        gated = False
        if st in triage.SKIP_STATUS:
            errs = r.get("errors")
            e0 = (
                errs[0]
                if isinstance(errs, list) and errs and isinstance(errs[0], dict)
                else {}
            )
            gated = str(e0.get("cat") or "") == "upstream" or str(
                r.get("sig") or ""
            ).startswith("upstream:")
        if not gated:
            out.append(r)
    return out


def test_build_tickets_conservation_fuzz(tmp_path: Path) -> None:
    """Σ count == 非豁免记录数；桶不相交（每记录恰一 (stage,sig)）；排序+sig_id 唯一。"""
    rng = fuzz_rng(_SEED + 22)
    recs = [
        _rec(
            f"p{i}",
            rng.choice(["compile", "xlat", "fixloop"]),
            rng.choice(_REC_STATUS),
            sig=rng.choice(_SIG_POOL),
            errors=rng.choice(_ERRORS_POOL),
            arm=rng.choice(["zh", "base", "mock", "fix"]),
        )
        for i in range(_ITERS)
    ]
    tickets = triage.build_tickets(recs, tmp_path)
    expected = _ticketed(recs)
    assert sum(t["count"] for t in tickets) == len(expected)
    cluster: Counter = Counter()
    for r in expected:
        cluster[(str(r.get("stage") or "?"), triage.record_sig(r))] += 1
    assert (
        Counter({(t["stage"], t["signature"]): t["count"] for t in tickets}) == cluster
    )
    keys = [(-t["count"], t["stage"], t["signature"]) for t in tickets]
    assert keys == sorted(keys)
    sig_ids = [t["sig_id"] for t in tickets]
    assert len(sig_ids) == len(set(sig_ids))
    for t in tickets:
        assert len(t["example_ids"]) <= triage.MAX_EXAMPLES
        assert len(set(t["example_ids"])) == len(t["example_ids"])
        assert t["count"] >= len(t["example_ids"])  # ids 簇内去重


def test_build_tickets_ok_with_sig_warning() -> None:
    """ok 记录带显式 sig 仍出票（warning 级）——豁免条件是 (无 sig ∧ 无 errors)。"""
    recs = [
        _rec("p1", "compile", "ok", sig="warn:invalid_utf8"),
        _rec("p2", "compile", "ok"),  # 无 sig 无 errors → 豁免
        _rec(
            "p3",
            "compile",
            "ok",
            errors=[{"code": "w", "cat": "w", "payload": ""}],
        ),
    ]
    tickets = triage.build_tickets(recs, Path("nonexistent-dir"))
    assert [(t["signature"], t["count"]) for t in tickets] == [
        ("w", 1),
        ("warn:invalid_utf8", 1),
    ]
    assert all("warning" in t["notes"] for t in tickets)


def test_compute_metrics_conservation_fuzz(tmp_path: Path) -> None:
    """逐 cell Σby_status==total ∧ ok/skip ⊆ total ∧ rate∈[0,1]；
    rescued ≤ attempted；pipeline_introduced 归因口径。"""
    rng = fuzz_rng(_SEED + 23)
    recs = [
        _rec(
            rng.choice(["a", "b", "c", "d", "e"]),
            rng.choice(["compile", "fixloop", "xlat", "parse"]),
            rng.choice(_REC_STATUS),
            arm=rng.choice(["zh", "base", "mock", "fix", "default"]),
            sig=rng.choice(_SIG_POOL),
            errors=rng.choice(_ERRORS_POOL),
            dur_s=rng.choice([0.0, 1.5, -2.0, 99.9, None]),
        )
        for _ in range(_ITERS)
    ]
    line = triage.compute_metrics(tmp_path, recs, None)
    total_sum = 0
    for stage, arms in line["stage_rates"].items():
        for arm, c in arms.items():
            oracle = [
                r
                for r in recs
                if str(r.get("stage") or "?") == stage
                and str(r.get("arm") or "default") == arm
            ]
            assert c["total"] == len(oracle)
            assert sum(c["by_status"].values()) == c["total"]
            assert c["ok"] <= c["total"]
            assert c["n_skip"] <= c["total"]
            assert c["rate"] is None or 0 <= c["rate"] <= 1
            ok_set = triage.RESCUED_STATUS if stage == "fixloop" else triage.OK_STATUS
            assert c["ok"] == sum(
                1 for r in oracle if str(r.get("status") or "") in ok_set
            )
            assert c["n_skip"] == sum(
                1 for r in oracle if str(r.get("status") or "") in triage.SKIP_STATUS
            )
            total_sum += c["total"]
    assert total_sum == len(recs)
    fl = line["fixloop"]
    attempted = [
        r
        for r in recs
        if r.get("stage") == "fixloop"
        and str(r.get("status") or "") not in triage.SKIP_STATUS
    ]
    assert fl["attempted"] == len(attempted)
    assert fl["rescued"] <= fl["attempted"]
    assert fl["rescue_rate"] is None or 0 <= fl["rescue_rate"] <= 1
    by_id: dict[str, dict] = {}
    for r in recs:
        if r.get("stage") == "compile":
            by_id.setdefault(str(r.get("id")), {})[str(r.get("arm") or "default")] = (
                str(r.get("status") or "")
            )
    ok_skip_err = triage.OK_STATUS | triage.SKIP_STATUS | {"error"}
    eligible = {
        i
        for i, a in by_id.items()
        if a.get("zh")
        and a["zh"] not in ok_skip_err
        and a.get("base") in triage.OK_STATUS
    }
    pipes = {r["id"] for r in line["regressions"] if r["kind"] == "pipeline_introduced"}
    assert pipes <= eligible
    for r in line["regressions"]:
        if r["kind"] == "pipeline_introduced_truncated":
            assert r["total"] == len(eligible)


def test_compute_metrics_rate_drop(tmp_path: Path) -> None:
    """rate_drop 回归：prev 同 stage/arm rate 高 → 报；相等/无 prev → 不报。"""
    recs = [
        _rec("a", "compile", "ok", arm="zh"),
        _rec("b", "compile", "fail", arm="zh"),
    ]
    prev = {"run_id": "prev", "stage_rates": {"compile": {"zh": {"rate": 0.9}}}}
    line = triage.compute_metrics(tmp_path, recs, prev)
    drops = [r for r in line["regressions"] if r["kind"] == "rate_drop"]
    assert len(drops) == 1
    assert drops[0]["cur"] == line["stage_rates"]["compile"]["zh"]["rate"]
    assert drops[0]["prev"] == prev["stage_rates"]["compile"]["zh"]["rate"]
    prev_eq = {"run_id": "p", "stage_rates": {"compile": {"zh": {"rate": 0.5}}}}
    line2 = triage.compute_metrics(tmp_path, recs, prev_eq)
    assert not [r for r in line2["regressions"] if r["kind"] == "rate_drop"]


def test_triage_errors_dict(tmp_path: Path) -> None:
    bad = _rec(
        "p",
        "xlat",
        "skip",
        sig="upstream:x",
        errors={"cat": "upstream", "code": "upstream_gate"},
    )
    # 期望语义：errors dict 视为无 errors → sig upstream:* 仍门控 → 零票
    assert triage.build_tickets([bad], tmp_path) == []
    assert triage.record_sig(bad) == "upstream:x"
    assert triage.classify("syntax", {"errors": {"a": 1}})[0] == "rule"


@pytest.mark.parametrize("bad_dur", ["abc", {"a": 1}, [1]], ids=["str", "dict", "list"])
def test_wall_s_nonstr_dur(tmp_path: Path, bad_dur: object) -> None:
    recs = [_rec("p", "compile", "fail", dur_s=bad_dur)]
    line = triage.compute_metrics(tmp_path, recs, None)
    assert math.isfinite(line["wall_s"])


@pytest.mark.parametrize(
    "bad_dur",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "inf", "-inf"],
)
def test_wall_s_nonfinite(tmp_path: Path, bad_dur: float) -> None:
    recs = [_rec("p", "compile", "fail", dur_s=bad_dur)]
    line = triage.compute_metrics(tmp_path, recs, None)
    assert math.isfinite(line["wall_s"])


def test_fixloop_degraded_skip_false_positive(tmp_path: Path) -> None:
    recs = [
        _rec(
            "p1",
            "fixloop",
            "skip",
            arm="fix",
            metrics={"compile_status_before": "fail"},
        )
    ]
    line = triage.compute_metrics(tmp_path, recs, None)
    degs = [r for r in line["regressions"] if r["kind"] == "fixloop_degraded"]
    assert degs == []


def test_missing_character_count_fragments(tmp_path: Path) -> None:
    sigs = ["missing_character", "missing_character:x1", "missing_character:x17"]
    recs = [
        _rec(
            f"p{i}",
            "compile",
            "partial",
            sig=sig,
            errors=[
                {
                    "code": "missing_character",
                    "cat": "missing_character",
                    "payload": "",
                }
            ],
        )
        for i, sig in enumerate(sigs)
    ]
    tickets = triage.build_tickets(recs, tmp_path)
    assert len(tickets) == 1
    assert tickets[0]["count"] == len(sigs)
    assert tickets[0]["fix_class"] == "rule"


# ---------------------------------------------------------------- legacy 降级
def test_legacy_corrupt_results(tmp_path: Path) -> None:
    (tmp_path / "results.json").write_text('{"a": {"id":"a", "pipe-xel": {"verd')
    assert triage.legacy_records(tmp_path) == []


@pytest.mark.parametrize(
    "doc", ["[1,2]", '"x"', "5", "null"], ids=["list", "str", "int", "null"]
)
def test_legacy_nondict_results(tmp_path: Path, doc: str) -> None:
    (tmp_path / "results.json").write_text(doc)
    assert triage.legacy_records(tmp_path) == []


@pytest.mark.parametrize(
    "bad_verdict",
    ['"boom"', "5", "[1]", "true"],
    ids=["str", "int", "list", "bool"],
)
def test_legacy_verdict_nondict(tmp_path: Path, bad_verdict: str) -> None:
    doc = {"a": {"id": "a", "pipe-xel": {"verdict": json.loads(bad_verdict)}}}
    (tmp_path / "results.json").write_text(json.dumps(doc))
    recs = triage.legacy_records(tmp_path)
    assert isinstance(recs, list)


@pytest.mark.parametrize(
    "bad_rounds",
    ['"boom"', '{"a":1}', "5", "[1,2]"],
    ids=["str", "dict", "int", "list_int"],
)
def test_legacy_rounds_nonlist(tmp_path: Path, bad_rounds: str) -> None:
    doc = {
        "a": {
            "id": "a",
            "pipe-fix": {
                "fixloop": {
                    "verdict": "unfixable:syntax",
                    "rounds": json.loads(bad_rounds),
                }
            },
        }
    }
    (tmp_path / "results.json").write_text(json.dumps(doc))
    recs = triage.legacy_records(tmp_path)
    assert isinstance(recs, list)


# ---------------------------------------------------------------- 真实账回放
def _sample_records_files(limit_per_file: int, rng: random.Random) -> list[dict]:
    """bench/results/*/records/*.jsonl 抽样真实行（gitignored——不在本机则空）。"""
    out: list[dict] = []
    for fp in sorted(_RESULTS.glob("*/records/*.jsonl")):
        n = 0
        for line in fp.open(errors="replace"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict):
                out.append(r)
                n += 1
            if n >= limit_per_file:
                break
        if len(out) >= limit_per_file * 6:
            break
    rng.shuffle(out)
    return out


#: 变异种类表——字段名即分支键（数字索引会踩 PLR2004 提名噪音）
_MUT_KINDS = (
    "status",
    "sig",
    "id",
    "arm",
    "upstream",
    "dur_s",
    "csb",
    "errval",
    "popjunk",
)


def _mutate(rec: dict, rng: random.Random) -> dict:  # noqa: C901 -- 变异点即分支表
    """字段值级变异（保 dict 形状）：status/sig/id/arm/upstream/dur_s/
    metrics.compile_status_before/errors[*] 字段值打乱 + 随机丢/加字段。"""
    r = json.loads(json.dumps(rec))
    for _ in range(rng.randrange(1, 4)):
        which = rng.choice(_MUT_KINDS)
        if which == "status":
            r["status"] = rng.choice([*_REC_STATUS, *_MUT_SCALAR])
        elif which == "sig":
            r["sig"] = rng.choice([*_SIG_POOL, *_MUT_SCALAR])
        elif which == "id":
            r["id"] = rng.choice(["a", "b", "p9", "", None, 5])
        elif which == "arm":
            r["arm"] = rng.choice(["zh", "base", "fix", "mock", "-", "", None])
        elif which == "upstream":
            r["upstream"] = rng.choice(["mock", "real", "", None])
        elif which == "dur_s":
            r["dur_s"] = rng.choice([0.0, 1.5, -3.0, None])
        elif which == "csb" and isinstance(r.get("metrics"), dict):
            r["metrics"]["compile_status_before"] = rng.choice(
                ["fail", "partial", "clean", None, 5]
            )
        elif which == "errval":
            errs = r.get("errors")
            if isinstance(errs, list) and errs and isinstance(errs[0], dict):
                errs[0][rng.choice(["code", "cat", "payload"])] = rng.choice(
                    _MUT_SCALAR
                )
        elif which == "popjunk":
            r.pop(rng.choice(["sig", "errors", "metrics", "dur_s"]), None)
            r[f"junk{rng.randrange(3)}"] = rng.choice(_MUT_SCALAR)
    return r


@pytest.mark.slow
@pytest.mark.skipif(
    not any(_RESULTS.glob("*/records/*.jsonl")),
    reason="bench/results/*/records/ 不在本机（gitignored 重产物）",
)
def test_real_records_mutated_triage(tmp_path: Path) -> None:
    """真实 stagerun 记录字段值变异 → build_tickets/compute_metrics 不崩且守恒。"""
    rng = fuzz_rng(_SEED + 30)
    sample = _sample_records_files(_SAMPLE_PER_FILE, rng)[:_SAMPLE_CAP]
    assert sample, "sample 为空——glob 命中但无 dict 行"
    mutated = [_mutate(r, rng) for r in sample]
    tickets = triage.build_tickets(mutated, tmp_path)
    expected = _ticketed(mutated)
    assert sum(t["count"] for t in tickets) == len(expected)
    line = triage.compute_metrics(tmp_path, mutated, None)
    total_sum = sum(
        c["total"] for arms in line["stage_rates"].values() for c in arms.values()
    )
    assert total_sum == len(mutated)


@pytest.mark.slow
@pytest.mark.skipif(
    not (_RESULTS / "stagerun-loop1-2026-09-16" / "records").is_dir(),
    reason="stagerun-loop1 records 不在本机（gitignored 重产物）",
)
def test_real_records_mutated_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真实 compile/fixloop 记录变异 → gate_scorecard.main 不崩且 cells 守恒。"""
    rng = fuzz_rng(_SEED + 31)
    src = _RESULTS / "stagerun-loop1-2026-09-16" / "records"
    comp_rows: list = []
    fix_rows: list = []
    for fp, sink in (
        (src / "compile.jsonl", comp_rows),
        (src / "fixloop.jsonl", fix_rows),
    ):
        n = 0
        for line in fp.open(errors="replace"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict):
                sink.append(_mutate(r, rng))
                n += 1
            if n >= _GATE_SAMPLE:
                break
    cells, pdf, clean, _out = _gate_run(
        tmp_path, comp_rows, fix_rows, capsys, monkeypatch
    )
    # oracle：mock 口径 + arm=zh + 非 arm_mismatch + str id 去重后条数
    valid = {
        r["id"]
        for r in comp_rows
        if isinstance(r.get("id"), str)
        and r.get("id")
        and r.get("arm") == "zh"
        and (r.get("upstream") or "mock") == "mock"
        and isinstance(r.get("errors") or [], list)
        and all(isinstance(e, dict) for e in (r.get("errors") or []))
        and not any(e.get("code") == "arm_mismatch" for e in (r.get("errors") or []))
    }
    assert cells == len(valid)
    assert clean <= pdf <= cells


@pytest.mark.slow
@pytest.mark.skipif(
    not any(_RESULTS.glob("*/results.json")),
    reason="bench/results/*/results.json 不在本机（gitignored 重产物）",
)
def test_real_results_json_legacy_roundtrip(tmp_path: Path) -> None:
    """真实 results.json → legacy_records → build_tickets/compute_metrics 不崩。"""
    src = next(iter(sorted(_RESULTS.glob("*/results.json"))))
    (tmp_path / "results.json").write_bytes(src.read_bytes())
    recs = triage.legacy_records(tmp_path)
    assert isinstance(recs, list)
    tickets = triage.build_tickets(recs, tmp_path)
    expected = _ticketed(recs)
    assert sum(t["count"] for t in tickets) == len(expected)
    line = triage.compute_metrics(tmp_path, recs, None)
    total = sum(
        c["total"] for arms in line["stage_rates"].values() for c in arms.values()
    )
    assert total == len(recs)


def test_selftest_synthetic_oracle(tmp_path: Path) -> None:
    """--selftest 合成账作 oracle 种：逐格核对 tickets/metrics 守恒。"""
    rdir = tmp_path / "run"
    (rdir / "records").mkdir(parents=True)
    (rdir / "work").mkdir()
    rows = {
        "compile": [
            _rec("a", "compile", "ok", arm="zh"),
            _rec("b", "compile", "fail", arm="zh", sig="missing_file:x.cls"),
            _rec("b", "compile", "clean", arm="zh"),  # 同键末条胜 → b clean
            _rec(
                "c",
                "compile",
                "skip",
                arm="zh",
                sig="upstream:parse=reject",
                errors=[{"code": "upstream_gate", "cat": "upstream", "payload": "p"}],
            ),
        ],
        "fixloop": [
            _rec(
                "b",
                "fixloop",
                "fail",
                arm="fix",
                sig="unfixable:missing_file:x.cls",
            )
        ],
    }
    for stage, rs in rows.items():
        _write_jsonl(rdir / "records" / f"{stage}.jsonl", rs)
    recs = triage.load_records(rdir)
    tickets = triage.build_tickets(recs, rdir)
    # b 末条 clean 无 sig → 豁免；c upstream 门 skip → 豁免；只剩 fixloop b
    assert [(t["signature"], t["count"]) for t in tickets] == [
        ("unfixable:missing_file:x.cls", 1)
    ]
    line = triage.compute_metrics(rdir, recs, None)
    assert line["stage_rates"]["compile"]["zh"]["total"] == len(rows["compile"]) - 1
