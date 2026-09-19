#!/usr/bin/env python3
r"""wrapfloat_bench.py — wrapfig 绕排碰撞 bench：布局级检出 + 降级修复验证。

动机案例：2609.19101 zh 版第 6 页 ``wrapfigure``（图 5）绕排区因译文缩短滑到
页底，与 ``table[b]`` 浮动表重叠；手工修成 ``figure[tb]`` 后该页干净。wrapfig
的绕排落点本质依赖后续段落行数，译文长度变化必然改变落点——本 bench 把这个
「依赖运气的排版本质」变成可测断言。

检出信号（poppler，不需 python pdf 库）：
  - ``pdftohtml -xml`` → 逐页 ``<image>``/``<text>`` bbox → image∩text 与
    text∩text 两类交集面积超阈 = 重叠（重叠排版在正常版式里不可能出现，
    阈值吃 kerning 边贴误报）。
  - ``pdftotext`` → 期望 caption 片段在场（页底裁切型碰撞的探针——裁掉的
    内容不会出现在文本层）。

案例（确定性 fixture——填充串钉死保证分页可复现）：
  A ``tableB_short``       ``table[b]`` + 短段落 → **期望碰撞**（2609.19101 亚型）
  B ``tableB_long``        ``table[b]`` + 长段落 → **期望碰撞**（页底绕排锚点
                           与段落长度无关——锚段落恰好落页底即撞）
  C ``tableT_long``        ``table[t]`` + 长段落 → 期望干净（运气好的绕排基线：
                           顶部浮体不占页底，绕排盒独占右下）
  每例配 ``*_demoted`` 臂——``demote_wrapfloats``（inject.py zh 侧降级手术）
  应用后期望全部干净 + caption 在场。函数缺席时降级臂记 ``skip``——本 bench
  先红（A/B 检出碰撞、降级臂 skip）后绿（降级臂全 clean）。fixture 的
  wrapfig 体复刻真实论文惯用的负 ``\vspace`` 收区 hack（``-10pt`` 图前 +
  ``-24pt`` caption 内）——降级不清掉则 caption 尾行溢出浮体盒压正文
  （2609.19101 demoted 构建目检实证的降级引入亚型）。

``--corpus N``：从 ``bench/corpus_daily``（wrapfloat 实测 32 篇在场语料）抽 N 篇
含 wrapfig 的论文做「原文臂 vs 降级臂」编译对照——降级不得让本来能编的工程
编不出来（译树无关失败标 ``en-broken`` 不算回归）。

产出 ``bench/results/wrapfloat-<date>/``：cases.jsonl + corpus.json + summary.md
+ work/（逐臂 tex/png/pdf/xml 现场）。

用法：
  uv run python bench/py/wrapfloat_bench.py              # 合成六臂 + 语料清单
  uv run python bench/py/wrapfloat_bench.py --corpus 4   # 附加真实论文编译对照
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import benchlib

RESULTS = ROOT / "bench/results"
CORPORA = [
    ROOT / "bench/corpus",
    ROOT / "bench/corpus_daily",
]
WRAP_RX = re.compile(rb"\\begin\s*\{wrap(?:figure|table|float)\*?\}")

CAPTION_FRAG = "Steering along our probe direction"
#: bbox 交集阈值：绝对下限 + 占小盒面积比下限（kerning 边贴/行盒紧邻误报闸）
OVERLAP_MIN_AREA = 150.0
OVERLAP_MIN_FRAC = 0.05
#: poppler 绝对路径（S607）；找不到退裸名交 PATH 解析。
_PDFTOHTML = shutil.which("pdftohtml") or "pdftohtml"
_PDFTOTEXT = shutil.which("pdftotext") or "pdftotext"

# ------------------------------------------------------------ fixture 生成

_LONG = (
    "Before applying our probes for monitoring purposes, we conduct a few analyses "
    "to better understand what the probes encode. Despite being generated on data "
    "that does not explicitly mention hacking or cheating, we find that these "
    "vectors represent these concepts coherently and consistently across a wide "
    "range of model families and training regimes. "
)
_SHORT = "我们发现这些向量连贯地表示了这些概念。 "
_FILL = (_LONG * 8) + "\n\n" + (_LONG * 8)

_DOC = r"""\documentclass{article}
\usepackage{graphicx,wrapfig,booktabs}
\begin{document}
\section{Intro}
FILLER

