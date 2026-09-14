#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
compile_bench.py — 真实 arXiv 源码注入 ctex 后重编译成功率 benchmark.

对每个 corpus 项目跑 3 个条件 x 2 引擎:
  baseline : 原文直接编译
  ctex     : \documentclass 行后注入 \usepackage[fontset=fandol,UTF8]{ctex}
  zh       : 所有 .tex 英文段落替换为中文占位 + 注入 ctex (模拟翻译后)

引擎:
  tectonic : tectonic -Z continue-on-errors --keep-logs  (≈ nonstopmode 语义)
  xelatex  : xelatex -interaction=nonstopmode, 最多 2 pass (参考文献/目录)

产出:
  bench/results/compile-bench.json   全部原始数据
  stdout                             进度 + 汇总矩阵
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CORPUS = Path(os.path.expanduser("~/src/texlate/bench/corpus")).resolve()
WORK = Path(os.path.expanduser("~/src/texlate/bench/work_compile")).resolve()
RESULTS = Path(os.path.expanduser("~/src/texlate/bench/results")).resolve()
TIMEOUT = 120  # 每次引擎调用上限(秒)
TECTONIC = "/opt/homebrew/bin/tectonic"
XELATEX = "xelatex"

CTEX_LINE = r"\usepackage[fontset=fandol,UTF8]{ctex}"
ZH_SENT = "这是一个翻译后的中文段落。它包含足够的字符来模拟真实翻译长度。"

# ---------------- 主文件定位 ----------------

DOC_RE = re.compile(r"\\document(class|style)")


def find_main_tex(proj: Path):
    r"""找含 \documentclass/\documentstyle 且含 \begin{document} 的最浅 .tex"""
    cands = []
    for f in sorted(proj.rglob("*.tex")):
        try:
            head = f.read_text(errors="replace")[:60000]
        except Exception:
            continue
        if DOC_RE.search(head):
            has_body = "\\begin{document}" in head
            depth = len(f.relative_to(proj).parts)
            cands.append((depth, 0 if has_body else 1, str(f)))
    if not cands:
        return None
    cands.sort()
    return Path(cands[0][2])


def doc_class_line(main: Path):
    for ln in main.read_text(errors="replace").splitlines():
        if DOC_RE.search(ln):
            return ln.strip()
    return ""


# ---------------- 条件 b: 注入 ctex ----------------

CJK_RE = re.compile(r"ctex|xeCJK|CJKutf8|CJKfontspec")


def inject_ctex(main: Path):
    r"""在 \documentclass/\documentstyle 行后插入 ctex 行。返回 'injected'|'already'"""
    txt = main.read_text(encoding="utf-8", errors="replace")
    if CJK_RE.search(txt):
        return "already"
    lines = txt.splitlines()
    for i, ln in enumerate(lines):
        if DOC_RE.search(ln):
            lines.insert(i + 1, CTEX_LINE + "  % [compile-bench injected]")
            main.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return "injected"
    return "no-docline"


# ---------------- 条件 c: 模拟翻译 ----------------

# 逐字复制环境: 内部不替换 (注释/代码/列表)
VERB_ENVS = (
    "verbatim",
    "verbatim*",
    "lstlisting",
    "minted",
    "Verbatim",
    "comment",
    "alltt",
    "filecontents",
    "filecontents*",
)

# 英文散文 run: 字母开头, 允许字母数字和常见标点/空格; 长度>=26 且 >=2 空格才算散文
RUN_RE = re.compile(
    "[A-Za-z][A-Za-z0-9.,;:'\"!?()\u2018\u2019\u201c\u201d\u2013\u2014 \\-]*"
)
MIN_LEN, MIN_SPACES = 26, 2

MATH_SPAN_RE = re.compile(
    r"\$\$.*?\$\$|\$[^$\n]*\$|\\\(.{0,200}?\\\)|\\\[.{0,200}?\\\]|"
    r"\\verb\*?(.).*?\1"
)


def _unescaped_pct(line: str) -> int:
    """返回首个未被反斜杠转义的 % 下标; 无则 -1"""
    for m in re.finditer(r"%", line):
        i = m.start()
        bs = 0
        j = i - 1
        while j >= 0 and line[j] == "\\":
            bs += 1
            j -= 1
        if bs % 2 == 0:
            return i
    return -1


