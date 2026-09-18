"""glossary 层 + 路径牢笼 fuzz——五层合并 oracle 对账 + confine 不变量。

不变量清单：

- ``resolve_glossary_path`` 牢笼：绝对路径与 ``..`` 组件预检即拒；
  返回路径 resolve 后必须落在允许根（``base_dir`` 先、``glossary_dir``
  兜底）之内且是常规文件；symlink 逃逸（文件/目录链、悬挂、自环）同挡；
  根内 ``is_file`` 逐根判定——base 侧目录命中不遮蔽 glossary_dir 同名文件。
  随机敌意名字（含 unicode/空白/换行/surrogateescape/``~``/反斜杠/
  伪 ``..`` 形态）永不逃逸、永不在界内输入上抛。
- ``Glossary.load`` 五层序 user > local > category（声明序 → 文件序，
  先写者胜）> default > placeholder——随机分层构造对独立 oracle 逐
  ``(zh, source)`` 对账；占位符绝不覆盖真术语。
- ``flatten_terms``：三形态归一 + 非 mapping/顶层 list 值只抛
  ``TypeError``；``load_csv`` 对界内文本恒回 ``dict[str, str]``（键非空）
  且逐字节确定；``load_index`` 缺/空 → ``{}``、结构脏 → ``TypeError``。
- ``doc_filter``：真术语命中面 == 独立 oracle（ASCII fold 子串扫描 +
  ASCII ``\\w`` 词边界）；输出序 = 真术语按 ``en.lower()`` 稳定序 +
  占位符按 ``sort_key`` 排尾；同输入逐字节确定。

缺陷台账（``tmp/glossary-fuzz/`` 实证，2026-09-17，xfail-strict 钉——
修复后 XPASS 即拆钉信号）：

- CONFIRMED D1：``gpath``/``glossary_dir`` 含 ``\\x00`` → ``resolve()``
  内 ``lstat`` 抛 ``ValueError`` 逃逸（只兜住了 ``..``/绝对形态，没兜
  FS 层异常）。请求面 ``options.glossary="a\\x00b"`` 无校验直达：
  ``_make_glossary`` 的 broad except 兜住 → 术语表静默丢；但
  ``_make_cache``（``translate.py``）与 ``_share_glossary_hash``
  （``share.py``）无兜网 → translating 段 fault / share pack 崩。
- CONFIRMED D2：组件 >255B → ``OSError`` ENAMETOOLONG 同面逃逸
  （255B 界内优雅返 None——realpath lstat 不吞 ENAMETOOLONG）。
- CONFIRMED D3：``flatten_terms`` 空值污染——yaml ``en:``/``~``/``null``/
  ``{target: null}`` → zh 变字面 ``"None"`` 注进 prompt（``str(v) or en``
  的 ``v=None`` 洞）。同族观察钉：``false``→``"False"``、``0``→``"0"``、
  ``{target: [x]}``→``"['x']"``（嵌套 list 不拒，与顶层 list 拒载不对称）。
- CONFIRMED D4（潜伏）：``load_index`` 条目逃逸 ``terms_dir``——
  ``cat: ../x.yaml`` 与绝对路径皆可经 ``terms_dir / fname`` 裸拼接读外部
  文件（`/` 运算遇绝对右操作数丢弃左侧）。当前输入是包内受信
  ``index.yaml``；``load(terms_dir=...)`` 是公开 kwarg——根/索引一旦
  用户可写即任意文件读（术语进 prompt 是外泄通道，审计 M2 同口径）。
- CONFIRMED D5：``load_csv`` 单字段 >131072B → ``csv.Error`` 整表崩
  （csv 默认 field_size_limit，docstring 未记此错型）。
- CONFIRMED D6：``#`` 起头术语连 RFC 引号也保不住——注释判定跑在
  解引号后的字段上，``"#tag",zh`` 与 ``#tag,zh`` 同被静默丢。
- CONFIRMED D7：``sort_key`` 非全序——``[[A_1]]``/``[[A_01]]``、``A``/
  ``[[A]]`` 等碰撞对的 tie 落 ``set`` 迭代序 = 哈希序 → ``Glossary.load``/
  ``doc_filter``/``collect_doc_placeholders`` 三处注入序随
  ``PYTHONHASHSEED`` 跨进程漂移（实证：seed 0/1/2 产出三种序），
  违背 docstring「逐字节稳定是前缀缓存命中前提」。
- CONFIRMED D8：目录型层文件/类目条目——``exists()`` 对目录放行后
  ``load_table`` 按后缀抛 ``ValueError`` 或 ``open()`` 抛
  ``IsADirectoryError`` 出 ``load``，而非按无文件跳过。
- CONFIRMED D9：根内 symlink **环**（自环/互环）→ ``resolve()`` ELOOP →
  ``RuntimeError`` 逃逸（``pathlib.check_eloop`` 非 OSError 系，与 D1/D2
  同面不同型）。可达性更甚：arXiv e-print tar 可带 ``a→a`` 自环项，
  落 ``base/`` 后请求面 ``glossary="a"`` 即点爆。

观察钉（pin observed，定性留给裁决）：

- ``load_csv`` 同文件重复 en 后写胜（dict 赋值）而跨层先写胜
  （``setdefault``）——非对称但确定；yaml 重复键 PyYAML 同静默后写胜。
- ``load_table`` 扩展名大小写敏感（``X.CSV`` → ``ValueError``）。
- ``gpath="."``/``""`` 遇**文件型**根返回根本身（生产不可达：settings
  校验 ``glossary_dir`` 必须是目录、``base_dir`` 恒为目录）。
- ``~`` 在 ``gpath`` 侧不展开（字面名受困）；``glossary_dir`` 相对形态
  resolve 到进程 CWD（生产不可达——settings 强制绝对+现存目录）。
- ``doc_filter`` 多行术语（csv 引号字段/yaml 键内嵌 ``\\n``）可命中
  ``\\n``-join 接缝——无单 chunk 含它却被注入（phantom 注入位浪费）。
- 用户术语 en 与占位符同形（``[[MATH_1]]``）时占位符恒等注入被
  ``setdefault`` 挡死——用户层优先是规格，但形同占位符的术语会诱导
  模型「翻译」占位符（PLAUSIBLE 设计张力，非纯实现缺陷）。
- ``Glossary.load`` 对显式路径**不做 confine**——confine 边界在 worker
  侧，load 是纯装载器（by design，钉住防误读）。
- ``Path.exists()`` 对 NUL 路径吞 ``ValueError`` 返 False——``load``
  侧 NUL 优雅，D1 崩溃只在 ``resolve()`` 侧（不对称佐证）。
"""

from __future__ import annotations

import os
import re
import string
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from _fuzzkit import fuzz_rng

from texlate.repair import resolve_glossary_path  # 私有函数即被测对象
from texlate.xlat.glossary import (
    Glossary,
    TermEntry,
    flatten_terms,
    load_csv,
    load_index,
    load_table,
    load_yaml,
)
from texlate.xlat.placeholders import sort_key

if TYPE_CHECKING:
    import random

# ---------------------------------------------------------------- 常量与 soup

