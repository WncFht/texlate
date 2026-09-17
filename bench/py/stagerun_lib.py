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
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

ROOT = Path(__file__).resolve().parents[2]
#: TEXLATE_SRC 可指冻结快照（同 e2e_real_bench：bench 期间 src/ 被改时隔离）。
sys.path.insert(0, os.environ.get("TEXLATE_SRC", str(ROOT / "src")))

# 同目录 bench 脚本经 sys.path[0] 可 import；模块级零副作用。
import benchlib

CORPUS = ROOT / "bench/corpus_v3"

#: resume 终态集（单源 benchlib）——记了这些 status 的 (id,arm,upstream)
#: 不再跑；skip（上游门）与 error（harness 崩）属可重试类。
DONE_STATUS = benchlib.DONE_STATUS
RETRIABLE_STATUS = benchlib.RETRIABLE_STATUS

STAGES = ("ingest", "parse", "xlat", "compile", "fixloop")


# ================================================================ 选样与 records
def select_ids(entries: list[dict], args: argparse.Namespace, stage: str) -> list[str]:
    """--ids 显式集 或 manifest 全量/--n 抽样子集（--seed 定序）。

    ``--n`` 抽样全 stage 共用 ``benchlib.pick_sample``（候选限 extracted/ 在盘
    者）——同 --n/--seed 跨 stage 命中同一子集。ingest 全量（--n 0）路径
    对未物化条目记 skip/reject（IA 拉取留 stub 归数据侧，见 stagerun.py
    docstring）；--ids 亦可定点。
    """
    if args.ids:
        want = {i.strip() for i in args.ids.split(",") if i.strip()}
        have = {e["id"] for e in entries}
        return sorted((want & have) | (want - have))
    if args.n and args.n > 0:
        pool = benchlib.pick_sample(entries, CORPUS, args.n, args.seed)
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
    return benchlib.rec_key(rec)


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
    return (
        benchlib.latest_by(benchlib.iter_jsonl(path), benchlib.rec_key)
        if path.exists()
        else {}
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
