"""corpus_hot — OpenAlex 热层：免费渠道抽样 → 产品钉版取源 → 湖/清单双写。

Port of ``bench/py/corpus/build_hot_layer.py``（verbatim 语义，kernel
机制）。动机照原：corpus 均匀层长尾正确但与真实负载分布不匹配，hot 层
补「近期高热度」轴——扩展而非替换。

两个 stratum（原样）：
  hot-cite   OpenAlex ``locations.source.id=arXiv`` + from_publication_date
             ≥2024-01-01，cited_by_count 降序取头。
  hot-recent 同源 2025-06-01+ ``sample=`` 随机抽（新 LaTeX 惯用法兜底）。

取源走产品 ``acquire_source``（HEAD+GET，限速/预算纪律全在产品内），
不绕限流：``limit``=单轮尝试封顶（原 --limit 85）、``day_budget`` 走
``RatePolicy.daily_budget``（原 180）由持久化 RateLimiter 落
``lake/durable/hot/ratelimit.json``。

单件三段链（item ``corpus-hot``，eval=True 非标件）：

- ``candidates`` — OpenAlex 两路 → ``lake/durable/hot/candidates.jsonl``
  （跨 run provenance 台账，cli backup 覆盖 durable）。去重域照原并加
  湖册：manifest*.jsonl ids ∪ bench/corpus/{dirs} ∪ lake catalog idcs。
- ``fetch`` — 台账逐候选 ``lake.hydrate(fetch_fn)``：OK/HIT → cell
  extracted+raw 落盘 + manifest_hot 行；永久 miss（not_found/pdf_only/
  unknown_format/too_large）→ 空 cell + meta 记因（durable empty，免
  fetch-storm）；逐件瞬态（error/unpack_error）→ fetch_fail.jsonl 续走；
  全局限流（parked/budget_exhausted）或达 limit → 截断返 error。
- ``report`` — manifest_hot 计数汇总（strata/yymm/fields/Σtex/Σbytes），
  needs fetch ok——fetch 截断（error）时本格 skip，待收割封口才出终报。

与原驱动的刻意偏差：

- payload 新家 = 湖 cell（``lake/corpus/arxiv/{safe_id}/``），不再落
  ``bench/corpus/{id}/``；manifest_hot.jsonl 行口径不变（仍 repo tracked）。
- 截断返 ``error`` 不返 ``partial``：DONE 态跨 run dedup
  （kernel._last_outcome 不看 fp）会把续跑门焊死，且 partial→retriable
  是 §3.1 明禁——error+cat=budget 是唯一可续跑的非 fail 词。
- cell meta 的 provenance 字段避开 ``source`` 键（hydrate 自写
  ``source``=湖源维，meta_extra 后展开会盖掉）——原 meta["source"]
  "openalex+arxiv_eprint" 改记 ``provenance``。
- candidates 一跑 ok 即跨 run dedup——候选池冻结在首跑（有界收割语义，
  与原「candidates 手动重跑才更新」等价）。
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from kernel import events, idnorm, lake, paths
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "bench" / "corpus"
MANIFEST_HOT = CORPUS / "manifest_hot.jsonl"

UA = {
    "User-Agent": "texlate-hot-corpus/1.0 (research benchmark; mailto:bench@localhost)"
}
OPENALEX = "https://api.openalex.org/works"
ARXIV_SRC = "S4306400194"  # OpenAlex source id: arXiv (Cornell)

_NEW_ID_RX = re.compile(r"^(\d{4})\.\d{4,5}$")
_ABS_RX = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})", re.IGNORECASE)


class _HaltBatch(Exception):
    """全局限流（parked/budget_exhausted）——停批，本次 run 到此为止。"""


class _TransientMiss(Exception):
    """逐件瞬态 miss（error/unpack_error）——记 fetch_fail 续走下一候选。"""


def _durable() -> Path:
    d = paths.lake_durable_dir() / "hot"
    d.mkdir(parents=True, exist_ok=True)
    return d


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


def _seen_ids() -> set[str]:
    """候选去重域：manifest*.jsonl ids ∪ bench/corpus 目录 ∪ 湖册 idcs。"""
    seen: set[str] = set()
    for mf in CORPUS.glob("manifest*.jsonl"):
        for _ln, rec, _raw in events.iter_jsonl(mf):
            if isinstance(rec, dict) and rec.get("id"):
                seen.add(str(rec["id"]))
    if CORPUS.is_dir():
        seen |= {p.name for p in CORPUS.iterdir() if p.is_dir()}
    seen |= set(lake.LakeCatalog.load().rows())
    return seen


# --- candidates -----------------------------------------------------------------


def _candidates(ctx):
    n_cite = int(ctx.params["n_cite"])
    n_recent = int(ctx.params["n_recent"])
    seed = int(ctx.params["seed"])
    candidates_path = _durable() / "candidates.jsonl"

    seen = _seen_ids()
    out: list[dict] = []

    def _flush() -> None:
        # 逐页落盘——OpenAlex 翻页长，中途崩丢全部已收集候选代价大；
        # out 为空且已有候选文件时不覆盖（防 0 条抹掉好文件）
        if out or not candidates_path.exists():
            candidates_path.write_text(
                "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in out),
                encoding="utf-8",
            )

    def _mk(aid: str, stratum: str, w: dict) -> dict:
        return {
            "id": aid,
            "stratum": stratum,
            "cited_by_count": w.get("cited_by_count"),
            "oa_date": w.get("publication_date"),
            "title": (w.get("title") or "")[:200],
            "field": _field(w),
        }

    # -- hot-cite：近窗活跃 + cited_by_count 降序 --
    cursor = "*"
    while sum(1 for c in out if c["stratum"] == "hot-cite") < n_cite and cursor:
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
            out.append(_mk(aid, "hot-cite", w))
            if sum(1 for c in out if c["stratum"] == "hot-cite") >= n_cite:
                break
        cursor = (d.get("meta") or {}).get("next_cursor")
        _flush()
        if not d.get("results"):
            break

    # -- hot-recent：2025-06+ 随机抽样 --
    got_recent = 0
    for attempt in range(4):
        if got_recent >= n_recent:
            break
        d = _oa_get(
            {
                "filter": f"locations.source.id:{ARXIV_SRC},from_publication_date:2025-06-01",
                "sample": str(n_recent * 2),
                "seed": str(seed + attempt),
                "select": "id,title,cited_by_count,publication_date,locations,primary_topic",
            }
        )
        for w in d.get("results", []):
            aid = _arxiv_id(w)
            if not aid or not _NEW_ID_RX.match(aid) or aid in seen:
                continue
            seen.add(aid)
            out.append(_mk(aid, "hot-recent", w))
            got_recent += 1
            if got_recent >= n_recent:
                break
        _flush()

    _flush()
    n_cite_got = sum(1 for c in out if c["stratum"] == "hot-cite")
    ctx.emit(
        {
            "stage": "candidates",
            "metric": "hot_candidates",
            "hot_cite": n_cite_got,
            "hot_recent": got_recent,
            "total": len(out),
            "seen": len(seen),
            "ledger": str(candidates_path),
        }
    )
    return "ok"


# --- fetch ----------------------------------------------------------------------


def _cell_meta(entry_dir: Path, cand: dict, stage: Path) -> dict:
    """产品 meta.json + 语料层字段 → cell meta_extra（原 _merge_meta）。"""
    meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
    # 产品 meta 的 n_files 是 unpack 计数，而 hydrate 自写权威 payload
    # 计数（meta_extra 后展开会盖掉它）——弹出，cell meta 的 n_files 必须
    # 是湖口径，否则 is_complete 假阴性 → 重抓风暴。
    meta.pop("n_files", None)
    yymm = (cand["id"].split(".")[0])[:4]
    locate_main = ((meta.get("locate") or {}).get("main")) or None
    main_sha = None
    if locate_main and (stage / "extracted" / locate_main).exists():
        main_sha = hashlib.sha256(
            (stage / "extracted" / locate_main).read_bytes()
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
            "provenance": "openalex+arxiv_eprint",
        }
    )
    return meta


def _miss_meta(cand: dict, status: str, detail: str) -> dict:
    """永久 miss 的空 cell meta——自证为何空（durable empty 不是黑洞）。"""
    return {
        "acquire_status": status,
        "acquire_detail": detail,
        "layer": "hot",
        "stratum_cell": f"hot|{cand['stratum']}",
        "cat_group": cand.get("field") or "unknown",
        "channel": "arxiv_eprint",
        "cited_by_count": cand.get("cited_by_count"),
        "pick_reason": cand["stratum"],
        "title": cand.get("title"),
        "provenance": "openalex+arxiv_eprint",
    }


def _manifest_row(cand: dict, meta: dict, cell: Path) -> dict:
    """manifest_hot 行（原 _manifest_row，cell 布局版）。"""
    ext = cell / "extracted"
    n_tex = sum(1 for p in ext.rglob("*.tex")) if ext.is_dir() else 0
    raw_bytes = 0
    raw_dir = cell / "raw"
    if raw_dir.is_dir():
        raw_bytes = sum(p.stat().st_size for p in raw_dir.rglob("*") if p.is_file())
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
        "n_files": meta.get("n_files"),
        "n_tex": n_tex,
        "bytes": raw_bytes or meta.get("raw_size"),
        "cited_by_count": cand.get("cited_by_count"),
        "pick_reason": cand["stratum"],
    }


def _read_cell_meta(pid: str) -> dict:
    try:
        meta = json.loads(
            (lake.cell_dir(pid) / "meta.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _make_fetch_fn(cand: dict, slot: dict, fetcher, cache):
    """闭包 fetch_fn：cand 语义 + acquire 结果槽随 hydrate 进 cell。"""

    def _fn(idc: str, stage: Path) -> dict:
        from texlate.arxiv.fetch import AcquireStatus, acquire_source

        slot["ran"] = True
        res = acquire_source(idc, fetcher=fetcher, cache=cache)
        slot["acquire"] = res.status.value
        slot["detail"] = res.detail
        slot["ver"] = res.resolved_version
        if res.status in (AcquireStatus.PARKED, AcquireStatus.BUDGET):
            raise _HaltBatch(res.status.value)
        if res.status in (
            AcquireStatus.NOT_FOUND,
            AcquireStatus.PDF_ONLY,
            AcquireStatus.UNKNOWN_FORMAT,
            AcquireStatus.TOO_LARGE,
        ):
            return _miss_meta(cand, res.status.value, res.detail or "")
        if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
            raise _TransientMiss(res.status.value)
        assert res.entry is not None
        entry_dir = res.entry.dir
        shutil.copytree(entry_dir / "extracted", stage / "extracted")
        raw_dir = stage / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        for raw in entry_dir.glob("raw.*"):
            shutil.copy2(raw, raw_dir / raw.name)
        return _cell_meta(entry_dir, cand, stage)

    return _fn


def _fetch(ctx):
    from texlate.arxiv.cache import SourceCache
    from texlate.arxiv.fetch import Fetcher
    from texlate.arxiv.ratelimit import RateLimiter, RatePolicy
    from texlate.textutil.osutil import cache_root

    candidates_path = _durable() / "candidates.jsonl"
    if not candidates_path.exists():
        ctx.emit_note("candidates.jsonl missing — candidates stage torn", level="warn")
        return "error"
    cands = [
        c
        for _ln, c, _raw in events.iter_jsonl(candidates_path)
        if isinstance(c, dict) and c.get("id")
    ]
    done_ids = set()
    if MANIFEST_HOT.exists():
        done_ids = {
            str(r["id"])
            for _ln, r, _raw in events.iter_jsonl(MANIFEST_HOT)
            if isinstance(r, dict) and r.get("id")
        }

    limit = int(ctx.params["limit"])
    day_budget = int(ctx.params["day_budget"])
    limiter = RateLimiter(
        state_path=_durable() / "ratelimit.json",
        policy=RatePolicy(daily_budget=day_budget),
    )
    fetch_fail = _durable() / "fetch_fail.jsonl"

    def _ff(pid: str, status: str, detail) -> None:
        with fetch_fail.open("a", encoding="utf-8") as ff:
            ff.write(
                json.dumps(
                    {"id": pid, "status": status, "detail": detail},
                    ensure_ascii=False,
                )
                + "\n"
            )

    n_new = 0
    n_ok = n_fail = n_healed = n_skipped = 0
    truncated: dict | None = None
    with Fetcher(limiter=limiter) as fetcher:
        cache = SourceCache(cache_root() / "src")
        with MANIFEST_HOT.open("a", encoding="utf-8") as mf:
            for cand in cands:
                pid = str(cand["id"])
                if pid in done_ids:
                    n_skipped += 1
                    continue
                res_c = idnorm.canon_id(pid)
                idc = res_c.idc if res_c.ok else pid
                if lake.is_complete(idc):
                    # 半程截尾自愈：cell 已完整而 manifest 行未落——回补
                    # 不重抓（原 corpus/{id}/extracted 分支的湖版）。
                    meta = _read_cell_meta(idc)
                    mf.write(
                        json.dumps(
                            _manifest_row(cand, meta, lake.cell_dir(idc)),
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    mf.flush()
                    done_ids.add(pid)
                    n_healed += 1
                    continue
                if n_new >= limit:
                    truncated = {
                        "cat": "budget",
                        "msg": f"limit {limit} reached — 续跑",
                    }
                    break
                slot: dict = {}
                try:
                    lake.hydrate(
                        idc,
                        fetch_fn=_make_fetch_fn(cand, slot, fetcher, cache),
                        run_seq=ctx.rundir.run_seq,
                    )
                except _HaltBatch as hb:
                    _ff(pid, str(hb), slot.get("detail"))
                    n_fail += 1
                    truncated = {
                        "cat": "budget" if str(hb) == "budget_exhausted" else "parked",
                        "msg": f"{hb} — 限流到顶，停批续跑",
                    }
                    break
                except _TransientMiss as tm:
                    _ff(pid, str(tm), slot.get("detail"))
                    n_fail += 1
                    ctx.emit(
                        {
                            "stage": "fetch",
                            "metric": "hot_fetch",
                            "id": pid,
                            "stratum": cand["stratum"],
                            "acquire": str(tm),
                            "outcome": "transient_miss",
                        }
                    )
                    continue
                except Exception as exc:
                    truncated = {
                        "cat": "exception",
                        "msg": f"{pid} acquire raised "
                        f"{type(exc).__name__}: {exc} — 停批续跑",
                    }
                    break
                if slot.get("ran"):
                    n_new += 1
                if lake.is_complete(idc):
                    meta = _read_cell_meta(idc)
                    mf.write(
                        json.dumps(
                            _manifest_row(cand, meta, lake.cell_dir(idc)),
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    mf.flush()
                    done_ids.add(pid)
                    n_ok += 1
                    ctx.emit(
                        {
                            "stage": "fetch",
                            "metric": "hot_fetch",
                            "id": pid,
                            "stratum": cand["stratum"],
                            "acquire": slot.get("acquire"),
                            "version": slot.get("ver"),
                            "outcome": "ok",
                        }
                    )
                else:
                    # 永久 miss → durable empty cell（meta 记因，不再重抓）
                    meta = _read_cell_meta(idc)
                    st = str(meta.get("acquire_status") or "empty")
                    _ff(pid, st, meta.get("acquire_detail"))
                    n_fail += 1
                    ctx.emit(
                        {
                            "stage": "fetch",
                            "metric": "hot_fetch",
                            "id": pid,
                            "stratum": cand["stratum"],
                            "acquire": st,
                            "outcome": "permanent_miss",
                        }
                    )
    ctx.emit(
        {
            "stage": "fetch",
            "metric": "hot_fetch_summary",
            "attempts": n_new,
            "ok": n_ok,
            "fail": n_fail,
            "healed": n_healed,
            "skipped_done": n_skipped,
            "remaining": sum(1 for c in cands if str(c["id"]) not in done_ids),
            "requests_today": limiter.requests_today,
            "day_budget": day_budget,
        }
    )
    if truncated is not None:
        return {"status": "error", "errors": [truncated]}
    return "ok"


# --- report ---------------------------------------------------------------------


def _report(ctx):
    from collections import Counter

    rows = (
        [
            r
            for _ln, r, _raw in events.iter_jsonl(MANIFEST_HOT)
            if isinstance(r, dict) and r.get("id")
        ]
        if MANIFEST_HOT.exists()
        else []
    )
    strata = Counter(str(r.get("pick_reason")) for r in rows)
    fields = Counter(str(r.get("cat_group")) for r in rows)
    yrs = Counter(str(r.get("yymm"))[:2] for r in rows)
    n_tex = sum(r.get("n_tex") or 0 for r in rows)
    n_bytes = sum(r.get("bytes") or 0 for r in rows)
    ctx.emit(
        {
            "stage": "report",
            "metric": "hot_report",
            "rows": len(rows),
            "strata": dict(strata),
            "yymm": dict(sorted(yrs.items())),
            "top_fields": dict(fields.most_common(8)),
            "n_tex": n_tex,
            "mb": round(n_bytes / 1e6, 1),
        }
    )
    ctx.emit_note(
        f"manifest_hot: {len(rows)} 篇 strata={dict(strata)} "
        f"Σ.tex={n_tex} Σ={n_bytes / 1e6:.0f}MB"
    )
    return "ok"


spec = Spec(
    kind="corpus_hot",
    eval=True,
    items=[{"id": "corpus-hot"}],
    params={
        "n_cite": Param(type=int, default=120),
        "n_recent": Param(type=int, default=40),
        "limit": Param(type=int, default=85, fp=False),
        "day_budget": Param(type=int, default=180, fp=False),
        "seed": Param(type=int, default=42),
    },
    stages=[
        Stage(
            "candidates",
            _candidates,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "error": "retriable",
            },
        ),
        Stage(
            "fetch",
            _fetch,
            needs=[("candidates", {"ok"})],
            status_class={
                "ok": "terminal",
                "error": "retriable",
            },
        ),
        Stage(
            "report",
            _report,
            needs=[("fetch", {"ok"})],
            status_class={
                "ok": "terminal",
                "error": "retriable",
            },
        ),
    ],
    lake=True,
    prefetch=False,
    code_deps=["src/texlate/arxiv", "src/texlate/textutil/osutil.py"],
)
