r"""builtins.graphics — 图形转换/驱动预检域修复原语 (C3 拆分收尾叶子)。

pstricks/dvips 路由预检 / ``.eps``→``.pdf`` 全量转换 (epstopdf 优先, gs
-dEPSCrop 兜底) / svg 包编译准备 (inkscape flag 臂或离线转换臂) /
dvipdfmx ``.xbb`` bbox 缓存预生成 / 内嵌 ``.pdf`` gs 重序列化。
missing_graphic 缺图族 (ci 改名/拒载分级/缺件占位/伪装改名/驱动期缺图)
已再分叶 ``builtins.gfx_missing`` —— 历史平名经本模块 ``__getattr__``
惰性回引, ``builtins`` 门面与既有 import 面不变 (见文件尾)。

monkeypatch 锚点迁移: ``_run_convert`` 的 patch 面随调用链落在本模块
——测试请 ``monkeypatch.setattr(builtins.graphics, "_run_convert", ...)``;
builtins/__init__.py 门面的同名回引只是再导出, patch 它不生效。缺图族成员
锚点同理随调用链落 ``builtins.gfx_missing``。
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _live_matches,
    _map_tex_files,
    _splice,
)
from texlate.texlog import PS_GRAPHIC_EXTS
from texlate.textutil import mask_tex, safe_is_file

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


def pstricks_dvips_preflight(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    """latex+dvips 路由前的 .pro 资源预检 (docs/spec/compile.md §6.6)。

    无论资源齐不齐都 REJECT (dvips 是唯一出路); 缺资源时 note 附
    advisory 让上层决策 (装 pst-tools / 放弃 pstricks 路)。
    """
    del ctx, payload  # ctx 无需读文件：预检只看系统侧资源

    missing = [fn for fn in params.get("require_files") or [] if not eng.probe_file(fn)]
    route = params.get("route", "latex+dvips")
    if missing:
        return True, f"REJECT: route={route} advisory=missing:{','.join(missing)}"
    return True, f"REJECT: route={route} dvips-resources-ok"


_EPS_EXTS = tuple(sorted(PS_GRAPHIC_EXTS))  # 单源 texlog.PS_GRAPHIC_EXTS
#: metapost 数字扩展名 ``.\d+`` —— ``diag1.1`` 实为 EPS (0806.4589 实证：
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
#: 只走 PostScript specials 的 graphicx 驱动 —— tectonic (xdvipdfmx) 下必死，
#: 且 ``[dvips]{graphicx}`` 会把无扩展名引用的搜索序掰成 .eps 优先
#: (1902.11112 实证：plykin.pdf 已生成仍请求 plykin.eps)。
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
#: 词表对 ``textutil.LOADER_CMDS`` 不机械换指：本正则只接 ``[opts]{name}``
#: 前位选项形——``*WithOptions`` 两枚是 ``{name}[opts]`` 后位形、
#: ``PassOptionsTo*`` 是 ``{opts}{name}`` 花括号形，结构上永不吃本正则;
#: ``documentclass``/``documentstyle`` 属 ``DOCCLASS_NAMES`` 声明族不在
#: LOADER 集。故本站词表 = LOADER∩[opts]{name}形 ∪ DOCCLASS_NAMES 手写投影。
_LOAD_OPT_RE = re.compile(
    r"\\(usepackage|RequirePackage|documentclass|documentstyle|LoadClass)"
    r"\s*\[([^\]\n]*)\](\s*\{[^}]*\})"
)
_GRAPHICS_PKGS_RE = re.compile(r"(?i)\b(?:graphics|graphicx|color|epsfig|epsf)\b")

#: 工程文件枚举的封装树排除面 —— ``_texmf`` (wired vendored texmfhome) 与
#: ``_tect_out`` (tectonic 产物树) 是引擎/注入侧封装件，非文档源件。
#: actions.py / builtins/shim.py 同名复用，改口径需三处同步。
_PDF_SANITIZE_SKIP_DIRS = frozenset({"_texmf", "_tect_out"})


def _iter_project_files(
    ctx: LoopCtx, exts: tuple[str, ...] | None = None
) -> list[Path]:
    """``wdir`` 工程源件枚举 (排序) —— 排除面单源，各扫描臂同口径。

    排除：dot-前缀部件 (``.fixloop-*`` 底板快照等隐藏面)、``_texmf``/
    ``_tect_out`` 引擎封装树、主输出 ``<main>.pdf`` (重编译自生非源件)。
    ``exts=None`` 收全量 (ci 找图按名命中不受扩展名约束); 传入时按
    ``p.suffix.lower()`` 过滤。目录段判定先于 ``is_file`` —— 封装树
    庞大时省下逐件 stat。
    """
    main = ctx.main_path()
    main_pdf = main.with_suffix(".pdf") if main is not None else None
    exts_t = {e.lower() for e in exts} if exts is not None else None
    out: list[Path] = []
    for p in sorted(ctx.wdir.rglob("*"), key=lambda p: p.as_posix()):
        parts = p.relative_to(ctx.wdir).parts
        if parts[0] in _PDF_SANITIZE_SKIP_DIRS or any(
            part.startswith(".") for part in parts
        ):
            continue
        if not p.is_file() or (exts_t is not None and p.suffix.lower() not in exts_t):
            continue
        if main_pdf is not None and p == main_pdf:
            continue
        out.append(p)
    return out


def _norm_graphic_name(name: str) -> str:
    r"""Log payload / ``\includegraphics`` 参数 → 规整 posix 相对路径。"""
    n = name.strip().strip("'\"")
    n = n.replace("\\", "/")
    while n.startswith("./"):
        n = n[2:]
    return n


def _strip_ps_driver_opts(t: str) -> tuple[str, int]:
    """摘 PS 路由驱动选项 → (新文本，摘除数)。

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
        p = subprocess.run(  # noqa: S603  # 转换工具调用，非用户输入
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
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


def _gs_bin() -> str | None:
    """GS 可执行名查找：``gs`` → ``gswin64c`` → ``gswin32c``。"""
    return shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")


def _produced(dst: Path, rc: int | None, *, to: bool | str) -> bool:
    """转换工具后件断言：``rc==0`` 且未超时且 dst 非空在盘; 判败残留就地清掉。"""
    if rc == 0 and not to and dst.is_file() and dst.stat().st_size:
        return True
    dst.unlink(missing_ok=True)  # 失败残留清掉，防半文件被当成产物
    return False


def _convert_one(epstopdf: str | None, gs: str | None, src: Path, dst: Path) -> bool:
    """单个 .eps/.ps → .pdf: epstopdf 优先，gs -dEPSCrop 兜底 (texglot 同配方)。"""
    for tool in (epstopdf, gs):
        if not tool:
            continue
        rc, _out, to = _run_convert(tool, src, dst)
        if _produced(dst, rc, to=to):
            return True
    return False


def _rewrite_eps_refs(
    ctx: LoopCtx, exts: tuple[str, ...], converted: dict[str, str]
) -> tuple[int, int]:
    r"""逐 tex 文件: ``x.eps``→``x.pdf`` 边界改写 + 剥 PS 驱动选项 → (改写文件数, 摘驱动数)。

    ``converted`` 键为 wdir 相对径 —— 引用 token 仅在 ``(filedir|wdir)/tok``
    解析到该源件时改写: 同名异目录源互不串写 (单侧转换失败不再跨目污染),
    裸 ``replace`` 的 ``myplot.eps``/``fig.epsx`` 子串误伤亦绝 —— 统一走
    ``(?<![\w.~/\\-])…(?![\w.])`` 边界正则 (原 ``new.startswith(old)`` 臂
    同款); ``diag1.1``→``diag1.1.pdf`` 叠后缀形二次触火由 ``(?![\w.])``
    挡回保持幂等。
    """
    n_drivers = 0
    rules = [
        (
            ctx.wdir / old_rel,
            PurePosixPath(new_rel).name,
            re.compile(
                rf"(?<![\w.~/\\-])((?:[\w.~\\-]+[/\\])*)"
                rf"{re.escape(PurePosixPath(old_rel).name)}(?![\w.])"
            ),
        )
        for old_rel, new_rel in converted.items()
    ]
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt = t
        for src, dst_base, rx in rules:

            def _sub(
                m: re.Match[str], _s: Path = src, _d: str = dst_base, _f: Path = f
            ) -> str:
                tok = _norm_graphic_name(m.group(0))
                local = Path(os.path.normpath(_f.parent / tok))
                target = (
                    local
                    if safe_is_file(local)
                    else Path(os.path.normpath(ctx.wdir / tok))
                )
                # filedir 命中优先 (TeX 近端解析); 解析到非本源件 = 同名异目 → 不动
                return (m.group(1) or "") + _d if target == _s else m.group(0)

            nt = rx.sub(_sub, nt)
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
    gs = _gs_bin()
    if not epstopdf and not gs:
        return False, "no epstopdf/gs available"
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    sources = [
        p
        for p in _iter_project_files(ctx)
        if p.suffix.lower() in _EPS_EXTS or _NUMERIC_EXT_RE.match(p.suffix)
    ]
    if not sources:
        return False, "no .eps/.ps/.mps/.N in project"
    converted: dict[str, str] = {}  # "img/fig.eps" -> "img/fig.pdf" (wdir 相对径级)
    for src in sources:
        dst = (
            src.with_name(src.name + ".pdf")
            if _NUMERIC_EXT_RE.match(src.suffix)
            else src.with_suffix(".pdf")
        )
        if dst.is_file() and dst.stat().st_size:
            # 上轮已转：复用，免重转
            converted[src.relative_to(ctx.wdir).as_posix()] = dst.relative_to(
                ctx.wdir
            ).as_posix()
            continue
        if _convert_one(epstopdf, gs, src, dst):
            converted[src.relative_to(ctx.wdir).as_posix()] = dst.relative_to(
                ctx.wdir
            ).as_posix()
    if not converted:
        return False, f"0/{len(sources)} converted"
    # 显式引用改写 + PS 驱动选项剥离：`x.eps`/`x.ps` 字面量改 `x.pdf`,
    # [dvips] 族驱动摘掉让无扩展名引用落到 .pdf 搜索序
    n_files, n_drivers = _rewrite_eps_refs(ctx, exts, converted)
    note = (
        f"eps->pdf {len(converted)}/{len(sources)} converted, "
        f"refs rewritten in {n_files} files"
    )
    if n_drivers:
        note += f", {n_drivers} ps-driver opts stripped"
    return True, note


# ═══ gs 重蒸馏原语 —— graphic_repair (gfx_missing 叶) 与 pdf_asset_sanitize 共用 ═══


def _try_gs_redistill(ctx: LoopCtx, f: Path, marker: Path) -> str | None:
    r"""``gs -sDEVICE=pdfwrite`` 重蒸馏 f 就地覆盖 → None 成功 / 失败原因串。

    原件拷为 marker (备份兼「已蒸馏」标记); 失败残留 ``.fixloop-tmp`` 清掉,
    防半文件被当成产物 (``_convert_one`` 同款纪律)。
    """
    gs = _gs_bin()
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
    if not _produced(tmp, rc, to=to):
        return f"gs failed rc={rc}{'/timeout' if to else ''}"
    shutil.copy2(f, marker)
    tmp.replace(f)
    ctx.invalidate(f)
    return None


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
        if _produced(dst, rc, to=to):
            return None
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

    def _fn(t: str) -> tuple[str, int]:
        if "\\includesvg" not in t:
            return t, 0
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
            return t, 0
        out.append(t[prev:])
        return "".join(out), n

    return _map_tex_files(ctx, (".tex", ".sty"), _fn)


def _svg_convert_arm(ctx: LoopCtx) -> tuple[bool, str]:
    r"""Inkscape 缺席/flag 被拒臂: wdir ``*.svg``→``.pdf`` + ``\includesvg`` 改写。

    dst 已在盘复用不重转; 全复用且无活 ``\includesvg`` → False
    (不白占轮次); 部分失败的 basename 记 note。
    """
    svgs = _iter_project_files(ctx, (".svg",))
    if not svgs:
        return False, "inkscape absent/flag-dropped and no .svg on disk"
    converted: dict[str, str] = {}
    failed: list[str] = []
    n_new = 0
    for src in svgs:
        dst = src.with_suffix(".pdf")
        if dst.is_file() and dst.stat().st_size:
            converted[src.name] = dst.name  # 上轮已转：复用
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
#: 回映同 stem 图形件兜底 (glob 全量已覆盖，防御非标准扩展名残留)。
_XBB_ERR_RE = re.compile(r"graphic in (\S+?)\.xbb \(no BoundingBox\)")


def _xbb_targets(ctx: LoopCtx) -> dict[Path, None]:
    """全量图形 glob + err_head 裸 stem 回映 → 保序去重目标表 (值占空)。

    glob 走 ``_iter_project_files`` 排除面 —— 引擎封装树/隐藏面/主输出
    不产 ``.xbb`` 旁件; err_head 回映同套段级守卫 (含空 stem 拒 ——
    ``Path()`` 空件防 ``wdir.with_suffix`` 越界探测)。
    """
    targets: dict[Path, None] = {}
    for p in _iter_project_files(ctx, _XBB_EXTS):
        targets[p] = None
    for stem in _XBB_ERR_RE.findall(ctx.err_head or ""):
        rel = PurePosixPath(_norm_graphic_name(stem))
        if (
            not rel.parts
            or rel.is_absolute()
            or ".." in rel.parts
            or rel.parts[0] in _PDF_SANITIZE_SKIP_DIRS
            or any(part.startswith(".") for part in rel.parts)
        ):
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
        # 失败空 .xbb 是毒件 (\ifeof 仍走 pipe) —— _produced 判败顺带清掉
        if _produced(xbb, rc, to=to):
            gen += 1
        else:
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


# ═══ xdvipdfmx pdf_link_obj 域 (xlinkobj 车道 2026-09-19): 内嵌 pdf 重序列化 ═══


def _pdf_asset_targets(ctx: LoopCtx) -> list[Path]:
    """``wdir`` 内嵌 .pdf 候选 —— 排除面归 ``_iter_project_files`` 单源 (sanitize/mislabeled 同口径)。"""
    return _iter_project_files(ctx, (".pdf",))


def pdf_asset_sanitize(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``pdf_link_obj(): passed invalid object`` fatal → 全量内嵌 .pdf gs 重序列化。

    机制 (xlinkobj 车道 5 格普查): 工程船货 .pdf 对象结构残缺 (缺 ``endobj``
    / bare-CR EOL / token-per-line 挤烂) → ``pdf:image`` import
    ``pdf_read_object`` 回 NULL → ``pdf_link_obj(NULL)`` fatal → xelatex
    SIGPIPE。标记只走 stderr→stdout_tail, ``.log`` 干净 —— ``_report_of``
    的 ``*:fatal:`` 归一使它可见即 ``other`` 类。gs pdfwrite 重序列化只改
    对象布局不改内容, 原件留 ``<name>.fixloop-rd`` 备份 (与 graphic_repair
    同 marker, 兼「已 sanitize」幂等标记); 肇事件不可定位 (fatal 不携
    文件名) 故全量重写 —— 健康件重序列化是语义 no-op。
    """
    del eng, payload, params
    targets = _pdf_asset_targets(ctx)
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
# rotatebox_caption_pad: figure env 内旋转图 caption 前垫 (qc99)
# ════════════════════════════════════════════════════════════════

#: figure/figure* env 块 (遮盖视图锚边界对，注释/verbatim 不锚)。
_FIG_ENV_RX = re.compile(r"\\begin\{figure\*?\}[\s\S]*?\\end\{figure\*?\}")

#: 旋转标记 —— ``\\rotatebox`` 盒或 graphicx ``angle=`` 键 (90/180/270
#: 族; 0°/小角不产生 bbox-ink 错位机制，防爆半径只咬旋转面)。
_ROTATED_RX = re.compile(r"\\rotatebox\b|\bangle\s*=\s*-?(?:90|180|270)\b")

_CAPTION_RX = re.compile(r"\\caption\b")
_ABOVECAP_RX = re.compile(r"\\abovecaptionskip")

#: 垫高量 —— 0812.0424 实测 eps bb 外轴标墨迹下探 ~10-15pt, EN base
#: 同 bleed 但 1 行 caption 勉强擦过; zh 2 行 caption 撞进 bleed 带。
_ROTFIG_PAD = "14pt"


def _rotfig_caption_pad_text(t: str, pad: str) -> tuple[str, int]:
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for m in _FIG_ENV_RX.finditer(vis):
        block = m.group(0)
        if not _ROTATED_RX.search(block) or not _CAPTION_RX.search(block):
            continue
        if _ABOVECAP_RX.search(block):
            continue  # 已有显式 abovecaptionskip → 幂等跳过
        # env 头后即注——figure 组内 setlength 对组内 minipage/caption
        # 全可见 (0707.3761 双 minipage+caption 对同效), 且天然先于
        # \caption 读值点。锚点须越过 ``[placement]`` 可选参
        # (0707.3761 ``[hb]`` 实证), 否则它被落成 figure 体首字面文本。
        head_end = t.index("}", m.start()) + 1
        j = head_end
        while j < m.end() and t[j] in " \t\n":
            j += 1
        if j < m.end() and t[j] == "[":
            close = t.find("]", j + 1, m.end())
            if close != -1:
                head_end = close + 1
        edits.append(
            (head_end, head_end, f"\n\\setlength{{\\abovecaptionskip}}{{{pad}}}")
        )
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def rotatebox_caption_pad(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Figure env 含旋转图 + ``\\caption`` → env 头注 ``\\abovecaptionskip`` 垫高。

    实证 (qc99 2026-09-28): 0812.0424 ``\\rotatebox{-90}{\\includegraphics
    [width=0.34\\linewidth]{fig5a.eps}}`` —— eps BoundingBox 外轴标墨迹
    (matplotlib 族通病, 标签挂出 bb) 旋到盒下 ~10-15pt bleed; EN base
    同 bleed 但 1 行 caption 擦过, zh 2 行撞进 (labels 720-731 vs
    caption 叠印)。0707.3761 同族 ``angle=270`` includegraphics 形。
    编译 clean 无 log 标记, 唯 precheck ``always`` 面可达。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    pad = str(params.get("pad") or _ROTFIG_PAD)
    n = _map_tex_files(ctx, exts, lambda t: _rotfig_caption_pad_text(t, pad))
    if not n:
        return False, "no rotated-graphic figure envs needing caption pad"
    return True, f"abovecaptionskip {pad} padded in {n} file(s)"


# ════════════════════════════════════════════════════════════════
# missing_graphic 族出叶惰性回引 (C3 再拆分)
# ════════════════════════════════════════════════════════════════

#: 随迁 ``builtins.gfx_missing`` 的本叶历史名 —— ``builtins._LAZY``
#: 门面表 / ``from builtins.graphics import X`` 测试面 /
#: ``builtins.misc`` eager import 全不经改：惰性解析直取新叶后缓存回
#: 本模块 globals。monkeypatch 锚点随迁 —— 新叶内部调用链只认
#: ``builtins.gfx_missing.X``, 在本模块 setattr 只遮蔽本模块属性。
_GFX_MISSING_NAMES = frozenset(
    {
        "_DRV_IMG_MISS_RE",
        "_ENUM_ARG_BAD_RE",
        "_EPS_KV_RE",
        "_EPS_PLACEHOLDER",
        "_GFX_ARG_RE",
        "_GFX_DEF_NC_RE",
        "_GFX_DEF_PRIM_RE",
        "_GFX_OPT_ARG_RE",
        "_GFX_PARAM_REF_RE",
        "_GRAPHICSPATH_RE",
        "_GRAPHIC_EXTS",
        "_GSPATH_DIR_RE",
        "_INCLUDE_GFX_RE",
        "_INCLUDE_PDF_RE",
        "_JPEG_PLACEHOLDER",
        "_KV_FILE_RE",
        "_LOG_MISS_GFX_RE",
        "_PDF_PLACEHOLDER",
        "_PNG_PLACEHOLDER",
        "_ProjectScan",
        "_RASTER_MAGICS",
        "_debrace_sweep",
        "_disk_hit",
        "_enum_missing_graphics",
        "_find_graphic_ci",
        "_gfx_call_args",
        "_gfx_macro_templates",
        "_gfx_resolve_hit",
        "_gfx_template_items",
        "_graphic_ref_hit",
        "_graphicspath_dirs",
        "_has_live_graphic_ref",
        "_macro_graphic_ref_hit",
        "_mislabeled_pdf_targets",
        "_opt_dim",
        "_rewrite_case_refs",
        "_rewrite_mislabeled_refs",
        "_sniff_raster_ext",
        "_stub_graphic_at",
        "_stub_graphic_refs",
        "_stub_sweep",
        "driver_missing_image_stub",
        "graphic_case_link",
        "graphic_missing_placeholder",
        "graphic_repair",
        "includepdf_missing_stub",
        "raster_pdf_rename",
    }
)


def __getattr__(name: str) -> object:
    """出叶名惰性回引 ``builtins.gfx_missing`` —— 兼容面，新代码请直取新叶。"""
    if name in _GFX_MISSING_NAMES:
        mod = importlib.import_module(f"{__package__}.gfx_missing")
        value = getattr(mod, name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(set(globals()) | _GFX_MISSING_NAMES)
