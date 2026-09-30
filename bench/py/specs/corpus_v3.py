r"""corpus_v3 — corpus P2 主管线 spec：簇下载→成员扫描→配额抽样→湖化物化→自检.

`bench/py/corpus/build_corpus_v3.py`（1820 行）的 kernel 移植。docs/spec/corpus.md
S1–S5：30 月簇配额抽样——a–d 带走 IA arxiv-bulk 月 chunk，e 带走 HF
TIGER-Lab/arxiv-latex-5T。零 arxiv.org 请求、零网关（全免费批量通道）。

块选取规则（verbatim）：n_chunks<=2 → 全取；n>2 → 等距 2 块
{n//4+1, 3n//4+1}（避开首块边界与末块 partial）。

Stage 链（单件 ``{"id": "corpus-v3"}`` 串行——成员级断点在工作区文件态，
与旧子命令断点同构）：

  plan           allocation×item-index×tiger-files join → chunks.json；
                 IA metadata（sha1/md5/has_zipsum）同步落 chunks（旧 probe
                 子命令的 metadata 半页折叠在此——HEAD 可达性检查由 fetch
                 的失败路径天然吸收）。frame 资产缺席 → fail（ord-0
                 frame_bootstrap 先行）。
  fetch          .part + Range 断点下载 → verify_chunk（size + sha1/oid16）
                 → rename。retry 轮 ≤4；短收 → partial（chunks.json 持态，
                 下个 run 续）。
  zipsum         IA zipsum.tsv（成员 sha256 交叉核验源；404 钉死永久缺失，
                 5xx 留下轮）。
  scan           流扫 chunk tar → members/features jsonl + tex staging .gz。
  frame_lookup   frame.parquet → frame_lookup.tsv.gz（仅此 stage 需
                 pyarrow——不可导入则 fail 而非 skip：缺 frame 的抽样是错口径）。
  sample         eligible∧frame-join → cell 内随机配额（SEED=42）→
                 sample_core.json + booster_pool.json（B01–B07 预筛）。
  extract        中选成员 → lake cell（hydrate(idc, fetch_fn, source="arxiv")：
                 fetch_fn 从 staging tar/幸存 raw 复读 blob → sha256 复验 →
                 {cell}/raw/{raw_name} + {cell}/extracted/）；
                 manifest.jsonl + MANIFEST.md → bench/corpus/（tracked）。
                 manifest 每轮从 lake cell meta 全量重建——hydrate 后崩
                 不丢行（denominator：manifest 行 ≡ v3 core meta cells）。
  extract_booster booster_selection.jsonl（booster-select 动词产物）中选
                 成员同款物化 → manifest_booster.jsonl；文件缺席 → skip
                 retriable（动词未跑是常态）。
  qc             配额/去重/lake 对账/manifests_tracked → clean|fail。

移植变更（相对旧驱动）：
- 工作区 bench/work_v3/（已灭）→ ``~/.local/state/texlate/corpus-build/v3/``
  持久 builder 目录（多日断点语义；ctx.workspace 跨 run 清，不可用）。
- payload bench/corpus/{id}/ → lake cells（source="arxiv"）；cell meta 带
  旧 meta.json 全字段（n_files 由 hydrate 按 payload 实数、"source" 键
  让位 lake 保留字段——渠道走 "channel" 键；另补 main_tex_sha256 入 cell
  meta 供 manifest 重建投影）。
- 成员 sha 不符 → 成员级 fault（cell errors cat=corrupt）不毁 stage；
  异国 complete cell（无 layer 标记）在 lake_lock 下原地并入 v3 meta
  （旧驱动无条件覆写 meta.json 的同义动作）；layer 冲突 → orphan_adopt。
- 特征提取块（TEXT_EXT..eval_signatures/blob_features/_texts_features/
  unpack_blob）逐字节 verbatim；strip_comments 引 _benchlite 单源
  （verbatim 不感知口径——texlate.arxiv._texutil 版语义不同勿替）。
"""

from __future__ import annotations

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
from collections import Counter
from pathlib import Path

from kernel import fsutil, idnorm, lake, paths
from kernel.events import iter_jsonl
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap
from specs._benchlite import strip_comments

_bootstrap.ensure()

REPO = Path(__file__).resolve().parents[3]
#: 持久 builder 工作区（旧 bench/work_v3 新家——多日断点状态全在这棵树下）。
WORK = (
    Path(os.environ.get("TEXLATE_CORPUS_WORK", ""))
    if os.environ.get("TEXLATE_CORPUS_WORK")
    else Path.home() / ".local" / "state" / "texlate" / "corpus-build" / "v3"
)
TARS = WORK / "tars"
CORPUS = REPO / "bench" / "corpus"
FRAME = REPO / "bench" / "frame"  # frame_bootstrap(ord-0) 物化区（gitignored 数据）
CHUNKS_JSON = WORK / "chunks.json"
SEED = 42  # 抽样口径常量（非旋钮——进 params 会诱改口径）
UA = {"User-Agent": "texlate-corpus-v3/1.0 (research benchmark build)"}
TIMEOUT = 60

IA_DL = "https://archive.org/download/{item}/{item}.tar"
IA_META = "https://archive.org/metadata/{item}"
IA_ZIPSUM = "https://archive.org/download/{item}/{item}_zipsum.tsv"
TIGER_DL = (
    "https://huggingface.co/datasets/TIGER-Lab/arxiv-latex-5T/resolve/main/{name}.tar"
)

#: lake cell 落点维度——全部下游 spec 的 lake_source 共识。
LAKE_SOURCE = "arxiv"

BAND_OF_CLUSTER = {}  # cluster_id -> year_band, filled by load_allocation()

