"""corpus_sw — scholarweave/arxiv-latex (HF) 通道适配器 + dev_recent 层 builder。

``bench/py/corpus/build_sw_layer.py`` 的 spec 化移植：scholarweave 是唯一免费
的 2025+ 批量 LaTeX 源（47 个 parquet 分片、~9.6GB/片、按月续更），行组
yymm_id 有序——footer 统计圈出近期行组，列投影 range-GET 免整片下载。

单 item（``corpus-sw``）串行五段链，每段对应旧子命令：

- ``footers``   分片 footer → durable/sw/footers/{n}.json + footers.json
- ``pool``      近期行组 [id,yymm_id,categories,license] 列投影 → pool.jsonl
- ``assign``    三层分流：sw 臂 ~1 行组/月组内采样；eprint 臂按月均匀切
                holdout/dev_recent id 清单 → assign_*.jsonl（durable，
                layers spec 经 metrics 里的路径做 ids_file 输入）
- ``rehydrate`` 行组级 latex 列 → FILE: 拆包 → lake.hydrate 逐 id 落格 +
                manifest_dev_recent.jsonl 追加（repo-tracked 选择层）
- ``report``    manifest 聚合 → metrics

湖格契约（不变式，下游编译 spec 的消费谓词）：channel=hf_scholarweave,
item=分片名，member=id, raw/raw.tar.gz=重打包文本树, meta
figures_stripped:true（无二进制图——编译臂走 \\includegraphics stub 而非
missing_file 膨胀）+ catalog row regen_cost=network（raw 是重打包树，
驱逐永不先逐它）。

HF 纪律：pyarrow/fsspec 不在项目 venv——所有 HF 触网动作走 env 白名单
{PATH,HOME} 的 ``uv run --with pyarrow --with "fsspec[http]" python
<本文件> --worker`` 子进程（代理 env 泄漏 → SSL EOF 前科，本机+archbox
双实证）。worker 子命令见 ``_worker_cli``；父进程从不 import 这两个包。

断点/续跑：footers/pool_parts/assign_* 全在 ``lake/durable/sw/``（跨 run
存活——ctx.workspace() 是 run 级 scratch）；rehydrate done 集 =
manifest_dev_recent ids ∪ 其他 manifest ids ∪ 已 complete 湖格，逐 rg
成功才推进；hydrate 到 manifest 追加之间的崩溃窗由「complete 但未上榜 →
从 meta.json 重建行」自愈。

蓄意 delta（相对 build_sw_layer.py）：
- meta.features 减配为 {docclasses, docstyle, docstyle_opts, docclass_opts,
  tex_roots, non_utf8}——tex_roots 口径逐字节同源（同 cc.DOCCLASS_RX + 同
  strip_comments），保 main_tex_sha256 语义；input_depth/flags_*/
  signatures 的机器（FLAG_RX/eval_signatures/input_depth 依赖网）未移植，
  无任何下游读 features。
- taken 集 = manifest*.jsonl ids ∪ 湖格 complete 判定（双侧 canon 归一——
  mixed-id-forms 前科）；旧 corpus_ids 只读 manifest。
- raw 落 ``{cell}/raw/raw.tar.gz``（新湖规范——_populate_from_raw 单 tar
  直解），旧式 cell 根 raw.tar.gz 归 importer 管。
- footers.json 始终是「已缓存分片的最大编目」；--shards 收窄只作用于
  抓取与 pool/rehydrate 行组过滤，不把编目写窄。

拆分（facade 化 god-split）：实现体按 stage 段拆进同包私有叶——
``corpus_sw.base``（常量区 + FILE: 拆包/词表小工具）、
``corpus_sw.worker``（_hf_* 派发管道 + --worker 体——``_hf_argv`` 以
``__file__`` 自指，worker 子进程跑的是该叶本体）、
``corpus_sw.manifest``（canon id 集/行装配）、``corpus_sw.plan``
（footers/pool/assign 段）、``corpus_sw.rehydrate``（rgrows 落格 +
manifest 追加 + report 段）、``corpus_sw._spec``（spec 组合根——叶干
``_`` 前缀脱导出名 ``spec`` 碰撞）。本
文件是 PEP 562 惰性门面（同 ``specs/corpus_v3/__init__.py`` 形制）——平名经
``_LEAF_EXPORTS`` 映射回叶子，``corpus_sw.X`` 与 ``from  import X``
面不变；``spec`` 住 ``corpus_sw._spec`` 叶。叶间直引
``from specs._corpus_sw_X import Y`` 不绕本门面（避环）。
``python specs/corpus_sw --worker ...``（dir→``__main__.py``）旧调用
形保持——入口已搬同包 ``__main__.py``。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import time
from collections import Counter, defaultdict
from pathlib import Path

# worker 裸跑 ``python specs/x.py --worker`` 时 bench/py 不在
# sys.path——先立起才够得着 specs.*（load_spec 径下幂等）。
_BENCH_PY = str(Path(__file__).resolve().parents[2])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)

from kernel import lake, paths
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap
from specs._benchlite import iter_jsonl, strip_comments

_bootstrap.ensure()

import importlib
from typing import TYPE_CHECKING

from specs import _corpus_common as cc

if TYPE_CHECKING:
    from specs.corpus_sw._spec import spec
    from specs.corpus_sw.base import (
        _CAT_GROUP,
        _GROUPS,
        _HEP_PHYS,
        CHANNEL,
        CORPUS,
        DATASET,
        FILE_MARK,
        LAYER,
        MANIFEST_OUT,
        PICK_REASON,
        RG_ATTEMPTS,
        ROOT,
        SHARD_URL,
        SHARDS,
        _iter_jsonl,
        _reduced_features,
        _sw,
        cat_group_of,
        shard_name,
        split_files,
        yymm_recent,
    )
    from specs.corpus_sw.manifest import (
        _all_manifest_ids,
        _manifest_ids,
        _manifest_row,
    )
    from specs.corpus_sw.plan import (
        _assign,
        _footers,
        _pool,
        _recent_rgs,
        _shard_set,
    )
    from specs.corpus_sw.rehydrate import (
        _fetch_for,
        _meta_extra,
        _rehydrate,
        _report,
    )
    from specs.corpus_sw.worker import (
        _hf_argv,
        _hf_env,
        _hf_run,
        _w_footer,
        _w_pool,
        _w_rgrows,
        _worker_cli,
    )


_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "base": (
        "CHANNEL",
        "CORPUS",
        "DATASET",
        "FILE_MARK",
        "LAYER",
        "MANIFEST_OUT",
        "PICK_REASON",
        "RG_ATTEMPTS",
        "ROOT",
        "SHARDS",
        "SHARD_URL",
        "_CAT_GROUP",
        "_GROUPS",
        "_HEP_PHYS",
        "_iter_jsonl",
        "_reduced_features",
        "_sw",
        "cat_group_of",
        "shard_name",
        "split_files",
        "yymm_recent",
    ),
    "worker": (
        "_hf_argv",
        "_hf_env",
        "_hf_run",
        "_w_footer",
        "_w_pool",
        "_w_rgrows",
        "_worker_cli",
    ),
    "manifest": (
        "_all_manifest_ids",
        "_manifest_ids",
        "_manifest_row",
    ),
    "plan": (
        "_assign",
        "_footers",
        "_pool",
        "_recent_rgs",
        "_shard_set",
    ),
    "rehydrate": (
        "_fetch_for",
        "_meta_extra",
        "_rehydrate",
        "_report",
    ),
    "_spec": ("spec",),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

_PKG = "specs.corpus_sw"  # load_spec exec 径下 __package__ 是 ""

# 字面列表——ruff F401 re-export 判定要静态 __all__；键集 = _LAZY 键集 +
# import 期名面（HEAD 全量 import 的平名）。新增导出两侧同步
# （``_export_drift`` 是三表同步闸）。
__all__ = [
    "CHANNEL",
    "CORPUS",
    "DATASET",
    "FILE_MARK",
    "LAYER",
    "MANIFEST_OUT",
    "PICK_REASON",
    "RG_ATTEMPTS",
    "ROOT",
    "SHARDS",
    "SHARD_URL",
    "_BENCH_PY",
    "_CAT_GROUP",
    "_GROUPS",
    "_HEP_PHYS",
    "Counter",
    "Param",
    "Path",
    "Spec",
    "Stage",
    "_all_manifest_ids",
    "_assign",
    "_bootstrap",
    "_fetch_for",
    "_footers",
    "_hf_argv",
    "_hf_env",
    "_hf_run",
    "_iter_jsonl",
    "_manifest_ids",
    "_manifest_row",
    "_meta_extra",
    "_pool",
    "_recent_rgs",
    "_reduced_features",
    "_rehydrate",
    "_report",
    "_shard_set",
    "_sw",
    "_w_footer",
    "_w_pool",
    "_w_rgrows",
    "_worker_cli",
    "cat_group_of",
    "cc",
    "contextlib",
    "defaultdict",
    "hashlib",
    "io",
    "iter_jsonl",
    "json",
    "lake",
    "os",
    "paths",
    "random",
    "re",
    "shard_name",
    "shutil",
    "spec",
    "split_files",
    "strip_comments",
    "subprocess",
    "sys",
    "tarfile",
    "time",
    "yymm_recent",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{_PKG}.{leaf}"), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖：

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝，是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
