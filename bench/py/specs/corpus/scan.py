"""corpus 扫描段叶——chunk tar 流扫（members/features/staging）+ frame_lookup 生成。

特征提取机（TEXT_EXT..eval_signatures/blob_features/_texts_features 全套）
→ ``specs._corpus_common`` 单源（cc.*）——勿再长第三份 verbatim。
``pyarrow`` 惰性 import 在 ``_frame_lookup`` 内。
"""

from __future__ import annotations

import gzip
import json
import tarfile
import time

from specs import _bootstrap
from specs import _corpus_common as cc
from specs.corpus.base import FRAME_LOOKUP_GZ, TARS, WORK, load_chunks

_bootstrap.ensure()

# ---------------- scan (S2) ----------------
# 特征提取机（TEXT_EXT..eval_signatures/blob_features/_texts_features 全套）
# → specs._corpus_common 单源（cc.*）——勿再长第三份 verbatim。


def _scan_chunk(c: dict) -> None:
    tag = f"{c['yymm']}_{c['chunk_no']:03d}"
    mdir = WORK / "members"
    fdir = WORK / "features"
    sdir = WORK / "staging" / c["cluster_id"]
    for d in (mdir, fdir, sdir):
        d.mkdir(parents=True, exist_ok=True)
    mout, fout = mdir / f"{tag}.jsonl", fdir / f"{tag}.jsonl"
    if fout.exists() and mout.exists():
        cc.log(f"scan {tag}: already done, skip")
        return
    mtmp, ftmp = mout.with_suffix(".tmp"), fout.with_suffix(".tmp")
    zsum = {}
    zp = WORK / "zipsum" / f"{c['item']}_zipsum.tsv"
    if zp.exists():
        for line in zp.read_text().splitlines():
            cols = line.split()  # 空格分隔：sha1 sha256 md5 size name
            if len(cols) >= 5:
                zsum[cols[-1]] = cols[1]  # member name -> sha256
    n = n_mismatch = 0
    t0 = time.time()
    with (
        tarfile.open(TARS / f"{c['item']}.tar", "r|") as tar,
        open(mtmp, "w") as mw,
        open(ftmp, "w") as fw,
    ):
        for m in tar:
            if not m.isreg():
                continue
            n += 1
            mw.write(
                json.dumps({"name": m.name, "size": m.size, "offset": m.offset_data})
                + "\n"
            )
            f = tar.extractfile(m)
            blob = f.read() if f else b""
            try:
                rec = cc.blob_features(m.name, blob)
            except Exception as e:  # 成员级异常不阻断
                rec = {
                    "member": m.name,
                    "id": cc.member_id(m.name),
                    "member_bytes": m.size,
                    "format": "error",
                    "error": f"{type(e).__name__}: {e}",
                }
            if zsum and m.name in zsum and rec.get("blob_sha256") != zsum[m.name]:
                n_mismatch += 1
                rec["zipsum_mismatch"] = True
            texts = rec.pop("_texts", None)
            if texts and (rec.get("n_tex_files") or 0) >= 1:
                mdir_out = sdir / rec["id"]
                for rel, content in texts.items():
                    rel_safe = cc.safe_name(rel)
                    if rel_safe is None:
                        continue
                    gzf = mdir_out / (rel_safe + ".gz")
                    gzf.parent.mkdir(parents=True, exist_ok=True)
                    gzf.write_bytes(gzip.compress(content, compresslevel=6))
            rec["cluster_id"] = c["cluster_id"]
            rec["channel"] = c["channel"]
            rec["item"] = c["item"]
            fw.write(json.dumps(rec) + "\n")
            if n % 500 == 0:
                cc.log(f"  {tag}: {n} members, {time.time() - t0:.0f}s")
    mtmp.rename(mout)
    ftmp.rename(fout)
    cc.log(
        f"scan {tag}: {n} members {time.time() - t0:.1f}s"
        + (f" zipsum_mismatch={n_mismatch}" if zsum else "")
    )


def _scan(ctx):
    chunks = load_chunks()
    n_scanned = n_failed = 0
    failed: list[str] = []
    for c in chunks:
        if c["state"] != "done":
            continue
        tag = f"{c['yymm']}_{c['chunk_no']:03d}"
        try:
            _scan_chunk(c)
            n_scanned += 1
        except Exception as e:
            n_failed += 1
            failed.append(tag)
            cc.log(f"!! scan {tag}: {type(e).__name__}: {e}")
    status = "ok" if n_failed == 0 and n_scanned else "partial"
    return {
        "status": status,
        "metrics": {
            "chunks_scanned": n_scanned,
            "chunks_failed": n_failed,
        },
        "errors": [{"cat": "corrupt", "payload": t} for t in failed[:20]],
    }


# ---------------- frame-lookup ----------------


def _frame_lookup(ctx):
    try:
        import pyarrow.parquet as pq  # 仅此 stage 需要
    except ImportError:
        ctx.emit_note(
            "pyarrow 不可导入——缺 frame 的抽样是错口径，按约定 fail 不 skip",
            level="warn",
        )
        return "fail"
    t = pq.read_table(
        cc.FRAME / "frame.parquet",
        columns=[
            "id",
            "tar_yymm",
            "year_band",
            "cat_group",
            "primary_cat",
            "license_class",
        ],
    )
    out = FRAME_LOOKUP_GZ
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt") as f:
        cols = [t.column(n).to_pylist() for n in t.column_names]
        for row in zip(*cols, strict=True):
            f.write("\t".join("" if v is None else str(v) for v in row) + "\n")
    cc.log(f"frame_lookup: {t.num_rows} rows -> {out}")
    return {"status": "ok", "metrics": {"frame_rows": t.num_rows}}
