"""bench/stagerun records 工厂——``rec(pid, stage, status, *, arm, upstream, **over)``。

``test_bench_*``/``test_*_scorecard*`` 簇逐文件复刻的 ``_rec`` 私有副本归此一处
（沿用 ``_fixloopkit``/``_fuzzkit``/``_segkit`` 抽取先例——只抽不写回，既有
文件保持原样）。canonical 九字段行：
``{id, stage, arm, upstream, status, dur_s, metrics, errors, sig}``——``over``
透传覆盖任意字段。

adopter deltas（各文件在调用点/kwarg 层吸收，kit 不派生变体签名）：

- ``test_bench_triage`` / ``test_fuzz_scorecard``：签名与字段逐字等价，
  ``_rec`` 直换 ``rec``。
- ``test_bench_rundiff``：``arm="zh", upstream="mock"`` 两 kwarg 即等价。
- ``test_gate_scorecard_hardening``：``arm`` 按 stage 取 ``"zh"``/``"fix"``
  且不产 ``dur_s``——调用方本地 wrapper ``del r["dur_s"]`` 吸收。
- ``test_bench_harness``：``_rec(pid, status)`` 窄签名——stage 固定
  ``"compile"``、字段集 ``{id, stage, arm, status, sig}``，走 per-file
  wrapper（``rec`` 产物 pop 多余键）。
"""

from __future__ import annotations


def rec(
    pid: str,
    stage: str,
    status: object,
    *,
    arm: str = "-",
    upstream: str = "",
    **over: object,
) -> dict:
    """合成 stagerun record 行——九字段 canonical 形 + ``over`` 任意覆盖。"""
    r = {
        "id": pid,
        "stage": stage,
        "arm": arm,
        "upstream": upstream,
        "status": status,
        "dur_s": 1.0,
        "metrics": {},
        "errors": [],
        "sig": "",
    }
    r.update(over)
    return r
