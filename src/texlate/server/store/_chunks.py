"""chunks 聚合 repo：解析产物块行（2026-09-15-web-layer.md §3.4.1 断点恢复物证）。

``flush_chunk_batch`` 是跨聚合事务（chunks + translation_cache + tasks
计数器），留在 ``__init__`` 门面编排；这里只出块级件。
"""

from __future__ import annotations

from typing import Any

from texlate.server.store._common import CHUNKS_PAGE_MAX, _qmarks, _Repo, _set_clause

#: 预览窄列（``chunks_page``/``chunks_by_seqs`` 共用）——流式预览端点
#: 消费的固定列集，``src_text``/``translation`` 全文列只走这两路出。
_PREVIEW_COLS = "seq, chunk_id, kind, status, src_text, translation"

#: copy-latex span 列（``spans_by_seqs`` 专用）——``_PREVIEW_COLS`` 无
#: ``src_file``/``byte_*`` span 列，新方法不复用（实现文档 §后端 2）。
_SPAN_COLS = "seq, chunk_id, src_file, byte_start, byte_end, kind, src_text"


class ChunkRepo(_Repo):
    """chunks 表聚合。构造只存门面回指——连接在 ``open()`` 后才可用。"""

    def insert_chunks(self, task_id: str, rows: list[dict[str, Any]]) -> None:
        """批量插 chunks（parsing 完成物证，§3.4.1）。

        executemany 中途失败会留下未提交的隐式事务——下一个无关
        ``commit()`` 会把半成品 chunks 静默落库（``has_chunks`` 误判
        parsing 完成、resume 拿残缺块集跑翻译）。显式事务 + 失败
        rollback，与 ``flush_chunk_batch`` 同口径。
        """
        conn = self.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                "INSERT INTO chunks (task_id, seq, chunk_id, src_file,"
                " byte_start, byte_end, kind, src_text)"
                " VALUES (?,?,?,?,?,?,?,?)",
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
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def has_chunks(self, task_id: str) -> bool:
        """Chunks 有行 = parsing 已完成（断点跳过判据）。"""
        row = self.conn.execute(
            "SELECT 1 FROM chunks WHERE task_id = ? LIMIT 1", (task_id,)
        ).fetchone()
        return row is not None

    def chunk_exists(self, task_id: str, seq: int) -> bool:
        """``(task_id, seq)`` chunk 存在性——单块重译端点的合法块闸。"""
        row = self.conn.execute(
            "SELECT 1 FROM chunks WHERE task_id = ? AND seq = ? LIMIT 1",
            (task_id, seq),
        ).fetchone()
        return row is not None

    def all_chunks(self, task_id: str) -> list[dict[str, Any]]:
        """全量 chunks 按 seq 序（重建 done_map / splice 用）。"""
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE task_id = ? ORDER BY seq", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_chunks(self, task_id: str) -> int:
        """清任务全部 chunks（retry 换 main 等解析产物作废面）→ 删行数。"""
        cur = self.conn.execute("DELETE FROM chunks WHERE task_id = ?", (task_id,))
        self.conn.commit()
        return cur.rowcount

    def chunks_page(
        self, task_id: str, *, offset: int = 0, limit: int = 100
    ) -> tuple[list[dict[str, Any]], int]:
        """Chunks 窄列分页（流式预览端点 U1 供）→ ``(rows, total)``，seq 升序。

        只选预览消费列（``seq/chunk_id/kind/status/src_text/translation``）；
        ``src_text``/``translation`` 是全文列，``limit`` 钳
        ``[0, CHUNKS_PAGE_MAX]``、``offset`` 钳 ``≥0``——负值/超限按边界
        收，不炸调用方。
        """
        lim = max(0, min(int(limit), CHUNKS_PAGE_MAX))
        off = max(0, int(offset))
        rows = self.conn.execute(
            f"SELECT {_PREVIEW_COLS}"  # noqa: S608 -- 模块内固定列集常量，值全走绑定
            " FROM chunks WHERE task_id = ? ORDER BY seq LIMIT ? OFFSET ?",
            (task_id, lim, off),
        ).fetchall()
        return [dict(r) for r in rows], self._count(task_id)

    def chunks_by_seqs(
        self, task_id: str, seqs: list[int]
    ) -> tuple[list[dict[str, Any]], int]:
        """按 seq 集定点取块（增量轮询供：web 端按 SSE 已知状态只拉脏 seq）。

        ``(rows, total)``——rows 仅命中 seq，seq 升序；total 仍是全集大小
        （与 ``chunks_page`` 同契约，前端分页计数不换语义）。空 seqs 短路。
        """
        total = self._count(task_id)
        if not seqs:
            return [], total
        rows = self.conn.execute(
            f"SELECT {_PREVIEW_COLS}"  # noqa: S608 -- 列集为模块常量；IN 占位符全为参数化生成
            f" FROM chunks WHERE task_id = ? AND seq IN ({_qmarks(seqs)})"
            " ORDER BY seq",
            (task_id, *seqs),
        ).fetchall()
        return [dict(r) for r in rows], total

    def spans_by_seqs(self, task_id: str, seqs: list[int]) -> list[dict[str, Any]]:
        """按 seq 集取 span 列（copy-latex ``POST /latex`` 供）→ seq 升序命中行。

        列集 ``seq,chunk_id,src_file,byte_start,byte_end,kind,src_text``——
        ``byte_*`` 是 ``decode_tex`` 后 str 的字符偏移（列名谎称，切片方
        负责对 str 切）。空 seqs 短路。
        """
        if not seqs:
            return []
        rows = self.conn.execute(
            f"SELECT {_SPAN_COLS}"  # noqa: S608 -- 列集为模块常量；IN 占位符全为参数化生成
            f" FROM chunks WHERE task_id = ? AND seq IN ({_qmarks(seqs)})"
            " ORDER BY seq",
            (task_id, *seqs),
        ).fetchall()
        return [dict(r) for r in rows]

    def _count(self, task_id: str) -> int:
        """任务 chunks 全集行数——``chunks_page``/``chunks_by_seqs`` 的 total 同契约。"""
        return int(
            self.conn.execute(
                "SELECT COUNT(*) AS c FROM chunks WHERE task_id = ?", (task_id,)
            ).fetchone()["c"]
        )

    def update_chunk(self, task_id: str, chunk_id: str, fields: dict[str, Any]) -> None:
        """单块状态更新（由批量 flush 事务调用，不单独 commit）。"""
        sets = _set_clause(fields)
        self.conn.execute(
            f"UPDATE chunks SET {sets} WHERE task_id = ? AND chunk_id = ?",  # noqa: S608 -- 键名全为内部白名单
            (*fields.values(), task_id, chunk_id),
        )

    def chunk_counts(self, task_id: str) -> dict[str, int]:
        """Counters 聚合：total/done(已处理含失败)/failed(回退 + 失败)。

        缓存命中数不在 chunks 表粒度——真值见 ``tasks.cached_chunks``
        （``flush_chunk_batch`` 计数落列 → snapshot.counters.cached）。
        """
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
            "failed": int(row["failed"] or 0),
        }
