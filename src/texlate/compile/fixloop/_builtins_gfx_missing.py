r"""_builtins_gfx_missing — missing_graphic 缺图域修复原语 (C3 再拆分叶子)。

``_builtins_graphics`` 同源分叶: 转换/驱动预检族 (eps→pdf 全量转换、
svg/xbb/pdf-asset、pstricks 预检) 留原叶, 本叶收「引用在盘但引擎喊缺 /
真缺件占位」一族 —— ci 大小写改名 ``graphic_case_link`` / 在盘拒载分级
修复 ``graphic_repair`` / ``\includepdf`` 缺件占位
``includepdf_missing_stub`` / 真缺件格式占位 ``graphic_missing_placeholder``
(含宏间接 ``#N`` 引用复核与 halt_on_error 源侧枚举) / raster-伪装
``.pdf`` 改名 ``raster_pdf_rename`` / xdvipdfmx 驱动期缺图
``driver_missing_image_stub``。

共享原语 (``_iter_project_files`` 排除面扫描 / ``_norm_graphic_name`` /
``_EPS_EXTS`` / ``_NUMERIC_EXT_RE`` / ``_try_gs_redistill`` gs 重蒸馏 /
``_pdf_asset_targets``) 仍留 ``_builtins_graphics`` 单源, 本叶顶行回引
—— 依赖单向 (gfx_missing → graphics) 无环; 反向
``_builtins_graphics.X`` 读面经彼侧 ``__getattr__`` 惰性回引本叶,
``builtins`` 门面 ``_LAZY`` 表与 ``from _builtins_graphics import X``
测试面不需改。

monkeypatch 锚点迁移: patch 面随调用链落在本叶 —— 测试请
``monkeypatch.setattr(_builtins_gfx_missing, "<name>", ...)``;
``_builtins_graphics``/``builtins`` 同名回引只是再导出, patch 不生效。
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _fixloop_log,
    _live_matches,
    _map_tex_files,
)
from texlate.compile.fixloop._builtins_graphics import (
    _EPS_EXTS,
    _NUMERIC_EXT_RE,
    _iter_project_files,
    _norm_graphic_name,
    _pdf_asset_targets,
    _try_gs_redistill,
)
from texlate.textutil import mask_tex, safe_is_file

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


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
#: arg 捕获面收一层内层花括 (``dir/{stem}.ext``/``{file.png}`` 两形) ——
#: ``[^}]*`` 在内层 ``}`` 处截断会漏 braced 实参 (1710.09412 micro2 实证)。
_INCLUDE_GFX_RE = re.compile(
    r"\\includegraphics\*?\s*(?:\[([^\]\n]*)\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}"
)

#: ``\includepdf[opts]{file}`` (pdfpages) 引用点 —— W66 孤儿裁决面:
#: 与 ``_INCLUDE_GFX_RE`` 分正则而非并表 —— graphic_repair 的 ``\fbox``
#: stub 语义只适用图像件, includepdf 缺件占位是 ``\clearpage\null``。
_INCLUDE_PDF_RE = re.compile(
    r"\\includepdf(?![a-zA-Z])\s*(?:\[([^\]\n]*)\])?\s*\{((?:[^{}]|\{[^{}]*\})*)\}"
)


def _find_graphic_ci(
    ctx: LoopCtx, want: str, files: list[Path] | None = None
) -> Path | None:
    r"""工程目录内大小写不敏感找图真身。

    命中序: 相对路径整串 ci 相等 / 文件名 ci 相等 (rank0) → want 无扩展名时
    stem ci 相等且扩展名在图形族面 (rank1, ``.\d+`` 数字扩展同收);
    多命中取 rank 低 + 相对路径短者 (确定性排序)。
    ``files`` 传 ``_ProjectScan.files`` 快照免逐 want 重扫 —— 候选面同走
    ``_iter_project_files`` 排除 (引擎封装树/隐藏面不做 ci 真身)。
    """
    want = _norm_graphic_name(want)
    if not want:
        return None
    wl = want.lower()
    base = PurePosixPath(wl).name
    stemless = "." not in base
    cands: list[tuple[int, int, str, Path]] = []
    for p in files if files is not None else _iter_project_files(ctx):
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


def _debrace_sweep(ctx: LoopCtx, exts: tuple[str, ...], base: Path) -> int:
    r"""全工程 ``\includegraphics``/``\includepdf`` braced 参数去括改写。

    ``dir/{stem}.ext``/``{file.png}`` 内层分组符 xetex 不剥按字面名寻档
    (1710.09412 micro2 实证): 去括路径在解析位 (main_dir|filedir) 命中
    即改写。braced 字面名在盘 (病态但合法) → 不动; 去括名也不在 → 不动
    (真缺件留占位域)。一次点火全量扫 —— 逐 payload 版多 braced 名格
    (1710.09412 ~16 名) 同样烧穿轮次上限。返回改写文件数。
    """
    changed = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or ("\\includegraphics" not in t and "\\includepdf" not in t):
            continue

        def _sub(m: re.Match[str], _f: Path = f) -> str:
            arg = m.group(2)
            if "{" not in arg and "}" not in arg:
                return m.group(0)
            a = _norm_graphic_name(arg)
            if safe_is_file(base / a) or safe_is_file(_f.parent / a):
                return m.group(0)
            d = _norm_graphic_name(a.replace("{", "").replace("}", ""))
            if not d or not (safe_is_file(base / d) or safe_is_file(_f.parent / d)):
                return m.group(0)
            return (
                m.group(0)[: m.start(2) - m.start()]
                + d
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
    # 1710.09412 (micro2 普查): ``dir/{stem}.ext`` 部分花括名 —— xetex 不剥
    # 内层分组符按字面名寻档 (tmp/lane-micro2/repro2 实证), 盘上真身是去括名。
    # braced payload 即文档惯用法证据 → 全量扫; 去括名不在盘的不动, 让位
    # ci-glob/占位域。先于 ci-glob —— 精确路径级命中不该轮到占位件遮真图。
    if "{" in want or "}" in want:
        mp = ctx.main_path()
        base = mp.parent if mp is not None else ctx.wdir
        exts = tuple(params.get("exts") or (".tex", ".sty"))
        changed = _debrace_sweep(ctx, exts, base)
        if changed:
            return True, f"de-brace {want}: swept refs in {changed} file(s)"
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
    ``(filedir|wdir)/arg`` 解析到 *其它* 在盘件的引用是同名好图 —— 不动
    (``_rewrite_case_refs``/``includepdf_missing_stub`` 同款守卫, 判据
    细化为「解析到非 f」: f 是拒载件本体, 指向 f 或无解析的引用照常落
    占位)。
    """
    w_d = str(params.get("stub_width") or r"0.6\linewidth")
    h_d = str(params.get("stub_height") or r"0.45\linewidth")
    names = {want, f.name, f.relative_to(ctx.wdir).as_posix()}
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    f_norm = os.path.normpath(f)
    changed = 0
    for tf in ctx.tex_files(exts):
        t = ctx.read(tf)
        if t is None or "\\includegraphics" not in t:
            continue

        def _sub(m: re.Match[str], _tf: Path = tf) -> str:
            arg = m.group(2)
            if not any(_graphic_ref_hit(arg, n) for n in names):
                return m.group(0)
            a = _norm_graphic_name(arg)
            hits = [c for c in (ctx.wdir / a, _tf.parent / a) if safe_is_file(c)]
            if hits and all(os.path.normpath(c) != f_norm for c in hits):
                return m.group(0)  # 引用落到别处在盘同名好图 —— 非本病灶
            w = _opt_dim(m.group(1), "width") or w_d
            h = _opt_dim(m.group(1), "height") or h_d
            box = rf"\fbox{{\rule{{0pt}}{{{h}}}\rule{{{w}}}{{0pt}}}}"
            return f"{box}% fixloop: stub for unreadable {f.name}"

        nt = _INCLUDE_GFX_RE.sub(_sub, t)
        if nt != t:
            ctx.write(tf, nt)
            changed += 1
    return changed


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
# \includepdf 缺件占位 (W66 孤儿裁决 mechmap-2026-09-17)
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

