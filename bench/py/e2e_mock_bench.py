#!/usr/bin/env python3
r"""e2e mock bench — corpus39 全量 mock 翻译 → ctex 注入 → 双引擎编译基线（M0 出口判据）。

产品路径版（2026-09-15 起）：解析/翻译/注入/编译全走 ``texlate.*`` 正式实现
（texlate.e2e.{pipe_condition,base_condition}；翻译 = XlatPipeline(MockTranslator)
+ L0 校验器）。旧 miniscanner+BUG1–5 补丁链已退役——patch 全部进 texlate.latex。

每工程条件（attribution 设计来自 tmp/exp/e2e/pipeline.py）:
  base-xel : 原样复制 → xelatex（zh 失败时区分"原文就挂"vs"管线引入"）
  pipe-xel : normalize → mock 翻译 → prepare_chinese(ctex) → xelatex → judge
  pipe-tec : 同上 → tectonic
  base-tec : 原样复制 → tectonic（**仅当 pipe-tec 非 clean 时补跑**，归因用）

路由先行：`route_project`（\documentstyle → reject；仍跑 base-xel 实证拒绝正确性）。
fault_chunks/leftover_ph 即管线 bug 信号（应零）。

用法:
  python3 bench/py/e2e_mock_bench.py [--only SUBSTR] [--conditions base-xel,...]
      [--limit N] [--timeout SEC] [--tag NAME]
产出: bench/results/e2emock-<tag>-<date>/{results.json,matrix.md,summary.md}
工作区: bench/work_e2emock/<cond>/<safe_id>/（gitignored 重产物）
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from texlate.compile.engine import route_project
from texlate.compile.inject import find_main_tex
from texlate.e2e import base_condition, pipe_condition

CORPUS = ROOT / "bench/corpus"
WORK = ROOT / "bench/work_e2emock"
RESULTS_DIR_DEFAULT = "e2emock-corpus39"


# ---------------------------------------------------------------- 条件执行
def run_condition(
    cond: str, src: Path, sid: str, main_rel: str, timeout: float
) -> dict:
    """单条件：复制 → (pipe: normalize→mock→inject | base: 原样) → compile → judge。"""
    engine_name = "xelatex" if cond.endswith("xel") else "tectonic"
    dst = WORK / cond / sid
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    if cond.startswith("pipe"):
        return pipe_condition(dst, engine_name, main_rel, timeout)
    return base_condition(dst, engine_name, main_rel, timeout)


def list_projects() -> list[str]:
    """corpus39 叶目录：直接含 .tex 的顶层目，或 hep-th/math 下的二级目。"""
    out = []
    for p in sorted(CORPUS.iterdir()):
        if not p.is_dir():
            continue
        if any(p.glob("*.tex")):
            out.append(p.name)
        else:
            out.extend(
                f"{p.name}/{d.name}"
                for d in sorted(p.iterdir())
                if d.is_dir() and any(d.glob("*.tex"))
            )
    return out


def safe_id(rel: str) -> str:
    return rel.replace("/", "--")


def run_project(rel: str, conditions: list[str], timeout: float) -> dict:
    src = CORPUS / rel
    sid = safe_id(rel)
    rec: dict = {"id": rel}
    main_path = find_main_tex(src)
    if main_path is None:
        rec["error"] = "no main tex"
        return rec
    main_rel = main_path.relative_to(src).as_posix()
    rec["main"] = main_rel
    route = route_project(src)
    rec["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
    }
    for cond in conditions:
        if cond == "base-tec":
            continue  # 条件性补跑——pipe-tec 非 clean 时再跑
        rec[cond] = run_condition(cond, src, sid, main_rel, timeout)
    if "base-tec" in conditions:
        pt = rec.get("pipe-tec", {}).get("verdict", {}).get("status")
        if pt is not None and pt != "clean":
            rec["base-tec"] = run_condition("base-tec", src, sid, main_rel, timeout)
    return rec


# ---------------------------------------------------------------- 报告
def _status(rec: dict, cond: str) -> str:
    c = rec.get(cond)
    if c is None:
        return "·"
    return c.get("verdict", {}).get("status", "?")


def write_reports(results: dict, out_dir: Path) -> None:
    conds = ["base-xel", "pipe-xel", "pipe-tec", "base-tec"]
    rows = []
    for rel, rec in sorted(results.items()):
        cells = [_status(rec, c) for c in conds]
        route = rec.get("route", {})
        flag = "reject" if route.get("reject") else ""
        rows.append((rel, rec.get("main", "?"), flag, *cells))
    matrix = [
        "| 工程 | main | 路由 | base-xel | pipe-xel | pipe-tec | base-tec |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    matrix.extend("| " + " | ".join(str(x) for x in r) + " |" for r in rows)
    (out_dir / "matrix.md").write_text("\n".join(matrix) + "\n", encoding="utf-8")

    lines = ["# e2e mock bench — corpus39", ""]
    for cond in conds:
        ran = [r[cond] for r in results.values() if r.get(cond)]
        clean = sum(1 for r in ran if r["verdict"]["status"] == "clean")
        lines.append(f"- **{cond}**: clean {clean}/{len(ran)}")
    lines.append("")
    # 归因：pipe 失败 ∧ base clean = 管线引入
    for eng in ("xel", "tec"):
        introduced = []
        for rel, rec in sorted(results.items()):
            p = rec.get(f"pipe-{eng}", {}).get("verdict", {}).get("status")
            b = rec.get(f"base-{eng}", {}).get("verdict", {}).get("status")
            if p not in (None, "clean") and b == "clean":
                introduced.append(rel)
        lines.append(f"- pipe-{eng} 失败且 base-{eng} clean（管线引入）: {introduced}")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="substring filter on project id")
    ap.add_argument("--conditions", default="base-xel,pipe-xel,pipe-tec,base-tec")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--tag", default=RESULTS_DIR_DEFAULT)
    ap.add_argument("--date", default=str(datetime.now(UTC).date()))
    args = ap.parse_args()

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    out_dir = ROOT / "bench/results" / f"{args.tag}-{args.date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    results = json.loads(out_path.read_text()) if out_path.exists() else {}

    projects = list_projects()
    for idx, rel in enumerate(projects):
        if args.only and args.only not in rel:
            continue
        if args.limit is not None and idx >= args.limit:
            break
        print(f"===== [{idx}/{len(projects)}] {rel} conds={conditions}", flush=True)
        rec = run_project(rel, conditions, args.timeout)
        if rel in results:
            results[rel].update(rec)
        else:
            results[rel] = rec
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        write_reports(results, out_dir)
        stat = {c: _status(rec, c) for c in conditions}
        print(f"  -> {stat}", flush=True)
    print(f"done -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
