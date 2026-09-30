"""_builtins_misschar — missing_char F4 族修复原语 (C3 拆分)。

log「Missing character」行 → 码位分级 → 按类修复: 表驱动字面替换
(``missing_char_fix``) / 组合附加符 accent cs 站点改写 (``accent_mark_fix``) /
``newunicodechar`` 逐字回退 + 数学域双模修 (``font_fallback``)。

读侧/规划侧机制 (``_mc_parse_log``/``_mc_table``/``_mc_hit``/``_mc_plan``
+ ``_MC_TABLE``/``_FB_FONT``/``_MATH_SHIM_CS`` 常量) 归位
``_builtins_common`` —— shim 叶同消费, 本叶只留修复动作本体。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _FB_FONT,
    _MATH_SHIM_CS,
    _brace_end,
    _inject_after_docclass,
    _inject_before_begindoc,
    _is_live,
    _map_tex_files,
    _mc_chr,
    _mc_hit,
    _mc_plan,
    _mc_seen,
    _mc_table,
    _skip_ws,
    _splice,
)
from texlate.latex.tables import MATH_ENVS
from texlate.textutil import cs_events_spans, mask_tex

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# missing_char: log「Missing character」行 → 码位分级 → 按类修复 (F4)
# ════════════════════════════════════════════════════════════════

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
#: ``_builtins_common`` 单源)。hangul 路由件须晚于一切包装载的
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


#: font_fallback 默认覆盖带 (scout-misschar 2026-09-16: 西里尔人名真损失
#: U+0400-04FF / 组合符 U+0300-036F / 拉丁扩展 U+00C0-017F)。
#: ``params.fallback_ranges`` 覆盖带表、``params.fallback_font`` 换字体。
_FB_RANGES: tuple[tuple[int, int], ...] = (
    (0x0400, 0x04FF),
    (0x0300, 0x036F),
    (0x00C0, 0x017F),
)

#: ``fallback_fonts`` 候选名按扩展名分流探测: 字体文件名 (otf/ttf/ttc)
#: → kpathsea ``probe_file`` (fontspec 文件形解析同一通路); 家族名 →
#: ``fc-list`` fontconfig 探测 (fontspec 家族名解析同一通路)。
_FONT_FILE_RE = re.compile(r"\.(?:otf|ttf|ttc|pfb|dfont)$", re.IGNORECASE)


def _fb_snippet_lines(
    cps: Iterable[int], font: str, cs: str = "txlatefallback"
) -> list[str]:
    r"""``newunicodechar`` 逐字回退注入块行表 (font_fallback/accent_mark_fix 共用)。

    替换体 ``{\ifmmode\mbox{\<cs> X}\else{\<cs> X}\fi}``: 活动字符在数学内
    也展开, 但 ``\<cs>`` 只切文本族——``\mbox`` 逃回文本域才能让回退字体
    生效 (scout-misschar math_font_chars 桶: 数学内字面量经数学族 TFM 仍
    缺字)。头行 ``\ifdefined\<cs>`` 守卫让同一块被两条规则/两轮各注一份
    时不炸 ``\newfontfamily`` 重定义; ``cs`` 参数支持第二回退族
    (``txlatecjkfb`` = CJK 带 FandolSong 实例, fixer-font-fallback-8bit
    spec §1)。

    ``\newunicodechar`` 行整体收进 ``\AtBeginDocument``: 本块注在
    ``\documentclass`` 后即活化字符, 晚于其装载的 xeCJK/ctex 导言区
    punct 表 ``\keys_set`` (xeCJK.sty 默认 KaiMingPunct/LongPunct/
    MiddlePunct) 会把活动字 csname 化进 ``\tl_new:c`` → ``\protect``
    撞 ``\endcsname`` (Missing endcsname, 2609.19944/2410.18001)。
    begindocument 钩先于 ``\@onlypreamble`` 废名执行 (latex.ltx
    ``\document`` 序), ``\newunicodechar`` 在钩内仍合法。
    """
    lines = [
        "% fixloop: per-char font fallback via newunicodechar",
        "\\RequirePackage{newunicodechar}",
        "\\ifdefined\\newfontfamily\\else\\RequirePackage{fontspec}\\fi",
        f"\\ifdefined\\{cs}\\else\\newfontfamily\\{cs}{{{font}}}\\fi",
    ]
    acts = [
        f"\\newunicodechar{{{c}}}"
        f"{{\\ifmmode\\mbox{{\\{cs} {c}}}\\else{{\\{cs} {c}}}\\fi}}"
        for cp in cps
        if (c := _mc_chr(cp)) is not None
    ]
    if acts:
        lines += ["\\AtBeginDocument{%", *acts, "}"]
    return lines


def _inject_fallback_lines(
    ctx: LoopCtx, cps: Iterable[int], font: str, cs: str = "txlatefallback"
) -> int:
    r"""逐字 ``\\newunicodechar`` 回退行注入 (已声明字符去重) → 新注入字符数。"""
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None:
        return 0
    fresh = [
        cp
        for cp in dict.fromkeys(cps)
        if (c := _mc_chr(cp)) is not None and f"\\newunicodechar{{{c}}}" not in t
    ]
    if not fresh:
        return 0
    if not _inject_after_docclass(ctx, "\n".join(_fb_snippet_lines(fresh, font, cs))):
        return 0
    return len(fresh)


def _fb_font_resolve(
    ctx: LoopCtx, eng: Engine, params: dict[str, Any]
) -> tuple[str | None, str]:
    """``fallback_fonts`` 有序候选 → 首个可解析字体名; 全灭 → (None, 原因)。

    条目为名字符串或 ``{name, install}`` 映射: 文件形名 (``_FONT_FILE_RE``
    命中) 经 ``eng.probe_file`` 探测, ``install: true`` 时 miss 先
    ``eng.install_file`` 再复核 (texmf 树外字体包如 unfonts-core 可补装);
    家族名经 ``fc-list <name> family`` 非空输出探测 (fc-list 缺席/查无此族
    → 下一候选)。未给 ``fallback_fonts`` 时走 ``fallback_font``/``_FB_FONT``
    单值旧路——不探测, 保持既有臂行为不变。
    """
    cands = params.get("fallback_fonts")
    if not cands:
        return str(params.get("fallback_font") or _FB_FONT), ""
    return _resolve_font_cands(ctx, eng, cands)


def _resolve_font_cands(
    ctx: LoopCtx, eng: Engine, cands: Iterable[Any]
) -> tuple[str | None, str]:
    """有序字体候选 → 首个可解析字体名; 全灭 → (None, 原因)。

    条目为名字符串或 ``{name, install}`` 映射: 文件形名 (``_FONT_FILE_RE``
    命中) 经 ``eng.probe_file`` 探测, ``install: true`` 时 miss 先
    ``eng.install_file`` 再复核; 家族名经 ``fc-list <name> family`` 非空
    输出探测 (fc-list 缺席/查无此族 → 下一候选)。
    """
    tried: list[str] = []
    for c in cands:
        if isinstance(c, str):
            name, install = c, False
        else:
            name = str(c.get("name") or "")
            install = bool(c.get("install"))
        if not name:
            continue
        if _FONT_FILE_RE.search(name):
            if eng.probe_file(name) or (
                install and eng.install_file(name) and eng.probe_file(name)
            ):
                return name, ""
        else:
            rc, out, _to = ctx.run_tool(["fc-list", name, "family"], timeout=15)
            if rc == 0 and out.strip():
                return name, ""
        tried.append(name)
    return None, f"no fallback font resolvable ({', '.join(tried)})"


#: ``\begin{数学env}`` 起锚 —— ``$..$``/``\(\)`` 之外的数学体 (重音 cs 改写
#: 与 cs-shim 探测共用的数学域守卫)。tabbing 不是数学但 ``\=`` 在其内是
#: 制表符命令非重音 —— 同列守卫。
_MATH_GUARD_BEGIN_RE = re.compile(
    r"\\begin\s*\{("
    + "|".join(re.escape(e) for e in sorted(MATH_ENVS | {"tabbing"}))
    + r")\}"
)


def _math_guard_spans(masked: str) -> list[tuple[int, int]]:
    r"""遮盖视图上的数学域区间表: ``$..$``/``$$``/``\(\)``/``\[\]`` + 数学 env 体。"""
    _css, spans = cs_events_spans(masked)
    for m in _MATH_GUARD_BEGIN_RE.finditer(masked):
        end = re.compile(r"\\end\s*\{" + re.escape(m[1]) + r"\}").search(
            masked, m.end()
        )
        spans.append((m.start(), end.end() if end else len(masked)))
    return sorted(spans)


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    """``pos`` 是否落在任一 (start, stop) 区间内。"""
    return any(a <= pos < b for a, b in spans)


#: 带一个实参的文本 cs —— 数学域内展开产预组字母缺字 (``\r{A}``→Å 类
#: accent cs)。值 = 该 cs 的全部预组产出码位 (触发门), shim 形为
#: ``\def\<cs>#1{...\txlateold<cs>{#1}...}`` 实参重花括透传 (0806.3530
#: ``$\r{A}$`` Å-in-cmmi9 实证)。无参字母 cs 归 _MATH_SHIM_CS;
#: cs_rebind 的无参 emit 形消费不到本表 (按设计, 含参站点不在其管面)。
_MATH_SHIM_ARG_CS: dict[str, tuple[int, ...]] = {
    "r": (0x00C5, 0x00E5, 0x016E, 0x016F),  # \r{AaUu} → ÅåŮů 全预组面
}


def _math_cs_shim_names(ctx: LoopCtx, seen: dict[int, tuple[str, str]]) -> list[str]:
    r"""缺字码位 ∩ cs 产出集 ∧ 源内 ``\\<cs>`` 现身数学 span → 待 shim 名单。

    双信号皆备才动: 码位在缺字表 (真有缺字) 且 cs 站点在数学域 (缺字确由
    数学内展开所产)——文本域 ``\i`` 缺字是 ambient 字体真缺字形, 不归此修。
    """
    cands = [cs for cs, cp in _MATH_SHIM_CS.items() if cp in seen]
    cands += [
        cs for cs, cps in _MATH_SHIM_ARG_CS.items() if any(cp in seen for cp in cps)
    ]
    if not cands:
        return []
    masked = mask_tex(ctx.source_blob())
    spans = _math_guard_spans(masked)
    if not spans:
        return []
    return [
        cs
        for cs in cands
        if any(
            _in_spans(m.start(), spans)
            for m in re.compile(rf"\\{cs}(?![a-zA-Z@])").finditer(masked)
        )
    ]


def _inject_math_cs_shims(ctx: LoopCtx, cses: Iterable[str]) -> list[str]:
    r"""``\\<cs>`` 数学逃逸 shim 注入 → 实际注到的 cs 名单 (幂等)。

    ``\let\txlateold<cs>\<cs>`` 存原义 + ``\protected\def`` 数学域走
    ``\mbox`` (文本域重放原 cs → ambient 文本字体有字形)。``\mbox`` 是
    kernel 原语——不用 amsmath 的 ``\text``, 免包依赖。``\ifdefined``
    守卫 ``\let``: 重复注入时 ``\txlateold<cs>`` 若重绑到 shim 后的
    ``\<cs>`` 会自指死循环 (前一轮同 shim 或人工改写的场景)。

    let+def 双双 ``\AtBeginDocument`` 迟延: hyperref 在 ``\begin{document}``
    预钩段 (begindocument/before) 重声明文本命令族, 导言区即时 ``\def``
    会被复回原义——1404.0332 ``\i``/1907.03882 ``\ss`` shim 在场仍缺字
    实证 (probe: ctex+hyperref 下即时 def 失效, hook 迟延存活)。带参 cs
    (``_MATH_SHIM_ARG_CS``, ``\r`` 类) 走 ``#1`` 重花括透传形。
    """
    cses = list(cses)
    if not cses:
        return []
    lines = ["% fixloop: math-mode escape for text letter cses"]
    for cs in cses:
        old = f"\\txlateold{cs}"
        if cs in _MATH_SHIM_ARG_CS:
            body = (
                rf"\ifdefined{old}\else\let{old}\{cs}\fi"
                rf"\protected\def\{cs}#1"
                rf"{{\ifmmode\mbox{{{old}{{#1}}}}\else{old}{{#1}}\fi}}"
            )
        else:
            body = (
                rf"\ifdefined{old}\else\let{old}\{cs}\fi"
                rf"\protected\def\{cs}{{\ifmmode\mbox{{{old}}}\else{old}\fi}}"
            )
        lines.append(rf"\AtBeginDocument{{{body}}}")
    if _inject_after_docclass(ctx, "\n".join(lines)):
        return list(cses)
    return []


def font_fallback(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""非 CJK 缺字 → ``newunicodechar`` 换字体兜底 + 数学域双模修 (F4b/F4d)。

    ``\newunicodechar{X}`` 逐缺字声明：替换体里同字面的 X 在 ``\newunicodechar``
    激活该字符前已按 letter catcode token 化，故无自递归 (``\protected``
    定义也使 label/cite 键名内同字符不展开)。主字体本就缺这些带时才见
    缺字——逐字回退不伤排版。已由 char_table ``replace`` 条目覆盖的码位
    (ø/è 等) 让位字面替换。数学域两个子修 (scout-misschar math_font_chars):
    字面量靠 ``\ifmmode`` 模板逃 ``\mbox`` (见 _fb_snippet_lines); 无参字母
    cs (``\i``/``\L``/``\AA`` 族) 在数学内展开产文本字形 → ``_inject_math_cs_shims``
    prologue shim。shim 不依赖 newunicodechar.sty, 包缺席也独立成立。

    ``params.fallback_fonts`` 有序候选表 (文件形名/家族名混排, ``_fb_font_resolve``
    按扩展名分流 kpathsea/fontconfig 探测, ``{name, install}`` 条目带补装)
    存在时首个可解析者胜出; 全灭 → decline 不谎报。未给表时旧
    ``fallback_font``/``_FB_FONT`` 单值路径不探测原样使用。
    """
    del payload
    seen = _mc_seen(ctx)
    if seen is None:
        return False, "no compile log with Missing character found"
    done: list[str] = []
    if shimmed := _inject_math_cs_shims(ctx, _math_cs_shim_names(ctx, seen)):
        done.append("math cs shim: " + ", ".join(rf"\{c}" for c in shimmed))
    bands = params.get("fallback_ranges") or _FB_RANGES
    font_not = params.get(
        "font_not"
    )  # 字体名正则: 命中即跳 (CJK cp 落 CJK 字体是真缺字形)
    fb_cs = str(params.get("fallback_cs") or "txlatefallback")
    table = _mc_table(params)
    taken = {
        cp
        for cp, (what, font) in seen.items()
        for e in table.values()
        if e.get("replace") and _mc_hit(e, cp, font)
    }
    chars = [
        cp
        for cp, (_what, font) in seen.items()
        if cp not in taken
        and any(lo <= cp <= hi for lo, hi in bands)
        and not (font_not and re.search(str(font_not), font, re.IGNORECASE))
    ]
    if not chars:
        if done:
            return True, "; ".join(done)
        return False, "no missing chars in fallback bands"
    if not eng.probe_file("newunicodechar.sty") and not eng.install_file(
        "newunicodechar.sty"
    ):
        if done:
            done.append("newunicodechar.sty unavailable")
        return bool(done), "; ".join(done) or "newunicodechar.sty unavailable"
    font, why = _fb_font_resolve(ctx, eng, params)
    if font is None:
        if done:
            done.append(why)
        return bool(done), "; ".join(done) if done else why
    if n := _inject_fallback_lines(ctx, chars, font, fb_cs):
        done.append(f"font_fallback: {n} char(s) -> {font}")
    return (
        (True, "; ".join(done)) if done else (False, "fallback snippet already present")
    )


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


