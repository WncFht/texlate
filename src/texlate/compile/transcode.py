r"""支持件字节卫生层（normalize.py 拆出）：非 ``.tex`` 手术面文件的 UTF-8 转码/净化。

invalid_utf8 输入侧修复臂：aux/bib/中间产物转码 + 中间件截尾整形 +
EPS/PS ``%`` 注释行逐行净化 + ``%%BoundingBox: (atend)`` 头行回值 +
catch-all 全树转码（``BINARY_SUFFIXES`` 豁免 + NUL 闸兜底）——实证依据
见各函数 docstring。另收两个跨模块共享的树遍历低层件：``_hidden_path``
（隐藏路径豁免口径单源）与 ``_record_verdict``（编码判定台账），
``normalize.py``/``shadow.py`` 回引。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.textutil import EncodingVerdict

from texlate.textutil import decode_tex, decode_tex_with

from .mask import TEX_SOURCE_SUFFIXES

#: 随附文献/书目数据后缀——不是 TeX 手术面，但 XeTeX/biber 一律按
#: UTF-8 读它们，非 UTF-8 字节须与 .tex 同档判定转码。
AUX_BIB_SUFFIXES = {".bib", ".bbl", ".bst"}

#: 引擎 pass 间回读的可再生中间产物（aux/out/toc/lof/lot/nav/snm/vrb/ent）：
#: shipped 件若带非 UTF-8 字节，首遍回读即 "Invalid UTF-8 byte" —— .aux 的
#: ``\@newl@bel`` EOF 实证 2211.13013 同族。不进 rebase/violations 扫描面
#: （机器生成内容，\input 审计无意义），只随 _transcode_support_files 转码。
INTERMEDIATE_SUFFIXES = {
    ".aux",
    ".out",
    ".toc",
    ".lof",
    ".lot",
    ".nav",
    ".snm",
    ".vrb",
    ".ent",
}

#: PostScript 图形后缀——graphicx 对 ``\includegraphics`` 目标做
#: ``%%BoundingBox`` 逐行文本扫描（xetex 驱动同此），头注释里的
#: latin-1/GBK 字节（Word2TeX 导出的 Windows 路径等）触发
#: invalid_utf8（loop1-0707.4363 ``Fig*.eps`` 实证）。整件转码会腐
#: ``%%BeginBinary``/内嵌预览的字节数据——只净化 ``%`` 注释行
#: （PostScript 语义惰性区），DOS-EPS 二进制头（``0xC5D0D3C6`` 魔数，
#: 内含绝对字节偏移）整件跳过。姊妹臂 ``_resolve_atend_bbox``：
#: ``(atend)`` 占位头行强制全件扫描，trailer 实值搬回头行后扫描
#: 在头行即停，数据行坏字节不再入扫。
#: ``.epsi/.epsf/.mps`` 同族归队：corpus_v3 全量 48 件皆 ``%!PS``
#: 文本形态（epsi=EPS Interchange、epsf=EPSF、mps=MetaPost 输出），
#: 真实非 UTF-8 坏点均在 ``%%`` 注释行（cond-mat/9901072
#: ``fig2.epsf`` ``%%Copyright \xa9`` latin-1、0806.2219
#: ``fig02b.epsi`` ``%%CreationDate`` GBK 日期）——走 catch-all 整件
#: 转码会把数据行高字节一并改写，必须走本臂保数据段字节。
PS_GRAPHIC_SUFFIXES = {".eps", ".epsf", ".epsi", ".mps", ".ps"}

#: 已知二进制后缀——catch-all 转码豁免名单。漏网的冷门二进制最坏被
#: latin-1→UTF-8 改写：编译树内只有 TeX 文本读取会触它（原样也只会
#: U+FFFD），源归档保持原样——宁可多转不可漏文本件。
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".tif",
    ".tiff",
    ".webp",
    ".bmp",
    ".jfif",
    ".jbig2",
    ".jb2",
    ".ico",
    ".icns",
    ".heic",
    ".avif",
    ".jp2",
    ".pdf",
    ".dvi",
    ".xdv",
    ".tfm",
    ".ofm",
    ".vf",
    ".pfb",
    ".pfa",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    ".pk",
    ".gf",
    ".gz",
    ".bz2",
    ".xz",
    ".zip",
    ".tar",
    ".7z",
    ".rar",
    ".lz4",
    ".zst",
    ".jar",
    ".class",
    ".pyc",
    ".pyo",
    ".o",
    ".so",
    ".a",
    ".dll",
    ".exe",
    ".dylib",
    ".mat",
    ".pickle",
    ".pkl",
    ".npy",
    ".npz",
    ".h5",
    ".hdf5",
    ".fits",
    ".sav",
    ".dta",
    ".parquet",
    ".feather",
    ".arrow",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".sobj",
    ".iwa",
    ".plist",
    ".wav",
    ".mp3",
    ".ogg",
    ".flac",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".webm",
    ".m4a",
    ".docx",
    ".xlsx",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".iso",
    ".img",
    ".dmg",
}

#: DOS-EPS 二进制头魔数——头部含 PS 段的绝对偏移，任何字节增删即腐，
#: 整件放弃净化（此类件本就带二进制预览，扫描面只会更糟）。
_DOS_EPS_MAGIC: Final = b"\xc5\xd0\xd3\xc6"

#: DSC 数据段标记——``%%Begin{Binary,Data,Document,Preview}`` 与配对
#: ``%%End*`` 之间的行是另一消费者的字节负载：其间形似注释的 ``%`` 行
#: 不是 PostScript 惰性区，逐行净化会改写二进制/嵌入件数据。
_PS_DATA_BEGIN_RX: Final = re.compile(
    rb"^[ \t]*%%Begin(?:Binary|Data|Document|Preview)\b"
)
_PS_DATA_END_RX: Final = re.compile(rb"^[ \t]*%%End(?:Binary|Data|Document|Preview)\b")


# ---------------------------------------------------------------- 树遍历/台账共享低层件
def _hidden_path(path: Path, root: Path) -> bool:
    """任一路径段 ``.`` 前缀——隐藏件（``.git``/``.dotfile``）整体豁免手术与审计。"""
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _record_verdict(
    encodings: dict[str, dict[str, str | None]],
    root: Path,
    path: Path,
    verdict: EncodingVerdict,
) -> None:
    """非平凡判定（非 strict-utf8 / 有声明出入注记）逐文件落账。"""
    if verdict.basis != "strict-utf8" or verdict.note:
        encodings[path.relative_to(root).as_posix()] = {
            "encoding": verdict.encoding,
            "basis": verdict.basis,
            "declared": verdict.declared,
            "note": verdict.note,
        }


# ---------------------------------------------------------------- 转码/净化臂
def _trim_intermediate_tail(text: str) -> str | None:
    r"""可再生中间产物的截尾整形：砍回最后一个完整行界；无完整行可留 → None。

    XeTeX 写缓冲在 8192B 边界劈断多字节字符 → 自产/shipped ``.aux`` 系
    文件可能终结于半截 ``\newlabel``——只转码不整形回读时
    ``\@newl@bel`` 照样扫过 EOF（2211.13013）。TeX 写出的完整行必以
    ``\n`` 收尾，``text`` 已是解码后字符面，按行界回退即完整字符边界；
    砍掉的部分引擎下遍重长，零数据损失。仅适用可再生中间产物——
    .bib/.bbl/.bst 是数据文件，无尾换行的完整末行是合法形态，不能砍。
    """
    if not text or text.endswith("\n"):
        return text
    end = text.rfind("\n") + 1
    return text[:end] if end else None


def _sanitize_ps_comments(blob: bytes) -> bytes:
    r"""EPS/PS 的 ``%`` 注释行逐行转码 UTF-8；非注释行与 DOS 二进制头原样。

    graphicx ``%%BoundingBox`` 扫描逐行读 PS 件——注释行坏字节即
    invalid_utf8；注释是 PostScript 惰性区，改写零语义差。非注释行
    （``%%BeginBinary``/字符串/hex 数据）字节即语义不许动——残余坏点
    只在 ``(atend)`` 全扫路径才再报，稀有可接受。DOS-EPS 头存绝对偏移，
    任何字节增删即腐，整件跳过。
    """
    if blob.startswith(_DOS_EPS_MAGIC):
        return blob
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError:
        pass  # 有坏字节才进逐行净化
    else:
        return blob
    out: list[bytes] = []
    changed = False
    in_data = False
    for raw_line in blob.split(b"\n"):
        line = raw_line
        if _PS_DATA_BEGIN_RX.match(line):
            in_data = True
        elif _PS_DATA_END_RX.match(line):
            in_data = False
        elif not in_data and line.lstrip(b" \t").startswith(b"%"):
            try:
                line.decode("utf-8")
            except UnicodeDecodeError:
                # decode_tex 的 EOL 归一会把行尾 \r 改写成 \n——CRLF 件
                # 净化后凭空多空行；剥尾转码再拼回保住行界字节。
                trail = b"\r" if line.endswith(b"\r") else b""
                body = line[:-1] if trail else line
                new = decode_tex(body).encode("utf-8") + trail
                changed = changed or new != line
                line = new
        out.append(line)
    return b"\n".join(out) if changed else blob


#: DSC 头区 ``%%BoundingBox: (atend)`` 占位行——值延到 trailer 才给。
_BBOX_ATEND_RX: Final = re.compile(rb"^[ \t]*%%BoundingBox:[ \t]*\(atend\)[ \t\r]*$")
#: 实值 ``%%BoundingBox:`` 行——恰好 4 个数值（负值/小数容忍），摄回 group 1。
_BBOX_VALUE_RX: Final = re.compile(
    rb"^[ \t]*%%BoundingBox:[ \t]*"
    rb"((?:[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[ \t]+){3}"
    rb"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)[ \t\r]*$"
)


def _resolve_atend_bbox(blob: bytes) -> bytes:
    r"""``%%BoundingBox: (atend)`` 头行就地改写为 trailer 实值行。

    graphicx/xetex 的 bbox 逐行扫描命中 ``(atend)`` 占位时被迫全件扫到
    trailer——``(...) show`` 数据行的坏字节随之落入 invalid_utf8 判定
    （数据行字节即语义，``_sanitize_ps_comments`` 刻意不动；utf8-rerun
    复验残 5 格全属此形态）。DSC 约定 atend 实值本就由 trailer 行承载，
    把头行改写为该值后扫描在头行即停——零语义差，trailer 原行保留无害。

    只认 DSC 头注释块（首个非 ``%`` 行 / ``%%EndComments`` 之前）的
    ``(atend)`` 占位行；取全件最后一条实值 ``%%BoundingBox:`` 行作源——
    无实值/畸形值不造值，原样返回。幂等：改写后头行即实值行，二次跑无
    占位可命中。DOS-EPS 二进制头同 sanitize 臂整件跳过。
    """
    if blob.startswith(_DOS_EPS_MAGIC):
        return blob
    lines = blob.split(b"\n")
    atend_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped:
            continue  # 空行不打断头注释块判定（CRLF 件的空行即 \r）
        if stripped.startswith(b"%%EndComments") or not stripped.startswith(b"%"):
            break  # DSC 头注释块边界——atend 占位只认头区
        if _BBOX_ATEND_RX.match(line):
            atend_idx = i
            break
    if atend_idx is None:
        return blob
    values: bytes | None = None
    for line in lines:
        match = _BBOX_VALUE_RX.match(line)
        if match:
            values = match[1]
    if values is None:
        return blob
    out = lines[:]
    trailer_ws = out[atend_idx][len(out[atend_idx].rstrip(b" \t\r")) :]
    out[atend_idx] = b"%%BoundingBox: " + values + trailer_ws
    return b"\n".join(out)


def _transcode_intermediate(
    path: Path, text: str, rel: str, ledgers: dict[str, list[str]]
) -> bool:
    """INTERMEDIATE 件截尾整形；返回 True=已处置（purge/截尾写回）不再转码。"""
    kept = _trim_intermediate_tail(text)
    if kept is None:
        try:
            path.unlink()
        except OSError:
            pass  # 只读目录 purge 不动——文件原样，不留台账
        else:
            ledgers["purged_intermediates"].append(rel)
        return True
    if kept == text:
        return False  # 无尾可截——回落通用转码臂
    try:
        path.write_text(kept, encoding="utf-8")
    except OSError:
        pass
    else:
        ledgers["trimmed_intermediates"].append(rel)
    return True


def _transcode_one(
    path: Path,
    suffix: str,
    encodings: dict[str, dict[str, str | None]],
    ledgers: dict[str, list[str]],
    root: Path,
) -> None:
    """单件解码判定+写回；INTERMEDIATE 截尾整形，其余全件转码落台账。

    读写任一步 OSError（只读件/只读目录）按「未触动」处理——不落台账、
    不中断整树扫描（同 ``_neutralize_junk_files`` 的守卫口径）。
    """
    try:
        original = path.read_bytes()
    except OSError:
        return
    text, verdict = decode_tex_with(original)
    # 漏网二进制闸：NUL 字节且非 UTF-16 形态（utf-16 判定自带 NUL 占比
    # 门槛）→ 拿不准的一律不动，也不进 encodings 归因（非文本件无可归因）。
    if b"\x00" in original and not verdict.encoding.startswith("utf-16"):
        return
    _record_verdict(encodings, root, path, verdict)
    rel = path.relative_to(root).as_posix()
    if suffix in INTERMEDIATE_SUFFIXES and _transcode_intermediate(
        path, text, rel, ledgers
    ):
        return
    if text.encode("utf-8") != original:
        try:
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass
        else:
            aux_family = suffix in AUX_BIB_SUFFIXES or suffix in INTERMEDIATE_SUFFIXES
            ledgers["transcoded_aux" if aux_family else "transcoded_data"].append(rel)


def _process_ps_file(path: Path, rel: str, ledgers: dict[str, list[str]]) -> None:
    """PS 件：DOS 魔数整件豁免落台账；atend 改写 + 注释净化，写成功才记。

    DOS-EPS 二进制头含绝对偏移，任何字节增删即腐——整件留原样落台账
    （残余 invalid_utf8 由引擎归因降到 sys_warn，不阻断 clean）。
    """
    try:
        original = path.read_bytes()
    except OSError:
        return
    if original.startswith(_DOS_EPS_MAGIC):
        ledgers["dos_eps_skipped"].append(rel)
        return
    resolved = _resolve_atend_bbox(original)
    sanitized = _sanitize_ps_comments(resolved)
    if sanitized == original:
        return
    try:
        path.write_bytes(sanitized)
    except OSError:
        return  # 写不进不记台账，保持原样
    if resolved != original:
        ledgers["resolved_atend_bbox"].append(rel)
    if sanitized != resolved:
        ledgers["sanitized_ps_comments"].append(rel)


def _transcode_support_files(
    root: Path, encodings: dict[str, dict[str, str | None]]
) -> dict[str, list[str]]:
    r"""非手术面文件按需转 UTF-8：aux/bib + 中间产物 + PS 注释行 + catch-all。

    只动字节不动字节序义：aux 由引擎下遍重写，转码只为消掉 shipped
    非 UTF-8 件首遍回读的 invalid_utf8（docs/research/latex/
    2026-09-16-aux-cjk-truncation.md 立项臂二；loop1 归因补充：工程
    内残留警告 = EPS 头注释/``\openin`` 数据件/未列名文本件）。中间
    产物另加截尾整形（``_trim_intermediate_tail``）——不完整末行比
    非法字节更致命：``\@newl@bel`` 的 EOF 扫描发生在参数层，合法
    UTF-8 也救不回来。

    catch-all：编译树内一切非 ``BINARY_SUFFIXES`` 后缀件必须可
    strict-UTF-8 解码——``.svn``/``.git`` 等隐藏目录、软链（写穿会
    改到 root 外目标）与二进制件豁免；``BINARY_SUFFIXES`` 漏网件另由
    ``_transcode_one`` 的 NUL 闸兜底（含 NUL 且非 UTF-16 → 不动）。

    返回 ``stats`` 片段（仅非空台账）：``transcoded_aux`` /
    ``transcoded_data`` / ``sanitized_ps_comments`` /
    ``resolved_atend_bbox`` / ``trimmed_intermediates`` /
    ``purged_intermediates`` / ``dos_eps_skipped``。
    """
    ledgers: dict[str, list[str]] = {
        "transcoded_aux": [],
        "transcoded_data": [],
        "sanitized_ps_comments": [],
        "resolved_atend_bbox": [],
        "trimmed_intermediates": [],
        "purged_intermediates": [],
        "dos_eps_skipped": [],
    }
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        if _hidden_path(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if suffix in TEX_SOURCE_SUFFIXES or suffix in BINARY_SUFFIXES:
            continue  # 手术面由主循环转码；二进制件不读文本层
        if suffix in PS_GRAPHIC_SUFFIXES:
            _process_ps_file(path, rel, ledgers)
            continue
        _transcode_one(path, suffix, encodings, ledgers, root)
    return {k: sorted(v) for k, v in ledgers.items() if v}
