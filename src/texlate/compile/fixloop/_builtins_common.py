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

from texlate.compile._seams import find_docclass_ends
from texlate.texlog import _mc_parse_log
from texlate.textutil import BEGIN_DOC_RX, iter_depth0, mask_tex, safe_is_file

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from typing import Any

    from texlate.compile.fixloop.engine import Engine, LoopCtx

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


# ════════════════════════════════════════════════════════════════
# ``\usepackage``/``\RequirePackage`` 装载命令骨架 (命名组单源,
# 自 _builtins_pkgload 归位 —— 旧拼在同骨架上组位逐处漂移,
# names 位 g5/g3/g2 不等; 命名组替数字位收口)
# ════════════════════════════════════════════════════════════════

#: 装载命令规范骨架 (命名组): ``head``=名单外全部前缀, ``cmd``=命令名,
#: ``opts``=整 ``[..]`` 段 (含括号), ``opts_inner``=选项本体,
#: ``names``=花括号名单。opts 字符集 ``[^\]]`` 允跨行 —— TeX 选项表
#: 换行合法 (旧 ``[^\]\n]`` 各拼形的严格超集)。
_PKG_LOAD_HEAD_SRC = (
    r"(?P<head>\\(?P<cmd>usepackage|RequirePackage)\s*"
    r"(?P<opts>\[(?P<opts_inner>[^\]]*)\])?\s*)"
)
_PKG_LOAD_SRC = _PKG_LOAD_HEAD_SRC + r"\{(?P<names>[^}]*)\}"
_PKG_LOAD_RE = re.compile(_PKG_LOAD_SRC)


def _pkg_list_re(pkg: str) -> re.Pattern[str]:
    r"""名单内含 ``pkg`` 的装载点变体 —— ``names`` 拆 ``before``/``after`` 双组。

    ``\b<pkg>\b`` 界只挡字母续名 (``{physics-tools}`` 这类连字符兄弟名
    的误中由调用方元素级判定滤掉)。``_builtins_pkgload._PHYS_LOAD_RE``
    等同形名单变体的单源。
    """
    return re.compile(
        _PKG_LOAD_HEAD_SRC
        + rf"\{{(?P<before>[^}}]*)\b{re.escape(pkg)}\b(?P<after>[^}}]*)\}}"
    )


#: ``_PKG_LOAD_SRC`` + ``^(\s*)`` 行首锚变体 —— 锚必须留:
#: option_clash_merge 靠它防行内装载点误并 (``\if..\RequirePackage``
#: 同行形态不收)。组面 = 命名组 (head/cmd/opts/opts_inner/names) +
#: 组1 行首空白。
_USE_RE = re.compile(rf"^(\s*){_PKG_LOAD_SRC}", re.MULTILINE)


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


def _exact_restore_wrap(cs: str) -> tuple[str, str]:
    r"""exact-restore @=11 包裹对的裸段 → ``(pre_seg, post_seg)``。

    ``pre_seg`` = ``\edef\<cs>{\catcode 64=\the\catcode 64\relax}\catcode 64=11\relax``
    (``\edef`` 存 ``\catcode 64`` 现值 → ``=11`` 读本族 @-cs), ``post_seg``
    = ``\<cs>`` (复元恒回原位)。分隔符 (空格/换行) 归属调用方拼 —
    ``_SHIP_WRAP_*``/``_AT_LETTER_*`` 尾空/头空, ``_SIU_PEACE_*`` 换行。
    (自 _builtins_pkgload 归位 —— 两侧包裹对字面量单源。)

    隐式耦合: 传入 ``cs`` 必须已登记进 ambient-@ 事件表的 restore 交替
    组 (pkgload ``_AMBIENT_AT_RE``/docfix ``_ATDEF_EVENT_RE`` 均
    ``TeXlate(?:At|StyIn)Restore``) —— 否则组作用域走查的 at_letter
    跟踪把该 cs 当普通字符消费, ``\catcode 64=11`` 事件配平丢失致状态
    误记。
    """
    return (
        rf"\edef\{cs}{{\catcode 64=\the\catcode 64\relax}}\catcode 64=11\relax",
        rf"\{cs}",
    )


#: 多 @-cs 注入块的宿主不可知 @=11 包裹对 (svglov3.clo exact-restore
#: idiom, 同 _builtins_pkgload._SHIP_WRAP_*): ``\edef`` 存 ``\catcode 64``
#: 现值 → ``=11`` 读块 → 复元; @=letter 宿主恒等变换, @=other 亦回原位。
#: restore cs 名纯字母 —— 宿主正处 @=other 时名里带 ``@`` 自断签名。
_AT_LETTER_SEG = _exact_restore_wrap("TeXlateAtRestore")
_AT_LETTER_PRE = _AT_LETTER_SEG[0] + " "
_AT_LETTER_POST = " " + _AT_LETTER_SEG[1]


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
        _advise(ctx, f"{name}: foreign file present, inject skipped")
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


