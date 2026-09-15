r"""文本小件单源 —— 注释/逐字遮盖 + 封顶 Levenshtein + 逐字环境注册表。

``mask_comments``：``\`` 后随字符整体跳过（``\%``/``\\%`` 语义正确），
未转义 ``%`` 到行尾替换为等长空格——offset/长度与原文逐字节对齐，
供正则/下标直接使用。**不处理 verbatim 环境**。

``mask_tex``：等长遮盖视图 = 逐字族环境体 + comment 失活环境 + 行内
``\verb``/``\lstinline`` + 行内 ``%`` 注释。定位视图 ≠ 改写目标——masked
view 绝不能拷回原文（``compile.mask`` 的手术都在原文回放）。

``VERBATIM_ENVS``/``DEAD_ENVS``：逐字/失活环境清单的单一事实源——并集自
原 compile.mask、arxiv._texutil、latex.tables 三处漂移清单。

``lev_capped``：带 early-exit 上限的 Levenshtein——L0 占位符拼写配对与
xlat 轻量对账共用一个实现，防两份 DP 各自漂移。

``decode_tex``：arXiv 源码字节 → str 的兜底解码链。语料实测 ~3.6% 的
.tex 不是 UTF-8（gb18030/latin-1 系）——裸 ``errors="replace"`` 会把
正文炸成 U+FFFD 喂给翻译层。
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "CJK_RANGES",
    "CJK_RX",
    "DEAD_ENVS",
    "VERBATIM_ENVS",
    "decode_tex",
    "is_cjk_cp",
    "lev_capped",
    "mask_comments",
    "mask_tex",
]


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
            while j < n and text[j] != "\n":
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


def _env_stop(text: str, env: str, pos: int) -> int:
    r"""从 pos 找 ``\end{env}``，返回其结束后 offset；找不到返回 len(text)。"""
    ending = re.search(r"\\end\s*\{" + re.escape(env) + r"\}", text[pos:])
    return pos + ending.end() if ending else len(text)


def _inline_verb_end(text: str, i: int, n: int) -> int | None:
    r"""``\verb``/``\lstinline`` 行内区段的结束 offset；不合法形态返回 None。

    ``\lstinline`` 允许 ``[opt]`` 前缀；定界符取首个非空白字符，
    ``{`` 定界时配 ``}``；未闭合或跨行不算（交回主循环逐字符扫）。
    """
    inline = re.match(r"\\(verb\*?|lstinline\*?)(?![A-Za-z@])", text[i:])
    if not inline:
        return None
    start = i + inline.end()
    if inline[1].startswith("lstinline"):
        options = re.match(r"\s*(?:\[[^\]\n]*\]\s*)?", text[start:])
        start += options.end()
    if start >= n or text[start].isspace():
        return None
    delimiter = text[start]
    end = text.find("}" if delimiter == "{" else delimiter, start + 1)
    newline = text.find("\n", start)
    if end < 0 or (newline >= 0 and newline < end):
        return None
    return end + 1


def mask_tex(text: str, *, mask_dead: bool = True, keep_verbatim: bool = False) -> str:
    r"""逐字环境 + 失活环境 + ``\verb``/``\lstinline`` + 行内 ``%`` 的等长遮盖视图。

    offset/行号与原文字节级对齐（``\n`` 保留）。顺序敏感：先吃逐字环境
    （``\verb|%|`` 里的 ``%`` 不是注释），再遮行内 ``%``。

    ``mask_dead=False`` 供 comment.sty 手术自身——``\end{comment}`` 行尾
    空白修复需要看见 comment 环境内部。
    ``keep_verbatim=True`` 供检测类消费（arxiv 定位/嗅探）——逐字环境体
    原样保留（其中 ``%`` 仍不算注释），不遮盖；计数场景需要这些字面量。
    """
    chars = list(text)

    def mask(start: int, stop: int) -> None:
        chars[start:stop] = ["\n" if c == "\n" else " " for c in text[start:stop]]

    i = 0
    n = len(text)
    while i < n:
        if text[i] == "%":
            stop = text.find("\n", i)
            stop = n if stop < 0 else stop
            mask(i, stop)
            i = stop
            continue
        if text[i] != "\\":
            i += 1
            continue
        env = _VERBATIM_BEGIN_RX.match(text, i)
        is_verbatim = env is not None
        if env is None and mask_dead:
            env = _DEAD_BEGIN_RX.match(text, i)
        if env:
            stop = _env_stop(text, env[1], i + env.end())
            if not (keep_verbatim and is_verbatim):
                mask(i, stop)
            i = stop
            continue
        verb_end = _inline_verb_end(text, i, n)
        if verb_end is not None:
            mask(i, verb_end)
            i = verb_end
            continue
        command = _COMMAND_RX.match(text, i)
        # match.end() 是绝对 offset——必须赋值不是累加（旧实现 i+=end 会把
        # i 推到 ~2i，大段注释逃逸遮盖）。
        i = command.end() if command else i + 1
    return "".join(chars)


def decode_tex(blob: bytes) -> str:
    """解码 arXiv 源码：UTF-8(BOM) → gb18030 → cp1252 → latin-1 兜底链。

    latin-1 永不失败——latin-5/latin-9 源会带 U+FFFD 风险留给编译层
    ``Invalid UTF-8 byte`` 判据兜底（docs/08 §4.3）。
    """
    for encoding in ("utf-8-sig", "gb18030", "cp1252", "latin-1"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    return blob.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- CJK 码点面

#: CJK 统一表意码点面：扩A + 基本区 + 兼容区 + 〇（U+3007，日期用字）
#: + 扩B~F（U+20000–2FA1F）。judge/l0/l2 三处计数曾各自漂移（judge 缺
#: 〇、l0 只有三区、l2 扩F 截断在 2EBEF）——单源化后口径唯一。
CJK_RANGES: Final = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x3007, 0x3007),
    (0x20000, 0x2FA1F),
)

#: ``CJK_RANGES`` 的字符类形态（``findall`` 计数用）。
CJK_RX: Final = re.compile(
    "["
    + "".join(f"{chr(lo)}-{chr(hi)}" if lo != hi else chr(lo) for lo, hi in CJK_RANGES)
    + "]"
)


def is_cjk_cp(cp: int) -> bool:
    """码点是否落在 ``CJK_RANGES``（``Missing character:`` 码点判定用）。"""
    return any(lo <= cp <= hi for lo, hi in CJK_RANGES)


def lev_capped(a: str, b: str, cap: int) -> int:
    """Levenshtein 距离，超 cap 提前返回 cap+1。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        rowmin = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            rowmin = min(rowmin, v)
        if rowmin > cap:
            return cap + 1
        prev = cur
    return prev[-1]
