"""``run --server`` 瘦客户端：任务提交 → SSE 实况（轮询兜底）→ 产物 sha256 自验下载。"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import time
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import typer

from texlate.arxiv.fetch import normalize_arxiv_id, valid_id
from texlate.cli._common import _is_dir
from texlate.cli._output import (
    _FALLBACK_DIV,
    console,
    fixloop_round_line,
    log_line_filtered,
    make_translate_progress,
    status,
)
from texlate.pipecore import FRONT_MATTER_NAMES

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from rich.progress import Progress, TaskID

#: 与 server/store.py TERMINAL_STATUSES 同集——瘦客户端不能 import server 层
#: （无 server extra 的安装形态下 cli 也要可用）。
_THIN_TERMINAL = frozenset(
    {"done", "partial", "fault", "cancelled", "interrupted", "needs_auth"}
)
_THIN_POLL_S = 2.0
#: SSE 断流带 ``Last-Event-ID`` 重连上限——尽后剩余预算归 ``_thin_wait`` 轮询。
_SSE_RETRIES = 2
#: server 回收 task_id 白名单形（``new_task_id`` 产 ``t_``+hex；测试桩
#: ``t_thin*`` 形兼容到 ``[A-Za-z0-9_-]``）——回收值直拼 URL 路径与
#: 下载 dest 目录名，``/`` ``\\`` ``.`` 形会穿出 ``/api/task/`` namespace
#: 或逃逸 dest 仓外，必须在 ``_thin_submit`` 边界挡下。
_THIN_TASK_ID_RX = re.compile(r"t_[A-Za-z0-9_-]+")


def _thin_run(  # noqa: C901, PLR0911, PLR0913 -- 与 run 的 --server 选项面一一对应
    source: str,
    *,
    server: str,
    engine: str,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    dialect: str | None,
    out: Path | None,
    wait: float,
    front_matter: frozenset[str] | None = None,
    quiet: bool = False,
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
    if dialect:
        headers["x-texlate-dialect"] = dialect
    opts: dict[str, object] = {"engine": engine}
    if front_matter is not None:
        # 显式全集 dict——未列名 = 关（不落服务端缺省，CLI 白名单语义）；
        # 键集单源 ``pipecore.FRONT_MATTER_NAMES``，sorted 保 wire 字节确定
        opts["front_matter"] = {
            k: k in front_matter for k in sorted(FRONT_MATTER_NAMES)
        }
    payload: dict[str, object] = {"options": opts}
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
            final = (
                _thin_wait(client, task_id, wait, quiet=True)
                if quiet
                else _thin_follow(client, task_id, wait)
            )
            if final is None:
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
                if final in ("lost", "needs_auth")
                else _thin_download(client, task_id, out, pinned)
            )
            typer.echo(
                json.dumps(
                    {
                        "task_id": task_id,
                        "status": final,
                        "artifacts": artifacts,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if final in ("done", "partial"):
                return 0
            return 2 if final == "needs_auth" else 1
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
        if _THIN_TASK_ID_RX.fullmatch(task_id):
            typer.echo(f"attach 进行中任务 {task_id}", err=True)
            return task_id
    elif resp.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED):
        body = resp.json()
        task_id = str(body.get("task_id") or "") if isinstance(body, dict) else ""
        if _THIN_TASK_ID_RX.fullmatch(task_id):
            typer.echo(f"task {task_id} → {body.get('status')}", err=True)
            return task_id
        # 畸形 2xx（缺/非法 task_id）落通用错误行——不当成功 attach
    typer.echo(f"translate {resp.status_code}: {resp.text[:300]}", err=True)
    return None


def _snapshot_line(snap: Mapping[str, Any]) -> str:
    """任务快照行 → 状态行文本（轮询与 SSE ``snapshot``/``resync`` 帧同形）。"""
    counters = snap.get("counters")
    if not isinstance(counters, dict):
        counters = {}
    return (
        f"{snap.get('status')}/{snap.get('stage') or '-'} "
        f"{snap.get('progress')}% chunks={counters.get('done', 0)}"
        f"/{counters.get('total', 0)} failed={counters.get('failed', 0)}"
    )


def _thin_wait(
    client: httpx.Client, task_id: str, wait: float, *, quiet: bool = False
) -> str | None:
    """快照轮询到终态；状态行变化才打 stderr（``quiet`` 全抑）。超时返回 None。"""
    deadline = time.monotonic() + wait
    last = ""
    while True:
        # 单次快照请求不超剩余预算——连接 wedged 时 --wait 仍作数
        resp = client.get(
            f"/api/task/{task_id}",
            timeout=min(120.0, max(1.0, deadline - time.monotonic())),
        )
        if resp.status_code != HTTPStatus.OK:
            typer.echo(f"快照 {resp.status_code}: {resp.text[:200]}", err=True)
            return "lost"
        snap = resp.json()
        if not isinstance(snap, dict):
            typer.echo(f"快照非法（非对象 JSON）: {resp.text[:200]}", err=True)
            return "lost"
        line = _snapshot_line(snap)
        if line != last:
            if not quiet:
                typer.echo(line, err=True)
            last = line
        st = str(snap.get("status"))
        if st in _THIN_TERMINAL:
            err = snap.get("error")
            if err:
                typer.echo(f"error: {err}", err=True)
            return st
        if time.monotonic() > deadline:
            return None
        time.sleep(_THIN_POLL_S)


def _thin_follow(client: httpx.Client, task_id: str, wait: float) -> str | None:
    """SSE 实况跟随 → 终态 status；``wait<=0``/非 SSE/重连尽 → ``_thin_wait`` 兜底。

    ``GET /api/task/{id}`` 带 ``Accept: text/event-stream``——Content-Type 不符
    即关流回轮询（MockTransport/无 SSE 的旧 server 全走兜底路径）。断流带
    ``Last-Event-ID`` 重连 ``_SSE_RETRIES`` 次（``task_events`` 重放补齐），
    尽后剩余等待预算归快照轮询。超时返回 None。
    """
    if wait <= 0:
        return _thin_wait(client, task_id, wait)
    deadline = time.monotonic() + wait
    follow = _SseFollow(client, task_id)
    retries = 0
    while True:
        try:
            kind, value = follow.stream_once(deadline)
        except httpx.HTTPError as e:
            kind, value = "retry", str(e)
        if kind == "status":
            return value
        if kind == "timeout":
            return None
        remaining = deadline - time.monotonic()
        if kind == "poll" or retries >= _SSE_RETRIES or remaining <= 0:
            if remaining <= 0:
                return None
            reason = "非 SSE 响应" if kind == "poll" else f"流断（{value}）"
            typer.echo(f"{reason}——回退快照轮询", err=True)
            return _thin_wait(client, task_id, remaining)
        retries += 1


def l2_done_line(p: Mapping[str, Any]) -> str | None:
    """``l2`` 帧 → 状态行文本；非 ``done`` 相位 ``None``（``CliSink._on_l2`` 同口径）。"""
    if p.get("phase") != "done":
        return None
    if not p.get("enabled"):
        return "l2 skipped"
    return (
        f"l2 done retranslated={p.get('retranslated', 0)}"
        f" fallback={p.get('fallback', 0)} errors={p.get('errors', 0)}"
    )


def fixloop_frame_line(p: Mapping[str, Any]) -> str | None:
    """``fixloop`` round/done 帧 → 状态行文本；其余相位 ``None``（``CliSink`` 同口径）。"""
    phase = p.get("phase")
    if phase == "round":
        r = p.get("round")
        return fixloop_round_line(r) if isinstance(r, dict) else f"fixloop round {r}"
    if phase == "done":
        cell = p.get("cell") or {}
        n = len(cell.get("rounds") or [])
        return f"fixloop done verdict={cell.get('verdict') or '—'} rounds={n}"
    return None


class _ChunkProgress:
    """chunk 计数 → tty 进度条 / 非 tty 退化行的 sink 无关策略件。

    tty 下 ``make_translate_progress`` Live 条 advance；非 tty 按
    ``_output._FALLBACK_DIV`` 节奏节流单行。
    ``close()`` 停 Live——断流/终帧/回轮询前必须收工，否则刷新区残留。
    ``CliSink._on_translate``/``_finish_translate`` 同策，拟迁 ``_output.py``
    供两 sink 共用。
    """

    def __init__(self, label: str = "chunks") -> None:
        self._label = label
        self._progress: Progress | None = None
        self._task: TaskID | None = None
        self._total = 0

    def update(self, done: int, total: int | None = None) -> None:
        """新 ``done`` 计数（可携新 ``total``）→ 进度条 advance / 退化行节流。"""
        if total:
            self._total = total
        if console.is_terminal and self._total:
            if self._progress is None:
                self._progress = make_translate_progress()
                self._progress.start()
                self._task = self._progress.add_task("translate", total=self._total)
            self._progress.update(self._task, completed=done)
        elif self._total and (
            done >= self._total or done % max(1, self._total // _FALLBACK_DIV) == 0
        ):
            console.print(f"  {self._label} {done}/{self._total}", style="dim")

    def close(self) -> None:
        """进度条收工——断流/终帧/回轮询前必须停 Live，否则刷新区残留。"""
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._task = None


class _SseFollow:
    """单任务 SSE 消费端：帧解析 → stderr 渲染；``_last_id`` 水位跨重连任。

    帧面（``server/events.py`` wire 协议）：``id:``/``event:``/``data:`` 字段 +
    空行分发、``:`` 前缀 ping 注释行。事件类型：``snapshot``（连接首帧，
    seq=0 现场合成）、``stage``/``chunk``/``log``/``warning``/``error``/
    ``l2``/``fixloop``/``precheck`` 实况帧、``resync``（重放缺口提示——
    拉新快照重置水位）、``done`` 终帧。
    """

    def __init__(self, client: httpx.Client, task_id: str) -> None:
        self._client = client
        self._task_id = task_id
        self._last_id = 0
        self._terminal_hint: str | None = None
        self._chunk_progress = _ChunkProgress()

    def stream_once(self, deadline: float) -> tuple[str, str | None]:
        """开一路 SSE 流消费到终帧/断流/超时 → ``(kind, value)``。

        ``kind`` ∈ ``status``（终态，value=status）/ ``poll``（响应非 SSE——
        回轮询）/ ``retry``（流早夭——带 ``_last_id`` 续放）/ ``timeout``
        （等待预算尽）。
        """
        headers = {"Accept": "text/event-stream"}
        if self._last_id:
            headers["Last-Event-ID"] = str(self._last_id)
        try:
            # 读超时钉剩余等待预算——挂死连接的 stall 不得越过 --wait
            with self._client.stream(
                "GET",
                f"/api/task/{self._task_id}",
                headers=headers,
                timeout=min(120.0, max(1.0, deadline - time.monotonic())),
            ) as resp:
                if resp.status_code != HTTPStatus.OK:
                    return "status", "lost"
                if (
                    "text/event-stream"
                    not in resp.headers.get("content-type", "").lower()
                ):
                    return "poll", None
                return self._consume(resp, deadline)
        finally:
            self._chunk_progress.close()

    def _consume(self, resp: httpx.Response, deadline: float) -> tuple[str, str | None]:
        """``iter_lines`` 帧循环：字段累积 → 空行 ``_dispatch`` → deadline 逐行查。"""
        event = "message"
        data: list[str] = []
        for raw in resp.iter_lines():
            if time.monotonic() > deadline:
                return "timeout", None
            line = raw.rstrip("\r")
            if not line:
                out = self._dispatch(event, data)
                if out is not None:
                    return out
                event, data = "message", []
                continue
            if line.startswith(":"):
                continue  # ping 注释行（sse-starlette ping=15s 保活）
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
            elif field == "id":
                with contextlib.suppress(ValueError):
                    self._last_id = int(value)
        # 流尽无 done 帧：snapshot 已终态 → 报终态；否则连接早夭 → 续放
        if self._terminal_hint is not None:
            return "status", self._terminal_hint
        return "retry", "流早夭"

    def _dispatch(  # noqa: C901, PLR0912 -- 事件类型面即分支面（每型独立渲染）
        self, event: str, data: list[str]
    ) -> tuple[str, str | None] | None:
        """单帧渲染分发 → ``("status", s)`` 收 done 帧；其余 ``None`` 续读。"""
        if not data:
            return None  # ping 事件帧/裸注释——无载荷不渲
        try:
            payload = json.loads("\n".join(data))
        except json.JSONDecodeError:
            return None  # 畸形帧丢不炸
        if not isinstance(payload, dict):
            payload = {}
        if event == "snapshot":
            self._on_snapshot(payload)
        elif event == "stage":
            status(
                f"{payload.get('stage') or '?'} {payload.get('progress', 0)}%"
                f" {payload.get('message') or ''}".rstrip()
            )
        elif event == "chunk":
            self._on_chunk(payload)
        elif event == "log":
            line = str(payload.get("line") or "")
            if not log_line_filtered(line):
                console.print(line, style="dim", highlight=False)
        elif event == "warning":
            console.print(
                f"warning {payload.get('code') or ''}: {payload.get('message') or ''}",
                style="yellow",
            )
        elif event == "error":
            console.print(
                f"error {payload.get('code') or ''}: {payload.get('message') or ''}",
                style="red",
            )
        elif event == "resync":
            self._on_resync()
        elif event == "done":
            return "status", str(payload.get("status") or "done")
        elif event == "l2":
            self._on_l2(payload)
        elif event == "fixloop":
            self._on_fixloop(payload)
        elif event == "precheck":
            if payload.get("phase") == "done":
                status("precheck done")
        else:
            console.print(f"· {event} {payload}", style="dim", highlight=False)
        return None

    # ---------------------------------------------------------------- 帧渲染

    def _on_snapshot(self, snap: Mapping[str, Any]) -> None:
        """快照帧 → 状态行；终态快照记 hint（流尽无 done 帧时兜底报终态）。"""
        console.print(_snapshot_line(snap))
        st = str(snap.get("status") or "")
        if st in _THIN_TERMINAL:
            self._terminal_hint = st
            err = snap.get("error")
            if err:
                console.print(f"error: {err}", style="red")

    def _on_chunk(self, p: Mapping[str, Any]) -> None:
        """``chunk`` 帧 → tty 进度条 / 非 tty 每 ~1/10 一行（``items`` 明细不渲）。"""
        total = p.get("total")
        self._chunk_progress.update(
            int(p.get("done") or 0), int(total) if total else None
        )

    def _on_l2(self, p: Mapping[str, Any]) -> None:
        """``l2`` done 帧 → 一行统计（``CliSink._on_l2`` 同口径）。"""
        line = l2_done_line(p)
        if line is not None:
            status(line)

    def _on_fixloop(self, p: Mapping[str, Any]) -> None:
        """``fixloop`` round/done 帧 → 行（``CliSink._on_fixloop`` 同口径）。"""
        line = fixloop_frame_line(p)
        if line is not None:
            status(line)

    def _on_resync(self) -> None:
        """``resync`` 缺口帧 → 拉新快照重置水位线渲染（best-effort，失败静默续流）。"""
        try:
            resp = self._client.get(f"/api/task/{self._task_id}")
            snap = resp.json()
        except (httpx.HTTPError, ValueError):
            return
        if isinstance(snap, dict):
            self._on_snapshot(snap)


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
