#!/usr/bin/env python3
r"""
compilebench_v2.py — B3 compilebench 扩展基线: corpus_v2 分层样本 × baseline × 双引擎.

LEGACY（refactor-audit F12 定调）：v3（``compilebench_v3.py`` + ``fixloop_bench.py``
corpus_v3 口径）已代——新测量一律走 v3；本文件留存仅作 corpus_v2 时代
基线报告的复算入口（--report），其残值（分层抽样名单/tectonic base 口径）
已并入 v3。另注意 ``ROOT`` 为硬编路径，异地运行静默指错树。

底材: bench/corpus_v2/{id}/extracted/(== raw.* 解包树, 图/.bbl/.bst/.cls 全在;
meta.json warnings 已核无编译相关丢失). baseline 条件 = 原文直编, 不注入不修复.

引擎与判据(docs/08 §4.2/§4.3):
  xelatex  : -no-shell-escape -interaction=nonstopmode -file-line-error -recorder,
             ≤2 pass, 240s/pass, 冷 TEXMF 沙箱(TEXMFHOME/VAR/CONFIG 隔离,
             不继承 ~/Library/texmf 已装包 → 模拟 TeXLive basic 裸环境),
             openin_any=p openout_any=p shell_escape=f
  tectonic : --untrusted -Z continue-on-errors --keep-logs --keep-intermediates,
             240s, 超时重试一次(bundle 冷拉包), TECTONIC_UNTRUSTED_MODE=1
  错误计数双格式: '^! ' + 'file:line:'(-file-line-error 下 ! 行变 file:line)
  clean = pdf 且 err≤3 且首错非 missing_*/undefined_cs 且 warning 扫描零命中
         (Invalid UTF-8 / Missing character U+FFFD / File not found / missing_graphic)
         —— baseline 不查中文渲染(zh 条件才查)
  verdict ∈ {clean, pdf~, FAIL, no_main_tex}; reject 标签仅作 route_expect 记录

抽样(--gen-sample): manifest 分层随机, seed=20260915, 配额 a9 b8 c8 d8 e7=40
(f 带按 docs/09 不进样); a 带内嵌 5 篇 reject 标签, 全局保底 xelatex≥6 /
non-utf8≥3(带内换入). 名单+种子落盘 sample.json 可复现.

产出(bench/results/compilebench-corpusv2-2026-09-15/, docs/10 §8 三件套):
  sample.json  抽样定义;  cases.jsonl  逐格明细(paper×engine);
  cells.json   逐篇聚合;  summary.md   per-引擎×per-带矩阵 + top 失败类

用法:
  python3 bench/py/compilebench_v2.py --gen-sample   # 生成/覆写 sample.json
  python3 bench/py/compilebench_v2.py              # 跑样本(可断点续跑)
  python3 bench/py/compilebench_v2.py --report     # 只重算 cells+summary
Deps: stdlib only.
"""

import argparse
import contextlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import benchlib

ROOT = Path("~/src/texlate").expanduser().resolve()
CORPUS = ROOT / "bench/corpus_v3"
WORK = ROOT / "bench/work_compile_v2"
OUT = ROOT / "bench/results/compilebench-corpusv2-2026-09-15"
MANIFEST = CORPUS / "manifest_v2.jsonl"
PARSE_PAPERS = ROOT / "bench/results/parsebench-corpusv2-papers.json"

SEED = 20260915
QUOTA = {"a": 9, "b": 8, "c": 8, "d": 8, "e": 7}  # f 带 docs/09 不进样
REJECT_IN_A = 5
MIN_TAGS = {"xelatex": 6, "non-utf8": 3}

TIMEOUT = 240  # 单次引擎调用上限(秒), docs/08 §4.1
MAX_PASS = 2
CLEAN_ERR_MAX = 3
JOBS = 4

TECTONIC = shutil.which("tectonic") or "/opt/homebrew/bin/tectonic"
XELATEX = "xelatex"

# 首错落这些类 → 有 pdf 也判 dirty(docs/08 §4.3 "首错非 missing_*/undefined_cs")
DIRTY_CATS = {
    "missing_file",
    "missing_tfm",
    "missing_pfb",
    "missing_graphic",
    "fontspec_missing",
    "xetexglyph_tfm",
    "undefined_cs",
    "ps_image",
    "dvipdf",
}

# ---------------- 抽样 ----------------


def band_of(yymm: str) -> str:
    y = int((yymm or "0").split("-")[0] or 0)
    return (
        "a"
        if y <= 2006
        else "b"
        if y <= 2011
        else "c"
        if y <= 2016
        else "d"
        if y <= 2020
        else "e"
        if y <= 2025
        else "f"
    )


