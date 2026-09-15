r"""文本小件单源 —— 转义感知注释遮盖 + 封顶 Levenshtein。

``mask_comments``：``\`` 后随字符整体跳过（``\%``/``\\%`` 语义正确），
未转义 ``%`` 到行尾替换为等长空格——offset/长度与原文逐字节对齐，
供正则/下标直接使用。**不处理 verbatim 环境**——逐字敏感场景用
``compile.mask.visible_tex``（先吃 ``\verb``/verbatim env 再遮注释）。

``lev_capped``：带 early-exit 上限的 Levenshtein——L0 占位符拼写配对与
xlat 轻量对账共用一个实现，防两份 DP 各自漂移。
"""

from __future__ import annotations

__all__ = ["lev_capped", "mask_comments"]


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


def lev_capped(a: str, b: str, cap: int) -> int:
    """Levenshtein 距离，超 cap 提前返回 cap+1。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        rowmin = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            rowmin = min(rowmin, v)
        if rowmin > cap:
            return cap + 1
        prev = cur
    return prev[-1]
