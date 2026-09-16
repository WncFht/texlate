r"""LaTeX 源码文本工具：注释剥离（\% 转义 / verbatim / comment 环境感知）。

供 sniff（pdf_wrapper 检测）与 locate（documentclass / \input 匹配）共用。
口径见 docs/research/corpus/corpus39-profile.md：逐行剥注释，奇数前导 \ 的
\% 视为转义不剥。

实现单源在 ``texlate.textutil.mask_tex``（等长遮盖视图）——本模块在其上
逐行 rstrip 还原"剥除"形态，只为定位/搜索消费，offset 语义不需要。
"""

from __future__ import annotations

from texlate.textutil import mask_tex


def strip_comments(text: str, *, keep_verbatim: bool = True) -> str:
    r"""剥注释，保持行数不变（行内截断，不删行）。

    - 未转义 ``%`` 到行尾剥除；``\%``（奇数前导反斜杠）不剥。
    - verbatim 族环境内部不剥 %（% 在其中是字面字符）。
    - comment 环境内容整体失活（其中的 ``\documentclass`` 不算数）。
    - ``\verb|…|``/``\lstinline|…|`` 行内区段不剥。

    ``keep_verbatim=False`` 时 verbatim 族环境体一并遮盖——``\input``/
    ``\documentclass``/``\bibliography`` 在逐字面里不执行，候选与 include
    拓扑需要一个不掺假的代码视图（TeX 示例 listing 会把假候选喂进裁决）。
    计数类消费（pdf_wrapper 正文含量）仍用默认 True 保字面量。
    """
    return "\n".join(
        line.rstrip()
        for line in mask_tex(text, keep_verbatim=keep_verbatim).split("\n")
    )
