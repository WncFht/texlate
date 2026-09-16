"""真书 EPUB 双语插译回归（export-formats 补验，2026-09-16）。

用法: uv run python bench/py/export_realbook.py <epub...> [--outdir DIR]

对手工下载的公版 EPUB 跑 translate_epub(MockTranslator) 全链并断言:
- 出包 zipfile 可开、mimetype 首条且 ZIP_STORED（OCF 硬约束）
- 每个 xhtml 文档 bs4 可解析、有 texlate-zh 插译节点、无重复 id（RSC-005）
- NCX navLabel 呈 "原文 / 译文" 双串；nav <li> 结构不塌（li 内无克隆 li）
- ExportReport 计数与实插节点数一致
可选: 环境里有 ebooklib 时额外做 reader 级打开检查（AGPL 库，仅验证工具）。

产物写 bench/results/export-realbook-2026-09-16/（report.json + README.md）。
"""

from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from texlate.export.epub import iter_units, load_epub, translate_epub
from texlate.export.rights import check_epub
from texlate.xlat.pipeline import MockTranslator

OUTDIR = Path("bench/results/export-realbook-2026-09-16")


def _check_one(src: Path, dst: Path) -> dict:
    rec: dict = {"src": str(src), "dst": str(dst), "size": src.stat().st_size}
    rec["drm"] = check_epub(src)
    assert rec["drm"] == "ok", f"{src} DRM"

    book = load_epub(src)
    soups = {p: BeautifulSoup(book.members[p], "html.parser") for p in book.doc_paths}
    units = list(iter_units(book, soups))
    rec["members"] = len(book.members)
    rec["doc_paths"] = len(book.doc_paths)
    rec["units"] = len(units)
    rec["ncx_units"] = sum(1 for u in units if u.ncx_text is not None)
    rec["marker_units"] = sum(1 for u in units if u.markers)
    rec["multi_run_units"] = sum(1 for u in units if u.is_multi_run)

    report = translate_epub(src, dst, MockTranslator())
    rec["report"] = {
        "units": report.units,
        "translated": report.translated,
        "unchanged": report.unchanged,
        "skipped": report.skipped,
        "fault": report.fault,
        "documents": report.documents,
        "warnings": report.warnings[:10],
    }
    assert report.fault == 0, f"fault units: {report.fault}"

    with zipfile.ZipFile(dst) as z:
        infos = z.infolist()
        assert infos[0].filename == "mimetype", "mimetype 非首条"
        assert infos[0].compress_type == zipfile.ZIP_STORED, "mimetype 非 STORED"
        names = z.namelist()
        assert len(names) == len(book.members), "成员数变化"
        rec["zip_ok"] = True
        zh_nodes_total = 0
        dup_ids: list[str] = []
        for path in book.doc_paths:
            soup = BeautifulSoup(z.read(path), "html.parser")
            zh = soup.select(".texlate-zh")
            zh_nodes_total += len(zh)
            ids = Counter(el["id"] for el in soup.find_all(attrs={"id": True}))
            dup_ids += [f"{path}#{i}" for i, c in ids.items() if c > 1]
            # nav <li> 走内部 append：li 数量不该因插译翻倍
            for li in soup.select("nav li"):
                assert not li.find_parent("li"), f"{path}: nav li 嵌套塌了"
        assert not dup_ids, f"重复 id: {dup_ids[:10]}"
        rec["zh_nodes"] = zh_nodes_total
        rec["dup_ids"] = 0
        body_units = report.units - rec["ncx_units"]
        assert zh_nodes_total == body_units, (
            f"插译节点 {zh_nodes_total} != 非 NCX units {body_units}"
        )
        if book.ncx_path and book.ncx_path in names:
            ncx = z.read(book.ncx_path).decode("utf-8")
            rec["ncx_bilingual_labels"] = ncx.count(" / ")
            assert "这是译文" in ncx, "NCX 无译文"

    # 可选 reader 级检查：ebooklib 在就用（验证工具，非依赖）
    try:
        from ebooklib import epub as el_epub

        bk = el_epub.read_epub(str(dst))
        rec["ebooklib_items"] = len(list(bk.get_items()))
        rec["ebooklib_ok"] = True
    except ImportError:
        rec["ebooklib_ok"] = None
    return rec


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    outdir = OUTDIR
    if "--outdir" in sys.argv:
        outdir = Path(sys.argv[sys.argv.index("--outdir") + 1])
    outdir.mkdir(parents=True, exist_ok=True)
    records = []
    for a in args:
        src = Path(a)
        dst = src.with_name(src.stem + ".bilingual.epub")
        rec = _check_one(src, dst)
        records.append(rec)
        print(
            f"{src.name}: units={rec['units']} zh_nodes={rec['zh_nodes']} "
            f"ncx={rec['ncx_units']} markers={rec['marker_units']} "
            f"multi_run={rec['multi_run_units']} ebooklib={rec['ebooklib_ok']}"
        )
    (outdir / "report.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"report → {outdir}/report.json")


if __name__ == "__main__":
    main()
