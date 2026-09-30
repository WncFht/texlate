"""specs.corpus_layers.extract — corpus_layers extract 段叶（池装载 + 配额/旗标选样 + 落 manifest）。

quota 路走 cell 池种子 shuffle 取头；flags 路走 FLAG_QUOTAS 稀有优先 +
old-era 回填；topup 模式按 select_stats deficit 补缺。
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs.corpus_layers.base import (
    _FAILMINE_FILL_CAP,
    FLAG_QUOTAS,
    PROFILES,
    _dirs,
)

# ---------------------------------------------------------------- extract


def _load_pool(ctx, d: dict, profile: dict) -> dict[str, dict]:
    """本层 features → {canon_id: rec}（eligible + 月份闸 + 全库去重）。"""
    excl = cc.existing_ids(d["corpus"])
    excl_months = (
        set(cc.yymm2cluster(d["frame"])) if profile["exclude_cluster_months"] else set()
    )
    cand: dict[str, dict] = {}
    for fp in sorted(d["dirs"].features.glob("*.jsonl")):
        for f in cc.iter_jsonl(fp):
            if not cc.eligible(f):
                continue
            pid = cc.canon_id(str(f["id"]))
            if pid in excl:
                continue
            if cc.member_yymm(f["member"]) in excl_months:
                continue
            cand[pid] = f
    return cand


def _flag_hit(f: dict, flag: str) -> bool:
    if flag == "docstyle209":
        return bool(f.get("docstyle"))
    return flag in (f.get("flags") or [])


def _frame_lut(ctx, d: dict, pool_ids) -> dict | None:
    try:
        lookup = cc.ensure_frame_lookup(d["frame"], d["build_root"])
    except Exception as e:
        ctx.emit_note(f"frame_lookup 不可用: {e}", level="warn")
        return None
    return cc.frame_filter(set(pool_ids), lookup)


def _select_quota(
    ctx, d: dict, profile: dict, quotas: dict[str, int]
) -> tuple[list[dict], dict] | None:
    """cell 配额选样：frame join → cell 池 → 种子 shuffle 取头。"""
    rng = random.Random(cc.SEED)
    cand = _load_pool(ctx, d, profile)
    lut = _frame_lut(ctx, d, cand.keys())
    if lut is None:
        return None
    c2y = cc.yymm2cluster(d["frame"])
    pools: dict[str, list[dict]] = defaultdict(list)
    for pid, f in cand.items():
        fr = cc.frame_get(lut, pid)
        if fr is None:
            continue  # join miss → 不进 cell 池（与原管线同口径）
        band = f.get("band") or cc.band_of_yymm(cc.member_yymm(f["member"]))
        cell = f"{band}|{fr['cat_group']}"
        if cell not in quotas:
            continue
        f["cat_group"] = fr["cat_group"]
        f["license_class"] = fr["license_class"]
        f["_cell"] = cell
        f["cluster_id"] = c2y.get(cc.member_yymm(f["member"]))
        pools[cell].append(f)
    for v in pools.values():
        rng.shuffle(v)
    sel: list[dict] = []
    stats = {}
    for cell, q in sorted(quotas.items()):
        pool = pools.get(cell, [])
        take = min(q, len(pool))
        sel.extend(pool[:take])
        stats[cell] = {
            "quota": q,
            "take": take,
            "avail": len(pool),
            "deficit": q - take,
        }
    return sel, stats


def _select_flags(ctx, d: dict, profile: dict) -> tuple[list[dict], dict] | None:
    """旗标选样：FLAG_QUOTAS 稀有优先顺序填充；短收→old-era 随机回填。"""
    rng = random.Random(cc.SEED)
    cand = _load_pool(ctx, d, profile)
    lut = _frame_lut(ctx, d, cand.keys())
    if lut is None:
        return None
    c2y = cc.yymm2cluster(d["frame"])
    for pid, f in cand.items():
        fr = cc.frame_get(lut, pid) or {}
        f["cat_group"] = fr.get("cat_group") or "unknown"
        f["license_class"] = fr.get("license_class")
        f["cluster_id"] = c2y.get(cc.member_yymm(f["member"]))
    picked: dict[str, dict] = {}
    stats = {}
    for flag, q in FLAG_QUOTAS:
        pool = [
            f for pid, f in cand.items() if pid not in picked and _flag_hit(f, flag)
        ]
        rng.shuffle(pool)
        take = pool[:q]
        for f in take:
            f["_cell"] = f"flag:{flag}"
            picked[cc.canon_id(str(f["id"]))] = f
        stats[f"flag:{flag}"] = {
            "quota": q,
            "take": len(take),
            "avail": len(pool),
            "deficit": q - len(take),
        }
    shortfall = sum(s["deficit"] for s in stats.values())
    if shortfall > 0:
        old_pool = [
            f
            for pid, f in cand.items()
            if pid not in picked and (f.get("band") or "z") <= _FAILMINE_FILL_CAP
        ]
        rng.shuffle(old_pool)
        for f in old_pool[:shortfall]:
            f["_cell"] = "failmine_fill"
            picked[cc.canon_id(str(f["id"]))] = f
        stats["failmine_fill"] = {
            "quota": shortfall,
            "take": min(shortfall, len(old_pool)),
            "avail": len(old_pool),
            "deficit": max(0, shortfall - len(old_pool)),
        }
    return list(picked.values()), stats


def _extract(ctx):
    d = _dirs(ctx)
    layer = d["layer"]
    profile = PROFILES.get(layer)
    if profile is None:
        ctx.emit(
            {
                "metric": "layers_extract",
                "layer": layer,
                "recent_only": True,
                "selected": 0,
            }
        )
        return "ok"
    plan = cc.load_plan(d["plan"])
    if plan is None:
        ctx.emit_note(f"{d['plan'].name} 缺 — 先跑 plan", level="warn")
        return "fail"
    if profile["quota"] == "flags":
        out = _select_flags(ctx, d, profile)
    else:
        out = _select_quota(ctx, d, profile, plan["quotas"])
    if out is None:
        return "fail"
    sel, stats = out
    limit = int(ctx.params.get("limit") or 0)
    if limit:
        sel = sel[:limit]
    d["lwd"].mkdir(parents=True, exist_ok=True)
    cc.atomic_write_text(d["select_stats"], json.dumps(stats, indent=1))
    if ctx.params.get("topup"):
        manifest = d["manifest"]
        done = {
            cc.canon_id(str(r["id"])) for r in cc.read_jsonl(manifest) if r.get("id")
        }
        have = Counter(r.get("stratum_cell") for r in cc.read_jsonl(manifest))
        need = {c: s.get("quota", 0) - have.get(c, 0) for c, s in stats.items()}
        keep: list[dict] = []
        for rec in sel:
            if cc.canon_id(str(rec["id"])) in done:
                continue
            cell = rec["_cell"]
            if need.get(cell, 0) > 0:
                need[cell] -= 1
                keep.append(rec)
        sel = keep
    return cc.extract_selected(
        ctx,
        sel,
        d,
        layer=layer,
        cluster_prefix=profile["cluster_prefix"],
        reason=layer,
        metric="layers_extract",
        emit_extra={"layer": layer},
    )
