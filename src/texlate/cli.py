"""texlate 命令行入口。

M0 集成面：``fetch``（取源钉版）/ ``parse``（半解析分块）/ ``run``（mock 端到端
——normalize → mock 翻译 → ctex 注入 → 编译 → 判定，驱动在 ``texlate.e2e``）。
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from texlate import __version__
from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import AcquireResult, AcquireStatus, Fetcher, acquire_source
from texlate.e2e import mock_pipeline_run
from texlate.latex.api import parse_file

app = typer.Typer(
    help="arXiv LaTeX 源码 → LLM 段落级翻译 → ctex 重编译中文 PDF。",
    no_args_is_help=True,
)

_DEFAULT_CACHE = Path.home() / ".cache" / "texlate" / "src"


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

    翻译走 ``XlatPipeline(MockTranslator)`` + L0 校验器（驱动在 ``texlate.e2e``）
    ——全链产品 API，不触网（arxiv id 源走缓存/在线取源除外）。
    退出码：0 clean/partial，1 编译失败，2 路由拒绝。
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
        verdict = mock_pipeline_run(work, engine, timeout)
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
