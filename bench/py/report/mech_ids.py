"""mech_ids.py — mechanism 标签 ↔ id 集双向索引（spec: bench/results/mechanism-subset-selection-2026-09-17.md）。

用法：
  python3 bench/py/report/mech_ids.py B01 W45              # 多 tag 并集 → stdout id 表
  python3 bench/py/report/mech_ids.py W45 --out /tmp/ids.txt
  python3 bench/py/report/mech_ids.py --rule <rule-name>   # rules/ 分片 mechanisms: 反查
  python3 bench/py/report/mech_ids.py W45 --plus-random 10 --seed 42   # 加对照随机格
  python3 bench/py/report/mech_ids.py W45 --validate       # 校验 id 在 corpus manifest 内
  python3 bench/py/report/mech_ids.py --coverage           # 全台账覆盖表 + orphan 名单
  python3 bench/py/report/mech_ids.py --paper <id>         # cell→mechs 反查
  python3 bench/py/report/mech_ids.py B01 --verified-only  # 只用人工核源（剔 feature 推标签）

标签源（默认全并集，mech_tags 已回填 manifest*.jsonl——mech_backfill.py）：
  verified  booster_selection.jsonl ∪ nominations/*.jsonl(verified=true)
            ∪ mechanisms.jsonl examples
  derived   manifest mech_tags 中的谓词/cite 成分 + nominations(verified=feature)
            + mechanisms evidence 文本 arXiv id 引用（select_booster.derive 口径）

产出接 `python3 bench/py/wave.py run <ids-file> [--go]`（旧 rerun-wave.sh --ids-file 口径）。
纯 stdlib，系统 python3 直跑（不 import texlate.*）。
"""

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
CORPUS = ROOT / "bench" / "corpus"
RULES_DIR = ROOT / "src" / "texlate" / "compile" / "fixloop" / "rules"

ARXIV_ID_RX = re.compile(
    r"(?:\d{4}\.\d{4,5}|(?:cond-mat|hep-\w+|math|cs|astro-ph|nucl-\w+|quant-ph"
    r"|gr-qc|nlin|physics|stat|adap-org|alg-geom|chao-dyn|cmp-lg|dg-ga|funct-an"
    r"|patt-sol|q-alg|solv-int|supr-con|acc-phys|ao-sci|atom-ph|bayes-an|chem-ph"
    r"|plasm-ph|q-bio)/\d{7})"
)


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def manifest_paths() -> list[Path]:
    """corpus 全部 manifest 层（expand 含在内——回填后可解析）。"""
    return sorted(CORPUS.glob("manifest*.jsonl"))


def mechanisms() -> list[dict]:
    return load_jsonl(CORPUS / "mechanisms.jsonl")


def tag_ids(tags: set[str], verified_only: bool = False) -> dict[str, list[str]]:
    """tag → 命中 id 表（多源并集；verified_only 剔 derived 源）。"""
    out: dict[str, set[str]] = {t: set() for t in tags}
    sel_path = CORPUS / "booster_selection.jsonl"
    if sel_path.exists():
        for r in load_jsonl(sel_path):
            for t in tags & set(r.get("mech_tags") or []):
                out[t].add(r["id"])
    nom_dir = CORPUS / "nominations"
    if nom_dir.is_dir():
        for fp in sorted(nom_dir.glob("*.jsonl")):
            if ".mechs." in fp.name:
                continue
            for r in load_jsonl(fp):
                if verified_only and r.get("verified") is not True:
                    continue
                for t in tags & set(r.get("mech_tags") or []):
                    out[t].add(r["id"])
    for r in mechanisms():
        mid = r.get("mech_id")
        if mid in tags:
            for ex in r.get("examples") or []:
                out[mid].add(ex)
            if not verified_only:
                for pid in ARXIV_ID_RX.findall(r.get("evidence") or ""):
                    out[mid].add(pid)
    if not verified_only:
        for p in manifest_paths():
            for r in load_jsonl(p):
                for t in tags & set(r.get("mech_tags") or []):
                    out[t].add(r["id"])
    return {t: sorted(v) for t, v in out.items()}


