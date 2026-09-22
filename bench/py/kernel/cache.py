"""cache — the global segment-level translation cache (§3.9).

Bucket layout: ``lake/cache/{file_key[:2]}/{file_key}.json`` — one JSON
dict ``{segment_key: zh_text}`` per ``file_cache_key`` identity
(prompt_version + base_url + model + lang + glossary + context), the same
shape src/texlate's ``StateStore.cache_path`` writes (str→str only,
corrupt file quarantined not deleted). Key formulas are NOT re-implemented
here — they are imported from ``texlate.xlat.state`` so the bench bucket
and the product cache can never drift apart.

Write discipline (the poison rules, §3.9/R18):

- loads are always safe — a miss just re-spends;
- stores BUFFER in the live ``SegCache`` dict and flush only via the
  kernel's post-terminal hook when the cell lands a FLUSH-worthy status
  ({ok, clean, partial} — DONE minus the failure set). A failed or
  crashed cell's segments never reach the shared bucket;
- correction/fix writers take ``writable=False`` (or a distinct
  ``context`` dim) — a hint-conditioned translation written under the
  plain key poisons the namespace for every later run (the server
  compile.py:832 precedent: the hint lives outside the key).

Metrics ride the terminal row: the kernel folds
``metrics.cache = {buckets, hits, misses, stores, evictions, bypassed}``
into the cell event before emit_batch. Probe accounting counts the
lookup points the pipeline actually makes: ``key in cache`` and
``cache.get(key)`` score hit/miss on outcome; ``cache[key]`` scores a
miss only on a KeyError (a hit-read after ``in`` is not double-counted).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from kernel import fsutil, locks, paths

__all__ = ["FLUSH_STATUSES", "SegCache", "bucket_path", "file_key_of",
           "metrics_of", "open_bucket", "status", "evict",
           "rebuild_from_vault"]

#: Cell terminals that release buffered stores into the shared buckets.
#: DONE minus the failure set — "cell 终态 ok 后才 flush" (§3.9).
FLUSH_STATUSES = frozenset({"ok", "clean", "partial"})

_BUCKET_NAME = re.compile(r"^[0-9a-f]{16}\.json$")

#: Default LRU cap for the whole cache tree (env TEXLATE_CACHE_CAP_GB).
_DEFAULT_CAP_GB = 8.0


def file_key_of(*, prompt_version: str, base_url: str, model: str,
                lang: str, glossary=None, context: str = "") -> str:
    """The 16-hex bucket key — texlate.xlat.state.file_cache_key verbatim."""
    from texlate.xlat.state import file_cache_key
    return file_cache_key(prompt_version=prompt_version, base_url=base_url,
                          model=model, lang=lang, glossary=glossary,
                          context=context)


def bucket_path(file_key: str) -> Path:
    """lake/cache/{file_key[:2]}/{file_key}.json — 256-way fanout."""
    fk = str(file_key)
    if not re.fullmatch(r"[0-9a-f]{16}", fk):
        raise ValueError(f"bad bucket key {file_key!r} (want 16-hex)")
    return paths.lake_cache_dir() / fk[:2] / f"{fk}.json"


def _bucket_lock(file_key: str):
    """Serialize the read-merge-write of one bucket across parallel runs."""
    lp = paths.lake_locks_dir() / f"cache-{file_key}.lock"
    lp.parent.mkdir(parents=True, exist_ok=True)
    return locks.flock(lp)


def _load_bucket(path: Path) -> dict:
    """load_cache semantics: str→str dict, corrupt -> quarantined."""
    from texlate.xlat.state import load_cache
    return load_cache(path)


class SegCache(dict):
    """A live bucket handle — a real dict (XlatPipeline's ``cache=``
    contract) plus probe counters and dirty tracking for the post-ok
    flush.

    ``writable=False`` is the correction/fix lane: reads still hit the
    shared bucket, stores/deletes are dropped on the floor and counted
    (``bypassed``) — nothing a hint-conditioned writer produces may
    enter the shared namespace.
    """

    def __init__(self, file_key: str, base: dict | None = None, *,
                 writable: bool = True) -> None:
        super().__init__(base or {})
        self.file_key = file_key
        self.writable = bool(writable)
        self.hits = 0
        self.misses = 0
        self.stores = 0
        self.evictions = 0
        self.bypassed = 0
        self.dirty = False
        self._flushed = False

    # -- probe counting -----------------------------------------------------
    def __contains__(self, key) -> bool:
        ok = dict.__contains__(self, key)
        if ok:
            self.hits += 1
        else:
            self.misses += 1
        return ok

    def get(self, key, default=None):
        ok = dict.__contains__(self, key)
        if ok:
            self.hits += 1
        else:
            self.misses += 1
        return dict.get(self, key, default)

    def __getitem__(self, key):
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            self.misses += 1
            raise

    # -- mutation -----------------------------------------------------------
    def __setitem__(self, key, value) -> None:
        if not self.writable:
            self.bypassed += 1
            return
        self.stores += 1
        self.dirty = True
        dict.__setitem__(self, key, value)

    def __delitem__(self, key) -> None:
        if not self.writable:
            self.bypassed += 1
            return
        self.evictions += 1
        self.dirty = True
        dict.__delitem__(self, key)

    def pop(self, key, *default):
        if not self.writable:
            self.bypassed += 1
            return default[0] if default else None
        if dict.__contains__(self, key):
            self.evictions += 1
            self.dirty = True
        return dict.pop(self, key, *default)

    def setdefault(self, key, default=None):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        if not self.writable:
            self.bypassed += 1
            return default
        self.stores += 1
        self.dirty = True
        dict.__setitem__(self, key, default)
        return default

    # -- flush --------------------------------------------------------------
    def flush(self) -> int:
        """Merge buffered entries into the on-disk bucket under the bucket
        lock (read-merge-write so parallel cells never last-writer-wins a
        sibling's stores). Returns entries written; 0 when clean."""
        if self._flushed or not self.dirty or not self.writable:
            self._flushed = True
            return 0
        bp = bucket_path(self.file_key)
        with _bucket_lock(self.file_key):
            disk = _load_bucket(bp) if bp.exists() else {}
            disk.update(dict(self))
            bp.parent.mkdir(parents=True, exist_ok=True)
            fsutil.atomic_write(
                bp, json.dumps(disk, ensure_ascii=False,
                               sort_keys=True).encode("utf-8"))
        self.dirty = False
        self._flushed = True
        return self.stores

    def discard(self) -> None:
        """Non-flush terminal — buffered stores die with the cell."""
        self.dirty = False
        self._flushed = True

    def metrics(self) -> dict:
        return {"bucket": self.file_key, "hits": self.hits,
                "misses": self.misses, "stores": self.stores,
                "evictions": self.evictions, "bypassed": self.bypassed,
                "writable": self.writable}


def metrics_of(caches) -> dict:
    """Aggregate per-cell cache metrics for the terminal row."""
    agg = {"buckets": 0, "hits": 0, "misses": 0, "stores": 0,
           "evictions": 0, "bypassed": 0}
    for sc in caches or ():
        agg["buckets"] += 1
        for k in ("hits", "misses", "stores", "evictions", "bypassed"):
            agg[k] += getattr(sc, k, 0)
    return agg


def open_bucket(*, prompt_version: str, base_url: str, model: str,
                lang: str, glossary=None, context: str = "",
                writable: bool = True) -> SegCache:
    """Load (or mint) the bucket for these key dims."""
    fk = file_key_of(prompt_version=prompt_version, base_url=base_url,
                     model=model, lang=lang, glossary=glossary,
                     context=context)
    bp = bucket_path(fk)
    base = _load_bucket(bp) if bp.exists() else {}
    return SegCache(fk, base, writable=writable)


# --- housekeeping ---------------------------------------------------------------


def _iter_buckets():
    """Yield (path, stat) for every well-formed bucket file."""
    root = paths.lake_cache_dir()
    if not root.is_dir():
        return
    for p in sorted(root.glob("*/*.json")):
        if not _BUCKET_NAME.match(p.name) or p.parent.name != p.name[:2]:
            continue
        try:
            yield p, p.stat()
        except OSError:
            continue


def status() -> dict:
    """{buckets, bytes, malformed_names} — doctor + `bench cache status`."""
    root = paths.lake_cache_dir()
    n = 0
    nbytes = 0
    for _p, st in _iter_buckets():
        n += 1
        nbytes += st.st_size
    malformed = 0
    if root.is_dir():
        for p in root.glob("*/*.json"):
            if not (_BUCKET_NAME.match(p.name)
                    and p.parent.name == p.name[:2]):
                malformed += 1
        malformed += sum(1 for p in root.iterdir()
                         if p.is_file() and p.suffix == ".json")
    cap_gb = float(os.environ.get("TEXLATE_CACHE_CAP_GB", _DEFAULT_CAP_GB))
    return {"root": str(root), "buckets": n, "bytes": nbytes,
            "malformed": malformed, "cap_gb": cap_gb,
            "over_cap": nbytes > cap_gb * (1 << 30)}


def evict(to_free: int) -> list[Path]:
    """LRU-evict bucket files until ``to_free`` bytes are released (mtime
    order — least-recently-touched first). Each delete rides the bucket
    lock so a concurrent flush can never be unlinked mid-merge."""
    removed: list[Path] = []
    freed = 0
    for p, st in sorted(_iter_buckets(), key=lambda t: t[1].st_mtime):
        if freed >= to_free:
            break
        with _bucket_lock(p.stem):
            try:
                freed += p.stat().st_size
                p.unlink()
                removed.append(p)
            except FileNotFoundError:
                continue
    return removed


def cap_evict() -> list[Path]:
    """Enforce the env cap — evict LRU until bytes <= cap. `bench cache
    evict` and any future janitor share this entry point."""
    st = status()
    over = st["bytes"] - int(st["cap_gb"] * (1 << 30))
    if over <= 0:
        return []
    return evict(over)


def rebuild_from_vault(*, prompt_version: str, base_url: str, model: str,
                       lang: str = "zh", glossary=None, context: str = "",
                       dry: bool = False, progress=None) -> dict:
    """vault/state -> buckets: replay every stored xlat-state cell's
    ``results[]`` through the segment_key formula and merge the ok rows
    into the bucket for the given key dims.

    The bucket identity is CALLER-SUPPLIED — state.json records model and
    pipeline_version but not base_url/lang/glossary/context, so the dims
    naming the corpus generation must come from the operator (for the
    promo stack: base_url=127.0.0.1:3033, model=swe-2-medium,
    prompt_version=texlate.xlat.prompts.PROMPT_VERSION).
    """
    from texlate.xlat import placeholders
    from texlate.xlat.state import ChunkRecord, segment_key

    fk = file_key_of(prompt_version=prompt_version, base_url=base_url,
                     model=model, lang=lang, glossary=glossary,
                     context=context)
    merged: dict[str, str] = {}
    cells = 0
    chunks = 0
    skipped = 0
    for kind_root in (paths.vault_kind_dir("state"),
                      paths.vault_dir() / "quar" / "state"):
        if not kind_root.is_dir():
            continue
        for state_file in sorted(kind_root.glob("*/*/state.json")):
            cells += 1
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                skipped += 1
                continue
            for raw in data.get("results") or []:
                try:
                    rec = ChunkRecord.from_dict(raw)
                except (KeyError, TypeError, ValueError):
                    skipped += 1
                    continue
                if rec.status != "ok" or not rec.source or not rec.translation:
                    skipped += 1
                    continue
                ph_types = [placeholders.ph_type(p)
                            for p in placeholders.ANY_PH_RX.findall(
                                rec.source)]
                merged[segment_key(rec.source, rec.kind,
                                   masked_snapshot=repr(ph_types))] = \
                    rec.translation
                chunks += 1
            if progress and cells % 50 == 0:
                progress(f"scanned {cells} state cells, {chunks} chunks")
    if not dry and merged:
        bp = bucket_path(fk)
        with _bucket_lock(fk):
            disk = _load_bucket(bp) if bp.exists() else {}
            disk.update(merged)
            bp.parent.mkdir(parents=True, exist_ok=True)
            fsutil.atomic_write(
                bp, json.dumps(disk, ensure_ascii=False,
                               sort_keys=True).encode("utf-8"))
    return {"file_key": fk, "cells": cells, "chunks": chunks,
            "skipped": skipped, "bucket_entries": len(merged),
            "dry": dry}
