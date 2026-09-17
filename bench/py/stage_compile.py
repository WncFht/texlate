r"""stage_compile.py — stagerun ``compile`` stage：splice+inject+compile+judge。

``--arm zh``：zh/ 副本 → splice/ + prepare_chinese(ctex) + xelatex + judge；
``--arm base``：src/ 原样副本 → build-base/ 直编（原文直编归因臂）。
zh 臂 resume 另核 xlat 换代印（marker.ts vs 末条 metrics.xlat_ts）。
"""

from __future__ import annotations

import contextlib
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import benchlib
import stagerun_lib as sl

from texlate.compile.engine import engine_for, route_project
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def _compile_judge(
    work: Path, main_rel: str, eng_name: str, timeout: float, *, expect_cjk: bool
) -> dict:
    """best-effort 编译 + judge → {compile, verdict, status}。"""
    kw = {"halt_on_error": False} if eng_name == "xelatex" else {}
    res = engine_for(eng_name, **kw).compile(
        work, main_rel, timeout=timeout, sandbox=True
    )
    return benchlib.judge_dict(res, expect_cjk=expect_cjk)


def _resolve_engine(
    args: argparse.Namespace, parse_doc: dict | None, root: Path
) -> str:
    if args.engine != "auto":
        return args.engine
    if parse_doc and parse_doc.get("engine_resolved"):
        return parse_doc["engine_resolved"]
    try:
        return route_project(root, prefer="xelatex").engines[0]
    except Exception:
        return "xelatex"


def _compile_one(
    pid: str, out_dir: Path, args: argparse.Namespace, xlat_recs: dict
) -> dict:
    t0 = time.monotonic()
    rec = sl.base_rec(pid, "compile", args.arm)
    wid = sl.workdir(out_dir, pid)
    pj = wid / "parse.json"
    parse_doc = json.loads(pj.read_text()) if pj.exists() else None
    main_rel = (parse_doc or {}).get("main_rel")

    if args.arm == "zh":
        zh = wid / "zh"
        marker_p = zh / ".xlat-arm.json"
        if not zh.is_dir() or not marker_p.exists():
            rec["status"] = "skip"
            rec["errors"] = [
                {
                    "code": "not_translated",
                    "cat": "upstream",
                    "payload": "zh/ missing or no .xlat-arm.json",
                }
            ]
            return sl.finish_rec(rec, t0)
        marker_doc = json.loads(marker_p.read_text())
        upstream = marker_doc.get("arm") or ""
        if args.xlat_arm and upstream != args.xlat_arm:
            rec["status"] = "skip"
            rec["errors"] = [
                {
                    "code": "arm_mismatch",
                    "cat": "upstream",
                    "payload": f"zh/ is {upstream}, want {args.xlat_arm}",
                }
            ]
            return sl.finish_rec(rec, t0)
        rec["upstream"] = upstream
        # xlat 换代印：同臂 --rerun 重建 zh/ 后 marker.ts 变，compile
        # resume 凭此判陈记（stage_compile 侧对照 latest 记录）
        rec["metrics"]["xlat_ts"] = marker_doc.get("ts")
        up_ok = set((args.upstream or "ok,partial").split(","))
        xr = xlat_recs.get((pid, upstream, ""))
        if xr is not None and xr.get("status") not in up_ok:
            rec["status"] = "skip"
            rec["errors"] = [
                {
                    "code": "upstream_gate",
                    "cat": "upstream",
                    "payload": f"xlat[{upstream}]={xr.get('status')}",
                }
            ]
            return sl.finish_rec(rec, t0)
        splice = wid / "splice"
        if splice.exists():
            shutil.rmtree(splice)
        shutil.copytree(zh, splice, ignore=benchlib.copytree_ignore())
        if not main_rel:
            m = find_main_tex(splice)
            main_rel = m.relative_to(splice).as_posix() if m else None
        if not main_rel:
            rec["status"] = "reject"
            rec["errors"] = [
                {
                    "code": "no_main_tex",
                    "cat": "compile",
                    "payload": classify_no_main(splice) or "",
                }
            ]
            return sl.finish_rec(rec, t0)
        eng = _resolve_engine(args, parse_doc, splice)
        rec["metrics"]["engine"] = eng
        rec["metrics"]["main_rel"] = main_rel
        try:
            rec["metrics"]["inject"] = prepare_chinese(splice, main_rel)
        except InjectRejectError as e:
            rec["status"] = "reject"
            rec["errors"] = [
                {"code": "inject_reject", "cat": "inject", "payload": e.reason}
            ]
            rec["metrics"]["verdict"] = {"status": "reject", "reasons": [e.reason]}
            return sl.finish_rec(rec, t0)
        # 0-chunk 主文档 (includepdf 壳) 无译文产出 → 不期待 CJK (F 桶假阳修);
        # xr 缺席时保守默认 True。记入 metrics 供 fixloop 复判同口径
        _tr = ((xr or {}).get("metrics") or {}).get("translate") or {}
        expect_cjk = _tr.get("chunks") != 0
        rec["metrics"]["expect_cjk"] = expect_cjk
        tail = _compile_judge(
            splice, main_rel, eng, args.timeout, expect_cjk=expect_cjk
        )
    else:  # base：src/ 原样直编（归因臂——不 normalize 不 inject）
        src = wid / "src"
        if not src.is_dir():
            rec["status"] = "skip"
            rec["errors"] = [
                {
                    "code": "no_src",
                    "cat": "upstream",
                    "payload": "work/{id}/src/ missing",
                }
            ]
            return sl.finish_rec(rec, t0)
        main = find_main_tex(src)
        if main is None:
            rec["status"] = "reject"
            rec["errors"] = [
                {
                    "code": "no_main_tex",
                    "cat": "compile",
                    "payload": classify_no_main(src) or "",
                }
            ]
            return sl.finish_rec(rec, t0)
        main_rel = main.relative_to(src).as_posix()
        build = wid / "build-base"
        if build.exists():
            shutil.rmtree(build)
        shutil.copytree(src, build, ignore=benchlib.copytree_ignore())
        eng = _resolve_engine(args, parse_doc, src)
        rec["metrics"]["engine"] = eng
        rec["metrics"]["main_rel"] = main_rel
        tail = _compile_judge(build, main_rel, eng, args.timeout, expect_cjk=False)

    rec["metrics"].update(tail)
    v = tail["verdict"]
    rec["status"] = v["status"]
    if v["status"] not in ("clean", "partial"):
        rec["errors"] = [
            {
                "code": v.get("category") or "compile_fail",
                "cat": v.get("category"),
                # payload 只取 verdict 对配字段——first_error 兜底曾是聚类毒药：
                # payload None 时整条 `abs/path/file.tex:N: msg` log 摘录进
                # errors[0]，sig 成 `cat:/home/...` 每篇一键（payload-scout
                # 实证 5 条 `undefined_cs:/home/...` 幻影 sig）。
                "payload": v.get("payload"),
            }
        ]
    elif v.get("category"):
        rec["errors"] = [
            {"code": v["category"], "cat": v["category"], "payload": v.get("payload")}
        ]
    rec["sig"] = benchlib.verdict_sig(v, tail["compile"].get("first_error"))
    rec["dur_s"] = round(time.monotonic() - t0, 2)
    return rec


