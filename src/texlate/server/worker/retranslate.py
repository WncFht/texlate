"""``PipelineWorker._Retranslate``——终态任务单块重译 job。

``runner.enqueue_retranslate`` 入队、dispatcher 与主任务同一串行域派发；
任务本体**不迁终态**——log/warning 走 ``force=True`` 终态后审计通道，
产物登记走 ``_register_forced`` 绕过 ``_register`` 的终态守卫（files
清单更新即本 job 目的）。失败路径只记 log + chunks 行 ``error_code``：
原译与旧产物一律保留，重译不得让既有状态倒退。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import shutil
import threading
import zipfile
from typing import TYPE_CHECKING, Any

from texlate.compile.judge import judge
from texlate.repair_l2 import (
    _resplice,
    split_cid,
)
from texlate.server.settings import scrub
from texlate.textutil import env_str

from ._common import (
    _SENTINELS,
    TaskCtx,
    _translator_clients,
)

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.repair_l2 import TreeRun
    from texlate.xlat.pipeline import ChunkResult

import texlate.server.worker as _w

log = logging.getLogger(__name__)

#: 用户触发重译喂给 ``retranslate_chunk`` 的 ``[compile_error]`` 槽位文本——
#: 无真实编译错可报，明示「上一版译文被读者否决」逼模型产出新译
_RETR_FEEDBACK = (
    "the previous translation of this chunk was rejected by the reader;"
    " produce a fresh, accurate translation"
)


class _Retranslate:
    """单块重译 job mixin：LLM 重译 → resplice → 重编 zh.pdf → 产物刷新。"""

    # ------------------------------------------------------------ job 入口

    async def run_retranslate(self, ctx: TaskCtx, seq: int) -> None:
        """``TaskRunner._retranslate_job`` 派发入口：loop 装配 → job 体 → 线程排空。

        与 ``run()`` 同款的内存字段重建（main_tex/engine_resolved 自
        options 复活）；``tokens_est`` 续行快照值——``_persist_usage``
        与 ``_flush_chunk_updates`` 的计数器回写在其上累加重译真账，
        不续会把 ``tasks.tokens`` 清 0。
        """
        self._loop = asyncio.get_running_loop()
        self._loop_tid = threading.get_ident()
        ctx.main_rel = str(ctx.row.get("main_tex") or "")
        ctx.engine_name = str(ctx.options().get("engine_resolved") or "tectonic")
        try:
            ctx.tokens_est = int(ctx.row.get("tokens") or 0)
        except (TypeError, ValueError):
            ctx.tokens_est = 0
        try:
            await self._retranslate_one(ctx, seq)
        except asyncio.CancelledError:
            # 在飞 to_thread 段即刻收敛（cancel_running/stop 已置过幂等）
            ctx.cancel_flag.set()
            raise
        except Exception as e:
            log.exception("retranslate job crashed for %s seq=%s", ctx.task_id, seq)
            with contextlib.suppress(Exception):
                self._warning(
                    ctx,
                    "retranslate",
                    f"chunk #{seq} 重译失败: {type(e).__name__}: {e}",
                    force=True,
                )
        finally:
            await self._drain_threads(ctx)

    # ------------------------------------------------------------ job 体

    async def _retranslate_one(self, ctx: TaskCtx, seq: int) -> None:
        """Job 体（loop 线程）：块定位 → BYOK 重译 → resplice → 重编 → 刷新。"""
        target = next((r for r in self._all_chunks(ctx) if int(r["seq"]) == seq), None)
        if target is None:
            self._log(ctx, f"retranslate: seq={seq} 无对应 chunk——跳过", force=True)
            return
        if not (ctx.zh_dir / ".splice-done").is_file():
            # enqueue 闸到此间 zh/ 可能被 retry 抹掉——落日志不升格
            self._log(ctx, "retranslate: zh 工程未 splice——跳过", force=True)
            return
        if (
            self._translator_factory is None
            and not ctx.secrets.api_key
            and env_str("TEXLATE_TRANSLATOR") != "mock"
        ):
            # 无 key 静默回退 MockTranslator 会把占位译文覆盖真实译文——
            # 重译是真金白银的用户动作，拒绝 mock 污染（factory 注入与
            # 显式 env=mock 的测试路径不受影响）
            self._log(
                ctx,
                "retranslate: 无 BYOK api_key——跳过（不落 MockTranslator 占位译文）",
                force=True,
            )
            return
        await self._ensure_scans(ctx)
        ctx.expect_cjk = self._expect_cjk(ctx)
        # TreeRun 复用 L2 臂装配：scans 指 zh/ 树 + ok 译文 trans 表 +
        # "fidx:cid"→chunk_id 回写映射 + 含术语表的旁路 pipe
        run, db_of = await self._to_thread(ctx, self._l2_run_state, ctx.zh_dir)
        key = {v: k for k, v in db_of.items()}.get(str(target["chunk_id"]))
        ci = run.chunk_ins.get(key) if key is not None else None
        if key is None or ci is None:
            self._log(ctx, f"retranslate: seq={seq} 不在扫描集——跳过", force=True)
            return
        clients = _translator_clients(run.pipe.translator)
        usage = self._meter_usage(clients)
        try:
            r = await run.pipe.retranslate_chunk(ci, _RETR_FEEDBACK)
        finally:
            # 重译烧的是 BYOK token——不入账就从 task_usage 蒸发；client
            # 与本 job 同 loop，直 await 关
            with contextlib.suppress(Exception):
                self._persist_usage(ctx, usage)
            await _w._aclose_clients(clients)  # noqa: SLF001 -- _w 包 attr 缝
        db_cid = str(target["chunk_id"])
        if r is None:
            self._retr_mark(ctx, db_cid, "provider_error", seq, str(target["status"]))
            self._log(
                ctx,
                f"retranslate: chunk #{seq} 传输层失败——保留原译",
                force=True,
            )
            return
        if r.status != "ok":
            # 校验仍不过：保留原译（L2 的回退原文语义不适用——用户既有
            # ok 译文不该被一次失败的重译销毁）
            self._retr_mark(ctx, db_cid, "validate", seq, str(target["status"]))
            self._log(
                ctx,
                f"retranslate: chunk #{seq} 重译未过校验——保留原译",
                force=True,
            )
            return
        fidx, ccid = split_cid(key)
        run.trans.setdefault(fidx, {})[ccid] = r.translation
        await self._to_thread(ctx, self._retr_resplice, run, fidx)
        self._retr_write_ok(ctx, db_cid, r, seq)
        try:
            compiled = await self._to_thread(ctx, self._retr_recompile)
        except Exception as e:  # noqa: BLE001 -- 重编失败不吞已落的译文/产物
            log.warning("retranslate recompile failed: %s", e)
            compiled = False
        await self._to_thread(ctx, self._retr_dual_md)
        tail = "" if compiled else "（重编译未出 pdf——zh.pdf 保留旧版）"
        self._log(ctx, f"retranslate: chunk #{seq} 已重译{tail}", force=True)
        self.store.heartbeat(ctx.task_id)

    # ------------------------------------------------------------ 落盘链（worker 线程段）

    def _retr_resplice(self, ctx: TaskCtx, run: TreeRun, fidx: int) -> None:
        """受影响文件 reconstruct 重写进 ``zh/`` + 编译哨兵失效 + zh-src.zip 重打。"""
        rewritten = _resplice(run, ctx.zh_dir, ctx.main_rel, {fidx})
        self._log(ctx, f"retranslate: resplice {','.join(rewritten)}", force=True)
        # zh/ 已变——.compile-done 哨兵随之失效（否则 retry 见哨兵直跳
        # 编译段，旧 pdf 当新译文产物交付）
        (ctx.zh_dir / ".compile-done").unlink(missing_ok=True)
        zip_path = ctx.root / "zh-src.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(ctx.zh_dir.rglob("*")):
                self._abort_if_cancelled(ctx)
                if f.is_file() and f.name not in _SENTINELS:
                    zf.write(f, f.relative_to(ctx.zh_dir).as_posix())
        self._register_forced(ctx, "zh_src_zip", "zh-src.zip")

    def _retr_recompile(self, ctx: TaskCtx) -> bool:
        """zh.pdf 重编译（轻量——无 L2/fixloop：单块改动的归因域就是它自己）。

        ``build-zh`` 重建编译；出 pdf 才覆盖登记（失败保留旧 pdf 与旧
        清单——重译不让产物面倒退）。返回是否出新 pdf。
        """
        self._abort_if_cancelled(ctx)
        work = ctx.root / "build-zh"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.zh_dir, work)
        eng = self._engine(ctx)
        rep = self._probe_target(ctx, work)
        res = eng.compile(
            work,
            ctx.main_rel,
            timeout=self._compile_timeout,
            sandbox=True,
            flags=rep.flags if rep else None,
            should_cancel=ctx.cancel_flag.is_set,
        )
        self._abort_if_cancelled(ctx)
        v = judge(res, expect_cjk=ctx.expect_cjk, log_text=self._log_text_of(res))
        ok = False
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "zh.pdf")
            self._embed_tounicode(ctx, ctx.root / "zh.pdf")
            self._register_forced(ctx, "zh_pdf", "zh.pdf")
            (ctx.zh_dir / ".compile-done").write_text("", encoding="utf-8")
            ok = True
        (ctx.root / "compile.log").write_text(
            scrub(self._log_text_of(res), ctx.secrets.api_key),
            encoding="utf-8",
        )
        self._register_forced(ctx, "compile_log", "compile.log")
        for r in v.reasons:
            self._log(ctx, f"judge: {r}", force=True)
        for n in v.notes:
            self._log(ctx, f"judge note: {n}", force=True)
        self._log(
            ctx,
            f"retranslate recompile verdict: {v.status} cat={v.category}",
            force=True,
        )
        return ok

    def _retr_dual_md(self, ctx: TaskCtx) -> None:
        """dual.json + md.zip 重建（终态任务的登记都走 ``_register_forced``）。

        md.zip 是降级产物——原任务产物面有它才刷新（无记录不新造，
        done 任务不会因重译凭空多出降级包）。
        """
        self._build_dual(ctx)
        self._register_forced(ctx, "dual_json", "dual.json")
        had_md = (
            self._on_loop(self.store.file_record, ctx.task_id, "md_zip") is not None
            or (ctx.root / "md.zip").is_file()
        )
        if not had_md:
            return
        self._build_md_zip(ctx)
        if (ctx.root / "md.zip").is_file():
            self._register_forced(ctx, "md_zip", "md.zip")
        else:
            self._on_loop(self.store.delete_file, ctx.task_id, "md_zip")

    # ------------------------------------------------------------ chunks 回写

    def _retr_write_ok(
        self, ctx: TaskCtx, db_cid: str, r: ChunkResult, seq: int
    ) -> None:
        """新译文落 chunks 行：status→ok + 清 error_code + warnings 留痕。"""
        self._flush_chunk_updates(
            ctx,
            [
                (
                    db_cid,
                    {
                        "status": "ok",
                        "translation": r.translation,
                        "error_code": None,
                        "warnings": (
                            json.dumps(r.warnings, ensure_ascii=False)
                            if r.warnings
                            else None
                        ),
                    },
                )
            ],
            [],
        )
        self._retr_chunk_event(ctx, seq, "ok", None)

    def _retr_mark(
        self, ctx: TaskCtx, db_cid: str, code: str, seq: int, status: str
    ) -> None:
        """失败记名：只动 error_code——status/translation 保留原译。"""
        self._flush_chunk_updates(ctx, [(db_cid, {"error_code": code})], [])
        self._retr_chunk_event(ctx, seq, status, code)

    def _retr_chunk_event(
        self, ctx: TaskCtx, seq: int, status: str, code: str | None
    ) -> None:
        """块级 SSE item（translating 段 ``chunk`` 事件同形）——打开中的订阅实时刷新。"""
        counts = self.store.chunk_counts(ctx.task_id)
        row = self.store.get(ctx.task_id)
        item: dict[str, Any] = {"seq": seq, "status": status}
        if code is not None:
            item["error_code"] = code
        self.bus.publish(
            ctx.task_id,
            "chunk",
            {
                "done": counts["done"],
                "total": counts["total"],
                "cached": int(row["cached_chunks"]) if row else 0,
                "failed": counts["failed"],
                "items": [item],
            },
        )

    def _register_forced(self, ctx: TaskCtx, kind: str, rel: str) -> dict[str, Any]:
        """终态任务的产物登记——绕过 ``_register`` 终态守卫（更新清单即本 job 目的）。"""
        size: int | None = None
        sha: str | None = None
        full: Path = ctx.root / rel
        if full.is_file():
            blob = full.read_bytes()
            size = len(blob)
            sha = hashlib.sha256(blob).hexdigest()
        return self._on_loop(
            self.store.put_file, ctx.task_id, kind, rel, size=size, sha256=sha
        )
