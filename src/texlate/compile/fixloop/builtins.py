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
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.inject import find_docclass_ends
from texlate.compile.normalize import INTERMEDIATE_SUFFIXES
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = ["REWRITE_FNS", "TRANSFORM_FNS"]

# pdfTeX 原语清单 (spike L284-298 + 2410.00012 实证扩: 文档面对象/注释/资源族)
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
    # 对象/表单/图像
    "pdfobj",
    "pdflastobj",
    "pdfrefobj",
    "pdfxform",
    "pdflastxform",
    "pdfrefxform",
    "pdfximage",
    "pdflastximage",
    "pdfrefximage",
    # 注释/链接/书签
    "pdfannot",
    "pdflastannot",
    "pdfdest",
    "pdflink",
    "pdfstartlink",
    "pdfendlink",
    "pdfoutline",
    "pdfcatalog",
    "pdfnames",
    # 文字流/页面资源
    "pdfliteral",
    "pdfcolorstack",
    "pdfcolorstackinit",
    "pdfsavepos",
    "pdfpageref",
    "pdfpageattr",
    "pdfpagesattr",
    "pdfpageresources",
    "pdfdraftmode",
    # 读取/工具原语
    "pdfescapestring",
    "pdfescapename",
    "pdfescapehex",
    "pdfunescapehex",
    "pdffilesize",
    "pdffilemoddate",
    "pdffiledump",
    "pdfmdfivesum",
    "pdfelapsedtime",
    "pdfresettimer",
    "pdfuniformdeviate",
    "pdfnormaldeviate",
    "pdfrandomseed",
    "pdfmatch",
    "pdflastmatch",
    "pdfstrcmp",
    "pdfprimitive",
    "pdfifprimitive",
    "pdfcreationdate",
    # 字体/微排/映射
    "pdffontname",
    "pdffontobjnum",
    "pdffontsize",
    "pdfincludechars",
    "pdfmapfile",
    "pdfmapline",
    "pdfglyphtounicode",
    "pdfgentounicode",
    "pdfadjustspacing",
    "pdfprotrudechars",
    "pdftracingfonts",
    "pdfdecimaldigits",
    "pdftexversion",
    "pdftexrevision",
    "pdfinclusionerrorlevel",
    "pdfsuppresswarningpagegroup",
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
    这类读取型需要原语已定义 (docs/08:268)。注入点恒在主文件头——
    cls/sty 内部读取发生在 ``\\documentclass`` 加载期间, 类行后注入太晚
    (2410.00012: ieeeaccess.cls:128 内 ``\\pdfobj``); ``ifdefined``
    前缀天然幂等。
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
    ctx.write(main, guard + " % fixloop polyfill\n" + t)
    return True, f"polyfill \\{prim} at file head"


