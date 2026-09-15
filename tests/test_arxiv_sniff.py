import gzip
import json
from pathlib import Path

import pytest

from texlate.arxiv.sniff import (
    BlobKind,
    SniffError,
    check_pdf_wrapper,
    sniff,
)

CORPUS_V2 = Path(__file__).resolve().parent.parent / "bench" / "corpus_v2"
CORPUS_V1 = Path(__file__).resolve().parent.parent / "bench" / "corpus"


def _raw_blobs() -> list[Path]:
    return sorted(CORPUS_V2.rglob("raw.*"))


@pytest.mark.skipif(not CORPUS_V2.exists(), reason="corpus_v2 not present")
def test_sniff_corpus_all() -> None:
    """139 个真实包：魔数判别与构建期 meta.json 的 format 字段全部一致。"""
    blobs = _raw_blobs()
    assert blobs
    kind_counts = {
        BlobKind.TAR: 0,
        BlobKind.SINGLE: 0,
        BlobKind.PDF: 0,
        BlobKind.UNKNOWN: 0,
    }
    mismatches: list[str] = []
    for blob in blobs:
        s = sniff(blob.read_bytes())
        kind_counts[s.kind] += 1
        meta_p = blob.parent / "meta.json"
        if not meta_p.exists():
            continue
        expected = json.loads(meta_p.read_text()).get("format")
        if expected and expected != s.kind.value:
            mismatches.append(f"{blob.parent.name}: meta={expected} got={s.kind}")
    assert not mismatches, "; ".join(mismatches)
    # 语料分布：tar 主导、单文件 .gz 次之、pdf/unknown 为零（构建期已滤掉 pdf_only）
    assert kind_counts[BlobKind.TAR] > kind_counts[BlobKind.SINGLE]
    assert kind_counts[BlobKind.PDF] == 0
    assert kind_counts[BlobKind.UNKNOWN] == 0


def test_sniff_pdf_magic() -> None:
    s = sniff(b"%PDF-1.5 fake pdf body")
    assert s.kind is BlobKind.PDF
    assert s.payload is None


def test_sniff_unknown() -> None:
    s = sniff(b"\x00\x01\x02\x03 random legacy blob")
    assert s.kind is BlobKind.UNKNOWN


def test_sniff_corrupt_gzip() -> None:
    with pytest.raises(SniffError):
        sniff(b"\x1f\x8b" + b"\x00" * 20 + b"truncated garbage")


def test_sniff_single_vs_tar() -> None:
    tex = b"\\documentclass{article}\n\\begin{document}hi\\end{document}\n"
    s = sniff(gzip.compress(tex))
    assert s.kind is BlobKind.SINGLE
    assert s.payload == tex


def test_pdf_wrapper_detect() -> None:
    src = (CORPUS_V1 / "1412.6980" / "arxiv.tex").read_text(encoding="utf-8")
    v = check_pdf_wrapper(src)
    assert v.is_wrapper
    assert v.has_includepdf
    assert v.n_sections == 0


def test_pdf_wrapper_negative() -> None:
    src = (
        (CORPUS_V2 / "2210.15358" / "extracted" / "acl_latex.tex")
        .read_bytes()
        .decode("utf-8", "replace")
    )
    v = check_pdf_wrapper(src)
    assert not v.is_wrapper
    assert not v.is_stub


def test_pdf_wrapper_commented_includepdf() -> None:
    src = (
        "\\documentclass{article}\n\\begin{document}\n"
        "% \\includepdf{fake.pdf}\n"
        "\\section{Real}\n" + "body " * 600 + "\n\\end{document}\n"
    )
    v = check_pdf_wrapper(src)
    assert not v.is_wrapper
    assert not v.has_includepdf
