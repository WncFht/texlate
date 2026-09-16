"""Gullet corpus bench —— M1 接线前实测门（leader 单 2026-09-15）。

对 corpus_v3 主文档跑 ``Gullet(tex, root_dir=extracted/)`` 抽干展开流，
逐文件记录：耗时 / steps / 输出 token 数 / warnings 分类（gen_overflow,
expansion_overflow, def_parse_fail, missing_input, if_unterminated）/
ArgMismatch 回吐次数 / ``\\if`` 两档（可求值 vs 界标，选中支分布）/
inputs 压栈数；并对 expand_all 输出做 token 级不动点重喂验证。

用法::

    uv run python bench/py/gullet_bench.py --n 60            # 冒烟
    uv run python bench/py/gullet_bench.py                 # 全量 manifest
    uv run python bench/py/gullet_bench.py --out <dir>     # 指定输出目录

输出：``<out>/rows.jsonl`` 逐文件行 + 终端汇总表。系统 python3 不可跑
（import texlate 需 uv venv）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import benchlib

from texlate.arxiv.locate import locate
from texlate.latex.gullet import ArgMismatch, Gullet, _tok_eq
from texlate.textutil import decode_tex

MANIFEST = REPO / "bench" / "corpus_v3" / "manifest.jsonl"


class Measured(Gullet):
    """计数探针：ArgMismatch 回吐 / if 两档 / 选中支。"""

    def __init__(self, *a, **kw) -> None:
        """同 Gullet；追加三个计数器。"""
        super().__init__(*a, **kw)
        self.n_arg_mismatch = 0
        self.n_if_marker = 0  # _eval_if → None（界标档，\ifX 本体交出）
        self.if_selected: list[bool | int] = []  # process_if 的 which（含 IfCond）

    def _invoke(self, t, r):
        """包 ``_invoke``：回吐发生即计数（仍回吐，语义不变）。"""
        try:
            return super()._invoke(t, r)
        except ArgMismatch:
            self.n_arg_mismatch += 1
            raise

    def _eval_if(self, name):
        """包 ``_eval_if``：None → 界标档计数。"""
        r = super()._eval_if(name)
        if r is None:
            self.n_if_marker += 1
        return r

    def process_if(self, which) -> None:
        """包 ``process_if``：可求值档记录选中支（True/False/ifcase idx）。"""
        self.if_selected.append(which)
        return super().process_if(which)


def run_doc(ext: Path, arxiv_id: str) -> dict:
    """单文档展开全程 → 行记录。任何异常落 err 字段（bench 不中断）。"""
    row: dict = {"id": arxiv_id}
    try:
        loc = locate(ext, arxiv_id=arxiv_id)
        main = ext / loc.main
        tex = decode_tex(main.read_bytes())
        row["bytes"] = len(tex)
        row["main"] = loc.main
    except Exception as e:
        row["err"] = f"locate/decode: {e!r}"
        return row
    g = Measured(tex, root_dir=str(ext))
    t0 = time.perf_counter()
    try:
        toks = g.expand_all()
    except Exception as e:
        row["err"] = f"expand: {e!r}"
        row["ms"] = (time.perf_counter() - t0) * 1000
        return row
    row["ms"] = (time.perf_counter() - t0) * 1000
    row["toks"] = len(toks)
    row["steps"] = g.steps
    row["n_inputs"] = len(g.file_texts)
    row["arg_mismatch"] = g.n_arg_mismatch
    row["if_marker"] = g.n_if_marker
    row["if_eval"] = len(g.if_selected)
    sel = Counter(
        "T" if w is True else "F" if w is False else f"case{w}" for w in g.if_selected
    )
    row["if_sel"] = dict(sel)
    row["warn"] = dict(Counter(w.kind for w in g.warnings))

    # 不动点：展开流整列重喂新 Gullet（fresh 宏表/cat表——输入已是 Tok 流）
    g2 = Measured()
    g2.unread(toks)
    t0 = time.perf_counter()
    try:
        toks2 = g2.expand_all()
    except Exception as e:
        row["fp_ms"] = (time.perf_counter() - t0) * 1000
        row["fp"] = f"refeed_err:{e!r}"
        return row
    row["fp_ms"] = (time.perf_counter() - t0) * 1000
    row["fp_steps"] = g2.steps
    if len(toks2) != len(toks):
        row["fp"] = f"len {len(toks)}->{len(toks2)}"
    else:
        for k, (a, b) in enumerate(zip(toks, toks2, strict=True)):
            if not _tok_eq(a, b):
                row["fp"] = (
                    f"tok@{k} {a.kind}:{a.text[:24]!r}!={b.kind}:{b.text[:24]!r}"
                )
                break
        else:
            row["fp"] = "ok"
    return row


def main() -> None:
    """全量/抽样跑 + 汇总打印。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="抽样条数（0=全量）")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "bench" / "results" / "gullet-corpus-2026-09-15",
    )
    args = ap.parse_args()

    entries = benchlib.read_jsonl(MANIFEST)
    if args.n:
        import random

        entries = random.Random(args.seed).sample(entries, min(args.n, len(entries)))

    args.out.mkdir(parents=True, exist_ok=True)
    rows_path = args.out / "rows.jsonl"
    # rows.jsonl append 真账：已有行按 id 续跑跳过（换 seed/样本圈重进自然补齐）
    rows = benchlib.read_jsonl(rows_path)
    done = {r["id"] for r in rows if "id" in r}
    if done:
        print(f"resume: {len(done)} prior rows kept", flush=True)
    t_all = time.perf_counter()
    with rows_path.open("w") as fh:  # 压实重写存量行后继续 append
        for r in rows:
            benchlib.write_jsonl(fh, r)
        for k, e in enumerate(entries):
            if e["id"] in done:
                continue
            ext = REPO / "bench" / "corpus_v3" / e["id"] / "extracted"
            row = run_doc(ext, e["id"])
            row["stratum"] = e.get("stratum_cell", "")
            rows.append(row)
            benchlib.write_jsonl(fh, row)
            if (k + 1) % 50 == 0:
                print(
                    f"  [{k + 1}/{len(entries)}] {time.perf_counter() - t_all:.0f}s",
                    flush=True,
                )
    summarize(rows, args.out)