def rule_tags(name: str) -> list[str]:
    """rules/ 分片里 `- id: <name>` 块的 mechanisms: 字段（声明式映射，peer1 schema）。"""
    tags: list[str] = []
    in_rule = False
    for line in (
        ln
        for f in sorted(RULES_DIR.glob("*.yaml"))
        for ln in f.read_text().splitlines()
    ):
        if line.strip() == f"- id: {name}":
            in_rule = True
            continue
        if in_rule:
            stripped = line.strip()
            if stripped.startswith("- id:"):
                break
            if stripped.startswith("mechanisms:"):
                payload = stripped.split(":", 1)[1].strip()
                tags = [t.strip() for t in payload.strip("[]").split(",") if t.strip()]
                break
    return tags


def manifest_ids() -> set[str]:
    ids: set[str] = set()
    for p in manifest_paths():
        for r in load_jsonl(p):
            if r.get("id"):
                ids.add(r["id"])
    return ids


def mech_meta() -> dict[str, dict]:
    """mech_id → 台账合成视图（跨重复行取首个 status/kind，union examples）。"""
    out: dict[str, dict] = {}
    for r in mechanisms():
        mid = r["mech_id"]
        slot = out.setdefault(
            mid,
            {
                "status": r.get("status"),
                "kind": r.get("kind"),
                "quota": r.get("quota"),
                "merged_into": r.get("merged_into") or r.get("merge_target"),
                "n_rows": 0,
            },
        )
        slot["n_rows"] += 1
        if not slot["status"]:
            slot["status"] = r.get("status")
        mt = r.get("merged_into") or r.get("merge_target")
        if mt:
            slot["merged_into"] = mt
    return out


def cmd_coverage(verified_only: bool) -> int:
    meta = mech_meta()
    all_tags = set(meta)
    by_tag = tag_ids(all_tags, verified_only=verified_only)
    known = manifest_ids()
    orphans, rows = [], []
    n_cells_total = 0
    for t in sorted(all_tags):
        ids = by_tag[t]
        valid = [i for i in ids if i in known]
        n_cells_total += len(valid)
        m = meta[t]
        orphan = not valid
        if orphan:
            orphans.append(t)
        rows.append(
            {
                "mech": t,
                "status": m["status"],
                "quota": m["quota"],
                "merged_into": m["merged_into"],
                "resolved": len(ids),
                "in_manifest": len(valid),
            }
        )
    fam = defaultdict(lambda: [0, 0])  # fam → [n_mechs, n_orphan]
    for r in rows:
        fam[r["mech"][0]][0] += 1
        if r["mech"] in orphans:
            fam[r["mech"][0]][1] += 1
    print(f"# coverage: {len(all_tags)} mech_ids, {n_cells_total} valid cells")
    for f in sorted(fam):
        n, o = fam[f]
        print(f"#   {f}-family: {n} mechs, {o} orphans")
    hdr = f"{'mech':6} {'status':20} {'quota':>5} {'resolved':>8} {'cells':>5} flags"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        flags = []
        if r["mech"] in orphans:
            flags.append("ORPHAN")
        if r["merged_into"]:
            flags.append(f"merged→{r['merged_into']}")
        if r["resolved"] > r["in_manifest"]:
            flags.append(f"{r['resolved'] - r['in_manifest']} out-of-corpus")
        print(
            f"{r['mech']:6} {r['status'] or '-':20} {r['quota'] or '-':>5} "
            f"{r['resolved']:>8} {r['in_manifest']:>5} {' '.join(flags)}"
        )
    print(f"\n# orphans ({len(orphans)}): {' '.join(orphans)}")
    return 0


