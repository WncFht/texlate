"""seqpos/alignment 仿真共用件——mapper_audit/seqpos_e2e_sim/seqpos_clicksim 单一事实源。

- ``create_position_mapper``：web/src/reader/alignment.ts createPositionMapper
  逐行移植——栏感知折序 (col+frac)/2、heights 页高表、dropOutliers 离群锚
  剔除、regions 优先插值、kind="pages" 同页退化。返回函数的 ``.knots``
  外露建后折线/区间表，供审计面量倒置与锯齿。
- ``lin_of/ro_lin/key_of/degrade/nearest``：sentalign.ts/pdfseqpos.ts 键系
  与旧基线 picker。
- ``lit_probes/lit_probe/scan_pages/truth_rects``：search_for 真值探针
  两口径（e2e 多针组 / audit 单针）。
- ``_char_stream``/``_norm_chars``/``_tex_strip``/``_doc_order``/
  ``seqpos_for_task``：``texlate.server.seqpos`` 转口面——tools 消费
  seqpos 一律经本件，私名跨包直连禁（源改名/收口只动本文件）。

生产改版先改源、回头同步本件——脚本里不再长副本。
"""

from __future__ import annotations

import math
import re
from typing import NamedTuple

import _env  # noqa: F401 -- src 登程须先于 texlate import
from texlate.server.seqpos import seqpos_for_task  # noqa: F401 -- 转口面：tools 侧唯一引口
from texlate.server.seqpos.docorder import _doc_order  # noqa: F401
from texlate.server.seqpos.stream import (  # noqa: F401
    _char_stream,
    _norm_chars,
    _tex_strip,
)

COL_X = 0.45  # 栏判定 x 中点契约——与前端 colOf / seqpos._COL_SPLIT_X 同口径


def col_of(p: dict) -> int:
    return 1 if (p.get("x") is not None and p["x"] >= COL_X) else 0


def lin_of(p: dict) -> float:
    return p["page"] + p["fraction"]


def ro_lin(p: dict) -> float:
    """sentalign.ts roLin：page + (col+frac)/2——页内阅读序分位。"""
    return p["page"] + (col_of(p) + p["fraction"]) / 2


def key_of(p: dict) -> tuple:
    return (p["page"], col_of(p), p["fraction"])


def degrade(lands, pos):
    """本页无右栏地标时右半点击退 col0（containingSeq/fracInBlock 同款）。"""
    if (
        pos.get("x") is not None
        and pos["x"] >= COL_X
        and not any(l[1]["page"] == pos["page"] and col_of(l[1]) == 1 for l in lands)
    ):
        return {**pos, "x": 0}
    return pos


def nearest(lands, pos, max_score: float = 1.0):
    """旧 picker 基线：|Δfraction| 最近（同页）/ dpage+ 页沿距（跨页）。"""
    best, bs = None, 1e18
    for k, p in lands:
        dp = abs(p["page"] - pos["page"])
        sc = (
            abs(p["fraction"] - pos["fraction"])
            if dp == 0
            else dp + (1 - p["fraction"] if p["page"] < pos["page"] else p["fraction"])
        )
        if sc < bs:
            bs, best = sc, k
    return best if bs <= max_score else None


# ---------- createPositionMapper（web/src/reader/alignment.ts 逐行移植） ----------


class Geom(NamedTuple):
    pages: int
    h: object  # (page: int) -> float，1-based
    off: list  # off[i] = Σh[0..i-1]，长度 pages+1


def geom_of(heights, pages: int) -> Geom:
    hs = heights or []

    def h(p: int) -> float:
        return hs[p - 1] if p - 1 < len(hs) else 1.0

    off = [0.0] * (pages + 1)
    for i in range(1, pages + 1):
        off[i] = off[i - 1] + h(i)
    return Geom(pages=pages, h=h, off=off)


def _round_page(v: float) -> int:
    # JS Math.round 正数口径（page 恒正）：half-up 非 Python round 的银行家舍入
    return int(math.floor(v + 0.5))


def to_linear(g: Geom, pos: dict, col_aware: bool) -> float:
    page = min(max(_round_page(pos["page"]), 1), g.pages)
    share = (col_of(pos) + pos["fraction"]) / 2 if col_aware else pos["fraction"]
    return g.off[page - 1] + share * g.h(page)


def from_linear(g: Geom, x: float, col_aware: bool) -> dict:
    total = g.off[g.pages]
    if x <= 0:
        return {"page": 1, "fraction": 0.0}
    if x >= total:
        return {"page": g.pages, "fraction": 1.0}
    lo, hi = 0, g.pages
    while lo + 1 < hi:
        mid = (lo + hi) >> 1
        if g.off[mid] <= x:
            lo = mid
        else:
            hi = mid
    hh = g.h(lo + 1)
    rem = min(max((x - g.off[lo]) / hh, 0.0), 1.0) if hh > 0 else 0.0
    fraction = (rem * 2 if rem <= 0.5 else (rem - 0.5) * 2) if col_aware else rem
    return {"page": lo + 1, "fraction": fraction}


