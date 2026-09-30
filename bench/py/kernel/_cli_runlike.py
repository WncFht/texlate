"""kernel._cli_runlike — init/run/plan 动词叶 (kernel.cli 拆分叶).

- ``_cmd_init``      — $TEXLATE_BENCH_ROOT zone layout 落成
- ``_kernel_run_path`` — kernel.kernel 的 run/plan 函数惰性解析
  (sys.modules["kernel.kernel"] fake 缝在此命中)
- ``_run_kwargs``/``_detach_run`` — run flag 规整与 detach re-exec
  (R22: 子进程自持 detach.lock; §3.6: paid spec 强制 --max-cost)
- ``_cmd_run``/``_cmd_plan`` — 动词本体 (run 先过 PAUSE 付费闸 +
  写前轻扫; plan 是 dry-run 永远放行)
- ``_print_quote``   — §3.6 五桶报价 + regen 决定表打印

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from kernel import locks, paths
from kernel._cli_common import (
    EXIT_FAIL,
    EXIT_OK,
    EXIT_REFUSED,
    _collect_params,
    _err,
    _lazy,
    _pause_refused,
    _pre_write,
    _print_json,
    _resolve_spec,
    _shim_path,
    _spec_paidness,
)

if TYPE_CHECKING:
    from pathlib import Path


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
        paid = any(getattr(st, "paid", False) for st in getattr(s, "stages", []) or ())
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
