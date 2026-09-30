"""kernel._kernel_needs — needs 域求值叶 (kernel.kernel 拆分叶，§3.6).

cell 临界段第 4 步的 upstream 裁决机件：

- ``_last_outcome`` — 跨 run 的末条 T_CELL records 行 (dedup 指针与
  ``declined:*`` gate reject 皆透明 — 无裁决语义的行不遮蔽真终态)
- ``_last_rec``     — key 的末条 records 行 (rowid 序), domain/statuses
                      过滤变体
- ``_product_ok``   — mutating upstream 的"产物可解析"per-kind 证据
                      (vault 在押 + 本 run work 树; tombstone 否决
                      不被 vault 字节翻案)
- ``_needs_eval``   — needs 边求值：domain = this run ∪ spec.foreign_runs,
                      末条 domain 行管判 (dedup 穿掩到末条 DONE)

门面回引名单见 ``kernel.kernel._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kernel import dedup as dedupmod
from kernel import events, vault

if TYPE_CHECKING:
    from pathlib import Path

    from kernel import runs
    from kernel.spec import Spec


def _last_outcome(idx, idc, arm, up, variant, stage) -> dict | None:
    """Last T_CELL records row for the key across ALL runs.

    The `cells` table is a latest-state projection — this run's own
    cell_queued/cell_started events mask prior terminal outcomes to
    'queued'/'started'. `records` holds T_CELL rows only, so it is the
    honest outcome history the self-dedup check must read (§3.1).

    Two row shapes are transparent to this scan — neither is a verdict:

    - `dedup` rows are pointers at an earlier verdict (needs_eval
      already resolves them to the last DONE row the same way). Reading
      through them lands on the verdict they resolved to — except when
      the chain bottoms at a declined row, which is the poison case
      below.
    - `reject` rows with sig `declined:*` are gate verdicts over the
      upstream state at emit time (needs-free collector stages keep
      their gates inside the fn). They must stay DONE — the terminal
      emit fires the last-mutating-stage harvest — but upstream revival
      makes them stale, so they never count as work evidence and the fn
      re-evaluates its gates every run.
    """
    row = idx.conn.execute(
        "SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
        "fp,dur_s,metrics,errors,ts FROM records "
        "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=? "
        "AND status != 'dedup' "
        "AND NOT (status = 'reject' AND COALESCE(sig, '') "
        "         LIKE 'declined:%') "
        "ORDER BY rowid DESC LIMIT 1",
        (idc, arm, up, variant, stage),
    ).fetchone()
    return dict(row) if row is not None else None


def _last_rec(
    idx, idc, arm, up, variant, stage, domain=None, statuses=None
) -> dict | None:
    """Last records row for the key — newest ledger row wins (rowid)."""
    sql = (
        "SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
        "fp,dur_s,metrics,errors,ts FROM records "
        "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=?"
    )
    args: list = [idc, arm, up, variant, stage]
    if domain is not None:
        dom = sorted(domain)
        sql += f" AND run IN ({','.join('?' * len(dom))})"
        args += dom
    if statuses is not None:
        sts = sorted(statuses)
        sql += f" AND status IN ({','.join('?' * len(sts))})"
        args += sts
    sql += " ORDER BY rowid DESC LIMIT 1"
    row = idx.conn.execute(sql, args).fetchone()
    return dict(row) if row is not None else None


def _dir_has_files(d: Path) -> bool:
    try:
        return d.is_dir() and any(p.is_file() for p in d.rglob("*"))
    except OSError:
        return False


def _product_ok(
    rd: runs.RunDir,
    cell: dict,
    up_stage: str,
    up_spec,
    rec: dict,
    idc: str,
    arm: str,
    variant: str,
    safe: str,
) -> bool:
    """'产物可解析' for a mutating upstream — PER-KIND, never cell-level.

    A kind counts through evidence the stage fn can actually REACH: an
    intact vault copy declaring it (ctx restores via vault.restore), or
    this run's own work tree. The upstream run's work tree is NOT
    evidence — ctx.upstream_asset_dir can only read this run's
    paper_dir, so bytes stranded in a foreign run dir greenlight a cell
    that then crash-loops on FileNotFoundError. A manifest-dead kind
    (tombstone/loss row with no later revive) vetoes the whole product
    UNLESS fresh work-tree bytes exist for it — vault-intact bytes do
    NOT revive a tombstoned kind, because tombstone is a verdict-layer
    loss record that deliberately leaves bytes on disk. The old
    cell-level bytes_ok leg let a live 'state' copy mask a tombstoned
    'zh' — downstream then burned paid requests against a product the
    ledger had already declared lost."""
    if not up_spec or not up_spec.mutates:
        return True
    try:
        ev = dedupmod.manifest_kind_evidence().get((idc, arm, variant))
    except Exception:
        ev = None
    dead = ev["dead"] if ev else set()
    try:
        vrows = vault.query(idc, arm, variant)
    except Exception:
        vrows = []
    base = rd.work(safe)
    lost = present = False
    for k in up_spec.mutates:
        work = _dir_has_files(base / vault._work_dirname(k, arm, variant))
        intact = any(
            isinstance(r.get("files"), dict) and k in r["files"] and r.get("bytes_ok")
            for r in vrows
        )
        if k in dead and not work:
            lost = True
        elif intact or work:
            present = True
    return present and not lost


def _needs_eval(rd: runs.RunDir, spec: Spec, idx, cell: dict, safe: str):
    """Evaluate the cell's needs edges (§3.6 needs domain).

    Returns ("proceed", primary_upstream_rec|None)
         | ("skip", reason)
         | ("fault", "upstream-lost").

    Domain = this run ∪ spec.foreign_runs. The LAST domain row governs:
    'dedup' resolves through the mask to the last DONE row anywhere (a
    dedup terminal in this run IS the declaration that the work is done);
    every other non-DONE row falls back to the last DONE row in domain —
    a retriable retry after an ok still counts the ok.
    """
    stage = spec.stage(cell["stage"])
    if stage is None:
        return ("skip", f"stage {cell['stage']} not in spec")
    domain = {rd.run} | set(spec.foreign_runs or [])
    primary = None
    for up_stage, _accept in stage.needs:
        latest = _last_rec(
            idx,
            cell["idc"],
            cell["arm"],
            cell["up"],
            cell["variant"],
            up_stage,
            domain=domain,
        )
        if latest is None:
            return ("skip", f"needs {up_stage}: no record in domain")
        if latest["status"] == "dedup":
            rec = _last_rec(
                idx,
                cell["idc"],
                cell["arm"],
                cell["up"],
                cell["variant"],
                up_stage,
                statuses=events.STATUS_DONE,
            )
        else:
            rec = _last_rec(
                idx,
                cell["idc"],
                cell["arm"],
                cell["up"],
                cell["variant"],
                up_stage,
                domain=domain,
                statuses=events.STATUS_DONE,
            )
        if rec is None:
            return (
                "skip",
                (f"needs {up_stage}: no done row (latest domain: {latest['status']})"),
            )
        accept = stage.accept_for(up_stage)
        if rec["status"] not in accept:
            return (
                "skip",
                (
                    f"needs {up_stage}: status {rec['status']!r} "
                    f"not in accept {sorted(accept)}"
                ),
            )
        up_spec = spec.stage(up_stage)
        if not _product_ok(
            rd,
            cell,
            up_stage,
            up_spec,
            rec,
            cell["idc"],
            cell["arm"],
            cell["variant"],
            safe,
        ):
            return ("fault", "upstream-lost")
        if primary is None:
            primary = rec
    return ("proceed", primary)
