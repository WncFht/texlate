"""corpus_sw._spec 组合根——Spec(...) 构建 + 其直接依赖闭包（stage fn 全走叶直引）。

叶干名 ``_spec`` 非 ``spec``：stem 撞导出名 ``spec`` 时叶件 import 会把
子模块绑上门面遮蔽惰性属性（verbs.dossier._main 同例）。"""

from __future__ import annotations

from kernel.spec import Param, Spec, Stage

from specs.corpus_sw.plan import _assign, _footers, _pool
from specs.corpus_sw.rehydrate import _rehydrate, _report

spec = Spec(
    kind="corpus_sw",
    # eval=True：item id 非 canon（"corpus-sw" 是 builder 单元不是 arxiv id）
    # ——非 eval spec 会过 canon_id 把它当 invalid 丢掉。
    eval=True,
    items=[{"id": "corpus-sw"}],
    params={
        "n_sw": Param(type=int, default=1200),
        "n_ep_holdout": Param(type=int, default=300),
        "n_ep_devrecent": Param(type=int, default=300),
        "min_yymm": Param(type=str, default="2501"),
        "seed": Param(type=int, default=42),
        # 试运行闸（fp=False：限流旋钮不进指纹）
        "limit": Param(type=int, default=0, fp=False),
        "shards": Param(type=str, default="", fp=False),
        "rg_limit": Param(type=int, default=0, fp=False),
    },
    stages=[
        Stage(
            "footers", _footers, status_class={"ok": "terminal", "error": "retriable"}
        ),
        Stage(
            "pool",
            _pool,
            needs=[("footers", {"ok"})],
            status_class={"ok": "terminal", "error": "retriable"},
        ),
        Stage(
            "assign",
            _assign,
            needs=[("pool", {"ok"})],
            status_class={"ok": "terminal", "error": "retriable"},
        ),
        Stage(
            "rehydrate",
            _rehydrate,
            needs=[("assign", {"ok"})],
            status_class={"ok": "terminal", "error": "retriable"},
        ),
        # needs 闸只认 DONE 行（_needs_eval statuses=STATUS_DONE）——
        # retriable error 永远喂不饱 accept，故 report 只接 ok；部分失败的
        # 面由 rehydrate 自己的 error+metrics 背，下轮 run 续跑收敛后
        # report 自然放行。
        Stage(
            "report",
            _report,
            needs=[("rehydrate", {"ok"})],
            status_class={"ok": "terminal", "error": "retriable"},
        ),
    ],
    lake=True,
    prefetch=False,  # builder 段内自管 hydrate——预取器对本 spec 无的放矢
    lake_source="arxiv",
    code_deps=[
        "bench/py/specs/_corpus_common/__init__.py",
        "bench/py/specs/_corpus_common/features.py",
        "bench/py/specs/_corpus_common/frame.py",
        "bench/py/specs/_corpus_common/io.py",
        "bench/py/specs/_corpus_common/materialize.py",
        "bench/py/specs/_corpus_common/net.py",
        "bench/py/specs/_corpus_common/scan.py",
        "bench/py/specs/_corpus_common/select.py",
        "bench/py/specs/corpus_sw/base.py",
        "bench/py/specs/corpus_sw/manifest.py",
        "bench/py/specs/corpus_sw/plan.py",
        "bench/py/specs/corpus_sw/rehydrate.py",
        "bench/py/specs/corpus_sw/_spec.py",
        "bench/py/specs/corpus_sw/worker.py",
    ],
)
