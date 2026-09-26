"""layoutqc 离线重放——vault 现行封件过工作树检测器，不写账本。

动机：检测器口径修订后账上 sig_counts 全是旧口径产出；spec 重跑会被
dedup 全跳（ok 是 DONE 态），--regen 又是付费字节闸不适用于免费质检段。
本工具把每格 vault 封件（splice pdf/log + layoutqc 封件内的 zh txlm
回填）直接喂 specs._layoutqc.qc_paper，产新口径 findings/sig_counts 并
与账上末条非 dedup 账做逐格差分——修订效果的实测面。

保真口径/已知偏差：
- 测的是 vault 现行封件，不是旧 qc 当时扫的那版字节——splice 重封过
  的格新旧差含产物漂移（属「现行产物真实质量」，语义上更对）。
- zh txlm 回填序：splice 封件 → layoutqc 封件 <stem>.zh.txlm → 缺则
  txlm_src=missing（zh 侧 marks_absent 仍照报——运行时同样缺席即真
  信号；geom={} 几何面与运行时口径一致）。
- base 臂未建的格 base_dir=None，与新检测器「未建对照臂不报错」口径
  一致；marks_era 恒 True（e2e_real marks 默认 True 且本批全 True）。
- 副本选择 (variant,altseq) 感知：默认 restore 取最低 altseq，但
  重封留下的 altseq=0 常是 state-only 残壳，且 rekey 只搬 zh/state
  ——老胞 splice 完好副本常只在 '-' 键域。本工具逐格在全 variant
  键域挑「含 splice 的完好副本」（.tex 齐者优先——artifact-only
  封件测不了 env 面；再按含 layoutqc 封件、zone、低 altseq、
  variant 字典序排）；--variant 钉回单变体旧口径。
- artifact-only 封件的格遮蔽 layout:dropped_env（splice 无 .tex 时
  env_inventory 恒空会全量误报）并标 env_masked——env 缺口在
  本批不可离线测量。
- 账本 mode=ro、vault mode=link（硬链只读契约）——全工具零写账。

用法：.venv/bin/python tools/qc_replay.py [--out DIR] [--jobs N] [--id X ...]
      [--variant V] [--arm A]   # soak 波封在 '-' arm 下须 --arm -
输出：<out>/papers.jsonl（逐格 findings+ 新旧 sig_counts）+ <out>/summary.json
      + stdout 聚合表。默认 <out>=tmp/qc_replay/。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "bench" / "py"))
sys.path.insert(0, str(_REPO / "src"))

from kernel import vault  # noqa: E402
from kernel.lake import cell_dir  # noqa: E402
from specs._layoutqc import _tier_of, qc_paper  # noqa: E402

_BENCH = Path(
    os.environ.get("TEXLATE_BENCH_ROOT", Path.home() / ".local/share/texlate-bench")
)
_ARM = "real"


def _splice_copy_index(
    variant: str | None = None, arm: str = _ARM
) -> dict[str, tuple[str, str]]:
    """{idc: (variant, altseq)}——逐格挑「含 splice 的完好副本」。默认
    restore 选最低 altseq，但重跑/重封留下的 altseq=0 副本常是
    state-only 残壳（splice 活在 altseq≥1 副本里）；rekey 只搬
    zh/state，老胞 splice 完好副本常只在 '-' 键域——variant 维放开
    竞争（pin 时退化为单变体）。含 layoutqc 封件的副本优先——同副本
    内 qc.json 与 splice 是同一测量对。"""
    best: dict[str, tuple] = {}
    for _mp, key, meta in vault._iter_metas():  # noqa: SLF001
        if key is None or meta is None or key[1] != arm:
            continue
        if variant is not None and key[2] != variant:
            continue
        files = meta.get("files") or {}
        if "splice" not in files or not vault._copy_intact(meta):  # noqa: SLF001
            continue
        try:
            z = vault._norm_zone(meta.get("zone", "pending"))  # noqa: SLF001
        except ValueError:
            continue
        # artifact-only 封件（splice 只封 pdf/log/txlm）测不了 env 面——
        # 有 .tex 的副本优先，让 dropped_env/marks_coverage 可测
        sp = files["splice"]
        has_tex = any(
            (f.get("path", "") if isinstance(f, dict) else str(f)).endswith(".tex")
            for f in sp
        )
        score = (
            0 if has_tex else 1,
            0 if "layoutqc" in files else 1,
            vault._ZONE_RANK.get(z, 4),  # noqa: SLF001
            int(key[3] or 0),
            key[2],  # 全同分残局按 variant 定胜负——确定性兜底
        )
        cur = best.get(key[0])
        if cur is None or score < cur[0]:
            best[key[0]] = (score, key[2], key[3])
    return {idc: (v, a) for idc, (_s, v, a) in best.items()}


def _cell_list(
    only: set[str] | None, variant: str | None, arm: str = _ARM
) -> list[dict]:
    """末条非 dedup layoutqc 账/格 + main_rel（compile 账优先 route 兜底）
    + 旧 sig_counts——重放对象集与对照面一次取齐。"""
    db = sqlite3.connect(f"file:{_BENCH}/ledger/index.sqlite?mode=ro", uri=True)
    db.execute("CREATE TEMP TABLE ids(idc TEXT PRIMARY KEY)")
    if only:
        # --id 直接驱动枚举：波形格可能没跑过 layoutqc（lq 降为 LEFT JOIN、
        # prev_* 留空），有 splice 副本的照常重放、缺的落成 no_splice 诊断行
        db.executemany("INSERT INTO ids VALUES (?)", [(i,) for i in only])
    else:
        db.execute(
            "INSERT INTO ids SELECT DISTINCT idc FROM records"
            " WHERE stage='layoutqc' AND status!='dedup'"
        )
    rows = db.execute(
        """
        WITH lc AS (
          SELECT idc, json_extract(metrics,'$.main_rel') mr,
                 ROW_NUMBER() OVER (PARTITION BY idc ORDER BY ts DESC) rn
          FROM records WHERE stage='compile' AND status!='dedup'
            AND json_extract(metrics,'$.main_rel') IS NOT NULL
        ), lr AS (
          SELECT idc, json_extract(metrics,'$.main_rel') mr,
                 ROW_NUMBER() OVER (PARTITION BY idc ORDER BY ts DESC) rn
          FROM records WHERE stage='route' AND status!='dedup'
            AND json_extract(metrics,'$.main_rel') IS NOT NULL
        ), lp AS (
          SELECT idc, json_extract(metrics,'$.main_rel') mr,
                 ROW_NUMBER() OVER (PARTITION BY idc ORDER BY ts DESC) rn
          FROM records WHERE stage='parse' AND status!='dedup'
            AND json_extract(metrics,'$.main_rel') IS NOT NULL
        ), lq AS (
          SELECT idc, status, json_extract(metrics,'$.sig_counts') sc,
                 ROW_NUMBER() OVER (PARTITION BY idc ORDER BY ts DESC) rn
          FROM records WHERE stage='layoutqc' AND status!='dedup'
        )
        SELECT i.idc, q.status, q.sc, COALESCE(c.mr, r.mr, p.mr) FROM ids i
        LEFT JOIN lq q ON q.idc=i.idc AND q.rn=1
        LEFT JOIN lc c ON c.idc=i.idc AND c.rn=1
        LEFT JOIN lr r ON r.idc=i.idc AND r.rn=1
        LEFT JOIN lp p ON p.idc=i.idc AND p.rn=1
        """
    ).fetchall()
    copies = _splice_copy_index(variant, arm)
    out = [
        {
            "idc": i,
            "prev_status": s,
            "prev_sig_counts": json.loads(sc) if sc else {},
            "main_rel": m,
            "copy": copies.get(i),
        }
        for i, s, sc, m in rows
    ]
    return sorted(out, key=lambda c: c["idc"])


def _backfill_txlm(paper: Path, splice: Path, main_rel: str) -> str:
    """运行时 zh txlm 常未随 splice 封存，但被拷进 layoutqc 封件
    （<stem>.zh.txlm）——回填回 splice 树复现运行时输入面。"""
    stem = Path(main_rel).stem
    dst = splice / Path(main_rel).parent / f"{stem}.txlm"
    if dst.exists():
        return "splice"
    for c in sorted(paper.glob(f"layoutqc.*/{stem}.zh.txlm")) or sorted(
        paper.glob(f"**/{stem}.zh.txlm")
    ):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(c, dst)
        return "layoutqc_vault"
    return "missing"


def _replay_cell(
    item: dict, work: Path, arm: str = _ARM, marks_era: bool = True
) -> dict:
    idc, main_rel = item["idc"], item["main_rel"]
    paper = work / idc
    paper.mkdir(parents=True, exist_ok=True)
    out = {
        "idc": idc,
        "prev_status": item["prev_status"],
        "prev_sig_counts": item["prev_sig_counts"],
        "main_rel": main_rel,
    }
    if item["copy"] is None:
        out["error"] = "no_splice"
        return out
    variant, altseq = item["copy"]
    out["variant"] = variant
    out["altseq"] = altseq
    try:
        vault.restore(idc, arm, variant, paper, altseq=altseq, mode="link")
    except vault.VaultError as e:
        out["error"] = f"vault:{e}"
        return out
    splice = paper / vault._work_dirname("splice", arm, variant)  # noqa: SLF001
    if not splice.is_dir():
        out["error"] = "no_splice"
        return out
    if not main_rel:
        out["error"] = "no_main_rel"
        return out
    out["txlm_src"] = _backfill_txlm(paper, splice, main_rel)
    cell = cell_dir(idc, "arxiv")
    src = cell / "extracted" if (cell / "extracted").is_dir() else cell
    try:
        qc = qc_paper(
            splice_dir=splice,
            main_rel=main_rel,
            base_dir=None,
            src_dir=src if src.is_dir() else None,
            marks_era=marks_era,
            flag_dir=None,
        )
        drop_sigs: set[str] = set()
        # artifact-only 封件无 .tex → env_inventory(splice) 恒空，
        # dropped_env 会把 src 全部 env 报成「丢」——遮蔽此不可测量面
        if not any(splice.rglob("*.tex")):
            drop_sigs.add("layout:dropped_env")
            out["env_masked"] = True
        # 非 marks-era 管线（soak 链不产 txlm）marks_absent 恒发=纯噪音
        if not marks_era:
            drop_sigs.add("layout:marks_absent")
        if drop_sigs:
            qc["findings"] = [f for f in qc["findings"] if f["sig"] not in drop_sigs]
            qc["sig_counts"] = dict(Counter(f["sig"] for f in qc["findings"]))
            qc["flagged_pages"] = sorted(
                {
                    p
                    for f_ in qc["findings"]
                    for p in (
                        [f_["page"]]
                        if isinstance(f_.get("page"), int)
                        else f_.get("pages") or []
                    )
                }
            )
            qc["qc_tier"] = _tier_of(qc["findings"], marks_era=marks_era)
        out.update(
            sig_counts=qc["sig_counts"],
            qc_tier=qc["qc_tier"],
            n_findings=len(qc["findings"]),
            flagged_pages=qc["flagged_pages"],
            findings=qc["findings"],
        )
    except Exception as e:  # noqa: BLE001
        out["error"] = f"qc:{e}"
        out["trace"] = traceback.format_exc()[-2000:]
    return out


def _summarize(results: list[dict]) -> dict:
    sig = Counter()
    sigp = Counter()
    prev_sig = Counter()
    prev_sigp = Counter()
    tiers = Counter()
    errs = Counter()
    txlm = Counter()
    variants = Counter()
    masked = 0
    ok = 0
    for r in results:
        if "error" in r:
            errs[r["error"].split(":", 1)[0]] += 1
            continue
        ok += 1
        tiers[r["qc_tier"]] += 1
        txlm[r.get("txlm_src", "?")] += 1
        variants[r.get("variant", "?")] += 1
        masked += bool(r.get("env_masked"))
        for k, v in r["sig_counts"].items():
            sig[k] += v
            sigp[k] += 1
        for k, v in r["prev_sig_counts"].items():
            prev_sig[k] += v
            prev_sigp[k] += 1
    return {
        "cells_ok": ok,
        "errors": dict(errs),
        "txlm_src": dict(txlm),
        "variants": dict(variants),
        "env_masked": masked,
        "tiers": dict(tiers),
        "new": {
            "findings": dict(sig.most_common()),
            "papers": dict(sigp.most_common()),
        },
        "prev": {
            "findings": dict(prev_sig.most_common()),
            "papers": dict(prev_sigp.most_common()),
        },
    }


def _print(summary: dict) -> None:
    print(
        f"\nok={summary['cells_ok']} err={sum(summary['errors'].values())} "
        f"tiers={summary['tiers']} txlm_src={summary['txlm_src']} "
        f"variants={summary['variants']} env_masked={summary['env_masked']}"
    )
    for k, v in summary["errors"].items():
        print(f"  ERR {v:4d}  {k}")
    keys = sorted(set(summary["new"]["findings"]) | set(summary["prev"]["findings"]))
    print(f"{'sig':34s} {'old':>6s} {'new':>6s} {'Δ':>6s}  papers(old→new)")
    for k in keys:
        o = summary["prev"]["findings"].get(k, 0)
        n = summary["new"]["findings"].get(k, 0)
        op = summary["prev"]["papers"].get(k, 0)
        np_ = summary["new"]["papers"].get(k, 0)
        print(f"{k:34s} {o:6d} {n:6d} {n - o:+6d}  {op}→{np_}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="tmp/qc_replay", help="output dir")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--id", action="append", default=[], help="only these idc")
    ap.add_argument(
        "--variant",
        default=None,
        help="pin one variant ('-' for the null domain); default picks per cell",
    )
    ap.add_argument(
        "--arm",
        default=_ARM,
        help="vault arm to read ('-' for the null arm used by soak specs)",
    )
    ap.add_argument(
        "--marks-era",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="pipeline produced marked txlm (e2e_real); --no-marks-era for soak waves",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="qc_replay_", dir=out_dir))
    items = _cell_list(set(args.id) or None, args.variant, args.arm)
    print(f"cells: {len(items)}", flush=True)

    results = []
    with (
        ProcessPoolExecutor(max_workers=args.jobs) as ex,
        (out_dir / "papers.jsonl").open("w", encoding="utf-8") as fh,
    ):
        futs = [
            ex.submit(_replay_cell, it, work, args.arm, args.marks_era) for it in items
        ]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            results.append(r)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            if i % 20 == 0:
                fh.flush()
                print(f"  {i}/{len(items)}", flush=True)

    summary = _summarize(results)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
