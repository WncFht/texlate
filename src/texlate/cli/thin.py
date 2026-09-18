"""``run --server`` 瘦客户端：任务提交 → 2s 快照轮询 → 产物 sha256 自验下载。"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import typer

from texlate.arxiv.fetch import normalize_arxiv_id, valid_id
from texlate.cli._common import _is_dir

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

#: 与 server/store.py TERMINAL_STATUSES 同集——瘦客户端不能 import server 层
#: （无 server extra 的安装形态下 cli 也要可用）。
_THIN_TERMINAL = frozenset(
    {"done", "partial", "fault", "cancelled", "interrupted", "needs_auth"}
)
_THIN_POLL_S = 2.0


def _thin_run(  # noqa: PLR0911, PLR0913 -- 与 run 的 --server 选项面一一对应
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
    if _is_dir(Path(source).expanduser()):
        typer.echo(
            "--server 模式只接 arXiv id/URL（本地目录请走 server /api/upload）",
            err=True,
        )
        return 2
    base, ver = normalize_arxiv_id(source)
    if not valid_id(base):
        # 非法 id 经 httpx dot-segment 归一化会逃逸 /api/arxiv/ 命名空间
        typer.echo(f"非法 arXiv id: {source}", err=True)
        return 2
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
            # lost = 快照通道已失联（清单必同挂）；needs_auth = 任务未产出
            # ——两者跳过产物下载，其余终态照试（fault/interrupted 可能有部分件）
            artifacts = (
                {}
                if status in ("lost", "needs_auth")
                else _thin_download(client, task_id, out, pinned)
            )
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
    except (httpx.HTTPError, httpx.InvalidURL, json.JSONDecodeError) as e:
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
        body = resp.json()
        task_id = str(body.get("task_id") or "") if isinstance(body, dict) else ""
        if task_id:
            typer.echo(f"attach 进行中任务 {task_id}", err=True)
            return task_id
    elif resp.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED):
        body = resp.json()
        task_id = str(body.get("task_id") or "") if isinstance(body, dict) else ""
        if task_id:
            typer.echo(f"task {task_id} → {body.get('status')}", err=True)
            return task_id
        # 畸形 2xx（缺 task_id）落通用错误行——不当成功 attach
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
        if not isinstance(snap, dict):
            typer.echo(f"快照非法（非对象 JSON）: {resp.text[:200]}", err=True)
            return "lost"
        counters = snap.get("counters")
        if not isinstance(counters, dict):
            counters = {}
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
    body = listing.json()
    artifacts = body.get("artifacts") if isinstance(body, dict) else None
    if not isinstance(artifacts, dict):
        artifacts = {}
    dest = (
        out.expanduser()
        if out is not None
        else Path.cwd() / f"texlate-{pinned}-{task_id[:8]}"
    )
    got: dict[str, str] = {}
    ensured = False
    dest_new = False  # 本调用新建的目录——零产物/全失败时回收空壳
    for kind, rec in artifacts.items():
        if not isinstance(rec, dict):
            continue
        if not ensured:
            dest_new = not dest.exists()
            try:
                dest.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                typer.echo(f"产物目录不可写 {dest}: {e}", err=True)
                return got
            ensured = True
        path = _thin_fetch_one(client, dest, str(kind), rec)
        if path is not None:
            got[str(kind)] = path
    if dest_new and not got:
        with contextlib.suppress(OSError):
            dest.rmdir()
    return got


def _thin_fetch_one(
    client: httpx.Client, dest: Path, kind: str, rec: Mapping[str, Any]
) -> str | None:
    r"""单产物流式下载：``.{name}.part`` 临时件 + sha256 过了才 rename。

    中断/校验不符不留半成品正名件；产物名取 url 末段，``.``/``..``/``\\``
    非法名跳过（防 ``dest`` 外逃逸）。失败打 stderr 返回 None。
    """
    url = str(rec.get("url") or "")
    if not url:
        return None
    fname = url.rsplit("/", 1)[-1] or str(kind)
    if fname in (".", "..") or "\\" in fname:
        typer.echo(f"{kind} 产物名非法 {fname!r}，跳过", err=True)
        return None
    target = dest / fname
    tmp = target.with_name(f".{fname}.part")
    digest = ""
    try:
        with client.stream("GET", url) as r:
            if r.status_code != HTTPStatus.OK:
                typer.echo(f"下载 {kind} {r.status_code}，跳过", err=True)
            else:
                h = hashlib.sha256()
                with tmp.open("wb") as fh:
                    for chunk in r.iter_bytes():
                        h.update(chunk)
                        fh.write(chunk)
                digest = h.hexdigest()
    except (httpx.HTTPError, OSError) as e:
        typer.echo(f"下载 {kind} 失败: {e}，跳过", err=True)
    if not digest:
        tmp.unlink(missing_ok=True)
        return None
    sha = str(rec.get("sha256") or "")
    if sha and digest != sha:
        typer.echo(f"{kind} sha256 不符，跳过", err=True)
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(target)
    typer.echo(f"{kind} → {target}", err=True)
    return str(target)
