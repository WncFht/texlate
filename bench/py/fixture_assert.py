#!/usr/bin/env python3
r"""fixture_assert — B2 陷阱断言跑分器: bench/fixtures/*.tex → 契约三件套.

断言逻辑全部复用 miniscanner_test (assert_tricky / assert_209 / assert_multi),
判定口径与 miniscanner-parse.json 一致. 覆盖: tricky.tex T01–T29 (26 条 +
_meta), tricky-209.tex 3 条, tricky-multi T14 ×4.

用法:
  python3 bench/py/fixture_assert.py --out DIR

产出 (docs/10 §统一产出契约): OUT/cases.jsonl (逐断言明细) +
OUT/cells.json (逐 fixture 聚合) + OUT/summary.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
FIXTURES = BENCH / "fixtures"

sys.path.insert(0, str(Path(__file__).parent))
import miniscanner as ms
import miniscanner_test as mt

FIXTURE_FILES = [
    ("tricky.tex", FIXTURES / "tricky.tex"),
    ("tricky-209.tex", FIXTURES / "tricky-209.tex"),
    ("tricky-multi/main.tex", FIXTURES / "tricky-multi" / "main.tex"),
]


def run_fixture(path: Path) -> dict:
    """parse + recon 一次, 供断言复用."""
    r = mt.parse_one(path, timeout_s=30, flatten=True)
    out = {"ok": r["ok"], "wall_ms": r["ms"]}
    if not r["ok"]:
        out["error"] = r["error"]
        return out
    res: ms.ScanResult = r["res"]
    rb = mt.rebuild_metrics(res)
    orig = path.read_text(encoding="utf-8", errors="replace")
    orig_flat = ms.flatten_inputs(orig, str(path.parent), str(path.parent))
    status, ratio, first_diff = mt.classify_recon(orig_flat, rb["recon_identity"])
    out.update(
        res=res,
        recon_identity=rb["recon_identity"],
        recon_fake=rb["recon_fake"],
        identity={"identical": "strict"}.get(status, status),
        quick_ratio=ratio,
        first_diff_at=first_diff,
        n_chunks=len(res.chunks),
        n_placeholders=len(res.ph_map),
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="fixtures trap-assertion bench")
    ap.add_argument("--out", required=True, type=Path, help="契约产出目录")
    args = ap.parse_args()
    out = args.out if args.out.is_absolute() else Path.cwd() / args.out
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    cases: list[dict] = []
    cells: dict[str, dict] = {}

    parsed: dict[str, dict] = {}
    for name, path in FIXTURE_FILES:
        parsed[name] = run_fixture(path)

    # ---- 逐 fixture 断言
    asserts: dict[str, dict] = {}
    t = parsed["tricky.tex"]
    asserts["tricky.tex"] = (
        mt.assert_tricky(t["res"], t["recon_identity"], t["recon_fake"])
        if t["ok"]
        else {"_parse": {"status": "fail", "detail": t.get("error", "")}}
    )
    t2 = parsed["tricky-209.tex"]
    asserts["tricky-209.tex"] = mt.assert_209(t2, t2.get("recon_identity", ""))
    tm = parsed["tricky-multi/main.tex"]
    asserts["tricky-multi/main.tex"] = (
        mt.assert_multi(tm["recon_identity"])
        if tm["ok"]
        else {"_parse": {"status": "fail", "detail": tm.get("error", "")}}
    )

    for name, p in parsed.items():
        cell = {
            "parse_ok": p["ok"],
            "wall_ms": p["wall_ms"],
            "error": p.get("error"),
            "identity": p.get("identity"),
            "n_chunks": p.get("n_chunks"),
            "n_placeholders": p.get("n_placeholders"),
            "n_assert": 0,
            "pass": 0,
            "partial": 0,
            "fail": 0,
            "info": 0,
        }
        for aid, v in asserts[name].items():
            if isinstance(v, dict):
                status, detail = v.get("status", "?"), v.get("detail", "")
            else:  # assert_209 的 parse_ok 是 bool
                status, detail = ("pass" if v else "fail"), str(v)
            cases.append(
                {
                    "case": f"{name}::{aid}",
                    "fixture": name,
                    "id": aid,
                    "status": status,
                    "detail": str(detail),
                    "parse_ok": p["ok"],
                    "wall_ms": p["wall_ms"],
                }
            )
            if status in ("pass", "partial", "fail"):
                cell[status] += 1
                cell["n_assert"] += 1
            else:  # info 级 (tricky _meta 等非断言行)
                cell["info"] += 1
        cells[name] = cell

    wall = round(time.perf_counter() - t0, 1)
    n_pass = sum(c["pass"] for c in cells.values())
    n_partial = sum(c["partial"] for c in cells.values())
    n_fail = sum(c["fail"] for c in cells.values())
    n_assert = sum(c["n_assert"] for c in cells.values())

    # ---- 落盘
    with (out / "cases.jsonl").open("w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    (out / "cells.json").write_text(
        json.dumps(
            {"fixtures_dir": str(FIXTURES), "wall_s": wall, "cells": cells},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = ["# fixtures trap-assertion summary\n"]
    lines.append(
        f"- assertions: **{n_pass}/{n_assert} pass**   "
        f"partial {n_partial}   fail {n_fail}   wall {wall}s"
    )
    lines.append("")
    lines.append("| fixture | parse | identity | chunks | pass/assert |")
    lines.append("|---|---|---|---|---|")
    for name, cell in cells.items():
        lines.append(
            f"| {name} | {cell['parse_ok']} | {cell['identity']} "
            f"| {cell['n_chunks']} | {cell['pass']}/{cell['n_assert']} |"
        )
    lines.append("")
    bad = [c for c in cases if c["status"] in ("fail", "partial")]
    if bad:
        lines.append("## non-pass assertions\n")
        lines.append("| case | status | detail |")
        lines.append("|---|---|---|")
        lines.extend(f"| {c['case']} | {c['status']} | {c['detail']} |" for c in bad)
        lines.append("")
    else:
        lines.append("## non-pass assertions\n\n(none)\n")
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"assertions {n_pass}/{n_assert} pass, partial {n_partial}, fail {n_fail}")
    for c in cases:
        print(f"  {c['case']}: {c['status']}  {c['detail'][:100]}")
    print(f"wrote {out}/cases.jsonl, cells.json, summary.md")


if __name__ == "__main__":
    main()
