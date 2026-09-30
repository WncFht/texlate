r"""compilebench — corpus 原文直编基线评测器（``compilebench_v3.py`` 的 spec 化）。

每格 = (paper × cond × engine)：``arm`` = cond（``baseline`` 原文直编 /
``zh`` normalize+prepare_chinese(ctex) 后直编，docs/spec/benchmark.md §B3
网格），``variant`` = ``{engine}@{EPOCH}``。判定走产品
``engine_for`` + ``compile.judge``（expect_cjk=False），冷 TEXMF 沙箱
（每篇 ``paper_dir()/_texmf`` 独立 TEXMFHOME/VAR/CONFIG，同 paper 各格
经 same_id_serial 串行共享）。

frame（items 的固定定义，属 spec 本体非 run 参数）：
``MANIFESTS`` = manifest.jsonl（1000 core 卷，38 个 stratum_cell）→
load_pool 过滤（stub∧n_tex=0 剔除，EVAL_LAYERS 剔除）→ 与湖 catalog
取交（hydrated/pinned/raw_only 或盘上 complete——替代旧
``extracted is_dir`` 检查，语义同位）→ ``gen_sample`` 逐行移植
（stratum_cell 比例分配 largest remainder + min 1，``Random(SEED)``
逐 cell shuffle，(band,cell,id) 定序）。``SAMPLE_N``/``SEED``/``EPOCH``
是模块常量：换抽样 = 换测量届——配合 ``EPOCH`` bump 开新一代 cell 键
（跨 run dedup 在 (idc,arm,up,variant,stage) 上永续，内核无重跑门，
评测器靠 variant 里的 epoch 分量换代；同 epoch 重跑即 resume dedup）。

done 口径对拍：旧 done = (paper_id,engine) ∈ cases.jsonl 任意 verdict
行 ↔ 新 done = (idc,cond,eng@EPOCH,cb_compile) records 末态 ∈
DONE∪{dedup}。桩行全落 terminal DONE 保分母：no_main_tex→reject、
inject_reject→reject、harness_crash→fault。

蓄意 delta（相对旧驱动，文档化项）：
- ``no_source``（src 缺席）旧为计分桩行 → 新 ``skip`` retriable；
  湖取交预过滤使其≈零触发，触发即 warn 级 note。
- 旧 baseline 臂双引擎**顺序共享同一脏 wdir**（tectonic 吃 xelatex
  残留 aux/log/missfont）；新格制每 (cond,eng) 独立干净目录——
  cell 间无保序通道，且干净口径更诚实。
- run 级聚合（summary.md/cells.json/v2 对比）不进城——归 derive/report
  分析动词；本 spec 只保证逐 case 行字段足以重建。

status 映射：judge clean/partial/fail/reject → 同名 kernel 终态；
旧词（pdf~/FAIL/no_*）保留在 metrics.verdict 与 case 行 verdict 字段。
子类别（no_main_tex/inject_reject/harness_crash/missing_pfb…）走
errors[].cat + sig 合成道（kernel cat 白名单外词不落 cat 列）。
"""

from __future__ import annotations

import contextlib
import functools
import os
import random
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from kernel import fsutil, idnorm, lake
from kernel.spec import EVAL_LAYERS, Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs import _select as _sel  # run 期收窄单源（ids/only/n 管道）

ROOT = Path(__file__).resolve().parents[3]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))

# ---------------------------------------------------------------- frame 常量

#: 测量届别——折进 variant（``{eng}@{EPOCH}``）。被测面（产品 compile/
#: judge/inject 码或抽样定义）换代时 bump：旧届 cell 键不动、dedup 不
#: 误伤，新届全量重测。
EPOCH = "v1"

#: 抽样定义（旧 --sample-n/--seed）：frame 的一部分，不是 selector。
SAMPLE_N = 180
SEED = 20260915

#: 旧 CONDS/引擎面。grid 枚举恒定全集，run 期收窄走 select 参数。
CONDS = ("baseline", "zh")
ENGINES = ("xelatex", "tectonic")

#: 旧 --manifest 默认 <corpus>/manifest.jsonl（core 卷是唯一无偏分层框；
#: booster/dev/holdout 卷不进基线分母）。
MANIFESTS = ("manifest.jsonl",)

