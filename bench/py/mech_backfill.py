"""mech_backfill.py — mech_tags 回填器：机制台账/提名/feature 谓词 → manifest 行内嵌标签。

用法：
  python3 bench/py/mech_backfill.py manifest.jsonl [--dry-run] [--report out.json]
  python3 bench/py/mech_backfill.py manifest_hot.jsonl \
      --compute-missing-features tmp/feat_hot.jsonl
  python3 bench/py/mech_backfill.py manifest_expand.jsonl \
      --compute-missing-features tmp/feat_expand.jsonl   # c10 复用同一入口

标签来源（并集，manifest 行序稳定、只加/更新 mech_tags 字段）：
  existing   行内已有 mech_tags（booster 层选择期写入）
  nomination nominations/*.jsonl（.mechs 除外）verified ∈ {true,"feature"} 逐格标签
  ledger     mechanisms.jsonl examples ∪ evidence 文本 arXiv id 引用
             （同 select_booster.derive 口径：examples + evidence 正则，
             notes 不取——交叉评论易误归因）
  feature    可求值谓词子集在 features 记录上求值；features 缺目时经
             --compute-missing-features 对 corpus_v3/<id>/raw.tar.gz 跑
             build_corpus_v3.blob_features 补算（同一生成码，口径一致）

feature 谓词表（台账 evidence 自然语言 → 可执行口径，歧义处回生成源）：
  B01  features.docstyle==true
  B02  features.non_utf8==true
  B03  input_depth>=3 或 n_tex_files>=10
       （台账 "input_depth/n_tex_files" ← build_corpus_v3.py booster 预筛 :834）
  B04  cat_group ∈ {cs, eess-stat-etc, eess, computer science} 且 yymm>="1701"
       （台账 "frame.cat_group ∈ {cs,econ,eess} d/e 带"；primary_cat 未沉淀，
       econ./q-fin. 前缀判不了——已知欠标，此语料 cat_group 无 econ 故影响为零）
  B05  flags ∩ {minted,pstricks} ≠ ∅ 或 docclasses ⊄ KNOWN_CLS
       （台账含 psfrag 但 FLAG_RX 无此 flag 产出——欠标；vendored .sty/.bst
       成员名不在 features 内，只判 docclass 维）
  B06  uncompressed_bytes > 2MiB 或 member_bytes > 10MiB
       （台账题名双条件；选池码只查 uncompressed>2<<20——取台账口径）
  B07  format ∈ {gz,pdf} 或 |tex_roots|>1
       （台账口径；选池码还收 stub/error——从严不取）
  W02  |tex_roots|>1
  W71  tex_roots==[] 且 n_tex_files>=2

纯 stdlib，系统 python3 直跑（--compute-missing-features 需 bench/py 在
sys.path 可 import build_corpus_v3，本脚本自动处理）。
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS = ROOT / "bench" / "corpus_v3"
FEATS_DIR = ROOT / "bench" / "work_v3" / "features"
sys.path.insert(0, str(ROOT / "bench" / "py"))

ARXIV_ID_RX = re.compile(
    r"(?:\d{4}\.\d{4,5}|(?:cond-mat|hep-\w+|math|cs|astro-ph|nucl-\w+|quant-ph"
    r"|gr-qc|nlin|physics|stat|adap-org|alg-geom|chao-dyn|cmp-lg|dg-ga|funct-an"
    r"|patt-sol|q-alg|solv-int|supr-con|acc-phys|ao-sci|atom-ph|bayes-an|chem-ph"
    r"|plasm-ph|q-bio)/\d{7})"
)

KNOWN_CLS = {
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

B04_CATS = {"cs", "eess-stat-etc", "eess", "computer science"}
B04_MIN_YYMM = "1701"  # d_2017_20/e_2021_25 带


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def feat_eval(f: dict, cat_group: str | None, yymm: str | None) -> set[str]:
    """可求值谓词子集 → 命中 tag 集。"""
    out: set[str] = set()
    if f.get("docstyle"):
        out.add("B01")
    if f.get("non_utf8"):
        out.add("B02")
    if (f.get("n_tex_files") or 0) >= 10 or (f.get("input_depth") or 0) >= 3:
        out.add("B03")
    if (cat_group or "").lower() in B04_CATS and (yymm or "") >= B04_MIN_YYMM:
        out.add("B04")
    if set(f.get("flags") or []) & {"minted", "pstricks"} or any(
        d.lower() not in KNOWN_CLS for d in (f.get("docclasses") or [])
    ):
        out.add("B05")
    if (f.get("uncompressed_bytes") or 0) > 2 << 20 or (
        f.get("member_bytes") or 0
    ) > 10 << 20:
        out.add("B06")
    roots = f.get("tex_roots") or []
    if f.get("format") in {"gz", "pdf"} or len(roots) > 1:
        out.add("B07")
    if len(roots) > 1:
        out.add("W02")
    if not roots and (f.get("n_tex_files") or 0) >= 2:
        out.add("W71")
    return out


def nomination_tags() -> dict[str, dict]:
    """id → {tags, verified_kinds}（nominations/*.jsonl 合并，多 agent 取并集）。"""
    out: dict[str, dict] = {}
    for fp in sorted((CORPUS / "nominations").glob("*.jsonl")):
        if ".mechs." in fp.name:
            continue
        for rec in load_jsonl(fp):
            tags = set(rec.get("mech_tags") or [])
            if not tags:
                continue
            pid = rec["id"]
            slot = out.setdefault(pid, {"tags": set(), "verified": set()})
            slot["tags"] |= tags
            slot["verified"].add(rec.get("verified"))
    return out


def ledger_tags() -> dict[str, set[str]]:
    """mech_id → 例证 id 集（examples ∪ evidence 文本引用，跨重复行合并）。"""
    out: dict[str, set[str]] = defaultdict(set)
    for rec in load_jsonl(CORPUS / "mechanisms.jsonl"):
        mid = rec["mech_id"]
        out[mid] |= set(rec.get("examples") or [])
        out[mid] |= set(ARXIV_ID_RX.findall(rec.get("evidence") or ""))
    return out


def paper_ledger_tags(ledger: dict[str, set[str]]) -> dict[str, set[str]]:
    """反查：id → ledger 来源 tag 集。"""
    out: dict[str, set[str]] = defaultdict(set)
    for mid, ids in ledger.items():
        for pid in ids:
            out[pid].add(mid)
    return out


def load_features(extra_paths: list[Path]) -> dict[str, dict]:
    feats: dict[str, dict] = {}
    for fp in sorted(FEATS_DIR.glob("*.jsonl")):
        for rec in load_jsonl(fp):
            feats[rec["id"]] = rec
    for p in extra_paths:
        for rec in load_jsonl(p):
            feats[rec["id"]] = rec
    return feats


def compute_features(rows: list[dict], cache_path: Path) -> dict[str, dict]:
    """对缺目 id 跑 blob_features（import build_corpus_v3），写 cache jsonl。"""
    import build_corpus_v3 as bcv

    out: dict[str, dict] = {}
    if cache_path.exists():
        for rec in load_jsonl(cache_path):
            out[rec["id"]] = rec
    todo = [r for r in rows if r["id"] not in out]
    n_done = 0
    with cache_path.open("a") as fh:
        for r in todo:
            pid = r["id"]
            raw = CORPUS / pid / "raw.tar.gz"
            if not raw.is_file():
                continue
            member = r.get("member") or f"{pid.replace('/', '_')}.tar.gz"
            rec = bcv.blob_features(member, raw.read_bytes())
            rec["id"] = pid
            rec.pop("_texts", None)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            out[pid] = rec
            n_done += 1
            if n_done % 25 == 0:
                print(f"# features {n_done}/{len(todo)}", file=sys.stderr)
    print(f"# computed features: {n_done} new, {len(out)} total", file=sys.stderr)
    return out


def set_mech_tags(row: dict, tags: list[str]) -> dict:
    """mech_tags 插到 pick_reason 前（booster 层原位），无则末尾。"""
    if "mech_tags" not in row:
        items = list(row.items())
        idx = next(
            (i for i, (k, _) in enumerate(items) if k == "pick_reason"),
            len(items),
        )
        items.insert(idx, ("mech_tags", []))
        row = dict(items)
    row["mech_tags"] = tags
    return row


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("manifest", help="bench/corpus_v3/ 下 manifest 文件名")
    ap.add_argument(
        "--compute-missing-features",
        metavar="CACHE.jsonl",
        help="对缺目 id 跑 blob_features，缓存到指定文件",
    )
    ap.add_argument(
        "--extra-features",
        action="append",
        default=[],
        metavar="FILE",
        help="追加 features jsonl（可多次；覆盖 work_v3/features 同 id）",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", metavar="FILE", help="写来源归因 JSON 报告")
    args = ap.parse_args()

    mf_path = CORPUS / args.manifest
    rows = load_jsonl(mf_path)

    extra = [Path(p) for p in args.extra_features]
    if args.compute_missing_features:
        cache = Path(args.compute_missing_features)
        have = load_features(extra)
        missing = [r for r in rows if r["id"] not in have]
        print(
            f"# {len(missing)}/{len(rows)} ids 无 features，补算中…",
            file=sys.stderr,
        )
        computed = compute_features(missing, cache)
        feats = {**have, **computed}
    else:
        feats = load_features(extra)

    noms = nomination_tags()
    ledger = ledger_tags()
    by_paper = paper_ledger_tags(ledger)

    # pass 1: id → tag 集 + 来源统计（初始读）
    tag_map: dict[str, set[str]] = {}
    src_count = defaultdict(int)  # (source) → n papers tagged
    tag_by_src: dict[str, set[str]] = defaultdict(set)  # tag → sources
    for row in rows:
        pid = row["id"]
        tags_src: dict[str, set[str]] = defaultdict(set)
        for t in row.get("mech_tags") or []:
            tags_src["existing"].add(t)
        for t in (noms.get(pid) or {}).get("tags") or ():
            tags_src["nomination"].add(t)
        for t in by_paper.get(pid) or ():
            tags_src["ledger"].add(t)
        f = feats.get(pid)
        if f:
            for t in feat_eval(f, row.get("cat_group"), row.get("yymm")):
                tags_src["feature"].add(t)
        tag_map[pid] = set().union(*tags_src.values()) if tags_src else set()
        for src, ts in tags_src.items():
            if ts:
                src_count[src] += 1
                tag_by_src[src] |= ts

    # pass 2: 写前重读——运行期间别家 append 的行原样保留（拿 mech_tags=[] 或
    # 命中 tag_map），竞态窗口缩到 read→write 瞬间
    fresh = load_jsonl(mf_path)
    n_changed = 0
    out_rows = []
    for row in fresh:
        merged = sorted(set(row.get("mech_tags") or []) | tag_map.get(row["id"], set()))
        if merged != (row.get("mech_tags") or []):
            n_changed += 1
        out_rows.append(set_mech_tags(row, merged))

    stats = {
        "manifest": args.manifest,
        "rows": len(fresh),
        "tagged": sum(1 for r in out_rows if r["mech_tags"]),
        "changed": n_changed,
        "papers_by_source": dict(sorted(src_count.items())),
        "distinct_tags": sorted(
            set().union(*[set(r["mech_tags"]) for r in out_rows]) if out_rows else set()
        ),
        "tags_by_source": {k: sorted(v) for k, v in sorted(tag_by_src.items())},
    }
    print(
        f"# {args.manifest}: {stats['tagged']}/{len(fresh)} 行带 tag "
        f"({n_changed} 行变更); 来源覆盖 {json.dumps(stats['papers_by_source'], ensure_ascii=False)}",
        file=sys.stderr,
    )
    if args.report:
        Path(args.report).write_text(
            json.dumps(stats, indent=1, ensure_ascii=False) + "\n"
        )
        print(f"# report -> {args.report}", file=sys.stderr)
    if not args.dry_run:
        mf_path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows)
        )
        print(f"# wrote {mf_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
