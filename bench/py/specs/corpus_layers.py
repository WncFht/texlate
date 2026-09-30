"""corpus_layers — 扩库层构建器 spec（holdout / dev_vol / dev_failmine / dev_recent）。

build_corpus_layers.py 的 spec 重写（trizone-ledger v2，无旧兼容）：
items = 每层一 cell（id=层名，params.layer 注入）；bulk 链
plan→scan→extract→qc，recent 正交臂（needs=[]，ids_file 闸）声明在 qc 前，
使 qc 见到本 run eprint 实收。

    bench run bench/py/specs/corpus_layers.py
    bench run corpus_layers --param layers=holdout,dev_vol
    bench run corpus_layers --param ids_file='sw/assign_{layer}.jsonl'

层剖面（PROFILES verbatim）：

- ``holdout``      flat 2700（core cell 配比直扩，月份与 30 个 core 簇月
                   不相交 → 时间外推）+ ~300 eprint（acquire_source 全量
                   blob——holdout 必须带图不走 sw 脱水 → figures_stripped=false）。
- ``dev_vol``      fbias 2000（失败率偏置 λ=bias，expand 同 rates_source 解析）。
- ``dev_failmine`` flags 1500（deadpkg/pdftex_prim/babel_german/docstyle209/
                   minted/pstricks/epsfig 旗标配额稀有优先填充，短收 →
                   old-era 随机合格成员回填 'failmine_fill'）。
- ``dev_recent``   recent-only——bulk 链全 ok-noop，账本靠 recent 臂。

口径/资产变化（旧世界已灭处全部 fail-closed 或显式标注）：

- work_v3 已灭 → 工作区 ``~/.local/state/texlate/corpus-build/layers/{layer}/``
  （TarDirs 同构布局）；plan/select_stats/records/qc.md/recent_fail 落层目录。
- frame 资产（item-index/tiger-files/allocation-core/cluster-cat-mix +
  frame_lookup）由 frame_build(ord-0) 供——缺一件 bulk 链 plan=fail；
  recent 臂不需要 frame（cat_group 来自 assign 行）。
- n100 故障率文件已灭 → fbias 走 ``rates_source`` 三路（run ref / rates
  json / flat fallback），与 corpus_expand 同一解析码（verbatim 复制保持
  文件级解耦）；flat_fallback 时 ``rates_mode`` metric 显式标注。
- ``ids_file`` 支持 ``{layer}`` 占位；缺省自动解析
  ``{lake_durable}/sw/assign_{layer}.jsonl``（corpus_sw assign 臂产物），
  不存在 → eprint 层 recent=skip 等待，bulk-only 层 recent=ok noop。
- recent 臂预算：``recent_limit``=单轮尝试封顶（默认 85），``day_budget``
  走持久化 RateLimiter（``{lwd}/ratelimit.json``，默认 180/日）；截断 →
  ``{"status":"error","errors":[{cat:"budget"}]}`` retriable 续跑（corpus_hot
  同口径——DONE 态跨 run dedup 会把截尾误记完成，error 是唯一可续跑词）。
"""

from __future__ import annotations

import json
import math
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

from kernel import lake, paths
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc

# 层剖面：quota=flat（core 配比直扩）/ fbias（失败率偏置，expand 配方）/
# flags（矿层签名旗标定向）。scale 仅文档义——largest_remainder 按 target
# 归一，不读 scale（旧构建器同）。
PROFILES = {
    "holdout": {
        "target": 2700,
        "quota": "flat",
        "scale": 2.7,
        "exclude_cluster_months": True,
        "cluster_prefix": "HO",
        "bands": "abcde",
    },
    "dev_vol": {
        "target": 2000,
        "quota": "fbias",
        "scale": 2.0,
        "bias": 1.0,
        "exclude_cluster_months": False,
        "cluster_prefix": "DV",
        "bands": "abcde",
    },
    "dev_failmine": {
        "target": 1500,
        "quota": "flags",
        "exclude_cluster_months": False,
        "cluster_prefix": "DF",
        # 矿层主采 2017 前月块——deadpkg/2.09/pdftex 原语密度都在旧档
        "bands": "abc",
    },
}
LAYER_NAMES = (*tuple(PROFILES), "dev_recent")
#: eprint recent 臂服务的层（sw assign 只对这两层切 id）。
EPRINT_LAYERS = {"holdout", "dev_recent"}

