#!/usr/bin/env python3
r"""e2e real bench — corpus_v3 抽样 → 真实网关翻译 → ctex 注入 → xelatex 编译基线。

docs/10 §B5 Mode B（真实翻译 E2E）。与 e2e_mock_bench 同产出契约
（results.json + matrix.md + summary.md），差异只在翻译器：
``XlatPipeline(GatewayTranslator(ChatClient))`` 打 3003 网关真模型，
其余 route → normalize → L0 校验 → splice → prepare_chinese → compile →
judge 全走 ``texlate.*`` 正式实现（``texlate.e2e.base_condition`` 复用，
pipe 条件因翻译是 async 在本文件内联同款流程）。

每工程条件：
  pipe-xel : copy → normalize → Gateway 翻译(L0 校验/retry 阶梯) → splice →
             prepare_chinese(ctex) → xelatex → judge(expect_cjk)
  pipe-fix : pipe-xel 产物树 copy → fixloop(xelatex usermode/TUNA/tlpdb 索引)
             → 救后 xelatex+judge 复判（默认 **仅当 pipe-xel fail 时补跑**——
             partial 已有 PDF，fixloop 的 halt_on_error 编译+树改写只会丢 PDF
             且救不了 warning 级判据，实测 partial→fail 回退；
             --fixloop always 全跑测幂等含 partial 回退率；inject reject
             不救——无 ctex 的 CJK 注定 fail）
  base-xel : 原样 copy → xelatex（默认 **仅当 pipe-xel 非 clean 时补跑**，
             归因"原文就挂 vs 管线引入"；--base always 可强制全跑）

抽样：`--seed` 对 corpus_v3 manifest.jsonl（core 层，1000 篇）有放回不放乱序
随机抽 `--n` 篇；`--layers core,booster` 可并入 booster 层
（manifest_booster.jsonl）。只收 `extracted/` 存在的条目。
断点续跑：StateStore 落 bench/work_e2ereal/_state/{sid}/（跨 copy 存活），
重跑同 id 自动续翻已完成 chunk；results.json 逐篇 merge。

用法:
  uv run python bench/py/e2e_real_bench.py --ids 0707.1206     # 单篇 smoke
  uv run python bench/py/e2e_real_bench.py --n 40 --seed 42    # 首轮样本
      [--model swe-2-medium] [--concurrency 10] [--timeout 240]
      [--time-budget 1800] [--base onfail|always|never]
      [--fixloop onfail|always|never] [--tag NAME]
产出: bench/results/e2e-real-<tag>-<date>/{results.json,matrix.md,summary.md,run_meta.json}
工作区: bench/work_e2ereal/{cond}/{safe_id}/ + _xlat_state/{safe_id}/（gitignored）
依赖: uv venv（httpx/typer）；xelatex；pdftotext（judge CJK 检查）；
      3003 网关（TEXLATE_GATEWAY_KEY 或 --api-key，默认见 -h）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: TEXLATE_SRC 可指向冻结快照目录（内含 texlate/ 包）——bench 期间 src/ 被
#: 其他代理实时改动时隔离用（NameError 半成品会污染整批 skip 记录）。
sys.path.insert(0, os.environ.get("TEXLATE_SRC", str(ROOT / "src")))

# fixloop 配方（TUNA 镜像钉 / usertree 三件套 / tlpdb 离线索引 / _NoSandbox）
# 单源复用 fixloop_bench——同目录脚本经 sys.path[0] 可 import，其模块级无 IO。
import fixloop_bench as _fl

from texlate.compile.engine import XelatexEngine, engine_for, route_project
from texlate.compile.fixloop import CaseSink, fixloop
from texlate.compile.inject import InjectRejectError, find_main_tex, prepare_chinese
from texlate.compile.judge import judge
from texlate.compile.normalize import normalize_project
from texlate.e2e import base_condition
from texlate.latex.api import parse_file, parse_tex
from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import reconstruct
from texlate.validate.l0 import validate_pair
from texlate.xlat.client import ChatClient
from texlate.xlat.pipeline import (
    ChunkIn,
    GatewayTranslator,
    PipelineConfig,
    XlatPipeline,
    chunk_to_in,
)
from texlate.xlat.state import StateStore

CORPUS = ROOT / "bench/corpus_v3"
WORK = ROOT / "bench/work_e2ereal"
STATE = WORK / "_xlat_state"
RESULTS_DIR_DEFAULT = "e2e-real"

#: 单篇可翻译总字符上限——超过记 skipped_oversize 不烧配额（B5 首轮保守闸）。
MAX_TOTAL_CHARS = 250_000


# ---------------------------------------------------------------- 启动自检
async def preflight() -> list[str]:
    """起 bench 前的一致性检查——0 网络，烧配额前拦下半成品源码树。

    2026-09-15 实证：`src/texlate/` 被并行代理 mid-refactor 时，l0/placeholders
    引用未定义名（``_no_comments``/``mask_comments``）——导入面正常但调用即
    NameError，整批 chunk 静默 skipped。模块在进程启动加载一次即冻结，
    因此"启动时全量导入 + 无网走一遍 mock 链"即可免疫运行期被改。
    """
    import importlib
    import pkgutil

    import texlate
    from texlate.xlat.pipeline import MockTranslator

    errs: list[str] = []
    for m in pkgutil.walk_packages(texlate.__path__, "texlate."):
        try:
            importlib.import_module(m.name)
        except Exception as e:
            errs.append(f"import {m.name}: {e!r}")

    try:
        scans = parse_tex(
            "\\documentclass{article}\n\\begin{document}\nHello world $x^2$.\n"
            "\\end{document}\n"
        )
        chunks = [
            chunk_to_in(c, chunk_id=f"0:{c.id}", ph_map=scans.ph_map)
            for c in scans.chunks
        ]
        pipe = XlatPipeline(
            MockTranslator(),
            validator=lambda s, z: validate_pair(s, z).feedback(),
        )
        results = await pipe.run(chunks)
        if any(r.status == "fault" for r in results):
            errs.append("mock chain: fault chunk in self-check")
    except Exception as e:
        errs.append(f"mock chain: {e!r}")
    return errs


# ---------------------------------------------------------------- 语料抽样
def load_manifest(layers: set[str]) -> list[dict]:
    """corpus_v3 manifest → [{id, layer, bytes}]；layer 缺失默认 core。"""
    out: list[dict] = []
    files = {"core": "manifest.jsonl", "booster": "manifest_booster.jsonl"}
    for layer in layers:
        fp = CORPUS / files.get(layer, f"manifest_{layer}.jsonl")
        if not fp.exists():
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            rec.setdefault("layer", layer)
            out.append(rec)
    return out


def pick_sample(entries: list[dict], n: int, seed: int) -> list[str]:
    """分层不区分地随机抽 n 个 id（extracted/ 存在）；返回排序后 id 列表。"""
    avail = [e["id"] for e in entries if (CORPUS / e["id"] / "extracted").is_dir()]
    avail = sorted(set(avail))
    rng = random.Random(seed)
    picked = rng.sample(avail, min(n, len(avail)))
    return sorted(picked)


def safe_id(rel: str) -> str:
    return rel.replace("/", "--")


# ---------------------------------------------------------------- 真实翻译
async def translate_tree(
    work: Path, translator: GatewayTranslator, state_dir: Path, cfg: PipelineConfig
) -> dict:
    """work 内全部 .tex → XlatPipeline(GatewayTranslator)+L0 → splice 写回。

    对齐 ``texlate.e2e.mock_translate_tree`` 的编排（chunk_id = file_idx:cid、
    reconstruct 回写、PH_RX 数残留），差异：async + StateStore 续跑 +
    per-status 统计 + 调用量/耗时计量。
    """
    scans = []
    chunks: list[ChunkIn] = []
    parse_fail: list[str] = []
    for f in sorted(work.rglob("*.tex")):
        try:
            res = parse_file(f, flatten=False)
        except Exception as e:
            parse_fail.append(f"{f.relative_to(work)}: {e!r:.120}")
            continue
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(
            chunk_to_in(c, chunk_id=f"{idx}:{c.id}", ph_map=res.ph_map)
            for c in res.chunks
        )

    stats: dict[str, int] = {
        "ok": 0,
        "partial": 0,
        "fault": 0,
        "skipped": 0,
        "attempts": 0,
        "batched": 0,
    }
    t0 = time.monotonic()
    state = StateStore(state_dir, model=translator.model)
    state_dir.mkdir(parents=True, exist_ok=True)
    pipe = XlatPipeline(
        translator,
        config=cfg,
        state=state,
        validator=lambda s, z: validate_pair(s, z).feedback(),
    )
    results = await pipe.run(chunks)
    translate_s = time.monotonic() - t0

    by_file: dict[int, dict[int, str]] = {}
    warn_kinds: dict[str, int] = {}
    for r in results:
        fidx, cid = (int(x) for x in r.chunk_id.split(":", 1))
        stats["attempts"] += r.attempts
        stats["batched"] += int(r.batched)
        if r.status in stats:
            stats[r.status] += 1
        else:
            stats["fault"] += 1
        if r.status == "ok" or (r.status == "partial" and r.translation):
            by_file.setdefault(fidx, {})[cid] = r.translation
        for w in r.warnings:
            key = w.split(":", 1)[0][:60]
            warn_kinds[key] = warn_kinds.get(key, 0) + 1
        if r.skip_reason:
            key = "skip:" + r.skip_reason.split(":", 1)[0][:60]
            warn_kinds[key] = warn_kinds.get(key, 0) + 1

    n_files = 0
    n_leftover = 0
    for idx, (f, res) in enumerate(scans):
        trans = by_file.get(idx)
        if not trans:
            continue
        zh = reconstruct(res, trans)
        f.write_text(zh, encoding="utf-8")
        n_files += 1
        n_leftover += len(PH_RX.findall(zh))

    return {
        "files": n_files,
        "chunks": len(chunks),
        **stats,
        "leftover_ph": n_leftover,
        "parse_fail": parse_fail,
        "warn_kinds": dict(sorted(warn_kinds.items())),
        "seconds": round(translate_s, 1),
        "src_chars": sum(len(c.content) for c in chunks),
    }


def _judge_dict(res, *, expect_cjk: bool) -> dict:
    """CompileResult → {compile, verdict, status}（同 e2e._compile_judge 形状）。"""
    v = judge(res, expect_cjk=expect_cjk)
    return {
        "compile": {
            "ok": res.ok,
            "timed_out": res.timed_out,
            "seconds": round(res.seconds, 2),
            "passes": res.passes,
            "rc": res.rc,
            "killed_signal": res.killed_signal,
            "pdf_bytes": res.pdf_bytes,
            "first_error": res.log.first_error,
        },
        "verdict": {
            "status": v.status,
            "reasons": v.reasons,
            "n_errors": v.n_errors,
            "category": v.category,
            "cjk_chars": v.cjk_chars,
            "missing_chars": v.missing_chars,
        },
        "status": v.status,
    }


def _compile_judge(
    work: Path, main_rel: str, timeout: float, *, expect_cjk: bool
) -> dict:
    """xelatex best-effort 编译 + judge。"""
    res = engine_for("xelatex", halt_on_error=False).compile(
        work, main_rel, timeout=timeout, sandbox=True
    )
    return _judge_dict(res, expect_cjk=expect_cjk)


async def pipe_xel_condition(
    src: Path,
    sid: str,
    main_rel: str,
    translator: GatewayTranslator,
    cfg: PipelineConfig,
    timeout: float,
) -> dict:
    """pipe-xel：copy → normalize → 真实翻译 → splice → ctex → xelatex → judge。"""
    work = WORK / "pipe-xel" / sid
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src, work)
    rec: dict[str, object] = {"engine": "xelatex"}
    rec["normalize"] = normalize_project(work, "xelatex", main_rel)
    rec["translate"] = await translate_tree(work, translator, STATE / sid, cfg)
    try:
        rec["inject"] = prepare_chinese(work, main_rel)
    except InjectRejectError as e:
        rec["status"] = "reject"
        rec["verdict"] = {"status": "reject", "reasons": [e.reason]}
        return rec
    rec.update(_compile_judge(work, main_rel, timeout, expect_cjk=True))
    return rec


def base_xel_condition(src: Path, sid: str, main_rel: str, timeout: float) -> dict:
    """base-xel：原样 copy → xelatex（复用 texlate.e2e.base_condition）。"""
    work = WORK / "base-xel" / sid
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src, work)
    return base_condition(work, "xelatex", main_rel, timeout)


def _want_fix(rec: dict, mode: str) -> bool:
    """pipe-xel verdict → 是否补跑 pipe-fix。

    onfail 只接 ``fail``：partial 已产出 PDF（warning 级判据——invalid_utf8/
    missing_chars 等非编译错误），fixloop 的 halt_on_error 引擎 + 树改写
    （vendored sty 隔离/tlmgr 装包）只会把 PDF 弄丢而救不了 warning——
    e2e-hotfix-smoke 实测 partial→fail 回退 2/3。reject 不救
    （inject 拒绝=无 ctex，CJK 注定 fail）。always=幂等/回退率探针。
    """
    v = (rec.get("pipe-xel") or {}).get("verdict", {}).get("status")
    if v is None or v == "reject" or mode == "never":
        return False
    return mode == "always" or v == "fail"


def pipe_fix_condition(
    src_work: Path, sid: str, main_rel: str, timeout: float, sink: CaseSink
) -> dict:
    """pipe-fix：pipe-xel 产物树 copy → fixloop(xelatex usermode) → 复判。

    fixloop 只管编译侧可修错误（missing_file/eps/syntax…）；救完统一再过
    halt_on_error=False compile + judge(expect_cjk)，与 pipe-xel/base-xel
    同 verdict 刻度可直读矩阵。texmf usertree 复用进复判编译——fixloop
    经 tlmgr 装的包只在 TEXMFHOME 里活着。
    """
    work = WORK / "pipe-fix" / sid
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src_work, work)
    texmf = WORK / "_texmf" / sid
    if texmf.exists():
        shutil.rmtree(texmf)  # 重跑从零冷启动，防半成品 usertree 偏暖
    _fl._init_usertree(texmf)
    eng = _fl._NoSandbox(
        XelatexEngine(halt_on_error=True, texmfhome=texmf, repository=_fl.TUNA_TLNET)
    )
    idx = _fl._index()
    if idx is not None:
        # 实例遮蔽 filemap：install_file 内部 self.filemap 调用也走索引
        eng.filemap = idx.query
    t0 = time.monotonic()
    try:
        cell = fixloop(
            work,
            eng,
            ruleset=_fl.RS,
            engine_name="xelatex",
            corpus_id=sid,
            cond="pipe-fix",
            runner=_fl._texmf_runner(texmf),
            case_sink=sink,
        )
    except Exception as e:  # 格子崩溃记 verdict 不炸整批（同 fixloop_bench）
        cell = {
            "project": sid,
            "engine": "xelatex",
            "verdict": f"harness_crash:{type(e).__name__}",
            "log_excerpt": str(e)[:500],
            "rounds": [],
            "actions": [],
        }
    cell["wall_s"] = round(time.monotonic() - t0, 1)
    rec: dict[str, object] = {"engine": "xelatex", "fixloop": cell}
    jeng = XelatexEngine(
        halt_on_error=False, texmfhome=texmf, repository=_fl.TUNA_TLNET
    )
    res = jeng.compile(work, main_rel, timeout=timeout, sandbox=False)
    rec.update(_judge_dict(res, expect_cjk=True))
    return rec


# ---------------------------------------------------------------- 单工程驱动
async def run_project(
    rel: str,
    translator: GatewayTranslator,
    cfg: PipelineConfig,
    timeout: float,
    base_mode: str,
    fixloop_mode: str,
    sink: CaseSink,
) -> dict:
    src = CORPUS / rel / "extracted"
    sid = safe_id(rel)
    rec: dict = {"id": rel}
    if not src.is_dir():
        rec["error"] = "no extracted/ dir"
        rec["status"] = "reject"
        return rec
    meta_p = CORPUS / rel / "meta.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
        rec["layer"] = meta.get("layer")
        rec["cat_group"] = meta.get("cat_group")
        rec["era"] = meta.get("era")
        rec["uncompressed_bytes"] = meta.get("uncompressed_bytes")
    main_path = find_main_tex(src)
    if main_path is None:
        rec["error"] = "no main tex"
        rec["status"] = "reject"
        return rec
    main_rel = main_path.relative_to(src).as_posix()
    rec["main"] = main_rel
    route = route_project(src)
    rec["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
    }
    if route.reject:
        rec["status"] = "reject"
        rec["base-xel"] = base_xel_condition(src, sid, main_rel, timeout)
        return rec

    t0 = time.monotonic()
    rec["pipe-xel"] = await pipe_xel_condition(
        src, sid, main_rel, translator, cfg, timeout
    )
    rec["seconds"] = round(time.monotonic() - t0, 1)
    rec["status"] = rec["pipe-xel"].get("status")

    want_base = base_mode == "always" or (
        base_mode == "onfail"
        and rec["pipe-xel"].get("verdict", {}).get("status") != "clean"
    )
    if want_base:
        rec["base-xel"] = base_xel_condition(src, sid, main_rel, timeout)
    if _want_fix(rec, fixloop_mode):
        rec["pipe-fix"] = pipe_fix_condition(
            WORK / "pipe-xel" / sid, sid, main_rel, timeout, sink
        )
    return rec


def _paper_done(rec: dict | None) -> bool:
    """results.json 里该篇是否算「完成」（bench 级续跑谓词）。

    与 ``XlatPipeline._load_resumed`` 同口径——``skipped``/``fault`` 是可重试类
    （draining 窗口的传输失败、阶梯三振），``bench_error`` 是执行中断，三种都得
    重进让 chunk 级 state 决定重翻谁；静态 reject/oversize 与全块 ok/partial
    才算终态。
    """
    if not isinstance(rec, dict) or not rec.get("status"):
        return False
    if rec["status"] == "bench_error":
        return False
    tr = (rec.get("pipe-xel") or {}).get("translate") or {}
    return not (tr.get("skipped") or tr.get("fault"))


# ---------------------------------------------------------------- 报告
def _v(rec: dict, cond: str) -> str:
    c = rec.get(cond)
    if c is None:
        return "·"
    return c.get("verdict", {}).get("status", "?")


def _tr(rec: dict) -> str:
    t = rec.get("pipe-xel", {}).get("translate")
    if not t:
        return "·"
    return f"{t['ok']}/{t['chunks']} ph:{t['leftover_ph']}"


def write_reports(results: dict, out_dir: Path, meta: dict) -> None:
    rows = []
    for rel, rec in sorted(results.items()):
        rows.append(
            (
                rel,
                rec.get("layer") or "?",
                rec.get("main", "?"),
                "reject" if rec.get("route", {}).get("reject") else "",
                _tr(rec),
                _v(rec, "pipe-xel"),
                _v(rec, "pipe-fix"),
                _v(rec, "base-xel"),
            )
        )
    matrix = [
        "| 工程 | 层 | main | 路由 | translate(ok/chunks leftover) | pipe-xel | pipe-fix | base-xel |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    matrix.extend("| " + " | ".join(str(x) for x in r) + " |" for r in rows)
    (out_dir / "matrix.md").write_text("\n".join(matrix) + "\n", encoding="utf-8")

    # ---- summary：分环节通过率 + 失败模式分类 ----
    lines = [
        f"# e2e real bench — {meta.get('model')}",
        "",
        f"- 样本: {len(results)} 篇（seed={meta.get('seed')} layers={meta.get('layers')}）",
        f"- 网关: {meta.get('base_url')} model={meta.get('model')}",
        "",
        "## 环节通过率",
    ]
    ran_pipe = [r for r in results.values() if r.get("pipe-xel")]
    n_tr = sum(1 for r in ran_pipe if r["pipe-xel"].get("translate", {}).get("chunks"))
    tot_chunks = sum(r["pipe-xel"]["translate"].get("chunks", 0) for r in ran_pipe)
    ok_chunks = sum(r["pipe-xel"]["translate"].get("ok", 0) for r in ran_pipe)
    ph = sum(r["pipe-xel"]["translate"].get("leftover_ph", 0) for r in ran_pipe)
    ph_bad = {
        rel: r["pipe-xel"]["translate"]["leftover_ph"]
        for rel, r in sorted(results.items())
        if r.get("pipe-xel") and r["pipe-xel"]["translate"].get("leftover_ph", 0) > 0
    }
    lines.append(f"- 翻译执行（chunks>0）: {n_tr}/{len(ran_pipe)} 篇")
    lines.append(
        f"- chunk 终态: ok {ok_chunks}/{tot_chunks}"
        f" · partial {sum(r['pipe-xel']['translate'].get('partial', 0) for r in ran_pipe)}"
        f" · fault {sum(r['pipe-xel']['translate'].get('fault', 0) for r in ran_pipe)}"
        f" · skipped {sum(r['pipe-xel']['translate'].get('skipped', 0) for r in ran_pipe)}"
    )
    lines.append(
        f"- splice 残留占位符: {ph}（应为 0）— gate "
        + ("PASS" if not ph_bad else f"**FAIL** {ph_bad}")
    )
    for cond in ("pipe-xel", "pipe-fix", "base-xel"):
        ran = [r[cond] for r in results.values() if r.get(cond)]
        if not ran:
            continue
        tally: dict[str, int] = {}
        for r in ran:
            s = r.get("verdict", {}).get("status", "?")
            tally[s] = tally.get(s, 0) + 1
        lines.append(
            f"- **{cond}**: "
            + " ".join(f"{k} {v}" for k, v in sorted(tally.items()))
            + f" /{len(ran)}"
        )

    ran_fix = [
        (rel, r["pipe-fix"]) for rel, r in sorted(results.items()) if r.get("pipe-fix")
    ]
    if ran_fix:
        rescued = [rel for rel, f in ran_fix if f.get("status") == "clean"]
        partial = [rel for rel, f in ran_fix if f.get("status") == "partial"]
        fl_tally: dict[str, int] = {}
        for _, f in ran_fix:
            fv = (f.get("fixloop") or {}).get("verdict") or "?"
            fl_tally[fv] = fl_tally.get(fv, 0) + 1
        lines.append(
            f"- **pipe-fix 救回**: clean {len(rescued)} · partial {len(partial)}"
            f" /{len(ran_fix)}（fixloop 内部 verdict: "
            + " ".join(f"{k} {v}" for k, v in sorted(fl_tally.items()))
            + "）"
        )
        # 回退检测：fixloop 的 halt_on_error 编译对 warning 级 partial 可能
        # 反向（原 best-effort 出 pdf → 修后无 pdf），union 口径取较好者。
        rank = {"clean": 0, "partial": 1, "fail": 2, "reject": 3, "?": 4}
        regressed = [
            rel
            for rel, f in ran_fix
            if rank.get(f.get("status") or "?", 4)
            > rank.get(
                (results[rel].get("pipe-xel") or {}).get("verdict", {}).get("status")
                or "?",
                4,
            )
        ]
        if regressed:
            lines.append(f"- **pipe-fix 回退**（比 pipe-xel 差）: {regressed}")

    lines += ["", "## 失败模式（pipe-xel verdict.reasons 计数）"]
    rcount: dict[str, int] = {}
    cats: dict[str, int] = {}
    for rec in results.values():
        v = rec.get("pipe-xel", {}).get("verdict", {})
        if v.get("status") in (None, "clean"):
            continue
        for reason in v.get("reasons") or []:
            key = str(reason).split("(")[0].split(":")[0][:60]
            rcount[key] = rcount.get(key, 0) + 1
        cat = v.get("category")
        if cat:
            cats[cat] = cats.get(cat, 0) + 1
    for k, c in sorted(rcount.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {k}: {c}")
    if cats:
        lines.append(
            "- first_error 类别: "
            + ", ".join(
                f"{k}×{v}" for k, v in sorted(cats.items(), key=lambda kv: -kv[1])
            )
        )

    introduced = [
        rel
        for rel, rec in sorted(results.items())
        if rec.get("pipe-xel", {}).get("verdict", {}).get("status")
        not in (None, "clean")
        and rec.get("base-xel", {}).get("verdict", {}).get("status") == "clean"
    ]
    lines += ["", f"- pipe-xel 非 clean 且 base-xel clean（管线引入）: {introduced}"]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- main
async def amain(args: argparse.Namespace) -> None:
    out_dir = ROOT / "bench/results" / f"{args.tag}-{args.date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    results = json.loads(out_path.read_text()) if out_path.exists() else {}

    entries = load_manifest(set(args.layers.split(",")))
    if args.ids:
        ids = sorted({i.strip() for i in args.ids.split(",") if i.strip()})
    else:
        ids = pick_sample(entries, args.n, args.seed)
    if args.only:
        ids = [i for i in ids if args.only in i]
    print(f"sample n={len(ids)} seed={args.seed} layers={args.layers}", flush=True)

    if not args.no_preflight:
        errs = await preflight()
        if errs:
            print("preflight FAILED — 源码树不一致，拒绝起 bench:", flush=True)
            for e in errs:
                print(f"  {e}", flush=True)
            return
        print("preflight ok", flush=True)

    meta = {
        "seed": args.seed,
        "layers": args.layers,
        "n_requested": args.n,
        "model": args.model,
        "base_url": args.base_url,
        "concurrency": args.concurrency,
        "timeout": args.timeout,
        "time_budget": args.time_budget,
        "base_mode": args.base,
        "fixloop_mode": args.fixloop,
        "sample_ids": ids,
        "started_at": datetime.now(UTC).isoformat(),
    }
    (out_dir / "run_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    cfg = PipelineConfig(concurrency=args.concurrency)
    sink = CaseSink(out_dir / "cases.jsonl")
    async with ChatClient(args.base_url, args.api_key) as client:
        if not args.no_probe:
            probe = await client.probe_model(args.model)
            print(
                f"probe {args.model}: ok={probe.probe_ok} "
                f"lat={probe.probe_latency_s}s err={probe.probe_error}",
                flush=True,
            )
            if not probe.probe_ok:
                print("model probe failed — abort", flush=True)
                return
        translator = GatewayTranslator(client, args.model)

        t_start = time.monotonic()
        for idx, rel in enumerate(ids):
            prev = results.get(rel)
            if not args.rerun and _paper_done(prev):
                # pipe-xel 工作区仍在 → 旧结果可只补 fixloop 臂，不重翻
                src_work = WORK / "pipe-xel" / safe_id(rel)
                if (
                    _want_fix(prev, args.fixloop)
                    and "pipe-fix" not in prev
                    and src_work.is_dir()
                    and prev.get("main")
                ):
                    prev["pipe-fix"] = pipe_fix_condition(
                        src_work,
                        safe_id(rel),
                        prev["main"],
                        args.timeout,
                        sink,
                    )
                    out_path.write_text(
                        json.dumps(results, ensure_ascii=False, indent=1),
                        encoding="utf-8",
                    )
                    write_reports(results, out_dir, meta)
                    print(
                        f"===== [{idx}/{len(ids)}] {rel} cached; pipe-fix "
                        f"backfill -> {prev['pipe-fix'].get('status')}",
                        flush=True,
                    )
                else:
                    print(
                        f"===== [{idx}/{len(ids)}] {rel} cached -> {prev['status']}",
                        flush=True,
                    )
                continue
            print(f"===== [{idx}/{len(ids)}] {rel}", flush=True)
            try:
                rec = await run_project(
                    rel,
                    translator,
                    cfg,
                    args.timeout,
                    args.base,
                    args.fixloop,
                    sink,
                )
            except Exception as e:
                rec = {"id": rel, "status": "bench_error", "error": repr(e)[:400]}
            if rel in results and isinstance(results[rel], dict):
                results[rel].update(rec)
            else:
                results[rel] = rec
            out_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            write_reports(results, out_dir, meta)
            t = rec.get("pipe-xel", {}).get("translate", {})
            print(
                f"  -> status={rec.get('status')} "
                f"tr={t.get('ok', '-')}/{t.get('chunks', '-')} "
                f"pipe={_v(rec, 'pipe-xel')} fix={_v(rec, 'pipe-fix')} "
                f"base={_v(rec, 'base-xel')} "
                f"({rec.get('seconds', '-')}s)",
                flush=True,
            )
            if time.monotonic() - t_start > args.time_budget:
                print(
                    f"time budget {args.time_budget}s reached — stopping "
                    f"({idx + 1}/{len(ids)} done)",
                    flush=True,
                )
                break
    print(f"done -> {out_dir}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40, help="sample size")
    ap.add_argument("--seed", type=int, default=42, help="sampling seed")
    ap.add_argument(
        "--layers", default="core", help="core / core,booster / core,booster,hot"
    )
    ap.add_argument("--ids", default=None, help="explicit comma-separated ids (smoke)")
    ap.add_argument("--only", default=None, help="substring filter on sampled ids")
    ap.add_argument("--model", default="swe-2-medium")
    ap.add_argument("--base-url", default="http://127.0.0.1:3003")
    ap.add_argument(
        "--api-key",
        default="240127",
        help="gateway bearer key（默认本机 3003 开发 key）",
    )
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=240.0, help="compile timeout")
    ap.add_argument(
        "--time-budget",
        type=float,
        default=1800.0,
        help="总时长闸（秒）：超时即停，写部分结果",
    )
    ap.add_argument(
        "--base",
        choices=["onfail", "always", "never"],
        default="onfail",
        help="base-xel 归因条件何时跑",
    )
    ap.add_argument(
        "--fixloop",
        choices=["onfail", "always", "never"],
        default="onfail",
        help="pipe-fix 救回臂何时跑（onfail=pipe-xel fail 才救；partial 不救——"
        "fixloop 对 warning 级判据无能为力且 halt_on_error 会丢已有 PDF）",
    )
    ap.add_argument("--no-probe", action="store_true", help="跳过模型探活")
    ap.add_argument(
        "--no-preflight",
        action="store_true",
        help="跳过启动自检（全量 import + mock 链）",
    )
    ap.add_argument("--rerun", action="store_true", help="无视 results.json 重跑")
    ap.add_argument("--tag", default=RESULTS_DIR_DEFAULT)
    ap.add_argument("--date", default=str(datetime.now(UTC).date()))
    args = ap.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
