import json
from pathlib import Path

import pytest

from texlate.arxiv.locate import DocKind, locate

CORPUS_V1 = Path(__file__).resolve().parent.parent / "bench" / "corpus"
CORPUS_V2 = Path(__file__).resolve().parent.parent / "bench" / "corpus_v2"

# 数据层 gitignored：干净 clone 目录仍在（MANIFEST 等入库），守卫须判数据文件而非目录
_HAS_V1 = any(CORPUS_V1.rglob("*.tex"))
_HAS_V2 = any(CORPUS_V2.rglob("meta.json"))

MAIN_TEX = (
    "\\documentclass{article}\n\\begin{document}\n\\input{sec1}\n"
    "text body here\\end{document}\n"
)


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


@pytest.mark.skipif(not _HAS_V2, reason="corpus_v2 数据不在场（gitignored）")
def test_locate_corpus_v2_all() -> None:
    """139 包全量定位：全部 kind=latex 且有 main，order 首元素即 main。"""
    metas = sorted(CORPUS_V2.rglob("meta.json"))
    assert metas
    failures: list[str] = []
    multi = 0
    for meta_p in metas:
        ext = meta_p.parent / "extracted"
        if not ext.is_dir():
            failures.append(f"{meta_p.parent.name}:no_extracted")
            continue
        arxiv_id = json.loads(meta_p.read_text())["arxiv_id"]
        r = locate(ext, arxiv_id=arxiv_id)
        if r.kind is not DocKind.LATEX or r.main is None:
            failures.append(f"{arxiv_id}:{r.kind}:{r.main}")
            continue
        assert r.order[0] == r.main
        if r.multi_doc:
            multi += 1
    assert not failures, "; ".join(failures)
    assert multi >= 1  # 语料中确有 multi_doc（2101.07948 等）


@pytest.mark.skipif(not _HAS_V1, reason="corpus_v1 数据不在场（gitignored）")
@pytest.mark.parametrize(
    ("arxiv_id", "expect_main", "expect_multi"),
    [
        ("1502.01589", "planck_parameters_2015.tex", False),
        ("2201.05989", "paper.tex", True),
        ("2501.14787", "main.tex", True),
        ("2609.08578", "Paper.processed.tex", False),
        ("1412.6980", "arxiv.tex", False),
    ],
)
def test_locate_traps(arxiv_id: str, expect_main: str, *, expect_multi: bool) -> None:
    """v1 陷阱语料：裸 \\input / multi_doc / 五独立根 / processed 主文件 / wrapper。"""
    r = locate(CORPUS_V1 / arxiv_id, arxiv_id=arxiv_id)
    assert r.main == expect_main
    assert r.multi_doc is expect_multi


@pytest.mark.skipif(not _HAS_V1, reason="corpus_v1 数据不在场（gitignored）")
def test_locate_1502_bare_input_and_bbl() -> None:
    r = locate(CORPUS_V1 / "1502.01589", arxiv_id="1502.01589")
    # 裸 \input 边要解析出节文件
    assert "abstract.tex" in r.order
    # 24 个 .bib 全缺但 jobname .bbl 在包内
    assert "planck_parameters_2015.bbl" in r.bibliographies


@pytest.mark.skipif(not _HAS_V1, reason="corpus_v1 数据不在场（gitignored）")
def test_locate_wrapper_flag() -> None:
    r = locate(CORPUS_V1 / "1412.6980", arxiv_id="1412.6980")
    assert r.pdf_wrapper
    assert any(w.startswith("pdf_wrapper:") for w in r.warnings)


def test_input_forms(tmp_path: Path) -> None:
    """八种引用形态各归位；注释里的 \\input 不产生边。"""
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                "\\input{a}\n"
                "\\input b_bare\n"
                "\\include{c}\n"
                "\\InputIfFileExists{d}{}{}\n"
                "\\subfile{e}\n"
                "\\includestandalone{f}\n"
                "\\CatchFileBetweenTags\\tok{g}{tag}\n"
                "\\import{sub/}{h}\n"
                "% \\input{ghost}\n"
                "\\includegraphics{zz}\n"  # 不得误配 \include
                "body body body\\end{document}\n"
            ),
            "a.tex": "sec a\n",
            "b_bare.tex": "sec b\n",
            "c.tex": "sec c\n",
            "d.tex": "sec d\n",
            "e.tex": "sec e\n",
            "f.tex": "sec f\n",
            "g.tex": "sec g\n",
            "sub/h.tex": "sec h\n",
        },
    )
    r = locate(tmp_path, arxiv_id="0000.00000")
    assert r.main == "main.tex"
    order = r.order
    for want in (
        "a.tex",
        "b_bare.tex",
        "c.tex",
        "d.tex",
        "e.tex",
        "f.tex",
        "g.tex",
        "sub/h.tex",
    ):
        assert want in order, want
    assert not any("ghost" in u.arg for u in r.unresolved)
    assert not any("zz" in u.arg for u in r.unresolved)