def translate_line(line: str) -> str:
    ci = _unescaped_pct(line)
    code, comment = (line, "") if ci < 0 else (line[:ci], line[ci:])
    if not code.strip():
        return line
    # 保护区间: 数学/\verb
    protected = [m.span() for m in MATH_SPAN_RE.finditer(code)]

    def in_protected(s, e):
        return any(s < pe and e > ps for ps, pe in protected)

    out = []
    last = 0
    for m in RUN_RE.finditer(code):
        s, e = m.span()
        run = m.group()
        if len(run) < MIN_LEN or run.count(" ") < MIN_SPACES:
            continue
        if s > 0 and code[s - 1] == "\\":  # \cmd 后紧跟的文字 → 命令名会被吃掉, 跳过
            continue
        if in_protected(s, e):
            continue
        out.append(code[last:s])
        out.append(ZH_SENT)
        last = e
    if not out:
        return line
    out.append(code[last:])
    return "".join(out) + comment


def mock_translate(proj: Path):
    n_files, n_lines = 0, 0
    begin_re = re.compile(
        r"\\begin\{(" + "|".join(re.escape(v) for v in VERB_ENVS) + r")\}"
    )
    end_re = re.compile(r"\\end\{(.*?)\}")
    for f in sorted(proj.rglob("*.tex")):
        verb_on = None
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        new_lines = []
        for ln in txt.splitlines():
            if verb_on:
                new_lines.append(ln)
                em = end_re.search(ln)
                if em and em.group(1) == verb_on:
                    verb_on = None
                continue
            bm = begin_re.search(ln)
            if bm:
                verb_on = bm.group(1)
                new_lines.append(ln)
                continue
            nl = translate_line(ln)
            if nl != ln:
                n_lines += 1
            new_lines.append(nl)
        f.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        n_files += 1
    return n_files, n_lines


# ---------------- 编译 ----------------


def _first_error_from_log(log_path: Path):
    """返回 (首个'!'行, 其后的 l.NNN 上下文行, '!'行总数)"""
    if not log_path.exists():
        return None, None, 0
    try:
        lines = log_path.read_text(errors="replace").splitlines()
    except Exception:
        return None, None, 0
    first, ctx, nerr = None, None, 0
    for i, ln in enumerate(lines):
        if ln.startswith("!"):
            nerr += 1
            if first is None:
                first = ln.strip()
                for j in range(i + 1, min(i + 4, len(lines))):
                    if re.match(r"^l\.\d+", lines[j].strip()) or re.match(
                        r"^l\.\d+", lines[j]
                    ):
                        ctx = lines[j].strip()
                        break
                    if lines[j].strip().startswith("l."):
                        ctx = lines[j].strip()
                        break
    return first, ctx, nerr


def classify(err: str, ctx: str, timed_out: bool, stderr: str = ""):
    """失败分类学. err/ctx 是首个'!'行及其上下文; stderr 仅作兜底(无'!'行时)."""
    head = " ".join(x for x in (err, ctx) if x)
    if timed_out:
        return "timeout", None
    # —— 优先在错误行本身匹配 ——
    RULES = [
        ("capacity", r"TeX capacity exceeded|main memory size|pool size|save size"),
        ("missing_class", r"File `([^']+\.cls)' not found"),
        ("missing_package", r"File `([^']+\.sty)' not found"),
        (
            "missing_font",
            r"Font [^\n]{0,80}?not loadable|Metric \(TFM\) file|"
            r"Cannot use XeTeXglyph with (\S+)|"
            r"fontspec[^']*?(?:not found|cannot)|"
            r"Cannot proceed without \.vf|physical font|"
            r"Cannot find font|Font .* not found",
        ),
        (
            "missing_graphic",
            r"File `([^']+\.(?:pdf|png|jpg|jpeg|eps|mps|bb))' not found|Cannot determine size of graphic|Unknown graphics extension",
        ),
        ("missing_file", r"File `([^']+)' not found|I can't find file `([^']+)'"),
        ("option_clash", r"Option clash for package ([^ .\n]+)"),
        ("minted", r"minted|pygmentize|highlighting style"),
        ("soul_cjk", r"Package soul Error|Reconstruction failed"),
        ("latex209", r"LaTeX2e command .* in LaTeX 2\.09|documentstyle|ptptex"),
        (
            "pdftex_prim",
            r"\\pdf(output|minorversion|compresslevel|info|pagewidth|pageheight)|pdfTeX",
        ),
        ("hyphenation", r"Not a letter|hyphenation"),
        (
            "env_mismatch",
            r"begin\{[^}]*\}.*ended by|Environment [^ \n]+ undefined|Extra \\end",
        ),
        ("undefined_cs", r"Undefined control sequence"),
        (
            "syntax",
            r"Missing \\?[$}{]|Missing \\?\\?endcsname|Extra }|Runaway argument|Paragraph ended before|Misplaced|Double subscript|Improper|There's no line|Lonely \\item|Bad math|Missing \\begin\{document\}|Something's wrong|Illegal unit of measure|not in outer par|allowed only in math|Missing delimiter|Missing number|already defined|Missing \\. inserted",
        ),
        (
            "bib_error",
            r"bibtex|BibTeX|Citation .* undefined|Empty .bbl|thebibliography",
        ),
        (
            "engine_halt",
            r"unrecoverable error|halted on|Emergency stop|Fatal error|job aborted",
        ),
    ]
    for name, pat in RULES:
        m = re.search(pat, head, re.I)
        if m:
            pkg = next((g for g in m.groups() if g), None)
            return name, pkg
    # —— 错误行为空时退到 stderr (tectonic 无 .log 的崩溃) ——
    blob = (stderr or "")[:4000]
    for name, pat in [
        (
            "missing_font",
            r"Cannot proceed without \.vf|physical font|"
            r"Cannot find font|Font .* not found",
        ),
        ("dvipdf", r"xdvipdfmx|dvipdfmx"),
        (
            "engine_halt",
            r"unrecoverable error|halted on|Emergency stop|"
            r"Fatal error|job aborted|cannot \read",
        ),
        ("missing_file", r"File `([^']+)' not found|I can't find file"),
    ]:
        m = re.search(pat, blob, re.I)
        if m:
            pkg = next((g for g in m.groups() if g), None)
            return name, pkg
    if err:
        return "other", None
    return None, None


