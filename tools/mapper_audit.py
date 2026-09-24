#!/usr/bin/env python3
"""Replicate createPositionMapper (web/src/reader/alignment.ts) on real task data
and measure: (a) ys adjacent inversions, (b) scroll-sync sawtooth amplitude,
(c) leave-one-out click-fallback error.

用法: .venv/bin/python tools/mapper_audit.py
"""

import json, sys, glob, os


def lin(pos, pages):
    # heights all 1.0 -> off[i]=i ; page clamped 1..pages
    p = min(max(round(pos["page"]), 1), pages)
    return (p - 1) + pos["fraction"]


def fromlin(x, pages):
    if x <= 0:
        return (1, 0.0)
    if x >= pages:
        return (pages, 1.0)
    lo = int(x)  # off[i]=i
    return (lo + 1, x - lo)


def build(pairs, regions, pages_o, pages_t):
    regs = []
    for r in regions:
        so = lin(
            {"page": r["original"]["page"], "fraction": r["original"]["start"]}, pages_o
        )
        eo = lin(
            {"page": r["original"]["page"], "fraction": r["original"]["end"]}, pages_o
        )
        st = lin(
            {"page": r["translated"]["page"], "fraction": r["translated"]["start"]},
            pages_t,
        )
        et = lin(
            {"page": r["translated"]["page"], "fraction": r["translated"]["end"]},
            pages_t,
        )
        regs.append(((min(so, eo), max(so, eo)), (min(st, et), max(st, et))))
    regs.sort(key=lambda r: r[0][0])
    byO = sorted(pairs, key=lambda p: lin(p["original"], pages_o))
    byT = sorted(pairs, key=lambda p: lin(p["translated"], pages_t))
    xsO = [lin(p["original"], pages_o) for p in byO]
    ysO = [lin(p["translated"], pages_t) for p in byO]
    xsT = [lin(p["translated"], pages_t) for p in byT]
    ysT = [lin(p["original"], pages_o) for p in byT]
    return regs, xsO, ysO, xsT, ysT


def interp(x, xs, ys):
    n = len(xs)
    if n == 0:
        return x
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, n - 1
    while lo + 1 < hi:
        mid = (lo + hi) >> 1
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    span = xs[lo + 1] - xs[lo]
    t = (x - xs[lo]) / span if span > 0 else 0
    return ys[lo] + t * (ys[lo + 1] - ys[lo])


def make_map(regs, xsO, ysO, xsT, ysT):
    def f(x, from_orig):
        for (s, e), (ds, de) in [(r[0], r[1]) for r in regs]:
            src = (s, e) if from_orig else (ds, de)
            if src[0] <= x <= src[1]:
                dst = (ds, de) if from_orig else (s, e)
                t = (x - src[0]) / (src[1] - src[0]) if src[1] > src[0] else 0
                return dst[0] + t * (dst[1] - dst[0])
        return interp(x, xsO if from_orig else xsT, ysO if from_orig else ysT)

    return f


