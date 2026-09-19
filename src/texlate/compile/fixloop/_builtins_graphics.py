r"""_builtins_graphics — 图形/EPS/SVG 域修复原语 (C3 拆分收尾叶子)。

pstricks/dvips 路由预检 / ``.eps``→``.pdf`` 全量转换 (epstopdf 优先, gs
-dEPSCrop 兜底) / missing_graphic 大小写改名 + 坏图分级修复 /
``\includepdf`` 缺件占位 / svg 包编译准备 (inkscape flag 臂或离线转换臂)。

monkeypatch 锚点迁移: ``_run_convert`` 的 patch 面随调用链落在本模块
——测试请 ``monkeypatch.setattr(_builtins_graphics, "_run_convert", ...)``;
builtins.py 门面的同名回引只是再导出, patch 它不生效。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import _live_matches
from texlate.textutil import mask_tex, safe_is_file

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


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


_EPS_EXTS = (
    ".eps",
    ".epsf",
    ".epsi",
    ".mps",
    ".ps",
)  # 与 normalize.PS_GRAPHIC_SUFFIXES 同步
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
#: 词表对 ``textutil.LOADER_CMDS`` 不机械换指: 本正则只接 ``[opts]{name}``
#: 前位选项形——``*WithOptions`` 两枚是 ``{name}[opts]`` 后位形、
#: ``PassOptionsTo*`` 是 ``{opts}{name}`` 花括号形, 结构上永不吃本正则;
#: ``documentclass``/``documentstyle`` 属 ``DOCCLASS_NAMES`` 声明族不在
#: LOADER 集。故本站词表 = LOADER∩[opts]{name}形 ∪ DOCCLASS_NAMES 手写投影。
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

    # 遮盖视图定位、原文改写——注释内装载点是死文本，不动不数
    out: list[str] = []
    prev = 0
    for m in _live_matches(_LOAD_OPT_RE, t):
        out.append(t[prev : m.start()])
        out.append(_sub(m))
        prev = m.end()
    out.append(t[prev:])
    return "".join(out), n


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


# ════════════════════════════════════════════════════════════════
# missing_graphic: 缺图 ci 改名 + 坏图分级修复
# (signature-mining 2026-09-16 top5#2: 2403.15102/2211.04457 大小写不符,
#  1502.06541/1012.5273 在盘拒载)
# ════════════════════════════════════════════════════════════════

#: graphicx 可装载图形扩展名面 —— 无扩展名 ``\includegraphics{x}`` 的
#: ci 补全候选域 (与 _EPS_EXTS 分工: 那边管 PS 族转换, 这边管全图形族匹配)。
_GRAPHIC_EXTS = (
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".eps",
    ".epsf",
    ".epsi",
    ".ps",
    ".mps",
)

#: ``\includegraphics`` 引用点: g1=可选 opts, g2=图像参数 (星号变体同收)。
_INCLUDE_GFX_RE = re.compile(
    r"\\includegraphics\*?\s*(?:\[([^\]\n]*)\])?\s*\{([^}]*)\}"
)

#: ``\includepdf[opts]{file}`` (pdfpages) 引用点 —— W66 孤儿裁决面:
#: 与 ``_INCLUDE_GFX_RE`` 分正则而非并表 —— graphic_repair 的 ``\fbox``
#: stub 语义只适用图像件, includepdf 缺件占位是 ``\clearpage\null``。
_INCLUDE_PDF_RE = re.compile(
    r"\\includepdf(?![a-zA-Z])\s*(?:\[([^\]\n]*)\])?\s*\{([^}]*)\}"
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
    r"""逐 tex 文件: 指 want 且本不可解析的 ``\includegraphics``/``\includepdf`` 参数改写 rel。

    ``(wdir|filedir)/arg`` 已命中文件的引用是别人的好引用 —— 不动;
    该守卫同时保证二次触火幂等 (改写后 arg 恰可解析 → 不再命中改写条件)。
    W66 扩面: ``\includepdf`` 与 ``\includegraphics`` 共享 ci-glob 命中面。
    """
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or ("\\includegraphics" not in t and "\\includepdf" not in t):
            continue

        def _sub(m: re.Match[str], _f: Path = f) -> str:
            arg = m.group(2)
            if not _graphic_ref_hit(arg, want):
                return m.group(0)
            a = _norm_graphic_name(arg)
            if safe_is_file(ctx.wdir / a) or safe_is_file(_f.parent / a):
                return m.group(0)
            return (
                m.group(0)[: m.start(2) - m.start()]
                + rel
                + m.group(0)[m.end(2) - m.start() :]
            )

        nt = _INCLUDE_GFX_RE.sub(_sub, t)
        nt = _INCLUDE_PDF_RE.sub(_sub, nt)
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
    if safe_is_file(ctx.wdir / want):
        return False, f"{want} resolves verbatim — not a case mismatch"
    real = _find_graphic_ci(ctx, want)
    if real is None:
        return False, f"no case-variant of {want} in project"
    rel = real.relative_to(ctx.wdir).as_posix()
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    changed = _rewrite_case_refs(ctx, exts, want, rel)
    if not changed:
        return False, f"{want} -> {rel} resolved but no ref rewrote"
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
    if not safe_is_file(f):
        f = _find_graphic_ci(ctx, want) or f
    if not safe_is_file(f):
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


# ════════════════════════════════════════════════════════════════
# \includepdf 缺件占位 (W66 孤儿裁决 mechmap-2026-09-17) +
# svg 包编译准备 (W31 孤儿裁决)
# ════════════════════════════════════════════════════════════════


def includepdf_missing_stub(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``\includepdf`` 缺件 → 整调用改写 ``\clearpage\null`` 占位 (W66)。

    翻译管线对 includepdf 区整体跳过 (机制裁决定调), 编译侧同语义 stub:
    空页保分页位, 页面数失真可接受。命中判定复用 ``_graphic_ref_hit``
    (全路径/basename/stem 三口径 ci); ``(wdir|filedir)/arg`` 本可解析的
    引用不动 (``_rewrite_case_refs`` 同款守卫 + 二次触火幂等)。
    """
    del eng
    want = _norm_graphic_name(payload or "")
    if not want:
        return False, "no includepdf payload"
    changed = 0
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "\\includepdf" not in t:
            continue
        out: list[str] = []
        prev = 0
        n = 0
        for m in _live_matches(_INCLUDE_PDF_RE, t):
            arg = m.group(2)
            if not _graphic_ref_hit(arg, want):
                continue
            a = _norm_graphic_name(arg)
            if safe_is_file(ctx.wdir / a) or safe_is_file(f.parent / a):
                continue  # 引用本可解析 → 非本 payload 病灶
            out.append(t[prev : m.start()])
            # 前缀注释形: match 落行中时 % 只吞自身到新行, 不啃原文尾部
            out.append(f"% fixloop: \\includepdf stub for {a}\n\\clearpage\\null")
            prev = m.end()
            n += 1
        if not n:
            continue
        out.append(t[prev:])
        ctx.write(f, "".join(out))
        changed += 1
    if not changed:
        return False, f"no live \\includepdf ref to {want}"
    return True, f"\\includepdf{{{want}}} -> \\clearpage\\null in {changed} file(s)"


