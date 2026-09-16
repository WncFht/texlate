"""builtins — fixloop 命名函数注册表 (rules.yaml `function:` 的实现侧)。

两类签名:
  - REWRITE_FNS: ``(re.Match) -> str`` —— regex_rewrite 条目的逐 match 改写
    (spike 里 `px_to_bp`/`keep_latin_tokens`, 算术/集合变换非纯模板)
  - TRANSFORM_FNS: ``(ctx, eng, payload, params) -> (applied, note)`` ——
    builtin_transform 条目的文件级算法改写 (spike 里 `option_clash_merge`,
    新增 6 条按 docs/08 §5.2 实现)

社区贡献规则多数只需写 regex; 新算法型修复才需要往这里 PR 代码。
"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.normalize import INTERMEDIATE_SUFFIXES

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = ["REWRITE_FNS", "TRANSFORM_FNS"]

# pdfTeX 原语清单 (spike L284-298)
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

_DATE_RE = re.compile(
    r"\\Provides(?:Package|Class|ExplPackage|ExplClass)\s*\{[^}]*\}\s*\[(\d{4})[/.-](\d{2})[/.-](\d{2})"
)


# ════════════════════════════════════════════════════════════════
# regex_rewrite 逐 match 改写函数 —— (Match) -> str
# ════════════════════════════════════════════════════════════════


def px_to_bp(m: re.Match[str]) -> str:
    """``N px`` → ``N*0.75 bp`` (CSS 96dpi 换算, spike L369-373)。"""
    v = float(m.group(1)) * 0.75
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s + "bp"


def keep_latin_tokens(m: re.Match[str]) -> str:
    r"""``\\hyphenation{...}`` 参数只留 ``[a-zA-Z][a-zA-Z-]*`` token (spike L418-420)。"""
    toks = re.findall(r"[a-zA-Z][a-zA-Z-]*", m.group(1))
    return "\\hyphenation{" + " ".join(toks) + "}"


REWRITE_FNS = {"px_to_bp": px_to_bp, "keep_latin_tokens": keep_latin_tokens}


# ════════════════════════════════════════════════════════════════
# builtin_transform 文件级变换 —— (ctx, eng, payload, params) -> (applied, note)
# ════════════════════════════════════════════════════════════════

_USE_RE = re.compile(
    r"^(\s*)\\(usepackage|RequirePackage)\s*(\[([^\]]*)\])?\s*\{([^}]*)\}",
    re.MULTILINE,
)


def option_clash_merge(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Option clash: 同包两次 ``\\usepackage`` → 合并选项到首处, 注释后处 (spike L459-494)。"""
    del eng  # 签名面统一; 本变换不触引擎
    if not payload:
        return False, "no pkg payload"
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        hits = [
            m
            for m in _USE_RE.finditer(t)
            if payload in [x.strip() for x in m.group(5).split(",")]
        ]
        if len(hits) < 2:  # noqa: PLR2004 - 2 = 重复加载的最小命中数
            continue
        first, later = hits[0], hits[-1]
        opts1 = first.group(4) or ""
        opts2 = later.group(4) or ""
        merged = ",".join(
            dict.fromkeys(o for o in (opts1 + "," + opts2).split(",") if o)
        )
        m0 = first.group(0)
        if first.group(3):
            first_new = m0.replace(first.group(3), f"[{merged}]", 1)
        else:  # 首个加载无 [opts] → 在花括号前插 [merged]; spike L486
            # `str.replace("", ...)` 会逐位插入, 此处修掉该潜伏 bug
            brace = m0.rfind("{")
            first_new = m0[:brace] + f"[{merged}]" + m0[brace:]
        t = (
            t[: first.start()]
            + first_new
            + t[first.end() : later.start()]
            + "% fixloop: merged into earlier \\usepackage\n% "
            + later.group(0).replace("\n", "\n% ")
            + t[later.end() :]
        )
        ctx.write(f, t)
        changed += 1
    return (changed > 0), f"merge \\usepackage{{{payload}}} opts in {changed} files"


