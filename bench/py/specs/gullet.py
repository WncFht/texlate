r"""gullet — corpus 宏展开抽干评测器（``gullet_bench.py`` 的 Spec v2 移植）。

对 ``manifest.jsonl`` 框架内每篇的湖格跑 ``Gullet.expand_all`` 回压式
宏展开全程 + token 级不动点重喂验证。纯本地测量面：不改产物字节、
零网络零付费、**零湖写**——``is_complete`` 闸在前，``src_path``
永不触发水化。

    bench run gullet                          # 全量 1000 行框架
    bench plan gullet n=60                    # 抽样报价
    bench run gullet ids=astro-ph/0111038     # 直选
    bench run gullet n=60 seed=7 --slug foo   # 换 seed 子集

逐格口径移植自 ``gullet_bench.run_doc``：``locate`` → ``decode_tex`` →
``Measured.expand_all``（ArgMismatch 回吐 / ``\if`` 可求值 vs 界标两档
/ 选中支分布 / warnings 按 kind）→ fresh ``Measured`` 整列重喂逐枚
``_tok_eq`` 不动点比对。

- **EPOCH**：forever-dedup 下「重测一代」的杠杆——模块常量折进
  ``variant``，换代=改 ``EPOCH``（``code_deps`` 驱动的 fp stale 只
  标记不重跑，评测器换代的唯一结构杠杆）。
- **fp 只进 metrics 永不进 status**——``refeed_err``/``len N->M``/
  ``tok@k`` 是测量发现不是失败：旧 ``fixpoint_bad⊂ok`` 分母口径原样
  保留，映成非 ok 会改掉 ok 分母。
- **err 行=终态**：locate/decode 异常 → ``fail``+errors cat=
  ``locate_decode``；expand 异常 → ``fail``+``expand_crash``（带部分
  ms）——旧「err 行即 done 永不重试」的终态等价物。域外异常逃逸到
  kernel ``error``（retriable，resume 重跑——有意的口径升级）。
- **湖格不完整 → skip(retriable)**：缺席/raw_only/skeleton 一律
  skip（旧口径这批格打 locate/decode err 落 done——对拍时此差集
  单列，不混入 fail 桶）。``prefetch=False`` 关 lookahead：测量 run
  不得有任何湖写副作用。
- 抽样口径=旧式 ``Random(seed).sample(manifest 文件序, n)``——
  ``_ITEMS`` 保文件序，``select`` 复现同序同 seed 子集（**不是**
  soak 的 sorted-pool 形）。
- ``summarize`` 不进城——聚合归 Wave-D 分析动词读 records 重建。
"""
from __future__ import annotations

import functools
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

# src/ 不在 `bench` 入口的 sys.path 上（kernel 惰性 import texlate.*）——
# specs/_sabotage.py 同款自举；TEXLATE_SRC 冻结快照语义一致。
sys.path.insert(
    0,
    os.environ.get(
        "TEXLATE_SRC", str(Path(__file__).resolve().parents[3] / "src")
    ),
)

import benchlib
from kernel import idnorm, lake
from kernel.spec import Param, Spec, Stage

from texlate.arxiv.locate import locate
from texlate.latex.gullet import ArgMismatch, Gullet, _tok_eq
from texlate.textutil import decode_tex

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "bench" / "corpus" / "manifest.jsonl"

#: 测量届别——折进 variant；想重测一代（引擎/gullet 变更后全量重跑）就
#: 改它，forever-dedup 按新 cell 键自然放行。
EPOCH = "v1"


class Measured(Gullet):
    """计数探针：ArgMismatch 回吐 / if 两档 / 选中支（逐方法面包面原样
    平移自 gullet_bench.Measured——回吐语义不变）。"""

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.n_arg_mismatch = 0
        self.n_if_marker = 0  # _eval_if → None（界标档，\ifX 本体交出）
        self.if_selected: list[bool | int] = []  # process_if 的 which

    def _invoke(self, t, r):
        try:
            return super()._invoke(t, r)
        except ArgMismatch:
            self.n_arg_mismatch += 1
            raise

    def _eval_if(self, name):
        r = super()._eval_if(name)
        if r is None:
            self.n_if_marker += 1
        return r

    def process_if(self, which, *, trig, tail_tag=""):
        self.if_selected.append(which)
        return super().process_if(which, trig=trig, tail_tag=tail_tag)


# ---------------------------------------------------------------- items/select


def _items() -> list[dict]:
    """manifest.jsonl 框架（1000 core 行，文件序即旧抽样底序）。"""
    items = []
    for row in benchlib.iter_jsonl(MANIFEST):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        items.append(
            {
                "id": str(row["id"]),
                "layer": row.get("layer"),
                "variant": EPOCH,
                "fp_input": row.get("main_tex_sha256")
                or row.get("blob_sha256"),
                "params": {"stratum": row.get("stratum_cell") or ""},
            }
        )
    return items


@functools.cache
def _canon(raw: str):
    return idnorm.canon_id(str(raw))


@functools.cache
def _sample_set(n: int, seed: int) -> frozenset:
    """旧抽样器原样：``Random(seed).sample(文件序 ids, min(n,len))``。"""
    ids = [it["id"] for it in _items()]
    return frozenset(random.Random(seed).sample(ids, min(n, len(ids))))


