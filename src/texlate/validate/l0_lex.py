"""validate.l0_lex — L0 词法层 + 共享视图叶 (validate.l0 域缝叶)。

``_lex`` 逐字符 ``(kind, text, pos)`` 三元组扫描：``cs`` 控制字 /
``bs`` 控制符号 / ``cmt`` 注释 / ``ch`` 其余字符——只做转义/注释豁免，
刻意不做解析（校验器异构原则，pylatexenc 静默截断的教训）。
``_Ctx`` 是 ``(src, zh)`` 校验对的共享预处理视图缓存：lex/masked/
prose/est 每视图每对惰性派生只算一次，全 checker 叶统一入参。
"""

from __future__ import annotations

import re
from functools import cached_property
from typing import TYPE_CHECKING

from texlate.textutil import est_tokens as _est_tokens
from texlate.textutil import mask_comments
from texlate.textutil import prose_text as _prose

if TYPE_CHECKING:
    from texlate.validate.l0_report import Issue


def _lex(s: str) -> list[tuple[str, str, int]]:
    r"""逐字符扫出 ``(kind, text, pos)`` 三元组。

    kind：``cs`` 控制字（不含反斜杠）、``bs`` 控制符号（``\\`` + 单字符，
    含 ``\\{`` ``\\%`` ``\\ ``）、``cmt`` 注释、``ch`` 其余字符。
    不做解析，只做转义/注释豁免——校验器刻意不依赖完整语法。
    """
    out: list[tuple[str, str, int]] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "%":
            nl = re.search(r"[\r\n]", s[i:])
            j = n if nl is None else i + nl.start()
            out.append(("cmt", s[i:j], i))
            i = j
            continue
        if c == "\\":
            j = i + 1
            if j < n and s[j].isalpha():
                k = j
                while k < n and (s[k].isalpha() or s[k] == "@"):
                    k += 1
                out.append(("cs", s[j:k], i))
                i = k
                continue
            j2 = min(i + 2, n)
            out.append(("bs", s[i:j2], i))
            i = j2
            continue
        out.append(("ch", c, i))
        i += 1
    return out


class _Ctx:
    """``(src, zh)`` 校验对的共享预处理视图缓存（``_CHECKERS`` 入参）。

    各 checker 曾按 ``(src, zh, issues)`` 签名各自重推同一批词法/遮盖/
    散文视图（每对 ``_lex`` ×13、``mask_comments`` ×9、``_prose`` ×4）；
    全部改为随本对象惰性派生——每视图每对只算一次，未消费的侧不付成本。
    """

    def __init__(self, src: str, zh: str, issues: list[Issue]) -> None:
        """记下双侧原文与共享 issues 槽；视图全部惰性。"""
        self.src = src
        self.zh = zh
        self.issues = issues

    @cached_property
    def lex_src(self) -> list[tuple[str, str, int]]:
        r"""``_lex(src)``——注释区整体是 ``cmt`` token，区内 ``\foo`` 本就不入 cs 计数。"""
        return _lex(self.src)

    @cached_property
    def lex_zh(self) -> list[tuple[str, str, int]]:
        """``_lex(zh)``."""
        return _lex(self.zh)

    @cached_property
    def masked_src(self) -> str:
        """``mask_comments(src)`` 等长遮盖视图。"""
        return mask_comments(self.src)

    @cached_property
    def masked_zh(self) -> str:
        """``mask_comments(zh)`` 等长遮盖视图。"""
        return mask_comments(self.zh)

    @cached_property
    def prose_src(self) -> str:
        """``prose_text(src)`` 剥占位符/cs 后的散文本体（length/same_source 共用）。"""
        return _prose(self.src)

    @cached_property
    def prose_zh(self) -> str:
        """``prose_text(zh)``."""
        return _prose(self.zh)

    @cached_property
    def est_src(self) -> float:
        """``est_tokens(prose_src)``——大小写不变量（CJK 数 + 非空白数），``ss.lower()`` 视图同值。"""
        return _est_tokens(self.prose_src)

    @cached_property
    def est_zh(self) -> float:
        """``est_tokens(prose_zh)``."""
        return _est_tokens(self.prose_zh)
