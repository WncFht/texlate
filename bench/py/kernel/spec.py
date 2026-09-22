"""Spec v2 authoring surface + compile-time checks (design §4).

A bench is one ``.py`` file exporting a ``spec`` object::

    spec = Spec(
        kind="soak",
        params={"ruleset": Param(default="hard18"), "n": Param(int, required=True)},
        stages=[
            Stage("ingest", fn=do_ingest, status_class={"ok": "terminal"}),
            Stage("xlat", fn=do_xlat, needs=[("ingest", {"ok"})], paid=True,
                  status_class={"ok": "terminal", "error": "retriable"}),
        ],
        items=items,                # iterable of (id, arm, up, variant)
        freeze_plan=True,
        executor="thread",
    )

Rules baked here:

- ``compile_checks`` runs at load AND at run start — stage names unique,
  needs/on targets exist, the needs DAG is acyclic, every stage's
  ``status_class`` covers 'ok' plus every status downstream stages accept,
  DONE statuses are never mapped to 'retriable' (§3.1: "禁把伪终态映进
  RETRIABLE"), paid stages carry a dedup_key (stage or spec level), item
  (id,arm,up,variant,stage) keys are unique, params schema has real types.
- ``status_class`` maps an instrument-returned status to
  terminal|retriable|upstream. 'upstream' means the errors[0].cat='upstream'
  triage-exempt marker — retriable for accounting, flagged for triage.
  An unclassified status at runtime lands 'fault' + note, never a silent
  retry (§3.1 fail-loud).
- fp params: selector knobs (n/seed/jobs/layer/run) are auto-excluded from
  the fp params component (§3.4) — ``Param(fp=True)`` on one is a compile
  error; ``fp=False`` elsewhere just pins the exclusion.
- items may be dicts, tuples (id[,arm[,up[,variant[,stage]]]]) or bare ids;
  a callable/generator is materialized ONCE into spec.items at check time.
"""
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from kernel import events

__all__ = [
    "DEFAULT_STATUS_CLASS",
    "EVAL_LAYERS",
    "EXECUTORS",
    "PARAM_TYPES",
    "SELECTOR_PARAMS",
    "STATUS_CLASSES",
    "Param",
    "Spec",
    "SpecError",
    "Stage",
    "cell_fp",
    "code_sha",
    "compile_checks",
    "load_spec",
    "spec_hash",
    "topo_stages",
]

# §3.4: selector knobs are banned from the fp params component.
SELECTOR_PARAMS = frozenset({"n", "seed", "jobs", "layer", "run"})

# status_class value vocabulary.
STATUS_CLASSES = frozenset({"terminal", "retriable", "upstream"})

# The canonical classification every stage starts from when the author
# doesn't declare one: DONE statuses are terminal, RETRIABLE are
# retriable. §3.1's mandatory-declaration teeth stay in compile_checks —
# a declared table must still cover ok + downstream-accepted statuses and
# may never map a DONE status to retriable — but omitting the table means
# "the obvious one", not an error (the authoring surface examples and
# shipped specs rely on this).
DEFAULT_STATUS_CLASS = dict(
    sorted(
        {**{s: "terminal" for s in events.STATUS_DONE},
         **{s: "retriable" for s in events.STATUS_RETRIABLE}}.items()
    )
)

EXECUTORS = frozenset({"thread", "process", "async-owned"})

# Layers that require spec.eval=True to enter items (holdout/eval_only are
# never casually runnable — §4 allowed_layers contract).
EVAL_LAYERS = frozenset({"holdout", "eval_only"})

PARAM_TYPES = (str, int, float, bool)

# Statuses a stage function may legitimately return: everything except the
# kernel-internal masks (those are emitted by the kernel, never the fn).
_FN_STATUSES = events.ALL_STATUSES - events.STATUS_KERNEL

_MUTATE_KINDS = frozenset({"zh", "splice", "state"})

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_STAGE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")
_RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[0-9]{4}-[0-9]{2}-[0-9]{2}/[A-Za-z0-9][A-Za-z0-9._-]*")


