"""store 包共享底料：DDL/列级迁移/状态机枚举/错误码/id 工具（web-layer.md §3.2-§3.4）。

叶模块（``_tasks``/``_chunks``/``_files``/``_cache``/``_events``/``_usage``）
与 ``__init__`` 门面都从这里取常量——单源防漂移；本文件不依赖任何叶。
"""

from __future__ import annotations

import contextlib
import secrets
import stat as stat_mod
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Sized
    from pathlib import Path

    from texlate.server.store import Store

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
  idempotency_key TEXT,
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
-- 终态臂 find_reusable 查不了上面的 ACTIVE 部分唯一索引——无此索引则
-- cache_key 等值查是全表扫（建行热路径，每次 create 都来）
CREATE INDEX IF NOT EXISTS idx_tasks_cachekey
  ON tasks(cache_key) WHERE cache_key IS NOT NULL;

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

-- M4 Phase B：kept refs 收藏（misc-pack 实现文档 §M4）。payload 是自含
-- RefMeta 快照 JSON 文本（`label/text/arxivId/doi/meta`——dom 路 key 漂移
-- 时导出不受影响）；无 tenant 列——task_id 经 get_task 租户闸即隔离；
-- 任务删行 ON DELETE CASCADE 殉葬。64KB 上限 CHECK 兜底（API 层先闸）。
CREATE TABLE IF NOT EXISTS kept_refs (
  task_id    TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  ref_key    TEXT NOT NULL,
  payload    TEXT NOT NULL CHECK (length(payload) <= 65536),
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY (task_id, ref_key)
);
"""

#: 列级迁移（CREATE IF NOT EXISTS 盖不住的老库加列）：
#: ``(table, column, ALTER 片段, 补列后回填 SQL|None)``——
#: table_info 探测缺失才执行 ALTER + 回填。
_COLUMN_MIGRATIONS: tuple[tuple[str, str, str, str | None], ...] = (
    ("chunks", "warnings", "ALTER TABLE chunks ADD COLUMN warnings TEXT", None),
    # idempotency_key 从 options_json 提升为一等列——json_extract 表达式
    # 索引抢不过 idx_tasks_tenant 的 ORDER BY 红利，热查询必须走真列
    (
        "tasks",
        "idempotency_key",
        "ALTER TABLE tasks ADD COLUMN idempotency_key TEXT",
        (
            "UPDATE tasks SET idempotency_key ="
            " json_extract(options_json, '$.idempotency_key')"
            " WHERE json_extract(options_json, '$.idempotency_key') IS NOT NULL"
        ),
    ),
)

#: 依赖迁移列的索引——必须在 ``_COLUMN_MIGRATIONS`` 之后建（老库列未补
#: 前 CREATE INDEX 引用即炸）；IF NOT EXISTS 幂等，新库重跑无害。
_POST_DDL = """
CREATE INDEX IF NOT EXISTS idx_tasks_idem
  ON tasks(tenant, idempotency_key, created_at DESC)
  WHERE idempotency_key IS NOT NULL;
