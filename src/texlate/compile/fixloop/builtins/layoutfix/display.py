r"""builtins.layoutfix.display — 编号对齐族收缩 + 无编号 display 包钳 (layoutfix 拆分)。

``display_math_shrink`` warn_overfull display 数学臂: 编号对齐族
env/before 字号+muskip 收缩钩 + ``$$``/``\[`` 无编号 display
``\adjustbox{max width=\linewidth}`` 文本包 (qc wide_display_math 桶)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _inject_before_begindoc,
    _map_tex_files,
    _splice,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = [
    "_DD_BRACKET_RX",
    "_DD_DOLLAR_RX",
    "_DISP_ANY_RX",
    "_DISP_SHRINK_ENVS",
    "_display_snippet",
    "_display_wrap_edits",
    "display_math_shrink",
]

#: 编号对齐族 env/before 收缩面——数学字号随环境外文本字号走 (钩在
#: ``before`` 即数学模式开启前注入，组内设定 env 末自还原), 编号保留。
#: ``bea``/``displaymath`` 同收 (revtex/旧式简写族同名环境钩面)。
_DISP_SHRINK_ENVS = (
    "equation",
    "equation*",
    "eqnarray",
    "eqnarray*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "flalign",
    "flalign*",
    "IEEEeqnarray",
    "IEEEeqnarray*",
    "dmath",
    "displaymath",
    "bea",
)

_DISP_ANY_RX = re.compile(
    r"\\begin\s*\{(?:"
    + "|".join(re.escape(e) for e in _DISP_SHRINK_ENVS)
    + r")\}|\$\$|\\\["
)


def _display_snippet(size: str) -> str:
    r"""编号对齐族 env/before 收缩钩块 + adjustbox 载备 (``$$``/``\[`` 臂用)。"""
    lines = [
        "% texlate-fixloop: display-math shrink v1",
        "\\usepackage{adjustbox}",
        "\\AtBeginDocument{%",
    ]
    lines.extend(
        f"\\AddToHook{{env/{e}/before}}{{\\{size}"
        "\\setlength{\\arraycolsep}{1.5pt}\\setlength{\\jot}{2pt}"
        "\\medmuskip=2mu\\thinmuskip=2mu\\thickmuskip=2mu\\relax}%"
        for e in _DISP_SHRINK_ENVS
    )
    lines.append("}")
    return "\n".join(lines)


#: 无编号 display 面包钳——``$$...$$`` 与 ``\[...\]`` 双形态。
#: ``[\s\S]*?`` 非贪配对 (``$$A$$ B $$C$$`` 逐对), 组 1=body。
_DD_DOLLAR_RX = re.compile(r"\$\$([\s\S]*?)\$\$")
_DD_BRACKET_RX = re.compile(r"\\\[([\s\S]*?)\\\]")


def _display_wrap_edits(t: str) -> tuple[str, int]:
    r"""``$$``/``\[`` 体 → ``\[\adjustbox{max width=\linewidth}{$\displaystyle<body>$}\]``。

    adjustbox ``max width`` 只缩超宽者 (不拉宽小公式, resizebox 恒等宽
    不采); 体内 aligned/array 在 inline math 域照常 boxed。已有
    ``\adjustbox``/``\resizebox`` 的体不叠包 (幂等); <4 字符玩具体跳过。
    """
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for rx in (_DD_DOLLAR_RX, _DD_BRACKET_RX):
        for m in rx.finditer(vis):
            body = t[m.start(1) : m.end(1)]
            if not body.strip():
                continue
            if "\\adjustbox" in body or "\\resizebox" in body:
                continue
            # 跨注释/逐字死区的命中剔除 (遮盖差 = 体穿 masked 区)
            if vis[m.start() : m.end()] != t[m.start() : m.end()]:
                continue
            rep = (
                "\\[\n\\adjustbox{max width=\\linewidth}{$\\displaystyle "
                + body
                + "$}\n\\]"
            )
            edits.append((m.start(), m.end(), rep))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def display_math_shrink(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""warn_overfull display 数学臂: 编号族收缩 + 无编号包钳。

    实证面 (qc wide_display_math 桶, 21+1 格): ``detected at line N``
    签名 = display 超宽 (eqnarray/``\bea`` 8 格、align/equation、
    ``$$``-chain、flalign、IEEEeqnarray; 0707.2648 单列 210pt)。

    - **env/before 臂**: 编号对齐族钩 ``\<size>`` + ``\arraycolsep``/
      ``\jot``/muskip 收缩——诊断面 26-75pt/~470pt 溢出 ≈6-16%,
      ``\footnotesize`` (10-12%) + colsep 多够; ``params.size`` 可换
      ``scriptsize``。钩在 ``before`` (数学开启前) 使文本字号传导进
      数学度规——fp 行号→env 绑定的脆径不需要, 钩面全域生效。
    - **包钳臂**: ``$$...$$``/``\[...\]`` → ``\[\adjustbox{max width=
      \linewidth}{$\displaystyle ...$}\]``。

    ``\left/\right`` 单原子撑宽与 eqnarray→array 丢行号改写不采
    (known_gap 同 math_run_break 边界)。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex",))
    n_files = _map_tex_files(ctx, exts, _display_wrap_edits)
    size = str(params.get("size") or "footnotesize")
    blob = "\n".join(mask_tex(t) for f in ctx.tex_files(exts) if (t := ctx.read(f)))
    injected = False
    if _DISP_ANY_RX.search(blob) is not None:
        injected = _inject_before_begindoc(ctx, _display_snippet(size), fallback="head")
    parts: list[str] = []
    if injected:
        parts.append(f"env-shrink hooks injected @{size}")
    if n_files:
        parts.append(f"display wrapped in {n_files} file(s)")
    if not parts:
        return False, "shrink hooks already present, no wraps"
    return True, "; ".join(parts)
