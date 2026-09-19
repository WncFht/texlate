#!/usr/bin/env python3
"""corpus_v2 builder: download arXiv e-print source packages for the
stratified id lists, unpack per arxiv-layer.md §3, and lay down
bench/corpus/{id}/ + manifest_v2.jsonl + MANIFEST_v2.md
(2026-09-20 起 v2 层并入统一根 corpus).

Deps: stdlib only (system python3).

Discipline: >=3.05s between arxiv.org requests, strictly serial, descriptive
UA; any 429 -> stop, persist progress, report. Request budget <=448.

Per-id dir layout (old-style ids nest as {archive}/{name}):
  raw.tar.gz | raw.gz     original package bytes (replayable)
  extracted/              filtered tree (single-file .gz -> one .tex)
  meta.json               per-paper metadata

State: progress.json holds request counter + all records; rerun skips done.
"""

import contextlib
import csv
import gzip
import hashlib
import io
import json
import os
import random
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

ROOT = os.path.dirname(  # bench/py/corpus/build_corpus_v2.py → repo root
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
)
DATA = os.path.join(ROOT, "bench/corpus")
BENCH_CORPUS = DATA  # v1 已并入 corpus（2026-09-20 七库合一）
MANIFEST_MD = os.path.join(ROOT, "bench/corpus/MANIFEST_v2.md")
PROGRESS = os.path.join(DATA, "progress_v2.json")
MANIFEST_JSONL = os.path.join(DATA, "manifest_v2.jsonl")
LOG = os.path.join(DATA, "build_v2.log")
SAMPLE_JSONL = os.path.join(ROOT, "tmp/exp/arxiv-serial2/sample.jsonl")
COV_JSONL = os.path.join(ROOT, "tmp/exp/arxiv-serial2/arxiv_cov.jsonl")
MONTHLY_CSV = os.path.join(ROOT, "tmp/exp/arxiv-serial2/arxiv_monthly.csv")

UA = "texlate/0.1-dev (+https://github.com/wncfht/texlate; mailto:research@texlate.dev)"
GAP = 3.3
MAX_REQ = 450  # spec hard budget
DL_CAP = 150 * 1024 * 1024  # refuse >150MB packages
TOT_CAP = 512 * 1024 * 1024  # extracted total
FILE_CAP = 100 * 1024 * 1024  # single member
MEMBER_CAP = 20000
TARGET = 300

_last = [0.0]
# Local proxy's shared exit IP gets intermittently WAF'd by arXiv (-> flaky
# minute-scale 406s on /src/). Direct egress measured clean — bypass it.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
state = {"req": 0, "records": {}, "attempts": {}, "phase_b_done": False}


class Stop429(Exception):
    pass


class OutOfBudget(Exception):
    pass


def log(msg):
    line = f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {msg}"
    print(line, file=sys.stderr, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def save_progress():
    tmp = PROGRESS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, PROGRESS)


def load_progress():
    if os.path.exists(PROGRESS):
        with open(PROGRESS) as f:
            state.update(json.load(f))


def throttle():
    dt = time.time() - _last[0]
    if dt < GAP:
        time.sleep(GAP - dt)
    _last[0] = time.time()


def request(method, url):
    """One HTTP request. Counts budget. 429 -> Stop429."""
    if state["req"] >= MAX_REQ:
        raise OutOfBudget
    throttle()
    state["req"] += 1
    # NB: urllib's default "Accept-Encoding: identity" trips arXiv's WAF -> 406.
    req = urllib.request.Request(  # noqa: S310  # URL 是脚本内部构造的 arxiv 固定端点
        url,
        method=method,
        headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip"},
    )
    try:
        with _opener.open(req, timeout=90) as r:
            if method == "HEAD":
                return r.status, r.headers, b""
            return r.status, r.headers, r.read(DL_CAP + 1)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise Stop429 from e
        # keep a snippet of error body for diagnosis (e.g. WAF page vs arXiv app)
        try:
            snippet = e.read(400)
        except Exception:
            snippet = b""
        h = dict(e.headers.items()) if e.headers else {}
        if snippet:
            h["x-err-body"] = snippet.decode("utf8", "replace")[:200]
        return e.code, h, b""


