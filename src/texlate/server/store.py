"""SQLite 任务库（web-layer.md §3.2 DDL + §3.3 状态机 + §3.4 断点恢复）。

单写者连接：所有写走创建线程（uvicorn loop 线程），
``PRAGMA journal_mode=WAL; busy_timeout=5000; synchronous=NORMAL``。
``task_events`` 落盘即 SSE 重放凭据（``Last-Event-ID`` → ``events_since``）。
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

#: §3.2 DDL（可直接执行；外键 + 部分唯一索引压实 reuse 语义）
DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tasks (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'queued',
  stage         TEXT,
  progress      INTEGER NOT NULL DEFAULT 0,
  message       TEXT NOT NULL DEFAULT '',
  title         TEXT NOT NULL DEFAULT '',
  arxiv_id      TEXT,
  source_name   TEXT NOT NULL DEFAULT '',
  main_tex      TEXT NOT NULL DEFAULT '',
  target_lang   TEXT NOT NULL,
  model         TEXT NOT NULL,
  config_json   TEXT NOT NULL DEFAULT '{}',
  options_json  TEXT NOT NULL DEFAULT '{}',
  auth_source   TEXT NOT NULL DEFAULT 'settings',
  tenant        TEXT NOT NULL DEFAULT 'local',
  cache_key     TEXT,
  total_chunks  INTEGER NOT NULL DEFAULT 0,
  done_chunks   INTEGER NOT NULL DEFAULT 0,
  cached_chunks INTEGER NOT NULL DEFAULT 0,
  failed_chunks INTEGER NOT NULL DEFAULT 0,
  tokens        INTEGER NOT NULL DEFAULT 0,
  error_json    TEXT,
  worker_id     TEXT,
  created_at    REAL NOT NULL, updated_at REAL NOT NULL,
  started_at REAL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status  ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_tenant  ON tasks(tenant, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_cachekey_active
  ON tasks(cache_key) WHERE status IN
  ('queued','fetching','parsing','translating','compiling','interrupted');

CREATE TABLE IF NOT EXISTS chunks (
  task_id    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  seq        INTEGER NOT NULL,
  chunk_id   TEXT NOT NULL,
  src_file   TEXT NOT NULL,
  byte_start INTEGER NOT NULL, byte_end INTEGER NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'text',
  src_text   TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'pending',
  translation TEXT,
  error_code TEXT,
  attempts   INTEGER NOT NULL DEFAULT 0,
  warnings   TEXT,
  PRIMARY KEY (task_id, chunk_id),
  UNIQUE (task_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_chunks_pending
  ON chunks(task_id, status) WHERE status='pending';

CREATE TABLE IF NOT EXISTS files (
  task_id  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind     TEXT NOT NULL,
  path     TEXT NOT NULL,
  bytes    INTEGER, sha256 TEXT,
  created_at REAL NOT NULL,
  PRIMARY KEY (task_id, kind)
);

CREATE TABLE IF NOT EXISTS translation_cache (
  key        TEXT PRIMARY KEY,
  translation TEXT NOT NULL,
  model TEXT NOT NULL, target_lang TEXT NOT NULL,
  hit_count INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, last_hit_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS task_events (
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  seq     INTEGER NOT NULL,
  type    TEXT NOT NULL,
  data    TEXT NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY (task_id, seq)
);

-- T4：翻译阶段真实 usage/latency 聚合（ChatClient.usage_sink → worker 记账；
-- CREATE IF NOT EXISTS 自带迁移——老库补建即得，不用 ALTER）
CREATE TABLE IF NOT EXISTS task_usage (
  task_id           TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
  model             TEXT NOT NULL DEFAULT '',
  calls             INTEGER NOT NULL DEFAULT 0,
  prompt_tokens     INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  latency_s         REAL NOT NULL DEFAULT 0,
  updated_at        REAL NOT NULL
);
"""

