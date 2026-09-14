#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
fixloop_report.py — 汇总 fixloop-results.json × compile-bench.json,
出 bench/results/fixloop-spike-report.md (中文)。

核心口径:
  rescued_pdf   : compile-bench 原始 xelatex pdf=False 的格, 循环后 final_pdf=True
  clean_pdf     : final_pdf 且 final_errors <= CLEAN_ERR_MAX(3)
  policy_reject : 命中路由规则(LaTeX2.09) 的主动拒绝 — 不算失败也不算救回
"""
import json
import os
from pathlib import Path
from collections import Counter, defaultdict

BENCH = Path(os.path.expanduser("~/src/texlate/bench")).resolve()
RES = BENCH / "results"

RULE_DOC = {
    "static_precheck":  "静态预检: 扫 \\usepackage/\\RequirePackage/\\documentclass → kpsewhich 验证 → 批量 tlmgr install (第0招, 不进循环)",
    "install_file":     "缺文件(.sty/.cls/.fd/.def…) → tlmgr search --global --file '/X' → --usermode install → kpsewhich 复核",
    "install_tfm":      "缺TFM字体(Font X not loadable) → 搜 '/{font}.tfm' → 装包 + updmap-user",
    "install_sysfont":  "fontspec 'font X cannot be found' → 搜 '/{X}.otf|.ttf|.ttc' → 装包 + updmap-user",
    "missing_pfb_updmap": "xdvipdfmx 物理字体缺失 → updmap-user 重建 map",
    "pdftex_prim_guard": "pdfTeX 原语裸用(\\pdfoutput 等11个) → \\ifdefined 守卫包裹",
    "px_to_bp":         "非法单位 px → ×0.75 换算 bp (CSS 96dpi)",
    "microtype_off":    "XeTeXglyph×TFM → microtype [protrusion=false,expansion=false]",
    "times_to_newtx":   "times/mathptmx → newtxtext/newtxmath",
    "hyphenation_sane": "\\hyphenation{} 参数剥离非拉丁 token",
    "soul_cjk_mbox":    "soul 族(\\hl\\ul\\st\\so\\caps) 参数含 CJK → \\mbox 包裹",
    "thm_sibling_strip": "thmtools sibling= 定理计数器冲突 → 剥 sibling 选项",
    "option_clash_merge": "Option clash → 同名包多次加载合并选项",
    "minted_frozencache": "minted frozencache → 有 pygmentize 才去选项(本机无→放弃)",
    "latex209_reject":  "\\documentstyle/LaTeX2.09 → 标记拒绝, 路由 latex+dvips",
    "undefined_cs_guess": "未定义 cs → 占位(需要 cs→包 知识库, 未实现)",
}

VERDICT_CN = {
    "clean": "clean (pdf+0错)",
    "acceptable_pdf": "可接受 (pdf+≤3错)",
    "dirty_pdf": "带错出pdf (>3错)",
    "reject_latex209": "路由拒绝 (LaTeX2.09)",
    "no_main_tex": "无主文件",
}


def main():
    fix = json.loads((RES / "fixloop-results.json").read_text())
    bench = json.loads((RES / "compile-bench.json").read_text())
    cells = fix["cells"]

    # 原始 bench 的 xelatex 结果作对照
    orig = {}
    for pn, p in bench["projects"].items():
        for cond, r in p["runs"].items():
            x = r.get("xelatex") or {}
            orig[(pn, cond)] = x

    lines = []
    A = lines.append
    A("# 编译自动修复循环 spike 报告")
    A("")
    m = fix["meta"]
    A(f"- 日期: {m['date']}  |  引擎: {m['engine']}  |  最大轮数: {m['max_rounds']}")
    A(f"- 环境: `{m['texmf_mode']}` TEXMFHOME (每格独立沙箱, 复现 TeXLive basic 裸环境)  "
      f"|  静态预检: {m['precheck']}")
    A(f"- clean 阈值: pdf 且 '!' 错误 ≤ {m['clean_err_max']}")
    A(f"- 脚本: `bench/py/fixloop.py`  数据: `bench/results/fixloop-results.json`")
    A(f"- 对照组: `compile-bench.json` 原始 xelatex(暖环境) 结果")
    A("")

    # ---------- 总表 ----------
    A("## 1. 自动救回率")
    A("")
    n = len(cells)
    n_orig_fail = sum(1 for c in cells
                      if not orig.get((c["project"], c["cond"]), {}).get("pdf"))
    rescued = [c for c in cells
               if not orig.get((c["project"], c["cond"]), {}).get("pdf")
               and c["final_pdf"]]
    rescued_clean = [c for c in rescued
                     if (c["final_errors"] or 0) <= 3]
    rejects = [c for c in cells if c["verdict"] == "reject_latex209"]
    A("| 口径 | 数 | 率 |")
    A("|---|---|---|")
    A(f"| 总格数 (12项目×3条件) | {n} | |")
    A(f"| 原始 xelatex 即失败(无pdf) | {n_orig_fail} | |")
    A(f"| **循环救回 pdf** | **{len(rescued)}** | "
      f"**{len(rescued)}/{n_orig_fail} = {len(rescued)/max(n_orig_fail,1)*100:.0f}%** |")
    A(f"| 救回且干净(≤3错) | {len(rescued_clean)} | "
      f"{len(rescued_clean)/max(n_orig_fail,1)*100:.0f}% |")
    A(f"| 路由拒绝(hep-th, 不算救回) | {len(rejects)} | |")
    n_pdf = sum(1 for c in cells if c["final_pdf"])
    n_clean = sum(1 for c in cells if c["verdict"] == "clean")
    n_ok = sum(1 for c in cells if c["verdict"] in ("clean", "acceptable_pdf"))
    A(f"| 终态出pdf总格 | {n_pdf} | {n_pdf}/{n} |")
    A(f"| 终态 clean(0错) | {n_clean} | |")
    A(f"| 终态可接受(≤3错) | {n_ok} | |")
    A("")

    # ---------- 逐格矩阵 ----------
    A("## 2. 逐格矩阵")
    A("")
    A("| 项目 | 条件 | 原始xelatex | 首错类别 | 轮数 | 装包 | 终态 | 错误数 |")
    A("|---|---|---|---|---|---|---|---|")
    for c in cells:
        key = (c["project"], c["cond"])
        o = orig.get(key, {})
        otag = ("FAIL" if not o.get("pdf") else
                ("clean" if o.get("clean") else "pdf~"))
        r0 = c["rounds"][0] if c["rounds"] else {}
        v = VERDICT_CN.get(c["verdict"], c["verdict"] or "?")
        A(f"| {c['project']} | {c['cond']} | {otag} | "
          f"{r0.get('category')}:{r0.get('payload') or ''} | "
          f"{len(c['rounds'])} | {len(c.get('installed', []))} | {v} | "
          f"{r0.get('n_errors')}→{c.get('final_errors')} |")
    A("")

    # ---------- 分类统计 ----------
    A("## 3. 按首错类别的修复成功率")
    A("")
    by_cat = defaultdict(list)
    for c in cells:
        r0 = c["rounds"][0] if c["rounds"] else {}
        cat0 = r0.get("category") or "none"
        # 把 missing_file 按扩展名再细分
        if cat0 == "missing_file" and r0.get("payload"):
            ext = str(r0["payload"]).rsplit(".", 1)[-1]
            cat0 = f"missing_{ext}"
        by_cat[cat0].append(c)
    A("| 首错类别 | 格数 | 救回pdf | 干净(≤3错) | 主要动作 |")
    A("|---|---|---|---|---|")
    for cat, cs in sorted(by_cat.items()):
        nr = sum(1 for c in cs if c["final_pdf"])
        nc = sum(1 for c in cs if (c["final_errors"] or 0) <= 3)
        rules = Counter(a["rule"] for c in cs for a in c["actions"]
                        if a["round"] > 0)
        top = ", ".join(f"{k}×{v}" for k, v in rules.most_common(3))
        A(f"| {cat} | {len(cs)} | {nr} | {nc} | {top} |")
    A("")

    # ---------- 规则触发统计 ----------
    A("## 4. 规则表与触发统计")
    A("")
    fire = Counter()
    success = defaultdict(set)
    for c in cells:
        for a in c["actions"]:
            fire[a["rule"]] += 1
            if c["final_pdf"]:
                success[a["rule"]].add((c["project"], c["cond"]))
    A("| 规则 | 触发次数 | 所在格最终出pdf | 说明 |")
    A("|---|---|---|---|")
    for rid, doc in RULE_DOC.items():
        f = fire.get(rid, 0)
        s = len(success.get(rid, ()))
        A(f"| `{rid}` | {f} | {s} | {doc} |")
    A("")

    # ---------- 修不动 ----------
    A("## 5. 修不动的 case")
    A("")
    bad = [c for c in cells if not c["final_pdf"]
           and c["verdict"] != "reject_latex209"]
    if not bad:
        A("(除路由拒绝对象外全部出pdf)")
    for c in bad:
        r0 = c["rounds"][0] if c["rounds"] else {}
        last = c["rounds"][-1] if c["rounds"] else {}
        A(f"- **{c['project']}/{c['cond']}** verdict=`{c['verdict']}` "
          f"首错 `{r0.get('category')}:{r0.get('payload')}` → "
          f"终错 `{last.get('category')}:{last.get('payload')}` "
          f"({last.get('n_errors')} errs)")
        for l in (c.get("log") or [])[-4:]:
            A(f"  - `{l}`")
    dirty = [c for c in cells if c["final_pdf"]
             and (c["final_errors"] or 0) > 3]
    if dirty:
        A("")
        A("带错出pdf (>3错, 未达 clean 阈值):")
        for c in dirty:
            A(f"- {c['project']}/{c['cond']}: {c['final_errors']} errs "
              f"终错 `{c.get('final_cat')}`")
    A("")
    (RES / "fixloop-spike-report.md").write_text(
        "\n".join(lines), encoding="utf-8")
    print("wrote", RES / "fixloop-spike-report.md")


if __name__ == "__main__":
    main()
