"""share.py pack↔unpack 性质 fuzz——manifest 七组分矩阵 × 随机产物 × 篡改包。

核心不变量：

- ``pack_share``：随机 manifest 只许 ``ShareError`` 或成功——其他异常即逃逸；
  成功 ⇒ bundle 自洽（归一组分/逐产物 sha256+bytes 对账、成员集 == 在场产物），
  且 ``unpack_share`` 字节级还原——pack 产出必须可被自家 unpack 消费；
- ``unpack_share``：随机篡改 manifest/成员/整包字节只许 ``ShareError`` 或成功；
  成功 ⇒ dest 恰为 manifest 登记名集合、逐件与返回 ``ShareManifest`` 的
  sha256/bytes 一致——manifest 与成员永远互洽（白名单抽取，未登记成员不落地）；
- ``share_key`` 直调：前六归一组分含 ``|`` ⇔ ``ShareError``；否则等于
  ``sha256("|".join(parts))`` 独立重算（oracle 不复用实现代码路径）。
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from typing import TYPE_CHECKING

import pytest
from _fuzzkit import fuzz_rng
from _sharekit import repack as _repack

from texlate.share import (
    ARTIFACT_NAMES,
    KEY_PART_FIELDS,
    MANIFEST_NAME,
    REQUIRED_ARTIFACTS,
    SHARE_FORMAT,
    ShareError,
    pack_share,
    share_key,
    unpack_share,
)

if TYPE_CHECKING:
    import random
    from collections.abc import Mapping
    from pathlib import Path

    from texlate.share import ShareManifest

_DIR = object()  # 产物路径落为目录哨兵（is_file False ≈ 缺席）
_EMPTYABLE = frozenset({"version", "glossary_hash"})
_FIRST_SIX = KEY_PART_FIELDS[:6]
_ANON_RX = re.compile(r"c-[0-9a-f]{16}")
_MEMBER_CAP = 4096  # monkeypatch 后 _MEMBER_MAX 测试值
_FIELD_MAX = 256  # share._MANIFEST_FIELD_MAX 镜像——字段级字节闸

#: 发生器概率常量（PLR2004：阈值字面量一律提名）。
_P_DROP_FIELD = 0.05
_P_VALID = 0.8
_P_CONTRIB = 0.08
_P_CREATED = 0.04
_P_SHAREKEY = 0.06
_P_ABSENT = 0.12
_P_DIR = 0.17
_P_HALF = 0.5
_P_TRUNC = 0.25
_P_ART_DROP = 0.3
_P_ART_JUNK = 0.65
_P_MEM_DROP = 0.4
_P_MEM_FLIP = 0.7
_P_DROP_PART = 0.4

#: fuzz 种子/迭代量（``_fuzzkit`` 约定 ``_SEED_*``/``_FUZZ_ITERS*`` 自报）。
_SEED_MANIFEST = 20260923
_SEED_ARTIFACT = 20260924
_SEED_MUT_MANIFEST = 20260925
_SEED_MUT_BYTES = 20260926
_SEED_SHAREKEY = 20260927
_FUZZ_ITERS_MANIFEST = 700
_FUZZ_ITERS_ARTIFACT = 400
_FUZZ_ITERS_MUT_MANIFEST = 700
_FUZZ_ITERS_MUT_BYTES = 500
_FUZZ_ITERS_SHAREKEY = 3000

_VALID_POOL: dict[str, list[object]] = {
    "arxiv_id": ["1706.03762", "2401.00001", "cs/0601001"],
    "version": ["v1", "v3", 3, "5", None, ""],
    "model": ["deepseek-chat", "qwen-plus", "gpt-5"],
    "prompt_ver": ["xlat-prompt-2025-0101", "p1"],
    "target_lang": ["zh-CN", "en", "ja"],
    "glossary_hash": ["", "ab12cd34", "g"],
    "pipeline_ver": ["texlate-0.1.0|xlat-prompt-2025-0101", "texlate-9|p9"],
}
_MUT_POOL: list[object] = [
    None,
    "",
    " ",
    "\t\n",
    "a|b",
    "|",
    "x|y|z",
    0,
    7,
    -1,
    True,
    [],
    {},
    3.5,
    "数据",
    "m\x00del",
    "v|x",
    " " * 40,
    "z" * 300,
]
_NEW_NAMES = [
    "extra.txt",
    "数据.json",
    "x" * 255,
    "y" * 256,
    "../evil",
    "a/b",
    "",
    ".",
    "..",
    MANIFEST_NAME,
    "dual.json ",
    "nul\x00x",
    "UPPER.PDF",
]
_EXTRA_MEMBER_NAMES = [n for n in _NEW_NAMES if n != MANIFEST_NAME]
_BAD_ART_ENTRIES: list[object] = [
    None,
    "x",
    [],
    {"sha256": "0" * 64},
    {"bytes": 3},
    {"sha256": "z" * 64, "bytes": -1},
    {"sha256": "0" * 64, "bytes": True},
    {"sha256": "0" * 64, "bytes": 1 << 40},
]
_BASE_PARTS: dict[str, object] = dict(
    zip(
        KEY_PART_FIELDS,
        [
            "1706.03762",
            "v5",
            "deepseek-chat",
            "xlat-prompt-2025-0101",
            "zh-CN",
            "",
            "texlate-0.1.0|xlat-prompt-2025-0101",
        ],
        strict=True,
    )
)


# ---------------------------------------------------------------- oracle


def _norm_ver(v: object) -> str:
    """``_norm_version`` 独立转写：None/空 → ""；缺 ``v`` 前缀补上。"""
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    return s if s.startswith("v") else f"v{s}"


def _norm_parts_pack(parts: Mapping[str, object]) -> dict[str, str] | None:
    """pack/unpack 侧 ``_key_parts`` 契约 oracle：七键在场 + 非空闸 +
    ``_MANIFEST_FIELD_MAX`` 字节闸 → 归一组分。"""
    out: dict[str, str] = {}
    for f in KEY_PART_FIELDS:
        if f not in parts:
            return None
        raw = parts[f]
        if raw is None:
            if f not in _EMPTYABLE:
                return None
            out[f] = ""
            continue
        s = _norm_ver(raw) if f == "version" else str(raw).strip()
        if not s and f not in _EMPTYABLE:
            return None
        if len(s.encode("utf-8", "replace")) > _FIELD_MAX:
            return None
        out[f] = s
    return out


def _norm_parts_key(parts: Mapping[str, object]) -> dict[str, str]:
    """``share_key`` 直调口径 oracle：只 strip/归一，无在场/空值闸。"""
    return {
        f: (_norm_ver(parts[f]) if f == "version" else str(parts[f]).strip())
        for f in KEY_PART_FIELDS
    }


def _oracle_key(norm: Mapping[str, str]) -> str | None:
    """归一组分 → 期望 share_key；前六含 ``|`` → None（应 ShareError）。"""
    if any("|" in norm[f] for f in _FIRST_SIX):
        return None
    joined = "|".join(norm[f] for f in KEY_PART_FIELDS)
    return hashlib.sha256(joined.encode()).hexdigest()


def _expect_pack_ok(
    parts: Mapping[str, object],
) -> tuple[dict[str, str] | None, str | None]:
    """pack 成功期望 → ``(归一组分，key)``；应拒 → ``(None, None)``。"""
    norm = _norm_parts_pack(parts)
    if norm is None:
        return None, None
    key = _oracle_key(norm)
    if key is None:
        return None, None
    given = parts.get("share_key")
    if given is not None and str(given) != key:
        return None, None
    # contributor/created_at 同受 ``_MANIFEST_FIELD_MAX`` 闸（``_manifest_field_str``）
    for name in ("contributor", "created_at"):
        if len(str(parts.get(name) or "").encode("utf-8", "replace")) > _FIELD_MAX:
            return None, None
    return norm, key


# ---------------------------------------------------------------- helpers


def _det_bytes(n: int) -> bytes:
    """确定性伪随机字节（长度即内容指纹，免共享 rng）。"""
    return bytes((i * 31 + n) % 256 for i in range(n))


def _write_work(root: Path, artifacts: Mapping[str, object]) -> dict[str, bytes]:
    """产物集落盘（bytes 写文件、``_DIR`` 建目录）→ 在场字节表。"""
    root.mkdir(parents=True, exist_ok=True)
    present: dict[str, bytes] = {}
    for name, payload in artifacts.items():
        if payload is _DIR:
            (root / name).mkdir()
        else:
            blob = payload if isinstance(payload, bytes) else b""
            (root / name).write_bytes(blob)
            present[name] = blob
    return present


def _gen_artifacts(rng: random.Random, cap: int) -> dict[str, object]:
    """随机产物集：缺席/目录/0B/边界尺寸/普通二进制混合。"""
    sizes = [0, 1, 63, cap - 1, cap, cap + 1, rng.randint(2, 1500)]
    out: dict[str, object] = {}
    for name in ARTIFACT_NAMES:
        r = rng.random()
        if r < _P_ABSENT:
            continue
        if r < _P_DIR:
            out[name] = _DIR
            continue
        out[name] = rng.randbytes(rng.choice(sizes))
    return out


def _check_bundle(
    bundle: Path,
    present: Mapping[str, bytes],
    norm: Mapping[str, str],
    key: str,
    given: Mapping[str, object],
) -> None:
    """包体对账：成员集/内容/manifest 字段/contributor 缺省形态。"""
    assert bundle.name == f"{key}.share.zip"
    with zipfile.ZipFile(bundle) as zf:
        doc = json.loads(zf.read(MANIFEST_NAME))
        member_blobs = {n: zf.read(n) for n in zf.namelist() if n != MANIFEST_NAME}
    assert set(member_blobs) == set(present)
    for n, b in member_blobs.items():
        assert b == present[n]
    assert isinstance(doc, dict)
    assert doc.get("format") == SHARE_FORMAT
    assert doc.get("share_key") == key
    assert doc.get("key_parts") == dict(norm)
    arts = doc.get("artifacts")
    assert isinstance(arts, dict)
    assert set(arts) == set(present)
    for n, entry in arts.items():
        assert entry == {
            "sha256": hashlib.sha256(present[n]).hexdigest(),
            "bytes": len(present[n]),
        }
    contrib = given.get("contributor")
    if contrib:
        assert doc.get("contributor") == str(contrib)
    else:
        assert _ANON_RX.fullmatch(str(doc.get("contributor")))
    created = given.get("created_at")
    if created:
        assert doc.get("created_at") == str(created)
    else:
        assert doc.get("created_at")  # 缺省 UTC 戳非空


def _check_unpacked(
    mf: ShareManifest, dest: Path, present: Mapping[str, bytes]
) -> None:
    """已知输入的解包断言：名集合恰等、字节级还原、sha/bytes 一致。"""
    assert set(mf.artifacts) == set(present)
    assert {p.name for p in dest.iterdir()} == set(present)
    for n, art in mf.artifacts.items():
        blob = (dest / n).read_bytes()
        assert blob == present[n]
        assert len(blob) == art.size
        assert hashlib.sha256(blob).hexdigest() == art.sha256


def _check_consistent(mf: ShareManifest, dest: Path) -> None:
    """未知输入的解包断言（篡改 fuzz 用）：落盘件逐一对账返回值。"""
    names = set(mf.artifacts)
    assert {p.name for p in dest.iterdir()} == names
    for n, art in mf.artifacts.items():
        blob = (dest / n).read_bytes()
        assert len(blob) == art.size
        assert hashlib.sha256(blob).hexdigest() == art.sha256
    key = _oracle_key(mf.key_parts)
    assert key is not None
    assert mf.share_key == key


def _base_bundle(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, bytes]]:
    """一个合法包的 manifest doc 与成员字节（篡改起点）。"""
    present = _write_work(
        tmp_path / "w",
        {"zh-src.zip": b"ZS-src", "zh.pdf": b"PDF-body", "dual.json": b'{"v":1}'},
    )
    bundle = pack_share(tmp_path / "w", _BASE_PARTS, out_dir=tmp_path)
    with zipfile.ZipFile(bundle) as zf:
        doc = json.loads(zf.read(MANIFEST_NAME))
        payloads = {n: zf.read(n) for n in zf.namelist() if n != MANIFEST_NAME}
    assert isinstance(doc, dict)
    assert set(payloads) == set(present)
    return doc, payloads


# ---------------------------------------------------------------- pack manifest 矩阵


def _gen_manifest(rng: random.Random) -> dict[str, object]:
    """七组分各自独立抽 pool：合法/变异混合，偶发整键缺席与可选键注入。"""
    parts: dict[str, object] = {}
    for f in KEY_PART_FIELDS:
        if rng.random() < _P_DROP_FIELD:
            continue
        pool = _VALID_POOL[f]
        parts[f] = (
            rng.choice(pool) if rng.random() < _P_VALID else rng.choice(_MUT_POOL)
        )
    r = rng.random()
    if r < _P_CONTRIB:
        parts["contributor"] = rng.choice(["alice-01", "", None, 0, 42, "数 据"])
    if r < _P_CREATED:
        parts["created_at"] = rng.choice(["2026-01-01T00:00:00+00:00", "", None, 7])
    if r < _P_SHAREKEY:
        _, key = _expect_pack_ok(parts)
        if key and rng.random() < _P_HALF:
            parts["share_key"] = key
        else:
            parts["share_key"] = rng.choice(["0" * 64, "", 123])
    return parts


def test_fuzz_pack_manifest_matrix(tmp_path: Path) -> None:
    """七组分 在场/缺席/null/空白/非串/含 ``|`` 矩阵：ShareError 或自洽成功。"""
    rng = fuzz_rng(_SEED_MANIFEST)
    present = _write_work(
        tmp_path / "work",
        {"zh-src.zip": b"ZS", "zh.pdf": b"PDF", "dual.json": b"{}"},
    )
    work = tmp_path / "work"
    for i in range(_FUZZ_ITERS_MANIFEST):
        parts = _gen_manifest(rng)
        norm, key = _expect_pack_ok(parts)
        out_dir = tmp_path / f"o{i}"
        if key is None:
            with pytest.raises(ShareError):
                pack_share(work, parts, out_dir=out_dir)
            continue
        assert norm is not None
        bundle = pack_share(work, parts, out_dir=out_dir)
        _check_bundle(bundle, present, norm, key, parts)
        mf = unpack_share(bundle, tmp_path / f"d{i}")
        assert mf.share_key == key
        assert mf.key_parts == norm
        _check_unpacked(mf, tmp_path / f"d{i}", present)


# ---------------------------------------------------------------- pack 产物矩阵


def test_fuzz_pack_artifact_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """随机产物集（缺席/目录/0B/``_MEMBER_MAX`` 边界）：ShareError 或字节级还原。"""
    monkeypatch.setattr("texlate.share._MEMBER_MAX", _MEMBER_CAP)
    rng = fuzz_rng(_SEED_ARTIFACT)
    norm = _norm_parts_pack(_BASE_PARTS)
    assert norm is not None
    key = _oracle_key(norm)
    assert key is not None
    for i in range(_FUZZ_ITERS_ARTIFACT):
        artifacts = _gen_artifacts(rng, _MEMBER_CAP)
        work = tmp_path / f"w{i}"
        present = _write_work(work, artifacts)
        ok = all(n in present for n in REQUIRED_ARTIFACTS) and all(
            len(b) <= _MEMBER_CAP for b in present.values()
        )
        if not ok:
            with pytest.raises(ShareError):
                pack_share(work, _BASE_PARTS, out_dir=tmp_path / f"o{i}")
            continue
        bundle = pack_share(work, _BASE_PARTS, out_dir=tmp_path / f"o{i}")
        _check_bundle(bundle, present, norm, key, _BASE_PARTS)
        _check_unpacked(
            unpack_share(bundle, tmp_path / f"d{i}"), tmp_path / f"d{i}", present
        )


def test_pack_member_max_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_MEMBER_MAX`` 边界钉：``<=`` 收、``+1`` 拒。"""
    monkeypatch.setattr("texlate.share._MEMBER_MAX", _MEMBER_CAP)
    for size in (_MEMBER_CAP - 1, _MEMBER_CAP, _MEMBER_CAP + 1):
        work = tmp_path / f"w{size}"
        _write_work(
            work,
            {"zh-src.zip": b"ZS", "dual.json": b"{}", "zh.pdf": _det_bytes(size)},
        )
        if size <= _MEMBER_CAP:
            bundle = pack_share(work, _BASE_PARTS, out_dir=tmp_path / f"o{size}")
            mf = unpack_share(bundle, tmp_path / f"d{size}")
            assert (tmp_path / f"d{size}" / "zh.pdf").stat().st_size == size
            assert mf.artifacts["zh.pdf"].size == size
        else:
            with pytest.raises(ShareError, match="too large"):
                pack_share(work, _BASE_PARTS, out_dir=tmp_path / f"o{size}")


