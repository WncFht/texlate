"""_corpus_common 物化叶——成员 blob/CacheEntry → lake stage 树 + meta + manifest 行。"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from specs._corpus_common_features import extracted_features, unpack_blob
from specs._corpus_common_scan import band_of_yymm, member_yymm

# ---------------------------------------------------------------- 物化（lake cell stage）
RAW_NAME = {
    "tar": "raw.tar.gz",
    "gz": "raw.gz",
    "pdf": "raw.pdf",
    "stub": "raw.stub",
    "error": "raw.bin",
}


def materialize_into_stage(
    rec: dict,
    blob: bytes,
    sha: str,
    stage: Path,
    *,
    layer: str,
    cluster_prefix: str,
    reason: str,
) -> dict:
    """成员 blob → ``{stage}/raw/{raw_name}`` + ``{stage}/extracted/`` +
    meta dict（lake.hydrate fetch_fn 的返回值——lake 自写 meta.json）。

    layer/cluster_prefix/reason 分层注入：expand 传 ("expand","EXP",
    "expand_quota")；layers 传层名+簇前缀, pick_reason=f"{reason}:{_cell}".
    """
    stage = Path(stage)
    pid = rec["id"]
    fmt = rec["format"]
    raw_name = RAW_NAME[fmt]
    raw_dir = stage / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / raw_name).write_bytes(blob)
    n_ext, warns = unpack_blob(blob, fmt, stage)
    roots = rec.get("tex_roots") or []
    main_sha = None
    if len(roots) == 1:
        mp = stage / "extracted" / roots[0]
        if mp.exists():
            main_sha = hashlib.sha256(mp.read_bytes()).hexdigest()
    era = "old" if "/" in pid else "new"
    yymm = member_yymm(rec["member"])
    # _cell 形态：配额层 "band|cat"；矿层 "flag:X"/"failmine_fill" → band 取 features 记录
    band = rec["_cell"].split("|", 1)[0]
    if band.startswith("flag:") or band == "failmine_fill" or "|" not in rec["_cell"]:
        band = rec.get("band") or band_of_yymm(yymm)
    meta = {
        "arxiv_id": pid,
        "resolved_version": None,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "era": era,
        "archive": pid.split("/")[0] if "/" in pid else None,
        "yymm": yymm,
        "cluster_id": rec.get("cluster_id") or f"{cluster_prefix}-{band}",
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
        "n_tex_files": rec.get("n_tex_files"),
        "bytes": len(blob),
        "uncompressed_bytes": rec.get("uncompressed_bytes"),
        "main_tex_sha256": main_sha,
        # 特征以 extracted 树重算为准(expand scan 记录仍是旧合并口径——
        # 无 staging 无法回填; extracted_features 与 blob_features 同一生成码)
        "features": extracted_features(stage / "extracted"),
        "pick_reason": f"{reason}:{rec['_cell']}",
        "warnings": warns,
        "source": rec["channel"],
    }
    if rec.get("_pool"):  # expand 选样记 _pool; 分层构建器无此字段
        meta["pool"] = rec["_pool"]
    meta["n_extracted_files"] = n_ext
    return meta


def manifest_row_from_meta(
    meta: dict, cell_dir: Path | None = None, default_layer: str = "expand"
) -> dict | None:
    """meta dict（或 cell_dir/meta.json）→ manifest 行（幂等回补同口径）。

    lake 版差异：main_tex_sha256 由物化时直写 meta（旧版回补时重算——
    同一字段两处口径等价）。"""
    if meta is None and cell_dir is not None:
        try:
            meta = json.loads((Path(cell_dir) / "meta.json").read_text())
        except Exception:
            return None
    if not isinstance(meta, dict) or not meta:
        return None
    main_sha = meta.get("main_tex_sha256")
    if main_sha is None and cell_dir is not None:
        roots = (meta.get("features") or {}).get("tex_roots") or []
        if len(roots) == 1:
            mp = Path(cell_dir) / "extracted" / roots[0]
            if mp.exists():
                main_sha = hashlib.sha256(mp.read_bytes()).hexdigest()
    return {
        "id": meta.get("arxiv_id") or meta.get("idc"),
        "era": meta.get("era"),
        "archive": meta.get("archive"),
        "yymm": meta.get("yymm"),
        "cluster_id": meta.get("cluster_id"),
        "layer": meta.get("layer") or default_layer,
        "channel": meta.get("channel"),
        "item": meta.get("item"),
        "member": meta.get("member"),
        "blob_sha256": meta.get("raw_sha256"),
        "main_tex_sha256": main_sha,
        "stratum_cell": meta.get("stratum_cell"),
        "cat_group": meta.get("cat_group"),
        "license_class": meta.get("license_class"),
        "format": meta.get("format"),
        "n_files": meta.get("n_files") or meta.get("n_extracted_files"),
        "n_tex": meta.get("n_tex_files") or meta.get("tex_files"),
        "bytes": meta.get("bytes"),
        "pick_reason": meta.get("pick_reason"),
        "pool": meta.get("pool"),
    }


def materialize_entry_into_stage(
    entry_dir: Path,
    stage: Path,
    *,
    pid: str,
    fm: dict,
    mechs: str,
    layer: str = "expand",
) -> dict:
    """acquire_source CacheEntry dir → lake stage 树 + meta dict.

    fetch-ids 臂（channel=arxiv_eprint）专用：entry 已含 extracted/+raw.*+
    meta.json（产品 locate 结果），这里搬树 + frame_lookup 回填分层字段。
    """
    stage = Path(stage)
    entry_dir = Path(entry_dir)
    ext = stage / "extracted"
    if ext.exists():
        shutil.rmtree(ext)  # 半程截尾树会与 copytree 合并留幽灵文件
    shutil.copytree(entry_dir / "extracted", ext)
    raw_dir = stage / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw = None
    for r_ in entry_dir.glob("raw.*"):
        raw = raw_dir / r_.name
        shutil.copy2(r_, raw)
    meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
    yymm = fm.get("tar_yymm") or pid.split(".", 1)[0][:4]
    band = fm.get("year_band") or band_of_yymm(yymm)
    cat = fm.get("cat_group") or "unknown"
    cell = f"{band}|{cat}"
    era = "old" if "/" in pid else "new"
    locate_main = ((meta.get("locate") or {}).get("main")) or None
    roots = (meta.get("locate") or {}).get("independent_roots") or (
        [locate_main] if locate_main else []
    )
    main_sha = None
    if locate_main and (ext / locate_main).exists():
        main_sha = hashlib.sha256((ext / locate_main).read_bytes()).hexdigest()
    feats = extracted_features(ext)
    if not feats.get("tex_roots") and roots:
        feats["tex_roots"] = roots
    meta.update(
        {
            "era": era,
            "archive": pid.split("/", maxsplit=1)[0] if "/" in pid else None,
            "yymm": yymm,
            "cluster_id": f"EXP-{band}",
            "year_band": band,
            "layer": layer,
            "stratum_cell": cell,
            "cat_group": cat,
            "license_class": fm.get("license_class"),
            "channel": "arxiv_eprint",
            "item": None,
            "member": None,
            "features": feats,
            "main_tex_sha256": main_sha,
            "pick_reason": f"expand_orphan:{mechs}",
            "pool": "eprint",
            "source": "arxiv_eprint",
            "arxiv_id": pid,
        }
    )
    meta["bytes"] = raw.stat().st_size if raw else meta.get("raw_size")
    return meta
