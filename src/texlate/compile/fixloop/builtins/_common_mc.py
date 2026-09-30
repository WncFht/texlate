r"""builtins._common_mc — missing_char 规划侧机制 (common 拆分)。

「Missing character」行解析 → 码位 → ``_MC_TABLE`` 表匹配 → 修复规划
(``_mc_hit``/``_mc_plan``); 修复动作本体 (warmup/字面替换/逐字回退/
accent 站点) 留在 ``builtins.misschar`` —— 本叶是 shim 叶同消费的
读侧/规划侧单源 (C3 收尾归位)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

__all__ = [
    "_CJK_FONT_RE",
    "_FB_FONT",
    "_MATH_SHIM_CS",
    "_MC_TABLE",
    "_fb_font_body",
    "_fb_preamble_lines",
    "_mc_chr",
    "_mc_hit",
    "_mc_plan",
    "_mc_table",
]

#: ``Missing character: There is no <what> (U+XXXX)? in font <font>``
#: 消息正则 (``_MISSCHAR_MSG_RX``)、U+000A 折行拼回 (``_MISSCHAR_WRAP_RX``)
#: 与码位解析 (``_misschar_cp``) 单源在更深的 ``texlate.texlog`` ——
#: fixloop→texlog 边既存 (engine/actions 同向), 本叶直引同口径件,
#: 不再同形双写。spec 字体 ``(U+XXXX)`` / tfm 字体 ``("XXXX)`` 十六进制 /
#: pdftex 8-bit 裸字符 / ``^^xx``/``^^X`` 记法的判定细则见彼层。

#: 判定「字体本身即 CJK 字体」的排除模式 —— CJK 码位落在 CJK 字体里
#: 是真缺字形 (换字体的 warmup 救不了), 不属于绑定污染类。
_CJK_FONT_RE = re.compile(
    r"fandol|noto.*cjk|source.?han|uming|ukai|wqy|ipa(?:ex)?[mg]|"
    r"sim(?:sun|hei|kai|fang)|ms ?(?:gothic|mincho)|cjk",
    re.IGNORECASE,
)


#: missing_char 修复默认表 (seeded 自 n100 缺字签名, 2026-09-16;
#: ``params.char_table`` 同形条目按 id 覆盖/扩列 —— 首匹配生效)。
#: 每条目: ``id``; 匹配面 ``cps:[int]`` | ``ranges:[[lo,hi],...]``,
#: ``font``/``font_not`` 为作用在日志字体名上的正则; 动作:
#: ``action: cjk_warmup`` (预热 xeCJK 字体绑定) 或 ``replace: "<TeX串>"``。
_MC_TABLE: list[dict[str, Any]] = [
    {
        "id": "cjk_glyph",
        # CJK 统一表意+假名+谚文+兼容/全角区 —— 落在非 CJK 字体 = xeCJK
        # (本表是 textutil.CJK_RANGES 的语义超集: 缺字判定要罩住假名/谚文/
        # 彝文/全角, 勿向 CJK_RANGES 单源回退)
        # 绑定被污染 (elsart 族 \no@harm 下 \protect=\noexpand 使
        # \fontfamily/\selectfont 失效, 首用把 xeCJK/<fam>/<ser>/<sh>/<size>
        # 全局绑到 lmroman —— 探针实证), 预热即可。
        "ranges": [
            [0x2E80, 0x303F],
            [0x3040, 0x30FF],
            [0x3100, 0x31EF],
            [0x3200, 0x33FF],
            [0x3400, 0x4DBF],
            [0x4E00, 0x9FFF],
            [0xA000, 0xA4CF],
            [0xAC00, 0xD7AF],
            [0xF900, 0xFAFF],
            [0xFE30, 0xFE4F],
            [0xFF00, 0xFFEF],
            [0x20000, 0x2FA1F],
        ],
        "font_not": _CJK_FONT_RE.pattern,
        # 仅 spec 字体 ([lmroman10]:mapping=tex-text 形) 缺 CJK 才预热——
        # tfm 字体 (cmr10/ec-lmss12) 缺 CJK 大头是数学模式 (xeCJK
        # interchartoks 水平列机制不进数学, warmup 白烧到 stuck;
        # scout-misschar 2026-09-16 实证), 数学面已由 inject 侧
        # \Umathcode 符号字体兜底 (CJK_MATH_FALLBACK) 治。
        "font": r"[\[:]",
        "action": "cjk_warmup",
    },
    # n100: 0806.1079 ×3 ≠ in cmr7/cmr5
    {"id": "neq", "cps": [0x2260], "replace": "\\ensuremath{\\neq}"},
    # n100: 1608.02516 ×1 − in cmr10
    {"id": "minus", "cps": [0x2212], "replace": "\\ensuremath{-}"},
    # n100: 2403.15096 ×1 § in cmr10
    {"id": "section", "cps": [0x00A7], "replace": "\\S"},
    # n100: 1003.1464 ×1 ø in cmmi8 (math italic → \mbox 包文本字形)
    {"id": "oslash", "cps": [0x00F8], "replace": "\\mbox{\\o}"},
    # n100: 0707.3950 è in cmex10
    {"id": "egrave", "cps": [0x00E8], "replace": "\\mbox{\\`{e}}"},
]


def _mc_table(params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """内置表 + ``params.char_table`` 按 id 合并 (参数条目同 id 覆盖)。"""
    table = {e["id"]: e for e in _MC_TABLE}
    for e in params.get("char_table") or []:
        table[e["id"]] = e
    return table


def _mc_hit(entry: dict[str, Any], cp: int, font: str) -> bool:
    """码位+字体 vs 条目匹配面 (cps/ranges 与 font/font_not 正则)。"""
    if (fno := entry.get("font_not")) and re.search(fno, font, re.IGNORECASE):
        return False
    if (fyes := entry.get("font")) and not re.search(fyes, font, re.IGNORECASE):
        return False
    if cp in (entry.get("cps") or ()):
        return True
    return any(lo <= cp <= hi for lo, hi in entry.get("ranges") or ())


def _mc_plan(
    seen: dict[int, tuple[str, str]], table: dict[str, dict[str, Any]]
) -> tuple[bool, dict[str, str], int]:
    """逐缺字码位查表 → (是否需 CJK 预热, 字面替换映射, 未匹配数)。"""
    warm = False
    repl: dict[str, str] = {}
    unmatched = 0
    for cp, (what, font) in seen.items():
        entry = next((e for e in table.values() if _mc_hit(e, cp, font)), None)
        if entry is None:
            unmatched += 1
        elif entry.get("action") == "cjk_warmup":
            warm = True
        elif rep := entry.get("replace"):
            ch = what if len(what) == 1 else _mc_chr(cp)
            if ch:
                repl[ch] = rep
    return warm, repl, unmatched


def _mc_chr(cp: int) -> str | None:
    """码位 → 字符; 超出 Unicode 面 → None。"""
    try:
        return chr(cp)
    except ValueError:
        return None


_FB_FONT = "Libertinus Serif"  # TL libertinus-fonts, 三带全覆盖实证


def _fb_preamble_lines(fam: str, font: str) -> list[str]:
    r"""回退字体族声明行 —— fontspec 守卫 + ``\newfontfamily`` 幂等声明。

    ``builtins.misschar._fb_snippet_lines`` 与 shim ``cs_rebind`` 共用
    骨架: ``\ifdefined\<fam>`` 守卫使同族二次注入不炸 ``\newfontfamily``
    重定义; ``fam`` 参数支持第二回退族 (``txlatecjkfb`` 等)。
    """
    return [
        "\\ifdefined\\newfontfamily\\else\\RequirePackage{fontspec}\\fi",
        f"\\ifdefined\\{fam}\\else\\newfontfamily\\{fam}{{{font}}}\\fi",
    ]


def _fb_font_body(fam: str, ch: str) -> str:
    r"""``\ifmmode`` 数学/文本双域回退字体替换体 —— ``\mbox`` 逃回文本域。

    活动字符/cs 在数学内也展开, 但 ``\<fam>`` 只切文本族 —— ``\mbox``
    逃回文本域才能让回退字体生效 (scout-misschar math_font_chars 桶)。
    """
    return rf"\ifmmode\mbox{{\{fam} {ch}}}\else{{\{fam} {ch}}}\fi"


#: 无参字母/符号 cs —— 文本域字形产出者, 在数学域无重音义 (\' \^ \~ 等
#: 有数学义 = \acute \hat \tilde, 刻意不收)。cs 名 → 产出字符码位
#: (scout-misschar math_font_chars 桶: ``Y$\i$lmaz``/``$\L^{\phi,p}$`` 实证)。
_MATH_SHIM_CS: dict[str, int] = {
    "i": 0x0131,
    "j": 0x0237,
    "L": 0x0141,
    "l": 0x0142,
    "O": 0x00D8,
    "o": 0x00F8,
    "AA": 0x00C5,
    "aa": 0x00E5,
    "AE": 0x00C6,
    "ae": 0x00E6,
    "OE": 0x0152,
    "oe": 0x0153,
    "ss": 0x00DF,
    "th": 0x00FE,
    "TH": 0x00DE,
    "S": 0x00A7,
    "P": 0x00B6,
    "dag": 0x2020,
    "ddag": 0x2021,
    "copyright": 0x00A9,
    "pounds": 0x00A3,
}
