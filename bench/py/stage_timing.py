r"""stage_timing.py — stagerun 批的分阶段计时面：records/*.jsonl → 分布 + 单篇分解。

纯 stdlib + benchlib（系统 python3 可跑，同 stagerun_lib 约束——不引 texlate.*）。

用法::

    python3 bench/py/stage_timing.py bench/results/<run> [more runs...] \
        [--out NAME] [--top N] [--no-chunks]

产出 ``bench/results/_timing/<out>.{json,md}``（默认 ``<out>`` = 当天日期）。
json 是全量账（每篇每 lane 一格），md 是人读表（分阶段分布 + 慢篇榜 + 缺口注记）。

口径
----

- 每格取 append 序**末条**记录（同 ``stagerun_lib.load_latest``，(id,arm,upstream)
  键经 canon 归一）——resume/--rerun 重记时新账盖旧账。
- ``dur_s`` = 格内墙钟（``finish_rec`` monotonic）。xlat 的 dur_s 自
  queue_wait_s 仪表化起不含跨篇排队；**更老格（字段缺席）的 dur_s 含
  paper_sem 排队**——loop1 mock 即此形态（dur_s 线性爬坡至批次全长），
  真功看 ``inner_s``；脚本按 ``dur_s - inner > 阈`` 记 contaminated 数。
- 内层计时分拆：xlat ``metrics.translate.seconds``（pipe.run）、compile
  ``metrics.compile.seconds``（引擎纯编译）、fixloop ``metrics.fixloop_wall_s``
  （格内核）——外层-内层差即编排/注入/复判开销。
- 重试面：xlat ``attempts - (chunks - skipped)`` ≈ HTTP 重试次数（skipped
  是 state 命中不发请求的块）；块级明细 ``work/<sid>/xlat-<arm>.jsonl``
  （attempts/error_kind 逐块）只对带重试/非 ok 信号的篇回读（``--no-chunks`` 关）。
- 请求时序三分拆：``metrics.translate.req_timing``（stage_xlat
  ``_instrument_translator`` 记账）——``chat_s`` 纯 HTTP 时延、``backoff_s``
  退避睡眠（inner−chat）、``sem_wait_s`` 全局闸排队（outer−inner）、
  ``span_s`` 请求路径总占；派生 http_retries/mean_chat_s/req_par/
  orch_resid_s（编排残差 = innerΣ − spanΣ/conc）。仅新批有账。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchlib

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "bench/results/_timing"

STAGE_ORDER = ("ingest", "parse", "xlat", "compile", "fixloop")
#: 无 dur_s 功的门控终态（上游闸/未物化）——分布只在 worked 集上算。
GATED_STATUS = {"skip"}
PCTILES = (50, 90, 95, 99)


def _canon(pid: str) -> str:
    return str(pid).replace("--", "/")


def _key(rec: dict) -> tuple[str, str, str]:
    return (
        _canon(rec.get("id") or ""),
        str(rec.get("arm") or ""),
        str(rec.get("upstream") or ""),
    )


def _pct(xs: list[float], q: float) -> float | None:
    """最近秩百分位；空集 → None。"""
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, math.ceil(q / 100 * len(s)) - 1))
    return round(s[i], 3)


def _dist(xs: list[float]) -> dict:
    """计数 + 和 + 均值 + p50/90/95/99 + max——空集全 None。"""
    if not xs:
        return {
            "n": 0,
            "sum": 0.0,
            "mean": None,
            **{f"p{q}": None for q in PCTILES},
            "max": None,
        }
    return {
        "n": len(xs),
        "sum": round(sum(xs), 2),
        "mean": round(sum(xs) / len(xs), 3),
        **{f"p{q}": _pct(xs, q) for q in PCTILES},
        "max": round(max(xs), 3),
    }


def lane_label(stage: str, rec: dict) -> str:
    """(stage,arm,upstream) → 表内 lane 名（臂/上游并入，列宽可控）。"""
    arm = str(rec.get("arm") or "")
    up = str(rec.get("upstream") or "")
    if stage in ("ingest", "parse"):
        return stage
    if stage == "xlat":
        return f"xlat[{arm or '?'}]"
    if stage == "compile":
        return f"compile[{arm}·{up or 'src'}]"
    if stage == "fixloop":
        return f"fixloop[{up or 'src'}]"
    return f"{stage}[{arm}]"


def _inner_s(stage: str, rec: dict) -> float | None:
    """格内内核秒数（引擎/管道纯功）；无此面 → None。"""
    m = rec.get("metrics") or {}
    if stage == "xlat":
        v = (m.get("translate") or {}).get("seconds")
    elif stage == "compile":
        v = (m.get("compile") or {}).get("seconds")
    elif stage == "fixloop":
        v = m.get("fixloop_wall_s")
    else:
        v = None
    return float(v) if isinstance(v, (int, float)) else None


def _xlat_extras(rec: dict) -> dict:
    """xlat 格的重试/批量/流量面（translate 子账）。

    retries 口径：``attempts - (chunks - skipped)``——state-store 命中/
    占位符块的 skipped 不发请求（attempts=0），应先从 chunks 里扣掉再
    比 attempts（rt1 实证：skipped=1861 时 attempts<chunks 直减会漏报）。
    """
    t = (rec.get("metrics") or {}).get("translate") or {}
    chunks = t.get("chunks") or 0
    att = t.get("attempts") or 0
    skipped = t.get("skipped") or 0
    return {
        "retries": max(0, att - (chunks - skipped)),
        "attempts": att,
        "chunks": chunks,
        "skipped": skipped,
        "batched": t.get("batched") or 0,
        "src_chars": t.get("src_chars") or 0,
        "ok_chunks": t.get("ok") or 0,
    }


def _chunk_detail(work: Path, sid: str, arm: str) -> dict | None:
    """work/<sid>/xlat-<arm>.jsonl → 逐块 attempts/error_kind 聚合；缺席 → None。"""
    fp = work / sid / f"xlat-{arm}.jsonl"
    if not fp.exists():
        return None
    n = retries = 0
    kinds: Counter[str] = Counter()
    for r in benchlib.iter_jsonl(fp):
        n += 1
        att = int(r.get("attempts") or 0)
        if att > 1:
            retries += att - 1
        ek = str(r.get("error_kind") or "")
        if ek:
            kinds[ek] += 1
    return {"chunks": n, "retries": retries, "error_kinds": dict(kinds.most_common())}


def load_run(run_dir: Path, *, with_chunks: bool = True) -> dict:
    """单批全量账：lane 分布 + 单篇 join + run_meta 墙钟。"""
    rec_dir = run_dir / "records"
    # lane → 末条记录集 {id: rec}（同键 append 序后者胜）
    lanes: dict[str, dict[str, dict]] = {}
    lane_stage: dict[str, str] = {}
    files_seen = []
    for stage in STAGE_ORDER:
        fp = rec_dir / f"{stage}.jsonl"
        if not fp.exists():
            continue
        files_seen.append((stage, fp))
        latest = benchlib.latest_by(benchlib.iter_jsonl(fp), _key)
        for rec in latest.values():
            lane = lane_label(stage, rec)
            lanes.setdefault(lane, {})[_canon(rec.get("id") or "")] = rec
            lane_stage[lane] = stage

    lane_stats: dict[str, dict] = {}
    papers: dict[str, dict] = {}
    for lane, by_id in lanes.items():
        stage = lane_stage[lane]
        status = Counter()
        worked: list[float] = []  # dur_s>0 的实功格
        inner: list[float] = []
        qw: list[float] = []
        extra = {
            "queue_wait_s_present": 0,
            "queue_contaminated": 0,
            "retries": 0,
            "attempts": 0,
            "chunks": 0,
            "skipped": 0,
            "batched": 0,
            "src_chars": 0,
            "rounds": [],
            "n_actions": 0,
            "sources": Counter(),
            "err_kinds": Counter(),
        }
        for pid, rec in by_id.items():
            st = str(rec.get("status") or "?")
            status[st] += 1
            d = float(rec.get("dur_s") or 0.0)
            if st not in GATED_STATUS and d > 0:
                worked.append(d)
            iv = _inner_s(stage, rec)
            if iv is not None:
                inner.append(iv)
            cell = {"status": st, "dur_s": d}
            if "queue_wait_s" in rec:
                extra["queue_wait_s_present"] += 1
                qv = float(rec.get("queue_wait_s") or 0.0)
                qw.append(qv)
                cell["queue_wait_s"] = qv
            elif stage == "xlat" and st != "skip" and iv is not None and d - iv > 10:
                # queue_wait_s 缺席而 dur_s 远超内核秒——queue_wait 仪表化
                # 前格的 dur_s 含 paper_sem 排队（loop1 mock 实证线性爬坡）
                extra["queue_contaminated"] += 1
                cell["contaminated"] = True
            if iv is not None:
                cell["inner_s"] = iv
            if stage == "xlat":
                xe = _xlat_extras(rec)
                for k in (
                    "retries",
                    "attempts",
                    "chunks",
                    "skipped",
                    "batched",
                    "src_chars",
                ):
                    extra[k] += xe[k]
                if xe["retries"]:
                    cell["retries"] = xe["retries"]
                if xe["src_chars"]:
                    cell["src_chars"] = xe["src_chars"]
                # 请求时序三分拆（stage_xlat._instrument_translator 记账）：
                # chat=HTTP 时延 backoff=退避 sem_wait=全局闸排队 span=outer
                rt = (rec.get("metrics") or {}).get("translate") or {}
                rt = rt.get("req_timing")
                if isinstance(rt, dict):
                    acc = extra.setdefault(
                        "req_timing",
                        {
                            "n_papers": 0,
                            "calls": 0,
                            "chat_calls": 0,
                            "chat_s": 0.0,
                            "backoff_s": 0.0,
                            "sem_wait_s": 0.0,
                            "span_s": 0.0,
                        },
                    )
                    acc["n_papers"] += 1
                    for k in (
                        "calls",
                        "chat_calls",
                        "chat_s",
                        "backoff_s",
                        "sem_wait_s",
                        "span_s",
                    ):
                        acc[k] += float(rt.get(k) or 0.0)
            if stage == "fixloop":
                m = rec.get("metrics") or {}
                extra["rounds"].append(int(m.get("rounds") or 0))
                extra["n_actions"] += int(m.get("n_actions") or 0)
            if stage == "ingest":
                src = (rec.get("metrics") or {}).get("source")
                if src:
                    extra["sources"][str(src)] += 1
            for e in rec.get("errors") or []:
                ek = str(e.get("cat") or e.get("code") or "?")
                extra["err_kinds"][ek] += 1
            papers.setdefault(pid, {})[lane] = cell

        # 块级明细回读：只翻带重试/非 ok 信号的篇（loop1 mock 5k 目录不全读）
        if with_chunks and stage == "xlat":
            arm = next(iter(by_id.values()), {}).get("arm") or ""
            retry_kinds: Counter[str] = Counter()
            n_retried_chunks = n_read = 0
            for pid, rec in by_id.items():
                xe = _xlat_extras(rec)
                if not (xe["retries"] or str(rec.get("status")) not in ("ok", "skip")):
                    continue
                det = _chunk_detail(run_dir / "work", benchlib.safe_id(pid), str(arm))
                if det is None:
                    continue
                n_read += 1
                n_retried_chunks += det["retries"]
                for k, v in det["error_kinds"].items():
                    retry_kinds[k] += v
            if n_read:
                extra["chunk_detail"] = {
                    "papers_read": n_read,
                    "retried_chunks": n_retried_chunks,
                    "error_kinds": dict(retry_kinds.most_common()),
                }

        lane_stats[lane] = {
            "stage": stage,
            "n": len(by_id),
            "status": dict(status.most_common()),
            "dur_s": _dist(worked),
            "inner_s": _dist(inner),
            "queue_wait_s": _dist(qw) if qw else None,
            "extras": {
                k: (dict(v.most_common()) if isinstance(v, Counter) else v)
                for k, v in extra.items()
                if v not in (0, [], None) and not (isinstance(v, Counter) and not v)
            },
        }

    # run_meta → 每次 invocation 的墙钟段（按 ts 序，末段右端 = finished_at/最新账 mtime）。
    # span 挂 lane 键（xlat 用 --arm，compile 用 --arm+--xlat-arm，其余归 stage）——
    # 同 stage 多臂多次调用各自归账，Σdur/span 才对应得上。
    meta = benchlib.load_run_meta(run_dir, default={}) or {}
    _, t1 = benchlib.meta_window(meta)
    invocations = meta.get("invocations") or []
    latest_mtime = max((fp.stat().st_mtime for _s, fp in files_seen), default=None)
    # 在跑判据：meta 在且 finished_at 已被 records 写穿（收尾后又落账=仍在跑），
    # 或有 invocation 账而 finished_at 未封（mark_run_finished 未走）。meta 全缺
    # 的裸 records 目录不称在跑——无可证窗口。
    in_progress = bool(latest_mtime) and (
        (t1 is not None and latest_mtime > t1.timestamp() + 60)
        or (t1 is None and bool(invocations))
    )
    now_ts = datetime.now(UTC).timestamp()
    stalled_min = (
        round((now_ts - latest_mtime) / 60, 1)
        if in_progress and latest_mtime and now_ts - latest_mtime > 1800
        else 0.0
    )

    def _inv_lane(inv: dict) -> tuple[str, float | None]:
        argv = [str(x) for x in inv.get("argv") or []]

        def _opt(name: str) -> str | None:
            if name in argv:
                return argv[argv.index(name) + 1]
            eq = name + "="
            hit = next((x for x in argv if x.startswith(eq)), None)
            return hit[len(eq) :] if hit else None

        stage = str(inv.get("stage") or "?")
        jraw = _opt("--jobs")
        try:
            jobs = float(jraw) if jraw else None
        except ValueError:
            jobs = None
        try:
            conc = float(_opt("--concurrency") or "") or None
        except ValueError:
            conc = None
        if stage == "xlat":
            return f"xlat[{_opt('--arm') or '?'}]", jobs, conc
        if stage == "compile":
            arm = _opt("--arm") or "?"
            xa = _opt("--xlat-arm")
            return (f"compile[{arm}·{xa}]" if xa else f"compile[{arm}]"), jobs, conc
        return stage, jobs, conc

    spans: list[tuple[str, float]] = []
    lane_jobs: dict[str, float] = {}
    lane_conc: dict[str, float] = {}
    prev_ts = prev_lane = None
    for inv in sorted(invocations, key=lambda i: str(i.get("ts") or "")):
        ts = benchlib.parse_iso(inv.get("ts"))
        lane, jobs, conc = _inv_lane(inv)
        if jobs:
            lane_jobs[lane] = max(jobs, lane_jobs.get(lane, 0))
        if conc:
            lane_conc[lane] = max(conc, lane_conc.get(lane, 0))
        if prev_ts is not None and ts is not None:
            spans.append((prev_lane, ts.timestamp() - prev_ts))
        prev_ts, prev_lane = (ts.timestamp() if ts else None), lane
    if prev_ts is not None:
        right = (t1.timestamp() if t1 else None) or 0.0
        if latest_mtime:
            right = max(right, latest_mtime)
        # in_progress：右端取末条记录 mtime（=账覆盖的活动窗）而非 now——
        # 停滞批用 now 会把停摆时长计入 span 稀释 ∥（rt1 实证：write 静默
        # 449min 而进程活着）。在飞未落账的尾段固有漏算，stalled_min 单列。
        if right > prev_ts:
            spans.append((prev_lane, right - prev_ts))
    lane_span: Counter[str] = Counter()
    stage_span: Counter[str] = Counter()
    for lane, sec in spans:
        lane_span[lane] += sec
        stage_span[lane.split("[", 1)[0]] += sec

    # 有效并行度 = 内核秒（无则 worked dur）/ lane 墙钟段；lane 无对应
    # invocation 段时回退 stage 段并标 approx。∥>jobs ⇒ span 被并发
    # invocation 的 ts 切段低估（loop1 实证 xlat real 与 compile 交叠）。
    for lane, st in lane_stats.items():
        num = st["inner_s"]["sum"] or st["dur_s"]["sum"]
        approx = False
        # compile[zh·mock] 对上 --xlat-arm mock 段；裸 --arm 段（compile[base]）
        # 兜底 lane 去 ·upstream 后缀（compile[base·src] → compile[base]）。
        cands = [lane]
        if "·" in lane:
            cands.append(lane.split("·", 1)[0] + "]")
        sp = next((lane_span[c] for c in cands if lane_span.get(c)), None)
        if not sp:
            sp = stage_span.get(st["stage"])
            approx = True
        if sp and sp > 0 and num:
            par = num / sp
            jb = lane_jobs.get(lane) or lane_jobs.get(st["stage"])
            st["parallelism"] = round(par, 2)
            st["parallelism_approx"] = approx
            if jb and par > jb * 1.2:
                st["parallelism_suspect"] = f"span_underestimate:jobs={jb:g}"

    # 请求时序派生：HTTP 重试数、单请求均延、请求路径并行度、编排残差。
    # orch_resid = innerΣ − spanΣ/conc——worker 不满载部分的壁钟（排队/IO/
    # splice 等编排面），conc 缺席按管道默认 10。
    for lane, st in lane_stats.items():
        rt = st["extras"].get("req_timing")
        if not rt or not rt["calls"]:
            continue
        inner_sum = st["inner_s"]["sum"]
        rt["http_retries"] = int(max(0, rt["chat_calls"] - rt["calls"]))
        rt["mean_chat_s"] = round(rt["chat_s"] / max(rt["chat_calls"], 1), 1)
        if inner_sum > 0:
            rt["req_par"] = round(rt["span_s"] / inner_sum, 2)
            conc = lane_conc.get(lane) or 10
            rt["orch_resid_s"] = round(inner_sum - rt["span_s"] / conc, 1)

    rows = [
        {
            "id": pid,
            "cells": cells,
            "total_s": round(sum(c["dur_s"] for c in cells.values()), 2),
        }
        for pid, cells in papers.items()
    ]
    rows.sort(key=lambda r: -r["total_s"])
    return {
        "dir": str(run_dir),
        "name": run_dir.name,
        "git_rev": meta.get("git_rev"),
        "window": {
            "started_at": meta.get("started_at"),
            "finished_at": meta.get("finished_at"),
            "in_progress": in_progress,
            "stalled_min": stalled_min,
            "last_record_mtime": (
                datetime.fromtimestamp(latest_mtime, UTC).isoformat(timespec="seconds")
                if latest_mtime
                else None
            ),
        },
        "stage_spans": dict(stage_span),
        "lane_spans": dict(lane_span),
        "lane_conc": dict(lane_conc),
        "lanes": lane_stats,
        "papers": rows,
    }


def _fmt(v, unit="s") -> str:
    return "-" if v is None else (f"{v:.1f}{unit}" if isinstance(v, float) else str(v))


def render_md(runs: list[dict], out_name: str, top_n: int) -> str:
    lines = [
        f"# e2e 分阶段计时面 — {out_name}",
        "",
        (
            f"生成：{datetime.now(UTC).isoformat(timespec='seconds')}；"
            "数据源 records/*.jsonl（末条胜）。dur_s=格内墙钟；"
            "inner=格内内核（xlat=translate.seconds / compile=compile.seconds"
            " / fixloop=fixloop_wall_s）。"
        ),
        "",
    ]
    for run in runs:
        w = run["window"]
        lines += [
            f"## {run['name']}",
            "",
            f"- git_rev `{run['git_rev']}`；窗口 {w['started_at']} → {w['finished_at']}"
            + ("（**批仍在跑**，span 右端=末条记录时刻）" if w["in_progress"] else "")
            + (
                f"；**疑似停滞**：末条 records 写入于 {w['last_record_mtime']}（{w['stalled_min']:.0f}min 前）"
                if w.get("stalled_min")
                else ""
            ),
            f"- invocation 墙钟段（lane 级）：{', '.join(f'{k}={v / 60:.0f}min' for k, v in sorted(run['lane_spans'].items())) or '（无 run_meta）'}",
            "",
            "| lane | n | 状态分布 | worked | Σdur | p50 | p95 | p99 | max | innerΣ | inner/outer | ∥ |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for lane in sorted(
            run["lanes"], key=lambda x: (STAGE_ORDER.index(run["lanes"][x]["stage"]), x)
        ):
            st = run["lanes"][lane]
            d = st["dur_s"]
            inn = st["inner_s"]
            stat_str = " ".join(f"{k}:{v}" for k, v in st["status"].items())
            share = (
                f"{inn['sum'] / d['sum'] * 100:.0f}%" if inn["n"] and d["sum"] else "-"
            )
            par = _fmt(st.get("parallelism"), "x")
            if st.get("parallelism_approx"):
                par += "~"  # 分子对的是 stage 总段而非本 lane 段
            if st.get("parallelism_suspect"):
                par += "!"  # ∥超 --jobs：span 被并发 invocation 的 ts 切段低估
            lines.append(
                f"| {lane} | {st['n']} | {stat_str} | {d['n']} | {d['sum']:.0f}s "
                f"| {_fmt(d['p50'])} | {_fmt(d['p95'])} | {_fmt(d['p99'])} | {_fmt(d['max'])} "
                f"| {inn['sum']:.0f}s | {share} | {par} |"
            )
        lines.append("")

        # xlat 深挖：排队/重试/吞吐
        xlat_lanes = [ln for ln in run["lanes"] if ln.startswith("xlat")]
        if xlat_lanes:
            lines += ["### xlat 深挖", ""]
            for lane in sorted(xlat_lanes):
                st = run["lanes"][lane]
                ex = st["extras"]
                qd = st.get("queue_wait_s")
                parts = []
                if qd and qd["n"]:
                    parts.append(
                        f"queue_wait n={qd['n']} Σ={qd['sum']:.0f}s p95={_fmt(qd['p95'])} max={_fmt(qd['max'])}"
                        f"（覆盖 {ex.get('queue_wait_s_present', qd['n'])}/{st['n']} 格）"
                    )
                elif ex.get("queue_wait_s_present"):
                    parts.append(
                        f"queue_wait 覆盖 {ex['queue_wait_s_present']}/{st['n']} 格"
                    )
                else:
                    parts.append("queue_wait_s 字段缺席（本批未到仪表化版本）")
                if ex.get("queue_contaminated"):
                    parts.append(
                        f"⚠ **{ex['queue_contaminated']} 格 dur_s 疑含跨篇排队**"
                        "（queue_wait_s 缺席且 dur−inner>10s）——dur 分布失真，真功看 innerΣ"
                    )
                if ex.get("attempts"):
                    parts.append(
                        f"chunks={ex.get('chunks', 0)} attempts={ex['attempts']} "
                        f"retries≈{ex.get('retries', 0)} batched={ex.get('batched', 0)}"
                    )
                if ex.get("src_chars") and st["inner_s"]["sum"]:
                    parts.append(
                        f"src_chars={ex['src_chars']} → {ex['src_chars'] / max(st['inner_s']['sum'], 0.1):.0f} chars/s（inner 口径）"
                    )
                cd = ex.get("chunk_detail")
                if cd:
                    ek = " ".join(
                        f"{k}:{v}" for k, v in list(cd["error_kinds"].items())[:8]
                    )
                    parts.append(
                        f"块明细回读 {cd['papers_read']} 篇：retried_chunks={cd['retried_chunks']} error_kind[{ek or '无'}]"
                    )
                lines.append(f"- **{lane}**：" + "；".join(parts))
                rt = ex.get("req_timing")
                if rt:
                    conc = (run.get("lane_conc") or {}).get(lane)
                    tail = ""
                    if rt.get("req_par"):
                        tail += f"，req_par={rt['req_par']}"
                        if conc:
                            tail += f"/conc={conc:g}"
                    if rt.get("orch_resid_s") is not None:
                        tail += f"；编排残差≈{rt['orch_resid_s']:.0f}s"
                    lines.append(
                        f"  - 请求时序（{rt['n_papers']} 篇）：calls={rt['calls']:.0f} "
                        f"chat={rt['chat_calls']:.0f}（HTTP 重试 {rt.get('http_retries', 0)}）"
                        f" chatΣ={rt['chat_s']:.0f}s（均 {rt.get('mean_chat_s', 0)}s/req）"
                        f" backoffΣ={rt['backoff_s']:.0f}s semΣ={rt['sem_wait_s']:.0f}s"
                        f" spanΣ={rt['span_s']:.0f}s{tail}"
                    )
            lines.append("")

        # fixloop/compile 附注
        for lane in sorted(run["lanes"]):
            st = run["lanes"][lane]
            ex = st["extras"]
            if lane.startswith("fixloop") and (ex.get("rounds") or ex.get("n_actions")):
                rr = ex.get("rounds") or []
                lines.append(
                    f"- {lane}：rounds Σ={sum(rr)} max={max(rr) if rr else 0}，n_actions Σ={ex.get('n_actions', 0)}"
                )
            if lane.startswith("ingest") and ex.get("sources"):
                lines.append(f"- {lane}：source 分布 {ex['sources']}")
        lines.append("")

        # 慢篇榜
        lanes_sorted = sorted(
            {ln for p in run["papers"] for ln in p["cells"]},
            key=lambda x: (
                STAGE_ORDER.index(
                    run["lanes"].get(x, {}).get("stage", "xlat")
                    if x in run["lanes"]
                    else 5
                ),
                x,
            ),
        )
        top = run["papers"][:top_n]
        lines += [
            f"### 单篇分解 top {len(top)}（按各格 Σdur_s 降序；`+qN`=queue_wait_s，`*`=dur_s 疑含排队）",
            "",
            "| id | " + " | ".join(lanes_sorted) + " | Σ |",
            "|---|" + "---|" * (len(lanes_sorted) + 1),
        ]
        for p in top:
            cells = []
            for ln in lanes_sorted:
                c = p["cells"].get(ln)
                if c is None:
                    cells.append("-")
                else:
                    s = f"{c['status']} {c['dur_s']:.1f}"
                    if c.get("queue_wait_s"):
                        s += f"+q{c['queue_wait_s']:.0f}"
                    if c.get("contaminated"):
                        s += "*"
                    cells.append(s)
            lines.append(
                f"| {p['id']} | " + " | ".join(cells) + f" | {p['total_s']:.0f}s |"
            )
        lines.append("")

    lines += [
        "## 未测出 / 缺口",
        "",
        (
            "- xlat `req_timing` 仅仪表化后新批有账；存量批（rt1 等）无此字段。"
            "编排残差 = innerΣ − spanΣ/conc 是推导值——spanΣ 含 sem 排队，"
            "残差混着 worker 空转/state IO/splice，非纯净编排功。"
        ),
        "- ingest：dur_s 含下载+解包合一，无下载/解包子相位（metrics.source 只见 cache/ia）。",
        "- compile：注入/复判开销 = dur_s − compile.seconds 间接得；inject 无独立计时。",
        "- parse：无 mouth/gullet/segmenter 子相位计时。",
        (
            "- xlat `dur_s` 在 queue_wait_s 仪表化前的存量格**含跨篇排队**（上表 ⚠ 计数）；"
            "修正真功用 `inner_s`。块级 error_kind 只记终态失败种别——HTTP 重试后恢复的块 "
            "error_kind 为空，重试**原因**不可归因（只有次数）。"
        ),
        (
            "- invocation 段由相邻 ts 切段：并发开跑的 stage 会互吃对方段（∥! 标记）；"
            "records 行无 ts，无法更细。"
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="stagerun records 分阶段计时面")
    ap.add_argument("runs", nargs="+", type=Path, help="bench/results/<run> 目录")
    ap.add_argument("--out", default=None, help="输出基名（默认=当天日期）")
    ap.add_argument("--top", type=int, default=25, help="md 慢篇榜行数")
    ap.add_argument("--no-chunks", action="store_true", help="不回读块级明细")
    a = ap.parse_args()

    runs = []
    for raw in a.runs:
        d = raw.expanduser().resolve()
        if not (d / "records").is_dir():
            print(f"!! {d} 无 records/ — 跳过", file=sys.stderr)
            continue
        runs.append(load_run(d, with_chunks=not a.no_chunks))
    if not runs:
        print("无可分析批", file=sys.stderr)
        return 1

    out_name = a.out or datetime.now(UTC).strftime("%Y-%m-%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jp = OUT_DIR / f"{out_name}.json"
    mp = OUT_DIR / f"{out_name}.md"
    jp.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "runs": runs,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    mp.write_text(render_md(runs, out_name, a.top), encoding="utf-8")
    print(f"wrote {jp}\nwrote {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