# ════════════════════════════════════════════════════════════════
# accent_mark_fix: accent cs 生成的组合符 → 站点级源改写 (F4c)
# ════════════════════════════════════════════════════════════════

#: 组合附加符码位 → 产生它的重音 cs (scout-misschar-coverage 2026-09-17
#: 0327 群 ~62 pids: ``\c{t}`` 类在无预组字形基字符上产 base+combining
#: 节点, ambient 字体无 U+0300-036F → Missing character; 附加符由 accent
#: 机制生成非输入字符, ``\newunicodechar`` 的 active-char 绑定拦不到)。
_ACCENT_CS: dict[int, str] = {
    0x0327: "c",
    0x0301: "'",
    0x0308: '"',
    0x0303: "~",
    0x0302: "^",
    0x0300: "`",
    0x0307: ".",
    0x0304: "=",
    0x0306: "u",
    0x030C: "v",
    0x030B: "H",
    0x0328: "k",
    0x0323: "d",
    0x0331: "b",
    0x030A: "r",
    0x0361: "t",
}


def _accent_site_re(cs: str) -> re.Pattern[str]:
    r"""``\\<cs>{x}`` 站点正则; 符号 cs (``\'`` 等) 兼收 ``\\<cs>x`` 裸字母实参。

    字母 cs 只认花括号实参——``\\ca`` 整体是另一个 cs 名, 裸字母形式在
    正则层无法与长名切割, 保守不收。
    """
    if cs.isalpha():
        return re.compile(rf"\\{re.escape(cs)}\s*\{{([^{{}}\\]*)\}}")
    return re.compile(rf"\\{re.escape(cs)}\s*(?:\{{([^{{}}\\]*)\}}|([a-zA-Z]))")