class SpecError(ValueError):
    """Spec failed authoring or compile checks. Carries the check list."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("spec compile errors:\n  " + "\n  ".join(self.problems))


# --- Param ------------------------------------------------------------------------


class Param:
    """One spec param: typed, optionally required/choices-bounded.

    ``fp`` controls the §3.4 params component: ``None`` = auto (True unless
    the name is a selector knob), explicit True/False pins it. ``fp=True``
    on a selector knob is a compile error — selector churn must never
    poison fingerprints.
    """

    def __init__(self, type=str, default=None, required: bool = False,
                 choices=None, fp=None):
        self.type = type
        self.default = default
        self.required = bool(required)
        self.choices = list(choices) if choices is not None else None
        self.fp = fp

    def fp_effective(self, name: str) -> bool:
        if self.fp is not None:
            return bool(self.fp)
        return name not in SELECTOR_PARAMS

    def coerce(self, name: str, raw):
        """Validate + coerce one supplied value (CLI params arrive as str)."""
        if raw is None:
            return None
        v = raw
        if self.type is bool and isinstance(v, str):
            v = v.strip().lower()
            if v in ("1", "true", "yes", "on"):
                v = True
            elif v in ("0", "false", "no", "off"):
                v = False
            else:
                raise SpecError([f"param {name!r}: {raw!r} is not a bool"])
        elif self.type is not str and isinstance(v, str):
            try:
                v = self.type(v)
            except (TypeError, ValueError):
                raise SpecError(
                    [f"param {name!r}: {raw!r} is not a {self.type.__name__}"]
                )
        if not isinstance(v, self.type) or isinstance(v, bool) != (self.type is bool) and self.type is bool:
            if not isinstance(v, self.type):
                raise SpecError(
                    [f"param {name!r}: {v!r} is not a {self.type.__name__}"]
                )
        if self.choices is not None and v not in self.choices:
            raise SpecError(
                [f"param {name!r}: {v!r} not in choices {self.choices}"]
            )
        return v

    def to_dict(self, name: str) -> dict:
        return {
            "type": getattr(self.type, "__name__", str(self.type)),
            "default": self.default,
            "required": self.required,
            "choices": self.choices,
            "fp": self.fp_effective(name),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Param({getattr(self.type, '__name__', self.type)}, "
            f"default={self.default!r}, required={self.required}, "
            f"choices={self.choices!r}, fp={self.fp!r})"
        )


# --- Stage ------------------------------------------------------------------------


def _norm_need(entry) -> tuple[str, frozenset]:
    """Normalize one needs entry -> (stage_name, accept_frozenset).

    Accepted spellings: "stage" (accept={'ok'}), ("stage", {"a","b"}),
    ("stage", {"accept": {...}}), {"stage": "s", "accept": {...}}.
    """
    if isinstance(entry, str):
        return entry, frozenset({"ok"})
    if isinstance(entry, dict):
        name = entry.get("stage") or entry.get("name")
        accept = entry.get("accept", {"ok"})
        return str(name), frozenset(accept)
    seq = list(entry)
    name = str(seq[0])
    if len(seq) < 2 or seq[1] is None:
        return name, frozenset({"ok"})
    second = seq[1]
    if isinstance(second, dict) and "accept" in second:
        second = second["accept"]
    return name, frozenset(second)


class Stage:
    """One pipeline stage.

    needs   [(stage, accept={...})] — each is a hard edge: the upstream
            cell's last effective record must exist in the needs domain and
            carry an acceptable status, else the cell skips.
    on      {stage: {status,...}} — trigger widening: merged into that
            edge's accept set (fixloop declares on={"compile": {"fail",
            "dirty_pdf"}} so it also runs after upstream failures).
    paid    stage spends gateway quota — claims/dedup/budget machinery on.
    executor 'thread'|'process'|'async-owned' override of spec.executor.
    cost_hook fn(usage_dict) -> usd for the meter; None = price table.
    mutates asset kinds this stage (re)writes: subset of {zh,splice,state}.
    status_class {status: 'terminal'|'retriable'|'upstream'} — optional;
            DEFAULT_STATUS_CLASS applies when omitted. Declare whenever
            the stage can return non-standard statuses (paid stages
            SHOULD — §3.1's mandatory review point).
    dedup_key None (asset default (idc,arm,variant)) | callable
            cell->(idc,arm,variant) | tuple of cell-field names.
    eval    stage's terminal rows also land in the eval_records lane
            (judge/score stages inside a mixed spec; spec.eval marks the
            whole run).
    """

    def __init__(self, name, fn, needs=None, paid: bool = False,
                 executor=None, cost_hook=None, mutates=None, on=None,
                 status_class=None, dedup_key=None, eval: bool = False):
        self.name = str(name)
        self.fn = fn
        self.needs = [_norm_need(n) for n in (needs or [])]
        self.paid = bool(paid)
        self.executor = executor
        self.cost_hook = cost_hook
        self.mutates = [str(m) for m in (mutates or [])]
        self.on = {str(k): frozenset(v) for k, v in (on or {}).items()}
        self.status_class = (dict(status_class) if status_class
                             else dict(DEFAULT_STATUS_CLASS))
        self.dedup_key = dedup_key
        self.eval = bool(eval)

    def accept_for(self, up_stage: str) -> frozenset:
        """Effective accept set for one upstream edge (needs accept ∪ on)."""
        for name, accept in self.needs:
            if name == up_stage:
                return accept | self.on.get(up_stage, frozenset())
        return self.on.get(up_stage, frozenset())

    def to_dict(self) -> dict:
        fn = self.fn
        fnref = f"{getattr(fn, '__module__', '')}.{getattr(fn, '__qualname__', repr(fn))}"
        return {
            "name": self.name,
            "fn": fnref,
            "needs": [{"stage": s, "accept": sorted(a)} for s, a in self.needs],
            "paid": self.paid,
            "executor": self.executor,
            "cost_hook": getattr(self.cost_hook, "__qualname__", None)
            if self.cost_hook else None,
            "mutates": list(self.mutates),
            "on": {k: sorted(v) for k, v in self.on.items()},
            "status_class": self.status_class,
            "eval": self.eval,
            "dedup_key": (
                None if self.dedup_key is None
                else list(self.dedup_key) if isinstance(self.dedup_key, (list, tuple))
                else getattr(self.dedup_key, "__qualname__", repr(self.dedup_key))
            ),
        }


# --- Spec -------------------------------------------------------------------------


class Spec:
    """The bench definition — one per spec file."""

    def __init__(self, kind, params=None, stages=None, items=None,
                 freeze_plan: bool = True, executor: str = "thread",
                 env_probes=None, code_deps=None, foreign_runs=None,
                 allowed_layers=None, lake: bool = False,
                 same_id_serial: bool = True, dedup_key=None,
                 eval: bool = False, gateway_factory=None, select=None):
        self.kind = str(kind)
        self.params = dict(params or {})
        self.stages = list(stages or [])
        self.items = items
        self.freeze_plan = bool(freeze_plan)
        self.executor = executor
        self.env_probes = list(env_probes or [])
        self.code_deps = list(code_deps or [])
        self.foreign_runs = list(foreign_runs or [])
        self.allowed_layers = list(allowed_layers or [])
        self.lake = bool(lake)
        self.same_id_serial = bool(same_id_serial)
        self.dedup_key = dedup_key
        self.eval = bool(eval)
        # ``select(item, resolved_params) -> bool`` — the plan-filter
        # channel: items() enumerates the full frame once, select narrows
        # it per-run by run params (soak --n/--seed/--ids/--layers).
        # Applied post-normalization, pre-canon inside _enumerate_cells;
        # NEVER at compile_checks (selector params only exist at run time).
        self.select = select
        # Paid gateway the run falls back to when the caller doesn't
        # inject one — GatewayFactory | callable | None. Config, not
        # semantics: deliberately excluded from to_dict/spec_hash.
        self.gateway_factory = gateway_factory
        # Filled by load_spec / run(): source path and resolved-params record.
        self._path: str | None = None
        self._code_sha: str | None = None

    # -- items --------------------------------------------------------------------

    def materialize_items(self) -> list:
        """Force one-shot iterables into a concrete list (once)."""
        if callable(self.items) and not isinstance(self.items, list):
            self.items = list(self.items())
        elif self.items is None:
            self.items = []
        elif not isinstance(self.items, list):
            self.items = list(self.items)
        return self.items

    def iter_items(self) -> list:
        """Normalized item dicts: {id, arm, up, variant, stage?, layer?,
        params?, fp_input?}. Raw ids only — canon happens at plan time."""
        out = []
        for it in self.materialize_items():
            out.append(norm_item(it))
        return out

    def stage(self, name: str) -> Stage | None:
        for st in self.stages:
            if st.name == name:
                return st
        return None

    def last_mutating_stage(self) -> str | None:
        """The stage after which per-id harvest fires (§3.5): the LAST
        stage in spec order that declares mutates."""
        last = None
        for st in self.stages:
            if st.mutates:
                last = st.name
        return last

    def mutating_kinds(self) -> list:
        """Union of all stages' mutates declarations (the harvest set)."""
        seen = []
        for st in self.stages:
            for k in st.mutates:
                if k not in seen:
                    seen.append(k)
        return seen

    def has_paid(self) -> bool:
        return any(st.paid for st in self.stages)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "params": {k: p.to_dict(k) for k, p in self.params.items()},
            "stages": [st.to_dict() for st in self.stages],
            "freeze_plan": self.freeze_plan,
            "executor": self.executor,
            "env_probes": list(self.env_probes),
            "code_deps": list(self.code_deps),
            "foreign_runs": list(self.foreign_runs),
            "allowed_layers": list(self.allowed_layers),
            "lake": self.lake,
            "same_id_serial": self.same_id_serial,
            "dedup_key": (
                None if self.dedup_key is None
                else list(self.dedup_key) if isinstance(self.dedup_key, (list, tuple))
                else getattr(self.dedup_key, "__qualname__", repr(self.dedup_key))
            ),
            "eval": self.eval,
            "select": (None if self.select is None else
                       getattr(self.select, "__qualname__",
                               repr(self.select))),
            "items": self.iter_items(),
        }

    def dedup_key_of(self, stage: Stage, cell: dict) -> tuple:
        """(idc,arm,variant) claim-space key for a paid cell (§3.6/R25).

        Eval-type paid stages declare their own dedup_key (callable
        cell->triple or field-name tuple); asset-type defaults to the
        cell's own (idc,arm,variant).
        """
        key = stage.dedup_key if stage.dedup_key is not None else self.dedup_key
        if key is None:
            return (str(cell.get("idc")), str(cell.get("arm", "-")),
                    str(cell.get("variant", "-")))
        if callable(key):
            out = key(cell)
            idc, arm, variant = (list(out) + ["-", "-"])[:3]
            return str(idc), str(arm), str(variant)
        fields = list(key)
        vals = [str(cell.get(f, "-")) for f in fields[:3]]
        while len(vals) < 3:
            vals.append("-")
        return tuple(vals)


