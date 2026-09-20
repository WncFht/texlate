r"""遮蔽视图与 TeX 词法小件：normalize/inject 所有正则定位都打在这里。

方法论（docs/spec/compile.md）：`visible_tex()` 把 verbatim 族环境、`\verb`、行内 `%`
注释做**等长空格遮盖**（`\n` 保留 → 行号与 offset 不变），调用方在视图上定位、
回原文做 span 编辑。**定位视图 ≠ 改写目标**——masked view 绝不能拷回原文，
否则注释行变空行、跨行参数被劈断。

移植自 texglot `app/sources.py`/`app/latex.py`（Apache-2.0，模式借用），
配套证据 docs/research/latex/texglot-patterns.md §1.0。
"""

from __future__ import annotations

import re

from texlate.textutil import mask_comments, mask_tex

#: 归一化层逐文件手术的扩展名集（.tex 之外，作者自带 .sty/.cls 同样要改）。
TEX_SOURCE_SUFFIXES = {".tex", ".sty", ".cls", ".cfg", ".def", ".clo", ".fd", ".ltx"}

_COMMAND_RE = re.compile(r"\\(?:[a-zA-Z@]+\*?|.)", re.DOTALL)
_NL_RE = re.compile(r"[\r\n]")


def without_comments(text: str) -> str:
    r"""剥掉行内 `%` 注释（等长空格替代，offset 保持）。不处理 verbatim 环境。

    只用于"注释会不会骗人"语义不敏感的场景（如 `\bibliography` 名提取）；
    逐字环境敏感的场景必须用 :func:`visible_tex`。
    """
    return mask_comments(text)


def visible_tex(text: str, *, mask_comment_environments: bool = True) -> str:
    r"""注释 + 逐字环境的等长遮盖视图；offset/行号与原文字节级对齐。

    实现单源在 :func:`texlate.textutil.mask_tex`。
    `mask_comment_environments=False` 用于 comment.sty 手术自身——
    `\end{comment}` 行尾空白修复需要看见 comment 环境内部。
    """
    return mask_tex(text, mask_dead=mask_comment_environments)


def group_end(s: str, pos: int) -> int:
    r"""从 `s[pos]` 的 `{`/`[` 读到配对的闭括号，返回其**后**一个 offset。

    感知转义 `\{`、嵌套与 `%` 注释；找不到配对时返回 `len(s)`。
    """
    if pos >= len(s) or s[pos] not in "[{":
        return pos
    # 显式栈迭代配对（原递归实现深嵌套 { 撞 RecursionError）：`{` 恒压 `}`、
    # `[` 仅最外层可作 opener，闭括号只看栈顶期望。
    closers = ["]" if s[pos] == "[" else "}"]
    i = pos + 1
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = _COMMAND_RE.match(s, i)
            i = m.end() if m else i + 2
        elif c == "%":
            m = _NL_RE.search(s, i)
            i = len(s) if m is None else m.start() + 1
        elif c == "{":
            closers.append("}")
            i += 1
        elif c == closers[-1]:
            closers.pop()
            if not closers:
                return i + 1
            i += 1
        else:
            i += 1
    return len(s)


def apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    """逆序回放 `(start, end, replacement)` 编辑列表；删除类编辑补回换行保行号。"""
    for start, end, replacement in sorted(edits, reverse=True):
        newlines = text[start:end].count("\n") - replacement.count("\n")
        text = text[:start] + replacement + "\n" * newlines + text[end:]
    return text
