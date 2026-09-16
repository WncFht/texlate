"""perf-tail wave-2: per-file parse_file timing over corpus_v3.

Usage:
  uv run python bench/py/scratch/perf_tail.py sample   # write sample list
  uv run python bench/py/scratch/perf_tail.py run OUT.jsonl  # time sample
  uv run python bench/py/scratch/perf_tail.py profile N      # cProfile top-N
"""

import cProfile
import json
import pstats
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "bench" / "corpus_v3"
PRIOR = ROOT / "bench/results/parsebench-v2full1955-2026-09-16/files.jsonl"
OUTDIR = ROOT / "bench/results/perf-tail-2026-09-16"
SAMPLE = OUTDIR / "sample.txt"

sys.path.insert(0, str(ROOT / "src"))
from texlate.latex.api import parse_file


def build_sample() -> list[str]:
    rows = [json.loads(ln) for ln in PRIOR.open()]
    timed = [(r["file"], (r.get("v2") or {}).get("wall_ms") or 0.0) for r in rows]
    timed.sort(key=lambda t: -t[1])
    top = [f for f, _ in timed[:40]]
    rest = [f for f, _ in timed[40:] if (CORPUS / f).exists()]
    rng = random.Random(20260916)
    pick = top + rng.sample(rest, 160)
    return [f for f in pick if (CORPUS / f).exists()]


def cmd_sample() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    files = build_sample()
    SAMPLE.write_text("\n".join(files) + "\n")
    print(f"wrote {len(files)} files to {SAMPLE}")


def cmd_run(out: Path) -> None:
    files = SAMPLE.read_text().split()
    with out.open("w") as fh:
        for i, rel in enumerate(files):
            p = CORPUS / rel
            t0 = time.perf_counter()
            try:
                res = parse_file(p)
                ms = (time.perf_counter() - t0) * 1000
                rec = {
                    "file": rel,
                    "ms": round(ms, 1),
                    "ok": True,
                    "n_chunks": len(res.chunks),
                    "size": p.stat().st_size,
                }
            except Exception as e:
                ms = (time.perf_counter() - t0) * 1000
                rec = {
                    "file": rel,
                    "ms": round(ms, 1),
                    "ok": False,
                    "err": str(e)[:200],
                }
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            if i % 20 == 0:
                print(f"[{i}/{len(files)}] {rel} {rec['ms']:.0f}ms", flush=True)


def cmd_profile(n: int, before: Path) -> None:
    rows = [json.loads(ln) for ln in before.open()]
    rows.sort(key=lambda r: -r["ms"])
    for r in rows[:n]:
        rel = r["file"]
        p = CORPUS / rel
        pr = cProfile.Profile()
        t0 = time.perf_counter()
        pr.enable()
        try:
            parse_file(p)
        except Exception as e:
            print(f"{rel}: parse failed {e}")
        pr.disable()
        ms = (time.perf_counter() - t0) * 1000
        out = OUTDIR / f"prof-{rel.replace('/', '_')}.txt"
        with out.open("w") as fh:
            st = pstats.Stats(pr, stream=fh)
            st.sort_stats("cumulative").print_stats(40)
            st.sort_stats("tottime").print_stats(40)
        print(f"{rel}: {ms:.0f}ms -> {out.name}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "sample":
        cmd_sample()
    elif cmd == "run":
        cmd_run(Path(sys.argv[2]))
    elif cmd == "profile":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        before = Path(sys.argv[3]) if len(sys.argv) > 3 else OUTDIR / "before.jsonl"
        cmd_profile(n, before)
