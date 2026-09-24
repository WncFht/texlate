"""端到端点击→对侧落点仿真 + 栏型普查——真值=search_for 实字形矩形。

完整复刻生产 PDF→PDF 链路（ReaderView/sentalign.ts/pdfseqpos.ts）：

  点击 pos(page,frac,x) → seqAtPoint（zh marked 走 TLXC 直命；否则
  containingSeq 全键 floor+栏降级+距离闸）→ jumpSeq：u=fracInBlock
  （点击在 src 区间 [S,S') 的分位）→ interpDst（dst 同 seq 区间
  [S_dst,S'_dst) 线性插回 Pos）→ 兜底 seqPos 直锚 → 再兜底 mapPos
  比例映射。落点 vs 该 seq 对侧真值矩形（lit_probe+search_for）。

与 seqpos_clicksim（合成域模型）互补；seqpos_audit 量锚精度，本脚本
量「点击→落地」全链路。另出：栏型普查、x 覆盖率、marked 覆盖、
en↔zh 锚序倒置率、栏边界应力（右栏顶/左栏底点击的栏序正确性）。

用法: .venv/bin/python tools/seqpos_e2e_sim.py [task_id ...]
输出: tmp/seqpos-e2e.json
"""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")
import pymupdf  # noqa: E402

from texlate.server.seqpos import _char_stream, _tex_strip  # noqa: E402

TASKS = Path.home() / ".texlate/tasks"
PH = re.compile(r"\[\[[A-Z]+_\d+\]\]")
COL_X = 0.45


def lit_probe(txt: str, want: int = 24) -> str | None:
    s = _tex_strip(txt or "")
    frags = [re.sub(r"\s+", " ", f.strip()) for f in PH.split(s)]
    frags = [f for f in frags if len(re.sub(r"[^0-9A-Za-z一-鿿]", "", f)) >= 4]
    if not frags:
        return None
    best = max(frags, key=len)
    return best[:want] if len(best) > want else best


# ---------- 生产语义复刻（pdfseqpos.ts / sentalign.ts / alignment.ts） ----------


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


def containing(lands: list[tuple[int, dict]], pos: dict) -> int | None:
    """pdfseqpos.ts containingSeq 逐行移植。"""
    if not lands:
        return None
    first = lands[0]
    if pos.get("x") is not None:
        eff = degrade(lands, pos)
        if key_of(eff) < key_of(first[1]):
            return first[0] if lin_of(first[1]) - lin_of(eff) <= 1 else None
        best, lo, hi = -1, 0, len(lands) - 1
        while lo <= hi:
            mid = (lo + hi) >> 1
            if key_of(lands[mid][1]) <= key_of(eff):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best < 0:
            return None
        return (
            lands[best][0] if abs(lin_of(lands[best][1]) - lin_of(eff)) <= 1.2 else None
        )
    best = -1
    lo_idx = 0
    for i, (_, p) in enumerate(lands):
        if (p["page"], p["fraction"]) < (
            lands[lo_idx][1]["page"],
            lands[lo_idx][1]["fraction"],
        ):
            lo_idx = i
        if (p["page"], p["fraction"]) > (pos["page"], pos["fraction"]):
            continue
        if best < 0 or (p["page"], p["fraction"]) >= (
            lands[best][1]["page"],
            lands[best][1]["fraction"],
        ):
            best = i
    if best < 0:
        f = lands[lo_idx][1]
        return lands[lo_idx][0] if lin_of(f) - lin_of(pos) <= 1 else None
    return lands[best][0] if abs(lin_of(lands[best][1]) - lin_of(pos)) <= 1.2 else None


def nearest(lands: list[tuple[int, dict]], pos: dict, max_score: float = 1.0):
    """旧 picker 基线：|Δfraction| 最近（同页）/ dpage+页沿距（跨页）。"""
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


def frac_in_block(lands, seq, pos):
    """sentalign.fracInBlock：u=(roLin(click)−roLin(S))/(roLin(S')−roLin(S))。"""
    idx = next((i for i, l in enumerate(lands) if l[0] == seq), -1)
    if idx < 0 or idx + 1 >= len(lands):
        return None
    p = degrade(lands, pos)
    a = ro_lin(lands[idx][1])
    d = ro_lin(lands[idx + 1][1]) - a
    if d == 0:
        return None
    return min(1.0, max(0.0, (ro_lin(p) - a) / d))


