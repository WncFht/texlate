"""corpus_expand — 扩库管线 spec（+~3740 篇增量 → 总 ~5000）。

build_corpus_expand.py 的 spec 重写（trizone-ledger v2，无旧兼容）：
core manifest 的 stratum_cell 分布 × 故障率偏置 → largest_remainder 配额 →
新 item 扫描（成员级断点）→ 全局选样 → lake.hydrate 物化 →
bench/corpus/manifest_expand.jsonl（tracked append）。

    bench run bench/py/specs/corpus_expand.py
    bench run corpus_expand --param rates_source=e2e_real/2026-09-22/<slug>
    bench run corpus_expand --param ids_file=tmp/orphans.jsonl

stage 链（单件串行 + 一条正交定点臂）：

- ``plan``      — manifest stratum × rates_source → 配额 → 候选 item 排序
                  → {workdir}/expand_plan.json。
- ``scan``      — 选中 item .part+Range 下载 → 流扫成员特征（成员级断点）
                  → features/members/{item}.jsonl + .done 后删 tar。
- ``extract``   — 配额选样（旧池 v3-workdir 本地 tar / 新池 Range-GET）
                  → lake.hydrate(idc, fetch_fn, source=channel) 物化 →
                  manifest_expand.jsonl 幂等 append。
- ``fetch_ids`` — 正交臂（needs=[]）：ids_file 清单 → 产品 acquire_source
                  /src 钉版 → hydrate(source='arxiv_eprint')。日预算
                  day_budget（默认 85 篇 ≈180 请求）闸；无 ids_file → skip。
- ``qc``        — manifest 实收 vs 配额 → {workdir}/qc.md + metrics；
                  差异非零即 fail。

口径变化（旧世界不可恢复资产，已文档化）：

- n100 故障率文件已灭 → ``rates_source`` Param 三路解析：run ref
  ``kind/date/slug``（index cells 末 stage per-id status）| rates json |
  缺省/``flat`` → flat_fallback（λ 失效纯比例），emit metric
  ``rates_mode`` 显式标注，绝不静默零偏置。显式给源但解析失败 → fail。
- 旧池复用 REUSE_FRAC=0.3 名义保留：work_v3 已灭，旧池=v3_workdir
  features/tars/chunks（新 v3 spec 跑过才有）；缺席 → 实效 0。
- 工作区新家：``~/.local/state/texlate/corpus-build/expand/``（work_v3
  已灭；TarDirs 同构布局，frame_lookup 共享件在 corpus-build 根）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# src/ 不在 `bench` 入口的 sys.path 上（kernel 惰性 import texlate.*）——
# soak/_corpus_common 同款自举；TEXLATE_SRC 冻结快照语义一致。
sys.path.insert(
    0,
    os.environ.get(
        "TEXLATE_SRC", str(Path(__file__).resolve().parents[3] / "src")
    ),
)

from kernel import index as indexmod
from kernel import lake, paths
from kernel.spec import Param, Spec, Stage

from specs import _corpus_common as cc

REPO = Path(__file__).resolve().parents[3]
SEED = 42
_RUN_REF = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*/[0-9]{4}-[0-9]{2}-[0-9]{2}/[A-Za-z0-9][A-Za-z0-9._-]*"
)
#: plan 依赖的 frame 资产清单——frame_build ord-0 前置；缺一件即 fail-closed。
_FRAME_NEEDS = (
    "item-index.csv",
    "tiger-files.csv",
    "allocation-core.csv",
    "cluster-cat-mix.csv",
)


def _dirs(ctx) -> dict:
    p = ctx.params
    wd = Path(str(p.get("workdir") or "")).expanduser()
    corpus = Path(str(p.get("corpus_dir") or "")).expanduser()
    return {
        "workdir": wd,
        "dirs": cc.TarDirs.from_workdir(wd),
        "plan": wd / "expand_plan.json",
        "records": wd / "extract_records.jsonl",
        "select_stats": wd / "select_stats.json",
        "qc_md": wd / "qc.md",
        "fails": wd / "fetch_ids_fail.jsonl",
        "corpus": corpus,
        "manifest": corpus / "manifest_expand.jsonl",
        "frame": Path(str(p.get("frame_dir") or "")).expanduser(),
        "v3": Path(str(p.get("v3_workdir") or "")).expanduser(),
        "build_root": Path(str(p.get("build_root") or cc.BUILD_ROOT)).expanduser(),
    }


def _load_plan(d: dict) -> dict | None:
    try:
        return json.loads(d["plan"].read_text())
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------- rates_source 三路解析


def _rate(stat: dict[str, Counter]) -> dict[str, float]:
    return {
        k: c["bad"] / (c["bad"] + c["ok"])
        for k, c in stat.items()
        if c["bad"] + c["ok"]
    }


def _rates_from_idstatus(
    id_status: dict[str, str], manifest_rows: list[dict], frame_dir: Path
) -> tuple[dict, dict, float]:
    """{id: status} × manifest×frame join → (band_bad_rate, cat_bad_rate, global).

    bad=status∈{fail,reject,partial}（n100_rates 同口径）；id 双侧 canon 归一。"""
    by_id = {cc.canon_id(r["id"]): r for r in manifest_rows if r.get("id")}
    c2b = cc.cluster2band(frame_dir)
    band_stat: dict[str, Counter] = defaultdict(Counter)
    cat_stat: dict[str, Counter] = defaultdict(Counter)
    n_bad = 0
    for pid, st in id_status.items():
        bad = st in ("fail", "reject", "partial")
        n_bad += bad
        m = by_id.get(cc.canon_id(pid), {})
        band = c2b.get(m.get("cluster_id"), "?")
        cat = m.get("cat_group") or "?"
        band_stat[band]["bad" if bad else "ok"] += 1
        cat_stat[cat]["bad" if bad else "ok"] += 1
    if not id_status:
        return {}, {}, 0.0
    return _rate(band_stat), _rate(cat_stat), n_bad / len(id_status)


def _run_id_statuses(run_id: str) -> dict[str, str] | None:
    """run ref → index cells 末 stage per-id status（canon id → status）。"""
    rdir = paths.runs_dir() / run_id
    spec_fp = rdir / "spec.json"
    if not spec_fp.is_file():
        return None
    try:
        stages = [s["name"] for s in json.loads(spec_fp.read_text()).get("stages", [])]
    except (OSError, json.JSONDecodeError):
        return None
    if not stages:
        return None
    idx = indexmod.Index()
    rows = idx.conn.execute(
        "SELECT idc,status FROM cells WHERE last_run=? AND stage=?",
        (run_id, stages[-1]),
    )
    return {cc.canon_id(r["idc"]): r["status"] for r in rows}


def _resolve_rates(
    ctx, d: dict, manifest_rows: list[dict]
) -> tuple[dict, dict, float, str, str]:
    """rates_source → (fr_band, fr_cat, fr_all, mode, detail)。

    三路：run ref | rates json | flat_fallback。显式源解析失败 → RuntimeError
    （fail-closed：口径错配绝不能静默退化成 flat）。"""
    src = str(ctx.params.get("rates_source") or "").strip()
    if not src or src.lower() in {"flat", "none", "flat_fallback"}:
        return {}, {}, 0.0, "flat_fallback", "no rates_source"
    p = Path(src).expanduser()
    if p.is_file():
        data = json.loads(p.read_text())
        if isinstance(data, dict) and ("band" in data or "cat" in data):
            return (
                dict(data.get("band") or {}),
                dict(data.get("cat") or {}),
                float(data.get("global") or 0.0),
                "rates_file",
                str(p),
            )
        # 旧 results.json 形 {id: {status:…}}（或 {id: status}）
        idst = {
            str(k): (v.get("status") if isinstance(v, dict) else str(v))
            for k, v in data.items()
        }
        fr_b, fr_c, fr_a = _rates_from_idstatus(idst, manifest_rows, d["frame"])
        return fr_b, fr_c, fr_a, "idstatus_file", str(p)
    if _RUN_REF.fullmatch(src):
        idst = _run_id_statuses(src)
        if idst is None:
            msg = f"rates_source run 不可解析（spec.json/stages 缺）: {src}"
            raise RuntimeError(msg)
        fr_b, fr_c, fr_a = _rates_from_idstatus(idst, manifest_rows, d["frame"])
        return fr_b, fr_c, fr_a, "run", src
    msg = f"rates_source 既不是文件也不是 run ref: {src!r}"
    raise RuntimeError(msg)


# ---------------------------------------------------------------- plan


def _scanned_items(d: dict) -> set[str]:
    """已扫 item: v3 chunks done ∪ v3/expand features/*.done。"""
    items = {c["item"] for c in cc.load_chunks(d["v3"]) if c.get("state") == "done"}
    for base in (d["v3"] / "features", d["dirs"].features):
        for p in base.glob("*.done"):
            items.add(p.stem)
    return items


def _candidate_items(d: dict) -> dict[str, list[dict]]:
    """{band: [item…]} 全量未扫候选（ia item-index ∪ tiger-files）。"""
    done = _scanned_items(d)
    out: dict[str, list[dict]] = defaultdict(list)
    with (d["frame"] / "item-index.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            item = r["identifier"]
            if item in done:
                continue
            yymm = r["yymm"]
            out[cc.band_of_yymm(yymm)].append(
                {
                    "item": item,
                    "yymm": yymm,
                    "chunk_no": int(r["chunk"]),
                    "channel": "ia",
                    "size": int(r["size"]),
                    "url": cc.item_url("ia", item),
                }
            )
    with (d["frame"] / "tiger-files.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            m = re.match(r"(arXiv_src_(\d{4})_(\d{3}))\.tar$", r["path"])
            if not m or m.group(1) in done:
                continue
            yymm = m.group(2)
            out[cc.band_of_yymm(yymm)].append(
                {
                    "item": m.group(1),
                    "yymm": yymm,
                    "chunk_no": int(m.group(3)),
                    "channel": "tiger",
                    "size": int(r["size_bytes"]),
                    "oid16": r["lfs_oid16"],
                    "url": cc.item_url("tiger", m.group(1)),
                }
            )
    for v in out.values():
        v.sort(key=lambda it: (it["yymm"], it["chunk_no"]))
    return out


def _order_items(cands: list[dict], cluster_months: set[str]) -> list[dict]:
    """候选项排序: 跨月 round-robin——每轮每月取 1 块, 先把月份摊满再回到
    同月下一块; 簇月在前, 非簇月种子 shuffle 避免挤在年带一端."""
    by_month: dict[str, list[dict]] = defaultdict(list)
    for it in cands:
        by_month[it["yymm"]].append(it)
    cl = sorted(m for m in by_month if m in cluster_months)
    nc = sorted(m for m in by_month if m not in cluster_months)
    random.Random(SEED).shuffle(nc)
    months = cl + nc
    ordered = []
    depth = 0
    while True:
        progressed = False
        for m in months:
            lst = by_month[m]
            if depth < len(lst):
                ordered.append(lst[depth])
                progressed = True
        if not progressed:
            return ordered
        depth += 1


def _chunk_yield_by_band(d: dict) -> dict[str, float]:
    """已扫 features → {band: 平均合格成员/item}（eligible 同口径）。

    v3+expand 两 features 目录全算——plan 首次跑时 expand 侧为空不污染。"""
    by_band: dict[str, list[int]] = defaultdict(list)
    fps = sorted((d["v3"] / "features").glob("*.jsonl")) + sorted(
        d["dirs"].features.glob("*.jsonl")
    )
    for fp in fps:
        n = 0
        band = None
        for r in cc.iter_jsonl(fp):
            if band is None:
                band = r.get("band") or cc.band_of_yymm(
                    cc.member_yymm(r.get("member") or "0000/x")
                )
            n += cc.eligible(r)
        if band:
            by_band[band].append(n)
    return {b: sum(v) / len(v) for b, v in by_band.items()}


def _plan(ctx):
    d = _dirs(ctx)
    d["workdir"].mkdir(parents=True, exist_ok=True)
    missing = [f for f in _FRAME_NEEDS if not (d["frame"] / f).is_file()]
    if missing:
        ctx.emit_note(
            f"frame 资产缺 {missing} — frame_build(ord-0) 前置未跑",
            level="warn",
        )
        return "fail"
    rows = cc.load_manifest_rows(d["corpus"], cc.manifest_layers(d["corpus"]))
    core = [r for r in rows if r.get("layer") == "core"]
    if not core:
        ctx.emit_note("无 core manifest — 配额分母不存在", level="warn")
        return "fail"
    cell_n = Counter(r["stratum_cell"] for r in core)
    try:
        fr_band, fr_cat, fr_all, rates_mode, rates_detail = _resolve_rates(
            ctx, d, rows
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
                fr_band.get(band, fr_all) / fr_all + fr_cat.get(cat, fr_all) / fr_all
            )
        else:
            rel = 1.0  # 无 bad 样本 → 无故障信号可加偏, 配额退化纯比例
        weights[cell] = n * (1 + bias * (rel - 1))
    target = int(ctx.params["target"])
    quotas = cc.largest_remainder(weights, target)
    band_q = Counter()
    for cell, q in quotas.items():
        band_q[cell.split("|")[0]] += q

    reuse_frac = float(ctx.params["reuse_frac"])
    pool_margin = float(ctx.params["pool_margin"])
    min_items = int(ctx.params["min_items"])
    mix = cc.band_cat_share(d["frame"])
    yld = _chunk_yield_by_band(d)
    reuse = {c: int(q * reuse_frac) for c, q in quotas.items()}
    need_new = {c: q - reuse[c] for c, q in quotas.items()}
    cands = _candidate_items(d)
    cluster_months = set(cc.yymm2cluster(d["frame"]))
    picked: list[dict] = []
    for band in sorted(band_q):
        cells_in_band = {
            c.split("|")[1]: need_new[c] for c in quotas if c.startswith(band)
        }
        shares = mix.get(band, {})
        members_needed = 0.0
        for cat, need in cells_in_band.items():
            s = shares.get(cat) or 0.005  # 稀 cat 兜底 0.5%
            members_needed = max(members_needed, need / s)
        members_needed = members_needed * pool_margin / 0.91  # 合格率余量
        per_chunk = yld.get(band, 300)
        n_items = max(min_items, math.ceil(members_needed / per_chunk))
        ordered = _order_items(cands.get(band, []), cluster_months)
        take = ordered[:n_items]
        picked.extend(take)
    plan = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "params": {
            "target": target,
            "bias_lambda": bias,
            "reuse_frac": reuse_frac,
            "pool_margin": pool_margin,
            "seed": SEED,
            "rates_source": str(ctx.params.get("rates_source") or ""),
            "rates_mode": rates_mode,
        },
        "fr_band": fr_band,
        "fr_cat": fr_cat,
        "quotas": dict(sorted(quotas.items())),
        "reuse_take": reuse,
        "items": picked,
    }
    cc.atomic_write_text(
        d["plan"], json.dumps(plan, indent=1, ensure_ascii=False) + "\n"
    )
    gb = sum(i["size"] for i in picked) / 1e9
    by_ch = Counter(i["channel"] for i in picked)
    ctx.emit(
        {
            "metric": "expand_plan",
            "rates_mode": rates_mode,
            "rates_detail": rates_detail,
            "fr_all": round(fr_all, 4),
            "cells": len(quotas),
            "items": len(picked),
            "gb": round(gb, 1),
            "channels": dict(by_ch),
            "quota_sum": sum(quotas.values()),
            "target": target,
        }
    )
    return "ok"


# ---------------------------------------------------------------- scan


def _scan(ctx):
    d = _dirs(ctx)
    plan = _load_plan(d)
    if plan is None:
        ctx.emit_note("expand_plan.json 缺/不可解析 — 先跑 plan", level="warn")
        return "error"
    items = plan["items"]
    limit = int(ctx.params.get("limit") or 0)
    if limit:
        items = items[:limit]
    errs = cc.scan_batch(items, d["dirs"], int(ctx.params["jobs"]))
    ctx.emit(
        {
            "metric": "expand_scan",
            "items": len(items),
            "failed": len(errs),
            "failed_items": errs[:20],
        }
    )
    if not errs:
        return "ok"
    return "partial" if len(errs) < len(items) else "error"


# ---------------------------------------------------------------- extract


def _select_members(ctx, d: dict) -> list[dict] | None:
    """全局选样: cell 配额 → old/new 池分摊 → 选单 [{id,member,item,…}]."""
    plan = _load_plan(d)
    if plan is None:
        return None
    quotas = plan["quotas"]
    reuse_frac = float(ctx.params["reuse_frac"])
    rng = random.Random(SEED)
    excl = cc.existing_ids(d["corpus"])
    chunks = cc.load_chunks(d["v3"])
    old_items = {c["item"] for c in chunks}
    old_files = sorted((d["v3"] / "features").glob("*.jsonl"))
    new_files = sorted(d["dirs"].features.glob("*.jsonl"))
    cand: dict[str, dict] = {}
    for fp in old_files + new_files:
        for f in cc.iter_jsonl(fp):
            if cc.eligible(f) and cc.canon_id(f["id"]) not in excl:
                cand[cc.canon_id(f["id"])] = f  # id 去重: 同 id 后记录覆盖
    try:
        lookup = cc.ensure_frame_lookup(d["frame"], d["build_root"])
    except Exception as e:
        ctx.emit_note(f"frame_lookup 不可用: {e}", level="warn")
        return None
    lut = cc.frame_filter(set(cand), lookup)
    c2y = cc.yymm2cluster(d["frame"])
    old_pool: dict[str, list[dict]] = defaultdict(list)
    new_pool: dict[str, list[dict]] = defaultdict(list)
    n_miss = 0
    for pid, f in cand.items():
        fr = cc.frame_get(lut, pid)
        if fr is None:
            n_miss += 1
            continue  # join miss → 不进 cell 池（与原管线同口径）
        band = f.get("band") or cc.band_of_yymm(cc.member_yymm(f["member"]))
        cell = f"{band}|{fr['cat_group']}"
        if cell not in quotas:
            continue
        f["cat_group"] = fr["cat_group"]
        f["license_class"] = fr["license_class"]
        f["_cell"] = cell
        f["cluster_id"] = f.get("cluster_id") or c2y.get(
            cc.member_yymm(f["member"])
        )
        (old_pool if f["item"] in old_items else new_pool)[cell].append(f)
    for v in list(old_pool.values()) + list(new_pool.values()):
        rng.shuffle(v)

    sel: list[dict] = []
    stats = {}
    for cell, q in sorted(quotas.items()):
        o, n = old_pool.get(cell, []), new_pool.get(cell, [])
        take_o = min(int(q * reuse_frac + 0.5), len(o))
        take_n = min(q - take_o, len(n))
        short = q - take_o - take_n
        if short > 0:  # 新池短收 → 旧池余量回补
            more = min(short, len(o) - take_o)
            take_o += more
            short -= more
        for f in o[:take_o]:
            f["_pool"] = "old"
        for f in n[:take_n]:
            f["_pool"] = "new"
        sel.extend(o[:take_o] + n[:take_n])
        stats[cell] = {
            "quota": q,
            "old_take": take_o,
            "new_take": take_n,
            "old_avail": len(o),
            "new_avail": len(n),
            "deficit": short,
        }
    cc.atomic_write_text(d["select_stats"], json.dumps(stats, indent=1))
    ctx.emit(
        {
            "metric": "expand_select",
            "picks": len(sel),
            "deficit": sum(s["deficit"] for s in stats.values()),
            "old_pool": sum(len(v) for v in old_pool.values()),
            "new_pool": sum(len(v) for v in new_pool.values()),
            "cand": len(cand),
            "join_miss": n_miss,
        }
    )
    return sel


def _member_fetch_fn(rec: dict, old_tars: dict, offs: dict):
    """lake.hydrate fetch_fn：blob 回取 → sha 复核 → stage 物化 + meta。"""
    def fn(idc, stage):
        blob = cc.fetch_blob(rec, old_tars, offs)
        sha = hashlib.sha256(blob).hexdigest()
        if sha != rec["blob_sha256"]:
            msg = f"sha256 mismatch {sha[:12]}"
            raise OSError(msg)
        return cc.materialize_into_stage(
            rec, blob, sha, stage,
            layer="expand", cluster_prefix="EXP", reason="expand_quota",
        )
    return fn


def _extract(ctx):
    d = _dirs(ctx)
    sel = _select_members(ctx, d)
    if sel is None:
        return "fail"
    limit = int(ctx.params.get("limit") or 0)
    if limit:
        sel = sel[:limit]
    manifest = d["manifest"]
    done = {
        cc.canon_id(r["id"]) for r in cc.read_jsonl(manifest) if r.get("id")
    }
    # 回补: lake cell 完整而 manifest 缺行（截尾场景）→ 从 cell meta 补行；
    # meta 不可解析则不标 done，走重抓自愈（hydrate 重写 meta+行）
    n_backfill = 0
    for rec in sel:
        pid = cc.canon_id(rec["id"])
        if pid in done:
            continue
        src = rec["channel"]
        cell = lake.cell_dir(rec["id"], source=src)
        if not (cell / "meta.json").exists() or not lake.is_complete(
            rec["id"], source=src
        ):
            continue
        row = cc.manifest_row_from_meta(None, cell)
        if row is None:
            continue
        cc.append_jsonl(manifest, row)
        done.add(pid)
        n_backfill += 1
    todo = [r for r in sel if cc.canon_id(r["id"]) not in done]
    chunks = cc.load_chunks(d["v3"])
    old_items = {c["item"] for c in chunks}
    tag_of_item = {
        c["item"]: f"{c['yymm']}_{c['chunk_no']:03d}" for c in chunks
    }
    need_items = {r["item"] for r in todo}
    old_tars = {
        it: d["v3"] / "tars" / f"{it}.tar"
        for it in need_items & old_items
        if (d["v3"] / "tars" / f"{it}.tar").exists()
    }
    offs = {
        it: cc.offsets_for(
            it, d["dirs"].members, tag_of_item, d["v3"] / "members"
        )
        for it in need_items
    }
    n0 = len(todo)
    todo = [r for r in todo if r["member"] in offs.get(r["item"], {})]
    if n0 - len(todo):
        ctx.emit_note(f"{n0 - len(todo)} members 无 offset 记录，跳过", level="warn")
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    n_ok = n_err = 0
    jobs = max(1, int(ctx.params["jobs"]))
    with manifest.open("a", encoding="utf-8") as mfh, ThreadPoolExecutor(
        max_workers=jobs
    ) as ex:
        futs = {
            ex.submit(
                lake.hydrate,
                rec["id"],
                _member_fetch_fn(rec, old_tars, offs),
                rec["channel"],
                run_seq,
            ): rec
            for rec in todo
        }
        for fut in as_completed(futs):
            rec = futs[fut]
            pid = rec["id"]
            try:
                cell = fut.result()
                if lake.is_complete(pid, source=rec["channel"]):
                    row = cc.manifest_row_from_meta(None, cell)
                    if row is not None:
                        mfh.write(json.dumps(row, ensure_ascii=False) + "\n")
                        mfh.flush()
                    n_ok += 1
                    st = "ok"
                else:
                    n_err += 1
                    st = "error: empty payload"
            except Exception as e:
                n_err += 1
                st = f"error: {type(e).__name__}: {e}"
                ctx.emit_note(f"  ERR {pid}: {st}", level="warn")
            cc.append_jsonl(
                d["records"],
                {
                    "id": pid,
                    "item": rec["item"],
                    "member": rec["member"],
                    "cell": rec["_cell"],
                    "pool": rec.get("_pool"),
                    "state": st,
                    "ts": time.strftime("%FT%T"),
                },
            )
    ctx.emit(
        {
            "metric": "expand_extract",
            "selected": len(sel),
            "todo": len(todo),
            "ok": n_ok,
            "err": n_err,
            "backfilled": n_backfill,
            "manifest": str(manifest),
        }
    )
    if n_err == 0:
        return "ok"
    return "partial" if n_ok else "error"


# ---------------------------------------------------------------- fetch_ids（正交定点臂）


def _eprint_fetch_fn(pid: str, cand: dict, fm: dict, fetcher, cache, holder):
    """fetch-ids 臂 fetch_fn：acquire_source → entry 树搬进 stage + meta。

    永久负态（not_found/pdf_only/unknown_format）→ {} 走 lake 'empty'
    耐久负答；瞬态（error/budget/网络异常）→ raise 不留 cell 可重试。"""
    from texlate.arxiv.fetch import AcquireStatus, acquire_source

    # 钉版负答：同 version 重试结果不变，走 lake 'empty' 耐久态省预算；
    # PARKED/BUDGET/ERROR 瞬态 raise 不留 cell。
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
            return cc.materialize_entry_into_stage(
                res.entry.dir,
                stage,
                pid=pid,
                fm=fm,
                mechs="+".join(cand["mechs"]) or "manual",
                layer="expand",
            )
        if res.status in permanent:
            holder["permanent"] = res.status.value
            return {}
        msg = f"acquire {res.status.value}: {res.detail or ''}"
        raise OSError(msg)

    return fn


def _fetch_ids(ctx):
    d = _dirs(ctx)
    ids_file = str(ctx.params.get("ids_file") or "").strip()
    if not ids_file:
        ctx.emit({"metric": "fetch_ids", "ran": 0, "reason": "no ids_file"})
        return "skip"
    ids_path = Path(ids_file).expanduser()
    if not ids_path.is_file():
        ctx.emit_note(f"ids_file 不存在: {ids_path}", level="warn")
        return "fail"
    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher

    cands = cc.load_ids_file(ids_path)
    limit = int(ctx.params.get("limit") or 0)
    if limit:
        cands = cands[:limit]
    day_budget = int(ctx.params["day_budget"])
    try:
        lookup = cc.ensure_frame_lookup(d["frame"], d["build_root"])
    except Exception as e:
        ctx.emit_note(f"frame_lookup 不可用: {e}", level="warn")
        return "fail"
    fmeta = cc.frame_meta_for([cc.canon_id(c["id"]) for c in cands], lookup)
    done = cc.existing_ids(d["corpus"])
    fetcher = Fetcher()
    cache = SourceCache(Path.home() / ".cache" / "texlate" / "src")
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    n_new = n_ok = n_skip = n_err = 0
    manifest = d["manifest"]
    with manifest.open("a", encoding="utf-8") as mf:
        for cand in cands:
            pid = cand["id"]
            if cc.canon_id(pid) in done:
                n_skip += 1
                continue
            cell = lake.cell_dir(pid, source="arxiv_eprint")
            meta_fp = cell / "meta.json"
            if meta_fp.exists():
                # 截尾回补 / 耐久负答：已落 meta 的不再消耗请求预算
                if lake.is_complete(pid, source="arxiv_eprint"):
                    row = cc.manifest_row_from_meta(None, cell)
                    if row is not None:
                        mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                        mf.flush()
                        done.add(cc.canon_id(pid))
                n_skip += 1
                continue
            if n_new >= day_budget:
                ctx.emit_note(
                    f"fetch-ids: day_budget {day_budget} — 截断续跑明日",
                    level="warn",
                )
                break
            holder: dict = {}
            try:
                lake.hydrate(
                    pid,
                    _eprint_fetch_fn(
                        pid,
                        cand,
                        fmeta.get(cc.canon_id(pid)) or {},
                        fetcher,
                        cache,
                        holder,
                    ),
                    "arxiv_eprint",
                    run_seq,
                )
            except Exception as e:
                if holder.get("fetched"):
                    n_new += 1
                cc.append_jsonl(
                    d["fails"],
                    {"id": pid, "error": f"{type(e).__name__}: {e}"},
                )
                n_err += 1
                continue
            if holder.get("fetched"):
                n_new += 1
            if lake.is_complete(pid, source="arxiv_eprint"):
                row = cc.manifest_row_from_meta(None, cell)
                if row is not None:
                    mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    mf.flush()
                done.add(cc.canon_id(pid))
                n_ok += 1
            else:
                res = holder.get("res")
                cc.append_jsonl(
                    d["fails"],
                    {
                        "id": pid,
                        "status": (
                            res.status.value if res is not None else "empty"
                        ),
                        "detail": getattr(res, "detail", ""),
                        "permanent": holder.get("permanent"),
                    },
                )
                n_skip += 1
    ctx.emit(
        {
            "metric": "fetch_ids",
            "ran": 1,
            "cands": len(cands),
            "fetched": n_new,
            "ok": n_ok,
            "skip": n_skip,
            "err": n_err,
            "day_budget": day_budget,
        }
    )
    if n_err and not n_ok:
        return "error"
    return "ok" if not n_err else "partial"


# ---------------------------------------------------------------- qc


def _qc(ctx):
    d = _dirs(ctx)
    plan = _load_plan(d)
    if plan is None:
        ctx.emit_note("expand_plan.json 缺 — qc 无配额分母", level="warn")
        return "error"
    man = cc.read_jsonl(d["manifest"])
    quotas = plan["quotas"]
    ids = [r["id"] for r in man]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    by_cell = Counter(r["stratum_cell"] for r in man)
    incomplete = [
        r["id"]
        for r in man
        if not lake.is_complete(r["id"], source=r.get("channel") or "arxiv")
    ]
    recs = cc.read_jsonl(d["records"])
    err_recs = [r for r in recs if r["state"] != "ok"]
    stats = (
        json.loads(d["select_stats"].read_text())
        if d["select_stats"].exists()
        else {}
    )
    lines = [
        "# expand 层自检",
        "",
        f"- manifest_expand 入库 **{len(man)}** / 目标 {plan['params']['target']}",
        f"- rates_mode: {plan['params'].get('rates_mode', '?')}",
        f"- id 重复: {sorted(dup) or '无'}",
        f"- lake cell 不完整: {incomplete[:10] or '无'} (n={len(incomplete)})",
        f"- 抓取错误记录: {len(err_recs)}",
        "",
        "| cell | quota | 实收 | old取 | new取 | deficit |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for cell, q in sorted(quotas.items()):
        s = stats.get(cell, {})
        lines.append(
            f"| {cell} | {q} | {by_cell.get(cell, 0)} "
            f"| {s.get('old_take', '-')} | {s.get('new_take', '-')} "
            f"| {s.get('deficit', '-')} |"
        )
    d["qc_md"].write_text("\n".join(lines) + "\n")
    attained = sum(1 for c, q in quotas.items() if by_cell.get(c, 0) >= q)
    ctx.emit(
        {
            "metric": "expand_qc",
            "manifest_rows": len(man),
            "target": plan["params"]["target"],
            "cells_attained": attained,
            "cells_total": len(quotas),
            "dup_ids": len(dup),
            "incomplete_cells": len(incomplete),
            "fetch_errors": len(err_recs),
            "qc_md": str(d["qc_md"]),
        }
    )
    if dup or incomplete:
        return "fail"
    return "ok" if attained == len(quotas) else "fail"


spec = Spec(
    kind="corpus_expand",
    items=[{"id": "corpus-expand"}],
    params={
        "workdir": Param(
            type=str, default=str(cc.BUILD_ROOT / "expand"), fp=False
        ),
        "build_root": Param(type=str, default=str(cc.BUILD_ROOT), fp=False),
        "corpus_dir": Param(type=str, default=str(cc.CORPUS), fp=False),
        "frame_dir": Param(type=str, default=str(cc.FRAME), fp=False),
        "v3_workdir": Param(
            type=str, default=str(cc.BUILD_ROOT / "v3"), fp=False
        ),
        "target": Param(type=int, default=3740),
        "bias": Param(type=float, default=1.0),
        "reuse_frac": Param(type=float, default=0.3),
        "pool_margin": Param(type=float, default=1.5),
        "min_items": Param(type=int, default=3),
        "rates_source": Param(type=str, default=""),
        "ids_file": Param(type=str, default=""),
        "day_budget": Param(type=int, default=85),
        "limit": Param(type=int, default=0),
        "jobs": Param(type=int, default=4),
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
            "fetch_ids",
            _fetch_ids,
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "skip": "retriable",
                "fail": "terminal",
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
    code_deps=[
        "bench/py/specs/_corpus_common.py",
        "src/texlate/arxiv",
    ],
)
