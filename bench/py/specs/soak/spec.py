"""soak spec 组合根——Spec(...) 构建 + 其直接依赖闭包（stage fn 全走叶直引）。"""

from __future__ import annotations

from kernel.spec import SC_SPECTRUM_UP, Param, Spec, Stage

from specs import _benchlite as benchlib
from specs._shared import DEFAULT_MODEL, devin_factory
from specs.soak.compile import _compile
from specs.soak.fixloop import _fixloop
from specs.soak.ingest import _ingest
from specs.soak.items import _items, _select
from specs.soak.parse import _parse
from specs.soak.xlat import _xlat

# ---------------------------------------------------------------- spec

spec = Spec(
    kind="soak",
    params={
        "n": Param(int, default=0),
        "seed": Param(int, default=42),
        "ids": Param(str, default="", fp=False),
        "layers": Param(str, default="core", fp=False),
        "only": Param(str, default="", fp=False),
        "on": Param(
            str,
            default="fail",
            choices=["fail", "nonclean", "misschar", "clean", "all"],
            fp=False,
        ),
        "engine": Param(
            str,
            default="xelatex",
            choices=["auto", "xelatex", "tectonic"],
            fp=True,
        ),
        "concurrency": Param(int, default=10, fp=True),
        "max_tries": Param(int, default=5, fp=True),
        "timeout": Param(float, default=240.0, fp=True),
        "oversize_cap": Param(int, default=benchlib.MAX_TOTAL_CHARS, fp=True),
        "model": Param(str, default=DEFAULT_MODEL, fp=True),
        "llm": Param(bool, default=False, fp=True),
        "marks": Param(bool, default=True, fp=True),
        "no_probe": Param(bool, default=False, fp=False),
        "resid_sweep": Param(bool, default=False, fp=True),
    },
    items=_items,
    select=_select,
    freeze_plan=True,
    executor="thread",
    env_probes=["xelatex", "tlmgr", "tectonic"],
    code_deps=[
        "bench/py/specs/soak/compile.py",
        "bench/py/specs/soak/fixloop.py",
        "bench/py/specs/soak/ingest.py",
        "bench/py/specs/soak/items.py",
        "bench/py/specs/soak/parse.py",
        "bench/py/specs/soak/spec.py",
        "bench/py/specs/soak/xlat.py",
        "src/texlate/compile",
        "src/texlate/latex",
        "src/texlate/textutil",
        "src/texlate/xlat",
        "src/texlate/pipecore.py",
        "src/texlate/validate",
    ],
    lake=True,
    prefetch=True,
    fetch_fn=None,
    lake_source="arxiv",
    same_id_serial=True,
    dedup_key=("idc", "arm", "variant"),
    gateway_factory=devin_factory(nslots=64),
    stages=[
        Stage(
            "ingest",
            _ingest,
            # 唯一字母表（ok/reject + 双 retriable）——不为单点造预设。
            status_class={
                "ok": "terminal",
                "reject": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
        Stage(
            "parse",
            _parse,
            needs=[("ingest", {"ok"})],
            mutates=["zh"],
            # 唯一字母表（ok/reject + upskip）——不为单点造预设。
            status_class={
                "ok": "terminal",
                "reject": "terminal",
                "skip": "upstream",
                "error": "retriable",
            },
        ),
        Stage(
            "xlat",
            _xlat,
            needs=[("parse", {"ok"})],
            paid=True,
            mutates=["zh", "state"],
            dedup_key=("idc", "arm", "variant"),
            # 唯一字母表（ok/partial/fail/reject + upskip）——不为单点造预设。
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "skip": "upstream",
                "error": "retriable",
            },
        ),
        Stage(
            "compile",
            _compile,
            needs=[("xlat", {"ok", "partial"})],
            mutates=["splice"],
            status_class=SC_SPECTRUM_UP,
        ),
        Stage(
            "fixloop",
            _fixloop,
            needs=[("compile", {"clean", "partial"})],
            # reject 也必须送 fn 落 ok+ran=False 终态——needs-skip 会把
            # 付费 zh/state 字节滞留 work/ 等 sweep（_ON_PRED 全排
            # reject，进 fn 即走无修必要短路）。
            on={"compile": {"fail", "dirty_pdf", "reject"}},
            paid=True,
            mutates=["splice"],
            dedup_key=("idc", "arm", "variant"),
            status_class=SC_SPECTRUM_UP,
        ),
    ],
)
