"""_corpus_common — corpus builder 共享叶（expand/layers/hot/v3 各臂共用）。

逐字提升自 ``bench/py/corpus/build_corpus_v3.py`` +
``build_corpus_expand.py`` + ``benchlib.py`` 三处（皆已随删除门退役）。
import 期纯 stdlib——``texlate.arxiv``/``pyarrow`` 一律惰性 import 在使用点
内（scan 链路系统 python3 可载，extract/fetch-ids 臂经 ``uv run`` 进产品环境）。

工作区契约（post-work_v3）：持久 builder 状态落
``~/.local/state/texlate/corpus-build/<layer>/`` —— TarDirs 标准布局
{features,members,tars,meta} 每层一束（先例为已退役 errsweep 的 state 目录布局）。
``frame_lookup.tsv.gz`` 全 builder 共享单件：
``corpus-build/frame_lookup.tsv.gz``，``ensure_frame_lookup`` 缺时从
``bench/frame/frame.parquet`` 现算（谁先跑谁建，幂等）。

公开面（layers spec 消费边界）::

    TarDirs / TarDirs.from_workdir
    log open_url item_url band_of_yymm member_yymm
    download_item scan_item scan_batch offsets_for fetch_blob
    remote_size                      # meta API 缓存内含
    member_id blob_features extracted_features eligible safe_name unpack_blob
    frame_lookup_path ensure_frame_lookup load_frame_lookup frame_filter
    frame_meta_for frame_get yymm2cluster band_cat_share load_chunks
    iter_jsonl read_jsonl write_jsonl append_jsonl atomic_write_text
    strip_comments canon_id canon_or_self cell_meta
    manifest_paths load_manifest_rows manifest_layers corpus_ids
    largest_remainder load_ids_file
    materialize_into_stage materialize_entry_into_stage manifest_row_from_meta
    RAW_NAME IA_DL IA_META TIGER_DL
    SEED RUN_REF_RX FRAME_NEEDS HaltFetch TransientMiss
    load_plan bad_rates rates_from_idstatus run_id_statuses resolve_rates
    order_items candidate_items member_fetch_fn extract_selected
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
import shutil
import sys
import tarfile
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[3]
CORPUS = REPO / "bench" / "corpus"
FRAME = REPO / "bench" / "frame"
UA = {"User-Agent": "texlate-corpus-v3/1.0 (research benchmark build)"}
TIMEOUT = 60

IA_DL = "https://archive.org/download/{item}/{item}.tar"
IA_META = "https://archive.org/metadata/{item}"
TIGER_DL = (
    "https://huggingface.co/datasets/TIGER-Lab/arxiv-latex-5T/resolve/main/{name}.tar"
)

#: 持久 builder 状态根（work_v3 已灭后的新家；布局先例为已退役 errsweep 的 state 目录）。
BUILD_ROOT = Path.home() / ".local" / "state" / "texlate" / "corpus-build"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- jsonl / 文件 IO
# jsonl 三件 + strip_comments 正本在 _benchlite（benchlib 收编叶）——本叶
# re-export 保旧调用形，勿再长第三份 verbatim。
from kernel import fsutil, idnorm, lake, paths
from kernel import index as indexmod

from specs._benchlite import (
    append_jsonl,
    iter_jsonl,
    read_jsonl,
    strip_comments,
)


def atomic_write_text(path: Path, text: str) -> None:
    """kernel ``fsutil.atomic_write`` 的 text 形委托（fsync+dir fsync 全耐久
    口径；corpus_v3._atomic_write_text 同构）。父目录须先存在。"""
    fsutil.atomic_write(Path(path), text.encode("utf-8"))


def canon_id(pid: str) -> str:
    """论文 id 规范形：safe_id 的逆（混合双形归一）——委托 kernel
    ``idnorm.idc_from_safe`` 单源（末个 ``--`` 才是分隔符）。"""
    return idnorm.idc_from_safe(str(pid))


# ---------------------------------------------------------------- manifest
def manifest_paths(corpus: Path, layers) -> list[tuple[str, Path]]:
    """corpus 分层 manifest → [(layer, path)]；不存在的层跳过。"""
    out = []
    for layer in layers:
        fp = corpus / (
            "manifest.jsonl" if layer == "core" else f"manifest_{layer}.jsonl"
        )
        if fp.exists():
            out.append((layer, fp))
    return out


def load_manifest_rows(corpus: Path, layers) -> list[dict]:
    """分层 manifest → [{...,"layer": layer}]；行缺 layer 字段时补所在层。"""
    rows: list[dict] = []
    for layer, fp in manifest_paths(corpus, layers):
        for rec in read_jsonl(fp):
            rec.setdefault("layer", layer)
            rows.append(rec)
    return rows


def manifest_layers(corpus: Path) -> list[str]:
    """磁盘在册的全部层名：manifest.jsonl→core、manifest_X.jsonl→X。"""
    out = []
    for fp in sorted(corpus.glob("manifest*.jsonl")):
        if fp.name == "manifest.jsonl":
            out.append("core")
        elif fp.name.startswith("manifest_"):
            out.append(fp.stem.removeprefix("manifest_"))
    return out


def corpus_ids(corpus: Path) -> set[str]:
    """全层 id 并集（canon 归一）——去重/qc 单源。"""
    return {
        canon_id(r["id"])
        for r in load_manifest_rows(corpus, manifest_layers(corpus))
        if r.get("id")
    }


def existing_ids(corpus: Path) -> set[str]:
    return corpus_ids(corpus)


# ---------------------------------------------------------------- 网络/下载
def open_url(url: str, headers: dict | None = None, timeout: int = TIMEOUT):
    req = urllib.request.Request(  # noqa: S310 — bench 下载脚本, URL 全是固定 https 端点
        url, headers={**UA, **(headers or {})}
    )
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — 同上


def item_url(channel: str, item: str) -> str:
    if channel == "ia":
        return IA_DL.format(item=item)
    return TIGER_DL.format(name=item)


def remote_size(it: dict, meta_dir: Path) -> int:
    """权威 size: ia 走 metadata API（item-index 尺寸有过期记录）并缓存于
    meta_dir; tiger 用索引 LFS size."""
    if it["channel"] == "tiger":
        return it["size"]
    meta_dir.mkdir(parents=True, exist_ok=True)
    cache = meta_dir / f"{it['item']}.json"
    meta = None
    if cache.exists():
        try:
            meta = json.loads(cache.read_text())
        except (OSError, json.JSONDecodeError):
            cache.unlink(missing_ok=True)  # 截尾缓存每次重跑都炸——弃掉重抓
    if meta is None:
        with open_url(IA_META.format(item=it["item"])) as r:
            meta = json.loads(r.read())
        atomic_write_text(cache, json.dumps(meta))
    for f in meta.get("files", []):
        if f["name"] == f"{it['item']}.tar":
            it["sha1"] = f.get("sha1")
            return int(f["size"])
    return it["size"]


def _verify_content(path: Path, it: dict) -> None:
    """尺寸之外的内容校验: ia→meta sha1, tiger→lfs oid16(sha256 前缀). 单遍流式."""
    want_sha1 = it.get("sha1")
    want_oid = it.get("oid16")
    if not want_sha1 and not want_oid:
        return
    h256 = hashlib.sha256()
    h1 = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(1 << 22), b""):
            h256.update(buf)
            h1.update(buf)
    if want_sha1 and h1.hexdigest() != want_sha1:
        msg = f"sha1 {h1.hexdigest()[:12]} != meta {want_sha1[:12]}"
        raise OSError(msg)
    if want_oid and not h256.hexdigest().startswith(want_oid):
        msg = f"sha256 {h256.hexdigest()[:16]} != oid16 {want_oid}"
        raise OSError(msg)


def download_item(it: dict, dest_dir: Path, meta_dir: Path) -> Path:
    """item tar → dest_dir/{item}.tar（.part+Range 续传, 尺寸+内容校验）."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    part = dest_dir / f"{it['item']}.tar.part"
    final = dest_dir / f"{it['item']}.tar"
    want = remote_size(it, meta_dir)
    if final.exists() and final.stat().st_size == want:
        # 尺寸对≠内容对: 腐 final 曾让本函数静默返回坏 tar(探针实证)——
        # 验不过就删掉落回下载循环重抓
        try:
            _verify_content(final, it)
        except OSError as e:
            log(f"  {it['item']} existing tar corrupt: {e} — 重抓")
            final.unlink()
        else:
            return final
    for attempt in range(4):
        have = part.stat().st_size if part.exists() else 0
        if have == want:
            try:
                _verify_content(part, it)
            except OSError as e:
                log(f"  {it['item']} .part 腐坏: {e} — 重抓")
                part.unlink()
                have = 0
            else:
                part.rename(final)
                return final
        if have > want:
            part.unlink()
            have = 0
        try:
            headers = {"Range": f"bytes={have}-"} if have else {}
            r = open_url(it["url"], headers=headers, timeout=180)
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
            if part.stat().st_size == want:
                _verify_content(part, it)
                part.rename(final)
                return final
            log(f"  {it['item']} partial {part.stat().st_size}/{want}")
        except Exception as e:
            log(f"  {it['item']} dl#{attempt}: {type(e).__name__}: {e}")
            time.sleep(5 * (attempt + 1))
    msg = f"{it['item']} download failed"
    raise OSError(msg)


