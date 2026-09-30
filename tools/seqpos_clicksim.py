"""点击→seq 解析仿真——三种 picker 语义对照，逐块均匀取点击点。

picker:
  nearest = 生产现状 |Δfraction| 最近锚（同页）/ dpage+ 页沿距（跨页）
  floor_y = (page,frac) 纯 y floor——含点块语义，栏盲
  floor_c = (page,col,frac) 栏感知 floor——col=x>=0.45，x 缺则全 0
真值定义：点击点落在 seq_i 的 [pos_i, pos_{i+1}) 域内 → 正确 seq=i
（域界=阅读序下一地标的起点；跨栏/跨页自动成段）。这隔离前端 picker
误差——假定后端锚正确；后端 miss/缺席另由 seqpos_audit 报。
zh 侧只测 unmarked seq（marked 点击精确命中 span 不走 picker）。

用法：.venv/bin/python tools/seqpos_clicksim.py
"""

import json

from _env import TASKS
from _seqpos_lib import _char_stream, key_of, lin_of, nearest

SAMPLES = (0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9)


def floor_y(order, pos):
    """order=[(seq,pos)] 已按 (page,frac) 排——最后 <=pos 者。"""
    x = lin_of(pos)
    seq = None
    for k, p in order:
        if lin_of(p) <= x + 1e-9:
            seq = k
        else:
            break
    return seq


def floor_c(order, pos):
    """(page,col,frac) 序 floor。pos 无 x → col=0。"""
    key = key_of(pos)
    seq = None
    for k, p in order:
        if key_of(p) <= key:
            seq = k
        else:
            break
    return seq


def sim(tid):
    d = TASKS / tid
    sp = json.loads((d / "seqpos.json").read_text())["seqpos"]
    _, _, marks = _char_stream(d / "zh.pdf", collect_marks=True)
    out = {}
    for side, k in (("en", "o"), ("zh", "t")):
        lms = [(int(s), v[k]) for s, v in sp.items() if v.get(k)]
        order_y = sorted(lms, key=lambda kv: lin_of(kv[1]))
        order_c = sorted(lms, key=lambda kv: key_of(kv[1]))
        tot = 0
        wrong = {n: 0 for n in ("nearest", "floor_y", "floor_c")}
        null_n = 0
        for i, (seq, p) in enumerate(order_y):
            if side == "zh" and seq in marks:
                continue
            p0 = lin_of(p)
            p1 = lin_of(order_y[i + 1][1]) if i + 1 < len(order_y) else p0 + 0.08
            if p1 <= p0 + 1e-6:
                continue
            for u in SAMPLES:
                x = p0 + u * (p1 - p0)
                pg = int(x)
                pos = {"page": pg, "fraction": x - pg, "x": p.get("x")}
                tot += 1
                n = nearest(lms, pos)
                if n is None:
                    null_n += 1
                elif n != seq:
                    wrong["nearest"] += 1
                if floor_y(order_y, pos) != seq:
                    wrong["floor_y"] += 1
                if floor_c(order_c, pos) != seq:
                    wrong["floor_c"] += 1
        out[side] = (tot, wrong, null_n)
    return out


def main():
    agg = {}
    print(
        f"{'task':24} {'side':4} {'N':>5} {'nearest':>8} {'floor_y':>8} {'floor_c':>8} {'null':>6}"
    )
    for d in sorted(TASKS.iterdir()):
        if not ((d / "seqpos.json").is_file() and (d / "zh.pdf").is_file()):
            continue
        try:
            r = sim(d.name)
        except Exception as e:
            print(d.name, "ERR", e)
            continue
        for side, (tot, wrong, nn) in r.items():
            if not tot:
                continue
            a = agg.setdefault(side, [0, {"nearest": 0, "floor_y": 0, "floor_c": 0}, 0])
            a[0] += tot
            for k_ in wrong:
                a[1][k_] += wrong[k_]
            a[2] += nn
            print(
                f"{d.name:24} {side:4} {tot:>5} {wrong['nearest'] / tot:>8.1%} "
                f"{wrong['floor_y'] / tot:>8.1%} {wrong['floor_c'] / tot:>8.1%} {nn / tot:>6.1%}"
            )
    print("== aggregate ==")
    for side, (tot, wrong, nn) in agg.items():
        print(
            f"{side:4} N={tot} nearest={wrong['nearest'] / tot:.1%} "
            f"floor_y={wrong['floor_y'] / tot:.1%} floor_c={wrong['floor_c'] / tot:.1%} "
            f"null={nn / tot:.1%}"
        )


main()