_FUZZ_ITERS = 800
_FUZZ_ITERS_MED = 300
_SEED_JAIL = 2026091701
_SEED_LOAD = 2026091702
_SEED_CSV = 2026091703
_SEED_FLAT = 2026091704
_SEED_FILTER = 2026091705
_NAME_MAX = 255
_CSV_FIELD_MAX = 131072
_MODE = "utf-8"

#: ASCII 词字符集——``doc_filter`` 的 ``\\w`` 在 ASCII 旗下口径
_ASCII_WORD = frozenset(string.ascii_letters + string.digits + "_")

#: 敌意路径组件汤——全部 ≤250B 且无 NUL（崩溃族由 xfail 钉单独覆盖，
#: 本汤只含「理应优雅返回」的输入；混入 surrogateescape 原始字节名）
_COMP_SOUP = [
    "a",
    "sub",
    "x.yaml",
    "g.yaml",
    "t.yaml",
    "g.csv",
    ".",
    "..",
    "~",
    " ",
    "  ",
    "...",
    "..x",
    "x..",
    "x.y",
    "a b",
    "a\nb",
    "a\tb",
    "\\",
    "a\\b",
    "a\\..\\b",
    "..\\..",
    "C:\\win",
    "C:",
    "*",
    "?",
    "!",
    "|",
    ";",
    "$(id)",
    "`id`",
    "%s",
    "{x}",
    "a:b",
    "日本語",
    "é",
    "ñ",
    "a\udcffb",
    "\udcff",
    ".hidden",
    "x" * 250,
    "y" * 120,
    "lk_f_out",
    "lk_d_out",
    "lk_in",
    "lk_dangle",
    "lk_f_out/x",
    "lk_d_out/sec.yaml",
    "lk_in/x",
    "sub/../t.yaml",
    "sub/./deep.yaml",
    # lk_loop（symlink 环）不入汤——resolve() ELOOP→RuntimeError 是 D9
    # 缺陷钉的专属面，strict fuzz 只含理应优雅的输入
]

#: csv 字段汤（不含 \\n——字段内换行须引号，接缝幻影另有专钉）
_CSV_FIELD_SOUP = [
    "a",
    "b",
    "en1",
    "zh1",
    "0",
    "1",
    " ",
    "  ",
    "#c",
    '"#q"',
    '"a,b"',
    "é",
    "中文",
    "a\tb",
    '"',
    '""',
    "a\x00b",
    "x" * 200,
]

#: doc_filter 术语汤——词/非词边界、大小写、unicode、占位符形、多行
_EN_SOUP = [
    "foo",
    "Bar",
    "AI",
    "c++",
    "C++",
    "a.b",
    "x y",
    "naïve",
    "中文",
    "-x",
    "x-",
    "[t]",
    "[[M_1]]",
    "x\ny",
    "end.",
    "2fa",
    "O'Reilly",
    "foo-bar",
    "",
    " ",
    "_",
]

_TEXT_SOUP = [
    "Hello world.",
    "the AI model",
    "a foo here",
    "xfoox",
    "C++17 code",
    "use C++ now",
    "a.b test",
    "xa.b tail",
    "naïve bayes",
    "中文 片段",
    "bar",
    "2factor",
    "a 2fa token",
    "[[M_1]] math",
    "x\ny seam",
    "a x",
    "y b",
    "O'Reilly book",
    "foo-bar baz",
    "\n",
    " ",
    "\t",
]


# ---------------------------------------------------------------- 牢笼 oracle


def _roots_of(glossary_dir: str, base_dir: Path) -> list[Path]:
    roots = [base_dir.resolve()]
    if glossary_dir:
        roots.append(Path(glossary_dir).expanduser().resolve())
    return roots


def _assert_jailed(out: Path | None, roots: list[Path]) -> None:
    """牢笼不变量：None，或 resolve 后在允许根内的常规文件。"""
    if out is None:
        return
    assert out.is_file(), f"non-file returned: {out}"
    assert any(out.is_relative_to(r) for r in roots), f"escape: {out} not under {roots}"


@pytest.fixture
def jail_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """base/gdir/outside 三树 + base 内五类 symlink（逃逸/内部/悬挂/自环）。"""
    base, gdir, outside = tmp_path / "base", tmp_path / "gdir", tmp_path / "out"
    for d in (base, gdir, outside):
        d.mkdir()
    (base / "t.yaml").write_text("a: 1\n", encoding=_MODE)
    (base / "sub").mkdir()
    (base / "sub" / "deep.yaml").write_text("d: 1\n", encoding=_MODE)
    (gdir / "g.yaml").write_text("a: 2\n", encoding=_MODE)
    (outside / "sec.yaml").write_text("leak: 1\n", encoding=_MODE)
    (base / "lk_f_out").symlink_to(outside / "sec.yaml")
    (base / "lk_d_out").symlink_to(outside, target_is_directory=True)
    (base / "lk_in").symlink_to(base / "t.yaml")
    (base / "lk_dangle").symlink_to(base / "missing")
    (base / "lk_loop").symlink_to(base / "lk_loop")
    (gdir / "lk_gd_out").symlink_to(outside / "sec.yaml")
    return base, gdir, outside


# ---------------------------------------------------------------- 牢笼：拒/钉


@pytest.mark.parametrize(
    "gpath",
    [
        "/etc/passwd",
        "/",
        "//h/x",
        "..",
        "../x",
        "a/../b",
        "a/b/../../x",
        "sub/../..",
        "t.yaml/..",
        "a/./../b",
        "../",
        "../../etc/passwd",
    ],
)
def test_glossary_path_rejects_absolute_dotdot(
    gpath: str, jail_tree: tuple[Path, Path, Path]
) -> None:
    """绝对形与含 ``..`` 组件预检即拒（resolve 前的字面判，不依赖盘上实况）。"""
    base, gdir, _ = jail_tree
    assert resolve_glossary_path(gpath, "", base) is None
    assert resolve_glossary_path(gpath, str(gdir), base) is None


def test_glossary_path_symlink_escape(jail_tree: tuple[Path, Path, Path]) -> None:
    """resolve 后落根外的 symlink 全挡：文件链、目录链穿层、悬挂、gdir 侧同挡。

    环链不在此——resolve() 对其抛 RuntimeError，是 D9 xfail 钉的面。
    """
    base, gdir, _ = jail_tree
    for bad in ("lk_f_out", "lk_d_out/sec.yaml", "lk_d_out", "lk_dangle"):
        assert resolve_glossary_path(bad, "", base) is None, bad
    assert resolve_glossary_path("lk_gd_out", str(gdir), base) is None
    # 根内 symlink 放行（confine 按解析后位置，不按名字洁癖）
    assert resolve_glossary_path("lk_in", "", base) == (base / "t.yaml").resolve()
    assert (
        resolve_glossary_path("sub/deep.yaml", "", base)
        == (base / "sub" / "deep.yaml").resolve()
    )


