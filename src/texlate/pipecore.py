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
  ``l2_repair``（done 帧同口）；开关决议 ``RepairPolicy``（显式 >
  options > ``TEXLATE_NO_*`` env 缺省皆开）与 ``reject:<rid>`` 判词
  （``reject_verdict``/``precheck_reject``）是 e2e/worker 两臂
  修复链 policy 的单源；整链 ``repair_chain``（precheck→L2→fixloop
  三级直铺）+ 翻前快照 ``baseline_snapshot`` 收 e2e/bench 两臂
  修复段单件。

观测约定：e2e/bench 臂走 ``NULL_SINK`` 零事件面（报告经 rec dict 投影，
与重构前一致）；worker 臂经 ``_Sink`` 绑 ``_log``/``_repair_event``——
同一份实况键集。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from texlate.compile.engine import engine_for
from texlate.compile.judge import Verdict, judge, paired_slot_diff
from texlate.compile.probe import target_probe
from texlate.latex.api import scan_tex_tree
from texlate.latex.reconstruct import (
    MARK_MOVING_UNSAFE_RX,
    reconstruct,
    seq_mark_issues,
    strip_seq_marks,
)
from texlate.repair import (
    ENV_FIXLOOP_LLM,
    ENV_NO_FIXLOOP,
    consume_engine_flags,
    fixloop_cell_parts,
    log_text_of,
    merge_flags,
    ruleset_with_baseline,
    run_fixloop,
    run_precheck,
)
from texlate.repair_l2 import (
    ENV_NO_L2,
    TreeRun,
    env_judge_all,
    l2_repair_round,
    retranslate_hits,
    split_cid,
    unknown_env_of,
)
from texlate.textutil import PH_RX, env_flag, env_str, mask_tex
from texlate.textutil.osutil import ENV_FRONT_MATTER, ENV_NO_SEQ_MARKS
from texlate.validate.l0 import pair_feedback
from texlate.xlat.client import DEFAULT_MODEL
from texlate.xlat.glossary import Glossary
from texlate.xlat.pipeline import (
    MockTranslator,
    PipelineConfig,
    XlatPipeline,
    chunk_to_in,
)
from texlate.xlat.placeholders import collect_doc_placeholders

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping

    from texlate.chunk import ChunkIn
    from texlate.compile.ctan import TlpdbIndex
    from texlate.compile.engine import CompRes, Engine
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.compile.probe import ProbeReport
    from texlate.latex.model import Chunk, ScanResult
    from texlate.repair import CrossRetry
    from texlate.xlat.pipeline import ChunkResult, Translator

log = logging.getLogger(__name__)