def interp_dst(lands, seq, u):
    """sentalign.interpDst：dst 同 seq 区间插回 Pos。"""
    if u is None:
        return None
    idx = next((i for i, l in enumerate(lands) if l[0] == seq), -1)
    if idx < 0 or idx + 1 >= len(lands):
        return None
    pa, pb = lands[idx][1], lands[idx + 1][1]
    y = ro_lin(pa) + u * (ro_lin(pb) - ro_lin(pa))
    page = int(y)
    s = y - page
    col = 1 if s >= 0.5 else 0
    out = {"page": page, "fraction": min(0.999, max(0.0, (s - col * 0.5) * 2))}
    xa, xb = pa.get("x"), pb.get("x")
    x = xa + u * (xb - xa) if (xa is not None and xb is not None) else (xa or xb)
    if x is not None:
        out["x"] = min(1.0, max(0.0, x))
    return out


def make_mapper(pairs: list[tuple[dict, dict]]):
    """mapPos 兜底（alignment.ts，pairs-only、页高均一化近似）。"""
    colaware = any(o.get("x") is not None or t.get("x") is not None for o, t in pairs)

    def to_l(p):
        share = (col_of(p) + p["fraction"]) / 2 if colaware else p["fraction"]
        return (p["page"] - 1) + share

    def from_l(x):
        page = int(x) + 1
        rem = x - int(x)
        frac = (rem * 2 if rem <= 0.5 else (rem - 0.5) * 2) if colaware else rem
        return {"page": page, "fraction": frac}

    def build(i, j):
        pts = sorted(pairs, key=lambda pr: to_l(pr[i]))
        return [to_l(p[i]) for p in pts], [to_l(p[j]) for p in pts]

    xys = {"o": build(0, 1), "t": build(1, 0)}

    def interp(x, xs, ys):
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

    def go(pos, frm):
        xs, ys = xys[frm]
        return from_l(interp(to_l(pos), xs, ys))

    return go


# ---------- 真值与普查 ----------


def _scan(doc, phrase, pages):
    out = []
    for pno in pages:
        pg = doc[pno]
        for r in pg.search_for(phrase):
            out.append((pno + 1, r, pg.rect.width, pg.rect.height))
    return out


def truth_rects(doc, phrase, near_page=None, win=2):
    """search_for → [(pno1, rect, w, h)]。近窗先扫、窗空才全扫。"""
    if not phrase:
        return []
    pages = list(range(doc.page_count))
    if near_page is not None:
        lo, hi = near_page - 1 - win, near_page - 1 + win
        out = _scan(doc, phrase, [p for p in pages if lo <= p <= hi])
        if out:
            return out
    return _scan(doc, phrase, pages)


def col_census(doc) -> tuple[int, int]:
    n2 = 0
    for pg in doc:
        w = pg.rect.width or 1
        right = left = 0
        for b in pg.get_text("blocks"):
            if b[6] != 0:
                continue
            if b[0] > (COL_X + 0.02) * w:
                right += 1
            if b[2] < (COL_X + 0.08) * w:
                left += 1
        if right >= 2 and left >= 2:
            n2 += 1
    return n2, doc.page_count


