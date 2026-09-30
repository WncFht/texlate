"""align.py 性质 fuzz——随机合成 PDF / stub reader / 垃圾字节下的结构不变量。

核心不变量：

- ``build_alignment`` 对任意输入不抛（损坏 PDF 按无锚降级 ``kind="pages"``），
  同输入逐字节确定；
- ``kind="landmarks"`` 时：pairs 双侧 ``(page, fraction)`` 各自非降（单调链
  语义），fraction ∈ [0,1]、page ∈ [1, npages]，id 皆为公共锚；regions
  双侧 ``0 ≤ start ≤ end ≤ 1``、id 限 ``figure.*``/``subfigure.*`` 公共锚，
  且按 original ``(page, start)`` 排序；
- ``_reader_landmarks``（stub reader 白盒）：heights 归一全正有限、dests
  页号在界、``page.N`` 锚不入、坏 dest 只丢自身；
- ``_monotonic_chain`` 产出 original 序子序列、translated key 非降、总权
  == 小规模暴力枚举最优（n≤8 全子集 oracle）；
- ``_multiply`` == 3×3 行向量矩阵乘 oracle（恒等/结合/随机等价）；
- ``_category`` 输出恒在 ``_WEIGHT`` 键内且大小写不敏感。

钉住的缺陷（回归测试）：

- ``_dest_yfrac`` 曾只捕 ``(AttributeError, TypeError, ValueError)``——巨型
  整数 ``/Top``（``NumberObject(10**400)``）的 ``float()`` 抛
  ``OverflowError``，穿透 ``_reader_landmarks`` 把整侧锚点提取作废；
  修复后改捕 ``Exception``（逐锚隔离），``test_reader_landmarks_giant_int_top``
  钉回归。

观察钉（pin 当前契约，非缺陷——裁决留负责人）：

- ``extract_landmarks`` 公共入口对垃圾字节/缺路径抛（pypdf 错误系裸逃），
  与 ``build_alignment`` 的吞咽式降级不对称——src 内无调用方。
- ``build_alignment`` 的 pypdf 缺席早退 ``{"kind": "pages"}`` 无
  ``heights`` 键，与常规降级 ``{"kind": "pages", "heights": {...}}``
  形状不齐（web 端 ``heights?.[side]`` 可选链容忍）。
- ``_reader_landmarks`` 的 ``named_destinations`` 抛错时连已算出的
  heights 一并丢——build_alignment 只能按整侧死回退（PLAUSIBLE，见
  tmp/fuzz-texlog/findings.md P3）。
- writer 全收敌意 dest 名（NUL/空/5k 长/Unicode）并原样回环进
  ``pairs[].id`` → JSON 合法转义、前端容忍。
"""

from __future__ import annotations

import itertools
import math
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from _fuzzkit import fuzz_rng
from pypdf import PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import (
    DecodedStreamObject,
    Destination,
    DictionaryObject,
    Fit,
    FloatObject,
    NameObject,
    NullObject,
    NumberObject,
    TextStringObject,
)

from texlate import align
from texlate.align import _WEIGHT, build_alignment, extract_landmarks

if TYPE_CHECKING:
    import random
    from pathlib import Path

PAGE_H = 792.0
_IMG_POOL = [bytes(range(64)) * 3, bytes(range(64, 128)) * 3, b"\x00" * 200]

#: 发生器概率常量（PLR2004：阈值字面量一律提名）。
_P_ROTATE = 0.15
_P_BAD_BOX = 0.08
_P_HAS_PAGE = 0.9
_P_HAS_TYPE = 0.8
_P_JUNK_RAND = 0.3
_P_JUNK_TRUNC = 0.5
_P_JUNK_EMPTY = 0.7
_P_JUNK_DIR = 0.85

#: dest 名池——含 page.N 排除锚、各类前缀、unicode、无点前缀名。
_NAME_POOL = [
    "section.1",
    "section.2",
    "section.3",
    "subsection.1.1",
    "figure.1",
    "figure.2",
    "subfigure.1.1",
    "table.1",
    "equation.5",
    "eq.7",
    "cite.doe20",
    "footnote.2",
    "page.1",
    "page.2",
    "page.9",
    "other.x",
    "数据.1",
    "sec tion.4",
    "FIGURE.9",
    "",
    ".",
    "figure.",
]