def summarize(rows: list[dict], out: Path) -> None:
    """汇总表 → 终端 + ``summary.json``。"""
    ok = [r for r in rows if "err" not in r]
    err = [r for r in rows if "err" in r]
    warn_tot: Counter = Counter()
    for r in ok:
        warn_tot.update(r.get("warn", {}))
    if_files = sum(1 for r in ok if r.get("if_eval", 0) + r.get("if_marker", 0) > 0)
    if_eval = sum(r.get("if_eval", 0) for r in ok)
    if_marker = sum(r.get("if_marker", 0) for r in ok)
    sel_tot: Counter = Counter()
    for r in ok:
        sel_tot.update(r.get("if_sel", {}))
    fp_ok = sum(1 for r in ok if r.get("fp") == "ok")
    fp_bad = [(r["id"], r["fp"]) for r in ok if r.get("fp") not in (None, "ok")]
    slow = sorted(ok, key=lambda r: -r.get("ms", 0))[:10]
    steps = sorted(r.get("steps", 0) for r in ok)
    ms = sorted(r.get("ms", 0) for r in ok)

    def pct(v, p):
        return f"{v[int(len(v) * p)]:.0f}" if v else "0"

    summary = {
        "docs": len(rows),
        "ok": len(ok),
        "err": len(err),
        "warn_totals": dict(warn_tot),
        "docs_with_warn": {
            k: sum(1 for r in ok if k in r.get("warn", {})) for k in warn_tot
        },
        "if": {
            "docs": if_files,
            "eval": if_eval,
            "marker": if_marker,
            "eval_rate": if_eval / max(if_eval + if_marker, 1),
            "selected": dict(sel_tot),
        },
        "arg_mismatch_total": sum(r.get("arg_mismatch", 0) for r in ok),
        "arg_mismatch_docs": sum(1 for r in ok if r.get("arg_mismatch", 0)),
        "steps": {
            "p50": pct(steps, 0.5),
            "p95": pct(steps, 0.95),
            "max": steps[-1] if steps else 0,
        },
        "ms": {
            "p50": pct(ms, 0.5),
            "p95": pct(ms, 0.95),
            "max": f"{ms[-1]:.0f}" if ms else "0",
        },
        "fixpoint_ok": fp_ok,
        "fixpoint_bad": fp_bad[:20],
        "slowest": [
            (r["id"], f"{r.get('ms', 0):.0f}ms", r.get("steps", 0), r.get("bytes", 0))
            for r in slow
        ],
        "errors": [(r["id"], r["err"]) for r in err[:20]],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
