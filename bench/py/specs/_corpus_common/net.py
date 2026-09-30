"""_corpus_common 网络/下载叶——open_url/item_url/meta 尺寸缓存/续传下载/内容校验。"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from typing import TYPE_CHECKING

from specs._corpus_common.io import (
    IA_DL,
    IA_META,
    TIGER_DL,
    TIMEOUT,
    UA,
    atomic_write_text,
    log,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------- 网络/下载
def open_url(url: str, headers: dict | None = None, timeout: int = TIMEOUT):
    req = urllib.request.Request(  # noqa: S310 — bench 下载脚本，URL 全是固定 https 端点
        url, headers={**UA, **(headers or {})}
    )
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — 同上


def item_url(channel: str, item: str) -> str:
    if channel == "ia":
        return IA_DL.format(item=item)
    return TIGER_DL.format(name=item)


def remote_size(it: dict, meta_dir: Path) -> int:
    """权威 size: ia 走 metadata API（item-index 尺寸有过期记录）并缓存于
    meta_dir; tiger 用索引 LFS size."""
    if it["channel"] == "tiger":
        return it["size"]
    meta_dir.mkdir(parents=True, exist_ok=True)
    cache = meta_dir / f"{it['item']}.json"
    meta = None
    if cache.exists():
        try:
            meta = json.loads(cache.read_text())
        except (OSError, json.JSONDecodeError):
            cache.unlink(missing_ok=True)  # 截尾缓存每次重跑都炸——弃掉重抓
    if meta is None:
        with open_url(IA_META.format(item=it["item"])) as r:
            meta = json.loads(r.read())
        atomic_write_text(cache, json.dumps(meta))
    for f in meta.get("files", []):
        if f["name"] == f"{it['item']}.tar":
            it["sha1"] = f.get("sha1")
            return int(f["size"])
    return it["size"]


def _verify_content(path: Path, it: dict) -> None:
    """尺寸之外的内容校验：ia→meta sha1, tiger→lfs oid16(sha256 前缀). 单遍流式."""
    want_sha1 = it.get("sha1")
    want_oid = it.get("oid16")
    if not want_sha1 and not want_oid:
        return
    h256 = hashlib.sha256()
    h1 = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(1 << 22), b""):
            h256.update(buf)
            h1.update(buf)
    if want_sha1 and h1.hexdigest() != want_sha1:
        msg = f"sha1 {h1.hexdigest()[:12]} != meta {want_sha1[:12]}"
        raise OSError(msg)
    if want_oid and not h256.hexdigest().startswith(want_oid):
        msg = f"sha256 {h256.hexdigest()[:16]} != oid16 {want_oid}"
        raise OSError(msg)


def download_item(it: dict, dest_dir: Path, meta_dir: Path) -> Path:
    """item tar → dest_dir/{item}.tar（.part+Range 续传，尺寸 + 内容校验）."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = dest_dir / f"{it['item']}.tar.part"
    final = dest_dir / f"{it['item']}.tar"
    want = remote_size(it, meta_dir)
    if final.exists() and final.stat().st_size == want:
        # 尺寸对≠内容对：腐 final 曾让本函数静默返回坏 tar(探针实证)——
        # 验不过就删掉落回下载循环重抓
        try:
            _verify_content(final, it)
        except OSError as e:
            log(f"  {it['item']} existing tar corrupt: {e} — 重抓")
            final.unlink()
        else:
            return final
    for attempt in range(4):
        have = part.stat().st_size if part.exists() else 0
        if have == want:
            try:
                _verify_content(part, it)
            except OSError as e:
                log(f"  {it['item']} .part 腐坏: {e} — 重抓")
                part.unlink()
                have = 0
            else:
                part.rename(final)
                return final
        if have > want:
            part.unlink()
            have = 0
        try:
            headers = {"Range": f"bytes={have}-"} if have else {}
            r = open_url(it["url"], headers=headers, timeout=180)
            try:
                resumed = bool(have) and r.status == 206
                with open(part, "ab" if resumed else "wb") as f:
                    while True:
                        buf = r.read(1 << 20)
                        if not buf:
                            break
                        f.write(buf)
            finally:
                r.close()
            if part.stat().st_size == want:
                _verify_content(part, it)
                part.rename(final)
                return final
            log(f"  {it['item']} partial {part.stat().st_size}/{want}")
        except Exception as e:
            log(f"  {it['item']} dl#{attempt}: {type(e).__name__}: {e}")
            time.sleep(5 * (attempt + 1))
    msg = f"{it['item']} download failed"
    raise OSError(msg)
