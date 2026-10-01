"""``PipelineWorker._Pdf``——upload_pdf/docx/epub 产物臂（babeldoc/export）。"""

from __future__ import annotations

import logging
import shutil
import time
from typing import TYPE_CHECKING, Any

from texlate.compile.sandbox import find_tool
from texlate.server.babeldoc import (
    BabeldocJob,
    BabeldocRun,
    default_timeout,
    lang_out_for,
    run_babeldoc,
    write_glossary_csv,
)
from texlate.server.settings import scrub
from texlate.server.store import TERMINAL_STATUSES

from ._common import (
    _FLUSH_MS,
    _FLUSH_N,
    _PIPE_TO_DB,
    PROGRESS,
    TaskCtx,
    _AbortingTranslator,
    _new_usage_meter,
    _scrub_deep,
    _translator_clients,
    chunk_error_code,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from texlate.export.common import ExportReport
    from texlate.server.events import EventBus
    from texlate.server.store import Store
    from texlate.xlat.pipeline import (
        ChunkResult,
    )

from texlate.server.worker import seams

log = logging.getLogger(__name__)

#: babeldoc ``on_progress`` 回弹节流——pct 动 ≥1pt 或距上次 ≥0.2s 才
#: 经 ``_on_loop`` 写 progress（sidecar 逐 tick 扇出成本高；终态 100
#: 由 ``transition`` 写不在此面）
_PROGRESS_MIN_DPCT = 1.0
_PROGRESS_MIN_S = 0.2


class _Pdf:
    """upload_pdf/docx/epub 产物臂 mixin（babeldoc/export）。"""

    if TYPE_CHECKING:
        # 组合根 ``worker._Core.__init__`` 注入的共享态契约
        bus: EventBus
        store: Store
        _babeldoc: str | None

    # ------------------------------------------------------------ pdf 管线

    def _babeldoc_job(
        self, ctx: TaskCtx, src: Path, outdir: Path, workdir: Path
    ) -> BabeldocJob:
        """``TaskCtx`` → ``BabeldocJob``：BYOK 凭证 + config base_url 兜底 + options 透传。

        术语表复用主链 ``_make_glossary``（confine 规则同款），写成
        babeldoc ``--glossary-files`` CSV。
        """
        cfg = ctx.config()
        options = ctx.options()
        glossary_csv = None
        glossary = self._make_glossary(ctx)
        if glossary is not None:
            glossary_csv = write_glossary_csv(
                workdir / "glossary.csv", list(glossary.as_dict().items())
            )
        return BabeldocJob(
            src=src,
            outdir=outdir,
            workdir=workdir,
            model=ctx.secrets.model or str(ctx.row["model"]),
            base_url=ctx.secrets.base_url or str(cfg.get("base_url") or ""),
            api_key=ctx.secrets.api_key,
            lang_out=lang_out_for(str(ctx.row["target_lang"])),
            qps=self._opt_int(ctx, options, "qps", 4, hi=50),
            pages=str(options.get("pages") or "") or None,
            dual=bool(options.get("dual", True)),
            alternating=bool(options.get("alternating", True)),
            send_temperature=bool(options.get("send_temperature", False)),
            custom_system_prompt=(
                str(options.get("custom_system_prompt") or "") or None
            ),
            glossary_csv=glossary_csv,
            timeout=default_timeout(),
        )

    async def _finish_pdf(self, ctx: TaskCtx, run: BabeldocRun) -> None:
        """Sidecar 结果 → 产物登记 + 终态迁移 + done 事件。"""
        ctx.tokens_est = int(run.stats.get("total_tokens") or 0)
        self.store.update_fields(ctx.task_id, tokens=ctx.tokens_est)
        if ctx.tokens_est:
            # babeldoc 不报调用次数——calls=0 只落 token 真账（与主链 T4 同表）
            self.store.record_usage(
                ctx.task_id,
                model=str(ctx.row["model"]),
                calls=0,
                prompt_tokens=int(run.stats.get("prompt_tokens") or 0),
                completion_tokens=int(run.stats.get("completion_tokens") or 0),
                latency_s=float(run.seconds),
            )
        await self._to_thread(ctx, self._harvest_pdf_outputs, run)
        self._log(ctx, f"babeldoc rc={run.rc} status={run.status} stats={run.stats}")
        if run.status == "failed":
            for ln in run.stderr_tail.strip().splitlines()[-3:]:
                self._log(ctx, f"babeldoc stderr: {ln}")
            self._fail(
                ctx,
                run.error_code or "compile",
                run.error or "babeldoc 失败",
                retryable=run.retryable,
                stage="compiling",
                detail={"babeldoc": _scrub_deep(run.stats, ctx.secrets.api_key)},
            )
            return
        await self._to_thread(ctx, self._build_dual)
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态：终态已写，不再覆盖
        status, err = "done", None
        if run.status == "degraded":
            status = "partial"
            err = {
                "code": "degraded",
                "message": scrub(run.error, ctx.secrets.api_key),
                "retryable": True,
            }
        self._finish_terminal(
            ctx,
            status,
            err=err,
            stats_extra={"babeldoc": _scrub_deep(run.stats, ctx.secrets.api_key)},
        )

    def _harvest_pdf_outputs(self, ctx: TaskCtx, run: BabeldocRun) -> None:
        """Sidecar 产物物化（worker 线程）：copyfile + ToUnicode 注入 + 登记。"""
        self._abort_if_cancelled(ctx)
        mono = run.outputs.get("mono")
        dual = run.outputs.get("dual")
        if mono is not None:
            shutil.copyfile(mono, ctx.root / "zh.pdf")
            self._embed_tounicode(ctx, ctx.root / "zh.pdf")
            self._register(ctx, "zh_pdf", "zh.pdf")
        if dual is not None:
            shutil.copyfile(dual, ctx.root / "dual.pdf")
            self._embed_tounicode(ctx, ctx.root / "dual.pdf")
            self._register(ctx, "dual_pdf", "dual.pdf")

    def _prep_pdf_dirs(
        self, ctx: TaskCtx, src: Path, outdir: Path, workdir: Path
    ) -> None:
        """``upload_pdf`` 前置物化（worker 线程）：en.pdf 回登记 + retry 清旧产物。"""
        self._abort_if_cancelled(ctx)
        en = ctx.root / "en.pdf"
        if not en.exists():
            shutil.copyfile(src, en)
        self._register(ctx, "en_pdf", "en.pdf")
        for d in (outdir, workdir):
            if d.exists():
                shutil.rmtree(d)  # retry 幂等：旧产物/旧 tracking 不混入本单

    async def _run_pdf(self, ctx: TaskCtx) -> None:
        """upload_pdf：BabelDOC sidecar（AGPL 边界=独立进程，§2.4 + pdf-path §4）。

        产物面：en.pdf（原文回登记）+ mono→zh.pdf + dual→dual.pdf；
        ``run_babeldoc`` 的 status 判定（tracking/fallback/CJK 兜底）
        映射终态——ok→done、degraded→partial、failed→fault。
        """
        self._stage(ctx, "compiling", "BabelDOC 双语转换", 30)
        src = self._first_upload(ctx, stage="compiling")
        if src is None:
            return
        outdir = ctx.root / "babeldoc-out"
        workdir = ctx.root / "babeldoc-work"
        await self._to_thread(ctx, self._prep_pdf_dirs, src, outdir, workdir)
        binary = self._babeldoc or find_tool("babeldoc")
        if binary is None:
            self._fail(
                ctx,
                "internal",
                "babeldoc 未安装（pipx/uv tool install babeldoc）",
                retryable=False,
                stage="compiling",
            )
            return
        job = self._babeldoc_job(ctx, src, outdir, workdir)
        last_stage = ""
        last_pct = -1.0
        last_emit = 0.0

        def on_progress(pct: float, stage: str) -> None:
            # sidecar 逐 tick 扇出节流（_PROGRESS_MIN_* 口径）
            nonlocal last_stage, last_pct, last_emit
            now = time.monotonic()
            if (
                abs(pct - last_pct) >= _PROGRESS_MIN_DPCT
                or now - last_emit >= _PROGRESS_MIN_S
            ):
                last_pct = pct
                last_emit = now
                self._on_loop(
                    self._progress,
                    ctx,
                    30 + min(65, round(65 * pct / 100)),
                )
            if stage and stage != last_stage:
                last_stage = stage
                self._log(ctx, f"babeldoc stage: {stage}")

        run = await run_babeldoc(
            job,
            binary=binary,
            on_progress=on_progress,
            on_log=lambda line: self._log(ctx, f"babeldoc: {line}"),
            should_cancel=ctx.cancel_flag.is_set,
        )
        self._check_cancelled(ctx)
        await self._finish_pdf(ctx, run)

    # ------------------------------------------------------------ doc 管线

    async def _run_doc(self, ctx: TaskCtx) -> None:  # noqa: C901 -- 接线/出口阶梯平铺即 spec
        """docx/epub：``export_document`` 双语插译（无编译链——产物即双语原文档）。

        ``export_document`` 内部 ``asyncio.run(XlatPipeline)``——必须
        ``to_thread`` 起独立 loop（本 loop 直调即 RuntimeError）；``on_result``
        在 thread 内触发，DB/事件写一律 ``_on_loop`` 回弹。``state_dir`` 落
        ``tasks/{id}/export-state/``——retry 由 StateStore 前缀校验自动续跑，
        成功即被 export 侧清理。产物 kind = ``zh_docx``/``zh_epub``。
        """
        from texlate.export import export_document  # noqa: PLC0415 -- 重依赖惰性加载
        from texlate.export.common import ExportError  # noqa: PLC0415

        src = self._first_upload(ctx, stage="translating")
        if src is None:
            return
        await self._to_thread(ctx, self._register, "src_tar", f"upload/{src.name}")
        self._stage(ctx, "translating", "文档插译", PROGRESS["translating"][0])
        ext = src.suffix.lower()
        if ext not in (".docx", ".epub"):
            ext = f".{ctx.row['kind']}"
        dst = ctx.root / f"{src.stem}_bilingual{ext}"
        counters = {"done": 0, "failed": 0}
        # 真实 token/延迟记账（tex 路 _stage_translate 同款 sink）——
        # _PerCallTranslator 内建挂 sink；factory 注入路径下补挂到共享 client
        usage, sink = _new_usage_meter()
        translator = self._doc_translator(ctx, sink)
        clients = _translator_clients(translator)
        for c in clients:
            c.usage_sink = sink

        on_result, flush_items = self._doc_on_result(ctx, counters)

        def _export(tctx: TaskCtx) -> ExportReport:
            # 取消传导：export 内嵌管线逐 unit 调 translator——旗标置位即
            # _SectionAbort 快失败排空（CancelledError 会打死管线 worker）
            return export_document(
                src,
                dst,
                _AbortingTranslator(translator, tctx.cancel_flag),
                target_lang=str(tctx.row["target_lang"]),
                state_dir=tctx.root / "export-state",
                glossary=self._make_glossary(tctx),
                on_result=on_result,
            )

        try:
            report = await self._to_thread(ctx, _export)
        except ExportError as e:
            # DRM/fixed-layout/畸形包/不识格式——重试无意义的拒翻面
            self._fail(
                ctx,
                "unsupported_format",
                str(e),
                retryable=False,
                stage="translating",
            )
            return
        finally:
            flush_items()
            try:
                self._persist_usage(ctx, usage, replace_est=True)
            except Exception:
                log.debug("doc usage persist failed", exc_info=True)
            # clients 在 to_thread 的 ephemeral loop 里跑过——aclose 尽力而为；
            # _PerCallTranslator 臂 client 懒绑消费侧 loop（export run 包装
            # finally 内自关），此处 clients 空跳过
            if clients:
                try:
                    await seams._aclose_clients(clients)  # noqa: SLF001 -- seams 缝
                except Exception:
                    log.debug("doc client aclose failed", exc_info=True)
        self._check_cancelled(ctx)
        for w in report.warnings:
            self._warning(ctx, "export", w)
        await self._to_thread(ctx, self._register, f"zh_{ctx.row['kind']}", dst.name)
        n_bad = report.skipped + report.fault
        self.store.update_fields(
            ctx.task_id,
            total_chunks=report.units,
            done_chunks=report.translated + report.unchanged,
            failed_chunks=n_bad,
            tokens=ctx.tokens_est,
        )
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态：终态已写，不再覆盖
        status = "done" if n_bad == 0 else "partial"
        err = None
        if status == "partial":
            err = {
                "code": "provider_error" if report.fault else "validate",
                "message": (
                    f"{n_bad} 段回退原文"
                    f"（skipped {report.skipped} / fault {report.fault}）"
                ),
                "retryable": bool(report.fault),
            }
        self._finish_terminal(ctx, status, err=err)

    def _doc_on_result(
        self, ctx: TaskCtx, counters: dict[str, int]
    ) -> tuple[Callable[[ChunkResult], None], Callable[[], None]]:
        """``on_result`` 工厂：逐 unit 计数 + tokens 估算 → ``_doc_emit`` 合批回弹。

        每 unit 一条 chunk 事件会把 ``EVENT_CAP`` 打满（tex 路 ``_FLUSH_N``/
        ``_FLUSH_MS`` 同口径合批）；返回 ``(on_result, flush)``——flush 由
        ``_run_doc`` finally 调排空缓冲尾部。
        """
        items: list[dict[str, Any]] = []
        last_flush = time.monotonic()

        def flush() -> None:
            nonlocal last_flush
            last_flush = time.monotonic()
            if not items:
                return
            self._on_loop(
                self._doc_emit,
                ctx,
                counters["done"],
                counters["failed"],
                ctx.tokens_est,
                {
                    "done": counters["done"],
                    "total": 0,
                    "cached": 0,
                    "failed": counters["failed"],
                    "items": list(items),
                },
            )
            items.clear()

        def on_result(r: ChunkResult) -> None:
            counters["done"] += 1
            if r.status in ("skipped", "fault"):
                counters["failed"] += 1
            ctx.tokens_est += (len(r.source) + len(r.translation)) // 4
            item: dict[str, Any] = {
                "seq": counters["done"],
                "status": _PIPE_TO_DB.get(r.status, "failed"),
            }
            code = chunk_error_code(r)
            if code is not None:
                item["error_code"] = code
            items.append(item)
            if len(items) >= _FLUSH_N or time.monotonic() - last_flush >= _FLUSH_MS:
                flush()

        return on_result, flush

    def _doc_emit(
        self,
        ctx: TaskCtx,
        done: int,
        failed: int,
        tokens: int,
        payload: dict[str, Any],
    ) -> None:
        """Doc 路逐 unit 回弹段（``_on_loop`` 切回 loop 线程的单写者面）。

        units 枚举在 export 内部、total 事前不可知——progress 按 done 自增
        近似并钉在 ``hi-1`` 以下（终态 100 由 ``transition`` 写）。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态：孤儿 thread 的迟到 emit 不落盘/扇出
        lo, hi = PROGRESS["translating"]
        self.store.update_fields(
            ctx.task_id,
            done_chunks=done,
            failed_chunks=failed,
            tokens=tokens,
            progress=min(hi - 1, lo + done),
        )
        self.bus.publish(ctx.task_id, "chunk", payload)
