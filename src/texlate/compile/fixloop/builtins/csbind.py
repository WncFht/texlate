r"""builtins.csbind — 上古/产出 cs 守卫式重绑 (builtins.shim C3 再拆叶)。

缺定义/产出错位的 cs 按 ``\ifdefined`` 守卫注入重绑, 三族:
``font_cs_shim`` AMS 上古字体 cs (``\fivmi`` 族) → ``\font`` 绑 CM
等价; ``cs_rebind`` TFM 字体下 cs 产出字符缺字 → ``\protected\def``
绑回退字体; ``bm_mathchar_wrap`` ``\bm`` 族 atom-walk 撞 XeTeX 15-bit
mathchar 墙 → 组路径守卫重定义。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

from texlate.compile.fixloop.builtins.common import (
    _FB_FONT,
    _MATH_SHIM_CS,
    _fb_font_body,
    _fb_preamble_lines,
    _fixloop_log,
    _inject_after_docclass,
    _inject_before_begindoc,
    _mc_chr,
    _mc_seen,
    _mc_table,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


#: AMS 上古字体 cs 名 ``<size><fam>`` 全词锚 —— ``\\fivmi``/``\\tenmib``
#: 族 (hep-th/9703214: ``\\doit{0}`` 死块内 ``\\font`` 定义不执行，活
#: ``\\skewchar\\fivmi`` 全链 undefined_cs ×83)。缩拼 + 全拼双写
#: (``\\fivemib`` 同稿实证)。``i`` 尾收 plain ``\\teni`` (cmmi10 惯名)。
#: 匹配模式由 ``_AMS_FONT_SIZE`` × ``_AMS_FONT_FAM`` 键合成 (params 可扩)。
#: 尺寸词 → pt (elv/frtn/... 是 LaTeX ``\\@xpt`` 族的 scaled-10 惯例值)。
_AMS_FONT_SIZE: dict[str, float] = {
    "fiv": 5,
    "six": 6,
    "sev": 7,
    "egt": 8,
    "nin": 9,
    "ten": 10,
    "elv": 10.95,
    "twl": 12,
    "frtn": 14.4,
    "svtn": 17.28,
    "twty": 20.74,
    "twfv": 24.88,
    "five": 5,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "eleven": 10.95,
    "twelve": 12,
}
#: 族尾 → CM/AMS 字体 base (10pt 设计尺寸恒在，``at <sz>pt`` 兜底)。
_AMS_FONT_FAM: dict[str, str] = {
    "mi": "cmmi",
    "i": "cmmi",
    "mib": "cmmib",
    "sy": "cmsy",
    "bsy": "cmbsy",
    "ex": "cmex",
    "bf": "cmbx",
    "rm": "cmr",
    "it": "cmti",
    "sl": "cmsl",
    "tt": "cmtt",
    "sc": "cmcsc",
    "ss": "cmss",
    "msa": "msam",
    "msb": "msbm",
    "euf": "eufm",
    "eub": "eufb",
    "eur": "eurm",
    "eus": "eusm",
}
#: log 内 undefined_cs 报错行 → l.N 顶行末 cs (出错点 cs) 提取 —
#: taxonomy ``Undefined control sequence`` payload 同口径。
_UNDEF_CS_LINE_RE = re.compile(
    r"Undefined control sequence[^\n]*\n[^\n]*\\([a-zA-Z@]+)[^\\\n]*(?:\n|$)"
)
#: 源内字体位使用点 —— ``\\skewchar\\X`` / ``\\textfont\\d=\\X`` /
#: ``\\font\\X=``。dead-block ``\\font`` 定义 (``\\doit{0}`` 宏参) 不在
#: 遮盖面 —— 正合此修需求 (定义不执行才需 shim)。
_FONT_POS_RE = re.compile(
    r"\\(?:skewchar|(?:scriptscript|script|text)?font)"
    r"\s*(?:\d+\s*=\s*)?\\([A-Za-z@]+)"
)
#: 非 ``\\font`` 的定义证据 —— 命中的 ``<size><fam>`` 名若另有 \\def/\\let
#: 系定义则是真宏撞名 (font shim 抢名会把它毁掉), 不接管。
_NONFONT_DEF_RE = re.compile(
    r"\\(?:[egx]?def|let|newcommand|renewcommand|providecommand|"
    r"DeclareRobustCommand|newif|newcount|newbox|newdimen|newskip|"
    r"newmuskip|newtoks|newlength|newsavebox|newread|newwrite)"
    r"\s*\*?\s*\{?\s*\\([A-Za-z@]+)"
)


def _ams_font_rhs(
    eng: Engine | None, m: re.Match[str], sizes: dict[str, float], fams: dict[str, str]
) -> str:
    r"""``fivmi`` 匹配 → ``cmmi5`` / ``elvrm`` → ``cmr10 at 10.95pt``。

    eng 在且整数设计尺寸的 ``<base><size>.tfm`` 可探 → 设计尺寸绑定
    (字重/侧衬最优); 否则 ``<base>10 at <size>pt`` —— base10 全族恒在。
    """
    size, base = sizes[m.group(1)], fams[m.group(2)]
    if (
        eng is not None
        and size == int(size)
        and eng.probe_file(f"{base}{int(size)}.tfm")
    ):
        return f"{base}{int(size)}"
    return f"{base}10 at {size:g}pt"


def font_cs_shim(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""AMS 上古字体 cs 缺定义 → ``\\font\\<cs>=<cm 等价>`` 注入。

    窄谓词: payload ∈ ``<size><fam>`` 模式。收集面 = log undefined_cs 撞名
    (l.N 顶行末 cs) ∩ 模式 ∪ 源内字体位 (``\\skewchar``/``\\textfont``/
    ``\\font``) 现身且无 ``\\def`` 系定义证据者 —— 一次性整批, 免 83 错
    逐名烧轮。注入点在 docclass 后: 稿内后到的活 ``\\font``/``\\def``
    定义仍覆盖我们的早期绑定 (先绑定后定义赢序), 只对真缺定义位生效。
    ``params.sizes``/``params.fams`` 可扩映射表。
    """
    cs = (payload or "").lstrip("\\")
    sizes = dict(_AMS_FONT_SIZE)
    fams = dict(_AMS_FONT_FAM)
    for k, v in (params.get("sizes") or {}).items():
        sizes[str(k)] = float(v)
    for k, v in (params.get("fams") or {}).items():
        fams[str(k)] = str(v)
    pat = re.compile(r"(" + "|".join(sizes) + r")(" + "|".join(fams) + r")\Z")
    if not pat.fullmatch(cs):
        return False, f"{payload} not an AMS-era font name"
    log = _fixloop_log(ctx)
    undef = {n for n in _UNDEF_CS_LINE_RE.findall(log) if pat.fullmatch(n)}
    blob_masked = mask_tex(ctx.source_blob())
    defined_elsewhere = set(_NONFONT_DEF_RE.findall(blob_masked))
    pos_used = {
        m.group(1)
        for m in _FONT_POS_RE.finditer(blob_masked)
        if pat.fullmatch(m.group(1))
    }
    cands = sorted(undef | {c for c in pos_used if c not in defined_elsewhere})
    if not cands:
        return False, "no AMS font cs to shim"
    main = ctx.main_path()
    main_t = (ctx.read(main) or "") if main is not None else ""
    # 文本上已有 \font\<cs>= 的 (活定义/死块定义/上轮 shim) 且本轮未报错
    # → 跳过; 在报错集里的无条件重注 (可见 \font 定义必为死定义)。
    fresh = [
        c
        for c in cands
        if c in undef or not re.search(rf"\\font\s*\\{c}\b\s*=", main_t)
    ]
    if not fresh:
        return False, "AMS font cs already shimmed"
    lines = ["% fixloop: AMS-era font cs -> CM equivalents"]
    lines += [
        rf"\font\{c}={_ams_font_rhs(eng, m, sizes, fams)}"
        for c in fresh
        if (m := pat.fullmatch(c)) is not None
    ]
    if not _inject_after_docclass(ctx, "\n".join(lines)):
        return False, "font shim block already present"
    return True, f"font-cs shim: {', '.join(fresh)}"


