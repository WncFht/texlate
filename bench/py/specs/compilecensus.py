r"""compilecensus — 原文直编大普查（compilebench 兄弟 spec）。

回答「缺件（``missing_file``）现状」：大样本分层抽样 × baseline 臂 ×
xelatex 单引擎裸编译，把全语料缺件面一次性量出来。与 compilebench
的差异三面：

- **帧**：非偏 manifest 并集（dev_failmine 刻意不入——fail 富集卷进
  现况分母即失真）∩ 湖可供应格，SAMPLE_N=5000，SEED 独立。
- **网格**：``(baseline,) × (xelatex,)`` 单格/篇——普查要的是「原文
  缺不缺件」一维，zh 臂/tectonic 第二引擎对现况问题是噪音格。
- **届**：``EPOCH`` 日期戳折进 variant——与 compilebench ``v1`` 代
  互不命中，不借 dedup 也不污染其基线分母。

stage fn/select/抽样全复用 compilebench 叶（``_cb_compile`` 单格实现、
``_pool/_sample/_grid`` 参数化、``_select`` 收窄面），不重抄。
"""

from __future__ import annotations

from kernel.spec import Param, Spec, Stage

import specs.compilebench as cb
from specs import _bootstrap

_bootstrap.ensure()

#: 普查帧 manifest 面——非偏层全收（holdout 由 EVAL_LAYERS 滤、
#: dev_failmine 由名单剔除）。
MANIFESTS = (
    "manifest.jsonl",
    "manifest_v1.jsonl",
    "manifest_v2.jsonl",
    "manifest_hot.jsonl",
    "manifest_booster.jsonl",
    "manifest_iclr.jsonl",
    "manifest_dev_vol.jsonl",
    "manifest_dev_recent.jsonl",
    "manifest_expand.jsonl",
    "manifest_m1k-v3.jsonl",
    "manifest_m1k-iclr.jsonl",
    "manifest_m1k-axhot.jsonl",
    "manifest_m1k-recent.jsonl",
)

#: 抽样定义——本 spec 帧本体（fp 经 variant epoch 承载，非 run 参数）。
SAMPLE_N = 5000
SEED = 20261002

#: 测量届别——日期戳（vN 编号只留顺序语义处）。
EPOCH = "2026-10"

#: 普查网格——baseline 原文直编 × xelatex，一篇一格。
CONDS = ("baseline",)
ENGINES = ("xelatex",)


def _items() -> list[dict]:
    picked = cb._sample(cb._pool(MANIFESTS), SAMPLE_N, SEED)
    # select 的 ``n=`` 谓词读 compilebench._PIDS（sample 定序前切）——
    # 本 spec 的样本序即本普查帧序，直接覆写该共享面。
    cb._PIDS = [p["id"] for p in picked]
    return cb._grid(picked, CONDS, ENGINES, EPOCH, SEED, SAMPLE_N)


spec = Spec(
    kind="compilecensus",
    params={
        "condition": Param(default="baseline", fp=False),
        "engines": Param(default="xelatex", fp=False),
        "ids": Param(default="", fp=False),
        "only": Param(default="", fp=False),
        "n": Param(type=int, default=0, fp=False),
    },
    items=_items,
    select=cb._select,
    stages=[
        Stage(
            "cb_compile",
            cb._cb_compile,
            eval=True,
            status_class={
                "ok": "terminal",
                "clean": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "fault": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
    ],
    lake=True,
    eval=False,
    same_id_serial=True,
    executor="thread",
    env_probes=["xelatex", "pdftotext"],
    code_deps=[
        "bench/py/specs/compilecensus.py",
        "bench/py/specs/compilebench.py",
        "src/texlate/compile",
        "src/texlate/latex",
    ],
)
