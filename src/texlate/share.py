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

import hashlib
import json
import logging
import secrets
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

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
    末位含分隔符无解析歧义）。
    """
    ver = _norm_version(version)
    parts = (
        arxiv_id,
        ver,
        model,
        prompt_ver,
        target_lang,
        glossary_hash,
        pipeline_ver,
    )
    for part in parts[:-1]:
        if "|" in part:
            msg = f"share_key component must not contain '|': {part!r}"
            raise ShareError(msg)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------- pack


def _key_parts(manifest: Mapping[str, object]) -> dict[str, str]:
    """七组分提取 + 归一；缺字段/非空组分为空 → ShareError。"""
    parts: dict[str, str] = {}
    for field in KEY_PART_FIELDS:
        raw = manifest.get(field)
        if raw is None:
            msg = f"manifest missing key part: {field}"
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
    for name in ARTIFACT_NAMES:
        src = work_dir / name
        if not src.is_file():
            if name in REQUIRED_ARTIFACTS:
                msg = f"artifact missing in work_dir: {name}"
                raise ShareError(msg)
            log.info("optional artifact absent, omitted from bundle: %s", name)
            continue
        size = src.stat().st_size
        if size > _MEMBER_MAX:
            msg = f"artifact too large: {name} ({size}B > {_MEMBER_MAX}B)"
            raise ShareError(msg)
        artifacts[name] = {
            "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
            "bytes": size,
        }
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
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        for name in artifacts:
            zf.write(work_dir / name, arcname=name)
    return out


# ---------------------------------------------------------------- unpack


def _name_ok(name: object) -> bool:
    r"""产物名必须是扁平文件名——拒绝 ``/`` ``\`` ``.`` ``..`` 与空名。"""
    return (
        isinstance(name, str)
        and bool(name)
        and name not in (".", "..")
        and "/" not in name
        and "\\" not in name
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
        doc = json.loads(zf.read(info))
    except (json.JSONDecodeError, zipfile.BadZipFile) as e:
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
    except (OSError, zipfile.BadZipFile, RuntimeError) as e:
        msg = f"corrupt member: {name}"
        raise ShareError(msg) from e
    if len(blob) != art.size or hashlib.sha256(blob).hexdigest() != art.sha256:
        msg = f"sha256 mismatch for artifact: {name}"
        raise ShareError(msg)
    (dest / name).write_bytes(blob)


def unpack_share(path: Path, dest: Path) -> ShareManifest:
    """解包 + 全量校验 → ShareManifest；任一步失败 → ShareError。

    校验序：zip 可读 → manifest.json 存在且 ≤ ``_MANIFEST_MAX`` →
    format/key_parts/share_key 重算 → artifacts 表 → 逐成员 size+sha256
    对账后才写盘。只抽取 manifest 登记成员（白名单），包内多余成员
    忽略——天然免 zip-slip。``dest`` 建议用全新目录：校验中途失败可能
    留下已写出的部分成员，由调用方清理。
    """
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        msg = f"not a readable share bundle: {path}"
        raise ShareError(msg) from e
    with zf:
        mf = _manifest_checked(_read_manifest(zf))
        dest.mkdir(parents=True, exist_ok=True)
        for name, art in mf.artifacts.items():
            _extract_verified(zf, name, art, dest)
        extra = set(zf.namelist()) - {MANIFEST_NAME, *mf.artifacts}
        if extra:
            log.debug("share bundle extra members ignored: %s", sorted(extra))
        return mf
