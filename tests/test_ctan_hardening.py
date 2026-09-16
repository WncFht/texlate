"""远端包/归档加固回归：ctan tree overlay 穿越 + 容量上限 + unpack dir casefold。

ctan 侧全部离线——fetcher 注入内存构造的 tar.xz；audit-2026-09-16
codehealth H3（overlay="tree" 只挡 ``../`` 前缀、解压无上限）与
「tar dir 成员不做 casefold 碰撞检查」两条发现的回归面。
"""

import io
import lzma
import tarfile
from pathlib import Path

import pytest

from texlate.arxiv.unpack import unpack_tar
from texlate.compile.fixloop.ctan import (
    CtanFetchError,
    FetchCaps,
    TlpdbIndex,
    ctan_fetch,
    fetch_package,
    fetch_tlpdb,
)

MIRROR = "https://m.test/tlnet"


def make_tarxz(
    members: dict[str, bytes] | list[tuple[tarfile.TarInfo, bytes]],
) -> bytes:
    """内存构造 ``archive/<pkg>.tar.xz`` 响应体（dict 形为常规成员）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        if isinstance(members, dict):
            members = [(_tar_reg(n, len(d)), d) for n, d in members.items()]
        for info, data in members:
            tf.addfile(info, io.BytesIO(data))
    return lzma.compress(buf.getvalue())


def _tar_reg(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    return info


def make_tar(members: list[tuple[tarfile.TarInfo, bytes]]) -> bytes:
    """裸 tar（unpack_tar 直吃解压后字节）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _tar_dir(name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.size = 0
    return info


# ---------------------------------------------------------------- 成员名穿越（tree 档主战场，flat 档同口径拒收）
@pytest.mark.parametrize(
    "evil",
    [
        "texmf-dist/tex/../../evil.sty",  # 中段 .. —— 旧实现只挡前缀 ../ 漏过
        "../evil.sty",
        "/abs/evil.sty",
        "C:/win/evil.sty",  # 盘符
        "tex\\win/evil.sty",  # 反斜杠（Windows 语义分隔符）
        "texmf-dist/tex/./../x.sty",
    ],
)
def test_tree_overlay_rejects_traversal(tmp_path: Path, evil: str) -> None:
    body = make_tarxz({evil: b"x", "texmf-dist/tex/ok.sty": b"ok"})
    with pytest.raises(CtanFetchError, match="unsafe member name"):
        fetch_package(
            "p", tmp_path, mirror=MIRROR, overlay="tree", fetcher=lambda _u: body
        )
    assert not (tmp_path / "ok.sty").exists()  # 整包拒收：无部分落盘


def test_flat_overlay_also_rejects_traversal(tmp_path: Path) -> None:
    body = make_tarxz({"a/../../evil.sty": b"x"})
    with pytest.raises(CtanFetchError, match="unsafe member name"):
        fetch_package("p", tmp_path, mirror=MIRROR, fetcher=lambda _u: body)


def test_tree_overlay_legit_members_land(tmp_path: Path) -> None:
    body = make_tarxz(
        {
            "texmf-dist/tex/latex/foo/foo.sty": b"s",
            "texmf-dist/fonts/tfm/foo.tfm": b"t",  # texmf-dist/ 前缀同剥
            "./texmf-dist/tex/latex/foo/dot.sty": b".",  # ./ 段规范化
        }
    )
    landed = fetch_package(
        "foo", tmp_path, mirror=MIRROR, overlay="tree", fetcher=lambda _u: body
    )
    assert (tmp_path / "tex/latex/foo/foo.sty").exists()
    assert sorted(landed) == [
        "fonts/tfm/foo.tfm",
        "tex/latex/foo/dot.sty",
        "tex/latex/foo/foo.sty",
    ]


# ---------------------------------------------------------------- 容量上限
def test_member_size_cap(tmp_path: Path) -> None:
    body = make_tarxz({"texmf-dist/tex/big.sty": b"0123456789"})
    caps = FetchCaps(max_member_bytes=4)
    with pytest.raises(CtanFetchError, match="member too large"):
        fetch_package("p", tmp_path, mirror=MIRROR, fetcher=lambda _u: body, caps=caps)


def test_total_size_cap(tmp_path: Path) -> None:
    body = make_tarxz(
        {"texmf-dist/tex/a.sty": b"aaaaaa", "texmf-dist/tex/b.sty": b"bbbbbb"}
    )
    caps = FetchCaps(max_total_bytes=8)
    with pytest.raises(CtanFetchError, match="extract total exceeds"):
        fetch_package("p", tmp_path, mirror=MIRROR, fetcher=lambda _u: body, caps=caps)
    assert not (tmp_path / "a.sty").exists()


def test_member_count_cap(tmp_path: Path) -> None:
    body = make_tarxz({"texmf-dist/tex/a.sty": b"a", "texmf-dist/tex/b.sty": b"b"})
    caps = FetchCaps(max_members=1)
    with pytest.raises(CtanFetchError, match="too_many_members"):
        fetch_package("p", tmp_path, mirror=MIRROR, fetcher=lambda _u: body, caps=caps)


def test_xz_bomb_rejected(tmp_path: Path) -> None:
    bomb = lzma.compress(b"0" * 100_000)
    caps = FetchCaps(max_inflated=1024)
    with pytest.raises(CtanFetchError, match="inflated exceeds"):
        fetch_package("p", tmp_path, mirror=MIRROR, fetcher=lambda _u: bomb, caps=caps)


def test_truncated_xz_rejected(tmp_path: Path) -> None:
    good = lzma.compress(b"payload")
    caps = FetchCaps()
    with pytest.raises(CtanFetchError, match="truncated xz"):
        fetch_package(
            "p",
            tmp_path,
            mirror=MIRROR,
            fetcher=lambda _u: good[: len(good) // 2],
            caps=caps,
        )


def test_download_cap_on_injected_fetcher(tmp_path: Path) -> None:
    caps = FetchCaps(max_download=16)
    with pytest.raises(CtanFetchError, match="download exceeds"):
        fetch_package(
            "p",
            tmp_path,
            mirror=MIRROR,
            fetcher=lambda _u: b"x" * 32,
            caps=caps,
        )


def test_not_a_tar_rejected(tmp_path: Path) -> None:
    body = lzma.compress(b"this is not a tar")
    with pytest.raises(CtanFetchError, match="not a tar stream"):
        fetch_package("p", tmp_path, mirror=MIRROR, fetcher=lambda _u: body)


def test_tlpdb_caps_applied(tmp_path: Path) -> None:
    caps = FetchCaps(max_download=8)
    with pytest.raises(CtanFetchError, match="download exceeds"):
        fetch_tlpdb(
            MIRROR, tmp_path, fetcher=lambda _u: lzma.compress(b"x" * 64), caps=caps
        )


def test_ctan_fetch_hostile_pkg_falls_through(tmp_path: Path) -> None:
    idx = TlpdbIndex({"w.sty": ["evil", "good"]})
    good = make_tarxz({"texmf-dist/tex/g/w.sty": b"g"})

    def fetcher(url: str) -> bytes:
        if "evil" in url:
            return make_tarxz({"texmf-dist/../../escape.sty": b"e"})
        return good

    res = ctan_fetch("w.sty", tmp_path, idx, mirror=MIRROR, fetcher=fetcher)
    assert res.ok
    assert res.pkg == "good"
    assert not (tmp_path / "escape.sty").exists()


# ---------------------------------------------------------------- arXiv unpack tar：dir casefold 缺口回归
def test_unpack_dir_casefold_collision_warns(tmp_path: Path) -> None:
    payload = make_tar(
        [
            (_tar_dir("Foo/"), b""),
            (_tar_dir("foo/"), b""),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert any(w.startswith("casefold_dir:Foo~foo") for w in res.warnings)
    dirs = [m.path for m in res.members if m.kind == "dir"]
    assert dirs == ["Foo"]  # 冲突目录不进 mtree


def test_unpack_dir_then_lower_file_renames(tmp_path: Path) -> None:
    """dir ``Foo/`` 后到的 file ``foo``：不覆盖既有目录，走 casefold 改名。"""
    payload = make_tar(
        [
            (_tar_dir("Foo/"), b""),
            (_tar_reg("foo", 3), b"abc"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "Foo").is_dir()
    assert (tmp_path / "foo~c2").is_file()
    assert any(w.startswith("casefold_rename:foo->foo~c2") for w in res.warnings)


def test_unpack_file_member_hitting_dir_skips(tmp_path: Path) -> None:
    """同名 dir+file 成员并存：file 落点是目录 → reject_dir_clash 而非崩溃。"""
    payload = make_tar(
        [
            (_tar_dir("d/"), b""),
            (_tar_reg("d", 3), b"abc"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert (tmp_path / "d").is_dir()
    assert any(w.startswith("reject_dir_clash:d") for w in res.warnings)


def test_unpack_dup_dir_member_idempotent(tmp_path: Path) -> None:
    payload = make_tar([(_tar_dir("a/"), b""), (_tar_dir("a/"), b"")])
    res = unpack_tar(payload, tmp_path)
    assert [m.path for m in res.members] == ["a"]  # 重复目录成员不重复记
    assert res.warnings == []
