"""e2e_real route 段叶——src 物化 → find_main_tex → route_project。"""

from __future__ import annotations

from specs import _bootstrap

_bootstrap.ensure()

from specs._e2e_real_frame import _frame_sha
from specs._shared import _gate
from texlate.compile.engine import route_project
from texlate.compile.inject import classify_no_main, find_main_tex

# ---------------------------------------------------------------- stage: route


def _route(ctx) -> dict:
    """src 物化 → find_main_tex → route_project；meta 四键+main_rel+ 帧戳
    进 metrics（下游经 _last_done 读）。三拒一律 reject+reject_at='route'。"""
    cell = ctx.cell
    metrics: dict = {
        "layer": cell.get("layer"),
        "cat_group": cell.get("cat_group"),
        "era": cell.get("era"),
        "bytes": cell.get("bytes"),
        "frame": f"frm-{_frame_sha()}",
    }
    src = ctx.src_path()
    if src is None:
        metrics["reject_at"] = "route"
        return _gate(
            "reject", "no_extracted", "route", "lake cell unfetchable", metrics
        )
    main = find_main_tex(src)
    if main is None:
        sub = classify_no_main(src)
        metrics["reject_at"] = "route"
        metrics["no_main_sub"] = sub
        return _gate("reject", "no_main_tex", "route", sub or "", metrics)
    main_rel = main.relative_to(src).as_posix()
    metrics["main_rel"] = main_rel
    route = route_project(src)
    metrics["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    if route.reject:
        metrics["reject_at"] = "route"
        return _gate("reject", "route_reject", "route", route.reject, metrics)
    return {"status": "ok", "metrics": metrics}
