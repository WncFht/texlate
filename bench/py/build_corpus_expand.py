#!/usr/bin/env python3
r"""build_corpus_expand.py — corpus_v3 扩库管线: +~3740 篇 → 总 ~5000.

在 build_corpus_v3.py 建库成果上做增量扩充（不改写既有三个 manifest）:

  plan      读三 manifest 算现有 stratum_cell 分布 → n100 故障率加权
            (w = n_cell × (1 + λ·((rel_band+rel_cat)/2 −1))) → 配额 3740
            → 选未扫 item（簇月优先、月内低 chunk、跨月 round-robin 摊月份）
            → bench/work_v3/expand_plan.json
  scan      逐 item 下载 (.part+Range 续传) → 流式扫成员
            → work_v3/expand/{members,features}/{item}.jsonl（逐成员 append,
            断点续扫）→ .done 后删 tar（成员级 Range-GET 回取，不留整包）
  extract   全局选样：旧池（已扫 56 chunk, 本地 tar 随机读）按 --reuse-frac
            摊 + 新池 Range-GET → corpus_v3/{id}/{raw.*,extracted/,meta.json}
            → manifest_expand.jsonl（逐行 append, id 幂等）
  qc        核对落盘完整性/各 strata 实收 vs 配额 → stdout + expand/qc.md

e-band (2021+) IA 索引无覆盖 → 走 tiger channel（HF LFS, Range GET 同路径）。
旧池复用理由：已扫未选的 ~41.5k 合格成员本地零成本；默认每 cell 三成取自
旧池、七成摊到新月份，兼顾带宽与月份多样性。

用法: python3 bench/py/build_corpus_expand.py <cmd> [--flags]
依赖: 纯 stdlib + 同目录 build_corpus_v3/benchlib（bench 脚本纪律: 系统 python3）；
      extract 例外——materialize 走 b3.unpack_blob → texlate.arxiv（eager httpx），
      用 `uv run python` 跑（与 build_corpus_v3 extract 同例）。
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
import re
import tarfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import benchlib
import build_corpus_v3 as b3

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "bench" / "corpus_v3"
WORK = REPO / "bench" / "work_v3"
EXP = WORK / "expand"  # 扩库工作区（features/members/tars/记录全在这下）
ETARS = EXP / "tars"
EFEATURES = EXP / "features"
EMEMBERS = EXP / "members"
PLAN_JSON = WORK / "expand_plan.json"
RECORDS = EXP / "extract_records.jsonl"
MANIFEST_OUT = CORPUS / "manifest_expand.jsonl"
N100 = (
    REPO / "bench" / "results" / "e2e-real-n100-postcutover-2026-09-16" / "results.json"
)
IA_INDEX = b3.EXP / "ia-pilot" / "item-index.csv"
TIGER_INDEX = b3.EXP / "post2020" / "tiger-files.csv"

SEED = 42
TARGET = 3740
LAMBDA = 1.0  # 故障偏向强度: 0=纯比例, 1=按 rel 故障率线性增减
REUSE_FRAC = 0.3  # 每 cell 配额中优先从旧池（已扫未选）取的比例上限
POOL_MARGIN = 1.5  # 新池规模安全系数（join_miss/dup/cell 短收）
MIN_ITEMS_PER_BAND = 3  # 每带至少扫几个 item 摊月份
RAW_NAME = {
    "tar": "raw.tar.gz",
    "gz": "raw.gz",
    "pdf": "raw.pdf",
    "stub": "raw.stub",
    "error": "raw.bin",
}

log = b3.log


def band_of_yymm(yymm: str) -> str:
    """'9910'→'a_pre2007' … '2105'→'e_2021_25'（成员月即 item 月）."""
    yy = int(yymm[:2])
    year = 1900 + yy if yy >= 91 else 2000 + yy
    ym = year * 100 + int(yymm[2:])
    if ym < 200701:
        return "a_pre2007"
    if ym < 201201:
        return "b_2007_11"
    if ym < 201701:
        return "c_2012_16"
    if ym < 202101:
        return "d_2017_20"
    return "e_2021_25"


def member_yymm(member: str) -> str:
    return member.split("/", 1)[0]


def item_url(channel: str, item: str) -> str:
    if channel == "ia":
        return b3.IA_DL.format(item=item)
    return b3.TIGER_DL.format(name=item)


def load_plan() -> dict:
    return json.loads(PLAN_JSON.read_text())


def save_plan(plan: dict) -> None:
    benchlib.atomic_write_text(
        PLAN_JSON, json.dumps(plan, indent=1, ensure_ascii=False) + "\n"
    )


def existing_ids() -> set[str]:
    rows = benchlib.load_manifest_rows(CORPUS, ["core", "booster", "hot"])
    ids = {r["id"] for r in rows}
    if MANIFEST_OUT.exists():
        ids |= {r["id"] for r in benchlib.iter_jsonl(MANIFEST_OUT)}
    return ids


def scanned_items() -> set[str]:
    """已扫 item: 原始 56 chunk + expand 已 .done 的。"""
    items = {c["item"] for c in b3.load_chunks() if c["state"] == "done"}
    for p in EFEATURES.glob("*.done"):
        items.add(p.stem)
    return items


def frame_filter(pool_ids: set[str]) -> dict[str, dict]:
    """frame_lookup 只留 pool 内 id 的行（全量 3.16M 行驻留太大, 过滤装载）."""
    lut: dict[str, dict] = {}
    with gzip.open(WORK / "frame_lookup.tsv.gz", "rt") as f:
        for line in f:
            pid = line.split("\t", 1)[0]
            if pid in pool_ids:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 6:
                    continue
                i, ty, yb, cg, pc, lc = parts[:6]
                lut[i] = {
                    "tar_yymm": ty,
                    "year_band": yb,
                    "cat_group": cg,
                    "primary_cat": pc,
                    "license_class": lc,
                }
    return lut


def yymm2cluster() -> dict[str, str]:
    with (b3.EXP / "frame" / "allocation-core.csv").open(newline="") as fh:
        return {r["yymm"]: r["cluster_id"] for r in csv.DictReader(fh)}


# ---------------- plan ----------------


def n100_rates(manifest_rows: list[dict]) -> tuple[dict, dict, float]:
    """n100 → (band_bad_rate, cat_bad_rate, global); bad=fail+reject+partial."""
    res = json.loads(N100.read_text())
    if not res:
        log(f"n100 结果为空 ({N100.name}) — band/cat/global 故障率报 0")
        return {}, {}, 0.0
    by_id = {r["id"]: r for r in manifest_rows}
    with (b3.EXP / "frame" / "allocation-core.csv").open(newline="") as fh:
        c2b = {r["cluster_id"]: r["year_band"] for r in csv.DictReader(fh)}
    band_stat: dict[str, Counter] = defaultdict(Counter)
    cat_stat: dict[str, Counter] = defaultdict(Counter)
    n_bad = 0
    for pid, v in res.items():
        bad = v.get("status") in ("fail", "reject", "partial")
        n_bad += bad
        m = by_id.get(pid, {})
        band = c2b.get(m.get("cluster_id"), "?")
        cat = m.get("cat_group") or "?"
        band_stat[band]["bad" if bad else "ok"] += 1
        cat_stat[cat]["bad" if bad else "ok"] += 1

    def rate(stat: dict[str, Counter]) -> dict[str, float]:
        return {
            k: c["bad"] / (c["bad"] + c["ok"])
            for k, c in stat.items()
            if c["bad"] + c["ok"]
        }

    return rate(band_stat), rate(cat_stat), n_bad / len(res)


def largest_remainder(weights: dict[str, float], total: int) -> dict[str, int]:
    neg = {k: w for k, w in weights.items() if w < 0}
    if neg:
        msg = f"negative weights: {neg}"
        raise ValueError(msg)
    s = sum(weights.values())
    raw = {k: total * w / s for k, w in weights.items()}
    q = {k: int(v) for k, v in raw.items()}
    for _, k in sorted(((raw[k] - int(raw[k]), k) for k in raw), reverse=True)[
        : total - sum(q.values())
    ]:
        q[k] += 1
    return q


def band_cat_share() -> dict[str, dict[str, float]]:
    """cluster-cat-mix → {band: {cat: share}}（带内聚合, 估算 item 产出用）."""
    agg: dict[str, Counter] = defaultdict(Counter)
    with (b3.EXP / "frame" / "cluster-cat-mix.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            agg[r["year_band"]][r["cat_group"]] += int(r["n"])
    return {
        b: {c: n / sum(cs.values()) for c, n in cs.items()} for b, cs in agg.items()
    }


def chunk_yield_by_band() -> dict[str, float]:
    """已扫 features → {band: 平均合格成员/chunk}（b3.eligible 同口径）."""
    chunks = {c["item"]: c for c in b3.load_chunks() if c["state"] == "done"}
    tag2chunk = {f"{c['yymm']}_{c['chunk_no']:03d}": c for c in chunks.values()}
    by_band: dict[str, list[int]] = defaultdict(list)
    for fp in sorted((WORK / "features").glob("*.jsonl")):
        c = tag2chunk.get(fp.stem)
        if c is None:
            continue
        n = sum(1 for r in benchlib.iter_jsonl(fp) if b3.eligible(r))
        by_band[band_of_yymm(c["yymm"])].append(n)
    return {b: sum(v) / len(v) for b, v in by_band.items()}


def candidate_items() -> dict[str, list[dict]]:
    """{band: [item…]} 全量未扫候选."""
    done = scanned_items()
    out: dict[str, list[dict]] = defaultdict(list)
    with IA_INDEX.open(newline="") as fh:
        for r in csv.DictReader(fh):
            item = r["identifier"]
            if item in done:
                continue
            yymm = r["yymm"]
            out[band_of_yymm(yymm)].append(
                {
                    "item": item,
                    "yymm": yymm,
                    "chunk_no": int(r["chunk"]),
                    "channel": "ia",
                    "size": int(r["size"]),
                    "url": item_url("ia", item),
                }
            )
    with TIGER_INDEX.open(newline="") as fh:
        for r in csv.DictReader(fh):
            m = re.match(r"(arXiv_src_(\d{4})_(\d{3}))\.tar$", r["path"])
            if not m or m.group(1) in done:
                continue
            yymm = m.group(2)
            out[band_of_yymm(yymm)].append(
                {
                    "item": m.group(1),
                    "yymm": yymm,
                    "chunk_no": int(m.group(3)),
                    "channel": "tiger",
                    "size": int(r["size_bytes"]),
                    "oid16": r["lfs_oid16"],
                    "url": item_url("tiger", m.group(1)),
                }
            )
    for v in out.values():
        v.sort(key=lambda it: (it["yymm"], it["chunk_no"]))
    return out


def order_items(cands: list[dict], cluster_months: set[str]) -> list[dict]:
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


def cmd_plan(args: argparse.Namespace) -> None:
    rows = benchlib.load_manifest_rows(CORPUS, ["core", "booster", "hot"])
    core = [r for r in rows if r["layer"] == "core"]
    cell_n = Counter(r["stratum_cell"] for r in core)
    fr_band, fr_cat, fr_all = n100_rates(rows)
    log(f"n100 bad={fr_all:.2f} bands={ {k: round(v, 2) for k, v in fr_band.items()} }")

    weights = {}
    for cell, n in cell_n.items():
        band, cat = cell.split("|", 1)
        if fr_all:
            rel = 0.5 * (
                fr_band.get(band, fr_all) / fr_all + fr_cat.get(cat, fr_all) / fr_all
            )
        else:
            rel = 1.0  # 无 bad 样本 → 无故障信号可加偏, 配额退化纯比例
        weights[cell] = n * (1 + args.bias * (rel - 1))
    quotas = largest_remainder(weights, args.target)
    band_q = Counter()
    for cell, q in quotas.items():
        band_q[cell.split("|")[0]] += q

    mix = band_cat_share()
    yld = chunk_yield_by_band()
    reuse = {c: int(q * args.reuse_frac) for c, q in quotas.items()}
    need_new = {c: q - reuse[c] for c, q in quotas.items()}
    cands = candidate_items()
    cluster_months = set(yymm2cluster())
    picked: list[dict] = []
    for band, qsum in sorted(band_q.items()):
        cells_in_band = {
            c.split("|")[1]: need_new[c] for c in quotas if c.startswith(band)
        }
        shares = mix.get(band, {})
        members_needed = 0.0
        for cat, need in cells_in_band.items():
            s = shares.get(cat) or 0.005  # 稀 cat 兜底 0.5%
            members_needed = max(members_needed, need / s)
        members_needed = members_needed * args.pool_margin / 0.91  # 合格率余量
        per_chunk = yld.get(band, 300)
        n_items = max(args.min_items, math.ceil(members_needed / per_chunk))
        ordered = order_items(cands.get(band, []), cluster_months)
        take = ordered[:n_items]
        picked.extend(take)
        months = {i["yymm"] for i in take}
        log(
            f"{band}: quota={qsum} need~{members_needed:.0f}mem "
            f"yield/chunk={per_chunk:.0f} -> {len(take)}/{len(ordered)} items "
            f"over {len(months)} months"
        )
    plan = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "params": {
            "target": args.target,
            "bias_lambda": args.bias,
            "reuse_frac": args.reuse_frac,
            "pool_margin": args.pool_margin,
            "seed": SEED,
            "n100": str(N100.relative_to(REPO)),
        },
        "fr_band": fr_band,
        "fr_cat": fr_cat,
        "quotas": dict(sorted(quotas.items())),
        "reuse_take": reuse,
        "items": picked,
    }
    save_plan(plan)
    gb = sum(i["size"] for i in picked) / 1e9
    by_ch = Counter(i["channel"] for i in picked)
    log(f"plan: {len(picked)} items ~{gb:.1f}GB channels={dict(by_ch)}")
    for cell, q in sorted(quotas.items()):
        print(f"  {cell:34s} quota={q:4d} reuse≤{reuse[cell]:3d} new≥{need_new[cell]}")


# ---------------- scan ----------------


def remote_size(it: dict) -> int:
    """权威 size: ia 走 metadata API（item-index 尺寸有过期记录）并缓存;
    tiger 用索引 LFS size."""
    if it["channel"] == "tiger":
        return it["size"]
    mdir = EXP / "meta"
    mdir.mkdir(parents=True, exist_ok=True)
    cache = mdir / f"{it['item']}.json"
    meta = None
    if cache.exists():
        try:
            meta = json.loads(cache.read_text())
        except (OSError, json.JSONDecodeError):
            cache.unlink(missing_ok=True)  # 截尾缓存每次重跑都炸——弃掉重抓
    if meta is None:
        with b3.open_url(b3.IA_META.format(item=it["item"])) as r:
            meta = json.loads(r.read())
        benchlib.atomic_write_text(cache, json.dumps(meta))
    for f in meta.get("files", []):
        if f["name"] == f"{it['item']}.tar":
            it["sha1"] = f.get("sha1")
            return int(f["size"])
    return it["size"]


def _verify_content(path: Path, it: dict) -> None:
    """尺寸之外的内容校验: ia→meta sha1, tiger→lfs oid16(sha256 前缀). 单遍流式."""
    want_sha1 = it.get("sha1")
    want_oid = it.get("oid16")
    if not want_sha1 and not want_oid:
        return
    h256 = hashlib.sha256()
    h1 = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(1 << 22), b""):
            h256.update(buf)
            h1.update(buf)
    if want_sha1 and h1.hexdigest() != want_sha1:
        msg = f"sha1 {h1.hexdigest()[:12]} != meta {want_sha1[:12]}"
        raise OSError(msg)
    if want_oid and not h256.hexdigest().startswith(want_oid):
        msg = f"sha256 {h256.hexdigest()[:16]} != oid16 {want_oid}"
        raise OSError(msg)


def download_item(it: dict, dest_dir: Path) -> Path:
    """item tar → dest_dir/{item}.tar（.part+Range 续传, 尺寸+内容校验）."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = dest_dir / f"{it['item']}.tar.part"
    final = dest_dir / f"{it['item']}.tar"
    want = remote_size(it)
    if final.exists() and final.stat().st_size == want:
        # 尺寸对≠内容对: 腐 final 曾让本函数静默返回坏 tar(探针实证)——
        # 验不过就删掉落回下载循环重抓
        try:
            _verify_content(final, it)
        except OSError as e:
            log(f"  {it['item']} existing tar corrupt: {e} — 重抓")
            final.unlink()
        else:
            return final
    for attempt in range(4):
        have = part.stat().st_size if part.exists() else 0
        if have == want:
            try:
                _verify_content(part, it)
            except OSError as e:
                log(f"  {it['item']} .part 腐坏: {e} — 重抓")
                part.unlink()
                have = 0
            else:
                part.rename(final)
                return final
        if have > want:
            part.unlink()
            have = 0
        try:
            headers = {"Range": f"bytes={have}-"} if have else {}
            r = b3.open_url(it["url"], headers=headers, timeout=180)
            try:
                resumed = bool(have) and r.status == 206
                with open(part, "ab" if resumed else "wb") as f:
                    while True:
                        buf = r.read(1 << 20)
                        if not buf:
                            break
                        f.write(buf)
            finally:
                r.close()
            if part.stat().st_size == want:
                _verify_content(part, it)
                part.rename(final)
                return final
            log(f"  {it['item']} partial {part.stat().st_size}/{want}")
        except Exception as e:
            log(f"  {it['item']} dl#{attempt}: {type(e).__name__}: {e}")
            time.sleep(5 * (attempt + 1))
    msg = f"{it['item']} download failed"
    raise OSError(msg)