def sim(tid: str) -> dict:
    td = TASKS / tid
    dual = json.loads((td / "dual.json").read_text(encoding="utf-8"))
    sp = json.loads((td / "seqpos.json").read_text(encoding="utf-8"))["seqpos"]
    ch = {c["seq"]: c for c in dual["chunks"] if isinstance(c.get("seq"), int)}

    en = pymupdf.open(td / "en.pdf")
    zh = pymupdf.open(td / "zh.pdf")
    _, _, marks = _char_stream(td / "zh.pdf", collect_marks=True)
    en2, enp = col_census(en)
    zh2, zhp = col_census(zh)

    lands = {
        s: sorted(
            ((int(k), v[k2]) for k, v in sp.items() if v.get(k2)),
            key=lambda kv: key_of(kv[1]),
        )
        for s, k2 in (("o", "o"), ("t", "t"))
    }
    sp_by_seq = {int(k): v for k, v in sp.items()}
    pairs = [(v["o"], v["t"]) for v in sp.values() if v.get("o") and v.get("t")]
    mapper = make_mapper(pairs)

    rects: dict[int, dict] = {}
    for ss, comp in sp.items():
        seq = int(ss)
        c = ch.get(seq) or {}
        rects[seq] = {}
        for side, doc, tkey in (("o", en, "en"), ("t", zh, "zh")):
            cp = comp.get(side)
            hits = truth_rects(
                doc, lit_probe(c.get(tkey) or ""), cp["page"] if cp else None
            )
            if not hits:
                rects[seq][side] = None
                continue
            if cp:
                cx = cp["page"] + cp["fraction"]
                best = min(hits, key=lambda h: abs(h[0] + h[1].y0 / h[3] - cx))
            else:
                best = hits[0]
            rects[seq][side] = best

    stat = {
        s: {
            "n": 0,
            "pick": 0,
            "e2e": 0,
            "e2e25": 0,
            "pg": 0,
            "null": 0,
            "nodst": 0,
            "near": 0,
        }
        for s in ("o", "t")
    }
    wrong_rows = []
    marked_n = 0
    for ss, comp in sp.items():
        seq = int(ss)
        for side, dst_side in (("o", "t"), ("t", "o")):
            cp = comp.get(side)
            hit = rects[seq].get(side)
            if not cp or not hit:
                continue
            pno, r, w, h = hit
            dst_rect = rects[seq].get(dst_side)
            for fx in (0.25, 0.5, 0.75):
                pos = {
                    "page": pno,
                    "fraction": (r.y0 + r.y1) / 2 / h,
                    "x": (r.x0 + fx * (r.x1 - r.x0)) / w,
                }
                st = stat[side]
                st["n"] += 1
                if side == "t" and seq in marks:
                    picked = seq
                    marked_n += 1
                else:
                    picked = containing(lands[side], pos)
                if nearest(lands[side], pos) == seq:
                    st["near"] += 1
                if picked is None:
                    st["null"] += 1
                    # 生产兜底：jumpPosToPdf = mapPos 比例映射
                    land_pos = mapper(pos, side)
                else:
                    if picked == seq:
                        st["pick"] += 1
                    # jumpSeq：u 插值 → seqPos 直锚 → mapPos
                    u = frac_in_block(lands[side], picked, pos)
                    land_pos = interp_dst(lands[dst_side], picked, u)
                    if land_pos is None:
                        dp = sp_by_seq.get(picked, {}).get(dst_side)
                        land_pos = dict(dp) if dp else None
                    if land_pos is None:
                        st["nodst"] += 1
                        land_pos = mapper(pos, side)
                if dst_rect is None:
                    continue
                dno, dr, _, dh = dst_rect
                dfrac = (dr.y0 + dr.y1) / 2 / dh
                dlin = abs(land_pos["page"] + land_pos["fraction"] - (dno + dfrac))
                hit10 = (
                    land_pos["page"] == dno
                    and abs(land_pos["fraction"] - dfrac) <= 0.10
                )
                hit25 = dlin <= 0.25
                st["e2e"] += hit10
                st["e2e25"] += hit25
                st["pg"] += land_pos["page"] == dno
                if not hit25:
                    wrong_rows.append(
                        {
                            "seq": seq,
                            "side": side,
                            "pick": picked,
                            "land": [land_pos["page"], round(land_pos["fraction"], 3)],
                            "true": [dno, round(dfrac, 3)],
                        }
                    )

    # 锚序倒置率（两侧都锚的 seq 对）
    o_rank = {s: i for i, (s, _) in enumerate(lands["o"])}
    t_rank = {s: i for i, (s, _) in enumerate(lands["t"])}
    bl = [s for s in o_rank if s in t_rank]
    inv = inv_big = tot = 0
    for i in range(len(bl)):
        for j in range(i + 1, len(bl)):
            a, b = bl[i], bl[j]
            tot += 1
            if (o_rank[a] < o_rank[b]) != (t_rank[a] < t_rank[b]):
                inv += 1
                pa, pb = sp_by_seq[a], sp_by_seq[b]
                if (
                    abs(lin_of(pa["o"]) - lin_of(pb["o"])) > 1
                    and abs(lin_of(pa["t"]) - lin_of(pb["t"])) > 1
                ):
                    inv_big += 1

    # 栏边界应力：点击贴锚内侧——右栏首锚下沿/左栏末锚下沿
    bounds = []
    for pg_i in range(en.page_count):
        pno = pg_i + 1
        col1 = [l for l in lands["o"] if l[1]["page"] == pno and col_of(l[1]) == 1]
        col0 = [l for l in lands["o"] if l[1]["page"] == pno and col_of(l[1]) == 0]
        if col1:
            want = min(col1, key=lambda l: l[1]["fraction"])
            pos = {
                "page": pno,
                "fraction": min(0.99, want[1]["fraction"] + 0.02),
                "x": 0.7,
            }
            bounds.append(
                {
                    "kind": "rtop",
                    "page": pno,
                    "want": want[0],
                    "got": containing(lands["o"], pos),
                }
            )
        if col0 and col1:
            want = max(col0, key=lambda l: l[1]["fraction"])
            pos = {
                "page": pno,
                "fraction": min(0.99, want[1]["fraction"] + 0.02),
                "x": 0.2,
            }
            bounds.append(
                {
                    "kind": "lbot",
                    "page": pno,
                    "want": want[0],
                    "got": containing(lands["o"], pos),
                }
            )

    def agg(s):
        d = stat[s]
        n = d["n"] or 1
        return {
            "n": d["n"],
            "pick": round(d["pick"] / n, 3),
            "pg": round(d["pg"] / n, 3),
            "e2e": round(d["e2e"] / n, 3),
            "e2e25": round(d["e2e25"] / n, 3),
            "null": round(d["null"] / n, 3),
            "nodst": round(d["nodst"] / n, 3),
            "nearest": round(d["near"] / n, 3),
        }

    xcov = {
        s: round(
            sum(1 for v in sp.values() if v.get(k2) and v[k2].get("x") is not None)
            / max(1, sum(1 for v in sp.values() if v.get(k2))),
            3,
        )
        for s, k2 in (("o", "o"), ("t", "t"))
    }
    return {
        "task": tid,
        "cols": {"en": [en2, enp], "zh": [zh2, zhp]},
        "x_cov": xcov,
        "marked_n": len(marks),
        "marked_clicks": marked_n,
        "inv": [inv, tot, inv_big],
        "o": agg("o"),
        "t": agg("t"),
        "bounds": bounds,
        "wrong_rows": wrong_rows[:40],
    }


