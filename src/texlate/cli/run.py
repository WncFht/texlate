"""``run`` 命令：本地 mock 端到端 / ``--server`` 瘦客户端分流。

``mock_pipeline_run`` 经 ``_cli.`` 调用期解析——测试 monkeypatch
``cli.mock_pipeline_run`` 面守恒。
"""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

import typer

import texlate.cli as _cli
from texlate.arxiv.fetch import AcquireStatus
from texlate.cli._common import _CLI_PATH, _DEFAULT_CACHE, _is_dir, app
from texlate.cli._output import CliSink, console, status
from texlate.cli.fetch import _acquire, _echo_acquire
from texlate.cli.thin import _thin_run
from texlate.logsetup import configure_logging, level_from_flags
from texlate.pipecore import FRONT_MATTER_NAMES, NULL_SINK
from texlate.textutil import env_flag
from texlate.xlat.client import API_DIALECTS


@app.command()
def run(  # noqa: C901, PLR0913 -- CLI 选项面即参数面 + 本地/瘦客户端双模分流
    source: Annotated[str, typer.Argument(help="arXiv id 或本地工程目录")],
    *,
    engine: Annotated[
        str, typer.Option("--engine", "-e", help="auto|xelatex|tectonic")
    ] = "auto",
    work_dir: Annotated[
        Path | None,
        typer.Option(
            "--work-dir",
            "-w",
            help="工作目录（缺省 mkdtemp）",
            click_type=_CLI_PATH,
        ),
    ] = None,
    timeout: Annotated[
        float, typer.Option("--timeout", help="单引擎编译超时秒", min=0.0)
    ] = 240.0,
    cache: Annotated[
        Path,
        typer.Option("--cache", help="source-tier 缓存根", click_type=_CLI_PATH),
    ] = _DEFAULT_CACHE,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="离线模式：取源只用本地 src-cache、零网络请求"
            "（env TEXLATE_OFFLINE=1 等效；--server 模式不生效）",
        ),
    ] = False,
    keep: Annotated[
        bool, typer.Option("--keep", help="保留工作目录（默认编译后删除）")
    ] = False,
    server: Annotated[
        str | None,
        typer.Option(
            "--server",
            help="远端 texlate server URL——任务走 API 提交而非本地管线"
            "（瘦客户端；web-layer §6）",
        ),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="任务模型（仅 --server）")
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="BYOK key（仅 --server，x-texlate-key）"),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url", help="上游 LLM 网关（仅 --server，x-texlate-base-url）"
        ),
    ] = None,
    dialect: Annotated[
        str | None,
        typer.Option(
            "--dialect",
            help="LLM 网关方言 auto|openai|anthropic|responses"
            "（仅 --server，x-texlate-dialect）",
        ),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="--server 产物下载目录", click_type=_CLI_PATH),
    ] = None,
    wait: Annotated[
        float | None,
        typer.Option("--wait", help="--server 终态等待上限秒（缺省 1800）", min=0.0),
    ] = None,
    front_matter: Annotated[
        str | None,
        typer.Option(
            "--front-matter",
            help="preamble 前置内容翻译白名单（逗号分隔 abstract,title,author；"
            "未列即关。缺省走服务端/env 默认 abstract,title）",
        ),
    ] = None,
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="日志加噪：-v=INFO -vv=DEBUG（覆盖 callback 位同名旗标）",
        ),
    ] = 0,
    quiet: Annotated[
        int,
        typer.Option(
            "--quiet",
            "-q",
            count=True,
            help="降噪：-q=ERROR 且关实况进度（-qq=CRITICAL）",
        ),
    ] = 0,
) -> None:
    """端到端：取源/本地目录 → normalize → mock 翻译 → ctex 注入 → 编译 → 判定。

    翻译走 ``XlatPipeline(MockTranslator)`` + L0 校验器（驱动在 ``texlate.e2e``）
    ——全链产品 API，不触网（arxiv id 源走缓存/在线取源除外）。

    ``--offline``/``TEXLATE_OFFLINE=1``：取源零网络——本地目录源无
    影响；arXiv id 源只查本地 src-cache（钉版精确查、未钉版取已缓存
    最高版），无缓存报 ``offline_no_cache`` 退出 1，不静默降级联网。

    退出码：0 = clean/partial（远端 done/partial）；1 = 编译失败（修复链
    走尽仍无 pdf），--server 侧另含终态 fault/cancelled/interrupted、
    快照失联（lost）与 --wait 超时；2 = 用法错（未知引擎/--server 选项
    脱离/--work-dir 非空/本地目录喂 --server）与策略拒绝
    （status=partial+reject_at），--server 侧另含提交被拒、传输错/
    非法 JSON 响应与 needs_auth 终态。

    ``--server URL`` 切换为瘦客户端：``POST /api/arxiv/{id}/translate`` →
    2s 快照轮询（web-layer §7 开放问题 1 明列的等价通道，不依赖 SSE
    客户端栈）→ 产物 sha256 校验下载。同 cache_key 重跑会自然
    attach 到进行中任务（409 duplicate_active 复用其 task_id）。
    """
    # typer min=0.0 拦不住 nan（nan<0 恒假）——非有限秒数让超时/等待语义失效
    if not math.isfinite(timeout) or (wait is not None and not math.isfinite(wait)):
        typer.echo("--timeout/--wait 需要有限秒数", err=True)
        raise typer.Exit(2)
    if not source.strip():
        typer.echo("source 为空——需要 arXiv id 或本地工程目录", err=True)
        raise typer.Exit(2)
    if engine not in ("auto", "xelatex", "tectonic"):
        typer.echo(
            f"unknown --engine {engine!r} (expect auto|xelatex|tectonic)", err=True
        )
        raise typer.Exit(2)
    dialect = _dialect_opt(dialect)
    fm = _front_matter_opt(front_matter)
    if server is not None:
        code = _thin_run(
            source,
            server=server,
            engine=engine,
            model=model,
            api_key=api_key,
            base_url=base_url,
            dialect=dialect,
            out=out,
            wait=1800.0 if wait is None else wait,
            front_matter=fm,
            quiet=quiet > 0,
        )
        raise typer.Exit(code)
    if any(v is not None for v in (model, api_key, base_url, dialect, out, wait)):
        typer.echo(
            "--model/--api-key/--base-url/--dialect/--out/--wait 仅配合 --server 使用",
            err=True,
        )
        raise typer.Exit(2)

    off = offline or env_flag("TEXLATE_OFFLINE", default=False)
    if not _is_dir(Path(source).expanduser()) and not quiet:
        status(f"fetch {source}" + (" (offline)" if off else ""))
    src_dir = _resolve_source(source, cache, offline=off)
    if src_dir is None:
        raise typer.Exit(1)

    # --work-dir 保护由 _populate_work_dir 收口；整个填充+管线都在 try 内，
    # 保证 mkdtemp 临时目录在 copytree 失败时也清掉（原先泄漏）。
    work = (
        work_dir.expanduser()
        if work_dir is not None
        else Path(tempfile.mkdtemp(prefix="texlate-run-"))
    )
    try:
        _populate_work_dir(src_dir, work)
        typer.echo(f"work dir: {work}", err=True)
        # 子命令位 -v/-q 覆盖 callback 已装的级别；未给时保留全局/缺省态。
        if verbose or quiet:
            configure_logging(level=level_from_flags(verbose, quiet), console=console)
        sink = NULL_SINK if quiet else CliSink()
        verdict = _cli.mock_pipeline_run(
            work, engine, timeout, front_matter=fm, sink=sink
        )
        typer.echo(json.dumps(verdict, ensure_ascii=False, indent=2))
        final = verdict.get("status")
        if verdict.get("reject_at"):
            raise typer.Exit(2)  # 策略拒绝 (status=partial+reject_at): 保持 exit 2
        if final not in ("clean", "partial"):
            raise typer.Exit(1)
    finally:
        if not keep and work_dir is None:
            shutil.rmtree(work, ignore_errors=True)