def scan_item(it: dict) -> str:
    """单 item: 下载→流扫(成员级断点)→.done→删 tar."""
    item = it["item"]
    done_f = EFEATURES / f"{item}.done"
    if done_f.exists():
        return "done-skip"
    EFEATURES.mkdir(parents=True, exist_ok=True)
    EMEMBERS.mkdir(parents=True, exist_ok=True)
    fjsonl = EFEATURES / f"{item}.jsonl"
    mjsonl = EMEMBERS / f"{item}.jsonl"
    done_members = (
        {r["member"] for r in benchlib.iter_jsonl(fjsonl) if r.get("member")}
        if fjsonl.exists()
        else set()
    )
    tar_path = download_item(it, ETARS)
    n = len(done_members)
    t0 = time.time()
    with (
        tarfile.open(tar_path, "r|") as tar,
        open(fjsonl, "a") as fw,
        open(mjsonl, "a") as mw,
    ):
        for m in tar:
            if not m.isreg():
                continue
            if m.name in done_members:
                continue  # 流式跳过已扫成员（读穿不处理）
            bf = tar.extractfile(m)
            blob = bf.read() if bf else b""
            try:
                rec = b3.blob_features(m.name, blob)
            except Exception as e:  # 成员级异常不阻断
                rec = {
                    "member": m.name,
                    "id": b3.member_id(m.name),
                    "member_bytes": m.size,
                    "format": "error",
                    "error": f"{type(e).__name__}: {e}",
                }
            rec.pop("_texts", None)  # 扩库不留 staging
            rec["item"] = item
            rec["channel"] = it["channel"]
            rec["band"] = band_of_yymm(it["yymm"])
            mw.write(
                json.dumps({"name": m.name, "size": m.size, "offset": m.offset_data})
                + "\n"
            )
            mw.flush()
            fw.write(json.dumps(rec) + "\n")
            fw.flush()
            n += 1
            if n % 1000 == 0:
                log(f"  {item}: {n} members {time.time() - t0:.0f}s")
    done_f.write_text(f"{n} members\n")
    tar_path.unlink(missing_ok=True)
    (ETARS / f"{item}.tar.part").unlink(missing_ok=True)
    return f"scanned {n}"


