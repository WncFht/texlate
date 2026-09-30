r"""builtins._mcnfss — nfss_enc 三臂 legacy NFSS enc 声明族 (C5 拆叶)。

``nfss_enc|cs`` → ``\DeclareTextCommand`` TU 体表 polyfill
(``_NFSS_UNAVAIL_RE``/``_NFSS_TU_BODY``/``nfss_cmd_enc_polyfill``);
``nfss_enc|enc`` → 活 ``\usefont/\fontencoding{E}`` 站点改 TU + 字形 cs
polyfill (``_nfss_enc_site_re``/``_CYR_PAIRS``→``_T2A_GLYPHS``/
``_NFSS_GLYPH_TABLES``/``_nfss_glyph_re``/``_rewrite_enc_sites``/
``_glyph_uses``/``_scan_sites``/``_polyfill_snippet``/
``nfss_enc_scheme_relax``); ``nfss_enc|E+F`` → ``\DeclareFontFamily``
注入 (``nfss_fam_declare``)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _inject_after_docclass,
    _is_live,
    _splice,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import Engine

__all__ = [
    "_CYR_PAIRS",
    "_NFSS_GLYPH_TABLES",
    "_NFSS_TU_BODY",
    "_NFSS_UNAVAIL_RE",
    "_T2A_GLYPHS",
    "_ch",
    "_cs",
    "_glyph_uses",
    "_nfss_enc_site_re",
    "_nfss_glyph_re",
    "_polyfill_snippet",
    "_rewrite_enc_sites",
    "_scan_sites",
    "nfss_cmd_enc_polyfill",
    "nfss_enc_scheme_relax",
    "nfss_fam_declare",
]


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
