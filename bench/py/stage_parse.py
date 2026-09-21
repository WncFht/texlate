r"""stage_parse.py — stagerun ``parse`` stage：route+normalize+parse_file。

work/{id}/src/ → zh/（normalize 归一化英文树）+ parse.json（main_rel /
engine_resolved / route / normalize stats / 逐文件 {chunks,warnings,inputs}）。
ProcessPool 执行——``_parse_job`` 的 pickle 边界是字符串路径 + 配置。
"""

from __future__ import annotations

import json
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

import benchlib
import stagerun_lib as sl

from texlate.compile.engine import route_project
from texlate.compile.inject import classify_no_main, find_main_tex
from texlate.compile.normalize import normalize_project
from texlate.latex.api import scan_tex_tree

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
        return sl.gate_rec(rec, "reject", "route_reject", "route", route.reject, t0)

    # zh/ 先建到兄弟暂存再 rename —— 并发 compile 读 zh/.xlat-arm.json
    # 时窗口内 rmtree+重建会让 marker 缺席 → 误记 skip (41 捞出 20 格)。
    # 暂存期 zh/ 保持上一版完整状态 (marker+内容一致)。
    stage = zh.with_name(".zh-build")
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(src, stage, ignore=benchlib.copytree_ignore())

    main = find_main_tex(stage)
    if main is None:
        sub = classify_no_main(stage)
        doc["status"] = "reject"
        doc["no_main_sub"] = sub
        sl.swap_in(stage, zh)
        pj.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        return sl.gate_rec(rec, "reject", "no_main_tex", "parse", sub or "", t0)
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

    # 逐文件枚举走全树扫描单源 latex.api.scan_tex_tree——与下游各 stage
    # 同一门：rglob("*")+is_file()+suffix.lower()==".tex"（.TEX 大写命中）、
    # dotfile/.rtx.tex 跳过、.code.tex/无散文件入 support、解析崩入 fault
    # （tar 伪装件连 fault 都不记，逐字节原样保留）。
    scan = scan_tex_tree(stage)
    files: list[dict] = []
    warn_kinds: dict[str, int] = {}
    unresolved: list[str] = []
    n_chunks = 0
    parse_fail = [f"{rel}: {exc!r:.160}" for rel, exc in scan.fault]
    support = sorted(scan.support)
    for _abs, rel, res in scan.parsed:
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
            "support_files": support,
            "totals": {
                "tex_files": len(files),
                "support_files": len(support),
                "chunks": n_chunks,
                "warn_kinds": dict(sorted(warn_kinds.items())),
                "unresolved": unresolved,
            },
        }
    )
    sl.swap_in(stage, zh)
    pj.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    rec["status"] = "ok"
    rec["metrics"].update(
        {
            "tex_files": len(files),
            "support_files": len(support),
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
            log.append(
                sl.gate_rec(
                    r,
                    "skip",
                    "no_src",
                    "upstream",
                    "work/{id}/src/ missing",
                    time.monotonic(),
                )
            )
            continue
        todo.append(
            (pid, str(src), str(wid / "zh"), str(wid / "parse.json"), args.engine)
        )
    print(f"parse: {len(todo)} to run (jobs={args.jobs})", flush=True)
    if not todo:
        return
    # 分发骨架收编 sl.run_pool——shutdown(wait=True, cancel_futures=True)
    # 收尾语义与原手写循环逐字一致（在飞 worker 写毕才交棒，残树不进
    # 下个 stage 视野）；ProcessPool 边界仍是 pickle 化的字符串参数。
    sl.run_pool(
        todo,
        submit_fn=lambda ex, t: ex.submit(_parse_job, *t),
        pid_fn=lambda t: t[0],
        log=log,
        args=args,
        stage="parse",
        arm="-",
        progress_fn=lambda i, n, pid, rec: print(
            f"  [{i}/{n}] {pid} -> {rec['status']} ({rec['dur_s']}s)", flush=True
        ),
        executor_cls=ProcessPoolExecutor,
    )