# ═══ svg 域 (W31): \includesvg 的 inkscape/shell-escape 链 ═══

#: svg 包装载点/``\includesvg`` 使用点 (遮盖视图评估)。
_SVG_PKG_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{[^}]*?\bsvg\b"
)
_INCLUDESVG_RE = re.compile(
    r"\\includesvg\*?(?![a-zA-Z])\s*(?:\[([^\]\n]*)\])?\s*\{([^}]*)\}"
)

#: svg→pdf 缺省转换器序 —— inkscape 在时包自身 shell-escape 链用 (flag 臂),
#: 缺席臂依次 rsvg-convert / magick / convert / cairosvg。
_SVG_CONVERTERS = ("rsvg-convert", "magick", "convert", "cairosvg")

#: ``\includesvg`` opts → graphicx 合法键白名单; inkscape*/pretex/...
#: svg 私有键丢弃 (改写后交给 ``\includegraphics`` 必须只吃 graphicx 键)。
_SVG_OPT_KEEP = frozenset(
    {"width", "height", "scale", "angle", "page", "clip", "trim", "keepaspectratio"}
)


def _svg_convert_one(ctx: LoopCtx, src: Path, dst: Path) -> str | None:
    """单 svg→pdf 逐工具试 → 成功 None / 失败原因串 (``ctx.run_tool`` 注入面)。"""
    tried = 0
    for name in _SVG_CONVERTERS:
        tool = shutil.which(name)
        if not tool:
            continue
        tried += 1
        argv = (
            [tool, "-f", "pdf", "-o", str(dst), str(src)]
            if name == "rsvg-convert"
            else [tool, str(src), "-o", str(dst)]
            if name == "cairosvg"
            else [tool, str(src), str(dst)]  # magick / convert
        )
        rc, _out, to = ctx.run_tool(argv, timeout=90)
        if rc == 0 and not to and dst.is_file() and dst.stat().st_size:
            return None
        dst.unlink(missing_ok=True)  # 失败残留清掉, 防半文件被当成产物
    return "no converter on PATH" if not tried else "all converters failed"


