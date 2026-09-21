"""zip 构造/加密声明/成员损坏公共件——``wzip``/``encdoc``/``ed``/``corrupt_member``。

canonical 出自 ``test_export_zip_guard``；``test_fuzz_export2`` 的
``_wzip``/``_encdoc``/``_ed`` 是同体孪生，差异已参数化并入：

- ``wzip``：``test_fuzz_export2._wzip`` 臂无 ``compress`` 参、恒
  ZIP_STORED——调用方按需传 ``compress=zipfile.ZIP_STORED`` 保原语义。
- ``ed``：``test_fuzz_export2._ed`` 臂多 ``alg=None`` → 裸
  ``<enc:EncryptionMethod/>`` 分支——并入 ``ed`` 默认值形，
  ``alg`` 为 ``None`` 时无 ``Algorithm`` 属性。

``test_fuzz_share._corrupt_member_data`` 是另一形（PK 扫描定位 +
新文件写出 + 覆写数据区首 8B），口径不同，不并入。
"""

from __future__ import annotations

import struct
import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def wzip(
    path: Path,
    members: dict[str, bytes],
    *,
    compress: int = zipfile.ZIP_DEFLATED,
) -> Path:
    """写 zip（成员序 = dict 序），``compress`` 控制全体成员压缩法。"""
    with zipfile.ZipFile(path, "w", compression=compress) as z:
        for name, blob in members.items():
            z.writestr(name, blob)
    return path


def encdoc(inner: bytes) -> bytes:
    """``encryption.xml`` 文档壳——``inner`` 为若干 ``<enc:EncryptedData>``。"""
    return (
        b'<?xml version="1.0"?>'
        b'<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        b'xmlns:enc="http://www.w3.org/2001/04/xmlenc#">' + inner + b"</encryption>"
    )


def ed(alg: str | None = None) -> bytes:
    """单条 ``<enc:EncryptedData>``——``alg=None`` 时无 ``Algorithm`` 属性。"""
    if alg is None:
        m = b"<enc:EncryptionMethod/>"
    else:
        m = f'<enc:EncryptionMethod Algorithm="{alg}"/>'.encode()
    return (
        b"<enc:EncryptedData>"
        + m
        + b'<enc:CipherData><enc:CipherReference URI=""/></enc:CipherData>'
        + b"</enc:EncryptedData>"
    )


def corrupt_member(path: Path, name: str) -> None:
    """翻转成员压缩数据中段 16B——CRC 必失配，deflate 流通常也坏。"""
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo(name)
    blob = bytearray(path.read_bytes())
    off = info.header_offset
    assert blob[off : off + 4] == b"PK\x03\x04"
    fn_len, ex_len = struct.unpack_from("<HH", blob, off + 26)
    start = off + 30 + fn_len + ex_len
    mid = start + info.compress_size // 2
    for i in range(mid, min(mid + 16, start + info.compress_size)):
        blob[i] ^= 0xFF
    path.write_bytes(bytes(blob))
