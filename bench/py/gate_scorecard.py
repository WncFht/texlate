#!/usr/bin/env python3
"""gate_scorecard — M2 出口门记分卡。

用法:
    python3 bench/py/gate_scorecard.py [records_dir] [--json]

缺省读 bench/results/stagerun-loop1-2026-09-16/records/。
对每篇 paper 取 compile(zh)/fixloop 末条 record，两套口径并列：

    end-state(末段胜)  新鲜 fixloop 记录存在即取 fixloop 终态，否则 compile
    union(best-of)     compile 与新鲜 fixloop 两段取较优终态(STATUS_RANK)

旧版把末段胜口径印在名为 "union" 的行上——名实不符：fixloop 回退格
(compile partial→post fail)在末段胜记 fail、在 best-of 记 partial。
现两口径分列，门线各出一条；union lift 块列出回退迁移明细。

fix 覆盖有门槛：compile 终态须为真编译结果(fail/partial/clean，
reject/skip 格的 fixloop 记录是 --on all 误编译英文树的产物不计入)。
新鲜度校验两档：fix 记录带 ``metrics.compile_fp`` 时做 compile 记录
指纹比对——compile 重跑 status 不变但 sig/first_error 已换(同态陈旧)
也拦；无指纹的史前排记录回退 ``compile_status_before`` 状态等值校验，
校验档位计数进 csb-check 块。另有 90% 门缺口数、excl-reject 口径。
依赖: 纯 stdlib。
"""

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import benchlib

DEFAULT_DIR = Path("bench/results/stagerun-loop1-2026-09-16/records")
GATE = 0.90

COMPILED = benchlib.COMPILED_STATUS
_RANK = benchlib.STATUS_RANK
#: compile 记录指纹单源——读侧比对与 stage_fixloop 写侧同一函数。
compile_fp = benchlib.compile_fp
#: 出 pdf 的终态集——end-state/union 两口径共用。
PDF_STATUS = {"clean", "partial"}


def last_records(
    path: Path, arm: str | None = None, upstream: str | None = "mock"
) -> dict[str, dict]:
    if not path.exists():
        return {}
    kept = []
    for r in benchlib.iter_jsonl(path, errors="replace"):
        if not isinstance(r, dict):
            continue
        if arm is not None and r.get("arm") != arm:
            continue
        # 双臂波次防串：对臂记录不进本口径——upstream 字段缺失按 mock
        # 计（史前排无此字段）；arm_mismatch skip 是对臂 decline 零
        # verdict 信息，两侧视图全跳。
        if upstream is not None and (r.get("upstream") or "mock") != upstream:
            continue
        errs = r.get("errors")
        if not isinstance(errs, list):
            errs = []
        if any(isinstance(e, dict) and e.get("code") == "arm_mismatch" for e in errs):
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            continue
        kept.append(r)
    return benchlib.latest_by(kept, lambda r: r["id"])


def pick_final(c: dict, f: dict | None) -> tuple[str, dict, str | None]:
    """合成终态：(stage, record, drop_reason)。

    fix 只在覆盖真编译结果且未过期时生效——`--on all` 会对
    inject:reject/skip 格也产出 fixloop 记录（编译被拒英文树），
    不能计入。新鲜度校验：``metrics.compile_fp`` 在场按 compile 记录
    指纹比对（同态陈旧拦），缺席回退 ``compile_status_before`` 状态
    等值（status 同而 log/树已换挡不住——弱校验档位由调用侧计数）。
    compile 在 fix 之后重跑且指纹/status 改变时 fix 陈旧作废。
    """
    if f is None:
        return "compile", c, None
    if c.get("status") not in COMPILED:
        return "compile", c, "over_noncompiled"
    fmet = f.get("metrics")
    if not isinstance(fmet, dict):
        fmet = {}
    fp = fmet.get("compile_fp")
    if isinstance(fp, str) and fp:
        if fp != compile_fp(c):
            return "compile", c, "fp_mismatch"
    else:
        csb = fmet.get("compile_status_before")
        if csb is None:
            return "compile", c, "no_csb"
        if csb != c.get("status"):
            return "compile", c, "stale"
    cu, fu = c.get("upstream"), f.get("upstream")
    if cu and fu and cu != fu:
        return "compile", c, "upstream_mismatch"
    return "fixloop", f, None


def _gate(pdf: int, total: int) -> dict:
    """90% 门判定 → {"pass": bool, "need": int}（need=距门尚缺格数）。"""
    ok = bool(total) and pdf / total >= GATE
    need = 0 if ok else max(0, math.ceil(total * GATE - pdf - 1e-9))
    return {"pass": ok, "need": need}


