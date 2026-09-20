#!/usr/bin/env python3
r"""
compilebench_v3.py — corpus base-arm 编译基线: 分层抽样 × 原文直编 × 双引擎.

底材: bench/corpus/{id}/extracted/(== raw.* 解包树; id 可含 archive 前缀如
astro-ph/0111038). baseline 条件 = 原文直编, 不注入不修复 —— 回答
"语料源文件本身多大比例能编出 PDF"(M2 pipe 臂天花板基准).

与 v2 差异(泛化点):
  - 引擎/判定走产品实现: engine_for + compile.judge(v2 内嵌 scan_log/classify
    退役; 产品 parse_log 双格式计数 + classify_error 同源 F 命名)
  - 冷 TEXMF 沙箱经 XelatexEngine(texmfhome=...) 表达, 语义同 v2
    (TEXMFHOME/VAR/CONFIG 隔离 → 裸环境); tectonic env_extra 同口径传入
  - 超时对齐 v2 墙钟: xelatex compile(timeout=480, passes=2) → per_pass=240s;
    tectonic compile(timeout=240) × ≤2 attempt
  - route_project 每篇实录(reject/eps优先/non_utf8)替代 v2 的 parsebench 标签
  - verdict 沿用 v2 词汇映射: clean→clean, partial→pdf~, fail→FAIL

抽样(--gen-sample): manifest stratum_cell(band×cat_group, 38格) 比例分配
(largest remainder, min 1), seed 定序可复现. 过滤 stub/n_tex=0.

产出(bench/results/compilebench-v3-*-<date>/, 三件套 + run_meta):
  sample.json   抽样定义;  cases.jsonl  逐格明细(paper×engine);
  cells.json    逐篇聚合;  summary.md    per-引擎×per-带矩阵 + top 失败类
  run_meta.json 环境实录(平台/引擎版本/沙箱口径/参数)

用法:
  uv run python bench/py/compilebench_v3.py --gen-sample     # 生成/覆写 sample.json
  uv run python bench/py/compilebench_v3.py                  # 跑样本(断点续跑, (id,eng)粒度)
  uv run python bench/py/compilebench_v3.py --report         # 只重算 cells+summary
Deps: --gen-sample/--report stdlib only; 跑样本路径 lazy-import
  texlate.compile.engine → toolchain → httpx（sys.path 直进 src/ 只解包名，
  第三方依赖仍要环境提供 → uv run 为推荐口径；装了 httpx 的系统 python3 亦可）。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import platform
import random
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import benchlib

CORPUS_DEFAULT = ROOT / "bench/corpus"
WORK_DEFAULT = ROOT / "bench/work_compile_v3"
RESULTS_DEFAULT = f"compilebench-v3-{time.strftime('%Y-%m-%d')}"
V2_CELLS_DEFAULT = ROOT / "bench/results/compilebench-corpusv2-2026-09-15/cells.json"

SEED_DEFAULT = 20260915
SAMPLE_N_DEFAULT = 180
PASS_TIMEOUT = 240.0  # 单 pass/单 attempt 上限(秒), docs/spec/compile.md, 与 v2 同
XELATEX_TIMEOUT = PASS_TIMEOUT * 2  # 产品 compile timeout 是总预算/per_pass
TECTONIC_TIMEOUT = PASS_TIMEOUT
MAX_PASSES = 2
JOBS = 4
CONDS = ("baseline", "zh")

#: tlmgr usermode 装包钉 tuna——mirror.ctan.org round-robin 本机不通
#: (fixloop_bench 同口径, 2026-09-15 实测)。单源在 benchlib。
TUNA_TLNET = benchlib.TUNA_TLNET

#: product verdict.status → v2 词汇(跨基线可比)
VERDICT_MAP = {"clean": "clean", "partial": "pdf~", "fail": "FAIL", "reject": "reject"}

# ---------------- 抽样 ----------------


def band_of_cell(stratum_cell: str) -> str:
    """'a_pre2007' → 'a'(v2 五带词汇)."""
    return (stratum_cell or "?").split("_", 1)[0]


def load_pool(manifest_paths: list[Path], corpus: Path):
    """manifest*.jsonl → 可编译论文池(滤 stub/无 tex)."""
    pool = {}
    for mp in manifest_paths:
        for r in benchlib.iter_jsonl(mp):
            if r.get("format") == "stub" or not r.get("n_tex"):
                continue
            pid = r["id"]
            cell = r.get("stratum_cell") or "?"
            pool[pid] = {
                "id": pid,
                "band": band_of_cell(cell),
                "stratum_cell": cell,
                "cat_group": r.get("cat_group"),
                "yymm": r.get("yymm"),
                "era": r.get("era"),
                "layer": r.get("layer"),
                "format": r.get("format"),
                "n_files": r.get("n_files"),
                "n_tex": r.get("n_tex"),
                "bytes": r.get("bytes"),
                "extracted": (corpus / pid / "extracted").is_dir(),
            }
    return pool


def gen_sample(args):
    """stratum_cell 比例分配(largest remainder, min 1) → sample.json."""
    pool = load_pool(args.manifest, args.corpus)
    pool = {k: v for k, v in pool.items() if v["extracted"]}
    rng = random.Random(args.seed)  # 语料抽样非安全用途
    by_cell = defaultdict(list)
    for p in pool.values():
        by_cell[p["stratum_cell"]].append(p)
    for cell in by_cell.values():
        rng.shuffle(cell)

    n_total = sum(len(v) for v in by_cell.values())
    n_target = min(args.sample_n, n_total)
    # 比例分配: floor + min1 + largest remainder 补齐
    quota = {}
    for cell, ps in by_cell.items():
        exact = n_target * len(ps) / n_total
        quota[cell] = max(1, int(exact))
    while sum(quota.values()) < n_target:
        best = max(
            by_cell,
            key=lambda c: (
                n_target * len(by_cell[c]) / n_total - quota[c],
                -len(by_cell[c]),
            ),
        )
        if quota[best] >= len(by_cell[best]):
            break
        quota[best] += 1
    while sum(quota.values()) > n_target:
        best = max(
            (c for c in quota if quota[c] > 1),
            key=lambda c: quota[c] - n_target * len(by_cell[c]) / n_total,
            default=None,
        )
        if best is None:
            break
        quota[best] -= 1

    picked = []
    for cell, q in sorted(quota.items()):
        picked.extend({**p, "pick_reason": f"cell:{cell}"} for p in by_cell[cell][:q])
    picked.sort(key=lambda p: (p["band"], p["stratum_cell"], p["id"]))
    doc = {
        "seed": args.seed,
        "sample_n": args.sample_n,
        "alloc": "stratum_cell proportional (largest remainder, min 1)",
        "manifests": [str(m) for m in args.manifest],
        "n": len(picked),
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "papers": picked,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "sample.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
    )
    print(f"sample -> {args.out / 'sample.json'}  n={len(picked)}")
    print("bands:", dict(Counter(p["band"] for p in picked)))
    print("cells:", len({p["stratum_cell"] for p in picked}), "stratum_cell")
    return doc


# ---------------- 单篇执行 ----------------

IGNORE = benchlib.copytree_ignore("_texmf")


def _cold_texmf(wdir: Path) -> Path:
    """建冷 usermode texmf 树(home/var/config 三子目录), 返回根."""
    tm = wdir.parent / "_texmf"
    for sub in ("home", "var", "config"):
        (tm / sub).mkdir(parents=True, exist_ok=True)
    return tm


def _run_engine(eng_name: str, wdir: Path, main_rel: str, texmf: Path):
    """产品 engine.compile + judge → case dict(xelatex halt_on_error=False 对齐
    v2 best-effort; texmfhome=冷沙箱). 函数内迟绑 import 保持 --report stdlib-only."""
    from texlate.compile.engine import engine_for
    from texlate.compile.judge import judge

    kw: dict = {}
    if eng_name == "xelatex":
        kw = {"halt_on_error": False, "texmfhome": texmf, "repository": TUNA_TLNET}
    eng = engine_for(eng_name, **kw)
    timeout = XELATEX_TIMEOUT if eng_name == "xelatex" else TECTONIC_TIMEOUT
    env_extra = {
        "TEXMFHOME": str(texmf / "home"),
        "TEXMFVAR": str(texmf / "var"),
        "TEXMFCONFIG": str(texmf / "config"),
    }
    res = eng.compile(
        wdir,
        main_rel,
        passes=MAX_PASSES,
        timeout=timeout,
        sandbox=True,
        env_extra=env_extra,
    )
    v = judge(res, expect_cjk=False)
    return res, v


#: 引擎 stderr/stdout 二次归因(v2 classify 同规则, 产品 classify_error 无此路):
#: tectonic xdvipdfmx 崩因(物理字体/PS图/缺文件)只在 stderr 能区分——
#: 仅当产品类别落弱类(clean/other/emergency)且无 pdf 时启用.
_STDERR_RULES = (
    ("missing_pfb", r"Cannot proceed without .vf|physical font"),
    (
        "ps_image",
        (
            r"PostScript images are not supported|"
            r'image inclusion failed for "[^"]*\.(?:eps|ps)"'
        ),
    ),
    ("missing_file", r"File `([^']+)' not found|I can't find file"),
    ("dvipdf", r"something bad happened inside|error:.*dvipdfmx"),
    ("emergency", r"unrecoverable|Emergency|Fatal|cannot \\read"),
)
_WEAK_CATS = {None, "clean", "other", "emergency", "dvipdf"}


def _refine_category(cat, pay, res):
    """弱类首错时用 stdout_tail(stderr已并入) 再归因 → (cat, pay, refined_flag)."""
    if cat not in _WEAK_CATS or res.has_pdf or not res.stdout_tail:
        return cat, pay, False
    for name, pat in _STDERR_RULES:
        m = re.search(pat, res.stdout_tail, re.IGNORECASE)
        if m:
            return name, next((g for g in m.groups() if g), pay), True
    return cat, pay, False


def run_paper(p, corpus: Path, work: Path, engines: list[str], cond: str = "baseline"):
    """复制 → find_main_tex + route_project → per-engine 编译判定.

    cond=zh: 每引擎独立拷贝 → normalize_project → prepare_chinese(ctex 注入)
    → 编译(docs/spec/benchmark.md §B3 网格 zh-injected 臂; inject 拒绝记 inject_reject)。
    """
    pid = p["id"]
    src = corpus / pid / "extracted"
    wdir = work / pid / cond
    paper = {
        "id": pid,
        "band": p["band"],
        "stratum_cell": p["stratum_cell"],
        "cat_group": p["cat_group"],
        "yymm": p["yymm"],
        "era": p["era"],
        "layer": p["layer"],
        "n_files": p["n_files"],
        "n_tex": p["n_tex"],
        "main": None,
        "route": None,
        "engines": {},
    }
    if not src.is_dir():
        for eng in engines:
            paper["engines"][eng] = {"verdict": "no_source", "engine": eng}
        return paper, []

    from texlate.compile.engine import route_project
    from texlate.compile.inject import classify_no_main, find_main_tex

    # 检测面用 src: copytree 对 .tex/.eps 等检测对象字节保真, src ≡ wdir
    route = route_project(src)
    paper["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    p["route"] = paper["route"]  # 回填 sample 记录, _case_base 用
    main = find_main_tex(src)
    if not main:
        sub = classify_no_main(src) or ""
        for eng in engines:
            paper["engines"][eng] = {
                "verdict": "no_main_tex",
                "engine": eng,
                "verdict_sub": sub,
            }
        return paper, []
    main_rel = main.relative_to(src).as_posix()
    paper["main"] = main_rel
    texmf = _cold_texmf(wdir)

    cases = []
    for eng_name in engines:
        prep: dict = {}
        if cond == "zh":
            cur = work / pid / f"zh-{eng_name}"
            if cur.exists():
                shutil.rmtree(cur)
            shutil.copytree(src, cur, ignore=IGNORE)
            from texlate.compile.inject import InjectRejectError, prepare_chinese
            from texlate.compile.normalize import normalize_project

            try:
                prep["normalize"] = normalize_project(cur, eng_name, main_rel)
                prep["inject"] = prepare_chinese(cur, main_rel)
            except InjectRejectError as e:
                r = {
                    "engine": eng_name,
                    "verdict": "reject",
                    "category": "inject_reject",
                    "payload": e.reason,
                }
                paper["engines"][eng_name] = r
                cases.append({**_case_base(p, pid, eng_name, main_rel, cond), **r})
                continue
        else:
            if wdir.exists():
                shutil.rmtree(wdir)
            shutil.copytree(src, wdir, ignore=IGNORE)
            cur = wdir
        try:
            res, v = _run_engine(eng_name, cur, main_rel, texmf)
        except Exception as e:
            r = {
                "engine": eng_name,
                "verdict": "FAIL",
                "category": "harness_crash",
                "payload": f"{type(e).__name__}: {e}",
            }
            paper["engines"][eng_name] = r
            cases.append({**_case_base(p, pid, eng_name, main_rel, cond), **r})
            continue
        cat, pay, refined = _refine_category(v.category, v.payload, res)
        rec = {
            "engine": eng_name,
            "status": v.status,
            "verdict": VERDICT_MAP.get(v.status, v.status),
            "reasons": v.reasons,
            "category": cat,
            "category_raw": v.category,
            "category_stderr": refined,
            "payload": pay,
            "n_errors": v.n_errors,
            "warnings_hit": v.warnings_hit,
            "missing_chars": v.missing_chars,
            "error_cats": v.error_cats,
            "error_pay": v.error_pay,
            "pdf": res.has_pdf,
            "pdf_bytes": res.pdf_bytes,
            "passes": res.passes,
            "seconds": round(res.seconds, 1),
            "timed_out": res.timed_out,
            "rc": res.rc,
            "first_error": (res.log.first_error or "")[:200] or None,
            "stdout_tail": (res.stdout_tail or "")[-800:],
            "n_deps": len(res.deps) if res.deps else 0,
            "deps": res.deps,
            "log": str(res.log_path) if res.log_path else None,
            **prep,
        }
        paper["engines"][eng_name] = rec
        cases.append({**_case_base(p, pid, eng_name, main_rel, cond), **rec})
    return paper, cases


def _case_base(p, pid, eng_name, main_rel, cond="baseline"):
    return {
        "corpus": "corpus",
        "cond": cond,
        "paper_id": pid,
        "band": p["band"],
        "stratum_cell": p["stratum_cell"],
        "cat_group": p["cat_group"],
        "engine": eng_name,
        "main": main_rel,
        "route_reject": (p.get("route") or {}).get("reject"),
        "route_non_utf8": (p.get("route") or {}).get("non_utf8"),
        "route_latex209_suspect": (p.get("route") or {}).get("latex209_suspect"),
    }


# ---------------- 汇总 ----------------

F_MAP = {
    "missing_file": "F1/F4 missing_pkg/cls/file",
    "missing_tfm": "F2 missing_font(TFM)",
    "missing_pfb": "F3 physical font @xdvipdfmx",
    "fontspec_missing": "F2/F3 fontspec font",
    "xetexglyph_tfm": "F7 XeTeXglyph×TFM",
    "pdftex_prim": "F5 pdfTeX 原语",
    "illegal_unit": "F6 非法单位",
    "soul_err": "F8 soul×CJK",
    "hyphenation": "F9 hyphenation",
    "minted_froz": "F10 minted",
    "already_def": "F11 宏冲突",
    "latex209": "F12 LaTeX2.09",
    "ps_image": "路由 eps/ps→xelatex",
    "eps_image": "路由 eps/ps→xelatex",  # 旧结果文件的改名前类别名
    "inputenc_unicode": "inputenc 拒载 Unicode 引擎",
    "timeout": "超时",
    "capacity": "TeX capacity",
    "emergency": "Emergency stop",
    "undefined_cs": "未定义控制序列",
    "env_mismatch": "环境不配平",
    "option_clash": "包选项冲突",
    "bib_error": "bibliography",
    "syntax": "语法",
    "harness_crash": "bench 自身异常",
    "other": "其他",
    "clean": "—",
}


def _engine_versions(engines: list[str]) -> dict:
    vers = {}
    for eng in engines:
        with contextlib.suppress(Exception):
            out = subprocess.run(
                [eng, "--version"], capture_output=True, text=True, timeout=15
            )
            vers[eng] = (out.stdout or out.stderr).strip().splitlines()[0]
    return vers


def write_run_meta(args, engines, phase):
    meta = {
        "phase": phase,
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cwd": str(ROOT),
        "corpus": str(args.corpus),
        "work": str(args.work),
        "out": str(args.out),
        "engines": engines,
        "condition": getattr(args, "condition", "baseline"),
        "engine_versions": _engine_versions(engines),
        "pass_timeout_s": PASS_TIMEOUT,
        "xelatex_timeout_total_s": XELATEX_TIMEOUT,
        "tectonic_timeout_s": TECTONIC_TIMEOUT,
        "max_passes": MAX_PASSES,
        "sandbox": "product sandbox_wrap (sandbox-exec darwin / passthrough linux)"
        " + child_env 白名单 + 冷 TEXMFHOME/VAR/CONFIG",
        "xelatex_flags": "-no-shell-escape -interaction=nonstopmode"
        " -file-line-error -recorder (halt_on_error=False)",
        "tectonic_flags": "-X compile --untrusted -Z continue-on-errors"
        " --keep-logs --keep-intermediates --makefile-rules",
        "judge": "texlate.compile.judge(expect_cjk=False)",
        "jobs": args.jobs,
        "sample_n": args.sample_n,
        "seed": args.seed,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "run_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n"
    )
    return meta


def report(args):
    cases = benchlib.read_jsonl(args.out / "cases.jsonl")
    cells_path = args.out / "cells.json"
    papers = {}
    if cells_path.exists():
        with contextlib.suppress(Exception):
            for p in json.loads(cells_path.read_text())["papers"]:
                papers[p["id"]] = p
    meta = write_run_meta(args, sorted({c["engine"] for c in cases}), "report")
    engines = sorted({c["engine"] for c in cases}) or ["xelatex", "tectonic"]
    doc = {"meta": meta, "papers": sorted(papers.values(), key=lambda p: p["id"])}
    cells_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")

    by_eng = defaultdict(list)
    for c in cases:
        by_eng[c["engine"]].append(c)
    n_papers = len(papers)

    pdf_by_id = defaultdict(set)
    clean_by_id = defaultdict(set)
    for c in cases:
        if c.get("pdf"):
            pdf_by_id[c["paper_id"]].add(c["engine"])
        if c["verdict"] == "clean":
            clean_by_id[c["paper_id"]].add(c["engine"])

    cond_lbl = cases[0].get("cond", "baseline") if cases else "baseline"
    lines = []
    lines.append(f"# compilebench v3 — corpus {cond_lbl} × 双引擎")
    lines.append("")
    lines.append(f"- 日期: {meta['date']}")
    lines.append(
        f"- 语料: `{args.corpus}` extracted/ 分层抽样 n={n_papers} "
        f"(sample.json, seed={args.seed}, stratum_cell 比例分配)"
    )
    lines.append(f"- 平台: {meta['platform']}")
    lines.extend(
        f"- {eng}: `{meta['engine_versions'].get(eng, '?')}`" for eng in engines
    )
    lines.append(
        "- 条件: "
        + (
            "baseline 原文直编, 不注入不修复"
            if cond_lbl == "baseline"
            else "zh — normalize_project + prepare_chinese(ctex) 后直编, 不修复"
        )
        + f"; xelatex ≤{MAX_PASSES}pass×{PASS_TIMEOUT:.0f}s, tectonic {TECTONIC_TIMEOUT:.0f}s"
    )
    lines.append(
        "- 判定: 产品 `texlate.compile.judge`(expect_cjk=False); "
        "clean = pdf ∧ err≤3 ∧ 首错非missing_*/undefined_cs ∧ warn红线零命中"
    )
    lines.append("")

    lines.append("## 1. 总成功率")
    lines.append("")
    lines.append("| 引擎 | n | clean | pdf~ | FAIL | clean率 | pdf率 |")
    lines.append("|---|---|---|---|---|---|---|")
    for eng in engines:
        cs = by_eng.get(eng, [])
        n = len(cs)
        if not n:
            lines.append(f"| {eng} | 0 | — | — | — | — | — |")
            continue
        ncl = sum(1 for c in cs if c["verdict"] == "clean")
        npd = sum(1 for c in cs if c["verdict"] == "pdf~")
        nfl = sum(1 for c in cs if c["verdict"] == "FAIL")
        npdf = sum(1 for c in cs if c.get("pdf"))
        lines.append(
            f"| {eng} | {n} | {ncl} | {npd} | {nfl} | "
            f"{ncl / n * 100:.1f}% | {npdf / n * 100:.1f}% |"
        )
    lines.append("")
    pdf_pct = len(pdf_by_id) / n_papers * 100 if n_papers else 0.0
    clean_pct = len(clean_by_id) / n_papers * 100 if n_papers else 0.0
    lines.append(
        f"联合覆盖: 任一引擎出 pdf {len(pdf_by_id)}/{n_papers} "
        f"({pdf_pct:.1f}%); "
        f"任一引擎 clean {len(clean_by_id)}/{n_papers} "
        f"({clean_pct:.1f}%); "
        f"全引擎皆死 {n_papers - len(pdf_by_id)}"
    )
    lines.append("")

    # ---- per-band 矩阵 ----
    band_of_id = {p["id"]: p.get("band", "?") for p in doc["papers"]}
    lines.append("## 2. per-引擎 × per-带 成功率矩阵 (clean / pdf~ / FAIL)")
    lines.append("")
    hdr = "| 带 | n |" + "".join(
        f" {eng[:3]} clean | {eng[:3]} pdf~ | {eng[:3]} FAIL |" for eng in engines
    )
    lines.append(hdr)
    lines.append("|" + "---|" * (2 + 3 * len(engines)))
    for b in sorted(set(band_of_id.values())):
        ids = {i for i, bb in band_of_id.items() if bb == b}
        row = [b, str(len(ids))]
        for eng in engines:
            cs = [c for c in by_eng.get(eng, []) if c["paper_id"] in ids]
            row += [
                str(sum(1 for c in cs if c["verdict"] == "clean")),
                str(sum(1 for c in cs if c["verdict"] == "pdf~")),
                str(sum(1 for c in cs if c["verdict"] == "FAIL")),
            ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- per-cat_group 矩阵(pdf 率) ----
    cg_of_id = {p["id"]: p.get("cat_group") or "?" for p in doc["papers"]}
    lines.append("## 2b. per-引擎 × cat_group pdf 率")
    lines.append("")
    lines.append(
        "| cat_group | n |" + " | ".join(f" {eng} pdf率 " for eng in engines) + " |"
    )
    lines.append("|" + "---|" * (2 + len(engines)))
    for cg in sorted(set(cg_of_id.values())):
        ids = {i for i, g in cg_of_id.items() if g == cg}
        row = [cg, str(len(ids))]
        for eng in engines:
            cs = [c for c in by_eng.get(eng, []) if c["paper_id"] in ids]
            row.append(f"{sum(1 for c in cs if c.get('pdf'))}/{len(cs)}" if cs else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- 路由实录 ----
    lines.append("## 3. route_project 实录 × 结果")
    lines.append("")
    rej_ids = {p["id"] for p in doc["papers"] if (p.get("route") or {}).get("reject")}
    sus_ids = {
        p["id"] for p in doc["papers"] if (p.get("route") or {}).get("latex209_suspect")
    }
    nu8_ids = {p["id"] for p in doc["papers"] if (p.get("route") or {}).get("non_utf8")}
    eps_ids = {
        p["id"]
        for p in doc["papers"]
        if any(
            "eps" in rsn or "pstricks" in rsn
            for rsn in (p.get("route") or {}).get("reasons", [])
        )
    }
    lines.append(
        "| 路由标记 | n篇 |"
        + " | ".join(f" {eng} clean/pdf~/FAIL " for eng in engines)
        + " |"
    )
    lines.append("|" + "---|" * (2 + len(engines)))
    for label, ids in (
        ("reject(route)", rej_ids),
        ("latex209_suspect(\\documentstyle 试编)", sus_ids),
        ("non_utf8", nu8_ids),
        ("eps/pstricks→xel优先", eps_ids),
    ):
        if not ids:
            continue
        row = [label, str(len(ids))]
        for eng in engines:
            cs = [c for c in by_eng.get(eng, []) if c["paper_id"] in ids]
            row.append(
                f"{sum(1 for c in cs if c['verdict'] == 'clean')}/"
                f"{sum(1 for c in cs if c['verdict'] == 'pdf~')}/"
                f"{sum(1 for c in cs if c['verdict'] == 'FAIL')}"
            )
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- top 失败类别 ----
    lines.append("## 4. top 失败类别 (首错归因, fixloop F 命名)")
    lines.append("")
    for eng in engines:
        cats = Counter(
            c["category"]
            for c in by_eng.get(eng, [])
            if c["verdict"] in ("pdf~", "FAIL") and c["category"]
        )
        lines.append(f"### {eng}")
        lines.append("")
        lines.append("| 类别 | F映射 | 格数 | 代表 payload |")
        lines.append("|---|---|---|---|")
        for cat, n in cats.most_common(15):
            pay = next(
                (
                    c.get("payload")
                    for c in by_eng[eng]
                    if c["category"] == cat and c.get("payload")
                ),
                "—",
            )
            lines.append(f"| {cat} | {F_MAP.get(cat, '—')} | {n} | {pay} |")
        lines.append("")

    # ---- 逐篇明细 ----
    lines.append("## 5. 逐篇明细")
    lines.append("")
    lines.append("| paper | band | cell | route |" + " | ".join(engines) + " |")
    lines.append("|" + "---|" * (4 + len(engines)))
    for p in doc["papers"]:
        route = p.get("route") or {}
        rmark = []
        if route.get("reject"):
            rmark.append("reject")
        if route.get("latex209_suspect"):
            rmark.append("209suspect")
        if route.get("non_utf8"):
            rmark.append("non-utf8")
        row = [
            p["id"],
            p.get("band", "?"),
            p.get("stratum_cell", "?"),
            ",".join(rmark) or "—",
        ]
        for eng in engines:
            r = p["engines"].get(eng, {})
            v = r.get("verdict", "—")
            row.append(
                f"{v}({r.get('n_errors', '-')}/{r.get('category', '-')})"
                if v not in ("—", None)
                else "—"
            )
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- 与 corpus_v2 基线对比 ----
    if args.v2_cells and Path(args.v2_cells).exists():
        try:
            v2 = json.loads(Path(args.v2_cells).read_text())
            v2_cases = defaultdict(dict)
            for p in v2["papers"]:
                for eng, r in p.get("engines", {}).items():
                    v2_cases[eng][p["id"]] = r
            lines.append("## 6. 与 corpus_v2 基线对比 (v2: n=40 分层, 同冷沙箱口径)")
            lines.append("")
            lines.append("| 指标 | corpus_v2 (n=40) | corpus (本轮) |")
            lines.append("|---|---|---|")
            for eng in engines:
                r2 = list(v2_cases.get(eng, {}).values())
                c3 = by_eng.get(eng, [])
                if r2 and c3:
                    v2cl = sum(1 for r in r2 if r.get("verdict") == "clean")
                    v2pdf = sum(1 for r in r2 if r.get("pdf"))
                    lines.append(
                        f"| {eng} clean率 | {v2cl}/{len(r2)} = "
                        f"{v2cl / len(r2) * 100:.1f}% | "
                        f"{sum(1 for c in c3 if c['verdict'] == 'clean')}/{len(c3)} = "
                        f"{sum(1 for c in c3 if c['verdict'] == 'clean') / len(c3) * 100:.1f}% |"
                    )
                    lines.append(
                        f"| {eng} pdf率 | {v2pdf}/{len(r2)} = "
                        f"{v2pdf / len(r2) * 100:.1f}% | "
                        f"{sum(1 for c in c3 if c.get('pdf'))}/{len(c3)} = "
                        f"{sum(1 for c in c3 if c.get('pdf')) / len(c3) * 100:.1f}% |"
                    )
            lines.append(
                f"| 联合pdf | — | {len(pdf_by_id)}/{n_papers} = {pdf_pct:.1f}% |"
            )
            lines.append("")
        except Exception as e:
            lines.append(f"## 6. corpus_v2 对比加载失败: {e}")
            lines.append("")

    # ---- M2 启示(数字骨架, 人工补解读) ----
    lines.append("## 7. 对 M2 ≥90% 目标的可行性")
    lines.append("")
    for eng in engines:
        cs = by_eng.get(eng, [])
        if not cs:
            continue
        npdf = sum(1 for c in cs if c.get("pdf"))
        ncl = sum(1 for c in cs if c["verdict"] == "clean")
        top = Counter(
            c["category"] for c in cs if c["verdict"] == "FAIL" and c["category"]
        ).most_common(3)
        lines.append(
            f"- {eng}: pdf {npdf}/{len(cs)} ({npdf / len(cs) * 100:.1f}%), "
            f"clean {ncl}/{len(cs)} ({ncl / len(cs) * 100:.1f}%), "
            f"top FAIL: {', '.join(f'{k}×{v}' for k, v in top) or '—'}"
        )
    lines.append(
        f"- 联合天花板: 任一引擎 pdf {pdf_pct:.1f}%, "
        f"clean {clean_pct:.1f}% —— "
        "fixloop+路由+normalize 需要补的百分点即 90%−此值"
    )
    lines.append("")
    lines.append("### 口径备注")
    lines.append("")
    lines.append(
        "- xelatex 跑在冷 TEXMF 沙箱(每篇独立 TEXMFHOME/VAR/CONFIG → "
        "不继承用户已装包), tectonic 用自带 bundle(缓存热身后即暖); "
        "判定器为产品 judge(v2 内嵌版退役), 红线集见 engine.WARNING_RED_LINES。"
    )
    lines.append(
        "- \\documentstyle 已降级为 latex209_suspect 试编标记(route 不再 reject)——"
        "真实试编, FAIL 计入管线缺口; fixloop 侧 latex209_reject gate 在"
        "真 2.09 错时兜底拒。inject 层拒绝记 inject_reject:latex209 类。"
    )
    lines.append("")
    (args.out / "summary.md").write_text("\n".join(lines) + "\n")
    print(
        f"report -> {args.out}/summary.md, cells.json "
        f"({n_papers} papers, {len(cases)} cases)"
    )


# ---------------- 主流程 ----------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen-sample", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument(
        "--condition",
        choices=CONDS,
        default="baseline",
        help="baseline=原文直编; zh=normalize+prepare_chinese(ctex) 后编译 (docs/spec/benchmark.md §B3)",
    )
    ap.add_argument("--corpus", type=Path, default=CORPUS_DEFAULT)
    ap.add_argument(
        "--manifest",
        type=Path,
        action="append",
        default=None,
        help="可重复; 默认 <corpus>/manifest.jsonl",
    )
    ap.add_argument("--sample-n", type=int, default=SAMPLE_N_DEFAULT)
    ap.add_argument("--seed", type=int, default=SEED_DEFAULT)
    ap.add_argument("--engines", default="xelatex,tectonic")
    ap.add_argument("--jobs", type=int, default=JOBS)
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="默认 bench/results/compilebench-v3[-zh]-<date>/",
    )
    ap.add_argument("--work", type=Path, default=WORK_DEFAULT)
    ap.add_argument("--v2-cells", type=Path, default=V2_CELLS_DEFAULT)
    args = ap.parse_args()
    # resolve 成绝对路径——相对 wdir 喂给 sandbox_wrap 时 profile 的 subpath
    # 是字面相对路径, 永不匹配真实绝对路径 → darwin 下引擎读不到输入文件
    args.corpus = args.corpus.resolve()
    args.work = args.work.resolve()
    if args.out is None:
        tag = (
            "compilebench-v3"
            if args.condition == "baseline"
            else f"compilebench-v3-{args.condition}"
        )
        args.out = ROOT / "bench/results" / f"{tag}-{time.strftime('%Y-%m-%d')}"
    args.out = args.out.resolve()
    if args.manifest is None:
        args.manifest = [args.corpus / "manifest.jsonl"]
    engines = [e.strip() for e in args.engines.split(",") if e.strip()]

    if args.gen_sample:
        gen_sample(args)
        return
    if args.report:
        report(args)
        return

    sample_path = args.out / "sample.json"
    if not sample_path.exists():
        gen_sample(args)
    sample = json.loads(sample_path.read_text())
    papers = sample["papers"]
    if args.only:
        papers = [p for p in papers if args.only in p["id"]]
    if args.limit:
        papers = papers[: args.limit]

    # 断点续跑: (paper_id, engine) 粒度——已齐的跳过, 缺引擎的补跑
    done = defaultdict(set)
    cases_path = args.out / "cases.jsonl"
    if cases_path.exists():
        for c in benchlib.iter_jsonl(cases_path):
            pid, eng = c.get("paper_id"), c.get("engine")
            if pid and eng:
                done[pid].add(eng)
    todo = [p for p in papers if set(engines) - done.get(p["id"], set())]
    print(f"{len(todo)}/{len(papers)} papers to run, jobs={args.jobs}", flush=True)

    args.work.mkdir(parents=True, exist_ok=True)
    write_run_meta(args, engines, "run")
    cells_path = args.out / "cells.json"
    papers_agg = {}
    if cells_path.exists():
        with contextlib.suppress(Exception):
            for p in json.loads(cells_path.read_text())["papers"]:
                papers_agg[p["id"]] = p

    with open(cases_path, "a") as cj, ThreadPoolExecutor(args.jobs) as ex:
        futs = {
            ex.submit(run_paper, p, args.corpus, args.work, engines, args.condition): p
            for p in todo
        }
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                paper, cases = fut.result()
            except Exception as e:
                print(f"[{p['id']}] CRASH {e}", flush=True)
                continue
            papers_agg[paper["id"]] = paper
            for c in cases:
                cj.write(json.dumps(c, ensure_ascii=False) + "\n")
            cj.flush()
            cells_path.write_text(
                json.dumps(
                    {
                        "meta": {"partial": True},
                        "papers": sorted(papers_agg.values(), key=lambda x: x["id"]),
                    },
                    ensure_ascii=False,
                    indent=1,
                )
                + "\n"
            )
            marks = " ".join(
                f"{e}={paper['engines'].get(e, {}).get('verdict', '-')}"
                for e in engines
            )
            print(f"[{paper['id']}] {marks}", flush=True)

    report(args)


if __name__ == "__main__":
    main()
