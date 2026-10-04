"""fixloop stuck 语义 (exhaustion-settled streak) 单测 —— 合成 log + mock engine。

旧制在第 stuck_sig_repeat 个同标记轮 ``_match_apply`` 前预判 stuck —— 产出轮
(apply 发生) 同样计入 sig_n, 只在第 N+1 轮才够得到的规则 (凭据门
if_phantom_protect 类：需兄弟规则的 action 先落 ledger) 被永久抢死在
窗口外 (1206.0701/1306.0364: r1/r2 各有 apply, r3 未派发即断)。

新制 (task #142): ``sig_n`` 仍记同标记连续 streak, 但 stuck verdict 移到
派发耗尽点结算 —— streak ≥ stuck_n 且本轮主 + 次级派发全 miss → stuck。
apply 轮次只续窗口不占判负; 真耗尽格烧轮止于派发枯竭，不多烧一轮。
"""

from pathlib import Path

from _fixloopkit import (
    BOOM_LOG,
    BOOM_TAXONOMY,
    CLEAN_LOG,
    MockEngine,
    make_proj,
    mini_rs,
)

from texlate.compile.fixloop import fixloop


def _rewrite_rule(
    rid: str,
    order: int,
    marker: str,
    *,
    category: str = "boom",
    gate: str | None = None,
) -> dict:
    """种 marker 注释的 regex_rewrite 规则; ``gate`` 非空时挂 source_contains 凭据门。"""
    rule = {
        "id": rid,
        "phase": "loop",
        "order": order,
        "when": {"category": category},
        "action": {
            "kind": "regex_rewrite",
            "params": {
                "exts": [".tex"],
                "rewrites": [{"pattern": "hi", "repl": f"hi %{marker}"}],
            },
        },
    }
    if gate is not None:
        rule["condition"] = {"source_contains": gate}
    return rule


def _applied_rules(cell: dict) -> list[str]:
    return [
        a["rule"]
        for a in cell["actions"]
        if isinstance(a.get("round"), int) and a["round"] > 0
    ]


def _loop_rounds(cell: dict) -> list[dict]:
    """salvage 兜底轮挂 rounds 尾 (salvage=True), 不占地正式轮数。"""
    return [r for r in cell["rounds"] if not r.get("salvage")]


def test_gated_rule_dispatches_at_streak3(tmp_path: Path) -> None:
    """核心回归：凭据门第 3 条规则在 streak-3 轮必须拿到派发窗口。

    1206.0701/1306.0364 型：fix1 种 %G1 → fix2 凭 %G1 放行种 %G2 → fix3
    凭 %G2 放行。旧制 r3 (sig_n=3) 在派发前判 stuck, fix3 永不达; 新制
    r3 照常派发，fix3 应用后 r4 收敛 clean。"""
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[
            _rewrite_rule("fix1", 1, "G1"),
            _rewrite_rule("fix2", 2, "G2", gate="%G1"),
            _rewrite_rule("fix3", 3, "G3", gate="%G2"),
        ],
        taxonomy=BOOM_TAXONOMY,
    )
    eng = MockEngine([{"log": BOOM_LOG}] * 3 + [{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, ruleset=rs)
    assert cell["verdict"] == "clean"
    assert _applied_rules(cell) == ["fix1", "fix2", "fix3"]
    src = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert all(f"%G{i}" in src for i in (1, 2, 3))


def test_apply_apply_miss_settles_stuck(tmp_path: Path) -> None:
    """真耗尽格 verdict 保留：apply,apply,miss → 第 3 轮结算 stuck。

    与旧制同 verdict 同轮数，但结算点在派发后 (r3 主 + 次级全 miss) 而非
    派发前预判 —— 窗口给了，没规则够得着才烧轮终止。"""
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[
            _rewrite_rule("fix1", 1, "G1"),
            _rewrite_rule("fix2", 2, "G2"),
        ],
        taxonomy=BOOM_TAXONOMY,
    )
    cell = fixloop(tmp_path, MockEngine([{"log": BOOM_LOG}]), ruleset=rs)
    assert cell["verdict"] == "stuck"
    assert len(_loop_rounds(cell)) == 3  # noqa: PLR2004 - streak 3 触发线
    assert _applied_rules(cell) == ["fix1", "fix2"]


def test_apply_miss_streak2_unfixable(tmp_path: Path) -> None:
    """证据阈：apply,miss streak=2 < stuck_sig_repeat → unfixable 非 stuck。"""
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[_rewrite_rule("fix1", 1, "G1")],
        taxonomy=BOOM_TAXONOMY,
    )
    cell = fixloop(tmp_path, MockEngine([{"log": BOOM_LOG}]), ruleset=rs)
    assert cell["verdict"] == "unfixable:boom"
    assert len(_loop_rounds(cell)) == 2  # noqa: PLR2004
    assert _applied_rules(cell) == ["fix1"]


