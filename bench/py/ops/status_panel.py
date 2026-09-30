#!/usr/bin/env python3
"""Read-only local status panel for texlate bench/fleet monitoring.

stdlib-only. Serves a single self-refreshing HTML page on 127.0.0.1.
All data sources are files or read-only commands; collectors are
independently fault-isolated and cached.

Run detached:
    setsid nohup python3 bench/py/ops/status_panel.py \
        >> "$TEXLATE_BENCH_ROOT/state/status-panel/run.log" 2>&1 </dev/null &
Stop:
    kill "$(cat "$TEXLATE_BENCH_ROOT/state/status-panel/panel.pid")"

Task board convention: agents report progress via
    python3 bench/py/ops/task_ping.py <name> --status running --done N --total M
(board lives at $TEXLATE_BENCH_ROOT/state/status-panel/tasks.d)
"""

from __future__ import annotations

import collections
import contextlib
import datetime as dt
import glob
import html
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 包内脚本直跑时 bench/py 不在 sys.path——先立起再引 kernel
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO = Path(__file__).resolve().parents[3]
try:
    from kernel import events as _kevents
    from kernel import paths as _kpaths

    BENCH_ROOT = _kpaths.root()
    RUNS_DIR = _kpaths.runs_dir()
except Exception:  # kernel is stdlib-only; fallback mirrors it
    _kevents = None
    BENCH_ROOT = Path(
        os.environ.get(
            "TEXLATE_BENCH_ROOT", Path.home() / ".local" / "share" / "texlate-bench"
        )
    ).expanduser()
    RUNS_DIR = BENCH_ROOT / "runs"
PANEL_DIR = BENCH_ROOT / "state" / "status-panel"
PIDFILE = PANEL_DIR / "panel.pid"
TASKS_DIR = PANEL_DIR / "tasks.d"
#: run 目录由 _n200_dir() 自动发现（realn200-*/e2e-* 最新含账者）——
#: 原硬钉目录名已在归档后失效，常亮空账不如无候选时的显式空态。
N200_PID = 439968
SESSIONS_GLOB = os.path.expanduser("~/.claude/sessions/*.json")
VENV_PY = REPO / ".venv" / "bin" / "python"
REFRESH_SECONDS = 45
STALE_TASK_SECONDS = 900
HOST = "127.0.0.1"
PORT = int(os.environ.get("PANEL_PORT", "8766"))

C_CLEAN = "#2da44e"
C_FAIL = "#cf222e"
C_PART = "#d4a72c"
C_SKIP = "#8b949e"
C_INFO = "#0969da"
C_PURPLE = "#8250df"

STATUS_COLOR = {
    "clean": C_CLEAN,
    "fail": C_FAIL,
    "partial": C_PART,
    "skipped": C_SKIP,
    "reject": C_FAIL,
}
STATUS_ZH = {
    "clean": "干净",
    "fail": "失败",
    "partial": "部分",
    "skipped": "跳过",
    "reject": "拒收",
}
TASK_STATUS_COLOR = {
    "starting": C_SKIP,
    "running": C_INFO,
    "blocked": C_PART,
    "done": C_CLEAN,
    "failed": C_FAIL,
}
TASK_STATUS_ZH = {
    "starting": "启动",
    "running": "运行",
    "blocked": "阻塞",
    "done": "完成",
    "failed": "失败",
}

