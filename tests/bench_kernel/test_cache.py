"""Tests for kernel/cache.py — the global segment cache (§3.9): probe
accounting, flush-on-ok discipline, writable bypass, eviction, and the
vault->cache rebuild verb.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest
from kernel import (
    cache as cachemod,
)
from kernel import (
    events,
    kernel,
    paths,
    runs,
)
from kernel.spec import Spec, Stage

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from kernel.ctx import Ctx

SC = {
    "ok": "terminal",
    "error": "retriable",
    "skip": "retriable",
    "fail": "terminal",
    "fault": "terminal",
}


def _stage(name: str, fn: Callable, **kw: object) -> Stage:
    kw.setdefault("status_class", dict(SC))
    return Stage(name, fn=fn, **kw)


def _free_spec(fns: dict[str, Callable], items: list[dict], **kw: object) -> Spec:
    kw.setdefault("kind", "tbench")
    kw.setdefault("eval", True)
    return Spec(stages=[_stage(n, fns[n]) for n in fns], items=items, **kw)


def _shard(rd: runs.RunDir) -> list[dict]:
    return [
        e for _ln, e, _raw in events.iter_jsonl(rd.events_path()) if isinstance(e, dict)
    ]


def _cell_rows(rd: runs.RunDir, status: str | None = None) -> list[dict]:
    return [
        e
        for e in _shard(rd)
        if e["type"] == "cell" and (status is None or e["status"] == status)
    ]


def _quiet(**kw: object) -> dict[str, object]:
    kw.setdefault("emit", lambda *_a, **_k: None)
    return kw


DIMS = {
    "prompt_version": "pv-test",
    "base_url": "http://gw.test",
    "model": "m-test",
    "lang": "zh",
}


def _key(**over: str) -> str:
    d = dict(DIMS)
    d.update(over)
    return cachemod.file_key_of(**d)


# --- SegCache semantics ---------------------------------------------------------


def test_seg_cache_probe_counters(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    sc = cachemod.SegCache(_key(), {"k1": "v1"})
    assert ("k1" in sc) is True
    assert ("k2" in sc) is False
    assert sc.get("k1") == "v1"
    assert sc.get("k3") is None
    with pytest.raises(KeyError):
        sc["k3"]  # absent getitem counts a miss too
    assert (sc.hits, sc.misses) == (2, 3)
    sc["k4"] = "v4"
    del sc["k1"]
    assert (sc.stores, sc.evictions, sc.dirty) == (1, 1, True)


def test_seg_cache_readonly_bypass(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    sc = cachemod.SegCache(_key(), {"k1": "v1"}, writable=False)
    assert sc["k1"] == "v1"  # reads still work (uncounted getitem)
    sc["k2"] = "v2"  # store drops on the floor
    sc.setdefault("k3", "v3")
    sc.pop("k1")
    assert (sc.bypassed, sc.dirty) == (3, False)
    assert "k1" in sc
    assert "k2" not in sc
    assert "k3" not in sc
    assert sc.flush() == 0  # nothing to write


def test_bucket_roundtrip_and_shard_layout(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    fk = _key()
    bp = cachemod.bucket_path(fk)
    assert bp.name == f"{fk}.json"
    assert bp.parent.name == fk[:2]
    sc = cachemod.open_bucket(**DIMS)
    sc["seg-1"] = "译文"
    assert sc.flush() == 1
    on_disk = json.loads(bp.read_text())
    assert on_disk == {"seg-1": "译文"}
    # reload merges — a second handle sees the stored entry
    sc2 = cachemod.open_bucket(**DIMS)
    assert sc2["seg-1"] == "译文"


def test_bad_bucket_key_refused(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    with pytest.raises(ValueError, match="bad bucket key"):
        cachemod.bucket_path("../escape")


# --- kernel flush hook ------------------------------------------------------------


def test_stores_flush_only_on_ok_terminal(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    """The poison rule: buffered stores land iff the cell ends
    flush-worthy; a failed cell's segments never reach the bucket."""
    fk = _key()

    def ok_fn(ctx: Ctx) -> str:
        sc = ctx.seg_cache(**DIMS)
        sc["seg-a"] = "甲"
        return "ok"

    def fail_fn(ctx: Ctx) -> str:
        sc = ctx.seg_cache(**DIMS)
        sc["seg-b"] = "乙"
        return "fail"

    spec = _free_spec({"a": ok_fn}, [{"id": "x"}])
    kernel.run(spec, **_quiet())
    bp = cachemod.bucket_path(fk)
    assert json.loads(bp.read_text()) == {"seg-a": "甲"}

    spec2 = _free_spec({"a": fail_fn}, [{"id": "y"}], kind="tbench2")
    kernel.run(spec2, **_quiet())
    assert json.loads(bp.read_text()) == {"seg-a": "甲"}  # no seg-b

    # and a crash discards likewise
    def boom(ctx: Ctx) -> str:
        sc = ctx.seg_cache(**DIMS)
        sc["seg-c"] = "丙"
        msg = "mid-cell crash"
        raise RuntimeError(msg)

    spec3 = _free_spec({"a": boom}, [{"id": "z"}], kind="tbench3")
    kernel.run(spec3, **_quiet())
    assert json.loads(bp.read_text()) == {"seg-a": "甲"}


