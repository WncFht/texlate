#!/usr/bin/env python3
r"""qualstats — qualbench records 统计臂：block bootstrap CI + pairwise acc + report。

records.jsonl schema v2（protocol_v=esa2，产见 qualbench.py）：每行一个
judged chunk——``key={model}|{paper}|{chunk_id}|{judge}|esa2``，主分
``stated100``（0-100，``score`` 同值），``derived100``=100-Σseverity 权重、
``score_delta``=stated-derived 自洽差、``errors[]``（span/category/severity/
note/span_verified）、``flags``、``contested``；失败行带
``judge_error``/``error`` 无分。旧协议行（无 stated100/protocol_v，主分
``score``）不进 esa2 指标——协议语义不同混算会污染，计
skipped_old_protocol。

子命令：
  ci DIR        paper 簇 block bootstrap（mt-metrics-eval 惯例：同 paper 的
                chunk 不独立，整簇重采样），95% percentile CI。指标：
                stated100/derived100/score_delta mean、per-kind mean、
                contested 率、各 flag 率、span_verified 率（verified/total
                error span——无错误行的重采样记 NaN 剔除）。输出
                DIR/ci.json + stdout 打印表；``--json`` 只打 JSON。
  pairacc A B   tie-calibrated pairwise accuracy（acc23 口径，Deutsch et
                al. 2023 / WMT22+ 段级元评官方口径）：key 对齐两侧分数，
                全部 unordered chunk 对比较 sign(ΔA)·sign(ΔB)——>0 记 1、
                任一边差为 0 记 0.5、<0 记 0。CI 用 chunk(item) 级
                bootstrap：整 item 重采样后重求全对（同 item 位对按 tie
                规则得 0.5）。--key-mode full 用 record ``key`` 对齐；
                paper_chunk 用 ``{paper}|{chunk_id}``（人锚回收 key 无
                judge/protocol 段）。
  report DIR    records.jsonl+run_meta.json → report.md：qualbench 自带
                报告加强版——总分/per-kind/contested/flag 率带 CI 列，
                cat×sev 表与 worst 30 原样保留。

B 重采样统一 ``random.Random(seed)`` 确定性（默认 B=1000 seed=42）。
依赖: 纯 stdlib；只读，不 import texlate.*。

用法:
  uv run python bench/py/qualstats.py ci tmp/qual-esa-smoke
  uv run python bench/py/qualstats.py pairacc judge.jsonl human.jsonl \
      --key-mode paper_chunk
  uv run python bench/py/qualstats.py report bench/results/qualbench-XXX
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

#: flag 词表全集（与 qualbench KNOWN_FLAGS 同源口径——report/ci 固定列）
KNOWN_FLAGS = (
    "untranslated_spans",
    "hallucinated_content",
    "mistranslation",
    "term_inconsistency",
    "over_translation",
    "placeholder_broken",
    "grammar",
    "fluency_register",
)

_SCORE_BANDS = ((90, "90-100"), (75, "75-89"), (55, "55-74"), (0, "0-54"))


# ---------------------------------------------------------------- 读取/分类
def read_jsonl(path: Path) -> tuple[list[dict], int]:
    """jsonl → (records, n_bad_json)；坏行不崩，计 bad_json。"""
    recs: list[dict] = []
    n_bad = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [], 0
    for raw_ln in text.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            n_bad += 1
            continue
        if isinstance(rec, dict):
            recs.append(rec)
        else:
            n_bad += 1
    return recs, n_bad


def _num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def classify(rec: dict) -> str:
    """record → judged | error | skipped_old_protocol。

    - 数值 ``stated100`` → judged（esa2 成功行；score 同值 canonical）
    - 无有效 stated100 但带 esa2 痕迹（protocol_v / judge_error / error /
      stated100 键存在）或 ``score`` 缺失为 None → error（esa2 失败行
      及未知坏行）
    - 其余（典型：旧协议行——有 ``score`` 但无 esa2 字段）→
      skipped_old_protocol
    """
    if _num(rec.get("stated100")):
        return "judged"
    if (
        rec.get("protocol_v")
        or "judge_error" in rec
        or "error" in rec
        or "stated100" in rec
        or rec.get("score") is None
    ):
        return "error"
    return "skipped_old_protocol"


def split_records(recs: list[dict]) -> dict[str, list[dict]]:
    """records → {judged, error, skipped_old_protocol} 三桶。"""
    out: dict[str, list[dict]] = {
        "judged": [],
        "error": [],
        "skipped_old_protocol": [],
    }
    for r in recs:
        out[classify(r)].append(r)
    return out


def paper_clusters(recs: list[dict]) -> list[list[dict]]:
    """judged records → paper 簇列表（block bootstrap 的重采样单元）。"""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        by[str(r.get("paper") or "?")].append(r)
    return list(by.values())


# ---------------------------------------------------------------- bootstrap
def _pctile(xs: list[float], q: float) -> float | None:
    """线性插值 percentile（numpy 'linear' 同款）；空列 → None。"""
    if not xs:
        return None
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    h = (len(xs) - 1) * q / 100.0
    lo = math.floor(h)
    frac = h - lo
    if lo + 1 < len(xs):
        return xs[lo] + frac * (xs[lo + 1] - xs[lo])
    return xs[-1]


def bootstrap_pools(
    clusters: list[list[dict]], n_boot: int, rng: random.Random
) -> list[list[dict]]:
    """n_boot 个 block-bootstrap 池：整簇重采样拼接（全 metric 共用同组池）。"""
    n_clusters = len(clusters)
    if n_clusters == 0:
        return []
    pools = []
    for _ in range(n_boot):
        idx = [rng.randrange(n_clusters) for _ in range(n_clusters)]
        pools.append([r for i in idx for r in clusters[i]])
    return pools


def ci_of(vals: list[float]) -> tuple[float | None, float | None]:
    """95% percentile CI。"""
    return _pctile(vals, 2.5), _pctile(vals, 97.5)


# ---------------------------------------------------------------- 指标
def _fnums(recs: list[dict], field: str) -> list[float]:
    return [float(r[field]) for r in recs if _num(r.get(field))]


def _mean_or_nan(xs: list[float]) -> float:
    return statistics.mean(xs) if xs else float("nan")


def metric_stated100_mean(recs: list[dict]) -> float:
    return _mean_or_nan(_fnums(recs, "stated100"))


def metric_derived100_mean(recs: list[dict]) -> float:
    return _mean_or_nan(_fnums(recs, "derived100"))


def metric_score_delta_mean(recs: list[dict]) -> float:
    return _mean_or_nan(_fnums(recs, "score_delta"))


def metric_contested_rate(recs: list[dict]) -> float:
    if not recs:
        return float("nan")
    return sum(1 for r in recs if r.get("contested")) / len(recs)


def metric_span_verified_rate(recs: list[dict]) -> float:
    """verified span / 全部 error span；池内零错误 → NaN（该重采样剔除）。"""
    tot = ver = 0
    for r in recs:
        for e in r.get("errors") or []:
            if isinstance(e, dict):
                tot += 1
                if e.get("span_verified"):
                    ver += 1
    return ver / tot if tot else float("nan")


def make_kind_mean(kind: str):
    def fn(recs: list[dict]) -> float:
        xs = [
            float(r["stated100"])
            for r in recs
            if str(r.get("kind") or "?") == kind and _num(r.get("stated100"))
        ]
        return _mean_or_nan(xs)

    return fn


def make_flag_rate(flag: str):
    def fn(recs: list[dict]) -> float:
        if not recs:
            return float("nan")
        return sum(1 for r in recs if flag in (r.get("flags") or [])) / len(recs)

    return fn


def metric_denominator_clusters(clusters: list[list[dict]], name: str) -> int:
    """该 metric 分母实际覆盖的簇数（kind/span 类指标只数有贡献的簇）。"""
    if name.startswith("kind_mean/"):
        kind = name.split("/", 1)[1]
        return sum(
            1 for c in clusters if any(str(r.get("kind") or "?") == kind for r in c)
        )
    if name == "span_verified_rate":
        return sum(
            1
            for c in clusters
            if any(isinstance(e, dict) for r in c for e in (r.get("errors") or []))
        )
    if name in ("derived100_mean", "score_delta_mean"):
        field = name.split("_mean", maxsplit=1)[0]
        return sum(1 for c in clusters if any(_num(r.get(field)) for r in c))
    return len(clusters)


def build_metric_fns(judged: list[dict]) -> list[tuple[str, object]]:
    """指标名 → fn(pooled recs)->float（保序：总分系 → 比率系 → per-kind → flag）。"""
    fns: list[tuple[str, object]] = [
        ("stated100_mean", metric_stated100_mean),
        ("derived100_mean", metric_derived100_mean),
        ("score_delta_mean", metric_score_delta_mean),
        ("contested_rate", metric_contested_rate),
        ("span_verified_rate", metric_span_verified_rate),
    ]
    kinds = sorted({str(r.get("kind") or "?") for r in judged})
    fns += [(f"kind_mean/{k}", make_kind_mean(k)) for k in kinds]
    seen = {f for r in judged for f in (r.get("flags") or [])}
    fns += [
        (f"flag_rate/{f}", make_flag_rate(f)) for f in sorted(set(KNOWN_FLAGS) | seen)
    ]
    return fns


def eval_metrics(
    clusters: list[list[dict]],
    fns: list[tuple[str, object]],
    pools: list[list[dict]],
) -> dict[str, dict]:
    """逐 metric 在全 bootstrap 池上求值 → {name:{mean,lo,hi,n,n_clusters}}。"""
    all_recs = [r for c in clusters for r in c]
    out: dict[str, dict] = {}
    for name, fn in fns:
        pt = fn(all_recs)
        vals = []
        for pool in pools:
            v = fn(pool)
            if not math.isnan(v):
                vals.append(v)
        lo, hi = ci_of(vals)
        # 分母规模（point 集上）
        if name.startswith("kind_mean/"):
            kind = name.split("/", 1)[1]
            n = sum(1 for r in all_recs if str(r.get("kind") or "?") == kind)
        elif name == "span_verified_rate":
            n = sum(
                1
                for r in all_recs
                for e in (r.get("errors") or [])
                if isinstance(e, dict)
            )
        elif name in ("derived100_mean", "score_delta_mean"):
            field = name.split("_mean", maxsplit=1)[0]
            n = sum(1 for r in all_recs if _num(r.get(field)))
        else:
            n = len(all_recs)
        out[name] = {
            "mean": round(pt, 4) if not math.isnan(pt) else None,
            "lo": round(lo, 4) if lo is not None else None,
            "hi": round(hi, 4) if hi is not None else None,
            "n": n,
            "n_clusters": metric_denominator_clusters(clusters, name),
            "n_boot_valid": len(vals),
        }
    return out


# ---------------------------------------------------------------- ci 命令
def _records_dir(args: argparse.Namespace) -> Path:
    """DIR 校验：须为含 records.jsonl 的目录（否则早退清晰错误）。"""
    d = Path(args.dir)
    if not d.is_dir():
        sys.exit(f"error: {d} 不是目录")
    if not (d / "records.jsonl").is_file():
        sys.exit(f"error: {d}/records.jsonl 不存在")
    return d


def cmd_ci(args: argparse.Namespace) -> None:
    d = _records_dir(args)
    recs, n_bad = read_jsonl(d / "records.jsonl")
    buckets = split_records(recs)
    judged = buckets["judged"]
    clusters = paper_clusters(judged)
    rng = random.Random(args.seed)
    pools = bootstrap_pools(clusters, args.B, rng)
    fns = build_metric_fns(judged)
    metrics = eval_metrics(clusters, fns, pools)

    payload = {
        "dir": str(d),
        "n_records": len(recs),
        "n_judged": len(judged),
        "n_error": len(buckets["error"]),
        "n_skipped_old_protocol": len(buckets["skipped_old_protocol"]),
        "n_bad_json": n_bad,
        "n_clusters": len(clusters),
        "B": args.B,
        "seed": args.seed,
        "ci_method": "block bootstrap over paper clusters, 95% percentile",
        "metrics": {
            k: {kk: v[kk] for kk in ("mean", "lo", "hi", "n", "n_clusters")}
            for k, v in metrics.items()
        },
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return

    print(f"# qualstats ci — {d}")
    print(
        f"records={len(recs)} judged={len(judged)} "
        f"error={len(buckets['error'])} "
        f"skipped_old_protocol={len(buckets['skipped_old_protocol'])} "
        f"bad_json={n_bad} clusters={len(clusters)}"
    )
    print(
        f"B={args.B} seed={args.seed} (block bootstrap over paper clusters, 95% percentile CI)"
    )
    print()
    hdr = f"{'metric':36} {'mean':>9} {'lo':>9} {'hi':>9} {'n':>6} {'cl':>4}"
    print(hdr)
    print("-" * len(hdr))
    for name, m in metrics.items():

        def _f(v: float | None) -> str:
            return f"{v:9.3f}" if v is not None else f"{'—':>9}"

        print(
            f"{name:36} {_f(m['mean'])} {_f(m['lo'])} {_f(m['hi'])} "
            f"{m['n']:>6} {m['n_clusters']:>4}"
        )
    out_path = d / "ci.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"\njson -> {out_path}")


# ---------------------------------------------------------------- pairacc 命令
def _load_scores(path: Path, key_mode: str) -> tuple[dict[str, float], dict]:
    """records.jsonl → {align_key: score}（数值分优先 stated100，回退 score）。

    同 key 重复：数值分后写覆盖（resume 语义）；error/旧协议行无数值分跳过。
    """
    recs, n_bad = read_jsonl(path)
    scores: dict[str, float] = {}
    n_dup = n_noscore = 0
    for r in recs:
        if key_mode == "paper_chunk":
            k = f"{r.get('paper', '?')}|{r.get('chunk_id', '?')}"
        else:
            k = str(r.get("key") or "")
            if not k:
                k = f"{r.get('paper', '?')}|{r.get('chunk_id', '?')}"
        v = r.get("stated100")
        if not _num(v):
            v = r.get("score")
        if not _num(v):
            n_noscore += 1
            continue
        if k in scores:
            n_dup += 1
        scores[k] = float(v)
    return scores, {
        "n_records": len(recs),
        "n_scored": len(scores),
        "n_noscore": n_noscore,
        "n_dup_keys": n_dup,
        "n_bad_json": n_bad,
    }


def _pair_contrib(items: list[tuple[float, float]]) -> list[float]:
    """全 unordered 对的 tie-calibrated 贡献列：1 / 0.5 / 0。"""
    out = []
    for i in range(len(items)):
        ai, bi = items[i]
        for j in range(i + 1, len(items)):
            da = ai - items[j][0]
            db = bi - items[j][1]
            prod = da * db
            out.append(1.0 if prod > 0 else (0.5 if prod == 0 else 0.0))
    return out


def cmd_pairacc(args: argparse.Namespace) -> None:
    sa, meta_a = _load_scores(Path(args.a), args.key_mode)
    sb, meta_b = _load_scores(Path(args.b), args.key_mode)
    common = sorted(set(sa) & set(sb))
    items = [(sa[k], sb[k]) for k in common]
    n_items = len(items)

    contribs = _pair_contrib(items)
    n_pairs = len(contribs)
    acc = statistics.mean(contribs) if contribs else float("nan")

    # chunk(item) 级 bootstrap：整 item 重采样，重求全 unordered 位对
    # （同一原 item 落两位 → ΔA=ΔB=0 → tie 规则记 0.5）
    rng = random.Random(args.seed)
    vals = []
    if n_items >= 2:
        for _ in range(args.B):
            idx = [rng.randrange(n_items) for _ in range(n_items)]
            pool = [items[i] for i in idx]
            c = _pair_contrib(pool)
            if c:
                vals.append(statistics.mean(c))
    lo, hi = ci_of(vals)

    payload = {
        "a": str(args.a),
        "b": str(args.b),
        "key_mode": args.key_mode,
        "n_items": n_items,
        "n_pairs": n_pairs,
        "n_compared": n_pairs,
        "n_only_a": len(set(sa) - set(sb)),
        "n_only_b": len(set(sb) - set(sa)),
        "acc": round(acc, 4) if not math.isnan(acc) else None,
        "lo": round(lo, 4) if lo is not None else None,
        "hi": round(hi, 4) if hi is not None else None,
        "B": args.B,
        "seed": args.seed,
        "ci_method": "item-level bootstrap over aligned chunks, 95% percentile",
        "side_a": meta_a,
        "side_b": meta_b,
        "tie_rule": "sign(dA)*sign(dB)>0 -> 1; either diff == 0 -> 0.5; else 0",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- report 命令
def _dist(scores: list[float]) -> str:
    c = {label: 0 for _, label in _SCORE_BANDS}
    for s in scores:
        for lo_b, label in _SCORE_BANDS:
            if s >= lo_b:
                c[label] += 1
                break
    return " ".join(f"{label}:{c[label]}" for _, label in _SCORE_BANDS)


def _flag_tally(recs: list[dict]) -> dict[str, int]:
    t: dict[str, int] = {}
    for r in recs:
        for f in r.get("flags") or []:
            t[f] = t.get(f, 0) + 1
    return t


def _ci_str(m: dict | None) -> str:
    if not m or m.get("lo") is None:
        return "—"
    return f"[{m['lo']:.1f}, {m['hi']:.1f}]"


def _quick_ci(recs: list[dict], fn, n_boot: int, seed: int) -> dict | None:
    """report 内嵌单指标 CI：paper 簇 bootstrap（复用同一 rng 序列）。"""
    clusters = paper_clusters(recs)
    if not clusters:
        return None
    rng = random.Random(seed)
    pools = bootstrap_pools(clusters, n_boot, rng)
    vals = []
    for pool in pools:
        v = fn(pool)
        if not math.isnan(v):
            vals.append(v)
    lo, hi = ci_of(vals)
    pt = fn([r for c in clusters for r in c])
    return {
        "mean": pt if not math.isnan(pt) else None,
        "lo": lo,
        "hi": hi,
        "n_clusters": len(clusters),
    }


def write_report(
    recs: list[dict],
    buckets: dict[str, list[dict]],
    meta: dict,
    out_dir: Path,
    n_boot: int,
    seed: int,
    n_bad: int,
) -> None:
    """records+meta → report.md（qualbench 版 + block bootstrap CI 列）。"""
    judged = buckets["judged"]
    n_judged = len(judged)
    n_error = len(buckets["error"])
    n_old = len(buckets["skipped_old_protocol"])

    groups: dict[str, list[dict]] = {}
    by_paper: dict[str, list[dict]] = {}
    by_kind: dict[str, list[dict]] = {}
    cat_sev: dict[str, dict[str, int]] = {}
    for r in judged:
        groups.setdefault(
            f"{r.get('model', '?')} × judge={r.get('judge_model', '?')}", []
        ).append(r)
        by_paper.setdefault(str(r.get("paper")), []).append(r)
        by_kind.setdefault(str(r.get("kind") or "?"), []).append(r)
        for e in r.get("errors") or []:
            if not isinstance(e, dict):
                continue
            row = cat_sev.setdefault(
                str(e.get("category") or "?"),
                {"minor": 0, "major": 0, "critical": 0},
            )
            sev = str(e.get("severity") or "minor")
            row[sev] = row.get(sev, 0) + 1
        for c in r.get("cats_extra") or []:
            cat_sev.setdefault(f"?(extra:{c})", {"minor": 0, "major": 0, "critical": 0})
    contested = [r for r in judged if r.get("contested")]
    worst = sorted(
        judged,
        key=lambda r: (r.get("stated100") or 0, -(r.get("n_errors") or 0)),
    )[:30]

    ci_glob = _quick_ci(judged, metric_contested_rate, n_boot, seed)
    lines = [
        "# qualstats report — 译文质量 LLM-judge（ESA，含 block bootstrap CI）",
        "",
        (
            f"- protocol_v: `{meta.get('protocol_v', '?')}` · "
            f"judge: `{meta.get('judge_model')}`"
            f"（mock={meta.get('mock_judge')}）· 二裁: `{meta.get('second_model')}`"
        ),
        (
            f"- source: {meta.get('source')} · seed={meta.get('seed')} · "
            f"papers={len(meta.get('papers') or [])} · records={len(recs)} · "
            f"judged={n_judged} · judge_error={n_error} · "
            f"skipped_old_protocol={n_old} · bad_json={n_bad}"
        ),
        (
            f"- contested={len(contested)} "
            f"({len(contested) / n_judged * 100:.1f}% "
            f"CI {_ci_str(ci_glob)})"
            if n_judged
            else "- contested=— (无 judged 行)"
        ),
        (
            f"- CI: block bootstrap over paper clusters · B={n_boot} · "
            f"seed={seed} · 95% percentile（簇数小则 CI 退化/偏宽）"
        ),
        f"- started: {meta.get('started_at')}",
        "",
        "## 总分 stated100（model × judge）",
        "",
        "| model × judge | n | mean | 95% CI | median | 分布 ≥90/75+/55+/<55 | Δmean |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name in sorted(groups):
        rs = groups[name]
        scores = [float(r["stated100"]) for r in rs]
        deltas = [float(r["score_delta"]) for r in rs if _num(r.get("score_delta"))]
        m = _quick_ci(rs, metric_stated100_mean, n_boot, seed)
        lines.append(
            f"| {name} | {len(rs)} | {statistics.mean(scores):.1f} "
            f"| {_ci_str(m)} | {statistics.median(scores):.0f} "
            f"| {_dist(scores)} | "
            + (f"{statistics.mean(deltas):+.1f}" if deltas else "—")
            + " |"
        )

    lines += ["", "## 错误分类 × severity（全体 judged chunk）", ""]
    if cat_sev:
        lines += [
            "| category | minor | major | critical | total |",
            "| --- | --- | --- | --- | --- |",
        ]
        for cat, row in sorted(cat_sev.items(), key=lambda kv: -sum(kv[1].values())):
            tot = sum(row.values())
            lines.append(
                f"| `{cat}` | {row['minor']} | {row['major']} | "
                f"{row['critical']} | {tot} |"
            )
    else:
        lines.append("- （无错误标注）")

    lines += [
        "",
        "## flag 频率（类目派生，率带 CI）",
        "",
        "| flag | n | rate | 95% CI |",
        "| --- | --- | --- | --- |",
    ]
    tally = _flag_tally(judged)
    for f in sorted(set(KNOWN_FLAGS) | set(tally)):
        c = tally.get(f, 0)
        m = _quick_ci(judged, make_flag_rate(f), n_boot, seed)
        rate = c / n_judged if n_judged else float("nan")
        lines.append(
            f"| `{f}` | {c} | "
            + (f"{rate:.3f}" if not math.isnan(rate) else "—")
            + f" | {_ci_str(m)} |"
        )

    lines += [
        "",
        "## per-kind",
        "",
        "| kind | n | mean | 95% CI | median | 分布 ≥90/75+/55+/<55 | flags |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for k in sorted(by_kind):
        rs = by_kind[k]
        scores = [float(r["stated100"]) for r in rs]
        ft = _flag_tally(rs)
        m = _quick_ci(rs, metric_stated100_mean, n_boot, seed)
        lines.append(
            f"| {k} | {len(rs)} | {statistics.mean(scores):.1f} "
            f"| {_ci_str(m)} | {statistics.median(scores):.0f} "
            f"| {_dist(scores)} | "
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
    for p in sorted(by_paper):
        rs = by_paper[p]
        scores = [float(r["stated100"]) for r in rs]
        ft = _flag_tally(rs)
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

    if n_old:
        # 旧协议行不进 esa2 指标，但给个摘要留痕（score 字段口径不同，无 CI）
        old_groups: dict[str, list[float]] = {}
        for r in buckets["skipped_old_protocol"]:
            if not _num(r.get("score")):
                continue
            old_groups.setdefault(
                f"{r.get('model', '?')} × judge={r.get('judge_model', '?')}", []
            ).append(float(r["score"]))
        lines += [
            "",
            "## 旧协议行（skipped_old_protocol——`score` 口径非 esa2，不进 CI）",
            "",
            "| model × judge | n | score mean | median | 分布 ≥90/75+/55+/<55 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for name in sorted(old_groups):
            ss = old_groups[name]
            lines.append(
                f"| {name} | {len(ss)} | {statistics.mean(ss):.1f} "
                f"| {statistics.median(ss):.0f} | {_dist(ss)} |"
            )

    if contested:
        lines += [
            "",
            "## contested chunk（触发二裁）",
            "",
            "| paper | chunk | reasons | stated | derived | judge2.stated |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in contested[:30]:
            j2 = r.get("judge2") or {}
            lines.append(
                f"| {r.get('paper')} | {r.get('chunk_id')} "
                f"| {','.join(r.get('contest_reasons') or [])} "
                f"| {r.get('stated100')} | {r.get('derived100')} "
                f"| {j2.get('stated100', j2.get('judge2_error', '—'))} |"
            )

    if worst:
        lines += [
            "",
            "## 最差 chunk（stated100 升序前 30）",
            "",
            "| paper | chunk | kind | stated | Δ | flags | span✗ | note |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in worst:
            if (r.get("stated100") or 0) >= 85 and not r.get("flags"):
                continue
            note = ""
            if r.get("errors"):
                e0 = r["errors"][0]
                if isinstance(e0, dict):
                    note = str(e0.get("note") or "")[:40]
            lines.append(
                f"| {r.get('paper')} | {r.get('chunk_id')} | {r.get('kind', '?')} "
                f"| {r.get('stated100')} | {r.get('score_delta', '—')} "
                f"| {','.join(r.get('flags') or []) or '—'} "
                f"| {r.get('n_span_unverified') or 0} | {note} |"
            )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_report(args: argparse.Namespace) -> None:
    d = _records_dir(args)
    recs, n_bad = read_jsonl(d / "records.jsonl")
    meta_p = d / "run_meta.json"
    meta = {}
    if meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    buckets = split_records(recs)
    write_report(recs, buckets, meta, d, args.B, args.seed, n_bad)
    print(
        f"report -> {d / 'report.md'} ({len(recs)} records, "
        f"judged={len(buckets['judged'])} "
        f"skipped_old_protocol={len(buckets['skipped_old_protocol'])})"
    )


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ci = sub.add_parser("ci", help="paper 簇 block bootstrap 95%% CI")
    p_ci.add_argument("dir", help="含 records.jsonl 的产出目录")
    p_ci.add_argument("--B", type=int, default=1000, help="bootstrap 重采样数")
    p_ci.add_argument("--seed", type=int, default=42)
    p_ci.add_argument(
        "--json", action="store_true", help="只向 stdout 打 JSON（不写 ci.json）"
    )
    p_ci.set_defaults(fn=cmd_ci)

    p_pa = sub.add_parser("pairacc", help="tie-calibrated pairwise accuracy")
    p_pa.add_argument("a", help="A 侧 records.jsonl（如 judge 分）")
    p_pa.add_argument("b", help="B 侧 records.jsonl（如人锚分）")
    p_pa.add_argument(
        "--key-mode",
        choices=["full", "paper_chunk"],
        default="full",
        help="对齐键：full=record key；paper_chunk={paper}|{chunk_id}（人锚用）",
    )
    p_pa.add_argument("--B", type=int, default=1000)
    p_pa.add_argument("--seed", type=int, default=42)
    p_pa.set_defaults(fn=cmd_pairacc)

    p_rp = sub.add_parser("report", help="records+meta → report.md（带 CI 列）")
    p_rp.add_argument("dir")
    p_rp.add_argument("--B", type=int, default=1000)
    p_rp.add_argument("--seed", type=int, default=42)
    p_rp.set_defaults(fn=cmd_report)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
