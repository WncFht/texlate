"""spec 编译检查叶 —— topo_stages Kahn 序 + compile_checks  authoring 面
linter (§4)。

原 ``kernel.spec`` 顶层「compile-time checks」段。门面回引名单见
``kernel.spec._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

from kernel import events
from kernel.spec.base import (
    _FN_STATUSES,
    _MUTATE_KINDS,
    _NAME_RE,
    _RUN_RE,
    _STAGE_RE,
    DEFAULT_STATUS_CLASS,
    EVAL_LAYERS,
    EXECUTORS,
    PARAM_TYPES,
    SELECTOR_PARAMS,
    STATUS_CLASSES,
    Param,
    Spec,
    SpecError,
    Stage,
)


def topo_stages(spec: Spec) -> list[Stage] | None:
    """Kahn topo order over needs+on edges; None on a cycle."""
    names = {st.name: st for st in spec.stages}
    indeg = {st.name: 0 for st in spec.stages}
    adj: dict[str, set[str]] = {st.name: set() for st in spec.stages}
    for st in spec.stages:
        # needs+on to the SAME upstream are one logical edge (accept set
        # unions) — counting them twice strands indeg above zero and
        # false-positives the cycle check (fixloop's needs+on to compile
        # is the designed shape).
        for up in {u for u, _ in st.needs} | set(st.on):
            if up in names:
                adj[up].add(st.name)
                indeg[st.name] += 1
    order = []
    ready = sorted(n for n, d in indeg.items() if d == 0)
    while ready:
        n = ready.pop(0)
        order.append(names[n])
        for m in sorted(adj[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
        ready.sort()
    if len(order) != len(spec.stages):
        return None
    return order


def compile_checks(spec: Spec) -> list[str]:
    """Authoring-surface linter (§4). Returns a list of problem strings —
    empty means clean. Materializes one-shot items as a side effect."""
    problems: list[str] = []
    if not isinstance(spec, Spec):
        return [f"spec object is {type(spec).__name__}, not a kernel Spec"]
    if not _NAME_RE.fullmatch(spec.kind or ""):
        problems.append(f"kind {spec.kind!r} is not a safe path component")
    if spec.select is not None and not callable(spec.select):
        problems.append(
            f"select {spec.select!r} is not callable — the plan-filter "
            "channel takes (item, resolved_params) -> bool"
        )
    if spec.fetch_fn is not None:
        if not callable(spec.fetch_fn):
            problems.append(
                f"fetch_fn {spec.fetch_fn!r} is not callable — the "
                "corpus hydrator takes (idc, stage_dir) -> dict|None"
            )
        elif not spec.lake:
            problems.append(
                "fetch_fn declared but lake=False — a corpus hydrator "
                "is only meaningful on a lake-consuming spec"
            )
    if spec.executor not in EXECUTORS:
        problems.append(f"executor {spec.executor!r} not in {sorted(EXECUTORS)}")
    problems.extend(
        f"foreign_runs entry {fr!r} is not kind/date/slug"
        for fr in spec.foreign_runs
        if not _RUN_RE.fullmatch(str(fr))
    )

    # -- params ----------------------------------------------------------------------
    for name, p in spec.params.items():
        if not isinstance(p, Param):
            problems.append(f"param {name!r} is not a Param")
            continue
        if p.type not in PARAM_TYPES:
            problems.append(
                f"param {name!r}: type {p.type!r} not in "
                f"{[t.__name__ for t in PARAM_TYPES]}"
            )
        if p.required and p.default is not None:
            problems.append(f"param {name!r}: required=True but default is set")
        if p.default is not None and not isinstance(p.default, p.type):
            problems.append(
                f"param {name!r}: default {p.default!r} is not a "
                f"{getattr(p.type, '__name__', p.type)}"
            )
        if p.choices is not None:
            if not p.choices:
                problems.append(f"param {name!r}: empty choices list")
            elif p.default is not None and p.default not in p.choices:
                problems.append(f"param {name!r}: default {p.default!r} not in choices")
        if p.fp is True and name in SELECTOR_PARAMS:
            problems.append(
                f"param {name!r}: selector knob cannot carry fp=True "
                "(§3.4 — selector churn must not poison fingerprints)"
            )

    # -- stages ----------------------------------------------------------------------
    seen: set[str] = set()
    for st in spec.stages:
        if not isinstance(st, Stage):
            problems.append(f"stage {st!r} is not a Stage")
            continue
        if not _STAGE_RE.fullmatch(st.name or ""):
            problems.append(f"stage name {st.name!r} is not a safe name")
        if st.name in seen:
            problems.append(f"duplicate stage name {st.name!r}")
        seen.add(st.name)
        if not callable(st.fn):
            problems.append(f"stage {st.name!r}: fn is not callable")
        if st.executor is not None and st.executor not in EXECUTORS:
            problems.append(
                f"stage {st.name!r}: executor {st.executor!r} not in "
                f"{sorted(EXECUTORS)}"
            )
        problems.extend(
            f"stage {st.name!r}: mutates kind {k!r} not in {sorted(_MUTATE_KINDS)}"
            for k in st.mutates
            if k not in _MUTATE_KINDS
        )

    names = {st.name for st in spec.stages if isinstance(st, Stage)}

    # needs/on targets + accept vocab
    for st in spec.stages:
        if not isinstance(st, Stage):
            continue
        for up, accept in st.needs:
            if up not in names:
                problems.append(f"stage {st.name!r}: needs unknown stage {up!r}")
            if up == st.name:
                problems.append(f"stage {st.name!r}: needs itself")
            if not accept:
                problems.append(f"stage {st.name!r}: needs {up!r} has empty accept")
            bad = set(accept) - _FN_STATUSES
            if bad:
                problems.append(
                    f"stage {st.name!r}: needs {up!r} accept holds "
                    f"non-instrument statuses {sorted(bad)}"
                )
        for up, statuses in st.on.items():
            if up not in names:
                problems.append(f"stage {st.name!r}: on unknown stage {up!r}")
            bad = set(statuses) - _FN_STATUSES
            if bad:
                problems.append(
                    f"stage {st.name!r}: on {up!r} holds non-instrument "
                    f"statuses {sorted(bad)}"
                )

    if topo_stages(spec) is None:
        problems.append("needs/on edges form a cycle")

    # status_class per stage (§3.1 mandatory declaration)
    accepted_downstream: dict[str, set[str]] = {}
    for st in spec.stages:
        if not isinstance(st, Stage):
            continue
        for up, accept in st.needs:
            accepted_downstream.setdefault(up, set()).update(accept)
        for up, statuses in st.on.items():
            accepted_downstream.setdefault(up, set()).update(statuses)
    for st in spec.stages:
        if not isinstance(st, Stage):
            continue
        sc = st.status_class or DEFAULT_STATUS_CLASS
        bad_keys = set(sc) - _FN_STATUSES
        if bad_keys:
            problems.append(
                f"stage {st.name!r}: status_class keys {sorted(bad_keys)} "
                "are not instrument statuses (kernel statuses are banned)"
            )
        bad_vals = set(sc.values()) - STATUS_CLASSES
        if bad_vals:
            problems.append(
                f"stage {st.name!r}: status_class values {sorted(bad_vals)} "
                f"not in {sorted(STATUS_CLASSES)}"
            )
        for status, cls in sc.items():
            if status in events.STATUS_DONE and cls == "retriable":
                problems.append(
                    f"stage {st.name!r}: DONE status {status!r} mapped to "
                    "retriable (§3.1 — pseudo-terminal must never retry)"
                )
        must = {"ok"} | accepted_downstream.get(st.name, set())
        missing = {s for s in must if s in _FN_STATUSES and s not in sc}
        if missing:
            problems.append(
                f"stage {st.name!r}: status_class does not classify "
                f"{sorted(missing)} (ok + downstream-accepted statuses)"
            )

    # paid stages need a dedup_key somewhere (§4)
    for st in spec.stages:
        if isinstance(st, Stage) and st.paid:
            if st.dedup_key is None and spec.dedup_key is None:
                problems.append(
                    f"paid stage {st.name!r}: dedup_key required "
                    "(asset default None is fine — declare it explicitly "
                    "at stage or spec level)"
                )
            eff = st.dedup_key if st.dedup_key is not None else spec.dedup_key
            remapped = callable(eff) or (
                eff is not None and tuple(eff) != ("idc", "arm", "variant")
            )
            # §4 eval keyspace: eval specs/stages may claim on a custom
            # (idc,arm,variant) triple (xlatbench model/rep/sample) —
            # cell-keyed evidence legs read 'absent' there BY DESIGN (no
            # assets exist under the eval keyspace; the claim mutex and
            # records lane are what dedup re-runs). Asset-paid stages keep
            # the hard ban — a remapped key reads 'absent' forever and
            # re-burns spend.
            if remapped and not (spec.eval or st.eval):
                problems.append(
                    f"paid stage {st.name!r}: dedup_key remap {eff!r} "
                    "voids cell-keyed evidence legs — manifest/claim/"
                    "paid_pool evidence is keyed (idc,arm,variant), so a "
                    "remapped key always reads 'absent' and re-burns. "
                    "Only eval specs/stages may remap the claim keyspace."
                )
            if remapped and (spec.eval or st.eval) and st.mutates:
                problems.append(
                    f"paid stage {st.name!r}: dedup_key remap {eff!r} on a "
                    "mutating eval stage splits evidence — vault/manifest "
                    "bytes land on the CELL key while claims ride the "
                    "remap, so a re-run dedups neither lane cleanly. Drop "
                    "mutates or keep the asset default key."
                )
    # Clarify: asset default IS 'no explicit key'; the check above only
    # fires when the author forgot the knob entirely AND spec lacks one.
    # An explicit dedup_key=None on the stage reads as the asset default.

    # -- items -----------------------------------------------------------------------
    try:
        items = spec.iter_items()
    except SpecError as exc:
        problems.extend(exc.problems)
        items = []
    allowed = set(spec.allowed_layers)
    keys: set[tuple] = set()
    for i, it in enumerate(items):
        if not it.get("id"):
            problems.append(f"items[{i}]: missing id")
            continue
        layer = it.get("layer")
        if layer is not None:
            if allowed and layer not in allowed:
                problems.append(
                    f"item {it.get('id')!r}: layer {layer!r} not in "
                    f"allowed_layers {sorted(allowed)}"
                )
            if layer in EVAL_LAYERS and not spec.eval:
                problems.append(
                    f"item {it.get('id')!r}: layer {layer!r} requires spec.eval=True"
                )
        stages = [it["stage"]] if it.get("stage") else [st.name for st in spec.stages]
        for sname in stages:
            if sname not in names:
                problems.append(f"item {it.get('id')!r}: unknown stage {sname!r}")
                continue
            key = (
                str(it["id"]),
                str(it["arm"]),
                str(it["up"]),
                str(it["variant"]),
                str(sname),
            )
            if key in keys:
                problems.append(f"duplicate item cell key {key}")
            keys.add(key)
    return problems
