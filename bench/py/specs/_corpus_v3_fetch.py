"""corpus_v3 下载段叶——plan/fetch/zipsum：chunks.json 落账 + .part 续传 + 双 hash 校验。"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import urllib.error
from typing import TYPE_CHECKING

from specs import _bootstrap
from specs import _corpus_common as cc
from specs._corpus_v3_base import (
    CHUNKS_JSON,
    IA_ZIPSUM,
    TARS,
    WORK,
    load_allocation,
    load_chunks,
    save_chunks,
)

_bootstrap.ensure()

if TYPE_CHECKING:
    from pathlib import Path

# ---------------- plan ----------------


def pick_chunk_ids(n: int) -> list[int]:
    """n 块月 → 选取的 1-indexed chunk 编号 (等距 2 块规则)."""
    if n <= 2:
        return list(range(1, n + 1))
    return sorted({n // 4 + 1, (3 * n) // 4 + 1})


_FRAME_INPUTS = (
    "allocation-core.csv",
    "item-index.csv",
    "tiger-files.csv",
)


def _plan(ctx):
    missing = [f for f in _FRAME_INPUTS if not (cc.FRAME / f).is_file()]
    if missing:
        ctx.emit_note(
            f"frame 资产缺席 {missing} — 先跑 frame_bootstrap(ord-0)", level="warn"
        )
        return {"status": "fail", "metrics": {"missing_frame": missing}}
    WORK.mkdir(parents=True, exist_ok=True)
    alloc = load_allocation()
    ia_idx: dict[str, dict[int, dict]] = {}
    with (cc.FRAME / "item-index.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            ia_idx.setdefault(r["yymm"], {})[int(r["chunk"])] = {
                "item": r["identifier"],
                "size": int(r["size"]),
            }
    tiger_idx: dict[str, dict[int, dict]] = {}
    with (cc.FRAME / "tiger-files.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            m = re.match(r"arXiv_src_(\d{4})_(\d{3})\.tar$", r["path"])
            if not m:
                continue
            tiger_idx.setdefault(m.group(1), {})[int(m.group(2))] = {
                "size": int(r["size_bytes"]),
                "oid16": r["lfs_oid16"],
            }

    chunks: list[dict] = []
    for row in alloc:
        yymm, ch = row["yymm"], row["channel"]
        idx = ia_idx if ch == "ia" else tiger_idx
        if yymm not in idx:
            cc.log(f"!! {row['cluster_id']} {yymm} 在 {ch} 索引中不存在")
            continue
        avail = sorted(idx[yymm])
        if len(avail) != row["n_chunks"]:
            cc.log(f"!! {yymm} 索引块数 {len(avail)} != allocation {row['n_chunks']}")
        for cid in pick_chunk_ids(len(avail)):
            if cid not in idx[yymm]:
                cc.log(f"!! {yymm} chunk {cid} 缺")
                continue
            info = idx[yymm][cid]
            if ch == "ia":
                item = info["item"]
                url = cc.IA_DL.format(item=item)
            else:
                item = f"arXiv_src_{yymm}_{cid:03d}"
                url = cc.TIGER_DL.format(name=item)
            chunks.append(
                {
                    "cluster_id": row["cluster_id"],
                    "yymm": yymm,
                    "channel": ch,
                    "chunk_no": cid,
                    "item": item,
                    "url": url,
                    "size": info["size"],
                    "oid16": info.get("oid16"),
                    "sha1": None,
                    "has_zipsum": None,
                    "state": "pending",
                    "sha256": None,
                    "elapsed_s": None,
                }
            )

    # ---- IA metadata 折叠（旧 cmd_probe 的 metadata 半页）：
    # sha1/md5 是 fetch 校验源、has_zipsum 是 zipsum 触发位——不取则下游全哑。
    # 单 item 失败只降级不钉死（probe 旧义：log 续行）。
    n_meta = 0
    (WORK / "meta").mkdir(parents=True, exist_ok=True)
    for c in chunks:
        if c["channel"] != "ia" or c.get("sha1") is not None:
            continue
        try:
            with cc.open_url(cc.IA_META.format(item=c["item"])) as r:
                meta = json.loads(r.read())
            (WORK / "meta" / f"{c['item']}.json").write_text(json.dumps(meta))
            for f in meta.get("files", []):
                if f["name"] == f"{c['item']}.tar":
                    c["sha1"] = f.get("sha1")
                    c["md5"] = f.get("md5")
                    if int(f.get("size", 0)) != c["size"]:
                        cc.log(
                            f"  {c['item']} size idx {c['size']} -> "
                            f"meta {f.get('size')}"
                        )
                        c["size"] = int(f["size"])  # meta 为权威尺寸
                if f["name"].endswith("_zipsum.tsv"):
                    c["has_zipsum"] = True
            if c["has_zipsum"] is None:
                c["has_zipsum"] = False
            n_meta += 1
        except Exception as e:
            cc.log(f"  meta fail {c['item']}: {e}")

    save_chunks(chunks)
    by_ch = {}
    for c in chunks:
        by_ch.setdefault(c["channel"], []).append(c)
    for ch, lst in by_ch.items():
        cc.log(f"{ch}: {len(lst)} chunks, {sum(c['size'] for c in lst) / 1e9:.2f} GB")
    cc.log(f"total {len(chunks)} chunks -> {CHUNKS_JSON}")
    return {
        "status": "ok",
        "metrics": {
            "chunks": len(chunks),
            "ia_meta_fetched": n_meta,
            "bytes_planned": sum(c["size"] for c in chunks),
            "clusters": len({c["cluster_id"] for c in chunks}),
        },
    }


# ---------------- fetch ----------------


def fetch_one(c: dict) -> dict:
    """下载单 chunk 到 .part → 校验 → rename .tar. 可重入：.part 按 Range 续传，
    已下载足量的直接进校验。返回更新后的 c."""
    t0 = time.time()
    part = TARS / f"{c['item']}.tar.part"
    final = TARS / f"{c['item']}.tar"
    try:
        # 快路：.tar 已在盘上且尺寸对 → 直接进校验 (状态文件被并发写乱时的自愈)
        if part.exists():
            have = part.stat().st_size
            src = part
        elif final.exists():
            if final.stat().st_size == c["size"]:
                have, src = c["size"], final
            else:
                # final 只经 verify 后 rename 而来——尺寸不对即腐文件，重抓
                final.unlink()
                have, src = 0, part
        else:
            have, src = 0, part
        if have > c["size"]:
            part.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            have = 0
        if have < c["size"]:
            stream_download(c, part, have)
            src = part
        try:
            full_sha = verify_chunk(src, c)
        except Exception:
            # 验不过的文件必删——final 验过才 rename 而来 (如今腐=盘上字节变),
            # part 验不过=内容错 (尺寸已齐), 留着下轮只是重复验同一坏字节
            (final if src == final else part).unlink(missing_ok=True)
            raise
        if src == part:
            part.rename(final)
        c.pop("error", None)
        c.update(state="done", sha256=full_sha, elapsed_s=round(time.time() - t0, 1))
    except Exception as e:
        c.update(state="failed", error=f"{type(e).__name__}: {e}")
    return c


def stream_download(c: dict, part: Path, have: int) -> None:
    """把 chunk 余量流进 .part (have>0 时 Range 续传); 完成后核对尺寸."""
    headers = {"Range": f"bytes={have}-"} if have else {}
    r = cc.open_url(c["url"], headers=headers, timeout=120)
    try:
        resumed = bool(have) and r.status == 206
        with open(part, "ab" if resumed else "wb") as f:
            while True:
                buf = r.read(1 << 20)
                if not buf:
                    break
                f.write(buf)
    finally:
        r.close()
    if part.stat().st_size != c["size"]:
        msg = f"size {part.stat().st_size} != expected {c['size']}"
        raise OSError(msg)


def verify_chunk(src: Path, c: dict) -> str:
    """完整性校验：全量 sha256 + IA sha1 (metadata) / TIGER lfs_oid16 前缀。
    返回文件 sha256."""
    # 单遍流式双 hash——read_bytes() 两次会把 GB 级 tar 整个吃进内存
    h256 = hashlib.sha256()
    h1 = hashlib.sha1(usedforsecurity=False)
    with src.open("rb") as f:
        for buf in iter(lambda: f.read(1 << 22), b""):
            h256.update(buf)
            h1.update(buf)
    full_sha = h256.hexdigest()
    if c["channel"] == "ia" and c.get("sha1"):
        s1 = h1.hexdigest()
        if s1 != c["sha1"]:
            msg = f"sha1 {s1} != meta {c['sha1']}"
            raise OSError(msg)
    if (
        c["channel"] == "tiger"
        and c.get("oid16")
        and not full_sha.startswith(c["oid16"])
    ):
        msg = f"sha256 {full_sha[:16]} != oid16 {c['oid16']}"
        raise OSError(msg)
    return full_sha


def _fetch(ctx):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    jobs = int(ctx.params.get("jobs") or 4)
    channel = ctx.params.get("channel")
    limit = ctx.params.get("limit")
    TARS.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks()
    todo = [
        c
        for c in chunks
        if c["state"] != "done" and (channel is None or c["channel"] == channel)
    ]
    if limit:
        todo = todo[: int(limit)]
    cc.log(
        f"fetch: {len(todo)} chunks pending"
        + (f" (channel={channel})" if channel else "")
    )
    done_bytes = 0
    for round_no in range(1, 5):  # 瞬断重试：.part 保留进度，Range 续传
        todo = [c for c in todo if c["state"] != "done"]
        if not todo:
            break
        if round_no > 1:
            cc.log(f"retry round {round_no}: {len(todo)} chunks")
            for c in todo:
                c["state"] = "pending"
            time.sleep(5)
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(fetch_one, c): c for c in todo}
            for fut in as_completed(futs):
                c = fut.result()
                save_chunks(chunks)
                if c["state"] == "done":
                    done_bytes += c["size"]
                    cc.log(
                        f"  ok {c['item']} {c['size'] / 1e6:.0f}MB "
                        f"{c['elapsed_s']}s | session {done_bytes / 1e9:.2f}GB"
                    )
                else:
                    cc.log(f"  FAIL {c['item']}: {c.get('error')}")
                (WORK / "download_progress.jsonl").open("a").write(
                    json.dumps(
                        {
                            "item": c["item"],
                            "state": c["state"],
                            "size": c["size"],
                            "elapsed_s": c["elapsed_s"],
                            "error": c.get("error"),
                            "ts": time.strftime("%FT%T"),
                        }
                    )
                    + "\n"
                )
    n_done = sum(c["state"] == "done" for c in chunks)
    cc.log(f"fetch done: {n_done}/{len(chunks)} chunks complete")
    failed = [c["item"] for c in chunks if c["state"] == "failed"]
    return {
        "status": "ok" if n_done == len(chunks) else "partial",
        "metrics": {
            "chunks_done": n_done,
            "chunks_total": len(chunks),
            "chunks_failed": len(failed),
            "session_bytes": done_bytes,
        },
        "errors": [{"cat": "upstream-lost", "payload": i} for i in failed[:20]],
    }


# ---------------- zipsum ----------------


def _zipsum(ctx):
    (WORK / "zipsum").mkdir(parents=True, exist_ok=True)
    chunks = load_chunks()
    n_hit = n_404 = n_err = 0
    for c in chunks:
        if c["channel"] != "ia" or not c.get("has_zipsum"):
            continue
        out = WORK / "zipsum" / f"{c['item']}_zipsum.tsv"
        if out.exists():
            n_hit += 1
            continue
        try:
            with cc.open_url(IA_ZIPSUM.format(item=c["item"])) as r:
                data = r.read()
            out.write_bytes(data)
            n_hit += 1
            cc.log(f"zipsum {c['item']} {len(data)}B")
        except urllib.error.HTTPError as e:
            cc.log(f"zipsum {c['item']} HTTP {e.code}")
            if e.code == 404:  # 永久缺失才钉死; 5xx 留下轮重试
                c["has_zipsum"] = False
                n_404 += 1
            else:
                n_err += 1
        except (urllib.error.URLError, OSError) as e:
            n_err += 1
            cc.log(f"zipsum {c['item']} {type(e).__name__}: {e} — 跳过重试")
    save_chunks(chunks)
    return {
        "status": "ok",
        "metrics": {"zipsum_present": n_hit, "zipsum_404": n_404, "zipsum_err": n_err},
    }