#: 湖「自带或可免费自愈字节」的态（soak 同口径）：hydrated/pinned 直读，
#: raw_only 经 hydrate() 本地重解包零网络。
_HYDRATABLE = frozenset({"hydrated", "pinned", "raw_only"})

PASS_TIMEOUT = 240.0  # 单 pass/单 attempt 上限 (s)，docs/spec/compile.md
XELATEX_TIMEOUT = PASS_TIMEOUT * 2  # 产品 compile timeout=总预算 (2 pass)
TECTONIC_TIMEOUT = PASS_TIMEOUT
MAX_PASSES = 2

#: tlmgr usermode 装包钉 tuna（mirror.ctan.org round-robin 本机不通，
#: 2026-09-15 实测）；单源 benchlib。
TUNA_TLNET = benchlib.TUNA_TLNET

#: product verdict.status → 旧 v2 词汇（metrics/case 展示口径；kernel
#: status 列用同名终态词）。
VERDICT_MAP = {
    "clean": "clean",
    "partial": "pdf~",
    "fail": "FAIL",
    "reject": "reject",
}

# ---------------------------------------------------------------- frame 构建


def band_of_cell(stratum_cell: str) -> str:
    """'a_pre2007' → 'a'（v2 五带词汇）。"""
    return (stratum_cell or "?").split("_", 1)[0]


def _pool() -> dict:
    """manifest → 可编译池（stub∧n_tex=0 滤、EVAL_LAYERS 滤）∩ 湖可供应格。

    旧 ``extracted is_dir`` 谓词的湖版：catalog 标 hydrated/pinned/
    raw_only，或未登记但盘上 complete（seed 湖）。failed/empty/skeleton
    态出池——它们的字节这条路径永远拿不到。
    """
    pool: dict[str, dict] = {}
    for name in MANIFESTS:
        mp = CORPUS / name
        if not mp.is_file():
            continue
        for r in benchlib.iter_jsonl(mp):
            if r.get("format") == "stub" or not r.get("n_tex"):
                continue
            if r.get("layer") in EVAL_LAYERS:
                continue
            pid = r["id"]
            cell = r.get("stratum_cell") or "?"
            pool[pid] = {
                "id": pid,
                "band": band_of_cell(cell),
                "stratum_cell": cell,
                "cat_group": r.get("cat_group"),
                "yymm": r.get("yymm"),
                "era": r.get("era"),
                "layer": r.get("layer"),
                "format": r.get("format"),
                "n_files": r.get("n_files"),
                "n_tex": r.get("n_tex"),
                "bytes": r.get("bytes"),
                "blob_sha256": r.get("blob_sha256"),
            }
    cat = lake.LakeCatalog.load()
    out: dict[str, dict] = {}
    for pid, p in pool.items():
        res = idnorm.canon_id(str(pid))
        idc = res.idc if res.ok and res.idc else str(pid)
        st = cat.state(idc)
        if st in _HYDRATABLE:
            ok = True
        elif st in ("failed", "empty"):
            ok = False
        else:
            ok = lake.is_complete(idc)
        if ok:
            out[pid] = {**p, "idc": idc}
    return out


def _sample(pool: dict) -> list[dict]:
    """gen_sample 逐行移植：stratum_cell 比例分配（floor+min1+largest
    remainder 补齐/收敛）+ Random(SEED) 逐 cell shuffle + (band,cell,id)
    定序。抽样定义在 spec 里文件化——plan.json 冻结格集即旧 sample.json。"""
    rng = random.Random(SEED)  # 语料抽样非安全用途
    by_cell = defaultdict(list)
    for p in pool.values():
        by_cell[p["stratum_cell"]].append(p)
    for cell in by_cell.values():
        rng.shuffle(cell)

    n_total = sum(len(v) for v in by_cell.values())
    n_target = min(SAMPLE_N, n_total)
    quota = {}
    for cell, ps in by_cell.items():
        exact = n_target * len(ps) / n_total
        quota[cell] = max(1, int(exact))
    while sum(quota.values()) < n_target:
        best = max(
            by_cell,
            key=lambda c: (
                n_target * len(by_cell[c]) / n_total - quota[c],
                -len(by_cell[c]),
            ),
        )
        if quota[best] >= len(by_cell[best]):
            break
        quota[best] += 1
    while sum(quota.values()) > n_target:
        best = max(
            (c for c in quota if quota[c] > 1),
            key=lambda c: quota[c] - n_target * len(by_cell[c]) / n_total,
            default=None,
        )
        if best is None:
            break
        quota[best] -= 1

    picked = []
    for cell, q in sorted(quota.items()):
        picked.extend({**p, "pick_reason": f"cell:{cell}"} for p in by_cell[cell][:q])
    picked.sort(key=lambda p: (p["band"], p["stratum_cell"], p["id"]))
    return picked


