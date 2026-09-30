r"""corpus_v3 — corpus P2 主管线 spec：簇下载→成员扫描→配额抽样→湖化物化→自检.

`bench/py/corpus/build_corpus_v3.py`（1820 行）的 kernel 移植。docs/spec/corpus.md
S1–S5：30 月簇配额抽样——a–d 带走 IA arxiv-bulk 月 chunk，e 带走 HF
TIGER-Lab/arxiv-latex-5T。零 arxiv.org 请求、零网关（全免费批量通道）。

块选取规则（verbatim）：n_chunks<=2 → 全取；n>2 → 等距 2 块
{n//4+1, 3n//4+1}（避开首块边界与末块 partial）。

Stage 链（单件 ``{"id": "corpus-v3"}`` 串行——成员级断点在工作区文件态，
与旧子命令断点同构）：

  plan           allocation×item-index×tiger-files join → chunks.json；
                 IA metadata（sha1/md5/has_zipsum）同步落 chunks（旧 probe
                 子命令的 metadata 半页折叠在此——HEAD 可达性检查由 fetch
                 的失败路径天然吸收）。frame 资产缺席 → fail（ord-0
                 frame_bootstrap 先行）。
  fetch          .part + Range 断点下载 → verify_chunk（size + sha1/oid16）
                 → rename。retry 轮 ≤4；短收 → partial（chunks.json 持态，
                 下个 run 续）。
  zipsum         IA zipsum.tsv（成员 sha256 交叉核验源；404 钉死永久缺失，
                 5xx 留下轮）。
  scan           流扫 chunk tar → members/features jsonl + tex staging .gz。
  frame_lookup   frame.parquet → frame_lookup.tsv.gz（仅此 stage 需
                 pyarrow——不可导入则 fail 而非 skip：缺 frame 的抽样是错口径）。
  sample         eligible∧frame-join → cell 内随机配额（SEED=42）→
                 sample_core.json + booster_pool.json（B01–B07 预筛）。
  extract        中选成员 → lake cell（hydrate(idc, fetch_fn, source="arxiv")：
                 fetch_fn 从 staging tar/幸存 raw 复读 blob → sha256 复验 →
                 {cell}/raw/{raw_name} + {cell}/extracted/）；
                 manifest.jsonl + MANIFEST.md → bench/corpus/（tracked）。
                 manifest 每轮从 lake cell meta 全量重建——hydrate 后崩
                 不丢行（denominator：manifest 行 ≡ v3 core meta cells）。
  extract_booster booster_selection.jsonl（booster-select 动词产物）中选
                 成员同款物化 → manifest_booster.jsonl；文件缺席 → skip
                 retriable（动词未跑是常态）。
  qc             配额/去重/lake 对账/manifests_tracked → clean|fail。

移植变更（相对旧驱动）：
- 工作区 bench/work_v3/（已灭）→ ``~/.local/state/texlate/corpus-build/v3/``
  持久 builder 目录（多日断点语义；ctx.workspace 跨 run 清，不可用）。
- payload bench/corpus/{id}/ → lake cells（source="arxiv"）；cell meta 带
  旧 meta.json 全字段（n_files 由 hydrate 按 payload 实数、"source" 键
  让位 lake 保留字段——渠道走 "channel" 键；另补 main_tex_sha256 入 cell
  meta 供 manifest 重建投影）。
- 成员 sha 不符 → 成员级 fault（cell errors cat=corrupt）不毁 stage；
  异国 complete cell（无 layer 标记）在 lake_lock 下原地并入 v3 meta
  （旧驱动无条件覆写 meta.json 的同义动作）；layer 冲突 → orphan_adopt。
- 特征提取块（TEXT_EXT..eval_signatures/blob_features/_texts_features/
  unpack_blob）与通用件（log/open_url/safe_name/REPO..TIGER_DL/SEED/
  frame_lookup 装载/cell_meta/canon 归一/RAW_NAME/atomic_write）全部走
  ``specs._corpus_common``（cc）单源——本文件此前是逐字节副本，dedup
  后 v3 专属注记已回填 cc 注释面。

拆分（facade 化 god-split）：实现体按 stage 段拆进同包私有叶——
``_corpus_v3_base``（WORK 常量/chunks.json 读写/allocation 装载）、
``_corpus_v3_fetch``（plan/fetch/zipsum 下载段）、
``_corpus_v3_scan``（scan/frame_lookup 扫描段）、
``_corpus_v3_sample``（配额抽样）、
``_corpus_v3_extract``（lake 物化/manifest 重建/booster 段）、
``_corpus_v3_qc``（自检段）。本文件是 PEP 562 惰性门面（同
``kernel.importer``/``fixloop.builtins`` 形制）——平名经
``_LEAF_EXPORTS`` 映射回叶子，``corpus_v3.X`` 与 ``from ... import X``
面不变；stage 函数 import 期实载（``spec`` 组合根即位）。叶间直引
``from specs._corpus_v3_X import Y`` 不绕本门面（避环）。
monkeypatch 锚点注意：``TARS`` 等常量住叶子模块——setattr patch 须指到
叶子（``specs._corpus_v3_extract.TARS`` 等），门面 setattr 只遮蔽门面
不改叶子（同 builtins 门面先例）。
"""

