#!/usr/bin/env python3
r"""e2e real bench — corpus 抽样 → 真实网关翻译 → ctex 注入 → xelatex 编译基线。

docs/spec/benchmark.md §B5 Mode B（真实翻译 E2E）。与 e2e_mock_bench 同产出契约
（results.json + matrix.md + summary.md），差异只在翻译器：
``XlatPipeline(GatewayTranslator(ChatClient))`` 打 3033 网关真模型，
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

抽样：`--seed` 对 corpus manifest.jsonl（core 层，1000 篇）有放回不放乱序
随机抽 `--n` 篇；`--layers core,booster` 可并入 booster 层
（manifest_booster.jsonl）。只收 `extracted/` 存在的条目。
断点续跑：StateStore 落 bench/work_e2ereal/_state/{sid}/（跨 copy 存活），
重跑同 id 自动续翻已完成 chunk；records.jsonl 逐篇 append（行在=done、
末行胜），results.json 整格替换快照（原子写）节流至每 ≥8 篇/≥30s 一刷
+ 收尾强刷，兼容旧消费方。

LEGACY（wave2-findings #2 + refactor-audit ★6 定调）：批式真网关跑批已归
``stagerun`` 分阶段管线（stage_xlat --arm real → stage_compile →
stage_fixloop，同 judge+flb 配方、判分同义）；本文件保留 lib 面
（``preflight``/``pick_sample``/``load_manifest`` 均为 benchlib 薄委托）
与单篇全链冒烟位（``--ids`` 一把梭仍是最短路径），新批量测量一律走
stagerun。

用法:
  uv run python bench/py/e2e_real_bench.py --ids 0707.1206     # 单篇 smoke
  uv run python bench/py/e2e_real_bench.py --n 40 --seed 42    # 首轮样本
      [--model swe-2-medium] [--concurrency 10] [--timeout 240]
      [--time-budget 1800] [--base onfail|always|never]
      [--fixloop onfail|always|never] [--tag NAME]
      [--rerun 全量重跑 | --recode 产码印章不符的格重跑（splice 修复验证）]
产出: bench/results/e2e-real-<tag>-<date>/{records.jsonl,results.json,matrix.md,summary.md,run_meta.json}
工作区: bench/work_e2ereal/{cond}/{safe_id}/ + _xlat_state/{safe_id}/（gitignored）
依赖: uv venv（httpx/typer）；xelatex；pdftotext（judge CJK 检查）；
      3033 网关（TEXLATE_GATEWAY_KEY 或 --api-key，默认见 -h）。
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import re
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parents[2]
#: TEXLATE_SRC 可指向冻结快照目录（内含 texlate/ 包）——bench 期间 src/ 被
#: 其他代理实时改动时隔离用（NameError 半成品会污染整批 skip 记录）。
sys.path.insert(0, os.environ.get("TEXLATE_SRC", str(ROOT / "src")))

# fixloop 配方（TUNA 镜像钉 / usertree 三件套 / tlpdb 离线索引 / _NoSandbox）
# 单源复用 fixloop_bench——同目录脚本经 sys.path[0] 可 import，其模块级无 IO。
import benchlib
import fixloop_bench as _fl

# 编排单源：translate_tree 委托 stage_xlat.translate_tree_async。
# TEXLATE_SRC 冻结快照语义不靠本处序位：stagerun_lib/e2e_mock_bench 在
# stage_xlat 链内各自 sys.path.insert(TEXLATE_SRC)，texlate 包一经落地
# __path__ 即钉快照侧——链中 texlate.* 子模块全部同源。
import stage_xlat

from texlate.compile.engine import XelatexEngine, engine_for, route_project
from texlate.compile.fixloop import CaseSink, fixloop
from texlate.compile.fixloop.llm_hook import make_llm_hook
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
from texlate.xlat.client import ChatClient
from texlate.xlat.pipeline import (
    AuthTrippedError,
    GatewayTranslator,
    PipelineConfig,
)

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import LlmHook

CORPUS = ROOT / "bench/corpus"
WORK = ROOT / "bench/work_e2ereal"
STATE = WORK / "_xlat_state"
RESULTS_DIR_DEFAULT = "e2e-real"

#: 单篇可翻译总字符上限——超过记 skipped_oversize 终态不烧配额
#:（B5 首轮保守闸；translate 记录带 oversize=True，base/fix 臂不补跑）。
#: 单源 ``benchlib.MAX_TOTAL_CHARS``（★6 下沉；stagerun real 臂同闸）。
MAX_TOTAL_CHARS = benchlib.MAX_TOTAL_CHARS

#: 连续「全 auth 败」论文数熔断阈值——凭证中途死透时停跑不空烧
#:（probe 只探开局；篇内 3 连熔断由 AuthTrippedError 即停，本闸兜的是
#: 篇均不足阈值块、逐篇全 401 的慢速失血）。单源 ``benchlib.AUTH_DEAD_STREAK``。
_AUTH_DEAD_STREAK = benchlib.AUTH_DEAD_STREAK


# ---------------------------------------------------------------- 启动自检
async def preflight() -> list[str]:
    """起 bench 前的一致性检查——0 网络，烧配额前拦下半成品源码树。

    单源 ``benchlib.preflight``（★6 下沉——实现与迁移前逐字同；delegate
    保 realn200 restart-safe：重启进程 import 本模块拿到的语义不变）。
    """
    return await benchlib.preflight()


# ---------------------------------------------------------------- 语料抽样
def load_manifest(layers: set[str]) -> list[dict]:
    """corpus manifest → [{id, layer, bytes}]；layer 缺失默认所在层。"""
    return benchlib.load_manifest_rows(CORPUS, sorted(layers))


def pick_sample(entries: list[dict], n: int, seed: int) -> list[str]:
    """分层不区分地随机抽 n 个 id（extracted/ 存在）；返回排序后 id 列表。

    单源 ``benchlib.pick_sample``（★6 下沉——corpus 参数由本模块 CORPUS 注入，
    抽样序与旧实现逐项同）。
    """
    return benchlib.pick_sample(entries, CORPUS, n, seed)


safe_id = benchlib.safe_id


# ---------------------------------------------------------------- 真实翻译
async def translate_tree(
    work: Path, translator: GatewayTranslator, state_dir: Path, cfg: PipelineConfig
) -> dict:
    """work 内可译 .tex → XlatPipeline(GatewayTranslator)+L0 → splice 写回。

    编排单源 ``stage_xlat.translate_tree_async``（扫描 → oversize 闸 →
    StateStore → XlatPipeline → 逐块对账 → reconstruct 写回），本函数只剩
    注入面 + results 丢弃。相对旧就地副本收编两处漂移：交付谓词
    ``pipecore.delivered``（``ok``+空译不回填 splice）与畸形 chunk_id 的
    ValueError 守备（记 fault+bad_chunk_id 不炸整篇）。stats 键面与旧
    副本逐字一致（含 ``auth_all_failed``/oversize 闸两键）。

    扫描段经 ``scan_fn=_scan_tree`` 显式传本模块全局（monkeypatch 缝保活），
    四门口径（dotfile/``.rtx.tex``/``.code.tex``/无散文 support_files）
    与 e2e/mock 臂同 ``pipecore.scan_tree`` 单源不漂移。
    """
    stats, _results = await stage_xlat.translate_tree_async(
        work,
        translator,
        state_dir,
        cfg,
        oversize_cap=MAX_TOTAL_CHARS,
        scan_fn=_scan_tree,
        validator=lambda s, z: validate_pair(s, z).feedback(),
    )
    return stats


def _compile_judge(
    work: Path, main_rel: str, timeout: float, *, expect_cjk: bool
) -> dict:
    """xelatex best-effort 编译 + judge。"""
    res = engine_for("xelatex", halt_on_error=False).compile(
        work, main_rel, timeout=timeout, sandbox=True
    )
    return benchlib.judge_dict(res, expect_cjk=expect_cjk)


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
    if rec["translate"].get("oversize"):
        rec["status"] = "skipped_oversize"
        return rec
    try:
        rec["inject"] = prepare_chinese(work, main_rel)
    except InjectRejectError as e:
        # F3: 策略拒绝 → partial + reject_at 审计（与 e2e.py 同形）
        rec["status"] = "partial"
        rec["reject_at"] = "inject"
        rec["verdict"] = {"status": "partial", "reasons": [e.reason]}
        return rec
    # 0-chunk 主文档 (includepdf 壳) 不期待 CJK 渲染 (F 桶假阳修)
    rec.update(
        _compile_judge(
            work, main_rel, timeout, expect_cjk=rec["translate"].get("chunks") != 0
        )
    )
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

    onfail 接 ``fail`` + 缺字 ``partial``：其余 partial 已产出 PDF
    （warning 级判据——invalid_utf8 等非编译错误），fixloop 的 halt_on_error
    引擎 + 树改写（vendored sty 隔离/tlmgr 装包）只会把 PDF 弄丢而救不了
    warning——e2e-hotfix-smoke 实测 partial→fail 回退 2/3。例外是
    missing_chars>0：F4 的 warn_missing_char/missing_char_fix 专打这一类
    （零 `!` 错误也驱动修复轮）。reject 不救（inject 拒绝=无 ctex，CJK 注定
    fail）。always=幂等/回退率探针。
    """
    verdict = (rec.get("pipe-xel") or {}).get("verdict", {})
    v = verdict.get("status")
    reject_at = (rec.get("pipe-xel") or {}).get("reject_at")
    if v is None or v == "reject" or reject_at or mode == "never":
        # v=="reject" 仅兼容 F3 前旧结果文件；新数据走 reject_at 判定
        return False
    if mode == "always" or v == "fail":
        return True
    # error 级 partial（n_errors>0 = 带 `!` 错也出了 PDF）是 fixloop 最可能
    # 救回的对象——1e 语义查实：原门槛把它与 warning 级 partial 混同排除，
    # 且 hotfix-smoke 的 2/3 回退率测于底板（floor_restored）落地之前。
    # misschar 支走单源 benchlib.misschar_partial（与 stagerun._on_misschar 同核）。
    return v == "partial" and (
        benchlib.misschar_partial(v, verdict) or (verdict.get("n_errors") or 0) > 0
    )


