"""corpus_sw 前三段叶——footers/pool/assign（编目 → 列投影池 → 三层分流）。"""

from __future__ import annotations

import json
import random
import shutil
from collections import defaultdict

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs.corpus_sw.base import (
    SHARDS,
    _iter_jsonl,
    _sw,
    cat_group_of,
    yymm_recent,
)
from specs.corpus_sw.manifest import _all_manifest_ids
from specs.corpus_sw.worker import _hf_run

# ---------------------------------------------------------------- stages


def _shard_set(ctx) -> set[int] | None:
    raw = str(ctx.params.get("shards") or "").strip()
    if not raw:
        return None
    out = set()
    for tok in raw.split(","):
        t = tok.strip()
        if t:
            out.add(int(t))
    return out or None


def _footers(ctx):
    """47 分片 footer 编目 → durable/sw/footers/{n}.json + footers.json。

    分片缓存存在即跳过（跨 run 增量）；footers.json 每次按盘上缓存全集
    重写——shards 收窄只少抓，不写窄编目。
    """
    if shutil.which("uv") is None:
        return {"status": "error", "errors": [{"cat": "env", "msg": "uv not on PATH"}]}
    sw = _sw()
    fdir = sw / "footers"
    fdir.mkdir(parents=True, exist_ok=True)
    want = _shard_set(ctx) or set(range(1, SHARDS + 1))
    fetched = cached = 0
    for n in sorted(want):
        if not 1 <= n <= SHARDS:
            continue
        out = fdir / f"{n:04d}.json"
        if out.exists():
            cached += 1
            continue
        rc, tail = _hf_run(("footer", n, out), timeout_s=300)
        if rc != 0 or not out.exists():
            ctx.emit(
                {
                    "stage": "footers",
                    "metric": "sw_footer",
                    "shard": n,
                    "rc": rc,
                    "err": tail,
                }
            )
            return {
                "status": "error",
                "errors": [
                    {"cat": "upstream", "msg": f"footer {n:04d} rc={rc}: {tail}"}
                ],
                "metrics": {"shard": n, "fetched": fetched, "cached": cached},
            }
        fetched += 1
        ctx.emit({"stage": "footers", "metric": "sw_footer", "shard": n, "rc": 0})
    cat = {}
    for fp in sorted(fdir.glob("*.json")):
        try:
            cat[int(fp.stem)] = json.loads(fp.read_text())
        except (OSError, ValueError):
            continue
    cc.atomic_write_text(sw / "footers.json", json.dumps(cat, indent=1) + "\n")
    min_yymm = str(ctx.params.get("min_yymm") or "2501")
    recent = sum(
        1
        for s in cat.values()
        for r in s["rgs"]
        if yymm_recent(r.get("ymax"), min_yymm)
    )
    return {
        "status": "ok",
        "metrics": {
            "shards": len(cat),
            "fetched": fetched,
            "cached": cached,
            "recent_rgs": recent,
            "footers": str(sw / "footers.json"),
        },
    }


def _recent_rgs(cat: dict, min_yymm: str, shard_set: set[int] | None) -> list[dict]:
    out = [
        {"shard": int(sn), **r}
        for sn, s in cat.items()
        for r in s["rgs"]
        if yymm_recent(r.get("ymax"), min_yymm)
        and (shard_set is None or int(sn) in shard_set)
    ]
    return sorted(out, key=lambda x: (x["ymin"], x["shard"], x["i"]))


def _pool(ctx):
    """近期行组列投影 → durable/sw/pool_parts/{s}_{i}.jsonl + pool.jsonl。"""
    sw = _sw()
    fp = sw / "footers.json"
    if not fp.exists():
        return {"status": "error", "errors": [{"cat": "env", "msg": f"missing {fp}"}]}
    if shutil.which("uv") is None:
        return {"status": "error", "errors": [{"cat": "env", "msg": "uv not on PATH"}]}
    cat = json.loads(fp.read_text())
    min_yymm = str(ctx.params.get("min_yymm") or "2501")
    rgs = _recent_rgs(cat, min_yymm, _shard_set(ctx))
    rg_cap = int(ctx.params.get("rg_limit") or 0)
    if rg_cap > 0:
        rgs = rgs[:rg_cap]
    pdir = sw / "pool_parts"
    pdir.mkdir(parents=True, exist_ok=True)
    n_rows = fetched = cached = 0
    lines: list[str] = []
    for ent in rgs:
        sn, i = ent["shard"], ent["i"]
        cache = pdir / f"{sn:04d}_{i:03d}.jsonl"
        if not cache.exists():
            rc, tail = _hf_run(("pool", sn, i, min_yymm, cache), timeout_s=600)
            if rc != 0 or not cache.exists():
                ctx.emit(
                    {
                        "stage": "pool",
                        "metric": "sw_pool_rg",
                        "shard": sn,
                        "rg": i,
                        "rc": rc,
                        "err": tail,
                    }
                )
                return {
                    "status": "error",
                    "errors": [
                        {"cat": "upstream", "msg": f"pool {sn:04d}/{i} rc={rc}: {tail}"}
                    ],
                    "metrics": {"n_rows": n_rows, "fetched": fetched, "cached": cached},
                }
            fetched += 1
        else:
            cached += 1
        part = [ln for ln in cache.read_text().splitlines() if ln.strip()]
        lines.extend(part)
        n_rows += len(part)
        ctx.emit(
            {
                "stage": "pool",
                "metric": "sw_pool_rg",
                "shard": sn,
                "rg": i,
                "rows": len(part),
            }
        )
    cc.atomic_write_text(sw / "pool.jsonl", "\n".join(lines) + ("\n" if lines else ""))
    return {
        "status": "ok",
        "metrics": {
            "n_rows": n_rows,
            "rgs": len(rgs),
            "fetched": fetched,
            "cached": cached,
            "pool": str(sw / "pool.jsonl"),
        },
    }


