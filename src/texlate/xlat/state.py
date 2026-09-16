"""断点续跑 state + 段级缓存（docs/08 §1.6）。

- `state.json` 五表之一：每块完成原子重写 `{version, meta{model,
  pipeline_version, total_chunks, started_at, finished_at}, completed[],
  results[], errors_report[]}`；其余四表 `chunks_map/placeholders_map/
  glossary(term_dict)/errors_report` 由 `StateStore` 一并管理——重建器只读
  map 表，不依赖内存态。
- `atomic_json`：tmp+rename+0600（tmp 名带 uuid 防同路径并发写撞）。
- 缓存双层键（照 texglot §3 教科书结构）：
    段级 `sha256(source + role + 失效标签 + masked/protected 快照)`——
    失效 tag 按需追加，masked/protected 快照使 token 布局变则 key 变；
    文件级 `sha256(prompt_version + base_url + model + lang + glossary + context)`
    → `cache-{16h}.json`。
- 缓存读入逐条再校验，损坏文件改名隔离不删（`*-invalid-<rand>.json`）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

log = logging.getLogger(__name__)

STATE_VERSION = "1.0"


def atomic_json(path: Path, obj: object) -> None:
    """tmp+rename+0600 原子落盘。tmp 名带随机后缀防同路径并发撞名。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        Path(tmp_name).chmod(0o600)
        Path(tmp_name).rename(path)  # POSIX rename = 原子覆盖
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------- 缓存键


def segment_key(
    source: str,
    role: str,
    *,
    invalidation_tags: Iterable[str] = (),
    masked_snapshot: str = "",
) -> str:
    """段级缓存键：source + role + 失效标签 + masked/protected 快照。

    失效 tag 按需追加（如 accent/声明/数量级命中才加）；`masked_snapshot`
    是占位符布局摘要（如 `repr(sorted(ph 位置/类型))`）——token 布局变则
    key 变，改 prompt 措辞由 `prompt_version` 走文件级键失效。
    """
    material = source if not role else f"{role}\x00{source}"
    for tag in invalidation_tags:
        material += f"\x00{tag}"
    if masked_snapshot:
        material += f"\x00masked\x00{masked_snapshot}"
    return hashlib.sha256(material.encode()).hexdigest()


