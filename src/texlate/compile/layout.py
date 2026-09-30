r"""版式手术 —— inject.py C4 拆分出叶。

概念归属：译文侧版式适配——``FLOAT_SIZING``（超高 figure/table 浮体
``\resizebox*`` 缩进页高 + ``\typeout`` 日志回读）、wrapfig 三环境降级
（``demote_wrapfloats``：wrapfigure/wraptable/wrapfloat → 普通浮体——
绕排落点依赖后续段落行数，译文缩短必然漂移，重则 caption 裁出版心，
2609.19101 zh p6 双亚型实证）。

``TABLE_FITTING``（表族 env/before+after 成对钩 adjustbox）0930 拔除：
成对钩在 begin/end 配对不候场形（cls ``\@tabular`` cs 形收尾、
``\end{document}`` 早退、宏内 env）与 fixloop v1 ``TeXlateTabClamp``
同挂时钩序错位，双压崩成 ``ended by`` 毁编（vault 普查 ~1200 事件）；
表族钳宽归 fixloop ``tabular_fit`` v2 源级跨度包（warn_overfull 驱动）。

缝原语（``_splice_after_seams``/``_splice_before_document``/``find_docclass_ends``）
已独立成 ``_docseams`` 叶，本叶顶层 ``from ._docseams import`` 取用；inject 侧
对本叶公共名静态回引（缝原语出 ``_docseams`` 后环断，顶层无双向 import 环）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from texlate.latex.model import ws_skip
from texlate.textutil import (
    BEGIN_DOC_RX,
    DOCCLASS_RX,
    iter_depth0,
)

from ._docseams import _splice_after_seams, _splice_before_document, find_docclass_ends
from .mainfile import _MAIN_TEX_SUFFIXES
from .mask import apply_edits, group_end, visible_tex
from .normalize import _read_tex
from .transcode import _iter_files

if TYPE_CHECKING:
    from pathlib import Path

#: FLOAT_SIZING 仅在工程含浮体环境时注入（docs/spec/compile.md）。
#: ``\@endfloatbox`` 仅浮体收尾机制调用——``\@captype`` 在位即整类浮体
#: （algorithm/algocf/listing/sideways*/deluxetable 内层 table/sn-jnl
#: ``tableorg`` 包装等具名 env 无需白名单枚举——白名单会漏改名壳，
#: 2503.10198 ``\@currenvir=tableorg`` 实证）。宽 ``>\textwidth`` / 高
#: ``>\textheight`` 两臂各自 shrink-only（旋转浮体两维天然随 90°
#: 对调，同一对限仍然正确）。
FLOAT_SIZING = r"""% texlate: fit complete oversized float boxes v2
\RequirePackage{graphicx}
\begingroup
\makeatletter
\AtBeginDocument{%
\let\texlate@endfloatbox\@endfloatbox
\def\@endfloatbox{%
\texlate@endfloatbox
\expandafter\ifx\csname @captype\endcsname\relax\else
\ifdim\wd\@currbox>\textwidth
\typeout{TeXlate-Float-Fit: \@captype\space \csname the\@captype\endcsname; width \the\wd\@currbox; limit \the\textwidth}%
\global\setbox\@currbox=\vbox{\resizebox{\textwidth}{!}{\box\@currbox}}%
\fi
\ifdim\dimexpr\ht\@currbox+\dp\@currbox\relax>\textheight
\edef\texlate@floatwidth{\the\wd\@currbox}%
\edef\texlate@floatheight{\the\dimexpr\textheight-\baselineskip\relax}%
\ifdim\texlate@floatheight>0pt
\typeout{TeXlate-Float-Fit: \@captype\space \csname the\@captype\endcsname; height \the\dimexpr\ht\@currbox+\dp\@currbox\relax; limit \texlate@floatheight}%
\global\setbox\@currbox=\vbox{\hbox to\texlate@floatwidth{\hfil\resizebox*{!}{\texlate@floatheight}{\box\@currbox}\hfil}}%
\fi\fi\fi}%
}
\endgroup
"""


def inject_float_sizing(root: Path) -> int:
    r"""FLOAT_SIZING 前导块：仅在工程确实含浮体环境时注入主文件。

    超宽/超高 float 用 `\resizebox`/`\resizebox*` 缩进版心 +
    `\typeout{TeXlate-Float-Fit:}` 供日志回读。返回注入文件数——
    ``_float_sized`` 对每个带 ``\documentclass`` 的源档各注一份，
    多 docclass 工程（subfiles 子档）可 >1。
    """
    # ``_iter_files``（os.walk followlinks=False + 软链/隐藏豁免）而非
    # rglob——本函数会写回树内文件，rglob 穿软链目录会把链外件当包内件
    # 改写（normalize.py ``_iter_files`` 同款教训）。
    sources = {}
    for path in _iter_files(root, _MAIN_TEX_SUFFIXES):
        text = _read_tex(path)  # 不可读档/tar 伪装件 → None（同闸）
        if text is not None:
            sources[path] = text
    if not any(
        re.search(
            r"\\begin\s*\{(?:figure|table|algorithm|algocf|listing|lstlisting"
            r"|tcolorbox|tableorg|deluxetable|sidewaystable|sidewaysfigure)\*?\}",
            visible_tex(text),
        )
        for text in sources.values()
    ):
        return 0
    n = 0
    for path, text in sources.items():
        new_text = _float_sized(text)
        if new_text != text:
            try:
                path.write_text(new_text, encoding="utf-8")
            except OSError:
                continue  # 不可写档不计入
            n += 1
    return n


def _float_sized(text: str) -> str:
    r"""单文件 FLOAT_SIZING 注入：dc 在档即收，返回改写后文本（未变=不注）。

    ``\AtBeginDocument`` 钩子只要求前导区位置——bd 在 ``\input`` 子文件的
    编排壳 main（cs/0408015 形态）同权；有 bd 走 ``_splice_before_document``
    depth-0 锚（宏体内 bd 字样不算——``\def\bd{\begin{document}}`` 简写形态），
    无 bd 落 docclass 缝后（多臂声明逐缝注入 + 哨兵兜双执行——
    ``\let\texlate@endfloatbox\@endfloatbox`` 二次捕获已补丁版本会自递归）。
    """
    vis = visible_tex(text)
    # ``texlate@endfloatbox`` 哨兵兼容 v1 旧块——已注过（任一版本）跳过，
    # 否则 v2 再注会把 ``\@endfloatbox`` 链进自身旧补丁造成递归死循环。
    if FLOAT_SIZING.strip() in text or "texlate@endfloatbox" in text:
        return text
    if not DOCCLASS_RX.search(vis):
        return text
    if next(iter_depth0(BEGIN_DOC_RX, vis), None) is not None:
        return _splice_before_document(text, FLOAT_SIZING, sentinel="TeXlateFloatFit")
    hits = find_docclass_ends(text)
    if not hits:
        return text
    block = FLOAT_SIZING
    if len(hits) > 1:
        block = (
            "% texlate: float sizing (multi-seam idempotent)\n"
            "\\ifdefined\\TeXlateFloatFit\\else\n"
            "\\def\\TeXlateFloatFit{1}%\n" + FLOAT_SIZING + "\\fi\n"
        )
    return _splice_after_seams(text, hits, block)


#: wrapfig 三环境：wrapfigure[*]/wraptable[*]/wrapfloat{type}——绕排落点依赖
#: 后续段落行数，译文缩短必然改变落点，轻则滑进同页浮动体造成图压表、重则
#: caption 整段裁出版心（2609.19101 zh p6 双亚型实证，bench/py/wrapfloat_bench
#: 合成复现）。zh 侧无条件降级为普通浮体是根修：浮体间永不重叠、永不裁切。
_WRAP_BEGIN_RX: Final = re.compile(
    r"\\begin\s*\{(wrapfigure\*?|wraptable\*?|wrapfloat)\}"
)
_ENV_TOKEN_RX: Final = re.compile(r"\\(begin|end)\s*\{([^}\s]+)\}")
_WRAP_CAPTYPE: Final = {"wrapfigure": "figure", "wraptable": "table"}
#: 零宽声明（``{0pt}``/``{0in}`` 等）= wrapfig「按内容自然宽度」——降级后
#: 不套 minipage 让 includegraphics 按原尺寸排版。
_ZERO_DIM_RX: Final = re.compile(r"0*(?:\.0*)?\s*[a-z]{0,2}", re.IGNORECASE)


def _wrap_args(
    vis: str, pos: int, kind: str
) -> tuple[int, str | None, str | None] | None:
    """解析 ``[nlines]?{pos}[overhang]?{width}``（wrapfloat 先吃 ``{type}``）。

    返回 ``(args_end, captype, width)``；必需组缺席（残稿）返 None 跳过降级。
    """
    captype = None
    if kind == "wrapfloat":
        i = ws_skip(vis, pos)
        if i >= len(vis) or vis[i] != "{":
            return None
        end = group_end(vis, i)
        captype = vis[i + 1 : end - 1].strip() or None
        pos = end
    pos_seen = False
    i = pos
    while i < len(vis):
        i = ws_skip(vis, i)
        c = vis[i] if i < len(vis) else ""
        if c == "[":
            i = group_end(vis, i)  # nlines / overhang 可选组直接跳过
            continue
        if c == "{":
            end = group_end(vis, i)
            if pos_seen:  # 第二必需组 = width（第一组 pos 已跳过）
                return end, captype, vis[i + 1 : end - 1].strip()
            pos_seen = True
            i = end
            continue
        break
    return None


def _pop_to(stack: list[str], pending: dict[int, dict], name: str) -> None:
    """非配对 end 容错：出栈到匹配层（沿途 pending 作废）。"""
    while stack and stack[-1] != name:
        stack.pop()
        pending.pop(len(stack), None)
    if stack:
        stack.pop()
        pending.pop(len(stack), None)


def _neg_space_edits(vis: str, lo: int, hi: int) -> list[tuple[int, int, str]]:
    r"""降级体内负间距命令删除编辑清单。

    wrapfig 作者惯用负 ``\vspace``/``\hspace``/``\vskip`` 收绕排区（语料实测
    182+2 例），落进浮体盒即成盒溢出（2609.19101 caption 尾行压正文实证）。
    正间距在浮体内无害——只删负值。
    """
    out: list[tuple[int, int, str]] = []
    for m in re.finditer(r"\\(?:vspace|hspace)\*?", vis[lo:hi]):
        i = ws_skip(vis, lo + m.end())
        if i >= hi or vis[i] != "{":
            continue
        end = group_end(vis, i)
        if end > hi:
            continue
        if vis[i + 1 : end - 1].lstrip().startswith("-"):
            out.append((lo + m.start(), end, ""))
    out.extend(
        (lo + m.start(), lo + m.end(), "")
        for m in re.finditer(
            r"\\vskip\s*-(?:\s*[0-9.]+\s*[a-z]{2}|\s*\\[a-zA-Z@]+)", vis[lo:hi]
        )
    )
    return out


def _demote_pair(rec: dict) -> tuple[str, str]:
    """单环境降级串对：``(begin 替换，end 替换)``（星号/宽度/minipage 决策点）。"""
    star = "*" if rec["name"].endswith("*") else ""
    captype = rec["captype"] or _WRAP_CAPTYPE.get(rec["name"].rstrip("*"), "figure")
    env = captype + star
    place = "[!tb]" if star else "[!htb]"
    width = rec["width"]
    if width and not _ZERO_DIM_RX.fullmatch(width):
        return (
            f"\\begin{{{env}}}{place}\\centering\\begin{{minipage}}{{{width}}}",
            f"\\end{{minipage}}\\end{{{env}}}",
        )
    return f"\\begin{{{env}}}{place}\\centering", f"\\end{{{env}}}"


def _demote_wrapfloats_text(tex: str) -> tuple[str, int]:
    r"""单文件降级：wrapfigure/wraptable/wrapfloat → 同名普通浮体环境。

    ``wrapfloat{T}`` 变 ``T``；声明宽度非零时套 ``minipage{原宽}`` 保内层
    ``\linewidth`` 相对尺寸语义；体内负 ``\vspace``/``\hspace``/``\vskip``
    一并删除（绕排收区 hack 落进浮体盒即溢出）。只在环境深度安全位降级
    （文件顶层或 ``document`` 为唯一外层）——minipage/center 等盒内
    wrapfig 降级成浮体会变 ``Not in outer par mode`` 错，保持原样。

    返回 ``(新文本, 降级环境数)``。
    """
    vis = visible_tex(tex)
    edits: list[tuple[int, int, str]] = []
    stack: list[str] = []
    pending: dict[int, dict] = {}  # wrap env 在 stack 的位置 → 解析记录
    n_demoted = 0
    for m in _ENV_TOKEN_RX.finditer(vis):
        tag, name = m.group(1), m.group(2)
        if tag == "begin":
            wm = _WRAP_BEGIN_RX.fullmatch(m.group(0))
            if wm and (not stack or stack[-1] == "document"):
                args = _wrap_args(vis, m.end(), name)
                if args is not None:
                    pending[len(stack)] = {
                        "name": name,
                        "begin_end": args[0],
                        "begin_start": m.start(),
                        "captype": args[1],
                        "width": args[2],
                    }
            stack.append(name)
            continue
        # end token
        if stack and stack[-1] == name:
            stack.pop()
            rec = pending.pop(len(stack), None)
            if rec is None:
                continue
            begin_repl, end_repl = _demote_pair(rec)
            edits.append((rec["begin_start"], rec["begin_end"], begin_repl))
            edits.append((m.start(), m.end(), end_repl))
            edits.extend(_neg_space_edits(vis, rec["begin_end"], m.start()))
            n_demoted += 1
        elif name in stack:
            _pop_to(stack, pending, name)  # 非配对 end（残稿容忍）
    if not edits:
        return tex, 0
    return apply_edits(tex, edits), n_demoted


def demote_wrapfloats(root: Path) -> int:
    r"""工程级 wrapfloat 降级：全 ``.tex/.ltx`` 树扫，返回降级环境总数。

    zh 侧手术（prepare_chinese 编排位）——en 树保持原文 wrapfig 排版保真。
    """
    # ``_iter_files`` + ``_read_tex`` 同 inject_float_sizing——写回路径上
    # rglob 会穿软链目录改写链外件，walk（followlinks=False）整支豁免。
    n = 0
    for path in _iter_files(root, _MAIN_TEX_SUFFIXES):
        text = _read_tex(path)  # 不可读档/tar 伪装件 → None（同闸）
        if text is None:
            continue
        new_text, k = _demote_wrapfloats_text(text)
        if new_text != text:
            try:
                path.write_text(new_text, encoding="utf-8")
            except OSError:
                continue
            n += k
    return n
