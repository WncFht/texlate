#!/usr/bin/env python3
"""gate_scorecard — M2 出口门记分卡。

用法:
    python3 bench/py/gate_scorecard.py [records_dir] [--json]
                                        [--require-frozen] [--write-window S]

缺省读 bench/results/stagerun-loop1-2026-09-16/records/。
对每篇 paper 取 compile(zh,upstream=mock)/fixloop(upstream=mock) 末条
record，两套口径并列（scope 块钉死语义，防臂并集误读）：

    end-state(末段胜)  新鲜 fixloop 记录存在即取 fixloop 终态，否则 compile
    union(best-of)     compile 与新鲜 fixloop 两段取较优终态(STATUS_RANK)

union 名实（2026-09-18 复核）：union=**阶段并集** best-of(compile∪fixloop)
按格取优——即 docs/10 的「union 口径取 pipe-xel/pipe-fix 较优者」，zh 臂
mock 上游单人口径，**非 zh+base 臂并集**（M2 门是 zh 条件编译成功率，base
臂是归因基线不入格）。输出 scope 块显式标注，防再次名实争议。

fix 覆盖有门槛：compile 终态须为真编译结果(fail/partial/clean，
reject/skip 格的 fixloop 记录是 --on all 误编译英文树的产物不计入)。
新鲜度校验两档：fix 记录带 ``metrics.compile_fp`` 时做 compile 记录
指纹比对——compile 重跑 status 不变但 sig/first_error 已换(同态陈旧)
也拦；无指纹的史前排记录回退 ``compile_status_before`` 状态等值校验，
校验档位计数进 csb-check 块（fingerprint/legacy_status/none 三分——
无 provenance 字段的记录不再误记 legacy_status）。

csb 校验加深（09-17 波次互踩复盘）：
  - post_inconsistent: metrics.post.status 与顶 status 相悖 → 拼账/腐记
    录，不可信，丢。
  - csb_contradicts_fp: 指纹匹配证明 fix 吃的就是当前 compile，而 csb
    字段相悖 → 拼账记录，丢。
  - window_stale: legacy-csb 过门但 run_meta 波次窗判定 compile(zh,mock)
    覆盖波晚于 fixloop(同上游) 覆盖波——fix 记录可能参照的是已被重写的
    compile，csb 状态等值挡不住同态重跑 → 按陈旧丢。估计式：compile 侧
    取最新覆盖波 ts（任何覆盖波都可能重写，悲观界）；fixloop 侧取
    max(--rerun 覆盖波, 最早覆盖波)（非 rerun 波对 done 格不重写——
    skip/error 格可被后续非 rerun 波重写是已知近似边，属保守方向）。

波次冻结窗（防在飞波次半截读入记分）：freeze 块综合四路信号——
run_meta 末 invocation.ts > finished_at（在飞或被看门狗硬杀的波次）、
records 文件 mtime 落 ``--write-window``（默认 120s）内、末非空行 json
截尾、读前后 (size,mtime_ns) 双采样比对（torn read）。任一命中 →
freeze.status=partial，读数为在飞截面，文本/json 均显式标注；
``--require-frozen`` 时拒绝记分（exit 3，只出 freeze 块）。

另有 90% 门缺口数、excl-reject 口径、population 过滤账（逐文件行级
去向计数）。依赖: 纯 stdlib。
"""

import argparse
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import benchlib

DEFAULT_DIR = Path("bench/results/stagerun-loop1-2026-09-16/records")
GATE = 0.90
SCHEMA = "gate_scorecard/v3"
#: M2 门人口边界——zh 臂 + mock 上游；base 臂/real 上游记录不入格。
ARM = "zh"
UPSTREAM = "mock"
#: records 文件 mtime 距读时点窗内 → 在飞写入嫌疑（--write-window 可调）。
ACTIVE_WRITE_WINDOW_S = 120.0

COMPILED = benchlib.COMPILED_STATUS
_RANK = benchlib.STATUS_RANK
#: compile 记录指纹单源——读侧比对与 stage_fixloop 写侧同一函数。
compile_fp = benchlib.compile_fp
#: 出 pdf 的终态集——end-state/union 两口径共用。
PDF_STATUS = {"clean", "partial"}