def _includesvg_opts(opts: str | None) -> str:
    r"""``\includesvg`` opts → graphicx 合法子集 ``[k=v,...]`` (``_SVG_OPT_KEEP``)。"""
    if not opts:
        return ""
    keep = [
        o.strip()
        for o in opts.split(",")
        if o.strip() and o.strip().split("=")[0].strip() in _SVG_OPT_KEEP
    ]
    return f"[{','.join(keep)}]" if keep else ""


def _rewrite_includesvg(ctx: LoopCtx, converted: dict[str, str]) -> int:
    r"""逐 tex 文件: 遮盖视图扫 ``\includesvg`` → ``\includegraphics`` 改写。

    converted 键是 svg basename; arg 规范名剥 ``.svg`` 尾 (或裸 stem) 后命中
    即改写, 目录前缀原样保留 —— dst 就落在 src 同目录。返回改写文件数。
    """
    changed = 0
    for f in ctx.tex_files((".tex", ".sty")):
        t = ctx.read(f)
        if t is None or "\\includesvg" not in t:
            continue
        out: list[str] = []
        prev = 0
        n = 0
        for m in _live_matches(_INCLUDESVG_RE, t):
            a = _norm_graphic_name(m.group(2))
            stem = PurePosixPath(a)
            base = stem.name
            if base.lower().endswith(".svg") and base in converted:
                new_arg = a[: len(a) - 4] + ".pdf"
            elif base in {PurePosixPath(k).stem for k in converted}:
                new_arg = f"{a}.pdf"
            else:
                continue
            out.append(t[prev : m.start()])
            out.append(
                f"\\includegraphics{_includesvg_opts(m.group(1))}{{{new_arg}}}"
                "% fixloop: includesvg->includegraphics"
            )
            prev = m.end()
            n += 1
        if not n:
            continue
        out.append(t[prev:])
        ctx.write(f, "".join(out))
        changed += 1
    return changed


