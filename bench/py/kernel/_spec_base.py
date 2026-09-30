"""spec 模型叶 —— 词表常量/SC_* 预设表/SpecError/Param/Stage/Spec/
norm_item (原 ``kernel.spec`` 顶层常量区 + authoring 三类)。

``Spec``/``Stage``/``Param``/``SpecError`` 的 ``__module__`` 钉回
``kernel.spec`` 保持 repr/pickle 引用路径不变。门面回引名单见
``kernel.spec._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import re

from kernel import events

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
        {
            **dict.fromkeys(events.STATUS_DONE, "terminal"),
            **dict.fromkeys(events.STATUS_RETRIABLE, "retriable"),
        }.items()
    )
)

# Named status_class presets for the shapes that recur verbatim across
# shipped specs (census: 13 of ~30 Stage sites share these five tables).
# Each preset is an exact-shape copy — dict content is wire data (lands in
# spec.json / plan fp), never extend a preset to fit a new stage. A stage
# whose fn-verdict alphabet matches no preset declares its own literal
# inline (mandatory-declaration teeth in compile_checks apply either way).
#
# skip=upstream 档（SC_SPECTRUM_UP）表「skip 是等上游格」的链段语义；
# 无 _UP 后缀的预设 skip=retriable（自格重试面）。
SC_SPECTRUM_UP = {
    "ok": "terminal",
    "clean": "terminal",
    "partial": "terminal",
    "fail": "terminal",
    "reject": "terminal",
    "dirty_pdf": "terminal",
    "skip": "upstream",
    "error": "retriable",
}

# 二值 verdict（ok/fail）仪器格。
SC_OK_FAIL = {
    "ok": "terminal",
    "fail": "terminal",
    "skip": "retriable",
    "error": "retriable",
}

# 裁决 verdict（ok/reject）——fn 无 skip 面，error 是唯一 retriable。
SC_OK_REJECT = {
    "ok": "terminal",
    "reject": "terminal",
    "error": "retriable",
}

# 纯测量格——verdict 只返 ok（发现全进 metrics）。
SC_OK_ONLY = {
    "ok": "terminal",
    "skip": "retriable",
    "error": "retriable",
}

# 部分成功 verdict（ok/partial）——翻译族产物格。
SC_OK_PARTIAL = {
    "ok": "terminal",
    "partial": "terminal",
    "skip": "retriable",
    "error": "retriable",
}

EXECUTORS = frozenset({"thread", "process", "async-owned"})

# Layers that require spec.eval=True to enter items (holdout/eval_only are
# never casually runnable — §4 allowed_layers contract).
EVAL_LAYERS = frozenset({"holdout", "eval_only"})

PARAM_TYPES = (str, int, float, bool)

# Statuses a stage function may legitimately return: everything except the
# kernel-internal masks (those are emitted by the kernel, never the fn).
_FN_STATUSES = events.ALL_STATUSES - events.STATUS_KERNEL

_MUTATE_KINDS = frozenset({"zh", "splice", "state", "layoutqc"})

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_STAGE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}")
_RUN_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*/[0-9]{4}-[0-9]{2}-[0-9]{2}/[A-Za-z0-9][A-Za-z0-9._-]*"
)


class SpecError(ValueError):
    """Spec failed authoring or compile checks. Carries the check list."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("spec compile errors:\n  " + "\n  ".join(self.problems))


SpecError.__module__ = "kernel.spec"


class Param:
    """One spec param: typed, optionally required/choices-bounded.

    ``fp`` controls the §3.4 params component: ``None`` = auto (True unless
    the name is a selector knob), explicit True/False pins it. ``fp=True``
    on a selector knob is a compile error — selector churn must never
    poison fingerprints.
    """

    def __init__(
        self,
        type=str,  # noqa: A002 -- 公开 kwarg：Param(type=int)
        default=None,
        required: bool = False,
        choices=None,
        fp=None,
    ):
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
                ) from None
        if not isinstance(v, self.type):
            raise SpecError([f"param {name!r}: {v!r} is not a {self.type.__name__}"])
        if self.choices is not None and v not in self.choices:
            raise SpecError([f"param {name!r}: {v!r} not in choices {self.choices}"])
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


