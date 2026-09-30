"""worker.compile_engine — 引擎接线 + 依赖探针 + 实况帧 plumbing 叶 (worker.compile 域缝叶)。

引擎构造单点族（``_task_texmf``/``_new_engine``/``_engine``/``_fixloop_engine``）、
编译前后依赖探针播报与差分对拍（``_probe_target``/``_probe_diff``）、修复链
实况帧发布（``_repair_event``）与 ``texlog.log_text_of`` 委托——编译段
各臂共享的基建件，策略决策不归此叶。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from texlate.compile.probe import (
    dep_seen,
    deps_diff,
)
from texlate.pipecore import (
    probe_report,
)
from texlate.server.worker import seams
from texlate.texlog import log_text_of

from ._common import (
    _PROBE_LIST_CAP,
    _PROBE_SEEN_TAG,
    _scrub_deep,
)

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.engine import (
        CompRes,
        Engine,
    )
    from texlate.compile.probe import ProbeReport

    from ._common import TaskCtx

log = logging.getLogger(__name__)


class _CompileEngine:
    """编译基建 mixin：引擎构造/任务 texmf 树/探针播报/修复实况帧。"""

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

    def _log_text_of(self, res: CompRes) -> str:
        """``texlog.log_text_of`` 单源委托（.log 非空优先、stdout_tail 兜底）。"""
        return log_text_of(res)
