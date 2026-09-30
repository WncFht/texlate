"""corpus_hydrate — 湖格 skeleton 批量水合 spec（纯免费通道）。

``catalog state=skeleton ∩ bench/corpus/manifest*.jsonl`` 的 id 集逐篇
cell 化，按 manifest 行可达通道分车道（车道在 spec 加载时定死——
``chunk_min`` 是阈值契约不是运行旋钮，改动走 code_sha）：

- ``chunk``  — 行带 ``item``+``member``（channel=ia|tiger）且同 item
  待水合成员 ≥ ``CHUNK_MIN``：整 tar ``.part``+Range 续传一次、成员偏移
  索引一次（``meta/{item}.members.json``），各 cell 在 per-chunk flock
  外 seek+ 读+sha256 复核 + ``cc.materialize_into_stage`` 物化——
  corpus_v3/corpus_expand 同一套下载/物化机制。成员全 settled
  （complete|empty|failed）才删 tar——峰值磁盘 ≈ 在飞 tar 数（≤jobs），
  不是全量 ~53GiB；残留 tar 下次 run 免费续用。
- ``eprint`` — 行无 item/member（v1/v2 清单）或 chunk 成员数不足阈值：
  产品 ``acquire_source``（host 限速 + 断路器 + 持久日预算，整道串行 —
  arXiv ToU 单连接）逐篇取源；v2 行带 ``resolved_version`` 钉版 +
  ``raw_sha256`` 复核（不一致只 warn 不拦）。
- ``sw``     — ``channel=hf_scholarweave`` 的行：payload 是
  figures_stripped 重打包树、归 corpus_sw 的 rgrows worker 管
  （shard→rg 索引没落盘，本 spec 不重实现）。默认 ``sw_mode=skip``
  （retriable，留账留格）；``sw_mode=eprint`` 改走全量源重水合——
  meta.channel=arxiv_eprint、blob 与 manifest blob_sha256 语义分叉
  （重打包 sha vs 原始源 sha，meta 里记 warnings 标注）。

磁盘闸（补丁 B kernel 侧 ``TEXLATE_BENCH_MIN_FREE_GB`` 的 spec 面显式归
类，双保险）：

- chunk 道下载前 ``lake.admit(tar_size)`` 预闸 + ``lake.hydrate`` 内
  ``DiskPressureError`` 头 room 闸 + ENOSPC OSError → 一律归
  ``error``（retriable）+ ``errors[].cat="disk_gate"``，绝不 fault；
- tar 删除只发生在「全员 settled」的 chunk 锁内——cat.set 是 hydrate
  末步，settled ⇒ 该成员的 read 早已结束，prune 窗不伤在飞读件。

用法::

    bench plan corpus_hydrate                    # 枚举 + 报价（不跑 fn）
    bench run corpus_hydrate --param dry=1       # 只跑 plan 格 → plan.json
    bench run corpus_hydrate --param n=64        # 头部 chunk 试跑
    bench run corpus_hydrate --param lane=eprint
    bench run corpus_hydrate --param sw_mode=eprint

stage 链：``plan``（驱动格：盘点 metrics + {work}/plan.json）+
``hydrate``（逐篇 cell，``needs=[]``——驱动格与 paper 格异 idc，
needs 边无意义，顺序由 items 序保证驱动格最先）。
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import shutil
import sys
import tarfile
import threading
import time
from pathlib import Path

# worker 裸跑 ``python specs/x.py --worker`` 时 bench/py 不在
# sys.path——先立起才够得着 specs.*（load_spec 径下幂等）。
_BENCH_PY = str(Path(__file__).resolve().parents[1])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)

from kernel import lake, locks, paths
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc

ROOT = Path(__file__).resolve().parents[3]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))
FRAME = Path(os.environ.get("TEXLATE_FRAME", str(ROOT / "bench/frame")))

DRIVER_ID = "corpus-hydrate"
#: 同道成员数阈值——`≥12 走整 tar` 是任务契约（小簇整 tar 下载不划算）。
CHUNK_MIN = 12
#: eprint 道 arXiv 直采日预算（请求口径——docs/spec/arxiv-source.md 实测
#: ~150 发后 /src 406 渐升，ratelimit.py 同口径默认 180）。
REQ_BUDGET = 180
#: prune 判据的「无字节也算 settled」目录态——empty=耐久负答、failed=死格。
_SETTLED_CAT = frozenset({"empty", "failed"})

# ---------------------------------------------------------------- plan 数据（load 时一次性物化）


def _canon(raw) -> str:
    return cc.canon_or_self(raw, fallback=cc.canon_id)


def _rowmap(corpus: Path) -> dict[str, dict]:
    """manifest*.jsonl 全行 → {canon_id: row}——同 id 多行取「信息更全」者：
    item+member 齐 > 有 resolved_version > 先到先得。"""
    out: dict[str, dict] = {}

    def score(r: dict) -> int:
        return (
            4 * bool(r.get("item") and r.get("member"))
            + 2 * (r.get("channel") in ("ia", "tiger"))
            + bool(r.get("resolved_version"))
        )

    for layer in cc.manifest_layers(corpus):
        for _lay, fp in cc.manifest_paths(corpus, [layer]):
            for r in cc.read_jsonl(fp):
                pid = r.get("id")
                if not pid:
                    continue
                r.setdefault("layer", layer)
                key = _canon(pid)
                cur = out.get(key)
                if cur is None or score(r) > score(cur):
                    out[key] = r
    return out


def _item_meta() -> dict[str, dict]:
    """frame 索引 → {f"{channel}:{item}": {channel,size,url,sha1？|oid16?}}——
    ia 走 item-index.csv + IA_DL，tiger 走 tiger-files.csv + TIGER_DL。
    键带 channel 前缀：tiger 清单是全集（arXiv_src_* 同名全覆盖），裸 item
    键会让 tiger 行静默盖掉 ia 行——channel=ia 的 chunk 会拿着 tiger 的
    url/size/oid16 去配 ia 的 remote_size，双校验口径互斥永远不过。"""
    out: dict[str, dict] = {}
    idx = FRAME / "item-index.csv"
    if idx.exists():
        for line in idx.read_text().splitlines()[1:]:
            parts = line.split(",")
            if len(parts) < 4:
                continue
            _yymm, _chunk, ident, size = parts[0], parts[1], parts[2], parts[3]
            try:
                out[f"ia:{ident}"] = {
                    "channel": "ia",
                    "size": int(size),
                    "url": cc.IA_DL.format(item=ident),
                }
            except ValueError:
                continue
    tig = FRAME / "tiger-files.csv"
    if tig.exists():
        for line in tig.read_text().splitlines()[1:]:
            parts = line.split(",")
            if len(parts) < 3:
                continue
            name, size, oid = parts[0], parts[1], parts[2]
            item = name.removesuffix(".tar")
            try:
                out[f"tiger:{item}"] = {
                    "channel": "tiger",
                    "size": int(size),
                    "url": cc.TIGER_DL.format(name=item),
                    "oid16": oid,
                }
            except ValueError:
                continue
    return out


def _build() -> tuple[list[dict], dict[str, dict], dict[str, dict], int]:
    """一次扫描 → (items, rows_by_idc, chunks, unmapped)。

    rows_by_idc: skeleton idc → manifest 行（含 lane 判决字段）。
    chunks: item → {channel,size,url,verify,members:{idc:member}}——成员
    全集按「load 时仍 skeleton」口径，车道阈值与 prune 判据共用此集。
    unmapped: skeleton 但 manifest 无行的计数（口径违约，只报不进 items）。
    """
    cat = lake.LakeCatalog.load()
    skel = {idc for idc, row in cat.rows().items() if row.get("state") == "skeleton"}
    rows_by_idc: dict[str, dict] = {}
    rmap = _rowmap(CORPUS)
    unmapped = 0
    for idc in skel:
        r = rmap.get(idc)
        if r is not None:
            rows_by_idc[idc] = r
        else:
            unmapped += 1
    # 同 item 待水合成员计数（阈值分母 = 本次仍 pending 的成员数）
    pend: dict[str, int] = {}
    for r in rows_by_idc.values():
        if (
            r.get("item")
            and r.get("member")
            and r.get("channel")
            in (
                "ia",
                "tiger",
            )
        ):
            pend[r["item"]] = pend.get(r["item"], 0) + 1
    meta = _item_meta()
    chunks: dict[str, dict] = {}
    items: list[dict] = [{"id": DRIVER_ID, "stage": "plan", "lane": "plan"}]
    body: list[dict] = []
    for idc, r in rows_by_idc.items():
        ch = r.get("channel")
        if ch == "hf_scholarweave":
            lane = "sw"
        elif (
            r.get("item")
            and r.get("member")
            and ch in ("ia", "tiger")
            and pend[r["item"]] >= CHUNK_MIN
        ):
            lane = "chunk"
            c = chunks.setdefault(
                r["item"],
                {
                    "item": r["item"],
                    "channel": ch,
                    "size": (meta.get(f"{ch}:{r['item']}") or {}).get("size") or 0,
                    "url": (meta.get(f"{ch}:{r['item']}") or {}).get("url")
                    or cc.item_url(ch, r["item"]),
                    "oid16": (meta.get(f"{ch}:{r['item']}") or {}).get("oid16"),
                    "members": {},
                },
            )
            c["members"][idc] = r["member"]
        else:
            lane = "eprint"
        body.append(
            {
                "id": idc,
                "stage": "hydrate",
                "lane": lane,
                "layer": r.get("layer"),
                "channel": ch,
                "item": r.get("item"),
                "member": r.get("member"),
                "format": r.get("format"),
                "blob_sha256": r.get("blob_sha256"),
                "yymm": r.get("yymm"),
                "stratum_cell": r.get("stratum_cell"),
                "cat_group": r.get("cat_group"),
                "license_class": r.get("license_class"),
                "cluster_id": r.get("cluster_id"),
                "resolved_version": r.get("resolved_version"),
                "raw_sha256": r.get("raw_sha256"),
                "n_tex": r.get("n_tex"),
                "fp_input": r.get("blob_sha256") or r.get("raw_sha256"),
            }
        )
    # chunk 道按 (channel,item) 聚簇——同 tar 的 cell 在 plan 序相邻，
    # jobs 线程自然挤在同一把 chunk 锁上而非摊到全盘。
    body.sort(
        key=lambda it: (
            {"chunk": 0, "eprint": 1, "sw": 2}[it["lane"]],
            str(it.get("channel") or ""),
            str(it.get("item") or ""),
            it["id"],
        )
    )
    items.extend(body)
    return items, rows_by_idc, chunks, unmapped


_ITEMS: list[dict] | None = None
_ROWS: dict[str, dict] = {}
_CHUNKS: dict[str, dict] = {}
_UNMAPPED = 0


def _items() -> list[dict]:
    global _ITEMS, _ROWS, _CHUNKS, _UNMAPPED
    if _ITEMS is None:
        _ITEMS, _ROWS, _CHUNKS, _UNMAPPED = _build()
    return _ITEMS


# ---------------------------------------------------------------- select（G1 plan-filter）


def _pre(item: dict, rp: dict) -> bool:
    """lane/ids/only 三件套——n 的 head 集复用同一条过滤链。"""
    lane = str(rp.get("lane") or "all")
    if lane != "all" and item.get("lane") != lane:
        return False
    ids_p = str(rp.get("ids") or "").strip()
    if ids_p:
        want: set[str] = set()
        for tok0 in ids_p.split(","):
            tok = tok0.strip()
            if not tok:
                continue
            want.add(tok)
            want.add(_canon(tok))
        if str(item.get("id")) not in want:
            return False
    only = str(rp.get("only") or "").strip()
    return not (only and only not in str(item.get("id") or ""))


_HEAD_MEMO: dict = {}


def _head_set(rp: dict) -> set[str]:
    key = (
        str(rp.get("lane")),
        str(rp.get("ids")),
        str(rp.get("only")),
        int(rp.get("n") or 0),
    )
    s = _HEAD_MEMO.get(key)
    if s is None:
        ordered = [
            str(it["id"])
            for it in _items()
            if it.get("stage") == "hydrate" and _pre(it, rp)
        ]
        s = set(ordered[: int(rp.get("n") or 0)])
        _HEAD_MEMO[key] = s
    return s


def _select(item: dict, rp: dict) -> bool:
    if item.get("stage") != "hydrate":
        return True  # 驱动格永远进 plan——dry 的语义就是只留它
    if rp.get("dry"):
        return False
    if not _pre(item, rp):
        return False
    n = int(rp.get("n") or 0)
    if n > 0:
        return str(item.get("id")) in _head_set(rp)
    return True


# ---------------------------------------------------------------- 工作区 / chunk 道


def _work(ctx) -> Path:
    d = Path(ctx.params.get("build_root") or cc.BUILD_ROOT) / "hydrate"
    for sub in ("tars", "meta", "locks"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def _tar_path(work: Path, item: str) -> Path:
    return work / "tars" / f"{item}.tar"


def _members_idx(work: Path, item: str) -> Path:
    return work / "meta" / f"{item}.members.json"


def _settled(idc: str, cat: lake.LakeCatalog) -> bool:
    return lake.is_complete(idc) or cat.state(idc) in _SETTLED_CAT


def _chunk_settled(ch: dict, cat: lake.LakeCatalog) -> bool:
    return all(_settled(idc, cat) for idc in ch["members"])


def _ensure_tar(ch: dict, work: Path) -> Path:
    """chunk 锁内调用：缺→admit 预闸；在/缺都过 download_item（在=尺寸+
    内容复核直通，缺=.part 续传 + 校验）。"""
    tar = _tar_path(work, ch["item"])
    # spec 侧预闸：kernel 闸在 lake.hydrate 内才触发，tar 下载发生在
    # fetch_fn 之前、闸覆盖不到——这里先挡（admit 是 fs floor+lake cap
    # 双腿闸）。
    if not tar.exists() and not lake.admit(int(ch.get("size") or 0)):
        msg = (
            f"admit refuse: {ch['item']} needs ~"
            f"{int(ch.get('size') or 0) / 2**30:.1f} GiB headroom"
        )
        raise lake.DiskPressureError(msg)
    it = {
        "item": ch["item"],
        "channel": ch["channel"],
        "size": ch["size"],
        "url": ch["url"],
    }
    if ch.get("oid16"):
        it["oid16"] = ch["oid16"]
    return cc.download_item(it, work / "tars", work / "meta")


def _offsets(ch: dict, tar: Path, work: Path) -> dict[str, list[int]]:
    """成员名→(data_offset,size) 索引——每 tar 建一次（头一遍流扫），落盘
    供后续 cell/后续 run 免重扫；tar_size 失配即重建（重抓后 offset 全漂）。"""
    idx_f = _members_idx(work, ch["item"])
    tar_size = tar.stat().st_size
    if idx_f.exists():
        try:
            idx = json.loads(idx_f.read_text())
        except (OSError, ValueError):
            idx = None
        if isinstance(idx, dict) and idx.get("tar_size") == tar_size:
            return idx["offsets"]
    want = set(ch["members"].values())
    offs: dict[str, list[int]] = {}
    with tarfile.open(tar, "r:") as tf:
        for ti in tf:
            name = ti.name.removeprefix("./")
            if name in want:
                offs[name] = [ti.offset_data, ti.size]
                if len(offs) == len(want):
                    break
    cc.atomic_write_text(
        idx_f,
        json.dumps(
            {"tar_size": tar_size, "offsets": offs},
            sort_keys=True,
        ),
    )
    return offs


def _read_blob(tar: Path, off: int, size: int) -> bytes:
    with tar.open("rb") as f:
        f.seek(off)
        return f.read(size)


def _maybe_prune(ch: dict, work: Path) -> int:
    """全员 settled → 删 tar/.part/成员索引。try-lock 抢占失败就跳过（下一
    个完赛 cell 再试）——便宜先行：meta.json 存在性预筛过了才读 catalog。"""
    tar = _tar_path(work, ch["item"])
    if not tar.exists():
        return 0
    for m in ch["members"]:
        if not (lake.cell_dir(m) / "meta.json").exists():
            return 0
    try:
        with locks.flock(
            work / "locks" / f"{ch['item']}.lock",
            exclusive=True,
            blocking=False,
        ):
            cat = lake.LakeCatalog.load()
            if not _chunk_settled(ch, cat):
                return 0
            freed = tar.stat().st_size
            tar.unlink()
            Path(str(tar) + ".part").unlink(missing_ok=True)
            _members_idx(work, ch["item"]).unlink(missing_ok=True)
            return freed
    except locks.WouldBlock:
        return 0


def _mk_rec(cell: dict) -> dict:
    """cell 字段 → cc.materialize_into_stage 的 rec 形态。"""
    return {
        "id": cell["idc"],
        "format": cell.get("format"),
        "member": cell["member"],
        "channel": cell.get("channel"),
        "item": cell.get("item"),
        "_cell": cell.get("stratum_cell") or "",
        "cat_group": cell.get("cat_group"),
        "license_class": cell.get("license_class"),
        "cluster_id": cell.get("cluster_id"),
        "n_tex_files": cell.get("n_tex"),
        "uncompressed_bytes": None,
    }


def _post_ok(idc: str, outcome: str, channel: str, extra: dict | None = None) -> dict:
    """hydrate 后统一落账：complete→ok；catalog 'empty'=耐久负答→ok；
    其余→error（retriable）。complete 时补 catalog channels/regen_cost
    （corpus_sw 同款——tar 一 prune，字节再生就只剩网络一路）；pinned
    态不许被这行打回 hydrated。"""
    if lake.is_complete(idc):
        cat = lake.LakeCatalog.load()
        base = cat.rows().get(idc) or {}
        channels = sorted(set(base.get("channels") or []) | {channel})
        cat.set(
            idc,
            "pinned" if base.get("state") == "pinned" else "hydrated",
            source="arxiv",
            regen_cost="network",
            channels=channels,
        )
        m = {"outcome": outcome}
        m.update(extra or {})
        return {"status": "ok", "metrics": m}
    cat = lake.LakeCatalog.load()
    if cat.state(idc) == "empty":
        m = {"outcome": "empty"}
        m.update(extra or {})
        return {"status": "ok", "metrics": m}
    return {
        "status": "error",
        "errors": [{"cat": "hydrate", "msg": "post-hydrate cell incomplete"}],
        "metrics": {"outcome": "incomplete"},
    }


def _hydrate_chunk(ctx, work: Path) -> dict:
    cell = ctx.cell
    idc = ctx.idc
    ch = _CHUNKS.get(str(cell.get("item")))
    if ch is None or not cell.get("member") or not cell.get("format"):
        return {
            "status": "fail",
            "errors": [{"cat": "plan", "msg": "chunk lane 缺 item/member/format"}],
        }
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    with locks.flock(work / "locks" / f"{ch['item']}.lock"):
        tar = _ensure_tar(ch, work)
        offs = _offsets(ch, tar, work)
    want_sha = cell.get("blob_sha256")

    def fetch(_idc: str, stage: Path) -> dict:
        off = offs.get(cell["member"])
        if off is None:
            return {}  # tar 已过内容校验仍无成员=耐久负答，走 lake 'empty'
        blob = _read_blob(tar, off[0], off[1])
        sha = hashlib.sha256(blob).hexdigest()
        if want_sha and sha != want_sha:
            msg = f"sha256 mismatch {sha[:12]} != {str(want_sha)[:12]}"
            raise OSError(msg)
        return cc.materialize_into_stage(
            _mk_rec(cell),
            blob,
            sha,
            stage,
            layer=str(cell.get("layer") or "core"),
            cluster_prefix="HYD",
            reason="hydrate_chunk",
        )

    lake.hydrate(idc, fetch_fn=fetch, source="arxiv", run_seq=run_seq)
    freed = 0
    if not ctx.params.get("keep_tars"):
        freed = _maybe_prune(ch, work)
    extra = {"item": ch["item"], "tar_freed": freed} if freed else {"item": ch["item"]}
    return _post_ok(idc, "chunk", str(ch["channel"]), extra)


# ---------------------------------------------------------------- eprint 道

_EPRINT_LOCK = threading.Lock()
_EPRINT_ENV: dict = {}


def _eprint_env(ctx):
    """进程级三件（lock 内惰性建）：RateLimiter(持久日预算)/Fetcher/
    SourceCache + frame_lookup fm——ToU 单连接纪律，整道串行。"""
    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher
    from texlate.arxiv.ratelimit import RateLimiter, RatePolicy
    from texlate.textutil.osutil import cache_root

    p = ctx.params
    key = (
        int(p.get("req_budget") or REQ_BUDGET),
        str(p.get("frame_dir") or str(FRAME)),
        str(p.get("build_root") or str(cc.BUILD_ROOT)),
    )
    env = _EPRINT_ENV.get("env")
    if env is not None and _EPRINT_ENV.get("key") == key:
        return env
    d = paths.lake_durable_dir() / "hydrate"
    d.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(
        state_path=d / "ratelimit.json",
        policy=RatePolicy(daily_budget=key[0]),
    )
    fetcher = Fetcher(limiter=limiter)
    cache = SourceCache(cache_root() / "src")
    try:
        lut = cc.ensure_frame_lookup(Path(key[1]), Path(key[2]))
        ids = [str(it["id"]) for it in _items() if it.get("lane") in ("eprint", "sw")]
        fmeta = cc.frame_meta_for(ids, lut)
    except Exception:  # frame 缺席 → fm={} 退化（cat_group 'unknown'）
        fmeta = {}
    env = (limiter, fetcher, cache, fmeta)
    _EPRINT_ENV["env"] = env
    _EPRINT_ENV["key"] = key
    return env


def _hydrate_eprint(ctx) -> dict:
    from texlate.arxiv.fetch import AcquireStatus, acquire_source
    from texlate.arxiv.ratelimit import BudgetExhaustedError, ParkedError

    cell = ctx.cell
    idc = ctx.idc
    pid = str(cell.get("id"))
    row = _ROWS.get(idc) or {}
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    permanent = {
        AcquireStatus.NOT_FOUND,
        AcquireStatus.PDF_ONLY,
        AcquireStatus.UNKNOWN_FORMAT,
        AcquireStatus.UNPACK_ERROR,
        AcquireStatus.TOO_LARGE,
    }
    ver = row.get("resolved_version")
    try:
        ver = int(ver) if ver is not None else None
    except (TypeError, ValueError):
        ver = None
    holder: dict = {}
    with _EPRINT_LOCK:
        limiter, fetcher, cache, fmeta = _eprint_env(ctx)
        # 预算预检：不发请求先看账——BudgetExhaustedError 由 acquire 抛也
        # 归 error(retriable)，这里先挡省得每格都撞一次异常路径。
        if limiter.requests_today >= limiter.policy.daily_budget:
            return {
                "status": "error",
                "errors": [
                    {
                        "cat": "budget",
                        "msg": f"daily req budget {limiter.policy.daily_budget} exhausted",
                    }
                ],
                "metrics": {"outcome": "budget"},
            }
        n0 = limiter.requests_today
        want_sha = row.get("raw_sha256")

        def fetch(_idc: str, stage: Path) -> dict:
            res = acquire_source(pid, fetcher=fetcher, cache=cache, version=ver)
            holder["res"] = res
            if res.status in (AcquireStatus.OK, AcquireStatus.HIT) and res.entry:
                meta = cc.materialize_entry_into_stage(
                    res.entry.dir,
                    stage,
                    pid=pid,
                    fm=fmeta.get(idc) or {},
                    mechs="hydrate",
                    layer=str(row.get("layer") or "expand"),
                )
                # manifest 行是分层真相——frame 回填的 EXP-* 簇/层名
                # 一律按行口径覆写；eprint 道 channel 保持 arxiv_eprint。
                for k in (
                    "layer",
                    "stratum_cell",
                    "cluster_id",
                    "cat_group",
                    "license_class",
                ):
                    if row.get(k) is not None:
                        meta[k] = row[k]
                meta["pick_reason"] = f"hydrate_eprint:{row.get('layer') or 'unlisted'}"
                if want_sha:
                    got = next(
                        (r for r in (stage / "raw").glob("raw.*")),
                        None,
                    )
                    if (
                        got is not None
                        and hashlib.sha256(got.read_bytes()).hexdigest() != want_sha
                    ):
                        meta.setdefault("warnings", []).append(
                            f"raw_sha256 mismatch vs manifest {str(want_sha)[:12]}"
                        )
                return meta
            if res.status in permanent:
                holder["permanent"] = res.status.value
                return {}
            msg = f"acquire {res.status.value}: {res.detail or ''}"
            raise OSError(msg)

        try:
            lake.hydrate(idc, fetch_fn=fetch, source="arxiv", run_seq=run_seq)
        except (BudgetExhaustedError, ParkedError) as e:
            return {
                "status": "error",
                "errors": [{"cat": "budget", "msg": str(e)}],
                "metrics": {"outcome": "budget"},
            }
    res = holder.get("res")
    extra = {
        "acquire": res.status.value if res is not None else None,
        "requests": limiter.requests_today - n0,
        "resolved_version": getattr(res, "resolved_version", None)
        if res is not None
        else None,
    }
    return _post_ok(idc, "eprint", "arxiv_eprint", extra)


# ---------------------------------------------------------------- stages


def _plan(ctx) -> dict:
    _items()  # 确保 _ROWS/_CHUNKS 物化
    work = _work(ctx)
    lane_n = {"chunk": 0, "eprint": 0, "sw": 0}
    for it in _items():
        if it.get("stage") == "hydrate":
            lane_n[it["lane"]] = lane_n.get(it["lane"], 0) + 1
    tar_gb = round(sum(c["size"] for c in _CHUNKS.values()) / 2**30, 1)
    missing = [
        f for f in ("item-index.csv", "tiger-files.csv") if not (FRAME / f).exists()
    ]
    lake_free = None
    with contextlib.suppress(OSError):
        lake_free = round(shutil.disk_usage(paths.lake_dir()).free / 2**30, 1)
    plan = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "skeleton": sum(lane_n.values()),
        "unmapped": _UNMAPPED,
        "lanes": lane_n,
        "chunks": sorted(
            (
                {
                    "item": c["item"],
                    "channel": c["channel"],
                    "size": c["size"],
                    "pending": len(c["members"]),
                }
                for c in _CHUNKS.values()
            ),
            key=lambda c: (c["channel"], c["item"]),
        ),
        "tar_gib": tar_gb,
        "eprint_days_est": round(
            lane_n.get("eprint", 0)
            * 2
            / max(int(ctx.params.get("req_budget") or REQ_BUDGET), 1),
            1,
        ),
        "disk_free_gib": lake_free,
        "admit0": lake.admit(0),
        "frame_missing": missing,
    }
    cc.atomic_write_text(work / "plan.json", json.dumps(plan, indent=2))
    ctx.emit(
        {
            "metric": "hydrate_plan",
            **{f"lane_{k}": v for k, v in lane_n.items()},
            "chunks": len(_CHUNKS),
            "tar_gib": tar_gb,
            "disk_free_gib": lake_free,
            "admit0": plan["admit0"],
            "unmapped": _UNMAPPED,
        }
    )
    if _UNMAPPED:
        ctx.emit_note(
            f"{_UNMAPPED} skeleton 格无 manifest 行——口径违约，跳过",
            level="warn",
        )
    if missing:
        ctx.emit_note(f"frame 资产缺: {missing} — chunk 道无尺寸/校验源", level="warn")
        return "fail"
    return "ok"


def _hydrate(ctx) -> dict:
    cell = ctx.cell
    idc = ctx.idc
    lane = str(cell.get("lane") or "")
    if lake.is_complete(idc):
        return {"status": "ok", "metrics": {"outcome": "already"}}
    # 免费本地臂：raw/ 残件在 → fetch_fn=None 重投影，零网络（lake 内建
    # raw_only→hydrated 路，且不吃 DiskPressureError 头 room 闸）。
    if (lake.cell_dir(idc) / "raw").is_dir():
        lake.hydrate(
            idc,
            fetch_fn=None,
            source="arxiv",
            run_seq=getattr(ctx.rundir, "run_seq", 0) or 0,
        )
        if lake.is_complete(idc):
            return {"status": "ok", "metrics": {"outcome": "raw_rebuild"}}
    if lane == "sw" and str(ctx.params.get("sw_mode")) != "eprint":
        return {
            "status": "skip",
            "errors": [
                {
                    "cat": "deferred",
                    "msg": "hf_scholarweave 格归 corpus_sw 管；"
                    "sw_mode=eprint 走全量源重水合",
                }
            ],
            "metrics": {"outcome": "sw_deferred"},
        }
    work = _work(ctx)
    try:
        if lane == "chunk":
            return _hydrate_chunk(ctx, work)
        return _hydrate_eprint(ctx)
    except lake.DiskPressureError as e:
        return {
            "status": "error",
            "errors": [{"cat": "disk_gate", "msg": str(e)}],
            "metrics": {"outcome": "disk_gate"},
        }
    except OSError as e:
        if e.errno == errno.ENOSPC:
            return {
                "status": "error",
                "errors": [{"cat": "disk_gate", "msg": str(e)}],
                "metrics": {"outcome": "disk_gate"},
            }
        raise


# ---------------------------------------------------------------- spec

spec = Spec(
    kind="corpus_hydrate",
    items=_items,
    params={
        "build_root": Param(type=str, default=str(cc.BUILD_ROOT), fp=False),
        "corpus_dir": Param(type=str, default=str(cc.CORPUS), fp=False),
        "frame_dir": Param(type=str, default=str(cc.FRAME), fp=False),
        "lane": Param(
            type=str,
            default="all",
            choices=["all", "chunk", "eprint", "sw"],
        ),
        "sw_mode": Param(
            type=str,
            default="skip",
            choices=["skip", "eprint"],
        ),
        "dry": Param(type=bool, default=False, fp=False),
        "n": Param(type=int, default=0),
        "ids": Param(type=str, default="", fp=False),
        "only": Param(type=str, default="", fp=False),
        "req_budget": Param(type=int, default=REQ_BUDGET),
        "keep_tars": Param(type=bool, default=False, fp=False),
    },
    stages=[
        Stage(
            "plan",
            _plan,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
        Stage(
            "hydrate",
            _hydrate,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
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
        "src/texlate/arxiv",
    ],
    select=_select,
    lake=True,
    prefetch=False,
    # eval=True 是单件非论文 id 的 canon 豁免口（corpus_v3 同款先例——
    # 驱动格 id "corpus-hydrate" 非 arXiv id；paper 格 id 已是 canon，
    # verbatim 与 canon 等价；副作用仅 cell 事件 eval=True 标记）。
    eval=True,
    executor="thread",
)
