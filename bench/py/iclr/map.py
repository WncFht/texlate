#!/usr/bin/env python3
r"""iclr/map.py — ICLR accepted 标题 → arXiv id 批量映射.

三档匹配: (1) OpenReview 缓存自带 arxiv_id 直录；(2) OpenAlex
``works?search=<title>`` top-10 候选 → 归一化标题 exact / fuzzy≥0.87；
(3) OA miss 走 Semantic Scholar ``/paper/search/match`` —— 命中且带
ArXiv externalId 则采用（S2 能把 OpenReview 版与改名后 arXiv 版连上），
否则记 ``no_arxiv``（S2 显示 venue=ICLR 即确认 OpenReview-only）。

输入: bench/work_iclr/accepted.jsonl (openreview 缓存导出)
输出: bench/work_iclr/map.jsonl 每行 {orid,arxiv_id|null,match,oa_title?}
      断点续跑——已写 orid 跳过。map.jsonl 是全量账目（含 cache 直录）。

限速: OA 并发 6 worker（API key 预算自管）；S2 单流 ~1rps。
凭据: OPENALEX_API_KEY 读 paper-search skill .env。

用法: uv run python bench/py/iclr/map.py [--phase oa|s2|all] [--limit N]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# 包内脚本直跑时 bench/py 不在 sys.path——先立起再引 specs/kernel
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from specs import _benchlite as benchlib

REPO = Path(__file__).resolve().parents[3]
WORK = REPO / "bench" / "work_iclr"
ACCEPTED = WORK / "accepted.jsonl"
MAP_OUT = WORK / "map.jsonl"

UA = {"User-Agent": "texlate-iclr-study/1.0 (research; mailto:bench@localhost)"}

# OA 终态：不再进 OA 队列；no_arxiv/s2_nomatch 刻意留作 OA 可重试
# （S2 match 命中 OpenReview 记录时会漏报 arXiv 重复记录——实测回收率
# 仅 ~2%，OA 恢复后须对 no_arxiv/s2_nomatch 二刷补漏）
TERMINAL = {"cache", "oa_exact", "oa_fuzzy", "oa_miss", "s2"}


#: stderr 时间戳日志 / paper-search .env 读取——benchlib 单源（iclr/ 包同源件）。
log = benchlib.log
load_env = benchlib.load_env


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).lower()
    t = re.sub(r"\\[a-zA-Z]+\s*", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def arxiv_of_work(w: dict) -> str | None:
    m = re.match(r"https?://doi\.org/10\.48550/arxiv\.(\S+)", w.get("doi") or "")
    if m:
        return m.group(1)
    for loc in w.get("locations") or []:
        for k in ("landing_page_url", "pdf_url"):
            u = loc.get(k) or ""
            m = re.search(
                r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5}|[a-z-]+/\d{7})", u
            )
            if m:
                return m.group(1)
    return None


def oa_search(client: httpx.Client, title: str, key_box: list) -> dict | None:
    """OpenAlex relevance search → {arxiv_id, match, oa_title} | None.

    key_box[0] 持有 api_key；命中付费预算耗尽 429（Insufficient budget）
    即置 None——本进程余下全部请求转匿名（mailto）通道。
    """
    works = None
    for attempt in range(4):
        params = {"search": title, "per-page": 10, "mailto": "bench@localhost"}
        if key_box[0]:
            params["api_key"] = key_box[0]
        try:
            r = client.get("https://api.openalex.org/works", params=params)
            if r.status_code == 429:
                if key_box[0] and "Insufficient budget" in r.text:
                    key_box[0] = None
                    continue  # 预算耗尽 → 本进程永久切匿名，下轮 attempt 即匿名
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                return {"error": f"oa_http_{r.status_code}"}
            works = r.json().get("results", [])
            break
        except Exception as e:
            if attempt == 3:
                return {"error": f"oa_{type(e).__name__}"}
            time.sleep(3 * (attempt + 1))
    if works is None:
        return {"error": "oa_429"}
    nt = norm(title)
    best_fuzzy = None
    for w in works:
        aid = arxiv_of_work(w)
        if not aid:
            continue
        wt = norm(w.get("title") or "")
        if wt == nt:
            return {"arxiv_id": aid, "match": "oa_exact"}
        if best_fuzzy is None and difflib.SequenceMatcher(None, nt, wt).ratio() > 0.87:
            best_fuzzy = (aid, w.get("title") or "")
    if best_fuzzy:
        return {
            "arxiv_id": best_fuzzy[0],
            "match": "oa_fuzzy",
            "oa_title": best_fuzzy[1],
        }
    return None


def s2_match(client: httpx.Client, title: str) -> dict:
    """S2 search/match → {arxiv_id?, match: s2|no_arxiv|s2_nomatch, s2_venue}."""
    for attempt in range(4):
        try:
            r = client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search/match",
                params={"query": title, "fields": "title,externalIds,venue,year"},
            )
        except Exception as e:
            if attempt == 3:
                return {"error": f"s2_{type(e).__name__}"}
            time.sleep(4 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(6 * (attempt + 1))
            continue
        if r.status_code != 200:
            return {"error": f"s2_http_{r.status_code}"}
        data = r.json().get("data") or []
        if not data:
            return {"match": "s2_nomatch"}
        p = data[0]
        aid = (p.get("externalIds") or {}).get("ArXiv")
        if aid:
            return {"arxiv_id": aid, "match": "s2", "s2_title": p.get("title")}
        return {
            "match": "no_arxiv",
            "s2_venue": p.get("venue") or "",
            "s2_title": p.get("title"),
        }
    return {"error": "s2_429"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["oa", "s2", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    accepted = [json.loads(line) for line in ACCEPTED.open()]
    done: dict[str, dict] = {}
    if MAP_OUT.exists():
        for line in MAP_OUT.open():
            try:
                r = json.loads(line)
                done[r["orid"]] = r
            except json.JSONDecodeError:
                pass

    # cache 直录: 有 arxiv_id 的先落账（幂等）
    with MAP_OUT.open("a") as f:
        n_new = 0
        for rec in accepted:
            if rec["orid"] in done:
                continue
            if rec.get("arxiv_id"):
                row = {
                    "orid": rec["orid"],
                    "arxiv_id": rec["arxiv_id"],
                    "match": "cache",
                }
                f.write(json.dumps(row) + "\n")
                done[rec["orid"]] = row
                n_new += 1
        f.flush()
    if n_new:
        log(f"cache 直录 +{n_new}")

    todo = [
        r
        for r in accepted
        if not (
            (d := done.get(r["orid"]))
            and (d.get("arxiv_id") or d.get("match") in TERMINAL)
        )
    ]
    if a.limit:
        todo = todo[: a.limit]
    log(f"to map: {len(todo)} (done {len(done)}/{len(accepted)})")
    if not todo:
        return
    key = load_env()["OPENALEX_API_KEY"]

    # ---- phase OA: 并发 OpenAlex ----
    oa_miss: list[dict] = []
    if a.phase in ("oa", "all"):
        with httpx.Client(timeout=45, headers=UA) as client:
            key_box = [key]

            def work(rec):
                return rec, oa_search(client, rec["title"], key_box)

            n_ok = n_miss = n_err = 0
            with (
                MAP_OUT.open("a") as f,
                ThreadPoolExecutor(max_workers=a.workers) as ex,
            ):
                futs = {ex.submit(work, r): r for r in todo}
                for i, fut in enumerate(as_completed(futs), 1):
                    rec, res = fut.result()
                    row = {"orid": rec["orid"]}
                    if res is None:
                        row["match"] = "oa_miss"
                        n_miss += 1
                        oa_miss.append(rec)
                    elif "error" in res:
                        row["match"] = res["error"]
                        n_err += 1
                    else:
                        row.update(res)
                        n_ok += 1
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    done[rec["orid"]] = row
                    if i % 200 == 0:
                        f.flush()
                        log(
                            f"  oa [{i}/{len(todo)}] hit={n_ok} miss={n_miss} err={n_err}"
                        )
            log(f"oa done: hit={n_ok} miss={n_miss} err={n_err}")

    # ---- phase S2: 仲裁（单流 ~1rps）----
    # 覆盖: 无 arxiv_id 且非 S2 终态（no_arxiv/s2_nomatch）的行 + 从未尝试的行。
    # OA 全挂时可 --phase s2 直接全量仲裁。
    if a.phase in ("s2", "all"):
        pending = [
            rec
            for rec in accepted
            if not ((row := done.get(rec["orid"])) and row.get("arxiv_id"))
            and (row is None or row.get("match") not in ("no_arxiv", "s2_nomatch"))
        ]
        log(f"s2 仲裁: {len(pending)} 篇")
        n_arxiv = n_noarxiv = n_other = 0
        with httpx.Client(timeout=30, headers=UA) as client, MAP_OUT.open("a") as f:
            for i, rec in enumerate(pending, 1):
                res = s2_match(client, rec["title"])
                row = {
                    "orid": rec["orid"],
                    "arxiv_id": res.get("arxiv_id"),
                    **{k: v for k, v in res.items() if k != "arxiv_id"},
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                done[rec["orid"]] = row
                if res.get("arxiv_id"):
                    n_arxiv += 1
                elif res.get("match") == "no_arxiv":
                    n_noarxiv += 1
                else:
                    n_other += 1
                if i % 100 == 0:
                    f.flush()
                    log(
                        f"  s2 [{i}/{len(pending)}] arxiv={n_arxiv} no_arxiv={n_noarxiv} other={n_other}"
                    )
                time.sleep(1.05)
        log(f"s2 done: arxiv={n_arxiv} no_arxiv={n_noarxiv} other={n_other}")

    n_final = sum(1 for v in done.values() if v.get("arxiv_id"))
    log(f"map 终态: {n_final}/{len(accepted)} 有 arxiv_id")


if __name__ == "__main__":
    main()
