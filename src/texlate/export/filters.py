"""送模型前的文本过滤与归一化（bbm ``helper.py``/``plan.py`` 对应件）。

归一化 = 零宽字符剥除 + 空白折叠；过滤器判"不该送模型的文本"：纯数字、
纯 URL、``Figure N``/``Listing N``/``Source:``/ISBN 这类 apparatus 文本。
EPUB 与 DOCX 两条管线共用同一口径。
"""

from __future__ import annotations

import hashlib
import re
import string

from texlate.xlat.placeholders import is_placeholder_only

#: 零宽/软连字符：留在文档里，从送模型文本剥掉（软连字符把词切成半 token）
_INVISIBLE_CHARS_RE = re.compile("[\\u00ad\\u200b\\ufeff]")

#: XML 1.0 非法字符（Char 产生式的补集相关项）：控制字符除 \t\n\r、孤代理、
#: U+FFFE/U+FFFF。bs4 对它们逐字节透传、lxml 在序列化时硬炸——写回译文与
#: 出包序列化前必须剥除，否则产出物是连 XML 解析器都打不开的非法文档。
_XML_ILLEGAL_RE = re.compile(
    "[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\ud800-\\udfff\\ufffe\\uffff]"
)


def sanitize_xml_text(text: str) -> str:
    """剥掉 XML 1.0 非法字符（含 NUL——故 marker sentinel 不可用控制字符）。"""
    return _XML_ILLEGAL_RE.sub("", text)


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
#: ``Figure N``/``Listing N`` 短 apparatus 标签的长度帽（ISBN 由 ``_ISBN_RE``
#: 自判不吃本帽——``ISBN 978-0-...`` 本就短；帽只闸散文句不被 ``^Figure\s*\d``
#: 前缀误吞，如 ``Figure 3 shows ...`` 长句放行）
_APPARATUS_MAX = 80


def normalize_text(raw: str) -> str:
    """送模型文本的归一化：剥 XML 非法字符 + 零宽字符 + 折叠全部空白 run。"""
    return " ".join(_INVISIBLE_CHARS_RE.sub("", sanitize_xml_text(raw)).split())


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
            bool(_LISTING_RE.match(stripped)) and len(stripped) < _APPARATUS_MAX,
            bool(_FIGURE_RE.match(stripped)) and len(stripped) < _APPARATUS_MAX,
            all(c.isdigit() or c.isspace() for c in stripped) and bool(stripped),
            bool(_ISBN_RE.match(stripped)),
        ]
    )


def is_unit_text(text: str) -> bool:
    """送模型文本的枚举接受判据：非空 + 非 special/apparatus/纯占位。

    DOCX ``iter_units`` 与 EPUB ``iter_units`` 两处枚举（正文 run/NCX
    navLabel）同一口径——原 ``docx._is_unit_text`` 上收为本公开件。
    """
    return bool(text) and not (
        is_special_text(text) or is_apparatus_text(text) or is_placeholder_only(text)
    )


def job_digest(text: str) -> str:
    """``job_id`` 的内容锚：``sha256(text)[:16]``——断点续跑的稳定键。

    DOCX/EPUB 两侧 job_id 共用同一锚（``docx.iter_units``/``epub.units``）——
    ``[:16]`` 截断契约只有这一个定义点。
    """
    return hashlib.sha256(text.encode()).hexdigest()[:16]