__all__ = [
    "DB_TO_PIPE",
    "NULL_SINK",
    "PIPE_TO_DB",
    "CompileRunner",
    "PipeJob",
    "RepairPolicy",
    "ReportSink",
    "baseline_snapshot",
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
    "precheck_reject",
    "probe_report",
    "reject_verdict",
    "repair_chain",
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

#: preamble 前置发射名全集——`options.front_matter`/`TEXLATE_FRONT_MATTER`
#: 的合法键面。
FRONT_MATTER_NAMES = frozenset({"abstract", "title", "author"})

#: ``options.front_matter`` 各键缺省（摘要+标题开、作者关——既定产品默认）。
_FRONT_MATTER_DEFAULT: dict[str, bool] = {
    "abstract": True,
    "title": True,
    "author": False,
}


def default_front_matter() -> frozenset[str]:
    """Env 缺省集：``TEXLATE_FRONT_MATTER`` 逗号清单，未设取 ``_FRONT_MATTER_DEFAULT`` 的开键。"""
    raw = env_str(ENV_FRONT_MATTER)
    if not raw:
        return frozenset(k for k, v in _FRONT_MATTER_DEFAULT.items() if v)
    return frozenset(x.strip() for x in raw.split(",")) & FRONT_MATTER_NAMES


def front_matter_of(options: dict[str, Any]) -> frozenset[str]:
    """``options.front_matter`` dict → frozenset；缺键按 ``_FRONT_MATTER_DEFAULT``。"""
    fm = options.get("front_matter")
    if not isinstance(fm, dict):
        return default_front_matter()
    return frozenset(
        k for k in FRONT_MATTER_NAMES if bool(fm.get(k, _FRONT_MATTER_DEFAULT[k]))
    )


def ran_front_matter(options: Mapping[str, Any]) -> frozenset[str]:
    """任务**实跑**前置集还原：显式 dict → ``front_matter_of``；缺席 → ``frozenset()``。

    与 ``front_matter_of`` 的分工：后者是**提交意图**解析（缺键落产品
    缺省，enqueue/扫描用）；本函数是**事后归因**解析——parse 段把解析
    集显式写回 ``options.front_matter``，故 done/partial 行的缺席即
    pre-feature 产物（前置全盖过的历史形态，实跑 ∅）。share manifest
    与 cache_key 重算据本函数还原实跑集，不给历史行错标缺省。
    """
    if not isinstance(options.get("front_matter"), dict):
        return frozenset()
    return front_matter_of(dict(options))


def scan_tree(
    root: Path, *, front_matter: frozenset[str] = frozenset()
) -> tuple[list[tuple[Path, ScanResult]], list[ChunkIn], list[str], list[str]]:
    """枚举树内 ``.tex`` → 四级分流 → 解析 + chunk 收集。

    扫描段单源 ``latex.api.scan_tex_tree``（文件名闸 ``.rtx.tex`` 运行时
    转储静默跳过、``.code.tex`` tikzlibrary 机制件记 support → 解析崩
    分两叉（解析闸内判定）：``OSError(EINVAL)``（tar 伪装 ``.tex``，tar
    闸在 ``parse_file`` 内）静默跳过——不进任何名单、逐字节保留；其余
    解析崩记 ``fault_files``（单文件崩不拖垮整树，原文保留）→ 无散文
    记 ``support_files``——pstricks/epsf/宏件/gnuplot 转储送译即腐蚀，
    按原文保留；与 fault 分流：有意跳过而非失败）。本壳只把 ``parsed``
    桶折成 ``(scans, chunks)``——chunk_id ``{idx}:{c.id}`` 方案归本臂。
    ``front_matter`` = preamble 前置发射白名单（透传 ``scan_tex_tree``）。
    """
    tree = scan_tex_tree(root, front_matter=front_matter)
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
    model = str(getattr(translator, "model", "") or DEFAULT_MODEL)
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


def translate_tree_run(  # noqa: PLR0913 -- 注入面穿透（scan/validator/sink 各臂缝）
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
    front_matter: frozenset[str] = frozenset(),
    sink: ReportSink = NULL_SINK,
    seq_marks: bool | None = None,
) -> tuple[dict[str, Any], TreeRun, list[ChunkResult]]:
    """目录树翻译 + splice 写回 → ``(stats, TreeRun, 逐块 results)``。

    ``env_judge=True`` 时对静态表外的未知 env 块问 LLM 可译性——
    False 的块回落原文不进 splice。``auto_glossary=True`` 时开逐篇
    LLM 术语抽取臂（仅对带 ``client`` 的真网关 translator 生效）。
    ``scan_fn`` 缺省走本模块 ``scan_tree`` 全局（patch 点随件迁）；
    ``validator`` 缺省 L0 ``validate_pair`` 全量规则——e2e/bench 显式
    透传自家模块全局，保 ``e2e.validate_pair`` 等 monkeypatch 缝。
    ``front_matter`` = preamble 前置发射白名单（缺省 scan 臂生效）。
    ``sink`` 收 ``translate`` 实况帧：scan 后 ``start``（载 total/files，
    CLI 靠它建进度条——裸 ``on_result`` 拿不到总量）、逐块 ``chunk``
    （done/total/status/chunk_id）、splice 后 ``done``（载 stats）。
    ``seq_marks`` 三态：None → ``TEXLATE_NO_SEQ_MARKS`` env 决议（缺省开）
    ——splice 时 ``[[CHUNK_n]]`` 按 seq（scans 序累计）注 marked-content
    锚，失衡文件剥锚降级。
    """
    scan = (
        (lambda r: scan_tree(r, front_matter=front_matter))
        if scan_fn is None
        else scan_fn
    )
    scans, chunks, fault_files, support_files = scan(root)
    total = len(chunks)
    sink.event(
        "translate",
        {"phase": "start", "total": total, "files": len(scans)},
    )
    _n_done = 0

    def _on_result(r: ChunkResult) -> None:
        nonlocal _n_done
        _n_done += 1
        sink.event(
            "translate",
            {
                "phase": "chunk",
                "done": _n_done,
                "total": total,
                "status": r.status,
                "chunk_id": r.chunk_id,
            },
        )

    pipe = XlatPipeline(
        translator or MockTranslator(),
        config=PipelineConfig(
            auto_glossary_fn=_auto_glossary_fn(translator) if auto_glossary else None
        ),
        glossary=Glossary.load(
            placeholders=collect_doc_placeholders(c.content for c in chunks)
        ),
        validator=validator or pair_feedback,
        cache={},
        on_result=_on_result,
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
    marks_on = _opt_switch(None, "seq_marks", ENV_NO_SEQ_MARKS, explicit=seq_marks)
    moving_ok = marks_on and not MARK_MOVING_UNSAFE_RX.search(
        "\n".join(mask_tex(res.vtex) for _, res in scans)
    )
    seq0 = 0
    for idx, (f, res) in enumerate(scans):
        cur0 = seq0
        seq0 += len(res.chunks)  # 无条件累计——跳译文件 seq 仍占位
        trans = by_file.get(idx)
        if not trans:
            continue
        zh = reconstruct(
            res,
            trans,
            mark_seq0=cur0 if marks_on else None,
            mark_moving=moving_ok,
        )
        if marks_on and (issues := seq_mark_issues(zh)):
            log.warning(
                "seq marks imbalanced in %s (%s); stripped", f, "; ".join(issues)
            )
            zh = strip_seq_marks(zh)
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
    sink.event("translate", {"phase": "done", "stats": stats})
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


# ------------------------------------------------------------ 修复链 policy


def _opt_switch(
    options: Mapping[str, Any] | None,
    key: str,
    env_name: str,
    *,
    explicit: bool | None,
) -> bool:
    """修复链单开关决议：``explicit`` > ``options[key]`` > ``not env_flag``。

    ``options`` 值容忍 bool 与 ``"0"/"false"/"no"/"off"`` 字符串 false 系
    ——worker ``opt_bool`` 同口径；``TEXLATE_NO_*`` env 是「关」语义，
    取反喂入故缺省皆开。e2e 只喂 explicit、worker 只喂 options——两臂
    各自的两级闸是同一条优先级链上的不同入口，在此收口。
    """
    if explicit is not None:
        return explicit
    if options is not None:
        v = options.get(key)
        if v is not None:
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() not in ("0", "false", "no", "off")
    return not env_flag(env_name, default=False)


@dataclass(frozen=True)
class RepairPolicy:
    """修复链开关决议快照——precheck/L2/fixloop 三级链闸的 policy 单源。

    e2e ``_repair_chain``（``fixloop_on``/``l2_on`` 显式闸）与 worker
    ``_compile_zh``（``options.*`` 闸）此前各复写同一条「显式 > options >
    ``TEXLATE_NO_*``（缺省皆开）」优先级链；``resolve`` 收成一处。
    precheck 闸随 ``fixloop``；``l2`` 另吃 ``precheck_reject`` 拒门与
    worker 侧 share 零 token 硬闸（臂内保留，不进本对象）。
    """

    fixloop: bool
    l2: bool

    @classmethod
    def resolve(
        cls,
        options: Mapping[str, Any] | None = None,
        *,
        fixloop_on: bool | None = None,
        l2_on: bool | None = None,
    ) -> RepairPolicy:
        """双闸同链决议：``*_on`` 显式 > ``options[键]`` > env 缺省开。"""
        return cls(
            fixloop=_opt_switch(
                options, "fixloop", ENV_NO_FIXLOOP, explicit=fixloop_on
            ),
            l2=_opt_switch(options, "l2", ENV_NO_L2, explicit=l2_on),
        )


def reject_verdict(verdict: object) -> bool:
    """``reject:<rid>`` verdict 判——precheck/fixloop 报告与终态合成同口径。"""
    return str(verdict or "").startswith("reject:")


def precheck_reject(rep: Mapping[str, Any] | None) -> bool:
    """``precheck`` 报告的 ``reject:<rid>`` 判（报告缺席按非拒）。"""
    return reject_verdict((rep or {}).get("verdict"))


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
    baseline_sigs: set[str] | None = None,
    seq_marks: bool | None = None,
) -> tuple[dict[str, Any], CompRes, Verdict | None]:
    """L2 回灌一轮 + done 实况帧（``sink.event`` 平铺统计键 + report 全量）。

    阶梯骨架在 ``repair_l2.l2_repair_round``；本层只做注入类型化
    （``recompile`` 归 ``CompileRunner`` 协议）与实况出口——done 帧
    平铺键 ``enabled/errors/retranslated/fallback`` 前端卡片直读，
    ``report`` 载全量 rep（worker 侧经 ``_repair_event`` scrub）。
    ``baseline_sigs`` 透传 ``l2_repair_round``——en 基线签名命中判源生
    不进归因面。``seq_marks`` 同路透传（None → env 决议）。返回
    (l2 报告, 最新 CompRes, 新 Verdict 或 None=未重编)。
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
        baseline_sigs=baseline_sigs,
        seq_marks=seq_marks,
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


def l2_repair_job(  # noqa: PLR0913 -- 注入面穿透（编译件/上限/sink 同契）
    job: PipeJob,
    run: TreeRun,
    res: CompRes,
    cap: int,
    *,
    engine_fn: Callable[..., Engine] | None = None,
    sink: ReportSink = NULL_SINK,
) -> tuple[dict, CompRes, dict | None]:
    """L2 回灌一轮（e2e 口径）→ (l2 报告, 最新 CompRes, 新尾段或 None)——原 e2e ``_l2_repair``。

    注入 e2e 编译件（``_compile_judge_job``，``engine_fn`` 保
    ``e2e.engine_for`` monkeypatch 缝）并把末态 Verdict 换回 tail dict
    报告形。``sink`` 透传 ``l2_repair``——CLI 臂收 done 实况帧。
    错误契约与 ``precheck_job``/``fixloop_job`` 同件：崩不传播，
    落 ``({'enabled': True, 'error': ...}, 入参 res, None)``——
    修复臂崩不毁主报告，调用方不必再包 try。
    """
    try:
        rep, last_res, v = l2_repair(
            run,
            job.work,
            job.main_rel,
            res,
            cap,
            retranslate=lambda r, h, c: asyncio.run(retranslate_hits(r, h, c)),
            recompile=lambda: _compile_judge_job(
                job, expect_cjk=True, engine_fn=engine_fn
            ),
            sink=sink,
        )
    except Exception as e:  # noqa: BLE001 -- 修复臂崩不毁主报告
        return ({"enabled": True, "error": f"{type(e).__name__}: {e}"}, res, None)
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
            sink=sink,
        )
    except Exception as e:  # noqa: BLE001 -- 修复臂崩不毁主报告
        return ({"enabled": True, "error": f"{type(e).__name__}: {e}"}, None, prev_res)
    rep = _slim_cell(cell)
    last_res = fix_last or prev_res
    cell_verdict = str(cell.get("verdict") or "")
    if reject_verdict(cell_verdict):
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


# ---------------------------------------------------------------- 修复链编排


def baseline_snapshot(
    work: Path, *, enabled: bool
) -> tempfile.TemporaryDirectory | None:
    """翻前快照 → fixloop ``baseline_dir``（normalize 后/翻译前的 pristine 树）。

    e2e ``_baseline_snapshot``/worker ``ctx.base_dir`` 同位——原地翻译臂
    无常驻 base，``restore_support_from_src``/``slot_arg_revert`` 要它
    逐字节复原被写脏的 support 件。快照落系统 tempdir 防污染
    ``scan_tree``/编译枚举；``enabled=False``（fixloop 关）跳过省一次
    全树 copytree；copytree 失败降级 ``None``（修复臂旁路件，不该砸死
    主链）。

    返回的 ``TemporaryDirectory`` 是生命周期令牌——快照根在
    ``Path(td.name)/"base"``；调用方持有到修复链收敛（局部变量持到
    函数返回即随帧清理，也可 ``td.cleanup()`` 显式收）。
    """
    if not enabled:
        return None
    td = tempfile.TemporaryDirectory(prefix="texlate-baseline-")
    base = Path(td.name) / "base"
    try:
        shutil.copytree(work, base)
    except (OSError, shutil.Error) as e:
        log.warning("baseline snapshot failed (%s) → fixloop 无 baseline", e)
        return None
    return td


def repair_chain(  # noqa: PLR0913 -- 修复链开关面穿透 + 三级阶梯直铺
    rec: dict,
    job: PipeJob,
    run: TreeRun,
    res: CompRes,
    *,
    expect_cjk: bool,
    l2_on: bool | None,
    fixloop_on: bool | None,
    l2_max_chunks: int,
    route_engines: list[str] | None,
    baseline_dir: Path | None = None,
    engine_fn: Callable[..., Engine] | None = None,
    sink: ReportSink = NULL_SINK,
) -> CompRes:
    """非 clean 后的修复链：precheck 预检 → L2 回灌 → fixloop；reports 直写 ``rec``。

    顺序是设计约束：precheck（装缺件，fixloop 第 0 招独立相）先消
    missing_file 类基建失败——它们进 L2 归因面只会把块拖去重译/回退
    （``t_f74894ebc691aaf4`` algpseudocodex 实证）；L2 回灌先于
    fixloop——fixloop 的 regex_rewrite 会被 L2 resplice 冲掉。
    三个 ``*_job`` 件各自吞崩成 error dict——修复臂崩不毁主报告。
    fixloop 只在仍非 clean 时跑。返回最新 ``CompRes`` 供 ToUnicode
    注入判产物。``engine_fn`` 缺省本模块 ``engine_for`` 全局——
    e2e 显式透传自家全局名保 ``e2e.engine_for`` monkeypatch 缝
    （conftest RecordingEngine）。
    """
    policy = RepairPolicy.resolve(fixloop_on=fixloop_on, l2_on=l2_on)
    fl, l2 = policy.fixloop, policy.l2

    # —— 第 0 招: precheck 预检 (装缺件/解嵌套 tar/收割构建 flag) ——
    # precheck 相全是增量件不碰 .tex 源——对 resplice 安全。装上缺件或
    # 收割到 engine_flags 才重编 (空转省一发编译)；clean 即收工。
    # reject:<rid> 不重编不跑 L2——路由拒绝交 fixloop 复现 + 跨引擎消费。
    pre_reject = False
    if fl:
        sink.event("stage", {"stage": "precheck"})
        pre = precheck_job(job, engine_fn=engine_fn)
        rec["precheck"] = pre
        pre_reject = precheck_reject(pre)
        pre_flags = [str(f) for f in pre.get("engine_flags") or []]
        if not pre_reject and (pre.get("installed") or pre_flags):
            tail0, res = compile_judge_tail(
                job,
                expect_cjk=expect_cjk,
                flags=pre_flags or None,
                engine_fn=engine_fn,
            )
            rec.update(tail0)
            if rec["status"] == "clean":
                return res

    if l2 and not pre_reject:
        sink.event("stage", {"stage": "l2"})
        l2_rep, res, tail2 = l2_repair_job(
            job, run, res, l2_max_chunks, engine_fn=engine_fn, sink=sink
        )
        rec["l2"] = l2_rep
        if tail2 is not None:
            rec.update(tail2)
    elif not l2:
        rec["l2"] = {"enabled": False, "reason": ENV_NO_L2}
    else:
        rec["l2"] = {"enabled": False, "reason": "precheck_reject"}

    if rec["status"] != "clean" and fl:
        sink.event("stage", {"stage": "fixloop"})
        fl_rep, tail3, res = fixloop_job(
            job,
            route_engines or [job.eng_name],
            res,
            timeout=job.timeout,
            expect_cjk=expect_cjk,
            baseline_dir=baseline_dir,
            engine_fn=engine_fn,
            sink=sink,
        )
        rec["fixloop"] = fl_rep
        if tail3 is not None:
            rec.update(tail3)
    elif rec["status"] != "clean":
        rec["fixloop"] = {"enabled": False, "reason": ENV_NO_FIXLOOP}
    return res