"""

#: 11 态机（§3.3）
ACTIVE_STATUSES = frozenset(
    {"queued", "fetching", "parsing", "translating", "compiling"}
)
TERMINAL_STATUSES = frozenset(
    {"done", "partial", "fault", "cancelled", "interrupted", "needs_auth"}
)

#: ACTIVE stage 名（snapshot.stage 枚举）
STAGES = ("fetching", "parsing", "translating", "compiling")

#: retry 允许的源态（§3.3 迁移守卫）
RETRYABLE_FROM = frozenset(
    {"fault", "partial", "cancelled", "interrupted", "needs_auth"}
)

#: task_events 每任务滚动上限（§3.2 表注）
EVENT_CAP = 2000

#: ``chunks_page`` 单页上限——``src_text``/``translation`` 全文列，页大即 MB 级
#: 载荷。``/api/task/{id}/chunks`` 的 ``limit`` Query 上限须与此同值（单源），
#: 声明界高于钳位即静默丢尾页
CHUNKS_PAGE_MAX = 500

#: ``snapshot.warnings`` 回放上限——只留最近 N 条 warning 事件
_WARNINGS_CAP = 200

#: ``snapshot.options`` 摘除键——app._RESERVED_OPTION_KEYS 的镜像
#: （worker 写入的内部审计字段）+ ``idempotency_key`` 一次性入参。
#: 环形依赖不许反向 import app，键集漂移时两侧同步改。
#: ``mock_run``/``no_seg_cache`` 同列：M1 审计/缓存围栅键（worker 与
#: retry 端点写入面），透出会让前端克隆任务把内部标记带进新任务。
_SNAPSHOT_OPTS_DROP = frozenset(
    {
        "reuse_hit",
        "arxiv_categories",
        "engine_resolved",
        "route_engines",
        "share",
        "idempotency_key",
        "mock_run",
        "no_seg_cache",
    }
)

#: 错误码枚举（§2.2）
ERROR_CODES = frozenset(
    {
        "arxiv_fetch",
        "no_latex_source",
        "no_html_source",
        "pdf_wrapper",
        "parse",
        "translate",
        "provider_auth",
        "provider_rate",
        "provider_timeout",
        "provider_error",
        "validate",
        "placeholder_mismatch",
        "compile",
        "inject_reject",
        "route_reject",
        "fixloop_exhausted",
        "fixloop_reject",
        "internal",
        "auth_required",
        "unsupported_format",
        "upload_too_large",
        # BabelDOC sidecar 判定码（pdf-path.md §4.2 assess → _run_pdf 透传）
        "timeout",
        "scanned_pdf",
        "babeldoc_translate",
        "zero_tokens",
        "degraded",
        # 编译段块级回落码（worker _env_judge_filter / _l2_writeback → chunks.error_code）
        "env_judge",
        "l2_reverted",
        # share 导入重验（worker _share_apply/_stage_compile share 臂）：
        # share_verify=任务级 reject code+reject_at；share_miss=块级未命中回落
        "share_verify",
        "share_miss",
    }
)

_TASK_ID_PREFIX = "t_"
_TASK_ID_LEN = len(_TASK_ID_PREFIX) + 16  # t_ + 16 hex

#: transition 参数的"未传"哨兵（None 是合法值——清 error/stage 要用）
_UNSET: Any = object()


# ------------------------------------------------------------ SQL 拼块件
# 包内占位符/SET 子句/枚举字面量渲染单源——叶 repo 一律从这里取，
# 防各聚合手滚漂移。


def _qmarks(items: Sized) -> str:
    """IN 占位符串（``?,?,…``）——只产占位符，值全走绑定参数。"""
    return ",".join("?" * len(items))


def _set_clause(fields: dict[str, Any]) -> str:
    """UPDATE SET 子句（``k = ?`` 逗号串）——键名全为调用方内部白名单。"""
    return ", ".join(f"{k} = ?" for k in fields)


def _sql_str_list(items: Iterable[str]) -> str:
    """渲染 SQL 字符串字面量列表（``'a','b'``）——仅染内部枚举常量，外部输入禁入。"""
    return ",".join(f"'{s}'" for s in items)


def _dir_size(d: Path) -> int:
    """目录树文件字节合计（扫描期单文件 OSError 跳过，整目录缺席→0）。"""
    total = 0
    try:
        for p in d.rglob("*"):
            with contextlib.suppress(OSError):
                st = p.stat()
                if stat_mod.S_ISREG(st.st_mode):
                    total += st.st_size
    except OSError:
        pass
    return total


def slim_task_dir(
    task_root: Path,
    keep: set[str],
    keep_dirs: tuple[str, ...] = (),
    *,
    dry: bool = False,
) -> int:
    """删 ``task_root`` 内未登记路径 + 摘空目录 → 释放字节数（幂等、纯 FS）。

    ``dry=True`` 只走同一口径核算将释放的字节——不 unlink 不 rmdir，
    供 API 端给 UI 出「约可释放 X」预估。

    ``keep`` = files 表登记的相对路径集（posix 分隔）——``file_get`` 的
    可服务面即白名单：产物字节一个不动，管线脚手架（build 目录/展开
    源码/tar 包外的中间件）全删。``keep_dirs`` = 整棵保留的子树
    （如 done/partial 的 ``zh``/``base``——单块重译与 share 打包的
    glossary 指纹都读活树），其内文件不走白名单逐件判。

    lexically 非法的 keep 项（绝对路径/含 ``..``）不生效——与
    ``file_get`` 的 resolve+is_relative_to 闸同口径，本就不可服务。
    symlink 特殊件一律 unlink（不跟随目标、不计字节）；空目录自底
    向上摘除，根目录本身保留。

    竞删/缺席按 OSError 吞——清扫面撞上并发 rmtree 不炸；在飞任务的
    排除是调用方职责（runner ``inflight_task_ids``）。
    """
    if task_root.is_symlink() or not task_root.is_dir():
        return 0

    def _norm(rels: Iterable[str]) -> set[str]:
        return {
            pp.as_posix()
            for rel in rels
            if not (pp := PurePosixPath(rel)).is_absolute() and ".." not in pp.parts
        }

    keep_norm = _norm(keep)
    prefixes = tuple(d + "/" for d in _norm(keep_dirs))
    freed = 0
    dirs: list[Path] = []
    with contextlib.suppress(OSError):
        for p in task_root.rglob("*"):
            # symlink 先于 is_dir 判定——dir 型 symlink 不递归不登记，直接摘链
            if not p.is_symlink() and p.is_dir():
                dirs.append(p)
                continue
            rel = p.relative_to(task_root).as_posix()
            if rel in keep_norm or rel.startswith(prefixes):
                continue
            with contextlib.suppress(OSError):
                st = p.lstat()
                if stat_mod.S_ISREG(st.st_mode):
                    freed += st.st_size
                if not dry:
                    p.unlink()
    if not dry:
        for d in sorted(dirs, key=lambda x: len(x.parts), reverse=True):
            with contextlib.suppress(OSError):
                d.rmdir()
    return freed


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


class _Repo:
    """聚合 repo 基类：存门面回指 + 惰性共享连接（单写者纪律由 Store 持有）。"""

    def __init__(self, store: Store) -> None:
        """回指门面（conn 惰性经 ``store.conn`` 取，断言即未 open 契约）。"""
        self._s = store

    @property
    def conn(self) -> sqlite3.Connection:
        """门面共享连接——repo 不持有独立连接（单写者纪律由 Store 持有）。"""
        return self._s.conn
