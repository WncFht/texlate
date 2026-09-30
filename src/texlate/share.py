"""社区共享译文缓存骨架——寻址键 + 包格式 + 校验解包（纯库层，零新依赖）。

设计见 ``docs/research/product/2026-09-16-shared-cache.md``。三层要点：

- 寻址：``share_key`` = ``sha256(arxiv_id|ver|model|prompt_ver|lang|
  glossary_hash|pipeline_ver)``——与产物级 dedup 键 ``cache_key_for``
  同构但独立：dedup 键是本地任务去重（``cache_scope``=per_key 时按
  凭证指纹分桶），本键是跨实例公开寻址，永不拼凭证/租户成分。
  ``cache_key_for``/``cache_scope``/``PIPELINE_VERSION`` 单源驻本
  模块——worker 经 ``_common`` 转口、cli 直取，两臂同源防公式漂移。
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
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate import __version__
from texlate.textutil import append_jsonl, env_str, safe_is_file, utc_now
from texlate.textutil.osutil import ENV_CACHE_SCOPE
from texlate.xlat.prompts import PROMPT_VERSION

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
#: 管线版本（cache_key/share_key 共有组分；prompt 模板或产品版本变即失效）。
PIPELINE_VERSION = f"texlate-{__version__}|{PROMPT_VERSION}"
#: manifest.json 尺寸上限（正常 <4KB，超限按坏包处理）。
_MANIFEST_MAX = 1 << 20
#: 单产物成员尺寸上限（论文工程含图一般 <100MB；宽松取 256MB 防 zip 炸弹）。
_MEMBER_MAX = 256 << 20
#: manifest ``artifacts`` 条目数上限——真包 2–4 件，宽松取值挡成员洪泛。
_ARTIFACT_MAX = 64
#: 聚合解压字节上限（与 ``worker.unpack_zip`` INFLATED_CAP 同量级）——按
#: manifest 声明 bytes 合计预算；成员真实大小与声明不符在
#: ``_extract_verified`` 对账即拒，声明总量即实际上界。bzip2/lzma 等
#: 压缩法不改变结论：上界钉在解压后尺寸，与压缩率无关。
_INFLATED_MAX = 300 << 20
#: sha256 hex digest 定长。
_SHA256_HEX_LEN = 64
#: 产物名字节上限——主流文件系统 NAME_MAX=255，超限名写盘必炸，校验段先拒。
_NAME_MAX = 255
#: manifest 字符串字段 UTF-8 字节上限（contributor/created_at/key_parts
#: 各组分）——``options["share"]`` 审计载荷在 64KB options 闸之后注入
#: 任务行，字段级先收敛到 ≤256B，单侧洪泛（如 MB 级 contributor）不会
#: 把 options_json 拖成巨型行。正常值量级：contributor ``c-<16hex>``、
#: created_at ISO8601、组分 ≤100B。
_MANIFEST_FIELD_MAX = 256
#: zipfile 读取面统一异常谱——``ZipFile()`` 构造（中央目录解析）与成员
#: 解压两侧共用，一律归一 ShareError：``NotImplementedError`` 覆盖未知
#: 压缩方法与中央目录 ``extract_version`` 超 ``MAX_EXTRACT_VERSION``，
#: ``zlib.error`` 是解压中途的坏 DEFLATE 流，``RuntimeError`` 覆盖加密成员。
_ZIP_ERRORS = (
    OSError,
    zipfile.BadZipFile,
    RuntimeError,
    NotImplementedError,
    zlib.error,
)


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
    *,
    front_matter: str = "",
) -> str:
    """共享缓存寻址键：``sha256(id|ver|model|prompt_ver|lang|glossary|pipeline_ver)``。

    ``version`` 须是**已解析**版本——``v`` 省略的 latest 语义由调用方在
    取源阶段 resolve 后再进键；``""``/``None`` 允许（上传时刻 latest 别名，
    不用于回读寻址）。``glossary_hash`` 是术语表内容指纹（``""`` = 默认/
    无术语表）——自定义术语表改变译文内容，不进键会让不同术语表的译文
    串桶（段级 cfg 指纹 ``sha256(model|prompt_ver|lang|glossary)[:16]``
    已含同成分，本键对齐其口径）。``front_matter`` = preamble 前置发射集
    的逗号排序清单（``"abstract,title"`` 形）——改变扫描块集即改变包
    内容，非空时作为组分插在 ``pipeline_ver`` 前；空串省略成分，
    与前置全盖过的历史包同键（旧包重算口径不变）。前六组分含 ``|``
    会破坏分隔 → ShareError；``pipeline_ver`` 是末位组分，自身允许含
    ``|``(``PIPELINE_VERSION = "texlate-{ver}|{prompt_ver}"``
    本就如此，末位含分隔符无解析歧义）。各组分 strip 归一——与
    ``_key_parts`` 的 manifest 侧归一同口径，边缘空白不进键（域内无意义）。
    """
    ver = _norm_version(version)
    parts = [
        arxiv_id.strip(),
        ver,
        model.strip(),
        prompt_ver.strip(),
        target_lang.strip(),
        glossary_hash.strip(),
    ]
    fm = front_matter.strip()
    if fm:
        parts.append(fm)
    parts.append(pipeline_ver.strip())
    for part in parts[:-1]:
        if "|" in part:
            msg = f"share_key component must not contain '|': {part!r}"
            raise ShareError(msg)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------- dedup 键


def cache_scope() -> str:
    """``TEXLATE_CACHE_SCOPE``：``shared``（默认）| ``per_key``。

    ``shared`` = hjfy 对等共享缓存（既定产品特性：公开论文的翻译结果是
    确定性函数，跨租户 reuse 省下重复 LLM 调用）；``per_key`` 把
    ``sha256(api_key)[:16]`` 混入缓存键按凭证分桶——消除「探测他租户是否
    译过某论文」的存在性 oracle，代价是缓存命中按 key 碎片化。
    旧名 ``tenant`` 同义 ``per_key``；非法值回落 ``shared``。
    """
    v = env_str(ENV_CACHE_SCOPE) or "shared"
    if v in ("per_key", "tenant"):
        return "per_key"
    if v != "shared":
        log.warning("TEXLATE_CACHE_SCOPE=%r 非法，回落 shared", v)
    return "shared"


def cache_key_for(  # noqa: PLR0913 -- 键材料五元组 + source/fm 即 dedup 面
    *,
    arxiv_id: str,
    version: int | None,
    model: str,
    target_lang: str,
    api_key: str = "",
    source: str = "eprint",
    front_matter: frozenset[str] | None = None,
) -> str:
    """产物级 dedup 键：``sha256(arxiv_id@ver|model|pipeline_ver|lang)``。

    故意不含租户身份（§4.3：公开论文的确定性函数可跨租户 reuse——
    hjfy 对等共享缓存是既定产品特性）；``cache_scope()=="per_key"``
    时把 ``sha256(api_key)[:16]`` 拼进材料按凭证分桶，消除跨租户
    缓存存在性 oracle（匿名桶 key="" 共享一桶，与 tenant_for 同语义）。

    ``source`` = 获取渠道：eprint 默认（材料不变，存量缓存续命）；
    ``html`` 等异源追加 ``|src:`` 成分——同 id@ver 的 eprint 与 html
    任务产物链不同构，channel-blind 会串桶互喂错产物。

    ``front_matter`` = preamble 前置发射集（调用方已按 options 缺省
    归一）：改变扫描块集即改变产物，非空追加 ``|fm:`` 成分分桶；
    空集/None = 前置全盖过的历史形态，材料不变续命存量缓存。
    """
    ver = f"v{version}" if version else ""
    material = f"{arxiv_id}@{ver}|{model}|{PIPELINE_VERSION}|{target_lang}"
    if source != "eprint":
        material += f"|src:{source}"
    if front_matter:
        material += f"|fm:{','.join(sorted(front_matter))}"
    if cache_scope() == "per_key":
        material += f"|k:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    return hashlib.sha256(material.encode()).hexdigest()


def glossary_content_hash(
    *,
    user_layer: Path | None,
    local_layer: Path | None,
    fallback_user: Path | None = None,
    strict_layers: frozenset[Path] = frozenset(),
) -> str:
    """``glossary_hash`` 组分：翻译时生效的自定义术语层内容复合指纹。

    层序 = 哈希材料序：user 层（``user_layer`` 命中；``None`` 时回落
    ``fallback_user``——``Glossary.load`` 缺省 user 层同态）→ local 层
    （``base/glossary.local.yaml``）。逐层 sha256 摘要再复合 sha256；
    全部缺席/未读到 → ``""``（内建 category/default 层随 ``pipeline_ver``
    走不进指纹）。

    ``strict_layers`` 内层 ``read_bytes`` 失败 → ShareError（配置层已死
    与 gate 同口径拒——宁缺不串桶）；其余层读失败 → ``log.warning``
    按缺席计。**路径解析策略归调用方**：cli 臂 ``expanduser`` 直收 +
    死径即拒，worker 臂 ``_glossary_path`` confine（拒/缺席回落缺省层）——
    两臂各按自己翻译时的实际生效层喂参，本函数只管层序与指纹口径。
    """
    gfile = user_layer if user_layer is not None and safe_is_file(user_layer) else None
    if gfile is None and fallback_user is not None and safe_is_file(fallback_user):
        gfile = fallback_user
    files = [f for f in (gfile, local_layer) if f is not None and safe_is_file(f)]
    if not files:
        return ""
    strict = frozenset(strict_layers)
    h = hashlib.sha256()
    hashed = 0
    for f in files:
        try:
            h.update(hashlib.sha256(f.read_bytes()).digest())
        except OSError as e:
            if f in strict:
                msg = f"glossary 层 {f} 读取失败: {e}"
                raise ShareError(msg) from e
            log.warning("glossary 层 %s 读取失败（%s）——按缺席计", f, e)
        else:
            hashed += 1
    return h.hexdigest() if hashed else ""


# ---------------------------------------------------------------- pack


def _key_parts(manifest: Mapping[str, object]) -> dict[str, str]:
    """七必选组分提取 + 归一；缺键/非空组分为空 → ShareError。

    键必须在场（七键格式契约）；``_EMPTY_OK`` 组分（version/glossary_hash）
    的 ``None`` 归一为 ``""``——与 ``_norm_version``/``share_key`` 的
    latest 别名口径一致，JSON ``null`` 与 ``""`` 同义；非可空组分 ``None``
    仍按缺失拒。``front_matter`` 是可选组分（缺席 = 前置全盖过的
    历史形态归一 ``""``）——``share_key`` 仅在其非空时拼入材料，
    旧包（key_parts 无此键）重算口径不变。
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
        if len(value.encode("utf-8", "replace")) > _MANIFEST_FIELD_MAX:
            msg = f"manifest key part too large: {field} > {_MANIFEST_FIELD_MAX}B"
            raise ShareError(msg)
        parts[field] = value
    fm_raw = manifest.get("front_matter")
    fm = "" if fm_raw is None else str(fm_raw).strip()
    if len(fm.encode("utf-8", "replace")) > _MANIFEST_FIELD_MAX:
        msg = f"manifest key part too large: front_matter > {_MANIFEST_FIELD_MAX}B"
        raise ShareError(msg)
    if fm:
        # 与 ``share_key`` 材料同口径——非空才记键，∅ 包 key_parts
        # 与前置全盖过的历史包七组分形完全一致
        parts["front_matter"] = fm
    return parts


def _derive_key(parts: Mapping[str, str]) -> str:
    """key_parts dict → share_key（组分序 = ``KEY_PART_FIELDS`` 序 + fm 选配）。"""
    return share_key(
        parts["arxiv_id"],
        parts["version"],
        parts["model"],
        parts["prompt_ver"],
        parts["target_lang"],
        parts["glossary_hash"],
        parts["pipeline_ver"],
        front_matter=parts.get("front_matter") or "",
    )


def share_manifest(  # noqa: PLR0913 -- 键材料组与 manifest 同面，参数面照 spec 平铺
    *,
    arxiv_base: str,
    version: int | None,
    model: str,
    target_lang: str,
    glossary_hash: str,
    options: Mapping[str, Any],
    contributor: str | None = None,
) -> dict[str, object]:
    """``KEY_PART_FIELDS`` 七组分 + ``front_matter``/``contributor`` manifest dict（单源）。

    cli 臂（``cli.share`` 事后打包端点）与 worker 臂（``server.worker.share``
    完成钩/API 打包）的同构 manifest 派生统一收口于此——两臂各自解析出
    ``arxiv_base``/``version``/``glossary_hash`` 与实跑 ``options`` 喂参，
    本件只管组分拼装口径：``prompt_ver``/``pipeline_ver`` 钉当前管线常量；
    ``front_matter`` 记实跑前置发射集（∅ 记 ``""`` 兼容旧包重算——
    ``_key_parts``/``share_key`` 对空串同口径省略）；给了 ``contributor``
    才进 manifest（``pack_share`` 缺省自产 ``c-<16hex>`` 匿名 id）。
    """
    from texlate.pipecore import ran_front_matter  # noqa: PLC0415 -- 重依赖延迟导入

    manifest: dict[str, object] = {
        "arxiv_id": arxiv_base,
        "version": f"v{version}" if version is not None else "",
        "model": model,
        "prompt_ver": PROMPT_VERSION,
        "target_lang": target_lang,
        "glossary_hash": glossary_hash,
        # 前置发射集进 key_parts——不同 fm 的任务产物不同包（∅ 记 ""
        # 兼容旧包重算）。实跑集还原：done 行经 parse 写回恒带显式 dict；
        # 缺席 = pre-feature 行（实跑 ∅）不标缺省
        "front_matter": ",".join(sorted(ran_front_matter(options))),
        "pipeline_ver": PIPELINE_VERSION,
    }
    if contributor:
        manifest["contributor"] = contributor
    return manifest


def _pack_member(
    zf: zipfile.ZipFile, name: str, src: Path
) -> tuple[dict[str, object], int]:
    """单产物 1MB 块流式进 zip，边写边算 sha256 → ``(manifest artifacts 条目，字节数)``。

    实时字节计数超 ``_MEMBER_MAX`` → ShareError（stat 预检后文件增长的兜底）。
    单读同时完成写入与哈希——manifest 记的是真实入包字节流的指纹。
    """
    digest = hashlib.sha256()
    written = 0
    with zf.open(name, "w") as member, src.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            written += len(chunk)
            if written > _MEMBER_MAX:
                msg = f"artifact too large: {name} ({written}B > {_MEMBER_MAX}B)"
                raise ShareError(msg)
            member.write(chunk)
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "bytes": written}, written


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
    ``REQUIRED_ARTIFACTS`` 口径对称）。生成 manifest 序列化超
    ``_MANIFEST_MAX`` 或产物合计超 ``_INFLATED_MAX`` → ShareError——
    pack 不产出自拒包（``contributor``/``created_at``/组分串同受
    ``_MANIFEST_FIELD_MAX`` 闸，与 unpack 校验同口径）。返回包路径
    （``out_dir`` 缺省 = ``work_dir``）。

    写体流式：产物边读边算 sha256 边进 zip（``ZipFile.open`` 成员流），
    不整载进 RAM——单读同时消灭「哈希到写入之间文件被改 → 包自矛盾」
    的 TOCTOU 窗口（manifest 记的是真实写入的字节流指纹）。发布前整
    包经 ``unpack_share`` 全量回验（manifest 结构 + 逐成员 size/sha256
    对账）——自拒包弃于临时位不发布。
    """
    parts = _key_parts(manifest)
    key = _derive_key(parts)
    given = manifest.get("share_key")
    if given is not None and str(given) != key:
        msg = f"share_key mismatch: given {given!r} != derived {key}"
        raise ShareError(msg)
    planned: list[tuple[str, Path]] = []
    for name in ARTIFACT_NAMES:
        src = work_dir / name
        if not src.is_file():
            if name in REQUIRED_ARTIFACTS:
                msg = f"artifact missing in work_dir: {name}"
                raise ShareError(msg)
            log.info("optional artifact absent, omitted from bundle: %s", name)
            continue
        if src.stat().st_size > _MEMBER_MAX:
            # 先 stat 快拒大件；写入期间再按实际字节数兜底（文件可增长）
            msg = f"artifact too large: {name}"
            raise ShareError(msg)
        planned.append((name, src))
    doc: dict[str, object] = {
        "format": SHARE_FORMAT,
        "share_key": key,
        "key_parts": parts,
        # artifacts 在流式写期间回填——写入多少哈希多少
        "artifacts": {},
        "contributor": _manifest_field_str(manifest, "contributor")
        or f"c-{secrets.token_hex(8)}",
        "created_at": _manifest_field_str(manifest, "created_at") or utc_now(),
    }
    out = (out_dir or work_dir) / f"{key}.share.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件 + 原子 rename 发布——并发同键打包/静态托管读取不会看到半成品
    tmp = out.with_name(f".{out.name}.{secrets.token_hex(4)}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            artifacts: dict[str, dict[str, object]] = {}
            total = 0
            for name, src in planned:
                entry, written = _pack_member(zf, name, src)
                artifacts[name] = entry
                total += written
                if total > _INFLATED_MAX:
                    msg = (
                        f"artifacts too large in aggregate: {total}B > {_INFLATED_MAX}B"
                    )
                    raise ShareError(msg)
            doc["artifacts"] = artifacts
            # 自洽闸：pack 产出必须可被自家 unpack 消费（unpack 侧同上限拒收）
            manifest_blob = (
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
            ).encode()
            if len(manifest_blob) > _MANIFEST_MAX:
                msg = f"manifest too large: {len(manifest_blob)}B > {_MANIFEST_MAX}B"
                raise ShareError(msg)
            zf.writestr(MANIFEST_NAME, manifest_blob)
        # 「pack 不产出自拒包」实做闸：发布前走自家 unpack 路径全量回验，
        # 失败即弃——tmp 与 verify 现场均由清理路径收走，out 不被触碰
        scratch = Path(tempfile.mkdtemp(prefix=f".{out.name}.verify.", dir=out.parent))
        try:
            unpack_share(tmp, scratch)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
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


def _read_member_capped(
    zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int, what: str
) -> bytes:
    """成员有界读：按 ``cap + 1`` 截断返回 blob（超限判定留给调用方）。

    中央目录 ``file_size`` 可谎报——有界读防「声明小、实解大」解压放大
    先于对账分配巨量。读取面异常一律归一 ``ShareError``（``_ZIP_ERRORS``
    谱），``what`` 作消息头（调用方语义：``manifest.json unreadable`` /
    ``corrupt member: <name>`` 等）。
    """
    try:
        with zf.open(info) as fp:
            return fp.read(cap + 1)
    except _ZIP_ERRORS as e:
        msg = f"{what}: {e}"
        raise ShareError(msg) from e


def _read_manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
    """取并解析 manifest.json；不存在/超限/非 JSON object → ShareError。

    声明 ``file_size`` 先快拒超 ``_MANIFEST_MAX``；读取仍按上限 +1 截断——
    目录 size 可谎报，有界读防「声明小、实解大」解压放大。
    """
    try:
        info = zf.getinfo(MANIFEST_NAME)
    except KeyError as e:
        msg = f"{MANIFEST_NAME} missing from bundle"
        raise ShareError(msg) from e
    if info.file_size > _MANIFEST_MAX:
        msg = f"{MANIFEST_NAME} too large: {info.file_size}B"
        raise ShareError(msg)
    blob = _read_member_capped(zf, info, _MANIFEST_MAX, f"{MANIFEST_NAME} unreadable")
    if len(blob) > _MANIFEST_MAX:
        msg = f"{MANIFEST_NAME} too large: {len(blob)}B"
        raise ShareError(msg)
    try:
        doc = json.loads(blob)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,  # 成员字节非法 UTF-8——loads 对 bytes 先 decode
        RecursionError,  # 上限内仍可构造超深嵌套
    ) as e:
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


def _manifest_field_str(doc: Mapping[str, Any], name: str) -> str:
    """``contributor``/``created_at`` 取串 + ``_MANIFEST_FIELD_MAX`` 字节闸。

    缺省 ``""``（pack 侧同字段有自产缺省）；超限 ``ShareError``——字段
    会原样进 ``options["share"]`` 审计载荷，无上限的串是 options_json
    膨胀面。
    """
    value = str(doc.get(name) or "")
    if len(value.encode("utf-8", "replace")) > _MANIFEST_FIELD_MAX:
        msg = f"manifest {name} too large: >{_MANIFEST_FIELD_MAX}B"
        raise ShareError(msg)
    return value


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
    if len(raw_arts) > _ARTIFACT_MAX:
        msg = f"too many artifacts: {len(raw_arts)} > {_ARTIFACT_MAX}"
        raise ShareError(msg)
    missing = [n for n in REQUIRED_ARTIFACTS if n not in raw_arts]
    if missing:
        msg = f"required artifacts absent from manifest: {missing}"
        raise ShareError(msg)
    arts = {str(n): _artifact_checked(n, a) for n, a in raw_arts.items()}
    total = sum(a.size for a in arts.values())
    if total > _INFLATED_MAX:
        msg = f"artifacts too large in aggregate: {total}B > {_INFLATED_MAX}B"
        raise ShareError(msg)
    return ShareManifest(
        fmt=SHARE_FORMAT,
        share_key=derived,
        key_parts=parts,
        artifacts=arts,
        contributor=_manifest_field_str(doc, "contributor"),
        created_at=_manifest_field_str(doc, "created_at"),
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
    blob = _read_member_capped(zf, info, art.size, f"corrupt member: {name}")
    if len(blob) != art.size or hashlib.sha256(blob).hexdigest() != art.sha256:
        msg = f"sha256 mismatch for artifact: {name}"
        raise ShareError(msg)
    (dest / name).write_bytes(blob)


def _publish_artifacts(
    artifacts: dict[str, ShareArtifact], tmp: Path, dest: Path
) -> None:
    """校验过的产物从事务位 ``tmp`` 落进 ``dest``——旧件撤 backup → 逐件 rename → 失败回滚。

    先预检全部目标位：被同名目录占据时 rename 必败，整体先拒（不确定
    性冲突收敛在前）。既有同名产物（含断链——``is_symlink`` 并查，
    ``exists()`` 对断链为 False，漏撤会被静默吞掉）撤入 ``dest`` 内
    backup 目录后逐件 rename 就位；任一步失败即回滚——已就位新件撤
    出、备份还原，``dest`` 回到发布前状态。回滚路径自身失败按
    best-effort 吞掉（原异常优先传播）。进程被杀/掉电等不经 Python
    的中断仍可能留半成品与 ``.bak`` 现场——多文件真原子不可达，
    残余均为隐藏点目录可手工清。
    """
    # 发布预检：目标位被同名目录占据时 rename 必败——整体先拒，
    # 避免逐件 rename 中段失败留下部分发布
    for name in artifacts:
        if (dest / name).is_dir():
            msg = f"publish target is a directory: {dest / name}"
            raise IsADirectoryError(msg)
    backup = Path(tempfile.mkdtemp(prefix=f".{dest.name}.bak.", dir=dest))
    published: list[str] = []
    try:
        for name in artifacts:
            target = dest / name
            if target.is_symlink() or target.exists():
                target.replace(backup / name)
        for name in artifacts:
            (tmp / name).replace(dest / name)
            published.append(name)
    except BaseException:
        for name in published:
            with contextlib.suppress(OSError):
                (dest / name).unlink()
        for name in artifacts:
            rescued = backup / name
            if rescued.is_symlink() or rescued.exists():
                with contextlib.suppress(OSError):
                    rescued.replace(dest / name)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def unpack_share(path: Path, dest: Path) -> ShareManifest:
    """解包 + 全量校验 → ShareManifest。

    包/校验失败 → ``ShareError``；``dest`` 落盘与改名等本地 I/O 失败抛
    ``OSError``（环境错与坏包分流，消费端按两者都降级）。校验序：
    zip 可读 → manifest.json 存在且 ≤ ``_MANIFEST_MAX`` →
    format/key_parts/share_key 重算 → artifacts 表（条数 ≤
    ``_ARTIFACT_MAX``、声明合计 ≤ ``_INFLATED_MAX``）→ 逐成员 size+sha256
    对账（读取按声明尺寸 +1 截断，目录 size 谎报不放大内存）。只抽取 manifest 登记成员（白名单），包内多余成员忽略——天然免
    zip-slip。产物先落 ``dest`` 内临时目录、全部对账过才发布——校验
    中途失败 ``dest`` 零残留（既有同名文件也不被覆写）。发布段由
    ``_publish_artifacts`` 事务化执行——``dest`` 要么完整就位要么回到
    发布前状态。
    """
    try:
        zf = zipfile.ZipFile(path)
    except (
        *_ZIP_ERRORS,
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
            _publish_artifacts(mf.artifacts, tmp, dest)
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
    UTF-8 单行 JSON + ``\n`` 结尾；追加经 ``textutil.append_jsonl`` flock
    串行化，``to_thread`` 工作线程并发落行不交错。返回写入的行 dict。
    """
    row: dict[str, Any] = {
        "share_key": manifest.share_key,
        "url": url,
        "key_parts": manifest.key_parts,
        "bytes": package_bytes,
        "created_at": manifest.created_at,
        "contributor": manifest.contributor,
    }
    append_jsonl(index_path, row)
    return row


