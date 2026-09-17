"""三级聚合 report.py 测试。"""

from texlate.validate import aggregate, parse_log_text, validate_pair
from texlate.validate.l1 import TsResult
from texlate.validate.l2 import L2Verdict


def test_aggregate_l0_only() -> None:
    l0 = validate_pair("见 [[MATH_1]]。", "见。")
    rep = aggregate("c1", l0=l0)
    assert not rep.ok
    assert rep.n_error >= 1
    assert rep.hard_failures()
    assert "占位符缺失" in rep.feedback()
    assert "L0✗" in rep.summary()


def test_aggregate_all_pass() -> None:
    l0 = validate_pair("见 [[MATH_1]]。", "见 [[MATH_1]]（译）。")
    l2 = parse_log_text(
        "This is XeTeX\n(./main.tex\n)\nOutput written on main.pdf (1 page).\n"
    )
    rep = aggregate("c2", l0=l0, l2=l2)
    assert rep.ok, rep.hard_failures()
    assert rep.n_error == 0
    assert "L0✓" in rep.summary()
    assert "L2✓" in rep.summary()


def test_aggregate_l2_fail() -> None:
    l2 = parse_log_text("! Undefined control sequence.\nl.3 \\foo\n")
    rep = aggregate("c3", l2=l2)
    assert not rep.ok
    assert any("l2" in h for h in rep.hard_failures())
    assert "l.3" in rep.feedback() or "3" in rep.feedback()


def test_aggregate_l2_missing_log_not_failure() -> None:
    rep = aggregate("c4", l2=L2Verdict(log_missing=True))
    assert rep.ok  # log 缺失 = 信息缺失，不算失败
    assert "L2?" in rep.summary()


def test_to_dict_roundtrip_shape() -> None:
    l0 = validate_pair("见 [[MATH_1]]。", "见。")
    rep = aggregate("c5", l0=l0)
    d = rep.to_dict()
    assert d["chunk_id"] == "c5"
    assert d["ok"] is False
    assert d["l0"]["n_error"] >= 1
    assert d["l1"] is None
    assert d["l2"] is None


# ------------------------------------------------- l1 层渲染补洞（审计 C1）
# hard_failures()/feedback()/summary()/ok/n_error 的 l1 分支此前零覆盖。


def test_aggregate_l1_fail_full_render() -> None:
    """l1 不过 → ok/n_error/hard_failures/feedback/summary/to_dict 全链路。"""
    l1 = TsResult(
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
    rep = aggregate("c6", l1=l1)
    assert not rep.ok
    assert rep.n_error == 1  # l1 不过只计 1 条硬判据
    (hf,) = rep.hard_failures()
    assert hf.startswith("l1:cst ")
    for tok in ("parse_errors=2", "env=1", "math=1", "brace=-2", "ph=3"):
        assert tok in hf
    fb = rep.feedback()
    assert "CST ERROR at row 4: \\end{eqx}" in fb
    assert "CST env end_name: begin=equation end=eqx line 12" in fb
    assert "placeholder missing: [[MATH_1]]" in fb
    assert "placeholder typo: [[MATH1]] should be [[MATH_1]]" in fb
    assert "L1✗" in rep.summary()
    d = rep.to_dict()
    assert d["l1"]["verdict_ok"] is False
    assert d["l1"]["brace_balance"] == l1.brace_balance


def test_aggregate_l1_fail_bare() -> None:
    """l1 无明细字段 → 'l1:cst failed' 兜底；feedback 整块为空。"""
    rep = aggregate(l1=TsResult(ok=False))
    assert rep.hard_failures() == ["l1:cst failed"]
    assert rep.feedback() == ""


def test_aggregate_l1_relative_pass() -> None:
    """baseline 相对判定是生产口径：ok=False + ok_relative=True → 放行。"""
    rep = aggregate("c7", l1=TsResult(ok=False, ok_relative=True))
    assert rep.ok
    assert rep.n_error == 0
    assert rep.hard_failures() == []
    assert rep.feedback() == ""
    assert "L1✓" in rep.summary()


def test_feedback_l0_empty_skipped() -> None:
    """l0 干净（feedback()==''）→ 不进 parts，空节不泄进 corrector 反馈。"""
    l0 = validate_pair("见 [[MATH_1]]。", "见 [[MATH_1]]（译）。")
    assert l0.ok
    rep = aggregate("c8", l0=l0)
    assert rep.feedback() == ""


def test_aggregate_mixed_layers_render() -> None:
    """三层全挂 → hard_failures 各带层前缀，feedback 三段全在。"""
    l0 = validate_pair("见 [[MATH_1]]。", "见。")
    l1 = TsResult(
        ok=False,
        parse_errors=[{"type": "ERROR", "row": 4, "snippet": "\\foo"}],
    )
    l2 = parse_log_text("! Undefined control sequence.\nl.3 \\foo\n")
    rep = aggregate("c9", l0=l0, l1=l1, l2=l2)
    assert not rep.ok
    assert rep.n_error == l0.n_error + 1 + l2.n_errors
    hf = rep.hard_failures()
    assert any(h.startswith("l0:") for h in hf)
    assert any(h.startswith("l1:cst") and "parse_errors=1" in h for h in hf)
    assert any(h.startswith("l2:compile") for h in hf)
    fb = rep.feedback()
    assert "占位符缺失" in fb
    assert "CST ERROR at row 4" in fb
    assert "compile error" in fb
    assert rep.summary().startswith("c9 L0✗ L1✗ L2✗")


def test_feedback_l1_caps_at_five() -> None:
    """parse_errors/env_mismatches 各只渲染前 5 条——corrector 反馈防爆。"""
    l1 = TsResult(
        ok=False,
        parse_errors=[{"type": "E", "row": i, "snippet": f"s{i}"} for i in range(7)],
        env_mismatches=[
            {"kind": "k", "begin_env": f"b{i}", "end_env": "e", "line": i}
            for i in range(7)
        ],
    )
    fb = aggregate(l1=l1).feedback()
    assert "s4" in fb
    assert "s5" not in fb
    assert "begin=b4" in fb
    assert "begin=b5" not in fb


def test_feedback_l1_default_keys() -> None:
    """worker 明细缺字段 → .get 默认值渲染（'ERROR'/'?'），不 KeyError。"""
    rep = aggregate(l1=TsResult(ok=False, parse_errors=[{}], env_mismatches=[{}]))
    fb = rep.feedback()
    assert "CST ERROR at row ?: " in fb
    assert "CST env ?: begin=None end=None line None" in fb


def test_hard_failures_ph_unexpected_only() -> None:
    """placeholders 只爆 unexpected → ph 计数照入 hard_failures，feedback 无此行。"""
    rep = aggregate(l1=TsResult(ok=False, placeholders={"unexpected": ["X_1"]}))
    assert rep.hard_failures() == ["l1:cst ph=1"]
    assert rep.feedback() == ""