_PIDS: list[str] = []


def _items() -> list[dict]:
    """样本 papers × CONDS × ENGINES 全格集（load 期一次物化）。

    ``_PIDS`` 留 sample 定序的 paper 序——select 的 ``n=`` 取前 n 篇
    （旧 --limit 口径：sample.json 序前切）。
    """
    global _PIDS  # noqa: PLW0603
    items: list[dict] = []
    picked = _sample(_pool())
    _PIDS = [p["id"] for p in picked]
    for p in picked:
        for cond in CONDS:
            items.extend(
                {
                    "id": p["id"],
                    "arm": cond,
                    "variant": f"{eng}@{EPOCH}",
                    "layer": p.get("layer"),
                    "fp_input": p.get("blob_sha256"),
                    "params": {
                        "band": p["band"],
                        "stratum_cell": p["stratum_cell"],
                        "cat_group": p.get("cat_group"),
                        "yymm": p.get("yymm"),
                        "era": p.get("era"),
                        "n_files": p.get("n_files"),
                        "n_tex": p.get("n_tex"),
                        "pick_reason": p["pick_reason"],
                        "sample_seed": SEED,
                        "sample_n": SAMPLE_N,
                        "epoch": EPOCH,
                    },
                }
                for eng in ENGINES
            )
    return items


# ---------------------------------------------------------------- select 收窄


def _dims(ctx: _sel.Ctx) -> bool:
    """condition（arm ∈ 名单，"all" 通配）+ engines（variant@head ∈ 名单）。"""
    conds = _sel.csv_set(ctx.rp.get("condition") or "baseline")
    if "all" not in conds and str(ctx.item.get("arm")) not in conds:
        return False
    engs = _sel.csv_set(ctx.rp.get("engines") or "")
    return not engs or str(ctx.item.get("variant", "")).split("@", 1)[0] in engs


def _n_first(ctx: _sel.Ctx) -> bool:
    return ctx.raw in set(_PIDS[: ctx.n])


def _select(item: dict, rp: dict) -> bool:
    """run 期收窄（全 fp=False selector 族）：``ids=`` canon 双拼写直选 →
    ``condition=``（默认 baseline，逗分或 all）→ ``engines=`` →
    ``only=`` idc 子串 → ``n=`` 前 n 篇（sample 定序）。"""
    return _sel.select(item, rp, pre=_dims, ids="gate", only="canon", sample=_n_first)


# ---------------------------------------------------------------- 编译核


def _cold_texmf(pdir: Path) -> Path:
    """冷 usermode texmf（home/var/config 三子目录），挂在 paper_dir 上——
    同 paper 各 (cond,eng) 格共享（same_id_serial 串行保证装包不互踩）。"""
    tm = pdir / "_texmf"
    for sub in ("home", "var", "config"):
        (tm / sub).mkdir(parents=True, exist_ok=True)
    return tm


def _run_engine(eng_name: str, wdir: Path, main_rel: str, texmf: Path):
    """产品 engine.compile + judge —— 参数面逐行对齐旧驱动。"""
    from texlate.compile.engine import engine_for
    from texlate.compile.judge import judge

    kw: dict = {}
    if eng_name == "xelatex":
        kw = {"halt_on_error": False, "texmfhome": texmf, "repository": TUNA_TLNET}
    eng = engine_for(eng_name, **kw)
    timeout = XELATEX_TIMEOUT if eng_name == "xelatex" else TECTONIC_TIMEOUT
    env_extra = {
        "TEXMFHOME": str(texmf / "home"),
        "TEXMFVAR": str(texmf / "var"),
        "TEXMFCONFIG": str(texmf / "config"),
    }
    res = eng.compile(
        wdir,
        main_rel,
        passes=MAX_PASSES,
        timeout=timeout,
        sandbox=True,
        env_extra=env_extra,
    )
    v = judge(res, expect_cjk=False)
    return res, v


