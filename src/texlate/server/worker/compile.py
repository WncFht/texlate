"""``PipelineWorker._Compile`` + fixloop 模块件——compiling 段全链。"""

from __future__ import annotations

import asyncio
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
from texlate.compile.judge import judge
from texlate.compile.probe import (
    dep_seen,
    deps_diff,
)
from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import reconstruct
from texlate.repair import (
    _ENV_FIXLOOP_LLM,
    _ENV_NO_FIXLOOP,
    _ENV_NO_L2,
    L2_MAX_CHUNKS,
    _retranslate_hits,
    _ruleset_with_baseline,
    _split_cid,
    _TreeRun,
    consume_engine_flags,
    embed_tounicode_quiet,
    fixloop_cell_parts,
    l2_repair_round,
    log_text_of,
    run_fixloop,
)
from texlate.server.settings import scrub
from texlate.server.store import TERMINAL_STATUSES
from texlate.server.upload import (
    _md_member,
    pdf_pages,
)
from texlate.textutil import env_flag, env_str
from texlate.validate.l0 import validate_pair
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
    _new_usage_meter,
    _PerCallTranslator,
    _scrub_deep,
    _tgt_lang,
    _translator_clients,
    chunk_db_id,
    opt_bool,
)
from .share import (
    _share_sourced,
)

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.engine import (
        CompRes,
        Engine,
    )
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.compile.judge import Verdict
    from texlate.compile.probe import ProbeReport
    from texlate.xlat.client import ChatClient

import texlate.server.worker as _w

log = logging.getLogger(__name__)


def _fixloop_summary(cell: dict[str, Any]) -> dict[str, Any]:
    """Fixloop cell → 压缩摘要（trace/setup 归并机械在 ``repair.fixloop_cell_parts``）。

    ``rounds``×``actions`` 按 round 归并；``round=0/-1`` 是 precheck/gate
    动作单列 ``setup``——salvage 轮 action 键为 ``"salvage"`` 单独对齐。
    """
    trace, setup = fixloop_cell_parts(cell)
    return {
        "verdict": cell.get("verdict"),
        "main": cell.get("main"),
        "engine": cell.get("engine"),
        "log_excerpt": cell.get("log_excerpt"),
        "trace": trace,
        "setup": setup,
        "installed": cell.get("installed") or [],
        "advisories": cell.get("advisories") or [],
    }


def _sync_fixed_sources(work: Path, zh: Path) -> int:
    """Fixloop 改动回灌：``work`` 内 TeX 输入层文件 → ``zh/`` 镜像（含删除）。

    copytree 起点两侧一致，分叉只来自 fixloop 改写/落包/隔离——按
    ``_FIXLOOP_SRC_EXTS`` 同步并删除 ``zh/`` 侧多余源文件（rename 隔离
    类规则的删除语义）；``_*`` 前缀目录（_tect_out/_minted-*）与哨兵不进。
    返回变更文件数。
    """
    keep: set[str] = set()
    n = 0
    for f in work.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(work)
        if rel.parts[0].startswith("_") or f.name in _SENTINELS:
            continue
        if f.suffix.lower() not in _FIXLOOP_SRC_EXTS:
            continue
        keep.add(rel.as_posix())
        dst = zh / rel
        if not dst.is_file() or dst.read_bytes() != f.read_bytes():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dst)
            n += 1
    for f in zh.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(zh)
        # copy 侧不收 ``_*`` 顶层项 → keep 永不含之；删侧同口径排除，
        # 否则 zh/ 自带的 _ 前缀目录（_tect_out 等）被当多余源清掉
        if rel.parts[0].startswith("_") or f.name in _SENTINELS:
            continue
        if f.suffix.lower() in _FIXLOOP_SRC_EXTS and rel.as_posix() not in keep:
            f.unlink()
            n += 1
    return n


