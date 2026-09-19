#!/usr/bin/env python3
r"""daily_arxiv.py — arXiv 日更全量枚举+取源：RSS 公告集 → corpus_daily 物化。

设计文档 ``docs/research/arxiv/2026-09-19-daily-soak.md``。三子命令：

  enum     拉 rss.arxiv.org/rss/{cs,math} → 并集去重 →
           corpus_daily/manifest_{公告日}.jsonl + work_daily/rss/ 快照 +
           work_daily/enum-{date}.jsonl。批次身份 = 频道 pubDate（公告日），
           已有该日 manifest 即跳过（幂等，周末重跑安全——feed 冻结在周五）。
  fetch    对 manifest_{date} 行（默认 announce_type∈new,cross）走产品
           ``acquire_source``（钉版 HEAD+GET+unpack+locate），状态逐篇记
           work_daily/fetch-{date}.jsonl，OK 条目物化 corpus_daily/{id}/
           （meta.json+raw.*+extracted/，同 corpus_v3 布局）。断点续跑：
           fetch jsonl 已有 ok/pdf_only/… 终态的 id 跳过。
  report   汇总 enum+fetch 状态 → 终端 + work_daily/report-{date}.json。

漏跑回填（枚举缺口）：
  --backfill-list 用 /list/{archive}/pastweek?skip=N 枚举最近 ~5 公告日
  （RSS 只留最新一天）；>1 周缺口走 OAI-PMH set 日窗（v2 待接，先告警）。

限速：RatePolicy(daily_budget=8000)（实测日需 ~2400 发、周一峰 ~8000），
GAP 3.05s 单连接串行不变——~1200 篇/日 ≈ 2h，周一 ~6h，隔夜窗口。
本机 arxiv 必须走代理（直连 TLS 被重置）——enum/fetch 前置探测
rss.arxiv.org，不通即中止不烧预算。

用法:
  uv run python bench/py/corpus/daily_arxiv.py enum
  uv run python bench/py/corpus/daily_arxiv.py fetch --date 2026-09-18 [--limit 20]
  uv run python bench/py/corpus/daily_arxiv.py report --date 2026-09-18
Deps: uv venv（httpx）；texlate.arxiv.* 产品层。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import ARXIV_HOST, EXPORT_HOST, AcquireStatus, Fetcher, acquire_source
from texlate.arxiv.ratelimit import RateLimiter, RatePolicy

#: 日更抓取走 export 主站——bulk_data.md 明示「harvesting 请用 export.arxiv.org」，
#: 官方 designated harvest host + Fastly 缓存；www 作转移备份。
FETCH_HOSTS = (EXPORT_HOST, ARXIV_HOST)

CORPUS_DAILY = ROOT / "bench" / "corpus_daily"
WORK = ROOT / "bench" / "work_daily"
CACHE = Path.home() / ".cache" / "texlate" / "src"
RATE_STATE = WORK / "ratelimit.json"

UA = {"User-Agent": "texlate-daily-soak/1.0 (research benchmark; mailto:bench@localhost)"}
RSS_BASE = "https://rss.arxiv.org/rss"
LIST_BASE = "https://arxiv.org/list"
DAILY_BUDGET = 8000

_ID_RX = re.compile(r"oai:arXiv\.org:(\S+?)v(\d+)$")
_ABS_RX = re.compile(r"/abs/([0-9]{4}\.[0-9]{4,5})(?:v(\d+))?")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _get(url: str, timeout: float = 60.0, tries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)  # noqa: S310 -- 固定 https 端点
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
                return r.read()
        except (urllib.error.URLError, OSError) as e:
            last = e
            time.sleep(4 * (attempt + 1))
    assert last is not None
    raise last


def preflight() -> None:
    """代理/网络健康检查——不通直接中止，不进 fetch 烧预算。"""
    try:
        body = _get(f"{RSS_BASE}/cs.CL", timeout=30, tries=1)
    except Exception as e:
        log(f"preflight FAILED: rss.arxiv.org unreachable ({e}) — 检查代理")
        sys.exit(3)
    if b"<rss" not in body[:400]:
        log("preflight FAILED: rss.arxiv.org 返回非 RSS——检查代理")
        sys.exit(3)


def _text(el: ET.Element, tag: str) -> str:
    for child in el:
        if child.tag.rsplit("}", 1)[-1] == tag:
            return (child.text or "").strip()
    return ""


def _texts(el: ET.Element, tag: str) -> list[str]:
    return [
        (c.text or "").strip() for c in el if c.tag.rsplit("}", 1)[-1] == tag and c.text
    ]


def parse_feed(xml_bytes: bytes) -> tuple[str, list[dict]]:
    """RSS → (公告日 YYYY-MM-DD, items)。pubDate 取频道级。"""
    root = ET.fromstring(xml_bytes)
    chan = root.find("channel")
    assert chan is not None
    pub_raw = _text(chan, "pubDate")
    day = parsedate_to_datetime(pub_raw).date().isoformat() if pub_raw else ""
    items: list[dict] = []
    for it in chan.findall("item"):
        guid = _text(it, "guid")
        m = _ID_RX.search(guid)
        if not m:
            continue
        cats = _texts(it, "category")
        items.append(
            {
                "id": m.group(1),
                "ver": int(m.group(2)),
                "type": _text(it, "announce_type"),
                "primary": cats[0] if cats else "",
                "cats": cats,
                "license": _text(it, "rights"),
                "title": " ".join(_text(it, "title").split()),
                "pubDate": _text(it, "pubDate"),
            }
        )
    return day, items


def cat_group(primary: str) -> str:
    """主类目 → cat_group slug（corpus_v3 口径：archive 前缀）。"""
    return primary.split(".", 1)[0] if primary else "other"


def cmd_enum(args: argparse.Namespace) -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "rss").mkdir(parents=True, exist_ok=True)
    CORPUS_DAILY.mkdir(parents=True, exist_ok=True)
    feeds = [f.strip() for f in args.feeds.split(",") if f.strip()]
    days: dict[str, dict] = {}  # date → {id → row}
    for feed in feeds:
        src = args.from_file.get(feed) if args.from_file else None
        if src:
            body = Path(src).read_bytes()
        else:
            body = _get(f"{RSS_BASE}/{feed}")
            (WORK / "rss" / f"{feed}-{int(time.time())}.xml").write_bytes(body)
        day, items = parse_feed(body)
        log(f"rss/{feed}: {len(items)} items, announce day {day or '?'}")
        if not day or not items:
            # 非公告日 feed 空——记空 enum 戳（区分「跑了没货」vs「没跑」），不写 manifest
            if day:
                (WORK / f"enum-{day}.empty").write_text(
                    f"{day}: feeds polled, 0 items\n", encoding="utf-8"
                )
            continue
        slot = days.setdefault(day, {})
        for it in items:
            row = slot.get(it["id"])
            if row is None:
                row = dict(it)
                row["feeds"] = [feed]
                row["types"] = {it["type"]}
                slot[it["id"]] = row
            else:
                row["feeds"].append(feed)
                row["types"].add(it["type"])
                # new 优先于 cross——主库公告语义更真
                if it["type"] == "new" and row["type"] != "new":
                    row["type"] = "new"
                    row["primary"] = it["primary"]
                    row["cats"] = it["cats"]
    n_written = 0
    for day in sorted(days):
        mf = CORPUS_DAILY / f"manifest_{day}.jsonl"
        enum_fp = WORK / f"enum-{day}.jsonl"
        if mf.exists() and not args.force:
            log(f"manifest_{day}.jsonl 已存在——跳过（--force 重写）")
            continue
        rows = []
        for pid, it in sorted(days[day].items()):
            rows.append(
                {
                    "id": pid,
                    "ver": it["ver"],
                    "era": "new",
                    "yymm": pid.split(".", 1)[0].replace("/", "-"),
                    "layer": day,
                    "channel": "arxiv_eprint",
                    "announce_type": it["type"],
                    "types_seen": sorted(it["types"]),
                    "feeds": it["feeds"],
                    "primary": it["primary"],
                    "cats": it["cats"],
                    "cat_group": cat_group(it["primary"]),
                    "license": it["license"],
                    "title": it["title"],
                }
            )
        tmp = mf.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp.replace(mf)
        enum_fp.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
        n_written += len(rows)
        log(f"manifest_{day}.jsonl: {len(rows)} 篇（并集去重后）")
    log(f"enum done: {n_written} rows")
    return 0


def _load_manifest(date: str) -> list[dict]:
    mf = CORPUS_DAILY / f"manifest_{date}.jsonl"
    if not mf.exists():
        log(f"manifest_{date}.jsonl 不存在——先跑 enum（或 --backfill-list）")
        sys.exit(2)
    return [
        json.loads(line) for line in mf.read_text(encoding="utf-8").splitlines() if line
    ]


def _fetch_done(status_fp: Path) -> dict[str, str]:
    """fetch jsonl → {id: 末次 status}——终态跳过，error/budget 重试。"""
    done: dict[str, str] = {}
    if not status_fp.exists():
        return done
    for line in status_fp.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        done[r["id"]] = r["status"]
    # 终态集：ok/pdf_only/unknown/not_found/too_large 不重试；error/budget/parked 可续
    terminal = {
        AcquireStatus.OK.value,
        AcquireStatus.PDF_ONLY.value,
        AcquireStatus.UNKNOWN_FORMAT.value,
        AcquireStatus.NOT_FOUND.value,
        AcquireStatus.TOO_LARGE.value,
        AcquireStatus.UNPACK_ERROR.value,
    }
    return {k: v for k, v in done.items() if v in terminal}


def _materialize(pid: str, entry_dir: Path) -> None:
    # 硬链接而非拷贝——缓存条目即语料内容，双视图零额外空间；缓存清理后语料仍持有数据
    dst = CORPUS_DAILY / pid
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(entry_dir, dst, copy_function=os.link)


def cmd_fetch(args: argparse.Namespace) -> int:
    preflight()
    rows = _load_manifest(args.date)
    want_types = set(args.types.split(","))
    pool = [
        r
        for r in rows
        if r.get("announce_type") in want_types or r.get("type") in want_types
    ]
    status_fp = WORK / f"fetch-{args.date}.jsonl"
    done = _fetch_done(status_fp)
    todo = [r for r in pool if r["id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    log(
        f"fetch {args.date}: manifest={len(rows)} pool={len(pool)} done={len(done)} todo={len(todo)}"
    )
    if not todo:
        return 0
    cache = SourceCache(CACHE)
    limiter = RateLimiter(
        RATE_STATE, policy=RatePolicy(daily_budget=args.budget)
    )
    counts: dict[str, int] = {}
    with status_fp.open("a", encoding="utf-8") as out, Fetcher(
        limiter=limiter, hosts=FETCH_HOSTS
    ) as fx:
        for i, row in enumerate(todo, 1):
            pid, ver = row["id"], row.get("ver")
            t0 = time.monotonic()
            try:
                res = acquire_source(
                    pid, version=ver, fetcher=fx, cache=cache
                )
            except Exception as e:  # noqa: BLE001 -- 逐篇记状态，不让单篇炸批
                res_status, detail, entry = "error", f"raise:{e}", None
            else:
                res_status, detail, entry = res.status.value, res.detail, res.entry
            rec = {
                "id": pid,
                "ver": ver,
                "status": res_status,
                "detail": detail or "",
                "secs": round(time.monotonic() - t0, 1),
                "ts": datetime.now(UTC).strftime("%H:%M:%S"),
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            counts[res_status] = counts.get(res_status, 0) + 1
            if res_status == AcquireStatus.OK.value and entry is not None:
                try:
                    _materialize(pid, entry.dir)
                except OSError as e:
                    log(f"  {pid} materialize failed: {e}")
            if i % 25 == 0 or i == len(todo):
                log(f"  [{i}/{len(todo)}] {counts}")
    log(f"fetch done: {counts}")
    return 0


def cmd_backfill_list(args: argparse.Namespace) -> int:
    """pastweek 页枚举补漏——/list/{archive}/pastweek?skip=N 全量分页。"""
    feeds = [f.strip() for f in args.feeds.split(",") if f.strip()]
    found: dict[str, dict[str, dict]] = {}
    for feed in feeds:
        for skip in range(0, 4000, 50):
            body = _get(f"{LIST_BASE}/{feed}/pastweek?skip={skip}").decode(
                "utf-8", "replace"
            )
            day_secs = re.findall(
                r"<h3[^>]*>\s*\w{3}, (\d{1,2} \w{3} \d{4}) \((\d+) entries", body
            )
            if not day_secs and skip == 0:
                # 兼容 "showing first 50 of N entries" 文案
                day_secs = re.findall(
                    r"<h3[^>]*>\s*\w{3}, (\d{1,2} \w{3} \d{4}) \(showing first \d+ of (\d+) entries", body
                )
            if not day_secs:
                break
            # 当前页属于哪个公告日：h3 之后逐条归属
            blocks = re.split(r"<h3[^>]*>", body)[1:]
            for blk in blocks:
                dm = re.match(r"\s*\w{3}, (\d{1,2} \w{3} \d{4})", blk)
                if not dm:
                    continue
                day = datetime.strptime(dm.group(1), "%d %b %Y").date().isoformat()
                slot = found.setdefault(day, {})
                for m in _ABS_RX.finditer(blk):
                    pid = m.group(1)
                    slot.setdefault(pid, {"id": pid, "feeds": [feed]})
            # 末页：条目数 <50 即停
            n_ids = len(re.findall(r"/abs/\d{4}\.\d{4,5}", body))
            if n_ids < 50:
                break
            time.sleep(3.05)
    for day in sorted(found):
        log(f"pastweek {day}: {len(found[day])} ids（cs+math 分列待合并语义见文档）")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    rows = _load_manifest(args.date) if (CORPUS_DAILY / f"manifest_{args.date}.jsonl").exists() else []
    status_fp = WORK / f"fetch-{args.date}.jsonl"
    stats: dict[str, int] = {}
    n = 0
    if status_fp.exists():
        for line in status_fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            stats[r["status"]] = stats.get(r["status"], 0) + 1
            n += 1
    by_type: dict[str, int] = {}
    by_group: dict[str, int] = {}
    for r in rows:
        by_type[r.get("announce_type", "?")] = by_type.get(r.get("announce_type", "?"), 0) + 1
        by_group[r.get("cat_group", "?")] = by_group.get(r.get("cat_group", "?"), 0) + 1
    rep = {
        "date": args.date,
        "manifest_rows": len(rows),
        "by_type": by_type,
        "by_cat_group": dict(sorted(by_group.items())),
        "fetch_attempts": n,
        "fetch_status": dict(sorted(stats.items())),
        "materialized": len([p for p in CORPUS_DAILY.iterdir() if p.is_dir()])
        if CORPUS_DAILY.exists()
        else 0,
    }
    out = WORK / f"report-{args.date}.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    """清 clean 格的 work 目录——磁盘紧俏（单日 ~21G），失败/异常格保留供 triage。"""
    results = ROOT / "bench" / "results" / f"soak-{args.date}"
    records = results / "records"
    work = results / "work"
    if not records.is_dir() or not work.is_dir():
        log(f"prune {args.date}: {results} 无 records/work——跳过")
        return 0
    clean_status = {"clean", "ok", "skip"}
    keep: set[str] = set()
    for fp in records.glob("*.jsonl"):
        for line in fp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("status") not in clean_status:
                keep.add(r["id"])
    n_del, freed = 0, 0
    for d in work.iterdir():
        if not d.is_dir() or d.name in keep:
            continue
        sz = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        shutil.rmtree(d)
        n_del += 1
        freed += sz
    log(f"prune {args.date}: 删 {n_del} 个 clean work 目录，留 {len(keep)} 个异常格，释放 {freed / 1e9:.1f}G")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="arXiv 日更全量枚举+取源（CS+math soak）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_e = sub.add_parser("enum", help="RSS 公告集 → manifest_{date}.jsonl")
    p_e.add_argument("--feeds", default="cs,math")
    p_e.add_argument("--force", action="store_true")
    p_e.add_argument(
        "--from-file",
        type=lambda s: dict(kv.split("=", 1) for kv in s.split(",")),
        default=None,
        help="feed=path 快照回放（测试/补录），如 cs=a.xml,math=b.xml",
    )
    p_f = sub.add_parser("fetch", help="manifest → acquire_source 物化")
    p_f.add_argument("--date", required=True, help="公告日 YYYY-MM-DD")
    p_f.add_argument("--types", default="new,cross")
    p_f.add_argument("--limit", type=int, default=0)
    p_f.add_argument("--budget", type=int, default=DAILY_BUDGET)
    p_b = sub.add_parser("backfill", help="pastweek 页枚举补漏（≤5 公告日）")
    p_b.add_argument("--feeds", default="cs,math")
    p_r = sub.add_parser("report", help="日度汇总")
    p_r.add_argument("--date", required=True)
    p_p = sub.add_parser("prune", help="清 clean 格 work 目录（留异常格供 triage）")
    p_p.add_argument("--date", required=True)
    args = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    if args.cmd == "enum":
        return cmd_enum(args)
    if args.cmd == "fetch":
        return cmd_fetch(args)
    if args.cmd == "backfill":
        return cmd_backfill_list(args)
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "prune":
        return cmd_prune(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