def _svg_convert_arm(ctx: LoopCtx) -> tuple[bool, str]:
    r"""Inkscape 缺席/flag 被拒臂: wdir ``*.svg``→``.pdf`` + ``\includesvg`` 改写。

    dst 已在盘复用不重转; 全复用且无活 ``\includesvg`` → False
    (不白占轮次); 部分失败的 basename 记 note。
    """
    svgs = sorted(p for p in ctx.wdir.rglob("*.svg") if p.is_file())
    if not svgs:
        return False, "inkscape absent/flag-dropped and no .svg on disk"
    converted: dict[str, str] = {}
    failed: list[str] = []
    n_new = 0
    for src in svgs:
        dst = src.with_suffix(".pdf")
        if dst.is_file() and dst.stat().st_size:
            converted[src.name] = dst.name  # 上轮已转: 复用
            continue
        why = _svg_convert_one(ctx, src, dst)
        if why is None:
            converted[src.name] = dst.name
            n_new += 1
        else:
            failed.append(f"{src.name}({why})")
    n_rw = _rewrite_includesvg(ctx, converted)
    if not n_new and not n_rw:
        if failed:
            return False, "svg->pdf all failed: " + "; ".join(failed)
        return False, "all svg already converted, no live \\includesvg"
    note = (
        f"svg->pdf {n_new} new/{len(svgs)} total via wdir, "
        f"\\includesvg rewritten in {n_rw} file(s)"
    )
    if failed:
        note += f"; failed: {'; '.join(failed)}"
    return True, note