\begin{table}[TABLESPEC]
\centering\footnotesize
\begin{tabular}{@{}lll@{}}
\toprule
Contrast & Layer & Top-5 promoted tokens \\
\midrule
Delete failing tests & 60 & cheating, sabot, deleting \\
Exploit a fixture & 60 & cheating, cheat, disgu, hack \\
Read hidden tests & 46 & illicit, doubled, sneak \\
Honest outcome control & 44 & inconsistent, disappointing \\
Fabricate a report & 57 & joking, wrong, actually \\
Exploit a fixture & 53 & unethical, trol, dishonest \\
\bottomrule
\end{tabular}
\caption{Logit-lens readout of each probe direction.}
\label{tab:lens}
\end{table}

\subsection{Probe Vectors}
\begin{wrapfigure}{r}{0.5\textwidth}
  \centering
  \vspace{-10pt}
  \includegraphics[width=0.98\linewidth]{fig.png}
  \caption{Steering along our probe direction elicits cheating.
  We plant a honeypot and observe how often the model invokes
  the function with vs. without steering.
  \vspace{-24pt}
  }
  \label{fig:honeypot}
\end{wrapfigure}
PARAS
\end{document}
"""


def _png(path: Path, w: int = 400, h: int = 300, rgb=(70, 110, 180)) -> None:
    """stdlib PNG（蓝块占位图——includegraphics 的 raster 载荷）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        head = struct.pack(">I", len(data)) + tag + data
        return head + struct.pack(">I", zlib.crc32(tag + data))

    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    blob = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(blob)


def synth_doc(table_spec: str, paras: str) -> str:
    return (
        _DOC.replace("TABLESPEC", table_spec)
        .replace("FILLER", _FILL)
        .replace("PARAS", paras)
    )


# ------------------------------------------------------------ 检出


def _boxes(xml_path: Path) -> list[dict]:
    """pdftohtml -xml → 逐页 image/text bbox 平铺 [{page,kind,top,left,w,h}]。"""
    import xml.etree.ElementTree as ET

    boxes: list[dict] = []
    root = ET.parse(xml_path).getroot()  # noqa: S314 — pdftohtml 自产 XML 非不可信输入
    for page in root.iter("page"):
        pno = int(page.get("number", "0"))
        for el in page:
            if el.tag not in ("image", "text"):
                continue
            boxes.append(
                {
                    "page": pno,
                    "kind": el.tag,
                    "top": float(el.get("top", "0")),
                    "left": float(el.get("left", "0")),
                    "w": float(el.get("width", "0")),
                    "h": float(el.get("height", "0")),
                }
            )
    return boxes


def _inter(a: dict, b: dict) -> float:
    x = min(a["left"] + a["w"], b["left"] + b["w"]) - max(a["left"], b["left"])
    y = min(a["top"] + a["h"], b["top"] + b["h"]) - max(a["top"], b["top"])
    return x * y if x > 0 and y > 0 else 0.0


def detect_overlap(xml_path: Path) -> list[dict]:
    """image∩text + text∩text 超阈交集对清单（命中即重叠排版）。"""
    boxes = _boxes(xml_path)
    hits: list[dict] = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            if a["page"] != b["page"]:
                continue
            if a["kind"] == "image" and b["kind"] == "image":
                continue
            area = _inter(a, b)
            small = min(a["w"] * a["h"], b["w"] * b["h"]) or 1.0
            if area > OVERLAP_MIN_AREA and area / small > OVERLAP_MIN_FRAC:
                pair = f"{a['kind']}∩{b['kind']}"
                hits.append({"page": a["page"], "pair": pair, "area": round(area)})
    return hits


