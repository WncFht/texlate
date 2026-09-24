"""一次性暖存：为所有已有 done 任务预算 seqpos.json（reader 首开免懒算峰）。

幂等——seqpos_for_task 自带 mtime+v 缓存命中，已暖的秒回。
seqpos 升级（_VERSION bump）后必须重跑，否则 reader 首开逐个懒算。
用法：.venv/bin/python tools/seqpos_warm.py
"""

import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "src")
from texlate.server.seqpos import seqpos_for_task  # noqa: E402

TASKS = Path.home() / ".texlate/tasks"

for tdir in sorted(TASKS.iterdir()):
    dual_p = tdir / "dual.json"
    if (
        not dual_p.is_file()
        or not (tdir / "en.pdf").is_file()
        or not (tdir / "zh.pdf").is_file()
    ):
        continue
    try:
        dual = json.loads(dual_p.read_text(encoding="utf-8"))
    except Exception:
        continue
    t0 = time.time()
    try:
        r = seqpos_for_task(tdir, dual)
        n = len(r) if isinstance(r, dict) else 0
        print(f"{tdir.name}: {time.time() - t0:.1f}s seqs={n}", flush=True)
    except Exception:
        traceback.print_exc()