def _is_live(m: re.Match[str], masked: str, t: str) -> bool:
    r"""遮盖视图命中体的原文保真判 —— 跨遮盖区 (注释/verbatim 死臂) 命中为假。

    ``_live_matches`` 的逐命中谓词形: 非 ``finditer`` 枚举源
    (``iter_depth0`` 等自带过滤的迭代器) 逐枚复核用。
    """
    return masked[m.start() : m.end()] == t[m.start() : m.end()]


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


def _splice(t: str, edits: list[tuple[int, int, str]]) -> str:
    r"""(start, end, rep) 编辑表 → 排序回放拼接 (站点改写通用骨架)。

    各 ``_*_fix_text``/站点改写器只产编辑表, 回放语义单源 —— 与
    ``compile/mask.py`` ``apply_edits`` 不同: 纯拼接, 不补 ``\\n`` 保行号。
    csfix 叶 prepend 形 = 零宽编辑同骨架。
    """
    edits.sort()
    out: list[str] = []
    prev = 0
    for s, e, r in edits:
        out.append(t[prev:s])
        out.append(r)
        prev = e
    out.append(t[prev:])
    return "".join(out)


def _drop_pkg_loads(t: str, pkg: str) -> tuple[str, int]:
    r"""剥 ``\usepackage``/``\RequirePackage`` 对 pkg 的装载 → (新文本, 摘除数)。

    独载: 行首锚 (前缀全空白) → 整行注释; 行内嵌入 → 置空
    (注释替换会误吃同行尾 token)。名单成员按逗号列**元素**判
    (``_load_elems``) —— 旧的 ``\b<pkg>\b`` 子串形把 ``{physics-tools}``
    的连字符兄弟名撕残 (``-tools`` 残留); 保留站点沿用原前缀文本
    (不再顺手归并 cmd↔opts↔``{`` 间空白)。
    """
    want = pkg.lower()
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        if want not in _load_elems(m):
            return m.group(0)
        n += 1
        keep = [
            p.strip()
            for p in m.group(1).split(",")
            if p.strip() and p.strip().lower() != want
        ]
        if keep:
            return f"{m.group(0)[: m.start(1) - m.start(0)]}{','.join(keep)}}}"
        ls = m.string.rfind("\n", 0, m.start()) + 1
        if m.string[ls : m.start()].strip():
            return ""
        return "% fixloop: stripped " + m.group(0).strip()

    return _LOAD_SITE_RE.sub(_sub, t), n


#: ``\usepackage``/``\RequirePackage`` 装载点 —— group(1)=花括内逗号列
#: 元素串 (``[opts]`` 跳过)。无行首锚: ``\if..\RequirePackage..\fi``
#: 单行条件形也收, 前置在 token 前序位恒正确。
_LOAD_SITE_RE = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]\n]*\])?\s*\{([^}]*)\}"
)


def _load_elems(m: re.Match[str]) -> set[str]:
    r"""``_LOAD_SITE_RE`` 命中的花括逗号列 → 小写去空白包名集。"""
    return {e.strip().lower() for e in m.group(1).split(",") if e.strip()}


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


def _inject_before_anchor(  # noqa: PLR0913 - 锚/depth0/strict_first/fallback 四旋钮各叶语义位
    ctx: LoopCtx,
    snippet: str,
    anchor: re.Pattern[str],
    *,
    depth0: bool = False,
    strict_first: bool = False,
    fallback: str | Callable[[LoopCtx, str], bool] | None = None,
) -> bool:
    r"""主文件首个活 ``anchor`` 命中行首前注入 snippet (幂等)。

    遮盖视图找锚: ``depth0`` 走 ``iter_depth0`` (def 体/花括组内命中不算,
    csfix docclass/paralong begindoc 口径), 缺省 ``finditer`` 全命中
    (misschar begindoc 口径); ``_is_live`` 复核剔注释/verbatim 死命中。
    ``strict_first`` 只验首个遮盖命中 (shim begindoc 口径: 首命中落死区
    不续扫, 视同无锚直退 ``fallback``)。

    无可用锚时 ``fallback`` 分派: ``None`` → False; ``"head"`` → 文件头
    注入 (csfix docclass 臂: preamble 顶仍先于一切 cls 执行); callable →
    委派 (shim: ``_inject_after_docclass``)。
    """
    main = ctx.main_path()
    t = ctx.read(main) if main is not None else None
    if t is None or snippet in t:
        return False
    masked = mask_tex(t)
    pos: int | None = None
    if strict_first:
        m = anchor.search(masked)
        if m is not None and _is_live(m, masked, t):
            pos = t.rfind("\n", 0, m.start()) + 1
    else:
        hits = iter_depth0(anchor, masked) if depth0 else anchor.finditer(masked)
        for m in hits:
            if _is_live(m, masked, t):
                pos = t.rfind("\n", 0, m.start()) + 1
                break
    if pos is None:
        if fallback is None:
            return False
        if fallback == "head":
            ctx.write(main, snippet + "\n" + t)
            return True
        return fallback(ctx, snippet)
    ctx.write(main, t[:pos] + snippet + "\n" + t[pos:])
    return True