def norm_item(it) -> dict:
    """Normalize one item spelling -> dict with id/arm/up/variant keys."""
    if isinstance(it, dict):
        d = dict(it)
        if "id" not in d and "idc" in d:
            d["id"] = d["idc"]
    elif isinstance(it, str):
        d = {"id": it}
    else:
        seq = list(it)
        keys = ("id", "arm", "up", "variant", "stage")
        d = {k: seq[i] for i, k in enumerate(keys) if i < len(seq)}
    if "id" not in d or d["id"] is None:
        raise SpecError([f"item lacks an id: {it!r}"])
    d.setdefault("arm", "-")
    d.setdefault("up", "-")
    d.setdefault("variant", "-")
    return d


# --- compile-time checks ------------------------------------------------------------


def topo_stages(spec: Spec) -> list[Stage] | None:
    """Kahn topo order over needs+on edges; None on a cycle."""
    names = {st.name: st for st in spec.stages}
    indeg = {st.name: 0 for st in spec.stages}
    adj: dict[str, set[str]] = {st.name: set() for st in spec.stages}
    for st in spec.stages:
        for up, _acc in st.needs:
            if up in names:
                adj[up].add(st.name)
                indeg[st.name] += 1
        for up in st.on:
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
            "channel takes (item, resolved_params) -> bool")
    if spec.executor not in EXECUTORS:
        problems.append(
            f"executor {spec.executor!r} not in {sorted(EXECUTORS)}")
    for fr in spec.foreign_runs:
        if not _RUN_RE.fullmatch(str(fr)):
            problems.append(
                f"foreign_runs entry {fr!r} is not kind/date/slug")

    # -- params ----------------------------------------------------------------------
    for name, p in spec.params.items():
        if not isinstance(p, Param):
            problems.append(f"param {name!r} is not a Param")
            continue
        if p.type not in PARAM_TYPES:
            problems.append(
                f"param {name!r}: type {p.type!r} not in "
                f"{[t.__name__ for t in PARAM_TYPES]}")
        if p.required and p.default is not None:
            problems.append(
                f"param {name!r}: required=True but default is set")
        if p.default is not None and not isinstance(p.default, p.type):
            problems.append(
                f"param {name!r}: default {p.default!r} is not a "
                f"{getattr(p.type, '__name__', p.type)}")
        if p.choices is not None:
            if not p.choices:
                problems.append(f"param {name!r}: empty choices list")
            elif p.default is not None and p.default not in p.choices:
                problems.append(
                    f"param {name!r}: default {p.default!r} not in choices")
        if p.fp is True and name in SELECTOR_PARAMS:
            problems.append(
                f"param {name!r}: selector knob cannot carry fp=True "
                "(§3.4 — selector churn must not poison fingerprints)")

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
                f"{sorted(EXECUTORS)}")
        for k in st.mutates:
            if k not in _MUTATE_KINDS:
                problems.append(
                    f"stage {st.name!r}: mutates kind {k!r} not in "
                    f"{sorted(_MUTATE_KINDS)}")

    names = {st.name for st in spec.stages if isinstance(st, Stage)}

    # needs/on targets + accept vocab
    for st in spec.stages:
        if not isinstance(st, Stage):
            continue
        for up, accept in st.needs:
            if up not in names:
                problems.append(
                    f"stage {st.name!r}: needs unknown stage {up!r}")
            if up == st.name:
                problems.append(f"stage {st.name!r}: needs itself")
            if not accept:
                problems.append(
                    f"stage {st.name!r}: needs {up!r} has empty accept")
            bad = set(accept) - _FN_STATUSES
            if bad:
                problems.append(
                    f"stage {st.name!r}: needs {up!r} accept holds "
                    f"non-instrument statuses {sorted(bad)}")
        for up, statuses in st.on.items():
            if up not in names:
                problems.append(
                    f"stage {st.name!r}: on unknown stage {up!r}")
            bad = set(statuses) - _FN_STATUSES
            if bad:
                problems.append(
                    f"stage {st.name!r}: on {up!r} holds non-instrument "
                    f"statuses {sorted(bad)}")

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
                "are not instrument statuses (kernel statuses are banned)")
        bad_vals = set(sc.values()) - STATUS_CLASSES
        if bad_vals:
            problems.append(
                f"stage {st.name!r}: status_class values {sorted(bad_vals)} "
                f"not in {sorted(STATUS_CLASSES)}")
        for status, cls in sc.items():
            if status in events.STATUS_DONE and cls == "retriable":
                problems.append(
                    f"stage {st.name!r}: DONE status {status!r} mapped to "
                    "retriable (§3.1 — pseudo-terminal must never retry)")
        must = {"ok"} | accepted_downstream.get(st.name, set())
        missing = {s for s in must if s in _FN_STATUSES and s not in sc}
        if missing:
            problems.append(
                f"stage {st.name!r}: status_class does not classify "
                f"{sorted(missing)} (ok + downstream-accepted statuses)")

    # paid stages need a dedup_key somewhere (§4)
    for st in spec.stages:
        if isinstance(st, Stage) and st.paid:
            if st.dedup_key is None and spec.dedup_key is None:
                problems.append(
                    f"paid stage {st.name!r}: dedup_key required "
                    "(asset default None is fine — declare it explicitly "
                    "at stage or spec level)")
            eff = st.dedup_key if st.dedup_key is not None else spec.dedup_key
            remapped = callable(eff) or (
                eff is not None and tuple(eff) != ("idc", "arm", "variant"))
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
                    "Only eval specs/stages may remap the claim keyspace.")
            if remapped and (spec.eval or st.eval) and st.mutates:
                problems.append(
                    f"paid stage {st.name!r}: dedup_key remap {eff!r} on a "
                    "mutating eval stage splits evidence — vault/manifest "
                    "bytes land on the CELL key while claims ride the "
                    "remap, so a re-run dedups neither lane cleanly. Drop "
                    "mutates or keep the asset default key.")
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
                    f"allowed_layers {sorted(allowed)}")
            if layer in EVAL_LAYERS and not spec.eval:
                problems.append(
                    f"item {it.get('id')!r}: layer {layer!r} requires "
                    "spec.eval=True")
        stages = [it["stage"]] if it.get("stage") else [st.name for st in spec.stages]
        for sname in stages:
            if sname not in names:
                problems.append(
                    f"item {it.get('id')!r}: unknown stage {sname!r}")
                continue
            key = (str(it["id"]), str(it["arm"]), str(it["up"]),
                   str(it["variant"]), str(sname))
            if key in keys:
                problems.append(
                    f"duplicate item cell key {key}")
            keys.add(key)
    return problems


