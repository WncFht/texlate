"""frame_build — bench/frame/ 抽样框资产再生。

bench/frame/ 全部 13 件资产 gitignored 已灭（payload 无副本），本 spec 是
唯一再生路径，也是 v3/expand/layers/hot 全部 corpus builder 的前置：

    bench run frame_build                              # 按上游最新快照重建
    bench run frame_build --param snapshot_sha=<rev>   # 钉 HF revision 重建

配方 = docs/research/corpus/frame-and-allocation.md（§1 远程列裁剪扫表、
§4 带内累计量等分位取月、§5 坑清单），逐条内化：簇主键 = id 内嵌月
tar_yymm（非 v1 月，3.1% 滚动错位）；yymm 比较走年序键（yy>=91→19yy，
'0612'<'9501' 裸序在 2000 界断裂）；license 取记录级最新值；a 带宇宙
≥1995-01（化石层排除）；e 带宇宙 = 可达月 ∩ band 区间；d 带宇宙含
IA 无 TIGER 有的两月。

五段链：snapshot（env -i 净环境 duckdb+httpfs 远扫 10 shard → frame_raw）
→ derive（frame.parquet 14 列 + strata/counts/coverage CSV）∥ indexes
（IA advancedsearch + HF tree 分页 → 双索引 + chunks_by_yymm）
→ allocate（30 月簇 × ~33 配额 + cluster-cat-mix + booster 表）
→ stamp（MANIFEST.md lastModified/行数刷新——唯一 tracked 写）。

duckdb 不在项目 venv：重活全走 ``env -i PATH HOME TMPDIR`` 子进程
``uv run --no-project --with duckdb python``（HF 代理泄漏→SSL EOF 是
实测坑，env 干净是硬要求；IA 同走净环境无害）。worker 自带 schema 与
license 词表校验：漂移 → fail（terminal），网络/IO → error（retriable）。
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from kernel import fsutil
from kernel.spec import SC_OK_FAIL, Param, Spec, Stage

REPO = Path(__file__).resolve().parents[3]
_HF_REPO = "librarian-bots/arxiv-metadata-snapshot"

# ---------------------------------------------------------------------------
# worker：在 env -i 净环境 uv run --with duckdb 下跑——项目 venv 无 parquet 栈。
# 协议：stderr 进度的最后打一行 ``RESULT {json}``；status ∈ ok|fail|error。
# ---------------------------------------------------------------------------

_WORKER_SRC = r'''
import csv, json, re, sys, urllib.request
from pathlib import Path

UA = {"User-Agent": "texlate-frame-build/1.0 (research sampling frame rebuild)"}
HF_REPO = "librarian-bots/arxiv-metadata-snapshot"
TIGER_REPO = "TIGER-Lab/arxiv-latex-5T"
IA_SEARCH = ("https://archive.org/advancedsearch.php?q=collection:arxiv-bulk"
             "&fl[]=identifier&fl[]=item_size&rows=8000&output=json")
IA_RX = re.compile(r"^arXiv_src_(\d{4})_(\d{3})$")
TG_RX = re.compile(r"^arXiv_src_(\d{4})_(\d{3})\.tar$")


def _result(status, **kw):
    kw["status"] = status
    print("RESULT " + json.dumps(kw, ensure_ascii=False, sort_keys=True))
    sys.exit({"ok": 0, "error": 2}.get(status, 1))


def _log(msg):
    print(f"[worker] {msg}", file=sys.stderr, flush=True)


def _get(url, timeout=180):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=timeout)


def _get_json(url, timeout=180):
    return json.loads(_get(url, timeout).read())


def _duck(tmp):
    import duckdb
    con = duckdb.connect()
    try:
        con.execute("INSTALL httpfs; LOAD httpfs;")
    except Exception:
        con.execute("LOAD httpfs;")
    if tmp:
        con.execute(f"SET temp_directory='{tmp}'")
    return con


def _ym(yymm):
    yy = int(yymm[:2])
    return ((1900 + yy) if yy >= 91 else (2000 + yy)) * 100 + int(yymm[2:])


# ---- snapshot -------------------------------------------------------------

def cmd_snapshot(out, rev, tmp):
    try:
        meta = _get_json(f"https://huggingface.co/api/datasets/{HF_REPO}")
    except Exception as e:
        _result("error", cat="hf_meta", err=str(e)[-300:])
    sha = rev or meta.get("sha")
    if not sha:
        _result("fail", cat="hf_meta", err="no sha in repo metadata")
    shards = [f"https://huggingface.co/datasets/{HF_REPO}/resolve/{sha}"
              f"/data/train-0000{i}-of-00010.parquet" for i in range(10)]
    try:
        con = _duck(tmp)
        cols = {r[0] for r in con.execute(
            f"DESCRIBE SELECT * FROM '{shards[0]}'").fetchall()}
    except Exception as e:
        _result("error", cat="hf_describe", err=str(e)[-300:])
    need = {"id", "versions", "categories", "license",
            "journal-ref", "update_date"}
    if not need <= cols:
        _result("fail", cat="schema_drift", missing=sorted(need - cols),
                have=sorted(cols))
    urls = ",".join(f"'{u}'" for u in shards)
    sql = f"""COPY (SELECT id,
      CASE WHEN strpos(id,'/')>0 THEN 'old' ELSE 'new' END id_style,
      (list_extract(versions,1)).created v1_created,
      try_strptime((list_extract(versions,1)).created,
                   '%a, %d %b %Y %H:%M:%S GMT') v1_ts,
      len(versions) n_versions,
      split_part(categories,' ',1) primary_cat,
      categories, license license_uri,
      ("journal-ref" IS NOT NULL) has_journal_ref,
      update_date
    FROM read_parquet([{urls}])) TO '{out / "frame_raw.parquet"}'
    (FORMAT PARQUET)"""
    try:
        con.execute(sql)
    except Exception as e:
        _result("error", cat="hf_scan", err=str(e)[-300:])
    raw = str(out / "frame_raw.parquet")
    n = con.execute(f"SELECT count(*) FROM '{raw}'").fetchone()[0]
    null_ts = con.execute(
        f"SELECT count(*) FROM '{raw}' WHERE v1_ts IS NULL").fetchone()[0]
    _result("ok", rows=n, snapshot_sha=sha, upstream_sha=meta.get("sha"),
            upstream_last_modified=meta.get("lastModified"),
            v1_ts_null=null_ts)


# ---- derive ---------------------------------------------------------------

_CAT_GROUP_SQL = """CASE
 WHEN primary_cat LIKE 'cs%' OR primary_cat='cmp-lg' THEN 'cs'
 WHEN primary_cat LIKE 'math%' OR primary_cat IN
      ('math-ph','alg-geom','dg-ga','funct-an','q-alg') THEN 'math'
 WHEN primary_cat LIKE 'cond-mat%' OR primary_cat IN
      ('mtrl-th','supr-con') THEN 'cond-mat'
 WHEN primary_cat LIKE 'astro-ph%' THEN 'astro-ph'
 WHEN primary_cat IN ('nucl-th','nucl-ex') THEN 'nucl'
 WHEN primary_cat='quant-ph' THEN 'quant-ph'
 WHEN split_part(primary_cat,'.',1) IN
      ('eess','stat','econ','q-bio','q-fin','bayes-an')
   THEN 'eess-stat-etc'
 ELSE 'hep-phys' END"""

_LICENSE_SQL = """CASE
 WHEN license_uri IS NULL THEN 'missing'
 WHEN license_uri LIKE '%nonexclusive%' THEN 'arxiv-nonexclusive'
 WHEN license_uri LIKE '%publicdomain%' OR license_uri LIKE '%/zero/%'
   OR license_uri LIKE '%cc0%' THEN 'cc0-pd'
 WHEN license_uri LIKE '%by-nc-nd%' THEN 'cc-by-nc-nd'
 WHEN license_uri LIKE '%by-nc-sa%' THEN 'cc-by-nc-sa'
 WHEN license_uri LIKE '%by-sa%' THEN 'cc-by-sa'
 ELSE 'cc-by' END"""

_LICENSE_COVER = ("license_uri LIKE '%nonexclusive%' OR license_uri LIKE "
    "'%publicdomain%' OR license_uri LIKE '%/zero/%' OR license_uri LIKE "
    "'%cc0%' OR license_uri LIKE '%by-nc-nd%' OR license_uri LIKE "
    "'%by-nc-sa%' OR license_uri LIKE '%by-sa%' OR license_uri LIKE '%/by/%'")


def _wcsv(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def cmd_derive(out, tmp):
    raw = out / "frame_raw.parquet"
    try:
        con = _duck(tmp)
        cols = {r[0] for r in con.execute(
            f"DESCRIBE SELECT * FROM '{raw}'").fetchall()}
    except Exception as e:
        _result("error", cat="raw_read", err=str(e)[-300:])
    need = {"id", "id_style", "v1_ts", "n_versions", "primary_cat",
            "license_uri", "has_journal_ref", "update_date"}
    if not need <= cols:
        _result("fail", cat="schema_drift", missing=sorted(need - cols))
    bad = con.execute(f"""SELECT license_uri, count(*) FROM '{raw}'
      WHERE license_uri IS NOT NULL AND NOT ({_LICENSE_COVER})
      GROUP BY 1""").fetchall()
    if bad:
        _result("fail", cat="license_drift",
                uris=[{"uri": u, "n": n} for u, n in bad])
    sql = f"""COPY (WITH b AS (
      SELECT id, id_style, v1_ts, n_versions, primary_cat, license_uri,
        has_journal_ref, update_date,
        COALESCE(NULLIF(regexp_extract(id,'^([0-9]{{4}})\\.',1),''),
                 NULLIF(regexp_extract(id,'/([0-9]{{4}})',1),''),
                 strftime(v1_ts,'%y%m')) tar_yymm
      FROM '{raw}'),
    k AS (SELECT *,
        CASE WHEN tar_yymm IS NULL THEN NULL ELSE
          (CASE WHEN CAST(substr(tar_yymm,1,2) AS INT) >= 91
                THEN 1900 ELSE 2000 END
           + CAST(substr(tar_yymm,1,2) AS INT)) END tar_year
      FROM b),
    banded AS (SELECT *,
        CASE WHEN tar_yymm IS NULL THEN 'unknown'
          WHEN tar_year*100 + CAST(substr(tar_yymm,3,2) AS INT) < 200701
            THEN 'a_pre2007'
          WHEN tar_year*100 + CAST(substr(tar_yymm,3,2) AS INT) < 201201
            THEN 'b_2007_11'
          WHEN tar_year*100 + CAST(substr(tar_yymm,3,2) AS INT) < 201701
            THEN 'c_2012_16'
          WHEN tar_year*100 + CAST(substr(tar_yymm,3,2) AS INT) < 202101
            THEN 'd_2017_20'
          WHEN tar_year*100 + CAST(substr(tar_yymm,3,2) AS INT) < 202601
            THEN 'e_2021_25'
          ELSE 'f_2026plus' END year_band,
        {_CAT_GROUP_SQL} cat_group,
        {_LICENSE_SQL} license_class
      FROM k)
    SELECT id, id_style, v1_ts, strftime(v1_ts,'%y%m') first_version_yymm,
      tar_yymm, tar_year, year_band, primary_cat, cat_group,
      license_uri, license_class, n_versions, has_journal_ref, update_date
    FROM banded) TO '{out / "frame.parquet"}' (FORMAT PARQUET)"""
    try:
        con.execute(sql)
    except Exception as e:
        _result("error", cat="derive", err=str(e)[-400:])
    fr = str(out / "frame.parquet")
    n = con.execute(f"SELECT count(*) FROM '{fr}'").fetchone()[0]
    gc = dict(con.execute(
        f"SELECT cat_group, count(*) FROM '{fr}' GROUP BY 1").fetchall())
    if set(gc) != {"cs", "math", "hep-phys", "cond-mat", "astro-ph",
                   "eess-stat-etc", "quant-ph", "nucl"} or 0 in gc.values():
        _result("fail", cat="cat_group_drift", groups=gc)
    n_null = con.execute(
        f"SELECT count(*) FROM '{fr}' WHERE tar_yymm IS NULL").fetchone()[0]
    # 分层 CSV
    era = con.execute(f"""SELECT year_band, cat_group, count(*) n
      FROM '{fr}' GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    _wcsv(out / "strata-era-cat.csv", ["year_band", "cat_group", "n"], era)
    lic = con.execute(f"""SELECT license_class, year_band, count(*) n
      FROM '{fr}' GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    _wcsv(out / "strata-license.csv", ["license_class", "year_band", "n"], lic)
    ym = con.execute(f"""SELECT tar_yymm, tar_year, year_band, count(*) n
      FROM '{fr}' WHERE tar_yymm IS NOT NULL GROUP BY 1,2,3
      ORDER BY tar_year, CAST(substr(tar_yymm,3,2) AS INT)""").fetchall()
    _wcsv(out / "counts_by_yymm.csv",
          ["yymm", "tar_year", "year_band", "n"], ym)
    cov = con.execute(f"""SELECT substr(id,1,4) yymm, count(*) n,
        max(CAST(regexp_extract(id,'\\.([0-9]+)$',1) AS BIGINT)) max_seq
      FROM '{fr}' WHERE id_style='new' GROUP BY 1 ORDER BY 1""").fetchall()
    _wcsv(out / "coverage_newstyle.csv",
          ["yymm", "n", "max_seq", "missing", "coverage"],
          [(y, c, s, s - c, round(c / s, 6)) for y, c, s in cov])
    tot_missing = sum(s - c for _, c, s in cov)
    tot_n = sum(c for _, c, _ in cov)
    tot_max = sum(s for _, _, s in cov)
    max_ym_row = ym[-1] if ym else (None, None, None, 0)
    _result("ok", rows=n, cat_groups=len(gc), tar_yymm_null=n_null,
            newstyle_missing=tot_missing,
            newstyle_coverage=round(tot_n / tot_max, 6) if tot_max else None,
            max_yymm=max_ym_row[0], max_yymm_n=max_ym_row[3],
            group_counts={k: v for k, v in sorted(gc.items())})


# ---- indexes ---------------------------------------------------------------

def cmd_indexes(out, tmp):
    # IA arxiv-bulk item 索引（advancedsearch 一次编目）
    try:
        docs = _get_json(IA_SEARCH)["response"]["docs"]
    except Exception as e:
        _result("error", cat="ia_search", err=str(e)[-300:])
    rows = []
    for d in docs:
        m = IA_RX.fullmatch(d.get("identifier") or "")
        if m:
            rows.append((m.group(1), int(m.group(2)), d["identifier"],
                         int(d.get("item_size") or 0)))
    rows.sort()
    _wcsv(out / "item-index.csv",
          ["yymm", "chunk", "identifier", "size"], rows)
    ia_chunks = {}
    for y, _c, _i, _s in rows:
        ia_chunks[y] = ia_chunks.get(y, 0) + 1
    (out / "ia_chunks_by_yymm.json").write_text(
        json.dumps(ia_chunks, indent=1, sort_keys=True) + "\n")
    # TIGER 文件索引（root tree 分页；lfs oid16 + size）
    trows, url = [], (
        f"https://huggingface.co/api/datasets/{TIGER_REPO}"
        "/tree/main?limit=1000")
    try:
        while url:
            r = _get(url)
            ents = json.loads(r.read())
            for e in ents:
                if e.get("type") != "file":
                    continue
                m = TG_RX.fullmatch(e.get("path") or "")
                if not m:
                    continue
                lfs = e.get("lfs") or {}
                trows.append((e["path"],
                              int(lfs.get("size") or e.get("size") or 0),
                              str(lfs.get("oid") or "")[:16]))
            link = r.headers.get("Link") or ""
            nm = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = nm.group(1) if nm else None
    except Exception as e:
        _result("error", cat="tiger_tree", err=str(e)[-300:])
    trows.sort()
    _wcsv(out / "tiger-files.csv",
          ["path", "size_bytes", "lfs_oid16"], trows)
    tg_chunks = {}
    for p, _s, _o in trows:
        y = TG_RX.fullmatch(p).group(1)
        tg_chunks[y] = tg_chunks.get(y, 0) + 1
    (out / "tiger_chunks_by_yymm.json").write_text(
        json.dumps(tg_chunks, indent=1, sort_keys=True) + "\n")
    if not rows or not trows:
        _result("fail", cat="index_empty",
                ia=len(rows), tiger=len(trows))
    ia_ym = sorted(ia_chunks, key=_ym)
    tg_ym = sorted(tg_chunks, key=_ym)
    _result("ok", ia_items=len(rows), ia_months=len(ia_chunks),
            ia_min_yymm=ia_ym[0], ia_max_yymm=ia_ym[-1],
            tiger_files=len(trows), tiger_months=len(tg_chunks),
            tiger_min_yymm=tg_ym[0], tiger_max_yymm=tg_ym[-1])


# ---- allocate ---------------------------------------------------------------

BANDS = [("a_pre2007", 199501, 200700), ("b_2007_11", 200701, 201200),
         ("c_2012_16", 201201, 201700), ("d_2017_20", 201701, 202100),
         ("e_2021_25", 202101, 202600)]
# 老清单（2026-09-14 快照口径）——漂移对照，非目标
OLD_PICK = ["9703", "9910", "0111", "0307", "0501", "0605",
            "0707", "0806", "0905", "1003", "1012", "1109",
            "1206", "1306", "1404", "1502", "1511", "1608",
            "1706", "1803", "1811", "1907", "2003", "2009",
            "2105", "2203", "2211", "2308", "2403", "2410"]


def cmd_allocate(out, tmp, snapshot_sha):
    con = _duck(tmp)
    fr = str(out / "frame.parquet")
    cnt = {y: n for y, n in con.execute(
        f"SELECT tar_yymm, count(*) FROM '{fr}' WHERE tar_yymm IS NOT NULL"
        " GROUP BY 1").fetchall()}
    ia = {}
    for r in csv.DictReader(open(out / "item-index.csv", newline="")):
        ia.setdefault(r["yymm"], []).append(r)
    tg = {}
    for r in csv.DictReader(open(out / "tiger-files.csv", newline="")):
        m = TG_RX.fullmatch(r["path"])
        if m:
            tg.setdefault(m.group(1), []).append(r)

    clusters = []
    for bi, (band, lo, hi) in enumerate(BANDS):
        uni = sorted((m for m in cnt
                      if lo <= _ym(m) <= hi and (m in ia or m in tg)),
                     key=_ym)
        if len(uni) < 6:
            _result("fail", cat="universe_thin", band=band, n=len(uni))
        total = sum(cnt[m] for m in uni)
        chosen, cum, pos = [], 0, 0
        for i in range(6):
            t = total * (i + 0.5) / 6
            while pos < len(uni) and cum + cnt[uni[pos]] < t:
                cum += cnt[uni[pos]]
                pos += 1
            m = uni[min(pos, len(uni) - 1)]
            if m in chosen:
                cand = [x for x in uni if x not in chosen]
                if not cand:
                    _result("fail", cat="universe_thin",
                            band=band, n=len(uni))
                pi = min(pos, len(uni) - 1)
                m = min(cand, key=lambda x: abs(uni.index(x) - pi))
            chosen.append(m)
        quota = [33] * 6
        for j in range(200 - 33 * 6):
            quota[(j * 6) // (200 - 33 * 6)] += 1
        for i, m in enumerate(chosen):
            if band == "e_2021_25":
                ch = "tiger" if m in tg else "ia"
            else:
                ch = "ia" if m in ia else "tiger"
            idx = ia if ch == "ia" else tg
            sz = sum(int(r["size"] if ch == "ia" else r["size_bytes"])
                     for r in idx[m])
            clusters.append({
                "cluster_id": f"C{bi * 6 + i + 1:02d}", "channel": ch,
                "yymm": m, "year_band": band, "n_papers": cnt[m],
                "n_chunks": len(idx[m]), "gb": round(sz / 1e9, 1),
                "quota_core": quota[i]})

    _wcsv(out / "allocation-core.csv",
          ["cluster_id", "channel", "yymm", "year_band", "n_papers",
           "n_chunks", "gb", "quota_core"],
          [(c["cluster_id"], c["channel"], c["yymm"], c["year_band"],
            c["n_papers"], c["n_chunks"], c["gb"], c["quota_core"])
           for c in clusters])
    (out / "cluster_pick.json").write_text(json.dumps(
        {"snapshot_sha": snapshot_sha, "clusters": clusters},
        indent=1, ensure_ascii=False) + "\n")

    # cluster-cat-mix：当月实际类目份额（簇内软配额参照）
    picks = [c["yymm"] for c in clusters]
    mix = con.execute(
        f"SELECT tar_yymm, cat_group, count(*) FROM '{fr}' "
        f"WHERE tar_yymm IN ({','.join(repr(p) for p in picks)})"
        " GROUP BY 1,2").fetchall()
    by_ym = {}
    for y, g, n in mix:
        by_ym.setdefault(y, {})[g] = n
    mixrows = []
    for c in clusters:
        tot = sum(by_ym.get(c["yymm"], {}).values()) or 1
        for g, n in sorted(by_ym.get(c["yymm"], {}).items()):
            mixrows.append((c["cluster_id"], c["yymm"], c["year_band"],
                            g, n, round(n / tot, 4)))
    _wcsv(out / "cluster-cat-mix.csv",
          ["cluster_id", "yymm", "year_band", "cat_group", "n", "share"],
          mixrows)

    # booster 配额表（§4.4）——侧重簇按新宇宙重算
    def cids(band):
        return [c["cluster_id"] for c in clusters if c["year_band"] == band]

    def share(c, groups):
        tot = sum(by_ym.get(c["yymm"], {}).values()) or 1
        return sum(by_ym.get(c["yymm"], {}).get(g, 0) for g in groups) / tot

    low_a = cids("a_pre2007")[:3]
    b04 = [c["cluster_id"] for c in sorted(
        (c for c in clusters
         if c["year_band"] in ("d_2017_20", "e_2021_25")),
        key=lambda c: -share(c, ("cs", "eess-stat-etc")))[:5]]
    b03 = [c["cluster_id"] for c in sorted(
        clusters, key=lambda c: -share(c, ("hep-phys",)))[:3]]
    de = cids("d_2017_20") + cids("e_2021_25")
    _wcsv(out / "allocation-booster.csv",
          ["cell", "quota", "target", "focus_clusters", "focus_rule"],
          [("B01", 30, "docstyle209_latex209", " ".join(low_a),
            "a 带最低 3 簇"),
           ("B02", 30, "non_utf8", " ".join(cids("a_pre2007")
            + cids("b_2007_11")[:2]), "a 带全部 + b 带最低 2 簇"),
           ("B03", 30, "deep_multi", " ".join(b03),
            "hep-phys 份额 top3 簇"),
           ("B04", 30, "low_tex_density", " ".join(b04),
            "d/e 带 cs+eess 份额 top5 簇"),
           ("B05", 25, "macro_pkgs", " ".join(cids("b_2007_11")[-3:]
            + cids("e_2021_25")[-3:]), "b 带末 3 + e 带末 3 簇"),
           ("B06", 20, "big_bytes", " ".join(de), "d/e 带全部簇"),
           ("B07", 25, "edge_format", " ".join(
            c["cluster_id"] for c in clusters), "全体簇"),
           ("B08", 10, "mech_fill", " ".join(
            c["cluster_id"] for c in clusters), "全体簇（机动回填）")])
    ov = len(set(picks) & set(OLD_PICK))
    _result("ok", clusters_n=len(clusters),
            quota_sum=sum(c["quota_core"] for c in clusters),
            ia_clusters=sum(1 for c in clusters if c["channel"] == "ia"),
            tiger_clusters=sum(1 for c in clusters
                               if c["channel"] == "tiger"),
            old_pick_overlap=ov,
            pick_yymms=[c["yymm"] for c in clusters],
            universe_months={b: len([m for m in cnt
                             if lo <= _ym(m) <= hi and (m in ia or m in tg)])
                             for b, lo, hi in BANDS})


SUBS = {"snapshot": cmd_snapshot, "derive": cmd_derive,
        "indexes": cmd_indexes, "allocate": cmd_allocate}

if __name__ == "__main__":
    sub, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    tmp = sys.argv[3] if len(sys.argv) > 3 else None
    extra = sys.argv[4] if len(sys.argv) > 4 else None
    try:
        if sub == "allocate":
            SUBS[sub](out, tmp, extra)
        elif sub == "snapshot":
            SUBS[sub](out, extra or None, tmp)
        else:
            SUBS[sub](out, tmp)
    except SystemExit:
        raise
    except Exception as e:
        _result("error", cat="crash", err=f"{type(e).__name__}: {e}"[-400:])
'''


# ---------------------------------------------------------------------------
# 调用面：worker 物化 + env -i 子进程 + RESULT 解析 + run 级状态边车。
# ---------------------------------------------------------------------------


def _out_dir(ctx) -> Path:
    d = Path(ctx.params.get("out_dir") or "bench/frame")
    return d if d.is_absolute() else REPO / d


def _worker_path(ctx) -> Path:
    p = ctx.rundir.derived() / "frame_worker.py"
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        fsutil.atomic_write(p, _WORKER_SRC.encode())
    return p


def _state(ctx, stage: str, result: dict) -> None:
    sp = ctx.rundir.derived() / "build_state.json"
    try:
        state = json.loads(sp.read_text())
    except (OSError, ValueError):
        state = {}
    state[stage] = result
    fsutil.atomic_write(sp, json.dumps(state, indent=1, sort_keys=True).encode())


def _load_state(ctx) -> dict:
    try:
        return json.loads((ctx.rundir.derived() / "build_state.json").read_text())
    except (OSError, ValueError):
        return {}


def _run_worker(ctx, sub: str, *extra: str) -> dict:
    uv = shutil.which("uv")
    if uv is None:
        return {
            "status": "fail",
            "cat": "no_uv",
            "err": "uv not on PATH — duckdb worker cannot run",
        }
    w = _worker_path(ctx)
    tmp = ctx.rundir.derived() / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "TMPDIR": str(tmp),
    }
    timeout = int(ctx.params.get("timeout_s") or 3600)
    cmd = [
        uv,
        "run",
        "--no-project",
        "--with",
        "duckdb",
        "python",
        str(w),
        sub,
        str(_out_dir(ctx)),
        str(tmp),
        *extra,
    ]
    try:
        r = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=timeout, cwd=REPO
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "cat": "timeout", "timeout_s": timeout}
    result = None
    for line in (r.stdout or "").splitlines():
        if line.startswith("RESULT "):
            with contextlib.suppress(ValueError):
                result = json.loads(line[7:])
    if result is None:
        return {
            "status": "error",
            "cat": "worker_crash",
            "rc": r.returncode,
            "stderr": (r.stderr or "")[-500:],
        }
    result.setdefault("worker_rc", r.returncode)
    return result


def _stage(ctx, sub: str, *extra: str):
    """worker 调用 + metrics 落账 + 状态映射."""
    if ctx.params.get("dry_run"):
        ctx.emit_note(f"{sub}: dry_run — 跳过真实构建", level="info")
        return "skip"
    res = _run_worker(ctx, sub, *extra)
    _state(ctx, sub, res)
    ctx.emit({"stage": sub, "metric": f"frame_build_{sub}", **res})
    status = res.get("status")
    if status in ("ok", "error"):
        return status
    if status == "fail":
        return {"status": "fail", "cat": str(res.get("cat") or "fail")}
    ctx.emit_note(f"{sub}: worker 无 status 字段 {res!r}", level="warn")
    return "error"


def _snapshot(ctx):
    rev = ctx.params.get("snapshot_sha") or None
    return _stage(ctx, "snapshot", rev or "")


def _derive(ctx):
    return _stage(ctx, "derive")


def _indexes(ctx):
    return _stage(ctx, "indexes")


def _allocate(ctx):
    sha = (_load_state(ctx).get("snapshot") or {}).get("snapshot_sha") or ""
    return _stage(ctx, "allocate", sha)


def _stamp(ctx):
    """MANIFEST.md lastModified/行数刷新——唯一 tracked 写."""
    if ctx.params.get("dry_run"):
        return "skip"
    st = _load_state(ctx)
    snap, drv = st.get("snapshot") or {}, st.get("derive") or {}
    lastmod = str(snap.get("upstream_last_modified") or "")[:10]
    rows = drv.get("rows") or snap.get("rows")
    max_yymm, part_n = drv.get("max_yymm"), drv.get("max_yymm_n")
    cov = drv.get("newstyle_coverage")
    mf = _out_dir(ctx) / "MANIFEST.md"
    if not mf.is_file():
        ctx.emit_note(f"MANIFEST 缺失: {mf}", level="warn")
        return "fail"
    txt = mf.read_text(encoding="utf-8")
    today = ctx.rundir.date
    mmdd = today[5:] if len(today) >= 7 else today
    edits = 0
    if lastmod:
        txt, n = re.subn(
            r"上游 lastModified \*\*[\d-]+\*\*，拉取 ~[\d-]+，覆盖至 "
            r"tar_yymm=\d{4}（当月部分量 ~[\d.k]+ 行）",
            f"上游 lastModified **{lastmod}**，拉取 ~{today}，覆盖至 "
            f"tar_yymm={max_yymm}（当月部分量 ~{part_n / 1000:.1f}k 行）"
            if max_yymm and part_n is not None
            else f"上游 lastModified **{lastmod}**，拉取 ~{today}",
            txt,
        )
        edits += n
    if rows:
        txt, n = re.subn(
            r"主资产：[\d,]+ 行 × 14 列", f"主资产：{int(rows):,} 行 × 14 列", txt
        )
        edits += n
    if cov:
        txt, n = re.subn(
            r"新式 id 覆盖 [\d.]+%", f"新式 id 覆盖 {float(cov) * 100:.4f}%", txt
        )
        edits += n
    txt, n = re.subn(r"item 索引（[\d-]+ 重建）", f"item 索引（{mmdd} 重建）", txt)
    edits += n
    if edits:
        fsutil.atomic_write(mf, txt.encode())
    ctx.emit(
        {
            "stage": "stamp",
            "metric": "frame_build_stamp",
            "edits": edits,
            "manifest": str(mf),
            "last_modified": lastmod,
            "rows": rows,
            "max_yymm": max_yymm,
            "newstyle_coverage": cov,
        }
    )
    if not lastmod or edits < 2:
        ctx.emit_note(
            f"stamp 只改到 {edits} 处/lastModified={lastmod!r} —— "
            "MANIFEST 行格式可能已漂变",
            level="warn",
        )
        return "fail"
    return "ok"


def _upstream_sha() -> str | None:
    """上游 head sha——plan 期一次性解析；ProxyHandler({}) 显式禁代理
    （泄漏的 127.0.0.1:7890 会把 HF 打成 SSL EOF，env -i 只管子进程）。"""
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"https://huggingface.co/api/datasets/{_HF_REPO}",
            headers={"User-Agent": "texlate-frame-build/1.0"},
        )
        return json.loads(op.open(req, timeout=60).read()).get("sha")
    except Exception:
        return None


def _select(item, resolved) -> bool:
    """把 cell 的 ``up`` 绑到解析后的 snapshot sha——(sha × recipe) 成为
    dedup 单元：钉 sha 必重建（deterministic rebuild），上游 head 移动
    自动重建，head 未动则 dedup 空转。spec.json 里 item 仍是 ``up=-``；
    离线时退 ``head-unknown``（cell 照常排队，snapshot 段会报真错）。"""
    sha = resolved.get("snapshot_sha") or _upstream_sha()
    item["up"] = sha or "head-unknown"
    return True


spec = Spec(
    kind="frame_build",
    select=_select,
    # eval=True：item id 非 canon（builder 单元不是 arxiv id）——豁免口
    # 同 corpus_v3.py:2117，副作用仅 cell 事件 eval 标记，无 eval 行
    eval=True,
    items=[{"id": "frame-build"}],
    params={
        "snapshot_sha": Param(type=str, default=None),
        "out_dir": Param(type=str, default="bench/frame"),
        "dry_run": Param(type=bool, default=False, fp=False),
        "timeout_s": Param(type=int, default=3600, fp=False),
    },
    stages=[
        Stage("snapshot", _snapshot, status_class=SC_OK_FAIL),
        Stage("derive", _derive, needs=[("snapshot", {"ok"})], status_class=SC_OK_FAIL),
        Stage(
            "indexes", _indexes, needs=[("snapshot", {"ok"})], status_class=SC_OK_FAIL
        ),
        Stage(
            "allocate",
            _allocate,
            needs=[("derive", {"ok"}), ("indexes", {"ok"})],
            status_class=SC_OK_FAIL,
        ),
        Stage("stamp", _stamp, needs=[("allocate", {"ok"})], status_class=SC_OK_FAIL),
    ],
)
