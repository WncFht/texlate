"""specs.validbench.main — items/select/stages + spec 装配叶 (validbench 拆分叶).

湖 catalog 全格 + ``__probes__`` 合成探针格两类 item; ``_vb_run`` (单篇
case 全判 + emit_case + 全量 jsonl 底账) / ``_vb_probes`` (14 条对抗探针
断言格) 双 stage; ``spec`` 单例含唯一字母表 status_class。
"""

from __future__ import annotations

import json
import time

from kernel import fsutil, lake
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _select as _sel  # run 期收窄单源（ids/only/n 管道）
from specs.validbench.cases import _gen_paper_cases, _ParseFail
from specs.validbench.judge import _l0_one, _l1_here, _l1_one
from specs.validbench.probes import _probe_eval

#: Measurement generation marker — folded into every cell's variant.
#: Cross-run dedup makes DONE cells immortal; bump to re-measure.
EPOCH = "v1"

SEED = 20260915
MIN_LEN, MAX_LEN = 40, 4000

# ---------------------------------------------------------------- items/select


def _items() -> list[dict]:
    """湖 catalog 全格 + 一条合成探针格（eval=True → 免 canon 闸）。

    catalog 行不预过滤：skeleton/failed 格也产 item，stage 内 src_path()
    拿不到 → skip（manifest 有湖没有这一类保持显式行可见）。
    """
    cat = lake.LakeCatalog.load()
    items = [
        {
            "id": idc,
            "stage": "vb_run",
            "variant": f"run@{EPOCH}",
            # cell.layer 须标量（compile_checks 的 EVAL_LAYERS 隶属判定）；
            # 全量 layers 另键携带供 select 多属过滤。
            "layer": (row.get("layers") or [""])[0] or "",
            "layers": sorted(row.get("layers") or []),
        }
        for idc, row in sorted(cat.rows().items())
    ]
    items.append(
        {
            "id": "__probes__",
            "stage": "vb_probes",
            "variant": f"p@{EPOCH}",
        }
    )
    return items


def _n_run(ctx: _sel.Ctx) -> bool:
    """n 抽样只圈 vb_run 池——探针格不是样本（B6 gate 的一部分）。"""
    pool = sorted(str(it["id"]) for it in _ITEMS_POOL if it.get("stage") == "vb_run")
    return ctx.raw in _sel.seeded(pool, ctx.n, ctx.seed)


def _select(item: dict, rp: dict) -> bool:
    """窄化面：ids 逗列 / only 子串 / layers 层滤 / n+seed 湖内抽样。

    probes 格：无窄化或窄化显式命中时选入；探针格不走标准管道
    （layers/n 不应圈走它——它是 B6 gate 的一部分，不是样本）。
    """
    if item.get("stage") == "vb_probes":
        ids_p = str(rp.get("ids") or "").strip()
        if ids_p:
            return "__probes__" in _sel.csv_set(ids_p)
        only = str(rp.get("only") or "").strip()
        if only:
            return only in "__probes__"
        return True
    return _sel.select(
        item,
        rp,
        ids="gate",
        canon=False,
        layers="",
        layers_any=True,
        only="raw",
        sample=_n_run,
    )


_ITEMS_POOL: list[dict] = []  # select 的 n 抽样池（items() 物化后回填）


def _items_full() -> list[dict]:
    global _ITEMS_POOL  # noqa: PLW0603
    its = _items()
    _ITEMS_POOL = its
    return its


# ---------------------------------------------------------------- stages


