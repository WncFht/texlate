"""mech_ids.py — mechanism 标签 → id 集外部 join（spec: bench/results/mechanism-subset-selection-2026-09-17.md）。

用法：
  python3 bench/py/mech_ids.py B01 W45              # 多 tag 并集 → stdout id 表
  python3 bench/py/mech_ids.py W45 --out /tmp/ids.txt
  python3 bench/py/mech_ids.py --rule <rule-name>   # rules.yaml mechanisms: 反查
  python3 bench/py/mech_ids.py W45 --plus-random 10 --seed 42   # 加对照随机格
  python3 bench/py/mech_ids.py W45 --validate       # 校验 id 在 corpus manifest 内

产出接 `bash tmp/rerun-wave.sh --ids-file <out> [--go]`。
纯 stdlib，系统 python3 直跑（不 import texlate.*）。
"""

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS = ROOT / "bench" / "corpus_v3"
RULES = ROOT / "src" / "texlate" / "compile" / "fixloop" / "rules.yaml"
MANIFESTS = ["manifest.jsonl", "manifest_booster.jsonl", "manifest_hot.jsonl"]


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def tag_ids(tags: set[str]) -> dict[str, list[str]]:
    """tag → 命中 id 表：booster_selection 逐文件标签 ∪ registry examples。"""
    out: dict[str, set[str]] = {t: set() for t in tags}
    sel_path = CORPUS / "booster_selection.jsonl"
    if sel_path.exists():
        for r in load_jsonl(sel_path):
            for t in tags & set(r.get("mech_tags") or []):
                out[t].add(r["id"])
    for r in load_jsonl(CORPUS / "mechanisms.jsonl"):
        if r.get("mech_id") in tags:
            for ex in r.get("examples") or []:
                out[r["mech_id"]].add(ex)
    return {t: sorted(v) for t, v in out.items()}


def rule_tags(name: str) -> list[str]:
    """rules.yaml 里 `- id: <name>` 块的 mechanisms: 字段（声明式映射，peer1 schema）。"""
    tags: list[str] = []
    in_rule = False
    for line in RULES.read_text().splitlines():
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
    for name in MANIFESTS:
        p = CORPUS / name
        if p.exists():
            for r in load_jsonl(p):
                if r.get("id"):
                    ids.add(r["id"])
    return ids


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("tags", nargs="*", help="机制 tag（B##/T##/W##），多个取并集")
    ap.add_argument("--rule", help="rules.yaml 规则名 → 读其 mechanisms: 字段反查 tag")
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
    args = ap.parse_args()

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

    by_tag = tag_ids(tags)
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
