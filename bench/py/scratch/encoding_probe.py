#!/usr/bin/env python3
r"""一次性探针：corpus_v3 non-UTF-8 / 编码族论文的逐文件编码判定对比。

对每个论文目录下的文本源文件（.tex/.sty/.cls/.bib/.bbl/.bst/.cfg/.def/.clo/.fd/.ltx/.idx/.ist），
对比「旧兜底链 utf-8-sig → gb18030 → cp1252 → latin-1」与新 ``sniff_tex_encoding`` 的
verdict 与实际解码文本差异；统计 verdict 分布与「旧链产出不同文本」的文件数。

用法: uv run python bench/py/scratch/encoding_probe.py [paper_id ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from texlate.textutil import decode_tex_with

SUFFIXES = {
    ".tex",
    ".sty",
    ".cls",
    ".cfg",
    ".def",
    ".clo",
    ".fd",
    ".ltx",
    ".bib",
    ".bbl",
    ".bst",
    ".idx",
    ".ist",
    ".nlo",
    ".gls",
}

PAPERS = [
    # compilebench-v3 route_non_utf8 全集 19 篇
    "0707.2833",
    "0905.4208",
    "1003.5531",
    "1012.1124",
    "1109.1664",
    "1109.1801",
    "1206.5628",
    "1206.5796",
    "1206.5832",
    "1306.2183",
    "1404.2164",
    "1404.5685",
    "1404.6180",
    "2009.03686",
    "2308.04174",
    "2403.15096",
    "cond-mat/0111097",
    "hep-ph/9910443",
    "math/0307077",
    # nominations 编码族案例
    "1511.06717",
    "2410.06008",
    "2403.15158",
    "2105.03820",
    "1511.06943",
]


def old_chain(blob: bytes) -> str:
    """已退役的兜底链——供新旧输出 diff。"""
    for enc in ("utf-8-sig", "gb18030", "cp1252", "latin-1"):
        try:
            return blob.decode(enc)
        except UnicodeDecodeError:
            continue
    return blob.decode("utf-8", errors="replace")


def main() -> None:
    corpus = ROOT / "bench" / "corpus_v3"
    papers = sys.argv[1:] or PAPERS
    verdict_rows = []
    n_diff = 0
    n_files = 0
    for pid in papers:
        root = corpus / pid / "extracted"
        if not root.is_dir():
            print(f"{pid}: MISSING")
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in SUFFIXES:
                continue
            blob = p.read_bytes()
            try:
                blob.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                continue  # strict-utf8 不在本探针范围
            n_files += 1
            text, v = decode_tex_with(blob)
            old = old_chain(blob)
            diff = text != old
            n_diff += diff
            verdict_rows.append(
                {
                    "paper": pid,
                    "file": str(p.relative_to(root)),
                    "encoding": v.encoding,
                    "basis": v.basis,
                    "declared": v.declared,
                    "note": v.note,
                    "old_differs": diff,
                    "hibytes": sum(1 for b in blob if b >= 0x80),
                }
            )
    for r in verdict_rows:
        flag = " DIFF" if r["old_differs"] else ""
        print(
            f"{r['paper']:20s} {r['file'][:44]:44s} {r['encoding']:12s} "
            f"{r['basis']:12s} decl={r['declared']} hi={r['hibytes']:4d} "
            f"{r['note'][:48]}{flag}"
        )
    from collections import Counter

    tally = Counter(r["encoding"] for r in verdict_rows)
    print("\n=== verdict encoding tally:", dict(tally))
    print(f"non-utf8 files: {n_files}  old-chain-differs: {n_diff}")
    out = ROOT / "bench" / "results" / "encoding-probe-2026-09-16.json"
    out.write_text(json.dumps(verdict_rows, ensure_ascii=False, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
