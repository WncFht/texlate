#!/usr/bin/env python3
"""harvest — 把 run 目录 work/ 里 real 臂的 zh/+splice/ 收进 bench/zh-store/，并维护 manifest.jsonl。

用法:
  python3 bench/py/harvest.py --dir bench/results/<run>     # 收割该 run 的 work/
  python3 bench/py/harvest.py --reindex                   # 全量重建 zh-store/manifest.jsonl

语义: move（资产出车间），收割后 work/ 是纯脚手架可整删。store 已有同 id 的进 _alt/{id}/{source_run}/。
纯文件操作，系统 python3 即可。
"""

import argparse
import json
import os
import shutil
from datetime import UTC, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE = os.path.join(ROOT, "bench", "zh-store")
MANIFEST = os.path.join(STORE, "manifest.jsonl")


def canon(safe: str) -> str:
    return safe.replace("--", "/")


def now() -> str:
    return datetime.now(UTC).isoformat()


def read_marker(cell: str) -> dict:
    for sub in ("zh", "splice"):
        p = os.path.join(cell, sub, ".xlat-arm.json")
        if os.path.isfile(p):
            try:
                return json.load(open(p))
            except Exception:
                return {}
    return {}


def store_dir(pid: str) -> str:
    return os.path.join(STORE, pid)


def harvest_run(run_dir: str) -> None:
    work = os.path.join(run_dir, "work")
    source_run = os.path.basename(run_dir.rstrip("/"))
    moved = skipped = alt = 0
    rows = []
    for safe in sorted(os.listdir(work)):
        cell = os.path.join(work, safe)
        if not os.path.isdir(cell):
            continue
        has_zh = os.path.isdir(os.path.join(cell, "zh"))
        has_splice = os.path.isdir(os.path.join(cell, "splice"))
        if not (has_zh or has_splice):
            continue
        marker = read_marker(cell)
        if marker.get("arm") != "real":
            skipped += 1
            continue
        pid = canon(safe)
        dst = store_dir(pid)
        if os.path.isdir(dst):
            dst = os.path.join(STORE, "_alt", pid, source_run)
            alt += 1
        os.makedirs(dst, exist_ok=True)
        for sub in ("zh", "splice"):
            src = os.path.join(cell, sub)
            if os.path.isdir(src):
                shutil.move(src, os.path.join(dst, sub))
        prov = {
            "id": pid,
            "arm": "real",
            "model": marker.get("model", ""),
            "source_run": source_run,
            "xlat_ts": marker.get("ts", ""),
            "moved_at": now(),
        }
        with open(os.path.join(dst, "provenance.json"), "w") as f:
            json.dump(prov, f)
        rows.append({"has_zh": has_zh, "has_splice": has_splice, **prov})
        moved += 1
    with open(MANIFEST, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"harvest {source_run}: moved={moved} alt={alt} skipped_nonreal={skipped}")


def reindex() -> None:
    rows = []
    for dirpath, _dirnames, filenames in os.walk(STORE):
        if "provenance.json" not in filenames:
            continue
        try:
            prov = json.load(open(os.path.join(dirpath, "provenance.json")))
        except Exception:
            continue
        rel = os.path.relpath(dirpath, STORE)
        pid = rel.split(os.sep)[0] if rel.startswith("_alt") else rel
        rows.append(
            {
                "id": prov.get("id", pid),
                "arm": prov.get("arm", ""),
                "model": prov.get("model", ""),
                "source_run": prov.get("source_run", ""),
                "xlat_ts": prov.get("xlat_ts", ""),
                "moved_at": prov.get("moved_at", ""),
                "has_zh": os.path.isdir(os.path.join(dirpath, "zh")),
                "has_splice": os.path.isdir(os.path.join(dirpath, "splice")),
                "alt": rel if rel.startswith("_alt") else "",
            }
        )
    rows.sort(key=lambda r: (r["id"], r["source_run"]))
    with open(MANIFEST, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    prim = {r["id"] for r in rows if not r["alt"]}
    print(f"reindex: {len(rows)} rows, {len(prim)} primary ids -> {MANIFEST}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="run dir containing work/ to harvest")
    ap.add_argument("--reindex", action="store_true", help="rebuild manifest.jsonl")
    args = ap.parse_args()
    if args.reindex:
        reindex()
    if args.dir:
        harvest_run(args.dir)


if __name__ == "__main__":
    main()