def test_apply_streak_extends_window_then_stuck(tmp_path: Path) -> None:
    """apply 轮次只续窗口：apply×3,miss → streak 4 结算 stuck。

    旧制 r3 (sig_n=3) 未派发即断，只吃 2 条 apply; 新制第 3 条规则拿到
    r3 窗口，烧轮止于 r4 派发枯竭 —— 多的一轮是真 apply 非空转。"""
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[
            _rewrite_rule("fix1", 1, "G1"),
            _rewrite_rule("fix2", 2, "G2"),
            _rewrite_rule("fix3", 3, "G3"),
        ],
        taxonomy=BOOM_TAXONOMY,
    )
    cell = fixloop(tmp_path, MockEngine([{"log": BOOM_LOG}]), ruleset=rs)
    assert cell["verdict"] == "stuck"
    assert len(_loop_rounds(cell)) == 4  # noqa: PLR2004 - mini_rs max_rounds=4
    assert _applied_rules(cell) == ["fix1", "fix2", "fix3"]


def test_sig_alternation_never_stuck(tmp_path: Path) -> None:
    """异签交替 streak 恒 1: 双标记格烧满 max_rounds 落 max_rounds 不 stuck。"""
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[
            _rewrite_rule("fixA1", 1, "A1"),
            _rewrite_rule("fixA2", 2, "A2"),
            _rewrite_rule("fixB1", 3, "B1", category="boomb"),
            _rewrite_rule("fixB2", 4, "B2", category="boomb"),
        ],
        taxonomy=[
            {"id": "boom", "scope": "head", "pattern": "BOOMA"},
            {"id": "boomb", "scope": "head", "pattern": "BOOMB"},
        ],
    )
    script = [{"log": "! BOOMA x\n"}, {"log": "! BOOMB x\n"}] * 4
    cell = fixloop(tmp_path, MockEngine(script), ruleset=rs)
    assert cell["verdict"] == "max_rounds"
    assert len(_loop_rounds(cell)) == 4  # noqa: PLR2004
    assert _applied_rules(cell) == ["fixA1", "fixB1", "fixA2", "fixB2"]


def test_first_miss_settles_immediately(tmp_path: Path) -> None:
    """零浪费闸：首轮即派发枯竭 streak=1 → unfixable, 不白烧到 streak 3。"""
    make_proj(tmp_path)
    rs = mini_rs(
        rules=[
            {
                "id": "other_cat_rule",
                "phase": "loop",
                "order": 1,
                "when": {"category": "other"},
                "action": {"kind": "run_tool", "params": {"argv": ["true"]}},
            }
        ],
        taxonomy=BOOM_TAXONOMY,
    )
    cell = fixloop(tmp_path, MockEngine([{"log": BOOM_LOG}]), ruleset=rs)
    assert cell["verdict"] == "unfixable:boom"
    assert len(_loop_rounds(cell)) == 1
