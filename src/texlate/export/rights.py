"""EPUB 是否声明了技术保护措施（bbm ``rights.py`` 移植）。

规避 TPM 在大多数司法辖区违法（DMCA §1201、EUCD Art. 6、日本著作权法
30-1），所以带保护的书直接拒开，没有任何开关放行。本模块只做*检测*：
不持有任何密钥材料、不做任何解密，且必须保持这样。

刻意保持零阅读器依赖：检查在任何阅读器接手之前运行（defusedxml 只是
stdlib ET 的实体攻击护栏，不是阅读器）。
"""

from __future__ import annotations

import zipfile
import zlib
from typing import TYPE_CHECKING

import defusedxml.ElementTree

if TYPE_CHECKING:
    from pathlib import Path
from defusedxml.common import DefusedXmlException

DRM_MESSAGE = (
    "This EPUB is protected by DRM and cannot be translated; "
    "the tool does not and will not remove it."
)

#: 厂商 rights 文件存在即保护：Adobe ADEPT/Nook（rights.xml）、Readium LCP
#: （license.lcpl）、Apple FairPlay（sinf.xml）。META-INF/signatures.xml
#: 刻意缺席——签名断言完整性而非保护，翻译一本书本来就会使签名失效。
PROTECTION_FILES = frozenset(
    {
        "META-INF/rights.xml",
        "META-INF/license.lcpl",
        "META-INF/sinf.xml",
    }
)

ENCRYPTION_FILE = "META-INF/encryption.xml"

#: encryption.xml 同时也是字体混淆的声明地，那不是保护：它搅乱嵌入字体以
#: 遵守字体厂商许可，内容文档仍是明文。其余算法（xmlenc#aes128-cbc、
#: aes256-cbc……）加密的是内容。
FONT_OBFUSCATION = frozenset(
    {
        "http://www.idpf.org/2008/embedding",
        "http://ns.adobe.com/pdf/enc#RC",
    }
)

#: ``encryption.xml`` 声明体读取上限——真书该文件 KB 级；仿 ``share.py``
#: ``_MANIFEST_MAX`` 的 1MB 闸精神，超限声明按"读不懂"判 ``"drm"``。
_DECLARATION_MAX = 1 << 20


def _local_name(tag: object) -> str:
    """去命名空间的元素名。

    按 local name 匹配是刻意的：下面的元素在合规产物里只会以 xmlenc
    命名空间出现，但信任命名空间的检查会让不合规产物把 AES 声明藏在
    明处——本检查恰恰为不老实的文件存在。
    """
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def check_epub(path: Path | str) -> str:  # noqa: C901, PLR0911 -- 每条 return 即一条 DRM 判定规则，表格式控制流
    """``path`` 声明保护措施返回 ``"drm"``，否则 ``"ok"``。

    不是 zip、或不存在的文件返回 ``"ok"``——这不是声称它是干净 EPUB，
    而是拒绝替别人报错：下一个打开它的读取器会给出准确得多的诊断
    （"not a zip file"、"no such file"），在这里抛错只会把好诊断换成
    糊涂诊断。解析不了的 ``encryption.xml`` 返回 ``"drm"``——读不懂的
    声明不能按无害读。
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if names & PROTECTION_FILES:
                return "drm"
            if ENCRYPTION_FILE not in names:
                return "ok"
            try:
                with archive.open(ENCRYPTION_FILE) as fp:
                    # 目录 file_size 可谎报——按上限 +1 截断读，防"声明小、
                    # 实解大"解压放大（``share.py`` ``_MANIFEST_MAX`` 同款闸）
                    declaration = fp.read(_DECLARATION_MAX + 1)
            except (
                OSError,
                ValueError,
                KeyError,
                RuntimeError,
                NotImplementedError,  # 未知压缩方法
                zipfile.BadZipFile,  # 成员级坏 CRC——此前漏进外层归 ok，与本臂契约相悖
                zlib.error,  # deflate 流中段坏
            ):
                return "drm"
            if len(declaration) > _DECLARATION_MAX:
                return "drm"
    except (OSError, ValueError, zipfile.BadZipFile):
        # ValueError 两臂分工：内层=声明读不出按有害判 drm；外层=文件开不了
        # （内嵌 NUL 的路径走 io.open 抛 ValueError，非 OSError 子类）归 ok。
        return "ok"

    try:
        root = defusedxml.ElementTree.fromstring(declaration)
    except (defusedxml.ElementTree.ParseError, DefusedXmlException):
        return "drm"

    # 白名单而非黑名单：仅当每个被声明资源都被确证为字体混淆才算明文。
    # 不报算法的条目、报我们不认识算法的条目、把方法藏在检查没看的位置的
    # 条目，对本工具而言都算保护——判反的代价是帮助规避。
    entries = [el for el in root.iter() if _local_name(el.tag) == "EncryptedData"]
    if not entries:
        return "drm"
    for entry in entries:
        # 只认直属子节点：EncryptionMethod 描述的是*本*资源的加密方式，唯一
        # 合法位置就是 EncryptedData 正下方——停在更深处的副本（比如
        # CipherData 里）什么都不声明，把它当声明读正是"引错位置的字体算法
        # 给 AES 加密书放行"的剧本。
        algorithms = [
            el.get("Algorithm")
            for el in entry
            if _local_name(el.tag) == "EncryptionMethod"
        ]
        if not algorithms:
            return "drm"
        if any(algorithm not in FONT_OBFUSCATION for algorithm in algorithms):
            return "drm"
    return "ok"
