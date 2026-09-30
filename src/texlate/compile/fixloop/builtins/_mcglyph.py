r"""builtins._mcglyph — macro_glyph_fix 宏生成缺字站点改写 (C5 拆叶)。

无参符号 cs 产出表 ``_MACRO_GLYPH_CS`` + ``\char<N>`` OT1 槽位表
``_OT1_CHAR_SLOTS`` + 数值实参站 ``_CHAR_NUM_RE``/``_char_num_value`` +
``_macro_glyph_fix_text`` 双站点类逐改写 —— ``macro_glyph_fix`` 入口。
字形由 cs 展开/原语查槽所产非输入字符, 字面替换/newunicodechar 皆不可达。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import _mc_seen, _splice
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine

__all__ = [
    "_CHAR_NUM_RE",
    "_MACRO_GLYPH_CS",
    "_OT1_CHAR_SLOTS",
    "_char_num_value",
    "_macro_glyph_fix_text",
    "macro_glyph_fix",
]


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
