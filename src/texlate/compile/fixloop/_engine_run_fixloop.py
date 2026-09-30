r"""engine._engine_run._engine_run_fixloop — ``fixloop`` 入口装配面 (二级拆叶)。

``fixloop`` = 装配面 + 主档解析 + ``_FixRun`` 驱相机;
``_record_case`` cases 沉淀缝。``inject.classify_no_main`` 经本叶回引
(``engine.X`` 兼容面)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.compile.fixloop._engine_disp import (
    _gate_fired_of,
    _precheck_phase,
    find_main_tex,
)
from texlate.compile.fixloop._engine_run import _FixRun
from texlate.compile.fixloop._engine_wire import _setup_ctx, _wire_engine
from texlate.compile.inject import classify_no_main as _classify_no_main

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import Any

    from texlate.compile.fixloop._engine_proto import Engine, LlmHook, RunFn
    from texlate.compile.fixloop.cases import CaseSink
    from texlate.compile.fixloop.ruleset import Ruleset

__all__ = [
    "_classify_no_main",
    "_record_case",
    "fixloop",
]


def fixloop(  # noqa: PLR0913 -- 注入面穿透
    proj: Path | str,
    eng: Engine,
    *,
    ruleset: Ruleset | None = None,
    engine_name: str | None = None,
    main_rel: str | None = None,
    corpus_id: str | None = None,
    cond: str | None = None,
    llm_hook: LlmHook | None = None,
    runner: RunFn | None = None,
    case_sink: CaseSink | None = None,
    compile_timeout: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """跑一格修复循环 → cell dict (字段与原型 fixloop-results.json 兼容)。

    verdict ∈ clean / acceptable_pdf / dirty_pdf / best_effort_pdf /
    unfixable:<cat> / stuck / max_rounds / reject:<rid> /
    no_errors_no_pdf / no_main_tex[:<sub>]（``classify_no_main`` 细分）

    装配面：setup (ruleset/引擎名/cfg/ctx/cell) → 主档解析与 no_main 早退
    → ``_FixRun`` 相机 (_floor_snapshot → precheck 早退 → rounds 主循环
    → tail 尾段)。相内状态机分支各归其方法，经验调谐注释逐块随迁。

    ``main_rel`` 缺省时 ``find_main_tex`` 双档推导；调用方持有正确主档
    时显式传入（译后 splice 树的语种重排会让 ``language_rank`` 把
    CJK 主档输给 standalone 英文档——ds209diag #191 实证 4 格误选）。
    指定档缺件/指树外则回退自动探测，落 ``cell["main_fallback"]`` 留痕；
    ``cell["main"]`` 恒记实效主档。

    ``on_round`` 可选逐轮回调：每轮 ``cell["rounds"]`` 落新 entry 即同步
    调用（含 salvage 兜底轮），entry 与 cell 内同对象——server worker
    借此发 SSE 实况帧；None 时零开销，e2e/bench 直调臂行为不变。
    """
    rs, engine_name, wdir, ctx = _setup_ctx(
        proj,
        eng,
        ruleset=ruleset,
        engine_name=engine_name,
        runner=runner,
        llm_hook=llm_hook,
    )
    cfg = rs.loop_cfg
    max_rounds = int(cfg.get("max_rounds", 8))
    clean_err_max = int(cfg.get("clean_err_max", 3))
    passes = int(cfg.get("compile_passes", 2))
    stuck_n = int(cfg.get("stuck_sig_repeat", 3))
    # 重编超时：参数 > meta.loop.timeout_sec > 引擎缺省 (None = 不透传)
    if compile_timeout is not None:
        timeout = float(compile_timeout)
    elif cfg.get("timeout_sec") is not None:
        timeout = float(cfg["timeout_sec"])
    else:
        timeout = None
    compile_kw: dict[str, Any] = {}
    if timeout is not None:
        compile_kw["timeout"] = timeout

    cell: dict[str, Any] = {
        "project": corpus_id or wdir.name,
        "cond": cond,
        "main": None,
        "engine": engine_name,
        "rounds": [],
        "actions": [],
        "verdict": None,
        # reject 决策名单：gate/loop 相 REJECT 不经 actions 列 (precheck 相
        # append 在先判 REJECT 在后，双栖) —— 单列物化，不混 rules_fired
        # 的修复语义，verdict ``reject:<rid>`` 的结构化面。
        "gate_fired": [],
        "floor_restored": False,
        # 调用方指定主档缺件/树外时的回退留痕——None = 无回退发生
        "main_fallback": None,
    }
    main: Path | None = None
    if main_rel is not None:
        cand = wdir / main_rel
        # 树外引用 (绝对路径/.. 逃逸) 与缺件同档处理——主档必须在工程树内
        if cand.is_file() and cand.resolve().is_relative_to(wdir.resolve()):
            main = cand
        else:
            cell["main_fallback"] = main_rel
            ctx.ledger.advisories.append(
                f"main_rel {main_rel} not in tree; fell back to find_main_tex"
            )
    if main is None:
        main = find_main_tex(wdir)
    if main is None:
        sub = _classify_no_main(wdir)
        cell["verdict"] = f"no_main_tex:{sub}" if sub else "no_main_tex"
        _record_case(
            case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
        )
        return cell
    ctx.io.main_rel = str(main.relative_to(wdir))
    cell["main"] = ctx.io.main_rel
    cell["actions"] = ctx.ledger.actions  # 同一 list: precheck/gate/loop 动作汇入一处
    _wire_engine(eng, rs, wdir, ctx)

    run = _FixRun(
        rs=rs,
        eng=eng,
        ctx=ctx,
        cell=cell,
        compile_kw=compile_kw,
        max_rounds=max_rounds,
        clean_err_max=clean_err_max,
        passes=passes,
        stuck_n=stuck_n,
        should_cancel=should_cancel,
        on_round=on_round,
    )
    run._floor_snapshot()  # noqa: SLF001 -- 装配臂驱相内方法

    # —— precheck phase (第 0 招; 静态路由也在这里) ——
    p_verdict, p_route = _precheck_phase(rs, ctx, eng)
    if p_verdict is not None:
        cell["verdict"] = p_verdict
        cell["gate_fired"] = _gate_fired_of(cell)
        if p_route:
            cell["reject_route"] = p_route
        _record_case(
            case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
        )
        return cell

    run.rounds()
    run.tail()
    _record_case(
        case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
    )
    return cell


def _record_case(
    sink: CaseSink | None,
    cell: dict[str, Any],
    *,
    corpus_id: str | None,
    cond: str | None,
    engine_name: str,
) -> None:
    """沉淀 cases.jsonl (docs/spec/compile.md); sink 缺省即不写。"""
    if sink is None:
        return
    sink.record(cell, corpus_id=corpus_id, cond=cond, engine=engine_name)
