"""actions._actions_rewrite — ``regex_rewrite`` 替换机制 (C5 拆叶)。

``_bounded_sub``/``_masked_sub`` 时限替换原语 (病态回溯超时归一
``None``), ``_patch_files`` 逐文件批量改写，``_compile_rewrites``
yaml ``rewrites[]`` 条目 → ``(pattern, repl|fn, masked)`` 三元组编译。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import regex

from texlate.compile.fixloop import builtins
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from texlate.compile.fixloop.engine import LoopCtx

#: 单次 ``pat.sub`` 硬顶（秒）——病态回溯超此即弃守该条替换。
_SUB_TIMEOUT_S = 20.0


def _bounded_sub(
    pat: regex.Pattern[str],
    repl: str | Callable[[regex.Match[str]], str],
    text: str,
    *,
    timeout_s: float = _SUB_TIMEOUT_S,
) -> str | None:
    """``pat.sub`` 时限包裹：超时 ``TimeoutError`` 归一成 ``None``。

    ``regex`` 引擎在匹配环内查 deadline——超时真中断、无残留线程。
    旧 stdlib ``re`` + daemon-thread 弃守形实证失效：泄漏 spinner 在
    C 层回溯不放 GIL，整进程冻结（guardsmoke fixloop 格 Thread-4
    utime 29min、worker 全 GIL 饿死、子进程僵死不收，2026-09-18）。
    ``regex`` 还自带部分病态形免疫（``(x+x+)``/``([a-zA-Z]+)*`` 线性过）。
    """
    try:
        return pat.sub(repl, text, timeout=timeout_s)
    except TimeoutError:
        return None


def _masked_sub(
    pat: regex.Pattern[str],
    repl: str | Callable[[regex.Match[str]], str],
    text: str,
    *,
    timeout_s: float = _SUB_TIMEOUT_S,
) -> str | None:
    r"""``match_surface: masked`` 替换——等长遮盖面匹配 + span 回切原文。

    在 ``mask_tex`` 等长视图上 finditer, 命中 span 右→左拼回原文
    (replacement 变长不漂后续 offset)。注释/逐字/失活区在视图中是等长
    空白——pattern 的必要内容无法锚在其中 (natbib_numbers_pass 注释行
    ``\\begin{document}`` 裂伤类的根修); repl 展开读视图 group——命中区
    全在活面时与原文逐字节一致, 跨遮盖区的野 span 按原文 span 替换
    (作者自担 pattern 形状)。超时归一 ``None``, 与 ``_bounded_sub`` 同约。
    """
    try:
        matches = list(pat.finditer(mask_tex(text), timeout=timeout_s))
        for m in reversed(matches):
            piece = repl(m) if callable(repl) else m.expand(repl)
            text = text[: m.start()] + piece + text[m.end() :]
    except TimeoutError:
        return None
    else:
        return text


def _patch_files(
    ctx: LoopCtx,
    exts: Iterable[str],
    subs: list[tuple[regex.Pattern[str], Any, bool]],
    rule_id: str = "",
) -> int:
    """对全部匹配文件做 ``pattern→repl|function`` 替换; 返回改动文件数 (原型)。"""
    n = 0
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None:
            continue
        nt = t
        for pat, repl, masked in subs:
            nxt = _masked_sub(pat, repl, nt) if masked else _bounded_sub(pat, repl, nt)
            if nxt is None:
                ctx.events.append(
                    f"rewrite_timeout {rule_id}: {pat.pattern[:80]!r} on {f}"
                )
                continue
            nt = nxt
        if nt != t:
            ctx.write(f, nt)
            n += 1
    return n


def _compile_rewrites(
    rewrites: list[dict[str, Any]],
) -> list[tuple[regex.Pattern[str], Any, bool]]:
    """Rewrite 条目 → ``(pattern, repl|fn, masked)`` 三元组。

    ``match_surface: masked`` 是逐条 opt-in——缺席/其他值走原文 ``sub``,
    既有规则零行为差 (ruleset 装载侧已把非法值拦成 RulesetError)。
    """
    subs = []
    for rw in rewrites:
        flags = 0
        for fl in rw.get("flags") or []:
            flags |= getattr(regex, fl, getattr(re, fl, 0))
        pat = regex.compile(rw["pattern"], flags)
        masked = rw.get("match_surface") == "masked"
        if "function" in rw:
            subs.append((pat, builtins.REWRITE_FNS[rw["function"]], masked))
        else:
            subs.append((pat, rw.get("repl", ""), masked))
    return subs
