r"""遮蔽视图与 TeX 词法小件：normalize/inject 所有正则定位都打在这里。

方法论（docs/08 §3.1）：`visible_tex()` 把 verbatim 族环境、`\verb`、行内 `%`
注释做**等长空格遮盖**（`\n` 保留 → 行号与 offset 不变），调用方在视图上定位、
回原文做 span 编辑。**定位视图 ≠ 改写目标**——masked view 绝不能拷回原文，
否则注释行变空行、跨行参数被劈断。

移植自 texglot `app/sources.py`/`app/latex.py`（Apache-2.0，模式借用），
配套证据 docs/research/latex/texglot-patterns.md §1.0。
"""

from __future__ import annotations

import re

#: 归一化层逐文件手术的扩展名集（.tex 之外，作者自带 .sty/.cls 同样要改）。
TEX_SOURCE_SUFFIXES = {".tex", ".sty", ".cls", ".cfg", ".def", ".clo", ".fd", ".ltx"}

#: 逐字环境：内容不做任何手术、不做翻译，整段遮盖。
VERBATIM_ENVS = (
    "verbatim",
    "verbatim*",
    "Verbatim",
    "lstlisting",
    "minted",
    "filecontents",
    "filecontents*",
)

_COMMAND_RE = re.compile(r"\\(?:[a-zA-Z@]+\*?|.)", re.DOTALL)


def without_comments(text: str) -> str:
    r"""剥掉行内 `%` 注释（等长空格替代，offset 保持）。不处理 verbatim 环境。

    只用于"注释会不会骗人"语义不敏感的场景（如 `\bibliography` 名提取）；
    逐字环境敏感的场景必须用 :func:`visible_tex`。
    """
    chars = list(text)
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == "%":
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            chars[i:end] = [" "] * (end - i)
            i = end
        else:
            i += 1
    return "".join(chars)


def visible_tex(text: str, *, mask_comment_environments: bool = True) -> str:
    r"""注释 + 逐字环境的等长遮盖视图；offset/行号与原文字节级对齐。

    顺序敏感：先吃逐字环境（`\verb|%|` 里的 `%` 不是注释），再遮行内 `%`。
    `mask_comment_environments=False` 用于 comment.sty 手术自身——
    `\end{comment}` 行尾空白修复需要看见 comment 环境内部。
    """
    chars = list(text)

    def mask(start: int, stop: int) -> None:
        chars[start:stop] = ["\n" if c == "\n" else " " for c in text[start:stop]]

    i = 0
    n = len(text)
    env_alt = "|".join(VERBATIM_ENVS) + (
        "|comment" if mask_comment_environments else ""
    )
    env_re = re.compile(r"\\begin\s*\{(" + env_alt + r")\}")
    while i < n:
        if text[i] == "%":
            stop = text.find("\n", i)
            stop = n if stop < 0 else stop
            mask(i, stop)
            i = stop
            continue
        if text[i] != "\\":
            i += 1
            continue
        env = env_re.match(text, i)
        if env:
            ending = re.search(
                r"\\end\s*\{" + re.escape(env[1]) + r"\}", text[i + env.end() :]
            )
            stop = i + env.end() + ending.end() if ending else n
            mask(i, stop)
            i = stop
            continue
        inline = re.match(r"\\(verb\*?|lstinline\*?)(?![A-Za-z@])", text[i:])
        if inline:
            start = i + inline.end()
            if inline[1].startswith("lstinline"):
                options = re.match(r"\s*(?:\[[^\]\n]*\]\s*)?", text[start:])
                start += options.end()
            if start < n and not text[start].isspace():
                delimiter = text[start]
                end = text.find("}" if delimiter == "{" else delimiter, start + 1)
                newline = text.find("\n", start)
                if end >= 0 and (newline < 0 or end < newline):
                    mask(i, end + 1)
                    i = end + 1
                    continue
        command = _COMMAND_RE.match(text, i)
        i += command.end() if command else 1
    return "".join(chars)


def group_end(s: str, pos: int) -> int:
    r"""从 `s[pos]` 的 `{`/`[` 读到配对的闭括号，返回其**后**一个 offset。

    感知转义 `\{`、嵌套与 `%` 注释；找不到配对时返回 `len(s)`。
    """
    if pos >= len(s) or s[pos] not in "[{":
        return pos
    close = {"[": "]", "{": "}"}[s[pos]]
    i = pos + 1
    while i < len(s):
        if s[i] == "\\":
            m = _COMMAND_RE.match(s, i)
            i = m.end() if m else i + 2
        elif s[i] == "%":
            j = s.find("\n", i)
            i = len(s) if j < 0 else j + 1
        elif s[i] == "{":
            i = group_end(s, i)
        elif s[i] == close:
            return i + 1
        else:
            i += 1
    return len(s)


def apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    """逆序回放 `(start, end, replacement)` 编辑列表；删除类编辑补回换行保行号。"""
    for start, end, replacement in sorted(edits, reverse=True):
        newlines = text[start:end].count("\n") - replacement.count("\n")
        text = text[:start] + replacement + "\n" * newlines + text[end:]
    return text


def decode_tex(blob: bytes) -> str:
    """解码 arXiv 源码：UTF-8(BOM) → gb18030 → cp1252 → latin-1 兜底链。

    latin-1 永不失败——latin-5/latin-9 源会带 U+FFFD 风险留给编译层
    `Invalid UTF-8 byte` 判据兜底（docs/08 §4.3）。
    """
    for encoding in ("utf-8-sig", "gb18030", "cp1252", "latin-1"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    return blob.decode("utf-8", errors="replace")