#: /Top 值池（经 writer FitH 注入）：负/零/页高/超页高/普通值。
_TOP_POOL = [None, -50.0, 0.0, 1.0, 400.0, PAGE_H, PAGE_H + 1, 1e6]


def _mk_pdf(
    path: Path,
    dests: list[tuple[str, int, float | None]],
    npages: int,
    rng: random.Random,
    arts: list[tuple[int, tuple[float, float, float, float], bytes]] | None = None,
) -> Path:
    """npages 空白页 + FitH/Fit named dests + 可选图像 XObject 落点。"""
    w = PdfWriter()
    for _ in range(npages):
        w.add_blank_page(width=612, height=PAGE_H)
    for i, (pidx, box, payload) in enumerate(arts or []):
        img = DecodedStreamObject()
        img.set_data(payload)
        img.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(8),
                NameObject("/Height"): NumberObject(8),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        page = w.pages[pidx]
        res = page.get("/Resources", DictionaryObject())
        xobj = res.get("/XObject", DictionaryObject())
        xobj[NameObject(f"/Im{i}")] = img
        res[NameObject("/XObject")] = xobj
        page[NameObject("/Resources")] = res
        x, y, aw, ah = box
        cs = DecodedStreamObject()
        cs.set_data(f"q {aw} 0 0 {ah} {x} {y} cm /Im{i} Do Q".encode())
        page[NameObject("/Contents")] = cs
    for name, pidx, top in dests:
        fit = Fit.fit() if top is None else Fit.fit_horizontally(top)
        w.add_named_destination_object(
            Destination(name, w.pages[pidx].indirect_reference, fit)
        )
    if rng.random() < _P_ROTATE and npages:  # 偶发页旋转——regions 映射面
        w.pages[rng.randrange(npages)][NameObject("/Rotate")] = NumberObject(
            rng.choice([90, 180, 270])
        )
    with path.open("wb") as fh:
        w.write(fh)
    return path


def _gen_pdf_spec(
    rng: random.Random, name_pool: list[str]
) -> tuple[list[tuple[str, int, float | None]], list, int]:
    """一份随机 PDF 规格：``(dests, arts, npages)``。"""
    npages = rng.randint(0, 8)
    dests: list[tuple[str, int, float | None]] = []
    arts: list[tuple[int, tuple[float, float, float, float], bytes]] = []
    if npages:
        dests.extend(
            (name, rng.randrange(npages), rng.choice(_TOP_POOL))
            for name in rng.sample(name_pool, min(len(name_pool), rng.randint(0, 12)))
        )
        for _ in range(rng.randint(0, 3)):
            box = (
                rng.uniform(-100, 700),
                rng.uniform(-100, 900),
                rng.choice([0.0, rng.uniform(0, 700)]),
                rng.choice([0.0, rng.uniform(0, 900)]),
            )
            arts.append((rng.randrange(npages), box, rng.choice(_IMG_POOL)))
    return dests, arts, npages


def _check_pos(p: dict[str, Any], npages: int) -> None:
    assert 1 <= p["page"] <= npages
    assert 0.0 <= p["fraction"] <= 1.0


def _check_alignment(
    al: dict[str, Any], na: int | None = None, nb: int | None = None
) -> None:
    """build_alignment 输出结构不变量；na/nb 为期望页数（缺省按 heights 推）。"""
    assert al["kind"] in ("landmarks", "pages")
    heights = al.get("heights", {})
    for side, want in (("original", na), ("translated", nb)):
        if side in heights:
            hs = heights[side]
            if want is not None:
                assert len(hs) == want
            assert all(math.isfinite(h) and h > 0 for h in hs)
    if al["kind"] == "pages":
        assert "pairs" not in al
        assert "regions" not in al
        return
    assert set(heights) == {"original", "translated"}
    npages = {s: len(hs) for s, hs in heights.items()}
    pairs = al["pairs"]
    assert pairs, "landmarks kind 需非空 pairs"
    ids = [p["id"] for p in pairs]
    assert len(set(ids)) == len(ids)
    for side in ("original", "translated"):
        keys = [(p[side]["page"], p[side]["fraction"]) for p in pairs]
        assert keys == sorted(keys), f"{side} 侧锚点非单调"
        for p in pairs:
            _check_pos(p[side], npages[side])
    regions = al.get("regions", [])
    for reg in regions:
        assert reg["id"].startswith(("figure.", "subfigure."))
        for side in ("original", "translated"):
            rc = reg[side]
            assert 1 <= rc["page"] <= npages[side]
            assert 0.0 <= rc["start"] <= rc["end"] <= 1.0
    assert [(r["original"]["page"], r["original"]["start"]) for r in regions] == sorted(
        (r["original"]["page"], r["original"]["start"]) for r in regions
    )