def _inject_before_begindoc(
    ctx: LoopCtx,
    snippet: str,
    *,
    depth0: bool = False,
    strict_first: bool = False,
    fallback: str | Callable[[LoopCtx, str], bool] | None = None,
) -> bool:
    r"""``_inject_before_anchor`` 的 ``\begin{document}`` 锚特化。

    导言区末位注入点 —— 晚于一切包装载的 catcode/charclass 重声明,
    又早于 class ``\AtBeginDocument`` 钩内排版与 ``\begin{document}``
    执行内触发的 aux 读面; ``\@onlypreamble`` 命令在此仍合法。
    """
    return _inject_before_anchor(
        ctx,
        snippet,
        BEGIN_DOC_RX,
        depth0=depth0,
        strict_first=strict_first,
        fallback=fallback,
    )


# ════════════════════════════════════════════════════════════════
# 编译 log 定位 (C3 收尾归位: csfix/bib/shim 三叶共用的通用版)
# ════════════════════════════════════════════════════════════════


def _iter_log_candidates(ctx: LoopCtx) -> Iterable[Path]:
    """本轮编译 log 候选枚举: ``{stem}.log`` → ``_tect_out/{stem}.log`` → 全树 ``*.log`` (名序)。

    ``_fixloop_log``/``_compile_log_text`` 共用的定位序 —— 两侧仅内容
    门不同 (无门 vs ``Missing character`` 门), 枚举单源消漂移。
    ``ctx.read`` 吞 OSError → ``None``, 缺件/目录同名天然滤除。
    """
    main = ctx.main_path()
    if main is not None:
        stem = main.stem
        yield ctx.wdir / f"{stem}.log"
        yield ctx.wdir / "_tect_out" / f"{stem}.log"
    yield from sorted(ctx.wdir.rglob("*.log"))


def _fixloop_log(ctx: LoopCtx) -> str:
    """本轮编译 log 定位 (通用版, 无内容过滤)。

    首个非空候选即返 —— 候选序见 ``_iter_log_candidates``
    (``{stem}.log`` → ``_tect_out/{stem}.log`` → 兜底 ``*.log``)。
    """
    for p in _iter_log_candidates(ctx):
        if t := ctx.read(p):
            return t
    return ""


def _compile_log_text(ctx: LoopCtx) -> str:
    """定位本轮编译 log (Missing character 内容门)。

    候选序同 ``_iter_log_candidates``; 首个含 Missing character
    的非空 log 命中即返。
    """
    for p in _iter_log_candidates(ctx):
        if (t := ctx.read(p)) and "Missing character" in t:
            return t
    return ""


def _mc_seen(ctx: LoopCtx) -> dict[int, tuple[str, str]] | None:
    """含缺字的编译 log → 解析码位表; 无 log → ``None`` (表可空: 全 nullfont 滤除)。

    ``_compile_log_text`` (内容门) + ``_mc_parse_log`` 的读侧短路 ——
    misschar 叶与 shim 叶 log-gate 同用 (后者 ``_fixloop_log`` + 子串门
    无 rglob 兜底, 弱于本口径)。
    """
    log = _compile_log_text(ctx)
    return _mc_parse_log(log) if log else None


# ════════════════════════════════════════════════════════════════
# missing_char 读侧/规划侧机制 (C3 收尾归位: shim 叶同消费)
# 「Missing character」行解析 → 码位 → 表匹配 → 修复规划;
# 修复动作本体 (warmup/字面替换/逐字回退/accent 站点) 留在
# _builtins_misschar。
# ════════════════════════════════════════════════════════════════

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

    ``_builtins_misschar._fb_snippet_lines`` 与 shim ``cs_rebind`` 共用
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


# ════════════════════════════════════════════════════════════════
# 工作树指纹 (engine 落件同步与 misc 失效补共用的通用树扫件)
# ════════════════════════════════════════════════════════════════


