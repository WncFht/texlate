"""shimfix-b — Missing-} shim-polyfill 修复族 (shimdiag #171 cluster-B, task #181)。

三格同构缺陷: shim/polyfill 把稿面可含 ``\\\\`` 的参数 #1 囚进花括组,
组落进对齐格 (IEEEtran ``\\@IEEEauthorhalign`` / article ``\\@maketitle``
``tabular{c}``) → 内核 "Missing } inserted ... current column of the
current alignment" 级联:

- 0905.1990 / 1404.0346 (IEEEtran[conference]): ``\\authorblockA`` polyfill
  ``\\\\[1ex]{\\small #1}`` —— #1 自带 \\\\ (多行机构) 囚进 ``{\\small ...}``。
  修形: ``\\ifdefined\\IEEEauthorblockN/A\\let`` 直通真件 V1.8a 机制
  (类源 :6310-6311 注释掉的 legacy 别名即此桥); 缺席 fallback 内层
  ``tabular`` 兜住 #1 内 \\\\。
- astro-ph/9901364 (crckapb shim): ``\\institute`` def
  ``\\\\ {\\normalsize\\itshape #1}`` 同型 → 内层 tabular 修形。
- vendor/stubs/aipproc.cls ``\\fixaip@addr`` 同形潜在面同修。

不变式: 发射体中 #1 (稿面可携 \\\\) 若在花括组内, 必须在
``\\begin{tabular}..\\end{tabular}`` 跨距内 —— \\\\ 归内层对齐行。
"""

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx

VENDOR = Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor"


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


def _cs_table() -> dict:
    rule = next(r for r in _rs().rules if r.id == "cs_targeted_fix")
    return rule.action["params"]["cs_table"]


def _shim_map() -> dict:
    rule = next(r for r in _rs().rules if r.id == "legacy_pkg_shim")
    return rule.action["params"]["shim_map"]


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


class _Eng:
    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr"})


def _def_body(src: str, head_pat: str) -> str:
    """``\\providecommand{\\x}[1]{<body>}`` / ``\\def\\x#1{<body>}`` 取 body 段。"""
    m = re.search(head_pat, src)
    assert m, f"{head_pat} 不在发射体"
    start = m.end()
    depth, i = 1, start
    while depth:
        assert i < len(src), "花括不平衡"
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


def _enclosing_group(text: str, pos: int) -> tuple[int, int] | None:
    """最小包含 pos 的花括组 (start, end); 顶层返回 None。"""
    spans: list[tuple[int, int]] = []
    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            spans.append((stack.pop(), i))
    inside = [(s, e) for s, e in spans if s < pos < e]
    return min(inside, key=lambda se: se[1] - se[0]) if inside else None


def _assert_arg_alignment_safe(body: str, needle: str = "#1") -> None:
    """needle 落在花括组内 ⟹ 必须在 ``\\begin{tabular}`` 内层对齐跨距内。"""
    for m in re.finditer(re.escape(needle), body):
        grp = _enclosing_group(body, m.start())
        if grp is None:
            continue
        seg = body[grp[0] : grp[1]]
        off = m.start() - grp[0]
        assert "\\begin{tabular}" in seg[:off], (
            f"{needle} 前无内层 tabular: {seg!r} —— 稿面 \\\\ 将对齐格内炸 Missing}}"
        )
        assert "\\end{tabular}" in seg[off:], f"{needle} 后无内层 tabular: {seg!r}"


# ── 结构断言 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["maketitle", "authorblockN", "authorblockA"])
def test_authorblock_let_bridge(key: str) -> None:
    """三键 polyfill 同带 V1.8a 真件桥 —— \\IEEEauthorblockN/A 在场即 \\let 直通。"""
    poly = _cs_table()[key]["polyfill"]
    assert "\\let\\authorblockN\\IEEEauthorblockN" in poly
    assert "\\let\\authorblockA\\IEEEauthorblockA" in poly


@pytest.mark.parametrize("key", ["maketitle", "authorblockN", "authorblockA"])
def test_authorblock_a_arg_alignment_safe(key: str) -> None:
    """\\authorblockA 发射体 #1 不得囚在非 tabular 花括组 (Missing} 级联形)。"""
    body = _def_body(
        _cs_table()[key]["polyfill"], r"\\providecommand\{\\authorblockA\}\[1\]\{"
    )
    _assert_arg_alignment_safe(body)


def test_authorblock_n_arg_alignment_safe() -> None:
    """\\authorblockN 发射体 #1 同查 (裸 #1 / tabular 皆合法)。"""
    for key in ("maketitle", "authorblockN"):
        body = _def_body(
            _cs_table()[key]["polyfill"], r"\\providecommand\{\\authorblockN\}\[1\]\{"
        )
        _assert_arg_alignment_safe(body)


def test_crckapb_institute_arg_alignment_safe() -> None:
    """crckapb.cls shim ``\\institute`` 发射体 #1 同查 (9901364 三行机构实证)。"""
    body = _def_body(_shim_map()["crckapb.cls"]["body"], r"\\def\\institute#1\{")
    _assert_arg_alignment_safe(body)


