r"""``texlate.e2e._scan_tree`` 文件闸契约 fuzz——三 runner 共享扫描段的分流不变量。

背景（★3 收敛 2026-09-17，a08dda3+1c55602）：``e2e_real_bench.translate_tree``
与 ``stage_xlat._translate_tree`` 此前各自内联扫描——real 臂零闸把 support 件
（pstricks/宏件/gnuplot 转储）送进网关烧配额且译文腐蚀源码，内联件还漏
``.TEX``/``.RTX.TEX`` 大写形、support 只记 basename 丢子目录路径。现已全收敛到
``e2e._scan_tree`` 单源——本文件把四级分流闸、键名契约与调用接线钉成回归网。

闸序（源码序即语义序——先文件名闸再解析闸，逐钉）：

1. dotfile（``name.startswith(".")``）静默跳过——不进任何输出表；
2. ``*.rtx.tex``（``name.lower()`` 判定）静默跳过——REVTeX 运行时转储；
3. ``*.code.tex`` → ``support_files``——tikzlibrary 机制件硬抛，**不解析**
   （装真散文也拦下，闸只看名不看内容）；
4. ``parse_file`` 崩 → ``fault_files``——单文件崩不拖垮整树，原文保留；
5. 解析出但 ``file_has_prose`` False → ``support_files``——有意跳过而非
   失败（空文件/纯宏件同路：零块即零散文）；
6. 枚举面 ``is_file`` + ``suffix.lower() == ".tex"``：``.TEX`` 大写收录、
   ``x.tex/`` 目录滤掉、``.txt``/``.tex~``/``.tex.bak`` 不进枚举；
7. ``chunk_id = "{scan_idx}:{chunk.id}"``——scan_idx 是 ``scans`` 下标
   （``sorted(rglob)`` 序稳定），cid 是该文件 ``ScanResult.chunks`` 的 id；
8. support/fault 记名 = root 相对 posix——嵌套子目录带 ``/``，非 basename。
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import TYPE_CHECKING

import pytest

from texlate import e2e
from texlate.xlat.pipeline import MockTranslator, PipelineConfig

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from texlate.latex.model import ScanResult

#: 真散文段——distinct 功能词 ≥3（the/and/with/for/here），file_has_prose=True。
_PROSE = (
    "This is a real sentence with enough prose words to pass the gate.\n"
    "Another line of English prose here for good measure and clarity.\n"
)
#: 宏件体——出 para chunk 但零功能词命中，file_has_prose=False。
_MACROS = "\\newcommand{\\zz}{b}\n\\psset{unit=1cm}\npstverb moveto neg def set\n"
#: 三 runner 共享的闸记名键（translate stats 契约面）。
_GATE_KEYS = ("fault_files", "support_files", "support_skipped")
_CID_RX = re.compile(r"^\d+:\d+$")


def _write(root: Path, rel: str, text: str) -> Path:
    """``root/rel`` 写文件（父目录随需建）；返回该路径。"""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _crash_on(monkeypatch: pytest.MonkeyPatch, names: set[str]) -> None:
    """``e2e.parse_file`` 换成按文件名崩的版本——fault 闸原料（真输入探针不崩）。"""
    real_parse = e2e.parse_file

    def flaky(path: Path, **kw: object) -> ScanResult:
        if path.name in names:
            msg = "simulated parse crash"
            raise RuntimeError(msg)
        return real_parse(path, **kw)

    monkeypatch.setattr(e2e, "parse_file", flaky)


def _mega_tree(root: Path) -> dict[str, list[str]]:
    """单树铺全闸（star3-smoke 布局放大版）；返回期望分流表。

    期望序按 ``sorted`` Path 枚举序手推——``scans``/``fault``/``support``
    三表断言钉的就是这个序。
    """
    _write(root, ".hidden.tex", _PROSE)
    _write(root, ".secret.code.tex", _PROSE)
    _write(root, "PAPER.TEX", _PROSE)
    _write(root, "aps.rtx.tex", _PROSE)
    _write(root, "broken.tex", "anything goes here\n")
    (root / "dirlike.tex").mkdir()  # *.tex 目录伪装——is_file 闸滤掉
    _write(root, "dirlike.tex/inner.tex", _PROSE)  # 叶文件仍枚举（闸只查叶）
    _write(root, "empty.tex", "")
    _write(root, "hasprose.code.tex", _PROSE)
    _write(root, "helper.code.tex", _MACROS)
    _write(root, "mac.tex", _MACROS)
    _write(root, "main.tex", _PROSE)
    # 非 .tex：不进枚举（suffix 闸）
    _write(root, "backup.tex~", _PROSE)
    _write(root, "main.tex.bak", _PROSE)
    _write(root, "notes.txt", _PROSE)
    _write(root, "figure.eps", "%!PS-Adobe moveto\n")
    _write(root, "weird.code.rtx.tex", _PROSE)  # rtx 闸在 code 闸前——静默
    _write(root, "sub/.hidden2.tex", _PROSE)
    _write(root, "sub/TIKZLIB.CODE.TEX", _MACROS)
    _write(root, "sub/UP.RTX.TEX", _PROSE)
    _write(root, "sub/broken2.tex", "nested crash\n")
    _write(root, "sub/deep/nest.tex", _PROSE)
    _write(root, "sub/defs.tex", _MACROS)
    _write(root, "sub/inner.tex", _PROSE)
    (root / "sub/dir2.tex").mkdir()
    return {
        "scans": [
            "PAPER.TEX",
            "dirlike.tex/inner.tex",
            "main.tex",
            "sub/deep/nest.tex",
            "sub/inner.tex",
        ],
        "faults": ["broken.tex", "sub/broken2.tex"],
        "support": [
            "empty.tex",
            "hasprose.code.tex",
            "helper.code.tex",
            "mac.tex",
            "sub/TIKZLIB.CODE.TEX",
            "sub/defs.tex",
        ],
        "silent": [
            ".hidden.tex",
            ".secret.code.tex",
            "aps.rtx.tex",
            "sub/.hidden2.tex",
            "sub/UP.RTX.TEX",
            "weird.code.rtx.tex",
        ],
    }


def _gate_tree(root: Path) -> dict[str, list[str]]:
    """runner 契约用小树——三类记名各至少一条 + 嵌套路径。"""
    _write(root, ".hidden.tex", _PROSE)
    _write(root, "aps.rtx.tex", _PROSE)
    _write(root, "broken.tex", "anything\n")
    _write(root, "helper.code.tex", _MACROS)
    _write(root, "mac.tex", _MACROS)
    _write(root, "main.tex", _PROSE)
    _write(root, "sub/defs.tex", _MACROS)
    _write(root, "sub/inner.tex", _PROSE)
    return {
        "scans": ["main.tex", "sub/inner.tex"],
        "faults": ["broken.tex"],
        "support": ["helper.code.tex", "mac.tex", "sub/defs.tex"],
    }


class _StubTranslator(MockTranslator):
    """``MockTranslator`` + ``.model``（e2e_real 的 StateStore 绑定要 model 名）。"""

    model = "stub-model"


def _scan_spy(
    monkeypatch: pytest.MonkeyPatch, mod: object, orig: Callable[..., object]
) -> list[Path]:
    """``mod._scan_tree`` 换成记录壳（from-import 绑定者须打自家模块属性）。"""
    calls: list[Path] = []

    def spy(root: Path) -> object:
        calls.append(root)
        return orig(root)

    monkeypatch.setattr(mod, "_scan_tree", spy)
    return calls


# ---------------------------------------------------------------- 单树全闸


def test_scan_tree_mega_tree_all_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一棵树铺满全部闸：分流表逐表钉死 + 静默件任何表不留名。"""
    exp = _mega_tree(tmp_path)
    _crash_on(monkeypatch, {"broken.tex", "broken2.tex"})
    scans, chunks, faults, support = e2e._scan_tree(tmp_path)  # noqa: SLF001

    assert [f.relative_to(tmp_path).as_posix() for f, _ in scans] == exp["scans"]
    assert faults == exp["faults"]
    assert support == exp["support"]

    seen = {f.relative_to(tmp_path).as_posix() for f, _ in scans}
    seen |= set(faults) | set(support)
    for rel in exp["silent"]:
        assert rel not in seen  # 静默件：扫描/记名两边都不出现

    # chunk_id 命名空间契约：{scan_idx}:{chunk.id}、fidx 单调、逐文件全覆盖
    assert all(_CID_RX.match(c.chunk_id) for c in chunks)
    fidxs = [int(c.chunk_id.partition(":")[0]) for c in chunks]
    assert fidxs == sorted(fidxs)
    expected_ids = {
        f"{i}:{c.id}" for i, (_f, res) in enumerate(scans) for c in res.chunks
    }
    assert {c.chunk_id for c in chunks} == expected_ids
    by_fidx: dict[int, dict[int, str]] = {}
    for ci in chunks:
        a, _, b = ci.chunk_id.partition(":")
        by_fidx.setdefault(int(a), {})[int(b)] = ci.content
    for i, (_f, res) in enumerate(scans):
        assert by_fidx.get(i, {}) == {c.id: c.content for c in res.chunks}


