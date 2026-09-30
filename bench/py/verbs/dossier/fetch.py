"""verbs.dossier 取数叶 —— run 账组解析 + records/cases index 投影 +
阶段分组/末条胜视图 + tickets/invocations 读取（dossier.py 拆分叶）。

门面回引名单见 ``verbs.dossier._LEAF_EXPORTS``。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from verbs._common import (
    _all_runs,
    _iter_jsonl,
    _rec_cols,
    _seed_match,
    _stem_group,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------- run 解析


def _resolve_run_group(idx, run_arg: str):
    """run 名 → 账组 runs 行（import 拆账的 *_records_<stage> 兄弟并组）。

    精确 → 前缀 → stem 并组；跨 stem 即歧义 (None, err)。
    """
    rows = _all_runs(idx)
    seeds, serr = _seed_match(rows, run_arg)
    if serr is not None:
        return None, serr
    return _stem_group(rows, seeds, run_arg)


# ---------------------------------------------------------------- records/cases 读取


def _row_to_rec(d: dict) -> dict:
    """index 行 → 旧 records 形（``up``→``upstream``，id 取 idc 正形）。"""
    _rec_cols(d)
    d["id"] = d.get("idc") or d.get("id")
    return d


def _fetch_records(idx, cands: list[str], runs: list[str] | None = None):
    """该 id 全部账（跨 run append 序 (run_seq, seq)）→ rec 行 list。"""
    ph = ",".join("?" for _ in cands)
    sql = (
        "SELECT r.*, ru.run_seq, ru.kind, ru.date, ru.slug"  # noqa: S608 — 值全走占位符参数化
        " FROM records r LEFT JOIN runs ru ON ru.run = r.run"
        f" WHERE (r.idc IN ({ph}) OR r.id IN ({ph}))"
    )
    args = list(cands) + list(cands)
    if runs:
        rph = ",".join("?" for _ in runs)
        sql += f" AND r.run IN ({rph})"
        args += list(runs)
    sql += " ORDER BY COALESCE(ru.run_seq, 9223372036854775807), r.seq"
    return [_row_to_rec(dict(r)) for r in idx.conn.execute(sql, args)]


def _fetch_cases(idx, cands: list[str], runs: list[str] | None = None):
    """cases 表 payload → 旧 cases.jsonl 形 dict 序列（append 序）。

    T_CELL_QUEUED 行 payload 是整个事件（无 corpus/cond/verdict 面）——
    滤到案卷形 dict（旧 cases.jsonl 语义只含 CaseSink 案卷）。
    """
    ph = ",".join("?" for _ in cands)
    sql = (
        "SELECT c.run, c.seq, c.payload, c.ts, ru.run_seq"  # noqa: S608 — 值全走占位符参数化
        " FROM cases c LEFT JOIN runs ru ON ru.run = c.run"
        f" WHERE (c.idc IN ({ph}) OR c.id IN ({ph}))"
    )
    args = list(cands) + list(cands)
    if runs:
        rph = ",".join("?" for _ in runs)
        sql += f" AND c.run IN ({rph})"
        args += list(runs)
    sql += " ORDER BY COALESCE(ru.run_seq, 9223372036854775807), c.seq"
    out = []
    for row in idx.conn.execute(sql, args):
        try:
            p = json.loads(row["payload"]) if row["payload"] else None
        except ValueError:
            continue
        if isinstance(p, dict) and ("corpus" in p or "cond" in p or "verdict" in p):
            out.append(p)
    # 旧 load_cases 语义：(corpus,cond) 键末条胜
    latest = {}
    for p in out:
        latest[(p.get("corpus"), p.get("cond"))] = p
    return list(latest.values())


def _group_stages(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(str(r.get("stage") or "?"), []).append(r)
    return out


def _rec_key(rec: dict) -> tuple[str, str, str]:
    return (
        str(rec.get("id")),
        str(rec.get("arm") or "-"),
        str(rec.get("upstream") or ""),
    )


def _latest(recs: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """每 stage 末条胜视图（(id,arm,upstream) 键，append 序后者胜）。"""
    out = {}
    for st, rows in recs.items():
        d = {}
        for r in rows:
            d[_rec_key(r)] = r
        out[st] = list(d.values())
    return out


def load_tickets(pid_cands: set[str], rundirs: list[Path]) -> list[str]:
    """derived/tickets*.jsonl 中 example_ids 含此 id 的工单 sig_id（缺席容忍）。"""
    out = []
    for rd in rundirs:
        d = rd / "derived"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("tickets*.jsonl")):
            out.extend(
                str(r.get("sig_id") or r.get("signature") or "?")
                for r in _iter_jsonl(f)
                if isinstance(r, dict)
                and pid_cands & {str(x) for x in (r.get("example_ids") or [])}
            )
    return out


def _invocations(rundir: Path | None) -> list[dict]:
    if rundir is None:
        return []
    return [r for r in _iter_jsonl(rundir / "invocations.jsonl") if isinstance(r, dict)]
