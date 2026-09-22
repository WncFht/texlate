#!/usr/bin/env python3
r"""iclr_pdf.py — 无 arXiv 映射的 ICLR 论文 → OpenReview PDF 兜底下载.

map.jsonl 中无 arxiv_id 的行 → OpenReview /pdf?id={orid}。双代际：
api2.openreview.net 服务 v2 论文（~ICLR 2024+），api.openreview.net
服务 v1 论文（更早）。两站各登各的 Bearer token，按年份路由首试，
404 互兜底。凭据读 paper-search skill .env。

落 bench/corpus_iclr_pdf/{orid}.pdf + fetch_pdf.jsonl 状态账。断点续跑。

用法: uv run python bench/py/iclr_pdf.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from specs import _benchlite as benchlib

REPO = Path(__file__).resolve().parents[2]
WORK = REPO / "bench" / "work_iclr"
PDF_DIR = REPO / "bench" / "corpus_iclr_pdf"
MAP = WORK / "map.jsonl"
STATUS = WORK / "fetch_pdf.jsonl"

UA = {"User-Agent": "texlate-iclr-study/1.0 (research; mailto:bench@localhost)"}
ACCEPTED = WORK / "accepted.jsonl"
API2 = "https://api2.openreview.net"
API1 = "https://api.openreview.net"


#: stderr 时间戳日志 / paper-search .env 读取——benchlib 单源（iclr_* 系同源件）。
log = benchlib.log
load_env = benchlib.load_env
ENV_FP = benchlib.ENV_FP


def login(client: httpx.Client, base: str, env: dict[str, str]) -> str:
    for attempt in range(6):
        r = client.post(
            f"{base}/login",
            json={"id": env["OPENREVIEW_USER"], "password": env["OPENREVIEW_PASS"]},
        )
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()["token"]
    r.raise_for_status()
    return ""  # unreachable


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    year_of = {
        r["orid"]: r.get("year", 0)
        for r in (json.loads(l) for l in ACCEPTED.open())
    }
    todo: dict[str, str] = {}  # orid -> match（map.jsonl 是 append 账：末行胜）
    for l in MAP.open():
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        orid = r.get("orid")
        if not orid:
            continue
        # 末行胜：后到的带 arxiv_id 行要把先到的无映射行从队列里撤掉，
        # 否则同一 orid 先记 no-arxiv 后记 mapped 时 PDF 臂仍照跑。
        if r.get("arxiv_id"):
            todo.pop(orid, None)
        else:
            todo[orid] = r.get("match", "?")
    done: set[str] = set()
    if STATUS.exists():
        for l in STATUS.open():
            try:
                r = json.loads(l)
            except json.JSONDecodeError:
                continue
            if r.get("status") in ("ok", "empty"):
                done.add(r["orid"])
    pending = [o for o in todo if o not in done]
    if a.limit:
        pending = pending[: a.limit]
    log(f"pdf arm: no_arxiv={len(todo)} done={len(done)} todo={len(pending)}")
    if not pending:
        return 0

    env = load_env()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with httpx.Client(timeout=60, headers=UA, follow_redirects=True) as client:
        tokens = {
            API2: login(client, API2, env),
            API1: login(client, API1, env),
        }
        t_reauth = time.monotonic()
        with STATUS.open("a") as out:
            for i, orid in enumerate(pending, 1):
                if time.monotonic() - t_reauth > 3000:  # token 寿命内轮换
                    tokens = {
                        API2: login(client, API2, env),
                        API1: login(client, API1, env),
                    }
                    t_reauth = time.monotonic()
                # v2 时代 ~ICLR 2024+；更早走 v1
                bases = (API2, API1) if year_of.get(orid, 0) >= 2024 else (API1, API2)
                t0 = time.monotonic()
                st = None
                for base in bases:
                    try:
                        r = client.get(
                            f"{base}/pdf",
                            params={"id": orid},
                            headers={"Authorization": f"Bearer {tokens[base]}"},
                        )
                        if r.status_code == 200 and r.content[:5] == b"%PDF-":
                            (PDF_DIR / f"{orid}.pdf").write_bytes(r.content)
                            st = "ok"
                            break
                        if r.status_code == 404:
                            continue  # 跨代际兜底
                        st = "empty" if r.status_code == 200 else f"http_{r.status_code}"
                        break
                    except Exception as e:
                        st = f"err:{type(e).__name__}"
                        break
                if st is None:
                    st = "http_404"  # 两代际都 404
                counts[st] = counts.get(st, 0) + 1
                out.write(json.dumps({
                    "orid": orid, "status": st,
                    "secs": round(time.monotonic() - t0, 1),
                    "ts": datetime.now(UTC).strftime("%m-%dT%H:%M:%S"),
                }) + "\n")
                out.flush()
                if i % 50 == 0 or i == len(pending):
                    log(f"  [{i}/{len(pending)}] {counts}")
                time.sleep(0.6)  # 温和限速——auth 通道无官方口径
    log(f"pdf done: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
