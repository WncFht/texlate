#!/usr/bin/env python3
r"""
fixloop.py — LaTeX 编译自动修复循环 spike.

循环: 编译(xelatex nonstopmode) → 解析 .log 首个 '!' 错误 → 分类 →
规则表匹配 → 应用修复(改 .tex/.sty 或 tlmgr --usermode 装包) → 重编译,
最多 MAX_ROUNDS 轮。每轮动作全记录, 用于量化"规则化修复能救回多少编译失败"。

用法:
  python3 fixloop.py                          # 12 项目 × 3 条件, 全冷 TEXMFHOME
  python3 fixloop.py --conds baseline         # 只跑 baseline
  python3 fixloop.py --projects 1810 2501     # 只跑匹配的项目
  python3 fixloop.py --texmf warm             # 不隔离(用 ~/Library/texmf 现状)
  python3 fixloop.py --no-precheck            # 关掉"静态预检装包"(对照)

环境约定(冷启动测量): 每格独立沙箱 TEXMFHOME/TEXMFVAR/TEXMFCONFIG,
不继承 ~/Library/texmf 里已装的 300+ 包 —— 复现 basic TeXLive 裸环境。
tlmgr search 结果(file->pkg)全局缓存, 因为远端仓库知识与环境冷热无关。
"""

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

BENCH = Path(os.path.expanduser("~/src/texlate/bench")).resolve()
WORK = BENCH / "work_compile"
RESULTS = BENCH / "results"
FIXWORK = BENCH / "work_fixloop"
JSON_OUT = RESULTS / "fixloop-results.json"
SEARCH_CACHE = RESULTS / "fixloop-tlmgr-search-cache.json"

XELATEX = "xelatex"
TIMEOUT = 120
MAX_ROUNDS = 8
CLEAN_ERR_MAX = 3  # "干净"阈值: pdf 且 '!' 错误 <= 3

# =====================================================================
# 1. log 解析器
# =====================================================================


def first_error(log_path: Path):
    """返回 (首个'!'行, 其后≤8行上下文 blob, '!'行总数, 全文tail)。"""
    if not log_path.exists():
        return None, None, 0, ""
    try:
        lines = log_path.read_text(errors="replace").splitlines()
    except Exception:
        return None, None, 0, ""
    first, ctx, nerr = None, None, 0
    for i, ln in enumerate(lines):
        if ln.startswith("!"):
            nerr += 1
            if first is None:
                first = ln.strip()
                ctx = "\n".join(lines[i : i + 8])
    tail = "\n".join(lines[-30:])
    return first, ctx, nerr, tail


