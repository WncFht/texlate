"""行内 marker 占位协议（bbm ``markers.py`` 移植，token 皮换成 ``[[TAG_n]]``）。

受保护且*短*的行内元素（exclude 的 ``<code>``/``<sup>``、``<img>`` 等渲染
空元素）在送模型文本里变成占位 token，写回时以源元素克隆落位——``[[IMG_1]]``
形态与 LaTeX 侧 ``PH_RX`` 同构，``xlat.placeholders.diff`` 多重集对账、
``encode_newlines``、MockTranslator token 保留全部零改动复用。

照抄 bbm 的两条硬规则（pinned 决策）：

- 碰撞回避：token 若在被送文本里已逐字出现则重新编号，保证恰好出现一次。
- 宽容调和：回复里没发过的 marker 形 token 一律剥掉；发了的丢了在句尾按
  源序补回——绝不因 marker 重试。配对 marker 划出范围（v1 不做）。
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 含词行内保护物变 marker 的渲染字符上限；超过则保持 barrier 切 run
INLINE_MARKER_MAX_CHARS = 40
#: 无词内容（URL/排开公式）的放宽上限——它是一枚原子，不按阅读长度计
INLINE_MARKER_WORDLESS_MAX_CHARS = 400

#: URL/路径/邮箱/标识符的黏着字符——两侧贴这些字符的字母 run 是原子碎片不是词
_TOKEN_GLUE = r"[0-9A-Za-z_./:#?=&%~@+\-]"  # noqa: S105 -- 正则字符类，非凭据

#: 一个"词" = ≥4 个 unicode 字母且两侧无黏着字符（CJK run 同样算词——其标点
#: 不是黏着符，run 仍会在句读处断开）。4 而非 3：数学短函数名 det/dim/sin/log
#: 会坐在全数字公式里被误判为词。
_PROSE_WORD_RE = re.compile(rf"(?<!{_TOKEN_GLUE})[^\W\d_]{{4,}}(?!{_TOKEN_GLUE})")


def _erase_marks(text: str) -> str:
    r"""扫描前抹掉组合记号与零宽连接符。

    天城文类文字的元音记号否则被 ``[^\W\d_]`` 读成非字母，整句印地语
    被误判 wordless。
    """
    return "".join(
        c for c in text if c not in "‌‍" and unicodedata.category(c) not in ("Mn", "Mc")
    )


def is_wordless(text: str) -> bool:
    """渲染文本是否一个散文词都没有（URL/公式/数字串 → True）。

    只服务于 marker 上限的选取，永远不参与"是否保护"的判定。
    """
    return _PROSE_WORD_RE.search(_erase_marks(text or "")) is None


#: marker 形 token 识别——与我方占位符同构 ``[[TAG_n]]``；额外吃 ``[[TAG]]``
#: 裸形，清洗侧好把模型臆造的无号变体也剥掉。刻意收窄：无空白、长度封顶，
#: 防止散文里的方括号吞掉半段。
MARKER_RE = re.compile(r"\[\[[A-Z_]{1,32}\d*\]\]")

_NAME_RE = re.compile(r"[^A-Z_]+")


def marker_name(tag_name: str | None) -> str:
    """Token 的名字半部：tag 名归约成 ``[A-Z_]+``（``h1``→``H``，``code``→``CODE``）。"""
    name = _NAME_RE.sub("", (tag_name or "").upper())
    return name or "X"


def marker_token(name: str, ordinal: int) -> str:
    """拼 ``[[NAME_n]]``。"""
    return f"[[{name}_{ordinal}]]"


class Ordinals:
    """单调序号供给，每文档一份。

    序号只需在单次请求内唯一（请求不跨文档），按文档编号足够且稳定。
    """

    def __init__(self, start: int = 1) -> None:
        """``start`` = 起始序号。"""
        self.next = start

    def allocate(
        self, tag_name: str | None, *, occupied: str = "", taken: Iterable[str] = ()
    ) -> str:
        """给 ``tag_name`` 发一个在 ``occupied`` 文本里逐字缺席的 token。

        ``occupied`` 是 token 即将植入的文本；``taken`` 是已植入的 token 集。
        重编号就是全部意义：源文逐字印着 ``[[IMG_1]]`` 的书绝不能拿到同形占位符。
        """
        name = marker_name(tag_name)
        taken_set = set(taken)
        while True:
            token = marker_token(name, self.next)
            self.next += 1
            if token not in occupied and token not in taken_set:
                return token


def find_markers(text: str | None) -> list[str]:
    """``text`` 中的 marker 形 token，按首次出现序、去重。"""
    found: list[str] = []
    for match in MARKER_RE.finditer(text or ""):
        token = match.group(0)
        if token not in found:
            found.append(token)
    return found


def _issued_and_literal(
    sent: str, issued: Iterable[str] | None
) -> tuple[list[str], list[str]]:
    """把 ``sent`` 里的 marker 形 token 分成"我方发出的"与"书自己的"。

    没发过的同形 token 是源文自有字面文本（碰撞回避已保证不重用），它不代表
    任何节点——不去重、不补回、更不可清洗（洗掉等于删作者写的字）。
    """
    shaped = find_markers(sent)
    if issued is None:
        return shaped, []
    issued_list = list(issued)
    return issued_list, [token for token in shaped if token not in issued_list]


def reconcile_markers(
    sent: str, reply: str | None, issued: Iterable[str] | None = None
) -> str:
    """把回复的 marker 调成与发出一致。绝不抛错。

    臆造 token 剥掉、已发 token 的重复出现剥掉、丢了的按源序补到句尾。
    回复本已一致时逐字节原样返回——常态零成本。
    """
    if reply is None:
        reply = ""
    issued_list, literal = _issued_and_literal(sent, issued)
    seen: list[str] = []

    def keep(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in issued_list:
            if token in seen:
                return ""
            seen.append(token)
            return token
        if token in literal:
            return token
        return ""

    out = MARKER_RE.sub(keep, reply)
    missing = [token for token in issued_list if token not in seen]
    if missing:
        out = (out.rstrip() + " " + " ".join(missing)).strip()
    return out


def marker_report(
    unit_name: str, sent: str, reply: str | None, issued: Iterable[str] | None = None
) -> str | None:
    """调和动作的一行描述；无事发生返回 ``None``。"""
    issued_list, literal = _issued_and_literal(sent, issued)
    got = find_markers(reply or "")
    missing = [token for token in issued_list if token not in got]
    invented = [
        token for token in got if token not in issued_list and token not in literal
    ]
    if not missing and not invented:
        return None
    parts = []
    if missing:
        parts.append(f"{len(missing)} marker(s) missing ({', '.join(missing)})")
    if invented:
        parts.append(f"{len(invented)} invented ({', '.join(invented)})")
    return f"{unit_name}: " + "; ".join(parts) + " — reconciled"


def split_on_markers(text: str, tokens: Iterable[str]) -> list[tuple[str, str]]:
    """``text`` 切成 ``("text"|"marker", value)`` 有序片段——写回的形状。"""
    tokens = list(tokens)
    if not tokens:
        return [("text", text)] if text else []
    pattern = re.compile("|".join(re.escape(t) for t in tokens))
    pieces: list[tuple[str, str]] = []
    position = 0
    for match in pattern.finditer(text):
        if match.start() > position:
            pieces.append(("text", text[position : match.start()]))
        pieces.append(("marker", match.group(0)))
        position = match.end()
    if position < len(text):
        pieces.append(("text", text[position:]))
    return pieces