class _Compile:
    """compiling 段 mixin：探测/编译/fixloop/L2/双语产物。"""

    # ------------------------------------------------------------ compiling

    async def _stage_compile(self, ctx: TaskCtx, *, share: bool = False) -> None:
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
        ok = await self._to_thread(ctx, self._compile_zh)
        self._check_cancelled(ctx)
        self._progress(ctx, PROGRESS["compiling"][1])
        # pypdf 页树走查 + named-dest 对齐是 CPU 重活——出 loop 线程，
        # 否则大 PDF 期间 SSE/心跳/分发全停
        await self._to_thread(ctx, self._build_dual)
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态：终态已写，不再覆盖
        # fixloop 策略拒绝（verdict reject:<rid>）与 e2e 同案归
        # partial + reject_at=fixloop——拒绝是降级交付不是故障
        verdict = str((ctx.fixloop or {}).get("verdict") or "")
        if verdict.startswith("reject:"):
            await self._to_thread(ctx, self._build_md_zip)
            detail: dict[str, Any] = {}
            if ctx.l2:
                detail["l2"] = ctx.l2
            if ctx.fixloop:
                detail["fixloop"] = ctx.fixloop
            self._reject(
                ctx,
                "fixloop_reject",
                f"fixloop policy reject: {verdict}",
                reject_at="fixloop",
                detail=detail or None,
            )
            await self._maybe_share_pack(ctx)
            return
        failed = self.store.chunk_counts(ctx.task_id)["failed"]
        if ok and failed == 0:
            status, err = "done", None
        elif ok or self._has_pdf(ctx, "zh_pdf"):
            status = "partial"
            err = {
                "code": "compile",
                "message": "有 pdf 但判据未全绿或块级失败",
                "retryable": True,
            }
            if ctx.share:
                err["share"] = ctx.share
            if ctx.l2:
                err["l2"] = ctx.l2
            if ctx.fixloop:
                err["fixloop"] = ctx.fixloop
        else:
            await self._no_pdf_finish(ctx, share=share)
            await self._maybe_share_pack(ctx)
            return
        self.store.transition(
            ctx.task_id,
            status,
            progress=100,
            error=err,
            force=True,
            message="完成" if status == "done" else "部分完成",
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
        await self._maybe_share_pack(ctx)

    async def _no_pdf_finish(self, ctx: TaskCtx, *, share: bool) -> None:
        """无 pdf 终态臂：md.zip 降级产物 → share 归策略拒绝 / tex 归 fault。

        fixloop 跑过仍无 pdf → 规则耗尽（``fixloop_exhausted``），摘要随
        error_json 落库供 triage。
        """
        await self._to_thread(ctx, self._build_md_zip)
        detail: dict[str, Any] = {}
        if ctx.l2:
            detail["l2"] = ctx.l2
        if ctx.fixloop:
            detail["fixloop"] = ctx.fixloop
        if share:
            self._reject(
                ctx,
                "share_verify",
                "share zh compile: no pdf",
                reject_at="share_verify",
                detail=detail or None,
            )
            return
        self._fail(
            ctx,
            "fixloop_exhausted" if ctx.fixloop else "compile",
            "zh compile: no pdf",
            retryable=True,
            stage="compiling",
            detail=detail or None,
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
        rows = self._on_loop(self.store.all_chunks, ctx.task_id)
        trans = {
            r["chunk_id"]: r["translation"]
            for r in rows
            if r["status"] == "ok" and r["translation"]
        }
        trans = self._env_judge_filter(ctx, trans, rows)
        n_files = 0
        for rel, res in ctx.scans.items():
            self._abort_if_cancelled(ctx)  # 逐文件 reconstruct——大工程秒级段
            by_int: dict[int, str] = {}
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                zh = trans.get(cid)
                if zh is not None:
                    by_int[c.id] = zh
            if not by_int:
                continue
            out = reconstruct(res, by_int)
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

    def _engine(self, ctx: TaskCtx) -> Engine:
        """按注入面/默认构造引擎（xelatex 走 best-effort nonstopmode）。"""
        eng = ctx.engine_name or "tectonic"
        if self._engine_factory is not None:
            return self._engine_factory(eng)
        kw: dict[str, Any] = {"halt_on_error": False} if eng == "xelatex" else {}
        return _w.engine_for(eng, **kw)

    def _probe_target(self, ctx: TaskCtx, work: Path) -> ProbeReport | None:
        r"""``target_probe`` best-effort 壳：编译前声明依赖预扫 + 信号播报。

        产物全走 log 事件（最小侵入）：依赖解析计数聚合行 + ``tl_pkg``
        可装清单 + 逐条 ``rep.notes``（missing 清单/路由信号理由——
        ``rep.missing`` 即 fixloop ``missing_file`` 前置情报；装包仍是
        fixloop/tlmgr 职责，此处只播报）。``prefer_engine`` 与
        ``route_project`` 决策不一致时多记一行——只播报不重复决策。
        探针崩溃只记行返回 ``None``，绝不阻塞编译。
        """
        try:
            rep = _w.target_probe(work, ctx.main_rel, deps_index=self._deps_index)
        except Exception as e:  # noqa: BLE001 -- 探针是旁路诊断，崩不拖编译
            self._log(ctx, f"probe crashed: {type(e).__name__}: {e}")
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
        """en.pdf：base/ 拷贝编译；失败只记 warning（不阻塞译文链）。"""
        self._abort_if_cancelled(ctx)
        if self._has_pdf(ctx, "en_pdf"):
            return
        work = ctx.root / "build-en"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.base_dir, work)
        rep = self._probe_target(ctx, work)
        res = self._engine(ctx).compile(
            work,
            ctx.main_rel,
            timeout=self._compile_timeout,
            sandbox=True,
            flags=rep.flags if rep else None,
        )
        # eng.compile 是原子段（无插桩点）——跑完即收敛，后续 diff/登记是白费
        self._abort_if_cancelled(ctx)
        self._probe_diff(ctx, rep, res)
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "en.pdf")
            self._register(ctx, "en_pdf", "en.pdf")
        else:
            self._warning(
                ctx,
                "en_compile",
                f"原文编译未出 pdf（{res.log.first_error or res.stdout_tail[:120]}）",
            )

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
        曾 env 胜 options（相反序），同侧两开关不一致已统一。
        """
        return opt_bool(
            ctx.options(),
            "fixloop",
            lambda: not env_flag(_ENV_NO_FIXLOOP, default=False),
        )

    def _fixloop_engine(self, ctx: TaskCtx, eng: Engine) -> Engine:
        """Fixloop 轮内用引擎：xelatex 独立构造 ``halt_on_error=True``（e2e 权威口径）。

        轮内编译要「首错清晰可分类」——主编译引擎是 best-effort
        nonstopmode（``halt_on_error=False``），续跑日志会让 post-fix
        复判混入下游错误、分类签名漂移，故不复用传入引擎。factory 在场
        尊重注入（测试面）；tectonic 无此旋钮保持原引擎。
        """
        if ctx.engine_name != "xelatex":
            return eng
        if self._engine_factory is not None:
            return self._engine_factory("xelatex")
        return _w.engine_for("xelatex", halt_on_error=True)

    def _run_fixloop(
        self, ctx: TaskCtx, work: Path, eng: Engine, first: CompRes
    ) -> CompRes:
        """Fixloop 救援循环（docs/08 §5）：规则引擎在 ``build-zh`` 内重编到出 pdf/放弃。

        摘要留 ``ctx.fixloop`` 并进 ``task_events``（``fixloop`` 事件可重放）+
        ``fixloop-cases.jsonl`` 沉淀（§5.5）。救回出 pdf 时把改动过的 TeX
        输入层文件回灌 ``zh/`` 并重打 zh-src.zip——让用户拿到的源码树真能
        编译。返回末次 ``CompRes``（fixloop 崩溃/未编译则原样回传）。
        """
        hook, hook_usage, hook_clients = self._llm_hook_pack(ctx)
        try:
            self._abort_if_cancelled(ctx)
            cell, fix_last = run_fixloop(
                work,
                self._fixloop_engine(ctx, eng),
                ruleset=_ruleset_with_baseline(ctx.base_dir),
                engine_name=ctx.engine_name,
                corpus_id=ctx.task_id,
                cond="zh",
                llm_hook=hook,
                case_sink=CaseSink(self.data_dir / "fixloop-cases.jsonl"),
                compile_timeout=self._compile_timeout,
            )
        except Exception as e:  # noqa: BLE001 -- fixloop 崩不拖垮编译段
            self._log(ctx, f"fixloop crashed: {type(e).__name__}: {e}")
            return first
        finally:
            self._teardown_llm_hook(ctx, hook_usage, hook_clients)
        # fixloop 轮间无插桩（repair 属主面外）——出环即收敛
        self._abort_if_cancelled(ctx)
        summary = _fixloop_summary(cell)
        res = fix_last or first
        flags = [str(f) for f in cell.get("engine_flags") or []]
        dropped = [str(f) for f in cell.get("engine_flags_dropped") or []]
        summary["engine_flags"] = flags
        summary["engine_flags_dropped"] = dropped
        adopted_cross = False
        if dropped:
            summary["flags_unapplied"] = True
        # 跨引擎消费 + 审计 note 的共享尾在 repair.consume_engine_flags
        # （e2e _run_fixloop 同臂）——dropped 多为 shell-escape 需求，
        # tectonic 丢的 flag 由 route 候选里的 xelatex 带全量 flag 重编
        # 取优。``route_engines`` 是 _build_base 持久化的生效候选列表——
        # 显式 engine= 覆盖时只剩用户指定那台，臂自熄（尊重显式选型）。
        # status_of 惰性——dropped 路径才需 incumbent 判据，flags-only
        # 不白费一轮 judge。
        xr, note = consume_engine_flags(
            engine_name=ctx.engine_name,
            route_engines=[str(e) for e in ctx.options().get("route_engines") or []],
            status_of=lambda: judge(
                res, expect_cjk=ctx.expect_cjk, log_text=log_text_of(res)
            ).status,
            work=work,
            main_rel=ctx.main_rel,
            timeout=self._compile_timeout,
            probe_flags=ctx.probe_flags,
            flags=flags,
            dropped=dropped,
            expect_cjk=ctx.expect_cjk,
            # halt_on_error=False：与主编译/salvage 同口径 best-effort——
            # retry 是交付路径终末重编（非轮内分类编译），nonstopmode
            # 续跑才能把 incumbent=fail 的树救成 partial（裁决见
            # tmp/b8-e2e/halt-on-error-ruling.md）
            make_engine=lambda: (
                self._engine_factory("xelatex")
                if self._engine_factory is not None
                else _w.engine_for("xelatex", halt_on_error=False)
            ),
        )
        if xr is not None:
            summary["cross_engine"] = xr.info
            if xr.adopted:
                res = xr.res
                adopted_cross = True
        if note is not None:
            self._log(ctx, f"fixloop: {note}")
        ctx.fixloop = _scrub_deep(summary, ctx.secrets.api_key)
        self._on_loop(self.bus.publish, ctx.task_id, "fixloop", ctx.fixloop)
        for ln in cell.get("log") or []:
            self._log(ctx, f"fixloop: {ln}")
        if cell.get("main") and cell["main"] != ctx.main_rel:
            self._log(ctx, f"fixloop: 主文件判定 {cell['main']} ≠ {ctx.main_rel}")
        if cell.get("final_pdf") or adopted_cross:
            n = _sync_fixed_sources(work, ctx.zh_dir)
            if n:
                self._log(ctx, f"fixloop: {n} 个修复文件回灌 zh/，重打 zh-src.zip")
                self._zip_zh(ctx)
        return res

    def _l2_enabled(self, ctx: TaskCtx) -> bool:
        """L2 回灌开关：``options.l2`` 显式优先，缺省读 ``TEXLATE_NO_L2``（默认开）。

        共享译文任务恒关——零 token 是结构承诺（``_share_apply`` 不回退
        自译同理），options/env 无权打开。
        """
        if _share_sourced(ctx):
            return False
        return opt_bool(
            ctx.options(), "l2", lambda: not env_flag(_ENV_NO_L2, default=False)
        )

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
        if not env_flag(_ENV_FIXLOOP_LLM, default=True):
            return None, None, []
        if self._translator_factory is not None:
            # 注入路径：factory 产 translator 直接给 hook（测试桩语义调用方担）
            tr = self._translator_factory(ctx)
            clients = _translator_clients(tr)
            return make_llm_hook(translator=tr), self._meter_usage(clients), clients
        force = env_str("TEXLATE_TRANSLATOR")
        if not ctx.secrets.api_key or force == "mock":
            if opt:
                self._log(ctx, "llm_hook: 无 BYOK api_key——跳过 escalate_llm")
            return None, None, []
        usage, sink = _new_usage_meter()
        model = ctx.secrets.model or "swe-2-medium"
        tr = _PerCallTranslator(ctx.secrets.base_url, ctx.secrets.api_key, model, sink)
        return make_llm_hook(translator=tr, model=model), usage, []

    def _teardown_llm_hook(
        self,
        ctx: TaskCtx,
        usage: dict[str, Any] | None,
        clients: list[ChatClient],
    ) -> None:
        """escalate_llm 旁路收尾：已发调用落账 + factory 路径 client 关闭。"""
        # escalate_llm 烧的是 BYOK token——崩溃/早退也把已发调用落账
        if usage is not None:
            try:
                self._persist_usage(ctx, usage)
            except Exception:
                log.debug("llm_hook usage persist failed", exc_info=True)
        if clients:
            try:
                asyncio.run(_w._aclose_clients(clients))  # noqa: SLF001 -- _w 包 attr 缝
            except Exception:
                log.debug("llm_hook client aclose failed", exc_info=True)

    def _l2_run_state(
        self, ctx: TaskCtx, work: Path
    ) -> tuple[_TreeRun, dict[str, str]]:
        """``repair._TreeRun`` 形态重建：scans 指向 work 内文件 + trans/chunk_ins。

        ``trans`` 取 chunks 表 status='ok' 译文（= work 内已 splice 内容）；
        ``db_of`` 是 ``"fidx:cid"`` → chunks.chunk_id 的 DB 回写映射。
        """
        self._abort_if_cancelled(ctx)
        ok = {
            r["chunk_id"]: r["translation"]
            for r in self._on_loop(self.store.all_chunks, ctx.task_id)
            if r["status"] == "ok" and r["translation"]
        }
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
            glossary=self._make_glossary(
                ctx,
                placeholders=collect_doc_placeholders(
                    ci.content for ci in chunk_ins.values()
                ),
            ),
            validator=lambda s, z: validate_pair(s, z).feedback(),
        )
        # 旁路 pipe 不经 run()——_doc_glossary 恒 {}，L2 重译 prompt 会
        # 丢术语块，须显式物化一次。不挂主链 SegmentCache：带
        # [compile_error] hint 语境的修复译文写同前缀缓存会污染主链段
        # 缓存命名空间（段缓存只认 source+masked 快照，不知 hint）
        pipe._materialize(list(chunk_ins.values()))  # noqa: SLF001 -- 旁路复用文档级物化
        run = _TreeRun(
            scans=[(work / rel, ctx.scans[rel]) for rel in rels],
            trans=trans,
            chunk_ins=chunk_ins,
            pipe=pipe,
        )
        return run, db_of

    def _l2_repair_zh(
        self, ctx: TaskCtx, work: Path, eng: Engine, res: CompRes
    ) -> tuple[dict[str, Any], CompRes, Verdict | None]:
        """L2 回灌一轮：阶梯骨架在 ``repair.l2_repair_round``（e2e ``_l2_repair`` 同件）。

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

        async def _retr(
            run: _TreeRun, hits: dict[str, dict[str, Any]], cap: int
        ) -> dict[str, Any]:
            try:
                return await _retranslate_hits(run, hits, cap)
            finally:
                # client 用/关收进同一 ephemeral loop——拆两次 asyncio.run
                # 会在已关 loop 上 aclose（RuntimeError 吞掉 → FD 泄漏）；
                # 清空清单让外层 finally 不对已关 client 二次 aclose
                await _w._aclose_clients(clients)  # noqa: SLF001 -- _w 包 attr 缝
                clients.clear()

        def _recompile() -> tuple[CompRes, Verdict]:
            r = eng.compile(
                work,
                ctx.main_rel,
                timeout=self._compile_timeout,
                sandbox=True,
                flags=ctx.probe_flags or None,
            )
            # compile 原子段跑完即收敛——judge 前查取消省一轮白费判分
            self._abort_if_cancelled(ctx)
            return r, judge(
                r, expect_cjk=ctx.expect_cjk, log_text=self._log_text_of(r)
            )

        try:
            rep, res2, v2 = l2_repair_round(
                run,
                work,
                ctx.main_rel,
                res,
                L2_MAX_CHUNKS,
                retranslate=lambda r, h, c: asyncio.run(_retr(r, h, c)),
                recompile=_recompile,
                checkpoint=lambda: self._abort_if_cancelled(ctx),
            )
        finally:
            # L2 重译也烧 token——不入账就从 task_usage 里蒸发
            try:
                self._persist_usage(ctx, usage)
            except Exception:
                log.debug("l2 usage persist failed", exc_info=True)
            if clients:
                # 未走到 _retr 的早退（localize 即崩）——未用 client 在新
                # loop 上关是平凡路径；_retr 跑过的已自清清单跳过
                try:
                    asyncio.run(_w._aclose_clients(clients))  # noqa: SLF001 -- _w 包 attr 缝
                except Exception:
                    log.debug("l2 client aclose failed", exc_info=True)
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
        run: _TreeRun,
        db_of: dict[str, str],
        rep: dict[str, Any],
    ) -> None:
        """L2 结果落 chunks 表：retranslated→新译文；reverted/fallback→fallback_orig。"""
        upd: dict[str, dict[str, Any]] = {}
        for cid in rep.get("retranslated") or []:
            fidx, ccid = _split_cid(cid)
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
        self._flush_chunk_updates(ctx, list(upd.items()), cache_puts)

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
            counters = {
                "total": len(st),
                "done": sum(
                    s in ("ok", "fallback_orig", "failed") for s in st.values()
                ),
                "cached": int(row["cached_chunks"]) if row else 0,
                "failed": sum(s in ("fallback_orig", "failed") for s in st.values()),
                "tokens": ctx.tokens_est,
                "progress": int(row["progress"]) if row else 0,
            }
            self.store.flush_chunk_batch(ctx.task_id, applied, cache_puts, counters)

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
                    else _ENV_NO_L2
                ),
            }
            return res, v
        try:
            rep, res2, v2 = self._l2_repair_zh(ctx, work, eng, res)
        except Exception as e:  # noqa: BLE001 -- L2 崩不拖垮编译段
            self._log(ctx, f"l2 crashed: {type(e).__name__}: {e}")
            return res, v
        ctx.l2 = _scrub_deep(rep, ctx.secrets.api_key)
        self._on_loop(self.bus.publish, ctx.task_id, "l2", ctx.l2)
        for key in ("retranslated", "reverted_l0", "fallback_src", "unresolved"):
            if rep.get(key):
                self._log(ctx, f"l2 {key}: {rep[key]}")
        return res2, (v2 if v2 is not None else v)

    def _compile_zh(self, ctx: TaskCtx) -> bool:
        """zh.pdf：zh/ 拷贝编译 +（非 clean 时）L2 回灌 → fixloop + judge(expect_cjk)。

        修复链顺序对齐 e2e ``pipe_condition``：L2（译文归因重译）先于
        fixloop——L2 resplice 重写 workdir，规则修源在其后兜底。
        ``.compile-done`` 哨兵落 ``zh/`` 内：main 变更的 retry 会 rmtree
        ``zh/``，哨兵与 zh_pdf 记录同生共死；resume 见哨兵+pdf 即跳过重编。
        返回「终态不 fault」——有 pdf 即 partial 起步。
        """
        self._abort_if_cancelled(ctx)
        if (ctx.zh_dir / ".compile-done").is_file() and self._has_pdf(ctx, "zh_pdf"):
            return True
        work = ctx.root / "build-zh"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.zh_dir, work)
        eng = self._engine(ctx)
        rep = self._probe_target(ctx, work)
        ctx.probe_flags = [str(f) for f in (rep.flags if rep else [])]
        res = eng.compile(
            work,
            ctx.main_rel,
            timeout=self._compile_timeout,
            sandbox=True,
            flags=rep.flags if rep else None,
        )
        # eng.compile 原子段跑完即收敛——L2/fixloop/登记是后续白费
        self._abort_if_cancelled(ctx)
        self._probe_diff(ctx, rep, res)
        v = judge(res, expect_cjk=ctx.expect_cjk, log_text=self._log_text_of(res))
        if v.status != "clean":
            res, v = self._l2_attempt(ctx, work, eng, res, v)
            self._abort_if_cancelled(ctx)
        if v.status != "clean" and self._fixloop_enabled(ctx):
            res = self._run_fixloop(ctx, work, eng, res)
            v = judge(res, expect_cjk=ctx.expect_cjk, log_text=self._log_text_of(res))
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "zh.pdf")
            self._embed_tounicode(ctx, ctx.root / "zh.pdf")
            self._register(ctx, "zh_pdf", "zh.pdf")
            (ctx.zh_dir / ".compile-done").write_text("", encoding="utf-8")
        (ctx.root / "compile.log").write_text(
            scrub(self._log_text_of(res), ctx.secrets.api_key),
            encoding="utf-8",
        )
        self._register(ctx, "compile_log", "compile.log")
        for r in v.reasons:
            self._log(ctx, f"judge: {r}")
        for n in v.notes:
            self._log(ctx, f"judge note: {n}")
        self._log(ctx, f"verdict: {v.status} cat={v.category} errs={v.n_errors}")
        return v.status in ("clean", "partial") or res.has_pdf

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
            _w.build_alignment(ctx.root / en["path"], ctx.root / zh["path"])
            if en and zh
            else {"kind": "pages"}
        )
        doc["chunks"] = [
            {
                "seq": r["seq"],
                "src_file": r["src_file"],
                "en": r["src_text"],
                # TEXT 列动态类型可落 BLOB——非 str 译文按空 coerce，
                # 不让单格 atomic_json TypeError 挡掉 dual.json 落盘；
                # 非 ok 行（fallback_orig 装的是 en 原文回写）zh 位留空——
                # 原文进 zh 槽会让 share 对账把英文当译文 ok 落库续传
                "zh": r["translation"]
                if r["status"] == "ok" and isinstance(r["translation"], str)
                else "",
                "kind": r["kind"],
            }
            for r in self._on_loop(self.store.all_chunks, ctx.task_id)
        ]
        atomic_json(ctx.root / "dual.json", doc)
        self._register(ctx, "dual_json", "dual.json")

    def _build_md_zip(self, ctx: TaskCtx) -> None:
        """md.zip 降级产物（§5.4）：编译彻底失败但译文在库 → 双语 markdown 包。

        ``view:"html"`` 的登记物——HtmlPane 实读 dual.json ``chunks``，本包
        是同数据的可下载形态（按 ``src_file`` 章节化、seq 锚注释保留 1:1
        对账位）。零译文不产：登记了而 chunks 无料会让前端落 empty 态。
        只在 ``_stage_compile`` 无 pdf 终态分支调用，此处 dual.json 已落。
        """
        self._abort_if_cancelled(ctx)
        rows = self._on_loop(self.store.all_chunks, ctx.task_id)
        # 同 dual.json zh 位口径——非 ok 行（fallback_orig/failed 装 en
        # 原文回写）不算译文载荷，全非 ok 即「零译文不产」
        if not rows or not any(r["status"] == "ok" and r["translation"] for r in rows):
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
                    f"{r['translation'] if r['status'] == 'ok' and isinstance(r['translation'], str) else ''}\n"
                    for r in sorted(by_file[src_file], key=lambda x: int(x["seq"]))
                ]
                zf.writestr(_md_member(src_file, seen), "\n".join(parts))
        self._register(ctx, "md_zip", "md.zip")
        self._log(ctx, f"md.zip: {sum(len(v) for v in by_file.values())} chunks")
