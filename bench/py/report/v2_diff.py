"""v1↔v2 双跑 diff harness——``parse_tex``(scanner) vs ``parse_tex_v2``(segmenter)。

对 corpus_v3 稳定抽样 N 篇主文件，**同一 tex 输入**两侧各跑一遍，逐文件记录：

- identity：``reconstruct(res)`` 对基准逐字节（v1 基准=源 tex；v2 基准=
  ``res.vtex``——vtex 是展开后叙事序坐标系）。三档 strict/normalized/diverged。
- chunk 数 / chunk 总字符 / 两侧 chunk 内容多重集差（only-v1 / only-v2）。
- warnings 按 kind 直方图（各自分列）。
- wall ms 各自；``len(res.inputs)`` 未解析 ``\\input`` 数。
- v2 附加 ``vtex_vs_src``：vtex vs 源文三档 = 展开足迹（strict=无净改动）。

主文件定位与 tmp/corpus_v2_smoke.py 同口径：剥注释后含
``\\documentclass|documentstyle`` 的第一个 .tex。超时走 SIGALRM（单侧独立）。

用法::

    uv run python bench/py/report/v2_diff.py                  # --n 200 --seed 20260915
    uv run python bench/py/report/v2_diff.py --n 40           # 冒烟
    uv run python bench/py/report/v2_diff.py --v1-only        # v2 中途不可用时降级
    uv run python bench/py/report/v2_diff.py --out-prefix bench/results/v2-diff-X

产出：``<out-prefix>.md``（汇总）+ ``<out-prefix>.jsonl``（逐文件行）。
import 级 v2 故障自动降级 v1-only 并在报告注明；逐文件 v2 异常落 err 字段。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import signal
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))  # uv venv 外直跑兼容

from texlate.latex.api import parse_tex
from texlate.latex.reconstruct import reconstruct
from texlate.textutil import decode_tex

try:  # segmenter 在改——import 级故障不阻塞 v1 半侧
    from texlate.latex.segmenter import parse_tex_v2

    V2_IMPORT_ERR: str | None = None
except Exception as exc:
    parse_tex_v2 = None
    V2_IMPORT_ERR = f"{type(exc).__name__}: {exc}"

CORPUS = REPO / "bench" / "corpus_v3"
MANIFEST = CORPUS / "manifest.jsonl"

_DOCCLASS = re.compile(r"\\(documentclass|documentstyle)\s*(?:\[[^\]]*\])?\s*\{")
_COMMENT = re.compile(r"(?<!\\)%[^\n]*")
_WS_RUN = re.compile(r"\s+")


class ParseTimeout(Exception):
    """SIGALRM 触发的单侧超时。"""


def _alarm(signum, frame):
    raise ParseTimeout


def find_main(extracted: Path) -> Path | None:
    """剥注释后含 ``\\documentclass`` 的第一个 .tex（smoke/parsebench 同口径）。"""
    for f in sorted(extracted.rglob("*")):
        if f.is_file() and f.suffix.lower() == ".tex":
            try:
                stripped = _COMMENT.sub("", f.read_text(errors="replace"))
            except OSError:
                continue
            if _DOCCLASS.search(stripped):
                return f
    return None


def classify(orig: str, recon: str) -> tuple[str, int]:
    """identity 三档：strict 逐字节 / normalized 仅空白差 / diverged + 首差异位。"""
    if orig == recon:
        return "strict", -1
    if _WS_RUN.sub(" ", orig).strip() == _WS_RUN.sub(" ", recon).strip():
        return "normalized", -1
    i, n = 0, min(len(orig), len(recon))
    while i < n and orig[i] == recon[i]:
        i += 1
    return "diverged", i


def _run(fn, tex: str, timeout_s: int) -> dict:
    """单侧执行 + 超时/异常兜底。返回 ok/ms 骨架，判定字段由调用方填。"""
    t0 = time.perf_counter()
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    try:
        res = fn(tex)
    except ParseTimeout:
        return {"ok": False, "err": f"Timeout(>{timeout_s}s)", "ms": timeout_s * 1000}
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return {"ok": False, "err": f"{type(exc).__name__}: {exc}", "ms": round(ms, 1)}
    finally:
        signal.alarm(0)
    return {"ok": True, "res": res, "ms": round((time.perf_counter() - t0) * 1000, 1)}


def _fill(out: dict, res, baseline: str) -> list[str]:
    """``_run`` ok 分支的公共判定：identity/chunk/warn/inputs。返回 chunk 文本列。"""
    out["n_chunks"] = len(res.chunks)
    out["chunk_chars"] = sum(len(c.content) for c in res.chunks)
    out["n_ph"] = len(res.ph_map)
    out["warn"] = dict(Counter(w.kind for w in res.warnings))
    out["n_inputs"] = len(res.inputs)
    try:
        status, at = classify(baseline, reconstruct(res))
        out["identity"] = status
        if at >= 0:
            out["first_diff_at"] = at
    except Exception as exc:
        out["identity"] = "recon_error"
        out["err"] = f"reconstruct: {type(exc).__name__}: {exc}"
    return [c.content for c in res.chunks]


def run_file(tex: str, timeout_s: int, *, v1_only: bool = False) -> dict:
    """同一 tex 双跑。返回 {v1: {...}, v2: {...}, chunks_*: 多重集差}。"""
    row: dict = {}
    r1 = _run(parse_tex, tex, timeout_s)
    v1 = {"ok": r1["ok"], "ms": r1["ms"]}
    c1: list[str] = []
    if r1["ok"]:
        c1 = _fill(v1, r1["res"], tex)
    else:
        v1["err"] = r1["err"]
    row["v1"] = v1

    if v1_only or parse_tex_v2 is None:
        row["v2"] = {"ok": False, "err": V2_IMPORT_ERR or "v1-only", "ms": 0}
        return row

    r2 = _run(parse_tex_v2, tex, timeout_s)
    v2 = {"ok": r2["ok"], "ms": r2["ms"]}
    c2: list[str] = []
    if r2["ok"]:
        res2 = r2["res"]
        c2 = _fill(v2, res2, res2.vtex)
        v2["vtex_len"] = len(res2.vtex)
        v2["vtex_vs_src"], _ = classify(tex, res2.vtex)
    else:
        v2["err"] = r2["err"]
    row["v2"] = v2

    if r1["ok"] and r2["ok"]:
        m1, m2 = Counter(c1), Counter(c2)
        row["chunks_common"] = sum((m1 & m2).values())
        row["chunks_only_v1"] = sum((m1 - m2).values())
        row["chunks_only_v2"] = sum((m2 - m1).values())
    return row


def _pct(sorted_vals: list[float], q: float) -> float:
    """最近秩分位（输入须已排序）。"""
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(len(sorted_vals) - 1, max(0, int(q * len(sorted_vals))))]


def summarize(rows: list[dict], md_path: Path, meta: dict) -> dict:
    """聚合 → markdown 汇总 + 终端打印。返回聚合 dict。"""
    tested = [r for r in rows if "v1" in r]
    n = len(tested)
    v1_ok = [r for r in tested if r["v1"]["ok"]]
    v2_rows = [r for r in tested if "v2" in r and r["v2"].get("err") != "v1-only"]
    v2_ok = [r for r in v2_rows if r["v2"]["ok"]]
    both = [r for r in tested if r["v1"]["ok"] and r.get("v2", {}).get("ok")]

    def _tally(side: str) -> Counter:
        t: Counter = Counter()
        for r in tested:
            s = r.get(side, {})
            if s.get("ok"):
                t[s.get("identity", "?")] += 1
        return t

    def _warn_tot(side: str) -> Counter:
        t: Counter = Counter()
        for r in tested:
            s = r.get(side, {})
            if s.get("ok"):
                t.update(s.get("warn") or {})
        return t

    id1, id2 = _tally("v1"), _tally("v2")
    w1, w2 = _warn_tot("v1"), _warn_tot("v2")
    vs = Counter(r["v2"].get("vtex_vs_src") for r in v2_ok)
    ms1 = sorted(r["v1"]["ms"] for r in v1_ok)
    ms2 = sorted(r["v2"]["ms"] for r in v2_ok)

    # chunk 召回差：per-file 比 v2/v1（v1>0 分母），及多/少/等计数
    ratios = [
        r["v2"]["n_chunks"] / r["v1"]["n_chunks"] for r in both if r["v1"]["n_chunks"]
    ]
    more = sum(1 for r in both if r["v2"]["n_chunks"] > r["v1"]["n_chunks"])
    less = sum(1 for r in both if r["v2"]["n_chunks"] < r["v1"]["n_chunks"])
    eq = len(both) - more - less
    sum_c1 = sum(r["v1"]["n_chunks"] for r in v1_ok)
    sum_c2 = sum(r["v2"]["n_chunks"] for r in v2_ok)
    only1 = sum(r.get("chunks_only_v1", 0) for r in both)
    only2 = sum(r.get("chunks_only_v2", 0) for r in both)
    in1 = sum(r["v1"].get("n_inputs", 0) for r in v1_ok)
    in2 = sum(r["v2"].get("n_inputs", 0) for r in v2_ok)

    kinds = sorted(set(w1) | set(w2))
    err1 = [(r["id"], r["v1"]["err"]) for r in tested if not r["v1"]["ok"]]
    err2 = [
        (r["id"], r["v2"]["err"])
        for r in v2_rows
        if not r["v2"]["ok"] and r["v2"].get("err") != "v1-only"
    ]

    lines = [
        "# v1↔v2 dual-run diff — corpus_v3 main-file sample",
        "",
        (
            f"- date: {meta['date']}   seed: {meta['seed']}   "
            f"timeout/side: {meta['timeout']}s"
        ),
        (
            f"- sampled: {n} files tested "
            f"({meta['no_main']} papers skipped: no main .tex / unreadable)"
        ),
        f"- v2 side: {meta['v2_status']}",
        "",
        "## headline",
        "",
        "| metric | v1 (scanner) | v2 (segmenter) |",
        "|---|---|---|",
        f"| parse ok | {len(v1_ok)}/{n} | {len(v2_ok)}/{len(v2_rows) or n} |",
        f"| identity strict | {id1.get('strict', 0)} | {id2.get('strict', 0)} |",
        (
            f"| identity normalized | {id1.get('normalized', 0)} | "
            f"{id2.get('normalized', 0)} |"
        ),
        f"| identity diverged | {id1.get('diverged', 0)} | {id2.get('diverged', 0)} |",
        (
            f"| identity recon_error | {id1.get('recon_error', 0)} | "
            f"{id2.get('recon_error', 0)} |"
        ),
        f"| Σ chunks | {sum_c1} | {sum_c2} |",
        (
            f"| Σ chunk chars | {sum(r['v1'].get('chunk_chars', 0) for r in v1_ok)} | "
            f"{sum(r['v2'].get('chunk_chars', 0) for r in v2_ok)} |"
        ),
        f"| Σ inputs (unresolved) | {in1} | {in2} |",
        (
            f"| wall ms p50 / p95 / max | "
            f"{_pct(ms1, 0.5):.0f} / {_pct(ms1, 0.95):.0f} / "
            f"{ms1[-1] if ms1 else 0:.0f} | "
            f"{_pct(ms2, 0.5):.0f} / {_pct(ms2, 0.95):.0f} / "
            f"{ms2[-1] if ms2 else 0:.0f} |"
        ),
        (
            f"| vtex_vs_src strict/normalized/diverged | — | "
            f"{vs.get('strict', 0)}/{vs.get('normalized', 0)}/"
            f"{vs.get('diverged', 0)} |"
        ),
        "",
        "## chunk recall delta (both-ok files)",
        "",
        (
            f"- files: {len(both)}   v2 more chunks: **{more}**   fewer: {less}   "
            f"equal: {eq}"
        ),
        (
            f"- per-file n_chunks v2/v1 ratio: median "
            f"{statistics.median(ratios):.3f}   mean {statistics.fmean(ratios):.3f}"
        )
        if ratios
        else "- no overlapping ok files",
        (
            f"- chunk-content multiset diff: only-v1 **{only1}**   only-v2 "
            f"**{only2}**   common {sum(r.get('chunks_common', 0) for r in both)}"
        ),
        "",
        "## warnings by kind",
        "",
        "| kind | v1 | v2 |",
        "|---|---|---|",
    ]
    lines += [f"| {k} | {w1.get(k, 0)} | {w2.get(k, 0)} |" for k in kinds]
    if not kinds:
        lines.append("| — | 0 | 0 |")

    # 差异文件表：ok-flip / identity 变 / chunk 数变 / multiset 有差
    diff = []
    for r in v2_rows:
        v1, v2 = r["v1"], r["v2"]
        flags = []
        if v1["ok"] != v2["ok"]:
            flags.append("ok-flip")
        if v1["ok"] and v2["ok"]:
            if v1.get("identity") != v2.get("identity"):
                flags.append("identity")
            if v1["n_chunks"] != v2["n_chunks"]:
                flags.append("chunks")
            if r.get("chunks_only_v1") or r.get("chunks_only_v2"):
                flags.append("chunk-text")
        if flags:
            diff.append((r, flags))
    lines += [
        "",
        f"## per-file diffs ({len(diff)}/{len(v2_rows)} v2-runnable)",
        "",
        (
            "| file | v1 id | v2 id | chunks v1→v2 | only1→only2 | ms v1→v2 | "
            "vtex_vs_src | flags |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for r, flags in diff[:80]:
        v1, v2 = r["v1"], r["v2"]
        lines.append(
            f"| {r['id']} | {v1.get('identity') or v1.get('err', '—')} | "
            f"{v2.get('identity') or v2.get('err', '—')} | "
            f"{v1.get('n_chunks', '—')}→{v2.get('n_chunks', '—')} | "
            f"{r.get('chunks_only_v1', '—')}→{r.get('chunks_only_v2', '—')} | "
            f"{v1.get('ms', '—')}→{v2.get('ms', '—')} | "
            f"{v2.get('vtex_vs_src', '—')} | {','.join(flags)} |"
        )
    if len(diff) > 80:
        lines.append(f"| … | +{len(diff) - 80} more | | | | | | |")

    if err1 or err2:
        lines += ["", "## errors", "", "| side | file | error |", "|---|---|---|"]
        lines += [f"| v1 | {i} | {e} |" for i, e in err1[:30]]
        lines += [f"| v2 | {i} | {e} |" for i, e in err2[:30]]
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "tested": n,
        "no_main": meta["no_main"],
        "v1": {"ok": len(v1_ok), "identity": dict(id1)},
        "v2": {
            "status": meta["v2_status"],
            "runnable": len(v2_rows),
            "ok": len(v2_ok),
            "identity": dict(id2),
            "vtex_vs_src": dict(vs),
        },
        "chunks": {
            "sum_v1": sum_c1,
            "sum_v2": sum_c2,
            "v2_more": more,
            "v2_less": less,
            "v2_equal": eq,
            "only_v1": only1,
            "only_v2": only2,
        },
        "warn_v1": dict(w1),
        "warn_v2": dict(w2),
        "ms": {
            "v1": {
                "p50": _pct(ms1, 0.5),
                "p95": _pct(ms1, 0.95),
                "max": ms1[-1] if ms1 else 0,
            },
            "v2": {
                "p50": _pct(ms2, 0.5),
                "p95": _pct(ms2, 0.95),
                "max": ms2[-1] if ms2 else 0,
            },
        },
        "errors_v1": err1[:30],
        "errors_v2": err2[:30],
    }


def main() -> None:
    """抽样 → 双跑 → 落盘。"""
    ap = argparse.ArgumentParser(description="v1↔v2 dual-run diff harness")
    ap.add_argument("--n", type=int, default=200, help="抽样文件数")
    ap.add_argument("--seed", type=int, default=20260915)
    ap.add_argument("--timeout", type=int, default=30, help="单侧 SIGALRM 秒")
    ap.add_argument(
        "--v1-only",
        action="store_true",
        help="只跑 v1（v2 中途不可用时降级，报告注明）",
    )
    ap.add_argument(
        "--out-prefix",
        type=Path,
        default=REPO / "bench" / "results" / "v2-diff-2026-09-15",
        help="产出前缀（.md/.jsonl 追加）",
    )
    args = ap.parse_args()

    ids = [json.loads(x)["id"] for x in MANIFEST.read_text().splitlines() if x.strip()]
    random.Random(args.seed).shuffle(ids)

    v2_status = (
        "v1-only (--v1-only)"
        if args.v1_only
        else f"import failed: {V2_IMPORT_ERR}"
        if V2_IMPORT_ERR
        else "ok"
    )

    rows: list[dict] = []
    no_main = tested = 0
    t_all = time.perf_counter()
    jsonl_path = args.out_prefix.with_suffix(".jsonl")
    md_path = args.out_prefix.with_suffix(".md")
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for pid in ids:
            if tested >= args.n:
                break
            ex = CORPUS / pid / "extracted"
            if not ex.is_dir():
                no_main += 1
                continue
            main_f = find_main(ex)
            if main_f is None:
                no_main += 1
                continue
            try:
                tex = decode_tex(main_f.read_bytes())
            except OSError:
                no_main += 1
                continue
            tested += 1
            row = {
                "id": pid,
                "file": str(main_f.relative_to(ex)),
                "bytes": len(tex),
            }
            row.update(run_file(tex, args.timeout, v1_only=args.v1_only))
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if tested % 25 == 0:
                print(
                    f"  [{tested}/{args.n}] {time.perf_counter() - t_all:.0f}s",
                    flush=True,
                )

    meta = {
        "date": "2026-09-15",
        "seed": args.seed,
        "timeout": args.timeout,
        "no_main": no_main,
        "v2_status": v2_status,
    }
    summary = summarize(rows, md_path, meta)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"wrote {md_path}\n      {jsonl_path}")


if __name__ == "__main__":
    main()
