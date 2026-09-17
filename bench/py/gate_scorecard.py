#!/usr/bin/env python3
"""gate_scorecard — M2 出口门记分卡（末条 record 口径）。

用法:
    python3 bench/py/gate_scorecard.py [records_dir]

缺省读 bench/results/stagerun-loop1-2026-09-16/records/。
对每篇 paper 取 compile(zh)/fixloop 末条 record 合成终态:
    pdf = 终态 ∈ {clean, partial}（compile 或 fixloop 产出了 PDF）
    union_pdf_rate = pdf / 全部格
fix 覆盖有门槛：compile 终态须为真编译结果（fail/partial/clean，
reject/skip 格的 fixloop 记录是 --on all 误编译英文树的产物不计入），
且 fix.metrics.compile_status_before 须等于当前 compile 终态（否则 fix 陈旧）。
同时给出 clean 率（严格口径）、各终态分布、距 90% 缺口数。
依赖: 纯 stdlib。
"""

import math
import sys
from collections import Counter
from pathlib import Path

import benchlib

DEFAULT_DIR = Path("bench/results/stagerun-loop1-2026-09-16/records")
GATE = 0.90


COMPILED = benchlib.COMPILED_STATUS


def last_records(
    path: Path, arm: str | None = None, upstream: str | None = "mock"
) -> dict[str, dict]:
    if not path.exists():
        return {}
    kept = []
    for r in benchlib.iter_jsonl(path):
        if arm is not None and r.get("arm") != arm:
            continue
        # 双臂波次防串：对臂记录不进本口径——upstream 字段缺失按 mock
        # 计（史前排无此字段）；arm_mismatch skip 是对臂 decline 零
        # verdict 信息，两侧视图全跳。
        if upstream is not None and (r.get("upstream") or "mock") != upstream:
            continue
        errs = r.get("errors") or []
        if any(e.get("code") == "arm_mismatch" for e in errs):
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        kept.append(r)
    return benchlib.latest_by(kept, lambda r: r["id"])


def pick_final(c: dict, f: dict | None) -> tuple[str, dict, str | None]:
    """合成终态：(stage, record, drop_reason)。

    fix 只在覆盖真编译结果且未过期时生效——`--on all` 会对
    inject:reject/skip 格也产出 fixloop 记录（编译被拒英文树），
    不能计入；compile 在 fix 之后重跑且终态改变时 fix 陈旧作废。
    """
    if f is None:
        return "compile", c, None
    if c.get("status") not in COMPILED:
        return "compile", c, "over_noncompiled"
    csb = (f.get("metrics") or {}).get("compile_status_before")
    if csb is None:
        return "compile", c, "no_csb"
    if csb != c.get("status"):
        return "compile", c, "stale"
    cu, fu = c.get("upstream"), f.get("upstream")
    if cu and fu and cu != fu:
        return "compile", c, "upstream_mismatch"
    return "fixloop", f, None


def main() -> int:
    rec_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    comp = last_records(rec_dir / "compile.jsonl", arm="zh", upstream="mock")
    fix = last_records(rec_dir / "fixloop.jsonl", upstream="mock")

    end = Counter()
    end_sig = Counter()
    dropped_fix = Counter()
    for pid, c in comp.items():
        f = fix.get(pid)
        stage, r, drop = pick_final(c, f)
        if drop is not None:
            dropped_fix[drop] += 1
        st = r.get("status") or "?"
        end[f"{stage}:{st}"] += 1
        if st != "clean":
            end_sig[r.get("sig") or "?"] += 1

    total = sum(end.values())
    pdf = sum(v for k, v in end.items() if k.split(":")[1] in ("clean", "partial"))
    clean = sum(v for k, v in end.items() if k.split(":")[1] == "clean")
    reject = end.get("compile:reject", 0)
    n_norej = total - reject

    print(f"records: {rec_dir}")
    if total == 0:
        print("cells=0  (no records)")
        return 0
    print(
        f"cells={total}  pdf={pdf} ({pdf / total:.2%})  clean={clean} ({clean / total:.2%})"
    )
    if pdf / total >= GATE:
        gate_line = "PASS"
    else:
        need = max(0, math.ceil(total * GATE - pdf - 1e-9))
        gate_line = f"need +{need}"
    print(f"gate union-pdf >=90%: {gate_line}")
    if n_norej:
        print(
            f"  excl-reject(n={n_norej}): pdf {pdf / n_norej:.2%}  clean {clean / n_norej:.2%}"
        )
    print("\nend-state:")
    for s, c in end.most_common():
        print(f"  {c:5d}  {s}")
    if dropped_fix:
        print("\ndropped fixloop overrides:")
        for s, c in dropped_fix.most_common():
            print(f"  {c:5d}  {s}")
    print("\ntop non-clean sigs:")
    for s, c in end_sig.most_common(15):
        print(f"  {c:5d}  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
