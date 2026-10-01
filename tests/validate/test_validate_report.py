"""三级聚合 report.py 测试。"""

from texlate.validate import aggregate, parse_log_text, validate_pair
from texlate.validate.cst import TsResult
from texlate.validate.logattr import LogVerdict


def test_aggregate_rules_only() -> None:
    rules = validate_pair("见 [[MATH_1]]。", "见。")
    rep = aggregate("c1", rules=rules)
    assert not rep.ok
    assert rep.n_error >= 1
    assert rep.hard_failures()
    assert "占位符缺失" in rep.feedback()
    assert "rules✗" in rep.summary()


def test_aggregate_all_pass() -> None:
    rules = validate_pair("见 [[MATH_1]]。", "见 [[MATH_1]]（译）。")
    logattr = parse_log_text(
        "This is XeTeX\n(./main.tex\n)\nOutput written on main.pdf (1 page).\n"
    )
    rep = aggregate("c2", rules=rules, logattr=logattr)
    assert rep.ok, rep.hard_failures()
    assert rep.n_error == 0
    assert "rules✓" in rep.summary()
    assert "logattr✓" in rep.summary()


def test_aggregate_logattr_fail() -> None:
    logattr = parse_log_text("! Undefined control sequence.\nl.3 \\foo\n")
    rep = aggregate("c3", logattr=logattr)
    assert not rep.ok
    assert any("logattr" in h for h in rep.hard_failures())
    assert "l.3" in rep.feedback() or "3" in rep.feedback()


def test_aggregate_logattr_missing_log_not_failure() -> None:
    rep = aggregate("c4", logattr=LogVerdict(log_missing=True))
    assert rep.ok  # log 缺失 = 信息缺失，不算失败
    assert "logattr?" in rep.summary()


def test_to_dict_roundtrip_shape() -> None:
    rules = validate_pair("见 [[MATH_1]]。", "见。")
    rep = aggregate("c5", rules=rules)
    d = rep.to_dict()
    assert d["chunk_id"] == "c5"
    assert d["ok"] is False
    assert d["rules"]["n_error"] >= 1
    assert d["cst"] is None
    assert d["logattr"] is None


# ------------------------------------------------- cst 层渲染补洞（审计 C1）
# hard_failures()/feedback()/summary()/ok/n_error 的 cst 分支此前零覆盖。


def test_aggregate_cst_fail_full_render() -> None:
    """cst 不过 → ok/n_error/hard_failures/feedback/summary/to_dict 全链路。"""
    cst = TsResult(
        ok=False,
        parse_errors=[
            {"type": "ERROR", "row": 4, "snippet": "\\end{eqx}"},
            {"type": "MISSING", "row": 9, "snippet": "}"},
        ],
        env_mismatches=[
            {
                "kind": "end_name",
                "begin_env": "equation",
                "end_env": "eqx",
                "line": 12,
            }
        ],
        unclosed_math=1,
        brace_balance=-2,
        placeholders={
            "missing": ["MATH_1"],
            "unexpected": ["ENV_9"],
            "typos": [{"found": "MATH1", "expected": "MATH_1"}],
        },
    )
    rep = aggregate("c6", cst=cst)
    assert not rep.ok
    assert rep.n_error == 1  # cst 不过只计 1 条硬判据
    (hf,) = rep.hard_failures()
    assert hf.startswith("cst:")
    for tok in ("parse_errors=2", "env=1", "math=1", "brace=-2", "ph=3"):
        assert tok in hf
    fb = rep.feedback()
    assert "CST ERROR at row 4: \\end{eqx}" in fb
    assert "CST env end_name: begin=equation end=eqx line 12" in fb
    assert "placeholder missing: [[MATH_1]]" in fb
    assert "placeholder typo: [[MATH1]] should be [[MATH_1]]" in fb
    assert "cst✗" in rep.summary()
    d = rep.to_dict()
    assert d["cst"]["verdict_ok"] is False
    assert d["cst"]["brace_balance"] == cst.brace_balance


def test_aggregate_cst_fail_bare() -> None:
    """cst 无明细字段 → 'cst:failed' 兜底；feedback 整块为空。"""
    rep = aggregate(cst=TsResult(ok=False))
    assert rep.hard_failures() == ["cst:failed"]
    assert rep.feedback() == ""


def test_aggregate_cst_relative_pass() -> None:
    """baseline 相对判定是生产口径：ok=False + ok_relative=True → 放行。"""
    rep = aggregate("c7", cst=TsResult(ok=False, ok_relative=True))
    assert rep.ok
    assert rep.n_error == 0
    assert rep.hard_failures() == []
    assert rep.feedback() == ""
    assert "cst✓" in rep.summary()


def test_feedback_rules_empty_skipped() -> None:
    """rules 干净（feedback()==''）→ 不进 parts，空节不泄进 corrector 反馈。"""
    rules = validate_pair("见 [[MATH_1]]。", "见 [[MATH_1]]（译）。")
    assert rules.ok
    rep = aggregate("c8", rules=rules)
    assert rep.feedback() == ""


def test_aggregate_mixed_layers_render() -> None:
    """三层全挂 → hard_failures 各带层前缀，feedback 三段全在。"""
    rules = validate_pair("见 [[MATH_1]]。", "见。")
    cst = TsResult(
        ok=False,
        parse_errors=[{"type": "ERROR", "row": 4, "snippet": "\\foo"}],
    )
    logattr = parse_log_text("! Undefined control sequence.\nl.3 \\foo\n")
    rep = aggregate("c9", rules=rules, cst=cst, logattr=logattr)
    assert not rep.ok
    assert rep.n_error == rules.n_error + 1 + logattr.n_errors
    hf = rep.hard_failures()
    assert any(h.startswith("rules:") for h in hf)
    assert any(h.startswith("cst:") and "parse_errors=1" in h for h in hf)
    assert any(h.startswith("logattr:compile") for h in hf)
    fb = rep.feedback()
    assert "占位符缺失" in fb
    assert "CST ERROR at row 4" in fb
    assert "compile error" in fb
    assert rep.summary().startswith("c9 rules✗ cst✗ logattr✗")


def test_feedback_cst_caps_at_five() -> None:
    """parse_errors/env_mismatches 各只渲染前 5 条——corrector 反馈防爆。"""
    cst = TsResult(
        ok=False,
        parse_errors=[{"type": "E", "row": i, "snippet": f"s{i}"} for i in range(7)],
        env_mismatches=[
            {"kind": "k", "begin_env": f"b{i}", "end_env": "e", "line": i}
            for i in range(7)
        ],
    )
    fb = aggregate(cst=cst).feedback()
    assert "s4" in fb
    assert "s5" not in fb
    assert "begin=b4" in fb
    assert "begin=b5" not in fb


def test_feedback_cst_default_keys() -> None:
    """worker 明细缺字段 → .get 默认值渲染（'ERROR'/'?'），不 KeyError。"""
    rep = aggregate(cst=TsResult(ok=False, parse_errors=[{}], env_mismatches=[{}]))
    fb = rep.feedback()
    assert "CST ERROR at row ?: " in fb
    assert "CST env ?: begin=None end=None line None" in fb


def test_hard_failures_ph_unexpected_only() -> None:
    """placeholders 只爆 unexpected → ph 计数照入 hard_failures，feedback 无此行。"""
    rep = aggregate(cst=TsResult(ok=False, placeholders={"unexpected": ["X_1"]}))
    assert rep.hard_failures() == ["cst:ph=1"]
    assert rep.feedback() == ""
