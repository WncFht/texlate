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
from texlate.latex.tables import PROTECTED_PARAM_CMDS

_ENV_BEGIN_RX = re.compile(r"\\begin\{([^}]*)\}")
_ENV_END_RX = re.compile(r"\\end\{([^}]*)\}")
_STRIP_PARAM_RX = re.compile(r"#[1-9]?")
_STRIP_CS_RX = re.compile(r"\\[a-zA-Z@]+\*?")
_STRIP_CS1_RX = re.compile(r"\\[^a-zA-Z]")
_NONALPHA_RX = re.compile(r"[^a-zA-Z]")
_WORD_RX = re.compile(r"[a-zA-Z]{2,}")
_PARAM_TOK_RX = re.compile(r"\\[a-zA-Z@]+\*?|#([1-9])")


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


def protected_param_positions(body: str, nargs: int) -> tuple[bool, ...]:
    r"""``#i`` 落在 ``\ref/\cite/\label/\url`` 等命令参数位 → 该参数保护。"""
    flags = [False] * nargs
    if nargs == 0:
        return ()
    cur_protect = False
    for m in _PARAM_TOK_RX.finditer(body):
        tok = m.group(0)
        if tok.startswith("#"):
            idx = int(tok[1]) - 1
            # 体引用超出 spec 的 #k（嵌套 \def 的 ##k、笔误 #9）→ 无位可标，跳过不抛
            if idx < nargs:
                flags[idx] = flags[idx] or cur_protect
        else:
            name = tok.lstrip("\\").rstrip("*")
            cur_protect = name in PROTECTED_PARAM_CMDS
    return tuple(flags)


def env_kind_of(body: str) -> str:
    r"""``\newenvironment`` 体启发：含 caption/figure → protected（W15 粗糙，维持）。"""
    return "protected" if "caption" in body or "figure" in body else "transparent"


def classify_body(body: str) -> tuple[MacroKind, str]:
    r"""``body.strip()`` 全匹配 ``\\begin{X}``/``\\end{X}`` → 端点宏。"""
    stripped = body.strip()
    b = _ENV_BEGIN_RX.fullmatch(stripped)
    if b:
        return MacroKind.ENV_BEGIN, b.group(1).strip()
    e = _ENV_END_RX.fullmatch(stripped)
    if e:
        return MacroKind.ENV_END, e.group(1).strip()
    return MacroKind.TRANSPARENT, ""


def register_macro(
    table: MacroTable,
    name: str,
    spec: list[ArgSpec],
    body: str,
    def_site: int = -1,
) -> None:
    """登记宏并做三分类判定（§5.1）。"""
    if not name:
        return
    entry = MacroEntry(name=name, spec=spec, body=body, def_site=def_site)
    kind, target = classify_body(body)
    if kind is MacroKind.TRANSPARENT:
        if not body_has_text(body):
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
            _, i = _spec_braced(spec_str, i, "{", "}")
            out.append(ArgSpec("e"))
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
            if p < n and tex[p] == "[":
                e2 = match_bracket(tex, p)
                if e2:
                    try:
                        nargs = int(tex[p + 1 : e2 - 1].strip() or 0)
                    except ValueError:
                        nargs = 0
                    p = e2
            bb = ws_skip(tex, p)
            eb = match_brace(tex, bb)
            if eb:
                body_b = tex[bb + 1 : eb - 1]
                ee = match_brace(tex, ws_skip(tex, eb))
                table.envs[envname] = EnvEntry(
                    name=envname, nargs=nargs, kind=env_kind_of(body_b)
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
                pos = e2
            else:
                break
        p2 = ws_skip(tex, pos)
        if p2 < n and tex[p2] == "{":
            e2 = match_brace(tex, p2)
            if e2:
                spec = [ArgSpec("o")] * (1 if has_opt else 0) + [ArgSpec("m")] * nargs
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
    """
    i, n = 0, len(tex)
    while i < n:
        c = tex[i]
        if c == "%":
            k = tex.find("\n", i)
            i = n if k < 0 else k + 1
            continue
        if c == "\\":
            name, j = read_cmd_name(tex, i)
            if name == "newif":
                p = ws_skip(tex, j)
                if p < n and tex[p] == "\\":
                    cond, e2 = read_cmd_name(tex, p)
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
