#!/usr/bin/env python3
r"""iclr_pdf_sections.py — OpenReview PDF → 章节级词数统计（无 arXiv 兜底臂）.

与 iclr_sections.py 同口径输出：每篇一行 sections 明细 + 聚合计数，
bucket 规则直接复用 LaTeX 臂（canon_section/count_words），两臂可比。

PDF 解析策略（ICLR 单栏版式前提）:
  pdftotext -layout 抽文（编号与标题同行；raw 模式下 ICLR 标题
  字距拉开会拆行）→ NFKC 归一（连字）→ 剥页眉页脚/页码行 →
  行级扫描编号标题（``1 Introduction`` / ``2.1 Setup`` / ``A Proof``）+
  已知无编号标题白名单 → despace 修复字距大写（``I NTRODUCTION``
  → ``INTRODUCTION``；首字母被吃成 tag 时拼回判别 ``A BSTRACT``
  → Abstract）→ 编号单调性 + Title-Case 比例 + 目录点线排除
  三闸门压误报 → 相邻标题间词数（标题行自身不计，同 LaTeX 臂）。

已知精度差（报告须注明）: PDF 文本里数学符号无法剥离，词数系统性
偏高；同篇双臂重叠论文用于校准该偏差。

输入: bench/corpus_iclr_pdf/{orid}.pdf
输出: bench/work_iclr/sections_pdf.jsonl（断点续跑）

用法: uv run python bench/py/iclr_pdf_sections.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PDF_DIR = REPO / "bench" / "corpus_iclr_pdf"
OUT = REPO / "bench" / "work_iclr" / "sections_pdf.jsonl"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from iclr_sections import canon_section, count_words  # noqa: E402
from specs import _benchlite as benchlib

#: stderr 时间戳日志——benchlib 单源（iclr_* 系同源件）。
log = benchlib.log

# ---------------- 行级清洗 ----------------

RUNNING_HEAD_RX = re.compile(
    r"(published as|under review|accepted|submitted|conference paper|workshop)"
    r".*(iclr|international conference on learning representations)"
    r"|^(iclr|international conference on learning representations)\b.*\d{4}"
    r"|openreview\.net",
    re.I,
)
PAGE_NUM_RX = re.compile(r"^\s*\d{1,4}\s*$")
DEHYPHEN_RX = re.compile(r"([A-Za-z])-\n([a-z])")

# 编号标题: "1 Introduction" / "2.1 Setup" / "A.2 Proof" / "B Details"
NUM_HEAD_RX = re.compile(
    r"^\s*(\d+(?:\.\d+){0,2}|[A-Z](?:\.\d+){0,2})[\s.]+([^\n]{1,90}?)\s*$"
)
# 无编号标题白名单（独立成行才算）
UNNUMBERED_HEADS = re.compile(
    r"^\s*(abstract|references|bibliography|appendix|appendices|"
    r"acknowledg\w*|acknowledgement\w*|reproducibility statement|"
    r"ethics statement|broader impact( statement)?|"
    r"societal impact|author contributions?|checklist)\s*$",
    re.I,
)
BAD_TAIL_RX = re.compile(r"[.,;:]$")
TOC_RX = re.compile(r"\.{3,}|\s\d{1,3}$")  # 目录点线/尾随页码
LETTER_SPACE_RX = re.compile(r"\b([A-Z]) (?=[A-Z]{2,})")  # 字距大写: I NTRODUCTION
# 拼回判别集: tag 单字母 + 字距标题 = 完整白名单词（A+BSTRACT→ABSTRACT）
JOINED_UNNUMBERED = {
    "ABSTRACT", "REFERENCES", "BIBLIOGRAPHY", "APPENDIX", "APPENDICES",
    "ACKNOWLEDGMENTS", "ACKNOWLEDGEMENTS", "REPRODUCIBILITYSTATEMENT",
    "ETHICSSTATEMENT", "BROADERIMPACT", "BROADERIMPACTSTATEMENT",
    "SOCIETALIMPACT", "AUTHORCONTRIBUTION", "AUTHORCONTRIBUTIONS",
    "CHECKLIST",
}


def despace(t: str) -> str:
    return LETTER_SPACE_RX.sub(r"\1", t)


def titlecase_ratio(title: str) -> float:
    """词首大写占比——正文句子罕见 >0.4，标题通常全大写词或 Title Case."""
    words = re.findall(r"[A-Za-z]{2,}", title)
    if not words:
        return 0.0
    cap = sum(1 for w in words if w[0].isupper() or w.isupper())
    return cap / len(words)


def detect_headings(lines: list[str]) -> list[tuple[int, int, str, str]]:
    """行级标题检测 → [(行号, level, raw标题, number_tag|'')].

    闸门: 结尾无句读、无目录点线、词数 ≤12、Title-Case ≥0.4；
    编号单调——数字顶级只能持平/+1（不许回跳到新号），字母顶级
    （附录）从 A 起递增。无编号白名单恒接受。
    """
    out: list[tuple[int, int, str, str]] = []
    prev_num = 0
    seen_num: set[int] = set()
    seen_app: set[int] = set()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or PAGE_NUM_RX.match(s):
            continue
        m = NUM_HEAD_RX.match(s)
        if m:
            tag, title = m.group(1), despace(m.group(2).strip())
            # 字距首字母被吃成 tag: A+BSTRACT→ABSTRACT 拼回白名单 → 无编号标题
            if len(tag) == 1 and tag.isalpha():
                joined = tag + title.replace(" ", "")
                if joined.upper() in JOINED_UNNUMBERED:
                    out.append((i, 1, joined.title(), ""))
                    continue
            if (
                BAD_TAIL_RX.search(title)
                or re.search(r"[?!]", title)  # 章节标题不带疑问/感叹
                or TOC_RX.search(title)
                or len(title.split()) > 12
                or titlecase_ratio(title) < 0.4
            ):
                continue
            parts = tag.split(".")
            if tag[0].isalpha():  # 附录字母编号 A/B/…
                if not seen_num:
                    continue  # 附录必在正文编号之后；否则是字距大写标题行误吃
                top = ord(parts[0].upper()) - ord("A") + 1
                if (seen_app and top > max(seen_app) + 1) or (
                    not seen_app and top != 1
                ):
                    continue
                seen_app.add(top)
            else:
                top = int(parts[0])
                if top > prev_num + 1 or (top < prev_num and top not in seen_num):
                    continue
                prev_num = max(prev_num, top)
                seen_num.add(top)
            out.append((i, tag.count(".") + 1, title, tag))
            continue
        if UNNUMBERED_HEADS.match(s):
            out.append((i, 1, s, ""))
    return out


# ---------------- 单篇分析 ----------------

def pdftotext(pdf: Path) -> str | None:
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
            capture_output=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def analyze_pdf(pdf: Path) -> dict:
    orid = pdf.stem
    raw = pdftotext(pdf)
    if raw is None:
        return {"orid": orid, "arm": "pdf", "status": "pdftotext_fail"}
    if len(raw.strip()) < 500:
        return {"orid": orid, "arm": "pdf", "status": "empty"}
    n_pages = raw.count("\f") or 1
    text = unicodedata.normalize("NFKC", raw).replace("\f", "\n")
    lines = [
        ln for ln in text.split("\n")
        if not RUNNING_HEAD_RX.search(ln) and not PAGE_NUM_RX.match(ln)
    ]
    heads = detect_headings(lines)
    if len(heads) < 2:
        return {"orid": orid, "arm": "pdf", "status": "few_headings",
                "n_pages": n_pages, "n_headings": len(heads)}

    def span_words(a: int, b: int) -> int:
        chunk = DEHYPHEN_RX.sub(r"\1\2", "\n".join(lines[a:b]))
        return count_words(chunk)

    sections: list[dict] = []
    cur_appendix = False
    for idx, (ln_i, level, title, tag) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        w = span_words(ln_i + 1, end)  # 标题行自身不计（同 LaTeX 臂）
        bucket = canon_section(title)
        if (
            bucket == "appendix"
            or (tag and tag[0].isalpha())
            or re.match(r"appendix\b", title, re.I)  # 数字编号的 "8 APPENDIX A:"
        ):
            cur_appendix = True
        if cur_appendix and bucket == "other":
            bucket = "appendix"
        sections.append({
            "raw": title[:120], "bucket": bucket, "level": level,
            "order": idx + 1, "words": w, "chars": 0, "caption_words": 0,
            "appendix": cur_appendix and bucket != "references",
            "unnumbered": not tag,
        })

    preface_words = span_words(0, heads[0][0])
    abstract_words = next(
        (s["words"] for s in sections if s["bucket"] == "abstract"), 0
    )
    n_top = sum(1 for s in sections if s["level"] == 1)
    body_words = sum(
        s["words"] for s in sections
        if not s["appendix"] and s["bucket"] != "references"
    )
    appendix_words = sum(
        s["words"] for s in sections if s["appendix"] or s["bucket"] == "appendix"
    )
    refs_words = sum(s["words"] for s in sections if s["bucket"] == "references")
    return {
        "orid": orid, "arm": "pdf", "status": "ok", "n_pages": n_pages,
        "n_headings": len(heads), "preface_words": preface_words,
        "abstract_words": abstract_words, "n_top_sections": n_top,
        "body_words": body_words, "appendix_words": appendix_words,
        "refs_words": refs_words, "sections": sections,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdfdir", default=str(PDF_DIR))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    pdfs = sorted(Path(a.pdfdir).glob("*.pdf"))
    done_ids: set[str] = set()
    outp = Path(a.out)
    if outp.exists():
        for l in outp.open():
            try:
                done_ids.add(json.loads(l)["orid"])
            except json.JSONDecodeError:
                pass
    todo = [p for p in pdfs if p.stem not in done_ids]
    if a.limit:
        todo = todo[: a.limit]
    log(f"pdf sections: total={len(pdfs)} done={len(done_ids)} todo={len(todo)}")

    stat: Counter = Counter()
    outp.parent.mkdir(parents=True, exist_ok=True)
    with outp.open("a") as f:
        for i, p in enumerate(todo, 1):
            try:
                rec = analyze_pdf(p)
            except Exception as e:  # noqa: BLE001
                rec = {"orid": p.stem, "arm": "pdf", "status": "crash",
                       "error": f"{type(e).__name__}: {e}"}
            stat[rec["status"]] += 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 200 == 0:
                f.flush()
                log(f"  [{i}/{len(todo)}] {dict(stat)}")
    log(f"done: {dict(stat)} -> {outp}")


if __name__ == "__main__":
    main()
