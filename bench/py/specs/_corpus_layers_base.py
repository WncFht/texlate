"""specs._corpus_layers_base — corpus_layers 层剖面常量 + 路径解析小件叶。

PROFILES/LAYER_NAMES/EPRINT_LAYERS/FLAG_QUOTAS 等层定义词表与
``_dirs``（run 参数 → 层目录布局解析）——各 stage 叶共享的地基层。
"""

from __future__ import annotations

import time
from pathlib import Path

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc

# 层剖面：quota=flat（core 配比直扩）/ fbias（失败率偏置，expand 配方）/
# flags（矿层签名旗标定向）。scale 仅文档义——largest_remainder 按 target
# 归一，不读 scale（旧构建器同）。
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
#: eprint recent 臂服务的层（sw assign 只对这两层切 id）。
EPRINT_LAYERS = {"holdout", "dev_recent"}

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
_FLAG_BAND_FRAC = {"a": 0.45, "b": 0.35, "c": 0.2}
#: 矿层回填带——old-era = a/b/c 三带（deadpkg/2.09 原语密度区）。
_FAILMINE_FILL_CAP = "c_2012_16"


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _layer(ctx) -> str:
    return str(ctx.params.get("layer") or "")


def _dirs(ctx) -> dict:
    p = ctx.params
    layer = _layer(ctx)
    wd_root = Path(str(p.get("workdir") or "")).expanduser()
    lwd = wd_root / layer
    corpus = Path(str(p.get("corpus_dir") or "")).expanduser()
    return {
        "layer": layer,
        "lwd": lwd,
        "dirs": cc.TarDirs.from_workdir(lwd),
        "plan": wd_root / f"{layer}_plan.json",
        "records": lwd / "extract_records.jsonl",
        "select_stats": lwd / "select_stats.json",
        "qc_md": lwd / "qc.md",
        "recent_fail": lwd / "recent_fail.jsonl",
        "corpus": corpus,
        "manifest": corpus / f"manifest_{layer}.jsonl",
        "frame": Path(str(p.get("frame_dir") or "")).expanduser(),
        "v3": Path(str(p.get("v3_workdir") or "")).expanduser(),
        "build_root": Path(str(p.get("build_root") or cc.BUILD_ROOT)).expanduser(),
    }