def run_cmd(cmd, cwd, timeout=TIMEOUT):
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            timeout=timeout,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        return p.returncode, p.stdout, time.time() - t0, False
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return None, out, time.time() - t0, True


def run_xelatex(work: Path, rel_main: str):
    """最多 2 pass; 第一 pass 无 pdf 则不重跑"""
    cwd = work / Path(rel_main).parent
    name = Path(rel_main).name
    stem = Path(rel_main).stem
    pdf = cwd / f"{stem}.pdf"
    log = cwd / f"{stem}.log"
    rec = {"engine": "xelatex", "passes": 0, "seconds": 0.0}
    first_err = ctx = None
    nerr = 0
    for p in range(1, 3):
        if p == 2 and not pdf.exists():
            break
        rc, out, sec, to = run_cmd([XELATEX, "-interaction=nonstopmode", name], cwd)
        rec["passes"] = p
        rec["seconds"] += sec
        rec["exit"] = rc
        rec["timed_out"] = to
        e, c, n = _first_error_from_log(log)
        if e and first_err is None:
            first_err, ctx = e, c
        nerr += n
        if to:
            break
        if p == 1 and pdf.exists():
            continue  # 需要第二遍解析 \ref/.bbl/toc
        break
    rec["pdf"] = pdf.exists()
    rec["pdf_bytes"] = pdf.stat().st_size if pdf.exists() else 0
    rec["clean"] = rec["pdf"] and nerr == 0
    rec["n_errors"] = nerr
    rec["first_error"] = first_err
    rec["error_ctx"] = ctx
    cat, pkg = classify(first_err, ctx, rec.get("timed_out", False))
    rec["category"], rec["pkg"] = cat, pkg
    rec["log"] = str(log) if log.exists() else None
    return rec


def run_tectonic(work: Path, rel_main: str):
    cwd = work / Path(rel_main).parent
    outdir = cwd / "_tect_out"
    outdir.mkdir(exist_ok=True)
    stem = Path(rel_main).stem
    pdf = outdir / f"{stem}.pdf"
    log = outdir / f"{stem}.log"
    rec = {"engine": "tectonic", "passes": None, "seconds": 0.0, "retried": False}
    for attempt in (1, 2):
        rc, out, sec, to = run_cmd(
            [
                TECTONIC,
                "-Z",
                "continue-on-errors",
                "--keep-logs",
                "--color",
                "never",
                "-o",
                str(outdir),
                Path(rel_main).name,
            ],
            cwd,
        )
        rec["seconds"] += sec
        rec["exit"] = rc
        rec["timed_out"] = to
        rec["stderr_tail"] = "\n".join(out.splitlines()[-8:])
        if not to:
            break
        rec["retried"] = True  # 首次 bundle 拉包可能超时, 缓存后重试一次
    e, c, n = _first_error_from_log(log)
    if not e:
        # tectonic 有时不产 .log 就崩了 (e.g. \documentstyle), 从 stderr 找
        m = re.search(r"^error: (.+)$", rec.get("stderr_tail", ""), re.M)
        if m:
            e = "! " + m.group(1)
    rec["pdf"] = pdf.exists()
    rec["pdf_bytes"] = pdf.stat().st_size if pdf.exists() else 0
    rec["clean"] = rec["pdf"] and n == 0
    rec["n_errors"] = n
    rec["first_error"] = e
    rec["error_ctx"] = c
    cat, pkg = classify(e, c, rec.get("timed_out", False), rec.get("stderr_tail", ""))
    rec["category"], rec["pkg"] = cat, pkg
    rec["log"] = str(log) if log.exists() else None
    return rec


