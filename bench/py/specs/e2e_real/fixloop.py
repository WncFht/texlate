"""e2e_real fixloop 段叶——needs-free 收割汇 + wanted 闸（_want_fix/_qc_wanted）。

monkeypatch 缝（seams.md §1 口径）：tests ``setattr(er, "fixloop")``/
``setattr(er, "XelatexEngine")`` 钉在门面命名空间——本叶内经 ``_er.``
属性读面晚绑定回取，补丁照常触达（叶内 ``from  import`` 直绑会被
静默旁路）。``flb``/``benchlib`` 是共享模块对象，补丁直落其属性即达。
"""

from __future__ import annotations

import shutil
import time

from kernel import fsutil

import specs.e2e_real as _er
from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs import _fixloop as flb  # 冷 usertree 引擎配方单源
from specs._shared import (
    PaidEscape,
    _ensure_kind,
    _gate,
    _last_done,
    _last_row,
    _swap_in,
    case_bridge,
)
from texlate.compile.fixloop import Ruleset
from texlate.compile.inject import classify_no_main, find_main_tex

# ---------------------------------------------------------------- stage: fixloop


def _want_fix(mode: str, compile_status, verdict: dict, reject_at) -> bool:
    """旧 ``_want_fix`` 谓词的 status 面平移：mode=never/verdict None/
    reject/reject_at → False；always|fail → True；partial 且
    (misschar_partial 或 n_errors>0) → True。

    旧读 ``rec['pipe-xel'].verdict.status``；v2 读 compile 账 metrics
    （verdict+reject_at 同位——inject 拒绝走 reject_at='inject' 不救，
    无 ctex 的 CJK 注定 fail）。版面重缺陷的质检补票不在本谓词——
    归 ``_fixloop`` 调用点的 ``_qc_wanted``（onfail 限定）。
    """
    v = compile_status
    if v is None or v == "reject" or reject_at or mode == "never":
        return False
    if mode == "always" or v == "fail":
        return True
    return v == "partial" and (
        benchlib.misschar_partial(v, verdict) or (verdict.get("n_errors") or 0) > 0
    )


#: wanted 闸的质检补票阈值（sig→触发下限）：编译 clean 但版面有重缺陷
#: 的格子由此进修复环——260 篇探针批实证 23 篇 overfull 无人接。
_QC_WANTED_MIN = {
    "layout:overfull": 1,
    "layout:float_lost": 1,
    "geo_margin_breach": 3,
    "geo_text_overlap": 3,
}


def _qc_wanted(ctx) -> dict:
    """跨 run layoutqc 账的重缺陷命中集 ``{sig: count}``（无命中→{}）。

    topo 上 layoutqc 在 fixloop 之后跑——本 run 内质检账尚未立，本闸
    吃的是上一轮 run 留下的 ``metrics.sig_counts``：本轮质检喂下一轮
    修复，设计内口径。钉 ``status='ok'`` 而非末条 DONE——declined:
    qc_no_input 闸行无 sig_counts，会遮蔽早先真命中（verify 实证）。
    """
    qc = _last_row(ctx, "layoutqc", status="ok") or {}
    counts = (qc.get("metrics") or {}).get("sig_counts")
    if not isinstance(counts, dict):
        return {}
    out = {}
    for sig, lo in _QC_WANTED_MIN.items():
        n = counts.get(sig)
        if isinstance(n, (int, float)) and not isinstance(n, bool) and n >= lo:
            out[sig] = n
    return out