def classify(err, ctx, tail, timed_out):
    """失败分类学 → (category, payload)。payload 供规则定位(文件名/字体名/cs名)。"""
    if timed_out:
        return "timeout", None
    head = "\n".join(x for x in (err, ctx) if x)
    rules = [
        # —— 文件缺失类: 统一抓文件名, 走 tlmgr search --file ——
        ("missing_file", r"File `([^']+\.[a-zA-Z0-9]+)' not found"),
        ("missing_file", r"I can't find file `([^']+)'"),
        # —— TFM 字体: 抓字体名(=文件名) ——
        ("missing_tfm", r"Font \\?\S*?=?\s*([a-zA-Z0-9]+) at [0-9.]+pt not loadable"),
        ("missing_tfm", r"Metric \(TFM\) file[^\n]*?(\w+)\.(tfm)"),
        # —— fontspec 时代错配 ——
        ("xetexglyph_tfm", r"Cannot use XeTeXglyph with (\S+)"),
        ("missing_pfb", r"Cannot proceed without .vf|physical font"),
        ("fontspec_missing", r'font [“"]([^”"]+)[”"] cannot be found'),
        # —— 源码级 ——
        ("illegal_unit", r"Illegal unit of measure"),
        ("option_clash", r"Option clash for package ([\w-]+)"),
        ("already_def", r"Command \\?([\w@]+) already defined"),
        ("soul_err", r"Package soul Error|Reconstruction failed"),
        ("hyphenation", r"Not a letter"),
        ("minted_froz", r"frozencache|Cannot highlight code"),
        ("latex209", r"documentstyle|LaTeX ?2\.09|LaTeX2e command .* in LaTeX 2\.09"),
        ("undefined_cs", r"Undefined control sequence"),
        ("capacity", r"TeX capacity exceeded"),
        ("emergency", r"Emergency stop|cannot \\read|Fatal error|job aborted"),
        ("env_mismatch", r"begin\{[^}]*\}.*ended by|Extra \\end"),
        (
            "syntax",
            (
                r"Missing|Runaway|Paragraph ended|Misplaced|Double subscript|"
                r"Illegal|There's no line|Lonely|Bad math|Something's wrong|"
                r"not in outer par|allowed only in math|improper"
            ),
        ),
        ("other", r"^!"),
    ]
    if err:
        for name, pat in rules:
            m = re.search(pat, head, re.IGNORECASE)
            if m:
                pay = next((g for g in m.groups() if g), None)
                # undefined_cs 里再细分 pdfTeX 原语
                if name == "undefined_cs":
                    pm = re.search(r"\\(pdf[a-zA-Z@]+)", head)
                    if pm:
                        return "pdftex_prim", pm.group(1)
                return name, pay
    # —— 无 '!' 行或首错是 emergency: 回溯找文件名提示符 ——
    blob = tail or ""
    m = re.search(r"File `([^']+\.[a-zA-Z0-9]+)' not found", blob)
    if m and ("Enter file name" in blob or "Emergency" in blob):
        return "missing_file", m.group(1)
    if "Enter file name" in blob:
        return "missing_file", None
    if re.search(r"documentstyle|LaTeX ?2\.09", blob):
        return "latex209", None
    return ("other" if err else "clean"), None


# =====================================================================
# 2. 修复动作原语
# =====================================================================


