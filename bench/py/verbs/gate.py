"""gate — 出口门记分卡（index 版）。

``bench gate [--run RUN] [--kind K] [--json] [--require-frozen]
             [--write-window S] [--arm zh] [--up UP]``

数据源 = index.records——旧 gate_scorecard.py 的 records/{compile,fixloop}.jsonl
双文件扫换成 records 表直查（字段映射 ``upstream``→``up``；格键走 ``idc``
正形——旧版「按拼写原样计格」注释在新世界 moot，idc 恒 canon）。
pick_final/_tally/_report 逐字保留：fp 新鲜度/陈旧语义是 harvest.clean_ids
的存活逻辑，index 之外无第二实现。

数据源迁移带来的换锚（语义等价改写点）:

- run 解析: ``--run`` 精确名 → 前缀唯一匹配 → stem 展开。import 旧账把一
  个 records 目录拆成 ``*_records_<stage>`` 兄弟 run——stem=去尾部
  ``_<stage>`` 后并组；前缀跨多 stem → 歧义报错 exit 2。无 ``--run`` 取
  kind 过滤下含 compile 账的最新 run_seq run。
- window_suspects: 旧 run_meta argv 波次估计 → records.ts 逐行直判（该格
  compile 末行 ts 晚于 fixloop 末行 ts → suspect）。新 invocations.jsonl
  的 flags 是整 run 级 spec params（无 per-stage argv/--ids 概念），
  records.ts 是更准的直接信号——估计式退役。
- freeze: 硬信号 ``runs.active_runs()``（heartbeat+run.lock）承接旧
  in_flight_invocation 位；recent_write 用 max(records.ts) 与 shard
  events.jsonl mtime 双源；tail_truncated/torn_read 保留在 shard 文件面。
- ``--up`` 缺省 None=全上游（soak 时代 up='-'，mock 口径须 --up mock 显式
  ——stem 组本身已钉住时代，缺省不再滤）。
- ``--arm`` 缺省自适应：账内有 zh 臂 compile 行 → 滤 zh（M2 旧口径，base
  归因基线不入格）；无 zh 臂 → 全臂（soak 单臂管线 arm='-' 是常态）。
  显式 ``--arm X`` 钉死任一臂；``--arm -`` 显式取无臂轴数据。
"""

import hashlib
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from kernel import index as index_mod
from kernel import paths
from kernel import runs as runs_mod

from verbs._common import (
    _all_runs,
    _stem_group,
    _stem_of,  # noqa: F401 — tests/bench_kernel/test_verbs.py 钉 gate._stem_of 私有名
)
from verbs._vocab import COMPILED_STATUS as COMPILED
from verbs._vocab import STATUS_RANK as _RANK

GATE = 0.90
SCHEMA = "gate_scorecard/v3"
ARM = "zh"
ACTIVE_WRITE_WINDOW_S = 120.0
PDF_STATUS = {"clean", "partial"}


# ---------------------------------------------------------------- 记录指纹
# compile_fp/_strkey/parse_iso 逐字录自 benchlib（benchlib 已退役；
# triage 若也要 compile_fp，归并 verbs/_vocab.py 是 leader 侧缺口，勿各自抄）。


def _strkey(d):
    """dict 键一律 str 化——混合类型键下 ``sort_keys`` 排序即 TypeError。"""
    return {str(k): v for k, v in d.items()} if isinstance(d, dict) else d


