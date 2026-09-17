"""上传物 unpack/sniff 安全件（原 ``worker.py`` 上传解包段，与类无关）。"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path, PurePosixPath

from texlate.arxiv.sniff import (
    BlobKind,
    SniffError,
    sniff,
)
from texlate.arxiv.unpack import (
    MAX_FILE_BYTES,
    UnpackError,
    _unique_rename,
)
from texlate.server.settings import (
    INFLATED_CAP,
    MAX_FILES,
)

#: zip 成员名拒绝面：绝对路径/盘符
_BAD_ZIP_NAME = re.compile(r"^(?:[a-zA-Z]:|/|\\)")

# ---------------------------------------------------------------- 上传解包


def _zip_member_payload(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """成员读归 ``UnpackError``——坏 CRC/未知压缩算法/加密成员与包级同案。

    漏出去会在 ``_stage_fetch`` 异常阶梯里落 ``internal`` 可重试 fault。
    """
    try:
        return zf.read(info)
    except (
        zipfile.BadZipFile,
        NotImplementedError,
        RuntimeError,
        OSError,
    ) as e:
        msg = f"bad member {info.filename}: {e}"
        raise UnpackError(msg) from e


def _zip_member_write(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path, rel_s: str
) -> str | None:
    """单成员落盘 + 目录冲突检 → 拒绝告警串或 None。

    冲突检测须遍历全部祖先前缀而非只查直接 parent：成员 ``a``（文件）+
    ``a/b/c.txt`` 同包时 parent ``a/b`` 尚不存在会漏检，mkdir 撞
    ``NotADirectoryError`` 毁整单。写体全段包 ``OSError``：单段超
    NAME_MAX 的合法成员名在 ``is_dir``/``mkdir``/``write_bytes`` 任一
    处都可能 ENAMETOOLONG/EDQUOT——归成员级拒（``reject_io``）跳过，
    不拖死整单。``UnpackError``（坏成员体）不在此吞，照旧上抛。
    """
    t_parts = PurePosixPath(rel_s).parts
    target = dest.joinpath(*t_parts)
    try:
        clash = target.is_dir() or any(
            (p := dest.joinpath(*t_parts[:i])).is_file() or p.is_symlink()
            for i in range(1, len(t_parts))
        )
        if clash:
            return f"reject_dir_clash:{rel_s}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_zip_member_payload(zf, info))
    except OSError:
        return f"reject_io:{rel_s}"
    return None


def unpack_zip(data: bytes, dest: Path) -> list[str]:
    """Zip 安全解包（upload_tex 路线；tar/gz 走 ``unpack_sniffed``）。

    拒绝：绝对路径/盘符/``..`` 逃逸/超过 4000 文件/单文件或总量超限。
    与 ``arxiv.unpack`` tar 侧同族：dup 成员告警覆盖（last-wins）、
    casefold 冲突改名 ``~cN``、成员名撞已建目录（或其路径段撞已落
    文件）告警跳过——不静默合并/不抛 IsADirectoryError。
    """
    warnings: list[str] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        msg = f"corrupt zip: {e}"
        raise UnpackError(msg) from e
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES:
            msg = f"too_many_files:{len(infos)}"
            raise UnpackError(msg)
        total = 0
        seen: dict[str, str] = {}
        dest.mkdir(parents=True, exist_ok=True)
        for info in infos:
            rel = PurePosixPath(info.filename)
            parts = [p for p in rel.parts if p not in ("", ".")]
            if _BAD_ZIP_NAME.match(info.filename) or any(p == ".." for p in parts):
                warnings.append(f"reject:{info.filename}")
                continue
            if info.file_size > MAX_FILE_BYTES:
                warnings.append(f"reject_size:{info.filename}")
                continue
            total += info.file_size
            if total > INFLATED_CAP:  # 300MB 解压上限（§2.4）
                warnings.append("reject_totalcap")
                break
            rel_s = PurePosixPath(*parts).as_posix()
            low = rel_s.lower()
            if low in seen and seen[low] != rel_s:
                new_rel = _unique_rename(rel_s, seen)
                warnings.append(f"casefold_rename:{rel_s}->{new_rel}")
                rel_s, low = new_rel, new_rel.lower()
            elif low in seen:
                warnings.append(f"dup_member_overwrite:{rel_s}")
            seen[low] = rel_s
            if w := _zip_member_write(zf, info, dest, rel_s):
                warnings.append(w)
    return warnings


def _zip_kind(data: bytes) -> str:
    """PK 容器细分：docx/epub/upload_tex（坏 zip 交解包处报错）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" in names:
                return "docx"
            head = b""
            if "mimetype" in names:
                try:
                    head = zf.read("mimetype")[:64].strip()
                except (KeyError, RuntimeError, NotImplementedError, OSError):
                    head = b""  # 加密/坏成员与 _zip_member_payload 同族——退 upload_tex 交解包处报错
            if head == b"application/epub+zip" or any(
                n.endswith("content.opf") for n in names
            ):
                return "epub"
    except zipfile.BadZipFile:
        pass  # 坏 zip 交给 upload_tex 路在解包处报错
    return "upload_tex"


def sniff_upload(data: bytes, filename: str) -> str:
    """上传魔数路由（§2.4）→ ``upload_pdf|upload_tex|docx|epub|unknown``。

    判据顺序：``%PDF`` → zip(docx/epub 细分) → gzip/tar → 可解码文本兜底。
    """
    if data[:4] == b"%PDF":
        return "upload_pdf"
    if data[:4] == b"PK\x03\x04":
        return _zip_kind(data)
    try:
        s = sniff(data)
    except SniffError:
        return "unknown"
    if s.kind in (BlobKind.TAR, BlobKind.SINGLE):
        return "upload_tex"
    if filename.lower().endswith((".tex", ".ltx", ".latex", ".txt")):
        return "upload_tex"
    return "upload_tex" if _looks_text(data) else "unknown"


def pdf_pages(pdf: Path) -> int:
    """PDF 页数 best-effort（pypdf；缺库/坏文件返 0）。"""
    try:
        from pypdf import PdfReader  # noqa: PLC0415 -- 重依赖惰性加载

        return len(PdfReader(str(pdf)).pages)
    except Exception:  # noqa: BLE001 -- best-effort：坏文件/缺库都退 0
        return 0


def _looks_text(data: bytes) -> bool:
    """粗糙文本判定：前 64KB 可 UTF-8 解码且无 NUL。"""
    if b"\x00" in data[:4096]:
        return False
    try:
        data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _safe_name(name: str) -> str:
    """上传文件名 → 安全落盘名（剥目录、滤怪字符，空则 main.tex）。"""
    base = PurePosixPath(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9_.+-]", "_", base)
    if not base or not base.lower().endswith((".tex", ".ltx", ".latex", ".txt")):
        base = (base or "main") + ".tex"
    return base


def _md_member(src_file: str, seen: set[str]) -> str:
    """``src_file`` → md.zip 成员名：剥 ``..``/盘符、``.tex`` 系后缀换 ``.md``、重名 ``~N``。"""
    parts = [
        p
        for p in PurePosixPath(src_file.replace("\\", "/")).parts
        if p not in ("", ".", "..") and not p.endswith(":")
    ]
    name = "/".join(parts) or "document"
    name = re.sub(r"\.(?:tex|ltx|latex|txt)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^A-Za-z0-9_./+-]", "_", name).strip("/") or "document"
    cand, n = name + ".md", 1
    while cand in seen:
        n += 1
        cand = f"{name}~{n}.md"
    seen.add(cand)
    return cand