def _assign(ctx):
    """三层分流：sw 臂 ~1 行组/月组内采样 + eprint 臂 holdout/dev_recent。"""
    sw = _sw()
    pool_path = sw / "pool.jsonl"
    if not pool_path.exists():
        return {
            "status": "error",
            "errors": [{"cat": "env", "msg": f"missing {pool_path}"}],
        }
    rng = random.Random(int(ctx.params.get("seed") or 42))
    n_sw = int(ctx.params.get("n_sw") or 1200)
    n_ho = int(ctx.params.get("n_ep_holdout") or 300)
    n_dr = int(ctx.params.get("n_ep_devrecent") or 300)
    pool = [r for r in _iter_jsonl(pool_path) if r.get("id")]
    taken = _all_manifest_ids()
    pool = [r for r in pool if cc.canon_or_self(r["id"]) not in taken]
    by_month: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_month[r["yymm_id"][:4]].append(r)
    months = sorted(by_month)
    if not months:
        return {
            "status": "error",
            "errors": [{"cat": "empty", "msg": "pool has no months"}],
            "metrics": {"pool": len(pool)},
        }

    # 脱水臂：每月 1 个行组（rg 是该月内连续 id 段），组内均匀采样
    sw_picks: list[dict] = []
    used_ids: set[str] = set()
    per_month = max(1, round(n_sw / len(months)))
    for m in months:
        rows = by_month[m]
        rgs = sorted({(r["shard"], r["rg"]) for r in rows})
        pick_rg = rng.choice(rgs)
        cand = [r for r in rows if (r["shard"], r["rg"]) == pick_rg]
        rng.shuffle(cand)
        for r in cand[:per_month]:
            used_ids.add(r["id"])
            sw_picks.append(
                {
                    "id": r["id"],
                    "yymm": m,
                    "cat_group": cat_group_of(r["cats"]),
                    "shard": r["shard"],
                    "rg": r["rg"],
                }
            )

    # eprint 臂：剩余全池按月分层均匀切 holdout/dev_recent 两段
    ep_pool = [r for r in pool if r["id"] not in used_ids]
    ep_by_month: dict[str, list[dict]] = defaultdict(list)
    for r in ep_pool:
        ep_by_month[r["yymm_id"][:4]].append(r)
    for v in ep_by_month.values():
        rng.shuffle(v)
    per_m_ho = max(1, n_ho // len(months))
    per_m_dr = max(1, n_dr // len(months))
    ho: list[dict] = []
    dr: list[dict] = []
    for m in months:
        cand = ep_by_month.get(m, [])
        ho.extend(
            {"id": r["id"], "yymm": m, "cat_group": cat_group_of(r["cats"])}
            for r in cand[:per_m_ho]
        )
        dr.extend(
            {"id": r["id"], "yymm": m, "cat_group": cat_group_of(r["cats"])}
            for r in cand[per_m_ho : per_m_ho + per_m_dr]
        )
    rng.shuffle(ho)
    rng.shuffle(dr)
    ho, dr = ho[:n_ho], dr[:n_dr]

    out_sw = sw / "assign_sw.jsonl"
    out_ho = sw / "assign_holdout.jsonl"
    out_dr = sw / "assign_dev_recent.jsonl"
    cc.atomic_write_text(
        out_sw, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in sw_picks)
    )
    cc.atomic_write_text(
        out_ho, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in ho)
    )
    cc.atomic_write_text(
        out_dr, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in dr)
    )
    return {
        "status": "ok",
        "metrics": {
            "pool": len(pool),
            "months": len(months),
            "month_first": months[0],
            "month_last": months[-1],
            "n_sw": len(sw_picks),
            "n_ep_holdout": len(ho),
            "n_ep_devrecent": len(dr),
            "assign_sw": str(out_sw),
            "assign_holdout": str(out_ho),
            "assign_dev_recent": str(out_dr),
        },
    }
