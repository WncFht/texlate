"""B6 写后复验钉 —— 末次编译后 apply 落件 → 常参 pass-1 复编刷末态证据。

w13spec B6 memo (2503.10148/2606.19622): 末轮 stub 写在末编 0.6-0.7s
后, loop 烧尽 → verdict assembly 消费写前轮 entry——``max_rounds``
+pdf 格 dirty→acceptable_pdf 升档与 Guard-A/B 判据全吃残证 (修复
成功的格被压成 dirty)。复验槽在 warn-preempt 与 salvage 之间:
``ledger.actions`` 账顶相对末次迭代编译前增长 (轮内 apply/gate/
post warn-preempt 统一入账点) 即补一发非 best_effort 编译, entry
按轮形落 (``reverify: True`` 标记) 让下游公式零改消费。

钉:
  a) 末轮 apply + 复验 clean → last=复验 entry, max_rounds→clean 升档;
  b) clean 出路 (含 apply 后 clean 收敛) → 零复编;
  c) 无 post-final 写 (末轮派发枯竭收场) → 不复验;
  d) halt 引擎复验带错 → log_truncated 置位 + Guard A 封 acceptable;
  e) 轮内 warn-preempt apply 同样触发复验;
  f) 0 错 warn-cat 复验不升 clean——spec clean 式 cat∉warn_cats 子句。
"""

from pathlib import Path

from _fixloopkit import (
    BOOM_LOG,
    BOOM_TAXONOMY,
    CLEAN_LOG,
    MockEngine,
    make_proj,
    mini_rs,
    run_tool_rules,
)

from texlate.compile.fixloop import Ruleset, fixloop

MC_LOG = BOOM_LOG + "Missing character: There is no A (U+0041) in font cmr10\n"
# 0 错 + missing_char 警告行——warn-cat 分类入口 (warn_id 命中 warnings)。
WARN_LOG = (
    "This is pdfTeX\n"
    "Missing character: There is no A (U+0041) in font cmr10\n"
    "Output written on main.pdf (1 page).\n"
)


class _HaltEngine(MockEngine):
    """``halt_on_error`` 置位的 MockEngine——Guard A 字段消费断言用。"""

    halt_on_error = True


def _rs(rules: list[dict], loop_cfg: dict | None = None) -> Ruleset:
    return mini_rs(rules=rules, taxonomy=BOOM_TAXONOMY, loop_cfg=loop_cfg)


def _warn_rs(rules: list[dict], loop_cfg: dict | None = None) -> Ruleset:
    """带 missing_char warnings 面 + warn-cat 分类行的合成 ruleset。"""
    return mini_rs(
        rules=rules,
        taxonomy=[
            *BOOM_TAXONOMY,
            {
                "id": "warn_missing_char",
                "scope": "warnings",
                "warn_id": "missing_char",
            },
        ],
        loop_cfg=loop_cfg,
        warnings=[{"id": "missing_char", "pattern": "Missing character:"}],
    )


def _runner(_a: object, _t: object, _w: object) -> tuple[int, str, float, bool]:
    return 0, "", 0.0, False