TRANSIENT = {406, 500, 502, 503, 504}
# NB: arXiv emits flaky minute-scale 406 windows on /src/; inline retry inside
# the window wastes quota — callers defer such ids to a later sweep instead.


def request_retry(method, url):
    """One retry on transport error only; transient HTTP left to the caller."""
    try:
        return request(method, url)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log(f"  transport err {e}; retry once in 10s")
        time.sleep(10)
        try:
            return request(method, url)
        except (urllib.error.URLError, TimeoutError, OSError) as e2:
            return -1, {"x-exc": str(e2)}, b""


def cd_filename(headers):
    cd = headers.get("Content-Disposition", "") if headers else ""
    m = re.search(r'filename="?([^";]+)', cd)
    return m.group(1) if m else ""


def cd_version(cd):
    m = re.search(r"v(\d+)\.(?:tar\.gz|gz|pdf)$", cd or "")
    return int(m.group(1)) if m else None


def norm_member(name):
    """Normalize tar member name -> relative path, or None to reject."""
    if "\x00" in name:
        return None
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts:
        return ""
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def extract(payload, dest):
    """payload = uncompressed tar bytes. Returns (n_files, tex_files, bytes, warnings)."""
    warnings = []
    seen = {}  # lower -> actual rel
    n_files = tex_files = 0
    total = 0
    n_members = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as tf:
        members = tf.getmembers()
        if len(members) > MEMBER_CAP:
            msg = f"too_many_members:{len(members)}"
            raise ValueError(msg)
        for m in members:
            n_members += 1
            rel = norm_member(m.name)
            if rel is None:
                warnings.append(f"reject_path:{m.name}")
                continue
            if rel == "":
                continue
            if m.mode and (m.mode & 0o6000):
                warnings.append(f"reject_setuid:{rel}")
                continue
            target = os.path.join(dest, rel)
            if m.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            if m.issym() or m.islnk():
                # keep only links resolving inside the tree
                if m.issym():
                    base = os.path.dirname(rel)
                    joined = os.path.normpath(os.path.join(base, m.linkname))
                else:  # hardlink: archive-root relative
                    joined = os.path.normpath(m.linkname)
                joined = joined.replace(os.sep, "/")
                if joined.startswith(("..", "/")) or os.path.isabs(joined):
                    warnings.append(f"reject_link:{rel}->{m.linkname}")
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                low = rel.lower()
                if low in seen:
                    rel = rel + f"~dup{n_members}"
                    target = os.path.join(dest, rel)
                    low = rel.lower()
                    warnings.append(f"dup_member:{m.name}")
                seen[low] = rel
                if m.issym():
                    if os.path.lexists(target):
                        os.remove(target)
                    os.symlink(m.linkname, target)
                    warnings.append(f"link_kept:{rel}->{m.linkname}")
                else:
                    src = os.path.join(dest, joined)
                    if os.path.isfile(src):
                        with open(src, "rb") as fi, open(target, "wb") as fo:
                            fo.write(fi.read())
                        warnings.append(f"hardlink_materialized:{rel}->{joined}")
                    else:
                        warnings.append(f"hardlink_dangling:{rel}->{joined}")
                        continue
                n_files += 1
                continue
            if not m.isreg():
                warnings.append(f"reject_special:{rel}")
                continue
            if m.size > FILE_CAP:
                warnings.append(f"reject_filesize:{rel}:{m.size}")
                continue
            if total + m.size > TOT_CAP:
                warnings.append(f"reject_totalcap:{rel}")
                continue
            # case-fold / exact dup handling
            low = rel.lower()
            if low in seen and seen[low] != rel:
                stem, ext = os.path.splitext(rel)
                k = 2
                while f"{stem}~c{k}{ext}".lower() in seen:
                    k += 1
                newrel = f"{stem}~c{k}{ext}"
                warnings.append(f"casefold_rename:{rel}->{newrel}")
                rel = newrel
                low = rel.lower()
                target = os.path.join(dest, rel)
            elif low in seen:
                warnings.append(f"dup_member_overwrite:{rel}")
            seen[low] = rel
            fobj = tf.extractfile(m)
            data = fobj.read() if fobj else b""
            os.makedirs(os.path.dirname(target) or dest, exist_ok=True)
            with open(target, "wb") as fo:
                fo.write(data)
            total += len(data)
            n_files += 1
            if rel.lower().endswith((".tex", ".ltx")):
                tex_files += 1
    return n_files, tex_files, total, warnings


