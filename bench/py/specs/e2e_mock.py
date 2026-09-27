r"""e2e_mock — mock 翻译全链 e2e（B5-A，M0 出口判据语料面）。

``e2e_mock_bench.py`` 的 kernel spec 移植：每 paper × 每条件一格跑产品全链
``texlate.e2e/pipecore``——route → normalize → MockTranslator 翻译 → ctex
注入 → 编译 → judge → precheck→L2→fixloop 修复链。variant=cond 字面：

    base-xel  原样复制 → xelatex（"原文就挂" vs "管线引入" 归因臂）
    pipe-xel  mock 翻译全链 → xelatex
    pipe-tec  同上 → tectonic
    base-tec  归因补跑臂——同 run pipe-tec clean 时 skip 抑制
    pipeB-xel/tec  pipe + Mode B 幻觉破坏（~30% 块丢/造占位符，
                   校验链须 100% 捕获；门槛 escaped==0 ∧ dirty==0）
    pipeC-xel/tec  pipe + Mode C 位置扰动（~10% 占位符挪位，量化
                   splice 鲁棒性）

Mode B/C 注入件唯一事实源 = ``specs/_sabotage.py``（translators_bench 与
三测试文件同引）；本 spec 只消费其 ``SabotageTranslator/PerturbTranslator``
+ ``_seg_of/_dirty_hits`` 归因谓词。

结构与旧驱动的对应：

- items() = manifest∩湖可供应池 × 8 cond 全 frame——同 id 的 cond 序内
  ``pipe-tec`` 必在 ``base-tec`` 前（same_id_serial 组内保序是归因前提）。
  选择钮 ``conditions/layers/ids/only/n/seed`` 全走 select() 过滤。
- base-tec 归因：needs 跨 variant 不可表达 → fn 内查本 run
  ``(idc,-,-,pipe-tec,run)`` 的 cells 行：clean/ok→skip，其它终态→直跑
  （归因补跑），本 run 非终态（queued/在飞/error）→ error retriable
  待 resume 复查，本 run 无行（pipe-tec 不在 conditions）→ 直跑。
- status 映射逐字：verdict clean/partial/fail→同名终态；
  InjectRejectError→partial + reject_at=inject（不得变 reject）；
  route.reject 只落 metrics 不 gate（仍跑实证拒绝正确性）；
  find_main_tex=None→reject（旧为整行无 cond 键）；湖格取不出→skip。
- 隔离：``ctx.workspace()/cond`` 每格重打（跨 variant 共享面必须分
  目录+rmtree）；``ctx.src_path()`` 是 0444 湖投影只读面——拷字节经
  ``fsutil.copy_mutating``，投影树上写=改共享 inode 毒湖格。
- 报告面（matrix/summary/Mode B 门槛/Mode C 存活率）留 Wave-D 动词
  读 ledger 终态格——跨 id 聚合不能做成 stage。

PAUSE 只挡付费格，本 spec 无 paid stage 照跑（tectonic bundle 拉取与
precheck scan_install 的网络/系统副作用在付费闸定义外——登记非阻塞）。
"""

from __future__ import annotations

import functools
import os
import random
import shutil
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from kernel import events, fsutil, idnorm, lake
from kernel.spec import EVAL_LAYERS, Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs._sabotage import (
    PerturbTranslator,
    SabotageTranslator,
    _dirty_hits,
    _seg_of,
)
from texlate import repair_l2 as repair_mod
from texlate.compile.engine import route_project
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.normalize import normalize_project
from texlate.e2e import base_condition, pipe_condition
from texlate.latex.placeholder import PH_RX
from texlate.pipecore import (
    PipeJob,
    RepairPolicy,
    baseline_snapshot,
    compile_judge_tail,
    delivered,
    probe_report,
    repair_chain,
    translate_tree_run,
)
from texlate.pipecore import (
    scan_tree as _scan_tree,
)
from texlate.repair import embed_tounicode_quiet
from texlate.textutil import env_flag
from texlate.validate.l0 import validate_pair

if TYPE_CHECKING:
    from texlate.xlat.pipeline import MockTranslator

ROOT = Path(__file__).resolve().parents[3]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))

EPOCH = "v1"

#: 条件轴——发射序即归因序：pipe-tec（idx2）必在 base-tec（idx3）前。
CONDS = (
    "base-xel",
    "pipe-xel",
    "pipe-tec",
    "base-tec",
    "pipeB-xel",
    "pipeB-tec",
    "pipeC-xel",
    "pipeC-tec",
)
DEFAULT_CONDITIONS = "base-xel,pipe-xel,pipe-tec,base-tec"