def stage_compile(
    args: argparse.Namespace,
    out_dir: Path,
    ids: list[str],
    log: sl.RecLog,
    xlat_recs: dict,
) -> None:
    todo = []
    ids = sl.dedup_wids(ids)  # 同 wid 单任务闸——直调本驱动的调用方也兜住
    # zh 臂 resume 还要核 xlat 换代：同臂 --rerun 会重建 zh/ 树，陈记的
    # (id,zh,arm) 键仍命中——对照末条 metrics.xlat_ts 与当前 marker.ts
    latest = sl.load_latest(log.path) if args.arm == "zh" else {}
    for pid in ids:
        # resume 键含 upstream：zh 臂对 mock/real 产物各记一格
        if args.arm == "zh":
            marker = sl.workdir(out_dir, pid) / "zh" / ".xlat-arm.json"
            up = ""
            mts = None
            if marker.exists():
                with contextlib.suppress(Exception):
                    doc = json.loads(marker.read_text())
                    up = doc.get("arm") or ""
                    mts = doc.get("ts")
            if not args.rerun and up and log.is_done(pid, "zh", up, recode=args.recode):
                last = latest.get((pid, "zh", up)) or {}
                # marker 无 ts（旧版产物）退回纯键判；记录缺印=换代不明→重编
                if mts is None or (last.get("metrics") or {}).get("xlat_ts") == mts:
                    continue
        elif not args.rerun and log.is_done(pid, "base", recode=args.recode):
            continue
        todo.append(pid)
    print(f"compile[{args.arm}]: {len(todo)} to run (jobs={args.jobs})", flush=True)
    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(_compile_one, p, out_dir, args, xlat_recs): p for p in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = sl.crash_rec(pid, "compile", args.arm, e, time.monotonic())
            log.append(rec)
            v = (rec.get("metrics") or {}).get("verdict") or {}
            print(
                f"  [{i}/{len(todo)}] {pid} -> {rec['status']} cat={v.get('category') or '-'} ({rec['dur_s']}s)",
                flush=True,
            )
            if args.time_budget and time.monotonic() - t_start > args.time_budget:
                break
