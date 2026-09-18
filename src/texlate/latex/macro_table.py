r"""宏体分类 + argspec 编译：gullet/segmenter 共享的登记侧 helper（docs/07 §5）。

分类在**登记时**一次完成，调用点只查表（§5.1）：

- ``body`` 整体是 ``\begin{X}`` → ENV_BEGIN(X)；``\end{X}`` → ENV_END(X)
- body 无自然文本（去命令/参数后无 ≥2 连续字母）→ OPAQUE
- 否则 → TRANSPARENT，``protect_args`` 标记落在 ``\ref/\cite/\label/\url``
  参数位的 ``#i``（调用点该位 → ``[[KEY]]``）
"""

from __future__ import annotations

import re

from texlate.latex.model import ArgSpec, MacroKind, ws_skip
from texlate.latex.tables import PROTECTED_PARAM_CMDS

_ENV_BEGIN_RX = re.compile(r"\\begin\{([^}]*)\}")
_ENV_END_TAIL_RX = re.compile(r"\\end\{([^}]*)\}\s*$")
# ``\csname endX\endcsname`` 整体形——LaTeX ``\end{X}`` 内核即展开成
# ``\endX``，故包它的宏（``\def\eea{\csname endeqnarray\endcsname}``）
# 语义上就是 env_end 端点（R1：token 层 ``x.text=="end"+target`` 同规
# 的表侧入口——csname 合成不经宏体表，不登记则配对扫描永远看不见它）。
_CSNAME_END_RX = re.compile(r"\\csname\s*end([a-zA-Z@*]+)\s*\\endcsname")
_STRIP_PARAM_RX = re.compile(r"#[1-9]?")
_STRIP_CS_RX = re.compile(r"\\[a-zA-Z@]+\*?")
_STRIP_CS1_RX = re.compile(r"\\[^a-zA-Z]")
_NONALPHA_RX = re.compile(r"[^a-zA-Z]")
_WORD_RX = re.compile(r"[a-zA-Z]{2,}")
_PARAM_TOK_RX = re.compile(r"\\[a-zA-Z@]+\*?|#[1-9]|[{}\[\]]")


def body_has_text(body: str) -> bool:
    """宏体是否含自然文本（去命令/参数记号后 ≥2 连续字母）。"""
    s = _STRIP_PARAM_RX.sub(" ", body)
    s = _STRIP_CS_RX.sub(" ", s)
    s = _STRIP_CS1_RX.sub(" ", s)
    s = _NONALPHA_RX.sub(" ", s)
    return bool(_WORD_RX.search(s))


def protected_param_positions(body: str, nargs: int) -> tuple[bool, ...]:  # noqa: C901 — token 流状态机，平铺即分派表
    r"""``#i`` 落在 ``\ref/\cite/\label/\url`` 等命令参数位 → 该参数保护。

    保护以组界为界：``\cite{#1}`` 的保护域止于配对 ``}``——
    ``\cite{#1} and #2`` 的 ``#2`` 不继承（audit C5：旧实现保护位
    只被下一枚 cs 复位，跨 ``}`` 泄漏把纯文本位误标 ``[[KEY]]``，
    调用点该参数永不进 chunk）。``[..]`` 可选参同样是参数位
    （``\includegraphics[#1]{#2}`` 两位皆保护），裸 token 参
    （``\cite#1``）消费一枚即止。
    """
    flags = [False] * nargs
    if nargs == 0:
        return ()
    armed = False  # 保护 cs 已见、参数未消费
    bracket = 0  # armed 期间 [..] 嵌套深度（可选参内 #i 亦保护且不吃 armed）
    gprot: list[bool] = []  # 各层 { 组是否为保护参组（栈，外层保护罩内层）
    for m in _PARAM_TOK_RX.finditer(body):
        tok = m.group(0)
        if tok == "{":
            gprot.append(armed)
            armed = False
        elif tok == "}":
            if gprot:
                gprot.pop()
            armed = False
        elif tok == "[":
            bracket += 1
        elif tok == "]":
            bracket = max(bracket - 1, 0)
        elif tok[0] == "#":
            idx = int(tok[1]) - 1
            # 体引用超出 spec 的 #k（嵌套 \def 的 ##k、笔误 #9）→ 无位可标，跳过不抛
            if idx < nargs and (armed or any(gprot)):
                flags[idx] = True
            if armed and not bracket:
                armed = False  # 裸 token 参消费一枚
        else:
            # cs 自身亦可作单 token 参（\cite\foo）：先消费再按名重挂
            armed = tok.lstrip("\\").rstrip("*") in PROTECTED_PARAM_CMDS
    return tuple(flags)