def _accent_fix_text(t: str, cs_marks: dict[str, str]) -> tuple[str, set[str], int]:
    r"""文本域 ``\\<cs>{x}`` 站点改写 → (新文本, 预组字集, 改写站点数)。

    逐站点: ``NFC(base+mark)`` 单字 → 预组字面量 (多字符实参对首字试组,
    余部原样保留); 无预组字 → 剥 accent 留 base。遮盖视图取 offset 回原文
    回放——verbatim/comment 体与数学域 (``\'``=\acute 族真义) 内站点不动。
    """
    masked = mask_tex(t)
    spans = _math_guard_spans(masked)
    edits: list[tuple[int, int, str]] = []
    composed: set[str] = set()
    for cs, mark in cs_marks.items():
        for m in _accent_site_re(cs).finditer(masked):
            if _in_spans(m.start(), spans):
                continue
            arg = m[1] if m[1] is not None else (m[2] or "")
            fused = unicodedata.normalize("NFC", arg[0] + mark) if arg else ""
            if len(fused) == 1:
                edits.append((m.start(), m.end(), fused + arg[1:]))
                composed.add(fused)
            else:
                edits.append((m.start(), m.end(), arg))
    if not edits:
        return t, set(), 0
    return _splice(t, edits), composed, len(edits)


