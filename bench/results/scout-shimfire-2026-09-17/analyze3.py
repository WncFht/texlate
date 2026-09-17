#!/usr/bin/env python3
"""Classify each (case-row, last-missing-file) by reason code."""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path("/home/fanghaotian/src/texlate")
CASES = ROOT / "bench/results/stagerun-loop1-2026-09-16/cases.jsonl"
RULES = ROOT / "src/texlate/compile/fixloop/rules.yaml"
OUT = ROOT / "bench/results/scout-shimfire-2026-09-17"

rules = yaml.safe_load(RULES.read_text())
shim_keys = set()
for r in rules["rules"]:
    if r.get("id") == "legacy_pkg_shim":
        shim_keys = set((r["action"]["params"].get("shim_map") or {}).keys())

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

# per-corpus: all rows sorted by ts, mark if later row rescued
by_corpus = defaultdict(list)
for c in cases:
    by_corpus[c["corpus"]].append(c)
rescued_later = {}
for cid, rows in by_corpus.items():
    rows.sort(key=lambda c: c["ts"])
    for i, r in enumerate(rows):
        if "missing" in str(r.get("verdict") or ""):
            rescued_later[(cid, r["ts"])] = any(
                x.get("final_pdf") for x in rows[i + 1 :]
            )

rows_out = []
reason_files = defaultdict(Counter)
file_reason = defaultdict(Counter)
for c in missing_cases:
    acts = c.get("actions") or []
    rounds = [r for r in (c.get("rounds") or []) if r.get("cat") is not None]  # drop salvage pseudo-round
    last_missing = None
    for a in acts:
        m = MISSING_RE.search(a.get("result") or "")
        if m:
            last_missing = parse_list(m.group(1))
    if not last_missing:
        continue
    pays = [r.get("pay") for r in rounds]
    shim_notes = [a.get("result") or "" for a in acts if a.get("rule") == "legacy_pkg_shim"]
    loop_actions = [a for a in acts if isinstance(a.get("round"), int) and a["round"] > 0]
    for f in last_missing:
        if f in shim_keys:
            cls = "A"
        elif f in CLASS_B:
            cls = "B"
        else:
            cls = "?"
        # normalize: pay may be basename or stem
        stem = f.rsplit(".", 1)[0]
        pay_eq = [p for p in pays if p and (p == f or p == stem or p.rsplit("/", 1)[-1] in (f, stem))]
        shim_hit = [n for n in shim_notes if f in n or stem in n]
        if not rounds:
            reason = "a"  # loop never ran
            ev = "no loop rounds"
        elif shim_hit:
            reason = "c"  # shim fired yet still last-missing
            ev = "; ".join(shim_hit)[:110]
        elif pay_eq:
            # file was payload but no shim action -> key absent at bench rev OR cond/mode skip
            reason = "d"
            ev = f"pay={pay_eq} loop_actions={[a['rule'] for a in loop_actions]}"
        else:
            reason = "b"  # never the payload; loop died on other cat/file
            ev = f"pays={pays[:4]}"
        rows_out.append((c["corpus"], c["ts"], c["verdict"], c["engine"], f, cls, reason, ev))
        file_reason[f][reason] += 1
        reason_files[reason][f] += 1

print("=== reason x file (class A+B) ===")
for f in sorted(file_reason, key=lambda x: -sum(file_reason[x].values())):
    cls = "A" if f in shim_keys else ("B" if f in CLASS_B else "?")
    tot = sum(file_reason[f].values())
    print(f"{tot:3d} {cls} {f:22s} {dict(file_reason[f])}")

print("\n=== reason totals ===")
print(Counter(r[6] for r in rows_out))
print("\n=== class totals ===")
print(Counter(r[5] for r in rows_out))

with open(OUT / "cases.tsv", "w") as fh:
    fh.write("corpus\tts\tverdict\tengine\tlast_missing_file\tclass\treason\tevidence\n")
    for r in rows_out:
        fh.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
print(f"\nwrote {OUT/'cases.tsv'} rows={len(rows_out)}")