def classify_body(body: str) -> tuple[MacroKind, str]:
    r"""``\\begin{X}`` 全匹配 / ``\\end{X}`` 尾匹配 → 端点宏。

    env_end 放宽为**尾匹配**（R7）：端点宏真实形态常带收尾原语
    （``\\def\\eea{\\relax\\end{eqnarray}}``——fullmatch 落空被当
    透明宏展开，体里 ``\\relax``+ENVTAG 裸进 surface、env 对不上号）。
    前缀闸防误伤：``\\end{X}`` 之前若含自然文本（``\\begin{c}Hi
    \\end{c}`` 全包宏形）则仍是 TRANSPARENT——调用点不展开、体里
    的真 ``\\end`` 也永远够不着，登记成 env_end 只会召回双输。
    ``\\begin`` 不做头匹配同理（``\\wrap{…\\begin{c}…\\end{c}}``
    被误登记 env_begin 会把调用点当 ``\\begin`` 处理）。
    """
    stripped = body.strip()
    b = _ENV_BEGIN_RX.fullmatch(stripped)
    if b:
        return MacroKind.ENV_BEGIN, b.group(1).strip()
    e = _ENV_END_TAIL_RX.search(stripped)
    if e is not None and not body_has_text(stripped[: e.start()]):
        return MacroKind.ENV_END, e.group(1).strip()
    c = _CSNAME_END_RX.fullmatch(stripped)
    if c is not None:
        return MacroKind.ENV_END, c.group(1).strip()
    return MacroKind.TRANSPARENT, ""


# ---------------------------------------------------------------- argspec


def parse_argspec(spec_str: str) -> list[ArgSpec]:  # noqa: C901, PLR0912 — argspec 字母各一分支，平铺即 §5.2 表
    r"""Xparse 参数签名串 → ``list[ArgSpec]``（§5.2）。

    ``m`` 强制 ``{}``；``n`` 裸 cs 名参（``\setlength\parskip`` 形——cs
    token 或 ``{}``/``[]`` 组）；``o`` 可选 ``[]``；``O{def}`` 带默认；
    ``s`` 星号；``d<>/D<>{d}`` 定界可选/带默认；``r<>/R<>`` 定界强制；
    ``v`` 逐字；``e{}/t<>`` 修饰/测试（解析即跳过语义）；``b`` 环境体；
    空白/未知跳过。
    """
    out: list[ArgSpec] = []
    i, n = 0, len(spec_str)
    while i < n:
        ch = spec_str[i]
        i += 1
        if ch in _WS_OR_PLUS:
            continue
        if ch == "m":
            out.append(ArgSpec("m"))
        elif ch == "o":
            out.append(ArgSpec("o"))
        elif ch == "O":
            d, i = _spec_braced(spec_str, i, "{", "}")
            out.append(ArgSpec("O", default=d))
        elif ch == "s":
            out.append(ArgSpec("s"))
        elif ch in "dD":
            d, i = _spec_delim(spec_str, i)
            spec = ArgSpec(ch, delim=d)
            if ch == "D":
                spec.default, i = _spec_braced(spec_str, i, "{", "}")
            out.append(spec)
        elif ch in "rR":
            d, i = _spec_delim(spec_str, i)
            spec = ArgSpec(ch, delim=d)
            if ch == "R":
                spec.default, i = _spec_braced(spec_str, i, "{", "}")
            out.append(spec)
        elif ch == "v":
            out.append(ArgSpec("v"))
        elif ch == "n":
            out.append(ArgSpec("n"))
        elif ch == "e":
            d, i = _spec_braced(spec_str, i, "{", "}")
            # token 表入 delim（``e{^_}``→"^_"）——调用点按它试吃修饰参
            # （此前丢弃 → e-spec 永不消费，位序错位，scanner-audit F10）
            out.append(ArgSpec("e", delim=d or ""))
        elif ch == "t":
            # t 是单字符测试符（t* / t< 各测一字），与 d/D/r/R 的双字符对不同
            pos = ws_skip(spec_str, i)
            if pos < len(spec_str):
                out.append(ArgSpec("t", delim=spec_str[pos]))
                i = pos + 1
            else:
                out.append(ArgSpec("t"))
        elif ch == "b":
            out.append(ArgSpec("b"))
        # 未知字符：跳过（容错优先，签名串脏了不崩）
    return out


_WS_OR_PLUS = " \t\n+"


def _spec_braced(spec: str, i: int, op: str, cl: str) -> tuple[str | None, int]:
    """``{..}``/``<..>`` 等成对读取；缺 opener → (None, i) 原样返回。"""
    pos = ws_skip(spec, i)
    if pos < len(spec) and spec[pos] == op:
        e = spec.find(cl, pos + 1)
        if e >= 0:
            return spec[pos + 1 : e], e + 1
    return None, i


def _spec_delim(spec: str, i: int) -> tuple[str, int]:
    """``d<>``/``t*`` 的定界符对：取后续两字符（含跳过空白后）。缺 → ('', i)。"""
    pos = ws_skip(spec, i)
    if pos + 1 < len(spec):
        return spec[pos] + spec[pos + 1], pos + 2
    return "", i
