r"""builtins._lfx_gfxw — ``\includegraphics`` max width 钳三面合修 (layoutfix 拆分)。

``gfx_width_clamp`` warn_overfull 图形臂: adjustbox ``export`` 键落实
(``_ensure_adjustbox_export``) → 逐调用点追 ``max width=\linewidth``
(``_gfx_call_edits``) + 相邻图组宽和收缩 (``_gfx_pair_edits``) +
字面超宽 ``width=N\linewidth`` 改写 (``_gfx_relwide_edits``)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _inject_before_begindoc,
    _is_live,
    _map_tex_files,
    _pkg_list_re,
    _splice,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = [
    "_GFX_CALL_RX",
    "_GFX_GLUE_RX",
    "_GFX_PAIR_MIN",
    "_GFX_PAIR_SUM",
    "_RELWIDE_RX",
    "_ensure_adjustbox_export",
    "_gfx_call_edits",
    "_gfx_pair_edits",
    "_gfx_relwide_edits",
    "_pkg_list_re",
    "gfx_width_clamp",
]

#: ``\includegraphics`` 调用点 (遮盖面)——组 ``opts`` 含括号。
_GFX_CALL_RX = re.compile(r"\\includegraphics\*?(?P<opts>\[[^\]\n]*\])?\s*\{[^}\n]*\}")

#: ``width=<f>\linewidth`` 族——f>1 即字面超宽 (pgfplots ``width=1.3
#: \linewidth`` 同收，不只 \includegraphics 域)。
_RELWIDE_RX = re.compile(
    r"width\s*=\s*(\d+(?:\.\d+)?)\s*\\(linewidth|textwidth|columnwidth)"
)

#: 图间 glue 面——连续 ``\includegraphics`` 之间的合法间隙串 (空判用)。
_GFX_GLUE_RX = re.compile(
    r"^(?:[\s~]|\\hfill|\\hfil|\\hspace\*?\{[^}\n]*\}|\\quad|\\qquad|\\,)+$"
)

#: 并图组收窄阈——相邻图声明宽和 ≥0.98 才等比缩 (indent/glue 吃残量)。
_GFX_PAIR_SUM = 0.98
#: 组链下限——单图本就走 ``max width`` 单臂，链臂只对 ≥2 成员生效。
_GFX_PAIR_MIN = 2


def _gfx_call_edits(t: str) -> tuple[str, int]:
    r"""逐 ``\includegraphics`` 追 ``max width=\linewidth`` (无 opts 补括号)。

    adjustbox ``export`` 使 ``max width`` 直接挂 graphics 键——只缩超
    限者, ``scale=``/height-only/无尺寸 EPS 均被兜底 (1906.00253/
    2609.19592/2504.15280 实证面)。已带 ``max width`` 的站不叠注。
    """
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for m in _GFX_CALL_RX.finditer(vis):
        if not _is_live(m, vis, t):
            continue
        opts = m.group("opts")
        if opts and "max width" in opts:
            continue
        if opts:
            ins_at = m.end("opts") - 1
            sep = "," if opts[1:-1].strip() else ""
            edits.append((ins_at, ins_at, f"{sep}max width=\\linewidth"))
        else:
            # ``{file}`` 组前补 ``[max width=\linewidth]``
            brace = vis.rfind("{", m.start(), m.end())
            if brace >= 0:
                edits.append((brace, brace, "[max width=\\linewidth]"))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _gfx_pair_edits(t: str) -> tuple[str, int]:
    r"""相邻图组宽和 ≥0.98\linewidth → 各 ``width`` 系数按比缩到和 0.98。

    两图并排行 (``[width=0.5\textwidth]`` 对间仅 glue) 声明宽和顶格仍
    出血——indent/glue 吃掉残量 (1306.0563/2608.08891/1003.0851 实证);
    系数等比缩 (0.98/sum) 而非固定 0.49——三图组同臂吸收。链仅由
    glue 连排且**逐成员皆声明相对宽**的 ``\includegraphics`` 构成——
    无宽成员与 ``\\par``/空行隔断链 (未知自然宽在场则宽和不可信)。
    """
    vis = mask_tex(t)
    hits = [m for m in _GFX_CALL_RX.finditer(vis) if _is_live(m, vis, t)]
    edits: list[tuple[int, int, str]] = []
    run: list[tuple[re.Match[str], re.Match[str]]] = []

    def flush() -> None:
        if len(run) < _GFX_PAIR_MIN:
            run.clear()
            return
        total = sum(float(wm.group(1)) for _, wm in run)
        if total >= _GFX_PAIR_SUM:
            scale = _GFX_PAIR_SUM / total
            for m, wm in run:
                new_f = float(wm.group(1)) * scale
                new_s = f"{new_f:.3f}".rstrip("0").rstrip(".")
                edits.append(
                    (
                        m.start("opts") + wm.start(1),
                        m.start("opts") + wm.end(1),
                        new_s,
                    )
                )
        run.clear()

    prev_end: int | None = None
    for m in hits:
        glue_ok = False
        if prev_end is not None:
            glue = t[prev_end : m.start()]
            glue_ok = (
                "\n\n" not in glue
                and "\\par" not in glue
                and _GFX_GLUE_RX.match(glue) is not None
            )
        wm = _RELWIDE_RX.search(m.group("opts") or "")
        if not glue_ok or wm is None:
            flush()
        if wm is not None:
            run.append((m, wm))
            prev_end = m.end()
        else:
            prev_end = None  # 无宽成员断链——其后不得续链配对
    flush()
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _gfx_relwide_edits(t: str) -> tuple[str, int]:
    r"""字面超宽 ``width=N\linewidth`` (N>1) → ``width=\linewidth``。

    pgfplots/tikz ``width=`` 键同收 (2504.07951 ``width=1.3\linewidth``
    实证)——相对宽 >1 在任何键域都是越版声明。
    """
    vis = mask_tex(t)
    edits = [
        (m.start(0), m.end(0), "width=\\linewidth")
        for m in _RELWIDE_RX.finditer(vis)
        if float(m.group(1)) > 1.0 and _is_live(m, vis, t)
    ]
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _ensure_adjustbox_export(ctx: LoopCtx) -> bool:
    r"""工程内 adjustbox 装载点全数补 ``export`` 键; 无装载 → preamble 注一行。

    ``export`` 必须挂在**最先执行**的装载点上 (迟到的 ``[export]`` 装载
    撞 Option clash)——文件序≠执行序不可知, 故对一切活装载点并
    ``export`` (首个执行者带 export 后其余装载成子集幂等)。全树无装载
    才 ``\begin{document}`` 前自注 ``\usepackage[export]{adjustbox}``。
    """
    rx = _pkg_list_re("adjustbox")
    found = False
    for f in ctx.tex_files((".tex", ".sty", ".cls")):
        t = ctx.read(f)
        if t is None:
            continue
        masked = mask_tex(t)
        edits: list[tuple[int, int, str]] = []
        for m in rx.finditer(masked):
            if not _is_live(m, masked, t):
                continue
            found = True
            opts = m.group("opts_inner") or ""
            if re.search(r"(?:^|,)\s*export\s*(?=,|$)", opts):
                continue  # export 已在
            names = (m.group("before") or "") + "adjustbox" + (m.group("after") or "")
            new = (
                f"\\{m.group('cmd')}"
                f"[{opts + ',' if opts.strip() else ''}export]"
                f"{{{names}}}"
            )
            edits.append((m.start(), m.end(), new))
        if edits:
            ctx.write(f, _splice(t, edits))
    if found:
        return True
    return _inject_before_begindoc(
        ctx,
        "% texlate-fixloop: gfx width clamp\n\\usepackage[export]{adjustbox}",
        fallback="head",
    )


def gfx_width_clamp(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""warn_overfull 图形臂: ``\includegraphics`` ``max width`` 钳三面合修。

    实证面 (qc oversized_graphics 桶, 20 格): ``scale=0.66`` 巨图源
    (1906.00253)、``width=2\linewidth`` (2504.15280)、``0.5+0.5`` 对
    (1306.0563)、height-only (2609.19592)、pgfplots ``width=1.3
    \linewidth`` (2504.07951)。

    1. adjustbox ``export`` 键落实 (装载点补注或未载新注) → 逐
       ``\includegraphics`` 追 ``max width=\linewidth``;
    2. 相邻图组 (glue 连排 ≥2) 声明宽和 ≥0.98 → 等比缩到 0.98;
    3. 字面 ``width=N\linewidth`` (N>1) → ``width=\linewidth``。

    picture env 系统盒 (1306.0005) 非 ``\includegraphics`` 面——
    known_gap 留 tabular_fit/display 族分管。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    n_clamp = _map_tex_files(ctx, exts, _gfx_call_edits)
    n_pair = _map_tex_files(ctx, exts, _gfx_pair_edits)
    n_wide = _map_tex_files(ctx, exts, _gfx_relwide_edits)
    loaded = _ensure_adjustbox_export(ctx)
    parts: list[str] = []
    if n_clamp:
        parts.append(f"max-width clamp in {n_clamp} file(s)")
    if n_pair:
        parts.append(f"pair/group shrink in {n_pair} file(s)")
    if n_wide:
        parts.append(f"literal-wide rewrite in {n_wide} file(s)")
    if loaded and not parts:
        parts.append("adjustbox[export] ensured")
    if not parts:
        return False, "no \\includegraphics sites / clamp already present"
    return True, "; ".join(parts)
