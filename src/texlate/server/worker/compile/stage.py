"""worker.compile.stage — compiling 段编排 + ``_Compile`` 组合根叶 (worker.compile 域缝叶)。

终态阶梯编排（``_stage_compile``/``_compile_zh_or_salvage``/``_no_pdf_finish``）、
zh 编译修复链驱动（``_compile_zh``：compile→judge→precheck→logfix→fixloop→judge）、
修复摘要归集件 ``_repair_detail``；``_Compile`` 是全部 compile_* 叶
mixin 的组合根——worker ``PipelineWorker`` 经 ``from texlate.server.worker.compile import _Compile``
拿到的即本类，方法集分布见各叶 docstring。
"""

from __future__ import annotations

import contextlib
import shutil
from typing import TYPE_CHECKING, Any

from texlate.compile.judge import (
    pdf_cjk_chars,
)
from texlate.pipecore import (
    compile_judge,
    judge_res,
    precheck_reject,
    reject_verdict,
)
from texlate.server.store import TERMINAL_STATUSES
from texlate.server.worker._common import (
    PROGRESS,
    _compile_done_verdict,
    _write_compile_done,
)
from texlate.server.worker.compile.artifacts import _CompileArtifacts
from texlate.server.worker.compile.en import _CompileEn
from texlate.server.worker.compile.engine import _CompileEngine
from texlate.server.worker.compile.fixloop import _CompileFixloop
from texlate.server.worker.compile.logfix import _CompileLogfix
from texlate.server.worker.compile.splice import _CompileSplice

if TYPE_CHECKING:
    from texlate.compile.engine import (
        CompRes,
    )
    from texlate.server.store import Store
    from texlate.server.worker._common import TaskCtx


def _repair_detail(ctx: TaskCtx, *, include_share: bool = False) -> dict[str, Any]:
    """修复摘要归集：precheck/logfix/fixloop 三段入 detail/err 的同一装配。

    ``include_share`` 时 ``share`` 键排最前——partial err 原手装序
    （share→precheck→logfix→fixloop）经 ``err.update`` 逐字保留。
    """
    detail: dict[str, Any] = {}
    if include_share and ctx.share:
        detail["share"] = ctx.share
    if ctx.precheck:
        detail["precheck"] = ctx.precheck
    if ctx.logfix:
        detail["logfix"] = ctx.logfix
    if ctx.fixloop:
        detail["fixloop"] = ctx.fixloop
    return detail