Param.__module__ = "kernel.spec"


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
            SHOULD — §3.1's mandatory review point). The SC_* presets
            cover the recurring fn-verdict alphabets; a unique alphabet
            stays an inline literal.
    dedup_key None (asset default (idc,arm,variant)) | callable
            cell->(idc,arm,variant) | tuple of cell-field names.
    eval    stage's terminal rows also land in the eval_records lane
            (judge/score stages inside a mixed spec; spec.eval marks the
            whole run).
    """

    def __init__(
        self,
        name,
        fn,
        needs=None,
        paid: bool = False,
        executor=None,
        cost_hook=None,
        mutates=None,
        on=None,
        status_class=None,
        dedup_key=None,
        eval: bool = False,  # noqa: A002 -- 公开 kwarg：Stage(eval=True)
    ):
        self.name = str(name)
        self.fn = fn
        self.needs = [_norm_need(n) for n in (needs or [])]
        self.paid = bool(paid)
        self.executor = executor
        self.cost_hook = cost_hook
        self.mutates = [str(m) for m in (mutates or [])]
        self.on = {str(k): frozenset(v) for k, v in (on or {}).items()}
        self.status_class = (
            dict(status_class) if status_class else dict(DEFAULT_STATUS_CLASS)
        )
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
        fnref = (
            f"{getattr(fn, '__module__', '')}.{getattr(fn, '__qualname__', repr(fn))}"
        )
        return {
            "name": self.name,
            "fn": fnref,
            "needs": [{"stage": s, "accept": sorted(a)} for s, a in self.needs],
            "paid": self.paid,
            "executor": self.executor,
            "cost_hook": getattr(self.cost_hook, "__qualname__", None)
            if self.cost_hook
            else None,
            "mutates": list(self.mutates),
            "on": {k: sorted(v) for k, v in self.on.items()},
            "status_class": self.status_class,
            "eval": self.eval,
            "dedup_key": (
                None
                if self.dedup_key is None
                else list(self.dedup_key)
                if isinstance(self.dedup_key, (list, tuple))
                else getattr(self.dedup_key, "__qualname__", repr(self.dedup_key))
            ),
        }


Stage.__module__ = "kernel.spec"


class Spec:
    """The bench definition — one per spec file."""

    def __init__(
        self,
        kind,
        params=None,
        stages=None,
        items=None,
        freeze_plan: bool = True,
        executor: str = "thread",
        env_probes=None,
        code_deps=None,
        foreign_runs=None,
        allowed_layers=None,
        lake: bool = False,
        same_id_serial: bool = True,
        dedup_key=None,
        eval: bool = False,  # noqa: A002 -- 公开 kwarg：Spec(eval=True)
        gateway_factory=None,
        select=None,
        fetch_fn=None,
        prefetch: bool = True,
        lake_source: str = "arxiv",
    ):
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
        # ``fetch_fn(idc, stage_dir) -> dict|None`` — the spec-declared
        # corpus hydrator (§3.10.3): populate ``{stage}/extracted/``
        # (payload) and optionally ``{stage}/raw/``; the returned dict
        # merges into the cell's meta.json. Wired into lake.hydrate by
        # ctx.lake_ensure and by the run-internal lookahead prefetcher —
        # stage fns never write their own fetchers.
        self.fetch_fn = fetch_fn
        # ``prefetch`` gates the lookahead thread (32 cells / 512 MiB
        # window ahead of the execution frontier — §3.10.3 预取双机制;
        # the t=0 burst IS the plan-time batch warm-up). Only runs when
        # ``lake`` is set. False = hydrate strictly on ctx.lake_ensure
        # demand (cold-miss instruments).
        self.prefetch = bool(prefetch)
        # Corpus-source dim for lake cell dirs (§3.10.3
        # lake/corpus/{source}/{safe_id}) — sw/iclr layers declare their own.
        self.lake_source = str(lake_source)
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
        return [norm_item(it) for it in self.materialize_items()]

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
                None
                if self.dedup_key is None
                else list(self.dedup_key)
                if isinstance(self.dedup_key, (list, tuple))
                else getattr(self.dedup_key, "__qualname__", repr(self.dedup_key))
            ),
            "eval": self.eval,
            "select": (
                None
                if self.select is None
                else getattr(self.select, "__qualname__", repr(self.select))
            ),
            "fetch_fn": (
                None
                if self.fetch_fn is None
                else getattr(self.fetch_fn, "__qualname__", repr(self.fetch_fn))
            ),
            "prefetch": self.prefetch,
            "lake_source": self.lake_source,
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
            return (
                str(cell.get("idc")),
                str(cell.get("arm", "-")),
                str(cell.get("variant", "-")),
            )
        if callable(key):
            out = key(cell)
            idc, arm, variant = ([*list(out), "-", "-"])[:3]
            return str(idc), str(arm), str(variant)
        fields = list(key)
        vals = [str(cell.get(f, "-")) for f in fields[:3]]
        while len(vals) < 3:
            vals.append("-")
        return tuple(vals)


Spec.__module__ = "kernel.spec"


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
