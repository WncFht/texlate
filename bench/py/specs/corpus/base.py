"""corpus 基座叶——持久工作区常量 / chunks.json 读写 / allocation 装载。

``BAND_OF_CLUSTER`` 由 ``load_allocation`` 原地填充——消费叶按名绑定同一
dict 对象（in-place 突变语义 verbatim）。
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from kernel.events import iter_jsonl

from specs import _bootstrap
from specs import _corpus_common as cc

_bootstrap.ensure()

#: 持久 builder 工作区（旧 bench/work 新家——多日断点状态全在这棵树下）。
WORK = (
    Path(os.environ.get("TEXLATE_CORPUS_WORK", ""))
    if os.environ.get("TEXLATE_CORPUS_WORK")
    else Path.home() / ".local" / "state" / "texlate" / "corpus-build" / "main"
)
TARS = WORK / "tars"
CHUNKS_JSON = WORK / "chunks.json"
#: frame_lookup stage 产物落点（本 builder 私有——corpus-build 根的共享件是
#: cc.ensure_frame_lookup 的另一契约，勿混用）。
FRAME_LOOKUP_GZ = WORK / "frame_lookup.tsv.gz"

IA_ZIPSUM = "https://archive.org/download/{item}/{item}_zipsum.tsv"

#: lake cell 落点维度——全部下游 spec 的 lake_source 共识。
LAKE_SOURCE = "arxiv"

BAND_OF_CLUSTER = {}  # cluster_id -> year_band, filled by load_allocation()

# ---------------- 通用 ----------------


def _read_jsonl(path: Path) -> list[dict]:
    return [row for _ln, row, _raw in iter_jsonl(Path(path)) if isinstance(row, dict)]


def load_allocation() -> list[dict]:
    with (cc.FRAME / "allocation-core.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["quota_core"] = int(r["quota_core"])
        r["n_chunks"] = int(r["n_chunks"])
        BAND_OF_CLUSTER[r["cluster_id"]] = r["year_band"]
    return rows


def load_chunks() -> list[dict]:
    return json.loads(CHUNKS_JSON.read_text())


def save_chunks(chunks: list[dict]) -> None:
    cc.atomic_write_text(CHUNKS_JSON, json.dumps(chunks, indent=1) + "\n")
