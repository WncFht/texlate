import json
from http import HTTPStatus
from pathlib import Path

import pytest

from texlate.arxiv.ratelimit import (
    BREAKER_STRIKES,
    BudgetExhaustedError,
    ParkedError,
    RateLimiter,
    RatePolicy,
    jitter,
    path_class,
)

GAP = 3.05
PARK_LO = 1800.0 * 0.79  # park_base * (1-jitter 下限)
PARK_HI = 1800.0 * 1.21
PARK2_LO = 3600.0 * 0.79
PARK2_HI = 3600.0 * 1.21
PARKCAP_HI = 7200.0 * 1.21
TWO_REQUESTS = 2


class _Clock:
    def __init__(self) -> None:
        self.t = 1_700_000_000.0  # 一个真实 epoch（day  rollover 语义正常）
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.slept.append(d)
        self.t += d


def _limiter(clk: _Clock, **kw: float) -> RateLimiter:
    return RateLimiter(policy=RatePolicy(**kw), clock=clk.now, sleep=clk.sleep)


def test_path_class() -> None:
    assert path_class("/api/query") == "api"
    assert path_class("/oai") == "oai"
    assert path_class("/oai2") == "oai"
    assert path_class("/src/2001.00001") == "content"
    assert path_class("/abs/2001.00001") == "content"
    assert path_class("/pdf/x.pdf") == "content"
    assert path_class("/other/thing") == "other"


def test_jitter_deterministic() -> None:
    a = jitter("seed")
    assert a == jitter("seed")
    lo, hi = 0.8, 1.2
    assert lo <= a <= hi
    assert jitter("a") != jitter("b")


def test_pacing_per_host() -> None:
    clk = _Clock()
    rl = _limiter(clk)
    url = "https://arxiv.org/src/2001.00001"
    rl.acquire(url)  # 首次不等待
    assert not clk.slept
    rl.acquire(url)  # 同 host 第二次等 ~3.05s
    assert clk.slept == pytest.approx([GAP])
    # 另一 host 独立桶——立即放行
    before = len(clk.slept)
    rl.acquire("https://export.arxiv.org/src/2001.00001")
    assert len(clk.slept) == before


def test_pacing_shared_across_path_class() -> None:
    """同一 host 的不同 path-class 共享 pacing（每 host 全局间隔）。"""
    clk = _Clock()
    rl = _limiter(clk)
    rl.acquire("https://arxiv.org/src/2001.00001")
    rl.acquire("https://arxiv.org/api/query?x=1")
    assert clk.slept == pytest.approx([GAP])


def test_breaker_park_per_path() -> None:
    clk = _Clock()
    rl = _limiter(clk)
    src = "https://arxiv.org/src/x"
    api = "https://arxiv.org/api/query"
    for _ in range(BREAKER_STRIKES):
        rl.acquire(src)
        clk.t += GAP
        rl.report(src, HTTPStatus.TOO_MANY_REQUESTS)
    until = rl.parked_until(src)
    assert PARK_LO <= until - clk.t <= PARK_HI
    # src 桶已 park；api 桶未受影响（park 按路径不按 host）
    rl.acquire(api)
    with pytest.raises(ParkedError):
        rl.acquire(src)


def test_breaker_doubling_and_cap() -> None:
    """park 翻倍：初次 ~1800s；窗口过后再 429 → 单发即重 park ~3600 → ~7200 封顶。

    consec_429 过阈后不归零——过期后再吃 429 一次就按 park_step 翻倍重 park。
    """
    clk = _Clock()
    rl = _limiter(clk)
    src = "https://arxiv.org/src/x"
    first_until = _trip(rl, clk, src)
    assert PARK_LO <= first_until - clk.t <= PARK_HI
    clk.t = first_until + 1
    second_until = _repark(rl, clk, src)
    assert PARK2_LO <= second_until - clk.t <= PARK2_HI
    clk.t = second_until + 1
    third_until = _repark(rl, clk, src)
    assert third_until - clk.t <= PARKCAP_HI