def test_aipproc_addr_inner_tabular() -> None:
    """aipproc.cls ``\\\\{...addr...}`` 组内 \\fixaip@addr 必在内层 tabular。"""
    stub = (VENDOR / "stubs" / "aipproc.cls").read_text(encoding="utf-8")
    m = re.search(r"\\\\\{", stub)
    assert m, "addr 前缀 \\\\{ 组不在"
    grp = _enclosing_group(stub, m.end())
    assert grp is not None
    seg = stub[grp[0] : grp[1]]
    assert "\\begin{tabular}" in seg, f"aipproc addr 组缺内层 tabular 开: {seg!r}"
    assert "\\fixaip@addr" in seg, f"aipproc addr cs 不在组内: {seg!r}"
    assert "\\end{tabular}" in seg, f"aipproc addr 组缺内层 tabular 收: {seg!r}"


# ── 真编译 e2e (transform 注入链 + 发射体原文) ────────────────────


def _xelatex(wdir: Path) -> str:
    xelatex = shutil.which("xelatex")
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [xelatex, "-interaction=nonstopmode", "main.tex"],
        cwd=wdir,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return (wdir / "main.log").read_text(encoding="utf-8", errors="replace")


def _n_err(log: str) -> int:
    return len(re.findall(r"^! ", log, re.MULTILINE))


_IEEE_DOC = (
    "\\documentclass[conference]{IEEEtran}\n"
    "\\title{T}\n"
    "\\author{\\authorblockN{Halyun Jeong and Young-Han Kim}\n"
    "\\authorblockA{Dept. of ECE, UCSD\\\\\nEmail: {hajeong, yhk}@ucsd.edu}}\n"
    "\\begin{document}\n\\maketitle\nx\n\\end{document}\n"
)


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
@pytest.mark.skipif(shutil.which("kpsewhich") is None, reason="kpsewhich not installed")
def test_authorblock_ieeetran_e2e(tmp_path: Path) -> None:
    """payload authorblockA → polyfill 注 docclass 缝 → IEEEtran \\\\-bearing
    \\authorblockA 零 ``!`` 错 (0905.1990/1404.0346 格形, \\let 桥臂)。"""
    kpsewhich = shutil.which("kpsewhich")
    assert kpsewhich is not None  # skipif 已守卫, 此取绝对路径喂 S607
    if subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [kpsewhich, "IEEEtran.cls"], capture_output=True, check=False
    ).returncode:
        pytest.skip("IEEEtran.cls 不在 texmf")
    (tmp_path / "main.tex").write_text(_IEEE_DOC)
    ok, note = TRANSFORM_FNS["cs_targeted_fix"](
        _ctx(tmp_path), _Eng(), "authorblockA", _cs_table_params()
    )
    assert ok, note
    log = _xelatex(tmp_path)
    assert _n_err(log) == 0, f"注入后仍 {_n_err(log)} 个 '!' 错"


def _cs_table_params() -> dict:
    return next(r for r in _rs().rules if r.id == "cs_targeted_fix").action["params"]


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_authorblock_fallback_e2e(tmp_path: Path) -> None:
    """article 面 (\\IEEEauthorblockA 缺席) → else 臂内层 tabular 零 ``!`` 错。"""
    doc = _IEEE_DOC.replace("[conference]{IEEEtran}", "{article}")
    (tmp_path / "main.tex").write_text(doc)
    ok, note = TRANSFORM_FNS["cs_targeted_fix"](
        _ctx(tmp_path), _Eng(), "authorblockA", _cs_table_params()
    )
    assert ok, note
    log = _xelatex(tmp_path)
    assert _n_err(log) == 0, f"fallback 臂仍 {_n_err(log)} 个 '!' 错"


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_crckapb_institute_e2e(tmp_path: Path) -> None:
    """shim_map 发射 crckapb.cls + 双 \\institute 多行机构 → 零 ``!`` 错
    (astro-ph/9901364 格形)。"""
    (tmp_path / "crckapb.cls").write_text(_shim_map()["crckapb.cls"]["body"])
    (tmp_path / "main.tex").write_text(
        "\\documentclass{crckapb}\n"
        "\\title{Topology of the Universe}\n"
        "\\author{Jean-Pierre Luminet$^1$}\n"
        "\\author{Boudewijn F. Roukema$^{2,3}$}\n"
        "\\institute{$^1$ DARC,\nObservatoire de Paris-Meudon, "
        "5 place Jules Janssen, \\\\\nF-92195 Meudon Cedex, France}\n"
        "\\institute{$^2$Institut d'Astrophysique de Paris\\\\\n"
        "$^3$IUCAA, Post Bag 4\\\\ Ganeshkhind, Pune, India}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    log = _xelatex(tmp_path)
    assert _n_err(log) == 0, f"crckapb shim 仍 {_n_err(log)} 个 '!' 错"
