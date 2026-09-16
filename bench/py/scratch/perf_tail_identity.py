"""A/B identity check: run parse_file under old vs new latex trees.

Usage: uv run python bench/py/scratch/perf_tail_identity.py SRCTREE OUT.jsonl
Each line: {"file":..., "digest": sha256 of canonical result dump}.
"""

import hashlib
import json
import sys
from pathlib import Path

SRCTREE = sys.argv[1]
OUT = sys.argv[2]
ROOT = Path("/home/fanghaotian/src/texlate")
sys.path.insert(0, SRCTREE)

from texlate.latex.api import parse_file

files = (ROOT / "bench/results/perf-tail-2026-09-16/sample.txt").read_text().split()


def digest(res) -> str:
    h = hashlib.sha256()
    h.update(res.vtex.encode())
    for c in res.chunks:
        h.update(b"\x00")
        h.update(repr(c).encode())
    for k, v in sorted(res.ph_map.items()):
        h.update(k.encode())
        h.update(v.encode())
    for w in res.warnings:
        h.update(repr((w.kind, w.pos, w.detail)).encode())
    for inp in res.inputs:
        h.update(repr(inp).encode())
    return h.hexdigest()


with open(OUT, "w") as fh:
    for rel in files:
        p = ROOT / "bench/corpus_v3" / rel
        try:
            res = parse_file(p)
            rec = {"file": rel, "digest": digest(res), "n_chunks": len(res.chunks)}
        except Exception as e:
            rec = {"file": rel, "err": f"{type(e).__name__}:{e}"[:300]}
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
print("done", OUT)
