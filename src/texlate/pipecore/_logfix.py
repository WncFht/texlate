"""``texlate.pipecore._logfix`` — logfix 回灌执行件叶（``pipecore`` 拆分叶）。

``logfix``：阶梯骨架 ``repair.logfix_round`` 的注入类型化壳
（``recompile`` 归 ``CompileRunner`` 协议）+ done 实况帧出口；
``logfix_job``：e2e 口径 job 形包装——注入 e2e 编译件并把末态
Verdict 换回 tail dict 报告形，崩不传播落 error dict。

门面回引名单见 ``texlate.pipecore._LEAF_EXPORTS``。
monkeypatch 锚点：setattr patch 须指本叶，指门面无效。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from texlate.pipecore.state import NULL_SINK
from texlate.pipecore.tail import _compile_judge_job, tail_dict
from texlate.repair import logfix_round, retranslate_hits

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from texlate.compile.engine import CompRes
    from texlate.compile.judge import Verdict
    from texlate.pipecore.state import CompileRunner, ReportSink
    from texlate.pipecore.tail import PipeJob
    from texlate.repair import TreeRun


def logfix(  # noqa: PLR0913 -- 阶梯钩子面穿透（与 logfix_round 同契）
    run: TreeRun,
    work: Path,
    main_rel: str,
    res: CompRes,
    cap: int,
    *,
    retranslate: Callable[[TreeRun, dict[str, dict[str, Any]], int], dict[str, Any]],
    recompile: CompileRunner,
    checkpoint: Callable[[], None] | None = None,
    sink: ReportSink = NULL_SINK,
    baseline_sigs: set[str] | None = None,
    seq_marks: bool | None = None,
) -> tuple[dict[str, Any], CompRes, Verdict | None]:
    """Logfix 回灌一轮 + done 实况帧（``sink.event`` 平铺统计键 + report 全量）。

    阶梯骨架在 ``repair.logfix_round``；本层只做注入类型化
    （``recompile`` 归 ``CompileRunner`` 协议）与实况出口——done 帧
    平铺键 ``enabled/errors/retranslated/fallback`` 前端卡片直读，
    ``report`` 载全量 rep（worker 侧经 ``_repair_event`` scrub）。
    ``baseline_sigs`` 透传 ``logfix_round``——en 基线签名命中判源生
    不进归因面。``seq_marks`` 同路透传（None → env 决议）。返回
    (logfix 报告，最新 CompRes, 新 Verdict 或 None=未重编)。
    """
    rep, last_res, v = logfix_round(
        run,
        work,
        main_rel,
        res,
        cap,
        retranslate=retranslate,
        recompile=recompile,
        checkpoint=checkpoint,
        baseline_sigs=baseline_sigs,
        seq_marks=seq_marks,
    )
    sink.event(
        "logfix",
        {
            "phase": "done",
            "enabled": rep.get("enabled"),
            "errors": rep.get("errors"),
            "retranslated": len(rep.get("retranslated") or []),
            "fallback": len(rep.get("fallback_src") or []),
            "report": rep,
        },
    )
    return rep, last_res, v


def logfix_job(
    job: PipeJob,
    run: TreeRun,
    res: CompRes,
    cap: int,
) -> tuple[dict, CompRes, dict | None]:
    """Logfix 回灌一轮（e2e 口径）→ (logfix 报告，最新 CompRes, 新尾段或 None)——原 e2e ``_logfix``。

    注入 e2e 编译件（``_compile_judge_job``——``PipeJob.engine_fn`` 保
    ``e2e.engine_for`` monkeypatch 缝）并把末态 Verdict 换回 tail dict
    报告形。重译走 ``run.drive``——翻译期 loop 复用（``TreeRun.loop``
    令牌，client 池不跨 loop）。``job.sink`` 透传 ``logfix``——
    CLI 臂收 done 实况帧。错误契约与 ``precheck_job``/``fixloop_job``
    同件：崩不传播，落 ``({'enabled': True, 'error': ...}, 入参 res,
    None)``——修复臂崩不毁主报告，调用方不必再包 try。
    """
    try:
        rep, last_res, v = logfix(
            run,
            job.work,
            job.main_rel,
            res,
            cap,
            retranslate=lambda r, h, c: run.drive(retranslate_hits(r, h, c)),
            recompile=lambda: _compile_judge_job(job, expect_cjk=True),
            sink=job.sink,
        )
    except Exception as e:  # noqa: BLE001 -- 修复臂崩不毁主报告
        return ({"enabled": True, "error": f"{type(e).__name__}: {e}"}, res, None)
    tail = tail_dict(last_res, v) if v is not None else None
    return rep, last_res, tail
