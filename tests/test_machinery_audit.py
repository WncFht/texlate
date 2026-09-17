r"""segmenter 机制波回归（fixer-machinery，illegal_unit 机制半场）。

覆盖 spec.md M1–M5 + keyarg 残留：

- M1 ``_emit_argspec_chunks`` in_arg 臂 lit 段 → ``[[CMD]]`` 代位
  （``\multirow{2}{*}{\parbox{3cm}{x}}`` 的 ``{3cm}`` 不裸进参内 chunk）；
- M2 新参种 ``n`` = 裸 cs 名参（``\setlength\parskip{4pt}`` 的 ``{4pt}`` 不漏），
  走 ``_BOUNDARY_TAIL_N`` 本地覆盖（``BOUNDARY_TAIL`` 属 tables.py 车道）；
- M3 ``\\[dim]`` 尾参；M4 ``\parindent[=]4pt`` 赋形尾；
- M5 ``_grp_spec_args_end`` ``m`` 臂认 ``[`` 定界组（restatable ``[N]``）；
- 残留：``\joref``/``\crefrange`` 多参书目宏签名驱动 mand——``{b}`` 不漏。

每条断言过 ``check_invariants`` 三件套 + 面级断言（结构参不进 chunk、
文本参仍进 chunk）。
"""

import pytest

from texlate.latex import parse_tex, reconstruct
from texlate.latex.model import ScanResult
from texlate.latex.reconstruct import validate_result

ART = "\\documentclass{article}\n%s\\begin{document}\n%s\n\\end{document}\n"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def check_invariants(res: ScanResult, tex: str) -> None:
    """公共断言：恒等重建 + 校验零告警 + pieces 无缝平铺 vtex。"""
    assert reconstruct(res) == tex
    assert validate_result(res) == []
    pos = 0
    for p in res.pieces:
        assert p.span.start == pos
        pos = p.span.end
    assert pos == len(res.vtex)


def chunk_text(res: ScanResult) -> str:
    """全部 chunk surface 拼接——泄漏断言的统一口径。"""
    return " ".join(c.content for c in res.chunks)


# ------------------------------------------------------------- M1 in_arg lit 段


