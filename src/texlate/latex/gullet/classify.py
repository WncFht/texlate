r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：体分类（math/opaque 判定）。"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
)

from texlate.latex.macro_table import (
    body_has_text,
    classify_body,
    protected_param_positions,
)
from texlate.latex.model import (
    MacroKind,
)

from .tables import (
    _MATH_CS,
)
from .tokutil import (
    _bare_cs,
    _has_at_cs,
    _surface,
)

if TYPE_CHECKING:
    from texlate.latex.mouth import (
        Tok,
    )


class _Classify:
    # ------------------------------------------------------------ 分类

    def _classify(
        self, body: list[Tok], nargs: int
    ) -> tuple[str, str, tuple[bool, ...]]:
        r"""定义时分类（§6.1 + §6.2 二分）。

        ``env_begin/env_end`` → ``classify_body`` 表面全匹配；
        无文本 → ``math``（含数学特征）/``opaque``；
        有文本 → ``transparent_expand``（体去 ``#i`` 位仍有文本）
        /``transparent_inline``。
        """
        surf = _surface(body)
        mk, target = classify_body(surf)
        if mk is MacroKind.ENV_BEGIN:
            return "env_begin", target, ()
        if mk is MacroKind.ENV_END:
            return "env_end", target, ()
        if _has_at_cs(body):
            return "opaque", "", ()
        if not body_has_text(surf):
            if _bare_cs(body) is not None:
                # 体=单枚 cs 的纯别名（\nc→\newcommand）：opaque 会让调用点
                # 交出本体、目标 primitive/宏永不执行——回吐走正常分派
                return "transparent_expand", "", ()
            return ("math" if self._has_math(body) else "opaque"), "", ()
        rest = _surface(self._strip_param_refs(body))
        kind = "transparent_expand" if body_has_text(rest) else "transparent_inline"
        return kind, "", protected_param_positions(surf, nargs)

    @staticmethod
    def _has_math(body: list[Tok]) -> bool:
        r"""体含数学特征：``$``/``^``/``_``/``\(``/``\[``/数学 cs 名。"""
        for t in body:
            if t.kind == "mathshift":
                return True
            if t.kind == "cs" and t.text in _MATH_CS:
                return True
            if t.kind != "cs" and t.text in ("^", "_"):
                return True
        return False

    @staticmethod
    def _strip_param_refs(body: list[Tok]) -> list[Tok]:
        """去 ``#n`` 参数引用对（§6.2 判据：体文本是否全经参数位进入）。"""
        out: list[Tok] = []
        i, n = 0, len(body)
        while i < n:
            t = body[i]
            if t.kind == "param" and i + 1 < n and body[i + 1].text.isdigit():
                i += 2
                continue
            out.append(t)
            i += 1
        return out
