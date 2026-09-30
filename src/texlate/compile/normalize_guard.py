r"""compile.normalize_guard — 字节面前置守卫叶 (compile.normalize 域缝叶)。

支持件兼容前导块注入闸（``_prologue_ok``：strict-UTF-8 且探测窗无 NUL）
与 Mac Finder-info/资源叉前缀剥除（``_strip_lead_junk``：首个行首锚点前
含 NUL 才剥）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from texlate.textutil import EncodingVerdict

# ---------------------------------------------------------------- 伪装二进制闸
#: tar 伪装件判定宿于 ``textutil.targate._tar_disguised``（本件经 facade
#: import 消费——compile/latex 两层共用的字节闸不能锚在消费层，规格注记
#: 随迁）。本档残留件：支持件兼容前导块注入的 NUL 探测窗——
#: ``_transcode_one`` 漏网二进制闸同族；strict-UTF-8 字节面下 NUL 即非文本
#: 证据（0x00 是合法 UTF-8 码位，仅靠判定族分不出 ASCII+NUL 的 blob）。
_PROLOGUE_NUL_WINDOW: Final = 4096


def _prologue_ok(blob: bytes, verdict: EncodingVerdict) -> bool:
    """支持件兼容前导块注入闸：strict-UTF-8 解码且探测窗内无 NUL。"""
    return verdict.basis == "strict-utf8" and b"\x00" not in blob[:_PROLOGUE_NUL_WINDOW]


#: Mac Finder-info/资源叉前缀剥除窗——首个 ``\documentstyle``/``\documentclass``/
#: ``%&`` 行首锚点须落在窗内才认「真 TeX 起点」（cond-mat/0003309: 129B 垃圾
#: 块 ``TEXT*TEX``/``mBIN`` 压在 ``\documentstyle`` 前 → base 臂 Missing
#: \begin{document}）。窗外命中不剥——大 blob 后段碰巧含锚字面时剥除会腐蚀本体。
_LEAD_JUNK_WINDOW: Final = 4096

#: 行首锚点（``(?m)^`` 要 ``\n`` 或文件头在前）——锚点行是垃圾块的天然终点。
_LEAD_ANCHOR_RX: Final = re.compile(rb"(?m)^(?:\\documentstyle|\\documentclass|%&)")


def _strip_lead_junk(blob: bytes) -> bytes:
    r"""剥首个行首锚点前的 NUL 垃圾前缀；无锚/锚在 0/前缀纯文本 → 原样返回。

    NUL 是垃圾判别子——``\documentclass`` 前的纯文本前缀（许可证头/注释块）
    是合法作者内容，不含 NUL 一律不剥。``_neutralize_junk_files`` 按文件名覆写
    整件，拦不住真主件内嵌的二进制前缀——本臂补字节级缺面。
    """
    for m in _LEAD_ANCHOR_RX.finditer(blob[:_LEAD_JUNK_WINDOW]):
        if b"\x00" in blob[: m.start()]:
            return blob[m.start() :]
    return blob