def _wdir_fingerprint(wdir: Path) -> dict[Path, tuple[int, int]]:
    """工作树文件 ``(mtime_ns, size)`` 指纹——``run_tool`` 改盘面快照 diff 用。

    通用树扫件而非规则实现——engine ``_landing_sync`` 的外部落件基线与
    ``_builtins_misc._invalidate_changed``/docstrip 全量失效两侧消费。
    """
    fp: dict[Path, tuple[int, int]] = {}
    for p in wdir.rglob("*"):
        try:
            st = p.stat()
        except OSError:
            continue
        if p.is_file():
            fp[p] = (st.st_mtime_ns, st.st_size)
    return fp


def _fp_diff(
    before: dict[Path, tuple[int, int]],
    after: dict[Path, tuple[int, int]],
    *,
    exclude: Iterable[Path] = (),
) -> list[Path]:
    """指纹 diff 核: 基线间变值路径集 (``exclude`` 自产写件除外)。

    ``_landing_sync`` 的外部落件判据与 ``_builtins_misc._invalidate_changed``
    的通用补同核——后者免 exclude (全量失效)。
    """
    excl = set(exclude)
    return [
        p
        for p in set(before) | set(after)
        if before.get(p) != after.get(p) and p not in excl
    ]


# ════════════════════════════════════════════════════════════════
# 工程件遍历 (自 _builtins_shim 归位: misc ``_conv_sibling`` 同口径共用)
# ════════════════════════════════════════════════════════════════

#: 工程件遍历的排除目录 —— ``_texmf`` (wired vendored texmfhome) 与
#: ``_tect_out`` (tectonic 产物树) 是引擎/注入侧封装件, 非稿自带件。
#: (canonical 自 _builtins_graphics 归位 —— 彼侧副本删后回引本件。)
_PDF_SANITIZE_SKIP_DIRS = frozenset({"_texmf", "_tect_out"})


def _in_wdir(ctx: LoopCtx, p: Path) -> bool:
    """``p`` resolve 后是否仍落 ``ctx.wdir`` 内 —— resolve 失败按逃逸论。"""
    try:
        p.resolve().relative_to(ctx.wdir.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _wdir_project_files(ctx: LoopCtx) -> Iterator[tuple[Path, tuple[str, ...]]]:
    """``wdir`` 工程件遍历 → ``(path, wdir 相对 parts)``, dot 段与引擎树排除。

    dot 段路径 (``.git``/``.fixloop-*`` 类) 与任一段命中
    ``_PDF_SANITIZE_SKIP_DIRS`` (``_texmf`` wired texmfhome / ``_tect_out``
    tectonic 产物树) 的件都不算工程档——引擎封装件非稿自带, 归位/hoist
    不得把它们当搬运源 (``parts[0]`` 判会漏嵌套位, 须 any-part)。
    """
    for p in ctx.wdir.rglob("*"):
        if not safe_is_file(p):
            continue
        parts = p.relative_to(ctx.wdir).parts
        if any(part.startswith(".") for part in parts) or any(
            part in _PDF_SANITIZE_SKIP_DIRS for part in parts
        ):
            continue
        yield p, parts


# ════════════════════════════════════════════════════════════════
# 引擎索引查包 + advisory 记账 (自 actions.py/_builtins_vendored 归位)
# ════════════════════════════════════════════════════════════════


def _index_candidates(eng: Engine, fname: str, *, suggest: bool = False) -> list[str]:
    """``filemap`` + ``ctan_fetch.peek_index`` 索引查包链 (``_builtins_vendored._index_providers`` 同构)。

    ``suggest=True`` 时 ``query`` 空集再退 ``suggest`` 前缀猜测——候选提示
    面可宽; 遮蔽佐证面 (``_index_providers``) 应保持默认 ``False`` 只收精确命中。
    """
    pkgs = list(eng.filemap(fname))
    if not pkgs:
        fetcher = getattr(eng, "ctan_fetch", None)
        peek = getattr(fetcher, "peek_index", None)
        idx = peek() if callable(peek) else None
        if idx is not None:
            pkgs = idx.query(fname)
            if suggest and not pkgs:
                pkgs = idx.suggest(fname.rsplit(".", 1)[0])
    return pkgs


def _advise(ctx: LoopCtx, adv: str) -> None:
    """幂等 advisory 记账 —— 同文条目不重复落 ``ctx.ledger.advisories``。

    ``ctx.advisories`` 经 ``LoopCtx.__getattr__`` 转发到 ``ctx.ledger.advisories``
    (engine.py forward 表 ``"advisories": "ledger"``), 两写形同列表 ——
    actions.py 与 _builtins_vendored.py 两侧同构副本的单源。
    """
    if adv not in ctx.advisories:
        ctx.advisories.append(adv)
