"""worker.compile_fixloop — fixloop/precheck/llm_hook 救援链叶 (worker.compile 域缝叶)。

规则引擎救援（``_run_fixloop`` zh 臂 / ``_fixloop_en`` en 臂 / 共享核
``_fixloop_pass``）、第 0 招预检（``_precheck_attempt``）、``escalate_llm``
BYOK 旁路接线（``_llm_hook_pack``/``_teardown_llm_hook``）与 cell →
压缩摘要归并件 ``_fixloop_summary``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop import CaseSink
from texlate.compile.fixloop.llm_hook import make_llm_hook
from texlate.pipecore import (
    PipeJob,
    RepairPolicy,
    compile_judge,
    fixloop_flags_tail,
    fixloop_round,
    judge_res,
    precheck_job,
    reject_verdict,
)
from texlate.repair import (
    ENV_FIXLOOP_LLM,
    fixloop_cell_parts,
    merge_flags,
)
from texlate.textutil import env_flag
from texlate.textutil.osutil import translator_mode
from texlate.xlat.client import DEFAULT_MODEL

from ._common import (
    _new_usage_meter,
    _scrub_deep,
    _Sink,
    _translator_clients,
)
from .compile_splice import _sync_fixed_sources
from .share import (
    _share_sourced,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from texlate.compile.engine import (
        CompRes,
        Engine,
    )
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.compile.judge import Verdict
    from texlate.xlat.client import ChatClient

    from ._common import TaskCtx


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


class _CompileFixloop:
    """fixloop/precheck 救援链 mixin：规则引擎循环 + LLM 旁路接线。"""

    def _fixloop_enabled(self, ctx: TaskCtx) -> bool:
        """Fixloop 开关：``options.fixloop`` 显式 > ``TEXLATE_NO_FIXLOOP``（默认开）。

        与 ``_l2_enabled``/``_env_judge_enabled``/e2e 同序——显式参数优先；
        曾 env 胜 options（相反序），同侧两开关不一致已统一。决议本体在
        ``pipecore.RepairPolicy``（e2e/worker policy 单源）。
        """
        return RepairPolicy.resolve(ctx.options()).fixloop

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
            # 续跑才能把 incumbent=fail 的树救成 partial。
            make_engine=lambda: self._new_engine(ctx, "xelatex", halt_on_error=False),
            should_cancel=ctx.cancel_flag.is_set,
        )
        adopted_cross = False
        if xr is not None and xr.adopted:
            res = xr.res
            adopted_cross = True
        if note is not None:
            self._log(ctx, f"fixloop: {note}")
        return res, summary, bool(cell.get("final_pdf")) or adopted_cross

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
        force = translator_mode()
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
