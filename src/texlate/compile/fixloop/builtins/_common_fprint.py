r"""builtins._common_fprint — 注入件指纹闸 (common 拆分)。

b3a 工单 (无版本/hash 闸, 留存旧 stub 无辨 —— hep-ph/0408075 espcrc2
跨 rerun 实证): 本引擎写出的 stub/shim 件携 sha1(body→sha256) 指纹;
盘上同名片四分判 ``absent``/``current``/``stale``/``foreign``。
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

from texlate.compile.fixloop.builtins._common_misc import _advise

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.fixloop.engine import LoopCtx

__all__ = [
    "_FINGERPRINT_RE",
    "_LEGACY_INJECTED_HEADS",
    "_fingerprint",
    "_inject_write",
    "_injected_state",
    "_mark_injected",
    "hashlib",
]

#: 注入件指纹行——本引擎写出的 stub/shim 件携 sha1(body) 指纹; 盘上同名
#: 片三分判：指纹匹配=本代已注入 (跳), 失配/旧代标记=旧注入件 (覆写刷新),
#: 全无名分=外来件 (稿自带/真包——不覆写，advisory)。
_FINGERPRINT_RE = re.compile(
    r"^% texlate-fixloop-injected: ([0-9a-f]{12})$", re.MULTILINE
)
#: 旧代注入件的行头标记（指纹闸引入前所写 stub 的认亲面）。
_LEGACY_INJECTED_HEADS = ("% texlate vendored stub", "% fixloop:")


def _fingerprint(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:12]


def _mark_injected(body: str) -> str:
    return f"% texlate-fixloop-injected: {_fingerprint(body)}\n{body}"


def _injected_state(target: Path, body: str) -> str:
    """同名片四分判：``absent``/``current``/``stale``/``foreign``。"""
    try:
        old = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "absent"
    m = _FINGERPRINT_RE.search(old)
    if m is None:
        head = old.lstrip()[:200]
        if head.startswith(_LEGACY_INJECTED_HEADS):
            return "stale"
        return "foreign"
    return "current" if m.group(1) == _fingerprint(body) else "stale"


def _inject_write(
    ctx: LoopCtx, target: Path, body: str, name: str
) -> tuple[tuple[bool, str] | None, str]:
    r"""同名片指纹闸 + 带指纹写盘 (``ctx.write`` 同步读缓存)。

    短路终局 ``((bool, note), state)`` 直冒泡：``foreign`` → 记 advisory +
    False (稿自带/真包件永不覆写)；``current`` → True 免重写；OSError →
    False。``absent``/``stale`` 写完返 ``(None, state)``——调用方据 state
    拼成功 note (``stale`` 供 "refreshed" 措辞位)。
    """
    state = _injected_state(target, body)
    if state == "foreign":
        _advise(ctx, f"{name}: foreign file present, inject skipped")
        return (False, f"{name} present (foreign) — inject skipped"), state
    if state == "current":
        return (True, f"{name} already current"), state
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        ctx.write(target, _mark_injected(body))
    except OSError as e:
        return (False, f"{name} write failed: {e}"), state
    return None, state