# ---------------- 主流程 ----------------


def prep_copy(proj_src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    # 注意: *.pdf 不能忽略 —— 项目自带图片就是 pdf
    shutil.copytree(
        proj_src,
        dst,
        ignore=shutil.ignore_patterns(
            "_tect_out",
            "*.aux",
            "*.log",
            "*.out",
            "*.toc",
            "*.synctex*",
            "*.fls",
            "*.fdb_latexmk",
            ".DS_Store",
            "texput.*",
        ),
    )


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    RESULTS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    projects = sorted([d for d in CORPUS.iterdir() if d.is_dir()])
    if only:
        projects = [d for d in projects if only in d.name]
    out = {
        "meta": {
            "date": time.strftime("%Y-%m-%d %H:%M"),
            "timeout_s": TIMEOUT,
            "tectonic": subprocess.run(
                [TECTONIC, "--version"], capture_output=True, text=True
            ).stdout.strip(),
            "xelatex": subprocess.run(
                [XELATEX, "--version"], capture_output=True, text=True
            ).stdout.splitlines()[0],
            "ctex_line": CTEX_LINE,
            "zh_sent": ZH_SENT,
            "corpus": str(CORPUS),
        },
        "projects": {},
    }
    json_path = RESULTS / "compile-bench.json"

    for proj in projects:
        name = proj.name
        main_src = find_main_tex(proj)
        if not main_src:
            print(f"[{name}] !! no main tex", flush=True)
            continue
        rel_main = str(main_src.relative_to(proj))
        n_tex = len(list(proj.rglob("*.tex")))
        print(f"[{name}] main={rel_main} ({n_tex} tex)", flush=True)
        prec = {
            "main": rel_main,
            "class": doc_class_line(main_src),
            "n_tex": n_tex,
            "runs": {},
        }
        for cond in ("baseline", "ctex", "zh"):
            wdir = WORK / name / cond
            prep_copy(proj, wdir)
            mw = wdir / rel_main
            inj = "-"
            nzh = None
            if cond == "ctex":
                inj = inject_ctex(mw)
            elif cond == "zh":
                nzh = mock_translate(wdir)
                inj = inject_ctex(mw)
            crec = {"injected": inj}
            if nzh is not None:
                crec["zh_files"], crec["zh_lines"] = nzh
            for eng, fn in (("tectonic", run_tectonic), ("xelatex", run_xelatex)):
                t0 = time.time()
                r = fn(wdir, rel_main)
                tag = "OK " if r["pdf"] else "FAIL"
                print(
                    f"  {cond:8s} {eng:8s} {tag} "
                    f"clean={r['clean']} err={r['n_errors']} "
                    f"cat={r['category']} {r['seconds']:.1f}s"
                    + (f" | {r['first_error']}" if r["first_error"] else ""),
                    flush=True,
                )
                crec[eng] = r
            prec["runs"][cond] = crec
        out["projects"][name] = prec
        json_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
        print(f"[{name}] done", flush=True)

    # ---- 汇总矩阵 ----
    print("\n==== MATRIX (pdf produced / clean) ====")
    print(
        f"{'project':14s} "
        + " ".join(
            f"{c[:4]}-{e[:4]:4s}"
            for c in ("baseline", "ctex", "zh")
            for e in ("tect", "xel")
        )
    )
    for name, p in out["projects"].items():
        cells = []
        for c in ("baseline", "ctex", "zh"):
            for e in ("tectonic", "xelatex"):
                r = p["runs"].get(c, {}).get(e)
                if not r:
                    cells.append("   -   ")
                elif r["pdf"] and r["clean"]:
                    cells.append("  PDF+   ")
                elif r["pdf"]:
                    cells.append("  pdf~   ")
                else:
                    cells.append("  FAIL   ")
        print(f"{name:14s} " + " ".join(cells))
    print(f"\njson -> {json_path}")


if __name__ == "__main__":
    main()