def cmd_scan(args: argparse.Namespace) -> None:
    plan = load_plan()
    items = plan["items"][: args.limit] if args.limit else plan["items"]
    todo = [it for it in items if not (EFEATURES / f"{it['item']}.done").exists()]
    log(f"scan: {len(todo)}/{len(items)} items pending")
    errs = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(scan_item, it): it for it in todo}
        for fut in as_completed(futs):
            it = futs[fut]
            state = "done"
            try:
                st = fut.result()
                log(f"ok {it['item']} ({it['size'] / 1e6:.0f}MB {it['channel']}): {st}")
            except Exception as e:
                errs.append(it["item"])
                state = "failed"
                log(f"FAIL {it['item']}: {type(e).__name__}: {e}")
            benchlib.append_jsonl(
                EXP / "scan_log.jsonl",
                {"item": it["item"], "state": state, "ts": time.strftime("%FT%T")},
            )
    log(f"scan pass done, {len(errs)} failed: {errs or '-'}")


# ---------------- extract ----------------


def select_members(args: argparse.Namespace) -> list[dict]:
    """全局选样: cell 配额 → old/new 池分摊 → 选单 [{id,member,item,…}]."""
    plan = load_plan()
    quotas = plan["quotas"]
    rng = random.Random(SEED)
    excl = existing_ids()
    old_items = {c["item"] for c in b3.load_chunks()}
    old_files = sorted((WORK / "features").glob("*.jsonl"))
    new_files = sorted(EFEATURES.glob("*.jsonl"))
    cand: dict[str, dict] = {}
    for fp in old_files + new_files:
        for f in benchlib.iter_jsonl(fp):
            if b3.eligible(f) and f["id"] not in excl:
                cand[f["id"]] = f  # id 去重: 同 id 后记录覆盖
    lut = frame_filter(set(cand))
    c2y = yymm2cluster()
    old_pool: dict[str, list[dict]] = defaultdict(list)
    new_pool: dict[str, list[dict]] = defaultdict(list)
    for pid, f in cand.items():
        fr = b3.frame_get(lut, pid)
        if fr is None:
            continue  # join miss → 不进 cell 池（与原管线同口径）
        band = f.get("band") or band_of_yymm(member_yymm(f["member"]))
        cell = f"{band}|{fr['cat_group']}"
        if cell not in quotas:
            continue
        f["cat_group"] = fr["cat_group"]
        f["license_class"] = fr["license_class"]
        f["_cell"] = cell
        f["cluster_id"] = f.get("cluster_id") or c2y.get(member_yymm(f["member"]))
        (old_pool if f["item"] in old_items else new_pool)[cell].append(f)
    for v in list(old_pool.values()) + list(new_pool.values()):
        rng.shuffle(v)

    sel: list[dict] = []
    stats = {}
    for cell, q in sorted(quotas.items()):
        o, n = old_pool.get(cell, []), new_pool.get(cell, [])
        take_o = min(int(q * args.reuse_frac + 0.5), len(o))
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
    benchlib.atomic_write_text(EXP / "select_stats.json", json.dumps(stats, indent=1))
    n_def = sum(s["deficit"] for s in stats.values())
    log(f"select: {len(sel)} picks, deficit {n_def} (明细 select_stats.json)")
    return sel


