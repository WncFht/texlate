#!/usr/bin/env python3
r"""stagerun.py — 分阶段批量驱动（batch-hardening §3 执行层）。

每阶段一子命令、独立 executor、append 式 records jsonl、按 (id, arm, upstream)
resume。论文流过 DAG 靠 ``work/{id}/`` 中间产物树而非内存对象。

    stagerun.py ingest  --layers core,booster        # corpus_v3 已物化副本 → work/{id}/src/
    stagerun.py parse   --n 3 --tag smoke            # → records/parse.jsonl + work/{id}/parse.json + zh/
    stagerun.py xlat    --arm mock --n 3 --tag smoke # → records/xlat.jsonl + zh/(译) + xlat-{arm}.jsonl
    stagerun.py compile --arm zh --n 3 --tag smoke   # → records/compile.jsonl + splice/
    stagerun.py compile --arm base --tag smoke       # → build-base/（原文直编归因臂）
    stagerun.py fixloop --on fail --tag smoke        # → records/fixloop.jsonl + cases.jsonl + splice/(修复)

work/{id}/ 契约（``--tag T`` → ``bench/results/stagerun-T-<date>/``）：

    src/              ingest：corpus_v3/{id}/extracted/ 原样副本（永不改——
                      compile --arm base 的「原文直编」归因基准）
    zh/               parse：src/ 副本 + route + normalize + 逐文件 parse_file
                      （归一化英文树）；xlat：就地翻译写回（splice 含在
                      translate_tree 内）。``zh/.xlat-arm.json`` 记录最近
                      一次翻译臂——compile zh 据此判 provenance。
    parse.json        parse 产物：main_rel / engine_resolved / route /
                      normalize stats / 逐文件 {chunks,warnings,inputs}
    xlat-{arm}.jsonl  xlat 逐块明细（chunk_id/status/attempts/warnings/...）
    splice/           compile --arm zh：zh/ 副本 + prepare_chinese(ctex) +
                      xelatex 产物原地。fixloop 就地修复此树（≈规格 §1 的
                      「zh/(repaired)」——物理落点是 splice/）。
    build-base/       compile --arm base：src/ 副本直编（无 normalize/inject）
    _texmf/           fixloop 每篇冷 usertree（tlmgr --usermode 装包落点）

resume 语义：records/{stage}.jsonl 里 (id, arm, upstream) 已记且 status ∉
{skip, error} 的格跳过；skip（上游门未过）/error（harness 崩）自动重试。
--rerun 全强制。zh/ 与 splice/ 是臂间共享树：real 臂翻译会覆盖 mock 产物
（records 按臂分记、marker 记 provenance，compile --xlat-arm 可钉住预期）。

与规格 §1/§3 的有意偏差（目录归谁写）：
  - zh/ 由 parse 建（normalize 必须有落点；src/ 留生料给 base 臂）；
    §1 图把 zh/ 画在 xlat 下——物理上 zh/ 是跨阶段共享演化的产品树。
  - parse.json 记 chunk 元数据（kind/span/文件归属）而非正文——reconstruct
    要 ScanResult（pieces/ph_map/macros），序列化不划算；xlat 重扫 ~1-3s/篇。
  - compile --post l2 留了旗标位但未接线：L2 回灌要 _TreeRun 内存态 +
    编译尾段，跨 stage 文件协议暂不支持（TODO 同 T2 auth 熔断——见 §4 横切洞）。
  - channel=arxiv_eprint 缺 extracted 的条目 ingest 记 reject
    （eprint_fetch_unwired）——规格 §2 说逐篇 API 仅作旁路，未铺。
  - ingest 的 IA 拉取是 stub：未物化但具 item/member 的条目记 skip
    （ia_fetch_unwired，下轮自动重试），stub/pdf/error 格式记 reject。
    具体实现归数据侧（复用 build_corpus_v3 的 scan + item-index.csv
    成员级单抽）——本文件只保 records/work/{id}/src/ 契约。

executor：ingest ThreadPool(IO) / parse ProcessPool(CPU，pickle 边界=路径)
/ xlat asyncio（--sem 全局信号量压网关 in-flight，默认 4=gwcap 硬闸；--jobs
控制同时在翻的论文数）/ compile+fixloop ThreadPool(subprocess)。

用法（smoke，离线）：
  uv run python bench/py/stagerun.py parse --n 3 --tag smoke
  uv run python bench/py/stagerun.py xlat --arm mock --n 3 --tag smoke
  uv run python bench/py/stagerun.py compile --arm zh --n 3 --tag smoke
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: TEXLATE_SRC 可指冻结快照（同 e2e_real_bench：bench 期间 src/ 被改时隔离）。
sys.path.insert(0, os.environ.get("TEXLATE_SRC", str(ROOT / "src")))

# 同目录 bench 脚本经 sys.path[0] 可 import；模块级零副作用（main 均有守卫）。
import benchlib
import e2e_real_bench as erb
import fixloop_bench as flb
import translators_bench as tb  # xlat 臂工厂 + sabotage 台账（e2e_mock 注入逻辑由此封装）

from texlate.compile.engine import (
    XelatexEngine,
    engine_for,
    route_project,
)
from texlate.compile.fixloop import CaseSink, fixloop
from texlate.compile.fixloop.llm_hook import make_llm_hook
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.normalize import normalize_project
from texlate.latex.api import parse_file
from texlate.latex.placeholder import PH_RX
from texlate.latex.prose import file_has_prose
from texlate.latex.reconstruct import reconstruct
from texlate.validate.l0 import validate_pair
from texlate.xlat.client import ChatClient
from texlate.xlat.pipeline import (
    GatewayTranslator,
    PipelineConfig,
    XlatPipeline,
    chunk_to_in,
)
from texlate.xlat.state import StateStore

CORPUS = ROOT / "bench/corpus_v3"

#: resume 终态集——记了这些 status 的 (id,arm,upstream) 不再跑；
#: skip（上游门）与 error（harness 崩）属可重试类。
DONE_STATUS = {"ok", "partial", "clean", "fail", "reject", "fault", "dirty_pdf"}
RETRIABLE_STATUS = {"skip", "error"}

STAGES = ("ingest", "parse", "xlat", "compile", "fixloop")


# ================================================================ 选样与 records
def select_ids(entries: list[dict], args: argparse.Namespace, stage: str) -> list[str]:
    """--ids 显式集 或 manifest 全量/--n 抽样子集（--seed 定序）。

    ``--n`` 抽样全 stage 共用 ``erb.pick_sample``（候选限 extracted/ 在盘
    者）——同 --n/--seed 跨 stage 命中同一子集。ingest 全量（--n 0）路径
    对未物化条目记 skip/reject（IA 拉取留 stub 归数据侧，见模块
    docstring）；--ids 亦可定点。
    """
    if args.ids:
        want = {i.strip() for i in args.ids.split(",") if i.strip()}
        have = {e["id"] for e in entries}
        return sorted((want & have) | (want - have))
    if args.n and args.n > 0:
        pool = erb.pick_sample(entries, args.n, args.seed)
    elif stage == "ingest":
        pool = sorted({e["id"] for e in entries})
    else:
        pool = sorted(
            {e["id"] for e in entries if (CORPUS / e["id"] / "extracted").is_dir()}
        )
    if args.only:
        pool = [i for i in pool if args.only in i]
    return pool


def _rec_key(rec: dict) -> tuple[str, str, str]:
    return (
        str(rec.get("id")),
        str(rec.get("arm") or "-"),
        str(rec.get("upstream") or ""),
    )


@functools.cache
def _code_stamp() -> str:
    """产码印章（``<sha>``/``<sha>-dirty``）——e2e_real_bench 同款，进程内一次。

    records 终态格带印：splice/parse 层修复落地后，旧格 work/ tex 是陈字节，
    ``is_done`` 的 resume 谓词无码感会整篇 carry-over（0707.3950 同款坑，
    e2e_real_bench ``090975d`` 已实证）。``--recode`` 时印章不符即不续跑。
    """
    return erb._code_stamp()


class RecLog:
    """records/{stage}.jsonl：load 出 done 键→印章映射 + 逐条 append（落盘即 done）。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.done: dict[tuple[str, str, str], str] = {}
        for rec in benchlib.iter_jsonl(path) if path.exists() else ():
            if str(rec.get("status")) in DONE_STATUS:
                self.done[_rec_key(rec)] = str(rec.get("code") or "")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")

    def is_done(
        self, pid: str, arm: str, upstream: str = "", recode: bool = False
    ) -> bool:
        code = self.done.get((pid, arm, upstream))
        if code is None:
            return False
        # --recode：印章不符/缺印 = 陈字节格, 不续跑（与 e2e _paper_done 同型修复）
        return not recode or code == _code_stamp()

    def append(self, rec: dict) -> None:
        benchlib.write_jsonl(self._fh, rec)
        if str(rec.get("status")) in DONE_STATUS:
            self.done[_rec_key(rec)] = str(rec.get("code") or "")

    def close(self) -> None:
        self._fh.close()


