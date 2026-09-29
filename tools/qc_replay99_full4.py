"""qc99 收官复扫 sweep3——universe=vault 现行可交付 splice 副本全集
（_splice_copy_index：intact+product_ok+非墓碑，双臂）。prev 对照面含 full2。
"""

import json, sys, tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import _env  # noqa: F401 -- src 登程须先于 texlate/kernel import

sys.path.insert(0, str(_env.BENCH_PY))
import qc_replay as qr
from kernel.dedup import _canon

OUT = _env.REPO / "tmp/qc_replay99_full4"
OUT.mkdir(parents=True, exist_ok=True)

prev: dict[str, dict] = {}
for f in [
    "tmp/qc_replay99_full/papers.jsonl",
    "tmp/qc_replay_regen_new/papers.jsonl",
    "tmp/qc_replay99-b/papers.jsonl",
    "tmp/qc_replay_real_new/papers.jsonl",
    "tmp/qc_replay-vault-real/papers.jsonl",
    "tmp/qc_replay99_full2/papers.jsonl",
    "tmp/qc_replay99_full3/papers.jsonl",
]:
    try:
        for line in open(_env.REPO / f):
            r = json.loads(line)
            k = _canon(r["idc"]) or r["idc"]
            e = prev.setdefault(k, {})
            if r.get("main_rel"):
                e.setdefault("main_rel", r["main_rel"])
            if r.get("sig_counts") is not None:
                e.setdefault("sig_counts", r["sig_counts"])
                e.setdefault("qc_tier", r.get("qc_tier"))
    except FileNotFoundError:
        pass

items = []
for arm, marks in (("-", False), ("real", True)):
    for idc, copy in qr._splice_copy_index(None, arm).items():
        ck = _canon(idc) or idc
        p = prev.get(ck, {})
        items.append(
            {
                "idc": idc,
                "prev_status": p.get("qc_tier"),
                "prev_sig_counts": p.get("sig_counts") or {},
                "main_rel": p.get("main_rel"),
                "copy": copy,
                "_arm": arm,
                "_marks": marks,
            }
        )
print(f"universe: {len(items)}", flush=True)

work = Path(tempfile.mkdtemp(prefix="qc_full_", dir=OUT))
res = []
with (
    ProcessPoolExecutor(max_workers=10) as ex,
    (OUT / "papers.jsonl").open("w", encoding="utf-8") as fh,
):
    futs = {
        ex.submit(qr._replay_cell, it, work, it["_arm"], it["_marks"]): it
        for it in items
    }
    for i, fut in enumerate(as_completed(futs), 1):
        r = fut.result()
        r["arm"] = futs[fut]["_arm"]
        res.append(r)
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        if i % 50 == 0:
            fh.flush()
            print(f"  {i}/{len(items)}", flush=True)

(OUT / "summary.json").write_text(
    json.dumps(qr._summarize(res), ensure_ascii=False, indent=2), encoding="utf-8"
)
print("tiers:", Counter((r.get("arm"), r.get("qc_tier")) for r in res))
print("errors:", Counter((r.get("arm"), r.get("error")) for r in res if "error" in r))
