"""``texlate.server`` 顶层共享件——app/routers 双侧消费的同口径小件。

首个入住件 ``slim_terminal_tasks``：``create_app`` retention loop 与
``POST /api/tasks/slim`` 端点的同一套终态瘦身扫描——两头曾各写一份
逐字节同构的循环（keep 白名单/keep_dirs/竞窗收窄口径漂移即双份维护
事故）。落点不选 ``store/_common``（其约定是「不依赖任何叶」的常量+
纯 FS 底料，async 编排进不去）也不选 ``worker/_common``（worker 域
内件，app/routers 拉它别扭）。轻依赖纪律同包 ``__init__``：只 import
``store``——本模块在 server extra 缺席时也应可 import。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from texlate.server.store import TERMINAL_STATUSES, slim_task_dir

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.server.store import Store

# 任务目录里的本地状态件：不是可服务产物（不进 files 表），但 sweep
# 必须留——reading.json 是用户阅读位置（删了每拍静默丢进度），
# seqpos.json 是 seq 对位缓存（删了 reader 首开重付 ~11s+ pypdf
# 重解析，撞上前端 15s 超时即 "signal timed out"）。
_TASK_LOCAL_KEEP = frozenset({"reading.json", "seqpos.json"})


async def slim_terminal_tasks(
    store: Store,
    tasks_dir: Path,
    *,
    skip: set[str],
    tenant: str | None = None,
    dry: bool = False,
) -> tuple[int, int]:
    """终态任务瘦身扫描 → ``(slimmed, freed_bytes)``。

    白名单 = files 表登记路径（``file_get`` 可服务面）+ ``_TASK_LOCAL_KEEP``
    本地状态件；产物/记录全留，done/partial 追加 ``zh``/``base`` 整树——
    单块重译（``_ensure_scans`` 重解析 base/ + resplice 写 zh/）与
    share 打包的 glossary 指纹都读活树。``dry=True`` 同口径只算不删——
    给 UI 出「约可释放 X」预估。

    ``skip`` = 调用方排除集（runner ``inflight_task_ids``）——retry
    竞窗靠它 + 逐任务状态复核收窄（复核→walk 间翻活只丢一拍窗口，
    下拍再瘦）。``slim_task_dir`` 的 rmtree 级重 I/O 逐任务
    ``to_thread`` 卸出 loop。
    """
    slimmed = 0
    freed = 0
    for tid in store.terminal_task_ids(tenant):
        if tid in skip:
            continue
        row = store.get(tid)
        if row is None or str(row["status"]) not in TERMINAL_STATUSES:
            continue
        keep = {
            str(rec["path"]) for rec in store.files(tid).values()
        } | _TASK_LOCAL_KEEP
        keep_dirs = ("zh", "base") if str(row["status"]) in ("done", "partial") else ()
        n = await asyncio.to_thread(
            slim_task_dir, tasks_dir / tid, keep, keep_dirs, dry=dry
        )
        if n:
            slimmed += 1
            freed += n
    return slimmed, freed
