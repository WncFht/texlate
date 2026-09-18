#!/usr/bin/env python3
r"""build_corpus_layers.py — 2026-09 扩库层构建器（holdout / dev_vol / dev_failmine / eprint recent 臂）。

背景：dev==eval 污染——全部 bench 都采 corpus_v3，fixloop 规则对着同一批论文调。
本构建器落三层新料（均在 corpus_v3，加层不删层）：

  holdout       仅评测层（benchlib.EVAL_ONLY_LAYERS 闸住 dev 枚举）：
                2700 bulk 分层（cell 配额 = core 配比 ×2.7，月份与 30 个 core
                簇月不相交→时间外推性质）+ ~300 eprint 近期（sw 池随机 id，
                arxiv.org/src 钉版全量 blob——holdout 必须带图，不走 sw 脱水）。
  dev_vol       修复训练集·纯量层：2000，沿用 expand 配方（core 配比 ×
                n100 失败率偏置 λ=1.0）。
  dev_failmine  修复训练集·矿层：1500，按残差签名族定向采旗标论文——
                deadpkg/pdftex_prim/babel_german/docstyle(2.09)/minted/pstricks/
                epsfig；旗标短收部分用 old-era 随机合格成员回填。

eprint recent 臂（``recent`` 子命令）同时服务 holdout 与 dev_recent 两层：
id 由 build_sw_layer.py 的 assign 阶段从 scholarweave 2501+ 池随机切出，
取源走产品 ``acquire_source``（arxiv.org/src 钉版），与 hot 层同路径。

管线（bulk 臂，同 expand 三段式）：plan → scan → extract → qc。
  plan    层剖面 → {cell 配额, 待扫 item 清单}（item 月份过滤在 plan 收口）
  scan    item tar 下载→流扫成员→features/members 记录→删 tar（成员级断点）
  extract 选样（配额/旗标）→成员 blob Range-GET→物化→manifest_{layer}.jsonl
  qc      分层自检 → work_v3/{layer}/qc.md

用法:
  python3 bench/py/build_corpus_layers.py plan --layer holdout
  python3 bench/py/build_corpus_layers.py scan --layer holdout [--jobs 4]
  python3 bench/py/build_corpus_layers.py extract --layer holdout [--jobs 8]
  python3 bench/py/build_corpus_layers.py qc --layer holdout
  uv run python bench/py/build_corpus_layers.py recent --layer holdout \
      --ids-file bench/work_v3/sw/assign_holdout.jsonl [--limit 85]
Deps: 标准库 + benchlib + build_corpus_v3/expand 件；recent 臂需 uv venv。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import shutil
import tarfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import benchlib
import build_corpus_expand as bx
import build_corpus_v3 as b3

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "bench" / "corpus_v3"
WORK = REPO / "bench" / "work_v3"
IA_INDEX = b3.FRAME / "item-index.csv"
TIGER_INDEX = b3.FRAME / "tiger-files.csv"
SEED = 42

log = b3.log

# 层剖面：quota=flat（core 配比直扩）/ fbias（失败率偏置，expand 配方）/ flags（矿层）
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
RAW_NAME = {
    "tar": "raw.tar.gz",
    "gz": "raw.gz",
    "pdf": "raw.pdf",
    "stub": "raw.stub",
    "error": "raw.bin",
}


def layer_dir(layer: str) -> Path:
    return WORK / layer


def manifest_path(layer: str) -> Path:
    return CORPUS / f"manifest_{layer}.jsonl"


def plan_path(layer: str) -> Path:
    return WORK / f"{layer}_plan.json"


def load_plan(layer: str) -> dict:
    return json.loads(plan_path(layer).read_text())


def save_plan(layer: str, plan: dict) -> None:
    benchlib.atomic_write_text(
        plan_path(layer), json.dumps(plan, indent=1, ensure_ascii=False) + "\n"
    )


def existing_ids() -> set[str]:
    return benchlib.corpus_ids(CORPUS)


def cluster_months() -> set[str]:
    return set(bx.yymm2cluster())


def scanned_items(layer: str) -> set[str]:
    """本层已 .done 的 item（跨层不共享——各层工作区自治）。"""
    return {p.stem for p in (layer_dir(layer) / "features").glob("*.done")}


def band_ok(band: str, profile: dict) -> bool:
    return band[0] in profile["bands"]


def candidate_items(profile: dict, layer: str) -> dict[str, list[dict]]:
    """{band: [item…]} 未扫候选；holdout 剖面额外剔除 core 簇月。"""
    done = scanned_items(layer)
    excl_months = cluster_months() if profile["exclude_cluster_months"] else set()
    out: dict[str, list[dict]] = defaultdict(list)
    with IA_INDEX.open(newline="") as fh:
        for r in csv.DictReader(fh):
            item, yymm = r["identifier"], r["yymm"]
            if item in done or yymm in excl_months:
                continue
            band = bx.band_of_yymm(yymm)
            if not band_ok(band, profile):
                continue
            out[band].append(
                {
                    "item": item,
                    "yymm": yymm,
                    "chunk_no": int(r["chunk"]),
                    "channel": "ia",
                    "size": int(r["size"]),
                    "url": bx.item_url("ia", item),
                }
            )
    with TIGER_INDEX.open(newline="") as fh:
        for r in csv.DictReader(fh):
            m = re.match(r"(arXiv_src_(\d{4})_(\d{3}))\.tar$", r["path"])
            if not m or m.group(1) in done or m.group(2) in excl_months:
                continue
            band = bx.band_of_yymm(m.group(2))
            if not band_ok(band, profile):
                continue
            out[band].append(
                {
                    "item": m.group(1),
                    "yymm": m.group(2),
                    "chunk_no": int(m.group(3)),
                    "channel": "tiger",
                    "size": int(r["size_bytes"]),
                    "oid16": r["lfs_oid16"],
                    "url": bx.item_url("tiger", m.group(1)),
                }
            )
    for v in out.values():
        v.sort(key=lambda it: (it["yymm"], it["chunk_no"]))
    return out


# ---------------- plan ----------------


def cell_quotas(profile: dict) -> dict[str, int]:
    """flat: core cell 配比 × scale；fbias: ×(1+λ(rel-1))，expand 同配方。"""
    rows = benchlib.load_manifest_rows(CORPUS, ["core"])
    cell_n = Counter(r["stratum_cell"] for r in rows)
    if profile["quota"] == "fbias":
        fr_band, fr_cat, fr_all = bx.n100_rates(rows)
        log(
            f"n100 bad={fr_all:.2f} "
            f"bands={ {k: round(v, 2) for k, v in fr_band.items()} }"
        )
        weights = {}
        for cell, n in cell_n.items():
            band, cat = cell.split("|", 1)
            if fr_all:
                rel = 0.5 * (
                    fr_band.get(band, fr_all) / fr_all
                    + fr_cat.get(cat, fr_all) / fr_all
                )
            else:
                rel = 1.0
            weights[cell] = n * (1 + profile["bias"] * (rel - 1))
    else:
        weights = {c: float(n) for c, n in cell_n.items()}
    return bx.largest_remainder(weights, profile["target"])


def cmd_plan(args: argparse.Namespace) -> None:
    profile = PROFILES[args.layer]
    plan: dict = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "layer": args.layer,
        "profile": {k: v for k, v in profile.items() if k != "bands"},
        "params": {"seed": SEED, "pool_margin": POOL_MARGIN},
    }
    cands = candidate_items(profile, args.layer)
    picked: list[dict] = []
    if profile["quota"] == "flags":
        quotas = dict(FLAG_QUOTAS)
        # 矿层 item 量按旗标密度估算：deadpkg/2.09 在旧档占比高，按总目标放大
        members_needed = profile["target"] * POOL_MARGIN
        n_items = max(4, math.ceil(members_needed / YIELD_PER_CHUNK))
        for band in sorted(cands):
            per_band = math.ceil(
                n_items * {"a": 0.45, "b": 0.35, "c": 0.2}.get(band[0], 0.0)
            )
            ordered = bx.order_items(cands[band], set())
            take = ordered[:per_band]
            picked.extend(take)
            log(f"{band}: failmine 取 {len(take)}/{len(ordered)} items")
        plan["flag_quotas"] = quotas
    else:
        quotas = cell_quotas(profile)
        band_q = Counter()
        for cell, q in quotas.items():
            band_q[cell.split("|")[0]] += q
        for band, qsum in sorted(band_q.items()):
            members_needed = qsum / 0.91 * POOL_MARGIN
            n_items = max(2, math.ceil(members_needed / YIELD_PER_CHUNK))
            ordered = bx.order_items(cands.get(band, []), set())
            take = ordered[:n_items]
            picked.extend(take)
            months = {i["yymm"] for i in take}
            log(
                f"{band}: quota={qsum} need~{members_needed:.0f}mem "
                f"-> {len(take)}/{len(ordered)} items over {len(months)} months"
            )
        plan["quotas"] = dict(sorted(quotas.items()))
    plan["items"] = picked
    save_plan(args.layer, plan)
    gb = sum(i["size"] for i in picked) / 1e9
    log(f"plan[{args.layer}]: {len(picked)} items ~{gb:.1f}GB")


# ---------------- scan ----------------


def remote_size(it: dict, meta_dir: Path) -> int:
    """权威 size: ia 走 metadata API（缓存于本层 meta/）；tiger 用索引 LFS size。"""
    if it["channel"] == "tiger":
        return it["size"]
    meta_dir.mkdir(parents=True, exist_ok=True)
    cache = meta_dir / f"{it['item']}.json"
    meta = None
    if cache.exists():
        try:
            meta = json.loads(cache.read_text())
        except (OSError, json.JSONDecodeError):
            cache.unlink(missing_ok=True)
    if meta is None:
        with b3.open_url(b3.IA_META.format(item=it["item"])) as r:
            meta = json.loads(r.read())
        benchlib.atomic_write_text(cache, json.dumps(meta))
    for f in meta.get("files", []):
        if f["name"] == f"{it['item']}.tar":
            it["sha1"] = f.get("sha1")
            return int(f["size"])
    return it["size"]


def download_item(it: dict, dest_dir: Path, meta_dir: Path) -> Path:
    """item tar → dest_dir/{item}.tar（.part+Range 续传, 尺寸+内容校验）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = dest_dir / f"{it['item']}.tar.part"
    final = dest_dir / f"{it['item']}.tar"
    want = remote_size(it, meta_dir)
    if final.exists() and final.stat().st_size == want:
        try:
            bx._verify_content(final, it)
        except OSError as e:
            log(f"  {it['item']} existing tar corrupt: {e} — 重抓")
            final.unlink()
        else:
            return final
    for attempt in range(4):
        have = part.stat().st_size if part.exists() else 0
        if have == want:
            try:
                bx._verify_content(part, it)
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
                bx._verify_content(part, it)
                part.rename(final)
                return final
            log(f"  {it['item']} partial {part.stat().st_size}/{want}")
        except Exception as e:
            log(f"  {it['item']} dl#{attempt}: {type(e).__name__}: {e}")
            time.sleep(5 * (attempt + 1))
    msg = f"{it['item']} download failed"
    raise OSError(msg)


