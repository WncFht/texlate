"""三级聚合 report.py 测试。"""

from texlate.validate import aggregate, parse_log_text, validate_pair
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
