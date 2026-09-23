"""kept_refs 聚合 repo：CiteCard ☆ 收藏的引用条目快照（M4 Phase B）。

payload 列存自含 JSON 文本（``{label,text,arxivId,doi,meta}``——dom 路
``bib.bibN`` 序数 key 随版本漂移时导出仍可用快照合成）；表无 tenant
列——隔离由 ``task_id`` 经 ``deps.get_task`` 租户闸传导，任务删行
``ON DELETE CASCADE`` 殉葬。
"""

from __future__ import annotations

import json
import time
from typing import Any

from texlate.server.store._common import StoreError, _Repo

#: payload 序列化后字节上限（与 DDL CHECK 同值——API 层先闸，此处兜底）
KEPT_PAYLOAD_MAX = 65536


class KeptRepo(_Repo):
    """kept_refs 表聚合。构造只存门面回指——连接在 ``open()`` 后才可用。"""

    def kept_list(self, task_id: str) -> dict[str, dict[str, Any]]:
        """任务 kept 全集 ``{ref_key: payload}``——坏 JSON 行跳过不炸整表。"""
        rows = self.conn.execute(
            "SELECT ref_key, payload FROM kept_refs WHERE task_id = ?"
            " ORDER BY created_at, ref_key",
            (task_id,),
        ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                payload = json.loads(str(row["payload"]))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                out[str(row["ref_key"])] = payload
        return out

    def kept_put(
        self, task_id: str, ref_key: str, payload: dict[str, Any]
    ) -> None:
        """Upsert 一条 kept（同 key 覆盖 payload + 刷 updated_at）。"""
        blob = json.dumps(payload, ensure_ascii=False)
        if len(blob.encode("utf-8")) > KEPT_PAYLOAD_MAX:
            msg = f"kept payload too large: {len(blob)} chars"
            raise StoreError(msg)
        now = time.time()
        self.conn.execute(
            "INSERT INTO kept_refs (task_id, ref_key, payload, created_at,"
            " updated_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(task_id, ref_key) DO UPDATE SET"
            " payload = excluded.payload, updated_at = excluded.updated_at",
            (task_id, ref_key, blob, now, now),
        )
        self.conn.commit()

    def kept_delete(self, task_id: str, ref_key: str) -> bool:
        """删一条 kept → 是否命中（未命中=False——API 层映 404）。"""
        cur = self.conn.execute(
            "DELETE FROM kept_refs WHERE task_id = ? AND ref_key = ?",
            (task_id, ref_key),
        )
        self.conn.commit()
        return cur.rowcount > 0
