#!/usr/bin/env python3
r"""rerun_xelatex.py — 修复循环第 1 轮: tlmgr usermode 补包后重跑 xelatex 失败项.

读取 compile-bench.json, 对 xelatex pdf=False 的 (project,cond) 在既有 work 目录
上重跑 xelatex, 结果写入 runs[cond]['xelatex_r1'], 并记录本轮应用的修复动作.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compile_bench import RESULTS, WORK, run_xelatex

FIXES = ["tlmgr --usermode install ifmtarg sttools silence"]
ROUND = "xelatex_r4"


def main():
    jp = RESULTS / "compile-bench.json"
    data = json.loads(jp.read_text())
    for name, p in data["projects"].items():
        rel = p["main"]
        for cond in ("baseline", "ctex", "zh"):
            r = p["runs"].get(cond, {})
            old = r.get("xelatex")
            if not old or old.get("pdf"):
                continue
            # 已修复成功过的跳过
            if any(
                r.get(k, {}).get("pdf")
                for k in ("xelatex_r1", "xelatex_r2", "xelatex_r3")
            ):
                continue
            wdir = WORK / name / cond
            if not wdir.exists():
                continue
            nr = run_xelatex(wdir, rel)
            nr["repair_fixes"] = FIXES
            r[ROUND] = nr
            tag = "OK " if nr["pdf"] else "FAIL"
            print(
                f"{name:14s} {cond:8s} {tag} clean={nr['clean']} "
                f"err={nr['n_errors']} cat={nr['category']} "
                f"{nr['seconds']:.1f}s | {nr.get('first_error')}",
                flush=True,
            )
    jp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print("saved", jp)


if __name__ == "__main__":
    main()
