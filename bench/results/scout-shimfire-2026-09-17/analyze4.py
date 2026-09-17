#!/usr/bin/env python3
"""Refined attribution: installed-at-precheck vs shimmed vs true residual."""
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
for r in rules["rules"]:
    if r.get("id") == "legacy_pkg_shim":
        SHIM = set((r["action"]["params"].get("shim_map") or {}).keys())

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

rows_out = []
file_reason = defaultdict(Counter)
b_eng = Counter()
b_install_fail = defaultdict(list)
for c in missing_cases:
    acts = c.get("actions") or []
    rounds = [r for r in (c.get("rounds") or []) if r.get("cat") is not None]
    last_missing = None
    installed0 = []
    for a in acts:
        m = MISSING_RE.search(a.get("result") or "")
        if m:
            last_missing = parse_list(m.group(1))
            installed0 = parse_list(m.group(2))
    if not last_missing:
        continue
    pays = [r.get("pay") for r in rounds]
    shim_notes = [a.get("result") or "" for a in acts if a.get("rule") == "legacy_pkg_shim"]
    loop_rules = [a["rule"] for a in acts if isinstance(a.get("round"), int) and a["round"] > 0]
    last_pay = pays[-1] if pays else None
    for f in last_missing:
        cls = "A" if f in SHIM else ("B" if f in CLASS_B else "?")
        stem = f.rsplit(".", 1)[0]
        pay_eq = [p for p in pays if p and (p == f or p == stem)]
        shim_hit = [n for n in shim_notes if re.search(rf"\b{re.escape(f)}\b", n)]
        if f in installed0:
            reason = "I"  # installed at precheck — artifact
            ev = "precheck installed"
        elif not rounds:
            reason, ev = "a", "no loop rounds"
        elif shim_hit:
            reason, ev = "c", "; ".join(shim_hit)[:100]
        elif pay_eq:
            reason = "d"  # payload but nothing applied
            ev = f"pay_hit, loop_rules={loop_rules}"
        else:
            reason = "b"
            ev = f"never payload; last_pay={last_pay}"
        rows_out.append((c["corpus"], c["ts"], c["verdict"], c["engine"], f, cls, reason, ev))
        file_reason[f][reason] += 1
        if cls == "B":
            b_eng[c["engine"]] += 1
            if reason == "b" and f not in installed0:
                b_install_fail[f].append((c["corpus"], c["engine"], [a.get("result") or "" for a in acts], c.get("advisories") or []))

print("=== reason x file ===")
for f in sorted(file_reason, key=lambda x: -sum(file_reason[x].values())):
    cls = "A" if f in SHIM else ("B" if f in CLASS_B else "?")
    print(f"{sum(file_reason[f].values()):3d} {cls} {f:22s} {dict(file_reason[f])}")
print("\nreason totals:", Counter(r[6] for r in rows_out))
print("class totals:", Counter(r[5] for r in rows_out))
print("class-B engines:", dict(b_eng))

print("\n=== class-B install evidence (sample) ===")
for f, lst in sorted(b_install_fail.items(), key=lambda x: -len(x[1]))[:8]:
    cid, eng, act_res, adv = lst[0]
    print(f"{f} n={len(lst)} e.g. {cid} eng={eng}")
    print(f"   acts={act_res[:3]}")
    print(f"   advisories={adv[:3]}")

with open(OUT / "cases.tsv", "w") as fh:
    fh.write("corpus\tts\tverdict\tengine\tlast_missing_file\tclass\treason\tevidence\n")
    for r in rows_out:
        fh.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
print(f"\nwrote cases.tsv rows={len(rows_out)}")
