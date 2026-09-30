r"""builtins._gfxm_refscan — 图形引用证据扫描域 (gfx_missing 拆分)。

epsfig/psfig kv 形引用点 (``_EPS_KV_RE``/``_KV_FILE_RE``) + 包装宏
``\includegraphics{..#N..}`` 模板 def 站册与调用位实参回填
(``_gfx_macro_templates``/``_macro_graphic_ref_hit``) +
``_has_live_graphic_ref`` 三口径活引用复核 —— 无扩展名 payload
的图形域证据面。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins._gfxm_caselink import (
    _INCLUDE_GFX_RE,
    _graphic_ref_hit,
)
from texlate.compile.fixloop.builtins.common import _live_matches
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx


__all__ = [
    "_EPS_KV_RE",
    "_GFX_ARG_RE",
    "_GFX_DEF_NC_RE",
    "_GFX_DEF_PRIM_RE",
    "_GFX_OPT_ARG_RE",
    "_GFX_PARAM_REF_RE",
    "_KV_FILE_RE",
    "_gfx_call_args",
    "_gfx_macro_templates",
    "_gfx_resolve_hit",
    "_gfx_template_items",
    "_has_live_graphic_ref",
    "_macro_graphic_ref_hit",
    "mask_tex",
]


#: ``\epsfig{file=X.eps, scale=..}`` / ``\psfig{figure=X}`` / ``\epsfbox{X}``
#: kv/裸参引用点 —— ``_INCLUDE_GFX_RE`` 吃不到 kv 形，独立一柄。
_EPS_KV_RE = re.compile(r"\\(?:epsfig|psfig|epsffile|epsfbox)\s*\{([^}]*)\}")
#: kv 形大括号串内的 ``file=``/``figure=`` 值。


_KV_FILE_RE = re.compile(r"(?:file|figure)\s*=\s*([^,\s}]+)")


# ═══ 宏间接引用 (w13 B3, 2505.06480): 包装宏内 #N 形参回填 ═══


# ═══ 宏间接引用 (w13 B3, 2505.06480): 包装宏内 #N 形参回填 ═══
#: ``\newcommand{\fig}[6]{..\includegraphics{..#4..}..}`` 族 def 站 —
#: 字面 ``\includegraphics`` 引用点为空，引用真身躲在 ``\fig{..}{01-abstract}``
#: 调用位 #N 实参。g1=name, g2=arity, g3=可选首参 default 位，g4=body
#: (两层内层花括; ``\fbox{\includegraphics{#2}}`` 级嵌套可收，更深截断
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