# ════════════════════════════════════════════════════════════════
# xetex 图形域二进制占位 (failmine4-covgap: "Unable to load picture or
# PDF file" 臂 6 格) —— 扩展名决定 xetex image-sniff 路径, EPS 文本写进
# .png/.jpg/.pdf 件名被格式探测拒载, 须真格式字节。三件同构 200x150
# 灰底+边框+对角线 (EPS 占位的像素版), Title/COM 段同痕可辨「图缺」。
# 字节产物经 identify/pdfinfo/gs 结构验证 + xetex \includegraphics
# 真编译实证; 生成器存档 tmp/lane-covgap/gen_ph.py (PNG zlib 程序化
# 合成 / PDF 手写 xref / JPEG magick 生成+手注 COM 段)。
# ════════════════════════════════════════════════════════════════

#: 200x150 RGB PNG (zlib IDAT, tEXt Title 留痕)。
_PNG_PLACEHOLDER = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAMgAAACWCAIAAAAUvlBOAAAAN3RFWHRUaXRsZQBmaXhsb29wIHBs"
    "YWNlaG9sZGVyIChncmFwaGljIGFic2VudCBmcm9tIGUtcHJpbnQpfeIzqwAAA4JJREFUeNrt3UFu"
    "4zAMBVDdH3PIHGV2RafINLEjSiL5/qpAF7E+X9HEsezxRyQgQwWyAtZD5Faew/r+Cx3JbVVfP4/v"
    "mNiSD1U9h4WXfELqBSy25LaqF7DYknuqXsPCS+6ReAsWW3IVw7uw2JJLDC7Awgupq07GJStsURUC"
    "iy2qomDhhVQgLLaoioLFFlVRsPBCKhAWW1RFwWKLqihYeCEVCIut5qoCYbHVWVUsLLx6kloEi62G"
    "qhbBYqubqnWw8OpDagMstpqo2gCLrQ6q9sDCqzapzbDYql3yTlhsFa53Myy8qlZ6BCy26pV5Ciy2"
    "itV4ECy8KlV3HCy2apR2Iiy2CtR1KCy8sld0NCy28pZzOiy2ktaSABZeGatIA4utXCVkgsVWouUn"
    "g9WWV7olp4TVzVbGxWaF1cdW0mUmhlWeV+qlpYdV1Vb2RVWAVc9WgeUUgVVsHmVmMcr8uRd4X1Jp"
    "EMP/EYcNVrU5Ff7wMUp+Yk/0ZW3V8odTQQ4PrArzK/+1QQtYjyN3sHQofPjSjSqwss614RUZo9Xl"
    "TRtv69Ot5OG6OarAyjTvttdSt4b1WHKv887FDjsUPJgDrNN52aYG1nwQVIE1nwVVYE32gRRY86FQ"
    "BdZ8W1SBNZkXUmDNt0UVWPNtUQVWCC9dgQUWWHlUqQssb97BcroBLKrYAiuEFF5gxapiC6xYImyB"
    "FSgDL7CiQLAFVhQFtmz/sv0LrISDt2G13eKXjbynLTcFqfyiYLUYsNsYUcUWWAkn6laRVLEFVrYR"
    "1rblAQIOEqyiA/PIE6occFdYHisHlsFUtlUHVrGR1BiHh41bFFg9Pq7XeL+YFVaT89d5R5MPVsMr"
    "BTIOaDjrY8ndYTW/2DfXmHLAsvUlUQlpYFGVq4ocsKhKV8jpsJBKWs7RsKjKW9G5sKhKXdSJsJAq"
    "UNpxsKiqUd1ZsKgqU+ApsJAqVuYRsKiqV+l+WFSVLHYnLKQKl7wNFlW1q94Di6rytlbDQqoJr6Ww"
    "qOpjax0sqlrZWgELqYa8wmFR1dNWLCyq2tqKgoVUc14hsKhiaz4sqtiaDAspvObDooqt+bCoYmsy"
    "LKTwmg+LKrbmw6KKrcmwkMJrPiyq2JoPiyq2LlF5DQspuYThLVhUyVUSr2FRJTdg/AYLKbnN67+w"
    "qJJPbD2HRZV8aOsnLKRkCq9/YFEls2w9hyUyJWBJSP4CIWwCxuF8Zi8AAAAASUVORK5CYII="
)
#: 单页 PDF 1.4 (5 obj, MediaBox[0 0 200 150], 边框+X stream, Info/Title)。
_PDF_PLACEHOLDER = base64.b64decode(
    "JVBERi0xLjQKJSBmaXhsb29wIHBsYWNlaG9sZGVyIChncmFwaGljIGFic2VudCBmcm9tIGUtcHJp"
    "bnQpCjEgMCBvYmoKPDwvVHlwZS9DYXRhbG9nL1BhZ2VzIDIgMCBSPj4KZW5kb2JqCjIgMCBvYmoK"
    "PDwvVHlwZS9QYWdlcy9LaWRzWzMgMCBSXS9Db3VudCAxPj4KZW5kb2JqCjMgMCBvYmoKPDwvVHlw"
    "ZS9QYWdlL1BhcmVudCAyIDAgUi9NZWRpYUJveFswIDAgMjAwIDE1MF0vQ29udGVudHMgNCAwIFIv"
    "UmVzb3VyY2VzPDw+Pj4+CmVuZG9iago0IDAgb2JqCjw8L0xlbmd0aCA2Nj4+CnN0cmVhbQowLjU1"
    "IGcgMS41IHcKMSAxIDE5OCAxNDggcmUgUwoxIDEgbSAxOTkgMTQ5IGwgUwoxOTkgMSBtIDEgMTQ5"
    "IGwgUwplbmRzdHJlYW0KZW5kb2JqCjUgMCBvYmoKPDwvVGl0bGUoZml4bG9vcCBwbGFjZWhvbGRl"
    "cikvUHJvZHVjZXIoZml4bG9vcCk+PgplbmRvYmoKeHJlZgowIDYKMDAwMDAwMDAwMCA2NTUzNSBm"
    "IAowMDAwMDAwMDYxIDAwMDAwIG4gCjAwMDAwMDAxMDYgMDAwMDAgbiAKMDAwMDAwMDE1NyAwMDAw"
    "MCBuIAowMDAwMDAwMjUxIDAwMDAwIG4gCjAwMDAwMDAzNjQgMDAwMDAgbiAKdHJhaWxlcgo8PC9T"
    "aXplIDYvUm9vdCAxIDAgUi9JbmZvIDUgMCBSPj4Kc3RhcnR4cmVmCjQyOQolJUVPRgo="
)
#: 200x150 灰阶 baseline JPEG (SOI 后手注 FF FE COM 段留痕)。
_JPEG_PLACEHOLDER = base64.b64decode(
    "/9j//gAzZml4bG9vcCBwbGFjZWhvbGRlciAoZ3JhcGhpYyBhYnNlbnQgZnJvbSBlLXByaW50Kf/g"
    "ABBKRklGAAEBAAABAAEAAP/bAEMACAYGBwYFCAcHBwkJCAoMFA0MCwsMGRITDxQdGh8eHRocHCAk"
    "LicgIiwjHBwoNyksMDE0NDQfJzk9ODI8LjM0Mv/AAAsIAJYAyAEBIgD/xAAYAAEBAQEBAAAAAAAA"
    "AAAAAAAABwYFA//EACkQAQAAAwgDAQEAAgMAAAAAAAABAwQCBQcXM1R0sZOU0QYREmFxgeH/2gAI"
    "AQEAAD8A8/2n7So/MVcIxhUTrM6dMswhZnxs/wCP8j/6yucM3aVftx+GcM3aVftx+GcM3aVftx+G"
    "cM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVf"
    "tx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM"
    "3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+GcM3aVftx+NV+L/AGlR+nq4xhCok2ZM6XZjC1Pj"
    "a/y/sY/GVxh16bkTu4JaAAAAAAAKlg9r1XIk9xMYdem5E7uCWgAAAAAACpYPa9VyJPcTGHXpuRO7"
    "gloAAAAAAAqWD2vVciT3Exh16bkTu4JaAAAAAAAKlg9r1XIk9xMYdem5E7uCWgAAAAAACpYPa9Vy"
    "JPcTGHXpuRO7gloAAAAAAAqWD2vVciT3Exh16bkTu4JaAAAAAAAKlg9r1XIk9xMYdem5E7uCWgAA"
    "AAAACpYPa9VyJPcTGHXpuRO7gloAAAAAAAqWD2vVciT3Exh16bkTu4JaAAAAAAAKlg9r1XIk9xMY"
    "dem5E7uCWgAAAAAACpYPa9VyJPcTGHXpuRO7gloAAAAAAAqWD2vVciT3Exh16bkTu4JaAAAAAAAK"
    "lg9r1XIk9xMYdem5E7uCWgAAAAAACpYPa9VyJPcTGHXpuRO7gloAAAAAAAqWD2vVciT3Exh16bkT"
    "u4JaAAAAAAAKlg9r1XIk9xMYdem5E7uCWgAAAAAACpYPa9VyJPcVJv38NJvyst2q2VTz7FibbtS4"
    "WrduH8/sf9f8QcnKi6NhSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6N"
    "hSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6NhSeWYZUXRsKTyzDKi6N"
    "hSeWY6txfhpNxVVm3QyqeTZtTLFqZCzbtx/v8j/v/t//2Q=="
)

