r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：token 表面/相等/代入工具。"""

from __future__ import annotations

from texlate.latex.mouth import (
    Tok,
)


def _surface(toks: list[Tok] | tuple[Tok, ...]) -> str:
    r"""Token 表面文本：cs → ``\name``，其余 → ``text``（分类/名拼接用）。

    cs 后紧邻 letter token 补一个空格——``\text foo`` 源里被吸收的空白
    在 token 流里已不存在，不补则 ``\textfoo`` 被 ``_STRIP_CS_RX`` 整体
    当命令名剥掉，含文本的体误判 opaque（``\begin{`` 不受影响：
    lbrace 非 letter）。
    """
    parts: list[str] = []
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind == "cs":
            parts.append("\\" + t.text)
            if i + 1 < n and toks[i + 1].kind == "letter":
                parts.append(" ")
        else:
            parts.append(t.text)
    return "".join(parts)


def _tok_eq(a: Tok, b: Tok) -> bool:
    """Token 结构相等（kind+text；忽略 pos/gen——plasTeX ``t == a`` 同义）。"""
    return a.kind == b.kind and a.text == b.text


def _bare_cs(body: list[Tok]) -> Tok | None:
    r"""体为单枚 cs（边沿空白不计）→ 该 cs；否则 ``None``。

    ``\newcommand{\nc}{\newcommand}`` 纯别名形的判据——edge-stripped
    只认一枚，多 token 体（``\foo\bar``）不走别名路。
    """
    i, j = 0, len(body)
    while i < j and body[i].kind in ("space", "eol_par"):
        i += 1
    while j > i and body[j - 1].kind in ("space", "eol_par"):
        j -= 1
    if j - i == 1 and body[i].kind == "cs":
        return body[i]
    return None


def _has_at_cs(body: list[Tok]) -> bool:
    r"""体含 @-letter cs token（``\@startsection``/``\z@``/裸 ``\@``）。

    @ 收进 cs 名只在 ``\makeatletter`` 语境成立；展开把 ``\@x`` 序列化进
    正文（@=other）会重解析为 ``\@``+字母（``\spacefactor`` 义）——替换体
    离开 makeatletter 即不可编译，此类宏只能 opaque 原样保留调用点，编译期
    由 tex 内被保留的 def 自己展开（0707.3950 ``\section`` 实证）。
    """
    if any(t.kind == "cs" and "@" in t.text for t in body):
        return True
    # ``\csname a@b\endcsname``：@ 以 letter/other 身份进体，csname 在展开期
    # 才合成 @-cs——同源泄漏的第二路径，同判 opaque。
    if any(t.kind == "cs" and t.text == "csname" for t in body):
        return any(t.kind in ("letter", "other") and t.text == "@" for t in body)
    return False


def expand_def(
    body: list[Tok], params: dict[int, list[Tok] | None], trig: Tok
) -> list[Tok]:
    r"""``#n`` 代入（``expandDef __init__.py:1096-1127`` 直接移植）。

    - ``##`` → 字面 ``#``；``#``+数字 → ``params[k]``（参数 token 保持自身
      pos/gen——它们是真实源 token）；``#``+非数字 → 容忍为字面 ``#``
      （plasTeX ``int(t)`` 会崩，我们选择不崩）；
    - ``previous == 'ifx'`` 时参数外包 ``{ }``（``__init__.py:1116`` 同款 hack）；
    - 体产出的 token 打 ``gen=trig.gen+1``、``origin=最外层调用点``——顶层
      调用的 origin 先打 ``trig.pos``（cs 名），``_invoke`` 返回前由
      ``_stamp_call_origin`` 补打为含 args 的整调用区间。
    """
    gen = trig.gen + 1
    origin = trig.origin or trig.pos
    out: list[Tok] = []
    i, n = 0, len(body)
    prev_name = ""
    while i < n:
        t = body[i]
        if t.kind != "param":
            out.append(Tok(t.kind, t.text, t.pos, gen, origin, t.xprotect))
            prev_name = t.text
            i += 1
            continue
        nxt = body[i + 1] if i + 1 < n else None
        if nxt is None:
            out.append(Tok("param", t.text, t.pos, gen, origin))
            prev_name = t.text
            i += 1
            continue
        if nxt.kind == "param":  # '##' → 字面 #
            out.append(Tok("param", nxt.text, nxt.pos, gen, origin))
            prev_name = nxt.text
            i += 2
            continue
        if nxt.text.isdigit():
            v = params.get(int(nxt.text))
            if v:
                if prev_name == "ifx":  # ifx hack：参数包组
                    out.append(Tok("lbrace", "{", t.pos, gen, origin))
                    out.extend(v)
                    out.append(Tok("rbrace", "}", t.pos, gen, origin))
                else:
                    out.extend(v)
            i += 2
            prev_name = nxt.text
            continue
        # '#' + 非数字非'#' → 字面 #，下一 token 下轮正常处理
        out.append(Tok("param", t.text, t.pos, gen, origin))
        prev_name = t.text
        i += 1
    return out
