"""paid_stub — the paid-path spec with an injectable gateway factory.

Proves the whole §3.6 paid gate with zero real spend: the ``xlat`` stage
is ``paid=True`` and declares ``dedup_key=('idc','arm','variant')`` — the
dedup-key declaration is mandatory for paid stages (compile_checks
enforces it).

The stage calls ``ctx.gateway().request('chat', ...)``. ``ctx.gateway()``
is lazy — constructing the client IS the paid assertion (claim + paid
slot + PAUSE/AUTH_DEAD checks all happen before the first request). The
factory itself is injected by the caller:

- ``kernel.run(..., gateway_factory=...)`` in tests injects a fake whose
  ``request()`` returns ``{"usage": {"out_tok": 150}}`` — the full
  claim/slot/cost-meter path runs with no network.
- Real specs inject the texlate gateway client factory
  (devin-2api / swe-2-medium) the same way; nothing in this file knows
  the difference.

``--max-cost`` is required for paid runs — the kernel refuses a paid
spec without a budget fuse (§3.6), and ``--detach`` forces it at the CLI
preflight.
"""

from kernel.spec import Param, Spec, Stage

_ITEMS = (
    ("9901.00001", "a", "-", "-"),
    ("9901.00002", "a", "-", "-"),
)


class _Items:
    """Dual-protocol item source (iterable AND callable)."""

    def __iter__(self):
        return iter(_ITEMS)

    def __call__(self, *args, **kwargs):
        return iter(_ITEMS)


def _ingest(ctx):
    """Materialize the source stub into the 'state' mutates-kind — the
    durable inter-stage channel. workspace() is per-run scratch: a cell
    regenerating under a NEW run (regen/resume) finds it empty, while a
    harvested mutates-kind is vault-restorable forever."""
    out = ctx.asset_dir("state")
    (out / "main.tex").write_text(
        "\\section{PaidStub}\npaid translation stub input\n",
        encoding="utf-8",
    )
    return "ok"


def _xlat(ctx):
    """The paid cell: gateway() construction is the paid assertion.

    Reads upstream 'state' via upstream_asset_dir, restoring from the
    vault when this run's work tree lacks it (regen/resume under a fresh
    work dir — the upstream cell dedups, its bytes live in the vault).
    Writes into asset_dir('zh') — a mutates-kind dir — so the terminal
    harvest secures the paid bytes into the vault (§3.5: paid output
    that never reaches the vault is unrecoverable spend)."""
    from kernel import vault

    state = ctx.upstream_asset_dir("state")
    if state is None:
        vault.restore(ctx.idc, ctx.arm, ctx.variant, ctx.paper_dir())
        state = ctx.upstream_asset_dir("state")
    src = (state / "main.tex").read_text(encoding="utf-8")
    gw = ctx.gateway()
    res = gw.request(
        "chat",
        model="paid-stub",
        messages=[{"role": "user", "content": src}],
    )
    out = ctx.asset_dir("zh")
    out.mkdir(parents=True, exist_ok=True)
    (out / "out.txt").write_text(src.upper(), encoding="utf-8")
    usage = res.get("usage", {}) if isinstance(res, dict) else {}
    ctx.emit(
        {
            "stage": "xlat",
            "metric": "paid_stub_tokens",
            "out_tok": usage.get("out_tok", 0),
        }
    )
    return "ok"


def _report(ctx):
    """Metrics row over the paid product; mutates nothing.

    Reads via upstream_asset_dir — the zh tree was vault-fused (0444)
    at xlat harvest, so the write-probed asset_dir accessor would
    refuse it."""
    zh = ctx.upstream_asset_dir("zh")
    if zh is None:
        return {"status": "error", "errors": [{"code": "no_zh_asset"}]}
    text = (zh / "out.txt").read_text(encoding="utf-8")
    ctx.emit({"stage": "report", "metric": "paid_stub_chars", "chars": len(text)})
    return "ok"


spec = Spec(
    kind="paid_stub",
    params={
        "note": Param(type=str, default=""),
    },
    items=_Items(),
    stages=[
        Stage("ingest", _ingest, mutates=["state"]),
        Stage(
            "xlat",
            _xlat,
            needs=[("ingest", {"ok"})],
            paid=True,
            mutates=["zh"],
            dedup_key=("idc", "arm", "variant"),
        ),
        Stage(
            "report",
            _report,
            needs=[("xlat", {"ok"})],
            mutates=[],
        ),
    ],
    lake=False,
)