#: ``index_lookup`` 解析缓存：``{index_path: (st_mtime_ns, st_size, 行表)}``。
#: append-only 索引每请求整读 + 逐行 ``json.loads`` 是 server share 查询
#: 路径（``routers/share.py`` ``to_thread``）主开销；``stat`` 复核
#: ``(mtime_ns, size)`` 一致才复用，变了即重解析。索引文件数 ≤ store 数
#: （个位量级），超 ``_INDEX_CACHE_MAX`` 全清重建——有界兜底防长尾滞留。
#: 行表按 ``share_key`` last-wins 建 dict（与原线性扫口径同义），行内
#: 非 str ``share_key`` 字段按不收录计（原口径下本就永不命中 str 查询）。
_INDEX_CACHE_MAX = 8
_INDEX_CACHE: dict[Path, tuple[int, int, dict[str, dict[str, Any]]]] = {}


def _index_rows(text: str) -> tuple[dict[str, dict[str, Any]], list[int]]:
    """index.jsonl 文本 → ``({share_key: row} last-wins 表，坏行行号)``。

    空行跳过；malformed 行（JSON 解析失败或非 object）跳过记行号——单行
    坏数据不毒死全索引。行内非 str ``share_key`` 字段不收录（str 查询
    本就永不命中）。
    """
    rows: dict[str, dict[str, Any]] = {}
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
        key = row.get("share_key")
        if isinstance(key, str):
            rows[key] = row  # last-wins（append-only：重传行覆盖旧行）
    return rows, bad_lines


