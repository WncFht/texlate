#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""compile_report.py — 汇总 compile-bench.json, 重分类错误, 写 compile-report.md."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compile_bench import RESULTS, classify

JP = RESULTS / "compile-bench.json"
MD = RESULTS / "compile-tables.md"   # 表格产物; 分析正文见手工维护的 compile-report.md
ROUNDS = ["xelatex_r1", "xelatex_r2", "xelatex_r3", "xelatex_r4",
          "xelatex_r5", "xelatex_r6", "xelatex_r7", "xelatex_r8",
          "xelatex_r9", "xelatex_r10", "xelatex_r11", "xelatex_r12"]
CONDS = ("baseline", "ctex", "zh")


def enrich_ctx(run):
    """用当前 log 重取首个'!'行+后5行做上下文(若log对应该轮)."""
    lp = run.get("log")
    if not lp or not Path(lp).exists():
        return run.get("error_ctx")
    try:
        lines = Path(lp).read_text(errors="replace").splitlines()
    except Exception:
        return run.get("error_ctx")
    fe = run.get("first_error")
    for i, ln in enumerate(lines):
        if ln.startswith("!") and (not fe or ln.strip() == fe.strip()
                                   or fe in ln):
            return "\n".join(lines[i:i + 6])
    return run.get("error_ctx")


def recat(run):
    if run.get("timed_out"):
        return "timeout", None
    err = run.get("first_error")
    ctx = enrich_ctx(run)
    if not err and run.get("pdf"):
        return None, None
    cat, pkg = classify(err, ctx, run.get("timed_out", False),
                        run.get("stderr_tail", ""))
    return cat, pkg


def best_xelatex(rec):
    """xelatex 最终态: 原始 or 最近一轮成功的修复记录."""
    if rec.get("xelatex", {}).get("pdf"):
        return rec["xelatex"], "r0"
    for k in reversed(ROUNDS):
        r = rec.get(k)
        if r and r.get("pdf"):
            return r, k
    # 全失败 → 最后一轮(最新错误)
    for k in reversed(ROUNDS):
        if rec.get(k):
            return rec[k], k
    return rec.get("xelatex", {}), "r0"


