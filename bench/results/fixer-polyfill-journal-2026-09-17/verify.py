# fixer-polyfill-journal verification driver — 复刻 stagerun._fixloop_one,
# 差异: Ruleset.load(path=rules-test.yaml) 测候选条目; 工作树复制到本目录
# (复跑 compile wave 会并发改写原 work/<pid>/splice, 快照隔离)。
# 用法: uv run python bench/results/fixer-polyfill-journal-2026-09-17/verify.py <pid> [pid...]
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path("/home/fanghaotian/src/texlate")
sys.path.insert(0, str(ROOT / "bench" / "py"))

import fixloop_bench as flb  # noqa: E402
from texlate.compile.engine import XelatexEngine  # noqa: E402
from texlate.compile.fixloop import CaseSink, Ruleset, fixloop  # noqa: E402

SRC_ROOT = ROOT / "bench/results/stagerun-loop1-2026-09-16/work"
MY_DIR = ROOT / "bench/results/fixer-polyfill-journal-2026-09-17"
RULES = MY_DIR / "rules-test.yaml"
WORK = MY_DIR / "work"


def dirpid(pid: str) -> str:
    return pid.replace("/", "--")


def run_one(pid: str) -> dict:
    wid = WORK / dirpid(pid)
    src_wid = SRC_ROOT / dirpid(pid)
    if not (src_wid / "splice").is_dir():
        return {"pid": pid, "verdict": "no_splice"}
    for sub in ("splice", "src"):
        dst, srcp = wid / sub, src_wid / sub
        if dst.exists():
            shutil.rmtree(dst)
        if srcp.is_dir():
            shutil.copytree(srcp, dst, symlinks=True)
    pj = src_wid / "parse.json"
    main_rel = json.loads(pj.read_text()).get("main_rel") if pj.exists() else None
    splice = wid / "splice"
    texmf = wid / "_texmf"
    if texmf.exists():
        shutil.rmtree(texmf)
    flb._init_usertree(texmf)
    eng = flb._NoSandbox(
        XelatexEngine(halt_on_error=True, texmfhome=texmf, repository=flb.TUNA_TLNET)
    )
    idx = flb._index()
    if idx is not None:
        eng.filemap = idx.query
    rs = Ruleset.load(path=RULES)
    if (wid / "src").is_dir():
        for rule in rs.rules:
            act = rule.raw.get("action") or {}
            if (
                act.get("kind") == "builtin_transform"
                and act.get("function") == "restore_support_from_src"
            ):
                act.setdefault("params", {})["baseline_dir"] = str(wid / "src")
    sink = CaseSink(MY_DIR / "cases.jsonl")
    t0 = time.monotonic()
    cell = fixloop(
        splice,
        eng,
        ruleset=rs,
        engine_name="xelatex",
        corpus_id=pid,
        cond="fixloop",
        runner=flb._texmf_runner(texmf),
        case_sink=sink,
        compile_timeout=240.0,
    )
    cell["_wall"] = round(time.monotonic() - t0, 1)
    cell["_main_rel"] = main_rel
    return cell


def main() -> None:
    for pid in sys.argv[1:]:
        try:
            cell = run_one(pid)
        except Exception as e:
            print(f"### {pid}: CRASH {type(e).__name__}: {e}", flush=True)
            continue
        rounds = cell.get("rounds") or []
        print(
            f"### {pid}: {cell.get('verdict')} rounds={len(rounds)} wall={cell.get('_wall')}s",
            flush=True,
        )
        for i, r in enumerate(rounds):
            acts = r.get("actions") or []
            applied = [
                f"{a.get('rule')}[{a.get('note', '')[:80]}]"
                for a in acts
                if a.get("applied")
            ]
            print(
                f"    r{i}: cat={r.get('category')} pay={r.get('payload')} applied={applied}",
                flush=True,
            )


if __name__ == "__main__":
    main()