def _tally(comp: dict[str, dict], fix: dict[str, dict]) -> dict:
    """逐格合成两口径计数——text/--json 两渲染层共用同一份账。"""
    end = Counter()  # "stage:status" —— 末段胜
    uni = Counter()  # union 终态（plain status）
    uni_src = Counter()  # union 终态由哪段供出
    lift_trans = Counter()  # union>end 的迁移对 "csb->post"
    end_sig = Counter()
    dropped_fix = Counter()
    csb_check = Counter()  # fingerprint / legacy_status
    dropped_better = 0  # 被弃 fix 状态反优于 compile——stale 丢救面
    code_dist = Counter()  # "stage@stamp" —— rerun 波混写多版代码的嗅探面
    floor_restored = 0  # fixloop 底板兜回(pdf 文件在盘)
    floor_nopdf = 0  # 兜回但 post 仍判无 pdf——「有文件没 verdict」虚低面
    for pid, c in comp.items():
        f = fix.get(pid)
        code_dist[f"compile@{c.get('code') or '?'}"] += 1
        if f is not None:
            code_dist[f"fixloop@{f.get('code') or '?'}"] += 1
        stage, r, drop = pick_final(c, f)
        if drop is not None:
            dropped_fix[drop] += 1
            if _RANK.get(str(f.get("status") or ""), -1) > _RANK.get(
                str(c.get("status") or ""), -1
            ):
                dropped_better += 1
        st = r.get("status") or "?"
        end[f"{stage}:{st}"] += 1
        if st != "clean":
            end_sig[r.get("sig") or "?"] += 1
        # 新鲜度校验档位计数：所有过了 COMPILED 闸的 fix 记录都吃过
        # 一次校验——接管与否都记档（fingerprint/legacy_status 覆盖面）。
        if f is not None and c.get("status") in COMPILED:
            fmet = f.get("metrics")
            fmet = fmet if isinstance(fmet, dict) else {}
            fp = fmet.get("compile_fp")
            csb_check[
                "fingerprint" if isinstance(fp, str) and fp else "legacy_status"
            ] += 1
        # union 口径：与 end-state 共用同一新鲜度门——陈旧 fix 的
        # 「曾出 pdf」不混入当前态读数（口径差全在聚合方式）。
        cs = str(c.get("status") or "?")
        us, usrc = cs, "compile"
        if stage == "fixloop":
            fs = str(f.get("status") or "?")
            fm = f.get("metrics")
            if isinstance(fm, dict) and fm.get("floor_restored"):
                floor_restored += 1
                if fs not in PDF_STATUS:
                    floor_nopdf += 1
            if _RANK.get(fs, -1) > _RANK.get(cs, -1):
                us, usrc = fs, "fixloop"
            elif _RANK.get(fs, -1) < _RANK.get(cs, -1):
                lift_trans[f"{cs}->{fs}"] += 1
        uni[us] += 1
        uni_src[usrc] += 1

    total = sum(end.values())
    reject = end.get("compile:reject", 0)
    n_norej = total - reject
    end_pdf = sum(v for k, v in end.items() if k.split(":")[1] in PDF_STATUS)
    end_clean = sum(v for k, v in end.items() if k.split(":")[1] == "clean")
    uni_pdf = sum(v for k, v in uni.items() if k in PDF_STATUS)
    uni_clean = uni.get("clean", 0)
    lift_cells = sum(lift_trans.values())
    return {
        "records": comp,
        "total": total,
        "reject": reject,
        "n_norej": n_norej,
        "end": end,
        "end_pdf": end_pdf,
        "end_clean": end_clean,
        "end_sig": end_sig,
        "uni": uni,
        "uni_pdf": uni_pdf,
        "uni_clean": uni_clean,
        "uni_src": uni_src,
        "lift_trans": lift_trans,
        "lift_cells": lift_cells,
        "lift_pdf": uni_pdf - end_pdf,
        "lift_clean": uni_clean - end_clean,
        "dropped_fix": dropped_fix,
        "dropped_better": dropped_better,
        "csb_check": csb_check,
        "code_dist": code_dist,
        "orphan_fix": len(set(fix) - set(comp)),
        "floor_restored": floor_restored,
        "floor_nopdf": floor_nopdf,
    }


def _report(t: dict, rec_dir: Path) -> dict:
    """tally → --json 机读文档（与文本输出同口径同数）。"""

    def pct(n: int, d: int) -> float | None:
        return round(n / d * 100, 4) if d else None

    total, norej = t["total"], t["n_norej"]
    return {
        "schema": "gate_scorecard/v2",
        "records_dir": str(rec_dir),
        "cells": total,
        "gate_threshold": GATE,
        "end_state": {
            "pdf": t["end_pdf"],
            "pdf_pct": pct(t["end_pdf"], total),
            "clean": t["end_clean"],
            "clean_pct": pct(t["end_clean"], total),
            "gate": _gate(t["end_pdf"], total),
            "excl_reject": (
                {
                    "n": norej,
                    "pdf_pct": pct(t["end_pdf"], norej),
                    "clean_pct": pct(t["end_clean"], norej),
                }
                if norej
                else None
            ),
            "dist": dict(t["end"].most_common()),
        },
        "union": {
            "pdf": t["uni_pdf"],
            "pdf_pct": pct(t["uni_pdf"], total),
            "clean": t["uni_clean"],
            "clean_pct": pct(t["uni_clean"], total),
            "gate": _gate(t["uni_pdf"], total),
            "excl_reject": (
                {
                    "n": norej,
                    "pdf_pct": pct(t["uni_pdf"], norej),
                    "clean_pct": pct(t["uni_clean"], norej),
                }
                if norej
                else None
            ),
            "dist": dict(t["uni"].most_common()),
            "source": dict(t["uni_src"]),
        },
        "lift": {
            "cells": t["lift_cells"],
            "pdf": t["lift_pdf"],
            "clean": t["lift_clean"],
            "transitions": dict(t["lift_trans"].most_common()),
        },
        "dropped_fix": dict(t["dropped_fix"].most_common()),
        "dropped_fix_better": t["dropped_better"],
        "csb_check": dict(t["csb_check"]),
        "code_stamps": dict(t["code_dist"].most_common()),
        "orphan_fix": t["orphan_fix"],
        "floor_restored": t["floor_restored"],
        "floor_restored_nopdf": t["floor_nopdf"],
        "top_sigs": t["end_sig"].most_common(15),
    }


