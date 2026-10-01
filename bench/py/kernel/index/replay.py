"""index 回放 mixin —— sealed 段摄入 / hot-tail byte watermark / 全量 rebuild。

- ``_sealed_done_set``/``sealed_done``/``_sealed_covered`` — 已重放段名集
  (meta ``sealed_done`` JSON) 与全覆盖判 (未摄段 = 投影盲区，封闸依据)。
- ``_ingest_sealed_segments`` — hot tail 整段旋走后仍可见的唯一通道：
  raw ``.jsonl`` 优先于 ``.zst`` (后者须 ledger.zst_verified 才信);
  每段摄入 + 标记同事务，读不出/验不过则留 pending 让封闸保持关闭。
- ``tail_ingest`` — 水位 = 末次吞入 ``\\n`` 之后一字节; inode tag 变
  (旋走重建) 或文件缩水则归零重放 (dedupe-by-sha 保证幂等)。
- ``_iter_all_events``/``_ledger_watermark`` — ledger 权威序回放 (sealed
  + hot 全覆盖) 与 fsync 尾偏移; ``_norm_iter_item`` 归一 dict/tuple 项。
- ``rebuild`` — kernel 活性闸后单事务全量重放：durable 游标先快照
  (回放期间新增行留给下次 tail_ingest), sealed_gen+1, .index-dirty
  提交成功后才清 (中途崩溃回滚到旧一致投影)。

只被 ``index.core.Index`` 继承; 不 import 兄弟叶 (探针走 ``index.common``,
``kernel.ledger`` 维持原码函数内惰性 import 避环)。
"""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path

from kernel import events, paths
from kernel.index.common import (
    _META_COUNTERS,
    _PROJECTION_TABLES,
    _file_tag,
    _kernel_idle,
    _sealed_segment_names,
)


def _norm_iter_item(item):
    """Normalize an iter_all_events item to an event dict (or None).

    Accepts dicts, (lineno, ev, raw) tuples like events.iter_jsonl yields,
    and (offset, ev) pairs — picks the dict member.
    """
    if isinstance(item, dict):
        return item
    if isinstance(item, (tuple, list)):
        for part in reversed(item):
            if isinstance(part, dict):
                return part
    return None