def offsets_for(item: str, tag_of_item: dict[str, str]) -> dict[str, tuple[int, int]]:
    """item → {member: (offset, size)}; expand item 读 expand/members/{item},
    旧 item 走 tag 映射读 work_v3/members/{tag}."""
    out = {}
    p = EMEMBERS / f"{item}.jsonl"
    if not p.exists() and item in tag_of_item:
        p = WORK / "members" / f"{tag_of_item[item]}.jsonl"
    if p.exists():
        for r in benchlib.iter_jsonl(p):
            off = r.get("offset", r.get("offset_data"))
            if off is None:
                continue  # 缺 offset 记录留给 extract 的「无 offset」过滤统一报
            out[r["name"]] = (off, r["size"])
    return out


def fetch_blob(rec: dict, old_tars: dict[str, Path], offs: dict[str, dict]) -> bytes:
    """成员 blob: 旧池本地 tar 随机读; 新池 tar URL Range GET（重试 3 轮）."""
    item, member = rec["item"], rec["member"]
    off, size = offs[item][member]
    if item in old_tars:
        with open(old_tars[item], "rb") as f:
            f.seek(off)
            data = f.read(size)
        if len(data) != size:
            msg = f"local short read {len(data)}/{size}"
            raise OSError(msg)
        return data
    url = item_url(rec["channel"], item)
    last = ""
    for attempt in range(3):
        try:
            r = b3.open_url(
                url,
                headers={"Range": f"bytes={off}-{off + size - 1}"},
                timeout=120,
            )
            try:
                # size+1 封顶: 服务端不理会 Range 时不至于把整 tar 读进内存
                data = r.read(size + 1)
            finally:
                r.close()
            if len(data) == size:
                return data
            last = f"read {len(data)}/{size}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(3 * (attempt + 1))
    err = f"{item}/{member}: {last}"
    raise OSError(err)


