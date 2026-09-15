"""dual.json ``alignment`` 段产出——en/zh PDF named-dest 锚点对齐（web-layer §5.4）。

阅读器滚动同步的锚点映射（texglot 方案）：双 PDF 各抽 hyperref named
destinations（``section.N``/``figure.N``/``cite.*`` 等），按锚点名配对后
取**最大权单调子序列**——乱序锚会让前端二分插值错向，宁丢勿乱。
页内 ``fraction`` 一律自顶向下 0..1；PDF ``/Top`` 是底向上坐标，这里翻转。
无公共锚时退化 ``kind="pages"``（前端同页码映射）。``regions``（图浮动块
区间）需要块界信息，named dest 只是点锚，暂不产出。

移植自 ``bench/py/alignbench.py`` 的 dest 抽取与链权 DP（B7 同源逻辑，
那边是评测 verdict，这边是产出侧 payload）。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["build_alignment", "extract_landmarks"]

#: hyperref 自动页锚 ``page.N``——只是页码，对锚点同步无信息量，单列不计。
_PAGE_ANCHOR_RX = re.compile(r"^page\.\d+$")

#: 类别权重（docs/10 §B7）：section 12 / 图表 10 / equation 4 / cite 2，
#: 与评测侧同表——链越"像目录序"权越高。
_WEIGHT = {
    "section": 12,
    "figtable": 10,
    "equation": 4,
    "cite": 2,
    "footnote": 1,
    "other": 1,
}


def _category(name: str) -> str:
    n = name.lower()
    if n.startswith(
        ("section", "subsection", "subsubsection", "chapter", "part", "paragraph")
    ):
        return "section"
    if n.startswith(("figure", "fig", "table", "tab")):
        return "figtable"
    if n.startswith(("equation", "eq")):
        return "equation"
    if n.startswith("cite"):
        return "cite"
    if n.startswith(("footnote", "hfootnote")):
        return "footnote"
    return "other"


def _dest_page(r: object, dest: object) -> int | None:
    """Dest → 0-based 页号；坏 dest 当缺锚（None），不让整篇作废。"""
    try:
        return r.get_destination_page_number(dest)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 -- pypdf 内部异常类型发散
        return None


def extract_landmarks(path: Path) -> dict[str, Any]:
    """抽一份 PDF 的锚点视图。

    返回 ``{"dests": {name: {"page","yfrac","fit"}}, "heights": [...],
    "npages": int}``；``yfrac`` 是**底向上** 0..1（PDF 原生坐标），heights
    归一化到首页高（首页=1.0）。page.N 锚不入 dests。
    """
    from pypdf import PdfReader  # noqa: PLC0415 -- 重依赖惰性加载

    r = PdfReader(str(path))
    raw_heights = [float(p.mediabox.height) or 792.0 for p in r.pages]
    h0 = raw_heights[0] if raw_heights else 1.0
    heights = [h / h0 for h in raw_heights]
    dests: dict[str, dict[str, Any]] = {}
    for name, dest in r.named_destinations.items():
        if _PAGE_ANCHOR_RX.match(name):
            continue
        page = _dest_page(r, dest)
        if page is None or page < 0 or page >= len(raw_heights):
            continue
        top = dest.get("/Top")
        yfrac = float(top) / raw_heights[page] if top is not None else None
        dests[name] = {
            "page": page + 1,  # 对外 1-based（web Pos.page 语义）
            "yfrac": yfrac,
            "fit": str(dest.get("/Type", "?")),
        }
    return {"dests": dests, "heights": heights, "npages": len(raw_heights)}


def _order_key(d: dict[str, Any]) -> tuple[int, float]:
    """阅读序 key：页号 + 页内自顶向下（底向上 yfrac 越大越靠前）。"""
    return (d["page"], -(d["yfrac"] if d["yfrac"] is not None else 0.0))


def _monotonic_chain(commons: list[tuple[str, dict, dict]]) -> list[str]:
    """按 original 序排序，取 translated 侧 key 非降的最大权子序列（O(n²) DP）。"""
    items = sorted(commons, key=lambda t: _order_key(t[1]))
    bkeys = [_order_key(it[2]) for it in items]
    wts = [_WEIGHT[_category(it[0])] for it in items]
    n = len(items)
    dp = wts[:]
    par = [-1] * n
    for i in range(n):
        for j in range(i):
            if bkeys[j] <= bkeys[i] and dp[j] + wts[i] > dp[i]:
                dp[i] = dp[j] + wts[i]
                par[i] = j
    if n == 0:
        return []
    i = max(range(n), key=lambda k: dp[k])
    chain: list[str] = []
    while i >= 0:
        chain.append(items[i][0])
        i = par[i]
    chain.reverse()
    return chain


def _pos(d: dict[str, Any]) -> dict[str, Any]:
    """Dest 视图 → §5.4 Pos：fraction 翻转为自顶向下 0..1。"""
    y = d["yfrac"]
    return {"page": d["page"], "fraction": round(1.0 - y, 5) if y is not None else 0.0}


def build_alignment(en_pdf: Path, zh_pdf: Path) -> dict[str, Any]:
    """产出 dual.json 的 ``alignment`` 段。

    有公共锚 → ``{"kind":"landmarks","heights":{...},"pairs":[...]}``，
    pairs 为 original 序的单调链（乱序锚丢弃）；无公共锚 →
    ``{"kind":"pages","heights":{...}}`` 让前端退同页映射。
    PDF 损坏/读不动按无锚处理——阅读器降级比任务失败便宜。
    """
    try:
        ea = extract_landmarks(en_pdf)
        eb = extract_landmarks(zh_pdf)
    except Exception:  # noqa: BLE001 -- 截断/加密 PDF 只丢同步精度
        return {"kind": "pages"}
    heights = {"original": ea["heights"], "translated": eb["heights"]}
    commons = [
        (n, ea["dests"][n], eb["dests"][n])
        for n in sorted(set(ea["dests"]) & set(eb["dests"]))
    ]
    chain = _monotonic_chain(commons)
    if not chain:
        return {"kind": "pages", "heights": heights}
    lut = {n: (a, b) for n, a, b in commons}
    pairs = [
        {
            "id": n,
            "original": _pos(lut[n][0]),
            "translated": _pos(lut[n][1]),
        }
        for n in chain
    ]
    return {"kind": "landmarks", "heights": heights, "pairs": pairs}
