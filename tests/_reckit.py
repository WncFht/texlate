"""stagerun records 行共享工厂——五处 ``_rec`` 复刻收敛为 ``make_rec`` 单源。

schema 全集：``id/stage/arm/upstream/status/dur_s=1.0/metrics={}/errors=[]/
sig=""``，``**over`` 末位 update 覆盖任意字段。收敛口径（沿用
``_fuzzkit``/``_segkit`` 抽取先例——只抽不写回处另案）：

- ``test_fuzz_scorecard``/``test_bench_triage`` 直用（缺省 ``arm="-"``/
  ``upstream=""`` 即同形）。
- ``test_bench_rundiff`` 钉 ``arm="zh", upstream="mock"``；
  ``test_gate_scorecard_hardening`` 钉 ``upstream="mock"`` + ``arm`` 按
  ``stage=="compile"`` 取 ``"zh"``/``"fix"``；``test_bench_harness`` 包为
  ``make_rec(pid, "compile", status, arm="zh")``——增补字段经 ``.get``+
  falsy 归一验证惰性（``dur_s`` 仅喂未断言的 ``wall_s``）。
- ``bench/py/triage.py`` 自检内 ``rec`` 同形可选第 6 处。
"""

from __future__ import annotations


def make_rec(
    pid: str,
    stage: str,
    status: object,
    *,
    arm: str = "-",
    upstream: str = "",
    **over: object,
) -> dict:
    """records 行全 schema 构造——缺省字段补齐后 ``**over`` 覆盖。"""
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
