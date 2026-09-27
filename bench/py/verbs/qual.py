"""qual-report — qualbench eval_records + cases → report.md（ESA 口径）。

旧 ``bench/py/qualbench.py`` 的 cmd_report/aggregate/write_report 移植
（pairs 不移——frame 本身是冻结抽样，``bench plan`` 枚举即预览）。

字段映射（旧 records.jsonl 行 → eval_records 行 + cases payload）：
  model→arm 列 · paper→idc 列 · judge_model→metrics.judge_model_used
  （variant 'proto|judge|chunk' 第二段同源互证）· chunk_id→metrics
  .chunk_id（variant 第三段同源）· kind→metrics.kind ·
  score/stated100/derived100/score_delta/n_errors/n_span_unverified/
  flags/contested/contest_reasons→metrics 同名 · judge2.*→metrics
  .judge2_* 平铺 · errors（ESA category/severity 标注）→cases 表
  payload（emit_case 通道，不入 metrics）。
meta 字段源：protocol_v/epoch→variant 首段 · judge/second_model→
plan.json run_params · source/seed→frame .meta.json · started_at→
runs.ts_start——缺字段渲染 '?' 不编。
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from verbs import _common

HELP = "qualbench 评判汇总 → report.md"

_SCORE_BANDS = ((90, "90-100"), (75, "75-89"), (55, "55-74"), (0, "0-54"))


def _err(msg: str) -> None:
    print(f"qual: {msg}", file=sys.stderr)


def _open_index():
    return _common._open_index(_err)


def _run_ref(ref: str):
    return _common._run_ref(ref, _err)


_unblob = _common._unblob
_payload = _common._payload


def _vseg(variant: str, i: int) -> str | None:
    """variant 'proto@epoch|judge|chunk' 第 i 段（spec _items 拼串契约）。"""
    parts = str(variant or "").split("|")
    return parts[i] if len(parts) > i and parts[i] else None


_eval_rows = _common._eval_rows


def _case_map(idx, run_name: str) -> dict[tuple, dict]:
    """(idc, chunk_id, model) → 末条 case payload（重试格 seq 大者胜）。

    ESA errors 标注走 emit_case 通道——metrics 只有计数面。"""
    out: dict[tuple, dict] = {}
    for r in idx.conn.execute(
        "SELECT idc,seq,payload FROM cases WHERE run=? AND stage='judge' ORDER BY seq",
        (run_name,),
    ):
        try:
            pl = json.loads(r["payload"])
        except (TypeError, ValueError):
            continue
        if not isinstance(pl, dict):
            continue
        key = (
            r["idc"],
            str(pl.get("chunk_id") or ""),
            str(pl.get("model") or ""),
        )
        out[key] = pl  # ORDER BY seq → 末条覆盖
    return out


def _rec_of(row: dict, rundir: Path | None, cases: dict) -> dict:
    """eval_records 行 → 旧 records.jsonl 行形（aggregate 逐字复用）。"""
    m = _payload(row.get("metrics"), rundir)
    m = m if isinstance(m, dict) else {}
    variant = str(row.get("variant") or "")
    chunk = m.get("chunk_id") or _vseg(variant, 2) or ""
    case = cases.get((row.get("idc"), str(chunk), str(row.get("arm")))) or {}
    j2 = None
    if any(
        k in m
        for k in ("judge2_stated100", "judge2_error", "judge2_model", "judge2_n_errors")
    ):
        j2 = {
            "stated100": m.get("judge2_stated100"),
            "judge2_error": m.get("judge2_error"),
            "judge_model": m.get("judge2_model"),
            "n_errors": m.get("judge2_n_errors"),
        }
    return {
        "model": row.get("arm"),
        "judge_model": m.get("judge_model_used") or _vseg(variant, 1),
        "paper": row.get("idc"),
        "kind": m.get("kind"),
        "chunk_id": chunk,
        "score": m.get("score"),
        "stated100": m.get("stated100"),
        "derived100": m.get("derived100"),
        "score_delta": m.get("score_delta"),
        "n_errors": m.get("n_errors"),
        "n_span_unverified": m.get("n_span_unverified"),
        "flags": m.get("flags"),
        "contested": m.get("contested"),
        "contest_reasons": m.get("contest_reasons"),
        "errors": case.get("errors"),
        "judge2": j2,
        "_variant": variant,
        "_up": row.get("up"),
    }


# ---------------------------------------------------------------- 聚合/报告
def _dist(scores: list[int]) -> str:
    """0-100 分带分布（≥90 / 75-89 / 55-74 / <55）。"""
    c = {label: 0 for _, label in _SCORE_BANDS}
    for s in scores:
        for lo, label in _SCORE_BANDS:
            if s >= lo:
                c[label] += 1
                break
    return " ".join(f"{label}:{c[label]}" for _, label in _SCORE_BANDS)


def aggregate(recs: list[dict]) -> dict:
    """records → {by_group, by_paper, by_kind, cat_sev, worst, contested,
    n_error}——旧 aggregate 逐字。"""
    groups: dict[str, list[dict]] = {}
    judged = [r for r in recs if r.get("score") is not None]
    for r in judged:
        groups.setdefault(
            f"{r.get('model', '?')} × judge={r.get('judge_model', '?')}", []
        ).append(r)
    by_paper: dict[str, list[dict]] = {}
    by_kind: dict[str, list[dict]] = {}
    cat_sev: dict[str, dict[str, int]] = {}
    for r in judged:
        by_paper.setdefault(str(r.get("paper")), []).append(r)
        by_kind.setdefault(str(r.get("kind") or "?"), []).append(r)
        for e in r.get("errors") or []:
            row = cat_sev.setdefault(
                e.get("category") or "?", {"minor": 0, "major": 0, "critical": 0}
            )
            row[e.get("severity") or "minor"] = (
                row.get(e.get("severity") or "minor", 0) + 1
            )
    contested = [r for r in judged if r.get("contested")]
    worst = sorted(
        judged,
        key=lambda r: (r["score"], -(r.get("n_errors") or 0)),
    )[:30]
    return {
        "groups": groups,
        "by_paper": by_paper,
        "by_kind": by_kind,
        "cat_sev": cat_sev,
        "contested": contested,
        "worst": worst,
        "n_error": sum(1 for r in recs if r.get("score") is None),
        "n_judged": len(judged),
    }


def _flag_tally(recs: list[dict]) -> dict[str, int]:
    t: dict[str, int] = {}
    for r in recs:
        for f in r.get("flags") or []:
            t[f] = t.get(f, 0) + 1
    return t


def _score_row(recs: list[dict]) -> str:
    scores = [int(r["score"]) for r in recs]
    deltas = [int(r["score_delta"]) for r in recs if r.get("score_delta") is not None]
    return (
        f"{len(recs)} | {statistics.mean(scores):.1f} | "
        f"{statistics.median(scores):.0f} | {_dist(scores)}"
        + (f" | {statistics.mean(deltas):+.1f}" if deltas else " | —")
    )


def write_report(recs: list[dict], meta: dict, out_path: Path) -> None:
    """records + meta → report.md——旧 write_report 模板逐字。"""
    agg = aggregate(recs)
    n_contested = len(agg["contested"])
    lines = [
        "# qualbench — 译文质量 LLM-judge（ESA）",
        "",
        (
            f"- protocol_v: `{meta.get('protocol_v', '?')}` · "
            f"judge: `{meta.get('judge_model')}`"
            f"（mock={meta.get('mock_judge')}）· 二裁: `{meta.get('second_model')}`"
        ),
        f"- source: {meta.get('source')} · seed={meta.get('seed')} · "
        f"papers={len(meta.get('papers') or [])} · judged={agg['n_judged']} chunks"
        + (f" · judge_error={agg['n_error']}" if agg["n_error"] else "")
        + (
            f" · contested={n_contested} ({n_contested / agg['n_judged'] * 100:.1f}%)"
            if agg["n_judged"]
            else ""
        ),
        f"- started: {meta.get('started_at')}",
        "",
        "## 总分 stated100（model × judge）",
        "",
        "| model × judge | n | mean | median | 分布 ≥90/75+/55+/<55 | Δmean |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {name} | {_score_row(agg['groups'][name])} |"
        for name in sorted(agg["groups"])
    )

    lines += ["", "## 错误分类 × severity（全体 judged chunk）", ""]
    if agg["cat_sev"]:
        lines += [
            "| category | minor | major | critical | total |",
            "| --- | --- | --- | --- | --- |",
        ]
        for cat, row in sorted(
            agg["cat_sev"].items(), key=lambda kv: -sum(kv[1].values())
        ):
            tot = sum(row.values())
            lines.append(
                f"| `{cat}` | {row['minor']} | {row['major']} | "
                f"{row['critical']} | {tot} |"
            )
    else:
        lines.append("- （无错误标注）")

    lines += ["", "## flag 频率（类目派生）", ""]
    tally = _flag_tally([r for v in agg["groups"].values() for r in v])
    if tally:
        for f, c in sorted(tally.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{f}`: {c}")
    else:
        lines.append("- （无 flag）")

    lines += [
        "",
        "## per-kind",
        "",
        "| kind | n | mean | median | 分布 ≥90/75+/55+/<55 | flags |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for k in sorted(agg["by_kind"]):
        rs = agg["by_kind"][k]
        ft = _flag_tally(rs)
        scores = [int(r["score"]) for r in rs]
        lines.append(
            f"| {k} | {len(rs)} | {statistics.mean(scores):.1f} | "
            f"{statistics.median(scores):.0f} | {_dist(scores)} | "
            + (
                ", ".join(
                    f"{f}×{c}" for f, c in sorted(ft.items(), key=lambda kv: -kv[1])
                )
                or "—"
            )
            + " |"
        )

    lines += [
        "",
        "## per-paper",
        "",
        "| paper | model | n | mean | 分布 ≥90/75+/55+/<55 | flags |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for p in sorted(agg["by_paper"]):
        rs = agg["by_paper"][p]
        ft = _flag_tally(rs)
        scores = [int(r["score"]) for r in rs]
        lines.append(
            f"| {p} | {rs[0].get('model', '?')} | {len(rs)} | "
            f"{statistics.mean(scores):.1f} | {_dist(scores)} | "
            + (
                ", ".join(
                    f"{f}×{c}" for f, c in sorted(ft.items(), key=lambda kv: -kv[1])
                )
                or "—"
            )
            + " |"
        )

    if agg["contested"]:
        lines += [
            "",
            "## contested chunk（触发二裁）",
            "",
            "| paper | chunk | reasons | stated | derived | judge2.stated |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in agg["contested"][:30]:
            j2 = r.get("judge2") or {}
            lines.append(
                f"| {r.get('paper')} | {r.get('chunk_id')} "
                f"| {','.join(r.get('contest_reasons') or [])} "
                f"| {r.get('stated100')} | {r.get('derived100')} "
                f"| {j2.get('stated100', j2.get('judge2_error', '—'))} |"
            )

    if agg["worst"]:
        lines += [
            "",
            "## 最差 chunk（stated100 升序前 30）",
            "",
            "| paper | chunk | kind | stated | Δ | flags | span✗ | note |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in agg["worst"]:
            if r["score"] >= 85 and not r.get("flags"):
                continue
            note = ""
            if r.get("errors"):
                note = str(r["errors"][0].get("note") or "")[:40]
            lines.append(
                f"| {r.get('paper')} | {r.get('chunk_id')} | "
                f"{r.get('kind', '?')} "
                f"| {r['score']} | {r.get('score_delta', '—')} "
                f"| {','.join(r.get('flags') or []) or '—'} "
                f"| {r.get('n_span_unverified') or 0} | {note} |"
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- meta
def _meta_of(idx, run_name: str, rdir: Path | None, recs: list[dict]) -> dict:
    """report 头 meta：spec/plan/frame 三源互证，缺字段 '?' 不编。"""
    rp: dict = {}
    lanes: set[str] = set()
    if rdir is not None and (rdir / "plan.json").is_file():
        try:
            plan = json.loads((rdir / "plan.json").read_text(encoding="utf-8"))
            cells = plan.get("cells") or []
            if cells:
                rp = dict(cells[0].get("run_params") or {})
            lanes = {str(c.get("lane")) for c in cells if c.get("lane")}
        except (ValueError, OSError):
            pass
    protos = sorted({_vseg(r["_variant"], 0) for r in recs if _vseg(r["_variant"], 0)})
    judges = sorted({_vseg(r["_variant"], 1) for r in recs if _vseg(r["_variant"], 1)})
    seeds: set[str] = set()
    sources: set[str] = set()
    repo = Path(__file__).resolve().parents[3]
    for lane in sorted(lanes):
        mp = repo / "bench" / "nominations" / f"{lane}.meta.json"
        if not mp.is_file():
            continue
        try:
            fm = json.loads(mp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if fm.get("seed") is not None:
            seeds.add(str(fm["seed"]))
        if fm.get("cmd"):
            sources.add(str(fm["cmd"]))
    ups = sorted({str(r.get("_up") or "") for r in recs} - {""})
    started = None
    r = idx.conn.execute(
        "SELECT ts_start FROM runs WHERE run=?", (run_name,)
    ).fetchone()
    if r and r["ts_start"]:
        import datetime as _dt

        started = _dt.datetime.fromtimestamp(r["ts_start"], _dt.UTC).isoformat(
            timespec="seconds"
        )
    return {
        "protocol_v": "+".join(protos) or "?",
        "judge_model": rp.get("judge") or "+".join(judges) or "?",
        "mock_judge": "mock-judge" in judges,
        "second_model": rp.get("second_model") or "?",
        "source": "+".join(sources) or "+".join(ups) or "?",
        "seed": "+".join(sorted(seeds)) or "?",
        "papers": sorted({str(r.get("paper")) for r in recs}),
        "started_at": started or "?",
    }


def _cmd_report(args) -> int:
    idx = _open_index()
    recs: list[dict] = []
    names: list[str] = []
    first_name = first_rundir = None
    for ref in args.runs:
        name, rdir = _run_ref(ref)
        if name is None:
            return 2
        r = idx.conn.execute("SELECT kind FROM runs WHERE run=?", (name,)).fetchone()
        kind = r["kind"] if r else None
        if kind != "qualbench":
            _err(f"{name}: kind={kind!r} skipped (qual-report reads qualbench runs)")
            continue
        names.append(name)
        if first_name is None:
            first_name, first_rundir = name, rdir
        cases = _case_map(idx, name)
        recs.extend(_rec_of(row, rdir, cases) for row in _eval_rows(idx, name))
    if not recs:
        print("qual-report: no eval_records rows (run empty or kind filtered)")
        return 0
    meta = _meta_of(idx, first_name, first_rundir, recs)
    if args.out:
        out_p = Path(args.out)
    elif first_rundir is not None:
        out_p = first_rundir / "derived" / "report.md"
    else:
        out_p = None
    if out_p is not None:
        write_report(recs, meta, out_p)
        print(f"report -> {out_p} ({len(recs)} records)")
    agg = aggregate(recs)
    summary = {
        "runs": names,
        "n_judged": agg["n_judged"],
        "n_error": agg["n_error"],
        "n_contested": len(agg["contested"]),
        "groups": {
            name: {
                "n": len(rs),
                "mean": round(statistics.mean([int(r["score"]) for r in rs]), 1),
            }
            for name, rs in sorted(agg["groups"].items())
        },
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"judged={summary['n_judged']} error={summary['n_error']} "
            f"contested={summary['n_contested']} · groups: "
            + ", ".join(
                f"{k}={v['mean']}({v['n']})" for k, v in summary["groups"].items()
            )
        )
    return 0


# ---------------------------------------------------------------- glue
def add_args(sp) -> None:
    sp.add_argument("runs", nargs="+", help="run 名 kind/date/slug 或 runs/ 下目录")
    sp.add_argument(
        "--out",
        default=None,
        help="report.md 落盘路径（默认首 run derived/report.md）",
    )
    sp.add_argument("--json", action="store_true", help="stdout 摘要改 JSON")


def main(args) -> int:
    return _cmd_report(args)
