#!/usr/bin/env python3
"""双臂 token 对账：按任务时间窗切 devin-2api 网关账本，输出逐臂逐篇 JSON。

基线口径（research/methods/agent-pipeline-baseline-2026-09-28）：texlate 臂
``api=openai-chat`` 按 server ``task_usage`` 键 + 提交/终态窗切；agent 臂
``api=openai-responses`` 按 codex `_status.log` START→次 START 窗切。
两臂同 key 面时窗口不复用——网关 ``logs`` 行无任务 id，隔离全靠 api+key+ 时间窗。

用法::

    .venv/bin/python tools/arms_tokens.py [--arms arms.json] [--out tmp/arms-tokens.json]

``--arms`` 缺省用内嵌 2026-09-28 基线窗口；自定义给
``{"texlate": {"api": "...", "key_hash": "...", "wins": [[paper,start,end],...]},
  "agent":   {"api": "...", "key_hash": null,  "wins": [...]}}``——
``key_hash`` 为 null 即不加 key 过滤；时间是当日 ``%H:%M:%S``（+0800）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path

GW_DB = Path.home() / ".local/state/devin-2api/devin-2api.db"
DAY = dt.date(2026, 9, 28)

BASELINE_ARMS = {
    "texlate": {
        "api": "openai-chat",
        "key_hash": "1edae45350064eb9",
        "wins": [
            ["2609.19330", "17:14:44", "17:17:04"],
            ["2609.19844", "17:17:04", "17:21:05"],
            ["2609.20533", "17:21:05", "17:25:05"],
            ["2609.19506", "17:25:05", "17:35:05"],
            ["2609.20610", "17:35:05", "17:36:46"],
            ["2609.19929", "17:36:46", "17:39:46"],
            ["2609.20739", "17:39:46", "17:45:26"],
            ["2609.20523", "17:45:26", "17:59:07"],
            ["2609.19990", "17:59:07", "18:01:47"],
            ["2609.20581", "18:01:47", "18:21:28"],
        ],
    },
    "agent": {
        "api": "openai-responses",
        "key_hash": None,
        "wins": [
            ["2609.19330", "17:13:13", "17:16:18"],
            ["2609.19844", "17:16:18", "17:21:16"],
            ["2609.20533", "17:21:16", "17:34:37"],
            ["2609.19506", "17:34:37", "18:01:30"],
            ["2609.19929", "18:01:30", "18:48:18"],
            ["2609.20739", "18:48:18", "18:54:30"],
            ["2609.20523", "18:54:30", "19:08:53"],
            ["2609.19990", "19:08:53", "19:22:24"],
            ["2609.20581", "19:22:24", "19:35:21"],
            ["2609.20610", "16:30:00", "17:11:00"],
        ],
    },
}


def _ms(hms: str, day: dt.date = DAY) -> int:
    """当日 ``%H:%M:%S``（+0800）→ epoch ms。"""
    h, m, s = map(int, hms.split(":"))
    local = dt.datetime(
        day.year,
        day.month,
        day.day,
        h,
        m,
        s,
        tzinfo=dt.timezone(dt.timedelta(hours=8)),
    )
    return int(local.timestamp() * 1000)


def _window_sums(
    db: sqlite3.Connection, api: str, key_hash: str | None, t0: str, t1: str
) -> dict[str, int]:
    sql = (
        "select count(*), coalesce(sum(input_tokens),0),"
        " coalesce(sum(cache_read_tokens),0), coalesce(sum(output_tokens),0)"
        " from logs where api=? and time between ? and ?"
    )
    args: tuple = (api, _ms(t0), _ms(t1))
    if key_hash is not None:
        sql = sql.replace("and time", "and key_hash=? and time")
        args = (api, key_hash, _ms(t0), _ms(t1))
    calls, inp, cr, out = db.execute(sql, args).fetchone()
    return {"calls": calls, "input": inp, "cache_read": cr, "output": out}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arms", type=Path, help="臂定义 JSON（缺省内嵌基线）")
    ap.add_argument("--out", type=Path, default=Path("tmp/arms-tokens.json"))
    ap.add_argument("--db", type=Path, default=GW_DB)
    args = ap.parse_args()

    arms = json.loads(args.arms.read_text()) if args.arms else BASELINE_ARMS
    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    result: dict[str, dict[str, dict[str, int]]] = {}
    for arm, spec in arms.items():
        result[arm] = {}
        for paper, t0, t1 in spec["wins"]:
            row = _window_sums(db, spec["api"], spec.get("key_hash"), t0, t1)
            row.update({"t0": t0, "t1": t1})
            result[arm][paper] = row
        total = {
            k: sum(v[k] for v in result[arm].values())
            for k in ("calls", "input", "cache_read", "output")
        }
        result[arm]["_total"] = total
        print(arm, total)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
