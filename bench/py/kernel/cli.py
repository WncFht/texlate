"""bench — the single CLI entry point for the trizone-ledger kernel (§2.1).

Every bench verb is a subcommand of one argparse program::

    bench init | run | plan | status | vault | ledger | lake
    bench derive | sweep | prune | backup | doctor | fsck | spec
    bench triage | gate | dossier          (analysis verbs — §5.2 queue)

Contract baked here:

- Write commands run a light sweep first (§2.4 — the reaper has an owner).
  The sweep module is a wave-C sibling; while it is absent the hook is a
  loud no-op, never a silent skip.
- ``run`` refuses while $ROOT/PAUSE exists only for PAID specs
  (locks.pause_engaged + spec.has_paid — Phase 3 rescope: the fence stops
  spend, not free work; ``plan`` always runs).
- ``--detach`` re-execs through locks.detach_with_lock (R22: the child
  holds the lock itself); a paid spec additionally requires --max-cost
  (§3.6 — detach forces the budget flag).
- kernel.kernel (run/plan), kernel.spec, kernel.sweep, kernel.doctor are
  wave-C sibling modules imported lazily — the CLI works for every verb
  that only needs foundation/zone modules, and reports a clean
  "not yet available" (exit 2) for the rest instead of crashing.

Exit codes: 0 ok · 1 command ran but reported failure · 2 refused /
unavailable / not yet implemented.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from collections import deque
from pathlib import Path

from kernel import (
    cache as cachemod,
)
from kernel import (
    cas,
    events,
    fsutil,
    idnorm,
    importer,
    lake,
    locks,
    paths,
    report,
    runs,
    vault,
)
from kernel import index as index_mod

__all__ = ["main"]

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_REFUSED = 2

_NOT_IMPLEMENTED = "not yet implemented — index-reading analysis verb lands with the §5.2 rewrite queue"


# --- small helpers ---------------------------------------------------------------


def _err(msg: str) -> None:
    print(f"bench: {msg}", file=sys.stderr)


def _lazy(modname: str):
    """Import a wave-C sibling kernel module; (module, None) or (None, err)."""
    try:
        return importlib.import_module(f"kernel.{modname}"), None
    except Exception as exc:  # ImportError AND in-module failures — report, don't hide
        return None, exc


def _specs_dir() -> Path:
    """bench/py/specs — the spec-file home (this file lives in kernel/)."""
    return Path(__file__).resolve().parents[1] / "specs"


def _shim_path() -> Path:
    """bench/py/bench — the executable shim next to the kernel package."""
    return Path(__file__).resolve().parents[1] / "bench"


def _resolve_spec(name: str) -> Path | None:
    """SPEC arg -> path: literal file first, then specs/{name}[.py]."""
    p = Path(name)
    if p.is_file():
        return p
    for cand in (_specs_dir() / name, _specs_dir() / f"{name}.py"):
        if cand.is_file():
            return cand
    _err(f"spec not found: {name!r} (tried literal path and {_specs_dir()})")
    return None


def _collect_params(args) -> dict:
    """--param k=v repeats + positional k=v leftovers -> params dict."""
    out: dict[str, str] = {}
    for kv in [*(args.param or []), *(args.params or [])]:
        if "=" not in kv:
            msg = f"param {kv!r} is not k=v"
            raise ValueError(msg)
        k, v = kv.split("=", 1)
        if not k:
            msg = f"param {kv!r} has an empty key"
            raise ValueError(msg)
        out[k] = v
    return out


def _pause_refused(what: str, paid) -> bool:
    """PAUSE is a paid-spend fence (Phase 3 rescope): only specs carrying a
    paid stage are refused; free work and ``plan`` run straight through so
    the migration can proceed while the fence stays up. ``paid=None``
    (unprovable spec) fails closed."""
    if paid is not False and locks.pause_engaged():
        _err(
            f"{what}: refused — PAUSE engaged ({paths.pause_path()}); "
            "paid work stays fenced, free specs are unaffected"
        )
        return True
    return False


def _spec_paidness(spec_path: Path):
    """True/False when the spec module can prove it, else None."""
    smod, _serr = _lazy("spec")
    loader = getattr(smod, "load_spec", None) if smod is not None else None
    if loader is None:
        return None
    try:
        return loader(str(spec_path)).has_paid()
    except Exception:
        return None


def _try_sweep(light: bool):
    """kernel.sweep.sweep when it exists; (report|None, err|None)."""
    mod, err = _lazy("sweep")
    fn = getattr(mod, "sweep", None) if mod is not None else None
    if fn is None:
        return None, err if err is not None else AttributeError("sweep")
    try:
        return fn(light=light), None
    except Exception as exc:
        return None, exc


def _pre_write() -> None:
    """Every write command auto-runs the light reaper first (§2.4).

    A missing/failed sweep warns on stderr but never blocks the write —
    the reaper's state is recoverable bookkeeping, not a write gate.
    """
    _, err = _try_sweep(light=True)
    if err is not None:
        _err(f"note: pre-write light sweep skipped ({err})")


def _open_index() -> index_mod.Index:
    """Open the derived index and pull it current (incremental tail ingest)."""
    idx = index_mod.Index()
    try:
        idx.tail_ingest()
    except Exception as exc:
        _err(f"note: tail_ingest failed ({exc}) — index may be stale")
    return idx


def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str))


def _load_registry():
    """PapersRegistry for id resolution at import boundaries (best effort)."""
    try:
        return idnorm.PapersRegistry.load()
    except Exception as exc:
        _err(f"note: PapersRegistry.load failed ({exc}) — ids resolve statelessly")
        return None


def _run_dir_of(name: str) -> Path | None:
    """Resolve a run reference: a directory, or a kind/date/slug run name."""
    p = Path(name)
    if p.is_dir():
        return p
    parts = str(name).split("/")
    if len(parts) == 3:
        d = paths.run_dir(parts[0], parts[1], parts[2])
        if d.is_dir():
            return d
    _err(f"run not found: {name!r} (need kind/date/slug or a run dir)")
    return None


def _rundir_of(name: str):
    """RunDir for a run name/path (kind/date/slug parsed from the dir)."""
    d = _run_dir_of(name)
    if d is None:
        return None
    try:
        parts = d.resolve().relative_to(paths.runs_dir()).parts
    except ValueError:
        parts = ()
    if len(parts) >= 3:
        try:
            return runs.load_run(parts[0], parts[1], parts[2])
        except FileNotFoundError:
            pass
        return runs.RunDir(path=d, kind=parts[0], date=parts[1], slug=parts[2])
    return runs.RunDir(path=d, kind="adhoc", date="-", slug=d.name)


def _parse_size(text: str) -> int:
    """'512M' / '5G' / '1.5T' / raw bytes -> int bytes."""
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KkMmGgTt]?)", str(text).strip())
    if not m:
        msg = f"bad size {text!r} (use bytes or K/M/G/T suffix)"
        raise ValueError(msg)
    mult = {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}
    return int(float(m.group(1)) * mult[m.group(2).upper()])


# --- init ------------------------------------------------------------------------


def _cmd_init(_args) -> int:
    root = paths.ensure_layout()
    print(f"bench root: {root}")
    for name, p in (
        ("ledger", paths.ledger_dir()),
        ("runs", paths.runs_dir()),
        ("vault", paths.vault_dir()),
        ("lake", paths.lake_dir()),
        ("locks", paths.locks_dir()),
        ("backup", paths.backup_dir()),
    ):
        print(f"  {name:<7} {p}")
    print("layout OK — sentinels, immortal lock files and seqfile present")
    return EXIT_OK


# --- run / plan ------------------------------------------------------------------


def _kernel_run_path():
    """kernel.kernel run/plan functions; (run, plan, err)."""
    mod, err = _lazy("kernel")
    run_fn = getattr(mod, "run", None) if mod is not None else None
    plan_fn = getattr(mod, "plan", None) if mod is not None else None
    return run_fn, plan_fn, err


def _run_kwargs(args) -> dict:
    return {
        "date": args.date,
        "slug": args.slug,
        "resume": getattr(args, "resume", False),
        "replan": args.replan,
        "max_cost": args.max_cost,
        "regen": args.regen,
        "sel": args.sel,
        "yes": args.yes,
        "allow_regen": args.allow_regen,
    }


def _detach_run(args, spec_path: Path) -> int:
    """Re-exec `bench run` (sans --detach) under locks.detach_with_lock (R22).

    The child holds locks/detach.lock for its whole lifetime — a second
    detach while one lives fails fast. §3.6: detach forces the budget flag
    for paid specs, checked here when the spec module can prove paidness.
    """
    run_fn, _plan_fn, kerr = _kernel_run_path()
    if run_fn is None:
        _err(f"run --detach: kernel run path unavailable ({kerr})")
        return EXIT_REFUSED
    smod, _serr = _lazy("spec")
    loader = getattr(smod, "load_spec", None) if smod is not None else None
    if loader is not None:
        try:
            s = loader(str(spec_path))
        except Exception as exc:
            _err(f"run --detach: spec preflight failed: {exc}")
            return EXIT_REFUSED
        paid = any(
            getattr(st, "paid", False) for st in getattr(s, "stages", []) or ()
        )
        if paid and args.max_cost is None:
            _err(
                "run --detach: paid spec requires --max-cost "
                "(§3.6 — detach forces the budget flag)"
            )
            return EXIT_REFUSED

    argv = [sys.executable, str(_shim_path()), "run", str(spec_path)]
    for kv in [*(args.param or []), *(args.params or [])]:
        argv += ["--param", kv]
    if args.date:
        argv += ["--date", args.date]
    if args.slug:
        argv += ["--slug", args.slug]
    for flag, name in (
        (args.resume, "--resume"),
        (args.replan, "--replan"),
        (args.regen, "--regen"),
        (args.yes, "--yes"),
        (args.allow_regen, "--allow-regen"),
    ):
        if flag:
            argv.append(name)
    if args.max_cost is not None:
        argv += ["--max-cost", str(args.max_cost)]
    if args.sel:
        argv += ["--sel", args.sel]
    if args.jobs is not None:
        argv += ["--jobs", str(args.jobs)]

    lock = paths.locks_dir() / "detach.lock"
    log = paths.root() / "detach.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        proc = locks.detach_with_lock(
            argv,
            lock,
            ack_timeout=30.0,
            stdout=fd,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    finally:
        os.close(fd)
    print(f"detached: pid={proc.pid} lock={lock} log={log}")
    return EXIT_OK


def _cmd_run(args) -> int:
    spec_path = _resolve_spec(args.spec)
    if spec_path is None:
        return EXIT_REFUSED
    if _pause_refused("run", _spec_paidness(spec_path)):
        return EXIT_REFUSED
    if args.detach:
        return _detach_run(args, spec_path)
    run_fn, _p, kerr = _kernel_run_path()
    if run_fn is None:
        _err(f"run: kernel run path unavailable ({kerr})")
        return EXIT_REFUSED
    try:
        params = _collect_params(args)
    except ValueError as exc:
        _err(str(exc))
        return EXIT_REFUSED
    _pre_write()
    try:
        res = run_fn(
            str(spec_path),
            params,
            jobs=args.jobs,
            emit=print,
            **_run_kwargs(args),
        )
    except Exception as exc:
        _err(f"run failed: {exc}")
        return EXIT_FAIL
    _print_json(res)
    ok = res.get("ok", True) if isinstance(res, dict) else True
    return EXIT_OK if ok else EXIT_FAIL


def _cmd_plan(args) -> int:
    # plan is a dry-run: allowed under PAUSE (it produces the dedup
    # coverage report the first-fire gate consumes)
    spec_path = _resolve_spec(args.spec)
    if spec_path is None:
        return EXIT_REFUSED
    _r, plan_fn, kerr = _kernel_run_path()
    if plan_fn is None:
        _err(f"plan: kernel run path unavailable ({kerr})")
        return EXIT_REFUSED
    try:
        params = _collect_params(args)
    except ValueError as exc:
        _err(str(exc))
        return EXIT_REFUSED
    try:
        res = plan_fn(
            str(spec_path),
            params,
            date=args.date,
            slug=args.slug,
            replan=args.replan,
            max_cost=args.max_cost,
            regen=args.regen,
            sel=args.sel,
            yes=args.yes,
            allow_regen=args.allow_regen,
            emit=print,
        )
    except Exception as exc:
        _err(f"plan failed: {exc}")
        return EXIT_FAIL
    _print_quote(res)
    return EXIT_OK


def _print_quote(res) -> None:
    """The §3.6 five-bucket quote + regen decision list.

    Accepts either a bare dedup.quote() dict or a wrapper carrying one
    under 'quote' — both spellings stay printable.
    """
    if not isinstance(res, dict):
        print(res)
        return
    q = res.get("quote") if isinstance(res.get("quote"), dict) else res
    print("plan quote (§3.6 five buckets):")
    for b in ("new", "reuse", "missing", "claimed", "attempted", "unsealed"):
        if b in q:
            v = q[b]
            print(f"  {b:<10} {v if isinstance(v, int) else len(v)}")
    if "total" in q:
        print(f"  {'total':<10} {q['total']}")
    if "sealed" in q:
        print(f"  sealed     {q['sealed']}")
    regen = res.get("regen_decisions") or q.get("regen_decisions") or []
    if regen:
        print("regen decision list (missing bytes — never auto-entered):")
        for r in regen:
            print(f"    {r}")
    cells = res.get("cells") or res.get("would_run") or []
    if cells:
        print(f"would run: {len(cells)} cell(s)")


# --- status ------------------------------------------------------------------------


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
                    "  tally: "
                    + " ".join(f"{k}={v}" for k, v in sorted(tally.items()))
                )
            return EXIT_OK

        active = {a["run"] for a in runs.active_runs()}
        rows = idx.conn.execute(
            "SELECT run,run_seq,kind,date,slug,ts_start FROM runs"
            " ORDER BY run_seq"
        ).fetchall()
        print(f"bench root: {paths.root()}")
        print(f"runs: {len(rows)}  active: {len(active)}")
        for r in rows:
            mark = " *active*" if r["run"] in active else ""
            n = idx.conn.execute(
                "SELECT COUNT(*) FROM cells WHERE last_run=?", (r["run"],)
            ).fetchone()[0]
            print(
                f"  seq={r['run_seq']:<4} {r['run']}  cells={n}{mark}"
            )
        if not rows:
            print("  (no runs yet)")
        return EXIT_OK
    finally:
        idx.close()


# --- vault --------------------------------------------------------------------------


def _cmd_vault_verify(args) -> int:
    rep = vault.verify(level=args.level)
    print(
        f"vault verify[{rep['level']}]: metas={rep['metas']}"
        f" checked={rep['checked']} inodes={rep['inodes']}"
        f" bad={len(rep['bad'])} meta_bad={len(rep['meta_bad'])}"
        f" meta_missing={len(rep['meta_missing'])}"
        f" extra={len(rep['extra'])}"
    )
    for b in rep["bad"][:20]:
        print(f"  bad: {b.get('reason')} {b.get('paths')}")
    for m in rep["meta_bad"][:20]:
        print(f"  meta_bad: {m}")
    for m in rep["meta_missing"][:20]:
        print(f"  meta_missing (orphan dir): {m}")
    bad = rep["bad"] or rep["meta_bad"]
    if not bad:
        # first-fire gate evidence (§6 Phase-3 首火闸): only a CLEAN pass
        # refreshes freshness — a verify that found rot must not stamp.
        stamp = {
            "ts": round(time.time(), 3), "level": rep["level"],
            "metas": rep["metas"], "checked": rep["checked"],
            "meta_missing": len(rep["meta_missing"]),
        }
        fsutil.atomic_write(
            paths.vault_verify_stamp_path(),
            (json.dumps(stamp, sort_keys=True) + "\n").encode("utf-8"),
        )
    return EXIT_FAIL if bad else EXIT_OK


def _cmd_vault_restore(args) -> int:
    _pre_write()
    try:
        n = vault.restore(
            args.idc,
            args.arm,
            args.variant,
            args.dest,
            altseq=args.altseq,
            mode=args.mode,
        )
    except Exception as exc:
        _err(f"vault restore failed: {exc}")
        return EXIT_FAIL
    print(f"restored {n} file(s) -> {args.dest} (mode={args.mode})")
    return EXIT_OK


def _cmd_vault_adopt(args) -> int:
    _pre_write()
    try:
        leaf = vault.adopt(
            args.dir,
            args.idc,
            arm=args.arm,
            variant=args.variant,
            reason=args.reason,
            kind=args.kind,
        )
    except Exception as exc:
        _err(f"vault adopt failed: {exc}")
        return EXIT_FAIL
    print(f"adopted -> {leaf}")
    return EXIT_OK


def _cmd_vault_tombstone(args) -> int:
    _pre_write()
    try:
        vault.tombstone(
            args.idc,
            args.arm,
            args.variant,
            args.kind,
            args.reason,
            lost_run=args.lost_run or "",
        )
    except Exception as exc:
        _err(f"vault tombstone failed: {exc}")
        return EXIT_FAIL
    print(
        f"tombstoned ({args.idc},{args.arm},{args.variant},{args.kind})"
        f" reason={args.reason}"
    )
    return EXIT_OK


def _cmd_vault_seed(args) -> int:
    """Phase-2 live-byte census — zh-store bytes -> vault (§3.10.9)."""
    _pre_write()
    if not Path(args.manifest).is_file():
        _err(f"manifest not found: {args.manifest}")
        return EXIT_REFUSED
    if not Path(args.bytes_root).is_dir():
        _err(f"bytes root not found: {args.bytes_root}")
        return EXIT_REFUSED
    idx = _open_index()
    try:
        res = importer.seed_vault_zhstore(
            args.manifest,
            args.bytes_root,
            idx,
            registry=_load_registry(),
            dry=args.dry,
        )
    except Exception as exc:
        _err(f"vault seed failed: {exc}")
        return EXIT_FAIL
    finally:
        idx.close()
    _print_json(res)
    return EXIT_OK


# --- ledger -------------------------------------------------------------------------


def _cmd_ledger_import(args) -> int:
    _pre_write()
    p = Path(args.path)
    if not p.exists():
        _err(f"import source not found: {p}")
        return EXIT_REFUSED
    idx = _open_index()
    try:
        reg = _load_registry()
        if args.manifest or args.bytes_root:
            if not (args.manifest and args.bytes_root):
                _err("zhstore import needs --manifest AND --bytes-root")
                return EXIT_REFUSED
            res = importer.import_zhstore(
                args.manifest, args.bytes_root, idx, registry=reg, dry=args.dry
            )
        elif p.is_dir():
            res = importer.import_all(
                {"scan_root": p}, idx, registry=reg, dry=args.dry
            )
        elif p.suffix in (".db", ".sqlite", ".sqlite3"):
            res = importer.import_benchdb(p, idx, registry=reg, dry=args.dry)
        else:
            res = importer.import_jsonl_file(
                p, run=args.run, index=idx, registry=reg, dry=args.dry
            )
    except Exception as exc:
        _err(f"ledger import failed: {exc}")
        return EXIT_FAIL
    finally:
        idx.close()
    _print_json(res)
    return EXIT_OK


def _cmd_ledger_ingest(args) -> int:
    """External-writer lane (§5): run='external', ledger-assigned seqs."""
    _pre_write()
    p = Path(args.external)
    if not p.is_file():
        _err(f"ingest source not found: {p}")
        return EXIT_REFUSED
    idx = _open_index()
    try:
        res = importer.import_jsonl_file(
            p,
            run=args.run or "external",
            index=idx,
            registry=_load_registry(),
            dry=args.dry,
        )
    except Exception as exc:
        _err(f"ledger ingest failed: {exc}")
        return EXIT_FAIL
    finally:
        idx.close()
    _print_json(res)
    return EXIT_OK


def _cmd_ledger_rebuild(_args) -> int:
    _pre_write()
    try:
        idx = index_mod.rebuild_index()
    except Exception as exc:
        _err(f"rebuild-index failed: {exc}")
        return EXIT_FAIL
    try:
        gen, wm = idx.sealed_state()
        print(f"rebuild-index: sealed_gen={gen} watermark={wm}")
    finally:
        idx.close()
    return EXIT_OK


def _cmd_ledger_tail(_args) -> int:
    _pre_write()
    idx = index_mod.Index()
    try:
        n = idx.tail_ingest()
        gen, wm = idx.sealed_state()
    finally:
        idx.close()
    print(f"tail-ingest: applied={n} sealed_gen={gen} watermark={wm}")
    return EXIT_OK


# --- lake ---------------------------------------------------------------------------


def _cmd_lake_status(_args) -> int:
    cat = lake.LakeCatalog.load()
    rows = cat.rows()
    tally: dict[str, int] = {}
    pinned_rows: list[dict] = []
    for r in rows.values():
        st = str(r.get("state", "?"))
        tally[st] = tally.get(st, 0) + 1
        if lake._pinned(r):
            pinned_rows.append(r)
    corpus = paths.lake_corpus_dir()
    nbytes = fsutil.dir_size(corpus) if corpus.exists() else 0
    pin_bytes = 0
    for r in pinned_rows:
        d = lake.cell_dir(r["idc"], r.get("source") or "arxiv")
        if d.is_dir():
            pin_bytes += fsutil.dir_size(d)
    cap_gb = os.environ.get("TEXLATE_LAKE_CAP_GB", "100")
    print(f"lake: {paths.lake_dir()}")
    print(f"  cells={len(rows)} corpus_bytes={nbytes} cap_gb={cap_gb}")
    for st, n in sorted(tally.items()):
        print(f"  {st:<12} {n}")
    print(f"  pinned={len(pinned_rows)} pinned_bytes={pin_bytes}")
    try:
        ostat = cas.stat()
    except Exception:
        ostat = None
    if ostat:
        print(
            f"  objects: blobs={ostat.get('blob', {}).get('n', 0)}"
            f" files={ostat.get('file', {}).get('n', 0)}"
        )
    return EXIT_OK


def _cmd_lake_pin(args, *, unpin: bool = False) -> int:
    """``bench lake pin|unpin <id>...`` — cell-side PINNED marker + catalog
    ``pinned`` field; canon 归一 same as the register arm."""
    _pre_write()
    verb = "unpin" if unpin else "pin"
    cat = lake.LakeCatalog.load()
    bad = 0
    for raw in args.ids:
        res = idnorm.canon_id(raw)
        if not res.ok:
            _err(f"{verb}: {raw!r} is not canon ({res.state} {res.reason})")
            bad += 1
            continue
        if unpin:
            row = cat.unpin(res.idc, source=args.source)
            if row is None:
                print(f"{res.idc}: not pinned (absent)")
            else:
                print(f"unpinned {res.idc}")
        else:
            cat.pin(res.idc, source=args.source)
            print(f"pinned {res.idc} -> "
                  f"{lake.cell_dir(res.idc, args.source)}")
    return EXIT_FAIL if bad else EXIT_OK


def _cmd_lake_unpin(args) -> int:
    return _cmd_lake_pin(args, unpin=True)


def _cmd_lake_evict(args) -> int:
    _pre_write()
    try:
        target = _parse_size(args.to_free)
    except ValueError as exc:
        _err(str(exc))
        return EXIT_REFUSED
    removed = lake.evict(target)
    print(f"evicted {len(removed)} path(s) toward {target} freed bytes:")
    for p in removed:
        print(f"  {p}")
    return EXIT_OK


def _cmd_lake_register(args) -> int:
    _pre_write()
    if args.manifests:
        idx = _open_index()
        try:
            res = importer.register_lake_manifests(
                args.manifests, idx, registry=_load_registry(),
                dry=args.dry)
        except Exception as exc:
            _err(f"lake register failed: {exc}")
            return EXIT_FAIL
        finally:
            idx.close()
        _print_json(res)
        return EXIT_OK
    if not args.ids:
        _err("register: give ids or --manifests")
        return EXIT_REFUSED
    bad = 0
    for raw in args.ids:
        res = idnorm.canon_id(raw)
        if not res.ok:
            _err(f"register: {raw!r} is not canon ({res.state} {res.reason})")
            bad += 1
            continue
        d = lake.register_skeleton(res.idc)
        print(f"registered {res.idc} -> {d}")
    return EXIT_FAIL if bad else EXIT_OK


def _cmd_lake_absorb(args) -> int:
    _pre_write()
    if not Path(args.root).is_dir():
        _err(f"absorb root not found: {args.root}")
        return EXIT_REFUSED
    idx = _open_index()
    try:
        res = importer.absorb_corpus(
            args.root, idx, registry=_load_registry(),
            manifests=args.manifests, dry=args.dry,
            source=args.source)
    except Exception as exc:
        _err(f"lake absorb failed: {exc}")
        return EXIT_FAIL
    finally:
        idx.close()
    _print_json(res)
    return EXIT_OK


# --- cache (§3.9) ------------------------------------------------------------------


def _cmd_cache_status(_args) -> int:
    _print_json(cachemod.status())
    return EXIT_OK


def _cmd_cache_evict(args) -> int:
    _pre_write()
    if args.to_free is None:
        removed = cachemod.cap_evict()
    else:
        try:
            target = _parse_size(args.to_free)
        except ValueError as exc:
            _err(str(exc))
            return EXIT_REFUSED
        removed = cachemod.evict(target)
    print(f"evicted {len(removed)} bucket(s):")
    for p in removed:
        print(f"  {p}")
    return EXIT_OK


def _cmd_cache_rebuild(args) -> int:
    _pre_write()
    glossary = None
    if args.glossary_json is not None:
        try:
            glossary = json.loads(args.glossary_json)
        except ValueError as exc:
            _err(f"--glossary-json: {exc}")
            return EXIT_REFUSED
    res = cachemod.rebuild_from_vault(
        prompt_version=args.prompt_version, base_url=args.base_url,
        model=args.model, lang=args.lang, glossary=glossary,
        context=args.context, dry=args.dry, progress=print)
    _print_json(res)
    return EXIT_OK


# --- derive / prune / sweep / backup --------------------------------------------------


def _cmd_derive(args) -> int:
    """Re-run the report/projection for a run — no cell re-execution (§2.1)."""
    _pre_write()
    rd = _rundir_of(args.run)
    if rd is None:
        return EXIT_REFUSED
    rep = runs.accounting_check(rd)
    print(
        f"accounting: plan={rep['plan']} queued={rep['queued']}"
        f" terminal={rep['terminal']} ok={rep['ok']}"
    )
    for k in ("missing_terminal", "extra_queued", "dup_terminal",
              "extra_terminal"):
        if rep[k]:
            print(f"  {k}: {rep[k]}")
    out = args.out or (rd.derived() / "projected")
    idx = _open_index()
    try:
        res = report.build_run_report(idx, rd.path, out, accounting=rep)
    finally:
        idx.close()
    print(
        f"derived: out={out} rows={res.get('rows')}"
        f" files={len(res.get('files', []))}"
    )
    return EXIT_OK if rep["ok"] else EXIT_FAIL


def _cmd_sweep(args) -> int:
    rep, err = _try_sweep(light=args.light)
    if rep is None:
        _err(f"sweep: unavailable or failed ({err})")
        return EXIT_REFUSED
    _print_json(rep)
    return EXIT_OK


_PRUNE_KEEP = {
    "report": ("report.md",),
    "events": ("events.jsonl",),
    "spec": ("spec.json",),
    "env": ("spec_env.json",),
    "plan": ("plan.json",),
    "cases": ("cases.jsonl",),
    "invocations": ("invocations.jsonl",),
    "work": ("work",),
    "derived": ("derived",),
}
# Never deleted regardless of keep-list: the immortal lock file (R21) and the
# heartbeat (structural — a stale mtime IS the zombie evidence).
_PRUNE_ALWAYS = {".lock", "heartbeat"}

_PAID_TREE_PREFIXES = ("zh", "splice", "state", "xlat-state")


def _cell_has_paid_bytes(cell: Path) -> bool:
    """Conservative paid-shape probe: zh/splice/state/xlat-state trees that
    carry any file mean paid bytes may live here (fail-closed)."""
    try:
        for e in cell.iterdir():
            if not e.is_dir():
                continue
            base = e.name.split(".", 1)[0].split("@", 1)[0]
            if base not in _PAID_TREE_PREFIXES:
                continue
            if any(p.is_file() for p in e.rglob("*")):
                return True
    except OSError:
        return True  # unreadable tree — treat as paid, refuse to guess
    return False


def _cmd_prune(args) -> int:
    """Reduce a run dir to its keep-list (§2.1 prune).

    work/ cells go through runs.remove_cell_tree — the single delete verb,
    which refuses a paid-shaped tree that no vault copy vouches for.
    """
    _pre_write()
    rd = _rundir_of(args.run)
    if rd is None:
        return EXIT_REFUSED
    keep = {t.strip() for t in str(args.keep).split(",") if t.strip()}
    unknown = keep - set(_PRUNE_KEEP)
    if unknown:
        _err(
            f"prune: unknown keep tokens {sorted(unknown)}"
            f" (allowed: {sorted(_PRUNE_KEEP)})"
        )
        return EXIT_REFUSED
    keep_names = set(_PRUNE_ALWAYS)
    for t in keep:
        keep_names.update(_PRUNE_KEEP[t])

    blocked = 0
    try:
        lock_ctx = rd.lock(blocking=False)
        lock_ctx.__enter__()
    except locks.WouldBlock:
        _err(
            f"prune: {rd.run} is live (run.lock held) — refusing to "
            "delete a running archive (R21)"
        )
        return EXIT_REFUSED
    try:
        for entry in sorted(rd.path.iterdir()):
            if entry.name in keep_names:
                print(f"  keep    {entry.name}")
                continue
            if entry.name == "work":
                for cell in sorted(entry.iterdir()):
                    if not cell.is_dir() or cell.name.startswith((".", "_")):
                        continue
                    sid = cell.name
                    idc = idnorm.idc_from_safe(sid)

                    def vault_check(sid=sid, idc=idc, cell=cell):
                        if not _cell_has_paid_bytes(cell):
                            return True
                        try:
                            return any(
                                r.get("bytes_ok") for r in vault.query(idc)
                            )
                        except Exception:
                            return False

                    try:
                        runs.remove_cell_tree(rd, sid, vault_check=vault_check)
                        print(f"  pruned  work/{sid}")
                    except runs.BlockedDelete as exc:
                        blocked += 1
                        _err(f"  blocked work/{sid}: {exc}")
                if not blocked:
                    # cells gone or none — drop the remaining tree (_texmf
                    # shared cache et al.; all rebuildable)
                    shutil.rmtree(entry)
                continue
            if entry.name == "events.jsonl":
                _err(
                    "  warning: removing the run events shard — the ledger "
                    "keeps the sole remaining copy (dual-write redundancy "
                    "ends)"
                )
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
            print(f"  pruned  {entry.name}")
    finally:
        lock_ctx.__exit__(None, None, None)
    if blocked:
        _err(f"prune: {blocked} cell tree(s) blocked (unharvested paid bytes)")
        return EXIT_FAIL
    return EXIT_OK


def _cmd_backup(_args) -> int:
    """Minimal backup unit (§3.10.1): ledger + vault meta/manifest + lake
    durable + run keep-tier files, as a plain tar under backup/.

    Scope note: vault PAYLOAD bytes (zh/splice/state trees), work trees,
    derived/, and the rebuildable index.sqlite are deliberately excluded —
    the paid bytes' second copy is restic/rsync territory, not this tar.
    """
    _pre_write()
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out = paths.backup_dir() / f"bench-backup-{ts}.tar"
    root = paths.root()
    members: list[Path] = []

    def add_tree(base: Path, *, skip=()) -> None:
        if not base.is_dir():
            return
        for p in sorted(base.rglob("*")):
            if any(p.match(s) for s in skip):
                continue
            members.append(p)

    # ledger — everything except the disposable index projection.
    add_tree(
        paths.ledger_dir(),
        skip=("index.sqlite", "index.sqlite-*", "*.lock"),
    )
    # vault meta + manifest — the credential layer, not the payload.
    add_tree(paths.vault_meta_dir())
    if paths.vault_manifest_path().is_file():
        members.append(paths.vault_manifest_path())
    # lake durable + the catalog projection (rebuildable, small).
    add_tree(paths.lake_durable_dir())
    if paths.lake_catalog_path().is_file():
        members.append(paths.lake_catalog_path())
    # run keep-tier files only — never work/ or derived/.
    keep_files = {
        "spec.json", "spec_env.json", "plan.json", "events.jsonl",
        "cases.jsonl", "invocations.jsonl", "report.md",
    }
    rbase = paths.runs_dir()
    if rbase.is_dir():
        members.extend(
            p for p in sorted(rbase.rglob("*"))
            if p.is_file() and p.name in keep_files
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(out, "w") as tf:
        for p in members:
            try:
                tf.add(p, arcname=p.relative_to(root), recursive=False)
                n += 1
            except (OSError, ValueError) as exc:
                _err(f"backup: skipped {p} ({exc})")
    print(
        f"backup: {out} ({out.stat().st_size} bytes, {n} member(s))\n"
        "scope: ledger + vault meta/manifest + lake durable/catalog +"
        " run keep-tier; vault payload bytes and work trees excluded"
    )
    return EXIT_OK


# --- doctor / fsck --------------------------------------------------------------------


def _print_checks(checks) -> bool:
    ok = True
    for c in checks:
        good = bool(c.get("ok"))
        ok = ok and good
        mark = "ok" if good else "FAIL"
        detail = c.get("detail", "")
        print(f"  [{mark}] {c.get('name')}" + (f" — {detail}" if detail else ""))
    return ok


def _mini_doctor(fix: bool, switch_ok: bool) -> list[dict]:
    """Fallback doctor while kernel.doctor is unwritten: layout, sentinels,
    immortal locks, seqfile sanity, ledger parse, index-dirty flag."""
    checks: list[dict] = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": ok, "detail": detail})

    if fix:
        try:
            paths.ensure_layout()
        except Exception as exc:
            add("layout", False, f"ensure_layout failed: {exc}")
    root = paths.root()
    add("root", root.is_dir(), str(root))
    add(
        "sentinels",
        paths.ledger_sentinel_path().exists()
        and paths.vault_sentinel_path().exists(),
        "ledger + vault mount proofs present",
    )
    add(
        "lock-files",
        paths.ledger_lock_path().exists() and paths.vault_lock_path().exists(),
        "immortal lock files present (never unlinked)",
    )
    try:
        seq = int(paths.seqfile_path().read_text().strip() or "0")
        add("seqfile", True, f"high-water={seq}")
    except Exception as exc:
        add("seqfile", False, f"unparseable: {exc}")
    bad = 0
    ep = paths.events_path()
    if ep.exists():
        for _ln, ev, _raw in events.iter_jsonl(ep):
            if ev is None:
                bad += 1
    add("ledger-parse", bad == 0, f"bad_lines={bad}")
    add(
        "index-dirty",
        not paths.index_dirty_path().exists(),
        ".index-dirty absent" if not paths.index_dirty_path().exists()
        else ".index-dirty PRESENT — rebuild required before paid work",
    )
    try:
        paths.assert_vault_same_volume()
        add("vault-volume", True, "vault/.staging same device")
    except Exception as exc:
        add("vault-volume", False, str(exc))
    if switch_ok:
        idle = locks.kernel_idle() and not runs.active_runs()
        add("switch-ok", idle, "kernel idle + no active runs" if idle
            else "kernel busy or active runs — drain first")
    return checks


def _cmd_doctor(args) -> int:
    mod, err = _lazy("doctor")
    fn = getattr(mod, "doctor", None) if mod is not None else None
    if fn is None:
        _err(f"note: kernel.doctor unavailable ({err}) — minimal checks only")
        checks = _mini_doctor(fix=args.fix, switch_ok=args.switch_ok)
        ok = _print_checks(checks)
        if args.switch_ok:
            print("SWITCH-OK" if ok else "SWITCH-BLOCKED")
        return EXIT_OK if ok else EXIT_FAIL
    try:
        rep = fn(fix=args.fix, switch_ok=args.switch_ok)
    except Exception as exc:
        _err(f"doctor failed: {exc}")
        return EXIT_FAIL
    checks = rep.get("checks", []) if isinstance(rep, dict) else []
    ok = _print_checks(checks) if checks else bool(rep.get("ok"))
    if args.switch_ok:
        print("SWITCH-OK" if ok else "SWITCH-BLOCKED")
    return EXIT_OK if ok else EXIT_FAIL


def _cmd_fsck(args) -> int:
    mod, err = _lazy("doctor")
    fn = getattr(mod, "fsck", None) if mod is not None else None
    if fn is None:
        _err(f"note: kernel.doctor.fsck unavailable ({err}) — vault stat scan")
        try:
            rep = vault.verify("stat")
        except Exception as exc:
            _err(f"fsck fallback failed: {exc}")
            return EXIT_FAIL
        print(
            f"fsck(vault stat): metas={rep['metas']} bad={len(rep['bad'])}"
            f" meta_bad={len(rep['meta_bad'])}"
            f" meta_missing={len(rep['meta_missing'])}"
            f" extra={len(rep['extra'])}"
        )
        ok = not rep["bad"] and not rep["meta_bad"]
        return EXIT_OK if ok else EXIT_FAIL
    try:
        rep = fn(defer_edges=args.defer_edges)
    except Exception as exc:
        _err(f"fsck failed: {exc}")
        return EXIT_FAIL
    checks = rep.get("checks", []) if isinstance(rep, dict) else []
    ok = _print_checks(checks) if checks else bool(rep.get("ok", True))
    return EXIT_OK if ok else EXIT_FAIL


# --- spec -----------------------------------------------------------------------------


def _spec_doc(path: Path) -> str:
    """First docstring line via ast — never executes the spec file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return ""
    doc = ast.get_docstring(tree) or ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def _spec_kind(path: Path):
    """kind via kernel.spec.load_spec when available, else a source regex."""
    mod, _load_err = _lazy("spec")
    loader = getattr(mod, "load_spec", None) if mod is not None else None
    kind = None
    if loader is not None:
        try:
            kind = getattr(loader(str(path)), "kind", None)
        except Exception:
            kind = None
    if kind:
        return str(kind)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "?"
    m = re.search(r"kind\s*=\s*['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else "?"


def _cmd_spec_list(_args) -> int:
    sdir = _specs_dir()
    rows = []
    if sdir.is_dir():
        for f in sorted(sdir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            rows.append((f.name, _spec_kind(f), _spec_doc(f)))
    print(f"specs: {sdir}")
    if not rows:
        print("  (none)")
        return EXIT_OK
    for name, kind, doc in rows:
        print(f"  {name:<24} kind={kind:<16} {doc}")
    return EXIT_OK


# --- analysis verbs -------------------------------------------------------------------


def _lazy_verb(name: str):
    """Import the module REGISTRY maps ``name`` to; (module, None) or
    (None, err). Hyphenated verb names share a module leaf."""
    leaf = _verb_registry().get(name, (name,))[0]
    try:
        return importlib.import_module(f"verbs.{leaf}"), None
    except Exception as exc:
        return None, exc


def _verb_registry() -> dict:
    """verbs.REGISTRY — pure-data import, safe at parser-build time."""
    try:
        return dict(importlib.import_module("verbs").REGISTRY)
    except Exception:
        return {}


def _cmd_verb(args) -> int:
    """Generic verb dispatch: lazy-load verbs.<cmd> and call main(args)."""
    mod, err = _lazy_verb(args.cmd)
    if mod is None or not hasattr(mod, "main"):
        _err(f"{args.cmd}: verb not installed ({err or 'no main'})")
        return EXIT_REFUSED
    return int(mod.main(args) or 0)


def _cmd_not_implemented(args) -> int:
    _err(f"{args.cmd}: {_NOT_IMPLEMENTED}")
    return EXIT_REFUSED


# --- parser ---------------------------------------------------------------------------


def _add_runlike_flags(sp, *, with_exec: bool) -> None:
    sp.add_argument("--date", help="run date YYYY-MM-DD (default: UTC today)")
    sp.add_argument("--slug", help="run slug (default: kind, uniquified)")
    sp.add_argument(
        "--param", action="append", default=[],
        help="spec param k=v (repeatable)",
    )
    sp.add_argument("--replan", action="store_true",
                    help="re-enumerate the frozen plan")
    sp.add_argument("--max-cost", type=float, default=None,
                    help="run-level budget fuse in USD (paid runs: required)")
    sp.add_argument("--regen", action="store_true",
                    help="request paid-byte regeneration — folds into"
                         " --allow-regen (needs --sel + --max-cost + --yes)")
    sp.add_argument("--sel", help="cell selector expression")
    sp.add_argument("--yes", action="store_true",
                    help="confirm destructive/paid actions")
    sp.add_argument("--allow-regen", action="store_true",
                    help="the only door past the regen gate (§3.6)")
    if with_exec:
        sp.add_argument("--resume", action="store_true",
                        help="reuse the run dir; done-set continues")
        sp.add_argument("--jobs", type=int, default=4,
                        help="cell executor parallelism (default 4)")
        sp.add_argument("--detach", action="store_true",
                        help="re-exec detached under locks/detach.lock (R22)")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bench",
        description="texlate bench — trizone-ledger kernel CLI (§2.1)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the $TEXLATE_BENCH_ROOT zone layout")

    sp = sub.add_parser("run", help="run a spec through the kernel")
    sp.add_argument("spec", help="spec file path or name under bench/py/specs/")
    sp.add_argument("params", nargs="*", help="extra spec params as k=v")
    _add_runlike_flags(sp, with_exec=True)

    sp = sub.add_parser("plan", help="dry-run quote: 5 dedup buckets + regen list")
    sp.add_argument("spec", help="spec file path or name under bench/py/specs/")
    sp.add_argument("params", nargs="*", help="extra spec params as k=v")
    _add_runlike_flags(sp, with_exec=False)

    sp = sub.add_parser("status", help="index reads: runs / cell state / tail")
    sp.add_argument("--run", help="cells whose last_run is RUN")
    sp.add_argument("--id", help="cell state + vault copies for an id")
    sp.add_argument("--tail", type=int, default=None,
                    help="last N ledger events")

    vp = sub.add_parser("vault", help="paid-bytes zone verbs")
    vsub = vp.add_subparsers(dest="vsub", required=True)
    sp = vsub.add_parser("verify", help="three-tier vault check")
    sp.add_argument("--level", default="stat",
                    choices=["stat", "sample", "full"])
    sp = vsub.add_parser("restore", help="vault -> work materialization")
    sp.add_argument("idc")
    sp.add_argument("--arm", required=True)
    sp.add_argument("--variant", default="-")
    sp.add_argument("--altseq", default=None)
    sp.add_argument("--dest", required=True)
    sp.add_argument("--mode", default="copy", choices=["copy", "link"])
    sp = vsub.add_parser("adopt", help="orphan bytes -> quarantine")
    sp.add_argument("dir")
    sp.add_argument("--idc", required=True)
    sp.add_argument("--arm", default="-")
    sp.add_argument("--variant", default="-")
    sp.add_argument("--kind", default="zh",
                    choices=sorted(vault.KINDS))
    sp.add_argument("--reason", default="orphan")
    sp = vsub.add_parser("tombstone", help="register lost bytes")
    sp.add_argument("idc")
    sp.add_argument("--arm", required=True)
    sp.add_argument("--variant", default="-")
    sp.add_argument("--kind", required=True,
                    choices=sorted(vault.KINDS))
    sp.add_argument("--reason", required=True)
    sp.add_argument("--lost-run", default="")
    sp = vsub.add_parser("seed", help="Phase-2 zh-store byte census -> vault")
    sp.add_argument("--manifest", required=True, help="zh-store manifest.jsonl")
    sp.add_argument("--bytes-root", required=True, help="zh-store payload root")
    sp.add_argument("--dry", action="store_true")

    lp = sub.add_parser("ledger", help="event ledger verbs")
    lsub = lp.add_subparsers(dest="lsub", required=True)
    sp = lsub.add_parser("import", help="import bench.db / jsonl / scan dir")
    sp.add_argument("path")
    sp.add_argument("--run", default=None, help="run name for jsonl files")
    sp.add_argument("--dry", action="store_true")
    sp.add_argument("--manifest", default=None,
                    help="zh-store manifest path (with --bytes-root)")
    sp.add_argument("--bytes-root", default=None,
                    help="zh-store payload root (with --manifest)")
    sp = lsub.add_parser("ingest", help="external writer lane (run='external')")
    sp.add_argument("--external", required=True,
                    help="jsonl file written by an external tool")
    sp.add_argument("--run", default=None,
                    help="run name (default 'external')")
    sp.add_argument("--dry", action="store_true")
    lsub.add_parser("rebuild-index", help="wipe + replay the derived index")
    lsub.add_parser("tail-ingest", help="incremental index catch-up")

    kp = sub.add_parser("lake", help="lazy corpus lake verbs")
    ksub = kp.add_subparsers(dest="ksub", required=True)
    ksub.add_parser("status", help="catalog + capacity summary")
    sp = ksub.add_parser("evict", help="LRU evict toward freed bytes")
    sp.add_argument("--to-free", required=True,
                    help="bytes to free (K/M/G/T suffix ok)")
    sp = ksub.add_parser("register", help="manifest cells (skeleton rows)")
    sp.add_argument("ids", nargs="*")
    sp.add_argument("--manifests", nargs="+", default=None,
                    help="manifest*.jsonl files or dirs to bulk-seed from")
    sp.add_argument("--dry", action="store_true")
    sp = ksub.add_parser(
        "pin", help="pin cells against eviction (PINNED marker + "
                    "catalog pinned field)")
    sp.add_argument("ids", nargs="+")
    sp.add_argument("--source", default="arxiv",
                    help="lake source namespace (default arxiv)")
    sp = ksub.add_parser("unpin", help="lift a cell's pin")
    sp.add_argument("ids", nargs="+")
    sp.add_argument("--source", default="arxiv")
    sp = ksub.add_parser("absorb",
                       help="CAS-ify an on-disk corpus tree into the lake")
    sp.add_argument("--root", required=True,
                    help="legacy corpus dir (e.g. bench/corpus)")
    sp.add_argument("--manifests", nargs="*", default=None,
                    help="manifests for the manifested flag (files or dirs)")
    sp.add_argument("--source", default="arxiv")
    sp.add_argument("--dry", action="store_true")

    cp = sub.add_parser("cache", help="global segment-cache verbs (§3.9)")
    csub = cp.add_subparsers(dest="csub", required=True)
    csub.add_parser("status", help="bucket count/bytes/cap + malformed")
    sp = csub.add_parser("evict", help="LRU evict buckets (or enforce cap)")
    sp.add_argument("--to-free", default=None,
                    help="bytes to free (K/M/G/T suffix ok); omit to "
                         "enforce the TEXLATE_CACHE_CAP_GB cap")
    sp = csub.add_parser(
        "rebuild", help="vault/state -> bucket(s): replay stored "
                        "xlat-state results through segment_key")
    sp.add_argument("--prompt-version", required=True)
    sp.add_argument("--base-url", required=True)
    sp.add_argument("--model", required=True)
    sp.add_argument("--lang", default="zh")
    sp.add_argument("--glossary-json", default=None,
                    help="JSON literal for the glossary key dim")
    sp.add_argument("--context", default="")
    sp.add_argument("--dry", action="store_true")

    sp = sub.add_parser("derive", help="re-run report/projection for a run")
    sp.add_argument("--run", required=True)
    sp.add_argument("--out", default=None,
                    help="output dir (default: run derived/projected)")

    sp = sub.add_parser("sweep", help="the reaper (§2.4)")
    sp.add_argument("--light", action="store_true",
                    help="fast version (the write-command pre-pass)")

    sp = sub.add_parser("prune", help="reduce a run dir to a keep-list")
    sp.add_argument("--run", required=True)
    sp.add_argument("--keep", required=True,
                    help="comma list: report,events,spec,env,plan,cases,"
                         "invocations,work,derived")

    sub.add_parser("backup", help="minimal backup tar under backup/")

    sp = sub.add_parser("doctor", help="kernel health checks")
    sp.add_argument("--fix", action="store_true",
                    help="repair what is safely repairable")
    sp.add_argument("--switch-ok", action="store_true",
                    help="drain gate: kernel idle + no in-flight writers")

    sp = sub.add_parser("fsck", help="deeper consistency check")
    sp.add_argument("--defer-edges", action="store_true",
                    help="skip dangling from_run edge checks")

    spp = sub.add_parser("spec", help="spec authoring helpers")
    ssub = spp.add_subparsers(dest="ssub", required=True)
    ssub.add_parser("list", help="list bench/py/specs/*.py")

    for vname, (_vleaf, vhelp) in _verb_registry().items():
        vsp = sub.add_parser(vname, help=vhelp)
        vmod, _verr = _lazy_verb(vname)
        if vmod is not None and hasattr(vmod, "add_args"):
            vmod.add_args(vsp)

    return p


_DISPATCH = {
    "init": _cmd_init,
    "run": _cmd_run,
    "plan": _cmd_plan,
    "status": _cmd_status,
    "derive": _cmd_derive,
    "sweep": _cmd_sweep,
    "prune": _cmd_prune,
    "backup": _cmd_backup,
    "doctor": _cmd_doctor,
    "fsck": _cmd_fsck,
    "triage": _cmd_verb,
    "rundiff": _cmd_verb,
    "gate": _cmd_verb,
    "dossier": _cmd_verb,
    "xlat-report": _cmd_verb,
    "xlat-rejudge": _cmd_verb,
    "qual-report": _cmd_verb,
}


def main(argv=None) -> int:
    """Entry point. Returns a process exit code (never raises SystemExit
    itself except through argparse usage errors)."""
    args = _build_parser().parse_args(argv)
    cmd = args.cmd

    # nested subcommand routing
    if cmd == "vault":
        return {
            "verify": _cmd_vault_verify,
            "restore": _cmd_vault_restore,
            "adopt": _cmd_vault_adopt,
            "tombstone": _cmd_vault_tombstone,
            "seed": _cmd_vault_seed,
        }[args.vsub](args)
    if cmd == "ledger":
        return {
            "import": _cmd_ledger_import,
            "ingest": _cmd_ledger_ingest,
            "rebuild-index": _cmd_ledger_rebuild,
            "tail-ingest": _cmd_ledger_tail,
        }[args.lsub](args)
    if cmd == "lake":
        return {
            "status": _cmd_lake_status,
            "evict": _cmd_lake_evict,
            "register": _cmd_lake_register,
            "absorb": _cmd_lake_absorb,
            "pin": _cmd_lake_pin,
            "unpin": _cmd_lake_unpin,
        }[args.ksub](args)
    if cmd == "cache":
        return {
            "status": _cmd_cache_status,
            "evict": _cmd_cache_evict,
            "rebuild": _cmd_cache_rebuild,
        }[args.csub](args)
    if cmd == "spec":
        return {"list": _cmd_spec_list}[args.ssub](args)
    return _DISPATCH[cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