def main() -> None:
    tids = sys.argv[1:] or [
        d.name
        for d in sorted(TASKS.iterdir())
        if (d / "seqpos.json").is_file() and (d / "dual.json").is_file()
    ]
    out = []
    print(
        f"{'task':24} {'en2col':>7} {'zh2col':>7} {'xo':>5} {'xt':>5} "
        f"{'oPick':>6} {'oE2E':>6} {'tPick':>6} {'tE2E':>6} {'inv%':>6} {'bd':>5}"
    )
    for tid in tids:
        t0 = time.time()
        try:
            r = sim(tid)
            out.append(r)
            bd = len(r["bounds"])
            bdok = sum(1 for b in r["bounds"] if b["want"] == b["got"])
            invp = r["inv"][0] / r["inv"][1] * 100 if r["inv"][1] else 0
            print(
                f"{tid:24} {r['cols']['en'][0]:>2}/{r['cols']['en'][1]:<4} "
                f"{r['cols']['zh'][0]:>2}/{r['cols']['zh'][1]:<4} "
                f"{r['x_cov']['o']:>5.2f} {r['x_cov']['t']:>5.2f} "
                f"{r['o']['pick']:>6.1%} {r['o']['e2e25']:>6.1%} "
                f"{r['t']['pick']:>6.1%} {r['t']['e2e25']:>6.1%} "
                f"{invp:>5.1f}% {bdok}/{bd} [{time.time() - t0:.0f}s]",
                flush=True,
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            print(f"{tid} FAILED {e}")
    Path("tmp/seqpos-e2e.json").write_text(json.dumps(out, ensure_ascii=False))
    agg = {}
    for r in out:
        for s in ("o", "t"):
            a = agg.setdefault(s, [0] * 6)
            a[0] += r[s]["n"]
            a[1] += r[s]["pick"] * r[s]["n"]
            a[2] += r[s]["e2e"] * r[s]["n"]
            a[3] += r[s]["e2e25"] * r[s]["n"]
            a[4] += r[s]["pg"] * r[s]["n"]
            a[5] += r[s]["nearest"] * r[s]["n"]
    print("== aggregate ==")
    for s, (n, pk, e2, e25, pg, nr) in agg.items():
        if n:
            print(
                f"{s}: N={n} pick={pk / n:.1%} pg={pg / n:.1%} e2e@.10={e2 / n:.1%} "
                f"e2e@.25={e25 / n:.1%} nearest={nr / n:.1%}"
            )
    print(f"\nwrote tmp/seqpos-e2e.json ({len(out)} tasks)")


if __name__ == "__main__":
    main()
