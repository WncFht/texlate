"""e2e_eval_cs —— e2e_eval 的 CS 专项兄弟 spec：holdout 新 CS 冻帧。

与 e2e_eval 同一条 stage 链、同一个 eval=True 闸，差异只在帧与世代：

- **帧**：``bench/nominations/e2e_eval_cs.jsonl``——holdout 层新 CS 池
  （``e_2021_25|cs`` 213 篇 + ``holdout|recent`` 中 cat_group=cs 123 篇，
  ∩ 湖可供应格 336）分层等比抽 200 冻帧（seed=20261002：e-era 127 +
  recent 73）。回答 holdout-200 帧答不了的「新 CS 论文表现」——通用帧
  内 e_2021_25|cs 仅 14 篇。
- **EPOCH 换代**：``2026-10-cs``——与 e2e_eval ``2026-10`` 代互不命中：
  两帧有交叠篇目，dedup 不借账，本帧是独立测量届。
"""

from __future__ import annotations

from pathlib import Path

from kernel.spec import SC_OK_REJECT, SC_SPECTRUM_UP, Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs._shared import DEFAULT_MODEL, devin_factory
from specs.e2e_real.base import _base
from specs.e2e_real.compile import _compile
from specs.e2e_real.fixloop_stage import _fixloop
from specs.e2e_real.frame import _frame_sha_of, _items_of, _select
from specs.e2e_real.layoutqc import _layoutqc
from specs.e2e_real.route import _route
from specs.e2e_real.xlat import _xlat

ROOT = Path(__file__).resolve().parents[3]

#: 冻结评测帧——holdout 新 CS 冻样工件。
FRAME = ROOT / "bench" / "nominations" / "e2e_eval_cs.jsonl"

#: 测量世代——日期戳+帧名后缀（与 e2e_eval "2026-10" 代隔开）。
EPOCH = "2026-10-cs"

#: 付费臂名——与 e2e_real 同臂族；键域区分靠 variant。
ARM = "real"


def _items() -> list[dict]:
    return _items_of(FRAME, ARM, EPOCH)


def _frame_sha() -> str:
    return _frame_sha_of(FRAME)


spec = Spec(
    kind="e2e_eval_cs",
    eval=True,
    params={
        "ids": Param(str, default="", fp=False),
        "only": Param(str, default="", fp=False),
        "model": Param(str, default=DEFAULT_MODEL, fp=True),
        "concurrency": Param(int, default=10, fp=True),
        "max_tries": Param(int, default=5, fp=True),
        "timeout": Param(float, default=240.0, fp=True),
        "oversize_cap": Param(int, default=benchlib.MAX_TOTAL_CHARS, fp=True),
        "base": Param(
            str, default="onfail", choices=["always", "onfail", "never"], fp=True
        ),
        "fixloop": Param(
            str, default="onfail", choices=["always", "onfail", "never"], fp=True
        ),
        "no_probe": Param(bool, default=False, fp=False),
        "marks": Param(bool, default=True, fp=True),
        "resid_sweep": Param(bool, default=False, fp=True),
        "frame_sha": Param(str, default=_frame_sha(), fp=False),
    },
    items=_items,
    select=_select,
    freeze_plan=True,
    executor="thread",
    env_probes=["xelatex", "tlmgr", "pdftotext"],
    code_deps=[
        "bench/py/specs/e2e_eval_cs.py",
        "bench/py/specs/e2e_real/base.py",
        "bench/py/specs/e2e_real/compile.py",
        "bench/py/specs/e2e_real/fixloop_stage.py",
        "bench/py/specs/e2e_real/frame.py",
        "bench/py/specs/e2e_real/layoutqc.py",
        "bench/py/specs/e2e_real/route.py",
        "bench/py/specs/e2e_real/_spec.py",
        "bench/py/specs/e2e_real/xlat.py",
        "src/texlate/compile",
        "src/texlate/latex",
        "src/texlate/textutil",
        "src/texlate/xlat",
        "src/texlate/pipecore",
        "src/texlate/validate",
        "src/texlate/e2e.py",
    ],
    lake=True,
    prefetch=True,
    fetch_fn=None,
    lake_source="arxiv",
    same_id_serial=True,
    dedup_key=("idc", "arm", "variant"),
    gateway_factory=devin_factory(),
    stages=[
        Stage("route", _route, status_class=SC_OK_REJECT),
        Stage(
            "xlat",
            _xlat,
            needs=[("route", {"ok"})],
            paid=True,
            mutates=["zh", "state"],
            dedup_key=("idc", "arm", "variant"),
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "skip": "retriable",
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
            on={
                "compile": {"clean", "partial", "fail", "reject", "dirty_pdf"},
            },
            mutates=["splice"],
            status_class=SC_SPECTRUM_UP,
        ),
        Stage(
            "base",
            _base,
            needs=[("route", {"ok", "reject"})],
            status_class=SC_SPECTRUM_UP,
        ),
        Stage(
            "layoutqc",
            _layoutqc,
            on={
                "fixloop": {
                    "clean",
                    "ok",
                    "partial",
                    "fail",
                    "reject",
                    "dirty_pdf",
                    "skip",
                    "error",
                },
                "base": {
                    "clean",
                    "ok",
                    "partial",
                    "fail",
                    "reject",
                    "dirty_pdf",
                    "skip",
                    "error",
                },
            },
            mutates=["layoutqc"],
            status_class={
                "clean": "terminal",
                "ok": "terminal",
                "reject": "terminal",
                "skip": "upstream",
                "error": "retriable",
            },
        ),
    ],
)
