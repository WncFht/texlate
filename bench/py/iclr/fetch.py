#!/usr/bin/env python3
r"""iclr/fetch.py — ICLR 映射表 → arXiv e-print 批量取源 → bench/corpus 物化.

镜像 daily_arxiv.py fetch 模式：acquire_source 钉版 HEAD+GET+unpack，
corpus/{id}/{meta.json,raw.*,extracted/} 布局同 daily 层（合并根）。
串行 3.05s 单连接纪律不变（日更 soak 同口径），RatePolicy 预算独立账。

输入: bench/work_iclr/map.jsonl（match!=no_arxiv 且 arxiv_id 非空行）
输出: bench/corpus/{id}/ + bench/work_iclr/fetch.jsonl 状态账（终态跳过重入）

用法: setsid nohup uv run python bench/py/iclr/fetch.py \
      > bench/work_iclr/fetch.log 2>&1 &   # 脱管批
      uv run python bench/py/iclr/fetch.py --limit 30   # 试跑
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# 包内脚本直跑时 bench/py 不在 sys.path——先立起再引 specs/kernel
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib

from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import (
    ARXIV_HOST,
    EXPORT_HOST,
    AcquireStatus,
    Fetcher,
    acquire_source,
)
from texlate.arxiv.ratelimit import RateLimiter, RatePolicy

FETCH_HOSTS = (EXPORT_HOST, ARXIV_HOST)
WORK = ROOT / "bench" / "work_iclr"
CORPUS = ROOT / "bench" / "corpus"
MAP = WORK / "map.jsonl"
STATUS = WORK / "fetch.jsonl"
CACHE = Path.home() / ".cache" / "texlate" / "src"
RATE_STATE = WORK / "ratelimit.json"
UA = {
    "User-Agent": "texlate-iclr-corpus/1.0 (research benchmark; mailto:bench@localhost)"
}
DAILY_BUDGET = 20000  # 独立预算账——与 daily soak 的 ratelimit.json 不共享

#: stderr 时间戳日志 / RSS 探针 / 终态账 / os.link 物化——benchlib 单源
#:（daily_arxiv 同源件；log 本名别名保行文不变）。
log = benchlib.log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--budget", type=int, default=DAILY_BUDGET)
    a = ap.parse_args()

    rows = {}
    for line in MAP.open():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("arxiv_id"):
            rows[r["orid"]] = r["arxiv_id"]
    todo_ids = sorted(set(rows.values()))
    done = benchlib.fetch_done(STATUS, id_key="arxiv_id")
    todo = [pid for pid in todo_ids if pid not in done]
    if a.limit:
        todo = todo[: a.limit]
    log(f"fetch: mapped={len(todo_ids)} done={len(done)} todo={len(todo)}")
    if not todo:
        return 0
    benchlib.rss_preflight(UA)
    CORPUS.mkdir(parents=True, exist_ok=True)
    cache = SourceCache(CACHE)
    limiter = RateLimiter(RATE_STATE, policy=RatePolicy(daily_budget=a.budget))
    counts: dict[str, int] = {}
    with STATUS.open("a") as out, Fetcher(limiter=limiter, hosts=FETCH_HOSTS) as fx:
        for i, pid in enumerate(todo, 1):
            t0 = time.monotonic()
            try:
                res = acquire_source(pid, fetcher=fx, cache=cache)
                res_status, detail, entry = (
                    res.status.value,
                    res.detail,
                    res.entry,
                )
            except Exception as e:
                res_status, detail, entry = "error", f"raise:{e}", None
            rec = {
                "arxiv_id": pid,
                "status": res_status,
                "detail": (detail or "")[:200],
                "secs": round(time.monotonic() - t0, 1),
                "ts": datetime.now(UTC).strftime("%m-%dT%H:%M:%S"),
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            counts[res_status] = counts.get(res_status, 0) + 1
            if res_status == AcquireStatus.OK.value and entry is not None:
                try:
                    benchlib.materialize_entry(entry.dir, CORPUS / pid)
                except OSError as e:
                    log(f"  {pid} materialize failed: {e}")
            if i % 25 == 0 or i == len(todo):
                log(f"  [{i}/{len(todo)}] {counts}")
    log(f"fetch done: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
