"""soak xlat 段叶——zh.- → .zh-xlat 翻译 → swap_in + state.- 明细 + marker。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
from datetime import UTC, datetime

from kernel import fsutil
from kernel import paid as paidmod

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs import _qmetrics as qp
from specs._shared import (
    DEFAULT_BASE_URL,
    PaidEscape,
    SessionClient,
    TimedTranslator,
    _ensure_kind,
    _gate,
    _swap_in,
)
from specs._xlat_async import translate_tree_async
from texlate.pipecore import delivered
from texlate.pipecore import scan_tree as _scan_tree
from texlate.validate.l0 import validate_pair
from texlate.xlat.glossary import LOCAL_GLOSSARY_NAME, Glossary
from texlate.xlat.pipeline import (
    AuthTrippedError,
    GatewayTranslator,
    PipelineConfig,
    RetryPolicy,
)
from texlate.xlat.prompts import PROMPT_VERSION

# ---------------------------------------------------------------- stage: xlat
#
# SessionClient/TimedTranslator/SessionTranslator/PaidEscape 单源在
# specs/_shared.py——e2e_real/qualbench 复用同一桥。


def _xlat(ctx) -> dict:
    """zh.- → .zh-xlat 暂存翻译 → swap_in + state.- 明细 + marker。

    全程「真网关」语义（soak 即 real 臂）：术语表注入 + term/leak 指标
    恒开；oversize_cap 恒生效（配额闸）。
    """
    zh = _ensure_kind(ctx, "zh")
    if zh is None or not (zh / "parse.json").exists():
        return _gate(
            "skip", "no_parse_tree", "upstream", "zh.-/ or zh.-/parse.json missing"
        )
    cat_group = ctx.cell.get("cat_group") or ""
    src = ctx.src_path()  # local 术语层锚（glossary.local.yaml 在论文树）
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
    seg = ctx.seg_cache(
        prompt_version=PROMPT_VERSION,
        base_url=DEFAULT_BASE_URL,
        model=str(ctx.params["model"]),
        lang="zh",
        glossary=cat_group,
    )

    def _glossary_fn(chunks: list) -> Glossary:
        return Glossary.load(
            user_path=qp._NO_USER_GLOSSARY,
            local_path=(src / LOCAL_GLOSSARY_NAME) if src else None,
            categories=[cat_group],
        )

    def _post_run(pipe) -> None:
        if pipe.state is None:
            return
        # term_dict 落盘（state.-/term_dict.json）——观测件不毁账。
        with contextlib.suppress(Exception):
            pipe.state.save_maps(term_dict=pipe._doc_glossary)

    state_dir = ctx.asset_dir("state")
    staging = ctx.paper_dir() / ".zh-xlat"
    if staging.exists():
        shutil.rmtree(staging)
    fsutil.copy_mutating(zh, staging)

    try:
        stats, results = asyncio.run(
            translate_tree_async(
                staging,
                translator,
                state_dir,
                cfg,
                oversize_cap=int(ctx.params["oversize_cap"]),
                glossary_fn=_glossary_fn,
                scan_fn=_scan_tree,
                validator=lambda s, z: validate_pair(s, z).feedback(),
                post_run=_post_run,
                cache=seg,
                resid_sweep=bool(ctx.params.get("resid_sweep")),
            )
        )
    except PaidEscape as e:
        # 拆舱：mid-flight 付费族异常（PAUSE 中启/abort/budget/越闸
        # PaidAbortCell）原样交内核映射——绝不落成终态 fail 假账。
        raise e.orig from e
    except AuthTrippedError as e:
        # 篇内连续 auth-fail 熔断 = 凭证死透——PaidAbortCell 映
        # fail+auth_dead+auth_tripped（旧 error→fail 改判对拍单列）。
        msg = f"{ctx.idc}: auth circuit tripped ({e})"
        raise paidmod.PaidAbortCell(msg) from e

    # req_timing 三分拆（口径注记：chat_s = session.request 全程含
    # paid_slot 排队——旧「纯 HTTP 时延」义不存在于 session 桥；
    # backoff_s = GatewayTranslator span − 线时；sem_wait_s 恒 0，
    # 全局闸角色由 paid_slot 顶掉且其等待计入 chat_s）。
    stats["req_timing"] = {
        "calls": translator.calls,
        "chat_calls": client.chat_calls,
        "chat_s": round(client.chat_s, 1),
        "backoff_s": round(max(0.0, translator.span_s - client.chat_s), 1),
        "sem_wait_s": 0.0,
        "span_s": round(translator.span_s, 1),
    }

    metrics = {"translate": stats}
    if stats.get("oversize"):
        shutil.rmtree(staging, ignore_errors=True)
        return _gate(
            "reject",
            "oversize",
            "xlat",
            f"src_chars={stats['src_chars']}",
            metrics,
        )

    # 逐块明细（triage/契约审计原料）——随 state.- 进 vault。
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
    _swap_in(staging, zh)

    stats.update(qp.scan_leak([(r.chunk_id, r.source or "") for r in results]))
    delivered_rows = [
        (r.chunk_id, r.source or "", r.translation or "")
        for r in results
        if delivered(r)
    ]
    try:
        td = qp.rebuild_term_dict(
            cat_group or None,
            [s for _c, s, _t in delivered_rows],
            (src / LOCAL_GLOSSARY_NAME) if src else None,
        )
        stats.update(qp.score_terms(delivered_rows, td))
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

    n_bad = stats["fault"] + stats["skipped"]
    if stats["leftover_ph"] > 0:
        return _gate("fail", "leftover_ph", "xlat", str(stats["leftover_ph"]), metrics)
    if stats["chunks"] and n_bad == stats["chunks"]:
        return _gate("fail", "all_chunks_bad", "xlat", str(stats["chunks"]), metrics)
    if n_bad or stats["fault_files"]:
        return _gate(
            "partial",
            "chunks_bad",
            "xlat",
            f"fault={stats['fault']} skipped={stats['skipped']}",
            metrics,
        )
    return {"status": "ok", "metrics": metrics}
