r"""宏体分类 + argspec 编译：gullet/segmenter 共享的登记侧 helper（docs/spec/latex-pipeline.md）。

分类在**登记时**一次完成，调用点只查表（§5.1）：

- ``body`` 整体是 ``\begin{X}`` → ENV_BEGIN(X)；``\end{X}`` → ENV_END(X)
- body 无自然文本（去命令/参数后无 ≥2 连续字母）→ OPAQUE
- 否则 → TRANSPARENT，``protect_args`` 标记落在 ``\ref/\cite/\label/\url``
  参数位的 ``#i``（调用点该位 → ``[[KEY]]``）
"""

from __future__ import annotations

import re
from typing import NamedTuple

from texlate.latex.model import ArgSpec, MacroKind, ws_skip
from texlate.latex.mouth import Mouth
from texlate.latex.tables import PROTECTED_PARAM_CMDS

_ENV_BEGIN_RX = re.compile(r"\\begin\{([^}]*)\}")
_ENV_END_TAIL_RX = re.compile(r"\\end\{([^}]*)\}\s*$")
# ``\csname endX\endcsname`` 整体形——LaTeX ``\end{X}`` 内核即展开成
# ``\endX``，故包它的宏（``\def\eea{\csname endeqnarray\endcsname}``）
# 语义上就是 env_end 端点（R1：token 层 ``x.text=="end"+target`` 同规
# 的表侧入口——csname 合成不经宏体表，不登记则配对扫描永远看不见它）。
# 尾锚定 + 前缀无文本闸同 ``_ENV_END_TAIL_RX``（R7：``\relax`` 等收尾
# 原语前缀不挡端点登记，带自然文本的前缀仍 TRANSPARENT）。
_CSNAME_END_TAIL_RX = re.compile(r"\\csname\s*end([a-zA-Z@*]+)\s*\\endcsname\s*$")
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
            # 只在 armed 期间计可选参嵌套——游离 ``[``（如 ``[0,1)`` 半开
            # 区间）占住 bracket 会让 ``\cite#1`` 的 armed 永不消费、
            # 后续 ``#j`` 被误标保护位；``]`` 不门控——``{``/``}`` 途中
            # 清过 armed 时残留深度仍须对称回收
            if armed:
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
    ``\\csname endX\\endcsname`` 臂同走 R7 尾匹配（``\\def\\eea{
    \\relax\\csname endeqnarray\\endcsname}`` 前缀闸同口径）。
    """
    stripped = body.strip()
    b = _ENV_BEGIN_RX.fullmatch(stripped)
    if b:
        return MacroKind.ENV_BEGIN, b.group(1).strip()
    e = _ENV_END_TAIL_RX.search(stripped)
    if e is not None and not body_has_text(stripped[: e.start()]):
        return MacroKind.ENV_END, e.group(1).strip()
    c = _CSNAME_END_TAIL_RX.search(stripped)
    if c is not None and not body_has_text(stripped[: c.start()]):
        return MacroKind.ENV_END, c.group(1).strip()
    return MacroKind.TRANSPARENT, ""


# ---------------------------------------------------------------- argspec


class SpecItem(NamedTuple):
    r"""Xparse spec 单项——**语义角色**表示（``scan_xparse`` 产物，双 lowering 公共源）。

    ``role`` 按语义定名不按源字母——xparse ``g``（可选 ``{..}`` 组）与
    ``l``（读到 ``{`` 的 until-group）分位，旧 ``ArgSpec("g")`` 实指
    后者；角色表：``mand``=m、``opt``=o、``opt_dft``=O{def}、``star``=s、
    ``test``=tC、``dopt``=dXY、``dopt_dft``=DXY{def}、``dreq``=rXY、
    ``dreq_dft``=RXY{def}、``verb``=v、``name``=n、``embel``=e{toks}、
    ``embel_dft``=E{toks}{dfts}、``until``=u{toks}、``ogrp``=g、
    ``ugrp``=l、``body``=b、``xexp``=x。
    """

    role: str
    open_c: str = ""  # dopt/dreq 族定界开符（定界对截断 → ""）
    close_c: str = ""  # 定界闭符
    default: str | None = None  # O/D/R/E 的 {..} 缺省值源串（None = 组缺席）
    char: str = ""  # star/test 的期待字符（star 恒 "*"；"" = t 尾缺席）
    toks: str | None = None  # e/u/E 花括组 token 表源串（None = 组缺席）


def scan_xparse(spec_str: str) -> list[SpecItem]:  # noqa: C901, PLR0912, PLR0915 — spec 字母各一分支，平铺即 §5.2/§4.3 表
    r"""Xparse spec 串 → ``list[SpecItem]`` 规范项（签名语言单源扫描）。

    合并原两份手搓 parser——本表路 ``parse_argspec``（→``ArgSpec``）与
    gullet ``_parse_xparse``（→``Arg``）——为一份扫描 + 两路 lowering：
    逐项产出语义角色 ``SpecItem``，载荷一律源串（``default``/``toks``
    不经 lex——活体猫码 lex 是 lowering 的事）。项内空白统一
    ``ws_skip``（xparse 本体忽略 spec 内空白；旧 decls ``_braced`` 不跳
    致 ``"O {x}"`` 两路分歧，归一后消）。

    ``m`` 强制 ``{}``；``o`` 可选 ``[]``；``O{def}`` 带默认；``s`` 星号；
    ``tC`` 单字符测试；``dXY/DXY{def}`` 定界可选/带默认；``rXY/RXY{def}``
    定界强制；``v`` 逐字；``n`` 裸 cs 名参；``e{toks}`` 修饰符表；
    ``E{toks}{dfts}`` 带缺省修饰；``u{toks}`` 读至序列；``g`` 可选
    ``{..}`` 组；``l`` 读至 ``{``；``b`` 环境体；``x`` 可展开参；
    ``!``/``+`` 前缀修饰（beamer 感知/long 标记）与未知字符跳过（容错
    优先，签名串脏了不崩）。载荷组缺席/定界对截断以 ``None``/``""``
    落项，由 lowering 裁决容错。

    Arg lowering 契约（decls ``_parse_xparse`` 参照实现）：``mand``→
    ``Arg("m")``；``opt``→``Arg("o")``；``opt_dft``/``dopt_dft``/
    ``dreq_dft`` 缺省经 ``self._lex`` 物化；``star``/``test``→``Arg("star",
    char=it.char or "*")``；``dopt``→``Arg("o", open, close)``；``dreq``→
    ``literal_match``+``delim`` 双槽；``until``→``Arg("delim")``、
    ``ogrp``→``Arg("o", "{", "}")``、``ugrp``→``Arg("until_group")``、
    ``embel``→``Arg("e")``；``verb``/``body``/``embel_dft``/``xexp``
    与 ``toks`` 缺席、定界对截断（``open_c==""``）→ fail-closed 返
    ``None``（整条不登记）。
    """
    out: list[SpecItem] = []
    i, n = 0, len(spec_str)
    while i < n:
        ch = spec_str[i]
        i += 1
        if ch in _WS_OR_PLUS:
            continue
        if ch == "m":
            out.append(SpecItem("mand"))
        elif ch == "o":
            out.append(SpecItem("opt"))
        elif ch == "O":
            d, i = _spec_braced(spec_str, i, "{", "}")
            out.append(SpecItem("opt_dft", default=d))
        elif ch == "s":
            out.append(SpecItem("star", char="*"))
        elif ch == "t":
            # t 是单字符测试符（t* / t< 各测一字），与 d/D/r/R 的双字符对不同
            pos = ws_skip(spec_str, i)
            if pos < n:
                out.append(SpecItem("test", char=spec_str[pos]))
                i = pos + 1
            else:
                out.append(SpecItem("test"))
        elif ch in "dD":
            pair, i = _spec_delim(spec_str, i)
            dft = None
            if ch == "D":
                dft, i = _spec_braced(spec_str, i, "{", "}")
            out.append(
                SpecItem(
                    "dopt_dft" if ch == "D" else "dopt",
                    open_c=pair[:1],
                    close_c=pair[1:],
                    default=dft,
                )
            )
        elif ch in "rR":
            pair, i = _spec_delim(spec_str, i)
            dft = None
            if ch == "R":
                dft, i = _spec_braced(spec_str, i, "{", "}")
            out.append(
                SpecItem(
                    "dreq_dft" if ch == "R" else "dreq",
                    open_c=pair[:1],
                    close_c=pair[1:],
                    default=dft,
                )
            )
        elif ch == "v":
            out.append(SpecItem("verb"))
        elif ch == "n":
            out.append(SpecItem("name"))
        elif ch == "e":
            d, i = _spec_braced(spec_str, i, "{", "}")
            out.append(SpecItem("embel", toks=d))
        elif ch == "E":
            d, i = _spec_braced(spec_str, i, "{", "}")
            # 第二组是缺省值**花括组列**（``{{up}{down}}``）——平衡读尽，
            # 非配对读残留 ``{b}}`` 回扫会污染后续 spec 位
            d2, i = _spec_group(spec_str, i)
            out.append(SpecItem("embel_dft", toks=d, default=d2))
        elif ch == "u":
            d, i = _spec_braced(spec_str, i, "{", "}")
            out.append(SpecItem("until", toks=d))
        elif ch == "g":
            out.append(SpecItem("ogrp"))
        elif ch == "l":
            out.append(SpecItem("ugrp"))
        elif ch == "b":
            out.append(SpecItem("body"))
        elif ch == "x":
            out.append(SpecItem("xexp"))
        # 未知字符：跳过（容错优先，签名串脏了不崩）
    return out


def parse_argspec(spec_str: str) -> list[ArgSpec]:  # noqa: C901, PLR0912 — spec 角色各一分支，平铺即 §5.2 表
    r"""Xparse 参数签名串 → ``list[ArgSpec]``（§5.2；``scan_xparse`` 的表路 lowering）。

    ``m`` 强制 ``{}``；``n`` 裸 cs 名参（``\setlength\parskip`` 形——cs
    token 或 ``{}``/``[]`` 组）；``o`` 可选 ``[]``；``O{def}`` 带默认；
    ``s`` 星号；``d<>/D<>{d}`` 定界可选/带默认；``r<>/R<>`` 定界强制；
    ``v`` 逐字；``e{}/t<>`` 修饰/测试（解析即跳过语义）；``u{}`` 读至
    token 列（``delim_toks`` 以**默认猫码**物化——签名串是静态数据无
    活体猫码可取，gullet ``u`` 位由调用点 ``self._lex`` 同形物化）；
    ``l`` → ``g``（读到 ``{`` 回吐不消费）；``b`` 环境体零宽占位。

    xparse ``g``（可选 ``{..}`` 组）→ ``ArgSpec("G")`` 零宽占位——
    不可落 ``"g"`` 位（那是 ``l`` 的 until-group 语义），亦不可丢
    （槽位序与 ``arg_roles``/``#i`` 对齐，``_args_tok`` else 臂零宽
    不消费同 ``b`` 先例）；真实消费待 ``_args_tok`` 对价槽型。
    ``E``/``x``（带缺省修饰/可展开参）表路无对价 → 跳过不产位。
    """
    out: list[ArgSpec] = []
    for it in scan_xparse(spec_str):
        role = it.role
        if role == "mand":
            out.append(ArgSpec("m"))
        elif role == "opt":
            out.append(ArgSpec("o"))
        elif role == "opt_dft":
            out.append(ArgSpec("O", default=it.default))
        elif role == "star":
            out.append(ArgSpec("s"))
        elif role == "test":
            out.append(ArgSpec("t", delim=it.char))
        elif role in ("dopt", "dopt_dft"):
            out.append(
                ArgSpec(
                    "d" if role == "dopt" else "D",
                    delim=it.open_c + it.close_c,
                    default=it.default,
                )
            )
        elif role in ("dreq", "dreq_dft"):
            out.append(
                ArgSpec(
                    "r" if role == "dreq" else "R",
                    delim=it.open_c + it.close_c,
                    default=it.default,
                )
            )
        elif role == "verb":
            out.append(ArgSpec("v"))
        elif role == "name":
            out.append(ArgSpec("n"))
        elif role == "embel":
            # token 表入 delim（``e{^_}``→"^_"）——调用点按它试吃修饰参
            # （此前丢弃 → e-spec 永不消费，位序错位，scanner-audit F10）
            out.append(ArgSpec("e", delim=it.toks or ""))
        elif role == "until":
            toks = tuple(Mouth(it.toks, -1)) if it.toks is not None else ()
            out.append(ArgSpec("u", delim_toks=toks))
        elif role == "ogrp":
            out.append(ArgSpec("G"))
        elif role == "ugrp":
            out.append(ArgSpec("g"))
        elif role == "body":
            out.append(ArgSpec("b"))
        # embel_dft/xexp/未知角色：跳过不产位（表路无对价槽型）
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


def _spec_group(spec: str, i: int) -> tuple[str | None, int]:
    """``{..}`` 平衡读取（``E{toks}{dfts}`` 的 dfts 槽——内容本身含嵌套组）。"""
    pos = ws_skip(spec, i)
    if pos < len(spec) and spec[pos] == "{":
        depth, j = 1, pos + 1
        while j < len(spec) and depth:
            if spec[j] == "{":
                depth += 1
            elif spec[j] == "}":
                depth -= 1
            j += 1
        if depth == 0:
            return spec[pos + 1 : j - 1], j
    return None, i


def _spec_delim(spec: str, i: int) -> tuple[str, int]:
    """``d<>``/``r()`` 的定界符对：取后续两字符（含跳过空白后）。缺 → ('', i)。"""
    pos = ws_skip(spec, i)
    if pos + 1 < len(spec):
        return spec[pos] + spec[pos + 1], pos + 2
    return "", i
