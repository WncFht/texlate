"""chunks 行/断点 state 桥域（自 ``_common`` 出叶）。

``chunk_db_id``/``zh_slot`` 是 chunks 行的 id 派生与 zh 槽读口径；
``FAILED_DB``/``chunk_error_code`` 是失败终态集与 SSE/chunks 共用的
error_code 唯一裁决点（T3）；``DBStateBridge`` 是 ``StateStore`` 鸭子型——
chunks 表做断点续跑状态面。``_DB_TO_PIPE``/``_PIPE_TO_DB`` 状态空间图
单源在 ``texlate.pipecore``，本叶别名钉住后经门面转口
（pdf.py/translate.py/__init__.py 消费面不改名）。
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from texlate.pipecore import (
    DB_TO_PIPE as _DB_TO_PIPE,
)
from texlate.pipecore import (
    PIPE_TO_DB as _PIPE_TO_DB,  # noqa: F401 -- 经门面再出口（pdf.py/translate.py 取）
)
from texlate.pipecore import (
    delivered_db,
)
from texlate.xlat.state import ChunkRecord, StateStore, atomic_json

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.server.store import Store
    from texlate.xlat.pipeline import ChunkResult


def chunk_db_id(src_file: str, byte_start: int, byte_end: int) -> str:
    """``sha256(src_file+byte_start+byte_end)[:24]``（§3.2 chunks.chunk_id）。"""
    h = hashlib.sha256(f"{src_file}:{byte_start}:{byte_end}".encode())
    return h.hexdigest()[:24]


def zh_slot(row: dict[str, Any]) -> str:
    """``all_chunks`` 行 zh 槽译文：``delivered_db`` 交付口径 + ``str`` 型判。

    非 ok 行（fallback/failed 装 en 原文回写）与 TEXT 列 BLOB 一律 ``""``——
    原文进 zh 槽阅读面会把英文当译文（dual.json/md.zip 两路消费单源，
    原 ``compile._zh_text``/``html._zh_slot`` 逐文件副本）。
    """
    t = row["translation"]
    return t if delivered_db(row["status"], t) and isinstance(t, str) else ""


# _DB_TO_PIPE/_PIPE_TO_DB 状态空间图单源在 texlate.pipecore——顶部别名导入，
# 本包消费面（pdf.py/translate.py/__init__.py）不改名。

#: chunks.status 的失败终态集（done 集 = ``_DB_TO_PIPE`` 键、pipecore
#: 状态图单源，不另建常量）
FAILED_DB = frozenset({"fallback_orig", "failed"})


def chunk_error_code(rec: ChunkResult | ChunkRecord) -> str | None:
    """Chunk error_code 唯一裁决点（T3）：SSE item 与 chunks 行共用一图。

    ``error_kind`` 归因先行（provider/auth 失败的块落库态是 skipped，
    不能被 validate 规则误标）；skipped → ``placeholder_mismatch``
    （占位符对账炸）/``validate``；fault 余者 → provider_error；
    ok/partial 无码。
    """
    if rec.error_kind in ("auth", "provider", "crash"):
        return {
            "auth": "provider_auth",
            "provider": "provider_error",
            "crash": "internal",
        }[rec.error_kind]
    if rec.fell_back:
        if "placeholder" in rec.skip_reason:
            return "placeholder_mismatch"
        return "validate"
    if rec.status == "fault":
        return "validate" if rec.error_kind == "validate" else "provider_error"
    return None


class DBStateBridge:
    """``StateStore`` 鸭子型：chunks 表做断点续跑状态面。

    ``load`` → (completed, recs)——completed 只收 ``ok``（pipeline 语义：
    skipped/fault 续跑必须重试）；``record`` → 待写缓冲由 worker flush。
    """

    def __init__(
        self,
        store: Store,
        task_id: str,
        *,
        rows: list[dict[str, Any]] | None = None,
        state_dir: Path | None = None,
    ) -> None:
        """绑定 store 与任务；``rows`` = 段头已读快照——给了 ``load`` 不再全扫。

        ``state_dir`` = ``save_maps`` 三表落盘根（任务 ``export-state/``）；
        缺省 None = 无落盘面，``save_maps`` 空操作。
        """
        self._store = store
        self._task_id = task_id
        self._rows = rows
        self._state_dir = state_dir
        self.buffer: list[ChunkRecord] = []

    def load(self) -> tuple[set[str], dict[str, ChunkRecord]]:
        """Chunks 行 → (completed, recs)（``_load_resumed`` 契约）。"""
        completed: set[str] = set()
        recs: dict[str, ChunkRecord] = {}
        rows = self._rows
        if rows is None:
            rows = self._store.all_chunks(self._task_id)
        for r in rows:
            status = r["status"]
            if status not in _DB_TO_PIPE:
                continue
            # chunks 表可经直写腐化（attempts 非数值、warnings 坏 JSON/BLOB）
            # ——坏格按 0/[] 容错，不让单格把 resume 拖进永 fault
            try:
                attempts = int(r["attempts"])
            except (TypeError, ValueError):
                attempts = 0
            try:
                warnings = json.loads(r["warnings"]) if r.get("warnings") else []
            except (TypeError, ValueError):
                warnings = []
            rec = ChunkRecord(
                chunk_id=r["chunk_id"],
                source=r["src_text"],
                translation=r["translation"] or "",
                status=_DB_TO_PIPE[status],
                kind=r["kind"],
                skipped=(status == "fallback_orig"),
                attempts=attempts,
                warnings=warnings,
            )
            recs[rec.chunk_id] = rec
            if status == "ok":
                completed.add(rec.chunk_id)
        return completed, recs

    def record(self, rec: ChunkRecord, *, error: dict[str, Any] | None = None) -> None:
        """缓冲一条结果（worker 按批量事务 flush）。"""
        del error
        self.buffer.append(rec)

    def start(self, total_chunks: int) -> None:
        """开跑登记：只记总数（state.json 语义已由 tasks 表覆盖）。"""
        self._store.update_fields(self._task_id, total_chunks=total_chunks)

    def finish(self) -> None:
        """收尾（落盘在 worker flush——这里无操作）。"""

    def save_maps(
        self,
        *,
        chunks_map: object = None,
        placeholders_map: object = None,
        term_dict: object = None,
    ) -> None:
        """``StateStore.save_maps`` 鸭子型：三表落 ``state_dir``，文件名同源。

        ``state_dir`` 未接线即空操作；写盘异常照常上浮——调用侧按
        「观测件不毁账」语义 suppress（bench ``stage_xlat`` 同式）。
        """
        out = self._state_dir
        if out is None:
            return
        if chunks_map is not None:
            atomic_json(out / StateStore.CHUNKS_MAP, chunks_map)
        if placeholders_map is not None:
            atomic_json(out / StateStore.PLACEHOLDERS_MAP, placeholders_map)
        if term_dict is not None:
            atomic_json(out / StateStore.GLOSSARY_FILE, term_dict)
