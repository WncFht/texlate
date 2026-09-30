"""specs.corpus_layers.recent — corpus_layers recent 段叶（eprint 正交臂）。

sw assign 清单 → acquire_source 全量 blob 落格 + manifest 追加；RateLimiter
持久化日预算；截断 → error(retriable) 续跑。仅 EPRINT_LAYERS 有臂。
"""

from __future__ import annotations

import json
from pathlib import Path

from kernel import lake, paths

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs.corpus_layers.base import EPRINT_LAYERS, PROFILES, _dirs

# ---------------------------------------------------------------- recent（eprint 正交臂）


def _load_recent_ids(path: Path) -> list[dict]:
    """sw assign 清单 → [{id, cat_group}]；jsonl 行或纯文本 id。"""
    out = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            r = json.loads(line)
            out.append({"id": r["id"], "cat_group": r.get("cat_group")})
        else:
            out.append({"id": line, "cat_group": None})
    return out


def _eprint_fetch_fn(pid, cand, prefix, layer, fetcher, cache, holder):
    """recent 臂 fetch_fn：acquire_source → entry 树搬进 stage + meta。

    永久负态 → {} 走 lake 'empty' 耐久负答；parked/budget → cc.HaltFetch 停批；
    其余非 OK → cc.TransientMiss 逐件跳过。meta 层字段在
    materialize_entry_into_stage 通用产物上覆写（cluster_id={prefix}-R /
    stratum_cell={layer}|recent / figures_stripped=false）。"""
    from texlate.arxiv.fetch import AcquireStatus, acquire_source

    permanent = {
        AcquireStatus.NOT_FOUND,
        AcquireStatus.PDF_ONLY,
        AcquireStatus.UNKNOWN_FORMAT,
        AcquireStatus.UNPACK_ERROR,
        AcquireStatus.TOO_LARGE,
    }

    def fn(idc, stage):
        res = acquire_source(pid, fetcher=fetcher, cache=cache)
        holder["res"] = res
        holder["fetched"] = True
        if res.status in (AcquireStatus.OK, AcquireStatus.HIT) and res.entry:
            meta = cc.materialize_entry_into_stage(
                res.entry.dir,
                stage,
                pid=pid,
                fm={},
                mechs="sw_assign",
                layer=layer,
            )
            meta.update(
                {
                    "cluster_id": f"{prefix}-R",
                    "stratum_cell": f"{layer}|recent",
                    "cat_group": cand.get("cat_group") or "recent",
                    "pick_reason": f"{layer}_recent",
                    # eprint 臂全量 blob——带图，与 sw 脱水臂 cell 区分
                    "figures_stripped": False,
                    "source": "sw_pool+arxiv_eprint",
                }
            )
            return meta
        if res.status in (AcquireStatus.PARKED, AcquireStatus.BUDGET):
            raise cc.HaltFetch(res.status.value)
        if res.status in permanent:
            holder["permanent"] = res.status.value
            return {}
        raise cc.TransientMiss(res.status.value)

    return fn


