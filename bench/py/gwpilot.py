#!/usr/bin/env python3
r"""gwpilot — 见缝插针网关调度器：自适应并发闸代理 + 断点续跑队列驱动。

为什么需要它（devin-2api rategate 实测语义，archbox internal/adapter/devin）：

  * 上游按**自然分钟桶**计 ~80rpm（config max_rpm:80，被拒尝试也计数），
    网关侧对齐窗口发送，排队预估超 gate_max_hold(15s) 即本地快败
    429+Retry-After；上游 resource_exhausted 则上冷却闩（声明 reset 或兜底
    60s），闩内仅 8s 滴灌探针、其余全部立即 429+Retry-After=闩剩余。
  * 本机 Claude 会话（claude-opus-4-6→swe-2-max 别名）与 texlate 产品链
    共用同一 lane——白天互动流量要优先，夜里空档要能吃满。
  * 退役 gwcap 是固定 sem=4 硬闸；本工具换成**自适应闸**：用网关自己暴露
    的 /healthz(active_requests) + /admin/stats(recent_rpm) 量出「别人占了
    多少」，剩下全是我们的；429 时按 Retry-After 全局冷却再半开爬坡。

用法：

  # 常驻代理（给手工 bench / texlate server 指 --base-url 用）
  python3 bench/py/gwpilot.py serve [--port 3398] [--max-cap 40]

  # 队列驱动（内嵌代理；端口已活则自动 attach 复用）
  python3 bench/py/gwpilot.py run bench/queue/night.jsonl [--follow]
      [--max-load 8] [--retry-failed]

  # 观测
  python3 bench/py/gwpilot.py status [--port 3398]     # 单行
  curl -s localhost:3398/__gwpilot/healthz | jq        # 全量
  curl -XPOST localhost:3398/__gwpilot/control -d '{"max_cap":8,"pause":true}'

队列文件（JSONL，# 注释/空行可）：{"id": "x", "sh": "... {GW} ...", "env": {...}}
  {GW} 展开为代理 base-url；env 注入 TEXLATE_BASE_URL/TEXLATE_API_KEY/
  TEXLATE_GATEWAY_KEY 默认值。状态落 <queue>.state.json（done 跳过、
  failed 重试≤3 次），日志 bench/work_gwpilot/logs/<queue>/<id>.log。

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
import urllib.request
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_LOG = logging.getLogger("gwpilot")

PY_DIR = Path(__file__).resolve().parent
ROOT = PY_DIR.parents[1]
WORK_DIR = ROOT / "bench" / "work_gwpilot"  # 命中 bench/work_*/ gitignore
RESULTS_DIR = ROOT / "bench" / "results" / "gwpilot"
TASK_PING = PY_DIR / "task_ping.py"

DEFAULT_UPSTREAM = "http://100.105.212.52:3003"
DEFAULT_PORT = 3398
DEFAULT_KEY = "240127"  # 与 qualbench/e2e_real_bench 的默认 --api-key 同源

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
    stats_poll: float = 30.0
    pause_file: str = ""  # 存在即全员让路（min_cap 细流）


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
        self._sent: deque[float] = deque()
        self.paused = False
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
        """当前允许的我方 in-flight 天花板（实时算，随外部占用浮动）。"""
        lat = max(self.lat_ewma, 5.0)
        c_rpm = max(0.0, self.cfg.rpm_budget - self.ext_rpm) * lat / 60.0
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
                    elif self.inflight < self.eff_cap():
                        self.inflight += 1
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
                self._sent.append(now)
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
                    self.ext_inflight = max(0, active - self.inflight)
                    self.up_ok = True
            except Exception as e:
                fails += 1
                _LOG.debug("healthz poll fail: %s", e)
                if fails >= 3:
                    with self.cond:
                        self.up_ok = False
            self._stop.wait(self.cfg.healthz_poll)

    def poller_stats(self) -> None:
        """admin/stats.recent_rpm 是全局 rpm——减去我方实测发送速率即外部 rpm。"""
        base = self.cfg.upstream.rstrip("/")
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(  # noqa: S310 — 内网网关
                    f"{base}/admin/stats",
                    headers={"Authorization": f"Bearer {self.cfg.key}"},
                )
                with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 — 内网网关
                    d = json.loads(r.read())
                data = d.get("data", {})
                total = float(data.get("rpm_stats", {}).get("recent_rpm") or 0.0)
                if total <= 0:
                    total = float(
                        data.get("recent", {}).get("s60", {}).get("rpm") or 0.0
                    )
                with self.cond:
                    self.ext_rpm = max(0.0, total - self.our_rpm())
            except Exception as e:
                _LOG.debug("stats poll fail: %s", e)
            self._stop.wait(self.cfg.stats_poll)

    def start_pollers(self) -> None:
        threading.Thread(target=self.poller_healthz, daemon=True, name="gov-hz").start()
        threading.Thread(
            target=self.poller_stats, daemon=True, name="gov-stats"
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
                "our_rpm": self.our_rpm(),
                "rpm_budget": self.cfg.rpm_budget,
                "lat_ewma_s": round(self.lat_ewma, 1),
                "stats": dict(self.stats),
            }


# ---------------------------------------------------------------- 代理转发


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

        up = gov.cfg.upstream.rstrip("/")
        scheme, _, rest = up.partition("://")
        hpart, _, port_s = rest.partition(":")
        uhost = hpart
        uport = int(port_s) if port_s else (443 if scheme == "https" else 80)
        conn_cls = (
            http.client.HTTPSConnection
            if scheme == "https"
            else http.client.HTTPConnection
        )

        headers = {
            k: v for k, v in self.headers.items() if k.lower() not in _HOP_BY_HOP
        }
        headers["Host"] = f"{uhost}:{uport}"

        t0 = time.monotonic()
        status = -1
        ra: float | None = None
        try:
            conn = conn_cls(uhost, uport, timeout=_UPSTREAM_TIMEOUT)
            conn.request(self.command, self.path, body=body, headers=headers)
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
    signal.signal(signal.SIGTERM, lambda *_: srv.shutdown())
    signal.signal(signal.SIGINT, lambda *_: srv.shutdown())
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


def cmd_run(args: argparse.Namespace) -> int:
    queue = Path(args.queue).resolve()
    state_dir = WORK_DIR / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{queue.stem}.state.json"
    log_dir = WORK_DIR / "logs" / queue.stem
    log_dir.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 代理：端口已活则 attach，否则内嵌一个
    cfg = _cfg_from(args)
    srv: GovServer | None = None
    if not args.no_serve:
        if _gov_healthz(cfg) is not None:
            _LOG.info("attach existing gwpilot :%d", cfg.port)
        else:
            srv = GovServer(cfg)
            srv.gov.start_pollers()
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _LOG.info("embedded gwpilot :%d -> %s", cfg.port, cfg.upstream)
    gw = f"http://{cfg.listen}:{cfg.port}"

    stop = threading.Event()

    def _sig(*_a: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    attempts: dict[str, int] = {}
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
                and not args.retry_failed
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
            snap = _gov_healthz(cfg) if not args.no_serve else None
            if snap is not None and not snap.get("up_ok", True):
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

        sh = t.get("sh")
        argv = t.get("argv")
        if sh:
            run_argv: list[str] | str = sh.replace("{GW}", gw)
            shell = True
        else:
            run_argv = [a.replace("{GW}", gw) for a in argv]
            shell = False
        env = dict(os.environ)
        env.setdefault("TEXLATE_BASE_URL", gw)
        env.setdefault("TEXLATE_API_KEY", cfg.key)
        env.setdefault("TEXLATE_GATEWAY_KEY", cfg.key)
        for k, v in (t.get("env") or {}).items():
            env[k] = str(v).replace("{GW}", gw)

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

    p_run = sub.add_parser("run", help="断点续跑队列驱动（内嵌/attach 代理）")
    p_run.add_argument("queue", help="JSONL 队列文件")
    p_run.add_argument("--follow", action="store_true", help="排空后驻留等新任务")
    p_run.add_argument(
        "--max-load", type=float, default=0.0, help="load1 阈值，超则不发新任务"
    )
    p_run.add_argument(
        "--retry-failed", action="store_true", help="重置 failed 任务的重试计数"
    )
    p_run.add_argument(
        "--no-serve", action="store_true", help="不内嵌代理（直连或已另有代理）"
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
