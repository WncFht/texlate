r"""builtins._mccjk — missing_char_fix 主臂 + CJK 绑定预热 + 谚文路由 (C5 拆叶)。

log「Missing character」行 → 码位分级 → 表驱动字面替换 (``_sub_literal_chars``)
/ xeCJK 逐组字体绑定 ``\AtBeginDocument`` 预热 (``_mc_apply_warmup``) /
kotex-xetexko 谚文路由件 (``_mc_apply_hangul_route`` + ``_ko_route_snippet``)
——``missing_char_fix`` 入口分诊三臂。探针面 (``_CJK_MECH_RE``/
``_KO_MECH_RE``/``_HANGUL_BANDS``/``_KO_FONT_NOT``/``_KO_FONT_CANDS``/
``_MC_WARMUP_SIZES``) 同叶驻留。``_resolve_font_cands`` 直跨
``_mcfallback`` 叶; common 读侧原语 (``_mc_seen``/``_mc_plan``/
``_mc_table``/``_splice``/``_map_tex_files``/``mask_tex`` 等) 经本叶回引。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins._mcfallback import _resolve_font_cands
from texlate.compile.fixloop.builtins.common import (
    _inject_after_docclass,
    _inject_before_begindoc,
    _map_tex_files,
    _mc_plan,
    _mc_seen,
    _mc_table,
    _splice,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine

__all__ = [
    "_CJK_MECH_RE",
    "_HANGUL_BANDS",
    "_KO_FONT_CANDS",
    "_KO_FONT_NOT",
    "_KO_MECH_RE",
    "_MC_WARMUP_SIZES",
    "_inject_before_begindoc",
    "_ko_route_snippet",
    "_map_tex_files",
    "_mc_apply_hangul_route",
    "_mc_apply_warmup",
    "_mc_plan",
    "_mc_seen",
    "_mc_table",
    "_splice",
    "_sub_literal_chars",
    "mask_tex",
    "missing_char_fix",
]


#: xeCJK/ctex 支持探针 (source_contains 级) —— 有 CJK 机制才有绑定可预热。
_CJK_MECH_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\b[^\n%]*\{[^}]*\b(?:ctex|xeCJK|CJKutf8)\b"
    r"|\\(?:setCJK\w*font|CJKfontspec|ctexset|xeCJKsetup|newCJKfontfamily)\b"
)

#: kotex/xetexko 系机制探针 —— hangul 路由臂的「kotex 条件」: kotex/dhucs
#: 系包装载 (shipped .cls/.sty 内的 ``\RequirePackage`` 也在 blob 命中面)、
#: oblivoir 系类名、或 hangul 字体 cs 现身。
_KO_MECH_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\b[^\n%]*\{[^}]*"
    r"\b(?:kotex|xetexko|dhucs|kotexutf|kotex-euc|hlatex|hangul|oblivoir)\b"
    r"|\\documentclass\b[^\n%]*\{[^}]*\b(?:kotex|dhucs|oblivoir|xob[a-z-]*)\b"
    r"|\\(?:setmainhangulfont|setsanshangulfont|setmonohangulfont|"
    r"sethangulfont|hangulfontspec|newhangulfontfamily|setkoreanfont)\b"
)

#: 谚文五段 —— 与 rules/60-misschar.yaml hangul_font_fallback.fallback_ranges 同表。
_HANGUL_BANDS: tuple[tuple[int, int], ...] = (
    (0x1100, 0x11FF),
    (0x3130, 0x318F),
    (0xA960, 0xA97C),
    (0xAC00, 0xD7A3),
    (0xD7B0, 0xD7FB),
)

#: 已覆盖 hangul 的缺字字体名排除模式 —— 与 yaml hangul_font_fallback.font_not
#: 同步维护: 谚文落其上 = 真缺字形, 路由臂不认领。
_KO_FONT_NOT = (
    r"noto.*(cjk|kr|korean)|source.?han|sarasa|hanazono|nanum|malgun|kopub|"
    r"plex.*kr|apple|batang|dotum|gulim|gungsuh|myeongjo|dinaru|"
    r"un(batang|dotum|graphic|pilgi|gungseo|dinaru|shinmun|yetgul|pen|taza|"
    r"vada|park|jamo|bom|yeti|sora)|hcr|hamchorom|jamo|baekmuk|"
    r"droid.*fallback|wqy|lxgw"
)

#: 路由臂 ko 字体有序候选 —— 与 yaml hangul_font_fallback.fallback_fonts 同序;
#: ``params.ko_fonts`` 可覆盖 (missing_char_fix 参数面)。
_KO_FONT_CANDS: tuple[Any, ...] = (
    {"name": "UnDotum.ttf", "install": True},
    "Noto Sans CJK KR",
    "IBM Plex Sans KR",
    "Nanum Gothic",
    "Malgun Gothic",
)

#: ``\begin{document}`` 锚 —— 导言区末位注入点 (``_inject_before_begindoc``,
#: ``builtins.common`` 单源)。hangul 路由件须晚于一切包装载的
#: catcode/charclass 重声明 (xetexko 装载把 AC00-D7A3 catcode 重置
#: 12 + 圈进自家 HG 类), 又早于 class ``\AtBeginDocument`` 钩内的排版
#: (kaist-ucs.cls 封面文字在钩内走)。


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

    谚文缺字先走 ``_mc_apply_hangul_route`` 预分诊 (kotex 条件臂):
    kotex/xetexko 把 AC00-D7A3 catcode 重置 12 → ``newunicodechar`` 活动
    字符绑定失效 (hangul_font_fallback 末位臂够不到), cjk_warmup 也只暖
    xeCJK 族绑定够不到 HG 类 —— 须路由件认领: xeCJK AutoFallBack 逐字
    ``\iffontchar`` 回退 + xetexko ``\setmainhangulfont`` 族, 认领码位出表。
    """
    del payload
    seen = _mc_seen(ctx)
    if seen is None:
        return False, "no compile log with Missing character found"
    if not seen:
        return False, "Missing character lines present but no codepoint parsed"

    applied: list[str] = []
    notes: list[str] = []
    ko_ok, ko_note, ko_cps = _mc_apply_hangul_route(ctx, eng, params, seen)
    if ko_note:
        (applied if ko_ok else notes).append(ko_note)
    if ko_cps:
        seen = {cp: v for cp, v in seen.items() if cp not in ko_cps}

    warm, repl, unmatched = _mc_plan(seen, _mc_table(params))
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