class Ctx:
    """每格运行上下文: 工作目录、沙箱texmf、已应用规则、tlmgr缓存。"""

    def __init__(self, wdir, main_rel, env, log):
        self.wdir = wdir
        self.main_rel = main_rel
        self.env = env  # 子进程 env(含 TEXMF* 沙箱)
        self.log = log  # 事件记录 list
        self.applied = set()  # (rule_id, key) 防重复
        self.installed_pkgs = []  # 本格装过的包
        self.search_cache = _load_cache()

    def tex_files(self):
        return [
            p
            for p in self.wdir.rglob("*")
            if p.suffix in (".tex", ".sty", ".cls") and p.is_file()
        ]

    def run(self, cmd, timeout=TIMEOUT, cwd=None):
        t0 = time.time()
        try:
            p = subprocess.run(
                cmd,
                cwd=str(cwd or self.wdir),
                env=self.env,
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

    def kpsewhich(self, fname):
        rc, out, _, _ = self.run(["kpsewhich", fname], timeout=15)
        return out.strip() if rc == 0 else ""

    def tlmgr_search_file(self, fname):
        """file→TL包名, 全局缓存(远端仓库知识, 与环境无关)。"""
        key = "/" + fname
        if key in self.search_cache:
            return self.search_cache[key]
        _rc, out, _, to = self.run(
            ["tlmgr", "search", "--global", "--file", key], timeout=60
        )
        pkgs = []
        if not to:
            for ln in out.splitlines():
                m = re.match(r"^([\w.-]+):$", ln.strip())
                if m:
                    p = m.group(1)
                    # 滤掉平台特定条目(tlgs.windows 等)与 tlmgr 自身输出
                    if "." in p and p.split(".")[-1] in (
                        "windows",
                        "win32",
                        "macosx",
                        "linux",
                        "x86_64",
                        "aarch64",
                        "amd64",
                        "i386",
                        "universal",
                    ):
                        continue
                    if p.startswith(("tlmgr", "tlgs")):
                        continue
                    pkgs.append(p)
        self.search_cache[key] = pkgs
        _save_cache(self.search_cache)
        return pkgs

    def tlmgr_install(self, pkgs, font_related=False):
        if not pkgs:
            return False, "no-pkg-found"
        # 冷 TEXMFHOME: 首次装包前必须建 usertree tlpdb,
        # 否则 --usermode 任何动作都报 "Cannot determine type of tlpdb"
        home = self.env.get("TEXMFHOME")
        if home and not (Path(home) / "tlpkg" / "texlive.tlpdb").exists():
            self.run(["tlmgr", "--usermode", "init-usertree"], timeout=60)
            self.log.append("    tlmgr init-usertree")
        rc, out, _, to = self.run(
            ["tlmgr", "--usermode", "install", *pkgs], timeout=180
        )
        ok = rc == 0 and not to
        self.log.append(
            f"    tlmgr install {' '.join(pkgs)} -> rc={rc} {'TIMEOUT' if to else ''}"
        )
        if ok:
            self.installed_pkgs.extend(pkgs)
            if font_related:
                self.run(["updmap-user"], timeout=120)
                self.log.append("    updmap-user 重建字体 map")
        return ok, out[-400:] if not ok else ""


def _load_cache():
    if SEARCH_CACHE.exists():
        with contextlib.suppress(Exception):
            return json.loads(SEARCH_CACHE.read_text())
    return {}


def _save_cache(c):
    SEARCH_CACHE.write_text(json.dumps(c, indent=0, sort_keys=True))


def patch_files(ctx, regex, repl, exts=(".tex", ".sty")):
    """对格内所有源码文件做正则替换; 返回改动文件数。"""
    n = 0
    pat = re.compile(regex)
    for f in ctx.tex_files():
        if f.suffix not in exts:
            continue
        t = None
        with contextlib.suppress(Exception):
            t = f.read_text(encoding="utf-8", errors="replace")
        if t is None:
            continue
        nt = pat.sub(repl, t)
        if nt != t:
            f.write_text(nt, encoding="utf-8")
            n += 1
    return n


def install_missing_file(ctx, fname, font_related=False):
    """kpsewhich 验证 → 缺则 tlmgr search+install。返回 (ok, note)。"""
    if not fname:
        return False, "no-filename"
    if ctx.kpsewhich(fname):
        return True, "already-present"
    pkgs = ctx.tlmgr_search_file(fname)
    if not pkgs:
        return False, f"tlmgr: no package provides {fname}"
    ok, note = ctx.tlmgr_install(pkgs, font_related=font_related)
    if ok and not ctx.kpsewhich(fname):
        return False, f"installed {pkgs} but {fname} still not found"
    return ok, note


# =====================================================================
# 3. 规则表 — (id, 何时适用, 做什么)
#    每条返回 (applied, note); applied=False 表示该规则放弃, 试下一条
# =====================================================================

PDFTEX_PRIMS = (
    "pdfoutput",
    "pdfminorversion",
    "pdfcompresslevel",
    "pdfinfo",
    "pdfpagewidth",
    "pdfpageheight",
    "pdfhorigin",
    "pdfvorigin",
    "pdfsuppressptexinfo",
    "pdftrailer",
    "pdfpxdimen",
    "pdflastxpos",
    "pdflastypos",
)


def r_install_file(ctx, cat, pay, **_):
    """missing_file/missing_package/missing_class → tlmgr search --file → install"""
    if cat != "missing_file":
        return False, ""
    fname = pay or ""
    ok, note = install_missing_file(
        ctx, fname, font_related=bool(re.search(r"\.(tfm|pfb|vf|fd|map|enc)$", fname))
    )
    if not ok:
        return False, note
    return True, f"install for {fname}"


def r_install_tfm(ctx, cat, pay, **_):
    """missing_tfm (Font X not loadable) → 装 {font}.tfm 所在包 + updmap"""
    if cat != "missing_tfm" or not pay:
        return False, ""
    ok, note = install_missing_file(ctx, f"{pay}.tfm", font_related=True)
    if not ok:
        return False, note
    return True, f"install tfm-font {pay}"


def r_install_sysfont(ctx, cat, pay, **_):
    """fontspec 'The font X cannot be found' → 按 {X}.otf/.ttf 搜包装"""
    if cat != "fontspec_missing" or not pay:
        return False, ""
    for ext in (".otf", ".ttf", ".ttc"):
        ok, _note = install_missing_file(ctx, pay + ext, font_related=True)
        if ok:
            return True, f"install font {pay}{ext}"
    return False, f"no TL package ships {pay}.(otf|ttf)"


def r_missing_pfb(ctx, cat, pay, **_):
    """xdvipdfmx 物理字体缺失 → updmap-user 重建 map; 已做过则放弃"""
    if cat != "missing_pfb":
        return False, ""
    rc, _out, _, _ = ctx.run(["updmap-user"], timeout=120)
    ctx.log.append(f"    updmap-user rc={rc}")
    return True, "updmap-user rebuild"


def r_pdftex_prim(ctx, cat, pay, **_):
    """pdfTeX 原语裸用 → \\ifdefined 守卫。
    \\pdfX=val → \\ifdefined\\pdfX\\pdfX=val\\fi ; {..} 形同理。
    (?<!ifdefined) 防止把已守卫的再套一层。"""
    if cat != "pdftex_prim":
        return False, ""
    prims = "|".join(PDFTEX_PRIMS)
    assign = re.compile(r"(?<!ifdefined)(\\(" + prims + r"))(\s*=\s*[^\n%]*)")
    brace = re.compile(r"(?<!ifdefined)(\\(" + prims + r"))(\s*\{[^\n]*\})")
    n = 0
    for f in ctx.tex_files():
        t = f.read_text(encoding="utf-8", errors="replace")
        nt = assign.sub(lambda m: f"\\ifdefined{m.group(1)}{m.group(0)}\\fi", t)
        nt = brace.sub(lambda m: f"\\ifdefined{m.group(1)}{m.group(0)}\\fi", nt)
        if nt != t:
            f.write_text(nt, encoding="utf-8")
            n += 1
    return (n > 0), f"guard pdfTeX prims in {n} files"


def r_px_to_bp(ctx, cat, pay, **_):
    """非法单位 px → bp 换算 (CSS 96dpi: 1px = 0.75bp)"""
    if cat != "illegal_unit":
        return False, ""

    def cvt(m):
        v = float(m.group(1)) * 0.75
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return s + "bp"

    n = patch_files(ctx, r"(\d*\.?\d+)\s*px\b", cvt, exts=(".tex", ".sty"))
    return (n > 0), f"px->bp in {n} files"


def r_microtype_off(ctx, cat, pay, **_):
    """XeTeXglyph×TFM: microtype 探针无法量 TFM → 关 protrusion/expansion"""
    if cat != "xetexglyph_tfm":
        return False, ""
    pat = re.compile(r"\\(usepackage|RequirePackage)\s*(\[[^\]]*\])?\s*\{microtype\}")
    n = 0
    for f in ctx.tex_files():
        t = f.read_text(encoding="utf-8", errors="replace")
        nt = pat.sub(
            lambda m: f"\\{m.group(1)}[protrusion=false,expansion=false]{{microtype}}",
            t,
        )
        if nt != t:
            f.write_text(nt, encoding="utf-8")
            n += 1
    return (n > 0), f"microtype protrusion/expansion off in {n} files"


def r_times_to_newtx(ctx, cat, pay, **_):
    """times/mathptmx (T1 TFM) → newtx (xelatex 下走 OTF)"""
    if cat != "xetexglyph_tfm":
        return False, ""
    n = patch_files(
        ctx,
        r"\{(times|mathptmx|mathptm)\}",
        lambda m: "{newtxtext,newtxmath}" if m.group(1) != "times" else "{newtxtext}",
        exts=(".tex", ".sty"),
    )
    return (n > 0), f"times-family -> newtx in {n} files"


def r_hyphenation(ctx, cat, pay, **_):
    """\\hyphenation{} 参数含非拉丁 → 剥离非 [a-zA-Z-] token"""
    if cat != "hyphenation":
        return False, ""
    pat = re.compile(r"\\hyphenation\{([^}]*)\}", re.DOTALL)
    n = 0
    for f in ctx.tex_files():
        t = f.read_text(encoding="utf-8", errors="replace")

        def sane(m):
            toks = re.findall(r"[a-zA-Z][a-zA-Z-]*", m.group(1))
            return "\\hyphenation{" + " ".join(toks) + "}"

        nt = pat.sub(sane, t)
        if nt != t:
            f.write_text(nt, encoding="utf-8")
            n += 1
    return (n > 0), f"sanitize \\hyphenation in {n} files"


def r_soul_cjk(ctx, cat, pay, **_):
    """soul 族命令参数含 CJK → 套 \\mbox 防逐字重构"""
    if cat != "soul_err":
        return False, ""
    pat = re.compile(
        r"\\(hl|ul|st|so|caps)\{((?:[^{}]|\{[^{}]*\})*"
        r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]"
        r"(?:[^{}]|\{[^{}]*\})*)\}"
    )
    n = 0
    for f in ctx.tex_files():
        t = f.read_text(encoding="utf-8", errors="replace")
        nt = pat.sub(lambda m: f"\\{m.group(1)}{{\\mbox{{{m.group(2)}}}}}", t)
        if nt != t:
            f.write_text(nt, encoding="utf-8")
            n += 1
    return (n > 0), f"mbox-wrap soul CJK args in {n} files"


