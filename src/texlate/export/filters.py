"""送模型前的文本过滤与归一化（bbm ``helper.py``/``plan.py`` 对应件）。

归一化 = 零宽字符剥除 + 空白折叠；过滤器判"不该送模型的文本"：纯数字、
纯 URL、``Figure N``/``Listing N``/``Source:``/ISBN 这类 apparatus 文本。
EPUB 与 DOCX 两条管线共用同一口径。
"""

from __future__ import annotations

import re
import string

#: 零宽/软连字符：留在文档里，从送模型文本剥掉（软连字符把词切成半 token）
_INVISIBLE_CHARS_RE = re.compile("[\\u00ad\\u200b\\ufeff]")

#: bbm helper.py 的 URL 正则（前缀匹配版与全串版分开用）
_URL_PATTERN = (
    r"(http[s]?://|www\.)+(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|"
    r"(?:%[0-9a-fA-F][0-9a-fA-F]))+"
)
_URL_TAIL_NUM = 80
_URL_TAIL_RE = re.compile(r".*" + _URL_PATTERN + r"$")
_PURE_URL_RE = re.compile(_URL_PATTERN)
_LISTING_RE = re.compile(r"^Listing\s*\d+")
_FIGURE_RE = re.compile(r"^Figure\s*\d+")
_ISBN_RE = re.compile(r"^[Ee]?ISBN\s*\d[\d\s]*$")
_ISBN_NUM = 80


def normalize_text(raw: str) -> str:
    """送模型文本的归一化：剥零宽字符 + 折叠全部空白 run 为单空格。"""
    return " ".join(_INVISIBLE_CHARS_RE.sub("", raw).split())


def is_special_text(text: str) -> bool:
    """纯数字/纯空白/纯标点/URL 开头——bbm ``_is_special_text`` 同口径。"""
    return (
        text.isdigit()
        or text.isspace()
        or bool(_PURE_URL_RE.match(text.strip()))
        or all(char in string.punctuation for char in text)
    )


def is_apparatus_text(text: str) -> bool:
    """``Figure N``/``Listing N``/``Source:``/ISBN/纯数字空白——bbm ``not_trans``。

    过滤器只拦整段 apparatus；``Figure 3 shows ...`` 这类散文不受影响
    （``_FIGURE_RE`` 命中但长度超帽即放行）。
    """
    stripped = text.strip()
    return any(
        [
            bool(_URL_TAIL_RE.match(stripped)) and len(stripped) < _URL_TAIL_NUM,
            stripped.startswith("Source: "),
            bool(_LISTING_RE.match(stripped)) and len(stripped) < _ISBN_NUM,
            bool(_FIGURE_RE.match(stripped)) and len(stripped) < _ISBN_NUM,
            all(c.isdigit() or c.isspace() for c in stripped) and bool(stripped),
            bool(_ISBN_RE.match(stripped)),
        ]
    )
