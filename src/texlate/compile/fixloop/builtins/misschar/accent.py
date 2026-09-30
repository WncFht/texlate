r"""builtins.misschar.accent — accent_mark_fix 组合附加符站点改写 (C5 拆叶)。

组合附加符码位 → 产生它的重音 cs 表 ``_ACCENT_CS`` + 站点正则
``_accent_site_re`` + 文本域 ``\\<cs>{x}`` 站点改写 ``_accent_fix_text``
(NFC 预组字面量 / 无预组剥 accent) —— ``accent_mark_fix`` 入口;
预组字自注 ``\newunicodechar`` 回退行直跨 ``misschar.fallback`` 叶
(``_inject_fallback_lines``/``_math_guard_spans``/``_in_spans``)。
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _FB_FONT,
    _mc_seen,
    _splice,
)
from texlate.compile.fixloop.builtins.misschar.fallback import (
    _in_spans,
    _inject_fallback_lines,
    _math_guard_spans,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine.ctx import LoopCtx
    from texlate.compile.fixloop.engine.proto import Engine

__all__ = [
    "_ACCENT_CS",
    "_accent_fix_text",
    "_accent_site_re",
    "accent_mark_fix",
]


# ════════════════════════════════════════════════════════════════
# accent_mark_fix: accent cs 生成的组合符 → 站点级源改写 (F4c)
# ════════════════════════════════════════════════════════════════

#: 组合附加符码位 → 产生它的重音 cs (scout-misschar-coverage 2026-09-17
#: 0327 群 ~62 pids: ``\c{t}`` 类在无预组字形基字符上产 base+combining
#: 节点，ambient 字体无 U+0300-036F → Missing character; 附加符由 accent
#: 机制生成非输入字符，``\newunicodechar`` 的 active-char 绑定拦不到)。
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
