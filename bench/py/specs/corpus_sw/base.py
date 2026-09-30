"""corpus_sw 基座叶——常量区 + FILE: 拆包/词表小工具（父子进程共享侧）。"""

from __future__ import annotations

import os
import re
from pathlib import Path

from kernel import paths

from specs import _bootstrap
from specs._benchlite import iter_jsonl, strip_comments

_bootstrap.ensure()

from specs import _corpus_common as cc

ROOT = Path(__file__).resolve().parents[4]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))
MANIFEST_OUT = CORPUS / "manifest_dev_recent.jsonl"

SHARDS = 47
DATASET = "scholarweave/arxiv-latex"
SHARD_URL = (
    "https://huggingface.co/datasets/"
    + DATASET
    + "/resolve/main/arxiv_part_{:04d}.parquet"
)
CHANNEL = "hf_scholarweave"
LAYER = "dev_recent"
PICK_REASON = "dev_recent_sw"
RG_ATTEMPTS = 3

# cat_group 词表对齐 frame（primary_cat 前缀 → 8 组；2501+ 只见现代类目）
_CAT_GROUP = {
    "eess": "eess-stat-etc",
    "stat": "eess-stat-etc",
    "nucl-ex": "nucl",
    "nucl-th": "nucl",
    "quant-ph": "quant-ph",
}
_HEP_PHYS = {"hep-ph", "hep-th", "hep-ex", "hep-lat", "gr-qc", "physics"}
_GROUPS = {"cs", "math", "cond-mat", "astro-ph"}

FILE_MARK = re.compile(r"^={10,}\r?\nFILE: (.+?)\r?\n={10,}\r?\n", re.MULTILINE)

# ---------------------------------------------------------------- 小工具


def _sw() -> Path:
    """durable builder zone——跨 run 存活的 footers/pool_parts/assign_*。"""
    return paths.lake_durable_dir() / "sw"


def _iter_jsonl(path: Path):
    """OSError 容忍（缺席/截尾）+ 坏行跳过——benchlib.iter_jsonl 薄转。"""
    try:
        yield from iter_jsonl(path)
    except OSError:
        return


def yymm_recent(yymm_id: str | None, min_yymm: str) -> bool:
    """yymm_id 前 4 位 ∈ [min_yymm, 2699]——裸词表比较会把 "9xxx" 旧年代和
    非数字前缀放进来。"""
    s = (yymm_id or "")[:4]
    return s.isdigit() and int(min_yymm) <= int(s) <= 2699


def cat_group_of(categories: str) -> str:
    """sw categories 首类 → frame cat_group 词表。"""
    pc = (categories or "").split()[0] if categories else ""
    if pc in _CAT_GROUP:
        return _CAT_GROUP[pc]
    base = pc.split(".", 1)[0]
    if base in _HEP_PHYS:
        return "hep-phys"
    if base in _GROUPS:
        return base
    return "other"


def shard_name(n: int) -> str:
    return f"arxiv_part_{n:04d}.parquet"


def split_files(latex: str) -> dict[str, str]:
    """==== FILE: 标记拆包 → {relpath: text}（首个标记前内容丢弃）。"""
    out: dict[str, str] = {}
    marks = list(FILE_MARK.finditer(latex))
    for idx, m in enumerate(marks):
        name = m.group(1).strip()
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(latex)
        body = latex[m.end() : end]
        # 路径消毒：禁绝对路径/../；重名追加序号
        parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            name = f"file_{idx}"
        else:
            name = "/".join(parts)
        base, n = name, 2
        while name in out:
            stem, dot, suf = base.rpartition(".")
            name = f"{stem}_{n}{dot}{suf}" if dot else f"{base}_{n}"
            n += 1
        out[name] = body
    return out


def _reduced_features(files: dict[str, str]) -> dict:
    """减配形态特征：docclasses/docstyle*/tex_roots/non_utf8。

    tex_roots 与 build_corpus_v3._texts_features 同口径（剥注释后含
    \\documentclass/\\documentstyle 的 .tex relpath）——main_tex_sha256
    的唯一消费点。input_depth/flags*/signatures 未移植（见模块 doc）。
    """
    tex_texts = {p: t for p, t in files.items() if Path(p).suffix.lower() == ".tex"}
    blob_txt = strip_comments("\n".join(tex_texts.values()))
    dcls_ms = list(cc.DOCCLASS_RX.finditer(blob_txt))
    roots = sorted(
        p for p, t in tex_texts.items() if cc.DOCCLASS_RX.search(strip_comments(t))
    )
    return {
        "docclasses": sorted({m.group(3).strip() for m in dcls_ms}),
        "docstyle": any(m.group(1) == "documentstyle" for m in dcls_ms),
        "docstyle_opts": sorted(
            o.strip()
            for m in dcls_ms
            if m.group(1) == "documentstyle" and m.group(2)
            for o in m.group(2).split(",")
            if o.strip()
        ),
        "docclass_opts": sorted(
            o.strip()
            for m in dcls_ms
            if m.group(1) == "documentclass" and m.group(2)
            for o in m.group(2).split(",")
            if o.strip()
        ),
        "tex_roots": roots,
        # parquet latex 列已是合法 str——旧口径（重读 extracted 树 decode
        # 探测）在本通道恒 False，字段保留只为 schema 对齐。
        "non_utf8": False,
    }