def cmd_paper(pid: str) -> int:
    known = manifest_ids()
    if pid not in known:
        print(f"warn: {pid} 不在任何 manifest", file=sys.stderr)
    hits: dict[str, set[str]] = defaultdict(set)
    for p in manifest_paths():
        for r in load_jsonl(p):
            if r["id"] == pid:
                for t in r.get("mech_tags") or []:
                    hits["manifest:" + p.name].add(t)
    sel_path = CORPUS / "booster_selection.jsonl"
    if sel_path.exists():
        for r in load_jsonl(sel_path):
            if r["id"] == pid:
                for t in r.get("mech_tags") or []:
                    hits["booster_selection"].add(t)
    nom_dir = CORPUS / "nominations"
    if nom_dir.is_dir():
        for fp in sorted(nom_dir.glob("*.jsonl")):
            if ".mechs." in fp.name:
                continue
            for r in load_jsonl(fp):
                if r["id"] == pid:
                    for t in r.get("mech_tags") or []:
                        hits[f"nomination:{fp.stem}(v={r.get('verified')})"].add(t)
    for r in mechanisms():
        mid = r["mech_id"]
        if pid in (r.get("examples") or []):
            hits["ledger:examples"].add(mid)
        if pid in ARXIV_ID_RX.findall(r.get("evidence") or ""):
            hits["ledger:evidence-cite"].add(mid)
    total = sorted(set().union(*hits.values()) if hits else set())
    print(f"# {pid}: {len(total)} tags")
    for src, ts in sorted(hits.items()):
        print(f"  {src}: {' '.join(sorted(ts))}")
    print("\n".join(total))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("tags", nargs="*", help="机制 tag（B##/T##/W##），多个取并集")
    ap.add_argument("--rule", help="rules/ 规则名 → 读其 mechanisms: 字段反查 tag")
    ap.add_argument(
        "--plus-random", type=int, default=0, metavar="N", help="追加 N 个随机对照格"
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", help="写文件（默认 stdout）")
    ap.add_argument(
        "--validate",
        action="store_true",
        help="校验 id 在 corpus manifest 内，越界者剔除并 warn",
    )
    ap.add_argument(
        "--verified-only",
        action="store_true",
        help="只用人工核源（剔 feature/evidence-cite 推导标签）",
    )
    ap.add_argument(
        "--coverage",
        action="store_true",
        help="全台账覆盖表：每 mech 可解 cell 数 + orphan 名单",
    )
    ap.add_argument("--paper", metavar="ID", help="cell→mechs 反查")
    args = ap.parse_args()

    if args.coverage:
        return cmd_coverage(args.verified_only)
    if args.paper:
        return cmd_paper(args.paper)

    tags = set(args.tags)
    if args.rule:
        rt = rule_tags(args.rule)
        if not rt:
            print(
                f"warn: rule '{args.rule}' 无 mechanisms: 字段或未找到", file=sys.stderr
            )
        tags |= set(rt)
    if not tags:
        ap.error("需要至少一个 tag 或 --rule")

    by_tag = tag_ids(tags, verified_only=args.verified_only)
    for t in sorted(tags):
        print(f"# {t}: {len(by_tag[t])} ids", file=sys.stderr)
    ids = sorted(set().union(*by_tag.values()))

    if args.plus_random:
        pool = sorted(manifest_ids() - set(ids))
        extra = random.Random(args.seed).sample(pool, min(args.plus_random, len(pool)))
        ids += extra
        print(f"# +random {len(extra)} (seed {args.seed})", file=sys.stderr)

    if args.validate:
        known = manifest_ids()
        bad = [i for i in ids if i not in known]
        if bad:
            print(f"warn: {len(bad)} ids 不在 manifest：{bad[:5]}", file=sys.stderr)
            ids = [i for i in ids if i in known]

    text = "\n".join(ids) + "\n"
    if args.out:
        Path(args.out).write_text(text)
        print(f"# wrote {len(ids)} ids -> {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
