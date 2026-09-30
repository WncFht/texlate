r"""builtins._csfix_abd — ``\AtBeginDocument`` 迟延定义者臂 (csfix 拆分)。

错误归因行 = live ``\begin{document}`` → 后定义者在 pkg/cls 注册
的钩体内 (babel .ldf ``\DeclareMathOperator`` 族); 声明点行前注
``\AtBeginDocument{\let\X\@undefined}``, 钩 FIFO 先清位迟延
定义者再定义赢。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.compile._docseams import find_docclass_ends
from texlate.compile.fixloop.builtins._csfix_alloc import (
    _inject_before_docclass,
)
from texlate.compile.fixloop.builtins._csfix_sites import _endstar_name
from texlate.compile.fixloop.builtins.common import _undefine_cs
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop._engine_ctx import LoopCtx


__all__ = [
    "_ABD_ERR_FILE_RE",
    "_abd_deferred",
    "_abd_hook_clear",
    "find_docclass_ends",
]


#: file:line 形 already_def 的归因行 —— ``path/<file>.<ext>:N:`` + Command 签。
#: group(1)=基名茎 group(2)=扩展 group(3)=行号 group(4)=撞名。判 ``\AtBeginDocument``
#: 钩内 deferred 定义者用: 钩体在 ``\begin{document}`` 执行期才跑, 其内定义撞名
#: 的 file:line 归因恒落在 ``\begin{document}`` 所在行 (1706.00033 russianb.ldf
#: ``\DeclareMathOperator{\sh}`` vs 用户 ``\def\sh`` 实证)。
_ABD_ERR_FILE_RE = re.compile(
    r"^[ \t]*\S*?([\w.+-]+)\."
    r"(tex|sty|cls|bbl|ldf|def|clo|ltx|dtx|ins|fd):(\d+):"
    r"\s*(?:LaTeX Error:\s*)?Command\s+[`'\"]?\\([A-Za-z@]+)[`'\"]?"
    r"\s+already\s+defined",
    re.IGNORECASE | re.MULTILINE,
)


def _abd_deferred(ctx: LoopCtx, blob: str) -> set[str]:
    r"""归因行 = live ``\begin{document}`` 的 already_def 撞名集。

    ``\AtBeginDocument`` 钩内 deferred 定义者 (包/类装载期注册, ``\begin{document}``
    执行时才定义) 的专属判据: 钩执行期错误的 file:line 归因恒为钩所在文件的
    ``\begin{document}`` 行。立即 ``\let`` (docclass 块/装载点前) 恒错序 ——
    先于用户 preamble 定义跑完, 钩内定义者照样撞; 站点臂亦够不到包内钩体。
    文件按基名匹配 wdir 件集, 归因行遮罩后须仍见 live ``\begin{document}``
    (剔注释/verbatim 假行)。
    """
    files = {
        f.name.lower(): f
        for f in ctx.tex_files((".tex", ".sty", ".cls", ".bbl", ".ltx", ".dtx"))
    }
    out: set[str] = set()
    for m in _ABD_ERR_FILE_RE.finditer(blob):
        f = files.get(f"{m.group(1)}.{m.group(2)}".lower())
        if f is None:
            continue
        t = ctx.read(f)
        if t is None:
            continue
        lines = mask_tex(t).splitlines()
        n = int(m.group(3))
        if 1 <= n <= len(lines) and "\\begin{document}" in lines[n - 1]:
            out.add(m.group(4))
    return out


def _abd_hook_clear(
    ctx: LoopCtx, main_t: str, offenders: set[str], blob: str
) -> set[str]:
    r"""``\AtBeginDocument`` 迟延定义者臂 → 本轮钩内清位名集 (空 = 臂未接管)。

    撞名归因行 = live ``\begin{document}`` → 后定义者在 pkg/cls 注册的钩体内
    (babel .ldf ``\DeclareMathOperator`` 族), 一切立即 ``\let`` (docclass
    块/装载点前) 恒错序 —— 钩执行晚于全部 preamble 行。修 = 声明点行前注
    ``\AtBeginDocument{<csname-let 清位串>}`` —— 钩按注册序 FIFO 执行, 先于一切
    pkg/cls 钩注册 → 钩执行时先清位, 迟延定义者再定义赢 (1706.00033 ``\sh``
    实证)。无任何声明点 → 不接管 (209 稿 ``\documentstyle`` 亦锚:
    209-rewrite 换核后钩生效, 不换则死代码无害); ``_inject_before_docclass``
    失败 (snippet 已在) 同样不接管。end* 名不入: 迟延定义者仍是
    ``\@ifdefinable`` 恒拒, 钩内 ``\let`` 同样徒劳。已注册钩的名不重注
    (本轮 ``main_t`` 文本复核)。
    """
    if not find_docclass_ends(main_t):
        return set()
    abd = [
        n
        for n in sorted(_abd_deferred(ctx, blob) & offenders)
        if not _endstar_name(n)
        and f"\\let\\{n}\\@undefined" not in main_t
        and f"\\csname {n}\\endcsname" not in main_t
    ]
    if not abd or not _inject_before_docclass(
        ctx,
        "\\AtBeginDocument{"
        + "".join(_undefine_cs(n) for n in abd)
        + "} % fixloop: deferred-definer clear",
    ):
        return set()
    return set(abd)
