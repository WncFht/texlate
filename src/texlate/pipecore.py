r"""管线核心契约层——e2e / worker / bench 三臂共享的 policy 脊。

``repair.py``/``repair_l2.py`` 已把修复机械单源化（``run_fixloop``/
``consume_engine_flags``/``l2_repair_round``/``embed_tounicode_quiet``…）；
本层收编两臂仍各自复写的**策略脊**，让 4× 接线的管线契约只剩一个事实源：

- 状态空间：pipe 空间（``ok/partial/skipped/fault``）↔ DB 空间
  （``ok/fallback_orig/failed``）映射 + 两空间的 delivered 谓词；
- 扫描/翻译脊：``scan_tree`` 四级分流 + ``translate_tree_run`` 全树翻译
  写回——``scan_fn``/``validator``/``engine_fn``/``probe_fn`` 注入面保住
  各臂模块全局 monkeypatch 缝（e2e 别名绑定、worker ``seams.*`` 直传）；
- 编译尾段：``probe_report``/``compile_judge``/``judge_res``/``tail_dict``
  + job 形 ``compile_judge_tail``/``l2_repair_job``/``fixloop_job``；
- 修复链编排：``fixloop_round``（轮实况经 ``ReportSink`` 出口）+
  ``fixloop_flags_tail``（engine_flags/reject_route 消费尾）+
  ``l2_repair``（done 帧同口）。

观测约定：e2e/bench 臂走 ``NULL_SINK`` 零事件面（报告经 rec dict 投影，
与重构前一致）；worker 臂经 ``_Sink`` 绑 ``_log``/``_repair_event``——
同一份实况键集。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from texlate.compile.engine import engine_for
from texlate.compile.judge import Verdict, judge, paired_slot_diff
from texlate.compile.probe import target_probe
from texlate.latex.api import scan_tex_tree
from texlate.latex.reconstruct import reconstruct
from texlate.repair import (
    ENV_FIXLOOP_LLM,
    consume_engine_flags,
    fixloop_cell_parts,
    log_text_of,
    ruleset_with_baseline,
    run_fixloop,
    run_precheck,
)
from texlate.repair_l2 import (
    TreeRun,
    env_judge_all,
    l2_repair_round,
    retranslate_hits,
    split_cid,
    unknown_env_of,
)
from texlate.textutil import PH_RX, env_flag
from texlate.validate.l0 import validate_pair
from texlate.xlat.glossary import Glossary
from texlate.xlat.pipeline import (
    MockTranslator,
    PipelineConfig,
    XlatPipeline,
    chunk_to_in,
)
from texlate.xlat.placeholders import collect_doc_placeholders

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable
    from pathlib import Path

    from texlate.chunk import ChunkIn
    from texlate.compile.engine import CompRes, Engine
    from texlate.compile.fixloop.ctan import TlpdbIndex
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.compile.probe import ProbeReport
    from texlate.latex.model import Chunk, ScanResult
    from texlate.repair import CrossRetry
    from texlate.xlat.pipeline import ChunkResult, Translator

__all__ = [
    "DB_TO_PIPE",
    "NULL_SINK",
    "PIPE_TO_DB",
    "CompileRunner",
    "PipeJob",
    "ReportSink",
    "compile_judge",
    "compile_judge_tail",
    "delivered",
    "delivered_db",
    "fixloop_flags_tail",
    "fixloop_job",
    "fixloop_round",
    "judge_res",
    "l2_repair",
    "l2_repair_job",
    "precheck_job",
    "probe_report",
    "scan_tree",
    "tail_dict",
    "translate_tree_run",
]

# ---------------------------------------------------------------- 状态空间

#: pipeline ``ChunkResult.status`` → chunks.status（原 worker ``_PIPE_TO_DB``）
PIPE_TO_DB = {
    "ok": "ok",
    "partial": "ok",
    "skipped": "fallback_orig",
    "fault": "failed",
}

#: chunks.status → pipeline 语义（resume ``DBStateBridge.load`` 反查）
DB_TO_PIPE = {"ok": "ok", "fallback_orig": "skipped", "failed": "fault"}


def delivered(r: ChunkResult) -> bool:
    """该 chunk 的译文会进 splice——与产品臂同口径。

    ``PIPE_TO_DB`` 把 pipeline ``partial``（阶梯 recovered）归 ``ok`` 照常
    splice；``e2e_real_bench`` 同此。译文必须非空——worker ``_build_zh``
    要求 ``status=="ok" and r["translation"]``，ok+"" 进 splice 会把块内容
    从 zh 树静默擦除，应与失败块同回落原文。skipped/fault 的
    ``translation`` 是原文回填，不判。
    """
    return r.status in ("ok", "partial") and bool(r.translation)


def delivered_db(status: object, translation: object) -> bool:
    """DB 空间 delivered 谓词：chunks 行 ``status=="ok"`` 且译文非空。

    worker ``_build_zh``/``_l2_run_state``/``_build_md_zip`` 三处同款——
    恰是 pipe 空间 ``delivered`` 经 ``PIPE_TO_DB`` 投影后的判定式
    （``partial`` 落库即 ``ok``）。``translation`` 只判真值——需要
    ``isinstance(str)`` 的消费点（dual.json zh 槽）另行自判。
    """
    return status == "ok" and bool(translation)


# ---------------------------------------------------------------- 注入协议


class CompileRunner(Protocol):
    """``() -> (CompRes, Verdict)``——编译+判定回环件（``l2_repair`` 的 ``recompile`` 契约）。"""

    def __call__(self) -> tuple[CompRes, Verdict]:
        """跑一次编译+判定回环 → ``(CompRes, Verdict)``。"""
        ...


class ReportSink(Protocol):
    """修复链实况/日志出口——worker 绑 ``_log``/``_repair_event``；e2e/bench 挂 ``NULL_SINK``。"""

    def log(self, msg: str) -> None:
        """一行修复日志（worker → 任务日志行；NULL → 静默）。"""
        ...

    def event(self, etype: str, payload: dict[str, Any]) -> None:
        """一帧修复实况（worker → ``bus.publish``；NULL → 静默）。"""
        ...


class _NullSink:
    """``ReportSink`` 空实现——e2e/bench 的报告走 rec dict 投影，零事件面。"""

    def log(self, msg: str) -> None:
        """静默吞行。"""

    def event(self, etype: str, payload: dict[str, Any]) -> None:
        """静默吞帧。"""


#: e2e/bench 臂默认 sink——修复实况无处投递即静默（与重构前行为一致）
NULL_SINK: ReportSink = _NullSink()


# ---------------------------------------------------------------- 扫描/翻译脊


def scan_tree(
    root: Path,
) -> tuple[list[tuple[Path, ScanResult]], list[ChunkIn], list[str], list[str]]:
    """枚举树内 ``.tex`` → 四级分流 → 解析 + chunk 收集。

    扫描段单源 ``latex.api.scan_tex_tree``（文件名闸 ``.rtx.tex`` 运行时
    转储静默跳过、``.code.tex`` tikzlibrary 机制件记 support → 解析崩
    记 ``fault_files`` → 无散文记 ``support_files``——pstricks/epsf/
    宏件/gnuplot 转储送译即腐蚀，按原文保留；与 fault 分流：有意跳过
    而非失败）。本壳只把 ``parsed`` 桶折成 ``(scans, chunks)``——
    chunk_id ``{idx}:{c.id}`` 方案归本臂。
    """
    tree = scan_tex_tree(root)
    scans: list[tuple[Path, ScanResult]] = []
    chunks: list[ChunkIn] = []
    for f, _rel, res in tree.parsed:
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(
            chunk_to_in(c, chunk_id=f"{idx}:{c.id}", ph_map=res.ph_map)
            for c in res.chunks
        )
    return scans, chunks, [rel for rel, _exc in tree.fault], tree.support


def _auto_glossary_fn(
    translator: Translator | None,
) -> Callable[[list[str]], Awaitable[dict[str, str]]] | None:
    """为带 ``client`` 的 translator（GatewayTranslator）接 ``autogloss.extract_terms``。

    MockTranslator/无 client 注入件 → ``None``（mock/bench 路径不打网关）。
    抽取臂沿用翻译同模（BYOK 端点模型名网关私有，硬编公网名会 404）。
    备忘防 ``pipe.run`` 二次调用重抽。
    """
    client = getattr(translator, "client", None)
    if client is None:
        return None
    model = str(getattr(translator, "model", "") or "swe-2-medium")
    memo: dict[str, dict[str, str]] = {}

    async def _fn(texts: list[str]) -> dict[str, str]:
        from texlate.xlat.autogloss import (  # noqa: PLC0415 -- 可选件惰载
            extract_terms,
        )

        if "terms" not in memo:
            memo["terms"] = await extract_terms(texts, client, model=model)
        return memo["terms"]

    return _fn


def _env_judge_pass(
    pipe: XlatPipeline,
    scans: list[tuple[Path, ScanResult]],
    results: list[ChunkResult],
    by_file: dict[int, dict[int, str]],
) -> dict[str, Any]:
    """未知 env 块 → LLM 可译性判定；判 False 的块从 ``by_file`` 摘除（回落原文）。"""
    targets: list[tuple[str, Chunk, str]] = []
    for r in results:
        if not delivered(r):
            continue
        fidx, cid = split_cid(r.chunk_id)
        chunk = scans[fidx][1].chunks[cid]
        env_name = unknown_env_of(chunk)
        if env_name is not None:
            targets.append((r.chunk_id, chunk, env_name))
    verdicts = asyncio.run(env_judge_all(pipe, targets))
    reverted = sorted(cid for cid, keep in verdicts.items() if not keep)
    for cid in reverted:
        fidx, ccid = split_cid(cid)
        by_file.get(fidx, {}).pop(ccid, None)
    return {"enabled": True, "asked": len(targets), "reverted": reverted}


def translate_tree_run(  # noqa: PLR0913 -- 注入面穿透（scan/validator 各臂缝）
    root: Path,
    *,
    translator: Translator | None = None,
    env_judge: bool = False,
    auto_glossary: bool = False,
    scan_fn: Callable[
        [Path],
        tuple[list[tuple[Path, ScanResult]], list[ChunkIn], list[str], list[str]],
    ]
    | None = None,
    validator: Callable[[str, str], str] | None = None,
) -> tuple[dict[str, Any], TreeRun, list[ChunkResult]]:
    """目录树翻译 + splice 写回 → ``(stats, TreeRun, 逐块 results)``。

    ``env_judge=True`` 时对静态表外的未知 env 块问 LLM 可译性——
    False 的块回落原文不进 splice。``auto_glossary=True`` 时开逐篇
    LLM 术语抽取臂（仅对带 ``client`` 的真网关 translator 生效）。
    ``scan_fn`` 缺省走本模块 ``scan_tree`` 全局（patch 点随件迁）；
    ``validator`` 缺省 L0 ``validate_pair`` 全量规则——e2e/bench 显式
    透传自家模块全局，保 ``e2e.validate_pair`` 等 monkeypatch 缝。
    """
    scan = scan_tree if scan_fn is None else scan_fn
    scans, chunks, fault_files, support_files = scan(root)

    pipe = XlatPipeline(
        translator or MockTranslator(),
        config=PipelineConfig(
            auto_glossary_fn=_auto_glossary_fn(translator) if auto_glossary else None
        ),
        glossary=Glossary.load(
            placeholders=collect_doc_placeholders(c.content for c in chunks)
        ),
        validator=validator or (lambda s, z: validate_pair(s, z).feedback()),
        cache={},
    )
    results = asyncio.run(pipe.run(chunks))
    by_file: dict[int, dict[int, str]] = {}
    n_fault = 0
    n_partial = 0
    for r in results:
        fidx, cid = split_cid(r.chunk_id)
        if delivered(r):
            by_file.setdefault(fidx, {})[cid] = r.translation
            if r.status == "partial":
                n_partial += 1
        else:
            n_fault += 1

    env_stats: dict[str, Any] = (
        _env_judge_pass(pipe, scans, results, by_file)
        if env_judge
        else {"enabled": False}
    )

    n_files = 0
    n_leftover = 0
    slot_diffs: dict[str, list[str]] = {}
    for idx, (f, res) in enumerate(scans):
        trans = by_file.get(idx)
        if not trans:
            continue
        zh = reconstruct(res, trans)
        f.write_text(zh, encoding="utf-8")
        rel = f.relative_to(root).as_posix()
        if notes := paired_slot_diff(res.vtex, zh, rel):
            slot_diffs[rel] = notes
        n_files += 1
        n_leftover += len(PH_RX.findall(zh))
    stats = {
        "files": n_files,
        "chunks": len(chunks),
        "partial_chunks": n_partial,
        "fault_chunks": n_fault,
        "fault_files": fault_files,
        "support_files": support_files,
        "support_skipped": len(support_files),
        "leftover_ph": n_leftover,
        "env_judge": env_stats,
        "slot_diffs": slot_diffs,
    }
    run = TreeRun(
        scans=scans,
        trans=by_file,
        chunk_ins={c.chunk_id: c for c in chunks},
        pipe=pipe,
    )
    return stats, run, results


# ---------------------------------------------------------------- 编译尾段


@dataclass(frozen=True)
class PipeJob:
    """单工程编译上下文——work/main/引擎/超时 + 声明侧旗标全程同捆（原 e2e ``_Job``）。"""

    work: Path
    main_rel: str
    eng_name: str
    timeout: float
    probe_flags: tuple[str, ...] = ()


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
    """``eng.compile`` → ``after_compile`` 插桩 → ``judge_res``：编译+判定单点对。

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
    engine_fn: Callable[..., Engine] | None = None,
) -> tuple[CompRes, Verdict]:
    """e2e 口径 job 编译：xelatex ``halt_on_error=False`` best-effort + probe/extra flags 合并。"""
    eng_fn = engine_for if engine_fn is None else engine_fn
    kw: dict[str, object] = (
        {"halt_on_error": False} if job.eng_name == "xelatex" else {}
    )
    eng = eng_fn(job.eng_name, **kw)
    _texmf_wire(eng, job.work)
    res = eng.compile(
        job.work,
        job.main_rel,
        timeout=job.timeout,
        sandbox=True,
        flags=list(dict.fromkeys([*job.probe_flags, *(flags or [])])) or None,
    )
    return res, judge_res(res, expect_cjk=expect_cjk)


