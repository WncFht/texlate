r"""``latex.tables_colspec`` — 列型前导启发（``tables`` god-file 机械拆分叶）。

未注册环境 ``\\begin{env}{preamble}`` 第一参的列型判据：剥 cs 名与
内层花括号组（``*{n}{spec}`` 先解卷）后只剩列型字符且含列型字母 →
判列参吃掉。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- 列型前导启发

_COLSPEC_CS_RX = re.compile(r"\\[a-zA-Z@]+\*?|\\.")
#: 剥内层花括号组——``*`` 紧随的 ``{n}`` 是 array-repeat 计数，剥了 ``*``
#: 成孤儿、star 配对永死（``*{2}{p{3cm}}`` 剥 ``{2}`` 后 spec 不再可达）。
_COLSPEC_GROUP_RX = re.compile(r"(?<!\*)\{[^{}]*\}")
#: array-repeat ``*{n}{spec}``：``{spec}`` 组剥空前先解卷——列字母全在
#: 被剥组内会让纯 ``*`` 重复型漏判（``{*{3}{c}|l}`` → ``*|l`` 无列字母）。
#: 解卷只需一份 spec 内容（判型不判展开次数）；``[^{}]*`` 界使内层
#: ``*{m}{…}`` 先匹配、不动点迭代逐层外卷。
_COLSPEC_STAR_RX = re.compile(r"\*\{\d+\}\{([^{}]*)\}")
# 列型字母族：array ``lcrpmb`` + tabularx ``X`` + ragged2e ``LCRJ`` +
# dcolumn ``D`` + siunitx ``Ss`` + array ``wW``；修饰 ``|><@!*`` 与
# dcolumn 数字/标点载荷（``D{,}{.}{2}`` 内组剥空后残留位）。
_COLSPEC_COLS = frozenset("lcrpmbXLCRJDwWs")
_COLSPEC_CHARS = _COLSPEC_COLS | frozenset("|><@!*.,:;-+= \t0123456789")


def looks_like_colspec(content: str) -> bool:
    r"""``{...}`` 参内容是否形似列型前导（``{cc}``/``{>{\raggedright}p{4cm}}`` 族）。

    未注册环境 ``\begin{env}{preamble}`` 的第一参：剥掉 cs 名与内层
    花括号组后只剩列型字符且含至少一个列型字母 → 判列参吃掉；否则
    回吐随主流进 chunk。``*{n}{spec}`` 纯重复型先解卷 spec 再走同判。
    ``{Title}`` 形含表外字母自然落空；``{c}``/``{l}`` 单字母文本参是
    已知误伤面（代价低于列参裸泄，罕见——真 ``tabular`` 族走
    ``ENV_MANDATORY_ARG`` 不经此路）。
    """
    s = _COLSPEC_CS_RX.sub("", content)
    while True:
        # star 解卷优先——同迭代剥组会吃掉刚解出的 spec 组（``*{2}{cl}``
        # 中态），嵌套 ``*{m}{…}`` 须等多一轮才能被 star 看见；
        # ``*{n}`` 的计数组不剥（剥了 ``*`` 成孤儿，star 配对永死）
        s2 = _COLSPEC_STAR_RX.sub(r"\1", s)
        if s2 != s:
            s = s2
            continue
        s3 = _COLSPEC_GROUP_RX.sub("", s)
        if s3 == s:
            break
        s = s3
    s = s.strip()
    if not s or any(c not in _COLSPEC_CHARS for c in s):
        return False
    return any(c in _COLSPEC_COLS for c in s)
