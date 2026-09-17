#!/usr/bin/env python3
"""Verify reason-d: did later reruns rescue these corpora? Any post-09-17 still missing?"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/home/fanghaotian/src/texlate")
CASES = ROOT / "bench/results/stagerun-loop1-2026-09-16/cases.jsonl"
OUT = ROOT / "bench/results/scout-shimfire-2026-09-17"

import yaml
rules = yaml.safe_load((ROOT / "src/texlate/compile/fixloop/rules.yaml").read_text())
for r in rules["rules"]:
    if r.get("id") == "legacy_pkg_shim":
        SHIM = set((r["action"]["params"].get("shim_map") or {}).keys())

cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
by_corpus = defaultdict(list)
for c in cases:
    by_corpus[c["corpus"]].append(c)
for rows in by_corpus.values():
    rows.sort(key=lambda c: c["ts"])

# load cases.tsv rows (reason d only)
reason_d = [l.split("\t") for l in (OUT / "cases.tsv").read_text().splitlines()[1:] if l.strip()]
reason_d = [r for r in reason_d if r[6] == "d"]

print("=== reason-d: ts distribution ===")
print(Counter(r[1][:10] for r in reason_d))

print("\n=== reason-d corpora: later-row outcomes ===")
outcome = Counter()
still_missing = []
for r in reason_d:
    cid, ts, verdict, eng, f = r[0], r[1], r[2], r[3], r[4]
    rows = by_corpus[cid]
    later = [x for x in rows if x["ts"] > ts]
    if not later:
        outcome["no_later_row"] += 1
        continue
    last = later[-1]
    v = str(last.get("verdict"))
    if last.get("final_pdf"):
        outcome[f"rescued:{v}"] += 1
    elif "missing" in v:
        outcome["still_missing"] += 1
        still_missing.append((cid, ts, f, v, last["ts"]))
    else:
        outcome[f"other:{v.split(':')[0]}"] += 1
print(outcome)
print("\nstill missing after later rerun:")
for x in still_missing[:20]:
    print("  ", x)

# check later rows' shim actions for the same file
print("\n=== later-row shim evidence for reason-d files (sample) ===")
shown = 0
for r in reason_d:
    cid, ts, f = r[0], r[1], r[4]
    later = [x for x in by_corpus[cid] if x["ts"] > ts]
    for x in later:
        for a in x.get("actions") or []:
            res = a.get("result") or ""
            if a.get("rule") == "legacy_pkg_shim" and f in res:
                print(f"  {cid} {x['ts'][:16]} {f}: {res[:80]} -> verdict={x['verdict']}")
                shown += 1
                break
        else:
            continue
        break
    if shown >= 15:
        break
