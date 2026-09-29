"""qc_replay 复用驱动——钉 regen 新副本（max altseq）而非默认低 altseq 优选。"""
import json, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, "tools")
sys.path.insert(0, "bench/py")
import qc_replay as qr
from kernel import vault

OUT = Path("tmp/qc_replay_regen_new")
OUT.mkdir(parents=True, exist_ok=True)

cohort = [l.strip() for l in open("tmp/qc_regen_soak_ids.txt") if l.strip()]
want = set(cohort)

# newest product-ok splice copy per idc (max altseq wins = today's regen seal)
best = {}
for _mp, key, meta in vault._iter_metas():
    if key is None or meta is None or key[0] not in want or key[1] != "-":
        continue
    files = meta.get("files") or {}
    if "splice" not in files or not vault._copy_intact(meta):
        continue
    if not vault._copy_product_ok(meta, "splice")[0]:
        continue
    a = int(key[3] or 0)
    if key[0] not in best or a > best[key[0]][0]:
        best[key[0]] = (a, key[2], key[3], meta.get("source_run"))

print("newest copies found:", len(best), file=sys.stderr)
items = qr._cell_list(want, None, "-")
for it in items:
    b = best.get(it["idc"])
    it["copy"] = (b[1], b[2]) if b else None
work = Path(tempfile.mkdtemp(prefix="qc_new_", dir=OUT))
res = []
with ProcessPoolExecutor(max_workers=10) as ex, (OUT/"papers.jsonl").open("w") as fh:
    futs = [ex.submit(qr._replay_cell, it, work, "-", False) for it in items]
    for i, f in enumerate(futs):
        r = f.result(); res.append(r); fh.write(json.dumps(r, ensure_ascii=False)+"\n")
        if i % 40 == 0: print(f"{i}/{len(items)}", flush=True)
from collections import Counter
print("tiers:", Counter(r.get("qc_tier") for r in res))
print("src_run of copies:", Counter(b[3] for b in best.values()))
