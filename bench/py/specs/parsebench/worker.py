r"""specs.parsebench.worker — 子进程测量体叶 (parsebench 拆分叶).

``_worker_run``：paper.json 先行（拓扑件在 kill 下幸存），files.jsonl
逐行 flush（被杀后残留行仍是真账）；``_worker_cli`` =
``--worker <srcdir> <workdir> <paper_id> <timeout_s>`` 入口，由门面
``parsebench.py`` 的 ``__main__`` 尾块经 ``__getattr__`` 惰性解到这里。
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs.parsebench.measure import file_metrics
from specs.parsebench.topology import _topology, rglob_tex


def _worker_run(src: Path, wd: Path, paper_id: str, timeout_s: int) -> int:
    """子进程测量体：paper.json 先行（拓扑件在 kill 下幸存），files.jsonl
    逐行 flush（被杀后残留行仍是真账——cell 内复刻旧「行在=测成」语义）。"""
    tex_files = sorted(rglob_tex(src))
    paper, parsed, roles, non_utf8_rp = _topology(src, tex_files, paper_id, timeout_s)
    (wd / "paper.json").write_text(
        json.dumps(paper, ensure_ascii=False), encoding="utf-8"
    )
    with (wd / "files.jsonl").open("w", encoding="utf-8") as fh:
        for p in tex_files:
            rel = p.relative_to(src).as_posix()
            rp = str(p.resolve())
            e = file_metrics(
                p,
                rel,
                paper_id,
                roles[rel],
                rp in non_utf8_rp,
                timeout_s,
                cached=parsed.get(rp),
            )
            benchlib.write_jsonl(fh, e)
            fh.flush()
    return 0


def _worker_cli() -> int:
    """``--worker <srcdir> <workdir> <paper_id> <timeout_s>`` 入口。"""
    if len(sys.argv) != 6 or sys.argv[1] != "--worker":
        print(
            "usage: parsebench --worker <srcdir> <workdir> <paper_id> <timeout_s>",
            file=sys.stderr,
        )
        return 2
    try:
        return _worker_run(
            Path(sys.argv[2]),
            Path(sys.argv[3]),
            sys.argv[4],
            int(sys.argv[5]),
        )
    except Exception:
        traceback.print_exc()
        return 1