def compile_fp(c: dict) -> str:
    """compile 记录身份指纹（sha256[:16]）——verdict 决定字段的稳定摘要。

    fixloop 记录新鲜度校验的比对料单源：写侧落 ``metrics.compile_fp``，
    读侧比对——compile 重跑 status 不变但 sig/first_error 已换（同态陈旧）
    时，``compile_status_before`` 状态等值放行、指纹不等即拦。
    计时字段（seconds/dur_s）不入——逐跑恒变而非 verdict 语义。
    """
    m = c.get("metrics")
    if not isinstance(m, dict):
        m = {}
    comp = m.get("compile")
    if not isinstance(comp, dict):
        comp = {}
    v = m.get("verdict")
    if not isinstance(v, dict):
        v = {}
    blob = json.dumps(
        [
            c.get("status"),
            c.get("sig"),
            c.get("code"),
            comp.get("first_error"),
            v.get("category"),
            v.get("payload"),
            _strkey(v.get("error_cats")),
            _strkey(m.get("taxonomy")),
        ],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _parse_iso(s):
    """ISO 串 → datetime；不可解 → None。"""
    try:
        return datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def _norm_dt(dt: datetime | None) -> datetime | None:
    """naive dt 按 UTC 计。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _open_index() -> index_mod.Index:
    return index_mod.open_index()


# ---------------------------------------------------------------- run 解析


def _has_compile(idx, run: str) -> bool:
    return (
        idx.conn.execute(
            "SELECT 1 FROM records WHERE run=? AND stage='compile' LIMIT 1",
            (run,),
        ).fetchone()
        is not None
    )


def _resolve_runs(idx, run_arg: str | None, kind: str | None):
    """→ (runs 行 list, err str|None)。stem 展开并组；跨 stem 即歧义。"""
    rows = _all_runs(idx)
    if kind is not None:
        rows = [r for r in rows if r.get("kind") == kind]
    if run_arg:
        seeds = [r for r in rows if r.get("run") == run_arg]
        if not seeds:
            seeds = [r for r in rows if str(r.get("run")).startswith(run_arg)]
        if not seeds:
            return None, f"run not found: {run_arg!r}"
    else:
        cand = sorted(rows, key=lambda r: r.get("run_seq") or 0, reverse=True)
        seeds = []
        for r in cand:
            if _has_compile(idx, r["run"]):
                seeds = [r]
                break
        if not seeds:
            return None, "no run with compile records"
    return _stem_group(_all_runs(idx), seeds, run_arg)


# ---------------------------------------------------------------- records 读取


def _blob_dir_for(run_row: dict | None) -> Path | None:
    if not run_row:
        return None
    k, d, s = run_row.get("kind"), run_row.get("date"), run_row.get("slug")
    if not all(isinstance(x, str) for x in (k, d, s)):
        return None
    return paths.run_dir(k, d, s) / "derived" / "blobs"


def _unblob(val, blob_dir: Path | None):
    """{"$blob":sha} 卸载标记 → 该 run derived/blobs 下的真值（读侧镜像
    ctx._unblob——records.metrics 存的是标记形）。"""
    if not (isinstance(val, dict) and isinstance(val.get("$blob"), str)):
        return val
    if blob_dir is None:
        return val
    p = blob_dir / f"{val['$blob']}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return val


def _fetch_rows(idx, run_names: list[str]) -> list[dict]:
    """compile+fixloop 全量行（append 序 = run_seq, seq）→ 旧 records 形 dict。"""
    if not run_names:
        return []
    ph = ",".join("?" for _ in run_names)
    cur = idx.conn.execute(
        "SELECT r.run, r.seq, r.id, r.idc, r.arm, r.up, r.variant, r.stage,"  # noqa: S608 — 值全走占位符参数化
        " r.status, r.cat, r.sig, r.code, r.fp, r.dur_s, r.metrics, r.errors,"
        " r.ts, ru.run_seq, ru.kind, ru.date, ru.slug"
        " FROM records r LEFT JOIN runs ru ON ru.run = r.run"
        f" WHERE r.run IN ({ph}) AND r.stage IN ('compile','fixloop')"
        " ORDER BY COALESCE(ru.run_seq, 9223372036854775807), r.seq",
        run_names,
    )
    out = []
    for row in cur.fetchall():
        d = dict(row)
        blob_dir = _blob_dir_for(d)
        for col in ("metrics", "errors"):
            v = d.get(col)
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    v = None
            d[col] = _unblob(v, blob_dir)
        d["upstream"] = d.get("up")  # pick_final 旧字段名映射
        out.append(d)
    return out


def scan_rows(
    rows: list[dict], stage: str, arm: str | None, upstream: str | None
) -> tuple[dict[str, dict], Counter, dict]:
    """records 行 → (idc 末条胜 dict, 行级去向账, 时戳面)。

    账键同旧 scan_records：rows/non_dict/arm_filtered/upstream_filtered/
    arm_mismatch/bad_id/accepted/unique/superseded（bad_lines 由读侧
    metrics/errors 解析失败计入）。返回的 ts_max 供 freeze recent_write。
    """
    stats: Counter = Counter()
    kept = []
    ts_max = None
    for r in rows:
        if r.get("stage") != stage:
            continue
        stats["rows"] += 1
        if arm is not None and r.get("arm") != arm:
            stats["arm_filtered"] += 1
            continue
        # 双臂波次防串同旧口径：up 缺失按 mock 计（史前排无此字段）。
        if upstream is not None and (r.get("up") or "mock") != upstream:
            stats["upstream_filtered"] += 1
            continue
        errs = r.get("errors")
        if not isinstance(errs, list):
            errs = []
        if any(isinstance(e, dict) and e.get("code") == "arm_mismatch" for e in errs):
            stats["arm_mismatch"] += 1
            continue
        rid = r.get("idc") or r.get("id")
        if not isinstance(rid, str) or not rid:
            stats["bad_id"] += 1
            continue
        stats["accepted"] += 1
        kept.append(r)
        t = r.get("ts")
        if isinstance(t, (int, float)) and (ts_max is None or t > ts_max):
            ts_max = t
    # 格键 idc（canon 正形）——append 序末条胜。
    latest = {}
    for r in kept:
        latest[r.get("idc") or r.get("id")] = r
    stats["unique"] = len(latest)
    stats["superseded"] = stats["accepted"] - stats["unique"]
    return latest, stats, {"ts_max": ts_max}


# ---------------------------------------------------------------- pick_final（逐字）


def pick_final(
    c: dict, f: dict | None, *, window_suspect: bool = False
) -> tuple[str, dict, str | None]:
    """合成终态：(stage, record, drop_reason)。

    fix 只在覆盖真编译结果且未过期时生效——``--on all`` 会对
    inject:reject/skip 格也产出 fixloop 记录（编译被拒英文树），
    不能计入。记录内部一致性闸：``metrics.post.status`` 与顶 status
    相悖 = 拼账/腐记录（post_inconsistent）。新鲜度校验：``metrics.compile_fp``
    在场按 compile 记录指纹比对（同态陈旧拦 fp_mismatch；指纹匹配而 csb
    字段相悖 = 拼账记录 csb_contradicts_fp），缺席回退
    ``compile_status_before`` 状态等值（status 同而 log/树已换挡不住——
    弱校验档位由调用侧计数）。legacy 档另加波次窗校验：records.ts 判定
    compile 末行晚于 fixloop 末行时，csb 等值可能是同态重跑巧合
    → window_stale 按陈旧丢。
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


def window_suspects(comp: dict[str, dict], fix: dict[str, dict]) -> set[str]:
    """compile 末行 ts 晚于 fixloop 末行 ts 的 id 集 → csb 存疑。

    旧版靠 run_meta invocation argv 估计覆盖波（records 无行级时戳的
    迂回）；index 版 records.ts 逐行带时戳，直判更准：fix 行写入后该格
    compile 行又写（哪怕同 status 同态重写）→ legacy-csb 等值不再可信。
    ts 缺失的行不参与（保守方向同旧 meta 缺席 → 空集）。
    """
    out = set()
    for pid, c in comp.items():
        f = fix.get(pid)
        if f is None:
            continue
        ct, ft = c.get("ts"), f.get("ts")
        if isinstance(ct, (int, float)) and isinstance(ft, (int, float)) and ct > ft:
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
    """末非空行 json 截尾 → True；缺席/空文件/末行可解 → False。"""
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


def check_freeze(
    run_names: list[str],
    file_info: dict[str, dict],
    stage_info: dict[str, dict],
    active: list[dict],
    now: datetime,
    *,
    write_window: float = ACTIVE_WRITE_WINDOW_S,
) -> dict:
    """冻结态 → freeze 块。

    信号重映射（旧四路 → 新世界）:
      in_flight_run      runs.active_runs()（heartbeat+run.lock 硬信号）
        命中目标 run——在飞或被看门狗硬杀后心跳未陈的波次；
      recent_write       max(records.ts) 落 write-window 内，或 shard
        events.jsonl mtime 落窗内——非 kernel 写径也兜住；
      tail_truncated     shard 末非空行 json 截尾——append 半截行；
      torn_read          读前后 (size,mtime_ns) 变——本次读已混合截面。
    """
    reasons: list[str] = []
    live = {a["run"]: a for a in active}
    flying = [
        {"run": r, "heartbeat_age": round(live[r]["heartbeat_age"], 1)}
        for r in run_names
        if r in live
    ]
    if flying:
        reasons.append("in_flight_run")
    signals: dict = {
        "active_runs": sorted(live),
        "in_flight_runs": flying,
    }
    for stage, si in stage_info.items():
        t = si.get("ts_max")
        if t is not None and now.timestamp() - t < write_window:
            reasons.append(f"recent_write:{stage}")
    fsum = {}
    for name, fi in file_info.items():
        if fi.get("torn"):
            reasons.append(f"torn_read:{name}")
        if fi.get("tail_truncated"):
            reasons.append(f"tail_truncated:{name}")
        age = fi.get("age_s")
        if age is not None and age < write_window:
            reasons.append(f"recent_write:{name}")
        fsum[name] = {
            k: fi.get(k) for k in ("exists", "age_s", "tail_truncated", "torn")
        }
    return {
        "runs": run_names,
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
    run_names: list[str],
    *,
    freeze: dict,
    population: dict[str, dict],
    window: dict,
    now: datetime,
    arm: str = ARM,
    upstream: str | None = None,
) -> dict:
    """tally → --json 机读文档（与文本输出同口径同数）。"""

    def pct(n: int, d: int) -> float | None:
        return round(n / d * 100, 4) if d else None

    total, norej = t["total"], t["n_norej"]
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "run": run_names[-1] if run_names else None,
        "runs": run_names,
        "cells": total,
        "gate_threshold": GATE,
        # 口径名实钉——union=阶段并集 best-of(compile∪fixloop)/cell，
        # arm 过滤单人口径，非 zh+base 臂并集（base 是归因基线不入格）。
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
    print(f"runs: {', '.join(rep['runs'])}")
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
    # 真 union 口径另起行。``ops.status_panel`` 转 --json 前正则仍可读。
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


# ---------------------------------------------------------------- verb 接口


def add_args(sp) -> None:
    sp.add_argument(
        "--run",
        default=None,
        help="目标 run：精确名 / 唯一前缀 / stem（import 旧账的"
        " *_records_<stage> 兄弟组自动并组）；缺省取含 compile 账的"
        "最新 run_seq run",
    )
    sp.add_argument("--kind", default=None, help="run 解析时的 kind 过滤")
    sp.add_argument("--json", action="store_true", dest="as_json", help="机读输出")
    sp.add_argument(
        "--require-frozen",
        action="store_true",
        help="账面在飞/半截嫌疑时拒绝记分（exit 3，只出 freeze 块）",
    )
    sp.add_argument(
        "--write-window",
        type=float,
        default=ACTIVE_WRITE_WINDOW_S,
        help="records.ts/shard mtime 判定在飞写入的秒数窗（默认 120）",
    )
    sp.add_argument(
        "--arm",
        default=None,
        help="compile 记录臂过滤（缺省自适应：有 zh 臂滤 zh——M2 旧口径；"
        "无 zh 臂全臂——soak 单臂管线 arm='-'）",
    )
    sp.add_argument(
        "--up",
        default=None,
        help="records up 过滤（缺省全上游；mock 口径显式 --up mock）",
    )


def main(args) -> int:
    idx = _open_index()
    group, err = _resolve_runs(idx, args.run, args.kind)
    if err is not None:
        print(f"gate: {err}", file=sys.stderr)
        return 2
    run_names = [str(r["run"]) for r in group]

    now = datetime.now(UTC)
    # shard 文件面双采样：SQL 读前后 stat 比对 → torn。
    shard_paths = {}
    for r in group:
        k, d, s = r.get("kind"), r.get("date"), r.get("slug")
        if all(isinstance(x, str) for x in (k, d, s)):
            shard_paths[str(r["run"])] = paths.run_dir(k, d, s) / "events.jsonl"
    pre_sig = {n: _stat_sig(p) for n, p in shard_paths.items()}

    rows = _fetch_rows(idx, run_names)
    # 臂轴自适应：--arm 显式 > zh 在场滤 zh（M2 旧口径——base 归因基线
    # 不入格）> 全臂（soak 单臂管线 arm='-'）。
    arm = args.arm
    if arm is None:
        arm = (
            ARM
            if any(r.get("stage") == "compile" and r.get("arm") == ARM for r in rows)
            else None
        )
    comp, comp_st, comp_si = scan_rows(rows, "compile", arm=arm, upstream=args.up)
    fix, fix_st, fix_si = scan_rows(rows, "fixloop", arm=None, upstream=args.up)

    post_sig = {n: _stat_sig(p) for n, p in shard_paths.items()}
    file_info = {}
    for n, p in shard_paths.items():
        post = post_sig[n]
        file_info[n] = {
            "exists": post is not None,
            "torn": pre_sig[n] != post,
            "tail_truncated": _tail_truncated(p) if post else False,
            "age_s": (
                None if post is None else round(now.timestamp() - post[1] / 1e9, 1)
            ),
            "size": None if post is None else post[0],
        }
    freeze = check_freeze(
        run_names,
        file_info,
        {"compile": comp_si, "fixloop": fix_si},
        runs_mod.active_runs(),
        now,
        write_window=args.write_window,
    )
    if args.require_frozen and freeze["partial"]:
        blk = {
            "schema": SCHEMA,
            "run": run_names[-1] if run_names else None,
            "runs": run_names,
            "freeze": freeze,
            "error": "records_not_frozen",
        }
        if args.as_json:
            print(json.dumps(blk, ensure_ascii=False, indent=1))
        else:
            print(f"freeze: PARTIAL ({'; '.join(freeze['reasons'])})")
            print("records 在飞/半截嫌疑——--require-frozen 拒绝记分")
        return 3
    suspects = window_suspects(comp, fix)
    t = _tally(comp, fix, suspects)
    window = {
        "basis": "records.ts",
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
        run_names,
        freeze=freeze,
        population=population,
        window=window,
        now=now,
        arm=arm or "all",
        upstream=args.up,
    )
    if args.as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        _print_text(t, rep)
    return 0
