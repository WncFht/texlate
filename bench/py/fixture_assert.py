#!/usr/bin/env python3
r"""fixture_assert — B2 陷阱断言跑分器: bench/fixtures/*.tex → 契约三件套.

断言矩阵来自 tests/test_bench_regression.py (spike miniscanner_test 移植,
跑在 texlate.latex 产品解析器上); 本脚本只做计时执行 + 契约产出落盘.
覆盖: tricky.tex T01–T29 (26 条 + _meta), tricky-209.tex 3 条 + parse_ok,
tricky-multi T14 ×4, xlat-traps.tex @X1–@X4.

用法:
  uv run python bench/py/fixture_assert.py --out DIR

产出 (docs/10 §统一产出契约): OUT/cases.jsonl (逐断言明细) +
OUT/cells.json (逐 fixture 聚合) + OUT/summary.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

import test_bench_regression as tbr


def main() -> None:
    ap = argparse.ArgumentParser(description="fixtures trap-assertion bench")
    ap.add_argument("--out", required=True, type=Path, help="契约产出目录")
    args = ap.parse_args()
    out = args.out if args.out.is_absolute() else Path.cwd() / args.out
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    cases: list[dict] = []
    cells: dict[str, dict] = {}

    # 逐 fixture 现跑 (拿 wall_ms); 断言函数与 pytest 侧共享同一份
    parsed = {
        name: tbr.run_fixture(name, path, top_dir=tbr._FIXTURE_TOPDIR.get(name))
        for name, path in tbr.FIXTURE_FILES
    }

    asserts: dict[str, dict] = {}
    t = parsed["tricky.tex"]
    asserts["tricky.tex"] = (
        tbr.assert_tricky(t.res, t.recon, t.recon_fake)
        if t.ok and t.res is not None
        else {"_parse": {"status": "fail", "detail": t.error}}
    )
    t2 = parsed["tricky-209.tex"]
    asserts["tricky-209.tex"] = tbr.assert_209(t2.res if t2.ok else None, t2.recon)
    tm = parsed["tricky-multi/main.tex"]
    asserts["tricky-multi/main.tex"] = (
        tbr.assert_multi(tm.recon)
        if tm.ok
        else {"_parse": {"status": "fail", "detail": tm.error}}
    )
    tx = parsed["xlat-traps.tex"]
    asserts["xlat-traps.tex"] = (
        tbr.assert_xlat(tx.res)
        if tx.ok
        else {"_parse": {"status": "fail", "detail": tx.error}}
    )
    tw = parsed["tricky-w.tex"]
    asserts["tricky-w.tex"] = (
        tbr.assert_w(tw.res, tw.recon, tw.recon_fake)
        if tw.ok
        else {"_parse": {"status": "fail", "detail": tw.error}}
    )
    t73 = parsed["tricky-w73/main/main.tex"]
    asserts["tricky-w73/main/main.tex"] = (
        tbr.assert_w73(t73.res)
        if t73.ok
        else {"_parse": {"status": "fail", "detail": t73.error}}
    )
    te = parsed["tricky-wenc.tex"]
    asserts["tricky-wenc.tex"] = (
        tbr.assert_wenc(te.res)
        if te.ok
        else {"_parse": {"status": "fail", "detail": te.error}}
    )
    td = parsed["tricky-dollar.tex"]
    asserts["tricky-dollar.tex"] = (
        tbr.assert_dollar(td.res, td.recon, td.recon_fake)
        if td.ok
        else {"_parse": {"status": "fail", "detail": td.error}}
    )
    tmk = parsed["tricky-mask.tex"]
    asserts["tricky-mask.tex"] = (
        tbr.assert_mask(tmk.res, tmk.recon, tmk.recon_fake)
        if tmk.ok
        else {"_parse": {"status": "fail", "detail": tmk.error}}
    )

    for name, p in parsed.items():
        if p.ok:
            status, _ratio, _first = tbr.classify_recon(p.flat, p.recon)
            identity = {"identical": "strict"}.get(status, status)
            n_chunks = len(p.res.chunks) if p.res else 0
            n_ph = len(p.res.ph_map) if p.res else 0
        else:
            identity, n_chunks, n_ph = None, None, None
        cell = {
            "parse_ok": p.ok,
            "wall_ms": p.wall_ms,
            "error": p.error or None,
            "identity": identity,
            "n_chunks": n_chunks,
            "n_placeholders": n_ph,
            "n_assert": 0,
            "pass": 0,
            "partial": 0,
            "fail": 0,
            "info": 0,
        }
        for aid, v in asserts.get(name, {}).items():
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
                    "parse_ok": p.ok,
                    "wall_ms": p.wall_ms,
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
            {"fixtures_dir": str(tbr.FIXTURES), "wall_s": wall, "cells": cells},
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
