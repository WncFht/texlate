"""``texlate._pipecore_fixloop`` — fixloop 执行件叶（``pipecore`` 拆分叶）。

``fixloop_round``：``run_fixloop`` + baseline ruleset 注入 + round/done/
log 三实况出口；``fixloop_flags_tail``：``engine_flags``/``reject_route``
消费尾（报告键回填 + 跨引擎重试）；``fixloop_job``：e2e 口径 job 形
包装（报告 + 新尾段 + 最新 CompRes），崩不传播落 error dict。

门面回引名单见 ``texlate.pipecore._LEAF_EXPORTS``。
monkeypatch 锚点：setattr patch 须指本叶，指门面无效——
``engine_fn`` 缺省读本叶 ``engine_for`` 全局。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from texlate._pipecore_policy import reject_verdict
from texlate._pipecore_state import NULL_SINK
from texlate._pipecore_tail import _texmf_eng, judge_res, tail_dict
from texlate.compile.engine import engine_for
from texlate.compile.judge import Verdict
from texlate.repair import (
    ENV_FIXLOOP_LLM,
    consume_engine_flags,
    fixloop_cell_parts,
    ruleset_with_baseline,
    run_fixloop,
)
from texlate.textutil import env_flag

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from texlate._pipecore_state import ReportSink
    from texlate._pipecore_tail import PipeJob
    from texlate.compile.engine import CompRes, Engine
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.repair import CrossRetry


def _slim_cell(cell: dict[str, Any]) -> dict[str, Any]:
    """Fixloop cell → e2e 报告视图（归并机械在 ``repair.fixloop_cell_parts``）。"""
    rounds, setup = fixloop_cell_parts(cell)
    return {
        "enabled": True,
        "verdict": cell.get("verdict"),
        "main": cell.get("main"),
        "rounds": rounds,
        "setup": setup,
        "advisories": cell.get("advisories") or [],
        "installed": cell.get("installed") or [],
        "engine_flags": cell.get("engine_flags") or [],
        "engine_flags_dropped": cell.get("engine_flags_dropped") or [],
        "reject_route": cell.get("reject_route"),
        "gate_fired": cell.get("gate_fired") or [],
        "log_excerpt": cell.get("log_excerpt"),
    }


def fixloop_round(  # noqa: PLR0913 -- 开关面穿透两臂同一契约
    work: Path,
    eng: Engine,
    *,
    engine_name: str,
    baseline_dir: Path | None = None,
    main_rel: str | None = None,
    llm_hook: LlmHook | None = None,
    compile_timeout: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
    sink: ReportSink = NULL_SINK,
    **run_kw: Any,  # noqa: ANN401 -- fixloop 开关面透传，键集由 fixloop 签名定
) -> tuple[dict[str, Any], CompRes | None]:
    """``run_fixloop`` + baseline ruleset 注入 + 实况出口 → ``(cell, 末次 CompRes|None)``。

    ``baseline_dir`` 在场时 ``ruleset_with_baseline`` 注入
    （``restore_support_from_src`` 的 pristine 源——worker ``ctx.base_dir``/
    e2e/bench ``baseline_snapshot`` 同位），缺席走默认 ruleset（restore
    fail-safe 空转）。实况出口经 ``sink``：round 帧（``on_round`` 未显式
    给时默认安装）、done 帧载全量 cell、cell ``log`` 行、主文件判定与
    ``main_rel`` 分歧行——e2e 臂 ``NULL_SINK`` 下全静默（与重构前一致）。
    """
    run_kw.setdefault(
        "on_round", lambda r: sink.event("fixloop", {"phase": "round", "round": r})
    )
    cell, fix_last = run_fixloop(
        work,
        eng,
        ruleset=(
            ruleset_with_baseline(baseline_dir) if baseline_dir is not None else None
        ),
        engine_name=engine_name,
        main_rel=main_rel,
        llm_hook=llm_hook,
        compile_timeout=compile_timeout,
        should_cancel=should_cancel,
        **run_kw,
    )
    # done 帧带完整引擎 cell（rounds/actions/verdict 全量，实况回放原料）
    sink.event("fixloop", {"phase": "done", "cell": cell})
    for ln in cell.get("log") or []:
        sink.log(f"fixloop: {ln}")
    if main_rel is not None and cell.get("main") and cell["main"] != main_rel:
        sink.log(f"fixloop: 主文件判定 {cell['main']} ≠ {main_rel}")
    return cell, fix_last


def fixloop_flags_tail(  # noqa: PLR0913 -- 开关面穿透两臂同一契约
    rep: dict[str, Any],
    cell: dict[str, Any],
    *,
    engine_name: str,
    route_engines: Iterable[str],
    status_of: Callable[[], str],
    work: Path,
    main_rel: str,
    timeout: float | None,
    probe_flags: Iterable[str],
    expect_cjk: bool,
    make_engine: Callable[[], Engine],
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[CrossRetry | None, str | None]:
    """``engine_flags``/``reject_route`` 消费尾：报告键回填 + 跨引擎重试。

    ``rep`` 原地补 ``engine_flags``/``engine_flags_dropped``（str 化——
    worker 口径，e2e 原样 str 亦恒等）/``flags_unapplied``/
    ``cross_engine``；``(xr, note)`` 返回后 adopted 换 tail/res 与
    note 落点两臂各自处理（e2e 贴 ``tail["verdict"]["notes"]``，
    worker 记 ``fixloop:`` 日志行）。dropped 多为 shell-escape 需求——
    tectonic 丢的 flag 由 xelatex 带 ``probe_flags``+``flags`` 合并
    去重后的全量请求重编取优（机械在 ``consume_engine_flags``）。
    """
    flags = [str(f) for f in cell.get("engine_flags") or []]
    dropped = [str(f) for f in cell.get("engine_flags_dropped") or []]
    rep["engine_flags"] = flags
    rep["engine_flags_dropped"] = dropped
    if dropped:
        rep["flags_unapplied"] = True
    xr, note = consume_engine_flags(
        engine_name=engine_name,
        route_engines=route_engines,
        status_of=status_of,
        work=work,
        main_rel=main_rel,
        timeout=timeout,
        probe_flags=probe_flags,
        flags=flags,
        dropped=dropped,
        reject_route=cell.get("reject_route"),
        expect_cjk=expect_cjk,
        make_engine=make_engine,
        should_cancel=should_cancel,
    )
    if xr is not None:
        rep["cross_engine"] = xr.info
    return xr, note


def fixloop_job(  # noqa: PLR0913 -- 开关面穿透同 pipe_condition
    job: PipeJob,
    route_engines: list[str],
    prev_res: CompRes,
    *,
    timeout: float | None = None,
    llm_hook: LlmHook | None = None,
    expect_cjk: bool = True,
    baseline_dir: Path | None = None,
    engine_fn: Callable[..., Engine] | None = None,
    sink: ReportSink = NULL_SINK,
) -> tuple[dict, dict | None, CompRes]:
    """跑 fixloop + 消费 engine_flags → (报告，新尾段或 None, 最新 CompRes)——原 e2e ``_run_fixloop``。

    引擎新造不带 e2e 的 best-effort 旋钮——xelatex 默认 halt_on_error=True
    （fixloop 首错分类语义）。flags 经 ``compile(flags=…)`` seam 落 CLI：
    xelatex 追加 argv；tectonic 只放支持子集，dropped 项（多为
    shell-escape 需求）→ 记 advisory + 换 xelatex 重编取优。

    ``timeout`` 覆盖 rules/ ``meta.loop.timeout_sec`` 的重编预算
    （None=用 yaml 值）。``llm_hook`` 未传时 ``TEXLATE_FIXLOOP_LLM=1``
    可经 env 启用 escalate_llm 钩（网关走 TEXLATE_* 三件套）。
    ``engine_fn`` 缺省本模块 ``engine_for`` 全局——e2e 显式透传自家
    全局名保 ``e2e.engine_for`` monkeypatch 缝（conftest RecordingEngine）。
    """
    eng_fn = engine_for if engine_fn is None else engine_fn
    if llm_hook is None and env_flag(ENV_FIXLOOP_LLM, default=False):
        from texlate.compile.fixloop.llm_hook import make_llm_hook  # noqa: PLC0415

        llm_hook = make_llm_hook()
    try:
        cell, fix_last = fixloop_round(
            job.work,
            eng_fn(job.eng_name),
            engine_name=job.eng_name,
            baseline_dir=baseline_dir,
            main_rel=job.main_rel,
            llm_hook=llm_hook,
            compile_timeout=timeout,
            sink=sink,
        )
    except Exception as e:  # noqa: BLE001 -- 修复臂崩不毁主报告
        return ({"enabled": True, "error": f"{type(e).__name__}: {e}"}, None, prev_res)
    rep = _slim_cell(cell)
    last_res = fix_last or prev_res
    cell_verdict = str(cell.get("verdict") or "")
    if reject_verdict(cell_verdict):
        # reject:<rid> = 策略拒绝 (走降级链) → 终态合成 partial, 理由串
        # 保留 reject 令牌供下游分流审计 (docs/spec/compile.md 判词口径)。
        tail = tail_dict(last_res, Verdict(status="partial", reasons=[cell_verdict]))
        tail["reject_at"] = "fixloop"
    else:
        tail = tail_dict(last_res, judge_res(last_res, expect_cjk=expect_cjk))

    xr, note = fixloop_flags_tail(
        rep,
        cell,
        engine_name=job.eng_name,
        route_engines=route_engines,
        status_of=lambda: tail["status"],
        work=job.work,
        main_rel=job.main_rel,
        timeout=job.timeout,
        probe_flags=job.probe_flags,
        expect_cjk=expect_cjk,
        make_engine=lambda: _texmf_eng(
            eng_fn, "xelatex", job.work, halt_on_error=False
        ),
    )
    if xr is not None and xr.adopted:
        tail, last_res = tail_dict(xr.res, xr.verdict), xr.res
    # 注在换编之后——贴到最终采用的 tail 上，换臂不丢审计痕迹
    if note is not None:
        tail["verdict"]["notes"].append(note)
    return rep, tail, last_res