def scan_records(
    path: Path, arm: str | None = None, upstream: str | None = "mock"
) -> tuple[dict[str, dict], Counter]:
    """records 文件全扫 → (末条胜 dict, 行级去向账)。

    账键：rows（非空行）/ bad_lines（json 截尾等）/ non_dict / arm_filtered /
    upstream_filtered / arm_mismatch / bad_id / accepted / unique /
    superseded（被同键后行覆盖——波次重写的量）。
    """
    stats: Counter = Counter()
    if not path.exists():
        stats["missing"] = 1
        return {}, stats

    def _bad(_raw: str, _exc: Exception) -> None:
        stats["bad_lines"] += 1

    kept = []
    for r in benchlib.iter_jsonl(path, on_bad=_bad, errors="replace"):
        stats["rows"] += 1
        if not isinstance(r, dict):
            stats["non_dict"] += 1
            continue
        if arm is not None and r.get("arm") != arm:
            stats["arm_filtered"] += 1
            continue
        # 双臂波次防串：对臂记录不进本口径——upstream 字段缺失按 mock
        # 计（史前排无此字段）；arm_mismatch skip 是对臂 decline 零
        # verdict 信息，两侧视图全跳。
        if upstream is not None and (r.get("upstream") or "mock") != upstream:
            stats["upstream_filtered"] += 1
            continue
        errs = r.get("errors")
        if not isinstance(errs, list):
            errs = []
        if any(isinstance(e, dict) and e.get("code") == "arm_mismatch" for e in errs):
            stats["arm_mismatch"] += 1
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            stats["bad_id"] += 1
            continue
        stats["accepted"] += 1
        kept.append(r)
    latest = benchlib.latest_by(kept, lambda r: r["id"])
    stats["unique"] = len(latest)
    stats["superseded"] = stats["accepted"] - stats["unique"]
    return latest, stats


def last_records(
    path: Path, arm: str | None = None, upstream: str | None = "mock"
) -> dict[str, dict]:
    return scan_records(path, arm, upstream)[0]


def pick_final(
    c: dict, f: dict | None, *, window_suspect: bool = False
) -> tuple[str, dict, str | None]:
    """合成终态：(stage, record, drop_reason)。

    fix 只在覆盖真编译结果且未过期时生效——`--on all` 会对
    inject:reject/skip 格也产出 fixloop 记录（编译被拒英文树），
    不能计入。记录内部一致性闸：``metrics.post.status`` 与顶 status
    相悖 = 拼账/腐记录（post_inconsistent）。新鲜度校验：``metrics.compile_fp``
    在场按 compile 记录指纹比对（同态陈旧拦 fp_mismatch；指纹匹配而 csb
    字段相悖 = 拼账记录 csb_contradicts_fp），缺席回退
    ``compile_status_before`` 状态等值（status 同而 log/树已换挡不住——
    弱校验档位由调用侧计数）。legacy 档另加波次窗校验：run_meta 判定
    compile(zh,本上游) 覆盖波晚于 fixloop(同上游) 覆盖波时，csb 等值
    可能是同态重跑巧合 → window_stale 按陈旧丢。
    compile 在 fix 之后重跑且指纹/status 改变时 fix 陈旧作废。
    """
    if f is None:
        return "compile", c, None
    if c.get("status") not in COMPILED:
        return "compile", c, "over_noncompiled"
    fmet = f.get("metrics")
    if not isinstance(fmet, dict):
        fmet = {}
    post = fmet.get("post")
    if isinstance(post, dict):
        ps = post.get("status")
        if isinstance(ps, str) and ps and ps != f.get("status"):
            return "compile", c, "post_inconsistent"
    fp = fmet.get("compile_fp")
    if isinstance(fp, str) and fp:
        if fp != compile_fp(c):
            return "compile", c, "fp_mismatch"
        csb = fmet.get("compile_status_before")
        if csb is not None and csb != c.get("status"):
            return "compile", c, "csb_contradicts_fp"
    else:
        csb = fmet.get("compile_status_before")
        if csb is None:
            return "compile", c, "no_csb"
        if csb != c.get("status"):
            return "compile", c, "stale"
        if window_suspect:
            return "compile", c, "window_stale"
    cu, fu = c.get("upstream"), f.get("upstream")
    if cu and fu and cu != fu:
        return "compile", c, "upstream_mismatch"
    return "fixloop", f, None


# ---------------------------------------------------------------- 波次窗
def _inv_argv(inv: dict) -> list:
    a = inv.get("argv")
    return a if isinstance(a, list) else []


