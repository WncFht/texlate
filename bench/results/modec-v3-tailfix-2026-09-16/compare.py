#!/usr/bin/env python3
"""新旧 modec-v3 对照：tailfix 复跑 vs 旧基线（pre-tail-parity harness）。

用法: python3 compare.py  （cwd 任意，路径硬编码）
产出: stdout 全文对照（report.md 素材）。
"""

import json
from collections import Counter
from pathlib import Path

OLD = Path(__file__).resolve().parent.parent / "modec-v3-2026-09-16" / "results.json"
NEW = Path(__file__).resolve().parent / "results.json"

CONDS = ["base-xel", "pipe-xel", "pipeB-xel", "pipeC-xel"]
RANK = {"reject": -1, "·": -1, "fail": 0, "partial": 1, "clean": 2}


def status(rec: dict, cond: str) -> str:
    c = rec.get(cond)
    if not c:
        return "·"
    return c.get("verdict", {}).get("status", "?")


def led(rec: dict, cond: str) -> dict:
    return rec.get(cond, {}).get("sabotage", {}) or {}


def main() -> None:
    old = json.loads(OLD.read_text())
    new = json.loads(NEW.read_text())
    ids = sorted(set(old) | set(new))
    print(f"papers: old {len(old)} / new {len(new)} / union {len(ids)}")

    print("\n== verdict 分布 (old -> new) ==")
    for c in CONDS:
        co = Counter(status(r, c) for r in old.values())
        cn = Counter(status(r, c) for r in new.values())
        print(f"{c:9s} old {dict(co)}  new {dict(cn)}")

    print("\n== 逐篇 verdict 差集 ==")
    for c in CONDS:
        better, worse, changed = [], [], []
        for i in ids:
            so, sn = status(old.get(i, {}), c), status(new.get(i, {}), c)
            if so == sn:
                continue
            d = RANK.get(sn, 0) - RANK.get(so, 0)
            row = f"{i}: {so}->{sn}"
            (better if d > 0 else worse if d < 0 else changed).append(row)
        print(f"\n[{c}] better {len(better)} / worse {len(worse)}")
        for r in better:
            print(f"  + {r}")
        for r in worse:
            print(f"  - {r}")

    print("\n== Mode B 台账 (pipeB-xel) ==")
    for tag, res in (("old", old), ("new", new)):
        tot = Counter()
        kinds: dict = {}
        esc: list = []
        for r in res.values():
            ledg = led(r, "pipeB-xel")
            tot.update({k: ledg.get(k, 0) for k in ("events", "sabotaged", "caught", "recovered", "escaped")})
            esc += ledg.get("escaped_ids", [])
            for k, v in (ledg.get("by_kind") or {}).items():
                kk = kinds.setdefault(k, Counter())
                kk.update(v)
        gate = "PASS" if tot["escaped"] == 0 else "FAIL"
        print(f"{tag}: sabotaged {tot['sabotaged']} (events {tot['events']}) -> "
              f"caught {tot['caught']} / recovered {tot['recovered']} / escaped {tot['escaped']} [{gate}]")
        for k in sorted(kinds):
            print(f"   {k}: {dict(kinds[k])}")
        if esc:
            print(f"   escaped_ids: {esc}")

    print("\n== Mode C 台账 (pipeC-xel) ==")
    for tag, res in (("old", old), ("new", new)):
        tot = Counter()
        for r in res.values():
            ledg = led(r, "pipeC-xel")
            tot.update({k: ledg.get(k, 0) for k in ("events", "sabotaged", "moved", "spliced", "dropped")})
        dist = Counter(status(r, "pipeC-xel") for r in res.values())
        base_pdf = surv = 0
        broke = []
        for i, r in res.items():
            a = status(r, "pipe-xel")
            if a not in ("clean", "partial"):
                continue
            base_pdf += 1
            if status(r, "pipeC-xel") in ("clean", "partial"):
                surv += 1
            else:
                broke.append(i)
        splice_rate = tot["spliced"] / tot["sabotaged"] if tot["sabotaged"] else 0
        print(f"{tag}: moved {tot['moved']} / 涉块 {tot['sabotaged']} -> spliced {tot['spliced']} "
              f"({splice_rate:.1%}) / dropped {tot['dropped']}; verdict {dict(dist)}")
        print(f"     存活 {surv}/{base_pdf} 出pdf; broke {broke}")

    print("\n== 管线引入退化 (pipe 非clean ∧ base clean) ==")
    for tag, res in (("old", old), ("new", new)):
        deg = [i for i in ids
               if status(res.get(i, {}), "pipe-xel") not in (None, "·", "clean")
               and status(res.get(i, {}), "base-xel") == "clean"]
        print(f"{tag}: {deg}")

    print("\n== Mode B/C vs pipe 同步退化 (破坏臂差于 pipe 臂的篇) ==")
    for tag, res in (("old", old), ("new", new)):
        for c in ("pipeB-xel", "pipeC-xel"):
            deg = [i for i in ids
                   if RANK.get(status(res.get(i, {}), c), 0) < RANK.get(status(res.get(i, {}), "pipe-xel"), 0)]
            print(f"{tag} {c}: {deg}")

    print("\n== 新跑 fault/leftover 信号 ==")
    for i in ids:
        for c in ("pipe-xel", "pipeB-xel", "pipeC-xel"):
            t = new.get(i, {}).get(c, {}).get("translate", {})
            fc, lp = t.get("fault_chunks", 0), t.get("leftover_ph", 0)
            if fc or lp:
                print(f"  {i} {c}: fault_chunks={fc} leftover_ph={lp}")


if __name__ == "__main__":
    main()
