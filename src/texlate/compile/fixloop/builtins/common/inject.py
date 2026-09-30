r"""builtins.common.inject — 主文件锚位注入原语 (common 拆分)。

``_inject_after_docclass`` (``\documentclass`` 逐缝后注, 幂等) /
``_inject_before_anchor`` (首个活锚行首前注, ``depth0``/``strict_first``/
``fallback`` 三旋钮) / ``_inject_before_begindoc`` (``\begin{document}``
锚特化, 导言区末位注入点)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from texlate.compile._docseams import find_docclass_ends
from texlate.compile.fixloop.builtins.common.sites import _is_live
from texlate.textutil import BEGIN_DOC_RX, iter_depth0, mask_tex

if TYPE_CHECKING:
    import re
    from collections.abc import Callable

    from texlate.compile.fixloop.engine import LoopCtx

__all__ = [
    "BEGIN_DOC_RX",
    "_inject_after_docclass",
    "_inject_before_anchor",
    "_inject_before_begindoc",
    "cast",
    "find_docclass_ends",
    "iter_depth0",
]


def _inject_after_docclass(ctx: LoopCtx, snippet: str) -> bool:
    r"""主文件每个 ``\documentclass`` 缝后注入 snippet（幂等）。

    复用 inject.find_docclass_ends：分支选择形态（``\ifpdf A \else B \fi``
    双 docclass）逐缝注入——静态不判死活，活臂生效死臂随分支跳过；
    宏体/depth>0 命中与注释命中天然排除，跨行 ``[opt]{cls}``（revtex
    五选一注释穿插）落在配对 ``}`` 行尾而非首行尾。无 docclass 行则
    退文件头（``\AtBeginDocument`` 类 snippet 前定义也合法）。

    缝位是行尾换行**之后** (eol+1)——docclass 行尾的 ``%`` 注释
    (``%!TEX program`` 类编辑器 pragma 常见) 会把行内注入整段吞成
    死文本 (1404.0346 实证: applied=True 但 snippet 在注释里)。
    """
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if main is None or t is None or snippet in t:
        return False
    hits = find_docclass_ends(t)
    if not hits:
        ctx.write(main, snippet + "\n" + t)
        return True
    out, delta = t, 0
    for pos, _ln, _cmd in hits:
        at = pos + delta
        if at < len(out) and out[at] == "\n":
            at += 1
            piece = snippet + "\n"
        else:  # docclass 是末行且无尾换行 —— 先补换行再落 snippet
            piece = "\n" + snippet + "\n"
        out = out[:at] + piece + out[at:]
        delta += len(piece)
    ctx.write(main, out)
    return True


def _inject_before_anchor(  # noqa: PLR0913 - 锚/depth0/strict_first/fallback 四旋钮各叶语义位
    ctx: LoopCtx,
    snippet: str,
    anchor: re.Pattern[str],
    *,
    depth0: bool = False,
    strict_first: bool = False,
    fallback: str | Callable[[LoopCtx, str], bool] | None = None,
) -> bool:
    r"""主文件首个活 ``anchor`` 命中行首前注入 snippet (幂等)。

    遮盖视图找锚: ``depth0`` 走 ``iter_depth0`` (def 体/花括组内命中不算,
    csfix docclass/paralong begindoc 口径), 缺省 ``finditer`` 全命中
    (misschar begindoc 口径); ``_is_live`` 复核剔注释/verbatim 死命中。
    ``strict_first`` 只验首个遮盖命中 (shim begindoc 口径: 首命中落死区
    不续扫, 视同无锚直退 ``fallback``)。

    无可用锚时 ``fallback`` 分派: ``None`` → False; ``"head"`` → 文件头
    注入 (csfix docclass 臂: preamble 顶仍先于一切 cls 执行); callable →
    委派 (shim: ``_inject_after_docclass``)。
    """
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if main is None or t is None or snippet in t:
        return False
    masked = mask_tex(t)
    pos: int | None = None
    if strict_first:
        m = anchor.search(masked)
        if m is not None and _is_live(m, masked, t):
            pos = t.rfind("\n", 0, m.start()) + 1
    else:
        hits = iter_depth0(anchor, masked) if depth0 else anchor.finditer(masked)
        for m in hits:
            if _is_live(m, masked, t):
                pos = t.rfind("\n", 0, m.start()) + 1
                break
    if pos is None:
        if fallback is None:
            return False
        if fallback == "head":
            ctx.write(main, snippet + "\n" + t)
            return True
        return cast("Callable[[LoopCtx, str], bool]", fallback)(ctx, snippet)
    ctx.write(main, t[:pos] + snippet + "\n" + t[pos:])
    return True


def _inject_before_begindoc(
    ctx: LoopCtx,
    snippet: str,
    *,
    depth0: bool = False,
    strict_first: bool = False,
    fallback: str | Callable[[LoopCtx, str], bool] | None = None,
) -> bool:
    r"""``_inject_before_anchor`` 的 ``\begin{document}`` 锚特化。

    导言区末位注入点 —— 晚于一切包装载的 catcode/charclass 重声明,
    又早于 class ``\AtBeginDocument`` 钩内排版与 ``\begin{document}``
    执行内触发的 aux 读面; ``\@onlypreamble`` 命令在此仍合法。
    """
    return _inject_before_anchor(
        ctx,
        snippet,
        BEGIN_DOC_RX,
        depth0=depth0,
        strict_first=strict_first,
        fallback=fallback,
    )