def _inv_opt(inv: dict, name: str) -> str | None:
    """invocation.argv 里 --name 的值；缺席/无值 → None。"""
    a = _inv_argv(inv)
    try:
        i = a.index(name)
    except ValueError:
        return None
    return a[i + 1] if i + 1 < len(a) else None


def _inv_ids(inv: dict) -> frozenset[str] | None:
    """--ids 显式集；缺席/空 → None（全量覆盖语义）。"""
    v = _inv_opt(inv, "--ids")
    if not isinstance(v, str) or not v.strip():
        return None
    return frozenset(x.strip() for x in v.split(",") if x.strip())


def _norm_dt(dt: datetime | None) -> datetime | None:
    """naive dt 按 UTC 计——与 run_meta 写侧 (aware) 可比。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _inv_ts(inv: dict) -> datetime | None:
    return _norm_dt(benchlib.parse_iso(inv.get("ts")))


def _meta_invs(meta: dict, stage: str, *, upstream: str) -> list[tuple]:
    """stage+上游覆盖口径的 invocation 子集 → (ts, rerun, ids) 按 ts 升序。

    --xlat-arm 缺席 = 不限定上游（按覆盖计，保守方向）；compile 侧
    --arm 非 zh（base 臂）滤出——base 记录不入本口径、重写不动 zh 账。
    """
    out = []
    for inv in meta.get("invocations") or []:
        if not isinstance(inv, dict) or inv.get("stage") != stage:
            continue
        if stage == "compile" and _inv_opt(inv, "--arm") not in (None, "zh"):
            continue
        xu = _inv_opt(inv, "--xlat-arm")
        if xu is not None and xu != upstream:
            continue
        t = _inv_ts(inv)
        if t is None:
            continue
        out.append((t, "--rerun" in _inv_argv(inv), _inv_ids(inv)))
    out.sort(key=lambda x: x[0])
    return out


def _cover_max(invs: list[tuple], pid: str, *, rerun_only: bool = False) -> datetime | None:
    cand = [
        t
        for t, rr, ids in invs
        if (ids is None or pid in ids) and (not rerun_only or rr)
    ]
    return max(cand) if cand else None


def _cover_first(invs: list[tuple], pid: str) -> datetime | None:
    for t, _rr, ids in invs:
        if ids is None or pid in ids:
            return t
    return None


def window_suspects(
    meta: dict | None, ids, *, upstream: str = UPSTREAM
) -> set[str]:
    """compile(zh,upstream) 波次晚于 fixloop(同上游) 波次的 id 集 → csb 存疑。

    估计式（run_meta invocation 窗——records 无行级时戳）：
      compile 写时取 **最新覆盖波 ts**（任何覆盖波都可能重写该 id——
        悲观界，偏多判 suspect）；
      fixloop 写时取 max(--rerun 覆盖波 ts, 最早覆盖波 ts)（非 --rerun
        波对 done 格不重写——当前 fix 记录的最晚写入时刻乐观界；
        skip/error 格可被后续非 rerun 波重写是已知近似边，偏保守）。
    meta 缺席/字段不可解 → 空集（不参与判定，行为同旧版）。
    """
    if not isinstance(meta, dict):
        return set()
    cinvs = _meta_invs(meta, "compile", upstream=upstream)
    finvs = _meta_invs(meta, "fixloop", upstream=upstream)
    out = set()
    for pid in ids:
        ct = _cover_max(cinvs, pid)
        if ct is None:
            continue
        cand = [
            x
            for x in (
                _cover_max(finvs, pid, rerun_only=True),
                _cover_first(finvs, pid),
            )
            if x is not None
        ]
        ft = max(cand) if cand else None
        if ft is None or ct > ft:
            out.add(pid)
    return out


# ---------------------------------------------------------------- 冻结窗
def _stat_sig(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _tail_truncated(path: Path, chunk: int = 65536) -> bool:
    """末非空行 json 截尾 → True；缺席/空文件/末行可解 → False。

    append 账的半截写只可能发生在文件尾——读末 64KB 找末个非空行判。
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - chunk))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    for line in reversed(tail.splitlines()):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            return True
        return False
    return False


