#!/usr/bin/env python3
"""envarg scout: census ``\\begin{ENV}{...}`` whose leading args are all
dimen/number-shaped (unit-letter leak candidates for argspec env entries).

Verdicts per occurrence:
  strict  - >=1 arg group, every content in {num, dimen, star}
  expr    - strict after also allowing {dimexpr, empty}
  partial - first arg shaped, some later arg not shaped (kept aside)
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "bench/results/stagerun-loop1-2026-09-16/work")
SRC_GLOB = sys.argv[3] if len(sys.argv) > 3 else "*/src"

BEGIN_RX = re.compile(r"\\begin\s*\{([^{}]+)\}")
TAIL_RX = re.compile(r"\s*(\[[^\[\]]*\])?\s*((?:\{[^{}]*\}\s*)+)")
GROUP_RX = re.compile(r"\{([^{}]*)\}")

NUM_RX = re.compile(r"^[+-]?[0-9.,]+$")
DIMEN_RX = re.compile(r"^[+-]?[0-9.,]+\s*(pt|pc|in|bp|cm|mm|dd|cc|sp|em|ex|mu|zh|zw)$", re.I)
DIMEXPR_RX = re.compile(
    r"^[+-]?(?:[0-9.,]+\s*(?:pt|pc|in|bp|cm|mm|dd|cc|sp|em|ex|mu|zh|zw)?\s*)?\\[a-zA-Z@]+\*?$",
    re.I,
)
STAR_RX = re.compile(r"^\*+$")


def classify(content: str) -> str:
    s = content.strip()
    if not s:
        return "empty"
    if STAR_RX.match(s):
        return "star"
    if NUM_RX.match(s):
        return "num"
    if DIMEN_RX.match(s):
        return "dimen"
    if DIMEXPR_RX.match(s):
        return "dimexpr"
    return "other"


SHAPED_STRICT = {"num", "dimen", "star"}
SHAPED_LOOSE = SHAPED_STRICT | {"dimexpr", "empty"}


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def main() -> None:
    stats = defaultdict(
        lambda: {
            "strict": 0,
            "expr": 0,
            "partial": 0,
            "papers": set(),
            "samples": [],
            "classes": Counter(),
            "opt": 0,
            "arg_shapes": Counter(),
        }
    )
    files = [p for src in ROOT.glob(SRC_GLOB) for p in src.rglob("*.tex")]
    for p in files:
        paper = p.relative_to(ROOT).parts[0]
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.split("\n")
        for m in BEGIN_RX.finditer(text):
            env = m.group(1).strip()
            t = TAIL_RX.match(text, m.end())
            if not t or not t.group(2):
                continue
            groups = GROUP_RX.findall(t.group(2))
            if not groups:
                continue
            classes = [classify(g) for g in groups]
            has_opt = bool(t.group(1))
            rec = stats[env]
            rec["classes"].update(classes)
            shape = " ".join("o" if has_opt else "" for _ in [0]) or ""
            sig = ("o " if has_opt else "") + " ".join(
                {"num": "n", "dimen": "d", "star": "*", "dimexpr": "D", "empty": "0", "other": "?"}[c]
                for c in classes
            )
            if all(c in SHAPED_STRICT for c in classes):
                verdict = "strict"
            elif all(c in SHAPED_LOOSE for c in classes):
                verdict = "expr"
            elif classes[0] in SHAPED_LOOSE:
                verdict = "partial"
            else:
                continue
            rec[verdict] += 1
            rec["papers"].add(paper)
            rec["arg_shapes"][sig] += 1
            if has_opt:
                rec["opt"] += 1
            if len(rec["samples"]) < 4:
                ln = line_of(text, m.start())
                src_line = lines[ln - 1].strip()[:200] if ln <= len(lines) else ""
                rec["samples"].append(f"{p}:{ln}: {src_line}")

    out = {
        env: {
            **{k: v for k, v in r.items() if k not in {"papers", "classes", "samples", "arg_shapes"}},
            "n_papers": len(r["papers"]),
            "classes": dict(r["classes"]),
            "samples": r["samples"],
            "arg_shapes": dict(r["arg_shapes"].most_common(5)),
        }
        for env, r in stats.items()
    }
    Path(sys.argv[2]).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    n = sum(1 for r in stats.values() if r["strict"] or r["expr"])
    print(f"files={len(files)} envs={len(stats)} shaped_envs={n}")


if __name__ == "__main__":
    main()