# --- hashing ------------------------------------------------------------------------


def _iter_dep_files(dep) -> list[Path]:
    p = Path(dep)
    if p.is_file():
        return [p]
    if p.is_dir():
        return sorted(f for f in p.rglob("*") if f.is_file())
    return []


def code_sha(spec: Spec, path=None) -> str:
    """The §3.4 code component: spec source bytes (or stage fn sources when
    no file exists) + every code_deps file's content. NOT a repo sha —
    a dirty tree can never poison the fingerprint."""
    if spec._code_sha is not None and path is None:
        return spec._code_sha
    h = hashlib.sha256()
    p = Path(path) if path is not None else (
        Path(spec._path) if spec._path else None)
    if p is not None and p.is_file():
        h.update(b"spec-file\x00")
        h.update(p.read_bytes())
    else:
        for st in spec.stages:
            try:
                src = inspect.getsource(st.fn)
            except (OSError, TypeError):
                src = repr(st.fn)
            h.update(b"fn\x00")
            h.update(st.name.encode("utf-8"))
            h.update(src.encode("utf-8", "replace"))
    for dep in spec.code_deps:
        for f in _iter_dep_files(dep):
            h.update(b"dep\x00")
            h.update(str(f).encode("utf-8"))
            h.update(f.read_bytes())
    out = h.hexdigest()
    if path is None:
        spec._code_sha = out
    return out


