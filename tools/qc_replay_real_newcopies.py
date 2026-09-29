"""real-arm regen 副本钉扎复测 (e2e_real/2026-09-28/e2e_real)。"""

import json, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import _env  # noqa: F401 -- src 登程须先于 texlate/kernel import

sys.path.insert(0, str(_env.BENCH_PY))
import qc_replay as qr
from kernel import vault

OUT = _env.REPO / "tmp/qc_replay_real_new"
OUT.mkdir(parents=True, exist_ok=True)

cohort = [l.strip() for l in open(_env.REPO / "tmp/qc_regen_real_ids.txt") if l.strip()]
want = set(cohort)

best = {}
for _mp, key, meta in vault._iter_metas():
    if key is None or meta is None or key[0] not in want or key[1] != "real":
        continue
    files = meta.get("files") or {}
    if "splice" not in files or not vault._copy_intact(meta):
        continue
    if not vault._copy_product_ok(meta, "splice")[0]:
        continue
    a = int(key[3] or 0)
    if key[0] not in best or a > best[key[0]][0]:
        best[key[0]] = (a, key[2], key[3], meta.get("source_run"))

print("real-arm newest copies:", len(best), file=sys.stderr)
items = qr._cell_list(want, None, "real")
for it in items:
    b = best.get(it["idc"])
    it["copy"] = (b[1], b[2]) if b else None
work = Path(tempfile.mkdtemp(prefix="qc_real_new_", dir=OUT))
res = []
with ProcessPoolExecutor(max_workers=4) as ex, (OUT / "papers.jsonl").open("w") as fh:
    futs = [ex.submit(qr._replay_cell, it, work, "real", True) for it in items]
    for f in futs:
        r = f.result()
        res.append(r)
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
from collections import Counter

print("tiers:", Counter(r.get("qc_tier") for r in res))
print("src_run of copies:", Counter(b[3] for b in best.values()))
for r in res:
    print(r["idc"], r.get("qc_tier"), r.get("sig_counts"), r.get("error"))
