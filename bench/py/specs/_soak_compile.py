"""soak compile 段叶——splice 重建树件（_rebuild/_ensure_translated/_main_rel/
_engine 单源，``_soak_fixloop`` 复用）+ base 归因臂折入的 compile stage。"""

from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path

from kernel import fsutil, vault

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs import _qmetrics as qp
from specs._shared import (
    _compile_judge,
    _ensure_kind,
    _gate,
    _last_done,
    _xlat_marker,
)
from texlate.compile.engine import route_project
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)

# ---------------------------------------------------------------- 小件共用
#
# _gate/_swap_in/_ensure_kind/_xlat_marker/_compile_judge/case_bridge 单源在
# specs/_shared.py（e2e_real/fixloop_bench 同款——勿再长本地副本）。


def _rebuild(zh: Path, splice: Path) -> None:
    """zh.- → splice.- 原样重建（旧 stagerun_lib.rebuild_splice 同式）。"""
    if splice.exists():
        shutil.rmtree(splice)
    fsutil.copy_mutating(zh, splice)


def _ensure_translated(ctx) -> tuple[Path | None, dict | None]:
    """(zh dir, marker_doc) — marker 选树：同 run 上游优先，无 marker
    回退 vault 已封副本。

    parse/xlat 共 zh 键域：上游 parse 实跑产的 zh.- 树无
    .xlat-arm.json，同 run xlat dedup 不再产物，下游 compile/fixloop
    拿到的是遮蔽 marker 载荷的 parse 树（regen-888 27 格
    not_translated 实证）。xlat 自己吃未标 parse 树走 _ensure_kind，
    不走这里。
    """
    zh = _ensure_kind(ctx, "zh")
    marker = _xlat_marker(zh) if zh is not None else None
    if marker is not None:
        return zh, marker
    with contextlib.suppress(OSError):
        if zh is not None:
            shutil.rmtree(zh)
    with contextlib.suppress(vault.VaultError):
        vault.restore(ctx.idc, ctx.arm, ctx.variant, ctx.paper_dir(), mode="copy")
    zh = ctx.upstream_asset_dir("zh")
    marker = _xlat_marker(zh) if zh is not None else None
    return zh, marker


def _main_rel(ctx, tree: Path) -> str | None:
    """main_rel 三段式：parse 账 metrics → zh.-/parse.json → find_main_tex。"""
    rec = _last_done(ctx, "parse")
    m = ((rec or {}).get("metrics") or {}).get("main_rel")
    if m:
        return str(m)
    zh = ctx.upstream_asset_dir("zh")
    pj = (zh / "parse.json") if zh is not None else None
    if pj is not None and pj.is_file():
        try:
            doc = json.loads(pj.read_text())
            if doc.get("main_rel"):
                return str(doc["main_rel"])
        except (json.JSONDecodeError, OSError):
            pass
    found = find_main_tex(tree)
    return found.relative_to(tree).as_posix() if found else None


def _engine(ctx, root: Path) -> str:
    """engine 三段式：params ≠ auto → parse 账 engine_resolved → route 兜底。"""
    eng = str(ctx.params.get("engine") or "xelatex")
    if eng != "auto":
        return eng
    rec = _last_done(ctx, "parse")
    m = ((rec or {}).get("metrics") or {}).get("engine_resolved")
    if m:
        return str(m)
    try:
        return route_project(root, prefer="xelatex").engines[0]
    except Exception:
        return "xelatex"


# ---------------------------------------------------------------- stage: compile


def _compile(ctx) -> dict:
    """splice.- 重建 + inject + judge；base 臂折进 metrics.base。

    base 先跑（src 直编归因臂）——zh 臂半途门控时本格仍带齐 base
    观测（旧两臂独立任务等价的覆盖面守恒）。
    """
    metrics: dict = {}
    timeout = float(ctx.params["timeout"])

    # ---- base 归因臂（src 原样直编，不 normalize 不 inject） -------------
    src = ctx.src_path()
    if src is not None:
        bmain = find_main_tex(src)
        if bmain is None:
            metrics["base"] = {
                "status": "reject",
                "code": "no_main_tex",
                "cat": "compile",
                "payload": classify_no_main(src) or "",
            }
        else:
            b_rel = bmain.relative_to(src).as_posix()
            bdir = ctx.paper_dir() / "build-base"
            if bdir.exists():
                shutil.rmtree(bdir)
            fsutil.copy_mutating(src, bdir)
            b_eng = _engine(ctx, src)
            b_tail = _compile_judge(bdir, b_rel, b_eng, timeout, expect_cjk=False)
            metrics["base"] = {
                "engine": b_eng,
                "main_rel": b_rel,
                **b_tail,
            }

    # ---- zh 臂 ------------------------------------------------------------
    zh, marker_doc = _ensure_translated(ctx)
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
    _rebuild(zh, splice)
    main_rel = _main_rel(ctx, splice)
    if not main_rel:
        return _gate(
            "reject", "no_main_tex", "compile", classify_no_main(splice) or "", metrics
        )
    eng = _engine(ctx, splice)
    metrics["engine"] = eng
    metrics["main_rel"] = main_rel
    try:
        metrics["inject"] = prepare_chinese(
            splice, main_rel, layout_marks=bool(ctx.params["marks"])
        )
    except InjectRejectError as e:
        metrics["verdict"] = {"status": "reject", "reasons": [e.reason]}
        return _gate("reject", "inject_reject", "inject", e.reason, metrics)
    # 0-chunk 主文档（includepdf 壳）无译文产出 → 不期待 CJK；
    # xlat 账缺席时保守默认 True。记入 metrics 供 fixloop 复判同口径。
    # 跨 run 域：xlat 本 run dedup 时 DONE 底账在前 run。
    xr = _last_done(ctx, "xlat")
    _tr = ((xr or {}).get("metrics") or {}).get("translate") or {}
    expect_cjk = _tr.get("chunks") != 0
    metrics["expect_cjk"] = expect_cjk
    tail = _compile_judge(splice, main_rel, eng, timeout, expect_cjk=expect_cjk)
    metrics.update(tail)
    v = tail["verdict"]
    if v["status"] in ("clean", "partial"):
        pdf = splice / Path(main_rel).with_suffix(".pdf")
        if not pdf.is_file():
            pdfs = [p for p in splice.glob("*.pdf") if p.is_file()]
            pdf = max(pdfs, key=lambda p: p.stat().st_mtime) if pdfs else None
        if pdf is not None:
            with contextlib.suppress(Exception):
                metrics["landmark"] = qp.landmark_metrics(pdf, splice)
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
