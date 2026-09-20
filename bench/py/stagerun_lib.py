r"""stagerun_lib.py — stagerun 内核：records 账 / resume 谓词 / run_meta / 选样。

``stagerun.py`` 薄 CLI 与各 ``stage_*.py`` 驱动共用的 kernel。本模块不引
``texlate.*``——系统 python3 可载（同 benchlib 约束）；``TEXLATE_SRC``
冻结快照的 sys.path 设置仍放这里，stage_* 模块先 ``import stagerun_lib``
即得同口径导入面（与 e2e_real_bench 顶部惯例同源）。

契约细节见 ``stagerun.py`` 模块 docstring（work/{id}/ 产物树 / resume
语义 / 与规格 §1/§3 的有意偏差）。
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[2]
#: TEXLATE_SRC 可指冻结快照（同 e2e_real_bench：bench 期间 src/ 被改时隔离）。
sys.path.insert(0, os.environ.get("TEXLATE_SRC", str(ROOT / "src")))

# 同目录 bench 脚本经 sys.path[0] 可 import；模块级零副作用。
import benchlib

#: TEXLATE_CORPUS 可换语料根（日更 soak 用 bench/corpus_daily；默认钉版 v3）。
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))

#: resume 终态集（单源 benchlib）——记了这些 status 的 (id,arm,upstream)
#: 不再跑；skip（上游门）与 error（harness 崩）属可重试类。
DONE_STATUS = benchlib.DONE_STATUS
RETRIABLE_STATUS = benchlib.RETRIABLE_STATUS

STAGES = ("ingest", "parse", "xlat", "compile", "fixloop")


# ================================================================ 选样与 records
#: 论文 id 规范形（``--`` → ``/``，``benchlib.safe_id`` 逆）——单源下沉
#: ``benchlib.canon_id``（stdlib-only 消费方免 import 本内核），此处保名
#: 兼作 ``stagerun.canon_id`` re-export 链源头。
canon_id = benchlib.canon_id


def dedup_wids(ids: list[str]) -> list[str]:
    """同 workdir 任务去重闸——同 wid 只留一个任务（首见者），撞名者丢弃 +
    stderr 显式化。

    ``canon_id`` 归一后 id 无 ``--``，safe_id 在该空间单射——同 wid ⟺ 同
    id，本闸正常路径恒不裁；兜住的是绕过 ``select_ids`` 直调 stage_* 的
    调用方（撞名对并发 = 双任务同树互 rmtree，同键双记 append 账）。丢弃
    即「同 wid 串行化」的最强形：同 wid 的两任务是同一份功，串行也只是
    重复跑。
    """
    seen: dict[str, str] = {}  # sid → 首见 raw（撞名报告对偶）
    out: list[str] = []
    dropped: list[str] = []
    for raw in ids:
        pid = canon_id(raw)
        sid = benchlib.safe_id(pid)
        if sid in seen:
            dropped.append(f"{raw}≡{seen[sid]}")
            continue
        seen[sid] = raw
        out.append(pid)
    if dropped:
        print(
            f"  wid 撞名去重: {len(dropped)} 个任务丢弃（同 workdir）: {dropped}",
            file=sys.stderr,
        )
    return out


def select_ids(entries: list[dict], args: argparse.Namespace, stage: str) -> list[str]:
    """--ids 显式集 或 manifest 全量/--n 抽样子集（--seed 定序）。

    ``--n`` 抽样全 stage 共用 ``benchlib.pick_sample``（候选限 extracted/ 在盘
    者）——同 --n/--seed 跨 stage 命中同一子集。ingest 全量（--n 0）路径
    对未物化条目记 skip/reject（IA 拉取留 stub 归数据侧，见 stagerun.py
    docstring）；--ids 亦可定点。

    所有产出 id 经 ``canon_id`` 归一——``--ids`` 收 flat 拼写自动回规范形
    （撞名对 set 语义坍缩成单任务）；``--only`` 子串过滤同口径 canon。
    """
    if args.ids:
        raw = [i.strip() for i in args.ids.split(",") if i.strip()]
        want = {canon_id(i) for i in raw}
        changed = sorted({f"{i}→{canon_id(i)}" for i in raw if i != canon_id(i)})
        if changed:
            print(f"  id 拼写归一: {', '.join(changed)}", file=sys.stderr)
        have = {canon_id(e["id"]) for e in entries}
        return sorted((want & have) | (want - have))
    if args.n and args.n > 0:
        pool = sorted(
            {
                canon_id(i)
                for i in benchlib.pick_sample(entries, CORPUS, args.n, args.seed)
            }
        )
    elif stage == "ingest":
        pool = sorted({canon_id(e["id"]) for e in entries})
    else:
        pool = sorted(
            {
                canon_id(e["id"])
                for e in entries
                if (CORPUS / e["id"] / "extracted").is_dir()
            }
        )
    if args.only:
        only = canon_id(args.only)
        pool = [i for i in pool if only in i]
    return pool


def _rec_key(rec: dict) -> tuple[str, str, str]:
    """records 账键——id 分量 canon 归一：flat 拼写存量账与规范形新账同键
    （loop1 双拼写并存实证：65 对 id 分裂成两套 done 键 → resume 互不认）。"""
    pid, arm, upstream = benchlib.rec_key(rec)
    return (canon_id(pid), arm, upstream)


@functools.cache
def _code_stamp() -> str:
    """产码印章（``<sha>``/``<sha>-dirty``）——单源 ``benchlib.code_stamp``，进程内一次。

    records 终态格带印：splice/parse 层修复落地后，旧格 work/ tex 是陈字节，
    ``is_done`` 的 resume 谓词无码感会整篇 carry-over（0707.3950 同款坑，
    e2e_real_bench ``090975d`` 已实证）。``--recode`` 时印章不符即不续跑。
    """
    return benchlib.code_stamp()


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
        code = self.done.get((canon_id(pid), arm, upstream))
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
    """records 文件 → {(id,arm,upstream): 末条记录}（append 序后者胜）。

    键经 ``_rec_key`` canon 归一——flat 拼写存量账按规范形键命中；
    同篇双拼写并存时 append 序跨拼写末条胜。
    """
    return (
        benchlib.latest_by(benchlib.iter_jsonl(path), _rec_key) if path.exists() else {}
    )


def make_sig(errors: list[dict]) -> str:
    """triage 契约：ok 级无 sig；否则 errors[0] 的 cat:pay 合成签名。"""
    return benchlib.errors_sig(errors)


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
    rec["sig"] = make_sig(rec["errors"])
    return rec


def gate_rec(rec: dict, status: str, code: str, cat: str, payload, t0: float) -> dict:
    """门控/早退终态快填：status + 单条 errors + finish_rec。

    各 stage 的「未真跑即终态」出口（上游门 skip / no_main_tex reject /
    环境 error）原是同型三行散在 compile/fixloop/parse/xlat/ingest——
    收编单源；sig 仍由 finish_rec 从 errors[0] 合成（cat:pay 口径不变，
    cat="upstream" 走 triage._upstream_gated 豁免不出票）。
    """
    rec["status"] = status
    rec["errors"] = [{"code": code, "cat": cat, "payload": payload}]
    return finish_rec(rec, t0)


def load_xlat_marker(wid: Path) -> dict | None:
    """``work/{id}/zh/.xlat-arm.json`` → 解析值；zh/ 或 marker 缺席 → ``None``。

    compile zh 臂 provenance 门与 fixloop --rerun 重建门共用读径（两臂
    原是同型就地抄）。腐 JSON / 非 dict 值原样抛/返回——两臂现状都是
    裸 ``json.loads``（崩 → crash_rec harness 格），读侧不改异常边界；
    调用方要容错口径的自行 suppress（stage_compile 驱动侧既有先例）。
    """
    p = wid / "zh" / ".xlat-arm.json"
    if not p.parent.is_dir() or not p.exists():
        return None
    return json.loads(p.read_text())


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


def _new_run_meta() -> dict:
    """首建 meta（load_run_meta 惰性 default——缺席才付 git_rev 子进程）。"""
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "git_rev": git_rev(),
        "invocations": [],
    }


def touch_run_meta(out_dir: Path, args: argparse.Namespace) -> None:
    """run_meta.json：首建 {created,git_rev,invocations[]}，逐次 append argv。

    ``started_at`` 缺省回填 ``created_at``（run 首触时刻）——triage ``_wall_s``
    读 started_at/finished_at 算真实墙钟；``finished_at`` 由
    ``mark_run_finished`` 在每次 invocation 收尾时推进。
    """
    mp = out_dir / "run_meta.json"
    meta = benchlib.load_run_meta(out_dir, strict=True, default=_new_run_meta)
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
    meta = benchlib.load_run_meta(out_dir, strict=True, default=dict)
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


# ================================================================ stage_* 共用件


def rebuild_splice(zh: Path, splice: Path) -> None:
    """zh/ → splice/ 原样重建：rmtree + copytree——compile zh 臂与 fixloop --rerun 共用序。

    fixloop ``--rerun`` 以当前 zh/ 从头重建（上波就地变异不带入新轮）；
    compile zh 臂是首次建树——原 ``stage_fixloop._rebuild_splice`` 与
    ``stage_compile._compile_one`` 就地同式的两份收敛于此。
    """
    if splice.exists():
        shutil.rmtree(splice)
    shutil.copytree(zh, splice, ignore=benchlib.copytree_ignore())


def resolve_main_rel(
    wid: Path,
    splice: Path,
    rec: dict,
    t0: float,
    *,
    no_main_status: str,
    parse_doc: dict | None = None,
) -> str | None:
    """main_rel 三段式解析：parse.json → find_main_tex 兜底 → no_main_tex 门。

    ``stage_compile._compile_one`` zh 臂与 ``stage_fixloop`` --rerun/就地两路
    三方共用（原 ``_resolve_main_rel`` 上提）。``parse_doc`` 缺省自重读
    parse.json（compile 侧已持有它供 ``_resolve_engine``，传入免二次读）。
    ``no_main_status`` 两臂有意不同：compile=reject（源树判不可修）、
    fixloop=error（compile 记录在而主档失踪属异常）；gate cat 取
    ``rec["stage"]``——恰是 base_rec 写入的 "compile"/"fixloop"，与两臂
    既有口径一致。
    返回 main_rel；命中门则终态经 ``gate_rec`` 写进 rec 并返回 None
    （调用方直 ``return rec``）。
    """
    # texlate 惰性引——本模块 import 期不引 texlate.*（系统 python3 可载约束）。
    from texlate.compile.inject import classify_no_main, find_main_tex

    if parse_doc is None:
        pj = wid / "parse.json"
        parse_doc = json.loads(pj.read_text()) if pj.exists() else None
    main_rel = (parse_doc or {}).get("main_rel")
    if not main_rel:
        m = find_main_tex(splice)
        main_rel = m.relative_to(splice).as_posix() if m else None
    if not main_rel:
        gate_rec(
            rec,
            no_main_status,
            "no_main_tex",
            rec["stage"],
            classify_no_main(splice) or "",
            t0,
        )
        return None
    return main_rel


def run_pool(
    todo: list,
    *,
    submit_fn: Callable,
    pid_fn: Callable,
    log: RecLog,
    args: argparse.Namespace,
    stage: str,
    arm: str,
    progress_fn: Callable,
    executor_cls: type = ThreadPoolExecutor,
) -> None:
    """Executor+as_completed+crash_rec+time_budget 分发骨架（stagerun 驱动共用形）。

    executor 生命周期显式化而非 ``with``：``finally`` 里
    ``shutdown(wait=True, cancel_futures=True)``——与 stage_parse 的
    shutdown 契约同口径。相对旧 ``with`` 块，budget ``break`` 的语义有意
    收窄：排队任务被 cancel 不再白跑（旧形 ``__exit__`` 只 wait，剩余
    任务照跑、副作用照落 work/ 树却无 record 入账）；在飞任务仍等其
    写毕再交棒——wait=False 会把在写树的 worker 丢在后台，下个 stage
    读到残树。

    ``submit_fn(ex, item)`` 提交任务、``pid_fn(item)`` 取 records 键、
    ``progress_fn(i, n, pid, rec)`` 打进度行——各 stage 只差 submit 映射
    与进度字段，其余全同型（原 ``stage_compile._run_pool`` 上提；
    stage_parse 的逐条 submit 变体仍自有循环）。
    """
    ex = executor_cls(max_workers=args.jobs)
    t_start = time.monotonic()
    try:
        futs = {submit_fn(ex, item): pid_fn(item) for item in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = crash_rec(pid, stage, arm, e, time.monotonic())
            log.append(rec)
            progress_fn(i, len(todo), pid, rec)
            if args.time_budget and time.monotonic() - t_start > args.time_budget:
                print(
                    f"time budget {args.time_budget}s — stop ({i}/{len(todo)})",
                    flush=True,
                )
                break
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
