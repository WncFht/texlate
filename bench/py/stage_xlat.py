r"""stage_xlat.py — stagerun ``xlat`` stage：XlatPipeline → zh/ 就地翻译。

asyncio 编排：``--sem`` 全局信号量压网关 in-flight（默认 4，对齐网关并发闸），
``--jobs`` 控制同时在翻的论文数。产物：zh/（暂存翻译完工换名）+
xlat-{arm}.jsonl 逐块明细 + zh/.xlat-arm.json provenance marker。

auth 断路器（与 e2e_real_bench 同型，★6 回补）：
  - 篇内：``AuthTrippedError``（连续 auth_fail_threshold 块 401/403）不再
    被 per-paper ``except Exception`` 吞成普通 error 续跑——记 error
    （retriable）+ ``auth_tripped`` 印，drive 收摊（死 key 不空烧全批）。
  - 跨篇：``translate.auth_all_failed`` 连续 ``benchlib.AUTH_DEAD_STREAK``
    篇即停（兜篇均不足阈值块的慢速失血）。
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import shutil
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import benchlib
import quality_proxies as qp  # S5 质量代理件（leak/term 指标 + TERM_ARMS + 禁用户层哨兵）
import stagerun_lib as sl
import translators_bench as tb  # xlat 臂工厂 + sabotage 台账（e2e_mock 注入逻辑由此封装）

from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import reconstruct
from texlate.pipecore import scan_tree as _scan_tree
from texlate.validate.l0 import validate_pair
from texlate.xlat.client import ChatClient
from texlate.xlat.glossary import LOCAL_GLOSSARY_NAME, Glossary
from texlate.xlat.pipeline import (
    AuthTrippedError,
    GatewayTranslator,
    PipelineConfig,
    XlatPipeline,
)
from texlate.xlat.placeholders import collect_doc_placeholders
from texlate.xlat.state import StateStore

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


class _SemTranslator:
    """全局网关信号量包裹：run 内全部 paper/pipeline 共享同一 sem（网关并发闸）。

    per-paper PipelineConfig.concurrency 管论文内部排队；本层管跨论文的
    真实在途请求数——``--sem 4`` 即全局 in-flight ≤4。
    """

    def __init__(self, inner: object, sem: asyncio.Semaphore) -> None:
        self._inner = inner
        self._sem = sem

    def __getattr__(self, k: str) -> object:
        return getattr(self._inner, k)

    async def translate(self, **kw: object) -> str:
        async with self._sem:
            return await self._inner.translate(**kw)


#: 逐请求计时归因槽：``client.chat`` 全 run 只包一层（client 跨篇共享），
#: 靠本 contextvar 把每次 HTTP 耗时记回发起它的 inner.translate 账上——
#: 同 task 上下文生效，worker 任务间天然隔离，跨篇不串账。
_CHAT_SINK: contextvars.ContextVar[list[float] | None] = contextvars.ContextVar(
    "xlat_chat_sink", default=None
)


def _install_chat_timer(client: ChatClient) -> None:
    """``client.chat`` 包计时一层（real 臂；幂等——drive 可多篇复用同 client）。"""
    if getattr(client, "_chat_timed", False):
        return
    orig = client.chat

    async def timed(*a: object, **kw: object) -> object:
        t0 = time.monotonic()
        try:
            return await orig(*a, **kw)
        finally:
            s = _CHAT_SINK.get()
            if s is not None:
                s.append(time.monotonic() - t0)

    client.chat = timed  # 实例遮蔽类方法；client 生命周期 = 本次 run
    client._chat_timed = True


def _instrument_translator(translator: object) -> dict:
    """per-paper 请求时序三包——``translate.seconds`` 三分拆原料（零产品码）。

    管道只见外层 ``translator.translate``：outer span = 全局 sem 排队 + 全程；
    ``translator._inner.translate``（real=GatewayTranslator）：inner span =
    退避重试全程（call_with_backoff 内部 sleep 也在其内）；inner span 内经
    ``_CHAT_SINK`` 收齐的 ``client.chat`` 耗时 = 纯请求时延。故
    退避 ≈ inner − chat，sem 排队 ≈ outer − inner。mock/无 ``.client`` 臂
    chat 侧自然记零。
    """
    rec = {"calls": 0, "outer_s": 0.0, "inner_s": 0.0, "chat_s": 0.0, "chat_calls": 0}
    inner = getattr(translator, "_inner", translator)
    orig_inner = inner.translate

    async def inner_timed(**kw: object) -> str:
        chats: list[float] = []
        tok = _CHAT_SINK.set(chats)
        t0 = time.monotonic()
        try:
            return await orig_inner(**kw)
        finally:
            d = time.monotonic() - t0
            _CHAT_SINK.reset(tok)
            rec["inner_s"] += d
            rec["chat_s"] += sum(chats)
            rec["chat_calls"] += len(chats)

    inner.translate = inner_timed  # per-paper 实例遮蔽，无跨篇串账
    orig_outer = translator.translate

    async def outer_timed(**kw: object) -> str:
        t0 = time.monotonic()
        try:
            return await orig_outer(**kw)
        finally:
            rec["outer_s"] += time.monotonic() - t0
            rec["calls"] += 1

    translator.translate = outer_timed
    return rec


async def _translate_tree(
    root: Path,
    translator: object,
    state_dir: Path,
    cfg: PipelineConfig,
    *,
    oversize_cap: int = 0,
    glossary_categories: list[str] | None = None,
    local_glossary: Path | None = None,
) -> tuple[dict, list]:
    """e2e_real.translate_tree 同构 + 返回逐块结果（chunk 明细/sabotage 归因用）。

    扫描段单源 ``pipecore.scan_tree``——文件名四门（dotfile 跳、``.rtx.tex`` 跳、
    ``.code.tex``/无散文记 support_files）与 ``is_file``/suffix 小写口径同
    e2e/mock/real 臂不漂移（★3 收敛：旧内联件漏 ``.TEX``/``.RTX.TEX`` 大写形，
    support 只记 basename 丢子目录路径）。
    """
    scans, chunks, fault_files, support_files = _scan_tree(root)
    total_chars = sum(len(c.content) for c in chunks)
    if oversize_cap and total_chars > oversize_cap:
        # 保守闸（同 e2e_real）：超上限不烧网关配额——调用侧记 oversize 终态
        return (
            {
                "files": 0,
                "chunks": len(chunks),
                "ok": 0,
                "partial": 0,
                "fault": 0,
                "skipped": 0,
                "attempts": 0,
                "batched": 0,
                "leftover_ph": 0,
                "fault_files": fault_files,
                "support_files": support_files,
                "support_skipped": len(support_files),
                "warn_kinds": {},
                "seconds": 0.0,
                "src_chars": total_chars,
                "oversize": True,
                "max_total_chars": oversize_cap,
            },
            [],
        )
    stats: dict[str, int] = {
        "ok": 0,
        "partial": 0,
        "fault": 0,
        "skipped": 0,
        "attempts": 0,
        "batched": 0,
    }
    t0 = time.monotonic()
    state_dir.mkdir(parents=True, exist_ok=True)
    state = StateStore(state_dir, model=getattr(translator, "model", "") or "")
    # 术语表注入只服务 TERM_ARMS（real）——mock 系臂不调 LLM，注入纯属
    # doc_filter 空转。categories=None → glossary=None → pipe._doc_glossary={}。
    # user 层禁用哨兵同 quality_proxies._NO_USER_GLOSSARY：机器相关的
    # ~/.texlate/glossary.yaml 会让跨机跑批与后算重建口径双双漂移。
    glossary = None
    if glossary_categories is not None:
        glossary = Glossary.load(
            user_path=qp._NO_USER_GLOSSARY,
            local_path=local_glossary,
            categories=glossary_categories,
            placeholders=collect_doc_placeholders(c.content for c in chunks),
        )
    req_rec = _instrument_translator(translator)
    pipe = XlatPipeline(
        translator,
        config=cfg,
        glossary=glossary,
        state=state,
        validator=lambda s, z: validate_pair(s, z).feedback(),
    )
    results = await pipe.run(chunks)
    if glossary is not None:
        # term_dict 落盘（xlat-state/{arm}/term_dict.json）——观测件不毁账：
        # 写盘失败不应把已完成的翻译格记成 error。
        with contextlib.suppress(Exception):
            state.save_maps(term_dict=pipe._doc_glossary)
    translate_s = time.monotonic() - t0

    by_file: dict[int, dict[int, str]] = {}
    warn_kinds: dict[str, int] = {}
    for r in results:
        try:
            fidx, cid = (int(x) for x in r.chunk_id.split(":", 1))
        except ValueError:
            # 畸形 chunk_id（translator 违约）——记 fault+名，不让整篇崩
            stats["fault"] += 1
            warn_kinds["bad_chunk_id"] = warn_kinds.get("bad_chunk_id", 0) + 1
            continue
        stats["attempts"] += r.attempts
        stats["batched"] += int(r.batched)
        if r.status in stats:
            stats[r.status] += 1
        else:
            stats["fault"] += 1
        if r.status == "ok" or (r.status == "partial" and r.translation):
            by_file.setdefault(fidx, {})[cid] = r.translation
        for w in r.warnings:
            key = w.split(":", 1)[0][:60]
            warn_kinds[key] = warn_kinds.get(key, 0) + 1
        if r.skip_reason:
            key = "skip:" + r.skip_reason.split(":", 1)[0][:60]
            warn_kinds[key] = warn_kinds.get(key, 0) + 1

    n_files = n_leftover = 0
    for idx, (f, res) in enumerate(scans):
        trans = by_file.get(idx)
        if not trans:
            continue
        zh = reconstruct(res, trans)
        f.write_text(zh, encoding="utf-8")
        n_files += 1
        n_leftover += len(PH_RX.findall(zh))
    stats_d = {
        "files": n_files,
        "chunks": len(chunks),
        **stats,
        "leftover_ph": n_leftover,
        "fault_files": fault_files,
        "support_files": support_files,
        "support_skipped": len(support_files),
        "warn_kinds": dict(sorted(warn_kinds.items())),
        "seconds": round(translate_s, 1),
        "src_chars": total_chars,
        # 请求时序三分拆（A1 界外需求裁决 a）：chat=纯 HTTP 时延，
        # backoff=inner−chat 退避睡眠，sem_wait=outer−inner 全局闸排队，
        # span=outer 请求路径总占；编排残差 = seconds − span/concurrency。
        "req_timing": {
            "calls": req_rec["calls"],
            "chat_calls": req_rec["chat_calls"],
            "chat_s": round(req_rec["chat_s"], 1),
            "backoff_s": round(max(0.0, req_rec["inner_s"] - req_rec["chat_s"]), 1),
            "sem_wait_s": round(max(0.0, req_rec["outer_s"] - req_rec["inner_s"]), 1),
            "span_s": round(req_rec["outer_s"], 1),
        },
        # AuthGate 设计口径「跨论文熔断由调用方累计」（e2e_real 同款键）：
        # 整篇全 auth 败时 drive 连记 N 篇即收摊（篇内阈值块熔断走
        # AuthTrippedError 即停，本键兜篇均不足阈值块的慢速失血）。
        "auth_all_failed": pipe.auth_gate.all_failed,
    }
    return stats_d, results


async def _xlat_one(
    pid: str,
    out_dir: Path,
    args: argparse.Namespace,
    translator_factory,
    paper_sem: asyncio.Semaphore,
) -> dict:
    # t0 进闸才打——闸外等待是跨篇排队不是本格功（此前 dur_s≈99.6% queue
    # wait，stage 占比全失真，perf 侦察头条）；排队量另记 queue_wait_s。
    tq = t0 = time.monotonic()
    qw = 0.0
    try:
        async with paper_sem:
            t0 = time.monotonic()
            qw = t0 - tq
            rec = await _xlat_one_inner(pid, out_dir, args, translator_factory, t0)
            rec["queue_wait_s"] = round(qw, 3)
            return rec
    except AuthTrippedError as e:
        # 篇内连续 auth-fail 熔断抛出 = 凭证死透——erb amain 同型：不收摊的
        # 话其后每篇只会各烧 auth_fail_threshold 块再 error（scout-e2ereal
        # §9）。落 error 格（retriable）+ auth_tripped 印，drive 见印即停；
        # 换凭证后同命令续跑。
        rec = sl.crash_rec(pid, "xlat", args.arm, e, t0)
        rec["auth_tripped"] = True
        rec["queue_wait_s"] = round(qw, 3)
        return rec
    except Exception as e:  # 格子崩溃记 error 不炸整批（CancelledError 仍外抛）
        rec = sl.crash_rec(pid, "xlat", args.arm, e, t0)
        rec["queue_wait_s"] = round(qw, 3)
        return rec


async def _xlat_one_inner(
    pid: str, out_dir: Path, args: argparse.Namespace, translator_factory, t0: float
) -> dict:
    rec = sl.base_rec(pid, "xlat", args.arm)
    wid = sl.workdir(out_dir, pid)
    zh = wid / "zh"
    pj = wid / "parse.json"
    if not zh.is_dir() or not pj.exists():
        return sl.gate_rec(
            rec,
            "skip",
            "no_parse_tree",
            "upstream",
            "zh/ or parse.json missing",
            t0,
        )
    translator = translator_factory(pid)
    state_dir = wid / "xlat-state" / args.arm  # 臂间 state 隔离——mock 结果不回灌 real
    cfg = PipelineConfig(concurrency=args.concurrency)
    cap = benchlib.MAX_TOTAL_CHARS if args.arm == "real" else 0  # 配额闸只对真网关
    # stagerun 驱动入口把 manifest cat_group 透传成 args.cat_map；直调本
    # stage 的调用方没此面 → 空 map，术语层退回 default.csv 兜底（§4）。
    cat_map = getattr(args, "cat_map", None) or {}
    # 同 _parse_job staging-swap: 翻译写进暂存树, 完工换名 —— 期间 zh/
    # 保持上一版 (marker+内容一致), 并发 compile 不读半成品
    stage = wid / ".zh-xlat"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(zh, stage, ignore=benchlib.copytree_ignore())
    stats, results = await _translate_tree(
        stage,
        translator,
        state_dir,
        cfg,
        oversize_cap=cap,
        glossary_categories=(
            [cat_map.get(pid) or ""] if args.arm in qp.TERM_ARMS else None
        ),
        local_glossary=wid / "src" / LOCAL_GLOSSARY_NAME,
    )
    if stats.get("oversize"):
        shutil.rmtree(stage, ignore_errors=True)
        rec["metrics"]["translate"] = stats
        return sl.gate_rec(
            rec, "reject", "oversize", "xlat", f"src_chars={stats['src_chars']}", t0
        )
    # 逐块明细（triage/契约审计原料）
    detail = wid / f"xlat-{args.arm}.jsonl"
    with detail.open("w", encoding="utf-8") as fh:
        for r in results:
            benchlib.write_jsonl(
                fh,
                {
                    "chunk_id": r.chunk_id,
                    "status": r.status,
                    "attempts": r.attempts,
                    "batched": r.batched,
                    "skipped": r.fell_back,
                    "error_kind": r.error_kind,
                    "skip_reason": r.skip_reason,
                    "warnings": r.warnings,
                },
            )
    marker = stage / ".xlat-arm.json"
    marker.write_text(
        json.dumps(
            {
                "arm": args.arm,
                "model": getattr(translator, "model", None),
                "ts": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
    )
    old = zh.with_name(".zh-xlat-old")
    if zh.exists():
        if old.exists():
            shutil.rmtree(old)
        zh.rename(old)
    stage.rename(zh)
    if old.exists():
        shutil.rmtree(old)
    rec["metrics"]["translate"] = stats
    # S5 质量代理观测键（wiring §1）：leak 两臂同义——送译 source 命中展开
    # 残留是上游 parse/gullet 质量面，与翻译臂无关；term 只 TERM_ARMS——
    # mock 系译文是 echo/扰动占位，置 null 键保形状（聚合按臂过滤）。
    stats.update(qp.scan_leak([(r.chunk_id, r.source or "") for r in results]))
    if args.arm in qp.TERM_ARMS:
        delivered = [
            (r.chunk_id, r.source or "", r.translation or "")
            for r in results
            if r.status in ("ok", "partial") and r.translation
        ]
        try:
            td = qp.rebuild_term_dict(
                cat_map.get(pid),
                [s for _c, s, _t in delivered],
                wid / "src" / LOCAL_GLOSSARY_NAME,
            )
            stats.update(qp.score_terms(delivered, td))
        except Exception as e:  # 观测件不毁账——重建失败记 note 不落 error 格
            stats.update(
                {
                    "term_applicable": None,
                    "term_hit": None,
                    "term_hit_rate": None,
                    "term_misses": [],
                    "term_dict_size": None,
                    "term_note": f"rebuild_failed:{type(e).__name__}",
                }
            )
    else:
        stats.update(
            {
                "term_applicable": None,
                "term_hit": None,
                "term_hit_rate": None,
                "term_misses": [],
                "term_dict_size": None,
            }
        )
    # sabotage/perturb 臂带 .finalize 台账面（translators_bench 契约）；
    # mock/real 无此面，getattr 探空跳过
    finalize = getattr(translator, "finalize", None)
    if finalize is not None:
        ledger = finalize(results)
        rec["metrics"]["sabotage"] = ledger
        if ledger.get("escaped"):
            rec["status"] = "fail"
            rec["errors"] = [
                {
                    "code": "sabotage_escaped",
                    "cat": "xlat",
                    "payload": f"{ledger['escaped']} escaped: {ledger['escaped_ids'][:8]}",
                }
            ]
            return sl.finish_rec(rec, t0)
    n_bad = stats["fault"] + stats["skipped"]
    if stats["leftover_ph"] > 0:
        rec["status"] = "fail"
        rec["errors"] = [
            {"code": "leftover_ph", "cat": "xlat", "payload": str(stats["leftover_ph"])}
        ]
    elif stats["chunks"] and n_bad == stats["chunks"]:
        rec["status"] = "fail"
        rec["errors"] = [
            {"code": "all_chunks_bad", "cat": "xlat", "payload": str(stats["chunks"])}
        ]
    elif n_bad or stats["fault_files"]:
        rec["status"] = "partial"
        if n_bad:
            rec["errors"] = [
                {
                    "code": "chunks_bad",
                    "cat": "xlat",
                    "payload": f"fault={stats['fault']} skipped={stats['skipped']}",
                }
            ]
    else:
        rec["status"] = "ok"
    return sl.finish_rec(rec, t0)


def stage_xlat(
    args: argparse.Namespace,
    out_dir: Path,
    ids: list[str],
    log: sl.RecLog,
    parse_recs: dict,
) -> None:
    upstream_ok = set((args.upstream or "ok").split(","))
    ids = sl.dedup_wids(ids)  # 同 wid 单任务闸——直调本驱动的调用方也兜住
    todo = []
    for pid in ids:
        if log.is_done(pid, args.arm, recode=args.recode) and not args.rerun:
            continue
        up = parse_recs.get((pid, "-", ""))
        if up is not None and up.get("status") not in upstream_ok:
            r = sl.base_rec(pid, "xlat", args.arm)
            r["status"] = "skip"
            r["errors"] = [
                {
                    "code": "upstream_gate",
                    "cat": "upstream",
                    "payload": f"parse={up.get('status')}",
                }
            ]
            log.append(sl.finish_rec(r, time.monotonic()))
            continue
        todo.append(pid)
    print(
        f"xlat[{args.arm}]: {len(todo)} to run (jobs={args.jobs} sem={args.sem})",
        flush=True,
    )
    if not todo:
        return

    async def drive(translator_factory) -> None:
        sem = asyncio.Semaphore(args.sem)
        paper_sem = asyncio.Semaphore(args.jobs)

        def make(pid: str):
            return _SemTranslator(translator_factory(pid), sem)

        tasks = [
            asyncio.ensure_future(_xlat_one(p, out_dir, args, make, paper_sem))
            for p in todo
        ]

        async def _drain_rest() -> None:
            """收摊路径共用：取消在飞任务并等其退出（CancelledError 不被
            _xlat_one 的 except Exception 吞——CancelledError 属 BaseException）。"""
            for tk in tasks:
                tk.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        t_start = time.monotonic()
        auth_dead = 0  # 连续「全 auth 败」篇数（cached 格不触碰——没测凭证）
        for i, fut in enumerate(asyncio.as_completed(tasks), 1):
            rec = await fut
            log.append(rec)
            t = (rec.get("metrics") or {}).get("translate") or {}
            print(
                f"  [{i}/{len(todo)}] {rec['id']} -> {rec['status']} "
                f"ok={t.get('ok', '-')}/{t.get('chunks', '-')} ph={t.get('leftover_ph', '-')} ({rec['dur_s']}s)",
                flush=True,
            )
            if rec.get("auth_tripped"):
                # 篇内熔断（AuthTrippedError）——凭证死透即收摊（erb 同型）
                print(
                    "auth circuit tripped — 凭证疑似失效（连续 401/403 熔断），"
                    "停跑不空烧；换凭证后同命令续跑",
                    flush=True,
                )
                await _drain_rest()
                break
            auth_dead = auth_dead + 1 if t.get("auth_all_failed") else 0
            if auth_dead >= benchlib.AUTH_DEAD_STREAK:
                print(
                    f"连续 {auth_dead} 篇全部请求 auth 失败——凭证疑似失效，停跑",
                    flush=True,
                )
                await _drain_rest()
                break
            if args.time_budget and time.monotonic() - t_start > args.time_budget:
                print(
                    f"time budget {args.time_budget}s — stop ({i}/{len(todo)})",
                    flush=True,
                )
                await _drain_rest()
                break

    if args.arm == "real":

        async def _run_real() -> None:
            async with ChatClient(args.base_url, args.api_key) as client:
                _install_chat_timer(client)
                if not args.no_probe:
                    probe = await client.probe_model(args.model)
                    print(
                        f"probe {args.model}: ok={probe.probe_ok} "
                        f"lat={probe.probe_latency_s}s err={probe.probe_error}",
                        flush=True,
                    )
                    if not probe.probe_ok:
                        print("model probe failed — abort", flush=True)
                        return

                def factory(pid: str):
                    return GatewayTranslator(client, args.model)

                await drive(factory)

        asyncio.run(_run_real())
    else:

        def factory(pid: str):
            return tb.make_translator(args.arm)

        asyncio.run(drive(factory))