def _scan_file(
    path: Path, arm: str | None, upstream: str | None, now: datetime
) -> tuple[dict, Counter, dict]:
    """records 文件读 + 冻结窗文件面信号（读前后 stat 双采样 → torn）。"""
    pre = _stat_sig(path)
    recs, stats = scan_records(path, arm, upstream)
    post = _stat_sig(path)
    info = {
        "exists": post is not None,
        "torn": pre != post,
        "tail_truncated": _tail_truncated(path) if post else False,
        "bad_lines": stats.get("bad_lines", 0),
        "age_s": (
            None
            if post is None
            else round(now.timestamp() - post[1] / 1e9, 1)
        ),
        "size": None if post is None else post[0],
    }
    return recs, stats, info


def check_freeze(
    rec_dir: Path,
    files: dict[str, dict],
    meta: dict | None,
    *,
    write_window: float = ACTIVE_WRITE_WINDOW_S,
) -> dict:
    """records 目录冻结态 → freeze 块。

    四路信号：
      in_flight_invocation  run_meta 末 invocation.ts > finished_at——
        在飞波次或被看门狗硬杀（finally 都没跑成）的波次；
      recent_write          records 文件 mtime 落 write-window 内——
        非 stagerun 写径（meta 外的 append 源）也兜住；
      tail_truncated        末非空行 json 截尾——append 半截行；
      torn_read             读前后 (size,mtime_ns) 变——本次读已是混合截面。
    """
    reasons: list[str] = []
    signals: dict = {"run_meta": "absent"}
    if isinstance(meta, dict):
        signals["run_meta"] = "present"
        signals["finished_at"] = meta.get("finished_at")
        flying = []
        for inv in meta.get("invocations") or []:
            if not isinstance(inv, dict):
                continue
            t = _inv_ts(inv)
            if t is not None:
                fin = _norm_dt(benchlib.parse_iso(meta.get("finished_at")))
                if fin is None or t > fin:
                    flying.append(
                        {
                            "stage": inv.get("stage"),
                            "ts": inv.get("ts"),
                            "argv": " ".join(str(x) for x in _inv_argv(inv))[:200],
                        }
                    )
        if flying:
            reasons.append("in_flight_invocation")
        signals["in_flight_invocations"] = flying
    fsum = {}
    for name, fi in files.items():
        if fi.get("torn"):
            reasons.append(f"torn_read:{name}")
        if fi.get("tail_truncated"):
            reasons.append(f"tail_truncated:{name}")
        age = fi.get("age_s")
        if age is not None and age < write_window:
            reasons.append(f"recent_write:{name}")
        fsum[name] = {
            k: fi.get(k)
            for k in ("exists", "age_s", "bad_lines", "tail_truncated", "torn")
        }
    return {
        "status": "partial" if reasons else "frozen",
        "partial": bool(reasons),
        "reasons": sorted(set(reasons)),
        "write_window_s": write_window,
        "signals": signals,
        "files": fsum,
    }


def _gate(pdf: int, total: int) -> dict:
    """90% 门判定 → {"pass": bool, "need": int}（need=距门尚缺格数）。"""
    ok = bool(total) and pdf / total >= GATE
    need = 0 if ok else max(0, math.ceil(total * GATE - pdf - 1e-9))
    return {"pass": ok, "need": need}


