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


# ---------------------------------------------------------------- run stem 并组
#
# import 拆账把一次收割落成 ``<stem>_records_<stage>`` 兄弟 runs 行——读侧
# 按 stem 并组还原账组（dossier/gate 原各带逐字副本，收此单源）。

#: 只认这些尾——run 名尾恰好撞上阶段词才拆，别的 ``_xx`` 尾一律视为 run
#: 名本体。
_STAGE_SUFFIXES = ("ingest", "parse", "xlat", "compile", "fixloop", "base")


def _stem_of(run: str) -> str:
    """run 名去尾部 ``_<stage>`` → 账组 stem（无尾 → 原名）。"""
    for s in _STAGE_SUFFIXES:
        suf = f"_{s}"
        if run.endswith(suf):
            return run[: -len(suf)]
    return run


def _all_runs(idx) -> list[dict]:
    """runs 表全量行——stem 并组池（seed 过滤不影响并组全域）。"""
    rows = idx.conn.execute(
        "SELECT run, run_seq, kind, date, slug FROM runs"
    ).fetchall()
    return [dict(r) for r in rows]


def _stem_group(rows: list[dict], seeds: list[dict], run_arg):
    """seeds（选定 runs 行）→ stem 唯一则并组（run_seq 序）；跨 stem 歧义
    → ``(None, err)``。``rows`` 须为并组池全量（kind/run 过滤只管 seed
    选取，并组恒跨全域——kind 收窄的 run 其 ``_records_<stage>`` 兄弟可能在
    别的 kind 下）。"""
    stems = {_stem_of(str(r["run"])) for r in seeds}
    if len(stems) > 1:
        sample = sorted(stems)[:10]
        more = f" …+{len(stems) - 10}" if len(stems) > 10 else ""
        return None, (
            f"ambiguous run scope {run_arg!r} — {len(stems)} account stems:"
            f" {sample}{more}（--run 给到单个 stem 再试）"
        )
    stem = next(iter(stems))
    group = [r for r in rows if _stem_of(str(r["run"])) == stem]
    group.sort(key=lambda r: r.get("run_seq") or 0)
    return group, None


def _unblob(val, rundir: Path | None):
    """rundir 派生 derived/blobs 目录 → ``kernel.events.unblob``（严格
    marker 形才解——全栈统一口径；gate/dossier 原宽松副本已收编）。"""
    from kernel import events

    blob_dir = None
    if rundir is not None and (rundir / "derived" / "blobs").is_dir():
        blob_dir = rundir / "derived" / "blobs"
    return events.unblob(val, blob_dir)


def _blob_dir_of(d: dict) -> Path | None:
    """records×runs JOIN 行 (kind/date/slug) → run_dir/derived/blobs；
    无 is_dir 闸（读败则 marker 原样，与 None 同果）。"""
    from kernel import paths

    k, dt, s = d.get("kind"), d.get("date"), d.get("slug")
    if not all(isinstance(x, str) for x in (k, dt, s)):
        return None
    return paths.run_dir(k, dt, s) / "derived" / "blobs"


# run→rundir 解析族（输入形各异，勿再长第四种）：
#
# - ``_run_ref(ref)``       CLI 引用形——kind/date/slug 串或 runs/ 下目录路径；
# - ``_rundir(row)``        records×runs JOIN 行形——kind/date/slug 字段；
# - ``dossier._rundir_for_name``  裸 run 名兜底——import-* 平名 glob + k/d/s
#   三切两路兜（dossier 残件，import 拆账命名才够得着）。
# 相关不解名：``_blob_dir_of`` 上行取 row→blobs（无闸）；kernel/paths.run_dir
# 是纯拼路径（从不碰盘）。


def _rundir(run_row: dict | None) -> Path | None:
    """records×runs JOIN 行 (kind/date/slug) → 存在的 run_dir 路径——
    dossier 原私有件收编；无闸版姊妹 = 上行 ``_blob_dir_of``。"""
    if not run_row:
        return None
    from kernel import paths

    k, d, s = run_row.get("kind"), run_row.get("date"), run_row.get("slug")
    if not all(isinstance(x, str) for x in (k, d, s)):
        return None
    p = paths.run_dir(k, d, s)
    return p if p.is_dir() else None


def _rec_cols(d: dict) -> dict:
    """index records 行原位整形：metrics/errors json 解 + $blob 解引用
    （严格形）+ ``up``→``upstream`` 旧字段别名。gate/dossier 同源收编。"""
    from kernel import events

    blob_dir = _blob_dir_of(d)
    for col in ("metrics", "errors"):
        v = d.get(col)
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except ValueError:
                v = None
        d[col] = events.unblob(v, blob_dir)
    d["upstream"] = d.get("up")
    return d


def _seed_match(rows: list[dict], run_arg: str):
    """run 引用 → seed runs 行：精确名先，否则前缀匹配；零命中 →
    ``(None, err)``。gate._resolve_runs/dossier._resolve_run_group 同源。"""
    seeds = [r for r in rows if r.get("run") == run_arg]
    if not seeds:
        seeds = [r for r in rows if str(r.get("run")).startswith(run_arg)]
    if not seeds:
        return None, f"run not found: {run_arg!r}"
    return seeds, None


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


def _iter_jsonl(path: Path):
    """OSError 容忍（缺席/截尾）+ 坏行跳过的 jsonl 逐行 yield——
    ``kernel.events.iter_jsonl`` 的 ``(lineno, val, raw)`` 三元组投影为
    纯值流（None 坏行滤掉）。verbs 侧不得引 specs._benchlite，此为本层
    对应的容忍读口径。"""
    from kernel import events

    try:
        for _ln, val, _raw in events.iter_jsonl(path):
            if val is not None:
                yield val
    except OSError:
        return
