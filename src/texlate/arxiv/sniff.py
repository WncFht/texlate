r"""e-print 线缆格式判别与 pdf_wrapper 源码壳检测（docs/06 §2.1）。

判别顺序（魔数优先，content-disposition 只作预检提示）::

    bytes[0:2] == 1f 8b   → gzip 封装
      └ gunzip → offset 257 起 "ustar" → tar 多文件
                 否则                  → 单文件 .tex 本体
    bytes[0:4] == "%PDF"  → PDF 直投（无源码 → sidecar）
    其他                  → 遗留格式告警（实测已绝迹，95% 上界 <1.6%）

另补一条 docs 未写的廉价分支：裸 blob 直接命中 ustar → 未压缩 tar
（arXiv 历史上出现过未压缩 tar 提交）。

第四态 ``pdf_wrapper``：源码包合法、有 ``\documentclass``，但正文是
``\includepdf``/``\pdfpages`` 壳（1412.6980v9 实证）。hasSrc 之外加正文
含量检测：剥 preamble 后 section==0 ∧ 文本 <2KB → 判 wrapper，走降级链。
"""

from __future__ import annotations

import gzip
import io
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from texlate.arxiv._texutil import strip_comments
from texlate.textutil import BEGIN_DOC_RX

GZIP_MAGIC: Final = b"\x1f\x8b"
PDF_MAGIC: Final = b"%PDF"
USTAR_MAGIC: Final = b"ustar"
USTAR_OFFSET: Final = 257
USTAR_LEN: Final = 5

#: 解包规格上限（docs/06 §2.2）：解压总量 ≤512MB。
MAX_INFLATED: Final = 512 * 1024 * 1024
#: pdf_wrapper 正文含量阈值：剥 preamble 后可见文本 <2KB。
WRAPPER_TEXT_CAP: Final = 2048


class BlobKind(StrEnum):
    """e-print 线缆格式。"""

    TAR = "tar"
    SINGLE = "single_gz"
    PDF = "pdf"
    UNKNOWN = "unknown"


class SniffError(Exception):
    """gzip 封装损坏等无法判别的错误。"""


@dataclass(frozen=True, slots=True)
class SniffResult:
    """魔数判别结果。

    ``payload`` 是 gunzip 后的字节（tar / single_gz 两态）；``oversized``
    为 True 时解压流超过 MAX_INFLATED，payload 置 None，由 unpack 层拒绝。
    """

    kind: BlobKind
    payload: bytes | None
    raw_size: int
    inflated_size: int | None = None
    oversized: bool = False


def _gunzip(blob: bytes, cap: int) -> tuple[bytes | None, int, bool]:
    """有上限的 gunzip。返回 (payload, inflated_size, oversized)。"""
    out = io.BytesIO()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(blob)) as gz:
            while True:
                chunk = gz.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                if out.tell() > cap:
                    return None, out.tell(), True
    except (OSError, EOFError) as e:
        msg = f"corrupt gzip stream: {e}"
        raise SniffError(msg) from e
    data = out.getvalue()
    return data, len(data), False


def _is_tar(payload: bytes) -> bool:
    return len(payload) >= USTAR_OFFSET + USTAR_LEN and (
        payload[USTAR_OFFSET : USTAR_OFFSET + USTAR_LEN] == USTAR_MAGIC
    )


def sniff(blob: bytes, *, max_inflated: int = MAX_INFLATED) -> SniffResult:
    """判别 e-print 原始字节格式。tar/single_gz 顺带返回解压后字节。"""
    if blob[:4] == PDF_MAGIC:
        return SniffResult(kind=BlobKind.PDF, payload=None, raw_size=len(blob))
    if blob[:2] == GZIP_MAGIC:
        payload, inflated, oversized = _gunzip(blob, max_inflated)
        if oversized or payload is None:
            return SniffResult(
                kind=BlobKind.TAR,  # 种类未定，先按 gzip 记；oversized 为拒绝信号
                payload=None,
                raw_size=len(blob),
                inflated_size=inflated,
                oversized=True,
            )
        kind = BlobKind.TAR if _is_tar(payload) else BlobKind.SINGLE
        return SniffResult(
            kind=kind, payload=payload, raw_size=len(blob), inflated_size=inflated
        )
    if _is_tar(blob):
        # 未压缩 tar：历史上存在，免费兼容
        return SniffResult(
            kind=BlobKind.TAR, payload=blob, raw_size=len(blob), inflated_size=len(blob)
        )
    return SniffResult(kind=BlobKind.UNKNOWN, payload=None, raw_size=len(blob))


# ---------------------------------------------------------------------------
# pdf_wrapper 源码壳检测（第四态）


@dataclass(frozen=True, slots=True)
class WrapperVerdict:
    r"""pdf_wrapper 判定结果。

    ``is_wrapper`` = 有 includepdf 类命令 ∧ section==0 ∧ 可见文本 <2KB
    （1412.6980v9 校准：298B 源码、正文仅一条 ``\\includepdf``）。
    ``is_stub`` 放宽 includepdf 要求——正文退化的其他形态也标出。
    """

    is_wrapper: bool
    is_stub: bool
    has_includepdf: bool
    n_sections: int
    body_text_bytes: int
    matched: list[str] = field(default_factory=list)


_END_DOC_RE: Final = re.compile(r"\\end\s*\{document\}")
# \includepdf / \includepdfmerge / \includepdfset（pdfpages 宏包）
_INCLUDEPDF_RE: Final = re.compile(r"\\includepdf\w*")
_SECTION_RE: Final = re.compile(
    r"\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*\{"
)
# 控制序列 + 参数括号 + 花括号整段剥掉，剩下的近似「可见文本」
_COMMAND_RE: Final = re.compile(
    r"\\[a-zA-Z@]+\*?\s*(\[[^\]]*\])?\s*(\{[^{}]*\})?|\\[\\{}$&%#_^~]|\\."
)
_BRACE_RE: Final = re.compile(r"[{}]")


def _body_text(source: str) -> str:
    m = BEGIN_DOC_RX.search(source)
    if not m:
        return ""
    end = _END_DOC_RE.search(source, m.end())
    return source[m.end() : end.start() if end else len(source)]


def _visible_text(body: str) -> str:
    """剥命令/括号/注释后剩下的近似可见文本。"""
    text = _COMMAND_RE.sub(" ", body)
    text = _BRACE_RE.sub(" ", text)
    return " ".join(text.split())


def check_pdf_wrapper(
    source: str, *, text_cap: int = WRAPPER_TEXT_CAP
) -> WrapperVerdict:
    r"""检测 includepdf 包装壳。``source`` 为主文件全文（未剥注释亦可）。"""
    stripped = strip_comments(source)
    body = _body_text(stripped)
    includepdf_hits = _INCLUDEPDF_RE.findall(body)
    n_sections = len(_SECTION_RE.findall(body))
    text_bytes = len(_visible_text(body).encode("utf-8", "replace"))
    is_stub = n_sections == 0 and text_bytes < text_cap
    return WrapperVerdict(
        is_wrapper=bool(includepdf_hits) and is_stub,
        is_stub=is_stub,
        has_includepdf=bool(includepdf_hits),
        n_sections=n_sections,
        body_text_bytes=text_bytes,
        matched=sorted(set(includepdf_hits)),
    )
