"""texlate 命令行入口。

M0 集成面：``fetch``（取源钉版）/ ``parse``（半解析分块）/ ``run``（mock 端到端
——normalize → mock 翻译 → ctex 注入 → 编译 → 判定，全链走产品 API）。
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from texlate import __version__
from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import AcquireResult, AcquireStatus, Fetcher, acquire_source
from texlate.compile.engine import engine_for, route_project
from texlate.compile.inject import InjectRejectError, find_main_tex, prepare_chinese
from texlate.compile.judge import judge
from texlate.compile.normalize import normalize_project
from texlate.latex.api import parse_file
from texlate.latex.reconstruct import reconstruct
from texlate.validate.l0 import validate_pair
from texlate.xlat.pipeline import ChunkIn, MockTranslator, XlatPipeline
from texlate.xlat.prompts import normalize_kind

if TYPE_CHECKING:
    from texlate.latex.model import ScanResult

app = typer.Typer(
    help="arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF。",
    no_args_is_help=True,
)

_DEFAULT_CACHE = Path.home() / ".cache" / "texlate" / "src"

_PH_LEFT_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]")


@app.callback()
def _main() -> None:
    """texlate。"""


@app.command()
def version() -> None:
    """打印版本号。"""
    typer.echo(f"texlate {__version__}")


# ---------------------------------------------------------------- fetch


@app.command()
def fetch(
    arxiv_id: Annotated[str, typer.Argument(help="arXiv id（新旧式/URL/vN 钉版均可）")],
    *,
    version: Annotated[
        int | None, typer.Option("--version", "-v", help="钉版本号")
    ] = None,
    cache: Annotated[
        Path, typer.Option("--cache", help="source-tier 缓存根")
    ] = _DEFAULT_CACHE,
) -> None:
    """取 arXiv e-print：HEAD → GET → sniff → unpack → locate，钉版落缓存。"""
    res = acquire_source(
        arxiv_id, fetcher=Fetcher(), cache=SourceCache(cache), version=version
    )
    _echo_acquire(res)
    if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
        raise typer.Exit(1)


def _echo_acquire(res: AcquireResult) -> None:
    out: dict[str, object] = {
        "status": res.status.value,
        "arxiv_id": res.arxiv_id,
        "resolved_version": res.resolved_version,
    }
    if res.entry is not None:
        out["dir"] = str(res.entry.dir)
        out["extracted"] = str(res.entry.extracted_dir)
        main = res.entry.meta.get("main_tex")
        if main:
            out["main_tex"] = main
    if res.warnings:
        out["warnings"] = res.warnings
    if res.detail:
        out["detail"] = res.detail
    typer.echo(json.dumps(out, ensure_ascii=False))


# ---------------------------------------------------------------- parse


@app.command()
def parse(
    path: Annotated[Path, typer.Argument(help=".tex 文件路径")],
    *,
    flatten: Annotated[
        bool, typer.Option("--flatten/--no-flatten", help="展开 \\input 图")
    ] = True,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="chunks.jsonl 输出路径")
    ] = None,
) -> None:
    """半解析单个 .tex：分块/占位符/警告统计，``--out`` 落逐块明细。"""
    res = parse_file(path, flatten=flatten)
    typer.echo(
        json.dumps(
            {
                "path": str(path),
                "chunks": len(res.chunks),
                "pieces": len(res.pieces),
                "placeholders": len(res.ph_map),
                "warnings": [f"{w.kind}@{w.pos}: {w.detail}" for w in res.warnings],
            },
            ensure_ascii=False,
        )
    )
    if out is not None:
        with out.open("w", encoding="utf-8") as fh:
            for c in res.chunks:
                fh.write(
                    json.dumps(
                        {
                            "id": c.id,
                            "context": c.context,
                            "env": c.env,
                            "placeholders": c.placeholders,
                            "content": c.content,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        typer.echo(f"chunks -> {out}", err=True)


# ---------------------------------------------------------------- run


@app.command()
def run(  # noqa: PLR0913 -- CLI 选项面即参数面
    source: Annotated[str, typer.Argument(help="arXiv id 或本地工程目录")],
    *,
    engine: Annotated[
        str, typer.Option("--engine", "-e", help="auto|xelatex|tectonic")
    ] = "auto",
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", "-w", help="工作目录（缺省 mkdtemp）"),
    ] = None,
    timeout: Annotated[
        float, typer.Option("--timeout", help="单引擎编译超时秒")
    ] = 240.0,
    cache: Annotated[
        Path, typer.Option("--cache", help="source-tier 缓存根")
    ] = _DEFAULT_CACHE,
    keep: Annotated[
        bool, typer.Option("--keep", help="保留工作目录（默认编译后删除）")
    ] = False,
) -> None:
    """Mock 端到端：取源/本地目录 → normalize → mock 翻译 → ctex 注入 → 编译 → 判定。

    翻译走 ``XlatPipeline(MockTranslator)`` + L0 校验器——全链产品 API，
    不触网（arxiv id 源走缓存/在线取源除外）。退出码：0 clean/partial，
    1 编译失败，2 路由拒绝。
    """
    src_dir = _resolve_source(source, cache)
    if src_dir is None:
        raise typer.Exit(1)

    work = work_dir or Path(tempfile.mkdtemp(prefix="texlate-run-"))
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src_dir, work)
    typer.echo(f"work dir: {work}", err=True)

    try:
        verdict = _mock_pipeline_run(work, engine, timeout)
        typer.echo(json.dumps(verdict, ensure_ascii=False, indent=2))
        status = verdict.get("status")
        if status == "reject":
            raise typer.Exit(2)
        if status not in ("clean", "partial"):
            raise typer.Exit(1)
    finally:
        if not keep and work_dir is None:
            shutil.rmtree(work, ignore_errors=True)


def _resolve_source(source: str, cache: Path) -> Path | None:
    """参数分流：存在的目录直接用，否则按 arXiv id 取源。"""
    p = Path(source)
    if p.is_dir():
        return p
    res = acquire_source(source, fetcher=Fetcher(), cache=SourceCache(cache))
    _echo_acquire(res)
    if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
        return None
    assert res.entry is not None  # noqa: S101 -- ok/hit 必有 entry
    return res.entry.extracted_dir


def _mock_pipeline_run(work: Path, engine_opt: str, timeout: float) -> dict:
    """工程目录上的 mock 全链（对齐 e2e_mock_bench 的 pipe 条件）。"""
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
    report["engine"] = eng_name
    report["normalize"] = normalize_project(work, eng_name, main_rel)
    report["translate"] = _mock_translate_tree(work)
    try:
        report["inject"] = prepare_chinese(work, main_rel)
    except InjectRejectError as e:
        report["status"] = "reject"
        report["route"]["reasons"] = [*route.reasons, e.reason]
        return report

    res = engine_for(eng_name).compile(work, main_rel, timeout=timeout, sandbox=True)
    v = judge(res, expect_cjk=True)
    report["compile"] = {
        "ok": res.ok,
        "timed_out": res.timed_out,
        "seconds": round(res.seconds, 2),
        "passes": res.passes,
        "rc": res.rc,
        "pdf_bytes": res.pdf_bytes,
        "first_error": res.log.first_error,
    }
    report["status"] = v.status
    report["verdict"] = {
        "status": v.status,
        "reasons": v.reasons,
        "n_errors": v.n_errors,
        "category": v.category,
        "cjk_chars": v.cjk_chars,
        "missing_chars": v.missing_chars,
    }
    return report


def _mock_translate_tree(root: Path) -> dict:
    """全部 .tex 走 XlatPipeline(MockTranslator) → splice 写回；返回汇总统计。"""
    scans: list[tuple[Path, ScanResult]] = []
    chunks: list[ChunkIn] = []
    for f in sorted(root.rglob("*.tex")):
        res = parse_file(f, flatten=False)
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(
            ChunkIn(
                chunk_id=f"{idx}:{c.id}",
                content=c.content,
                kind=normalize_kind(c.context),
            )
            for c in res.chunks
        )

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
        n_leftover += len(_PH_LEFT_RX.findall(zh))
    return {
        "files": n_files,
        "chunks": len(chunks),
        "fault_chunks": n_fault,
        "leftover_ph": n_leftover,
    }
