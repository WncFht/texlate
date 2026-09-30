"""verbs.dossier cli 叶 —— add_args 参数面 + main 编排（dossier.py 拆分叶）。

门面回引名单见 ``verbs.dossier._LEAF_EXPORTS``。
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

from kernel import idnorm, paths, vault

from verbs._common import _open_index, _rundir, _stem_of
from verbs._dossier_attrib import _cross_run, _end_state
from verbs._dossier_env import _load_registry, _maybe_reexec_venv
from verbs._dossier_fetch import (
    _fetch_cases,
    _fetch_records,
    _group_stages,
    _invocations,
    _resolve_run_group,
    load_tickets,
)
from verbs._dossier_render import build_dossier, render_md
from verbs._dossier_work import work_inventory

# ---------------------------------------------------------------- cli


def add_args(sp) -> None:
    sp.add_argument(
        "id", nargs="?", help="arxiv id（cat/YYMMNNN、YYMM.NNNNN 或 safe 形）"
    )
    sp.add_argument(
        "--run",
        default=None,
        help="钉 run（精确名/唯一前缀/stem——import 兄弟组自动并组；"
        "缺省选含此 id 的最新 run_seq 账组）",
    )
    sp.add_argument(
        "--diff",
        default=None,
        metavar="RUN",
        help="与另一 run 做 end-state 对账（波前后迁移）",
    )
    sp.add_argument("--all-runs", action="store_true", help="附跨 run 出现史")
    sp.add_argument(
        "--json", action="store_true", dest="as_json", help="机读 dossier dict 输出"
    )
    sp.add_argument(
        "-o", "--out", type=Path, default=None, help="写文件（缺省 stdout）"
    )


def main(args) -> int:
    _maybe_reexec_venv()
    if not args.id:
        print("dossier: id 必填", file=sys.stderr)
        return 2

    res = idnorm.canon_id(args.id, registry=_load_registry())
    if not res.ok:
        cands = f" candidates={res.candidates}" if res.candidates else ""
        print(
            f"dossier: canon 不可解 {args.id!r}: {res.reason}{cands}", file=sys.stderr
        )
        return 2
    idc = res.idc
    safe = idnorm.safe_id(idc)
    cands = list(dict.fromkeys([args.id, idc, safe]))
    cand_set = set(cands)

    idx = _open_index()

    group = None
    if args.run:
        group, err = _resolve_run_group(idx, args.run)
        if err is not None:
            print(f"dossier: {err}", file=sys.stderr)
            return 2
        run_names = [str(r["run"]) for r in group]
        rows = _fetch_records(idx, cands, run_names)
        if not rows:
            print(f"dossier: {idc} 不在 {args.run!r} 账组里", file=sys.stderr)
            return 2
    else:
        rows = _fetch_records(idx, cands)
        if not rows:
            cases_probe = _fetch_cases(idx, cands)
            if not cases_probe:
                # workdir 兜底：run_seq 倒序找 work/{safe}
                run_rows = [
                    dict(r)
                    for r in idx.conn.execute(
                        "SELECT run, run_seq, kind, date, slug FROM runs"
                        " ORDER BY run_seq DESC"
                    ).fetchall()
                ]
                hit = None
                for rr in run_rows:
                    rd = _rundir(rr)
                    if rd and (rd / "work" / safe).is_dir():
                        hit = rr
                        break
                if hit is None:
                    print(
                        f"dossier: {idc} 查无此人（records/cases/work 三路全空）",
                        file=sys.stderr,
                    )
                    return 2
                group = [hit]
                run_names = [str(hit["run"])]
            else:
                seen = {}
                for rr in idx.conn.execute(
                    "SELECT run, run_seq, kind, date, slug FROM runs"
                ):
                    seen[rr["run"]] = dict(rr)
                # cases 的 run 归属取最新出现者
                ph = ",".join("?" for _ in cands)
                crows = idx.conn.execute(
                    "SELECT DISTINCT run FROM cases"  # noqa: S608 — 值全走占位符参数化
                    f" WHERE idc IN ({ph}) OR id IN ({ph})",
                    list(cands) + list(cands),
                ).fetchall()
                best = max(
                    (seen.get(cr["run"]) for cr in crows),
                    key=lambda r: (r or {}).get("run_seq") or -1,
                    default=None,
                )
                group = [best] if best else []
                run_names = [str(best["run"])] if best else []
        else:
            latest_run = max((r for r in rows), key=lambda r: r.get("run_seq") or -1)[
                "run"
            ]
            group, _ = _resolve_run_group(idx, latest_run)
            run_names = [str(r["run"]) for r in (group or [])]
            if group and len(group) > 1:
                rows = _fetch_records(idx, cands, run_names)

    run_names = [str(r["run"]) for r in (group or [])] if group else run_names
    recs = _group_stages(rows)
    cases = _fetch_cases(idx, cands, run_names or None)
    stem = _stem_of(run_names[-1]) if run_names else idc
    run_label = stem if len(run_names) > 1 else (run_names[-1] if run_names else "-")

    # workdir：组内 run_seq 倒序找第一个有 work/{safe} 的 rundir
    primary = (group or [])[-1] if group else None
    wdir = None
    for rr in reversed(group or []):
        rd = _rundir(rr)
        if rd and (rd / "work" / safe).is_dir():
            wdir = rd / "work" / safe
            break
    if wdir is None and primary is not None:
        rd = _rundir(primary)
        wdir = (rd / "work" / safe) if rd else Path(f"<no-rundir>/{safe}")
    if wdir is None:
        wdir = Path(f"<no-run>/{safe}")
    inv = work_inventory(wdir)

    vault_copies = []
    if not inv.get("present"):
        with contextlib.suppress(Exception):
            vault_copies = vault.query(idc)

    # tickets：本组 rundirs + 全 rundir 面（prior 票史）
    group_rds = [rd for rd in (_rundir(r) for r in (group or [])) if rd]
    all_rds = [p for p in sorted(paths.runs_dir().glob("*/*/*")) if p.is_dir()]
    prior_tickets = load_tickets(cand_set, all_rds or group_rds)

    prior_waves = sorted({str(r.get("run")) for r in rows})
    primary_rd = _rundir(primary)
    run_info = primary
    invocs = _invocations(primary_rd)

    all_runs = None
    if args.all_runs:
        group_rundirs = {str(r["run"]): _rundir(r) for r in (group or [])}
        all_runs = _cross_run(rows, group_rundirs, safe)

    diff = None
    if args.diff:
        dgroup, derr = _resolve_run_group(idx, args.diff)
        if derr is not None:
            print(f"dossier: --diff {derr}", file=sys.stderr)
            return 2
        dnames = [str(r["run"]) for r in dgroup]
        drows = _fetch_records(idx, cands, dnames)
        dwdir = None
        for rr in reversed(dgroup or []):
            rd = _rundir(rr)
            if rd and (rd / "work" / safe).is_dir():
                dwdir = rd / "work" / safe
                break
        diff = {
            "a": _end_state(recs, wdir if inv.get("present") else None),
            "b": _end_state(_group_stages(drows), dwdir),
            "a_name": run_label,
            "b_name": args.diff,
        }

    d = build_dossier(
        args.id,
        cand_set,
        recs,
        cases,
        wdir,
        inv,
        run_label=run_label,
        run_info=run_info,
        invocations=invocs,
        vault_copies=vault_copies,
        prior_waves=prior_waves,
        prior_tickets=prior_tickets,
        all_runs=all_runs,
        diff=diff,
    )
    text = (
        json.dumps(d, ensure_ascii=False, indent=1, default=str)
        if args.as_json
        else render_md(d)
    )
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"→ {args.out}")
    else:
        print(text)
    return 0
