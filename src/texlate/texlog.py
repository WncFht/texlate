r"""TeX ``.log`` 词法原语 —— engine/l2/fixloop 三处文件栈收敛的单源实现。

``(``/``)`` 开闭配对追踪：TeX log 用圆括号标记打开/关闭文件，行内可能混
非文件括号（``.log`` 折行、参数转储），非文件 ``(`` 入栈 ``None`` 占位以
保持配对正确——这是文件栈算法的核心不变量（早期"只压不弹"实现把栈
越滚越大的教训）。

79 列折行可能把文件名劈到下一行——本模块逐字符扫，劈断的 token 因扩展名
校验失败自然落入 ``None`` 占位，栈配对仍正确（近似即可，文件栈只用于
缩小 rewrite 作用域与 escalate 上下文，不是精确解析器）。
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "TEX_FILE_EXTS",
    "file_stack_at",
    "looks_like_tex_file",
    "update_file_stack",
]

#: tex 系扩展名（三版并集：engine 编译面 + l2 观测面 + logparse 判定面）。
TEX_FILE_EXTS: Final = frozenset(
    {
        "tex",
        "sty",
        "cls",
        "def",
        "cfg",
        "clo",
        "fd",
        "ldf",
        "dtx",
        "ins",
        "ltx",
        "bib",
        "bst",
        "bbl",
        "bbx",
        "cbx",
        "map",
        "enc",
        "aux",
        "out",
        "toc",
        "mf",
        "tfm",
        "vf",
        "ofm",
        "ovp",
    }
)

#: ``(`` 后的候选文件 token（排除 ``()``/``{}`` 内字符——后者是字体/参数转储）。
_OPEN_TOKEN_RX: Final = re.compile(r"[^\s(){}]+")


def looks_like_tex_file(token: str) -> bool:
    """``(`` 后 token 是否 tex 系文件名（路径末段取扩展名判定）。"""
    base = token.rsplit("/", 1)[-1]
    if "." not in base:
        return False
    return base.rsplit(".", 1)[-1].lower() in TEX_FILE_EXTS


def update_file_stack(ln: str, stack: list[str | None]) -> None:
    """单行扫 ``(``/``)`` 增量维护文件栈；非文件 ``(`` 入栈 ``None`` 保持配对。

    入栈的是字面 token（保留 ``./`` 前缀——log 原样，消费端按 endswith 用）。
    """
    j = 0
    while j < len(ln):
        c = ln[j]
        if c == "(":
            m = _OPEN_TOKEN_RX.match(ln, j + 1)
            if m and looks_like_tex_file(m.group(0)):
                stack.append(m.group(0))
                j = m.end()
                continue
            stack.append(None)
            j += 1
        elif c == ")":
            if stack:
                stack.pop()
            j += 1
        else:
            j += 1


def file_stack_at(lines: list[str], stop: int) -> list[str]:
    """重放 ``lines[:stop]`` 的文件栈，取 stop 行处仍打开的文件名序列。"""
    stack: list[str | None] = []
    for ln in lines[:stop]:
        update_file_stack(ln, stack)
    return [s for s in stack if s]