def _dialect_opt(raw: str | None) -> str | None:
    """``--dialect`` 白名单校验；非法值 exit 2。"""
    if raw is None or raw in API_DIALECTS:
        return raw
    typer.echo(f"unknown --dialect {raw!r} (expect {sorted(API_DIALECTS)})", err=True)
    raise typer.Exit(2)


def _front_matter_opt(raw: str | None) -> frozenset[str] | None:
    """``--front-matter`` 逗号清单 → frozenset 白名单；非法名 exit 2。"""
    if raw is None:
        return None
    names = {x.strip() for x in raw.split(",") if x.strip()}
    bad = names - FRONT_MATTER_NAMES
    if bad:
        typer.echo(
            f"unknown --front-matter {sorted(bad)!r}"
            f" (expect {sorted(FRONT_MATTER_NAMES)})",
            err=True,
        )
        raise typer.Exit(2)
    return frozenset(names)


def _populate_work_dir(src_dir: Path, work: Path) -> None:
    """``work`` 目录校验 + 拷工程：已存在非空目录绝不 rmtree。

    指错路径删整树的坑——空目录/不存在正常用作工作区；文件形态报错
    exit 2，OSError（拷贝中途盘满/权限）干净报错 exit 1。
    """
    try:
        if work.exists():
            if not work.is_dir():
                typer.echo(f"--work-dir 不是目录: {work}", err=True)
                raise typer.Exit(2)
            if any(work.iterdir()):
                typer.echo(
                    f"--work-dir 已存在且非空，拒绝覆盖删除: {work}\n"
                    "（请换路径或自行清空后重试）",
                    err=True,
                )
                raise typer.Exit(2)
            shutil.copytree(src_dir, work, dirs_exist_ok=True)
        else:
            shutil.copytree(src_dir, work)
    except OSError as e:
        typer.echo(f"工作目录准备失败 {work}: {e}", err=True)
        raise typer.Exit(1) from None


def _resolve_source(source: str, cache: Path, *, offline: bool = False) -> Path | None:
    """参数分流：存在的目录直接用，否则按 arXiv id 取源。"""
    p = Path(source).expanduser()
    if _is_dir(p):
        return p
    res = _acquire(source, cache, offline=offline)
    _echo_acquire(res)
    if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
        return None
    assert res.entry is not None  # noqa: S101 -- ok/hit 必有 entry
    return res.entry.extracted_dir
