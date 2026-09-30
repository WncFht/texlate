"""_corpus_common — corpus builder 共享叶（expand/layers/hot/v3 各臂共用）。

逐字提升自 ``bench/py/corpus/build_corpus_v3.py`` +
``build_corpus_expand.py`` + ``benchlib.py`` 三处（皆已随删除门退役）。
import 期纯 stdlib——``texlate.arxiv``/``pyarrow`` 一律惰性 import 在使用点
内（scan 链路系统 python3 可载，extract/fetch-ids 臂经 ``uv run`` 进产品环境）。

工作区契约（post-work_v3）：持久 builder 状态落
``~/.local/state/texlate/corpus-build/<layer>/`` —— TarDirs 标准布局
{features,members,tars,meta} 每层一束（先例为已退役 errsweep 的 state 目录布局）。
``frame_lookup.tsv.gz`` 全 builder 共享单件：
``corpus-build/frame_lookup.tsv.gz``，``ensure_frame_lookup`` 缺时从
``bench/frame/frame.parquet`` 现算（谁先跑谁建，幂等）。

公开面（layers spec 消费边界）::

    TarDirs / TarDirs.from_workdir
    log open_url item_url band_of_yymm member_yymm
    download_item scan_item scan_batch offsets_for fetch_blob
    remote_size                      # meta API 缓存内含
    member_id blob_features extracted_features eligible safe_name unpack_blob
    frame_lookup_path ensure_frame_lookup load_frame_lookup frame_filter
    frame_meta_for frame_get yymm2cluster band_cat_share load_chunks
    iter_jsonl read_jsonl write_jsonl append_jsonl atomic_write_text
    strip_comments canon_id canon_or_self cell_meta
    manifest_paths load_manifest_rows manifest_layers corpus_ids
    largest_remainder load_ids_file
    materialize_into_stage materialize_entry_into_stage manifest_row_from_meta
    RAW_NAME IA_DL IA_META TIGER_DL
    SEED RUN_REF_RX FRAME_NEEDS HaltFetch TransientMiss
    load_plan bad_rates rates_from_idstatus run_id_statuses resolve_rates
    order_items candidate_items member_fetch_fn extract_selected

拆分（facade 化 god-split）：实现体按子域拆进同包私有叶——
``_corpus_common_io``（径位常量/log/IO/canon/manifest/纯函数）、
``_corpus_common_net``（网络下载/meta 尺寸缓存/续传/内容校验）、
``_corpus_common_scan``（TarDirs 布局/月带/成员扫描批/offset 簿/blob 回取）、
``_corpus_common_frame``（frame_lookup 单件/allocation·cat-mix/chunks.json）、
``_corpus_common_features``（成员名解析/签名正则面/blob_features/unpack）、
``_corpus_common_materialize``（lake stage 物化/meta/manifest 行）、
``_corpus_common_select``（rates 解析/round-robin/候选枚举/选单物化）。
本文件是 PEP 562 惰性门面（同 ``kernel.importer``/``fixloop.builtins``
形制）——平名经 ``_LEAF_EXPORTS`` 映射回叶子，``__getattr__`` 首访解析
并缓存，``cc.X`` 公共面与 ``from ... import X`` 形不变。叶间直引
``from specs._corpus_common_X import Y`` 不绕本门面（避环）。
"""

from __future__ import annotations

# ---------------------------------------------------------------- import 期名面
# HEAD 同款的全部 import——逐名搬入保持 ``cc.X`` 对消费方与旧调用形零漂移
# （stdlib/kernel 模块名也含在名面内：``cc.Path``/``cc.lake`` 等可解析）。
import csv
import gzip
import hashlib
import importlib
import io
import json
import os
import random
import re
import shutil
import sys
import tarfile
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from kernel import fsutil, idnorm, lake, paths
from kernel import index as indexmod

# jsonl 三件 + strip_comments 正本在 _benchlite（benchlib 收编叶）——本叶
# re-export 保旧调用形，勿再长第三份 verbatim。
from specs._benchlite import (
    append_jsonl,
    iter_jsonl,
    read_jsonl,
    strip_comments,
)