def test_fuzz_build_alignment_random_pdfs(tmp_path: Path) -> None:
    """随机双 PDF（共享锚子集 + 随机 /Top + 图像 XObject + 偶发旋转）：
    输出结构不变量 + 逐字节确定。"""
    rng = fuzz_rng(20260917)
    for i in range(300):
        pool = rng.sample(_NAME_POOL, rng.randint(1, len(_NAME_POOL)))
        a_dests, a_arts, na = _gen_pdf_spec(rng, pool)
        b_dests, b_arts, nb = _gen_pdf_spec(rng, pool)
        try:
            pa = _mk_pdf(tmp_path / f"a{i}.pdf", a_dests, na, rng, a_arts)
            pb = _mk_pdf(tmp_path / f"b{i}.pdf", b_dests, nb, rng, b_arts)
        except Exception:  # noqa: BLE001 -- writer 拒收病态构造时改用垃圾字节
            (tmp_path / f"a{i}.pdf").write_bytes(rng.randbytes(200))
            (tmp_path / f"b{i}.pdf").write_bytes(rng.randbytes(200))
            _check_alignment(
                build_alignment(tmp_path / f"a{i}.pdf", tmp_path / f"b{i}.pdf")
            )
            continue
        al1 = build_alignment(pa, pb)
        al2 = build_alignment(pa, pb)
        assert al1 == al2, f"iter {i}: build_alignment 非确定"
        _check_alignment(al1, na, nb)


def test_fuzz_build_alignment_garbage_inputs(tmp_path: Path) -> None:
    """随机/截断/目录/空文件输入：恒不抛、输出恒合法——pypdf 宽容解析下
    截断前缀仍可能抽出真锚（``landmarks`` 亦合法），只钉结构不变量。"""
    rng = fuzz_rng(20260918)
    good = _mk_pdf(tmp_path / "good.pdf", [("section.1", 0, PAGE_H)], 3, rng)
    for i in range(400):
        r = rng.random()
        junk = tmp_path / f"j{i}.pdf"
        if r < _P_JUNK_RAND:
            junk.write_bytes(rng.randbytes(rng.randint(0, 2000)))
        elif r < _P_JUNK_TRUNC:
            raw = good.read_bytes()
            junk.write_bytes(raw[: rng.randrange(len(raw))])
        elif r < _P_JUNK_EMPTY:
            junk.write_bytes(b"")
        elif r < _P_JUNK_DIR:
            junk.mkdir()  # 路径落为目录
        else:
            junk.write_bytes(b"%PDF-1.4 garbage " + rng.randbytes(100))
        _check_alignment(build_alignment(junk, good))
        _check_alignment(build_alignment(good, junk))
        _check_alignment(build_alignment(junk, junk))


def test_build_alignment_missing_paths_never_raise(tmp_path: Path) -> None:
    """不存在路径两侧组合：恒 ``kind="pages"`` 不抛。"""
    rng = fuzz_rng(20260919)
    good = _mk_pdf(tmp_path / "g.pdf", [("section.1", 0, PAGE_H)], 2, rng)
    missing = tmp_path / "nope.pdf"
    assert build_alignment(missing, good)["kind"] == "pages"
    assert build_alignment(good, missing)["kind"] == "pages"
    assert build_alignment(missing, missing)["kind"] == "pages"


# ---------------------------------------------------------------- stub reader 白盒


class _StubPage:
    def __init__(self, height: object = PAGE_H) -> None:
        self.mediabox = SimpleNamespace(height=height)


class _BadBoxPage:
    @property
    def mediabox(self) -> object:
        msg = "corrupt mediabox"
        raise ValueError(msg)