def scan_item(it: dict, layer: str) -> str:
    """单 item: 下载→流扫(成员级断点)→.done→删 tar。"""
    wdir = layer_dir(layer)
    feat_dir, mem_dir, tar_dir = (
        wdir / "features",
        wdir / "members",
        wdir / "tars",
    )
    done_f = feat_dir / f"{it['item']}.done"
    if done_f.exists():
        return "done-skip"
    for d in (feat_dir, mem_dir):
        d.mkdir(parents=True, exist_ok=True)
    fjsonl = feat_dir / f"{it['item']}.jsonl"
    mjsonl = mem_dir / f"{it['item']}.jsonl"
    done_members = (
        {r["member"] for r in benchlib.iter_jsonl(fjsonl) if r.get("member")}
        if fjsonl.exists()
        else set()
    )
    tar_path = download_item(it, tar_dir, wdir / "meta")
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
                continue
            bf = tar.extractfile(m)
            blob = bf.read() if bf else b""
            try:
                rec = b3.blob_features(m.name, blob)
            except Exception as e:
                rec = {
                    "member": m.name,
                    "id": b3.member_id(m.name),
                    "member_bytes": m.size,
                    "format": "error",
                    "error": f"{type(e).__name__}: {e}",
                }
            rec.pop("_texts", None)
            rec["item"] = it["item"]
            rec["channel"] = it["channel"]
            rec["band"] = bx.band_of_yymm(it["yymm"])
            mw.write(
                json.dumps({"name": m.name, "size": m.size, "offset": m.offset_data})
                + "\n"
            )
            mw.flush()
            fw.write(json.dumps(rec) + "\n")
            fw.flush()
            n += 1
            if n % 1000 == 0:
                log(f"  {it['item']}: {n} members {time.time() - t0:.0f}s")
    done_f.write_text(f"{n} members\n")
    tar_path.unlink(missing_ok=True)
    (tar_dir / f"{it['item']}.tar.part").unlink(missing_ok=True)
    return f"scanned {n}"