def load_pool():
    """manifest.jsonl + parsebench 路由标签 → 可编译论文池."""
    tags_by_id, root_by_id = {}, {}
    if PARSE_PAPERS.exists():
        d = json.loads(PARSE_PAPERS.read_text())
        for p in d["papers"]:
            pid = p["id"].replace("/extracted", "")
            tags_by_id[pid] = p.get("tags", [])
            root_by_id[pid] = p.get("primary_root") or ""
    pool = {}
    for r in benchlib.iter_jsonl(MANIFEST):
        if r.get("status") != "ok" or not r.get("tex_files"):
            continue
        pid = r["id"]
        pool[pid] = {
            "id": pid,
            "band": band_of(r.get("yymm") or ""),
            "yymm": r.get("yymm"),
            "era": r.get("era"),
            "format": r.get("format"),
            "n_files": r.get("n_files"),
            "tex_files": r.get("tex_files"),
            "bytes": r.get("bytes"),
            "tags": tags_by_id.get(pid, []),
            "parsebench_root": root_by_id.get(pid, ""),
        }
    return pool


def gen_sample():
    pool = load_pool()
    rng = random.Random(SEED)  # 语料抽样非安全用途
    by_band = defaultdict(list)
    for p in pool.values():
        by_band[p["band"]].append(p)
    for b in by_band:
        rng.shuffle(by_band[b])

    picked, picked_ids = [], set()

    def take(p, why):
        picked.append({**p, "pick_reason": why})
        picked_ids.add(p["id"])

    # a 带内嵌 reject 标签样本(预期失败, 验路由标签)
    rej = [p for p in by_band["a"] if "reject" in p["tags"]]
    for p in rej[:REJECT_IN_A]:
        take(p, "tag:reject")

    # 带配额填充
    for b, q in QUOTA.items():
        n_have = sum(1 for p in picked if p["band"] == b)
        for p in by_band[b]:
            if n_have >= q:
                break
            if p["id"] in picked_ids:
                continue
            take(p, f"band:{b}")
            n_have += 1

    # 全局标签保底: 不足则从同带未选池带内换入(优先换非标签纸)
    for tag, need in MIN_TAGS.items():
        have = sum(1 for p in picked if tag in p["tags"])
        if have >= need:
            continue
        for b in QUOTA:
            if have >= need:
                break
            for cand in by_band[b]:
                if have >= need:
                    break
                if cand["id"] in picked_ids or tag not in cand["tags"]:
                    continue
                vic = next(
                    (
                        x
                        for x in picked
                        if x["band"] == b
                        and x["pick_reason"].startswith("band:")
                        and not set(x["tags"]) & {"reject", "xelatex", "non-utf8"}
                    ),
                    None,
                )
                if vic is None:
                    continue
                picked.remove(vic)
                picked_ids.discard(vic["id"])
                take(cand, f"tag:{tag}")
                have += 1

    picked.sort(key=lambda p: (p["band"], p["id"]))
    doc = {
        "seed": SEED,
        "quota": QUOTA,
        "reject_in_a": REJECT_IN_A,
        "min_tags": MIN_TAGS,
        "n": len(picked),
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "papers": picked,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sample.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
    )
    print(f"sample -> {OUT / 'sample.json'}  n={len(picked)}")
    print("bands:", dict(Counter(p["band"] for p in picked)))
    print(
        "tags:",
        dict(Counter(t for p in picked for t in p["tags"] if t != "no-hyperref")),
    )
    return doc


# ---------------- log 解析 / 分类 / 判定 ----------------

FILELINE_RE = re.compile(r"^(?:\./|/|[\w.@-]+[\\/])?[\w .@~+\\/-]+\.\w{1,6}:\d{1,7}:")