def test_basis_order_cwd_first(tmp_path: Path) -> None:
    """编译 CWD（main 目录）优先于 including 文件目录。

    TeX 真实语义：``\\input{shared}`` 一律先查编译 CWD（根），查不到才
    退 including 文件所在目录——sub/inc.tex 的引用应中根 ``shared.tex``。
    """
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                "\\input{sub/inc}\nbody\\end{document}\n"
            ),
            "sub/inc.tex": "\\input{shared}\n",
            "shared.tex": "cwd wins\n",
            "sub/shared.tex": "including-dir loses\n",
        },
    )
    r = locate(tmp_path, arxiv_id="0000.00000")
    assert r.main == "main.tex"
    assert "shared.tex" in r.order
    assert "sub/shared.tex" not in r.order
    edge = r.edges.get("sub/inc.tex") or []
    assert edge == ["shared.tex"]


def test_cycle_and_diamond(tmp_path: Path) -> None:
    """真环出告警，菱形重访静默去重。"""
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                "\\input{x}\\input{y}\nbody\\end{document}\n"
            ),
            "x.tex": "\\input{z}\n",
            "y.tex": "\\input{z}\n",  # 菱形：z 被 x、y 双引
            "z.tex": "\\input{x}\n",  # z→x 真环
        },
    )
    r = locate(tmp_path, arxiv_id="0000.00000")
    assert r.order.count("z.tex") == 1
    assert any(w.startswith("cycle:") for w in r.warnings)


def test_plain_tex_and_context(tmp_path: Path) -> None:
    _write_tree(tmp_path, {"p.tex": "\\starttext\nhi\n\\stoptext\n"})
    r = locate(tmp_path)
    assert r.kind is DocKind.CONTEXT
    assert r.main is None

    _write_tree(tmp_path, {"p.tex": "plain\n\\bye\n"})
    r = locate(tmp_path)
    assert r.kind is DocKind.PLAIN_TEX


def test_commented_documentclass_not_candidate(tmp_path: Path) -> None:
    _write_tree(
        tmp_path,
        {
            "main.tex": MAIN_TEX,
            "fake.tex": "% \\documentclass{book}\nstuff\n",
            "sec1.tex": "one\n",
        },
    )
    r = locate(tmp_path)
    assert r.candidates == ["main.tex"]


def test_verbatim_documentclass_not_candidate(tmp_path: Path) -> None:
    r"""verbatim 环境里的 ``\documentclass``/``\begin{document}`` 不执行——
    TeX 示例 listing 不能抢候选位（实测会把 listing.tex 推上 main）。"""
    _write_tree(
        tmp_path,
        {
            "real.tex": (
                "\\documentclass{article}\n\\begin{document}\nreal\\end{document}\n"
            ),
            "listing.tex": (
                "\\begin{verbatim}\n"
                "\\documentclass{book}\n\\begin{document}x\\end{document}\n"
                "\\end{verbatim}\n"
            ),
        },
    )
    r = locate(tmp_path)
    assert r.candidates == ["real.tex"]
    assert r.main == "real.tex"
    assert not r.multi_doc


def test_verbatim_input_and_bibliography_no_edges(tmp_path: Path) -> None:
    r"""``lstlisting`` 内的 ``\input``/``\bibliography`` 不产生边/未解析引用。"""
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                "\\begin{lstlisting}\n\\input{fake}\n\\bibliography{fakebib}\n"
                "\\end{lstlisting}\n"
                "body\\end{document}\n"
            ),
            "fake.tex": "sec\n",
        },
    )
    r = locate(tmp_path)
    assert r.order == ["main.tex"]
    assert not r.unresolved
    assert not r.bibliographies


def test_bibliography_bib_fallback(tmp_path: Path) -> None:
    r"""``\bibliography{x}`` 无 ``x.bbl`` 时回探 ``x.bib``——docstring 承诺的双探。"""
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\nbody\n"
                "\\bibliography{refs}\n\\end{document}\n"
            ),
            "refs.bib": "@article{a, title={t}}\n",
        },
    )
    r = locate(tmp_path)
    assert "refs.bib" in r.bibliographies
    assert not any(u.arg == "refs" for u in r.unresolved)


def test_inline_verb_input_no_edge(tmp_path: Path) -> None:
    r"""行内 ``\verb``/``\lstinline`` 段的 ``\input`` 同样不产生边。"""
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                "see \\verb|\\input{fake}| for usage\n"
                "body\\end{document}\n"
            ),
            "fake.tex": "sec\n",
        },
    )
    r = locate(tmp_path)
    assert r.order == ["main.tex"]
    assert "fake.tex" not in r.edges.get("main.tex", [])