def test_glossary_path_root_order_and_fallthrough(
    jail_tree: tuple[Path, Path, Path],
) -> None:
    """base 根先中（同名双根 → base 胜）；base 侧目录命中不遮蔽 gdir 文件。"""
    base, gdir, _ = jail_tree
    (gdir / "t.yaml").write_text("g: 9\n", encoding=_MODE)
    assert (
        resolve_glossary_path("t.yaml", str(gdir), base) == (base / "t.yaml").resolve()
    )
    # base/sub 是目录 → is_file 门失败 → 不遮蔽 gdir/sub 同名文件
    (gdir / "sub").write_text("s: 1\n", encoding=_MODE)
    assert resolve_glossary_path("sub", str(gdir), base) == (gdir / "sub").resolve()
    # 仅 gdir 命中 → 兜底根生效
    assert resolve_glossary_path("g.yaml", "", base) is None
    assert (
        resolve_glossary_path("g.yaml", str(gdir), base) == (gdir / "g.yaml").resolve()
    )
    # 双根皆无 → None
    assert resolve_glossary_path("nope.yaml", str(gdir), base) is None


def test_glossary_path_weird_names_confined(
    jail_tree: tuple[Path, Path, Path],
) -> None:
    """怪名不是逃逸理由——根内实存的换行/空白/``~``/surrogate 名照常被服务。

    confine 按解析后位置判，非名字卫生；surrogateescape 名对应原始字节
    文件名（合法回环）。POSIX 下 ``\\`` 非分隔符——``a\\..\\b`` 是单组件
    字面名，不构 ``..`` 语义。
    """
    base, _, _ = jail_tree
    for name in ("a\nb", " ", "~x", "..x", "x..", "a\\..\\b"):
        (base / name).write_text("k: v\n", encoding=_MODE)
        assert resolve_glossary_path(name, "", base) == (base / name).resolve()
    raw = base / "raw\udcffb.yaml"
    fd = os.open(os.fsencode(raw), os.O_CREAT | os.O_WRONLY, 0o644)
    os.write(fd, b"k: v\n")
    os.close(fd)
    assert resolve_glossary_path("raw\udcffb.yaml", "", base) == raw.resolve()
    # ``~`` 不展开为用户目录——受困字面名
    assert resolve_glossary_path("~/anything", "", base) is None
    assert resolve_glossary_path("~", "", base) is None


def test_glossary_path_normalization(
    jail_tree: tuple[Path, Path, Path],
) -> None:
    """Path 归一化的副面：尾斜杠/``/./``/双分隔符剥落后照常解析；``a/../b``
    即使会 resolve 回根内也被预检拒（严格口径钉）。"""
    base, _, _ = jail_tree
    assert resolve_glossary_path("t.yaml/", "", base) == (base / "t.yaml").resolve()
    assert resolve_glossary_path("./t.yaml", "", base) == (base / "t.yaml").resolve()
    assert (
        resolve_glossary_path("sub//deep.yaml", "", base)
        == (base / "sub" / "deep.yaml").resolve()
    )
    assert (
        resolve_glossary_path("sub/../t.yaml", "", base) is None
    )  # 预检拒，不看 resolve 终点


def test_glossary_path_missing_and_relative_roots(tmp_path: Path) -> None:
    """缺/空根优雅 None；相对 ``glossary_dir`` resolve 到进程 CWD（观察钉：

    生产不可达——``settings._check_glossary_dir`` 强制绝对+现存目录；
    纯函数层面 CWD 相关性如实钉住）。
    """
    base = tmp_path / "nobase"
    assert resolve_glossary_path("x.yaml", "", base) is None
    assert resolve_glossary_path("x.yaml", str(tmp_path / "nogdir"), tmp_path) is None
    # 相对 glossary_dir → CWD 下找
    cwd_rel = Path.cwd() / "relgdir-probe"
    cwd_rel.mkdir(exist_ok=True)
    try:
        (cwd_rel / "x.yaml").write_text("k: 1\n", encoding=_MODE)
        assert (
            resolve_glossary_path("x.yaml", "relgdir-probe", tmp_path)
            == (cwd_rel / "x.yaml").resolve()
        )
    finally:
        for f in cwd_rel.iterdir():
            f.unlink()
        cwd_rel.rmdir()


def test_glossary_path_dot_returns_file_root(tmp_path: Path) -> None:
    """观察钉：``gpath="."``/``""`` 遇**文件型**根返回根本身。

    ``is_relative_to`` 含等号——根本身是文件时即被当候选命中。
    生产不可达（roots 恒为目录），纯函数层面如实钉。
    """
    f = tmp_path / "only.yaml"
    f.write_text("k: 1\n", encoding=_MODE)
    assert resolve_glossary_path(".", "", f) == f.resolve()
    assert resolve_glossary_path("", "", f) == f.resolve()
    d = tmp_path / "d"
    d.mkdir()
    assert resolve_glossary_path(".", "", d) is None
    assert resolve_glossary_path("", "", d) is None


def test_glossary_path_boundary_255_graceful(tmp_path: Path) -> None:
    """``NAME_MAX`` 界内（255B）长名不抛；>255B 由 D2 xfail 钉。"""
    for n in (_NAME_MAX - 1, _NAME_MAX):
        assert resolve_glossary_path("x" * n, "", tmp_path) is None
    # 多字节名按字节计——80 个「日」= 240B 界内
    assert resolve_glossary_path("日" * 80, "", tmp_path) is None


def test_glossary_path_deterministic(jail_tree: tuple[Path, Path, Path]) -> None:
    """同参双调逐字节同果（纯函数钉）。"""
    base, gdir, _ = jail_tree
    for gpath in ("t.yaml", "../x", "lk_in", "nope", "a\nb"):
        assert resolve_glossary_path(gpath, str(gdir), base) == resolve_glossary_path(
            gpath, str(gdir), base
        )


def test_fuzz_glossary_path_jail(jail_tree: tuple[Path, Path, Path]) -> None:
    """随机敌意名 soup——``None`` 或「resolve 后在允许根内的常规文件」。

    崩溃族（NUL/>255B）由 xfail 钉单独覆盖；本汤全界内——抛即新缺陷。
    """
    rng = fuzz_rng(_SEED_JAIL)
    base, gdir, outside = jail_tree
    for _ in range(_FUZZ_ITERS):
        n = rng.randint(0, 4)
        gpath = rng.choice(["/", "//"]).join(rng.choice(_COMP_SOUP) for _ in range(n))
        r = rng.random()
        if r < 0.12:  # noqa: PLR2004 -- soup 概率档
            gpath = "/" + gpath
        elif r < 0.2:  # noqa: PLR2004
            gpath = "~/" + gpath
        elif r < 0.3:  # noqa: PLR2004
            gpath = rng.choice(["lk_d_out/", "lk_dangle/", "sub/"]) + gpath
        gdir_arg = rng.choice(["", str(gdir), str(outside)])
        roots = _roots_of(gdir_arg, base)
        _assert_jailed(resolve_glossary_path(gpath, gdir_arg, base), roots)


