"""worker.translate.stage — translating 段编排叶 + ``_Translate`` 组合根 (worker.translate 域缝叶)。

translating 段主链：``_stage_translate``（XlatPipeline 跑 chunks pending
集 + 批量 flush 落盘）、``_teardown_translate``（正常/fault/cancel 全
走收尾：撤 run_task → usage 落账 → 残余 flush → splice 哨兵 → client
关闭）、``_translate_prep``（段头纯计算簇，``_to_thread`` 里跑）、
``_flush_translate``（批量事务落盘 + chunk 事件）、``_invalidate_splice``
（译文变更摘 ``.splice-done`` 哨兵 + 陈旧产物并删）。``_Translate`` 是
全部 translate_* 叶 mixin 的组合根——worker ``PipelineWorker`` 经
``from texlate.server.worker.translate import _Translate``（惰性门面）取得。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import time
from typing import TYPE_CHECKING, Any

from texlate.server.worker import seams
from texlate.server.worker._common import (
    _DB_TO_PIPE,
    _FLUSH_MS,
    _FLUSH_N,
    _PIPE_TO_DB,
    _SPLICE_STALE_KINDS,
    FAILED_DB,
    PROGRESS,
    DBStateBridge,
    SegmentCache,
    _repend_puts,
    _row_status_snap,
    _tgt_lang,
    _translate_progress,
    _translator_clients,
    chunk_error_code,
)
from texlate.server.worker.translate.cache import _TranslateCache
from texlate.server.worker.translate.envjudge import _TranslateEnvJudge
from texlate.server.worker.translate.glossary import _TranslateGlossary
from texlate.server.worker.translate.usage import _TranslateUsage
from texlate.server.worker.translate.xlator import _TranslateXlator
from texlate.validate.l0 import pair_feedback
from texlate.xlat.pipeline import (
    ChunkIn,
    PipelineConfig,
    XlatPipeline,
)

if TYPE_CHECKING:
    from texlate.server.worker._common import TaskCtx
    from texlate.xlat.client import ChatClient
    from texlate.xlat.pipeline import ChunkResult

log = logging.getLogger(__name__)


class _TranslateStage:
    """translating 段 mixin（编排/收尾/段头计算簇/flush/splice 哨兵）。"""

    # ------------------------------------------------------------ translating

    async def _stage_translate(self, ctx: TaskCtx) -> None:
        """translating：XlatPipeline 跑 chunks pending 集（批量 flush 落盘）。"""
        rows = self._all_chunks(ctx)
        if not rows:
            self._stage(ctx, "translating", "无可译块", PROGRESS["translating"][1])
            return
        await self._ensure_scans(ctx)
        self._stage(ctx, "translating", "翻译中", PROGRESS["translating"][0])

        translator = self._make_translator(ctx)
        clients = _translator_clients(translator)
        # 段头纯计算簇（placeholders 全扫/glossary load/ph 映射/inputs
        # 物化/seq·status·pre_rows 表）挪工作线程——5k 块量级在主 loop
        # 上秒级堵 SSE/心跳/分发；DB 读按单写者纪律留 loop 线程
        prep = await self._to_thread(ctx, self._translate_prep, rows)
        cache: SegmentCache = prep["cache"]
        state = DBStateBridge(
            self.store,
            ctx.task_id,
            rows=rows,
            state_dir=ctx.root / "export-state",
        )
        seq_map: dict[str, int] = prep["seq_map"]
        status_map: dict[str, str] = prep["status_map"]
        # 本段起跑前快照——retry/resume 重跑翻译若改行（pending→ok/
        # 重译改译文），既有 .splice-done 即过期，须摘除逼编译段重
        # splice（zh/ 被 _build_zh rmtree，.compile-done 随之同死）
        pre_rows: dict[str, tuple[str, str]] = prep["pre_rows"]
        sse_items: list[dict[str, Any]] = []
        last_flush = time.monotonic()
        # T4：每次成功 chat() 的真实 token/延迟记账（ChatClient 回调）
        usage = self._meter_usage(clients)

        def on_result(r: ChunkResult) -> None:
            item: dict[str, Any] = {
                "seq": seq_map.get(r.chunk_id, -1),
                "status": _PIPE_TO_DB.get(r.status, "failed"),
            }
            code = chunk_error_code(r)
            if code is not None:
                item["error_code"] = code
            sse_items.append(item)
            ctx.tokens_est += (len(r.source) + len(r.translation)) // 4

        pipe = XlatPipeline(
            translator,
            config=PipelineConfig(
                concurrency=self._opt_int(ctx, ctx.options(), "concurrency", 10, hi=16),
                tgt_lang=_tgt_lang(str(ctx.row["target_lang"])),
                auto_glossary_fn=self._auto_glossary_fn(ctx, clients),
            ),
            glossary=prep["glossary"],
            state=state,  # type: ignore[arg-type] -- StateStore 鸭子型
            validator=pair_feedback,
            cache=cache,  # type: ignore[arg-type] -- MutableMapping 鸭子型
            on_result=on_result,
        )
        inputs: list[ChunkIn] = prep["inputs"]
        # 段缓存一次性预载（分批 SELECT IN）——prewarm 后 __contains__/
        # __getitem__ 纯内存查，5k 逐键 SELECT 不再逐块占 loop 线程
        cache.prewarm(pipe._seg_key(c) for c in inputs)  # noqa: SLF001 -- 缓存键只有管线会算

        run_task: asyncio.Task[list[ChunkResult]] | None = None
        try:
            run_task = asyncio.create_task(pipe.run(inputs))
            while not run_task.done():
                # wait 代 sleep：任务完成即醒（无残 50ms 尾延），超时兜底
                # 0.5s 维持 cancel/flush 轮询节奏
                await asyncio.wait({run_task}, timeout=0.5)
                self._check_cancelled(ctx)
                if (
                    len(state.buffer) >= _FLUSH_N
                    or time.monotonic() - last_flush >= _FLUSH_MS
                ):
                    self._flush_translate(ctx, state, cache, status_map, sse_items)
                    last_flush = time.monotonic()
            await run_task  # 传播异常（AuthTrippedError → run() 归 provider_auth）
            if prep["glossary"] is not None:
                # term_dict 落盘（export-state/term_dict.json）——观测件不毁账：
                # 写盘失败不把已完成的翻译段记成 fault（bench stage_xlat 同式）
                with contextlib.suppress(Exception):
                    state.save_maps(
                        term_dict=pipe._doc_glossary  # noqa: SLF001 -- 管线内部观测表
                    )
        finally:
            await self._teardown_translate(
                ctx=ctx,
                run_task=run_task,
                state=state,
                cache=cache,
                status_map=status_map,
                sse_items=sse_items,
                usage=usage,
                clients=clients,
                pre_rows=pre_rows,
            )
        self._stage(ctx, "translating", "翻译完成", PROGRESS["translating"][1])
        counts = self.store.chunk_counts(ctx.task_id)
        if counts["failed"]:
            self._warning(
                ctx,
                "chunks_failed",
                f"{counts['failed']} 块回退原文（fallback_orig/failed）",
            )
        self._check_cancelled(ctx)

    async def _teardown_translate(  # noqa: PLR0913 -- 收尾现场全员（run_task + flush 参数 + usage + clients）
        self,
        *,
        ctx: TaskCtx,
        run_task: asyncio.Task[list[ChunkResult]] | None,
        state: DBStateBridge,
        cache: SegmentCache,
        status_map: dict[str, str],
        sse_items: list[dict[str, Any]],
        usage: dict[str, Any],
        clients: list[ChatClient],
        pre_rows: dict[str, tuple[str, str]],
    ) -> None:
        """收尾 translating 段（正常/fault/cancel 全走）：撤 run_task → usage 落账 → 残余 buffer flush → 过期 splice 哨兵摘除 → client 关闭。"""
        if run_task is not None and not run_task.done():
            # cancel 竞态：poll 循环被 _check_cancelled 抛出时 pipe.run
            # 仍在跑——不撤它就是孤儿任务：剩余 item 全标 skipped、flush
            # 后继续写 buffer/sse_items/done_map，且 clients 在任务脚下
            # 被 aclose
            run_task.cancel()
            # asyncio.wait 不回传 run_task 的 CancelledError——await 直等
            # 会把外层 worker 自身的二次 cancel 一并吞掉（同型异常不可分）
            await asyncio.wait({run_task})
        in_flight = sys.exc_info()[0] is not None
        tail_exc: Exception | None = None
        try:
            # 有真账用真账——replace_est 把 tokens_est 从字符估算换成
            # prompt+completion；buffer 空时下面 _flush_translate 早退，
            # update_fields 不跑则 tasks.tokens 滞留估算值。本段在 loop
            # 线程跑，_on_loop 直调即原内联写盘口径
            self._persist_usage(ctx, usage, replace_est=True)
        except Exception as e:  # noqa: BLE001 -- 记账失败不挡数据落盘与资源释放
            tail_exc = e
            log.warning("teardown usage persist failed: %s: %s", type(e).__name__, e)
        # fault/cancel 也要把缓冲里的已完块落盘（原先异常路径丢 buffer）——
        # flush 是同步体无悬置点：pending-cancel 不会投递进来截断写盘
        try:
            self._flush_translate(ctx, state, cache, status_map, sse_items)
        except Exception as e:  # noqa: BLE001 -- flush 失败仍须 invalidate+aclose
            if tail_exc is None:
                tail_exc = e
            log.warning("teardown flush failed: %s: %s", type(e).__name__, e)
        self._invalidate_splice(ctx, pre_rows)
        await seams._aclose_clients(clients)  # noqa: SLF001 -- seams 缝
        # 无在飞异常才把收尾失败上浮——有则保原异常（AuthTripped 不得错标 internal）
        if tail_exc is not None and not in_flight:
            raise tail_exc

    def _translate_prep(
        self, ctx: TaskCtx, rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """段头纯计算簇（``_to_thread`` 里跑）：glossary/cache/frag 映射/inputs/对账表。

        ``_ph_frag_map`` 逐块重建 ChunkIn、``Glossary.load`` 的文件读、
        ``_make_cache`` 的术语层指纹哈希——5k 块量级秒级 CPU/IO，全在主
        loop 上跑会堵死 SSE/心跳/分发。本簇零 DB 触（``_make_glossary``
        的 ``_warning`` 经 ``_on_loop`` 回弹保持单写者）；``all_chunks``
        与 ``cache.prewarm`` 的 SELECT 留 loop 线程。
        """
        # 主链 ChunkIn 必须带 ph_fragments——不给则 _repair_fn 恒 None，
        # recover_copied_tokens 抄回修复臂整条死代码（_l2_run_state 同款
        # chunk_to_in(ph_map=) 模式；DB chunk_id ↔ scans 按 byte span 对账）
        frag_of = self._ph_frag_map(ctx)
        return {
            "glossary": self._make_glossary(ctx),
            "cache": self._make_cache(ctx),
            "frag_of": frag_of,
            "inputs": [
                ChunkIn(
                    chunk_id=r["chunk_id"],
                    content=r["src_text"],
                    kind=r["kind"],
                    ph_fragments=frag_of.get(r["chunk_id"]),
                )
                for r in rows
            ],
            "seq_map": {r["chunk_id"]: int(r["seq"]) for r in rows},
            "status_map": {r["chunk_id"]: str(r["status"]) for r in rows},
            "pre_rows": _row_status_snap(rows),
        }

    def _flush_translate(
        self,
        ctx: TaskCtx,
        state: DBStateBridge,
        cache: SegmentCache,
        status_map: dict[str, str],
        sse_items: list[dict[str, Any]],
    ) -> None:
        """批量事务 flush（§3.4.2）：record 缓冲 → chunks 行 + 段缓存 + 计数器 + chunk 事件。

        本函数体必须保持纯同步（无 await）——``_teardown_translate`` 在
        pending-cancel 下也要靠它把缓冲落盘：cancel 只投递在悬置点，同步
        体原子跑完不会被吞。若日后要加真异步（如 to_thread 落库），调用
        方的 cancel 语义面须整体重评。
        """
        if not state.buffer and not sse_items:
            return
        updates = []
        for rec in state.buffer:
            db_status = _PIPE_TO_DB.get(rec.status, "failed")
            status_map[rec.chunk_id] = db_status
            updates.append(
                (
                    rec.chunk_id,
                    {
                        "status": db_status,
                        "translation": rec.translation,
                        "error_code": chunk_error_code(rec),
                        "warnings": (
                            json.dumps(rec.warnings, ensure_ascii=False)
                            if rec.warnings
                            else None
                        ),
                        "attempts": rec.attempts,
                    },
                )
            )
        # done 集 = ``_DB_TO_PIPE`` 键（pipecore 状态图单源）；failed 子集 ``FAILED_DB``
        n_done = sum(v in _DB_TO_PIPE for v in status_map.values())
        n_failed = sum(v in FAILED_DB for v in status_map.values())
        counts = {
            "total": len(status_map),
            "done": n_done,
            "cached": cache.hits,
            "failed": n_failed,
            "tokens": ctx.tokens_est,
            "progress": _translate_progress(n_done, len(status_map)),
        }
        puts = cache.drain()
        try:
            self.store.flush_chunk_batch(ctx.task_id, updates, puts, counts)
        except Exception:
            # 瞬逝 DB 错：drain 已取走的段缓存项回挂 pending——与下面
            # ``state.buffer`` 滞留同口径，下轮 flush 重投不丢缓存项
            _repend_puts(cache, puts)
            raise
        ctx.chunks_cache = None  # chunks 行已写——物化缓存失效
        # 落盘成功才丢缓冲——瞬逝 DB 错时记录留 buffer 等下一轮 flush 重投
        state.buffer = []
        items_now = list(sse_items)
        sse_items.clear()
        self.bus.publish(
            ctx.task_id,
            "chunk",
            {
                "done": counts["done"],
                "total": counts["total"],
                "cached": counts["cached"],
                "failed": counts["failed"],
                "items": items_now,
            },
        )

    def _invalidate_splice(
        self, ctx: TaskCtx, pre_rows: dict[str, tuple[str, str]]
    ) -> None:
        """本段改了 chunks 行（status/translation 任一变化）→ 摘 ``.splice-done``。

        retry/resume 重进翻译段时 zh/ 可能已 splice 甚至已编译——译文变
        更若不摘哨兵，``_build_zh`` 见哨兵直跳，旧译文永留产物。哨兵一摘
        ``_build_zh`` rmtree zh/ 重建（``.compile-done`` 随之同死重编）；
        无变化不动哨兵，resume 才能直进编译臂。loop 线程直读 store。

        哨兵摘除即旧产物作废：``_SPLICE_STALE_KINDS`` 的 files 行与磁盘件
        并删——否则重编失败/resume 未到编译段就终态时，files/reader 端点
        照发上一轮的旧译文产物（reader 直接读 dual.json 磁盘件，仅删行
        不够）。
        """
        sent = ctx.zh_dir / ".splice-done"
        if not sent.is_file():
            return
        post = _row_status_snap(self._all_chunks(ctx))
        if post == pre_rows:
            return
        sent.unlink()
        task_root = ctx.root.resolve()
        for kind in _SPLICE_STALE_KINDS:
            rel = self.store.delete_file(ctx.task_id, kind)
            if rel is None:
                continue
            stale = (ctx.root / rel).resolve()
            if stale.is_relative_to(task_root):
                with contextlib.suppress(OSError):
                    stale.unlink(missing_ok=True)
        self._log(ctx, "译文变更：摘除 .splice-done，编译段将重 splice")


class _Translate(
    _TranslateStage,
    _TranslateCache,
    _TranslateXlator,
    _TranslateGlossary,
    _TranslateEnvJudge,
    _TranslateUsage,
):
    """translating 段 mixin + 译器/词表/用量接线——translate_* 叶组合根。"""
