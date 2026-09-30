"""worker.compile.l2 — L2 回灌 + 块级回写事务叶 (worker.compile 域缝叶)。

L2 译文归因修复链：``_l2_run_state`` 重建 ``repair_l2.TreeRun`` 形态、
``_l2_repair_zh`` 一轮回灌（resplice→重编→复判）、``_l2_writeback``
重译/回退结果落 chunks 表、``_flush_chunk_updates`` 块级回写事务
（L2/env_judge 共用）与 ``_l2_attempt`` 臂编排。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from texlate.pipecore import (
    DB_TO_PIPE,
    RepairPolicy,
    compile_judge,
    l2_repair,
)
from texlate.repair_l2 import (
    ENV_NO_L2,
    L2_MAX_CHUNKS,
    TreeRun,
    retranslate_hits,
    split_cid,
)
from texlate.server.worker._common import (
    FAILED_DB,
    SegmentCache,
    _repend_puts,
    _scrub_deep,
    _Sink,
    _tgt_lang,
    _translator_clients,
    chunk_db_id,
)
from texlate.server.worker.compile.splice import (
    _delivered_map,
    _seq_marks_on,
    _sync_fixed_sources,
)
from texlate.server.worker.share import (
    _share_sourced,
)
from texlate.validate.l0 import pair_feedback
from texlate.xlat.pipeline import (
    ChunkIn,
    PipelineConfig,
    XlatPipeline,
    chunk_to_in,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from pathlib import Path

    from texlate.compile.engine import (
        CompRes,
        Engine,
    )
    from texlate.compile.judge import Verdict
    from texlate.server.worker._common import TaskCtx


class _CompileL2:
    """L2 回灌 mixin：译文归因重译 + resplice 重编 + chunks 表回写事务。"""

    def _l2_enabled(self, ctx: TaskCtx) -> bool:
        """L2 回灌开关：``options.l2`` 显式优先，缺省读 ``TEXLATE_NO_L2``（默认开）。

        共享译文任务恒关——零 token 是结构承诺（``_share_apply`` 不回退
        自译同理），options/env 无权打开。
        """
        if _share_sourced(ctx):
            return False
        return RepairPolicy.resolve(ctx.options()).l2

    def _l2_run_state(self, ctx: TaskCtx, work: Path) -> tuple[TreeRun, dict[str, str]]:
        """``repair_l2.TreeRun`` 形态重建：scans 指向 work 内文件 + trans/chunk_ins。

        ``trans`` 取 chunks 表 status='ok' 译文（= work 内已 splice 内容）；
        ``db_of`` 是 ``"fidx:cid"`` → chunks.chunk_id 的 DB 回写映射。
        """
        self._abort_if_cancelled(ctx)
        ok = _delivered_map(self._on_loop(self._all_chunks, ctx))
        rels = sorted(ctx.scans)
        trans: dict[int, dict[int, str]] = {}
        chunk_ins: dict[str, ChunkIn] = {}
        db_of: dict[str, str] = {}
        for fidx, rel in enumerate(rels):
            res = ctx.scans[rel]
            for c in res.chunks:
                key = f"{fidx}:{c.id}"
                db_cid = chunk_db_id(rel, c.span.start, c.span.end)
                db_of[key] = db_cid
                chunk_ins[key] = chunk_to_in(c, chunk_id=key, ph_map=res.ph_map)
                zh = ok.get(db_cid)
                if zh is not None:
                    trans.setdefault(fidx, {})[c.id] = zh
        pipe = XlatPipeline(
            self._make_translator(ctx),
            config=PipelineConfig(tgt_lang=_tgt_lang(str(ctx.row["target_lang"]))),
            glossary=self._make_glossary(ctx),
            validator=pair_feedback,
        )
        # 旁路 pipe 不经 run()——_doc_glossary 恒 {}，L2 重译 prompt 会
        # 丢术语块，须显式物化一次。不挂主链 SegmentCache：带
        # [compile_error] hint 语境的修复译文写同前缀缓存会污染主链段
        # 缓存命名空间（段缓存只认 source+masked 快照，不知 hint）
        pipe._materialize(list(chunk_ins.values()))  # noqa: SLF001 -- 旁路复用文档级物化
        run = TreeRun(
            scans=[(work / rel, ctx.scans[rel]) for rel in rels],
            trans=trans,
            chunk_ins=chunk_ins,
            pipe=pipe,
        )
        return run, db_of

    def _l2_repair_zh(
        self, ctx: TaskCtx, work: Path, eng: Engine, res: CompRes
    ) -> tuple[dict[str, Any], CompRes, Verdict | None]:
        """L2 回灌一轮：阶梯骨架在 ``pipecore.l2_repair``（e2e ``l2_repair_job`` 同件）。

        resplice 只重写 ``build-zh``——DB 回写 + ``_sync_fixed_sources``
        灌回 ``zh/`` + 重打 zh-src.zip 由本层补齐（worker 的成品树是
        ``zh/`` 而非 work），仅重编走过（v2 非 None）才回写。``_recompile``
        内保留 compile→judge 间中止点（repair 侧 ``checkpoint`` 在
        retranslate 前后/recompile 后另补三拍，合原作粒度超集）。
        返回 (l2 报告，最新 CompRes, 新 Verdict 或 None=未重编）。
        """
        run, db_of = self._l2_run_state(ctx, work)
        clients = _translator_clients(run.pipe.translator)
        usage = self._meter_usage(clients)

        def _retr(
            run: TreeRun, hits: dict[str, dict[str, Any]], cap: int
        ) -> Awaitable[dict[str, Any]]:
            # coro_fn 同步体：progress 帧随调用即发，返回的协交由
            # ``_run_ephemeral`` 内 ``await coro_fn()`` 消费——包一层
            # async def 只是多一次无意义协程嵌套
            self._repair_event(
                ctx,
                "l2",
                {"phase": "progress", "message": f"L2 重译 {len(hits)} 块"},
            )
            return retranslate_hits(run, hits, cap)

        def _recompile() -> tuple[CompRes, Verdict]:
            self._repair_event(
                ctx, "l2", {"phase": "progress", "message": "L2 回灌重编"}
            )
            # compile 原子段跑完即收敛——judge 前查取消省一轮白费判分
            # （after_compile 插桩 = 原 compile→abort→judge 序）
            return compile_judge(
                eng,
                work,
                ctx.main_rel,
                timeout=self._compile_timeout,
                flags=ctx.probe_flags or None,
                expect_cjk=ctx.expect_cjk,
                should_cancel=ctx.cancel_flag.is_set,
                after_compile=lambda _r: self._abort_if_cancelled(ctx),
            )

        try:
            rep, res2, v2 = l2_repair(
                run,
                work,
                ctx.main_rel,
                res,
                L2_MAX_CHUNKS,
                # 旁路 client 用/关收进同一 ephemeral loop——``_run_ephemeral``
                # 壳契约（拆两次 asyncio.run 会在已关 loop 上 aclose）
                retranslate=lambda r, h, c: self._run_ephemeral(
                    clients, lambda: _retr(r, h, c)
                ),
                recompile=_recompile,
                checkpoint=lambda: self._abort_if_cancelled(ctx),
                sink=_Sink(
                    lambda m: self._log(ctx, m),
                    lambda t, p: self._repair_event(ctx, t, p),
                ),
                baseline_sigs=self._en_err_sigs(ctx),
                seq_marks=_seq_marks_on(ctx.options()),
            )
        finally:
            # L2 重译也烧 token——不入账就从 task_usage 里蒸发；clients
            # 非空=未走到 _retr 的早退（localize 即崩），_run_ephemeral
            # 跑过的已自清清单由 helper 内 ``if clients`` 跳过
            self._teardown_llm_hook(ctx, usage, clients, tag="l2")
        if v2 is not None:
            self._l2_writeback(ctx, run, db_of, rep)
            n = _sync_fixed_sources(work, ctx.zh_dir)
            if n:
                self._log(ctx, f"l2: {n} 个重译文件回灌 zh/，重打 zh-src.zip")
                self._zip_zh(ctx)
        return rep, res2, v2

    def _l2_writeback(
        self,
        ctx: TaskCtx,
        run: TreeRun,
        db_of: dict[str, str],
        rep: dict[str, Any],
    ) -> None:
        """L2 结果落 chunks 表：retranslated→新译文；reverted/fallback→fallback_orig。"""
        upd: dict[str, dict[str, Any]] = {}
        for cid in rep.get("retranslated") or []:
            fidx, ccid = split_cid(cid)
            zh = (run.trans.get(fidx) or {}).get(ccid)
            if zh is not None and cid in db_of:
                upd[db_of[cid]] = {"translation": zh}
        for cid in (
            *(rep.get("reverted_l0") or []),
            *(rep.get("fallback_src") or []),
        ):
            if cid not in db_of:
                continue
            ci = run.chunk_ins.get(cid)
            upd[db_of[cid]] = {
                "status": "fallback_orig",
                "translation": ci.content if ci is not None else "",
                "error_code": "l2_reverted",
            }
        cache = run.pipe.cache
        cache_puts = cache.drain() if isinstance(cache, SegmentCache) else []
        if not upd and not cache_puts:
            return
        try:
            self._flush_chunk_updates(ctx, list(upd.items()), cache_puts)
        except Exception:
            # drain 已取走的缓存项随 flush 失败回挂——同 ``_flush_translate``
            # 口径（当前 L2 旁路 pipe 无 ``cache=`` 实为防御臂）
            if cache_puts and isinstance(cache, SegmentCache):
                _repend_puts(cache, cache_puts)
            raise

    def _flush_chunk_updates(
        self,
        ctx: TaskCtx,
        updates: list[tuple[str, dict[str, Any]]],
        cache_puts: list[tuple[str, str, str, str]],
    ) -> None:
        """编译段块级回写事务（L2/env_judge 共用）：chunk 更新 + 段缓存 + 计数器。

        worker 线程调用——``_on_loop`` 压回 loop 线程后读改写一笔成交；
        计数器按 chunks 表最终态全量重算（不靠增量推演），progress 沿用行值。
        """

        def _flush() -> None:
            st = {
                r["chunk_id"]: str(r["status"])
                for r in self.store.all_chunks(ctx.task_id)
            }
            applied = [(cid, f) for cid, f in updates if cid in st]
            for cid, f in applied:
                st[cid] = str(f.get("status") or st[cid])
            row = self.store.get(ctx.task_id)
            # 行格可经直写腐化（TEXT 列 BLOB/非数值）——坏格按 0 容错，
            # 不让单格 int() 把 flush 事务参数求值先炸（``_stats`` 的
            # created_at 守卫同口径）
            try:
                cached = int(row["cached_chunks"]) if row else 0
            except (TypeError, ValueError):
                cached = 0
            try:
                progress = int(row["progress"]) if row else 0
            except (TypeError, ValueError):
                progress = 0
            counters = {
                "total": len(st),
                "done": sum(s in DB_TO_PIPE for s in st.values()),
                "cached": cached,
                "failed": sum(s in FAILED_DB for s in st.values()),
                "tokens": ctx.tokens_est,
                "progress": progress,
            }
            self.store.flush_chunk_batch(ctx.task_id, applied, cache_puts, counters)
            ctx.chunks_cache = None  # chunks 行已写——物化缓存失效

        self._on_loop(_flush)

    def _l2_attempt(
        self,
        ctx: TaskCtx,
        work: Path,
        eng: Engine,
        res: CompRes,
        v: Verdict,
    ) -> tuple[CompRes, Verdict]:
        """非 clean 判据后的 L2 臂：跑 ``_l2_repair_zh`` + 报告入账/事件/日志。"""
        if not self._l2_enabled(ctx):
            ctx.l2 = {
                "enabled": False,
                "reason": (
                    "share_zero_token"
                    if _share_sourced(ctx)
                    else "options.l2"
                    if "l2" in ctx.options()
                    else ENV_NO_L2
                ),
            }
            return res, v
        self._repair_event(ctx, "l2", {"phase": "start"})
        try:
            rep, res2, v2 = self._l2_repair_zh(ctx, work, eng, res)
        except Exception as e:  # noqa: BLE001 -- L2 崩不拖垮编译段
            self._log(ctx, f"l2 crashed: {type(e).__name__}: {e}")
            self._repair_event(
                ctx,
                "l2",
                {
                    "phase": "done",
                    "crashed": True,
                    "message": f"{type(e).__name__}: {e}",
                },
            )
            return res, v
        ctx.l2 = _scrub_deep(rep, ctx.secrets.api_key)
        # done 帧（平铺统计键 + report 全量）已随 pipecore.l2_repair 的
        # sink 出口发布——scrub 在 _repair_event 内，键集不变
        for key in ("retranslated", "reverted_l0", "fallback_src", "unresolved"):
            if rep.get(key):
                self._log(ctx, f"l2 {key}: {rep[key]}")
        return res2, (v2 if v2 is not None else v)