# ---------------------------------------------------------------- TarDirs / 扫描
class TarDirs(NamedTuple):
    """IA tar 管线的层工作区——下载/扫描各目录一束.

    每层注入 ``corpus-build/{layer}/`` 下同构目录——同一套 .part 续传/
    成员级断点机器, 只是落点不同.
    """

    workdir: Path  # scan_log 等层记录落点
    features: Path
    members: Path
    tars: Path
    meta: Path

    @classmethod
    def from_workdir(cls, workdir: Path) -> TarDirs:
        """标准布局: {features,members,tars,meta} 全在 workdir 下."""
        return cls(
            workdir,
            workdir / "features",
            workdir / "members",
            workdir / "tars",
            workdir / "meta",
        )


def band_of_yymm(yymm: str) -> str:
    """'9910'→'a_pre2007' … '2105'→'e_2021_25'（成员月即 item 月）."""
    yy = int(yymm[:2])
    year = 1900 + yy if yy >= 91 else 2000 + yy
    ym = year * 100 + int(yymm[2:])
    if ym < 200701:
        return "a_pre2007"
    if ym < 201201:
        return "b_2007_11"
    if ym < 201701:
        return "c_2012_16"
    if ym < 202101:
        return "d_2017_20"
    return "e_2021_25"


def member_yymm(member: str) -> str:
    return member.split("/", 1)[0]


