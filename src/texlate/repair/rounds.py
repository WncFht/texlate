"""repair.rounds — logfix 回灌阶梯叶 (repair 拆分叶).

``logfix_round`` 一轮骨架（归因 → 重译 → resplice → 重编 → 余孽
回落原文）+ 注入臂本体 ``retranslate_hits`` + resplice 写盘/对账簇
（``_resplice_and_diffs``/``_resplice``/``_slot_diffs``）。

叶子互引走全路径直跨（``texlate.repair.<叶>``），不经包门面。
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING

from texlate.compile.inject import InjectRejectError, prepare_chinese
from texlate.compile.judge import paired_slot_diff
from texlate.latex.reconstruct import (
    reconstruct,
    seq_mark_issues,
    strip_seq_marks,
)
from texlate.repair.attr import _attr_localize
from texlate.repair.runstate import split_cid
from texlate.textutil import env_flag
from texlate.textutil.osutil import ENV_NO_SEQ_MARKS

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import Any

    from texlate.compile.engine import CompRes
    from texlate.compile.judge import Verdict
    from texlate.repair.runstate import TreeRun

log = logging.getLogger(__name__)


async def retranslate_hits(
    run: TreeRun, hits: dict[str, dict[str, Any]], cap: int
) -> dict[str, Any]:
    """逐块重译（单发）+ 结果入账；返回报告 dict（``_`` 前缀内部键）。"""
    rep: dict[str, Any] = {
        "retranslated": [],
        "reverted_rules": [],
        "kept_transport_err": [],
        "over_cap": [],
    }
    changed: set[str] = rep.setdefault("_changed", set())
    adopted: set[str] = rep.setdefault("_adopted", set())
    tried = 0
    for cid, info in hits.items():
        if tried >= cap:
            rep["over_cap"].append(cid)
            continue
        ci = run.chunk_ins.get(cid)
        if ci is None:
            continue
        tried += 1
        fidx, ccid = split_cid(cid)
        loc = f"{info['file']}:{info['line']}" if info["line"] else info["file"]
        r = await run.pipe.retranslate_chunk(ci, f"{info['head']}\n(at {loc})")
        if r is None:
            rep["kept_transport_err"].append(cid)
            continue
        if r.status == "ok":
            run.trans.setdefault(fidx, {})[ccid] = r.translation
            rep["retranslated"].append(cid)
            adopted.add(cid)
        else:
            # 重译产物仍不过 rules → 回落原文（spec: 再不过 → fallback 原文）
            run.trans.get(fidx, {}).pop(ccid, None)
            rep["reverted_rules"].append(cid)
        changed.add(cid)
    return rep


def _resplice_and_diffs(  # noqa: PLR0913 -- 注入面穿透（写盘/diff/锚三臂缝）
    run: TreeRun,
    work: Path,
    main_rel: str,
    fidxs: set[int],
    *,
    diffs: bool = True,
    seq_marks: bool | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """受影响文件 reconstruct 重写 + 写入即 ``paired_slot_diff`` 对账（单遍）。

    diff 取**注入前**在手 ``zh``——``res.vtex`` 对重建体的干净口径
    （``pipecore.translate_tree_run`` 同形）：主文件的 ``prepare_chinese``
    注入不污染 notes（旧盘后重读会把 demote/inject 改写面记成机位差）。
    ``prepare_chinese`` 重跑补 ctex 在全量写+diff 之后；注入后树级审计
    由 ``machine_slot_audit``（judge）覆盖。``diffs=False`` 跳过对账
    （``_resplice`` 写盘臂——调用方另走 ``_slot_diffs`` 盘后真值口径，
    在手 diff 算了也丢）。``seq_marks`` 三态：None → ``TEXLATE_NO_SEQ_MARKS``
    env 决议（缺省开）；重烘焙产物与 ``_build_zh`` 同 seq 口径
    （``sum(len(chunks) for j < fidx)`` 基址）自动补锚，失衡即剥降级。
    """
    marks_on = (
        not env_flag(ENV_NO_SEQ_MARKS, default=False)
        if seq_marks is None
        else seq_marks
    )
    main_path = work / main_rel
    rewritten: list[str] = []
    diff_map: dict[str, list[str]] = {}
    touched_main = False
    for fidx in sorted(fidxs):
        f, res = run.scans[fidx]
        seq0 = sum(len(run.scans[j][1].chunks) for j in range(fidx))
        zh = reconstruct(
            res,
            run.trans.get(fidx) or {},
            mark_seq0=seq0 if marks_on else None,
            mark_moving=marks_on,
        )
        if marks_on and (issues := seq_mark_issues(zh)):
            log.warning(
                "seq marks imbalanced in %s (%s); stripped", f, "; ".join(issues)
            )
            zh = strip_seq_marks(zh)
        f.write_text(zh, encoding="utf-8", newline="")
        rel = f.relative_to(work).as_posix()
        rewritten.append(rel)
        if diffs and (notes := paired_slot_diff(res.vtex, zh, rel)):
            diff_map[rel] = notes
        touched_main = touched_main or f == main_path
    if touched_main:
        # 首注已过——同文件重注不会再触发 \documentstyle 拒绝
        with suppress(InjectRejectError):
            prepare_chinese(work, main_rel)
    return rewritten, diff_map


def _resplice(
    run: TreeRun,
    work: Path,
    main_rel: str,
    fidxs: set[int],
    *,
    seq_marks: bool | None = None,
) -> list[str]:
    """受影响文件 reconstruct 重写；主文件重跑 ``prepare_chinese`` 补 ctex。

    ``_resplice_and_diffs`` 的写盘臂（worker ``_retr_resplice`` 旧签名档——
    其 ``_slot_diffs`` 盘后读回保留注入后磁盘真值口径，在手 diff 臂
    ``diffs=False`` 跳过不算）。
    """
    return _resplice_and_diffs(
        run, work, main_rel, fidxs, diffs=False, seq_marks=seq_marks
    )[0]


def _slot_diffs(run: TreeRun, work: Path, fidxs: set[int]) -> dict[str, list[str]]:
    """``_resplice`` 落盘 zh 对 ``res.vtex`` 的机位配对 diff——重写后逐文件对账。

    盘后读回 = 注入后磁盘真值口径（worker ``_retr_resplice`` 消费位）；
    ``logfix_round`` 内面走 ``_resplice_and_diffs`` 的注入前在手 zh 口径。
    """
    out: dict[str, list[str]] = {}
    for fidx in sorted(fidxs):
        f, res = run.scans[fidx]
        rel = f.relative_to(work).as_posix()
        if notes := paired_slot_diff(res.vtex, f.read_text(encoding="utf-8"), rel):
            out[rel] = notes
    return out


def logfix_round(  # noqa: C901, PLR0913 -- 阶梯直铺：钩子面穿透两臂同一契约
    run: TreeRun,
    work: Path,
    main_rel: str,
    res: CompRes,
    cap: int,
    *,
    retranslate: Callable[[TreeRun, dict[str, dict[str, Any]], int], dict[str, Any]],
    recompile: Callable[[], tuple[CompRes, Verdict]],
    checkpoint: Callable[[], None] | None = None,
    baseline_sigs: set[str] | None = None,
    seq_marks: bool | None = None,
) -> tuple[dict[str, Any], CompRes, Verdict | None]:
    """Logfix 回灌一轮骨架：归因 → 重译 → resplice → 重编 → 余孽回落原文。

    ``retranslate``/``recompile`` 两臂注入——e2e 包 ``run.drive(
    retranslate_hits)``（翻译期 loop 复用，见 ``TreeRun.loop``）+
    ``_compile_judge``（tail dict 臂侧合成）；
    worker 包 client aclose 同 loop 纪律 + ``eng.compile``+``judge``。
    ``checkpoint`` 是 cancel 轮询点（worker ``_abort_if_cancelled``
    同位三处：重译前/后、首编后），缺省无操作。
    ``baseline_sigs`` 是 en 基线错误标记集（``err_signatures`` 快照）——
    命中判源生错不进归因面；两轮 localize（首归因 + 重编后余孽检测）
    同口径过滤。``seq_marks`` 透传 ``_resplice_and_diffs``（None → env
    决议）。返回 (logfix 报告，最新 CompRes, 新 Verdict 或 None=未重编)。
    """
    rep: dict[str, Any] = {"enabled": True, "cap": cap}
    hits, n_err = _attr_localize(work, run, res, baseline_sigs=baseline_sigs)
    rep["errors"] = n_err
    rep["hits"] = hits
    last_res = res
    if not hits:
        rep["note"] = "no chunk-level attribution"
        return rep, last_res, None
    if checkpoint is not None:
        checkpoint()
    retr = retranslate(run, hits, cap)
    if checkpoint is not None:
        checkpoint()
    changed: set[str] = retr.pop("_changed")
    adopted: set[str] = retr.pop("_adopted")
    rep.update(retr)
    if not changed:
        rep["note"] = "no chunk changed"
        return rep, last_res, None

    fidxs = {split_cid(c)[0] for c in changed}
    rep["rewritten"], diffs = _resplice_and_diffs(
        run, work, main_rel, fidxs, seq_marks=seq_marks
    )
    if diffs:
        rep["slot_diffs"] = diffs
    res2, v2 = recompile()
    if checkpoint is not None:
        checkpoint()
    last_res = res2
    rep["recompiled"] = v2.status
    if v2.status == "clean":
        return rep, last_res, v2

    # 重编仍不过：本轮"重译过且仍被点名"的块回落原文；
    # 其余归因（含已回落原文仍犯错的——那是源级问题）记名留 fixloop。
    hits2, _ = _attr_localize(work, run, res2, baseline_sigs=baseline_sigs)
    still_bad = sorted(set(hits2) & adopted)
    rep["fallback_src"] = still_bad
    rep["unresolved"] = sorted(set(hits2) - adopted)
    if still_bad:
        for cid in still_bad:
            fidx, ccid = split_cid(cid)
            run.trans.get(fidx, {}).pop(ccid, None)
        fb_fidxs = {split_cid(c)[0] for c in still_bad}
        rep["fallback_rewritten"], fb_diffs = _resplice_and_diffs(
            run, work, main_rel, fb_fidxs, seq_marks=seq_marks
        )
        if fb_diffs:
            rep["fallback_slot_diffs"] = fb_diffs
        # 回落态即交付树——补一次裸编：fixloop 关/崩/reject 时不再有
        # 代验兜底，zh-src.zip 不能装未验证树（audit fallback_unverified）
        res3, v3 = recompile()
        rep["fallback_verdict"] = v3.status
        last_res, v2 = res3, v3
    return rep, last_res, v2
