"""soak parse 段叶——route → normalize → scan_tex_tree → zh.- 暂存 swap。"""

from __future__ import annotations

import json
import shutil

from kernel import fsutil

from specs import _bootstrap

_bootstrap.ensure()

from specs._shared import _gate, _swap_in
from texlate.compile.engine import route_project
from texlate.compile.inject import classify_no_main, find_main_tex
from texlate.compile.normalize import normalize_project
from texlate.latex.api import scan_tex_tree

# ---------------------------------------------------------------- stage: parse


def _parse(ctx) -> dict:
    """route(src) → .zh-build 暂存 → find_main → normalize → scan →
    zh.-/ + zh.-/parse.json（_parse_job 的 ctx 版平移）。

    parse.json 双落点：``paper_dir/parse.json``（旧 ``wid/parse.json``
    同位，本 run 诊断面）+ ``zh.-/parse.json``（随树封 vault——跨 run
    的 main_rel/engine_resolved 消费面；route_reject 不出 zh.- 树，
    与旧式 zh/ 缺席同义）。
    """
    src = ctx.src_path()
    if src is None:
        return _gate("skip", "no_src", "upstream", "lake cell materialization failed")
    paper = ctx.paper_dir()
    pj_root = paper / "parse.json"
    stage = paper / ".zh-build"

    def _write_doc(doc: dict) -> None:
        text = json.dumps(doc, ensure_ascii=False, indent=1)
        pj_root.write_text(text, encoding="utf-8")
        zh = ctx.upstream_asset_dir("zh")
        if zh is not None:
            (zh / "parse.json").write_text(text, encoding="utf-8")

    metrics: dict = {}
    route = route_project(src)
    metrics["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    doc: dict = {"id": ctx.idc, "route": metrics["route"]}
    if route.reject:
        doc["status"] = "reject"
        if stage.exists():
            shutil.rmtree(stage)
        _write_doc(doc)
        return _gate("reject", "route_reject", "route", route.reject, metrics)

    if stage.exists():
        shutil.rmtree(stage)
    fsutil.copy_mutating(src, stage)

    main = find_main_tex(stage)
    if main is None:
        sub = classify_no_main(stage)
        doc["status"] = "reject"
        doc["no_main_sub"] = sub
        zh = ctx.asset_dir("zh")
        _swap_in(stage, zh)  # zh.- 在场=未归一化原料树（旧式同形）
        _write_doc(doc)
        metrics["no_main_sub"] = sub
        return _gate("reject", "no_main_tex", "parse", sub or "", metrics)
    main_rel = main.relative_to(stage).as_posix()
    eng = str(ctx.params.get("engine") or "xelatex")
    if eng == "auto":
        eng = route.engines[0] if route.engines else "xelatex"
    norm = normalize_project(stage, eng, main_rel)
    doc.update({"main_rel": main_rel, "engine_resolved": eng, "normalize": norm})
    metrics.update({"main_rel": main_rel, "engine_resolved": eng, "normalize": norm})

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
    zh = ctx.asset_dir("zh")
    _swap_in(stage, zh)
    _write_doc(doc)
    metrics.update(
        {
            "tex_files": len(files),
            "support_files": len(support),
            "chunks": n_chunks,
            "warn_kinds": doc["totals"]["warn_kinds"],
            "n_unresolved": len(unresolved),
            "parse_fail": parse_fail,
        }
    )
    out = {"status": "ok", "metrics": metrics}
    if parse_fail:
        out["errors"] = [
            {"code": "parse_file", "cat": "parse", "payload": p}
            for p in parse_fail[:10]
        ]
    return out