def _drop_outliers(pairs: list, geoms: dict, col_aware: bool) -> list:
    if len(pairs) < 3:
        return pairs
    drop = set()
    for src, dst in (("original", "translated"), ("translated", "original")):
        unit = geoms[dst].off[geoms[dst].pages] / max(geoms[dst].pages, 1)
        order = sorted(
            range(len(pairs)),
            key=lambda i: to_linear(geoms[src], pairs[i][src], col_aware),
        )
        xs = [to_linear(geoms[src], pairs[i][src], col_aware) for i in order]
        ys = [to_linear(geoms[dst], pairs[i][dst], col_aware) for i in order]
        for k in range(1, len(order) - 1):
            span = xs[k + 1] - xs[k - 1]
            if span <= 0:
                continue
            exp = ys[k - 1] + (ys[k + 1] - ys[k - 1]) * ((xs[k] - xs[k - 1]) / span)
            if abs(ys[k] - exp) > 2 * unit:
                drop.add(order[k])
    return [p for i, p in enumerate(pairs) if i not in drop] if drop else pairs


def interp(x: float, xs: list, ys: list) -> float:
    if not xs:
        return x
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while lo + 1 < hi:
        mid = (lo + hi) >> 1
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    span = xs[lo + 1] - xs[lo]
    t = (x - xs[lo]) / span if span > 0 else 0
    return ys[lo] + t * (ys[lo + 1] - ys[lo])


def create_position_mapper(alignment: dict | None, pages: dict):
    """alignment.ts createPositionMapper 移植：f(pos, frm) → Pos。

    frm ∈ {"original", "translated"}（sim 侧 "o"/"t" 由调用方映射）。
    f.knots = {"xsO","ysO","xsT","ysT","regions","col_aware","geoms",
    "use_landmarks"}——审计面量倒置/锯齿要 knot 序列本身。
    """
    al = alignment or {}
    heights = al.get("heights") or {}
    geoms = {
        "original": geom_of(heights.get("original"), max(1, int(pages["original"]))),
        "translated": geom_of(
            heights.get("translated"), max(1, int(pages["translated"]))
        ),
    }
    raw = list(al.get("pairs") or [])
    col_aware = any(
        p["original"].get("x") is not None or p["translated"].get("x") is not None
        for p in raw
    )
    pairs = _drop_outliers(raw, geoms, col_aware)

    regions = []
    for r in al.get("regions") or []:
        ro, rt = r["original"], r["translated"]
        go, gt = geoms["original"], geoms["translated"]
        so = to_linear(go, {"page": ro["page"], "fraction": ro["start"]}, col_aware)
        eo = to_linear(go, {"page": ro["page"], "fraction": ro["end"]}, col_aware)
        st = to_linear(gt, {"page": rt["page"], "fraction": rt["start"]}, col_aware)
        et = to_linear(gt, {"page": rt["page"], "fraction": rt["end"]}, col_aware)
        regions.append(
            {"o": (min(so, eo), max(so, eo)), "t": (min(st, et), max(st, et))}
        )
    regions.sort(key=lambda r: r["o"][0])

    by_o = sorted(
        pairs, key=lambda p: to_linear(geoms["original"], p["original"], col_aware)
    )
    by_t = sorted(
        pairs,
        key=lambda p: to_linear(geoms["translated"], p["translated"], col_aware),
    )
    xsO = [to_linear(geoms["original"], p["original"], col_aware) for p in by_o]
    ysO = [to_linear(geoms["translated"], p["translated"], col_aware) for p in by_o]
    xsT = [to_linear(geoms["translated"], p["translated"], col_aware) for p in by_t]
    ysT = [to_linear(geoms["original"], p["original"], col_aware) for p in by_t]

    use_landmarks = al.get("kind") != "pages" and len(pairs) > 0

    def f(pos: dict, frm: str) -> dict:
        to = "translated" if frm == "original" else "original"
        src, dst = geoms[frm], geoms[to]
        x = to_linear(src, pos, col_aware)
        if use_landmarks:
            hit = None
            for r in regions:
                s, e = r["o"] if frm == "original" else r["t"]
                if s <= x <= e:
                    hit = r
                    break
            if hit is not None:
                s, e = hit["o"] if frm == "original" else hit["t"]
                ds, de = hit["t"] if frm == "original" else hit["o"]
                t = (x - s) / (e - s) if e > s else 0
                y = ds + t * (de - ds)
            else:
                xs = xsO if frm == "original" else xsT
                ys = ysO if frm == "original" else ysT
                y = interp(x, xs, ys)
            out = from_linear(dst, y, col_aware)
            out["viewport"] = pos.get("viewport")
            return out
        return {
            "page": min(max(_round_page(pos["page"]), 1), dst.pages),
            "fraction": pos["fraction"],
            "viewport": pos.get("viewport"),
        }

    f.knots = {
        "xsO": xsO,
        "ysO": ysO,
        "xsT": xsT,
        "ysT": ysT,
        "regions": regions,
        "col_aware": col_aware,
        "geoms": geoms,
        "use_landmarks": use_landmarks,
    }
    return f