def test_scan_tree_empty_tree(tmp_path: Path) -> None:
    """空树 → 四空表。"""
    assert e2e._scan_tree(tmp_path) == ([], [], [], [])  # noqa: SLF001


def test_scan_tree_all_support_no_scans(tmp_path: Path) -> None:
    """全树无散文（空件 + 宏件 + .code.tex）→ scans/chunks 空、全落 support。"""
    _write(tmp_path, "a/empty.tex", "")
    _write(tmp_path, "b/mac.tex", _MACROS)
    _write(tmp_path, "c/lib.code.tex", _PROSE)
    scans, chunks, faults, support = e2e._scan_tree(tmp_path)  # noqa: SLF001

    assert scans == []
    assert chunks == []
    assert faults == []
    assert support == ["a/empty.tex", "b/mac.tex", "c/lib.code.tex"]


def test_scan_tree_only_non_tex(tmp_path: Path) -> None:
    """纯非 .tex 树（含 .tex 目录伪装）→ 四空表，零枚举。"""
    _write(tmp_path, "a.txt", _PROSE)
    _write(tmp_path, "b.sty", _MACROS)
    _write(tmp_path, "c.tex.bak", _PROSE)
    (tmp_path / "d.tex").mkdir()
    assert e2e._scan_tree(tmp_path) == ([], [], [], [])  # noqa: SLF001


