"""corpus 自检段叶——配额/去重/lake 对账/manifests_tracked → clean|fail。"""

from __future__ import annotations

import json

from kernel import lake

from specs import _bootstrap
from specs import _corpus_common as cc
from specs.corpus.base import LAKE_SOURCE, WORK, _read_jsonl

_bootstrap.ensure()

# ---------------- qc (S5) ----------------


def _qc(ctx):
    import subprocess

    problems: list[str] = []
    manifest = _read_jsonl(cc.CORPUS / "manifest.jsonl")
    ids = [r["id"] for r in manifest]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        problems.append(f"id 重复: {dup[:8]}")
    # lake 对账：manifest 行 → cell complete（empty 态 pdf/stub 是合法终态）
    missing = []
    for r in manifest:
        idc = cc.canon_or_self(r["id"])
        d = lake.cell_dir(idc, LAKE_SOURCE)
        meta = cc.cell_meta(d)
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
            [  # noqa: S607 — manifests_tracked 断言的 git 探针沿用 PATH（HEAD 同形预存）
                "git",
                "ls-files",
                "--error-unmatch",
                "bench/corpus/manifest.jsonl",
                "bench/corpus/manifest_booster.jsonl",
                "bench/corpus/MANIFEST.md",
            ],
            cwd=cc.REPO,
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
    cc.atomic_write_text(WORK / "qc_report.md", "\n".join(lines) + "\n")
    print("\n".join(lines[:8]))
    return {
        "status": "fail" if problems else "clean",
        "metrics": {
            "core_rows": len(manifest),
            "dup_ids": len(dup),
            "lake_missing": len(missing),
            "members_scanned": total,
            "manifests_tracked": tracked,
        },
        "errors": [{"cat": "index_unsealed", "payload": p} for p in problems],
    }