#: ``\epsfig{file=X.eps, scale=..}`` / ``\psfig{figure=X}`` / ``\epsfbox{X}``
#: kv/裸参引用点 —— ``_INCLUDE_GFX_RE`` 吃不到 kv 形, 独立一柄。
_EPS_KV_RE = re.compile(r"\\(?:epsfig|psfig|epsffile|epsfbox)\s*\{([^}]*)\}")
#: kv 形大括号串内的 ``file=``/``figure=`` 值。
_KV_FILE_RE = re.compile(r"(?:file|figure)\s*=\s*([^,\s}]+)")

# ═══ 宏间接引用 (w13 B3, 2505.06480): 包装宏内 #N 形参回填 ═══
#: ``\newcommand{\fig}[6]{..\includegraphics{..#4..}..}`` 族 def 站 —
#: 字面 ``\includegraphics`` 引用点为空, 引用真身躲在 ``\fig{..}{01-abstract}``
#: 调用位 #N 实参。g1=name, g2=arity, g3=可选首参 default 位, g4=body
#: (两层内层花括; ``\fbox{\includegraphics{#2}}`` 级嵌套可收, 更深截断
#: —— 保守)。
_GFX_DEF_NC_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)\*?"
    r"\s*\{?\\([a-zA-Z@]+)\}?\s*"
    r"(?:\[\s*(\d)\s*\])?\s*(\[[^\]]*\]\s*)?"
    r"\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}"
)
#: ``\def``/``\gdef``/``\edef``/``\xdef`` 形参记号形 —— g2 形参串
#: (无括号无 cs 无换行; ``\long`` 等前缀词在 ``\def`` 前自落不匹配位)。
_GFX_DEF_PRIM_RE = re.compile(
    r"\\[egx]?def\\([a-zA-Z@]+)([^\\{}\n]*?)"
    r"\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}"
)
#: 调用位花括实参 (两层内层花括 —— caption ``\textbf{..}`` 嵌套可过)。
_GFX_ARG_RE = re.compile(r"\s*\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}")
_GFX_OPT_ARG_RE = re.compile(r"\s*\[([^\]]*)\]")
#: arg 模板内 ``#<1-9>`` 形参位。
_GFX_PARAM_REF_RE = re.compile(r"#([1-9])")


