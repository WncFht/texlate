r"""specs/_xlat_async.py — async 翻译编排单源（原 ``stage_xlat.translate_tree_async``）。

扫描 → oversize 闸 → StateStore → XlatPipeline → 逐块对账 → splice 写回。
stagerun ``xlat``（``stage_xlat._translate_tree`` 壳）与
``e2e_real_bench.translate_tree`` 两臂共享；Phase-4 spec 化阶段经
``from specs._xlat_async import translate_tree_async`` 取同一实现，
不各抄一份。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import reconstruct
from texlate.pipecore import delivered
from texlate.pipecore import scan_tree as _scan_tree
from texlate.validate.l0 import pair_feedback
from texlate.xlat.pipeline import PipelineConfig, XlatPipeline
from texlate.xlat.resid import SweepOpts
from texlate.xlat.resid import sweep_tree as _resid_sweep_tree
from texlate.xlat.state import StateStore

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


async def translate_tree_async(
    root: Path,
    translator: object,
    state_dir: Path,
    cfg: PipelineConfig,
    *,
    oversize_cap: int = 0,
    glossary_fn: Callable | None = None,
    scan_fn: Callable | None = None,
    validator: Callable | None = None,
    post_run: Callable | None = None,
    cache: dict | None = None,
    resid_sweep: bool = False,
) -> tuple[dict, list]:
    """bench 两臂共享的 async 翻译编排体——``benchlib.translate_tree_async`` 候升位。

    ``e2e_real_bench.translate_tree`` 与本文件原 ``_translate_tree`` 的同构单源：
    扫描 → oversize 闸 → StateStore → XlatPipeline → 逐块对账 → splice 写回，
    恒返 ``(stats, results)``（e2e_real 弃 results 不用）。注入面全 kw-only：

    - ``glossary_fn(chunks) -> Glossary | None``：回调式术语表注入——
      ``Glossary.load`` 的 ``placeholders`` 要 post-scan chunks 经
      ``collect_doc_placeholders`` 算，调用方预计算即双扫，故按回调给。
    - ``post_run(pipe) -> None``：``pipe.run`` 后调一次——term_dict 落盘等
      要 ``pipe._doc_glossary``/``pipe.state`` 面的观测件由此接。
    - ``scan_fn``/``validator``：调用侧**显式**传自家模块全局
      （``scan_fn=_scan_tree``、``validator=lambda s,z: validate_pair(s,z)
      .feedback()``）——test_fuzz_scan_tree 的 ``_scan_spy`` monkeypatch
      缝靠 from-import 属性查找保活（同 e2e._translate_tree 注入格局）；
      缺省回退 ``_scan_tree``/``pair_feedback``（L0→str 适配单源）。
    - 交付谓词 ``pipecore.delivered``：``ok``+空译不回填 splice（旧式
      ``status=="ok" or (partial and zh)`` 会把块内容从 zh 树静默擦除），
      与产品臂 ``translate_tree_run`` 同口径。
    - 畸形 ``chunk_id`` 守备解析记 fault+bad_chunk_id 不炸整篇——
      续跑腐记录/translator 违约向量下比对拍裸解更稳（e2e_real 裸解形
      是已漂移副本，勿回抄）。
    - ``resid_sweep``：splice 写回后对 ``root`` 全部 ``.tex`` 跑保护区体
      残英清扫（``xlat.resid.sweep_tree``）——保护区体文不进 chunk 表
      （segmenter ``MINED_ONLY`` 口径），胞格散文/浮体说明永远留英，
      rexlat 结构性救不回；清扫在 root 全 ``.tex`` 面扫而非仅触块文件，
      覆盖零 chunk 的纯表 appendix。metrics 落 ``stats_d["resid_sweep"]``。
      复用同一 ``cache`` 桶（``resid_v1`` role 入键——span 缓存与
      chunk 缓存同桶不同名域），付费口径随调用方。
    """
    scans, chunks, fault_files, support_files = (scan_fn or _scan_tree)(root)
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
    pipe = XlatPipeline(
        translator,
        config=cfg,
        glossary=glossary_fn(chunks) if glossary_fn is not None else None,
        state=state,
        validator=validator or pair_feedback,
        cache=cache,
    )
    results = await pipe.run(chunks)
    if post_run is not None:
        post_run(pipe)
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
        if delivered(r):
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
    resid_m: dict | None = None
    if resid_sweep:
        resid_m = await _resid_sweep_tree(
            root,
            translator,
            SweepOpts(
                concurrency=cfg.concurrency,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            ),
            cache=cache,
        )
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
        # AuthGate 设计口径「跨论文熔断由调用方累计」（e2e_real 同款键）：
        # 整篇全 auth 败时 drive 连记 N 篇即收摊（篇内阈值块熔断走
        # AuthTrippedError 即停，本键兜篇均不足阈值块的慢速失血）。
        "auth_all_failed": pipe.auth_gate.all_failed,
    }
    if resid_m is not None:
        stats_d["resid_sweep"] = resid_m
    return stats_d, results
