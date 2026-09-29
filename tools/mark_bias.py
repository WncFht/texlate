"""批量核验：全部任务中 BDC 落在 \\sectioning{...} 参数内的 mark，测其与
标题字形真实位置的偏差分布（pymupdf 逐字 bbox 顶向下 frac 与 seqpos 同口径）。

输出：每枚标题类 mark 的 (task, seq, parent_cs, mark_page/frac, 同页最近文本命中 frac, Δ)。
Δ<0 = mark 在文本上方（stale-tm 方向），|Δ|>0.03 肉眼可见。
注意：marks_with_tm 复刻的是「旧口径」BDC-tm 锚法，用来量化 stale-tm 偏置；
seqpos v6+ 改锚到标内首字形后，本工具对比的是新旧口径差异。

用法：.venv/bin/python tools/mark_bias.py
"""

import json
import re
from pathlib import Path

import pymupdf
from pypdf import PdfReader

from _env import TASKS
from texlate.server.seqpos import _norm_chars, _tex_strip
BDC_RX = re.compile(r"\\special\{pdf:code /TLXC <</MCID (\d+)>> BDC\}")
ARG_RX = re.compile(r"\\([a-zA-Z@]+\*?)\s*\{\s*$")
SECT_CS = {
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "subparagraph",
    "chapter",
    "part",
    "title",
    "sect",
    "subsect",
    "caption",
    "captionof",
    "author",
    "thanks",
    "IEEEauthorblockN",
    "IEEEauthorblockA",
}


def marks_with_tm(path: Path):
    """旧口径：seq → (page1, frac)（BDC 时的 tm，setdefault 首个）。"""
    reader = PdfReader(str(path))
    marks = {}
    for pi, page in enumerate(reader.pages):
        height = float(page.mediabox.height)

        def vob(op, args, cm, tm, _pi=pi, _h=height):
            if op != b"BDC" or len(args) < 2:
                return
            prop = args[1]
            d = prop.get_object() if hasattr(prop, "get_object") else prop
            mcid = d.get("/MCID") if hasattr(d, "get") else None
            try:
                seq = int(mcid) - 50000
            except (TypeError, ValueError):
                return
            if seq < 0:
                return
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            marks.setdefault(seq, (_pi + 1, round(1 - (y + 6) / _h, 5)))

        page.extract_text(visitor_operand_before=vob)
    return marks


def page_charpos(doc: pymupdf.Document):
    """每页 (归一字符流，[frac]) —— 逐字 bbox 顶向下。"""
    out = []
    for pno in range(doc.page_count):
        page = doc[pno]
        h = page.rect.height or 1
        rd = page.get_text("rawdict")
        chars, pos = [], []
        for blk in rd.get("blocks", []):
            for ln in blk.get("lines", []):
                for sp in ln.get("spans", []):
                    for ch in sp.get("chars", []):
                        n = _norm_chars(ch.get("c", ""))
                        if not n:
                            continue
                        chars.extend(n)
                        pos.extend([ch["bbox"][1] / h] * len(n))
        out.append(("".join(chars), pos))
    return out


def main():
    rows = []
    for tdir in sorted(TASKS.iterdir()):
        zh, zhpdf, dualp = tdir / "zh", tdir / "zh.pdf", tdir / "dual.json"
        if not (zh.is_dir() and zhpdf.is_file() and dualp.is_file()):
            continue
        try:
            dual = json.loads(dualp.read_text())
        except Exception:
            continue
        chunks = {
            c["seq"]: c for c in dual.get("chunks", []) if isinstance(c.get("seq"), int)
        }
        # 标题类 mark = BDC 紧邻 \cs{ 且 cs ∈ SECT_CS
        in_arg: dict[int, str] = {}
        for f in zh.rglob("*.tex"):
            try:
                t = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in BDC_RX.finditer(t):
                pre = t[max(0, m.start() - 400) : m.start()]
                im = ARG_RX.search(pre)
                if im and im.group(1).rstrip("*").lower() in {
                    s.lower() for s in SECT_CS
                }:
                    in_arg[int(m.group(1)) - 50000] = im.group(1)
        if not in_arg:
            continue
        try:
            marks = marks_with_tm(zhpdf)
        except Exception as e:
            print(f"{tdir.name} pypdf fail: {e}")
            continue
        doc = pymupdf.open(zhpdf)
        pages = page_charpos(doc)
        for seq, cs in sorted(in_arg.items()):
            if seq not in marks:
                continue
            c = chunks.get(seq) or {}
            nd = _norm_chars(_tex_strip(c.get("zh") or ""))
            probe = nd[:14] if len(nd) >= 14 else nd
            if len(probe) < 2:
                continue
            mpg, mfr = marks[seq]
            stream, pos = pages[mpg - 1]
            # 同页全部命中 → 最近者
            hits = []
            start = 0
            while True:
                j = stream.find(probe, start)
                if j < 0:
                    break
                hits.append(pos[j])
                start = j + 1
            if not hits:
                rows.append((tdir.name, seq, cs, mpg, mfr, None, None))
                continue
            best = min(hits, key=lambda h: abs(h - mfr))
            rows.append(
                (tdir.name, seq, cs, mpg, mfr, round(best, 5), round(mfr - best, 4))
            )
        doc.close()

    print(
        f"{'task':22} {'seq':>4} {'cs':16} {'pg':>3} {'mark':>8} {'text':>8} {'Δ':>8}"
    )
    for r in rows:
        flag = " <<<" if r[6] is not None and abs(r[6]) > 0.03 else ""
        print(
            f"{r[0]:22} {r[1]:>4} {r[2]:16} {r[3]:>3} {r[4]:>8} {r[5]!s:>8} {r[6]!s:>8}{flag}"
        )
    ds = [r[6] for r in rows if r[6] is not None]
    if ds:
        ds.sort()
        n = len(ds)
        print(
            f"\nn={n}  p10={ds[n // 10]} p50={ds[n // 2]} p90={ds[min(n - 1, int(n * 0.9))]}"
        )
        print(f"min={ds[0]} max={ds[-1]}")
        big = [d for d in ds if d < -0.03]
        print(f"Δ<-0.03 (mark 偏上>0.03): {len(big)}")
        big2 = [d for d in ds if d > 0.03]
        print(f"Δ>+0.03 (mark 偏下>0.03): {len(big2)}")


main()
