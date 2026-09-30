r"""builtins.misschar.umath — umath_doc_cs_restore 遮蔽 cs 复位 (C5 拆叶)。

unicode-math 已知名表收割 (``_UMATH_ROW_RX``/``_UMATH_CACHE``/
``_UMATH_DEF_RX``/``_UMATH_LOAD_RX``/``_umath_names``) + doc 侧
``\newcommand`` 族定义平衡提取 (``_cs_tok_end``/``_umath_doc_defs``) →
``\AtBeginDocument`` ``\renewcommand`` 复位行 (``umath_doc_cs_restore``)。
``_skip_ws``/``_brace_end`` 经本叶回引。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import (
    _brace_end,
    _inject_before_begindoc,
    _skip_ws,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine.ctx import LoopCtx
    from texlate.compile.fixloop.engine.proto import Engine

__all__ = [
    "_UMATH_CACHE",
    "_UMATH_DEF_RX",
    "_UMATH_LOAD_RX",
    "_UMATH_ROW_RX",
    "_brace_end",
    "_cs_tok_end",
    "_skip_ws",
    "_umath_doc_defs",
    "_umath_names",
    "umath_doc_cs_restore",
]


# ════════════════════════════════════════════════════════════════
# umath_doc_cs_restore: unicode-math 遮蔽 doc 自定义 cs → 复位 (qc-impl)
# ════════════════════════════════════════════════════════════════

#: ``\\UnicodeMathSymbol{cp}{\\cs}{cls}`` 行内 cs 名提取——unicode-math
#: 已知名全集以 TL 装件 ``unicode-math-table.tex`` 为准 (进程缓存)。
_UMATH_ROW_RX = re.compile(r"\\UnicodeMathSymbol\{[^{}]*\}\s*\{\\([A-Za-z@]+)\}")
#: ``_umath_names`` 进程级名表缓存——dict 可变容器避免 global 重绑 (PLW0603)。
_UMATH_CACHE: dict[str, frozenset[str]] = {}

#: doc 侧 ``\\newcommand`` 族定义头 —— 抓 cs 名 + 可选 ``[nargs]``;
#: body 另行平衡组/单 token 提取 (regex 吃不下平衡括)。
_UMATH_DEF_RX = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)"
    r"\s*\*?\s*\{?\\([A-Za-z@]+)\}?\s*(\[[0-9]\])?"
)

#: unicode-math 装载面探针 (\\usepackage{unicode-math} / \\setmathfont)。
_UMATH_LOAD_RX = re.compile(r"unicode-math|unicode_math|\\setmathfont")


def _umath_names(ctx: LoopCtx) -> frozenset[str] | None:
    """``kpsewhich unicode-math-table.tex`` → umath 已知名集 (None=不可解析)。"""
    if "names" in _UMATH_CACHE:
        return _UMATH_CACHE["names"]
    rc, out, _to = ctx.run_tool(["kpsewhich", "unicode-math-table.tex"], 15)
    if rc != 0:
        return None
    path = next(
        (
            ln.strip()
            for ln in out.splitlines()
            if ln.strip().endswith("unicode-math-table.tex")
        ),
        "",
    )
    if not path:
        return None
    try:
        data = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    _UMATH_CACHE["names"] = frozenset(_UMATH_ROW_RX.findall(data))
    return _UMATH_CACHE["names"]


def _cs_tok_end(t: str, pos: int) -> int:
    r"""``t[pos]=='\\'`` → cs token 末 offset (字母+@ 连读, 否则单字符)。"""
    j = pos + 1
    if j < len(t) and (t[j].isalpha() or t[j] == "@"):
        while j < len(t) and (t[j].isalpha() or t[j] == "@"):
            j += 1
    else:
        j = pos + 2
    return j


def _umath_doc_defs(t: str, umath: frozenset[str]) -> dict[str, str]:
    r"""单文件 doc-def 收割: umath 名表 ∩ ``\newcommand`` 族 → ``\renewcommand`` 复位行。

    body 原文搬运; 头部命中在遮盖视图 (注释/verbatim 内定义不收); body 在原文取——
    mask_tex 保长, 双视错位等。
    """
    vis = mask_tex(t)
    out: dict[str, str] = {}
    for m in _UMATH_DEF_RX.finditer(vis):
        name, nargs = m.group(1), m.group(2) or ""
        if name not in umath:
            continue
        pos = _skip_ws(t, m.end())
        if pos >= len(t):
            continue
        if t[pos] == "{":
            end = _brace_end(t, pos)
            if end > len(t):
                continue
            body = t[pos:end]
        elif t[pos] == "\\":
            end = _cs_tok_end(t, pos)
            body = t[pos:end]
        elif t[pos].isalpha() or t[pos] in "#$%&~^_":
            continue  # 裸字符 body——异常形不收
        else:
            body, end = t[pos : pos + 1], pos + 1
        out[name] = f"\\renewcommand{{\\{name}}}{nargs}{body}"
    return out


def umath_doc_cs_restore(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""unicode-math 遮蔽 doc ``\\newcommand`` 名 → ``\\AtBeginDocument`` 复位。

    实证 (qc-impl 2026-09-28, 2609.19583): ``unicode-math-table.tex:1302``
    ``\\smt``=U+2AAA 覆盖 doc ``\\newcommand{\\smt}{SMT\\xspace}``,
    LinLibertine 无槽 → 节首 tofu (char_table ``smaller_than``→``<`` 只救
    字面不收 cs 产出)。``\\AtBeginDocument`` 钩按注册序执行, 导言区末位
    注入使复位行晚于 umath 字体装载钩生效——doc 定义重夺名。
    """
    del eng, payload
    exts = tuple(params.get("exts") or (".tex", ".sty", ".cls"))
    names = _umath_names(ctx)
    if not names:
        return False, "unicode-math-table.tex not resolvable"
    blob = "\n".join(s for f in ctx.tex_files(exts) if (s := ctx.read(f)) is not None)
    if not _UMATH_LOAD_RX.search(blob):
        return False, "unicode-math not loaded"
    restored: dict[str, str] = {}
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        restored.update(_umath_doc_defs(t, names))
    if not restored:
        return False, "no doc def shadowed by unicode-math"
    lines = [
        "% fixloop: umath_doc_cs_restore",
        "\\makeatletter",
        "\\AtBeginDocument{%",
        *[f"{v}%" for v in restored.values()],
        "}",
        "\\makeatother",
    ]
    if not _inject_before_begindoc(ctx, "\n".join(lines)):
        return False, "restore hook already injected"
    return True, f"restored {len(restored)} shadowed cs: {', '.join(sorted(restored))}"