def r_already_def(ctx, cat, pay, **_):
    """thmtools sibling 选项弃用冲突 → 剥掉 sibling= 让各定理独立编号"""
    if cat != "already_def":
        return False, ""
    n = patch_files(ctx, r"sibling\s*=\s*\w+\s*,?\s*", "", exts=(".tex", ".sty"))
    if n == 0:
        # 泛化: 同名 \\newtheorem/\\declaretheorem 去重(留首个)
        return False, "no sibling= found; generic dedup not attempted"
    return True, f"strip sibling= in {n} files"


def r_option_clash(ctx, cat, pay, **_):
    """Option clash: 同包两次 \\usepackage → 合并选项到首处, 注释后处"""
    if cat != "option_clash" or not pay:
        return False, ""
    pkg = pay
    use = re.compile(
        r"^(\s*)\\(usepackage|RequirePackage)\s*(\[([^\]]*)\])?\s*\{([^}]*)\}",
        re.MULTILINE,
    )
    changed = 0
    for f in ctx.tex_files():
        t = f.read_text(encoding="utf-8", errors="replace")
        hits = [
            m
            for m in use.finditer(t)
            if pkg in [x.strip() for x in m.group(5).split(",")]
        ]
        if len(hits) < 2:
            continue
        first, later = hits[0], hits[-1]
        opts1 = first.group(4) or ""
        opts2 = later.group(4) or ""
        merged = ",".join(
            dict.fromkeys([o for o in (opts1 + "," + opts2).split(",") if o])
        )
        t = (
            t[: first.start()]
            + first.group(0).replace(first.group(3) or "", f"[{merged}]")
            + t[first.end() : later.start()]
            + "% fixloop: merged into earlier \\usepackage\n% "
            + later.group(0).replace("\n", "\n% ")
            + t[later.end() :]
        )
        f.write_text(t, encoding="utf-8")
        changed += 1
    return (changed > 0), f"merge \\usepackage{{{pkg}}} opts in {changed} files"