class _StubReader:
    """duck-type PdfReader——畸形 /Top/页高形态 writer 写不出，走对象图直构。"""

    def __init__(self, dests: dict[str, Any], pages: list[object]) -> None:
        self._dests = dests
        self.pages = pages

    @property
    def named_destinations(self) -> dict[str, Any]:
        return self._dests

    @staticmethod
    def get_destination_page_number(dest: object) -> int:
        return int(dest["__p"])  # type: ignore[index]


_HEIGHT_POOL = [PAGE_H, 612.0, 1.0, 1e6, float("nan"), float("inf"), -5.0, 0.0, "junk"]
#: /Top 值池（对象形态直构）——不含巨型整数：``float(10**400)`` 的
#: ``OverflowError`` 逃逸是已钉缺陷（见 test_reader_landmarks_giant_int_top）。
_TOP_OBJ_POOL = [
    FloatObject(400.0),
    FloatObject(-10.0),
    FloatObject(1e9),
    FloatObject(float("nan")),
    FloatObject(float("inf")),
    NumberObject(700),
    NumberObject(-3),
    TextStringObject("junk"),
    TextStringObject("1e999"),
    NullObject(),
    None,  # 缺席 /Top
]
_P_POOL: list[object] = [0, 1, 2, 5, -1, 99, "x", 3.5, None, [0]]


def _gen_stub(rng: random.Random) -> _StubReader:
    """随机 stub reader：随机页列（含坏 mediabox/异型 height）+ 随机 dests。"""
    pages: list[object] = [
        _BadBoxPage()
        if rng.random() < _P_BAD_BOX
        else _StubPage(rng.choice(_HEIGHT_POOL))
        for _ in range(rng.randint(0, 6))
    ]
    dests: dict[str, Any] = {}
    for name in rng.sample(_NAME_POOL, rng.randint(0, len(_NAME_POOL))):
        d: dict[str, Any] = {}
        if rng.random() < _P_HAS_PAGE:
            d["__p"] = rng.choice(_P_POOL)
        top = rng.choice(_TOP_OBJ_POOL)
        if top is not None:
            d["/Top"] = top
        if rng.random() < _P_HAS_TYPE:
            d["/Type"] = rng.choice(["/XYZ", "/FitH", "junk"])
        dests[name] = d
    return _StubReader(dests, pages)


def test_fuzz_reader_landmarks_stub() -> None:
    """stub reader 随机页列+dests：heights 全正有限、dests 页号在界、
    ``page.N`` 不收、yfrac None 或 [0,1]——单 dest 坏不拖整侧。"""
    rng = fuzz_rng(20260920)
    for _ in range(800):
        r = _gen_stub(rng)
        lm = align._reader_landmarks(r)  # noqa: SLF001 -- 白盒钉私有提取
        n = len(r.pages)
        assert lm["npages"] == n
        assert len(lm["heights"]) == n
        assert all(math.isfinite(h) and h > 0 for h in lm["heights"])
        if n:
            assert lm["heights"][0] == pytest.approx(1.0)
        for name, d in lm["dests"].items():
            assert align._PAGE_ANCHOR_RX.match(name) is None  # noqa: SLF001
            assert 1 <= d["page"] <= n
            assert d["yfrac"] is None or 0.0 <= d["yfrac"] <= 1.0
            assert isinstance(d["fit"], str)


def test_reader_landmarks_giant_int_top() -> None:
    """``/Top`` 巨整数（``float()`` → ``OverflowError``）按缺锚处理、只丢
    该锚——曾穿透 ``_dest_yfrac`` 窄捕获表把整侧提取作废（回归钉）。"""
    dests = {
        "section.1": {"/Top": FloatObject(400.0), "__p": 0},
        "giant.1": {"/Top": NumberObject(10**400), "__p": 0},
        "section.2": {"/Top": FloatObject(500.0), "__p": 1},
    }
    lm = align._reader_landmarks(  # noqa: SLF001 -- 白盒钉私有提取
        _StubReader(dests, [_StubPage(), _StubPage()])
    )
    assert set(lm["dests"]) == {"section.1", "giant.1", "section.2"}
    assert lm["dests"]["giant.1"]["yfrac"] is None


# ---------------------------------------------------------------- monotonic chain oracle