def cmd_scan(args: argparse.Namespace) -> None:
    plan = load_plan(args.layer)
    items = plan["items"][: args.limit] if args.limit else plan["items"]
    wdir = layer_dir(args.layer)
    todo = [
        it for it in items if not (wdir / "features" / f"{it['item']}.done").exists()
    ]
    log(f"scan[{args.layer}]: {len(todo)}/{len(items)} items pending")
    errs = []
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(scan_item, it, args.layer): it for it in todo}
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
                wdir / "scan_log.jsonl",
                {"item": it["item"], "state": state, "ts": time.strftime("%FT%T")},
            )
    log(f"scan pass done, {len(errs)} failed: {errs or '-'}")


# ---------------- extract ----------------


def load_pool(layer: str, profile: dict) -> dict[str, dict]:
    """本层 features → {id: rec}（eligible + 月份闸 + 去重）。"""
    excl = existing_ids()
    excl_months = cluster_months() if profile["exclude_cluster_months"] else set()
    cand: dict[str, dict] = {}
    for fp in sorted((layer_dir(layer) / "features").glob("*.jsonl")):
        for f in benchlib.iter_jsonl(fp):
            if not b3.eligible(f) or f["id"] in excl:
                continue
            if bx.member_yymm(f["member"]) in excl_months:
                continue
            cand[f["id"]] = f
    return cand


