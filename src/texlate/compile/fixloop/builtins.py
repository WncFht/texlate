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
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
        nt = pat.sub(f"\\input{{{target.name}}}", t, count=1)
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
                nt = re.sub(rf"\\{old_cs}\b", f"\\{new_cs}", nt)
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


TRANSFORM_FNS = {
    "option_clash_merge": option_clash_merge,
    "pdftex_prim_polyfill": pdftex_prim_polyfill,
    "vendored_shadow_isolate": vendored_shadow_isolate,
    "non_utf8_recode": non_utf8_recode,
    "bbl_stub_rewrite": bbl_stub_rewrite,
    "font_sub_shim": font_sub_shim,
    "pstricks_dvips_preflight": pstricks_dvips_preflight,
}
