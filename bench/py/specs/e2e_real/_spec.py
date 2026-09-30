"""e2e_real._spec 组合根——Spec(...) 构建 + 其直接依赖闭包（stage fn 全走叶直引）。

叶干名 ``_spec`` 非 ``spec``：stem 撞导出名 ``spec`` 时叶件 import 会把
子模块绑上门面遮蔽惰性属性（verbs.dossier._main 同例）。"""

from __future__ import annotations

from kernel.spec import SC_OK_REJECT, SC_SPECTRUM_UP, Param, Spec, Stage

from specs import _benchlite as benchlib
from specs._shared import DEFAULT_MODEL, devin_factory
from specs.e2e_real.base import _base
from specs.e2e_real.compile import _compile
from specs.e2e_real.fixloop import _fixloop
from specs.e2e_real.frame import _items, _select
from specs.e2e_real.layoutqc import _layoutqc
from specs.e2e_real.route import _route
from specs.e2e_real.xlat import _xlat

# ---------------------------------------------------------------- spec

spec = Spec(
    kind="e2e_real",
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
        # \pdfsavepos 版面真值注入（compile/marks.py）——bench 默认开，
        # 开销 <1%；zh 臂走 prepare_chinese kwarg，en 臂走 _base 直注
        "marks": Param(bool, default=True, fp=True),
        # 保护区体残英清扫（xlat.resid）——真臂无 seg-cache，span 不缓存
        "resid_sweep": Param(bool, default=False, fp=True),
    },
    items=_items,
    select=_select,
    freeze_plan=True,
    executor="thread",
    env_probes=["xelatex", "tlmgr", "pdftotext"],
    code_deps=[
        "bench/py/specs/e2e_real/base.py",
        "bench/py/specs/e2e_real/compile.py",
        "bench/py/specs/e2e_real/fixloop.py",
        "bench/py/specs/e2e_real/frame.py",
        "bench/py/specs/e2e_real/layoutqc.py",
        "bench/py/specs/e2e_real/route.py",
        "bench/py/specs/e2e_real/_spec.py",
        "bench/py/specs/e2e_real/xlat.py",
        "src/texlate/compile",
        "src/texlate/latex",
        "src/texlate/textutil",
        "src/texlate/xlat",
        "src/texlate/pipecore.py",
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
        Stage(
            "route",
            _route,
            status_class=SC_OK_REJECT,
        ),
        Stage(
            "xlat",
            _xlat,
            needs=[("route", {"ok"})],
            paid=True,
            mutates=["zh", "state"],
            dedup_key=("idc", "arm", "variant"),
            # 唯一字母表（ok/partial/fail/reject + 双 retriable）——无第二处
            # 同款，不为单点造预设。
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
            # needs-free 收割汇：on 只给 topo 边（compile→fixloop 排
            # 序），不给闸——末段 mutates 格恒跑恒 DONE，任何上游死法
            # 都能落 fn 内 decline→reject→harvest。soak 的
            # needs+on 双写在 compile=reject 时 needs-skip，付费
            # zh.-/state.- 滞留 work/（本 spec 不复制该洞）。
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
            # needs-free 末段汇：on 双 topo 边钉死「fixloop ∧ base 之后」，
            # 任何上游死法都照跑（fn 内按产物在否降级）。mutates 使本格
            # 成为 last_mutating_stage → harvest 触发点从 fixloop 移此，
            # splice/zh/state 内容不变、多封 qc.json+txlm 质检包。
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
            # 唯一字母表（clean/ok/reject + upskip）——不为单点造预设。
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