def _gfx_macro_templates(ctx: LoopCtx) -> dict[str, dict[str, Any]]:
    r"""工程内包装宏 def 站 → {name: {"opt": 有无可选首参, "items": [(need, arg模板)]}}。

    def 体里 ``\includegraphics`` arg 含 ``#<n>`` 的条目入册,
    need = 模板内最大形参位 (调用位实参数不够即拒解)。
    """
    out: dict[str, dict[str, Any]] = {}
    for f in ctx.tex_files((".tex", ".sty")):
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)  # 注释/verbatim 内 def 不算 (fig 双胎注释先例)
        for m in _GFX_DEF_NC_RE.finditer(masked):
            rec = out.setdefault(m.group(1), {"opt": False, "items": []})
            if m.group(3) is not None:
                rec["opt"] = True
            _gfx_template_items(rec, m.group(4))
        for m in _GFX_DEF_PRIM_RE.finditer(masked):
            rec = out.setdefault(m.group(1), {"opt": False, "items": []})
            _gfx_template_items(rec, m.group(3))
    return {k: v for k, v in out.items() if v["items"]}


def _gfx_template_items(rec: dict[str, Any], body: str) -> None:
    r"""扫描 def 体内 ``\includegraphics`` 含 ``#<n>`` 的 arg 模板入册。"""
    for im in _INCLUDE_GFX_RE.finditer(body):
        arg = im.group(2)
        need = max((int(d) for d in _GFX_PARAM_REF_RE.findall(arg)), default=0)
        if not need:
            continue
        if arg.startswith("{") and arg.endswith("}"):
            arg = arg[1:-1]  # ``{#4}`` 内层花括不属名面 —— 剥一层对齐三口径
        rec["items"].append((need, arg))


def _gfx_call_args(masked: str, pos: int, rec: dict[str, Any]) -> list[str | None]:
    r"""调用位连续花括实参扫到 need 上限 (可选首参缺省记 ``None`` 拒解)。"""
    args: list[str | None] = []
    if rec["opt"]:
        om = _GFX_OPT_ARG_RE.match(masked, pos)
        if om is not None:
            args.append(om.group(1))
            pos = om.end()
        else:
            args.append(None)  # opt 首参走 default → #1 模板拒解
    need_max = max(n for n, _ in rec["items"])
    while len(args) < need_max:
        am = _GFX_ARG_RE.match(masked, pos)
        if am is None:
            break
        args.append(am.group(1))
        pos = am.end()
    return args


def _gfx_resolve_hit(args: list[str | None], rec: dict[str, Any], want: str) -> bool:
    r"""#N 模板回填调用位实参 → ``_graphic_ref_hit`` 复核 (残 ``#`` 即拒)。"""
    for need, template in rec["items"]:
        if len(args) < need:
            continue
        resolved = template
        for i, a in enumerate(args, 1):
            if a is not None:
                resolved = resolved.replace(f"#{i}", a)
        if "#" not in resolved and _graphic_ref_hit(resolved, want):
            return True
    return False


def _macro_graphic_ref_hit(
    ctx: LoopCtx, want: str, templates: dict[str, dict[str, Any]]
) -> bool:
    r"""``\name`` 调用位花括实参回填 #N 模板 → ``_graphic_ref_hit`` 复核。

    单层解析 (宏内再调宏不递归); 回填后模板残 ``#`` (超 arity 引用/
    ``##`` 嵌套 def) 即拒 —— 命中判定只走字面已解形。
    """
    call_res = {
        n: re.compile(r"\\" + re.escape(n) + r"(?![a-zA-Z@])") for n in templates
    }
    for f in ctx.tex_files((".tex", ".sty")):
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)
        for name, rec in templates.items():
            for m in call_res[name].finditer(masked):
                args = _gfx_call_args(masked, m.end(), rec)
                if _gfx_resolve_hit(args, rec, want):
                    return True
    return False


