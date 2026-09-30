"""SourceCache 钉版目录：glob 消毒、get 语义、原子 commit/回滚（docs/spec/arxiv-source.md）。"""

import json
from pathlib import Path

import pytest

from texlate.arxiv.cache import CacheError, SourceCache


def _stage_with_meta(cache: SourceCache, tag: str = "m") -> Path:
    staging = cache.stage()
    (staging / "meta.json").write_text(
        json.dumps({"arxiv_id": "1502.01589", "tag": tag}), encoding="utf-8"
    )
    return staging


def test_find_versions_lists_sorted(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path / "src")
    for v in (10, 2, 1):
        (cache.root / f"1502.01589v{v}").mkdir(parents=True)
    (cache.root / "1502.01589vX").mkdir()  # 非数字尾巴不算
    (cache.root / "1502.01589v3.bak").mkdir()
    assert cache.find_versions("1502.01589") == [1, 2, 10]


def test_find_versions_glob_injection_empty(tmp_path: Path) -> None:
    """glob 元字符/``..``/前导 ``/`` 一律空集——``/etc`` 曾让
    ``root.glob("/etcv*")`` 成绝对模式抛 NotImplementedError。"""
    cache = SourceCache(tmp_path / "src")
    cache.root.mkdir(parents=True)
    for bad in ("/etc", "/", "a*?", "a[bc]", "a/../b", "..", "", "a\x00b"):
        assert cache.find_versions(bad) == []
    assert cache.find_versions("1502.01589") == []


def test_get_miss_and_corrupt_meta(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path / "src")
    assert cache.get("1502.01589", 1) is None
    d = cache.root / "1502.01589v1"
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{bad json", encoding="utf-8")
    assert cache.get("1502.01589", 1) is None  # 损坏按 miss
    (d / "meta.json").write_text("[1,2]", encoding="utf-8")
    assert cache.get("1502.01589", 1) is None  # 非对象按 miss
    (d / "meta.json").write_text('{"arxiv_id": "x"}', encoding="utf-8")
    e = cache.get("1502.01589", 1)
    assert e is not None
    assert e.meta["arxiv_id"] == "x"


def test_get_entry_dir_escape_raises(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path / "src")
    with pytest.raises(CacheError, match="escapes cache root"):
        cache.get("../outside", 1)


def test_get_latest_picks_highest_valid(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path / "src")
    for v in (1, 2, 3):
        d = cache.root / f"1502.01589v{v}"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(f'{{"v": {v}}}', encoding="utf-8")
    # v3 meta 损坏 → 回退 v2
    (cache.root / "1502.01589v3" / "meta.json").write_text("{bad", encoding="utf-8")
    e = cache.get_latest("1502.01589")
    assert e is not None
    assert e.resolved_version == 2  # noqa: PLR2004


def test_commit_atomic_and_last_wins(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path / "src")
    s1 = _stage_with_meta(cache, "A")
    e1 = cache.commit(s1, "1502.01589", 1)
    assert e1.meta["tag"] == "A"
    s2 = _stage_with_meta(cache, "B")
    e2 = cache.commit(s2, "1502.01589", 1)
    assert e2.meta["tag"] == "B"
    assert json.loads((e2.dir / "meta.json").read_text())["tag"] == "B"
    # 无 .old-/.staging- 残渣
    assert not list(cache.root.glob(".old-*"))
    assert not list(cache.root.glob(".staging-*"))


def test_commit_dest_stray_file_replaced(tmp_path: Path) -> None:
    """dest 位被散文件占用：rename 备份后 rmtree(file) 会静默失败留
    ``.old-*`` 残渣——按类型分流 unlink。"""
    cache = SourceCache(tmp_path / "src")
    cache.root.mkdir(parents=True)
    (cache.root / "1502.01589v1").write_text("stray", encoding="utf-8")
    staging = _stage_with_meta(cache)
    e = cache.commit(staging, "1502.01589", 1)
    assert (e.dir / "meta.json").is_file()
    assert not list(cache.root.glob(".old-*"))


def test_commit_requires_meta(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path / "src")
    staging = cache.stage()
    with pytest.raises(CacheError, match=r"missing meta\.json"):
        cache.commit(staging, "1502.01589", 1)
    SourceCache.cleanup(staging)


def test_commit_bad_meta_object(tmp_path: Path) -> None:
    cache = SourceCache(tmp_path / "src")
    staging = cache.stage()
    (staging / "meta.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(CacheError, match="not an object"):
        cache.commit(staging, "1502.01589", 1)
    SourceCache.cleanup(staging)


def test_commit_nested_old_style_id(tmp_path: Path) -> None:
    """旧式 id 自带 ``archive/`` 段 → 嵌套目录正常落。"""
    cache = SourceCache(tmp_path / "src")
    staging = _stage_with_meta(cache)
    e = cache.commit(staging, "hep-th/9901001", 2)
    assert e.dir == cache.root / "hep-th/9901001v2"
    assert (e.dir / "meta.json").is_file()


def test_entry_dir_nul_raises_cache_error(tmp_path: Path) -> None:
    """NUL 内嵌 id：``resolve`` 裸 ``ValueError`` 收口为 ``CacheError``——
    与逃逸臂同契约（textutil ``safe_resolve`` 同款 catch 集）。"""
    cache = SourceCache(tmp_path / "src")
    for bad in ("a\x00b", "\x00"):
        with pytest.raises(CacheError, match="not path-representable"):
            cache.entry_dir(bad, 1)
        with pytest.raises(CacheError, match="not path-representable"):
            cache.get(bad, 1)
