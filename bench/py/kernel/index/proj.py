"""index 类型投影 mixin —— events 镜像 → 各类型投影表。

- ``_project`` — REQUIRED-keys 闸 (缺键事件只进镜像不进类型表) + 类型
  路由; papers 别名表是尾钩 (任何同载 id/idc 的事件都登记，§3.2)。
- ``_proj_cell`` — cells (idc,arm,up,variant,stage) LWW upsert;
  cell_queued 同步落 cases 排队单; cell 终态落 records, eval 域
  (eval_stages ∪ eval=1 标记) 复写 eval_records。
- ``_proj_claim`` — claims 追加 + paid_slots 镜像流：reap 清整键，
  acquire 占位 upsert, release 删槽。
- ``_proj_asset``/``_upsert_vault_meta`` — assets 追加; vault 管理类
  kind 同步 upsert vault_meta 凭证面 (verdict 显式优先，否则 state 映射)。

只被 ``index.core.Index`` 继承; 不 import 兄弟叶 (常量走 ``index.common``)。
"""

from __future__ import annotations

from kernel import events
from kernel.index.common import (
    _STATUS_QUEUED,
    _STATUS_STARTED,
    _VAULT_KINDS,
    _j,
)


class _ProjMixin:
    def _project(self, ev: dict, run_seq: int, seq: int) -> None:
        t = ev.get("type")
        # Projection gate: only events carrying their REQUIRED key set feed
        # typed tables; everything still lands in the events mirror.
        req = events.REQUIRED.get(t)
        if req is not None and not req <= ev.keys():
            return
        cur = self.conn
        if t in (events.T_CELL_QUEUED, events.T_CELL_STARTED, events.T_CELL):
            self._proj_cell(cur, ev, t)
        elif t == events.T_CASE:
            # Author eval rows (Ctx.emit_case) — same sink as the queued
            # manifest; payload is the author's dict, not the whole event.
            cur.execute(
                "INSERT INTO cases(run,seq,id,idc,stage,payload,ts)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    ev.get("run"),
                    ev.get("seq"),
                    ev.get("id"),
                    ev.get("idc"),
                    ev.get("stage"),
                    _j(ev.get("payload")),
                    ev.get("ts"),
                ),
            )
        elif t == events.T_CLAIM:
            self._proj_claim(cur, ev)
        elif t == events.T_ASSET:
            self._proj_asset(cur, ev)
        elif t == events.T_TOMBSTONE:
            self._upsert_vault_meta(
                cur, ev, verdict="tombstone", zone=ev.get("zone", "quar")
            )
        elif t == events.T_RUN_REGISTERED:
            cur.execute(
                "INSERT INTO runs(run,run_seq,kind,date,slug,spec_hash,ts_start)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(run) DO UPDATE SET"
                "  run_seq=excluded.run_seq, kind=excluded.kind,"
                "  date=excluded.date, slug=excluded.slug,"
                "  spec_hash=excluded.spec_hash, ts_start=excluded.ts_start",
                (
                    ev.get("run"),
                    ev.get("run_seq"),
                    ev.get("kind"),
                    ev.get("date"),
                    ev.get("slug"),
                    ev.get("spec_hash"),
                    ev.get("ts_start", ev.get("ts")),
                ),
            )
        # papers alias table: any event carrying both spellings (§3.2).
        if ev.get("id") and ev.get("idc"):
            src = ev.get("import_src") or ev.get("run") or "ledger"
            cur.execute(
                "INSERT OR IGNORE INTO papers(idc,id_raw,src) VALUES (?,?,?)",
                (ev["idc"], ev["id"], src),
            )

    def _proj_cell(self, cur, ev: dict, t: str) -> None:
        if t == events.T_CELL_QUEUED:
            status = _STATUS_QUEUED
        elif t == events.T_CELL_STARTED:
            status = _STATUS_STARTED
        else:
            status = ev.get("status")
        cur.execute(
            "INSERT INTO cells"
            "(idc,arm,up,variant,stage,last_run,last_seq,status,cat,fp,ts)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(idc,arm,up,variant,stage) DO UPDATE SET"
            "  last_run=excluded.last_run, last_seq=excluded.last_seq,"
            "  status=excluded.status, cat=excluded.cat,"
            "  fp=excluded.fp, ts=excluded.ts",
            (
                ev.get("idc"),
                ev.get("arm"),
                ev.get("up"),
                ev.get("variant"),
                ev.get("stage"),
                ev.get("run"),
                ev.get("seq"),
                status,
                ev.get("cat"),
                ev.get("fp"),
                ev.get("ts"),
            ),
        )
        if t == events.T_CELL_QUEUED:
            cur.execute(
                "INSERT INTO cases(run,seq,id,idc,stage,payload,ts)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    ev.get("run"),
                    ev.get("seq"),
                    ev.get("id"),
                    ev.get("idc"),
                    ev.get("stage"),
                    events.dumps(ev),
                    ev.get("ts"),
                ),
            )
        elif t == events.T_CELL:
            row = (
                ev.get("run"),
                ev.get("seq"),
                ev.get("id"),
                ev.get("idc"),
                ev.get("arm"),
                ev.get("up"),
                ev.get("variant"),
                ev.get("stage"),
                ev.get("status"),
                ev.get("cat"),
                ev.get("sig"),
                ev.get("code"),
                ev.get("fp"),
                ev.get("dur_s"),
                _j(ev.get("metrics")),
                _j(ev.get("errors")),
                ev.get("ts"),
            )
            cur.execute(
                "INSERT INTO records"
                "(run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
                " fp,dur_s,metrics,errors,ts)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row,
            )
            # eval lane: stage declared eval by the caller, or a row the
            # caller tagged eval=1 (import paths bypass the cell whitelist).
            if ev.get("stage") in self.eval_stages or ev.get("eval"):
                cur.execute(
                    "INSERT INTO eval_records"
                    "(run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
                    " fp,dur_s,metrics,errors,ts)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    row,
                )

    def _proj_claim(self, cur, ev: dict) -> None:
        cur.execute(
            "INSERT INTO claims(idc,arm,variant,run,seq,op,slot,fate,ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ev.get("idc"),
                ev.get("arm"),
                ev.get("variant"),
                ev.get("run"),
                ev.get("seq"),
                ev.get("op"),
                ev.get("slot"),
                ev.get("fate"),
                ev.get("ts"),
            ),
        )
        if ev.get("op") == "reap":
            # a reap clears every paid_slots mirror row the reaped key
            # left behind, whichever slot it sat in
            cur.execute(
                "DELETE FROM paid_slots WHERE idc=? AND arm=? AND variant=?",
                (ev.get("idc"), ev.get("arm"), ev.get("variant")),
            )
            return
        slot = ev.get("slot")
        if slot is None:
            return
        if ev.get("op") == "acquire":
            cur.execute(
                "INSERT INTO paid_slots(slot,idc,arm,variant,run,ts)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(slot) DO UPDATE SET"
                "  idc=excluded.idc, arm=excluded.arm,"
                "  variant=excluded.variant, run=excluded.run, ts=excluded.ts",
                (
                    slot,
                    ev.get("idc"),
                    ev.get("arm"),
                    ev.get("variant"),
                    ev.get("run"),
                    ev.get("ts"),
                ),
            )
        elif ev.get("op") == "release":
            cur.execute("DELETE FROM paid_slots WHERE slot=?", (slot,))

    def _proj_asset(self, cur, ev: dict) -> None:
        cur.execute(
            "INSERT INTO assets"
            "(idc,arm,variant,kind,path,sha,bytes,state,run,seq,ts)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                ev.get("idc"),
                ev.get("arm"),
                ev.get("variant"),
                ev.get("kind"),
                ev.get("path"),
                ev.get("sha"),
                ev.get("bytes"),
                ev.get("state"),
                ev.get("run"),
                ev.get("seq"),
                ev.get("ts"),
            ),
        )
        # Vault-managed byte kinds also feed the vault_meta credential view;
        # verdict is explicit when carried, else mapped from asset state.
        if ev.get("kind") in _VAULT_KINDS:
            self._upsert_vault_meta(
                cur,
                ev,
                verdict=ev.get("verdict") or ev.get("state"),
                zone=ev.get("zone"),
            )

    def _upsert_vault_meta(self, cur, ev: dict, *, verdict, zone) -> None:
        cur.execute(
            "INSERT INTO vault_meta"
            "(idc,arm,variant,altseq,zone,verdict,path,sha,ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(idc,arm,variant,altseq) DO UPDATE SET"
            "  zone=excluded.zone, verdict=excluded.verdict,"
            "  path=excluded.path, sha=excluded.sha, ts=excluded.ts",
            (
                ev.get("idc"),
                ev.get("arm"),
                ev.get("variant"),
                str(ev.get("altseq", "0")),
                zone,
                verdict,
                ev.get("path"),
                ev.get("sha"),
                ev.get("ts"),
            ),
        )
