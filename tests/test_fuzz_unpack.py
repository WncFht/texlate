"""unpack.py 对抗 tar fuzz——程序化成员流 + 字节级变异 + 截断扫描。

核心不变量（``unpack_tar`` 正常返回时）：``members``(mtree) 与盘上实况一致——

- 成员路径唯一（last-wins 去重，不留重复条目）；
- 每个成员的真实落点 resolve 后仍在 dest 内（零逃逸）；
- 同一真实落点被多条成员路径别名共享时（经 kept symlink 祖先写入），
  后到写穿先到，先到条目的内容字段由 ``_reconcile_aliases`` 改记为
  赢家实况——本套断言逐成员全验 kind/sha 与盘上相符；
- dir/symlink 条目 kind 与盘上类型一致、link_target 原样；
- 盘上无 phantom：每个真实文件/链接都是某成员的真实落点，每个真实
  目录是成员目录或某成员落点的祖先（隐式父级）；
- 告警全部 UTF-8 可编码且前缀在已知告警集内；
- 只抛 ``UnpackError``——成员级 IO 病态已降级 ``reject_io``。
"""

from __future__ import annotations

import hashlib
import io
import random
import tarfile
from typing import TYPE_CHECKING

import pytest
from conftest import make_tar, tar_dir, tar_reg

