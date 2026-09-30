"""corpus_v3 抽样段叶——eligible∧frame-join → cell 内随机配额 → sample_core/booster_pool。"""

from __future__ import annotations

import csv
import json
import random

from specs import _bootstrap
from specs import _corpus_common as cc
from specs._corpus_v3_base import (
    FRAME_LOOKUP_GZ,
    WORK,
    _read_jsonl,
    load_allocation,
    load_chunks,
)

_bootstrap.ensure()

# ---------------- sample (S3a) ----------------


def _sample(ctx):
    rng = random.Random(cc.SEED)
    alloc = {r["cluster_id"]: r for r in load_allocation()}
    mix: dict[str, dict[str, float]] = {}
    mix_path = cc.FRAME / "cluster-cat-mix.csv"
    if not mix_path.is_file():
        ctx.emit_note(f"frame 资产缺席 {mix_path.name}", level="warn")
        return "fail"
    with mix_path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            mix.setdefault(r["yymm"], {})[r["cat_group"]] = float(r["share"])
    lut = cc.load_frame_lookup(FRAME_LOOKUP_GZ)
    chunks = load_chunks()

    feats_by_cluster: dict[str, list[dict]] = {}
    for c in chunks:
        if c["state"] != "done":
            continue
        tag = f"{c['yymm']}_{c['chunk_no']:03d}"
        fp = WORK / "features" / f"{tag}.jsonl"
        if not fp.exists():
            continue
        for rec in _read_jsonl(fp):
            rec["_tag"] = tag
            feats_by_cluster.setdefault(c["cluster_id"], []).append(rec)

    selected: dict[str, list[dict]] = {}
    report = []
    booster_pool: dict[str, list[dict]] = {f"B{i:02d}": [] for i in range(1, 8)}

    for cid in sorted(alloc):
        row = alloc[cid]
        yymm, q = row["yymm"], row["quota_core"]
        feats = feats_by_cluster.get(cid, [])
        # join frame
        pool = []
        n_join_miss = 0
        for f in feats:
            fr = cc.frame_get(lut, f["id"])
            if fr is None:
                n_join_miss += 1
                f["cat_group"] = "unknown"
                f["license_class"] = "unknown"
            else:
                f["cat_group"] = fr["cat_group"]
                f["license_class"] = fr["license_class"]
                f["primary_cat"] = fr["primary_cat"]
                if fr["tar_yymm"] != yymm:
                    f["yymm_mismatch"] = True
            # 只有 frame 命中的成员进核心池 (事后分层权重需要 cat_group)
            if fr is not None and cc.eligible(f):
                pool.append(f)
            # ---- booster 候选预筛 (不中选也可入池, extract 阶段只挑最终提名) ----
            whys: dict[str, list[str]] = {}
            if f.get("docstyle"):
                whys["B01"] = ["documentstyle"]
            if f.get("non_utf8"):
                whys["B02"] = ["non_utf8"]
            if (f.get("n_tex_files") or 0) >= 10 or (f.get("input_depth") or 0) >= 3:
                whys["B03"] = [
                    f"n_tex={f.get('n_tex_files')}",
                    f"depth={f.get('input_depth')}",
                ]
            pc = f.get("primary_cat") or ""
            if (
                f.get("cat_group") in ("cs", "eess-stat-etc")
                or pc.startswith(("econ.", "q-fin."))
            ) and row["year_band"] in ("d_2017_20", "e_2021_25"):
                whys["B04"] = [f"low-tex-cat:{pc or f.get('cat_group')}"]
            fl = set(f.get("flags") or [])
            known_cls = {
                "article",
                "revtex",
                "revtex4",
                "revtex4-1",
                "revtex4-2",
                "amsart",
                "ieeetran",
                "llncs",
                "elsarticle",
                "mnras",
                "aa",
                "report",
                "book",
                "scrartcl",
                "memoir",
                "aastex",
            }
            vendored = any(
                d.lower() not in known_cls for d in (f.get("docclasses") or [])
            )
            if fl & {"minted", "pstricks"} or vendored:
                whys["B05"] = sorted(fl & {"minted", "pstricks"}) + (
                    ["vendored-cls"] if vendored else []
                )
            if (f.get("uncompressed_bytes") or 0) > 2 << 20:
                whys["B06"] = [f"uncompressed={f['uncompressed_bytes']}"]
            if f.get("format") in ("gz", "pdf", "stub", "error"):
                whys["B07"] = [f"format={f.get('format')}"]
            for cell, reasons in whys.items():
                booster_pool[cell].append(
                    {
                        "id": f["id"],
                        "cluster_id": cid,
                        "member": f["member"],
                        "_tag": f["_tag"],
                        "why": reasons,
                    }
                )

        shares = mix.get(yymm, {})
        by_group: dict[str, list[dict]] = {}
        for f in pool:
            by_group.setdefault(f["cat_group"], []).append(f)
        for v in by_group.values():
            rng.shuffle(v)
        # largest-remainder 配额
        targets, rema = {}, []
        for g, s in shares.items():
            t = q * s
            targets[g] = int(t)
            rema.append((t - int(t), g))
        for _ in range(q - sum(targets.values())):
            if not rema:
                break
            rema.sort(reverse=True)
            _, g = rema.pop(0)
            targets[g] += 1
        picked: list[dict] = []
        attain = {}
        for g, t in sorted(targets.items()):
            avail = by_group.get(g, [])
            take = min(t, len(avail))
            picked.extend(avail[:take])
            by_group[g] = avail[take:]
            attain[g] = (t, take)
        deficit = q - len(picked)
        if deficit > 0:
            rest = [f for v in by_group.values() for f in v]
            rng.shuffle(rest)
            picked.extend(rest[:deficit])
        for f in picked:
            f["layer"] = "core"
        selected[cid] = picked
        report.append(
            {
                "cluster_id": cid,
                "yymm": yymm,
                "quota": q,
                "members_scanned": len(feats),
                "eligible": len(pool),
                "frame_join_miss": n_join_miss,
                "picked": len(picked),
                "deficit": deficit,
                "attain": {
                    g: {"target": t, "got": got}
                    for g, (t, got) in sorted(attain.items())
                },
                "format_dist": {
                    k: sum(1 for f in feats if f.get("format") == k)
                    for k in ("tar", "gz", "pdf", "stub", "error")
                },
            }
        )

    # booster 池去掉核心中选
    core_ids = {f["id"] for lst in selected.values() for f in lst}
    for k, lst in booster_pool.items():
        booster_pool[k] = [c for c in lst if c["id"] not in core_ids]

    cc.atomic_write_text(
        WORK / "sample_core.json",
        json.dumps(
            {
                cid: [
                    {
                        k: f.get(k)
                        for k in (
                            "id",
                            "member",
                            "_tag",
                            "cat_group",
                            "license_class",
                            "primary_cat",
                            "blob_sha256",
                            "format",
                        )
                    }
                    for f in lst
                ]
                for cid, lst in selected.items()
            },
            indent=1,
        )
        + "\n",
    )
    cc.atomic_write_text(
        WORK / "booster_pool.json", json.dumps(booster_pool, indent=1) + "\n"
    )
    cc.atomic_write_text(
        WORK / "sample_report.json", json.dumps(report, indent=1) + "\n"
    )
    for r in report:
        att = ", ".join(f"{g}:{a['got']}/{a['target']}" for g, a in r["attain"].items())
        print(
            f"{r['cluster_id']} {r['yymm']} q={r['quota']} "
            f"pool={r['members_scanned']} elig={r['eligible']} "
            f"picked={r['picked']} miss={r['frame_join_miss']} | {att}"
        )
    cc.log(
        f"sample: {sum(r['picked'] for r in report)} core picks, "
        f"booster pool { {k: len(v) for k, v in booster_pool.items()} }"
    )
    return {
        "status": "ok",
        "metrics": {
            "core_picked": sum(r["picked"] for r in report),
            "deficit": sum(r["deficit"] for r in report),
            "frame_join_miss": sum(r["frame_join_miss"] for r in report),
            "booster_pool": sum(len(v) for v in booster_pool.values()),
        },
    }
