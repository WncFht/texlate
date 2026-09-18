"""``fetch`` 命令 + ``_acquire``/``_echo_acquire`` 取源收口件。

``Fetcher`` 经 ``_cli.Fetcher`` 调用期解析——测试 monkeypatch ``cli.Fetcher``
面守恒（``worker.seams.X`` 同款缝）。
"""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 -- typer eval_str 解析 Annotated 实参
from typing import Annotated

import typer

import texlate.cli as _cli
from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import AcquireResult, AcquireStatus, acquire_source
from texlate.cli._common import _CLI_PATH, _DEFAULT_CACHE, app
from texlate.textutil import env_flag


@app.command()
def fetch(
    arxiv_id: Annotated[str, typer.Argument(help="arXiv id（新旧式/URL/vN 钉版均可）")],
    *,
    version: Annotated[
        int | None,
        typer.Option("--version", "-v", help="钉版本号", min=1),
    ] = None,
    cache: Annotated[
        Path,
        typer.Option("--cache", help="source-tier 缓存根", click_type=_CLI_PATH),
    ] = _DEFAULT_CACHE,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="离线模式：只用本地 src-cache、零网络请求（env TEXLATE_OFFLINE=1 等效）",
        ),
    ] = False,
) -> None:
    """取 arXiv e-print：HEAD → GET → sniff → unpack → locate，钉版落缓存。

    ``--offline``/``TEXLATE_OFFLINE=1``：跳过全部网络调用——钉版查
    ``{id}v{ver}``、未钉版取已缓存最高版；无缓存报 ``offline_no_cache``
    退出 1，不静默降级上网。
    """
    res = _acquire(
        arxiv_id,
        cache,
        version=version,
        offline=offline or env_flag("TEXLATE_OFFLINE", default=False),
    )
    _echo_acquire(res)
    if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
        raise typer.Exit(1)


def _acquire(
    arxiv_id: str, cache: Path, *, version: int | None = None, offline: bool = False
) -> AcquireResult:
    """``acquire_source`` 收口：``Fetcher`` context manager 管 httpx.Client 池。

    缓存根/条目探测的 ``OSError``（ENAMETOOLONG/EACCES 等）归一 ``error``
    JSON + exit 1——不穿透成 traceback。
    """
    try:
        with _cli.Fetcher() as fetcher:
            return acquire_source(
                arxiv_id,
                fetcher=fetcher,
                cache=SourceCache(cache.expanduser()),
                version=version,
                offline=offline,
            )
    except OSError as e:
        typer.echo(
            json.dumps(
                {
                    "status": AcquireStatus.ERROR.value,
                    "arxiv_id": arxiv_id,
                    "resolved_version": None,
                    "detail": f"os_error:{e}",
                },
                ensure_ascii=False,
            )
        )
        raise typer.Exit(1) from None


def _echo_acquire(res: AcquireResult) -> None:
    out: dict[str, object] = {
        "status": res.status.value,
        "arxiv_id": res.arxiv_id,
        "resolved_version": res.resolved_version,
    }
    if res.entry is not None:
        out["dir"] = str(res.entry.dir)
        out["extracted"] = str(res.entry.extracted_dir)
        # meta.json 里主文件在 locate.main——顶层无 "main_tex" 键（曾读死键）。
        main = (res.entry.meta.get("locate") or {}).get("main")
        if main:
            out["main_tex"] = main
    if res.warnings:
        out["warnings"] = res.warnings
    if res.detail:
        out["detail"] = res.detail
    typer.echo(json.dumps(out, ensure_ascii=False))