rows = []
for taskdir in sorted(glob.glob(os.path.expanduser("~/.texlate/tasks/t_*"))):
    sp_f = os.path.join(taskdir, "seqpos.json")
    du_f = os.path.join(taskdir, "dual.json")
    if not (os.path.exists(sp_f) and os.path.exists(du_f)):
        continue
    try:
        spw = json.load(open(sp_f))
        sp = spw.get("seqpos", spw) if isinstance(spw, dict) else {}
        dual = json.load(open(du_f))
    except Exception as e:
        print(taskdir, "ERR", e)
        continue
    al = dual.get("alignment") or {}
    doc = dual.get("documents") or {}
    pages_o = (doc.get("original") or {}).get("pages") or 1
    pages_t = (doc.get("translated") or {}).get("pages") or 1
    pairs = list(al.get("pairs") or [])
    for k, v in sp.items():
        if not isinstance(v, dict):
            continue
        if v.get("o") and v.get("t"):
            pairs.append({"id": f"s{k}", "original": v["o"], "translated": v["t"]})
    regions = al.get("regions") or []
    regs, xsO, ysO, xsT, ysT = build(pairs, regions, pages_o, pages_t)
    n = len(xsO)
    if n < 3:
        continue

    def stats(xs, ys):
        inv = sum(1 for i in range(len(ys) - 1) if ys[i + 1] < ys[i] - 1e-9)
        big = sum(1 for i in range(len(ys) - 1) if abs(ys[i + 1] - ys[i]) > 1.5)
        invpct = 100 * inv / max(1, len(ys) - 1)
        # same-page column-wrap inversions: knots on same source page, y descends
        return inv, invpct, big

    invO, invpctO, bigO = stats(xsO, ysO)
    invT, invpctT, bigT = stats(xsT, ysT)

    # scroll sawtooth: sweep x finely, measure largest down-swing in mapped y
    f = make_map(regs, xsO, ysO, xsT, ysT)

    def sawtooth(from_orig, xmax):
        peak = -1e9
        worst = 0.0
        prev = None
        N = 4000
        for i in range(N + 1):
            x = xmax * i / N
            y = f(x, from_orig)
            if prev is not None and y < prev:
                # falling
                pass
            if y > peak:
                peak = y
            worst = max(worst, peak - y)
            prev = y
        return worst

    sawO = sawtooth(True, pages_o)
    sawT = sawtooth(False, pages_t)

    # leave-one-out click-fallback error on seqpos knots (o->t and t->o)
    def loo_error(from_orig):
        errs = []
        seq_knots = [
            (lin(v["o"], pages_o), lin(v["t"], pages_t))
            for v in sp.values()
            if isinstance(v, dict) and v.get("o") and v.get("t")
        ]
        base_pairs = list(al.get("pairs") or [])
        for k, v in sp.items():
            if not (isinstance(v, dict) and v.get("o") and v.get("t")):
                continue
            others = [
                ({"id": f"s{k2}", "original": v2["o"], "translated": v2["t"]})
                for k2, v2 in sp.items()
                if k2 != k and isinstance(v2, dict) and v2.get("o") and v2.get("t")
            ]
            pr = base_pairs + others
            rg2, x2, y2, x2t, y2t = build(pr, regions, pages_o, pages_t)
            fm = make_map(rg2, x2, y2, x2t, y2t)
            if from_orig:
                x = lin(v["o"], pages_o)
                yt = lin(v["t"], pages_t)
            else:
                x = lin(v["t"], pages_t)
                yt = lin(v["o"], pages_o)
            errs.append(abs(fm(x, from_orig) - yt))
        errs.sort()
        if not errs:
            return (0, 0, 0)
        return (errs[len(errs) // 2], errs[int(len(errs) * 0.9)], errs[-1])

    looO = loo_error(True)
    looT = loo_error(False)

    rows.append(
        dict(
            task=os.path.basename(taskdir),
            n=n,
            pages=(pages_o, pages_t),
            invO=invO,
            invpctO=round(invpctO, 1),
            bigO=bigO,
            invT=invT,
            invpctT=round(invpctT, 1),
            bigT=bigT,
            sawO=round(sawO, 2),
            sawT=round(sawT, 2),
            looO=tuple(round(e, 2) for e in looO),
            looT=tuple(round(e, 2) for e in looT),
        )
    )

print(
    f"{'task':24} {'n':>4} {'pages':>8} | {'invO':>4} {'%O':>5} {'>1.5O':>5} {'sawO':>6} | {'invT':>4} {'%T':>5} {'>1.5T':>5} {'sawT':>6} | {'looO p50/p90/max':>18} {'looT p50/p90/max':>18}"
)
for r in rows:
    print(
        f"{r['task']:24} {r['n']:>4} {str(r['pages']):>8} | {r['invO']:>4} {r['invpctO']:>5} {r['bigO']:>5} {r['sawO']:>6} | {r['invT']:>4} {r['invpctT']:>5} {r['bigT']:>5} {r['sawT']:>6} | {str(r['looO']):>18} {str(r['looT']):>18}"
    )