def _trip(rl: RateLimiter, clk: _Clock, url: str) -> float:
    for _ in range(BREAKER_STRIKES):
        rl.acquire(url)
        clk.t += GAP
        rl.report(url, HTTPStatus.TOO_MANY_REQUESTS)
    return rl.parked_until(url)


def _repark(rl: RateLimiter, clk: _Clock, url: str) -> float:
    rl.acquire(url)
    clk.t += GAP
    rl.report(url, HTTPStatus.TOO_MANY_REQUESTS)
    return rl.parked_until(url)


def test_success_resets_breaker() -> None:
    clk = _Clock()
    rl = _limiter(clk)
    src = "https://arxiv.org/src/x"
    rl.acquire(src)
    clk.t += GAP
    rl.report(src, HTTPStatus.TOO_MANY_REQUESTS)  # 1 strike
    rl.acquire(src)
    clk.t += GAP
    rl.report(src, HTTPStatus.OK)  # 清零
    rl.acquire(src)
    clk.t += GAP
    rl.report(src, HTTPStatus.TOO_MANY_REQUESTS)  # 又是 1——不 park
    assert rl.parked_until(src) == 0.0


def test_404_resets_breaker() -> None:
    clk = _Clock()
    rl = _limiter(clk)
    src = "https://arxiv.org/src/x"
    rl.acquire(src)
    clk.t += GAP
    rl.report(src, HTTPStatus.TOO_MANY_REQUESTS)
    rl.acquire(src)
    clk.t += GAP
    rl.report(src, HTTPStatus.NOT_FOUND)
    rl.acquire(src)
    clk.t += GAP
    rl.report(src, HTTPStatus.TOO_MANY_REQUESTS)
    assert rl.parked_until(src) == 0.0


def test_daily_budget() -> None:
    clk = _Clock()
    rl = _limiter(clk, daily_budget=3)
    for _ in range(3):
        rl.acquire("https://arxiv.org/src/x")
        clk.t += GAP
    with pytest.raises(BudgetExhaustedError):
        rl.acquire("https://arxiv.org/src/x")


def test_state_persistence(tmp_path: Path) -> None:
    clk = _Clock()
    state = tmp_path / "rl.json"
    rl = RateLimiter(state, clock=clk.now, sleep=clk.sleep)
    rl.acquire("https://arxiv.org/src/x")
    clk.t += GAP
    rl.report("https://arxiv.org/src/x", HTTPStatus.TOO_MANY_REQUESTS)
    rl.acquire("https://arxiv.org/src/x")
    clk.t += GAP
    rl.report("https://arxiv.org/src/x", HTTPStatus.TOO_MANY_REQUESTS)
    assert state.exists()
    data = json.loads(state.read_text())
    assert data["requests_today"] == TWO_REQUESTS

    clk2 = _Clock()
    clk2.t = clk.t
    rl2 = RateLimiter(state, clock=clk2.now, sleep=clk2.sleep)
    assert rl2.requests_today == TWO_REQUESTS
    with pytest.raises(ParkedError):
        rl2.acquire("https://arxiv.org/src/x")


def test_load_corrupt_state_starts_clean(tmp_path: Path) -> None:
    """合法 JSON 但字段类型错 → 干净起步（以前 int("x") 直接炸 init）。"""
    state = tmp_path / "rl.json"
    state.write_text(
        '{"day": 5, "requests_today": "oops", "buckets": {"h|c": {"last_ts": "bad"}}}'
    )
    clk = _Clock()
    rl = RateLimiter(state, clock=clk.now, sleep=clk.sleep)
    assert rl.requests_today == 0
    rl.acquire("https://arxiv.org/src/x")  # 不拦请求路径


def test_parked_until_expired_is_zero() -> None:
    """过期 park 返回 0（文档承诺 0=未 park），不再回吐历史时间戳。"""
    clk = _Clock()
    rl = _limiter(clk)
    src = "https://arxiv.org/src/x"
    until = _trip(rl, clk, src)
    assert rl.parked_until(src) == until > 0
    clk.t = until + 1
    assert rl.parked_until(src) == 0.0