#: catalog 中「自带或可免费自愈字节」的态（soak/compilebench 同口径）。
_HYDRATABLE = frozenset({"hydrated", "pinned", "raw_only"})

#: cells 终态域——DONE ∪ KERNEL（dedup/claimed 等内核终态同算落地）。
_TERMINAL = events.STATUS_DONE | getattr(events, "STATUS_KERNEL", frozenset())

# ---------------------------------------------------------------- items/select


def _pool() -> dict:
    """manifest∩湖可供应格——compilebench 同谓词（stub/n_tex=0 滤、
    EVAL_LAYERS 滤、failed/empty/skeleton 出池）。"""
    cat = lake.LakeCatalog.load()
    out: dict[str, dict] = {}
    for mp in sorted(CORPUS.glob("manifest*.jsonl")):
        for r in benchlib.iter_jsonl(mp):
            pid = r.get("id")
            if not pid or pid in out:
                continue
            if r.get("layer") in EVAL_LAYERS:
                continue
            if r.get("format") == "stub" or not r.get("n_tex"):
                continue
            res = idnorm.canon_id(str(pid))
            idc = res.idc if res.ok and res.idc else str(pid)
            st = cat.state(idc)
            if st in _HYDRATABLE:
                ok = True
            elif st in ("failed", "empty"):
                ok = False
            else:
                ok = lake.is_complete(idc)
            if not ok:
                continue
            out[pid] = {
                "id": pid,
                "idc": idc,
                "layer": r.get("layer"),
                "cat_group": r.get("cat_group"),
                "fp_input": r.get("blob_sha256") or r.get("main_tex_sha256"),
            }
    return out


def _items() -> list[dict]:
    """全 frame：每 paper 连续发 8 cond 格（paper-major——同 idc 格相邻，
    same_id_serial 组内按发射序串行，pipe-tec→base-tec 序在此保证）。"""
    out: list[dict] = []
    for pid in sorted(_pool()):
        p = _pool()[pid]
        out.extend(
            {
                "id": pid,
                "variant": cond,
                "layer": p["layer"],
                "cat_group": p["cat_group"],
                "fp_input": p["fp_input"],
            }
            for cond in CONDS
        )
    return out


@functools.cache
def _canon(raw: str):
    return idnorm.canon_id(str(raw))


def _sample_idcs(
    pool: dict, layers: set[str], needle: str, n: int, seed: int
) -> set[str]:
    """--n 湖内 seeded 抽 n 个 canon idc（池已过湖谓词，无需再滤）。"""
    cands = sorted(
        {
            p["idc"]
            for p in pool.values()
            if (not layers or str(p.get("layer") or "") in layers)
            and (not needle or needle in p["idc"])
        }
    )
    rng = random.Random(seed)
    return set(rng.sample(cands, min(n, len(cands))))


def _select(item: dict, rp: dict) -> bool:
    """G1 plan-filter：conditions（variant 门）→ ids 直选（bypass layers）
    → layers（缺省 core）→ only canon 子串 → n/seed 抽样。"""
    conds = {
        c.strip()
        for c in str(rp.get("conditions") or DEFAULT_CONDITIONS).split(",")
        if c.strip()
    }
    if str(item.get("variant")) not in conds:
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
    layers = {
        s.strip() for s in str(rp.get("layers") or "core").split(",") if s.strip()
    }
    if layers and str(item.get("layer") or "") not in layers:
        return False
    needle = ""
    only = str(rp.get("only") or "").strip()
    if only:
        r = _canon(only)
        needle = r.idc if r.ok and r.idc else only
        if needle not in idc:
            return False
    n = int(rp.get("n") or 0)
    if n > 0:
        seed = int(rp.get("seed") or 0)
        return idc in _sample_idcs(_pool(), layers, needle, n, seed)
    return True


# ---------------------------------------------------------------- Mode B/C 条件体
# （e2e_mock_bench.pipe_mode_condition 逐字移植；注入件在 _sabotage 单源）


def _translate_tree(root: Path, translator: MockTranslator, *, env_judge: bool = False):
    """``pipecore.translate_tree_run`` 薄壳 + 带出逐块 results（归因账本用）。

    scan_fn 透传 ``pipecore.scan_tree``（文件名四门单源）；validator 同产品
    臂 L0 ``validate_pair`` 全量规则。
    """
    return translate_tree_run(
        root,
        translator=translator,
        env_judge=env_judge,
        scan_fn=_scan_tree,
        validator=lambda s, z: validate_pair(s, z).feedback(),
    )


