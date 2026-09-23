import json
from pathlib import Path

import pytest

from texlate.arxiv.locate import DocKind, locate

CORPUS = Path(__file__).resolve().parent.parent / "bench" / "corpus"

# 数据层 gitignored：干净 clone 目录仍在（MANIFEST 等入库），守卫须判数据文件而非目录。
# v1/v2 已合一根但布局不同——v1 包扁平（<id>/*.tex 直接在包目录），v2 包是
# <id>/{meta.json,extracted/}。_HAS_V1 探扁平包标记（v2-only 树下 skip 而非 fail），
# _HAS_V2 探 meta.json 层。
_HAS_V1 = (CORPUS / "1502.01589" / "planck_parameters_2015.tex").is_file()
_HAS_V2 = any(CORPUS.rglob("meta.json"))

MAIN_TEX = (
    "\\documentclass{article}\n\\begin{document}\n\\input{sec1}\n"
    "text body here\\end{document}\n"
)


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_V2, reason="corpus 数据不在场（gitignored）")
def test_locate_corpus_v2_all() -> None:
    """corpus 全量定位：全部 kind=latex 且有 main，order 首元素即 main。

    枚举面以盘上 ``*/meta.json`` 为准（v3 统一根重建后 manifest_v2.jsonl
    的 old-style id 与在盘成员已不再同集）；``format=="pdf"`` 的 pdf_only
    行无 tex 源不属本测试面；plain_tex/none 是语料真实成员（Knuth
    plain-TeX、索引包等）——locate 的正确分类，不算定位失败。
    """
    metas = sorted(CORPUS.glob("*/meta.json"))
    assert metas
    failures: list[str] = []
    multi = 0
    for meta_p in metas:
        meta = json.loads(meta_p.read_text())
        if meta.get("format") == "pdf":
            continue
        ext = meta_p.parent / "extracted"
        if not ext.is_dir():
            failures.append(f"{meta_p.parent.name}:no_extracted")
            continue
        arxiv_id = meta["arxiv_id"]
        r = locate(ext, arxiv_id=arxiv_id)
        if r.kind is not DocKind.LATEX:
            # plain_tex/none 是语料真实成员——locate 的正确分类非定位失败
            continue
        if r.main is None:
            failures.append(f"{arxiv_id}:{r.kind}:{r.main}")
            continue
        assert r.order[0] == r.main
        if r.multi_doc:
            multi += 1
    assert not failures, "; ".join(failures)
    assert multi >= 1  # 语料中确有 multi_doc（meta.locate 面 ~98 例）


@pytest.mark.skipif(not _HAS_V1, reason="corpus 数据不在场（gitignored）")
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
    r = locate(CORPUS / arxiv_id, arxiv_id=arxiv_id)
    assert r.main == expect_main
    assert r.multi_doc is expect_multi


@pytest.mark.skipif(not _HAS_V1, reason="corpus 数据不在场（gitignored）")
def test_locate_1502_bare_input_and_bbl() -> None:
    r = locate(CORPUS / "1502.01589", arxiv_id="1502.01589")
    # 裸 \input 边要解析出节文件
    assert "abstract.tex" in r.order
    # 24 个 .bib 全缺但 jobname .bbl 在包内
    assert "planck_parameters_2015.bbl" in r.bibliographies


@pytest.mark.skipif(not _HAS_V1, reason="corpus 数据不在场（gitignored）")
def test_locate_wrapper_flag() -> None:
    r = locate(CORPUS / "1412.6980", arxiv_id="1412.6980")
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


def test_nontex_documentclass_not_candidate(tmp_path: Path) -> None:
    r"""非 TEX_EXT 后缀的 ``\documentclass`` 文件不进候选（W69）。

    ``.txt`` 伪主文件在 TEX_EXT 闸外，扫描阶段即不入场。
    """
    _write_tree(
        tmp_path,
        {
            "paper.tex": MAIN_TEX,
            "notes.txt": ("\\documentclass{book}\n\\begin{document}n\\end{document}\n"),
            "sec1.tex": "one\n",
        },
    )
    r = locate(tmp_path)
    assert r.candidates == ["paper.tex"]
    assert r.main == "paper.tex"


def test_nontex_only_documentclass_rootless(tmp_path: Path) -> None:
    r"""唯一 docclass 落在 ``.txt`` 里 → 根缺失告警照出（W69/W71 交界）。"""
    _write_tree(
        tmp_path,
        {
            "frag.tex": "just a fragment\n",
            "readme.txt": "\\documentclass{book}\n",
        },
    )
    r = locate(tmp_path)
    assert r.main is None
    assert r.candidates == []
    assert any(w.startswith("no_documentclass:") for w in r.warnings)