def _fixloop(ctx) -> dict:
    """needs-free 收割汇：fn 内三段闸（route_dead / no_compile / flux）
    后再 _want_fix 谓词——decline 一律 reject+gate 分桶（DONE 触发
    §3.5 harvest，上游付费字节封 vault 不滞留 work/）。

    _want_fix 不买时（mode=onfail ∧ compile∈{clean,ok} ∧ 无 reject_at
    限定）补查跨 run layoutqc 末条 ok 账的 ``sig_counts``——命中
    ``_QC_WANTED_MIN`` 重缺陷即视为 wanted 续走（metrics 记
    qc_wanted）；inject 拒绝与 compile reject 不吃补票。layoutqc
    topo 在本格之后，本 run 质检账未立是常态：闸吃上一轮 run 立的
    账，本轮质检喂下一轮修复。

    旧 ``pipe_fix_condition``：copy splice → 冷 usertree fixloop
    （halt_on_error=True + tlpdb 影子 + _NoSandbox + TUNA runner）→
    halt_on_error=False 复判 → 修复树 swap 回 splice.-。llm_hook 恒
    None（付费面归 sibling spec——paid 是静态旗标）。
    """
    t0 = time.monotonic()
    mode = str(ctx.params.get("fixloop") or "onfail")

    def _decline(gate: str, extra: dict | None = None) -> dict:
        return {
            "status": "reject",
            "sig": f"declined:{gate}",
            "metrics": {
                "gate": gate,
                "mode": mode,
                "fixloop_ran": False,
                **(extra or {}),
            },
        }

    # 上游账三段闸——needs-free 格的恒久性判读全在 fn 内：
    rr = _last_done(ctx, "route")
    if rr is not None and rr.get("status") != "ok":
        return _decline("route_dead", {"route_status": rr.get("status")})
    comp_rec = _last_done(ctx, "compile")
    if comp_rec is None:
        xr = _last_done(ctx, "xlat")
        if xr is not None and xr.get("status") in {"fail", "reject"}:
            # 链永死（xlat 终态败 → compile 永不立账）——收割 state.-。
            return _decline("no_compile", {"xlat_status": xr.get("status")})
        # 上游仍在 flux（error/skip 可续）——retriable 不固化 decline。
        # 文案须带末态：compile 行可能已 error/skip 落账（重试穷尽前
        # 的瞬态），「in flight」把终态误读成竞态（e2e_real-2 六例）。
        last_c = _last_row(ctx, "compile")
        last_s = (last_c or {}).get("status") or "absent"
        return _gate(
            "error",
            "compile_flux",
            "upstream",
            f"compile has no DONE row (last={last_s})",
        )
    cm = comp_rec.get("metrics") or {}
    cst = comp_rec.get("status")
    qc_hit: dict = {}
    if not _want_fix(mode, cst, cm.get("verdict") or {}, cm.get("reject_at")):
        # compile 账不买但版面有重缺陷 → 跨 run 质检账补票；只在「编译
        # 本身干净」（clean/ok 且无 reject_at）时救——inject 拒绝与
        # compile reject 不吃补票（前者 _want_fix 口径本就是「不救」，
        # 后者上游链已死修 splice 无意义）。always 本就 wanted 不进
        # 此支，never 仍拒。
        if mode == "onfail" and cst in {"clean", "ok"} and not cm.get("reject_at"):
            qc_hit = _qc_wanted(ctx)
        if not qc_hit:
            return _decline("not_wanted", {"compile_status_before": cst})

    splice_src = _ensure_kind(ctx, "splice")
    if splice_src is None:
        return _gate("skip", "no_splice", "upstream", "splice.- missing post-compile")
    metrics: dict = {"mode": mode, "fixloop_ran": True, "compile_status_before": cst}
    if qc_hit:
        metrics["qc_wanted"] = qc_hit
    work = ctx.paper_dir() / ".pipe-fix"
    if work.exists():
        shutil.rmtree(work)
    fsutil.copy_mutating(splice_src, work)
    main_rel = cm.get("main_rel")
    if not main_rel:
        found = find_main_tex(work)
        if found is None:
            return _gate(
                "error", "no_main_tex", "fixloop", classify_no_main(work) or "", metrics
            )
        main_rel = found.relative_to(work).as_posix()
    metrics["main_rel"] = main_rel

    texmf = ctx.paper_dir() / "_texmf"
    if texmf.exists():
        shutil.rmtree(texmf)  # 冷启动——防半成品 usertree 偏暖
    eng = flb._make_engine("xelatex", texmf, work)
    # baseline_dir 逐格注入（soak 同式）——restore_support_from_src/
    # slot_arg_revert 需要 src/ 原件树。
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
    try:
        cell = _er.fixloop(
            work,
            eng,
            ruleset=rs,
            engine_name="xelatex",
            main_rel=main_rel,
            corpus_id=ctx.idc,
            cond="pipe-fix",
            runner=flb._texmf_runner(texmf),
            case_sink=case_bridge(ctx),
            llm_hook=None,  # 付费面归 sibling spec（paid 静态旗标）
            compile_timeout=timeout,
        )
        crashed = False
    except PaidEscape as e:
        raise e.orig from e  # 拆舱交内核——harness_crash 兜底绝不收付费族
    except Exception as e:  # 格子崩溃记 verdict 不炸整批（旧同式）
        cell = {
            "project": ctx.idc,
            "engine": "xelatex",
            "verdict": f"harness_crash:{type(e).__name__}",
            "log_excerpt": str(e)[:500],
            "rounds": [],
            "actions": [],
        }
        crashed = True
    cell_wall = round(time.monotonic() - t0, 1)
    # 复判：texmf usertree 复用（fixloop 装的包只在 TEXMFHOME 里活着）
    # ——旧驱动恒 fresh-compile 复判（不用 soak 的 ResProxy fix_last 捷
    # 径，保驱动口径）。
    jeng = _er.XelatexEngine(
        halt_on_error=False, texmfhome=texmf, repository=flb.TUNA_TLNET
    )
    res = jeng.compile(work, main_rel, timeout=timeout, sandbox=False)
    expect_cjk = cm.get("expect_cjk", True)
    tail = benchlib.judge_dict(res, expect_cjk=expect_cjk)

    rounds = cell.get("rounds") or []
    fv = str(cell.get("verdict") or "?")
    fcat, fpay = benchlib.fixloop_attr(rounds, fv, cell.get("final_cat"))
    v = tail["verdict"]
    tail["regressed"] = benchlib.STATUS_RANK.get(
        str(v["status"] or ""), -1
    ) < benchlib.STATUS_RANK.get(str(cst or ""), -1)
    metrics.update(
        {
            "fixloop_verdict": fv,
            "final_cat": fcat,
            "rounds": len(rounds),
            "n_actions": len(cell.get("actions") or []),
            "rules_fired": list(
                dict.fromkeys(
                    str(a["rule"]) for a in (cell.get("actions") or []) if a.get("rule")
                )
            ),
            "gate_fired": list(cell.get("gate_fired") or []),
            "installed": cell.get("installed") or [],
            "floor_restored": bool(cell.get("floor_restored")),
            "fixloop_wall_s": cell_wall,
            "post": tail,
        }
    )
    # 修复树（含 harness_crash 的半修态）swap 回 splice.-——末段 mutates
    # 格，harvest 以本 stage DONE 把 zh/state/splice 一并封 vault。
    splice = ctx.asset_dir("splice")
    _swap_in(work, splice)
    if crashed:
        return {
            "status": "fail",
            "sig": benchlib.fixloop_sig(fv, fcat, fpay),
            "metrics": metrics,
            "errors": [{"code": fv, "cat": fcat, "payload": fpay}],
        }
    out = {
        "status": v["status"],
        "metrics": metrics,
        "sig": benchlib.fixloop_sig(fv, fcat, fpay),
    }
    if v["status"] != "clean":
        out["errors"] = [{"code": fv, "cat": fcat, "payload": fpay}]
    return out
