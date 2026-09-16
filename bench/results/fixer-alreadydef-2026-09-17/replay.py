# replay.py — fixer-alreadydef 单格 fixloop 复现 (stagerun._fixloop_one 同构).
# 用法: uv run python bench/results/fixer-alreadydef-2026-09-17/replay.py <pid> [pid...]
# splice 树复制到本目录 work/<pid>/splice 再修复——不动 stagerun 共享树
# (compile --rerun 波正在重写原树)。
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "py"))

import benchlib  # noqa: E402
import fixloop_bench as flb  # noqa: E402
from texlate.compile.engine import XelatexEngine  # noqa: E402
from texlate.compile.fixloop import CaseSink, Ruleset, fixloop  # noqa: E402
from texlate.compile.inject import find_main_tex  # noqa: E402

SRC = Path("bench/results/stagerun-loop1-2026-09-16")
OUT = Path("bench/results/fixer-alreadydef-2026-09-17")
RULES_OVERRIDE = os.environ.get("RULES_YAML")


def replay(pid: str) -> dict:
    t0 = time.monotonic()
    wid = OUT / "work" / pid
    splice = wid / "splice"
    if splice.exists():
        shutil.rmtree(splice)
    shutil.copytree(SRC / "work" / pid / "splice", splice)
    src = SRC / "work" / pid / "src"
    if src.is_dir():
        if (wid / "src").exists():
            shutil.rmtree(wid / "src")
        shutil.copytree(src, wid / "src")
    pj = SRC / "work" / pid / "parse.json"
    main_rel = json.loads(pj.read_text()).get("main_rel") if pj.exists() else None
    if not main_rel:
        m = find_main_tex(splice)
        main_rel = m.relative_to(splice).as_posix() if m else None
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
    rs = flb.RS
    if RULES_OVERRIDE or (wid / "src").is_dir():
        rs = Ruleset.load(Path(RULES_OVERRIDE) if RULES_OVERRIDE else None)
        for rule in rs.rules:
            act = rule.raw.get("action") or {}
            if (
                act.get("kind") == "builtin_transform"
                and act.get("function") == "restore_support_from_src"
            ):
                act.setdefault("params", {})["baseline_dir"] = str(wid / "src")
    sink = CaseSink(OUT / "cases.jsonl")
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
    jeng = XelatexEngine(halt_on_error=False, texmfhome=texmf, repository=flb.TUNA_TLNET)
    res = jeng.compile(splice, main_rel, timeout=240, sandbox=False)
    tail = benchlib.judge_dict(res, expect_cjk=True)
    return {
        "pid": pid,
        "verdict": cell.get("verdict"),
        "rounds": cell.get("rounds"),
        "actions": cell.get("actions"),
        "post": tail["verdict"],
        "wall_s": round(time.monotonic() - t0, 1),
    }


if __name__ == "__main__":
    out = []
    for pid in sys.argv[1:]:
        r = replay(pid)
        out.append(r)
        print(json.dumps(r, ensure_ascii=False, indent=1), flush=True)
    (OUT / "replay-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