def compile_judge_tail(
    job: PipeJob,
    *,
    expect_cjk: bool,
    flags: list[str] | None = None,
    engine_fn: Callable[..., Engine] | None = None,
) -> tuple[dict, CompRes]:
    """编译 + 判定公共尾段 → (报告 dict, CompRes)——原 e2e ``_compile_judge``。

    best-effort 语义：xelatex halt_on_error=False 对齐 bench；
    tectonic 无此旋钮——恒 ``-Z continue-on-errors``。``flags`` 透传
    fixloop engine_flags（跨引擎臂用——tectonic 丢的 flag 由 xelatex 接）。
    """
    res, v = _compile_judge_job(
        job, expect_cjk=expect_cjk, flags=flags, engine_fn=engine_fn
    )
    return tail_dict(res, v), res


def precheck_job(
    job: PipeJob,
    *,
    engine_fn: Callable[..., Engine] | None = None,
) -> dict[str, Any]:
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
    eng_fn = engine_for if engine_fn is None else engine_fn
    try:
        pre = run_precheck(job.work, eng_fn(job.eng_name), engine_name=job.eng_name)
    except Exception as e:  # noqa: BLE001 -- 预检崩不毁主报告
        return {"enabled": True, "error": f"{type(e).__name__}: {e}"}
    return {
        "enabled": True,
        "verdict": pre.get("verdict"),
        "reject_route": pre.get("reject_route"),
        "installed": pre.get("installed") or [],
        "engine_flags": pre.get("engine_flags") or [],
        "engine_flags_dropped": pre.get("flags_dropped") or [],
        "advisories": pre.get("advisories") or [],
        "actions": pre.get("actions") or [],
    }


