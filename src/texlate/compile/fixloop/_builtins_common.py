r"""_builtins_common — fixloop builtins 跨域共享原语 (C3 builtins.py 拆分叶子)。

跨域 helper 单源: ``mask_tex`` 遮盖视图匹配 / 逐 tex 文件映射 / ``\\usepackage``
剥载 / ``\\documentclass`` 缝后注入 / pdfTeX 原语清单 (engine._FAMILY_TOKENS
与 pdftex_prim_polyfill 双侧消费)。只做 helper/常量, 不含注册表条目本体。
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from texlate.compile.inject import find_docclass_ends
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from texlate.compile.fixloop.engine import LoopCtx

# pdfTeX 原语清单 (spike L284-298 + 2410.00012 实证扩: 文档面对象/注释/资源族)
PDFTEX_PRIMS = (
    "pdfoutput",
    "pdfminorversion",
    "pdfcompresslevel",
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
    "pdfsuppresswarningpagegroup",
)


_USE_RE = re.compile(
    r"^(\s*)\\(usepackage|RequirePackage)\s*(\[([^\]]*)\])?\s*\{([^}]*)\}",
    re.MULTILINE,
)


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