from __future__ import annotations

# ---------------------------------------------------------------- import 期名面
# HEAD 同款的全部 import——逐名搬入保持 ``corpus_v3.X`` 名面零漂移。
import csv
import gzip
import hashlib
import importlib
import json
import os
import random
import re
import sys
import tarfile
import time
import urllib.error
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from kernel import fsutil, idnorm, lake, paths
from kernel.events import iter_jsonl
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs._corpus_v3_extract import _stage_extract, _stage_extract_booster
from specs._corpus_v3_fetch import _fetch, _plan, _zipsum
from specs._corpus_v3_qc import _qc
from specs._corpus_v3_sample import _sample
from specs._corpus_v3_scan import _frame_lookup, _scan

if TYPE_CHECKING:
    from specs._corpus_v3_base import (
        BAND_OF_CLUSTER,
        CHUNKS_JSON,
        FRAME_LOOKUP_GZ,
        IA_ZIPSUM,
        LAKE_SOURCE,
        TARS,
        WORK,
        _read_jsonl,
        load_allocation,
        load_chunks,
        save_chunks,
    )
    from specs._corpus_v3_extract import (
        _adopt_cell,
        _cell_state,
        _extract_members,
        _make_fetch,
        _member_meta,
        _MemberFault,
        _prune_tar,
        _rebuild_manifest,
        _write_manifest_md,
    )
    from specs._corpus_v3_fetch import (
        _FRAME_INPUTS,
        fetch_one,
        pick_chunk_ids,
        stream_download,
        verify_chunk,
    )
    from specs._corpus_v3_scan import _scan_chunk

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_corpus_v3_base": (
        "BAND_OF_CLUSTER",
        "CHUNKS_JSON",
        "FRAME_LOOKUP_GZ",
        "IA_ZIPSUM",
        "LAKE_SOURCE",
        "TARS",
        "WORK",
        "_read_jsonl",
        "load_allocation",
        "load_chunks",
        "save_chunks",
    ),
    "_corpus_v3_fetch": (
        "_FRAME_INPUTS",
        "_fetch",
        "_plan",
        "_zipsum",
        "fetch_one",
        "pick_chunk_ids",
        "stream_download",
        "verify_chunk",
    ),
    "_corpus_v3_scan": (
        "_frame_lookup",
        "_scan",
        "_scan_chunk",
    ),
    "_corpus_v3_sample": ("_sample",),
    "_corpus_v3_extract": (
        "_MemberFault",
        "_adopt_cell",
        "_cell_state",
        "_extract_members",
        "_make_fetch",
        "_member_meta",
        "_prune_tar",
        "_rebuild_manifest",
        "_stage_extract",
        "_stage_extract_booster",
        "_write_manifest_md",
    ),
    "_corpus_v3_qc": ("_qc",),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__；键集 = _LAZY 键集 +
