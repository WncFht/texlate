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
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _FB_FONT,
    _MATH_SHIM_CS,
    _inject_after_docclass,
    _map_tex_files,
    _mc_chr,
    _mc_hit,
    _mc_parse_log,
    _mc_plan,
    _mc_table,
)
from texlate.latex.tables import MATH_ENVS
from texlate.textutil import cs_events_spans, mask_tex

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ════════════════════════════════════════════════════════════════
# missing_char: log「Missing character」行 → 码位分级 → 按类修复 (F4)
# ════════════════════════════════════════════════════════════════

#: xeCJK/ctex 支持探针 (source_contains 级) —— 有 CJK 机制才有绑定可预热。
_CJK_MECH_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\b[^\n%]*\{[^}]*\b(?:ctex|xeCJK|CJKutf8)\b"
    r"|\\(?:setCJK\w*font|CJKfontspec|ctexset|xeCJKsetup|newCJKfontfamily)\b"
)


def _compile_log_text(ctx: LoopCtx) -> str:
    """定位本轮编译 log。

    ``{stem}.log`` (xelatex) → ``_tect_out/{stem}.log`` (tectonic)
    → 任一含 Missing character 的 ``*.log`` (兜底)。
    """
    main = ctx.main_path()
    cands: list[Path] = []
    if main is not None:
        stem = main.stem
        cands += [ctx.wdir / f"{stem}.log", ctx.wdir / "_tect_out" / f"{stem}.log"]
    for p in cands:
        t = ctx.read(p) if p.is_file() else None
        if t and "Missing character" in t:
            return t
    for p in sorted(ctx.wdir.rglob("*.log")):
        t = ctx.read(p)
        if t and "Missing character" in t:
            return t
    return ""


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
    """
    del eng, payload
    log = _compile_log_text(ctx)
    if not log:
        return False, "no compile log with Missing character found"
    seen = _mc_parse_log(log)
    if not seen:
        return False, "Missing character lines present but no codepoint parsed"
    warm, repl, unmatched = _mc_plan(seen, _mc_table(params))

    applied: list[str] = []
    notes: list[str] = []
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


#: font_fallback 默认覆盖带 (scout-misschar 2026-09-16: 西里尔人名真损失
#: U+0400-04FF / 组合符 U+0300-036F / 拉丁扩展 U+00C0-017F)。
#: ``params.fallback_ranges`` 覆盖带表、``params.fallback_font`` 换字体。
_FB_RANGES: tuple[tuple[int, int], ...] = (
    (0x0400, 0x04FF),
    (0x0300, 0x036F),
    (0x00C0, 0x017F),
)


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
    """
    lines = [
        "% fixloop: per-char font fallback via newunicodechar",
        "\\usepackage{newunicodechar}",
        "\\ifdefined\\newfontfamily\\else\\usepackage{fontspec}\\fi",
        f"\\ifdefined\\{cs}\\else\\newfontfamily\\{cs}{{{font}}}\\fi",
    ]
    lines += (
        f"\\newunicodechar{{{c}}}"
        f"{{\\ifmmode\\mbox{{\\{cs} {c}}}\\else{{\\{cs} {c}}}\\fi}}"
        for cp in cps
        if (c := _mc_chr(cp)) is not None
    )
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


def _math_cs_shim_names(ctx: LoopCtx, seen: dict[int, tuple[str, str]]) -> list[str]:
    r"""缺字码位 ∩ cs 产出集 ∧ 源内 ``\\<cs>`` 现身数学 span → 待 shim 名单。

    双信号皆备才动: 码位在缺字表 (真有缺字) 且 cs 站点在数学域 (缺字确由
    数学内展开所产)——文本域 ``\i`` 缺字是 ambient 字体真缺字形, 不归此修。
    """
    cands = [cs for cs, cp in _MATH_SHIM_CS.items() if cp in seen]
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
    """
    cses = list(cses)
    if not cses:
        return []
    lines = ["% fixloop: math-mode escape for text letter cses"]
    for cs in cses:
        old = f"\\txlateold{cs}"
        lines += [
            rf"\ifdefined{old}\else\let{old}\{cs}\fi",
            rf"\protected\def\{cs}{{\ifmmode\mbox{{{old}}}\else{old}\fi}}",
        ]
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
    """
    del payload
    log = _compile_log_text(ctx)
    if not log:
        return False, "no compile log with Missing character found"
    seen = _mc_parse_log(log)
    done: list[str] = []
    if shimmed := _inject_math_cs_shims(ctx, _math_cs_shim_names(ctx, seen)):
        done.append("math cs shim: " + ", ".join(rf"\{c}" for c in shimmed))
    bands = params.get("fallback_ranges") or _FB_RANGES
    font_not = params.get(
        "font_not"
    )  # 字体名正则: 命中即跳 (CJK cp 落 CJK 字体是真缺字形)
    fb_cs = str(params.get("fallback_cs") or "txlatefallback")
    taken = {
        cp
        for cp, (what, font) in seen.items()
        for e in _mc_table(params).values()
        if e.get("replace") and _mc_hit(e, cp, font)
    }
    chars = [
        cp
        for cp, (_what, font) in seen.items()
        if cp not in taken
        and any(lo <= cp <= hi for lo, hi in bands)
        and not (font_not and re.search(str(font_not), font))
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
    font = str(params.get("fallback_font") or _FB_FONT)
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
    hits: list[tuple[int, str]] = []
    for ch, to in repl.items():
        start = 0
        while (i := masked.find(ch, start)) >= 0:
            if t[i] == ch:  # 同码位恰落在遮盖位 (' '/'\\n') 时守卫
                hits.append((i, to))
            start = i + 1
    if not hits:
        return t, 0
    hits.sort()
    out: list[str] = []
    prev = 0
    for i, to in hits:
        out.append(t[prev:i])
        out.append(to)
        prev = i + 1
    out.append(t[prev:])
    return "".join(out), len(hits)


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
    edits.sort()
    out: list[str] = []
    prev = 0
    for s, e, r in edits:
        out.append(t[prev:s])
        out.append(r)
        prev = e
    out.append(t[prev:])
    return "".join(out), composed, len(edits)


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
    log = _compile_log_text(ctx)
    if not log:
        return False, "no compile log with Missing character found"
    seen = _mc_parse_log(log)
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