#: 列级迁移（CREATE IF NOT EXISTS 盖不住的老库加列）：
#: ``(table, column, ALTER 片段)``——table_info 探测缺失才执行。
_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("chunks", "warnings", "ALTER TABLE chunks ADD COLUMN warnings TEXT"),
)

#: 11 态机（§3.3）
ACTIVE_STATUSES = frozenset(
    {"queued", "fetching", "parsing", "translating", "compiling"}
)
TERMINAL_STATUSES = frozenset(
    {"done", "partial", "fault", "cancelled", "interrupted", "needs_auth"}
)
ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES

#: ACTIVE stage 名（snapshot.stage 枚举）
STAGES = ("fetching", "parsing", "translating", "compiling")

#: retry 允许的源态（§3.3 迁移守卫）
RETRYABLE_FROM = frozenset(
    {"fault", "partial", "cancelled", "interrupted", "needs_auth"}
)

#: task_events 每任务滚动上限（§3.2 表注）
EVENT_CAP = 2000

#: 错误码枚举（§2.2）
ERROR_CODES = frozenset(
    {
        "arxiv_fetch",
        "no_latex_source",
        "pdf_wrapper",
        "parse",
        "provider_auth",
        "provider_rate",
        "provider_timeout",
        "provider_error",
        "validate",
        "placeholder_mismatch",
        "compile",
        "inject_reject",
        "fixloop_exhausted",
        "internal",
        "auth_required",
        "unsupported_format",
        "upload_too_large",
        # BabelDOC sidecar 判定码（pdf-path.md §三 assess → _run_pdf 透传）
        "timeout",
        "scanned_pdf",
        "babeldoc_translate",
        "zero_tokens",
        "degraded",
        # 编译段块级回落码（worker _env_judge_filter / _l2_writeback → chunks.error_code）
        "env_judge",
        "l2_reverted",
    }
)

_TASK_ID_PREFIX = "t_"
_TASK_ID_LEN = len(_TASK_ID_PREFIX) + 16  # t_ + 16 hex

#: transition 参数的"未传"哨兵（None 是合法值——清 error/stage 要用）
_UNSET: Any = object()


def new_task_id() -> str:
    """``t_`` + 16hex（URL 安全）。"""
    return _TASK_ID_PREFIX + secrets.token_hex(8)


def valid_task_id(task_id: str) -> bool:
    """task_id 形态校验（路径参数白名单，绝不进 SQL 拼接）。"""
    if len(task_id) != _TASK_ID_LEN or not task_id.startswith(_TASK_ID_PREFIX):
        return False
    try:
        int(task_id.removeprefix(_TASK_ID_PREFIX), 16)
    except ValueError:
        return False
    return True


class StoreError(Exception):
    """store 层异常基类。"""


class TransitionError(StoreError):
    """非法状态迁移（§3.3 守卫）——API 层映射 409。"""

    def __init__(self, task_id: str, current: str, target: str) -> None:
        """记录 当前→目标 迁移对。"""
        self.task_id = task_id
        self.current = current
        self.target = target
        super().__init__(f"{task_id}: {current} -> {target} rejected")


