r"""TeX 文本遮盖原语 —— 转义感知注释遮盖的单源实现。

``mask_comments``：``\`` 后随字符整体跳过（``\%``/``\\%`` 语义正确），
未转义 ``%`` 到行尾替换为等长空格——offset/长度与原文逐字节对齐，
供正则/下标直接使用。**不处理 verbatim 环境**——逐字敏感场景用
``compile.mask.visible_tex``（先吃 ``\verb``/verbatim env 再遮注释）。
"""

from __future__ import annotations

__all__ = ["mask_comments"]


def mask_comments(text: str) -> str:
    r"""``%`` 到行尾等长空格遮盖；``\`` 后随字符整体跳过。保位不保内容。"""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "%":
            j = i
            while j < n and text[j] != "\n":
                out[j] = " "
                j += 1
            i = j
            continue
        i += 1
    return "".join(out)