def test_cache_metrics_ride_terminal_row(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    def fn(ctx: Ctx) -> str:
        sc = ctx.seg_cache(**DIMS)
        sc["seg-a"] = "甲"
        _ = "seg-a" in sc  # hit (already stored locally)
        _ = "seg-zzz" in sc  # miss
        return "ok"

    spec = _free_spec({"a": fn}, [{"id": "x"}])
    res = kernel.run(spec, **_quiet())
    rd = runs.load_run(spec.kind, res["date"], res["slug"])
    row = _cell_rows(rd)[0]
    cm = row["metrics"]["cache"]
    assert (cm["buckets"], cm["stores"]) == (1, 1)
    assert (cm["hits"], cm["misses"]) == (1, 1)


def test_cache_hit_across_runs(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    """The payoff: a second cell over the same bucket reads a hit."""
    fk = _key()
    bp = cachemod.bucket_path(fk)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps({"seg-a": "甲"}))

    seen = {}

    def fn(ctx: Ctx) -> str:
        sc = ctx.seg_cache(**DIMS)
        seen["hit"] = sc.get("seg-a")
        return "ok"

    spec = _free_spec({"a": fn}, [{"id": "x"}])
    kernel.run(spec, **_quiet())
    assert seen["hit"] == "甲"


# --- eviction + status --------------------------------------------------------------


def test_status_and_evict(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    fk1, fk2 = _key(model="m1"), _key(model="m2")
    for fk, payload in ((fk1, {"a": "x" * 100}), (fk2, {"b": "y" * 10})):
        bp = cachemod.bucket_path(fk)
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_text(json.dumps(payload))
    older = cachemod.bucket_path(fk1)
    os.utime(older, (0, 0))  # force oldest mtime
    st = cachemod.status()
    assert (st["buckets"], st["malformed"]) == (2, 0)
    removed = cachemod.evict(50)
    assert removed == [older]
    assert not older.exists()
    assert cachemod.bucket_path(fk2).exists()


def test_status_flags_malformed(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    root = paths.lake_cache_dir()
    (root / "junk").mkdir(parents=True, exist_ok=True)
    (root / "junk" / "nothexname.json").write_text("{}")
    st = cachemod.status()
    assert st["malformed"] >= 1


# --- vault rebuild ------------------------------------------------------------------


def _write_state_cell(sid: str, key: str, results: list[dict]) -> Path:
    d = paths.vault_kind_dir("state") / sid / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({"results": results}))
    return d


def test_rebuild_from_vault(broot: Path) -> None:  # noqa: ARG001 -- fixture 副作用 (隔离 bench root)
    from texlate.xlat import (  # noqa: PLC0415 -- 随 kernel 侧惰载口径：texlate.xlat 重依赖不进模块顶层
        placeholders,
    )
    from texlate.xlat.state import segment_key  # noqa: PLC0415 -- 同上

    src = "The [[MATH_3]] result holds."  # placeholder-bearing source
    zh = "[[MATH_3]] 结果成立。"
    results = [
        {
            "chunk_id": "c0",
            "source": src,
            "translation": zh,
            "status": "ok",
            "kind": "para",
        },
        {
            "chunk_id": "c1",
            "source": "bad",
            "translation": "坏",
            "status": "fault",
            "kind": "para",
        },  # non-ok never enters
    ]
    _write_state_cell("2401.00001", "swe.0", results)
    res = cachemod.rebuild_from_vault(
        prompt_version=DIMS["prompt_version"],
        base_url=DIMS["base_url"],
        model=DIMS["model"],
        lang="zh",
    )
    assert (res["cells"], res["chunks"], res["skipped"]) == (1, 1, 1)
    bp = cachemod.bucket_path(res["file_key"])
    disk = json.loads(bp.read_text())
    ph_types = [placeholders.ph_type(p) for p in placeholders.ANY_PH_RX.findall(src)]
    want_key = segment_key(src, "para", masked_snapshot=repr(ph_types))
    assert disk == {want_key: zh}

    # dry mode reports but writes nothing new
    res2 = cachemod.rebuild_from_vault(
        prompt_version="pv-other",
        base_url=DIMS["base_url"],
        model=DIMS["model"],
        dry=True,
    )
    assert res2["chunks"] == 1
    assert not cachemod.bucket_path(res2["file_key"]).exists()
