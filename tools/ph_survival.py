"""ph id 存活率对照（只读统计）：chunks.src_text vs translation 的 [[TYPE_n]] id 集合差分。

同篇双臂任务配对（如 prompt 批间对账）逐任务输出：
- doc_ph/src_occ: 源文去重 ph id 数 / 总出现次数
- tr_kept_ids/tr_occ/tr_extra_ids: 译文命中源 id 数 / 译文总出现 / 臆造串号 id 数
- missing_ids/extra_ids: 丢失与臆造 id（打印截前 12，JSON 报告全量）
- survival = tr_kept_ids/doc_ph；pair 级 src_overlap/same_src_ph 校验两臂同源
  （异篇或 rekey 漂移即在该字段现形）

词法 = 签发侧 canonical ``texlate.textutil.PH_RX``（整 token ``[[TYPE_n]]``，
type 含下划线亦覆盖——tmp 版私有 ``[A-Z]+`` 口径的上收）。
与 tools/ph_remap.py 不同物：本件纯统计只读（DB mode=ro 零写），
ph_remap 是 rekey 备份驱动的译文 id 重映射修复件（写 DB/dual.json）。

用法：.venv/bin/python tools/ph_survival.py [--labels v4,v5] [--db PATH] [--out tmp/ph-survival.json] <a> <b> [<a2> <b2> ...]
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path

from _env import DB
from texlate.textutil import PH_RX


def ph_ids(text: str) -> list[str]:
    """``[[TYPE_n]]`` 整 token 去壳成 ``TYPE_n`` id 串列（出现序、含重复）。"""
    return [m.group(0)[2:-2] for m in PH_RX.finditer(text)]


def _ph_sort(ids: set[str]) -> list[str]:
    """(type, n) 数值序——纯字典序会把 ``MATH_10`` 排到 ``MATH_2`` 前。"""
    return sorted(ids, key=lambda i: (i.rsplit("_", 1)[0], int(i.rsplit("_", 1)[1])))


def task_ph(db: sqlite3.Connection, tid: str) -> tuple[dict, set[str]]:
    """单任务 ph 统计 + 源 ph id 集（后者供 pair 级同源校验，不进报告）。"""
    rows = db.execute(
        "select src_text, translation from chunks where task_id=?", (tid,)
    ).fetchall()
    src_ids: set[str] = set()
    tr_ids: set[str] = set()
    src_occ = tr_occ = 0
    for s, t in rows:
        if s:
            ids = ph_ids(s)
            src_ids |= set(ids)
            src_occ += len(ids)
        if t:
            ids = ph_ids(t)
            tr_ids |= set(ids)
            tr_occ += len(ids)
    kept = src_ids & tr_ids
    extra = tr_ids - src_ids
    missing = src_ids - tr_ids
    stats = {
        "chunks": len(rows),
        "doc_ph": len(src_ids),
        "src_occ": src_occ,
        "tr_kept_ids": len(kept),
        "tr_occ": tr_occ,
        "tr_extra_ids": len(extra),
        "n_missing": len(missing),
        "missing_ids": _ph_sort(missing),
        "extra_ids": _ph_sort(extra),
        "survival": round(len(kept) / len(src_ids), 4) if src_ids else None,
    }
    return stats, src_ids


def _shown(st: dict) -> dict:
    """打印用副本——id 列表截前 12 防爆行；JSON 报告走全量。"""
    return {
        **st,
        "missing_ids": st["missing_ids"][:12],
        "extra_ids": st["extra_ids"][:12],
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="同篇双臂任务 ph id 存活率对照（只读统计）→ stdout + JSON 报告"
    )
    ap.add_argument("tasks", nargs="+", help="偶数个 task_id，按序两两成对")
    ap.add_argument(
        "--labels", default="a,b", help="臂标签逗号对（打印/报告键名，默认 a,b）"
    )
    ap.add_argument("--db", default=str(DB), help="texlate.db 路径（只读连接）")
    ap.add_argument("--out", default="tmp/ph-survival.json", help="JSON 报告落点")
    args = ap.parse_args()

    if len(args.tasks) % 2:
        ap.error(f"tasks 须偶数个（两两成对），得 {len(args.tasks)} 个")
    labels = [s.strip() for s in args.labels.split(",")]
    if len(labels) != 2:
        ap.error(f"--labels 须逗号分隔两个臂标签，得 {args.labels!r}")

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    report = {"generated": time.time(), "db": args.db, "pairs": []}
    pairs = [args.tasks[i : i + 2] for i in range(0, len(args.tasks), 2)]
    for ta, tb in pairs:
        sa, a_src = task_ph(db, ta)
        sb, b_src = task_ph(db, tb)
        overlap = len(a_src & b_src)
        same = a_src == b_src
        for lab, tid, st in ((labels[0], ta, sa), (labels[1], tb, sb)):
            print(f"{lab} {tid}: {json.dumps(_shown(st), ensure_ascii=False)}")
        print(f"pair: src_overlap={overlap} same_src_ph={str(same).lower()}\n")
        report["pairs"].append(
            {
                "labels": labels,
                "a": {"task": ta, **sa},
                "b": {"task": tb, **sb},
                "src_overlap": overlap,
                "same_src_ph": same,
            }
        )
    db.close()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
