"""``PipelineWorker._Translate``——translating 段 + 译器/词表/用量接线。"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.repair import resolve_glossary_path
from texlate.repair_l2 import ENV_ENV_JUDGE, env_judge_all, unknown_env_of
from texlate.server.settings import (
    cache_scope,
    validate_model,
)
from texlate.textutil import env_flag, env_str
from texlate.validate.l0 import validate_pair
from texlate.xlat.client import ChatClient, UsageRecord
from texlate.xlat.glossary import (
    LOCAL_GLOSSARY_NAME,
    Glossary,
)
from texlate.xlat.pipeline import (
    ChunkIn,
    ChunkResult,
    GatewayTranslator,
    MockTranslator,
    PipelineConfig,
    Translator,
    XlatPipeline,
)
from texlate.xlat.placeholders import collect_doc_placeholders
from texlate.xlat.prompts import PROMPT_VERSION

from ._common import (
    _FLUSH_MS,
    _FLUSH_N,
    _PIPE_TO_DB,
    _SPLICE_STALE_KINDS,
    PROGRESS,
    DBStateBridge,
    SegmentCache,
    TaskCtx,
    _FallbackTranslator,
    _new_usage_meter,
    _PerCallTranslator,
    _tgt_lang,
    _translate_progress,
    _translator_clients,
    chunk_db_id,
    chunk_error_code,
    opt_bool,
)
from .share import (
    _share_sourced,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from texlate.latex.model import Chunk

import texlate.server.worker as _w

log = logging.getLogger(__name__)


class _Translate:
    """translating 段 mixin + 译器/词表/用量接线。"""

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
            ),
            glossary=prep["glossary"],
            state=state,  # type: ignore[arg-type] -- StateStore 鸭子型
            validator=lambda s, z: validate_pair(s, z).feedback(),
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
            if usage["calls"]:
                # 有真账用真账——tokens_est 由字符估算换成 prompt+completion
                ctx.tokens_est = usage["prompt_tokens"] + usage["completion_tokens"]
                # buffer 空时下面的 _flush_translate 早退，tasks.tokens 滞留估算值
                self.store.update_fields(ctx.task_id, tokens=ctx.tokens_est)
                self.store.record_usage(
                    ctx.task_id,
                    model=str(usage["model"]),
                    calls=int(usage["calls"]),
                    prompt_tokens=int(usage["prompt_tokens"]),
                    completion_tokens=int(usage["completion_tokens"]),
                    latency_s=float(usage["latency_s"]),
                )
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
        await _w._aclose_clients(clients)  # noqa: SLF001 -- _w 包 attr 缝
        # 无在飞异常才把收尾失败上浮——有则保原异常（AuthTripped 不得错标 internal）
        if tail_exc is not None and not in_flight:
            raise tail_exc

    def _translate_prep(
        self, ctx: TaskCtx, rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """段头纯计算簇（``_to_thread`` 里跑）：glossary/cache/frag 映射/inputs/对账表。

        ``collect_doc_placeholders`` 全量扫 src_text、``_ph_frag_map``
        逐块重建 ChunkIn、``Glossary.load`` 的文件读、``_make_cache``
        的术语层指纹哈希——5k 块量级秒级 CPU/IO，全在主 loop 上跑会
        堵死 SSE/心跳/分发。本簇零 DB 触（``_make_glossary`` 的
        ``_warning`` 经 ``_on_loop`` 回弹保持单写者）；``all_chunks``
        与 ``cache.prewarm`` 的 SELECT 留 loop 线程。
        """
        # 主链 ChunkIn 必须带 ph_fragments——不给则 _repair_fn 恒 None，
        # recover_copied_tokens 抄回修复臂整条死代码（_l2_run_state 同款
        # chunk_to_in(ph_map=) 模式；DB chunk_id ↔ scans 按 byte span 对账）
        frag_of = self._ph_frag_map(ctx)
        if "doc_ph" not in ctx.memo:
            ctx.memo["doc_ph"] = collect_doc_placeholders(r["src_text"] for r in rows)
        return {
            "glossary": self._make_glossary(
                ctx,
                placeholders=ctx.memo["doc_ph"],
            ),
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
            "pre_rows": {
                r["chunk_id"]: (str(r["status"]), str(r["translation"] or ""))
                for r in rows
            },
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
        n_done = sum(
            v in ("ok", "fallback_orig", "failed") for v in status_map.values()
        )
        n_failed = sum(v in ("fallback_orig", "failed") for v in status_map.values())
        counts = {
            "total": len(status_map),
            "done": n_done,
            "cached": cache.hits,
            "failed": n_failed,
            "tokens": ctx.tokens_est,
            "progress": _translate_progress(n_done, len(status_map)),
        }
        self.store.flush_chunk_batch(ctx.task_id, updates, cache.drain(), counts)
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
        post = {
            r["chunk_id"]: (str(r["status"]), str(r["translation"] or ""))
            for r in self._all_chunks(ctx)
        }
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

    def _env_judge_enabled(self, ctx: TaskCtx) -> bool:
        """env_judge 开关：``options.env_judge`` 显式优先，缺省读 ``TEXLATE_ENV_JUDGE``（默认关）。

        共享译文任务（kind=share 导入 / arxiv 隐式命中）恒关——零 token
        结构承诺，options/env 无权打开。
        """
        if _share_sourced(ctx):
            return False
        return opt_bool(
            ctx.options(),
            "env_judge",
            lambda: env_flag(ENV_ENV_JUDGE, default=False),
        )

    def _env_judge_filter(  # noqa: C901 -- 守卫/回退阶梯平铺即 spec 的跳过面
        self,
        ctx: TaskCtx,
        trans: dict[str, str],
        rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        """静态表外 env 块问 LLM 可译性（e2e ``_env_judge_pass`` 同语义）。

        判 false 的块移出 splice 映射（回写时保留原文）并落库
        ``fallback_orig``/``env_judge``。
        """
        if not self._env_judge_enabled(ctx) or not trans:
            return trans
        targets: list[tuple[str, Chunk, str]] = []
        for rel, res in ctx.scans.items():
            for c in res.chunks:
                env_name = unknown_env_of(c)
                if env_name is None:
                    continue
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                if cid in trans:
                    targets.append((cid, c, env_name))
        if not targets:
            return trans
        translator = self._make_translator(ctx)
        clients = _translator_clients(translator)
        usage = self._meter_usage(clients)
        pipe = XlatPipeline(
            translator,
            config=PipelineConfig(tgt_lang=_tgt_lang(str(ctx.row["target_lang"]))),
            glossary=self._make_glossary(ctx),
        )

        async def _judged() -> dict[str, bool]:
            try:
                return await env_judge_all(pipe, targets)
            finally:
                # client 的用/关收进同一 ephemeral loop——拆两次 asyncio.run
                # 会在已关 loop 上 aclose（RuntimeError 吞掉 → 连接 FD 泄漏）；
                # 关完清空清单让外层 finally 不对已关 client 二次 aclose
                await _w._aclose_clients(clients)  # noqa: SLF001 -- _w 包 attr 缝
                clients.clear()

        try:
            verdicts = asyncio.run(_judged())
        finally:
            # judge 调用也烧 token——不入账就从 task_usage 里蒸发
            try:
                self._persist_usage(ctx, usage)
            except Exception:
                log.debug("env_judge usage persist failed", exc_info=True)
            if clients:
                # 未走到 _judged 就早退（aclose 内部未跑）——未用 client 在
                # 新 loop 上关是平凡路径，兜底不敞口
                try:
                    asyncio.run(_w._aclose_clients(clients))  # noqa: SLF001 -- _w 包 attr 缝
                except Exception:
                    log.debug("env_judge client aclose failed", exc_info=True)
        reverted = sorted(cid for cid, keep in verdicts.items() if not keep)
        self._log(
            ctx,
            f"env_judge: {len(targets)} 块待判，{len(reverted)} 块回落原文",
        )
        if not reverted:
            return trans
        by_id = {r["chunk_id"]: r for r in rows}
        updates = [
            (
                cid,
                {
                    "status": "fallback_orig",
                    "translation": str(by_id[cid]["src_text"] or ""),
                    "error_code": "env_judge",
                },
            )
            for cid in reverted
            if cid in by_id
        ]
        self._flush_chunk_updates(ctx, updates, [])
        out = dict(trans)
        for cid in reverted:
            out.pop(cid, None)
        return out

    def _meter_usage(self, clients: list[ChatClient]) -> dict[str, Any]:
        """给一组 client 挂 usage_sink 并返回累加 dict（``_new_usage_meter`` 的装配糖）。"""
        usage, sink = _new_usage_meter()
        for c in clients:
            c.usage_sink = sink
        return usage

    def _persist_usage(
        self, ctx: TaskCtx, usage: dict[str, Any], *, replace_est: bool = False
    ) -> None:
        """旁路臂真实 usage 落账（``_teardown_translate`` 的旁路对应物）。

        旁路 meter 只数本臂调用——``tokens_est`` **累加**而非覆盖
        （覆盖会把主链真账抹成旁路小计）。ExportError/crash 早退也把
        已发调用的真账留下；``_on_loop`` 回弹使 worker 线程内的旁路臂
        （env_judge/L2/llm_hook）也可直调。``replace_est=True`` 给唯一
        记账臂（doc 路——est 全程只是字符估算）用真账**替换**估算，
        口径同 ``_teardown_translate``。
        """
        if not usage["calls"]:
            return
        real = usage["prompt_tokens"] + usage["completion_tokens"]
        ctx.tokens_est = real if replace_est else ctx.tokens_est + real
        self._on_loop(self.store.update_fields, ctx.task_id, tokens=ctx.tokens_est)
        self._on_loop(
            self.store.record_usage,
            ctx.task_id,
            model=str(usage["model"]),
            calls=int(usage["calls"]),
            prompt_tokens=int(usage["prompt_tokens"]),
            completion_tokens=int(usage["completion_tokens"]),
            latency_s=float(usage["latency_s"]),
        )

    # ------------------------------------------------------------ translator

    def _make_translator(self, ctx: TaskCtx) -> Translator:
        """默认工厂：key 或 ``TEXLATE_TRANSLATOR=gateway`` → 网关，否则 Mock。

        ``options.retry_model`` 仅在默认网关路径生效——备选模型与 primary
        同 client（同 endpoint+key），``translator_factory``/Mock 注入路径
        由调用方自担语义不包。
        """
        if self._translator_factory is not None:
            return self._translator_factory(ctx)
        force = env_str("TEXLATE_TRANSLATOR")
        if force == "mock":
            return MockTranslator()
        if force == "gateway" or ctx.secrets.api_key:
            client = ChatClient(ctx.secrets.base_url, ctx.secrets.api_key)
            primary = GatewayTranslator(client, ctx.secrets.model or "swe-2-medium")
            retry_model = str(ctx.options().get("retry_model") or "").strip()
            if retry_model and retry_model != primary.model:
                try:
                    retry_model = validate_model(retry_model)
                except ValueError:
                    self._warning(
                        ctx,
                        "retry_model",
                        f"options.retry_model {retry_model!r} 非法，忽略",
                    )
                else:
                    return _FallbackTranslator(
                        primary, GatewayTranslator(client, retry_model)
                    )
            return primary
        # 无 key 且未显式 mock/gateway——静默假译文是生产事故面，必须留痕
        if ctx.task_id not in self._mock_warned:
            self._mock_warned.add(ctx.task_id)
            self._warning(
                ctx,
                "mock_translator",
                "未配置 API key——回退 MockTranslator，产出为占位译文而非真实翻译",
            )
        return MockTranslator()

    def _doc_translator(
        self, ctx: TaskCtx, sink: Callable[[UsageRecord], None]
    ) -> Translator:
        """``_run_doc`` 专用 translator——决策序与 ``_make_translator`` 同口径。

        差异在网关臂：``export_document`` 内嵌管线在 to_thread 的
        ephemeral ``asyncio.run`` loop 里消费 client——共享 client 的
        aclose 回不去该 loop（已关），跨 loop 关连接炸 RuntimeError
        被吞成 FD 泄漏。换 per-call 形态（``_PerCallTranslator``）即开
        即关；``retry_model`` 经其内建备选臂保持 option 面等价。
        factory/Mock 注入路径原样（测试桩语义调用方担）。
        """
        if self._translator_factory is not None:
            return self._translator_factory(ctx)
        force = env_str("TEXLATE_TRANSLATOR")
        if force == "mock":
            return MockTranslator()
        if force == "gateway" or ctx.secrets.api_key:
            model = ctx.secrets.model or "swe-2-medium"
            retry_model = str(ctx.options().get("retry_model") or "").strip()
            if retry_model and retry_model != model:
                try:
                    retry_model = validate_model(retry_model)
                except ValueError:
                    self._warning(
                        ctx,
                        "retry_model",
                        f"options.retry_model {retry_model!r} 非法，忽略",
                    )
                    retry_model = ""
            else:
                retry_model = ""
            return _PerCallTranslator(
                ctx.secrets.base_url,
                ctx.secrets.api_key,
                model,
                sink,
                retry_model=retry_model,
            )
        return self._make_translator(ctx)  # 无 key → mock 警告链同源

    def _glossary_path(
        self, ctx: TaskCtx, gpath: str, glossary_dir: str
    ) -> Path | None:
        """``glossary`` 选项 → confine 后的实际路径（None = 拒/无命中）。

        防任意文件读（审计 M2：glossary 内容进 LLM prompt 是外泄通道）：
        只收**相对路径**，逐个解析根——任务 ``base/`` 优先，然后
        ``glossary_dir``（settings 指定、运维侧受信目录，经 config_json
        透传）兜底；绝对路径与 ``..`` 形态即拒，resolve 后仍须
        is_relative_to 根（symlink 逃逸同挡）。
        """
        rel = Path(gpath)
        if rel.is_absolute() or ".." in rel.parts:
            self._warning(ctx, "glossary_rejected", f"glossary 路径越界被拒: {gpath!r}")
            return None
        cand = resolve_glossary_path(gpath, glossary_dir, ctx.base_dir)
        if cand is None:
            self._warning(
                ctx, "glossary_rejected", f"glossary 不在允许根内或不存在: {gpath!r}"
            )
        return cand

    def _local_glossary(self, ctx: TaskCtx) -> Path | None:
        """论文级 ``glossary.local.yaml`` 探测：任务 ``base/`` 根下同名文件。

        三级表（user > local > category seed）的 local 层——随源树走的
        项目内覆盖（upload_tex 压缩包/arxiv e-print 自带即生效）；docx/
        epub/pdf 路无 ``base/`` 自然缺省。返回 None = 无该层。
        """
        cand = ctx.base_dir / LOCAL_GLOSSARY_NAME
        return cand if cand.is_file() else None

    def _arxiv_categories(self, ctx: TaskCtx) -> list[str]:
        """``options.arxiv_categories``（``_fetch_arxiv`` 持久化）→ category 层键。"""
        raw = ctx.options().get("arxiv_categories")
        if not isinstance(raw, list):
            return []
        return [c for c in raw if isinstance(c, str)]

    def _make_glossary(
        self, ctx: TaskCtx, *, placeholders: Iterable[str] = ()
    ) -> Glossary | None:
        """术语表：config.glossary 路径优先（confine 后），缺省内置默认层。

        五层序：user > local(``base/glossary.local.yaml``) > categories
        （arXiv 声明分类 → ``terms/*.csv`` 经 index.yaml）> default >
        placeholders（``[[X_n]]`` 恒等注入逼模型原样回抄）。

        每任务 2~4 调（主链/env_judge/L2/pdf 臂同形构造）——``ctx.memo``
        按 ``("glossary", frozenset(placeholders))`` 备忘复用。
        """
        mkey = ("glossary", frozenset(placeholders))
        if mkey in ctx.memo:
            return ctx.memo[mkey]
        try:
            cfg = json.loads(str(ctx.row.get("config_json") or "{}"))
        except json.JSONDecodeError:
            cfg = {}
        gpath = str(cfg.get("glossary") or ctx.options().get("glossary") or "")
        local = self._local_glossary(ctx)
        cats = self._arxiv_categories(ctx)
        try:
            path = (
                self._glossary_path(ctx, gpath, str(cfg.get("glossary_dir") or ""))
                if gpath
                else None
            )
            if path is None:
                g = Glossary.load(
                    local_path=local, categories=cats, placeholders=placeholders
                )
            else:
                g = Glossary.load(
                    user_path=path,
                    local_path=local,
                    categories=cats,
                    placeholders=placeholders,
                )
        except Exception as e:  # noqa: BLE001 -- 术语表是增强件：load 面 TypeError/yaml.YAMLError 等非 OSError/ValueError 同降级无表
            self._log(ctx, f"glossary load failed: {e}")
            g = None
        ctx.memo[mkey] = g
        return g

    def _make_cache(self, ctx: TaskCtx) -> SegmentCache:
        """段缓存门面（cfg 指纹前缀含 model/prompt_ver/lang[/key 指纹]）。"""
        try:
            cfg_row = json.loads(str(ctx.row.get("config_json") or "{}"))
        except json.JSONDecodeError:
            cfg_row = {}
        glossary = str(cfg_row.get("glossary") or ctx.options().get("glossary") or "")
        local = self._local_glossary(ctx)
        local_sig = ""
        if local is not None:
            # local 层内容进指纹——同名文件换内容/有无该层都改变有效术语表
            local_sig = hashlib.sha256(local.read_bytes()).hexdigest()[:12]
        # user 层同按内容进指纹（``_share_glossary_hash`` 同口径）：
        # 路径字符串当指纹会同名换内容串桶/异名同内容分桶；拒/缺席与
        # ``_make_glossary`` 同态回落 ``USER_GLOSSARY_PATH`` 缺省层
        gfile = (
            resolve_glossary_path(
                glossary, str(cfg_row.get("glossary_dir") or ""), ctx.base_dir
            )
            if glossary
            else None
        )
        if gfile is None and _w.USER_GLOSSARY_PATH.is_file():
            gfile = _w.USER_GLOSSARY_PATH
        user_sig = ""
        if gfile is not None:
            try:
                user_sig = hashlib.sha256(gfile.read_bytes()).hexdigest()[:12]
            except OSError:
                user_sig = ""
        # categories 进指纹：不同分类 → category 层术语不同 → 同源句的
        # 翻译函数不同，跨论文共享必须按分类分桶。placeholders 是恒等
        # 注入且逐文档漂移——进指纹会把缓存锁死成单文档桶，不进。
        cats = ",".join(self._arxiv_categories(ctx))
        # base_url 进指纹：同名 model 换后端（free 网关 vs BYOK 端点）产出
        # 不同——缺此项段缓存跨 provider 混桶中毒（spec file_cache_key
        # 公式含 base 同口径，spec-xlat #7）。
        base = str(ctx.secrets.base_url or cfg_row.get("base_url") or "")
        cfg = hashlib.sha256(
            f"{ctx.row['model']}|{PROMPT_VERSION}|{ctx.row['target_lang']}"
            f"|{base}|u:{user_sig}|l:{local_sig}|c:{cats}".encode()
        ).hexdigest()[:16]
        if cache_scope() == "per_key":
            # 与 cache_key_for 同一 oracle 防护：段级 translation_cache
            # 表同样可被跨租户探测命中，按 key 指纹分桶。
            key_sha = hashlib.sha256(ctx.secrets.api_key.encode()).hexdigest()[:16]
            cfg = f"k{key_sha}:{cfg}"
        return SegmentCache(
            self.store,
            prefix=cfg,
            model=str(ctx.row["model"]),
            target_lang=str(ctx.row["target_lang"]),
        )