def accent_mark_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""组合附加符缺字 → accent cs 站点改写预组字面量, 无预组则剥 accent。

    触发面: log ``Missing character`` 里 U+0300-036F 组合符码位——全部由
    ``\c \~ \^ \' \" \u \v`` 族 accent 机制生成 (输入层无此字符,
    newunicodechar 绑不住)。改写 ``\\<cs>{x}`` 站点 (``.tex+.bbl+.cls``,
    遮盖视图护 verbatim/注释, 数学 span 跳过): 有预组字 → 字面量并自注
    ``\newunicodechar`` 回退行 (``applied`` 键一次性, 不等 font_fallback
    再触火); 无预组字 → 剥 accent 留 base。
    """
    del payload
    seen = _mc_seen(ctx)
    if seen is None:
        return False, "no compile log with Missing character found"
    cs_marks = {cs: chr(cp) for cp, cs in _ACCENT_CS.items() if cp in seen}
    if not cs_marks:
        return False, "no combining-mark missing chars"
    exts = tuple(params.get("exts") or (".tex", ".bbl", ".cls"))
    n_sites = 0
    n_files = 0
    composed: set[str] = set()
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, chars, n = _accent_fix_text(t, cs_marks)
        if n and nt != t:
            ctx.write(f, nt)
            n_sites += n
            n_files += 1
            composed |= chars
    if not n_sites:
        return False, "combining marks missing but no accent-cs sites in source"
    done = [f"accent sites rewritten: {n_sites} in {n_files} file(s)"]
    if composed:
        if not eng.probe_file("newunicodechar.sty") and not eng.install_file(
            "newunicodechar.sty"
        ):
            done.append("newunicodechar.sty unavailable for composed chars")
        else:
            font = str(params.get("fallback_font") or _FB_FONT)
            n = _inject_fallback_lines(ctx, sorted(map(ord, composed)), font)
            done.append(f"self-injected newunicodechar fallback x{n}")
    return True, "; ".join(done)


# ════════════════════════════════════════════════════════════════
# macro_glyph_fix: 宏生成缺字 cs → 站点级源改写 (F4e)
# ════════════════════════════════════════════════════════════════

#: 无参符号 cs → (触发码位, 双模安全替换串): 字形由 cs 展开所产非输入
#: 字符 —— char_table ``replace`` 字面替换与 ``\newunicodechar`` 活动字符
#: 绑定都够不到 (utf8census rebucket-misschar-site-rewrite ×2 实证):
#: ``\texttildelow`` 产 U+02F7 (2308.04265 ``\raisebox{0.5ex}{\texttildelow}``
#: 文本域站点, lmroman10 无槽); ``\textlangle``/``\textrangle`` 产
#: U+2329/232A (2403.00011 ``\qdist`` 宏体在文本域定义、数学域展开,
#: zptmcmr 无槽 + invalid-in-math warning)。替换串一律 ``\ensuremath``/
#: ``\mbox`` 双模: 定义点与展开点可分居两域, 站点域判不准, 双模串两侧恒正。
_MACRO_GLYPH_CS: dict[str, tuple[int, str]] = {
    "texttildelow": (0x02F7, "\\ensuremath{\\sim}"),
    "textlangle": (0x2329, "\\ensuremath{\\langle}"),
    "textrangle": (0x232A, "\\ensuremath{\\rangle}"),
    # misscharcen #162 (loop3 残余普查): \textendash 在数学态 ket 记号内
    # 产 U+2013 (0806.2407 ``$i_{13/2}\textendash\frac{3}{2}$``, cmr10
    # 无槽 ×40) —— \mbox{--} 与 char_table endash 同形, TFM 连字双模安全。
    "textendash": (0x2013, "\\mbox{--}"),
    # hep-ph/0605319 ``\textgravedbl X\textacutedbl`` 作者 „...˝ 引号对:
    # tuenc gravedbl→U+02F5 缺 ×12 (lmroman 无槽), acutedbl→U+02DD 有槽
    # 不缺字。gravedbl→\quotedblbase „ 保引号语义; acutedbl 键在伴生
    # 02F5 而非自产 02DD —— 引号对成对归一为 „..." (改半对留 „...˝
    # 混搭); 音标域 02DD 真缺字场景不触发, '' 不误伤语义。
    "textgravedbl": (0x02F5, "\\mbox{\\quotedblbase}"),
    "textacutedbl": (0x02F5, "\\mbox{''}"),
    # ── 2026-09-20 erafam macro-glyph (failmine7 桶 → erafam 车道普查) ──
    # \checkmark 产 U+2713 落 LinLibertine_R 无槽 (2508.04740 表格域 /
    # 2602.08678 / 2603.08225 tikz 节点 ×3) —— \surd 数学族恒有, 勾形近似。
    "checkmark": (0x2713, "\\ensuremath{\\surd}"),
    # \blacktriangle 产 U+25B4 落 libertinusmath 无槽 (2502.00432
    # experiments.tex ``$\times 2.050 \ \blacktriangle$``) —— \vartriangle
    # 是空心近似 (实→空有损, census 已标注), 数学族恒有兜底。
    "blacktriangle": (0x25B4, "\\ensuremath{\\vartriangle}"),
    # \MakeUppercase 作用于 \ss 产 ẞ U+1E9E (2512.03885 作者名
    # ``Au\ss{}enhofer`` → AUSSENHOFER 大写 ẞ 落主字体无槽) —— 替换 "ss"
    # 是 2017 前德语大写正字法 (ẞ→SS), 小写语境 "Aussenhofer" 同为合规
    # 转写 (census flagged approx)。
    "ss": (0x1E9E, "ss"),
}

#: ``\char<dec>`` OT1/cmc 0-31 槽位 → 替换串 (misscharcen #169):
#: Unicode 字体下 ``\char13`` 产码位 13 本身而非 TFM 槽位字形 ——
#: pdftex-era ``\textsc{\char13}`` (=cmcsc 13 号 fl 连字) 语义漂移成
#: U+000D 控制符缺字 (1404.0578 lmromancaps10 ``^^M`` ×41, 全格唯一
#: 观测槽)。槽位表对 TFM 语境亦语义保持 (fl 字母重归槽位连字、
#: ``\c`` 重归槽位 accent) —— 门控失误也零副作用。0-10 大写希腊走
#: ``\ensuremath`` (数学族恒有; lmroman 虽有 391-3A9 槽, TFM 语境不
#: 普适); 11-15 f-连字写字母 (ambient 上下文自动成形 —— \textsc
#: 内=小型大写连字); 16-17 无点 i/j (lmroman 0131/0237 有槽, TFM
#: 下 cs 本义同槽); 18-23 重音符用数学裸 accent (修饰字母块超
#: _FB_RANGES 回退带, 数学形恒可印); 24 走 ``\c{}`` (产 U+0327,
#: lmroman 无槽但落 0300-036F 回退带两轮收敛); 25-31 拉丁字母 cs
#: (Latin-1/Ext 双编码恒覆盖)。32+ ASCII 面不可缺字天然不收。
_OT1_CHAR_SLOTS: dict[int, str] = {
    0: "\\ensuremath{\\Gamma}",
    1: "\\ensuremath{\\Delta}",
    2: "\\ensuremath{\\Theta}",
    3: "\\ensuremath{\\Lambda}",
    4: "\\ensuremath{\\Xi}",
    5: "\\ensuremath{\\Pi}",
    6: "\\ensuremath{\\Sigma}",
    7: "\\ensuremath{\\Upsilon}",
    8: "\\ensuremath{\\Phi}",
    9: "\\ensuremath{\\Psi}",
    10: "\\ensuremath{\\Omega}",
    11: "ff",
    12: "fi",
    13: "fl",
    14: "ffi",
    15: "ffl",
    16: "\\i",
    17: "\\j",
    18: "\\ensuremath{\\grave{}}",
    19: "\\ensuremath{\\acute{}}",
    20: "\\ensuremath{\\check{}}",
    21: "\\ensuremath{\\breve{}}",
    22: "\\ensuremath{\\bar{}}",
    23: "\\ensuremath{\\mathring{}}",
    24: "\\c{}",
    25: "\\ss",
    26: "\\ae",
    27: "\\oe",
    28: "\\o",
    29: "\\AE",
    30: "\\OE",
    31: "\\O",
}

#: ``\char`` 数值实参站点: 十进制 ``\char13`` / 八进制 ``\char'15`` /
#: 十六进制 ``\char"D`` (尾界防 ``\chardef``; 非数值形 ``\char`a``、
#: ``\numexpr`` 实参不收)。
_CHAR_NUM_RE = re.compile(
    r"\\char(?![a-zA-Z@])[ \t]*(?:'([0-7]+)|\"([0-9a-fA-F]+)|([0-9]+))"
)


def _char_num_value(m: re.Match[str]) -> int:
    """``_CHAR_NUM_RE`` 三分支 (八/十六/十进制) → 码位值。"""
    if m[1]:
        return int(m[1], 8)
    if m[2]:
        return int(m[2], 16)
    return int(m[3])


def _macro_glyph_fix_text(
    t: str, sites: dict[str, str], char_slots: dict[int, str]
) -> tuple[str, int, int]:
    r"""``\\<cs>``/``\char<N>`` 站点逐改写 → (新文本, cs 站点数, char 站点数)。

    遮盖视图取 offset 回原文回放 —— verbatim/失活环境/注释内同名 cs 不动;
    ``(?![a-zA-Z@])`` 尾界防 ``\textlangleX``/``\chardef`` 长名误吃。
    ``\char`` 实参按进制解析后查槽位表, 表外槽位 (≥32 ASCII 面) 不动。
    """
    masked = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for cs, rep in sites.items():
        edits.extend(
            (m.start(), m.end(), rep)
            for m in re.compile(rf"\\{re.escape(cs)}(?![a-zA-Z@])").finditer(masked)
        )
    n_cs = len(edits)
    n_char = 0
    if char_slots:
        for m in _CHAR_NUM_RE.finditer(masked):
            if rep := char_slots.get(_char_num_value(m)):
                edits.append((m.start(), m.end(), rep))
                n_char += 1
    if not edits:
        return t, 0, 0
    return _splice(t, edits), n_cs, n_char


def macro_glyph_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""宏/原语生成缺字 → 站点改写双模安全替换串 (F4e + #169 ``\char`` 臂)。

    双门触发: 缺字码位 ∈ 产出表 ∧ 站点在源 —— 字形由 cs 展开/原语查槽
    所产, 字面替换/newunicodechar 皆不可达; 字体真有该字形的站点 (产出
    码位不进缺字表) 静默不动。两个站点类: ``_MACRO_GLYPH_CS`` 无参
    符号 cs (产码位=表键) 与 ``\char<dec>`` OT1 槽位原语 (产码位=实参
    值, 槽位表 ``_OT1_CHAR_SLOTS`` 0-31)。``params.exts`` 覆盖文件面
    (缺省 .tex/.bbl/.cls)。
    """
    del eng, payload
    seen = _mc_seen(ctx)
    if seen is None:
        return False, "no compile log with Missing character found"
    sites = {cs: rep for cs, (cp, rep) in _MACRO_GLYPH_CS.items() if cp in seen}
    char_slots = {n: rep for n, rep in _OT1_CHAR_SLOTS.items() if n in seen}
    if not sites and not char_slots:
        return False, "no macro-generated missing chars"
    exts = tuple(params.get("exts") or (".tex", ".bbl", ".cls"))
    n_sites = 0
    n_char = 0
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, ns, nc = _macro_glyph_fix_text(t, sites, char_slots)
        if ns + nc and nt != t:
            ctx.write(f, nt)
            n_sites += ns
            n_char += nc
            n_files += 1
    if not n_sites and not n_char:
        return False, "macro-generated cps missing but no cs sites in source"
    parts = [
        f"macro glyph sites rewritten: {n_sites}" if n_sites else "",
        f"\\char slot sites rewritten: {n_char}" if n_char else "",
    ]
    return True, "; ".join(p for p in parts if p) + f" in {n_files} file(s)"


# ════════════════════════════════════════════════════════════════
# caret_utf8_fix: ``^^XX`` UTF-8 字节记法 → 解码还原字面量 (F4f)
# ════════════════════════════════════════════════════════════════

#: bibtex-era ``^^XX`` 字节记法运行段 (相邻 ≥1 token; 逐 token 尝试
#: UTF-8 多字节, 不合法字节回吐原 token —— 见 _caret_decode_run)。
_CARET_RUN_RE = re.compile(r"(?:\^\^[0-9a-fA-F]{2})+")
_CARET_TOK_RE = re.compile(r"\^\^([0-9a-fA-F]{2})")

#: UTF-8 lead-byte 分类下界 (≥F5 非法 lead/续字节存在性/超长/代理区
#: 全部由 ``bytes.decode`` 严格校验兜底 —— 猜测宽只为取窗)。
_LEAD2, _LEAD3, _LEAD4 = 0xC0, 0xE0, 0xF0

#: ``^^XX`` mojibake 指纹带: C1 控制符缺字区间 —— 高位 UTF-8 字节
#: (0x80-0x9F) 落此才报缺字, Latin-1 面字节静默错印。
_C1_LO, _C1_HI = 0x80, 0x9F


def _caret_decode_run(run: str) -> tuple[str, int]:
    r"""单段 ``^^XX`` 运行 → (重放文本, 解码出的多字节字符数)。

    逐字节位置按 lead-byte 宽度 (C0-DF→2/E0-EF→3/F0-F4→4) 取窗口交
    ``bytes.decode`` 严格校验 —— 截断/超长/代理区/非续字节全部回
    吐原 ``^^XX`` token。单字节 token (``^^41``/``^^0d`` 合法 TeX
    字符记法) 恒原样保留, 只多字节序列算 mojibake 证据。
    """
    toks = _CARET_TOK_RE.findall(run)
    byts = [int(h, 16) for h in toks]
    out: list[str] = []
    n_seq = 0
    i = 0
    while i < len(byts):
        b = byts[i]
        width = 4 if b >= _LEAD4 else 3 if b >= _LEAD3 else 2 if b >= _LEAD2 else 0
        if width and i + width <= len(byts):
            try:
                out.append(bytes(byts[i : i + width]).decode("utf-8"))
                n_seq += 1
                i += width
                continue
            except UnicodeDecodeError:
                pass
        out.append(f"^^{toks[i]}")
        i += 1
    return "".join(out), n_seq