def load_latest(path: Path) -> dict[tuple[str, str, str], dict]:
    """records 文件 → {(id,arm,upstream): 末条记录}（append 序后者胜）。"""
    out: dict[tuple[str, str, str], dict] = {}
    if path.exists():
        for rec in benchlib.iter_jsonl(path):
            out[_rec_key(rec)] = rec
    return out


def make_sig(status: str, errors: list[dict]) -> str:
    """triage 契约：ok 级无 sig；否则 errors[0] 的 cat:pay 合成签名。"""
    if not errors:
        return ""
    cat = str(errors[0].get("cat") or errors[0].get("code") or "error")
    pay = str(errors[0].get("payload") or "")
    return f"{cat}:{pay}".rstrip(":")


def base_rec(pid: str, stage: str, arm: str, upstream: str = "") -> dict:
    return {
        "id": pid,
        "stage": stage,
        "arm": arm,
        "upstream": upstream,
        "code": _code_stamp(),
        "status": "error",
        "dur_s": 0.0,
        "metrics": {},
        "errors": [],
        "sig": "",
    }


def finish_rec(rec: dict, t0: float) -> dict:
    rec["dur_s"] = round(time.monotonic() - t0, 2)
    rec["sig"] = make_sig(str(rec["status"]), rec["errors"])
    return rec


def crash_rec(pid: str, stage: str, arm: str, e: BaseException, t0: float) -> dict:
    rec = base_rec(pid, stage, arm)
    rec["status"] = "error"
    rec["errors"] = [
        {
            "code": f"harness:{type(e).__name__}",
            "cat": "harness",
            "payload": repr(e)[:400],
        }
    ]
    return finish_rec(rec, t0)


