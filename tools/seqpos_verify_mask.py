"""Verify: does audit's nearest-hit truth mask wrong-occurrence anchors?

For each seq/side with nhits>1, build expected occurrence window from
monotonic doc-order skeleton of UNAMBIGUOUS (nhits==1) seqs whose computed
agrees with the unique hit. If audit's picked hit (nearest to computed) is
outside the window while another hit is inside -> masked error candidate.

用法：.venv/bin/python tools/seqpos_verify_mask.py <task_id> ...
"""

import bisect as bs
import json
import sys

import pymupdf

from _alignsim import char_pos_stream
from _env import TASKS
from _seqpos_lib import _doc_order, _norm_chars, _tex_strip

PROBE_N = 30


def probe_windows(nd):
    if len(nd) <= PROBE_N:
        return [nd]
    return [nd[:PROBE_N], nd[len(nd) // 2 : len(nd) // 2 + PROBE_N], nd[-PROBE_N:]]


def locate_off(stream, pos, nd):
    """Like audit locate but keep stream offsets: [(offset, page1, frac)]."""
    for probe in probe_windows(nd):
        hits = []
        start = 0
        while True:
            j = stream.find(probe, start)
            if j < 0:
                break
            hits.append((j, pos[j][0], pos[j][1]))
            start = j + 1
            if len(hits) > 200:
                break
        if hits:
            return hits
    return []


def audit_task(tid):
    tdir = TASKS / tid
    dual = json.loads((tdir / "dual.json").read_text(encoding="utf-8"))
    sp = json.loads((tdir / "seqpos.json").read_text(encoding="utf-8"))["seqpos"]
    chunks = {
        c["seq"]: c for c in dual.get("chunks", []) if isinstance(c.get("seq"), int)
    }
    order = _doc_order(tdir, list(chunks.values()))
    big = 1 << 30

    def key(s):
        return order.get(s, big + s) if order else s

    en_doc = pymupdf.open(tdir / "en.pdf")
    zh_doc = pymupdf.open(tdir / "zh.pdf")
    en_stream, en_pos = char_pos_stream(en_doc)
    zh_stream, zh_pos = char_pos_stream(zh_doc)

    results = {}
    for side, stream, pos, fld in (
        ("o", en_stream, en_pos, "en"),
        ("t", zh_stream, zh_pos, "zh"),
    ):
        minlen = 2 if side == "t" else 4
        # collect per-seq hits
        per = {}
        for seq_s, comp in sp.items():
            seq = int(seq_s)
            cp = comp.get(side)
            if not cp:
                continue
            c = chunks.get(seq) or {}
            nd = _norm_chars(_tex_strip(c.get(fld) or ""))
            if len(nd) < minlen:
                continue
            hits = locate_off(stream, pos, nd)
            if not hits:
                continue
            cx = cp["page"] + cp["fraction"]
            picked = min(hits, key=lambda h: abs(h[1] + h[2] - cx))
            per[seq] = {
                "hits": hits,
                "picked": picked,
                "computed": (cp["page"], cp["fraction"]),
            }
        # skeleton: seqs with exactly 1 hit, where computed agrees (<0.05 lin)
        skel = []  # (rank, offset)
        for seq, d in per.items():
            if len(d["hits"]) == 1:
                off = d["hits"][0][0]
                cl = d["computed"][0] + d["computed"][1]
                hl = d["hits"][0][1] + d["hits"][0][2]
                if abs(cl - hl) < 0.05:
                    skel.append((key(seq), off))
        skel.sort()
        # for ambiguous seqs, find expected window from skeleton neighbors
        ranks = [r for r, _ in skel]
        masked = []
        for seq, d in per.items():
            if len(d["hits"]) <= 1:
                continue
            r = key(seq)
            i = bs.bisect_left(ranks, r)
            lo = skel[i - 1][1] if i > 0 else 0
            hi = skel[i][1] if i < len(skel) else len(stream)
            in_win = [h for h in d["hits"] if lo <= h[0] <= hi]
            picked = d["picked"]
            cl = d["computed"][0] + d["computed"][1]
            pl = picked[1] + picked[2]
            if len(in_win) == 1 and in_win[0][0] != picked[0]:
                # audit picked a different occurrence than skeleton-expected
                exp = in_win[0]
                el = exp[1] + exp[2]
                masked.append(
                    {
                        "seq": seq,
                        "nhits": len(d["hits"]),
                        "computed": d["computed"],
                        "audit_err": round(abs(cl - pl), 4),
                        "true_err": round(abs(cl - el), 4),
                        "picked_hit": (picked[1], round(picked[2], 3)),
                        "expect_hit": (exp[1], round(exp[2], 3)),
                    }
                )
        results[side] = {
            "ambig_n": sum(1 for d in per.values() if len(d["hits"]) > 1),
            "masked": masked,
        }
    return results


for tid in sys.argv[1:]:
    r = audit_task(tid)
    print("===", tid)
    for side in ("o", "t"):
        print(
            f"  {side}: ambig={r[side]['ambig_n']} masked_candidates={len(r[side]['masked'])}"
        )
        for m in r[side]["masked"][:15]:
            print("   ", m)