def _probe_flags_of(work: Path, main_rel: str) -> tuple[str, ...]:
    """probe_report 旗标投影——探针崩只空旗标返回，不阻塞编译。"""
    rep = probe_report(work, main_rel)
    return tuple(rep.flags) if rep is not None else ()


def _pipe_mode(
    work: Path,
    eng_name: str,
    main_rel: str,
    timeout: float,
    mode: str,
    *,
    env_judge: bool | None = None,
    l2_on: bool | None = None,
    fixloop_on: bool | None = None,
    l2_max_chunks: int = repair_mod.L2_MAX_CHUNKS,
    route_engines: list[str] | None = None,
) -> dict:
    """pipe_condition 变体：翻译层换 Mode B/C 破坏 translator，其余全链同
    产品臂。逐块结局归因账 verbatim（caught/recovered/escaped/dirty/armed
    /armed_zh/by_kind 或 moved/spliced/dropped）；编译尾段 =
    ``pipecore.repair_chain`` 同一条链，inject 拒绝同口径 partial。"""
    rec: dict = {"engine": eng_name}
    rec["normalize"] = normalize_project(work, eng_name, main_rel)
    tr = SabotageTranslator() if mode == "B" else PerturbTranslator()
    ej = (
        env_flag(repair_mod.ENV_ENV_JUDGE, default=False)
        if env_judge is None
        else env_judge
    )
    # baseline 快照在翻译写回前抓；_td 须活到修复链收敛——局部绑定持到
    # 函数返回即随帧清理，快照寿命=修复链全程。
    fl = RepairPolicy.resolve(fixloop_on=fixloop_on).fixloop
    _td = baseline_snapshot(work, enabled=fl)
    baseline_dir = Path(_td.name) / "base" if _td is not None else None
    stats, run, results = _translate_tree(work, tr, env_judge=ej)
    rec["translate"] = stats
    # 事件归因 → 逐块结局；env_judge 回落的块视同未进 splice（防 escaped 虚报）
    reverted = set(stats["env_judge"].get("reverted") or ())
    src_ph = lambda s: sorted(PH_RX.findall(s))  # noqa: E731
    ledger: dict = {"events": len(tr.events), "sabotaged": 0, "moved": 0}
    if mode == "B":
        ledger.update(
            {
                "caught": 0,
                "recovered": 0,
                "escaped": 0,
                "dirty": 0,
                "armed": 0,
                "armed_zh": 0,
                "escaped_ids": [],
                "escaped_detail": [],
                "dirty_ids": [],
                "dirty_detail": [],
                "armed_ids": [],
                "armed_detail": [],
                "by_kind": {},
            }
        )
    else:
        ledger.update({"spliced": 0, "dropped": 0})
    for r in results:
        # 交付谓词与 splice 同口径：delivered 放行 partial。
        is_delivered = delivered(r) and r.chunk_id not in reverted
        if mode == "B":
            # 内容通道度量按全 delivered 块记账：armed = src 自带签名；
            # dirty = zh 命中中 src 解释不了的签名（判定性 echo）。
            zh_hits = _dirty_hits(r.translation) if is_delivered else []
            src_legit = _dirty_hits(r.source) if is_delivered else []
            ambig = [s for s in zh_hits if s in src_legit]
            hits = [s for s in zh_hits if s not in src_legit]
            if src_legit:
                ledger["armed"] += 1
                ledger["armed_ids"].append(r.chunk_id)
                ledger["armed_zh"] += bool(ambig)
                ledger["armed_detail"].append(
                    {"chunk": r.chunk_id, "src_legit": src_legit, "ambig": ambig}
                )
            if hits:
                ledger["dirty"] += 1
                ledger["dirty_ids"].append(r.chunk_id)
                ledger["dirty_detail"].append(
                    {"chunk": r.chunk_id, "hits": hits, "ambig": ambig}
                )
        evs = [e for e in tr.events if _seg_of(r.source, e["seg"])]
        if not evs:
            continue
        ledger["sabotaged"] += 1
        ledger["moved"] += sum(e.get("moved", 0) for e in evs)
        if mode == "B":
            kinds = "+".join(sorted({e.get("kind", "?") for e in evs}))
            bk = ledger["by_kind"].setdefault(
                kinds,
                {"caught": 0, "recovered": 0, "escaped": 0, "dirty": 0, "armed": 0},
            )
            if is_delivered and src_legit:
                bk["armed"] += 1
            if is_delivered and hits:
                bk["dirty"] += 1
            if not is_delivered:
                ledger["caught"] += 1  # fault/skipped/env回落 → 原文回退
                bk["caught"] += 1
            elif src_ph(r.translation) != src_ph(r.source):
                ledger["escaped"] += 1
                bk["escaped"] += 1
                ledger["escaped_ids"].append(r.chunk_id)
                src_m, zh_m = (
                    Counter(src_ph(r.source)),
                    Counter(src_ph(r.translation)),
                )
                ledger["escaped_detail"].append(
                    {
                        "chunk": r.chunk_id,
                        "kinds": kinds,
                        "details": [e.get("detail") for e in evs],
                        "lost": sorted((src_m - zh_m).elements()),
                        "extra": sorted((zh_m - src_m).elements()),
                    }
                )
            else:
                ledger["recovered"] += 1
                bk["recovered"] += 1
        elif is_delivered:
            ledger["spliced"] += 1  # 挪位译文进了文档 → 编译判存活
        else:
            ledger["dropped"] += 1
    rec["sabotage"] = ledger
    try:
        rec["inject"] = prepare_chinese(work, main_rel)
    except InjectRejectError as e:
        # 与 pipe_condition 同口径：策略拒绝 → partial (F3), reject_at 审计
        rec["status"] = "partial"
        rec["reject_at"] = "inject"
        rec["verdict"] = {"status": "partial", "reasons": [e.reason]}
        return rec
    job = PipeJob(
        work,
        main_rel,
        eng_name,
        timeout,
        probe_flags=_probe_flags_of(work, main_rel),
    )
    # 0-chunk 主文档不期待 CJK（与 pipe_condition 同口径，F 桶假阳修）
    expect_cjk = stats.get("chunks") != 0
    tail, res = compile_judge_tail(job, expect_cjk=expect_cjk)
    rec.update(tail)

    if rec["status"] != "clean":
        # 修复链 = pipecore.repair_chain 单件（precheck → L2 回灌 →
        # fixloop，与 pipe_condition 同一条链）
        res = repair_chain(
            rec,
            job,
            run,
            res,
            expect_cjk=expect_cjk,
            l2_on=l2_on,
            fixloop_on=fl,
            l2_max_chunks=l2_max_chunks,
            route_engines=route_engines,
            baseline_dir=baseline_dir,
        )
    # ToUnicode 注入在修复链收敛之后（pipe_condition 同位）
    if res.has_pdf and res.pdf is not None:
        rec["tounicode_fonts"] = embed_tounicode_quiet(res.pdf)
    return rec


