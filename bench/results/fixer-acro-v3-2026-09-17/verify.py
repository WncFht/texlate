#!/usr/bin/env python3
"""fixer-acro-v3 单格验证: 1706.00240 acro v3 short-format key。

splice-base/  = 现状 rules.yaml (基线, 预期 unfixable:early_eof)
splice-test/  = rules-test.yaml (key_unknown 签 + acro_v3_key_rename when 扩)
两副本已预打 env 字体贴片 (Noto Mono → Noto Sans Mono) 让编译走到 acro 错。

跑法: uv run python bench/results/fixer-acro-v3-2026-09-17/verify.py [base|test|both]
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "bench" / "py"))

import fixloop_bench as flb  # noqa: E402
from texlate.compile.engine import XelatexEngine  # noqa: E402
from texlate.compile.fixloop import CaseSink, Ruleset, fixloop  # noqa: E402

OUT = Path(__file__).resolve().parent
WORK = REPO / "bench/results/stagerun-loop1-2026-09-16/work/1706.00240"


def main_rel(splice: Path) -> str:
    pj = WORK / "parse.json"
    if pj.exists():
        rel = json.loads(pj.read_text()).get("main_rel")
        if rel:
            return rel
    return "torus.tex"


def run_one(tag: str, ruleset_path: Path | None) -> dict:
    splice = OUT / f"splice-{tag}"
    texmf = OUT / f"_texmf-{tag}"
    if texmf.exists():
        shutil.rmtree(texmf)
    flb._init_usertree(texmf)
    eng = flb._NoSandbox(
        XelatexEngine(
            halt_on_error=True, texmfhome=texmf, repository=flb.TUNA_TLNET
        )
    )
    idx = flb._index()
    if idx is not None:
        eng.filemap = idx.query
    rs = Ruleset.load(path=ruleset_path) if ruleset_path else flb.RS
    if (WORK / "src").is_dir():
        for rule in rs.rules:
            act = rule.raw.get("action") or {}
            if (
                act.get("kind") == "builtin_transform"
                and act.get("function") == "restore_support_from_src"
            ):
                act.setdefault("params", {})["baseline_dir"] = str(WORK / "src")
    sink = CaseSink(OUT / "cases.jsonl")
    t0 = time.monotonic()
    cell = fixloop(
        splice,
        eng,
        ruleset=rs,
        engine_name="xelatex",
        corpus_id=f"1706.00240-{tag}",
        cond="fixloop",
        runner=flb._texmf_runner(texmf),
        case_sink=sink,
        compile_timeout=240.0,
    )
    cell["wall_s"] = round(time.monotonic() - t0, 1)
    return cell


def summarize(cell: dict) -> None:
    print(f"  verdict: {cell.get('verdict')}")
    for r in cell.get("rounds") or []:
        print(
            f"    r{r.get('round')} cat={r.get('category')} pay={r.get('payload')} "
            f"pdf={r.get('pdf')} err={r.get('n_errors')}"
        )
    for a in cell.get("actions") or []:
        print(f"    act r{a.get('round')} {a.get('rule')}: {a.get('result')}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("base", "both"):
        print("=== baseline (live rules.yaml) ===")
        c = run_one("base", None)
        summarize(c)
        (OUT / "cell-base.json").write_text(
            json.dumps(c, ensure_ascii=False, indent=1)
        )
    if which in ("test", "both"):
        print("=== candidate (rules-test.yaml) ===")
        c = run_one("test", OUT / "rules-test.yaml")
        summarize(c)
        (OUT / "cell-test.json").write_text(
            json.dumps(c, ensure_ascii=False, indent=1)
        )
