#!/usr/bin/env python3
"""harvest — 把 run 目录 work/ 里 real 臂译文收进 bench/zh-store/，并维护 manifest.jsonl。

用法:
  python3 bench/py/harvest.py --dir bench/results/<run>     # 收割该 run 的 work/
  python3 bench/py/harvest.py --reindex                   # 全量重建 zh-store/manifest.jsonl

门槛: 读 records/compile.jsonl(arm=zh) + fixloop.jsonl 取每 id 终判状态;
  终判 clean → primary {id}/{zh,splice}; 其余已译格 → _quarantine/{id}/（付费字节保留,
  供日后 compile/fixloop 免费重试, manifest 标记使选池永不重译）; 同 id 已入库 → _alt/{id}/{run}/。
move 语义（资产出车间），收割后 work/ 是纯脚手架可整删。纯文件操作，系统 python3。
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


def latest_status(path: str, arm: str | None) -> dict:
    out = {}
    if not os.path.isfile(path):
        return out
    for line in open(path):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if arm is not None and r.get("arm") != arm:
            continue
        out[canon(r["id"])] = r.get("status")
    return out


def clean_ids(run_dir: str) -> set:
    rec = os.path.join(run_dir, "records")
    comp = latest_status(os.path.join(rec, "compile.jsonl"), "zh")
    fix = latest_status(os.path.join(rec, "fixloop.jsonl"), None)
    eff = dict(comp)
    eff.update(fix)  # fixloop 是 compile 之后的终判
    return {pid for pid, st in eff.items() if st == "clean"}


def zone_of(rel: str) -> str:
    if rel.startswith("_alt"):
        return "alt"
    if rel.startswith("_quarantine"):
        return "quarantine"
    return "primary"


def harvest_run(run_dir: str) -> None:
    work = os.path.join(run_dir, "work")
    source_run = os.path.basename(run_dir.rstrip("/"))
    clean = clean_ids(run_dir)
    moved = skipped = alt = quar = 0
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
        zone = "primary" if pid in clean else "quarantine"
        dst = os.path.join(STORE, pid) if zone == "primary" else os.path.join(STORE, "_quarantine", pid)
        if os.path.isdir(dst):
            dst = os.path.join(STORE, "_alt", pid, source_run)
            zone = "alt"
            alt += 1
        elif zone == "quarantine":
            quar += 1
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
            "zone": zone,
        }
        with open(os.path.join(dst, "provenance.json"), "w") as f:
            json.dump(prov, f)
        rows.append({"has_zh": has_zh, "has_splice": has_splice, **prov})
        moved += 1
    with open(MANIFEST, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"harvest {source_run}: moved={moved} primary={moved - alt - quar} quarantine={quar} alt={alt} skipped_nonreal={skipped}")


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
        parts = rel.split(os.sep)
        pid = parts[1] if rel.startswith(("_alt", "_quarantine")) and len(parts) > 1 else rel
        zone = zone_of(rel)
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
                "zone": zone,
            }
        )
    rows.sort(key=lambda r: (r["id"], r["source_run"]))
    with open(MANIFEST, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    from collections import Counter

    z = Counter(r["zone"] for r in rows)
    prim = {r["id"] for r in rows if r["zone"] == "primary"}
    print(f"reindex: {len(rows)} rows zones={dict(z)} primary_ids={len(prim)} -> {MANIFEST}")


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
