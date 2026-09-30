"""soak fixloop 段叶——compile 非 clean 格修复（恒自 zh.- 重建 splice.-）。"""

from __future__ import annotations

import shutil
import time

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs import _fixloop as flb  # 冷 usertree 引擎配方单源
from specs._shared import (
    PaidEscape,
    SessionTranslator,
    _gate,
    _last_done,
    case_bridge,
)
from specs._soak_compile import _ensure_translated, _main_rel, _rebuild
from texlate.compile.engine import XelatexEngine
from texlate.compile.fixloop import Ruleset, fixloop
from texlate.compile.fixloop.llm_hook import make_llm_hook
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    prepare_chinese,
)
from texlate.repair import ResProxy

_ON_PRED: dict[str, object] = {
    "fail": lambda c: c.get("status") == "fail",
    "nonclean": lambda c: c.get("status") in {"fail", "partial"},
    "misschar": lambda c: benchlib.misschar_partial(
        c.get("status"), (c.get("metrics") or {}).get("verdict") or {}
    ),
    "clean": lambda c: c.get("status") == "clean",
    # reject/skip 无有效 splice 树——post-judge 编译被拒英文树会虚增
    # union-pdf（1e 审计 +414 phantom 上限）；error(harness 崩) 树态不定同排。
    "all": lambda c: c.get("status") not in {"reject", "skip", "error"},
}

# ---------------------------------------------------------------- stage: fixloop


def _fixloop(ctx) -> dict:
    """compile 非 clean 格修复：恒自 zh.- 重建 splice.-（rerun-only），
    冷 usertree + Ruleset + ResProxy + post 复判同 compile 刻度。"""
    t0 = time.monotonic()
    # on 谓词读域 = _needs_eval 同域（跨全 run 末条 DONE）——本 run
    # upstream_rec 在 compile dedup 的续跑 run 里返 None，会误判成
    # 「无修必要」白放行。
    comp_rec = _last_done(ctx, "compile") or {}
    want = _ON_PRED[str(ctx.params.get("on") or "fail")]
    if not want(comp_rec):
        # on 谓词不中 = 「本轮无修必要」——ok + ran=False 终态触发
        # §3.5 harvest，把上游付费字节封进 vault；skip 是 retriable
        # 会让 zh.-/state.- 滞留 work/ 等 sweep/adopt 捞。
        return {
            "status": "ok",
            "metrics": {
                "mode": ctx.params.get("on"),
                "fixloop_ran": False,
                "on_gate": comp_rec.get("status"),
                "compile_fp": benchlib.compile_fp(comp_rec) if comp_rec else None,
            },
        }

    zh, marker_doc = _ensure_translated(ctx)
    if marker_doc is None:
        return _gate(
            "skip", "not_translated", "upstream", "zh.- missing or no .xlat-arm.json"
        )
    splice = ctx.asset_dir("splice")
    _rebuild(zh, splice)
    main_rel = _main_rel(ctx, splice)
    if not main_rel:
        return _gate("error", "no_main_tex", "fixloop", classify_no_main(splice) or "")
    metrics: dict = {"splice_rebuilt": True}
    try:
        metrics["inject"] = prepare_chinese(
            splice, main_rel, layout_marks=bool(ctx.params["marks"])
        )
    except InjectRejectError as e:
        metrics["verdict"] = {"status": "reject", "reasons": [e.reason]}
        return _gate("reject", "inject_reject", "inject", e.reason, metrics)

    texmf = ctx.paper_dir() / "_texmf"
    if texmf.exists():
        shutil.rmtree(texmf)  # 冷启动——防半成品 usertree 偏暖
    eng = flb._make_engine("xelatex", texmf, splice)
    # baseline_dir 逐格注入：params 在共享 flb.RS 上无法按 pid 注入，
    # 故每格 Ruleset.load() 后按 transform 名注入 src/ 原件树。
    src = ctx.src_path()
    rs = flb.RS
    if src is not None and src.is_dir():
        rs = Ruleset.load()
        for rule in rs.rules:
            act = rule.raw.get("action") or {}
            if act.get("kind") == "builtin_transform" and act.get("function") in {
                "restore_support_from_src",
                "slot_arg_revert",
            }:
                act.setdefault("params", {})["baseline_dir"] = str(src)
    timeout = float(ctx.params["timeout"])
    llm_hook = None
    if ctx.params.get("llm"):
        llm_hook = make_llm_hook(
            translator=SessionTranslator(ctx.gateway(), str(ctx.params["model"]))
        )
    try:
        proxy = ResProxy(eng)
        cell = fixloop(
            splice,
            proxy,
            ruleset=rs,
            engine_name="xelatex",
            main_rel=main_rel,
            corpus_id=ctx.idc,
            cond="fixloop",
            runner=flb._texmf_runner(texmf),
            case_sink=case_bridge(ctx),
            llm_hook=llm_hook,
            compile_timeout=timeout,
        )
        fix_last = proxy.last
    except PaidEscape as e:
        raise e.orig from e  # 拆舱交内核——harness_crash 兜底绝不收付费族
    except Exception as e:
        cell = {
            "project": ctx.idc,
            "engine": "xelatex",
            "verdict": f"harness_crash:{type(e).__name__}",
            "log_excerpt": str(e)[:500],
            "rounds": [],
            "actions": [],
        }
        fix_last = None
    cell_wall = round(time.monotonic() - t0, 1)
    # post 复判吃 fixloop 末轮 CompRes——与产品侧 res = fix_last or
    # first 同口径；兜底 fresh-compile 仅早退/崩溃/主档错位形。
    if fix_last is not None and cell.get("main") == main_rel:
        res = fix_last
        post_src = "fixloop_last"
    else:
        jeng = XelatexEngine(
            halt_on_error=False, texmfhome=texmf, repository=flb.TUNA_TLNET
        )
        res = jeng.compile(splice, main_rel, timeout=timeout, sandbox=False)
        post_src = "fresh_compile"
    expect_cjk = (comp_rec.get("metrics") or {}).get("expect_cjk", True)
    tail = benchlib.judge_dict(res, expect_cjk=expect_cjk)

    rounds = cell.get("rounds") or []
    fv = str(cell.get("verdict") or "?")
    fcat, fpay = benchlib.fixloop_attr(rounds, fv, cell.get("final_cat"))
    v = tail["verdict"]
    csb = comp_rec.get("status")
    tail["regressed"] = benchlib.STATUS_RANK.get(
        str(v["status"] or ""), -1
    ) < benchlib.STATUS_RANK.get(str(csb or ""), -1)
    actions = cell.get("actions") or []
    metrics.update(
        {
            "mode": ctx.params.get("on"),
            "fixloop_ran": True,
            "compile_status_before": csb,
            "compile_fp": benchlib.compile_fp(comp_rec) if comp_rec else None,
            "fixloop_verdict": fv,
            "final_cat": fcat,
            "rounds": len(rounds),
            "n_actions": len(actions),
            "rules_fired": list(
                dict.fromkeys(str(a["rule"]) for a in actions if a.get("rule"))
            ),
            "gate_fired": list(cell.get("gate_fired") or []),
            "installed": cell.get("installed") or [],
            "floor_restored": bool(cell.get("floor_restored")),
            "fixloop_wall_s": cell_wall,
            "post_src": post_src,
            "post": tail,
        }
    )
    out = {
        "status": v["status"],
        "metrics": metrics,
        "sig": benchlib.fixloop_sig(fv, fcat, fpay),
    }
    if v["status"] != "clean":
        out["errors"] = [{"code": fv, "cat": fcat, "payload": fpay}]
    return out
