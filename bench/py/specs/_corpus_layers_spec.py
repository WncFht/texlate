"""specs._corpus_layers_spec — corpus_layers spec 组合根（_select + Spec 装配）。

bulk 链 plan→scan→extract→qc + recent 正交臂（needs=[]）声明在 qc 前；
code_deps 保留 ``_corpus_common*`` 8 条原 dep + 本 spec 全部叶。
"""

from __future__ import annotations

from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs._corpus_layers_base import LAYER_NAMES
from specs._corpus_layers_extract import _extract
from specs._corpus_layers_plan import _plan
from specs._corpus_layers_qc import _qc
from specs._corpus_layers_recent import _recent
from specs._corpus_layers_scan import _scan

# ---------------------------------------------------------------- items/select


def _select(item: dict, rp: dict) -> bool:
    """``layers`` run 参数（逗号分隔层名）——缺省全层。"""
    wanted = {s.strip() for s in str(rp.get("layers") or "").split(",") if s.strip()}
    return not wanted or str(item.get("id")) in wanted


spec = Spec(
    kind="corpus_layers",
    items=[{"id": n, "params": {"layer": n}} for n in LAYER_NAMES],
    params={
        "workdir": Param(type=str, default=str(cc.BUILD_ROOT / "layers"), fp=False),
        "build_root": Param(type=str, default=str(cc.BUILD_ROOT), fp=False),
        "corpus_dir": Param(type=str, default=str(cc.CORPUS), fp=False),
        "frame_dir": Param(type=str, default=str(cc.FRAME), fp=False),
        "v3_workdir": Param(type=str, default=str(cc.BUILD_ROOT / "v3"), fp=False),
        "layers": Param(type=str, default=",".join(LAYER_NAMES), fp=False),
        "layer": Param(type=str, default="", fp=False),
        "rates_source": Param(type=str, default="", fp=False),
        "bias": Param(type=float, default=1.0),
        "target": Param(type=int, default=0),
        "ids_file": Param(type=str, default="", fp=False),
        "limit": Param(type=int, default=0, fp=False),
        "recent_limit": Param(type=int, default=85, fp=False),
        "day_budget": Param(type=int, default=180, fp=False),
        "jobs": Param(type=int, default=4, fp=False),
        "topup": Param(type=bool, default=False, fp=False),
    },
    stages=[
        Stage(
            "plan",
            _plan,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
        Stage(
            "scan",
            _scan,
            needs=[("plan", {"ok"})],
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "error": "retriable",
            },
        ),
        Stage(
            "extract",
            _extract,
            needs=[("scan", {"ok", "partial"})],
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
        Stage(
            "recent",
            _recent,
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
        Stage(
            "qc",
            _qc,
            needs=[("extract", {"ok", "partial"})],
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
    ],
    select=_select,
    code_deps=[
        "bench/py/specs/_corpus_common.py",
        "bench/py/specs/_corpus_common_features.py",
        "bench/py/specs/_corpus_common_frame.py",
        "bench/py/specs/_corpus_common_io.py",
        "bench/py/specs/_corpus_common_materialize.py",
        "bench/py/specs/_corpus_common_net.py",
        "bench/py/specs/_corpus_common_scan.py",
        "bench/py/specs/_corpus_common_select.py",
        "bench/py/specs/_corpus_layers_base.py",
        "bench/py/specs/_corpus_layers_extract.py",
        "bench/py/specs/_corpus_layers_plan.py",
        "bench/py/specs/_corpus_layers_qc.py",
        "bench/py/specs/_corpus_layers_recent.py",
        "bench/py/specs/_corpus_layers_scan.py",
        "bench/py/specs/_corpus_layers_spec.py",
        "src/texlate/arxiv",
    ],
)
