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
from pathlib import Path
from typing import Final

__all__ = [
    "TEX_FILE_EXTS",
    "file_stack_at",
    "is_project_file",
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

#: ``Missing character: There is no X in font`` —— X 是**字面字形**，可为
#: ``(``/``)``（nullfont 缺字符实测）：不配对的 ``)`` 会误弹真文件帧，
#: ``(`` 留幻影帧吃掉后续真闭括弧。字形后必跟空格（单字符形态）或行尾；
#: ``(U+0029)``/``("0029)`` 码位形态括号自带配对，不在此列。
_MISS_CHAR_RX: Final = re.compile(r"Missing character: There is no ([()])(?=[ (]|$)")


def looks_like_tex_file(token: str) -> bool:
    """``(`` 后 token 是否 tex 系文件名（路径末段取扩展名判定）。"""
    base = token.rsplit("/", 1)[-1]
    if "." not in base:
        return False
    return base.rsplit(".", 1)[-1].lower() in TEX_FILE_EXTS


def update_file_stack(
    ln: str,
    stack: list[str | None],
    popped: list[str | None] | None = None,
) -> None:
    """单行扫 ``(``/``)`` 增量维护文件栈；非文件 ``(`` 入栈 ``None`` 保持配对。

    入栈的是字面 token（保留 ``./`` 前缀——log 原样，消费端按 endswith 用）。
    ``popped`` 非 None 时把本行弹出的栈顶按序追加——``File ended while
    scanning`` 类 runaway 错报在父文件续行位（``)`` 先于错误打印），消费端
    靠"刚弹出的文件"找回真肇事文件（#78）。
    """
    if "(" not in ln and ")" not in ln:
        return
    skip: frozenset[int] = (
        frozenset(m.start(1) for m in _MISS_CHAR_RX.finditer(ln))
        if "Missing character" in ln
        else frozenset()
    )
    j = 0
    while j < len(ln):
        c = ln[j]
        if j in skip:
            j += 1
        elif c == "(":
            m = _OPEN_TOKEN_RX.match(ln, j + 1)
            if m and looks_like_tex_file(m.group(0)):
                stack.append(m.group(0))
                j = m.end()
                continue
            stack.append(None)
            j += 1
        elif c == ")":
            if stack:
                top = stack.pop()
                if popped is not None:
                    popped.append(top)
            j += 1
        else:
            j += 1


def file_stack_at(lines: list[str], stop: int) -> list[str]:
    """重放 ``lines[:stop]`` 的文件栈，取 stop 行处仍打开的文件名序列。"""
    stack: list[str | None] = []
    for ln in lines[:stop]:
        update_file_stack(ln, stack)
    return [s for s in stack if s]


#: 系统 texmf/bundle 树路径标记——``root`` 缺席时绝对路径的归因兜底。
#: 段内含 ``texmf``（``texmf-dist``/``_texmf`` usertree/``~/texmf``）或
#: Tectonic bundle 缓存均判系统侧——注意 fixloop usertree 落在
#: ``wdir/_texmf``（root 之内仍是系统语义），故本标记先于 root 前缀判。
#: 大小写敏感：``Tectonic`` 只认 canonical 大写缓存目录名——小写
#: ``tectonic/`` 恰是 fixloop 编译工作段名（``wdir/tectonic``），误吃会把
#: 工程件错判系统。
_SYS_TREE_RX: Final = re.compile(r"[^/]*texmf[^/]*/|/Tectonic/")


def is_project_file(token: str | None, root: Path | None = None) -> bool:
    """文件栈 token → 工程文件判定（invalid_utf8 类红线按产生者归因用）。

    相对 token（``./x``/``sec/y``）= cwd 相对即工程内；绝对路径先看 texmf
    标记再按 ``root`` 前缀判（root 给定时界外即系统——沙箱 root=wdir，
    工程件不可能在其外）。裸名是 tectonic bundle 日志形态：``root`` 给定
    按 ``root/token`` 存在性分（bundle 件不在工程树），缺席时保守归工程
    ——不可归因不掉红线。
    """
    if token is None:
        return True
    if "/" not in token:
        return root is None or (root / token).is_file()
    if not token.startswith("/"):
        return True
    if _SYS_TREE_RX.search(token):
        return False
    return root is None or Path(token).resolve().is_relative_to(Path(root).resolve())
