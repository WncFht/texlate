"""task_events 聚合 repo：事件落盘/重放 + snapshot warnings 回放。

``task_events`` 落盘即 SSE 重放凭据（``Last-Event-ID`` → ``events_since``）。
"""

from __future__ import annotations

import json
import time
from typing import Any

from texlate.server.store._common import _WARNINGS_CAP, EVENT_CAP, _Repo


class EventRepo(_Repo):
    """task_events 表聚合。构造只存门面回指——连接在 ``open()`` 后才可用。"""

    def append_event(self, task_id: str, etype: str, data: dict[str, Any]) -> int:
        """事件落盘 → 分配递增 seq；同事务滚动截断到 EVENT_CAP。

        任务行已被 ``DELETE`` 的迟到 publish（FK 无从依附，裸 INSERT 会
        ``IntegrityError`` 炸回 worker）：``INSERT…SELECT…WHERE EXISTS``
        静默丢弃，返回 ``0`` 哨兵（``0`` 即 snapshot 合成帧 seq，天然
        「未落盘」语义）——调用方据 ``0`` 跳过扇出。正常路径返回
        ``MAX(seq)+1`` 不变。
        """
        conn = self.conn
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS mx FROM task_events WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        seq = int(row["mx"]) + 1
        cur = conn.execute(
            "INSERT INTO task_events (task_id, seq, type, data, created_at)"
            " SELECT ?,?,?,?,? WHERE EXISTS(SELECT 1 FROM tasks WHERE id = ?)",
            (
                task_id,
                seq,
                etype,
                json.dumps(data, ensure_ascii=False),
                time.time(),
                task_id,
            ),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return 0
        conn.execute(
            "DELETE FROM task_events WHERE task_id = ? AND seq <= ?",
            (task_id, seq - EVENT_CAP),
        )
        conn.commit()
        return seq

    def events_since(self, task_id: str, seq: int) -> list[dict[str, Any]]:
        """``seq`` 之后的全部事件（Last-Event-ID 重放面）。

        ``data`` 列可经直写腐化——单格坏 JSON 跳过该条不拖垮整段
        resync（seq 序照旧连续，消费侧按 ``seq`` 字段对账不按位置）。
        """
        rows = self.conn.execute(
            "SELECT seq, type, data FROM task_events WHERE task_id = ? AND seq > ?"
            " ORDER BY seq",
            (task_id, seq),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                data = json.loads(r["data"])
            except json.JSONDecodeError:
                continue
            out.append({"seq": int(r["seq"]), "type": r["type"], "data": data})
        return out

    def last_seq(self, task_id: str) -> int:
        """任务当前最大事件 seq（snapshot.last_seq）。"""
        row = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS mx FROM task_events WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row["mx"])

    def _warnings(self, task_id: str) -> list[str]:
        """task_events 重放 warning 事件 → snapshot ``warnings`` 串列。

        web 侧 ``warnings?: string[]`` 按 ``[code] message`` 渲染（与 live
        WarningEvent 同形）；EVENT_CAP 滚动截断外的旧警告随之自然消失。
        ``type='warning'`` 下推 SQL + ``DESC LIMIT`` 只物化最近
        ``_WARNINGS_CAP`` 条再反序——snapshot 每次调用都走这里，全量
        warning 事件 json.loads 重放是白烧的 CPU。
        """
        rows = self.conn.execute(
            "SELECT data FROM task_events WHERE task_id = ? AND type = 'warning'"
            " ORDER BY seq DESC LIMIT ?",
            (task_id, _WARNINGS_CAP),
        ).fetchall()
        rows.reverse()
        out: list[str] = []
        for r in rows:
            try:
                data = json.loads(r["data"])
            except json.JSONDecodeError:
                continue  # 坏格不拖垮 snapshot warnings 回放
            if isinstance(data, dict) and "message" in data:
                out.append(f"[{data.get('code', '?')}] {data['message']}")
            else:
                out.append(str(data))
        return out
