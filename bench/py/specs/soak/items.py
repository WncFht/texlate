"""soak items/select 叶——corpus manifest 行投影 + catalog 缓存 + 湖内抽样。

``_items``/``_select`` 是 spec 的 items/select 挂点；``_catalog``/``_HYDRATABLE``
被 ``soak.ingest`` 复用（catalog 状态机词表单源）。
"""

from __future__ import annotations

import os
from pathlib import Path

from kernel import lake, paths
from kernel.spec import EVAL_LAYERS

from specs import _benchlite as benchlib
from specs import _select as _sel

ROOT = Path(__file__).resolve().parents[4]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))

#: 键域纪元——与 e2e_real 同一 "v1"，让 rekey 进 v1 的 139 格老 zh
#: 与本 spec 产物共享 (idc,arm,variant) dedup/vault 键域；不加则 soak
#: 落 "-" 域，与质检/保险库口径分裂。
EPOCH = "v1"

#: lake catalog 中「自带或可免费自愈字节」的态——hydrated/pinned 直读，
#: raw_only 经 hydrate() 本地重解包零网络回 hydrated。
_HYDRATABLE = frozenset({"hydrated", "pinned", "raw_only"})

# ---------------------------------------------------------------- items/select


def _corpus_rows() -> list[dict]:
    """manifest*.jsonl 全行（eval 层剔除 + 同 id 首见胜）。

    行字段随 cell 全量携带：id/layer/cat_group/format/channel/item/
    member + fp_input=blob_sha256|main_tex_sha256。
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for mp in sorted(CORPUS.glob("manifest*.jsonl")):
        for row in benchlib.iter_jsonl(mp):
            if not isinstance(row, dict):
                continue
            pid = row.get("id")
            if not pid or pid in seen:
                continue
            if row.get("layer") in EVAL_LAYERS:
                continue  # holdout 层只进 eval spec（spec.eval 门）
            seen.add(pid)
            rows.append(
                {
                    "id": str(pid),
                    "variant": EPOCH,
                    "layer": row.get("layer"),
                    "cat_group": row.get("cat_group"),
                    "format": row.get("format"),
                    "channel": row.get("channel"),
                    "item": row.get("item"),
                    "member": row.get("member"),
                    "fp_input": row.get("blob_sha256") or row.get("main_tex_sha256"),
                }
            )
    return rows


_ITEMS: list[dict] | None = None


def _items() -> list[dict]:
    """materialize-once item 源——compile_checks 物化进 spec.items。"""
    global _ITEMS  # noqa: PLW0603
    if _ITEMS is None:
        _ITEMS = _corpus_rows()
    return _ITEMS


_CAT_MEMO: dict = {"sig": None, "cat": None}


def _catalog() -> lake.LakeCatalog:
    """mtime+size 签名缓存的 catalog 投影——在飞 hydrate 写行即失效重载。"""
    p = paths.lake_catalog_path()
    try:
        st = p.stat()
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None
    if sig != _CAT_MEMO["sig"] or _CAT_MEMO["cat"] is None:
        _CAT_MEMO["cat"] = lake.LakeCatalog.load()
        _CAT_MEMO["sig"] = sig
    return _CAT_MEMO["cat"]


def _sampleable(item: dict) -> bool:
    """--n 抽样池谓词：catalog 标可水化态，或未登记但盘上完整（seed 湖）。"""
    res = _sel.canon_res(item["id"])
    if not res.ok or not res.idc:
        return False
    st = _catalog().state(res.idc)
    if st in _HYDRATABLE:
        return True
    if st in ("failed", "empty"):
        return False
    return lake.is_complete(res.idc)


_SAMPLE_MEMO: dict = {}


def _sample_ids(layers: set[str], needle: str, n: int, seed: int) -> set[str]:
    """分层不区分地 seeded 抽 n 个 canon id（benchlib.pick_sample 的湖版）。

    select 钩子按 item 逐格调本函数——抽样结果按 (layers,needle,n,seed)
    记忆化，否则 plan 是 O(items²) 且每趟重建都重新付 catalog 装载
    （hydrate 在飞写 catalog 时每次 _sampleable 都可能触发重载）。
    """
    key = (frozenset(layers), needle, n, seed)
    hit = _SAMPLE_MEMO.get(key)
    if hit is not None:
        return hit
    pool = []
    for it in _items():
        if layers and str(it.get("layer") or "") not in layers:
            continue
        res = _sel.canon_res(it["id"])
        idc = res.idc if res.ok and res.idc else str(it["id"])
        if needle and needle not in idc:
            continue
        if not _sampleable(it):
            continue
        if res.ok and res.idc:
            pool.append(res.idc)
    pool = sorted(set(pool))
    out = _sel.seeded(pool, n, seed)
    _SAMPLE_MEMO[key] = out
    return out


def _n_sample(ctx: _sel.Ctx) -> bool:
    return ctx.idc in _sample_ids(ctx.layers, ctx.needle, ctx.n, ctx.seed)


def _select(item: dict, rp: dict) -> bool:
    """G1 plan-filter：--ids 直选（canon 双拼写归一，bypass layers）→
    --layers（缺省 core）→ --only canon 子串 → --n/--seed 湖内抽样。"""
    return _sel.select(
        item, rp, ids="decisive", layers="core", only="canon", sample=_n_sample
    )