def main():
    data = json.loads(JP.read_text())
    projs = data["projects"]

    # —— 重分类 ——
    for name, p in projs.items():
        for cond in CONDS:
            rec = p["runs"].get(cond, {})
            for key in ["xelatex", "tectonic"] + ROUNDS:
                r = rec.get(key)
                if r:
                    r["cat2"], r["pkg2"] = recat(r)

    # —— 汇总 ——
    def cell(r):
        if not r:
            return "-"
        if r.get("pdf") and r.get("clean"):
            return "PDF"
        if r.get("pdf"):
            return "pdf~"
        return "FAIL"

    matrix = {}
    for name, p in projs.items():
        row = {}
        for cond in CONDS:
            rec = p["runs"].get(cond, {})
            row[(cond, "tectonic")] = cell(rec.get("tectonic"))
            r, rnd = best_xelatex(rec)
            row[(cond, "xelatex")] = cell(r) if cell(r) != "-" else cell(rec.get("xelatex"))
            row[(cond, "xelatex_raw")] = cell(rec.get("xelatex"))
        matrix[name] = row

    def rate(engine, cond, use_final=True):
        ok = cl = 0
        for name, row in matrix.items():
            k = (cond, engine) if (engine != "xelatex" or use_final) \
                else (cond, "xelatex_raw")
            v = row[k]
            ok += v in ("PDF", "pdf~")
            cl += v == "PDF"
        return ok, cl

    # —— 失败分类统计 ——
    cat_counter = defaultdict(list)   # cat -> [(proj,cond,eng,err)]
    for name, p in projs.items():
        for cond in CONDS:
            rec = p["runs"].get(cond, {})
            for key in ["xelatex", "tectonic"] + ROUNDS:
                r = rec.get(key)
                if r and r.get("cat2") and not r.get("pdf"):
                    cat_counter[r["cat2"]].append(
                        (name, cond, key, r.get("first_error", "")))
                elif r and r.get("cat2") and r.get("pdf") and not r.get("clean"):
                    cat_counter[r["cat2"] + "·dirty"].append(
                        (name, cond, key, r.get("first_error", "")))

    # —— zh/ctex 增量错误 (首个错误与 baseline 不同) ——
    added = {"ctex": [], "zh": []}
    for name, p in projs.items():
        for cond in ("ctex", "zh"):
            for eng in ("tectonic", "xelatex"):
                b = p["runs"]["baseline"].get(eng, {})
                c = p["runs"][cond].get(eng, {})
                if (b.get("first_error") != c.get("first_error")
                        and c.get("first_error")):
                    added[cond].append(
                        (name, eng, c["first_error"][:90]))

    # —— 写报告 ——
    out = []
    A = out.append
    m = data["meta"]
    A("# 编译 Benchmark 报告: 真实 arXiv 源码注入 ctex 重编译成功率\n")
    A(f"- 语料: `{m['corpus']}` — 12 个 arXiv 项目")
    A(f"- 引擎: {m['tectonic']} vs {m['xelatex']}")
    A(f"- 条件: baseline(原文) / ctex(注入 `{m['ctex_line']}`) / zh(英文段落→中文+ctex)")
    A(f"- 判据: 超时 {m['timeout_s']}s; **pdf**=产出PDF; **clean**=全程无 `!` 错误; "
      "xelatex `-interaction=nonstopmode` 最多2遍; "
      "tectonic `-Z continue-on-errors` (≈nonstopmode)")
    A("- 日期: " + m["date"] + "\n")

    A("## 1. 总成功率 (12 项目)\n")
    A("| 引擎 | 条件 | pdf 产出 | clean |")
    A("|---|---|---|---|")
    for eng, lbl in (("tectonic", "tectonic"),
                     ("xelatex_raw", "xelatex (原始环境)"),
                     ("xelatex", "xelatex (修复后)")):
        for c in CONDS:
            if eng == "xelatex_raw":
                ok, cl = rate("xelatex", c, use_final=False)
            elif eng == "xelatex":
                ok, cl = rate("xelatex", c)
            else:
                ok, cl = rate("tectonic", c)
            A(f"| {lbl} | {c} | {ok}/12 | {cl}/12 |")
    A("")

    A("## 2. 逐项目矩阵\n")
    A("PDF=干净出pdf, pdf~=带错误出pdf, FAIL=无pdf; "
      "xelatex 列为修复后最终态\n")
    A("| 项目 | base-t | base-x | ctex-t | ctex-x | zh-t | zh-x |")
    A("|---|---|---|---|---|---|---|")
    for name, row in matrix.items():
        A(f"| {name} | " + " | ".join(
            row[(c, e)] for c in CONDS for e in ("tectonic", "xelatex"))
          + " |")
    A("")

    A("## 3. 失败分类学\n")
    A("| 类别 | 次数(失败) | 代表错误 | 涉及项目 |")
    A("|---|---|---|---|")
    for cat, items in sorted(cat_counter.items(),
                             key=lambda kv: -len(kv[1])):
        if cat.endswith("·dirty"):
            continue
        ex = items[0][3][:70]
        ps = sorted(set(i[0] for i in items))
        A(f"| {cat} | {len(items)} | `{ex}` | {', '.join(ps[:4])} |")
    A("\n### 带错误但出 pdf 的类别\n")
    A("| 类别 | 次数 | 代表错误 | 涉及项目 |")
    A("|---|---|---|---|")
    for cat, items in sorted(cat_counter.items(), key=lambda kv: -len(kv[1])):
        if not cat.endswith("·dirty"):
            continue
        ex = items[0][3][:70]
        ps = sorted(set(i[0] for i in items))
        A(f"| {cat[:-6]} | {len(items)} | `{ex}` | {', '.join(ps[:4])} |")
    A("")

    A("## 4. ctex/zh 注入新增错误 (首错与 baseline 不同)\n")
    for cond in ("ctex", "zh"):
        A(f"### {cond}\n")
        if not added[cond]:
            A("(无)")
        for name, eng, e in added[cond]:
            A(f"- `{name}` {eng}: `{e}`")
        A("")

    A("## 5. 原始记录\n```json")
    # 精简 JSON: 每 run 只留关键字段
    slim = {}
    for name, p in projs.items():
        slim[name] = {"main": p["main"], "class": p["class"], "runs": {}}
        for cond in CONDS:
            slim[name]["runs"][cond] = {
                k: {kk: r.get(kk) for kk in
                    ("pdf", "clean", "n_errors", "cat2", "pkg2",
                     "first_error", "seconds")}
                for k, r in p["runs"][cond].items()
                if isinstance(r, dict)}
    A(json.dumps(slim, ensure_ascii=False, indent=1)[:6000])
    A("```\n")

    MD.write_text("\n".join(out))
    JP.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print("wrote", MD)
    print("\n".join(out[:80]))


if __name__ == "__main__":
    main()
