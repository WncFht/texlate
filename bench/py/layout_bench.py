#!/usr/bin/env python3
"""layout_bench — mine en-vs-zh layout damage across bench work dirs.

Pure stdlib + poppler (pdftoppm) only; runs under system python3.

Subcommands:
  metrics   walk a work/ dir, parse build-base + splice logs -> metrics.jsonl
  features  scan work/{sid}/src/*.tex static layout-risk features -> features.jsonl
  ink       render pdf pairs, per-page ink/blank/margin metrics -> ink.jsonl
  report    join metrics+features+ink -> leaderboard + report.md
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

RE_OUT_WRITTEN = re.compile(rb"Output written on (\S+\.pdf) \((\d+) page")
RE_OF_H = re.compile(rb"Overfull \\hbox")
RE_OF_V = re.compile(rb"Overfull \\vbox")
RE_UF_H = re.compile(rb"Underfull \\hbox")
RE_UF_V = re.compile(rb"Underfull \\vbox")
RE_FLOAT_FIT = re.compile(rb"TeXlate-Float-Fit:")
RE_TOO_MANY_FLOATS = re.compile(rb"Too many unprocessed floats|Float\(s\) lost")
RE_DOCCLASS = re.compile(r"\\documentclass\s*(\[([^\]]*)\])?\s*\{([^}]+)\}")
RE_BEGIN_ENV = re.compile(r"\\begin\{(\w+\*?)\}")
RE_FLOAT_SPEC_H = re.compile(r"\\begin\{(?:figure|table)\*?\}\s*\[H\]")
RE_INCLUDEPDF = re.compile(r"\\includepdf")
RE_MULTICOLS = re.compile(r"\\begin\{multicols\*?\}|\\usepackage[^%]*\{multicol")
RE_TWOCOLUMN_CMD = re.compile(r"\\twocolumn\b")
RE_TABULAR_SPEC = re.compile(
    r"\\begin\{tabular\*?x?\}(?:\[[^\]]*\])?(?:\s*\{[^}]*\})?\s*\{([^}]*)\}"
)

FLOAT_ENVS = {
    "figure",
    "figure*",
    "table",
    "table*",
    "wrapfigure",
    "wraptable",
    "sidewaystable",
    "sidewaysfigure",
}
TABLE_BODY_ENVS = {"tabular", "tabularx", "tabulary", "longtable", "tabu"}


def parse_log(log_path: Path) -> dict:
    try:
        data = log_path.read_bytes()
    except OSError:
        return {"log": None}
    m = RE_OUT_WRITTEN.search(data)
    return {
        "log": log_path.name,
        "out_pdf": m.group(1).decode(errors="replace") if m else None,
        "pages": int(m.group(2)) if m else None,
        "of_h": len(RE_OF_H.findall(data)),
        "of_v": len(RE_OF_V.findall(data)),
        "uf_h": len(RE_UF_H.findall(data)),
        "uf_v": len(RE_UF_V.findall(data)),
        "float_fit": len(RE_FLOAT_FIT.findall(data)),
        "float_lost": len(RE_TOO_MANY_FLOATS.findall(data)),
        "log_bytes": len(data),
    }


def find_main_log(d: Path) -> Path | None:
    logs = list(d.glob("*.log"))
    if not logs:
        return None
    # the main log is the one whose stem matches the main pdf, or the biggest
    pdfs = {p.stem for p in d.glob("*.pdf")}
    for lg in logs:
        if lg.stem in pdfs:
            return lg
    return max(logs, key=lambda p: p.stat().st_size)


def cmd_metrics(args: argparse.Namespace) -> None:
    work = Path(args.work)
    out = Path(args.out)
    n = 0
    with out.open("w") as fh:
        for sid_dir in sorted(work.iterdir()):
            if not sid_dir.is_dir():
                continue
            rec: dict = {"id": sid_dir.name}
            for arm, sub in (("en", "build-base"), ("zh_mock", "splice")):
                d = sid_dir / sub
                if not d.is_dir():
                    continue
                lg = find_main_log(d)
                rec[arm] = parse_log(lg) if lg else {"log": None}
            # real-zh arm lives elsewhere; allow --zh-real-dir pointing at a flat dir
            if args.zh_real_dir:
                d = Path(args.zh_real_dir) / sid_dir.name
                if d.is_dir():
                    lg = find_main_log(d)
                    rec["zh_real"] = parse_log(lg) if lg else {"log": None}
            fh.write(json.dumps(rec) + "\n")
            n += 1
    print(f"metrics: {n} papers -> {out}", file=sys.stderr)


def cmd_features(args: argparse.Namespace) -> None:
    work = Path(args.work)
    out = Path(args.out)
    n = 0
    with out.open("w") as fh:
        for sid_dir in sorted(work.iterdir()):
            src = sid_dir / "src"
            if not src.is_dir():
                continue
            text_parts: list[str] = []
            for tex in src.rglob("*.tex"):
                with contextlib.suppress(OSError):
                    text_parts.append(tex.read_text(errors="replace"))
            text = "\n".join(text_parts)
            m = RE_DOCCLASS.search(text)
            opts = (m.group(2) or "") if m else ""
            docclass = m.group(3) if m else None
            envs = RE_BEGIN_ENV.findall(text)
            n_float = sum(1 for e in envs if e in FLOAT_ENVS)
            n_star = sum(1 for e in envs if e.endswith("*") and e in FLOAT_ENVS)
            n_tabbody = sum(1 for e in envs if e in TABLE_BODY_ENVS)
            col_max = 0
            for spec in RE_TABULAR_SPEC.findall(text):
                cols = len(re.findall(r"[lcr]|[pmb]\{", spec)) + spec.count("X")
                col_max = max(col_max, cols)
            rec = {
                "id": sid_dir.name,
                "docclass": docclass,
                "twocolumn": bool(
                    re.search(r"twocolumn", opts)
                    or RE_TWOCOLUMN_CMD.search(text)
                    or (
                        docclass in {"revtex4-1", "revtex4-2", "IEEEtran"}
                        and re.search(r"twocolumn", opts)
                    )
                ),
                "opts": opts,
                "n_float": n_float,
                "n_float_star": n_star,
                "n_wrapfloat": sum(1 for e in envs if e in {"wrapfigure", "wraptable"}),
                "n_table_body": n_tabbody,
                "tabular_col_max": col_max,
                "n_H": len(RE_FLOAT_SPEC_H.findall(text)),
                "includepdf": bool(RE_INCLUDEPDF.search(text)),
                "multicols": bool(RE_MULTICOLS.search(text)),
                "n_tex": len(text_parts),
            }
            fh.write(json.dumps(rec) + "\n")
            n += 1
    print(f"features: {n} papers -> {out}", file=sys.stderr)


# ---------- ink analysis ----------

P5_HEADER = re.compile(rb"^P5\s+(\d+)\s+(\d+)\s+(\d+)\s")
_DARKMAP = bytes([1] * 200 + [0] * 56)  # pixel<200 -> 1 (ink), else 0


def read_pgm(path: Path):
    data = path.read_bytes()
    m = P5_HEADER.match(data)
    if not m:
        return None
    w, h, _maxv = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return w, h, data[m.end() :]


def page_metrics(w: int, h: int, pix: bytes) -> dict:
    """Ink coverage + bottom-void + right-edge bleed for one grayscale page.

    Footer/header zones excluded: body = y in [8%,92%]. A 'half-empty' page has
    content up top but the band y in [55%,90%] essentially empty (float-deferral
    signature); page numbers at ~95% don't count. 'bleed' = body-zone rows with
    ink right of 93% page width (overfull box into margin).
    """
    body_top, body_bot = int(h * 0.08), int(h * 0.92)
    dark = pix.translate(_DARKMAP)  # 1 where pixel < 200
    row_ink = []
    row_rx = []  # rightmost ink x per body row (0 if none)
    for y in range(body_top, body_bot):
        row = dark[y * w : (y + 1) * w]
        row_ink.append(row.count(1))
        row_rx.append(row.rfind(b"\x01") + 1)  # x+1, 0 when empty
    total_ink = sum(row_ink)
    body_area = (body_bot - body_top) * w
    if total_ink == 0:
        return {"ink": 0.0, "blank": True, "half_empty": False, "bleed_rows": 0}
    # void band: rows in [55%,90%] of page height with <0.5% row ink
    v0, v1 = int(h * 0.55) - body_top, int(h * 0.90) - body_top
    band = row_ink[v0:v1]
    void_rows = sum(1 for c in band if c < w * 0.005)
    bottom_void = void_rows / max(1, len(band))
    # upper content: rows in [8%,50%] with ink
    up = row_ink[: int(h * 0.50) - body_top]
    has_top = sum(1 for c in up if c > w * 0.01) > len(up) * 0.15
    rxs = sorted((x / w for x in row_rx if x), reverse=True)
    rx_p95 = rxs[int(len(rxs) * 0.05)] if len(rxs) > 20 else (rxs[-1] if rxs else 0)
    return {
        "ink": total_ink / body_area,
        "blank": total_ink / body_area < 0.002,
        "bottom_void": bottom_void,
        "half_empty": bottom_void > 0.85 and has_top,
        "rx_max": rxs[0] if rxs else 0.0,
        "rx_top5": rxs[:5],
        "rx_p95": rx_p95,
    }


def render_pdf(pdf: Path, outdir: Path, dpi: int = 60) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftoppm", "-gray", "-r", str(dpi), str(pdf), str(outdir / "pg")],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return sorted(outdir.glob("pg-*.pgm"))


def pdf_ink(pdf: Path, workdir: Path, dpi: int) -> dict:
    pgms = render_pdf(pdf, workdir, dpi)
    pages = []
    for p in pgms:
        r = read_pgm(p)
        if r:
            pages.append(page_metrics(*r))
    for p in pgms:
        p.unlink()
    n_blank = sum(1 for pg in pages if pg.get("blank"))
    n_halfempty = sum(1 for pg in pages if pg.get("half_empty"))
    # doc-calibrated bleed: text-block right edge = median rx_p95 across
    # non-blank pages; a page "bleeds" when ink pokes >1.5% of width past it
    p95s = [pg["rx_p95"] for pg in pages if not pg.get("blank") and pg.get("rx_p95")]
    p95s.sort()
    baseline_rx = p95s[len(p95s) // 2] if p95s else 1.0
    for pg in pages:
        pg["bleed"] = bool(
            not pg.get("blank") and pg.get("rx_max", 0) > baseline_rx + 0.015
        )
    n_bleed = sum(1 for pg in pages if pg["bleed"])
    return {
        "pages": len(pages),
        "blank": n_blank,
        "half_empty": n_halfempty,
        "bleed_pages": n_bleed,
        "ink_mean": sum(pg.get("ink", 0) for pg in pages) / max(1, len(pages)),
        "page_detail": pages,
    }


def cmd_ink(args: argparse.Namespace) -> None:
    """pairs file: jsonl {id, en: path, zh: path} (either may be null)."""
    out = Path(args.out)
    scratch = Path(args.scratch)
    done = set()
    if out.exists():
        for line in out.open():
            done.add(json.loads(line)["id"])
    n = 0
    with out.open("a") as fh:
        for line in Path(args.pairs).open():
            pair = json.loads(line)
            if pair["id"] in done:
                continue
            rec = {"id": pair["id"]}
            for arm in ("en", "zh"):
                pdf = pair.get(arm)
                if pdf and Path(pdf).exists():
                    wd = scratch / f"{pair['id']}-{arm}"
                    try:
                        rec[arm] = pdf_ink(Path(pdf), wd, args.dpi)
                    except subprocess.CalledProcessError as e:
                        rec[arm] = {"error": e.stderr.decode()[:200]}
                    for f in wd.glob("*"):
                        f.unlink()
                    wd.rmdir()
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            n += 1
            if n % 10 == 0:
                print(f"ink: {n} rendered", file=sys.stderr)
    print(f"ink: {n} papers -> {out}", file=sys.stderr)


def cmd_report(args: argparse.Namespace) -> None:
    feats = {}
    if args.features and Path(args.features).exists():
        for line in Path(args.features).open():
            d = json.loads(line)
            feats[d["id"]] = d
    mets = {}
    if args.metrics and Path(args.metrics).exists():
        for line in Path(args.metrics).open():
            d = json.loads(line)
            mets[d["id"]] = d
    inks = {}
    if args.ink and Path(args.ink).exists():
        for line in Path(args.ink).open():
            d = json.loads(line)
            inks[d["id"]] = d
    rows = []
    for pid in sorted(set(mets) | set(inks)):
        row = {"id": pid}
        row.update(feats.get(pid, {}))
        m = mets.get(pid, {})
        for arm in ("en", "zh_mock", "zh_real"):
            if m.get(arm):
                for k, v in m[arm].items():
                    row[f"{arm}_{k}"] = v
        ik = inks.get(pid, {})
        for arm in ("en", "zh"):
            if ik.get(arm):
                a = dict(ik[arm])
                a.pop("page_detail", None)
                for k, v in a.items():
                    row[f"ink_{arm}_{k}"] = v
        rows.append(row)
    with Path(args.out).open("w") as fh:
        fh.writelines(json.dumps(r) + "\n" for r in rows)
    print(f"joined: {len(rows)} -> {args.out}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("metrics")
    p.add_argument("--work", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--zh-real-dir", default=None)
    p.set_defaults(fn=cmd_metrics)

    p = sub.add_parser("features")
    p.add_argument("--work", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_features)

    p = sub.add_parser("ink")
    p.add_argument("--pairs", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--scratch", required=True)
    p.add_argument("--dpi", type=int, default=60)
    p.set_defaults(fn=cmd_ink)

    p = sub.add_parser("report")
    p.add_argument("--features", default=None)
    p.add_argument("--metrics", default=None)
    p.add_argument("--ink", default=None)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_report)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
