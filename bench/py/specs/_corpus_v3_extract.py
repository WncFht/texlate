"""corpus_v3 物化段叶——lake.hydrate 成员物化 / cell 归属裁决 / manifest 重建。

``texlate.arxiv`` 惰性 import 在 ``_stage_extract``/``_stage_extract_booster``
内（lazy 惯例——import 期纯 stdlib+kernel）。
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import time
from collections import Counter
from pathlib import Path

from kernel import fsutil, idnorm, lake, paths

from specs import _bootstrap
from specs import _corpus_common as cc
from specs._corpus_v3_base import (
    BAND_OF_CLUSTER,
    FRAME_LOOKUP_GZ,
    LAKE_SOURCE,
    TARS,
    WORK,
    _read_jsonl,
    load_allocation,
    load_chunks,
)

_bootstrap.ensure()

# ---------------- extract (S4) — lake 物化 ----------------


class _MemberFault(Exception):
    """成员级故障——fetch_fn 内抛，stage fn 捕，记 cell errors 不毁 stage。"""

    def __init__(self, cat: str, payload: str):
        self.cat = cat
        self.payload = payload
        super().__init__(f"{cat}:{payload}")


def _cell_state(idc: str, layer: str) -> str:
    """lake cell 相对本管线的归属态：ours/conflict/build。

    无 layer 的异国 cell 不再单列 adopt——hydrate 对 complete 先者胜与
    catalog empty 皆短路返回，是否并入在 hydrate 落点后读 meta 折叠判定。
    torn ours（meta 在而 payload 缺）走 build 交 hydrate 重建修复。
    """
    meta = cc.cell_meta(lake.cell_dir(idc, LAKE_SOURCE))
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
        meta = cc.cell_meta(d)
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
        "raw_file": cc.RAW_NAME.get(feat["format"], "raw.bin"),
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
    raw_name = cc.RAW_NAME.get(fmt, "raw.bin")
    idc = cc.canon_or_self(rec["id"])

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
            _n_ext, warns = cc.unpack_blob(blob, fmt, stage)
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
            idc = cc.canon_or_self(rec["id"])
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
            meta = cc.cell_meta(d)
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
            meta = cc.cell_meta(d)
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
    cc.atomic_write_text(
        cc.CORPUS / out_name,
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
    )
    return rows


def _stage_extract(ctx):
    try:
        import texlate.arxiv  # noqa: F401 — unpack 产品码预检（lazy 惯例）
    except ImportError:
        ctx.emit_note("texlate.arxiv 不可导入（需项目 venv）", level="warn")
        return "fail"
    cc.CORPUS.mkdir(exist_ok=True)
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
    sel_path = cc.CORPUS / "booster_selection.jsonl"
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
    cc.log(f"extract done: {stats} | manifest {len(manifest)} rows -> {cc.CORPUS}")
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
    md = cc.CORPUS / "MANIFEST.md"
    if md.exists() and "## 补强层" in md.read_text(encoding="utf-8"):
        # 现行 MANIFEST.md 含手补的 booster/hot/expand 策展段——整文件重写
        # 会把它们抹掉; 核心表如需重生成请人工合并进现有文件
        cc.log("MANIFEST.md 含策展段，跳过重写（核心表如需更新请手工合并）")
        return
    cc.atomic_write_text(md, "\n".join(lines) + "\n")


def _stage_extract_booster(ctx):
    """S3b→S4：booster_selection.jsonl 的补强篇物化（layer=booster）。

    选集由 booster-select 动词产出；成员定位走 features.jsonl（id→member/
    item/sha256 全在）。manifest_booster.jsonl 独立文件不碰核心。
    """
    sel_path = cc.CORPUS / "booster_selection.jsonl"
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
    cc.CORPUS.mkdir(exist_ok=True)
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
        cc.log(f"!! {pid} 无 features 记录（member 定位失败——跳过）")

    # frame join 补 cat_group/license_class（旧 extract_booster 同款 lut 回查）
    lut = cc.load_frame_lookup(FRAME_LOOKUP_GZ) if FRAME_LOOKUP_GZ.exists() else {}
    chunks = load_chunks()
    tag_of_item = {c["item"]: f"{c['yymm']}_{c['chunk_no']:03d}" for c in chunks}
    wanted: dict[str, dict[str, dict]] = {}
    feat_lut: dict[str, dict] = {}
    for f in feat_by_id.values():
        fr = cc.frame_get(lut, f["id"]) or {}
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
    cc.log(
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