from texlate.arxiv.unpack import (
    STUB_PREFIX,
    MemberEntry,
    UnpackError,
    UnpackResult,
    unpack_single,
    unpack_tar,
    write_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path

#: 已知告警前缀全集——出现表外前缀即未登记的新路径，需人工定性。
_KNOWN_WARNS = frozenset(
    {
        "reject_path",
        "reject_setuid",
        "reject_special",
        "reject_link",
        "reject_filesize",
        "reject_totalcap",
        "reject_io",
        "reject_dir_clash",
        "casefold_rename",
        "casefold_dir",
        "dup_member_overwrite",
        "stub_member",
        "link_kept",
        "hardlink_dangling",
        "hardlink_materialized",
    }
)

_NAME_MAX = 255
_STUB_P = 0.08
_REPAIR_P = 0.5


def _sym(name: str, linkname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = linkname
    return info


def _lnk(name: str, linkname: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE
    info.linkname = linkname
    return info


def _real_loc(dest: Path, rel: str) -> Path:
    """成员 rel 的真实落点：父级 resolve（可穿 kept symlink 祖先）+ 末段名。"""
    p = dest / rel
    return p.parent.resolve() / p.name


def _walk(dest: Path) -> tuple[set[Path], set[Path], dict[Path, str], list[Path]]:
    """不随 symlink 下钻地扫真实树 → ``(files, dirs, links, others)``（绝对路径键）。"""
    files: set[Path] = set()
    dirs: set[Path] = set()
    links: dict[Path, str] = {}
    others: list[Path] = []
    stack = [dest]
    while stack:
        d = stack.pop()
        for p in d.iterdir():
            if p.is_symlink():
                links[p] = str(p.readlink())
            elif p.is_dir():
                dirs.add(p)
                stack.append(p)
            elif p.is_file():
                files.add(p)
            else:
                others.append(p)
    return files, dirs, links, others


def _check_views(res: UnpackResult) -> None:
    """派生视图 + 告警自洽（不触盘）：files/stub/tex_files、告警编码与前缀白名单。"""
    members = res.members
    paths = [m.path for m in members]
    assert len(set(paths)) == len(paths), f"dup member paths: {paths}"
    files_prop = sorted(m.path for m in members if m.kind in ("file", "hardlink"))
    assert res.files == files_prop
    assert res.n_files == len(files_prop)
    assert res.tex_files == sum(
        1 for f in files_prop if f.lower().endswith((".tex", ".ltx", ".latex"))
    )
    assert res.stub_files == sorted(m.path for m in members if m.stub)
    for w in res.warnings:
        w.encode("utf-8")  # meta.json 可编码性
        kind, sep, _ = w.partition(":")
        assert sep, f"warning missing prefix: {w!r}"
        assert kind in _KNOWN_WARNS, f"unknown warning: {w!r}"


def _check_manifest(res: UnpackResult, meta_dir: Path) -> None:
    """write_manifest 对账：files.txt == res.files，mtree 逐字段重构全等。"""
    write_manifest(res, meta_dir)
    files_txt = (meta_dir / "files.txt").read_text(encoding="utf-8").splitlines()
    assert files_txt == res.files
    mtree = (meta_dir / "mtree.txt").read_text(encoding="utf-8").splitlines()
    expected: list[str] = []
    for m in sorted(res.members, key=lambda m: m.path):
        line = f"{m.path}\t{m.size}\t{m.sha256}\t{m.kind}"
        if m.link_target:
            line += f"\t-> {m.link_target}"
        if m.stub:
            line += "\tstub"
        expected.append(line)
    assert mtree == expected


def _check_winner(m: MemberEntry, loc: Path, dest_res: Path) -> None:
    """某落点的最末成员：kind/sha/link_target 必须与盘上实况相符。"""
    if m.kind in ("file", "hardlink"):
        assert loc.is_file(), m.path
        assert not loc.is_symlink(), m.path
        data = loc.read_bytes()
        assert len(data) == m.size, f"size lie: {m.path}"
        assert hashlib.sha256(data).hexdigest() == m.sha256, f"sha lie: {m.path}"
        if m.kind == "hardlink":
            src = dest_res / str(m.link_target)
            assert src.resolve().is_relative_to(dest_res)
    elif m.kind == "dir":
        assert loc.is_dir(), m.path
        assert not loc.is_symlink(), m.path
    elif m.kind == "symlink":
        assert loc.is_symlink(), m.path
        assert str(loc.readlink()) == m.link_target
        try:
            resolved = loc.resolve()
        except RuntimeError:
            return  # 自环/链环链接：任何解引用都失败，天然不可逃逸
        assert resolved.is_relative_to(dest_res), m.path
    else:  # pragma: no cover -- 当前实现只产出四类
        pytest.fail(f"unknown member kind {m.kind}")


def _check_disk(res: UnpackResult, dest: Path) -> None:
    """逐成员盘上实况断言 + 无 phantom 反查。"""
    dest_res = dest.resolve()
    members = res.members
    if not dest_res.exists():
        # 全拒/全跳过的包不落盘（lazy mkdir）——此时 members 必须为空
        assert members == [], f"dest absent but members reported: {members}"
        return
    # 真实落点（resolve 父级，可穿 kept symlink）→ 落点别名识别：
    # 同 loc 的最末成员是赢家；先到条目已被对账改记为赢家实况，逐成员全验
    locs = [_real_loc(dest_res, m.path) for m in members]
    winner = {loc: i for i, loc in enumerate(locs)}  # 后者覆盖——最末写序
    for m, loc in zip(members, locs, strict=True):
        assert loc.is_relative_to(dest_res), f"escape member: {m.path}"
        _check_winner(m, loc, dest_res)
    files, dirs, links, others = _walk(dest_res)
    assert others == []
    # 盘上实体与"赢家"（各落点最末成员）对账
    win = [
        (loc, m)
        for m, loc in zip(members, locs, strict=True)
        if loc == locs[winner[loc]]
    ]
    # 别名条目的 size 与赢家同记一份——字节总量只按各落点赢家对账
    assert res.extracted_bytes >= sum(
        m.size for _, m in win if m.kind in ("file", "hardlink")
    )
    member_file_locs = {loc for loc, m in win if m.kind in ("file", "hardlink")}
    member_dir_locs = {loc for loc, m in win if m.kind == "dir"}
    member_link_locs = {loc for loc, m in win if m.kind == "symlink"}
    link_targets = {loc: m.link_target for loc, m in win if m.kind == "symlink"}
    # 无 phantom：盘上每件实体都对应成员落点（或成员的隐式祖先目录）
    assert files == member_file_locs
    assert set(links) == member_link_locs
    for lp, target in links.items():
        assert target == link_targets[lp]
    all_locs = member_file_locs | member_link_locs | member_dir_locs
    for d in dirs:
        if d in member_dir_locs:
            continue
        assert any(d in loc.parents for loc in all_locs), f"phantom dir {d}"


def _check_result(res: UnpackResult, dest: Path) -> None:
    """全套一致性：成员视图 + manifest 对账 + 盘上实况。"""
    _check_views(res)
    _check_manifest(res, dest.parent / f"{dest.name}.meta")
    _check_disk(res, dest)


# ---------------------------------------------------------------- 随机成员流

_PATHS = [
    "a",
    "b.tex",
    "c.sty",
    "d",
    "d/x.tex",
    "d/f.tex",  # 与 "e"→"d" symlink 组合可构造别名落点
    "d/deep/y.tex",
    "e",
    "e/f.tex",
    "A.tex",
    "B",
    "Figs",
    "Figs/g.eps",
    "sub",
    "sub/h.tex",
    "z",
    "Z",
    "d/../b.tex",  # reject_path
    "/abs.tex",  # reject_path
    "C:/w.tex",  # reject_path
    "bad\tx.tex",  # reject_path（控制字符）
    "caf\udce9.tex",  # reject_path（代理区——tarfile 写入侧 surrogateescape 还原 raw 字节）
    ".",  # 归一为空静默跳过
    "./dot.tex",
]

_LINKNAMES = [
    "b.tex",
    "d/x.tex",
    "e",
    "d",  # 目录别名源（e→d 让 e/f.tex 与 d/f.tex 同落点）
    "ghost.tex",  # dangling
    "../esc",  # 逃逸
    "a/../../esc",  # 归一后逃逸
    "/etc/passwd",  # 绝对
    "C:/w",  # 盘符
    "tgt\ttex",  # 控制字符
    "x/../b.tex",  # 折回树内（文本层合法）
    "",
]


def _gen_member(rng: random.Random) -> tuple[tarfile.TarInfo, bytes]:
    kind = rng.choices(
        ["file", "dir", "sym", "lnk", "fifo", "setuid"],
        weights=[52, 12, 14, 10, 3, 9],
    )[0]
    name = rng.choice(_PATHS)
    if kind == "dir":
        return tar_dir(name), b""
    if kind == "sym":
        return _sym(name, rng.choice(_LINKNAMES)), b""
    if kind == "lnk":
        return _lnk(name, rng.choice(_LINKNAMES)), b""
    if kind == "fifo":
        info = tarfile.TarInfo(name)
        info.type = tarfile.FIFOTYPE
        return info, b""
    if kind == "setuid":
        return tar_reg(name, 4, mode=0o4755), b"suid"
    data = rng.randbytes(rng.randint(0, 1500))
    if rng.random() < _STUB_P:
        data = STUB_PREFIX + data
    return tar_reg(name, len(data)), data


def test_fuzz_random_member_streams(tmp_path: Path) -> None:
    """随机成员序列：解包成功则 mtree↔盘上实况全一致，否则必 UnpackError。"""
    rng = random.Random(20260917)  # noqa: S311 -- 确定性种子
    for i in range(500):
        members = [_gen_member(rng) for _ in range(rng.randint(1, 22))]
        payload = make_tar(members)
        dest = tmp_path / f"d{i}"
        res = unpack_tar(payload, dest)
        _check_result(res, dest)


# ---------------------------------------------------------------- 字节级变异


def _mutate(payload: bytes, rng: random.Random, *, repair: bool) -> bytes:
    """随机写字节；``repair`` 重算每个非零 512 块的 checksum——字段变异真实生效。"""
    data = bytearray(payload)
    for _ in range(rng.randint(1, 6)):
        data[rng.randrange(len(data))] = rng.randrange(256)
    if repair:
        for base in range(0, len(data) - 511, 512):
            if not any(data[base : base + 512]):
                continue
            data[base + 148 : base + 156] = b"        "
            chk = sum(data[base : base + 512])
            data[base + 148 : base + 156] = f"{chk:06o}\x00 ".encode()
    return bytes(data)


_BASE_MEMBERS: list[tuple[tarfile.TarInfo, bytes]] = [
    (tar_dir("sub"), b""),
    (tar_reg("sub/a.tex", 120), b"x" * 120),
    (tar_reg("b.sty", 300), b"y" * 300),
    (_sym("sub/l.tex", "a.tex"), b""),
    (_lnk("h.tex", "b.sty"), b""),
]


def test_fuzz_byte_mutations_never_lie(tmp_path: Path) -> None:
    """脏字节变异（含 checksum 修复让字段生效）：UnpackError 或盘上实况一致。"""
    rng = random.Random(20260918)  # noqa: S311 -- 确定性种子
    payload = make_tar(_BASE_MEMBERS)
    for i in range(600):
        mutated = _mutate(payload, rng, repair=rng.random() < _REPAIR_P)
        dest = tmp_path / f"m{i}"
        try:
            res = unpack_tar(mutated, dest)
        except UnpackError:
            continue
        _check_result(res, dest)


def test_fuzz_garbage_payloads(tmp_path: Path) -> None:
    """纯随机/截断/空载荷：只许 UnpackError（非 tar 流）。"""
    rng = random.Random(20260919)  # noqa: S311 -- 确定性种子
    payload = make_tar(_BASE_MEMBERS)
    for i in range(200):
        blob = rng.randbytes(rng.randint(0, 3000))
        if rng.random() < _REPAIR_P:
            blob = payload[: rng.randrange(len(payload))]
        try:
            res = unpack_tar(blob, tmp_path / f"g{i}")
        except UnpackError:
            continue
        _check_result(res, tmp_path / f"g{i}")


def test_truncation_sweep(tmp_path: Path) -> None:
    """逐段截断：mid-header/mid-data/边界切点全覆盖——UnpackError 或前缀一致。"""
    payload = make_tar(_BASE_MEMBERS)
    cuts = set(range(0, len(payload), 53)) | {
        n * 512 + d for n in range(6) for d in (0, 1, 148, 156, 511)
    }
    for i, cut in enumerate(sorted(c for c in cuts if c <= len(payload))):
        dest = tmp_path / f"t{i}"
        try:
            res = unpack_tar(payload[:cut], dest)
        except UnpackError:
            continue
        _check_result(res, dest)


# ---------------------------------------------------------------- 定向对抗

_TYPE_MAKERS = {
    "file": lambda n: (tar_reg(n, 4), b"DATA"),
    "dir": lambda n: (tar_dir(n), b""),
    "sym": lambda n: (_sym(n, "tgt.tex"), b""),
    "lnk": lambda n: (_lnk(n, "tgt.tex"), b""),
}


@pytest.mark.parametrize("first", list(_TYPE_MAKERS))
@pytest.mark.parametrize("second", list(_TYPE_MAKERS))
def test_dup_member_cross_type_last_wins(
    tmp_path: Path, first: str, second: str
) -> None:
    """同路径异类型重复成员全矩阵：后到者语义 + mtree 与盘上一致。"""
    tgt = tar_reg("tgt.tex", 5)
    members = [(tgt, b"TTTTT"), _TYPE_MAKERS[first]("x"), _TYPE_MAKERS[second]("x")]
    res = unpack_tar(make_tar(members), tmp_path / "d")
    _check_result(res, tmp_path / "d")
    xs = [m for m in res.members if m.path == "x"]
    assert len(xs) <= 1  # 留下至多一条，且不留幽灵


def test_alias_via_symlinked_dir_lies_in_mtime(tmp_path: Path) -> None:
    """别名落点对账回归钉：``d``→``e`` symlink 后，``d/x`` 与 ``e/x`` 别名
    同实文件——后到写穿先到，``_reconcile_aliases`` 把先到条目的 sha 改记
    为盘上实况（赢家 B），并记 ``dup_member_overwrite``。"""
    payload = make_tar(
        [
            (tar_dir("e"), b""),
            (_sym("d", "e"), b""),
            (tar_reg("d/x.tex", 1), b"A"),
            (tar_reg("e/x.tex", 1), b"B"),
        ]
    )
    dest = tmp_path / "d"
    res = unpack_tar(payload, dest)
    entry = next(m for m in res.members if m.path == "d/x.tex")
    actual = hashlib.sha256((dest / "e" / "x.tex").read_bytes()).hexdigest()
    assert entry.sha256 == actual
    assert "dup_member_overwrite:d/x.tex" in res.warnings


def test_hardlink_chain_order_dependent(tmp_path: Path) -> None:
    """hardlink 链按声明序单遍物化：``h2→h1`` 先于 ``h1→f`` 声明时 h2 dangling。

    现规格语义位（"目标已在树上才物化"）——不是 defect，钉住以显化
    与 GNU tar 全序解析的差异。
    """
    h1 = _lnk("h1.tex", "f.tex")
    h2 = _lnk("h2.tex", "h1.tex")
    f = tar_reg("f.tex", 4)
    res_fwd = unpack_tar(make_tar([(h1, b""), (h2, b""), (f, b"DATA")]), tmp_path / "a")
    assert set(res_fwd.files) == {"f.tex", "h1.tex", "h2.tex"}
    res_rev = unpack_tar(make_tar([(h2, b""), (h1, b""), (f, b"DATA")]), tmp_path / "b")
    assert set(res_rev.files) == {"f.tex", "h1.tex"}
    assert "hardlink_dangling:h2.tex->h1.tex" in res_rev.warnings


def test_name_max_boundary(tmp_path: Path) -> None:
    """NAME_MAX=255 边界：恰 255B 落盘，单段 256B → ``reject_io``(ENAMETOOLONG)。"""
    ok_name = "d/" + "x" * (_NAME_MAX - 4) + ".tex"
    ok_leaf = ok_name.split("/", 1)[1]
    assert len(ok_leaf.encode()) == _NAME_MAX
    bad_name = "d/" + "y" * (_NAME_MAX + 1)  # 单段 256B
    payload = make_tar(
        [
            (tar_dir("d"), b""),
            (tar_reg(ok_name, 3), b"xxx"),
            (tar_reg(bad_name, 3), b"yyy"),
        ]
    )
    res = unpack_tar(payload, tmp_path)
    assert ok_name in res.files
    assert bad_name not in res.files
    assert any(w.startswith("reject_io:") for w in res.warnings)


def test_pax_longname_bad_utf8_rejected(tmp_path: Path) -> None:
    """PAX ``path=`` 值非法 UTF-8：tarfile surrogateescape 出代理区 → ``reject_path``。"""
    buf = io.BytesIO()
    long_name = "d/" + "x" * 150 + ".tex"
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        tf.addfile(tar_reg(long_name, 3), io.BytesIO(b"xxx"))
        tf.addfile(tar_reg("ok.tex", 3), io.BytesIO(b"yyy"))
    raw = bytearray(buf.getvalue())
    idx = raw.find(b"path=" + long_name.encode()[:20])
    assert idx != -1, "pax path record not found"
    # path= 值段内原地改写 4 字节为非法 UTF-8（data 区不吃 header checksum）
    raw[idx + 10 : idx + 14] = b"\xff\xfe\xff\xfe"
    res = unpack_tar(bytes(raw), tmp_path)
    assert res.files == ["ok.tex"]
    assert any(w.startswith("reject_path:") for w in res.warnings)


def test_max_members_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("texlate.arxiv.unpack.MAX_MEMBERS", 3)
    payload = make_tar([(tar_reg(f"f{i}.tex", 3), b"xxx") for i in range(4)])
    with pytest.raises(UnpackError, match="too_many_members"):
        unpack_tar(payload, tmp_path)


def test_unpack_single_stem_sanitized(tmp_path: Path) -> None:
    """stem_hint 路径注入面：``../``/绝对路径只剩末段文件名。"""
    body = b"\\documentclass{article}\n" + b"z" * 300
    res = unpack_single(body, tmp_path, stem_hint="../../../etc/passwd.gz")
    assert res.files == ["passwd.tex"]
    assert (tmp_path / "passwd.tex").read_bytes() == body