def r_minted_froz(ctx, cat, pay, **_):
    """minted frozencache 版本错配: 有 pygmentize 则去 frozencache+shell-escape,
    否则放弃 (钉 minted v2 超出 tlmgr 能力)"""
    if cat != "minted_froz":
        return False, ""
    if shutil.which("pygmentize"):
        n = patch_files(ctx, r"frozencache\s*,?\s*", "", exts=(".tex",))
        return (n > 0), f"drop frozencache opt in {n} files (needs -shell-escape)"
    return False, "no pygmentize; frozencache unfixable here"


def r_latex209(ctx, cat, pay, wdir=None, main=None, **_):
    """LaTeX 2.09/厂商 cls → 路由拒绝 (非修复: 归入 policy_reject)"""
    if cat == "latex209":
        return True, "REJECT: LaTeX 2.09 doc, route to latex+dvips"
    # missing_file 且主文件是 \documentstyle → 也是 2.09 路由
    if cat == "missing_file" and main:
        try:
            head = (wdir / main).read_text(errors="replace")[:3000]
        except Exception:
            return False, ""
        if "\\documentstyle" in head:
            return True, "REJECT: \\documentstyle (LaTeX 2.09)"
    return False, ""


def r_undefined_cs_guess(ctx, cat, pay, **_):
    """未定义控制序列兜底: cs 名当 sty 名试搜一次 (长射, 命中率低)"""
    if cat != "undefined_cs" or not pay:
        return False, ""
    return False, "no rule (would need cs->pkg knowledge base)"


