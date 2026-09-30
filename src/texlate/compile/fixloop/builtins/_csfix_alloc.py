r"""builtins._csfix_alloc — 跨域共享护栏叶 (csfix 拆分)。

寄存器/盒型分配名集 (``_allocated_cs_names``: ``\newbox`` 裸形 +
``\newlength{}`` 花括号形 + ``\newif`` 伴生 ``true``/``false``)
—— ``undefine_for_redef``/``ctlseq_undefine`` 双臂的清位禁区;
主文件 ``\documentclass`` 行前注入 ``_inject_before_docclass``
(cls 执行期调用面专用, ``_csfix_target``/``_csfix_abd`` 同消费)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins.common import _inject_before_anchor
from texlate.textutil import DOCCLASS_RX

if TYPE_CHECKING:
    from texlate.compile.fixloop._engine_ctx import LoopCtx


__all__ = [
    "DOCCLASS_RX",
    "_ALLOC_BRACE_RE",
    "_ALLOC_CS_RE",
    "_allocated_cs_names",
    "_inject_before_anchor",
    "_inject_before_docclass",
]


def _inject_before_docclass(ctx: LoopCtx, snippet: str) -> bool:
    r"""主文件首个活 ``\documentclass`` 行首前注入 snippet (幂等)。

    cls 内调用面专用: ``\documentclass`` 执行期的 undefined_cs ——
    halt_on_error 下缝后注入永远够不到。首个 depth-0 docclass token
    的行首前落位; 无 depth-0 docclass (宏代理形/残缺稿) 退文件头,
    preamble 顶仍先于一切 cls 执行。多臂 ``\if..\else..\fi`` 分支
    docclass 是已知残余 (注进首臂, 不烂义)。
    """
    return _inject_before_anchor(
        ctx, snippet, DOCCLASS_RX, depth0=True, fallback="head"
    )


#: 寄存器/盒型分配的裸 cs 形 (plain/cls 内码常见): ``\newbox\splitbox``。
#: ``\newif\ifX`` 伴生 ``\Xtrue``/``\Xfalse``; ``*def`` 系 primitive 同把名
#: 绑进寄存器槽位——``\let\X\@undefined`` 后名被后载包抢占, 原 ``\setbox``/
#: ``\advance`` 点变 Missing number (2211.04482 aastex62 ``\splitbox`` 实证)。
_ALLOC_CS_RE = re.compile(
    r"\\(?:newbox|newcount|newdimen|newskip|newmuskip|newtoks|newread"
    r"|newwrite|newif|newinsert|newmarks|newfont|newlanguage"
    r"|chardef|mathchardef|countdef|dimendef|skipdef|muskipdef"
    r"|toksdef|font)\s*\\([A-Za-z@]+)"
)
#: LaTeX 花括号形: ``\newlength{\x}``/``\newsavebox{\x}`` 直给寄存器名;
#: ``\newcounter{c}`` 分配 ``\c@c``; ``\newboolean{b}`` 内部走 ``\newif\ifb``。


_ALLOC_BRACE_RE = re.compile(
    r"\\(newlength|newsavebox|newcounter|newboolean|provideboolean)"
    r"\s*\{\s*\\?([A-Za-z@]+)\s*\}"
)


def _allocated_cs_names(masked_blob: str) -> frozenset[str]:
    r"""遮盖视图上扫寄存器/盒型分配名集 (含 ``\newif``/``\newboolean`` 伴生)。"""
    names: set[str] = set()
    for m in _ALLOC_CS_RE.finditer(masked_blob):
        n = m.group(1)
        names.add(n)
        if n.startswith("if") and n[2:]:
            names.add(n[2:] + "true")
            names.add(n[2:] + "false")
    for m in _ALLOC_BRACE_RE.finditer(masked_blob):
        kind, n = m.group(1), m.group(2)
        if kind in ("newlength", "newsavebox"):
            names.add(n)
        elif kind == "newcounter":
            names.add("c@" + n)
        else:  # newboolean/provideboolean → \newif\ifn 同构
            names.add("if" + n)
            names.add(n + "true")
            names.add(n + "false")
    return frozenset(names)
