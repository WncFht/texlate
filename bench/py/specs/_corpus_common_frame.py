"""_corpus_common frame 资产叶——frame_lookup 单件 / allocation·cluster-cat-mix / chunks.json。

``pyarrow`` 惰性 import 在使用点内（scan 链路系统 python3 可载）。
"""

from __future__ import annotations

import csv
import gzip
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from specs._corpus_common_io import BUILD_ROOT, FRAME, log


# ---------------------------------------------------------------- frame 资产
def frame_lookup_path(build_root: Path = BUILD_ROOT) -> Path:
    """全 builder 共享的 frame_lookup.tsv.gz 落点（corpus-build 根）。"""
    return Path(build_root) / "frame_lookup.tsv.gz"


def ensure_frame_lookup(frame_dir: Path = FRAME, build_root: Path = BUILD_ROOT) -> Path:
    """frame.parquet → frame_lookup.tsv.gz（缺时现算；pyarrow 惰性）。

    v3/expand/layers 谁先到谁建——原子写幂等。缺 frame.parquet → OSError
    （frame_build ord-0 前置未跑，调用方按 fail-closed 处理）。"""
    out = frame_lookup_path(build_root)
    if out.exists():
        return out
    import pyarrow.parquet as pq

    src = Path(frame_dir) / "frame.parquet"
    t = pq.read_table(
        src,
        columns=[
            "id",
            "tar_yymm",
            "year_band",
            "cat_group",
            "primary_cat",
            "license_class",
        ],
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as f:
        cols = [t.column(n).to_pylist() for n in t.column_names]
        for row in zip(*cols, strict=True):
            f.write("\t".join("" if v is None else str(v) for v in row) + "\n")
    os.replace(tmp, out)
    log(f"frame_lookup: {t.num_rows} rows -> {out}")
    return out


def load_frame_lookup(path: Path) -> dict[str, dict]:
    lut = {}
    with gzip.open(path, "rt") as f:
        for line in f:
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


def frame_filter(pool_ids: set[str], path: Path) -> dict[str, dict]:
    """frame_lookup 只留 pool 内 id 的行（全量 3.16M 行驻留太大，过滤装载）."""
    lut: dict[str, dict] = {}
    with gzip.open(path, "rt") as f:
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


def frame_meta_for(ids: list[str], path: Path) -> dict[str, dict]:
    """frame_lookup 流式过滤 → {id: {tar_yymm, year_band, cat_group, license_class}}."""
    want = set(ids)
    out: dict[str, dict] = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            pid = line.split("\t", 1)[0]
            if pid in want:
                p = line.rstrip("\n").split("\t")
                out[pid] = {
                    "tar_yymm": p[1] if len(p) > 1 else None,
                    "year_band": p[2] if len(p) > 2 else None,
                    "cat_group": p[3] if len(p) > 3 else None,
                    "primary_cat": p[4] if len(p) > 4 else None,
                    "license_class": p[5] if len(p) > 5 else None,
                }
            if len(out) == len(want):
                break
    return out


def frame_get(lut: dict, pid: str) -> dict | None:
    """成员 id → frame 行; 旧式 math.XX/ 归并 math/ 回退."""
    r = lut.get(pid)
    if r is None and "/" in pid:
        arch, num = pid.split("/", 1)
        if "." in arch:
            r = lut.get(f"{arch.split('.')[0]}/{num}")
    return r


def yymm2cluster(frame_dir: Path = FRAME) -> dict[str, str]:
    with (Path(frame_dir) / "allocation-core.csv").open(newline="") as fh:
        return {r["yymm"]: r["cluster_id"] for r in csv.DictReader(fh)}


def cluster2band(frame_dir: Path = FRAME) -> dict[str, str]:
    with (Path(frame_dir) / "allocation-core.csv").open(newline="") as fh:
        return {r["cluster_id"]: r["year_band"] for r in csv.DictReader(fh)}


def band_cat_share(frame_dir: Path = FRAME) -> dict[str, dict[str, float]]:
    """cluster-cat-mix → {band: {cat: share}}（带内聚合，估算 item 产出用）."""
    agg: dict[str, Counter] = defaultdict(Counter)
    with (Path(frame_dir) / "cluster-cat-mix.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            agg[r["year_band"]][r["cat_group"]] += int(r["n"])
    return {
        b: {c: n / sum(cs.values()) for c, n in cs.items()} for b, cs in agg.items()
    }


def load_chunks(v3_workdir: Path) -> list[dict]:
    """v3 builder 的 chunks.json（旧池 membership 单源）；缺档 → []."""
    p = Path(v3_workdir) / "chunks.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return []