def caption_present(pdf: Path, frag: str) -> bool:
    out = subprocess.run(
        [_PDFTOTEXT, str(pdf), "-"], capture_output=True, text=True
    ).stdout
    return frag in re.sub(r"\s+", " ", out)


# ------------------------------------------------------------ 编译臂


def _engine():
    from texlate.compile.engine import engine_for

    return engine_for("tectonic")


def _demote(root: Path) -> int | None:
    """lazy-import zh 侧降级手术——函数缺席（fix 未落）返 None 记 skip。"""
    try:
        from texlate.compile.inject import demote_wrapfloats
    except ImportError:
        return None
    return demote_wrapfloats(root)


def run_case(case_dir: Path, tex: str, *, demote: bool) -> dict:
    """单臂：落 main.tex + fig.png → （按需降级）→ tectonic → 检出三件套。"""
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "main.tex").write_text(tex, encoding="utf-8")
    _png(case_dir / "fig.png")
    rec: dict = {"case": case_dir.name, "demoted": demote}
    if demote:
        n = _demote(case_dir)
        rec["demote_n"] = n
        if n is None:
            rec["verdict"] = "skip"
            rec["note"] = "demote_wrapfloats not available"
            return rec
        rec["still_wrapfig"] = bool(
            WRAP_RX.search((case_dir / "main.tex").read_bytes())
        )
    eng = _engine()
    res = eng.compile(case_dir, "main.tex", timeout=240, sandbox=False)
    rec["compile_ok"] = bool(res.ok and res.pdf)
    if not rec["compile_ok"]:
        rec["verdict"] = "compile-fail"
        rec["note"] = (res.stdout_tail or "")[-200:]
        return rec
    pdf = res.pdf
    xml_prefix = case_dir / "xml"
    subprocess.run(
        [_PDFTOHTML, "-xml", "-nodrm", str(pdf), str(xml_prefix)],
        capture_output=True,
        cwd=case_dir,
    )
    xml = xml_prefix.with_suffix(".xml")
    rec["overlaps"] = detect_overlap(xml) if xml.exists() else []
    rec["caption_present"] = caption_present(pdf, CAPTION_FRAG)
    bad = rec["overlaps"] or not rec["caption_present"]
    rec["verdict"] = "collision" if bad else "clean"
    return rec


# ------------------------------------------------------------ 语料


def corpus_inventory() -> dict:
    """各语料库 wrapfloat 用量盘点（论文级口径）。"""
    inv: dict = {}
    for c in CORPORA:
        if not c.is_dir():
            continue
        files = [
            p
            for p in c.rglob("*.tex")
            if p.suffix == ".tex" and WRAP_RX.search(p.read_bytes())
        ]
        papers = {p.relative_to(c).parts[0] for p in files}
        inv[c.name] = {"files": len(files), "papers": len(papers)}
    return inv


def _wrapfloat_papers(corpus: Path) -> list[str]:
    hits = set()
    for p in corpus.rglob("*.tex"):
        if p.suffix != ".tex" or not WRAP_RX.search(p.read_bytes()):
            continue
        hits.add(p.relative_to(corpus).parts[0])
    return sorted(hits)


def run_corpus_pair(corpus: Path, paper: str, work: Path) -> dict:
    """真实论文对照：原文臂 vs 降级臂编译回归（en 不能编→en-broken 不计）。"""
    src = corpus / paper
    if (src / "extracted").is_dir():
        src = src / "extracted"
    rec = {"paper": paper}
    for arm in ("orig", "demoted"):
        dest = work / f"{paper.replace('/', '_')}-{arm}"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        n = _demote(dest) if arm == "demoted" else 0
        if n is None:
            rec["verdict"] = "skip"
            return rec
        eng = _engine()
        res = eng.compile(dest, _find_main(dest), timeout=240, sandbox=False)
        rec[arm] = {"ok": bool(res.ok and res.pdf), "demote_n": n}
    if not rec["orig"]["ok"]:
        rec["verdict"] = "en-broken"
    elif not rec["demoted"]["ok"]:
        rec["verdict"] = "regression"
    else:
        rec["verdict"] = "ok"
    return rec


