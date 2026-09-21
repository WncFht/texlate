"""logtrunc Guard A+B 钉 —— halt 截断 log 与内容腰斩否决 acceptable_pdf/clean。

Adjudication #10 (tmp/lane-pgdrop/gate-design.md):

  Guard A — halt_on_error 下 ``n_bang>0`` ⇒ log 截在首错, 计数是下界非
    测量值, 证不了 errors≤clean_err_max: 轮 entry 记 ``log_truncated``,
    汇总段压 clean→dirty_pdf 且禁升 acceptable_pdf; ``_xelatex.compile``
    侧给 CompRes 盖 ``res.log_truncated`` → judge 记测量缺陷判 partial。
    锚点形: 1708.07366 (rc=1 残 pdf n_bang=1 曾判 acceptable) 与
    2002.05660 (截断 log 把 106→1 错伪报改进)。
  Guard B — 终产物字节相对本 run 最强 pdf (floor 快照 ∪ 逐轮峰值) 腰斩
    >50% ⇒ ``content_regressed``: nonstopmode 定败残页等 log 信号够不
    到的补位; clean→dirty_pdf 同降, acceptable_pdf 同封。

钉:
  a) halt 截断末轮 (pdf+1 错) → log_truncated 置位, 留 dirty_pdf 不升;
  b) 非 halt 引擎同形 → 不置位, acceptable_pdf 旧路保留;
  c) ``_xelatex.compile`` 盖章三态: halt+err→True / best_effort→False /
     halt_on_error=False→False;
  d) judge: 盖章 res → partial+reason; baseline kwarg → content_regressed;
  e) Guard B: floor 大 pdf + 末轮腰斩 → content_regressed + 不升;
  f) 阴性: 腰斩比 ≥50% → acceptable_pdf 不误伤; 截断缺席 → clean 不误伤。
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from test_fixloop_loop import (
    BOOM_LOG,
    BOOM_TAXONOMY,
    CLEAN_LOG,
    MockEngine,
    MockRes,
    make_proj,
    mini_rs,
    run_tool_rules,
)

from texlate.compile.engine import CompRes, XelatexEngine
from texlate.compile.fixloop import Ruleset, fixloop
from texlate.compile.judge import judge
from texlate.compile.loginfo import LogInfo


class _SizedMockRes(MockRes):
    """MockRes + spec ``pdf_size`` —— 变尺寸 pdf 供 Guard B 腰斩构造。"""

    def __init__(self, wdir: Path, main: str, spec: dict | str) -> None:
        super().__init__(wdir, main, spec)
        if self.pdf is not None and isinstance(spec, dict) and "pdf_size" in spec:
            self.pdf.write_bytes(b"x" * int(spec["pdf_size"]))
            self.pdf_bytes = self.pdf.stat().st_size


class _SizedEngine(MockEngine):
    """逐轮 spec 产变尺寸 pdf 的引擎; ``halt_on_error`` 可开关。"""

    def __init__(self, script: list, *, halt_on_error: bool = False) -> None:
        super().__init__(script)
        self.halt_on_error = halt_on_error

    def compile(
        self, wdir: Path, main: str, *, passes: int = 2, **_kw: object
    ) -> _SizedMockRes:
        del passes, _kw
        i = min(self.rounds, len(self.script) - 1)
        self.rounds += 1
        return _SizedMockRes(Path(wdir), main, self.script[i])


def _rs(loop_cfg: dict | None = None) -> Ruleset:
    return mini_rs(rules=[], taxonomy=BOOM_TAXONOMY, loop_cfg=loop_cfg)


# ---------------------------------------------------------------- Guard A
def test_halt_truncated_round_blocks_acceptable(tmp_path: Path) -> None:
    """pin a: halt 截断末轮 (pdf+1 错) → log_truncated=True + dirty_pdf。

    旧路 ``final_errors=1 ≤ clean_err_max`` → acceptable_pdf; 截断 log 的
    n_bang 是下界证不了 ≤3 → Guard A 封升 (1708.07366/2002.05660 形)。
    """
    eng = _SizedEngine([{"log": BOOM_LOG, "pdf": True}], halt_on_error=True)
    cell = fixloop(make_proj(tmp_path), eng, ruleset=_rs())
    assert cell["rounds"][0]["log_truncated"] is True
    assert cell["verdict"] == "dirty_pdf"
    assert cell["verdict"] != "acceptable_pdf"


def test_nonhalt_same_shape_promotes(tmp_path: Path) -> None:
    """pin b: 非 halt 引擎同形 → 不置位, ≤3 错 dirty 照旧升 acceptable_pdf。"""
    eng = _SizedEngine([{"log": BOOM_LOG, "pdf": True}], halt_on_error=False)
    cell = fixloop(make_proj(tmp_path), eng, ruleset=_rs())
    assert cell["rounds"][0]["log_truncated"] is False
    assert cell["verdict"] == "acceptable_pdf"


def test_halt_clean_round_not_truncated(tmp_path: Path) -> None:
    """halt 引擎但 0 错 → 编译没截 (n_bang=0) → log_truncated=False + clean。"""
    eng = _SizedEngine([{"log": CLEAN_LOG, "pdf": True}], halt_on_error=True)
    cell = fixloop(make_proj(tmp_path), eng, ruleset=_rs())
    assert all(not r["log_truncated"] for r in cell["rounds"])
    assert cell["verdict"] == "clean"


def test_stuck_truncated_end_blocked(tmp_path: Path) -> None:
    """stuck + 截断末轮 → split 压 dirty_pdf 且 Guard A 封 acceptable 升档。

    烧轮终止路径 (verdict 集合 None/max_rounds/stuck 的 split 臂) 同样
    受闸——截断轮只经 ``last.get("log_truncated")`` 进入 dirty 判定。
    """
    rs = mini_rs(rules=run_tool_rules(2), taxonomy=BOOM_TAXONOMY)
    eng = _SizedEngine([{"log": BOOM_LOG, "pdf": True}], halt_on_error=True)
    cell = fixloop(
        make_proj(tmp_path),
        eng,
        ruleset=rs,
        runner=lambda _a, _t, _w: (0, "", 0.0, False),
    )
    assert cell["rounds"][-1]["log_truncated"] is True
    assert cell["verdict"] == "dirty_pdf"
    assert cell["verdict"] != "acceptable_pdf"


# ---------------------------------------------------------------- _xelatex 盖章
def _fake_xe_run(log: str) -> Callable:
    """run_process 替身: 写 main.pdf/main.log, rc=1 镜像 halt 首错即停。"""

    def run(  # noqa: PLR0913
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        out_cap: int = 8 * 1024 * 1024,
        should_cancel: Callable[[], bool] | None = None,
    ) -> tuple[int | None, str, float, bool]:
        _ = (cmd, env, timeout, out_cap, should_cancel)
        out = Path(cwd).resolve()
        (out / "main.pdf").write_bytes(b"%PDF-fake")
        (out / "main.log").write_text(log, encoding="utf-8")
        return 1, "", 0.1, False

    return run


def test_xelatex_stamp_three_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pin c: res.log_truncated = halt_on_error ∧ 非 best_effort ∧ n_errors>0。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr("texlate.compile.engine.run_process", _fake_xe_run(BOOM_LOG))
    eng = XelatexEngine(binary="/x/xelatex")  # halt_on_error=True 缺省
    res = eng.compile(tmp_path, "main.tex", passes=1)
    assert res.log.n_errors == 1
    assert res.log_truncated is True
    # best_effort 去 -halt-on-error 跑全程 → 同错数也不截
    res_be = eng.compile(tmp_path, "main.tex", passes=1, best_effort=True)
    assert res_be.log_truncated is False
    # 引擎级 nonstop (halt_on_error=False) → log 完整不截
    eng2 = XelatexEngine(binary="/x/xelatex", halt_on_error=False)
    res_ns = eng2.compile(tmp_path, "main.tex", passes=1)
    assert res_ns.log_truncated is False


def test_xelatex_stamp_clean_log_not_truncated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0 错健康 log → 没截 → log_truncated=False。"""
    (tmp_path / "main.tex").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr("texlate.compile.engine.run_process", _fake_xe_run(CLEAN_LOG))
    eng = XelatexEngine(binary="/x/xelatex")
    res = eng.compile(tmp_path, "main.tex", passes=1)
    assert res.log.n_errors == 0
    assert res.log_truncated is False