def test_fuzz_glossary_path_jail_forest(tmp_path: Path) -> None:
    """随机 symlink 林（内/外/悬挂/环）× 随机名——同牢笼不变量。"""
    rng = fuzz_rng(_SEED_JAIL + 1)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sec.yaml").write_text("leak: 1\n", encoding=_MODE)
    (outside / "sub").mkdir()
    (outside / "sub" / "deep.yaml").write_text("d: 1\n", encoding=_MODE)
    for it in range(_FUZZ_ITERS_MED):
        base = tmp_path / f"b{it}"
        gdir = tmp_path / f"g{it}"
        base.mkdir()
        gdir.mkdir()
        (base / "t.yaml").write_text("a: 1\n", encoding=_MODE)
        # 每树撒 0-3 条随机 symlink
        for j in range(rng.randint(0, 3)):
            lnk = base / f"l{j}"
            tgt = rng.choice(
                [
                    outside / "sec.yaml",
                    outside,
                    base / "t.yaml",
                    base / "missing",
                    gdir,
                    # 自环（lnk 自身）不入——ELOOP→RuntimeError 是 D9 面
                ]
            )
            lnk.symlink_to(tgt, target_is_directory=tgt.is_dir())
        gdir_arg = rng.choice(["", str(gdir)])
        roots = _roots_of(gdir_arg, base)
        for _ in range(rng.randint(1, 6)):
            n = rng.randint(1, 3)
            gpath = "/".join(
                rng.choice([*_COMP_SOUP, "l0", "l1", "l2"]) for _ in range(n)
            )
            _assert_jailed(resolve_glossary_path(gpath, gdir_arg, base), roots)


# ---------------------------------------------------------------- 牢笼：崩溃族（缺陷钉）


@pytest.mark.parametrize(
    "gpath", ["\x00", "a\x00b", "x\x00.yaml", "sub/\x00", "\x00/x"]
)
def test_glossary_path_nul_returns_none(
    gpath: str, jail_tree: tuple[Path, Path, Path]
) -> None:
    """NUL 名按「不在允许根内」静默拒——同 ``..`` 拒径同语态（D1 已修：
    ``safe_resolve`` 吞 ``ValueError``）。"""
    base, gdir, _ = jail_tree
    assert resolve_glossary_path(gpath, "", base) is None
    assert resolve_glossary_path(gpath, str(gdir), base) is None


def test_glossary_path_nul_gdir_returns_none(tmp_path: Path) -> None:
    """D1 同族：``glossary_dir`` 含 NUL → 该根按缺席处理。"""
    base = tmp_path / "base"
    base.mkdir()
    assert resolve_glossary_path("x.yaml", "g\x00d", base) is None


@pytest.mark.parametrize("n", [_NAME_MAX + 1, _NAME_MAX + 45])
def test_glossary_path_overlong_component(
    n: int, jail_tree: tuple[Path, Path, Path]
) -> None:
    """D2 已修：>255B 组件经 ``safe_resolve`` 吞 ``ENAMETOOLONG`` → None。"""
    base, gdir, _ = jail_tree
    assert resolve_glossary_path("x" * n, "", base) is None
    assert resolve_glossary_path("sub/" + "x" * n, str(gdir), base) is None


@pytest.mark.parametrize("gpath", ["lk_loop", "lk_loop/x"])
def test_glossary_path_symlink_loop_returns_none(
    gpath: str, jail_tree: tuple[Path, Path, Path]
) -> None:
    """D9 已修：环链按「非常规文件」静默拒——同悬挂链同语态
    （``check_eloop`` 的 ``RuntimeError`` 非 OSError 系，``safe_resolve`` 同吞）。"""
    base, gdir, _ = jail_tree
    assert resolve_glossary_path(gpath, "", base) is None
    assert resolve_glossary_path(gpath, str(gdir), base) is None


# ---------------------------------------------------------------- flatten_terms


@pytest.mark.parametrize(
    ("data", "want"),
    [
        (None, {}),
        ({"a": "1"}, {"a": "1"}),
        ({"a": {"target": "1"}}, {"a": "1"}),
        ({"terms": {"a": "1"}}, {"a": "1"}),
        # dict 值无 target → 恒等（宁保原语不读歪的对偶面）
        ({"a": {"context": "c"}}, {"a": "a"}),
        ({"a": ""}, {"a": "a"}),
        ({"a": "  "}, {"a": "a"}),
        ({"  a  ": "1"}, {"a": "1"}),
        ({"": "1", "  ": "2"}, {}),
        # "terms" 非标量值不当包装——按普通术语处理（观察钉）
        ({"terms": "x"}, {"terms": "x"}),
        # "terms" 包装命中后顶层兄弟键静默丢（观察钉）
        ({"terms": {"a": "1"}, "extra": "x"}, {"a": "1"}),
        # 嵌套 terms 只解一层——内层 "terms" 落回普通术语（观察钉）
        ({"terms": {"terms": {"a": "1"}}}, {"terms": "terms"}),
        # 非 str 键 str() 化；True==1 键碰撞后者胜（观察钉；``|`` 合并避 F601/C408/C416 互搏）
        ({1: "a"} | {True: "b"}, {"1": "b"}),
        ({None: "x"}, {"None": "x"}),
        # D3 同族非 None 标量——语义可辩，如实钉
        ({"a": False}, {"a": "False"}),
        ({"a": 0}, {"a": "0"}),
        ({"a": {"target": ["x"]}}, {"a": "['x']"}),  # 嵌套 list 不拒（不对称）
        ({"a": {"target": {"x": 1}}}, {"a": "{'x': 1}"}),
    ],
)
def test_flatten_terms_forms(data: object, want: dict[str, str]) -> None:
    assert flatten_terms(data, name="t") == want


@pytest.mark.parametrize("data", [["a"], "x", 42, 3.5])
def test_flatten_terms_rejects_nonmap(data: object) -> None:
    """非 mapping 顶层（None 除外——空文件语义回 {}）只抛 TypeError。"""
    with pytest.raises(TypeError):
        flatten_terms(data, name="t")


@pytest.mark.parametrize(
    "data",
    [{"a": [1]}, {"a": []}, {"a": ["x", "y"]}, {"terms": {"a": [1]}}],
)
def test_flatten_terms_list_value_typeerror(data: object) -> None:
    """顶层 list 值刻意拒载（宁可拒载不静默读歪——docstring 明誓）。"""
    with pytest.raises(TypeError):
        flatten_terms(data, name="t")


@pytest.mark.parametrize(
    "data",
    [{"a": None}, {"a": {"target": None}}],
)
def test_flatten_terms_null_is_identity(data: object) -> None:
    """D3 已修：空值术语 = 保原语（``zh == en``），与 ``en: ""`` 同语态。"""
    assert flatten_terms(data, name="t") == {"a": "a"}


def test_fuzz_flatten_terms_contract() -> None:
    """随机结构汤——只回 ``dict[str,str]``（键非空）或 ``TypeError``，他型不抛。"""
    rng = fuzz_rng(_SEED_FLAT)
    atoms: list[object] = ["a", "1", 0, 1, True, False, None, 3.5, "é", " "]

    def gen(depth: int = 0) -> object:
        r = rng.random()
        if depth >= 2 or r < 0.5:  # noqa: PLR2004 -- soup 参数
            return rng.choice(atoms)
        if r < 0.75:  # noqa: PLR2004
            return {rng.choice(atoms): gen(depth + 1) for _ in range(rng.randint(0, 4))}
        return [gen(depth + 1) for _ in range(rng.randint(0, 3))]

    for _ in range(_FUZZ_ITERS_MED):
        try:
            out = flatten_terms(gen(), name="f")
        except TypeError:
            continue
        assert isinstance(out, dict)
        assert all(
            isinstance(k, str) and isinstance(v, str) and k for k, v in out.items()
        )