def frame_filter(pool_ids: set[str]) -> dict[str, dict]:
    """frame_lookup 只留 pool 内 id（bx 同源逻辑——work_v3 已清, 文件在）。"""
    return bx.frame_filter(pool_ids)


def flag_hit(f: dict, flag: str) -> bool:
    if flag == "docstyle209":
        return bool(f.get("docstyle"))
    return flag in (f.get("flags") or [])


def select_quota(
    layer: str, profile: dict, quotas: dict[str, int]
) -> tuple[list[dict], dict]:
    """cell 配额选样：frame join → cell 池 → 种子 shuffle 取头。"""
    rng = random.Random(SEED)
    cand = load_pool(layer, profile)
    lut = frame_filter(set(cand))
    c2y = bx.yymm2cluster()
    pools: dict[str, list[dict]] = defaultdict(list)
    for pid, f in cand.items():
        fr = lut.get(pid) or b3.frame_get(lut, pid)
        if fr is None:
            continue
        band = f.get("band") or bx.band_of_yymm(bx.member_yymm(f["member"]))
        cell = f"{band}|{fr['cat_group']}"
        if cell not in quotas:
            continue
        f["cat_group"] = fr["cat_group"]
        f["license_class"] = fr["license_class"]
        f["_cell"] = cell
        f["cluster_id"] = c2y.get(bx.member_yymm(f["member"]))
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