# ---------------------------------------------------------------- stage: run


def _sibling_status(ctx, variant: str):
    """本 run 内 (idc,arm,up,variant,run) 的 cells 终态——跨 variant 归因
    查询（needs 只查同键，base-tec 抑制只能靠它）。

    返回 (found_this_run, status_or_None)。
    """
    if ctx.index is None:
        return False, None
    row = ctx.index.last_cell(ctx.idc, ctx.arm, ctx.up, variant, "run")
    if row is None or row.get("last_run") != ctx.run:
        return False, None
    return True, row.get("status")


def _route_engines(p: dict) -> list[str] | None:
    raw = str(p.get("route_engines") or "").strip()
    if not raw:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()] or None


def _run(ctx):
    """单条件格：归因门 → src 投影 → route/find_main → 拷字节进
    workspace()/cond → cond 派发 → rec 全量进 metrics（>4KB 自动 $blob）。"""
    cond = ctx.variant
    p = ctx.params
    timeout = float(p.get("timeout") or 240.0)

    # base-tec 归因门（先查后投影——抑制路径零编译开销）：
    #   本 run pipe-tec clean/ok  → skip（旧口径「归因补跑」反面）
    #   本 run pipe-tec 其它终态  → 直跑（管线失败归因对照）
    #   本 run pipe-tec 非终态    → error retriable（queued/在飞/出错
    #                               不误判，resume 时复查秒收敛）
    #   本 run 无 pipe-tec 行      → 直跑（显式请求；conditions 未含）
    if cond == "base-tec":
        found, st = _sibling_status(ctx, "pipe-tec")
        if found and st in _TERMINAL:
            if st in ("clean", "ok"):
                ctx.emit(
                    {
                        "metrics": {
                            "cond": cond,
                            "epoch": EPOCH,
                            "suppressed_by": "pipe-tec",
                            "sibling_status": st,
                        }
                    }
                )
                return "skip"
        elif found:
            ctx.emit(
                {
                    "metrics": {
                        "cond": cond,
                        "epoch": EPOCH,
                        "deferred_on": "pipe-tec",
                        "sibling_status": st,
                    }
                }
            )
            return "error"

    src = ctx.src_path()
    if src is None:
        # 湖格取不出（池谓词后≈零触发）——湖缺口非稿件缺陷，skip
        # retriable 等 hydrate/restore 补齐（compilebench 同款 delta）。
        ctx.emit_note(f"{ctx.idc}: lake cell unavailable -> skip", level="warn")
        return "skip"

    route = route_project(src)
    route_d = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    base_metrics = {
        "cond": cond,
        "epoch": EPOCH,
        "layer": ctx.cell.get("layer"),
        "cat_group": ctx.cell.get("cat_group"),
        "route": route_d,
    }

    main = find_main_tex(src)
    if main is None:
        # 旧口径整行无 cond 键（矩阵 '·'）→ 新映射 reject 终态；route 段
        # 仍落 metrics 保可对照。
        sub = classify_no_main(src) or ""
        ctx.emit(
            {
                "metrics": {
                    **base_metrics,
                    "verdict": "no_main_tex",
                    "verdict_sub": sub,
                },
                "errors": [
                    {"code": "no_main_tex", "cat": "no_main_tex", "payload": sub}
                ],
            }
        )
        return "reject"
    main_rel = main.relative_to(src).as_posix()
    base_metrics["main"] = main_rel

    # 隔离工作区：workspace()/cond 每格 rmtree 重打 + 投影拷字节
    # （src_path 的 0444 硬链面绝不可原位写）。
    wroot = ctx.workspace() / cond
    if wroot.exists():
        shutil.rmtree(wroot)
    fsutil.copy_mutating(src, wroot)

    eng = "xelatex" if cond.endswith("xel") else "tectonic"
    kw = {
        "env_judge": p.get("env_judge"),
        "l2_on": p.get("l2_on"),
        "fixloop_on": p.get("fixloop_on"),
        "l2_max_chunks": int(p.get("l2_max_chunks") or repair_mod.L2_MAX_CHUNKS),
        "route_engines": _route_engines(p),
    }
    if cond.startswith("pipeB-"):
        rec = _pipe_mode(wroot, eng, main_rel, timeout, "B", **kw)
    elif cond.startswith("pipeC-"):
        rec = _pipe_mode(wroot, eng, main_rel, timeout, "C", **kw)
    elif cond.startswith("pipe"):
        rec = pipe_condition(wroot, eng, main_rel, timeout, **kw)
    else:
        rec = base_condition(wroot, eng, main_rel, timeout)

    # rec 全量进 metrics（route/main/layer 工程级键合流；>4KB 由 events
    # $blob 自动卸载到 derived/blobs）。
    status = rec.get("status") or ((rec.get("verdict") or {}).get("status")) or "error"
    out = {"metrics": {**base_metrics, **rec}}
    if status in ("fail", "reject", "partial"):
        reasons = (rec.get("verdict") or {}).get("reasons") or []
        payload = str(reasons[0] if reasons else "")[:400]
        cat = "inject" if rec.get("reject_at") == "inject" else "verdict"
        out["errors"] = [{"code": status, "cat": cat, "payload": payload}]
    ctx.emit(out)
    return status