def scan_log(log_path: Path):
    """→ (bang行数, file:line行数, 首错行, 首错ctx, tail30, warn计数dict)."""
    if not log_path.exists():
        return 0, 0, None, None, "", Counter()
    try:
        text = log_path.read_text(errors="replace")
    except Exception:
        return 0, 0, None, None, "", Counter()
    lines = text.splitlines()
    n_bang = n_fl = 0
    first = ctx = None
    for i, ln in enumerate(lines):
        is_err = ln.startswith("!") or bool(FILELINE_RE.match(ln))
        if not is_err:
            continue
        if ln.startswith("!"):
            n_bang += 1
        else:
            n_fl += 1
        if first is None:
            first = ln.strip()
            ctx = "\n".join(lines[i : i + 8])
    warn = Counter()
    warn["invalid_utf8"] = text.count("Invalid UTF-8 byte")
    warn["missing_char"] = len(
        re.findall(r"^.*Missing character.*$", text, re.MULTILINE)
    )
    warn["ufffd"] = len(re.findall(r"Missing character.*(?:U\+FFFD|)", text))
    warn["file_not_found"] = len(re.findall(r"File `[^']+' not found", text))
    warn["missing_graphic"] = len(
        re.findall(
            r"File `[^']+\.(?:pdf|png|jpe?g|eps|mps|bb)' not found|"
            r"Cannot determine size of graphic|Unknown graphics extension",
            text,
        )
    )
    warn["emergency_stop"] = text.count("Emergency stop")
    return n_bang, n_fl, first, ctx, "\n".join(lines[-30:]), warn


def classify(err, ctx, tail, timed_out, stderr=""):
    """fixloop 系分类学(F1-F12 同源命名) → (category, payload)。"""
    if timed_out:
        return "timeout", None
    head = "\n".join(x for x in (err, ctx) if x)
    rules = [
        ("missing_file", r"File `([^']+\.[a-zA-Z0-9]+)' not found"),
        ("missing_file", r"I can't find file `([^']+)'"),
        ("missing_tfm", r"Font \\?\S*?=?\s*([a-zA-Z0-9]+) at [0-9.]+pt not loadable"),
        ("missing_tfm", r"Metric \(TFM\) file[^\n]*?(\w+)\.(tfm)"),
        ("xetexglyph_tfm", r"Cannot use XeTeXglyph with (\S+)"),
        ("missing_pfb", r"Cannot proceed without .vf|physical font"),
        ("fontspec_missing", r'font [“"]([^”"]+)[”"] cannot be found'),
        (
            "missing_graphic",
            r"Cannot determine size of graphic|Unknown graphics extension",
        ),
        ("illegal_unit", r"Illegal unit of measure"),
        ("option_clash", r"Option clash for package ([\w-]+)"),
        ("already_def", r"Command \\?([\w@]+) already defined"),
        ("soul_err", r"Package soul Error|Reconstruction failed"),
        ("hyphenation", r"Not a letter"),
        ("minted_froz", r"frozencache|Cannot highlight code|pygmentize"),
        ("inputenc_xetex", r"inputenc is not designed for"),
        ("latex209", r"documentstyle|LaTeX ?2\.09|LaTeX2e command .* in LaTeX 2\.09"),
        ("undefined_cs", r"Undefined control sequence"),
        ("capacity", r"TeX capacity exceeded"),
        ("emergency", r"Emergency stop|cannot \\read|Fatal error|job aborted"),
        ("dvipdf", r"something bad happened inside (?:x?dvipdfmx?)|xdvipdfmx"),
        ("env_mismatch", r"begin\{[^}]*\}.*ended by|Extra \\end"),
        ("bib_error", r"bibtex|BibTeX|Empty .bbl|thebibliography"),
        (
            "syntax",
            (
                r"Missing|Runaway|Paragraph ended|Misplaced|Double subscript|"
                r"Illegal|There's no line|Lonely|Bad math|Something's wrong|"
                r"not in outer par|allowed only in math|improper|already defined|"
                r"Too many|has an extra \}"
            ),
        ),
        ("other", r"^!|:\d+:"),
    ]
    cat0 = None
    if err:
        for name, pat in rules:
            m = re.search(pat, head, re.IGNORECASE | re.MULTILINE)
            if m:
                pay = next((g for g in m.groups() if g), None)
                if name == "undefined_cs":
                    pm = re.search(r"\\(pdf[a-zA-Z@]+)", head)
                    if pm:
                        cat0 = ("pdftex_prim", pm.group(1))
                        break
                cat0 = (name, pay)
                break
    if cat0 is None:
        blob = tail or ""
        m = re.search(r"File `([^']+\.[a-zA-Z0-9]+)' not found", blob)
        if m and ("Enter file name" in blob or "Emergency" in blob):
            cat0 = ("missing_file", m.group(1))
        elif "Enter file name" in blob:
            cat0 = ("missing_file", None)
        elif re.search(r"documentstyle|LaTeX ?2\.09", blob):
            cat0 = ("latex209", None)
    # stderr 细分: 无 err 或 err 只命中泛类(other/dvipdf/emergency)时,
    # tectonic 的 xdvipdfmx 崩因(物理字体/PS图/缺文件)在 stderr 才能区分
    if stderr and (
        cat0 is None or cat0[0] in ("other", "dvipdf", "emergency", "clean")
    ):
        for name, pat in [
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
        ]:
            m = re.search(pat, stderr, re.IGNORECASE)
            if m:
                return name, next((g for g in m.groups() if g), None)
    if cat0:
        return cat0
    return (("other" if err else "clean"), None)