# ---------------------------------------------------------------- load_csv / load_yaml / load_table


def test_load_csv_pins(tmp_path: Path) -> None:
    """注释/空行/引号/单例恒等/后写胜/NUL 穿透逐条钉。

    D6 已修：注释判定在原始行上做——裸 ``#x,3`` 是注释丢，
    RFC 引号形 ``"#q"`` 是数据留。
    """
    p = tmp_path / "t.csv"
    p.write_text(
        "a,1\n"
        "# comment line\n"
        "   \n"
        '"b,c",2\n'
        "#x,3\n"
        '"#q",4\n'
        "single\n"
        "k, \n"
        " ,z\n"
        "last,one\n"
        "last,two\n"
        "a\tb,tab\n",
        encoding=_MODE,
    )
    assert load_csv(p) == {
        "a": "1",
        "b,c": "2",
        "#q": "4",  # 引号形 ``#`` 字段是数据
        "single": "single",
        "k": "k",
        "last": "two",  # 同文件重复：后写胜（对照跨层先写胜）
        "a\tb": "tab",
    }
    nul = tmp_path / "nul.csv"
    nul.write_bytes(b"a\x00b,zh\n")
    assert load_csv(nul) == {"a\x00b": "zh"}  # NUL 穿透成术语键
    bom = tmp_path / "bom.csv"
    bom.write_bytes(b"\xef\xbb\xbfa,1\n")
    assert load_csv(bom) == {"a": "1"}  # utf-8-sig 剥 BOM
    extra = tmp_path / "extra.csv"
    extra.write_text("a,1,2,3\n", encoding=_MODE)
    assert load_csv(extra) == {"a": "1"}  # 多余列静默丢
    u16 = tmp_path / "u16.csv"
    u16.write_bytes("a: 1\n".encode("utf-16"))
    with pytest.raises(UnicodeDecodeError):
        load_csv(u16)


def test_load_csv_deterministic(tmp_path: Path) -> None:
    p = tmp_path / "d.csv"
    p.write_text("b,2\na,1\nc,3\n", encoding=_MODE)
    assert load_csv(p) == load_csv(p)


def test_fuzz_load_csv_contract(tmp_path: Path) -> None:
    """随机行流——恒 ``dict[str,str]`` 键非空、重载同果。"""
    rng = fuzz_rng(_SEED_CSV)
    for i in range(_FUZZ_ITERS_MED):
        lines = [
            ",".join(rng.choice(_CSV_FIELD_SOUP) for _ in range(rng.randint(1, 4)))
            for _ in range(rng.randint(0, 12))
        ]
        p = tmp_path / f"c{i}.csv"
        p.write_text("\n".join(lines), encoding=_MODE)
        out = load_csv(p)
        assert isinstance(out, dict)
        assert all(
            isinstance(k, str) and isinstance(v, str) and k for k, v in out.items()
        )
        assert out == load_csv(p)


def test_load_csv_huge_field_graceful(tmp_path: Path) -> None:
    """D5 已修：超限字段不使整表拒载——``load_csv`` 解析期间把
    ``csv.field_size_limit`` 抬到平台上限、读完还原。"""
    p = tmp_path / "big.csv"
    p.write_text("k," + "v" * (_CSV_FIELD_MAX + 1) + "\n", encoding=_MODE)
    assert load_csv(p) == {"k": "v" * (_CSV_FIELD_MAX + 1)}


def test_load_yaml_pins(tmp_path: Path) -> None:
    """BOM/编码/语法/非安全 tag/重复键/顶层形态的异常分类钉。"""
    bom = tmp_path / "bom.yaml"
    bom.write_bytes(b"\xef\xbb\xbfa: 1\n")
    assert load_yaml(bom) == {"a": "1"}  # PyYAML 自剥 BOM
    u16 = tmp_path / "u16.yaml"
    u16.write_bytes("a: 1\n".encode("utf-16"))
    with pytest.raises(UnicodeDecodeError):
        load_yaml(u16)
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed\n", encoding=_MODE)
    with pytest.raises(yaml.YAMLError):
        load_yaml(bad)
    unsafe = tmp_path / "obj.yaml"
    unsafe.write_text("a: !!python/object/apply:os.system ['id']\n", encoding=_MODE)
    with pytest.raises(yaml.YAMLError):  # ConstructorError ⊆ YAMLError
        load_yaml(unsafe)
    dup = tmp_path / "dup.yaml"
    dup.write_text("a: 1\na: 2\n", encoding=_MODE)
    assert load_yaml(dup) == {"a": "2"}  # PyYAML 静默后写胜
    lst = tmp_path / "list.yaml"
    lst.write_text("- a\n- b\n", encoding=_MODE)
    with pytest.raises(TypeError):
        load_yaml(lst)
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding=_MODE)
    assert load_yaml(empty) == {}


def test_load_table_dispatch(tmp_path: Path) -> None:
    """后缀分发钉：.csv/.yaml/.yml 通；大小写敏感（PLAUSIBLE papercut——
    ``X.CSV`` 同格式被拒）；缺文件 ``FileNotFoundError``；目录后缀巧名
    ``IsADirectoryError``。"""
    for name in ("a.csv", "a.yaml", "a.yml"):
        p = tmp_path / name
        p.write_text("a: 1\n" if name != "a.csv" else "a,1\n", encoding=_MODE)
        assert load_table(p) == {"a": "1"}
    up = tmp_path / "UP.CSV"
    up.write_text("a,1\n", encoding=_MODE)
    with pytest.raises(ValueError, match="unsupported glossary format"):
        load_table(up)
    with pytest.raises(ValueError, match="unsupported glossary format"):
        load_table(tmp_path / "plain")
    with pytest.raises(FileNotFoundError):
        load_table(tmp_path / "missing.csv")
    d = tmp_path / "d.yaml"
    d.mkdir()
    with pytest.raises(IsADirectoryError):
        load_table(d)


# ---------------------------------------------------------------- load_index


def test_load_index_forms(tmp_path: Path) -> None:
    """缺文件/空文件 → ``{}``；str 逗号分隔与 list 形态；脏结构 ``TypeError``。"""
    assert load_index(tmp_path / "none.yaml") == {}
    idx = tmp_path / "index.yaml"
    idx.write_text("", encoding=_MODE)
    assert load_index(idx) == {}
    idx.write_text("cA: a.csv, b.csv\ncB: [c.csv]\ncC: ''\n", encoding=_MODE)
    assert load_index(idx) == {
        "cA": ["a.csv", "b.csv"],
        "cB": ["c.csv"],
        "cC": [],
    }
    idx.write_text("cN: [1, 2.5]\n", encoding=_MODE)
    assert load_index(idx) == {"cN": ["1", "2.5"]}  # 非 str 成员 str() 化
    idx.write_text("- notamap\n", encoding=_MODE)
    with pytest.raises(TypeError, match="must be a mapping"):
        load_index(idx)
    idx.write_text("c: 7\n", encoding=_MODE)
    with pytest.raises(TypeError, match="must be a string or list"):
        load_index(idx)


