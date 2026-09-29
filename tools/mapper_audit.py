#!/usr/bin/env python3
"""Replicate createPositionMapper (web/src/reader/alignment.ts) on real task data
and measure: (a) ys adjacent inversions, (b) scroll-sync sawtooth amplitude,
(c) leave-one-out click-fallback error.

映射复刻走 _seqpos_lib.create_position_mapper——栏感知折序/页高表/离群
剔除与生产同口径。误差与锯齿在视觉 scroll 坐标度量（scroll/落点 Pos
无 x → 折栏只发生在 mapper 内部插值，不在度量面）。

用法：.venv/bin/python tools/mapper_audit.py
"""

import json

from _env import TASKS
from _seqpos_lib import create_position_mapper, from_linear, to_linear

_OTHER = {"original": "translated", "translated": "original"}


def eff_map(mapper, x, frm):
    """视觉 scroll 线性位 → 映射 → 对侧视觉线性位。"""
    geoms = mapper.knots["geoms"]
    pos = from_linear(geoms[frm], x, col_aware=False)
    return to_linear(geoms[_OTHER[frm]], mapper(pos, frm), False)


def stats(xs, ys):
    inv = sum(1 for i in range(len(ys) - 1) if ys[i + 1] < ys[i] - 1e-9)
    big = sum(1 for i in range(len(ys) - 1) if abs(ys[i + 1] - ys[i]) > 1.5)
    invpct = 100 * inv / max(1, len(ys) - 1)
    return inv, invpct, big


rows = []
for taskdir in sorted(TASKS.glob("t_*")):
    sp_f = taskdir / "seqpos.json"
    du_f = taskdir / "dual.json"
    if not (sp_f.is_file() and du_f.is_file()):
        continue
    try:
        spw = json.loads(sp_f.read_text())
        sp = spw.get("seqpos", spw) if isinstance(spw, dict) else {}
        dual = json.loads(du_f.read_text())
    except Exception as e:
        print(taskdir, "ERR", e)
        continue
    al = dual.get("alignment") or {}
    doc = dual.get("documents") or {}
    pages = {
        "original": (doc.get("original") or {}).get("pages") or 1,
        "translated": (doc.get("translated") or {}).get("pages") or 1,
    }
    base_pairs = list(al.get("pairs") or [])
    seq_pairs = [
        {"id": f"s{k}", "original": v["o"], "translated": v["t"]}
        for k, v in sp.items()
        if isinstance(v, dict) and v.get("o") and v.get("t")
    ]
    mapper = create_position_mapper({**al, "pairs": base_pairs + seq_pairs}, pages)
    K = mapper.knots
    n = len(K["xsO"])
    if n < 3:
        continue

    invO, invpctO, bigO = stats(K["xsO"], K["ysO"])
    invT, invpctT, bigT = stats(K["xsT"], K["ysT"])

    # scroll sawtooth: sweep x finely, measure largest down-swing in mapped y
    def sawtooth(frm):
        g = K["geoms"][frm]
        total = g.off[g.pages]
        peak = -1e9
        worst = 0.0
        N = 4000
        for i in range(N + 1):
            y = eff_map(mapper, total * i / N, frm)
            if y > peak:
                peak = y
            worst = max(worst, peak - y)
        return worst

    sawO = sawtooth("original")
    sawT = sawtooth("translated")

    # leave-one-out click-fallback error on seqpos knots（视觉 scroll 坐标）
    def loo_error(frm):
        errs = []
        sk, dk = ("o", "t") if frm == "original" else ("t", "o")
        gd = K["geoms"][_OTHER[frm]]
        for k, v in sp.items():
            if not (isinstance(v, dict) and v.get("o") and v.get("t")):
                continue
            others = [
                {"id": f"s{k2}", "original": v2["o"], "translated": v2["t"]}
                for k2, v2 in sp.items()
                if k2 != k and isinstance(v2, dict) and v2.get("o") and v2.get("t")
            ]
            fm = create_position_mapper(
                {**al, "pairs": base_pairs + others}, pages
            )
            pred = to_linear(gd, fm(v[sk], frm), False)
            errs.append(abs(pred - to_linear(gd, v[dk], False)))
        errs.sort()
        if not errs:
            return (0, 0, 0)
        return (errs[len(errs) // 2], errs[int(len(errs) * 0.9)], errs[-1])

    looO = loo_error("original")
    looT = loo_error("translated")

    rows.append(
        dict(
            task=taskdir.name,
            n=n,
            pages=(pages["original"], pages["translated"]),
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
