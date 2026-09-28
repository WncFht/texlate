r"""字符级原语层——单遍逐字符扫描的共享低层工具（零依赖叶）。

扶正自 ``model.py`` 的原语区（分层修复：``model`` 是数据层，本文件
不 import texlate 任何模块——``model``/``tables``/``segmenter``/
``macro_table``/``flatten``/``gullet`` 全单向依赖此叶，无环）。
旧 ``from texlate.latex.model import ws_skip`` 调用面由 ``model``
再出口保持。
"""

from __future__ import annotations

import re

_WS = " \t\n\r"
_PAR_BREAK_RX = re.compile(r"\n[ \t\r]*\n")


def ws_skip(tex: str, i: int) -> int:
    r"""跳过 `` \t\n\r``，返回下一个非空白位置。"""
    n = len(tex)
    while i < n and tex[i] in _WS:
        i += 1
    return i


def ws_skip_arg(tex: str, i: int) -> int:
    r"""参数读取专用 ws_skip：不跨段落边界；``%`` 注释透明跳过。

    TeX 不定界参数扫描只跳 space token——``\n[ \t\r]*\n`` 即 ``\par``，
    停在 ``\par`` 涉及的 ``\n`` 处（调用方看到空白字符 → 参数不成立）。
    ``%`` 吃掉到行尾**含换行**；吃注释后处新行态——紧跟的空行仍是
    ``\par``（``\section% c\n\n{T}`` 不取参，``\section% c\n{T}`` 取参）。
    停止位约定：``\par`` 对内任一 ``\n`` 位置重入本函数仍停（幂等）——
    ``_args`` 按参数项循环从停止位重扫（scanner-audit F4-par 修复）。
    scanner-audit F4：此前遇 ``%`` 即停 → ``\cite%\n{key}`` 参数错位泄漏。
    """
    n = len(tex)
    while i < n:
        c = tex[i]
        if c == "%":
            k = tex.find("\n", i)
            if k < 0:
                return n
            i = k + 1
            continue  # 新行态交给 \n 分支统一判（含下方后向检查）
        if c not in _WS:
            return i
        if c == "\n":
            k = i + 1
            while k < n and tex[k] in " \t\r":
                k += 1
            if k < n and tex[k] == "\n":
                return i
            # 幂等：本 \n 是某 par 对的后一个换行（前向已看不到配对首 \n）
            # ——回看前一非空白若为 \n 同样停住
            k = i - 1
            while k >= 0 and tex[k] in " \t\r":
                k -= 1
            if k >= 0 and tex[k] == "\n":
                return i
        i += 1
    return i


def has_par_break(s: str) -> bool:
    r"""``s`` 内含段落边界（``\n`` + 空白* + ``\n``，与主循环 §3.1.4 同判据）。"""
    return bool(_PAR_BREAK_RX.search(s))


def match_brace(  # noqa: C901, PLR0913 — 栈配四旋钮（openers/nest/cap/eol）参数化面即规格，逐支平铺
    tex: str,
    i: int,
    *,
    verbatim: bool = False,
    openers: str = "{",
    nest: str | None = None,
    cap: int | None = None,
    eol: re.Pattern[str] | None = None,
) -> int | None:
    r"""``tex[i]`` ∈ ``openers`` → 匹配闭符的后一位；未闭/越 ``cap`` → None。

    ``nest`` = 体内可嵌套的开符集（缺省 = ``openers``——``{`` 组内
    ``[`` 是字面，``[`` 组内 ``{`` 是否配对由 nest 决定）。
    ``%..EOL`` 内括号不计（``verbatim=True`` 关闭——``%`` 按字面过）；
    EOL 定界缺省 ``\n``，``eol`` 给正则可扩到 ``\r``（``textutil.mask``
    的 ``[\r\n]`` 口径）。``\X`` 跳两字符。
    """
    if i >= len(tex) or tex[i] not in openers:
        return None
    if nest is None:
        nest = openers
    closers = ["}" if tex[i] == "{" else "]"]
    j, n = i + 1, (min(len(tex), cap) if cap is not None else len(tex))
    while j < n:
        c = tex[j]
        if c == "\\":
            j += 2
            continue
        if c == "%" and not verbatim:
            if eol is not None:
                m = eol.search(tex, j)
                k = -1 if m is None else m.start()
            else:
                k = tex.find("\n", j)
            j = n if k < 0 else k + 1
            continue
        if c == "{" and "{" in nest:
            closers.append("}")
        elif c == "[" and "[" in nest:
            closers.append("]")
        elif c == closers[-1]:
            closers.pop()
            if not closers:
                return j + 1
        j += 1
    return None


