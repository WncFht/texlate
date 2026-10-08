"""``TaskRunner``——进程内队列分发 + 串行管线槽 + 心跳 ticker。"""

from __future__ import annotations

import asyncio
import logging
import secrets as secrets_mod
import time
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from texlate.server.channels import ChannelStore, routed_auth
from texlate.server.settings import (
    SettingsStore,
    env_base_url,
    env_model,
    resolve_auth,
    server_mode,
)

from ._common import (
    Secrets,
    TaskCtx,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from typing import Any

    from texlate.server.events import EventBus
    from texlate.server.store import Store
    from texlate.server.worker import PipelineWorker

from texlate.server.worker import seams

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _RetranslateJob:
    """单块重译队列项——``secrets`` 随 job 走，不进共享 ``runner.secrets``。

    该 registry 键位属主任务行：重译覆写会污染紧随其后的 retry 凭证。
    """

    task_id: str
    seq: int
    secrets: Secrets | None = None


class TaskRunner:
    """``asyncio.Queue`` 单消费者 + secrets 注册表 + 心跳 + cancel 路由。

    所有 DB 交互都在 loop 线程。``secrets`` 只挂内存——重启后
    ``auth_source='header'`` 的任务因凭证丢失走 ``needs_auth``。
    并发天花板恒为 1：``_dispatch_loop`` 单消费者即串行槽——吞吐扩容
    要动调度域（多 dispatcher/并发槽位），加深队列不改变串行事实。
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
        self._queue: asyncio.Queue[str | _RetranslateJob] | None = None
        #: ``_queue`` 未建（``start()`` 前）的入队暂存——此刻 enqueue
        #: 登记 secrets 却排不进队，header-BYOK 行会成 replay 不捞的
        #: 僵尸；暂存后 ``start()`` 建队即补灌
        self._pending_enqueue: list[str | _RetranslateJob] = []
        #: 在队未派的 ``(task_id, seq)`` 重译去重集——job 开跑即摘
        #: （跑中再点是合法的第二次排队，不吞）
        self._retr_pending: set[tuple[str, int]] = set()
        self._dispatcher: asyncio.Task[None] | None = None
        self._ticker: asyncio.Task[None] | None = None
        #: ``(task_id, ctx, task)``——ctx 在组里是为 cancel/stop 置
        #: ``cancel_flag``（线程段轮询面）不靠 worker 反射找
        self._current: tuple[str, TaskCtx, asyncio.Task[None]] | None = None

    # ------------------------------------------------------------ 生命周期

    def start(self) -> None:
        """起 dispatcher + 心跳 ticker（必须在 loop 线程调）。"""
        self._queue = asyncio.Queue()
        pending, self._pending_enqueue = self._pending_enqueue, []
        for item in pending:
            self._queue.put_nowait(item)
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
        不可恢复），此处再防御性排除；其余按 env/渠道表重决议
        secrets（与 ``deps.auth()`` 同一介入条件），决议不到 key 时
        与冷启动同语义走 MockTranslator 警告链。
        """
        rows = self.store.queued_rows()
        if not rows:
            return
        cstore = ChannelStore(self.worker.data_dir)
        auth = resolve_auth(
            SettingsStore(self.worker.data_dir).load(),
            key_env_lookup=cstore.key_env_for,
        )
        if server_mode() == "local" and not (env_base_url() or env_model()):
            # 与 deps.auth() 同口径——渠道档凭据只在 env 未显式接管时介入
            routed = cstore.resolve_route()
            if routed is not None:
                auth = routed_auth(routed, settings=auth.settings, mode=server_mode())
        for r in rows:
            self.enqueue(
                str(r["id"]),
                Secrets.from_auth(auth, model=str(r["model"])),
            )
        log.info("replayed %d queued task(s) after restart", len(rows))

    async def stop(self) -> None:
        """关停：cancel ticker/dispatcher，当前任务由 dispatcher 的 ``await task`` 传导取消。

        不再显式二次 cancel——``Task.cancel`` 在 ``await task`` 悬置点本就
        撤子任务；先置 ``cancel_flag`` 让在飞线程段立即开始收敛，
        ``await dispatcher`` 即覆盖其含 ``_drain_threads`` 的全部收尾。
        """
        for t in (self._ticker, self._dispatcher):
            if t is not None:
                t.cancel()
        if self._current is not None:
            self._current[1].cancel_flag.set()
        pending = [t for t in (self._ticker, self._dispatcher) if t]
        for t in pending:
            try:
                await t
            except asyncio.CancelledError:
                # 被等对象自身的 cancel 正常吞；stop 自身被 cancel 必须重抛
                if asyncio.current_task().cancelling() > 0:
                    raise
            except Exception:  # noqa: BLE001,S112 -- 关停吞全部
                continue

    # ------------------------------------------------------------ 对外

    def enqueue(self, task_id: str, secrets: Secrets | None = None) -> None:
        """入队；``secrets`` 给了就登记（header BYOK 任务的唯一凭证通道）。

        ``start()`` 前队列未建——暂存 ``_pending_enqueue`` 由 ``start()``
        补灌，不丢任务也不让 secrets 只登不消。
        """
        if secrets is not None:
            self.secrets[task_id] = secrets
        if self._queue is not None:
            self._queue.put_nowait(task_id)
        else:
            self._pending_enqueue.append(task_id)

    def enqueue_retranslate(
        self, task_id: str, seq: int, secrets: Secrets | None = None
    ) -> None:
        """终态任务单块重译入队——与主队列同一串行域（重译碰 ``tasks/{id}/``）。

        闸与 ``app.py`` 路由同口径：未知任务 ``KeyError``；非 done/partial、
        zh 工程未 splice、seq 无对应 chunk 均 ``ValueError``。同块在队去重。
        """
        row = self.store.get(task_id)
        if row is None:
            msg = f"unknown task {task_id}"
            raise KeyError(msg)
        if row["status"] not in ("done", "partial"):
            msg = f"task {task_id} status {row['status']} not retranslatable"
            raise ValueError(msg)
        zh = self.worker.data_dir / "tasks" / task_id / "zh"
        if not (zh / ".splice-done").is_file():
            msg = f"task {task_id} has no spliced zh tree"
            raise ValueError(msg)
        if not self.store.chunk_exists(task_id, seq):
            msg = f"task {task_id} has no chunk seq={seq}"
            raise ValueError(msg)
        key = (task_id, seq)
        if key in self._retr_pending:
            return
        self._retr_pending.add(key)
        job = _RetranslateJob(task_id=task_id, seq=seq, secrets=secrets)
        if self._queue is not None:
            self._queue.put_nowait(job)
        else:
            self._pending_enqueue.append(job)

    def cancel_running(self, task_id: str) -> bool:
        """取消正在跑的任务；未在跑（还在队列）返回 False。

        先置 ``cancel_flag`` 再 ``task.cancel()``——在飞 ``to_thread``
        段的轮询面即刻开始收敛，不等 coroutine 的 cancel 投递。
        """
        if self._current is not None and self._current[0] == task_id:
            self._current[1].cancel_flag.set()
            self._current[2].cancel()
            return True
        return False

    def inflight_task_ids(self) -> set[str]:
        """在飞任务 id 集（队列暂存 + 排队中 + 当前跑）——清扫面跳过集。

        终态任务在清扫枚举与落手之间被 retry/retranslate 翻活时，本集
        兜底不瘦其目录。``asyncio.Queue`` 无公开快照——读内部 deque
        只扫不摘，loop 单写者下无并发改形。
        """
        ids: set[str] = set()
        for item in self._queued_items():
            ids.add(item.task_id if isinstance(item, _RetranslateJob) else item)
        if self._current is not None:
            ids.add(self._current[0])
        return ids

    def _queued_items(self) -> list[str | _RetranslateJob]:
        """在队项快照：``_pending_enqueue`` 暂存 + 内存队列现存项。

        ``asyncio.Queue`` 无公开快照面——读内部 deque 只扫不摘（loop
        单写者下无并发改形），私读收此单点，消费者勿再直探。
        """
        items: list[str | _RetranslateJob] = list(self._pending_enqueue)
        if self._queue is not None:
            items.extend(self._queue._queue)  # noqa: SLF001 -- 无公开快照面
        return items

    # ------------------------------------------------------------ 内部

    async def _dispatch_loop(self) -> None:
        """串行消费：dequeue → 状态复核 → 建 ctx → worker.run。"""
        assert self._queue is not None  # noqa: S101 -- start() 后必有
        while True:
            item = await self._queue.get()
            try:
                if isinstance(item, _RetranslateJob):
                    await self._retranslate_job(item)
                    continue
                task_id = item
                row = self.store.get(task_id)
                if row is None or row["status"] != "queued":
                    self.secrets.pop(task_id, None)
                    continue
                sec = self.secrets.get(task_id)
                self.store.claim(task_id, self.worker_id)
                try:
                    await self._run_slot(
                        task_id,
                        row,
                        sec,
                        self.worker.run,
                        f"texlate-task-{task_id}",
                    )
                finally:
                    self.secrets.pop(task_id, None)
            except Exception:
                # 前置段（store.get/claim/ctx 构造）的 DB/IO 异常——透出会把
                # dispatcher 整个打死，后续任务静默饿死且 secrets 残留。
                # 原口径只丢队列项留行 queued（重启 replay 才兜底）——行永
                # 显示「排队中」同进程内不可见不可 retry；能写库就落 fault
                # 让行立即可见可 retry，DB 级故障（transition 同挂）则内层
                # 吞掉仍回 replay 兜底。job 项泄漏到此按 task_id 走同一
                # fault 闸——其行已终态，``_dispatch_fault`` 的 queued 检查
                # 早退不覆写。
                log.exception("dispatch setup failed for %s", item)
                tid = item.task_id if isinstance(item, _RetranslateJob) else item
                self.secrets.pop(tid, None)
                self._dispatch_fault(tid)
            finally:
                self._queue.task_done()

    def _dispatch_fault(self, task_id: str) -> None:
        """前置段失败 → 行落 fault + error/done 事件（终态一致性）。

        行仍 ``queued`` 才写——task 已创建/已终态的竞态不覆盖。DB 级
        故障下本函数自身抛错由调用方兜住（行留 queued 等重启 replay）。
        """
        try:
            row = self.store.get(task_id)
            if row is None or row["status"] != "queued":
                return
            err = {
                "code": "internal",
                "message": "dispatch setup failed",
                "retryable": True,
            }
            self.store.transition(
                task_id,
                "fault",
                error=err,
                force=True,
                message="dispatch setup failed",
            )
            self.bus.publish(
                task_id, "error", {**err, "stage": row["stage"], "chunk_seq": None}
            )
            try:
                seconds = round(time.time() - float(row["created_at"]), 1)
            except (TypeError, ValueError):
                seconds = 0.0
            self.bus.publish(
                task_id,
                "done",
                {
                    "status": "fault",
                    "artifacts": {},
                    "stats": {
                        "tokens": 0,
                        "seconds": seconds,
                        "chunks_failed": 0,
                    },
                },
            )
        except Exception:
            log.exception("dispatch fault transition failed for %s", task_id)

    async def _run_slot(
        self,
        task_id: str,
        row: dict[str, Any],
        secrets: Secrets | None,
        coro_fn: Callable[[TaskCtx], Coroutine[Any, Any, None]],
        name: str,
    ) -> None:
        """串行槽共用协议：建 ctx → spawn 命名子任务 → await 带 cancel 路由。

        子任务 cancel（``cancel_running``/``stop`` 撤 ``_current``）正常吞；
        dispatcher 自身被 cancel 必须重抛——否则循环回 ``queue.get()`` 死等，
        ``stop()`` 的 await dispatcher 永久挂起。``_current`` 出槽即清；
        ``name`` 兼作 escaped 日志标签（``texlate-task-*``/``texlate-retr-*``）。
        """
        ctx = TaskCtx(
            store=self.store,
            bus=self.bus,
            task_id=task_id,
            row=row,
            secrets=secrets or Secrets(model=str(row["model"])),
            root=self.worker.data_dir / "tasks" / task_id,
        )
        task = asyncio.create_task(coro_fn(ctx), name=name)
        self._current = (task_id, ctx, task)
        try:
            await task
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling() > 0:
                raise
        except Exception:
            log.exception("%s escaped for %s", name, task_id)
        finally:
            self._current = None

    async def _retranslate_job(self, job: _RetranslateJob) -> None:
        """终态任务单块重译——占同一串行槽 + ``_current`` 心跳/取消面。

        行在入队闸到此间可能已变（retry/删除）——非 done/partial 直接丢。
        job 自包含：异常全内吞（任务行已终态，``_dispatch_fault`` 语义
        不适用）；dispatcher 自身 cancel 照常传播。
        """
        task_id = job.task_id
        try:
            # 开跑即摘去重键——跑中再点是合法的第二次排队
            self._retr_pending.discard((task_id, job.seq))
            row = self.store.get(task_id)
            if row is None or row["status"] not in ("done", "partial"):
                return
            await self._run_slot(
                task_id,
                row,
                job.secrets,
                partial(self.worker.run_retranslate, seq=job.seq),
                f"texlate-retr-{task_id}-{job.seq}",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("retranslate dispatch failed for %s", task_id)

    async def _heartbeat_loop(self) -> None:
        """每 ``_HEARTBEAT_S`` 秒 bump 当前任务 updated_at。"""
        while True:
            await asyncio.sleep(seams._HEARTBEAT_S)  # noqa: SLF001 -- seams 缝
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
