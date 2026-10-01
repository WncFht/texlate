"""index 事件应用 mixin —— ledger event → events 镜像 + dedupe + quarantine。

- ``apply_event``/``apply_events`` — 单条/批量应用入口 (各自一条 _txn)。
- ``_key_of`` — (run_seq,seq) 去重键决议：run 事件先查 runs 表; run-less
  事件 run_seq=-1 + assigned seq 走深负段 (-(1<<40)-n), 永不撞 kernel
  seq 的 -1..-N 带。
- ``_apply_one`` — payload_sha 全表 dedupe 先行 → events PK 冲突分流：
  同 sha = replay (dedup_skip++), 异 sha = ledger 损坏 → quarantine
  不抛出 (毒 payload 同步入 dedupe 防重放再隔离)。
- ``_quarantine`` — 单发 O_APPEND os.write 落 ledger/quarantine.jsonl;
  index 永不取 ledger/.lock (可能在 emit 临界段内被调，取锁即死锁)。

只被 ``index.core.Index`` 继承; 不 import 兄弟叶。
"""

from __future__ import annotations

import os
import time

from kernel import events, paths


class _ApplyMixin:
    def apply_event(self, ev: dict) -> str:
        """Apply one ledger event. Returns 'applied' | 'replay' | 'quarantined'."""
        with self._txn():
            return self._apply_one(ev)

    def apply_events(self, evs) -> int:
        """Batched apply in a single transaction. Returns rows newly applied."""
        applied = 0
        with self._txn():
            for ev in evs:
                if self._apply_one(ev) == "applied":
                    applied += 1
        return applied

    def _key_of(self, ev: dict, *, runless: bool) -> tuple[int, int]:
        """Resolve the (run_seq, seq) dedup key.

        run events: explicit run_seq, else resolve via the runs table
        (run_registered precedes its cells in ledger order).
        run-less events: run_seq=-1 + index-assigned seq from a meta counter.
        Events with a run_seq but no seq (run_registered itself) also draw
        from the counter — assigned seqs are NEGATIVE so they can never
        collide with a minted seq on the same run_seq.
        """
        run_seq = ev.get("run_seq")
        if run_seq is None and not runless:
            run = ev.get("run")
            if run is not None:
                row = self.conn.execute(
                    "SELECT run_seq FROM runs WHERE run=?", (run,)
                ).fetchone()
                run_seq = row["run_seq"] if row else None
        if run_seq is None:
            run_seq = -1
        seq = ev.get("seq")
        if seq is None:
            # Deep negative band: kernel seqs (sweep adjudication rows) live
            # at -1..-N under real run_seqs — an assigned seq in that range
            # collides on the (run_seq,seq) primary key and quarantines or
            # replay-drops a legitimate event.
            seq = -(1 << 40) - self._meta_incr("runless_seq")
        return int(run_seq), int(seq)

    def _apply_one(self, ev: dict, *, runless: bool = False) -> str:
        if not isinstance(ev, dict):
            msg = f"event must be a dict, got {type(ev).__name__}"
            raise TypeError(msg)
        sha = events.content_hash(ev)
        if self.conn.execute(
            "SELECT 1 FROM dedupe WHERE payload_sha=?", (sha,)
        ).fetchone():
            self._meta_incr("dedup_skip")
            return "replay"
        run_seq, seq = self._key_of(ev, runless=runless)
        res = self.conn.execute(
            "INSERT OR IGNORE INTO events"
            "(line_no,run_seq,seq,payload_sha,payload,ts,type)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                self._next_line_no(),
                run_seq,
                seq,
                sha,
                events.dumps(ev),
                ev.get("ts"),
                ev.get("type"),
            ),
        )
        if res.rowcount == 0:
            # (run_seq,seq) already present — compare payload (§3.10.5).
            row = self.conn.execute(
                "SELECT payload_sha FROM events WHERE run_seq=? AND seq=?",
                (run_seq, seq),
            ).fetchone()
            if row is not None and row["payload_sha"] == sha:
                self._meta_incr("dedup_skip")
                self.conn.execute(
                    "INSERT OR IGNORE INTO dedupe(payload_sha) VALUES (?)", (sha,)
                )
                return "replay"
            self._quarantine(ev, sha, run_seq, seq, row["payload_sha"] if row else None)
            # Mark the rejected payload too: replays of it must not re-quarantine.
            self.conn.execute(
                "INSERT OR IGNORE INTO dedupe(payload_sha) VALUES (?)", (sha,)
            )
            return "quarantined"
        self.conn.execute("INSERT INTO dedupe(payload_sha) VALUES (?)", (sha,))
        self._project(ev, run_seq, seq)
        return "applied"

    def _quarantine(self, ev, sha, run_seq, seq, existing_sha) -> None:
        """Append a corruption row to ledger/quarantine.jsonl.

        Single O_APPEND os.write mirrors the torn-tail contract; index never
        takes ledger/.lock (it may be called from inside the emit critical
        section — taking it would deadlock).
        """
        rec = {
            "type": "index_conflict",
            "reason": "seq_conflict",
            "run_seq": run_seq,
            "seq": seq,
            "payload_sha": sha,
            "existing_sha": existing_sha,
            "payload": events.dumps(ev),
            "ts": round(time.time(), 3),
        }
        line = (events.dumps(rec) + "\n").encode("utf-8")
        qp = paths.quarantine_path()
        qp.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(qp, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._meta_incr("quarantine")
