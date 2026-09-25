"""``PipelineWorker._Compile`` + fixloop 模块件——compiling 段全链。"""

from __future__ import annotations

import contextlib
import logging
import shutil
import zipfile
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop import CaseSink
from texlate.compile.fixloop.llm_hook import make_llm_hook
from texlate.compile.inject import (
    InjectRejectError,
    prepare_chinese,
)
from texlate.compile.judge import (
    log_died_mid_doc,
    paired_slot_diff,
    pdf_cjk_chars,
)
from texlate.compile.probe import (
    dep_seen,
    deps_diff,
)
from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import (
    reconstruct,
    seq_mark_issues,
    strip_seq_marks,
)
from texlate.pipecore import (
    DB_TO_PIPE,
    PipeJob,
    RepairPolicy,
    _opt_switch,
    compile_judge,
    delivered_db,
    fixloop_flags_tail,
    fixloop_round,
    judge_res,
    l2_repair,
    precheck_job,
    precheck_reject,
    probe_report,
    reject_verdict,
)
from texlate.repair import (
    ENV_FIXLOOP_LLM,
    embed_tounicode_quiet,
    fixloop_cell_parts,
    log_text_of,
    merge_flags,
)
from texlate.repair_l2 import (
    ENV_NO_L2,
    L2_MAX_CHUNKS,
    TreeRun,
    err_signatures,
    err_signatures_text,
    retranslate_hits,
    split_cid,
)
from texlate.server.store import TERMINAL_STATUSES
from texlate.server.upload import (
    _md_member,
    pdf_pages,
)
from texlate.textutil import env_flag, env_str
from texlate.textutil.osutil import ENV_NO_SEQ_MARKS, ENV_TRANSLATOR
from texlate.validate.l0 import pair_feedback
from texlate.xlat.client import DEFAULT_MODEL
from texlate.xlat.pipeline import (
    ChunkIn,
    PipelineConfig,
    XlatPipeline,
    chunk_to_in,
)
from texlate.xlat.placeholders import collect_doc_placeholders
from texlate.xlat.state import atomic_json

from ._common import (
    _FIXLOOP_SRC_EXTS,
    _PROBE_LIST_CAP,
    _PROBE_SEEN_TAG,
    _SENTINELS,
    PROGRESS,
    SegmentCache,
    TaskCtx,
    _compile_done_verdict,
    _new_usage_meter,
    _scrub_deep,
    _Sink,
    _tgt_lang,
    _translator_clients,
    _write_compile_done,
    chunk_db_id,
    zh_slot,
)
from .html import (
    _dual_chunk_row,
)
from .share import (
    _share_sourced,
)
from .translate import (
    FAILED_DB,
    _repend_puts,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable
    from pathlib import Path

    from texlate.compile.engine import (
        CompRes,
        Engine,
    )
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.compile.judge import Verdict
    from texlate.compile.probe import ProbeReport
    from texlate.xlat.client import ChatClient

from texlate.server.worker import seams

log = logging.getLogger(__name__)


def _fixloop_summary(cell: dict[str, Any]) -> dict[str, Any]:
    """Fixloop cell → 压缩摘要（trace/setup 归并机械在 ``repair.fixloop_cell_parts``）。

    ``rounds``×``actions`` 按 round 归并；``round=0/-1`` 是 precheck/gate
    动作单列 ``setup``——salvage 轮 action 键为 ``"salvage"`` 单独对齐。
    """
    trace, setup = fixloop_cell_parts(cell)
    return {
        "verdict": cell.get("verdict"),
        "reject_route": cell.get("reject_route"),
        "gate_fired": cell.get("gate_fired") or [],
        "main": cell.get("main"),
        "engine": cell.get("engine"),
        "log_excerpt": cell.get("log_excerpt"),
        "trace": trace,
        "setup": setup,
        "installed": cell.get("installed") or [],
        "advisories": cell.get("advisories") or [],
    }


def _seq_mark_scrub(rel: str, suffix: str, src: bytes) -> bytes:
    """``.tex`` 回灌件的 seq 锚失衡 lint——BDC/EMC 不配平或 MCID 重复时剥全锚。

    fixloop 改写可能拆散 BDC/EMC 对或复制出重复 MCID（fileset_relocate
    同锚双份）；剥锚换编译面干净，锚面降级模糊匹配（pdf.js 对失衡本就
    容忍，此处是双保险不阻断）。
    """
    if suffix != ".tex" or b"TLXC" not in src:
        return src
    issues = seq_mark_issues(src.decode("utf-8", errors="replace"))
    if not issues:
        return src
    log.warning(
        "seq marks imbalanced in %s (%s); stripped", rel, "; ".join(issues)
    )
    return strip_seq_marks(src.decode("utf-8", errors="replace")).encode("utf-8")


def _sync_fixed_sources(work: Path, zh: Path) -> int:
    """Fixloop 改动回灌：``work`` 内 TeX 输入层文件 → ``zh/`` 镜像（含删除）。

    copytree 起点两侧一致，分叉只来自 fixloop 改写/落包/隔离——按
    ``_FIXLOOP_SRC_EXTS`` 同步并删除 ``zh/`` 侧多余源文件（rename 隔离
    类规则的删除语义）；``_*`` 前缀**目录**（_tect_out/_minted-*）与
    哨兵不进——顶层 ``_*.tex`` 这类下划线文件名是合法源件照常镜像。
    返回变更文件数。
    """
    keep: set[str] = set()
    n = 0
    for f in work.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(work)
        if (len(rel.parts) > 1 and rel.parts[0].startswith("_")) or f.name in _SENTINELS:
            continue
        if f.suffix.lower() not in _FIXLOOP_SRC_EXTS:
            continue
        keep.add(rel.as_posix())
        dst = zh / rel
        src = _seq_mark_scrub(rel.as_posix(), f.suffix.lower(), f.read_bytes())
        if not dst.is_file() or dst.read_bytes() != src:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src)
            n += 1
    for f in zh.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(zh)
        # 排除口径 = ``_`` 前缀目录——copy 侧同口径故 keep 永不覆盖该类
        # 子树，删侧同排除防 zh/ 自带的产物目录（_tect_out 等）被当多余
        # 源清掉；顶层 ``_*`` 文件与常规模源件同走 keep 比对
        if (len(rel.parts) > 1 and rel.parts[0].startswith("_")) or f.name in _SENTINELS:
            continue
        if f.suffix.lower() in _FIXLOOP_SRC_EXTS and rel.as_posix() not in keep:
            f.unlink()
            n += 1
    return n