class Store:
    """单写者 SQLite 封装。``open()`` 必须在 loop 线程调一次。"""

    def __init__(self, path: Path) -> None:
        """Path = texlate.db 路径（父目录由调用方建）。"""
        self.path = path
        self._conn: sqlite3.Connection | None = None

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
        """列级迁移：``_COLUMN_MIGRATIONS`` 里探测缺失才 ALTER（幂等）。"""
        for table, column, ddl in _COLUMN_MIGRATIONS:
            cols = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(ddl)
        conn.commit()

    def close(self) -> None:
        """关连接。"""
        conn, self._conn = self._conn, None
        if conn is not None:
            conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        """已开连接；未 open 直接断言（内部约定，非用户输入）。"""
        assert self._conn is not None  # noqa: S101 -- open() 前置是类内契约
        return self._conn

    # ------------------------------------------------------------ tasks

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
        self.conn.execute(
            "INSERT INTO tasks (id, kind, status, title, arxiv_id, source_name,"
            " target_lang, model, config_json, options_json, auth_source,"
            " tenant, cache_key, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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

    def list_tasks(
        self, tenant: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """任务列表（按 tenant 隔离 + 可选 status 过滤），created_at 倒序。"""
        if status:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE tenant = ? AND status = ?"
                " ORDER BY created_at DESC",
                (tenant, status),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE tenant = ? ORDER BY created_at DESC",
                (tenant,),
            ).fetchall()
        return [dict(r) for r in rows]

    def find_active_by_cache_key(self, cache_key: str) -> dict[str, Any] | None:
        """同 cache_key 的 ACTIVE/interrupted 任务（部分唯一索引覆盖集）。"""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE cache_key = ? AND status IN"
            " ('queued','fetching','parsing','translating','compiling','interrupted')"
            " ORDER BY created_at DESC LIMIT 1",
            (cache_key,),
        ).fetchone()
        return dict(row) if row else None

    def find_reusable(self, cache_key: str) -> dict[str, Any] | None:
        """同 cache_key 已完成（done/partial）任务——reuse 命中依据。"""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE cache_key = ? AND status IN ('done','partial')"
            " ORDER BY created_at DESC LIMIT 1",
            (cache_key,),
        ).fetchone()
        return dict(row) if row else None

    def find_by_idempotency(self, tenant: str, idem_key: str) -> dict[str, Any] | None:
        """``options.idempotency_key`` 去重查找（JSON1 json_extract）。"""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE tenant = ?"
            " AND json_extract(options_json, '$.idempotency_key') = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (tenant, idem_key),
        ).fetchone()
        return dict(row) if row else None

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
        fields: dict[str, Any] = {"status": to, "updated_at": time.time()}
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
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE tasks SET {sets} WHERE id = ?",  # noqa: S608 -- 键名全为内部白名单
            (*fields.values(), task_id),
        )
        self.conn.commit()
        out = self.get(task_id)
        assert out is not None  # noqa: S101 -- 刚更新的行必然存在
        return out

    def _set_fields(self, task_id: str, fields: dict[str, Any]) -> None:
        """UPDATE tasks 不 commit（flush 事务内复用）。"""
        fields = {**fields, "updated_at": time.time()}
        sets = ", ".join(f"{k} = ?" for k in fields)
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
        qmarks = ",".join("?" * len(active))
        rows = self.conn.execute(
            f"SELECT id, auth_source FROM tasks WHERE status IN ({qmarks})",  # noqa: S608 -- '?' 占位符拼接，值全走绑定参数
            active,
        ).fetchall()
        n_interrupted = n_needs_auth = 0
        for r in rows:
            target = "needs_auth" if r["auth_source"] == "header" else "interrupted"
            self.conn.execute(
                "UPDATE tasks SET status = ?, worker_id = NULL, updated_at = ?"
                " WHERE id = ?",
                (target, time.time(), r["id"]),
            )
            if target == "needs_auth":
                n_needs_auth += 1
            else:
                n_interrupted += 1
        # queued 行残留 worker_id 也清掉
        self.conn.execute(
            "UPDATE tasks SET worker_id = NULL WHERE status = 'queued'"
            " AND worker_id IS NOT NULL"
        )
        self.conn.commit()
        return {"interrupted": n_interrupted, "needs_auth": n_needs_auth}

    # ------------------------------------------------------------ chunks

    def insert_chunks(self, task_id: str, rows: list[dict[str, Any]]) -> None:
        """批量插 chunks（parsing 完成物证，§3.4.1）。"""
        self.conn.executemany(
            "INSERT INTO chunks (task_id, seq, chunk_id, src_file, byte_start,"
            " byte_end, kind, src_text) VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    task_id,
                    r["seq"],
                    r["chunk_id"],
                    r["src_file"],
                    r["byte_start"],
                    r["byte_end"],
                    r["kind"],
                    r["src_text"],
                )
                for r in rows
            ],
        )
        self.conn.commit()

    def has_chunks(self, task_id: str) -> bool:
        """Chunks 有行 = parsing 已完成（断点跳过判据）。"""
        row = self.conn.execute(
            "SELECT 1 FROM chunks WHERE task_id = ? LIMIT 1", (task_id,)
        ).fetchone()
        return row is not None

    def all_chunks(self, task_id: str) -> list[dict[str, Any]]:
        """全量 chunks 按 seq 序（重建 done_map / splice 用）。"""
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE task_id = ? ORDER BY seq", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_chunk(self, task_id: str, chunk_id: str, fields: dict[str, Any]) -> None:
        """单块状态更新（由批量 flush 事务调用，不单独 commit）。"""
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE chunks SET {sets} WHERE task_id = ? AND chunk_id = ?",  # noqa: S608 -- 键名全为内部白名单
            (*fields.values(), task_id, chunk_id),
        )

    def chunk_counts(self, task_id: str) -> dict[str, int]:
        """Counters 聚合：total/done(已处理含失败)/cached/failed(回退+失败)。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN status IN ('ok','fallback_orig','failed')"
            "   THEN 1 ELSE 0 END) AS done,"
            " SUM(CASE WHEN status IN ('fallback_orig','failed') THEN 1 ELSE 0 END)"
            "   AS failed"
            " FROM chunks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "done": int(row["done"] or 0),
            "cached": 0,
            "failed": int(row["failed"] or 0),
        }

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
            now = time.time()
            for key, translation, model, lang in cache_puts:
                conn.execute(
                    "INSERT OR REPLACE INTO translation_cache"
                    " (key, translation, model, target_lang, hit_count,"
                    "  created_at, last_hit_at) VALUES"
                    " (?,?,?,?, COALESCE((SELECT hit_count FROM translation_cache"
                    "  WHERE key = ?), 0), COALESCE((SELECT created_at FROM"
                    "  translation_cache WHERE key = ?), ?), ?)",
                    (
                        key,
                        translation,
                        model,
                        lang,
                        key,
                        key,
                        now,
                        now,
                    ),
                )
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

    # ------------------------------------------------------------ usage（T4）

    def record_usage(  # noqa: PLR0913 -- usage 聚合五元组是 spec 定案字段
        self,
        task_id: str,
        *,
        model: str,
        calls: int,
        prompt_tokens: int,
        completion_tokens: int,
        latency_s: float,
    ) -> None:
        """翻译阶段真实 usage 聚合落 task_usage（upsert 累加，T4）。"""
        self.conn.execute(
            "INSERT INTO task_usage (task_id, model, calls, prompt_tokens,"
            " completion_tokens, latency_s, updated_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(task_id) DO UPDATE SET"
            " model = excluded.model,"
            " calls = task_usage.calls + excluded.calls,"
            " prompt_tokens = task_usage.prompt_tokens + excluded.prompt_tokens,"
            " completion_tokens = task_usage.completion_tokens"
            "   + excluded.completion_tokens,"
            " latency_s = task_usage.latency_s + excluded.latency_s,"
            " updated_at = excluded.updated_at",
            (
                task_id,
                model,
                calls,
                prompt_tokens,
                completion_tokens,
                latency_s,
                time.time(),
            ),
        )
        self.conn.commit()

    def usage_for(self, task_id: str) -> dict[str, Any] | None:
        """task_usage 行 → dict；无记录 None。"""
        row = self.conn.execute(
            "SELECT model, calls, prompt_tokens, completion_tokens, latency_s"
            " FROM task_usage WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    # ------------------------------------------------------------ files

    def put_file(
        self,
        task_id: str,
        kind: str,
        path: str,
        *,
        data_dir: Path | None = None,
    ) -> dict[str, Any]:
        """登记产物（upsert）。bytes/sha256 由 path 实测（相对 tasks/{id}/）。"""
        size: int | None = None
        sha: str | None = None
        if data_dir is not None:
            full = data_dir / path
            if full.is_file():
                blob = full.read_bytes()
                size = len(blob)
                sha = hashlib.sha256(blob).hexdigest()
        self.conn.execute(
            "INSERT INTO files (task_id, kind, path, bytes, sha256, created_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(task_id, kind) DO UPDATE SET"
            " path=excluded.path, bytes=excluded.bytes,"
            " sha256=excluded.sha256, created_at=excluded.created_at",
            (task_id, kind, path, size, sha, time.time()),
        )
        self.conn.commit()
        return {"kind": kind, "path": path, "bytes": size, "sha256": sha}

    def files(self, task_id: str) -> dict[str, dict[str, Any]]:
        """产物清单 ``{kind: {bytes, sha256, created_at, path}}``。"""
        rows = self.conn.execute(
            "SELECT kind, path, bytes, sha256, created_at FROM files WHERE task_id = ?",
            (task_id,),
        ).fetchall()
        return {
            r["kind"]: {
                "path": r["path"],
                "bytes": r["bytes"],
                "sha256": r["sha256"],
                "created_at": r["created_at"],
            }
            for r in rows
        }

    def file_record(self, task_id: str, kind: str) -> dict[str, Any] | None:
        """单条产物记录。"""
        return self.files(task_id).get(kind)

    def tenant_usage(self, tenant: str) -> dict[str, int]:
        """租户配额用量：``{tasks, bytes}``——任务行数 + files.bytes 合计。"""
        n = self.conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE tenant = ?", (tenant,)
        ).fetchone()["c"]
        b = self.conn.execute(
            "SELECT COALESCE(SUM(f.bytes), 0) AS b FROM files f"
            " JOIN tasks t ON t.id = f.task_id WHERE t.tenant = ?",
            (tenant,),
        ).fetchone()["b"]
        return {"tasks": int(n), "bytes": int(b)}

    # ------------------------------------------------------------ translation_cache

    def cache_get(self, key: str) -> str | None:
        """段级缓存读；命中记 hit_count/last_hit_at。"""
        conn = self.conn
        row = conn.execute(
            "SELECT translation FROM translation_cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE translation_cache SET hit_count = hit_count + 1,"
            " last_hit_at = ? WHERE key = ?",
            (time.time(), key),
        )
        conn.commit()
        return str(row["translation"])

    # ------------------------------------------------------------ task_events

    def append_event(self, task_id: str, etype: str, data: dict[str, Any]) -> int:
        """事件落盘 → 分配递增 seq；同事务滚动截断到 EVENT_CAP。"""
        conn = self.conn
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS mx FROM task_events WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        seq = int(row["mx"]) + 1
        conn.execute(
            "INSERT INTO task_events (task_id, seq, type, data, created_at)"
            " VALUES (?,?,?,?,?)",
            (task_id, seq, etype, json.dumps(data, ensure_ascii=False), time.time()),
        )
        conn.execute(
            "DELETE FROM task_events WHERE task_id = ? AND seq <= ?",
            (task_id, seq - EVENT_CAP),
        )
        conn.commit()
        return seq

    def events_since(self, task_id: str, seq: int) -> list[dict[str, Any]]:
        """``seq`` 之后的全部事件（Last-Event-ID 重放面）。"""
        rows = self.conn.execute(
            "SELECT seq, type, data FROM task_events WHERE task_id = ? AND seq > ?"
            " ORDER BY seq",
            (task_id, seq),
        ).fetchall()
        return [
            {"seq": int(r["seq"]), "type": r["type"], "data": json.loads(r["data"])}
            for r in rows
        ]

    def last_seq(self, task_id: str) -> int:
        """任务当前最大事件 seq（snapshot.last_seq）。"""
        row = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS mx FROM task_events WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row["mx"])

    # ------------------------------------------------------------ snapshot

    def snapshot(self, task_id: str, *, artifacts: dict[str, str]) -> dict[str, Any]:
        """§2.2 snapshot schema：任务行 + counters + error + artifacts + last_seq。"""
        row = self.get(task_id)
        if row is None:
            return {}
        error_raw = row.get("error_json")
        error = json.loads(error_raw) if error_raw else None
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
            "warnings": [],
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
        return snap