def test_ltx_extension_candidate(tmp_path: Path) -> None:
    """``.ltx`` 同属 TEX_EXT——候选不只看 ``.tex``。"""
    _write_tree(
        tmp_path,
        {
            "ms.ltx": "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n",
        },
    )
    r = locate(tmp_path)
    assert r.candidates == ["ms.ltx"]
    assert r.main == "ms.ltx"


def test_relative_cls_documentclass_candidate(tmp_path: Path) -> None:
    r"""``\documentclass{./dir/cls}`` 相对路径类名照样进候选（W98）。

    探测只看控制序列存在，不解析 cls 参数路径。
    """
    _write_tree(
        tmp_path,
        {
            "ms.tex": (
                "\\documentclass{./cls/journal}\n"
                "\\begin{document}\nbody\\end{document}\n"
            ),
        },
    )
    r = locate(tmp_path)
    assert r.main == "ms.tex"
    assert r.kind is DocKind.LATEX


def test_documentstyle_candidate(tmp_path: Path) -> None:
    r"""``\documentstyle``（latex209 形）同样计候选——DOCCLASS_RX 含此命令。"""
    _write_tree(
        tmp_path,
        {
            "old.tex": (
                "\\documentstyle[12pt]{article}\n\\begin{document}\nx\\end{document}\n"
            ),
        },
    )
    r = locate(tmp_path)
    assert r.main == "old.tex"


def test_multi_doc_independent_roots(tmp_path: Path) -> None:
    """≥2 独立根（各带 docclass+bd、互不引）→ multi_doc 置位（B07）。

    文件名先验把 ``paper.tex`` 推上 main。
    """
    _write_tree(
        tmp_path,
        {
            "paper.tex": (
                "\\documentclass{article}\n\\begin{document}\np\\end{document}\n"
            ),
            "supp.tex": (
                "\\documentclass{article}\n\\begin{document}\ns\\end{document}\n"
            ),
        },
    )
    r = locate(tmp_path)
    assert r.multi_doc
    assert r.independent_roots == ["paper.tex", "supp.tex"]
    assert r.main == "paper.tex"


def test_stub_body_warning(tmp_path: Path) -> None:
    """main 正文近空（无 section、可见文本 <2KB）→ stub_body 告警。"""
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\nhi\\end{document}\n"
            ),
        },
    )
    r = locate(tmp_path)
    assert r.main == "main.tex"
    assert any(w.startswith("stub_body:") for w in r.warnings)
    assert not r.pdf_wrapper


def test_input_space_dir_member(tmp_path: Path) -> None:
    r"""含空格目录成员 ``\input{my dir/sec}`` 正常解析入图（W52）。"""
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\n"
                "\\input{my dir/sec}\nbody\\end{document}\n"
            ),
            "my dir/sec.tex": "sec\n",
        },
    )
    r = locate(tmp_path)
    assert "my dir/sec.tex" in r.order
    assert not r.unresolved


def test_bibliography_trailing_empty_arg(tmp_path: Path) -> None:
    r"""``\bibliography{main}{}`` 尾随空参组被忽略，``main`` 正常解析（W36）。"""
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\nbody\n"
                "\\bibliography{main}{}\n\\end{document}\n"
            ),
            "main.bbl": "\\begin{thebibliography}{1}\\end{thebibliography}\n",
        },
    )
    r = locate(tmp_path)
    assert "main.bbl" in r.bibliographies
    assert not r.unresolved


def test_bibliography_host_path_unresolved(tmp_path: Path) -> None:
    r"""主机路径 ``\bibliography`` 一律拒解析 → unresolved（W16）。

    绝对路径、``~``、盘符、``..`` 逃逸四形态同归 ``_norm_arg`` 拒绝臂。
    """
    _write_tree(
        tmp_path,
        {
            "main.tex": (
                "\\documentclass{article}\n\\begin{document}\nbody\n"
                "\\bibliography{/home/u/refs,~/more,C:\\bibs\\x,../up}\n"
                "\\end{document}\n"
            ),
        },
    )
    r = locate(tmp_path)
    assert not r.bibliographies
    args = {u.arg for u in r.unresolved}
    assert "/home/u/refs" in args
    assert "~/more" in args
    assert "C:\\bibs\\x" in args
    assert "../up" in args
