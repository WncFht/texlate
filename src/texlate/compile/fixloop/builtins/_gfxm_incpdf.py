r"""builtins._gfxm_incpdf — ``\includepdf`` 缺件占位域 (gfx_missing 拆分)。

``includepdf_missing_stub``: pdfpages 缺件整调用改写
``\clearpage\null`` 空页占位 —— 与图像 ``\fbox`` stub 分语义
(翻译管线对 includepdf 区整体跳过同调)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins._gfxm_caselink import (
    _INCLUDE_PDF_RE,
    _graphic_ref_hit,
)
from texlate.compile.fixloop.builtins.common import _live_matches
from texlate.compile.fixloop.builtins.graphics import _norm_graphic_name
from texlate.textutil import safe_is_file

if TYPE_CHECKING:
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine


__all__ = [
    "_live_matches",
    "includepdf_missing_stub",
]


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