def _caret_utf8_text(t: str) -> tuple[str, int, int]:
    r"""``^^XX`` 运行段逐段解码 → (新文本, 改写段数, 解码字符数)。

    遮盖视图取 offset 回原文回放 —— verbatim/注释内记法不动; 段内
    无一合法多字节序列的段整体不动 (``^^41`` 纯 ASCII 记法段)。
    """
    masked = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    n_chars = 0
    for m in _CARET_RUN_RE.finditer(masked):
        text, n = _caret_decode_run(m[0])
        if n:
            edits.append((m.start(), m.end(), text))
            n_chars += n
    if not edits:
        return t, 0, 0
    return _splice(t, edits), len(edits), n_chars


def caret_utf8_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``^^XX`` UTF-8 字节记法 → 解码还原字面量 (F4f, .bbl 消毒位)。

    bibtex-era 工具把非 ASCII 按 UTF-8 字节写成 ``^^e2^^80^^93`` 三连,
    每 ``^^XX`` 在 xetex 下读作独立码位 U+00XX: 高位字节产 C1
    (U+0080-9F) 缺字, 低位字节产 â/¼ 等静默 mojibake (2104.00026
    master2020.bbl: ``Knizhnik^^e2^^80^^93Zamolodchikov`` = en-dash,
    ``f^^c3^^bcr`` = für)。门控 = 日志见 C1 缺字 (字节记法指纹);
    解码面 = 全文 ``^^XX`` 段中严格合法 UTF-8 多字节序列 —— 同机制
    的零缺字节对 (ü 的 C3/BC 都落 Latin-1 有槽面) 一并还原, 字节级
    seen-门会漏这类不可见 mojibake。解码产字面量, 缺字链下游
    (char_table/字体回退) 照常接管。``params.exts`` 缺省 .tex/.bbl。
    """
    del eng, payload
    seen = _mc_seen(ctx)
    if seen is None:
        return False, "no compile log with Missing character found"
    if not any(_C1_LO <= cp <= _C1_HI for cp in seen):
        return False, "no C1 missing chars (^^XX byte-notation fingerprint)"
    exts = tuple(params.get("exts") or (".tex", ".bbl"))
    n_runs = 0
    n_chars = 0
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, nr, nc = _caret_utf8_text(t)
        if nr and nt != t:
            ctx.write(f, nt)
            n_runs += nr
            n_chars += nc
            n_files += 1
    if not n_runs:
        return False, "C1 misses present but no decodable ^^XX runs in source"
    return True, (
        f"^^XX UTF-8 runs decoded: {n_runs} run(s), "
        f"{n_chars} char(s) in {n_files} file(s)"
    )


# ════════════════════════════════════════════════════════════════
# fontspec_clone_sub: fontspec_missing 名查找缺字体 → 度量克隆/同件文件形替换
# ════════════════════════════════════════════════════════════════

#: ``-<weight>`` 字重尾剥除 —— payload "Tinos-Regular" 与源 ``{Tinos}``、
#: "Amiri-Regular" 与 ``{Amiri-Regular.ttf}`` 归一到同茎。
_WEIGHT_TAIL_RE = re.compile(
    r"-(?:regular|bold|italic|bolditalic|light|medium|thin|black|semibold|"
    r"extralight|extrabold|heavy|demibold|ultralight|normal|book|oblique|"
    r"boldoblique|italicbold)$",
    re.IGNORECASE,
)


def _font_stem(name: str) -> str:
    """``fontspec`` 引用名归一化: 剥文件扩展名 + ``-<weight>`` 尾 + 空白 → casefold 茎。"""
    n = _FONT_FILE_RE.sub("", name.strip())
    n = _WEIGHT_TAIL_RE.sub("", n)
    return re.sub(r"\s+", " ", n).strip().casefold()


#: 默认克隆表 (``params.clone_table`` 覆盖): 归一化茎 → **文件形**替换名。
#: 家族名在 fixloop 面不可探测 (``run_tool`` 无 FONTCONFIG_FILE 注入,
#: fc-list 对 texmf 字族恒盲), 文件形经 ``eng.probe_file`` kpathsea 同
#: fontspec 文件查找同一通路; 字体名写入站点后 fontspec 对文件形名
#: 自动同目录补全字重 (texgyretermes/Tinos/NotoSerif 实测 verbatim)。
#: Amiri 不收 —— TL 内外皆无度量克隆, 强替发错字体声明 (车道裁决 unfixable)。
_CLONE_TABLE: dict[str, str] = {
    # URW Nimbus 系与 TeX Gyre 同源度量克隆; nimbus 只发 TFM/pfb, fontspec 面无件。
    "nimbus roman": "texgyretermes-regular.otf",
    "nimbus sans": "texgyreheros-regular.otf",
    "nimbus mono ps": "texgyrecursor-regular.otf",
    # 同件在 texmf truetype 树 —— 文件形引用绕 fontconfig 直中,
    # ``Path = fonts/...`` 捆绑键剥除后保作者字体 (2609.20064 anthology-ch.cls)。
    "tinos": "Tinos-Regular.ttf",
    "notoserif": "NotoSerif-Regular.ttf",
}

#: 文件名绑定 keyval —— 换字体名后仍指原档, 整键剥除 (``Path``/``Extension``
#: 定位原档; ``*Font`` 把各字重绑到原档文件名)。其余键 (Scale/Ligatures/
#: Numbers/FakeBold…) 为渲染语义, 换字体后仍成立 → 保留。
_FONTSPEC_FILEBIND_KEYS = frozenset(
    {
        "path",
        "extension",
        "uprightfont",
        "boldfont",
        "italicfont",
        "bolditalicfont",
        "slantedfont",
        "boldslantedfont",
        "smallcapsfont",
        "swashfont",
    }
)

#: fontspec 声明 cs 面 —— 与 rules/50-font.yaml font_name_substitute 同族
#: (裸名形) + 带族名实形 (``\newfontfamily\cs``/``\babelfont[lang]{fam}``)。
_FONTSPEC_NAME_CS = (
    "setmainfont",
    "setsansfont",
    "setmonofont",
    "setromanfont",
    "setmathrm",
    "setmathfont",
    "fontspec",
    "setfontfamily",
    "setCJKmainfont",
    "setCJKsansfont",
    "setCJKmonofont",
)
_FONTSPEC_FAM_CS = (
    "newfontfamily",
    "newfontface",
    "setfontface",
    "newCJKfontfamily",
    "babelfont",
)

#: 可括号选项组 (keyval 内不收方括号 —— 非嵌套足够)。
_FS_OPT = r"\[[^\[\]]*\]"

#: ``\cs[opt]{name}[opt]`` / ``\cs{name}[opt]`` —— fontspec 前后双序并收。
_NAME_SITE_RE = re.compile(
    r"\\(?P<cs>" + "|".join(_FONTSPEC_NAME_CS) + r")(?![a-zA-Z@])"
    r"(?P<pre>\s*" + _FS_OPT + r")?\s*"
    r"\{(?P<name>[^{}]+)\}"
    r"(?P<post>\s*" + _FS_OPT + r")?"
)

#: ``\cs[opt]{fam|cs}[opt]{name}[opt]`` —— 族名实参形。
_FAM_SITE_RE = re.compile(
    r"\\(?P<cs>" + "|".join(_FONTSPEC_FAM_CS) + r")(?![a-zA-Z@])"
    r"(?P<pre>\s*" + _FS_OPT + r")?\s*"
    r"(?P<fam>\{[^{}]*\}|\\[a-zA-Z@]+)"
    r"(?P<mid>\s*" + _FS_OPT + r")?\s*"
    r"\{(?P<name>[^{}]+)\}"
    r"(?P<post>\s*" + _FS_OPT + r")?"
)


def _split_kv(inner: str) -> list[str]:
    """``keyval`` 顶层逗号切分 (花括内逗号不切)。"""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in inner:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _strip_filebind_opts(opt: str | None) -> str:
    r"""``[k=v, ...]`` 组剥文件名绑定键 → 重建 ``[..]``; 空组/缺席 → ``""``。"""
    if not opt or "[" not in opt:
        return ""
    inner = opt[opt.index("[") + 1 : opt.rindex("]")]
    kept = [
        kv.strip()
        for kv in _split_kv(inner)
        if kv.strip()
        and kv.split("=", 1)[0].strip().casefold() not in _FONTSPEC_FILEBIND_KEYS
    ]
    return "[" + ", ".join(kept) + "]" if kept else ""


def _clone_fix_text(t: str, resolve: Callable[[str], str | None]) -> tuple[str, int]:
    """单文件 fontspec 站点逐替换 → (新文本, 改写站点数)。

    遮盖视图命中且匹配体完整未遮 (``_live_matches`` 同判据); 茎 ∈ 表
    且 ``resolve(stem)`` 得可 kpathsea 命中的文件形名 → 名替换 +
    前后 ``[..]`` 组剥 ``_FONTSPEC_FILEBIND_KEYS``。一轮扫全表 (不只
    payload 茎) —— 同稿多缺名字体同轮收敛。
    """
    masked = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for rx, is_fam in ((_NAME_SITE_RE, False), (_FAM_SITE_RE, True)):
        for m in rx.finditer(masked):
            if not _is_live(m, masked, t):
                continue
            sub = resolve(_font_stem(m["name"]))
            if sub is None:
                continue
            pre = _strip_filebind_opts(m["pre"])
            post = _strip_filebind_opts(m["post"])
            rep = "\\" + m["cs"] + pre
            if is_fam:
                rep += m["fam"] + _strip_filebind_opts(m["mid"])
            rep += "{" + sub + "}" + post
            if rep != m[0]:
                edits.append((m.start(), m.end(), rep))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def fontspec_clone_sub(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``fontspec`` 名查找字体真缺 → 表驱动文件形名替换 + 文件名绑定键剥除 (fontfb-A)。

    ``fontspec_missing|X`` 里 install_sysfont 装不上 (payload 是家族名/
    无 filemap 档) 与 font_name_substitute 无差别换 Latin Modern 之间
    的精确臂: 度量克隆表逐茎替换 —— Nimbus 系 → TeX Gyre 同源克隆,
    Tinos/NotoSerif → texmf truetype 同件文件形名 (``Path = fonts/…``
    捆绑键剥除后保作者字体)。克隆件经 ``eng.probe_file`` 实证可达才
    动笔, 全灭 → decline 落回 31 号 LM 臂; payload 茎不在表 → decline
    (Amiri 无克隆不收 = 车道裁决 unfixable, 不发错字体声明)。
    """
    table = {
        _font_stem(str(k)): str(v)
        for k, v in (params.get("clone_table") or _CLONE_TABLE).items()
    }
    if not payload or _font_stem(payload) not in table:
        return False, f"payload {payload!r} has no clone-table entry"
    memo: dict[str, str | None] = {}

    def _resolve(stem: str) -> str | None:
        if stem not in memo:
            cand = table.get(stem)
            memo[stem] = cand if cand and eng.probe_file(cand) else None
        return memo[stem]

    if _resolve(_font_stem(payload)) is None:
        return False, f"clone for {payload!r} not resolvable via kpathsea"
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    n_sites = 0
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n = _clone_fix_text(t, _resolve)
        if n and nt != t:
            ctx.write(f, nt)
            n_sites += n
            n_files += 1
    if not n_sites:
        return False, f"no fontspec sites named {payload!r} in fileset"
    return True, f"clone-substituted {n_sites} fontspec site(s) in {n_files} file(s)"


