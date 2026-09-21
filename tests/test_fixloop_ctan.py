"""ctan — tlpdb 索引 / fetch_package 解包 / version_guard / ctan_fetch 全链单测。

全部离线: fetcher 注入返回内存构造的 tar.xz / tlpdb.xz; 不触网。
"""

import lzma
from pathlib import Path

import pytest
from test_ctan_hardening import MIRROR, make_tarxz

from texlate.compile.ctan import (
    CtanFetcher,
    TlpdbIndex,
    check_version_compat,
    ctan_fetch,
    default_cache_dir,
    fetch_package,
)

TLPDB_TEXT = """\
name foo
runfiles
  texmf-dist/tex/latex/foo/foo.sty
  RELOC/tex/latex/foo/foo.def
docfiles
  texmf-dist/doc/foo/readme.txt
srcfiles
  texmf-dist/src/foo/foo.dtx
name bar
runfiles
  texmf-dist/tex/latex/bar/bar.sty
  texmf-dist/tex/latex/bar/same.sty
name zzz
runfiles
  texmf-dist/tex/latex/zzz/same.sty
"""


def write_tlpdb(tmp_path: Path) -> Path:
    p = tmp_path / "texlive.tlpdb"
    p.write_text(TLPDB_TEXT)
    return p


# ---------------------------------------------------------------- TlpdbIndex
def test_from_tlpdb_indexes_basenames(tmp_path: Path) -> None:
    idx = TlpdbIndex.from_tlpdb(write_tlpdb(tmp_path))
    assert idx.table["foo.sty"] == ["foo"]
    assert idx.table["foo.def"] == ["foo"]  # RELOC/ 前缀已剥
    assert idx.table["same.sty"] == ["bar", "zzz"]
    assert "readme.txt" not in idx.table  # 非 INDEX_EXTS
    assert "foo.dtx" not in idx.table


def test_index_save_load_roundtrip(tmp_path: Path) -> None:
    idx = TlpdbIndex({"a.sty": ["pkga"]})
    idx.save(tmp_path)
    assert TlpdbIndex.load(tmp_path).table == {"a.sty": ["pkga"]}


def test_query_stem_disambiguation_and_overrides() -> None:
    idx = TlpdbIndex(
        {"hyperxmp.sty": ["zzz", "hyperxmp"], "same.sty": ["zzz", "bar"]},
        overrides={"x.sty": "pkgx", "noise.sty": None},
    )
    assert idx.query("hyperxmp.sty")[0] == "hyperxmp"  # stem==包名 优先
    assert idx.query("same.sty") == ["bar", "zzz"]  # 无 stem 命中 → 字母序
    assert idx.query("x.sty") == ["pkgx"]
    assert idx.query("noise.sty") == []  # 显式 null = 已知噪声
    assert idx.query("absent.sty") == []


def test_suggest_prefix_candidates() -> None:
    idx = TlpdbIndex({"a.sty": ["hyperxmp"], "b.sty": ["hyperef", "zother"]})
    assert idx.suggest("hyper") == ["hyperef", "hyperxmp"]
    assert idx.suggest("nope") == []


# ---------------------------------------------------------------- fetch_package
def test_fetch_package_flat_overlay_filters(tmp_path: Path) -> None:
    body = make_tarxz(
        {
            "texmf-dist/tex/latex/foo/foo.sty": b"\\ProvidesPackage{foo}",
            "texmf-dist/tex/latex/foo/foo.def": b"d",
            "texmf-dist/doc/foo/readme.txt": b"doc",
            "texmf-dist/fonts/foo.pfb": b"PFB",  # 物理字体不投 (xdvipdfmx 死路)
        }
    )
    fetcher = lambda _url: body  # noqa: E731 - 一次性注入函数
    landed = fetch_package("foo", tmp_path, mirror=MIRROR, fetcher=fetcher)
    assert sorted(landed) == ["foo.def", "foo.sty"]  # 平铺 basename
    assert (tmp_path / "foo.sty").read_bytes().startswith(b"\\ProvidesPackage")
    assert not (tmp_path / "readme.txt").exists()
    assert not (tmp_path / "foo.pfb").exists()


def test_fetch_package_tree_overlay(tmp_path: Path) -> None:
    body = make_tarxz({"texmf-dist/tex/latex/foo/foo.sty": b"s"})
    fetch_package(
        "foo", tmp_path, mirror=MIRROR, overlay="tree", fetcher=lambda _u: body
    )
    assert (tmp_path / "tex/latex/foo/foo.sty").exists()


# ---------------------------------------------------------------- version_guard
def test_version_compat_epoch_gate(tmp_path: Path) -> None:
    new = tmp_path / "new.sty"
    new.write_text("\\NeedsTeXFormat{LaTeX2e}[2023/05/01]\n")
    old = tmp_path / "old.sty"
    old.write_text("\\NeedsTeXFormat{LaTeX2e}[2020/01/01]\n")
    expl = tmp_path / "expl.sty"
    expl.write_text("\\@ifpackagelater{expl3}{2024/02/01}{}{}\n")
    assert check_version_compat([new], "2022-07-14")[0] is False
    assert check_version_compat([old], "2022-07-14")[0] is True
    assert check_version_compat([expl], "2022-07-14")[0] is False
    assert check_version_compat([old], "2022-07-14") == (True, None)


