"""一次性探针：e2e-real v3-100 的 base-xel 补跑（给 alignbench 凑 en 对）。

对 results.json 里 pipe-xel 产出过 pdf（pdf_bytes>0）但 base-xel 未跑的工程，
复用 e2e_real_bench.base_xel_condition 补 base 编译（corpus 原样 copy→xelatex）。
不写回 results.json——纯补齐 work_e2ereal/base-xel/<id>/ 产物供 pairs.jsonl。

用法: uv run python bench/py/scratch/base_fill.py [--tag v3-100-2026-09-15] [-j 4]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# bench 模块与 texlate 快照都要在 texlate import 之前就位
os.environ.setdefault(
    "TEXLATE_SRC", str(ROOT / "bench/work_e2ereal/_src_snapshot_v3/src")
)
sys.path.insert(0, str(ROOT / "bench/py"))

import e2e_real_bench


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v3-100-2026-09-15")
    ap.add_argument("-j", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=240.0)
    args = ap.parse_args()

    results = json.loads(
        (ROOT / "bench/results" / args.tag / "results.json").read_text()
    )
    todo = []
    for pid, rec in sorted(results.items()):
        pipe = rec.get("pipe-xel") or {}
        has_zh_pdf = (pipe.get("compile") or {}).get("pdf_bytes", 0) > 0
        has_base = "base-xel" in rec
        if not has_zh_pdf or has_base:
            continue
        main_rel = rec.get("main")
        src = e2e_real_bench.CORPUS / pid / "extracted"
        if not main_rel or not src.is_dir():
            continue
        todo.append((pid, src, main_rel))
    print(f"base fill: {len(todo)} papers", flush=True)

    def one(item):
        pid, src, main_rel = item
        sid = e2e_real_bench.safe_id(pid)
        try:
            rec = e2e_real_bench.base_xel_condition(src, sid, main_rel, args.timeout)
            return pid, rec.get("status"), (rec.get("compile") or {}).get("first_error")
        except Exception as e:
            return pid, "bench_error", repr(e)[:200]

    with ThreadPoolExecutor(max_workers=args.j) as ex:
        for pid, status, err in ex.map(one, todo):
            print(f"  {pid}: {status} {err or ''}", flush=True)


if __name__ == "__main__":
    main()
