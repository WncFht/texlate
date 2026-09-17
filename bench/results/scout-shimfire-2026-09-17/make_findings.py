#!/usr/bin/env python3
"""Emit findings.txt — class-A root-cause table + class-B engine table + fixes."""
import json
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path("/home/fanghaotian/src/texlate")
OUT = ROOT / "bench/results/scout-shimfire-2026-09-17"
CASES = ROOT / "bench/results/stagerun-loop1-2026-09-16/cases.jsonl"

rules = yaml.safe_load((ROOT / "src/texlate/compile/fixloop/rules.yaml").read_text())
for r in rules["rules"]:
    if r.get("id") == "legacy_pkg_shim":
        SHIM = set((r["action"]["params"].get("shim_map") or {}).keys())

CLASS_B = {
    "pstricks.sty", "algorithm.sty", "stmaryrd.sty", "pst-plot.sty",
    "pst-node.sty", "epsf.sty", "mathdots.sty", "algorithmic.sty",
    "siunitx.sty", "algpseudocode.sty", "faktor.sty", "pst-all.sty",
    "pst-text.sty", "pstricks-add.sty", "soul.sty",
}

rows = [l.split("\t") for l in (OUT / "cases.tsv").read_text().splitlines()[1:] if l.strip()]
# rows: corpus, ts, verdict, engine, file, cls, reason, evidence

by_file = defaultdict(list)
for r in rows:
    by_file[r[4]].append(r)

# later-row rescue map for reason-d rows
cases = [json.loads(l) for l in CASES.read_text().splitlines() if l.strip()]
by_corpus = defaultdict(list)
for c in cases:
    by_corpus[c["corpus"]].append(c)
for v in by_corpus.values():
    v.sort(key=lambda c: c["ts"])

def later_verdict(cid, ts):
    later = [x for x in by_corpus[cid] if x["ts"] > ts]
    return (later[-1].get("verdict"), bool(later[-1].get("final_pdf"))) if later else (None, False)

L = []
L.append("SCOUT-SHIMFIRE residual missing_file tail attribution")
L.append("data: bench/results/stagerun-loop1-2026-09-16/cases.jsonl (6452 rows, ALL xelatex — no tectonic arm ran)")
L.append("bench rev: git_rev 7ba0ece (run created 2026-09-16T05:36Z); batch-8 shim expansion (36f926d) landed DURING/AFTER the sweep")
L.append("")
L.append("LEGEND — reason codes:")
L.append("  I = file was installed by static_precheck (in 'installed [...]') — t=0 snapshot artifact, NOT residual")
L.append("  c = legacy_pkg_shim DID fire for this file in this row (stub injected) — rescued mid-loop; case died on a DIFFERENT payload — artifact")
L.append("  d = file WAS the loop payload (missing_file round) but NO rule applied — at that row's rev the shim_map key did not exist yet")
L.append("  b = file never became the loop payload (loop died on another missing file/category first) — latent, never evaluated")
L.append("  a = loop never ran")
L.append("")
L.append("MECHANISM NOTE: 'missing files=[...]' is emitted ONLY by static_precheck at round 0 — a static")
L.append("scan BEFORE any install/shim. Files on that list that were later installed (I) or shimmed (c) stay")
L.append("on the list — the tail metric does not re-baseline. True residual = reason d (+ latent b).")
L.append("")
L.append("=== CLASS A — shim-covered files in last-missing (dominant reason per file) ===")
L.append(f"{'file':24s} {'n':>3s}  reasons  example corpus ids")
for f in sorted(by_file, key=lambda x: -sum(1 for r in by_file[x] if r[5] == 'A')):
    rs = [r for r in by_file[f] if r[5] == "A"]
    if not rs:
        continue
    rc = Counter(r[6] for r in rs)
    ex = [r[0] for r in rs[:3]]
    L.append(f"{f:24s} {len(rs):3d}  {dict(rc)}  {ex}")
L.append("")
L.append("=== CLASS B — CTAN-real files: engine arm + disposition ===")
L.append("ALL 105 class-B rows ran xelatex (bench has no tectonic arm). Disposition:")
bstat = defaultdict(Counter)
for r in rows:
    if r[5] == "B":
        bstat[r[4]][r[6]] += 1
for f in sorted(bstat, key=lambda x: -sum(bstat[x].values())):
    L.append(f"  {f:18s} {dict(bstat[f])}  e.g. {[r[0] for r in rows if r[4]==f][:2]}")
L.append("")
L.append("Every class-B file was successfully tlmgr-installed at precheck (reason I) — they are")
L.append("metric artifacts, not failures. tlmgr usermode installs persist in TEXMFHOME across cells.")
L.append("")
L.append("=== REASON-D RESCUE CHECK (rerun rows in same cases.jsonl) ===")
drows = [r for r in rows if r[6] == "d"]
resc = Counter()
for r in drows:
    v, pdf = later_verdict(r[0], r[1])
    if v is None:
        resc["no_later_row"] += 1
    elif pdf:
        resc["rescued"] += 1
    elif "missing" in str(v):
        resc["still_missing"] += 1
    else:
        resc["other_fail"] += 1
L.append(f"reason-d rows: {len(drows)} -> {dict(resc)}")
L.append("'still_missing' files that ARE in current shim_map (keys landed post-last-batch ~08:00 09-17):")
sm = defaultdict(list)
for r in drows:
    v, pdf = later_verdict(r[0], r[1])
    if v and not pdf and "missing" in str(v):
        sm[r[4]].append(r[0])
for f, cs in sorted(sm.items(), key=lambda x: -len(x[1])):
    tag = "SHIM-now" if f in SHIM else "NO-KEY (true gap)"
    L.append(f"  {f:20s} {tag:22s} n={len(cs)} e.g. {cs[:3]}")
L.append("")
L.append("=== TOP-3 RECOMMENDED FIXES ===")
L.append("1) TAIL METRIC re-baseline: subtract static_precheck 'installed [...]' + shim-injected files")
L.append("   from last-missing attribution — 204/429 rows (I=173 + c=31) are pure snapshot artifacts.")
L.append("   Attribute residual by the LAST loop round's missing_file payload, not the t=0 scan list.")
L.append("2) RERUN the ~48 reason-d stragglers on HEAD: 24 still-missing (aasms4/psfig.tex/aas2pp4 keys")
L.append("   landed in batch-8 after the last 08:00 batch) + 24 never-rerun. Expect most 'A' to flip;")
L.append("   the '?' no-key files (nato.sty, laa.cls, dina4.sty, prabib.sty, BoxedEPS.tex, FEYNMAN.tex,")
L.append("   kapjrnls.tex, axodraw2.sty) are genuine shim_map coverage gaps → candidate new keys.")
L.append("3) SHIM DEP CHAIN: axodraw.sty shim needs axodraw2.sty which tlmgr could not provide at first")
L.append("   (advisory 'no package provides axodraw2.sty (candidates: axodraw2)'); dep failure dead-ends")
L.append("   the cell. Consider needs-dep failure -> fall through to next rule or degrade to noop stub.")

(OUT / "findings.txt").write_text("\n".join(L) + "\n")
print("\n".join(L))
