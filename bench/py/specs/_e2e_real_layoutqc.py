"""e2e_real layoutqc 段叶——T0 版面质检汇（needs-free 末段 mutates 格）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from specs import _bootstrap

_bootstrap.ensure()

from specs._layoutqc import qc_paper
from specs._shared import _ensure_kind, _last_done

# ---------------------------------------------------------------- stage: layoutqc


def _layoutqc(ctx) -> dict:
    """T0 版面质检汇（needs-free，mutates=["layoutqc"]）。

    读 splice zh 产物（pdf/log/txlm）+ build-base en 对照 + src 期望
    面 → specs._layoutqc.qc_paper。findings 全量进 metrics + 逐条
    errors（cat='layoutqc'），sig 取首条。qc.json + 双臂 .txlm 拷进
    layoutqc.- 资产——harvest 以本格为末段 mutates 把质检面包进
    vault（保留政策的诊断料）。本格只测不改：永远不断言 zh 不合格，
    clean/ok 皆 terminal，缺陷密度全交给 triage 聚合。"""
    comp = _last_done(ctx, "compile") or {}
    cm = comp.get("metrics") or {}
    main_rel = cm.get("main_rel")
    if not main_rel:
        main_rel = ((_last_done(ctx, "route") or {}).get("metrics") or {}).get(
            "main_rel"
        )
    splice = _ensure_kind(ctx, "splice")
    if splice is None or not main_rel:
        return {
            "status": "reject",
            "sig": "declined:qc_no_input",
            "metrics": {
                "gate": "qc_no_input",
                "has_splice": splice is not None,
                "has_main_rel": bool(main_rel),
            },
        }
    base_dir = ctx.paper_dir() / "build-base"
    if not base_dir.is_dir():
        base_dir = None
    src = ctx.src_path()
    out_dir = ctx.asset_dir("layoutqc")
    qc = qc_paper(
        splice_dir=splice,
        main_rel=main_rel,
        base_dir=base_dir,
        src_dir=src,
        marks_era=bool(ctx.params["marks"]),
        # compile metrics 的 inject.layout_marks 是 marks 注入的账本
        # 口径——marks_absent 出处闸（缺席预期 vs 真断链）。
        marks_expected=(
            None if not cm else (cm.get("inject") or {}).get("layout_marks", 0) >= 1
        ),
        flag_dir=out_dir / "flagged",
    )
    findings = qc["findings"]
    metrics = {
        "main_rel": main_rel,
        "n_findings": len(findings),
        "qc_tier": qc["qc_tier"],
        "sig_counts": qc["sig_counts"],
        "flagged_pages": qc["flagged_pages"],
        "qc": qc["metrics"],
    }
    # 质检包：qc.json + 双臂 .txlm（<stem>.zh.txlm / .base.txlm）
    stem = Path(main_rel).stem
    try:
        (out_dir / "qc.json").write_text(
            json.dumps(
                {
                    "idc": ctx.idc,
                    "main_rel": main_rel,
                    "qc_tier": qc["qc_tier"],
                    "sig_counts": qc["sig_counts"],
                    "flagged_pages": qc["flagged_pages"],
                    "findings": findings,
                    "metrics": qc["metrics"],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        zh_t = splice / Path(main_rel).parent / f"{stem}.txlm"
        if zh_t.exists():
            shutil.copy2(zh_t, out_dir / f"{stem}.zh.txlm")
        if base_dir is not None:
            b_t = base_dir / Path(main_rel).parent / f"{stem}.txlm"
            if b_t.exists():
                shutil.copy2(b_t, out_dir / f"{stem}.base.txlm")
    except OSError as e:
        metrics["qc_write_error"] = str(e)
    status = "clean" if not findings else "ok"
    out = {
        "status": status,
        "metrics": metrics,
        "sig": findings[0]["sig"] if findings else "qc:clean",
    }
    if findings:
        out["errors"] = [
            {
                "code": f["sig"],
                "cat": "layoutqc",
                "payload": json.dumps(f, ensure_ascii=False)[:300],
            }
            for f in findings
        ]
    return out