def scan_item(it: dict, dirs: TarDirs) -> str:
    """单 item: 下载→流扫(成员级断点)→.done→删 tar."""
    item = it["item"]
    done_f = dirs.features / f"{item}.done"
    if done_f.exists():
        return "done-skip"
    dirs.features.mkdir(parents=True, exist_ok=True)
    dirs.members.mkdir(parents=True, exist_ok=True)
    fjsonl = dirs.features / f"{item}.jsonl"
    mjsonl = dirs.members / f"{item}.jsonl"
    done_members = (
        {r["member"] for r in iter_jsonl(fjsonl) if r.get("member")}
        if fjsonl.exists()
        else set()
    )
    tar_path = download_item(it, dirs.tars, dirs.meta)
    n = len(done_members)
    t0 = time.time()
    with (
        tarfile.open(tar_path, "r|") as tar,
        open(fjsonl, "a") as fw,
        open(mjsonl, "a") as mw,
    ):
        for m in tar:
            if not m.isreg():
                continue
            if m.name in done_members:
                continue  # 流式跳过已扫成员（读穿不处理）
            bf = tar.extractfile(m)
            blob = bf.read() if bf else b""
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
            rec.pop("_texts", None)  # 扩库不留 staging
            rec["item"] = item
            rec["channel"] = it["channel"]
            rec["band"] = band_of_yymm(it["yymm"])
            mw.write(
                json.dumps({"name": m.name, "size": m.size, "offset": m.offset_data})
                + "\n"
            )
            mw.flush()
            fw.write(json.dumps(rec) + "\n")
            fw.flush()
            n += 1
            if n % 1000 == 0:
                log(f"  {item}: {n} members {time.time() - t0:.0f}s")
    done_f.write_text(f"{n} members\n")
    tar_path.unlink(missing_ok=True)
    (dirs.tars / f"{item}.tar.part").unlink(missing_ok=True)
    return f"scanned {n}"


def scan_batch(items: list[dict], dirs: TarDirs, jobs: int, tag: str = "") -> list[str]:
    """ThreadPool 批量 scan_item + scan_log 落账（expand 与分层构建器共用）。

    返回失败 item 名单（调用方据此定 ok/partial 终态）。"""
    todo = [it for it in items if not (dirs.features / f"{it['item']}.done").exists()]
    log(f"scan{tag}: {len(todo)}/{len(items)} items pending")
    errs = []
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(scan_item, it, dirs): it for it in todo}
        for fut in as_completed(futs):
            it = futs[fut]
            state = "done"
            try:
                st = fut.result()
                log(f"ok {it['item']} ({it['size'] / 1e6:.0f}MB {it['channel']}): {st}")
            except Exception as e:
                errs.append(it["item"])
                state = "failed"
                log(f"FAIL {it['item']}: {type(e).__name__}: {e}")
            append_jsonl(
                dirs.workdir / "scan_log.jsonl",
                {"item": it["item"], "state": state, "ts": time.strftime("%FT%T")},
            )
    log(f"scan pass done, {len(errs)} failed: {errs or '-'}")
    return errs


def offsets_for(
    item: str,
    members_dir: Path,
    tag_of_item: dict[str, str] | None = None,
    fallback_members_dir: Path | None = None,
) -> dict[str, tuple[int, int]]:
    """item → {member: (offset, size)}; members_dir 下 {item}.jsonl 直读,
    缺档且给了 tag/fallback 时回退旧池 {fallback_members_dir}/{tag}.jsonl."""
    out = {}
    p = members_dir / f"{item}.jsonl"
    if not p.exists() and tag_of_item and fallback_members_dir and item in tag_of_item:
        p = fallback_members_dir / f"{tag_of_item[item]}.jsonl"
    if p.exists():
        for r in iter_jsonl(p):
            off = r.get("offset", r.get("offset_data"))
            if off is None:
                continue  # 缺 offset 记录留给「无 offset」过滤统一报
            out[r["name"]] = (off, r["size"])
    return out


def fetch_blob(rec: dict, old_tars: dict[str, Path], offs: dict[str, dict]) -> bytes:
    """成员 blob: 旧池本地 tar 随机读; 新池 tar URL Range GET（重试 3 轮）."""
    item, member = rec["item"], rec["member"]
    off, size = offs[item][member]
    if item in old_tars:
        with open(old_tars[item], "rb") as f:
            f.seek(off)
            data = f.read(size)
        if len(data) != size:
            msg = f"local short read {len(data)}/{size}"
            raise OSError(msg)
        return data
    url = item_url(rec["channel"], item)
    last = ""
    for attempt in range(3):
        try:
            r = open_url(
                url,
                headers={"Range": f"bytes={off}-{off + size - 1}"},
                timeout=120,
            )
            try:
                # size+1 封顶: 服务端不理会 Range 时不至于把整 tar 读进内存
                data = r.read(size + 1)
            finally:
                r.close()
            if len(data) == size:
                return data
            last = f"read {len(data)}/{size}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(3 * (attempt + 1))
    err = f"{item}/{member}: {last}"
    raise OSError(err)


# ---------------------------------------------------------------- frame 资产
def frame_lookup_path(build_root: Path = BUILD_ROOT) -> Path:
    """全 builder 共享的 frame_lookup.tsv.gz 落点（corpus-build 根）。"""
    return Path(build_root) / "frame_lookup.tsv.gz"


