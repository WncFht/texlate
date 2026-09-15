r"""LaTeX 源码文本工具：注释剥离（\% 转义 / verbatim / comment 环境感知）。

供 sniff（pdf_wrapper 检测）与 locate（documentclass / \input 匹配）共用。
口径见 docs/research/corpus/corpus39-profile.md：逐行剥注释，奇数前导 \ 的
\% 视为转义不剥。
"""

from __future__ import annotations

import re
from typing import Final

# verbatim 族：内部 % 不是注释，内容原样保留（stub 文本计数需要它们）。
_VERBATIM_ENVS: Final = (
    "verbatim",
    "lstlisting",
    "minted",
    "Verbatim",
    "BVerbatim",
    "LVerbatim",
    "lstpython",
)
# comment 宏包环境：TeX 整体跳过——其中的 \documentclass 不生效，内容清空。
_DEAD_ENVS: Final = ("comment",)
_ALL_ENVS: Final = _VERBATIM_ENVS + _DEAD_ENVS
_BEGIN_ENV_RE: Final = re.compile(
    r"\\begin\{(" + "|".join(re.escape(e) for e in _ALL_ENVS) + r")\*?\}"
)


def _env_end_re(env: str) -> re.Pattern[str]:
    return re.compile(r"\\end\{" + re.escape(env) + r"\*?\}")


def _strip_line(line: str) -> str:
    r"""剥单行注释：遇未转义 % 截断；\verb|…| 区段内 % 不剥。"""
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\":
            # \verb<delim>…<delim> 或 \verb*<delim>…<delim>：区段内 % 原样
            if line.startswith("\\verb", i):
                j = i + 5
                if j < n and line[j] == "*":
                    j += 1
                if j < n and line[j] not in "{\\ \t":
                    delim = line[j]
                    k = line.find(delim, j + 1)
                    i = n if k < 0 else k + 1
                    continue
            i += 2  # 控制序列/转义字符：跳过下一个字符（\\% 由此免疫）
            continue
        if ch == "%":
            return line[:i]
        i += 1
    return line


def strip_comments(text: str) -> str:
    r"""剥注释，保持行数不变（行内截断，不删行）。

    - 未转义 ``%`` 到行尾剥除；``\%``（奇数前导反斜杠）不剥。
    - verbatim 族环境内部不剥 %（% 在其中是字面字符）。
    - comment 环境内容整体失活（其中的 ``\documentclass`` 不算数）。
    - ``\verb|…|`` 行内区段不剥。
    """
    out: list[str] = []
    active_env: str | None = None
    end_re: re.Pattern[str] | None = None
    for line in text.split("\n"):
        if active_env is not None:
            # \end{env} 出现即退出；\end 行自身及之前的内部行按环境语义处理
            hit_end = end_re is not None and end_re.search(line)
            if active_env in _DEAD_ENVS:
                out.append("")  # comment 环境：内容整行清空
            else:
                out.append(line)
            if hit_end:
                active_env = None
                end_re = None
            continue
        stripped = _strip_line(line)
        m = _BEGIN_ENV_RE.search(stripped)
        if m:
            active_env = m.group(1)
            end_re = _env_end_re(active_env)
            if active_env in _DEAD_ENVS:
                stripped = ""  # \begin{comment} 行：\begin 之后内容也失活
        out.append(stripped)
    return "\n".join(out)
