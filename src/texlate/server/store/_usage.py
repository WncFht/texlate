"""task_usage 聚合 repo：翻译阶段真实 usage/latency 聚合（T4）。"""

from __future__ import annotations

import time
from typing import Any

from texlate.server.store._common import _Repo


class UsageRepo(_Repo):
    """task_usage 表聚合。构造只存门面回指——连接在 ``open()`` 后才可用。"""

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