# ---------------------------------------------------------------- judge 面
def _res_with_pdf(tmp_path: Path, size: int, *, n_errors: int = 0) -> CompRes:
    pdf = tmp_path / "main.pdf"
    pdf.write_bytes(b"x" * size)
    return CompRes(
        engine="xelatex",
        ok=True,
        rc=0,
        pdf=pdf,
        pdf_bytes=size,
        log=LogInfo(n_errors=n_errors),
    )


def test_judge_log_truncated_partial(tmp_path: Path) -> None:
    """pin d-a: 盖章 res + pdf → partial, ``log_truncated`` 进 reasons。"""
    res = _res_with_pdf(tmp_path, 4000, n_errors=1)
    res.log_truncated = True
    v = judge(res)
    assert v.status == "partial"
    assert "log_truncated" in v.reasons


def test_judge_no_stamp_still_clean(tmp_path: Path) -> None:
    """阴性: 无盖章字段 (getattr 容错) + 干净 log → clean 不误伤。"""
    res = _res_with_pdf(tmp_path, 4000)
    assert judge(res).status == "clean"


def test_judge_baseline_content_regressed(tmp_path: Path) -> None:
    """pin d-b: baseline 供入 + 腰斩 → ``content_regressed:<ratio>`` → partial。"""
    res = _res_with_pdf(tmp_path, 3000)
    v = judge(res, baseline_pdf_bytes=10000)
    assert v.status == "partial"
    assert "content_regressed:0.300" in v.reasons


