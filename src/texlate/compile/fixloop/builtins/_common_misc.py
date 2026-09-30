r"""builtins._common_misc — 引擎索引查包 + advisory 记账 + 词法小件 (common 拆分)。

``_index_candidates`` (``filemap`` + ``ctan_fetch.peek_index`` 索引查包链,
自 actions.py/builtins.vendored 归位) / ``_advise`` 幂等 advisory 记账 /
``_skip_ws``/``_brace_end`` 可视流词法 / ``_read_utf8`` 树外件直读。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = [
    "_advise",
    "_brace_end",
    "_index_candidates",
    "_read_utf8",
    "_skip_ws",
]


def _index_candidates(eng: Engine, fname: str, *, suggest: bool = False) -> list[str]:
    """``filemap`` + ``ctan_fetch.peek_index`` 索引查包链 (``builtins.vendored._index_providers`` 同构)。

    ``suggest=True`` 时 ``query`` 空集再退 ``suggest`` 前缀猜测——候选提示
    面可宽; 遮蔽佐证面 (``_index_providers``) 应保持默认 ``False`` 只收精确命中。
    """
    pkgs = list(eng.filemap(fname))
    if not pkgs:
        fetcher = getattr(eng, "ctan_fetch", None)
        peek = getattr(fetcher, "peek_index", None)
        idx = peek() if callable(peek) else None
        if idx is not None:
            pkgs = idx.query(fname)
            if suggest and not pkgs:
                pkgs = idx.suggest(fname.rsplit(".", 1)[0])
    return pkgs


def _advise(ctx: LoopCtx, adv: str) -> None:
    """幂等 advisory 记账 —— 同文条目不重复落 ``ctx.ledger.advisories``。

    ``ctx.advisories`` 经 ``LoopCtx.__getattr__`` 转发到 ``ctx.ledger.advisories``
    (engine.py forward 表 ``"advisories": "ledger"``), 两写形同列表 ——
    actions.py 与 builtins/vendored.py 两侧同构副本的单源。
    """
    if adv not in ctx.advisories:
        ctx.advisories.append(adv)


def _skip_ws(vis: str, pos: int) -> int:
    r"""``" \t"`` 空白跳过 → 首个非空白位 (mask 后可视流词法; optfix 叶另有含 ``\\n`` 变体)。"""
    while pos < len(vis) and vis[pos] in " \t":
        pos += 1
    return pos


def _brace_end(vis: str, pos: int) -> int:
    r"""``vis[pos]=='{'`` → 配对 ``}`` 后 offset; 未配对 → ``len(vis)``。"""
    depth, j = 1, pos + 1
    while j < len(vis) and depth:
        c = vis[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        j += 1
    return j


def _read_utf8(f: Path) -> str:
    """utf-8 直读 (指纹探测用, 树外件不走 ctx 缓存); 不可读 → ``""``。"""
    try:
        return f.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