#: 引擎 stderr/stdout_tail 二次归因（v2 classify 同规则，产品
#: classify_error 无此路）：仅当产品类别落弱类且无 pdf 时启用。
_STDERR_RULES = (
    ("missing_pfb", r"Cannot proceed without .vf|physical font"),
    (
        "ps_image",
        (
            r"PostScript images are not supported|"
            r'image inclusion failed for "[^"]*\.(?:eps|ps)"'
        ),
    ),
    ("missing_file", r"File `([^']+)' not found|I can't find file"),
    ("dvipdf", r"something bad happened inside|error:.*dvipdfmx"),
    ("emergency", r"unrecoverable|Emergency|Fatal|cannot \\read"),
)
_WEAK_CATS = {None, "clean", "other", "emergency", "dvipdf"}


def _refine_category(cat, pay, res):
    """弱类首错时 stdout_tail（stderr 已并入）再归因 → (cat,pay,refined)。"""
    if cat not in _WEAK_CATS or res.has_pdf or not res.stdout_tail:
        return cat, pay, False
    for name, pat in _STDERR_RULES:
        m = re.search(pat, res.stdout_tail, re.IGNORECASE)
        if m:
            return name, next((g for g in m.groups() if g), pay), True
    return cat, pay, False


@functools.cache
def _engine_version(eng: str) -> str | None:
    """``eng --version`` 首行——随格进 metrics（env_probes 只记路径不记
    版本，引擎升级不改 fp；版本实录是口径漂移的观测面）。"""
    with contextlib.suppress(Exception):
        out = subprocess.run(
            [eng, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = (out.stdout or out.stderr).strip().splitlines()
        if lines:
            return lines[0]
    return None


def _case_base(ctx, eng: str, main_rel: str | None, route: dict) -> dict:
    """旧 _case_base 身份字段逐格等价。"""
    p = ctx.params
    return {
        "corpus": "corpus",
        "cond": ctx.arm,
        "paper_id": ctx.idc,
        "band": p.get("band"),
        "stratum_cell": p.get("stratum_cell"),
        "cat_group": p.get("cat_group"),
        "engine": eng,
        "main": main_rel,
        "route_reject": route.get("reject"),
        "route_non_utf8": route.get("non_utf8"),
        "route_latex209_suspect": route.get("latex209_suspect"),
    }


# ---------------------------------------------------------------- stage fn


def _cb_compile(ctx) -> dict:
    """run_paper 单格化：src 投影 → route/find_main 检测 → （zh 臂
    normalize+inject）→ 产品引擎编译 + judge → case+metrics 全字段。"""
    from texlate.compile.engine import route_project
    from texlate.compile.inject import (
        InjectRejectError,
        classify_no_main,
        find_main_tex,
        prepare_chinese,
    )
    from texlate.compile.normalize import normalize_project

    cond = ctx.arm
    eng = ctx.variant.split("@", 1)[0]
    src = ctx.src_path()
    if src is None:
        # 湖格中途被逐——旧口径这是 no_source 计分桩行；新口径湖取交
        # 预过滤后≈零触发，skip retriable（刻意 delta，见 docstring）。
        ctx.emit_note(f"{ctx.idc}: lake cell unavailable -> skip", level="warn")
        return "skip"

    route = route_project(src)  # prefer 默认 tectonic（旧同）
    route_d = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    base_metrics = {
        "route": route_d,
        "engine_version": _engine_version(eng),
        "epoch": EPOCH,
    }

    main = find_main_tex(src)
    if not main:
        sub = classify_no_main(src) or ""
        case = {
            **_case_base(ctx, eng, None, route_d),
            "verdict": "no_main_tex",
            "verdict_sub": sub,
        }
        ctx.emit_case(case)
        return {
            "status": "reject",
            "metrics": {**base_metrics, "verdict": "no_main_tex", "verdict_sub": sub},
            "errors": [{"cat": "no_main_tex", "msg": sub or "no main tex found"}],
        }
    main_rel = main.relative_to(src).as_posix()

    texmf = _cold_texmf(ctx.paper_dir())
    cur = ctx.workspace() / f"{cond}.{eng}"
    if cur.exists():
        shutil.rmtree(cur)
    fsutil.copy_mutating(src, cur)  # 0444 投影剥 mode——禁 copytree

    prep: dict = {}
    if cond == "zh":
        try:
            prep["normalize"] = normalize_project(cur, eng, main_rel)
            prep["inject"] = prepare_chinese(cur, main_rel)
        except InjectRejectError as e:
            case = {
                **_case_base(ctx, eng, main_rel, route_d),
                "verdict": "reject",
                "category": "inject_reject",
                "payload": e.reason,
            }
            ctx.emit_case(case)
            return {
                "status": "reject",
                "metrics": {
                    **base_metrics,
                    "verdict": "reject",
                    "category": "inject_reject",
                    "payload": e.reason,
                    **prep,
                },
                "errors": [{"cat": "inject_reject", "payload": e.reason}],
            }

    try:
        res, v = _run_engine(eng, cur, main_rel, texmf)
    except Exception as e:
        # 旧 harness_crash 是计分桩行（verdict=FAIL 入分母）——落 fault
        # terminal，绝不能漏进 kernel error retriable 让分母漂移。
        case = {
            **_case_base(ctx, eng, main_rel, route_d),
            "verdict": "FAIL",
            "category": "harness_crash",
            "payload": f"{type(e).__name__}: {e}",
        }
        ctx.emit_case(case)
        return {
            "status": "fault",
            "metrics": {
                **base_metrics,
                "verdict": "FAIL",
                "category": "harness_crash",
                **prep,
            },
            "errors": [{"cat": "harness_crash", "msg": f"{type(e).__name__}: {e}"}],
        }

    cat, pay, refined = _refine_category(v.category, v.payload, res)
    rec = {
        "status": v.status,
        "verdict": VERDICT_MAP.get(v.status, v.status),
        "reasons": v.reasons,
        "category": cat,
        "category_raw": v.category,
        "category_stderr": refined,
        "payload": pay,
        "n_errors": v.n_errors,
        "warnings_hit": v.warnings_hit,
        "missing_chars": v.missing_chars,
        "error_cats": v.error_cats,
        "error_pay": v.error_pay,
        "pdf": res.has_pdf,
        "pdf_bytes": res.pdf_bytes,
        "passes": res.passes,
        "seconds": round(res.seconds, 1),
        "timed_out": res.timed_out,
        "rc": res.rc,
        "first_error": (res.log.first_error or "")[:200] or None,
        "stdout_tail": (res.stdout_tail or "")[-800:],
        "n_deps": len(res.deps) if res.deps else 0,
        "deps": res.deps,
        "log": str(res.log_path) if res.log_path else None,
        **prep,
    }
    ctx.emit_case({**_case_base(ctx, eng, main_rel, route_d), **rec})
    kstatus = v.status if v.status in VERDICT_MAP else "fail"
    out = {
        "status": kstatus,
        "metrics": {**base_metrics, **rec},
    }
    if kstatus in ("fail", "reject", "fault"):
        # 失败类终态给 errors[] 一行——sig 合成 cat:pay 供 triage。
        out["errors"] = [
            {"cat": str(cat or v.status or "fail"), "payload": str(pay or "")[:200]}
        ]
    return out


# ---------------------------------------------------------------- spec

spec = Spec(
    kind="compilebench",
    params={
        # 全 selector 族（fp=False）——只收窄执行集，不进指纹。
        "condition": Param(default="baseline", fp=False),
        "engines": Param(default="xelatex,tectonic", fp=False),
        "ids": Param(default="", fp=False),
        "only": Param(default="", fp=False),
        "n": Param(type=int, default=0, fp=False),
    },
    items=_items,
    select=_select,
    stages=[
        Stage(
            "cb_compile",
            _cb_compile,
            eval=True,  # 终态行进 eval_records 车道
            # 唯一字母表（含 fault、缺 dirty_pdf）——不为单点造预设。
            status_class={
                "ok": "terminal",  # 词表要求——fn 不返但下游 accept 参照
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
    eval=False,  # canon 闸必须过（manifest 混 archive 前缀旧式 id）
    same_id_serial=True,  # 同 paper 格共享 _texmf 冷沙箱——装包串行
    executor="thread",
    env_probes=["xelatex", "tectonic", "pdftotext"],
    code_deps=["src/texlate/compile", "src/texlate/latex"],
)