def _has_live_graphic_ref(
    ctx: LoopCtx, want: str, templates: dict[str, dict[str, Any]] | None = None
) -> bool:
    r"""存活图形调用点 arg 与 want 命中复核 (``_graphic_ref_hit`` 三口径)。

    ``\includegraphics``/epsfig/psfig 族全覆盖 —— 无扩展名 payload 的
    图形域证据面 (``\input`` 系裸缺件没有图形调用点, 不落占位)。
    字面扫空后再走宏间接臂: def 站 ``\includegraphics{..#N..}`` 模板
    对 ``\name{...}`` 调用位实参回填 (2505.06480 ``\fig`` 实证)。
    ``templates`` 传 ``_ProjectScan.templates()`` 缓存 —— sweep 内逐
    want 复用同一份 def 站册 (mask_tex 全工程扫只付一次)。
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
    if templates is None:
        templates = _gfx_macro_templates(ctx)
    return bool(templates) and _macro_graphic_ref_hit(ctx, want, templates)


#: 编译 log 全量枚举缺图签名的两形 —— nonstop 编译单趟即列全部缺件
#: (``File `X' not found`` 兼中 pdftex.def ": using draft setting" 前缀与
#: LaTeX Warning/Error 两阶; ``Unable to load picture or PDF file 'X'`` 是
#: xetex 图形域专属)。多缺件格逐轮单补烧穿轮次上限 (v3all
#: 2501.01329/2501.01425 实证: 8 轮逐件补, 末件占位写于末次编译后 →
#: 差一轮翻 clean) —— 一次点火同签全补。
_LOG_MISS_GFX_RE = re.compile(
    r"Unable to load picture or PDF file '([^']+)'|File `([^']+)' not found"
)

# ═══ 源侧枚举 (haltsweep): halt_on_error 下 log 只曝首件, log 扫不够 ═══

#: ``\graphicspath{{d1/}{d2/}}`` 声明点 (遮盖视图; 多次声明取并集=保守超集)。
_GRAPHICSPATH_RE = re.compile(r"\\graphicspath\s*\{((?:[^{}]|\{[^{}]*\})*)\}")
_GSPATH_DIR_RE = re.compile(r"\{([^{}]*)\}")

#: 枚举只收字面 arg —— 宏拼名/特殊字符形 (``\imgdir/x``) 静态不可判,
#: 留在 log 驱动臂 (``_LOG_MISS_GFX_RE``) 的既有逐件路径。
_ENUM_ARG_BAD_RE = re.compile(r"[\\%#~^&$'\"`\x00-\x1f]")


def _graphicspath_dirs(ctx: LoopCtx) -> list[PurePosixPath]:
    r"""全工程活 ``\graphicspath`` 目录并集 —— 超集只减误判 (不误占位真图)。"""
    dirs: list[PurePosixPath] = []
    for f in ctx.tex_files():
        t = ctx.read(f)
        if t is None or "\\graphicspath" not in t:
            continue
        for m in _live_matches(_GRAPHICSPATH_RE, t):
            for raw in _GSPATH_DIR_RE.findall(m.group(1)):
                d = _norm_graphic_name(raw).rstrip("/")
                pp = PurePosixPath(d)
                if (
                    d
                    and not pp.is_absolute()
                    and ".." not in pp.parts
                    and not _ENUM_ARG_BAD_RE.search(d)
                    and pp not in dirs
                ):
                    dirs.append(pp)
    return dirs


def _disk_hit(ctx: LoopCtx, p: Path, disk: set[str] | None) -> bool:
    """快照成员检 + 实况兜底。

    ``disk`` (wdir 相对 posix 名集) 在册免 stat; 脱册回落 ``safe_is_file``
    —— sweep 内新落盘件与 symlink 径件不受快照盲区。
    """
    if disk is not None:
        try:
            if p.relative_to(ctx.wdir).as_posix() in disk:
                return True
        except ValueError:
            pass
    return safe_is_file(p)


def _enum_missing_graphics(
    ctx: LoopCtx, eng: Engine | None, base: Path, disk: set[str] | None = None
) -> list[str]:
    r"""源侧枚举存活图形引用的全部缺件名 —— halt_on_error 盲区补全。

    fixloop 编译走 ``halt_on_error`` —— 每轮 log 只曝首个缺件
    (``_LOG_MISS_GFX_RE`` 扫不出未达段), 逐 payload 补件在多缺件格
    烧穿轮次上限 (v3all 2501.01425: 8 轮补 8 件, log 从未触及的第 9+
    件仍在)。对每张 tex: 活 ``\includegraphics``/epsfig 族字面 arg →
    解析位 (filedir / main_dir / wdir / ``\graphicspath`` 目录) 全 miss
    即缺件候选; 带后缀 arg 再过 ``eng.probe_file`` (kpathsea texmf 树
    —— 防占位遮蔽 texlive 随发图如 mwe ``example-image.pdf``; 无后缀
    arg 免探: 同名 texmf 图按 ``\Gin@extensions`` 扩展序先中, 落盘
    ``.eps`` 永不遮蔽)。非字面 arg 跳过 —— 静态不可判, 归 log 臂。
    ``disk`` 传 ``_ProjectScan.disk`` 快照: arg×root×ext 成员检免逐件
    stat, 脱册路径仍实况兜底 (与全 stat 口径语义等价)。
    """
    gspath = _graphicspath_dirs(ctx)
    wants: list[str] = []
    for f in ctx.tex_files():
        t = ctx.read(f)
        if t is None or not any(
            k in t for k in ("\\includegraphics", "\\epsf", "\\psfig")
        ):
            continue
        args = [m.group(2) for m in _live_matches(_INCLUDE_GFX_RE, t)]
        for m in _live_matches(_EPS_KV_RE, t):
            kv = _KV_FILE_RE.search(m.group(1))
            args.append(kv.group(1) if kv else m.group(1))
        for arg in args:
            a = _norm_graphic_name(arg)
            if not a or _ENUM_ARG_BAD_RE.search(a):
                continue
            pp = PurePosixPath(a)
            if pp.is_absolute() or ".." in pp.parts:
                continue
            exts = ("",) if pp.suffix else ("", *_GRAPHIC_EXTS)
            roots = [f.parent, base, ctx.wdir]
            roots += [r / g for g in gspath for r in (f.parent, base, ctx.wdir)]
            if any(
                _disk_hit(ctx, root / f"{a}{e}", disk) for root in roots for e in exts
            ):
                continue
            if pp.suffix and eng is not None and eng.probe_file(a, cwd=base):
                continue  # texmf 树可解 (mwe 族) —— 占位会遮蔽真件, 跳过
            if a not in wants:
                wants.append(a)
    return wants


class _ProjectScan:
    """单轮点火共享的工程文件快照 + 懒取宏模板缓存 —— 占位 sweep 免逐 want 重扫。

    ``files``/``disk`` 走 ``_iter_project_files`` 排除面 —— ``disk`` 为
    wdir 相对 posix 名集, 供 ``_enum_missing_graphics`` 成员检免逐
    arg×root×ext stat。sweep 落盘件经 ``add`` 入册, 后续 want 的
    ci/去括救检立见 (与逐件 rglob 读到新件同语义)。``templates()``
    懒取 ``_gfx_macro_templates`` —— 只有无后缀 want 的活引用复核需要。
    """

    def __init__(self, ctx: LoopCtx) -> None:
        self._ctx = ctx
        self.files = _iter_project_files(ctx)
        self.disk = {p.relative_to(ctx.wdir).as_posix() for p in self.files}
        self._templates: dict[str, dict[str, Any]] | None = None

    def templates(self) -> dict[str, dict[str, Any]]:
        """``_gfx_macro_templates`` 结果缓存 —— 首取后全 sweep 复用。"""
        if self._templates is None:
            self._templates = _gfx_macro_templates(self._ctx)
        return self._templates

    def add(self, p: Path) -> None:
        """Sweep 内新落盘件入册。"""
        try:
            rel = p.relative_to(self._ctx.wdir).as_posix()
        except ValueError:
            return
        if rel not in self.disk:
            self.disk.add(rel)
            self.files.append(p)


def _stub_graphic_at(  # noqa: C901, PLR0911, PLR0912 - 逐门 decline note 即归因
    ctx: LoopCtx, base: Path, want: str, *, rescue_check: bool, scan: _ProjectScan
) -> tuple[bool, str]:
    r"""单件缺图占位落盘 —— ``graphic_missing_placeholder`` 逐 payload 核。

    ``rescue_check=True`` (log 扫描补件): 去括名/ci-变体在盘 → decline
    让路 case_link 下轮按真名修复 —— 占位是缺件兜底不该遮可救真图。
    首错 payload 不做此检: case_link@17 本轮已先评 (含 kv 形引用
    ``_INCLUDE_GFX_RE`` 够不着时占位落名仍是唯一编译救法)。
    ``scan`` 携带本轮共享文件快照/宏模板缓存 —— 逐 want 不重扫全树。
    """
    suffix = PurePosixPath(want).suffix.lower()
    if suffix and suffix not in _GRAPHIC_EXTS:
        return False, f"{want}: not a known graphic ext"
    if not suffix:
        if not _has_live_graphic_ref(ctx, want, scan.templates()):
            return False, f"{want}: no live graphic ref — not graphic domain"
        want += ".eps"
        suffix = ".eps"
    if ".." in PurePosixPath(want).parts:
        return False, f"{want}: path traversal rejected"
    f = base / want
    try:
        f.resolve().relative_to(ctx.wdir.resolve())
    except (OSError, RuntimeError, ValueError):
        return False, f"{want}: escapes wdir"
    if safe_is_file(f):
        return False, f"{want}: resolved meanwhile"
    if rescue_check:
        d = want.replace("{", "").replace("}", "")
        if d != want and safe_is_file(base / d):
            return False, f"{want}: de-braced file on disk — case_link domain"
        if _find_graphic_ci(ctx, want, scan.files) is not None:
            return False, f"{want}: ci-variant on disk — case_link domain"
    blob: str | bytes
    if suffix in _EPS_EXTS:
        blob = _EPS_PLACEHOLDER
    elif suffix == ".pdf":
        blob = _PDF_PLACEHOLDER
    elif suffix == ".png":
        blob = _PNG_PLACEHOLDER
    elif suffix in (".jpg", ".jpeg"):
        blob = _JPEG_PLACEHOLDER
    else:
        # _GRAPHIC_EXTS 日后扩面时的保守缺省 —— 格式不符的占位即废件
        return False, f"{want}: no placeholder asset for {suffix}"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(blob, str):
            ctx.write(f, blob)
        else:
            f.write_bytes(blob)
            ctx.invalidate(f)
    except OSError as e:
        return False, f"{want}: write failed ({e})"
    scan.add(f)  # 落盘件入册 —— 后续 want 的 ci/去括救检可见
    return True, f"placeholder {suffix.lstrip('.').upper()} at {want}"


def _stub_sweep(
    ctx: LoopCtx,
    base: Path,
    wants: list[str],
    *,
    rescue_skip_first: bool = False,
    scan: _ProjectScan | None = None,
) -> tuple[bool, str]:
    r"""Wants 全量逐件过 ``_stub_graphic_at`` 落占位 → (有落盘, 汇总 note)。

    ``rescue_skip_first=True``: 首件 (本轮首错 payload) 免 rescue_check
    —— case_link 本轮已先评; 其余 sweep 件带检, 去括/ci 变体在盘时让位。
    ``scan`` 缺省自建 —— 调用点已建 (``_enum_missing_graphics`` 同快照)
    时传入复用, 一轮点火只付一次全树扫。note 组装: 首件落盘 note +
    ``(+N swept)`` + ``| declined: ...``。
    """
    if scan is None:
        scan = _ProjectScan(ctx)
    wrote: list[str] = []
    declined: list[str] = []
    for i, w in enumerate(wants):
        ok, note = _stub_graphic_at(
            ctx, base, w, rescue_check=i > 0 or not rescue_skip_first, scan=scan
        )
        (wrote if ok else declined).append(note)
    if not wrote:
        return False, declined[0] if declined else "no stub written"
    head = wrote[0]
    if len(wrote) > 1:
        head += f" (+{len(wrote) - 1} swept)"
    if declined:
        head += f" | declined: {'; '.join(declined)}"
    return True, head


def graphic_missing_placeholder(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""图档真缺件 → ``<main_dir>/<payload>`` 落最小合法格式占位。

    graphic_ext_relax 残家 (failmine3 8 格) + xetex "Unable to load
    picture or PDF file" 残家 (failmine4-covgap 6 格): sibling 不存在时
    剥扩展名也救不了 —— 修复不是改源而是补档 (xbb_pregen 旁件同形)。
    站点改写形盖不全调用面: ``\epsfig{file=X.eps}`` kv 形与宏体
    ``#1.eps`` 间接名 (payload 是展开后真名, 源码字面不可锚) 只能由
    「真名落盘」治; 子目录路径 (``FIGS/``/``images/``) mkdir 随行。

    占位格式按 payload 扩展名分发 (xetex image-sniff 认格式字节):
    ``.eps/.epsf/.epsi/.ps/.mps`` → 文本 EPS; ``.png/.jpg/.jpeg/.pdf``
    → 同构图二进制占位; 无扩展名 (ext-relax 残家 vanilla 解析序) 须
    先过 ``_has_live_graphic_ref`` 复核才补 ``.eps`` —— ``\input`` 系
    裸缺件不落图占位。落盘基址 = ``main_path().parent`` (TeX 的
    cwd 解析位; main 未知退回 wdir) —— main 住子目录时 wdir 根位
    对 TeX 不可见。payload 是 log 派生路径 —— 双层守卫: ``..`` 段拒
    + resolve 后仍须在 wdir 内 (防穿越写); 解析位已有档 (大小写
    变体/前轮已补) → False 让路。

    micro2 扩面 (v3all 2501.01329/2501.01425): 本轮 log 全量枚举同签
    缺图一次补齐 —— nonstop 编译单趟已列全部, 逐轮单补在多缺件格
    烧穿轮次上限。log 缺席/单件时行为与旧逐件版等价。

    haltsweep 扩面 (v3all 8 格普查): fixloop 编译走 halt_on_error —
    每轮 log 只曝首个缺件, log 扫臂实际仍逐轮单补 (2501.01425 烧
    8 轮, 余 3 件 log 从未触及)。补 ``_enum_missing_graphics`` 源侧
    枚举 —— 全工程活引用静态解析, 一轮尽列已知缺件。
    """
    del params
    want = _norm_graphic_name(payload or "")
    if not want:
        return False, "no graphic payload"
    mp = ctx.main_path()
    base = mp.parent if mp is not None else ctx.wdir
    wants = [want]
    for m in _LOG_MISS_GFX_RE.finditer(_fixloop_log(ctx)):
        w = _norm_graphic_name(m.group(1) or m.group(2))
        if w and w not in wants:
            wants.append(w)
    scan = _ProjectScan(ctx)
    for w in _enum_missing_graphics(ctx, eng, base, scan.disk):
        if w not in wants:
            wants.append(w)
    return _stub_sweep(ctx, base, wants, rescue_skip_first=True, scan=scan)