def test_scan_tree_scans_follow_sorted_order(tmp_path: Path) -> None:
    """建序乱序不影响扫描序——``sorted`` 枚举序即 ``scans`` 下标序。"""
    _write(tmp_path, "z2.tex", _PROSE)
    _write(tmp_path, "a1.tex", _PROSE)
    _write(tmp_path, "m9.tex", _PROSE)
    scans, chunks, _f, _s = e2e._scan_tree(tmp_path)  # noqa: SLF001

    assert [f.name for f, _ in scans] == ["a1.tex", "m9.tex", "z2.tex"]
    assert {c.chunk_id.split(":")[0] for c in chunks} == {"0", "1", "2"}
    assert all(c.chunk_id.startswith("0:") for c in chunks[: len(scans[0][1].chunks)])


# ---------------------------------------------------------------- 闸序钉


def test_scan_tree_gate_ordering_pins(tmp_path: Path) -> None:
    """闸序语义：dotfile > rtx > code > parse > prose——重排即破约。

    ``.secret.code.tex``：dotfile 闸先中 → 静默（若 code 闸前移则落 support）；
    ``x.code.rtx.tex``：rtx 闸先中 → 静默（code 闸前移则落 support）；
    ``prose.code.tex``：code 闸不看内容 → 真散文照样 support；
    ``UP.RTX.TEX``/``X.CODE.TEX``：文件名闸均 lower 后判定。
    """
    _write(tmp_path, ".secret.code.tex", _PROSE)
    _write(tmp_path, "x.code.rtx.tex", _PROSE)
    _write(tmp_path, "prose.code.tex", _PROSE)
    _write(tmp_path, "UP.RTX.TEX", _PROSE)
    _write(tmp_path, "X.CODE.TEX", _MACROS)
    _write(tmp_path, "main.tex", _PROSE)
    scans, _c, faults, support = e2e._scan_tree(tmp_path)  # noqa: SLF001

    assert [f.name for f, _ in scans] == ["main.tex"]
    assert faults == []
    assert support == ["X.CODE.TEX", "prose.code.tex"]