# failmine 旗标配额（稀有优先顺序选样——一稿多旗时先填最稀有的坑）
FLAG_QUOTAS = [
    ("pdftex_prim", 150),
    ("babel_german", 75),
    ("deadpkg", 600),
    ("docstyle209", 300),
    ("minted", 75),
    ("pstricks", 150),
    ("epsfig", 150),
]
YIELD_PER_CHUNK = 280  # 合格成员/chunk 经验值（expand 实测口径 ~200-400）
POOL_MARGIN = 1.6  # join_miss/短收/不合格余量
_FLAG_BAND_FRAC = {"a": 0.45, "b": 0.35, "c": 0.2}
#: 矿层回填带——old-era = a/b/c 三带（deadpkg/2.09 原语密度区）。
_FAILMINE_FILL_CAP = "c_2012_16"


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _layer(ctx) -> str:
    return str(ctx.params.get("layer") or "")


def _dirs(ctx) -> dict:
    p = ctx.params
    layer = _layer(ctx)
    wd_root = Path(str(p.get("workdir") or "")).expanduser()
    lwd = wd_root / layer
    corpus = Path(str(p.get("corpus_dir") or "")).expanduser()
    return {
        "layer": layer,
        "lwd": lwd,
        "dirs": cc.TarDirs.from_workdir(lwd),
        "plan": wd_root / f"{layer}_plan.json",
        "records": lwd / "extract_records.jsonl",
        "select_stats": lwd / "select_stats.json",
        "qc_md": lwd / "qc.md",
        "recent_fail": lwd / "recent_fail.jsonl",
        "corpus": corpus,
        "manifest": corpus / f"manifest_{layer}.jsonl",
        "frame": Path(str(p.get("frame_dir") or "")).expanduser(),
        "v3": Path(str(p.get("v3_workdir") or "")).expanduser(),
        "build_root": Path(str(p.get("build_root") or cc.BUILD_ROOT)).expanduser(),
    }


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
                rel = 1.0  # 无 bad 样本 → 无故障信号可加偏, 配额退化纯比例
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


# ---------------------------------------------------------------- scan


def _scan(ctx):
    d = _dirs(ctx)
    layer = d["layer"]
    if PROFILES.get(layer) is None:
        ctx.emit(
            {
                "metric": "layers_scan",
                "layer": layer,
                "recent_only": True,
                "items": 0,
            }
        )
        return "ok"
    plan = cc.load_plan(d["plan"])
    if plan is None:
        ctx.emit_note(f"{d['plan'].name} 缺/不可解析 — 先跑 plan", level="warn")
        return "error"
    items = plan["items"]
    limit = int(ctx.params.get("limit") or 0)
    if limit:
        items = items[:limit]
    errs = cc.scan_batch(items, d["dirs"], int(ctx.params["jobs"]), tag=f"[{layer}]")
    ctx.emit(
        {
            "metric": "layers_scan",
            "layer": layer,
            "items": len(items),
            "failed": len(errs),
            "failed_items": errs[:20],
        }
    )
    if not errs:
        return "ok"
    return "partial" if len(errs) < len(items) else "error"


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


# ---------------------------------------------------------------- recent（eprint 正交臂）


def _load_recent_ids(path: Path) -> list[dict]:
    """sw assign 清单 → [{id, cat_group}]；jsonl 行或纯文本 id。"""
    out = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            r = json.loads(line)
            out.append({"id": r["id"], "cat_group": r.get("cat_group")})
        else:
            out.append({"id": line, "cat_group": None})
    return out


