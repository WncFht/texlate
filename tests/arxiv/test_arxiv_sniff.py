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

CORPUS = Path(__file__).resolve().parents[2] / "bench" / "corpus"

# 数据层 gitignored：干净 clone 目录仍在（MANIFEST 等入库），守卫须判数据文件而非目录。
# v1 陷阱包成员判据须落到具体文件——v3 统一根后 extracted/ 树里全是 .tex，
# 粗粒度 rglob 会把「v1 包缺席」误判在场。
_HAS_V1 = (CORPUS / "1412.6980" / "arxiv.tex").is_file()
_HAS_V2 = any(CORPUS.rglob("meta.json"))


def _raw_blobs() -> list[Path]:
    """盘上 ``*/raw.*`` 全量枚举——v3 统一根重建后 manifest_v2.jsonl 的
    old-style id 与在盘成员已不同集，枚举以实盘为准。"""
    return sorted(CORPUS.glob("*/raw.*"))


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_V2, reason="corpus 数据不在场（gitignored）")
def test_sniff_corpus_all() -> None:
    """corpus 全量真实包：魔数判别与构建期 meta.json 的 format 字段全部一致。"""
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
    # v3 语料分布：tar 主导、pdf_only 行保留（不再构建期滤除）、single_gz 少量、
    # unknown 恒零（全部 blob 须可判别——漏网即 meta 不一致或真未知）
    assert kind_counts[BlobKind.TAR] > kind_counts[BlobKind.SINGLE]
    assert kind_counts[BlobKind.SINGLE] > 0
    assert kind_counts[BlobKind.PDF] > 0
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


@pytest.mark.skipif(not _HAS_V1, reason="corpus 数据不在场（gitignored）")
def test_pdf_wrapper_detect() -> None:
    src = (CORPUS / "1412.6980" / "arxiv.tex").read_text(encoding="utf-8")
    v = check_pdf_wrapper(src)
    assert v.is_wrapper
    assert v.has_includepdf
    assert v.n_sections == 0


#: 真文档反例锚点：meta.locate.pdf_wrapper=False 的 latex 主文件
#: （v3 重建后原锚 2210.15358 已不在语料内）。
_WRAPPER_NEG = (
    CORPUS / "2509.18111" / "extracted" / "iclr2026" / "iclr2026_conference.tex"
)


@pytest.mark.skipif(
    not _WRAPPER_NEG.is_file(), reason="corpus 成员不在场（gitignored）"
)
def test_pdf_wrapper_negative() -> None:
    src = _WRAPPER_NEG.read_bytes().decode("utf-8", "replace")
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


def test_pdf_wrapper_section_optional_arg_counts() -> None:
    r"""``\section[short]{long}`` 可选参形态计入 n_sections——漏判曾把
    ``\includepdf`` + 可选参 section 的真文档判成 is_stub → wrapper 假阳。"""
    src = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includepdf{paper.pdf}\n"
        "\\section[Short]{Long}\n\\subsection*[s]{l}\n\\paragraph{p}\n"
        "\\end{document}\n"
    )
    v = check_pdf_wrapper(src)
    assert v.n_sections == 3  # noqa: PLR2004 -- 钉命中数
    assert v.has_includepdf
    assert not v.is_stub
    assert not v.is_wrapper
