"""社区共享译文缓存骨架——寻址键 + 包格式 + 校验解包（纯库层，零新依赖）。

设计见 ``docs/research/product/shared-cache.md``。三层要点：

- 寻址：``share_key`` = ``sha256(arxiv_id|ver|model|prompt_ver|lang|
  glossary_hash|pipeline_ver)``——与 ``server.worker.cache_key_for``
  的产物级 dedup 键同构但独立：dedup 键是本地任务去重（per_key scope
  可按凭证指纹分桶），本键是跨实例公开寻址，永不拼凭证/租户成分。
- 包格式：``{share_key}.share.zip`` = ``manifest.json`` + ``zh-src.zip``
  + ``dual.json`` + 可选 ``zh.pdf``；manifest 自校验（key_parts 重算
  share_key、逐产物 sha256/bytes 对账）。``zh.pdf`` 缺席的 partial 包
  合法——它只是贡献者侧编译证据，译文载荷在 ``dual.json``。
- 信任边界：本模块只做机械校验（格式/字段/哈希），不保证译文语义——
  消费端拿 ``dual.json`` 回灌本地 splice→validate→compile 重跑，
  包本身不被信任（设计文 §5）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import secrets
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger(__name__)

#: 包格式版本（manifest.json ``format`` 字段；不兼容变更 bump）。
SHARE_FORMAT = "texlate-share/1"
#: 包内 manifest 成员名。
MANIFEST_NAME = "manifest.json"
#: 标准产物三件套——``pack_share`` 在场即收；文件名即包内 arcname。
ARTIFACT_NAMES = ("zh-src.zip", "zh.pdf", "dual.json")
#: 打包/解包双侧强制在场的产物子集（zh.pdf 缺席的 partial 包合法——译文载荷在 dual.json）。
REQUIRED_ARTIFACTS = ("zh-src.zip", "dual.json")
#: share_key 七组分（序 = 哈希材料序）。
KEY_PART_FIELDS = (
    "arxiv_id",
    "version",
    "model",
    "prompt_ver",
    "target_lang",
    "glossary_hash",
    "pipeline_ver",
)
#: 允许空串的组分（version="" 表 latest 别名、glossary_hash="" 表无术语表）。
_EMPTY_OK = frozenset({"version", "glossary_hash"})
#: manifest.json 尺寸上限（正常 <4KB，超限按坏包处理）。
_MANIFEST_MAX = 1 << 20
#: 单产物成员尺寸上限（论文工程含图一般 <100MB；宽松取 256MB 防 zip 炸弹）。
_MEMBER_MAX = 256 << 20
#: sha256 hex digest 定长。
_SHA256_HEX_LEN = 64
#: 产物名字节上限——主流文件系统 NAME_MAX=255，超限名写盘必炸，校验段先拒。
_NAME_MAX = 255


class ShareError(Exception):
    """共享包校验失败：坏 zip / manifest 缺字段 / 产物哈希对账不过 / 不安全成员名。"""


@dataclass(frozen=True)
class ShareArtifact:
    """manifest ``artifacts`` 单条校验记录（``bytes`` 键名对齐 store.files 表口径）。"""

    sha256: str
    size: int


@dataclass(frozen=True)
class ShareManifest:
    """``unpack_share`` 返回值——manifest.json 校验后视图。"""

    fmt: str
    share_key: str
    key_parts: dict[str, str]
    artifacts: dict[str, ShareArtifact]
    contributor: str
    created_at: str


def _utcnow() -> str:
    """UTC ISO8601 秒级时间戳（与 ``xlat.state._utcnow`` 同口径）。"""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _norm_version(version: object) -> str:
    """版本归一：``3``/``"3"``/``"v3"`` → ``"v3"``；``None``/``""`` → ``""``（latest 别名）。"""
    if version is None:
        return ""
    v = str(version).strip()
    if not v:
        return ""
    return v if v.startswith("v") else f"v{v}"


def share_key(  # noqa: PLR0913, PLR0917 -- 七组分即寻址公式本身，参数面照 spec 平铺
    arxiv_id: str,
    version: int | str | None,
    model: str,
    prompt_ver: str,
    target_lang: str,
    glossary_hash: str,
    pipeline_ver: str,
) -> str:
    """共享缓存寻址键：``sha256(id|ver|model|prompt_ver|lang|glossary|pipeline_ver)``。

    ``version`` 须是**已解析**版本——``v`` 省略的 latest 语义由调用方在
    取源阶段 resolve 后再进键；``""``/``None`` 允许（上传时刻 latest 别名，
    不用于回读寻址）。``glossary_hash`` 是术语表内容指纹（``""`` = 默认/
    无术语表）——自定义术语表改变译文内容，不进键会让不同术语表的译文
    串桶（段级 cfg 指纹 ``sha256(model|prompt_ver|lang|glossary)[:16]``
    已含同成分，本键对齐其口径）。前六组分含 ``|`` 会破坏分隔 →
    ShareError；``pipeline_ver`` 是末位组分，自身允许含 ``|``
    （``worker.PIPELINE_VERSION = "texlate-{ver}|{prompt_ver}"`` 本就如此，
    末位含分隔符无解析歧义）。各组分 strip 归一——与 ``_key_parts`` 的
    manifest 侧归一同口径，边缘空白不进键（域内无意义）。
    """
    ver = _norm_version(version)
    parts = (
        arxiv_id.strip(),
        ver,
        model.strip(),
        prompt_ver.strip(),
        target_lang.strip(),
        glossary_hash.strip(),
        pipeline_ver.strip(),
    )
    for part in parts[:-1]:
        if "|" in part:
            msg = f"share_key component must not contain '|': {part!r}"
            raise ShareError(msg)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------- pack


def _key_parts(manifest: Mapping[str, object]) -> dict[str, str]:
    """七组分提取 + 归一；缺键/非空组分为空 → ShareError。

    键必须在场（七键格式契约）；``_EMPTY_OK`` 组分（version/glossary_hash）
    的 ``None`` 归一为 ``""``——与 ``_norm_version``/``share_key`` 的
    latest 别名口径一致，JSON ``null`` 与 ``""`` 同义；非可空组分 ``None``
    仍按缺失拒。
    """
    parts: dict[str, str] = {}
    for field in KEY_PART_FIELDS:
        if field not in manifest:
            msg = f"manifest missing key part: {field}"
            raise ShareError(msg)
        raw = manifest[field]
        if raw is None:
            if field in _EMPTY_OK:
                parts[field] = ""
                continue
            msg = f"manifest key part empty: {field}"
            raise ShareError(msg)
        value = _norm_version(raw) if field == "version" else str(raw).strip()
        if not value and field not in _EMPTY_OK:
            msg = f"manifest key part empty: {field}"
            raise ShareError(msg)
        parts[field] = value
    return parts


def _derive_key(parts: Mapping[str, str]) -> str:
    """key_parts dict → share_key（组分序 = ``KEY_PART_FIELDS`` 序）。"""
    return share_key(
        parts["arxiv_id"],
        parts["version"],
        parts["model"],
        parts["prompt_ver"],
        parts["target_lang"],
        parts["glossary_hash"],
        parts["pipeline_ver"],
    )


def pack_share(
    work_dir: Path,
    manifest: Mapping[str, object],
    *,
    out_dir: Path | None = None,
) -> Path:
    """在场产物 + 生成的 manifest.json → ``{share_key}.share.zip``。

    ``manifest`` 必带 ``KEY_PART_FIELDS`` 七键（``version``/``glossary_hash``
    可空串）；可选 ``contributor``（缺省生成 ``c-<16hex>`` 匿名 id）与
    ``created_at``（缺省 UTC now）。给了 ``share_key`` 但与组分量重算
    不符 → ShareError（调用方错配防呆）。``REQUIRED_ARTIFACTS`` 缺失/
    超 ``_MEMBER_MAX`` → ShareError；``zh.pdf`` 缺席则不登记不打包——
    manifest artifacts 表即在场清单（缺席即 partial 包，与 unpack 的
    ``REQUIRED_ARTIFACTS`` 口径对称）。返回包路径（``out_dir`` 缺省
    = ``work_dir``）。
    """
    parts = _key_parts(manifest)
    key = _derive_key(parts)
    given = manifest.get("share_key")
    if given is not None and str(given) != key:
        msg = f"share_key mismatch: given {given!r} != derived {key}"
        raise ShareError(msg)
    artifacts: dict[str, dict[str, object]] = {}
    blobs: dict[str, bytes] = {}
    for name in ARTIFACT_NAMES:
        src = work_dir / name
        if not src.is_file():
            if name in REQUIRED_ARTIFACTS:
                msg = f"artifact missing in work_dir: {name}"
                raise ShareError(msg)
            log.info("optional artifact absent, omitted from bundle: %s", name)
            continue
        if src.stat().st_size > _MEMBER_MAX:
            # 先 stat 拒大件避免整块读进内存
            msg = f"artifact too large: {name}"
            raise ShareError(msg)
        blob = src.read_bytes()
        if len(blob) > _MEMBER_MAX:
            msg = f"artifact too large: {name} ({len(blob)}B > {_MEMBER_MAX}B)"
            raise ShareError(msg)
        # 同一份字节既进 manifest 对账又写 zip 成员——单读消灭
        # 「哈希到写入之间文件被改 → 包自矛盾」的 TOCTOU 窗口
        artifacts[name] = {
            "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob),
        }
        blobs[name] = blob
    doc: dict[str, object] = {
        "format": SHARE_FORMAT,
        "share_key": key,
        "key_parts": parts,
        "artifacts": artifacts,
        "contributor": str(manifest.get("contributor") or f"c-{secrets.token_hex(8)}"),
        "created_at": str(manifest.get("created_at") or _utcnow()),
    }
    out = (out_dir or work_dir) / f"{key}.share.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件 + 原子 rename 发布——并发同键打包/静态托管读取不会看到半成品
    tmp = out.with_name(f".{out.name}.{secrets.token_hex(4)}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                MANIFEST_NAME, json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
            )
            for name, blob in blobs.items():
                zf.writestr(name, blob)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


# ---------------------------------------------------------------- unpack


def _name_ok(name: object) -> bool:
    r"""产物名必须是扁平文件名——拒绝 ``/`` ``\`` ``.`` ``..``、空名、NUL 与超 NAME_MAX 名。"""
    return (
        isinstance(name, str)
        and bool(name)
        and name not in (".", "..")
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
        and len(os.fsencode(name)) <= _NAME_MAX
    )


def _read_manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
    """取并解析 manifest.json；不存在/超限/非 JSON object → ShareError。"""
    try:
        info = zf.getinfo(MANIFEST_NAME)
    except KeyError as e:
        msg = f"{MANIFEST_NAME} missing from bundle"
        raise ShareError(msg) from e
    if info.file_size > _MANIFEST_MAX:
        msg = f"{MANIFEST_NAME} too large: {info.file_size}B"
        raise ShareError(msg)
    try:
        blob = zf.read(info)
    except (
        OSError,
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,  # 未知压缩方法
    ) as e:
        msg = f"{MANIFEST_NAME} unreadable: {e}"
        raise ShareError(msg) from e
    try:
        doc = json.loads(blob)
    except json.JSONDecodeError as e:
        msg = f"{MANIFEST_NAME} unreadable: {e}"
        raise ShareError(msg) from e
    if not isinstance(doc, dict):
        msg = f"{MANIFEST_NAME} is not a JSON object"
        raise ShareError(msg)
    return doc


def _artifact_checked(name: object, entry: object) -> ShareArtifact:
    """单条 artifacts 记录校验：安全名 + 64hex sha256 + ``[0, _MEMBER_MAX]`` int bytes。"""
    if not _name_ok(name):
        msg = f"unsafe artifact name: {name!r}"
        raise ShareError(msg)
    if not isinstance(entry, dict):
        msg = f"artifact entry not an object: {name}"
        raise ShareError(msg)
    sha, size = entry.get("sha256"), entry.get("bytes")
    hex_ok = isinstance(sha, str) and len(sha) == _SHA256_HEX_LEN
    if hex_ok:
        try:
            bytes.fromhex(sha)
        except ValueError:
            hex_ok = False
    size_ok = (
        isinstance(size, int)
        and not isinstance(size, bool)
        and 0 <= size <= _MEMBER_MAX
    )
    if not (hex_ok and size_ok):
        msg = f"artifact entry malformed: {name}"
        raise ShareError(msg)
    return ShareArtifact(sha256=str(sha), size=int(size))


def _manifest_checked(doc: Mapping[str, Any]) -> ShareManifest:
    """Manifest dict → ShareManifest（format + key_parts + share_key 自校验 + artifacts 表）。"""
    fmt = doc.get("format")
    if fmt != SHARE_FORMAT:
        msg = f"unsupported share format: {fmt!r}"
        raise ShareError(msg)
    raw_parts = doc.get("key_parts")
    if not isinstance(raw_parts, dict):
        msg = "key_parts missing or not an object"
        raise ShareError(msg)
    parts = _key_parts(raw_parts)
    derived = _derive_key(parts)
    if doc.get("share_key") != derived:
        msg = "share_key missing or does not match key_parts"
        raise ShareError(msg)
    raw_arts = doc.get("artifacts")
    if not isinstance(raw_arts, dict) or not raw_arts:
        msg = "artifacts missing or not an object"
        raise ShareError(msg)
    missing = [n for n in REQUIRED_ARTIFACTS if n not in raw_arts]
    if missing:
        msg = f"required artifacts absent from manifest: {missing}"
        raise ShareError(msg)
    arts = {str(n): _artifact_checked(n, a) for n, a in raw_arts.items()}
    return ShareManifest(
        fmt=SHARE_FORMAT,
        share_key=derived,
        key_parts=parts,
        artifacts=arts,
        contributor=str(doc.get("contributor") or ""),
        created_at=str(doc.get("created_at") or ""),
    )


def _extract_verified(
    zf: zipfile.ZipFile, name: str, art: ShareArtifact, dest: Path
) -> None:
    """成员 → 校验（size 头对账 → 读取 → sha256）→ 写 ``dest/name``。"""
    try:
        info = zf.getinfo(name)
    except KeyError as e:
        msg = f"artifact member missing from bundle: {name}"
        raise ShareError(msg) from e
    if info.file_size != art.size:
        msg = (
            f"size mismatch for {name}: "
            f"manifest {art.size}B != member {info.file_size}B"
        )
        raise ShareError(msg)
    try:
        blob = zf.read(info)
    except (
        OSError,
        zipfile.BadZipFile,
        RuntimeError,
        NotImplementedError,  # 未知压缩方法
    ) as e:
        msg = f"corrupt member: {name}"
        raise ShareError(msg) from e
    if len(blob) != art.size or hashlib.sha256(blob).hexdigest() != art.sha256:
        msg = f"sha256 mismatch for artifact: {name}"
        raise ShareError(msg)
    (dest / name).write_bytes(blob)


def unpack_share(path: Path, dest: Path) -> ShareManifest:
    """解包 + 全量校验 → ShareManifest。

    包/校验失败 → ``ShareError``；``dest`` 落盘与改名等本地 I/O 失败抛
    ``OSError``（环境错与坏包分流，消费端按两者都降级）。校验序：
    zip 可读 → manifest.json 存在且 ≤ ``_MANIFEST_MAX`` →
    format/key_parts/share_key 重算 → artifacts 表 → 逐成员 size+sha256
    对账。只抽取 manifest 登记成员（白名单），包内多余成员忽略——天然免
    zip-slip。产物先落 ``dest`` 内临时目录、全部对账过才逐件 rename 进
    ``dest``——校验中途失败 ``dest`` 零残留（既有同名文件也不被覆写）。
    """
    try:
        zf = zipfile.ZipFile(path)
    except (
        OSError,
        zipfile.BadZipFile,
        UnicodeDecodeError,  # 中央目录成员名标 UTF-8 但字节非法
    ) as e:
        msg = f"not a readable share bundle: {path}"
        raise ShareError(msg) from e
    with zf:
        mf = _manifest_checked(_read_manifest(zf))
        fresh = not dest.exists()
        dest.mkdir(parents=True, exist_ok=True)
        # 校验写入面与 dest 隔离：tmp 与 dest 同目录同设备，rename 即原子发布
        tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", dir=dest))
        try:
            for name, art in mf.artifacts.items():
                _extract_verified(zf, name, art, tmp)
            for name in mf.artifacts:
                (tmp / name).replace(dest / name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            if fresh:
                # 失败路径顺手收掉本次新建的空壳 dest（成功时非空，rmdir 自失败被吞）
                with contextlib.suppress(OSError):
                    dest.rmdir()
        extra = set(zf.namelist()) - {MANIFEST_NAME, *mf.artifacts}
        if extra:
            log.debug("share bundle extra members ignored: %s", sorted(extra))
        return mf


# ---------------------------------------------------------------- index


def index_append(
    index_path: Path, manifest: ShareManifest, url: str, package_bytes: int
) -> dict[str, Any]:
    r"""追加一条 index.jsonl 行 ``{share_key, url, key_parts, bytes, created_at, contributor}``。

    行字段直取 ``manifest`` + 入参（设计文 §7：静态托管旁挂清单，一行一
    已发布包）；父目录缺席自动创建。index 是 append-only——同 share_key
    重传即追加新行，旧行不删，读取侧 last-wins（见 ``index_lookup``）。
    UTF-8 单行 JSON + ``\n`` 结尾。返回写入的行 dict。
    """
    row: dict[str, Any] = {
        "share_key": manifest.share_key,
        "url": url,
        "key_parts": manifest.key_parts,
        "bytes": package_bytes,
        "created_at": manifest.created_at,
        "contributor": manifest.contributor,
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def index_lookup(index_path: Path, share_key: str) -> dict[str, Any] | None:
    """线性扫 index.jsonl 取 ``share_key`` 行；文件缺席/未命中 → ``None``。

    空行跳过；malformed 行（JSON 解析失败或非 object）跳过并在扫完记一条
    warning 带行号——单行坏数据不毒死全索引（多源汇聚场景坏行只伤自身，
    与 ``benchlib.iter_jsonl`` 容错账读同口径）。文件整体非 UTF-8 仍抛
    ``UnicodeDecodeError``，由调用方降级。同 share_key 多行时 last-wins
    （append-only 语义：重传行覆盖旧行）。
    """
    try:
        text = index_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    found: dict[str, Any] | None = None
    bad_lines: list[int] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad_lines.append(lineno)
            continue
        if not isinstance(row, dict):
            bad_lines.append(lineno)
            continue
        if row.get("share_key") == share_key:
            found = row
    if bad_lines:
        log.warning("share index %s: skipped malformed lines %s", index_path, bad_lines)
    return found
