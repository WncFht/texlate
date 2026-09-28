#!/usr/bin/env python3
"""逐臂逐篇网关账本对账（本件取代 arms_tokens.py——其在飞处置由别 lane 裁决；本件自包含不 import 它）。

口径：devin-2api.db ``logs.time`` 是毫秒 epoch，窗切按 api+key_hash+ms
三元隔离（``logs`` 无任务 id，同 key 面窗口不复用是铁律）；``task_usage``
是 server 权威总额，``window_balanced``=窗Σ(input+cache_read)==tu_prompt
且 calls==tu_calls 才算干净窗。``--key`` 缺省不过滤——同 key 面/共享
key 时窗会吃进别家调用，``--wins`` 场景建议恒带。

输入二选一：

- ``--arms`` 多臂 JSON ``{arm: {api, key_hash|null, wins: [[paper,hms0,hms1]]}}``
  （纯 hms 窗，须 ``--date``）；
- ``--wins`` 单臂窗 JSON（arm_driver 产物：epoch ``t0``/``t1`` 优先，缺时
  ``t*_hms``+``--date``，跨零点 ``t1<t0`` 自动 +86400s）。

用法::

    .venv/bin/python tools/arm_usage.py --wins tmp/arm-wins.json --key <hash> --date 2026-09-28
    .venv/bin/python tools/arm_usage.py --arms arms.json --date 2026-09-28
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics as st
from datetime import date
from pathlib import Path

import _env
from _arm_lib import DAY_MS, hms_ms
from texlate.arxiv.fetch import normalize_arxiv_id
from texlate.textutil import PH_RX

GW_DB = Path.home() / ".local/state/devin-2api/devin-2api.db"


def _load_arms(path: Path) -> dict:
    """``--arms`` 形 → 同构行集：``{arm: {api,key_hash,rows}}``。"""
    arms = {}
    for name, spec in json.loads(path.read_text()).items():
        rows = [
            {
                "paper": paper,
                "t0_hms": t0,
                "t1_hms": t1,
                "passthrough": {"t0": t0, "t1": t1},
            }
            for paper, t0, t1 in spec["wins"]
        ]
        arms[name] = {
            "api": spec["api"],
            "key_hash": spec.get("key_hash"),
            "rows": rows,
        }
    return arms


def _load_wins(path: Path, name: str, api: str, key_hash: str | None) -> dict:
    """``--wins`` 形（arm_driver 产物）→ 同构行集。"""
    rows = []
    for paper, w in json.loads(path.read_text()).items():
        passthrough = {
            "task_id": w.get("task_id"),
            "status": w.get("status"),
            "secs": w.get("secs"),
        }
        for k in ("t0_hms", "t1_hms"):
            if w.get(k):
                passthrough[k] = w[k]
        rows.append(
            {
                "paper": paper,
                "task_id": w.get("task_id"),
                "t0": w.get("t0"),
                "t1": w.get("t1"),
                "t0_hms": w.get("t0_hms"),
                "t1_hms": w.get("t1_hms"),
                "passthrough": passthrough,
            }
        )
    return {name: {"api": api, "key_hash": key_hash, "rows": rows}}


def _resolve_ms(row: dict, day: date | None) -> tuple[int, int] | None:
    """epoch 优先 → hms+``day`` 兜底 → 跨零点 ``t1<t0`` 加 ``DAY_MS``。"""
    if row.get("t0") is not None and row.get("t1") is not None:
        t0_ms, t1_ms = int(row["t0"] * 1000), int(row["t1"] * 1000)
    elif row.get("t0_hms") and row.get("t1_hms") and day is not None:
        t0_ms = hms_ms(row["t0_hms"], day)
        t1_ms = hms_ms(row["t1_hms"], day)
    else:
        return None
    if t1_ms < t0_ms:
        t1_ms += DAY_MS
    return t0_ms, t1_ms


def _window_metrics(
    gw: sqlite3.Connection, api: str, key_hash: str | None, t0_ms: int, t1_ms: int
) -> dict:
    """窗内 logs 行 → calls/in/cr/out + in_p50/in_max/cr_max/hit_calls。"""
    cond = "api=? and time>=? and time<=?"
    args: tuple = (api, t0_ms, t1_ms)
    if key_hash is not None:
        cond = "api=? and key_hash=? and time>=? and time<=?"
        args = (api, key_hash, t0_ms, t1_ms)
    rows = gw.execute(
        f"select input_tokens, cache_read_tokens, output_tokens from logs where {cond}",
        args,
    ).fetchall()
    ins = [r[0] for r in rows]
    crs = [r[1] for r in rows]
    return {
        "calls": len(rows),
        "input": sum(ins),
        "cache_read": sum(crs),
        "output": sum(r[2] for r in rows),
        "in_p50": int(st.median(ins)) if ins else 0,
        "in_max": max(ins) if ins else 0,
        "cr_max": max(crs) if crs else 0,
        "hit_calls": sum(1 for c in crs if c > 0),
    }


def _enrich_tx(tx: sqlite3.Connection, tid: str, rec: dict) -> None:
    """task_usage 权威总额 + window_balanced + chunks/doc_ph（tid 在场才调）。"""
    tu = tx.execute(
        "select calls, prompt_tokens, completion_tokens, latency_s"
        " from task_usage where task_id=?",
        (tid,),
    ).fetchone()
    if tu:
        rec.update(
            tu_calls=tu[0],
            tu_prompt=tu[1],
            tu_completion=tu[2],
            tu_latency_s=round(tu[3], 1),
        )
        rec["window_balanced"] = (
            rec["input"] + rec["cache_read"] == tu[1] and rec["calls"] == tu[0]
        )
    ch = tx.execute(
        "select count(*),"
        " sum(case when translation is not null then 1 else 0 end)"
        " from chunks where task_id=?",
        (tid,),
    ).fetchone()
    ids = set()
    for (s,) in tx.execute("select src_text from chunks where task_id=?", (tid,)):
        if s:
            ids |= set(PH_RX.findall(s))
    rec.update(chunks=ch[0], translated=ch[1] or 0, doc_ph=len(ids))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--arms", type=Path, help="多臂 JSON（hms 窗，须 --date）")
    src.add_argument("--wins", type=Path, help="单臂窗 JSON（arm_driver 产物）")
    ap.add_argument("--name", default="run", help="--wins 臂名")
    ap.add_argument("--api", default="openai-chat", help="--wins 网关 api 名")
    ap.add_argument("--key", default=None, help="key_hash；缺省不加 key 过滤")
    ap.add_argument("--date", default=None, help="hms 窗锚定日 YYYY-MM-DD（+0800）")
    ap.add_argument("--gw-db", type=Path, default=GW_DB)
    ap.add_argument("--tx-db", type=Path, default=_env.DB)
    ap.add_argument("--out", type=Path, default=Path("tmp/arm-usage.json"))
    args = ap.parse_args()

    day: date | None = None
    if args.date:
        try:
            day = date.fromisoformat(args.date)
        except ValueError:
            ap.error("--date 须 YYYY-MM-DD 形")
    if args.arms:
        if day is None:
            ap.error("--arms 是纯 hms 窗输入，须 --date YYYY-MM-DD 锚日")
        arms = _load_arms(args.arms)
    else:
        arms = _load_wins(args.wins, args.name, args.api, args.key)
        need_day = any(
            (r.get("t0") is None or r.get("t1") is None) and r.get("t0_hms")
            for r in arms[args.name]["rows"]
        )
        if day is None and need_day:
            ap.error("wins 内有无 epoch 的 hms 窗，须 --date YYYY-MM-DD 锚日")

    gw = sqlite3.connect(f"file:{args.gw_db}?mode=ro", uri=True)
    tx = sqlite3.connect(f"file:{args.tx_db}?mode=ro", uri=True)

    result: dict[str, dict] = {}
    for name, spec in arms.items():
        arm_out: dict[str, dict] = {}
        for row in spec["rows"]:
            pid = normalize_arxiv_id(row["paper"])[0]
            rec = dict(row["passthrough"])
            win = _resolve_ms(row, day)
            if win is not None:
                rec.update(_window_metrics(gw, spec["api"], spec["key_hash"], *win))
                if row.get("task_id"):
                    _enrich_tx(tx, row["task_id"], rec)
            arm_out[pid] = rec
            print(pid, json.dumps(rec, ensure_ascii=False))
        arm_out["_total"] = {
            k: sum(v[k] for v in arm_out.values() if k in v)
            for k in ("calls", "input", "cache_read", "output")
        }
        result[name] = arm_out
        print(name, arm_out["_total"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