def select_flags(layer: str, profile: dict) -> tuple[list[dict], dict]:
    """旗标选样：FLAG_QUOTAS 稀有优先顺序填充；短收→old-era 随机回填。"""
    rng = random.Random(SEED)
    cand = load_pool(layer, profile)
    lut = frame_filter(set(cand))
    c2y = bx.yymm2cluster()
    for pid, f in cand.items():
        fr = lut.get(pid) or b3.frame_get(lut, pid)
        f["cat_group"] = (fr or {}).get("cat_group") or "unknown"
        f["license_class"] = (fr or {}).get("license_class")
        f["cluster_id"] = c2y.get(bx.member_yymm(f["member"]))
    picked: dict[str, dict] = {}
    stats = {}
    for flag, q in FLAG_QUOTAS:
        pool = [f for pid, f in cand.items() if pid not in picked and flag_hit(f, flag)]
        rng.shuffle(pool)
        take = pool[:q]
        for f in take:
            f["_cell"] = f"flag:{flag}"
            picked[f["id"]] = f
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
            if pid not in picked and (f.get("band") or "z") <= "c_2012_16"
        ]
        rng.shuffle(old_pool)
        for f in old_pool[:shortfall]:
            f["_cell"] = "failmine_fill"
            picked[f["id"]] = f
        stats["failmine_fill"] = {
            "quota": shortfall,
            "take": min(shortfall, len(old_pool)),
            "avail": len(old_pool),
            "deficit": max(0, shortfall - len(old_pool)),
        }
    return list(picked.values()), stats


def offsets_for(item: str, layer: str) -> dict[str, tuple[int, int]]:
    out = {}
    p = layer_dir(layer) / "members" / f"{item}.jsonl"
    if p.exists():
        for r in benchlib.iter_jsonl(p):
            off = r.get("offset", r.get("offset_data"))
            if off is None:
                continue
            out[r["name"]] = (off, r["size"])
    return out


def materialize(rec: dict, blob: bytes, sha: str, layer: str, profile: dict) -> dict:
    """blob → corpus_v3/{id}/ + manifest 行（layer=本层）。"""
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
    yymm = bx.member_yymm(rec["member"])
    # _cell 形态：配额层 "band|cat"；矿层 "flag:X"/"failmine_fill" → band 取 features 记录
    band = rec["_cell"].split("|", 1)[0]
    if band.startswith("flag:") or band == "failmine_fill" or "|" not in rec["_cell"]:
        band = rec.get("band") or bx.band_of_yymm(yymm)
    meta = {
        "arxiv_id": pid,
        "resolved_version": None,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "era": era,
        "archive": pid.split("/")[0] if "/" in pid else None,
        "yymm": yymm,
        "cluster_id": rec.get("cluster_id") or f"{profile['cluster_prefix']}-{band}",
        "year_band": band,
        "layer": layer,
        "stratum_cell": rec["_cell"],
        "cat_group": rec.get("cat_group"),
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
        "features": b3.extracted_features(dest / "extracted"),
        "pick_reason": f"{layer}:{rec['_cell']}",
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
        "layer": layer,
        "channel": rec["channel"],
        "item": rec["item"],
        "member": rec["member"],
        "blob_sha256": sha,
        "main_tex_sha256": main_sha,
        "stratum_cell": rec["_cell"],
        "cat_group": rec.get("cat_group"),
        "license_class": rec.get("license_class"),
        "format": fmt,
        "n_files": n_ext,
        "n_tex": rec.get("n_tex_files"),
        "bytes": len(blob),
        "pick_reason": meta["pick_reason"],
    }


