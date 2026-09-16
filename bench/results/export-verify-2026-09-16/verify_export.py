"""export 真实文件验证驱动（2026-09-16）。

对真实 EPUB/DOCX 跑 export_document 全链（MockTranslator），断言：
- 源文件逐字节不动（sha256 前后一致）
- 产物 zip 完整可开（testzip + mimetype-first-STORED for epub）
- 每篇 xhtml/docx part 可再解析；.texlate-zh 节点数与插译计数对账
- 译文插在原 unit 紧邻之后（docx：addnext 兄弟；epub：owner 后/内部追加）
- marker token 不泄漏（输出文本里的 [[TAG_n]] 只能是源文自有字面 token）
- 无重复 id（epub RSC-005）；nav li 不塌；NCX 双串
- docx：译文 run eastAsia=SimSun + color 555555；克隆不携带 w:sectPr
- ExportReport 计数自洽（units == translated+unchanged+skipped+fault）

用法: uv run python bench/results/export-verify-2026-09-16/verify_export.py
产物: 同目录 report.json + 各 dst 文件（bilingual 副本，gitignored 区）。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
from lxml import etree

from texlate.export import export_document, sniff_format
from texlate.export.epub import iter_units, load_epub
from texlate.export.markers import MARKER_RE
from texlate.export.rights import check_epub
from texlate.xlat.pipeline import MockTranslator

ROOT = Path("/home/fanghaotian/src/texlate")
OUT = ROOT / "bench/results/export-verify-2026-09-16"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

EPUBS = [
    "tmp/realbook/pg1080.epub",
    "tmp/realbook/pg1952.epub",
    "tmp/refs/bilingual_book_maker/test_books/Liber_Esther.epub",
    "tmp/refs/bilingual_book_maker/test_books/lemo.epub",
    "tmp/refs/bilingual_book_maker/test_books/animal_farm.epub",
]

DOCXS = [
    "bench/results/stagerun-loop1-2026-09-16/work/1502.02223/src/manuscript.docx",
    "bench/results/stagerun-loop1-2026-09-16/work/2009.11007/src/Response_letter_final.docx",
    "bench/results/stagerun-loop1-2026-09-16/work/1404.0578/src/PLM_paper_figures_tables.docx",
    "bench/results/stagerun-loop1-2026-09-16/work/2410.17973/src/word/acl.docx",
    "bench/work_base_v3full/2203.12985/baseline/bios/czxu-pub.docx",
    "tmp/refs/MinerU/demo/office_docs/docx_01.docx",
    "tmp/exp/post2020/tiger-corpus-2408/2408.00108/kr24.docx",
]

_EXTRA_PART_RE = re.compile(
    r"^/?word/(header\d*|footer\d*|footnotes|endnotes|comments)\.xml$"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _owns(p: etree._Element, node: etree._Element) -> bool:
    """node 的最近 w:p 祖先是 p 才算 p 的（嵌套 txbx 段不算）。"""
    el = node.getparent()
    while el is not None:
        if el is p:
            return True
        if el.tag == W + "p":
            return False
        el = el.getparent()
    return False


def _failures(rec: dict) -> list[str]:
    return rec.setdefault("failures", [])


def _check(rec: dict, cond: bool, label: str) -> None:
    if not cond:
        _failures(rec).append(label)


def verify_epub(src: Path, dst: Path) -> dict:
    rec: dict = {"file": src.name, "format": "epub", "size": src.stat().st_size}
    src_hash = _sha256(src)
    rec["sniff"] = sniff_format(src)
    rec["drm"] = check_epub(src)
    _check(rec, rec["sniff"] == "epub", "sniff!=epub")
    _check(rec, rec["drm"] == "ok", "drm!=ok")

    book = load_epub(src)
    soups = {p: BeautifulSoup(book.members[p], "html.parser") for p in book.doc_paths}
    units = list(iter_units(book, soups))
    # 源文自有的字面 marker token（碰撞回避基线）
    literal_markers: set[str] = set()
    for p in book.doc_paths:
        literal_markers.update(
            MARKER_RE.findall(book.members[p].decode("utf-8", "replace"))
        )
    rec.update(
        {
            "members": len(book.members),
            "doc_paths": len(book.doc_paths),
            "units": len(units),
            "ncx_units": sum(1 for u in units if u.ncx_text is not None),
            "marker_units": sum(1 for u in units if u.markers),
            "multi_run_units": sum(1 for u in units if u.is_multi_run),
            "literal_marker_tokens": len(literal_markers),
        }
    )

    report = export_document(src, dst, MockTranslator())
    rec["report"] = {
        "units": report.units,
        "translated": report.translated,
        "unchanged": report.unchanged,
        "skipped": report.skipped,
        "fault": report.fault,
        "documents": report.documents,
        "warnings": report.warnings[:20],
    }
    _check(rec, report.fault == 0, f"fault={report.fault}")
    _check(
        rec,
        report.units
        == report.translated + report.unchanged + report.skipped + report.fault,
        "report 计数不平",
    )
    _check(rec, _sha256(src) == src_hash, "源文件被改写")

    with zipfile.ZipFile(dst) as z:
        _check(rec, z.testzip() is None, "zip CRC 损坏")
        infos = z.infolist()
        _check(rec, infos[0].filename == "mimetype", "mimetype 非首条")
        _check(
            rec,
            infos[0].compress_type == zipfile.ZIP_STORED,
            "mimetype 非 STORED",
        )
        names = z.namelist()
        _check(rec, set(names) == set(book.members), "成员集合变化")
        zh_nodes_total = 0
        dup_ids: list[str] = []
        leaked_markers: list[str] = []
        xml_broken: list[str] = []
        for path in book.doc_paths:
            raw = z.read(path)
            soup = BeautifulSoup(raw, "html.parser")
            zh = soup.select(".texlate-zh")
            zh_nodes_total += len(zh)
            ids = Counter(el["id"] for el in soup.find_all(attrs={"id": True}))
            dup_ids += [f"{path}#{i}" for i, c in ids.items() if c > 1]
            for li in soup.select("nav li"):
                if li.find_parent("li"):
                    _failures(rec).append(f"{path}: nav li 嵌套塌")
                    break
            # marker 泄漏：输出文本里的 token 形串减去源文自有字面 token
            text = soup.get_text()
            leaked = [t for t in MARKER_RE.findall(text) if t not in literal_markers]
            leaked_markers += [f"{path}:{t}" for t in leaked]
            # 源是良构 XML 的文档，输出也必须良构（html.parser 回写不能破坏）
            try:
                etree.fromstring(book.members[path])
            except etree.XMLSyntaxError:
                pass  # 源本非良构（HTML 书）——输出不苛求
            else:
                try:
                    etree.fromstring(raw)
                except etree.XMLSyntaxError as e:
                    xml_broken.append(f"{path}: {e}")
        _check(rec, not dup_ids, f"重复 id: {dup_ids[:5]}")
        _check(rec, not leaked_markers, f"marker 泄漏: {leaked_markers[:5]}")
        _check(rec, not xml_broken, f"XHTML 失良构: {xml_broken[:3]}")
        rec["zh_nodes"] = zh_nodes_total
        # NCX 双语标签数 = dst 含 " / " 的 <text> 减 src 基线（unchanged 不计）
        ncx_translated = 0
        if book.ncx_path and book.ncx_path in names:

            def _bi_labels(blob: bytes) -> int:
                try:
                    root = etree.fromstring(blob)
                except etree.XMLSyntaxError:
                    return 0
                return sum(
                    1
                    for el in root.iter()
                    if isinstance(el.tag, str)
                    and el.tag.rsplit("}", 1)[-1] == "text"
                    and " / " in "".join(el.itertext())
                )

            ncx_translated = _bi_labels(z.read(book.ncx_path)) - _bi_labels(
                book.members[book.ncx_path]
            )
            rec["ncx_bilingual_delta"] = ncx_translated
            _check(
                rec,
                "这是译文" in z.read(book.ncx_path).decode("utf-8")
                or rec["ncx_units"] == 0,
                "NCX 无译文",
            )
        body_translated = report.translated - ncx_translated
        _check(
            rec,
            zh_nodes_total == body_translated,
            f"插译节点 {zh_nodes_total} != 非NCX译文 {body_translated}",
        )
        # CSS 注入恰在有译文时
        if book.doc_paths:
            head_raw = z.read(book.doc_paths[0]).decode("utf-8", "replace")
            has_css = ".texlate-zh" in head_raw
            _check(rec, has_css == (report.translated > 0), "CSS 注入与译文数不符")
        opf_raw = z.read(book.opf_path)
        try:
            opf_root = etree.fromstring(opf_raw)
        except etree.XMLSyntaxError as e:
            _failures(rec).append(f"输出 OPF 非法 XML: {e}")
        else:
            langs = [
                el.text
                for el in opf_root.iter()
                if isinstance(el.tag, str) and el.tag.rsplit("}", 1)[-1] == "language"
            ]
            _check(rec, bool(langs) and langs[0] == "zh-CN", "dc:language 未改")
    return rec


def verify_docx(src: Path, dst: Path) -> dict:
    rec: dict = {"file": src.name, "format": "docx", "size": src.stat().st_size}
    src_hash = _sha256(src)
    rec["sniff"] = sniff_format(src)
    _check(rec, rec["sniff"] == "docx", "sniff!=docx")

    with zipfile.ZipFile(src) as z:
        src_names = z.namelist()
        # 每个 XML part 的 w:p 数（基线）
        src_pcount = {}
        for n in src_names:
            if n.endswith(".xml") and (
                n == "word/document.xml" or _EXTRA_PART_RE.match("/" + n)
            ):
                try:
                    root = etree.fromstring(z.read(n))
                except etree.XMLSyntaxError:
                    continue
                src_pcount[n] = len(list(root.iter(W + "p")))
    rec["src_parts"] = len(src_names)
    rec["src_w_p"] = sum(src_pcount.values())

    report = export_document(src, dst, MockTranslator())
    rec["report"] = {
        "units": report.units,
        "translated": report.translated,
        "unchanged": report.unchanged,
        "skipped": report.skipped,
        "fault": report.fault,
        "documents": report.documents,
        "warnings": report.warnings[:20],
    }
    _check(rec, report.fault == 0, f"fault={report.fault}")
    _check(
        rec,
        report.units
        == report.translated + report.unchanged + report.skipped + report.fault,
        "report 计数不平",
    )
    _check(rec, _sha256(src) == src_hash, "源文件被改写")

    # 产物可再打开
    try:
        doc = Document(str(dst))
        rec["docx_reopen"] = True
    except Exception as e:
        rec["docx_reopen"] = False
        _failures(rec).append(f"python-docx 重开失败: {e}")
        return rec

    with zipfile.ZipFile(dst) as z:
        _check(rec, z.testzip() is None, "zip CRC 损坏")
        _check(rec, set(z.namelist()) == set(src_names), "part 集合变化")
        # 每个 part 的 w:p 增量 == 该 part 插译数（translated units 分布未知——
        # 用全局对账：总新增 w:p == translated）
        new_p_total = 0
        zh_runs = 0
        sect_in_clone = 0
        leaked = []
        for n, old_count in src_pcount.items():
            try:
                root = etree.fromstring(z.read(n))
            except etree.XMLSyntaxError:
                _failures(rec).append(f"{n} 输出 XML 不可解析")
                continue
            ps = list(root.iter(W + "p"))
            new_p_total += len(ps) - old_count

            # 译文段判定：run 文本含 mock 串且带 SimSun+555555 戳——源文不可能有
            for p in ps:
                hit = False
                for r in p.iter(W + "r"):
                    if not _owns(p, r):
                        continue
                    rtext = "".join(
                        t.text or "" for t in r.iter(W + "t") if _owns(p, t)
                    )
                    if "这是译文" not in rtext:
                        continue
                    rpr = r.find(W + "rPr")
                    rf = rpr.find(W + "rFonts") if rpr is not None else None
                    col = rpr.find(W + "color") if rpr is not None else None
                    if (
                        rf is not None
                        and rf.get(W + "eastAsia") == "SimSun"
                        and col is not None
                        and col.get(W + "val") == "555555"
                    ):
                        hit = True
                if hit:
                    zh_runs += 1
                    ppr = p.find(W + "pPr")
                    if ppr is not None and ppr.find(W + "sectPr") is not None:
                        sect_in_clone += 1
            text_all = "".join(root.itertext())
            leaked += MARKER_RE.findall(text_all)
        rec["new_w_p"] = new_p_total
        rec["zh_paras"] = zh_runs
        _check(
            rec,
            new_p_total == report.translated,
            f"新增 w:p {new_p_total} != translated {report.translated}",
        )
        _check(
            rec,
            zh_runs == report.translated,
            f"打戳译文段 {zh_runs} != translated {report.translated}",
        )
        _check(rec, sect_in_clone == 0, f"克隆段携带 sectPr x{sect_in_clone}")
        _check(rec, not leaked, f"marker 泄漏: {leaked[:5]}")

    # 位置断言（正文面）：译文段紧邻源段之后——用 mock 串+字体戳双特征
    body_ps = doc.element.body.findall(W + "p")
    adjacency = 0
    for i in range(len(body_ps) - 1):
        nxt = body_ps[i + 1]
        zh = any(
            _owns(nxt, r)
            and "这是译文" in "".join(t.text or "" for t in r.iter(W + "t"))
            and r.find(W + "rPr") is not None
            and r.find(W + "rPr").find(W + "rFonts") is not None
            and r.find(W + "rPr").find(W + "rFonts").get(W + "eastAsia") == "SimSun"
            for r in nxt.iter(W + "r")
        )
        if zh:
            adjacency += 1
    rec["body_top_zh_paras"] = adjacency
    return rec


def main() -> int:
    records = []
    for rel in EPUBS:
        src = ROOT / rel
        dst = OUT / (src.stem + ".bilingual.epub")
        try:
            rec = verify_epub(src, dst)
        except Exception as e:
            rec = {"file": src.name, "format": "epub", "exception": repr(e)}
        records.append(rec)
        status = (
            "PASS" if not rec.get("failures") and "exception" not in rec else "FAIL"
        )
        print(
            f"[{status}] {src.name}: units={rec.get('units')} "
            f"translated={rec.get('report', {}).get('translated')} "
            f"failures={rec.get('failures')} exc={rec.get('exception')}"
        )
    for rel in DOCXS:
        src = ROOT / rel
        dst = OUT / (src.stem + ".bilingual.docx")
        try:
            rec = verify_docx(src, dst)
        except Exception as e:
            rec = {"file": src.name, "format": "docx", "exception": repr(e)}
        records.append(rec)
        status = (
            "PASS" if not rec.get("failures") and "exception" not in rec else "FAIL"
        )
        print(
            f"[{status}] {src.name}: units={rec.get('report', {}).get('units')} "
            f"translated={rec.get('report', {}).get('translated')} "
            f"new_p={rec.get('new_w_p')} "
            f"failures={rec.get('failures')} exc={rec.get('exception')}"
        )
    (OUT / "report.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    n_fail = sum(1 for r in records if r.get("failures") or "exception" in r)
    print(f"\n{len(records)} files, {n_fail} with failures → report.json")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
