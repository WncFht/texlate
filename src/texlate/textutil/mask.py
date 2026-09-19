r"""等长遮盖机 + 逐字/失活环境注册表 + 遮盖视图迭代件。

``mask_comments``：``\`` 后随字符整体跳过（``\%``/``\\%`` 语义正确），
未转义 ``%`` 到行尾替换为等长空格——offset/长度与原文逐字节对齐，
供正则/下标直接使用。**不处理 verbatim 环境**。

``mask_tex``：等长遮盖视图 = 逐字族环境体 + comment 失活环境 + 行内
``\verb``/``\lstinline`` + 行内 ``%`` 注释。定位视图 ≠ 改写目标——masked
view 绝不能拷回原文（``compile.mask`` 的手术都在原文回放）。

``VERBATIM_ENVS``/``DEAD_ENVS``：逐字/失活环境清单的单一事实源——并集自
原 compile.mask、arxiv._texutil、latex.tables 三处漂移清单。
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator


def mask_comments(text: str) -> str:
    r"""``%`` 到行尾等长空格遮盖；``\`` 后随字符整体跳过。保位不保内容。"""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "%":
            j = i
            while j < n and text[j] not in "\r\n":
                out[j] = " "
                j += 1
            i = j
            continue
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- 逐字/失活环境注册表

#: 逐字族环境基名（三处旧清单的并集）：内容按字面处理，不解析不手术不翻译。
_VERBATIM_BASE: Final = (
    "verbatim",
    "Verbatim",
    "BVerbatim",
    "LVerbatim",
    "lstlisting",
    "lstpython",
    "minted",
    "filecontents",
    "filecontents+",
    "filecontentsheader",
)
#: 逐字族环境全枚举（含 ``*`` 变体）。
VERBATIM_ENVS: Final = frozenset(
    e for base in _VERBATIM_BASE for e in (base, base + "*")
)
#: 失活环境（comment.sty）——内容对 TeX 不可见，遮盖口径同逐字。
DEAD_ENVS: Final = frozenset({"comment", "comment*"})

#: ``\begin{env}`` 识别：环境名需 ``re.escape``——名单含 ``*`` 字面，
#: 直接进 alternation 会把 ``verbatim*`` 解析成 ``verbat``+``im*``（旧实现即此 bug）。
_VERBATIM_BEGIN_RX: Final = re.compile(
    r"\\begin\s*\{(" + "|".join(re.escape(e) for e in sorted(VERBATIM_ENVS)) + r")\}"
)
_DEAD_BEGIN_RX: Final = re.compile(
    r"\\begin\s*\{(" + "|".join(re.escape(e) for e in sorted(DEAD_ENVS)) + r")\}"
)
#: TeX 控制序列：`\word*` 或单个非字母字符（DOTALL 让 `\.` 能吃 `\`+换行）。
_COMMAND_RX: Final = re.compile(r"\\(?:[a-zA-Z@]+\*?|.)", re.DOTALL)
_INLINE_VERB_RX: Final = re.compile(r"\\(verb\*?|lstinline\*?)(?![A-Za-z@])")
#: ``\lstinline`` 的 ``[opt]`` 前缀段——前导空白只跳水平空白，不跨换行：
#: 跨行 ``\s*`` 会把二遍遮盖产生的空白当真实空白吃，桥到别的 ``\`` 上
#: 产出假 verb span，破坏 ``mask_tex`` 幂等。
_LSTINLINE_OPT_RX: Final = re.compile(r"[ \t]*(?:\[[^\]\n]*\][ \t]*)?")
_NL_RX: Final = re.compile(r"[\r\n]")


def _env_stop(text: str, env: str, pos: int, *, dead: bool) -> int:
    r"""从 pos 找 ``\end{env}``，返回其结束后 offset；找不到返回 len(text)。

    verbatim 族终结是**逐字 token 序列** ``\end{env}``（kernel ``\@xverbatim``
    定界字串 / listings 逐 ``\`` 探测 / filecontents 行内含即终）——行内
    出现即终，但 ``\end {env}`` 空白断序列真实 TeX 不终结。
    comment 族终结是**行锚定整行比对**（comment.sty ``\ifx`` 比行内容 ==
    ``\end{env}``）——行首空格是 catcode-12 字面符不匹配、行尾空格被输入
    层剥除故容许；行内 ``x\end{comment}`` 与 ``\end {comment}`` 均不终结。
    """
    # 锚定 pos 搜索零切片——env 集有界，re 内部编译缓存兜住逐次 compile。
    if dead:
        ending = _dead_end_rx(env).search(text, pos)
    else:
        ending = re.compile(r"\\end\{" + re.escape(env) + r"\}").search(text, pos)
    return ending.end() if ending else len(text)


def _dead_end_rx(env: str) -> re.Pattern[str]:
    r"""``\\end{env}`` 行锚式（comment.sty ``\ifx`` 行比对单一事实源）。"""
    return re.compile(r"(?<=[\r\n])\\end\{" + re.escape(env) + r"\} *(?=[\r\n]|\Z)")


def dead_env_end(text: str, env: str, pos: int) -> int:
    r"""``pos`` 起首个行锚 ``\\end{env}`` 的 ``\\`` 起点；无命中 ``-1``。

    ``_env_stop`` dead 臂同一式——scan 视图（flatten/scanner/segmenter）
    三消费点共用；返回值给的是 ``\\`` 起点（``\\end{env}`` 段长调用方自加）。
    """
    m = _dead_end_rx(env).search(text, pos)
    return -1 if m is None else m.start()


def dead_end_anchored(text: str, env: str, a: int, e: int) -> bool:
    r"""核验 ``[a, e)`` 恰为行锚 ``\\end{env}``——``_env_stop`` dead 臂的 token 侧等价。

    ``a`` = ``\\`` 起点、``e`` = ``}`` 后一字符。字面段须逐字节 ==
    ``\\end{env}``（``\\end {env}``/``\\end{ env }`` 断序列不终结）；
    ``a`` 前列须换行（文件头不算，``(?<=[\r\n])`` 同式）、``e`` 后仅
    `` *`` 到行尾/EOF。
    """
    if text[a:e] != "\\end{" + env + "}":
        return False
    if a == 0 or text[a - 1] not in "\r\n":
        return False
    i = e
    n = len(text)
    while i < n and text[i] == " ":
        i += 1
    return i == n or text[i] in "\r\n"


def _inline_verb_span(text: str, i: int, n: int) -> tuple[int, int, int] | None:
    r"""``\verb``/``\lstinline`` 行内区段 ``(content_a, content_b, end)``。

    不合法形态返回 None（交回主循环逐字符扫）。返回值三分量：只遮
    ``[content_a, content_b)`` 定界符间内容——``\verb`` 本体与定界符原样
    保留（残形 ``\verb`` 也要求可见，test_edge_boundary_semantics 钉），
    ``end`` 是整个 verb 结构消费完的 resume offset。

    ``\lstinline`` 允许 ``[opt]`` 前缀，定界符取首个非空白字符。
    ``\verb``/``\verb*`` 定界符扫描跳过水平空白 token（``\verb |x|`` ≡
    ``\verb|x|``，latex 实证）；紧跟换行时换行本身为定界符、下一整行是
    逐字内容（latex 实证 ``\verb\n|x| after`` 全行 cmtt）。但跳过空白后
    落行尾则**不**定界——等长遮盖下被遮区段留下的空格会桥到行间 ``\r\n``
    上产出假 span、吞掉同一行真实内容，破坏 ``mask_tex`` 幂等。
    ``{`` 定界时配 ``}``；未闭合或跨行不算。

    只遮内容不遮 ``\verb``/定界符是幂等性的结构来源：二遍扫描在同一
    ``\verb`` 上拿到同一定界符与收尾位置，content 已是空格 → 再遮为
    no-op；若连定界符也遮，``\verb``+空格串可桥到任意真定界符对上。
    """
    inline = _INLINE_VERB_RX.match(text, i)
    if not inline:
        return None
    start = inline.end()
    skipped = False
    if inline[1].startswith("lstinline"):
        options = _LSTINLINE_OPT_RX.match(text, start)
        start = options.end()
        if start >= n or text[start].isspace():
            return None
    else:
        while start < n and text[start] in " \t":
            start += 1
            skipped = True
        if start >= n:
            return None
    delimiter = text[start]
    if delimiter in "\r\n":
        # ``\r\n`` 对是一个行尾——``\r`` 定界 + 紧邻 ``\n`` 时跨过整个 eol，
        # 逐字内容从下个字开始、到下一行尾终结（latex 实证）。但空白跳过
        # 后落行尾则不定界：被遮区段留下的空格会桥到行间 ``\r\n`` 上产出
        # 假 span 吞掉同行真实内容，破坏 ``mask_tex`` 幂等。
        off = 2 if text[start : start + 2] == "\r\n" else 1
        nl = None if skipped else _NL_RX.search(text, start + off)
        return None if nl is None else (start + off, nl.start(), nl.start() + 1)
    end = text.find("}" if delimiter == "{" else delimiter, start + 1)
    nl = _NL_RX.search(text, start)
    newline = -1 if nl is None else nl.start()
    if end < 0 or (newline >= 0 and newline < end):
        return None
    return (start + 1, end, end + 1)


#: memo 上界：normalize 一次工程内同份文本被 13+ pass 复扫（B14 画像
#: fix#5），内容键 lru_cache 消重——键即输入对象，改写管线 pass 间文本
#: 一旦变动自然换新键，无陈旧命中面。条数封顶 + 单件输入阈值防巨型件
#: pin 双份内存；超阈直调实现，行为不变仅失加速。
_MEMO_MAXSIZE: Final = 512
_MEMO_MAX_INPUT: Final = 2 << 20


def mask_tex(text: str, *, mask_dead: bool = True, keep_verbatim: bool = False) -> str:
    r"""逐字环境 + 失活环境 + ``\verb``/``\lstinline`` + 行内 ``%`` 的等长遮盖视图。

    offset/行号与原文字节级对齐（``\n`` 保留）。顺序敏感：先吃逐字环境
    （``\verb|%|`` 里的 ``%`` 不是注释），再遮行内 ``%``。

    ``\begin{env}`` 只在花括号深度 0 开环境——宏定义体/参数内的字面
    ``\begin{comment}``/``\begin{verbatim}`` 不执行（``\bc``/``\ec`` 别名
    形态），误开会吞到 EOF。

    ``mask_dead=False`` 供 comment.sty 手术自身——``\end{comment}`` 行尾
    空白修复需要看见 comment 环境内部。
    ``keep_verbatim=True`` 供检测类消费（arxiv 定位/嗅探）——逐字环境体
    原样保留（其中 ``%`` 仍不算注释），不遮盖；计数场景需要这些字面量。
    """
    if len(text) > _MEMO_MAX_INPUT:
        return _mask_tex(text, mask_dead=mask_dead, keep_verbatim=keep_verbatim)
    return _mask_tex_memo(text, mask_dead=mask_dead, keep_verbatim=keep_verbatim)


def _mask_tex(  # noqa: C901 -- 深度门新增两分支即语义面
    text: str, *, mask_dead: bool = True, keep_verbatim: bool = False
) -> str:
    chars = list(text)

    def mask(start: int, stop: int) -> None:
        chars[start:stop] = [c if c in "\r\n" else " " for c in text[start:stop]]

    i = 0
    n = len(text)
    depth = 0
    while i < n:
        if text[i] == "%":
            nl = _NL_RX.search(text, i)
            stop = n if nl is None else nl.start()
            mask(i, stop)
            i = stop
            continue
        if text[i] == "{":
            depth += 1
            i += 1
            continue
        if text[i] == "}":
            depth = max(depth - 1, 0)
            i += 1
            continue
        if text[i] != "\\":
            i += 1
            continue
        env = _VERBATIM_BEGIN_RX.match(text, i)
        is_verbatim = env is not None
        if env is None and mask_dead:
            env = _DEAD_BEGIN_RX.match(text, i)
        # 花括号内 ``\begin{env}`` 不是活环境开——宏定义/参数体内的字面
        # 序列（verbatim 本就不能进参；``\newcommand{\bc}{\begin{comment}}``
        # 别名形态若误开环境且无行锚 ``\end{comment}`` 会吞到 EOF，
        # corpus_daily 2609.20015 ``no_main_tex`` 实证）。
        if env is not None and depth == 0:
            stop = _env_stop(text, env[1], env.end(), dead=not is_verbatim)
            if not (keep_verbatim and is_verbatim):
                mask(i, stop)
            i = stop
            continue
        verb = _inline_verb_span(text, i, n)
        if verb is not None:
            content_a, content_b, verb_end = verb
            mask(content_a, content_b)
            i = verb_end
            continue
        command = _COMMAND_RX.match(text, i)
        # match.end() 是绝对 offset——必须赋值不是累加（旧实现 i+=end 会把
        # i 推到 ~2i，大段注释逃逸遮盖）。
        i = command.end() if command else i + 1
    return "".join(chars)


_mask_tex_memo = lru_cache(maxsize=_MEMO_MAXSIZE)(_mask_tex)


def iter_depth0(rx: re.Pattern[str], vis: str) -> Iterator[re.Match[str]]:
    r"""``rx`` 在遮盖视图上、起始位置 brace 深度 0 的全部命中。

    花括号配对走查随 finditer 游标推进；``\\`` 双字符跳过不吃配对。
    ``\bgroup``/``[..]`` 非字符花括号不计深度——与 TeX 语义一致。
    ``inject.find_docclass_ends`` 与 ``latex209._primary_docstyle`` 共用
    （原逐字复抄，单源后落本模块——两层都不能反依赖 compile 层）。
    """
    depth = 0
    pos = 0
    for m in rx.finditer(vis):
        while pos < m.start():
            c = vis[pos]
            if c == "\\":
                pos += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            pos += 1
        pos = m.end()
        if depth == 0:
            yield m
