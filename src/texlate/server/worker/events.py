"""``PipelineWorker._Events``——loop 回弹/事件/log/终态/stats/产物登记。"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, TypeVar

from texlate.server.settings import scrub
from texlate.server.store import TERMINAL_STATUSES

from ._common import (
    KIND_URL,
    TaskCtx,
)

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Mapping,
    )

_T = TypeVar("_T")


class _Events:
    """loop 回弹/事件/log/终态/stats/产物登记 mixin。"""

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

    def _stage(self, ctx: TaskCtx, stage: str, message: str, progress: int) -> None:
        """状态迁移 + stage 事件（先写库再发，同序保证）。

        cancel 竞态守卫同 ``_fail``/``_reject``：行已入终态则跳过——
        否则 cancel 后的下一拍 ``_stage`` 会把 cancelled 覆写回
        ACTIVE，终态 done 事件之后又补 stage 事件。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
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

    def _log(self, ctx: TaskCtx, line: str) -> None:
        self._on_loop(
            self.bus.publish,
            ctx.task_id,
            "log",
            {"line": scrub(line, ctx.secrets.api_key)},
        )

    def _warning(self, ctx: TaskCtx, code: str, message: str) -> None:
        self._on_loop(
            self.bus.publish,
            ctx.task_id,
            "warning",
            {"code": code, "message": scrub(message, ctx.secrets.api_key)},
        )

    def _current_status(self, ctx: TaskCtx) -> str:
        row = self.store.get(ctx.task_id)
        return str(row["status"]) if row else "fault"

    def _check_cancelled(self, ctx: TaskCtx) -> None:
        """段边界 cancel 检查：API 置 cancelled 后由本检查收敛 worker。"""
        if self._current_status(ctx) == "cancelled":
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
        clean = scrub(message, ctx.secrets.api_key)
        err = {"code": code, "message": clean, "retryable": retryable}
        if detail:
            err.update(detail)
        row = self.store.get(ctx.task_id)
        progress = int(row["progress"]) if row else 0
        if row and row["stage"]:
            # ctx.row 是入队快照——error 事件的 stage 以库内现值为准
            stage = str(row["stage"])
        self.store.transition(
            ctx.task_id, "fault", error=err, progress=progress, force=True
        )
        self.bus.publish(
            ctx.task_id, "error", {**err, "stage": stage, "chunk_seq": None}
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": "fault",
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

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
        err = {
            "code": code,
            "message": scrub(message, ctx.secrets.api_key),
            "retryable": False,
            "reject_at": reject_at,
        }
        if detail:
            err.update(detail)
        row = self.store.get(ctx.task_id)
        self.store.transition(
            ctx.task_id,
            "partial",
            error=err,
            progress=int(row["progress"]) if row else 0,
            force=True,
            message="部分完成",
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": "partial",
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    def _artifact_urls(self, ctx: TaskCtx) -> dict[str, str]:
        """Files 行 → ``{db_kind: /api/files/{id}/{url_kind}}``。"""
        return {
            kind: f"/api/files/{ctx.task_id}/{KIND_URL.get(kind, kind)}"
            for kind in self.store.files(ctx.task_id)
        }

    def _stats(self, ctx: TaskCtx) -> dict[str, Any]:
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
        if ctx.fault_files:
            out["fault_files"] = ctx.fault_files
        if ctx.support_files:
            out["support_files"] = ctx.support_files
        if ctx.leftover_ph:
            out["leftover_ph"] = ctx.leftover_ph
        if ctx.fixloop:
            out["fixloop"] = ctx.fixloop.get("verdict")
        if ctx.l2:
            out["l2"] = {
                "enabled": ctx.l2.get("enabled"),
                "errors": ctx.l2.get("errors"),
                "retranslated": len(ctx.l2.get("retranslated") or []),
                "fallback": len(ctx.l2.get("fallback_src") or []),
            }
        if ctx.share:
            out["share"] = ctx.share
        return out

    def _register(self, ctx: TaskCtx, kind: str, rel: str) -> dict[str, Any]:
        """产物登记（bytes/sha256 在**调用线程**实测——大文件哈希不占 loop）。

        缺失产物记 NULL 同旧口径；``_on_loop`` 回弹的只剩 DB 写。
        """
        size: int | None = None
        sha: str | None = None
        full = ctx.root / rel
        if full.is_file():
            blob = full.read_bytes()
            size = len(blob)
            sha = hashlib.sha256(blob).hexdigest()
        return self._on_loop(
            self.store.put_file, ctx.task_id, kind, rel, size=size, sha256=sha
        )

    def _opt_int(
        self, ctx: TaskCtx, options: Mapping[str, Any], key: str, default: int
    ) -> int:
        """``options[key]`` 容错 int：非数值 → warning + 默认；≤0 → warning + 钳 1。

        存量 options_json 可残留非法值（早于 ``_clean_task_options`` 闸或经
        share/retry 旁路写入）。``qps`` 等旋钮下游无 ``__post_init__`` 兜底
        ——负值会直接进 babeldoc sidecar。
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
        return v