def test_load_index_escape_mechanism(tmp_path: Path) -> None:
    """D4 已修：index 条目 confine 到 ``terms_dir``——``..`` 相对形、绝对路径
    （``Path`` 右操作数取胜）、symlink 外指三臂 resolve 后落界外一律跳过。

    ``terms_dir`` 是 ``Glossary.load`` 公开 kwarg——根/索引一旦用户可写，
    裸拼接即任意文件读（术语进 prompt 是外泄通道，审计 M2 口径）。
    """
    tdir = tmp_path / "terms"
    tdir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sec.yaml").write_text("leak: 外\n", encoding=_MODE)
    (outside / "abs.yaml").write_text("absleak: 外\n", encoding=_MODE)
    (tdir / "lk.yaml").symlink_to(outside / "sec.yaml")
    (tdir / "index.yaml").write_text(
        f'c1: ../outside/sec.yaml\nc2: ["{outside}/abs.yaml"]\nc3: ok.csv\nc4: lk.yaml\n',
        encoding=_MODE,
    )
    (tdir / "ok.csv").write_text("ok,1\n", encoding=_MODE)
    g = Glossary.load(
        categories=["c1", "c2", "c3", "c4"], terms_dir=tdir, include_default=False
    )
    assert "leak" not in g.terms  # .. 逃逸被拒
    assert "absleak" not in g.terms  # 绝对路径逃逸被拒
    assert g.terms["ok"].zh == "1"


# ---------------------------------------------------------------- Glossary.load 五层


def _wcsv(path: Path, table: dict[str, str]) -> None:
    """平表 csv 写出器（oracle 侧知悉内容——只产干净键值）。"""
    path.write_text("".join(f"{en},{zh}\n" for en, zh in table.items()), encoding=_MODE)


def test_load_layer_precedence(tmp_path: Path) -> None:
    """五层序钉：user > local > category(声明序→文件序) > default > placeholder。"""
    tdir = tmp_path / "terms"
    tdir.mkdir()
    (tdir / "index.yaml").write_text(
        "catA: [a.csv, b.csv]\ncatB: c.csv\n", encoding=_MODE
    )
    _wcsv(tdir / "a.csv", {"shared": "catA-a", "aonly": "va"})
    _wcsv(tdir / "b.csv", {"shared": "catA-b", "bonly": "vb"})
    _wcsv(tdir / "c.csv", {"shared": "catB-c", "conly": "vc"})
    _wcsv(tdir / "default.csv", {"shared": "def", "donly": "vd"})
    u = tmp_path / "u.csv"
    _wcsv(u, {"shared": "user", "uonly": "u"})
    loc = tmp_path / "l.csv"
    _wcsv(loc, {"shared": "local", "lonly": "l"})
    g = Glossary.load(
        user_path=u,
        local_path=loc,
        categories=["catA", "catB"],
        terms_dir=tdir,
        placeholders=["shared", "phonly"],
    )
    got = {k: (v.zh, v.source) for k, v in g.terms.items()}
    assert got["shared"] == ("user", "user")
    assert got["uonly"] == ("u", "user")
    assert got["lonly"] == ("l", "local")
    assert got["aonly"] == ("va", "category:catA")
    assert got["bonly"] == ("vb", "category:catA")  # 同 cat 文件序先写胜
    assert got["conly"] == ("vc", "category:catB")
    assert got["donly"] == ("vd", "default")
    assert got["phonly"] == ("phonly", "placeholder")
    # 声明序翻转 → 赢家翻转（顺序即规格）
    g2 = Glossary.load(
        categories=["catB", "catA"], terms_dir=tdir, include_default=False
    )
    assert g2.terms["shared"].source == "category:catB"


def test_load_missing_and_broken(tmp_path: Path) -> None:
    """缺文件层静默跳；断链 symlink ``exists()=False`` 同跳（NUL 路径
    ``exists()`` 吞 ValueError 同跳——观察钉见 docstring）。"""
    assert (
        Glossary.load(user_path=tmp_path / "none.yaml", include_default=False).terms
        == {}
    )
    blink = tmp_path / "blink.csv"
    blink.symlink_to(tmp_path / "missing")
    assert Glossary.load(user_path=blink, include_default=False).terms == {}
    nul = tmp_path / "a\x00b.csv"
    assert Glossary.load(user_path=nul, include_default=False).terms == {}
    # 未知 category 静默；index 缺失静默
    tdir = tmp_path / "terms"
    tdir.mkdir()
    assert (
        Glossary.load(categories=["nope"], terms_dir=tdir, include_default=False).terms
        == {}
    )


@pytest.mark.parametrize("name", ["glos", "glos.yaml"])
def test_load_dir_layer_skipped(tmp_path: Path, name: str) -> None:
    """D8 已修：层门 ``exists()`` → ``safe_is_file``——目录型路径按无文件跳过。"""
    d = tmp_path / name
    d.mkdir()
    g = Glossary.load(user_path=d, include_default=False)
    assert g.terms == {}


def test_load_category_dir_entry_skipped(tmp_path: Path) -> None:
    """D8 同族已修：category 条目指向目录 → confine 门后 ``safe_is_file`` 拒。"""
    tdir = tmp_path / "terms"
    tdir.mkdir()
    (tdir / "d.csv").mkdir()
    (tdir / "index.yaml").write_text("c: [d.csv]\n", encoding=_MODE)
    g = Glossary.load(categories=["c"], terms_dir=tdir, include_default=False)
    assert g.terms == {}


def test_load_index_malformed_propagates(tmp_path: Path) -> None:
    """index 结构脏 → ``TypeError`` 出 ``load``（受信层的「宁抛不歪」钉）。"""
    tdir = tmp_path / "terms"
    tdir.mkdir()
    (tdir / "index.yaml").write_text("- notamap\n", encoding=_MODE)
    with pytest.raises(TypeError):
        Glossary.load(categories=["c"], terms_dir=tdir, include_default=False)


def test_load_no_confine_by_design(tmp_path: Path) -> None:
    """观察钉：``load`` 对显式路径零 confine——任意位置皆读（边界在
    worker ``resolve_glossary_path``，非装载器职责）。"""
    anywhere = tmp_path / "deep" / "elsewhere.csv"
    anywhere.parent.mkdir(parents=True)
    _wcsv(anywhere, {"x": "1"})
    assert Glossary.load(user_path=anywhere, include_default=False).terms["x"].zh == "1"


def test_load_user_placeholder_shape_overrides(tmp_path: Path) -> None:
    """观察钉（PLAUSIBLE 设计张力）：用户术语 en 与占位符同形时，
    占位符恒等注入被 ``setdefault`` 挡死——``[[MATH_1]]`` 被映射成用户
    zh 进 prompt，模型可能「照译」占位符 → ph diff 丢标。"""
    u = tmp_path / "u.csv"
    _wcsv(u, {"[[MATH_1]]": "数学"})
    g = Glossary.load(user_path=u, include_default=False, placeholders=["[[MATH_1]]"])
    assert g.terms["[[MATH_1]]"].source == "user"
    assert g.terms["[[MATH_1]]"].zh == "数学"
    # doc_filter 将其当真术语注入（corpus 含该 token 时）
    assert g.doc_filter(["see [[MATH_1]] here"]) == {"[[MATH_1]]": "数学"}


