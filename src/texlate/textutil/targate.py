r"""tar 伪装二进制闸——arXiv 源码 blob 的 tar 伪装件判定。

``decode_tex`` 永不抛（latin-1 兜底）：tar 成员文本里可含
``\begin{document}``/``\documentclass``/``\fontfamily``，blob 解出的
"文本"照样命中各手术锚点——0707.0382 ``AMSbsy.sty`` 实为 1MB tar。
宿于独立底叶：compile/latex 两层共用（normalize/inject 手术面 +
api/flatten 翻译面 + fixloop 解包闸），不能锚在消费层。
"""

from __future__ import annotations

from typing import Final

#: tar 魔数探测窗——与 fixloop ``_tar_header_start`` 同口径（前 64KB 扫
#: ``ustar``、回推 257 验头），原生与被前置注入推位的变异 blob 通吃。
#: 兼容前导块前置把 ustar 推离 257 实案。
_TAR_SNIFF_WINDOW: Final = 65536
_TAR_MAGIC_OFF: Final = 257
_TAR_MAGIC: Final = b"ustar"
#: offset-257 魔数 + 版本域全宽 8B：POSIX ``ustar\0`` + ``00``，GNU
#: ``ustar`` + 2 空格 + ``\0``。``ustar}``/``ustarh``/``ustar(`` 等文本
#: 命中永不过此关（2410.17904 ``\mustar``/``\mustarh`` 宏名假阳实案——
#: fixloop 侧真 ``paper.tex`` 曾被改名 .tarblob → missing_file）。
_TAR_MAGIC_LEN: Final = 8
_TAR_MAGIC_FIELDS: Final = frozenset({b"ustar\x0000", b"ustar  \x00"})
#: tar chksum 字段（头内偏移 148，8 字节）——存值须等于 512B 头余字节
#: 按空格计之和；数据表里 ``012345␣␣`` 形态巧合过不了值校验，
#: 与魔数域双校验后假阳率近零。
_TAR_CHKSUM_OFF: Final = 148
_TAR_CHKSUM_LEN: Final = 8
_TAR_HEADER_LEN: Final = 512


def _tar_header_ok(head: bytes, start: int) -> bool:
    """Tar 头校验：name 首字节非 NUL + 魔数 + 版本域全宽 + 512B 校验和。

    ``start`` 为调用方 ``ustar`` 命中回推 ``_TAR_MAGIC_OFF`` 的头起点
    （``0 <= start < len(head)``）；``head`` 须给到 ``start+512`` 才让
    校验和层生效——窗尾命中不足 512B 按非 tar 拒。
    """
    if head[start] == 0:
        return False
    magic = head[start + _TAR_MAGIC_OFF : start + _TAR_MAGIC_OFF + _TAR_MAGIC_LEN]
    if magic not in _TAR_MAGIC_FIELDS:
        return False
    blk = head[start : start + _TAR_HEADER_LEN]
    if len(blk) < _TAR_HEADER_LEN:
        return False
    field = blk[_TAR_CHKSUM_OFF : _TAR_CHKSUM_OFF + _TAR_CHKSUM_LEN]
    digits = field.split(b"\x00")[0].strip()
    if not digits or any(c not in b"01234567" for c in digits):
        return False
    return int(digits, 8) == (
        sum(blk[:_TAR_CHKSUM_OFF])
        + _TAR_CHKSUM_LEN * 0x20
        + sum(blk[_TAR_CHKSUM_OFF + _TAR_CHKSUM_LEN :])
    )


def _tar_disguised(blob: bytes) -> bool:
    """Tar 伪装件判定：探测窗内 ``ustar`` 回推 ``_TAR_MAGIC_OFF`` 双校验。

    多读 ``_TAR_HEADER_LEN`` 让窗尾命中仍见全头（不足按非 tar 拒）。
    """
    head = blob[: _TAR_SNIFF_WINDOW + _TAR_HEADER_LEN]
    pos = head.find(_TAR_MAGIC)
    while pos != -1:
        start = pos - _TAR_MAGIC_OFF
        if start >= 0 and _tar_header_ok(head, start):
            return True
        pos = head.find(_TAR_MAGIC, pos + 1)
    return False
