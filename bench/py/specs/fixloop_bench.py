"""fixloop_bench — B3 营救率评测器（原 ``bench/py/fixloop_bench.py`` baseline 臂）。

每篇 × 每引擎一格：湖投影 → 剥 mode 拷贝 → 产品化
``texlate.compile.fixloop.fixloop``（编译→logparse→taxonomy→规则修复→重编，
≤ruleset max_rounds=8 轮）。营救率 = baseline FAIL 格内经 fixloop 出
pdf/clean 层的比例——聚合归分析动词（Wave-D），本 spec 只落逐格 verdict
+ baseline 对拍字段进 eval_records。

样本面（40 篇 corpus_v2 分层抽样，seed=20260915）：旧
``results/compilebench-corpusv2-2026-09-15/{sample,cells}.json`` 已删除，
基线经 **import 道复原**——items 读 ledger index 中
``import-archive-2026-09-20_results_compilebench-corpusv2-2026-09-15_cells-recovered``
run 的 40 条 records（每篇 metrics.engines{eng} 含 baseline
verdict/category/pdf）。换基线 run 改模块常量 ``BASELINE_RUN``。

payload 现状：该 40 篇在湖 catalog 全 ``skeleton``（Phase-4 迁移期字节未
水化）——``ctx.src_path()`` 返 None → ``skip``(retriable)。corpus builders
（Wave-E）或 IA 抓取补水后 resume 自然开跑；**不把 skeleton 当 fail 计**——
旧世 ``no_source`` 桩行是"字节判死"语义，湖世 skeleton 是"字节在途"，
语义不同桶（刻意 delta，见下）。

status 映射（fn 可达集）：

- ``ok``(terminal)    — fixloop 产出 verdict（含 reject:/no_main_tex/stuck
                        等全部测量结果；verdict 光谱进 metrics，不进 status）
- ``fault``(terminal) — 测量路径崩溃（引擎装配/fixloop 异常 → 旧
                        ``harness_crash:<Type>`` 行等价物，计分母）
- ``skip``(retriable) — 湖格不可投影（skeleton/未水化；旧 no_source 的
                        诚实替代——湖补水后自然可跑）
- ``error``(retriable)— 域外异常（copy/route/IO 基建）

done 定义：终态 = ok∪fault∪{kernel dedup}；skip/error 走 RETRIABLE 重排队。
分母守恒：frame = 40 篇 × 2 引擎 = 80 格（同旧 cells.jsonl 行数）；旧
``verdict`` 字段逐格保留在 metrics，baseline 对拍列经 item params 内嵌
（base_verdict/base_category/base_pdf），救回率分子/分母可纯从
eval_records 重建。

EPOCH 约定（Wave-B 重测口径）：``variant = "{eng}@{EPOCH}"``——内核跨
run dedup 按 (idc,arm,up,variant,stage) 永久记忆，测量世代递进靠 bump
模块常量 ``EPOCH``（code_deps 同动 → fp 标 stale + 新 cell 键）。

刻意 delta（vs 旧驱动）：

- ``--llm``/``--inject-zh`` 臂不移植：llm 是付费面（须独立 paid stage 配
  gateway_factory+预算闸，另案）；zh 注入臂属 soak 链内 cond，非 B3 测量面。
- ``--cases-from`` 模式不移植：换基线 = 改 BASELINE_RUN（items 零参物化
  拿不到 run param）。
- _make_engine/fixloop 异常从「静默丢格（主循环 fut.result() 崩→无行）」
  改为 ``fault`` 终态行——分母不再漏格。
- workspace()/_texmf 归 paper_dir per-run：旧跨 run 复用 wdir 的「复用树」
  语义天然 per-run 化（每次测量冷启动，更接近 baseline 冷口径）。
- xelatex 格内 rmtree(_texmf) 重冷启动逻辑保留（resume 重跑时防半成品
  usertree 偏暖）。

用法::

    bench plan fixloop_bench                 # 80 格报价
    bench run  fixloop_bench engines=tectonic n=4
    bench run  fixloop_bench ids=1404.7186   # 单篇双臂
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import random
import shutil
import sqlite3
import time
from pathlib import Path

from kernel import fsutil, idnorm, paths
from kernel.spec import Param, Spec, Stage

from specs import _benchlite as benchlib
from specs import _fixloop as _flx
from texlate.compile import route_project
from texlate.compile.fixloop import CaseSink, fixloop

ROOT = Path(__file__).resolve().parents[3]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))

#: 测量世代——bump 即换 cell 键（跨 run dedup 自然失效），code_deps 同动
#: 标 stale。文档化重测口径：不改代码只重测 = bump EPOCH。
EPOCH = "v1"

#: corpusv2 40 篇分层样本的基线来源：import 道复原的 compilebench cells
#: （每篇一条 records，metrics.engines{eng} 双引擎 verdict 全字段）。
BASELINE_RUN = (
    "import-archive-2026-09-20_results_compilebench-corpusv2-2026-09-15_cells-recovered"
)

ENGINES = ("xelatex", "tectonic")
COND = "b3"

# ---------------------------------------------------------------- tier 映射
# fixloop verdict → baseline 可比层（旧 fixloop_bench.py TIER/GOOD/PDFY
# 原样——救回率口径逐字保真）。

TIER = {
    "clean": "clean",
    "acceptable_pdf": "clean~",
    "dirty_pdf": "pdf~",
    "best_effort_pdf": "pdf~",
    "stuck": "fail",
    "max_rounds": "fail",
    "no_errors_no_pdf": "fail",
    "no_main_tex": "fail",
    "no_source": "fail",
}
GOOD = {"clean", "acceptable_pdf"}
PDFY = {"clean", "acceptable_pdf", "dirty_pdf", "best_effort_pdf"}


def _tier_of(verdict) -> str:
    v = str(verdict or "")
    if v.startswith(("reject:", "unfixable:", "harness_crash:")):
        return "reject" if v.startswith("reject:") else "fail"
    return TIER.get(v, "fail")


# ---------------------------------------------------------------- items


@functools.cache
def _canon(raw: str):
    return idnorm.canon_id(str(raw))


def _baseline_rows() -> dict[str, dict]:
    """index 复原 corpusv2 基线：{idc: metrics dict}（只读连接）。"""
    idx = paths.index_path()
    if not idx.is_file():
        return {}
    out: dict[str, dict] = {}
    try:
        con = sqlite3.connect(f"file:{idx}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        for idc, mjson in con.execute(
            "SELECT idc, metrics FROM records WHERE run=?", (BASELINE_RUN,)
        ):
            try:
                out[str(idc)] = json.loads(mjson or "{}")
            except ValueError:
                out[str(idc)] = {}
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return out


@functools.cache
def _manifest_sha() -> dict[str, str]:
    """manifest*.jsonl 的 id → fp_input（blob|main_tex|raw sha256）。

    ``raw_sha256`` 兜底：corpusv2 40 篇只挂 manifest_v2（tarball sha，
    无解压后面 sha）——tarball 是 extracted/ 的上游字节源，照样钉死
    输入。键按 canon 归一双侧匹配（raw/canon 混存——mixed-id-forms 前科）。
    """
    out: dict[str, str] = {}
    for mp in sorted(CORPUS.glob("manifest*.jsonl")):
        for row in benchlib.iter_jsonl(mp):
            if not isinstance(row, dict) or not row.get("id"):
                continue
            sha = (
                row.get("blob_sha256")
                or row.get("main_tex_sha256")
                or row.get("raw_sha256")
            )
            if not sha:
                continue
            res = _canon(row["id"])
            key = res.idc if res.ok and res.idc else str(row["id"])
            out.setdefault(key, str(sha))
            out.setdefault(str(row["id"]), str(sha))
    return out


def _items() -> list[dict]:
    """items = corpusv2 样本 × ENGINES 网格（spec load 时一次物化）。

    每格 params 内嵌 baseline 对拍字段（该引擎格的 verdict/category/pdf）
    + 论文元数据（band/tags/yymm）——eval_records 单行即可重建救回率。
    """
    rows = _baseline_rows()
    sha = _manifest_sha()
    items: list[dict] = []
    for idc in sorted(rows):
        m = rows[idc]
        engines_m = m.get("engines") or {}
        res = _canon(idc)
        cid = res.idc if res.ok and res.idc else idc
        for eng in ENGINES:
            be = engines_m.get(eng) or {}
            items.append(
                {
                    "id": idc,
                    "arm": COND,
                    "variant": f"{eng}@{EPOCH}",
                    "fp_input": sha.get(cid) or sha.get(idc),
                    "params": {
                        "engine": eng,
                        "base_verdict": be.get("verdict"),
                        "base_category": be.get("category"),
                        "base_pdf": bool(be.get("pdf")),
                        "band": m.get("band"),
                        "tags": m.get("tags") or [],
                        "yymm": m.get("yymm"),
                        "src_run": BASELINE_RUN,
                    },
                }
            )
    return items


_ITEMS: list[dict] | None = None


def _items_cached() -> list[dict]:
    global _ITEMS  # noqa: PLW0603
    if _ITEMS is None:
        _ITEMS = _items()
    return _ITEMS


def _sample_idcs(n: int, seed: int) -> set[str]:
    """论文级 seeded 抽样（样本 n 篇 → 该篇全部引擎格保留）。"""
    pool: set[str] = set()
    for it in _items_cached():
        res = _canon(it["id"])
        if res.ok and res.idc:
            pool.add(res.idc)
    pool_l = sorted(pool)
    rng = random.Random(seed)
    return set(rng.sample(pool_l, min(n, len(pool_l))))


def _select(item: dict, rp: dict) -> bool:
    """run 期收窄：engines → ids（raw/canon 双侧）→ only 子串 → n/seed 抽样。"""
    engs = {
        s.strip()
        for s in str(rp.get("engines") or "xelatex,tectonic").split(",")
        if s.strip()
    }
    if engs and str((item.get("params") or {}).get("engine")) not in engs:
        return False
    raw = str(item.get("id") or "")
    res = _canon(raw)
    idc = res.idc if res.ok and res.idc else raw
    ids_p = str(rp.get("ids") or "").strip()
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
        if needle not in idc and only not in raw:
            return False
    n = int(rp.get("n") or 0)
    if n > 0:
        seed = int(rp.get("seed") or 0)
        return idc in _sample_idcs(n, seed)
    return True


# ---------------------------------------------------------------- stage


class _CaseBridge(CaseSink):
    """CaseSink → ctx.emit_case 桥：fixloop 的原生 case 沉淀同时落
    cases 表/cases.jsonl（内核批原子提交）；文件面走 os.devnull——
    ledger 是唯一真账，per-run cases.jsonl 由内核镜像生成。"""

    def __init__(self, ctx) -> None:
        super().__init__(os.devnull)
        self._ctx = ctx

    def record(self, cell, *, corpus_id=None, cond=None, engine=None):
        rec = super().record(cell, corpus_id=corpus_id, cond=cond, engine=engine)
        self._ctx.emit_case(rec)
        return rec


def _route_of(wdir: Path) -> dict:
    """route_project(prefer='xelatex') 记录面（旧 report() 同口径）。"""
    out = {
        "engines": [],
        "reject": None,
        "reasons": [],
        "non_utf8": False,
        "latex209_suspect": False,
    }
    with contextlib.suppress(Exception):
        r = route_project(wdir, prefer="xelatex")
        out = {
            "engines": list(r.engines or []),
            "reject": r.reject,
            "reasons": list(r.reasons or []),
            "non_utf8": bool(r.non_utf8),
            "latex209_suspect": bool(r.latex209_suspect),
        }
    return out


def _fl_b3(ctx) -> dict:
    """单格：湖投影 → 剥 mode 拷贝 → route 记录 → fixloop 测量。

    verdict 光谱全进 metrics（含 reject:/no_main_tex/stuck 等——都是成功
    测量）；返回 status 只管「测量是否完成」：ok / fault(崩) / skip(无源)。
    """
    eng_name = str(ctx.params.get("engine") or "xelatex")
    base = {
        "base_verdict": ctx.params.get("base_verdict"),
        "base_category": ctx.params.get("base_category"),
        "base_pdf": bool(ctx.params.get("base_pdf")),
        "src_run": ctx.params.get("src_run") or BASELINE_RUN,
    }
    meta = {
        "band": ctx.params.get("band"),
        "tags": ctx.params.get("tags") or [],
        "yymm": ctx.params.get("yymm"),
    }

    src = ctx.src_path()
    if src is None:
        # 湖格无载荷（skeleton/未水化）——旧 no_source 桩行的诚实替代：
        # retriable skip，湖补水后 resume 自然开跑。
        ctx.emit(
            {
                "metrics": {
                    "engine": eng_name,
                    "cond": COND,
                    "verdict": "no_source",
                    "tier": _tier_of("no_source"),
                    **base,
                    **meta,
                }
            }
        )
        return "skip"

    ws = ctx.workspace()
    wdir = ws / f"fl_{eng_name}"
    if wdir.exists():
        shutil.rmtree(wdir)
    try:
        n_copied = fsutil.copy_mutating(src, wdir)
    except (OSError, ValueError) as e:
        ctx.emit(
            {
                "errors": [{"cat": "project_io", "msg": f"copy_mutating: {e}"}],
                "metrics": {"engine": eng_name, **base, **meta},
            }
        )
        return "error"

    texmf = ctx.paper_dir() / "_texmf"
    if eng_name == "xelatex" and texmf.exists():
        shutil.rmtree(texmf)  # 重跑须从零冷启动（旧 run_paper 同口径）

    t0 = time.time()
    try:
        eng = _flx._make_engine(eng_name, texmf, wdir)
        cell = fixloop(
            wdir,
            eng,
            ruleset=_flx._rs(),
            engine_name=eng_name,
            corpus_id=ctx.idc,
            cond=COND,
            runner=_flx._texmf_runner(texmf) if eng_name == "xelatex" else None,
            case_sink=_CaseBridge(ctx),
            compile_timeout=(
                float(ctx.params["timeout"]) or None
                if float(ctx.params.get("timeout") or 0) > 0
                else None
            ),
        )
    except Exception as e:
        # fault(terminal)：旧世 fut.result() 崩丢格的缺陷修正——分母保格。
        return {
            "status": "fault",
            "errors": [
                {
                    "cat": "harness_crash",
                    "payload": type(e).__name__,
                    "msg": str(e)[:400],
                }
            ],
            "metrics": {
                "engine": eng_name,
                "cond": COND,
                "verdict": f"harness_crash:{type(e).__name__}",
                "tier": "fail",
                "final_pdf": False,
                "wall_s": round(time.time() - t0, 1),
                "n_copied": n_copied,
                "route": _route_of(wdir),
                **base,
                **meta,
            },
        }

    verdict = cell.get("verdict")
    tier = _tier_of(verdict)
    bv = base["base_verdict"]
    rounds = [
        {
            "round": r.get("round"),
            "cat": r.get("category"),
            "pdf": r.get("pdf"),
            "n_errors": r.get("n_errors"),
        }
        for r in cell.get("rounds") or []
    ]
    return {
        "status": "ok",
        "metrics": {
            "engine": eng_name,
            "cond": COND,
            "verdict": verdict,
            "tier": tier,
            "final_cat": cell.get("final_cat"),
            "main": cell.get("main"),
            "final_pdf": bool(cell.get("final_pdf")),
            "n_rounds": len(cell.get("rounds") or []),
            "rounds": rounds,
            "n_actions": len(cell.get("actions") or []),
            "installed": list(cell.get("installed") or []),
            "gate_fired": list(cell.get("gate_fired") or []),
            "wall_s": round(time.time() - t0, 1),
            "n_copied": n_copied,
            "route": _route_of(wdir),
            # 救回率逐格布尔（聚合动词直接 sum）：
            "rescued_pdf": bv == "FAIL" and verdict in PDFY,
            "rescued_good": bv == "FAIL" and verdict in GOOD,
            "regression": verdict not in PDFY and bv in ("clean", "pdf~"),
            **base,
            **meta,
        },
    }


# ---------------------------------------------------------------- spec


spec = Spec(
    kind="fixloop_bench",
    params={
        "ids": Param(str, default="", fp=False),
        "only": Param(str, default="", fp=False),
        "engines": Param(str, default="xelatex,tectonic", fp=False),
        "n": Param(int, default=0),
        "seed": Param(int, default=0),
        # >0 → fixloop compile_timeout 覆盖（0 = ruleset/引擎缺省 240s）
        "timeout": Param(float, default=0.0, fp=True),
    },
    items=_items_cached,
    select=_select,
    stages=[
        Stage(
            "fl_b3",
            _fl_b3,
            status_class={
                "ok": "terminal",
                "fault": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
            eval=True,  # 测量行进 eval_records 道（spec.eval=False 保 canon 闸）
        ),
    ],
    freeze_plan=True,
    executor="thread",
    same_id_serial=True,  # 同 idc 双引擎格共享 paper_dir/_texmf——串行防互踩
    lake=True,
    eval=False,
    env_probes=["xelatex", "tectonic", "tlmgr", "pdftotext"],
    code_deps=[
        # 被测面进 fp：fixloop 引擎+规则库+配方层+引擎/装包/路由件——
        # 任一改动 → stale 标记（重测 = bump EPOCH 换 cell 键）。
        "src/texlate/compile/fixloop",
        "bench/py/specs/_fixloop.py",
        "src/texlate/compile/engine",
        "src/texlate/compile/ctan.py",
        "src/texlate/compile/mainfile.py",
        "src/texlate/compile/judge.py",
        "src/texlate/compile/logparse.py",
        "src/texlate/compile/texlive",
    ],
)
