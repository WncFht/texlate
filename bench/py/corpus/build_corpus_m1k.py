#!/usr/bin/env python3
r"""build_corpus_m1k.py — m1k 评测语料构建：4 源抽样 → 物化 → corpus/（m1k-* 层）。

语料组成（1000 篇，设计见本文件尾 + work_m1k/report.md）：
  recent 300  corpus_daily 2026-09-18 层 announce_type∈{new,cross} 已物化池
  axhot  250  alphaXiv /papers/v3/feed（Hot 30d+90d + Views/Likes All）
  iclr   200  work_iclr/map.jsonl 已映射 arXiv id，年份加权抽样
  v3     250  corpus dev 层（holdout 除外——评测贞操层不烧 QA 跑）

物化优先级：本地已有（corpus_daily/corpus/corpus_iclr）→ copytree；
否则 acquire_source（钉版 HEAD+GET+unpack）3.05s 串行纪律，与
daily_arxiv/iclr_fetch 同 RatePolicy 独立预算账。

子命令：
  select       抽样 + 去重 + cat_group 补全 → work_m1k/selection.jsonl
  materialize  selection → corpus/{pid}/{meta.json,raw.*,extracted/}
  emit         物化成功集 → corpus/manifest_m1k-{layer}.jsonl + report.md
  all          以上一把梭（断点续跑：selection 已有即跳过抽样）

用法:
  uv run python bench/py/corpus/build_corpus_m1k.py all
  uv run python bench/py/corpus/build_corpus_m1k.py select --seed 42
  uv run python bench/py/corpus/build_corpus_m1k.py materialize [--limit 30]
Deps: uv venv（httpx）；texlate.arxiv.* 产品层；alphaXiv feed 无鉴权。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import ARXIV_HOST, EXPORT_HOST, AcquireStatus, Fetcher, acquire_source
from texlate.arxiv.ratelimit import RateLimiter, RatePolicy

FETCH_HOSTS = (EXPORT_HOST, ARXIV_HOST)
CORPUS = ROOT / "bench" / "corpus"  # 2026-09-20 起 m1k 层并入统一根
WORK = ROOT / "bench" / "work_m1k"
DAILY = ROOT / "bench" / "corpus_daily"
V3 = ROOT / "bench" / "corpus"
ICLR_CORPUS = V3  # corpus_iclr 已并入 corpus
ICLR_MAP = ROOT / "bench" / "work_iclr" / "map.jsonl"
ICLR_ACCEPTED = ROOT / "bench" / "work_iclr" / "accepted.jsonl"
CACHE = Path.home() / ".cache" / "texlate" / "src"
RATE_STATE = WORK / "ratelimit.json"
SELECTION = WORK / "selection.jsonl"
FETCH_STATUS = WORK / "fetch.jsonl"

UA = {"User-Agent": "texlate-m1k-corpus/1.0 (research benchmark; mailto:bench@localhost)"}
DAILY_BUDGET = 20000  # 与 daily/iclr 账互不共享
SEED = 42

N_RECENT, N_AXHOT, N_ICLR, N_V3 = 300, 250, 200, 250
DAILY_LAYER = "2026-09-18"
#: iclr 年份加权配额（map 覆盖到 2024 止）
ICLR_YEAR_QUOTA = [(2024, 80), (2023, 50), (2022, 35), (2021, 20), (0, 15)]
#: axhot 拉取清单：sort×interval 各拉 pages 页（pageSize=100）
AX_FEEDS = [("Hot", "90 Days", 4), ("Hot", "30 Days", 4), ("Views", "All time", 2), ("Likes", "All time", 2)]
#: v3 参与抽样的层（holdout 评测贞操层不烧）
V3_LAYERS = ("core", "booster", "dev_vol", "dev_failmine", "dev_recent", "expand", "hot")

_VER_RX = re.compile(r"^(?P<base>.+?)v\d+$")
#: arXiv id 合法形：new-style YYMM.NNNNN(vN) 或 old-style archive/YYMMNNN(vN)。
_ARXIV_ID_RX = re.compile(r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})v?\d*$")
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def base_id(pid: str) -> str:
    m = _VER_RX.match(pid)
    return m.group("base") if m else pid


def read_jsonl(fp: Path) -> list[dict]:
    if not fp.exists():
        return []
    out = []
    for line in fp.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def write_jsonl(fp: Path, rows) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    with fp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def materialized(corpus: Path, pid: str) -> bool:
    return (corpus / pid / "extracted").is_dir()


def cat_of(primary: str | None) -> str:
    """primary cat（cs.CL / math.PR / hep-th）→ cat_group（cs/math/hep-th）。"""
    if not primary:
        return ""
    return primary.split(".")[0]


# ---------------------------------------------------------------- alphaXiv feed
def axhot_pool() -> list[dict]:
    """alphaXiv feed 多榜拉取 → [{id, rank, sorts, title, pdf_only}]（rank=最佳榜位）。"""
    best: dict[str, dict] = {}
    for sort, interval, pages in AX_FEEDS:
        for page in range(1, pages + 1):
            url = (
                "https://api.alphaxiv.org/papers/v3/feed"
                f"?sort={sort}&interval={urllib.request.quote(interval)}"
                f"&pageNum={page}&pageSize=100"
            )
            req = urllib.request.Request(url, headers=UA)  # noqa: S310 固定 https 端点
            try:
                with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
                    data = json.loads(r.read())
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
                log(f"  axhot {sort}/{interval} p{page}: {e} — 跳过")
                break
            papers = data.get("papers") or []
            if not papers:
                break
            for i, p in enumerate(papers):
                pid = p.get("universal_paper_id")
                if not pid or not _ARXIV_ID_RX.match(pid):
                    continue  # 跳过非 arXiv 内容（alphaxiv 自有 slug 会混进 feed）
                rank = (page - 1) * 100 + i
                cur = best.get(pid)
                if cur is None:
                    best[pid] = {
                        "id": pid,
                        "rank": rank,
                        "sorts": [f"{sort}/{interval}"],
                        "title": p.get("title") or "",
                        "pdf_only": bool(p.get("pdf_only")),
                        "pub_date": p.get("publication_date") or "",
                    }
                else:
                    cur["rank"] = min(cur["rank"], rank)
                    cur["sorts"].append(f"{sort}/{interval}")
            time.sleep(0.4)  # 礼貌间隔——1.5M/h 限额远未触，但别贴脸打
    pool = sorted(best.values(), key=lambda r: r["rank"])
    log(f"axhot pool: {len(pool)} unique ids")
    return pool


# ---------------------------------------------------------------- arXiv API cat 补全
def fill_cat_groups(rows: list[dict]) -> None:
    """缺 cat_group 的行走 arXiv API 批量补（id_list 50/req）。"""
    want = [r for r in rows if not r.get("cat_group")]
    log(f"cat_group 补全: {len(want)} 行")
    for i in range(0, len(want), 50):
        batch = want[i : i + 50]
        id_list = ",".join(base_id(r["id"]) for r in batch)
        url = f"https://export.arxiv.org/api/query?id_list={id_list}&max_results=50"
        req = urllib.request.Request(url, headers=UA)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
                tree = ET.fromstring(r.read())
        except (urllib.error.URLError, OSError, ET.ParseError) as e:
            log(f"  cat batch {i}: {e} — 跳过")
            continue
        by_id: dict[str, str] = {}
        for entry in tree.findall(f"{_ATOM}entry"):
            eid = (entry.findtext(f"{_ATOM}id") or "").rsplit("/", 1)[-1]
            eid = base_id(eid)
            prim = entry.find(f"{_ARXIV}primary_category")
            term = prim.get("term") if prim is not None else ""
            if eid and term:
                by_id[eid] = cat_of(term)
        for r in batch:
            g = by_id.get(base_id(r["id"]))
            if g:
                r["cat_group"] = g
        time.sleep(3.05)


# ---------------------------------------------------------------- select
def cmd_select(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    chosen: dict[str, dict] = {}  # id -> row（层序即选择序）

    # ---- recent：daily 层 new/cross 已物化池 ----
    rows = read_jsonl(DAILY / f"manifest_{DAILY_LAYER}.jsonl")
    pool = [
        r
        for r in rows
        if r.get("announce_type") in ("new", "cross") and materialized(DAILY, r["id"])
    ]
    rng.shuffle(pool)
    for r in pool[:N_RECENT]:
        chosen[r["id"]] = {
            "id": r["id"],
            "layer": "recent",
            "cat_group": r.get("cat_group") or "",
            "title": r.get("title") or "",
            "src": f"corpus_daily/{DAILY_LAYER}",
        }
    log(f"recent: pool={len(pool)} picked={sum(1 for r in chosen.values() if r['layer'] == 'recent')}")

    # ---- axhot ----
    n0 = 0
    for p in axhot_pool():
        if n0 >= N_AXHOT:
            break
        pid = p["id"]
        if pid in chosen or p.get("pdf_only"):
            continue
        chosen[pid] = {
            "id": pid,
            "layer": "axhot",
            "cat_group": "",
            "title": p.get("title") or "",
            "src": "alphaxiv:" + ";".join(p["sorts"]),
        }
        n0 += 1
    log(f"axhot: picked={n0}")

    # ---- iclr：年份加权 ----
    year_of: dict[str, int] = {}
    for r in read_jsonl(ICLR_ACCEPTED):
        year_of[r["orid"]] = int(r.get("year") or 0)
    usable: dict[str, int] = {}  # base arxiv id -> year
    for r in read_jsonl(ICLR_MAP):
        aid = r.get("arxiv_id")
        if not aid or r.get("match") == "no_arxiv":
            continue
        usable[base_id(aid)] = year_of.get(r["orid"], 0)
    n_iclr = 0
    for year, quota in ICLR_YEAR_QUOTA:
        # year=0 桶收 ≤2021 剩余
        if year == 0:
            pool_y = sorted(pid for pid, y in usable.items() if y <= 2021)
        else:
            pool_y = sorted(pid for pid, y in usable.items() if y == year)
        rng.shuffle(pool_y)
        got = 0
        for pid in pool_y:
            if got >= quota:
                break
            if pid in chosen:
                continue
            chosen[pid] = {
                "id": pid,
                "layer": "iclr",
                "cat_group": "",
                "title": "",
                "src": f"iclr:{usable[pid]}",
            }
            got += 1
            n_iclr += 1
        log(f"iclr year={year or '<=2021'}: pool={len(pool_y)} picked={got}")
    log(f"iclr: picked={n_iclr}")

    # ---- v3：dev 层已物化池 ----
    pool = []
    for layer in V3_LAYERS:
        fp = V3 / ("manifest.jsonl" if layer == "core" else f"manifest_{layer}.jsonl")
        for r in read_jsonl(fp):
            if materialized(V3, r["id"]):
                pool.append(r)
    rng.shuffle(pool)
    n_v3 = 0
    for r in pool:
        if n_v3 >= N_V3:
            break
        pid = r["id"]
        if pid in chosen:
            continue
        chosen[pid] = {
            "id": pid,
            "layer": "v3",
            "cat_group": r.get("cat_group") or "",
            "title": "",
            "src": f"corpus/{r.get('layer', layer)}",
        }
        n_v3 += 1
    log(f"v3: pool={len(pool)} picked={n_v3}")

    sel = list(chosen.values())
    fill_cat_groups(sel)
    write_jsonl(SELECTION, sel)
    counts = {}
    for r in sel:
        counts[r["layer"]] = counts.get(r["layer"], 0) + 1
    log(f"select done: {counts} total={len(sel)} -> {SELECTION}")
    return 0


# ---------------------------------------------------------------- materialize
def local_source(pid: str) -> Path | None:
    for corpus in (DAILY, V3, ICLR_CORPUS):
        d = corpus / pid
        if (d / "extracted").is_dir():
            return d
    return None


def cmd_materialize(args: argparse.Namespace) -> int:
    sel = read_jsonl(SELECTION)
    done_status = {r["id"]: r["status"] for r in read_jsonl(FETCH_STATUS)}
    copied = fetched = skipped = 0
    todo_fetch: list[dict] = []
    for r in sel:
        pid = r["id"]
        if materialized(CORPUS, pid):
            skipped += 1
            continue
        src = local_source(pid)
        if src is not None:
            dst = CORPUS / pid
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            copied += 1
        elif done_status.get(pid) in ("ok", "cache_hit"):
            continue  # 物化成功但 dir 被清——下一轮 copy 不补，保持现状记
        else:
            todo_fetch.append(r)
    log(f"materialize: copied={copied} already={skipped} to_fetch={len(todo_fetch)}")
    if args.limit:
        todo_fetch = todo_fetch[: args.limit]
    if not todo_fetch:
        return 0

    # arXiv 可达性预检（本机直连被重置——代理必须在线）
    try:
        req = urllib.request.Request(  # noqa: S310
            "https://rss.arxiv.org/rss/cs.CL", headers=UA
        )
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            if b"<rss" not in r.read(400)[:400]:
                raise OSError("non-RSS response")
    except (urllib.error.URLError, OSError) as e:
        log(f"preflight FAILED: rss.arxiv.org unreachable ({e}) — 检查代理")
        return 3

    cache = SourceCache(CACHE)
    limiter = RateLimiter(RATE_STATE, policy=RatePolicy(daily_budget=args.budget))
    counts: dict[str, int] = {}
    CORPUS.mkdir(parents=True, exist_ok=True)
    with FETCH_STATUS.open("a", encoding="utf-8") as out, Fetcher(
        limiter=limiter, hosts=FETCH_HOSTS
    ) as fx:
        for i, row in enumerate(todo_fetch, 1):
            pid = row["id"]
            t0 = time.monotonic()
            try:
                res = acquire_source(pid, fetcher=fx, cache=cache)
                status, detail, entry = res.status.value, res.detail, res.entry
            except Exception as e:  # noqa: BLE001 逐篇记状态不炸批
                status, detail, entry = "error", f"raise:{e}", None
            rec = {
                "id": pid,
                "layer": row["layer"],
                "status": status,
                "detail": (detail or "")[:200],
                "secs": round(time.monotonic() - t0, 1),
                "ts": datetime.now(UTC).strftime("%m-%dT%H:%M:%S"),
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            counts[status] = counts.get(status, 0) + 1
            if status in (AcquireStatus.OK.value, AcquireStatus.HIT.value) and entry is not None:
                dst = CORPUS / pid
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    shutil.rmtree(dst)
                try:
                    shutil.copytree(entry.dir, dst)
                    fetched += 1
                except OSError as e:
                    log(f"  {pid} materialize failed: {e}")
            if i % 25 == 0 or i == len(todo_fetch):
                log(f"  [{i}/{len(todo_fetch)}] {counts}")
    log(f"fetch done: {counts}")
    return 0


# ---------------------------------------------------------------- emit
def cmd_emit(args: argparse.Namespace) -> int:
    sel = read_jsonl(SELECTION)
    by_layer: dict[str, list[dict]] = {}
    missing: list[str] = []
    for r in sel:
        if materialized(CORPUS, r["id"]):
            by_layer.setdefault(r["layer"], []).append(r)
        else:
            missing.append(r["id"])
    for layer, rows in by_layer.items():
        fp = CORPUS / f"manifest_m1k-{layer}.jsonl"
        write_jsonl(fp, rows)
        log(f"manifest_m1k-{layer}.jsonl: {len(rows)}")
    report = WORK / "report.md"
    lines = [
        "# corpus_m1k 构建报告",
        "",
        f"- 生成: {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- seed: {SEED}",
        "",
        "| 层 | 目标 | 物化 |",
        "|---|---|---|",
    ]
    target = {"recent": N_RECENT, "axhot": N_AXHOT, "iclr": N_ICLR, "v3": N_V3}
    for layer in ("recent", "axhot", "iclr", "v3"):
        n = len(by_layer.get(layer, []))
        lines.append(f"| {layer} | {target[layer]} | {n} |")
    lines += [
        "",
        f"- 未物化（fetch fail/pdf_only/error）: {len(missing)}",
        "",
        "## 未物化清单",
        "",
    ]
    lines += [f"- {i}" for i in missing]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"report -> {report}; missing={len(missing)}")
    return 0 if not missing else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_sel = sub.add_parser("select")
    p_sel.add_argument("--seed", type=int, default=SEED)
    p_mat = sub.add_parser("materialize")
    p_mat.add_argument("--limit", type=int, default=0)
    p_mat.add_argument("--budget", type=int, default=DAILY_BUDGET)
    p_emit = sub.add_parser("emit")
    p_all = sub.add_parser("all")
    p_all.add_argument("--seed", type=int, default=SEED)
    p_all.add_argument("--budget", type=int, default=DAILY_BUDGET)
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    CORPUS.mkdir(parents=True, exist_ok=True)
    if args.cmd == "select":
        return cmd_select(args)
    if args.cmd == "materialize":
        return cmd_materialize(args)
    if args.cmd == "emit":
        return cmd_emit(args)
    rc = cmd_select(args)
    if rc == 0:
        args.limit = 0
        rc = cmd_materialize(args)
    if rc == 0:
        rc = cmd_emit(args)
    return rc


if __name__ == "__main__":
    sys.exit(main())