def pdftex_prim_polyfill(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""读取型 pdfTeX 原语补定义: ``\\ifdefined\\<prim>\\else\\chardef\\<prim>=1\\fi``。

    guard 规则只管 ``\\pdfX=val``/``\\pdfX{..}`` 赋值型; ``\\ifnum\\pdfoutput``
    这类读取型需要原语已定义 (docs/08:268)。注入点在主文件
    ``\\documentclass`` 行后; ``ifdefined`` 前缀天然幂等。
    """
    del eng  # 签名面统一; 注入发生在主文件源文本
    prim = str(params.get("prim") or payload or "")
    if prim not in PDFTEX_PRIMS:
        return False, f"{prim} not in pdfTeX prim list"
    guard = f"\\ifdefined\\{prim}\\else\\chardef\\{prim}=1\\fi"
    main = ctx.main_path()
    if main is None:
        return False, "no main tex"
    t = ctx.read(main) or ""
    if f"\\ifdefined\\{prim}" in t:
        return False, f"{prim} already guarded"
    lines = t.split("\n")
    for i, ln in enumerate(lines):
        if "\\documentclass" in ln:
            lines.insert(i + 1, guard + " % fixloop polyfill")
            ctx.write(main, "\n".join(lines))
            return True, f"polyfill \\{prim} after \\documentclass"
    ctx.write(main, guard + " % fixloop polyfill\n" + t)
    return True, f"polyfill \\{prim} at file head"


def _provides_date(text: str) -> tuple[int, int, int] | None:
    m = _DATE_RE.search(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def find_vendored_shadows(ctx: LoopCtx, eng: Engine, exts: tuple[str, ...]) -> list:
    r"""工程内 .sty/.cls 与系统副本同名且本地更旧 → 遮蔽候选列表。

    比较 ``\\ProvidesPackage``/``\\ProvidesClass`` 日期; 本地无日期或系统
    无副本不列为候选 (盲删必死 —— 同目录 cls 可能是唯一来源)。
    """
    cands = []
    for f in ctx.tex_files(exts):
        resolved = eng.probe_file(f.name)
        if not resolved:
            continue
        rp = Path(resolved) if isinstance(resolved, str) else resolved
        try:
            if rp.resolve() == f.resolve():
                continue  # probe 命中工程自身, 非遮蔽
        except OSError:
            continue
        local_txt = ctx.read(f)
        try:
            sys_txt = Path(rp).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if local_txt is None:
            continue
        ld, sd = _provides_date(local_txt), _provides_date(sys_txt)
        if ld is not None and sd is not None and ld < sd:
            cands.append((f, ld, sd))
    return cands


def vendored_shadow_isolate(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    """确证更旧的工程内 .sty/.cls → rename ``<f>.fixloop-iso`` 隔离 (docs/08:269)。"""
    del payload
    exts = tuple(params.get("exts") or (".sty", ".cls"))
    suffix = str(params.get("suffix") or ".fixloop-iso")
    moved = []
    for f, ld, sd in find_vendored_shadows(ctx, eng, exts):
        f.rename(f.with_name(f.name + suffix))
        moved.append(f"{f.name} ({ld} < {sd})")
    return (bool(moved)), f"isolate vendored: {', '.join(moved)}"


def non_utf8_recode(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""非 UTF-8 源文件就地转码 UTF-8 (docs/08:272; iconv 等价物, stdlib 版)。

    只对 utf-8 解码真失败的文件动刀; cp1252 是 latin-1 超集, 兼容
    西文 smart quote。能 utf-8 解码的文件绝不重写。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls", ".bib"))
    recoded = []
    for f in ctx.tex_files(exts):
        raw = f.read_bytes()
        try:
            raw.decode("utf-8")
            continue
        except UnicodeDecodeError:
            pass
        for enc in ("cp1252", "latin-1"):
            with contextlib.suppress(UnicodeDecodeError):
                f.write_text(raw.decode(enc), encoding="utf-8")
                recoded.append(f"{f.name}({enc})")
                ctx.invalidate(f)
                break
    return (bool(recoded)), f"recode to utf-8: {', '.join(recoded)}"


def bbl_stub_rewrite(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Tectonic stub bbl 断链: 有 .bbl 无 .bib → ``\\bibliography{x}`` → ``\\input{main.bbl}``。

    实证根因 (ctanfetch-probe §3.3): tectonic 自动 bibtex 在无 .bib 时
    生成 24 行 stub bbl, 在内存文件层遮蔽磁盘真 bbl → 空 thebibliography。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    bbls = {p.stem: p for p in ctx.wdir.rglob("*.bbl")}
    if not bbls:
        return False, "no .bbl in project"
    main = ctx.main_path()
    stem = main.stem if main is not None else None
    target = bbls.get(stem) or next(iter(bbls.values()))
    pat = re.compile(r"\\bibliography(\[[^\]]*\])?\{[^}]*\}")
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "\\bibliography" not in t:
            continue
        nt = pat.sub(rf"\\input{{{target.name}}}", t, count=1)
        if nt != t:
            ctx.write(f, nt)
            changed += 1
    return (
        changed > 0
    ), f"\\bibliography -> \\input{{{target.name}}} in {changed} files"


def font_sub_shim(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""MF-only 字体包 → Type1 近亲 shim (docs/08:275, ctanfetch-probe §3.5)。

    ``\\usepackage{bbm}`` → ``\\usepackage{dsfont}`` + cs 族改写
    (``\\mathbbm``→``\\mathds`` 等)。物理字体投放对 tectonic xdvipdfmx
    是死路, 只能靠改写换 bundle 内字体族。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    shim_map: dict[str, dict[str, Any]] = params.get("shim_map") or {}
    changed = []
    load_pat = re.compile(
        r"(\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*)\{([^}]*)\}"
    )
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt = t
        for old_pkg, spec in shim_map.items():
            new_pkg = spec.get("usepackage")
            if not new_pkg:
                continue

            # 装载点: {bbm} 精确 / {a,bbm,c} 列表元素 (其余不动)
            def _sw(m: re.Match[str], _o: str = old_pkg, _n: str = new_pkg) -> str:
                parts = [x.strip() for x in m.group(2).split(",")]
                if _o not in parts:
                    return m.group(0)
                return (
                    m.group(1)
                    + "{"
                    + ",".join(_n if p == _o else p for p in parts)
                    + "}"
                )

            nt = load_pat.sub(_sw, nt)
            for old_cs, new_cs in (spec.get("cs_map") or {}).items():
                nt = re.sub(rf"\\{old_cs}\b", rf"\\{new_cs}", nt)
        if nt != t:
            ctx.write(f, nt)
            changed.append(f.name)
    return (bool(changed)), f"font shim applied in {', '.join(changed)}"


def pstricks_dvips_preflight(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    """latex+dvips 路由前的 .pro 资源预检 (docs/08:273)。

    无论资源齐不齐都 REJECT (dvips 是唯一出路); 缺资源时 note 附
    advisory 让上层决策 (装 pst-tools / 放弃 pstricks 路)。
    """
    del ctx, payload  # ctx 无需读文件: 预检只看系统侧资源

    missing = [fn for fn in params.get("require_files") or [] if not eng.probe_file(fn)]
    route = params.get("route", "latex+dvips")
    if missing:
        return True, f"REJECT: route={route} advisory=missing:{','.join(missing)}"
    return True, f"REJECT: route={route} dvips-resources-ok"


_EPS_EXTS = (".eps", ".ps")
_GS_FLAGS = [
    "-dSAFER",
    "-dBATCH",
    "-dNOPAUSE",
    "-sDEVICE=pdfwrite",
    "-dEPSCrop",
    "-dEmbedAllFonts=true",
]
#: 只走 PostScript specials 的 graphicx 驱动 —— tectonic (xdvipdfmx) 下必死,
#: 且 ``[dvips]{graphicx}`` 会把无扩展名引用的搜索序掰成 .eps 优先
#: (1902.11112 实证: plykin.pdf 已生成仍请求 plykin.eps)。
_PS_DRIVERS = frozenset(
    {
        "dvips",
        "dvipsone",
        "dvipsam",
        "dviwindo",
        "dviwin",
        "oztex",
        "textures",
        "pctexps",
        "pctexwin",
        "pctexhp",
        "pctex32",
        "psprint",
        "pubps",
        "dvitops",
        "dvi2ps",
        "xdvi",
    }
)
#: 带选项的装载点; documentclass/documentstyle/LoadClass 是全局选项位。
_LOAD_OPT_RE = re.compile(
    r"\\(usepackage|RequirePackage|documentclass|documentstyle|LoadClass)"
    r"\s*\[([^\]\n]*)\](\s*\{[^}]*\})"
)
_GRAPHICS_PKGS_RE = re.compile(r"(?i)\b(?:graphics|graphicx|color|epsfig|epsf)\b")


def _strip_ps_driver_opts(t: str) -> tuple[str, int]:
    """摘 PS 路由驱动选项 → (新文本, 摘除数)。

    usepackage/RequirePackage 只在参数表命中图形族包名时剥; 类装载点
    (全局选项会下传给 graphicx) 无条件剥。选项表剥空时连方括号一起去掉。
    """
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        cmd, opts, brace = m.group(1), m.group(2), m.group(3)
        if cmd in ("usepackage", "RequirePackage") and not _GRAPHICS_PKGS_RE.search(
            brace
        ):
            return m.group(0)
        parts = [p.strip() for p in opts.split(",")]
        keep = [p for p in parts if p and p.lower() not in _PS_DRIVERS]
        if len(keep) == len(parts):
            return m.group(0)
        n += len(parts) - len(keep)
        opt = f"[{','.join(keep)}]" if keep else ""
        return f"\\{cmd}{opt}{brace}"

    return _LOAD_OPT_RE.sub(_sub, t), n


def _run_convert(tool: str, src: Path, dst: Path) -> tuple[int | None, str, bool]:
    """跑单个转换工具 → (rc, out, timed_out)。argv 列表无 shell。"""
    argv = (
        [tool, str(src), f"--outfile={dst}"]
        if Path(tool).name.startswith("epstopdf")
        else [tool, *_GS_FLAGS, "-o", str(dst), str(src)]
    )
    try:
        p = subprocess.run(  # noqa: S603  # 转换工具调用, 非用户输入
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "", True
    except OSError as e:
        return None, f"{type(e).__name__}: {e}", False
    else:
        return p.returncode, p.stdout or "", False


def _convert_one(epstopdf: str | None, gs: str | None, src: Path, dst: Path) -> bool:
    """单个 .eps/.ps → .pdf: epstopdf 优先, gs -dEPSCrop 兜底 (texglot 同配方)。"""
    for tool in (epstopdf, gs):
        if not tool:
            continue
        rc, _out, to = _run_convert(tool, src, dst)
        if rc == 0 and not to and dst.is_file() and dst.stat().st_size:
            return True
        dst.unlink(missing_ok=True)  # 失败残留清掉, 防半文件被当成产物
    return False


def _rewrite_eps_refs(
    ctx: LoopCtx, exts: tuple[str, ...], converted: dict[str, str]
) -> tuple[int, int]:
    """逐 tex 文件: 字面量 ``x.eps``→``x.pdf`` + 剥 PS 驱动选项 → (改写文件数, 摘驱动数)。"""
    n_files = 0
    n_drivers = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt = t
        for old, new in converted.items():
            if old in nt:
                nt = nt.replace(old, new)
        nt, k = _strip_ps_driver_opts(nt)
        n_drivers += k
        if nt != t:
            ctx.write(f, nt)
            n_files += 1
    return n_files, n_drivers


def eps_to_pdf(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Xdvipdfmx EPS 硬墙救回: 全量 .eps/.ps → .pdf + 引用改写 + PS 驱动剥离。

    实证 (fixloop-v2 整改探针): tectonic 报 ``image inclusion failed for "x.eps"``
    时, 同名 ``x.pdf`` 存在即可过 —— graphicx 无扩展名引用的搜索序里 .pdf
    先于 .eps, 显式 ``{x.eps}``/``file=x.eps`` 则由字面替换接住; 若工程带
    ``[dvips]{graphicx}`` 等 PS 驱动选项 (1902.11112), 无扩展名引用仍会被掰回
    .eps 优先, 故同步剥 PS 驱动。
    参考 texglot app/graphics.py (gs -dEPSCrop + 引用改写同款思路)。
    """
    del eng, payload  # 转换不触引擎原语; 全量转换不靠单点 payload
    epstopdf = shutil.which("epstopdf")
    gs = shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")
    if not epstopdf and not gs:
        return False, "no epstopdf/gs available"
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    sources = sorted(
        p for p in ctx.wdir.rglob("*") if p.is_file() and p.suffix in _EPS_EXTS
    )
    if not sources:
        return False, "no .eps/.ps in project"
    converted: dict[str, str] = {}  # "fig.eps" -> "fig.pdf" (basename 级)
    for src in sources:
        dst = src.with_suffix(".pdf")
        if dst.is_file() and dst.stat().st_size:
            converted[src.name] = dst.name  # 上轮已转: 复用, 免重转
            continue
        if _convert_one(epstopdf, gs, src, dst):
            converted[src.name] = dst.name
    if not converted:
        return False, f"0/{len(sources)} converted"
    # 显式引用改写 + PS 驱动选项剥离: `x.eps`/`x.ps` 字面量改 `x.pdf`,
    # [dvips] 族驱动摘掉让无扩展名引用落到 .pdf 搜索序
    n_files, n_drivers = _rewrite_eps_refs(ctx, exts, converted)
    note = (
        f"eps->pdf {len(converted)}/{len(sources)} converted, "
        f"refs rewritten in {n_files} files"
    )
    if n_drivers:
        note += f", {n_drivers} ps-driver opts stripped"
    return True, note


def legacy_pkg_shim(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""退役/改名包的 shim: ``shim_map[payload]`` → 往 wdir 注入同名 stub + 装依赖。

    spec 键:
      ``loads: <pkg-base>`` — cls 类 stub 模板 ``\\LoadClassWithOptions{<pkg>}``;
      ``body: <tex>``       — 自定义 stub 全文 (sty 桥接, 如 psfig→epsfig);
      ``needs: [files]``    — stub 依赖文件, 先 install_file 补齐 (缺则照记, 下轮
                              missing_file 自然归因)。
    实证锚点 (fixloop-v2): aastex→emulateapj 救回 1806.06690 (aastex701 删了
    ``\\altaffilmark`` 族, 非 drop-in; emulateapj 为 arXiv 投稿仿 aastex 接口);
    psfig→epsfig 桥可用因 epsfig 的 Gin key 同收 ``figure=``/``file=``。
    """
    spec = (params.get("shim_map") or {}).get(payload or "")
    if not spec:
        return False, f"no legacy shim for {payload}"
    stub = spec.get("body")
    loads = spec.get("loads")
    if not stub and loads:
        stem = (payload or "").rsplit(".", 1)[0]
        stub = (
            "\\NeedsTeXFormat{LaTeX2e}\n"
            # 版本串必须以 YYYY/MM/DD 日期开头: \\documentclass 装载时
            # \\@ifl@t@r 会解析 ver@*.cls, 裸文字 "fixloop ..." 让
            # \\@parse@version@ 读出 `f' → "Missing = inserted for \\ifnum"
            # (1806.06690 实证; 无 halt-on-error 时可恢复故有 pdf 假象)。
            f"\\ProvidesClass{{{stem}}}[2026/09/15 fixloop legacy shim -> {loads}]\n"
            f"\\LoadClassWithOptions{{{loads}}}\n"
            "\\endinput\n"
        )
    if not stub:
        return False, f"shim spec for {payload} has neither body nor loads"
    missing = []
    for dep in spec.get("needs") or []:
        if ctx.wdir.joinpath(dep).is_file():
            continue
        if eng.probe_file(dep) or eng.install_file(dep):
            continue
        missing.append(dep)
    target = ctx.wdir / str(payload)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stub, encoding="utf-8")
    note = f"stub {payload} injected"
    if loads:
        note += f" (\\LoadClassWithOptions{{{loads}}})"
    if missing:
        note += f"; deps still missing: {', '.join(missing)}"
    return True, note


#: AAS 期刊缩写宏表 —— emulateapj.cls L1201-1256 ``\ref@jnl`` 全表抄录
#: (去壳成纯文本展开)。实证锚点: tectonic bundle 内置 aastex 5.0rc3.1 (1999)
#: 没有这批宏, 老 aastex 文档 \bibitem 里的 ``\actaa`` 族全成 undefined_cs
#: (1806.06690 tectonic 臂)。\providecommand 语义: 类里已有定义时不覆盖。
_JOURNAL_MACROS: dict[str, str] = {
    "aj": "AJ",
    "araa": "ARA\\&A",
    "apj": "ApJ",
    "apjl": "ApJ~Lett.",
    "apjs": "ApJS",
    "ao": "Appl.~Opt.",
    "apss": "Ap\\&SS",
    "aap": "A\\&A",
    "aapr": "A\\&A~Rev.",
    "aaps": "A\\&AS",
    "azh": "AZh",
    "baas": "BAAS",
    "icarus": "Icarus",
    "jrasc": "JRASC",
    "memras": "MmRAS",
    "mnras": "MNRAS",
    "pra": "Phys.~Rev.~A",
    "prb": "Phys.~Rev.~B",
    "prc": "Phys.~Rev.~C",
    "prd": "Phys.~Rev.~D",
    "pre": "Phys.~Rev.~E",
    "prl": "Phys.~Rev.~Lett.",
    "pasp": "PASP",
    "pasj": "PASJ",
    "qjras": "QJRAS",
    "skytel": "S\\&T",
    "solphys": "Sol.~Phys.",
    "sovast": "Soviet~Ast.",
    "ssr": "Space~Sci.~Rev.",
    "zap": "ZAp",
    "nat": "Nature",
    "iaucirc": "IAU~Circ.",
    "aplett": "Astrophys.~Lett.",
    "apspr": "Astrophys.~Space~Phys.~Res.",
    "bain": "Bull.~Astron.~Inst.~Netherlands",
    "fcp": "Fund.~Cosmic~Phys.",
    "gca": "Geochim.~Cosmochim.~Acta",
    "grl": "Geophys.~Res.~Lett.",
    "jcp": "J.~Chem.~Phys.",
    "jgr": "J.~Geophys.~Res.",
    "jqsrt": "J.~Quant.~Spec.~Radiat.~Transf.",
    "memsai": "Mem.~Soc.~Astron.~Italiana",
    "nphysa": "Nucl.~Phys.~A",
    "physrep": "Phys.~Rep.",
    "physscr": "Phys.~Scr.",
    "planss": "Planet.~Space~Sci.",
    "procspie": "Proc.~SPIE",
    "actaa": "Acta Astron.",
    "caa": "Chinese Astron. Astrophys.",
    "cjaa": "Chinese J. Astron. Astrophys.",
    "jcap": "J.~Cosmology Astropart.~Phys.",
    "na": "New~A",
    "nar": "New~A~Rev.",
    "pasa": "PASA",
    "rmxaa": "Rev.~Mexicana Astron.~Astrofis.",
}
_DOCCLASS_LINE_RE = re.compile(r"(?m)^[ \t]*\\document(?:class|style)[^\n]*\n?")


def _drop_pkg_loads(t: str, pkg: str) -> tuple[str, int]:
    r"""剥 ``\usepackage``/``\RequirePackage`` 对 pkg 的装载 → (新文本, 摘除数)。

    独载: 行首锚 (前缀全空白) → 整行注释; 行内嵌入 → 置空
    (注释替换会误吃同行尾 token)。列表成员: 外科摘除元素保留其余。
    """
    pat = re.compile(
        rf"\\(usepackage|RequirePackage)(\s*\[[^\]\n]*\])?\s*\{{([^}}]*)\b{re.escape(pkg)}\b([^}}]*)\}}"
    )
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        pkgs = [p.strip() for p in (m.group(3) + "," + m.group(4)).split(",")]
        keep = [p for p in pkgs if p and p != pkg]
        n += 1
        if keep:
            return f"\\{m.group(1)}{m.group(2) or ''}{{{','.join(keep)}}}"
        ls = m.string.rfind("\n", 0, m.start()) + 1
        if m.string[ls : m.start()].strip():
            return ""
        return "% fixloop: stripped " + m.group(0).strip()

    return pat.sub(_sub, t), n


_INPUTENCODING_RE = re.compile(r"\\inputencoding\s*\{[^}]*\}")


def strip_inputenc(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Unicode 引擎剥 inputenc: 装载点 + ``\inputencoding{}`` 调用 (compilebench-v3 缺口)。

    inputenc.sty 对 xetex/luatex 整包拒载 ("not designed for xetex or
    luatex"); 源真为非 UTF-8 时由 warn_utf8 → non_utf8_source 在后续轮
    接续转码, 两轮分工不混。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    changed = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "inputenc" not in t:
            continue
        nt, n_load = _drop_pkg_loads(t, "inputenc")
        nt, n_enc = _INPUTENCODING_RE.subn("", nt)
        if nt != t:
            ctx.write(f, nt)
            changed.append(f"{f.name}(-{n_load}load,-{n_enc}enc)")
    return (bool(changed)), f"strip inputenc in {', '.join(changed)}"


#: undefined_cs → 定向修复表 (cs_targeted_fix 的默认表, rules.yaml
#: params.cs_table 可扩)。spec 键: strip_pkg / usepackage / cs_map /
#: polyfill / engines{eng: 覆盖 spec} —— 组合语义见 cs_targeted_fix。
_CS_FIX_TABLE: dict[str, dict[str, Any]] = {
    # 1909.05039: breakurl 的 shipout 钩调 \headerps@out —— 该宏只在
    # hyperref dvips/ps2pdf 驱动下有定义, xetex/tectonic 走 hdvipdfm →
    # 未定义即炸。breakurl 对 pdf 直出引擎本就无意义, 剥装载点是根修。
    "headerps@out": {"strip_pkg": "breakurl"},
    # 2301.01267: \mathbbm ← bbm。xelatex/TL2026 装 bbm-macros 即可;
    # tectonic 侧 bbm 是 MF-only 死路 (font_sub_shim 同族) → 换 dsfont\mathds。
    "mathbbm": {
        "usepackage": "bbm",
        "engines": {
            "tectonic": {
                "strip_pkg": "bbm",
                "usepackage": "dsfont",
                "cs_map": {"mathbbm": "mathds"},
            }
        },
    },
}


def _map_tex_files(
    ctx: LoopCtx, exts: tuple[str, ...], fn: Callable[[str], tuple[str, int]]
) -> int:
    """逐 tex 文件应用 ``fn(t) -> (nt, n)``, n>0 且文本有变则写回 → 改动文件数。"""
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n = fn(t)
        if n and nt != t:
            ctx.write(f, nt)
            n_files += 1
    return n_files


def _rewrite_cs_map(t: str, cmap: dict[str, str]) -> tuple[str, int]:
    r"""``\old``→``\new`` 逐对改写 (词边界定) → (新文本, 是否改动)。"""
    nt = t
    for old, new in cmap.items():
        nt = re.sub(rf"\\{old}\b", rf"\\{new}", nt)
    return nt, int(nt != t)


def _inject_after_docclass(ctx: LoopCtx, snippet: str) -> bool:
    """主文件 documentclass 行后注入 snippet (无 documentclass 则文件头; 幂等)。"""
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None or snippet in t:
        return False
    m = _DOCCLASS_LINE_RE.search(t)
    at = m.end() if m else 0
    ctx.write(main, t[:at] + snippet + "\n" + t[at:])
    return True


def _ensure_usepackage(ctx: LoopCtx, eng: Engine, pkg: str) -> list[str]:
    r"""主文件 ``\documentclass`` 后注入 ``\usepackage{pkg}`` + 装文件 → 已做事项。"""
    out = []
    if not re.search(
        rf"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{{[^}}]*\b{re.escape(pkg)}\b",
        ctx.source_blob(),
    ) and _inject_after_docclass(ctx, f"\\usepackage{{{pkg}}} % fixloop: cs-fix"):
        out.append(f"inject \\usepackage{{{pkg}}}")
    if eng.probe_file(f"{pkg}.sty") or eng.install_file(f"{pkg}.sty"):
        out.append(f"{pkg}.sty available")
    else:
        out.append(f"{pkg}.sty still missing")
    return out


def cs_targeted_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""undefined_cs 按 cs 修复表打靶 (handoff §2.2 cs→包表项)。

    spec 键组合序: ``strip_pkg`` 剥装载点 → ``usepackage`` 注入+装文件
    → ``cs_map`` ``\old``→``\new`` 逐文件改写 → ``polyfill`` 注原始 TeX body。
    ``engines.{eng_name}`` 子表整体覆盖顶层同名词 (引擎差异修, 如 bbm→dsfont)。
    payload 不在表 → False 落 undefined_cs_guess。
    """
    table = dict(_CS_FIX_TABLE)
    table.update(params.get("cs_table") or {})
    cs = (payload or "").lstrip("\\")
    base = table.get(cs)
    if not base:
        return False, f"{payload} not in cs-fix table"
    spec = {k: v for k, v in base.items() if k != "engines"}
    spec.update((base.get("engines") or {}).get(ctx.engine_name) or {})
    done: list[str] = []
    if strip := spec.get("strip_pkg"):
        n = _map_tex_files(
            ctx,
            (".tex", ".sty", ".cls"),
            lambda t: _drop_pkg_loads(t, str(strip)),
        )
        if n:
            done.append(f"strip \\usepackage{{{strip}}} x{n}")
    if use := spec.get("usepackage"):
        done.extend(_ensure_usepackage(ctx, eng, str(use)))
    if cmap := spec.get("cs_map"):
        n = _map_tex_files(ctx, (".tex", ".sty"), lambda t: _rewrite_cs_map(t, cmap))
        if n:
            done.append(f"cs_map in {n} files")
    if spec.get("polyfill") and _inject_after_docclass(ctx, str(spec["polyfill"])):
        done.append("polyfill injected")
    if not done:
        return False, f"cs-fix spec for {cs} applied nothing"
    return True, "; ".join(done)


def journal_cs_polyfill(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""期刊缩写宏 polyfill: payload cs 命中表 → 全表 ``\providecommand`` 注入主文件。

    一次注入整表而非单宏 —— ``\bibitem`` 里期刊宏成串出现, 逐宏救火要打
    whack-a-mole 轮次; ``\providecommand`` 幂等, 重复注入无副作用。
    payload 未命中 → False 落到 undefined_cs_guess。
    """
    del eng
    table = dict(_JOURNAL_MACROS)
    table.update(params.get("macros") or {})
    cs = (payload or "").lstrip("\\")
    if cs not in table:
        return False, f"{payload} not a known journal macro"
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None:
        return False, "no main tex"
    block = "% fixloop: AAS journal-macro polyfills (类文件过老缺定义)\n" + "\n".join(
        rf"\providecommand{{\{name}}}{{{exp}}}" for name, exp in sorted(table.items())
    )
    m = _DOCCLASS_LINE_RE.search(t)
    at = m.end() if m else 0
    ctx.write(main, t[:at] + block + "\n" + t[at:])
    return True, f"journal-macro polyfill injected (\\{cs} 命中, 全表 {len(table)} 宏)"


def bundled_class_shadow(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""引擎 bundle 内建类太老 → wdir 注入同名 stub 遮蔽 (wdir 优先于 bundle)。

    实证: tectonic 内置 aastex 5.0rc3.1 (1999) 缺 ``\actaa``/deluxetable
    宏族 —— missing_file 永远打不到 (bundle 能解析), 只能 undefined_cs 确证后
    遮蔽换 emulateapj。``cs_set`` 命中 + ``include_journal_table`` 并集判
    payload; stub ``body`` 由 rules.yaml 提供 (版本串须日期开头, 见
    legacy_pkg_shim 注)。
    """
    cs = (payload or "").lstrip("\\")
    cs_set = {str(x).lstrip("\\") for x in params.get("cs_set") or []}
    if params.get("include_journal_table"):
        cs_set |= set(_JOURNAL_MACROS)
    target = params.get("target")
    body = params.get("body")
    if not cs or cs not in cs_set or not target or not body:
        return False, f"{payload} not in bundle-shadow set"
    missing = []
    for dep in params.get("needs") or []:
        if (
            ctx.wdir.joinpath(dep).is_file()
            or eng.probe_file(dep)
            or eng.install_file(dep)
        ):
            continue
        missing.append(dep)
    t = ctx.wdir / str(target)
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(body, encoding="utf-8")
    note = f"shadow {target} injected (\\{cs} missing from bundled class)"
    if missing:
        note += f"; deps still missing: {', '.join(missing)}"
    return True, note


def shim_pkgs_in_use(ctx: LoopCtx, shim_map: dict[str, Any]) -> list[str]:
    r"""工程源码里实际 ``\\usepackage`` 的 shim_map 键 (shim_known 条件实现)。"""
    blob = ctx.source_blob()
    return [
        pkg
        for pkg in shim_map
        if re.search(
            rf"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{{[^}}]*\b{re.escape(pkg)}\b",
            blob,
        )
    ]


def purge_corrupt_intermediates(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""删损坏的可再生中间件 (aux 族), 下遍引擎自动重生成 (2211.13013 同族)。

    XeTeX 写缓冲在 8192B 边界劈断多字节字符 → 自产 .aux/.toc 带非法
    UTF-8 → 下遍回读 "Invalid UTF-8 byte" + ``\@newl@bel`` EOF
    (docs/research/latex/2026-09-16-aux-cjk-truncation.md)。
    损坏谓词 = strict utf-8 解码失败 (字节劈断) 或末行不完整
    (边界恰好落在字符缝上时文件仍可解码但停在某宏参数中间——
    TeX 写出的完整行必以 \n 收尾)。健康件含 xr ``\externaldocument``
    外链 aux 一律保留; shipped 侧归 normalize 转码兜底, 本函数只管
    引擎自产件的运行时截断。
    """
    del eng, payload
    exts = {str(e).lower() for e in (params.get("exts") or INTERMEDIATE_SUFFIXES)}
    purged = []
    for f in sorted(ctx.wdir.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in exts:
            continue
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        try:
            raw.decode("utf-8")
            corrupt = not raw.endswith(b"\n")
        except UnicodeDecodeError:
            corrupt = True
        if not corrupt:
            continue
        f.unlink()
        ctx.invalidate(f)
        purged.append(str(f.relative_to(ctx.wdir)))
    return (bool(purged)), f"purged corrupt intermediates: {', '.join(purged)}"


TRANSFORM_FNS = {
    "option_clash_merge": option_clash_merge,
    "pdftex_prim_polyfill": pdftex_prim_polyfill,
    "vendored_shadow_isolate": vendored_shadow_isolate,
    "non_utf8_recode": non_utf8_recode,
    "bbl_stub_rewrite": bbl_stub_rewrite,
    "font_sub_shim": font_sub_shim,
    "pstricks_dvips_preflight": pstricks_dvips_preflight,
    "eps_to_pdf": eps_to_pdf,
    "legacy_pkg_shim": legacy_pkg_shim,
    "journal_cs_polyfill": journal_cs_polyfill,
    "bundled_class_shadow": bundled_class_shadow,
    "strip_inputenc": strip_inputenc,
    "cs_targeted_fix": cs_targeted_fix,
    "purge_corrupt_intermediates": purge_corrupt_intermediates,
}