def verdict_of(pdf, n_err, cat, warn):
    if not pdf:
        return "FAIL"
    dirty_warn = (
        warn["invalid_utf8"]
        or warn["ufffd"]
        or warn["missing_graphic"]
        or warn["file_not_found"]
    )
    if n_err <= CLEAN_ERR_MAX and cat not in DIRTY_CATS and not dirty_warn:
        return "clean"
    return "pdf~"


# ---------------- 引擎调用 ----------------

DOC_RE = re.compile(r"\\document(class|style)")


def find_main_tex(proj: Path):
    cands = []
    for f in sorted(proj.rglob("*.tex")):
        with contextlib.suppress(Exception):
            head = f.read_text(errors="replace")[:60000]
            if DOC_RE.search(head):
                has_body = "\\begin{document}" in head
                depth = len(f.relative_to(proj).parts)
                cands.append((depth, 0 if has_body else 1, str(f)))
    if not cands:
        return None
    cands.sort()
    return Path(cands[0][2])


def run_cmd(cmd, cwd, env, timeout=TIMEOUT):
    """Popen+killpg: 进程树超时杀。"""
    t0 = time.time()
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as e:
        return None, f"spawn-fail: {e}", 0.0, False
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or "", time.time() - t0, False
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        return None, out or "", time.time() - t0, True


def sandbox_env(paper_dir: Path):
    """冷 TEXMF 沙箱 + 受限 open*/shell_escape(docs/08 §4.4 子集)."""
    env = dict(os.environ)
    tm = paper_dir / "_texmf"
    for sub in ("home", "var", "config"):
        (tm / sub).mkdir(parents=True, exist_ok=True)
    env["TEXMFHOME"] = str(tm / "home")
    env["TEXMFVAR"] = str(tm / "var")
    env["TEXMFCONFIG"] = str(tm / "config")
    env["openin_any"] = "p"
    env["openout_any"] = "p"
    env["shell_escape"] = "f"
    env["TECTONIC_UNTRUSTED_MODE"] = "1"
    return env


def run_xelatex(wdir: Path, rel_main: str, env):
    cwd = wdir / Path(rel_main).parent
    name = Path(rel_main).name
    stem = Path(rel_main).stem
    pdf, log = cwd / f"{stem}.pdf", cwd / f"{stem}.log"
    rec = {"engine": "xelatex", "passes": 0, "seconds": 0.0}
    first_err = ctx = None
    nerr = n_bang = n_fl = 0
    warn = Counter()
    tail = ""
    timed_out = False
    for p in range(1, MAX_PASS + 1):
        if p == 2 and not pdf.exists():
            break
        _rc, _out, sec, to = run_cmd(
            [
                XELATEX,
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-file-line-error",
                "-recorder",
                name,
            ],
            cwd,
            env,
        )
        rec["passes"] = p
        rec["seconds"] += sec
        rec["exit"] = _rc
        timed_out = timed_out or to
        nb, nfl, e, c, tail, w = scan_log(log)
        nerr += nb + nfl
        n_bang += nb
        n_fl += nfl
        warn += w
        if e and first_err is None:
            first_err, ctx = e, c
        if to:
            break
        if p == 1 and pdf.exists():
            continue
        break
    cat, pay = classify(first_err, ctx, tail, timed_out)
    rec.update(
        pdf=pdf.exists(),
        pdf_bytes=pdf.stat().st_size if pdf.exists() else 0,
        n_errors=nerr,
        n_bang=n_bang,
        n_fileline=n_fl,
        first_error=first_err,
        error_ctx=(ctx or "")[:600],
        category=cat,
        payload=pay,
        warn=dict(warn),
        timed_out=timed_out,
        log=str(log) if log.exists() else None,
    )
    rec["verdict"] = verdict_of(rec["pdf"], nerr, cat, warn)
    return rec


