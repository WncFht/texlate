"""e2e_real base 段叶——base-xel 归因臂（src 原样直编）。"""

from __future__ import annotations

import shutil

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs._shared import _gate, _last_done
from texlate.compile.inject import classify_no_main, find_main_tex
from texlate.compile.marks import inject_layout_marks
from texlate.e2e import base_condition

# ---------------------------------------------------------------- stage: base


def _base(ctx) -> dict:
    """base-xel 归因臂（旧 base_xel_condition）：src 原样直编。

    onfail 抑制只读跨 run 账（同 run topo 序 base 先于 xlat——无账照跑
    =onfail→always 的文档化漂移）：xlat oversize 或 compile clean →
    reject+gate 分桶。"""
    mode = str(ctx.params.get("base") or "onfail")
    metrics: dict = {"mode": mode, "engine": "xelatex"}
    if mode == "never":
        return {
            "status": "reject",
            "sig": "declined:base_never",
            "metrics": {**metrics, "gate": "base_never"},
        }
    if mode == "onfail":
        xr = _last_done(ctx, "xlat")
        tr = ((xr or {}).get("metrics") or {}).get("translate") or {}
        if tr.get("oversize"):
            return {
                "status": "reject",
                "sig": "declined:oversize",
                "metrics": {**metrics, "gate": "oversize"},
            }
        cr = _last_done(ctx, "compile")
        cv = ((cr or {}).get("metrics") or {}).get("verdict") or {}
        if cv.get("status") == "clean":
            return {
                "status": "reject",
                "sig": "declined:compile_clean",
                "metrics": {**metrics, "gate": "compile_clean"},
            }

    src = ctx.src_path()
    if src is None:
        return _gate(
            "error", "no_extracted", "upstream", "lake cell unfetchable", metrics
        )
    rrec = _last_done(ctx, "route") or {}
    main_rel = (rrec.get("metrics") or {}).get("main_rel")
    main = find_main_tex(src)
    if main is None:
        return {
            "status": "reject",
            "sig": "declined:no_main_tex",
            "metrics": {
                **metrics,
                "gate": "no_main_tex",
                "no_main_sub": classify_no_main(src),
            },
        }
    if not main_rel:
        main_rel = main.relative_to(src).as_posix()
    metrics["main_rel"] = main_rel
    work = ctx.paper_dir() / "build-base"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src, work, ignore=benchlib.copytree_ignore())
    # en 基线臂同样打 marks——跨臂浮体对照（drift/lost/inversion）的真值源
    if ctx.params["marks"]:
        metrics["base_marks"] = inject_layout_marks(work)
    rec = base_condition(work, "xelatex", main_rel, float(ctx.params["timeout"]))
    metrics.update(rec)
    v = rec.get("verdict") or {}
    out = {
        "status": v.get("status") or "fail",
        "metrics": metrics,
        "sig": benchlib.verdict_sig(v, (rec.get("compile") or {}).get("first_error")),
    }
    if v.get("status") not in ("clean", "partial"):
        out["errors"] = [
            {
                "code": v.get("category") or "compile_fail",
                "cat": v.get("category"),
                "payload": v.get("payload"),
            }
        ]
    return out