def _brute_chain_weight(items: list[tuple[str, dict, dict]]) -> int:
    """小规模暴力 oracle：original 序全子集枚举 translated-key 非降的最大权。"""
    bkeys = [align._order_key(it[2]) for it in items]  # noqa: SLF001
    wts = [_WEIGHT[align._category(it[0])] for it in items]  # noqa: SLF001
    best = 0
    for r in range(len(items) + 1):
        for combo in itertools.combinations(range(len(items)), r):
            if all(bkeys[a] <= bkeys[b] for a, b in itertools.pairwise(combo)):
                best = max(best, sum(wts[k] for k in combo))
    return best


def test_fuzz_monotonic_chain_optimality() -> None:
    """n≤8 随机 commons：DP 链权 == 全子集枚举最优；链是 original 序
    子序列且 translated ``(page, -yfrac)`` 非降。"""
    rng = fuzz_rng(20260921)
    for _ in range(600):
        commons = [
            (
                rng.choice(_NAME_POOL) + str(j),
                {
                    "page": rng.randint(1, 6),
                    "yfrac": rng.choice([None, rng.uniform(-0.5, 1.5)]),
                },
                {
                    "page": rng.randint(1, 6),
                    "yfrac": rng.choice([None, rng.uniform(-0.5, 1.5)]),
                },
            )
            for j in range(rng.randint(0, 8))
        ]
        sorted_items = sorted(commons, key=lambda t: align._order_key(t[1]))  # noqa: SLF001
        chain = align._monotonic_chain(commons)  # noqa: SLF001
        by_name = {it[0]: it for it in commons}
        order = {id(it): k for k, it in enumerate(sorted_items)}
        positions = [order[id(by_name[n])] for n in chain]
        assert positions == sorted(positions), "链非 original 序子序列"
        assert len(set(positions)) == len(positions), "链含重复锚"
        bkeys = [align._order_key(by_name[n][2]) for n in chain]  # noqa: SLF001
        assert all(a <= b for a, b in itertools.pairwise(bkeys)), "链 translated 侧乱序"
        got = sum(_WEIGHT[align._category(n)] for n in chain)  # noqa: SLF001
        assert got == _brute_chain_weight(sorted_items), (
            f"链权 {got} != 最优 {_brute_chain_weight(sorted_items)}"
        )


# ---------------------------------------------------------------- _multiply oracle


def _matmul33(
    m1: tuple[tuple[float, ...], ...], m2: tuple[tuple[float, ...], ...]
) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(sum(m1[i][k] * m2[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )


def _to33(m: tuple[float, ...]) -> tuple[tuple[float, ...], ...]:
    """PDF 仿射 (a,b,c,d,e,f) → 行向量约定 3×3 ``[[a,b,0],[c,d,0],[e,f,1]]``。"""
    a, b, c, d, e, f = m
    return ((a, b, 0.0), (c, d, 0.0), (e, f, 1.0))


def _from33(m: tuple[tuple[float, ...], ...]) -> tuple[float, ...]:
    return (m[0][0], m[0][1], m[1][0], m[1][1], m[2][0], m[2][1])


_IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def test_fuzz_multiply_matches_3x3_oracle() -> None:
    """``_multiply(f, s)`` == 行向量 3×3 乘 f×s；恒等元 + 结合律 + 随机等价。"""
    rng = fuzz_rng(20260922)
    for _ in range(2000):
        f = tuple(rng.uniform(-100, 100) for _ in range(6))
        s = tuple(rng.uniform(-100, 100) for _ in range(6))
        assert align._multiply(f, _IDENT) == pytest.approx(f)  # noqa: SLF001
        assert align._multiply(_IDENT, f) == pytest.approx(f)  # noqa: SLF001
        assert align._multiply(f, s) == pytest.approx(  # noqa: SLF001
            _from33(_matmul33(_to33(f), _to33(s)))
        )
        t = tuple(rng.uniform(-10, 10) for _ in range(6))
        assert align._multiply(align._multiply(f, s), t) == pytest.approx(  # noqa: SLF001
            align._multiply(f, align._multiply(s, t))  # noqa: SLF001
        )


# ---------------------------------------------------------------- _category


def test_fuzz_category_outputs() -> None:
    """任意名 → 恒在 ``_WEIGHT`` 键内；大小写不敏感。"""
    rng = fuzz_rng(20260923)
    alphabet = list("seciontublfigqraphzy.0123456789数据中_-.")
    for _ in range(3000):
        name = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 25)))
        cat = align._category(name)  # noqa: SLF001
        assert cat in _WEIGHT
        assert align._category(name.upper()) == cat  # noqa: SLF001


