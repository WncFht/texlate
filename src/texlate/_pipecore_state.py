"""``texlate._pipecore_state`` — 状态空间映射 + 注入协议契约叶（``pipecore`` 拆分叶）。

pipe 空间（``ok/partial/skipped/fault``）↔ DB 空间
（``ok/fallback_orig/failed``）双向映射 + 两空间 delivered 谓词；编译
回环 ``CompileRunner`` 协议与修复链实况/日志出口 ``ReportSink``
（worker 绑 ``_log``/``_repair_event``；e2e/bench 挂 ``NULL_SINK``
零事件面）在本叶定址。

门面回引名单见 ``texlate.pipecore._LEAF_EXPORTS``。
monkeypatch 锚点：setattr patch 须指本叶，指门面无效。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from texlate.compile.engine import CompRes
    from texlate.compile.judge import Verdict
    from texlate.xlat.pipeline import ChunkResult

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
