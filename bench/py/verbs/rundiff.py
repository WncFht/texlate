r"""rundiff — 两 run 逐格终态迁移对比 (A→B 改善/退化判读)。

两侧 index records ∪ eval_records 各自按 (id,arm,up,variant,stage) seq
末条胜去重 (复用 verbs.triage.load_records), 同键格比对 status 等级
(verbs._vocab.STATUS_RANK):

  - 迁移矩阵: 行=A status / 列=B status, 格=计数; (absent) 轴收编单侧格
  - degraded: rank 降 | improved: rank 升 | added/removed: 单侧格清单

  bench rundiff A B                  # 对比两 run 共有的全部 stage
  bench rundiff A B --stage compile  # 只比该 stage (可重复)
  bench rundiff A B --deep           # same-status churn 清单 (sig/taxonomy/
                                     #   n_errors/dur_s 四维变化逐格列出)
  bench rundiff A B --json           # 机读输出
  bench rundiff A B --json-out PATH  # stdout 面照打 + 机读 JSON 双写落盘

A/B = kind/date/slug、run 目录或任意 records.run 值。无 id 的行无法成格
键, 丢弃。纯 stdlib + 同目 verbs.triage/_vocab。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from verbs import _vocab
from verbs import triage as _triage

#: 单侧格的矩阵伪状态——只进矩阵轴，不进 improved/degraded 判定。
ABSENT = "(absent)"
MAX_LIST = 100


def _rank(status):
    """STATUS_RANK 序数; 表外词 (skip/error/...) -1, 比 reject 更低。"""
    return _vocab.STATUS_RANK.get(str(status or ""), -1)


def stage_cells(index, run, blob_dir=None, table="both"):
    """index records → {stage: {(id,arm,up,variant): rec}}；末条胜口径同 triage。"""
    stages = {}
    for rec in _triage.load_records(index, run, blob_dir, table):
        if not rec.get("id"):
            continue
        stage = str(rec.get("stage") or "?")
        key = (
            str(rec["id"]),
            str(rec.get("arm") or "-"),
            str(rec.get("upstream") or ""),
            str(rec.get("variant") or ""),
        )
        stages.setdefault(stage, {})[key] = rec
    return stages


def _status(rec):
    return str(rec.get("status") or "?")


def _sig(rec):
    return str(rec.get("sig") or "")


def _taxo(rec):
    """records 物化 taxonomy——compile 在 metrics.taxonomy, fixloop post 在
    metrics.post.taxonomy; → {slot: "cat:pay"} (只收 dict 形，缺席不出键)。"""
    m = rec.get("metrics") or {}
    if not isinstance(m, dict):
        return {}
    out = {}
    for slot, t in (
        ("tax", m.get("taxonomy")),
        ("post.tax", (m.get("post") or {}).get("taxonomy")),
    ):
        if isinstance(t, dict):
            out[slot] = f"{t.get('cat')}:{t.get('pay')}"
    return out


def _n_errors(rec):
    m = rec.get("metrics") or {}
    if not isinstance(m, dict):
        return None
    n = m.get("n_errors")
    return n if isinstance(n, (int, float)) else None


def _dur(rec):
    d = rec.get("dur_s")
    return d if isinstance(d, (int, float)) else None


def _churn(ra, rb):
    """same-status 格的四维实质变化 → {facet: (a, b)}; 全同 → {}。

    dur_s 仅 |Δ|≥10s 且 ≥2× 才记——重跑恒有时序抖动，量级变化才是信号。
    """
    out = {}
    if _sig(ra) != _sig(rb):
        out["sig"] = (_sig(ra), _sig(rb))
    ta, tb = _taxo(ra), _taxo(rb)
    if ta != tb:
        out["taxonomy"] = (ta, tb)
    na, nb = _n_errors(ra), _n_errors(rb)
    if na is not None and nb is not None and na != nb:
        out["n_errors"] = (na, nb)
    da, db = _dur(ra), _dur(rb)
    if (
        da is not None
        and db is not None
        and abs(db - da) >= 10
        and (db >= 2 * da or da >= 2 * db)
    ):
        out["dur_s"] = (round(da, 1), round(db, 1))
    return out


def _entry(key, rec, side=None):
    """格键 → 清单条目; side='a'/'b' 时补该侧 status/sig。"""
    rid, arm, up, variant = key
    e = {"id": rid, "arm": arm, "upstream": up}
    if variant not in ("", "-"):
        e["variant"] = variant
    if side is not None:
        e[side] = _status(rec)
        if _sig(rec):
            e["sig"] = _sig(rec)
    return e


def diff_stage(cells_a, cells_b, deep=False):
    """{key: rec} × {key: rec} → {matrix, same, improved, degraded, added, removed, churn}。

    matrix 含 (absent) 轴单侧格; improved/degraded 只在共有键上按 rank 判。
    degraded 条目带 sig_b (退化原因侧), improved 带 sig_a (修复前缺陷侧)。
    deep=True 时对 same-status 格跑 _churn 四维面，有变的进 churn 清单
    (条目仍在 same 计数内——churn 是 same 的注解子集)。
    """
    matrix = Counter()
    same, improved, degraded, churn = [], [], [], []
    for key in sorted(cells_a.keys() & cells_b.keys()):
        ra, rb = cells_a[key], cells_b[key]
        sa, sb = _status(ra), _status(rb)
        matrix[(sa, sb)] += 1
        e = _entry(key, None)
        e["a"], e["b"] = sa, sb
        if _sig(ra):
            e["sig_a"] = _sig(ra)
        if _sig(rb):
            e["sig_b"] = _sig(rb)
        if _rank(sb) > _rank(sa):
            improved.append(e)
        elif _rank(sb) < _rank(sa):
            degraded.append(e)
        else:
            same.append(e)
            if deep:
                c = _churn(ra, rb)
                if c:
                    e["churn"] = c
                    churn.append(e)
    added, removed = [], []
    for key in sorted(cells_b.keys() - cells_a.keys()):
        matrix[(ABSENT, _status(cells_b[key]))] += 1
        added.append(_entry(key, cells_b[key], "b"))
    for key in sorted(cells_a.keys() - cells_b.keys()):
        matrix[(_status(cells_a[key]), ABSENT)] += 1
        removed.append(_entry(key, cells_a[key], "a"))
    return {
        "matrix": matrix,
        "same": same,
        "improved": improved,
        "degraded": degraded,
        "added": added,
        "removed": removed,
        "churn": churn,
    }


def _status_order(statuses):
    """rank 降序 → 名称升序; (absent) 恒垫底。"""
    return sorted(statuses, key=lambda s: (s == ABSENT, -_rank(s), s))


def _label(e):
    extra = "/".join(
        p
        for p in (
            e["arm"] if e["arm"] != "-" else "",
            e["upstream"] if e["upstream"] != "-" else "",
            e.get("variant") or "",
        )
        if p
    )
    return f"{e['id']} ({extra})" if extra else e["id"]


def _md_list(lines, title, entries, fmt):
    lines += [f"### {title} ({len(entries)})", ""]
    if not entries:
        lines += ["无。", ""]
        return
    for e in entries[:MAX_LIST]:
        lines.append(f"- `{_label(e)}` {fmt(e)}")
    if len(entries) > MAX_LIST:
        lines.append(f"- … 其余 {len(entries) - MAX_LIST} 条见 --json")
    lines.append("")


def _churn_fmt(e):
    """churn 条目的四维渲染：`sig a→b; taxonomy x:y→p:q; n_errors 110→5`。"""
    parts = []
    c = e["churn"]
    if "sig" in c:
        a, b = c["sig"]
        parts.append(f"sig `{a or '∅'}`→`{b or '∅'}`")
    if "taxonomy" in c:
        a, b = c["taxonomy"]
        parts.extend(
            f"taxonomy.{slot} `{a.get(slot, '∅')}`→`{b.get(slot, '∅')}`"
            for slot in sorted(set(a) | set(b))
        )
    if "n_errors" in c:
        a, b = c["n_errors"]
        parts.append(f"n_errors {a}→{b}")
    if "dur_s" in c:
        a, b = c["dur_s"]
        parts.append(f"dur {a}s→{b}s")
    return "; ".join(parts)


def render_md(name_a, name_b, diffs, deep=False):
    """{stage: diff} → markdown 文本。"""
    lines = [f"# rundiff — {name_a} → {name_b}", ""]
    for stage, d in diffs.items():
        common = len(d["same"]) + len(d["improved"]) + len(d["degraded"])
        lines += [
            f"## {stage}",
            "",
            (
                f"- 共有格 {common} · same {len(d['same'])}"
                f" · improved {len(d['improved'])} · degraded {len(d['degraded'])}"
                f" · added {len(d['added'])} · removed {len(d['removed'])}"
                + (f" · same-status churn {len(d['churn'])}" if deep else "")
            ),
            "",
        ]
        if d["matrix"]:
            cols = _status_order({sb for _, sb in d["matrix"]})
            rows = _status_order({sa for sa, _ in d["matrix"]})
            lines.append("| A \\ B | " + " | ".join(cols) + " |")
            lines.append("| --- |" + " --- |" * len(cols))
            for sa in rows:
                cells = " | ".join(str(d["matrix"].get((sa, sb), 0)) for sb in cols)
                lines.append(f"| {sa} | {cells} |")
            lines.append("")
        _md_list(
            lines,
            "degraded",
            d["degraded"],
            lambda e: (
                f"{e['a']} → {e['b']}"
                + (f" — `{e['sig_b']}`" if e.get("sig_b") else "")
            ),
        )
        _md_list(
            lines,
            "improved",
            d["improved"],
            lambda e: (
                f"{e['a']} → {e['b']}"
                + (f" — `{e['sig_a']}`" if e.get("sig_a") else "")
            ),
        )
        _md_list(
            lines,
            "added in B",
            d["added"],
            lambda e: e["b"] + (f" — `{e['sig']}`" if e.get("sig") else ""),
        )
        _md_list(
            lines,
            "removed in B",
            d["removed"],
            lambda e: e["a"] + (f" — `{e['sig']}`" if e.get("sig") else ""),
        )
        if deep:
            _md_list(
                lines,
                "same-status churn",
                d["churn"],
                lambda e: f"{e['a']} → {e['b']} — {_churn_fmt(e)}",
            )
    return "\n".join(lines)


def _jsonable(name_a, name_b, diffs, deep=False):
    stages = {}
    for stage, d in diffs.items():
        matrix = {}
        for (sa, sb), n in sorted(d["matrix"].items()):
            matrix.setdefault(sa, {})[sb] = n
        out = {
            "matrix": matrix,
            "counts": {
                "same": len(d["same"]),
                "improved": len(d["improved"]),
                "degraded": len(d["degraded"]),
                "added": len(d["added"]),
                "removed": len(d["removed"]),
            },
            "improved": d["improved"],
            "degraded": d["degraded"],
            "added": d["added"],
            "removed": d["removed"],
        }
        if deep:
            out["counts"]["churn"] = len(d["churn"])
            out["churn"] = d["churn"]
        stages[stage] = out
    return {"a": name_a, "b": name_b, "stages": stages}


def add_args(sp):
    sp.add_argument("run_a", help="基准 run (kind/date/slug、目录或 records.run 值)")
    sp.add_argument("run_b", help="对照 run")
    sp.add_argument(
        "--stage",
        action="append",
        default=None,
        help="只比该 stage (可重复); 缺省 = 两 run 共有 stage 全集",
    )
    sp.add_argument(
        "--table",
        choices=sorted(_triage._TABLES),
        default="both",
        help="records 面选择（缺省 both）",
    )
    sp.add_argument("--json", action="store_true", dest="as_json", help="机读输出")
    sp.add_argument(
        "--json-out",
        type=Path,
        default=None,
        metavar="PATH",
        help="机读 JSON 额外落盘——stdout 面不变 (与 --json 可并给, 单扫双发)",
    )
    sp.add_argument(
        "--deep",
        action="store_true",
        help="same-status 格列四维 churn 清单 (sig/taxonomy/n_errors/dur_s)",
    )


def main(args):
    from kernel import cli as _cli
    from kernel import report as _report

    index = _cli._open_index()
    try:
        ia = _report._resolve(index, args.run_a)
        ib = _report._resolve(index, args.run_b)
        cells_a = stage_cells(
            index, ia["run"], _triage._blob_dir(ia["rundir"]), args.table
        )
        cells_b = stage_cells(
            index, ib["run"], _triage._blob_dir(ib["rundir"]), args.table
        )
        if args.stage:
            stages = list(dict.fromkeys(args.stage))
        else:
            stages = sorted(set(cells_a) & set(cells_b))
        if not stages:
            print("rundiff: 无共有 stage 可比", file=sys.stderr)
            return 1
        for s in stages:
            if s not in cells_a:
                print(
                    f"rundiff: warn {s} 不在 {ia['run']} records (按全 added 计)",
                    file=sys.stderr,
                )
            if s not in cells_b:
                print(
                    f"rundiff: warn {s} 不在 {ib['run']} records (按全 removed 计)",
                    file=sys.stderr,
                )
        diffs = {
            s: diff_stage(cells_a.get(s, {}), cells_b.get(s, {}), deep=args.deep)
            for s in stages
        }
        name_a, name_b = ia["run"], ib["run"]
        payload = None
        if args.as_json or args.json_out:
            payload = _jsonable(name_a, name_b, diffs, deep=args.deep)
        if args.json_out:
            # print 渲染比 join 多一个换行——拼回保持落盘与 stdout 逐字节一致。
            args.json_out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8",
            )
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=1))
        else:
            print(render_md(name_a, name_b, diffs, deep=args.deep))
        return 0
    finally:
        index.close()
