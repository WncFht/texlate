"""mock E2E 驱动（docs/10 B5 Mode A 的产品化扶正）。

全链走产品 API：``route_project → normalize_project → XlatPipeline(MockTranslator)
+ L0 校验 → splice 写回 → prepare_chinese → engine.compile → judge``。
bench harness（e2e_mock_bench）与 CLI ``texlate run`` 共用同一实现——
评测条件矩阵在 bench 侧，单工程驱动在这里。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from texlate.compile.engine import engine_for, route_project
from texlate.compile.inject import InjectRejectError, find_main_tex, prepare_chinese
from texlate.compile.judge import judge
from texlate.compile.normalize import normalize_project
from texlate.latex.api import parse_file
from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import reconstruct
from texlate.validate.l0 import validate_pair
from texlate.xlat.pipeline import ChunkIn, MockTranslator, XlatPipeline, chunk_to_in

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.latex.model import ScanResult


def mock_translate_tree(root: Path) -> dict:
    """目录树内全部 .tex 走 XlatPipeline(MockTranslator) → splice 写回。

    单 pipeline 跨文件编排（chunk_id = ``{file_idx}:{chunk.id}``），
    校验器注入 L0 ``validate_pair``。返回 per-tree 汇总统计。
    """
    scans: list[tuple[Path, ScanResult]] = []
    chunks: list[ChunkIn] = []
    for f in sorted(root.rglob("*.tex")):
        res = parse_file(f, flatten=False)
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(chunk_to_in(c, chunk_id=f"{idx}:{c.id}") for c in res.chunks)

    pipe = XlatPipeline(
        MockTranslator(),
        validator=lambda s, z: validate_pair(s, z).feedback(),
    )
    results = asyncio.run(pipe.run(chunks))
    by_file: dict[int, dict[int, str]] = {}
    n_fault = 0
    for r in results:
        fidx, cid = (int(x) for x in r.chunk_id.split(":", 1))
        if r.status == "ok":
            by_file.setdefault(fidx, {})[cid] = r.translation
        else:
            n_fault += 1

    n_files = 0
    n_leftover = 0
    for idx, (f, res) in enumerate(scans):
        trans = by_file.get(idx)
        if not trans:
            continue
        zh = reconstruct(res, trans)
        f.write_text(zh, encoding="utf-8")
        n_files += 1
        n_leftover += len(PH_RX.findall(zh))
    return {
        "files": n_files,
        "chunks": len(chunks),
        "fault_chunks": n_fault,
        "leftover_ph": n_leftover,
    }


def _compile_judge(
    work: Path, main_rel: str, eng_name: str, timeout: float, *, expect_cjk: bool
) -> dict:
    """编译 + 判定公共尾段。

    best-effort 语义：xelatex halt_on_error=False 对齐 bench；
    tectonic 无此旋钮——恒 ``-Z continue-on-errors``。
    """
    kw: dict[str, object] = {"halt_on_error": False} if eng_name == "xelatex" else {}
    res = engine_for(eng_name, **kw).compile(
        work, main_rel, timeout=timeout, sandbox=True
    )
    v = judge(res, expect_cjk=expect_cjk)
    return {
        "compile": {
            "ok": res.ok,
            "timed_out": res.timed_out,
            "seconds": round(res.seconds, 2),
            "passes": res.passes,
            "rc": res.rc,
            "pdf_bytes": res.pdf_bytes,
            "first_error": res.log.first_error,
        },
        "verdict": {
            "status": v.status,
            "reasons": v.reasons,
            "n_errors": v.n_errors,
            "category": v.category,
            "cjk_chars": v.cjk_chars,
            "missing_chars": v.missing_chars,
        },
        "status": v.status,
    }


def pipe_condition(work: Path, eng_name: str, main_rel: str, timeout: float) -> dict:
    """跑 pipe 条件：normalize → mock 翻译 → ctex 注入 → 编译 → 判定。"""
    rec: dict[str, object] = {"engine": eng_name}
    rec["normalize"] = normalize_project(work, eng_name, main_rel)
    rec["translate"] = mock_translate_tree(work)
    try:
        rec["inject"] = prepare_chinese(work, main_rel)
    except InjectRejectError as e:
        rec["status"] = "reject"
        rec["verdict"] = {"status": "reject", "reasons": [e.reason]}
        return rec
    rec.update(_compile_judge(work, main_rel, eng_name, timeout, expect_cjk=True))
    return rec


def base_condition(work: Path, eng_name: str, main_rel: str, timeout: float) -> dict:
    """跑 base 条件：不动源码直接编译+判定（管线引入 vs 原生失败的归因对照）。"""
    rec: dict[str, object] = {"engine": eng_name}
    rec.update(_compile_judge(work, main_rel, eng_name, timeout, expect_cjk=False))
    return rec


def mock_pipeline_run(work: Path, engine_opt: str, timeout: float) -> dict:
    """工程目录上的 mock 全链（对齐 e2e_mock_bench 的 pipe 条件语义）。

    ``engine_opt``：``auto`` 取路由首选，或显式引擎名。返回结构化报告 dict
    （route/normalize/translate/inject/compile/verdict + 终态 status）。
    """
    report: dict[str, object] = {"work": str(work)}
    route = route_project(work)
    report["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
    }
    if route.reject:
        report["status"] = "reject"
        return report
    main_path = find_main_tex(work)
    if main_path is None:
        report["status"] = "reject"
        report["route"]["reasons"] = [*route.reasons, "no main tex"]
        return report
    main_rel = main_path.relative_to(work).as_posix()
    report["main"] = main_rel

    eng_name = engine_opt if engine_opt != "auto" else route.engines[0]
    report.update(pipe_condition(work, eng_name, main_rel, timeout))
    return report