# ---------------------------------------------------------------- ctan_fetch
def test_ctan_fetch_ext_gate(tmp_path: Path) -> None:
    res = ctan_fetch("x.pfb", tmp_path, TlpdbIndex({}), mirror=MIRROR)
    assert not res.ok
    assert "不在 TeX 输入层" in res.advisory


def test_ctan_fetch_unknown_file_advisory(tmp_path: Path) -> None:
    idx = TlpdbIndex({"hyperxmp.sty": ["hyperxmp"]})
    res = ctan_fetch("hyperref99.sty", tmp_path, idx, mirror=MIRROR)
    assert not res.ok
    assert "no TL package ships" in res.advisory


def test_ctan_fetch_success_flat(tmp_path: Path) -> None:
    idx = TlpdbIndex({"foo.sty": ["foo"]})
    body = make_tarxz({"texmf-dist/tex/latex/foo/foo.sty": b"sty"})

    def fetcher(url: str) -> bytes:
        assert url.endswith("/archive/foo.tar.xz")
        return body

    res = ctan_fetch("foo.sty", tmp_path, idx, mirror=MIRROR, fetcher=fetcher)
    assert res.ok
    assert res.pkg == "foo"
    assert (tmp_path / "foo.sty").exists()


def test_ctan_fetch_version_rollback(tmp_path: Path) -> None:
    idx = TlpdbIndex({"new.sty": ["newpkg"]})
    body = make_tarxz(
        {"texmf-dist/tex/latex/n/new.sty": (b"\\NeedsTeXFormat{LaTeX2e}[2025/01/01]\n")}
    )
    res = ctan_fetch(
        "new.sty",
        tmp_path,
        idx,
        mirror=MIRROR,
        epoch="2022-07-14",
        fetcher=lambda _u: body,
    )
    assert not res.ok
    assert not (tmp_path / "new.sty").exists()  # 过新版已撤回


def test_ctan_fetch_falls_to_next_candidate(tmp_path: Path) -> None:
    idx = TlpdbIndex({"w.sty": ["badpkg", "goodpkg"]})
    good = make_tarxz({"texmf-dist/tex/latex/g/w.sty": b"g"})

    def fetcher(url: str) -> bytes:
        if "badpkg" in url:
            msg = "404"
            raise OSError(msg)
        return good

    res = ctan_fetch("w.sty", tmp_path, idx, mirror=MIRROR, fetcher=fetcher)
    assert res.ok
    assert res.pkg == "goodpkg"


def test_ctan_fetch_landed_must_contain_target(tmp_path: Path) -> None:
    idx = TlpdbIndex({"want.sty": ["wrongpkg"]})
    body = make_tarxz({"texmf-dist/tex/latex/w/other.sty": b"o"})
    res = ctan_fetch("want.sty", tmp_path, idx, mirror=MIRROR, fetcher=lambda _u: body)
    assert not res.ok
    assert not (tmp_path / "other.sty").exists()  # 未命中目标 → 整包撤回


# ---------------------------------------------------------------- CtanFetcher 适配器
def test_ctan_fetcher_lazy_index(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    wdir = tmp_path / "proj"
    wdir.mkdir()
    tlpdb_xz = lzma.compress(TLPDB_TEXT.encode())
    pkg = make_tarxz({"texmf-dist/tex/latex/foo/foo.sty": b"sty"})
    calls = []

    def fetcher(url: str) -> bytes:
        calls.append(url)
        if url.endswith("texlive.tlpdb.xz"):
            return tlpdb_xz
        return pkg

    cf = CtanFetcher(wdir, cache_dir=cache, mirror=MIRROR, fetcher=fetcher)
    assert cf.peek_index() is None  # 构造零 IO
    dest = cf("foo.sty")
    assert dest == str(wdir / "foo.sty")
    assert (wdir / "foo.sty").exists()
    assert cf.peek_index() is not None
    n_tlpdb = sum(1 for u in calls if "tlpdb" in u)
    assert n_tlpdb == 1  # 索引只建一次
    cf("foo.sty")  # 二次调用不重建索引
    assert sum(1 for u in calls if "tlpdb" in u) == n_tlpdb


def test_ctan_fetcher_epoch_wired(tmp_path: Path) -> None:
    wdir = tmp_path / "proj"
    wdir.mkdir()
    pkg = make_tarxz(
        {"texmf-dist/tex/latex/f/foo.sty": b"\\NeedsTeXFormat{LaTeX2e}[2026/01/01]"}
    )
    idx = TlpdbIndex({"foo.sty": ["foo"]})
    cf = CtanFetcher(
        wdir, index=idx, epoch="2022-07-14", mirror=MIRROR, fetcher=lambda _u: pkg
    )
    assert cf("foo.sty") is None  # 版本过新 → 拒装
    assert not (wdir / "foo.sty").exists()
    assert "requires" in cf.last_note


def test_default_cache_dir_env_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEXLATE_CACHE > TEXLATE_DATA_DIR/cache > ~/.texlate/cache (wave-5c 归并)。"""
    monkeypatch.delenv("TEXLATE_CACHE", raising=False)
    monkeypatch.delenv("TEXLATE_DATA_DIR", raising=False)
    assert default_cache_dir() == Path.home() / ".texlate" / "cache"
    monkeypatch.setenv("TEXLATE_DATA_DIR", str(tmp_path / "droot"))
    assert default_cache_dir() == tmp_path / "droot" / "cache"
    monkeypatch.setenv("TEXLATE_CACHE", str(tmp_path / "explicit"))
    assert default_cache_dir() == tmp_path / "explicit"
