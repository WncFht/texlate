"""verb 层共享读件——index 打开 / run 引用解析 / eval_records 投影 /
$blob 解引用。

kernel import 一律函数内惰性（与 verbs 的既有 lazy-kernel 约定一致）。
``err`` 参数保留各 verb 的 stderr 前缀（``qual:``/``xlat:``）；默认
``_err`` 裸 print，兼容 dossier/gate 的旧内联 print 口径。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _open_index(err=_err):
    """Index + tail_ingest（``kernel.index.open_index`` 薄转）。"""
    from kernel import index as index_mod

    return index_mod.open_index(warn=err)


def _run_ref(ref: str, err=_err):
    """run 引用 → (run_name, rundir)。kind/date/slug 或 runs/ 下目录。"""
    from kernel import paths

    p = Path(ref)
    if p.is_dir():
        try:
            rel = p.resolve().relative_to(paths.runs_dir().resolve())
        except ValueError:
            rel = None
        if rel is not None and len(rel.parts) >= 3:
            return "/".join(rel.parts[:3]), p
        err(f"run dir outside runs/: {ref}")
        return None, None
    parts = ref.split("/")
    if len(parts) == 3:
        d = paths.run_dir(*parts)
        if d.is_dir():
            return ref, d
    err(f"run not found: {ref!r} (need kind/date/slug or a runs/ dir)")
    return None, None


def _unblob(val, rundir: Path | None):
    """rundir 派生 derived/blobs 目录 → ``kernel.report._unblob``（严格
    marker 形才解；宽松版见 verbs/gate.py 本地件——两口径勿混）。"""
    from kernel import report as report_mod

    blob_dir = None
    if rundir is not None and (rundir / "derived" / "blobs").is_dir():
        blob_dir = rundir / "derived" / "blobs"
    return report_mod._unblob(val, blob_dir)


def _payload(raw, rundir: Path | None):
    """json 列 → 值 → $blob 解引用（blob 文件读不出则 marker 原样）。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return _unblob(raw, rundir)


def _eval_rows(idx, run_name: str) -> list[dict]:
    """末条胜集：(idc,arm,up,variant) 键 seq 大者胜。"""
    wins: dict[tuple, dict] = {}
    for r in idx.conn.execute(
        "SELECT seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"
        "dur_s,metrics,errors,ts FROM eval_records WHERE run=? ORDER BY seq",
        (run_name,),
    ):
        wins[(r["idc"], r["arm"], r["up"], r["variant"])] = dict(r)
    return list(wins.values())
