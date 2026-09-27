"""smoke — the validation spec: three free stages over synthetic items.

No lake, no paid gate, no network — the spec that proves a checkout can
run the kernel end to end::

    bench run bench/py/specs/smoke.py        # or: bench run smoke

Pipeline per item: ``ingest`` writes ``work/{id}/src/main.tex`` from an
inline fixture; ``transform`` uppercases it to ``work/{id}/zh/out.txt``
(needs ingest -> ok); ``report`` emits a metrics row (needs transform ->
ok, mutates nothing).
"""

from kernel.spec import Param, Spec, Stage

# Canon-clean synthetic ids (9901 = January 2099 — collides with nothing
# real). Item tuple shape: (id, arm, up, variant) per §4.
_ITEMS = (
    ("9901.00001", "a", "-", "-"),
    ("9901.00002", "a", "-", "-"),
    ("9901.00003", "a", "-", "-"),
)


class _Items:
    """Dual-protocol item source: iterates like a tuple AND is callable as
    ``items(params)`` — whichever convention kernel.kernel settles on."""

    def __iter__(self):
        return iter(_ITEMS)

    def __call__(self, *args, **kwargs):
        return iter(_ITEMS)


_TEX_FIXTURE = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\section{Smoke}\n"
    "Hello bench kernel — this fixture never leaves the run work dir.\n"
    "\\end{document}\n"
)


def _ingest(ctx):
    """Materialize the 'paper source' under the cell work dir."""
    src = ctx.workspace() / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "main.tex").write_text(_TEX_FIXTURE, encoding="utf-8")
    return "ok"


def _transform(ctx):
    """Uppercase the source into a stand-in 'zh' product."""
    ws = ctx.workspace()
    text = (ws / "src" / "main.tex").read_text(encoding="utf-8")
    out = ws / "zh"
    out.mkdir(parents=True, exist_ok=True)
    (out / "out.txt").write_text(text.upper(), encoding="utf-8")
    return "ok"


def _report(ctx):
    """Emit one metrics row; mutates=[] — report writes go through emit."""
    text = (ctx.workspace() / "zh" / "out.txt").read_text(encoding="utf-8")
    ctx.emit(
        {
            "stage": "report",
            "metric": "smoke_chars",
            "chars": len(text),
            "lines": text.count("\n"),
        }
    )
    return "ok"


spec = Spec(
    kind="smoke",
    params={
        "note": Param(type=str, default=""),  # free-form tag, optional
    },
    items=_Items(),
    stages=[
        Stage("ingest", _ingest),
        Stage("transform", _transform, needs=[("ingest", {"ok"})]),
        Stage(
            "report",
            _report,
            needs=[("transform", {"ok"})],
            mutates=[],
        ),
    ],
    lake=False,
)