def match_bracket(tex: str, i: int) -> int | None:
    r"""``tex[i]=='['`` → 匹配 ``']'`` 的后一位；允许内嵌 ``{..}`` 组与注释。

    迭代实现（原为自递归）：``[`` 嵌套用深度计数——规则与递归版逐条同构
    （``{`` 组整跳、``%``→EOL、``\\`` 跳双），但深嵌套不再爆栈
    （铁律 1「绝不抛异常」；scanner-audit F1：``[``×1500 曾 RecursionError）。
    """
    if i >= len(tex) or tex[i] != "[":
        return None
    j, n = i + 1, len(tex)
    depth = 1
    while j < n:
        c = tex[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            e = match_brace(tex, j)
            j = e or j + 1
            continue
        if c == "[":
            depth += 1
            j += 1
            continue
        if c == "%":
            k = tex.find("\n", j)
            j = n if k < 0 else k + 1
            continue
        if c == "]":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return None


def read_cmd_name(tex: str, i: int) -> tuple[str, int]:
    r"""``tex[i]=='\\'`` → (名字, 命令后一位)。字母+``@`` 串、``\@``+字母串或非字母单字符。"""
    j = i + 1
    n = len(tex)
    if j < n and tex[j] == "@" and j + 1 < n and tex[j + 1].isalpha():
        # `\@input` 类 @-宏整名读取——字节层无 catcode 概念，按 makeatletter
        # 语义收（\@ 后紧跟字母串时整体视作宏名一部分，否则 orphan）
        k = j + 1
        while k < n and (tex[k].isalpha() or tex[k] == "@"):
            k += 1
        return tex[j:k], k
    if j < n and tex[j].isalpha():
        k = j
        while k < n and (tex[k].isalpha() or tex[k] == "@"):
            k += 1
        return tex[j:k], k
    if j < n:
        return tex[j], j + 1
    return "", j


def strip_brace_comments(raw: str) -> str:
    r"""``{arg}`` 花括实参内 ``%``→EOL 注释段剔除（tokenize 语义）。

    ``\begin{%\ncomment}``/``\input{%\nfile}`` 的实参是 ``comment``/``file``
    ——注释段留在名里会让 DEAD_ENVS 查表/missing_input 查找整体失手。
    ``\X`` 跳双字符——``\%`` 转义名不剥。``env_name_at`` 与
    ``flatten._try_input`` 共用的共享原语。
    """
    if "%" not in raw:
        return raw
    out: list[str] = []
    k = 0
    while k < len(raw):
        c = raw[k]
        if c == "\\":
            out.append(raw[k : k + 2])
            k += 2
            continue
        if c == "%":
            nl = raw.find("\n", k)
            k = len(raw) if nl < 0 else nl + 1
            continue
        out.append(c)
        k += 1
    return "".join(out)


def env_name_at(tex: str, i: int) -> tuple[str | None, int]:
    r"""``{name}`` 读取：ws 后 ``{env}`` → (名, ``}`` 后一位)；否则 (None, i)。

    ``\begin/\end`` 的参数读取同样不跨段落边界（ws_skip_arg）。
    名内 ``%`` 注释段按 tokenize 语义整段剔除（含其换行）——
    ``\begin{%\ncomment}`` 的名字是 ``comment``（W11 泛化）；注释段
    原样留在名里会让 DEAD_ENVS 等查表全数失手、环境走字面退化路。
    """
    pos = ws_skip_arg(tex, i)
    if pos < len(tex) and tex[pos] == "{":
        e = match_brace(tex, pos)
        if e:
            raw = strip_brace_comments(tex[pos + 1 : e - 1])
            return raw.strip(), e
    return None, i


def unescaped_dollar_odd(body: str) -> bool:
    r"""``body`` 内未转义 ``$`` 计数为奇 → True（math-debt 判据）。

    ``%`` 到行尾跳过——注释内 ``$`` 在 TeX 配对域外（编辑器平衡伪注释），
    计入会把闭合完好的数学体误判为奇、给下一枚 ``$`` 发假债（W92）。
    """
    odd = False
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            k = body.find("\n", i)
            i = n if k < 0 else k + 1
            continue
        if c == "$":
            odd = not odd
        i += 1
    return odd


def skip_verb_at(tex: str, name: str, j: int) -> int | None:
    r"""``\verb``/``\lstinline`` 定界体跳过：返回体后一位；非定界形 → None。

    ``j`` = 命令名后一位。``\verb*?``、``\lstinline[opt]``
    前缀与 ``{...}`` 配对形都认；定界符搜索上限 = 下一 ``\n``（W9）。
    scanner/flatten/_find_env_end/_process_if 四处共用同一判据。
    """
    n = len(tex)
    k = j
    if name == "verb" and k < n and tex[k] == "*":
        k += 1
    if name == "lstinline":
        k = ws_skip(tex, k)
        if k < n and tex[k] == "[":
            e2 = match_bracket(tex, k)
            if e2:
                k = ws_skip(tex, e2)
    if k < n:
        d = tex[k]
        if d == "{":
            e = match_brace(tex, k, verbatim=True)
            if e:
                return e
        elif d not in _WS:
            eol = tex.find("\n", k + 1)
            limit = n if eol < 0 else eol
            e = tex.find(d, k + 1, limit)
            if e > 0:
                return e + 1
    return None