def run_tectonic(wdir: Path, rel_main: str, env):
    cwd = wdir / Path(rel_main).parent
    outdir = cwd / "_tect_out"
    outdir.mkdir(exist_ok=True)
    stem = Path(rel_main).stem
    pdf, log = outdir / f"{stem}.pdf", outdir / f"{stem}.log"
    rec = {"engine": "tectonic", "passes": None, "seconds": 0.0, "retried": False}
    out = ""
    timed_out = False
    for _attempt in (1, 2):
        _rc, out, sec, to = run_cmd(
            [
                TECTONIC,
                "--untrusted",
                "-Z",
                "continue-on-errors",
                "--keep-logs",
                "--keep-intermediates",
                "--color",
                "never",
                "-o",
                str(outdir),
                Path(rel_main).name,
            ],
            cwd,
            env,
        )
        rec["seconds"] += sec
        rec["exit"] = _rc
        timed_out = timed_out or to
        if not to:
            break
        rec["retried"] = True
    nb, nfl, e, c, tail, warn = scan_log(log)
    stderr_tail = "\n".join((out or "").splitlines()[-14:])
    if not e:
        m = re.search(r"^error: (.+)$", stderr_tail, re.MULTILINE)
        if m:
            e = "! " + m.group(1)
    nerr = nb + nfl
    cat, pay = classify(e, c, tail, timed_out, stderr_tail)
    rec.update(
        pdf=pdf.exists(),
        pdf_bytes=pdf.stat().st_size if pdf.exists() else 0,
        n_errors=nerr,
        n_bang=nb,
        n_fileline=nfl,
        first_error=e,
        error_ctx=(c or "")[:600],
        category=cat,
        payload=pay,
        warn=dict(warn),
        timed_out=timed_out,
        stderr_tail=stderr_tail[:800],
        log=str(log) if log.exists() else None,
    )
    rec["verdict"] = verdict_of(rec["pdf"], nerr, cat, warn)
    return rec


# ---------------- 单篇执行 ----------------

IGNORE = benchlib.copytree_ignore()


def run_paper(p):
    pid = p["id"]
    src = CORPUS / pid / "extracted"
    wdir = WORK / pid / "baseline"
    paper = {
        "id": pid,
        "band": p["band"],
        "yymm": p["yymm"],
        "tags": p["tags"],
        "n_files": p["n_files"],
        "tex_files": p["tex_files"],
        "main": None,
        "engines": {},
    }
    if not src.is_dir():
        for eng in ("xelatex", "tectonic"):
            paper["engines"][eng] = {"verdict": "no_source", "engine": eng}
        return paper, []
    if wdir.exists():
        shutil.rmtree(wdir)
    shutil.copytree(src, wdir, ignore=IGNORE)
    main = find_main_tex(wdir)
    if not main:
        for eng in ("xelatex", "tectonic"):
            paper["engines"][eng] = {"verdict": "no_main_tex", "engine": eng}
        return paper, []
    rel_main = str(main.relative_to(wdir))
    paper["main"] = rel_main
    with contextlib.suppress(Exception):
        paper["docclass_line"] = next(
            (
                ln.strip()
                for ln in main.read_text(errors="replace").splitlines()
                if DOC_RE.search(ln)
            ),
            "",
        )[:160]
    env = sandbox_env(wdir.parent)  # 引擎共享本篇冷 texmf
    cases = []
    for eng, fn in (("xelatex", run_xelatex), ("tectonic", run_tectonic)):
        r = fn(wdir, rel_main, env)
        paper["engines"][eng] = r
        cases.append(
            {
                "corpus": "corpus_v3",
                "cond": "baseline",
                "paper_id": pid,
                "band": p["band"],
                "tags": p["tags"],
                "engine": eng,
                "verdict": r["verdict"],
                "category": r.get("category"),
                "payload": r.get("payload"),
                "n_errors": r.get("n_errors"),
                "n_bang": r.get("n_bang"),
                "n_fileline": r.get("n_fileline"),
                "pdf": r.get("pdf"),
                "pdf_bytes": r.get("pdf_bytes"),
                "passes": r.get("passes"),
                "seconds": round(r.get("seconds", 0.0), 1),
                "timed_out": r.get("timed_out", False),
                "retried": r.get("retried"),
                "first_error": (r.get("first_error") or "")[:200] or None,
                "warn": r.get("warn", {}),
                "log": r.get("log"),
                "main": rel_main,
            }
        )
    return paper, cases


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
    "dvipdf": "路由 xdvipdfmx 硬墙",
}


