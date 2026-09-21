"""EPUB 拆包读入：DRM 预检 → zip 成员表 → container → OPF → 文档面枚举。"""

from __future__ import annotations

import posixpath
import zipfile
import zlib
from pathlib import Path
from urllib.parse import unquote

import defusedxml.ElementTree
from defusedxml.common import DefusedXmlException

from texlate.export.common import (
    DrmError,
    FixedLayoutError,
    MalformedEpubError,
)
from texlate.export.rights import DRM_MESSAGE, check_epub

from .model import EpubBook

CONTAINER_PATH = "META-INF/container.xml"
_CONTAINER_NS = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_OPF_NS = "{http://www.idpf.org/2007/opf}"

XHTML_MEDIA_TYPES = frozenset({"application/xhtml+xml", "text/html"})

#: 成员解压上限——上传 EPUB 是不可信面（``UPLOAD_CAP`` 只闸压缩态 80MB），
#: ``zf.read`` 无界解整成员即 inflate 炸弹面；粒度仿 ``share.py`` ``_MEMBER_MAX``
_EPUB_MEMBER_MAX = 256 << 20

#: 全本解压合计闸——``members`` 把全本解进内存，成员闸管单点、本闸管总量
#: （仿 ``share.py`` ``_INFLATED_MAX``）；80MB 压缩帽下真书放大远低于此
_EPUB_INFLATED_MAX = 512 << 20


def load_epub(src: Path | str) -> EpubBook:  # noqa: C901, PLR0912, PLR0915 -- 拆包校验每分支即一条 doc-formats.md 拒翻规则，拆开反而对不上 §2
    """读全本：DRM 预检 → zip 成员表 → container → OPF → 文档面枚举。"""
    if check_epub(src) == "drm":
        raise DrmError(DRM_MESSAGE)
    try:
        zf = zipfile.ZipFile(src)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        msg = f"不是可读 zip/EPUB: {Path(src).name} ({e})"
        raise MalformedEpubError(msg) from e
    with zf:
        infos = zf.infolist()
        members: dict[str, bytes] = {}
        order: list[str] = []
        inflated = 0
        for info in infos:
            if info.filename not in members:  # zip 重名条目只取首个
                if info.file_size > _EPUB_MEMBER_MAX:
                    msg = (
                        f"zip 成员 {info.filename} 声明解压大小超限:"
                        f" {info.file_size}B > {_EPUB_MEMBER_MAX}B"
                    )
                    raise MalformedEpubError(msg)
                try:
                    with zf.open(info) as fp:
                        # 目录 file_size 可谎报——上限 +1 截断读才是真闸
                        # （rights.py ``_DECLARATION_MAX`` 同款）
                        blob = fp.read(_EPUB_MEMBER_MAX + 1)
                except (
                    OSError,
                    RuntimeError,
                    NotImplementedError,
                    zipfile.BadZipFile,
                    zlib.error,  # deflate 流中段坏
                ) as e:
                    # 成员级坏 CRC/加密/未知压缩——裸 BadZipFile 会绕过 ExportError 族
                    msg = f"zip 成员 {info.filename} 读取失败: {e}"
                    raise MalformedEpubError(msg) from e
                if len(blob) > _EPUB_MEMBER_MAX:
                    msg = f"zip 成员 {info.filename} 解压超限: >{_EPUB_MEMBER_MAX}B"
                    raise MalformedEpubError(msg)
                inflated += len(blob)
                if inflated > _EPUB_INFLATED_MAX:
                    msg = f"EPUB 解压合计超限: >{_EPUB_INFLATED_MAX}B"
                    raise MalformedEpubError(msg)
                members[info.filename] = blob
                order.append(info.filename)

    if CONTAINER_PATH not in members:
        msg = f"缺 {CONTAINER_PATH}——不是 EPUB"
        raise MalformedEpubError(msg)
    try:
        container = defusedxml.ElementTree.fromstring(members[CONTAINER_PATH])
    except (defusedxml.ElementTree.ParseError, DefusedXmlException) as e:
        msg = f"container.xml 解析失败: {e}"
        raise MalformedEpubError(msg) from e
    rootfile = container.find(f".//{_CONTAINER_NS}rootfile")
    opf_path = rootfile.get("full-path") if rootfile is not None else None
    if not opf_path or opf_path not in members:
        msg = "container.xml 未给出有效 OPF full-path"
        raise MalformedEpubError(msg)
    opf_dir = posixpath.dirname(opf_path)
    try:
        opf = defusedxml.ElementTree.fromstring(members[opf_path])
    except (defusedxml.ElementTree.ParseError, DefusedXmlException) as e:
        msg = f"OPF 解析失败: {e}"
        raise MalformedEpubError(msg) from e

    # fixed-layout（pre-paginated）插译必破版式——警告级拒翻
    # （doc-formats.md §2 收尾「EPUB 特有注意点」段；亦见 §5 边界表）
    for meta in opf.iter(f"{_OPF_NS}meta"):
        if (
            meta.get("property") == "rendition:layout"
            and (meta.text or "").strip() == "pre-paginated"
        ):
            msg = "fixed-layout（pre-paginated）EPUB 不支持插译"
            raise FixedLayoutError(msg)

    def member_path(href: str) -> str | None:
        """Manifest ``href`` → zip 成员名：percent-decode 优先、原样兜底。

        OPF ``href`` 是 URI——``ch%201.xhtml`` 指成员 ``ch 1.xhtml``（真书
        InDesign/转换器产物）；``unquote`` 后缺席再试原样（成员名逐字印着
        ``%20`` 的畸形产物宽容）。
        """
        raw = href.split("#", 1)[0]  # manifest href 按 spec 无 fragment
        for cand in (unquote(raw), raw):
            path = posixpath.join(opf_dir, cand) if opf_dir else cand
            # ``../``/``./`` 是合法 URI 相对引用——不 normpath 会查无成员
            path = posixpath.normpath(path)
            if path in members:
                return path
        return None

    manifest: dict[str, tuple[str, str]] = {}
    ncx_path: str | None = None
    for it in opf.iter(f"{_OPF_NS}item"):
        iid = it.get("id")
        href = it.get("href")
        mtype = it.get("media-type") or ""
        if not iid or not href:
            continue
        manifest[iid] = (href, mtype)
        if mtype == "application/x-dtbncx+xml":
            ncx_path = member_path(href)

    spine: list[str] = [ir.get("idref") or "" for ir in opf.iter(f"{_OPF_NS}itemref")]
    docs: list[str] = []
    for idref in spine:
        entry = manifest.get(idref)
        if entry is None or entry[1] not in XHTML_MEDIA_TYPES:
            continue
        path = member_path(entry[0])
        if path is not None and path not in docs:
            docs.append(path)
    # spine 之外、manifest 里仍是 xhtml 的（不在 spine 的 nav/封面页）追加在尾
    for href, mtype in manifest.values():
        if mtype not in XHTML_MEDIA_TYPES:
            continue
        path = member_path(href)
        if path is not None and path not in docs:
            docs.append(path)
    if not docs:
        msg = "manifest 里没有可翻的 xhtml 文档"
        raise MalformedEpubError(msg)
    return EpubBook(members, order, docs, opf_path, opf_dir, ncx_path)