# ---------------------------------------------------------------- spec

spec = Spec(
    kind="e2e_mock",
    params={
        "timeout": Param(float, default=240.0, fp=True),
        "env_judge": Param(bool, default=None, fp=True),
        "l2_on": Param(bool, default=None, fp=True),
        "fixloop_on": Param(bool, default=None, fp=True),
        "l2_max_chunks": Param(int, default=repair_mod.L2_MAX_CHUNKS, fp=True),
        "route_engines": Param(str, default="", fp=True),
        "conditions": Param(str, default=DEFAULT_CONDITIONS, fp=False),
        "layers": Param(str, default="core", fp=False),
        "ids": Param(str, default="", fp=False),
        "only": Param(str, default="", fp=False),
        "n": Param(int, default=0),
        "seed": Param(int, default=42),
    },
    items=_items,
    select=_select,
    freeze_plan=True,
    executor="thread",
    env_probes=["xelatex", "tectonic", "pdftotext"],
    code_deps=[
        "src/texlate/e2e.py",
        "src/texlate/pipecore.py",
        "src/texlate/compile",
        "src/texlate/xlat",
        "src/texlate/validate",
        "src/texlate/repair",
        "src/texlate/repair_l2.py",
        "src/texlate/latex",
        "src/texlate/textutil",
        "bench/py/specs/_sabotage.py",
    ],
    lake=True,
    prefetch=True,
    fetch_fn=None,
    lake_source="arxiv",
    same_id_serial=True,
    eval=False,
    stages=[
        Stage(
            "run",
            _run,
            status_class={
                "ok": "terminal",
                "clean": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
    ],
)
