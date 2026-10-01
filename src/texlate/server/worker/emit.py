"""``PipelineWorker._Events``——loop 回弹/事件/log/终态/stats/产物登记。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, TypeVar

from texlate.server.settings import scrub
from texlate.server.store import TERMINAL_STATUSES

from ._common import (
    TaskCtx,
    artifact_urls,
)

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Mapping,
    )

    from texlate.server.events import EventBus
    from texlate.server.store import Store

_T = TypeVar("_T")

log = logging.getLogger(__name__)

#: 孤儿线程排空预算——cancel/stop/fault 收尾时等在飞 ``_to_thread``
#: 段自然收敛的上限：轮询旗标的段 ms 级收敛；``engine.compile`` 这类
#: 原子段无插桩点只能等其自身 timeout，超限记 warning 放走（不堵
#: dispatcher 的串行槽）
_DRAIN_S = 5.0

#: ``_log`` 行合批阈值（仿 ``_doc_emit`` 的 N/秒双闸）——fixloop/
#: babeldoc on_log 这类逐行源单事件扇出成本高；满 N 行或距上次排空
#: 超 S 秒合并成单条 ``\n`` 拼接 log 事件
_LOG_FLUSH_N = 20
_LOG_FLUSH_S = 0.2

#: ``ctx.log_buf`` 的 append↔snapshot/swap 跨线程锁——``_log`` 会在
#: worker 线程跑（``to_thread`` 段内逐行源）、``_flush_logs`` 多在
#: loop 线程排空；无锁时 append 可落进已摘取的旧缓冲（orphan list
#: join 后丢行），交错的两次 flush 还会重复发布。只在缓冲操作瞬间
#: 持锁（µs 级）；``_on_loop`` 回弹会跨线程阻塞，绝不可带锁等
_LOG_BUF_LOCK = threading.Lock()


def _wait_events(evs: list[threading.Event], deadline: float) -> None:
    """顺序等事件集直到全置位/deadline——在辅助线程内跑，不占 loop。"""
    for ev in evs:
        left = deadline - time.monotonic()
        if left <= 0 or not ev.wait(left):
            return


class _Events:
    """loop 回弹/事件/log/终态/stats/产物登记 mixin。"""

    if TYPE_CHECKING:
        # 组合根 ``worker._Core.__init__`` 注入的共享态契约
        bus: EventBus
        store: Store
        _loop_tid: int

    # ------------------------------------------------------------ 事件辅助

    def _on_loop(self, fn: Callable[..., _T], *args: object, **kw: object) -> _T:
        """Worker 线程的 DB/事件写弹回 loop 线程执行（§3.2 单写者纪律）。

        ``asyncio.to_thread`` 段内的 ``store``/``bus`` 调用一律走这里；
        loop 只 ``await`` 线程结果、反向等待不构成环，无死锁。
        """
        if self._loop is None or threading.get_ident() == self._loop_tid:
            return fn(*args, **kw)
        fut: Future[_T] = Future()

        def _run() -> None:
            try:
                fut.set_result(fn(*args, **kw))
            except Exception as e:  # noqa: BLE001 -- 透传回 worker 线程
                fut.set_exception(e)

        self._loop.call_soon_threadsafe(_run)
        return fut.result()

    # ------------------------------------------------------------ 线程段取消协议

    async def _to_thread(
        self, ctx: TaskCtx, fn: Callable[..., _T], *args: object, **kw: object
    ) -> _T:
        """``asyncio.to_thread`` 的取消可感知变体——worker 线程段统一入口。

        ``fn`` 约定为 ``(ctx, *args, **kw)`` 形态（线程段函数清一色
        ctx 首参）——``fn(ctx, *args, **kw)`` 调用。

        - 旗标已置位直接 CancelledError：coroutine 被 cancel 后 ``await``
          在悬置点立即抛、工作线程照跑成孤儿——先查旗标不新造在飞段；
        - 在飞段登记 ``ctx.in_flight``（payload 线程 ``finally`` 置位——
          注意**不能**在 await 侧摘除：cancel 后 coroutine 先走、线程
          还活着，摘掉就让 ``_drain_threads`` 看不见它）；``run()``
          收尾按此有界等排空；
        - 段内取消由长段轮询 ``ctx.cancel_flag``（``_abort_if_cancelled``）
          或消费方 ``should_cancel`` 回调传导；段边界照旧
          ``_check_cancelled``。
        """
        if ctx.cancel_flag.is_set():
            raise asyncio.CancelledError
        done = threading.Event()
        ctx.in_flight.add(done)

        def _payload() -> _T:
            try:
                return fn(ctx, *args, **kw)
            finally:
                done.set()

        return await asyncio.to_thread(_payload)

    def _abort_if_cancelled(self, ctx: TaskCtx) -> None:
        """线程段内轮询点：旗标置位即抛 CancelledError 尽快放弃长段。

        与 ``_check_cancelled``（段边界、读库）的分工：本函数纯内存检查，
        可在 ``to_thread`` 段内循环迭代/子调用间高频调——SQLite conn 有
        线程亲和，线程内查库状态是违例。CancelledError 经
        ``await _to_thread`` 传播即正常取消语义的收敛路径。
        """
        if ctx.cancel_flag.is_set():
            raise asyncio.CancelledError

    async def _drain_threads(self, ctx: TaskCtx) -> None:
        """收尾有界等在飞 ``_to_thread`` 段排空（``run()`` finally 调）。

        cancel 端点语义 = 「置 cancelled + 立即返回」，不承诺线程已死；
        但 retry 进入时旧段还在写同一 ``tasks/{id}/`` 目录就交错。轮询
        旗标的段 ms 级收敛；``engine.compile`` 类原子段无插桩点，只能等
        其自身 timeout——按 ``_DRAIN_S`` 预算等，残余记 warning 放走
        （已知窗口：孤儿最迟随其内部超时死）。等待本体挪辅助线程，
        ``Event.wait`` 不堵 loop。
        """
        deadline = time.monotonic() + _DRAIN_S
        while True:
            pending = [ev for ev in ctx.in_flight if not ev.is_set()]
            if not pending:
                return
            await asyncio.to_thread(_wait_events, pending, deadline)
            pending = [ev for ev in pending if not ev.is_set()]
            if not pending or time.monotonic() >= deadline:
                break
        if pending:
            log.warning(
                "task %s: %d 个在飞线程段 %.1fs 内未排空（孤儿残尾）",
                ctx.task_id,
                len(pending),
                _DRAIN_S,
            )

    def _stage(self, ctx: TaskCtx, stage: str, message: str, progress: int) -> None:
        """状态迁移 + stage 事件（先写库再发，同序保证）。

        cancel 竞态守卫同 ``_fail``/``_reject``：行已入终态则跳过——
        否则 cancel 后的下一拍 ``_stage`` 会把 cancelled 覆写回
        ACTIVE，终态 done 事件之后又补 stage 事件。段边界是日志缓冲
        的自然排空点（stage 事件不得越过先产出的 log 行）；首入点
        monotonic 记 ``ctx.stage_marks`` 供 done 载荷 ``stage_seconds``。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        self._flush_logs(ctx)
        ctx.stage_marks.setdefault(stage, time.monotonic())
        self.store.transition(
            ctx.task_id, stage, message=message, progress=progress, force=True
        )
        self.bus.publish(
            ctx.task_id,
            "stage",
            {
                "stage": stage,
                "progress": progress,
                "message": message,
                "at": time.time(),
            },
        )

    def _log(self, ctx: TaskCtx, line: str, *, force: bool = False) -> None:
        r"""Log 事件（终态守卫 + 行合批——孤儿线程的迟到扇出不再落 task_events）。

        逐行 publish 对 fixloop/babeldoc on_log 这类逐行源扇出成本高——
        行先入 ``ctx.log_buf``，满 ``_LOG_FLUSH_N`` 行/距上次排空超
        ``_LOG_FLUSH_S`` 秒/``force`` 时合并成单条 ``\n`` 拼接事件；
        ``_stage``/``_warning``/``_mark_terminal`` 是自然排空点
        （跨类型事件时序不破）。``force=True`` 供有意的终态后审计用
        ——``_share_pack_try`` 的打包/跳过行只在 transition 之后才
        有机会发，走守卫即失声。
        """
        if not force and ctx.terminal:
            return
        with _LOG_BUF_LOCK:
            if not ctx.log_buf:
                ctx.log_last = time.monotonic()  # 批计时自缓冲首行起（0 值会立 flush）
            ctx.log_buf.append(line)
            due = (
                force
                or len(ctx.log_buf) >= _LOG_FLUSH_N
                or time.monotonic() - ctx.log_last >= _LOG_FLUSH_S
            )
        # 锁外排空——``_on_loop`` 跨线程阻塞，持锁等 loop 是死锁面
        if due:
            self._flush_logs(ctx, force=force)

    def _flush_logs(self, ctx: TaskCtx, *, force: bool = False) -> None:
        """``ctx.log_buf`` 排空成单条 log 事件（时序锚点专用）。

        发布侧仍过 ``_current_status`` 守卫——``ctx.terminal`` 只覆盖
        worker 自迁终态，外部 cancel（API 置库）由库读兜底。
        """
        # snapshot+swap 与 ``_log`` append 同锁——否则 append 落进已
        # 摘取的旧缓冲即丢行，交错双 flush 还会把同批行发布两次
        with _LOG_BUF_LOCK:
            lines = ctx.log_buf
            if not lines:
                return
            ctx.log_buf = []
            ctx.log_last = 0.0  # 0 = 无在批行——下次 append 重新起表

        def _pub() -> None:
            if not force and self._current_status(ctx) in TERMINAL_STATUSES:
                return
            self.bus.publish(
                ctx.task_id,
                "log",
                {"line": scrub("\n".join(lines), ctx.secrets.api_key)},
            )

        self._on_loop(_pub)

    def _mark_terminal(self, ctx: TaskCtx, status: str) -> None:
        """Worker 自迁终态点：排空日志 → 置本地终态旗 → 摘 mock 告警登记。

        须在 ``store.transition`` **前**、同一（loop）线程调：残余
        log 行按时序先于 done 落扇出；``ctx.terminal`` 置位后事件写
        路径守卫短路免 ``store.get``；``_mock_warned`` 摘除防终态后
        集合只增不减。
        """
        self._flush_logs(ctx, force=True)
        ctx.terminal = status
        self._mock_warned.discard(ctx.task_id)

    def _warning(
        self, ctx: TaskCtx, code: str, message: str, *, force: bool = False
    ) -> None:
        """Warning 事件（终态守卫同 ``_log``——``force`` 用途亦同）。

        先排空 log 缓冲——warning 不得越过先产出的 log 行。
        """
        self._flush_logs(ctx, force=force)

        def _pub() -> None:
            if not force and self._current_status(ctx) in TERMINAL_STATUSES:
                return
            self.bus.publish(
                ctx.task_id,
                "warning",
                {"code": code, "message": scrub(message, ctx.secrets.api_key)},
            )

        self._on_loop(_pub)

    def _current_status(self, ctx: TaskCtx) -> str:
        """行 status——``ctx.terminal`` 本地旗标短路，空旗才读库兜底。"""
        if ctx.terminal:
            return ctx.terminal
        row = self.store.get(ctx.task_id)
        return str(row["status"]) if row else "fault"

    def _progress(self, ctx: TaskCtx, value: int) -> None:
        """Progress 字段写（非状态写）——终态后钳写跳过（done 已钉 100）。"""
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        self.store.update_fields(ctx.task_id, progress=value)

    def _check_cancelled(self, ctx: TaskCtx) -> None:
        """段边界 cancel 检查：API 置 cancelled 后由本检查收敛 worker。

        顺手置 ``cancel_flag``——线程段轮询面（内存）与 DB 态同源，
        不靠 cancel_running 单点置位。
        """
        if self._current_status(ctx) == "cancelled":
            ctx.cancel_flag.set()
            raise asyncio.CancelledError

    def _fail(  # noqa: PLR0913 -- code/message/retryable/stage/detail 即错误面
        self,
        ctx: TaskCtx,
        code: str,
        message: str,
        *,
        retryable: bool,
        stage: str | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """致命错误：fault 迁移 + error 事件 + done 事件（终态一致性）。

        并发 cancel 竞态守卫：行已入终态则整条跳过（cancel 路径已发 done）。
        ``detail`` 附加字段进 error_json（fixloop 摘要等审计载荷）。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        self._mark_terminal(ctx, "fault")
        err = {
            "code": code,
            "message": scrub(message, ctx.secrets.api_key),
            "retryable": retryable,
        }
        if detail:
            err.update(detail)
        self._write_terminal(ctx, "fault", err, emit_error=True, stage=stage)

    def _reject(  # code/message/reject_at/detail 即错误面
        self,
        ctx: TaskCtx,
        code: str,
        message: str,
        *,
        reject_at: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """F3 策略拒绝：``partial`` 终态 + error_json 留 ``reject_at`` 审计字段。

        与 e2e ``status=partial + reject_at`` 同形——拒绝是降级交付不是
        故障（``inject_reject``/``route_reject`` 同输入必再拒，
        ``retryable=False``）。不发 ``error`` 事件：partial 既有通道只有
        ``transition(error=...)`` + ``done``，消费方读 ``snapshot.error``。
        cancel 竞态守卫同 ``_fail``。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        self._mark_terminal(ctx, "partial")
        err = {
            "code": code,
            "message": scrub(message, ctx.secrets.api_key),
            "retryable": False,
            "reject_at": reject_at,
        }
        if detail:
            err.update(detail)
        self._write_terminal(ctx, "partial", err, message="部分完成")

    def _write_terminal(  # noqa: PLR0913 -- 终态写面即参数面
        self,
        ctx: TaskCtx,
        status: str,
        err: dict[str, Any],
        *,
        message: str | None = None,
        emit_error: bool = False,
        stage: str | None = None,
    ) -> None:
        """``_fail``/``_reject`` 公共尾段：终态迁移 → （可选 error 帧）→ done 帧。

        迁移写 ``error_json`` 并按库内现值快照 progress；``emit_error``
        时 error 帧夹在迁移与 done 之间（fault 的错误语义面，``stage``
        以库内现值为准、缺席回退入参——``ctx.row`` 只是入队快照）。
        ``message`` 非 None 才写行 message 字段（``transition`` 的 None
        即「不动」语义）。
        """
        row = self.store.get(ctx.task_id)
        # progress 可经直写腐化（TEXT 列 BLOB/非数值）——坏格按 0 容错
        # （``_stats`` 的 created_at 守卫同口径）：参数求值先炸会把任务
        # 卡在非终态——``_mark_terminal`` 已置旗而库行未迁
        try:
            progress = int(row["progress"]) if row else 0
        except (TypeError, ValueError):
            progress = 0
        self.store.transition(
            ctx.task_id,
            status,
            error=err,
            progress=progress,
            force=True,
            message=message,
        )
        if emit_error:
            if row and row["stage"]:
                stage = str(row["stage"])
            self.bus.publish(
                ctx.task_id, "error", {**err, "stage": stage, "chunk_seq": None}
            )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": status,
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    def _finish_terminal(  # noqa: PLR0913 -- 终态写面即参数面
        self,
        ctx: TaskCtx,
        status: str,
        *,
        err: dict[str, Any] | None = None,
        message: str | None = None,
        stats_extra: dict[str, Any] | None = None,
        progress: int | None = 100,
    ) -> None:
        """成功路径终态公共尾：终态旗 → 迁移 → done 帧（终态一致性）。

        与 ``_write_terminal`` 的分工：本函数是成功/partial 交付尾，
        ``_write_terminal`` 是 ``_fail``/``_reject`` 的 fault 尾（按库内
        现值快照 progress、夹 error 帧）——形态 genuinely 不同，不互调。

        - ``err=None`` 显式清 ``error_json``（``transition`` 的 None 即
          置 NULL，与 reuse 命中行 post-queued 本已 NULL 同效）；
        - ``progress=None`` 不动行内进度（``transition`` 跳过 None）——
          cancel 臂的 interrupted 靠它保留「不钉 100」语义；
        - ``message=None`` 时按 status 取默认（done→完成，其余→部分完成），
          interrupted 由调用侧显式传 "worker cancelled"；
        - ``stats_extra`` 并入 done 载荷的 stats（babeldoc 统计等）。
        """
        self._mark_terminal(ctx, status)
        self.store.transition(
            ctx.task_id,
            status,
            progress=progress,
            error=err,
            force=True,
            message=(
                message
                if message is not None
                else "完成"
                if status == "done"
                else "部分完成"
            ),
        )
        stats = self._stats(ctx)
        if stats_extra:
            stats.update(stats_extra)
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": status,
                "artifacts": self._artifact_urls(ctx),
                "stats": stats,
            },
        )

    def _all_chunks(self, ctx: TaskCtx) -> list[dict[str, Any]]:
        """``all_chunks`` 的 run 内物化缓存——loop 线程专用（conn 亲和）。

        每任务曾 5~7 次 ``SELECT *`` 全扫；首调物化进 ``ctx.chunks_cache``，
        chunk 写点（insert/flush 调用侧）置 ``None`` 失效后下调用重读。
        """
        rows = ctx.chunks_cache
        if rows is None:
            rows = ctx.chunks_cache = self.store.all_chunks(ctx.task_id)
        return rows

    def _artifact_urls(self, ctx: TaskCtx) -> dict[str, str]:
        """Files 行 → ``{db_kind: /api/files/{id}/{url_kind}}``——``_common.artifact_urls`` 绑 ``ctx`` 形。"""
        return artifact_urls(self.store, ctx.task_id)

    def _stats(self, ctx: TaskCtx) -> dict[str, Any]:  # noqa: C901 -- 审计载荷条件阶梯平铺
        counts = self.store.chunk_counts(ctx.task_id)
        # created_at 可经直写腐化（update_fields 无字段白名单）——坏格按 0
        # 秒容错，不能让 _fail/_reject 在落终态后、publish done 前炸
        try:
            seconds = round(time.time() - float(ctx.row["created_at"]), 1)
        except (TypeError, ValueError):
            seconds = 0.0
        out: dict[str, Any] = {
            "tokens": ctx.tokens_est,
            "seconds": seconds,
            "chunks_failed": counts["failed"],
        }
        # 阶段耗时：相邻 ``_stage`` 首入点差值；末段计到本构建点。
        # resume/reuse 命中的未跑段无 mark 自然缺席。
        if ctx.stage_marks:
            order = (
                ("fetching", "fetch"),
                ("parsing", "parse"),
                ("translating", "translate"),
                ("compiling", "compile"),
            )
            marks = ctx.stage_marks
            stage_seconds: dict[str, float] = {}
            for i, (stage, key) in enumerate(order):
                t0 = marks.get(stage)
                if t0 is None:
                    continue
                t1 = next(
                    (marks[s] for s, _ in order[i + 1 :] if s in marks),
                    time.monotonic(),
                )
                stage_seconds[key] = round(t1 - t0, 1)
            if stage_seconds:
                out["stage_seconds"] = stage_seconds
        if ctx.fault_files:
            out["fault_files"] = ctx.fault_files
        if ctx.support_files:
            out["support_files"] = ctx.support_files
        if ctx.leftover_ph:
            out["leftover_ph"] = ctx.leftover_ph
        if ctx.fixloop:
            out["fixloop"] = ctx.fixloop.get("verdict")
        if ctx.logfix:
            out["logfix"] = {
                "enabled": ctx.logfix.get("enabled"),
                "errors": ctx.logfix.get("errors"),
                "retranslated": len(ctx.logfix.get("retranslated") or []),
                "fallback": len(ctx.logfix.get("fallback_src") or []),
            }
        if ctx.share:
            out["share"] = ctx.share
        return out

    def _register(
        self, ctx: TaskCtx, kind: str, rel: str, *, force: bool = False
    ) -> dict[str, Any]:
        """产物登记（bytes/sha256 在**调用线程**实测——大文件哈希不占 loop）。

        缺失产物记 NULL 同旧口径；``_on_loop`` 回弹的只剩 DB 写。
        ``force=True`` 跳终态守卫——终态任务的单块重译 job（retranslate）
        以刷新 files 清单为目的，登记不得因任务已 done/partial 短路
        （入队闸已限终态）。
        """
        size: int | None = None
        sha: str | None = None
        full = ctx.root / rel
        if full.is_file():
            blob = full.read_bytes()
            size = len(blob)
            sha = hashlib.sha256(blob).hexdigest()

        def _put() -> dict[str, Any]:
            if not force and self._current_status(ctx) in TERMINAL_STATUSES:
                # 终态后登记的 files 行让 done 事件已发的产物清单失真——
                # 孤儿线程残尾只登记不落盘的形态与取消语义一致
                return {"kind": kind, "path": rel, "bytes": size, "sha256": sha}
            return self.store.put_file(ctx.task_id, kind, rel, size=size, sha256=sha)

        return self._on_loop(_put)

    def _opt_int(
        self,
        ctx: TaskCtx,
        options: Mapping[str, Any],
        key: str,
        default: int,
        *,
        hi: int | None = None,
    ) -> int:
        """``options[key]`` 容错 int：falsy 原值静默取默认；解析值 ``<1`` → 钳 1；``hi`` 超上限钳位。

        falsy 原值（``0``/``False``/``""``/``None``/缺席）直返 ``default``
        ——不经 ``int()`` 也就无 warning（与 ``"0"`` 串这类**非 falsy**
        的零值不同：它过 ``int()`` 命中 ``<1`` 钳位臂，记 bad_option
        warning）。非数值 → warning + 默认。存量 options_json 可残留
        非法值（早于 ``_clean_task_options`` 闸或经
        share/retry 旁路写入）。``qps``/``concurrency`` 下游无
        ``__post_init__`` 兜底——负值直接进 sidecar，放大值打爆网关
        并发/速率面（上限口径对齐 ``app._clean_task_options``：
        concurrency≤16 / qps≤50）。
        """
        raw = options.get(key)
        if not raw:
            return default
        try:
            v = int(raw)  # type: ignore[arg-type] -- JSON 值可为 str/float
        except (TypeError, ValueError):
            self._warning(
                ctx, "bad_option", f"options.{key}={raw!r} 非数值——按 {default} 处理"
            )
            return default
        if v < 1:
            self._warning(ctx, "bad_option", f"options.{key}={raw!r} ≤0——按 1 钳位")
            return 1
        if hi is not None and v > hi:
            self._warning(
                ctx, "bad_option", f"options.{key}={raw!r} 超上限——按 {hi} 钳位"
            )
            return hi
        return v
