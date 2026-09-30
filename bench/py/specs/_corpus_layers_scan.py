"""specs._corpus_layers_scan — corpus_layers scan 段叶（plan items → features 批扫）。

recent-only 层 ok-noop；plan 缺/不可解析 → error（retriable）。
"""

from __future__ import annotations

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs._corpus_layers_base import PROFILES, _dirs

# ---------------------------------------------------------------- scan


def _scan(ctx):
    d = _dirs(ctx)
    layer = d["layer"]
    if PROFILES.get(layer) is None:
        ctx.emit(
            {
                "metric": "layers_scan",
                "layer": layer,
                "recent_only": True,
                "items": 0,
            }
        )
        return "ok"
    plan = cc.load_plan(d["plan"])
    if plan is None:
        ctx.emit_note(f"{d['plan'].name} 缺/不可解析 — 先跑 plan", level="warn")
        return "error"
    items = plan["items"]
    limit = int(ctx.params.get("limit") or 0)
    if limit:
        items = items[:limit]
    errs = cc.scan_batch(items, d["dirs"], int(ctx.params["jobs"]), tag=f"[{layer}]")
    ctx.emit(
        {
            "metric": "layers_scan",
            "layer": layer,
            "items": len(items),
            "failed": len(errs),
            "failed_items": errs[:20],
        }
    )
    if not errs:
        return "ok"
    return "partial" if len(errs) < len(items) else "error"
