#!/usr/bin/env python3
"""gate_scorecard — M2 出口门记分卡（末条 record 口径）。

用法:
    python3 bench/py/gate_scorecard.py [records_dir]

缺省读 bench/results/stagerun-loop1-2026-09-16/records/。
对每篇 paper 取 compile(zh)/fixloop 末条 record 合成终态:
    pdf = 终态 ∈ {clean, partial}（compile 或 fixloop 产出了 PDF）
    union_pdf_rate = pdf / 全部格
同时给出 clean 率（严格口径）、各终态分布、距 90% 缺口数。
依赖: 纯 stdlib。
"""

import json
import sys
from collections import Counter
from pathlib import Path

DEFAULT_DIR = Path("bench/results/stagerun-loop1-2026-09-16/records")
GATE = 0.90


def last_records(path: Path, arm: str | None = None) -> dict[str, dict]:
    last: dict[str, dict] = {}
    if not path.exists():
        return last
    for line in path.open():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if arm is not None and r.get("arm") != arm:
            continue
        last[r["id"]] = r
    return last


def main() -> int:
    rec_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    comp = last_records(rec_dir / "compile.jsonl", arm="zh")
    fix = last_records(rec_dir / "fixloop.jsonl")

    end = Counter()
    end_sig = Counter()
    for pid, c in comp.items():
        f = fix.get(pid)
        stage, st = ("fixloop", f["status"]) if f else ("compile", c["status"])
        end[f"{stage}:{st}"] += 1
        if st not in ("clean",):
            end_sig[(f or c).get("sig") or "?"] += 1

    total = sum(end.values())
    pdf = sum(v for k, v in end.items() if k.split(":")[1] in ("clean", "partial"))
    clean = sum(v for k, v in end.items() if k.split(":")[1] == "clean")
    reject = end.get("compile:reject", 0)
    n_norej = total - reject

    print(f"records: {rec_dir}")
    print(f"cells={total}  pdf={pdf} ({pdf/total:.2%})  clean={clean} ({clean/total:.2%})")
    print(f"gate union-pdf >=90%: {'PASS' if pdf/total >= GATE else f'need +{int(total*GATE)-pdf+1}'}")
    print(f"  excl-reject(n={n_norej}): pdf {pdf/n_norej:.2%}  clean {clean/n_norej:.2%}")
    print("\nend-state:")
    for s, c in end.most_common():
        print(f"  {c:5d}  {s}")
    print("\ntop non-clean sigs:")
    for s, c in end_sig.most_common(15):
        print(f"  {c:5d}  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
