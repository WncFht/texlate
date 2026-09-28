#!/usr/bin/env python3
"""对照臂驱动：逐篇 POST ``/api/arxiv/{id}/translate``，轮询快照到终态，落窗口 JSON。

串行「提交→等终态→下一篇」是窗不重叠的构造保证——下游 arm_usage 按
ms 窗切网关 logs 全靠它。产物 ``--out``（默认 ``tmp/arm-wins.json``）形
``{paper: {task_id,status,t0,t1,secs,t0_hms,t1_hms}}``；``t*_hms`` 是
+0800 当日面。提交失败行 ``{status,t0,t1}``、超时行缺 ``secs`` 属契约
内形（消费方按字段缺席判读）。终态集 =
``texlate.server.store.TERMINAL_STATUSES`` ∪ 防御别名
failed/error/canceled（interrupted/needs_auth 也在真终态内——任务死在
这两态不再空等到 ``--timeout``）。``--papers`` 不预校验——normalize/
拒收是 server 400 面，提交失败按 SUBMIT-FAIL 记窗。

用法::

    .venv/bin/python tools/arm_driver.py --papers 2609.19330v1,2609.19844v1
    .venv/bin/python tools/arm_driver.py --papers @papers.txt --prefer fresh --out tmp/arm-wins.json
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import _env  # noqa: F401 -- src 登程须先于 texlate import
from _arm_lib import hms
from texlate.server.store import TERMINAL_STATUSES
from texlate.textutil import DEFAULT_BIND_PORT

TERMINAL = TERMINAL_STATUSES | {"failed", "error", "canceled"}


def _papers_arg(raw: str) -> list[str]:
    """``--papers``：逗号列，或 ``@file``（空白分列、跳空行与 ``#`` 注释行）。"""
    if raw.startswith("@"):
        out: list[str] = []
        for line in Path(raw[1:]).read_text().splitlines():
            out.extend(line.split("#", 1)[0].split())
        return out
    return [p.strip() for p in raw.split(",") if p.strip()]


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.load(urllib.request.urlopen(req, timeout=60))


def _get(url: str) -> dict:
    return json.load(urllib.request.urlopen(url, timeout=30))


def _drive_paper(base: str, pid: str, body: dict, poll: float, timeout: float) -> dict:
    """单篇：POST → 轮询终态 → 窗记录；t0 在 POST 前取（覆盖提交时延）。"""
    t0 = time.time()
    try:
        r = _post(f"{base}/api/arxiv/{pid}/translate", body)
    except Exception as e:  # noqa: BLE001 -- 提交失败也要记窗继续下一篇
        print(f"{pid} SUBMIT-FAIL {e}", flush=True)
        return {"status": f"submit_fail:{e}", "t0": t0, "t1": time.time()}
    tid = r.get("task_id")
    print(f"{hms(t0)} {pid} -> {tid} ({r.get('status')})", flush=True)
    status, msg = "?", ""
    while True:
        time.sleep(poll)
        try:
            s = _get(f"{base}/api/task/{tid}")
            status = s.get("status", "?")
            msg = s.get("message") or s.get("stage") or ""
        except Exception as e:  # noqa: BLE001 -- 轮询抖动不终态，撞 timeout 才收
            status, msg = "poll_fail", str(e)
        if status in TERMINAL:
            t1 = time.time()
            print(f"{hms(t1)} {pid} {status} {t1 - t0:.0f}s", flush=True)
            return {
                "task_id": tid,
                "status": status,
                "t0": t0,
                "t1": t1,
                "secs": round(t1 - t0),
                "t0_hms": hms(t0),
                "t1_hms": hms(t1),
            }
        if time.time() - t0 > timeout:
            t1 = time.time()
            print(f"{hms(t1)} {pid} TIMEOUT last={status} {msg}", flush=True)
            return {
                "task_id": tid,
                "status": f"timeout:{status}",
                "t0": t0,
                "t1": t1,
                "t0_hms": hms(t0),
                "t1_hms": hms(t1),
            }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--base",
        default=f"http://127.0.0.1:{DEFAULT_BIND_PORT}",
        help="server base URL",
    )
    ap.add_argument(
        "--papers", required=True, help="逗号列 id（可带 vN），或 @file 空白分列"
    )
    ap.add_argument("--prefer", choices=("reuse", "fresh"), default="fresh")
    ap.add_argument("--poll", type=float, default=15, help="轮询间隔秒")
    ap.add_argument("--timeout", type=float, default=3600, help="单篇墙钟上限秒")
    ap.add_argument("--out", type=Path, default=Path("tmp/arm-wins.json"))
    ap.add_argument("--model", default=None, help="body 顶层 model（缺省不发）")
    ap.add_argument(
        "--target-lang", default=None, help="body 顶层 target_lang（缺省不发）"
    )
    ap.add_argument(
        "--source", choices=("eprint", "html"), default=None, help="options.source"
    )
    args = ap.parse_args()

    options: dict = {"prefer": args.prefer}
    if args.source:
        options["source"] = args.source
    body: dict = {"options": options}
    if args.model:
        body["model"] = args.model
    if args.target_lang:
        body["target_lang"] = args.target_lang

    wins: dict[str, dict] = {}
    try:
        for pid in _papers_arg(args.papers):
            wins[pid] = _drive_paper(args.base, pid, body, args.poll, args.timeout)
    finally:
        # Ctrl-C/挂死也落已收窗——一串跑 1h+ 的成果不能随中断全丢
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(wins, f, indent=1)
        print("wrote", args.out, flush=True)


if __name__ == "__main__":
    main()
