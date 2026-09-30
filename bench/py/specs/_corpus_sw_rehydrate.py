"""corpus_sw rehydrate/report 段叶——rgrows worker 抽 latex → hydrate 落格 +
manifest 追加（崩溃窗自愈）+ manifest 聚合报表。"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import tarfile
import time
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from kernel import lake

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs._corpus_sw_base import (
    CHANNEL,
    LAYER,
    MANIFEST_OUT,
    PICK_REASON,
    RG_ATTEMPTS,
    _iter_jsonl,
    _reduced_features,
    _sw,
    cat_group_of,
    shard_name,
    split_files,
)
from specs._corpus_sw_manifest import (
    _all_manifest_ids,
    _manifest_ids,
    _manifest_row,
)
from specs._corpus_sw_worker import _hf_run

if TYPE_CHECKING:
    from pathlib import Path


def _meta_extra(
    r: dict, files: dict[str, str], sha: str, blob_n: int, tex_n: int
) -> dict:
    """湖格 meta.json 的 fetch_fn 贡献——hydrate 自管 idc/source/n_files/
    hydrated_at/run_seq，这里给其余全字段（含 figures_stripped 契约）。"""
    pid = r["id"]
    yymm = r["yymm_id"][:4]
    cg = cat_group_of(r["categories"])
    return {
        "arxiv_id": pid,
        "resolved_version": None,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "era": "new" if "." in pid else "old",
        "archive": None,
        "yymm": yymm,
        "cluster_id": f"SW-{yymm}",
        "year_band": "f_2025plus",
        "layer": LAYER,
        "stratum_cell": f"sw|{yymm}",
        "cat_group": cg,
        "license_class": None,
        "license": r.get("license"),
        "categories": r.get("categories"),
        "channel": CHANNEL,
        "item": shard_name(r["shard"]),
        "member": pid,
        "raw_sha256": sha,
        "raw_file": "raw.tar.gz",
        "format": "tar",
        "tex_files": tex_n,
        "bytes": blob_n,
        "figures_stripped": True,
        "sw": {
            "shard": r["shard"],
            "rg": r["rg"],
            "update_date": r.get("update_date"),
            "version": r.get("version"),
        },
        "features": _reduced_features(files),
        "pick_reason": PICK_REASON,
        "source": CHANNEL,
    }


def _fetch_for(r: dict, files: dict[str, str]):
    """行 + 拆包结果 → lake.hydrate 的 fetch_fn（extracted/ + raw/ 双写）。"""

    def fetch(_idc: str, stage: Path) -> dict:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, text in files.items():
                data = text.encode("utf-8", "replace")
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
        blob = buf.getvalue()
        sha = hashlib.sha256(blob).hexdigest()
        raw = stage / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "raw.tar.gz").write_bytes(blob)
        ext = stage / "extracted"
        ext.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            fp = ext / name
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(text, encoding="utf-8", errors="replace")
        tex_n = sum(1 for p in files if p.lower().endswith(".tex"))
        return _meta_extra(r, files, sha, len(blob), tex_n)

    return fetch


def _rehydrate(ctx):
    """assign_sw picks → 逐 rg worker 抽 latex → lake.hydrate 落格 + manifest。

    断点口径：done=dev_recent manifest ids；taken=其余 manifest ids；
    complete 湖格未上榜 → meta 重建行（崩溃窗自愈）。n_err>0 → error
    （retriable——done 集让下次 run 只补缺口）。
    """
    sw = _sw()
    apath = sw / "assign_sw.jsonl"
    if not apath.exists():
        return {
            "status": "error",
            "errors": [{"cat": "env", "msg": f"missing {apath}"}],
        }
    if shutil.which("uv") is None:
        return {"status": "error", "errors": [{"cat": "env", "msg": "uv not on PATH"}]}
    picks = [p for p in _iter_jsonl(apath) if p.get("id")]
    done = _manifest_ids(MANIFEST_OUT) if MANIFEST_OUT.exists() else set()
    taken = _all_manifest_ids()  # 含 done——manifest 过的 id 一律不碰
    by_rg: dict[tuple[int, int], list[dict]] = defaultdict(list)
    n_done = n_taken = 0
    for p in picks:
        idc = cc.canon_or_self(p["id"])
        if idc in taken:
            if idc in done:
                n_done += 1
            else:
                n_taken += 1
            continue
        by_rg[(p["shard"], p["rg"])].append(p)

    MANIFEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    limit = int(ctx.params.get("limit") or 0)
    ws = ctx.workspace() / "rgrows"
    ws.mkdir(parents=True, exist_ok=True)
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    cat = lake.LakeCatalog.load()
    n_ok = n_skip = n_err = n_heal = 0
    stop = False
    with MANIFEST_OUT.open("a", encoding="utf-8") as mf:
        for (sn, rgi), plist in sorted(by_rg.items()):
            pending: list[dict] = []
            for p in plist:
                idc = cc.canon_or_self(p["id"])
                if lake.is_complete(idc):
                    # 湖格在、manifest 行不在（hydrate→append 崩溃窗）：
                    # meta.json 重建行直接补账，不碰网络。
                    meta = {}
                    with contextlib.suppress(OSError, ValueError):
                        meta = json.loads(
                            (lake.cell_dir(idc) / "meta.json").read_text(
                                encoding="utf-8"
                            )
                        )
                    row = _manifest_row(meta, p["id"], lake.cell_dir(idc) / "extracted")
                    mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    mf.flush()
                    n_heal += 1
                else:
                    pending.append(p)
            if pending:
                want_f = ws / f"want_{sn:04d}_{rgi:03d}.txt"
                want_f.write_text(
                    "".join(p["id"] + "\n" for p in pending), encoding="utf-8"
                )
                rows_f = ws / f"rg_{sn:04d}_{rgi:03d}.jsonl"
                ok_rg = False
                for attempt in range(RG_ATTEMPTS):
                    rc, tail = _hf_run(
                        ("rgrows", sn, rgi, want_f, rows_f), timeout_s=1800
                    )
                    if rc == 0 and rows_f.exists():
                        ok_rg = True
                        break
                    ctx.emit(
                        {
                            "stage": "rehydrate",
                            "metric": "sw_rg_retry",
                            "shard": sn,
                            "rg": rgi,
                            "attempt": attempt + 1,
                            "rc": rc,
                            "err": tail,
                        }
                    )
                    if attempt + 1 < RG_ATTEMPTS:
                        time.sleep(15 * (attempt + 1))
                if not ok_rg:
                    n_err += len(pending)
                    ctx.emit(
                        {
                            "stage": "rehydrate",
                            "metric": "sw_rg_fail",
                            "shard": sn,
                            "rg": rgi,
                            "lost": len(pending),
                        }
                    )
                    continue
                rows = {r["id"]: r for r in _iter_jsonl(rows_f) if r.get("id")}
                for p in pending:
                    r = rows.get(p["id"])
                    if r is None:
                        n_skip += 1
                        continue
                    r["shard"] = sn
                    r["rg"] = rgi
                    files = split_files(r["latex"] or "")
                    if not any(pf.lower().endswith(".tex") for pf in files):
                        n_skip += 1
                        continue
                    idc = cc.canon_or_self(p["id"])
                    try:
                        d = lake.hydrate(
                            idc,
                            fetch_fn=_fetch_for(r, files),
                            source="arxiv",
                            run_seq=run_seq,
                        )
                    except Exception as e:
                        ctx.emit(
                            {
                                "stage": "rehydrate",
                                "metric": "sw_cell_err",
                                "id": p["id"],
                                "err": f"{type(e).__name__}: {e}",
                            }
                        )
                        n_err += 1
                        continue
                    if d is None or not lake.is_complete(idc):
                        n_err += 1
                        continue
                    # raw 是重打包文本树（非网络可再生的零成本件）——
                    # catalog 标 regen_cost=network，驱逐永不先逐 raw。
                    base = cat.rows().get(idc) or {}
                    layers = sorted(set(base.get("layers") or []) | {LAYER})
                    channels = sorted(set(base.get("channels") or []) | {CHANNEL})
                    # 写死 "hydrated"——本 cat 实例在段头 load，hydrate 内部
                    # 是自己的实例；拿陈旧 state() 会把刚落的行打回 absent。
                    cat.set(
                        idc,
                        "hydrated",
                        source="arxiv",
                        regen_cost="network",
                        layers=layers,
                        channels=channels,
                    )
                    meta = {}
                    with contextlib.suppress(OSError, ValueError):
                        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                    row = _manifest_row(meta, p["id"], d / "extracted")
                    mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    mf.flush()
                    n_ok += 1
            ctx.emit(
                {
                    "stage": "rehydrate",
                    "metric": "sw_rg",
                    "shard": sn,
                    "rg": rgi,
                    "ok": n_ok,
                    "skip": n_skip,
                    "err": n_err,
                    "heal": n_heal,
                }
            )
            if limit and n_ok >= limit:
                stop = True
                break
    status = "error" if n_err else "ok"
    return {
        "status": status,
        "metrics": {
            "picks": len(picks),
            "n_ok": n_ok,
            "n_skip": n_skip,
            "n_err": n_err,
            "n_heal": n_heal,
            "n_done": n_done,
            "n_taken": n_taken,
            "rgs": len(by_rg),
            "limit_hit": int(stop),
            "manifest": str(MANIFEST_OUT),
        },
    }


def _report(ctx):
    """manifest_dev_recent.jsonl 聚合 → metrics（恒 ok——真账由上游段背）。"""
    rows = list(_iter_jsonl(MANIFEST_OUT)) if MANIFEST_OUT.exists() else []
    months = Counter(r.get("yymm") for r in rows)
    cats = Counter(r.get("cat_group") for r in rows)
    ctx.emit(
        {
            "stage": "report",
            "metric": "sw_report",
            "n": len(rows),
            "months": dict(sorted(months.items())),
            "cats": dict(cats.most_common()),
        }
    )
    return {
        "status": "ok",
        "metrics": {
            "n_rows": len(rows),
            "months": dict(sorted(months.items())),
            "cat_groups": dict(cats.most_common()),
            "sum_mb": round(sum(r.get("bytes") or 0 for r in rows) / 1e6, 1),
            "sum_tex": sum(r.get("n_tex") or 0 for r in rows),
            "manifest": str(MANIFEST_OUT),
        },
    }