# ════════════════════════════════════════════════════════════════
# fontenc_enc_relax: missing_file|<enc>enc.def → 未使用 enc 从 fontenc 选项摘除
# ════════════════════════════════════════════════════════════════

#: ``<enc>enc.def`` payload → enc 名 (t2aenc.def→T2A, lgrenc.def→LGR)。
_ENC_DEF_RE = re.compile(r"^([a-zA-Z0-9]+)enc\.def$", re.IGNORECASE)

#: ``\usepackage[..,ENC,..]{fontenc}`` / ``\RequirePackage`` 选项表行。
_FONTENC_LOAD_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*\[([^\]]*)\]\s*\{\s*fontenc\s*\}"
)


def _enc_use_res(enc: str) -> list[re.Pattern[str]]:
    r"""``enc`` 被「使用」的探针集。

    ``\fontencoding{ENC}`` 选定与 ``\DeclareText{Symbol,Command,Accent,Composite}{cs}{ENC}``
    声明; ``\DeclareFontEncoding{ENC}`` 本身是装载点不归使用 (可摘)。
    """
    e = re.escape(enc)
    return [
        re.compile(rf"\\fontencoding\s*\{{\s*{e}\s*\}}"),
        re.compile(
            rf"\\DeclareText(?:Symbol|Command|Accent|Composite)"
            rf"\s*\{{[^{{}}]*\}}\s*\{{\s*{e}\s*\}}"
        ),
    ]