def _find_main(root: Path) -> str:
    from texlate.compile.inject import find_main_tex

    m = find_main_tex(root)
    return m.relative_to(root).as_posix() if m else "main.tex"


# ------------------------------------------------------------ main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=int, default=0, help="corpus_daily 抽样篇数")
    ap.add_argument("--out", default=None, help="results 子目录名覆写")
    ap.add_argument("--seed", type=int, default=20260919)
    args = ap.parse_args()

    date = time.strftime("%Y-%m-%d")
    out = RESULTS / (args.out or f"wrapfloat-{date}")
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)

    cases = [
        ("tableB_short", synth_doc("b", _SHORT * 4), False, "collision"),
        ("tableB_short_demoted", synth_doc("b", _SHORT * 4), True, "clean"),
        ("tableB_long", synth_doc("b", _LONG * 45), False, "collision"),
        ("tableB_long_demoted", synth_doc("b", _LONG * 45), True, "clean"),
        ("tableT_long", synth_doc("t", _LONG * 45), False, "clean"),
        ("tableT_long_demoted", synth_doc("t", _LONG * 45), True, "clean"),
    ]
    results = []
    for name, tex, demote, expect in cases:
        rec = run_case(work / name, tex, demote=demote)
        rec["expect"] = expect
        if rec["verdict"] != "skip":
            rec["pass"] = rec["verdict"] == expect
        results.append(rec)
        print(
            f"[{name:24s}] verdict={rec['verdict']:13s} expect={expect:9s} "
            f"overlaps={len(rec.get('overlaps', []))} caption={rec.get('caption_present')}"
        )

    inv = corpus_inventory()
    (out / "corpus.json").write_text(
        json.dumps(inv, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    corpus_rows = []
    if args.corpus:
        papers = _wrapfloat_papers(ROOT / "bench/corpus_daily")
        picked = (
            benchlib.pick_sample(
                [{"id": p} for p in papers],
                ROOT / "bench/corpus_daily",
                args.corpus,
                args.seed,
            )
            if papers
            else []
        )
        for p in picked:
            row = run_corpus_pair(ROOT / "bench/corpus_daily", p, work)
            corpus_rows.append(row)
            print(f"[corpus {p:20s}] {row['verdict']}")

    with (out / "cases.jsonl").open("w") as fh:
        for r in results:
            benchlib.write_jsonl(fh, r)
    if corpus_rows:
        with (out / "corpus_cases.jsonl").open("w") as fh:
            for r in corpus_rows:
                benchlib.write_jsonl(fh, r)

    n_pass = sum(1 for r in results if r.get("pass"))
    n_skip = sum(1 for r in results if r["verdict"] == "skip")
    lines = [
        f"# wrapfloat bench {date}",
        "",
        f"- synth cases: {n_pass}/{len(results) - n_skip} 符合期望"
        + (f"（{n_skip} 臂 skip：降级手术未落）" if n_skip else ""),
        "- corpus wrapfloat 清单："
        + ", ".join(f"{k}={v['papers']}篇" for k, v in inv.items()),
    ]
    for r in results:
        ov = f" overlaps={r['overlaps']}" if r.get("overlaps") else ""
        lines.append(
            f"- `{r['case']}`: {r['verdict']}（期望 {r['expect']}）"
            f" caption={r.get('caption_present')}{ov}"
        )
    lines.extend(f"- corpus `{r['paper']}`: {r['verdict']}" for r in corpus_rows)
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nresults → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
