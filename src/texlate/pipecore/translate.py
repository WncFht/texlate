"""``texlate.pipecore.translate`` — 全树翻译写回脊叶（``pipecore`` 拆分叶）。

``translate_tree_run``：``scan_fn``（缺省本叶 ``scan_tree`` 全局——patch
锚随件迁指本叶）→ ``XlatPipeline`` 逐块翻译 → env 可译性判
（``_env_judge_pass``）→ splice 写回 + seq 注锚 + slot/emit 哨兵对账。
``_auto_glossary_fn`` 是 ``pipecore.scan.auto_glossary_fn`` 的
translator 取件糖。注入面（scan/validator/translator/sink）保住各臂
模块全局 monkeypatch 缝——e2e 别名绑定、worker ``seams.*`` 直传。

门面回引名单见 ``texlate.pipecore._LEAF_EXPORTS``。
monkeypatch 锚点：setattr patch 须指本叶，指门面无效。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from texlate.compile.judge import paired_slot_diff
from texlate.latex.reconstruct import (
    reconstruct,
    seq_mark_issues,
    splice_emit_issues,
    strip_seq_marks,
)
from texlate.pipecore.policy import _opt_switch
from texlate.pipecore.scan import auto_glossary_fn, scan_tree
from texlate.pipecore.state import NULL_SINK, delivered
from texlate.repair_l2 import (
    TreeRun,
    env_judge_all,
    split_cid,
    unknown_env_of,
)
from texlate.textutil import PH_RX
from texlate.textutil.osutil import ENV_NO_SEQ_MARKS
from texlate.validate.l0 import pair_feedback
from texlate.xlat.client import DEFAULT_MODEL
from texlate.xlat.glossary import Glossary
from texlate.xlat.pipeline import (
    MockTranslator,
    PipelineConfig,
    XlatPipeline,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from texlate.chunk import ChunkIn
    from texlate.latex.model import Chunk, ScanResult
    from texlate.pipecore.state import ReportSink
    from texlate.xlat.pipeline import ChunkResult, Translator

log = logging.getLogger(__name__)


def _auto_glossary_fn(
    translator: Translator | None,
) -> Callable[[list[str]], Awaitable[dict[str, str]]] | None:
    """取 translator 的 ``.client``/``.model`` 转调 ``auto_glossary_fn`` 的装配糖。

    MockTranslator/无 client 注入件 → ``None``（mock/bench 路径不打网关）。
    抽取臂沿用翻译同模（BYOK 端点模型名网关私有，硬编公网名会 404）。
    """
    return auto_glossary_fn(
        getattr(translator, "client", None),
        str(getattr(translator, "model", "") or DEFAULT_MODEL),
    )


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
        glossary=Glossary.load(),
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
            mark_moving=marks_on,
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
        # emit 哨兵（splice_emit_verifier 项）：花括净深背离/环境配对崩坏/
        # 交付译文 <90% 逐字在场/U+FFFD+C1 mojibake——note 并入 slot_diffs
        # 对账通道，只报不拦。
        if emit_notes := splice_emit_issues(res.vtex, zh, trans, rel):
            slot_diffs.setdefault(rel, []).extend(emit_notes)
            log.warning("emit splice issues in %s: %s", rel, "; ".join(emit_notes[:8]))
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