def materialize(rec: dict, blob: bytes, sha: str) -> dict:
    """blob → corpus_v3/{id}/ + manifest 行（shape 同 booster + layer=expand）."""
    pid = rec["id"]
    dest = CORPUS / pid
    dest.mkdir(parents=True, exist_ok=True)
    fmt = rec["format"]
    raw_name = RAW_NAME[fmt]
    (dest / raw_name).write_bytes(blob)
    n_ext, warns = b3.unpack_blob(blob, fmt, dest)
    main_sha = None
    roots = rec.get("tex_roots") or []
    if len(roots) == 1:
        mp = dest / "extracted" / roots[0]
        if mp.exists():
            main_sha = hashlib.sha256(mp.read_bytes()).hexdigest()
    era = "old" if "/" in pid else "new"
    yymm = member_yymm(rec["member"])
    band = rec["_cell"].split("|")[0]
    meta = {
        "arxiv_id": pid,
        "resolved_version": None,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "era": era,
        "archive": pid.split("/")[0] if "/" in pid else None,
        "yymm": yymm,
        "cluster_id": rec.get("cluster_id") or f"EXP-{band}",
        "year_band": band,
        "layer": "expand",
        "stratum_cell": rec["_cell"],
        "cat_group": rec["cat_group"],
        "license_class": rec.get("license_class"),
        "channel": rec["channel"],
        "item": rec["item"],
        "member": rec["member"],
        "raw_sha256": sha,
        "raw_file": raw_name,
        "format": fmt,
        "n_files": n_ext,
        "tex_files": rec.get("n_tex_files"),
        "bytes": len(blob),
        "uncompressed_bytes": rec.get("uncompressed_bytes"),
        "features": {
            k: rec[k]
            for k in (
                "docclasses",
                "docstyle",
                "input_depth",
                "non_utf8",
                "flags",
                "tex_roots",
            )
            if k in rec
        },
        "pick_reason": f"expand_quota:{rec['_cell']}",
        "pool": rec["_pool"],
        "warnings": warns,
        "source": rec["channel"],
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    return {
        "id": pid,
        "era": era,
        "archive": meta["archive"],
        "yymm": yymm,
        "cluster_id": meta["cluster_id"],
        "layer": "expand",
        "channel": rec["channel"],
        "item": rec["item"],
        "member": rec["member"],
        "blob_sha256": sha,
        "main_tex_sha256": main_sha,
        "stratum_cell": rec["_cell"],
        "cat_group": rec["cat_group"],
        "license_class": rec.get("license_class"),
        "format": fmt,
        "n_files": n_ext,
        "n_tex": rec.get("n_tex_files"),
        "bytes": len(blob),
        "pick_reason": meta["pick_reason"],
        "pool": rec["_pool"],
    }


def manifest_row_from_meta(dest: Path) -> dict | None:
    """meta.json → manifest 行（截尾回补：materialize 写盘与 manifest append
    之间崩了会留下 extracted 树但无 manifest 行）。"""
    try:
        meta = json.loads((dest / "meta.json").read_text())
    except Exception:
        return None
    roots = (meta.get("features") or {}).get("tex_roots") or []
    main_sha = None
    if len(roots) == 1:
        mp = dest / "extracted" / roots[0]
        if mp.exists():
            main_sha = hashlib.sha256(mp.read_bytes()).hexdigest()
    return {
        "id": meta.get("arxiv_id") or dest.name,
        "era": meta.get("era"),
        "archive": meta.get("archive"),
        "yymm": meta.get("yymm"),
        "cluster_id": meta.get("cluster_id"),
        "layer": meta.get("layer") or "expand",
        "channel": meta.get("channel"),
        "item": meta.get("item"),
        "member": meta.get("member"),
        "blob_sha256": meta.get("raw_sha256"),
        "main_tex_sha256": main_sha,
        "stratum_cell": meta.get("stratum_cell"),
        "cat_group": meta.get("cat_group"),
        "license_class": meta.get("license_class"),
        "format": meta.get("format"),
        "n_files": meta.get("n_files"),
        "n_tex": meta.get("tex_files"),
        "bytes": meta.get("bytes"),
        "pick_reason": meta.get("pick_reason"),
        "pool": meta.get("pool"),
    }


def cmd_extract(args: argparse.Namespace) -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    sel = select_members(args)
    if args.limit:
        sel = sel[: args.limit]
    done = {r["id"] for r in benchlib.read_jsonl(MANIFEST_OUT)}
    # meta.json 在而 manifest 缺的（截尾场景）→ 从 meta.json 回补 manifest 行；
    # meta 不可解析则不标 done，走重抓自愈（materialize 重写 meta+行）
    for rec in sel:
        if rec["id"] in done or not (CORPUS / rec["id"] / "meta.json").exists():
            continue
        row = manifest_row_from_meta(CORPUS / rec["id"])
        if row is None:
            continue
        benchlib.append_jsonl(MANIFEST_OUT, row)
        done.add(rec["id"])
    todo = [r for r in sel if r["id"] not in done]
    old_items = {c["item"] for c in b3.load_chunks()}
    tag_of_item = {
        c["item"]: f"{c['yymm']}_{c['chunk_no']:03d}" for c in b3.load_chunks()
    }
    need_items = {r["item"] for r in todo}
    old_tars = {
        it: b3.TARS / f"{it}.tar"
        for it in need_items & old_items
        if (b3.TARS / f"{it}.tar").exists()
    }
    offs = {it: offsets_for(it, tag_of_item) for it in need_items}
    n0 = len(todo)
    todo = [r for r in todo if r["member"] in offs.get(r["item"], {})]
    if n0 - len(todo):
        log(f"!! {n0 - len(todo)} members 无 offset 记录，跳过")
    log(
        f"extract: {len(todo)} to fetch "
        f"({sum(r['item'] in old_tars for r in todo)} local / "
        f"{sum(r['item'] not in old_tars for r in todo)} range-get)"
    )
    n_ok = n_err = 0
    with (
        open(MANIFEST_OUT, "a") as mfh,
        ThreadPoolExecutor(max_workers=args.jobs) as ex,
    ):
        futs = {ex.submit(fetch_blob, rec, old_tars, offs): rec for rec in todo}
        for fut in as_completed(futs):
            rec = futs[fut]
            try:
                blob = fut.result()
                sha = hashlib.sha256(blob).hexdigest()
                if sha != rec["blob_sha256"]:
                    msg = f"sha256 mismatch {sha[:12]}"
                    raise OSError(msg)  # noqa: TRY301
                row = materialize(rec, blob, sha)
                mfh.write(json.dumps(row, ensure_ascii=False) + "\n")
                mfh.flush()
                n_ok += 1
                st = "ok"
            except Exception as e:
                n_err += 1
                st = f"error: {type(e).__name__}: {e}"
                log(f"  ERR {rec['id']}: {st}")
            benchlib.append_jsonl(
                RECORDS,
                {
                    "id": rec["id"],
                    "item": rec["item"],
                    "member": rec["member"],
                    "cell": rec["_cell"],
                    "pool": rec["_pool"],
                    "state": st,
                    "ts": time.strftime("%FT%T"),
                },
            )
            if (n_ok + n_err) % 200 == 0:
                log(f"  extract {n_ok + n_err}/{len(todo)} ok={n_ok} err={n_err}")
    log(f"extract done: ok={n_ok} err={n_err} -> {MANIFEST_OUT}")


# ---------------- qc ----------------


def cmd_qc() -> None:
    man = benchlib.read_jsonl(MANIFEST_OUT)
    plan = load_plan()
    quotas = plan["quotas"]
    ids = [r["id"] for r in man]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    by_cell = Counter(r["stratum_cell"] for r in man)
    missing_meta = [
        r["id"] for r in man if not (CORPUS / r["id"] / "meta.json").exists()
    ]
    empty_ext = [
        r["id"]
        for r in man
        if r["format"] in ("tar", "gz")
        and not any((CORPUS / r["id"] / "extracted").glob("*"))
    ]
    recs = benchlib.read_jsonl(RECORDS)
    err_recs = [r for r in recs if r["state"] != "ok"]
    stats = (
        json.loads((EXP / "select_stats.json").read_text())
        if (EXP / "select_stats.json").exists()
        else {}
    )
    lines = [
        "# expand 层自检",
        "",
        f"- manifest_expand 入库 **{len(man)}** / 目标 {plan['params']['target']}",
        f"- id 重复: {sorted(dup) or '无'}",
        f"- 缺 meta.json: {missing_meta[:10] or '无'} (n={len(missing_meta)})",
        f"- extracted 空: {empty_ext[:10] or '无'} (n={len(empty_ext)})",
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
    (EXP / "qc.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:10]))
    attained = sum(1 for c, q in quotas.items() if by_cell.get(c, 0) >= q)
    log(f"qc: {len(man)} rows, cells 达成 {attained}/{len(quotas)}")


# ---------------- main ----------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["plan", "scan", "extract", "qc"])
    ap.add_argument("--target", type=int, default=TARGET)
    ap.add_argument("--bias", type=float, default=LAMBDA)
    ap.add_argument("--reuse-frac", type=float, default=REUSE_FRAC)
    ap.add_argument("--pool-margin", type=float, default=POOL_MARGIN)
    ap.add_argument("--min-items", type=int, default=MIN_ITEMS_PER_BAND)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="冒烟: 只处理前 N 个")
    a = ap.parse_args()
    EXP.mkdir(parents=True, exist_ok=True)
    if a.cmd == "qc":
        cmd_qc()
    else:
        {"plan": cmd_plan, "scan": cmd_scan, "extract": cmd_extract}[a.cmd](a)


if __name__ == "__main__":
    main()
