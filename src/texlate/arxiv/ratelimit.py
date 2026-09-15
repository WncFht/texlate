r"""请求纪律：按 host 限速桶 + (host, path) 断路器 + 日预算（docs/06 §1.2/§1.3）。

- **限速**：每 host ≥3.05s 全局间隔、零并发（官方 ToU：≤1 req/3s、单连接）。
  arxiv.org / export.arxiv.org / oaipmh.arxiv.org 三个独立桶。
- **断路器**：同 (host, path-class) 连续 2 次 429/406 → 按路径 park。实测
  限流按路径不按 host（export 的 /api 429 时 /src 照常 200）→ park 键带
  path-class；窗口实测 >30min、无 Retry-After → 初始 park 取 30min
  （docs/06 表内 15min 与其自身证据矛盾，export-probes.md 建议 30–60min
  起步），逐次翻倍封顶 2h。
- **日预算**：直采 ~150–200 发/日护栏（实测 ~150 发后 /src 回 406）。
- 状态 JSON 落盘（checkpoint 可恢复）；clock/sleep 可注入便于测试。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable

#: 每 host 最小请求间隔（官方 3s + 0.05s 余量）
GAP_SECONDS: Final = 3.05
#: 直采日预算（实测 ~150 发后 /src 406 渐升；留余量取 180）
DAILY_BUDGET: Final = 180
#: 初始 park 时长（惩罚窗口实测 >30min，取保守起步 30min）
PARK_BASE_SECONDS: Final = 1800.0
#: park 翻倍上限 2h（docs/06 §1.3）
PARK_MAX_SECONDS: Final = 7200.0
#: 断路器触发阈值：同 (host,path) 连续 N 次 429/406
BREAKER_STRIKES: Final = 2

_CONTENT_PATH_RE: Final = re.compile(
    r"^/(?:src|pdf|abs|html|e-print|list|rss|catchup|refs|cits|format)(?:/|$)"
)


def path_class(path: str) -> str:
    """URL path → 限流路径类（实测 429 按路径不按 host）。"""
    if path.startswith("/api/") or path == "/api":
        return "api"
    if path.startswith("/oai"):
        return "oai"
    if _CONTENT_PATH_RE.match(path):
        return "content"
    return "other"


def jitter(seed: str, span: float = 0.2) -> float:
    """确定性 ±span jitter（sha256 取流，不用 random）。"""
    h = hashlib.sha256(seed.encode()).digest()
    frac = int.from_bytes(h[:4], "big") / 0xFFFFFFFF
    return 1.0 - span + 2 * span * frac


class ParkedError(Exception):
    """该 (host, path-class) 在 park 窗口内。"""

    def __init__(self, host: str, klass: str, until: float) -> None:
        """记录 park 归属与截止时间。"""
        self.host = host
        self.klass = klass
        self.until = until
        super().__init__(f"{host}/{klass} parked until {until:.0f}")


class BudgetExhaustedError(Exception):
    """当日请求预算耗尽——转批量渠道或次日再来。"""

    def __init__(self, day: str, used: int, budget: int) -> None:
        """记录当日用量与预算。"""
        self.day = day
        self.used = used
        self.budget = budget
        super().__init__(f"daily budget exhausted: {used}/{budget} on {day}")


@dataclass(frozen=True, slots=True)
class RatePolicy:
    """限速参数集（默认值即 docs/06 校准值）。"""

    gap: float = GAP_SECONDS
    daily_budget: int = DAILY_BUDGET
    park_base: float = PARK_BASE_SECONDS
    park_max: float = PARK_MAX_SECONDS


@dataclass(slots=True)
class _Bucket:
    last_ts: float = 0.0
    consec_429: int = 0
    park_until: float = 0.0
    park_step: int = 0


class RateLimiter:
    """限速+断路器+日预算。状态 JSON 落盘可恢复。"""

    def __init__(
        self,
        state_path: Path | str | None = None,
        *,
        policy: RatePolicy | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """state_path 为 None 时纯内存（不落盘）。"""
        self.state_path = Path(state_path) if state_path else None
        self.policy = policy or RatePolicy()
        self._now = clock
        self._sleep = sleep
        self._buckets: dict[str, _Bucket] = {}
        self._day = ""
        self._requests_today = 0
        self._load()

    # ---- 状态持久化 ----

    def _key(self, host: str, klass: str) -> str:
        return f"{host}|{klass}"

    def _load(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._day = data.get("day", "")
        self._requests_today = int(data.get("requests_today", 0))
        for key, b in data.get("buckets", {}).items():
            self._buckets[key] = _Bucket(
                last_ts=float(b.get("last_ts", 0.0)),
                consec_429=int(b.get("consec_429", 0)),
                park_until=float(b.get("park_until", 0.0)),
                park_step=int(b.get("park_step", 0)),
            )

    def _save(self) -> None:
        if not self.state_path:
            return
        data = {
            "day": self._day,
            "requests_today": self._requests_today,
            "buckets": {
                k: {
                    "last_ts": b.last_ts,
                    "consec_429": b.consec_429,
                    "park_until": b.park_until,
                    "park_step": b.park_step,
                }
                for k, b in self._buckets.items()
            },
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.state_path)

    def _rollover(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime(self._now()))
        if self._day != today:
            self._day = today
            self._requests_today = 0

    # ---- 主接口 ----

    @property
    def requests_today(self) -> int:
        """当日已记请求数。"""
        self._rollover()
        return self._requests_today

    def parked_until(self, url: str) -> float:
        """该 URL 所在 (host,path) 桶的 park 截止时间（0 = 未 park）。"""
        parts = urlsplit(url)
        b = self._buckets.get(self._key(parts.netloc, path_class(parts.path)))
        return b.park_until if b else 0.0

    def acquire(self, url: str) -> None:
        """发请求前调用：限速等待 + park/预算检查。计一次请求。"""
        parts = urlsplit(url)
        host, klass = parts.netloc, path_class(parts.path)
        key = self._key(host, klass)
        b = self._buckets.setdefault(key, _Bucket())
        now = self._now()
        if b.park_until > now:
            raise ParkedError(host, klass, b.park_until)
        self._rollover()
        if self._requests_today >= self.policy.daily_budget:
            raise BudgetExhaustedError(
                self._day, self._requests_today, self.policy.daily_budget
            )
        # pacing：每 host 全局间隔（跨 path-class 合并计时）
        host_last = max(
            (x.last_ts for k, x in self._buckets.items() if k.startswith(host + "|")),
            default=0.0,
        )
        wait = host_last + self.policy.gap - now
        if wait > 0:
            self._sleep(wait)
            now = self._now()
        b.last_ts = now
        self._requests_today += 1
        self._save()

    def report(self, url: str, status: int) -> None:
        """请求返回后调用：维护 429/406 断路器计数。"""
        parts = urlsplit(url)
        key = self._key(parts.netloc, path_class(parts.path))
        b = self._buckets.setdefault(key, _Bucket())
        if status in (HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.NOT_ACCEPTABLE):
            # 429=边缘限流；406=IP 配额惩罚窗口（实测 /src 分钟级 406）
            b.consec_429 += 1
            if b.consec_429 >= BREAKER_STRIKES:
                dur = min(
                    self.policy.park_base * (2**b.park_step), self.policy.park_max
                )
                dur *= jitter(key + str(self._now()))
                b.park_until = self._now() + dur
                b.park_step += 1
        elif (
            HTTPStatus.OK <= status < HTTPStatus.BAD_REQUEST
            or status == HTTPStatus.NOT_FOUND
        ):
            # 成功/确定性 404 都证明窗口已过
            b.consec_429 = 0
            b.park_step = 0
            b.park_until = 0.0
        self._save()