# ---------- search_for 真值探针 ----------

_SEG_SPLIT = re.compile(r"\[\[[A-Z]+_\d+\]\]|\$[^$]*\$|\\\([^)]*\\\)|\\\[[^\]]*\]")
_ALNUM_CH = re.compile(r"[0-9A-Za-z一-鿿]")
_CJK_CH = re.compile(r"[一-鿿]")


def lit_probes(txt: str, short_ok: bool = False) -> list[str]:
    """真值探针组——洞外连段 + 多相位滑窗。

    探针必须取占位符/行间数学之间的连段：先剥成空格再切片会得到跨洞
    针，PDF 洞位是真字形（数学/引用/图表号），跨洞探针永远全灭
    （bedd zh 侧 60% 盲区实证）。CJK 可在任意字间断行 → 定宽滑窗
    多相位铺满，至少一格整窗落单行内；段含 CJK 时另发去空格变体
    （\\textbf{后件：}由 → 后件：由 连排无空白，假洞=latex 命令位）。
    short_ok：seq 有锚页时用 ≥2 字针兜底（'引言'级短题头近窗可钉）。
    """
    cands: list[str] = []
    for piece in _SEG_SPLIT.split(txt or ""):
        seg = _tex_strip(piece)
        sp = re.sub(r"\s+", " ", seg).strip()
        variants = [sp]
        if _CJK_CH.search(sp):
            ns = sp.replace(" ", "")
            if ns != sp:
                variants.append(ns)
        cands.extend(v for v in variants if len(_ALNUM_CH.findall(v)) >= 4)
    if not cands:
        if not short_ok:
            return []
        sp = re.sub(r"\s+", " ", _tex_strip(txt or "")).strip()
        return [
            v[:12]
            for v in dict.fromkeys((sp, sp.replace(" ", "")))
            if len(_ALNUM_CH.findall(v)) >= 2
        ]
    out: list[str] = []

    def add(p: str) -> None:
        if p and p not in out and len(out) < 9:
            out.append(p)

    best = max(cands, key=len)
    add(best[:24])
    wide = 10 if _CJK_CH.search(best) else 16
    if len(best) > wide:
        for off in range(0, len(best) - wide + 1, max(wide - 2, 1)):
            add(best[off : off + wide])
        add(best[-wide:])
    for c in sorted(cands, key=len, reverse=True):
        add(c if len(c) <= 24 else c[:24])
    return out


def lit_probe(txt: str, want: int = 24) -> str | None:
    """audit 单针口径——_tex_strip 已把占位符剥成空格（PH.split 恒单段），
    语义 = 剥后文本最长相干段的前 want 字。保留 seqpos_audit 既有真值口径
    （修复前基线快照可比性）。"""
    s = re.sub(r"\s+", " ", _tex_strip(txt or "").strip())
    if len(re.sub(r"[^0-9A-Za-z一-鿿]", "", s)) < 4:
        return None
    return s[:want]


def scan_pages(doc, phrase, pages):
    out = []
    for pno in pages:
        pg = doc[pno]
        for r in pg.search_for(phrase):
            out.append((pno + 1, r, pg.rect.width, pg.rect.height))
    return out


def truth_rects(doc, probes, near_page=None, win=2):
    """search_for 探针组 → [(pno1, rect, w, h)]。近窗全探针并集，远窗先中先用。

    近窗必须并集全探针：滑窗片在锚位出现点可能恰跨断行全灭、却在
    孪生出现点单行命中——首中即返会把真值钉到远端孪生（a7c5 seq13
    en 锚 0.839 vs 真值错挑 0.088 实证）；并集后近锚挑选才稳。
    """
    pages = list(range(doc.page_count))
    if near_page is not None:
        lo, hi = near_page - 1 - win, near_page - 1 + win
        span = [p for p in pages if lo <= p <= hi]
        seen: set[tuple] = set()
        near: list[tuple] = []
        for phrase in probes:
            for h in scan_pages(doc, phrase, span):
                k = (h[0], round(h[1].x0, 1), round(h[1].y0, 1))
                if k not in seen:
                    seen.add(k)
                    near.append(h)
        if near:
            return near
    for phrase in probes:
        out = scan_pages(doc, phrase, pages)
        if out:
            return out
    return []
