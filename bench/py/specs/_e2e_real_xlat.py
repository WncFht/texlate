"""e2e_real xlat 段叶——断点水合 + 暂存翻译 → zh.-/state.-。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
from datetime import UTC, datetime

from kernel import fsutil, vault
from kernel import paid as paidmod

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs._shared import (
    PaidEscape,
    SessionClient,
    TimedTranslator,
    _gate,
    _last_done,
    _swap_in,
)
from specs._xlat_async import translate_tree_async
from texlate.compile.inject import classify_no_main, find_main_tex
from texlate.compile.normalize import normalize_project
from texlate.pipecore import scan_tree as _scan_tree
from texlate.validate.l0 import validate_pair
from texlate.xlat.pipeline import (
    AuthTrippedError,
    GatewayTranslator,
    PipelineConfig,
    RetryPolicy,
)

# ---------------------------------------------------------------- stage: xlat


def _xlat(ctx) -> dict:
    """暂存翻译 → zh.-/state.-；chunk 断点经 vault.restore 水合续跑。

    旧 ``pipe_xel_condition`` 的翻译段（copy→normalize→translate_tree），
    splice 写回在 translate_tree_async 内部完成；ctex 注入与编译判分在
    下游 compile stage。stats→status 映射见模块 docstring——
    fault|skipped>0 → error(retriable) 保 _paper_done 坏块重译语义。
    """
    paper = ctx.paper_dir()
    # 断点水合：state.-（及同凭证 zh/splice）从 vault 最优副本物化——
    # 缺席即 VaultError 静默，fresh 起步。restore 先于 asset_dir，让
    # StateStore 直接吃到旧 chunk 账。
    with contextlib.suppress(vault.VaultError):
        vault.restore(ctx.idc, ctx.arm, ctx.variant, paper, mode="copy")
    state_dir = ctx.asset_dir("state")

    src = ctx.src_path()
    if src is None:
        return _gate(
            "error", "no_extracted", "upstream", "lake cell unfetchable post-route"
        )
    rrec = _last_done(ctx, "route") or {}
    main_rel = (rrec.get("metrics") or {}).get("main_rel")
    staging = paper / ".xlat-stage"
    if staging.exists():
        shutil.rmtree(staging)
    fsutil.copy_mutating(src, staging)
    if not main_rel:
        found = find_main_tex(staging)
        if found is None:
            return _gate(
                "error", "no_main_tex", "upstream", classify_no_main(staging) or ""
            )
        main_rel = found.relative_to(staging).as_posix()

    metrics: dict = {"main_rel": main_rel, "engine": "xelatex"}
    metrics["normalize"] = normalize_project(staging, "xelatex", main_rel)

    session = ctx.gateway()
    if not ctx.params.get("no_probe"):
        session.probe_model()  # GatewayChat 无 probe_model → 门检后即 True
    client = SessionClient(session)
    translator = TimedTranslator(
        GatewayTranslator(
            client,
            str(ctx.params["model"]),
            policy=RetryPolicy(max_tries=int(ctx.params["max_tries"])),
        )
    )
    cfg = PipelineConfig(concurrency=int(ctx.params["concurrency"]))
    try:
        stats, results = asyncio.run(
            translate_tree_async(
                staging,
                translator,
                state_dir,
                cfg,
                oversize_cap=int(ctx.params["oversize_cap"]),
                scan_fn=_scan_tree,
                validator=lambda s, z: validate_pair(s, z).feedback(),
                resid_sweep=bool(ctx.params.get("resid_sweep")),
            )
        )
    except PaidEscape as e:
        # 拆舱：mid-flight 付费族异常原样交内核映射——绝不落成终态假账。
        raise e.orig from e
    except AuthTrippedError as e:
        # 篇内连续 auth-fail 熔断 = 凭证死透——PaidAbortCell 映
        # fail+auth_dead+auth_tripped。
        msg = f"{ctx.idc}: auth circuit tripped ({e})"
        raise paidmod.PaidAbortCell(msg) from e

    # req_timing 三分拆（soak 同口径注记：chat_s 含 paid_slot 排队）。
    stats["req_timing"] = {
        "calls": translator.calls,
        "chat_calls": client.chat_calls,
        "chat_s": round(client.chat_s, 1),
        "backoff_s": round(max(0.0, translator.span_s - client.chat_s), 1),
        "sem_wait_s": 0.0,
        "span_s": round(translator.span_s, 1),
    }
    metrics["translate"] = stats

    if stats.get("oversize"):
        shutil.rmtree(staging, ignore_errors=True)
        metrics["reject_at"] = "xlat"
        return _gate(
            "reject",
            "oversize",
            "xlat",
            f"src_chars={stats['src_chars']}",
            metrics,
        )

    # 逐块明细随 state.- 进 vault（triage/契约审计原料）。
    detail = state_dir / "xlat-detail.jsonl"
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

    n_bad = stats["fault"] + stats["skipped"]
    if stats["leftover_ph"] > 0:
        shutil.rmtree(staging, ignore_errors=True)
        return _gate("fail", "leftover_ph", "xlat", str(stats["leftover_ph"]), metrics)
    if n_bad:
        # retriable——坏块账在 state.-，续跑只重翻 fault/skipped 块
        # （_paper_done 同口径；「全坏」被本支吞掉属刻意：旧谓词同样
        # 重试，而 chunk state 让重试不重烧已成交块）。
        return _gate(
            "error",
            "chunks_retriable",
            "xlat",
            f"fault={stats['fault']} skipped={stats['skipped']}",
            metrics,
        )
    # 树可交付（ok/partial 路径）才落 zh.- + marker。
    (staging / ".xlat-arm.json").write_text(
        json.dumps(
            {
                "arm": ctx.arm,
                "model": str(ctx.params["model"]),
                "ts": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
    )
    zh = ctx.asset_dir("zh")
    _swap_in(staging, zh)
    if stats["partial"] or stats["fault_files"]:
        return _gate(
            "partial",
            "chunks_partial",
            "xlat",
            f"partial={stats['partial']} fault_files={stats['fault_files']}",
            metrics,
        )
    return {"status": "ok", "metrics": metrics}
