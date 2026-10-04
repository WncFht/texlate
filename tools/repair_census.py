r"""修复普查——台账 events 驱动：收 never-passed 修复池的标记聚类。

对 manifest∩canon 下每个 stage（compile/fixloop/xlat/parse）取「触过真臂但
从未 done」的 idc，找其最新终态 cell event，抽 sig + errors.cat/code +
metrics 首错行，归一成标记簇 → tmp/repair-census.json + 打印簇表。

用法: .venv/bin/python tools/repair_census.py [--out tmp/repair-census.json] [--stage compile,fixloop]
"""

import argparse
import contextlib
import glob
import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

LEDGER = os.path.expanduser("~/.local/share/texlate-bench/ledger/index.sqlite")
REAL_ARMS = ("-", "real", "base", "zh", "fix")
DONE = {"ok", "clean", "partial", "dedup"}
FAILST = {"fail", "error", "reject", "fault"}


def canon(i: str) -> str:
    return i.replace("/", "--")


def manifest() -> set[str]:
    man = set()
    for f in glob.glob("bench/corpus/manifest*.jsonl") + [
        "bench/corpus/booster_selection.jsonl"
    ]:
        for raw in open(f):
            line = raw.strip()
            if line:
                with contextlib.suppress(Exception):
                    man.add(canon(json.loads(line)["id"]))
    return man


_PATH_RX = re.compile(r"/[^\s:]*/")
_NUM_RX = re.compile(r"\d+")
_CS_RX = re.compile(r"\\[a-zA-Z@]+")


def norm_errline(s: str | None) -> str:
    if not s:
        return ""
    s = _PATH_RX.sub("<path>", s)
    s = _CS_RX.sub("<cs>", s)
    s = _NUM_RX.sub("<n>", s)
    return s.strip()[:160]


def cohorts(db: sqlite3.Connection, man: set[str]):
    """stage → {idc: (latest_status, run)} 触过真臂从未 done 的 idc。"""
    latest = {}
    for idc, arm, status, run, rid, stage in db.execute(
        "select idc,arm,status,run,rowid,stage from records"
    ):
        c = canon(idc)
        if c not in man or arm not in REAL_ARMS:
            continue
        k = (c, stage, arm)
        if k not in latest or rid > latest[k][0]:
            latest[k] = (rid, status, run)
    by = defaultdict(list)
    for (c, stage, _arm), (rid, st, run) in latest.items():
        by[(c, stage)].append((rid, st, run))
    out = {}
    for (c, stage), v in by.items():
        if any(st in DONE for _, st, _ in v):
            continue
        rid, st, run = max(v)
        out.setdefault(stage, {})[c] = (st, run)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tmp/repair-census.json")
    ap.add_argument("--stage", default="compile,fixloop,xlat,parse")
    args = ap.parse_args()
    stages = args.stage.split(",")
    man = manifest()
    db = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True)
    co = cohorts(db, man)

    # index cell events: (idc,stage,run) → payload
    evmap = {}
    for (payload,) in db.execute("select payload from events where type='cell'"):
        p = json.loads(payload)
        k = (canon(p.get("idc") or p.get("id", "")), p.get("stage"), p.get("run"))
        if p.get("status") in FAILST or True:
            prev = evmap.get(k)
            if prev is None or p.get("seq", 0) >= prev.get("seq", 0):
                evmap[k] = p

    report = {}
    for stage in stages:
        rows = co.get(stage, {})
        clusters = defaultdict(list)
        for idc, (st, run) in rows.items():
            ev = evmap.get((idc, stage, run)) or {}
            errs = ev.get("errors") or []
            code = errs[0].get("code") if errs else None
            cat = errs[0].get("cat") if errs else None
            m = ev.get("metrics") or {}
            fe = ""
            if isinstance(m, dict):
                fe = (m.get("post") or {}).get("compile", {}).get("first_error") or ""
                if not fe:
                    fe = str(m.get("fixloop_verdict") or m.get("final_cat") or "")
            sig = ev.get("sig") or code or norm_errline(fe) or st
            key = f"{sig}|{cat or '-'}|{norm_errline(fe)[:80]}"
            clusters[key].append(
                {
                    "idc": idc,
                    "status": st,
                    "run": run,
                    "sig": sig,
                    "cat": cat,
                    "code": code,
                    "first_error": (fe or "")[:300],
                    "verdict": (
                        m.get("fixloop_verdict") if isinstance(m, dict) else ""
                    ),
                }
            )
        clist = [
            {"key": k, "n": len(v), "examples": sorted(v, key=lambda x: x["idc"])[:6]}
            for k, v in sorted(clusters.items(), key=lambda kv: -len(kv[1]))
        ]
        for c in clist:
            if c["key"].startswith("declined:"):
                c["policy_skip"] = True
        policy_skipped = sum(c["n"] for c in clist if c.get("policy_skip"))
        report[stage] = {
            "needfix_raw": len(rows),
            "policy_skipped": policy_skipped,
            "needfix": len(rows) - policy_skipped,
            "clusters": clist,
        }
        print(
            f"\n=== {stage} needfix={report[stage]['needfix']} "
            f"(raw={report[stage]['needfix_raw']} declined={policy_skipped}) "
            f"clusters={len(report[stage]['clusters'])}"
        )
        for c in report[stage]["clusters"][:25]:
            tag = " [skip]" if c.get("policy_skip") else ""
            print(f"  {c['n']:4}{tag}  {c['key'][:140]}")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\n-> {args.out}")


main()
