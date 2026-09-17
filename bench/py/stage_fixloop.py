r"""stage_fixloop.py — stagerun ``fixloop`` stage：compile 非 clean 格就地修复。

splice/ 就地修复（fixloop yaml 规则引擎 + usermode tlmgr 冷 usertree）+
post 复判编译（与 compile 记录同 verdict 刻度）。``--on`` 谓词选目标格；
``--rerun`` 自 zh/ 重建 splice（上波就地变异不带入新轮）。
"""

from __future__ import annotations

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import benchlib
import fixloop_bench as flb
import stagerun_lib as sl

from texlate.compile.engine import XelatexEngine
from texlate.compile.fixloop import CaseSink, Ruleset, fixloop
from texlate.compile.fixloop.llm_hook import make_llm_hook
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)
from texlate.repair import ResProxy

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def _fixloop_one(
    pid: str, out_dir: Path, args: argparse.Namespace, comp_rec: dict, sink: CaseSink
) -> dict:
    """pipe_fix_condition 同构：splice/ 就地修复 + usermode 复判。

    splice/ 即 zh 臂编后树（normalize+译+inject+编译产物）；修复终态落同目录，
    ``post`` 复判编译与 compile 记录同 verdict 刻度。
    ``--rerun`` = 以当前 zh/ 从头重跑本 stage——上波 fixloop 就地变异
    （shim 落盘/preamble 注入/补丁）不得带入新轮（2211.04482 实证脏
    splice 泄漏：二轮规则在假树上复跑）。重建与 ``_compile_one`` 同式：
    copytree(zh→splice) + prepare_chinese。
    """
    t0 = time.monotonic()
    upstream = comp_rec.get("upstream") or ""
    rec = sl.base_rec(pid, "fixloop", "fix", upstream)
    wid = sl.workdir(out_dir, pid)
    splice = wid / "splice"
    if args.rerun:
        zh = wid / "zh"
        marker_p = zh / ".xlat-arm.json"
        if not zh.is_dir() or not marker_p.exists():
            rec["status"] = "error"
            rec["errors"] = [
                {
                    "code": "rerun_no_zh",
                    "cat": "upstream",
                    "payload": "zh/ missing or no .xlat-arm.json",
                }
            ]
            return sl.finish_rec(rec, t0)
        marker_arm = json.loads(marker_p.read_text()).get("arm") or ""
        if upstream and marker_arm and marker_arm != upstream:
            # 与 _compile_one 的 arm 门同口径：zh/ 已被别的 xlat 臂重译，
            # 重建会混臂——skip 让位而非在错位树上误修。
            rec["status"] = "skip"
            rec["errors"] = [
                {
                    "code": "arm_mismatch",
                    "cat": "upstream",
                    "payload": f"zh/ is {marker_arm}, compile was {upstream}",
                }
            ]
            return sl.finish_rec(rec, t0)
        if splice.exists():
            shutil.rmtree(splice)
        shutil.copytree(zh, splice, ignore=benchlib.copytree_ignore())
        rec["metrics"]["splice_rebuilt"] = True
    if not splice.is_dir():
        rec["status"] = "skip"
        rec["errors"] = [
            {"code": "no_splice", "cat": "upstream", "payload": "splice/ missing"}
        ]
        return sl.finish_rec(rec, t0)
    pj = wid / "parse.json"
    main_rel = None
    if pj.exists():
        main_rel = json.loads(pj.read_text()).get("main_rel")
    if not main_rel:
        m = find_main_tex(splice)
        main_rel = m.relative_to(splice).as_posix() if m else None
    if not main_rel:
        rec["status"] = "error"
        rec["errors"] = [
            {
                "code": "no_main_tex",
                "cat": "fixloop",
                "payload": classify_no_main(splice) or "",
            }
        ]
        return sl.finish_rec(rec, t0)
    if args.rerun:
        # 重建的 splice 是纯 zh/ 副本——ctex 注入须与 compile 同式重做，
        # 否则 fixloop 修的是未注入树（与编译期口径不一致）。
        try:
            rec["metrics"]["inject"] = prepare_chinese(splice, main_rel)
        except InjectRejectError as e:
            rec["status"] = "reject"
            rec["errors"] = [
                {"code": "inject_reject", "cat": "inject", "payload": e.reason}
            ]
            rec["metrics"]["verdict"] = {"status": "reject", "reasons": [e.reason]}
            return sl.finish_rec(rec, t0)

    texmf = wid / "_texmf"
    if texmf.exists():
        shutil.rmtree(texmf)  # 冷启动——防半成品 usertree 偏暖（同 pipe_fix_condition）
    flb._init_usertree(texmf)
    eng = flb._NoSandbox(
        XelatexEngine(halt_on_error=True, texmfhome=texmf, repository=flb.TUNA_TLNET)
    )
    idx = flb._index()
    if idx is not None:
        eng.filemap = idx.query
    # restore_support_from_src 的 baseline_dir 是逐格运行时路径 (复跑继承
    # pre-prose-gate 脏树才有存量腐蚀可修) —— params 在共享 flb.RS 上无法按
    # pid 注入, 故每格 Ruleset.load() 后按 transform 名注入 src/ 原件树
    # (同 worker.ruleset_with_baseline 契约)。
    rs = flb.RS
    if (wid / "src").is_dir():
        rs = Ruleset.load()
        for rule in rs.rules:
            act = rule.raw.get("action") or {}
            if (
                act.get("kind") == "builtin_transform"
                and act.get("function") == "restore_support_from_src"
            ):
                act.setdefault("params", {})["baseline_dir"] = str(wid / "src")
    try:
        # ResProxy 记末次 CompRes——与产品侧 run_fixloop (repair.py:207) 同式
        # 接线，但直调 fixloop 保留本模块的 monkeypatch 缝 (test_bench_triage)。
        proxy = ResProxy(eng)
        cell = fixloop(
            splice,
            proxy,
            ruleset=rs,
            engine_name="xelatex",
            corpus_id=pid,
            cond="fixloop",
            runner=flb._texmf_runner(texmf),
            case_sink=sink,
            llm_hook=make_llm_hook() if getattr(args, "llm", False) else None,
            compile_timeout=args.timeout,
        )
        fix_last = proxy.last
    except Exception as e:
        cell = {
            "project": pid,
            "engine": "xelatex",
            "verdict": f"harness_crash:{type(e).__name__}",
            "log_excerpt": str(e)[:500],
            "rounds": [],
            "actions": [],
        }
        fix_last = None
    cell_wall = round(time.monotonic() - t0, 1)
    # post 复判吃 fixloop 末轮 CompRes——与产品侧 ``res = fix_last or first``
    # 同口径 (worker/compile.py:516)：判定输入仍是末轮编译产物+judge 输出，
    # 只是不再 fresh compile 白跑一遍 (B14 画像: 此编译占 row dur ~33%)。
    # 兜底走旧 fresh-compile 路径的情形：fixloop 早退无编译 (no_main_tex/
    # precheck reject/max_rounds=0)、harness 崩溃、fixloop 宽松档选的主档
    # 与 stage main_rel 错位 (cell["main"] 是 fixloop 实测主档)。
    if fix_last is not None and cell.get("main") == main_rel:
        res = fix_last
        post_src = "fixloop_last"
    else:
        jeng = XelatexEngine(
            halt_on_error=False, texmfhome=texmf, repository=flb.TUNA_TLNET
        )
        res = jeng.compile(splice, main_rel, timeout=args.timeout, sandbox=False)
        post_src = "fresh_compile"
    # 复判沿用 compile 臂的 CJK 期待口径 (0-chunk 主文档不判 cjk_chars=0)
    expect_cjk = (comp_rec.get("metrics") or {}).get("expect_cjk", True)
    tail = benchlib.judge_dict(res, expect_cjk=expect_cjk)

    rounds = cell.get("rounds") or []
    fcat = cell.get("final_cat") or (rounds[-1].get("category") if rounds else None)
    fpay = ""
    for rd in reversed(rounds):
        if rd and (rd.get("pay") or rd.get("payload")):
            fpay = rd.get("pay") or rd.get("payload")
            break
    fv = str(cell.get("verdict") or "?")
    v = tail["verdict"]
    rec["status"] = v["status"]
    csb = comp_rec.get("status")
    # post.regressed 物化：csb→post rank 回落——与 triage fixloop_degraded
    # 同式（STATUS_RANK 表外取 -1，非终态词恒不判退化），写侧一次消三处自算
    # （gate.pick_final stale 是跨记录校验，不在此物化面）。
    tail["regressed"] = benchlib.STATUS_RANK.get(
        str(v["status"] or ""), -1
    ) < benchlib.STATUS_RANK.get(str(csb or ""), -1)
    actions = cell.get("actions") or []
    rec["metrics"].update(
        {
            "mode": args.on,
            "compile_status_before": comp_rec.get("status"),
            # verdict 指纹级校验料——csb 状态等值挡不住同态陈旧
            # （compile 重跑 status 同而 sig/first_error 已换），
            # gate_scorecard.pick_final 在场即比对、缺席回退 csb。
            "compile_fp": benchlib.compile_fp(comp_rec),
            "fixloop_verdict": fv,
            "final_cat": fcat,
            "rounds": len(rounds),
            "n_actions": len(actions),
            "rules_fired": list(
                dict.fromkeys(str(a["rule"]) for a in actions if a.get("rule"))
            ),
            "installed": cell.get("installed") or [],
            "floor_restored": bool(cell.get("floor_restored")),
            "fixloop_wall_s": cell_wall,
            # post 复判来源：fixloop_last=末轮 CompRes 复用 (主路径) /
            # fresh_compile=兜底重编 (早退/崩溃/主档错位) —— 下游可观测复用率
            "post_src": post_src,
            "post": tail,
        }
    )
    if rec["status"] != "clean":
        rec["errors"] = [{"code": fv, "cat": fcat, "payload": fpay}]
        rec["sig"] = benchlib.fixloop_sig(fv, fcat, fpay)
    rec["dur_s"] = round(time.monotonic() - t0, 2)
    return rec