def cmd_extract(args: argparse.Namespace) -> None:
    layer = args.layer
    profile = PROFILES[layer]
    wdir = layer_dir(layer)
    wdir.mkdir(parents=True, exist_ok=True)
    plan = load_plan(layer)
    if profile["quota"] == "flags":
        sel, stats = select_flags(layer, profile)
    else:
        sel, stats = select_quota(layer, profile, plan["quotas"])
    if args.limit:
        sel = sel[: args.limit]
    benchlib.atomic_write_text(wdir / "select_stats.json", json.dumps(stats, indent=1))
    log(f"select[{layer}]: {len(sel)} picks")
    man = manifest_path(layer)
    done = {r["id"] for r in benchlib.read_jsonl(man)} if man.exists() else set()
    if args.topup:
        have = Counter(r.get("stratum_cell") for r in benchlib.read_jsonl(man))
        need = {c: s.get("quota", 0) - have.get(c, 0) for c, s in stats.items()}
        deficit = {c: n for c, n in need.items() if n > 0}
        sel = [r for r in sel if r["id"] not in done]
        keep: list[dict] = []
        for rec in sel:
            cell = rec["_cell"]
            if need.get(cell, 0) > 0:
                need[cell] -= 1
                keep.append(rec)
        log(f"topup[{layer}]: deficit={deficit} -> {len(keep)} fresh picks")
        sel = keep
    for rec in sel:
        if rec["id"] in done or not (CORPUS / rec["id"] / "meta.json").exists():
            continue
        row = bx.manifest_row_from_meta(CORPUS / rec["id"])
        if row is None:
            continue
        benchlib.append_jsonl(man, row)
        done.add(rec["id"])
    todo = [r for r in sel if r["id"] not in done]
    old_tars = {
        it: b3.TARS / f"{it}.tar"
        for it in {r["item"] for r in todo}
        if (b3.TARS / f"{it}.tar").exists()
    }
    offs = {it: offsets_for(it, layer) for it in {r["item"] for r in todo}}
    n0 = len(todo)
    todo = [r for r in todo if r["member"] in offs.get(r["item"], {})]
    if n0 - len(todo):
        log(f"!! {n0 - len(todo)} members 无 offset 记录，跳过")
    log(
        f"extract[{layer}]: {len(todo)} to fetch "
        f"({sum(r['item'] in old_tars for r in todo)} local / "
        f"{sum(r['item'] not in old_tars for r in todo)} range-get)"
    )
    n_ok = n_err = 0
    records = wdir / "extract_records.jsonl"
    with open(man, "a") as mfh, ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(bx.fetch_blob, rec, old_tars, offs): rec for rec in todo}
        for fut in as_completed(futs):
            rec = futs[fut]
            try:
                blob = fut.result()
                sha = hashlib.sha256(blob).hexdigest()
                if sha != rec["blob_sha256"]:
                    msg = f"sha256 mismatch {sha[:12]}"
                    raise OSError(msg)  # noqa: TRY301
                row = materialize(rec, blob, sha, layer, profile)
                mfh.write(json.dumps(row, ensure_ascii=False) + "\n")
                mfh.flush()
                n_ok += 1
                st = "ok"
            except Exception as e:
                n_err += 1
                st = f"error: {type(e).__name__}: {e}"
                log(f"  ERR {rec['id']}: {st}")
            benchlib.append_jsonl(
                records,
                {
                    "id": rec["id"],
                    "item": rec["item"],
                    "member": rec["member"],
                    "cell": rec.get("_cell"),
                    "state": st,
                    "ts": time.strftime("%FT%T"),
                },
            )
            if (n_ok + n_err) % 200 == 0:
                log(f"  extract {n_ok + n_err}/{len(todo)} ok={n_ok} err={n_err}")
    log(f"extract[{layer}] done: ok={n_ok} err={n_err} -> {man}")


