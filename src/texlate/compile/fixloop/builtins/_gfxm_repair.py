r"""builtins._gfxm_repair — 在盘拒载分级修复域 (gfx_missing 拆分)。

``graphic_repair``: ``.pdf`` 先 ``gs -sDEVICE=pdfwrite`` 重蒸馏
(``_try_gs_redistill`` 归 graphics 单源), 不可救降级
``\includegraphics`` → ``\fbox`` 占位框 (``_stub_graphic_refs``,
W/H 取 opts 尺寸)。
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins._gfxm_caselink import (
    _INCLUDE_GFX_RE,
    _find_graphic_ci,
    _graphic_ref_hit,
)
from texlate.compile.fixloop.builtins.graphics import (
    _norm_graphic_name,
    _try_gs_redistill,
)
from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine


__all__ = [
    "_opt_dim",
    "_stub_graphic_refs",
    "_try_gs_redistill",
    "graphic_repair",
]


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