def test_fuzz_load_precedence_oracle(  # noqa: C901 -- 分层构造天然多支，分支即层语义
    tmp_path: Path,
) -> None:
    """随机分层构造 → 逐 ``(zh, source)`` 对独立 oracle + 重载确定性。

    oracle = 按层序 ``setdefault`` 重放我自己写出的表（文件内容即生成
    物——无解析黑盒）；类目声明序含重复与未登记项。
    """
    rng = fuzz_rng(_SEED_LOAD)
    cats_pool = ("cA", "cB", "cC")
    ens = ["alpha", "beta", "gamma", "delta", "eps", "zeta", "[[PH_1]]", "[[M_2]]"]
    zhs = ["甲", "乙", "丙", "丁"]
    phs_pool = ["[[P_1]]", "[[P_2]]", "[[Q_1]]", "alpha", "[[PH_1]]"]
    for it in range(_FUZZ_ITERS_MED):
        d = tmp_path / f"i{it}"
        tdir = d / "terms"
        tdir.mkdir(parents=True)
        exp: dict[str, tuple[str, str]] = {}

        def put(
            table: dict[str, str],
            src: str,
            dst: dict = exp,  # 当帧 exp 即目表（默认参绑定即 B023 正解）
        ) -> None:
            for en, zh in table.items():
                dst.setdefault(en, (zh, src))

        # ① user 层（随机在场）
        u = None
        if rng.random() < 0.7:  # noqa: PLR2004 -- soup 概率
            u = d / "u.csv"
            table = {rng.choice(ens): rng.choice(zhs) for _ in range(rng.randint(1, 4))}
            _wcsv(u, table)
            put(table, "user")
        # ② local 层
        loc = None
        if rng.random() < 0.6:  # noqa: PLR2004
            loc = d / "l.csv"
            table = {rng.choice(ens): rng.choice(zhs) for _ in range(rng.randint(1, 3))}
            _wcsv(loc, table)
            put(table, "local")
        # ③ category 层：index + 各 cat 1-2 个 csv（可共享）
        index: dict[str, list[str]] = {}
        files: dict[str, dict[str, str]] = {}
        for c in rng.sample(cats_pool, rng.randint(0, 3)):
            fnames = [f"{c}{j}.csv" for j in range(rng.randint(1, 2))]
            index[c] = fnames
            for f in fnames:
                if f not in files:
                    files[f] = {
                        rng.choice(ens): rng.choice(zhs)
                        for _ in range(rng.randint(1, 4))
                    }
                    _wcsv(tdir / f, files[f])
        (tdir / "index.yaml").write_text(
            "".join(f"{c}: {', '.join(fs)}\n" for c, fs in index.items()),
            encoding=_MODE,
        )
        cats = [rng.choice([*cats_pool, "nope"]) for _ in range(rng.randint(0, 4))]
        for c in cats:
            for f in index.get(c, []):
                put(files[f], f"category:{c}")
        # ④ default 层
        include_default = rng.random() < 0.8  # noqa: PLR2004
        if rng.random() < 0.7:  # noqa: PLR2004
            dt = {rng.choice(ens): rng.choice(zhs) for _ in range(rng.randint(1, 3))}
            _wcsv(tdir / "default.csv", dt)
            if include_default:
                put(dt, "default")
        # ⑤ placeholder 层——oracle 镜像 ``(sort_key, ph)`` 全序
        phs = [rng.choice(phs_pool) for _ in range(rng.randint(0, 4))]
        for ph in sorted(set(phs), key=lambda p: (sort_key(p), p)):
            exp.setdefault(ph, (ph, "placeholder"))

        g = Glossary.load(
            user_path=u,
            local_path=loc,
            categories=cats,
            terms_dir=tdir,
            include_default=include_default,
            placeholders=phs,
        )
        got = [(k, v.zh, v.source) for k, v in g.terms.items()]
        want = [(k, zh, src) for k, (zh, src) in exp.items()]
        assert got == want, f"it={it}"
        assert g.as_dict() == {k: zh for k, (zh, _s) in exp.items()}
        # 重载逐字节同果
        g2 = Glossary.load(
            user_path=u,
            local_path=loc,
            categories=cats,
            terms_dir=tdir,
            include_default=include_default,
            placeholders=phs,
        )
        assert [(k, v.zh, v.source) for k, v in g2.terms.items()] == got


# ---------------------------------------------------------------- sort_key / 占位符序


def test_sort_key_order_pins() -> None:
    """TYPE 字典序 + n 数值序；裸标记 n=-1 排同型前；碰撞对实证存在。"""
    assert sort_key("[[A_2]]") < sort_key("[[A_10]]")  # 数值序非字典序
    assert sort_key("[[A]]") < sort_key("[[A_1]]")  # 裸先带号后
    # D7 碰撞面：不同 token 同 key —— tie 落 set 迭代序（哈希序）
    assert sort_key("[[A_1]]") == sort_key("[[A_01]]")
    assert sort_key("A") == sort_key("[[A]]")
    assert sort_key("x_3") == sort_key("[[x_3]]")
    # 任意字符串不抛（placeholders 参数是不受信 iterable）
    for s in ("", "[", "]", "_5", "a_", "__", "[[", "x_1_2", "日本語"):
        sort_key(s)


def _ph_order_in_subprocess(seed: int) -> str:
    """``PYTHONHASHSEED=seed`` 子进程里的占位符合并序（D7 实证仪）。"""
    toks = [
        "[[A_1]]",
        "[[A_01]]",
        "[[A_2]]",
        "[[A_02]]",
        "A",
        "[[A]]",
        "x_3",
        "[[x_3]]",
    ]
    code = (
        "from texlate.xlat.glossary import Glossary;"
        f"print(list(Glossary.load(include_default=False, placeholders={toks!r}).terms))"
    )
    r = subprocess.run(  # noqa: S603 -- 固定 argv 无外部输入
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": str(seed)},
        check=True,
        timeout=60,
    )
    return r.stdout.strip()


def test_placeholder_order_seed_independent() -> None:
    """D7 已修：注入序与 ``PYTHONHASHSEED`` 无关——排序键 ``(sort_key, ph)``
    全序消歧；``collect_doc_placeholders`` 同口径。"""
    orders = {_ph_order_in_subprocess(seed) for seed in (0, 1, 2, 42, 1337)}
    assert len(orders) == 1


def test_placeholder_dedup_and_order() -> None:
    """占位符去重 + ``sort_key`` 序（非碰撞面逐字节确定）。"""
    g = Glossary.load(
        include_default=False,
        placeholders=["[[B_2]]", "[[A_10]]", "[[A_2]]", "[[A_2]]"],
    )
    assert list(g.terms) == ["[[A_2]]", "[[A_10]]", "[[B_2]]"]


