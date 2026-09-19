#!/usr/bin/env python3
r"""build_hot_layer.py — corpus hot 层：OpenAlex 高引近期论文 → 产品取源 → 语料落盘。

动机（2026-09-16 立项）：corpus 是 arXiv 三十年均匀抽样（IA 月块 ≤2020-10 +
TIGER ≤2412），长尾覆盖正确但与真实用户负载分布不匹配——hjfy 类产品压倒性服务
近期高热度论文。hot 层补这条轴：**扩展而非替换**，均匀层/booster 层原样保留。

两个子层（stratum）：
  hot-cite   OpenAlex `locations.source.id=arXiv` + 近窗活跃（from_publication_date
             ≥2024-01-01，按最新版本日）按 cited_by_count 降序取头——需求轴。
  hot-recent 同源 2025-06-01+ `sample=` 随机抽——2025-26 首发表的新 LaTeX 惯用法
             兜底（引用还没积累起来的新坑）。

取源走产品路径 ``acquire_source``（arxiv.org/src 钉版），不绕过限流——
每篇 = HEAD+GET 2 请求，日预算 ~180 发 → 单轮 ~85 篇封顶，次日 --resume 续。

产出（对 corpus 惯例）：
  bench/corpus/{id}/{meta.json,raw.*,extracted/}   （gitignored 数据）
  bench/corpus/manifest_hot.jsonl                  （入库清单）
  bench/work_v3/hot/candidates.jsonl                  （候选审计轨迹，gitignored）

用法:
  uv run python bench/py/corpus/build_hot_layer.py candidates [--n-cite 120] [--n-recent 40]
  uv run python bench/py/corpus/build_hot_layer.py fetch [--limit 85]
  uv run python bench/py/corpus/build_hot_layer.py report
Deps: uv venv（httpx/typer 产品代码 + urllib OpenAlex）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)  # bench/py lib 层（subdir 化）

import benchlib

from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import AcquireStatus, Fetcher, acquire_source

CORPUS = ROOT / "bench" / "corpus"
WORK = ROOT / "bench" / "work_v3" / "hot"
CANDIDATES = WORK / "candidates.jsonl"
MANIFEST_HOT = CORPUS / "manifest_hot.jsonl"
CACHE = Path.home() / ".cache" / "texlate" / "src"

UA = {
    "User-Agent": "texlate-hot-corpus/1.0 (research benchmark; mailto:bench@localhost)"
}
OPENALEX = "https://api.openalex.org/works"
ARXIV_SRC = "S4306400194"  # OpenAlex source id: arXiv (Cornell)

_NEW_ID_RX = re.compile(r"^(\d{4})\.\d{4,5}$")
_ABS_RX = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})", re.IGNORECASE)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _oa_get(params: dict) -> dict:
    # cursor/seed 等值必须 urlencode——裸插会把 `*`、`,` 之类断成坏查询
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{OPENALEX}?{qs}", headers=UA)  # noqa: S310 -- 固定 https 端点
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 -- 同上
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            last = e
        except (urllib.error.URLError, OSError) as e:
            last = e
        time.sleep(4 * (attempt + 1))
    assert last is not None
    raise last


def _arxiv_id(w: dict) -> str | None:
    for loc in w.get("locations") or []:
        u = loc.get("landing_page_url") or ""
        m = _ABS_RX.search(u)
        if m:
            return m.group(1)
    return None


def _field(w: dict) -> str:
    t = (w.get("primary_topic") or {}).get("field") or {}
    return str(t.get("display_name") or "unknown")


def cmd_candidates(args: argparse.Namespace) -> None:
    """OpenAlex 两路抽样 → candidates.jsonl（去重 vs 已有 manifest + 语料目录）。"""
    WORK.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for mf in CORPUS.glob("manifest*.jsonl"):
        for rec in benchlib.iter_jsonl(mf):
            if rec.get("id"):
                seen.add(rec["id"])
    seen |= {p.name for p in CORPUS.iterdir() if p.is_dir()}
    log(f"existing ids: {len(seen)}")

    out: list[dict] = []

    def _flush() -> None:
        # 逐页落盘——OpenAlex 翻页长，中途崩丢全部已收集候选代价大；
        # out 为空且已有候选文件时不覆盖（防 0 条抹掉好文件）
        if out or not CANDIDATES.exists():
            CANDIDATES.write_text(
                "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in out),
                encoding="utf-8",
            )
            log(f"candidates -> {CANDIDATES} ({len(out)} 条)")

    # -- hot-cite：近窗活跃 + cited_by_count 降序 --
    cursor = "*"
    while sum(1 for c in out if c["stratum"] == "hot-cite") < args.n_cite and cursor:
        d = _oa_get(
            {
                "filter": f"locations.source.id:{ARXIV_SRC},from_publication_date:2024-01-01",
                "sort": "cited_by_count:desc",
                "per-page": "200",
                "cursor": cursor,
                "select": "id,title,cited_by_count,publication_date,locations,primary_topic",
            }
        )
        for w in d.get("results", []):
            aid = _arxiv_id(w)
            if not aid or not _NEW_ID_RX.match(aid) or aid in seen:
                continue
            seen.add(aid)
            out.append(
                {
                    "id": aid,
                    "stratum": "hot-cite",
                    "cited_by_count": w.get("cited_by_count"),
                    "oa_date": w.get("publication_date"),
                    "title": (w.get("title") or "")[:200],
                    "field": _field(w),
                }
            )
            if sum(1 for c in out if c["stratum"] == "hot-cite") >= args.n_cite:
                break
        cursor = (d.get("meta") or {}).get("next_cursor")
        log(f"hot-cite collected {len(out)} (next_cursor={'y' if cursor else 'n'})")
        _flush()
        if not d.get("results"):
            break

    # -- hot-recent：2025-06+ 随机抽样（sample= 随机抽样参数）--
    got_recent = 0
    for attempt in range(4):
        if got_recent >= args.n_recent:
            break
        d = _oa_get(
            {
                "filter": f"locations.source.id:{ARXIV_SRC},from_publication_date:2025-06-01",
                "sample": str(args.n_recent * 2),
                "seed": str(args.seed + attempt),
                "select": "id,title,cited_by_count,publication_date,locations,primary_topic",
            }
        )
        for w in d.get("results", []):
            aid = _arxiv_id(w)
            if not aid or not _NEW_ID_RX.match(aid) or aid in seen:
                continue
            seen.add(aid)
            out.append(
                {
                    "id": aid,
                    "stratum": "hot-recent",
                    "cited_by_count": w.get("cited_by_count"),
                    "oa_date": w.get("publication_date"),
                    "title": (w.get("title") or "")[:200],
                    "field": _field(w),
                }
            )
            got_recent += 1
            if got_recent >= args.n_recent:
                break
        log(
            f"hot-recent attempt {attempt}: +{len(d.get('results', []))} → {got_recent}"
        )
        _flush()

    _flush()


def _merge_meta(entry_dir: Path, cand: dict, dest: Path) -> dict:
    """产品 meta.json + 语料层字段合并 → corpus 风格 meta。"""
    meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
    yymm = (cand["id"].split(".")[0])[:4]
    locate_main = ((meta.get("locate") or {}).get("main")) or None
    main_sha = None
    if locate_main and (dest / "extracted" / locate_main).exists():
        main_sha = hashlib.sha256(
            (dest / "extracted" / locate_main).read_bytes()
        ).hexdigest()
    meta.update(
        {
            "era": "new",
            "archive": None,
            "yymm": yymm,
            "cluster_id": "HOT",
            "layer": "hot",
            "stratum_cell": f"hot|{cand['stratum']}",
            "cat_group": cand.get("field") or "unknown",
            "channel": "arxiv_eprint",
            "cited_by_count": cand.get("cited_by_count"),
            "pick_reason": cand["stratum"],
            "title": cand.get("title"),
            "main_tex_sha256": main_sha,
            "source": "openalex+arxiv_eprint",
        }
    )
    return meta


def _manifest_row(cand: dict, meta: dict, dest: Path) -> dict:
    ext = dest / "extracted"
    n_files = sum(1 for p in ext.rglob("*") if p.is_file()) if ext.is_dir() else 0
    n_tex = sum(1 for p in ext.rglob("*.tex")) if ext.is_dir() else 0
    raw = next(dest.glob("raw.*"), None)
    return {
        "id": cand["id"],
        "era": "new",
        "archive": None,
        "yymm": meta.get("yymm"),
        "cluster_id": "HOT",
        "layer": "hot",
        "channel": "arxiv_eprint",
        "item": None,
        "member": None,
        "blob_sha256": meta.get("raw_sha256"),
        "main_tex_sha256": meta.get("main_tex_sha256"),
        "stratum_cell": f"hot|{cand['stratum']}",
        "cat_group": meta.get("cat_group"),
        "license_class": None,
        "format": meta.get("format"),
        "n_files": n_files,
        "n_tex": n_tex,
        "bytes": raw.stat().st_size if raw else meta.get("raw_size"),
        "cited_by_count": cand.get("cited_by_count"),
        "pick_reason": cand["stratum"],
    }


def cmd_fetch(args: argparse.Namespace) -> None:
    """候选 → acquire_source → corpus/{id}/ + manifest_hot.jsonl（可重入续跑）。"""
    if not CANDIDATES.exists():
        sys.exit("先跑 candidates 子命令")
    cands = benchlib.read_jsonl(CANDIDATES)
    done_ids = set()
    if MANIFEST_HOT.exists():
        done_ids = {r["id"] for r in benchlib.iter_jsonl(MANIFEST_HOT) if r.get("id")}

    fetcher = Fetcher()
    cache = SourceCache(CACHE)
    n_new = 0
    with MANIFEST_HOT.open("a", encoding="utf-8") as mf:
        for cand in cands:
            pid = cand["id"]
            if pid in done_ids:
                continue
            if (CORPUS / pid / "extracted").is_dir():
                # 上次崩在 copytree~manifest append 之间：meta 在 → 回补
                # manifest 行；meta 缺/坏 → 树不完整，落回重抓自愈
                try:
                    meta = json.loads(
                        (CORPUS / pid / "meta.json").read_text(encoding="utf-8")
                    )
                    mf.write(
                        json.dumps(
                            _manifest_row(cand, meta, CORPUS / pid),
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    mf.flush()
                    done_ids.add(pid)
                    continue
                except (OSError, json.JSONDecodeError):
                    pass
            if n_new >= args.limit:
                log(f"limit {args.limit} reached — 明日续跑（预算护栏）")
                break
            log(f"fetch {pid} ({cand['stratum']}, cites={cand.get('cited_by_count')})")
            try:
                res = acquire_source(pid, fetcher=fetcher, cache=cache)
            except Exception as e:
                log(f"  !! {pid} acquire raised {type(e).__name__}: {e} — 停批续跑")
                break
            n_new += 1
            if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
                log(f"  skip {pid}: {res.status.value} {res.detail or ''}")
                with (WORK / "fetch_fail.jsonl").open("a") as ff:
                    ff.write(
                        json.dumps(
                            {
                                "id": pid,
                                "status": res.status.value,
                                "detail": res.detail,
                            }
                        )
                        + "\n"
                    )
                continue
            assert res.entry is not None
            entry = res.entry.dir
            dest = CORPUS / pid
            dest.mkdir(parents=True, exist_ok=True)
            # 上次半程截尾的 extracted/ 与本次 copytree 合并会留幽灵文件——重抓前清掉
            stale = dest / "extracted"
            if stale.exists():
                shutil.rmtree(stale)
            shutil.copytree(entry / "extracted", stale)
            for raw in entry.glob("raw.*"):
                shutil.copy2(raw, dest / raw.name)
            meta = _merge_meta(entry, cand, dest)
            (dest / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
            mf.write(
                json.dumps(_manifest_row(cand, meta, dest), ensure_ascii=False) + "\n"
            )
            mf.flush()
            log(f"  ok {pid} v{res.resolved_version} → {dest.relative_to(ROOT)}")


def cmd_report(_args: argparse.Namespace) -> None:
    rows = benchlib.read_jsonl(MANIFEST_HOT)
    from collections import Counter

    strata = Counter(r["pick_reason"] for r in rows)
    fields = Counter(r.get("cat_group") for r in rows)
    yrs = Counter(str(r.get("yymm"))[:2] for r in rows)
    print(f"manifest_hot.jsonl: {len(rows)} 篇")
    print(f"  strata: {dict(strata)}")
    print(f"  yymm: {dict(sorted(yrs.items()))}")
    print(f"  top fields: {fields.most_common(8)}")
    n_tex = sum(r.get("n_tex") or 0 for r in rows)
    print(
        f"  Σ.tex: {n_tex}  Σbytes: {sum(r.get('bytes') or 0 for r in rows) / 1e6:.0f}MB"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("candidates")
    pc.add_argument("--n-cite", type=int, default=120)
    pc.add_argument("--n-recent", type=int, default=40)
    pc.add_argument("--seed", type=int, default=42)
    pf = sub.add_parser("fetch")
    pf.add_argument("--limit", type=int, default=85, help="单轮取源上限（日预算护栏）")
    sub.add_parser("report")
    args = ap.parse_args()
    {"candidates": cmd_candidates, "fetch": cmd_fetch, "report": cmd_report}[args.cmd](
        args
    )


if __name__ == "__main__":
    main()
