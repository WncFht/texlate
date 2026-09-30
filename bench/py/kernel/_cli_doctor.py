"""kernel._cli_doctor — doctor/fsck 体检动词叶 (kernel.cli 拆分叶).

``bench doctor`` (kernel 健康检查，--fix 修可修项，--switch-ok 换机闸)
与 ``bench fsck`` (更深层一致性检查，--defer-edges 挂边检查可跳)。
两动词都走 ``_lazy("doctor")`` 惰性拉 kernel.doctor——拉不到报
"unavailable" (exit 1) 而非崩溃。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

from kernel._cli_common import EXIT_FAIL, EXIT_OK, _err, _lazy


def _print_checks(checks) -> bool:
    ok = True
    for c in checks:
        good = bool(c.get("ok"))
        ok = ok and good
        mark = "ok" if good else "FAIL"
        detail = c.get("detail", "")
        print(f"  [{mark}] {c.get('name')}" + (f" — {detail}" if detail else ""))
    return ok


def _cmd_doctor(args) -> int:
    mod, err = _lazy("doctor")
    fn = getattr(mod, "doctor", None) if mod is not None else None
    if fn is None:
        _err(f"doctor: kernel.doctor unavailable ({err})")
        return EXIT_FAIL
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
        _err(f"fsck: kernel.doctor.fsck unavailable ({err})")
        return EXIT_FAIL
    try:
        rep = fn(defer_edges=args.defer_edges)
    except Exception as exc:
        _err(f"fsck failed: {exc}")
        return EXIT_FAIL
    checks = rep.get("checks", []) if isinstance(rep, dict) else []
    ok = _print_checks(checks) if checks else bool(rep.get("ok", True))
    return EXIT_OK if ok else EXIT_FAIL
