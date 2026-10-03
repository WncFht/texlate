"""server.sweep — 产物清扫/保留策略簇（自 ``app.py`` 拆出的后台维护叶）。

启动段 ``_sweep_orphan_task_dirs``（建行前落盘残骸孤儿目录清扫）
+ 周期段 ``sweep_once``/``retention_loop``（终态瘦身 ``_slim_terminal``
+ retention 淘汰 ``_sweep_delete``）。本叶不依赖 fastapi——``texlate.server``
轻依赖纪律同 ``store``/``settings`` 面，惰性装载下可直 import。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from contextlib import suppress
from typing import TYPE_CHECKING

from texlate.server._common import slim_terminal_tasks
from texlate.server.store import (
    ACTIVE_STATUSES,
    Store,
    valid_task_id,
)
from texlate.server.store._common import _dir_size, _retention_drop_order

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.server.settings import SettingsStore
    from texlate.server.worker import TaskRunner

log = logging.getLogger(__name__)


def _sweep_orphan_task_dirs(store: Store, root: Path) -> int:
    """启动清扫：``tasks/{id}`` 无对应 DB 行的孤儿目录 → 清扫数。

    upload/share_import 在建行前落盘 blob——进程在写盘与 INSERT 之间
    被杀会留孤儿目录。只在启动窗口跑（尚无并发建行）；名字非法或不
    是 task-id 形态的条目不碰。
    """
    tasks_root = root / "tasks"
    if not tasks_root.is_dir():
        return 0
    known = set(store.task_ids())
    n = 0
    for d in tasks_root.iterdir():
        if not (valid_task_id(d.name) and d.name not in known):
            continue
        if d.is_dir() and not d.is_symlink():
            shutil.rmtree(d, ignore_errors=True)
        else:
            with suppress(OSError):
                d.unlink()
        n += 1
    return n


async def _slim_terminal(store: Store, runner: TaskRunner, tasks_dir: Path) -> None:
    """瘦身段（无条件）：终态任务 ``tasks/{id}/`` 清未登记字节。

    扫描体单源在 ``server/_common.slim_terminal_tasks``（与
    ``POST /api/tasks/slim`` 同口径）；本段只管 sweep 语义——
    不区分 tenant（本地库即全集），瘦出量进 log。
    """
    slimmed, slim_freed = await slim_terminal_tasks(
        store, tasks_dir, skip=runner.inflight_task_ids()
    )
    if slimmed:
        log.info("slim sweep: %d task(s), freed %d B", slimmed, slim_freed)


async def _sweep_delete(  # noqa: C901 -- 两阶段淘汰阶梯平铺
    store: Store, settings_store: SettingsStore, tasks_dir: Path
) -> None:
    """删除段：``retention_days``/``retention_max_gb`` 淘汰整任务（全 0 = 关）。

    retention 淘汰的 loop-native 实现——决策查询（``TaskRepo``
    单侧化）+ ``delete_task_guard`` 条件写留在 loop，``_dir_size``/
    ``rmtree`` 重 I/O 逐段 ``to_thread``；阶段二淘汰序/剪停判定单源
    ``_retention_drop_order``。settings 每拍重读（PUT 即生效，不用重启）。
    """
    st = settings_store.load()
    days = int(st.get("retention_days") or 0)
    max_gb = int(st.get("retention_max_gb") or 0)
    if days <= 0 and max_gb <= 0:
        return
    removed: list[str] = []
    freed_bytes = 0

    async def _drop(tid: str) -> int:
        """条件删行（loop）+ rmtree（thread）→ 目录字节数。"""
        if not store.delete_task_guard(tid, blocked=ACTIVE_STATUSES):
            return 0
        sz = await asyncio.to_thread(_dir_size, tasks_dir / tid)
        await asyncio.to_thread(shutil.rmtree, tasks_dir / tid, ignore_errors=True)
        removed.append(tid)
        return sz

    if days > 0:
        cutoff = time.time() - days * 86400
        for tid in store.retention_candidates(cutoff):
            freed_bytes += await _drop(tid)
    if max_gb > 0:
        cap = max_gb * (1 << 30)
        total = await asyncio.to_thread(_dir_size, tasks_dir)
        if total > cap:
            order = _retention_drop_order(
                store.terminal_oldest_first(),
                total_bytes=total,
                cap_bytes=cap,
            )
            try:
                tid = next(order)
                while True:
                    sz = await _drop(tid)
                    freed_bytes += sz
                    tid = order.send(sz)
            except StopIteration:
                pass
    if removed:
        log.info(
            "retention sweep: %s",
            {"removed": removed, "freed_bytes": freed_bytes},
        )


async def sweep_once(
    store: Store,
    settings_store: SettingsStore,
    runner: TaskRunner,
    tasks_dir: Path,
) -> None:
    """Retention sweep 一拍：终态瘦身 + 保留策略淘汰（可测单元）。"""
    await _slim_terminal(store, runner, tasks_dir)
    await _sweep_delete(store, settings_store, tasks_dir)


async def retention_loop(
    store: Store,
    settings_store: SettingsStore,
    runner: TaskRunner,
    tasks_dir: Path,
) -> None:
    """产物保留策略周期 sweep（每 10min 一拍：瘦身 + retention 删除）。

    失败只 log——保留策略是后台清扫面，故障绝不拖垮服务。
    """
    while True:
        await asyncio.sleep(600)
        try:
            await sweep_once(store, settings_store, runner, tasks_dir)
        except Exception as e:  # noqa: BLE001 -- 后台清扫失败只留 warning
            log.warning("retention sweep failed: %s", e)