def test_category_prefix_table() -> None:
    """前缀归类钉点：各权重族代表名 + 大小写变体。"""
    cases = {
        "section.1": "section",
        "Section.2": "section",
        "subsection.1": "section",
        "chapter.3": "section",
        "figure.1": "figtable",
        "fig.2": "figtable",
        "table.4": "figtable",
        "tab1": "figtable",
        "equation.7": "equation",
        "eq.3": "equation",
        "cite.a": "cite",
        "citealp.b": "cite",
        "footnote.1": "footnote",
        "hfootnote.2": "footnote",
        "page.3": "other",
        "数据": "other",
        "": "other",
    }
    for name, want in cases.items():
        assert align._category(name) == want, name  # noqa: SLF001


# ---------------------------------------------------------------- 降级形状钉


def test_build_alignment_both_dead_heights_empty(tmp_path: Path) -> None:
    """双侧都不可读 → ``{"kind":"pages","heights":{}}``——heights 键在但空。"""
    bad1 = tmp_path / "b1.pdf"
    bad2 = tmp_path / "b2.pdf"
    bad1.write_bytes(b"garbage one")
    bad2.write_bytes(b"garbage two")
    assert build_alignment(bad1, bad2) == {"kind": "pages", "heights": {}}


def test_build_alignment_one_dead_keeps_survivor_heights(tmp_path: Path) -> None:
    """一侧坏掉 → ``pages`` 降级但存活侧真实 ``heights`` 保留。"""
    rng = fuzz_rng(20260924)
    good = _mk_pdf(tmp_path / "g.pdf", [("section.1", 0, PAGE_H)], 3, rng)
    bad = tmp_path / "b.pdf"
    bad.write_bytes(b"%PDF-1.4 truncated")
    al = build_alignment(bad, good)
    assert al == {
        "kind": "pages",
        "heights": {"translated": [1.0, 1.0, 1.0]},
    }


def test_pypdf_absent_bare_pages_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """观察钉：pypdf 缺席 → ``{"kind":"pages"}`` 无 ``heights`` 键。

    与常规降级 ``{"kind":"pages","heights":{...}}`` 形状不齐——web 端
    ``heights?.[side]`` 可选链容忍，属防御面不齐非功能缺陷。
    """
    monkeypatch.setitem(sys.modules, "pypdf", None)
    rng = fuzz_rng(20260925)
    a = _mk_pdf(tmp_path / "a.pdf", [("section.1", 0, PAGE_H)], 2, rng)
    assert build_alignment(a, a) == {"kind": "pages"}


def test_zero_page_pdf(tmp_path: Path) -> None:
    """0 页 PDF：landmarks 空视图 + ``pages`` 降级，heights 双侧空表。"""
    z = tmp_path / "z.pdf"
    w = PdfWriter()
    with z.open("wb") as fh:
        w.write(fh)
    lm = extract_landmarks(z)
    assert lm == {"dests": {}, "heights": [], "npages": 0}
    assert build_alignment(z, z) == {
        "kind": "pages",
        "heights": {"original": [], "translated": []},
    }


def test_extract_landmarks_unreadable_raises(tmp_path: Path) -> None:
    """观察钉：公共入口对垃圾字节/缺路径裸抛——与 ``build_alignment``
    吞咽式降级不对称（src 内无调用方，bench/测试才用）。"""
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(PdfReadError):
        extract_landmarks(bad)
    with pytest.raises(FileNotFoundError):
        extract_landmarks(tmp_path / "missing.pdf")


# ---------------------------------------------------------------- 敌意 dest 名


