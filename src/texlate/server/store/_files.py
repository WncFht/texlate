"""files 聚合 repo：产物登记 + 租户配额用量（web-layer.md §3.2 files 表）。

``tenant_usage`` 跨表 JOIN tasks 读（files.bytes 按租户聚合）——只读
查询，归本 repo 一并持有。
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any

from texlate.server.store._common import _Repo

if TYPE_CHECKING:
    from pathlib import Path


class FileRepo(_Repo):
    """files 表聚合。构造只存门面回指——连接在 ``open()`` 后才可用。"""

    def put_file(  # noqa: PLR0913 -- 登记面五元组 + 可选预算值即 spec 定案字段
        self,
        task_id: str,
        kind: str,
        path: str,
        *,
        data_dir: Path | None = None,
        size: int | None = None,
        sha256: str | None = None,
    ) -> dict[str, Any]:
        """登记产物（upsert）。

        ``size``/``sha256`` 调用方预算传入即只写库（worker ``_register``
        在 worker 线程算好——大文件哈希不占 loop）；缺省则给 ``data_dir``
        就地实测（读全文件+sha256，相对 ``tasks/{id}/``）。
        """
        sha = sha256
        if size is None and sha is None and data_dir is not None:
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
        """单条产物记录——``(task_id, kind)`` PK 直查，不拉全 kind 清单。"""
        row = self.conn.execute(
            "SELECT path, bytes, sha256, created_at FROM files"
            " WHERE task_id = ? AND kind = ?",
            (task_id, kind),
        ).fetchone()
        if row is None:
            return None
        return {
            "path": row["path"],
            "bytes": row["bytes"],
            "sha256": row["sha256"],
            "created_at": row["created_at"],
        }

    def delete_file(self, task_id: str, kind: str) -> str | None:
        """删产物登记行 → 被删行的 ``path``；无行返回 ``None``。

        派生产物失效面（retry 换 main / splice 失效重建）摘行用——磁盘件
        清理由调用方按返回 path 负责（``delete_task`` 同分工：表行与
        ``tasks/{id}/`` 文件分两层）。
        """
        rec = self.file_record(task_id, kind)
        if rec is None:
            return None
        self.conn.execute(
            "DELETE FROM files WHERE task_id = ? AND kind = ?", (task_id, kind)
        )
        self.conn.commit()
        return str(rec["path"])

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
