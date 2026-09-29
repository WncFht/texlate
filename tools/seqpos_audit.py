"""seqpos 精度审计——pymupdf search_for 字面搜索当真值，与 seqpos.json 对比。

真值口径：chunk 文本剥出最长裸文本片段（lit_probe 去 [[X_n]] 占位符），
直接 search_for 拿视觉框 y0——与「用户看到的字」同口径。不用归一化字符流
探针（占位符在 needle 上打孔、断页退探针会造假错页）。marked 臂因 BDC 锚
在 v6+ 取标内首字形基线，与字形顶差 ~1 个 ascender，|Δfrac| 容忍带已含。

指标：cov=真值定位率 / wrong_page=错页率 / p50,p90=同页 |Δfrac| /
miss=错页或 |Δfrac|>0.08。zh 侧分臂：marked_mcOK(mc≥10)/marked_mc0/
unmarked。absent=1-len(sp)/len(chunks) 单列——seqpos.json 缺整条=双向
跳不了，不进 miss 分母但是真实失败面。

用法：.venv/bin/python tools/seqpos_audit.py [task_id ...]
输出：tmp/seqpos-audit.json（2026-09-24 修复前基线在 tmp/seqpos-audit2-BEFORE.json）
"""

import json
import sys
import time
from pathlib import Path

import pymupdf

from _env import TASKS
from _seqpos_lib import lit_probe
from texlate.server.seqpos import _char_stream

MISS_FRAC = 0.08


def truth(doc: pymupdf.Document, phrase: str | None):
    if not phrase:
        return []
    out = []
    for pno in range(doc.page_count):
        pg = doc[pno]
        h = pg.rect.height or 1
        for r in pg.search_for(phrase):
            out.append((pno + 1, r.y0 / h))
    return out


def audit(tid: str) -> dict:
    td = TASKS / tid
    dual = json.loads((td / "dual.json").read_text(encoding="utf-8"))
    sp = json.loads((td / "seqpos.json").read_text(encoding="utf-8"))["seqpos"]
    ch = {c["seq"]: c for c in dual["chunks"] if isinstance(c.get("seq"), int)}

    en = pymupdf.open(td / "en.pdf")
    zh = pymupdf.open(td / "zh.pdf")
    _, _, marks = _char_stream(td / "zh.pdf", collect_marks=True)
    # occurrence 列表化后：mc = 末个有锚 occurrence 的裹字形数（trusted 同口径）
    mc = {
        seq: (anch[-1].get("chars") or 0)
        for seq, occs in marks.items()
        if (anch := [o for o in occs if o.get("fraction") is not None])
    }

    zh_all = "".join(zh[p].get_text() for p in range(zh.page_count))
    zh_dead = sum(1 for c in zh_all if "一" <= c <= "鿿") < max(100, len(zh_all) // 20)

    rows = []
    for ss, comp in sp.items():
        seq = int(ss)
        c = ch.get(seq) or {}
        r = {"seq": seq, "marked": seq in marks, "mc": mc.get(seq)}
        for side, doc, txt in (
            ("o", en, c.get("en") or ""),
            ("t", zh, c.get("zh") or ""),
        ):
            cp = comp.get(side)
            if not cp:
                r[side] = None
                continue
            hits = truth(doc, lit_probe(txt))
            if not hits:
                r[side] = {"found": False}
                continue
            cx = cp["page"] + cp["fraction"]
            best = min(hits, key=lambda h: abs(h[0] + h[1] - cx))
            dp = cp["page"] - best[0]
            r[side] = {
                "found": True,
                "dpage": dp,
                "abs_frac": (abs(cp["fraction"] - best[1]) if dp == 0 else None),
                "nhits": len(hits),
            }
        rows.append(r)

    def agg(side, filt=None):
        rs = [r[side] for r in rows if r.get(side) and (filt is None or filt(r))]
        fo = [r for r in rs if r.get("found")]
        dfs = sorted(r["abs_frac"] for r in fo if r["abs_frac"] is not None)
        n = len(fo)
        nd = len(dfs)
        return {
            "n": len(rs),
            "cov": round(len(fo) / len(rs), 3) if rs else None,
            "wrong_page": round(sum(1 for r in fo if r["dpage"]) / n, 3) if n else None,
            "p50": round(dfs[nd // 2], 4) if nd else None,
            "p90": round(dfs[min(nd - 1, int(nd * 0.9))], 4) if nd else None,
            "miss": round(
                sum(1 for r in fo if r["dpage"] or (r["abs_frac"] or 0) > MISS_FRAC)
                / n,
                3,
            )
            if n
            else None,
            "amb": round(sum(1 for r in fo if r["nhits"] > 1) / n, 3) if n else None,
        }

    n_chunks = len(ch)
    return {
        "task": tid,
        "seqs": len(sp),
        "absent": round(1 - len(sp) / n_chunks, 3) if n_chunks else None,
        "zh_dead": zh_dead,
        "marked_n": len(marks),
        "o": agg("o"),
        "t": agg("t"),
        "t_marked": agg("t", lambda r: r["marked"]),
        "t_mark_mcOK": agg("t", lambda r: r["marked"] and (r["mc"] or 0) >= 10),
        "t_mark_mc0": agg("t", lambda r: r["marked"] and (r["mc"] or 0) < 10),
        "t_unmarked": agg("t", lambda r: not r["marked"]),
        "rows": rows,
    }


def main() -> None:
    tids = sys.argv[1:] or [
        d.name
        for d in sorted(TASKS.iterdir())
        if (d / "seqpos.json").is_file() and (d / "dual.json").is_file()
    ]
    out = []
    f = lambda a: (
        f"cov={a['cov']} wp={a['wrong_page']} p50={a['p50']} "
        f"p90={a['p90']} miss={a['miss']} amb={a['amb']}"
    )
    for tid in tids:
        t0 = time.time()
        try:
            r = audit(tid)
            out.append(r)
            print(
                f"{tid} seqs={r['seqs']} absent={r['absent']} "
                f"marked={r['marked_n']} dead={r['zh_dead']}\n"
                f"  o {f(r['o'])}\n  t {f(r['t'])}\n  t_mcOK {f(r['t_mark_mcOK'])}\n"
                f"  t_mc0 {f(r['t_mark_mc0'])}\n  t_unmkd {f(r['t_unmarked'])}\n"
                f"  [{time.time() - t0:.0f}s]",
                flush=True,
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            print(f"{tid} FAILED {e}")
    Path("tmp/seqpos-audit.json").write_text(json.dumps(out, ensure_ascii=False))
    print(f"\nwrote tmp/seqpos-audit.json ({len(out)} tasks)")


main()