def file_cache_key(  # noqa: PLR0913 -- 缓存键六个成分字段，spec 定案公式
    *,
    prompt_version: str,
    base_url: str,
    model: str,
    lang: str,
    glossary: object = None,
    context: str = "",
) -> str:
    """文件级缓存键 → `cache-{16hex}.json` 文件名。"""
    payload = json.dumps(
        {
            "version": prompt_version,
            "base": base_url,
            "model": model,
            "language": lang,
            "glossary": glossary,
            "context": context,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_cache(path: Path) -> dict[str, str]:
    """读段级缓存；损坏文件改名隔离（不删——留诊断现场），返回干净 dict。"""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        bad = path.with_name(f"{path.stem}-invalid-{secrets.token_hex(4)}{path.suffix}")
        path.rename(bad)
        log.warning("cache %s corrupted (%s) → quarantined as %s", path, e, bad.name)
        return {}
    if not isinstance(data, dict):
        return {}
    # 逐条再校验：只留 str→str 条目
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


# ---------------------------------------------------------------- StateStore


@dataclass
class ChunkRecord:
    """`results[]` 里一条 chunk 记录。"""

    chunk_id: str
    source: str
    translation: str
    status: str = "ok"  # ok | skipped | fault | partial
    kind: str = "para"
    batched: bool = False
    batch_id: str | None = None
    skipped: bool = False
    skip_reason: str = ""
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    #: 失败成因（""|auth|provider|crash|validate）——error_code 归一输入
    error_kind: str = ""


class StateStore:
    """`output/{paper}/` 五表 + state.json + 段级缓存的统一落盘口。

    - `record(rec)`：completed+results 追加并原子重写 state.json（逐块落盘）。
    - `save_maps(chunks_map, placeholders_map, glossary)`：物化期一次写三表。
    - `load()`：续跑读 state → (completed 集合, results 表)。
    - 缓存：`cache_path(file_key)` → `load_cache`/`save_cache`。
    """

    STATE_FILE = "state.json"
    CHUNKS_MAP = "chunks_map.json"
    PLACEHOLDERS_MAP = "placeholders_map.json"
    GLOSSARY_FILE = "term_dict.json"
    ERRORS_FILE = "errors_report.json"

    def __init__(
        self,
        outdir: Path,
        *,
        model: str = "",
        pipeline_version: str = "",
        save_every: int = 1,
    ) -> None:
        """`outdir` 为 output/{paper}/ 目录；`save_every` 控制落盘频率（≥1）。"""
        self.outdir = Path(outdir)
        self.model = model
        self.pipeline_version = pipeline_version
        #: 每完成 `save_every` 块落一次盘（默认逐块——spec 原文；大文档可调大摊薄 O(n²) IO）
        self.save_every = max(1, save_every)
        self._completed: dict[str, None] = {}  # dict 当有序 set——重试块不重复登记
        self._results: list[dict[str, Any]] = []
        self._errors: list[dict[str, Any]] = []
        self._started_at = _utcnow()
        self._finished_at: str | None = None
        self._total_chunks = 0
        self._dirty = 0

    # ------------------------------------------------------------ state.json

    def state_path(self) -> Path:
        """state.json 路径。"""
        return self.outdir / self.STATE_FILE

    def load(self) -> tuple[set[str], dict[str, ChunkRecord]]:
        """续跑加载 → (completed 集合, chunk_id→ChunkRecord)。文件损坏从头来。"""
        path = self.state_path()
        if not path.exists():
            return set(), {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            # 与 load_cache 同口径：隔离留诊断现场，不覆盖不删除
            bad = path.with_name(
                f"{path.stem}-invalid-{secrets.token_hex(4)}{path.suffix}"
            )
            path.rename(bad)
            log.warning(
                "state %s corrupted (%s) → quarantined as %s", path, e, bad.name
            )
            return set(), {}
        if not isinstance(data, dict):
            bad = path.with_name(
                f"{path.stem}-invalid-{secrets.token_hex(4)}{path.suffix}"
            )
            path.rename(bad)
            log.warning(
                "state %s malformed (top-level %s) → quarantined as %s",
                path,
                type(data).__name__,
                bad.name,
            )
            return set(), {}
        completed = set(data.get("completed") or [])
        results: dict[str, ChunkRecord] = {}
        for r in data.get("results") or []:
            try:
                rec = ChunkRecord(
                    chunk_id=str(r["chunk_id"]),
                    source=str(r.get("source", "")),
                    translation=str(r.get("translation", "")),
                    status=str(r.get("status", "ok")),
                    kind=str(r.get("kind", "para")),
                    batched=bool(r.get("batched", False)),
                    batch_id=r.get("batch_id"),
                    skipped=bool(r.get("skipped", False)),
                    skip_reason=str(r.get("skip_reason", "")),
                    attempts=int(r.get("attempts", 0)),
                    warnings=list(r.get("warnings") or []),
                    error_kind=str(r.get("error_kind") or ""),
                )
            except (KeyError, TypeError, ValueError) as e:
                log.warning("state record skipped: %s", e)
                continue
            results[rec.chunk_id] = rec
        self._completed = dict.fromkeys(data.get("completed") or [])
        self._results = list(data.get("results") or [])
        self._errors = list(data.get("errors_report") or [])
        meta = data.get("meta") or {}
        self._started_at = meta.get("started_at") or self._started_at
        self._total_chunks = int(meta.get("total_chunks") or 0)
        return completed, results

    def start(self, total_chunks: int) -> None:
        """开跑登记。"""
        self._total_chunks = total_chunks
        self._started_at = _utcnow()
        self.flush()

    def record(self, rec: ChunkRecord, *, error: dict[str, Any] | None = None) -> None:
        """完成一块：completed+results 追加，按 save_every 原子落盘。

        续跑重试会让同一 chunk_id 二次经过——completed 按 key 去重
        （results 仍各记一条，留重试审计痕迹，load() 后者覆盖前者）。
        """
        self._completed[rec.chunk_id] = None
        self._results.append(
            {
                "chunk_id": rec.chunk_id,
                "source": rec.source,
                "translation": rec.translation,
                "status": rec.status,
                "kind": rec.kind,
                "batched": rec.batched,
                "batch_id": rec.batch_id,
                "skipped": rec.skipped,
                "skip_reason": rec.skip_reason,
                "attempts": rec.attempts,
                "warnings": rec.warnings,
                "error_kind": rec.error_kind,
            }
        )
        if error is not None:
            self._errors.append({"chunk_id": rec.chunk_id, **error})
        self._dirty += 1
        if self._dirty >= self.save_every:
            self.flush()

    def finish(self) -> None:
        """收尾：finished_at + 强制落盘。"""
        self._finished_at = _utcnow()
        self.flush()

    def flush(self) -> None:
        """原子重写 state.json。"""
        atomic_json(
            self.state_path(),
            {
                "version": STATE_VERSION,
                "meta": {
                    "model": self.model,
                    "pipeline_version": self.pipeline_version,
                    "total_chunks": self._total_chunks,
                    "started_at": self._started_at,
                    "finished_at": self._finished_at,
                },
                "completed": list(self._completed),
                "results": self._results,
                "errors_report": self._errors,
            },
        )
        if self._errors:
            atomic_json(self.outdir / self.ERRORS_FILE, self._errors)
        self._dirty = 0

    # ------------------------------------------------------------ 其余四表

    def save_maps(
        self,
        *,
        chunks_map: object = None,
        placeholders_map: object = None,
        term_dict: object = None,
    ) -> None:
        """物化期一次写 chunks_map/placeholders_map/term_dict 三表。"""
        if chunks_map is not None:
            atomic_json(self.outdir / self.CHUNKS_MAP, chunks_map)
        if placeholders_map is not None:
            atomic_json(self.outdir / self.PLACEHOLDERS_MAP, placeholders_map)
        if term_dict is not None:
            atomic_json(self.outdir / self.GLOSSARY_FILE, term_dict)

    # ------------------------------------------------------------ 段级缓存

    def cache_path(self, file_key: str) -> Path:
        """`cache-{file_key16}.json`。"""
        return self.outdir / f"cache-{file_key}.json"

    def load_cache(self, file_key: str) -> dict[str, str]:
        """读段级缓存（损坏隔离）。"""
        return load_cache(self.cache_path(file_key))

    def save_cache(self, file_key: str, cache: dict[str, str]) -> None:
        """写段级缓存（全表原子重写——texglot 的 O(n²) 写放大已知，v0 保正确性）。"""
        atomic_json(self.cache_path(file_key), cache)