# ════════════════════════════════════════════════════════════════
# raster-in-pdf 伪装件 (singlesweep mislabeled-raster-as-pdf 6 格):
# e-print 船货 ``X.pdf`` 实为 PNG/JPEG 字节 —— 引擎按后缀走 pdf
# 链拒载 (xetex "Unable to load picture or PDF file 'X.pdf'")。
# ════════════════════════════════════════════════════════════════

#: 伪装件 magic → 真格式扩展名 (graphicx 原生可读面; ``.jpeg``
#: 同收 ``\Gin@extensions`` 但 ``.jpg`` 是通用落名)。
_RASTER_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)


def _sniff_raster_ext(p: Path) -> str | None:
    """文件头 magic → raster 扩展名; 非 PNG/JPEG 伪装 (真 pdf/其它) → None。"""
    try:
        with p.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    for magic, ext in _RASTER_MAGICS:
        if head.startswith(magic):
            return ext
    return None


def _mislabeled_pdf_targets(ctx: LoopCtx) -> list[tuple[Path, str]]:
    r"""``wdir`` 全量 ``*.pdf`` magic 复核 → ``[(path, real_ext)]``。

    排除面与 ``_pdf_asset_targets`` 同口径: dot-部件 (``.fixloop-*``
    底板快照)、``_texmf``/``_tect_out`` 封装树、main 输出 pdf
    (重编译自生非内嵌图件)。真 ``%PDF`` 头件不落表 —— 引擎可读。
    """
    return [
        (p, ext)
        for p in _pdf_asset_targets(ctx)
        if (ext := _sniff_raster_ext(p)) is not None
    ]


