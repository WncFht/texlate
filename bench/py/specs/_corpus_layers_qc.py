"""specs._corpus_layers_qc — corpus_layers qc 段叶（层自检报告 + 配额达成判定）。

manifest vs select_stats/plan 配额对拍 → qc.md + layers_qc metric；
dup/incomplete/跨层撞 id 任一即 fail。
"""

from __future__ import annotations

import json
from collections import Counter

from kernel import lake

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs._corpus_layers_base import PROFILES, _dirs

# ---------------------------------------------------------------- qc


def _qc(ctx):
    d = _dirs(ctx)
    layer = d["layer"]
    plan = cc.load_plan(d["plan"])
    if plan is None and PROFILES.get(layer) is not None:
        ctx.emit_note(f"{d['plan'].name} 缺 — qc 无配额分母", level="warn")
        return "error"
    d["lwd"].mkdir(parents=True, exist_ok=True)
    rows = cc.read_jsonl(d["manifest"])
    ids = [r["id"] for r in rows]
    own = {cc.canon_id(str(i)) for i in ids}
    dup = [i for i, c in Counter(ids).items() if c > 1]
    by_cell = Counter(r.get("stratum_cell") for r in rows)
    incomplete = [
        r["id"]
        for r in rows
        if not lake.is_complete(r["id"], source=r.get("channel") or "arxiv")
    ]
    # 跨层撞 id：本层在册 id 出现在他层 manifest（分母污染）
    overlap = sorted(own & (cc.existing_ids(d["corpus"]) - own))
    stats = (
        json.loads(d["select_stats"].read_text()) if d["select_stats"].exists() else {}
    )
    quotas = (plan or {}).get("quotas") or {}
    # 分母：select_stats 两段式账目（flag:X+failmine_fill 也在内）优先，
    # 未跑 extract 时退回 plan 配额
    denom = {c: s.get("quota", 0) for c, s in stats.items()} if stats else quotas
    lines = [
        f"# {layer} 层自检",
        "",
        f"- manifest_{layer} 入库 **{len(rows)}**",
        f"- id 重复: {sorted(dup) or '无'}",
        f"- 跨层撞 id: {overlap[:10] or '无'} (n={len(overlap)})",
        f"- lake cell 不完整: {incomplete[:10] or '无'} (n={len(incomplete)})",
        "",
        "| cell | 实收 | quota | avail | deficit |",
        "| --- | --- | --- | --- | --- |",
    ]
    if stats:
        for cell, s in sorted(stats.items()):
            lines.append(
                f"| {cell} | {by_cell.get(cell, 0)} | {s.get('quota', '-')} "
                f"| {s.get('avail', '-')} | {s.get('deficit', '-')} |"
            )
    else:
        for cell, q in sorted(quotas.items()):
            lines.append(f"| {cell} | {by_cell.get(cell, 0)} | {q} | - | - |")
    d["qc_md"].write_text("\n".join(lines) + "\n")
    attained = sum(1 for c, q in denom.items() if by_cell.get(c, 0) >= q)
    ctx.emit(
        {
            "metric": "layers_qc",
            "layer": layer,
            "manifest_rows": len(rows),
            "cells_attained": attained,
            "cells_total": len(denom),
            "dup_ids": len(dup),
            "incomplete_cells": len(incomplete),
            "overlap_ids": len(overlap),
            "qc_md": str(d["qc_md"]),
        }
    )
    if dup or incomplete or overlap:
        return "fail"
    return "ok" if attained == len(denom) else "fail"