# ---------------- eprint recent 臂 ----------------


def cmd_recent(args: argparse.Namespace) -> None:
    """ids 清单 → acquire_source → corpus cells（layer 归属由 --layer 定）。

    与 hot 层同取源路径（arxiv.org/src 钉版）；--limit 日预算护栏。
    """
    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import AcquireStatus, Fetcher, acquire_source

    layer = args.layer
    prefix = PROFILES.get(layer, {}).get("cluster_prefix", layer.upper()[:2])
    man = manifest_path(layer)
    cands = benchlib.read_jsonl(Path(args.ids_file))
    done_ids = (
        {r["id"] for r in benchlib.iter_jsonl(man) if r.get("id")}
        if man.exists()
        else set()
    )
    taken = benchlib.corpus_ids(CORPUS)
    fetcher = Fetcher()
    cache = SourceCache(Path.home() / ".cache" / "texlate" / "src")
    n_new = 0
    with man.open("a", encoding="utf-8") as mf:
        for cand in cands:
            pid = cand["id"]
            if pid in done_ids:
                continue
            if pid in taken:
                log(f"  skip {pid}: 已在册")
                continue
            if n_new >= args.limit:
                log(f"limit {args.limit} reached — 明日续跑（预算护栏）")
                break
            if (CORPUS / pid / "extracted").is_dir():
                try:
                    meta = json.loads(
                        (CORPUS / pid / "meta.json").read_text(encoding="utf-8")
                    )
                    mf.write(
                        json.dumps(
                            bx.manifest_row_from_meta(CORPUS / pid),
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    mf.flush()
                    done_ids.add(pid)
                    continue
                except (OSError, json.JSONDecodeError):
                    pass
            log(f"fetch {pid} ({layer})")
            try:
                res = acquire_source(pid, fetcher=fetcher, cache=cache)
            except Exception as e:
                log(f"  !! {pid} acquire raised {type(e).__name__}: {e} — 停批续跑")
                break
            n_new += 1
            if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
                log(f"  skip {pid}: {res.status.value} {res.detail or ''}")
                benchlib.append_jsonl(
                    layer_dir(layer) / "recent_fail.jsonl",
                    {"id": pid, "status": res.status.value, "detail": res.detail},
                )
                continue
            assert res.entry is not None
            entry = res.entry.dir
            dest = CORPUS / pid
            dest.mkdir(parents=True, exist_ok=True)
            stale = dest / "extracted"
            if stale.exists():
                shutil.rmtree(stale)
            shutil.copytree(entry / "extracted", stale)
            for raw in entry.glob("raw.*"):
                shutil.copy2(raw, dest / raw.name)
            meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
            yymm = pid.split(".")[0][:4] if "." in pid else pid.split("/")[-1][:4]
            locate_main = ((meta.get("locate") or {}).get("main")) or None
            main_sha = None
            if locate_main and (dest / "extracted" / locate_main).exists():
                main_sha = hashlib.sha256(
                    (dest / "extracted" / locate_main).read_bytes()
                ).hexdigest()
            meta.update(
                {
                    "era": "new" if "." in pid else "old",
                    "archive": None,
                    "yymm": yymm,
                    "cluster_id": f"{prefix}-R",
                    "layer": layer,
                    "stratum_cell": f"{layer}|recent",
                    "cat_group": cand.get("cat_group") or "recent",
                    "channel": "arxiv_eprint",
                    "pick_reason": f"{layer}_recent",
                    "main_tex_sha256": main_sha,
                    "source": "sw_pool+arxiv_eprint",
                }
            )
            (dest / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8",
            )
            ext = dest / "extracted"
            n_files = sum(1 for p in ext.rglob("*") if p.is_file())
            n_tex = sum(1 for p in ext.rglob("*.tex"))
            raw = next(dest.glob("raw.*"), None)
            mf.write(
                json.dumps(
                    {
                        "id": pid,
                        "era": meta["era"],
                        "archive": None,
                        "yymm": yymm,
                        "cluster_id": f"{prefix}-R",
                        "layer": layer,
                        "channel": "arxiv_eprint",
                        "item": None,
                        "member": None,
                        "blob_sha256": meta.get("raw_sha256"),
                        "main_tex_sha256": main_sha,
                        "stratum_cell": f"{layer}|recent",
                        "cat_group": meta.get("cat_group"),
                        "license_class": None,
                        "format": meta.get("format"),
                        "n_files": n_files,
                        "n_tex": n_tex,
                        "bytes": raw.stat().st_size if raw else None,
                        "pick_reason": f"{layer}_recent",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            mf.flush()
            done_ids.add(pid)
            log(f"  ok {pid} v{res.resolved_version}")


# ---------------- qc ----------------


def cmd_qc(args: argparse.Namespace) -> None:
    layer = args.layer
    wdir = layer_dir(layer)
    man = manifest_path(layer)
    rows = benchlib.read_jsonl(man)
    ids = [r["id"] for r in rows]
    dup = [i for i, c in Counter(ids).items() if c > 1]
    by_cell = Counter(r.get("stratum_cell") for r in rows)
    missing_meta = [
        r["id"] for r in rows if not (CORPUS / r["id"] / "meta.json").exists()
    ]
    empty_ext = [
        r["id"]
        for r in rows
        if r.get("format") in ("tar", "gz")
        and not any((CORPUS / r["id"] / "extracted").glob("*"))
    ]
    overlap = sorted(set(ids) & (existing_ids() - set(ids)))
    stats = (
        json.loads((wdir / "select_stats.json").read_text())
        if (wdir / "select_stats.json").exists()
        else {}
    )
    lines = [
        f"# {layer} 层自检",
        "",
        f"- manifest_{layer} 入库 **{len(rows)}**",
        f"- id 重复: {sorted(dup) or '无'}",
        f"- 跨层撞 id: {overlap[:10] or '无'} (n={len(overlap)})",
        f"- 缺 meta.json: {missing_meta[:10] or '无'} (n={len(missing_meta)})",
        f"- extracted 空: {empty_ext[:10] or '无'} (n={len(empty_ext)})",
        "",
        "| cell | 实收 | quota | avail | deficit |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cell, s in sorted(stats.items()):
        lines.append(
            f"| {cell} | {by_cell.get(cell, 0)} | {s.get('quota', '-')} "
            f"| {s.get('avail', '-')} | {s.get('deficit', '-')} |"
        )
    (wdir / "qc.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    log(f"qc[{layer}]: {len(rows)} rows")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["plan", "scan", "extract", "qc", "recent"])
    ap.add_argument("--layer", required=True, choices=LAYER_NAMES)
    ap.add_argument(
        "--ids-file",
        default="",
        help="recent: sw assign 清单（jsonl {id, cat_group?}）",
    )
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="冒烟/日预算护栏")
    ap.add_argument(
        "--topup",
        action="store_true",
        help="extract: 只补 deficit cell（quota − manifest 实收），不动足额 cell",
    )
    a = ap.parse_args()
    if a.cmd == "recent" and not a.ids_file:
        ap.error("recent 需要 --ids-file")
    layer_dir(a.layer).mkdir(parents=True, exist_ok=True)
    {
        "plan": cmd_plan,
        "scan": cmd_scan,
        "extract": cmd_extract,
        "qc": cmd_qc,
        "recent": cmd_recent,
    }[a.cmd](a)


if __name__ == "__main__":
    main()
