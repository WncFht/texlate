"""kernel._cli_status — status 动词叶 (kernel.cli 拆分叶).

``bench status`` 的三条读径: --tail 直读 ledger 事件 (真源不过
index)、--id 查 cell 状态 + vault 副本、--run 查单 run 格表;
默认面列全 run + 活动标记。读侧件, 无写径。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

from collections import deque

from kernel import events, idnorm, paths, runs, vault
from kernel._cli_common import EXIT_OK, _err, _open_index


def _event_line(ev: dict) -> str:
    bits = [
        f"seq={ev.get('run_seq', '-')}/{ev.get('seq', '-')}",
        str(ev.get("type")),
    ]
    if ev.get("run"):
        bits.append(f"run={ev['run']}")
    if ev.get("id"):
        bits.append(f"id={ev['id']}")
    bits.extend(
        f"{k}={ev[k]}"
        for k in ("stage", "status", "cat", "verdict", "state", "level")
        if ev.get(k)
    )
    return " ".join(bits)


def _cmd_status(args) -> int:
    if args.tail is not None:
        # Read the ledger directly — the source of truth needs no index.
        tail: deque = deque(maxlen=max(0, args.tail))
        ep = paths.events_path()
        if ep.exists():
            for _ln, ev, _raw in events.iter_jsonl(ep):
                if ev is not None:
                    tail.append(ev)
        for ev in tail:
            print(_event_line(ev))
        return EXIT_OK

    idx = _open_index()
    try:
        if args.id:
            res = idnorm.canon_id(args.id)
            idc = res.idc if res.ok else args.id
            print(
                f"id: {args.id}  idc: {idc}"
                + ("" if res.ok else f"  (canon: {res.state} {res.reason})")
            )
            rows = idx.conn.execute(
                "SELECT idc,arm,up,variant,stage,status,cat,last_run,ts"
                " FROM cells WHERE idc=? OR idc=? ORDER BY stage",
                (idc, args.id),
            ).fetchall()
            if not rows:
                print("  (no cells)")
            for r in rows:
                print(
                    f"  {r['stage']:<12} {r['status'] or '-':<10}"
                    f" arm={r['arm']} variant={r['variant']}"
                    f" cat={r['cat'] or '-'} run={r['last_run']}"
                )
            try:
                copies = vault.query(idc)
            except Exception as exc:
                copies = []
                _err(f"note: vault query failed ({exc})")
            for c in copies:
                print(
                    f"  vault altseq={c.get('altseq')} zone={c.get('zone')}"
                    f" verdict={c.get('verdict')} bytes_ok={c.get('bytes_ok')}"
                )
            return EXIT_OK

        if args.run:
            rows = idx.conn.execute(
                "SELECT idc,arm,variant,stage,status,cat FROM cells"
                " WHERE last_run=? ORDER BY idc,stage",
                (args.run,),
            ).fetchall()
            print(f"run: {args.run}  cells: {len(rows)}")
            tally: dict[str, int] = {}
            for r in rows:
                tally[r["status"] or "?"] = tally.get(r["status"] or "?", 0) + 1
                print(
                    f"  {r['idc']:<18} {r['stage']:<12} {r['status'] or '-'}"
                    f" arm={r['arm']} variant={r['variant']}"
                    f" cat={r['cat'] or '-'}"
                )
            if tally:
                print(
                    "  tally: " + " ".join(f"{k}={v}" for k, v in sorted(tally.items()))
                )
            return EXIT_OK

        active = {a["run"] for a in runs.active_runs()}
        rows = idx.conn.execute(
            "SELECT run,run_seq,kind,date,slug,ts_start FROM runs ORDER BY run_seq"
        ).fetchall()
        print(f"bench root: {paths.root()}")
        print(f"runs: {len(rows)}  active: {len(active)}")
        for r in rows:
            mark = " *active*" if r["run"] in active else ""
            n = idx.conn.execute(
                "SELECT COUNT(*) FROM cells WHERE last_run=?", (r["run"],)
            ).fetchone()[0]
            print(f"  seq={r['run_seq']:<4} {r['run']}  cells={n}{mark}")
        if not rows:
            print("  (no runs yet)")
        return EXIT_OK
    finally:
        idx.close()