def spec_hash(spec: Spec, path=None) -> str:
    """Run-registration hash: code component + the serialized spec dict.
    spec_hash feeds run_registered/invocations, never the run identity
    (R15) — but it pins exactly what definition produced this run."""
    payload = {
        "code": code_sha(spec, path),
        "spec": spec.to_dict(),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def cell_fp(spec: Spec, cell: dict) -> str:
    """Per-cell fingerprint (§3.4):
    sha256(code component, fp_input, cell-level effective fp params).

    fp never enters done decisions — it only marks staleness. fp_input is
    the upstream fp chain (or manifest-supplied input hash); params carry
    only fp-effective cell params (selector knobs structurally excluded).
    """
    merged = dict(cell.get("run_params") or {})
    merged.update(cell.get("params") or {})
    fp_params = {
        k: v for k, v in sorted(merged.items())
        if k in spec.params and spec.params[k].fp_effective(k)
    }
    payload = {
        "code": code_sha(spec),
        "input": cell.get("fp_input"),
        "params": fp_params,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# --- loading ------------------------------------------------------------------------


def load_spec(path) -> Spec:
    """Exec a spec .py file and return its ``spec`` object.

    The file must define a module-level ``spec`` (a Spec). compile_checks
    run here — a spec that fails authoring never reaches the kernel.
    """
    p = Path(path)
    if not p.is_file():
        raise SpecError([f"spec file not found: {p}"])
    name = f"_texlate_spec_{hashlib.sha256(str(p).encode()).hexdigest()[:12]}"
    mod = importlib.util.spec_from_file_location(name, p)
    if mod is None or mod.loader is None:
        raise SpecError([f"cannot load spec file: {p}"])
    module = importlib.util.module_from_spec(mod)
    sys.modules[name] = module
    try:
        mod.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    spec = getattr(module, "spec", None)
    if spec is None:
        # tolerate single-Spec files that named it differently
        cands = [v for v in vars(module).values() if isinstance(v, Spec)]
        spec = cands[0] if len(cands) == 1 else None
    if not isinstance(spec, Spec):
        raise SpecError(
            [f"{p} exports no `spec` Spec object"])
    spec._path = str(p)
    problems = compile_checks(spec)
    if problems:
        raise SpecError(problems)
    return spec
