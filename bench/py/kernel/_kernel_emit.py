"""kernel._kernel_emit — 事件落账叶 (kernel.kernel 拆分叶).

cell 临界段与 run 管线共享的最小 emit 面：

- ``_CELL_MERGE_KEYS``/``_CELL_RESERVED`` — outbox 归并白名单与
  framework 保留键 (emit() 不得改写身份/状态)
- ``_merge_outbox`` — 作者 emit() 行折叠进终态事件 + verbatim 事件
- ``_synth_sig``    — errors[0] -> ``cat:pay`` 默认 sig
- ``_terminal_ev``  — T_CELL 终态戳构造 (eval 标记/cat/dur_s/fp/sig 合成)
- ``_note``         — kernel note 行 (负 seq 命名空间，best-effort)
- ``_emit``/``_emit_batch`` — ledger.emit(_batch) + index sink 绑定

门面回引名单见 ``kernel.kernel._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import contextlib

from kernel import events, ledger, runs


def _emit(env, idx, ev):
    return ledger.emit(ev, run_dir=env.rd.path, sink=idx.apply_event)


def _emit_batch(env, idx, evs):
    return ledger.emit_batch(evs, run_dir=env.rd.path, sink=idx.apply_event)


def _note(env, text: str, level: str = "info"):
    """Kernel note row — negative seqs (kernel writer namespace)."""
    # best-effort: a dead run dir must never kill the cell that wanted a note
    with contextlib.suppress(Exception):
        runs._emit_note(env.rd, text, level=level)


_CELL_MERGE_KEYS = {"metrics", "errors", "sig", "code", "dur_s"}
# Framework-owned cell fields — emit() can never rewrite identity/status
# (status comes from the fn return alone; fp is kernel-stamped).
_CELL_RESERVED = {
    "id",
    "idc",
    "arm",
    "up",
    "variant",
    "stage",
    "run",
    "seq",
    "ts",
    "type",
    "status",
    "fp",
}


def _merge_outbox(terminal_ev: dict, outbox: list) -> list:
    """Fold author emit() rows into the terminal event + verbatim events.

    Rows without 'type' merge into the terminal cell event: whitelisted
    merge keys fold directly (metrics update, errors extend, scalars
    last-wins); cell-identity/framework keys drop; every other payload
    key folds into ``metrics`` — that keeps the T_CELL whitelist closed
    while still landing author rows like {metric, chars, lines} on the
    ledger (§3.1). Rows with 'type' (make_event'd verbatim events incl.
    buffered notes) pass through as their own ledger rows.
    """
    extra: list[dict] = []

    def _metrics() -> dict:
        m = terminal_ev.get("metrics")
        if not isinstance(m, dict):
            m = {}
            terminal_ev["metrics"] = m
        return m

    for row in outbox:
        if not isinstance(row, dict):
            continue
        if "type" in row:
            extra.append(row)
            continue
        for k, v in row.items():
            if k in _CELL_RESERVED:
                continue
            if k == "metrics" and isinstance(v, dict):
                _metrics().update(v)
            elif k == "errors":
                e = terminal_ev.get("errors")
                if not isinstance(e, list):
                    e = []
                    terminal_ev["errors"] = e
                e.extend(v if isinstance(v, list) else [v])
            elif k in _CELL_MERGE_KEYS:
                terminal_ev[k] = v
            else:
                _metrics()[k] = v
    return extra


def _synth_sig(errors) -> str | None:
    """errors[0] -> ``cat:pay`` default sig (the benchlib.errors_sig triage
    contract as a kernel-side default — a fn returning its own sig always
    wins; this only fires when the row would otherwise carry none)."""
    if not isinstance(errors, list) or not errors:
        return None
    e0 = errors[0]
    if not isinstance(e0, dict):
        return None
    cat = str(e0.get("cat") or e0.get("code") or "error")
    pay = str(e0.get("payload") or "")
    return f"{cat}:{pay}".rstrip(":")


def _terminal_ev(
    env,
    cell,
    status: str,
    *,
    seq: int,
    cat=None,
    dur_s=None,
    fp=None,
    metrics=None,
    errors=None,
    sig=None,
    code=None,
    extra=None,
) -> dict:
    ev = events.make_event(
        events.T_CELL,
        run=env.rd.run,
        seq=seq,
        id=cell["id"],
        idc=cell["idc"],
        arm=cell["arm"],
        up=cell["up"],
        variant=cell["variant"],
        stage=cell["stage"],
        status=status,
    )
    spec = env.spec
    stage_obj = spec.stage(cell["stage"]) if spec is not None else None
    if (spec is not None and spec.eval) or (
        stage_obj is not None and getattr(stage_obj, "eval", False)
    ):
        ev["eval"] = True
    if cat is not None:
        ev["cat"] = cat
    if dur_s is not None:
        ev["dur_s"] = dur_s
    if fp is not None:
        ev["fp"] = fp
    if metrics is not None:
        ev["metrics"] = metrics
    if errors is not None:
        ev["errors"] = errors
    if sig is None:
        sig = _synth_sig(errors)
    if sig is not None:
        ev["sig"] = sig
    if code is not None:
        ev["code"] = code
    for k, v in (extra or {}).items():
        if k in events.OPTIONAL_WHITELIST:
            ev[k] = v
    return ev