def _eprint_fetch_fn(pid, cand, prefix, layer, fetcher, cache, holder):
    """recent 臂 fetch_fn：acquire_source → entry 树搬进 stage + meta。

    永久负态 → {} 走 lake 'empty' 耐久负答；parked/budget → cc.HaltFetch 停批；
    其余非 OK → cc.TransientMiss 逐件跳过。meta 层字段在
    materialize_entry_into_stage 通用产物上覆写（cluster_id={prefix}-R /
    stratum_cell={layer}|recent / figures_stripped=false）。"""
    from texlate.arxiv.fetch import AcquireStatus, acquire_source

    permanent = {
        AcquireStatus.NOT_FOUND,
        AcquireStatus.PDF_ONLY,
        AcquireStatus.UNKNOWN_FORMAT,
        AcquireStatus.UNPACK_ERROR,
        AcquireStatus.TOO_LARGE,
    }

    def fn(idc, stage):
        res = acquire_source(pid, fetcher=fetcher, cache=cache)
        holder["res"] = res
        holder["fetched"] = True
        if res.status in (AcquireStatus.OK, AcquireStatus.HIT) and res.entry:
            meta = cc.materialize_entry_into_stage(
                res.entry.dir,
                stage,
                pid=pid,
                fm={},
                mechs="sw_assign",
                layer=layer,
            )
            meta.update(
                {
                    "cluster_id": f"{prefix}-R",
                    "stratum_cell": f"{layer}|recent",
                    "cat_group": cand.get("cat_group") or "recent",
                    "pick_reason": f"{layer}_recent",
                    # eprint 臂全量 blob——带图，与 sw 脱水臂 cell 区分
                    "figures_stripped": False,
                    "source": "sw_pool+arxiv_eprint",
                }
            )
            return meta
        if res.status in (AcquireStatus.PARKED, AcquireStatus.BUDGET):
            raise cc.HaltFetch(res.status.value)
        if res.status in permanent:
            holder["permanent"] = res.status.value
            return {}
        raise cc.TransientMiss(res.status.value)

    return fn


