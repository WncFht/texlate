#!/usr/bin/env python3
"""单格 fixloop 复放 (mirror stagerun._fixloop_one) — scratch ruleset 版.

用法: uv run python replay.py
现场: work/1306.0281/ 为 stagerun 格的拷贝; scratch-rules.yaml = 现行
rules.yaml + rules-fragment.yaml 的 acm_proc_article-sp.cls 条目替换.
产出: replay-cell.json (fixloop cell dict) + judge.json (post 复判) +
cases.jsonl (CaseSink) + work/1306.0281/splice 就地修复终态.
"""

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/fanghaotian/src/texlate/bench/py")
import benchlib
import fixloop_bench as flb
from texlate.compile.engine import XelatexEngine
from texlate.compile.fixloop import CaseSink, Ruleset, fixloop

BASE = Path(__file__).resolve().parent
PID = "1306.0281"
wid = BASE / "work" / PID
splice = wid / "splice"
texmf = wid / "_texmf"

t0 = time.monotonic()
if texmf.exists():
    shutil.rmtree(texmf)
flb._init_usertree(texmf)
eng = flb._NoSandbox(
    XelatexEngine(halt_on_error=True, texmfhome=texmf, repository=flb.TUNA_TLNET)
)
idx = flb._index()
if idx is not None:
    eng.filemap = idx.query

rs = Ruleset.load(BASE / "scratch-rules.yaml")
if (wid / "src").is_dir():
    for rule in rs.rules:
        act = rule.raw.get("action") or {}
        if (
            act.get("kind") == "builtin_transform"
            and act.get("function") == "restore_support_from_src"
        ):
            act.setdefault("params", {})["baseline_dir"] = str(wid / "src")

pj = json.loads((wid / "parse.json").read_text())
main_rel = pj.get("main_rel")
sink = CaseSink(BASE / "cases.jsonl")
cell = fixloop(
    splice,
    eng,
    ruleset=rs,
    engine_name="xelatex",
    corpus_id=PID,
    cond="fixloop-scratch",
    runner=flb._texmf_runner(texmf),
    case_sink=sink,
    llm_hook=None,
)
cell["wall_s"] = round(time.monotonic() - t0, 1)
(BASE / "replay-cell.json").write_text(json.dumps(cell, ensure_ascii=False, indent=2))

# post 复判 (同 _fixloop_one: halt_on_error=False 宽松编译 + judge_dict)
jeng = XelatexEngine(halt_on_error=False, texmfhome=texmf, repository=flb.TUNA_TLNET)
res = jeng.compile(splice, main_rel, sandbox=False)
tail = benchlib.judge_dict(res, expect_cjk=True)
(BASE / "judge.json").write_text(json.dumps(tail, ensure_ascii=False, indent=2))
print("verdict:", cell.get("verdict"), "| judge:", json.dumps(tail, ensure_ascii=False))
