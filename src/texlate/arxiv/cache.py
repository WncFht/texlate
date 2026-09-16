r"""source-tier 钉版缓存（docs/06 §4.1）。

布局（``root`` 默认 ``cache/src``，由调用方给）::

    {root}/{arxiv_id}v{resolved_version}/
        raw.{tar.gz|gz|pdf|bin}   原始 blob 字节原样（可重放）
        extracted/                过滤后树（pdf_only/unknown 无此目录）
        files.txt                 每行一个相对路径
        mtree.txt                 path<TAB>size<TAB>sha256<TAB>kind[<TAB>-> target][<TAB>stub]
        meta.json                 requested_id/resolved_version/etag/…

缓存键永远用 **resolved version**（裸 id 经 HEAD 文件名解析出 vN）。
发布原子化：``.staging-{uuid}`` 构建 → ``Path.rename`` 换入；已有目录先改名
``.old-{uuid}`` 备份，换入失败回滚（借 arxiv-to-prompt 的模式）。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: find_versions 的 glob 消毒：id 只许这些字符（glob 元字符 ``*?[]`` 全拒）
_SAFE_GLOB_ID: re.Pattern[str] = re.compile(r"[A-Za-z0-9._/-]+")


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """一条 source-tier 缓存。"""

    arxiv_id: str
    resolved_version: int
    dir: Path
    meta: dict

    @property
    def raw_path(self) -> Path | None:
        """原始 blob 路径。"""
        rf = self.meta.get("raw_file")
        return self.dir / rf if rf else None

    @property
    def extracted_dir(self) -> Path:
        """过滤后树目录。"""
        return self.dir / "extracted"

    @property
    def etag(self) -> str:
        """落盘时的 etag（重验证凭据）。"""
        return str(self.meta.get("etag") or "")


class CacheError(Exception):
    """缓存层失败。"""


class SourceCache:
    """``{id}v{n}`` 钉版目录的存取与原子发布。"""

    def __init__(self, root: Path | str) -> None:
        """Root = source-tier 缓存根（如 ``cache/src``）。"""
        self.root = Path(root)

    def entry_dir(self, arxiv_id: str, resolved_version: int) -> Path:
        """条目目录（旧式 id 自带 archive/ 段，自然嵌套）。"""
        d = self.root / f"{arxiv_id}v{resolved_version}"
        if not d.resolve().is_relative_to(self.root.resolve()):
            msg = f"arxiv_id escapes cache root: {arxiv_id!r}"
            raise CacheError(msg)
        return d

    def find_versions(self, arxiv_id: str) -> list[int]:
        """已缓存版本清单（升序）。id 含 glob 元字符或 ``..`` 段直接空集。"""
        if not _SAFE_GLOB_ID.fullmatch(arxiv_id) or ".." in arxiv_id.split("/"):
            return []
        return sorted(
            int(p.name.rsplit("v", 1)[-1])
            for p in self.root.glob(f"{arxiv_id}v*")
            if p.is_dir() and p.name.rsplit("v", 1)[-1].isdigit()
        )

    def get(self, arxiv_id: str, resolved_version: int) -> CacheEntry | None:
        """按钉版读条目；meta.json 缺失/损坏/非对象视为未命中。"""
        d = self.entry_dir(arxiv_id, resolved_version)
        meta_p = d / "meta.json"
        if not meta_p.is_file():
            return None
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            # 损坏条目按未命中处理（重取会覆盖），但留痕——静默重下会烧日预算
            log.warning("cache meta unreadable, treating as miss: %s (%s)", meta_p, e)
            return None
        if not isinstance(meta, dict):
            log.warning("cache meta not an object, treating as miss: %s", meta_p)
            return None
        return CacheEntry(arxiv_id, resolved_version, d, meta)

    def get_latest(self, arxiv_id: str) -> CacheEntry | None:
        """无版本钉时取已缓存最高版本（仅离线兜底，不等价于远端最新）。"""
        versions = self.find_versions(arxiv_id)
        for v in reversed(versions):
            e = self.get(arxiv_id, v)
            if e is not None:
                return e
        return None

    def stage(self) -> Path:
        """新建 staging 目录（调用方负责填充后 commit / 失败后 cleanup）。"""
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / f".staging-{uuid.uuid4().hex[:12]}"
        staging.mkdir()
        return staging

    def commit(self, staging: Path, arxiv_id: str, resolved_version: int) -> CacheEntry:
        """Staging → 目标目录原子换入。meta.json 必须已写好。"""
        meta_p = staging / "meta.json"
        if not meta_p.is_file():
            msg = f"staging missing meta.json: {staging}"
            raise CacheError(msg)
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            msg = f"staging meta.json not an object: {staging}"
            raise CacheError(msg)
        dest = self.entry_dir(arxiv_id, resolved_version)
        dest.parent.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None
        if dest.exists():
            backup = self.root / f".old-{uuid.uuid4().hex[:12]}"
            dest.rename(backup)
        try:
            staging.rename(dest)
        except OSError:
            if backup is not None:
                backup.rename(dest)  # 回滚
            raise
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return CacheEntry(arxiv_id, resolved_version, dest, meta)

    @staticmethod
    def cleanup(staging: Path) -> None:
        """清理 staging / 回滚残留目录。"""
        shutil.rmtree(staging, ignore_errors=True)
