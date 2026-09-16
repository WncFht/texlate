"""texlate 命令行入口。

M0 集成面：``fetch``（取源钉版）/ ``parse``（半解析分块）/ ``run``（mock 端到端
——normalize → mock 翻译 → ctex 注入 → 编译 → 判定，驱动在 ``texlate.e2e``）。
``run --server`` 为瘦客户端形态（web-layer §6）：本地不跑管线，任务提交远端
server API、轮询快照到终态、拉取产物。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
import webbrowser
import zipfile
from http import HTTPStatus
from pathlib import Path
from typing import IO, TYPE_CHECKING, Annotated
from urllib.parse import quote

import httpx
import typer

from texlate import __version__
from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import (
    AcquireResult,
    AcquireStatus,
    Fetcher,
    acquire_source,
    normalize_arxiv_id,
)
from texlate.compile import toolchain
from texlate.e2e import mock_pipeline_run
from texlate.latex.api import parse_file
from texlate.share import KEY_PART_FIELDS, ShareError, pack_share, unpack_share

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from texlate.xlat.pipeline import Translator

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
        int | None,
        typer.Option("--version", "-v", help="钉版本号", min=1),
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
        # meta.json 里主文件在 locate.main——顶层无 "main_tex" 键（曾读死键）。
        main = (res.entry.meta.get("locate") or {}).get("main")
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
    path: Annotated[
        Path,
        typer.Argument(
            help=".tex 文件路径", exists=True, dir_okay=False, readable=True
        ),
    ],
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
def run(  # noqa: C901, PLR0913 -- CLI 选项面即参数面 + 本地/瘦客户端双模分流
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
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="--server 产物下载目录"),
    ] = None,
    wait: Annotated[
        float, typer.Option("--wait", help="--server 终态等待上限秒")
    ] = 1800.0,
) -> None:
    """端到端：取源/本地目录 → normalize → mock 翻译 → ctex 注入 → 编译 → 判定。

    翻译走 ``XlatPipeline(MockTranslator)`` + L0 校验器（驱动在 ``texlate.e2e``）
    ——全链产品 API，不触网（arxiv id 源走缓存/在线取源除外）。
    退出码：0 clean/partial，1 编译失败，2 路由拒绝。

    ``--server URL`` 切换为瘦客户端：``POST /api/arxiv/{id}/translate`` →
    2s 快照轮询（web-layer §7 开放问题 1 明列的等价通道，不依赖 SSE
    客户端栈）→ 产物 sha256 校验下载。同 cache_key 重跑会自然
    attach 到进行中任务（409 duplicate_active 复用其 task_id）。
    """
    if engine not in ("auto", "xelatex", "tectonic"):
        typer.echo(
            f"unknown --engine {engine!r} (expect auto|xelatex|tectonic)", err=True
        )
        raise typer.Exit(2)
    if server is not None:
        code = _thin_run(
            source,
            server=server,
            engine=engine,
            model=model,
            api_key=api_key,
            base_url=base_url,
            out=out,
            wait=wait,
        )
        raise typer.Exit(code)
    if (
        any(v is not None for v in (model, api_key, base_url, out)) or wait != 1800.0  # noqa: PLR2004 -- 与签名缺省同一字面值
    ):
        typer.echo(
            "--model/--api-key/--base-url/--out/--wait 仅配合 --server 使用",
            err=True,
        )
        raise typer.Exit(2)

    src_dir = _resolve_source(source, cache)
    if src_dir is None:
        raise typer.Exit(1)

    # --work-dir 保护：已存在的非空目录绝不 rmtree（指错路径删整树的坑）；
    # 空目录/不存在 → 正常用作工作区。文件形态报错。
    work = work_dir or Path(tempfile.mkdtemp(prefix="texlate-run-"))
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
    typer.echo(f"work dir: {work}", err=True)

    try:
        verdict = mock_pipeline_run(work, engine, timeout)
        typer.echo(json.dumps(verdict, ensure_ascii=False, indent=2))
        status = verdict.get("status")
        if verdict.get("reject_at"):
            raise typer.Exit(2)  # 策略拒绝 (status=partial+reject_at): 保持 exit 2
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


# ---------------------------------------------------------------- run --server（瘦客户端）

#: 与 server/store.py TERMINAL_STATUSES 同集——瘦客户端不能 import server 层
#: （无 server extra 的安装形态下 cli 也要可用）。
_THIN_TERMINAL = frozenset(
    {"done", "partial", "fault", "cancelled", "interrupted", "needs_auth"}
)
_THIN_POLL_S = 2.0


def _thin_run(  # noqa: PLR0913 -- 与 run 的 --server 选项面一一对应
    source: str,
    *,
    server: str,
    engine: str,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    out: Path | None,
    wait: float,
) -> int:
    """瘦客户端主流程：提交任务 → 轮询到终态 → 下载产物。返回退出码。"""
    if Path(source).is_dir():
        typer.echo(
            "--server 模式只接 arXiv id/URL（本地目录请走 server /api/upload）",
            err=True,
        )
        return 2
    base, ver = normalize_arxiv_id(source)
    pinned = f"{base}v{ver}" if ver is not None else base

    headers: dict[str, str] = {}
    if api_key:
        headers["x-texlate-key"] = api_key
    if base_url:
        headers["x-texlate-base-url"] = base_url
    payload: dict[str, object] = {"options": {"engine": engine}}
    if model:
        payload["model"] = model

    try:
        with httpx.Client(
            base_url=server.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(120.0, connect=10.0),
        ) as client:
            task_id = _thin_submit(client, pinned, payload)
            if task_id is None:
                return 2
            status = _thin_wait(client, task_id, wait)
            if status is None:
                typer.echo(
                    f"等待超时（--wait {wait}s）；任务 {task_id} 仍在 server 上"
                    "——同参数重跑本命令即可 attach 续等",
                    err=True,
                )
                return 1
            artifacts = _thin_download(client, task_id, out, pinned)
            typer.echo(
                json.dumps(
                    {
                        "task_id": task_id,
                        "status": status,
                        "artifacts": artifacts,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if status in ("done", "partial"):
                return 0
            return 2 if status == "needs_auth" else 1
    except httpx.HTTPError as e:
        typer.echo(f"server 传输错: {e}", err=True)
        return 2


def _thin_submit(
    client: httpx.Client, pinned: str, payload: dict[str, object]
) -> str | None:
    """``POST /api/arxiv/{id}/translate`` → task_id；失败打 stderr 返回 None。

    409 ``duplicate_active`` 不是错误——复用其 task_id 自然 attach 到
    同 cache_key 的进行中任务（§2.1 dedup 语义）。
    """
    resp = client.post(f"/api/arxiv/{pinned}/translate", json=payload)
    if resp.status_code == HTTPStatus.CONFLICT:
        task_id = str(resp.json().get("task_id") or "")
        if task_id:
            typer.echo(f"attach 进行中任务 {task_id}", err=True)
            return task_id
    elif resp.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED):
        task_id = str(resp.json()["task_id"])
        typer.echo(f"task {task_id} → {resp.json().get('status')}", err=True)
        return task_id
    typer.echo(f"translate {resp.status_code}: {resp.text[:300]}", err=True)
    return None


def _thin_wait(client: httpx.Client, task_id: str, wait: float) -> str | None:
    """快照轮询到终态；状态行变化才打 stderr。超时返回 None。"""
    deadline = time.monotonic() + wait
    last = ""
    while True:
        resp = client.get(f"/api/task/{task_id}")
        if resp.status_code != HTTPStatus.OK:
            typer.echo(f"快照 {resp.status_code}: {resp.text[:200]}", err=True)
            return "lost"
        snap = resp.json()
        counters = snap.get("counters") or {}
        line = (
            f"{snap.get('status')}/{snap.get('stage') or '-'} "
            f"{snap.get('progress')}% chunks={counters.get('done', 0)}"
            f"/{counters.get('total', 0)} failed={counters.get('failed', 0)}"
        )
        if line != last:
            typer.echo(line, err=True)
            last = line
        status = str(snap.get("status"))
        if status in _THIN_TERMINAL:
            err = snap.get("error")
            if err:
                typer.echo(f"error: {err}", err=True)
            return status
        if time.monotonic() > deadline:
            return None
        time.sleep(_THIN_POLL_S)


def _thin_download(
    client: httpx.Client, task_id: str, out: Path | None, pinned: str
) -> dict[str, str]:
    """``GET /api/files/{id}`` 清单逐件下载，sha256 自验。返回 ``{kind: 路径}``。"""
    listing = client.get(f"/api/files/{task_id}")
    if listing.status_code != HTTPStatus.OK:
        typer.echo(f"产物清单 {listing.status_code}: {listing.text[:200]}", err=True)
        return {}
    artifacts = listing.json().get("artifacts") or {}
    dest = out or Path.cwd() / f"texlate-{pinned}-{task_id[:8]}"
    dest.mkdir(parents=True, exist_ok=True)
    got: dict[str, str] = {}
    for kind, rec in artifacts.items():
        url = str(rec.get("url") or "")
        if not url:
            continue
        fname = url.rsplit("/", 1)[-1] or str(kind)
        r = client.get(url)
        if r.status_code != HTTPStatus.OK:
            typer.echo(f"下载 {kind} {r.status_code}，跳过", err=True)
            continue
        blob = r.content
        sha = str(rec.get("sha256") or "")
        if sha and hashlib.sha256(blob).hexdigest() != sha:
            typer.echo(f"{kind} sha256 不符，跳过", err=True)
            continue
        target = dest / fname
        target.write_bytes(blob)
        got[str(kind)] = str(target)
        typer.echo(f"{kind} → {target}", err=True)
    return got


# ---------------------------------------------------------------- web


def _connect_url(host: str, port: int) -> str:
    """浏览器可点地址：通配/空绑定回环化。"""
    if host in ("0.0.0.0", "::", ""):  # noqa: S104 -- 比较非绑定：通配回环化
        return f"http://127.0.0.1:{port}"
    return f"http://{host}:{port}"


def _service_lock(
    root: Path, host: str, port: int
) -> tuple[IO[bytes] | None, str | None]:
    """``<data_dir>/service.lock`` 单实例锁（web-layer §6 本地形态）。

    返回 ``(fh, None)`` = 拿到锁——**fh 必须活到进程终止**（flock 随 fd
    关闭/进程退出自动释放）；``(None, url)`` = 锁被持有即已有实例在跑，
    url 取自锁文件元数据（缺席按 host/port 推）；``(None, None)`` = 退化
    放行（``TEXLATE_MODE=server`` 多副本部署 / 无 fcntl 平台 / 锁文件
    不可写——不加锁也不拦起服）。
    """
    from texlate.server.settings import server_mode  # noqa: PLC0415

    if server_mode() == "server":
        return None, None
    try:
        import fcntl  # noqa: PLC0415 -- 平台门：win/无 fcntl 退化为无锁
    except ImportError:
        return None, None
    try:
        fh = (root / "service.lock").open("a+b")
    except OSError:
        return None, None
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        url = ""
        try:
            fh.seek(0)
            meta = json.loads(fh.read().decode() or "{}")
            url = str(meta.get("url") or "")
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        fh.close()
        return None, url or _connect_url(host, port)
    # "a+b" 写恒落 EOF——truncate(0) 显式清零再写，免得上任持有者的
    # 元数据残留拼出非法 JSON（读侧解析失败会回退 host/port 推断）。
    fh.truncate(0)
    fh.write(json.dumps({"pid": os.getpid(), "url": _connect_url(host, port)}).encode())
    fh.flush()
    return fh, None


@app.command()
def web(
    *,
    host: Annotated[str, typer.Option("--host", help="绑定地址")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="端口")] = 8765,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir", help="数据目录（缺省 TEXLATE_DATA_DIR 或 ~/.texlate）"
        ),
    ] = None,
) -> None:
    """起 web 服务：FastAPI + SSE + 任务队列（需 ``texlate[server]`` extra）。

    local 形态单实例（web-layer §6）：``<data_dir>/service.lock`` flock
    被持有 → 浏览器打开已运行实例并退出，而不是端口冲突或静默双开。
    ``python -m texlate.server`` 是低层入口、不经此锁（瘦客户端自动
    拉起/容器内的预期通路）。
    """
    if data_dir is not None:
        os.environ["TEXLATE_DATA_DIR"] = str(data_dir.expanduser())
    try:
        import uvicorn  # noqa: PLC0415 -- server extra 延迟导入

        from texlate.server.app import create_app  # noqa: PLC0415
        from texlate.server.settings import data_dir as _data_dir  # noqa: PLC0415
    except ImportError:
        typer.echo(
            "web 需要 server extra：uv sync --extra server"
            "（或 pip install 'texlate[server]'）",
            err=True,
        )
        raise typer.Exit(1) from None
    _lock_fh, existing = _service_lock(_data_dir(), host, port)
    if existing is not None:
        typer.echo(
            f"texlate web 已在运行 → {existing}（service.lock 被持有）",
            err=True,
        )
        webbrowser.open(existing)
        return
    typer.echo(f"texlate web → http://{host}:{port}", err=True)
    uvicorn.run(create_app(), host=host, port=port)


# ---------------------------------------------------------------- export


@app.command()
def export(
    path: Annotated[
        Path, typer.Argument(help="EPUB/DOCX 文档（zip 内容嗅探，不看后缀）")
    ],
    *,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="输出路径（缺省 {stem}_bilingual{ext}）"),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="模型名（缺省 TEXLATE_MODEL）")
    ] = None,
    mock: Annotated[
        bool, typer.Option("--mock", help="MockTranslator 干跑（不触网）")
    ] = False,
) -> None:
    """EPUB/DOCX → 双语插译文档（原文段落后跟译文）。

    DRM 声明/fixed-layout/畸形包落翻译前拒开；中断留 ``{dst}.state/`` 自动续跑。
    """
    from texlate.export import export_document  # noqa: PLC0415 -- 重依赖延迟导入
    from texlate.export.common import ExportError  # noqa: PLC0415

    translator = _export_translator(model, mock=mock)
    try:
        report = export_document(path, out, translator)
    except ExportError as e:
        typer.echo(f"export: {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        f"{report.dst} — 插译 {report.translated}/{report.units}"
        f"（unchanged {report.unchanged} / skipped {report.skipped}"
        f" / fault {report.fault}）",
        err=True,
    )


def _export_translator(model: str | None, *, mock: bool) -> Translator:
    """worker._make_translator 的无 ctx 版：env/key → 网关，否则 Mock。"""
    from texlate.xlat.pipeline import (  # noqa: PLC0415
        GatewayTranslator,
        MockTranslator,
    )

    force = os.environ.get("TEXLATE_TRANSLATOR", "").lower()
    api_key = os.environ.get("TEXLATE_API_KEY", "")
    if mock or force == "mock" or (not api_key and force != "gateway"):
        return MockTranslator()
    from texlate.xlat.client import ChatClient  # noqa: PLC0415

    return GatewayTranslator(
        ChatClient(
            os.environ.get("TEXLATE_BASE_URL", "http://100.105.212.52:3003"), api_key
        ),
        model or os.environ.get("TEXLATE_MODEL", "") or "swe-2-medium",
    )


# ---------------------------------------------------------------- share

share_app = typer.Typer(
    help="社区共享译文缓存包（设计 docs/research/product/shared-cache.md）。",
    no_args_is_help=True,
)
app.add_typer(share_app, name="share")


def _share_data_root(data_dir: Path | None) -> Path:
    """数据根：``--data-dir`` > ``TEXLATE_DATA_DIR`` > ``~/.texlate``。

    与 ``settings.data_dir()`` 同序但**不 mkdir**——pack 是只读定位，
    找不到库由调用方报错，不为查询副作用建目录。
    """
    if data_dir is not None:
        return data_dir.expanduser()
    raw = os.environ.get("TEXLATE_DATA_DIR")
    return Path(raw).expanduser() if raw else Path.home() / ".texlate"


def _share_task_dir(arg: str, data_dir: Path | None) -> Path:
    """Pack 参数分流：已存在目录直接用；``t_*`` 形按任务 id 到数据根 ``tasks/`` 下找。"""
    p = Path(arg).expanduser()
    if p.is_dir():
        return p
    if arg.startswith("t_"):
        cand = _share_data_root(data_dir) / "tasks" / arg
        if cand.is_dir():
            return cand
        typer.echo(f"任务目录不存在: {cand}", err=True)
        raise typer.Exit(1)
    typer.echo(f"share pack: 既不是已存在目录也不像任务 id: {arg!r}", err=True)
    raise typer.Exit(1)


def _share_db(task_dir: Path, data_dir: Path | None) -> Path | None:
    """定位 ``texlate.db``：``--data-dir`` > 任务目录上跳（``tasks/t_*`` 形态）> 默认数据根。"""
    cands = [
        task_dir.parent.parent / "texlate.db",
        task_dir.parent / "texlate.db",
    ]
    if data_dir is not None:
        cands.insert(0, data_dir.expanduser() / "texlate.db")
    cands.append(_share_data_root(data_dir) / "texlate.db")
    for cand in cands:
        if cand.is_file():
            return cand
    return None


def _share_row(db: Path, task_id: str) -> dict[str, Any] | None:
    """只读开库取任务行——不走 ``Store.open()``（它有 DDL/迁移写副作用）。"""
    conn = sqlite3.connect(f"file:{quote(str(db), safe='/')}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def _share_fields(row: Mapping[str, Any]) -> tuple[str, int | None, str, str]:
    """任务行 → ``(arxiv_base, resolved_ver, model, target_lang)``；取不到显式报错。"""
    status = str(row.get("status") or "")
    if status not in ("done", "partial"):
        typer.echo(f"任务状态 {status!r} 不可打包（需 done|partial）", err=True)
        raise typer.Exit(1)
    raw_id = str(row.get("arxiv_id") or "")
    if not raw_id:
        typer.echo("任务行无 arxiv_id（upload/文档任务不参与共享寻址）", err=True)
        raise typer.Exit(1)
    base, ver = normalize_arxiv_id(raw_id)
    model = str(row.get("model") or "")
    lang = str(row.get("target_lang") or "")
    if not model or not lang:
        typer.echo("任务行 model/target_lang 为空，无法派生 share key", err=True)
        raise typer.Exit(1)
    return base, ver, model, lang


def _share_verify_pipeline(
    row: Mapping[str, Any], base: str, ver: int | None, model: str, lang: str
) -> None:
    """``cache_key`` 重算交叉验证——证明产物确实出自当前 ``PIPELINE_VERSION``。

    任务行 ``arxiv_id`` 存的是 resolved 钉版，而 ``cache_key_for`` 进键的是
    **请求时**版本（钉版请求 → ver、latest 请求 → None），两种形态都试。
    ``TEXLATE_CACHE_SCOPE=per_key`` 时材料含凭证指纹，无 key 无法重算 →
    降级为 stderr 告警（不阻断）。
    """
    from texlate.server.settings import cache_scope  # noqa: PLC0415
    from texlate.server.worker import cache_key_for  # noqa: PLC0415

    stored = str(row.get("cache_key") or "")
    if not stored:
        return
    if cache_scope() == "per_key":
        typer.echo(
            "per_key 分桶：cache_key 含凭证指纹无法重算校验 pipeline_ver"
            "——按当前版本记账",
            err=True,
        )
        return
    expect = {
        cache_key_for(arxiv_id=base, version=v, model=model, target_lang=lang)
        for v in (ver, None)
    }
    if stored not in expect:
        typer.echo(
            "cache_key 与当前 PIPELINE_VERSION 重算不符——产物出自不同版本"
            "管线，按现版本打包会错标 share key，拒绝",
            err=True,
        )
        raise typer.Exit(1)


def _share_glossary_hash(
    task_dir: Path, cfg: Mapping[str, Any], options: Mapping[str, Any]
) -> str:
    """``glossary_hash`` 组分：无自定义术语表层 → ``""``；有层则各层文件 sha256 复合。

    内置/分类默认层随 ``pipeline_ver`` 走不进指纹；自定义层 = 配置的
    glossary 路径（缺省 ``~/.texlate/glossary.yaml`` 若存在）+ 论文级
    ``base/glossary.local.yaml``。配置路径已死 → ShareError——宁缺不
    串桶，错标 ``""`` 会把自定义译文混进默认池。
    """
    from texlate.xlat.glossary import (  # noqa: PLC0415 -- share 子命令局部依赖
        LOCAL_GLOSSARY_NAME,
        USER_GLOSSARY_PATH,
    )

    files: list[Path] = []
    gpath = str(cfg.get("glossary") or options.get("glossary") or "")
    if gpath:
        gfile = Path(gpath).expanduser()
        if not gfile.is_file():
            msg = f"任务配置了 glossary 但文件不可读: {gpath}"
            raise ShareError(msg)
        files.append(gfile)
    elif USER_GLOSSARY_PATH.is_file():
        files.append(USER_GLOSSARY_PATH)
    local = task_dir / "base" / LOCAL_GLOSSARY_NAME
    if local.is_file():
        files.append(local)
    if not files:
        return ""
    h = hashlib.sha256()
    for f in files:
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def _share_out_is_file(out: Path) -> bool:
    """``-o`` 形态判定：已存在目录 → 目录；带后缀路径 → 文件；无后缀 → 目录。"""
    return not out.is_dir() and bool(out.suffix)


@share_app.command("pack")
def share_pack(
    task: Annotated[
        str,
        typer.Argument(help="任务目录（<data>/tasks/t_*）或任务 id（t_*）"),
    ],
    *,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="输出路径——目录/无后缀路径则其下落 {share_key}.share.zip；"
            "带后缀路径按给定名落盘；缺省 cwd",
        ),
    ] = None,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir", help="任务库目录（缺省 TEXLATE_DATA_DIR 或 ~/.texlate）"
        ),
    ] = None,
    contributor: Annotated[
        str | None,
        typer.Option("--contributor", help="manifest 贡献者标识（缺省匿名 c-<16hex>）"),
    ] = None,
) -> None:
    """本地任务产物 → ``{share_key}.share.zip``（opt-in 分享到社区缓存的第一步）。

    key_parts 七组分来源：``arxiv_id``/``version`` 取任务行钉版形
    （worker fetch 后落 ``{id}v{N}``）、``model``/``target_lang`` 取任务行、
    ``prompt_ver``/``pipeline_ver`` 取本装管线常量、``glossary_hash`` 由
    自定义术语表层内容派生——取不到一律显式报错，不编造进键。
    """
    from texlate.server.worker import PIPELINE_VERSION  # noqa: PLC0415
    from texlate.xlat.prompts import PROMPT_VERSION  # noqa: PLC0415

    task_dir = _share_task_dir(task, data_dir)
    db = _share_db(task_dir, data_dir)
    if db is None:
        typer.echo(
            "定位不到 texlate.db——任务目录需位于 <data>/tasks/ 下，"
            "或用 --data-dir 指数据根",
            err=True,
        )
        raise typer.Exit(1)
    row = _share_row(db, task_dir.name)
    if row is None:
        typer.echo(f"任务行不在库中: {task_dir.name} @ {db}", err=True)
        raise typer.Exit(1)
    base, ver, model, lang = _share_fields(row)
    _share_verify_pipeline(row, base, ver, model, lang)
    try:
        cfg = json.loads(str(row.get("config_json") or "{}"))
        if not isinstance(cfg, dict):
            cfg = {}
    except json.JSONDecodeError:
        cfg = {}
    try:
        opts = json.loads(str(row.get("options_json") or "{}"))
        if not isinstance(opts, dict):
            opts = {}
    except json.JSONDecodeError:
        opts = {}
    try:
        manifest: dict[str, object] = {
            "arxiv_id": base,
            "version": f"v{ver}" if ver is not None else "",
            "model": model,
            "prompt_ver": PROMPT_VERSION,
            "target_lang": lang,
            "glossary_hash": _share_glossary_hash(task_dir, cfg, opts),
            "pipeline_ver": PIPELINE_VERSION,
        }
        if contributor:
            manifest["contributor"] = contributor
        out_dir = (
            Path.cwd()
            if out is None
            else (out.parent if _share_out_is_file(out) else out)
        )
        bundle = pack_share(task_dir, manifest, out_dir=out_dir)
    except ShareError as e:
        typer.echo(f"share pack: {e}", err=True)
        raise typer.Exit(1) from None
    final = bundle
    if out is not None and _share_out_is_file(out) and bundle != out:
        bundle.replace(out)
        final = out
    typer.echo(
        json.dumps(
            {
                "share_key": bundle.name.removesuffix(".share.zip"),
                "path": str(final),
                "task_id": task_dir.name,
                "key_parts": {k: manifest[k] for k in KEY_PART_FIELDS},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@share_app.command("unpack")
def share_unpack(
    bundle: Annotated[
        Path,
        typer.Argument(
            help=".share.zip 包路径", exists=True, dir_okay=False, readable=True
        ),
    ],
    *,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="解包目录（缺省 cwd/{包名去后缀}）"),
    ] = None,
) -> None:
    """``.share.zip`` → 校验解包 + 打印 manifest 摘要。

    只机械校验格式/share_key 自洽/逐产物 sha256 对账——译文可信度由
    消费端重跑 splice/validate/compile 保证（shared-cache.md §5 信任
    模型），本命令不解语义无信任。
    """
    stem = bundle.name.removesuffix(".share.zip")
    if not stem or stem == bundle.name:
        stem = bundle.stem or "share-unpacked"
    dest = out or Path.cwd() / stem
    try:
        mf = unpack_share(bundle, dest)
    except ShareError as e:
        typer.echo(f"share unpack: {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        json.dumps(
            {
                "share_key": mf.share_key,
                "format": mf.fmt,
                "key_parts": mf.key_parts,
                "artifacts": {
                    name: {"sha256": a.sha256, "bytes": a.size}
                    for name, a in mf.artifacts.items()
                },
                "contributor": mf.contributor,
                "created_at": mf.created_at,
                "dest": str(dest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


# ---------------------------------------------------------------- tools

tools_app = typer.Typer(
    help="外部工具链管理（编译引擎探测/安装）。",
    no_args_is_help=True,
)
app.add_typer(tools_app, name="tools")


@tools_app.command("install-tectonic")
def tools_install_tectonic() -> None:
    """探测 tectonic（系统件/托管件/缺失）；缺失时下载安装到托管目录。

    走 ``compile.toolchain``：sha256 钉值校验 → 单文件提取 → 原子落位，
    托管落点 ``<data>/tools/``（``TEXLATE_DATA_DIR`` > ``~/.texlate``）。
    已可用即报落点退出；``TEXLATE_NO_DOWNLOAD``/CI 默认关自动下载——
    显式 ``TEXLATE_NO_DOWNLOAD=0`` 可在 CI 强制开。
    """
    resolved = toolchain.resolve_tool("tectonic")
    if resolved is not None:
        kind = "托管件" if resolved == toolchain.find_managed() else "系统件"
        typer.echo(f"tectonic: {kind} {resolved} —— 无需安装")
        return
    typer.echo("tectonic: 缺失（PATH 与托管目录均未命中）")
    if not toolchain.download_allowed():
        typer.echo(
            "自动下载已关闭（TEXLATE_NO_DOWNLOAD / CI）；"
            "显式 TEXLATE_NO_DOWNLOAD=0 可强制开启",
            err=True,
        )
        raise typer.Exit(1)
    try:
        path = toolchain.install_tectonic()
    except (
        OSError,
        RuntimeError,
        tarfile.TarError,
        zipfile.BadZipFile,
        httpx.HTTPError,
    ) as e:
        typer.echo(f"tectonic 安装失败：{e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"tectonic: 已安装 {toolchain.TECTONIC_VERSION} → {path}")
