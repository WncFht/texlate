#!/usr/bin/env python3
"""Attribute residual missing_file tail in stagerun-loop1 cases.jsonl."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path("/home/fanghaotian/src/texlate")
CASES = ROOT / "bench/results/stagerun-loop1-2026-09-16/cases.jsonl"
RULES = ROOT / "src/texlate/compile/fixloop/rules.yaml"

rules = yaml.safe_load(RULES.read_text())

# collect ALL shim_map keys (there may be more than one shim_map in yaml)
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
print(f"shim_map keys: {len(shim_keys)}", file=sys.stderr)

CLASS_B = {
    "pstricks.sty", "algorithm.sty", "stmaryrd.sty", "pst-plot.sty",
    "pst-node.sty", "epsf.sty", "mathdots.sty", "algorithmic.sty",
    "siunitx.sty", "algpseudocode.sty", "faktor.sty", "pst-all.sty",
    "pst-text.sty", "pstricks-add.sty", "soul.sty",
}

MISSING_RE = re.compile(r"missing files=\[(.*?)\]\s*->\s*installed \[(.*?)\]")


def parse_list(s):
    s = s.strip()
    if not s:
        return []
    return [x.strip().strip("'\"") for x in s.split(",")]


cases = []
for line in CASES.read_text().splitlines():
    line = line.strip()
    if line:
        cases.append(json.loads(line))

print(f"cases: {len(cases)}", file=sys.stderr)

missing_cases = [c for c in cases if "missing" in str(c.get("verdict") or "")]
print(f"verdict~missing: {len(missing_cases)}", file=sys.stderr)

# per-case: last 'missing files=[...]' action
rows = []  # corpus, verdict, engine, file, cls, reason, evidence
file_counter = Counter()
file_cases = defaultdict(list)
for c in missing_cases:
    acts = c.get("actions") or []
    last_missing = None
    for a in acts:
        r = a.get("result") or a.get("detail") or ""
        m = MISSING_RE.search(r)
        if m:
            last_missing = (a.get("round"), parse_list(m.group(1)), parse_list(m.group(2)), r)
    if not last_missing:
        continue
    rnd, files, installed, raw = last_missing
    for f in files:
        file_counter[f] += 1
        file_cases[f].append(c)

print("\n=== top last-missing files ===", file=sys.stderr)
for f, n in file_counter.most_common(40):
    tag = "SHIM" if f in shim_keys else ("REALB" if f in CLASS_B else "?")
    print(f"{n:4d} {tag:5s} {f}", file=sys.stderr)

# dump per-case detail for the top offenders
out = ROOT / "bench/results/scout-shimfire-2026-09-17"
with open(out / "file_cases.json", "w") as fh:
    json.dump({f: [c["corpus"] for c in cs] for f, cs in file_cases.items()}, fh, indent=0)

# save full case records for shim-covered files
with open(out / "shim_cases_full.jsonl", "w") as fh:
    seen = set()
    for f, cs in file_cases.items():
        if f in shim_keys or f in CLASS_B:
            for c in cs:
                k = (c["corpus"], c.get("engine"), c.get("cond"))
                if k not in seen:
                    seen.add(k)
                    fh.write(json.dumps(c) + "\n")
print("wrote file_cases.json + shim_cases_full.jsonl", file=sys.stderr)
