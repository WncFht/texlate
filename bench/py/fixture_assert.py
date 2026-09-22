#!/usr/bin/env python3
r"""fixture_assert — B2 陷阱断言跑分器: bench/fixtures/*.tex → 契约三件套.

断言矩阵来自 bench/py/specs/_fixture_matrix.py (spike miniscanner_test 移植,
跑在 texlate.latex 产品解析器上); 本脚本只做计时执行 + 契约产出落盘.
覆盖 9 fixture: tricky.tex T01–T29 (26 条 + _meta), tricky-209.tex
(3 条 + parse_ok; parse 失败也跑 assert_209(None)), tricky-multi/main.tex
T14 ×4, xlat-traps.tex @X1–@X4, tricky-w.tex, tricky-w73/main/main.tex,
tricky-wenc.tex, tricky-dollar.tex, tricky-mask.tex.

用法:
  uv run python bench/py/fixture_assert.py --out DIR

产出 (docs/spec/benchmark.md 统一产出契约): OUT/cases.jsonl (逐断言明细) +
OUT/cells.json (逐 fixture 聚合) + OUT/summary.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from specs import _fixture_matrix as fm


def _guarded(fn, *fields: str):
    """p.ok 门包装：parse 失败 → 单条 ``_parse`` fail 行，不跑断言函数。

    ``fields`` 是 FixtureScan 的字段名序——按序解出传给 ``fn``。
    """

    def run(p: fm.FixtureScan) -> dict:
        if not p.ok:
            return {"_parse": {"status": "fail", "detail": p.error}}
        return fn(*(getattr(p, f) for f in fields))

    return run


#: fixture → 断言函数分派表（assert 函数与 pytest 侧共享同一份）。
#: 表外 fixture = 零断言格——下方构建 asserts 时 stderr 显式化（cells 记
#: n_assert=0，summary 里直接可见）。
#: tricky-209 有意不走 _guarded：assert_209 自身处理 res=None（parse_ok
#: 断言覆盖解析失败路径）。
_ASSERTS = {
    "tricky.tex": _guarded(fm.assert_tricky, "res", "recon", "recon_fake"),
    "tricky-209.tex": lambda p: fm.assert_209(p.res if p.ok else None, p.recon),
    "tricky-multi/main.tex": _guarded(fm.assert_multi, "recon"),
    "xlat-traps.tex": _guarded(fm.assert_xlat, "res"),
    "tricky-w.tex": _guarded(fm.assert_w, "res", "recon", "recon_fake"),
    "tricky-w73/main/main.tex": _guarded(fm.assert_w73, "res"),
    "tricky-wenc.tex": _guarded(fm.assert_wenc, "res"),
    "tricky-dollar.tex": _guarded(fm.assert_dollar, "res", "recon", "recon_fake"),
    "tricky-mask.tex": _guarded(fm.assert_mask, "res", "recon", "recon_fake"),
}


def main() -> None:
    ap = argparse.ArgumentParser(description="fixtures trap-assertion bench")
    ap.add_argument("--out", required=True, type=Path, help="契约产出目录")
    args = ap.parse_args()
    out = args.out if args.out.is_absolute() else Path.cwd() / args.out
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    cases: list[dict] = []
    cells: dict[str, dict] = {}

    # 复用矩阵模块级测量包 (fm import 时已逐 fixture parse+重建，
    # wall_ms 随包带); 断言函数与 pytest 侧共享同一份
    parsed = fm._PARSED

    asserts: dict[str, dict] = {}
    for name, p in parsed.items():
        fn = _ASSERTS.get(name)
        if fn is None:
            print(f"  note: {name} 无断言映射——cells 记 0-assert", file=sys.stderr)
            continue
        asserts[name] = fn(p)

    for name, p in parsed.items():
        if p.ok:
            status, _ratio, _first = fm.classify_recon(p.res.vtex, p.recon)
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
            {"fixtures_dir": str(fm.FIXTURES), "wall_s": wall, "cells": cells},
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
