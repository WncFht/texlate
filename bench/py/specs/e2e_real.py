r"""e2e_real — real-arm 全链路付费评测（Phase-4 Wave-C）。

``bench/py/e2e_real_bench.py`` 的 spec 化：route → xlat(paid) → compile →
fixloop → base 五段链。与 soak（生产主线）是同构兄弟——soak 走
ingest→parse→xlat→compile→fixloop 的资产流，本 spec 是旧 B5 驱动的
逐格平移，条件臂落为独立 stage 而非 rec 键：

- route   ：src 物化 → find_main_tex → route_project（meta 四键+frame sha
  进 metrics）。无 extracted/无 main/路由拒绝 → ``reject`` +
  ``metrics.reject_at='route'``（旧 ``partial+reject_at`` 折叠为 terminal
  reject——reject_at provenance 进 metrics 保留报表口径）。
- xlat    ：paid。fn 头 ``vault.restore`` 水合 ``state.-``（chunk 断点
  升格——旧 ``work_e2ereal/_xlat_state/`` 全局目录的 vault 形态）；
  copy→normalize→``translate_tree_async``（SessionClient 桥 PaidSession，
  fn 内 ``asyncio.run``——单 thread executor 下不得让 async cell 分波）→
  swap_in ``zh.-`` + ``state.-``。stats→status：oversize→reject；
  leftover_ph>0→fail；fault|skipped>0→error（retriable——``_paper_done``
  的坏块重译语义；「全坏」被本支吞掉属刻意，旧谓词同样重试）；
  partial|fault_files>0→partial；else ok。
- compile ：needs xlat {ok,partial}。zh.- → splice.- → prepare_chinese
  （InjectRejectError→reject+reject_at='inject'）→ xelatex best-effort +
  judge(expect_cjk=translate.chunks!=0——0-delivered 篇目同口径 False)。
- fixloop ：**needs-free 收割汇**——on={compile:…} 只给 topo 边不给闸
  （``_needs_eval`` 只迭代 needs）。末段 mutates 格恒到达 DONE 才能恒
  harvest：xlat/compile 半途死掉的篇目 zh.-/state.- 不困死 work/（soak
  的 needs={clean,partial}+on={fail,dirty_pdf} 在 compile=reject 时
  needs-skip → 付费字节滞留 work/ 只能等 sweep/adopt——本 spec 不复制
  该洞）。fn 内三段闸：route DONE≠ok → reject+gate='route_dead'；
  compile 无 DONE 账且 xlat DONE∈{fail,reject} → reject+gate=
  'no_compile'（链永死）；compile 无 DONE 账但上游仍在 flux → error
  retriable（续跑重评，不提前固化 decline）；compile DONE →
  ``_want_fix`` 谓词，decline→reject+gate='not_wanted'（报告侧按
  gate 分桶，非真 reject）。跑则 copy splice → 冷 usertree+TUNA+
  tlpdb fixloop → 复判 → 修复树 swap 回 splice.-。
- base    ：needs route {ok,reject}（路由拒绝篇也跑归因臂）。topo 序
  base 先于 xlat（Kahn 字母 ready 队列：indeg-0 集合 route 之后
  {base,xlat} 按字典序 base 先）——同 run 内 upstream_rec('xlat')
  恒 None，onfail 抑制只能靠跨 run 账（_last_done 全域）：oversize→
  reject+gate='oversize'、compile clean→reject+gate='compile_clean'；
  无账照跑=onfail→always 的文档化漂移（base 编译免费，宁多勿缺）。

语义决策点（相对旧驱动的漂移，全部有意）：

- ``--time-budget`` 墙钟保险丝 kernel 无等价物——弃参，run 级中止走
  kernel abort/PAUSE 面。
- ``--fixloop-llm`` 付费面：llm_hook 使 fixloop 变付费，而 paid 是静态
  旗标——本 spec 恒 ``llm_hook=None``（fixloop 非 paid 格），付费修复
  臂归 sibling spec（e2e-fixllm），不在本文件。
- ``--rerun``/``--recode``：由 kernel dedup/regen + code_deps/freeze_plan
  覆盖（fp 漂移即重排），无 spec 参数。
- ``--no-preflight``：源码树自检是 run 级前奏非 cell 语义，env_probes
  管二进制在场；弃参。
- probe：``session.probe_model()`` 对 GatewayChat 是无线调用真值返回
  （无 probe_model attr）——nonstream 502 事故面不触线；真实探活由
  401-breaker（PAPER_401_LIMIT=3/RUN_ALL_FAILED_LIMIT=2≡旧
  AUTH_DEAD_STREAK=2）承担。
- items=冻结帧 ``bench/nominations/e2e_real_frame.jsonl``（bake 锁死
  样本集=旧 run_meta.sample_ids 防漂移语义）；``--ids``/``--only``
  窄化经 select()。帧 sha 经 route metrics.frame 留痕（不进 cell
  键域——帧改版不烧付费 dedup）。
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# src/ 不在 `bench` 入口的 sys.path 上（kernel 惰性 import texlate.*）——
# specs/_sabotage.py 同款自举；TEXLATE_SRC 冻结快照语义一致。
sys.path.insert(
    0,
    os.environ.get(
        "TEXLATE_SRC", str(Path(__file__).resolve().parents[3] / "src")
    ),
)

from kernel import events, fsutil, idnorm, vault
from kernel import paid as paidmod
from kernel.spec import Param, Spec, Stage

from specs import _benchlite as benchlib
from specs import _fixloop as flb  # 冷 usertree 引擎配方单源
from specs._shared import (
    DEFAULT_MODEL,
    PaidEscape,
    SessionClient,
    TimedTranslator,
    devin_factory,
)
from specs._xlat_async import translate_tree_async
from texlate.compile.engine import XelatexEngine, engine_for, route_project
from texlate.compile.fixloop import CaseSink, Ruleset, fixloop
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.normalize import normalize_project
from texlate.e2e import base_condition
from texlate.pipecore import scan_tree as _scan_tree
from texlate.validate.l0 import validate_pair
from texlate.xlat.pipeline import (
    AuthTrippedError,
    GatewayTranslator,
    PipelineConfig,
)

ROOT = Path(__file__).resolve().parents[3]

#: 冻结抽样帧——benchlib.pick_sample 等价口径（seed=42 n=40）烘于
#: 2026-09-23，抽样池=非 eval 层∧湖可水化格∧有源指纹
#: （blob_sha256|main_tex_sha256 非空——无 fp 的 cell 输入同一性无从钉；
#: 旧 core 层 manifest 的 extracted 已清盘，帧池即当前 dev 可用集
#: 682 格）。帧即锁：同帧重跑样本集逐 id 相等（旧 run_meta.sample_ids
#: 防漂移语义）。
FRAME = ROOT / "bench" / "nominations" / "e2e_real_frame.jsonl"

#: 测量世代——forever-dedup 下换代靠变体升档而非 rerun 旗标。
EPOCH = "v1"

#: 付费臂名——与 mock 兄弟臂/soak 生产臂隔开 (idc,arm,variant) vault+claim
#: 键域（soak 用 '-' 默认臂，本 spec 恒 'real'）。
ARM = "real"

_DONE_STS = tuple(sorted(events.STATUS_DONE))

#: IN 位串只插占位符个数（模块级常量）——值仍全参数化。
_LAST_DONE_SQL = (
    "SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"  # noqa: S608
    "fp,dur_s,metrics,errors,ts FROM records "
    "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=? "
    f"AND status IN ({','.join('?' * len(_DONE_STS))}) "
    "ORDER BY rowid DESC LIMIT 1"
)


def _last_done(ctx, stage: str) -> dict | None:
    """末条 DONE 账·跨全 run——``_needs_eval`` 的 dedup-look-through 同域。

    ``ctx.upstream_rec`` 是 run∪foreign_runs 域：run2 里 run1 的账出域
    （本 run 那行是 dedup 非 DONE）——want_fix/want_base/expect_cjk 这些
    「上游账」判读必须读全域，否则跨 run 续跑全部看成 None 走歪。
    """
    idx = ctx.index
    if idx is None:
        return None
    row = idx.conn.execute(
        _LAST_DONE_SQL,
        (ctx.idc, ctx.arm, ctx.up, ctx.variant, stage, *_DONE_STS),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for col in ("metrics", "errors"):
        v = d.get(col)
        if isinstance(v, str):
            with contextlib.suppress(ValueError):
                d[col] = json.loads(v)
        d[col] = ctx._unblob(d[col])
    return d


def _gate(status: str, code: str, cat: str, payload,
          metrics: dict | None = None) -> dict:
    """stagerun gate_rec 的 return-dict 版（soak 同式）：status + 单条
    errors + 可选 metrics；sig 由内核 errors[0] cat:pay 自动合成。"""
    out = {
        "status": status,
        "code": code,
        "errors": [{"code": code, "cat": cat, "payload": payload}],
    }
    if metrics:
        out["metrics"] = metrics
    return out


def _swap_in(stage_dir: Path, dst: Path) -> None:
    """暂存树 → dst 的 rename 接力（stagerun_lib.swap_in 同式）。"""
    old = stage_dir.with_name(f"{stage_dir.name}-old")
    if dst.exists():
        if old.exists():
            shutil.rmtree(old)
        os.rename(dst, old)
    os.rename(stage_dir, dst)
    if old.exists():
        shutil.rmtree(old)


def _ensure_kind(ctx, kind: str) -> Path | None:
    """本 run 的 mutates-kind 读径（soak 同式）：同 run 上游产物优先，
    缺席则 vault restore(mode="copy") 物化全部已封 kind——0444 融合树的
    可写副本口径。无完好 vault 副本 → None。"""
    d = ctx.upstream_asset_dir(kind)
    if d is not None:
        return d
    with contextlib.suppress(vault.VaultError):
        vault.restore(ctx.idc, ctx.arm, ctx.variant, ctx.paper_dir(),
                      mode="copy")
    return ctx.upstream_asset_dir(kind)


def _xlat_marker(zh: Path) -> dict | None:
    """``zh.-/.xlat-arm.json`` → dict；缺席 → None。"""
    p = zh / ".xlat-arm.json"
    if not zh.is_dir() or not p.exists():
        return None
    try:
        doc = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return doc if isinstance(doc, dict) else None


# ---------------------------------------------------------------- items/select


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@functools.cache
def _frame_sha() -> str:
    """帧 sha 缓存——route metrics.frame 的 provenance 戳（不进 cell
    键域，帧改版只改戳不烧 dedup）。"""
    return _sha256(FRAME)[:12] if FRAME.is_file() else "absent"


def _items() -> list[dict]:
    """冻结帧 items——compile_checks 物化一次。帧缺席=空（eval 帧是
    opt-in 工件，不是硬依赖）；行自带 id/layer/cat_group/era/bytes/
    fp_input，arm/variant 由本函数盖章（帧只管选样不管键域）。"""
    if not FRAME.is_file():
        return []
    rows: list[dict] = []
    for row in benchlib.iter_jsonl(FRAME):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        rows.append(
            {
                "id": str(row["id"]),
                "layer": row.get("layer"),
                "cat_group": row.get("cat_group"),
                "era": row.get("era"),
                "bytes": row.get("bytes"),
                "fp_input": row.get("fp_input"),
                "arm": ARM,
                "variant": EPOCH,
            }
        )
    return rows


@functools.cache
def _canon(raw: str):
    return idnorm.canon_id(str(raw))


def _select(item: dict, rp: dict) -> bool:
    """G1 plan-filter：--ids 直选（canon 双拼写+cat 别名折叠归一）→
    --only canon 子串——旧驱动 --ids/--only 窄化的 run 级等价物。"""
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
        return needle in idc
    return True


# ---------------------------------------------------------------- stage: route


def _route(ctx) -> dict:
    """src 物化 → find_main_tex → route_project；meta 四键+main_rel+帧戳
    进 metrics（下游经 _last_done 读）。三拒一律 reject+reject_at='route'。"""
    cell = ctx.cell
    metrics: dict = {
        "layer": cell.get("layer"),
        "cat_group": cell.get("cat_group"),
        "era": cell.get("era"),
        "bytes": cell.get("bytes"),
        "frame": f"frm-{_frame_sha()}",
    }
    src = ctx.src_path()
    if src is None:
        metrics["reject_at"] = "route"
        return _gate("reject", "no_extracted", "route",
                     "lake cell unfetchable", metrics)
    main = find_main_tex(src)
    if main is None:
        sub = classify_no_main(src)
        metrics["reject_at"] = "route"
        metrics["no_main_sub"] = sub
        return _gate("reject", "no_main_tex", "route", sub or "", metrics)
    main_rel = main.relative_to(src).as_posix()
    metrics["main_rel"] = main_rel
    route = route_project(src)
    metrics["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    if route.reject:
        metrics["reject_at"] = "route"
        return _gate("reject", "route_reject", "route", route.reject,
                     metrics)
    return {"status": "ok", "metrics": metrics}


# ---------------------------------------------------------------- stage: xlat


def _xlat(ctx) -> dict:
    """暂存翻译 → zh.-/state.-；chunk 断点经 vault.restore 水合续跑。

    旧 ``pipe_xel_condition`` 的翻译段（copy→normalize→translate_tree），
    splice 写回在 translate_tree_async 内部完成；ctex 注入与编译判分在
    下游 compile stage。stats→status 映射见模块 docstring——
    fault|skipped>0 → error(retriable) 保 _paper_done 坏块重译语义。
    """
    paper = ctx.paper_dir()
    # 断点水合：state.-（及同凭证 zh/splice）从 vault 最优副本物化——
    # 缺席即 VaultError 静默，fresh 起步。restore 先于 asset_dir，让
    # StateStore 直接吃到旧 chunk 账。
    with contextlib.suppress(vault.VaultError):
        vault.restore(ctx.idc, ctx.arm, ctx.variant, paper, mode="copy")
    state_dir = ctx.asset_dir("state")

    src = ctx.src_path()
    if src is None:
        return _gate("error", "no_extracted", "upstream",
                     "lake cell unfetchable post-route")
    rrec = _last_done(ctx, "route") or {}
    main_rel = (rrec.get("metrics") or {}).get("main_rel")
    staging = paper / ".xlat-stage"
    if staging.exists():
        shutil.rmtree(staging)
    fsutil.copy_mutating(src, staging)
    if not main_rel:
        found = find_main_tex(staging)
        if found is None:
            return _gate("error", "no_main_tex", "upstream",
                         classify_no_main(staging) or "")
        main_rel = found.relative_to(staging).as_posix()

    metrics: dict = {"main_rel": main_rel, "engine": "xelatex"}
    metrics["normalize"] = normalize_project(staging, "xelatex", main_rel)

    session = ctx.gateway()
    if not ctx.params.get("no_probe"):
        session.probe_model()  # GatewayChat 无 probe_model → 门检后即 True
    client = SessionClient(session)
    translator = TimedTranslator(
        GatewayTranslator(client, str(ctx.params["model"]))
    )
    cfg = PipelineConfig(concurrency=int(ctx.params["concurrency"]))
    try:
        stats, results = asyncio.run(
            translate_tree_async(
                staging,
                translator,
                state_dir,
                cfg,
                oversize_cap=int(ctx.params["oversize_cap"]),
                scan_fn=_scan_tree,
                validator=lambda s, z: validate_pair(s, z).feedback(),
            )
        )
    except PaidEscape as e:
        # 拆舱：mid-flight 付费族异常原样交内核映射——绝不落成终态假账。
        raise e.orig from e
    except AuthTrippedError as e:
        # 篇内连续 auth-fail 熔断 = 凭证死透——PaidAbortCell 映
        # fail+auth_dead+auth_tripped。
        msg = f"{ctx.idc}: auth circuit tripped ({e})"
        raise paidmod.PaidAbortCell(msg) from e

    # req_timing 三分拆（soak 同口径注记：chat_s 含 paid_slot 排队）。
    stats["req_timing"] = {
        "calls": translator.calls,
        "chat_calls": client.chat_calls,
        "chat_s": round(client.chat_s, 1),
        "backoff_s": round(max(0.0, translator.span_s - client.chat_s), 1),
        "sem_wait_s": 0.0,
        "span_s": round(translator.span_s, 1),
    }
    metrics["translate"] = stats

    if stats.get("oversize"):
        shutil.rmtree(staging, ignore_errors=True)
        metrics["reject_at"] = "xlat"
        return _gate(
            "reject", "oversize", "xlat",
            f"src_chars={stats['src_chars']}", metrics,
        )

    # 逐块明细随 state.- 进 vault（triage/契约审计原料）。
    detail = state_dir / "xlat-detail.jsonl"
    with detail.open("w", encoding="utf-8") as fh:
        for r in results:
            benchlib.write_jsonl(
                fh,
                {
                    "chunk_id": r.chunk_id,
                    "status": r.status,
                    "attempts": r.attempts,
                    "batched": r.batched,
                    "skipped": r.fell_back,
                    "error_kind": r.error_kind,
                    "skip_reason": r.skip_reason,
                    "warnings": r.warnings,
                },
            )

    n_bad = stats["fault"] + stats["skipped"]
    if stats["leftover_ph"] > 0:
        shutil.rmtree(staging, ignore_errors=True)
        return _gate("fail", "leftover_ph", "xlat",
                     str(stats["leftover_ph"]), metrics)
    if n_bad:
        # retriable——坏块账在 state.-，续跑只重翻 fault/skipped 块
        # （_paper_done 同口径；「全坏」被本支吞掉属刻意：旧谓词同样
        # 重试，而 chunk state 让重试不重烧已成交块）。
        return _gate(
            "error", "chunks_retriable", "xlat",
            f"fault={stats['fault']} skipped={stats['skipped']}", metrics,
        )
    # 树可交付（ok/partial 路径）才落 zh.- + marker。
    (staging / ".xlat-arm.json").write_text(
        json.dumps(
            {
                "arm": ctx.arm,
                "model": str(ctx.params["model"]),
                "ts": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
    )
    zh = ctx.asset_dir("zh")
    _swap_in(staging, zh)
    if stats["partial"] or stats["fault_files"]:
        return _gate(
            "partial", "chunks_partial", "xlat",
            f"partial={stats['partial']} fault_files={stats['fault_files']}",
            metrics,
        )
    return {"status": "ok", "metrics": metrics}


# ---------------------------------------------------------------- stage: compile


def _compile_judge(
    work: Path, main_rel: str, timeout: float, *, expect_cjk: bool
) -> dict:
    """xelatex best-effort 编译 + judge（旧 _compile_judge 同式）。"""
    res = engine_for("xelatex", halt_on_error=False).compile(
        work, main_rel, timeout=timeout, sandbox=True
    )
    return benchlib.judge_dict(res, expect_cjk=expect_cjk)


def _compile(ctx) -> dict:
    """zh.- → splice.- → inject → xelatex+judge（旧 pipe_xel_condition
    的 inject+compile 段）。expect_cjk 读 xlat 账 translate.chunks。"""
    metrics: dict = {"engine": "xelatex"}
    zh = _ensure_kind(ctx, "zh")
    marker_doc = _xlat_marker(zh) if zh is not None else None
    if marker_doc is None:
        return _gate("skip", "not_translated", "upstream",
                     "zh.- missing or no .xlat-arm.json", metrics)
    metrics["xlat_ts"] = marker_doc.get("ts")
    splice = ctx.asset_dir("splice")
    if splice.exists():
        shutil.rmtree(splice)
    fsutil.copy_mutating(zh, splice)
    rrec = _last_done(ctx, "route") or {}
    main_rel = (rrec.get("metrics") or {}).get("main_rel")
    if not main_rel:
        found = find_main_tex(splice)
        if found is None:
            return _gate("reject", "no_main_tex", "compile",
                         classify_no_main(splice) or "", metrics)
        main_rel = found.relative_to(splice).as_posix()
    metrics["main_rel"] = main_rel
    timeout = float(ctx.params["timeout"])
    try:
        metrics["inject"] = prepare_chinese(splice, main_rel)
    except InjectRejectError as e:
        metrics["verdict"] = {"status": "reject", "reasons": [e.reason]}
        metrics["reject_at"] = "inject"
        return _gate("reject", "inject_reject", "inject", e.reason, metrics)
    # 0-delivered 篇目不期待 CJK（旧 chunks!=0 怪癖逐字保留）；xlat 账
    # 缺席（dedup 底账在前 run 经 _last_done 全域读到）保守 True。
    xr = _last_done(ctx, "xlat")
    _tr = ((xr or {}).get("metrics") or {}).get("translate") or {}
    expect_cjk = _tr.get("chunks") != 0
    metrics["expect_cjk"] = expect_cjk
    tail = _compile_judge(splice, main_rel, timeout, expect_cjk=expect_cjk)
    metrics.update(tail)
    v = tail["verdict"]
    out = {"status": v["status"], "metrics": metrics,
           "sig": benchlib.verdict_sig(v, tail["compile"].get("first_error"))}
    if v["status"] not in ("clean", "partial"):
        out["errors"] = [
            {
                "code": v.get("category") or "compile_fail",
                "cat": v.get("category"),
                "payload": v.get("payload"),
            }
        ]
    elif v.get("category"):
        out["errors"] = [
            {
                "code": v["category"],
                "cat": v["category"],
                "payload": v.get("payload"),
            }
        ]
    return out


# ---------------------------------------------------------------- stage: fixloop


class _CaseBridge(CaseSink):
    """CaseSink → ctx.emit_case 桥（soak 同款）：record 行形状逐字进
    cases 账道；文件落点 /dev/null（ledger+cases.jsonl 由内核原子写，
    双重落盘只会留两份漂移面——旧 _dedup_cases 末行胜去重由账道末行胜
    天然覆盖）。"""

    def __init__(self, ctx) -> None:
        super().__init__(os.devnull)
        self._ctx = ctx

    def record(self, cell, **kw):
        rec = super().record(cell, **kw)
        self._ctx.emit_case(rec)
        return rec


def _want_fix(mode: str, compile_status, verdict: dict, reject_at) -> bool:
    """旧 ``_want_fix`` 谓词的 status 面平移：mode=never/verdict None/
    reject/reject_at → False；always|fail → True；partial 且
    (misschar_partial 或 n_errors>0) → True。

    旧读 ``rec['pipe-xel'].verdict.status``；v2 读 compile 账 metrics
    （verdict+reject_at 同位——inject 拒绝走 reject_at='inject' 不救，
    无 ctex 的 CJK 注定 fail）。
    """
    v = compile_status
    if v is None or v == "reject" or reject_at or mode == "never":
        return False
    if mode == "always" or v == "fail":
        return True
    return v == "partial" and (
        benchlib.misschar_partial(v, verdict)
        or (verdict.get("n_errors") or 0) > 0
    )


def _fixloop(ctx) -> dict:
    """needs-free 收割汇：fn 内三段闸（route_dead / no_compile / flux）
    后再 _want_fix 谓词——decline 一律 reject+gate 分桶（DONE 触发
    §3.5 harvest，上游付费字节封 vault 不滞留 work/）。

    旧 ``pipe_fix_condition``：copy splice → 冷 usertree fixloop
    （halt_on_error=True + tlpdb 影子 + _NoSandbox + TUNA runner）→
    halt_on_error=False 复判 → 修复树 swap 回 splice.-。llm_hook 恒
    None（付费面归 sibling spec——paid 是静态旗标）。
    """
    t0 = time.monotonic()
    mode = str(ctx.params.get("fixloop") or "onfail")

    def _decline(gate: str, extra: dict | None = None) -> dict:
        return {
            "status": "reject",
            "sig": f"declined:{gate}",
            "metrics": {
                "gate": gate,
                "mode": mode,
                "fixloop_ran": False,
                **(extra or {}),
            },
        }

    # 上游账三段闸——needs-free 格的恒久性判读全在 fn 内：
    rr = _last_done(ctx, "route")
    if rr is not None and rr.get("status") != "ok":
        return _decline("route_dead", {"route_status": rr.get("status")})
    comp_rec = _last_done(ctx, "compile")
    if comp_rec is None:
        xr = _last_done(ctx, "xlat")
        if xr is not None and xr.get("status") in {"fail", "reject"}:
            # 链永死（xlat 终态败 → compile 永不立账）——收割 state.-。
            return _decline("no_compile", {"xlat_status": xr.get("status")})
        # 上游仍在 flux（error/skip 可续）——retriable 不固化 decline。
        return _gate("error", "compile_flux", "upstream",
                     "no DONE compile row; upstream still in flight")
    cm = comp_rec.get("metrics") or {}
    cst = comp_rec.get("status")
    if not _want_fix(mode, cst, cm.get("verdict") or {},
                     cm.get("reject_at")):
        return _decline("not_wanted", {"compile_status_before": cst})

    splice_src = _ensure_kind(ctx, "splice")
    if splice_src is None:
        return _gate("skip", "no_splice", "upstream",
                     "splice.- missing post-compile")
    metrics: dict = {"mode": mode, "fixloop_ran": True,
                     "compile_status_before": cst}
    work = ctx.paper_dir() / ".pipe-fix"
    if work.exists():
        shutil.rmtree(work)
    fsutil.copy_mutating(splice_src, work)
    main_rel = cm.get("main_rel")
    if not main_rel:
        found = find_main_tex(work)
        if found is None:
            return _gate("error", "no_main_tex", "fixloop",
                         classify_no_main(work) or "", metrics)
        main_rel = found.relative_to(work).as_posix()
    metrics["main_rel"] = main_rel

    texmf = ctx.paper_dir() / "_texmf"
    if texmf.exists():
        shutil.rmtree(texmf)  # 冷启动——防半成品 usertree 偏暖
    eng = flb._make_engine("xelatex", texmf, work)
    # baseline_dir 逐格注入（soak 同式）——restore_support_from_src/
    # slot_arg_revert 需要 src/ 原件树。
    src = ctx.src_path()
    rs = flb.RS
    if src is not None and src.is_dir():
        rs = Ruleset.load()
        for rule in rs.rules:
            act = rule.raw.get("action") or {}
            if act.get("kind") == "builtin_transform" and act.get(
                "function"
            ) in {"restore_support_from_src", "slot_arg_revert"}:
                act.setdefault("params", {})["baseline_dir"] = str(src)
    timeout = float(ctx.params["timeout"])
    try:
        cell = fixloop(
            work,
            eng,
            ruleset=rs,
            engine_name="xelatex",
            main_rel=main_rel,
            corpus_id=ctx.idc,
            cond="pipe-fix",
            runner=flb._texmf_runner(texmf),
            case_sink=_CaseBridge(ctx),
            llm_hook=None,  # 付费面归 sibling spec（paid 静态旗标）
            compile_timeout=timeout,
        )
        crashed = False
    except PaidEscape as e:
        raise e.orig from e  # 拆舱交内核——harness_crash 兜底绝不收付费族
    except Exception as e:  # 格子崩溃记 verdict 不炸整批（旧同式）
        cell = {
            "project": ctx.idc,
            "engine": "xelatex",
            "verdict": f"harness_crash:{type(e).__name__}",
            "log_excerpt": str(e)[:500],
            "rounds": [],
            "actions": [],
        }
        crashed = True
    cell_wall = round(time.monotonic() - t0, 1)
    # 复判：texmf usertree 复用（fixloop 装的包只在 TEXMFHOME 里活着）
    # ——旧驱动恒 fresh-compile 复判（不用 soak 的 ResProxy fix_last 捷
    # 径，保驱动口径）。
    jeng = XelatexEngine(
        halt_on_error=False, texmfhome=texmf, repository=flb.TUNA_TLNET
    )
    res = jeng.compile(work, main_rel, timeout=timeout, sandbox=False)
    expect_cjk = cm.get("expect_cjk", True)
    tail = benchlib.judge_dict(res, expect_cjk=expect_cjk)

    rounds = cell.get("rounds") or []
    fv = str(cell.get("verdict") or "?")
    fcat, fpay = benchlib.fixloop_attr(rounds, fv, cell.get("final_cat"))
    v = tail["verdict"]
    tail["regressed"] = benchlib.STATUS_RANK.get(
        str(v["status"] or ""), -1
    ) < benchlib.STATUS_RANK.get(str(cst or ""), -1)
    metrics.update(
        {
            "fixloop_verdict": fv,
            "final_cat": fcat,
            "rounds": len(rounds),
            "n_actions": len(cell.get("actions") or []),
            "rules_fired": list(
                dict.fromkeys(
                    str(a["rule"]) for a in (cell.get("actions") or [])
                    if a.get("rule")
                )
            ),
            "gate_fired": list(cell.get("gate_fired") or []),
            "installed": cell.get("installed") or [],
            "floor_restored": bool(cell.get("floor_restored")),
            "fixloop_wall_s": cell_wall,
            "post": tail,
        }
    )
    # 修复树（含 harness_crash 的半修态）swap 回 splice.-——末段 mutates
    # 格，harvest 以本 stage DONE 把 zh/state/splice 一并封 vault。
    splice = ctx.asset_dir("splice")
    _swap_in(work, splice)
    if crashed:
        return {
            "status": "fail",
            "sig": benchlib.fixloop_sig(fv, fcat, fpay),
            "metrics": metrics,
            "errors": [{"code": fv, "cat": fcat, "payload": fpay}],
        }
    out = {"status": v["status"], "metrics": metrics,
           "sig": benchlib.fixloop_sig(fv, fcat, fpay)}
    if v["status"] != "clean":
        out["errors"] = [{"code": fv, "cat": fcat, "payload": fpay}]
    return out


# ---------------------------------------------------------------- stage: base


def _base(ctx) -> dict:
    """base-xel 归因臂（旧 base_xel_condition）：src 原样直编。

    onfail 抑制只读跨 run 账（同 run topo 序 base 先于 xlat——无账照跑
    =onfail→always 的文档化漂移）：xlat oversize 或 compile clean →
    reject+gate 分桶。"""
    mode = str(ctx.params.get("base") or "onfail")
    metrics: dict = {"mode": mode, "engine": "xelatex"}
    if mode == "never":
        return {"status": "reject", "sig": "declined:base_never",
                "metrics": {**metrics, "gate": "base_never"}}
    if mode == "onfail":
        xr = _last_done(ctx, "xlat")
        tr = ((xr or {}).get("metrics") or {}).get("translate") or {}
        if tr.get("oversize"):
            return {"status": "reject", "sig": "declined:oversize",
                    "metrics": {**metrics, "gate": "oversize"}}
        cr = _last_done(ctx, "compile")
        cv = ((cr or {}).get("metrics") or {}).get("verdict") or {}
        if cv.get("status") == "clean":
            return {"status": "reject", "sig": "declined:compile_clean",
                    "metrics": {**metrics, "gate": "compile_clean"}}

    src = ctx.src_path()
    if src is None:
        return _gate("error", "no_extracted", "upstream",
                     "lake cell unfetchable", metrics)
    rrec = _last_done(ctx, "route") or {}
    main_rel = (rrec.get("metrics") or {}).get("main_rel")
    main = find_main_tex(src)
    if main is None:
        return {"status": "reject", "sig": "declined:no_main_tex",
                "metrics": {**metrics, "gate": "no_main_tex",
                            "no_main_sub": classify_no_main(src)}}
    if not main_rel:
        main_rel = main.relative_to(src).as_posix()
    metrics["main_rel"] = main_rel
    work = ctx.paper_dir() / "build-base"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src, work, ignore=benchlib.copytree_ignore())
    rec = base_condition(work, "xelatex", main_rel,
                         float(ctx.params["timeout"]))
    metrics.update(rec)
    v = rec.get("verdict") or {}
    out = {"status": v.get("status") or "fail", "metrics": metrics,
           "sig": benchlib.verdict_sig(
               v, (rec.get("compile") or {}).get("first_error"))}
    if v.get("status") not in ("clean", "partial"):
        out["errors"] = [
            {
                "code": v.get("category") or "compile_fail",
                "cat": v.get("category"),
                "payload": v.get("payload"),
            }
        ]
    return out


# ---------------------------------------------------------------- spec


spec = Spec(
    kind="e2e_real",
    params={
        "ids": Param(str, default="", fp=False),
        "only": Param(str, default="", fp=False),
        "model": Param(str, default=DEFAULT_MODEL, fp=True),
        "concurrency": Param(int, default=10, fp=True),
        "timeout": Param(float, default=240.0, fp=True),
        "oversize_cap": Param(int, default=benchlib.MAX_TOTAL_CHARS,
                              fp=True),
        "base": Param(str, default="onfail",
                      choices=["always", "onfail", "never"], fp=True),
        "fixloop": Param(str, default="onfail",
                         choices=["always", "onfail", "never"], fp=True),
        "no_probe": Param(bool, default=False, fp=False),
    },
    items=_items,
    select=_select,
    freeze_plan=True,
    executor="thread",
    env_probes=["xelatex", "tlmgr", "pdftotext"],
    code_deps=[
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
            status_class={
                "ok": "terminal",
                "reject": "terminal",
                "error": "retriable",
            },
        ),
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
            status_class={
                "ok": "terminal",
                "clean": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "dirty_pdf": "terminal",
                "skip": "upstream",
                "error": "retriable",
            },
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
                "compile": {"clean", "partial", "fail", "reject",
                            "dirty_pdf"},
            },
            mutates=["splice"],
            status_class={
                "ok": "terminal",
                "clean": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "dirty_pdf": "terminal",
                "skip": "upstream",
                "error": "retriable",
            },
        ),
        Stage(
            "base",
            _base,
            needs=[("route", {"ok", "reject"})],
            status_class={
                "ok": "terminal",
                "clean": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "dirty_pdf": "terminal",
                "error": "retriable",
            },
        ),
    ],
)
