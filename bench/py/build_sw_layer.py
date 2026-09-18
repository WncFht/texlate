#!/usr/bin/env python3
r"""build_sw_layer.py — scholarweave/arxiv-latex (HF) 通道适配器 + dev_recent 层。

scholarweave 是唯一免费的 2025+ 批量 LaTeX 源（docs/research/arxiv/bulk-channels.md）：
47 个 parquet 分片（~9.6GB/片、全库 3.15M 行、按月续更），行组 yymm_id 有序——
用 footer 统计圈出 2501+ 行组，列投影 range-GET 免整片下载。

子命令：
  footers   47 分片 footer → work_v3/sw/footers.json（行组 yymm 范围编目）
  pool      2501+ 行组的 [id,yymm_id,categories,license] 列投影 → sw/pool.jsonl
  assign    三层分流：dev_recent_sw 选 ~1 行组/月整组抓取 + 组内采样；
            holdout/dev_recent 各切 eprint 臂 id 清单（全池均匀分层）
  rehydrate 行组级下载 latex 列 → FILE: 拆包 → 重打包 raw.tar.gz →
            corpus_v3/{id}/ cells + manifest_dev_recent.jsonl

单元契约（sw cell）：channel=hf_scholarweave, item=分片名, member=id,
raw.tar.gz=重水化文本树, meta figures_stripped:true（无二进制图——编译臂
走 \includegraphics stub 而非 missing_file 膨胀）。

eprint 臂落盘走 build_corpus_layers.py recent（acquire_source 同 hot 层）。

用法（HF 须 env -i 净环境——代理泄漏会 SSL EOF）:
  env -i PATH=$PATH HOME=$HOME uv run --with pyarrow --with "fsspec[http]" \
      python bench/py/build_sw_layer.py footers|pool|assign|rehydrate
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import re
import shutil
import tarfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import benchlib
import build_corpus_v3 as b3

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "bench" / "corpus_v3"
WORK = REPO / "bench" / "work_v3"
SW = WORK / "sw"
MANIFEST_OUT = CORPUS / "manifest_dev_recent.jsonl"
SEED = 42
SHARDS = 47
DATASET = "scholarweave/arxiv-latex"
SHARD_URL = (
    "https://huggingface.co/datasets/"
    + DATASET
    + "/resolve/main/arxiv_part_{:04d}.parquet"
)
MIN_YYMM = "2501"  # 近期层下界（TIGER bulk 截止 2412 之后）
N_SW = 1200  # dev_recent 脱水臂目标
N_EP_HOLDOUT = 300
N_EP_DEVRECENT = 300

log = b3.log

# cat_group 词表对齐 frame（primary_cat 前缀 → 8 组；2501+ 只见现代类目）
_CAT_GROUP = {
    "eess": "eess-stat-etc",
    "stat": "eess-stat-etc",
    "nucl-ex": "nucl",
    "nucl-th": "nucl",
    "quant-ph": "quant-ph",
}
_HEP_PHYS = {"hep-ph", "hep-th", "hep-ex", "hep-lat", "gr-qc", "physics"}
_GROUPS = {"cs", "math", "cond-mat", "astro-ph"}

FILE_MARK = re.compile(r"^={10,}\r?\nFILE: (.+?)\r?\n={10,}\r?\n", re.MULTILINE)


def yymm_recent(yymm_id: str | None) -> bool:
    """yymm_id 前 4 位 ∈ [2501, 2699]——裸词表比较会把 "9xxx" 旧年代和非数字前缀放进来。"""
    s = (yymm_id or "")[:4]
    return s.isdigit() and int(MIN_YYMM) <= int(s) <= 2699


def cat_group_of(categories: str) -> str:
    """sw categories 首类 → frame cat_group 词表。"""
    pc = (categories or "").split()[0] if categories else ""
    if pc in _CAT_GROUP:
        return _CAT_GROUP[pc]
    base = pc.split(".", 1)[0]
    if base in _HEP_PHYS:
        return "hep-phys"
    if base in _GROUPS:
        return base
    return "other"


def shard_name(n: int) -> str:
    return f"arxiv_part_{n:04d}.parquet"


def _fs_open(url: str):
    import fsspec

    return fsspec.open(url, "rb")


def load_footers() -> dict:
    return json.loads((SW / "footers.json").read_text())


# ---------------- footers ----------------


def cmd_footers(_args: argparse.Namespace) -> None:
    import pyarrow.parquet as pq

    SW.mkdir(parents=True, exist_ok=True)
    cat = {}
    for n in range(1, SHARDS + 1):
        out = SW / "footers" / f"{n:04d}.json"
        if out.exists():
            cat[n] = json.loads(out.read_text())
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        with _fs_open(SHARD_URL.format(n)) as f:
            md = pq.ParquetFile(f).metadata
        cidx = next(
            i for i in range(md.num_columns) if md.schema.column(i).name == "yymm_id"
        )
        rgs = []
        for i in range(md.num_row_groups):
            rg = md.row_group(i)
            try:
                st = rg.column(cidx).statistics
                rgs.append(
                    {
                        "i": i,
                        "rows": rg.num_rows,
                        "ymin": st.min,
                        "ymax": st.max,
                        "mb": round(rg.total_byte_size / 1e6, 1),
                    }
                )
            except Exception:
                rgs.append({"i": i, "rows": rg.num_rows, "ymin": "", "ymax": ""})
        cat[n] = {"rows": md.num_rows, "rgs": rgs}
        benchlib.atomic_write_text(out, json.dumps(cat[n]))
        log(f"footer {n:04d}: {md.num_rows} rows {len(rgs)} rgs")
    benchlib.atomic_write_text(SW / "footers.json", json.dumps(cat, indent=1) + "\n")
    recent = sum(1 for s in cat.values() for r in s["rgs"] if yymm_recent(r.get("ymax")))
    log(f"footers: {len(cat)} shards; {recent} rgs 含 {MIN_YYMM}+")


def recent_rgs(cat: dict) -> list[dict]:
    """含 2501+ 行的行组清单 [{shard, rg, ymin, ymax, rows}]。"""
    out = [
        {"shard": int(sn), **r}
        for sn, s in cat.items()
        for r in s["rgs"]
        if yymm_recent(r.get("ymax"))
    ]
    return sorted(out, key=lambda x: (x["ymin"], x["shard"], x["i"]))


# ---------------- pool ----------------


def cmd_pool(_args: argparse.Namespace) -> None:
    import pyarrow.parquet as pq

    cat = load_footers()
    rgs = recent_rgs(cat)
    log(f"pool: {len(rgs)} rgs 含 {MIN_YYMM}+")
    cols = ["id", "yymm_id", "categories", "license"]
    n_rows = 0
    out = SW / "pool.jsonl"
    with out.open("w") as fw:
        for ent in rgs:
            sn, i = ent["shard"], ent["i"]
            cache = SW / "pool_parts" / f"{sn:04d}_{i:03d}.jsonl"
            if cache.exists():
                for line in cache.read_text().splitlines():
                    fw.write(line + "\n")
                    n_rows += 1
                continue
            cache.parent.mkdir(parents=True, exist_ok=True)
            with _fs_open(SHARD_URL.format(sn)) as f:
                t = pq.ParquetFile(f).read_row_group(i, columns=cols)
            rows = [
                {
                    "id": r["id"],
                    "yymm_id": r["yymm_id"],
                    "cats": r["categories"],
                    "lic": r["license"],
                    "shard": sn,
                    "rg": i,
                }
                for r in t.to_pylist()
                if yymm_recent(r["yymm_id"])
            ]
            cache.write_text("\n".join(json.dumps(x) for x in rows) + "\n")
            for x in rows:
                fw.write(json.dumps(x) + "\n")
            n_rows += len(rows)
            log(f"  {sn:04d} rg{i}: {len(rows)} ids (Σ{n_rows})")
    log(f"pool: {n_rows} ids -> {out}")


# ---------------- assign ----------------


def cmd_assign(args: argparse.Namespace) -> None:
    rng = random.Random(SEED)
    pool = benchlib.read_jsonl(SW / "pool.jsonl")
    taken = benchlib.corpus_ids(CORPUS)
    pool = [r for r in pool if r["id"] not in taken]
    log(f"assign: pool {len(pool)} (去重后)")
    by_month: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_month[r["yymm_id"][:4]].append(r)
    months = sorted(by_month)
    log(f"  months: {len(months)} ({months[0]}..{months[-1]})")

    # 脱水臂：每月 1 个行组（rg 是该月内连续 id 段），组内均匀采样
    sw_picks: list[dict] = []
    used_ids: set[str] = set()
    per_month = max(1, round(N_SW / len(months)))
    for m in months:
        rows = by_month[m]
        rgs = sorted({(r["shard"], r["rg"]) for r in rows})
        pick_rg = rng.choice(rgs)
        cand = [r for r in rows if (r["shard"], r["rg"]) == pick_rg]
        rng.shuffle(cand)
        take = cand[:per_month]
        for r in take:
            used_ids.add(r["id"])
            sw_picks.append(
                {
                    "id": r["id"],
                    "yymm": m,
                    "cat_group": cat_group_of(r["cats"]),
                    "shard": r["shard"],
                    "rg": r["rg"],
                }
            )
    log(f"  sw picks: {len(sw_picks)} across {len(months)} months")

    # eprint 臂：剩余全池按月分层均匀切 holdout/dev_recent 两段
    ep_pool = [r for r in pool if r["id"] not in used_ids]
    ep_by_month: dict[str, list[dict]] = defaultdict(list)
    for r in ep_pool:
        ep_by_month[r["yymm_id"][:4]].append(r)
    for v in ep_by_month.values():
        rng.shuffle(v)
    per_m_ho = max(1, N_EP_HOLDOUT // len(months))
    per_m_dr = max(1, N_EP_DEVRECENT // len(months))
    ho: list[dict] = []
    dr: list[dict] = []
    for m in months:
        cand = ep_by_month.get(m, [])
        ho.extend(
            {
                "id": r["id"],
                "yymm": m,
                "cat_group": cat_group_of(r["cats"]),
            }
            for r in cand[:per_m_ho]
        )
        dr.extend(
            {
                "id": r["id"],
                "yymm": m,
                "cat_group": cat_group_of(r["cats"]),
            }
            for r in cand[per_m_ho : per_m_ho + per_m_dr]
        )
    rng.shuffle(ho)
    rng.shuffle(dr)
    ho, dr = ho[:N_EP_HOLDOUT], dr[:N_EP_DEVRECENT]

    (SW / "assign_sw.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in sw_picks) + "\n"
    )
    (SW / "assign_holdout.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in ho) + "\n"
    )
    (SW / "assign_dev_recent.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in dr) + "\n"
    )
    log(
        f"assign: sw={len(sw_picks)} ep_holdout={len(ho)} "
        f"ep_devrecent={len(dr)} -> sw/assign_*.jsonl"
    )


# ---------------- rehydrate ----------------


def split_files(latex: str) -> dict[str, str]:
    """==== FILE: 标记拆包 → {relpath: text}（首个标记前内容丢弃）。"""
    out: dict[str, str] = {}
    marks = list(FILE_MARK.finditer(latex))
    for idx, m in enumerate(marks):
        name = m.group(1).strip()
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(latex)
        body = latex[m.end() : end]
        # 路径消毒：禁绝对路径/../；重名追加序号
        parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            name = f"file_{idx}"
        else:
            name = "/".join(parts)
        base, n = name, 2
        while name in out:
            stem, dot, suf = base.rpartition(".")
            name = f"{stem}_{n}{dot}{suf}" if dot else f"{base}_{n}"
            n += 1
        out[name] = body
    return out


def rehydrate_row(r: dict, dest: Path) -> dict | None:
    """parquet 行 → corpus cell；不合格（无 .tex）返回 None。"""
    files = split_files(r["latex"] or "")
    tex = [p for p in files if p.lower().endswith(".tex")]
    if not tex:
        return None
    pid = r["id"]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, text in files.items():
            data = text.encode("utf-8", "replace")
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    blob = buf.getvalue()
    sha = hashlib.sha256(blob).hexdigest()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "raw.tar.gz").write_bytes(blob)
    ext = dest / "extracted"
    if ext.exists():
        shutil.rmtree(ext)
    for name, text in files.items():
        fp = ext / name
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(text, encoding="utf-8", errors="replace")
    feats = b3.extracted_features(ext)
    yymm = r["yymm_id"][:4]
    cg = cat_group_of(r["categories"])
    meta = {
        "arxiv_id": pid,
        "resolved_version": None,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "era": "new" if "." in pid else "old",
        "archive": None,
        "yymm": yymm,
        "cluster_id": f"SW-{yymm}",
        "year_band": "f_2025plus",
        "layer": "dev_recent",
        "stratum_cell": f"sw|{yymm}",
        "cat_group": cg,
        "license_class": None,
        "license": r.get("license"),
        "categories": r.get("categories"),
        "channel": "hf_scholarweave",
        "item": shard_name(r["shard"]),
        "member": pid,
        "raw_sha256": sha,
        "raw_file": "raw.tar.gz",
        "format": "tar",
        "n_files": len(files),
        "tex_files": len(tex),
        "bytes": len(blob),
        "figures_stripped": True,
        "sw": {
            "shard": r["shard"],
            "rg": r["rg"],
            "update_date": r.get("update_date"),
            "version": r.get("version"),
        },
        "features": feats,
        "pick_reason": "dev_recent_sw",
        "source": "hf_scholarweave",
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    roots = (feats or {}).get("tex_roots") or []
    main_sha = None
    if len(roots) == 1 and (ext / roots[0]).exists():
        main_sha = hashlib.sha256((ext / roots[0]).read_bytes()).hexdigest()
    return {
        "id": pid,
        "era": meta["era"],
        "archive": None,
        "yymm": yymm,
        "cluster_id": meta["cluster_id"],
        "layer": "dev_recent",
        "channel": "hf_scholarweave",
        "item": meta["item"],
        "member": pid,
        "blob_sha256": sha,
        "main_tex_sha256": main_sha,
        "stratum_cell": meta["stratum_cell"],
        "cat_group": cg,
        "license_class": None,
        "format": "tar",
        "n_files": len(files),
        "n_tex": len(tex),
        "bytes": len(blob),
        "pick_reason": "dev_recent_sw",
        "figures_stripped": True,
    }


def cmd_rehydrate(args: argparse.Namespace) -> None:
    import pyarrow.parquet as pq

    picks = benchlib.read_jsonl(SW / "assign_sw.jsonl")
    done = (
        {r["id"] for r in benchlib.iter_jsonl(MANIFEST_OUT) if r.get("id")}
        if MANIFEST_OUT.exists()
        else set()
    )
    taken = benchlib.corpus_ids(CORPUS)
    by_rg: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for p in picks:
        if p["id"] not in done and p["id"] not in taken:
            by_rg[(p["shard"], p["rg"])].append(p)
    log(f"rehydrate: {sum(len(v) for v in by_rg.values())} picks / {len(by_rg)} rgs")
    cols = [
        "id",
        "yymm_id",
        "categories",
        "license",
        "version",
        "created",
        "update_date",
        "latex",
    ]
    n_ok = n_skip = n_err = 0
    for (sn, rgi), plist in sorted(by_rg.items()):
        want = {p["id"] for p in plist}
        try:
            with _fs_open(SHARD_URL.format(sn)) as f:
                t = pq.ParquetFile(f).read_row_group(rgi, columns=cols)
        except Exception as e:
            log(f"FAIL rg {sn:04d}/{rgi}: {type(e).__name__}: {e}")
            n_err += len(plist)
            continue
        rows = {r["id"]: r for r in t.to_pylist() if r["id"] in want}
        with MANIFEST_OUT.open("a") as mf:
            for p in plist:
                r = rows.get(p["id"])
                if r is None:
                    log(f"  miss {p['id']} (rg 内无此行)")
                    n_skip += 1
                    continue
                r["shard"] = sn
                r["rg"] = rgi
                try:
                    row = rehydrate_row(r, CORPUS / p["id"])
                except Exception as e:
                    log(f"  ERR {p['id']}: {type(e).__name__}: {e}")
                    n_err += 1
                    continue
                if row is None:
                    log(f"  skip {p['id']}: 无 .tex")
                    n_skip += 1
                    continue
                mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                mf.flush()
                n_ok += 1
        log(f"  rg {sn:04d}/{rgi}: ok={n_ok} skip={n_skip} err={n_err}")
        if args.limit and n_ok >= args.limit:
            break
    log(f"rehydrate done: ok={n_ok} skip={n_skip} err={n_err} -> {MANIFEST_OUT}")


def cmd_report(_args: argparse.Namespace) -> None:
    rows = benchlib.read_jsonl(MANIFEST_OUT)
    months = Counter(r.get("yymm") for r in rows)
    cats = Counter(r.get("cat_group") for r in rows)
    print(f"manifest_dev_recent.jsonl: {len(rows)} 篇")
    print(f"  months: {dict(sorted(months.items()))}")
    print(f"  cats: {dict(cats.most_common())}")
    print(
        f"  Σbytes: {sum(r.get('bytes') or 0 for r in rows) / 1e6:.0f}MB "
        f"Σtex: {sum(r.get('n_tex') or 0 for r in rows)}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "cmd",
        choices=["footers", "pool", "assign", "rehydrate", "report"],
    )
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    SW.mkdir(parents=True, exist_ok=True)
    {
        "footers": cmd_footers,
        "pool": cmd_pool,
        "assign": cmd_assign,
        "rehydrate": cmd_rehydrate,
        "report": cmd_report,
    }[a.cmd](a)


if __name__ == "__main__":
    main()
