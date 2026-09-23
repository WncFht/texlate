"""SQLite 任务库（web-layer.md §3.2 DDL + §3.3 状态机 + §3.4 断点恢复）。

单写者连接：所有写走创建线程（uvicorn loop 线程），
``PRAGMA journal_mode=WAL; busy_timeout=5000; synchronous=NORMAL``。
``task_events`` 落盘即 SSE 重放凭据（``Last-Event-ID`` → ``events_since``）。

包布局：``_common`` 持 DDL/迁移/状态机枚举单源；``_tasks``/``_chunks``/
``_files``/``_cache``/``_events``/``_usage`` 六个聚合 repo 共享门面同一
连接（构造只回指 Store，conn 惰性经 ``store.conn`` 取）。``Store`` 留
组合门面：连接生命周期 + 跨聚合编排（``flush_chunk_batch``/``snapshot``
+ ``sweep_retention``——``app._sweep_delete`` 的同步孪生，生产走
loop-native 版，本函数仅测试面在用），其余 ``store.X`` 一律经
``__getattr__`` 透传到对应 repo——调用面/私有名/monkeypatch 实例遮蔽
语义全保。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from typing import TYPE_CHECKING, Any

from texlate.server.store._cache import CacheRepo
from texlate.server.store._chunks import ChunkRepo
from texlate.server.store._common import (
    _COLUMN_MIGRATIONS,
    _POST_DDL,
    _SNAPSHOT_OPTS_DROP,
    ACTIVE_STATUSES,
    CHUNKS_PAGE_MAX,
    DDL,
    ERROR_CODES,
    EVENT_CAP,
    RETRYABLE_FROM,
    STAGES,
    TERMINAL_STATUSES,
    StoreError,
    TransitionError,
    _dir_size,
    new_task_id,
    slim_task_dir,
    valid_task_id,
)
from texlate.server.store._events import EventRepo
from texlate.server.store._files import FileRepo
from texlate.server.store._kept import KeptRepo
from texlate.server.store._tasks import TaskRepo
from texlate.server.store._usage import UsageRepo

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "ACTIVE_STATUSES",
    "CHUNKS_PAGE_MAX",
    "DDL",
    "ERROR_CODES",
    "EVENT_CAP",
    "RETRYABLE_FROM",
    "STAGES",
    "TERMINAL_STATUSES",
    "Store",
    "StoreError",
    "TransitionError",
    "new_task_id",
    "slim_task_dir",
    "valid_task_id",
]


def row_json(row: dict[str, Any], key: str) -> dict[str, Any]:
    """任务行 ``*_json`` 文本列容错反序列化——坏 JSON/非 dict 一律 ``{}``。

    ``options_json``/``config_json`` 列共享口径：行可经直写腐化，单格
    坏值不许拖垮消费点（snapshot/retry/share 打包/worker 同款防护）。
    """
    try:
        data = json.loads(str(row.get(key) or "{}"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class Store:
    """单写者 SQLite 封装 + 聚合 repo 组合门面。``open()`` 必须在 loop 线程调一次。"""

    def __init__(self, path: Path) -> None:
        """Path = texlate.db 路径（父目录由调用方建）。"""
        self.path = path
        self._conn: sqlite3.Connection | None = None
        #: 段缓存命中记账缓冲 ``{key: 待加次数}``——``cache_get`` 不逐命中
        #: commit（翻译热环每命中一 fsync 划不来），聚合后由
        #: ``flush_chunk_batch`` 事务顺带落 / 兜底阈值 / ``close`` 冲刷。
        self._cache_hits: dict[str, int] = {}
        self._tasks = TaskRepo(self)
        self._chunks = ChunkRepo(self)
        self._files = FileRepo(self)
        self._cache = CacheRepo(self, self._cache_hits)
        self._events = EventRepo(self)
        self._usage = UsageRepo(self)
        self._kept = KeptRepo(self)

    def __getattr__(self, name: str) -> object:
        """``store.X`` 透传：未命中门面本体时按序查聚合 repo。

        只在常规查找失败时触发——门面实属性（``conn``/``path``/
        ``_cache_hits``/各 ``_*Repo``）与 monkeypatch 的实例遮蔽
        （``setattr(store, "get", ...)``）一律优先，调用面语义不变。
        """
        for key in (
            "_tasks",
            "_chunks",
            "_files",
            "_cache",
            "_events",
            "_usage",
            "_kept",
        ):
            repo = self.__dict__.get(key)
            if repo is not None and hasattr(repo, name):
                return getattr(repo, name)
        msg = f"{type(self).__name__!r} object has no attribute {name!r}"
        raise AttributeError(msg)

    # ------------------------------------------------------------ 连接

    def open(self) -> None:
        """建连 + DDL 幂等执行。重复调用安全。"""
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(DDL)
        self._migrate(conn)
        self._conn = conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """列级迁移 + 迁移列索引：探测缺失才 ALTER/回填（幂等）。"""
        for table, column, ddl, backfill in _COLUMN_MIGRATIONS:
            cols = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(ddl)
                if backfill is not None:
                    conn.execute(backfill)
        conn.executescript(_POST_DDL)
        conn.commit()

    def close(self) -> None:
        """关连接——挂起的缓存命中记账先尽力落盘（丢得起，不炸关停）。"""
        if self._conn is None:
            return
        self._drain_cache_hits()
        conn, self._conn = self._conn, None
        conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        """已开连接；未 open 直接断言（内部约定，非用户输入）。"""
        assert self._conn is not None  # noqa: S101 -- open() 前置是类内契约
        return self._conn

    # ------------------------------------------------------------ 跨聚合编排

    def flush_chunk_batch(
        self,
        task_id: str,
        updates: list[tuple[str, dict[str, Any]]],
        cache_puts: list[tuple[str, str, str, str]],
        counters: dict[str, int],
    ) -> None:
        """块级落盘事务（§3.4.2）：chunk 更新 + 段缓存写入 + 计数器一笔。

        ``updates``: [(chunk_id, {status, translation, error_code, attempts})]
        ``cache_puts``: [(key, translation, model, target_lang)]
        """
        conn = self.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            for chunk_id, fields in updates:
                self.update_chunk(task_id, chunk_id, fields)
            self.cache_put_batch(cache_puts)
            self._flush_cache_hits()
            self._set_fields(
                task_id,
                {
                    "total_chunks": counters.get("total", 0),
                    "done_chunks": counters.get("done", 0),
                    "cached_chunks": counters.get("cached", 0),
                    "failed_chunks": counters.get("failed", 0),
                    "tokens": counters.get("tokens", 0),
                    "progress": counters.get("progress", 0),
                },
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def sweep_retention(
        self, tasks_dir: Path, *, max_age_s: float, max_total_bytes: int
    ) -> dict[str, Any]:
        """产物 GC（两阶段；``0`` 关闭对应阶段；``ACTIVE`` 任务永不删）。

        阶段一（``max_age_s > 0``）：终态且 ``COALESCE(finished_at,
        updated_at)`` 早于 ``now - max_age_s`` 的任务删行 + ``tasks/{id}/``
        目录。阶段二（``max_total_bytes > 0``）：清后 ``tasks_dir`` 总字节
        仍超限，剩余终态任务按完成时间 oldest-first 继续删到达标或候选
        穷尽——目录不在库内的孤儿条目只计入总量、不由本函数删（启动期
        ``_sweep_orphan_task_dirs`` 的职责）。

        删序先行后目录：中途被杀留孤儿目录（启动清扫可回收），不留
        「行在而产物蒸发」的假活任务。返回 ``{"removed": [id...],
        "freed_bytes": n}``。

        rmtree/目录遍历是重 I/O——本函数在调用方线程同步跑，调用方
        （loop 线程）应 ``to_thread`` 卸载。``share_dir``/``index.jsonl``
        不在本函数范围。

        生产面由 ``app._sweep_delete``（loop-native 版）持有同语义——
        ``_drop`` 同走 ``delete_task_guard(blocked=ACTIVE_STATUSES)``
        条件删：候选枚举到执行间被 retry 回 ``queued`` 的任务当场拒删，
        不许闸漂移。
        """
        removed: list[str] = []
        freed = 0

        def _drop(tid: str) -> int:
            """条件删行 + rmtree 目录 → 目录字节数（无效/在飞 id 拒动返 0）。"""
            if not valid_task_id(tid):
                return 0
            if not self.delete_task_guard(tid, blocked=ACTIVE_STATUSES):
                return 0
            sz = _dir_size(tasks_dir / tid)
            shutil.rmtree(tasks_dir / tid, ignore_errors=True)
            removed.append(tid)
            return sz

        if max_age_s > 0:
            for tid in self.retention_candidates(time.time() - max_age_s):
                freed += _drop(tid)
        if max_total_bytes > 0:
            total = _dir_size(tasks_dir)
            if total > max_total_bytes:
                for tid in self.terminal_oldest_first():
                    if total <= max_total_bytes:
                        break
                    sz = _drop(tid)
                    freed += sz
                    total -= sz
        return {"removed": removed, "freed_bytes": freed}

    # ------------------------------------------------------------ snapshot

    def snapshot(self, task_id: str, *, artifacts: dict[str, str]) -> dict[str, Any]:
        """§2.2 snapshot schema：任务行 + counters + error + artifacts + last_seq。"""
        row = self.get(task_id)
        if row is None:
            return {}
        # error_json 列可经直写腐化——坏 JSON/非 dict 按「无错」None 收，
        # 不许单格坏值 500 掉 SSE bootstrap 端点（row_json 同款容错口径）
        error_raw = row.get("error_json")
        try:
            err_obj = json.loads(error_raw) if error_raw else None
        except json.JSONDecodeError:
            err_obj = None
        error = err_obj if isinstance(err_obj, dict) else None
        snap: dict[str, Any] = {
            "task_id": row["id"],
            "kind": row["kind"],
            "status": row["status"],
            "progress": int(row["progress"]),
            "message": row["message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "counters": {
                "total": int(row["total_chunks"]),
                "done": int(row["done_chunks"]),
                "cached": int(row["cached_chunks"]),
                "failed": int(row["failed_chunks"]),
                "tokens": int(row["tokens"]),
            },
            "warnings": self._warnings(task_id),
            "error": error,
            "artifacts": artifacts,
            "last_seq": self.last_seq(task_id),
        }
        usage = self.usage_for(task_id)
        if usage is not None:
            snap["usage"] = usage
        if row["stage"]:
            snap["stage"] = row["stage"]
        for opt_key, snap_key in (
            ("title", "title"),
            ("arxiv_id", "arxiv_id"),
            ("target_lang", "target_lang"),
            ("model", "model"),
        ):
            if row.get(opt_key):
                snap[snap_key] = row[opt_key]
        if row["status"] == "queued":
            # 排队位次（1 基）= queued_rows 序（created_at,id 升序）内位置；
            # header 凭证行不进 replay 队列（queued_rows 排除口径）——
            # 不在序内的行字段缺席而非 null（前端按「字段缺席」渲染）
            ids = [str(r["id"]) for r in self.queued_rows()]
            if task_id in ids:
                snap["queue_position"] = ids.index(task_id) + 1
        self._snapshot_user_fields(row, snap)
        return snap

    @staticmethod
    def _snapshot_user_fields(row: dict[str, Any], snap: dict[str, Any]) -> None:
        """用户入参 options/glossary 回显（前端 try-html/克隆任务透传源）。

        内部审计键（share/reuse_hit/engine_resolved 等 worker 写入面）与
        一次性 idempotency_key 不回显：传过去会污染新任务的 dedup/对账面。
        """
        opts = row_json(row, "options_json")
        user_opts = {k: v for k, v in opts.items() if k not in _SNAPSHOT_OPTS_DROP}
        if user_opts:
            snap["options"] = user_opts
        cfg = row_json(row, "config_json")
        if cfg.get("glossary"):
            snap["glossary"] = cfg["glossary"]
