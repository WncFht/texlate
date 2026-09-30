"""share.py 单测：round-trip / 篡改与缺字段拒绝 / 成员安全 / key 组分敏感性。"""

from __future__ import annotations

import binascii
import hashlib
import json
import struct
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _sharekit import bundle_manifest as _bundle_manifest
from _sharekit import repack as _repack

from texlate.share import (
    ARTIFACT_NAMES,
    MANIFEST_NAME,
    REQUIRED_ARTIFACTS,
    SHARE_FORMAT,
    ShareError,
    index_append,
    index_lookup,
    pack_share,
    share_key,
    unpack_share,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import BinaryIO, Self

    from texlate.share import ShareManifest

_PARTS: dict[str, object] = {
    "arxiv_id": "1706.03762",
    "version": "v5",
    "model": "deepseek-chat",
    "prompt_ver": "xlat-prompt-v3",
    "target_lang": "zh-CN",
    "glossary_hash": "",
    "pipeline_ver": "texlate-0.1.0|xlat-prompt-v3",
}
_PDF_BYTES = b"%PDF-1.4 fake pdf"
_ZH_TEX = "\\documentclass{article}\\begin{document}正文\\end{document}"
_ZERO_SHA = "0" * 64
_KEY_HEX_LEN = 64


def _make_work(root: Path) -> Path:
    """tmp 下造最小产物三件套任务目录。"""
    w = root / "task"
    w.mkdir()
    (w / "dual.json").write_text(
        json.dumps({"version": 1, "documents": {}, "chunks": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (w / "zh.pdf").write_bytes(_PDF_BYTES)
    with zipfile.ZipFile(w / "zh-src.zip", "w") as zf:
        zf.writestr("main.tex", _ZH_TEX)
    return w


def _payloads(bundle: Path) -> dict[str, bytes]:
    """读出包内全部产物成员。"""
    with zipfile.ZipFile(bundle) as zf:
        return {n: zf.read(n) for n in ARTIFACT_NAMES}


def _tampered(
    tmp_path: Path,
    mutate_manifest: Callable[[dict[str, object]], None] | None = None,
    mutate_payloads: Callable[[dict[str, bytes]], None] | None = None,
    *,
    parts: dict[str, object] | None = None,
    out_name: str = "evil.share.zip",
) -> Path:
    """``_make_work → pack_share → 读回 manifest/payloads → 变异 → _repack`` 一条龙。

    篡改/前向兼容用例的公共 prologue：``mutate_*`` 回调就地改 dict（``del``
    或 isinstance 窄化写成局部 ``def`` 闭包抓参数）。manifest 变异不影响
    ``_payloads`` 读出结果，固定先读后变异与原先 lazy 读等值；``parts``
    可换打包组分（version 归一用例），``out_name`` 区分非 evil 语义的包。
    """
    work = _make_work(tmp_path)
    bundle = pack_share(
        work, parts if parts is not None else _PARTS, out_dir=tmp_path / "out"
    )
    manifest = _bundle_manifest(bundle)
    payloads = _payloads(bundle)
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    if mutate_payloads is not None:
        mutate_payloads(payloads)
    return _repack(tmp_path / out_name, manifest, payloads)


# ---------------------------------------------------------------- round-trip


def test_roundtrip(tmp_path: Path) -> None:
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    dest = tmp_path / "unpacked"
    mf = unpack_share(bundle, dest)
    assert bundle.name == f"{mf.share_key}.share.zip"
    assert mf.fmt == SHARE_FORMAT
    assert mf.share_key == share_key(**_PARTS)
    assert mf.key_parts == _PARTS
    assert set(mf.artifacts) == set(ARTIFACT_NAMES)
    assert mf.contributor.startswith("c-")
    assert mf.created_at
    for name in ARTIFACT_NAMES:
        assert (dest / name).read_bytes() == (work / name).read_bytes()
        assert mf.artifacts[name].size == len((work / name).read_bytes())


def test_pack_contributor_passthrough(tmp_path: Path) -> None:
    work = _make_work(tmp_path)
    bundle = pack_share(work, {**_PARTS, "contributor": "alice-01"}, out_dir=tmp_path)
    mf = unpack_share(bundle, tmp_path / "d")
    assert mf.contributor == "alice-01"


def test_pack_share_key_given_and_consistent(tmp_path: Path) -> None:
    """调用方带上正确 share_key → 接受。"""
    work = _make_work(tmp_path)
    key = share_key(**_PARTS)
    bundle = pack_share(work, {**_PARTS, "share_key": key}, out_dir=tmp_path)
    assert bundle.name == f"{key}.share.zip"


def test_pack_artifact_single_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """产物单读语义：``_pack_member`` 单开单流——同一字节流既写 zip 成员
    又算 manifest sha256，成员读完后磁盘件再被改不产生自矛盾包。"""
    work = _make_work(tmp_path)
    original = Path.open
    calls: list[str] = []

    class _MutateAtEof:
        """``zh.pdf`` 读流 EOF 时改源文件——模拟读-写间隙 TOCTOU。"""

        def __init__(self, fh: BinaryIO, path: Path) -> None:
            self._fh = fh
            self._path = path

        def read(self, n: int = -1) -> bytes:
            data = self._fh.read(n)
            if not data:
                self._path.write_bytes(b"MUTATED after stream consumed")
            return data

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_exc: object) -> None:
            self._fh.close()

        def __getattr__(self, name: str) -> object:
            return getattr(self._fh, name)

    def open_once(self: Path, mode: str = "r", *args: object, **kw: object) -> object:
        fh = original(self, mode, *args, **kw)
        if "r" in mode and "b" in mode and self.parent == work:
            calls.append(self.name)
            if self.name == "zh.pdf":
                return _MutateAtEof(fh, self)
        return fh

    monkeypatch.setattr(Path, "open", open_once)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    monkeypatch.undo()
    assert sorted(calls) == sorted(ARTIFACT_NAMES)
    unpack_share(bundle, tmp_path / "d")
    assert (tmp_path / "d" / "zh.pdf").read_bytes() == _PDF_BYTES


def test_pack_version_none_is_latest_alias(tmp_path: Path) -> None:
    """``version=None`` 归一 latest 别名（``""``）——与 ``share_key`` 直调同键。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, {**_PARTS, "version": None}, out_dir=tmp_path)
    mf = unpack_share(bundle, tmp_path / "d")
    assert mf.key_parts["version"] == ""
    assert mf.share_key == share_key(**{**_PARTS, "version": None})


# ---------------------------------------------------------------- 拒绝面


def test_unpack_rejects_non_zip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.share.zip"
    bad.write_bytes(b"this is not a zip archive")
    with pytest.raises(ShareError, match="not a readable"):
        unpack_share(bad, tmp_path / "d")


def test_tampered_artifact_rejected(tmp_path: Path) -> None:
    """成员内容被换（同长度，只 sha256 对不上）→ 拒绝。"""

    def swap(payloads: dict[str, bytes]) -> None:
        payloads["zh.pdf"] = bytes(len(_PDF_BYTES))

    evil = _tampered(tmp_path, mutate_payloads=swap)
    with pytest.raises(ShareError, match="sha256 mismatch"):
        unpack_share(evil, tmp_path / "d")


def test_resized_artifact_rejected(tmp_path: Path) -> None:
    """成员尺寸对不上 manifest 声明 → 拒绝（size 头对账先开火）。"""

    def shrink(payloads: dict[str, bytes]) -> None:
        payloads["dual.json"] = b"{}"

    evil = _tampered(tmp_path, mutate_payloads=shrink)
    with pytest.raises(ShareError, match="size mismatch"):
        unpack_share(evil, tmp_path / "d")


def test_lied_manifest_hash_rejected(tmp_path: Path) -> None:
    """manifest 里声明的 sha256 被改（产物本身真）→ 拒绝。"""

    def lie(manifest: dict[str, object]) -> None:
        arts = manifest["artifacts"]
        assert isinstance(arts, dict)
        arts["zh.pdf"] = {"sha256": _ZERO_SHA, "bytes": len(_PDF_BYTES)}

    evil = _tampered(tmp_path, mutate_manifest=lie)
    with pytest.raises(ShareError, match="sha256 mismatch"):
        unpack_share(evil, tmp_path / "d")


def test_member_missing_from_zip_rejected(tmp_path: Path) -> None:
    """manifest 登记了 zh.pdf 但包里没有该成员 → 拒绝。"""

    def drop_pdf(payloads: dict[str, bytes]) -> None:
        del payloads["zh.pdf"]

    evil = _tampered(tmp_path, mutate_payloads=drop_pdf)
    with pytest.raises(ShareError, match="missing"):
        unpack_share(evil, tmp_path / "d")


@pytest.mark.parametrize("drop", ["format", "share_key", "key_parts", "artifacts"])
def test_manifest_missing_top_fields_rejected(tmp_path: Path, drop: str) -> None:
    def drop_field(manifest: dict[str, object]) -> None:
        del manifest[drop]

    evil = _tampered(tmp_path, mutate_manifest=drop_field)
    with pytest.raises(ShareError):
        unpack_share(evil, tmp_path / "d")


@pytest.mark.parametrize("field", ["model", "prompt_ver", "pipeline_ver"])
def test_manifest_missing_key_part_rejected(tmp_path: Path, field: str) -> None:
    def drop_part(manifest: dict[str, object]) -> None:
        parts = manifest["key_parts"]
        assert isinstance(parts, dict)
        del parts[field]

    evil = _tampered(tmp_path, mutate_manifest=drop_part)
    with pytest.raises(ShareError, match="key part"):
        unpack_share(evil, tmp_path / "d")


def test_unsafe_artifact_name_rejected(tmp_path: Path) -> None:
    """manifest artifacts 里出现 ``../`` 名 → 拒绝（zip-slip 闸）。"""

    def add_unsafe(manifest: dict[str, object]) -> None:
        arts = manifest["artifacts"]
        assert isinstance(arts, dict)
        arts["../evil.tex"] = {"sha256": _ZERO_SHA, "bytes": 3}

    evil = _tampered(tmp_path, mutate_manifest=add_unsafe)
    with pytest.raises(ShareError, match="unsafe"):
        unpack_share(evil, tmp_path / "d")


@pytest.mark.parametrize("bad", ["a\x00b", "x" * 300])
def test_bad_artifact_name_rejected(tmp_path: Path, bad: str) -> None:
    """NUL / 超 NAME_MAX(255B) 的产物名 → 拒绝（写盘前闸死，不放行成 500）。"""

    def add_bad(manifest: dict[str, object]) -> None:
        arts = manifest["artifacts"]
        assert isinstance(arts, dict)
        arts[bad] = {"sha256": _ZERO_SHA, "bytes": 3}

    evil = _tampered(tmp_path, mutate_manifest=add_bad)
    with pytest.raises(ShareError, match="unsafe"):
        unpack_share(evil, tmp_path / "d")


def test_bad_utf8_member_name_rejected(tmp_path: Path) -> None:
    """中央目录成员名标 UTF-8 flag 但字节非法 → ``not a readable``（不炸 UnicodeDecodeError）。"""
    name = b"a\xff\xfeb"
    content = b"x"
    crc = binascii.crc32(content) & 0xFFFFFFFF
    local = (
        struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,
            0x800,
            0,
            0,
            0,
            crc,
            len(content),
            len(content),
            len(name),
            0,
        )
        + name
    )
    cd_off = len(local) + len(content)
    central = (
        struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            0x800,
            0,
            0,
            0,
            crc,
            len(content),
            len(content),
            len(name),
            0,
            0,
            0,
            0,
            0,
            0,
        )
        + name
    )
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central), cd_off, 0)
    bad = tmp_path / "bad.share.zip"
    bad.write_bytes(local + content + central + eocd)
    with pytest.raises(ShareError, match="not a readable"):
        unpack_share(bad, tmp_path / "d")


def test_unknown_compression_member_rejected(tmp_path: Path) -> None:
    """产物成员标未知压缩方法 → ``corrupt member``（不炸 NotImplementedError）。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    data = bytearray(bundle.read_bytes())
    # 只把 dual.json 成员的 method 字段（local+central 两处）改成未知值 99
    for sig, m_off, n_off in ((b"PK\x03\x04", 8, 26), (b"PK\x01\x02", 10, 28)):
        idx = data.find(sig)
        while idx != -1:
            nlen = int.from_bytes(data[idx + n_off : idx + n_off + 2], "little")
            name_at = idx + n_off + 4 if sig == b"PK\x03\x04" else idx + n_off + 18
            if bytes(data[name_at : name_at + nlen]) == b"dual.json":
                data[idx + m_off] = 99
            idx = data.find(sig, idx + 1)
    evil = tmp_path / "evil.share.zip"
    evil.write_bytes(bytes(data))
    with pytest.raises(ShareError, match="corrupt member"):
        unpack_share(evil, tmp_path / "d")


@pytest.mark.parametrize("drop", list(REQUIRED_ARTIFACTS))
def test_pack_missing_required_artifact_rejected(tmp_path: Path, drop: str) -> None:
    """必需产物（zh-src.zip/dual.json）缺席 → 拒绝。"""
    work = _make_work(tmp_path)
    (work / drop).unlink()
    with pytest.raises(ShareError, match="missing in work_dir"):
        pack_share(work, _PARTS, out_dir=tmp_path)


def test_pack_partial_no_zh_pdf(tmp_path: Path) -> None:
    """zh.pdf 缺席的 partial 任务 → 合法打包：manifest 不登记、包内无成员、
    unpack 正常消费（与 ``REQUIRED_ARTIFACTS`` 口径对称）。"""
    work = _make_work(tmp_path)
    (work / "zh.pdf").unlink()
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    doc = _bundle_manifest(bundle)
    arts = doc["artifacts"]
    assert isinstance(arts, dict)
    assert set(arts) == set(REQUIRED_ARTIFACTS)
    with zipfile.ZipFile(bundle) as zf:
        assert set(zf.namelist()) == {MANIFEST_NAME, *REQUIRED_ARTIFACTS}
    dest = tmp_path / "unpacked"
    mf = unpack_share(bundle, dest)
    assert set(mf.artifacts) == set(REQUIRED_ARTIFACTS)
    for name in REQUIRED_ARTIFACTS:
        assert (dest / name).read_bytes() == (work / name).read_bytes()
    assert not (dest / "zh.pdf").exists()


@pytest.mark.parametrize("drop", ["model", "version", "glossary_hash"])
def test_pack_missing_key_part_rejected(tmp_path: Path, drop: str) -> None:
    """七键必带——可空组分（version/glossary_hash）整键缺席也按 missing 拒。"""
    work = _make_work(tmp_path)
    bad = {k: v for k, v in _PARTS.items() if k != drop}
    with pytest.raises(ShareError, match="missing key part"):
        pack_share(work, bad, out_dir=tmp_path)


def test_pack_null_non_emptyable_key_part_rejected(tmp_path: Path) -> None:
    """非可空组分值为 ``None`` → 拒（null 只等价于 ``""`` 于 _EMPTY_OK 字段）。"""
    work = _make_work(tmp_path)
    with pytest.raises(ShareError, match="key part empty"):
        pack_share(work, {**_PARTS, "model": None}, out_dir=tmp_path)


def test_pack_share_key_mismatch_rejected(tmp_path: Path) -> None:
    """调用方 share_key 与组分不符 → 拒绝（错配防呆）。"""
    work = _make_work(tmp_path)
    with pytest.raises(ShareError, match="share_key mismatch"):
        pack_share(work, {**_PARTS, "share_key": _ZERO_SHA}, out_dir=tmp_path)


def test_extra_zip_member_ignored(tmp_path: Path) -> None:
    """manifest 未登记的包内成员被忽略且不落地。"""

    def add_member(payloads: dict[str, bytes]) -> None:
        payloads["evil.txt"] = b"nope"

    repacked = _tampered(
        tmp_path, mutate_payloads=add_member, out_name="extra.share.zip"
    )
    dest = tmp_path / "d"
    mf = unpack_share(repacked, dest)
    assert set(mf.artifacts) == set(ARTIFACT_NAMES)
    assert not (dest / "evil.txt").exists()


def test_extra_manifest_artifact_extracted(tmp_path: Path) -> None:
    """manifest 登记了标准三件套以外的成员 → 照样校验落地（前向兼容）。"""
    extra = b"future artifact payload"

    def add_decl(manifest: dict[str, object]) -> None:
        arts = manifest["artifacts"]
        assert isinstance(arts, dict)
        arts["extra.txt"] = {
            "sha256": hashlib.sha256(extra).hexdigest(),
            "bytes": len(extra),
        }

    def add_blob(payloads: dict[str, bytes]) -> None:
        payloads["extra.txt"] = extra

    repacked = _tampered(tmp_path, add_decl, add_blob, out_name="fwd.share.zip")
    dest = tmp_path / "d"
    mf = unpack_share(repacked, dest)
    assert "extra.txt" in mf.artifacts
    assert (dest / "extra.txt").read_bytes() == extra


def _tampered_last_artifact(tmp_path: Path) -> Path:
    """造末位成员（dual.json）sha256 对账失败的包——前两成员校验均通过。"""

    def zero_tail(payloads: dict[str, bytes]) -> None:
        # 同长换内容：size 头对账过、sha256 开火——中途失败点
        payloads["dual.json"] = bytes(len(payloads["dual.json"]))

    return _tampered(tmp_path, mutate_payloads=zero_tail)


def test_unpack_mid_failure_no_residue(tmp_path: Path) -> None:
    """新 dest + 校验中途失败 → dest 整个收走，零残留。"""
    evil = _tampered_last_artifact(tmp_path)
    dest = tmp_path / "d"
    with pytest.raises(ShareError, match="sha256 mismatch"):
        unpack_share(evil, dest)
    assert not dest.exists()


def test_unpack_mid_failure_preserves_existing_dest(tmp_path: Path) -> None:
    """dest 既有目录：失败只清临时件——用户文件与同名旧成员原样保留。"""
    evil = _tampered_last_artifact(tmp_path)
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "keep.txt").write_text("user data", encoding="utf-8")
    (dest / "zh.pdf").write_bytes(b"STALE")  # 同名旧件——校验失败不得覆写
    with pytest.raises(ShareError, match="sha256 mismatch"):
        unpack_share(evil, dest)
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "user data"
    assert (dest / "zh.pdf").read_bytes() == b"STALE"
    assert {p.name for p in dest.iterdir()} == {"keep.txt", "zh.pdf"}


def test_unpack_replaces_and_cleans_tmp(tmp_path: Path) -> None:
    """成功路径：同名旧件被替换，dest 不留临时目录。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "zh.pdf").write_bytes(b"STALE")
    mf = unpack_share(bundle, dest)
    assert set(mf.artifacts) == set(ARTIFACT_NAMES)
    assert (dest / "zh.pdf").read_bytes() == _PDF_BYTES
    assert {p.name for p in dest.iterdir()} == set(ARTIFACT_NAMES)


def test_unpack_publish_mid_failure_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """发布段第二件 rename 注入失败 → 回滚：新件撤出、备份还原，dest 原样。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    dest = tmp_path / "d"
    dest.mkdir()
    for name in ARTIFACT_NAMES:
        (dest / name).write_bytes(f"STALE-{name}".encode())
    real_replace = Path.replace
    published: list[str] = []
    armed = True
    msg = "simulated mid-publish failure"

    def flaky(self: Path, target: Path) -> Path:
        nonlocal armed
        # 只拦「落进 dest」的发布移动；撤备份/还原移动放行，炸一次即卸引信
        if Path(target).parent == dest:
            published.append(self.name)
            if armed and self.name == "zh.pdf":
                armed = False
                raise OSError(msg)
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    with pytest.raises(OSError, match="mid-publish"):
        unpack_share(bundle, dest)
    # 前两位 = 发布失败点；后续条目是回滚还原移动（同落 dest 被计数）
    assert published[:2] == ["zh-src.zip", "zh.pdf"]
    for name in ARTIFACT_NAMES:
        assert (dest / name).read_bytes() == f"STALE-{name}".encode()
    assert {p.name for p in dest.iterdir()} == set(ARTIFACT_NAMES)


def test_pack_mid_failure_no_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """构建中途失败 → 临时 zip 收走，out_dir 零残留。"""
    work = _make_work(tmp_path)
    out_dir = tmp_path / "out"

    def boom(*_a: object) -> None:
        msg = "simulated mid-pack failure"
        raise OSError(msg)

    monkeypatch.setattr("texlate.share._pack_member", boom)
    with pytest.raises(OSError, match="mid-pack"):
        pack_share(work, _PARTS, out_dir=out_dir)
    assert not list(out_dir.iterdir())


# ---------------------------------------------------------------- share_key


def test_share_key_deterministic() -> None:
    key = share_key(**_PARTS)
    assert len(key) == _KEY_HEX_LEN
    assert key == share_key(**_PARTS)


@pytest.mark.parametrize("field", list(_PARTS))
def test_share_key_sensitive_to_each_part(field: str) -> None:
    """任一组分变动 → key 变。"""
    alt = {**_PARTS, field: f"{_PARTS[field]}-x"}
    assert share_key(**alt) != share_key(**_PARTS)


def test_share_key_version_normalization() -> None:
    """``5``/``"5"``/``"v5"`` 同键；``None``/``""`` 是 latest 别名（不同键）。"""
    base = share_key(**_PARTS)
    assert share_key(**{**_PARTS, "version": 5}) == base
    assert share_key(**{**_PARTS, "version": "5"}) == base
    assert share_key(**{**_PARTS, "version": " v5 "}) == base
    latest = share_key(**{**_PARTS, "version": None})
    assert latest == share_key(**{**_PARTS, "version": ""})
    assert latest != base


def test_share_key_rejects_pipe_in_parts() -> None:
    """前六组分含 ``|`` 会撞分隔符 → ShareError；末位 pipeline_ver 允许。"""
    with pytest.raises(ShareError, match="must not contain"):
        share_key(**{**_PARTS, "model": "a|b"})
    # pipeline_ver 天生含 '|'（texlate-{ver}|{prompt_ver}）——末位不歧义
    assert share_key(**_PARTS)


def test_share_key_last_part_pipe_unambiguous() -> None:
    """``pipeline_ver`` 内 ``|`` 不产生别名：把 ``|`` 前移进前六组分的构造被拒。"""
    tail = share_key(**{**_PARTS, "pipeline_ver": "x|y"})
    with pytest.raises(ShareError, match="must not contain"):
        share_key(**{**_PARTS, "glossary_hash": "g|x", "pipeline_ver": "y"})
    assert tail


def test_share_key_strips_whitespace() -> None:
    """直调组分带边缘空白 → 与 manifest 侧 strip 归一后同键。"""
    assert share_key(**{**_PARTS, "model": " deepseek-chat "}) == share_key(**_PARTS)
    assert share_key(**{**_PARTS, "target_lang": "zh-CN "}) == share_key(**_PARTS)


def test_share_key_front_matter_enters_material() -> None:
    """``front_matter`` 非空 → 插 ``pipeline_ver`` 前进键；空串/缺席同键
    （与前置全盖过的历史包同口径——七组分键不变）。"""
    base = share_key(**_PARTS)
    keyed = share_key(**_PARTS, front_matter="abstract,title")
    assert keyed != base
    assert keyed != share_key(**_PARTS, front_matter="title")
    assert share_key(**_PARTS, front_matter="") == base
    assert share_key(**_PARTS, front_matter="  ") == base  # strip 归一后同 ∅


def test_share_key_rejects_pipe_in_front_matter() -> None:
    """``front_matter`` 在 ``pipeline_ver`` 前进材料——含 ``|`` 撞分隔符
    → ShareError（受 ``parts[:-1]`` 闸覆盖）。"""
    with pytest.raises(ShareError, match="must not contain"):
        share_key(**_PARTS, front_matter="abstract|title")


def test_unpack_key_parts_empty_front_matter_omitted(tmp_path: Path) -> None:
    """key_parts.front_matter 空串 → ``key_parts`` 不落该字段（∅ 与历史缺席
    同形），share_key 重算仍命中七组分键。"""

    def blank_fm(manifest: dict[str, object]) -> None:
        parts = manifest["key_parts"]
        assert isinstance(parts, dict)
        parts["front_matter"] = ""

    repacked = _tampered(tmp_path, blank_fm, out_name="fm.share.zip")
    mf = unpack_share(repacked, tmp_path / "d")
    assert "front_matter" not in mf.key_parts
    assert mf.share_key == share_key(**_PARTS)


def test_unpack_key_parts_extra_fields_tolerated(tmp_path: Path) -> None:
    """key_parts 多出未知字段 → 忽略（前向兼容），只用七组分派生。"""

    def add_field(manifest: dict[str, object]) -> None:
        parts = manifest["key_parts"]
        assert isinstance(parts, dict)
        parts["future_field"] = "x"

    repacked = _tampered(tmp_path, add_field, out_name="fwd.share.zip")
    mf = unpack_share(repacked, tmp_path / "d")
    assert mf.key_parts == _PARTS


def test_unpack_key_parts_version_null(tmp_path: Path) -> None:
    """key_parts.version 为 JSON null → 归一 ``""``（latest 别名）照常解包。"""
    parts_empty = {**_PARTS, "version": ""}

    def null_version(manifest: dict[str, object]) -> None:
        kp = manifest["key_parts"]
        assert isinstance(kp, dict)
        kp["version"] = None  # JSON null 与 "" 同义

    repacked = _tampered(
        tmp_path, null_version, parts=parts_empty, out_name="null.share.zip"
    )
    mf = unpack_share(repacked, tmp_path / "d")
    assert mf.key_parts["version"] == ""
    assert mf.share_key == share_key(**parts_empty)


# ---------------------------------------------------------------- index.jsonl


def _packed(root: Path, parts: dict[str, object]) -> tuple[Path, ShareManifest]:
    """打一包再解出 manifest——index 用例的行字段来源。"""
    root.mkdir()
    work = _make_work(root)
    bundle = pack_share(work, parts, out_dir=root / "out")
    return bundle, unpack_share(bundle, root / "unpacked")


def test_index_append_lookup_roundtrip(tmp_path: Path) -> None:
    """两个不同 key 的包入索引后都可回读；行字段 = manifest + 入参。"""
    b1, m1 = _packed(tmp_path / "a", _PARTS)
    b2, m2 = _packed(tmp_path / "b", {**_PARTS, "model": "qwen-plus"})
    idx = tmp_path / "idx" / "index.jsonl"
    row1 = index_append(
        idx,
        m1,
        url=f"https://h.invalid/{m1.share_key}.share.zip",
        package_bytes=b1.stat().st_size,
    )
    row2 = index_append(
        idx,
        m2,
        url=f"https://h.invalid/{m2.share_key}.share.zip",
        package_bytes=b2.stat().st_size,
    )
    assert m1.share_key != m2.share_key
    assert row1 == {
        "share_key": m1.share_key,
        "url": f"https://h.invalid/{m1.share_key}.share.zip",
        "key_parts": m1.key_parts,
        "bytes": b1.stat().st_size,
        "created_at": m1.created_at,
        "contributor": m1.contributor,
    }
    assert index_lookup(idx, m1.share_key) == row1
    assert index_lookup(idx, m2.share_key) == row2
    assert idx.read_text(encoding="utf-8").splitlines() == [
        json.dumps(row1, ensure_ascii=False),
        json.dumps(row2, ensure_ascii=False),
    ]


def test_index_lookup_last_wins(tmp_path: Path) -> None:
    """同 share_key 追加两行 → lookup 返回后写的（append-only 重传覆盖）。"""
    bundle, mf = _packed(tmp_path / "a", _PARTS)
    idx = tmp_path / "index.jsonl"
    size = bundle.stat().st_size
    index_append(idx, mf, url="https://h.invalid/old.zip", package_bytes=size)
    index_append(idx, mf, url="https://h.invalid/new.zip", package_bytes=size)
    row = index_lookup(idx, mf.share_key)
    assert row is not None
    assert row["url"] == "https://h.invalid/new.zip"


def test_index_lookup_miss(tmp_path: Path) -> None:
    """索引有行但 share_key 不命中 → ``None``。"""
    bundle, mf = _packed(tmp_path / "a", _PARTS)
    idx = tmp_path / "index.jsonl"
    index_append(
        idx, mf, url="https://h.invalid/x.zip", package_bytes=bundle.stat().st_size
    )
    assert index_lookup(idx, _ZERO_SHA) is None


def test_index_malformed_lines_skipped(tmp_path: Path) -> None:
    """坏行（非 JSON / 非 object）夹中间不毒死索引——合法键照常命中。"""
    idx = tmp_path / "index.jsonl"
    idx.write_text(
        '{"share_key": "a"}\nnot-json\n[1, 2]\n{"share_key": "b"}\n',
        encoding="utf-8",
    )
    assert index_lookup(idx, "a") == {"share_key": "a"}
    assert index_lookup(idx, "b") == {"share_key": "b"}
    assert index_lookup(idx, "c") is None


def test_index_malformed_preserves_last_wins(tmp_path: Path) -> None:
    """同键合法行之间夹坏行——last-wins 不受干扰（坏行不参与覆盖）。"""
    idx = tmp_path / "index.jsonl"
    idx.write_text(
        '{"share_key": "a", "url": "old"}\n{bad\n{"share_key": "a", "url": "new"}\n',
        encoding="utf-8",
    )
    assert index_lookup(idx, "a") == {"share_key": "a", "url": "new"}


def test_index_all_malformed_misses(tmp_path: Path) -> None:
    """全坏行 → miss 返回 ``None`` 不炸。"""
    idx = tmp_path / "index.jsonl"
    idx.write_text('not-json\n"str"\n{bad\n', encoding="utf-8")
    assert index_lookup(idx, "a") is None


def test_index_missing_file(tmp_path: Path) -> None:
    """索引缺席：lookup → ``None``；append 自动建父目录落行。"""
    idx = tmp_path / "deep" / "dir" / "index.jsonl"
    assert index_lookup(idx, "a") is None
    bundle, mf = _packed(tmp_path / "a", _PARTS)
    index_append(
        idx, mf, url="https://h.invalid/x.zip", package_bytes=bundle.stat().st_size
    )
    assert index_lookup(idx, mf.share_key) is not None


def test_index_blank_lines_tolerated(tmp_path: Path) -> None:
    """空行/纯空白行跳过不报错。"""
    idx = tmp_path / "index.jsonl"
    idx.write_text('\n{"share_key": "a"}\n   \n', encoding="utf-8")
    assert index_lookup(idx, "a") == {"share_key": "a"}
    assert index_lookup(idx, "b") is None