def _mc_apply_warmup(ctx: LoopCtx) -> tuple[bool, str]:
    r"""``\AtBeginDocument`` 预热盒注入 —— 仅当源里有 ctex/xeCJK 机制。"""
    box = "\\setbox0=\\hbox{" + "".join(f"{{{s}}}" for s in _MC_WARMUP_SIZES) + "}"
    snippet = f"\\AtBeginDocument{{{box}}} % fixloop: xeCJK bind warmup"
    if not _CJK_MECH_RE.search(mask_tex(ctx.source_blob())):
        return False, "cjk drops but no ctex/xeCJK in source — warmup skipped"
    if _inject_after_docclass(ctx, snippet):
        return True, "injected CJK font-binding warmup"
    return False, "warmup snippet already present"


def _ko_route_snippet(font: str) -> str:
    r"""Hangul 路由件 —— xeCJK AutoFallBack 臂 + xetexko hangulfont 臂并射。

    xeCJK 臂: ``AutoFallBack`` 让 ``\xeCJK_fallback_symbol:NN`` 在 CJK 类
    (含 HangulJamo 拷贝面) interchartoks 内逐字 ``\iffontchar`` —— 缺字形
    时改选 ``<CJKfamily>/FallBack`` 族字体, rm/sf/tt 三族各绑一份。xetexko
    臂: ``\setmainhangulfont`` 族定 HG 类谚文字体 (undefined 时 HG 谚文落
    ambient 西文字体缺字; xetexko 自带 ``\AtBeginDocument`` UnBatang 兜底
    在 unfonts 缺席环境失救)。两臂各 ``\ifdefined`` 守 —— 装载序决定谚文
    归 CJK 类还是 HG 类 (2403.00013 前者 / 2410.18001 后者), 静态不可判,
    未装载一侧空转。
    """
    return "\n".join(
        [
            "% fixloop: hangul -> ko font via xeCJK fallback / xetexko hangulfont",
            "\\ifdefined\\xeCJKsetup\\xeCJKsetup{AutoFallBack}\\fi",
            "\\ifdefined\\setCJKfallbackfamilyfont",
            f"  \\setCJKfallbackfamilyfont{{\\CJKrmdefault}}{{{font}}}",
            f"  \\setCJKfallbackfamilyfont{{\\CJKsfdefault}}{{{font}}}",
            f"  \\setCJKfallbackfamilyfont{{\\CJKttdefault}}{{{font}}}",
            "\\fi",
            f"\\ifdefined\\setmainhangulfont\\setmainhangulfont{{{font}}}\\fi",
            f"\\ifdefined\\setsanshangulfont\\setsanshangulfont{{{font}}}\\fi",
            f"\\ifdefined\\setmonohangulfont\\setmonohangulfont{{{font}}}\\fi",
        ]
    )


