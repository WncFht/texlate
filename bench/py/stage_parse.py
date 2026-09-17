r"""stage_parse.py — stagerun ``parse`` stage：route+normalize+parse_file。

work/{id}/src/ → zh/（normalize 归一化英文树）+ parse.json（main_rel /
engine_resolved / route / normalize stats / 逐文件 {chunks,warnings,inputs}）。
ProcessPool 执行——``_parse_job`` 的 pickle 边界是字符串路径 + 配置。
"""

from __future__ import annotations

import json
import shutil
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

import benchlib
import stagerun_lib as sl

from texlate.compile.engine import route_project
from texlate.compile.inject import classify_no_main, find_main_tex
from texlate.compile.normalize import normalize_project
from texlate.latex.api import parse_file

if TYPE_CHECKING:
    import argparse


def _parse_job(pid: str, src_s: str, zh_s: str, pj_s: str, engine_opt: str) -> dict:
    """ProcessPool 工作元：pickle 边界 = 字符串路径 + 配置。

    route(src) → copytree(src→zh) → find_main → normalize(zh, eng) →
    逐文件 parse_file(flatten=False) → parse.json + record。
    """
    t0 = time.monotonic()
    src, zh, pj = Path(src_s), Path(zh_s), Path(pj_s)
    rec = sl.base_rec(pid, "parse", "-")
    route = route_project(src)
    rec["metrics"]["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    doc: dict = {"id": pid, "route": rec["metrics"]["route"]}
    if route.reject:
        doc["status"] = "reject"
        pj.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        rec["status"] = "reject"
        rec["errors"] = [
            {"code": "route_reject", "cat": "route", "payload": route.reject}
        ]
        return sl.finish_rec(rec, t0)

    # zh/ 先建到兄弟暂存再 rename —— 并发 compile 读 zh/.xlat-arm.json
    # 时窗口内 rmtree+重建会让 marker 缺席 → 误记 skip (41 捞出 20 格)。
    # 暂存期 zh/ 保持上一版完整状态 (marker+内容一致)。
    stage = zh.with_name(".zh-build")
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(src, stage, ignore=benchlib.copytree_ignore())

    def _swap_in() -> None:
        # rename 接力而非 rmtree+rename —— zh 路径名全程存在
        old = zh.with_name(".zh-old")
        if zh.exists():
            if old.exists():
                shutil.rmtree(old)
            zh.rename(old)
        stage.rename(zh)
        if old.exists():
            shutil.rmtree(old)

    main = find_main_tex(stage)
    if main is None:
        sub = classify_no_main(stage)
        doc["status"] = "reject"
        doc["no_main_sub"] = sub
        _swap_in()
        pj.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        rec["status"] = "reject"
        rec["errors"] = [{"code": "no_main_tex", "cat": "parse", "payload": sub or ""}]
        return sl.finish_rec(rec, t0)
    main_rel = main.relative_to(stage).as_posix()
    eng = (
        engine_opt
        if engine_opt != "auto"
        else (route.engines[0] if route.engines else "xelatex")
    )
    norm = normalize_project(stage, eng, main_rel)
    doc.update({"main_rel": main_rel, "engine_resolved": eng, "normalize": norm})
    rec["metrics"]["main_rel"] = main_rel
    rec["metrics"]["engine_resolved"] = eng
    rec["metrics"]["normalize"] = norm

    files: list[dict] = []
    warn_kinds: dict[str, int] = {}
    unresolved: list[str] = []
    n_chunks = 0
    parse_fail: list[str] = []
    for f in sorted(stage.rglob("*.tex")):
        if f.name.startswith("."):
            continue
        rel = f.relative_to(stage).as_posix()
        try:
            res = parse_file(f, flatten=False)
        except Exception as e:
            parse_fail.append(f"{rel}: {e!r:.160}")
            continue
        ws = [{"kind": w.kind, "pos": w.pos, "detail": w.detail} for w in res.warnings]
        for w in res.warnings:
            warn_kinds[w.kind] = warn_kinds.get(w.kind, 0) + 1
        ins = [name for _pos, name in res.inputs]
        unresolved.extend(f"{rel}:{n}" for n in ins)
        n_chunks += len(res.chunks)
        files.append(
            {
                "rel": rel,
                "n_chunks": len(res.chunks),
                "chunk_kinds": sorted({c.context for c in res.chunks}),
                "warnings": ws,
                "inputs": ins,
            }
        )
    doc.update(
        {
            "status": "ok",
            "files": files,
            "parse_fail": parse_fail,
            "totals": {
                "tex_files": len(files),
                "chunks": n_chunks,
                "warn_kinds": dict(sorted(warn_kinds.items())),
                "unresolved": unresolved,
            },
        }
    )
    _swap_in()
    pj.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    rec["status"] = "ok"
    rec["metrics"].update(
        {
            "tex_files": len(files),
            "chunks": n_chunks,
            "warn_kinds": doc["totals"]["warn_kinds"],
            "n_unresolved": len(unresolved),
            "parse_fail": parse_fail,
        }
    )
    if parse_fail:
        rec["errors"] = [
            {"code": "parse_file", "cat": "parse", "payload": p}
            for p in parse_fail[:10]
        ]
    return sl.finish_rec(rec, t0)


def stage_parse(
    args: argparse.Namespace, out_dir: Path, ids: list[str], log: sl.RecLog
) -> None:
    ids = sl.dedup_wids(ids)  # 同 wid 单任务闸——直调本驱动的调用方也兜住
    todo = []
    for pid in ids:
        if log.is_done(pid, "-", recode=args.recode) and not args.rerun:
            continue
        wid = sl.workdir(out_dir, pid)
        src = wid / "src"
        if not src.is_dir():
            r = sl.base_rec(pid, "parse", "-")
            r["status"] = "skip"
            r["errors"] = [
                {
                    "code": "no_src",
                    "cat": "upstream",
                    "payload": "work/{id}/src/ missing",
                }
            ]
            log.append(sl.finish_rec(r, time.monotonic()))
            continue
        todo.append(
            (pid, str(src), str(wid / "zh"), str(wid / "parse.json"), args.engine)
        )
    print(f"parse: {len(todo)} to run (jobs={args.jobs})", flush=True)
    if not todo:
        return
    ex = ProcessPoolExecutor(max_workers=args.jobs)
    t_start = time.monotonic()
    try:
        futs = {ex.submit(_parse_job, *t): t[0] for t in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = sl.crash_rec(pid, "parse", "-", e, time.monotonic())
            log.append(rec)
            print(
                f"  [{i}/{len(todo)}] {pid} -> {rec['status']} ({rec['dur_s']}s)",
                flush=True,
            )
            if args.time_budget and time.monotonic() - t_start > args.time_budget:
                print(
                    f"time budget {args.time_budget}s — stop ({i}/{len(todo)})",
                    flush=True,
                )
                break
    finally:
        # wait=False 会把仍在写 zh/ 的在飞 worker 丢在后台——下个 stage
        # 读到残树 (1e 审计)。cancel_futures 只收排队任务；在跑任务等其
        # 写毕再交棒，bounded by 单篇 parse 时长。
        ex.shutdown(wait=True, cancel_futures=True)
