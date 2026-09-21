#!/usr/bin/env python3
r"""gwpilot — 见缝插针批跑驱动：断点续跑队列（主）+ 自适应并发闸代理（兜底）。

2026-09-18 起上游网关已上线 fg/bg 分级准入：批跑用 bg 令牌直连即被
闸内调度（fg 动态预留、bg 闸内排队 ~120s、快败 429 带 Retry-After +
X-Gate-Reason: quota|latch|hold，每响应附 X-Gate-* 窗口遥测）——run 默认
直连，调速职能上交网关。serve 代理留作无分级网关的兜底；语义详见
gwpilot.md。

用法：

  # 队列驱动（默认直连网关）
  python3 bench/py/gwpilot.py run bench/queue/night.jsonl [--follow]
      [--max-load 8] [--retry-failed] [--serve]

  # 常驻调速代理（无 fg/bg 分级的网关才需要）
  python3 bench/py/gwpilot.py serve [--port 3398] [--max-cap 40]

  # 观测
  python3 bench/py/gwpilot.py status [--port 3398]     # 单行
  curl -s localhost:3398/__gwpilot/healthz | jq        # 全量
  curl -XPOST localhost:3398/__gwpilot/control -d '{"max_cap":8,"pause":true}'

队列文件（JSONL，# 注释/空行可）：{"id": "x", "sh": "... {GW} ...", "env": {...}}
  {GW} 展开为网关 base-url（直连=上游，--serve=本代理）；{BGKEY} 展开为
  bg 令牌（env GWPILOT_BG_KEY 或 bench/work_gwpilot/bg.token 读入）；env 注入
  TEXLATE_BASE_URL/TEXLATE_API_KEY/TEXLATE_GATEWAY_KEY 默认值。状态落
  <queue>.state.json（done 跳过、failed 重试≤3 次），日志
  bench/work_gwpilot/logs/<queue>/<id>.log。

脱管（>30min 一律 setsid，runbook 纪律）：
  setsid nohup python3 bench/py/gwpilot.py run bench/queue/night.jsonl --follow \
      >> bench/results/gwpilot/run.log 2>&1 </dev/null &

调速信号优先级：pause 哨兵/控制面 > 冷却闩 > 外部占用 > rpm 预算 > max_cap。
纯 stdlib；python3 直跑，不依赖 venv。
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_LOG = logging.getLogger("gwpilot")

PY_DIR = Path(__file__).resolve().parent
ROOT = PY_DIR.parents[1]
WORK_DIR = ROOT / "bench" / "work_gwpilot"  # 命中 bench/work_*/ gitignore
RESULTS_DIR = ROOT / "bench" / "results" / "gwpilot"
TASK_PING = PY_DIR / "task_ping.py"

DEFAULT_UPSTREAM = os.environ.get("TEXLATE_BASE_URL", "http://127.0.0.1:3033")
DEFAULT_PORT = 3398
DEFAULT_KEY = os.environ.get(
    "TEXLATE_API_KEY", ""
)  # 与 qualbench/e2e_real_bench 的默认 --api-key 同源（fg）
BG_TOKEN_FILE = WORK_DIR / "bg.token"  # bg 令牌存放点（bench/work_* gitignored）

_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
#: 只闸 LLM 会话面；GET /v1/models 这类探针直接放行不占闸位。
_GATED_PATHS = ("/v1/chat/completions", "/v1/messages", "/chat/completions")
_UPSTREAM_TIMEOUT = 620
_MAX_ERR_BODY = 4 << 20
_COOLDOWN_MAX = 180.0


# ---------------------------------------------------------------- 配置


def _split_upstream(upstream: str) -> tuple[str, str, int, str]:
    """upstream URL → ``(scheme, host, port, path_prefix)``——配置面单源解析。

    ``urlsplit`` 处理 IPv6 字面量/缺省端口/路径前缀；畸形值在此 SystemExit
    早败（serve/run 同走 ``_cfg_from``→``GovConfig``，建配置即校验，不留到
    首个转发请求才炸）。path_prefix 供 ``_forward`` 拼接在请求路径前——
    带前缀的反代上游（``http://host:port/api``）不再把前缀吞掉。
    """
    try:
        u = urllib.parse.urlsplit(upstream.rstrip("/"))
    except ValueError as e:
        msg = f"upstream 配置不可解析 {upstream!r}: {e}"
        raise SystemExit(msg) from e
    if u.scheme not in ("http", "https") or not u.hostname:
        msg = f"upstream 需形如 http(s)://host[:port][/前缀]: {upstream!r}"
        raise SystemExit(msg)
    if u.query or u.fragment:
        msg = f"upstream 不可带 query/fragment: {upstream!r}"
        raise SystemExit(msg)
    try:
        port = u.port or (443 if u.scheme == "https" else 80)
    except ValueError as e:  # 端口越界/非数字
        msg = f"upstream 端口不可解析 {upstream!r}: {e}"
        raise SystemExit(msg) from e
    return u.scheme, u.hostname, port, u.path.rstrip("/")


@dataclass
class GovConfig:
    """调速旋钮；全有 CLI 对应。"""

    upstream: str = DEFAULT_UPSTREAM
    listen: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    key: str = DEFAULT_KEY  # 仅用于我们自己的 healthz/stats 轮询
    max_cap: int = 40  # 我方 in-flight 绝对上限
    min_cap: int = 2  # 保底细流——任何情况下都保持前进
    rpm_budget: float = 72.0  # 愿占的上游 rpm 预算（80 总量留 8 安全边际）
    yield_per_ext: int = 8  # 每个外部 in-flight 请求压我们多少 cap
    queue_wait: float = 100.0  # 排队上限（客户 180s 超时内）；超出合成 429
    max_queue: int = 128
    healthz_poll: float = 4.0
    accounts_poll: float = 3.0  # /admin/accounts 轮询——lane 闸门精确算术的源
    reserve_margin: int = 4  # 本桶给外部预留的兜底条数（ext_rate 预测之外）
    pause_file: str = ""  # 存在即全员让路（min_cap 细流）
    #: (scheme, host, port, path_prefix)——__post_init__ 一次解析缓存；
    #: 畸形 upstream 在配置构造即 SystemExit（不拖到首个转发请求）。
    up_parts: tuple[str, str, int, str] = field(init=False)

    def __post_init__(self) -> None:
        self.up_parts = _split_upstream(self.upstream)


# ---------------------------------------------------------------- 调速器


class _QueueFull(Exception):
    """排队超时/超深——回客户端合成 429。"""


_Q_DEPTH = "queue depth exceeded"
_Q_WAIT = "queue wait exceeded"


class Governor:
    """自适应并发闸：cap 由外部占用 + rpm 预算联合定天花板，429 砍半+冷却。

    天花板 = min(max_cap, C_rpm, C_burst)：
      C_rpm   = (rpm_budget - ext_rpm) · lat_ewma/60   —— Little 定律换算
      C_burst = 有外部 in-flight 时线性让位（每个让 yield_per_ext）
    cap 在天花板内 AIMD：成功 +0.5；上游 429 半砍并按 Retry-After 上闩；
    5xx/传输错误 ×0.85。
    """

    def __init__(self, cfg: GovConfig) -> None:
        self.cfg = cfg
        self.cond = threading.Condition()
        self.inflight = 0
        self.queued = 0
        self.cap = min(8.0, float(cfg.max_cap))
        self.cooldown_until = 0.0
        self.lat_ewma = 30.0
        self.ext_inflight = 0
        self.ext_rpm = 0.0
        self.up_ok = True
        self._sent: deque[float] = deque()  # 我方发送时刻（60s 滑窗=our_rpm）
        self.paused = False
        # ---- 精确桶算术（/admin/accounts 轮询填充）----
        self.acct_seen = 0.0  # 上次成功抓取的墙钟时刻；>12s 视为过期回退估算
        self.win_remaining = 0.0  # 本桶全体可用 lane 的剩余配额合计
        self.win_reset_ts = 0.0  # 最近可用 lane 的窗口重置 epoch（秒）
        self.quota_total = 0.0  # 可用 lane 的 window_quota 合计（=真实总预算）
        self.ext_waiters = 0  # 网关各 lane 上排队中的外部请求（窗口一开即耗量）
        self.ext_rate = 0.0  # 外部到达率 EMA（条/秒，同桶内 used 增量扣我方）
        self._win_key = ""  # 当前桶标识（win_reset_ts 串），换桶清零 _sent_win
        self._sent_win = 0  # 本桶内我方已发送数
        self._prev_used = 0  # 上轮 total_used 基线（同桶内差分）
        self._prev_our = 0
        self._prev_t = 0.0
        self.stats = {
            "admitted": 0,
            "up2xx": 0,
            "up429": 0,
            "up4xx": 0,
            "up5xx": 0,
            "conn_err": 0,
            "synth429": 0,
            "cooldowns": 0,
        }
        self._stop = threading.Event()

    # ---- 量测 ------------------------------------------------------

    def our_rpm(self) -> float:
        now = time.monotonic()
        while self._sent and now - self._sent[0] > 60:
            self._sent.popleft()
        return float(len(self._sent))

    def ceiling(self) -> float:
        """当前允许的我方 in-flight 天花板（实时算，随外部占用浮动）。

        预算源二选一：accounts 新鲜时用真实总配额（Σ 可用 lane 的
        window_quota，当前 2 lane =160rpm），过期回退配置 rpm_budget。
        """
        lat = max(self.lat_ewma, 5.0)
        fresh = time.time() - self.acct_seen <= 12.0
        budget = (
            self.quota_total
            if (fresh and self.quota_total > 0)
            else self.cfg.rpm_budget
        )
        c_rpm = max(0.0, budget - self.ext_rpm) * lat / 60.0
        if self.ext_inflight <= 0:
            c_burst = float(self.cfg.max_cap)
        else:
            c_burst = float(
                max(
                    self.cfg.min_cap,
                    self.cfg.max_cap - self.cfg.yield_per_ext * self.ext_inflight,
                )
            )
        ceil = min(float(self.cfg.max_cap), c_rpm, c_burst)
        return max(float(self.cfg.min_cap), ceil)

    def eff_cap(self) -> int:
        return max(self.cfg.min_cap, int(min(self.cap, self.ceiling())))

    # ---- 准入 ------------------------------------------------------

    def _paused(self) -> bool:
        return bool(
            self.paused or (self.cfg.pause_file and os.path.exists(self.cfg.pause_file))
        )

    def acquire(self) -> None:
        """拿到闸位才返回；排队超 queue_wait 或超深 → _QueueFull。"""
        deadline = time.monotonic() + self.cfg.queue_wait
        with self.cond:
            if self.queued >= self.cfg.max_queue:
                raise _QueueFull(_Q_DEPTH)
            self.queued += 1
        try:
            while True:
                with self.cond:
                    now = time.monotonic()
                    if now >= deadline:
                        raise _QueueFull(_Q_WAIT)
                    if self._paused():
                        wait = 1.0
                    elif now < self.cooldown_until:
                        wait = min(self.cooldown_until - now, 1.0)
                    elif self._win_blocked(now):
                        # 本桶配额（扣外部预测）已尽——睡到窗口重置再来
                        wait = min(max(self.win_reset_ts - time.time(), 0.3), 1.0)
                    elif self.inflight < self.eff_cap():
                        self.inflight += 1
                        self._sent.append(now)
                        self._sent_win += 1
                        self.stats["admitted"] += 1
                        return
                    else:
                        wait = 0.5
                    self.cond.wait(min(wait, max(0.05, deadline - now)))
        finally:
            with self.cond:
                self.queued -= 1

    def release(self, status: int, elapsed: float, retry_after: float | None) -> None:
        """回执驱动 cap 调整 + 冷却闩。status<0 表示传输层失败。"""
        with self.cond:
            self.inflight = max(0, self.inflight - 1)
            now = time.monotonic()
            if 200 <= status < 300:
                self.lat_ewma = 0.8 * self.lat_ewma + 0.2 * max(elapsed, 0.5)
                self.cap = min(self.cap + 0.5, float(self.cfg.max_cap))
                self.stats["up2xx"] += 1
            elif status == 429:
                hold = min(max(retry_after or 15.0, 1.0), _COOLDOWN_MAX)
                if now + hold > self.cooldown_until:
                    self.cooldown_until = now + hold
                    self.stats["cooldowns"] += 1
                self.cap = max(float(self.cfg.min_cap), self.cap * 0.5)
                self.stats["up429"] += 1
            elif status < 0:
                self.cap = max(float(self.cfg.min_cap), self.cap * 0.85)
                self.stats["conn_err"] += 1
                # 网关不可达时短闩，避免空转锤击
                self.cooldown_until = max(self.cooldown_until, now + 3.0)
            elif status >= 500:
                self.cap = max(float(self.cfg.min_cap), self.cap * 0.85)
                self.stats["up5xx"] += 1
            else:
                self.stats["up4xx"] += 1
            self.cond.notify_all()

    # ---- 窗口算术 ----------------------------------------------------

    def _win_blocked(self, now_mono: float) -> bool:
        """精确桶判定：accounts 数据新鲜且本桶配额（扣外部预测）耗尽。"""
        if time.time() - self.acct_seen > 12.0:
            return False  # 数据过期——回退 C_rpm 估算路径，不瞎拦
        return self._sent_win >= self._allowance()

    def _allowance(self) -> float:
        """本桶我方可用配额 = 剩余总量 − 外部到达预测 − 外部排队 − 兜底。"""
        t_left = max(0.0, self.win_reset_ts - time.time())
        reserve = self.ext_rate * t_left + self.ext_waiters + self.cfg.reserve_margin
        return max(0.0, self.win_remaining - reserve)

    def _poll_accounts(self) -> None:
        """/admin/accounts：每 lane 的 window_used/quota/latched/sendable/inflight。"""
        base = self.cfg.upstream.rstrip("/")
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(  # noqa: S310 — 内网网关
                    f"{base}/admin/accounts",
                    headers={"Authorization": f"Bearer {self.cfg.key}"},
                )
                with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 — 内网网关
                    d = json.loads(r.read())
                self._ingest_accounts(d.get("data", {}).get("accounts") or [])
            except Exception as e:
                _LOG.debug("accounts poll fail: %s", e)
            self._stop.wait(self.cfg.accounts_poll)

    def _ingest_accounts(self, lanes: list[dict]) -> None:
        """聚合 lane 态 → win_remaining/ext_inflight/ext_rate + 换桶检测。"""
        now = time.time()
        remaining = 0.0
        quota_total = 0.0
        used_total = 0
        waiters = 0
        ext_inflight = 0
        reset_ts = float("inf")
        for a in lanes:
            if a.get("disabled"):
                continue
            g = a.get("gate") or {}
            lane = a.get("lane") or {}
            used_total += int(g.get("window_used") or 0)
            waiters += int(g.get("waiters") or 0)
            ext_inflight += int(a.get("inflight") or 0)
            if not (
                g.get("sendable") and not g.get("latched") and lane.get("healthy", True)
            ):
                continue
            remaining += float(g.get("window_quota") or 0) - float(
                g.get("window_used") or 0
            )
            quota_total += float(g.get("window_quota") or 0)
            ts = _parse_ts(g.get("window_next"))
            if ts:
                reset_ts = min(reset_ts, ts)

        with self.cond:
            # reset_ts 有效且前进 = 换桶（无可用 lane 时保持旧桶计数——
            # 全闩态本就被拦，乱清零会低估我方已耗量导致解闩后超发）
            if reset_ts != float("inf") and f"{reset_ts:.0f}" != self._win_key:
                self._win_key = f"{reset_ts:.0f}"
                self._sent_win = 0
                self._prev_used = used_total
                self._prev_our = 0
                self._prev_t = now
            else:
                dt = now - self._prev_t
                if dt >= 1.0:
                    d_used = used_total - self._prev_used
                    d_our = self._sent_win - self._prev_our
                    ext_inst = max(0.0, (d_used - d_our) / dt)
                    self.ext_rate = 0.6 * self.ext_rate + 0.4 * ext_inst
                    self._prev_used = used_total
                    self._prev_our = self._sent_win
                    self._prev_t = now
            self.win_remaining = remaining
            self.quota_total = quota_total
            self.win_reset_ts = reset_ts if reset_ts != float("inf") else now + 60
            self.ext_waiters = waiters
            # accounts 的 inflight 合计即全局在途——比 healthz 更准（同源）
            self.ext_inflight = max(0, ext_inflight - self.inflight)
            self.ext_rpm = self.ext_rate * 60.0
            self.acct_seen = now
            self.cond.notify_all()  # 窗口重置/解闩时唤醒排队者

    # ---- 外部占用轮询 ----------------------------------------------

    def poller_healthz(self) -> None:
        """healthz.active_requests 是全局在途——减去我方 inflight 即外部占用。"""
        base = self.cfg.upstream.rstrip("/")
        fails = 0
        while not self._stop.is_set():
            try:
                with urllib.request.urlopen(f"{base}/healthz", timeout=5) as r:  # noqa: S310 — 内网网关
                    d = json.loads(r.read())
                active = int(d.get("active_requests", 0))
                fails = 0
                with self.cond:
                    # accounts 新鲜时以它的 Σinflight 为准（含 waiters 语义更全）
                    if time.time() - self.acct_seen > 12.0:
                        self.ext_inflight = max(0, active - self.inflight)
                    self.up_ok = True
            except Exception as e:
                fails += 1
                _LOG.debug("healthz poll fail: %s", e)
                if fails >= 3:
                    with self.cond:
                        self.up_ok = False
            self._stop.wait(self.cfg.healthz_poll)

    def start_pollers(self) -> None:
        threading.Thread(target=self.poller_healthz, daemon=True, name="gov-hz").start()
        threading.Thread(
            target=self._poll_accounts, daemon=True, name="gov-acct"
        ).start()

    def shutdown(self) -> None:
        self._stop.set()
        with self.cond:
            self.cond.notify_all()

    # ---- 观测 ------------------------------------------------------

    def snapshot(self) -> dict:
        with self.cond:
            cd = max(0.0, self.cooldown_until - time.monotonic())
            return {
                "ok": True,
                "up_ok": self.up_ok,
                "inflight": self.inflight,
                "queued": self.queued,
                "cap": round(self.cap, 1),
                "eff_cap": self.eff_cap(),
                "ceiling": round(self.ceiling(), 1),
                "max_cap": self.cfg.max_cap,
                "min_cap": self.cfg.min_cap,
                "cooldown_s": round(cd, 1),
                "paused": self._paused(),
                "ext_inflight": self.ext_inflight,
                "ext_rpm": round(self.ext_rpm, 1),
                "win_remaining": round(self.win_remaining, 1),
                "win_allowance": round(self._allowance(), 1),
                "win_reset_in_s": round(max(0.0, self.win_reset_ts - time.time()), 1),
                "quota_total": self.quota_total,
                "sent_win": self._sent_win,
                "acct_fresh": time.time() - self.acct_seen <= 12.0,
                "our_rpm": self.our_rpm(),
                "rpm_budget": self.cfg.rpm_budget,
                "lat_ewma_s": round(self.lat_ewma, 1),
                "stats": dict(self.stats),
            }


# ---------------------------------------------------------------- 代理转发


def _parse_ts(s: object) -> float | None:
    """RFC3339 → epoch 秒（accounts 的 window_next 是带时区串）。"""
    if not isinstance(s, str):
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _read_chunked(rfile) -> bytes:
    """读 Transfer-Encoding: chunked 请求体（httpx 走 length，这里兜底）。"""
    buf = bytearray()
    while True:
        line = rfile.readline(65536).strip()
        try:
            n = int(line.split(b";", 1)[0], 16)
        except ValueError:
            break
        if n == 0:
            while rfile.readline(65536) not in (b"\r\n", b"\n", b""):
                pass
            break
        buf.extend(rfile.read(n))
        rfile.read(2)
    return bytes(buf)


def _body_retry_after(body: bytes) -> float | None:
    """与 xlat/client.py 同口径：error.retry_after 在 body。"""
    try:
        err = json.loads(body).get("error")
        raw = err.get("retry_after") if isinstance(err, dict) else None
        return float(raw) if raw is not None else None
    except Exception:
        return None


def _header_retry_after(headers: http.client.HTTPMessage) -> float | None:
    raw = headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class GovHandler(BaseHTTPRequestHandler):
    """全透传反代；LLM 会话面经 Governor 准入，其余路径直通。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        _LOG.debug("%s %s", self.address_string(), fmt % args)

    @property
    def gov(self) -> Governor:
        return self.server.gov  # type: ignore[attr-defined]

    # -- 本地控制面 ---------------------------------------------------

    def _local(self) -> bool:
        if self.path in ("/__gwpilot/healthz", "/__gwpilot/stats"):
            self._send_json(200, self.gov.snapshot())
            return True
        if self.path == "/__gwpilot/control" and self.command == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                d = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                d = {}
            cfg = self.gov.cfg
            if "max_cap" in d:
                cfg.max_cap = max(1, int(d["max_cap"]))
            if "rpm_budget" in d:
                cfg.rpm_budget = max(0.0, float(d["rpm_budget"]))
            if "min_cap" in d:
                cfg.min_cap = max(1, int(d["min_cap"]))
            if "pause" in d:
                self.gov.paused = bool(d["pause"])
            self._send_json(200, self.gov.snapshot())
            return True
        return False

    def _send_json(
        self, code: int, obj: dict, extra: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _synth_429(self, why: str) -> None:
        ra = max(5.0, min(30.0, self.gov.cooldown_until - time.monotonic() or 10.0))
        self.gov.stats["synth429"] += 1
        self._send_json(
            429,
            {
                "error": {
                    "message": f"gwpilot: {why}",
                    "type": "rate_limit_error",
                    "retry_after": round(ra, 1),
                }
            },
            {"Retry-After": str(int(ra) + 1)},
        )

    # -- 转发 ---------------------------------------------------------

    def _read_body(self) -> bytes:
        n = self.headers.get("Content-Length")
        if n is not None:
            return self.rfile.read(int(n))
        if "chunked" in (self.headers.get("Transfer-Encoding") or ""):
            return _read_chunked(self.rfile)
        return b""

    def _gated(self) -> bool:
        return self.command == "POST" and any(
            self.path.startswith(p) for p in _GATED_PATHS
        )

    def _forward(self) -> None:
        body = self._read_body()
        gov = self.gov
        admitted = False
        if self._gated():
            try:
                gov.acquire()
                admitted = True
            except _QueueFull as e:
                self._synth_429(str(e))
                return

        # upstream 已在 GovConfig.__post_init__ 一次解析（含 IPv6/路径前缀）。
        scheme, uhost, uport, uprefix = gov.cfg.up_parts
        conn_cls = (
            http.client.HTTPSConnection
            if scheme == "https"
            else http.client.HTTPConnection
        )

        headers = {
            k: v for k, v in self.headers.items() if k.lower() not in _HOP_BY_HOP
        }
        # IPv6 字面量 Host 头须带方括号（urlsplit.hostname 已剥壳）。
        headers["Host"] = f"[{uhost}]:{uport}" if ":" in uhost else f"{uhost}:{uport}"

        t0 = time.monotonic()
        status = -1
        ra: float | None = None
        try:
            conn = conn_cls(uhost, uport, timeout=_UPSTREAM_TIMEOUT)
            conn.request(
                self.command, f"{uprefix}{self.path}", body=body, headers=headers
            )
            resp = conn.getresponse()
            status = resp.status
            if 200 <= status < 300:
                # 成功面流式回传（SSE 逐 chunk 透传，in-flight 持到流尾）
                self.send_response(status)
                chunked_out = "Content-Length" not in resp.headers
                for k, v in resp.headers.items():
                    lk = k.lower()
                    if lk in _HOP_BY_HOP or lk == "transfer-encoding":
                        continue
                    self.send_header(k, v)
                if chunked_out:
                    self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while True:
                    chunk = resp.read1(65536)
                    if not chunk:
                        break
                    if chunked_out:
                        self.wfile.write(b"%X\r\n" % len(chunk) + chunk + b"\r\n")
                    else:
                        self.wfile.write(chunk)
                    self.wfile.flush()
                if chunked_out:
                    self.wfile.write(b"0\r\n\r\n")
            else:
                # 错误面缓冲（小）——抽 retry_after 喂调速器
                ebody = resp.read(_MAX_ERR_BODY)
                ra = _header_retry_after(resp.headers) or _body_retry_after(ebody)
                self.send_response(status)
                for k, v in resp.headers.items():
                    lk = k.lower()
                    if lk in _HOP_BY_HOP or lk in (
                        "transfer-encoding",
                        "content-length",
                    ):
                        continue
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(ebody)))
                self.end_headers()
                self.wfile.write(ebody)
            conn.close()
        except (OSError, http.client.HTTPException, TimeoutError) as e:
            _LOG.warning("upstream error: %s", e)
            with contextlib.suppress(OSError):
                self._send_json(
                    502,
                    {
                        "error": {
                            "message": f"gwpilot upstream: {e}",
                            "type": "upstream_error",
                        }
                    },
                )
        finally:
            if admitted:
                gov.release(status, time.monotonic() - t0, ra)

    # -- HTTP 方法分发 -------------------------------------------------

    def _dispatch(self) -> None:
        try:
            if self._local():
                return
            self._forward()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            _LOG.exception("handler error")
            with contextlib.suppress(OSError):
                self._send_json(500, {"error": {"message": "gwpilot internal"}})

    do_GET = _dispatch  # noqa: N815
    do_POST = _dispatch  # noqa: N815
    do_PUT = _dispatch  # noqa: N815
    do_DELETE = _dispatch  # noqa: N815
    do_PATCH = _dispatch  # noqa: N815
    do_HEAD = _dispatch  # noqa: N815


class GovServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cfg: GovConfig) -> None:
        self.gov = Governor(cfg)
        super().__init__((cfg.listen, cfg.port), GovHandler)


# ---------------------------------------------------------------- 共用


def _cfg_from(args: argparse.Namespace) -> GovConfig:
    return GovConfig(
        upstream=args.upstream,
        listen=args.listen,
        port=args.port,
        key=(
            os.environ.get("TEXLATE_GATEWAY_KEY")
            or os.environ.get("TEXLATE_API_KEY")
            or args.key
        ),
        max_cap=args.max_cap,
        min_cap=args.min_cap,
        rpm_budget=args.rpm_budget,
        yield_per_ext=args.yield_per_ext,
        queue_wait=args.queue_wait,
        max_queue=args.max_queue,
        accounts_poll=args.accounts_poll,
        reserve_margin=args.reserve_margin,
        pause_file=args.pause_file,
    )


def _add_gov_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    p.add_argument("--listen", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--key", default=DEFAULT_KEY, help="healthz/stats 轮询用 key")
    p.add_argument("--max-cap", type=int, default=40)
    p.add_argument("--min-cap", type=int, default=2)
    p.add_argument("--rpm-budget", type=float, default=72.0)
    p.add_argument("--yield-per-ext", type=int, default=8)
    p.add_argument("--queue-wait", type=float, default=100.0)
    p.add_argument("--max-queue", type=int, default=128)
    p.add_argument("--accounts-poll", type=float, default=3.0)
    p.add_argument("--reserve-margin", type=int, default=4)
    p.add_argument("--pause-file", default="", help="存在即让路的哨兵文件")


# ---------------------------------------------------------------- serve


def cmd_serve(args: argparse.Namespace) -> int:
    cfg = _cfg_from(args)
    srv = GovServer(cfg)
    srv.gov.start_pollers()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    (WORK_DIR / "gwpilot.pid").write_text(str(os.getpid()))
    _LOG.info(
        "gwpilot serve :%d -> %s max_cap=%d budget=%.0f rpm",
        cfg.port,
        cfg.upstream,
        cfg.max_cap,
        cfg.rpm_budget,
    )
    print(
        f"gwpilot serving http://{cfg.listen}:{cfg.port} -> {cfg.upstream} "
        f"(healthz /__gwpilot/healthz)",
        flush=True,
    )

    # shutdown() 必须跨线程调——信号 handler 跑在主线程会跟 serve_forever 死锁
    def _sig(*_a: object) -> None:
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    try:
        srv.serve_forever()
    finally:
        srv.gov.shutdown()
        srv.server_close()
    return 0


# ---------------------------------------------------------------- run


def _load_queue(path: Path) -> list[dict]:
    """JSONL 队列 → 任务行；# 注释/空行跳过，坏行报错不静默。"""
    try:
        text = path.read_text()
    except OSError as e:
        msg = f"队列文件不可读: {path}: {e}"
        raise SystemExit(msg) from e
    tasks: list[dict] = []
    seen: set[str] = set()
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            t = json.loads(line)
        except json.JSONDecodeError as e:
            msg = f"{path}:{ln} 坏行: {e}"
            raise SystemExit(msg) from e
        tid = t.get("id")
        if not tid or ("sh" not in t and "argv" not in t):
            msg = f"{path}:{ln} 需要 id + sh|argv"
            raise SystemExit(msg)
        if tid in seen:
            msg = f"{path}:{ln} id 重复: {tid}"
            raise SystemExit(msg)
        seen.add(tid)
        tasks.append(t)
    return tasks


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(path)


def _ping(done: int, total: int, status: str) -> None:
    """status_panel task_ping 约定——best-effort，面板不在就静默。"""
    if not TASK_PING.exists():
        return
    try:
        subprocess.run(
            [
                sys.executable,
                str(TASK_PING),
                "gwpilot",
                "--status",
                status,
                "--done",
                str(done),
                "--total",
                str(total),
            ],
            timeout=10,
            capture_output=True,
        )
    except Exception as e:
        _LOG.debug("task_ping fail: %s", e)


def _gov_healthz(cfg: GovConfig) -> dict | None:
    try:
        with urllib.request.urlopen(
            f"http://{cfg.listen}:{cfg.port}/__gwpilot/healthz", timeout=3
        ) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _bg_key() -> str:
    """bg 令牌：env GWPILOT_BG_KEY > bg.token 文件。缺省 ""（调用方提示按 fg 计费）。"""
    env = os.environ.get("GWPILOT_BG_KEY", "").strip()
    if env:
        return env
    if BG_TOKEN_FILE.exists():
        return BG_TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


def _upstream_ok(cfg: GovConfig) -> bool:
    """直连模式的发射前活性检查：上游 /healthz 报 ok 且不在 draining。"""
    try:
        with urllib.request.urlopen(f"{cfg.upstream}/healthz", timeout=5) as r:  # noqa: S310 — 内网网关
            d = json.loads(r.read())
    except Exception:
        return False
    return d.get("status") == "ok" and not d.get("draining")


def cmd_run(args: argparse.Namespace) -> int:
    queue = Path(args.queue).resolve()
    state_dir = WORK_DIR / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{queue.stem}.state.json"
    log_dir = WORK_DIR / "logs" / queue.stem
    log_dir.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 默认直连网关（fg/bg 分级准入在网关侧）；--serve 才内嵌/attach 调速代理
    cfg = _cfg_from(args)
    srv: GovServer | None = None
    if args.serve:
        if _gov_healthz(cfg) is not None:
            _LOG.info("attach existing gwpilot :%d", cfg.port)
        else:
            srv = GovServer(cfg)
            srv.gov.start_pollers()
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _LOG.info("embedded gwpilot :%d -> %s", cfg.port, cfg.upstream)
        gw = f"http://{cfg.listen}:{cfg.port}"
    else:
        gw = cfg.upstream
    bgkey = _bg_key()
    if not bgkey:
        _LOG.warning(
            "bg 令牌缺失（GWPILOT_BG_KEY / %s）——批跑将按 fg 计费", BG_TOKEN_FILE
        )

    stop = threading.Event()

    def _sig(*_a: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    attempts: dict[str, int] = {}
    if args.retry_failed:
        # --retry-failed = 给 failed 格一轮新的 ≤3 次预算：把持久化的
        # attempts 清零（内存账与落盘 state 两侧同口径）。旧实现只是把
        # ≥3 门控整段跳过 = 无限重试，与 help 文案「重置重试计数」不符。
        state0 = _load_state(state_path)
        reset = False
        for tid0, st0 in state0.items():
            if st0.get("status") == "failed":
                st0["attempts"] = 0
                attempts[tid0] = 0
                reset = True
        if reset:
            _save_state(state_path, state0)
    while not stop.is_set():
        tasks = _load_queue(queue)
        state = _load_state(state_path)
        done_ct = sum(1 for v in state.values() if v.get("status") == "done")
        pending = []
        for t in tasks:
            tid = t["id"]
            st = state.get(tid, {})
            if st.get("status") == "done":
                continue
            if (
                st.get("status") == "failed"
                and max(attempts.get(tid, 0), st.get("attempts", 0)) >= 3
            ):
                continue
            pending.append(t)
        _ping(done_ct, len(tasks), "running" if pending else "done")
        if not pending:
            if not args.follow:
                break
            stop.wait(60)
            continue
        t = pending[0]
        tid = t["id"]
        attempts[tid] = (
            max(attempts.get(tid, 0), state.get(tid, {}).get("attempts", 0)) + 1
        )
        state[tid] = {
            "status": "running",
            "started": time.time(),
            "attempts": attempts[tid],
        }
        _save_state(state_path, state)

        # 上游不可达/本地高载时不发新任务（在跑的不杀）
        while not stop.is_set():
            if args.serve:
                snap = _gov_healthz(cfg)
                up_ok = snap.get("up_ok", False) if snap is not None else False
            else:
                up_ok = _upstream_ok(cfg)
            if not up_ok:
                _LOG.info("上游不可达——等 30s")
                stop.wait(30)
                continue
            if args.max_load > 0:
                try:
                    if os.getloadavg()[0] > args.max_load:
                        _LOG.info(
                            "load %.1f > %s——等 60s", os.getloadavg()[0], args.max_load
                        )
                        stop.wait(60)
                        continue
                except OSError:
                    pass
            break
        if stop.is_set():
            break

        def _xp(s: str) -> str:
            return s.replace("{GW}", gw).replace("{BGKEY}", bgkey)

        sh = t.get("sh")
        argv = t.get("argv")
        if sh:
            run_argv: list[str] | str = _xp(sh)
            shell = True
        else:
            run_argv = [_xp(a) for a in argv]
            shell = False
        env = dict(os.environ)
        env.setdefault("TEXLATE_BASE_URL", gw)
        env.setdefault("TEXLATE_API_KEY", bgkey or cfg.key)
        env.setdefault("TEXLATE_GATEWAY_KEY", bgkey or cfg.key)
        for k, v in (t.get("env") or {}).items():
            env[k] = _xp(str(v))

        logf = log_dir / f"{tid}.log"
        _LOG.info("task %s start -> %s", tid, logf)
        with logf.open("ab") as lf:
            lf.write(
                f"\n===== {time.strftime('%F %T')} attempt {attempts[tid]} =====\n".encode()
            )
            lf.flush()
            proc = subprocess.Popen(
                run_argv,
                shell=shell,
                cwd=t.get("cwd") or str(ROOT),
                env=env,
                stdout=lf,
                stderr=subprocess.STDOUT,
            )
            while proc.poll() is None and not stop.is_set():
                stop.wait(2)
            if stop.is_set() and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            rc = proc.poll()

        state = _load_state(state_path)
        if rc == 0:
            state[tid] = {
                "status": "done",
                "rc": 0,
                "ended": time.time(),
                "attempts": attempts[tid],
            }
            _LOG.info("task %s done", tid)
        elif stop.is_set():
            state[tid] = {"status": "pending", "rc": rc, "ended": time.time()}
            _LOG.info("task %s interrupted", tid)
        else:
            state[tid] = {
                "status": "failed",
                "rc": rc,
                "ended": time.time(),
                "attempts": attempts[tid],
            }
            _LOG.warning("task %s failed rc=%s (%s)", tid, rc, logf)
        _save_state(state_path, state)

    final = _load_state(state_path)
    _ping(
        sum(1 for v in final.values() if v.get("status") == "done"),
        len(_load_queue(queue)),
        "done",
    )
    if srv is not None:
        srv.gov.shutdown()
        srv.shutdown()
    return 0


# ---------------------------------------------------------------- status


def cmd_status(args: argparse.Namespace) -> int:
    url = f"http://{args.listen}:{args.port}/__gwpilot/healthz"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            d = json.loads(r.read())
    except Exception as e:
        print(f"gwpilot DOWN ({e})")
        return 1
    s = d["stats"]
    print(
        f"gwpilot cap={d['cap']}/{d['max_cap']} eff={d['eff_cap']} "
        f"inflight={d['inflight']} queued={d['queued']} cd={d['cooldown_s']}s "
        f"ext[inflight={d['ext_inflight']} rpm={d['ext_rpm']}] "
        f"our_rpm={d['our_rpm']} lat={d['lat_ewma_s']}s up_ok={d['up_ok']} "
        f"up[2xx={s['up2xx']} 429={s['up429']} 5xx={s['up5xx']} err={s['conn_err']}] "
        f"synth429={s['synth429']}"
    )
    return 0


# ---------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="常驻自适应并发闸代理")
    _add_gov_flags(p_serve)

    p_run = sub.add_parser("run", help="断点续跑队列驱动（默认直连网关）")
    p_run.add_argument("queue", help="JSONL 队列文件")
    p_run.add_argument("--follow", action="store_true", help="排空后驻留等新任务")
    p_run.add_argument(
        "--max-load", type=float, default=0.0, help="load1 阈值，超则不发新任务"
    )
    p_run.add_argument(
        "--retry-failed", action="store_true", help="重置 failed 任务的重试计数"
    )
    p_run.add_argument(
        "--serve",
        action="store_true",
        help="内嵌/attach 调速代理（无 fg/bg 分级的网关才需要）",
    )
    _add_gov_flags(p_run)

    p_st = sub.add_parser("status", help="单行状态")
    p_st.add_argument("--listen", default="127.0.0.1")
    p_st.add_argument("--port", type=int, default=DEFAULT_PORT)

    args = ap.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    if args.cmd == "serve":
        sys.exit(cmd_serve(args))
    if args.cmd == "run":
        sys.exit(cmd_run(args))
    if args.cmd == "status":
        sys.exit(cmd_status(args))


if __name__ == "__main__":
    main()
