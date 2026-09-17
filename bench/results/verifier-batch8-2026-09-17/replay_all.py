#!/usr/bin/env python3
"""batch-8 fire-rate audit — replay stagerun-loop1 cells with current rules.yaml.

Rebuild splice = work/{id}/zh copy + prepare_chinese, fresh _texmf usertree,
fixloop(flb.RS current) + post judge. Mirrors stagerun._fixloop_one.

Usage: uv run python bench/results/verifier-batch8-2026-09-17/replay_all.py
"""

import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/home/fanghaotian/src/texlate/bench/py")
import benchlib
import fixloop_bench as flb
from texlate.compile.engine import XelatexEngine
from texlate.compile.fixloop import CaseSink, Ruleset, fixloop
from texlate.compile.inject import find_main_tex, prepare_chinese

SRC = Path("/home/fanghaotian/src/texlate/bench/results/stagerun-loop1-2026-09-16")
BASE = Path("/home/fanghaotian/src/texlate/bench/results/verifier-batch8-2026-09-17")

# corpus -> (target keys/shims watched, worst orig verdict seen in cases.jsonl)
CELLS = {
    "0806.3501": "iopart.cls+Eref-belt+submitto",
    "0806.2190": "iopart.cls+iopamstrue",
    "1206.1691": "iopart.cls+iopams.sty+fl",
    "1206.0321": "iopart.cls+ams",
    "0806.2706": "iopart.cls+PRL",
    "1907.00292": "tcilatex.tex+func",
    "0806.1203": "tcilatex.tex+FRAME",
    "hep-th/9703079": "tcilatex+QQQ",
    "astro-ph/0605222": "sciii",
    "astro-ph/0307216": "ifnfssone",
    "0806.2482": "elsart1p.cls+corauth",
    "hep-lat/0111059": "elsart.cls+eqntopsep",
    "0707.2284": "elsart.cls+corauth",
    "astro-ph/9901112": "aa.cls+thesaurus",
    "0806.3705": "aa.cls+acknowledgements",
    "astro-ph/0104134": "aipproc.cls+address",
    "1404.0354": "overrideIEEEmargins",
    "0707.3252": "diag",
    "1206.1993": "Bar",
    "2211.04441": "hypersetup",
}


def replay_one(pid: str) -> dict:
    sid = benchlib.safe_id(pid)
    src_wid = SRC / "work" / sid
    wid = BASE / "work" / sid
    splice = wid / "splice"
    texmf = wid / "_texmf"
    t0 = time.monotonic()
    wid.mkdir(parents=True, exist_ok=True)
    if splice.exists():
        shutil.rmtree(splice)
    shutil.copytree(src_wid / "zh", splice, ignore=benchlib.copytree_ignore())

    main_rel = None
    pj = src_wid / "parse.json"
    if pj.exists():
        main_rel = json.loads(pj.read_text()).get("main_rel")
    if not main_rel:
        m = find_main_tex(splice)
        main_rel = m.relative_to(splice).as_posix() if m else None
    if not main_rel:
        return {"corpus": pid, "error": "no_main_tex"}

    inject = prepare_chinese(splice, main_rel)

    if texmf.exists():
        shutil.rmtree(texmf)
    flb._init_usertree(texmf)
    eng = flb._NoSandbox(
        XelatexEngine(halt_on_error=True, texmfhome=texmf, repository=flb.TUNA_TLNET)
    )
    idx = flb._index()
    if idx is not None:
        eng.filemap = idx.query

    rs = Ruleset.load()
    if (src_wid / "src").is_dir():
        for rule in rs.rules:
            act = rule.raw.get("action") or {}
            if (
                act.get("kind") == "builtin_transform"
                and act.get("function") == "restore_support_from_src"
            ):
                act.setdefault("params", {})["baseline_dir"] = str(src_wid / "src")

    sink = CaseSink(BASE / "cases.jsonl")
    try:
        cell = fixloop(
            splice,
            eng,
            ruleset=rs,
            engine_name="xelatex",
            corpus_id=pid,
            cond="fixloop",
            runner=flb._texmf_runner(texmf),
            case_sink=sink,
            llm_hook=None,
            compile_timeout=240.0,
        )
    except Exception as e:
        cell = {"verdict": f"harness_crash:{type(e).__name__}", "err": str(e)[:300],
                "rounds": [], "actions": []}

    jeng = XelatexEngine(halt_on_error=False, texmfhome=texmf, repository=flb.TUNA_TLNET)
    res = jeng.compile(splice, main_rel, timeout=240.0, sandbox=False)
    tail = benchlib.judge_dict(res, expect_cjk=True)

    out = {
        "corpus": pid,
        "watch": CELLS[pid],
        "inject": inject,
        "wall_s": round(time.monotonic() - t0, 1),
        "verdict": cell.get("verdict"),
        "final_pdf": cell.get("final_pdf"),
        "rounds": [
            {k: r.get(k) for k in ("round", "cat", "pay", "category", "payload", "pdf", "n_errors")}
            for r in cell.get("rounds") or []
        ],
        "actions": cell.get("actions") or [],
        "judge": tail.get("verdict"),
    }
    (wid / "replay.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main() -> None:
    (BASE / "work").mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    todo = [p for p in CELLS if not only or p in only]
    print(f"replaying {len(todo)} cells", flush=True)
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(replay_one, p): p for p in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            pid = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"corpus": pid, "error": f"{type(e).__name__}: {e}"}
            print(
                f"[{i}/{len(todo)}] {pid} -> {r.get('verdict') or r.get('error')} "
                f"({r.get('wall_s', '?')}s)",
                flush=True,
            )


if __name__ == "__main__":
    main()