def test_unpack_member_max_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """unpack 侧独立闸：manifest 声明 bytes 超 monkeypatch 后上限 → 拒。"""
    present = _write_work(tmp_path / "w", {"zh-src.zip": b"ZS", "dual.json": b"{}"})
    bundle = pack_share(tmp_path / "w", _BASE_PARTS, out_dir=tmp_path)
    monkeypatch.setattr("texlate.share._MEMBER_MAX", 1)
    with pytest.raises(ShareError, match="malformed"):
        unpack_share(bundle, tmp_path / "d")
    monkeypatch.setattr("texlate.share._MEMBER_MAX", _MEMBER_CAP + 1)
    mf = unpack_share(bundle, tmp_path / "d2")
    _check_unpacked(mf, tmp_path / "d2", present)


def test_unpack_manifest_max_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_MANIFEST_MAX`` 闸：manifest 成员超声明上限 → ``too large``。"""
    _write_work(tmp_path / "w", {"zh-src.zip": b"ZS", "dual.json": b"{}"})
    bundle = pack_share(tmp_path / "w", _BASE_PARTS, out_dir=tmp_path)
    monkeypatch.setattr("texlate.share._MANIFEST_MAX", 16)
    with pytest.raises(ShareError, match="too large"):
        unpack_share(bundle, tmp_path / "d")


def test_pack_huge_caller_field_self_rejects(tmp_path: Path) -> None:
    """``contributor`` 等调用方控字段把序列化 manifest 顶超 ``_MANIFEST_MAX``
    → pack 侧先拒（自洽闸：不产出自家 ``unpack_share`` 拒收的包）。"""
    _write_work(tmp_path / "w", {"zh-src.zip": b"ZS", "dual.json": b"{}"})
    parts = {**_BASE_PARTS, "contributor": "x" * (1 << 21)}
    with pytest.raises(ShareError, match="too large"):
        pack_share(tmp_path / "w", parts, out_dir=tmp_path)


# ---------------------------------------------------------------- unpack 篡改 fuzz


def _op_top(doc: dict[str, object], rng: random.Random) -> None:
    k = rng.choice(
        ["format", "share_key", "key_parts", "artifacts", "contributor", "created_at"]
    )
    if rng.random() < _P_HALF:
        doc.pop(k, None)
    else:
        doc[k] = rng.choice([0, [], "junk", None, {}, 3.5])


def _op_format(doc: dict[str, object], rng: random.Random) -> None:
    doc["format"] = rng.choice(["texlate-share/2", "Texlate-Share/1", "", 1])


def _op_key_parts(doc: dict[str, object], rng: random.Random) -> None:
    parts = doc.get("key_parts")
    if not isinstance(parts, dict):
        return
    f = rng.choice([*KEY_PART_FIELDS, "extra_future"])
    if rng.random() < _P_DROP_PART:
        parts.pop(f, None)
    else:
        parts[f] = rng.choice(_MUT_POOL)


def _op_share_key(doc: dict[str, object], rng: random.Random) -> None:
    """share_key 扰动——含"重算合法新身份"路径（换身份仍是可解包）。"""
    norm = (
        _norm_parts_pack(doc["key_parts"])
        if isinstance(doc.get("key_parts"), dict)
        else None
    )
    key = _oracle_key(norm) if norm else None
    if key and rng.random() < _P_HALF:
        doc["share_key"] = key
    else:
        doc["share_key"] = rng.choice(["0" * 64, "", None, 12345])


def _op_arts_mutate(doc: dict[str, object], rng: random.Random) -> None:
    arts = doc.get("artifacts")
    if not isinstance(arts, dict) or not arts:
        return
    n = rng.choice(list(arts))
    r = rng.random()
    if r < _P_ART_DROP:
        arts.pop(n)
    elif r < _P_ART_JUNK:
        arts[n] = rng.choice(_BAD_ART_ENTRIES)
    else:
        e = dict(arts[n]) if isinstance(arts[n], dict) else {}
        e["bytes"] = rng.choice([0, -1, 7, 1 << 30])
        arts[n] = e


def _op_arts_add(doc: dict[str, object], rng: random.Random) -> None:
    arts = doc.get("artifacts")
    if isinstance(arts, dict):
        arts[rng.choice(_NEW_NAMES)] = {
            "sha256": hashlib.sha256(b"NP").hexdigest(),
            "bytes": 2,
        }


_DOC_OPS = [
    _op_top,
    _op_format,
    _op_key_parts,
    _op_share_key,
    _op_arts_mutate,
    _op_arts_add,
]


def _mutate_doc(doc: dict[str, object], rng: random.Random) -> None:
    """就地改 manifest：顶层键/format/七组分/share_key/artifacts 全表面。"""
    for _ in range(rng.randint(1, 3)):
        rng.choice(_DOC_OPS)(doc, rng)


def _mutate_members(payloads: dict[str, bytes], rng: random.Random) -> None:
    """成员侧变异：丢件/翻字节/加未登记成员。

    ``MANIFEST_NAME`` 不入成员名池——重名 manifest 成员会把随机字节顶上
    权威位（last-wins）只剩必拒路径，对 fuzz 无增量覆盖（权威语义由
    ``test_unpack_dup_manifest_member_last_wins`` 单钉）。
    """
    for _ in range(rng.randint(0, 2)):
        r = rng.random()
        if r < _P_MEM_DROP and payloads:
            payloads.pop(rng.choice(list(payloads)))
        elif r < _P_MEM_FLIP and payloads:
            n = rng.choice(list(payloads))
            b = bytearray(payloads[n])
            if b:
                b[rng.randrange(len(b))] ^= 0xFF
            payloads[n] = bytes(b)
        else:
            payloads[rng.choice(_EXTRA_MEMBER_NAMES)] = rng.randbytes(
                rng.randint(0, 40)
            )


def test_fuzz_unpack_mutated_manifest(tmp_path: Path) -> None:
    """manifest 字段随机篡改：只许 ShareError 或自洽成功（dest == 登记集合）。"""
    rng = fuzz_rng(_SEED_MUT_MANIFEST)
    doc0, payloads0 = _base_bundle(tmp_path)
    for i in range(_FUZZ_ITERS_MUT_MANIFEST):
        doc = json.loads(json.dumps(doc0))  # 深拷贝
        payloads = dict(payloads0)
        _mutate_doc(doc, rng)
        _mutate_members(payloads, rng)
        evil = _repack(tmp_path / f"e{i}.zip", doc, payloads)
        dest = tmp_path / f"d{i}"
        try:
            mf = unpack_share(evil, dest)
        except ShareError:
            assert not dest.exists()  # 新 dest + 失败 ⇒ 零残留
            continue
        _check_consistent(mf, dest)


def test_fuzz_unpack_mutated_bytes(tmp_path: Path) -> None:
    """整包字节级变异/截断：几乎必 ShareError；偶然成功须内部自洽。"""
    rng = fuzz_rng(_SEED_MUT_BYTES)
    doc0, payloads0 = _base_bundle(tmp_path)
    good = _repack(tmp_path / "good.zip", doc0, payloads0)
    raw = good.read_bytes()
    for i in range(_FUZZ_ITERS_MUT_BYTES):
        data = bytearray(raw)
        if rng.random() < _P_TRUNC:
            data = data[: rng.randrange(len(data))]
        else:
            for _ in range(rng.randint(1, 8)):
                data[rng.randrange(len(data))] = rng.randrange(256)
        evil = tmp_path / f"b{i}.zip"
        evil.write_bytes(bytes(data))
        dest = tmp_path / f"d{i}"
        try:
            mf = unpack_share(evil, dest)
        except ShareError:
            assert not dest.exists()
            continue
        _check_consistent(mf, dest)


def test_non_utf8_manifest_share_error(tmp_path: Path) -> None:
    """``manifest.json`` 成员字节非法 UTF-8 → ShareError（``json.loads`` 对
    bytes 先 decode 的 ``UnicodeDecodeError`` 归一契约内，不逃逸）。"""
    out = tmp_path / "bad.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(MANIFEST_NAME, b"\xbb\x87not-utf8")
        zf.writestr("zh-src.zip", b"ZS")
        zf.writestr("dual.json", b"{}")
    with pytest.raises(ShareError):
        unpack_share(out, tmp_path / "d")


def _corrupt_member_data(bundle: Path, member: str, out: Path) -> Path:
    """定位 ``member`` 的 local-header 数据区并覆写——解压侧 ``zlib.error``。"""
    data = bytearray(bundle.read_bytes())
    pos = 0
    while (i := data.find(b"PK\x03\x04", pos)) != -1:
        nlen = int.from_bytes(data[i + 26 : i + 28], "little")
        elen = int.from_bytes(data[i + 28 : i + 30], "little")
        name = bytes(data[i + 30 : i + 30 + nlen])
        start = i + 30 + nlen + elen
        if name == member.encode():
            data[start : start + 8] = b"\xff" * 8
            break
        pos = start + 1
    else:  # pragma: no cover -- 构造保证命中
        pytest.fail(f"local header not found: {member}")
    out.write_bytes(bytes(data))
    return out


def test_corrupt_deflate_member_share_error(tmp_path: Path) -> None:
    """成员 DEFLATE 流损坏 → 解压中途 ``zlib.error``，归一 ShareError（成员
    读取面异常谱 ``_ZIP_ERRORS`` 已含，不逃逸契约）。"""
    doc, payloads = _base_bundle(tmp_path)
    good = _repack(tmp_path / "good.zip", doc, payloads)
    evil = _corrupt_member_data(good, "zh-src.zip", tmp_path / "e.zip")
    with pytest.raises(ShareError):
        unpack_share(evil, tmp_path / "d")


def test_bad_zip_version_share_error(tmp_path: Path) -> None:
    """中央目录 ``extract_version`` 超 ``MAX_EXTRACT_VERSION`` → ``ZipFile()``
    构造抛 ``NotImplementedError``——构造侧与成员读取侧同异常谱，归一
    ShareError。"""
    doc, payloads = _base_bundle(tmp_path)
    good = _repack(tmp_path / "good.zip", doc, payloads)
    data = bytearray(good.read_bytes())
    i = data.find(b"PK\x01\x02")  # 中央目录首条目
    assert i != -1
    data[i + 6] = 200  # extract_version: 4s sig + create_version/create_system 后
    evil = tmp_path / "e.zip"
    evil.write_bytes(bytes(data))
    with pytest.raises(ShareError):
        unpack_share(evil, tmp_path / "d")


def test_unpack_dup_manifest_member_last_wins(tmp_path: Path) -> None:
    """zip 内重复 ``manifest.json``：getinfo/read 取中央目录末位登记——钉住权威语义。"""
    doc, payloads = _base_bundle(tmp_path)
    out = tmp_path / "dup.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps({**doc, "contributor": "first-entry"}))
        zf.writestr(MANIFEST_NAME, json.dumps({**doc, "contributor": "second-entry"}))
        for n, b in payloads.items():
            zf.writestr(n, b)
    mf = unpack_share(out, tmp_path / "d")
    assert mf.contributor == "second-entry"


def test_name_max_boundary_artifact(tmp_path: Path) -> None:
    """产物名 ``_NAME_MAX``=255B 边界：恰 255B 收，256B → ``unsafe``。"""
    doc, payloads = _base_bundle(tmp_path)
    arts = doc["artifacts"]
    assert isinstance(arts, dict)
    ok_name, bad_name = "x" * 255, "y" * 256
    blob = b"NP"
    arts[ok_name] = {"sha256": hashlib.sha256(blob).hexdigest(), "bytes": 2}
    good = _repack(tmp_path / "g.zip", doc, {**payloads, ok_name: blob})
    mf = unpack_share(good, tmp_path / "d")
    assert (tmp_path / "d" / ok_name).read_bytes() == blob
    assert ok_name in mf.artifacts
    arts[bad_name] = {"sha256": hashlib.sha256(blob).hexdigest(), "bytes": 2}
    evil = _repack(tmp_path / "e.zip", doc, {**payloads, ok_name: blob, bad_name: blob})
    with pytest.raises(ShareError, match="unsafe"):
        unpack_share(evil, tmp_path / "d2")


def test_unpack_stale_dest_preserved_on_failure(tmp_path: Path) -> None:
    """失败路径既有 dest 零残留语义：坏包不动用户文件（fuzz 补钉）。"""
    doc, payloads = _base_bundle(tmp_path)
    arts = doc["artifacts"]
    assert isinstance(arts, dict)
    arts["zh.pdf"] = {"sha256": "0" * 64, "bytes": 8}  # sha 对不上 → 校验拒
    evil = _repack(tmp_path / "e.zip", doc, payloads)
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(ShareError):
        unpack_share(evil, dest)
    assert {p.name for p in dest.iterdir()} == {"keep.txt"}


def test_unpack_rename_phase_no_partial_publish(tmp_path: Path) -> None:
    """发布段预检：dest 既有同名**目录**挡住 rename → 开 rename 循环前整体
    ``IsADirectoryError``（OSError 域，环境冲突非坏包），已校验成员零落盘——
    ``zh-src.zip`` 保持 STALE，无部分发布。"""
    doc, payloads = _base_bundle(tmp_path)
    good = _repack(tmp_path / "g.zip", doc, payloads)
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "zh.pdf").mkdir()  # 同名目录——rename 到它必 IsADirectoryError
    (dest / "zh-src.zip").write_bytes(b"STALE")
    with pytest.raises(IsADirectoryError):
        unpack_share(good, dest)
    # 全或零语义：失败后 zh-src.zip 保持 STALE
    assert (dest / "zh-src.zip").read_bytes() == b"STALE"


# ---------------------------------------------------------------- share_key 直调


def test_fuzz_share_key_pipe_iff() -> None:
    """前六归一组分含 ``|`` ⇔ ShareError；否则 == 独立 sha256 重算。"""
    rng = fuzz_rng(_SEED_SHAREKEY)
    alphabet = ["a", "v1", " ", "|", "a|b", "数据", "x" * 40, "", "\t"]
    ver_pool = [None, "", "v3", "3", 3, "|", "v|x", " v5 "]
    for _ in range(_FUZZ_ITERS_SHAREKEY):
        parts = {
            f: rng.choice(ver_pool if f == "version" else alphabet)
            for f in KEY_PART_FIELDS
        }
        norm = _norm_parts_key(parts)
        key = _oracle_key(norm)
        if key is None:
            with pytest.raises(ShareError, match="must not contain"):
                share_key(**parts)
        else:
            assert share_key(**parts) == key
            assert share_key(**parts) == share_key(**parts)  # 确定性
