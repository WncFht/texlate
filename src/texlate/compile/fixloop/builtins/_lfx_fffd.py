r"""builtins._lfx_fffd — 字面 U+FFFD 邻域分派替换 (layoutfix 拆分)。

``fffd_context_fix``: FFFD 连跑按双侧邻域分派 (CJK 间 ``{}``/页码
``--``/拉丁名断点 ``'``/``\'``/兜底 ``{}``) —— 替掉 char_table
``fffd_repl('-')`` 的无语境连字符 (``许-多``/``C-orcoles`` 错修实证)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import _map_tex_files, _splice
from texlate.textutil import is_cjk_cp, mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = [
    "_FFFD_RUN_RX",
    "_fffd_repl",
    "_fffd_text_edits",
    "fffd_context_fix",
    "is_cjk_cp",
]

#: FFFD 连跑 (多字 mojibake 常连发, ``来��级``) —— 整跑按
#: 双侧邻域一次替换, 不留 ``{}{}`` 串。
_FFFD_RUN_RX = re.compile("\\uFFFD+")


def _fffd_repl(before: str, after: str) -> str:
    r"""FFFD 跑双侧邻域 → 替换串。

    - CJK 夹 ``→ ``{}`` (``许多``→``许多`` 原字已失, 空组保 token 界);
    - 数字尾页码域 ``→ ``--`` (``91104``/``120C139`` en-dash 页域);
    - 拉丁字母夹 ``→ ``\'`` (后随小写, ``Corcoles``→``C\'orcoles``=
      Córcoles) / ``'`` (后随大写, ``DellAnna``→``Dell'Anna``——撇号
      断点非重音);
    - 单侧 CJK / emoji / hashtag / 兜底 ``→ ``{}``。
    """
    if before and after:
        b_cjk = is_cjk_cp(ord(before))
        a_cjk = is_cjk_cp(ord(after))
        if b_cjk and a_cjk:
            return "{}"
        if before.isdigit():
            return "--"
        if b_cjk or a_cjk:
            # CJK-拉丁混夹 (``isalpha`` 对 CJK 为真, 须在拉丁臂前分流)
            return "{}"
        if before.isalpha() and after.isalpha():
            return "'" if after.isupper() else "\\'"
    elif (before and is_cjk_cp(ord(before))) or (after and is_cjk_cp(ord(after))):
        return "{}"
    return "{}"


def _fffd_text_edits(t: str) -> tuple[str, int]:
    """单文件 FFFD 跑分派 (遮盖视图活位 only——注释/verbatim 内不动)。"""
    vis = mask_tex(t)
    edits: list[tuple[int, int, str]] = []
    for m in _FFFD_RUN_RX.finditer(vis):
        before = t[m.start() - 1] if m.start() else ""
        after = t[m.end()] if m.end() < len(t) else ""
        edits.append((m.start(), m.end(), _fffd_repl(before, after)))
    if not edits:
        return t, 0
    return _splice(t, edits), len(edits)


def fffd_context_fix(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""字面 U+FFFD 邻域分派替换 (vis_degenerate 桶, 10 格实证)。

    源档 FFFD = mojibake 残痕, 无语境 ``-`` 盲换 (char_table
    ``fffd_repl``) 产 ``许-多``/``C-orcoles`` 错修实证——邻域分派:

    - CJK 夹 ``{}``: 0812.1323 许多 / 1206.0210 存在 / 1206.5329 表明;
    - 数字尾 ``--``: 1107.0677 ``91104`` / 1812.00010 ``120C139``;
    - 拉丁夹 ``\'``/``'``: 1003.0894 ``DellAnna`` (大写随=撇号) /
      1306.2279 ``Corcoles`` (小写随=重音, 实面在 .bbl);
    - emoji/hashtag/兜底 ``{}``: 2501.16123 / 2302.00102 / 2409.11654。

    词法单源 ``mask_tex`` 遮盖面——注释/verbatim 内 FFFD 不动; 嵌
    PDF 轴标里的 FFFD 是非字面位 (figure 内嵌), 不在本臂面。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".bbl", ".cls", ".sty"))
    n = _map_tex_files(ctx, exts, _fffd_text_edits)
    if not n:
        return False, "no literal U+FFFD in live surface"
    return True, f"context-dispatched U+FFFD runs in {n} file(s)"