def _repair_detail(ctx: TaskCtx, *, include_share: bool = False) -> dict[str, Any]:
    """修复摘要归集：precheck/l2/fixloop 三段入 detail/err 的同一装配。

    ``include_share`` 时 ``share`` 键排最前——partial err 原手装序
    （share→precheck→l2→fixloop）经 ``err.update`` 逐字保留。
    """
    detail: dict[str, Any] = {}
    if include_share and ctx.share:
        detail["share"] = ctx.share
    if ctx.precheck:
        detail["precheck"] = ctx.precheck
    if ctx.l2:
        detail["l2"] = ctx.l2
    if ctx.fixloop:
        detail["fixloop"] = ctx.fixloop
    return detail


def _delivered_map(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """``all_chunks`` 行 → ``{chunk_id: 译文}`` 交付映射（``delivered_db`` 口径）。

    ``isinstance(str)`` 判与 ``zh_slot`` 同口径——TEXT 列可落 BLOB 等非
    str 腐格，放行进 splice/L2 重译会把字节料写进 .tex 源树。
    """
    return {
        r["chunk_id"]: r["translation"]
        for r in rows
        if delivered_db(r["status"], r["translation"])
        and isinstance(r["translation"], str)
    }


class _Compile:
    """compiling 段 mixin：探测/编译/fixloop/L2/双语产物。"""

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

    def _build_zh(self, ctx: TaskCtx) -> None:
        """回写 zh 工程：按 chunks 表译文 splice + ctex 注入 + zip 登记。"""
        self._abort_if_cancelled(ctx)
        if (ctx.zh_dir / ".splice-done").is_file():
            return
        if ctx.zh_dir.exists():
            shutil.rmtree(ctx.zh_dir)
        shutil.copytree(ctx.base_dir, ctx.zh_dir)
        rows = self._on_loop(self._all_chunks, ctx)
        trans = self._env_judge_filter(ctx, _delivered_map(rows), rows)
        marks_on = _opt_switch(
            ctx.options(), "seq_marks", ENV_NO_SEQ_MARKS, explicit=None
        )
        # moving-arg 全量放行（废 .tex 面 RX 闸）：hyperref 常经 .cls/.sty 传递
        # 加载，.tex 扫描必漏检——漏检时同 MCID 被 .toc 重放成双 BDC，命中又
        # 误杀全部标题/图题锚。实证注入仅换 pdfstring 期 hyperref
        # "removing \special" 警告、编译无害（4 任务 zh.pdf 均产出）；目录/
        # 页眉重放出的重复 occurrence 由读侧 seqpos dedupe 收敛。
        n_files = 0
        seq0 = 0
        for rel, res in ctx.scans.items():
            self._abort_if_cancelled(ctx)  # 逐文件 reconstruct——大工程秒级段
            cur0 = seq0
            seq0 += len(res.chunks)  # 无条件累计——跳译文件 seq 仍占位
            by_int: dict[int, str] = {}
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                zh = trans.get(cid)
                if zh is not None:
                    by_int[c.id] = zh
            if not by_int:
                continue
            out = reconstruct(
                res,
                by_int,
                mark_seq0=cur0 if marks_on else None,
                mark_moving=marks_on,
            )
            if marks_on and (issues := seq_mark_issues(out)):
                self._log(ctx, f"seqmarks {rel} 失衡({'; '.join(issues)})——剥锚降级")
                out = strip_seq_marks(out)
            if notes := paired_slot_diff(res.vtex, out, rel):
                self._log(ctx, f"slotdiff {rel}: {'; '.join(notes)}")
            (ctx.zh_dir / rel).write_text(out, encoding="utf-8")
            ctx.leftover_ph += len(PH_RX.findall(out))
            n_files += 1
        self._log(ctx, f"splice: {n_files} files rewritten")
        try:
            info = prepare_chinese(ctx.zh_dir, ctx.main_rel)
        except InjectRejectError:
            # F3 降级交付：译文已 splice——zh-src.zip 先落盘，再由
            # run() 归 partial+reject_at=inject（不落 .splice-done，
            # resume 重打重拒同态收敛）
            self._zip_zh(ctx)
            raise
        self._log(ctx, f"inject: {info}")
        # zip 先于哨兵：崩在 zip 里时 resume 会因无哨兵重建 zh/ 重打，
        # 反序则哨兵在、产物登记永远缺席
        self._zip_zh(ctx)
        (ctx.zh_dir / ".splice-done").write_text("", encoding="utf-8")

    def _zip_zh(self, ctx: TaskCtx) -> None:
        """``zh/`` → zh-src.zip 登记（fixloop 回灌后重打复用同一函数）。"""
        zip_path = ctx.root / "zh-src.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(ctx.zh_dir.rglob("*")):
                self._abort_if_cancelled(ctx)
                if f.is_file() and f.name not in _SENTINELS:
                    zf.write(f, f.relative_to(ctx.zh_dir).as_posix())
        self._register(ctx, "zh_src_zip", "zh-src.zip")

    def _task_texmf(self, ctx: TaskCtx, eng: Engine) -> Engine:
        """任务级 ``ctx.root/_texmf`` 装件树接管（None-only 预设语义）。

        fixloop ``_wire_engine`` 只在 texmfhome 为 None 时接线——此处预设
        即接管落点：装件落任务根而非 ``build-zh/_texmf``（retry rmtree
        不丢装件）；en/zh 编译与 precheck/fixloop 装件共享同树——zh 侧
        装上的缺件对 en 编译可见（en 重试闸的前提）。
        """
        if getattr(eng, "texmfhome", "unset") is None:
            eng.texmfhome = ctx.root / "_texmf"  # type: ignore[attr-defined]
        return eng

    def _new_engine(self, ctx: TaskCtx, name: str, **kw: object) -> Engine:
        """引擎构造单点：factory 注入优先，否则 ``seams.engine_for``——两路都过 ``_task_texmf``。"""
        if self._engine_factory is not None:
            return self._task_texmf(ctx, self._engine_factory(name))
        return self._task_texmf(ctx, seams.engine_for(name, **kw))

    def _engine(self, ctx: TaskCtx) -> Engine:
        """按注入面/默认构造引擎（xelatex 走 best-effort nonstopmode）。"""
        eng = ctx.engine_name or "tectonic"
        kw: dict[str, Any] = {"halt_on_error": False} if eng == "xelatex" else {}
        return self._new_engine(ctx, eng, **kw)

    def _probe_target(self, ctx: TaskCtx, work: Path) -> ProbeReport | None:
        r"""``target_probe`` best-effort 壳：编译前声明依赖预扫 + 信号播报。

        产物全走 log 事件（最小侵入）：依赖解析计数聚合行 + ``tl_pkg``
        可装清单 + 逐条 ``rep.notes``（missing 清单/路由信号理由——
        ``rep.missing`` 即 fixloop ``missing_file`` 前置情报；装包仍是
        fixloop/tlmgr 职责，此处只播报）。``prefer_engine`` 与
        ``route_project`` 决策不一致时多记一行——只播报不重复决策。
        探针崩溃只记行返回 ``None``，绝不阻塞编译。
        """
        rep = probe_report(
            work,
            ctx.main_rel,
            deps_index=self._deps_index,
            probe_fn=seams.target_probe,
            on_error=lambda e: self._log(
                ctx, f"probe crashed: {type(e).__name__}: {e}"
            ),
        )
        if rep is None:
            return None
        parts = [
            f"deps={len(rep.deps)}",
            f"local={sum(d.resolved == 'local' for d in rep.deps)}",
            f"tl_pkg={sum(d.resolved == 'tl_pkg' for d in rep.deps)}",
            f"missing={len(rep.missing)}",
        ]
        if rep.prefer_engine:
            parts.append(f"prefer_engine={rep.prefer_engine}")
        if rep.flags:
            parts.append(f"flags={','.join(rep.flags)}")
        self._log(ctx, "probe: " + " ".join(parts))
        if rep.tl_packages:
            self._log(ctx, f"probe tl_pkg: {','.join(rep.tl_packages)}")
        for n in rep.notes:
            self._log(ctx, f"probe: {n}")
        if rep.prefer_engine and rep.prefer_engine != ctx.engine_name:
            self._log(
                ctx,
                f"probe: prefer_engine={rep.prefer_engine} 与 route 决策 "
                f"{ctx.engine_name} 不一致（仅记录不切换）",
            )
        return rep

    def _probe_diff(self, ctx: TaskCtx, rep: ProbeReport | None, res: CompRes) -> None:
        r"""编译后 ``deps_diff`` 对拍：期望输入集 vs ``res.deps`` 权威集。

        ``expected`` = 静态 ``\input`` 图（``rep.inputs``）+ local 命中声明
        的 detail；``unread`` = 期望却未被引擎读取，``undeclared`` = 权威集
        多出的隐式输入（kpsewhich 解析产物等）——一条聚合行，列表截断。
        ``rep.missing`` 逐条过 ``dep_seen`` 复核（真缺失 vs 路径/时序，
        fixloop ``install_file`` 前置判据）；``rep.flags`` 被引擎拒放的
        （``flags_dropped``）也记一行。全程 best-effort，崩溃只记行。
        """
        if rep is None:
            return
        try:
            expected = set(rep.inputs)
            expected.update(d.detail for d in rep.deps if d.resolved == "local")
            diff = deps_diff(expected, res.deps)
            if diff.authoritative:
                line = (
                    f"probe diff: seen={len(diff.seen)} "
                    f"unread={len(diff.unseen)} undeclared={len(diff.extra)}"
                )
                if diff.unseen:
                    line += " unread: " + ",".join(diff.unseen[:_PROBE_LIST_CAP])
                    if len(diff.unseen) > _PROBE_LIST_CAP:
                        line += f"+{len(diff.unseen) - _PROBE_LIST_CAP}"
                self._log(ctx, line)
                if rep.missing:
                    tags = ", ".join(
                        f"{f}={_PROBE_SEEN_TAG[dep_seen(res.deps, f)]}"
                        for f in rep.missing
                    )
                    self._log(ctx, f"probe missing 复核: {tags}")
            else:
                self._log(
                    ctx,
                    "probe diff: 引擎未产 .fls/.mk 依赖记录——差分不可判",
                )
            dropped = [f for f in rep.flags if f in res.flags_dropped]
            if dropped:
                self._log(
                    ctx,
                    f"probe: 引擎拒放 flags {','.join(dropped)}（flags_dropped）",
                )
        except Exception as e:  # noqa: BLE001 -- 差分诊断崩不拖编译
            self._log(ctx, f"probe diff crashed: {type(e).__name__}: {e}")

    def _compile_en(self, ctx: TaskCtx) -> None:
        """en.pdf：base/ 拷贝编译 + fixloop 基建救援；失败只记 warning（不阻塞译文链）。

        原文无译文伤——L2 不归此臂；不出 pdf 时 fixloop 修基建（缺包/字体/
        工具链）再登记。修复只动 ``build-en`` 一次性树，不回灌 ``base/``
        （``base`` 是 zh 重建与 fixloop baseline 的 pristine 源）。
        """
        self._abort_if_cancelled(ctx)
        if self._has_pdf(ctx, "en_pdf"):
            return
        work = ctx.root / "build-en"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.base_dir, work)
        self._en_mark_inject(ctx, work)
        rep = self._probe_target(ctx, work)
        eng = self._engine(ctx)
        res = eng.compile(
            work,
            ctx.main_rel,
            timeout=self._compile_timeout,
            sandbox=True,
            flags=rep.flags if rep else None,
            should_cancel=ctx.cancel_flag.is_set,
        )
        # eng.compile 是原子段（无插桩点）——跑完即收敛，后续 diff/登记是白费
        self._abort_if_cancelled(ctx)
        self._probe_diff(ctx, rep, res)
        # en 首编错误签名快照 → zh L2 归因基线：源生错签名不归 chunk
        # （fixloop_en 前置取——救回前全量；救回修复的源生错 zh 侧同样
        # 修得动，留在基线里不会误豁免译文伤）
        ctx.en_err_sigs = err_signatures(res)
        if (not res.has_pdf or self._en_died(res)) and self._fixloop_enabled(ctx):
            res = self._fixloop_en(
                ctx,
                work,
                eng,
                res,
                probe_flags=[str(f) for f in (rep.flags if rep else [])],
            )
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "en.pdf")
            self._register(ctx, "en_pdf", "en.pdf")
            if self._en_died(res):
                self._warning(
                    ctx,
                    "en_compile",
                    "原文编译中途死亡，en.pdf 为截断残件（fixloop 未救回）",
                )
        else:
            self._warning(
                ctx,
                "en_compile",
                f"原文编译未出 pdf（{res.log.first_error or res.stdout_tail[:120]}）",
            )

    def _en_mark_inject(self, ctx: TaskCtx, work: Path) -> None:
        """en.pdf 注锚：identity reconstruct。

        translations=None → 原文逐字节，只叠 /TLXC marked-content——seq
        口径与 _build_zh 同序累计，双侧 seq 对位一致。谓词拒绝/失衡文件
        剥锚留原文，注锚异常不挡编译。
        """
        marks_on = _opt_switch(
            ctx.options(), "seq_marks", ENV_NO_SEQ_MARKS, explicit=None
        )
        if not marks_on or not ctx.scans:
            return
        seq0 = 0
        n_marked = 0
        for rel, res in ctx.scans.items():
            cur0 = seq0
            seq0 += len(res.chunks)  # 无条件累计——与 zh 侧同序保 seq 对位
            if not res.chunks:
                continue
            try:
                out = reconstruct(res, None, mark_seq0=cur0, mark_moving=True)
            except Exception as e:  # noqa: BLE001 -- 注锚失败=原样编译
                self._log(ctx, f"seqmarks-en {rel} 注锚异常({e})——原样编译")
                continue
            if issues := seq_mark_issues(out):
                self._log(
                    ctx,
                    f"seqmarks-en {rel} 失衡({'; '.join(issues)})——剥锚降级",
                )
                out = strip_seq_marks(out)
            (work / rel).write_text(out, encoding="utf-8")
            n_marked += 1
        self._log(ctx, f"seqmarks-en: {n_marked} files marked")

    def _en_died(self, res: CompRes) -> bool:
        """en.pdf 截断收编闸判定。

        e116 实证：en 编译 35 页死亡、残件 pdf 因 ``has_pdf`` 非空被无条件
        登记。``Output written`` 截断照印不可信，唯一信号是
        ``Emergency stop``/``Fatal error`` 致命中止签名
        （``judge.log_died_mid_doc`` 单源）。出 pdf 但死了 → 照样进
        fixloop 救；救不回登记时记 warning。
        """
        return bool(res.has_pdf) and bool(log_died_mid_doc(self._log_text_of(res)))

    def _log_text_of(self, res: CompRes) -> str:
        """``repair.log_text_of`` 单源委托（.log 非空优先、stdout_tail 兜底）。"""
        return log_text_of(res)

    def _expect_cjk(self, ctx: TaskCtx) -> bool:
        """0-chunk 主文档（includepdf 壳等）不期待 CJK——cjk_chars=0 是其正确终态。

        只能在 loop 线程调（store conn 线程亲和）——编译线程读 ``ctx.expect_cjk``。
        """
        return self.store.chunk_counts(ctx.task_id)["total"] != 0

    def _fixloop_enabled(self, ctx: TaskCtx) -> bool:
        """Fixloop 开关：``options.fixloop`` 显式 > ``TEXLATE_NO_FIXLOOP``（默认开）。

        与 ``_l2_enabled``/``_env_judge_enabled``/e2e 同序——显式参数优先；
        曾 env 胜 options（相反序），同侧两开关不一致已统一。决议本体在
        ``pipecore.RepairPolicy``（e2e/worker policy 单源）。
        """
        return RepairPolicy.resolve(ctx.options()).fixloop

    def _fixloop_engine(self, ctx: TaskCtx, eng: Engine) -> Engine:
        """Fixloop 轮内用引擎：xelatex 独立构造 ``halt_on_error=True``（e2e 权威口径）。

        轮内编译要「首错清晰可分类」——主编译引擎是 best-effort
        nonstopmode（``halt_on_error=False``），续跑日志会让 post-fix
        复判混入下游错误、分类签名漂移，故不复用传入引擎。factory 在场
        尊重注入（测试面）；tectonic 无此旋钮保持原引擎。
        """
        if ctx.engine_name != "xelatex":
            return eng
        return self._new_engine(ctx, "xelatex", halt_on_error=True)

    def _repair_event(self, ctx: TaskCtx, etype: str, payload: dict[str, Any]) -> None:
        """修复链实况帧发布：``bus.publish`` 经 ``_on_loop`` 回弹 + BYOK 秘钥 scrub。

        best-effort 观测面——帧发布失败只留 debug 痕，不拖垮修复臂本体。
        fixloop ``on_round`` 回调与 L2 阶段帧同走此口。
        """
        try:
            self._on_loop(
                self.bus.publish,
                ctx.task_id,
                etype,
                _scrub_deep(payload, ctx.secrets.api_key),
            )
        except Exception:
            log.debug("%s event publish failed", etype, exc_info=True)

    def _run_fixloop(
        self, ctx: TaskCtx, work: Path, eng: Engine, first: CompRes
    ) -> CompRes:
        """Fixloop 救援循环（docs/spec/compile.md）：规则引擎在 ``build-zh`` 内重编到出 pdf/放弃。

        摘要留 ``ctx.fixloop`` 并进 ``task_events``（``fixloop`` 事件可重放）+
        ``fixloop-cases.jsonl`` 沉淀（§5.5）。救回出 pdf 时把改动过的 TeX
        输入层文件回灌 ``zh/`` 并重打 zh-src.zip——让用户拿到的源码树真能
        编译。返回末次 ``CompRes``（fixloop 崩溃/未编译则原样回传）。
        """
        res, summary, rescued = self._fixloop_pass(
            ctx,
            work,
            eng,
            first,
            cond="zh",
            expect_cjk=ctx.expect_cjk,
            probe_flags=ctx.probe_flags,
        )
        if summary is not None:
            ctx.fixloop = _scrub_deep(summary, ctx.secrets.api_key)
        if rescued:
            n = _sync_fixed_sources(work, ctx.zh_dir)
            if n:
                self._log(ctx, f"fixloop: {n} 个修复文件回灌 zh/，重打 zh-src.zip")
                self._zip_zh(ctx)
        return res

    def _fixloop_en(
        self,
        ctx: TaskCtx,
        work: Path,
        eng: Engine,
        first: CompRes,
        *,
        probe_flags: list[str],
    ) -> CompRes:
        """原文侧基建救援：同一 fixloop 引擎（cases 记 ``cond="en"``），不回灌 base。

        摘要只记一行任务日志——``ctx.fixloop`` 是 zh 归账位（partial 判据
        面），en 侧失败本来就只走 warning，不另建持久键。
        """
        res, summary, _rescued = self._fixloop_pass(
            ctx,
            work,
            eng,
            first,
            cond="en",
            expect_cjk=False,
            probe_flags=probe_flags,
        )
        if summary is not None:
            self._log(
                ctx,
                f"fixloop(en): verdict={summary.get('verdict')}"
                f" installed={summary.get('installed')}",
            )
        return res

    def _fixloop_pass(  # noqa: PLR0913 -- 开关面穿透两臂同一契约
        self,
        ctx: TaskCtx,
        work: Path,
        eng: Engine,
        first: CompRes,
        *,
        cond: str,
        expect_cjk: bool,
        probe_flags: Iterable[str],
    ) -> tuple[CompRes, dict[str, Any] | None, bool]:
        """Fixloop 救援循环共享核 → ``(末次 CompRes, 摘要|None=崩溃, 救回标记)``。

        zh/en 两臂同一引擎/实况面/cases 沉淀；``cond`` 只标 cases 来源，
        ``expect_cjk`` 供 flags_tail 跨引擎复判（en 恒 False——原文编译
        不受 CJK 判据约束）。摘要归账（``ctx.fixloop``）与源码回灌是
        调用方决策，不进共享核。
        """
        hook, hook_usage, hook_clients = self._llm_hook_pack(ctx)

        def _evt(t: str, p: dict[str, Any]) -> None:
            # en/zh 两臂同走 fixloop 事件型——cond 入帧供消费侧分辨来源
            self._repair_event(ctx, t, {**p, "cond": cond} if t == "fixloop" else p)

        sink = _Sink(
            lambda m: self._log(ctx, m),
            _evt,
        )
        try:
            self._abort_if_cancelled(ctx)
            # 轮实况/done 帧/cell log/主文件分歧行随 fixloop_round 出口
            # （sink 绑 _log/_repair_event——原臂后段同键集前置到环尾）
            cell, fix_last = fixloop_round(
                work,
                self._fixloop_engine(ctx, eng),
                engine_name=ctx.engine_name,
                baseline_dir=ctx.base_dir,
                main_rel=ctx.main_rel,
                llm_hook=hook,
                compile_timeout=self._compile_timeout,
                should_cancel=ctx.cancel_flag.is_set,
                sink=sink,
                corpus_id=ctx.task_id,
                cond=cond,
                case_sink=CaseSink(self.data_dir / "fixloop-cases.jsonl"),
            )
        except Exception as e:  # noqa: BLE001 -- fixloop 崩不拖垮编译段
            self._log(ctx, f"fixloop crashed: {type(e).__name__}: {e}")
            self._repair_event(
                ctx,
                "fixloop",
                {
                    "phase": "done",
                    "cond": cond,
                    "crashed": True,
                    "message": f"{type(e).__name__}: {e}",
                },
            )
            return first, None, False
        finally:
            self._teardown_llm_hook(ctx, hook_usage, hook_clients)
        # fixloop 轮间无插桩（repair 属主面外）——出环即收敛
        self._abort_if_cancelled(ctx)
        summary = _fixloop_summary(cell)
        res = fix_last or first
        # 跨引擎消费 + 审计 note 的共享尾在 pipecore.fixloop_flags_tail
        # （e2e fixloop_job 同臂）——dropped 多为 shell-escape 需求，
        # tectonic 丢的 flag 由 route 候选里的 xelatex 带全量 flag 重编
        # 取优。``route_engines`` 是 _build_base 持久化的生效候选列表——
        # 显式 engine= 覆盖时只剩用户指定那台，臂自熄（尊重显式选型）。
        # status_of 惰性——dropped 路径才需 incumbent 判据，flags-only
        # 不白费一轮 judge。
        xr, note = fixloop_flags_tail(
            summary,
            cell,
            engine_name=ctx.engine_name,
            route_engines=[str(e) for e in ctx.options().get("route_engines") or []],
            status_of=lambda: judge_res(res, expect_cjk=expect_cjk).status,
            work=work,
            main_rel=ctx.main_rel,
            timeout=self._compile_timeout,
            probe_flags=probe_flags,
            expect_cjk=expect_cjk,
            # halt_on_error=False：与主编译/salvage 同口径 best-effort——
            # retry 是交付路径终末重编（非轮内分类编译），nonstopmode
            # 续跑才能把 incumbent=fail 的树救成 partial（裁决见
            # tmp/b8-e2e/halt-on-error-ruling.md）
            make_engine=lambda: self._new_engine(
                ctx, "xelatex", halt_on_error=False
            ),
            should_cancel=ctx.cancel_flag.is_set,
        )
        adopted_cross = False
        if xr is not None and xr.adopted:
            res = xr.res
            adopted_cross = True
        if note is not None:
            self._log(ctx, f"fixloop: {note}")
        return res, summary, bool(cell.get("final_pdf")) or adopted_cross

    def _l2_enabled(self, ctx: TaskCtx) -> bool:
        """L2 回灌开关：``options.l2`` 显式优先，缺省读 ``TEXLATE_NO_L2``（默认开）。

        共享译文任务恒关——零 token 是结构承诺（``_share_apply`` 不回退
        自译同理），options/env 无权打开。
        """
        if _share_sourced(ctx):
            return False
        return RepairPolicy.resolve(ctx.options()).l2

    def _llm_hook_pack(
        self, ctx: TaskCtx
    ) -> tuple[LlmHook | None, dict[str, Any] | None, list[ChatClient]]:
        """Fixloop ``escalate_llm`` 的 server 侧接线：``(hook, usage, clients)``。

        与 e2e ``TEXLATE_FIXLOOP_LLM`` opt-in 不同——server 侧**默认开**
        （与 L2 parity）：任务带真 BYOK key 即建 hook，token 经
        ``usage_sink`` → ``_persist_usage`` 落账。None 条件（序即优先级）：

        - 共享译文任务（``_share_sourced``）：零 token 结构承诺，任何开关无权开；
        - ``options.llm_hook`` 显式 false / ``TEXLATE_FIXLOOP_LLM=0``；
        - 无 ``api_key``（含 ``TEXLATE_TRANSLATOR=mock``）：不给裸
          env-key client——那会绕开 BYOK 计费面。
        """
        if _share_sourced(ctx):
            return None, None, []
        opt = ctx.options().get("llm_hook")
        if opt is not None and (
            opt is False or str(opt).strip().lower() in ("0", "false", "no", "off")
        ):
            return None, None, []
        if not env_flag(ENV_FIXLOOP_LLM, default=True):
            return None, None, []
        if self._translator_factory is not None:
            # 注入路径：factory 产 translator 直接给 hook（测试桩语义调用方担）
            tr = self._translator_factory(ctx)
            clients = _translator_clients(tr)
            return make_llm_hook(translator=tr), self._meter_usage(clients), clients
        force = env_str(ENV_TRANSLATOR)
        if not ctx.secrets.api_key or force == "mock":
            if opt:
                self._log(ctx, "llm_hook: 无 BYOK api_key——跳过 escalate_llm")
            return None, None, []
        usage, sink = _new_usage_meter()
        model = ctx.secrets.model or DEFAULT_MODEL
        tr = self._resolve_translator(ctx, sink=sink, retry=False)
        return make_llm_hook(translator=tr, model=model), usage, []

    def _teardown_llm_hook(
        self,
        ctx: TaskCtx,
        usage: dict[str, Any] | None,
        clients: list[ChatClient],
        *,
        tag: str = "llm_hook",
    ) -> None:
        """LLM 旁路臂收尾——``_teardown_bypass`` 薄别名（``tag``→``label``）。

        保留旧方法名/签名：既有调用点与测试面（``worker._teardown_llm_hook``
        直调）不改名；env_judge/L2/llm_hook 同构收尾本体已单源归并。
        """
        self._teardown_bypass(ctx, usage, clients, label=tag)

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
        if "doc_ph" not in ctx.memo:
            ctx.memo["doc_ph"] = collect_doc_placeholders(
                ci.content for ci in chunk_ins.values()
            )
        pipe = XlatPipeline(
            self._make_translator(ctx),
            config=PipelineConfig(tgt_lang=_tgt_lang(str(ctx.row["target_lang"]))),
            glossary=self._make_glossary(
                ctx,
                placeholders=ctx.memo["doc_ph"],
            ),
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

    def _en_err_sigs(self, ctx: TaskCtx) -> set[str]:
        """基线错误签名集（en 侧）——``_compile_en`` 已快照则直取，否则回扫 ``build-en`` 残存 .log。

        resume/dedup 路径 en 不重编但签名仍要。
        """
        if ctx.en_err_sigs:
            return ctx.en_err_sigs
        work = ctx.root / "build-en"
        if work.is_dir():
            for lf in sorted(work.rglob("*.log")):
                try:
                    text = lf.read_text(errors="replace")
                except OSError:
                    continue
                ctx.en_err_sigs = err_signatures_text(text, project_root=work)
                if ctx.en_err_sigs:
                    break
        return ctx.en_err_sigs

    def _l2_repair_zh(
        self, ctx: TaskCtx, work: Path, eng: Engine, res: CompRes
    ) -> tuple[dict[str, Any], CompRes, Verdict | None]:
        """L2 回灌一轮：阶梯骨架在 ``pipecore.l2_repair``（e2e ``l2_repair_job`` 同件）。

        resplice 只重写 ``build-zh``——DB 回写 + ``_sync_fixed_sources``
        灌回 ``zh/`` + 重打 zh-src.zip 由本层补齐（worker 的成品树是
        ``zh/`` 而非 work），仅重编走过（v2 非 None）才回写。``_recompile``
        内保留 compile→judge 间中止点（repair 侧 ``checkpoint`` 在
        retranslate 前后/recompile 后另补三拍，合原作粒度超集）。
        返回 (l2 报告, 最新 CompRes, 新 Verdict 或 None=未重编）。
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
                seq_marks=_opt_switch(
                    ctx.options(), "seq_marks", ENV_NO_SEQ_MARKS, explicit=None
                ),
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

    def _precheck_attempt(
        self,
        ctx: TaskCtx,
        work: Path,
        eng: Engine,
        res: CompRes,
        v: Verdict,
    ) -> tuple[CompRes, Verdict]:
        """第 0 招预检臂：fixloop precheck 相独立跑 + 装上件/收得 flag 后重编。

        缺包类失败在 L2 归因前就消掉——missing_file 进 L2 兜底只会把块
        拖去重译/回退（``t_f74894ebc691aaf4`` algpseudocodex 实证）。
        预检引擎走 ``_fixloop_engine``（与 fixloop 轮内同机——precheck
        无编译，halt_on_error 无关，要的是同一台接线对象）；报告形走
        ``pipecore.precheck_job``（两臂同一 ``run_precheck`` 包壳——
        崩溃兜底形 ``{"error": ...}`` 复刻原 except 臂语义）。
        ``reject:<rid>`` 不重编——路由拒绝交 fixloop 复现 + 跨引擎消费。
        """
        pre = precheck_job(
            PipeJob(
                work=work,
                main_rel=ctx.main_rel,
                eng_name=ctx.engine_name,
                timeout=self._compile_timeout,
            ),
            engine_fn=lambda _name: self._fixloop_engine(ctx, eng),
        )
        if "error" in pre:  # 预检崩不拖垮编译段——precheck_job 兜底形
            self._log(ctx, f"precheck crashed: {pre['error']}")
            return res, v
        ctx.precheck = _scrub_deep(
            {
                "verdict": pre.get("verdict"),
                "reject_route": pre.get("reject_route"),
                "gate_fired": pre.get("gate_fired") or [],
                "installed": pre.get("installed") or [],
                "engine_flags": pre.get("engine_flags") or [],
                "advisories": pre.get("advisories") or [],
                "actions": pre.get("actions") or [],
            },
            ctx.secrets.api_key,
        )
        self._repair_event(ctx, "precheck", {"phase": "done", "report": ctx.precheck})
        for a in pre.get("advisories") or []:
            self._log(ctx, f"precheck advisory: {a}")
        if pre.get("installed"):
            self._log(ctx, f"precheck installed: {pre['installed']}")
        if reject_verdict(pre.get("verdict")):
            return res, v
        flags = [str(f) for f in pre.get("engine_flags") or []]
        if not (pre.get("installed") or flags):
            return res, v  # 空转省一发编译
        self._repair_event(
            ctx, "precheck", {"phase": "progress", "message": "预检后重编"}
        )
        return compile_judge(
            eng,
            work,
            ctx.main_rel,
            timeout=self._compile_timeout,
            flags=merge_flags(ctx.probe_flags, flags),
            expect_cjk=ctx.expect_cjk,
            should_cancel=ctx.cancel_flag.is_set,
            after_compile=lambda _r: self._abort_if_cancelled(ctx),
        )

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

    def _compile_zh(self, ctx: TaskCtx) -> str:
        """zh.pdf：zh/ 拷贝编译 +（非 clean 时）precheck → L2 回灌 → fixloop + judge(expect_cjk)。

        修复链顺序对齐 e2e ``_repair_chain``：precheck 预检（装缺件，
        fixloop 第 0 招独立相）先消 missing_file 类基建失败；L2（译文
        归因重译）先于 fixloop——L2 resplice 重写 workdir，规则修源在
        其后兜底。precheck ``reject:<rid>`` 跳过 L2——路由拒绝交
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
                    if ctx.expect_cjk
                    and pdf_cjk_chars(ctx.root / "zh.pdf") == 0
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
            # eng.compile 原子段跑完即收敛——L2/fixloop/登记是后续白费
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
            res, v = self._l2_attempt(ctx, work, eng, res, v)
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

    def _embed_tounicode(self, ctx: TaskCtx, pdf: Path) -> None:
        """``repair.embed_tounicode_quiet`` 委托——失败经 ``on_error`` 落任务日志。"""
        n = embed_tounicode_quiet(
            pdf,
            on_error=lambda e: self._log(
                ctx, f"tounicode embed failed: {type(e).__name__}: {e}"
            ),
        )
        if n:
            self._log(ctx, f"tounicode: {n} 个 GB1 CJK 字体补 ToUnicode cmap")

    def _build_dual(self, ctx: TaskCtx) -> None:
        """dual.json（§5.4）：documents 版本/pages + 页级 alignment + chunks。

        调用方 ``_to_thread`` 起（pdf_pages/build_alignment 扫
        content stream 是 CPU 重活）——store 读一律 ``_on_loop`` 回弹。
        """
        self._abort_if_cancelled(ctx)
        files = self._on_loop(self.store.files, ctx.task_id)
        doc: dict[str, Any] = {"version": 1, "documents": {}, "chunks": []}
        en = files.get("en_pdf")
        zh = files.get("zh_pdf")
        if en:
            doc["documents"]["original"] = {
                "version": en.get("sha256") or "",
                "pages": pdf_pages(ctx.root / en["path"]),
            }
        if zh:
            doc["documents"]["translated"] = {
                "version": zh.get("sha256") or "",
                "pages": pdf_pages(ctx.root / zh["path"]),
            }
        # named-dest 单调链锚点同步（texlate.align）；缺侧/无公共锚 → 同页映射
        doc["alignment"] = (
            seams.build_alignment(ctx.root / en["path"], ctx.root / zh["path"])
            if en and zh
            else {"kind": "pages"}
        )
        # 占位符 → 原文体表：eprint 链 chunk 文本带 ``[[TYPE_n]]`` 掩码——
        # 阅读面（HtmlPane md 渲染）要 ph 反查真实公式/引用再渲 KaTeX。
        # scans 缺场（resume 直进编译段）尽力重解析；拿不到就缺省——
        # 前端对无 ph 的 token 降级成样式 chip，不挡 dual 落盘。
        if not ctx.scans:
            try:
                _rows, ctx.scans = self._parse_all(ctx)
            except Exception as e:  # noqa: BLE001 -- 源已清/重解析失败不挡落盘
                self._log(ctx, f"dual ph reparse failed: {e}")
        frag_of: dict[str, dict[str, str]] = {}
        if ctx.scans:
            try:
                frag_of = self._ph_frag_map(ctx)
            except Exception as e:  # noqa: BLE001
                self._log(ctx, f"dual ph frag map failed: {e}")
        for r in self._on_loop(self._all_chunks, ctx):
            # 行投影与 html 链 ``_build_dual_html`` 同件——zh 位
            # coerce/非 ok 留空口径在 ``_dual_chunk_row`` docstring
            ch = _dual_chunk_row(r)
            ph = frag_of.get(r["chunk_id"])
            if ph:
                ch["ph"] = ph
            doc["chunks"].append(ch)
        atomic_json(ctx.root / "dual.json", doc)
        self._register(ctx, "dual_json", "dual.json")
        # seqpos 预算：reader 首开的懒算峰（39pp 实测 ~11s pypdf CMap
        # 重解析）挪进编译尾段——此处本就在 _to_thread 里，首开即缓存命中
        try:
            from texlate.server.seqpos import seqpos_for_task  # noqa: PLC0415

            seqpos_for_task(ctx.root, doc)
        except Exception as e:  # noqa: BLE001 -- 对位是增强件，失败不挡交付
            self._log(ctx, f"seqpos precompute failed: {e}")

    def _build_md_zip(self, ctx: TaskCtx) -> None:
        """md.zip 降级产物（§5.4）：编译彻底失败但译文在库 → 双语 markdown 包。

        ``view:"html"`` 的登记物——HtmlPane 实读 dual.json ``chunks``，本包
        是同数据的可下载形态（按 ``src_file`` 章节化、seq 锚注释保留 1:1
        对账位）。零译文不产：登记了而 chunks 无料会让前端落 empty 态。
        只在 ``_stage_compile`` 无 pdf 终态分支调用，此处 dual.json 已落。
        """
        self._abort_if_cancelled(ctx)
        rows = self._on_loop(self._all_chunks, ctx)
        # 同 dual.json zh 位口径——非 ok/非 str 译文行不算译文载荷，
        # zh 槽全空即「零译文不产」
        if not rows or not any(zh_slot(r) for r in rows):
            return
        by_file: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_file.setdefault(str(r["src_file"]), []).append(r)
        seen: set[str] = set()
        with zipfile.ZipFile(ctx.root / "md.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            for src_file in sorted(by_file):
                parts = [
                    f"<!-- chunk:{r['seq']} kind:{r['kind']} -->\n\n"
                    f"{r['src_text']}\n\n---\n\n"
                    f"{zh_slot(r)}\n"
                    for r in sorted(by_file[src_file], key=lambda x: int(x["seq"]))
                ]
                zf.writestr(_md_member(src_file, seen), "\n".join(parts))
        self._register(ctx, "md_zip", "md.zip")
        self._log(ctx, f"md.zip: {sum(len(v) for v in by_file.values())} chunks")