def pipe_fix_condition(
    src_work: Path,
    sid: str,
    main_rel: str,
    timeout: float,
    sink: CaseSink,
    llm_hook: LlmHook | None = None,
    *,
    expect_cjk: bool = True,
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
            llm_hook=llm_hook,
            compile_timeout=timeout,
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
    # 同 (corpus,cond) 重跑会让 cases.jsonl 追加双行，而消费端 load_cases/
    # triage 不去重（scout-e2ereal §5）——写侧按「末行胜」物理去重保持
    # artifact 干净，覆盖一切 pipe-fix 调用点（含 amain cached 补臂）。
    _dedup_cases(sink.path)
    rec: dict[str, object] = {"engine": "xelatex", "fixloop": cell}
    jeng = XelatexEngine(
        halt_on_error=False, texmfhome=texmf, repository=_fl.TUNA_TLNET
    )
    res = jeng.compile(work, main_rel, timeout=timeout, sandbox=False)
    rec.update(benchlib.judge_dict(res, expect_cjk=expect_cjk))
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
    llm_hook: LlmHook | None = None,
) -> dict:
    src = CORPUS / rel / "extracted"
    sid = safe_id(rel)
    rec: dict = {"id": rel, "code": _code_stamp()}
    if not src.is_dir():
        rec["error"] = "no extracted/ dir"
        rec["status"] = "partial"  # F3: 拒跑归降级档 + reject_at
        rec["reject_at"] = "route"
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
        sub = classify_no_main(src)
        rec["error"] = f"no main tex:{sub}" if sub else "no main tex"
        rec["status"] = "partial"
        rec["reject_at"] = "route"
        return rec
    main_rel = main_path.relative_to(src).as_posix()
    rec["main"] = main_rel
    route = route_project(src)
    rec["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    if route.reject:
        rec["status"] = "partial"
        rec["reject_at"] = "route"
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
        and rec.get("status") != "skipped_oversize"
        and rec["pipe-xel"].get("verdict", {}).get("status") != "clean"
    )
    if want_base:
        rec["base-xel"] = base_xel_condition(src, sid, main_rel, timeout)
    if _want_fix(rec, fixloop_mode):
        rec["pipe-fix"] = pipe_fix_condition(
            WORK / "pipe-xel" / sid,
            sid,
            main_rel,
            timeout,
            sink,
            llm_hook,
            expect_cjk=rec["pipe-xel"].get("translate", {}).get("chunks") != 0,
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
    if rec["status"] == benchlib.BENCH_ERROR_STATUS:
        return False
    tr = (rec.get("pipe-xel") or {}).get("translate") or {}
    return not (tr.get("skipped") or tr.get("fault"))


def _code_stamp() -> str:
    """产码印章——单源 ``benchlib.code_stamp``（★6 下沉）。

    语义不变：``snap-<sha256[:12]>``（TEXLATE_SRC 冻结快照带
    snapshot-manifest.txt 时）或 ``<sha>``/``<sha>-dirty``；进程内一次
    （benchlib 侧 lru_cache）。
    """
    return benchlib.code_stamp()


def _dedup_cases(path: Path) -> int:
    """cases.jsonl 同 (corpus,cond) 重跑追加的双行 → 按「末行胜」物理去重。

    flock + 原地 truncate 重写（**不** os.replace）——CaseSink 追加方是
    open→flock→append，原地写保证并发追加落在去重后文件末尾而非写进旧
    inode 丢行（records.jsonl 保留双行是审计账，cases 是沉淀原料、语义
    同末行胜，物理去重无损）。截尾坏行随重写清掉；返回剔除行数。
    """
    if not path.exists():
        return 0
    removed = 0
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.seek(0)
            parsed: list[tuple[tuple, str]] = []
            for ln in fh.read().splitlines():
                s = ln.strip()
                if not s:
                    continue
                try:
                    rec = json.loads(s)
                except json.JSONDecodeError:
                    removed += 1
                    continue
                key = (
                    (rec.get("corpus"), rec.get("cond"))
                    if isinstance(rec, dict)
                    else None
                )
                # 缺键行无法判重——各按唯一键全保留
                parsed.append(
                    (key if key and any(key) else ("__keep__", len(parsed)), s)
                )
            last = benchlib.latest_by(
                enumerate(parsed), keyfn=lambda t: t[1][0], valfn=lambda t: t[0]
            )
            kept = [s for i, (k, s) in enumerate(parsed) if last[k] == i]
            removed += len(parsed) - len(kept)
            if removed:
                fh.seek(0)
                fh.truncate()
                fh.write(("\n".join(kept) + "\n") if kept else "")
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return removed


def _stored_sample(out_dir: Path) -> list[str] | None:
    """run_meta.json 里的首轮抽样快照（无文件/无字段/坏 JSON → None）。

    须在 amain 重写 run_meta 之前读——它记的是「本目录这一跑」的样本集。
    """
    try:
        meta = benchlib.load_run_meta(out_dir)
    except OSError:
        return None
    if meta is None:
        return None
    ids = meta.get("sample_ids")
    return [str(i) for i in ids] if isinstance(ids, list) else None


_DATE_SUFFIX_RX = re.compile(r"\d{4}-\d{2}-\d{2}")


def _warn_date_fork(tag: str, out_dir: Path) -> None:
    """``--date`` 跨日分叉守卫（醒目警告，不阻断）。

    默认 ``--date`` = 当天 UTC——崩溃后隔日原样重启会新建 ``<tag>-<新日期>``
    空目录、records 从零开始全量重跑，结果劈进两个日期目录
    （scout-e2ereal-2026-09-17 §1，realpostfix2 臂实证风险）。目标目录尚不
    存在而 bench/results/ 已有同 tag 的其他日期目录时，列出最近一个并提示
    续跑日期；全新首跑（无任何同 tag 目录）保持静默不误警。
    """
    if out_dir.exists() or not out_dir.parent.is_dir():
        return
    prefix = f"{tag}-"
    siblings = sorted(
        d.name
        for d in out_dir.parent.iterdir()
        if d.is_dir()
        and d.name.startswith(prefix)
        and _DATE_SUFFIX_RX.fullmatch(d.name[len(prefix) :])
    )
    if not siblings:
        return
    latest = siblings[-1]
    print(
        f"*** WARNING: 目标目录 {out_dir.name}/ 不存在——本次将新建空目录从头跑。\n"
        f"*** 同 tag 已有 {len(siblings)} 个历史日期目录（最近：{latest}）。\n"
        f"*** 若意在续跑请加 --date {latest[len(prefix) :]}；"
        "确为全新一跑可无视本警告。",
        flush=True,
    )


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
    # .get 容忍旧格式种子行（results.json 里的 translate 可能缺 leftover_ph
    # 等后加键——直索引曾在续跑 write_reports 段 KeyError 炸停）
    return f"{t.get('ok', 0)}/{t.get('chunks', 0)} ph:{t.get('leftover_ph', 0)}"


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
    benchlib.atomic_write(out_dir / "matrix.md", "\n".join(matrix) + "\n")

    # ---- summary：分环节通过率 + 失败模式分类 ----
    lines = [
        f"# e2e real bench — {meta.get('model')}",
        "",
        f"- 样本：{len(results)} 篇（seed={meta.get('seed')} layers={meta.get('layers')}）",
        f"- 网关：{meta.get('base_url')} model={meta.get('model')}",
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
        f"- chunk 终态：ok {ok_chunks}/{tot_chunks}"
        f" · partial {sum(r['pipe-xel']['translate'].get('partial', 0) for r in ran_pipe)}"
        f" · fault {sum(r['pipe-xel']['translate'].get('fault', 0) for r in ran_pipe)}"
        f" · skipped {sum(r['pipe-xel']['translate'].get('skipped', 0) for r in ran_pipe)}"
    )
    lines.append(
        f"- splice 残留占位符：{ph}（应为 0）— gate "
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
            "- first_error 类别："
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
    benchlib.atomic_write(out_dir / "summary.md", "\n".join(lines) + "\n")


# ---------------------------------------------------------------- main
async def amain(args: argparse.Namespace) -> None:
    out_dir = ROOT / "bench/results" / f"{args.tag}-{args.date}"
    _warn_date_fork(args.tag, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    rec_path = out_dir / "records.jsonl"
    # records.jsonl 是 append 真账（行在=done，末行胜）；results.json 为兼容
    # 旧 run 目录的兜底种子 + 逐篇快照（l2_attr_probe 等读它）。
    results = benchlib.load_records(rec_path) if rec_path.exists() else {}
    if not results and out_path.exists():
        # records 缺失/空/全坏行时回退 results.json 种子——空 records 曾把
        # 有快照的旧目录判成全量重跑（scout-e2ereal §7）。坏 JSON 按空种子
        # 起步不炸启动。
        try:
            seed_rec = json.loads(out_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(
                f"*** WARNING: results.json 种子不可读（{e!r:.80}）——按空种子起步",
                flush=True,
            )
        else:
            if isinstance(seed_rec, dict):
                results = seed_rec

    entries = load_manifest(set(args.layers.split(",")))
    if args.ids:
        ids = sorted({i.strip() for i in args.ids.split(",") if i.strip()})
    else:
        ids = pick_sample(entries, args.n, args.seed)
        # 抽样漂移守卫（scout-e2ereal §8）：pick_sample 对「extracted/ 存在」
        # 集合 seeded sample——corpus 补解压后同 seed 样本漂移。目录已有进度
        # 时沿用 run_meta.sample_ids（首轮快照）保证续跑同一集合；无快照可
        # 依时至少把「进度含样本外 id」喊出来。全新首跑尊重当次 seed/n。
        stored = _stored_sample(out_dir)
        if stored is not None and results and ids != stored:
            print(
                f"*** WARNING: 重抽样 {len(ids)} 篇与首轮样本 {len(stored)} 篇"
                "不一致——沿用 run_meta.sample_ids 续跑（要换样本请换 --tag）",
                flush=True,
            )
            ids = stored
        elif results:
            outside = sorted(r for r in results if r not in ids)
            if outside:
                print(
                    f"*** WARNING: 已有进度含 {len(outside)} 个本次样本外 id"
                    f"（疑似抽样漂移）: {outside[:8]}",
                    flush=True,
                )
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
        "code": _code_stamp(),
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
    benchlib.atomic_write(
        out_dir / "run_meta.json", json.dumps(meta, ensure_ascii=False, indent=1)
    )

    def _close_meta(reason: str) -> None:
        """run_meta 落终态标记——scout 收尾注意：无完成标记时只能靠进程
        退出+records 行数判读；缺 ended_at 即被杀（KeyboardInterrupt 不补写）。"""
        meta["ended_at"] = datetime.now(UTC).isoformat()
        meta["end_reason"] = reason
        benchlib.atomic_write(
            out_dir / "run_meta.json", json.dumps(meta, ensure_ascii=False, indent=1)
        )

    # results.json + matrix.md + summary.md 快照节流：records.jsonl append
    # 已是逐篇耐久账（行在=done、末行胜），快照类全量重写逐篇跑是热路径
    # 冗余 IO——每 ≥8 篇或距上次 ≥30s 才落；循环收尾 force 补末刷，
    # 消费方拿到的是 ≤8 篇滞后的截面而非每篇一写。
    _snap = {"n": 0, "t": 0.0}

    def _snap_reports(force: bool = False) -> None:
        _snap["n"] += 1
        now = time.monotonic()
        if not force and _snap["n"] < 8 and now - _snap["t"] < 30.0:
            return
        _snap["n"] = 0
        _snap["t"] = now
        benchlib.atomic_write(
            out_path, json.dumps(results, ensure_ascii=False, indent=1)
        )
        write_reports(results, out_dir, meta)

    cfg = PipelineConfig(concurrency=args.concurrency)
    sink = CaseSink(out_dir / "cases.jsonl")
    # 上次被杀 run 可能留了同 (corpus,cond) 双行——启动先物理去重
    _dedup_cases(sink.path)
    fl_llm_hook = (
        make_llm_hook(base_url=args.base_url, api_key=args.api_key, model=args.model)
        if args.fixloop_llm
        else None
    )
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
                _close_meta("probe_failed")
                return
        translator = GatewayTranslator(client, args.model)

        t_start = time.monotonic()
        end_reason = "completed"
        auth_dead = 0  # 连续「全 auth 败」篇数（cached 格不触碰——没测凭证）
        for idx, rel in enumerate(ids):
            prev = results.get(rel)
            # --recode：产码印章不符的旧格不续跑（splice 层修复验证用——
            # chunk state 还在，重翻免费、parse/splice/compile 走新码）
            stale_code = args.recode and (
                not isinstance(prev, dict) or prev.get("code") != _code_stamp()
            )
            if not args.rerun and not stale_code and _paper_done(prev):
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
                        fl_llm_hook,
                        expect_cjk=prev.get("pipe-xel", {})
                        .get("translate", {})
                        .get("chunks")
                        != 0,
                    )
                    prev["ts"] = time.time()
                    benchlib.append_jsonl(rec_path, prev)
                    _snap_reports()
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
            auth_stop = False
            try:
                rec = await run_project(
                    rel,
                    translator,
                    cfg,
                    args.timeout,
                    args.base,
                    args.fixloop,
                    sink,
                    fl_llm_hook,
                )
            except AuthTrippedError as e:
                # 篇内连续 auth-fail 熔断抛出 = 凭证死透——不收摊的话其后每篇
                # 只会各烧 auth_fail_threshold 块再 bench_error
                # （scout-e2ereal §9）。落行取证即停，换凭证后同命令续跑。
                rec = {
                    "id": rel,
                    "status": "bench_error",
                    "error": repr(e)[:400],
                    "code": _code_stamp(),
                }
                auth_stop = True
            except Exception as e:
                rec = {
                    "id": rel,
                    "status": "bench_error",
                    "error": repr(e)[:400],
                    "code": _code_stamp(),
                }
            # rec 已是完整格记录（与 records.jsonl 末行胜同口径）——整替换
            # 而非浅合并：旧格不再产的臂键（pipe-fix/base-xel/error/
            # reject_at）残留进新行会成 matrix 幻影行。
            results[rel] = rec
            rec["ts"] = time.time()
            benchlib.append_jsonl(rec_path, rec)
            _snap_reports()
            t = rec.get("pipe-xel", {}).get("translate", {})
            print(
                f"  -> status={rec.get('status')} "
                f"tr={t.get('ok', '-')}/{t.get('chunks', '-')} "
                f"pipe={_v(rec, 'pipe-xel')} fix={_v(rec, 'pipe-fix')} "
                f"base={_v(rec, 'base-xel')} "
                f"({rec.get('seconds', '-')}s)",
                flush=True,
            )
            if auth_stop:
                end_reason = "auth_tripped"
                print(
                    "auth circuit tripped — 凭证疑似失效（连续 401/403 熔断），"
                    "停跑不空烧；换凭证后同命令续跑",
                    flush=True,
                )
                break
            auth_dead = auth_dead + 1 if t.get("auth_all_failed") else 0
            if auth_dead >= _AUTH_DEAD_STREAK:
                end_reason = "auth_dead"
                print(
                    f"连续 {auth_dead} 篇全部请求 auth 失败——凭证疑似失效，停跑",
                    flush=True,
                )
                break
            if time.monotonic() - t_start > args.time_budget:
                end_reason = "time_budget"
                print(
                    f"time budget {args.time_budget}s reached — stopping "
                    f"({idx + 1}/{len(ids)} done)",
                    flush=True,
                )
                break
    _snap_reports(force=True)  # 收尾强刷——节流窗内滞留的末几篇快照落盘
    _close_meta(end_reason)
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
    ap.add_argument(
        "--base-url",
        default=os.environ.get("TEXLATE_BASE_URL", "http://127.0.0.1:3033"),
    )
    ap.add_argument(
        "--api-key",
        default=os.environ.get("TEXLATE_API_KEY", ""),
        help="gateway bearer key（默认本机 3033 开发 key）",
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
    ap.add_argument(
        "--fixloop-llm",
        action="store_true",
        help="pipe-fix 臂 escalate_llm 规则接 LLM 修复钩（与 --model/--base-url/--api-key 同网关）",
    )
    ap.add_argument("--no-probe", action="store_true", help="跳过模型探活")
    ap.add_argument(
        "--no-preflight",
        action="store_true",
        help="跳过启动自检（全量 import + mock 链）",
    )
    ap.add_argument("--rerun", action="store_true", help="无视 records 重跑")
    ap.add_argument(
        "--recode",
        action="store_true",
        help="产码印章（record.code，snap-* 或 HEAD sha±dirty）不符的格重跑——splice/parse 层修复验证用，chunk 缓存仍在不重翻",
    )
    ap.add_argument("--tag", default=RESULTS_DIR_DEFAULT)
    ap.add_argument("--date", default=str(datetime.now(UTC).date()))
    args = ap.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