# ---------------- 通用 ----------------


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _atomic_write_text(path: Path, text: str) -> None:
    fsutil.atomic_write(Path(path), text.encode("utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [row for _ln, row, _raw in iter_jsonl(Path(path)) if isinstance(row, dict)]


def load_allocation() -> list[dict]:
    with (FRAME / "allocation-core.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["quota_core"] = int(r["quota_core"])
        r["n_chunks"] = int(r["n_chunks"])
        BAND_OF_CLUSTER[r["cluster_id"]] = r["year_band"]
    return rows


def load_chunks() -> list[dict]:
    return json.loads(CHUNKS_JSON.read_text())


def save_chunks(chunks: list[dict]) -> None:
    _atomic_write_text(CHUNKS_JSON, json.dumps(chunks, indent=1) + "\n")


def open_url(url: str, headers: dict | None = None, timeout: int = TIMEOUT):
    req = urllib.request.Request(  # noqa: S310 — bench 下载脚本, URL 全是固定 https 端点
        url, headers={**UA, **(headers or {})}
    )
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — 同上


def safe_name(name: str) -> str | None:
    p = Path(name.lstrip("./"))
    if p.is_absolute() or ".." in p.parts:
        return None
    return str(p)


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
    missing = [f for f in _FRAME_INPUTS if not (FRAME / f).is_file()]
    if missing:
        ctx.emit_note(
            f"frame 资产缺席 {missing} — 先跑 frame_bootstrap(ord-0)", level="warn"
        )
        return {"status": "fail", "metrics": {"missing_frame": missing}}
    WORK.mkdir(parents=True, exist_ok=True)
    alloc = load_allocation()
    ia_idx: dict[str, dict[int, dict]] = {}
    with (FRAME / "item-index.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            ia_idx.setdefault(r["yymm"], {})[int(r["chunk"])] = {
                "item": r["identifier"],
                "size": int(r["size"]),
            }
    tiger_idx: dict[str, dict[int, dict]] = {}
    with (FRAME / "tiger-files.csv").open(newline="") as fh:
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
            log(f"!! {row['cluster_id']} {yymm} 在 {ch} 索引中不存在")
            continue
        avail = sorted(idx[yymm])
        if len(avail) != row["n_chunks"]:
            log(f"!! {yymm} 索引块数 {len(avail)} != allocation {row['n_chunks']}")
        for cid in pick_chunk_ids(len(avail)):
            if cid not in idx[yymm]:
                log(f"!! {yymm} chunk {cid} 缺")
                continue
            info = idx[yymm][cid]
            if ch == "ia":
                item = info["item"]
                url = IA_DL.format(item=item)
            else:
                item = f"arXiv_src_{yymm}_{cid:03d}"
                url = TIGER_DL.format(name=item)
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
            with open_url(IA_META.format(item=c["item"])) as r:
                meta = json.loads(r.read())
            (WORK / "meta" / f"{c['item']}.json").write_text(json.dumps(meta))
            for f in meta.get("files", []):
                if f["name"] == f"{c['item']}.tar":
                    c["sha1"] = f.get("sha1")
                    c["md5"] = f.get("md5")
                    if int(f.get("size", 0)) != c["size"]:
                        log(
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
            log(f"  meta fail {c['item']}: {e}")

    save_chunks(chunks)
    by_ch = {}
    for c in chunks:
        by_ch.setdefault(c["channel"], []).append(c)
    for ch, lst in by_ch.items():
        log(f"{ch}: {len(lst)} chunks, {sum(c['size'] for c in lst) / 1e9:.2f} GB")
    log(f"total {len(chunks)} chunks -> {CHUNKS_JSON}")
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
    """下载单 chunk 到 .part → 校验 → rename .tar. 可重入: .part 按 Range 续传,
    已下载足量的直接进校验. 返回更新后的 c."""
    t0 = time.time()
    part = TARS / f"{c['item']}.tar.part"
    final = TARS / f"{c['item']}.tar"
    try:
        # 快路: .tar 已在盘上且尺寸对 → 直接进校验 (状态文件被并发写乱时的自愈)
        if part.exists():
            have = part.stat().st_size
            src = part
        elif final.exists():
            if final.stat().st_size == c["size"]:
                have, src = c["size"], final
            else:
                # final 只经 verify 后 rename 而来——尺寸不对即腐文件, 重抓
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
            # 验不过的文件必删——final 验过才 rename 而来(如今腐=盘上字节变),
            # part 验不过=内容错(尺寸已齐), 留着下轮只是重复验同一坏字节
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
    r = open_url(c["url"], headers=headers, timeout=120)
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
    """完整性校验: 全量 sha256 + IA sha1 (metadata) / TIGER lfs_oid16 前缀.
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
    log(
        f"fetch: {len(todo)} chunks pending"
        + (f" (channel={channel})" if channel else "")
    )
    done_bytes = 0
    for round_no in range(1, 5):  # 瞬断重试: .part 保留进度, Range 续传
        todo = [c for c in todo if c["state"] != "done"]
        if not todo:
            break
        if round_no > 1:
            log(f"retry round {round_no}: {len(todo)} chunks")
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
                    log(
                        f"  ok {c['item']} {c['size'] / 1e6:.0f}MB "
                        f"{c['elapsed_s']}s | session {done_bytes / 1e9:.2f}GB"
                    )
                else:
                    log(f"  FAIL {c['item']}: {c.get('error')}")
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
    log(f"fetch done: {n_done}/{len(chunks)} chunks complete")
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
            with open_url(IA_ZIPSUM.format(item=c["item"])) as r:
                data = r.read()
            out.write_bytes(data)
            n_hit += 1
            log(f"zipsum {c['item']} {len(data)}B")
        except urllib.error.HTTPError as e:
            log(f"zipsum {c['item']} HTTP {e.code}")
            if e.code == 404:  # 永久缺失才钉死; 5xx 留下轮重试
                c["has_zipsum"] = False
                n_404 += 1
            else:
                n_err += 1
        except (urllib.error.URLError, OSError) as e:
            n_err += 1
            log(f"zipsum {c['item']} {type(e).__name__}: {e} — 跳过重试")
    save_chunks(chunks)
    return {
        "status": "ok",
        "metrics": {"zipsum_present": n_hit, "zipsum_404": n_404, "zipsum_err": n_err},
    }


# ---------------- scan (S2) ----------------
# 特征提取逐字节 lift build_corpus_v3（其本身改编自 ia-pilot 原型的 scan_tar.py;
# 增量: blob_sha256 / stub / staging 输出 / zipsum 交叉核验）.

TEXT_EXT = {
    ".tex",
    ".sty",
    ".cls",
    ".bbl",
    ".bib",
    ".txt",
    ".def",
    ".clo",
    ".cfg",
    ".ltx",
    ".dtx",
    ".ins",
    ".fd",
    ".bst",
    ".mf",
    ".mac",
}
DOCCLASS_RX = re.compile(
    r"\\(documentclass|documentstyle)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}",
    re.DOTALL,
)
INPUT_RX = re.compile(
    r"\\(?:input|include|InputIfFileExists)\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}"
)
# deadpkg 名单：净室 stub 族（禁再分发→missing_file 必中）+ vendored 真件族
# （pkg_version_skew/接口漂移高发）+ 残差签名实测族。小写归一，匹配 IGNORECASE。
# revtex 只钉裸名——revtex4/revtex4-2 是 CTAN 现役，\b 边界天然排除。
DEAD_PKGS = {
    "aa",
    "aasms4",
    "aaspp4",
    "aastex",
    "aipproc",
    "aipmod",
    "apjfonts",
    "axodraw",
    "boxedeps",
    "citesort",
    "complexity",
    "diagrams",
    "elsart",
    "emulateapj",
    "epsf",
    "epsfx",
    "eqsecnum",
    "espcrc1",
    "espcrc2",
    "iopart",
    "imsart",
    "jhep3",
    "jheppub",
    "jinstpub",
    "mn2e",
    "moriond",
    "psfig",
    "pst-node",
    "revtex",
    "slashbox",
    "sprocl",
    "svglov3",
    "svjour",
    "svjour3",
    "sw20lart",
    "tcilatex",
    "texsort",
}
DEADPKG_ALT = "|".join(sorted(DEAD_PKGS, key=len, reverse=True)).replace("-", "[-]")
DEADPKG_RX = re.compile(
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*?(?:"
    + DEADPKG_ALT
    + r")\b|"
    + r"\\document(?:class|style)\s*(?:\[[^\]]*\])?\s*\{[^}]*?(?:"
    + DEADPKG_ALT
    + r")\b|"
    + r"\\documentstyle\[[^\]]*(?:"
    + DEADPKG_ALT
    + r")\b|"
    + r"\\input\s*\{?[^{}\s]*(?:"
    + DEADPKG_ALT
    + r")\b",
    re.IGNORECASE,
)

FLAG_RX = {
    "minted": re.compile(
        # \mint 定界（W108）：必须是 minted 调用形（[opts]{lang}）——作者常以
        # \def\mint{\int..} 表多重积分，\b 裸匹配会把定义体/积分用法误作 flag
        r"\\begin\{minted\}|\\inputminted|"
        r"\\mint(?:inline)?(?:\[[^\]]*\])?\{[a-zA-Z0-9_+.-]+\}|"
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*minted"
    ),
    "pstricks": re.compile(
        r"\\begin\{pspicture\}|\\ps[A-Z]|"
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{pst[-a-z]*"
    ),
    "tikz": re.compile(
        r"\\begin\{tikzpicture\}|\\tikz\b|\\usetikzlibrary|"
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*tikz"
    ),
    "biblatex": re.compile(
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{biblatex|"
        r"\\addbibresource|\\printbibliography"
    ),
    "hyperref": re.compile(
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*hyperref|"
        r"\\hypersetup"
    ),
    "amsmath": re.compile(
        r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*amsmath|"
        r"\\begin\{align|\\begin\{equation"
    ),
    "epsfig": re.compile(
        r"\\epsfig\{|\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{epsfig|"
        r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\.e?ps\}?",
        re.IGNORECASE,
    ),
    # failmine 矿类旗（2026-09-19 扩库）：命中即"现代引擎大概率 missing_file /
    # 走 vendor stub"的论文——名单对齐 fixloop/vendor/{stubs,files} 绝版族 +
    # loop1 残差签名族（aasms4/psfig/pst-node/JHEP3/epsf）。三种命中形态：
    # \usepackage{}/\RequirePackage{}、\documentstyle 选项位、\input X.sty。
    "deadpkg": DEADPKG_RX,
    # 旧式 pdftex 原语直写（unfixable:pdftex_prim:* 族）：现代引擎不认的
    # 原语赋值——只钉赋值形（=\d），读位（\ifnum\pdfoutput）不算病灶。
    "pdftex_prim": re.compile(
        r"\\pdf(?:compresslevel|objcompresslevel|decimaldigits|"
        r"optionalwaysusepdfpagebox|omitcharset|suppressptexinfo)\s*=?|"
        r"\\pdfoutput\s*=\s*\d"
    ),
    # babel 非英语选项族（残差签名 babel_opt:german）：选项位命中即记——
    # 只钉 babel 包，其他包的 german 同名选项不捞。
    "babel_german": re.compile(
        r"\\(?:usepackage|RequirePackage)\[[^\]]*german[^\]]*\]\{babel\}|"
        r"\\usepackage\{babel\}[^\n]*german"
    ),
}
AUTOIGNORE = b"%auto-ignore"

# ---- EVAL 良性形态签名（mechanisms.jsonl EVAL 族；blob_features 簿记进 signatures）----
USEP_RX = re.compile(r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]*)\}")
# W35 期刊样式以 \usepackage 加载的已知样式包（jheppub 类——2.09 docstyle 选项系同款）
JOURNAL_STY_PKGS = {
    "jheppub",
    "jinstpub",
    "aasms4",
    "aaspp4",
    "sprocl",
    "espcrc2",
    "moriond",
    "aipmod",
    "eqsecnum",
    "emulateapj",
}
# W62 kitchen-sink 异质 DSL 包（证据谱：CJKutf8+skak+xypic+tikz-cd+commath+faktor+nccmath）
DSL_PKGS = {
    "skak",
    "xypic",
    "tikz-cd",
    "commath",
    "faktor",
    "nccmath",
    "chess",
    "amscd",
    "pb-diagram",
    "forest",
    "qtree",
    "xy",
}
# W64 \documentclass 非常规 option 位期刊样式（证据 ecta；同谱补 jhep/jcap/mnras/aastex
# + revtex 期刊/学会位 pra..prx/aps/aip——实测 docclass_opts 谱见 1502.06414）
JOURNAL_OPTS = {
    "ecta",
    "jhep",
    "jcap",
    "mnras",
    "aastex",
    "aps",
    "aip",
    "pra",
    "prb",
    "prc",
    "prd",
    "pre",
    "prl",
    "prx",
    "rmp",
}
# W70 选项错拼判定基线：LaTeX 内核 + 主流类选项白名单（编辑距 ≤1 即疑 typo）
KERNEL_OPTS = {
    "8pt",
    "9pt",
    "10pt",
    "11pt",
    "12pt",
    "14pt",
    "17pt",
    "20pt",
    "a4paper",
    "a5paper",
    "b5paper",
    "letterpaper",
    "legalpaper",
    "executivepaper",
    "landscape",
    "twocolumn",
    "onecolumn",
    "twoside",
    "oneside",
    "draft",
    "final",
    "fleqn",
    "leqno",
    "titlepage",
    "notitlepage",
    "openright",
    "openany",
    "openbib",
    "preprint",
    "preprintnumbers",
    "superscriptaddress",
    "amsmath",
    "amssymb",
    "amsfonts",
    "floatfix",
    "nofootinbib",
    "showkeys",
    "showpacs",
    "longbibliography",
    "reprint",
    "conference",
    "journal",
    "technote",
    "compsoc",
    "peerreview",
    "review",
    "manuscript",
    "screen",
    "referee",
    "english",
    "proc",
    "overfull",
    "numbered",
    "authoryear",
    # 实测语料补录（避免标准类选项误作 typo 候选）:
    # amsart 系 eqno/tags/limits 位
    "reqno",
    "tbtags",
    "centertags",
    "intlimits",
    "nointlimits",
    "sumlimits",
    "nosumlimits",
    "namelimits",
    "nonamelimits",
    # IEEEtran 学会位
    "comsoc",
    "transmag",
    # svjour/aip 系参考文献样式位
    "author-year",
}
ORG_LABEL_RX = re.compile(r"\\label\{sec:org[0-9a-f]{5,9}\}")
EDITOR_LEFT_RX = re.compile(r"\\label\{[a-z]+:enter-label\}|\\textbf\{\}")
PLAIN_OUT_RX = re.compile(
    r"\\(?:headline|footline|output|shipout)\s*(?=[={\\])|\\shipout\b"
)
MANUAL_BF_RX = re.compile(r"\{\\bf[a-z]*\b")
CENTERLINE_RX = re.compile(r"\\centerline\b")
SECTION_RX = re.compile(r"\\(?:sub)*section\*?\s*[{\[]")
XREF_RX = re.compile(r"\\jobname\.xref|\.xref\b")


def _dist1(a: str, b: str) -> bool:
    """a 与 b 编辑距离恰为 1（W70 选项错拼：12pi↔12pt）。"""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    if la > lb:
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1 :]


def eval_signatures(blob_txt: str) -> dict[str, object]:
    """良性形态签名簿记 → {mech_id: 命中明细}；只在 paper 自身 tex（剥注释后）上看。

    每条对应 mechanisms.jsonl EVAL 族一行——把「长得像故障的良性形态」注记进
    features，供归因/狩猎区分真缺陷与形态签名（W48 协作残留、W88 手排、W70 typo 等）。
    """
    sig: dict[str, object] = {}
    pkgs = Counter(
        p.strip()
        for m in USEP_RX.finditer(blob_txt)
        for p in m.group(1).split(",")
        if p.strip()
    )
    if dups := sorted(p for p, c in pkgs.items() if c >= 2):
        sig["W48"] = dups
    if jsty := sorted(pkgs.keys() & JOURNAL_STY_PKGS):
        sig["W35"] = jsty
    if ORG_LABEL_RX.search(blob_txt):
        sig["W39"] = True
    if n := len(EDITOR_LEFT_RX.findall(blob_txt)):
        sig["W60"] = n
    if (dsl := sorted(pkgs.keys() & DSL_PKGS)) and len(dsl) >= 2:
        sig["W62"] = dsl
    dcls_opts = {
        o.strip()
        for m in DOCCLASS_RX.finditer(blob_txt)
        if m.group(1) == "documentclass" and m.group(2)
        for o in m.group(2).split(",")
        if o.strip()
    }
    if jopt := sorted(dcls_opts & JOURNAL_OPTS):
        sig["W64"] = jopt
    if typos := sorted(
        o
        for o in dcls_opts - JOURNAL_OPTS - KERNEL_OPTS
        if any(_dist1(o, k) for k in KERNEL_OPTS)
    ):
        sig["W70"] = typos
    if not SECTION_RX.search(blob_txt) and (
        len(MANUAL_BF_RX.findall(blob_txt)) >= 3
        or len(CENTERLINE_RX.findall(blob_txt)) >= 2
    ):
        sig["W88"] = True
    if outs := sorted({o.strip() for o in PLAIN_OUT_RX.findall(blob_txt)}):
        sig["W93"] = outs
    if XREF_RX.search(blob_txt):
        sig["W106"] = True
    return sig


def looks_like_tar(b: bytes) -> bool:
    if len(b) < 512:
        return False
    if b[257:262] == b"ustar":
        return True
    try:
        chksum = int(b[148:156].split(b"\0", 1)[0].strip() or b"0", 8)
        calc = sum(b[:148]) + 8 * 32 + sum(b[156:512])
    except ValueError:
        return False
    return calc == chksum


def norm_target(raw: str) -> str:
    t = raw.strip().strip("{}").strip('"').strip("'")
    t = t.replace("\\", "/").lstrip("./")
    if not Path(t).suffix:
        t += ".tex"
    return t


def input_depth(tex_by_norm: dict[str, str], roots: list[str]) -> int:
    edges: dict[str, set[str]] = {}
    for path, text in tex_by_norm.items():
        deps = set()
        base = Path(path).parent
        for m in INPUT_RX.finditer(text):
            t = norm_target(m.group(1))
            cands = (str(base / t), t, str(base / Path(t).name))
            hit = next(
                (
                    x
                    for x in (str(Path(x)) if x.startswith("/") else x for x in cands)
                    if x in tex_by_norm
                ),
                None,
            )
            if hit is not None:
                deps.add(hit)
        edges[path] = deps
    starts = roots or list(tex_by_norm)
    best = 0
    for s in starts:
        seen: dict[str, int] = {}
        stack = [(s, 0)]
        while stack:
            node, d = stack.pop()
            if seen.get(node, -1) >= d or d > 32:
                continue
            seen[node] = d
            best = max(best, d)
            stack.extend((nxt, d + 1) for nxt in edges.get(node, ()))
    return best


def member_id(name: str) -> str:
    """'9802/astro-ph9802001.gz' → 'astro-ph/9802001';
    '1201/1201.00012.gz' → '1201.00012'."""
    stem = Path(name).name
    stem = re.sub(r"\.(gz|pdf|tar\.gz)$", "", stem)
    m = re.match(r"([a-z-]+(?:\.[A-Z]{2})?)(\d{7})$", stem)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return stem


def blob_features(name: str, blob: bytes) -> dict:
    """单个 e-print blob → 特征 dict (scan_tar 版 + sha256/stub/staging texts).

    特征口径见 _texts_features: flags=tex 通道 / flags_vendored=sty·cls·bbl 通道
    / flags_commented=剥注释差集 / signatures=EVAL 良性形态簿记。
    """
    rec: dict = {
        "member": name,
        "id": member_id(name),
        "member_bytes": len(blob),
        "blob_sha256": hashlib.sha256(blob).hexdigest(),
    }
    if blob[:5] == b"%PDF-":
        rec["format"] = "pdf"
        return rec
    if blob[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(blob)
        except OSError as e:
            rec["format"] = "error"
            rec["error"] = f"gunzip: {e}"
            return rec
    else:
        data = blob
    if data.lstrip()[:20].startswith(AUTOIGNORE):
        rec["format"] = "stub"
        rec["uncompressed_bytes"] = len(data)
        return rec
    if looks_like_tar(data):
        rec["format"] = "tar"
        try:
            inner = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
            files = [m for m in inner.getmembers() if m.isreg()]
        except tarfile.TarError as e:
            rec["format"] = "error"
            rec["error"] = f"inner tar: {e}"
            return rec
        texts: dict[str, bytes] = {}
        n_tex = 0
        total_bytes = 0
        for m in files:
            total_bytes += m.size
            ext = Path(m.name).suffix.lower()
            if ext == ".tex":
                n_tex += 1
            if ext in TEXT_EXT and m.size < 8 << 20:
                f = inner.extractfile(m)
                if f:
                    texts[m.name.lstrip("./")] = f.read()
        rec["n_total_files"] = len(files)
        rec["n_tex_files"] = n_tex
        rec["uncompressed_bytes"] = total_bytes
    else:
        rec["format"] = "gz"
        rec["n_total_files"] = 1
        head = data.lstrip()[:8]
        is_tex = not head.startswith((b"%!PS", b"%PDF"))
        rec["n_tex_files"] = 1 if is_tex else 0
        if not is_tex:
            rec["gz_payload"] = "ps/pdf"
        rec["uncompressed_bytes"] = len(data)
        texts = {Path(name).name.replace(".gz", ".tex"): data}

    tex_texts: dict[str, str] = {}
    non_utf8 = False
    for p, b in texts.items():
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            non_utf8 = True
            s = b.decode("utf-8", "replace")
        if Path(p).suffix.lower() == ".tex" or rec["format"] == "gz":
            tex_texts[p] = s
    rec["non_utf8"] = non_utf8
    rec["_texts"] = texts  # staging 用, 不落 jsonl
    rec.update(_texts_features(tex_texts, texts))
    return rec


def _texts_features(tex_texts: dict[str, str], texts: dict[str, bytes]) -> dict:
    """tex_texts(剥注释前 tex 文本)+texts(全部文本件)→ 形态特征字段。

    blob_features(scan_tar) 与 fetch-ids extracted 树共用同一计算——特征口径
    单点维护, 避免两通道漂移。
    """
    rec: dict = {}
    tex_raw = "\n".join(tex_texts.values())
    sty_raw = "\n".join(
        b.decode("utf-8", "replace")
        for p, b in texts.items()
        if Path(p).suffix.lower() in {".sty", ".cls", ".bbl"}
    )
    blob_txt = strip_comments(tex_raw)
    sty_txt = strip_comments(sty_raw)
    dcls_ms = list(DOCCLASS_RX.finditer(blob_txt))
    rec["docclasses"] = sorted({m.group(3).strip() for m in dcls_ms})
    rec["docstyle"] = any(m.group(1) == "documentstyle" for m in dcls_ms)
    # W80-feat: 2.09 \documentstyle[jheppub,12pt]{article} 的期刊样式本体在 option 位
    rec["docstyle_opts"] = sorted(
        {
            o.strip()
            for m in dcls_ms
            if m.group(1) == "documentstyle" and m.group(2)
            for o in m.group(2).split(",")
            if o.strip()
        }
    )
    rec["docclass_opts"] = sorted(
        {
            o.strip()
            for m in dcls_ms
            if m.group(1) == "documentclass" and m.group(2)
            for o in m.group(2).split(",")
            if o.strip()
        }
    )
    roots = [p for p, t in tex_texts.items() if DOCCLASS_RX.search(strip_comments(t))]
    rec["tex_roots"] = sorted(roots)
    rec["input_depth"] = input_depth(tex_texts, roots)
    # W101: flags 拆 tex/vendored 双通道——sty/cls/bbl 是发行资产, 合并扫描会把
    # 宏包自带形态(如样式文件内嵌 pstricks 钩)误记为论文自身 flag
    rec["flags"] = sorted(k for k, rx in FLAG_RX.items() if rx.search(blob_txt))
    rec["flags_vendored"] = sorted(k for k, rx in FLAG_RX.items() if rx.search(sty_txt))
    # W109: hunter rg 命中剥注释复核——只活在注释里的命中单列(raw 有 stripped 无)
    raw_scan = tex_raw + "\n" + sty_raw
    stripped_hits = set(rec["flags"]) | set(rec["flags_vendored"])
    rec["flags_commented"] = sorted(
        {k for k, rx in FLAG_RX.items() if rx.search(raw_scan)} - stripped_hits
    )
    if sig := eval_signatures(blob_txt):
        rec["signatures"] = sig
    return rec


def _scan_chunk(c: dict) -> None:
    tag = f"{c['yymm']}_{c['chunk_no']:03d}"
    mdir = WORK / "members"
    fdir = WORK / "features"
    sdir = WORK / "staging" / c["cluster_id"]
    for d in (mdir, fdir, sdir):
        d.mkdir(parents=True, exist_ok=True)
    mout, fout = mdir / f"{tag}.jsonl", fdir / f"{tag}.jsonl"
    if fout.exists() and mout.exists():
        log(f"scan {tag}: already done, skip")
        return
    mtmp, ftmp = mout.with_suffix(".tmp"), fout.with_suffix(".tmp")
    zsum = {}
    zp = WORK / "zipsum" / f"{c['item']}_zipsum.tsv"
    if zp.exists():
        for line in zp.read_text().splitlines():
            cols = line.split()  # 空格分隔: sha1 sha256 md5 size name
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
                rec = blob_features(m.name, blob)
            except Exception as e:  # 成员级异常不阻断
                rec = {
                    "member": m.name,
                    "id": member_id(m.name),
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
                    rel_safe = safe_name(rel)
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
                log(f"  {tag}: {n} members, {time.time() - t0:.0f}s")
    mtmp.rename(mout)
    ftmp.rename(fout)
    log(
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
            log(f"!! scan {tag}: {type(e).__name__}: {e}")
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
        FRAME / "frame.parquet",
        columns=[
            "id",
            "tar_yymm",
            "year_band",
            "cat_group",
            "primary_cat",
            "license_class",
        ],
    )
    out = WORK / "frame_lookup.tsv.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt") as f:
        cols = [t.column(n).to_pylist() for n in t.column_names]
        for row in zip(*cols, strict=True):
            f.write("\t".join("" if v is None else str(v) for v in row) + "\n")
    log(f"frame_lookup: {t.num_rows} rows -> {out}")
    return {"status": "ok", "metrics": {"frame_rows": t.num_rows}}


def load_frame_lookup() -> dict[str, dict]:
    path = WORK / "frame_lookup.tsv.gz"
    lut = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6:
                continue
            i, ty, yb, cg, pc, lc = parts[:6]
            lut[i] = {
                "tar_yymm": ty,
                "year_band": yb,
                "cat_group": cg,
                "primary_cat": pc,
                "license_class": lc,
            }
    return lut


def frame_get(lut: dict, pid: str) -> dict | None:
    """成员 id → frame 行; 旧式 math.XX/ 归并 math/ 回退."""
    r = lut.get(pid)
    if r is None and "/" in pid:
        arch, num = pid.split("/", 1)
        if "." in arch:
            r = lut.get(f"{arch.split('.')[0]}/{num}")
    return r


# ---------------- sample (S3a) ----------------


def eligible(f: dict) -> bool:
    return f.get("format") in ("tar", "gz") and (f.get("n_tex_files") or 0) >= 1


def _sample(ctx):
    rng = random.Random(SEED)
    alloc = {r["cluster_id"]: r for r in load_allocation()}
    mix: dict[str, dict[str, float]] = {}
    mix_path = FRAME / "cluster-cat-mix.csv"
    if not mix_path.is_file():
        ctx.emit_note(f"frame 资产缺席 {mix_path.name}", level="warn")
        return "fail"
    with mix_path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            mix.setdefault(r["yymm"], {})[r["cat_group"]] = float(r["share"])
    lut = load_frame_lookup()
    chunks = load_chunks()

    feats_by_cluster: dict[str, list[dict]] = {}
    for c in chunks:
        if c["state"] != "done":
            continue
        tag = f"{c['yymm']}_{c['chunk_no']:03d}"
        fp = WORK / "features" / f"{tag}.jsonl"
        if not fp.exists():
            continue
        for rec in _read_jsonl(fp):
            rec["_tag"] = tag
            feats_by_cluster.setdefault(c["cluster_id"], []).append(rec)

    selected: dict[str, list[dict]] = {}
    report = []
    booster_pool: dict[str, list[dict]] = {f"B{i:02d}": [] for i in range(1, 8)}

    for cid in sorted(alloc):
        row = alloc[cid]
        yymm, q = row["yymm"], row["quota_core"]
        feats = feats_by_cluster.get(cid, [])
        # join frame
        pool = []
        n_join_miss = 0
        for f in feats:
            fr = frame_get(lut, f["id"])
            if fr is None:
                n_join_miss += 1
                f["cat_group"] = "unknown"
                f["license_class"] = "unknown"
            else:
                f["cat_group"] = fr["cat_group"]
                f["license_class"] = fr["license_class"]
                f["primary_cat"] = fr["primary_cat"]
                if fr["tar_yymm"] != yymm:
                    f["yymm_mismatch"] = True
            # 只有 frame 命中的成员进核心池 (事后分层权重需要 cat_group)
            if fr is not None and eligible(f):
                pool.append(f)
            # ---- booster 候选预筛 (不中选也可入池, extract 阶段只挑最终提名) ----
            whys: dict[str, list[str]] = {}
            if f.get("docstyle"):
                whys["B01"] = ["documentstyle"]
            if f.get("non_utf8"):
                whys["B02"] = ["non_utf8"]
            if (f.get("n_tex_files") or 0) >= 10 or (f.get("input_depth") or 0) >= 3:
                whys["B03"] = [
                    f"n_tex={f.get('n_tex_files')}",
                    f"depth={f.get('input_depth')}",
                ]
            pc = f.get("primary_cat") or ""
            if (
                f.get("cat_group") in ("cs", "eess-stat-etc")
                or pc.startswith(("econ.", "q-fin."))
            ) and row["year_band"] in ("d_2017_20", "e_2021_25"):
                whys["B04"] = [f"low-tex-cat:{pc or f.get('cat_group')}"]
            fl = set(f.get("flags") or [])
            known_cls = {
                "article",
                "revtex",
                "revtex4",
                "revtex4-1",
                "revtex4-2",
                "amsart",
                "ieeetran",
                "llncs",
                "elsarticle",
                "mnras",
                "aa",
                "report",
                "book",
                "scrartcl",
                "memoir",
                "aastex",
            }
            vendored = any(
                d.lower() not in known_cls for d in (f.get("docclasses") or [])
            )
            if fl & {"minted", "pstricks"} or vendored:
                whys["B05"] = sorted(fl & {"minted", "pstricks"}) + (
                    ["vendored-cls"] if vendored else []
                )
            if (f.get("uncompressed_bytes") or 0) > 2 << 20:
                whys["B06"] = [f"uncompressed={f['uncompressed_bytes']}"]
            if f.get("format") in ("gz", "pdf", "stub", "error"):
                whys["B07"] = [f"format={f.get('format')}"]
            for cell, reasons in whys.items():
                booster_pool[cell].append(
                    {
                        "id": f["id"],
                        "cluster_id": cid,
                        "member": f["member"],
                        "_tag": f["_tag"],
                        "why": reasons,
                    }
                )

        shares = mix.get(yymm, {})
        by_group: dict[str, list[dict]] = {}
        for f in pool:
            by_group.setdefault(f["cat_group"], []).append(f)
        for v in by_group.values():
            rng.shuffle(v)
        # largest-remainder 配额
        targets, rema = {}, []
        for g, s in shares.items():
            t = q * s
            targets[g] = int(t)
            rema.append((t - int(t), g))
        for _ in range(q - sum(targets.values())):
            if not rema:
                break
            rema.sort(reverse=True)
            _, g = rema.pop(0)
            targets[g] += 1
        picked: list[dict] = []
        attain = {}
        for g, t in sorted(targets.items()):
            avail = by_group.get(g, [])
            take = min(t, len(avail))
            picked.extend(avail[:take])
            by_group[g] = avail[take:]
            attain[g] = (t, take)
        deficit = q - len(picked)
        if deficit > 0:
            rest = [f for v in by_group.values() for f in v]
            rng.shuffle(rest)
            picked.extend(rest[:deficit])
        for f in picked:
            f["layer"] = "core"
        selected[cid] = picked
        report.append(
            {
                "cluster_id": cid,
                "yymm": yymm,
                "quota": q,
                "members_scanned": len(feats),
                "eligible": len(pool),
                "frame_join_miss": n_join_miss,
                "picked": len(picked),
                "deficit": deficit,
                "attain": {
                    g: {"target": t, "got": got}
                    for g, (t, got) in sorted(attain.items())
                },
                "format_dist": {
                    k: sum(1 for f in feats if f.get("format") == k)
                    for k in ("tar", "gz", "pdf", "stub", "error")
                },
            }
        )

    # booster 池去掉核心中选
    core_ids = {f["id"] for lst in selected.values() for f in lst}
    for k, lst in booster_pool.items():
        booster_pool[k] = [c for c in lst if c["id"] not in core_ids]

    _atomic_write_text(
        WORK / "sample_core.json",
        json.dumps(
            {
                cid: [
                    {
                        k: f.get(k)
                        for k in (
                            "id",
                            "member",
                            "_tag",
                            "cat_group",
                            "license_class",
                            "primary_cat",
                            "blob_sha256",
                            "format",
                        )
                    }
                    for f in lst
                ]
                for cid, lst in selected.items()
            },
            indent=1,
        )
        + "\n",
    )
    _atomic_write_text(
        WORK / "booster_pool.json", json.dumps(booster_pool, indent=1) + "\n"
    )
    _atomic_write_text(WORK / "sample_report.json", json.dumps(report, indent=1) + "\n")
    for r in report:
        att = ", ".join(f"{g}:{a['got']}/{a['target']}" for g, a in r["attain"].items())
        print(
            f"{r['cluster_id']} {r['yymm']} q={r['quota']} "
            f"pool={r['members_scanned']} elig={r['eligible']} "
            f"picked={r['picked']} miss={r['frame_join_miss']} | {att}"
        )
    log(
        f"sample: {sum(r['picked'] for r in report)} core picks, "
        f"booster pool { {k: len(v) for k, v in booster_pool.items()} }"
    )
    return {
        "status": "ok",
        "metrics": {
            "core_picked": sum(r["picked"] for r in report),
            "deficit": sum(r["deficit"] for r in report),
            "frame_join_miss": sum(r["frame_join_miss"] for r in report),
            "booster_pool": sum(len(v) for v in booster_pool.values()),
        },
    }


# ---------------- extract (S4) — lake 物化 ----------------


def unpack_blob(blob: bytes, fmt: str, dest: Path) -> tuple[int, list[str]]:
    """raw e-print blob → ``dest/extracted/``（归并产品 ``texlate.arxiv`` unpack）。

    sniff 做有上限 gunzip + 魔数复核——``fmt`` 只是扫描侧标注，内容优先、不符
    记 fmt_mismatch 告警；tar 走产品逐成员过滤（容量/setuid/link/casefold/
    stub），单文件 gz 沿用旧命名：tex → ``main.tex``、ps/pdf payload 按真实
    扩展名落盘。非 tar/gz 与解包硬错误 → ``(0, warns)``，不炸批。
    """
    from texlate.arxiv import (  # 仅 extract 路径需要 (pyarrow 同例；其余 stage 保持 stdlib-only)
        BlobKind,
        SniffError,
        UnpackError,
        sniff,
        unpack_single,
        unpack_tar,
    )

    if fmt not in ("tar", "gz"):
        return 0, [f"{fmt} member — blob 留存不解包"]
    ext_dir = dest / "extracted"
    ext_dir.mkdir(parents=True, exist_ok=True)
    try:
        s = sniff(blob)
    except SniffError as e:
        return 0, [f"sniff_error:{e}"]
    if s.oversized or s.payload is None:
        return 0, [
            f"inflated_too_large:{s.inflated_size}"
            if s.oversized
            else f"cannot unpack kind={s.kind}"
        ]
    try:
        if s.kind is BlobKind.TAR:
            res = unpack_tar(s.payload, ext_dir)
            if fmt != "tar":
                res.warnings.append("fmt_mismatch:gz->tar")
            return res.n_files, res.warnings
        if s.kind is BlobKind.SINGLE:
            head = s.payload.lstrip()[:8]
            if head.startswith((b"%!PS", b"%PDF")):
                ext = ".ps" if head.startswith(b"%!PS") else ".pdf"
                (ext_dir / f"main{ext}").write_bytes(s.payload)
                return 1, [f"single-gz payload sniffed as {ext}"]
            res = unpack_single(s.payload, ext_dir, stem_hint="main")
            if fmt != "gz":
                res.warnings.append("fmt_mismatch:tar->single")
            return res.n_files, res.warnings
    except UnpackError as e:
        return 0, [f"unpack_error:{e}"]
    return 0, [f"cannot unpack kind={s.kind}"]


class _MemberFault(Exception):
    """成员级故障——fetch_fn 内抛，stage fn 捕，记 cell errors 不毁 stage。"""

    def __init__(self, cat: str, payload: str):
        self.cat = cat
        self.payload = payload
        super().__init__(f"{cat}:{payload}")


_RAW_NAME = {
    "tar": "raw.tar.gz",
    "gz": "raw.gz",
    "pdf": "raw.pdf",
    "stub": "raw.stub",
}


def _cell_meta(d: Path) -> dict:
    try:
        m = json.loads((Path(d) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def _idc_of(pid: str) -> str:
    res = idnorm.canon_id(pid)
    return res.idc if res.ok and res.idc else pid


def _cell_state(idc: str, layer: str) -> str:
    """lake cell 相对本管线的归属态：ours/conflict/build。

    无 layer 的异国 cell 不再单列 adopt——hydrate 对 complete 先者胜与
    catalog empty 皆短路返回，是否并入在 hydrate 落点后读 meta 折叠判定。
    torn ours（meta 在而 payload 缺）走 build 交 hydrate 重建修复。
    """
    meta = _cell_meta(lake.cell_dir(idc, LAKE_SOURCE))
    if not meta:
        return "build"
    if meta.get("layer") == layer and meta.get("member"):
        if (meta.get("n_files") or 0) == 0 or lake.is_complete(idc, source=LAKE_SOURCE):
            return "ours"
        return "build"
    if meta.get("layer"):
        return "conflict"
    return "build"


def _adopt_cell(idc: str, extra: dict) -> None:
    """异国 cell 原地并入 v3 meta（lake_lock 下 atomic 合并）。

    meta 缺席（异国 catalog-empty 无 dir 情形）时以 extra 起家新建——
    分母守恒优先于保守缺省。"""
    sid = idnorm.safe_id(idc)
    with lake.lake_lock(sid):
        d = lake.cell_dir(idc, LAKE_SOURCE)
        meta = _cell_meta(d)
        if meta.get("layer"):
            return
        d.mkdir(parents=True, exist_ok=True)
        meta.update(extra)
        fsutil.atomic_write(
            d / "meta.json",
            json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2).encode(
                "utf-8"
            ),
        )


def _member_meta(
    rec: dict,
    c: dict | None,
    feat: dict,
    layer: str,
    stratum: str,
    sel: dict | None = None,
    *,
    sha=None,
    nbytes=None,
    warns=None,
    main_sha=None,
    fetched_at=None,
) -> dict:
    """cell meta 字段集（旧 meta.json 全字段口径）——fetch_fn 与 adopt
    合并共用。n_files/source 由 hydrate/lake 簿记不入此集。"""
    pid = rec["id"]
    member = rec["member"]
    item = c["item"] if c else feat.get("item")
    # booster 臂旧口径：yymm 恒取成员目录头（core 取 chunk yymm）
    yymm = member.split("/")[0] if layer == "booster" or c is None else c["yymm"]
    meta = {
        "arxiv_id": pid,
        "resolved_version": None,
        "fetched_at": fetched_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "era": "old" if "/" in pid else "new",
        "archive": pid.split("/")[0] if "/" in pid else None,
        "yymm": yymm,
        "cluster_id": rec.get("cluster_id") or feat.get("cluster_id"),
        "year_band": BAND_OF_CLUSTER.get(
            rec.get("cluster_id") or feat.get("cluster_id"), ""
        ),
        "layer": layer,
        "stratum_cell": stratum,
        "cat_group": rec.get("cat_group") or feat.get("cat_group"),
        "license_class": rec.get("license_class") or feat.get("license_class"),
        "channel": c["channel"] if c else feat.get("channel"),
        "item": item,
        "member": member,
        "raw_sha256": sha,
        "raw_file": _RAW_NAME.get(feat["format"], "raw.bin"),
        "format": feat["format"],
        "tex_files": feat.get("n_tex_files"),
        "bytes": nbytes,
        "uncompressed_bytes": feat.get("uncompressed_bytes"),
        "main_tex_sha256": main_sha,
        "features": {
            k: feat[k]
            for k in (
                "docclasses",
                "docstyle",
                "docstyle_opts",
                "docclass_opts",
                "input_depth",
                "non_utf8",
                "flags",
                "flags_vendored",
                "flags_commented",
                "signatures",
                "tex_roots",
            )
            if k in feat
        },
        "warnings": warns if warns is not None else [],
    }
    if sel is not None:  # booster 臂增字段
        meta["mech_tags"] = sel.get("mech_tags", [])
        meta["pick_reason"] = sel.get("pick_reason")
    return meta


def _make_fetch(
    rec: dict,
    c: dict | None,
    feat: dict,
    layer: str,
    stratum: str,
    sel: dict | None = None,
):
    """成员级 fetch_fn 工厂——lake.hydrate(idc, fetch_fn) 的 fetch_fn。

    blob 解析序：staging tar 成员（首选，sha256 复验 scan 记录）→ 幸存 cell
    raw/（tar 被清时的回退——同样复验）。sha 不符/无源 → _MemberFault。
    """
    item = c["item"] if c else feat.get("item")
    tar_path = TARS / f"{item}.tar" if item else None
    member = rec["member"]
    fmt = feat["format"]
    raw_name = _RAW_NAME.get(fmt, "raw.bin")
    idc = _idc_of(rec["id"])

    def fetch(_idc: str, stage: Path) -> dict:
        stage = Path(stage)
        blob = None
        if tar_path is not None and tar_path.is_file():
            with tarfile.open(tar_path, "r:") as tar:
                tm = next(
                    (m for m in tar.getmembers() if m.isreg() and m.name == member),
                    None,
                )
                if tm is not None:
                    fobj = tar.extractfile(tm)
                    blob = fobj.read() if fobj else None
        if blob is None:
            # tar 缺席/成员丢失 → 幸存 cell raw 回退
            old = lake.cell_dir(idc, LAKE_SOURCE) / "raw"
            if old.is_dir():
                raws = [p for p in old.iterdir() if p.is_file()]
                if raws:
                    blob = raws[0].read_bytes()
        if blob is None:
            raise _MemberFault(cat="no_bulk_route", payload=f"{idc}:{member}")
        sha = hashlib.sha256(blob).hexdigest()
        want_sha = rec.get("blob_sha256") or feat.get("blob_sha256")
        if want_sha and sha != want_sha:
            raise _MemberFault(cat="corrupt", payload=f"{idc}:{member}")
        (stage / "raw").mkdir(parents=True, exist_ok=True)
        (stage / "raw" / raw_name).write_bytes(blob)
        warns = []
        if fmt in ("tar", "gz"):
            _n_ext, warns = unpack_blob(blob, fmt, stage)
        else:
            warns.append(f"{fmt} member — blob 留存不解包（B07 归因材料）")
        main_sha = None
        roots = feat.get("tex_roots") or []
        if len(roots) == 1:
            mp = stage / "extracted" / roots[0]
            if mp.exists():
                main_sha = hashlib.sha256(mp.read_bytes()).hexdigest()
        return _member_meta(
            rec,
            c,
            feat,
            layer,
            stratum,
            sel,
            sha=sha,
            nbytes=len(blob),
            warns=warns,
            main_sha=main_sha,
        )

    return fetch


def _extract_members(
    ctx,
    wanted: dict[str, dict[str, dict]],
    layer: str,
    stratum_fn,
    sel_of=None,
    feat_lut=None,
    prune_tars: set[str] | None = None,
) -> dict:
    """成员物化主循环——extract 与 extract_booster 共用。

    wanted: {tag: {member: rec}}（rec 带 id/cluster_id/cat_group/...）。
    feat_lut 缺省按 wanted tag 现扫 features/{tag}.jsonl（core 口径）；
    booster 臂传全局 member→feat 映射。返回计数 + faults[(cat,payload)]。

    prune_tars: 允许用完即删的 tag 集——成员循环正常收尾（非 limit 截断）
    且 tag 在集内时，该 chunk 的 .tar/.part 即删（§2.4 峰值控制）。
    """
    chunks = {f"{c['yymm']}_{c['chunk_no']:03d}": c for c in load_chunks()}
    if feat_lut is None:
        feat_lut = {}
        for tag, members_wanted in wanted.items():
            fp = WORK / "features" / f"{tag}.jsonl"
            if not fp.exists():
                continue
            for f in _read_jsonl(fp):
                if f["member"] in members_wanted:
                    feat_lut[f["member"]] = f

    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    limit = ctx.params.get("limit")
    stats = {"hydrated": 0, "reused": 0, "adopted": 0, "empty": 0, "tar_freed_bytes": 0}
    faults: list[tuple[str, str]] = []
    n_done = 0
    for tag, members in sorted(wanted.items()):
        c = chunks.get(tag)
        truncated = False
        for mname, rec in sorted(members.items()):
            if limit and n_done >= int(limit):
                truncated = True
                break
            n_done += 1
            feat = feat_lut.get(mname)
            if feat is None:
                faults.append(("canon_drift", f"{rec['id']}:{mname} 无 features 记录"))
                continue
            idc = _idc_of(rec["id"])
            state = _cell_state(idc, layer)
            if state == "ours":
                stats["reused"] += 1
                continue
            if state == "conflict":
                faults.append(("orphan_adopt", f"{idc} 异国 layer cell 占位"))
                continue
            # build/torn/foreign —— hydrate 裁决（complete 先者胜短路、
            # catalog empty 短路、torn/缺席经 fetch_fn 重建），落点后读
            # meta 折叠归属（fetch_fn 内部复读 tar/sha 复验）
            try:
                d = lake.hydrate(
                    idc,
                    fetch_fn=_make_fetch(
                        rec,
                        c,
                        feat,
                        layer,
                        stratum_fn(rec, feat),
                        sel=sel_of(rec) if sel_of else None,
                    ),
                    source=LAKE_SOURCE,
                    run_seq=run_seq,
                )
            except _MemberFault as e:
                faults.append((e.cat, e.payload))
                continue
            if d is None:
                faults.append(("no_bulk_route", f"{idc}:{mname} hydrate 空返"))
                continue
            meta = _cell_meta(d)
            if meta.get("layer") == layer and meta.get("member"):
                stats["empty" if not meta.get("n_files") else "hydrated"] += 1
            elif meta.get("layer"):
                # 锁内双检挡不住的并发先者胜（异国 complete 落点）
                faults.append(("orphan_adopt", f"{idc} hydrate 后仍异国 layer"))
            else:
                # 异国 complete/catalog-empty 短路——原地并入 v3 meta；
                # None 键滤掉不覆写既有值（fetched_at 等保原件）
                extra = _member_meta(
                    rec,
                    c,
                    feat,
                    layer,
                    stratum_fn(rec, feat),
                    sel_of(rec) if sel_of else None,
                    sha=rec.get("blob_sha256") or feat.get("blob_sha256"),
                    nbytes=feat.get("member_bytes"),
                    fetched_at=None,
                )
                _adopt_cell(idc, {k: v for k, v in extra.items() if v is not None})
                stats["adopted"] += 1
        if (
            c is not None
            and not truncated
            and prune_tars is not None
            and tag in prune_tars
        ):
            # TARS 用后即焚（§2.4 运行期峰值）：本 chunk 全部中选成员已落
            # lake cell，.tar/.part 即死存——重跑由 fetch 阶段 .part 续传
            # 自愈。limit 截断的 tag 不删：余下成员还要读它。
            stats["tar_freed_bytes"] += _prune_tar(c)
    return {**stats, "faults": faults}


def _prune_tar(c: dict) -> int:
    """删除单 chunk 的 ``{item}.tar`` 与 ``{item}.tar.part``，返回释放字节。"""
    freed = 0
    for p in (TARS / f"{c['item']}.tar", TARS / f"{c['item']}.tar.part"):
        try:
            freed += p.stat().st_size
        except FileNotFoundError:
            continue
        p.unlink()
    return freed


def _rebuild_manifest(layer: str, out_name: str) -> list[dict]:
    """manifest 行 ← lake cell meta 全量重建（denominator：行 ≡ v3 cells）。

    内存累积的替代——hydrate 后/manifest 落盘前崩不丢行：下个 run 重新
    投影时已建 cell（dedup 跳过）照样出行。
    """
    root = paths.lake_corpus_dir() / LAKE_SOURCE
    rows = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            meta = _cell_meta(d)
            if (
                meta.get("layer") != layer
                or not meta.get("member")
                or not meta.get("cluster_id")
            ):
                continue
            row = {
                "id": meta.get("arxiv_id"),
                "era": meta.get("era"),
                "archive": meta.get("archive"),
                "yymm": meta.get("yymm"),
                "cluster_id": meta.get("cluster_id"),
                "layer": layer,
                "channel": meta.get("channel"),
                "item": meta.get("item"),
                "member": meta.get("member"),
                "blob_sha256": meta.get("raw_sha256"),
                "main_tex_sha256": meta.get("main_tex_sha256"),
                "stratum_cell": meta.get("stratum_cell"),
                "cat_group": meta.get("cat_group"),
                "license_class": meta.get("license_class"),
                "format": meta.get("format"),
                "n_files": meta.get("n_files"),
                "n_tex": meta.get("tex_files"),
                "bytes": meta.get("bytes"),
            }
            if layer == "booster":
                row["mech_tags"] = meta.get("mech_tags", [])
                row["pick_reason"] = meta.get("pick_reason")
            rows.append(row)
    _atomic_write_text(
        CORPUS / out_name,
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
    )
    return rows


def _stage_extract(ctx):
    try:
        import texlate.arxiv  # noqa: F401 — unpack 产品码预检（lazy 惯例）
    except ImportError:
        ctx.emit_note("texlate.arxiv 不可导入（需项目 venv）", level="warn")
        return "fail"
    CORPUS.mkdir(exist_ok=True)
    load_allocation()  # BAND_OF_CLUSTER
    sample = json.loads((WORK / "sample_core.json").read_text())
    wanted: dict[str, dict[str, dict]] = {}
    for cid, lst in sample.items():
        for rec in lst:
            wanted.setdefault(rec["_tag"], {})[rec["member"]] = {
                **rec,
                "cluster_id": cid,
            }
    # TARS 用完即删：booster 选集缺席时本段是唯一消费者，全 tag 可删；
    # 在场时只删 booster 用不到的 chunk（其成员提取走同一批 tar）。
    prune_tars: set[str] | None = set(wanted)
    sel_path = CORPUS / "booster_selection.jsonl"
    if sel_path.is_file():
        bsel = {s["id"] for s in _read_jsonl(sel_path) if s.get("id")}
        tag_of_item = {
            c["item"]: f"{c['yymm']}_{c['chunk_no']:03d}" for c in load_chunks()
        }
        btags: set[str] = set()
        fdir = WORK / "features"
        if fdir.is_dir():
            for ff in sorted(fdir.glob("*.jsonl")):
                for f in _read_jsonl(ff):
                    if f.get("id") in bsel:
                        btags.add(tag_of_item.get(f["item"], "unknown"))
        prune_tars = set(wanted) - btags
    stats = _extract_members(
        ctx,
        wanted,
        "core",
        lambda rec, _feat: (
            f"{BAND_OF_CLUSTER.get(rec['cluster_id'], '')}|{rec.get('cat_group')}"
        ),
        prune_tars=prune_tars,
    )
    manifest = _rebuild_manifest("core", "manifest.jsonl")
    _write_manifest_md(manifest)
    faults = stats.pop("faults")
    log(f"extract done: {stats} | manifest {len(manifest)} rows -> {CORPUS}")
    return {
        "status": "partial" if faults else "ok",
        "metrics": {**stats, "manifest_rows": len(manifest)},
        "errors": [{"cat": cat, "payload": p} for cat, p in faults[:50]],
    }


def _write_manifest_md(manifest: list[dict]) -> None:
    n = len(manifest)
    fmt_c = Counter(r["format"] for r in manifest)
    era_c = Counter(r["era"] for r in manifest)
    ch_c = Counter(r["channel"] for r in manifest)
    cl_c = Counter(r["cluster_id"] for r in manifest)
    lines = [
        "# Corpus v3 Manifest — arXiv 月度簇分层抽样源码语料",
        "",
        (
            "渠道钉版批量语料: a–d 带 IA `arxiv-bulk` 月 chunk / e 带 HF "
            "`TIGER-Lab/arxiv-latex-5T`（成员四元组 "
            "`(channel,item,member,blob_sha256)` 钉版，`resolved_version=null`）。"
        ),
        (
            "数据在 lake `corpus/arxiv/{safe_id}/` cell（meta.json+raw+extracted），"
            "入库清单：`manifest.jsonl`（核心）/`manifest_booster.jsonl`（补强）/"
            "`manifest_expand.jsonl`（扩展）/`manifest_hot.jsonl`（热层）/"
            "`mechanisms.jsonl`/`booster_selection.jsonl`；管线 spec 在 "
            "`bench/py/specs/`。"
        ),
        ("抽样管线见 `docs/spec/corpus.md` S0–S5；旧式 ID 按 `archive/name` 嵌套。"),
        "",
        (
            f"- 入库 **{n}** 篇（核心层）· {sum(r['n_tex'] or 0 for r in manifest)} "
            f"个 .tex · 原始包共 {sum(r.get('bytes') or 0 for r in manifest) / 1e6:.0f}M"
        ),
        f"- 打包形式: {dict(fmt_c)}",
        f"- 年代: {dict(era_c)} · 渠道: {dict(ch_c)}",
        (f"- 簇: {len(cl_c)} 个, 每簇 {min(cl_c.values())}–{max(cl_c.values())} 篇")
        if cl_c
        else "- 簇: 0",
        "",
        "| ID | era | yymm | 簇 | cat_group | license | 格式 | .tex |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {r['id']} | {r['era']} | {r['yymm']} | {r['cluster_id']} "
        f"| {r['cat_group']} | {r.get('license_class') or '-'} "
        f"| {r['format']} | {r['n_tex']} |"
        for r in sorted(manifest, key=lambda r: (r["cluster_id"], r["id"]))
    )
    md = CORPUS / "MANIFEST.md"
    if md.exists() and "## 补强层" in md.read_text(encoding="utf-8"):
        # 现行 MANIFEST.md 含手补的 booster/hot/expand 策展段——整文件重写
        # 会把它们抹掉; 核心表如需重生成请人工合并进现有文件
        log("MANIFEST.md 含策展段，跳过重写（核心表如需更新请手工合并）")
        return
    _atomic_write_text(md, "\n".join(lines) + "\n")


def _stage_extract_booster(ctx):
    """S3b→S4：booster_selection.jsonl 的补强篇物化（layer=booster）。

    选集由 booster-select 动词产出；成员定位走 features.jsonl（id→member/
    item/sha256 全在）。manifest_booster.jsonl 独立文件不碰核心。
    """
    sel_path = CORPUS / "booster_selection.jsonl"
    if not sel_path.is_file():
        ctx.emit_note(
            "booster_selection.jsonl 缺席——booster-select 动词未跑，skip 留下轮",
            level="info",
        )
        return "skip"
    try:
        import texlate.arxiv  # noqa: F401
    except ImportError:
        ctx.emit_note("texlate.arxiv 不可导入（需项目 venv）", level="warn")
        return "fail"
    CORPUS.mkdir(exist_ok=True)
    load_allocation()
    sel = _read_jsonl(sel_path)
    want = {s["id"]: s for s in sel if s.get("id")}
    feat_by_id: dict[str, dict] = {}
    fdir = WORK / "features"
    if fdir.is_dir():
        for ff in sorted(fdir.glob("*.jsonl")):
            for f in _read_jsonl(ff):
                if f.get("id") in want:
                    feat_by_id[f["id"]] = f
    skipped = sorted(set(want) - set(feat_by_id))
    for pid in skipped:
        log(f"!! {pid} 无 features 记录（member 定位失败——跳过）")

    # frame join 补 cat_group/license_class（旧 extract_booster 同款 lut 回查）
    lut = load_frame_lookup() if (WORK / "frame_lookup.tsv.gz").exists() else {}
    chunks = load_chunks()
    tag_of_item = {c["item"]: f"{c['yymm']}_{c['chunk_no']:03d}" for c in chunks}
    wanted: dict[str, dict[str, dict]] = {}
    feat_lut: dict[str, dict] = {}
    for f in feat_by_id.values():
        fr = frame_get(lut, f["id"]) or {}
        tag = tag_of_item.get(f["item"], "unknown")
        wanted.setdefault(tag, {})[f["member"]] = {
            "id": f["id"],
            "member": f["member"],
            "_tag": tag,
            "cluster_id": f.get("cluster_id"),
            "cat_group": fr.get("cat_group"),
            "license_class": fr.get("license_class"),
            "blob_sha256": f.get("blob_sha256"),
            "format": f.get("format"),
        }
        feat_lut[f["member"]] = f

    stats = _extract_members(
        ctx,
        wanted,
        "booster",
        lambda rec, feat: (
            f"booster|"
            f"{BAND_OF_CLUSTER.get(rec.get('cluster_id') or feat.get('cluster_id'), '')}"
        ),
        sel_of=lambda rec: want.get(rec["id"]),
        feat_lut=feat_lut,
        prune_tars=set(wanted),  # booster 是 TARS 末段消费者，用完即删
    )
    manifest = _rebuild_manifest("booster", "manifest_booster.jsonl")
    faults = stats.pop("faults")
    log(
        f"extract_booster done: {stats} | manifest {len(manifest)} rows"
        + (
            f" | skipped(no features): {len(skipped)} {skipped[:10]}"
            + ("…" if len(skipped) > 10 else "")
            if skipped
            else ""
        )
    )
    errors = [{"cat": cat, "payload": p} for cat, p in faults[:50]]
    errors += [{"cat": "canon_drift", "payload": p} for p in skipped[:20]]
    return {
        "status": "partial" if (faults or skipped) else "ok",
        "metrics": {
            **stats,
            "manifest_rows": len(manifest),
            "want": len(want),
            "no_features": len(skipped),
        },
        "errors": errors,
    }


# ---------------- qc (S5) ----------------


def _qc(ctx):
    import subprocess

    problems: list[str] = []
    manifest = _read_jsonl(CORPUS / "manifest.jsonl")
    ids = [r["id"] for r in manifest]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        problems.append(f"id 重复: {dup[:8]}")
    v2_dir = REPO / "bench" / "corpus_v2"
    overlap: list = []
    if v2_dir.is_dir():
        v2_ids = {p.name for p in v2_dir.iterdir() if p.is_dir()}
        v2_ids |= {
            f"{p.parent.name}/{p.name}" for p in v2_dir.glob("*/*") if p.is_dir()
        }
        overlap = sorted(set(ids) & v2_ids)
        if overlap:
            problems.append(f"与 corpus_v2 重叠: {overlap[:8]}")
    # lake 对账：manifest 行 → cell complete（empty 态 pdf/stub 是合法终态）
    missing = []
    for r in manifest:
        idc = _idc_of(r["id"])
        d = lake.cell_dir(idc, LAKE_SOURCE)
        meta = _cell_meta(d)
        if not meta:
            missing.append(r["id"])
    if missing:
        problems.append(f"manifest 行无 lake cell: {missing[:8]} (n={len(missing)})")
    report_path = WORK / "sample_report.json"
    report = json.loads(report_path.read_text()) if report_path.is_file() else []
    n_stub = sum(r["format_dist"].get("stub", 0) for r in report)
    n_pdf = sum(r["format_dist"].get("pdf", 0) for r in report)
    n_err = sum(r["format_dist"].get("error", 0) for r in report)
    total = sum(r["members_scanned"] for r in report)
    # manifest tracked 断言（dossier③：spec emit metric，doctor 面留给 kernel）
    tracked = 0
    try:
        r = subprocess.run(
            [
                "git",
                "ls-files",
                "--error-unmatch",
                "bench/corpus/manifest.jsonl",
                "bench/corpus/manifest_booster.jsonl",
                "bench/corpus/MANIFEST.md",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=30,
        )
        tracked = int(r.returncode == 0)
    except (OSError, subprocess.TimeoutExpired):
        tracked = 0
    lines = [
        "# corpus P2 自检",
        "",
        f"- 核心层入库: **{len(manifest)}** / 目标 1000",
        f"- id 重复: {dup or '无'}",
        f"- 与 corpus_v2 重叠: {overlap or '无'}",
        (f"- manifest 行无 lake cell: {missing[:8] or '无'} (n={len(missing)})"),
        (
            f"- 扫描成员总数: {total}（pdf_only {n_pdf} · stub {n_stub} "
            f"· error {n_err}）"
        ),
        f"- manifests_tracked: {tracked}",
        "",
        "| 簇 | yymm | 配额 | 扫描 | 合格 | 中选 | join_miss |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {r['cluster_id']} | {r['yymm']} | {r['quota']} "
        f"| {r['members_scanned']} | {r['eligible']} "
        f"| {r['picked']} | {r['frame_join_miss']} |"
        for r in report
    )
    _atomic_write_text(WORK / "qc_report.md", "\n".join(lines) + "\n")
    print("\n".join(lines[:8]))
    return {
        "status": "fail" if problems else "clean",
        "metrics": {
            "core_rows": len(manifest),
            "dup_ids": len(dup),
            "v2_overlap": len(overlap),
            "lake_missing": len(missing),
            "members_scanned": total,
            "manifests_tracked": tracked,
        },
        "errors": [{"cat": "index_unsealed", "payload": p} for p in problems],
    }


# ---------------- spec ----------------

_STATUS = {
    "ok": "terminal",
    "clean": "terminal",
    "partial": "terminal",
    "fail": "terminal",
    "skip": "retriable",
    "error": "retriable",
}

spec = Spec(
    kind="corpus_v3",
    # eval=True 是单件非论文 id 的 canon 豁免口（非 eval item 全过
    # canon_id，"corpus-v3" 不是 arXiv 形会被丢；
    # 副作用仅 cell 事件 eval=True 标记，无 stage.eval 行）。
    eval=True,
    items=[{"id": "corpus-v3"}],
    params={
        "channel": Param(type=str, default=None, choices=["ia", "tiger"], fp=False),
        "jobs": Param(type=int, default=4),
        "limit": Param(type=int, default=None, fp=False),
    },
    stages=[
        Stage("plan", _plan, status_class=dict(_STATUS)),
        Stage("fetch", _fetch, needs=[("plan", {"ok"})], status_class=dict(_STATUS)),
        Stage("zipsum", _zipsum, needs=[("fetch", {"ok"})], status_class=dict(_STATUS)),
        Stage("scan", _scan, needs=[("fetch", {"ok"})], status_class=dict(_STATUS)),
        Stage(
            "frame_lookup",
            _frame_lookup,
            needs=[("scan", {"ok"})],
            status_class=dict(_STATUS),
        ),
        Stage(
            "sample",
            _sample,
            needs=[("frame_lookup", {"ok"})],
            status_class=dict(_STATUS),
        ),
        Stage(
            "extract",
            _stage_extract,
            needs=[("sample", {"ok"})],
            status_class=dict(_STATUS),
        ),
        Stage(
            "extract_booster",
            _stage_extract_booster,
            needs=[("sample", {"ok"})],
            status_class=dict(_STATUS),
        ),
        Stage("qc", _qc, needs=[("extract", {"ok"})], status_class=dict(_STATUS)),
    ],
)