# ---------------------------------------------------------------- L2 回灌


def l2_repair(  # noqa: PLR0913 -- 阶梯钩子面穿透（与 l2_repair_round 同契）
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
) -> tuple[dict[str, Any], CompRes, Verdict | None]:
    """L2 回灌一轮 + done 实况帧（``sink.event`` 平铺统计键 + report 全量）。

    阶梯骨架在 ``repair_l2.l2_repair_round``；本层只做注入类型化
    （``recompile`` 归 ``CompileRunner`` 协议）与实况出口——done 帧
    平铺键 ``enabled/errors/retranslated/fallback`` 前端卡片直读，
    ``report`` 载全量 rep（worker 侧经 ``_repair_event`` scrub）。
    返回 (l2 报告, 最新 CompRes, 新 Verdict 或 None=未重编)。
    """
    rep, last_res, v = l2_repair_round(
        run,
        work,
        main_rel,
        res,
        cap,
        retranslate=retranslate,
        recompile=recompile,
        checkpoint=checkpoint,
    )
    sink.event(
        "l2",
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


def l2_repair_job(
    job: PipeJob,
    run: TreeRun,
    res: CompRes,
    cap: int,
    *,
    engine_fn: Callable[..., Engine] | None = None,
) -> tuple[dict, CompRes, dict | None]:
    """L2 回灌一轮（e2e 口径）→ (l2 报告, 最新 CompRes, 新尾段或 None)——原 e2e ``_l2_repair``。

    注入 e2e 编译件（``_compile_judge_job``，``engine_fn`` 保
    ``e2e.engine_for`` monkeypatch 缝）并把末态 Verdict 换回 tail dict
    报告形。
    """
    rep, last_res, v = l2_repair(
        run,
        job.work,
        job.main_rel,
        res,
        cap,
        retranslate=lambda r, h, c: asyncio.run(retranslate_hits(r, h, c)),
        recompile=lambda: _compile_judge_job(job, expect_cjk=True, engine_fn=engine_fn),
    )
    tail = tail_dict(last_res, v) if v is not None else None
    return rep, last_res, tail


# ---------------------------------------------------------------- fixloop


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
    e2e ``_baseline_snapshot`` 同位），缺席走默认 ruleset（restore
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
) -> tuple[dict, dict | None, CompRes]:
    """跑 fixloop + 消费 engine_flags → (报告, 新尾段或 None, 最新 CompRes)——原 e2e ``_run_fixloop``。

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
        )
    except Exception as e:  # noqa: BLE001 -- 修复臂崩不毁主报告
        return ({"enabled": True, "error": f"{type(e).__name__}: {e}"}, None, prev_res)
    rep = _slim_cell(cell)
    last_res = fix_last or prev_res
    cell_verdict = str(cell.get("verdict") or "")
    if cell_verdict.startswith("reject:"):
        # reject:<rid> = 策略拒绝 (走降级链) → 终态合成 partial, 理由串
        # 保留 reject 令牌供下游分流审计 (docs/08:185, spec §9 F3)。
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
