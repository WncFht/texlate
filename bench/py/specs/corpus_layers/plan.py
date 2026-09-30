"""specs.corpus_layers.plan — corpus_layers plan 段叶（配额解算 + item 拣选 + plan.json 落盘）。

flat/fbias/flags 三 quota 路；frame 资产缺一件即 fail（frame_build ord-0
前置）；recent-only 层产空 plan ok-noop。
"""

from __future__ import annotations

import json
import math
from collections import Counter

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs.corpus_layers.base import (
    _FLAG_BAND_FRAC,
    FLAG_QUOTAS,
    POOL_MARGIN,
    PROFILES,
    YIELD_PER_CHUNK,
    _dirs,
    _ts,
)

# ---------------------------------------------------------------- plan


def _scanned_items(d: dict) -> set[str]:
    """本层已 .done 的 item（features/*.done——各层工作区自治，跨层不共享）。"""
    return {p.stem for p in d["dirs"].features.glob("*.done")}


def _plan(ctx):
    d = _dirs(ctx)
    layer = d["layer"]
    d["lwd"].mkdir(parents=True, exist_ok=True)
    profile = PROFILES.get(layer)
    if profile is None:
        plan = {
            "created": _ts(),
            "layer": layer,
            "recent_only": True,
            "params": {"seed": cc.SEED},
            "items": [],
        }
        cc.atomic_write_text(
            d["plan"], json.dumps(plan, indent=1, ensure_ascii=False) + "\n"
        )
        ctx.emit(
            {
                "metric": "layers_plan",
                "layer": layer,
                "recent_only": True,
                "items": 0,
            }
        )
        return "ok"
    missing = [f for f in cc.FRAME_NEEDS if not (d["frame"] / f).is_file()]
    if missing:
        ctx.emit_note(
            f"frame 资产缺 {missing} — frame_build(ord-0) 前置未跑",
            level="warn",
        )
        return "fail"
    rows_all = cc.load_manifest_rows(d["corpus"], cc.manifest_layers(d["corpus"]))
    core = [r for r in rows_all if r.get("layer") == "core"]
    if not core:
        ctx.emit_note("无 core manifest — 配额分母不存在", level="warn")
        return "fail"
    target = int(ctx.params["target"]) or int(profile["target"])
    cell_n = Counter(r["stratum_cell"] for r in core)
    rates_mode = rates_detail = "-"
    if profile["quota"] == "flags":
        quotas = dict(FLAG_QUOTAS)
    elif profile["quota"] == "fbias":
        try:
            fr_band, fr_cat, fr_all, rates_mode, rates_detail = cc.resolve_rates(
                ctx.params.get("rates_source"), rows_all, d["frame"]
            )
        except (RuntimeError, OSError, json.JSONDecodeError) as e:
            ctx.emit_note(f"rates_source 解析失败: {e}", level="warn")
            return "fail"
        bias = float(ctx.params["bias"])
        weights = {}
        for cell, n in cell_n.items():
            band, cat = cell.split("|", 1)
            if fr_all:
                rel = 0.5 * (
                    fr_band.get(band, fr_all) / fr_all
                    + fr_cat.get(cat, fr_all) / fr_all
                )
            else:
                rel = 1.0  # 无 bad 样本 → 无故障信号可加偏，配额退化纯比例
            weights[cell] = n * (1 + bias * (rel - 1))
        quotas = cc.largest_remainder(weights, target)
    else:  # flat——core cell 配比直扩
        quotas = cc.largest_remainder({c: float(n) for c, n in cell_n.items()}, target)
    cands = cc.candidate_items(
        d["frame"],
        _scanned_items(d),
        excl_months=(
            set(cc.yymm2cluster(d["frame"]))
            if profile["exclude_cluster_months"]
            else set()
        ),
        bands=profile["bands"],
    )
    picked: list[dict] = []
    if profile["quota"] == "flags":
        # 矿层 item 量按旗标密度估算：deadpkg/2.09 在旧档占比高，按总目标放大
        n_items = max(4, math.ceil(target * POOL_MARGIN / YIELD_PER_CHUNK))
        for band in sorted(cands):
            per_band = math.ceil(n_items * _FLAG_BAND_FRAC.get(band[0], 0.0))
            picked.extend(cc.order_items(cands[band], set())[:per_band])
    else:
        band_q = Counter()
        for cell, q in quotas.items():
            band_q[cell.split("|")[0]] += q
        for band, qsum in sorted(band_q.items()):
            members_needed = qsum / 0.91 * POOL_MARGIN
            n_items = max(2, math.ceil(members_needed / YIELD_PER_CHUNK))
            picked.extend(cc.order_items(cands.get(band, []), set())[:n_items])
    plan = {
        "created": _ts(),
        "layer": layer,
        "profile": {k: v for k, v in profile.items() if k != "bands"},
        "params": {
            "seed": cc.SEED,
            "pool_margin": POOL_MARGIN,
            "target": target,
            "rates_source": str(ctx.params.get("rates_source") or ""),
            "rates_mode": rates_mode,
        },
        "quotas": dict(sorted(quotas.items())),
        "items": picked,
    }
    cc.atomic_write_text(
        d["plan"], json.dumps(plan, indent=1, ensure_ascii=False) + "\n"
    )
    gb = sum(i["size"] for i in picked) / 1e9
    ctx.emit(
        {
            "metric": "layers_plan",
            "layer": layer,
            "quota": profile["quota"],
            "rates_mode": rates_mode,
            "rates_detail": rates_detail,
            "cells": len(quotas),
            "items": len(picked),
            "gb": round(gb, 1),
            "quota_sum": sum(quotas.values()),
            "target": target,
        }
    )
    return "ok"
