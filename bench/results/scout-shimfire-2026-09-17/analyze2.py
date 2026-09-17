#!/usr/bin/env python3
"""Per-case attribution: why shim-covered files stayed last-missing."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path("/home/fanghaotian/src/texlate")
CASES = ROOT / "bench/results/stagerun-loop1-2026-09-16/cases.jsonl"
RULES = ROOT / "src/texlate/compile/fixloop/rules.yaml"
OUT = ROOT / "bench/results/scout-shimfire-2026-09-17"

rules = yaml.safe_load(RULES.read_text())
shim_keys = set()


def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "shim_map" and isinstance(v, dict):
                shim_keys.update(v.keys())
            else:
                walk(v)
    elif isinstance(o, list):
        for i in o:
            walk(i)


walk(rules)

CLASS_B = {
    "pstricks.sty", "algorithm.sty", "stmaryrd.sty", "pst-plot.sty",
    "pst-node.sty", "epsf.sty", "mathdots.sty", "algorithmic.sty",
    "siunitx.sty", "algpseudocode.sty", "faktor.sty", "pst-all.sty",
    "pst-text.sty", "pstricks-add.sty", "soul.sty",
}

MISSING_RE = re.compile(r"missing files=\[(.*?)\]\s*->\s*installed \[(.*?)\]")


def parse_list(s):
    s = s.strip()
    return [x.strip().strip("'\"") for x in s.split(",")] if s else []


cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
missing_cases = [c for c in cases if "missing" in str(c.get("verdict") or "")]

TOP_A = ["aasms4.sty", "psfig.tex", "axodraw.sty", "revtex4.cls", "jheppub.sty",
         "psfig.sty", "citesort.sty", "diagrams.sty", "revtex4-1.cls", "aastex.cls",
         "iopart.cls", "svjour3.cls", "iopams.sty", "texsort.sty", "emulateapj5.sty"]

detail = []
for c in missing_cases:
    acts = c.get("actions") or []
    rounds = c.get("rounds") or []
    last_missing = None
    for a in acts:
        r = a.get("result") or a.get("detail") or ""
        m = MISSING_RE.search(r)
        if m:
            last_missing = parse_list(m.group(1))
    if not last_missing:
        continue
    pays = [r.get("pay") for r in rounds]
    cats = [r.get("cat") for r in rounds]
    shim_actions = [a for a in acts if a.get("rule") == "legacy_pkg_shim"]
    for f in last_missing:
        if f not in shim_keys and f not in CLASS_B:
            continue
        cls = "A" if f in shim_keys else "B"
        # was f ever the loop payload?
        pay_hits = [i for i, p in enumerate(pays) if p == f or (p and p.rsplit("/", 1)[-1] == f)]
        shim_for_f = [a for a in shim_actions if f in str(a.get("result") or a.get("detail") or "")]
        last_round = rounds[-1] if rounds else {}
        detail.append({
            "corpus": c["corpus"], "engine": c.get("engine"), "cond": c.get("cond"),
            "verdict": c.get("verdict"), "file": f, "cls": cls,
            "n_rounds": len(rounds), "started_fail": c.get("started_fail"),
            "pay_hits": pay_hits, "pays": pays, "cats": cats,
            "shim_for_f": [str(a.get("result") or a.get("detail")) for a in shim_for_f],
            "last_cat": last_round.get("cat"), "last_pay": last_round.get("pay"),
            "actions": [f"{a.get('round')}:{a.get('rule')}:{str(a.get('result') or a.get('detail'))[:120]}" for a in acts],
        })

with open(OUT / "detail.json", "w") as fh:
    json.dump(detail, fh, indent=1)

# Summary per file
by_file = defaultdict(list)
for d in detail:
    by_file[d["file"]].append(d)

for f in TOP_A:
    ds = by_file.get(f, [])
    print(f"\n### {f} ({len(ds)} cases)")
    for d in ds[:6]:
        print(f"  {d['corpus']} eng={d['engine']} v={d['verdict']} rounds={d['n_rounds']} payhits={d['pay_hits']} last={d['last_cat']}:{d['last_pay']}")
        print(f"    cats={d['cats']} pays={d['pays']}")
        for a in d["actions"]:
            print(f"    act {a}")