def test_hostile_dest_names_roundtrip(tmp_path: Path) -> None:
    """NUL/空/超长/Unicode dest 名经 writer 回环原样进 dests→pairs[].id。

    观察钉：JSON 序列化对 NUL/换行合法转义，前端按 str key 容忍——
    但锚名不做任何净化即进 dual.json 载荷，值得留档。
    """
    names = ["", "a\x00b", "x" * 5000, "锚.1", "fig\nure", "..", " figure.2"]
    dests = [(n, 0, PAGE_H) for n in names]
    rng = fuzz_rng(20260926)
    a = _mk_pdf(tmp_path / "a.pdf", dests, 2, rng)
    lm = extract_landmarks(a)
    assert set(names) <= set(lm["dests"])
    al = build_alignment(a, a)
    assert al["kind"] == "landmarks"
    ids = [p["id"] for p in al["pairs"]]
    assert "a\x00b" in ids
    assert "" in ids


# ---------------------------------------------------------------- _dest_yfrac 直测


@pytest.mark.parametrize(
    "top",
    [
        None,
        0,
        -1.0,
        PAGE_H,
        1e9,
        float("nan"),
        float("inf"),
        "x",
        b"2",
        [1],
        {"a": 1},
        True,
    ],
    ids=[
        "none",
        "zero",
        "neg",
        "page_h",
        "huge",
        "nan",
        "inf",
        "str",
        "bytes",
        "list",
        "dict",
        "bool",
    ],
)
def test_dest_yfrac_hostile_values(top: object) -> None:
    """``/Top`` 敌意值恒收 ``None`` 或 [0,1]——逐锚隔离不抛。"""
    out = align._dest_yfrac({"/Top": top}, PAGE_H)  # noqa: SLF001
    assert out is None or 0.0 <= out <= 1.0


def test_dest_yfrac_zero_height() -> None:
    """height=0 除零亦被 except 收——内部调用方恒 >0，直测兜底。"""
    assert align._dest_yfrac({"/Top": 5.0}, 0.0) is None  # noqa: SLF001


# ---------------------------------------------------------------- 私有面崩坏隔离


class _DestsBoomReader:
    """named_destinations 抛错的 stub reader——heights 可算但整侧丢。"""

    def __init__(self, pages: list[object]) -> None:
        self.pages = pages

    @property
    def named_destinations(self) -> dict[str, Any]:
        msg = "names tree corrupt"
        raise RuntimeError(msg)

    @staticmethod
    def get_destination_page_number(dest: object) -> int:  # noqa: ARG004
        return 0


def test_reader_landmarks_dests_boom_keeps_heights() -> None:
    """P3 回归：``named_destinations`` 抛 → 锚段置空但 heights 存活——
    build_alignment 保页序信息而非整侧死回退。"""
    r = _DestsBoomReader([_StubPage(), _StubPage()])
    lm = align._reader_landmarks(r)  # noqa: SLF001 -- 白盒钉私有提取
    assert lm["dests"] == {}
    assert len(lm["heights"]) == len(r.pages)
    assert lm["npages"] == len(r.pages)


class _BoomPage:
    """``get_inherited`` 裸炸的页——``_graphic_regions`` 上半段在 try 外。"""

    def get_inherited(self, _key: str, _default: object = None) -> object:
        msg = "resources boom"
        raise RuntimeError(msg)


def test_match_figure_regions_page_crash_isolated() -> None:
    """单页 content 解析崩只丢该页 regions——``_match_figure_regions``
    的 per-page try 把 ``_graphic_regions`` 任意异常收成空表。"""
    readers = {
        "original": SimpleNamespace(pages=[_BoomPage()]),
        "translated": SimpleNamespace(pages=[_BoomPage()]),
    }
    commons = [
        (
            "figure.1",
            {"page": 1, "yfrac": 0.5, "fit": "?"},
            {"page": 1, "yfrac": 0.5, "fit": "?"},
        )
    ]
    assert align._match_figure_regions(readers, commons) == []  # noqa: SLF001


def test_match_figure_regions_skips_non_figure_and_none() -> None:
    """region 归属只认 figure.*/subfigure.* 且双侧 yfrac 非 None。"""
    readers = {
        "original": SimpleNamespace(pages=[_BoomPage()]),
        "translated": SimpleNamespace(pages=[_BoomPage()]),
    }
    commons = [
        ("table.1", {"page": 1, "yfrac": 0.5}, {"page": 1, "yfrac": 0.5}),
        ("figure.2", {"page": 1, "yfrac": None}, {"page": 1, "yfrac": 0.5}),
    ]
    assert align._match_figure_regions(readers, commons) == []  # noqa: SLF001