def _recent(ctx):
    d = _dirs(ctx)
    layer = d["layer"]
    if layer not in EPRINT_LAYERS:
        ctx.emit(
            {
                "metric": "layers_recent",
                "layer": layer,
                "ran": 0,
                "reason": "no_eprint_arm",
            }
        )
        return "ok"
    ids_file = str(ctx.params.get("ids_file") or "").strip()
    if ids_file:
        try:
            ids_path = Path(ids_file.format(layer=layer)).expanduser()
        except (KeyError, IndexError, ValueError):
            ids_path = Path(ids_file).expanduser()
        if not ids_path.is_file():
            ctx.emit_note(f"ids_file 不存在: {ids_path}", level="warn")
            return "fail"
    else:
        ids_path = paths.lake_durable_dir() / "sw" / f"assign_{layer}.jsonl"
        if not ids_path.is_file():
            ctx.emit(
                {
                    "metric": "layers_recent",
                    "layer": layer,
                    "ran": 0,
                    "reason": "no ids_file",
                    "tried": str(ids_path),
                }
            )
            return "skip"
    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher
    from texlate.arxiv.ratelimit import RateLimiter, RatePolicy

    d["lwd"].mkdir(parents=True, exist_ok=True)
    cands = _load_recent_ids(ids_path)
    limit = int(ctx.params["recent_limit"])
    day_budget = int(ctx.params["day_budget"])
    man = d["manifest"]
    done_ids = (
        {cc.canon_id(str(r["id"])) for r in cc.iter_jsonl(man) if r.get("id")}
        if man.exists()
        else set()
    )
    taken = cc.existing_ids(d["corpus"])
    profile = PROFILES.get(layer) or {}
    prefix = profile.get("cluster_prefix") or layer.upper()[:2]
    limiter = RateLimiter(
        state_path=d["lwd"] / "ratelimit.json",
        policy=RatePolicy(daily_budget=day_budget),
    )
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    n_new = n_ok = n_skip = n_err = 0
    truncated: dict | None = None
    with Fetcher(limiter=limiter) as fetcher, man.open("a", encoding="utf-8") as mf:
        cache = SourceCache(Path.home() / ".cache" / "texlate" / "src")
        for cand in cands:
            pid = str(cand["id"])
            pidc = cc.canon_id(pid)
            if pidc in done_ids:
                continue
            if pidc in taken:
                n_skip += 1  # 已在册（他层）——认账会跨层重复计数
                continue
            cell = lake.cell_dir(pid, source="arxiv_eprint")
            meta_fp = cell / "meta.json"
            if meta_fp.exists():
                try:
                    meta = json.loads(meta_fp.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    meta = {}
                if meta.get("layer") == layer and lake.is_complete(
                    pid, source="arxiv_eprint"
                ):
                    row = cc.manifest_row_from_meta(None, cell, default_layer=layer)
                    if row is not None:
                        mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                        mf.flush()
                        done_ids.add(pidc)
                # else: 并发异层臂已落此 cell——认账会跨层重复计数
                n_skip += 1
                continue
            if limit and n_new >= limit:
                truncated = {
                    "cat": "budget",
                    "msg": f"recent_limit {limit} reached — 续跑",
                }
                break
            holder: dict = {}
            try:
                lake.hydrate(
                    pid,
                    _eprint_fetch_fn(pid, cand, prefix, layer, fetcher, cache, holder),
                    "arxiv_eprint",
                    run_seq,
                )
            except cc.HaltFetch as hb:
                cc.append_jsonl(d["recent_fail"], {"id": pid, "status": str(hb)})
                if holder.get("fetched"):
                    n_new += 1
                truncated = {
                    "cat": "budget" if "budget" in str(hb) else "parked",
                    "msg": f"{hb} — 限流到顶，停批续跑",
                }
                n_err += 1
                break
            except cc.TransientMiss as tm:
                cc.append_jsonl(d["recent_fail"], {"id": pid, "status": str(tm)})
                if holder.get("fetched"):
                    n_new += 1
                n_skip += 1
                continue
            except Exception as e:
                if holder.get("fetched"):
                    n_new += 1
                cc.append_jsonl(
                    d["recent_fail"],
                    {"id": pid, "error": f"{type(e).__name__}: {e}"},
                )
                truncated = {
                    "cat": "exception",
                    "msg": f"{pid} acquire raised {type(e).__name__}: {e} — 停批续跑",
                }
                n_err += 1
                break
            if holder.get("fetched"):
                n_new += 1
            if lake.is_complete(pid, source="arxiv_eprint"):
                row = cc.manifest_row_from_meta(None, cell, default_layer=layer)
                if row is not None:
                    mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    mf.flush()
                done_ids.add(pidc)
                taken.add(pidc)
                n_ok += 1
            else:
                res = holder.get("res")
                cc.append_jsonl(
                    d["recent_fail"],
                    {
                        "id": pid,
                        "status": (res.status.value if res is not None else "empty"),
                        "detail": getattr(res, "detail", "") if res else "",
                        "permanent": holder.get("permanent"),
                    },
                )
                n_skip += 1
    remaining = sum(1 for c in cands if cc.canon_id(str(c["id"])) not in done_ids)
    ctx.emit(
        {
            "metric": "layers_recent",
            "layer": layer,
            "ran": 1,
            "cands": len(cands),
            "fetched": n_new,
            "ok": n_ok,
            "skip": n_skip,
            "err": n_err,
            "remaining": remaining,
            "recent_limit": limit,
            "day_budget": day_budget,
            "requests_today": getattr(limiter, "requests_today", None),
        }
    )
    if truncated is not None:
        return {"status": "error", "errors": [truncated]}
    if n_err and not n_ok:
        return "error"
    return "ok"


# ---------------------------------------------------------------- qc


def _qc(ctx):
    d = _dirs(ctx)
    layer = d["layer"]
    plan = cc.load_plan(d["plan"])
    if plan is None and PROFILES.get(layer) is not None:
        ctx.emit_note(f"{d['plan'].name} 缺 — qc 无配额分母", level="warn")
        return "error"
    d["lwd"].mkdir(parents=True, exist_ok=True)
    rows = cc.read_jsonl(d["manifest"])
    ids = [r["id"] for r in rows]
    own = {cc.canon_id(str(i)) for i in ids}
    dup = [i for i, c in Counter(ids).items() if c > 1]
    by_cell = Counter(r.get("stratum_cell") for r in rows)
    incomplete = [
        r["id"]
        for r in rows
        if not lake.is_complete(r["id"], source=r.get("channel") or "arxiv")
    ]
    # 跨层撞 id：本层在册 id 出现在他层 manifest（分母污染）
    overlap = sorted(own & (cc.existing_ids(d["corpus"]) - own))
    stats = (
        json.loads(d["select_stats"].read_text()) if d["select_stats"].exists() else {}
    )
    quotas = (plan or {}).get("quotas") or {}
    # 分母：select_stats 两段式账目（flag:X+failmine_fill 也在内）优先，
    # 未跑 extract 时退回 plan 配额
    denom = {c: s.get("quota", 0) for c, s in stats.items()} if stats else quotas
    lines = [
        f"# {layer} 层自检",
        "",
        f"- manifest_{layer} 入库 **{len(rows)}**",
        f"- id 重复: {sorted(dup) or '无'}",
        f"- 跨层撞 id: {overlap[:10] or '无'} (n={len(overlap)})",
        f"- lake cell 不完整: {incomplete[:10] or '无'} (n={len(incomplete)})",
        "",
        "| cell | 实收 | quota | avail | deficit |",
        "| --- | --- | --- | --- | --- |",
    ]
    if stats:
        for cell, s in sorted(stats.items()):
            lines.append(
                f"| {cell} | {by_cell.get(cell, 0)} | {s.get('quota', '-')} "
                f"| {s.get('avail', '-')} | {s.get('deficit', '-')} |"
            )
    else:
        for cell, q in sorted(quotas.items()):
            lines.append(f"| {cell} | {by_cell.get(cell, 0)} | {q} | - | - |")
    d["qc_md"].write_text("\n".join(lines) + "\n")
    attained = sum(1 for c, q in denom.items() if by_cell.get(c, 0) >= q)
    ctx.emit(
        {
            "metric": "layers_qc",
            "layer": layer,
            "manifest_rows": len(rows),
            "cells_attained": attained,
            "cells_total": len(denom),
            "dup_ids": len(dup),
            "incomplete_cells": len(incomplete),
            "overlap_ids": len(overlap),
            "qc_md": str(d["qc_md"]),
        }
    )
    if dup or incomplete or overlap:
        return "fail"
    return "ok" if attained == len(denom) else "fail"


# ---------------------------------------------------------------- items/select


def _select(item: dict, rp: dict) -> bool:
    """``layers`` run 参数（逗号分隔层名）——缺省全层。"""
    wanted = {s.strip() for s in str(rp.get("layers") or "").split(",") if s.strip()}
    return not wanted or str(item.get("id")) in wanted


spec = Spec(
    kind="corpus_layers",
    items=[{"id": n, "params": {"layer": n}} for n in LAYER_NAMES],
    params={
        "workdir": Param(type=str, default=str(cc.BUILD_ROOT / "layers"), fp=False),
        "build_root": Param(type=str, default=str(cc.BUILD_ROOT), fp=False),
        "corpus_dir": Param(type=str, default=str(cc.CORPUS), fp=False),
        "frame_dir": Param(type=str, default=str(cc.FRAME), fp=False),
        "v3_workdir": Param(type=str, default=str(cc.BUILD_ROOT / "v3"), fp=False),
        "layers": Param(type=str, default=",".join(LAYER_NAMES), fp=False),
        "layer": Param(type=str, default="", fp=False),
        "rates_source": Param(type=str, default="", fp=False),
        "bias": Param(type=float, default=1.0),
        "target": Param(type=int, default=0),
        "ids_file": Param(type=str, default="", fp=False),
        "limit": Param(type=int, default=0, fp=False),
        "recent_limit": Param(type=int, default=85, fp=False),
        "day_budget": Param(type=int, default=180, fp=False),
        "jobs": Param(type=int, default=4, fp=False),
        "topup": Param(type=bool, default=False, fp=False),
    },
    stages=[
        Stage(
            "plan",
            _plan,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
        Stage(
            "scan",
            _scan,
            needs=[("plan", {"ok"})],
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "error": "retriable",
            },
        ),
        Stage(
            "extract",
            _extract,
            needs=[("scan", {"ok", "partial"})],
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
        Stage(
            "recent",
            _recent,
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
        Stage(
            "qc",
            _qc,
            needs=[("extract", {"ok", "partial"})],
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
    ],
    select=_select,
    code_deps=[
        "bench/py/specs/_corpus_common.py",
        "bench/py/specs/_corpus_common_features.py",
        "bench/py/specs/_corpus_common_frame.py",
        "bench/py/specs/_corpus_common_io.py",
        "bench/py/specs/_corpus_common_materialize.py",
        "bench/py/specs/_corpus_common_net.py",
        "bench/py/specs/_corpus_common_scan.py",
        "bench/py/specs/_corpus_common_select.py",
        "src/texlate/arxiv",
    ],
)