_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def run_cmd(argv: list[str], timeout: float) -> str:
    proc = subprocess.run(
        argv,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    out = (proc.stdout + proc.stderr).strip()
    return out or f"(exit {proc.returncode}, no output)"


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def fmt_age(ts: float) -> str:
    delta = max(0, time.time() - ts)
    if delta < 60:
        return f"{delta:.0f} 秒前"
    if delta < 3600:
        return f"{delta / 60:.0f} 分钟前"
    if delta < 86400:
        return f"{delta / 3600:.1f} 小时前"
    return f"{delta / 86400:.1f} 天前"


def fmt_dur(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"{h} 小时 {m:02d} 分" if h else f"{m} 分钟"


def esc(s: object) -> str:
    return html.escape(str(s))


# ---------- html fragments


def chip(label: str, value: str, sub: str = "", cls: str = "") -> str:
    return (
        f"<div class='chip {cls}'><div class='k'>{esc(label)}</div>"
        f"<div class='v'>{esc(value)}</div>"
        f"<div class='s'>{esc(sub)}</div></div>"
    )


def hbar(label: str, n: float, maxn: float, color: str, extra: str = "") -> str:
    pct = n / maxn * 100 if maxn else 0
    return (
        f"<div class='hrow'><div class='hl'>{esc(label)}</div>"
        f"<div class='hb'><div class='hf' style='width:{pct:.1f}%;"
        f"background:{color}'></div></div>"
        f"<div class='hn'>{n:g}{esc(extra)}</div></div>"
    )


def stacked(parts: list[tuple[str, int, str]], total: int) -> str:
    segs, legend = [], []
    for label, n, color in parts:
        if not n or not total:
            continue
        w = n / total * 100
        segs.append(
            f"<div class='seg' style='width:{w:.2f}%;background:{color}' "
            f"title='{esc(label)} {n}'></div>"
        )
        legend.append(
            f"<span class='lg'><i style='background:{color}'></i>"
            f"{esc(label)} {n}</span>"
        )
    return (
        "<div class='stack'>" + "".join(segs) + "</div>"
        "<div class='legend'>" + "".join(legend) + "</div>"
    )


def badge(text: str, color: str) -> str:
    return (
        f"<span class='bdg' style='background:{color}1a;color:{color};"
        f"border-color:{color}55'>{esc(text)}</span>"
    )


def table(headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def minibar(done: float, total: float) -> str:
    pct = min(done / total * 100, 100) if total else 0
    return (
        f"<div class='mb'><div class='mf' style='width:{pct:.0f}%'></div></div>"
        f"<span class='mbn'>{done:g}/{total:g}</span>"
    )


# ---------- data collectors


def scorecard_raw() -> str:
    def collect() -> str:
        if not VENV_PY.exists():
            return f".venv python missing: {VENV_PY}"
        # gate 动词（bench/py/kernel/cli.py REGISTRY）= gate_scorecard.py
        # 新世界等价物；未落地时 stderr 进面板、scorecard_data {} 兜底。
        return run_cmd(
            [str(VENV_PY), str(REPO / "bench" / "py" / "bench"), "gate", "--json"], 180
        )

    return cached("scorecard", 60, collect)


def scorecard_data() -> dict:
    """gate_scorecard --json → 面板消费形。

    主口径 = union（best-of——chip/门线标签即「联合 PDF」）；end-state
    （末段胜）作副口径随带。scorecard 崩/输出非 json → 全零兜底不炸面板。
    """
    try:
        rep, _ = json.JSONDecoder().raw_decode(scorecard_raw().strip())
    except json.JSONDecodeError:
        rep = {}
    if not isinstance(rep, dict):
        rep = {}
    uni = rep.get("union") or {}
    end = rep.get("end_state") or {}

    def _gate_txt(g) -> str:
        if not isinstance(g, dict) or not g:
            return "?"
        return "PASS" if g.get("pass") else f"need +{g.get('need', '?')}"

    def _excl(blk: dict) -> dict | None:
        e = blk.get("excl_reject")
        if not isinstance(e, dict):
            return None
        return {
            "n": e.get("n") or 0,
            "pdf": f"{e.get('pdf_pct') or 0:.2f}",
            "clean": f"{e.get('clean_pct') or 0:.2f}",
        }

    dist = end.get("dist")
    return {
        "cells": rep.get("cells") or 0,
        "pdf_n": uni.get("pdf") or 0,
        "pdf_pct": uni.get("pdf_pct") or 0.0,
        "clean_n": uni.get("clean") or 0,
        "clean_pct": uni.get("clean_pct") or 0.0,
        "gate": _gate_txt(uni.get("gate")),
        "excl": _excl(uni),
        "end_pdf_n": end.get("pdf") or 0,
        "end_pdf_pct": end.get("pdf_pct") or 0.0,
        "end_gate": _gate_txt(end.get("gate")),
        "end_state": list(dist.items()) if isinstance(dist, dict) else [],
        "top_sigs": rep.get("top_sigs") or [],
    }


RATE_STATE = PANEL_DIR / "rate-state.json"
RATE_WINDOW_S = 30 * 60
RATE_KEEP_S = 6 * 3600
RATE_MIN_SPAN_S = 120


def _rate_sample(done: int) -> tuple[float | None, float]:
    """追加 (ts, done) 采样 → (窗口速率/s, 窗口跨度) 或 (None, 0)。

    records.jsonl 跨重启 append-only 而 run_meta.started_at 是重启点，
    elapsed 口径在断点续跑后失真——改用最近 ``RATE_WINDOW_S`` 滑窗的
    Δcount/Δt；窗口样本不足（<2 个或跨度 < ``RATE_MIN_SPAN_S``）回退
    None 由调用侧走全程均速。
    """
    now = time.time()
    try:
        samples = json.loads(RATE_STATE.read_text())
    except (OSError, json.JSONDecodeError):
        samples = []
    if not isinstance(samples, list):
        samples = []
    samples.append([now, done])
    samples = [s for s in samples if now - s[0] <= RATE_KEEP_S]
    with contextlib.suppress(OSError):
        RATE_STATE.write_text(json.dumps(samples))
    win = [s for s in samples if now - s[0] <= RATE_WINDOW_S]
    if len(win) >= 2 and (span := win[-1][0] - win[0][0]) >= RATE_MIN_SPAN_S:
        return (win[-1][1] - win[0][1]) / span, span
    return None, 0.0


_BLOB_SHA_RE = re.compile(r"[0-9a-f]{64}")


def _unblob(val, blob_dir: Path | None):
    """{"$blob": sha, "$bytes": n} 卸载标记 → run derived/blobs/ 载荷——
    ``kernel.events.unblob`` 委派；kernel 缺席（裸跑降级面）时 inline
    严格形兜底。"""
    if _kevents is not None:
        return _kevents.unblob(val, blob_dir)
    if not (
        isinstance(val, dict)
        and set(val) == {"$blob", "$bytes"}
        and isinstance(val["$blob"], str)
        and _BLOB_SHA_RE.fullmatch(val["$blob"])
        and isinstance(val["$bytes"], int)
        and not isinstance(val["$bytes"], bool)
        and blob_dir is not None
    ):
        return val
    p = blob_dir / f"{val['$blob']}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return val


#: n200 段盯的 e2e 批 kind 集（realn200 是 importer 旧账名）。
_N200_KINDS = ("e2e_real", "realn200", "e2e")

#: 产出过 pdf 的终态词（compile/fixloop 段共用口径）。
_PDF_STATUS = {
    "ok",
    "clean",
    "partial",
    "dirty_pdf",
    "acceptable_pdf",
    "best_effort_pdf",
}

#: e2e 链 stage 序——done 判据 = 五段全有终态行（needs-skip 也落账）。
_N200_STAGES = ("route", "xlat", "compile", "fixloop", "base")


def _n200_run(conn: sqlite3.Connection | None) -> tuple[str, Path] | None:
    """最新 e2e 批 → (run_name, rundir)：runs 表 kind 过滤 run_seq 最大者。

    旧 RESULTS_DIR glob realn200-*/e2e-* 的等价面；无候选 → None
    （collect 走零形兜底）。"""
    if conn is None:
        return None
    r = None
    for kind in _N200_KINDS:  # 序即优先级——e2e_real 先于旧账名
        r = conn.execute(
            "SELECT run,kind,date,slug FROM runs WHERE kind=? "
            "ORDER BY run_seq DESC LIMIT 1",
            (kind,),
        ).fetchone()
        if r is not None:
            break
    if r is None:
        return None
    return r[0], RUNS_DIR / r[1] / r[2] / r[3]


def _paper_status(sm: dict[str, dict]) -> str:
    """篇目终态词：compile 实编结果优先，上游死法回退 xlat/route。"""
    comp = str((sm.get("compile") or {}).get("status") or "")
    if comp in ("clean", "partial", "fail", "reject", "dirty_pdf"):
        return "partial" if comp == "dirty_pdf" else comp
    x = str((sm.get("xlat") or {}).get("status") or "")
    if x in ("fail", "reject"):
        return x
    if str((sm.get("route") or {}).get("status") or "") == "reject":
        return "reject"
    return "skipped"


def _n200_empty() -> dict:
    """无 run 目录时的零形 st——消费方按 ``total == 0`` 分支渲染空态。"""
    return {
        "done": 0,
        "total": 0,
        "elapsed": 0.0,
        "rate_ps": None,
        "rate_span": 0.0,
        "started": None,
        "top": collections.Counter(),
        "fix": collections.Counter(),
        "base": collections.Counter(),
        "chunks": collections.Counter(),
        "reasons": collections.Counter(),
        "strip": [],
        "meta": {},
        "xlat_secs": 0.0,
        "xlat_exec": 0,
        "pdf_pipe": 0,
        "pdf_union": 0,
        "mtime": None,
        "in_flight": [],
        "queued": [],
        "dir": None,
    }


def n200_stats() -> dict:
    def collect() -> dict:
        conn = _kernel_index()
        found = _n200_run(conn)
        if found is None:
            return _n200_empty()
        run_name, nd = found
        # plan.json 冻结全集 → total/sample_ids/run_params；runs.ts_start
        # 是起跑戳。records 表逐格终态行（needs-skip 也落账）按 idc×stage
        # 重组篇目账——末条胜（重试格覆盖）。
        sample_ids: list[str] = []
        meta: dict = {}
        plan_p = nd / "plan.json"
        if plan_p.is_file():
            try:
                plan = json.loads(plan_p.read_text())
                cells = plan.get("cells") or []
                sample_ids = sorted(
                    {str(c.get("idc") or c.get("id") or "") for c in cells} - {""}
                )
                if cells:
                    meta["run_params"] = dict(cells[0].get("run_params") or {})
            except (ValueError, OSError):
                pass
        total = len(sample_ids)
        rrow = conn.execute(
            "SELECT ts_start FROM runs WHERE run=?", (run_name,)
        ).fetchone()
        started = (
            dt.datetime.fromtimestamp(rrow[0], dt.UTC) if rrow and rrow[0] else None
        )
        elapsed = (
            (dt.datetime.now(dt.UTC) - started).total_seconds() if started else 0.0
        )
        blob_dir = nd / "derived" / "blobs"
        if not blob_dir.is_dir():
            blob_dir = None
        per: dict[str, dict[str, dict]] = {}
        mtime = 0.0
        for row in conn.execute(
            "SELECT idc,stage,status,metrics,ts FROM records WHERE run=? ORDER BY seq",
            (run_name,),
        ):
            idc, stage, status, mraw, ts = row
            m = None
            if mraw:
                try:
                    m = _unblob(json.loads(mraw), blob_dir)
                except ValueError:
                    m = None
            per.setdefault(str(idc), {})[str(stage)] = {
                "status": status,
                "metrics": m if isinstance(m, dict) else {},
            }
            if ts and ts > mtime:
                mtime = ts
        top = collections.Counter()
        fix_stat = collections.Counter()
        base_stat = collections.Counter()
        chunks = collections.Counter()
        reasons = collections.Counter()
        strip = []
        xlat_secs = 0.0
        xlat_exec = pdf_pipe = pdf_union = 0
        for idc in sorted(per):
            sm = per[idc]
            pst = _paper_status(sm)
            top[pst] += 1
            strip.append((idc, pst))
            t = ((sm.get("xlat") or {}).get("metrics") or {}).get("translate") or {}
            xlat_secs += t.get("seconds", 0) or 0
            if t.get("chunks"):
                xlat_exec += 1
            for k in ("ok", "partial", "fault", "skipped", "chunks", "leftover_ph"):
                chunks[k] += t.get(k, 0) or 0
            pipe_pdf = (sm.get("compile") or {}).get("status") in _PDF_STATUS
            fix_pdf = (sm.get("fixloop") or {}).get("status") in _PDF_STATUS
            pdf_pipe += pipe_pdf
            pdf_union += pipe_pdf or fix_pdf
            v = ((sm.get("compile") or {}).get("metrics") or {}).get("verdict") or {}
            for rs in v.get("reasons", []):
                reasons[re.sub(r"\s*\(\d+\)\s*$", "", rs)] += 1
            if "fixloop" in sm:
                fix_stat[sm["fixloop"]["status"] or "?"] += 1
            if "base" in sm:
                base_stat[sm["base"]["status"] or "?"] += 1
        done_ids = {i for i, sm in per.items() if all(s in sm for s in _N200_STAGES)}
        in_flight = sorted(i for i, sm in per.items() if i not in done_ids)
        queued = [i for i in sample_ids if i not in per]
        meta["sample_ids"] = sample_ids
        # devin-2api 钉死面（specs/_shared.DEFAULT_BASE_URL）——gw 探活源
        meta.setdefault("base_url", "http://127.0.0.1:3033")
        meta["concurrency"] = (meta.get("run_params") or {}).get("concurrency")
        rate_ps, rate_span = _rate_sample(len(done_ids))
        return {
            "done": len(done_ids),
            "total": total or len(per),
            "elapsed": elapsed,
            "rate_ps": rate_ps,
            "rate_span": rate_span,
            "started": started,
            "top": top,
            "fix": fix_stat,
            "base": base_stat,
            "chunks": chunks,
            "reasons": reasons,
            "strip": strip,
            "meta": meta,
            "xlat_secs": xlat_secs,
            "xlat_exec": xlat_exec,
            "pdf_pipe": pdf_pipe,
            "pdf_union": pdf_union,
            "mtime": mtime or None,
            "in_flight": in_flight,
            "queued": queued,
            "dir": run_name,
        }

    return cached("n200", 30, collect)


def gw_status() -> str:
    def probe() -> str:
        meta = n200_stats()["meta"]
        base = (meta.get("base_url") or "").rstrip("/")
        if not base:
            return "未知"
        try:
            with urllib.request.urlopen(base + "/", timeout=3) as resp:  # noqa: S310 —— base 是本机 run_meta 钉的内网网关
                return f"可达 HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            return f"可达 HTTP {exc.code}"
        except Exception:
            return "不可达"

    return cached("gw", 60, probe)


def milestones() -> list[tuple[str, str]]:
    files = sorted(glob.glob(str(REPO / "docs/HANDOFF-*.md")))
    status_map = {
        "已验收": "done",
        "实质达成": "done",
        "达成": "done",
        "完成": "done",
        "推进中": "active",
        "在飞": "active",
        "未启": "pending",
        "规划": "pending",
    }
    found: dict[str, str] = {}
    if files:
        text = Path(files[-1]).read_text(errors="replace")[:4000]
        for m in re.finditer(
            r"M(\d)(?:/M(\d))?\s*(已验收|实质达成|达成|推进中|在飞|完成|未启\w*|规划\w*)",
            text,
        ):
            state = status_map.get(m.group(3), "pending")
            found[f"M{m.group(1)}"] = (m.group(3), state)
            if m.group(2):
                found[f"M{m.group(2)}"] = (m.group(3), state)
    if not found:
        found = {
            "M0": ("已验收", "done"),
            "M1": ("实质达成", "done"),
            "M2": ("推进中", "active"),
            "M3": ("推进中", "active"),
        }
    return [(k, *v) for k, v in sorted(found.items())]


def tasks() -> list[dict]:
    out = []
    if not TASKS_DIR.exists():
        return out
    for f in TASKS_DIR.glob("*.json"):
        try:
            t = json.loads(f.read_text())
            t["_file"] = f.stem
            out.append(t)
        except (OSError, json.JSONDecodeError):
            continue
    rank = {"starting": 0, "running": 0, "blocked": 1, "failed": 2, "done": 3}
    out.sort(key=lambda t: (rank.get(t.get("status"), 4), -t.get("ts", 0)))
    return out


# ---------- page sections


def sec_chips() -> str:
    chips: list[str] = []
    sc = scorecard_data()
    gate_ok = sc["gate"] == "PASS"
    chips.append(
        chip(
            "M2 联合 PDF",
            f"{sc['pdf_pct']:.2f}%",
            f"{sc['pdf_n']}/{sc['cells']} · 门槛 ≥90% {sc['gate']}",
            "good" if gate_ok else "bad",
        )
    )
    chips.append(
        chip(
            "clean 率",
            f"{sc['clean_pct']:.2f}%",
            f"{sc['clean_n']}/{sc['cells']}",
        )
    )
    st = n200_stats()
    if st["total"]:
        chips.append(
            chip(
                "n200 进度",
                f"{st['done']}/{st['total']}",
                f"{st['done'] / st['total'] * 100:.0f}% · 已跑 {fmt_dur(st['elapsed'])}",
            )
        )
    else:
        chips.append(chip("n200 进度", "—", "未发现 realn200/e2e run 目录"))
    c = st["chunks"]
    if c["chunks"]:
        ok_ph = not c["leftover_ph"] and not c["fault"]
        chips.append(
            chip(
                "chunk 通过",
                f"{c['ok'] / c['chunks'] * 100:.2f}%",
                f"残留占位符 {c['leftover_ph']}",
                "good" if ok_ph else "bad",
            )
        )
    df_tmp = run_cmd(["df", "-h", "/tmp"], 5).splitlines()  # noqa: S108 —— 监控对象即 /tmp 挂载
    if len(df_tmp) > 1:
        pct = int(re.search(r"(\d+)%", df_tmp[1]).group(1))
        chips.append(
            chip(
                "tmpfs /tmp",
                f"{pct}%",
                f"剩 {df_tmp[1].split()[3]}",
                "bad" if pct >= 80 else "",
            )
        )
    load = Path("/proc/loadavg").read_text().split()
    chips.append(chip("负载", load[0], f"5m {load[1]} · 15m {load[2]}"))
    gw = gw_status()
    chips.append(
        chip(
            "翻译网关",
            "在线" if gw.startswith("可达") else "离线",
            f"{gw} · swe-2-medium",
            "good" if gw.startswith("可达") else "bad",
        )
    )
    return "<div class='chips'>" + "".join(chips) + "</div>"


def sec_milestones() -> str:
    steps = []
    for name, zh, state in milestones():
        cls = {"done": "ms-done", "active": "ms-act", "pending": "ms-pend"}[state]
        extra = ""
        if name == "M2":
            sc = scorecard_data()
            extra = (
                f"<div class='msx'>联合 pdf {sc['pdf_pct']:.2f}% "
                f"(门≥90%) "
                + (
                    badge("PASS", C_CLEAN)
                    if sc["gate"] == "PASS"
                    else badge("FAIL", C_FAIL)
                )
                + "</div>"
            )
        steps.append(
            f"<div class='ms {cls}'><div class='msn'>{esc(name)}</div>"
            f"<div class='mss'>{esc(zh)}</div>{extra}</div>"
        )
    return "<div class='msrow'>" + "<div class='msarr'>→</div>".join(steps) + "</div>"


def sec_tasks() -> str:
    ts = tasks()
    hint = (
        "<div class='cap'>上报：<code>python3 bench/py/ops/task_ping.py "
        "&lt;名&gt; --status running --done N --total M --note …"
        "</code> · 完结 <code>--finish</code> · 撤下 <code>--remove</code>"
        "（看板目录 $TEXLATE_BENCH_ROOT/state/status-panel/tasks.d）</div>"
    )
    if not ts:
        return hint + "<div class='prow'>看板为空</div>"
    rows = []
    now = time.time()
    for t in ts:
        status = t.get("status", "?")
        stale = (
            status in ("starting", "running", "blocked")
            and now - t.get("ts", now) > STALE_TASK_SECONDS
        )
        total, done = t.get("total") or 0, t.get("done") or 0
        prog = minibar(done, total) if total else esc(done)
        sb = badge(
            TASK_STATUS_ZH.get(status, status), TASK_STATUS_COLOR.get(status, C_SKIP)
        )
        if stale:
            sb += " " + badge("静默>15m", C_PART)
        note = str(t.get("note") or "")[:60]
        rows.append(
            [
                f"<b>{esc(t.get('name', '?'))}</b>",
                esc(t.get("owner", "?")),
                prog,
                sb,
                esc(fmt_age(t.get("ts", now))),
                esc(note),
            ]
        )
    return table(["任务", "属主", "进度", "状态", "上报", "备注"], rows) + hint


def sec_n200() -> str:
    st = n200_stats()
    done, total = st["done"], st["total"]
    if not total:
        return "<div class='prow'>runs 表无 e2e_real/realn200 run——批尚未启动。</div>"
    if st["rate_ps"] is not None:
        rate = st["rate_ps"] * 3600
        basis = f"近{fmt_dur(st['rate_span'])}均速"
    else:
        rate = done / st["elapsed"] * 3600 if st["elapsed"] > 0 else 0
        basis = "全程均速"
    eta_s = (total - done) / (rate / 3600) if rate > 0 else 0
    eta_at = dt.datetime.now(tz=dt.UTC).astimezone() + dt.timedelta(seconds=eta_s)
    conc = st["meta"].get("concurrency")
    pid, note = N200_PID, "钉选"
    if not pid_alive(pid):
        # pgrep 模式跟随 run slug（bench run 命令行带 --slug）；run_cmd
        # 无输出哨兵是 "(exit N, no output)"——probe[0] 会是 "(exit"
        # 而非空，须 isdigit 兜底否则 int() 崩坏整节。
        slug = str(st.get("dir") or "").rsplit("/", 1)[-1] or "e2e"
        pat = f"bench.*{re.escape(slug)}"
        probe = run_cmd(["pgrep", "-f", pat], 5).split()
        pid, note = (
            (int(probe[0]), "自动发现")
            if probe and probe[0].isdigit()
            else (0, "未发现")
        )
    alive = pid and pid_alive(pid)
    parts = [
        f"<div class='prow'><b>{done}</b> / {total} 篇 "
        f"({done / total * 100:.1f}%) — 速率 {rate:.1f} 篇/时({basis}) · "
        f"并发 {conc if conc is not None else '?'} · "
        f"已跑 {fmt_dur(st['elapsed'])} · 预计剩余 {fmt_dur(eta_s)} "
        f"(约 {eta_at.strftime('%m-%d %H:%M')}) · "
        f"runner pid {pid or '-'}({note}) "
        + (badge("存活", C_CLEAN) if alive else badge("已退出", C_FAIL))
        + " · 网关 "
        + badge(gw_status(), C_CLEAN if gw_status().startswith("可达") else C_FAIL)
        + f" · 最后写入 {fmt_age(st['mtime'])}</div>"
    ]
    if st["in_flight"]:
        parts.append(
            "<div class='prow'>正在处理："
            + " ".join(f"<code>{esc(i)}</code>" for i in st["in_flight"])
            + f" · 队列待跑 {len(st['queued'])} 篇"
            + (
                "（下批 "
                + " ".join(f"<code>{esc(i)}</code>" for i in st["queued"][:4])
                + "…）"
                if st["queued"]
                else ""
            )
            + "</div>"
        )
    funnel = [
        ("采样", total, C_SKIP),
        ("已产出记录", done, C_INFO),
        ("翻译执行", st["xlat_exec"], C_PURPLE),
        ("pipe-xel 出 PDF", st["pdf_pipe"], C_PART),
        ("联合 PDF(+fixloop)", st["pdf_union"], C_CLEAN),
    ]
    parts.append(
        "<div class='cap'>阶段漏斗</div>"
        + "".join(hbar(k, v, total, c) for k, v, c in funnel)
    )
    parts.append(
        "<div class='cap'>逐篇状态（按完成序）</div>"
        "<div class='strip'>"
        + "".join(
            f"<i style='background:{STATUS_COLOR.get(s, C_SKIP)}' "
            f"title='{esc(i)} · {esc(STATUS_ZH.get(s, s))}'></i>"
            for i, s in st["strip"]
        )
        + "</div>"
    )
    order = ["clean", "partial", "fail"]
    parts.append(
        "<div class='cap'>编译判分</div>"
        + stacked(
            [(STATUS_ZH.get(k, k), st["top"].get(k, 0), STATUS_COLOR[k]) for k in order]
            + [(k, v, C_SKIP) for k, v in st["top"].most_common() if k not in order],
            done,
        )
    )
    c = st["chunks"]
    if c["chunks"]:
        parts.append(
            "<div class='cap'>翻译 chunk</div>"
            + stacked(
                [
                    ("通过", c["ok"], C_CLEAN),
                    ("部分", c["partial"], C_PART),
                    ("故障", c["fault"], C_FAIL),
                    ("跳过", c["skipped"], C_SKIP),
                ],
                c["chunks"],
            )
            + f"<div class='prow'>残留占位符 leftover_ph = "
            f"<b>{c['leftover_ph']}</b>（硬门=0）· "
            f"翻译累计 {st['xlat_secs'] / 60:.0f} 分钟</div>"
        )
    if st["fix"]:
        parts.append(
            "<div class='cap'>fixloop 修复臂 vs base 直编对照"
            f"（各 {sum(st['fix'].values())} 格）</div>"
            "<div class='two'>"
            + stacked(
                [
                    (STATUS_ZH.get(k, k), v, STATUS_COLOR.get(k, C_SKIP))
                    for k, v in st["fix"].most_common()
                ],
                sum(st["fix"].values()),
            )
            + stacked(
                [
                    (STATUS_ZH.get(k, k), v, STATUS_COLOR.get(k, C_SKIP))
                    for k, v in st["base"].most_common()
                ],
                sum(st["base"].values()),
            )
            + "</div>"
        )
    if st["reasons"]:
        mx = st["reasons"].most_common(1)[0][1]
        parts.append(
            "<div class='cap'>非 clean 原因</div>"
            + "".join(hbar(k, v, mx, C_FAIL) for k, v in st["reasons"].most_common(8))
        )
    return "".join(parts)


def _kernel_index() -> sqlite3.Connection | None:
    """Read-only handle on ledger/index.sqlite — ``query_only`` pragma,
    pure SELECTs; WAL readers never block the writer, and the section's
    exception isolation covers a momentarily-absent db."""
    p = BENCH_ROOT / "ledger" / "index.sqlite"
    if not p.is_file():
        return None
    conn = sqlite3.connect(str(p), timeout=5)
    conn.execute("PRAGMA query_only=ON")
    return conn


def sec_kernel() -> str:
    """Trizone-ledger kernel feed — index.sqlite projections + lock
    sentinels + run heartbeats (the v2 supply; the pre-v2 collectors
    below still feed the legacy panel sections)."""
    parts = []
    flags = []
    if (BENCH_ROOT / "PAUSE").exists():
        flags.append(badge("PAUSE", C_FAIL))
    if (BENCH_ROOT / "locks" / "AUTH_DEAD").exists():
        flags.append(badge("AUTH_DEAD", C_FAIL))
    if (BENCH_ROOT / ".kernel-active").exists():
        flags.append(badge("kernel-active", C_INFO))
    parts.append(
        "<div class='prow'>栅栏 "
        + (" ".join(flags) if flags else badge("无闸", C_CLEAN))
        + "</div>"
    )
    ev = BENCH_ROOT / "ledger" / "events.jsonl"
    if ev.exists():
        st = ev.stat()
        parts.append(
            f"<div class='prow'>ledger events.jsonl "
            f"{st.st_size / 1048576:.1f} MiB · 最后写入 {fmt_age(st.st_mtime)}</div>"
        )
    conn = _kernel_index()
    if conn is None:
        return "".join(parts) + "<div class='prow'>index.sqlite 尚未建立</div>"
    try:
        meta = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta")}
        dirty = (BENCH_ROOT / "ledger" / ".index-dirty").exists()
        parts.append(
            f"<div class='prow'>index sealed_gen "
            f"<b>{esc(meta.get('sealed_gen', '0'))}</b> · watermark "
            f"{esc(meta.get('watermark', '0'))} · "
            + (badge("dirty", C_FAIL) if dirty else badge("sealed", C_CLEAN))
            + "</div>"
        )
        # 最近 run + heartbeat 活性（heartbeat 文件 15s 一拍）
        rows = conn.execute(
            "SELECT run, kind, ts_start FROM runs ORDER BY ts_start DESC LIMIT 8"
        ).fetchall()
        if rows:
            trs = []
            for run, kind, ts in rows:
                # run = kind/date/slug — heartbeat lives at that path
                hb = BENCH_ROOT / "runs" / str(run) / "heartbeat"
                hb_age = fmt_age(hb.stat().st_mtime) if hb.exists() else "—"
                trs.append(
                    [
                        f"<code>{esc(run)}</code>",
                        esc(kind),
                        esc(fmt_age(ts or 0)),
                        esc(hb_age),
                    ]
                )
            parts.append(table(["run", "kind", "起跑", "心跳"], trs))
        mix = conn.execute(
            "SELECT status, COUNT(*) FROM cells GROUP BY status"
        ).fetchall()
        if mix:
            total = sum(n for _, n in mix)
            parts.append(
                "<div class='cap'>cells 状态面（末条胜）</div>"
                + stacked(
                    [(s, n, STATUS_COLOR.get(s, C_SKIP)) for s, n in mix],
                    total,
                )
            )
        held = conn.execute(
            "SELECT COUNT(*) FROM claims c1 WHERE op='acquire' AND rowid=("
            "SELECT MAX(rowid) FROM claims c2 WHERE "
            "c2.idc=c1.idc AND c2.arm=c1.arm AND c2.variant=c1.variant)"
        ).fetchone()[0]
        if held:
            parts.append(f"<div class='prow'>claims 持有 <b>{held}</b></div>")
    finally:
        conn.close()
    # lake catalog — last-wins state counts
    cat = BENCH_ROOT / "lake" / "corpus" / "catalog.jsonl"
    if cat.is_file():
        states: dict[str, int] = {}
        try:
            for line in cat.read_bytes().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                idc, state = row.get("idc"), row.get("state")
                if isinstance(idc, str):
                    states[idc] = state or "?"
        except (OSError, json.JSONDecodeError):
            pass
        counts = collections.Counter(states.values())
        if counts:
            parts.append(
                "<div class='cap'>lake catalog</div>"
                + stacked(
                    [
                        (s, n, C_INFO if s == "hydrated" else C_SKIP)
                        for s, n in counts.most_common()
                    ],
                    sum(counts.values()),
                )
            )
    return "".join(parts)


def sec_jobs() -> str:
    out = run_cmd(["ps", "-eo", "pid,etime,%cpu,%mem,args", "--sort", "pid"], 5)
    keep = re.compile(
        r"bench/py/|e2e_real_bench|stagerun|texlate web|status_panel|compilebench"
    )
    drop = re.compile(r"vscode-server|jedi|pylint|lsp_server|ps -eo|grep")
    rows = []
    for line in out.splitlines()[1:]:
        if not (keep.search(line) and not drop.search(line)):
            continue
        f = line.split(None, 4)
        if len(f) < 5:
            continue
        cmd = f[4]
        m = re.search(
            r"(e2e_real_bench\.py --tag \w+|texlate web.*port \d+|"
            r"status_panel\.py|stagerun[^ ]*|compilebench[^ ]*|"
            r"bench/py/[\w./]+)",
            cmd,
        )
        short = m.group(0) if m else cmd[-60:]
        rows.append(
            [
                esc(f[0]),
                esc(f[1]),
                esc(f[2]),
                esc(f[3]),
                f"<code>{esc(short)}</code>",
            ]
        )
    if not rows:
        return "<div class='prow'>没有在跑的 bench 进程</div>"
    return table(["pid", "已运行", "%cpu", "%mem", "命令"], rows)


def sec_sessions() -> str:
    rows = []
    for path in sorted(glob.glob(SESSIONS_GLOB)):
        try:
            s = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pid = s.get("pid", 0)
        alive = isinstance(pid, int) and pid_alive(pid)
        status = s.get("status", "?")
        scls = {"busy": C_INFO, "idle": C_CLEAN, "shell": C_PART}.get(status, C_SKIP)
        rows.append(
            (
                {"busy": 0, "idle": 1}.get(status, 2),
                [
                    f"<b>{esc(s.get('name') or s.get('sessionId', '?')[:12])}</b>",
                    badge(status, scls),
                    esc(pid),
                    badge("存活", C_CLEAN) if alive else badge("僵死", C_FAIL),
                    esc(
                        fmt_age(s.get("updatedAt", 0) / 1000)
                        if s.get("updatedAt")
                        else "-"
                    ),
                    f"<code>{esc(s.get('cwd', '?').replace(os.path.expanduser('~') + '/', '~/'))}</code>",
                ],
            )
        )
    rows = [r for _, r in sorted(rows, key=lambda t: t[0])]
    return (
        table(["会话", "状态", "pid", "进程", "活跃", "目录"], rows)
        if rows
        else "无会话文件"
    )


def sec_reports() -> str:
    """runs/ 三层 walk（kind/date/slug）→ 最近 12 个 run + 摘要行。"""
    dirs = (
        [d for d in RUNS_DIR.glob("*/*/*") if d.is_dir()] if RUNS_DIR.is_dir() else []
    )
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    rows = []
    for d in dirs[:12]:
        title = ""
        for cand in (
            "report.md",
            "derived/report.md",
            "summary.md",
            "README.md",
            "REPORT.md",
        ):
            f = d / cand
            if f.exists():
                for raw_ln in f.read_text(errors="replace").splitlines():
                    ln = raw_ln.strip().lstrip("#").strip()
                    if ln:
                        title = ln[:90]
                        break
                break
        if not title:
            files = sorted(p.name for p in d.iterdir() if p.is_file())[:3]
            title = "产物: " + ", ".join(files) + ("…" if len(files) == 3 else "")
        rows.append(
            [
                esc(fmt_age(d.stat().st_mtime)),
                f"<code>{esc('/'.join(d.parts[-3:]))}</code>",
                esc(title),
            ]
        )
    return table(["更新", "run", "摘要"], rows)


def sec_scorecard() -> str:
    sc = scorecard_data()
    parts = [
        f"<div class='prow'>cells <b>{sc['cells']}</b> · "
        f"union pdf <b>{sc['pdf_n']}</b> ({sc['pdf_pct']:.2f}%) · "
        f"end-state pdf <b>{sc['end_pdf_n']}</b> ({sc['end_pdf_pct']:.2f}%) · "
        f"clean <b>{sc['clean_n']}</b> ({sc['clean_pct']:.2f}%) · "
        "门≥90%: union "
        + (
            badge("PASS", C_CLEAN)
            if sc["gate"] == "PASS"
            else badge(sc["gate"], C_FAIL)
        )
        + " end-state "
        + (
            badge("PASS", C_CLEAN)
            if sc["end_gate"] == "PASS"
            else badge(sc["end_gate"], C_FAIL)
        )
        + (
            f" · 剔除 reject(n={sc['excl']['n']}): pdf {sc['excl']['pdf']}% "
            f"clean {sc['excl']['clean']}%"
            if sc["excl"]
            else ""
        )
        + "</div>"
    ]
    parts.append(
        "<div class='gatebar'><div class='gfill' "
        f"style='width:{min(sc['pdf_pct'], 100):.2f}%'></div>"
        "<div class='gmark' style='left:90%'></div>"
        f"<span class='gtxt'>pdf {sc['pdf_pct']:.2f}% ｜ 竖线=90% 门</span></div>"
    )
    if sc["end_state"]:
        mx = max(n for _, n in sc["end_state"])
        parts.append(
            "<div class='cap'>终态分布</div>"
            + "".join(
                hbar(
                    k,
                    n,
                    mx,
                    C_CLEAN
                    if "clean" in k
                    else C_PART
                    if "partial" in k
                    else C_FAIL
                    if ("fail" in k or "reject" in k)
                    else C_SKIP,
                )
                for k, n in sc["end_state"]
            )
        )
    if sc["top_sigs"]:
        mx = sc["top_sigs"][0][1]
        parts.append(
            "<div class='cap'>非 clean 签名 top</div>"
            + "".join(hbar(k, n, mx, C_INFO) for k, n in sc["top_sigs"][:12])
        )
    return "".join(parts)


def sec_resources() -> str:
    df_tmp = run_cmd(["df", "-h", "/tmp"], 5).splitlines()  # noqa: S108
    free = run_cmd(["free", "-g"], 5).splitlines()
    load = Path("/proc/loadavg").read_text().split()
    parts = []
    if len(df_tmp) > 1:
        f = df_tmp[1].split()
        pct = int(re.search(r"(\d+)%", df_tmp[1]).group(1))
        parts.append(
            "<div class='cap'>/tmp（usrquota tmpfs，EDQUOT 风险点）</div>"
            + hbar(
                f"/tmp {f[2]}/{f[1]}",  # noqa: S108 —— 监控对象即 /tmp 挂载
                pct,
                100,
                C_FAIL if pct >= 80 else C_PART if pct >= 60 else C_CLEAN,
                f"% · 剩 {f[3]}",
            )
        )
    if len(free) > 1:
        f = free[1].split()
        parts.append(
            "<div class='cap'>内存 GiB</div>"
            + hbar(
                f"已用 {f[2]}/{f[1]}", int(f[2]), int(f[1]), C_INFO, f"G · 可用 {f[6]}G"
            )
        )
    df_repo = run_cmd(["df", "-h", str(REPO)], 5).splitlines()

    def du() -> str:
        try:
            return run_cmd(["du", "-shx", str(REPO)], 30).split()[0]
        except (subprocess.TimeoutExpired, IndexError):
            return "?"

    if len(df_repo) > 1:
        f = df_repo[1].split()
        pct = int(re.search(r"(\d+)%", df_repo[1]).group(1))
        parts.append(
            "<div class='cap'>仓库盘</div>"
            + hbar(
                f"fs {f[2]}/{f[1]}",
                pct,
                100,
                C_FAIL if pct >= 90 else C_PART if pct >= 75 else C_CLEAN,
                f"% · 仓体 {cached('du', 600, du)}",
            )
        )
    parts.append(
        f"<div class='prow'>loadavg {load[0]} / {load[1]} / {load[2]} "
        f"（{load[3]} tasks）</div>"
    )
    return "".join(parts)


def sec_ledger() -> str:
    files = sorted(glob.glob(str(REPO / "docs/research/overseer-*.md")))
    if not files:
        return "无 overseer-*.md"
    path = Path(files[-1])
    tail = path.read_text(errors="replace").splitlines()[-18:]
    return (
        f"<div class='cap'>{esc(path.name)} 尾部</div>"
        f"<pre>{esc(chr(10).join(tail))}</pre>"
    )


SECTIONS = [
    ("里程碑", sec_milestones),
    ("trizone kernel", sec_kernel),
    ("任务看板（agent 上报）", sec_tasks),
    ("实时跑批 · realn200", sec_n200),
    ("M2 门 · scorecard", sec_scorecard),
    ("在跑进程", sec_jobs),
    ("舰队花名册", sec_sessions),
    ("最新产出 runs/", sec_reports),
    ("资源", sec_resources),
    ("台账摘要", sec_ledger),
]

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="{refresh}">
<title>texlate 状态面板</title>
<style>
body {{ font: 14px/1.5 -apple-system,"Segoe UI","Noto Sans CJK SC",
       "PingFang SC",sans-serif; margin: 1.2em auto; max-width: 1180px;
       padding: 0 1em; color: #1f2328; background: #fff; }}
h1 {{ font-size: 1.15em; margin: 0 0 .15em; }}
h2 {{ font-size: 1em; margin: 1.2em 0 .35em; color: #0550ae;
     border-bottom: 1px solid #e5e7ea; padding-bottom: .15em; }}
code, pre {{ font-family: ui-monospace,"SF Mono",monospace;
           font-size: .92em; }}
pre {{ background: #f6f8fa; border: 1px solid #d8dce0; border-radius: 6px;
      padding: .55em .75em; overflow-x: auto; margin: 0; }}
a {{ color: #0969da; }}
.meta {{ color: #656d76; font-size: .85em; }}
.chips {{ display: flex; flex-wrap: wrap; gap: .6em; margin: .8em 0 .4em; }}
.chip {{ border: 1px solid #d8dce0; border-radius: 8px; padding: .45em .8em;
        background: #fff; min-width: 9em;
        box-shadow: 0 1px 2px #00000008; }}
.chip .k {{ font-size: .72em; color: #656d76; }}
.chip .v {{ font-size: 1.3em; font-weight: 650; font-variant-numeric:
           tabular-nums; }}
.chip .s {{ font-size: .75em; color: #656d76; }}
.chip.good .v {{ color: {c_clean}; }}
.chip.bad .v {{ color: {c_fail}; }}
.cap {{ font-size: .8em; color: #656d76; margin: .7em 0 .25em; }}
.prow {{ margin: .35em 0; font-size: .93em; }}
.stack {{ display: flex; height: 14px; border-radius: 7px; overflow: hidden;
         background: #eef1f4; margin: .25em 0 .15em; }}
.seg {{ height: 100%; }}
.legend {{ font-size: .8em; color: #444; display: flex; gap: 1.1em;
          flex-wrap: wrap; }}
.lg i {{ display: inline-block; width: .75em; height: .75em;
        border-radius: 2px; margin-right: .3em; vertical-align: -1px; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 2em; }}
.strip {{ display: flex; flex-wrap: wrap; gap: 2px; margin: .2em 0; }}
.strip i {{ width: 14px; height: 14px; border-radius: 3px; }}
.hrow {{ display: flex; align-items: center; gap: .6em; margin: .12em 0; }}
.hl {{ width: 21em; font-size: .85em; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap; }}
.hb {{ flex: 1; height: 11px; background: #eef1f4; border-radius: 5px;
      overflow: hidden; }}
.hf {{ height: 100%; }}
.hn {{ width: 10em; font-size: .82em; color: #444;
      font-variant-numeric: tabular-nums; }}
.gatebar {{ position: relative; height: 20px; background: #eef1f4;
           border-radius: 6px; margin: .4em 0 .2em; overflow: hidden; }}
.gfill {{ height: 100%; background: linear-gradient(90deg,#2da44e99,#2da44e); }}
.gmark {{ position: absolute; top: 0; bottom: 0; width: 2px;
         background: {c_fail}; }}
.gtxt {{ position: absolute; left: .6em; top: 1px; font-size: .78em;
        color: #fff; text-shadow: 0 0 3px #0006; }}
table {{ border-collapse: collapse; font-size: .86em; width: 100%; }}
th {{ text-align: left; color: #656d76; font-weight: 600; font-size: .8em;
     border-bottom: 1px solid #d8dce0; padding: .25em .7em .25em 0; }}
td {{ padding: .22em .7em .22em 0; border-bottom: 1px solid #eef1f4;
     vertical-align: middle; }}
.bdg {{ display: inline-block; border: 1px solid; border-radius: 9px;
       padding: 0 .55em; font-size: .78em; line-height: 1.5; }}
.mb {{ display: inline-block; width: 8em; height: 8px; background: #eef1f4;
      border-radius: 4px; overflow: hidden; vertical-align: middle; }}
.mf {{ height: 100%; background: {c_info}; }}
.mbn {{ font-size: .82em; color: #444; margin-left: .4em; }}
.msrow {{ display: flex; align-items: stretch; gap: .4em; margin: .3em 0; }}
.ms {{ border: 1px solid #d8dce0; border-radius: 8px; padding: .4em .9em;
      min-width: 6.5em; }}
.ms .msn {{ font-weight: 700; font-size: 1.05em; }}
.ms .mss {{ font-size: .8em; color: #656d76; }}
.ms .msx {{ font-size: .78em; margin-top: .2em; }}
.ms-done {{ background: #f0fff4; border-color: #2da44e55; }}
.ms-done .msn {{ color: {c_clean}; }}
.ms-act {{ background: #fff8e6; border-color: #d4a72c88; }}
.ms-act .msn {{ color: {c_part}; }}
.ms-pend {{ color: #8b949e; }}
.msarr {{ align-self: center; color: #8b949e; }}
</style></head><body>
<h1>texlate 状态面板</h1>
<div class="meta">生成于 {now} · 每 {refresh}s 自刷 · 数据缓存 ≤60s ·
只读 · <a href="http://127.0.0.1:8765/">产品阅读器 :8765</a></div>
{chips}
{body}
</body></html>
"""


def render() -> str:
    parts = []
    for title, fn in SECTIONS:
        try:
            frag = fn()
        except Exception as exc:  # section isolation: never 500 the page
            frag = f"<pre style='color:{C_FAIL}'>采集异常: {esc(repr(exc))}</pre>"
        parts.append(f"<h2>{esc(title)}</h2>{frag}")
    try:
        chips_html = sec_chips()
    except Exception as exc:  # 同 SECTIONS 隔离——chips 采集崩不带垮整页
        chips_html = (
            f"<pre style='color:{C_FAIL}'>chips 采集异常: {esc(repr(exc))}</pre>"
        )
    now = dt.datetime.now(tz=dt.UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return PAGE.format(
        refresh=REFRESH_SECONDS,
        now=now,
        c_clean=C_CLEAN,
        c_fail=C_FAIL,
        c_part=C_PART,
        c_info=C_INFO,
        chips=chips_html,
        body="\n".join(parts),
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            body, ctype = b"ok\n", "text/plain"
        elif self.path in ("/", "/index.html"):
            body, ctype = render().encode(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        print(
            f"[{dt.datetime.now(tz=dt.UTC).astimezone():%H:%M:%S}] "
            f"{self.address_string()} {fmt % args}",
            flush=True,
        )


def _stop(*_args) -> None:
    PIDFILE.unlink(missing_ok=True)
    raise SystemExit(0)


def main() -> None:
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"[{dt.datetime.now(tz=dt.UTC).astimezone():%F %T}] "
        f"serving http://{HOST}:{PORT} pid={os.getpid()}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