def _mc_apply_hangul_route(
    ctx: LoopCtx,
    eng: Engine,
    params: dict[str, Any],
    seen: dict[int, tuple[str, str]],
) -> tuple[bool, str, set[int]]:
    r"""谚文缺字 → 路由件注入 → (applied, note, 认领码位集)。

    门控三层: 码位 ∈ 谚文五段 ∧ 缺字字体名不具 hangul 覆盖 (``_KO_FONT_NOT``
    —— 落 ko 字体上 = 真缺字形, 不认领) ∧ 源内有 xeCJK/ctex 或 kotex/xetexko
    系机制 (``_CJK_MECH_RE``/``_KO_MECH_RE`` 双探 —— 两系皆无则
    newunicodechar 逐字回退本来就是活路, 不占先)。ko 字体候选
    (``params.ko_fonts`` 覆盖) 全灭 → decline 诚实交回。认领成功的码位
    由调用方剔出 ``seen`` —— 不再误触 cjk_warmup (暖 xeCJK 族绑定对 HG
    类谚文无效) 或计 unmatched。
    """
    cps = {
        cp
        for cp, (_what, font) in seen.items()
        if any(lo <= cp <= hi for lo, hi in _HANGUL_BANDS)
        and not re.search(_KO_FONT_NOT, font, re.IGNORECASE)
    }
    if not cps:
        return False, "", set()
    blob = mask_tex(ctx.source_blob())
    if not (_CJK_MECH_RE.search(blob) or _KO_MECH_RE.search(blob)):
        return (
            False,
            f"hangul drops x{len(cps)} but no xeCJK/kotex mechanism — route skipped",
            set(),
        )
    font, why = _resolve_font_cands(ctx, eng, params.get("ko_fonts") or _KO_FONT_CANDS)
    if font is None:
        return False, f"hangul drops x{len(cps)} but {why}", set()
    snippet = _ko_route_snippet(font)
    main = ctx.main_path()
    if main is not None and snippet in (ctx.read(main) or ""):
        # 路由件已在场而缺字持续: 码位同样认领出表 —— 自注 snippet 的
        # \xeCJKsetup/\setCJK*font 字样会让 _CJK_MECH_RE 自我命中,
        # 留表会让暖盒假阳性空烧一轮 (kotex-only 工程本无 xeCJK 可暖)。
        return False, "hangul route already present but drops persist", cps
    if _inject_before_begindoc(ctx, snippet):
        return True, f"hangul route: {len(cps)} cp(s) -> {font}", cps
    return False, "hangul drops but no live \\begin{document} anchor", set()


def _sub_literal_chars(t: str, repl: dict[str, str]) -> tuple[str, int]:
    r"""字面字符 → TeX 命令串逐替换 → (新文本, 替换数)。

    替换域限正文: ``mask_tex`` 等长遮盖视图把 verbatim 族环境体 / comment
    失活环境 / ``\\verb``/``\\lstinline`` / ``%`` 注释抹成空格——在遮盖
    视图上取命中 offset 回原文回放, 代码清单与注释里的同码位字面量不被
    腐蚀成 ``\\ensuremath{...}`` 串 (audit-2026-09-16)。
    """
    masked = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for ch, to in repl.items():
        start = 0
        while (i := masked.find(ch, start)) >= 0:
            if t[i] == ch:  # 同码位恰落在遮盖位 (' '/'\\n') 时守卫
                edits.append((i, i + 1, to))
            start = i + 1
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)
