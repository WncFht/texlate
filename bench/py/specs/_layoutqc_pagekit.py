"""specs._layoutqc_pagekit — 跨通道共享页判定件 (_layoutqc 拆分叶).

poppler 子进程包 (``_run``) + 页家具判定 (folio 行解/结构性页首/
verso 白页豁免)——textcheck 与 rastercheck 双臂共用的页级口径件。
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from specs._layoutqc_thresh import (
    _FOLIO_RX,
    _ROMAN_DIGIT,
    _STRUCT_HEAD_RX,
    FRONTMATTER_PAGES,
    POPPLER_TIMEOUT,
)

if TYPE_CHECKING:
    from pathlib import Path


def _struct_head(head: str, doc_title: str | None = None) -> bool:
    """页首行是否结构性标题（verso/分隔白页豁免的佐证判）。

    ``doc_title``=splice tex ``\\title`` 参数 squash 串——标题页
    首行即论文标题本身（``Universitá`` 式机构行之外的另一族无
    关键字页首，1503.00131 实证）：head squash 与 title 互为前缀
    即中（截断抽取/题+副题单行都盖）。"""
    if _STRUCT_HEAD_RX.match(head):
        return True
    hk = re.sub(r"\s+", "", head)
    return bool(
        doc_title
        and len(doc_title) >= 6
        and len(hk) >= 4
        and (doc_title.startswith(hk) or hk.startswith(doc_title))
    )


def _folio_val(ln: str) -> int | None:
    """folio 行→页码整数（阿拉伯/罗马数字）；非 folio 行返 None。

    verso 判定的真口径：frontmatter 罗马码段让 PDF 序数与印刷页码
    错位（1812.00314 实证），能读到 folio 就以它为准。"""
    s = ln.strip()
    if not s or not _FOLIO_RX.match(ln):
        return None
    if s.isdigit():
        return int(s)
    vals = [_ROMAN_DIGIT.get(c) for c in s.lower()]
    if any(v is None for v in vals):
        return None
    tot = 0
    for k, v in enumerate(vals):
        tot += -v if k + 1 < len(vals) and v < vals[k + 1] else v
    return tot or None


def _verso_blank(
    pi: int, text_page: str, twoside: bool, blankpage_marker: bool
) -> bool:
    """单页级 verso 豁免（pdftotext 页文本口径）。

    - 页自带 folio 可解 → folio 偶数即 verso（twoside 限定）；folio
      缺席退回 PDF 序数 (pi+1)%2 旧口径；
    - frontmatter 域 + twoside + tex 有 \\blankpage 族标记 → 佐证压
      （只当前 N 页，全篇不适用）。"""
    if not twoside:
        return False
    folio = next(
        (v for ln in text_page.splitlines() if (v := _folio_val(ln)) is not None),
        None,
    )
    if folio is not None:
        return folio % 2 == 0
    if (pi + 1) % 2 == 0:
        return True
    # frontmatter 域（roman 偏移使 PDF 序数与 folio 奇偶错开，
    # 1812.00314 实证击穿序数判）+ twoside → 空页全 verso 授权；
    # 原 \blankpage 族标记臂（同限 frontmatter 域）被全域判吸收，
    # 参数保留给调用面记账——域外空页仍不得豁免（0928 裁定）。
    return pi < FRONTMATTER_PAGES


def _run(
    argv: list[str], cwd: Path | None = None, *, timeout: float = POPPLER_TIMEOUT
) -> str:
    """poppler 子进程包——超时/缺席一律空串（调用方按缺席降级）。"""
    try:
        r = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout or ""