RULES = [
    ("install_file", r_install_file),
    ("install_tfm", r_install_tfm),
    ("install_sysfont", r_install_sysfont),
    ("missing_pfb_updmap", r_missing_pfb),
    ("pdftex_prim_guard", r_pdftex_prim),
    ("px_to_bp", r_px_to_bp),
    ("microtype_off", r_microtype_off),
    ("times_to_newtx", r_times_to_newtx),
    ("hyphenation_sane", r_hyphenation),
    ("soul_cjk_mbox", r_soul_cjk),
    ("thm_sibling_strip", r_already_def),
    ("option_clash_merge", r_option_clash),
    ("minted_frozencache", r_minted_froz),
    ("latex209_reject", r_latex209),
    ("undefined_cs_guess", r_undefined_cs_guess),
]


def pick_and_apply(ctx, cat, pay):
    """按序找第一条"声称能修且本负载没用过"的规则。返回 (rid, note) 或 None。"""
    for rid, fn in RULES:
        key = (rid, str(pay))
        if key in ctx.applied:
            continue
        kw = {"cat": cat, "pay": pay, "wdir": ctx.wdir, "main": ctx.main_rel}
        try:
            applied, note = fn(ctx, **kw)
        except Exception as e:
            applied, note = False, f"rule crashed: {e}"
        if applied:
            ctx.applied.add(key)
            return rid, note
        if note:
            ctx.log.append(f"    rule {rid}: skip ({note})")
    return None, ""


# =====================================================================
# 4. 编译 + 预检 + 主循环
# =====================================================================

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


USE_RE = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
CLS_RE = re.compile(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")


def static_precheck(ctx):
    """第0招: 静态扫 \\usepackage/\\RequirePackage/\\documentclass →
    kpsewhich 验证 → 批量 tlmgr install。返回装了的包列表。"""
    need = set()
    for f in ctx.tex_files():
        t = None
        with contextlib.suppress(Exception):
            t = f.read_text(encoding="utf-8", errors="replace")
        if t is None:
            continue
        for m in USE_RE.finditer(t):
            for p in m.group(1).split(","):
                pkg = p.strip()
                if pkg:
                    need.add(pkg + ".sty")
        for m in CLS_RE.finditer(t):
            need.add(m.group(1).strip() + ".cls")
    missing = sorted(f for f in need if not ctx.kpsewhich(f))
    pkgs = []
    for f in missing:
        pkgs += ctx.tlmgr_search_file(f)
    pkgs = sorted(set(pkgs))
    if pkgs:
        ctx.tlmgr_install(pkgs)
    return missing, pkgs


def compile_pass(ctx):
    """xelatex nonstopmode ≤2 pass; 返回 (pdf?, n_errors, cat, pay, sec)。"""
    cwd = ctx.wdir / Path(ctx.main_rel).parent
    name = Path(ctx.main_rel).name
    stem = Path(ctx.main_rel).stem
    pdf, log = cwd / f"{stem}.pdf", cwd / f"{stem}.log"
    nerr, first_cat, first_pay, sec = 0, None, None, 0.0
    for p in (1, 2):
        if p == 2 and not pdf.exists():
            break
        _rc, _out, s, to = ctx.run([XELATEX, "-interaction=nonstopmode", name], cwd=cwd)
        sec += s
        e, c, n, tail = first_error(log)
        nerr += n
        if first_cat is None and (e or to):
            first_cat, first_pay = classify(e, c, tail, to)
        if to:
            first_cat = "timeout"
            break
    return pdf.exists(), nerr, first_cat, first_pay, sec


def prep_sandbox(proj_name, cond, texmf_mode, precheck):
    """work_compile/{p}/{cond} → work_fixloop/{p}/{cond} (去掉编译产物,
    保留源码与图片pdf; 删掉主stem.pdf防误判)。"""
    src = WORK / proj_name / cond
    dst = FIXWORK / proj_name / cond
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(
            "_tect_out",
            "*.aux",
            "*.log",
            "*.out",
            "*.toc",
            "*.lof",
            "*.lot",
            "*.fls",
            "*.fdb_latexmk",
            "*.synctex*",
            "*.blg",
            "texput.*",
            "missfont.log",
            ".DS_Store",
            "__pycache__",
        ),
    )
    main = find_main_tex(dst)
    if main:
        stem_pdf = main.parent / (main.stem + ".pdf")
        if stem_pdf.exists():
            stem_pdf.unlink()  # 上次跑出的输出, 防"躺着成功"
    if texmf_mode == "cold":
        tag = "" if precheck else "_np"
        tm = FIXWORK / proj_name / f"_texmf{tag}_{cond}"
        shutil.rmtree(tm, ignore_errors=True)
        for sub in ("home", "var", "config"):
            (tm / sub).mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["TEXMFHOME"] = str(tm / "home")
        env["TEXMFVAR"] = str(tm / "var")
        env["TEXMFCONFIG"] = str(tm / "config")
    else:
        env = dict(os.environ)
    return dst, (str(main.relative_to(dst)) if main else None), env


