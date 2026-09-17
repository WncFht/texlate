r"""stage_xlat.py — stagerun ``xlat`` stage：XlatPipeline → zh/ 就地翻译。

asyncio 编排：``--sem`` 全局信号量压网关 in-flight（默认 4=gwcap 硬闸），
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
import json
import shutil
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import benchlib
import stagerun_lib as sl
import translators_bench as tb  # xlat 臂工厂 + sabotage 台账（e2e_mock 注入逻辑由此封装）

from texlate.latex.api import parse_file
from texlate.latex.placeholder import PH_RX
from texlate.latex.prose import file_has_prose
from texlate.latex.reconstruct import reconstruct
from texlate.validate.l0 import validate_pair
from texlate.xlat.client import ChatClient
from texlate.xlat.pipeline import (
    AuthTrippedError,
    GatewayTranslator,
    PipelineConfig,
    XlatPipeline,
    chunk_to_in,
)
from texlate.xlat.state import StateStore

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


class _SemTranslator:
    """全局网关信号量包裹：run 内全部 paper/pipeline 共享同一 sem（gwcap 硬闸）。

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


async def _translate_tree(
    root: Path,
    translator: object,
    state_dir: Path,
    cfg: PipelineConfig,
    *,
    oversize_cap: int = 0,
) -> tuple[dict, list]:
    """e2e_real.translate_tree 同构 + 返回逐块结果（chunk 明细/sabotage 归因用）。"""
    scans = []
    chunks = []
    parse_fail: list[str] = []
    support_files: list[str] = []
    for f in sorted(root.rglob("*.tex")):
        if f.name.startswith(".") or f.name.endswith(".rtx.tex"):
            continue  # 隐文件 + REVTeX 运行时转储不进翻译集 (regress4-1003.1717)
        if f.name.lower().endswith(".code.tex"):
            support_files.append(f.name)  # tikzlibrary 机制件硬抛 (e2e._scan_tree 同径)
            continue
        try:
            res = parse_file(f, flatten=False)
        except Exception as e:
            parse_fail.append(f"{f.relative_to(root)}: {e!r:.120}")
            continue
        if not file_has_prose(res.chunks):
            support_files.append(f.name)  # 无散文=support 件, 送译即腐蚀 (9bd8811 门)
            continue
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(
            chunk_to_in(c, chunk_id=f"{idx}:{c.id}", ph_map=res.ph_map)
            for c in res.chunks
        )
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
                "parse_fail": parse_fail,
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
    pipe = XlatPipeline(
        translator,
        config=cfg,
        state=state,
        validator=lambda s, z: validate_pair(s, z).feedback(),
    )
    results = await pipe.run(chunks)
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
        "parse_fail": parse_fail,
        "support_skipped": len(support_files),
        "warn_kinds": dict(sorted(warn_kinds.items())),
        "seconds": round(translate_s, 1),
        "src_chars": total_chars,
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
    t0 = time.monotonic()
    try:
        async with paper_sem:
            return await _xlat_one_inner(pid, out_dir, args, translator_factory, t0)
    except AuthTrippedError as e:
        # 篇内连续 auth-fail 熔断抛出 = 凭证死透——erb amain 同型：不收摊的
        # 话其后每篇只会各烧 auth_fail_threshold 块再 error（scout-e2ereal
        # §9）。落 error 格（retriable）+ auth_tripped 印，drive 见印即停；
        # 换凭证后同命令续跑。
        rec = sl.crash_rec(pid, "xlat", args.arm, e, t0)
        rec["auth_tripped"] = True
        return rec
    except Exception as e:  # 格子崩溃记 error 不炸整批（CancelledError 仍外抛）
        return sl.crash_rec(pid, "xlat", args.arm, e, t0)


async def _xlat_one_inner(
    pid: str, out_dir: Path, args: argparse.Namespace, translator_factory, t0: float
) -> dict:
    rec = sl.base_rec(pid, "xlat", args.arm)
    wid = sl.workdir(out_dir, pid)
    zh = wid / "zh"
    pj = wid / "parse.json"
    if not zh.is_dir() or not pj.exists():
        rec["status"] = "skip"
        rec["errors"] = [
            {
                "code": "no_parse_tree",
                "cat": "upstream",
                "payload": "zh/ or parse.json missing",
            }
        ]
        return sl.finish_rec(rec, t0)
    translator = translator_factory(pid)
    state_dir = wid / "xlat-state" / args.arm  # 臂间 state 隔离——mock 结果不回灌 real
    cfg = PipelineConfig(concurrency=args.concurrency)
    cap = benchlib.MAX_TOTAL_CHARS if args.arm == "real" else 0  # 配额闸只对真网关
    # 同 _parse_job staging-swap: 翻译写进暂存树, 完工换名 —— 期间 zh/
    # 保持上一版 (marker+内容一致), 并发 compile 不读半成品
    stage = wid / ".zh-xlat"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(zh, stage, ignore=benchlib.copytree_ignore())
    stats, results = await _translate_tree(
        stage, translator, state_dir, cfg, oversize_cap=cap
    )
    if stats.get("oversize"):
        shutil.rmtree(stage, ignore_errors=True)
        rec["status"] = "reject"
        rec["errors"] = [
            {
                "code": "oversize",
                "cat": "xlat",
                "payload": f"src_chars={stats['src_chars']}",
            }
        ]
        rec["metrics"]["translate"] = stats
        return sl.finish_rec(rec, t0)
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
                    "skipped": r.skipped,
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
    elif n_bad or stats["parse_fail"]:
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
