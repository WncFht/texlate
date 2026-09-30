"""ops.status_panel 采集叶 —— scorecard/rate/n200/gw/milestones/tasks/
kernel index 各读件（status_panel.py 拆分叶）。

门面回引名单见 ``ops.status_panel._LEAF_EXPORTS``。
"""

from __future__ import annotations

import collections
import contextlib
import datetime as dt
import glob
import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

from ops._status_panel_env import (
    BENCH_ROOT,
    PANEL_DIR,
    REPO,
    RUNS_DIR,
    TASKS_DIR,
    VENV_PY,
    _kevents,
)
from ops._status_panel_util import cached, run_cmd

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