def git_rev() -> str:
    try:
        p = subprocess.run(
            [shutil.which("git") or "git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return p.stdout.strip() if p.returncode == 0 else "?"
    except OSError:
        return "?"


def touch_run_meta(out_dir: Path, args: argparse.Namespace) -> None:
    """run_meta.json：首建 {created,git_rev,invocations[]}，逐次 append argv。

    ``started_at`` 缺省回填 ``created_at``（run 首触时刻）——triage ``_wall_s``
    读 started_at/finished_at 算真实墙钟；``finished_at`` 由
    ``mark_run_finished`` 在每次 invocation 收尾时推进。
    """
    mp = out_dir / "run_meta.json"
    meta = (
        json.loads(mp.read_text())
        if mp.exists()
        else {
            "created_at": datetime.now(UTC).isoformat(),
            "git_rev": git_rev(),
            "invocations": [],
        }
    )
    meta.setdefault(
        "started_at", meta.get("created_at") or datetime.now(UTC).isoformat()
    )
    meta["invocations"].append(
        {
            "ts": datetime.now(UTC).isoformat(),
            "stage": args.stage,
            "argv": sys.argv[1:],
            "seed": args.seed,
            "layers": args.layers,
            "code": _code_stamp(),
        }
    )
    mp.write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def mark_run_finished(out_dir: Path) -> None:
    """run_meta.finished_at = now——末次 invocation 收尾时刻（triage 墙钟右端点）。"""
    mp = out_dir / "run_meta.json"
    meta = json.loads(mp.read_text()) if mp.exists() else {}
    meta["finished_at"] = datetime.now(UTC).isoformat()
    mp.write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def out_dir_of(args: argparse.Namespace) -> Path:
    if args.dir:
        return Path(args.dir).expanduser().resolve()
    return ROOT / "bench/results" / f"stagerun-{args.tag}-{args.date}"


def workdir(out_dir: Path, pid: str) -> Path:
    return out_dir / "work" / benchlib.safe_id(pid)


# ================================================================ ingest
def _ingest_copy(pid: str, out_dir: Path) -> dict:
    """已物化条目：corpus_v3/{id}/extracted/ → work/{id}/src/。"""
    t0 = time.monotonic()
    rec = base_rec(pid, "ingest", "-")
    src_corp = CORPUS / pid / "extracted"
    dst = workdir(out_dir, pid) / "src"
    if not src_corp.is_dir():
        rec["errors"] = [
            {"code": "no_extracted", "cat": "ingest", "payload": str(src_corp)}
        ]
        rec["status"] = "error"
        return finish_rec(rec, t0)
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_corp, dst)
    n_files = sum(1 for p in dst.rglob("*") if p.is_file())
    main = find_main_tex(dst)
    rec["status"] = "ok"
    rec["metrics"] = {
        "n_files": n_files,
        "main_tex_guess": main.relative_to(dst).as_posix() if main else None,
        "source": "cache",
        "sha256_ok": None,
    }
    return finish_rec(rec, t0)


def _missing_rec(entry: dict) -> dict:
    """未物化条目的 stub 记录。

    IA 拉取实现归数据侧（见模块 docstring）：可拉取相（有 item/member）
    记 skip `ia_fetch_unwired` 留下轮重试；stub/pdf/error 格式或无
    item 的记 reject（本路径永不可解）。metrics 四键与 cache 路径同形。
    """
    t0 = time.monotonic()
    pid, fmt, ch = entry["id"], entry.get("format"), entry.get("channel")
    r = base_rec(pid, "ingest", "-")
    r["metrics"] = {
        "n_files": 0,
        "main_tex_guess": None,
        "source": "ia" if entry.get("item") else None,
        "sha256_ok": None,
    }
    if fmt in ("stub", "pdf", "error") or not entry.get("item"):
        r["status"] = "reject"
        code = (
            f"{fmt}_format"
            if fmt in ("stub", "pdf", "error")
            else ("eprint_fetch_unwired" if ch == "arxiv_eprint" else "no_item")
        )
        # cat=code：sig 要能分流 stub_format/eprint_fetch_unwired 等
        r["errors"] = [{"code": code, "cat": code, "payload": entry.get("member")}]
    else:
        r["status"] = "skip"
        # cat=code 同 reject 约定；payload 只到 item 级——triage sig 按 IA
        # item 聚类（一个 tar 一个工单），member 由 id 回 manifest 查。
        r["errors"] = [
            {
                "code": "ia_fetch_unwired",
                "cat": "ia_fetch_unwired",
                "payload": f"item={entry['item']}",
            }
        ]
    return finish_rec(r, t0)


def stage_ingest(
    args: argparse.Namespace,
    out_dir: Path,
    ids: list[str],
    entries: list[dict],
    log: RecLog,
) -> None:
    by_id = {e["id"]: e for e in entries}
    cached, missing = [], []
    for pid in ids:
        if log.is_done(pid, "-", recode=args.recode) and not args.rerun:
            continue
        if (CORPUS / pid / "extracted").is_dir():
            cached.append(pid)
        else:
            missing.append(by_id.get(pid) or {"id": pid})
    print(
        f"ingest: {len(cached)} cached + {len(missing)} unmaterialized "
        f"(jobs={args.jobs})",
        flush=True,
    )
    done_n = 0
    for e in missing:
        r = _missing_rec(e)
        log.append(r)
        done_n += 1
        print(f"  [{done_n}] {r['id']} -> {r['status']}", flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(_ingest_copy, pid, out_dir): pid for pid in cached}
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception as e:
                r = crash_rec(futs[fut], "ingest", "-", e, time.monotonic())
            log.append(r)
            done_n += 1
            print(f"  [{done_n}] {r['id']} -> {r['status']}", flush=True)


# ================================================================ parse
def _parse_job(pid: str, src_s: str, zh_s: str, pj_s: str, engine_opt: str) -> dict:
    """ProcessPool 工作元：pickle 边界 = 字符串路径 + 配置。

    route(src) → copytree(src→zh) → find_main → normalize(zh, eng) →
    逐文件 parse_file(flatten=False) → parse.json + record。
    """
    t0 = time.monotonic()
    src, zh, pj = Path(src_s), Path(zh_s), Path(pj_s)
    rec = base_rec(pid, "parse", "-")
    route = route_project(src)
    rec["metrics"]["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    doc: dict = {"id": pid, "route": rec["metrics"]["route"]}
    if route.reject:
        doc["status"] = "reject"
        pj.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        rec["status"] = "reject"
        rec["errors"] = [
            {"code": "route_reject", "cat": "route", "payload": route.reject}
        ]
        return finish_rec(rec, t0)

    if zh.exists():
        shutil.rmtree(zh)
    shutil.copytree(src, zh, ignore=benchlib.copytree_ignore())
    main = find_main_tex(zh)
    if main is None:
        sub = classify_no_main(zh)
        doc["status"] = "reject"
        doc["no_main_sub"] = sub
        pj.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        rec["status"] = "reject"
        rec["errors"] = [{"code": "no_main_tex", "cat": "parse", "payload": sub or ""}]
        return finish_rec(rec, t0)
    main_rel = main.relative_to(zh).as_posix()
    eng = (
        engine_opt
        if engine_opt != "auto"
        else (route.engines[0] if route.engines else "xelatex")
    )
    norm = normalize_project(zh, eng, main_rel)
    doc.update({"main_rel": main_rel, "engine_resolved": eng, "normalize": norm})
    rec["metrics"]["main_rel"] = main_rel
    rec["metrics"]["engine_resolved"] = eng
    rec["metrics"]["normalize"] = norm

    files: list[dict] = []
    warn_kinds: dict[str, int] = {}
    unresolved: list[str] = []
    n_chunks = 0
    parse_fail: list[str] = []
    for f in sorted(zh.rglob("*.tex")):
        if f.name.startswith("."):
            continue
        rel = f.relative_to(zh).as_posix()
        try:
            res = parse_file(f, flatten=False)
        except Exception as e:
            parse_fail.append(f"{rel}: {e!r:.160}")
            continue
        ws = [{"kind": w.kind, "pos": w.pos, "detail": w.detail} for w in res.warnings]
        for w in res.warnings:
            warn_kinds[w.kind] = warn_kinds.get(w.kind, 0) + 1
        ins = [name for _pos, name in res.inputs]
        unresolved.extend(f"{rel}:{n}" for n in ins)
        n_chunks += len(res.chunks)
        files.append(
            {
                "rel": rel,
                "n_chunks": len(res.chunks),
                "chunk_kinds": sorted({c.context for c in res.chunks}),
                "warnings": ws,
                "inputs": ins,
            }
        )
    doc.update(
        {
            "status": "ok",
            "files": files,
            "parse_fail": parse_fail,
            "totals": {
                "tex_files": len(files),
                "chunks": n_chunks,
                "warn_kinds": dict(sorted(warn_kinds.items())),
                "unresolved": unresolved,
            },
        }
    )
    pj.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    rec["status"] = "ok"
    rec["metrics"].update(
        {
            "tex_files": len(files),
            "chunks": n_chunks,
            "warn_kinds": doc["totals"]["warn_kinds"],
            "n_unresolved": len(unresolved),
            "parse_fail": parse_fail,
        }
    )
    if parse_fail:
        rec["errors"] = [
            {"code": "parse_file", "cat": "parse", "payload": p}
            for p in parse_fail[:10]
        ]
    return finish_rec(rec, t0)


def stage_parse(
    args: argparse.Namespace, out_dir: Path, ids: list[str], log: RecLog
) -> None:
    todo = []
    for pid in ids:
        if log.is_done(pid, "-", recode=args.recode) and not args.rerun:
            continue
        wid = workdir(out_dir, pid)
        src = wid / "src"
        if not src.is_dir():
            r = base_rec(pid, "parse", "-")
            r["status"] = "skip"
            r["errors"] = [
                {
                    "code": "no_src",
                    "cat": "upstream",
                    "payload": "work/{id}/src/ missing",
                }
            ]
            log.append(finish_rec(r, time.monotonic()))
            continue
        todo.append(
            (pid, str(src), str(wid / "zh"), str(wid / "parse.json"), args.engine)
        )
    print(f"parse: {len(todo)} to run (jobs={args.jobs})", flush=True)
    if not todo:
        return
    ex = ProcessPoolExecutor(max_workers=args.jobs)
    t_start = time.monotonic()
    try:
        futs = {ex.submit(_parse_job, *t): t[0] for t in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = crash_rec(pid, "parse", "-", e, time.monotonic())
            log.append(rec)
            print(
                f"  [{i}/{len(todo)}] {pid} -> {rec['status']} ({rec['dur_s']}s)",
                flush=True,
            )
            if args.time_budget and time.monotonic() - t_start > args.time_budget:
                print(
                    f"time budget {args.time_budget}s — stop ({i}/{len(todo)})",
                    flush=True,
                )
                break
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


# ================================================================ xlat
class _SemTranslator:
    """全局网关信号量包裹：run 内全部 paper/pipeline 共享同一 sem（gwcap 硬闸）。

    per-paper PipelineConfig.concurrency 管论文内部排队；本层管跨论文的
    真实在途请求数——``--sem 4`` 即全局 in-flight ≤4。
    """

    def __init__(self, inner: object, sem: asyncio.Semaphore) -> None:
        self._inner = inner
        self._sem = sem

    def __getattr__(self, k: str) -> object:
        return getattr(self._inner, k)

    async def translate(self, **kw: object) -> str:
        async with self._sem:
            return await self._inner.translate(**kw)


async def _translate_tree(
    root: Path,
    translator: object,
    state_dir: Path,
    cfg: PipelineConfig,
    *,
    oversize_cap: int = 0,
) -> tuple[dict, list]:
    """e2e_real.translate_tree 同构 + 返回逐块结果（chunk 明细/sabotage 归因用）。"""
    scans = []
    chunks = []
    parse_fail: list[str] = []
    support_files: list[str] = []
    for f in sorted(root.rglob("*.tex")):
        if f.name.startswith(".") or f.name.endswith(".rtx.tex"):
            continue  # 隐文件 + REVTeX 运行时转储不进翻译集 (regress4-1003.1717)
        if f.name.lower().endswith(".code.tex"):
            support_files.append(f.name)  # tikzlibrary 机制件硬抛 (e2e._scan_tree 同径)
            continue
        try:
            res = parse_file(f, flatten=False)
        except Exception as e:
            parse_fail.append(f"{f.relative_to(root)}: {e!r:.120}")
            continue
        if not file_has_prose(res.chunks):
            support_files.append(f.name)  # 无散文=support 件, 送译即腐蚀 (9bd8811 门)
            continue
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(
            chunk_to_in(c, chunk_id=f"{idx}:{c.id}", ph_map=res.ph_map)
            for c in res.chunks
        )
    total_chars = sum(len(c.content) for c in chunks)
    if oversize_cap and total_chars > oversize_cap:
        # 保守闸（同 e2e_real）：超上限不烧网关配额——调用侧记 oversize 终态
        return (
            {
                "files": 0,
                "chunks": len(chunks),
                "ok": 0,
                "partial": 0,
                "fault": 0,
                "skipped": 0,
                "attempts": 0,
                "batched": 0,
                "leftover_ph": 0,
                "parse_fail": parse_fail,
                "support_skipped": len(support_files),
                "warn_kinds": {},
                "seconds": 0.0,
                "src_chars": total_chars,
                "oversize": True,
                "max_total_chars": oversize_cap,
            },
            [],
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
    state_dir.mkdir(parents=True, exist_ok=True)
    state = StateStore(state_dir, model=getattr(translator, "model", "") or "")
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

    n_files = n_leftover = 0
    for idx, (f, res) in enumerate(scans):
        trans = by_file.get(idx)
        if not trans:
            continue
        zh = reconstruct(res, trans)
        f.write_text(zh, encoding="utf-8")
        n_files += 1
        n_leftover += len(PH_RX.findall(zh))
    stats_d = {
        "files": n_files,
        "chunks": len(chunks),
        **stats,
        "leftover_ph": n_leftover,
        "parse_fail": parse_fail,
        "support_skipped": len(support_files),
        "warn_kinds": dict(sorted(warn_kinds.items())),
        "seconds": round(translate_s, 1),
        "src_chars": total_chars,
    }
    return stats_d, results


async def _xlat_one(
    pid: str,
    out_dir: Path,
    args: argparse.Namespace,
    translator_factory,
    paper_sem: asyncio.Semaphore,
) -> dict:
    t0 = time.monotonic()
    try:
        async with paper_sem:
            return await _xlat_one_inner(pid, out_dir, args, translator_factory, t0)
    except Exception as e:  # 格子崩溃记 error 不炸整批（CancelledError 仍外抛）
        return crash_rec(pid, "xlat", args.arm, e, t0)


async def _xlat_one_inner(
    pid: str, out_dir: Path, args: argparse.Namespace, translator_factory, t0: float
) -> dict:
    rec = base_rec(pid, "xlat", args.arm)
    wid = workdir(out_dir, pid)
    zh = wid / "zh"
    pj = wid / "parse.json"
    if not zh.is_dir() or not pj.exists():
        rec["status"] = "skip"
        rec["errors"] = [
            {
                "code": "no_parse_tree",
                "cat": "upstream",
                "payload": "zh/ or parse.json missing",
            }
        ]
        return finish_rec(rec, t0)
    translator = translator_factory(pid)
    state_dir = wid / "xlat-state" / args.arm  # 臂间 state 隔离——mock 结果不回灌 real
    cfg = PipelineConfig(concurrency=args.concurrency)
    cap = erb.MAX_TOTAL_CHARS if args.arm == "real" else 0  # 配额闸只对真网关
    stats, results = await _translate_tree(
        zh, translator, state_dir, cfg, oversize_cap=cap
    )
    if stats.get("oversize"):
        rec["status"] = "reject"
        rec["errors"] = [
            {
                "code": "oversize",
                "cat": "xlat",
                "payload": f"src_chars={stats['src_chars']}",
            }
        ]
        rec["metrics"]["translate"] = stats
        return finish_rec(rec, t0)
    # 逐块明细（triage/契约审计原料）
    detail = wid / f"xlat-{args.arm}.jsonl"
    with detail.open("w", encoding="utf-8") as fh:
        for r in results:
            benchlib.write_jsonl(
                fh,
                {
                    "chunk_id": r.chunk_id,
                    "status": r.status,
                    "attempts": r.attempts,
                    "batched": r.batched,
                    "skipped": r.skipped,
                    "error_kind": r.error_kind,
                    "skip_reason": r.skip_reason,
                    "warnings": r.warnings,
                },
            )
    (zh / ".xlat-arm.json").write_text(
        json.dumps(
            {
                "arm": args.arm,
                "model": getattr(translator, "model", None),
                "ts": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
    )
    rec["metrics"]["translate"] = stats
    # sabotage/perturb 臂带 .finalize 台账面（translators_bench 契约）；
    # mock/real 无此面，getattr 探空跳过
    finalize = getattr(translator, "finalize", None)
    if finalize is not None:
        ledger = finalize(results)
        rec["metrics"]["sabotage"] = ledger
        if ledger.get("escaped"):
            rec["status"] = "fail"
            rec["errors"] = [
                {
                    "code": "sabotage_escaped",
                    "cat": "xlat",
                    "payload": f"{ledger['escaped']} escaped: {ledger['escaped_ids'][:8]}",
                }
            ]
            return finish_rec(rec, t0)
    n_bad = stats["fault"] + stats["skipped"]
    if stats["leftover_ph"] > 0:
        rec["status"] = "fail"
        rec["errors"] = [
            {"code": "leftover_ph", "cat": "xlat", "payload": str(stats["leftover_ph"])}
        ]
    elif stats["chunks"] and n_bad == stats["chunks"]:
        rec["status"] = "fail"
        rec["errors"] = [
            {"code": "all_chunks_bad", "cat": "xlat", "payload": str(stats["chunks"])}
        ]
    elif n_bad or stats["parse_fail"]:
        rec["status"] = "partial"
        if n_bad:
            rec["errors"] = [
                {
                    "code": "chunks_bad",
                    "cat": "xlat",
                    "payload": f"fault={stats['fault']} skipped={stats['skipped']}",
                }
            ]
    else:
        rec["status"] = "ok"
    return finish_rec(rec, t0)


def stage_xlat(
    args: argparse.Namespace,
    out_dir: Path,
    ids: list[str],
    log: RecLog,
    parse_recs: dict,
) -> None:
    upstream_ok = set((args.upstream or "ok").split(","))
    todo = []
    for pid in ids:
        if log.is_done(pid, args.arm, recode=args.recode) and not args.rerun:
            continue
        up = parse_recs.get((pid, "-", ""))
        if up is not None and up.get("status") not in upstream_ok:
            r = base_rec(pid, "xlat", args.arm)
            r["status"] = "skip"
            r["errors"] = [
                {
                    "code": "upstream_gate",
                    "cat": "upstream",
                    "payload": f"parse={up.get('status')}",
                }
            ]
            log.append(finish_rec(r, time.monotonic()))
            continue
        todo.append(pid)
    print(
        f"xlat[{args.arm}]: {len(todo)} to run (jobs={args.jobs} sem={args.sem})",
        flush=True,
    )
    if not todo:
        return

    async def drive(translator_factory) -> None:
        sem = asyncio.Semaphore(args.sem)
        paper_sem = asyncio.Semaphore(args.jobs)

        def make(pid: str):
            return _SemTranslator(translator_factory(pid), sem)

        tasks = [
            asyncio.ensure_future(_xlat_one(p, out_dir, args, make, paper_sem))
            for p in todo
        ]
        t_start = time.monotonic()
        for i, fut in enumerate(asyncio.as_completed(tasks), 1):
            rec = await fut
            log.append(rec)
            t = (rec.get("metrics") or {}).get("translate") or {}
            print(
                f"  [{i}/{len(todo)}] {rec['id']} -> {rec['status']} "
                f"ok={t.get('ok', '-')}/{t.get('chunks', '-')} ph={t.get('leftover_ph', '-')} ({rec['dur_s']}s)",
                flush=True,
            )
            if args.time_budget and time.monotonic() - t_start > args.time_budget:
                print(
                    f"time budget {args.time_budget}s — stop ({i}/{len(todo)})",
                    flush=True,
                )
                for tk in tasks:
                    tk.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                break

    if args.arm == "real":

        async def _run_real() -> None:
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

                def factory(pid: str):
                    return GatewayTranslator(client, args.model)

                await drive(factory)

        asyncio.run(_run_real())
    else:

        def factory(pid: str):
            return tb.make_translator(args.arm)

        asyncio.run(drive(factory))


# ================================================================ compile
def _compile_judge(
    work: Path, main_rel: str, eng_name: str, timeout: float, *, expect_cjk: bool
) -> dict:
    """best-effort 编译 + judge → {compile, verdict, status}。"""
    kw = {"halt_on_error": False} if eng_name == "xelatex" else {}
    res = engine_for(eng_name, **kw).compile(
        work, main_rel, timeout=timeout, sandbox=True
    )
    return benchlib.judge_dict(res, expect_cjk=expect_cjk)


def _resolve_engine(
    args: argparse.Namespace, parse_doc: dict | None, root: Path
) -> str:
    if args.engine != "auto":
        return args.engine
    if parse_doc and parse_doc.get("engine_resolved"):
        return parse_doc["engine_resolved"]
    try:
        return route_project(root, prefer="xelatex").engines[0]
    except Exception:
        return "xelatex"


def _compile_one(
    pid: str, out_dir: Path, args: argparse.Namespace, xlat_recs: dict
) -> dict:
    t0 = time.monotonic()
    rec = base_rec(pid, "compile", args.arm)
    wid = workdir(out_dir, pid)
    pj = wid / "parse.json"
    parse_doc = json.loads(pj.read_text()) if pj.exists() else None
    main_rel = (parse_doc or {}).get("main_rel")

    if args.arm == "zh":
        zh = wid / "zh"
        marker_p = zh / ".xlat-arm.json"
        if not zh.is_dir() or not marker_p.exists():
            rec["status"] = "skip"
            rec["errors"] = [
                {
                    "code": "not_translated",
                    "cat": "upstream",
                    "payload": "zh/ missing or no .xlat-arm.json",
                }
            ]
            return finish_rec(rec, t0)
        upstream = json.loads(marker_p.read_text()).get("arm") or ""
        if args.xlat_arm and upstream != args.xlat_arm:
            rec["status"] = "skip"
            rec["errors"] = [
                {
                    "code": "arm_mismatch",
                    "cat": "upstream",
                    "payload": f"zh/ is {upstream}, want {args.xlat_arm}",
                }
            ]
            return finish_rec(rec, t0)
        rec["upstream"] = upstream
        up_ok = set((args.upstream or "ok,partial").split(","))
        xr = xlat_recs.get((pid, upstream, ""))
        if xr is not None and xr.get("status") not in up_ok:
            rec["status"] = "skip"
            rec["errors"] = [
                {
                    "code": "upstream_gate",
                    "cat": "upstream",
                    "payload": f"xlat[{upstream}]={xr.get('status')}",
                }
            ]
            return finish_rec(rec, t0)
        splice = wid / "splice"
        if splice.exists():
            shutil.rmtree(splice)
        shutil.copytree(zh, splice, ignore=benchlib.copytree_ignore())
        if not main_rel:
            m = find_main_tex(splice)
            main_rel = m.relative_to(splice).as_posix() if m else None
        if not main_rel:
            rec["status"] = "reject"
            rec["errors"] = [
                {
                    "code": "no_main_tex",
                    "cat": "compile",
                    "payload": classify_no_main(splice) or "",
                }
            ]
            return finish_rec(rec, t0)
        eng = _resolve_engine(args, parse_doc, splice)
        rec["metrics"]["engine"] = eng
        rec["metrics"]["main_rel"] = main_rel
        try:
            rec["metrics"]["inject"] = prepare_chinese(splice, main_rel)
        except InjectRejectError as e:
            rec["status"] = "reject"
            rec["errors"] = [
                {"code": "inject_reject", "cat": "inject", "payload": e.reason}
            ]
            rec["metrics"]["verdict"] = {"status": "reject", "reasons": [e.reason]}
            return finish_rec(rec, t0)
        # 0-chunk 主文档 (includepdf 壳) 无译文产出 → 不期待 CJK (F 桶假阳修);
        # xr 缺席时保守默认 True。记入 metrics 供 fixloop 复判同口径
        _tr = ((xr or {}).get("metrics") or {}).get("translate") or {}
        expect_cjk = _tr.get("chunks") != 0
        rec["metrics"]["expect_cjk"] = expect_cjk
        tail = _compile_judge(
            splice, main_rel, eng, args.timeout, expect_cjk=expect_cjk
        )
    else:  # base：src/ 原样直编（归因臂——不 normalize 不 inject）
        src = wid / "src"
        if not src.is_dir():
            rec["status"] = "skip"
            rec["errors"] = [
                {
                    "code": "no_src",
                    "cat": "upstream",
                    "payload": "work/{id}/src/ missing",
                }
            ]
            return finish_rec(rec, t0)
        main = find_main_tex(src)
        if main is None:
            rec["status"] = "reject"
            rec["errors"] = [
                {
                    "code": "no_main_tex",
                    "cat": "compile",
                    "payload": classify_no_main(src) or "",
                }
            ]
            return finish_rec(rec, t0)
        main_rel = main.relative_to(src).as_posix()
        build = wid / "build-base"
        if build.exists():
            shutil.rmtree(build)
        shutil.copytree(src, build, ignore=benchlib.copytree_ignore())
        eng = _resolve_engine(args, parse_doc, src)
        rec["metrics"]["engine"] = eng
        rec["metrics"]["main_rel"] = main_rel
        tail = _compile_judge(build, main_rel, eng, args.timeout, expect_cjk=False)

    rec["metrics"].update(tail)
    v = tail["verdict"]
    rec["status"] = v["status"]
    if v["status"] not in ("clean", "partial"):
        rec["errors"] = [
            {
                "code": v.get("category") or "compile_fail",
                "cat": v.get("category"),
                "payload": v.get("payload") or tail["compile"].get("first_error"),
            }
        ]
    elif v.get("category"):
        rec["errors"] = [
            {"code": v["category"], "cat": v["category"], "payload": v.get("payload")}
        ]
    rec["sig"] = benchlib.verdict_sig(v, tail["compile"].get("first_error"))
    rec["dur_s"] = round(time.monotonic() - t0, 2)
    return rec


def stage_compile(
    args: argparse.Namespace,
    out_dir: Path,
    ids: list[str],
    log: RecLog,
    xlat_recs: dict,
) -> None:
    todo = []
    for pid in ids:
        # resume 键含 upstream：zh 臂对 mock/real 产物各记一格
        if args.arm == "zh":
            marker = workdir(out_dir, pid) / "zh" / ".xlat-arm.json"
            up = ""
            if marker.exists():
                with contextlib.suppress(Exception):
                    up = json.loads(marker.read_text()).get("arm") or ""
            if not args.rerun and up and log.is_done(pid, "zh", up, recode=args.recode):
                continue
        elif not args.rerun and log.is_done(pid, "base", recode=args.recode):
            continue
        todo.append(pid)
    print(f"compile[{args.arm}]: {len(todo)} to run (jobs={args.jobs})", flush=True)
    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(_compile_one, p, out_dir, args, xlat_recs): p for p in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = crash_rec(pid, "compile", args.arm, e, time.monotonic())
            log.append(rec)
            v = (rec.get("metrics") or {}).get("verdict") or {}
            print(
                f"  [{i}/{len(todo)}] {pid} -> {rec['status']} cat={v.get('category') or '-'} ({rec['dur_s']}s)",
                flush=True,
            )
            if args.time_budget and time.monotonic() - t_start > args.time_budget:
                break


# ================================================================ fixloop
def _fixloop_one(
    pid: str, out_dir: Path, args: argparse.Namespace, comp_rec: dict, sink: CaseSink
) -> dict:
    """pipe_fix_condition 同构：splice/ 就地修复 + usermode 复判。

    splice/ 即 zh 臂编后树（normalize+译+inject+编译产物）；修复终态落同目录，
    ``post`` 复判编译与 compile 记录同 verdict 刻度。
    """
    t0 = time.monotonic()
    upstream = comp_rec.get("upstream") or ""
    rec = base_rec(pid, "fixloop", "fix", upstream)
    wid = workdir(out_dir, pid)
    splice = wid / "splice"
    if not splice.is_dir():
        rec["status"] = "skip"
        rec["errors"] = [
            {"code": "no_splice", "cat": "upstream", "payload": "splice/ missing"}
        ]
        return finish_rec(rec, t0)
    pj = wid / "parse.json"
    main_rel = None
    if pj.exists():
        main_rel = json.loads(pj.read_text()).get("main_rel")
    if not main_rel:
        m = find_main_tex(splice)
        main_rel = m.relative_to(splice).as_posix() if m else None
    if not main_rel:
        rec["status"] = "error"
        rec["errors"] = [
            {
                "code": "no_main_tex",
                "cat": "fixloop",
                "payload": classify_no_main(splice) or "",
            }
        ]
        return finish_rec(rec, t0)

    texmf = wid / "_texmf"
    if texmf.exists():
        shutil.rmtree(texmf)  # 冷启动——防半成品 usertree 偏暖（同 pipe_fix_condition）
    flb._init_usertree(texmf)
    eng = flb._NoSandbox(
        XelatexEngine(halt_on_error=True, texmfhome=texmf, repository=flb.TUNA_TLNET)
    )
    idx = flb._index()
    if idx is not None:
        eng.filemap = idx.query
    try:
        cell = fixloop(
            splice,
            eng,
            ruleset=flb.RS,
            engine_name="xelatex",
            corpus_id=pid,
            cond="fixloop",
            runner=flb._texmf_runner(texmf),
            case_sink=sink,
            llm_hook=make_llm_hook() if getattr(args, "llm", False) else None,
            compile_timeout=args.timeout,
        )
    except Exception as e:
        cell = {
            "project": pid,
            "engine": "xelatex",
            "verdict": f"harness_crash:{type(e).__name__}",
            "log_excerpt": str(e)[:500],
            "rounds": [],
            "actions": [],
        }
    cell_wall = round(time.monotonic() - t0, 1)
    jeng = XelatexEngine(
        halt_on_error=False, texmfhome=texmf, repository=flb.TUNA_TLNET
    )
    res = jeng.compile(splice, main_rel, timeout=args.timeout, sandbox=False)
    # 复判沿用 compile 臂的 CJK 期待口径 (0-chunk 主文档不判 cjk_chars=0)
    expect_cjk = (comp_rec.get("metrics") or {}).get("expect_cjk", True)
    tail = benchlib.judge_dict(res, expect_cjk=expect_cjk)

    rounds = cell.get("rounds") or []
    fcat = cell.get("final_cat") or (rounds[-1].get("category") if rounds else None)
    fpay = ""
    for rd in reversed(rounds):
        if rd and (rd.get("pay") or rd.get("payload")):
            fpay = rd.get("pay") or rd.get("payload")
            break
    fv = str(cell.get("verdict") or "?")
    v = tail["verdict"]
    rec["status"] = v["status"]
    rec["metrics"].update(
        {
            "mode": args.on,
            "compile_status_before": comp_rec.get("status"),
            "fixloop_verdict": fv,
            "final_cat": fcat,
            "rounds": len(rounds),
            "n_actions": len(cell.get("actions") or []),
            "installed": cell.get("installed") or [],
            "floor_restored": bool(cell.get("floor_restored")),
            "fixloop_wall_s": cell_wall,
            "post": tail,
        }
    )
    if rec["status"] != "clean":
        sig = fv
        if fv.startswith("unfixable:") and fcat and str(fcat) not in fv:
            sig = f"{fv}:{fcat}"
        if fpay:
            sig = f"{sig}:{fpay}"
        rec["errors"] = [{"code": fv, "cat": fcat, "payload": fpay}]
        rec["sig"] = sig
    rec["dur_s"] = round(time.monotonic() - t0, 2)
    return rec


def _on_misschar(crec: dict) -> bool:
    """缺字窄口：partial ∧ missing_chars>0 —— missing_char_fix 可修的子集。

    与 e2e_real_bench._want_fix 同口径；其余 warning 级 partial 不进
    （partial→fail 回退教训）。
    """
    v = (crec.get("metrics") or {}).get("verdict") or {}
    return crec.get("status") == "partial" and (v.get("missing_chars") or 0) > 0


_ON_PRED: dict[str, object] = {
    "fail": lambda c: c.get("status") == "fail",
    "nonclean": lambda c: c.get("status") in {"fail", "partial"},
    "misschar": _on_misschar,
    "clean": lambda c: c.get("status") == "clean",
    # reject/skip 无有效 splice 树 —— post-judge 编译被拒英文树会虚增
    # union-pdf (1e 审计: +414 phantom 上限)。clean 保留供非回归复判。
    "all": lambda c: c.get("status") not in {"reject", "skip"},
}


def stage_fixloop(
    args: argparse.Namespace, out_dir: Path, ids: list[str], log: RecLog
) -> None:
    want = _ON_PRED[args.on]
    want_ids = set(ids)
    # (pid,zh) 可并存多个 upstream 键 —— load_latest dict 插序是首见序,
    # cand[-1] 拿到的不是最新 compile 格 (1e 审计); 直扫文件按 append 序取。
    cand_latest: dict[str, dict] = {}
    comp_path = out_dir / "records" / "compile.jsonl"
    if comp_path.exists():
        for rec in benchlib.iter_jsonl(comp_path):
            if rec.get("id") in want_ids and rec.get("arm") == "zh":
                cand_latest[rec["id"]] = rec  # append 序覆盖 = 末条
    todo: list[tuple[str, dict]] = []
    for pid in ids:
        crec = cand_latest.get(pid)
        if crec is None:
            continue
        if not want(crec):
            continue
        if (
            log.is_done(pid, "fix", crec.get("upstream") or "", recode=args.recode)
            and not args.rerun
        ):
            continue
        todo.append((pid, crec))
    print(f"fixloop[on={args.on}]: {len(todo)} cells (jobs={args.jobs})", flush=True)
    if not todo:
        return
    sink = CaseSink(out_dir / "cases.jsonl")
    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {
            ex.submit(_fixloop_one, p, out_dir, args, cr, sink): p for p, cr in todo
        }
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = crash_rec(pid, "fixloop", "fix", e, time.monotonic())
            log.append(rec)
            fv = (rec.get("metrics") or {}).get("fixloop_verdict") or "-"
            print(
                f"  [{i}/{len(todo)}] {pid} -> {rec['status']} fixloop={fv} ({rec['dur_s']}s)",
                flush=True,
            )
            if args.time_budget and time.monotonic() - t_start > args.time_budget:
                break


# ================================================================ main
def _add_shared(p: argparse.ArgumentParser, jobs: int) -> None:
    p.add_argument("--ids", default=None, help="逗号分隔显式 id（smoke 用）")
    p.add_argument(
        "--layers", default="core", help="core / core,booster / core,booster,hot"
    )
    p.add_argument("--n", type=int, default=0, help="抽样式量；0=全集")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--only", default=None, help="id 子串过滤")
    p.add_argument("--jobs", type=int, default=jobs)
    p.add_argument("--tag", default="stagerun", help="结果目 stagerun-{tag}-{date}")
    p.add_argument("--dir", default=None, help="显式结果目（覆盖 --tag/--date）")
    p.add_argument("--date", default=str(datetime.now(UTC).date()))
    p.add_argument("--rerun", action="store_true", help="无视 records 重跑")
    p.add_argument(
        "--recode",
        action="store_true",
        help="产码印章（record.code=HEAD sha±dirty）不符/缺印的格重跑——splice/parse 层修复验证用",
    )
    p.add_argument(
        "--upstream", default=None, help="上游可收 status CSV（默认各 stage 自定）"
    )
    p.add_argument("--time-budget", type=float, default=0.0, help="秒；0=不限")
    p.add_argument(
        "--no-preflight",
        action="store_true",
        help="跳过启动自检（全量 import+mock 链）",
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="stagerun.py", description=__doc__.splitlines()[0]
    )
    sub = ap.add_subparsers(dest="stage", required=True)

    p_ing = sub.add_parser(
        "ingest", help="manifest→copytree → work/{id}/src/（IA 拉取 stub，归数据侧）"
    )
    _add_shared(p_ing, 8)

    p_par = sub.add_parser(
        "parse", help="route+normalize+parse_file → parse.json + zh/"
    )
    _add_shared(p_par, 6)
    p_par.add_argument(
        "--engine",
        default="xelatex",
        choices=["auto", "xelatex", "tectonic"],
        help="normalize 目标引擎",
    )

    p_xl = sub.add_parser("xlat", help="XlatPipeline → zh/ 就地翻译 + 逐块明细")
    _add_shared(p_xl, 4)
    p_xl.add_argument(
        "--arm",
        required=True,
        choices=["mock", "real", "sabotage-b", "sabotage-c", "perturb"],
    )
    p_xl.add_argument("--sem", type=int, default=4, help="全局网关信号量（gwcap 硬闸）")
    p_xl.add_argument(
        "--concurrency", type=int, default=10, help="单篇 pipeline 内部 worker 数"
    )
    p_xl.add_argument("--model", default="swe-2-medium")
    p_xl.add_argument("--base-url", default="http://100.105.212.52:3003")
    p_xl.add_argument("--api-key", default="240127")
    p_xl.add_argument("--no-probe", action="store_true")

    p_cp = sub.add_parser("compile", help="splice+inject+compile+judge（zh|base）")
    _add_shared(p_cp, 4)
    p_cp.add_argument("--arm", required=True, choices=["zh", "base"])
    p_cp.add_argument(
        "--engine", default="xelatex", choices=["auto", "xelatex", "tectonic"]
    )
    p_cp.add_argument(
        "--xlat-arm", default=None, help="钉住 zh/ 期望的 xlat 臂（防陈旧树）"
    )
    p_cp.add_argument("--timeout", type=float, default=240.0)
    p_cp.add_argument(
        "--post",
        default="none",
        choices=["none", "l2"],
        help="l2 回灌（暂 stub——需 _TreeRun 内存态）",
    )

    p_fx = sub.add_parser("fixloop", help="compile 非 clean 格 → fixloop+CaseSink")
    _add_shared(p_fx, 4)
    p_fx.add_argument(
        "--on",
        default="fail",
        choices=["fail", "nonclean", "misschar", "clean", "all"],
        help="目标格选择：fail(默认)/nonclean/misschar(缺字 partial 窄口)/clean(幂等探针)/all",
    )
    p_fx.add_argument("--timeout", type=float, default=240.0)
    p_fx.add_argument(
        "--llm",
        action="store_true",
        help="escalate_llm 规则接 LLM 修复钩（默认关；网关走 TEXLATE_* env/默认）",
    )

    args = ap.parse_args()
    out_dir = out_dir_of(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "records").mkdir(exist_ok=True)
    (out_dir / "work").mkdir(exist_ok=True)
    gi = out_dir / ".gitignore"
    if not gi.exists():
        gi.write_text(
            "work/\n", encoding="utf-8"
        )  # 重产物树不进库（对齐 bench/work_*/ 惯例）
    touch_run_meta(out_dir, args)

    entries = erb.load_manifest(set(args.layers.split(",")))
    ids = select_ids(entries, args, args.stage)
    print(
        f"== {args.stage} n={len(ids)} layers={args.layers} seed={args.seed} -> {out_dir}",
        flush=True,
    )

    if not args.no_preflight:
        errs = asyncio.run(erb.preflight())
        if errs:
            print("preflight FAILED — 源码树不一致，拒绝跑:", flush=True)
            for e in errs:
                print(f"  {e}", flush=True)
            sys.exit(2)
        print("preflight ok", flush=True)

    log = RecLog(out_dir / "records" / f"{args.stage}.jsonl")
    try:
        if args.stage == "ingest":
            stage_ingest(args, out_dir, ids, entries, log)
        elif args.stage == "parse":
            stage_parse(args, out_dir, ids, log)
        elif args.stage == "xlat":
            stage_xlat(
                args,
                out_dir,
                ids,
                log,
                load_latest(out_dir / "records" / "parse.jsonl"),
            )
        elif args.stage == "compile":
            if args.post == "l2":
                print(
                    "note: --post l2 未接线（需 _TreeRun 内存态；TODO 见 docstring）",
                    flush=True,
                )
            stage_compile(
                args, out_dir, ids, log, load_latest(out_dir / "records" / "xlat.jsonl")
            )
        elif args.stage == "fixloop":
            stage_fixloop(args, out_dir, ids, log)
    finally:
        log.close()
        mark_run_finished(out_dir)
    print(f"done -> {out_dir}/records/{args.stage}.jsonl", flush=True)


if __name__ == "__main__":
    main()
