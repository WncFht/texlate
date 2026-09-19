r"""_builtins_common — fixloop builtins 跨域共享原语 (C3 builtins.py 拆分叶子)。

跨域 helper 单源: ``mask_tex`` 遮盖视图匹配 / 逐 tex 文件映射 / ``\\usepackage``
剥载 / ``\\documentclass`` 缝后注入 / pdfTeX 原语清单 (engine._FAMILY_TOKENS
与 pdftex_prim_polyfill 双侧消费)。只做 helper/常量, 不含注册表条目本体。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from texlate.compile.inject import find_docclass_ends
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from texlate.compile.fixloop.engine import LoopCtx

# pdfTeX 原语清单 (spike L284-298 + 2410.00012 实证扩: 文档面对象/注释/资源族)
PDFTEX_PRIMS = (
    "pdfoutput",
    "pdfminorversion",
    "pdfoptionpdfminorversion",  # axessibility.sty:350 实证 (旧拼形整参)
    "pdfcompresslevel",
    "pdfobjcompresslevel",  # 同族整参 (老包常与 pdfcompresslevel 连写)
    "pdfinfo",
    "pdfpagewidth",
    "pdfpageheight",
    "pdfhorigin",
    "pdfvorigin",
    "pdfsuppressptexinfo",
    "pdftrailer",
    "pdfpxdimen",
    "pdflastxpos",
    "pdflastypos",
    # 对象/表单/图像
    "pdfobj",
    "pdflastobj",
    "pdfrefobj",
    "pdfxform",
    "pdflastxform",
    "pdfrefxform",
    "pdfximage",
    "pdflastximage",
    "pdfrefximage",
    # 注释/链接/书签
    "pdfannot",
    "pdflastannot",
    "pdfdest",
    "pdflink",
    "pdfstartlink",
    "pdfendlink",
    "pdfoutline",
    "pdfcatalog",
    "pdfnames",
    # 文字流/页面资源
    "pdfliteral",
    "pdfcolorstack",
    "pdfcolorstackinit",
    "pdfsavepos",
    "pdfpageref",
    "pdfpageattr",
    "pdfpagesattr",
    "pdfpageresources",
    "pdfdraftmode",
    # 读取/工具原语
    "pdfescapestring",
    "pdfescapename",
    "pdfescapehex",
    "pdfunescapehex",
    "pdffilesize",
    "pdffilemoddate",
    "pdffiledump",
    "pdfmdfivesum",
    "pdfelapsedtime",
    "pdfresettimer",
    "pdfuniformdeviate",
    "pdfnormaldeviate",
    "pdfrandomseed",
    "pdfmatch",
    "pdflastmatch",
    "pdfstrcmp",
    "pdfprimitive",
    "pdfifprimitive",
    "pdfcreationdate",
    # 字体/微排/映射
    "pdffontname",
    "pdffontobjnum",
    "pdffontsize",
    "pdfincludechars",
    "pdfmapfile",
    "pdfmapline",
    "pdfglyphtounicode",
    "pdfgentounicode",
    "pdfadjustspacing",
    "pdfprotrudechars",
    "pdftracingfonts",
    "pdfdecimaldigits",
    "pdftexversion",
    "pdftexrevision",
    "pdfinclusionerrorlevel",
    "pdfinclusioncopyfonts",  # 2403.15085: 稿面 \prim=1 写形, guard 包裹位
    "pdfsuppresswarningpagegroup",
    # `pdf@` 包内别名族 (breakurl/pdfmark.def/pdftexcmds 系包体在 pdftex
    # 下自导原语绑定, xelatex 下全族裸缺) —— @-名只能存在于 @=11 包体
    # 语境, pdftex_prim|<@名> 报错定义上即包内宏展开帧 (file_stack 归
    # doc 侧, err_outside_fileset 不见), 主文件头补定义是唯一治法。
    "pdf@box",  # breakurl.sty \sbox\pdf@box scratch box (2502.03387 colm)
    "pdf@toks",
    "pdf@defaulttoks",
    "pdf@draftmode",
    "pdf@inclusionerrorlevel",
    "pdf@lastxpos",
    "pdf@lastypos",
    "pdf@lastxform",
    "pdf@lastximage",
    "pdf@addtoks",
    "pdf@addtoksx",
    "pdf@docset",
    "pdf@linktype",
    "pdf@majorminor",
    "pdf@objdef",
    "pdf@rect",
    "pdf@type",
    "pdf@xform",
    "pdf@refxform",
    "pdf@ximage",
    "pdf@refximage",
    "pdf@escapestring",
    "pdf@escapename",
    "pdf@escapehex",
    "pdf@unescapehex",
    "pdf@filemoddate",
    "pdf@filedump",
    "pdf@filesize",
    "pdf@mdfivesum",
    "pdf@pageref",
    "pdf@lastmatch",
    "pdf@strcmp",
    "pdf@match",
    "pdf@ifdraftmode",
)


_USE_RE = re.compile(
    r"^(\s*)\\(usepackage|RequirePackage)\s*(\[([^\]]*)\])?\s*\{([^}]*)\}",
    re.MULTILINE,
)


# ════════════════════════════════════════════════════════════════
# catcode-agnostic 注入形 (spacefactor lane, 2026-09-19)
# ════════════════════════════════════════════════════════════════

#: 永不定义的纯字母 cs —— ``\let\X\TeXlateUndefCs`` 的右操作数。
#: ``\csname @undefined\endcsname`` 会把 ``\@undefined`` 冻结成 ``\relax``
#: (csname 未定义名副作用), 产 ``\relax`` 值而非真 undefined ——
#: ``\ifcsname``/expl3 ``\cs_if_exist`` 存在性检查下仍算 defined
#: (freeze_test 实证)。纯字母名任何宿主 @ catcode 下成 token, 且不冻名。
_UNDEF_MARK = "TeXlateUndefCs"


def _let_cs(target: str, source: str) -> str:
    r"""``\let\<target>\<source>`` 的 catcode-agnostic 形 (两侧均可含 ``@``)。

    ``\csname`` 侧壳使 @ 名在任意宿主 catcode 下成 token —— 裸
    ``\makeatletter``/``\makeatother`` 对的尾段会把 @=letter 宿主尾段
    强翻回 12 (1803.02902 csfix 清位串实证), def 体内字面 ``\@`` 亦
    无法重读 (@=12 下已成 ``\@``+裸字母 → spacefactor 签); csname 形
    两语境皆免 catcode。
    """
    return (
        rf"\expandafter\let\csname {target}\expandafter\endcsname"
        rf"\csname {source}\endcsname"
    )


def _undefine_cs(name: str) -> str:
    r"""``\let\<name>\@undefined`` 的 catcode-agnostic 形 → 清位串。

    右操作数用 ``_UNDEF_MARK`` (永不定义纯字母名): 产**真** undefined,
    ``\ifdefined``/``\cs_if_exist``/``\@ifdefinable`` 三代检查通吃;
    ``\csname @undefined\endcsname`` 形只得 ``\relax`` 值, 存在性检查
    下破防 (ctlseq_undefine 的 ``\cs_new`` 撞名格实证需求)。
    """
    return rf"\expandafter\let\csname {name}\endcsname\{_UNDEF_MARK}"


#: 多 @-cs 注入块的宿主不可知 @=11 包裹对 (svglov3.clo exact-restore
#: idiom, 同 _builtins_pkgload._SHIP_WRAP_*): ``\edef`` 存 ``\catcode 64``
#: 现值 → ``=11`` 读块 → 复元; @=letter 宿主恒等变换, @=other 亦回原位。
#: restore cs 名纯字母 —— 宿主正处 @=other 时名里带 ``@`` 自断签名。
_AT_LETTER_PRE = (
    r"\edef\TeXlateAtRestore{\catcode 64=\the\catcode 64\relax}"
    r"\catcode 64=11\relax "
)
_AT_LETTER_POST = r" \TeXlateAtRestore"


# ════════════════════════════════════════════════════════════════
# 注入件指纹 (b3a 工单: 无版本/hash 闸, 留存旧 stub 无辨——
# hep-ph/0408075 espcrc2 跨 rerun 实证)
# ════════════════════════════════════════════════════════════════

#: 注入件指纹行——本引擎写出的 stub/shim 件携 sha1(body) 指纹; 盘上同名
#: 片三分判: 指纹匹配=本代已注入(跳), 失配/旧代标记=旧注入件(覆写刷新),
#: 全无名分=外来件(稿自带/真包——不覆写, advisory)。
_FINGERPRINT_RE = re.compile(
    r"^% texlate-fixloop-injected: ([0-9a-f]{12})$", re.MULTILINE
)
#: 旧代注入件的行头标记（指纹闸引入前所写 stub 的认亲面）。
_LEGACY_INJECTED_HEADS = ("% texlate vendored stub", "% fixloop:")


def _fingerprint(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:12]


def _mark_injected(body: str) -> str:
    return f"% texlate-fixloop-injected: {_fingerprint(body)}\n{body}"


def _injected_state(target: Path, body: str) -> str:
    """同名片四分判: ``absent``/``current``/``stale``/``foreign``。"""
    try:
        old = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "absent"
    m = _FINGERPRINT_RE.search(old)
    if m is None:
        head = old.lstrip()[:200]
        if head.startswith(_LEGACY_INJECTED_HEADS):
            return "stale"
        return "foreign"
    return "current" if m.group(1) == _fingerprint(body) else "stale"


def _inject_write(
    ctx: LoopCtx, target: Path, body: str, name: str
) -> tuple[tuple[bool, str] | None, str]:
    r"""同名片指纹闸 + 带指纹写盘 (``ctx.write`` 同步读缓存)。

    短路终局 ``((bool, note), state)`` 直冒泡：``foreign`` → 记 advisory +
    False (稿自带/真包件永不覆写)；``current`` → True 免重写；OSError →
    False。``absent``/``stale`` 写完返 ``(None, state)``——调用方据 state
    拼成功 note (``stale`` 供 "refreshed" 措辞位)。
    """
    state = _injected_state(target, body)
    if state == "foreign":
        adv = f"{name}: foreign file present, inject skipped"
        if adv not in ctx.advisories:
            ctx.advisories.append(adv)
        return (False, f"{name} present (foreign) — inject skipped"), state
    if state == "current":
        return (True, f"{name} already current"), state
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        ctx.write(target, _mark_injected(body))
    except OSError as e:
        return (False, f"{name} write failed: {e}"), state
    return None, state


def _resolve_site(ctx: LoopCtx, rel: PurePosixPath) -> Path | None:
    """落点 = kpathsea 解析位 ``main_dir/<rel>``; main 未知退 wdir 根。

    编译 cwd = ``main_path().parent`` 且无 TEXINPUTS 根注入 —— 平铺
    wdir 根对嵌套 main (``templates/arxiv/main.tex``) 不可见
    (2609.19664 fired-unfixed 实证); fileset_relocate 同口径。
    ``main_rel`` 怪径致目标逃出 wdir → None。
    """
    mp = ctx.main_path()
    dst = (mp.parent if mp is not None else ctx.wdir) / Path(*rel.parts)
    try:
        dst.resolve().relative_to(ctx.wdir.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return dst


def _live_matches(rx: re.Pattern[str], t: str) -> list[re.Match[str]]:
    r"""遮盖视图命中且匹配体完整未遮——``%`` 注释/verbatim 内假装载点不算。

    mask_tex 等长遮盖 → match 位置/group 对原文有效；跨遮盖区的命中
    （注释内 ``\documentclass``、comment 环境）span 与原文不一致，跳过。
    2211.04482 记档同族：锚正则把 ``%\documentclass`` 当活缝。
    """
    masked = mask_tex(t)
    return [
        m
        for m in rx.finditer(masked)
        if masked[m.start() : m.end()] == t[m.start() : m.end()]
    ]


def _map_tex_files(
    ctx: LoopCtx, exts: tuple[str, ...], fn: Callable[[str], tuple[str, int]]
) -> int:
    """逐 tex 文件应用 ``fn(t) -> (nt, n)``, n>0 且文本有变则写回 → 改动文件数。"""
    n_files = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt, n = fn(t)
        if n and nt != t:
            ctx.write(f, nt)
            n_files += 1
    return n_files


def _drop_pkg_loads(t: str, pkg: str) -> tuple[str, int]:
    r"""剥 ``\usepackage``/``\RequirePackage`` 对 pkg 的装载 → (新文本, 摘除数)。

    独载: 行首锚 (前缀全空白) → 整行注释; 行内嵌入 → 置空
    (注释替换会误吃同行尾 token)。列表成员: 外科摘除元素保留其余。
    """
    pat = re.compile(
        rf"\\(usepackage|RequirePackage)(\s*\[[^\]\n]*\])?\s*\{{([^}}]*)\b{re.escape(pkg)}\b([^}}]*)\}}"
    )
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        pkgs = [p.strip() for p in (m.group(3) + "," + m.group(4)).split(",")]
        keep = [p for p in pkgs if p and p != pkg]
        n += 1
        if keep:
            return f"\\{m.group(1)}{m.group(2) or ''}{{{','.join(keep)}}}"
        ls = m.string.rfind("\n", 0, m.start()) + 1
        if m.string[ls : m.start()].strip():
            return ""
        return "% fixloop: stripped " + m.group(0).strip()

    return pat.sub(_sub, t), n


def _inject_after_docclass(ctx: LoopCtx, snippet: str) -> bool:
    r"""主文件每个 ``\documentclass`` 缝后注入 snippet（幂等）。

    复用 inject.find_docclass_ends：分支选择形态（``\ifpdf A \else B \fi``
    双 docclass）逐缝注入——静态不判死活，活臂生效死臂随分支跳过；
    宏体/depth>0 命中与注释命中天然排除，跨行 ``[opt]{cls}``（revtex
    五选一注释穿插）落在配对 ``}`` 行尾而非首行尾。无 docclass 行则
    退文件头（``\AtBeginDocument`` 类 snippet 前定义也合法）。

    缝位是行尾换行**之后** (eol+1)——docclass 行尾的 ``%`` 注释
    (``%!TEX program`` 类编辑器 pragma 常见) 会把行内注入整段吞成
    死文本 (1404.0346 实证: applied=True 但 snippet 在注释里)。
    """
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None or snippet in t:
        return False
    hits = find_docclass_ends(t)
    if not hits:
        ctx.write(main, snippet + "\n" + t)
        return True
    out, delta = t, 0
    for pos, _ln, _cmd in hits:
        at = pos + delta
        if at < len(out) and out[at] == "\n":
            at += 1
            piece = snippet + "\n"
        else:  # docclass 是末行且无尾换行 —— 先补换行再落 snippet
            piece = "\n" + snippet + "\n"
        out = out[:at] + piece + out[at:]
        delta += len(piece)
    ctx.write(main, out)
    return True


# ════════════════════════════════════════════════════════════════
# 编译 log 定位 (C3 收尾归位: csfix/bib/shim 三叶共用的通用版)
# ════════════════════════════════════════════════════════════════


def _fixloop_log(ctx: LoopCtx) -> str:
    """本轮编译 log 定位 (通用版, 无内容过滤)。

    ``{stem}.log`` (xelatex) → ``_tect_out/{stem}.log`` (tectonic)
    → 兜底首个非空 ``*.log``。misschar 域的 ``_compile_log_text`` 有
    Missing character 内容门, 非缺字扫描不可复用。
    """
    main = ctx.main_path()
    if main is not None:
        stem = main.stem
        for p in (
            ctx.wdir / f"{stem}.log",
            ctx.wdir / "_tect_out" / f"{stem}.log",
        ):
            if p.is_file() and (t := ctx.read(p)):
                return t
    for p in sorted(ctx.wdir.rglob("*.log")):
        if t := ctx.read(p):
            return t
    return ""


# ════════════════════════════════════════════════════════════════
# missing_char 读侧/规划侧机制 (C3 收尾归位: shim 叶同消费)
# 「Missing character」行解析 → 码位 → 表匹配 → 修复规划;
# 修复动作本体 (warmup/字面替换/逐字回退/accent 站点) 留在
# _builtins_misschar。
# ════════════════════════════════════════════════════════════════

#: ``Missing character: There is no <what> (U+XXXX)? in font <font>``
#: xetex/tectonic spec 字体带 ``(U+XXXX)``; tfm 字体带 ``("XXXX)`` 十六进制
#: (``("8FD9)`` = U+8FD9「这」, 码位仍是 Unicode); pdftex 8-bit 给裸字符或
#: ``^^xx`` 记法。
_MISSING_CHAR_RE = re.compile(
    r"Missing character:\s*There is no (?P<what>.+?)"
    r"(?:\s*\((?P<cp>U\+[0-9A-Fa-f]+|\"[0-9A-Fa-f]+)\))?\s*in font\s+(?P<font>[^\s!;]+)"
)

#: ``^^xx``/``^^^xxxx`` TeX 记法码位提取。
_CARET_HEX_RE = re.compile(r"\^{2,3}([0-9a-fA-F]{2,4})")

#: 判定「字体本身即 CJK 字体」的排除模式 —— CJK 码位落在 CJK 字体里
#: 是真缺字形 (换字体的 warmup 救不了), 不属于绑定污染类。
_CJK_FONT_RE = re.compile(
    r"fandol|noto.*cjk|source.?han|uming|ukai|wqy|ipa(?:ex)?[mg]|"
    r"sim(?:sun|hei|kai|fang)|ms ?(?:gothic|mincho)|cjk",
    re.IGNORECASE,
)


def _mc_codepoint(what: str, cp: str | None) -> int | None:
    """``(U+XXXX)`` / ``("XXXX)`` / ``^^xx`` / 裸字符 → 码位; 不可判定 → None。"""
    if cp:
        return int(cp[2:] if cp.startswith("U+") else cp[1:], 16)
    if m := _CARET_HEX_RE.fullmatch(what.strip()):
        return int(m.group(1), 16)
    if len(what) == 1:
        return ord(what)
    return None


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
        # 全局绑到 lmroman —— /tmp/mc-repro 实证), 预热即可。
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


def _mc_parse_log(log: str) -> dict[int, tuple[str, str]]:
    """``Missing character`` 行 → {码位: (原字面, 字体名)} 去重; nullfont 滤除。"""
    seen: dict[int, tuple[str, str]] = {}
    for m in _MISSING_CHAR_RE.finditer(log):
        font = m.group("font").rstrip(".,;")
        if font == "nullfont":
            # 测量盒/\write 上下文的缺字按设计不可印 (scout-misschar ×5)——
            # 签名侧经 rules/ missing_char pattern 排除, 这里兜底 wrap 漏网。
            continue
        cp = _mc_codepoint(m.group("what"), m.group("cp"))
        if cp is not None and cp not in seen:
            seen[cp] = (m.group("what"), font)
    return seen


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
