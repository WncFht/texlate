"""tasks 聚合 repo：建行/查询/状态机迁移/启动恢复（web-layer.md §3.3-§3.4）。

所有方法经 ``self.conn`` 走门面共享连接——单写者纪律由 Store 持有。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from texlate.server.store._common import (
    _UNSET,
    ACTIVE_STATUSES,
    DDL,
    RETRYABLE_FROM,
    STAGES,
    TERMINAL_STATUSES,
    StoreError,
    TransitionError,
    _qmarks,
    _Repo,
    _set_clause,
    _sql_str_list,
)

if TYPE_CHECKING:
    import sqlite3


# ------------------------------------------------------------ 共享底料
# ``_Repo`` 基类与 ``_qmarks``/``_set_clause``/``_sql_str_list`` SQL
# 拼块件都已上抬 ``_common.py`` 作包内单源；本节余下的是 tasks 聚合
# 自用的枚举序常量。

#: cache_key 占用态集 = ``ACTIVE_STATUSES ∪ {"interrupted"}``——与
#: ``_common.DDL`` 的 ``uq_tasks_cachekey_active`` 部分唯一索引谓词
#: 同集**且同序**。查询侧渲染字面量 IN 列表（``_sql_str_list``）而非
#: 绑定参数：SQLite 只对字面量逐项全同的 IN 列表认部分索引蕴涵——
#: 同集异序或 ``IN (?,?,…)`` 参数化都丢 ``uq_tasks_cachekey_active``
#: 资格回退 ``idx_tasks_cachekey``（实证）。序按已部署 DDL 钉死：
#: ``IF NOT EXISTS`` 不重建老库索引，序漂移 = 存量库永久丢索引。
_CACHE_KEY_HELD_STATUSES = (
    "queued",
    "fetching",
    "parsing",
    "translating",
    "compiling",
    "interrupted",
)
assert frozenset(_CACHE_KEY_HELD_STATUSES) == ACTIVE_STATUSES | {  # noqa: S101 -- 集合契约：与 ACTIVE_STATUSES∪interrupted 锁步，漂移即坏 DDL/查询两侧同集前提
    "interrupted"
}
#: 序契约压实：渲染字面量须为已部署 DDL 谓词的逐字子串——同集异序
#: 上面集合 assert 验不出，这里直接对 DDL 文本钉死。
assert f"({_sql_str_list(_CACHE_KEY_HELD_STATUSES)})" in DDL  # noqa: S101 -- 序漂移即丢 uq_tasks_cachekey_active 部分索引资格，载入即炸响

#: 终态 IN 列表/绑定参数渲染件——terminal_task_ids/retention_candidates/
#: terminal_oldest_first 三处共用（sorted 序固定，占位符与参数一一对应）。
_TERMINAL_IN = f"({_qmarks(TERMINAL_STATUSES)})"
_TERMINAL_ARGS: tuple[str, ...] = tuple(sorted(TERMINAL_STATUSES))


class TaskRepo(_Repo):
    """tasks 表聚合。构造只存门面回指——连接在 ``open()`` 后才可用。"""

    def create_task(  # noqa: PLR0913 -- 列即参数面，构造任务行的全字段
        self,
        *,
        task_id: str,
        kind: str,
        target_lang: str,
        model: str,
        arxiv_id: str | None = None,
        source_name: str = "",
        title: str = "",
        config: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        auth_source: str = "settings",
        tenant: str = "local",
        cache_key: str | None = None,
    ) -> dict[str, Any]:
        """插入 queued 任务行；cache_key 唯一索引撞 → IntegrityError 上抛。"""
        now = time.time()
        idem_raw = (options or {}).get("idempotency_key")
        self.conn.execute(
            "INSERT INTO tasks (id, kind, status, title, arxiv_id, source_name,"
            " target_lang, model, config_json, options_json, auth_source,"
            " tenant, cache_key, idempotency_key, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                kind,
                "queued",
                title,
                arxiv_id,
                source_name,
                target_lang,
                model,
                json.dumps(config or {}, ensure_ascii=False),
                json.dumps(options or {}, ensure_ascii=False),
                auth_source,
                tenant,
                cache_key,
                str(idem_raw) if idem_raw else None,
                now,
                now,
            ),
        )
        self.conn.commit()
        row = self.get(task_id)
        assert row is not None  # noqa: S101 -- 刚插入的行必然存在
        return row

    def get(self, task_id: str) -> dict[str, Any] | None:
        """按 id 读任务行 → dict；不存在 None。"""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def _list_tasks_all(
        self, tenant: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """未分页全量任务列表——**测试专用**（``list_tasks_page`` 的排序对账 oracle）。

        生产面一律走分页版：全量 ``SELECT *`` 无 LIMIT，任务行膨胀后是
        白烧的内存/loop 时间，故降级为私有名只留测试引用。
        """
        if status:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE tenant = ? AND status = ?"
                " ORDER BY created_at DESC, id DESC",
                (tenant, status),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE tenant = ?"
                " ORDER BY created_at DESC, id DESC",
                (tenant,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_tasks_page(
        self,
        tenant: str,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[sqlite3.Row], int]:
        """分页任务列表（只选列表 API 消费列）+ total。"""
        where = "WHERE tenant = ?"
        params: list[Any] = [tenant]
        if status:
            where += " AND status = ?"
            params.append(status)
        rows = self.conn.execute(
            "SELECT id, kind, status, stage, progress, message, title, arxiv_id,"  # noqa: S608 -- where 由内部字面量拼装，值全走绑定参数
            " source_name, target_lang, model, created_at, updated_at,"
            " total_chunks, done_chunks, cached_chunks, failed_chunks, tokens,"
            " error_json,"
            " (SELECT COALESCE(MAX(e.seq), 0) FROM task_events e"
            " WHERE e.task_id = tasks.id) AS last_seq"
            f" FROM tasks {where}"
            " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        total = int(
            self.conn.execute(
                f"SELECT COUNT(*) AS c FROM tasks {where}",  # noqa: S608 -- 同上
                params,
            ).fetchone()["c"]
        )
        return rows, total

    def find_active_by_cache_key(self, cache_key: str) -> dict[str, Any] | None:
        """同 cache_key 的 ACTIVE/interrupted 任务（部分唯一索引覆盖集）。

        IN 列表渲染字面量（``_CACHE_KEY_HELD_STATUSES``，与 DDL 谓词同集）
        而非绑定参数——参数化丢部分索引资格，见常量注。
        """
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE cache_key = ? AND status IN"  # noqa: S608 -- 状态集为内部枚举字面量渲染，cache_key 仍走绑定
            f" ({_sql_str_list(_CACHE_KEY_HELD_STATUSES)})"
            " ORDER BY created_at DESC LIMIT 1",
            (cache_key,),
        ).fetchone()
        return dict(row) if row else None

    def find_reusable(self, cache_key: str) -> dict[str, Any] | None:
        """同 cache_key 已完成任务——reuse 命中依据（仅 ``done``）。

        ``partial`` 不收：partial 是降级交付（inject/route reject、修复链未
        收敛），``_finish_reuse`` 会原样镜像其终态 + ``error_json``——把腐
        产物克隆给后来者等于毒传播（``t_f74894ebc691aaf4`` 缺包 partial
        被 reuse 克隆给 ``t_74d635d226e68251`` 实证）。partial 命中方请
        走真跑（修复链可能收敛成 done）。
        """
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE cache_key = ? AND status = 'done'"
            " ORDER BY created_at DESC LIMIT 1",
            (cache_key,),
        ).fetchone()
        return dict(row) if row else None

    def find_by_idempotency(self, tenant: str, idem_key: str) -> dict[str, Any] | None:
        """``idempotency_key`` 列去重查找（``idx_tasks_idem`` 复合覆盖）。"""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE tenant = ? AND idempotency_key = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (tenant, idem_key),
        ).fetchone()
        return dict(row) if row else None

    def find_latest_by_arxiv(
        self, tenant: str, base_id: str, version: int | None = None
    ) -> dict[str, Any] | None:
        """``arxiv_id`` 最新任务行（hjfy 兼容面查源）。

        ``base_id`` 须已归一去版（调用方过 ``normalize_arxiv_id`` +
        ``valid_id``——id 字符集无 GLOB 元字符，``{base}v*`` 模式安全）。
        arxiv/upload_tex 建行存裸 id、share 导入存 ``{id}v{N}`` 钉版形，
        ``= base`` 或 GLOB 同罩两形；``version`` 钉版查询精确行优先，
        其余按创建时间取最新。tenant 隔离与 ``_get_task`` 同口径。
        """
        exact = f"{base_id}v{version}" if version is not None else base_id
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE tenant = ?"
            " AND (arxiv_id = ? OR arxiv_id GLOB ?)"
            " ORDER BY (arxiv_id = ?) DESC, created_at DESC, id DESC LIMIT 1",
            (tenant, base_id, f"{base_id}v*", exact),
        ).fetchone()
        return dict(row) if row else None

    def task_ids(self) -> list[str]:
        """全量任务 id——启动孤儿目录清扫（``_sweep_orphan_task_dirs``）的已知集合。"""
        rows = self.conn.execute("SELECT id FROM tasks").fetchall()
        return [str(r["id"]) for r in rows]

    def terminal_task_ids(self, tenant: str | None = None) -> list[str]:
        """终态任务 id（``tenant`` 可选过滤）——瘦身/清扫候选面。"""
        sql = f"SELECT id FROM tasks WHERE status IN {_TERMINAL_IN}"  # noqa: S608 -- '?' 占位符拼接，值全走绑定参数
        args: tuple[str, ...] = _TERMINAL_ARGS
        if tenant is not None:
            sql += " AND tenant = ?"
            args += (tenant,)
        rows = self.conn.execute(sql, args).fetchall()
        return [str(r["id"]) for r in rows]

    def retention_candidates(self, cutoff: float) -> list[str]:
        """终态且 ``COALESCE(finished_at, updated_at) < cutoff``——retention 龄期候选。"""
        rows = self.conn.execute(
            f"SELECT id FROM tasks WHERE status IN {_TERMINAL_IN}"  # noqa: S608 -- 同上
            " AND COALESCE(finished_at, updated_at) < ?",
            (*_TERMINAL_ARGS, cutoff),
        ).fetchall()
        return [str(r["id"]) for r in rows]

    def terminal_oldest_first(self) -> list[str]:
        """终态按完成时间升序——retention 容量阶段 oldest-first 候选序。"""
        rows = self.conn.execute(
            f"SELECT id FROM tasks WHERE status IN {_TERMINAL_IN}"  # noqa: S608 -- 同上
            " ORDER BY COALESCE(finished_at, updated_at), id",
            _TERMINAL_ARGS,
        ).fetchall()
        return [str(r["id"]) for r in rows]

    def queued_rows(self) -> list[dict[str, Any]]:
        """库内残留 ``queued`` 行（header 源除外）——``TaskRunner`` 重启补放面。

        窄列 ``id``/``model``，``created_at, id`` 升序——与内存队列 FIFO
        同口径。header 凭证随进程死亡不可恢复（``recover_startup`` 已分流
        ``needs_auth``），此处防御性排除。
        """
        rows = self.conn.execute(
            "SELECT id, model FROM tasks WHERE status = 'queued'"
            " AND auth_source != 'header' ORDER BY created_at, id"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_task(self, task_id: str) -> bool:
        """删任务行——FK ``ON DELETE CASCADE`` 带走 chunks/files/events/usage。

        无条件臂即 ``delete_task_guard`` 空 blocked 特例——单 DELETE 路径
        不另滚 SQL。返回是否有行被删（API 层 ``_get_task`` 已做存在性
        检查，这里只是幂等回执）。任务工作目录 ``tasks/{id}/`` 清理由
        调用方负责。
        """
        return self.delete_task_guard(task_id, blocked=frozenset())

    def delete_task_guard(self, task_id: str, *, blocked: frozenset[str]) -> bool:
        """条件删除：status ∈ blocked 或行不存在 → False 不删；否则删行返 True。"""
        if blocked:
            qmarks = _qmarks(blocked)
            cur = self.conn.execute(
                f"DELETE FROM tasks WHERE id = ? AND status NOT IN ({qmarks})",  # noqa: S608 -- '?' 占位符拼接，值全走绑定参数
                (task_id, *blocked),
            )
        else:
            cur = self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------ 状态迁移

    def transition(  # noqa: C901, PLR0913 -- 状态机守卫 + 字段表平铺即 §3.3
        self,
        task_id: str,
        to: str,
        *,
        stage: str | object | None = _UNSET,
        progress: int | None = None,
        message: str | None = None,
        error: dict[str, Any] | object | None = _UNSET,
        force: bool = False,
    ) -> dict[str, Any]:
        """守卫迁移。``force`` 为 worker 内部通道（状态机正向推进）。

        API 侧只允许 cancel（ACTIVE→cancelled）与 retry
        （RETRYABLE_FROM→queued）——其余迁移一律 TransitionError。

        读-判-写（get → 守卫判定 → UPDATE）整体同步执行、无 await：
        单写者纪律下全部调用都在 loop 线程串行（worker 线程经
        ``_on_loop`` 回弹；``check_same_thread`` 缺省开——越线程直调
        当场 ``ProgrammingError`` 炸响而非静默竞写），判定与写之间无
        插入窗，不需要 ``UPDATE ... WHERE status=?`` 条件写兜底。
        """
        row = self.get(task_id)
        if row is None:
            msg = f"task not found: {task_id}"
            raise StoreError(msg)
        cur = row["status"]
        if not force:
            legal = (to == "cancelled" and cur in ACTIVE_STATUSES) or (
                to == "queued" and cur in RETRYABLE_FROM
            )
            if not legal:
                raise TransitionError(task_id, cur, to)
        fields: dict[str, Any] = {"status": to}  # updated_at 由 _set_fields 统一打戳
        if stage is not _UNSET:
            fields["stage"] = stage
        elif to in STAGES:
            fields["stage"] = to
        if progress is not None:
            fields["progress"] = progress
        if message is not None:
            fields["message"] = message
        if error is not _UNSET:
            fields["error_json"] = (
                json.dumps(error, ensure_ascii=False) if error is not None else None
            )
        if to in STAGES and row["started_at"] is None:
            fields["started_at"] = time.time()
        if to in TERMINAL_STATUSES:
            fields["finished_at"] = time.time()
            fields["stage"] = None
        if to == "queued":
            # 重入队：清 worker 认领标记与 stage
            fields["worker_id"] = None
            fields["stage"] = None
            fields["error_json"] = None
            fields["finished_at"] = None
        self._set_fields(task_id, fields)
        self.conn.commit()
        out = self.get(task_id)
        assert out is not None  # noqa: S101 -- 刚更新的行必然存在
        return out

    def _set_fields(self, task_id: str, fields: dict[str, Any]) -> None:
        """UPDATE tasks 不 commit（flush 事务内复用）。"""
        fields = {**fields, "updated_at": time.time()}
        sets = _set_clause(fields)
        self.conn.execute(
            f"UPDATE tasks SET {sets} WHERE id = ?",  # noqa: S608 -- 键名全为内部白名单
            (*fields.values(), task_id),
        )

    def update_fields(self, task_id: str, **fields: object) -> None:
        """非状态字段直改（progress/counters/main_tex/title/tokens/options）。"""
        if not fields:
            return
        self._set_fields(task_id, fields)
        self.conn.commit()

    def claim(self, task_id: str, worker_id: str) -> None:
        """Worker 认领标记（崩溃恢复判定依据）。"""
        self.update_fields(task_id, worker_id=worker_id)

    def heartbeat(self, task_id: str) -> None:
        """活跃任务心跳：只 bump updated_at（SSE/列表页 staleness 信号）。"""
        self.conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (time.time(), task_id),
        )
        self.conn.commit()

    def recover_startup(self) -> dict[str, int]:
        """启动恢复（§3.4.4）：遗留 ACTIVE → interrupted；header 源 → needs_auth。"""
        active = tuple(ACTIVE_STATUSES - {"queued"})
        qmarks = _qmarks(active)
        rows = self.conn.execute(
            f"SELECT id, auth_source FROM tasks WHERE status IN ({qmarks})",  # noqa: S608 -- '?' 占位符拼接，值全走绑定参数
            active,
        ).fetchall()
        n_interrupted = n_needs_auth = 0
        for r in rows:
            target = "needs_auth" if r["auth_source"] == "header" else "interrupted"
            now = time.time()
            self.conn.execute(
                "UPDATE tasks SET status = ?, stage = NULL, worker_id = NULL,"
                " updated_at = ?, finished_at = ? WHERE id = ?",
                (target, now, now, r["id"]),
            )
            if target == "needs_auth":
                n_needs_auth += 1
            else:
                n_interrupted += 1
        # queued + header 源：凭证只活在死亡进程的内存 secrets 里，
        # 永远等不到——分流 needs_auth（用户带 key retry 可续）；其余
        # queued 由 TaskRunner.start 重放回内存队列续跑
        n_needs_auth += self.conn.execute(
            "UPDATE tasks SET status = 'needs_auth', stage = NULL,"
            " worker_id = NULL, updated_at = ?, finished_at = ?"
            " WHERE status = 'queued' AND auth_source = 'header'",
            (time.time(), time.time()),
        ).rowcount
        # queued 行残留 worker_id 也清掉
        self.conn.execute(
            "UPDATE tasks SET worker_id = NULL WHERE status = 'queued'"
            " AND worker_id IS NOT NULL"
        )
        self.conn.commit()
        return {"interrupted": n_interrupted, "needs_auth": n_needs_auth}