def ensure_frame_lookup(frame_dir: Path = FRAME, build_root: Path = BUILD_ROOT) -> Path:
    """frame.parquet → frame_lookup.tsv.gz（缺时现算；pyarrow 惰性）。

    v3/expand/layers 谁先到谁建——原子写幂等。缺 frame.parquet → OSError
    （frame_build ord-0 前置未跑，调用方按 fail-closed 处理）。"""
    out = frame_lookup_path(build_root)
    if out.exists():
        return out
    import pyarrow.parquet as pq

    src = Path(frame_dir) / "frame.parquet"
    t = pq.read_table(
        src,
        columns=[
            "id",
            "tar_yymm",
            "year_band",
            "cat_group",
            "primary_cat",
            "license_class",
        ],
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as f:
        cols = [t.column(n).to_pylist() for n in t.column_names]
        for row in zip(*cols, strict=True):
            f.write("\t".join("" if v is None else str(v) for v in row) + "\n")
    os.replace(tmp, out)
    log(f"frame_lookup: {t.num_rows} rows -> {out}")
    return out


def load_frame_lookup(path: Path) -> dict[str, dict]:
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


def frame_filter(pool_ids: set[str], path: Path) -> dict[str, dict]:
    """frame_lookup 只留 pool 内 id 的行（全量 3.16M 行驻留太大, 过滤装载）."""
    lut: dict[str, dict] = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            pid = line.split("\t", 1)[0]
            if pid in pool_ids:
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


def frame_meta_for(ids: list[str], path: Path) -> dict[str, dict]:
    """frame_lookup 流式过滤 → {id: {tar_yymm, year_band, cat_group, license_class}}."""
    want = set(ids)
    out: dict[str, dict] = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            pid = line.split("\t", 1)[0]
            if pid in want:
                p = line.rstrip("\n").split("\t")
                out[pid] = {
                    "tar_yymm": p[1] if len(p) > 1 else None,
                    "year_band": p[2] if len(p) > 2 else None,
                    "cat_group": p[3] if len(p) > 3 else None,
                    "primary_cat": p[4] if len(p) > 4 else None,
                    "license_class": p[5] if len(p) > 5 else None,
                }
            if len(out) == len(want):
                break
    return out


def frame_get(lut: dict, pid: str) -> dict | None:
    """成员 id → frame 行; 旧式 math.XX/ 归并 math/ 回退."""
    r = lut.get(pid)
    if r is None and "/" in pid:
        arch, num = pid.split("/", 1)
        if "." in arch:
            r = lut.get(f"{arch.split('.')[0]}/{num}")
    return r


def yymm2cluster(frame_dir: Path = FRAME) -> dict[str, str]:
    with (Path(frame_dir) / "allocation-core.csv").open(newline="") as fh:
        return {r["yymm"]: r["cluster_id"] for r in csv.DictReader(fh)}


def cluster2band(frame_dir: Path = FRAME) -> dict[str, str]:
    with (Path(frame_dir) / "allocation-core.csv").open(newline="") as fh:
        return {r["cluster_id"]: r["year_band"] for r in csv.DictReader(fh)}


def band_cat_share(frame_dir: Path = FRAME) -> dict[str, dict[str, float]]:
    """cluster-cat-mix → {band: {cat: share}}（带内聚合, 估算 item 产出用）."""
    agg: dict[str, Counter] = defaultdict(Counter)
    with (Path(frame_dir) / "cluster-cat-mix.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            agg[r["year_band"]][r["cat_group"]] += int(r["n"])
    return {
        b: {c: n / sum(cs.values()) for c, n in cs.items()} for b, cs in agg.items()
    }


def load_chunks(v3_workdir: Path) -> list[dict]:
    """v3 builder 的 chunks.json（旧池 membership 单源）；缺档 → []."""
    p = Path(v3_workdir) / "chunks.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------- blob 特征机器
# （build_corpus_v3 verbatim：特征口径单源——scan_tar 与 extracted 树共用。）
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
    features，供归因/狩猎区分真缺陷与形态签名（W48 协作残留、W88 手排、W70 typo 等）。"""
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


def extracted_features(extract_dir: Path) -> dict:
    """已解压 extracted/ 树 → 同口径特征 dict(fetch-ids 通道的补齐件)。"""
    texts: dict[str, bytes] = {}
    for fp in sorted(extract_dir.rglob("*")):
        if (
            fp.is_file()
            and fp.suffix.lower() in TEXT_EXT
            and fp.stat().st_size < 8 << 20
        ):
            texts[str(fp.relative_to(extract_dir))] = fp.read_bytes()
    tex_texts: dict[str, str] = {}
    non_utf8 = False
    for p, b in texts.items():
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            non_utf8 = True
            s = b.decode("utf-8", "replace")
        if Path(p).suffix.lower() == ".tex":
            tex_texts[p] = s
    rec = _texts_features(tex_texts, texts)
    rec["non_utf8"] = non_utf8
    return rec


def eligible(f: dict) -> bool:
    return f.get("format") in ("tar", "gz") and (f.get("n_tex_files") or 0) >= 1


def safe_name(name: str) -> str | None:
    p = Path(name.lstrip("./"))
    if p.is_absolute() or ".." in p.parts:
        return None
    return str(p)


def unpack_blob(blob: bytes, fmt: str, dest: Path) -> tuple[int, list[str]]:
    """raw e-print blob → ``dest/extracted/``（归并产品 ``texlate.arxiv`` unpack）。

    sniff 做有上限 gunzip + 魔数复核——``fmt`` 只是扫描侧标注，内容优先、不符
    记 fmt_mismatch 告警；tar 走产品逐成员过滤（容量/setuid/link/casefold/
    stub），单文件 gz 沿用旧命名：tex → ``main.tex``、ps/pdf payload 按真实
    扩展名落盘。非 tar/gz 与解包硬错误 → ``(0, warns)``，不炸批。
    """
    from texlate.arxiv import (  # 惰性——本叶 import 期纯 stdlib 约定
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


# ---------------------------------------------------------------- 物化（lake cell stage）
RAW_NAME = {
    "tar": "raw.tar.gz",
    "gz": "raw.gz",
    "pdf": "raw.pdf",
    "stub": "raw.stub",
    "error": "raw.bin",
}


def materialize_into_stage(
    rec: dict,
    blob: bytes,
    sha: str,
    stage: Path,
    *,
    layer: str,
    cluster_prefix: str,
    reason: str,
) -> dict:
    """成员 blob → ``{stage}/raw/{raw_name}`` + ``{stage}/extracted/`` +
    meta dict（lake.hydrate fetch_fn 的返回值——lake 自写 meta.json）。

    layer/cluster_prefix/reason 分层注入：expand 传 ("expand","EXP",
    "expand_quota")；layers 传层名+簇前缀, pick_reason=f"{reason}:{_cell}".
    """
    stage = Path(stage)
    pid = rec["id"]
    fmt = rec["format"]
    raw_name = RAW_NAME[fmt]
    raw_dir = stage / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / raw_name).write_bytes(blob)
    n_ext, warns = unpack_blob(blob, fmt, stage)
    roots = rec.get("tex_roots") or []
    main_sha = None
    if len(roots) == 1:
        mp = stage / "extracted" / roots[0]
        if mp.exists():
            main_sha = hashlib.sha256(mp.read_bytes()).hexdigest()
    era = "old" if "/" in pid else "new"
    yymm = member_yymm(rec["member"])
    # _cell 形态：配额层 "band|cat"；矿层 "flag:X"/"failmine_fill" → band 取 features 记录
    band = rec["_cell"].split("|", 1)[0]
    if band.startswith("flag:") or band == "failmine_fill" or "|" not in rec["_cell"]:
        band = rec.get("band") or band_of_yymm(yymm)
    meta = {
        "arxiv_id": pid,
        "resolved_version": None,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "era": era,
        "archive": pid.split("/")[0] if "/" in pid else None,
        "yymm": yymm,
        "cluster_id": rec.get("cluster_id") or f"{cluster_prefix}-{band}",
        "year_band": band,
        "layer": layer,
        "stratum_cell": rec["_cell"],
        "cat_group": rec.get("cat_group"),
        "license_class": rec.get("license_class"),
        "channel": rec["channel"],
        "item": rec["item"],
        "member": rec["member"],
        "raw_sha256": sha,
        "raw_file": raw_name,
        "format": fmt,
        "n_tex_files": rec.get("n_tex_files"),
        "bytes": len(blob),
        "uncompressed_bytes": rec.get("uncompressed_bytes"),
        "main_tex_sha256": main_sha,
        # 特征以 extracted 树重算为准(expand scan 记录仍是旧合并口径——
        # 无 staging 无法回填; extracted_features 与 blob_features 同一生成码)
        "features": extracted_features(stage / "extracted"),
        "pick_reason": f"{reason}:{rec['_cell']}",
        "warnings": warns,
        "source": rec["channel"],
    }
    if rec.get("_pool"):  # expand 选样记 _pool; 分层构建器无此字段
        meta["pool"] = rec["_pool"]
    meta["n_extracted_files"] = n_ext
    return meta


def manifest_row_from_meta(
    meta: dict, cell_dir: Path | None = None, default_layer: str = "expand"
) -> dict | None:
    """meta dict（或 cell_dir/meta.json）→ manifest 行（幂等回补同口径）。

    lake 版差异：main_tex_sha256 由物化时直写 meta（旧版回补时重算——
    同一字段两处口径等价）。"""
    if meta is None and cell_dir is not None:
        try:
            meta = json.loads((Path(cell_dir) / "meta.json").read_text())
        except Exception:
            return None
    if not isinstance(meta, dict) or not meta:
        return None
    main_sha = meta.get("main_tex_sha256")
    if main_sha is None and cell_dir is not None:
        roots = (meta.get("features") or {}).get("tex_roots") or []
        if len(roots) == 1:
            mp = Path(cell_dir) / "extracted" / roots[0]
            if mp.exists():
                main_sha = hashlib.sha256(mp.read_bytes()).hexdigest()
    return {
        "id": meta.get("arxiv_id") or meta.get("idc"),
        "era": meta.get("era"),
        "archive": meta.get("archive"),
        "yymm": meta.get("yymm"),
        "cluster_id": meta.get("cluster_id"),
        "layer": meta.get("layer") or default_layer,
        "channel": meta.get("channel"),
        "item": meta.get("item"),
        "member": meta.get("member"),
        "blob_sha256": meta.get("raw_sha256"),
        "main_tex_sha256": main_sha,
        "stratum_cell": meta.get("stratum_cell"),
        "cat_group": meta.get("cat_group"),
        "license_class": meta.get("license_class"),
        "format": meta.get("format"),
        "n_files": meta.get("n_files") or meta.get("n_extracted_files"),
        "n_tex": meta.get("n_tex_files") or meta.get("tex_files"),
        "bytes": meta.get("bytes"),
        "pick_reason": meta.get("pick_reason"),
        "pool": meta.get("pool"),
    }


def materialize_entry_into_stage(
    entry_dir: Path,
    stage: Path,
    *,
    pid: str,
    fm: dict,
    mechs: str,
    layer: str = "expand",
) -> dict:
    """acquire_source CacheEntry dir → lake stage 树 + meta dict.

    fetch-ids 臂（channel=arxiv_eprint）专用：entry 已含 extracted/+raw.*+
    meta.json（产品 locate 结果），这里搬树 + frame_lookup 回填分层字段。
    """
    stage = Path(stage)
    entry_dir = Path(entry_dir)
    ext = stage / "extracted"
    if ext.exists():
        shutil.rmtree(ext)  # 半程截尾树会与 copytree 合并留幽灵文件
    shutil.copytree(entry_dir / "extracted", ext)
    raw_dir = stage / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw = None
    for r_ in entry_dir.glob("raw.*"):
        raw = raw_dir / r_.name
        shutil.copy2(r_, raw)
    meta = json.loads((entry_dir / "meta.json").read_text(encoding="utf-8"))
    yymm = fm.get("tar_yymm") or pid.split(".", 1)[0][:4]
    band = fm.get("year_band") or band_of_yymm(yymm)
    cat = fm.get("cat_group") or "unknown"
    cell = f"{band}|{cat}"
    era = "old" if "/" in pid else "new"
    locate_main = ((meta.get("locate") or {}).get("main")) or None
    roots = (meta.get("locate") or {}).get("independent_roots") or (
        [locate_main] if locate_main else []
    )
    main_sha = None
    if locate_main and (ext / locate_main).exists():
        main_sha = hashlib.sha256((ext / locate_main).read_bytes()).hexdigest()
    feats = extracted_features(ext)
    if not feats.get("tex_roots") and roots:
        feats["tex_roots"] = roots
    meta.update(
        {
            "era": era,
            "archive": pid.split("/", maxsplit=1)[0] if "/" in pid else None,
            "yymm": yymm,
            "cluster_id": f"EXP-{band}",
            "year_band": band,
            "layer": layer,
            "stratum_cell": cell,
            "cat_group": cat,
            "license_class": fm.get("license_class"),
            "channel": "arxiv_eprint",
            "item": None,
            "member": None,
            "features": feats,
            "main_tex_sha256": main_sha,
            "pick_reason": f"expand_orphan:{mechs}",
            "pool": "eprint",
            "source": "arxiv_eprint",
            "arxiv_id": pid,
        }
    )
    meta["bytes"] = raw.stat().st_size if raw else meta.get("raw_size")
    return meta


def largest_remainder(weights: dict[str, float], total: int) -> dict[str, int]:
    neg = {k: w for k, w in weights.items() if w < 0}
    if neg:
        msg = f"negative weights: {neg}"
        raise ValueError(msg)
    s = sum(weights.values())
    if weights and s == 0:
        msg = "all weights zero"
        raise ValueError(msg)
    raw = {k: total * w / s for k, w in weights.items()}
    q = {k: int(v) for k, v in raw.items()}
    for _, k in sorted(((raw[k] - int(raw[k]), k) for k in raw), reverse=True)[
        : total - sum(q.values())
    ]:
        q[k] += 1
    return q


def load_ids_file(path: Path) -> list[dict]:
    """ids 清单 → [{id, mechs, note}]；jsonl 行或纯文本 id（# 注释/空行跳过）。"""
    out = []
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("{"):
            r = json.loads(line)
            out.append(
                {
                    "id": r["id"],
                    "mechs": r.get("mechs") or r.get("mech_tags") or [],
                    "note": r.get("note") or r.get("justification") or "",
                }
            )
        else:
            out.append({"id": line, "mechs": [], "note": ""})
    return out


# ---------------------------------------------------------------- 选样/物化机
# （corpus_expand ↔ corpus_layers verbatim 双份收编：rates 三路解析 / 跨月
# round-robin / item 候选枚举 / 配额选单 → lake.hydrate 物化主循环。）
SEED = 42  # 抽样口径常量（非旋钮——进 params 会诱改口径）
RUN_REF_RX = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*/[0-9]{4}-[0-9]{2}-[0-9]{2}/[A-Za-z0-9][A-Za-z0-9._-]*"
)
#: plan 依赖的 frame 资产清单——frame_build ord-0 前置；缺一件即 fail-closed。
FRAME_NEEDS = (
    "item-index.csv",
    "tiger-files.csv",
    "allocation-core.csv",
    "cluster-cat-mix.csv",
)


class HaltFetch(Exception):
    """限流到顶（parked/budget）——停批续跑，截断返 error。"""


class TransientMiss(Exception):
    """逐件瞬态 miss——记 fail 账续走下一候选。"""


def canon_or_self(raw, fallback=None) -> str:
    """``idnorm.canon_id`` 全解 → idc；解不出回 ``str(raw)``（或
    ``fallback(raw)``——hydrate 的 idc_from_safe 两跳口径走它）。"""
    res = idnorm.canon_id(str(raw))
    if res.ok and res.idc:
        return res.idc
    return str(raw) if fallback is None else fallback(raw)


def cell_meta(d: Path) -> dict:
    """cell 目录 meta.json → dict（缺档/坏 json → {}）。"""
    try:
        m = json.loads((Path(d) / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}


def load_plan(path: Path) -> dict | None:
    """plan json → dict（缺档/坏 json → None——调用方 fail-closed）。"""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def bad_rates(stat: dict[str, Counter]) -> dict[str, float]:
    """{key: Counter(bad/ok)} → {key: bad 占比}。"""
    return {
        k: c["bad"] / (c["bad"] + c["ok"])
        for k, c in stat.items()
        if c["bad"] + c["ok"]
    }


def rates_from_idstatus(
    id_status: dict[str, str], manifest_rows: list[dict], frame_dir: Path
) -> tuple[dict, dict, float]:
    """{id: status} × manifest×frame join → (band_bad_rate, cat_bad_rate, global).

    bad=status∈{fail,reject,partial}（n100_rates 同口径）；id 双侧 canon 归一。"""
    by_id = {canon_id(r["id"]): r for r in manifest_rows if r.get("id")}
    c2b = cluster2band(frame_dir)
    band_stat: dict[str, Counter] = defaultdict(Counter)
    cat_stat: dict[str, Counter] = defaultdict(Counter)
    n_bad = 0
    for pid, st in id_status.items():
        bad = st in ("fail", "reject", "partial")
        n_bad += bad
        m = by_id.get(canon_id(pid), {})
        band = c2b.get(m.get("cluster_id"), "?")
        cat = m.get("cat_group") or "?"
        band_stat[band]["bad" if bad else "ok"] += 1
        cat_stat[cat]["bad" if bad else "ok"] += 1
    if not id_status:
        return {}, {}, 0.0
    return bad_rates(band_stat), bad_rates(cat_stat), n_bad / len(id_status)


def run_id_statuses(run_id: str) -> dict[str, str] | None:
    """run ref → index cells 末 stage per-id status（canon id → status）。"""
    rdir = paths.runs_dir() / run_id
    spec_fp = rdir / "spec.json"
    if not spec_fp.is_file():
        return None
    try:
        stages = [s["name"] for s in json.loads(spec_fp.read_text()).get("stages", [])]
    except (OSError, json.JSONDecodeError):
        return None
    if not stages:
        return None
    idx = indexmod.Index()
    rows = idx.conn.execute(
        "SELECT idc,status FROM cells WHERE last_run=? AND stage=?",
        (run_id, stages[-1]),
    )
    return {canon_id(r["idc"]): r["status"] for r in rows}


def resolve_rates(
    rates_source: str, manifest_rows: list[dict], frame_dir: Path
) -> tuple[dict, dict, float, str, str]:
    """rates_source → (fr_band, fr_cat, fr_all, mode, detail)。

    三路：run ref | rates json | flat_fallback。显式源解析失败 → RuntimeError
    （fail-closed：口径错配绝不能静默退化成 flat）。"""
    src = str(rates_source or "").strip()
    if not src or src.lower() in {"flat", "none", "flat_fallback"}:
        return {}, {}, 0.0, "flat_fallback", "no rates_source"
    p = Path(src).expanduser()
    if p.is_file():
        data = json.loads(p.read_text())
        if isinstance(data, dict) and ("band" in data or "cat" in data):
            return (
                dict(data.get("band") or {}),
                dict(data.get("cat") or {}),
                float(data.get("global") or 0.0),
                "rates_file",
                str(p),
            )
        # 旧 results.json 形 {id: {status:…}}（或 {id: status}）
        idst = {
            str(k): (v.get("status") if isinstance(v, dict) else str(v))
            for k, v in data.items()
        }
        fr_b, fr_c, fr_a = rates_from_idstatus(idst, manifest_rows, frame_dir)
        return fr_b, fr_c, fr_a, "idstatus_file", str(p)
    if RUN_REF_RX.fullmatch(src):
        idst = run_id_statuses(src)
        if idst is None:
            msg = f"rates_source run 不可解析（spec.json/stages 缺）: {src}"
            raise RuntimeError(msg)
        fr_b, fr_c, fr_a = rates_from_idstatus(idst, manifest_rows, frame_dir)
        return fr_b, fr_c, fr_a, "run", src
    msg = f"rates_source 既不是文件也不是 run ref: {src!r}"
    raise RuntimeError(msg)


def order_items(cands: list[dict], cluster_months: set[str]) -> list[dict]:
    """候选项排序: 跨月 round-robin——每轮每月取 1 块, 先把月份摊满再回到
    同月下一块; 簇月在前, 非簇月种子 shuffle 避免挤在年带一端."""
    by_month: dict[str, list[dict]] = defaultdict(list)
    for it in cands:
        by_month[it["yymm"]].append(it)
    cl = sorted(m for m in by_month if m in cluster_months)
    nc = sorted(m for m in by_month if m not in cluster_months)
    random.Random(SEED).shuffle(nc)
    months = cl + nc
    ordered = []
    depth = 0
    while True:
        progressed = False
        for m in months:
            lst = by_month[m]
            if depth < len(lst):
                ordered.append(lst[depth])
                progressed = True
        if not progressed:
            return ordered
        depth += 1


def candidate_items(
    frame_dir: Path,
    done: set[str],
    *,
    excl_months: set[str] | frozenset[str] = frozenset(),
    bands: str | None = None,
) -> dict[str, list[dict]]:
    """{band: [item…]} 未扫候选（ia item-index ∪ tiger-files）。

    ``excl_months``：剔除的簇月 yymm 集（holdout 时间外推闸）；
    ``bands``：允许的年带首字母串（"abc" 只采 a/b/c 带——矿层旧档定向）。"""
    out: dict[str, list[dict]] = defaultdict(list)
    with (Path(frame_dir) / "item-index.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            item, yymm = r["identifier"], r["yymm"]
            if item in done or yymm in excl_months:
                continue
            band = band_of_yymm(yymm)
            if bands is not None and band[0] not in bands:
                continue
            out[band].append(
                {
                    "item": item,
                    "yymm": yymm,
                    "chunk_no": int(r["chunk"]),
                    "channel": "ia",
                    "size": int(r["size"]),
                    "url": item_url("ia", item),
                }
            )
    with (Path(frame_dir) / "tiger-files.csv").open(newline="") as fh:
        for r in csv.DictReader(fh):
            m = re.match(r"(arXiv_src_(\d{4})_(\d{3}))\.tar$", r["path"])
            if not m or m.group(1) in done or m.group(2) in excl_months:
                continue
            band = band_of_yymm(m.group(2))
            if bands is not None and band[0] not in bands:
                continue
            out[band].append(
                {
                    "item": m.group(1),
                    "yymm": m.group(2),
                    "chunk_no": int(m.group(3)),
                    "channel": "tiger",
                    "size": int(r["size_bytes"]),
                    "oid16": r["lfs_oid16"],
                    "url": item_url("tiger", m.group(1)),
                }
            )
    for v in out.values():
        v.sort(key=lambda it: (it["yymm"], it["chunk_no"]))
    return out


def member_fetch_fn(
    rec: dict,
    old_tars: dict,
    offs: dict,
    *,
    layer: str,
    cluster_prefix: str,
    reason: str,
):
    """lake.hydrate fetch_fn：blob 回取 → sha 复核 → stage 物化 + meta。"""

    def fn(idc, stage):
        blob = fetch_blob(rec, old_tars, offs)
        sha = hashlib.sha256(blob).hexdigest()
        if sha != rec["blob_sha256"]:
            msg = f"sha256 mismatch {sha[:12]}"
            raise OSError(msg)
        return materialize_into_stage(
            rec,
            blob,
            sha,
            stage,
            layer=layer,
            cluster_prefix=cluster_prefix,
            reason=reason,
        )

    return fn


def extract_selected(
    ctx,
    sel: list[dict],
    d: dict,
    *,
    layer: str,
    cluster_prefix: str,
    reason: str,
    metric: str,
    emit_extra: dict | None = None,
    rec_extra=None,
) -> str:
    """配额选单 → lake.hydrate 成员物化 + manifest append（expand/layers 主循环）。

    sel 已过 limit 截断（调用方先切）。d 须带 manifest/records/v3/dirs 键
    （dirs=TarDirs——members 簿与 v3 旧池互为回退）。截尾回补先行：lake cell
    完整而 manifest 缺行 → 从 cell meta 补行不重抓。``emit_extra`` 并入收尾
    metric dict；``rec_extra`` 逐条并入 records 行（expand 的 ``_pool`` 记法）。
    """
    manifest = d["manifest"]
    done = {canon_id(str(r["id"])) for r in read_jsonl(manifest) if r.get("id")}
    # 回补: lake cell 完整而 manifest 缺行（截尾场景）→ 从 cell meta 补行；
    # meta 不可解析则不标 done，走重抓自愈（hydrate 重写 meta+行）
    n_backfill = 0
    for rec in sel:
        pid = canon_id(str(rec["id"]))
        if pid in done:
            continue
        src = rec["channel"]
        cell = lake.cell_dir(rec["id"], source=src)
        if not (cell / "meta.json").exists() or not lake.is_complete(
            rec["id"], source=src
        ):
            continue
        row = manifest_row_from_meta(None, cell, default_layer=layer)
        if row is None:
            continue
        append_jsonl(manifest, row)
        done.add(pid)
        n_backfill += 1
    todo = [r for r in sel if canon_id(str(r["id"])) not in done]
    chunks = load_chunks(d["v3"])
    old_items = {c["item"] for c in chunks}
    tag_of_item = {c["item"]: f"{c['yymm']}_{c['chunk_no']:03d}" for c in chunks}
    need_items = {r["item"] for r in todo}
    old_tars = {
        it: d["v3"] / "tars" / f"{it}.tar"
        for it in need_items & old_items
        if (d["v3"] / "tars" / f"{it}.tar").exists()
    }
    offs = {
        it: offsets_for(it, d["dirs"].members, tag_of_item, d["v3"] / "members")
        for it in need_items
    }
    n0 = len(todo)
    todo = [r for r in todo if r["member"] in offs.get(r["item"], {})]
    if n0 - len(todo):
        ctx.emit_note(f"{n0 - len(todo)} members 无 offset 记录，跳过", level="warn")
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    n_ok = n_err = 0
    jobs = max(1, int(ctx.params["jobs"]))
    with (
        manifest.open("a", encoding="utf-8") as mfh,
        ThreadPoolExecutor(max_workers=jobs) as ex,
    ):
        futs = {
            ex.submit(
                lake.hydrate,
                rec["id"],
                member_fetch_fn(
                    rec,
                    old_tars,
                    offs,
                    layer=layer,
                    cluster_prefix=cluster_prefix,
                    reason=reason,
                ),
                rec["channel"],
                run_seq,
            ): rec
            for rec in todo
        }
        for fut in as_completed(futs):
            rec = futs[fut]
            pid = rec["id"]
            try:
                cell = fut.result()
                if lake.is_complete(pid, source=rec["channel"]):
                    row = manifest_row_from_meta(None, cell, default_layer=layer)
                    if row is not None:
                        mfh.write(json.dumps(row, ensure_ascii=False) + "\n")
                        mfh.flush()
                    n_ok += 1
                    st = "ok"
                else:
                    n_err += 1
                    st = "error: empty payload"
            except Exception as e:
                n_err += 1
                st = f"error: {type(e).__name__}: {e}"
                ctx.emit_note(f"  ERR {pid}: {st}", level="warn")
            rec_row = {
                "id": pid,
                "item": rec["item"],
                "member": rec["member"],
                "cell": rec["_cell"],
            }
            if rec_extra is not None:
                rec_row.update(rec_extra(rec))
            rec_row.update({"state": st, "ts": time.strftime("%FT%T")})
            append_jsonl(d["records"], rec_row)
    ctx.emit(
        {
            "metric": metric,
            "selected": len(sel),
            "todo": len(todo),
            "ok": n_ok,
            "err": n_err,
            "backfilled": n_backfill,
            "manifest": str(manifest),
            **(emit_extra or {}),
        }
    )
    if n_err == 0:
        return "ok"
    return "partial" if n_ok else "error"
