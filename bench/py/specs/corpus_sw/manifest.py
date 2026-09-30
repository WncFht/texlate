"""corpus_sw manifest 账叶——canon id 集/taken 并集/行装配（重建路径同式）。"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from specs import _corpus_common as cc
from specs.corpus_sw.base import (
    CHANNEL,
    CORPUS,
    LAYER,
    PICK_REASON,
    _iter_jsonl,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------- corpus 账


def _manifest_ids(path: Path) -> set[str]:
    """一 manifest 文件的 canon id 集。"""
    return {cc.canon_or_self(r["id"]) for r in _iter_jsonl(path) if r.get("id")}


def _all_manifest_ids() -> set[str]:
    """bench/corpus/manifest*.jsonl 全行 canon id 并集（taken 一翼）。"""
    out: set[str] = set()
    for mp in sorted(CORPUS.glob("manifest*.jsonl")):
        out |= _manifest_ids(mp)
    return out


def _manifest_row(meta: dict, pid: str, ext: Path | None) -> dict:
    """cell meta (+extracted 树可选) → manifest_dev_recent 行。

    ext=None 时 main_tex_sha256 从 meta.features.tex_roots 单根判定；
    重建路径（湖格在、行不在）与正常路径同一份字段装配。
    """
    roots = (meta.get("features") or {}).get("tex_roots") or []
    main_sha = None
    if ext is not None and len(roots) == 1 and (ext / roots[0]).exists():
        main_sha = hashlib.sha256((ext / roots[0]).read_bytes()).hexdigest()
    return {
        "id": pid,
        "era": meta.get("era"),
        "archive": None,
        "yymm": meta.get("yymm"),
        "cluster_id": meta.get("cluster_id"),
        "layer": LAYER,
        "channel": CHANNEL,
        "item": meta.get("item"),
        "member": pid,
        "blob_sha256": meta.get("raw_sha256"),
        "main_tex_sha256": main_sha,
        "stratum_cell": meta.get("stratum_cell"),
        "cat_group": meta.get("cat_group"),
        "license_class": None,
        "format": "tar",
        "n_files": meta.get("n_files"),
        "n_tex": meta.get("tex_files"),
        "bytes": meta.get("bytes"),
        "pick_reason": PICK_REASON,
        "figures_stripped": True,
    }