# ═══ missing_char 第三子路：produced-by-cs 缺字 → cs 重绑回退字体 ═══


def _producer_map(params: dict[str, Any]) -> dict[int, str]:
    r"""码位 → 产出 cs 名: ``_MATH_SHIM_CS`` 反转 ∪ char_table ``produced_by`` ∪ ``params.producers`` hex 键。"""
    producers = {cp: cs for cs, cp in _MATH_SHIM_CS.items()}
    for e in _mc_table(params).values():
        if pb := e.get("produced_by"):
            for cp in e.get("cps") or ():
                producers[int(cp)] = str(pb).lstrip("\\")
    for k, v in (params.get("producers") or {}).items():
        producers[int(str(k), 16)] = str(v).lstrip("\\")
    return producers


def cs_rebind(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""TFM 字体下 ``\\S``/``\\o`` 等 cs 产出字符缺字 → ``\\protected\\def`` 绑回退字体。

    ``\\S``→§ 在 cmr10 下字面缺字 (2403.15096, 31 处 ``\\S`` 无一个字面 §):
    literal-replace 够不到 cs 产出面, ``\\newunicodechar`` 只管字面输入 ——
    missing_char_fix(25)/font_fallback(26) 都治不了, 缺第三子路。
    窄谓词 (全部成立才动):
      - 码位 ∈ 产出表 (``_MATH_SHIM_CS`` 反转 ∪ char_table ``produced_by``
        键 ∪ ``params.producers`` ``{"A7": "S"}`` hex 键);
      - 字面字符 *不* 在遮盖源 (在则 literal 面先修);
      - ``\\<cs>`` 在遮盖源现身 (cs 确为该缺字的生产者)。
    ``\\protected`` 保 moving-arg 安全 (physics/9901057 ``\\markboth{...\\o...}``
    实证); ``\\ifmmode\\mbox`` 分支数学/文本双域兼容。回退族名
    ``params.fallback_cs`` (缺省 txlatefallback) 与 font_fallback 共享
    ``\\ifdefined`` 守卫面 —— 先后注入不互踩 ``\\newfontfamily``。
    def 裹 ``\\AtBeginDocument`` 迟延: ctex+hyperref 宿主下 hyperref 在
    ``begindocument/before`` 重声明 text-cs 族, 回卷 preamble 即时
    ``\\protected\\def`` (1404.0332 ``\\i`` 垫在仍缺实证) —— top-level 钩
    排在重声明后, 迟延绑定存活。
    """
    del eng, payload
    seen = _mc_seen(ctx)
    if seen is None:
        return False, "no Missing character in compile log"
    if not seen:
        return False, "Missing character lines but no codepoint parsed"
    producers = _producer_map(params)
    blob = mask_tex(ctx.source_blob())
    todo = [
        (cp, cs)
        for cp in sorted(seen)
        if (ch := _mc_chr(cp)) is not None
        and (cs := producers.get(cp)) is not None
        and ch not in blob
        and re.search(rf"\\{cs}(?![a-zA-Z@])", blob)
    ]
    if not todo:
        return False, "no produced-by-cs missing chars"
    main = ctx.main_path()
    main_masked = mask_tex(ctx.read(main) or "") if main is not None else ""
    fresh = [
        (cp, cs)
        for cp, cs in todo
        if not re.search(rf"\\protected\\def\\{cs}(?![a-zA-Z@])", main_masked)
    ]
    if not fresh:
        return False, "producer cs already rebound"
    font = str(params.get("fallback_font") or _FB_FONT)
    fam = str(params.get("fallback_cs") or "txlatefallback")
    lines = [
        "% fixloop: cs-rebind — missing chars produced by cs under TFM fonts",
        *_fb_preamble_lines(fam, font),
    ]
    for cp, cs in fresh:
        ch = cast("str", _mc_chr(cp))  # fresh ⊆ todo——上游已滤 ch is not None
        lines.append(
            rf"\AtBeginDocument{{\protected\def\{cs}{{{_fb_font_body(fam, ch)}}}}}"
        )
    if not _inject_after_docclass(ctx, "\n".join(lines)):
        return False, "cs-rebind block already present"
    names = ", ".join(f"\\{cs}->U+{cp:04X}" for cp, cs in fresh)
    return True, f"cs rebind: {names}"


# ════════════════════════════════════════════════════════════════
# bm 族宏 atom-walk 撞 XeTeX 15-bit mathchar 扫描墙 (failmine3 census)
# ════════════════════════════════════════════════════════════════

#: bm 族守卫式重定义注入块 —— bm.sty ``\bm@test@token`` 对实参内每个
#: catcode-11/12 token 做 ``\count@\mathcode`#1`` 原子遍历; XeTeX 的
#: ``\mathcode`` 旧式操作数扫描对 >0xFF 字符 (xeCJK CJK 字/扩展 mathcode)
#: 必炸 "Extended mathchar used as mathchar" (hep-ph/0605174 GLUON.tex:464
#: 四值循环 83922905=0x05008FD9=这 / 83912239=是 / 83921873=译 /
#: 83912071=文; mathchar 探针实证 ``\count@=\mathcode` 这`` 文本
#: 态同炸、``\the\mathcode`` 读取不炸; t1-t6 实证裸 ``$这$``/``{\rm 这}``/
#: ``\tilde``/上下标全不炸 —— 修复面只锁 ``\bm`` 族)。
#: ``\bm#1 → \TeXlateBM{{#1}}`` 双花括号把实参改走 bm 自带 ``\bm@gr@@p``→
#: ``\boldmath`` 组路径 (遍历被跳过且粗体语义保留; fix3/fix4 全形零错)。
#: ``\b``/``\unit`` 等 ``\newcommand`` 别名调用点重展开 ``\bm`` 自动受益;
#: ``\boldsymbol``/``\heavysymbol`` 是 bm.sty 末行 ``\let`` 别名，
#: ``\ifx`` 等义复核后才重绑新 ``\bm``/``\hm`` (amsbsy 自带 ``\boldsymbol``
#: 非 bm 别名不误伤)。``\ifdefined\TeXlateBM`` 幂等防自捕环 (若 ``\let``
#: 重捕到新 ``\bm``, ``\TeXlateBM{{#1}}`` 无穷递归)。
_BM_MATHCHAR_WRAP = (
    "% fixloop: bm-family atom-walk reads \\mathcode of every char token —\n"
    "% XeTeX 15-bit mathchar scan rejects >0xFF chars (CJK/extended mathcodes).\n"
    "% Re-route the argument through bm's own group path (\\bm@group->\\boldmath).\n"
    "\\ifdefined\\bm\n"
    "  \\ifdefined\\TeXlateBM\\else\n"
    "    \\let\\TeXlateBM\\bm\n"
    "    \\protected\\def\\bm#1{\\TeXlateBM{{#1}}}\n"
    "    \\ifx\\boldsymbol\\TeXlateBM\\let\\boldsymbol\\bm\\fi\n"
    "  \\fi\n"
    "\\fi\n"
    "\\ifdefined\\hm\n"
    "  \\ifdefined\\TeXlateHM\\else\n"
    "    \\let\\TeXlateHM\\hm\n"
    "    \\protected\\def\\hm#1{\\TeXlateHM{{#1}}}\n"
    "    \\ifx\\heavysymbol\\TeXlateHM\\let\\heavysymbol\\hm\\fi\n"
    "  \\fi\n"
    "\\fi"
)

#: bm 族在用量粗探 —— ``\bm``/``\hm``/``\boldsymbol``/``\heavysymbol`` 字面。
#: ``\b``/``\unit`` 等 ``\newcommand`` 别名定义体内含 ``\bm`` 字面同中;
#: ``\let``-别名调用点不含字面但本修也够不到 (旧 ``\bm`` 快照不走新定义)。
_BM_FAMILY_USE_RE = re.compile(r"\\(?:bm|hm|boldsymbol|heavysymbol)(?![a-zA-Z@])")


def bm_mathchar_wrap(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``\bm{<CJK>}`` 撞 Extended mathchar 墙 → 序言守卫式 ``\bm`` 族重定义。

    实证根因 (failmine3 census ~6 格, hep-ph/0605174 + 1206.0485 +
    2112.00003 全 ``\usepackage{bm}``): bm.sty 原子遍历对实参内 catcode-11
    token 逐个 ``\count@\mathcode`#1`` —— >0xFF 字符在 XeTeX legacy
    mathchar 扫描位必炸 (probe5.tex 实证 ``\mathcode`Ω``=31458217 同炸,
    非 CJK 专属)。``\bm{arg} → \bm{{arg}}`` 双花括号改走 bm 自带组路径
    (``\bm@group`` 分支 ``\bm@mchoice``→``\boldmath`` 直排不遍历, 粗体经
    math version 照常生效)。

    注入点 ``_inject_before_begindoc``: 全部 ``\usepackage``/cls 装载已毕,
    ``\ifdefined\bm``/``\ifdefined\hm`` 守卫对未用 bm.sty 的稿纯空转;
    ``\b``/``\unit`` 宏别名运行时重展开 ``\bm`` 同愈。遮盖源无 bm 族字面
    → False (别名缺口见 ``_BM_FAMILY_USE_RE`` 注); ``snippet in t`` +
    ``\ifdefined\TeXlateBM`` 双幂等。
    """
    del eng, payload, params
    if not _BM_FAMILY_USE_RE.search(mask_tex(ctx.source_blob())):
        return False, "no bm-family macro use in source"
    if not _inject_before_begindoc(
        ctx, _BM_MATHCHAR_WRAP, strict_first=True, fallback=_inject_after_docclass
    ):
        return False, "bm wrap block already present"
    return True, "bm-family group-wrap polyfill injected"