def test_judge_baseline_absent_or_above_half(tmp_path: Path) -> None:
    """阴性: baseline 缺席 (standalone 调用面) 或 ≥50% → 闸不启用。"""
    res = _res_with_pdf(tmp_path, 3000)
    assert judge(res).status == "clean"  # baseline 缺席
    assert judge(res, baseline_pdf_bytes=6000).status == "clean"  # 恰 50% 不腰斩
    assert judge(res, baseline_pdf_bytes=0).status == "clean"  # 0 baseline 除零豁免


# ---------------------------------------------------------------- Guard B
def test_guard_b_shrunk_blocks_acceptable(tmp_path: Path) -> None:
    """pin e-a: floor 10KB + 末轮 3KB (1 错) → content_regressed + 留 dirty_pdf。

    旧路 1≤3 错升 acceptable_pdf; 腰斩残页 = 真内容回归 → Guard B 封升。
    """
    (tmp_path / "main.pdf").write_bytes(b"x" * 10000)  # 入口产物 → floor 快照
    eng = _SizedEngine([{"log": BOOM_LOG, "pdf": True, "pdf_size": 3000}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=_rs())
    assert cell["content_regressed"] == 0.3  # noqa: PLR2004 - 腰斩阈值闸
    assert cell["verdict"] == "dirty_pdf"
    assert cell["verdict"] != "acceptable_pdf"


def test_guard_b_clean_demote(tmp_path: Path) -> None:
    """pin e-b: floor 10KB + 0 错腰斩 3KB → clean 压成 dirty_pdf。

    0 错编译也可腰斩 (修复误删附录类)——clean 不豁免内容回归。
    """
    (tmp_path / "main.pdf").write_bytes(b"x" * 10000)
    eng = _SizedEngine([{"log": CLEAN_LOG, "pdf": True, "pdf_size": 3000}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=_rs())
    assert cell["content_regressed"] == 0.3  # noqa: PLR2004 - 腰斩阈值闸
    assert cell["verdict"] == "dirty_pdf"


def test_guard_b_above_half_keeps_acceptable(tmp_path: Path) -> None:
    """pin f-a: 末轮 6KB ≥ floor 10KB 的 50% → 不腰斩 → acceptable_pdf 照旧。"""
    (tmp_path / "main.pdf").write_bytes(b"x" * 10000)
    eng = _SizedEngine([{"log": BOOM_LOG, "pdf": True, "pdf_size": 6000}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=_rs())
    assert "content_regressed" not in cell
    assert cell["verdict"] == "acceptable_pdf"


def test_guard_b_peak_baseline(tmp_path: Path) -> None:
    """逐轮峰值计入 baseline: r1 产 9KB 后又缩回 3KB → 相对峰值腰斩。

    floor=0 (入口无 pdf) 格也被 run 内峰值覆盖——census ``no_baseline``
    盲区的关闭面。r1 派发 apply → r2 同签 dedup miss → dirty_pdf 收尾。
    """
    rs = mini_rs(rules=run_tool_rules(1), taxonomy=BOOM_TAXONOMY)
    eng = _SizedEngine(
        [
            {"log": BOOM_LOG, "pdf": True, "pdf_size": 9000},
            {"log": BOOM_LOG, "pdf": True, "pdf_size": 3000},
        ]
    )
    cell = fixloop(
        make_proj(tmp_path),
        eng,
        ruleset=rs,
        runner=lambda _a, _t, _w: (0, "", 0.0, False),
    )
    # floor 快照 = 首轮 pdf 9000 (入口无产物的首轮兜底); baseline=9000,
    # 末轮 3000 → ratio 0.333 腰斩。
    assert cell["content_regressed"] == 0.333  # noqa: PLR2004 - 腰斩阈值闸
    assert cell["verdict"] == "dirty_pdf"


def test_guard_b_floor_restore_exempt(tmp_path: Path) -> None:
    """floor 兜回格: 终产物即快照本体 (final=floor_bytes) → 不记腰斩。

    入口 pdf 在 fixloop 打死后被原样兜回——交付物=入口态, 非内容回归;
    ≤3 错的兜回格照旧升 acceptable_pdf (floor 语义不被 Guard B 误伤)。
    """
    (tmp_path / "main.pdf").write_bytes(b"x" * 10000)
    eng = _SizedEngine([{"log": BOOM_LOG, "pdf": False}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=_rs())
    assert cell["floor_restored"] is True
    assert cell["final_pdf"] is True
    assert "content_regressed" not in cell
    assert cell["verdict"] == "acceptable_pdf"
