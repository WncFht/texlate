"""``texlate.pipecore.tail`` — 编译尾段叶（``pipecore`` 拆分叶）。

``PipeJob`` 单工程编译上下文 + ``probe_report`` best-effort 探针壳 +
``judge_res``/``compile_judge`` 编译判定单点对 + ``tail_dict`` 报告
尾段 + ``_texmf_*`` 任务树 ``_texmf`` 装件接线 + ``_compile_judge_job``/
``compile_judge_tail`` job 形编译尾 + ``precheck_job`` 第 0 招静态
预检壳。

门面回引名单见 ``texlate.pipecore._LEAF_EXPORTS``。
monkeypatch 锚点：setattr patch 须指本叶，指门面无效——
``PipeJob.engine_fn=None`` 时读本叶 ``engine_for`` 全局、``probe_fn``
缺省读本叶 ``target_probe`` 全局。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from texlate.compile.engine import engine_for
from texlate.compile.judge import judge
from texlate.compile.probe import target_probe
from texlate.pipecore.state import NULL_SINK
from texlate.repair import merge_flags, run_precheck
from texlate.texlog import log_text_of

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from pathlib import Path

    from texlate.compile.ctan import TlpdbIndex
    from texlate.compile.engine import CompRes, Engine
    from texlate.compile.judge import Verdict
    from texlate.compile.probe import ProbeReport
    from texlate.pipecore.state import ReportSink


@dataclass(frozen=True)
class PipeJob:
    """单工程编译上下文——work/main/引擎/超时 + 旗标/路由/基线/注入缝全程同捆（原 e2e ``_Job``）。

    收编原 ``repair_chain``/``*_job`` 散参穿透：``engine_fn=None`` → 各
    消费叶读本叶 ``engine_for`` 全局（monkeypatch 缝——e2e 在构造时
    透传自家 ``e2e.engine_for`` 全局名）；``route_engines=None`` →
    消费点按 ``[eng_name]`` 收窄；``baseline_dir`` = 翻前 pristine 快照
    根（fixloop ``ruleset_with_baseline`` 注入件）；``sink`` 缺省
    ``NULL_SINK`` 零事件面。
    """

    work: Path
    main_rel: str
    eng_name: str
    timeout: float
    probe_flags: tuple[str, ...] = ()
    route_engines: Iterable[str] | None = None
    baseline_dir: Path | None = None
    engine_fn: Callable[..., Engine] | None = None
    sink: ReportSink = NULL_SINK


def probe_report(
    work: Path,
    main_rel: str,
    *,
    deps_index: TlpdbIndex | None = None,
    probe_fn: Callable[..., ProbeReport] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> ProbeReport | None:
    """``target_probe`` best-effort 壳：崩只 ``on_error`` 回报 + ``None``，不阻塞编译。

    ``probe_fn`` 缺省本模块 ``target_probe`` 全局——worker 显式传
    ``seams.target_probe`` 保测试缝；e2e 走默认（无缝，同重构前）。
    """
    fn = target_probe if probe_fn is None else probe_fn
    try:
        return fn(work, main_rel, deps_index)
    except Exception as e:  # noqa: BLE001 -- 探针是旁路诊断
        if on_error is not None:
            on_error(e)
        return None


def judge_res(res: CompRes, *, expect_cjk: bool) -> Verdict:
    """``judge`` + ``log_text_of`` 配对——两臂全部判定点同一 log 文本口径。"""
    return judge(res, expect_cjk=expect_cjk, log_text=log_text_of(res))


def compile_judge(  # noqa: PLR0913 -- 编译开关面穿透（worker should_cancel/after_compile 同位）
    eng: Engine,
    work: Path,
    main_rel: str,
    *,
    timeout: float | None,
    flags: list[str] | None = None,
    expect_cjk: bool,
    should_cancel: Callable[[], bool] | None = None,
    after_compile: Callable[[CompRes], None] | None = None,
) -> tuple[CompRes, Verdict]:
    """``eng.compile`` → ``after_compile`` 插桩 → ``judge_res``：编译 + 判定单点对。

    ``after_compile`` 落在 compile 与 judge 之间——worker 的
    ``_abort_if_cancelled``/``_probe_diff`` 原位插桩（compile 原子段
    跑完即收敛，judge 前的取消/差分不白费）；e2e 臂无插桩点走 None。
    """
    res = eng.compile(
        work,
        main_rel,
        timeout=timeout,
        sandbox=True,
        flags=flags,
        should_cancel=should_cancel,
    )
    if after_compile is not None:
        after_compile(res)
    return res, judge_res(res, expect_cjk=expect_cjk)


def tail_dict(res: CompRes, v: Verdict) -> dict:
    """CompRes + Verdict → 报告尾段（compile/verdict/status 三键）。"""
    return {
        "compile": {
            "ok": res.ok,
            "timed_out": res.timed_out,
            "seconds": round(res.seconds, 2),
            "passes": res.passes,
            "rc": res.rc,
            "killed_signal": res.killed_signal,
            "pdf_bytes": res.pdf_bytes,
            "first_error": res.log.first_error,
        },
        "verdict": {
            "status": v.status,
            "reasons": v.reasons,
            "notes": v.notes,
            "n_errors": v.n_errors,
            "category": v.category,
            "payload": v.payload,
            "error_cats": v.error_cats,
            "error_pay": v.error_pay,
            "cjk_chars": v.cjk_chars,
            "dead_chars": v.dead_chars,
            "missing_chars": v.missing_chars,
            "warnings_hit": v.warnings_hit,
        },
        "status": v.status,
    }


def _texmf_wire(eng: Engine, wdir: Path) -> None:
    """任务树 ``_texmf`` 装件对一次性引擎可见。

    fixloop ``_wire_engine`` 的 texmfhome 接线只盖它手里那台引擎——
    编译尾段/跨引擎重试每发新造的引擎 texmfhome=None，看不见 precheck/
    fixloop 装进 ``wdir/_texmf`` 的缺件（装了个寂寞）。同款 None-only
    语义：调用方预设即接管落点，不覆写显式接线。
    """
    if getattr(eng, "texmfhome", "unset") is None:
        eng.texmfhome = wdir / "_texmf"  # type: ignore[attr-defined]


def _texmf_eng(
    eng_fn: Callable[..., Engine],
    name: str,
    wdir: Path,
    **kw: Any,  # noqa: ANN401 -- 引擎构造旋钮透传，键集由引擎定
) -> Engine:
    """``eng_fn(name, **kw)`` + ``_texmf_wire``——make_engine 工厂位。"""
    eng = eng_fn(name, **kw)
    _texmf_wire(eng, wdir)
    return eng


def _compile_judge_job(
    job: PipeJob,
    *,
    expect_cjk: bool,
    flags: list[str] | None = None,
) -> tuple[CompRes, Verdict]:
    """e2e 口径 job 编译：xelatex ``halt_on_error=False`` best-effort + probe/extra flags 合并。"""
    eng_fn = engine_for if job.engine_fn is None else job.engine_fn
    kw: dict[str, object] = (
        {"halt_on_error": False} if job.eng_name == "xelatex" else {}
    )
    eng = _texmf_eng(eng_fn, job.eng_name, job.work, **kw)
    return compile_judge(
        eng,
        job.work,
        job.main_rel,
        timeout=job.timeout,
        flags=merge_flags(job.probe_flags, flags),
        expect_cjk=expect_cjk,
    )


def compile_judge_tail(
    job: PipeJob,
    *,
    expect_cjk: bool,
    flags: list[str] | None = None,
) -> tuple[dict, CompRes]:
    """编译 + 判定公共尾段 → (报告 dict, CompRes)——原 e2e ``_compile_judge``。

    best-effort 语义：xelatex halt_on_error=False 对齐 bench；
    tectonic 无此旋钮——恒 ``-Z continue-on-errors``。``flags`` 透传
    fixloop engine_flags（跨引擎臂用——tectonic 丢的 flag 由 xelatex 接）。
    """
    res, v = _compile_judge_job(job, expect_cjk=expect_cjk, flags=flags)
    return tail_dict(res, v), res


def precheck_job(job: PipeJob) -> dict[str, Any]:
    """L2/编译链前的静态预检（第 0 招）→ 摘要 dict。

    fixloop precheck 相独立跑一轮：``scan_install`` 装缺件 /
    ``tar_blob_extract`` 解嵌套 tar / ``build_directive_harvest`` 收割
    构建 flag——全是增量件不碰 .tex 源，对 L2 resplice 安全。缺包类
    失败在 L2 归因前就消掉（``t_f74894ebc691aaf4`` algpseudocodex
    实证：missing_file 进 L2 兜底只会把块拖去重译/回退）。
    ``reject:<rid>`` verdict 原样上报——路由拒绝交 fixloop 主循环
    复现 + ``fixloop_flags_tail`` 跨引擎消费。引擎不带编译旋钮——
    precheck 相无编译。
    """
    eng_fn = engine_for if job.engine_fn is None else job.engine_fn
    try:
        pre = run_precheck(
            job.work,
            eng_fn(job.eng_name),
            engine_name=job.eng_name,
            main_rel=job.main_rel,
        )
    except Exception as e:  # noqa: BLE001 -- 预检崩不毁主报告
        return {"enabled": True, "error": f"{type(e).__name__}: {e}"}
    return {
        "enabled": True,
        "verdict": pre.get("verdict"),
        "reject_route": pre.get("reject_route"),
        "gate_fired": pre.get("gate_fired") or [],
        "installed": pre.get("installed") or [],
        "engine_flags": pre.get("engine_flags") or [],
        "engine_flags_dropped": pre.get("flags_dropped") or [],
        "advisories": pre.get("advisories") or [],
        "actions": pre.get("actions") or [],
    }