def _strip_enc_opts(t: str, enc: str) -> tuple[str, int]:
    """``fontenc`` 选项表摘除 ``enc`` → (新文本, 摘除数); 表空则连方括号一起去。"""
    masked = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    want = enc.casefold()
    for m in _FONTENC_LOAD_RE.finditer(masked):
        if not _is_live(m, masked, t):
            continue
        toks = [k.strip() for k in m[1].split(",")]
        kept = [k for k in toks if k and k.casefold() != want]
        if len(kept) == len([k for k in toks if k]):
            continue
        if kept:
            edits.append((m.start(1), m.end(1), " " + ", ".join(kept) + " "))
        else:
            edits.append((m.start(1) - 1, m.end(1) + 1, ""))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _comment_enc_decl(t: str, enc: str) -> tuple[str, int]:
    r"""``\DeclareFontEncoding{ENC}`` 整行注释 → (新文本, 注释数)。

    decl 即 ``<enc>enc.def`` 装载点 —— 全文无 ``\fontencoding{ENC}`` 使用时
    (已由调用方前置保证) 声明是死件, 注释摘除零语义差。
    """
    rx = re.compile(
        rf"^[ \t]*\\DeclareFontEncoding\s*\{{\s*{re.escape(enc)}\s*\}}[^\n]*",
        re.MULTILINE,
    )
    masked = mask_tex(t)
    edits = [
        (m.start(), m.end(), "%" + m[0])
        for m in rx.finditer(masked)
        if _is_live(m, masked, t)
    ]
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def fontenc_enc_relax(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``missing_file|<enc>enc.def`` → 未使用 enc 从 fontenc 装载点摘除 (fontfb-B)。

    install_file/vendored_fetch 全真件臂 (t2aenc/lgrenc 皆有 filemap 档 +
    vendor 真件) 之后的末位改写臂 —— 面向既无档又无 vendor 件的 enc.def。
    全文无 ``\fontencoding{ENC}``/``\DeclareText*{..}{ENC}`` 使用时:
    ``\usepackage[..,ENC,..]{fontenc}`` 选项摘 ENC (表空连方括号去,
    ``\usepackage{fontenc}`` TU 默认下无害) + 裸 ``\DeclareFontEncoding``
    行注释。ENC 在使 → decline 诚实 unfixable (T2A→OT2 换编码产 mojibake,
    无安全替代); 装载点不见 → 传递性请求 (babel ldf 内拉) 同样 decline。
    """
    del eng
    m = _ENC_DEF_RE.match(payload or "")
    if not m:
        return False, f"payload {payload!r} is not an <enc>enc.def"
    enc = m[1].upper()
    blob = mask_tex(ctx.source_blob())
    if any(rx.search(blob) for rx in _enc_use_res(enc)):
        return False, f"{enc} selected in source — strip unsafe"
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    n_sites = 0
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n1 = _strip_enc_opts(t, enc)
        nt, n2 = _comment_enc_decl(nt, enc)
        if n1 + n2 and nt != t:
            ctx.write(f, nt)
            n_sites += n1 + n2
            n_files += 1
    if not n_sites:
        return False, f"{enc} not referenced by any fontenc load — transitive"
    return True, f"stripped {enc} from {n_sites} site(s) in {n_files} file(s)"


# ════════════════════════════════════════════════════════════════
# nfss_enc 三臂: xelatex TU 下 legacy NFSS enc 声明族 (nfsstu 车道)
# ════════════════════════════════════════════════════════════════

#: ``Command \X unavailable in encoding E`` —— 实报 enc 从 err_head 提取
#: (缺省 TU)。payload 只载 cs 名, enc 在签名尾段。
_NFSS_UNAVAIL_RE = re.compile(r"unavailable in encoding ([A-Za-z0-9]+)")

#: Arm A TU 体表: cs 名 → ``\DeclareTextCommand`` 声明体。``\ensuremath``
#: 件两模态通用且不依赖字体覆盖面 —— ``\DeclareTextSymbol`` 字面槽在无
#: fontspec 的 cm 字体会 missing-char 软丢字 (f1c repro 实证), ``\ensuremath{'}``
#: 恰是稿自带 ``\providecommand*{\textprime}{\('}`` 的本义 (f1d 净)。
_NFSS_TU_BODY: dict[str, str] = {
    "textprime": r"\ensuremath{'}",
    "textdprime": r"\ensuremath{''}",
    "texttrprime": r"\ensuremath{'''}",
}


def nfss_cmd_enc_polyfill(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``nfss_enc|cs`` → ``\DeclareTextCommand{\cs}{E}{body}`` docclass 后注入。

    hyperref puenc.def 等对 PU 声明的 cs 在 TU 下调用即报本签 —— 稿自带
    ``\providecommand`` 兜底被先定义盖死, 唯一治法是给该 cs 补目标 enc
    分支 (per-enc 声明正是 NFSS 分发机制)。体表外 cs 直 decline 不猜字形。
    """
    del eng, params
    cs = (payload or "").strip().lstrip("\\")
    body = _NFSS_TU_BODY.get(cs)
    if body is None:
        return False, f"no TU body-table entry for \\{cs}"
    m = _NFSS_UNAVAIL_RE.search(ctx.err_head or "")
    enc = m[1] if m else "TU"
    snippet = rf"\DeclareTextCommand{{\{cs}}}{{{enc}}}{{{body}}}"
    if _inject_after_docclass(ctx, snippet):
        return True, f"declared \\{cs} for {enc} (polyfill)"
    return False, f"\\{cs} {enc} declaration already present"


#: Arm B 站点探针: ``\usefont{E}``/``\fontencoding{E}`` (E 大小写不敏,
#: NFSS enc 名规范化前字面匹配)。
def _nfss_enc_site_re(enc: str) -> re.Pattern[str]:
    return re.compile(
        rf"(\\(?:usefont|fontencoding)\s*)\{{\s*{re.escape(enc)}\s*\}}",
        re.IGNORECASE,
    )


#: T2A Cyrillic 字形 cs → Unicode 字符 (t2aenc.dfu
#: ``\DeclareUnicodeCharacter`` 逆推: 仅裸 cs 映射项 ——
#: ``\@tabacckludge``/``\U``/``\H`` 复合重音项无对应 cs)。大写 cs 名
#: 列字面, 小写形由名/字双 ``.lower()`` 推导 (``CYRZH``→``cyrzh``/Ж→ж)。
_CYR_PAIRS: tuple[tuple[str, str], ...] = (
    ("CYRYO", "Ё"),
    ("CYRDJE", "Ђ"),
    ("CYRIE", "Є"),
    ("CYRDZE", "Ѕ"),
    ("CYRII", "І"),
    ("CYRYI", "Ї"),
    ("CYRJE", "Ј"),
    ("CYRLJE", "Љ"),
    ("CYRNJE", "Њ"),
    ("CYRTSHE", "Ћ"),
    ("CYRUSHRT", "Ў"),
    ("CYRDZHE", "Џ"),
    ("CYRA", "А"),
    ("CYRB", "Б"),
    ("CYRV", "В"),
    ("CYRG", "Г"),
    ("CYRD", "Д"),
    ("CYRE", "Е"),
    ("CYRZH", "Ж"),
    ("CYRZ", "З"),
    ("CYRI", "И"),
    ("CYRISHRT", "Й"),
    ("CYRK", "К"),
    ("CYRL", "Л"),
    ("CYRM", "М"),
    ("CYRN", "Н"),
    ("CYRO", "О"),
    ("CYRP", "П"),
    ("CYRR", "Р"),
    ("CYRS", "С"),
    ("CYRT", "Т"),
    ("CYRU", "У"),
    ("CYRF", "Ф"),
    ("CYRH", "Х"),
    ("CYRC", "Ц"),
    ("CYRCH", "Ч"),
    ("CYRSH", "Ш"),
    ("CYRSHCH", "Щ"),
    ("CYRHRDSN", "Ъ"),
    ("CYRERY", "Ы"),
    ("CYRSFTSN", "Ь"),
    ("CYREREV", "Э"),
    ("CYRYU", "Ю"),
    ("CYRYA", "Я"),
    ("CYRGUP", "Ґ"),
    ("CYRGHCRS", "Ғ"),
    ("CYRZHDSC", "Җ"),
    ("CYRZDSC", "Ҙ"),
    ("CYRKDSC", "Қ"),
    ("CYRKVCRS", "Ҝ"),
    ("CYRKBEAK", "Ҡ"),
    ("CYRNDSC", "Ң"),
    ("CYRNG", "Ҥ"),
    ("CYRSDSC", "Ҫ"),
    ("CYRY", "Ү"),
    ("CYRYHCRS", "Ұ"),
    ("CYRHDSC", "Ҳ"),
    ("CYRCHRDSC", "Ҷ"),
    ("CYRCHVCRS", "Ҹ"),
    ("CYRSHHA", "Һ"),
    ("CYRpalochka", "Ӏ"),
    ("CYRAE", "Ӕ"),
    ("CYRSCHWA", "Ә"),
    ("CYROTLD", "Ө"),
)
_T2A_GLYPHS: dict[str, str] = {}
for _cs, _ch in _CYR_PAIRS:
    _T2A_GLYPHS[_cs] = _ch
    _T2A_GLYPHS[_cs.lower()] = _ch.lower()

#: enc → 该 enc 字形 cs 表。表外 enc 仍做站点改写 (残留 undefined_cs
#: 由 cs 族臂下轮接), 但 note 如实报无表。
_NFSS_GLYPH_TABLES: dict[str, dict[str, str]] = {"T2A": _T2A_GLYPHS}


def _nfss_glyph_re(table: dict[str, str]) -> re.Pattern[str]:
    r"""活文本里本 enc 字形 cs 的使用探针 (``\\``+名+``\\b`` 全名匹配)。"""
    names = sorted(table, key=len, reverse=True)
    return re.compile(r"\\(" + "|".join(names) + r")\b")


def _rewrite_enc_sites(t: str, rx: re.Pattern[str]) -> tuple[str, int]:
    """``{E}`` 段改 ``{TU}`` → (新文本, 改写数); 遮盖区命中跳过。"""
    masked = mask_tex(t)
    edits = [
        (m.start(0) + len(m[1]), m.end(0), "{TU}")
        for m in rx.finditer(masked)
        if _is_live(m, masked, t)
    ]
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def _glyph_uses(t: str, glyph_re: re.Pattern[str]) -> set[str]:
    """活文本里命中的字形 cs 名集合 (遮盖区命中不计)。"""
    masked = mask_tex(t)
    return {m[1] for m in glyph_re.finditer(masked) if _is_live(m, masked, t)}


def _scan_sites(
    ctx: LoopCtx,
    exts: tuple[str, ...],
    site_re: re.Pattern[str],
    glyph_re: re.Pattern[str] | None,
) -> tuple[int, int, set[str]]:
    """逐文件站点改写 + 字形 cs 使用扫描 → (改写数, 触文件数, 命中 cs 集)。"""
    n_sites, n_files = 0, 0
    used: set[str] = set()
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n = _rewrite_enc_sites(t, site_re)
        if n:
            ctx.write(f, nt)
            n_sites += n
            n_files += 1
            t = nt
        if glyph_re is not None:
            used.update(_glyph_uses(t, glyph_re))
    return n_sites, n_files, used


def _polyfill_snippet(used: set[str], table: dict[str, str]) -> str:
    r"""命中 cs 各一行 ``\providecommand{\cs}{glyph}`` (名序)。"""
    return "\n".join(rf"\providecommand{{\{cs}}}{{{table[cs]}}}" for cs in sorted(used))


def nfss_enc_scheme_relax(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``nfss_enc|enc`` → 活 ``\usefont/\fontencoding{E}`` 站点改 TU + 字形 cs polyfill。

    空 ``\DeclareFontEncoding{E}{}{}`` 实证产 "Corrupted NFSS tables"
    (f2a: 无 .fd 的 enc 声明是硬错非安全兜底), 故走源面站点改写 ——
    enc 直选点转 TU, 字形 cs 由 literal-char providecommand 承接
    (2609.20339 ``\easycyrsymbol{\CYRZH}`` 族, f2b repro 净)。无活站点
    decline; 表外 enc 站点照改, 残留 cs 留给下轮 cs 族臂。
    """
    del eng
    enc = (payload or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]+", enc):
        return False, f"payload {payload!r} is not an encoding name"
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    table = _NFSS_GLYPH_TABLES.get(enc.upper(), {})
    glyph_re = _nfss_glyph_re(table) if table else None
    n_sites, n_files, used = _scan_sites(ctx, exts, _nfss_enc_site_re(enc), glyph_re)
    if not n_sites and not used:
        return False, f"{enc} has no live \\usefont/\\fontencoding sites"
    n_poly = 0
    if used and _inject_after_docclass(ctx, _polyfill_snippet(used, table)):
        n_poly = len(used)
    note = f"rewrote {n_sites} {enc} site(s) to TU in {n_files} file(s)"
    if n_poly:
        note += f" + {n_poly} glyph polyfill(s)"
    elif used:
        note += "; glyph polyfills already present"
    elif not table:
        note += f"; no glyph table for {enc}"
    return True, note


def nfss_fam_declare(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``nfss_enc|E+F`` → ``\DeclareFontFamily{E}{F}{}`` docclass 后注入。

    签名成立前提 = enc E 已声明 (``\DeclareFontShape`` 先查 ``T@E`` 再查
    ``E+F`` —— E 未声明会先报 ``Encoding scheme`` 签走 scheme 臂)。空
    family 声明合法 (fd 文件同款; 与空 enc 声明的 Corrupted-NFSS 死路
    不同机制), 2609.20539 times.sty ``\AtBeginDocument\DeclareFontShape``
    钩 f3 repro 净。
    """
    del eng, params
    m = re.fullmatch(r"([A-Za-z0-9]+)\+([A-Za-z0-9]+)", (payload or "").strip())
    if not m:
        return False, f"payload {payload!r} is not an E+F family pair"
    enc, fam = m[1], m[2]
    snippet = rf"\DeclareFontFamily{{{enc}}}{{{fam}}}{{}}"
    if _inject_after_docclass(ctx, snippet):
        return True, f"declared font family {enc}+{fam}"
    return False, f"family {enc}+{fam} declaration already present"


# ════════════════════════════════════════════════════════════════
# umath_doc_cs_restore: unicode-math 遮蔽 doc 自定义 cs → 复位 (qc-impl)
# ════════════════════════════════════════════════════════════════

#: ``\\UnicodeMathSymbol{cp}{\\cs}{cls}`` 行内 cs 名提取——unicode-math
#: 已知名全集以 TL 装件 ``unicode-math-table.tex`` 为准 (进程缓存)。
_UMATH_ROW_RX = re.compile(r"\\UnicodeMathSymbol\{[^{}]*\}\s*\{\\([A-Za-z@]+)\}")
#: ``_umath_names`` 进程级名表缓存——dict 可变容器避免 global 重绑 (PLW0603)。
_UMATH_CACHE: dict[str, frozenset[str]] = {}

#: doc 侧 ``\\newcommand`` 族定义头 —— 抓 cs 名 + 可选 ``[nargs]``;
#: body 另行平衡组/单 token 提取 (regex 吃不下平衡括)。
_UMATH_DEF_RX = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)"
    r"\s*\*?\s*\{?\\([A-Za-z@]+)\}?\s*(\[[0-9]\])?"
)