# import 期名面（HEAD 全量 import 的平名）。新增导出两侧同步
# （``_export_drift`` 是三表同步闸）。
__all__ = [
    # base 叶
    "BAND_OF_CLUSTER",
    "CHUNKS_JSON",
    "FRAME_LOOKUP_GZ",
    "IA_ZIPSUM",
    "LAKE_SOURCE",
    "TARS",
    "WORK",
    # fetch 叶
    "_FRAME_INPUTS",
    # spec 组合根（本地实名）
    "_STATUS",
    # HEAD import 期平名（stdlib/kernel 模块与类型名——``corpus_v3.X`` 可解析保旧形）
    "Counter",
    "Param",
    "Path",
    "Spec",
    "Stage",
    # extract 叶
    "_MemberFault",
    "_adopt_cell",
    "_bootstrap",
    "_cell_state",
    "_extract_members",
    "_fetch",
    # scan 叶
    "_frame_lookup",
    "_make_fetch",
    "_member_meta",
    "_plan",
    "_prune_tar",
    # qc 叶
    "_qc",
    "_read_jsonl",
    "_rebuild_manifest",
    # sample 叶
    "_sample",
    "_scan",
    "_scan_chunk",
    "_stage_extract",
    "_stage_extract_booster",
    "_write_manifest_md",
    "_zipsum",
    "cc",
    "csv",
    "fetch_one",
    "fsutil",
    "gzip",
    "hashlib",
    "idnorm",
    "iter_jsonl",
    "json",
    "lake",
    "load_allocation",
    "load_chunks",
    "os",
    "paths",
    "pick_chunk_ids",
    "random",
    "re",
    "save_chunks",
    "spec",
    "stream_download",
    "tarfile",
    "time",
    "urllib",
    "verify_chunk",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。

    叶名写死 ``specs.`` 前缀——spec 文件经 ``load_spec`` exec 装载时
    ``__package__`` 为空串，``f"{__package__}.{leaf}"`` 拼出 ``.leaf``
    触发 TypeError（相对导入缺包名）。
    """
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"specs.{leaf}"), name)
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


# ---------------- spec ----------------

_STATUS = {
    "ok": "terminal",
    "clean": "terminal",
    "partial": "terminal",
    "fail": "terminal",
    "skip": "retriable",
    "error": "retriable",
}

spec = Spec(
    kind="corpus_v3",
    # eval=True 是单件非论文 id 的 canon 豁免口（非 eval item 全过
    # canon_id，"corpus-v3" 不是 arXiv 形会被丢；
    # 副作用仅 cell 事件 eval=True 标记，无 stage.eval 行）。
    eval=True,
    items=[{"id": "corpus-v3"}],
    params={
        "channel": Param(type=str, default=None, choices=["ia", "tiger"], fp=False),
        "jobs": Param(type=int, default=4),
        "limit": Param(type=int, default=None, fp=False),
    },
    stages=[
        Stage("plan", _plan, status_class=dict(_STATUS)),
        Stage("fetch", _fetch, needs=[("plan", {"ok"})], status_class=dict(_STATUS)),
        Stage("zipsum", _zipsum, needs=[("fetch", {"ok"})], status_class=dict(_STATUS)),
        Stage("scan", _scan, needs=[("fetch", {"ok"})], status_class=dict(_STATUS)),
        Stage(
            "frame_lookup",
            _frame_lookup,
            needs=[("scan", {"ok"})],
            status_class=dict(_STATUS),
        ),
        Stage(
            "sample",
            _sample,
            needs=[("frame_lookup", {"ok"})],
            status_class=dict(_STATUS),
        ),
        Stage(
            "extract",
            _stage_extract,
            needs=[("sample", {"ok"})],
            status_class=dict(_STATUS),
        ),
        Stage(
            "extract_booster",
            _stage_extract_booster,
            needs=[("sample", {"ok"})],
            status_class=dict(_STATUS),
        ),
        Stage("qc", _qc, needs=[("extract", {"ok"})], status_class=dict(_STATUS)),
    ],
    code_deps=[
        "bench/py/specs/_corpus_common.py",
        "bench/py/specs/_corpus_common_features.py",
        "bench/py/specs/_corpus_common_frame.py",
        "bench/py/specs/_corpus_common_io.py",
        "bench/py/specs/_corpus_common_materialize.py",
        "bench/py/specs/_corpus_common_net.py",
        "bench/py/specs/_corpus_common_scan.py",
        "bench/py/specs/_corpus_common_select.py",
        "bench/py/specs/_corpus_v3_base.py",
        "bench/py/specs/_corpus_v3_extract.py",
        "bench/py/specs/_corpus_v3_fetch.py",
        "bench/py/specs/_corpus_v3_qc.py",
        "bench/py/specs/_corpus_v3_sample.py",
        "bench/py/specs/_corpus_v3_scan.py",
        "src/texlate/arxiv",
    ],
)