def _tally(
    comp: dict[str, dict], fix: dict[str, dict], suspects: set[str] | None = None
) -> dict:
    """逐格合成两口径计数——text/--json 两渲染层共用同一份账。"""
    suspects = suspects or set()
    end = Counter()  # "stage:status" —— 末段胜
    uni = Counter()  # union 终态（plain status）
    uni_src = Counter()  # union 终态由哪段供出
    lift_trans = Counter()  # union>end 的迁移对 "csb->post"
    end_sig = Counter()
    dropped_fix = Counter()
    csb_check = Counter()  # fingerprint / legacy_status / none
    dropped_better = 0  # 被弃 fix 状态反优于 compile——stale 丢救面
    code_dist = Counter()  # "stage@stamp" —— rerun 波混写多版代码的嗅探面
    floor_restored = 0  # fixloop 底板兜回(pdf 文件在盘)
    floor_nopdf = 0  # 兜回但 post 仍判无 pdf——「有文件没 verdict」虚低面
    for pid, c in comp.items():
        f = fix.get(pid)
        code_dist[f"compile@{c.get('code') or '?'}"] += 1
        if f is not None:
            code_dist[f"fixloop@{f.get('code') or '?'}"] += 1
        stage, r, drop = pick_final(c, f, window_suspect=pid in suspects)
        if drop is not None:
            dropped_fix[drop] += 1
            if _RANK.get(str(f.get("status") or ""), -1) > _RANK.get(
                str(c.get("status") or ""), -1
            ):
                dropped_better += 1
        st = r.get("status") or "?"
        end[f"{stage}:{st}"] += 1
        if st != "clean":
            end_sig[r.get("sig") or "?"] += 1
        # 新鲜度校验档位计数：所有过了 COMPILED 闸的 fix 记录都吃过
        # 一次校验——接管与否都记档。桶=实际走到的判据：
        # fingerprint(fp 真值 str) / legacy_status(无 fp 有 csb) /
        # none(两无——pick_final 落 no_csb，旧版误记 legacy_status)。
        if f is not None and c.get("status") in COMPILED:
            fmet = f.get("metrics")
            fmet = fmet if isinstance(fmet, dict) else {}
            fp = fmet.get("compile_fp")
            if isinstance(fp, str) and fp:
                csb_check["fingerprint"] += 1
            elif fmet.get("compile_status_before") is not None:
                csb_check["legacy_status"] += 1
            else:
                csb_check["none"] += 1
        # union 口径：与 end-state 共用同一新鲜度门——陈旧 fix 的
        # 「曾出 pdf」不混入当前态读数（口径差全在聚合方式）。
        cs = str(c.get("status") or "?")
        us, usrc = cs, "compile"
        if stage == "fixloop":
            fs = str(f.get("status") or "?")
            fm = f.get("metrics")
            if isinstance(fm, dict) and fm.get("floor_restored"):
                floor_restored += 1
                if fs not in PDF_STATUS:
                    floor_nopdf += 1
            if _RANK.get(fs, -1) > _RANK.get(cs, -1):
                us, usrc = fs, "fixloop"
            elif _RANK.get(fs, -1) < _RANK.get(cs, -1):
                lift_trans[f"{cs}->{fs}"] += 1
        uni[us] += 1
        uni_src[usrc] += 1

    total = sum(end.values())
    reject = end.get("compile:reject", 0)
    n_norej = total - reject
    end_pdf = sum(v for k, v in end.items() if k.split(":")[1] in PDF_STATUS)
    end_clean = sum(v for k, v in end.items() if k.split(":")[1] == "clean")
    uni_pdf = sum(v for k, v in uni.items() if k in PDF_STATUS)
    uni_clean = uni.get("clean", 0)
    lift_cells = sum(lift_trans.values())
    return {
        "records": comp,
        "total": total,
        "reject": reject,
        "n_norej": n_norej,
        "end": end,
        "end_pdf": end_pdf,
        "end_clean": end_clean,
        "end_sig": end_sig,
        "uni": uni,
        "uni_pdf": uni_pdf,
        "uni_clean": uni_clean,
        "uni_src": uni_src,
        "lift_trans": lift_trans,
        "lift_cells": lift_cells,
        "lift_pdf": uni_pdf - end_pdf,
        "lift_clean": uni_clean - end_clean,
        "dropped_fix": dropped_fix,
        "dropped_better": dropped_better,
        "csb_check": csb_check,
        "window_suspects": len(set(comp) & suspects),
        "code_dist": code_dist,
        "orphan_fix": len(set(fix) - set(comp)),
        "floor_restored": floor_restored,
        "floor_nopdf": floor_nopdf,
    }


