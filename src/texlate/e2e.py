"""mock E2E 驱动（docs/10 B5 Mode A 的产品化扶正）。

全链走产品 API：``route_project → normalize_project → XlatPipeline(MockTranslator)
+ L0 校验 → splice 写回 → prepare_chinese → engine.compile → judge``。
bench harness（e2e_mock_bench）与 CLI ``texlate run`` 共用同一实现——
评测条件矩阵在 bench 侧，单工程驱动在这里。

编译失败后的两级修复（docs/08 §2.3/§5 接线）：

1. **L2 回灌**（先跑）——log 解析把错误定位到 chunk（file:line: 或文件栈
   归因），只重译被点名的块（每块限 1 次、per-doc 有上限），resplice 后
   重编一次；仍被点名且本轮重译过的块回落原文（"再不过 → fallback 原文"）。
   先修自家译文伤——fixloop 的 regex_rewrite 会直接改盘上文件，若先跑
   fixloop 再 resplice 会把它的修复冲掉。
2. **fixloop**（后跑）——yaml 规则引擎修源/基建类问题（缺包、preamble、
   字体……）。``TEXLATE_NO_FIXLOOP=1`` 关闭（测试/对照臂）；轮数上限沿用
   rules.yaml ``meta.loop.max_rounds``。产出 ``engine_flags`` 在此消费：
   当前引擎没法直接吃 CLI 旗标（引擎 seam 未开），先落 advisory + 触发
   跨引擎换编（tectonic 上收到 flag → 换 xelatex 再编，取更优 verdict）。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.cjkmap import embed_cjk_mappings
from texlate.compile.engine import engine_for, route_project
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.judge import Verdict, judge
from texlate.compile.normalize import normalize_project
from texlate.compile.probe import target_probe
from texlate.latex.api import parse_file
from texlate.latex.placeholder import PH_RX
from texlate.latex.prose import file_has_prose
from texlate.latex.reconstruct import reconstruct
from texlate.repair import (
    _ENV_ENV_JUDGE,
    _ENV_NO_L2,
    _KNOWN_ENVS,
    L2_MAX_CHUNKS,
    _env_judge_all,
    _l2_localize,
    _resplice,
    _retranslate_hits,
    _ruleset_with_baseline,
    _split_cid,
    _TreeRun,
    cross_engine_retry,
    fixloop_cell_parts,
    log_text_of,
    run_fixloop,
)
from texlate.textutil import env_flag
from texlate.validate.l0 import validate_pair
from texlate.xlat.glossary import Glossary
from texlate.xlat.pipeline import (
    ChunkIn,
    MockTranslator,
    XlatPipeline,
    chunk_to_in,
)
from texlate.xlat.placeholders import collect_doc_placeholders

if TYPE_CHECKING:
    from collections.abc import Iterator

    from texlate.compile.engine import CompRes
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.latex.model import Chunk, ScanResult
    from texlate.xlat.pipeline import ChunkResult, Translator

log = logging.getLogger(__name__)

#: 环境开关
_ENV_NO_FIXLOOP = "TEXLATE_NO_FIXLOOP"


# ---------------------------------------------------------------- 翻译树


def _delivered(r: ChunkResult) -> bool:
    """该 chunk 的译文会进 splice——与产品臂同口径。

    worker ``_PIPE_TO_DB`` 把 pipeline ``partial``（阶梯 recovered）归
    ``ok`` 照常 splice；``e2e_real_bench`` 同此。译文必须非空——worker
    ``_build_zh`` 要求 ``status=="ok" and r["translation"]``，ok+"" 进
    splice 会把块内容从 zh 树静默擦除，应与失败块同回落原文。
    skipped/fault 的 ``translation`` 是原文回填，不判。
    """
    return r.status in ("ok", "partial") and bool(r.translation)


def _env_judge_pass(
    pipe: XlatPipeline,
    scans: list[tuple[Path, ScanResult]],
    results: list[ChunkResult],
    by_file: dict[int, dict[int, str]],
) -> dict[str, Any]:
    """未知 env 块 → LLM 可译性判定；判 False 的块从 ``by_file`` 摘除（回落原文）。"""
    targets: list[tuple[str, Chunk, str]] = []
    for r in results:
        if not _delivered(r):
            continue
        fidx, cid = _split_cid(r.chunk_id)
        chunk = scans[fidx][1].chunks[cid]
        env_name = (chunk.env or "").strip()
        if env_name and env_name not in _KNOWN_ENVS:
            targets.append((r.chunk_id, chunk, env_name))
    verdicts = asyncio.run(_env_judge_all(pipe, targets))
    reverted = sorted(cid for cid, keep in verdicts.items() if not keep)
    for cid in reverted:
        fidx, ccid = _split_cid(cid)
        by_file.get(fidx, {}).pop(ccid, None)
    return {"enabled": True, "asked": len(targets), "reverted": reverted}


def _scan_tree(
    root: Path,
) -> tuple[list[tuple[Path, ScanResult]], list[ChunkIn], list[str], list[str]]:
    """枚举树内 ``.tex`` → 三级分流 → 解析 + chunk 收集。

    文件名闸（``.rtx.tex`` 运行时转储静默跳过、``.code.tex`` tikzlibrary
    机制件记 support）→ 解析崩记 ``fault_files`` → 无散文记
    ``support_files``（pstricks/epsf/宏件/gnuplot 转储——送译即腐蚀，
    按原文保留；与 fault 分流：这里是有意跳过而非失败）。
    """
    scans: list[tuple[Path, ScanResult]] = []
    chunks: list[ChunkIn] = []
    fault_files: list[str] = []
    support_files: list[str] = []
    for f in sorted(
        f for f in root.rglob("*") if f.is_file() and f.suffix.lower() == ".tex"
    ):
        if f.name.startswith("."):
            continue  # 隐文件不进翻译集 (同 worker._parse_all/stagerun)
        if f.name.lower().endswith(".rtx.tex"):
            continue  # REVTeX 运行时转储不进翻译集 (regress4-1003.1717)
        rel = f.relative_to(root).as_posix()
        if f.name.lower().endswith(".code.tex"):
            support_files.append(rel)
            continue
        try:
            res = parse_file(f, flatten=False)
        except Exception:  # noqa: BLE001 -- 单文件解析崩不拖垮整树：
            fault_files.append(rel)  # 记名可审计，该文件按原文保留
            continue
        if not file_has_prose(res.chunks):
            support_files.append(rel)
            continue
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(
            chunk_to_in(c, chunk_id=f"{idx}:{c.id}", ph_map=res.ph_map)
            for c in res.chunks
        )
    return scans, chunks, fault_files, support_files


def _translate_tree(
    root: Path,
    *,
    translator: Translator | None = None,
    env_judge: bool = False,
) -> tuple[dict, _TreeRun]:
    """目录树翻译 + splice 写回；返回 (stats, 运行态)。

    ``env_judge=True`` 时对静态表外的未知 env 块问 LLM 可译性——
    False 的块回落原文不进 splice。
    """
    scans, chunks, fault_files, support_files = _scan_tree(root)

    pipe = XlatPipeline(
        translator or MockTranslator(),
        glossary=Glossary.load(
            placeholders=collect_doc_placeholders(c.content for c in chunks)
        ),
        validator=lambda s, z: validate_pair(s, z).feedback(),
        cache={},
    )
    results = asyncio.run(pipe.run(chunks))
    by_file: dict[int, dict[int, str]] = {}
    n_fault = 0
    n_partial = 0
    for r in results:
        fidx, cid = _split_cid(r.chunk_id)
        if _delivered(r):
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
    for idx, (f, res) in enumerate(scans):
        trans = by_file.get(idx)
        if not trans:
            continue
        zh = reconstruct(res, trans)
        f.write_text(zh, encoding="utf-8")
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
    }
    run = _TreeRun(
        scans=scans,
        trans=by_file,
        chunk_ins={c.chunk_id: c for c in chunks},
        pipe=pipe,
    )
    return stats, run


def mock_translate_tree(
    root: Path,
    *,
    translator: Translator | None = None,
    env_judge: bool | None = None,
) -> dict:
    """目录树内全部 .tex 走 XlatPipeline(MockTranslator) → splice 写回。

    单 pipeline 跨文件编排（chunk_id = ``{file_idx}:{chunk.id}``），
    校验器注入 L0 ``validate_pair``。返回 per-tree 汇总统计。
    ``translator`` 可注入真网关 Translator；``env_judge`` 缺省读
    ``TEXLATE_ENV_JUDGE``（默认关——静态表外 env 的可译性 LLM 判定）。
    """
    ej = env_flag(_ENV_ENV_JUDGE, default=False) if env_judge is None else env_judge
    stats, _run = _translate_tree(root, translator=translator, env_judge=ej)
    return stats


# ---------------------------------------------------------------- 编译尾段


@dataclass(frozen=True)
class _Job:
    """单工程编译上下文——work/main/引擎/超时 + 声明侧旗标全程同捆。"""

    work: Path
    main_rel: str
    eng_name: str
    timeout: float
    probe_flags: tuple[str, ...] = ()


def _tail_dict(res: CompRes, v: Verdict) -> dict:
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


def _probe_flags_of(work: Path, main_rel: str) -> tuple[str, ...]:
    """``target_probe`` best-effort 壳：声明侧编译旗标（minted→-shell-escape 等）。

    worker._probe_target 同款旁路语义——探针崩只空旗标返回，不阻塞编译。
    """
    try:
        return tuple(target_probe(work, main_rel).flags)
    except Exception:  # noqa: BLE001 -- 探针是旁路诊断
        return ()


def _compile_judge(
    job: _Job, *, expect_cjk: bool, flags: list[str] | None = None
) -> tuple[dict, CompRes]:
    """编译 + 判定公共尾段 → (报告 dict, CompRes)。

    best-effort 语义：xelatex halt_on_error=False 对齐 bench；
    tectonic 无此旋钮——恒 ``-Z continue-on-errors``。``flags`` 透传
    fixloop engine_flags（跨引擎臂用——tectonic 丢的 flag 由 xelatex 接）。
    """
    kw: dict[str, object] = (
        {"halt_on_error": False} if job.eng_name == "xelatex" else {}
    )
    res = engine_for(job.eng_name, **kw).compile(
        job.work,
        job.main_rel,
        timeout=job.timeout,
        sandbox=True,
        flags=list(dict.fromkeys([*job.probe_flags, *(flags or [])])) or None,
    )
    v = judge(res, expect_cjk=expect_cjk, log_text=log_text_of(res))
    return _tail_dict(res, v), res


def _embed_tounicode(pdf: Path) -> int:
    """``embed_cjk_mappings`` best-effort 壳：后处理崩不拖管线（对齐 worker 语义）。"""
    try:
        return embed_cjk_mappings(pdf)
    except Exception:  # 产物后处理失败不该 fault 整链
        log.debug("tounicode embed failed", exc_info=True)
        return 0


# ---------------------------------------------------------------- L2 回灌


def _l2_repair(
    job: _Job, run: _TreeRun, res: CompRes, cap: int
) -> tuple[dict, CompRes, dict | None]:
    """L2 回灌一轮：归因 → 重译 → resplice → 重编一次 → 余孽回落。

    返回 (l2 报告, 最新 CompRes, 新尾段或 None)。
    """
    rep: dict[str, Any] = {"enabled": True, "cap": cap}
    hits, n_err = _l2_localize(job.work, run, res)
    rep["errors"] = n_err
    rep["hits"] = hits
    last_res = res
    if not hits:
        rep["note"] = "no chunk-level attribution"
        return rep, last_res, None

    retr = asyncio.run(_retranslate_hits(run, hits, cap))
    changed: set[str] = retr.pop("_changed")
    adopted: set[str] = retr.pop("_adopted")
    rep.update(retr)
    if not changed:
        rep["note"] = "no chunk changed"
        return rep, last_res, None

    rep["rewritten"] = _resplice(
        run, job.work, job.main_rel, {_split_cid(c)[0] for c in changed}
    )
    tail2, res2 = _compile_judge(job, expect_cjk=True)
    last_res = res2
    rep["recompiled"] = tail2["verdict"]["status"]
    if tail2["status"] == "clean":
        return rep, last_res, tail2

    # 重编仍不过：本轮"重译过且仍被点名"的块回落原文；
    # 其余归因（含已回落原文仍犯错的——那是源级问题）记名留 fixloop。
    hits2, _ = _l2_localize(job.work, run, res2)
    still_bad = sorted(set(hits2) & adopted)
    rep["fallback_src"] = still_bad
    rep["unresolved"] = sorted(set(hits2) - adopted)
    if still_bad:
        for cid in still_bad:
            fidx, ccid = _split_cid(cid)
            run.trans.get(fidx, {}).pop(ccid, None)
        rep["fallback_rewritten"] = _resplice(
            run, job.work, job.main_rel, {_split_cid(c)[0] for c in still_bad}
        )
        # 回落态即交付树——补一次裸编：fixloop 关/崩/reject 时不再有
        # 代验兜底，zh-src.zip 不能装未验证树（audit fallback_unverified）
        tail3, res3 = _compile_judge(job, expect_cjk=True)
        rep["fallback_verdict"] = tail3["verdict"]["status"]
        last_res, tail2 = res3, tail3
    return rep, last_res, tail2


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
        "log_excerpt": cell.get("log_excerpt"),
    }


@contextmanager
def _baseline_snapshot(work: Path, *, enabled: bool) -> Iterator[Path | None]:
    """翻前快照 → fixloop ``baseline_dir``（normalize 后/翻译前的 pristine 树）。

    worker ``ctx.base_dir`` 同位（normalize 过的英文树）——e2e 原地翻译
    无常驻 base，``restore_support_from_src`` 要它逐字节复原被写脏的
    support 件。fixloop 关闭时跳过（省一次全树 copytree）；快照放系统
    tempdir 防污染 ``_scan_tree``/编译枚举，``with`` 出块即清理；快照
    失败降级 None（修复臂旁路件，不该砸死主链）。
    """
    if not enabled:
        yield None
        return
    with tempfile.TemporaryDirectory(prefix="texlate-baseline-") as td:
        base = Path(td) / "base"
        try:
            shutil.copytree(work, base)
        except (OSError, shutil.Error) as e:
            log.warning("baseline snapshot failed (%s) → fixloop 无 baseline", e)
            base = None
        yield base


def _run_fixloop(  # noqa: PLR0913 -- 开关面穿透同 pipe_condition
    job: _Job,
    route_engines: list[str],
    prev_res: CompRes,
    *,
    timeout: float | None = None,
    llm_hook: LlmHook | None = None,
    expect_cjk: bool = True,
    baseline_dir: Path | None = None,
) -> tuple[dict, dict | None, CompRes]:
    """跑 fixloop + 消费 engine_flags → (报告, 新尾段或 None, 最新 CompRes)。

    引擎新造不带 e2e 的 best-effort 旋钮——xelatex 默认 halt_on_error=True
    （fixloop 首错分类语义）。flags 经 ``compile(flags=…)`` seam 落 CLI：
    xelatex 追加 argv；tectonic 只放支持子集，dropped 项（多为
    shell-escape 需求）→ 记 advisory + 换 xelatex 重编取优。

    ``timeout`` 覆盖 rules.yaml ``meta.loop.timeout_sec`` 的重编预算
    （None=用 yaml 值）。``llm_hook`` 未传时 ``TEXLATE_FIXLOOP_LLM=1``
    可经 env 启用 escalate_llm 钩（网关走 TEXLATE_* 三件套）。
    ``baseline_dir`` 在场时注入 ruleset（``repair._ruleset_with_baseline``——
    worker ``ctx.base_dir`` 同件注入），缺席走默认 ruleset（restore_support_from_src
    fail-safe 空转，bench 直调臂即此形态）。
    """
    if llm_hook is None and env_flag("TEXLATE_FIXLOOP_LLM", default=False):
        from texlate.compile.fixloop.llm_hook import make_llm_hook  # noqa: PLC0415

        llm_hook = make_llm_hook()
    try:
        cell, fix_last = run_fixloop(
            job.work,
            engine_for(job.eng_name),
            ruleset=(
                _ruleset_with_baseline(baseline_dir)
                if baseline_dir is not None
                else None
            ),
            engine_name=job.eng_name,
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
        tail = _tail_dict(last_res, Verdict(status="partial", reasons=[cell_verdict]))
        tail["reject_at"] = "fixloop"
    else:
        tail = _tail_dict(
            last_res,
            judge(last_res, expect_cjk=expect_cjk, log_text=log_text_of(last_res)),
        )

    flags: list[str] = rep["engine_flags"]
    dropped: list[str] = rep["engine_flags_dropped"]
    if dropped:
        rep["flags_unapplied"] = True
        # 跨引擎消费：dropped 多为 shell-escape 需求——tectonic --untrusted
        # 下不收 → 换 xelatex 重编并把全部请求 flag 经 seam 带给它（retry
        # 机械在 repair.cross_engine_retry——本臂沿 _compile_judge 的
        # best-effort 旋钮与 probe_flags 合并）
        xr = cross_engine_retry(
            engine_name=job.eng_name,
            route_engines=route_engines,
            current_status=tail["status"],
            work=job.work,
            main_rel=job.main_rel,
            timeout=job.timeout,
            flags=list(dict.fromkeys([*job.probe_flags, *flags])) or None,
            dropped=dropped,
            expect_cjk=expect_cjk,
            make_engine=lambda: engine_for("xelatex", halt_on_error=False),
        )
        if xr is not None:
            rep["cross_engine"] = xr.info
            if xr.adopted:
                tail, last_res = _tail_dict(xr.res, xr.verdict), xr.res
        # 注在换编之后——贴到最终采用的 tail 上，换臂不丢审计痕迹
        tail["verdict"]["notes"].append(
            f"engine_flags unsupported on {job.eng_name}: {dropped}"
        )
    elif flags:
        tail["verdict"]["notes"].append(f"engine_flags applied via CLI seam: {flags}")
    return rep, tail, last_res


# ---------------------------------------------------------------- 条件臂


def _repair_chain(  # noqa: PLR0913 -- 修复链开关面穿透
    rec: dict,
    job: _Job,
    run: _TreeRun,
    res: CompRes,
    *,
    expect_cjk: bool,
    l2_on: bool | None,
    fixloop_on: bool | None,
    l2_max_chunks: int,
    route_engines: list[str] | None,
    baseline_dir: Path | None = None,
) -> CompRes:
    """非 clean 后的两级修复链：L2 回灌 → fixloop；reports 直写 ``rec``。

    L2 崩不丢整条 rec（worker._l2_attempt 同款包）；fixloop 只在仍非
    clean 时跑。返回最新 ``CompRes`` 供 ToUnicode 注入判产物。
    """
    l2 = (not env_flag(_ENV_NO_L2, default=False)) if l2_on is None else l2_on
    if l2:
        try:
            l2_rep, res, tail2 = _l2_repair(job, run, res, l2_max_chunks)
        except Exception as e:  # noqa: BLE001 -- L2 崩不丢整条 rec（含首编 verdict）
            rec["l2"] = {"enabled": True, "error": f"{type(e).__name__}: {e}"}
        else:
            rec["l2"] = l2_rep
            if tail2 is not None:
                rec.update(tail2)
    else:
        rec["l2"] = {"enabled": False, "reason": _ENV_NO_L2}

    fl = (
        (not env_flag(_ENV_NO_FIXLOOP, default=False))
        if fixloop_on is None
        else fixloop_on
    )
    if rec["status"] != "clean" and fl:
        fl_rep, tail3, res = _run_fixloop(
            job,
            route_engines or [job.eng_name],
            res,
            timeout=job.timeout,
            expect_cjk=expect_cjk,
            baseline_dir=baseline_dir,
        )
        rec["fixloop"] = fl_rep
        if tail3 is not None:
            rec.update(tail3)
    elif rec["status"] != "clean":
        rec["fixloop"] = {"enabled": False, "reason": _ENV_NO_FIXLOOP}
    return res


def pipe_condition(  # noqa: PLR0913 -- 修复链开关面（env 缺省，显式可覆盖）
    work: Path,
    eng_name: str,
    main_rel: str,
    timeout: float,
    *,
    translator: Translator | None = None,
    env_judge: bool | None = None,
    l2_on: bool | None = None,
    fixloop_on: bool | None = None,
    l2_max_chunks: int = L2_MAX_CHUNKS,
    route_engines: list[str] | None = None,
) -> dict:
    """跑 pipe 条件：normalize → 翻译 → ctex 注入 → 编译 → 判定 → 修复链。

    非 clean 时先 L2 回灌（译文归因重译）再 fixloop（规则修源）。开关：
    ``TEXLATE_ENV_JUDGE`` / ``TEXLATE_NO_L2`` / ``TEXLATE_NO_FIXLOOP``
    （显式参数优先于 env）。``route_engines`` 供 engine_flags 跨引擎消费，
    缺省 ``[eng_name]``（bench 直调不跨界）。fixloop 启用时翻译前先抓
    baseline 快照（worker ``ctx.base_dir`` 同位——e2e 原地翻译，snapshot
    即 pristine 源），供 restore_support_from_src 复原被写脏的 support 件。
    """
    rec: dict[str, object] = {"engine": eng_name}
    rec["normalize"] = normalize_project(work, eng_name, main_rel)
    ej = env_flag(_ENV_ENV_JUDGE, default=False) if env_judge is None else env_judge
    fl = (
        (not env_flag(_ENV_NO_FIXLOOP, default=False))
        if fixloop_on is None
        else fixloop_on
    )
    with _baseline_snapshot(work, enabled=fl) as baseline_dir:
        stats, run = _translate_tree(work, translator=translator, env_judge=ej)
        rec["translate"] = stats
        try:
            rec["inject"] = prepare_chinese(work, main_rel)
        except InjectRejectError as e:
            # 策略拒绝 → partial (降级链交付), reject_at+reason 留审计 (F3)
            rec["status"] = "partial"
            rec["reject_at"] = "inject"  # inject_reject 类: 与 route reject 分流
            rec["verdict"] = {"status": "partial", "reasons": [e.reason]}
            return rec
        job = _Job(
            work,
            main_rel,
            eng_name,
            timeout,
            probe_flags=_probe_flags_of(work, main_rel),
        )
        # 0-chunk 主文档 (includepdf 壳等) 无译文产出 → 不期待 CJK 渲染,
        # cjk_chars=0 是其正确终态而非静默失败 (scout-cjk0 F 桶 11 格假阳)
        expect_cjk = stats.get("chunks") != 0
        tail, res = _compile_judge(job, expect_cjk=expect_cjk)
        rec.update(tail)

        if rec["status"] != "clean":
            res = _repair_chain(
                rec,
                job,
                run,
                res,
                expect_cjk=expect_cjk,
                l2_on=l2_on,
                fixloop_on=fl,
                l2_max_chunks=l2_max_chunks,
                route_engines=route_engines,
                baseline_dir=baseline_dir,
            )
        # ToUnicode 注入在修复链收敛之后——L2 重编/fixloop 换编都会重写同一
        # <stem>.pdf，只对最终落盘产物注一次（worker _embed_tounicode 同位）
        if res.has_pdf and res.pdf is not None:
            rec["tounicode_fonts"] = _embed_tounicode(res.pdf)
    return rec


def base_condition(work: Path, eng_name: str, main_rel: str, timeout: float) -> dict:
    """跑 base 条件：不动源码直接编译+判定（管线引入 vs 原生失败的归因对照）。"""
    rec: dict[str, object] = {"engine": eng_name}
    job = _Job(
        work,
        main_rel,
        eng_name,
        timeout,
        probe_flags=_probe_flags_of(work, main_rel),
    )
    tail, _res = _compile_judge(job, expect_cjk=False)
    rec.update(tail)
    return rec


def mock_pipeline_run(  # noqa: PLR0913 -- 同上：开关面穿透到 pipe_condition
    work: Path,
    engine_opt: str,
    timeout: float,
    *,
    translator: Translator | None = None,
    env_judge: bool | None = None,
    l2_on: bool | None = None,
    fixloop_on: bool | None = None,
    l2_max_chunks: int = L2_MAX_CHUNKS,
) -> dict:
    """工程目录上的 mock 全链（对齐 e2e_mock_bench 的 pipe 条件语义）。

    ``engine_opt``：``auto`` 取路由首选，或显式引擎名。返回结构化报告 dict
    （route/normalize/translate/inject/compile/verdict + 修复链 + 终态）。
    """
    report: dict[str, object] = {"work": str(work)}
    route = route_project(work)
    report["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    if route.reject:
        report["status"] = "partial"  # 策略拒绝 → partial (F3), reject_at 审计
        report["reject_at"] = "route"
        return report
    main_path = find_main_tex(work)
    if main_path is None:
        sub = classify_no_main(work)
        report["status"] = "partial"
        report["reject_at"] = "route"
        report["route"]["reasons"] = [
            *route.reasons,
            f"no main tex:{sub}" if sub else "no main tex",
        ]
        return report
    main_rel = main_path.relative_to(work).as_posix()
    report["main"] = main_rel

    eng_name = engine_opt if engine_opt != "auto" else route.engines[0]
    report.update(
        pipe_condition(
            work,
            eng_name,
            main_rel,
            timeout,
            translator=translator,
            env_judge=env_judge,
            l2_on=l2_on,
            fixloop_on=fixloop_on,
            l2_max_chunks=l2_max_chunks,
            # 显式 engine 收窄到该引擎——跨引擎换编臂自熄（worker
            # _build_base 同口径：engines = route.engines if auto else
            # [opt_engine]，持久化进 options.route_engines）
            route_engines=route.engines if engine_opt == "auto" else [eng_name],
        )
    )
    return report