class _ReplayMixin:
    def _sealed_done_set(self) -> set:
        """Segment stems already replayed into the index (meta name-set)."""
        try:
            return set(json.loads(self._meta_get("sealed_done", "[]") or "[]"))
        except ValueError:
            return set()

    def sealed_done(self) -> set:
        """Sealed-segment stems fully replayed into the index — the
        'index watermark past the tail' leg for ledger.seal_gc."""
        return self._sealed_done_set()

    def _sealed_covered(self) -> bool:
        """Every sealed segment present on disk is ingested — an uningested
        segment is a blind spot: it can hold tombstone/missing evidence the
        projections have never seen."""
        return _sealed_segment_names() <= self._sealed_done_set()

    def _ingest_sealed_segments(self) -> int:
        """Apply events from sealed segments not yet in ``sealed_done``.

        The hot tail rotates away whole — without this leg every byte the
        seal moved would stay invisible to the projections forever (the
        'unsealed' verdict that can never clear). Raw ``.jsonl`` wins over
        ``.zst`` when both exist (identical bytes, cheaper); a ``.zst`` is
        trusted only after ledger.zst_verified passes — a clean-exit zstdcat
        can still decode garbage. Each segment ingests + marks done in ONE
        transaction. Returns rows newly applied.
        """
        done = self._sealed_done_set()
        pending = sorted(_sealed_segment_names() - done)
        if not pending:
            return 0
        from kernel import ledger as _ledger

        sdir = paths.sealed_dir()
        applied = 0
        for name in pending:
            evs: list = []
            bad = 0
            raw = sdir / name
            zst = Path(str(raw) + ".zst")
            if raw.exists():
                for _ln, ev, _rawline in events.iter_jsonl(raw):
                    if ev is None:
                        bad += 1
                    else:
                        evs.append(ev)
            elif zst.exists() and _ledger.zst_verified(zst):
                for _n, _off, ev in _ledger._iter_zst(zst):
                    if ev is None:
                        bad += 1
                    else:
                        evs.append(ev)
            else:
                # Nothing readable/verifiable — keep the segment pending so
                # the seal gate stays closed instead of going blind.
                continue
            with self._txn():
                for ev in evs:
                    if self._apply_one(ev) == "applied":
                        applied += 1
                if bad:
                    self._meta_incr("bad_lines", bad)
                done.add(name)
                self._meta_set("sealed_done", json.dumps(sorted(done)))
        return applied

    def tail_ingest(self) -> int:
        """Consume complete lines from events.jsonl past the stored watermark.

        Watermark = offset just past the last swallowed '\\n'; an unterminated
        tail is left for the next pass. The watermark is pinned to an inode
        tag: a rotated/recreated hot tail (different dev:ino) or a shrunken
        file resets it to 0 — dedupe-by-sha keeps the replay idempotent.
        Newly sealed segments are ingested first so rotated-away bytes stay
        visible. Returns rows newly applied.
        """
        applied = self._ingest_sealed_segments()
        ep = paths.events_path()
        watermark = int(self._meta_get("watermark", "0") or 0)
        try:
            st = ep.stat()
        except FileNotFoundError:
            return applied
        size = st.st_size
        tag = f"{st.st_dev}:{st.st_ino}"
        if self._meta_get("watermark_tag", "") != tag or watermark > size:
            watermark = 0
        with open(ep, "rb") as f:
            f.seek(watermark)
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return applied
        evs, bad = [], 0
        for line in data[: end + 1].split(b"\n"):
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:  # JSONDecodeError + UnicodeDecodeError
                bad += 1
                continue
            if not isinstance(ev, dict):
                bad += 1  # valid JSON, wrong shape — same skip-and-warn contract
                continue
            evs.append(ev)
        applied += self.apply_events(evs)
        with self._txn():
            if bad:
                self._meta_incr("bad_lines", bad)
            self._meta_set("watermark", str(watermark + end + 1))
            self._meta_set("watermark_tag", tag)
        return applied

    def _iter_all_events(self):
        """Yield ledger events in authoritative append order.

        kernel.ledger.iter_all_events() covers sealed segments + hot tail —
        the sole complete source (a hot-tail-only read silently misses
        sealed history and must never serve a rebuild). Items may be dicts
        or tuples carrying the dict — normalized here.
        """
        from kernel import ledger

        for item in ledger.iter_all_events():
            yield _norm_iter_item(item)

    def _ledger_watermark(self) -> int:
        from kernel import ledger

        return int(ledger.watermark_offset())

    def rebuild(self) -> int:
        """Wipe all projection tables and replay the ledger in one txn.

        Refused while the kernel is active — claims are rebuilt from events
        and the rebuild window would have no live lease (§3.2). On success:
        sealed_gen += 1, watermark = fsync'd tail offset, .index-dirty
        cleared AFTER commit (a crash mid-rebuild rolls back to the old
        consistent index and leaves the flag alone). Returns rows applied.
        """
        if not _kernel_idle():
            msg = (
                "kernel active — index rebuild refused "
                "(claims/done projections would go blind mid-run)"
            )
            raise RuntimeError(msg)
        # Snapshot the durable cursors BEFORE replaying: stamping a
        # watermark measured after replay could cover ledger lines that
        # arrived mid-replay and were never applied — the index would sit
        # permanently ahead of its own projections. Anything the ledger
        # gains during replay stays ahead of the stamped cursor for the
        # next tail_ingest instead.
        wm = self._ledger_watermark()
        wtag = _file_tag(paths.events_path())
        sealed_names = _sealed_segment_names()
        applied = 0
        with self._txn():
            for t in _PROJECTION_TABLES:
                self.conn.execute(f"DELETE FROM {t}")  # noqa: S608 -- t 来自 _PROJECTION_TABLES 常量表名
            for k in _META_COUNTERS:
                if k != "sealed_gen":  # generation only moves forward
                    self._meta_set(k, "0")
            self._line_no_hwm = 0
            for ev in self._iter_all_events():
                if ev is None:
                    self._meta_incr("bad_lines")
                    continue
                if self._apply_one(ev) == "applied":
                    applied += 1
            self._meta_incr("sealed_gen")
            self._meta_set("watermark", str(wm))
            self._meta_set("watermark_tag", wtag)
            self._meta_set("sealed_done", json.dumps(sorted(sealed_names)))
        # Commit succeeded — the index is sealed again; only now clear dirty.
        with suppress(FileNotFoundError):
            paths.index_dirty_path().unlink()
        return applied
