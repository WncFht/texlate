"""share.py 单测：round-trip / 篡改与缺字段拒绝 / 成员安全 / key 组分敏感性。"""

from __future__ import annotations

import hashlib
import json
import zipfile
from typing import TYPE_CHECKING

import pytest

from texlate.share import (
    ARTIFACT_NAMES,
    MANIFEST_NAME,
    REQUIRED_ARTIFACTS,
    SHARE_FORMAT,
    ShareError,
    pack_share,
    share_key,
    unpack_share,
)

if TYPE_CHECKING:
    from pathlib import Path

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


def _bundle_manifest(bundle: Path) -> dict[str, object]:
    """读出包内 manifest.json。"""
    with zipfile.ZipFile(bundle) as zf:
        doc = json.loads(zf.read(MANIFEST_NAME))
    assert isinstance(doc, dict)
    return doc


def _payloads(bundle: Path) -> dict[str, bytes]:
    """读出包内全部产物成员。"""
    with zipfile.ZipFile(bundle) as zf:
        return {n: zf.read(n) for n in ARTIFACT_NAMES}


def _repack(out: Path, manifest: dict[str, object], payloads: dict[str, bytes]) -> Path:
    """按给定 manifest/payload 直写 bundle——篡改用例的构造器（不走 pack_share）。"""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False))
        for name, blob in payloads.items():
            zf.writestr(name, blob)
    return out


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


# ---------------------------------------------------------------- 拒绝面


def test_unpack_rejects_non_zip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.share.zip"
    bad.write_bytes(b"this is not a zip archive")
    with pytest.raises(ShareError, match="not a readable"):
        unpack_share(bad, tmp_path / "d")


def test_tampered_artifact_rejected(tmp_path: Path) -> None:
    """成员内容被换（同长度，只 sha256 对不上）→ 拒绝。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    manifest = _bundle_manifest(bundle)
    payloads = _payloads(bundle)
    payloads["zh.pdf"] = bytes(len(_PDF_BYTES))
    evil = _repack(tmp_path / "evil.share.zip", manifest, payloads)
    with pytest.raises(ShareError, match="sha256 mismatch"):
        unpack_share(evil, tmp_path / "d")


def test_resized_artifact_rejected(tmp_path: Path) -> None:
    """成员尺寸对不上 manifest 声明 → 拒绝（size 头对账先开火）。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    manifest = _bundle_manifest(bundle)
    payloads = _payloads(bundle)
    payloads["dual.json"] = b"{}"
    evil = _repack(tmp_path / "evil.share.zip", manifest, payloads)
    with pytest.raises(ShareError, match="size mismatch"):
        unpack_share(evil, tmp_path / "d")


def test_lied_manifest_hash_rejected(tmp_path: Path) -> None:
    """manifest 里声明的 sha256 被改（产物本身真）→ 拒绝。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    manifest = _bundle_manifest(bundle)
    arts = manifest["artifacts"]
    assert isinstance(arts, dict)
    arts["zh.pdf"] = {"sha256": _ZERO_SHA, "bytes": len(_PDF_BYTES)}
    evil = _repack(tmp_path / "evil.share.zip", manifest, _payloads(bundle))
    with pytest.raises(ShareError, match="sha256 mismatch"):
        unpack_share(evil, tmp_path / "d")


def test_member_missing_from_zip_rejected(tmp_path: Path) -> None:
    """manifest 登记了 zh.pdf 但包里没有该成员 → 拒绝。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    manifest = _bundle_manifest(bundle)
    payloads = _payloads(bundle)
    del payloads["zh.pdf"]
    evil = _repack(tmp_path / "evil.share.zip", manifest, payloads)
    with pytest.raises(ShareError, match="missing"):
        unpack_share(evil, tmp_path / "d")


@pytest.mark.parametrize("drop", ["format", "share_key", "key_parts", "artifacts"])
def test_manifest_missing_top_fields_rejected(tmp_path: Path, drop: str) -> None:
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    manifest = _bundle_manifest(bundle)
    del manifest[drop]
    evil = _repack(tmp_path / "evil.share.zip", manifest, _payloads(bundle))
    with pytest.raises(ShareError):
        unpack_share(evil, tmp_path / "d")


@pytest.mark.parametrize("field", ["model", "prompt_ver", "pipeline_ver"])
def test_manifest_missing_key_part_rejected(tmp_path: Path, field: str) -> None:
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    manifest = _bundle_manifest(bundle)
    parts = manifest["key_parts"]
    assert isinstance(parts, dict)
    del parts[field]
    evil = _repack(tmp_path / "evil.share.zip", manifest, _payloads(bundle))
    with pytest.raises(ShareError, match="key part"):
        unpack_share(evil, tmp_path / "d")


def test_unsafe_artifact_name_rejected(tmp_path: Path) -> None:
    """manifest artifacts 里出现 ``../`` 名 → 拒绝（zip-slip 闸）。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    manifest = _bundle_manifest(bundle)
    arts = manifest["artifacts"]
    assert isinstance(arts, dict)
    arts["../evil.tex"] = {"sha256": _ZERO_SHA, "bytes": 3}
    evil = _repack(tmp_path / "evil.share.zip", manifest, _payloads(bundle))
    with pytest.raises(ShareError, match="unsafe"):
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


def test_pack_missing_key_part_rejected(tmp_path: Path) -> None:
    work = _make_work(tmp_path)
    bad = {k: v for k, v in _PARTS.items() if k != "model"}
    with pytest.raises(ShareError, match="missing key part"):
        pack_share(work, bad, out_dir=tmp_path)


def test_pack_share_key_mismatch_rejected(tmp_path: Path) -> None:
    """调用方 share_key 与组分不符 → 拒绝（错配防呆）。"""
    work = _make_work(tmp_path)
    with pytest.raises(ShareError, match="share_key mismatch"):
        pack_share(work, {**_PARTS, "share_key": _ZERO_SHA}, out_dir=tmp_path)


def test_extra_zip_member_ignored(tmp_path: Path) -> None:
    """manifest 未登记的包内成员被忽略且不落地。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    manifest = _bundle_manifest(bundle)
    payloads = {**_payloads(bundle), "evil.txt": b"nope"}
    repacked = _repack(tmp_path / "extra.share.zip", manifest, payloads)
    dest = tmp_path / "d"
    mf = unpack_share(repacked, dest)
    assert set(mf.artifacts) == set(ARTIFACT_NAMES)
    assert not (dest / "evil.txt").exists()


def test_extra_manifest_artifact_extracted(tmp_path: Path) -> None:
    """manifest 登记了标准三件套以外的成员 → 照样校验落地（前向兼容）。"""
    work = _make_work(tmp_path)
    bundle = pack_share(work, _PARTS, out_dir=tmp_path / "out")
    manifest = _bundle_manifest(bundle)
    arts = manifest["artifacts"]
    assert isinstance(arts, dict)
    extra = b"future artifact payload"
    arts["extra.txt"] = {
        "sha256": hashlib.sha256(extra).hexdigest(),
        "bytes": len(extra),
    }
    repacked = _repack(
        tmp_path / "fwd.share.zip", manifest, {**_payloads(bundle), "extra.txt": extra}
    )
    dest = tmp_path / "d"
    mf = unpack_share(repacked, dest)
    assert "extra.txt" in mf.artifacts
    assert (dest / "extra.txt").read_bytes() == extra


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