def _rewrite_mislabeled_refs(
    ctx: LoopCtx, exts: tuple[str, ...], renamed: dict[str, str]
) -> int:
    r"""逐 tex: 指向已改名件的显式 ``.pdf`` arg → 后缀换真格式名 → 改写文件数。

    arg 只换尾缀不动目录/stem —— 改名保路径位, 原解析机制
    (filedir/main_dir/graphicspath) 对新名同效。无扩展名 arg 不收
    (``{fig5}`` ← ``fig5.pdf``): ``\Gin@extensions`` 序含 .png/.jpg
    改名后自解 (1607.00405 实证)。``\includepdf`` 不扫 —— pdfpages
    只收真 pdf, 改名后其缺件归 includepdf_missing_stub 诚实降级。
    """

    def _fn(t: str) -> tuple[str, int]:
        if "\\includegraphics" not in t:
            return t, 0
        out: list[str] = []
        prev = 0
        n = 0
        for m in _live_matches(_INCLUDE_GFX_RE, t):
            arg = m.group(2)
            if PurePosixPath(_norm_graphic_name(arg)).suffix.lower() != ".pdf":
                continue
            new_rel = next(
                (new for old, new in renamed.items() if _graphic_ref_hit(arg, old)),
                None,
            )
            if new_rel is None:
                continue
            new_arg = re.sub(
                r"(?i)\.pdf(\s*)$", PurePosixPath(new_rel).suffix + r"\1", arg
            )
            out.append(t[prev : m.start(2)])
            out.append(new_arg)
            prev = m.end(2)
            n += 1
        if not n:
            return t, 0
        out.append(t[prev:])
        return "".join(out), n

    return _map_tex_files(ctx, exts, _fn)