def _report(
    t: dict,
    rec_dir: Path,
    *,
    freeze: dict,
    population: dict[str, dict],
    window: dict,
    now: datetime,
    arm: str = ARM,
    upstream: str = UPSTREAM,
) -> dict:
    """tally → --json 机读文档（与文本输出同口径同数）。"""

    def pct(n: int, d: int) -> float | None:
        return round(n / d * 100, 4) if d else None

    total, norej = t["total"], t["n_norej"]
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "records_dir": str(rec_dir),
        "cells": total,
        "gate_threshold": GATE,
        # 口径名实钉——union=阶段并集 best-of(compile∪fixloop)/cell，
        # zh 臂 mock 上游单人口径，非 zh+base 臂并集（M2 门=zh 条件编译）。
        "scope": {
            "arm": arm,
            "upstream": upstream,
            "end_state": "末段胜：新鲜 fixloop 终态接管，否则 compile 终态",
            "union": "best-of(compile,fixloop) per cell by STATUS_RANK",
            "union_not": "zh+base 臂并集——base 是归因基线不入本口径",
        },
        "freeze": freeze,
        "population": population,
        "freshness_window": window,
        "end_state": {
            "pdf": t["end_pdf"],
            "pdf_pct": pct(t["end_pdf"], total),
            "clean": t["end_clean"],
            "clean_pct": pct(t["end_clean"], total),
            "reject": t["reject"],
            "gate": _gate(t["end_pdf"], total),
            "excl_reject": (
                {
                    "n": norej,
                    "pdf_pct": pct(t["end_pdf"], norej),
                    "clean_pct": pct(t["end_clean"], norej),
                }
                if norej
                else None
            ),
            "dist": dict(t["end"].most_common()),
        },
        "union": {
            "pdf": t["uni_pdf"],
            "pdf_pct": pct(t["uni_pdf"], total),
            "clean": t["uni_clean"],
            "clean_pct": pct(t["uni_clean"], total),
            "gate": _gate(t["uni_pdf"], total),
            "excl_reject": (
                {
                    "n": norej,
                    "pdf_pct": pct(t["uni_pdf"], norej),
                    "clean_pct": pct(t["uni_clean"], norej),
                }
                if norej
                else None
            ),
            "dist": dict(t["uni"].most_common()),
            "source": dict(t["uni_src"]),
        },
        "lift": {
            "cells": t["lift_cells"],
            "pdf": t["lift_pdf"],
            "clean": t["lift_clean"],
            "transitions": dict(t["lift_trans"].most_common()),
        },
        "dropped_fix": dict(t["dropped_fix"].most_common()),
        "dropped_fix_better": t["dropped_better"],
        "csb_check": dict(t["csb_check"]),
        "code_stamps": dict(t["code_dist"].most_common()),
        "orphan_fix": t["orphan_fix"],
        "floor_restored": t["floor_restored"],
        "floor_restored_nopdf": t["floor_nopdf"],
        "top_sigs": t["end_sig"].most_common(15),
    }


