#!/usr/bin/env python3
r"""iclr_stats.py — ICLR 章节长度统计汇总（双臂）.

三表 join: sections.jsonl (arXiv 臂, arxiv_id 键) + sections_pdf.jsonl
(PDF 臂, orid 键) + accepted.jsonl/map.jsonl (orid↔arxiv_id↔year/track)。

产出 bench/work_iclr/stats.json:
  per_year[year]: {n, n_pdf_arm, body/appendix/refs/abstract 词数分布,
                   n_top_sections, n_bib_items, appendix 率}
  bucket_year[bucket][year]: {n_papers, n_sections, words 分布,
                              frac_of_body 中位}
  track_year[year][track]: {n, body_words 中位}
  calibration: 双臂重叠论文 per-bucket 词数比（pdf/latex）中位数 →
               PDF 臂系统性偏差估计（数学残留噪声）
  unmatched: 状态对账

分布口径: median/p25/p75/mean/p10/p90（词数），外加 n。
词数偏差已知项: PDF 臂数学符号残留 → 偏高；LaTeX 臂 caption 单列。

用法: uv run python bench/py/iclr_stats.py [--md out.md]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from specs import _benchlite as benchlib

REPO = Path(__file__).resolve().parents[2]
WORK = REPO / "bench" / "work_iclr"

BUCKETS = [
    "abstract", "introduction", "related_work", "background", "method",
    "theory", "experiments", "results", "ablation", "analysis",
    "limitations", "conclusion", "acknowledgments", "reproducibility",
    "references", "appendix", "other",
]


def quantiles(xs: list[float]) -> dict:
    if not xs:
        return {}
    s = sorted(xs)
    n = len(s)

    def q(p: float) -> float:
        if n == 1:
            return s[0]
        k = (n - 1) * p
        f = math.floor(k)
        return s[f] + (s[min(f + 1, n - 1)] - s[f]) * (k - f)

    return {
        "n": n, "median": round(q(0.5), 1), "p25": round(q(0.25), 1),
        "p75": round(q(0.75), 1), "p10": round(q(0.10), 1),
        "p90": round(q(0.90), 1), "mean": round(sum(s) / n, 1),
    }


def paper_level_stats(rec: dict) -> dict:
    """归一到单篇粒度：body/appendix/refs/abstract + bucket→words 聚合.

    同 bucket 多节合并（paper 级分布）；frac_of_body 用合并值。
    """
    secs = rec.get("sections") or []
    bw = defaultdict(int)
    for s in secs:
        if s["bucket"] == "references":
            continue
        bw[s["bucket"]] += s["words"]
    body = rec.get("body_words") or sum(
        s["words"] for s in secs if not s["appendix"] and s["bucket"] != "references"
    )
    return {
        "body": body,
        "appendix": rec.get("appendix_words", 0),
        "refs": rec.get("refs_words", 0),
        "abstract": rec.get("abstract_words", 0),
        "n_top": rec.get("n_top_sections", 0),
        "n_bib": rec.get("n_bib_items"),  # PDF 臂无此字段 → None, 分位输入侧滤除
        "bucket_words": dict(bw),
        "n_secs": len(secs),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--md", default="", help="同时输出 markdown 汇总表")
    a = ap.parse_args()

    accepted = {r["orid"]: r for r in benchlib.read_jsonl(WORK / "accepted.jsonl")}
    orid2arxiv: dict[str, str] = {}
    for r in benchlib.read_jsonl(WORK / "map.jsonl"):
        if r.get("arxiv_id"):
            orid2arxiv[r["orid"]] = r["arxiv_id"]

    # ---- 双臂行 → (year, arm, rec) ----
    rows: list[dict] = []
    unmatched = {"latex_no_orid": 0, "pdf_no_accepted": 0}
    for r in benchlib.read_jsonl(WORK / "sections.jsonl"):
        if r.get("status") != "ok":
            continue
        aid = r["arxiv_id"]
        orid = next((o for o, x in orid2arxiv.items() if x == aid), None)
        if orid is None or orid not in accepted:
            unmatched["latex_no_orid"] += 1
            continue
        rows.append({"arm": "latex", "orid": orid, "aid": aid,
                     "year": accepted[orid]["year"],
                     "track": accepted[orid].get("track", "unknown"),
                     **paper_level_stats(r)})
    for r in benchlib.read_jsonl(WORK / "sections_pdf.jsonl"):
        if r.get("status") != "ok":
            continue
        orid = r["orid"]
        if orid not in accepted:
            unmatched["pdf_no_accepted"] += 1
            continue
        rows.append({"arm": "pdf", "orid": orid,
                     "aid": orid2arxiv.get(orid),
                     "year": accepted[orid]["year"],
                     "track": accepted[orid].get("track", "unknown"),
                     **paper_level_stats(r)})

    # ---- 每篇选臂: LaTeX 优先（词数更准），无则 PDF 臂 ----
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["orid"])
        if cur is None or (cur["arm"] == "pdf" and r["arm"] == "latex"):
            best[r["orid"]] = r
    papers = list(best.values())

    # ---- per year ----
    per_year: dict = {}
    years = sorted({r["year"] for r in papers})
    for y in years:
        src = [r for r in papers if r["year"] == y]
        per_year[y] = {
            "n": len(src),
            "n_latex": sum(1 for r in src if r["arm"] == "latex"),
            "n_pdf": sum(1 for r in src if r["arm"] == "pdf"),
            "body": quantiles([r["body"] for r in src]),
            "appendix": quantiles([r["appendix"] for r in src]),
            "refs": quantiles([r["refs"] for r in src]),
            "abstract": quantiles([r["abstract"] for r in src]),
            "n_top_sections": quantiles([r["n_top"] for r in src]),
            "n_bib_items": quantiles(
                [r["n_bib"] for r in src if r["n_bib"] is not None]
            ),
            "appendix_rate": round(
                sum(1 for r in src if r["appendix"] > 0) / max(len(src), 1), 3
            ),
        }

    # ---- bucket × year ----
    bucket_year: dict[str, dict] = defaultdict(dict)
    for b in BUCKETS:
        for y in years:
            src = [r for r in papers if r["year"] == y]
            have = [r for r in src if r["bucket_words"].get(b, 0) > 0]
            if not have:
                continue
            bucket_year[b][y] = {
                "n_papers": len(have),
                "coverage": round(len(have) / max(len(src), 1), 3),
                "words": quantiles([r["bucket_words"][b] for r in have]),
                "frac_body_median": round(
                    sorted(
                        r["bucket_words"][b] / max(r["body"], 1) for r in have
                    )[len(have) // 2],
                    3,
                ),
            }

    # ---- track × year（近两年）----
    track_year: dict[str, dict] = defaultdict(dict)
    for y in years:
        for t in ("oral", "spotlight", "poster", "unknown"):
            sel = [
                r for r in papers if r["year"] == y and r["track"] == t
            ]
            if len(sel) < 5:
                continue
            track_year[y][t] = {
                "n": len(sel),
                "body": quantiles([r["body"] for r in sel]),
                "appendix": quantiles([r["appendix"] for r in sel]),
            }

    # ---- 双臂校准 ----
    by_aid_latex = {r["aid"]: r for r in rows if r["arm"] == "latex" and r["aid"]}
    by_orid_pdf = {r["orid"]: r for r in rows if r["arm"] == "pdf"}
    overlap = [
        (by_aid_latex[orid2arxiv[o]], by_orid_pdf[o])
        for o in by_orid_pdf
        if o in orid2arxiv and orid2arxiv[o] in by_aid_latex
    ]
    calib: dict[str, dict] = {}
    for b in ("body", "appendix", "refs", "abstract"):
        ratios = [
            p[b] / max(l[b], 1)
            for l, p in overlap
            if l.get(b, 0) > 50 and p.get(b, 0) > 50
        ]
        calib[b] = quantiles(ratios)
    calib["n_overlap"] = len(overlap)

    stats = {
        "n_rows": len(rows), "unmatched": unmatched,
        "per_year": per_year, "bucket_year": dict(bucket_year),
        "track_year": dict(track_year), "calibration": calib,
    }
    (WORK / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"rows={len(rows)} overlap={len(overlap)} unmatched={unmatched}", file=sys.stderr)

    if a.md:
        lines = ["# ICLR 章节长度统计（自动产出）\n"]
        for y in years:
            py = per_year[y]
            lines.append(
                f"## {y} (latex={py['n_latex']} pdf={py['n_pdf']})\n"
                f"- body: {json.dumps(py['body'])}\n"
                f"- appendix: {json.dumps(py['appendix'])} (rate={py['appendix_rate']})\n"
            )
        for b in BUCKETS:
            if b not in bucket_year:
                continue
            lines.append(f"## bucket={b}\n")
            for y in years:
                if y in bucket_year[b]:
                    e = bucket_year[b][y]
                    lines.append(f"- {y}: {json.dumps(e)}\n")
        Path(a.md).write_text("".join(lines))


if __name__ == "__main__":
    main()