def _select(item: dict, rp: dict) -> bool:
    """G1 plan-filter：ids 直选（canon 双侧归一）→ only 子串 →
    n/seed 文件序抽样。"""
    ids_p = str(rp.get("ids") or "").strip()
    raw = str(item.get("id") or "")
    res = _canon(raw)
    idc = res.idc if res.ok and res.idc else raw
    if ids_p:
        want: set[str] = set()
        for tok0 in ids_p.split(","):
            tok = tok0.strip()
            if not tok:
                continue
            want.add(tok)
            r = _canon(tok)
            if r.ok and r.idc:
                want.add(r.idc)
        return raw in want or idc in want
    only = str(rp.get("only") or "").strip()
    if only:
        r = _canon(only)
        needle = r.idc if r.ok and r.idc else only
        if needle not in idc:
            return False
    n = int(rp.get("n") or 0)
    if n > 0:
        return raw in _sample_set(n, int(rp.get("seed") or 0))
    return True


# ---------------------------------------------------------------- stage: gexpand


def _gexpand(ctx) -> dict:
    """单文档展开全程 + 不动点重喂 → 测量行折进 terminal 事件。"""
    metrics: dict = {"stratum": ctx.params.get("stratum", "")}
    # 纯读闸：不完整湖格（absent/raw_only/skeleton）→ skip 等水化，
    # 永不触发 src_path 的自水合写径。
    if not lake.is_complete(ctx.idc):
        return {"status": "skip", "metrics": {**metrics, "reason": "lake_incomplete"}}
    ext = ctx.src_path()
    if ext is None:
        return {"status": "skip", "metrics": {**metrics, "reason": "no_src"}}

    # ---- 测量域 1: locate/decode（err → fail+locate_decode 终态） ----
    try:
        loc = locate(ext, arxiv_id=ctx.idc)
        main = ext / loc.main
        tex = decode_tex(main.read_bytes())
    except Exception as e:
        return {
            "status": "fail",
            "errors": [{"cat": "locate_decode", "msg": repr(e)[:400]}],
            "metrics": metrics,
        }
    metrics["bytes"] = len(tex)
    metrics["main"] = loc.main

    # ---- 测量域 2: expand（err → fail+expand_crash 终态，带部分 ms） ----
    g = Measured(tex, root_dir=str(ext))
    t0 = time.perf_counter()
    try:
        toks = g.expand_all()
    except Exception as e:
        metrics["ms"] = (time.perf_counter() - t0) * 1000
        return {
            "status": "fail",
            "errors": [{"cat": "expand_crash", "msg": repr(e)[:400]}],
            "metrics": metrics,
        }
    metrics["ms"] = (time.perf_counter() - t0) * 1000
    metrics["toks"] = len(toks)
    metrics["steps"] = g.steps
    metrics["n_inputs"] = len(g.file_texts)
    metrics["arg_mismatch"] = g.n_arg_mismatch
    metrics["if_marker"] = g.n_if_marker
    metrics["if_eval"] = len(g.if_selected)
    metrics["if_sel"] = dict(
        Counter(
            "T" if w is True else "F" if w is False else f"case{w}"
            for w in g.if_selected
        )
    )
    metrics["warn"] = dict(Counter(w.kind for w in g.warnings))

    # ---- 测量域 3: 不动点重喂（任何结局都留在 metrics.fp，status 恒 ok） ----
    g2 = Measured()
    g2.unread(toks)
    t0 = time.perf_counter()
    try:
        toks2 = g2.expand_all()
    except Exception as e:
        metrics["fp_ms"] = (time.perf_counter() - t0) * 1000
        metrics["fp"] = f"refeed_err:{e!r}"
        return {"status": "ok", "metrics": metrics}
    metrics["fp_ms"] = (time.perf_counter() - t0) * 1000
    metrics["fp_steps"] = g2.steps
    if len(toks2) != len(toks):
        metrics["fp"] = f"len {len(toks)}->{len(toks2)}"
    else:
        for k, (a, b) in enumerate(zip(toks, toks2, strict=True)):
            if not _tok_eq(a, b):
                metrics["fp"] = (
                    f"tok@{k} {a.kind}:{a.text[:24]!r}"
                    f"!={b.kind}:{b.text[:24]!r}"
                )
                break
        else:
            metrics["fp"] = "ok"
    return {"status": "ok", "metrics": metrics}


# ---------------------------------------------------------------- spec


spec = Spec(
    kind="gullet",
    params={
        "n": Param(int, default=0),
        "seed": Param(int, default=0),
        "ids": Param(str, default="", fp=False),
        "only": Param(str, default="", fp=False),
    },
    items=_items,
    select=_select,
    freeze_plan=True,
    executor="thread",
    env_probes=["python"],
    code_deps=[
        "src/texlate/latex/gullet",
        "src/texlate/latex/tables.py",
        "src/texlate/arxiv/locate.py",
        "src/texlate/textutil",
    ],
    allowed_layers=["core"],
    lake=True,
    prefetch=False,  # 测量 run 零湖写——水化只准 ctx.lake_ensure 按需（且本 spec 先 is_complete 闸，永不触发）
    eval=False,
    stages=[
        Stage(
            "gexpand",
            _gexpand,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
    ],
)
