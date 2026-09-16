r"""宏表：六类定义命令扫描 + MacroEntry 分类 + argspec 编译（docs/07 §5）。

分类在**登记时**一次完成，调用点只查表（§5.1）：

- ``body`` 整体是 ``\begin{X}`` → ENV_BEGIN(X)；``\end{X}`` → ENV_END(X)
- body 无自然文本（去命令/参数后无 ≥2 连续字母）→ OPAQUE
- 否则 → TRANSPARENT，``protect_args`` 标记落在 ``\ref/\cite/\label/\url``
  参数位的 ``#i``（调用点该位 → ``[[KEY]]``）

v1 刻意降级：``\def`` 定界参数（``\def\f(#1){}`` 型）不登记、定义区段
literal、记 ``def_parse_fail``，后续调用走未知命令 ``[[CMD]]`` 路径
（docs/07 §8.3 表 + §10 W 表；§8.4 编译留 v2）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from texlate.latex.model import (
    ArgSpec,
    EnvEntry,
    MacroEntry,
    MacroKind,
    ScanState,
    ScanWarning,
    env_name_at,
    match_brace,
    match_bracket,
    read_cmd_name,
    ws_skip,
)
from texlate.latex.tables import MATH_ENVS, PROTECTED_PARAM_CMDS
from texlate.textutil import mask_tex

_ENV_BEGIN_RX = re.compile(r"\\begin\{([^}]*)\}")
_ENV_END_RX = re.compile(r"\\end\{([^}]*)\}")
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
# cs 名内含 ``@``（``\@startsection``/``\z@``/裸 ``\@``）——@ 能进 cs 名
# 只在 makeatletter 语境成立；``\\x@``（``\\`` 换行 + ``@``）稀有误命中
# 仅致保守 opaque，无害。
_AT_CS_RX = re.compile(r"\\[a-zA-Z@]*@")
# ``\csname a@b\endcsname``：@ 是字面字符、@-cs 在展开期才合成——同源第二
# 路径（gullet ``_has_at_cs`` csname 支对价）。
_AT_CSNAME_RX = re.compile(r"\\csname(?:(?!\\endcsname).)*@", re.DOTALL)


@dataclass(slots=True)
class MacroTable:
    """命令/环境双表（spike ``env:`` 前缀键的显式化，W6 扶正）。"""

    cmds: dict[str, MacroEntry] = field(default_factory=dict)
    envs: dict[str, EnvEntry] = field(default_factory=dict)


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


def env_kind_of(body: str) -> str:
    r"""``\newenvironment`` 体启发：含 caption/figure → protected（W15 粗糙，维持）。"""
    return "protected" if "caption" in body or "figure" in body else "transparent"


_ENV_TAIL_BEGIN_RX = re.compile(r"\\begin\s*\{([^}]*)\}\s*$")
_ENV_TAIL_CS_RX = re.compile(r"\\([a-zA-Z@]+\*?)\s*$")


def env_body_role_of(body: str, table: MacroTable | None = None) -> str:
    r"""``\newenvironment`` before 体尾开数学 → ``"math"``（否则 ``""``）。

    gullet ``_env_body_role`` 的字符串版对价（1003.0112）：尾形 ``$``/``$$``、
    ``\begin{math-env}``、开数学 cs（``\eqnarray`` 族内核名、``\(`/``\[``）、
    env_begin→math-env 的已注册宏端点、``body_role=math`` 用户 env 套娃。
    """
    tail = body.rstrip()
    if not tail:
        return ""
    m = _ENV_TAIL_BEGIN_RX.search(tail)
    if m is not None:
        name = m.group(1).strip()
        e = table.envs.get(name) if table is not None else None
        math = (
            name in MATH_ENVS
            or name.rstrip("*") in MATH_ENVS
            or (e is not None and e.body_role == "math")
        )
        return "math" if math else ""
    if tail.endswith(("\\(", "\\[")) or (
        tail.endswith("$") and not tail.endswith("\\$")
    ):
        return "math"
    m = _ENV_TAIL_CS_RX.search(tail)
    name = m.group(1) if m is not None else ""
    if name in MATH_ENVS:
        return "math"
    e = table.cmds.get(name) if table is not None else None
    if e is None or e.kind is not MacroKind.ENV_BEGIN:
        return ""
    tenv = e.target_env
    ee = table.envs.get(tenv) if table is not None else None
    math = (
        tenv in MATH_ENVS
        or tenv.rstrip("*") in MATH_ENVS
        or (ee is not None and ee.body_role == "math")
    )
    return "math" if math else ""


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


def register_macro(
    table: MacroTable,
    name: str,
    spec: list[ArgSpec],
    body: str,
    def_site: int = -1,
) -> None:
    r"""登记宏并做三分类判定（§5.1）。

    替换体含 @-letter csname（``\\@startsection``/``\\z@``）→ OPAQUE：
    该类体离开 makeatletter 语境不可编译，展开只会产出 ``\\@``+字母
    的断裂文本（gullet ``_has_at_cs`` 的字符串版对价，0707.3950 实证）。
    """
    if not name:
        return
    entry = MacroEntry(name=name, spec=spec, body=body, def_site=def_site)
    kind, target = classify_body(body)
    if kind is MacroKind.TRANSPARENT:
        if (
            _AT_CS_RX.search(body)
            or _AT_CSNAME_RX.search(body)
            or not body_has_text(body)
        ):
            entry.kind = MacroKind.OPAQUE
        else:
            entry.kind = MacroKind.TRANSPARENT
            nargs = len(spec)
            entry.protect_args = protected_param_positions(body, nargs)
    else:
        entry.kind = kind
        entry.target_env = target
    table.cmds[name] = entry


def register_newif(state: ScanState, cond: str, def_site: int = -1) -> None:
    r"""``\newif\ifX`` → 旗标 ``X`` 入 ``ifflags``，``\Xtrue/\Xfalse`` 注册 LITERAL。"""
    if not cond.startswith("if"):
        return
    base = cond[2:]
    state.ifflags[base] = False
    for suffix in ("true", "false"):
        state.macros.cmds.setdefault(
            base + suffix,
            MacroEntry(name=base + suffix, kind=MacroKind.LITERAL, def_site=def_site),
        )


# ---------------------------------------------------------------- argspec


def parse_argspec(spec_str: str) -> list[ArgSpec]:  # noqa: C901, PLR0912 — argspec 字母各一分支，平铺即 §5.2 表
    """Xparse 参数签名串 → ``list[ArgSpec]``（§5.2）。

    ``m`` 强制 ``{}``；``o`` 可选 ``[]``；``O{def}`` 带默认；``s`` 星号；
    ``d<>/D<>{d}`` 定界可选/带默认；``r<>/R<>`` 定界强制；``v`` 逐字；
    ``e{}/t<>`` 修饰/测试（解析即跳过语义）；``b`` 环境体；空白/未知跳过。
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


# ---------------------------------------------------------------- 定义扫描


def scan_macro_def(  # noqa: C901, PLR0911, PLR0912, PLR0915 — 六类定义命令各一段语法，平铺即 §5 分族表
    tex: str, i: int, name: str, state: ScanState
) -> int:
    r"""定义命令 → 登记宏表，返回整段后一位。全部逐字保留（调用方发 LITERAL）。

    ``i`` 指向 ``\``，``name`` 已读出。解析失败一律返回当前能确定的位置
    （绝不抛异常）；``\def`` 定界参 → 不登记 + ``def_parse_fail`` warning。
    """
    pos = i + 1 + len(name)
    n = len(tex)
    table = state.macros

    if name in ("newenvironment", "renewenvironment"):
        envname, p = env_name_at(tex, pos)
        if envname:
            p = ws_skip(tex, p)
            nargs = 0
            has_opt = False
            # ``[n][dflt]`` 双 bracket——与 newcommand 的 for-k 循环同形
            # （旧版只读 [n]，落在 [dflt] 上 match_brace 失败 → 定义尾部
            # 整段回落进正文 chunk：scanner-audit F3，corpus 1.5% 命中）。
            for k in range(2):
                if p < n and tex[p] == "[":
                    e2 = match_bracket(tex, p)
                    if e2 is None:
                        break
                    if k == 0:
                        try:
                            nargs = int(tex[p + 1 : e2 - 1].strip() or 0)
                        except ValueError:
                            nargs = 0
                    else:
                        has_opt = True
                    p = e2
                else:
                    break
                p = ws_skip(tex, p)
            bb = ws_skip(tex, p)
            eb = match_brace(tex, bb)
            if eb:
                body_b = tex[bb + 1 : eb - 1]
                ee = match_brace(tex, ws_skip(tex, eb))
                table.envs[envname] = EnvEntry(
                    name=envname,
                    # LaTeX n **含**可选位：``[2][d]`` = opt + 1 强制
                    # （v2 ``_do_newenv`` ``max(n-1,0)`` 同规，audit C3；
                    # ``_eat_env_args`` 的 ``[opt]`` 试吃与 mand 数两立）
                    nargs=max(nargs - 1, 0) if has_opt else nargs,
                    kind=env_kind_of(body_b),
                    body_role=env_body_role_of(body_b, table),
                )
                return ee or eb
        return pos

    if name in ("newcommand", "renewcommand", "providecommand"):
        pos = ws_skip(tex, pos)
        if pos < n and tex[pos] == "*":
            pos += 1
        mname, pos = _read_def_name(tex, pos)
        if mname is None:
            return pos
        nargs, has_opt = 0, False
        opt_default: str | None = None
        for k in range(2):
            p2 = ws_skip(tex, pos)
            if p2 < n and tex[p2] == "[":
                e2 = match_bracket(tex, p2)
                if e2 is None:
                    break
                if k == 0:
                    try:
                        nargs = int(tex[p2 + 1 : e2 - 1].strip() or 0)
                    except ValueError:
                        nargs = 0
                else:
                    has_opt = True
                    opt_default = tex[p2 + 1 : e2 - 1]
                pos = e2
            else:
                break
        p2 = ws_skip(tex, pos)
        if p2 < n and tex[p2] == "{":
            e2 = match_brace(tex, p2)
            if e2:
                # LaTeX ``[n][d]`` 的 n **含**可选位：``[2][d]`` = o + m×1
                # （v2 ``_do_newcmd`` ``max(n-1,0)`` 同规，audit C2——
                # 旧版 o+m×n 的幻影第 3 参会把正文 token 吞进 [[MACRO]]）
                spec = ([ArgSpec("o", default=opt_default)] if has_opt else []) + [
                    ArgSpec("m")
                ] * max(nargs - (1 if has_opt else 0), 0)
                register_macro(table, mname, spec, tex[p2 + 1 : e2 - 1], i)
                return e2
        return pos

    if name in ("def", "gdef", "edef", "xdef"):
        pos = ws_skip(tex, pos)
        mname, pos = _read_def_name(tex, pos)
        if mname is None:
            return pos
        # 参数文本 = \name 与首个 '{' 之间；只认连续 #1..#9（+空白）为
        # 无参定界形，其余 → 定界参 v1 降级：不登记 + 整段 literal + warning。
        ok, nargs, body_pos = _scan_def_params(tex, pos)
        bpos = ws_skip(tex, body_pos)
        if bpos < n and tex[bpos] == "{":
            e2 = match_brace(tex, bpos)
            if e2:
                if ok:
                    register_macro(
                        table, mname, [ArgSpec("m")] * nargs, tex[bpos + 1 : e2 - 1], i
                    )
                else:
                    state.warnings.append(
                        ScanWarning("def_parse_fail", i, f"delimited \\def\\{mname}")
                    )
                return e2
        if ok:
            # 纯 #n 序列但无 body（EOF/参数中断）——降级也留信号
            state.warnings.append(
                ScanWarning("def_parse_fail", i, f"bodyless \\def\\{mname}")
            )
        return body_pos if not ok else pos

    if name in (
        "NewDocumentCommand",
        "RenewDocumentCommand",
        "ProvideDocumentCommand",
        "DeclareDocumentCommand",
    ):
        pos = ws_skip(tex, pos)
        mname, pos = _read_def_name(tex, pos)
        if mname is None:
            return pos
        pos = ws_skip(tex, pos)
        spec: list[ArgSpec] = []
        if pos < n and tex[pos] == "{":
            e2 = match_brace(tex, pos)
            if e2:
                spec = parse_argspec(tex[pos + 1 : e2 - 1])
                pos = e2
        p2 = ws_skip(tex, pos)
        if p2 < n and tex[p2] == "{":
            e2 = match_brace(tex, p2)
            if e2:
                register_macro(table, mname, spec, tex[p2 + 1 : e2 - 1], i)
                return e2
        return pos

    if name == "DeclareMathOperator":
        pos = ws_skip(tex, pos)
        if pos < n and tex[pos] == "*":
            pos += 1
        mname, pos = _read_def_name(tex, ws_skip(tex, pos))
        if mname is not None:
            table.cmds[mname] = MacroEntry(
                name=mname, spec=[], kind=MacroKind.OPAQUE, def_site=i
            )
        p2 = ws_skip(tex, pos)
        if p2 < n and tex[p2] == "{":
            e2 = match_brace(tex, p2)
            if e2:
                return e2
        return pos

    return pos


def _read_def_name(tex: str, pos: int) -> tuple[str | None, int]:
    r"""``{\cmd}`` 或 ``\cmd`` 两种形态读宏名。"""
    n = len(tex)
    if pos < n and tex[pos] == "{":
        e2 = match_brace(tex, pos)
        if e2:
            return tex[pos + 1 : e2 - 1].strip().lstrip("\\"), e2
        return None, pos
    if pos < n and tex[pos] == "\\":
        return read_cmd_name(tex, pos)
    return None, pos


def _scan_def_params(tex: str, pos: int) -> tuple[bool, int, int]:
    r"""``\def`` 参数文本扫描：(是否纯 ``#n`` 序列, 参数数, 扫描停止位)。

    纯序列 = 连续 ``#1..#9`` + 空白，直到 ``{``/``\par``/其他字符。
    单个 ``\n`` 在参数文本里是 space token（TeX catcode 语义），
    ``\n\n`` 才是 ``\par`` 停止位。
    """
    n = len(tex)
    nargs = 0
    ok = True
    while pos < n:
        c = tex[pos]
        if c == "#" and pos + 1 < n and tex[pos + 1].isdigit():
            nargs += 1
            pos += 2
        elif c in " \t\r":
            pos += 1
        elif c == "\n":
            k = pos + 1
            while k < n and tex[k] in " \t\r":
                k += 1
            if k < n and tex[k] == "\n":
                break  # \par：非 \long 定义到此为止
            pos += 1  # 单换行 = space token，继续扫 #n
        elif c == "#":
            # '##' 或 '#{' 等非数字形 → 定界参
            ok = False
            pos += 1
        elif c == "{":
            break
        else:
            ok = False
            pos += 1
    return ok, nargs, pos


def register_macros_in(tex: str, state: ScanState) -> None:
    r"""Preamble 区间：只找定义命令登记宏表，不产出 pieces。

    ``\\newif`` 一并登记（旗标进 ``state.ifflags``）——preamble 里的
    ``\\newif`` 不进主流水线，漏登记会让正文 ``\\Xtrue`` 走未知命令路径。

    定位扫 ``mask_tex`` 等长遮盖视图：verbatim/lstlisting 环境、
    ``\verb``/``\lstinline``、comment 失活环境与 ``%`` 注释里的假
    ``\def``/``\newcommand`` 不进表（audit F9a）。offset 与原文逐字节
    对齐，命中的定义仍在原串上解析（体字节保真——遮盖视图仅供定位）。
    """
    view = mask_tex(tex)
    i, n = 0, len(view)
    while i < n:
        c = view[i]
        if c == "\\":
            name, j = read_cmd_name(view, i)
            if name == "newif":
                p = ws_skip(view, j)
                if p < n and view[p] == "\\":
                    cond, e2 = read_cmd_name(view, p)
                    register_newif(state, cond, i)
                    i = e2
                    continue
                i = j
                continue
            if name in _DEF_SCAN_NAMES:
                end = scan_macro_def(tex, i, name, state)
                i = max(end, j)
                continue
            i = j
            continue
        i += 1


_DEF_SCAN_NAMES = {
    "newcommand",
    "renewcommand",
    "providecommand",
    "def",
    "gdef",
    "edef",
    "xdef",
    "NewDocumentCommand",
    "RenewDocumentCommand",
    "ProvideDocumentCommand",
    "DeclareDocumentCommand",
    "DeclareMathOperator",
    "newenvironment",
    "renewenvironment",
}