def _provides_date(text: str) -> tuple[int, int, int] | None:
    m = _DATE_RE.search(text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _index_providers(eng: Engine, fname: str) -> list[str]:
    """``filemap`` + ``ctan_fetch.peek_index`` 查 ``fname`` 的 bundle/TL 提供包。

    只收 ``query`` 精确命中 —— ``suggest`` 前缀猜测面太宽, 不足以佐证
    撞名遮蔽。
    """
    pkgs = list(eng.filemap(fname))
    if not pkgs:
        fetcher = getattr(eng, "ctan_fetch", None)
        peek = getattr(fetcher, "peek_index", None)
        idx = peek() if callable(peek) else None
        if idx is not None:
            pkgs = idx.query(fname)
    return pkgs


def find_vendored_shadows(
    ctx: LoopCtx, eng: Engine, exts: tuple[str, ...]
) -> list[tuple[Path, tuple[int, int, int] | None, tuple[int, int, int] | None, str]]:
    r"""工程内 .sty/.cls 遮蔽候选 → ``(file, 本地日期, 系统日期, 提供方)``。

    xelatex: ``probe_file`` 命中系统副本且 ``\\ProvidesPackage``/``\\ProvidesClass``
    日期 ``ld < sd`` 确证才列 (盲删必死 —— 同目录 cls 可能是唯一来源)。
    tectonic: ``probe_file`` 无 cwd 恒 None —— 改查 filemap/tlpdb 索引,
    撞名被收录 (bundle/TL 有现行副本) 即列 ``sd=None`` advisory 级候选;
    bundle 内文件无日期面, 提供方记 ``bundle provides <pkg>``, 不走
    ``ld < sd`` 判据。
    """
    cands = []
    tectonic = ctx.engine_name == "tectonic"
    for f in ctx.tex_files(exts):
        resolved = eng.probe_file(f.name)
        if not resolved:
            if tectonic:
                pkgs = _index_providers(eng, f.name)
                if pkgs:
                    local_txt = ctx.read(f)
                    ld = _provides_date(local_txt) if local_txt else None
                    prov = f"bundle provides {', '.join(pkgs)}"
                    cands.append((f, ld, None, prov))
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
            cands.append((f, ld, sd, str(rp)))
    return cands


def vendored_shadow_isolate(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    """确证更旧的工程内 .sty/.cls → rename ``<f>.fixloop-iso`` 隔离 (docs/08:269)。

    ``sd=None`` 的 tectonic 索引候选是 advisory 级 —— 无日期面确证新旧,
    不 rename, 记 ``bundle provides <pkg>`` advisory (幂等去重)。
    """
    del payload
    exts = tuple(params.get("exts") or (".sty", ".cls"))
    suffix = str(params.get("suffix") or ".fixloop-iso")
    moved = []
    for f, ld, sd, prov in find_vendored_shadows(ctx, eng, exts):
        if sd is None:
            adv = f"{f.name}: {prov}——vendored 撞名未确证新旧, 保留"
            if adv not in ctx.advisories:
                ctx.advisories.append(adv)
            continue
        f.rename(f.with_name(f.name + suffix))
        moved.append(f"{f.name} ({ld} < {sd})")
    if not moved:
        return False, "无确证更旧的可隔离遮蔽"
    return True, f"isolate vendored: {', '.join(moved)}"


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


def bbl_regen(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Bundled 旧版 .bbl 撞新 biblatex → ``biber <stem>`` 就地重生成 (.bcf 在场)。

    实证根因 (2009.11064): e-print 捆绑 biber <3.3 格式 .bbl, TL biblatex 3.21
    拒载 —— ``\\sortlist`` undefined / ``File 'ms.bbl' is wrong format version``;
    .bcf+.bib 在场即 ``biber <stem>`` 重生成正确版本 .bbl (输出落 .bcf 同目录,
    嵌套亦直传 wdir 相对 stem)。biber 缺席 → run_tool rc≠0 fail-safe。
    """
    del eng, payload, params
    bcfs = sorted(ctx.wdir.rglob("*.bcf"))
    if not bcfs:
        return False, "no .bcf in project"
    done: list[str] = []
    failed: list[str] = []
    for bcf in bcfs:
        stem = str(bcf.relative_to(ctx.wdir).with_suffix(""))
        rc, _out, to = ctx.run_tool(["biber", stem], 60)
        if rc == 0 and not to:
            done.append(bcf.name)
            ctx.invalidate(bcf.with_suffix(".bbl"))
        else:
            failed.append(f"{bcf.name} rc={rc}{'/timeout' if to else ''}")
    if not done:
        return False, f"biber regen failed: {'; '.join(failed)}"
    note = f"biber regen: {', '.join(done)}"
    if failed:
        note += f"; failed: {'; '.join(failed)}"
    return True, note


#: ``\documentclass`` 选项表提取 —— 选项可缺省, 方括号内允跨行空白。
_DOCCLASS_OPTS_RE = re.compile(r"\\documentclass\s*(?:\[([^\]]*)\])?\s*\{")


def svjour_clo_stub(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""svjour.cls 零 .clo 伴船 → 按 ``\documentclass`` 选项写 ``sv<opt>.clo`` noop stub。

    实证根因 (0905.0193): e-print 捆绑 svjour.cls (2003, Springer) 但不带
    任何 .clo, TeX Live 亦不收录 svjour → ``\DeclareOption*`` 里
    ``\InputIfFileExists{sv\CurrentOption.clo}`` 逐选项落空,
    ``\journalopt`` 停在 ``\@empty`` → ``\ClassError{No valid journal
    specified}`` + ``\stop``。noop ``\endinput`` stub 让 InputIfFileExists
    走真臂置 ``\journalopt`` 为选项名即过; 盘上已有真 .clo 不覆盖。
    """
    del eng, payload, params
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None:
        return False, "no main tex"
    if not _DOCCLASS_OPTS_RE.search(t):
        return False, "no \\documentclass in main"
    opts = [
        o.strip()
        for m in _DOCCLASS_OPTS_RE.finditer(t)
        for o in (m.group(1) or "").split(",")
        if o.strip()
    ]
    if not opts:
        return False, "no documentclass options"
    written = []
    for opt in dict.fromkeys(opts):
        if "/" in opt or "\\" in opt:
            continue  # 防选项里的路径分隔符穿出 wdir / write_text 炸 OSError
        target = ctx.wdir / f"sv{opt}.clo"
        if target.exists():
            continue  # 盘上真 .clo 优先, 不覆盖
        ctx.write(target, "% fixloop: svjour option stub (noop)\n\\endinput\n")
        written.append(target.name)
    if not written:
        return False, "all sv*.clo already present, nothing written"
    return True, f"svjour .clo stubs written: {', '.join(written)}"


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


_EPS_EXTS = (".eps", ".ps", ".mps")
#: metapost 数字扩展名 ``.\d+`` —— ``diag1.1`` 实为 EPS (0806.4589 实证:
#: ps_image 只认 .eps/.ps 把它漏归 other), 与 _EPS_EXTS 并列进扫源面。
_NUMERIC_EXT_RE = re.compile(r"^\.\d+$")
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
            if new.startswith(old):
                # ``.\d+`` dst = 原名+".pdf": old 是 new 前缀, 裸 replace 二次
                # 触火会叠 suffix; 且 ``diag1.1`` 是 ``diag1.10`` 前缀 → 边界正则
                nt = re.sub(rf"(?<![\w.]){re.escape(old)}(?![\w.])", new, nt)
            elif old in nt:
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
    metapost 产物 ``diagN.M`` (``.\d+`` 扩展, 实为 EPS) 同扫 (0806.4589
    实证漏归 other) —— 其 dst 叠后缀 ``diagN.M.pdf`` 而非换后缀,
    避免 ``diag1.1``/``diag1.2`` 同塌 ``diag1.pdf`` 互踩。
    参考 texglot app/graphics.py (gs -dEPSCrop + 引用改写同款思路)。
    """
    del eng, payload  # 转换不触引擎原语; 全量转换不靠单点 payload
    epstopdf = shutil.which("epstopdf")
    gs = shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")
    if not epstopdf and not gs:
        return False, "no epstopdf/gs available"
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    sources = sorted(
        p
        for p in ctx.wdir.rglob("*")
        if p.is_file()
        and (p.suffix.lower() in _EPS_EXTS or _NUMERIC_EXT_RE.match(p.suffix))
    )
    if not sources:
        return False, "no .eps/.ps/.mps/.N in project"
    converted: dict[str, str] = {}  # "fig.eps" -> "fig.pdf" (basename 级)
    for src in sources:
        dst = (
            src.with_name(src.name + ".pdf")
            if _NUMERIC_EXT_RE.match(src.suffix)
            else src.with_suffix(".pdf")
        )
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
    shim_map = params.get("shim_map") or {}
    fname = payload or ""
    spec = shim_map.get(fname)
    if spec is None and not Path(fname).suffix:
        # `I can't find file `X'` 裸 payload (\input 系): 实体是 X.tex ——
        # shim 键与 stub 落点都用归一名 (epsf→epsf.tex 实证)。
        fname = f"{fname}.tex"
        spec = shim_map.get(fname)
    if not spec:
        return False, f"no legacy shim for {payload}"
    stub = spec.get("body")
    loads = spec.get("loads")
    if not stub and loads:
        stem = fname.rsplit(".", 1)[0]
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
    target = ctx.wdir / fname
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(stub, encoding="utf-8")
    note = f"stub {fname} injected"
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
    r"""主文件每个 ``\documentclass`` 缝后注入 snippet（幂等）。

    复用 inject.find_docclass_ends：分支选择形态（``\ifpdf A \else B \fi``
    双 docclass）逐缝注入——静态不判死活，活臂生效死臂随分支跳过；
    宏体/depth>0 命中与注释命中天然排除，跨行 ``[opt]{cls}``（revtex
    五选一注释穿插）落在配对 ``}`` 行尾而非首行尾。无 docclass 行则
    退文件头（``\AtBeginDocument`` 类 snippet 前定义也合法）。
    """
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None or snippet in t:
        return False
    hits = find_docclass_ends(t)
    if not hits:
        ctx.write(main, snippet + "\n" + t)
        return True
    out, delta = t, 0
    for pos, _ln, _cmd in hits:
        out = out[: pos + delta] + snippet + "\n" + out[pos + delta :]
        delta += len(snippet) + 1
    ctx.write(main, out)
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


#: cs_targeted_fix 的 glue-残骸前缀拆分默认头表 —— 只收语料实证过的
#: 粘连头 (n100 undefined_cs 24/24 均为 splice/join 合并残骸; ``in`` 头
#: 前缀面太热 (int/indent/input/index… 真宏云集), 留在 cs_table 显式条目)。
_SPLIT_HEADS: tuple[str, ...] = (
    "linebreak",
    "item",
    "nabla",
    "Delta",
    "hline",
    "frac",
    "par",
    "dd",
    "bf",
    "it",
    "rm",
)
#: 与头同前缀的真宏名守卫 —— 命中即不拆 (part/parbox/parskip 是 kernel
#: 命令; ddot/ddots 是 amsmath; itemize/fraction 同理)。残余门之外的双保险。
_SPLIT_GUARD: frozenset[str] = frozenset(
    {
        "part",
        "para",
        "parbox",
        "parskip",
        "itemize",
        "itemsep",
        "ddot",
        "ddots",
        "fraction",
    }
)
#: 拆分残余的长度门 (语料残余全 ≤4: FSU/Cd/i/and/r…; 更长残余的真宏名
#: 还有 guard 兜底)。
_SPLIT_REST_MAX = 4


def _split_glued_cs(cs: str, heads: Iterable[str], guard: Iterable[str]) -> str | None:
    """``cs`` = 已知粘连头 + 残余 → ``"head rest"``; 不可拆返回 None。

    残余门: 大写起首或 ≤_SPLIT_REST_MAX 字符; ``@`` 含名是包内私有 cs
    (版本偏斜类), 非粘连残骸, 不拆。
    """
    if "@" in cs or cs in guard:
        return None
    for head in sorted(heads, key=len, reverse=True):
        if not cs.startswith(head):
            continue
        rest = cs[len(head) :]
        if rest and (rest[0].isupper() or len(rest) <= _SPLIT_REST_MAX):
            return f"{head} {rest}"
    return None


def cs_targeted_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""undefined_cs 按 cs 修复表打靶 (handoff §2.2 cs→包表项)。

    spec 键组合序: ``strip_pkg`` 剥装载点 → ``usepackage`` 注入+装文件
    → ``cs_map`` ``\old``→``\new`` 逐文件改写 → ``polyfill`` 注原始 TeX body。
    ``engines.{eng_name}`` 子表整体覆盖顶层同名词 (引擎差异修, 如 bbm→dsfont)。
    payload 不在表 → 试 ``split_heads`` glue-残骸前缀拆分 (合成 cs_map 项);
    仍不中 → False 落 undefined_cs_guess。
    """
    table = dict(_CS_FIX_TABLE)
    table.update(params.get("cs_table") or {})
    cs = (payload or "").lstrip("\\")
    base = table.get(cs)
    if not base:
        split = _split_glued_cs(
            cs,
            params.get("split_heads") or _SPLIT_HEADS,
            params.get("split_guard") or _SPLIT_GUARD,
        )
        if split is None:
            return False, f"{payload} not in cs-fix table"
        base = {"cs_map": {cs: split}}
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
    r"""工程源码里实际引用的 shim_map 键 (shim_known 条件实现)。

    键可带扩展名 (install_file 系 map 形如 ``revtex4-1.cls``)——按 stem
    匹 ``\\usepackage``/``\\RequirePackage``/``\\documentclass``/``\\documentstyle``
    花括号名单, 否则 ``\\bspotcolor\\.sty\\b`` 对裸名 ``{spotcolor}`` 永不中。
    """
    blob = ctx.source_blob()
    hits = []
    for pkg in shim_map:
        stem = re.sub(r"\.(?:sty|cls|clo|tex|def|cfg)$", "", str(pkg))
        if re.search(
            rf"\\(?:usepackage|RequirePackage|documentclass|documentstyle)"
            rf"\s*(?:\[[^\]]*\])?\s*\{{[^}}]*\b{re.escape(stem)}\b",
            blob,
        ):
            hits.append(pkg)
    return hits


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


# ════════════════════════════════════════════════════════════════
# missing_char: log「Missing character」行 → 码位分级 → 按类修复 (F4)
# ════════════════════════════════════════════════════════════════

#: ``Missing character: There is no <what> (U+XXXX)? in font <font>``
#: xetex/tectonic spec 字体带 ``(U+XXXX)``; tfm 字体带 ``("XXXX)`` 十六进制
#: (``("8FD9)`` = U+8FD9「这」, 码位仍是 Unicode); pdftex 8-bit 给裸字符或
#: ``^^xx`` 记法。
_MISSING_CHAR_RE = re.compile(
    r"Missing character:\s*There is no (?P<what>.+?)"
    r"(?:\s*\((?P<cp>U\+[0-9A-Fa-f]+|\"[0-9A-Fa-f]+)\))?\s*in font\s+(?P<font>[^\s!;]+)"
)

#: ``^^xx``/``^^^xxxx`` TeX 记法码位提取。
_CARET_HEX_RE = re.compile(r"\^{2,3}([0-9a-fA-F]{2,4})")

#: xeCJK/ctex 支持探针 (source_contains 级) —— 有 CJK 机制才有绑定可预热。
_CJK_MECH_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\b[^\n%]*\{[^}]*\b(?:ctex|xeCJK|CJKutf8)\b"
    r"|\\(?:setCJK\w*font|CJKfontspec|ctexset|xeCJKsetup|newCJKfontfamily)\b"
)

#: 判定「字体本身即 CJK 字体」的排除模式 —— CJK 码位落在 CJK 字体里
#: 是真缺字形 (换字体的 warmup 救不了), 不属于绑定污染类。
_CJK_FONT_RE = re.compile(
    r"fandol|noto.*cjk|source.?han|uming|ukai|wqy|ipa(?:ex)?[mg]|"
    r"sim(?:sun|hei|kai|fang)|ms ?(?:gothic|mincho)|cjk",
    re.IGNORECASE,
)


def _mc_codepoint(what: str, cp: str | None) -> int | None:
    """``(U+XXXX)`` / ``("XXXX)`` / ``^^xx`` / 裸字符 → 码位; 不可判定 → None。"""
    if cp:
        return int(cp[2:] if cp.startswith("U+") else cp[1:], 16)
    if m := _CARET_HEX_RE.fullmatch(what.strip()):
        return int(m.group(1), 16)
    if len(what) == 1:
        return ord(what)
    return None


def _compile_log_text(ctx: LoopCtx) -> str:
    """定位本轮编译 log。

    ``{stem}.log`` (xelatex) → ``_tect_out/{stem}.log`` (tectonic)
    → 任一含 Missing character 的 ``*.log`` (兜底)。
    """
    main = ctx.main_path()
    cands: list[Path] = []
    if main is not None:
        stem = main.stem
        cands += [ctx.wdir / f"{stem}.log", ctx.wdir / "_tect_out" / f"{stem}.log"]
    for p in cands:
        t = ctx.read(p) if p.is_file() else None
        if t and "Missing character" in t:
            return t
    for p in sorted(ctx.wdir.rglob("*.log")):
        t = ctx.read(p)
        if t and "Missing character" in t:
            return t
    return ""


#: missing_char 修复默认表 (seeded 自 n100 缺字签名, 2026-09-16;
#: ``params.char_table`` 同形条目按 id 覆盖/扩列 —— 首匹配生效)。
#: 每条目: ``id``; 匹配面 ``cps:[int]`` | ``ranges:[[lo,hi],...]``,
#: ``font``/``font_not`` 为作用在日志字体名上的正则; 动作:
#: ``action: cjk_warmup`` (预热 xeCJK 字体绑定) 或 ``replace: "<TeX串>"``。
_MC_TABLE: list[dict[str, Any]] = [
    {
        "id": "cjk_glyph",
        # CJK 统一表意+假名+谚文+兼容/全角区 —— 落在非 CJK 字体 = xeCJK
        # (本表是 textutil.CJK_RANGES 的语义超集: 缺字判定要罩住假名/谚文/
        # 彝文/全角, 勿向 CJK_RANGES 单源回退)
        # 绑定被污染 (elsart 族 \no@harm 下 \protect=\noexpand 使
        # \fontfamily/\selectfont 失效, 首用把 xeCJK/<fam>/<ser>/<sh>/<size>
        # 全局绑到 lmroman —— /tmp/mc-repro 实证), 预热即可。
        "ranges": [
            [0x2E80, 0x303F],
            [0x3040, 0x30FF],
            [0x3100, 0x31EF],
            [0x3200, 0x33FF],
            [0x3400, 0x4DBF],
            [0x4E00, 0x9FFF],
            [0xA000, 0xA4CF],
            [0xAC00, 0xD7AF],
            [0xF900, 0xFAFF],
            [0xFE30, 0xFE4F],
            [0xFF00, 0xFFEF],
            [0x20000, 0x2FA1F],
        ],
        "font_not": _CJK_FONT_RE.pattern,
        # 仅 spec 字体 ([lmroman10]:mapping=tex-text 形) 缺 CJK 才预热——
        # tfm 字体 (cmr10/ec-lmss12) 缺 CJK 大头是数学模式 (xeCJK
        # interchartoks 水平列机制不进数学, warmup 白烧到 stuck;
        # scout-misschar 2026-09-16 实证), 数学面已由 inject 侧
        # \Umathcode 符号字体兜底 (CJK_MATH_FALLBACK) 治。
        "font": r"[\[:]",
        "action": "cjk_warmup",
    },
    # n100: 0806.1079 ×3 ≠ in cmr7/cmr5
    {"id": "neq", "cps": [0x2260], "replace": "\\ensuremath{\\neq}"},
    # n100: 1608.02516 ×1 − in cmr10
    {"id": "minus", "cps": [0x2212], "replace": "\\ensuremath{-}"},
    # n100: 2403.15096 ×1 § in cmr10
    {"id": "section", "cps": [0x00A7], "replace": "\\S"},
    # n100: 1003.1464 ×1 ø in cmmi8 (math italic → \mbox 包文本字形)
    {"id": "oslash", "cps": [0x00F8], "replace": "\\mbox{\\o}"},
    # n100: 0707.3950 è in cmex10
    {"id": "egrave", "cps": [0x00E8], "replace": "\\mbox{\\`{e}}"},
]

#: cjk_warmup 注入的绑定预热盒: 每 ``{尺寸/系列 中}`` 组把
#: ``xeCJK/<fam>/<ser>/<sh>/<size>`` 在干净上下文先绑到真 CJK 字体,
#: 之后 \no@harm 测量盒再遇同型直接复用既有绑定, 不再污染。
_MC_WARMUP_SIZES = (
    "\\normalsize 中",
    "\\small 中",
    "\\footnotesize 中",
    "\\large 中",
    "\\Large\\bfseries 中",
    "\\bfseries 中",
    "\\itshape 中",
)


def _mc_table(params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """内置表 + ``params.char_table`` 按 id 合并 (参数条目同 id 覆盖)。"""
    table = {e["id"]: e for e in _MC_TABLE}
    for e in params.get("char_table") or []:
        table[e["id"]] = e
    return table


def _mc_hit(entry: dict[str, Any], cp: int, font: str) -> bool:
    """码位+字体 vs 条目匹配面 (cps/ranges 与 font/font_not 正则)。"""
    if (fno := entry.get("font_not")) and re.search(fno, font, re.IGNORECASE):
        return False
    if (fyes := entry.get("font")) and not re.search(fyes, font, re.IGNORECASE):
        return False
    if cp in (entry.get("cps") or ()):
        return True
    return any(lo <= cp <= hi for lo, hi in entry.get("ranges") or ())


def missing_char_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Missing character`` 缺字 → 字符类分诊修复 (F4, 表驱动可扩)。

    CJK 类码位落在非 CJK 字体 = xeCJK 逐 (family,series,shape,size) 的字体
    绑定被 ``\no@harm`` 式上下文污染 (elsart ``\proc@elem`` 测量盒实证:
    \protect 被重定义后 \fontfamily/\selectfont 变 no-op, 首用绑定落
    lmroman 且 ``\cs_gset_eq`` 全局不可回) → 注入 ``\AtBeginDocument`` 预热
    盒先在干净上下文绑好常用 size。非 CJK 缺字走 ``replace`` 字面替换
    (≠→\neq 等)。表在 ``params.char_table`` 可按 id 覆盖扩列。
    """
    del eng, payload
    log = _compile_log_text(ctx)
    if not log:
        return False, "no compile log with Missing character found"
    seen = _mc_parse_log(log)
    if not seen:
        return False, "Missing character lines present but no codepoint parsed"
    warm, repl, unmatched = _mc_plan(seen, _mc_table(params))

    applied: list[str] = []
    notes: list[str] = []
    if warm:
        ok, note = _mc_apply_warmup(ctx)
        (applied if ok else notes).append(note)
    if repl:
        n = _map_tex_files(
            ctx,
            tuple(params.get("exts") or (".tex",)),
            lambda t: _sub_literal_chars(t, repl),
        )
        if n:
            applied.append(f"replaced {len(repl)} char kinds in {n} file(s)")
    if not applied:
        if unmatched:
            notes.append(f"{unmatched} codepoint(s) unmatched by char_table")
        return False, "; ".join(notes) or "no actionable missing chars"
    return True, "; ".join(applied + notes)


def _mc_parse_log(log: str) -> dict[int, tuple[str, str]]:
    """``Missing character`` 行 → {码位: (原字面, 字体名)} 去重。"""
    seen: dict[int, tuple[str, str]] = {}
    for m in _MISSING_CHAR_RE.finditer(log):
        cp = _mc_codepoint(m.group("what"), m.group("cp"))
        if cp is not None and cp not in seen:
            seen[cp] = (m.group("what"), m.group("font").rstrip(".,;"))
    return seen


def _mc_plan(
    seen: dict[int, tuple[str, str]], table: dict[str, dict[str, Any]]
) -> tuple[bool, dict[str, str], int]:
    """逐缺字码位查表 → (是否需 CJK 预热, 字面替换映射, 未匹配数)。"""
    warm = False
    repl: dict[str, str] = {}
    unmatched = 0
    for cp, (what, font) in seen.items():
        entry = next((e for e in table.values() if _mc_hit(e, cp, font)), None)
        if entry is None:
            unmatched += 1
        elif entry.get("action") == "cjk_warmup":
            warm = True
        elif rep := entry.get("replace"):
            ch = what if len(what) == 1 else _mc_chr(cp)
            if ch:
                repl[ch] = rep
    return warm, repl, unmatched


def _mc_chr(cp: int) -> str | None:
    """码位 → 字符; 超出 Unicode 面 → None。"""
    try:
        return chr(cp)
    except ValueError:
        return None


def _mc_apply_warmup(ctx: LoopCtx) -> tuple[bool, str]:
    r"""``\AtBeginDocument`` 预热盒注入 —— 仅当源里有 ctex/xeCJK 机制。"""
    box = "\\setbox0=\\hbox{" + "".join(f"{{{s}}}" for s in _MC_WARMUP_SIZES) + "}"
    snippet = f"\\AtBeginDocument{{{box}}} % fixloop: xeCJK bind warmup"
    if not _CJK_MECH_RE.search(ctx.source_blob()):
        return False, "cjk drops but no ctex/xeCJK in source — warmup skipped"
    if _inject_after_docclass(ctx, snippet):
        return True, "injected CJK font-binding warmup"
    return False, "warmup snippet already present"


#: font_fallback 默认覆盖带 (scout-misschar 2026-09-16: 西里尔人名真损失
#: U+0400-04FF / 组合符 U+0300-036F / 拉丁扩展 U+00C0-017F)。
#: ``params.fallback_ranges`` 覆盖带表、``params.fallback_font`` 换字体。
_FB_RANGES: tuple[tuple[int, int], ...] = (
    (0x0400, 0x04FF),
    (0x0300, 0x036F),
    (0x00C0, 0x017F),
)
_FB_FONT = "Libertinus Serif"  # TL libertinus-fonts, 三带全覆盖实证


def font_fallback(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""非 CJK 缺字 (西里尔/拉丁扩展/组合符) → ``newunicodechar`` 换字体兜底。

    ``\newunicodechar{X}{{\txlatefallback X}}`` 逐缺字声明：替换体里同字面
    的 X 在 ``\newunicodechar`` 激活该字符前已按 letter catcode  token 化，
    故无自递归 (newunicodechar 的 ``\protected`` 定义也使 label/cite 键名
    内同字符不展开)。主字体本就缺这些带时才见缺字——逐字回退不伤排版。
    已由 char_table ``replace`` 条目覆盖的码位 (ø/è 等) 让位字面替换。
    """
    del payload
    log = _compile_log_text(ctx)
    if not log:
        return False, "no compile log with Missing character found"
    seen = _mc_parse_log(log)
    bands = params.get("fallback_ranges") or _FB_RANGES
    taken = {
        cp
        for cp, (what, font) in seen.items()
        for e in _mc_table(params).values()
        if e.get("replace") and _mc_hit(e, cp, font)
    }
    chars = [
        cp for cp in seen if cp not in taken and any(lo <= cp <= hi for lo, hi in bands)
    ]
    if not chars:
        return False, "no missing chars in fallback bands"
    if not eng.probe_file("newunicodechar.sty") and not eng.install_file(
        "newunicodechar.sty"
    ):
        return False, "newunicodechar.sty unavailable"
    font = str(params.get("fallback_font") or _FB_FONT)
    lines = [
        "% fixloop: per-char font fallback via newunicodechar",
        "\\usepackage{newunicodechar}",
        "\\ifdefined\\newfontfamily\\else\\usepackage{fontspec}\\fi",
        f"\\newfontfamily\\txlatefallback{{{font}}}",
    ]
    lines += (
        f"\\newunicodechar{{{c}}}{{{{\\txlatefallback {c}}}}}"
        for cp in chars
        if (c := _mc_chr(cp)) is not None
    )
    if _inject_after_docclass(ctx, "\n".join(lines)):
        return True, f"font_fallback: {len(chars)} char(s) -> {font}"
    return False, "fallback snippet already present"


def _sub_literal_chars(t: str, repl: dict[str, str]) -> tuple[str, int]:
    r"""字面字符 → TeX 命令串逐替换 → (新文本, 替换数)。

    替换域限正文: ``mask_tex`` 等长遮盖视图把 verbatim 族环境体 / comment
    失活环境 / ``\\verb``/``\\lstinline`` / ``%`` 注释抹成空格——在遮盖
    视图上取命中 offset 回原文回放, 代码清单与注释里的同码位字面量不被
    腐蚀成 ``\\ensuremath{...}`` 串 (audit-2026-09-16)。
    """
    masked = mask_tex(t)
    hits: list[tuple[int, str]] = []
    for ch, to in repl.items():
        start = 0
        while (i := masked.find(ch, start)) >= 0:
            if t[i] == ch:  # 同码位恰落在遮盖位 (' '/'\\n') 时守卫
                hits.append((i, to))
            start = i + 1
    if not hits:
        return t, 0
    hits.sort()
    out: list[str] = []
    prev = 0
    for i, to in hits:
        out.append(t[prev:i])
        out.append(to)
        prev = i + 1
    out.append(t[prev:])
    return "".join(out), len(hits)


# ════════════════════════════════════════════════════════════════
# missing_graphic: 缺图 ci 改名 + 坏图分级修复
# (signature-mining 2026-09-16 top5#2: 2403.15102/2211.04457 大小写不符,
#  1502.06541/1012.5273 在盘拒载)
# ════════════════════════════════════════════════════════════════

#: graphicx 可装载图形扩展名面 —— 无扩展名 ``\includegraphics{x}`` 的
#: ci 补全候选域 (与 _EPS_EXTS 分工: 那边管 PS 族转换, 这边管全图形族匹配)。
_GRAPHIC_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ps", ".mps")

#: ``\includegraphics`` 引用点: g1=可选 opts, g2=图像参数 (星号变体同收)。
_INCLUDE_GFX_RE = re.compile(
    r"\\includegraphics\*?\s*(?:\[([^\]\n]*)\])?\s*\{([^}]*)\}"
)


def _norm_graphic_name(name: str) -> str:
    r"""Log payload / ``\includegraphics`` 参数 → 规整 posix 相对路径。"""
    n = name.strip().strip("'\"")
    n = n.replace("\\", "/")
    while n.startswith("./"):
        n = n[2:]
    return n


def _find_graphic_ci(ctx: LoopCtx, want: str) -> Path | None:
    r"""工程目录内大小写不敏感找图真身。

    命中序: 相对路径整串 ci 相等 / 文件名 ci 相等 (rank0) → want 无扩展名时
    stem ci 相等且扩展名在图形族面 (rank1, ``.\d+`` 数字扩展同收);
    多命中取 rank 低 + 相对路径短者 (确定性排序)。
    """
    want = _norm_graphic_name(want)
    if not want:
        return None
    wl = want.lower()
    base = PurePosixPath(wl).name
    stemless = "." not in base
    cands: list[tuple[int, int, str, Path]] = []
    for p in ctx.wdir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ctx.wdir).as_posix().lower()
        if rel == wl or p.name.lower() == base:
            rank = 0
        elif (
            stemless
            and p.stem.lower() == base
            and (p.suffix.lower() in _GRAPHIC_EXTS or _NUMERIC_EXT_RE.match(p.suffix))
        ):
            rank = 1
        else:
            continue
        cands.append((rank, len(rel), str(p), p))
    if not cands:
        return None
    return min(cands, key=lambda t: t[:3])[3]


def _graphic_ref_hit(arg: str, want: str) -> bool:
    r"""``\includegraphics`` 参数 arg 是否指向 payload want (全 ci)。

    相等判定: 全路径 / basename / 无扩展名侧对侧 stem (``{fig}`` ↔
    ``fig.pdf`` 双向) —— 覆盖 ``{sf_08_VX}`` vs ``img/sf_08_VX.pdf`` 各形。
    """
    a = _norm_graphic_name(arg).lower()
    w = _norm_graphic_name(want).lower()
    if not a or not w:
        return False
    if a == w:
        return True
    ap, wp = PurePosixPath(a), PurePosixPath(w)
    if ap.name == wp.name:
        return True
    if "." not in ap.name and ap.name == wp.stem:
        return True
    return "." not in wp.name and ap.stem == wp.name


def _rewrite_case_refs(ctx: LoopCtx, exts: tuple[str, ...], want: str, rel: str) -> int:
    r"""逐 tex 文件: 指 want 且本不可解析的 ``\includegraphics`` 参数改写 rel。

    ``(wdir|filedir)/arg`` 已命中文件的引用是别人的好引用 —— 不动;
    该守卫同时保证二次触火幂等 (改写后 arg 恰可解析 → 不再命中改写条件)。
    """
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "\\includegraphics" not in t:
            continue

        def _sub(m: re.Match[str], _f: Path = f) -> str:
            arg = m.group(2)
            if not _graphic_ref_hit(arg, want):
                return m.group(0)
            a = _norm_graphic_name(arg)
            if (ctx.wdir / a).is_file() or (_f.parent / a).is_file():
                return m.group(0)
            return (
                m.group(0)[: m.start(2) - m.start()]
                + rel
                + m.group(0)[m.end(2) - m.start() :]
            )

        nt = _INCLUDE_GFX_RE.sub(_sub, t)
        if nt != t:
            ctx.write(f, nt)
            changed += 1
    return changed


def graphic_case_link(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""大小写不符型 missing_graphic: ci 找真身 → ``\includegraphics`` 参数改写真名。

    实证: e-print 跨平台搬运后 ``{img/sf_08_VX.pdf}`` vs 盘上
    ``img/SF_08_VX.pdf`` 在 Linux 敏感 FS 挂 (2403.15102/2211.04457)。
    改写参数而非建 symlink —— 改写随工程走可移植, 不依赖 FS/平台语义。
    """
    del eng
    want = _norm_graphic_name(payload or "")
    if not want:
        return False, "no graphic payload"
    if (ctx.wdir / want).is_file():
        return False, f"{want} resolves verbatim — not a case mismatch"
    real = _find_graphic_ci(ctx, want)
    if real is None:
        return False, f"no case-variant of {want} in project"
    rel = real.relative_to(ctx.wdir).as_posix()
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    changed = _rewrite_case_refs(ctx, exts, want, rel)
    if not changed:
        return False, f"{want} -> {rel} resolved but no \\includegraphics ref rewrote"
    return True, f"case-link {want} -> {rel}: rewrote refs in {changed} file(s)"


def _opt_dim(opts: str | None, key: str) -> str | None:
    r"""Opts 串里 ``key=<dim>`` 提取 (graphicx ``width=2in`` → ``2in``)。"""
    if not opts:
        return None
    m = re.search(rf"(?:^|,)\s*{key}\s*=\s*([^,\]]+)", opts)
    return m.group(1).strip() if m else None


def _stub_graphic_refs(ctx: LoopCtx, f: Path, want: str, params: dict[str, Any]) -> int:
    r"""指向坏图的 ``\includegraphics`` → ``\fbox{\rule{0pt}{H}\rule{W}{0pt}}``.

    W/H 取 opts 的 ``width=``/``height=`` 保版式尺寸; 缺省
    ``params.stub_width``/``stub_height`` 再缺省 ``0.6/0.45\linewidth``。
    arg 命中 payload / 真身 basename / 真身相对路径任一即改 → 改写文件数。
    """
    w_d = str(params.get("stub_width") or r"0.6\linewidth")
    h_d = str(params.get("stub_height") or r"0.45\linewidth")
    names = {want, f.name, f.relative_to(ctx.wdir).as_posix()}
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    changed = 0
    for tf in ctx.tex_files(exts):
        t = ctx.read(tf)
        if t is None or "\\includegraphics" not in t:
            continue

        def _sub(m: re.Match[str]) -> str:
            if not any(_graphic_ref_hit(m.group(2), n) for n in names):
                return m.group(0)
            w = _opt_dim(m.group(1), "width") or w_d
            h = _opt_dim(m.group(1), "height") or h_d
            box = rf"\fbox{{\rule{{0pt}}{{{h}}}\rule{{{w}}}{{0pt}}}}"
            return f"{box}% fixloop: stub for unreadable {f.name}"

        nt = _INCLUDE_GFX_RE.sub(_sub, t)
        if nt != t:
            ctx.write(tf, nt)
            changed += 1
    return changed


def _try_gs_redistill(ctx: LoopCtx, f: Path, marker: Path) -> str | None:
    r"""``gs -sDEVICE=pdfwrite`` 重蒸馏 f 就地覆盖 → None 成功 / 失败原因串。

    原件拷为 marker (备份兼「已蒸馏」标记); 失败残留 ``.fixloop-tmp`` 清掉,
    防半文件被当成产物 (``_convert_one`` 同款纪律)。
    """
    gs = shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")
    if gs is None:
        return "no gs"
    tmp = f.with_name(f.name + ".fixloop-tmp")
    rc, _out, to = ctx.run_tool(
        [
            gs,
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=pdfwrite",
            "-o",
            str(tmp),
            str(f),
        ],
        timeout=90,
    )
    if rc != 0 or to or not tmp.is_file() or not tmp.stat().st_size:
        tmp.unlink(missing_ok=True)
        return f"gs failed rc={rc}{'/timeout' if to else ''}"
    shutil.copy2(f, marker)
    tmp.replace(f)
    ctx.invalidate(f)
    return None


def graphic_repair(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""在盘但引擎拒载的 graphic: gs 重蒸馏 → 降级 ``\fbox`` 占位框 (分级修复)。

    实证: 1502.06541 figDY.pdf 合法但双引擎拒载; 1012.5273 zeromode.pdf
    经 eps_to_pdf 转换后仍拒载。分级序 —— ``.pdf`` 且未蒸馏过先
    ``gs -sDEVICE=pdfwrite`` 重蒸馏就地覆盖 (原件留 ``<name>.fixloop-rd``
    旁记 = 备份兼「已蒸馏」标记); ``params.force_stub`` / marker 已存在 /
    非 pdf / 无 gs / 蒸馏失败 → ``\includegraphics`` 改写 ``\fbox`` 占位框
    (尺寸见 _stub_graphic_refs)。蒸馏成功仍拒载的残案靠规则序兜底:
    下一轮同 payload 走第二条规则再入本函数, marker 短路直落 stub。
    """
    del eng
    want = _norm_graphic_name(payload or "")
    if not want:
        return False, "no graphic payload"
    f = ctx.wdir / want
    if not f.is_file():
        f = _find_graphic_ci(ctx, want) or f
    if not f.is_file():
        return False, f"{want} not found in project"
    marker = f.with_name(f.name + ".fixloop-rd")
    why = (
        "force_stub"
        if params.get("force_stub")
        else "already redistilled"
        if marker.exists()
        else f"non-pdf {f.suffix or '(no ext)'}"
        if f.suffix.lower() != ".pdf"
        else _try_gs_redistill(ctx, f, marker)
    )
    if why is None:
        return True, f"gs redistilled {f.name} (orig -> {marker.name})"
    n = _stub_graphic_refs(ctx, f, want, params)
    if not n:
        return (
            False,
            f"{f.name} unreadable ({why}) but no \\includegraphics ref to stub",
        )
    return True, f"stub \\fbox for {f.name} ({why}) in {n} file(s)"


TRANSFORM_FNS = {
    "option_clash_merge": option_clash_merge,
    "pdftex_prim_polyfill": pdftex_prim_polyfill,
    "vendored_shadow_isolate": vendored_shadow_isolate,
    "non_utf8_recode": non_utf8_recode,
    "bbl_stub_rewrite": bbl_stub_rewrite,
    "bbl_regen": bbl_regen,
    "svjour_clo_stub": svjour_clo_stub,
    "font_sub_shim": font_sub_shim,
    "pstricks_dvips_preflight": pstricks_dvips_preflight,
    "eps_to_pdf": eps_to_pdf,
    "legacy_pkg_shim": legacy_pkg_shim,
    "journal_cs_polyfill": journal_cs_polyfill,
    "bundled_class_shadow": bundled_class_shadow,
    "strip_inputenc": strip_inputenc,
    "cs_targeted_fix": cs_targeted_fix,
    "purge_corrupt_intermediates": purge_corrupt_intermediates,
    "missing_char_fix": missing_char_fix,
    "font_fallback": font_fallback,
    "graphic_case_link": graphic_case_link,
    "graphic_repair": graphic_repair,
}