def id_dir(arxiv_id):
    return os.path.join(DATA, arxiv_id)  # old-style id carries archive/name


def process_package(arxiv_id, era, archive, yymm, source_tag, url, cd_hint=None):
    """GET url, classify, unpack, write dir + record. Returns record dict."""
    rec = {
        "id": arxiv_id,
        "era": era,
        "archive": archive,
        "yymm": yymm,
        "source": source_tag,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    st, hdrs, body = request_retry("GET", url)
    rec["http_status"] = st
    rec["cd_filename"] = cd_filename(hdrs) or cd_hint or ""
    ver = cd_version(rec["cd_filename"])
    rec["resolved_version"] = ver
    if st == 404:
        rec["status"] = "not_found"
        return rec
    if st != 200:
        rec["status"] = f"fetch_error:{st}"
        return rec
    if len(body) > DL_CAP:
        rec["status"] = "too_large"
        rec["bytes"] = len(body)
        return rec
    if hdrs and hdrs.get("Content-Encoding", "").lower() == "gzip":
        with contextlib.suppress(OSError):
            body = gzip.decompress(body)
    rec["bytes"] = len(body)
    rec["raw_sha256"] = hashlib.sha256(body).hexdigest()
    d = id_dir(arxiv_id)
    rec["dir"] = os.path.relpath(d, DATA)
    ext_dir = os.path.join(d, "extracted")

    # --- magic classify ---
    if body[:4] == b"%PDF":
        rec["status"] = "pdf_only"
        return rec
    if body[:2] != b"\x1f\x8b":
        rec["status"] = "unknown_format"
        rec["head_hex"] = body[:16].hex()
        return rec
    try:
        gzf = gzip.GzipFile(fileobj=io.BytesIO(body))
        payload = gzf.read(TOT_CAP + 1)
    except (OSError, EOFError) as e:
        rec["status"] = f"unpack_error:gunzip:{e}"
        return rec
    if len(payload) > TOT_CAP:
        rec["status"] = "too_large_inflated"
        return rec

    os.makedirs(ext_dir, exist_ok=True)
    if len(payload) > 512 and payload[257:262] == b"ustar":
        rec["format"] = "tar"
        raw_name = "raw.tar.gz"
        try:
            n_files, tex_files, total, warnings = extract(payload, ext_dir)
        except Exception as e:
            rec["status"] = f"unpack_error:{e}"
            return rec
        rec["warnings"] = warnings
        rec["n_files"] = n_files
        rec["tex_files"] = tex_files
        rec["extracted_bytes"] = total
    else:
        rec["format"] = "single_gz"
        raw_name = "raw.gz"
        stem = re.sub(r"^arXiv-", "", rec["cd_filename"])
        stem = stem[:-3] if stem.endswith(".gz") else arxiv_id.replace("/", "")
        name = stem + ".tex"
        with open(os.path.join(ext_dir, name), "wb") as f:
            f.write(payload)
        rec["n_files"] = 1
        rec["tex_files"] = 1
        rec["extracted_bytes"] = len(payload)
    with open(os.path.join(d, raw_name), "wb") as f:
        f.write(body)
    rec["raw_file"] = raw_name
    rec["status"] = "ok"
    meta = {
        "arxiv_id": arxiv_id,
        "resolved_version": ver,
        "era": era,
        "archive": archive,
        "yymm": yymm,
        "cd_filename": rec["cd_filename"],
        "raw_sha256": rec["raw_sha256"],
        "raw_file": raw_name,
        "format": rec["format"],
        "n_files": rec["n_files"],
        "tex_files": rec["tex_files"],
        "bytes": rec["bytes"],
        "extracted_bytes": rec["extracted_bytes"],
        "fetched_at": rec["fetched_at"],
        "warnings": rec.get("warnings", []),
        "source": source_tag,
    }
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return rec


def existing_ids():
    out = set()
    for d in os.listdir(BENCH_CORPUS):
        p = os.path.join(BENCH_CORPUS, d)
        if not os.path.isdir(p):
            continue
        if "/" not in d and re.match(
            r"^(hep|astro|cond|math|physics|nlin|nucl|quant|adap|alg|comp|funct|gr-|solv|chao|patt|atom)",
            d,
        ):
            for sub in os.listdir(p):
                if os.path.isdir(os.path.join(p, sub)):
                    out.add(f"{d}/{sub}")
        else:
            out.add(d)
    return out


def build_worklist():
    have = existing_ids()
    work = []
    for line in open(SAMPLE_JSONL):
        r = json.loads(line)
        cd = r.get("cd") or ""
        if (
            r.get("status") == 200
            and re.search(r"\.(tar\.gz|gz)$", cd)
            and not cd.endswith(".pdf")
        ):
            aid = r["arxiv_id"]
            if aid in have:
                continue
            ver = cd_version(cd)
            url = (
                f"https://arxiv.org/src/{aid}v{ver}"
                if ver
                else f"https://arxiv.org/src/{aid}"
            )
            work.append(
                {
                    "id": aid,
                    "era": r.get("era"),
                    "archive": r.get("archive"),
                    "yymm": r.get("yymm"),
                    "tag": "serial2",
                    "url": url,
                    "cd": cd,
                }
            )
            have.add(aid)
    for line in open(COV_JSONL):
        r = json.loads(line)
        if r["eprint"].get("kind") == "source_gz" and r["eprint"].get("status") == 200:
            aid = r["id"]
            if aid in have:
                continue
            work.append(
                {
                    "id": aid,
                    "era": "new",
                    "archive": None,
                    "yymm": r.get("month"),
                    "tag": "cov",
                    "url": f"https://arxiv.org/src/{aid}",
                    "cd": None,
                }
            )
            have.add(aid)
    return work, have


def fill_slots(have):
    """New-style id sampler, 2018-2026 round-robin by year."""
    rng = random.Random(202609142)  # 语料抽样不是安全用途
    months = {}
    with open(MONTHLY_CSV) as f:
        for row in csv.DictReader(f):
            months[row["month"]] = int(row["submissions"])
    years = list(range(2018, 2027))
    ym = {y: [m for m in range(1, 13) if f"{y}-{m:02d}" in months] for y in years}
    i = 0
    while True:
        y = years[i % len(years)]
        i += 1
        mm = rng.choice(ym[y])
        key = f"{y}-{mm:02d}"
        n = rng.randint(1, months[key])
        aid = f"{y % 100:02d}{mm:02d}.{n:05d}"
        if aid in have:
            continue
        have.add(aid)
        yield aid, key, y


def ok_count():
    return sum(1 for r in state["records"].values() if r["status"] == "ok")


def finalize():
    """Rewrite manifest.jsonl + MANIFEST.md from records."""
    recs = sorted(
        state["records"].values(),
        key=lambda r: (r.get("yymm") or "", r.get("id") or r.get("arxiv_id") or ""),
    )
    with open(MANIFEST_JSONL, "w") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
    oks = [r for r in recs if r["status"] == "ok"]
    n_tex = sum(r.get("tex_files", 0) for r in oks)
    n_files = sum(r.get("n_files", 0) for r in oks)
    tot_bytes = sum(r.get("bytes", 0) for r in oks)
    from collections import Counter

    disc = Counter(r["status"].split(":")[0] for r in recs if r["status"] != "ok")

    def human2(n):
        if n < 1024:
            return f"{n}B"
        if n < 1024 * 1024:
            return f"{n / 1024:.0f}K"
        return f"{n / 1024 / 1024:.1f}M"

    lines = [
        "# Corpus v2 Manifest — arXiv 分层随机抽样源码语料",
        "",
        "分层随机抽样的 arXiv e-print 源码（`arxiv.org/src/{id}v{N}` 钉版本下载，字节原样存 `raw.*`，过滤后树存 `extracted/`）。",
        "数据在 `bench/corpus_v2/`（不入库），本目录只有此清单。抽样与解包口径见 `bench/PROTOCOL.md` / `docs/research/arxiv/layer.md` §3。",
        "旧式 ID 按 `archive/name` 嵌套（如 `hep-th/0212074/`）。版本号为下载时 content-disposition 解析值，可复现。",
        "",
        f"- 入库 **{len(oks)}** 篇 · {n_files} 文件 · {n_tex} 个 .tex · 原始包共 {human2(tot_bytes)}",
        f"- 打包形式：tar {sum(1 for r in oks if r.get('format') == 'tar')} · 单文件 .gz {sum(1 for r in oks if r.get('format') == 'single_gz')}",
        f"- 年代：old-style {sum(1 for r in oks if r.get('era') == 'old')} · new-style {sum(1 for r in oks if r.get('era') == 'new')}",
        f"- 来源批次：serial2 {sum(1 for r in oks if r.get('source') == 'serial2')} · coverage {sum(1 for r in oks if r.get('source') == 'cov')} · 补充抽样 {sum(1 for r in oks if r.get('source') == 'fill')}",
        f"- 丢弃：{', '.join(f'{k} {v}' for k, v in sorted(disc.items())) or '无'}（另有预检已知 pdf_only 未下载：serial2 6 篇、cov 8 篇）",
        f"- 请求用量：{state['req']}（预算 450）",
        "",
        "| ID@版本 | era | archive | yymm | 格式 | 文件数 | .tex | 原始包 | 批次 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in oks:
        ver = f"v{r['resolved_version']}" if r.get("resolved_version") else "v?"
        lines.append(
            f"| {r['id']}@{ver} | {r.get('era') or ''} | {r.get('archive') or '—'} | {r.get('yymm') or ''} "
            f"| {r.get('format') or ''} | {r.get('n_files', 0)} | {r.get('tex_files', 0)} "
            f"| {human2(r.get('bytes', 0))} | {r.get('source') or ''} |"
        )
    os.makedirs(os.path.dirname(MANIFEST_MD), exist_ok=True)
    with open(MANIFEST_MD, "w") as f:
        f.write("\n".join(lines) + "\n")
    return len(oks), n_tex, disc


def is_transient(rec):
    s = rec.get("status", "")
    if s.startswith("fetch_error:"):
        try:
            return int(s.split(":", 1)[1]) in TRANSIENT
        except ValueError:
            return False
    if s.startswith("head_error:"):
        try:
            return int(s.split(":", 1)[1]) in TRANSIENT
        except ValueError:
            return False
    return False


def fetch_one(w):
    """Process one work item; defer transient failures (retry in sweeps)."""
    aid = w["id"]
    att = state["attempts"].get(aid, 0) + 1
    state["attempts"][aid] = att
    rec = process_package(
        aid, w["era"], w["archive"], w["yymm"], w["tag"], w["url"], w["cd"]
    )
    rec["attempts"] = att
    state["records"][aid] = rec
    save_progress()
    return rec


def main():
    load_progress()
    work, have = build_worklist()
    deferred = []  # transient-failed items -> swept after main passes
    log(f"worklist {len(work)} known-positive; requests so far {state['req']}")
    try:
        for w in work:
            prev = state["records"].get(w["id"])
            if prev and prev["status"] == "ok":
                continue
            rec = fetch_one(w)
            if is_transient(rec) and rec["attempts"] < 4:
                deferred.append(w)
            log(
                f"A {w['id']} -> {rec['status']}"
                + (
                    f" v{rec.get('resolved_version')} {rec.get('format')} files={rec.get('n_files')}"
                    if rec["status"] == "ok"
                    else ""
                )
                + f" [req={state['req']} ok={ok_count()}]"
            )

        # ---- phase B: top-up sampling ----
        have.update(state["records"].keys())  # don't resample already-seen ids
        have.update(w["id"] for w in deferred)
        need = TARGET - ok_count()
        log(f"phase B need {need}")
        sampler = fill_slots(have)
        misses = 0
        while ok_count() < TARGET and misses < 400:
            aid, key, _year = next(sampler)
            st, hdrs, _ = request_retry("HEAD", f"https://arxiv.org/src/{aid}")
            if st == 404:
                state["records"][aid] = {
                    "id": aid,
                    "era": "new",
                    "archive": None,
                    "yymm": key,
                    "source": "fill",
                    "status": "not_found",
                    "http_status": 404,
                }
                misses += 1
                save_progress()
                log(f"B {aid} 404 [req={state['req']} ok={ok_count()}]")
                continue
            if st != 200:
                state["records"][aid] = {
                    "id": aid,
                    "era": "new",
                    "archive": None,
                    "yymm": key,
                    "source": "fill",
                    "status": f"head_error:{st}",
                    "http_status": st,
                }
                if st in TRANSIENT:
                    deferred.append(
                        {
                            "id": aid,
                            "era": "new",
                            "archive": None,
                            "yymm": key,
                            "tag": "fill",
                            "url": None,
                            "cd": None,
                        }
                    )
                else:
                    misses += 1
                save_progress()
                log(f"B {aid} HEAD {st} [req={state['req']}]")
                continue
            cd = cd_filename(hdrs)
            if cd.endswith(".pdf"):
                state["records"][aid] = {
                    "id": aid,
                    "era": "new",
                    "archive": None,
                    "yymm": key,
                    "source": "fill",
                    "status": "pdf_only",
                    "cd_filename": cd,
                    "resolved_version": cd_version(cd),
                    "http_status": 200,
                }
                misses += 1
                save_progress()
                log(f"B {aid} pdf_only [req={state['req']} ok={ok_count()}]")
                continue
            ver = cd_version(cd)
            url = (
                f"https://arxiv.org/src/{aid}v{ver}"
                if ver
                else f"https://arxiv.org/src/{aid}"
            )
            rec = fetch_one(
                {
                    "id": aid,
                    "era": "new",
                    "archive": None,
                    "yymm": key,
                    "tag": "fill",
                    "url": url,
                    "cd": cd,
                }
            )
            if is_transient(rec) and rec["attempts"] < 4:
                deferred.append(
                    {
                        "id": aid,
                        "era": "new",
                        "archive": None,
                        "yymm": key,
                        "tag": "fill",
                        "url": url,
                        "cd": cd,
                    }
                )
            elif rec["status"] != "ok":
                misses += 1
            log(f"B {aid} -> {rec['status']} [req={state['req']} ok={ok_count()}]")
        state["phase_b_done"] = True

        # ---- sweeps: retry deferred transient failures after windows pass ----
        for sweep in range(1, 4):
            deferred = [
                w
                for w in deferred
                if state["records"].get(w["id"], {}).get("status") != "ok"
            ]
            if not deferred or ok_count() >= TARGET:
                break
            log(
                f"sweep {sweep}: {len(deferred)} deferred, sleeping 75s for 406 windows"
            )
            time.sleep(75)
            still = []
            for w in deferred:
                if state["req"] >= MAX_REQ:
                    still.append(w)
                    continue
                url = w["url"]
                if url is None:  # phase-B head-deferred: re-HEAD first
                    st, hdrs, _ = request_retry(
                        "HEAD", f"https://arxiv.org/src/{w['id']}"
                    )
                    if st != 200:
                        if st in TRANSIENT:
                            still.append(w)
                        else:
                            state["records"][w["id"]] = {
                                "id": w["id"],
                                "era": "new",
                                "archive": None,
                                "yymm": w["yymm"],
                                "source": "fill",
                                "status": f"head_error:{st}",
                                "http_status": st,
                            }
                            save_progress()
                        continue
                    cd = cd_filename(hdrs)
                    if cd.endswith(".pdf"):
                        state["records"][w["id"]] = {
                            "id": w["id"],
                            "era": "new",
                            "archive": None,
                            "yymm": w["yymm"],
                            "source": "fill",
                            "status": "pdf_only",
                            "cd_filename": cd,
                            "resolved_version": cd_version(cd),
                            "http_status": 200,
                        }
                        save_progress()
                        continue
                    ver = cd_version(cd)
                    url = (
                        f"https://arxiv.org/src/{w['id']}v{ver}"
                        if ver
                        else f"https://arxiv.org/src/{w['id']}"
                    )
                    item = dict(w, url=url, cd=cd)
                else:
                    item = w
                rec = fetch_one(item)
                if is_transient(rec) and rec["attempts"] < 4:
                    still.append(item)
                log(
                    f"S{sweep} {item['id']} -> {rec['status']} [req={state['req']} ok={ok_count()}]"
                )
            deferred = still
    except Stop429:
        log("429 RECEIVED — stopping, progress saved")
    except OutOfBudget:
        log("request budget ceiling reached — stopping")
    finally:
        save_progress()
        n_ok, n_tex, disc = finalize()
        log(f"FINAL ok={n_ok} tex={n_tex} req={state['req']} discards={dict(disc)}")


if __name__ == "__main__":
    main()
