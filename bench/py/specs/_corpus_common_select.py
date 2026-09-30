"""_corpus_common 选样/物化机叶——rates 三路解析 / 跨月 round-robin / 候选枚举 / 配额选单物化。"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from kernel import idnorm, lake, paths
from kernel import index as indexmod

from specs._benchlite import append_jsonl, read_jsonl
from specs._corpus_common_frame import cluster2band, load_chunks
from specs._corpus_common_io import canon_id
from specs._corpus_common_materialize import (
    manifest_row_from_meta,
    materialize_into_stage,
)
from specs._corpus_common_net import item_url
from specs._corpus_common_scan import band_of_yymm, fetch_blob, offsets_for

# ---------------------------------------------------------------- 选样/物化机
# （corpus_expand ↔ corpus_layers verbatim 双份收编：rates 三路解析 / 跨月
# round-robin / item 候选枚举 / 配额选单 → lake.hydrate 物化主循环。）
SEED = 42  # 抽样口径常量（非旋钮——进 params 会诱改口径）
RUN_REF_RX = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*/[0-9]{4}-[0-9]{2}-[0-9]{2}/[A-Za-z0-9][A-Za-z0-9._-]*"
)
#: plan 依赖的 frame 资产清单——frame_build ord-0 前置；缺一件即 fail-closed。
FRAME_NEEDS = (
    "item-index.csv",
    "tiger-files.csv",
    "allocation-core.csv",
    "cluster-cat-mix.csv",
)


class HaltFetch(Exception):
    """限流到顶（parked/budget）——停批续跑，截断返 error。"""


class TransientMiss(Exception):
    """逐件瞬态 miss——记 fail 账续走下一候选。"""


def canon_or_self(raw, fallback=None) -> str:
    """``idnorm.canon_id`` 全解 → idc；解不出回 ``str(raw)``（或
    ``fallback(raw)``——hydrate 的 idc_from_safe 两跳口径走它）。"""
    res = idnorm.canon_id(str(raw))
    if res.ok and res.idc:
        return res.idc
    return str(raw) if fallback is None else fallback(raw)


def bad_rates(stat: dict[str, Counter]) -> dict[str, float]:
    """{key: Counter(bad/ok)} → {key: bad 占比}。"""
    return {
        k: c["bad"] / (c["bad"] + c["ok"])
        for k, c in stat.items()
        if c["bad"] + c["ok"]
    }


def rates_from_idstatus(
    id_status: dict[str, str], manifest_rows: list[dict], frame_dir: Path
) -> tuple[dict, dict, float]:
    """{id: status} × manifest×frame join → (band_bad_rate, cat_bad_rate, global).

    bad=status∈{fail,reject,partial}（n100_rates 同口径）；id 双侧 canon 归一。"""
    by_id = {canon_id(r["id"]): r for r in manifest_rows if r.get("id")}
    c2b = cluster2band(frame_dir)
    band_stat: dict[str, Counter] = defaultdict(Counter)
    cat_stat: dict[str, Counter] = defaultdict(Counter)
    n_bad = 0
    for pid, st in id_status.items():
        bad = st in ("fail", "reject", "partial")
        n_bad += bad
        m = by_id.get(canon_id(pid), {})
        band = c2b.get(m.get("cluster_id"), "?")
        cat = m.get("cat_group") or "?"
        band_stat[band]["bad" if bad else "ok"] += 1
        cat_stat[cat]["bad" if bad else "ok"] += 1
    if not id_status:
        return {}, {}, 0.0
    return bad_rates(band_stat), bad_rates(cat_stat), n_bad / len(id_status)


def run_id_statuses(run_id: str) -> dict[str, str] | None:
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
    return {canon_id(r["idc"]): r["status"] for r in rows}


def resolve_rates(
    rates_source: str, manifest_rows: list[dict], frame_dir: Path
) -> tuple[dict, dict, float, str, str]:
    """rates_source → (fr_band, fr_cat, fr_all, mode, detail)。

    三路：run ref | rates json | flat_fallback。显式源解析失败 → RuntimeError
    （fail-closed：口径错配绝不能静默退化成 flat）。"""
    src = str(rates_source or "").strip()
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
        fr_b, fr_c, fr_a = rates_from_idstatus(idst, manifest_rows, frame_dir)
        return fr_b, fr_c, fr_a, "idstatus_file", str(p)
    if RUN_REF_RX.fullmatch(src):
        idst = run_id_statuses(src)
        if idst is None:
            msg = f"rates_source run 不可解析（spec.json/stages 缺）: {src}"
            raise RuntimeError(msg)
        fr_b, fr_c, fr_a = rates_from_idstatus(idst, manifest_rows, frame_dir)
        return fr_b, fr_c, fr_a, "run", src
    msg = f"rates_source 既不是文件也不是 run ref: {src!r}"
    raise RuntimeError(msg)


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


def candidate_items(
    frame_dir: Path,
    done: set[str],
    *,
    excl_months: set[str] | frozenset[str] = frozenset(),
    bands: str | None = None,
) -> dict[str, list[dict]]:
    """{band: [item…]} 未扫候选（ia item-index ∪ tiger-files）。

    ``excl_months``：剔除的簇月 yymm 集（holdout 时间外推闸）；
    ``bands``：允许的年带首字母串（"abc" 只采 a/b/c 带——矿层旧档定向）。"""
    out: dict[str, list[dict]] = defaultdict(list)
    with (Path(frame_dir) / "item-index.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            item, yymm = r["identifier"], r["yymm"]
            if item in done or yymm in excl_months:
                continue
            band = band_of_yymm(yymm)
            if bands is not None and band[0] not in bands:
                continue
            out[band].append(
                {
                    "item": item,
                    "yymm": yymm,
                    "chunk_no": int(r["chunk"]),
                    "channel": "ia",
                    "size": int(r["size"]),
                    "url": item_url("ia", item),
                }
            )
    with (Path(frame_dir) / "tiger-files.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            m = re.match(r"(arXiv_src_(\d{4})_(\d{3}))\.tar$", r["path"])
            if not m or m.group(1) in done or m.group(2) in excl_months:
                continue
            band = band_of_yymm(m.group(2))
            if bands is not None and band[0] not in bands:
                continue
            out[band].append(
                {
                    "item": m.group(1),
                    "yymm": m.group(2),
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


def member_fetch_fn(
    rec: dict,
    old_tars: dict,
    offs: dict,
    *,
    layer: str,
    cluster_prefix: str,
    reason: str,
):
    """lake.hydrate fetch_fn：blob 回取 → sha 复核 → stage 物化 + meta。"""

    def fn(idc, stage):
        blob = fetch_blob(rec, old_tars, offs)
        sha = hashlib.sha256(blob).hexdigest()
        if sha != rec["blob_sha256"]:
            msg = f"sha256 mismatch {sha[:12]}"
            raise OSError(msg)
        return materialize_into_stage(
            rec,
            blob,
            sha,
            stage,
            layer=layer,
            cluster_prefix=cluster_prefix,
            reason=reason,
        )

    return fn


def extract_selected(
    ctx,
    sel: list[dict],
    d: dict,
    *,
    layer: str,
    cluster_prefix: str,
    reason: str,
    metric: str,
    emit_extra: dict | None = None,
    rec_extra=None,
) -> str:
    """配额选单 → lake.hydrate 成员物化 + manifest append（expand/layers 主循环）。

    sel 已过 limit 截断（调用方先切）。d 须带 manifest/records/v3/dirs 键
    （dirs=TarDirs——members 簿与 v3 旧池互为回退）。截尾回补先行：lake cell
    完整而 manifest 缺行 → 从 cell meta 补行不重抓。``emit_extra`` 并入收尾
    metric dict；``rec_extra`` 逐条并入 records 行（expand 的 ``_pool`` 记法）。
    """
    manifest = d["manifest"]
    done = {canon_id(str(r["id"])) for r in read_jsonl(manifest) if r.get("id")}
    # 回补: lake cell 完整而 manifest 缺行（截尾场景）→ 从 cell meta 补行；
    # meta 不可解析则不标 done，走重抓自愈（hydrate 重写 meta+行）
    n_backfill = 0
    for rec in sel:
        pid = canon_id(str(rec["id"]))
        if pid in done:
            continue
        src = rec["channel"]
        cell = lake.cell_dir(rec["id"], source=src)
        if not (cell / "meta.json").exists() or not lake.is_complete(
            rec["id"], source=src
        ):
            continue
        row = manifest_row_from_meta(None, cell, default_layer=layer)
        if row is None:
            continue
        append_jsonl(manifest, row)
        done.add(pid)
        n_backfill += 1
    todo = [r for r in sel if canon_id(str(r["id"])) not in done]
    chunks = load_chunks(d["v3"])
    old_items = {c["item"] for c in chunks}
    tag_of_item = {c["item"]: f"{c['yymm']}_{c['chunk_no']:03d}" for c in chunks}
    need_items = {r["item"] for r in todo}
    old_tars = {
        it: d["v3"] / "tars" / f"{it}.tar"
        for it in need_items & old_items
        if (d["v3"] / "tars" / f"{it}.tar").exists()
    }
    offs = {
        it: offsets_for(it, d["dirs"].members, tag_of_item, d["v3"] / "members")
        for it in need_items
    }
    n0 = len(todo)
    todo = [r for r in todo if r["member"] in offs.get(r["item"], {})]
    if n0 - len(todo):
        ctx.emit_note(f"{n0 - len(todo)} members 无 offset 记录，跳过", level="warn")
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    n_ok = n_err = 0
    jobs = max(1, int(ctx.params["jobs"]))
    with (
        manifest.open("a", encoding="utf-8") as mfh,
        ThreadPoolExecutor(max_workers=jobs) as ex,
    ):
        futs = {
            ex.submit(
                lake.hydrate,
                rec["id"],
                member_fetch_fn(
                    rec,
                    old_tars,
                    offs,
                    layer=layer,
                    cluster_prefix=cluster_prefix,
                    reason=reason,
                ),
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
                    row = manifest_row_from_meta(None, cell, default_layer=layer)
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
            rec_row = {
                "id": pid,
                "item": rec["item"],
                "member": rec["member"],
                "cell": rec["_cell"],
            }
            if rec_extra is not None:
                rec_row.update(rec_extra(rec))
            rec_row.update({"state": st, "ts": time.strftime("%FT%T")})
            append_jsonl(d["records"], rec_row)
    ctx.emit(
        {
            "metric": metric,
            "selected": len(sel),
            "todo": len(todo),
            "ok": n_ok,
            "err": n_err,
            "backfilled": n_backfill,
            "manifest": str(manifest),
            **(emit_extra or {}),
        }
    )
    if n_err == 0:
        return "ok"
    return "partial" if n_ok else "error"