def run_cell(proj_name, cond, texmf_mode="cold", precheck=True):
    """跑一格修复循环。返回 cell 结果 dict。"""
    log = []
    wdir, main_rel, env = prep_sandbox(proj_name, cond, texmf_mode, precheck)
    cell = {
        "project": proj_name,
        "cond": cond,
        "main": main_rel,
        "texmf": texmf_mode,
        "precheck": precheck,
        "rounds": [],
        "actions": [],
        "verdict": None,
    }
    if not main_rel:
        cell["verdict"] = "no_main_tex"
        return cell
    ctx = Ctx(wdir, main_rel, env, log)
    stem = Path(main_rel).stem

    if precheck:
        t0 = time.time()
        missing, pkgs = static_precheck(ctx)
        cell["actions"].append(
            {
                "round": 0,
                "rule": "static_precheck",
                "detail": f"missing files={missing} -> install {pkgs}",
                "sec": round(time.time() - t0, 1),
            }
        )

    prev_sig, sig_count = None, 0
    for rnd in range(1, MAX_ROUNDS + 1):
        pdf, nerr, cat, pay, sec = compile_pass(ctx)
        pdf_bytes = 0
        p = wdir / Path(main_rel).parent / f"{stem}.pdf"
        if pdf:
            pdf_bytes = p.stat().st_size
        entry = {
            "round": rnd,
            "pdf": pdf,
            "pdf_bytes": pdf_bytes,
            "n_errors": nerr,
            "category": cat,
            "payload": pay,
            "sec": round(sec, 1),
        }
        cell["rounds"].append(entry)
        log.append(f"  r{rnd}: pdf={pdf} err={nerr} cat={cat} pay={pay} ({sec:.1f}s)")
        # —— 终止判据 ——
        if pdf and nerr == 0:
            cell["verdict"] = "clean"
            break
        if cat in (None, "clean"):
            cell["verdict"] = "clean" if pdf else "no_errors_no_pdf"
            break
        if cat == "latex209" or (
            cat == "missing_file"
            and main_rel
            and "\\documentstyle"
            in (wdir / main_rel).read_text(errors="replace")[:3000]
        ):
            cell["verdict"] = "reject_latex209"
            break
        sig = f"{cat}:{pay}"
        sig_count = sig_count + 1 if sig == prev_sig else 1
        prev_sig = sig
        if sig_count >= 3:
            cell["verdict"] = "stuck"
            break
        # —— 规则匹配+应用 ——
        rid, note = pick_and_apply(ctx, cat, pay)
        if rid is None:
            cell["verdict"] = ("unfixable:" + str(cat)) if not pdf else "dirty_pdf"
            break
        if note.startswith("REJECT"):
            cell["verdict"] = "reject_latex209"
            break
        cell["actions"].append({"round": rnd, "rule": rid, "detail": note})
        log.append(f"    apply {rid}: {note}")
    else:
        cell["verdict"] = "max_rounds"

    # 汇总最终态
    last = cell["rounds"][-1] if cell["rounds"] else {}
    cell["final_pdf"] = bool(last.get("pdf"))
    cell["final_errors"] = last.get("n_errors")
    cell["final_cat"] = last.get("category")
    cell["installed"] = ctx.installed_pkgs
    cell["log"] = log
    started_fail = not (cell["rounds"] and cell["rounds"][0]["pdf"])
    cell["started_fail"] = started_fail
    if cell["verdict"] in (None, "max_rounds", "stuck") and cell["final_pdf"]:
        cell["verdict"] = "dirty_pdf" if (last.get("n_errors") or 9) > 0 else "clean"
    if (
        cell["final_pdf"]
        and (cell["final_errors"] or 0) <= CLEAN_ERR_MAX
        and cell["verdict"] == "dirty_pdf"
    ):
        cell["verdict"] = "acceptable_pdf"  # pdf 且错误数 <= 阈值
    return cell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conds", default="baseline,ctex,zh")
    ap.add_argument("--projects", default="")
    ap.add_argument("--texmf", choices=["cold", "warm"], default="cold")
    ap.add_argument("--no-precheck", action="store_true")
    ap.add_argument("--out", default=str(JSON_OUT))
    args = ap.parse_args()

    conds = args.conds.split(",")
    projects = sorted(d.name for d in WORK.iterdir() if d.is_dir())
    if args.projects:
        pats = args.projects.split(",")
        projects = [p for p in projects if any(x in p for x in pats)]

    out_path = Path(args.out)
    data = {
        "meta": {
            "date": time.strftime("%Y-%m-%d %H:%M"),
            "texmf_mode": args.texmf,
            "precheck": not args.no_precheck,
            "max_rounds": MAX_ROUNDS,
            "clean_err_max": CLEAN_ERR_MAX,
            "xelatex": subprocess.run(
                [XELATEX, "--version"], capture_output=True, text=True
            ).stdout.splitlines()[0],
            "engine": "xelatex -interaction=nonstopmode, ≤2 pass",
            "rules": [r[0] for r in RULES],
        },
        "cells": [],
    }
    if out_path.exists():
        with contextlib.suppress(Exception):
            data["cells"] = json.loads(out_path.read_text())["cells"]

    for pn in projects:
        for cond in conds:
            if not (WORK / pn / cond).exists():
                continue
            # 已跑过的格跳过(增量续跑)
            if any(
                c["project"] == pn
                and c["cond"] == cond
                and c.get("texmf") == args.texmf
                and c.get("precheck") == (not args.no_precheck)
                for c in data["cells"]
            ):
                print(f"[skip] {pn}/{cond}", flush=True)
                continue
            print(f"===== {pn} / {cond} =====", flush=True)
            cell = run_cell(
                pn, cond, texmf_mode=args.texmf, precheck=not args.no_precheck
            )
            data["cells"].append(cell)
            r0 = cell["rounds"][0] if cell["rounds"] else {}
            print(
                f"  start: pdf={r0.get('pdf')} err={r0.get('n_errors')} "
                f"cat={r0.get('category')} | verdict={cell['verdict']} "
                f"rounds={len(cell['rounds'])} "
                f"pkgs={len(cell['installed'])}",
                flush=True,
            )
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1))

    # —— 汇总 ——
    cells = data["cells"]
    n_fail = sum(1 for c in cells if c["started_fail"])
    rescued = sum(1 for c in cells if c["started_fail"] and c["final_pdf"])
    clean = sum(1 for c in cells if c["verdict"] == "clean")
    print("\n==== SUMMARY ====")
    print(
        f"cells={len(cells)} started_fail={n_fail} "
        f"rescued_pdf={rescued} clean_final={clean}"
    )
    for c in cells:
        r0 = c["rounds"][0] if c["rounds"] else {}
        print(
            f"  {c['project']:12} {c['cond']:8} "
            f"start={'FAIL' if c['started_fail'] else 'pdf~':4} "
            f"({r0.get('category')}) -> {c['verdict']:18} "
            f"err {r0.get('n_errors')}->{c.get('final_errors')} "
            f"r={len(c['rounds'])}"
        )
    print(f"json -> {out_path}")


if __name__ == "__main__":
    main()