def _print_text(t: dict, rep: dict) -> None:
    total = t["total"]
    e, u = rep["end_state"], rep["union"]
    print(f"records: {rep['records_dir']}")
    # 口径名实钉——union 是阶段并集非臂并集（scope 块同源文案）
    print(
        f"scope: arm={rep['scope']['arm']} upstream={rep['scope']['upstream']}"
        " · union=best-of(compile∪fixloop)/cell（非 zh+base 臂并集）"
    )
    fz = rep["freeze"]
    if fz["partial"]:
        print(f"freeze: PARTIAL ({'; '.join(fz['reasons'])}) — 读数为在飞截面慎引")
    else:
        print(f"freeze: {fz['status']}")
    if total == 0:
        print("cells=0  (no records)")
        return
    # 首行锚点沿用旧格式(cells=/pdf=/clean=)——end-state 口径；
    # 真 union 口径另起行。status_panel 转 --json 前正则仍可读。
    print(
        f"cells={total}  pdf={e['pdf']} ({e['pdf_pct']:.2f}%)"
        f"  clean={e['clean']} ({e['clean_pct']:.2f}%)   [end-state]"
    )
    print(
        f"union:  pdf={u['pdf']} ({u['pdf_pct']:.2f}%)"
        f"  clean={u['clean']} ({u['clean_pct']:.2f}%)   [best-of]"
    )
    for tag, g in (("end-state-pdf", e["gate"]), ("union-pdf", u["gate"])):
        line = "PASS" if g["pass"] else f"need +{g['need']}"
        print(f"gate {tag} >=90%: {line}")
    if t["n_norej"]:
        ee, ue = e["excl_reject"], u["excl_reject"]
        print(
            f"  excl-reject(n={ee['n']}): pdf {ee['pdf_pct']:.2f}%"
            f"  clean {ee['clean_pct']:.2f}% (end-state)"
            f" · pdf {ue['pdf_pct']:.2f}%  clean {ue['clean_pct']:.2f}% (union)"
        )
    lift = rep["lift"]
    print(
        f"union lift: +{lift['pdf']} pdf +{lift['clean']} clean"
        f" over {lift['cells']} cells (best-of vs end-state)"
    )
    if t["floor_restored"]:
        print(
            f"floor-restored: {t['floor_restored']} 格底板兜回"
            f"（其中 {t['floor_nopdf']} 终态仍无 pdf——文件在盘但判 fail）"
        )
    print("\nend-state:")
    for s, c in t["end"].most_common():
        print(f"  {c:5d}  {s}")
    if t["lift_trans"]:
        print("\nunion-lift:")
        for s, c in t["lift_trans"].most_common():
            print(f"  {c:5d}  {s}")
    if t["dropped_fix"]:
        print("\ndropped fixloop overrides:")
        for s, c in t["dropped_fix"].most_common():
            print(f"  {c:5d}  {s}")
        if t["dropped_better"]:
            print(
                f"  (+{t['dropped_better']} dropped fix had better status"
                " than compile — stale 丢救面)"
            )
    if t["csb_check"]:
        print("\ncsb-check:")
        for s, c in t["csb_check"].most_common():
            print(f"  {c:5d}  {s}")
    fw = rep["freshness_window"]
    if fw["suspect_cells"]:
        print(
            f"freshness-window: {fw['suspect_cells']} 格 compile 波晚于 fixloop 波"
            f"（其中 {t['dropped_fix'].get('window_stale', 0)} 格 legacy 接管按"
            " window_stale 丢——波次互踩闸）"
        )
    if len(t["code_dist"]) > 1 or t["orphan_fix"]:
        print("\ncode-stamps:")
        for s, c in t["code_dist"].most_common(12):
            print(f"  {c:5d}  {s}")
        rest = len(t["code_dist"]) - 12
        if rest > 0:
            print(f"   …    +{rest} more")
        if t["orphan_fix"]:
            print(f"  (+{t['orphan_fix']} orphan fixloop records, no compile cell)")
    print("\ntop non-clean sigs:")
    for s, c in t["end_sig"].most_common(15):
        print(f"  {c:5d}  {s}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0])
    p.add_argument(
        "records_dir", nargs="?", default=str(DEFAULT_DIR), help="records/ 目录"
    )
    p.add_argument("--json", action="store_true", dest="as_json", help="机读输出")
    p.add_argument(
        "--require-frozen",
        action="store_true",
        help="records 冻结窗非 frozen 时拒绝记分（exit 3，只出 freeze 块）",
    )
    p.add_argument(
        "--write-window",
        type=float,
        default=ACTIVE_WRITE_WINDOW_S,
        help="records 文件 mtime 判定在飞写入的秒数窗（默认 120）",
    )
    p.add_argument("--arm", default=ARM, help="compile 记录臂过滤（默认 zh）")
    p.add_argument(
        "--upstream", default=UPSTREAM, help="records upstream 过滤（默认 mock）"
    )
    args = p.parse_args(argv)
    rec_dir = Path(args.records_dir)

    now = datetime.now(UTC)
    comp, comp_st, comp_fi = _scan_file(
        rec_dir / "compile.jsonl", arm=args.arm, upstream=args.upstream, now=now
    )
    fix, fix_st, fix_fi = _scan_file(
        rec_dir / "fixloop.jsonl", arm=None, upstream=args.upstream, now=now
    )
    meta = benchlib.load_run_meta(rec_dir.parent, strict=False, default=None)
    meta_state = (
        "present"
        if isinstance(meta, dict)
        else ("corrupt" if (rec_dir.parent / "run_meta.json").exists() else "absent")
    )
    freeze = check_freeze(
        rec_dir,
        {"compile.jsonl": comp_fi, "fixloop.jsonl": fix_fi},
        meta,
        write_window=args.write_window,
    )
    if args.require_frozen and freeze["partial"]:
        blk = {
            "schema": SCHEMA,
            "records_dir": str(rec_dir),
            "freeze": freeze,
            "error": "records_not_frozen",
        }
        if args.as_json:
            print(json.dumps(blk, ensure_ascii=False, indent=1))
        else:
            print(f"freeze: PARTIAL ({'; '.join(freeze['reasons'])})")
            print("records 在飞/半截嫌疑——--require-frozen 拒绝记分")
        return 3
    suspects = window_suspects(meta, set(comp) & set(fix), upstream=args.upstream)
    t = _tally(comp, fix, suspects)
    window = {
        "run_meta": meta_state,
        "suspect_cells": t["window_suspects"],
        "window_stale_dropped": t["dropped_fix"].get("window_stale", 0),
        "suspect_ids": sorted(suspects)[:64],
        "suspect_ids_total": len(suspects),
    }
    population = {
        "compile": dict(comp_st),
        "fixloop": dict(fix_st),
    }
    rep = _report(
        t,
        rec_dir,
        freeze=freeze,
        population=population,
        window=window,
        now=now,
        arm=args.arm,
        upstream=args.upstream,
    )
    if args.as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        _print_text(t, rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