# ---------------------------------------------------------------- runner 契约


def test_bench_runners_bind_same_scan_tree() -> None:
    """三 runner 持同一函数对象——from-import 绑定没漂回内联副本。"""
    erb = pytest.importorskip("e2e_real_bench")
    sx = pytest.importorskip("stage_xlat")
    emb = pytest.importorskip("e2e_mock_bench")

    assert erb._scan_tree is e2e._scan_tree  # noqa: SLF001
    assert sx._scan_tree is e2e._scan_tree  # noqa: SLF001
    assert emb.e2e_mod._scan_tree is e2e._scan_tree  # noqa: SLF001


def test_e2e_translate_tree_gate_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """产品臂 ``mock_translate_tree``：闸键齐 + 记名与直扫一致 + 真调 _scan_tree。"""
    exp = _gate_tree(tmp_path)
    _crash_on(monkeypatch, {"broken.tex"})
    calls = _scan_spy(monkeypatch, e2e, e2e._scan_tree)  # noqa: SLF001

    stats = e2e.mock_translate_tree(tmp_path)

    assert calls == [tmp_path]  # 模块全局名查找——补丁生效即证明走 _scan_tree
    for k in _GATE_KEYS:
        assert k in stats
    assert stats["fault_files"] == exp["faults"]
    assert stats["support_files"] == exp["support"]
    assert stats["support_skipped"] == len(exp["support"])


def test_e2e_mock_bench_translate_tree_gate_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bench mock 臂同契约：stats 三键 + ``e2e_mod._scan_tree`` 属性查找可钩。"""
    emb = pytest.importorskip("e2e_mock_bench")
    work = tmp_path / "w"
    exp = _gate_tree(work)
    _crash_on(monkeypatch, {"broken.tex"})
    calls = _scan_spy(monkeypatch, e2e, e2e._scan_tree)  # noqa: SLF001

    stats, _run, _results = emb.translate_tree(work, MockTranslator())

    assert calls == [work]
    for k in _GATE_KEYS:
        assert k in stats
    assert stats["fault_files"] == exp["faults"]
    assert stats["support_files"] == exp["support"]
    assert stats["support_skipped"] == len(exp["support"])


def test_e2e_real_bench_translate_tree_gate_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """real 臂（async + StateStore + GatewayTranslator 协议桩）真调 _scan_tree。

    ★3 前此臂零闸——support/fault 键本身就是回归对象，不只取值。
    """
    erb = pytest.importorskip("e2e_real_bench")
    work = tmp_path / "w"
    exp = _gate_tree(work)
    _crash_on(monkeypatch, {"broken.tex"})
    calls = _scan_spy(monkeypatch, erb, erb._scan_tree)  # noqa: SLF001

    stats = asyncio.run(
        erb.translate_tree(work, _StubTranslator(), tmp_path / "st", PipelineConfig())
    )

    assert calls == [work]  # from-import 绑定：打 erb 自家模块属性即中
    for k in _GATE_KEYS:
        assert k in stats
    assert stats["fault_files"] == exp["faults"]
    assert stats["support_files"] == exp["support"]
    assert stats["support_skipped"] == len(exp["support"])
    assert stats["files"] == len(exp["scans"])  # 全 mock 交付 → 全扫描件写回


def test_stage_xlat_translate_tree_gate_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stagerun xlat 臂（async，返回 (stats, results) 二元）同闸契约。"""
    sx = pytest.importorskip("stage_xlat")
    work = tmp_path / "w"
    exp = _gate_tree(work)
    _crash_on(monkeypatch, {"broken.tex"})
    calls = _scan_spy(monkeypatch, sx, sx._scan_tree)  # noqa: SLF001

    stats, results = asyncio.run(
        sx._translate_tree(  # noqa: SLF001
            work, _StubTranslator(), tmp_path / "st", PipelineConfig()
        )
    )

    assert calls == [work]
    for k in _GATE_KEYS:
        assert k in stats
    assert stats["fault_files"] == exp["faults"]
    assert stats["support_files"] == exp["support"]
    assert stats["support_skipped"] == len(exp["support"])
    # 逐块结果只覆盖扫描件块——support/fault 件的 chunk 从未进 pipeline
    assert all(_CID_RX.match(r.chunk_id) for r in results)