def test_parbox_inside_multirow_arg_no_lit_leak() -> None:
    r"""M1：``\multirow{2}{*}{\parbox{3cm}{text}}``——``{3cm}`` 参内字面段
    不落 chunk（``\parbox`` 非 TRANSPARENT_HEAD 族，走 argspec chunk-arg）。"""
    tex = ART % (
        "\\usepackage{multirow}\n",
        (
            "\\begin{table}\n\\begin{tabular}{lc}\n"
            "\\multirow{2}{*}{\\parbox{3cm}{Boxed inner text}} & cell \\\\\n"
            "\\end{tabular}\n\\end{table}\n"
            "After text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "3cm" not in body
    assert "parbox" not in body
    assert "Boxed inner text" in body


def test_framebox_opt_inside_caption_arg() -> None:
    r"""M1 参内多参形：``\caption{..\framebox[2cm][l]{x}..}`` 的 ``[2cm][l]``
    字面段全成 ``[[CMD]]``——参内 sub-scan 不挖洞但字面段不进 surface。"""
    tex = ART % (
        "",
        (
            "\\caption{Cap \\framebox[2cm][l]{Boxed inner} tail words}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "2cm" not in body
    assert "framebox" not in body
    assert "Cap " in body


# ------------------------------------------------------------- M2 bare-cs 参种 n


def test_setlength_bare_cs_arg() -> None:
    r"""M2 主形：``\setlength\parskip{4pt}``——``\parskip`` 作 ``n`` 参直收、
    ``{4pt}`` 随调用进 LITERAL，双不漏。"""
    tex = ART % (
        "",
        (
            "\\setlength\\parskip{4pt}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "4pt" not in body
    assert "parskip" not in body
    assert "setlength" not in body
    assert "Body text" in body


def test_setlength_braced_form_unchanged() -> None:
    r"""M2 花括号形回归：``\setlength{\parskip}{4pt}`` 照常全收。"""
    tex = ART % (
        "",
        (
            "\\setlength{\\parskip}{4pt}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "4pt" not in body
    assert "parskip" not in body


def test_addtolength_bare_cs_arg() -> None:
    r"""M2 同族：``\addtolength\\parskip{2pt}`` 同收。"""
    tex = ART % (
        "",
        (
            "\\addtolength\\parskip{2pt}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "2pt" not in body
    assert "parskip" not in body


def test_setlength_bare_cs_in_arg() -> None:
    r"""M2 参内形：``\caption{..\setlength\parskip{4pt}..}`` 整调用 ``[[CMD]]``。"""
    tex = ART % (
        "",
        (
            "\\caption{Cap \\setlength\\parskip{4pt} tail words}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "4pt" not in body
    assert "parskip" not in body
    assert "Cap " in body


def test_setcounter_keeps_m_spec() -> None:
    r"""M2 签名核验：``\setcounter`` 首参是计数器名（字母非 cs）——留 ``m m``，
    ``\setcounter{page}{3}`` 照常全收。"""
    tex = ART % (
        "",
        (
            "\\setcounter{page}{3}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "{page}" not in body
    assert "{3}" not in body


# ------------------------------------------------------------- M3 \\[dim] 尾参


def test_bsbs_dim_opt_protected() -> None:
    r"""M3：``a\\[4pt]b`` 的 ``[4pt]`` 随 ``\\`` 进 ``[[CMD]]`` 不译。"""
    tex = ART % (
        "",
        (
            "First line words here \\\\[4pt] second line words to fill "
            "the paragraph out nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "4pt" not in body
    assert "second line words" in body


def test_bsbs_text_opt_conservative() -> None:
    r"""M3 保守面：``a\\[text]b`` 非 dim 形不吸——``[text]`` 照常进 chunk。"""
    tex = ART % (
        "",
        (
            "First line words here \\\\[text] second line words to fill "
            "the paragraph out nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "[text]" in chunk_text(res)


# ------------------------------------------------------------- M4 赋形尾参


def test_parindent_assign_with_eq() -> None:
    r"""M4：``\parindent=4pt`` 等号赋形随命令进 ``[[CMD]]``。"""
    tex = ART % (
        "",
        "\\parindent=4pt\nBody text here to fill the paragraph out nicely.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "4pt" not in body
    assert "parindent" not in body


def test_parindent_assign_no_eq() -> None:
    r"""M4：``\parindent 4pt`` 无等号赋形同收（dimen 尾 ``=?`` 可选）。"""
    tex = ART % (
        "",
        "\\parindent 4pt\nBody text here to fill the paragraph out nicely.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "4pt" not in body
    assert "parindent" not in body


# ------------------------------------------------------------- M5 组内 m 认 [ 组


def test_restatable_note_inside_brace_group() -> None:
    r"""M5：``{..\begin{restatable}[N]{t}{c}..}`` 组内 ``[N]`` 被 ``m`` 收——
    ``]{t}{c}`` 不漏进 surface。"""
    tex = ART % (
        "\\usepackage{thmtools}\n",
        (
            "{Pre \\begin{restatable}[N]{thm}{myc}\n"
            "\\label{t:x} Body words of the theorem go here nicely.\n"
            "\\end{restatable}}\n"
            "After text to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "[N]" not in body
    assert "{thm}" not in body
    assert "{myc}" not in body
    assert "Body words of the theorem" in body


# ------------------------------------------------------------- 残留：多参书目宏


def test_joref_all_args_protected() -> None:
    r"""残留修复：``\joref{a}{j}{v}{p}{y}`` 五参书目宏——签名 ``m×5`` 驱动
    ``mand``，尾参 ``{v}``/``{p}``/``{y}`` 不再漏。"""
    tex = ART % (
        "",
        (
            "See \\joref{AA}{JJ}{VV}{PP}{YY} for details and more words "
            "to fill the paragraph nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    for a in ("AA", "JJ", "VV", "PP", "YY"):
        assert a not in body
    assert "for details" in body


def test_crefrange_tail_arg_protected() -> None:
    r"""残留修复：``\crefrange{eq:a}{eq:b}`` 签名 ``s m m``——``{eq:b}``
    随 ``[[REF]]`` 进保护（此前硬编 mand=1 漏尾参）。"""
    tex = ART % (
        "\\usepackage{cleveref}\n",
        (
            "See \\crefrange{eq:a}{eq:b} for details and more words to "
            "fill the paragraph nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "eq:a" not in body
    assert "eq:b" not in body
    assert "for details" in body


def test_cite_two_groups_unchanged() -> None:
    r"""回归闸：``\cite{a}{b}`` 签名 ``o m`` → mand=1——``{b}`` 仍当正文
    （既有刻意行为不变，``_cite_ref_mand`` 只放宽多参签名族）。"""
    tex = ART % (
        "",
        (
            "See \\cite{keya}{tail} for details and more words to fill "
            "the paragraph nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "keya" not in body
    assert "{tail}" in body
