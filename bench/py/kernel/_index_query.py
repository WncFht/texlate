"""index 查询 mixin —— sealed 对账 oracle + dedup 域读面 + .index-dirty 旗。

- ``sealed_state``/``check_sealed`` — 付费闸 fail-closed oracle (§3.10.6):
  gen 匹配 + 无 dirty + sealed 段全摄 + watermark 覆盖调用方 fsync 偏移;
  ``min_tag`` 不同 = 热尾已旋走, 字节覆盖改由 sealed 全覆盖证明。
- ``done``/``last_cell`` — cells 终态读 (DONE ∪ KERNEL 终向截流) 与整行。
- ``paid_pool``/``vault_bytes_ok``/``active_claims`` — dedup 域集:
  付费池按 spec 付费 stages 截 (免费 stage 的 ok 不铸付费证据);
  claims 表里 slot IS NULL 才是生命周期行 (带 slot 的是 paid_slots
  镜像流, 同表另一信道)。
- ``dedup_skip_count``/``quarantine_count`` — 计数读面。
- ``note_dirty``/``dirty`` — emit 败写后标记 .index-dirty (oracle 即拒)。

只被 ``_index_core.Index`` 继承; 不 import 兄弟叶 (常量走 ``_index_common``,
跨 mixin 方法经 self MRO 解析)。
"""

from __future__ import annotations

import time

from kernel import paths
from kernel._index_common import (
    _TERMINAL,
    _VAULT_BYTES_OK,
    _file_tag,
    _sealed_segment_names,
)


class _QueryMixin:
    def sealed_state(self) -> tuple[int, int]:
        """(sealed_gen, watermark) — the pair a run snapshots at startup."""
        return (
            int(self._meta_get("sealed_gen", "0") or 0),
            int(self._meta_get("watermark", "0") or 0),
        )

    def check_sealed(
        self, gen: int, min_offset: int = 0, min_tag: str | None = None
    ) -> bool:
        """Fail-closed oracle input (§3.10.6): generation must match AND no
        .index-dirty flag AND no uningested sealed segment AND the index
        must have swallowed the bytes the caller observed.

        ``min_tag`` is the caller-snapshot inode tag of events.jsonl
        (``st_dev:st_ino``). When it still matches the live file the plain
        watermark>=min_offset comparison is honest. When it does not, the
        file the offset pointed into rotated into sealed/: the bytes are
        covered iff every sealed segment is ingested — and at least one
        must exist, else the tail was wiped by a foreign hand, not a seal.
        False = caller must NOT issue 'absent→放行'."""
        if self.dirty():
            return False
        gen_now, watermark = self.sealed_state()
        if gen_now != int(gen):
            return False
        if min_tag and _file_tag(paths.events_path()) != min_tag:
            return bool(_sealed_segment_names()) and self._sealed_covered()
        return self._sealed_covered() and watermark >= int(min_offset)

    def done(self, idc, arm, up, variant, stage, runs=None) -> bool:
        """Terminal status in cells for (idc,arm,up,variant,stage).

        Terminal = DONE ∪ KERNEL statuses — dedup/claimed/lost/unpaid_gate
        are terminal too (fail-closed direction for paid cells). When runs
        is given, the cell's latest state must come from one of those runs
        (needs-eval domain = this run ∪ spec.foreign_runs).
        """
        row = self.conn.execute(
            "SELECT status, last_run FROM cells"
            " WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=?",
            (idc, arm, up, variant, stage),
        ).fetchone()
        if row is None or row["status"] not in _TERMINAL:
            return False
        if runs is not None:
            if isinstance(runs, str):
                runs = {runs}
            if row["last_run"] not in runs:
                return False
        return True

    def last_cell(self, idc, arm, up, variant, stage) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM cells"
            " WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=?",
            (idc, arm, up, variant, stage),
        ).fetchone()
        return dict(row) if row else None

    def paid_pool(self, stages=None) -> set[tuple]:
        """(idc,arm,variant) whose latest cell state is terminal ok|partial —
        the index leg of the paid dedup domain for plan snapshots (§3.10.6).

        ``stages`` MUST be the spec's paid stages on the spend path — an
        ok row from a FREE stage (ingest/report) mints no paid-verified
        evidence; without the filter it leaks into the pool and dedups the
        paid cell forever (§3.10.6 verified leg is stage-scoped).
        None = all stages (reconciliation callers only)."""
        sql = (
            "SELECT DISTINCT idc,arm,variant FROM cells"
            " WHERE status IN ('ok','partial')"
        )
        args: list = []
        if stages is not None:
            sql += f" AND stage IN ({','.join('?' * len(stages))})"
            args += sorted(stages)
        return {
            (r["idc"], r["arm"], r["variant"]) for r in self.conn.execute(sql, args)
        }

    def vault_bytes_ok(self) -> set[tuple]:
        """(idc,arm,variant) with verified vault bytes (§3.8 dedup-hit
        verdicts: verified/primary/alt/quar/quarantine/adopted)."""
        marks = ",".join("?" for _ in _VAULT_BYTES_OK)
        return {
            (r["idc"], r["arm"], r["variant"])
            for r in self.conn.execute(
                f"SELECT DISTINCT idc,arm,variant FROM vault_meta"  # noqa: S608 -- marks 是 "?"*n 占位符
                f" WHERE verdict IN ({marks})",
                tuple(sorted(_VAULT_BYTES_OK)),
            )
        }

    def active_claims(self) -> set[tuple]:
        """(idc,arm,variant) whose latest claim op is 'acquire'.

        slot-bearing rows are the paid_slots mirror stream — a separate
        channel multiplexed on the same table; only slot IS NULL rows are
        claim-lifecycle evidence.
        """
        return {
            (r["idc"], r["arm"], r["variant"])
            for r in self.conn.execute(
                "SELECT c.idc, c.arm, c.variant FROM claims c"
                " WHERE c.slot IS NULL AND c.op='acquire' AND c.rowid ="
                " (SELECT MAX(rowid) FROM claims c2"
                "  WHERE c2.idc=c.idc AND c2.arm=c.arm"
                "  AND c2.variant=c.variant AND c2.slot IS NULL)"
            )
        }

    def dedup_skip_count(self) -> int:
        return int(self._meta_get("dedup_skip", "0") or 0)

    def quarantine_count(self) -> int:
        return int(self._meta_get("quarantine", "0") or 0)

    def note_dirty(self, reason: str = "") -> None:
        """Set ledger/.index-dirty — emit path calls this when its sqlite
        write failed after the ledger line landed (§3.10.6 ③)."""
        p = paths.index_dirty_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{round(time.time(), 3)} {reason}\n", encoding="utf-8")

    def dirty(self) -> bool:
        return paths.index_dirty_path().exists()