#: unicode-math 装载面探针 (\\usepackage{unicode-math} / \\setmathfont)。
_UMATH_LOAD_RX = re.compile(r"unicode-math|unicode_math|\\setmathfont")


def _umath_names(ctx: LoopCtx) -> frozenset[str] | None:
    """``kpsewhich unicode-math-table.tex`` → umath 已知名集 (None=不可解析)。"""
    if "names" in _UMATH_CACHE:
        return _UMATH_CACHE["names"]
    rc, out, _to = ctx.run_tool(["kpsewhich", "unicode-math-table.tex"], 15)
    if rc != 0:
        return None
    path = next(
        (
            ln.strip()
            for ln in out.splitlines()
            if ln.strip().endswith("unicode-math-table.tex")
        ),
        "",
    )
    if not path:
        return None
    try:
        data = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    _UMATH_CACHE["names"] = frozenset(_UMATH_ROW_RX.findall(data))
    return _UMATH_CACHE["names"]


def _cs_tok_end(t: str, pos: int) -> int:
    r"""``t[pos]=='\\'`` → cs token 末 offset (字母+@ 连读, 否则单字符)。"""
    j = pos + 1
    if j < len(t) and (t[j].isalpha() or t[j] == "@"):
        while j < len(t) and (t[j].isalpha() or t[j] == "@"):
            j += 1
    else:
        j = pos + 2
    return j


def _umath_doc_defs(t: str, umath: frozenset[str]) -> dict[str, str]:
    r"""单文件 doc-def 收割: umath 名表 ∩ ``\newcommand`` 族 → ``\renewcommand`` 复位行。

    body 原文搬运; 头部命中在遮盖视图 (注释/verbatim 内定义不收); body 在原文取——
    mask_tex 保长, 双视错位等。
    """
    vis = mask_tex(t)
    out: dict[str, str] = {}
    for m in _UMATH_DEF_RX.finditer(vis):
        name, nargs = m.group(1), m.group(2) or ""
        if name not in umath:
            continue
        pos = _skip_ws(t, m.end())
        if pos >= len(t):
            continue
        if t[pos] == "{":
            end = _brace_end(t, pos)
            if end > len(t):
                continue
            body = t[pos:end]
        elif t[pos] == "\\":
            end = _cs_tok_end(t, pos)
            body = t[pos:end]
        elif t[pos].isalpha() or t[pos] in "#$%&~^_":
            continue  # 裸字符 body——异常形不收
        else:
            body, end = t[pos : pos + 1], pos + 1
        out[name] = f"\\renewcommand{{\\{name}}}{nargs}{body}"
    return out


def umath_doc_cs_restore(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""unicode-math 遮蔽 doc ``\\newcommand`` 名 → ``\\AtBeginDocument`` 复位。

    实证 (qc-impl 2026-09-28, 2609.19583): ``unicode-math-table.tex:1302``
    ``\\smt``=U+2AAA 覆盖 doc ``\\newcommand{\\smt}{SMT\\xspace}``,
    LinLibertine 无槽 → 节首 tofu (char_table ``smaller_than``→``<`` 只救
    字面不收 cs 产出)。``\\AtBeginDocument`` 钩按注册序执行, 导言区末位
    注入使复位行晚于 umath 字体装载钩生效——doc 定义重夺名。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    names = _umath_names(ctx)
    if not names:
        return False, "unicode-math-table.tex not resolvable"
    blob = "\n".join(s for f in ctx.tex_files(exts) if (s := ctx.read(f)) is not None)
    if not _UMATH_LOAD_RX.search(blob):
        return False, "unicode-math not loaded"
    restored: dict[str, str] = {}
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        restored.update(_umath_doc_defs(t, names))
    if not restored:
        return False, "no doc def shadowed by unicode-math"
    lines = [
        "% fixloop: umath_doc_cs_restore",
        "\\makeatletter",
        "\\AtBeginDocument{%",
        *[f"{v}%" for v in restored.values()],
        "}",
        "\\makeatother",
    ]
    if not _inject_before_begindoc(ctx, "\n".join(lines)):
        return False, "restore hook already injected"
    return True, f"restored {len(restored)} shadowed cs: {', '.join(sorted(restored))}"
