"""lake 水合叶 —— hydrate 双检锁协议 + raw 回填 + stage 整目录发布。

原 ``kernel.lake`` 顶层「hydration」段 (``_populate_from_raw``/
``_publish_stage``/``hydrate``)。抓取余量闸住 ``kernel._lake_gate``
(``_check_fetch_headroom``); 门面子模块互引走全路径直跨不绕门面。
门面回引名单见 ``kernel.lake._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tarfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from kernel import fsutil, paths, vault
from kernel._lake_catalog import LakeCatalog
from kernel._lake_cell import (
    PIN_MARKER,
    _payload_count,
    _read_meta,
    cell_dir,
    cell_pinned,
    is_complete,
    lake_lock,
)
from kernel._lake_gate import _check_fetch_headroom
from kernel.idnorm import safe_id

if TYPE_CHECKING:
    from collections.abc import Callable


def _populate_from_raw(raw_dir: Path, dst: Path) -> None:
    """Rebuild an extracted projection from the cell's canonical raw layer.

    - raw is a multi-entry tree → hardlink_farm the whole tree (the sw /
      repacked-text case — zero-copy read-only projection).
    - raw holds exactly one archive file → tarfile-extract (filter='data',
      stdlib safe extraction).
    - raw holds one non-tar ``*.gz`` → gzip single-file decompress
      (arXiv old-style members are gzipped single payloads).
    - raw holds one plain file → hardlink it across (EXDEV → copyfile via
      the farm fallback path is unnecessary for a single leaf; os.link is
      attempted first).
    """
    entries = sorted(raw_dir.iterdir())
    dst.mkdir(parents=True, exist_ok=True)
    if len(entries) == 1 and entries[0].is_file():
        f = entries[0]
        if tarfile.is_tarfile(f):
            with tarfile.open(f) as tf:
                tf.extractall(dst, filter="data")
            return
        if f.suffix == ".gz":
            with gzip.open(f, "rb") as fi:
                data = fi.read()
            out = dst / f.stem
            out.write_bytes(data)
            return
        try:
            os.link(f, dst / f.name)
        except OSError:
            shutil.copyfile(f, dst / f.name)
        return
    fsutil.hardlink_farm(raw_dir, dst)


def _publish_stage(stage: Path, dest: Path) -> bool:
    """Whole-dir rename of a built stage into ``dest``.

    Returns False when dest is already a COMPLETE cell — first wins, the
    existing tree is kept and our stage is discarded (§3.10.8 "已占 dest
    拒 rename 先者胜"). An occupied-but-incomplete dest (torn/skeleton) is
    ours to finish: it is removed and our stage lands.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        dest.unlink()  # a link is never a cell — clear it before publish
    elif dest.exists():
        meta = _read_meta(dest)
        n_files = meta.get("n_files")
        if (
            isinstance(n_files, int)
            and not isinstance(n_files, bool)
            and n_files > 0
            and n_files == _payload_count(dest)
        ):
            return False
        # The PINNED marker rides the torn tree into rmtree — carry it
        # across the rename so a re-hydrate can never silently un-pin.
        keep_pin = cell_pinned(dest)
        shutil.rmtree(dest)
    else:
        keep_pin = False
    os.rename(stage, dest)
    if keep_pin:
        (dest / PIN_MARKER).write_bytes(b"pinned\n")
    fsutil.fsync_dir(dest.parent)
    return True


def hydrate(
    idc: str, fetch_fn: Callable | None = None, source: str = "arxiv", run_seq: int = 0
) -> Path | None:
    """Materialize one cell; returns the cell dir, or None when the cell is
    lazy-unfetchable (no fetch_fn and no local raw to re-extract).

    Protocol (§3.10.3/§3.10.8):

    1. Fast path: ``is_complete`` outside the lock → return.
    2. ``.locks/{safe_id}.lock`` LOCK_EX → re-check inside the lock
       (double-check — a concurrent hydrator's finished cell is reused,
       never re-fetched: two same-cell hydrations degrade to one-fetch
       one-wait).
    3. Build whole-cell in ``lake/tmp/rebuild/{run_seq}/{safe}.stage``:
       ``fetch_fn(idc, stage)`` when provided — it must populate
       ``{stage}/extracted/`` (payload) and may populate ``{stage}/raw/``
       and return a dict of extra meta fields — else, when the existing
       cell still holds ``raw/``, re-extract locally at zero network cost
       (the raw_only tier's way back to hydrated). A new fetch first
       passes the DiskPressureError free-space gate; the local re-extract
       is exempt.
    4. meta.json via atomic_write, then whole-dir rename into place.
    5. Catalog row + lake_cell event 'hydrated'.
    """
    d = cell_dir(idc, source)
    if is_complete(idc, source):
        return d
    sid = safe_id(idc)
    with lake_lock(sid):
        # Double-check inside the lock — whoever held it before us may have
        # finished the hydration while we queued.
        if is_complete(idc, source):
            return d
        cat = LakeCatalog.load()
        if cat.state(idc) == "empty":
            # a recorded zero-payload answer — a legitimately empty fetch is
            # durable state, not a reason to fetch-storm the network again
            return d
        old_meta = _read_meta(d)
        raw_dir = d / "raw"

        if fetch_fn is None and raw_dir.is_dir():
            # raw_only → hydrated, in-place: extracted.stage inside the cell
            # then rename (no payload-risking window on the canonical layer).
            cat.set(idc, "hydrating", source=source)
            stage_e = d / "extracted.stage"
            if stage_e.exists():
                shutil.rmtree(stage_e)
            stage_e.mkdir(parents=True)
            _populate_from_raw(raw_dir, stage_e)
            vault.cas_link_tree(stage_e)
            ex = d / "extracted"
            if ex.is_symlink():
                ex.unlink()  # never a projection dir — clear it
            elif ex.exists():
                shutil.rmtree(ex)  # torn half-tree — replaced atomically
            os.rename(stage_e, ex)
            n = _payload_count(d)
            meta = {
                **old_meta,
                "idc": idc,
                "source": source,
                "n_files": n,
                "hydrated_at": round(time.time(), 3),
                "run_seq": run_seq,
                "rebuilt_from": "raw",
            }
            fsutil.atomic_write(
                d / "meta.json",
                json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2).encode(
                    "utf-8"
                ),
            )
            cat.set(
                idc,
                "empty" if n == 0 else "hydrated",
                source=source,
                n_files=n,
                bytes=fsutil.dir_size(d),
                manifested=True,
                last_used_at=round(time.time(), 3),
            )
            return d

        if fetch_fn is None:
            return None  # lazy-unfetchable: nothing local, no fetcher

        _check_fetch_headroom()
        cat.set(idc, "hydrating", source=source)
        stage = paths.lake_tmp_dir() / "rebuild" / str(run_seq) / f"{sid}.stage"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        try:
            ret = fetch_fn(idc, stage)
            meta_extra = dict(ret) if isinstance(ret, dict) else {}
            ex_dir = stage / "extracted"
            if ex_dir.is_dir():
                vault.cas_link_tree(ex_dir)
            n = _payload_count(stage)
            meta = {
                **old_meta,
                "idc": idc,
                "source": source,
                "n_files": n,
                "hydrated_at": round(time.time(), 3),
                "run_seq": run_seq,
                **meta_extra,
            }
            fsutil.atomic_write(
                stage / "meta.json",
                json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2).encode(
                    "utf-8"
                ),
            )
            if not _publish_stage(stage, d):
                shutil.rmtree(stage, ignore_errors=True)
                return d  # first wins — existing complete cell kept
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        cat.set(
            idc,
            "empty" if n == 0 else "hydrated",
            source=source,
            n_files=n,
            bytes=fsutil.dir_size(d),
            manifested=True,
            last_used_at=round(time.time(), 3),
        )
        return d