def _vb_run(ctx) -> dict | str:
    """单篇：投影子进程解析 → case 生成 → L0(+L1) 逐判 → emit_case."""
    src = ctx.src_path()
    if src is None:
        ctx.emit({"metrics": {"reason": "lake_absent"}})
        return "skip"
    try:
        cases, stats = _gen_paper_cases(
            ctx.idc,
            src,
            max_per_paper=int(ctx.params["max_per_paper"]),
            min_len=int(ctx.params["min_len"]),
            max_len=int(ctx.params["max_len"]),
            seed=int(ctx.params["gen_seed"]),
        )
    except _ParseFail as e:
        return {
            "status": "fail",
            "errors": [{"cat": "parse", "msg": str(e)[:300]}],
            "metrics": {"parse_fail": 1},
        }
    if not cases:
        # 无 root / 窗内零 chunk / 全对 none-skipped —— 合法的零产出终态
        ctx.emit({"metrics": {**stats, "n_cases": 0}})
        return "clean"

    no_l1 = bool(ctx.params.get("no_l1"))
    daemon, l1_note = (None, "--no-l1") if no_l1 else _l1_here()
    baselines: dict = {}
    l0_wall_s = 0.0
    det = ncorr = clean_fp = warn_only = 0
    missed: list[str] = []
    fp_ids: list[str] = []
    l1_n = l1_det_rel = l1_det_abs = l1_clean_fp_rel = 0
    full_path = (
        ctx.rundir.derived() / "validbench-cases" / f"{ctx.safe}.jsonl"
        if ctx.rundir is not None
        else None
    )
    full_rows: list[str] = []

    for cs in cases:
        t0 = time.perf_counter_ns()
        verdict = _l0_one(cs)
        l0_wall_s += (time.perf_counter_ns() - t0) / 1e9
        if daemon is not None:
            cs["l1"] = _l1_one(daemon, cs, baselines)
            l1_n += 1
            l1_det_rel += int(cs["l1"]["detected"])
            l1_det_abs += int(not cs["l1"]["ok"])
            if cs["kind"] == "clean" and cs["l1"]["detected"]:
                l1_clean_fp_rel += 1
        # 紧凑判定行进 cases 表（分母守恒的逐 case 键面）
        ctx.emit_case(
            {
                "id": cs["id"],
                "paper": cs["paper"],
                "chunk": cs["chunk"],
                "level": cs["level"],
                "kind": cs["kind"],
                "l0": verdict,
                **({"l1": cs["l1"]} if "l1" in cs else {}),
            }
        )
        full_rows.append(json.dumps({**cs, "l0": verdict}, ensure_ascii=False))
        if cs["kind"] == "clean":
            if not verdict["ok"]:
                clean_fp += 1
                fp_ids.append(cs["id"])
            elif verdict["n_warn"]:
                warn_only += 1
        else:
            ncorr += 1
            if verdict["ok"]:
                missed.append(cs["id"])
            else:
                det += 1

    if full_path is not None:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        fsutil.atomic_write(full_path, ("\n".join(full_rows) + "\n").encode())

    metrics = {
        **stats,
        "n_cases": len(cases),
        "corrupt_n": ncorr,
        "corrupt_detected": det,
        "missed": missed[:50],
        "clean_n": len(cases) - ncorr,
        "clean_error_fp": clean_fp,
        "clean_fp_ids": fp_ids[:50],
        "clean_warn_only": warn_only,
        "l0_wall_s": round(l0_wall_s, 3),
        "l0_wall_per_pair_ms": round(l0_wall_s * 1000 / len(cases), 4),
        "cases_file": str(full_path) if full_path else None,
    }
    if daemon is None:
        metrics["l1_note"] = l1_note or "unavailable"
    else:
        metrics["l1"] = {
            "n": l1_n,
            "det_rel": l1_det_rel,
            "det_abs": l1_det_abs,
            "clean_fp_rel": l1_clean_fp_rel,
        }
    errors = []
    if missed:
        errors.append({"cat": "validator_miss", "msg": ";".join(missed[:8])})
    if clean_fp:
        errors.append({"cat": "clean_fp", "msg": ";".join(fp_ids[:8])})
    status = "fail" if errors else "ok"
    return {"status": status, "metrics": metrics, "errors": errors}


def _vb_probes(ctx) -> dict:
    """14 条对抗探针断言格."""
    rows = _probe_eval()
    n_pass = sum(1 for r in rows if r["pass"])
    fails = [r for r in rows if not r["pass"]]
    for r in rows:
        ctx.emit_case(
            {
                "id": r["id"],
                "probe": True,
                "expect_ok": r["expect_ok"],
                "ok": r["ok"],
                "n_err": r["n_err"],
                "n_warn": r["n_warn"],
                "pass": r["pass"],
                "fails": r["fails"],
            }
        )
    metrics = {
        "n": len(rows),
        "pass": n_pass,
        "fail_ids": [r["id"] for r in fails],
        "detail": [
            {"id": r["id"], "pass": r["pass"], "fails": r["fails"]} for r in rows
        ],
    }
    errors = [
        {"cat": "probe_fail", "msg": f"{r['id']}: {'; '.join(r['fails'])[:160]}"}
        for r in fails[:8]
    ]
    return {
        "status": "fail" if fails else "ok",
        "metrics": metrics,
        "errors": errors,
    }


spec = Spec(
    kind="validbench",
    params={
        "ids": Param(default="", fp=False),
        "only": Param(default="", fp=False),
        "layers": Param(default="", fp=False),
        "n": Param(type=int, default=0),
        "seed": Param(type=int, default=0),
        "max_per_paper": Param(type=int, default=6),
        "min_len": Param(type=int, default=MIN_LEN),
        "max_len": Param(type=int, default=MAX_LEN),
        "gen_seed": Param(type=int, default=SEED),
        "no_l1": Param(type=bool, default=False),
    },
    items=_items_full,
    select=_select,
    stages=[
        Stage(
            "vb_run",
            _vb_run,
            eval=True,
            # 唯一字母表（ok/fail/clean + 双 retriable）——不为单点造预设。
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "clean": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
        Stage(
            "vb_probes",
            _vb_probes,
            eval=True,
            # 唯一字母表（ok/fail 缺 skip——探针格无重试面）——不为单点造预设。
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
    ],
    eval=True,
    lake=True,
    env_probes=["python", "node"],
    code_deps=[
        "src/texlate/validate",
        "src/texlate/latex",
        "src/texlate/compile/mainfile.py",
        "bench/py/specs/validbench/pseudo.py",
        "bench/py/specs/validbench/corrupt.py",
        "bench/py/specs/validbench/cases.py",
        "bench/py/specs/validbench/judge.py",
        "bench/py/specs/validbench/probes.py",
        "bench/py/specs/validbench/main.py",
    ],
)