# ---------------------------------------------------------------- a) 升档
def test_final_round_write_reverify_promotes(tmp_path: Path) -> None:
    """pin a: 末轮 apply 落件 → 复验编译取证 → 修好的格 max_rounds→clean。

    无复验时 ``rounds[-1]`` 是写前 BOOM 证据, verdict 压 dirty/acceptable;
    复验 entry 的 0 错新证让既有公式自然落成 clean。
    """
    rs = _rs(run_tool_rules(2), {"max_rounds": 2, "compile_passes": 1})
    eng = MockEngine(
        [
            {"log": BOOM_LOG, "pdf": True},
            {"log": BOOM_LOG, "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs, runner=_runner)
    last = cell["rounds"][-1]
    assert last.get("reverify") is True
    assert last["n_errors"] == 0
    assert cell["final_errors"] == 0
    assert cell["verdict"] == "clean"
    assert eng.rounds == 3  # noqa: PLR2004 - r1+r2+复验


def test_reverify_residual_error_stays_dirty(tmp_path: Path) -> None:
    """a 的对照: 复验仍有 1 错 (非 halt 不截) → dirty→acceptable_pdf 照升。

    复验不捏造修复——写后残错如实记账, 升档走既有 acceptable 公式。
    """
    rs = _rs(run_tool_rules(2), {"max_rounds": 2, "compile_passes": 1})
    eng = MockEngine([{"log": BOOM_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs, runner=_runner)
    last = cell["rounds"][-1]
    assert last.get("reverify") is True
    assert last["n_errors"] == 1
    assert cell["verdict"] == "acceptable_pdf"


# ---------------------------------------------------------------- b) clean 零开销
def test_clean_exit_zero_extra_compile(tmp_path: Path) -> None:
    """pin b-1: 首轮收敛 → 无派发无写 → 复验门构造性不燃, 零复编。"""
    rs = _rs(run_tool_rules(1), {"compile_passes": 1})
    eng = MockEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs, runner=_runner)
    assert cell["verdict"] == "clean"
    assert eng.rounds == 1
    assert not any(r.get("reverify") for r in cell["rounds"])


def test_clean_after_apply_no_reverify(tmp_path: Path) -> None:
    """pin b-2: r1 apply → r2 编译即写后验证 → clean break 不再补验。

    轮内 apply 的写由下一轮编译天然复验——只有「末次」编译后的写
    才欠一发复编 (构造保证 clean 出路零复验)。
    """
    rs = _rs(run_tool_rules(1), {"compile_passes": 1})
    eng = MockEngine(
        [
            {"log": BOOM_LOG, "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs, runner=_runner)
    assert cell["verdict"] == "clean"
    assert eng.rounds == 2  # noqa: PLR2004 - r1+r2, 零复验
    assert not any(r.get("reverify") for r in cell["rounds"])


# ---------------------------------------------------------------- c) 无写不复验
def test_no_post_final_write_no_reverify(tmp_path: Path) -> None:
    """pin c: 末轮派发枯竭 (dedup miss) 收场 → 树自末编未变, 不复验。"""
    rs = _rs(run_tool_rules(1), {"compile_passes": 1})
    eng = MockEngine([{"log": BOOM_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs, runner=_runner)
    # r1 apply fix1; r2 fix1 dedup → 无 apply → dirty_pdf → acceptable
    assert cell["verdict"] == "acceptable_pdf"
    assert eng.rounds == 2  # noqa: PLR2004 - 零复验零兜底
    assert not any(r.get("reverify") for r in cell["rounds"])


# ---------------------------------------------------------------- d) Guard A 兼容
def test_halt_reverify_error_blocks_acceptable(tmp_path: Path) -> None:
    """pin d: halt 引擎复验带错 → log_truncated 置位 → Guard A 封升档。

    复验 entry 与轮 entry 同字段面——Guard A/B 的
    died/log_truncated/pdf_bytes 读取零改兼容。
    """
    rs = _rs(run_tool_rules(2), {"max_rounds": 2, "compile_passes": 1})
    eng = _HaltEngine([{"log": BOOM_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs, runner=_runner)
    last = cell["rounds"][-1]
    assert last.get("reverify") is True
    for k in (
        "round",
        "pdf",
        "pdf_bytes",
        "died",
        "log_truncated",
        "driver_fatal",
        "n_errors",
        "category",
        "payload",
        "warnings",
        "warnings_sys",
        "line_no",
        "file_stack",
        "sec",
    ):
        assert k in last
    assert last["log_truncated"] is True
    assert cell["verdict"] == "dirty_pdf"


# ---------------------------------------------------------------- e) warn-preempt 触发
def test_warn_preempt_apply_triggers_reverify(tmp_path: Path) -> None:
    """pin e: 末轮 warn-preempt apply 同属 post-final 写 → 复验点火。"""
    rules = [
        *run_tool_rules(1),
        {
            "id": "mcfix",
            "phase": "loop",
            "order": 9,
            "when": {"category": "warn_missing_char"},
            "action": {"kind": "run_tool", "params": {"argv": ["true"]}},
        },
    ]
    rs = _warn_rs(rules, {"max_rounds": 2, "compile_passes": 1})
    eng = MockEngine(
        [
            {"log": MC_LOG, "pdf": True},
            {"log": MC_LOG, "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs, runner=_runner)
    assert any(a.get("via") == "warn_preempt" for a in cell["actions"])
    last = cell["rounds"][-1]
    assert last.get("reverify") is True
    assert cell["verdict"] == "clean"


# ---------------------------------------------------------------- f) warn-cat 不升 clean
def test_reverify_warn_cat_stays_acceptable(tmp_path: Path) -> None:
    """pin f: 0 错但 cat∈warn_cats 的复验 entry 不升 clean (spec clean 式)。

    汇总公式 warn_cats 子句的反向钉——缺了它 0-err warn 残格会被
    B6 复验误升 clean (旧 ``or 9`` 靠副作用碰巧压住)。
    """
    rules = [
        {
            "id": "mcfix",
            "phase": "loop",
            "order": 1,
            "when": {"category": "warn_missing_char"},
            "action": {"kind": "run_tool", "params": {"argv": ["true"]}},
        }
    ]
    rs = _warn_rs(rules, {"max_rounds": 1, "compile_passes": 1})
    eng = MockEngine([{"log": WARN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs, runner=_runner)
    last = cell["rounds"][-1]
    assert last.get("reverify") is True
    assert last["n_errors"] == 0
    assert last["category"] == "warn_missing_char"
    assert cell["verdict"] == "acceptable_pdf"
    assert eng.rounds == 2  # noqa: PLR2004 - r1+复验