def _on_misschar(crec: dict) -> bool:
    """缺字窄口：partial ∧ missing_chars>0 —— missing_char_fix 可修的子集。

    判定核单源 ``benchlib.misschar_partial``（与 e2e_real_bench._want_fix
    同口径）；其余 warning 级 partial 不进（partial→fail 回退教训）。
    """
    v = (crec.get("metrics") or {}).get("verdict") or {}
    return benchlib.misschar_partial(crec.get("status"), v)


_ON_PRED: dict[str, object] = {
    "fail": lambda c: c.get("status") == "fail",
    "nonclean": lambda c: c.get("status") in {"fail", "partial"},
    "misschar": _on_misschar,
    "clean": lambda c: c.get("status") == "clean",
    # reject/skip 无有效 splice 树 —— post-judge 编译被拒英文树会虚增
    # union-pdf (1e 审计: +414 phantom 上限)。error(harness 崩) 树态不定
    # 同排。clean 保留供非回归复判。
    "all": lambda c: c.get("status") not in {"reject", "skip", "error"},
}


def stage_fixloop(
    args: argparse.Namespace, out_dir: Path, ids: list[str], log: sl.RecLog
) -> None:
    want = _ON_PRED[args.on]
    ids = sl.dedup_wids(ids)  # 同 wid 单任务闸（canon 归一+去重）
    want_ids = set(ids)
    # (pid,zh) 可并存多个 upstream 键 —— load_latest dict 插序是首见序,
    # cand[-1] 拿到的不是最新 compile 格 (1e 审计); 直扫文件按 append 序取。
    # id 全程 canon 归一 —— flat 拼写存量 compile 账按规范形命中
    # (loop1 双拼写并存实证, 不 canon 则 flat 账静默落选)。
    cand_latest: dict[str, dict] = {}
    comp_path = out_dir / "records" / "compile.jsonl"
    if comp_path.exists():
        cand_latest = benchlib.latest_by(
            (
                rec
                for rec in benchlib.iter_jsonl(comp_path)
                if sl.canon_id(str(rec.get("id") or "")) in want_ids
                and rec.get("arm") == "zh"
                # 多 xlat 臂并存时同键 append 互覆 —— 指定 --xlat-arm 则只认
                # 该臂记录 (arm_mismatch skip 的 upstream 为空, 自然滤除)
                and (not args.xlat_arm or (rec.get("upstream") or "") == args.xlat_arm)
            ),
            lambda r: sl.canon_id(str(r["id"])),  # append 序覆盖 = 末条
        )
    todo: list[tuple[str, dict]] = []
    for pid in ids:
        crec = cand_latest.get(pid)
        if crec is None:
            continue
        if not want(crec):
            continue
        if (
            log.is_done(pid, "fix", crec.get("upstream") or "", recode=args.recode)
            and not args.rerun
        ):
            continue
        todo.append((pid, crec))
    print(f"fixloop[on={args.on}]: {len(todo)} cells (jobs={args.jobs})", flush=True)
    if not todo:
        return
    # 坏 yaml 拒开波: 每格 _fixloop_one 内 Ruleset.load()——表挂则逐格 error
    # ('.\\hbox' 非法转义事故 809 格全 error), preflight 一次挡在波前。
    Ruleset.load()
    sink = CaseSink(out_dir / "cases.jsonl")
    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {
            ex.submit(_fixloop_one, p, out_dir, args, cr, sink): p for p, cr in todo
        }
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = sl.crash_rec(pid, "fixloop", "fix", e, time.monotonic())
            log.append(rec)
            fv = (rec.get("metrics") or {}).get("fixloop_verdict") or "-"
            print(
                f"  [{i}/{len(todo)}] {pid} -> {rec['status']} fixloop={fv} ({rec['dur_s']}s)",
                flush=True,
            )
            if args.time_budget and time.monotonic() - t_start > args.time_budget:
                break
