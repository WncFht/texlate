"""e2e_real compile 段叶——zh.- → splice.- → inject → xelatex+judge。"""

from __future__ import annotations

import shutil

from kernel import fsutil

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs._shared import (
    _compile_judge,
    _ensure_kind,
    _gate,
    _last_done,
    _xlat_marker,
)
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)

# ---------------------------------------------------------------- stage: compile


def _compile(ctx) -> dict:
    """zh.- → splice.- → inject → xelatex+judge（旧 pipe_xel_condition
    的 inject+compile 段）。expect_cjk 读 xlat 账 translate.chunks。"""
    metrics: dict = {"engine": "xelatex"}
    zh = _ensure_kind(ctx, "zh")
    marker_doc = _xlat_marker(zh) if zh is not None else None
    if marker_doc is None:
        return _gate(
            "skip",
            "not_translated",
            "upstream",
            "zh.- missing or no .xlat-arm.json",
            metrics,
        )
    metrics["xlat_ts"] = marker_doc.get("ts")
    splice = ctx.asset_dir("splice")
    if splice.exists():
        shutil.rmtree(splice)
    fsutil.copy_mutating(zh, splice)
    rrec = _last_done(ctx, "route") or {}
    main_rel = (rrec.get("metrics") or {}).get("main_rel")
    if not main_rel:
        found = find_main_tex(splice)
        if found is None:
            return _gate(
                "reject",
                "no_main_tex",
                "compile",
                classify_no_main(splice) or "",
                metrics,
            )
        main_rel = found.relative_to(splice).as_posix()
    metrics["main_rel"] = main_rel
    timeout = float(ctx.params["timeout"])
    try:
        metrics["inject"] = prepare_chinese(
            splice, main_rel, layout_marks=bool(ctx.params["marks"])
        )
    except InjectRejectError as e:
        metrics["verdict"] = {"status": "reject", "reasons": [e.reason]}
        metrics["reject_at"] = "inject"
        return _gate("reject", "inject_reject", "inject", e.reason, metrics)
    # 0-delivered 篇目不期待 CJK（旧 chunks!=0 怪癖逐字保留）；xlat 账
    # 缺席（dedup 底账在前 run 经 _last_done 全域读到）保守 True。
    xr = _last_done(ctx, "xlat")
    _tr = ((xr or {}).get("metrics") or {}).get("translate") or {}
    expect_cjk = _tr.get("chunks") != 0
    metrics["expect_cjk"] = expect_cjk
    tail = _compile_judge(splice, main_rel, "xelatex", timeout, expect_cjk=expect_cjk)
    metrics.update(tail)
    v = tail["verdict"]
    out = {
        "status": v["status"],
        "metrics": metrics,
        "sig": benchlib.verdict_sig(v, tail["compile"].get("first_error")),
    }
    if v["status"] not in ("clean", "partial"):
        out["errors"] = [
            {
                "code": v.get("category") or "compile_fail",
                "cat": v.get("category"),
                "payload": v.get("payload"),
            }
        ]
    elif v.get("category"):
        out["errors"] = [
            {
                "code": v["category"],
                "cat": v["category"],
                "payload": v.get("payload"),
            }
        ]
    return out