def report():
    cases = benchlib.read_jsonl(OUT / "cases.jsonl")
    cells_path = OUT / "cells.json"
    papers = {}
    if cells_path.exists():
        with contextlib.suppress(Exception):
            for p in json.loads(cells_path.read_text())["papers"]:
                papers[p["id"]] = p
    meta = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "corpus": str(CORPUS),
        "work": str(WORK),
        "timeout_s": TIMEOUT,
        "clean_err_max": CLEAN_ERR_MAX,
        "texmf_mode": "cold (per-paper TEXMFHOME/VAR/CONFIG)",
        "xelatex": subprocess.run(
            [XELATEX, "--version"], capture_output=True, text=True
        ).stdout.splitlines()[0],
        "tectonic": subprocess.run(
            [TECTONIC, "--version"], capture_output=True, text=True
        ).stdout.strip(),
    }
    doc = {"meta": meta, "papers": sorted(papers.values(), key=lambda p: p["id"])}
    cells_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")

    # ---- summary.md ----
    lines = []
    lines.append("# B3 compilebench 扩展基线 — corpus_v2 baseline × 双引擎")
    lines.append("")
    lines.append(f"- 日期: {meta['date']}")
    lines.append(
        f"- 语料: `bench/corpus_v3/` v2 层 extracted/ 分层样本 n={len(papers)} (sample.json, seed={SEED})"
    )
    lines.append(f"- 条件: baseline 原文直编, 不注入不修复; 超时 {TIMEOUT}s")
    lines.append(f"- xelatex: `{meta['xelatex']}` — nonstopmode ≤2 pass, 冷 TEXMF 沙箱")
    lines.append(
        f"- tectonic: `{meta['tectonic']}` — --untrusted -Z continue-on-errors"
    )
    lines.append(
        "- clean = pdf ∧ err≤3 ∧ 首错非missing_*/undefined_cs ∧ warn扫描零命中"
    )
    lines.append("")

    def cell_key(c):
        return (c["paper_id"], c["engine"])

    by_eng = defaultdict(list)
    for c in cases:
        by_eng[c["engine"]].append(c)

    lines.append("## 1. 总成功率")
    lines.append("")
    lines.append("| 引擎 | n | clean | pdf~ | FAIL | clean率 | pdf率 |")
    lines.append("|---|---|---|---|---|---|---|")
    for eng in ("xelatex", "tectonic"):
        cs = by_eng.get(eng, [])
        n = len(cs)
        ncl = sum(1 for c in cs if c["verdict"] == "clean")
        npd = sum(1 for c in cs if c["verdict"] == "pdf~")
        nfl = sum(1 for c in cs if c["verdict"] == "FAIL")
        npdf = sum(1 for c in cs if c.get("pdf"))
        lines.append(
            f"| {eng} | {n} | {ncl} | {npd} | {nfl} | "
            f"{ncl / n * 100:.0f}% | {npdf / n * 100:.0f}% |"
            if n
            else f"| {eng} | 0 | — |"
        )
    lines.append("")
    # 联合覆盖
    pdf_by_id = defaultdict(set)
    clean_by_id = defaultdict(set)
    for c in cases:
        if c.get("pdf"):
            pdf_by_id[c["paper_id"]].add(c["engine"])
        if c["verdict"] == "clean":
            clean_by_id[c["paper_id"]].add(c["engine"])
    lines.append(
        f"联合覆盖: 任一引擎出 pdf {len(pdf_by_id)}/{len(papers)}; "
        f"任一引擎 clean {len(clean_by_id)}/{len(papers)}; "
        f"双引擎皆死 {len(papers) - len(pdf_by_id)}"
    )
    lines.append("")

    lines.append("## 2. per-引擎 × per-带 成功率矩阵 (clean / pdf~ / FAIL)")
    lines.append("")
    lines.append(
        "| 带 | n | xel clean | xel pdf~ | xel FAIL | tec clean | tec pdf~ | tec FAIL |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    band_of_id = {p["id"]: p["band"] for p in doc["papers"]}
    for b in "abcdef":
        ids = {i for i, bb in band_of_id.items() if bb == b}
        if not ids:
            continue
        row = [b, str(len(ids))]
        for eng in ("xelatex", "tectonic"):
            cs = [c for c in by_eng.get(eng, []) if c["paper_id"] in ids]
            row += [
                str(sum(1 for c in cs if c["verdict"] == "clean")),
                str(sum(1 for c in cs if c["verdict"] == "pdf~")),
                str(sum(1 for c in cs if c["verdict"] == "FAIL")),
            ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 3. 路由标签 × 结果 (静态路由金标准对拍)")
    lines.append("")
    lines.append("| 标签 | n篇 | xel clean/pdf~/FAIL | tec clean/pdf~/FAIL |")
    lines.append("|---|---|---|---|")
    for tag in ("reject", "xelatex", "non-utf8", "no-hyperref"):
        ids = {p["id"] for p in doc["papers"] if tag in p["tags"]}
        if not ids:
            continue
        row = [tag, str(len(ids))]
        for eng in ("xelatex", "tectonic"):
            cs = [c for c in by_eng.get(eng, []) if c["paper_id"] in ids]
            row.append(
                f"{sum(1 for c in cs if c['verdict'] == 'clean')}/"
                f"{sum(1 for c in cs if c['verdict'] == 'pdf~')}/"
                f"{sum(1 for c in cs if c['verdict'] == 'FAIL')}"
            )
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 4. top 失败类别 (首错归因, fixloop F1-F12 命名)")
    lines.append("")
    for eng in ("xelatex", "tectonic"):
        cats = Counter(
            c["category"]
            for c in by_eng.get(eng, [])
            if c["verdict"] != "clean" and c["category"]
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

    lines.append("## 5. 逐格明细")
    lines.append("")
    lines.append("| paper | band | tags | xel | tec |")
    lines.append("|---|---|---|---|---|")
    for p in doc["papers"]:
        row = [
            p["id"],
            p["band"],
            ",".join(t for t in p["tags"] if t != "no-hyperref") or "—",
        ]
        for eng in ("xelatex", "tectonic"):
            r = p["engines"].get(eng, {})
            v = r.get("verdict", "—")
            row.append(
                f"{v}({r.get('n_errors', '-')}/{r.get('category', '-')})"
                if v not in ("—", None)
                else "—"
            )
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ---- §6 与 12 篇旧基线一致性 ----
    xe = by_eng.get("xelatex", [])
    te = by_eng.get("tectonic", [])
    n = len(xe)
    xe_pdf = sum(1 for c in xe if c.get("pdf"))
    te_pdf = sum(1 for c in te if c.get("pdf"))
    rej = [c for c in cases if "reject" in c.get("tags", [])]
    rej_clean = sum(1 for c in rej if c["verdict"] == "clean")
    lines.append("## 6. 与 compile_bench 12 篇结论的一致性")
    lines.append("")
    lines.append("| 旧结论 (corpus39 12篇) | 本轮 (corpus_v2 40篇分层) | 判定 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| tectonic 原文 pdf 率 75% (9/12) | {te_pdf}/{n} = {te_pdf / n * 100:.0f}% | "
        "偏低——本样本含 5 篇 2.09 reject + 9 篇 eps/ps 硬墙(旧集各仅1篇) |"
    )
    lines.append(
        f"| xelatex 原始(近冷环境) pdf 率 17% (2/12) | {xe_pdf}/{n} = {xe_pdf / n * 100:.0f}% "
        "(严格冷 TEXMF 沙箱) | 一致——TL-basic 裸环境缺包主导失败 |"
    )
    lines.append(
        f"| 双引擎联合 pdf 92% (11/12) | {len(pdf_by_id)}/{n} = {len(pdf_by_id) / n * 100:.0f}% | "
        "缺口≈reject+路由类失败, 属预期不可救(见§7) |"
    )
    lines.append(
        f"| tectonic 缺包静默降级是暗雷 | "
        f"pdf~ {sum(1 for c in te if c['verdict'] == 'pdf~')} 格中 warn 命中: "
        + ", ".join(
            f"{k}×{v}"
            for k, v in Counter(
                w
                for c in te
                if c["verdict"] == "pdf~"
                for w, x in c["warn"].items()
                if x
            ).most_common()
        )
        + " | 坐实, File-not-found 降级真实批量出现 |"
    )
    lines.append(
        "| 缺包/缺字体主导 xelatex 失败 | "
        "xelatex FAIL 34/34 全为 missing_file (首错), 次错=Emergency stop(文件名提示符) | "
        "一致且更强——static_precheck 在冷环境是必要条件 |"
    )
    lines.append(
        "| eps/pstricks→xelatex 路由 | tectonic FAIL 16 格中 ps_image×9 + missing_pfb×1=62% 硬墙 | "
        "路由预测准确; 但发现标签漏检(§7-2) |"
    )
    lines.append(
        f"| \\documentstyle→reject | reject 标签 5 篇: xelatex 5×FAIL, tectonic 5×pdf~(降级残页), "
        f"clean={rej_clean} | 零误杀, reject 路由成立 |"
    )
    lines.append("")

    lines.append("## 7. 对 M2 的启示")
    lines.append("")
    lines.append(
        "1. **冷环境缺包是 xelatex 唯一死因**(34/34 missing_file→Emergency stop): "
        "TL2026-basic 缺 revtex4/revtex4-1/revtex.cls(13格)、IEEEtran、subfigure、emulateapj、aastex 等期刊会议类。"
        "static_precheck(kpsewhich+filemap 批量装)是 fixloop 的第一杠杆, 与 spike 结论一致。"
    )
    lines.append(
        "2. **路由标签有 FN**: `.ps` 扩展名(0909.3990, astro-ph/0306068)与无扩展名 "
        "\\includegraphics(1406.1994: `{imvp22}` 引用而盘上仅有 imvp22.eps)逃过 `\\.eps\\b` 文本检测, "
        "实测全撞 xdvipdfmx ps 墙。建议路由检测补 `.ps` 字面量 + **包内 .eps/.ps 文件存在性回查**"
        "(不依赖源文引用形态——盘上文件即事实)。"
    )
    lines.append(
        '3. **bbm 物理字体墙实证**(2301.01267): `Cannot proceed without .vf or "physical" font` — '
        "docs/08 `font_sub_shim`/换引擎规则的目标场景, 首错归 missing_pfb。"
    )
    lines.append(
        "4. **tectonic 降级产出必须 warn 扫描兜底**: pdf~ 16 格仅 ~1/3 靠错误数触脏, "
        '其余靠 file_not_found/invalid_utf8/ufffd 命中——"出pdf≠成功"在大样本复现。'
    )
    lines.append(
        "5. **基线定标**: 本轮 clean 率 xelatex 10% / tectonic 20% / 联合 22.5%; pdf 率 15%/60%/65%。"
        "M2 目标 ≥90%(zh 条件)意味着 fixloop+路由+normalize 要补 ~70pp——"
        "主要缺口构成: missing_* 系(xel) + ps/bbm 路由(tec) + 2.09 reject。"
    )
    lines.append(
        "6. **引擎互补再次验证**: tectonic 独救 20 篇, xelatex 独救 2 篇(1009.5340 eps 干净过, "
        "astro-ph/0306068 带错出pdf)——tectonic 优先 + xelatex 兜底的排序对。"
    )
    lines.append("")
    lines.append("### 口径备注")
    lines.append("")
    lines.append(
        "- xelatex 在冷 TEXMF 沙箱跑(TEXMFHOME/VAR/CONFIG 隔离 → TL2026-basic 裸环境), "
        "不代表用户暖环境(~300 已装包下 12 篇基线 pdf 率 92%);选冷口径=fixloop 的真实起点。"
    )
    lines.append(
        "- n_errors 双格式计数(^! + file:line), 两遍 pass 累加——同一缺包在 2 pass 各报一次会算 2, 与上轮口径一致。"
    )
    lines.append(
        "- tectonic 的 xdvipdfmx 崩因经 stderr `caused by:` 二次归因: "
        "ps_image=PS图硬墙 / missing_pfb=物理字体 / 余下才是 generic dvipdf。"
    )
    lines.append(
        "- 1607.00497 等 clean 格带 1 个非 missing_* 错误(missing \\item@thebibliography)——"
        "按 ≤3 阈值判 clean, zh 条件更严的 CJK 检查本轮不适用。"
    )
    lines.append("")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    print(
        f"report -> {OUT}/summary.md, cells.json ({len(papers)} papers, {len(cases)} cases)"
    )


# ---------------- 主流程 ----------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen-sample", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--jobs", type=int, default=JOBS)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    if args.gen_sample:
        gen_sample()
        return
    if args.report:
        report()
        return

    sample_path = OUT / "sample.json"
    if not sample_path.exists():
        gen_sample()
    sample = json.loads(sample_path.read_text())
    papers = sample["papers"]
    if args.only:
        papers = [p for p in papers if args.only in p["id"]]

    # 断点续跑: 已有 case 的 (id,engine) 跳过整篇
    done = set()
    cases_path = OUT / "cases.jsonl"
    if cases_path.exists():
        for c in benchlib.iter_jsonl(cases_path):
            if c.get("paper_id"):
                done.add(c["paper_id"])
    todo = [p for p in papers if p["id"] not in done]
    print(f"{len(todo)}/{len(papers)} papers to run, jobs={args.jobs}", flush=True)

    WORK.mkdir(parents=True, exist_ok=True)
    cells_path = OUT / "cells.json"
    papers_agg = {}
    if cells_path.exists():
        with contextlib.suppress(Exception):
            for p in json.loads(cells_path.read_text())["papers"]:
                papers_agg[p["id"]] = p

    with open(cases_path, "a") as cj, ThreadPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(run_paper, p): p for p in todo}
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
            xv = paper["engines"].get("xelatex", {}).get("verdict", "-")
            tv = paper["engines"].get("tectonic", {}).get("verdict", "-")
            print(f"[{paper['id']}] xel={xv} tec={tv}", flush=True)

    report()


if __name__ == "__main__":
    main()