def _print_text(t: dict, rec_dir: Path) -> None:
    total = t["total"]
    rep = _report(t, rec_dir)
    e, u = rep["end_state"], rep["union"]
    print(f"records: {rec_dir}")
    if total == 0:
        print("cells=0  (no records)")
        return
    # 首行锚点沿用旧格式(cells=/pdf=/clean=)——end-state 口径；
    # 真 union 口径另起行。status_panel 转 --json 前正则仍可读。
    print(
        f"cells={total}  pdf={e['pdf']} ({e['pdf_pct']:.2f}%)"
        f"  clean={e['clean']} ({e['clean_pct']:.2f}%)   [end-state]"
    )
    print(
        f"union:  pdf={u['pdf']} ({u['pdf_pct']:.2f}%)"
        f"  clean={u['clean']} ({u['clean_pct']:.2f}%)   [best-of]"
    )
    for tag, g in (("end-state-pdf", e["gate"]), ("union-pdf", u["gate"])):
        line = "PASS" if g["pass"] else f"need +{g['need']}"
        print(f"gate {tag} >=90%: {line}")
    if t["n_norej"]:
        ee, ue = e["excl_reject"], u["excl_reject"]
        print(
            f"  excl-reject(n={ee['n']}): pdf {ee['pdf_pct']:.2f}%"
            f"  clean {ee['clean_pct']:.2f}% (end-state)"
            f" · pdf {ue['pdf_pct']:.2f}%  clean {ue['clean_pct']:.2f}% (union)"
        )
    lift = rep["lift"]
    print(
        f"union lift: +{lift['pdf']} pdf +{lift['clean']} clean"
        f" over {lift['cells']} cells (best-of vs end-state)"
    )
    if t["floor_restored"]:
        print(
            f"floor-restored: {t['floor_restored']} 格底板兜回"
            f"（其中 {t['floor_nopdf']} 终态仍无 pdf——文件在盘但判 fail）"
        )
    print("\nend-state:")
    for s, c in t["end"].most_common():
        print(f"  {c:5d}  {s}")
    if t["lift_trans"]:
        print("\nunion-lift:")
        for s, c in t["lift_trans"].most_common():
            print(f"  {c:5d}  {s}")
    if t["dropped_fix"]:
        print("\ndropped fixloop overrides:")
        for s, c in t["dropped_fix"].most_common():
            print(f"  {c:5d}  {s}")
        if t["dropped_better"]:
            print(
                f"  (+{t['dropped_better']} dropped fix had better status"
                " than compile — stale 丢救面)"
            )
    if t["csb_check"]:
        print("\ncsb-check:")
        for s, c in t["csb_check"].most_common():
            print(f"  {c:5d}  {s}")
    if len(t["code_dist"]) > 1 or t["orphan_fix"]:
        print("\ncode-stamps:")
        for s, c in t["code_dist"].most_common(12):
            print(f"  {c:5d}  {s}")
        rest = len(t["code_dist"]) - 12
        if rest > 0:
            print(f"   …    +{rest} more")
        if t["orphan_fix"]:
            print(f"  (+{t['orphan_fix']} orphan fixloop records, no compile cell)")
    print("\ntop non-clean sigs:")
    for s, c in t["end_sig"].most_common(15):
        print(f"  {c:5d}  {s}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0])
    p.add_argument(
        "records_dir", nargs="?", default=str(DEFAULT_DIR), help="records/ 目录"
    )
    p.add_argument("--json", action="store_true", dest="as_json", help="机读输出")
    args = p.parse_args(argv)
    rec_dir = Path(args.records_dir)

    comp = last_records(rec_dir / "compile.jsonl", arm="zh", upstream="mock")
    fix = last_records(rec_dir / "fixloop.jsonl", upstream="mock")
    t = _tally(comp, fix)
    if args.as_json:
        print(json.dumps(_report(t, rec_dir), ensure_ascii=False, indent=1))
    else:
        _print_text(t, rec_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
