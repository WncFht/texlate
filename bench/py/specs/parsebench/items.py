r"""specs.parsebench.items — item 源与收窄叶 (parsebench 拆分叶).

``_corpus_rows``：manifest*.jsonl 全行（eval 层剔除 + 同 id 首见胜）→
item 源；``_items`` materialize-once；``_catalog`` mtime+size 签名缓存；
``_sampleable``/``_sample_ids``/``_n_sample``/``_select`` G1 plan-filter。
"""

from __future__ import annotations

import os
from pathlib import Path

from kernel import lake, paths
from kernel.spec import EVAL_LAYERS

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs import _select as _sel  # run 期收窄单源（ids/layers/only/n 管道）

ROOT = Path(__file__).resolve().parents[4]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))

#: 测量届别——折进 variant；想全量重测一代（产品码换代后）就改它，
#: forever-dedup 按新 cell 键自然放行。
EPOCH = "v1"


def _corpus_rows() -> list[dict]:
    """manifest*.jsonl 全行（eval 层剔除 + 同 id 首见胜）→ item 源。

    行字段：id/layer/variant=EPOCH/fp_input=blob|main_tex sha 拼 +
    params={manifest 加权/归因全字段}（未声明 Param 不进 fp——cell_fp
    只数 spec.params 声明位）。
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
            sha = "|".join(
                x for x in (row.get("blob_sha256"), row.get("main_tex_sha256")) if x
            )
            rows.append(
                {
                    "id": str(pid),
                    "layer": row.get("layer"),
                    "variant": EPOCH,
                    "fp_input": sha or None,
                    "params": {
                        k: row.get(k)
                        for k in (
                            "stratum_cell",
                            "cluster_id",
                            "yymm",
                            "era",
                            "archive",
                            "cat_group",
                            "layer",
                            "channel",
                            "n_tex",
                            "n_files",
                            "bytes",
                            "mech_tags",
                        )
                    },
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
    """--n 抽样池谓词：**extracted 字节在场**（旧式「盘上可扫论文」同义——
    catalog 标 hydrated/pinned，或未登记但盘上完整）。raw_only 不在池：
    probe 判 partial 终态不可测，抽中即浪费样本位。"""
    res = _sel.canon_res(item["id"])
    if not res.ok or not res.idc:
        return False
    st = _catalog().state(res.idc)
    if st in ("hydrated", "pinned"):
        return True
    if st in ("failed", "empty", "raw_only", "skeleton", "hydrating", "evicted"):
        return False
    return lake.is_complete(res.idc)


def _sample_ids(layers: set[str], needle: str, n: int, seed: int) -> set[str]:
    """分层不区分地 seeded 抽 n 个 canon id（soak 同式 sorted-pool）。"""
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
    return _sel.seeded(pool, n, seed)


def _n_sample(ctx: _sel.Ctx) -> bool:
    return ctx.idc in _sample_ids(ctx.layers, ctx.needle, ctx.n, ctx.seed)


def _select(item: dict, rp: dict) -> bool:
    """G1 plan-filter：--ids 直选（canon 双拼写归一，bypass layers）→
    --layers（缺省 core）→ --only canon 子串 → --n/--seed 可测格抽样。"""
    return _sel.select(
        item, rp, ids="decisive", layers="core", only="canon", sample=_n_sample
    )