def _recent(ctx):
    d = _dirs(ctx)
    layer = d["layer"]
    if layer not in EPRINT_LAYERS:
        ctx.emit(
            {
                "metric": "layers_recent",
                "layer": layer,
                "ran": 0,
                "reason": "no_eprint_arm",
            }
        )
        return "ok"
    ids_file = str(ctx.params.get("ids_file") or "").strip()
    if ids_file:
        try:
            ids_path = Path(ids_file.format(layer=layer)).expanduser()
        except (KeyError, IndexError, ValueError):
            ids_path = Path(ids_file).expanduser()
        if not ids_path.is_file():
            ctx.emit_note(f"ids_file 不存在: {ids_path}", level="warn")
            return "fail"
    else:
        ids_path = paths.lake_durable_dir() / "sw" / f"assign_{layer}.jsonl"
        if not ids_path.is_file():
            ctx.emit(
                {
                    "metric": "layers_recent",
                    "layer": layer,
                    "ran": 0,
                    "reason": "no ids_file",
                    "tried": str(ids_path),
                }
            )
            return "skip"
    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher
    from texlate.arxiv.ratelimit import RateLimiter, RatePolicy

    d["lwd"].mkdir(parents=True, exist_ok=True)
    cands = _load_recent_ids(ids_path)
    limit = int(ctx.params["recent_limit"])
    day_budget = int(ctx.params["day_budget"])
    man = d["manifest"]
    done_ids = (
        {cc.canon_id(str(r["id"])) for r in cc.iter_jsonl(man) if r.get("id")}
        if man.exists()
        else set()
    )
    taken = cc.existing_ids(d["corpus"])
    profile = PROFILES.get(layer) or {}
    prefix = profile.get("cluster_prefix") or layer.upper()[:2]
    limiter = RateLimiter(
        state_path=d["lwd"] / "ratelimit.json",
        policy=RatePolicy(daily_budget=day_budget),
    )
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    n_new = n_ok = n_skip = n_err = 0
    truncated: dict | None = None
    with Fetcher(limiter=limiter) as fetcher, man.open("a", encoding="utf-8") as mf:
        cache = SourceCache(Path.home() / ".cache" / "texlate" / "src")
        for cand in cands:
            pid = str(cand["id"])
            pidc = cc.canon_id(pid)
            if pidc in done_ids:
                continue
            if pidc in taken:
                n_skip += 1  # 已在册（他层）——认账会跨层重复计数
                continue
            cell = lake.cell_dir(pid, source="arxiv_eprint")
            meta_fp = cell / "meta.json"
            if meta_fp.exists():
                try:
                    meta = json.loads(meta_fp.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    meta = {}
                if meta.get("layer") == layer and lake.is_complete(
                    pid, source="arxiv_eprint"
                ):
                    row = cc.manifest_row_from_meta(None, cell, default_layer=layer)
                    if row is not None:
                        mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                        mf.flush()
                        done_ids.add(pidc)
                # else: 并发异层臂已落此 cell——认账会跨层重复计数
                n_skip += 1
                continue
            if limit and n_new >= limit:
                truncated = {
                    "cat": "budget",
                    "msg": f"recent_limit {limit} reached — 续跑",
                }
                break
            holder: dict = {}
            try:
                lake.hydrate(
                    pid,
                    _eprint_fetch_fn(pid, cand, prefix, layer, fetcher, cache, holder),
                    "arxiv_eprint",
                    run_seq,
                )
            except cc.HaltFetch as hb:
                cc.append_jsonl(d["recent_fail"], {"id": pid, "status": str(hb)})
                if holder.get("fetched"):
                    n_new += 1
                truncated = {
                    "cat": "budget" if "budget" in str(hb) else "parked",
                    "msg": f"{hb} — 限流到顶，停批续跑",
                }
                n_err += 1
                break
            except cc.TransientMiss as tm:
                cc.append_jsonl(d["recent_fail"], {"id": pid, "status": str(tm)})
                if holder.get("fetched"):
                    n_new += 1
                n_skip += 1
                continue
            except Exception as e:
                if holder.get("fetched"):
                    n_new += 1
                cc.append_jsonl(
                    d["recent_fail"],
                    {"id": pid, "error": f"{type(e).__name__}: {e}"},
                )
                truncated = {
                    "cat": "exception",
                    "msg": f"{pid} acquire raised {type(e).__name__}: {e} — 停批续跑",
                }
                n_err += 1
                break
            if holder.get("fetched"):
                n_new += 1
            if lake.is_complete(pid, source="arxiv_eprint"):
                row = cc.manifest_row_from_meta(None, cell, default_layer=layer)
                if row is not None:
                    mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    mf.flush()
                done_ids.add(pidc)
                taken.add(pidc)
                n_ok += 1
            else:
                res = holder.get("res")
                cc.append_jsonl(
                    d["recent_fail"],
                    {
                        "id": pid,
                        "status": (res.status.value if res is not None else "empty"),
                        "detail": getattr(res, "detail", "") if res else "",
                        "permanent": holder.get("permanent"),
                    },
                )
                n_skip += 1
    remaining = sum(1 for c in cands if cc.canon_id(str(c["id"])) not in done_ids)
    ctx.emit(
        {
            "metric": "layers_recent",
            "layer": layer,
            "ran": 1,
            "cands": len(cands),
            "fetched": n_new,
            "ok": n_ok,
            "skip": n_skip,
            "err": n_err,
            "remaining": remaining,
            "recent_limit": limit,
            "day_budget": day_budget,
            "requests_today": getattr(limiter, "requests_today", None),
        }
    )
    if truncated is not None:
        return {"status": "error", "errors": [truncated]}
    if n_err and not n_ok:
        return "error"
    return "ok"
