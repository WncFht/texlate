"""``TaskRunner``——进程内队列分发 + 串行管线槽 + 心跳 ticker。"""

from __future__ import annotations

import asyncio
import logging
import secrets as secrets_mod
from typing import TYPE_CHECKING

from texlate.server.settings import (
    SettingsStore,
    resolve_auth,
)

from ._common import (
    Secrets,
    TaskCtx,
)

if TYPE_CHECKING:
    from texlate.server.events import EventBus
    from texlate.server.store import Store
    from texlate.server.worker import PipelineWorker

import texlate.server.worker as _w

log = logging.getLogger(__name__)


class TaskRunner:
    """``asyncio.Queue`` 单消费者 + secrets 注册表 + 心跳 + cancel 路由。

    所有 DB 交互都在 loop 线程。``secrets`` 只挂内存——重启后
    ``auth_source='header'`` 的任务因凭证丢失走 ``needs_auth``。
    """

    def __init__(
        self,
        store: Store,
        bus: EventBus,
        worker: PipelineWorker,
        *,
        worker_id: str | None = None,
    ) -> None:
        """worker_id 缺省 ``w-<rand>``（崩溃恢复认领标记）。"""
        self.store = store
        self.bus = bus
        self.worker = worker
        self.worker_id = worker_id or f"w-{secrets_mod.token_hex(6)}"
        self.secrets: dict[str, Secrets] = {}
        self._queue: asyncio.Queue[str] | None = None
        self._dispatcher: asyncio.Task[None] | None = None
        self._ticker: asyncio.Task[None] | None = None
        self._current: tuple[str, asyncio.Task[None]] | None = None

    # ------------------------------------------------------------ 生命周期

    def start(self) -> None:
        """起 dispatcher + 心跳 ticker（必须在 loop 线程调）。"""
        self._queue = asyncio.Queue()
        self._replay_queued()
        self._dispatcher = asyncio.create_task(
            self._dispatch_loop(), name="texlate-dispatch"
        )
        self._ticker = asyncio.create_task(
            self._heartbeat_loop(), name="texlate-heartbeat"
        )

    def _replay_queued(self) -> None:
        """把库内残留 ``queued`` 行灌回内存队列。

        内存队列重启即空、dispatcher 只消费内存队列——不补放则 queued
        行永远显示「排队中」成为僵尸。``auth_source='header'`` 的行已
        被 ``recover_startup`` 分流 needs_auth（header 凭证随进程死亡
        不可恢复），此处再防御性排除；其余按 settings/env 重决议
        secrets——决议不到 key 时与冷启动同语义走 MockTranslator 警告链。
        """
        rows = self.store.conn.execute(
            "SELECT id, model FROM tasks WHERE status = 'queued'"
            " AND auth_source != 'header' ORDER BY created_at, id"
        ).fetchall()
        if not rows:
            return
        auth = resolve_auth(SettingsStore(self.worker.data_dir).load())
        for r in rows:
            self.enqueue(
                str(r["id"]),
                Secrets(
                    api_key=auth.api_key,
                    base_url=auth.base_url,
                    model=str(r["model"]),
                    source=auth.source,
                ),
            )
        log.info("replayed %d queued task(s) after restart", len(rows))

    async def stop(self) -> None:
        """关停：cancel ticker/dispatcher/当前任务，等收尾。"""
        for t in (self._ticker, self._dispatcher):
            if t is not None:
                t.cancel()
        if self._current is not None:
            self._current[1].cancel()
        pending = [t for t in (self._ticker, self._dispatcher) if t]
        if self._current is not None:
            pending.append(self._current[1])
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001,S112 -- 关停吞全部
                continue

    # ------------------------------------------------------------ 对外

    def enqueue(self, task_id: str, secrets: Secrets | None = None) -> None:
        """入队；``secrets`` 给了就登记（header BYOK 任务的唯一凭证通道）。"""
        if secrets is not None:
            self.secrets[task_id] = secrets
        if self._queue is not None:
            self._queue.put_nowait(task_id)

    def cancel_running(self, task_id: str) -> bool:
        """取消正在跑的任务；未在跑（还在队列）返回 False。"""
        if self._current is not None and self._current[0] == task_id:
            self._current[1].cancel()
            return True
        return False

    # ------------------------------------------------------------ 内部

    async def _dispatch_loop(self) -> None:
        """串行消费：dequeue → 状态复核 → 建 ctx → worker.run。"""
        assert self._queue is not None  # noqa: S101 -- start() 后必有
        while True:
            task_id = await self._queue.get()
            try:
                row = self.store.get(task_id)
                if row is None or row["status"] != "queued":
                    self.secrets.pop(task_id, None)
                    continue
                sec = self.secrets.get(task_id) or Secrets(model=str(row["model"]))
                ctx = TaskCtx(
                    store=self.store,
                    bus=self.bus,
                    task_id=task_id,
                    row=row,
                    secrets=sec,
                    root=self.worker.data_dir / "tasks" / task_id,
                )
                self.store.claim(task_id, self.worker_id)
                task = asyncio.create_task(
                    self.worker.run(ctx), name=f"texlate-task-{task_id}"
                )
                self._current = (task_id, task)
                try:
                    await task
                except asyncio.CancelledError:
                    # 子任务 cancel（cancel_running/stop 撤 _current）正常吞;
                    # dispatcher 自身被 cancel 必须重抛——否则循环回
                    # queue.get() 死等,stop() 的 await dispatcher 永久挂起
                    if asyncio.current_task().cancelling() > 0:
                        raise
                except Exception:
                    log.exception("worker escaped for %s", task_id)
                finally:
                    self._current = None
                    self.secrets.pop(task_id, None)
            except Exception:
                # 前置段（store.get/claim/ctx 构造）的 DB/IO 异常——单条失败
                # 只丢这一队列项（行仍 queued，重启 replay 兜底）；透出会把
                # dispatcher 整个打死，后续任务静默饿死且 secrets 残留
                log.exception("dispatch setup failed for %s", task_id)
                self.secrets.pop(task_id, None)
            finally:
                self._queue.task_done()

    async def _heartbeat_loop(self) -> None:
        """每 ``_HEARTBEAT_S`` 秒 bump 当前任务 updated_at。"""
        while True:
            await asyncio.sleep(_w._HEARTBEAT_S)  # noqa: SLF001 -- _w 包 attr 缝
            # 快照防竞态：dispatch finally 可把 _current 清 None，分开读
            # check/use 会 TypeError 杀死 ticker
            cur = self._current
            if cur is None:
                continue
            # 心跳是活性信号：sqlite3.Error 等非 StoreError/OSError 面同样不许杀 ticker
            try:
                self.store.heartbeat(cur[0])
            except Exception:
                log.debug("heartbeat failed for %s", cur[0], exc_info=True)