def index_lookup(index_path: Path, share_key: str) -> dict[str, Any] | None:
    """扫 index.jsonl 取 ``share_key`` 行；文件缺席/未命中 → ``None``。

    空行跳过；malformed 行（JSON 解析失败或非 object）跳过并在扫完记一条
    warning 带行号——单行坏数据不毒死全索引（多源汇聚场景坏行只伤自身，
    与 ``benchlib.iter_jsonl`` 容错账读同口径）。文件整体非 UTF-8 仍抛
    ``UnicodeDecodeError``，由调用方降级。同 share_key 多行时 last-wins
    （append-only 语义：重传行覆盖旧行）。解析结果经 ``_INDEX_CACHE``
    按 ``(path, st_mtime_ns, st_size)`` 短缓存——stat 变即重扫。
    """
    try:
        st = index_path.stat()
    except FileNotFoundError:
        return None
    hit = _INDEX_CACHE.get(index_path)
    if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2].get(share_key)
    try:
        text = index_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    rows, bad_lines = _index_rows(text)
    if bad_lines:
        log.warning("share index %s: skipped malformed lines %s", index_path, bad_lines)
    if len(_INDEX_CACHE) >= _INDEX_CACHE_MAX:
        _INDEX_CACHE.clear()
    _INDEX_CACHE[index_path] = (st.st_mtime_ns, st.st_size, rows)
    return rows.get(share_key)