# ---------------------------------------------------------------- doc_filter


def _afold(s: str) -> str:
    """ASCII-only case fold——``re.IGNORECASE | re.ASCII`` 的等价口径
    （非 ASCII 字母不折叠，与 ``str.lower`` 刻意区分）。"""
    return "".join(c.upper() if "a" <= c <= "z" else c for c in s)


#: ws-flex 缝字符集——impl ``_term_pattern`` 的 ``[~\\s]+`` 同口径
#: （``re.ASCII`` 旗下 ``\\s`` = 六空白符）。
_SEAM = frozenset("~ \t\n\r\f\v")
_WS_SPLIT_RX = re.compile(r"[~\s]+")


def _zero_width_hit(fc: str) -> bool:
    """空/纯缝 en 的 ``(?<!\\w)(?!\\w)`` 零宽断言——逐位扫描。"""
    for i in range(len(fc) + 1):
        pre_ok = i == 0 or fc[i - 1] not in _ASCII_WORD
        post_ok = i == len(fc) or fc[i] not in _ASCII_WORD
        if pre_ok and post_ok:
            return True
    return False


def _seam_match(words: list[str], fc: str, i: int) -> int:
    """位置 i 起词序列缝扫——命中返尾位，否则 -1。"""
    j = i + len(words[0])
    for w in words[1:]:
        k = j
        while k < len(fc) and fc[k] in _SEAM:
            k += 1
        if k == j or not fc.startswith(w, k):
            return -1
        j = k + len(w)
    return j


def _oracle_term_hit(en: str, corpus: str) -> bool:
    """独立命中 oracle：词序列按 ``[~\\s]+`` 缝扫描 + 首尾 ASCII 词边界。

    镜像 ``_term_pattern``：en strip 后按 ``[~\\s]+`` 切词，缝可吃
    换行/tab/``~``/多空格（≥1 缝字符必有）；空/纯缝 en 退化为
    零宽断言同旧口径。
    """
    words = [_afold(w) for w in _WS_SPLIT_RX.split(en.strip()) if w]
    fc = _afold(corpus)
    if not words:
        return _zero_width_hit(fc)
    first, start = words[0], 0
    while True:
        i = fc.find(first, start)
        if i < 0:
            return False
        j = _seam_match(words, fc, i)
        pre_ok = i == 0 or fc[i - 1] not in _ASCII_WORD
        post_ok = j >= 0 and (j == len(fc) or fc[j] not in _ASCII_WORD)
        if j >= 0 and pre_ok and post_ok:
            return True
        start = i + 1


def _oracle_doc_filter(
    terms: list[tuple[str, str, str]], texts: list[str]
) -> dict[str, str]:
    """``doc_filter`` 结构重放：真术语 oracle 命中 → ``en.lower()`` 稳定序；
    占位符不滤 corpus、``sort_key`` 排尾。"""
    corpus = "\n".join(texts)
    real = [
        (en, zh)
        for en, zh, src in terms
        if src != "placeholder" and _oracle_term_hit(en, corpus)
    ]
    real.sort(key=lambda t: t[0].lower())  # stable — tie 保 terms 序
    phs = [(en, zh) for en, zh, src in terms if src == "placeholder"]
    phs.sort(key=lambda t: (sort_key(t[0]), t[0]))
    return dict([*real, *phs])


def test_doc_filter_boundary_pins() -> None:
    """词边界语义钉：IGNORECASE 命中、``\\w`` 邻接拒、符号术语尾界、
    大小写双形态共存、占位符不滤 corpus 恒发。"""
    g = Glossary()
    for en in ["AI", "C++", "a.b", "naïve", "Foo", "foo"]:
        g.terms[en] = TermEntry(en, "T", "user")
    got = g.doc_filter(
        [
            "an ai tool",
            "C++17 code",
            "use C++ here",
            "xa.b tail",
            "a.b lit",
            "naïve bayes",
            "foo and Foo",
        ]
    )
    # "C++" 中自 "use C++ here"（C++17 的 '1' 词字符拒）；a.b 中自独立 "a.b"
    assert got == {
        "AI": "T",
        "C++": "T",
        "Foo": "T",
        "a.b": "T",
        "foo": "T",
        "naïve": "T",
    }


def test_doc_filter_seam_phantom() -> None:
    """观察钉：多行术语命中 ``\\n``-join 接缝——无单 chunk 含它仍被注入。"""
    g = Glossary()
    g.terms["x\ny"] = TermEntry("x\ny", "ZH", "user")
    assert g.doc_filter(["a x", "y b"]) == {"x\ny": "ZH"}
    assert g.doc_filter(["a x", "z y b"]) == {}  # 'x\nz' 非 seam 形 → 不中


def test_doc_filter_placeholder_unconditional() -> None:
    """占位符不滤 corpus 恒发（它们本来就是文档收集物）；空 corpus 同发。"""
    g = Glossary()
    g.terms["[[M_2]]"] = TermEntry("[[M_2]]", "[[M_2]]", "placeholder")
    g.terms["real"] = TermEntry("real", "真", "user")
    assert g.doc_filter(["unrelated"]) == {"[[M_2]]": "[[M_2]]"}
    assert g.doc_filter([]) == {"[[M_2]]": "[[M_2]]"}


def test_doc_filter_output_order() -> None:
    """输出序 = 真术语 ``en.lower()`` 序 + 占位符 ``sort_key`` 尾。"""
    g = Glossary()
    for en in ["zebra", "Apple", "mango"]:
        g.terms[en] = TermEntry(en, en + "z", "user")
    for ph in ("[[B_1]]", "[[A_9]]"):
        g.terms[ph] = TermEntry(ph, ph, "placeholder")
    assert list(g.doc_filter(["zebra apple mango"])) == [
        "Apple",
        "mango",
        "zebra",
        "[[A_9]]",
        "[[B_1]]",
    ]


def test_fuzz_doc_filter_oracle() -> None:
    """随机术语表 × 随机文本——命中集与输出序全量对独立 oracle。"""
    rng = fuzz_rng(_SEED_FILTER)
    for _ in range(_FUZZ_ITERS_MED):
        g = Glossary()
        for _ in range(rng.randint(0, 10)):
            en = rng.choice(_EN_SOUP)
            src = rng.choice(["user", "local", "category:c", "default"])
            if rng.random() < 0.2:  # noqa: PLR2004 -- soup 概率
                src = "placeholder"
                en = rng.choice(["[[P_1]]", "[[Q_2]]", "[[M_10]]"])
            g.terms.setdefault(en, TermEntry(en, f"z{en}", src))
        terms = [(e.en, e.zh, e.source) for e in g.terms.values()]
        texts = [_gen_soup(rng, _TEXT_SOUP, 0, 6) for _ in range(rng.randint(0, 6))]
        want = _oracle_doc_filter(terms, texts)
        got = g.doc_filter(texts)
        assert list(got.items()) == list(want.items())
        # 确定性：双调同果
        assert g.doc_filter(texts) == got


def _gen_soup(rng: random.Random, soup: list[str], lo: int, hi: int) -> str:
    return "".join(rng.choice(soup) for _ in range(rng.randint(lo, hi)))