if TYPE_CHECKING:
    from specs._corpus_common_features import (
        AUTOIGNORE,
        CENTERLINE_RX,
        DEAD_PKGS,
        DEADPKG_ALT,
        DEADPKG_RX,
        DOCCLASS_RX,
        DSL_PKGS,
        EDITOR_LEFT_RX,
        FLAG_RX,
        INPUT_RX,
        JOURNAL_OPTS,
        JOURNAL_STY_PKGS,
        KERNEL_OPTS,
        MANUAL_BF_RX,
        ORG_LABEL_RX,
        PLAIN_OUT_RX,
        SECTION_RX,
        TEXT_EXT,
        USEP_RX,
        XREF_RX,
        _dist1,
        _texts_features,
        blob_features,
        eligible,
        eval_signatures,
        extracted_features,
        input_depth,
        looks_like_tar,
        member_id,
        norm_target,
        safe_name,
        unpack_blob,
    )
    from specs._corpus_common_frame import (
        band_cat_share,
        cluster2band,
        ensure_frame_lookup,
        frame_filter,
        frame_get,
        frame_lookup_path,
        frame_meta_for,
        load_chunks,
        load_frame_lookup,
        yymm2cluster,
    )
    from specs._corpus_common_io import (
        BUILD_ROOT,
        CORPUS,
        FRAME,
        IA_DL,
        IA_META,
        REPO,
        TIGER_DL,
        TIMEOUT,
        UA,
        atomic_write_text,
        canon_id,
        cell_meta,
        corpus_ids,
        existing_ids,
        largest_remainder,
        load_ids_file,
        load_manifest_rows,
        load_plan,
        log,
        manifest_layers,
        manifest_paths,
    )
    from specs._corpus_common_materialize import (
        RAW_NAME,
        manifest_row_from_meta,
        materialize_entry_into_stage,
        materialize_into_stage,
    )
    from specs._corpus_common_net import (
        _verify_content,
        download_item,
        item_url,
        open_url,
        remote_size,
    )
    from specs._corpus_common_scan import (
        TarDirs,
        band_of_yymm,
        fetch_blob,
        member_yymm,
        offsets_for,
        scan_batch,
        scan_item,
    )
    from specs._corpus_common_select import (
        FRAME_NEEDS,
        RUN_REF_RX,
        SEED,
        HaltFetch,
        TransientMiss,
        bad_rates,
        candidate_items,
        canon_or_self,
        extract_selected,
        member_fetch_fn,
        order_items,
        rates_from_idstatus,
        resolve_rates,
        run_id_statuses,
    )

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_corpus_common_io": (
        "BUILD_ROOT",
        "CORPUS",
        "FRAME",
        "IA_DL",
        "IA_META",
        "REPO",
        "TIGER_DL",
        "TIMEOUT",
        "UA",
        "atomic_write_text",
        "canon_id",
        "cell_meta",
        "corpus_ids",
        "existing_ids",
        "largest_remainder",
        "load_ids_file",
        "load_manifest_rows",
        "load_plan",
        "log",
        "manifest_layers",
        "manifest_paths",
    ),
    "_corpus_common_net": (
        "_verify_content",
        "download_item",
        "item_url",
        "open_url",
        "remote_size",
    ),
    "_corpus_common_scan": (
        "TarDirs",
        "band_of_yymm",
        "fetch_blob",
        "member_yymm",
        "offsets_for",
        "scan_batch",
        "scan_item",
    ),
    "_corpus_common_frame": (
        "band_cat_share",
        "cluster2band",
        "ensure_frame_lookup",
        "frame_filter",
        "frame_get",
        "frame_lookup_path",
        "frame_meta_for",
        "load_chunks",
        "load_frame_lookup",
        "yymm2cluster",
    ),
    "_corpus_common_features": (
        "AUTOIGNORE",
        "CENTERLINE_RX",
        "DEAD_PKGS",
        "DEADPKG_ALT",
        "DEADPKG_RX",
        "DOCCLASS_RX",
        "DSL_PKGS",
        "EDITOR_LEFT_RX",
        "FLAG_RX",
        "INPUT_RX",
        "JOURNAL_OPTS",
        "JOURNAL_STY_PKGS",
        "KERNEL_OPTS",
        "MANUAL_BF_RX",
        "ORG_LABEL_RX",
        "PLAIN_OUT_RX",
        "SECTION_RX",
        "TEXT_EXT",
        "USEP_RX",
        "XREF_RX",
        "_dist1",
        "_texts_features",
        "blob_features",
        "eligible",
        "eval_signatures",
        "extracted_features",
        "input_depth",
        "looks_like_tar",
        "member_id",
        "norm_target",
        "safe_name",
        "unpack_blob",
    ),
    "_corpus_common_materialize": (
        "RAW_NAME",
        "materialize_entry_into_stage",
        "materialize_into_stage",
        "manifest_row_from_meta",
    ),
    "_corpus_common_select": (
        "FRAME_NEEDS",
        "RUN_REF_RX",
        "SEED",
        "HaltFetch",
        "TransientMiss",
        "bad_rates",
        "candidate_items",
        "canon_or_self",
        "extract_selected",
        "member_fetch_fn",
        "order_items",
        "rates_from_idstatus",
        "resolve_rates",
        "run_id_statuses",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__；键集 = _LAZY 键集 +
# import 期名面（HEAD 全量 import 的平名，stdl/kernel 模块名在内）。
# 新增导出两侧同步（``_export_drift`` 是三表同步闸）。
__all__ = [
    # features 叶
    "AUTOIGNORE",
    # io 叶
    "BUILD_ROOT",
    "CENTERLINE_RX",
    "CORPUS",
    "DEADPKG_ALT",
    "DEADPKG_RX",
    "DEAD_PKGS",
    "DOCCLASS_RX",
    "DSL_PKGS",
    "EDITOR_LEFT_RX",
    "FLAG_RX",
    "FRAME",
    # select 叶
    "FRAME_NEEDS",
    "IA_DL",
    "IA_META",
    "INPUT_RX",
    "JOURNAL_OPTS",
    "JOURNAL_STY_PKGS",
    "KERNEL_OPTS",
    "MANUAL_BF_RX",
    "ORG_LABEL_RX",
    "PLAIN_OUT_RX",
    # materialize 叶
    "RAW_NAME",
    "REPO",
    "RUN_REF_RX",
    "SECTION_RX",
    "SEED",
    "TEXT_EXT",
    "TIGER_DL",
    "TIMEOUT",
    "UA",
    "USEP_RX",
    "XREF_RX",
    # HEAD import 期平名（stdlib/kernel 模块与类型名——``cc.X`` 可解析保旧形）
    "Counter",
    "HaltFetch",
    "NamedTuple",
    "Path",
    # scan 叶
    "TarDirs",
    "ThreadPoolExecutor",
    "TransientMiss",
    "_dist1",
    "_texts_features",
    # net 叶
    "_verify_content",
    # _benchlite re-export（import 期实载）
    "append_jsonl",
    "as_completed",
    "atomic_write_text",
    "bad_rates",
    # frame 叶
    "band_cat_share",
    "band_of_yymm",
    "blob_features",
    "candidate_items",
    "canon_id",
    "canon_or_self",
    "cell_meta",
    "cluster2band",
    "corpus_ids",
    "csv",
    "defaultdict",
    "download_item",
    "eligible",
    "ensure_frame_lookup",
    "eval_signatures",
    "existing_ids",
    "extract_selected",
    "extracted_features",
    "fetch_blob",
    "frame_filter",
    "frame_get",
    "frame_lookup_path",
    "frame_meta_for",
    "fsutil",
    "gzip",
    "hashlib",
    "idnorm",
    "indexmod",
    "input_depth",
    "io",
    "item_url",
    "iter_jsonl",
    "json",
    "lake",
    "largest_remainder",
    "load_chunks",
    "load_frame_lookup",
    "load_ids_file",
    "load_manifest_rows",
    "load_plan",
    "log",
    "looks_like_tar",
    "manifest_layers",
    "manifest_paths",
    "manifest_row_from_meta",
    "materialize_entry_into_stage",
    "materialize_into_stage",
    "member_fetch_fn",
    "member_id",
    "member_yymm",
    "norm_target",
    "offsets_for",
    "open_url",
    "order_items",
    "os",
    "paths",
    "random",
    "rates_from_idstatus",
    "re",
    "read_jsonl",
    "remote_size",
    "resolve_rates",
    "run_id_statuses",
    "safe_name",
    "scan_batch",
    "scan_item",
    "shutil",
    "strip_comments",
    "sys",
    "tarfile",
    "time",
    "unpack_blob",
    "urllib",
    "yymm2cluster",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{__package__}.{leaf}"), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖:

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝, 是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子, 只供测试调用, 装载期不自检。
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
        except Exception as exc:  # 审计兜全漂移, 非首错即死
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