def raster_pdf_rename(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``.pdf`` 名实为 PNG/JPEG 字节 → 改名真扩展名 + ``\includegraphics`` arg 后缀改写。

    singlesweep mislabeled-raster-as-pdf 6 格 (1607.00405 fig5.pdf=PNG
    / 2310.01082 mlp_noise.pdf=JPEG / 2504.15280 fig0-all-angles 与
    fig2-question 双 PNG): e-print 船货 ``X.pdf`` 字节非 ``%PDF`` ——
    引擎按后缀走 pdf 链, 格式不符拒载 (``missing_graphic|X.pdf``)。
    ``graphic_repair`` 的 gs 重蒸馏对光栅字节同样失败 → ``\fbox``
    stub 丢真图; 改名+引用改写是全救。全量扫一次点火 ——
    halt_on_error 每轮只曝首件 (2504.15280 双伪装件实证), 逐轮修
    会烧穿轮次上限。目标位撞名 (``X.png`` 已在盘) 逐件 decline
    不覆写; 无一改成则整体 False 让 repair/stub 域接手。
    """
    del eng, payload
    targets = _mislabeled_pdf_targets(ctx)
    if not targets:
        return False, "no raster-bytes .pdf in fileset"
    renamed: dict[str, str] = {}
    skipped: list[str] = []
    for src, ext in targets:
        dst = src.with_suffix(ext)
        if dst.exists():
            skipped.append(f"{dst.name} exists")
            continue
        try:
            src.rename(dst)
        except OSError as e:
            skipped.append(f"{src.name}({e})")
            continue
        ctx.invalidate(src)
        ctx.invalidate(dst)
        renamed[src.relative_to(ctx.wdir).as_posix()] = dst.relative_to(
            ctx.wdir
        ).as_posix()
    if not renamed:
        return False, f"0/{len(targets)} renamed ({'; '.join(skipped)})"
    exts = tuple(params.get("exts") or (".tex", ".sty"))
    changed = _rewrite_mislabeled_refs(ctx, exts, renamed)
    note = (
        f"renamed {len(renamed)}/{len(targets)} raster-as-pdf "
        f"({', '.join(renamed.values())}), refs rewritten in {changed} file(s)"
    )
    if skipped:
        note += f"; skipped: {'; '.join(skipped)}"
    return True, note


# ═══ xdvipdfmx 驱动期缺图域 (failmine4 drvstage lane 2026-09-20) ═══

#: 驱动 fatal 行的缺图名捕获 —— ``Image inclusion failed. Could not
#: find file: X`` 名字恒占行尾 (xdvipdfmx fatal 单行不折行, probe4
#: 实证 120+col 路径仍整行)。
_DRV_IMG_MISS_RE = re.compile(
    r"Image inclusion failed\.\s*Could not find file:\s*([^\n]+)"
)


def driver_missing_image_stub(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Image inclusion failed`` 驱动期缺图 fatal → 解析位落占位件。

    failmine4 drvstage 4 格 (2501.01611/2502.00335/2504.06306/
    2505.07205): tex 趟净 (``.xbb`` 旁件供 bbox / ``\special{psfile}``
    裸递串 / nonstop 先错已修后的残轮) 但 xdvipdfmx 嵌入期找不到
    图档 —— ``*: fatal:`` 只走合并 stdout 不进 .log, ``_report_of``
    归一成 ``!`` 行后 taxonomy 无头模 → ``other`` 类目派发; 归一化
    漏形由 ``_round_cat`` driver_fatal 臂兜底 (payload=原始 fatal
    行)。tex 侧 ``!`` 签名臂群 (graphic_missing_placeholder@17.6
    等) 对此面零可见 —— 驱动名只在 stdout_tail/err_head/payload。

    名源双面: ``other`` 轮读 ``ctx.err_head`` (归一 ``!`` 行+ctx),
    ``driver_fatal`` 轮读 ``payload``。名经 ``_norm_graphic_name``
    规整后逐件过 ``_stub_graphic_at`` 全守卫 (ext 白名单/``..`` 拒/
    wdir 逃逸拒/已在盘 decline=幂等); ``rescue_check=True`` —— 去
    括/ci 变体在盘时让位不落假图遮真件 (占位是缺件兜底; 驱动期
    ci 残家属后续专用臂域, 非本臂假件理)。落盘基址同 tex 侧:
    ``main_path().parent`` (xelatex cwd = main 所在目录)。

    补 ``_enum_missing_graphics`` 源侧枚举 (haltsweep 同件): 驱动
    每轮 fatal 只曝首件, 而 ``other`` 轮 ``applied`` dedup 键恒为
    ``{rid}:None`` —— 单补一件即封再派发, 多缺件格 (2501.01611:
    shufflenet+model 双缺) 会卡 stuck。一轮尽列已知缺件。
    """
    del params
    blob = (payload or "") + "\n" + (ctx.err_head or "")
    wants: list[str] = []
    for m in _DRV_IMG_MISS_RE.finditer(blob):
        w = _norm_graphic_name(m.group(1))
        if w and w not in wants:
            wants.append(w)
    if not wants:
        return False, "no driver missing-image name"
    mp = ctx.main_path()
    base = mp.parent if mp is not None else ctx.wdir
    scan = _ProjectScan(ctx)
    for w in _enum_missing_graphics(ctx, eng, base, scan.disk):
        if w not in wants:
            wants.append(w)
    return _stub_sweep(ctx, base, wants, scan=scan)
