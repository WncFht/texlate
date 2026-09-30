r"""builtins._mcfallback — font_fallback 逐字回退 + 数学域双模修 (C5 拆叶)。

``newunicodechar`` 注入块行表 (``_fb_snippet_lines``/``_inject_fallback_lines``),
回退字体有序候选解析 (``_fb_font_resolve``/``_resolve_font_cands`` +
``_FONT_FILE_RE`` 文件形分流), 数学域守卫 (``_MATH_GUARD_BEGIN_RE``/
``_math_guard_spans``/``_in_spans``) 与无参字母 cs 逃逸 shim
(``_MATH_SHIM_ARG_CS``/``_math_cs_shim_names``/``_inject_math_cs_shims``),
归口 ``font_fallback`` 入口。common 常量 (``_FB_FONT``/``_MATH_SHIM_CS``/
``_mc_chr``/``_mc_hit``) 与 ``MATH_ENVS``/``cs_events_spans`` 经本叶回引。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _FB_FONT,
    _MATH_SHIM_CS,
    _inject_after_docclass,
    _mc_chr,
    _mc_hit,
    _mc_seen,
    _mc_table,
)
from texlate.latex.tables import MATH_ENVS
from texlate.textutil import cs_events_spans, mask_tex

if TYPE_CHECKING:
    from collections.abc import Iterable

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine

__all__ = [
    "MATH_ENVS",
    "_FB_FONT",
    "_FB_RANGES",
    "_FONT_FILE_RE",
    "_MATH_GUARD_BEGIN_RE",
    "_MATH_SHIM_ARG_CS",
    "_MATH_SHIM_CS",
    "_fb_font_resolve",
    "_fb_snippet_lines",
    "_in_spans",
    "_inject_after_docclass",
    "_inject_fallback_lines",
    "_inject_math_cs_shims",
    "_math_cs_shim_names",
    "_math_guard_spans",
    "_mc_chr",
    "_mc_hit",
    "_resolve_font_cands",
    "cs_events_spans",
    "font_fallback",
]


#: font_fallback 默认覆盖带 (scout-misschar 2026-09-16: 西里尔人名真损失
#: U+0400-04FF / 组合符 U+0300-036F / 拉丁扩展 U+00C0-017F)。
#: ``params.fallback_ranges`` 覆盖带表、``params.fallback_font`` 换字体。
_FB_RANGES: tuple[tuple[int, int], ...] = (
    (0x0400, 0x04FF),
    (0x0300, 0x036F),
    (0x00C0, 0x017F),
)

#: ``fallback_fonts`` 候选名按扩展名分流探测：字体文件名 (otf/ttf/ttc)
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

    条目为名字符串或 ``{name, install}`` 映射：文件形名 (``_FONT_FILE_RE``
    命中) 经 ``eng.probe_file`` 探测，``install: true`` 时 miss 先
    ``eng.install_file`` 再复核 (texmf 树外字体包如 unfonts-core 可补装);
    家族名经 ``fc-list <name> family`` 非空输出探测 (fc-list 缺席/查无此族
    → 下一候选)。未给 ``fallback_fonts`` 时走 ``fallback_font``/``_FB_FONT``
    单值旧路——不探测，保持既有臂行为不变。
    """
    cands = params.get("fallback_fonts")
    if not cands:
        return str(params.get("fallback_font") or _FB_FONT), ""
    return _resolve_font_cands(ctx, eng, cands)


def _resolve_font_cands(
    ctx: LoopCtx, eng: Engine, cands: Iterable[Any]
) -> tuple[str | None, str]:
    """有序字体候选 → 首个可解析字体名; 全灭 → (None, 原因)。

    条目为名字符串或 ``{name, install}`` 映射：文件形名 (``_FONT_FILE_RE``
    命中) 经 ``eng.probe_file`` 探测，``install: true`` 时 miss 先
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


#: ``\begin{数学 env}`` 起锚 —— ``$..$``/``\(\)`` 之外的数学体 (重音 cs 改写
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
#: cs_rebind 的无参 emit 形消费不到本表 (按设计，含参站点不在其管面)。
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
    )  # 字体名正则：命中即跳 (CJK cp 落 CJK 字体是真缺字形)
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
