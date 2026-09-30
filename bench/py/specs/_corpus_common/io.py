"""_corpus_common 基座叶——径位常量 / log / 文件 IO / canon / manifest / 通用纯函数。

import 期纯 stdlib+kernel+_benchlite——``texlate.*`` 惰性纪律见各消费叶。
拆自 ``specs._corpus_common``（facade 化 god-split）；名面经 facade 原样回引。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from kernel import fsutil, idnorm

from specs._benchlite import read_jsonl

REPO = Path(__file__).resolve().parents[4]
CORPUS = REPO / "bench" / "corpus"
FRAME = REPO / "bench" / "frame"
UA = {"User-Agent": "texlate-corpus-v3/1.0 (research benchmark build)"}
TIMEOUT = 60

IA_DL = "https://archive.org/download/{item}/{item}.tar"
IA_META = "https://archive.org/metadata/{item}"
TIGER_DL = (
    "https://huggingface.co/datasets/TIGER-Lab/arxiv-latex-5T/resolve/main/{name}.tar"
)

#: 持久 builder 状态根（work_v3 已灭后的新家；布局先例为已退役 errsweep 的 state 目录）。
BUILD_ROOT = Path.home() / ".local" / "state" / "texlate" / "corpus-build"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def atomic_write_text(path: Path, text: str) -> None:
    """kernel ``fsutil.atomic_write`` 的 text 形委托（fsync+dir fsync 全耐久
    口径；corpus_v3._atomic_write_text 同构）。父目录须先存在。"""
    fsutil.atomic_write(Path(path), text.encode("utf-8"))


def canon_id(pid: str) -> str:
    """论文 id 规范形：safe_id 的逆（混合双形归一）——委托 kernel
    ``idnorm.idc_from_safe`` 单源（末个 ``--`` 才是分隔符）。"""
    return idnorm.idc_from_safe(str(pid))


# ---------------------------------------------------------------- manifest
def manifest_paths(corpus: Path, layers) -> list[tuple[str, Path]]:
    """corpus 分层 manifest → [(layer, path)]；不存在的层跳过。"""
    out = []
    for layer in layers:
        fp = corpus / (
            "manifest.jsonl" if layer == "core" else f"manifest_{layer}.jsonl"
        )
        if fp.exists():
            out.append((layer, fp))
    return out


def load_manifest_rows(corpus: Path, layers) -> list[dict]:
    """分层 manifest → [{...,"layer": layer}]；行缺 layer 字段时补所在层。"""
    rows: list[dict] = []
    for layer, fp in manifest_paths(corpus, layers):
        for rec in read_jsonl(fp):
            rec.setdefault("layer", layer)
            rows.append(rec)
    return rows


def manifest_layers(corpus: Path) -> list[str]:
    """磁盘在册的全部层名：manifest.jsonl→core、manifest_X.jsonl→X。"""
    out = []
    for fp in sorted(corpus.glob("manifest*.jsonl")):
        if fp.name == "manifest.jsonl":
            out.append("core")
        elif fp.name.startswith("manifest_"):
            out.append(fp.stem.removeprefix("manifest_"))
    return out


def corpus_ids(corpus: Path) -> set[str]:
    """全层 id 并集（canon 归一）——去重/qc 单源。"""
    return {
        canon_id(r["id"])
        for r in load_manifest_rows(corpus, manifest_layers(corpus))
        if r.get("id")
    }


def existing_ids(corpus: Path) -> set[str]:
    return corpus_ids(corpus)


def largest_remainder(weights: dict[str, float], total: int) -> dict[str, int]:
    neg = {k: w for k, w in weights.items() if w < 0}
    if neg:
        msg = f"negative weights: {neg}"
        raise ValueError(msg)
    s = sum(weights.values())
    if weights and s == 0:
        msg = "all weights zero"
        raise ValueError(msg)
    raw = {k: total * w / s for k, w in weights.items()}
    q = {k: int(v) for k, v in raw.items()}
    for _, k in sorted(((raw[k] - int(raw[k]), k) for k in raw), reverse=True)[
        : total - sum(q.values())
    ]:
        q[k] += 1
    return q


def load_ids_file(path: Path) -> list[dict]:
    """ids 清单 → [{id, mechs, note}]；jsonl 行或纯文本 id（# 注释/空行跳过）。"""
    out = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            r = json.loads(line)
            out.append(
                {
                    "id": r["id"],
                    "mechs": r.get("mechs") or r.get("mech_tags") or [],
                    "note": r.get("note") or r.get("justification") or "",
                }
            )
        else:
            out.append({"id": line, "mechs": [], "note": ""})
    return out


def cell_meta(d: Path) -> dict:
    """cell 目录 meta.json → dict（缺档/坏 json → {}）。"""
    try:
        m = json.loads((Path(d) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def load_plan(path: Path) -> dict | None:
    """plan json → dict（缺档/坏 json → None——调用方 fail-closed）。"""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