class _CompileStage:
    """compiling 段编排 mixin：终态阶梯 + zh 编译修复链驱动。"""

    if TYPE_CHECKING:
        # 组合根 ``worker._Core.__init__`` 注入的共享态契约
        store: Store
        _compile_timeout: float

    # ------------------------------------------------------------ compiling

    async def _stage_compile(  # 编译段终态阶梯直铺
        self, ctx: TaskCtx, *, share: bool = False
    ) -> None:
        """compiling：en/zh 双侧编译 + zh-src.zip + dual.json + 终态。

        ``share=True``（share 导入链）：重编未出 pdf 不归 fault——共享包
        验证失败是策略拒绝（partial + ``reject_at=share_verify``），
        与 route/inject reject 同形。
        """
        self._stage(ctx, "compiling", "编译", PROGRESS["compiling"][0])
        await self._ensure_scans(ctx)
        await self._to_thread(ctx, self._build_zh)
        self._check_cancelled(ctx)
        self._progress(ctx, PROGRESS["compiling"][0] + 4)
        await self._to_thread(ctx, self._compile_en)
        ctx.expect_cjk = self._expect_cjk(ctx)
        verdict_zh = await self._compile_zh_or_salvage(ctx)
        self._check_cancelled(ctx)
        self._progress(ctx, PROGRESS["compiling"][1])
        # pypdf 页树走查 + named-dest 对齐是 CPU 重活——出 loop 线程，
        # 否则大 PDF 期间 SSE/心跳/分发全停
        await self._to_thread(ctx, self._build_dual)
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态：终态已写，不再覆盖
        # fixloop 策略拒绝（verdict reject:<rid>）与 e2e 同案归
        # partial + reject_at=fixloop——拒绝是降级交付不是故障。
        # 例外：reject_route→xelatex 换编被采用（cross_engine.adopted）时
        # 终态已按 xelatex 复判取优——策略拒绝让位给实际产物判定。
        verdict = str((ctx.fixloop or {}).get("verdict") or "")
        cross_adopted = bool((ctx.fixloop or {}).get("cross_engine", {}).get("adopted"))
        if reject_verdict(verdict) and not cross_adopted:
            await self._to_thread(ctx, self._build_md_zip)
            self._reject(
                ctx,
                "fixloop_reject",
                f"fixloop policy reject: {verdict}",
                reject_at="fixloop",
                detail=_repair_detail(ctx) or None,
            )
            await self._maybe_share_pack(ctx)
            return
        failed = self.store.chunk_counts(ctx.task_id)["failed"]
        # done 只配 clean 判据——verdict=fail（死层/截断残件/引擎被杀）即便
        # 出了 pdf 也是 partial（c32920 死层曾被 has_pdf 臂洗成 done）。
        if verdict_zh == "clean" and failed == 0:
            status, err = "done", None
        elif verdict_zh != "fail" or self._has_pdf(ctx, "zh_pdf"):
            status = "partial"
            err = {
                "code": "compile",
                "message": "有 pdf 但判据未全绿或块级失败",
                "retryable": True,
            }
            err.update(_repair_detail(ctx, include_share=True))
        else:
            await self._no_pdf_finish(ctx, share=share)
            await self._maybe_share_pack(ctx)
            return
        self._finish_terminal(ctx, status, err=err)
        await self._maybe_share_pack(ctx)

    async def _compile_zh_or_salvage(self, ctx: TaskCtx) -> str:
        """``_compile_zh`` + 异常降级臂：编译段崩也把在库译文包出来。

        dual/md_zip 只吃 chunks 表不依赖编译成败——尽力补出再走 fault。
        cancel 在飞不救（旗标已置即用户要它死，不再花秒级补产物）；
        CancelledError 是 BaseException 不经 ``except Exception`` 臂。
        返回 zh 编译 verdict 三态（``_stage_compile`` 终态阶梯消费）。
        """
        try:
            return await self._to_thread(ctx, self._compile_zh)
        except Exception:
            if not ctx.cancel_flag.is_set():
                for salvage in (self._build_dual, self._build_md_zip):
                    with contextlib.suppress(Exception):
                        await self._to_thread(ctx, salvage)
            raise

    async def _no_pdf_finish(self, ctx: TaskCtx, *, share: bool) -> None:
        """无 pdf 终态臂：md.zip 降级产物 → share 归策略拒绝 / tex 归 fault。

        fixloop 跑过仍无 pdf → 规则耗尽（``fixloop_exhausted``），摘要随
        error_json 落库供 triage。
        """
        await self._to_thread(ctx, self._build_md_zip)
        detail = _repair_detail(ctx) or None
        if share:
            self._reject(
                ctx,
                "share_verify",
                "share zh compile: no pdf",
                reject_at="share_verify",
                detail=detail,
            )
            return
        self._fail(
            ctx,
            "fixloop_exhausted" if ctx.fixloop else "compile",
            "zh compile: no pdf",
            retryable=True,
            stage="compiling",
            detail=detail,
        )

    def _has_pdf(self, ctx: TaskCtx, kind: str) -> bool:
        rec = self._on_loop(self.store.file_record, ctx.task_id, kind)
        return rec is not None and bool(rec.get("bytes"))

    def _expect_cjk(self, ctx: TaskCtx) -> bool:
        """0-chunk 主文档（includepdf 壳等）不期待 CJK——cjk_chars=0 是其正确终态。

        只能在 loop 线程调（store conn 线程亲和）——编译线程读 ``ctx.expect_cjk``。
        """
        return self.store.chunk_counts(ctx.task_id)["total"] != 0

    def _compile_zh(self, ctx: TaskCtx) -> str:
        """zh.pdf：zh/ 拷贝编译 +（非 clean 时）precheck → logfix 回灌 → fixloop + judge(expect_cjk)。

        修复链顺序对齐 ``pipecore.repair_chain``：precheck 预检（装缺件，
        fixloop 第 0 招独立相）先消 missing_file 类基建失败；logfix（译文
        归因重译）先于 fixloop——logfix resplice 重写 workdir，规则修源在
        其后兜底。precheck ``reject:<rid>`` 跳过 logfix——路由拒绝交
        fixloop 复现 + 跨引擎消费。
        ``.compile-done`` 哨兵落 ``zh/`` 内：main 变更的 retry 会 rmtree
        ``zh/``，哨兵与 zh_pdf 记录同生共死；resume 见哨兵+pdf 即跳过重编。
        哨兵载荷=终态 verdict——旧版空件只能回退 cjk 抽测复判（死层是
        唯一可仅靠 pdf 复测的否决判据）。
        返回 judge 三态 verdict：``_stage_compile`` 的 done 只配 clean。
        """
        self._abort_if_cancelled(ctx)
        if (ctx.zh_dir / ".compile-done").is_file() and self._has_pdf(ctx, "zh_pdf"):
            v0 = _compile_done_verdict(ctx.zh_dir)
            if v0 is None:
                # 旧版空哨兵——死层可复测，其余判据无法从成品 pdf 重建
                v0 = (
                    "fail"
                    if ctx.expect_cjk and pdf_cjk_chars(ctx.root / "zh.pdf") == 0
                    else "clean"
                )
            return v0
        work = ctx.root / "build-zh"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.zh_dir, work)
        eng = self._engine(ctx)
        rep = self._probe_target(ctx, work)
        ctx.probe_flags = [str(f) for f in (rep.flags if rep else [])]

        def _post(r: CompRes) -> None:
            # eng.compile 原子段跑完即收敛——logfix/fixloop/登记是后续白费
            self._abort_if_cancelled(ctx)
            self._probe_diff(ctx, rep, r)

        res, v = compile_judge(
            eng,
            work,
            ctx.main_rel,
            timeout=self._compile_timeout,
            flags=rep.flags if rep else None,
            expect_cjk=ctx.expect_cjk,
            should_cancel=ctx.cancel_flag.is_set,
            after_compile=_post,
        )
        if v.status != "clean" and self._fixloop_enabled(ctx):
            res, v = self._precheck_attempt(ctx, work, eng, res, v)
            self._abort_if_cancelled(ctx)
        pre_reject = precheck_reject(ctx.precheck)
        if v.status != "clean" and not pre_reject:
            res, v = self._logfix_attempt(ctx, work, eng, res, v)
            self._abort_if_cancelled(ctx)
        if v.status != "clean" and self._fixloop_enabled(ctx):
            res = self._run_fixloop(ctx, work, eng, res)
            v = judge_res(res, expect_cjk=ctx.expect_cjk)
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "zh.pdf")
            self._embed_tounicode(ctx, ctx.root / "zh.pdf")
            self._register(ctx, "zh_pdf", "zh.pdf")
            _write_compile_done(ctx.zh_dir, v.status)
        self._judge_log(ctx, res, v)
        self._log(ctx, f"verdict: {v.status} cat={v.category} errs={v.n_errors}")
        return v.status


class _Compile(
    _CompileStage,
    _CompileSplice,
    _CompileEn,
    _CompileEngine,
    _CompileFixloop,
    _CompileLogfix,
    _CompileArtifacts,
):
    """compiling 段 mixin：探测/编译/fixloop/logfix/双语产物。"""