def svg_prepare(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""W31 svg 包编译准备: inkscape 在 → ``-shell-escape``; 缺席 → svg→pdf 预转换。

    两臂择一自适应: flag 臂 —— ``shutil.which("inkscape")`` 中 ∧ flag 未在
    ``ctx.flags_dropped`` (引擎 seam 拒放记录, tectonic/无沙箱 xelatex) →
    ``ctx.engine_flags`` 请 ``-shell-escape``, svg 包自带 ``\includesvg``
    shell-out 链接管余下。转换臂 —— inkscape 缺席或 flag 被拒 →
    ``_svg_convert_arm``: 全量 wdir ``*.svg`` → 同目录 ``.pdf``
    (``_SVG_CONVERTERS`` 序) + 活 ``\includesvg`` 改写 ``\includegraphics``
    (opts 过 ``_SVG_OPT_KEEP`` 白名单)。
    幂等: flag 已请且未拒 / svg 全转毕 → False 让位。
    """
    del eng, payload
    blob = mask_tex(ctx.source_blob())
    if not (_SVG_PKG_RE.search(blob) or _INCLUDESVG_RE.search(blob)):
        return False, "no live svg usage"
    flag = str(params.get("flag") or "-shell-escape")
    if shutil.which("inkscape") and flag not in ctx.flags_dropped:
        if flag in ctx.engine_flags:
            return False, f"{flag} already requested"
        ctx.engine_flags.append(flag)
        return True, f"inkscape on PATH -> engine_flags +{flag}"
    return _svg_convert_arm(ctx)


# ═══ dvipdfmx pipe/xbb 域 (pipecensus 2026-09-19): extractbb 缓存预生成 ═══

#: ``\Gread@extractbb@aux`` 经 ``<stem>.xbb`` 读的图形扩展名面 ——
#: dvipdfmx.def ``Gin@rule@<ext>`` 表第二元为 ``.xbb`` 的族
#: (pdf/ai/jp2/jpf/png/jpg/jpeg/bmp); eps/ps/mps 走 eps 读法不进本面。
_XBB_EXTS = (".pdf", ".ai", ".png", ".jpg", ".jpeg", ".jp2", ".jpf", ".bmp")

#: err_head 内 ``graphic in <stem>.xbb (no BoundingBox)`` 抽取 —— 裸 stem
#: 回映同 stem 图形件兜底 (glob 全量已覆盖, 防御非标准扩展名残留)。
_XBB_ERR_RE = re.compile(r"graphic in (\S+?)\.xbb \(no BoundingBox\)")


def _xbb_targets(ctx: LoopCtx) -> dict[Path, None]:
    """全量图形 glob + err_head 裸 stem 回映 → 保序去重目标表 (值占空)。"""
    targets: dict[Path, None] = {}
    for p in sorted(ctx.wdir.rglob("*")):
        if p.is_file() and p.suffix.lower() in _XBB_EXTS:
            targets[p] = None
    for stem in _XBB_ERR_RE.findall(ctx.err_head or ""):
        rel = PurePosixPath(_norm_graphic_name(stem))
        if rel.is_absolute() or ".." in rel.parts:
            continue
        base = ctx.wdir / Path(*rel.parts)
        if base.is_file():
            targets.setdefault(base)
            continue
        for e in _XBB_EXTS:
            g = base.with_suffix(e)
            if g.is_file():
                targets.setdefault(g)
                break
    return targets


def _xbb_fresh(xbb: Path, src: Path) -> bool:
    """``.xbb`` 非空且不旧于源图 → 免重转 (stat 败一律按不鲜)。"""
    try:
        return bool(
            xbb.is_file()
            and xbb.stat().st_size
            and xbb.stat().st_mtime >= src.stat().st_mtime
        )
    except OSError:
        return False


def xbb_pregen(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Dvipdfmx pipe/xbb 双错: 全量图形 ``extractbb -x`` 预生成 ``.xbb`` bbox 缓存。

    机制 (graphics-def ``dvipdfmx.def:104-131``): doc 强指 ``[dvipdfmx]``
    驱动时 pdf/png 族图形先 ``\openin <stem>.xbb`` —— miss 退
    ``"|extractbb -O <file>"`` pipe → 沙箱 ``shell_escape=f`` 下 pipe 死 →
    ``Cannot run pipe command`` + ``<stem>.xbb (no BoundingBox)`` 每图一对
    (2105.00151 IEICE 模板 13 图 26 错格)。``.xbb`` 在盘非空即被直读、
    pipe 臂整体跳过 —— 全量预生成单轮尽数解掉 (err_head 只露首错 stem,
    逐 stem 修要烧轮次; extractbb 批式只写末件故逐件调用)。
    幂等: ``.xbb`` 非空且不旧于源图 → 跳过; extractbb 败残留的空 ``.xbb``
    (``\ifeof`` 为真照样走 pipe 的毒件) 就地清掉。
    """
    del eng, payload
    extractbb = shutil.which("extractbb")
    if not extractbb:
        return False, "no extractbb on PATH"
    targets = _xbb_targets(ctx)
    if not targets:
        return False, "no extractbb-capable graphic in project"
    timeout = int(params.get("timeout", 60))
    gen = fresh = 0
    failed: list[str] = []
    for src in targets:
        xbb = src.with_suffix(".xbb")
        if _xbb_fresh(xbb, src):
            fresh += 1
            continue
        # openout_any=p 下 extractbb 拒写绝对径产物 —— argv 给 wdir 相对径
        # (run_tool cwd=wdir), 同名 .xbb 落源图旁。
        rc, _out, to = ctx.run_tool(
            [extractbb, "-x", src.relative_to(ctx.wdir).as_posix()], timeout=timeout
        )
        if rc == 0 and not to and xbb.is_file() and xbb.stat().st_size:
            gen += 1
        else:
            xbb.unlink(missing_ok=True)  # 失败空 .xbb 是毒件 —— \ifeof 仍走 pipe
            failed.append(f"{src.name}(rc={rc}{'/to' if to else ''})")
    if not gen:
        if fresh and not failed:
            return False, f"all {fresh} .xbb already fresh"
        return False, f"0 generated ({'; '.join(failed) or 'nothing to do'})"
    note = f"xbb pregen {gen} new/{len(targets)} targets"
    if fresh:
        note += f", {fresh} fresh"
    if failed:
        note += f"; failed: {'; '.join(failed)}"
    return True, note


# ═══ xdvipdfmx pdf_link_obj 域 (xlinkobj lane 2026-09-19): 内嵌 pdf 重序列化 ═══

#: sanitize 目标扫描的排除目录 —— ``_texmf`` (wired vendored texmfhome) 与
#: ``_tect_out`` (tectonic 产物树) 是引擎/注入侧封装件, 非文档内嵌图件。
_PDF_SANITIZE_SKIP_DIRS = frozenset({"_texmf", "_tect_out"})


def _pdf_sanitize_targets(ctx: LoopCtx) -> list[Path]:
    """``wdir`` 内 sanitize 候选 .pdf —— 排除引擎产物/隐藏面/封装树。"""
    main = ctx.main_path()
    main_pdf = main.with_suffix(".pdf") if main is not None else None
    out: list[Path] = []
    for p in sorted(ctx.wdir.rglob("*")):
        if not p.is_file() or p.suffix.lower() != ".pdf":
            continue
        parts = p.relative_to(ctx.wdir).parts
        if any(part.startswith(".") for part in parts):
            continue  # .fixloop-entry.pdf 底板快照等隐藏面不动
        if parts[0] in _PDF_SANITIZE_SKIP_DIRS:
            continue
        if main_pdf is not None and p == main_pdf:
            continue  # 主输出 pdf 重编译自生, 非内嵌图件
        out.append(p)
    return out


def pdf_asset_sanitize(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``pdf_link_obj(): passed invalid object`` fatal → 全量内嵌 .pdf gs 重序列化。

    机制 (xlinkobj lane 5 格普查): 工程船货 .pdf 对象结构残缺 (缺 ``endobj``
    / bare-CR EOL / token-per-line 挤烂) → ``pdf:image`` import
    ``pdf_read_object`` 回 NULL → ``pdf_link_obj(NULL)`` fatal → xelatex
    SIGPIPE。签名只走 stderr→stdout_tail, ``.log`` 干净 —— ``_report_of``
    的 ``*:fatal:`` 归一使它可见即 ``other`` 类。gs pdfwrite 重序列化只改
    对象布局不改内容, 原件留 ``<name>.fixloop-rd`` 备份 (与 graphic_repair
    同 marker, 兼「已 sanitize」幂等标记); 肇事件不可定位 (fatal 不携
    文件名) 故全量重写 —— 健康件重序列化是语义 no-op。
    """
    del eng, payload, params
    targets = _pdf_sanitize_targets(ctx)
    if not targets:
        return False, "no pdf assets in project"
    done = skipped = 0
    failed: list[str] = []
    for f in targets:
        marker = f.with_name(f.name + ".fixloop-rd")
        if marker.exists():
            skipped += 1
            continue
        if why := _try_gs_redistill(ctx, f, marker):
            failed.append(f"{f.name}({why})")
        else:
            done += 1
    if not done:
        if skipped and not failed:
            return False, f"all {skipped} pdf already sanitized"
        return False, f"0/{len(targets)} sanitized ({'; '.join(failed)})"
    note = f"gs pdfwrite sanitized {done}/{len(targets)} pdf assets"
    if skipped:
        note += f", {skipped} already"
    if failed:
        note += f"; failed: {'; '.join(failed)}"
    return True, note


# ════════════════════════════════════════════════════════════════
# missing_file 的 PS 族图档真缺件 → wdir 落占位 EPS (failmine3 #164a)
# ════════════════════════════════════════════════════════════════

#: 最小合法 EPS 占位: epsfig/graphics 两系 bbox 解析都吃 ``%%BoundingBox``,
#: xdvipdfmx 走内嵌 gs 蒸馏 (沙箱 ``-no-shell-escape`` 下仍通——epsprobe
#: 实测 ``File: ph.eps Graphic file (type eps)`` 载入出 PDF); tectonic 侧
#: .eps 是 ps_image 墙, 占位件是真 EPS 可由 eps_to_pdf(15) 的 gs 照常转换。
#: 边框+对角线让读者可辨「图缺」占位而非空白; 200x150bp 近常见插图比例,
#: 调用点 ``width=``/``scale=`` 照常缩放。
_EPS_PLACEHOLDER = (
    "%!PS-Adobe-3.0 EPSF-3.0\n"
    "%%BoundingBox: 0 0 200 150\n"
    "%%Title: fixloop placeholder (graphic absent from e-print)\n"
    "%%EndComments\n"
    "0.55 setgray 1.2 setlinewidth\n"
    "newpath 0 0 moveto 200 0 lineto 200 150 lineto 0 150 lineto closepath stroke\n"
    "newpath 0 0 moveto 200 150 lineto stroke\n"
    "newpath 200 0 moveto 0 150 lineto stroke\n"
    "%%EOF\n"
)

#: ``\epsfig{file=X.eps, scale=..}`` / ``\psfig{figure=X}`` / ``\epsfbox{X}``
#: kv/裸参引用点 —— ``_INCLUDE_GFX_RE`` 吃不到 kv 形, 独立一柄。
_EPS_KV_RE = re.compile(r"\\(?:epsfig|psfig|epsffile|epsfbox)\s*\{([^}]*)\}")
#: kv 形大括号串内的 ``file=``/``figure=`` 值。
_KV_FILE_RE = re.compile(r"(?:file|figure)\s*=\s*([^,\s}]+)")


def _has_live_graphic_ref(ctx: LoopCtx, want: str) -> bool:
    r"""存活图形调用点 arg 与 want 命中复核 (``_graphic_ref_hit`` 三口径)。

    ``\includegraphics``/epsfig/psfig 族全覆盖 —— 无扩展名 payload 的
    图形域证据面 (``\input`` 系裸缺件没有图形调用点, 不落占位)。
    """
    for f in ctx.tex_files((".tex", ".sty")):
        t = ctx.read(f)
        if t is None:
            continue
        for m in _live_matches(_INCLUDE_GFX_RE, t):
            if _graphic_ref_hit(m.group(2), want):
                return True
        for m in _live_matches(_EPS_KV_RE, t):
            kv = _KV_FILE_RE.search(m.group(1))
            arg = kv.group(1) if kv else m.group(1)
            if _graphic_ref_hit(arg, want):
                return True
    return False


def graphic_missing_placeholder(  # noqa: PLR0911 - 逐门 decline note 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""missing_file 的 PS 族图档真缺件 → ``wdir/<payload>`` 落最小合法 EPS。

    graphic_ext_relax 残家 (failmine3 8 格): sibling 不存在时剥扩展名也
    救不了 —— 修复不是改源而是补档 (xbb_pregen 旁件同形)。站点改写形
    盖不全调用面: ``\epsfig{file=X.eps}`` kv 形与宏体 ``#1.eps`` 间接名
    (payload 是展开后真名, 源码字面不可锚) 只能由「真名落盘」治;
    子目录路径 (``FIGS/``/``images/``) mkdir 随行。

    payload 是 log 派生路径 —— 双层守卫: ``..`` 段拒 + resolve 后仍须
    在 wdir 内 (防穿越写)。无扩展名 payload (ext-relax 残家 vanilla
    解析序) 须先过 ``_has_live_graphic_ref`` 复核才补 ``.eps`` ——
    ``\input`` 系裸缺件不落图占位。盘上已有档 (大小写变体/前轮已补)
    → False 让路。
    """
    del eng, params
    want = _norm_graphic_name(payload or "")
    if not want:
        return False, "no graphic payload"
    suffix = PurePosixPath(want).suffix.lower()
    if suffix and suffix not in _EPS_EXTS:
        return False, f"{want}: not a PS-family graphic"
    if not suffix:
        if not _has_live_graphic_ref(ctx, want):
            return False, f"{want}: no live graphic ref — not graphic domain"
        want += ".eps"
    if ".." in PurePosixPath(want).parts:
        return False, f"{want}: path traversal rejected"
    f = ctx.wdir / want
    try:
        f.resolve().relative_to(ctx.wdir.resolve())
    except ValueError:
        return False, f"{want}: escapes wdir"
    if safe_is_file(f):
        return False, f"{want}: resolved meanwhile"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        ctx.write(f, _EPS_PLACEHOLDER)
    except OSError as e:
        return False, f"{want}: write failed ({e})"
    return True, f"placeholder EPS at {want}"