# ---------------------------------------------------------------- 随机分区


def test_scan_tree_random_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """随机树分区对拍：oracle 按闸则独立重算期望桶（枚举/排序口径共享已钉）。

    逐枚举行按文件名规则独立分类（dotfile→rtx→code→crash→prose 判序与
    固定夹具互证）；fidx 命名空间与 chunk 全覆盖在此做集合级断言。
    """
    rng = random.Random(20260917)  # noqa: S311 -- 固定种子复现，非密码学
    dirs = ["", "sub", "sub/deep", "a/b/c"]
    kinds = [
        "prose",
        "prose_upper",
        "macros",
        "dotfile",
        "rtx",
        "rtx_upper",
        "code",
        "code_upper",
        "crash",
        "nontex",
        "dir",
    ]
    crash_names: set[str] = set()
    # 生成时登记期望桶——oracle 不从文件名重推分类，与闸实现互独立
    want: dict[str, str] = {}  # rel → scan|fault|support|silent
    for i in range(60):
        d = rng.choice(dirs)
        kind = rng.choice(kinds)
        stem = f"{kind}{i}"
        if kind == "dir":
            (tmp_path / d / f"{stem}.tex").mkdir(parents=True, exist_ok=True)
            continue
        if kind == "nontex":
            _write(tmp_path, f"{d}/{stem}.txt" if d else f"{stem}.txt", _PROSE)
            continue
        name = {
            "prose": f"{stem}.tex",
            "prose_upper": f"{stem}.TEX",
            "macros": f"{stem}.tex",
            "dotfile": f".{stem}.tex",
            "rtx": f"{stem}.rtx.tex",
            "rtx_upper": f"{stem}.RTX.TEX",
            "code": f"{stem}.code.tex",
            "code_upper": f"{stem}.CODE.TEX",
            "crash": f"{stem}.tex",
        }[kind]
        rel = f"{d}/{name}" if d else name
        want[rel] = {
            "prose": "scan",
            "prose_upper": "scan",
            "macros": "support",
            "dotfile": "silent",
            "rtx": "silent",
            "rtx_upper": "silent",
            "code": "support",
            "code_upper": "support",
            "crash": "fault",
        }[kind]
        if kind == "crash":
            crash_names.add(name)
        _write(tmp_path, rel, _PROSE if kind != "macros" else _MACROS)
    _crash_on(monkeypatch, crash_names)

    # oracle：枚举口径共享（is_file+suffix 已由定向用例钉），桶归属生成侧登记
    exp_scan: list[str] = []
    exp_fault: list[str] = []
    exp_support: list[str] = []
    exp_silent: set[str] = set()
    for f in sorted(
        p for p in tmp_path.rglob("*") if p.is_file() and p.suffix.lower() == ".tex"
    ):
        rel = f.relative_to(tmp_path).as_posix()
        bucket = want[rel]
        if bucket == "scan":
            exp_scan.append(rel)
        elif bucket == "fault":
            exp_fault.append(rel)
        elif bucket == "support":
            exp_support.append(rel)
        else:
            exp_silent.add(rel)

    scans, chunks, faults, support = e2e._scan_tree(tmp_path)  # noqa: SLF001

    assert [f.relative_to(tmp_path).as_posix() for f, _ in scans] == exp_scan
    assert faults == exp_fault
    assert support == exp_support
    seen = {*exp_scan, *exp_fault, *exp_support}
    assert exp_silent.isdisjoint(seen)  # 静默件任何表不留名
    expected_ids = {
        f"{i}:{c.id}" for i, (_f, res) in enumerate(scans) for c in res.chunks
    }
    assert {c.chunk_id for c in chunks} == expected_ids
