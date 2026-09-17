r"""dim-参残留族回归（fixer-argtab 波次，illegal_unit 表侧半场）。

stagerun/realn200 实证形：``\titlespacing*{\section}{0pt}{4pt}{4pt}``
的 ``{0pt}``/``{4pt}`` 落 chunk 译成 ``{0这是译文}``；``\multirow`` 文
本参内 ``\rotatebox[origin=c]{90}{2D}`` 的 ``[origin=c]`` 被译
（``[这是译文]``，2310.16788）。修复走 ``TRANSPARENT_HEAD_SPEC``——
主流/in_arg/组内三路径都按 spec 消费头参进 ``[[CMD]]``，尾 ``{text}``
组留主流可译。

每条断言过 ``check_invariants`` 三件套 + 面级断言（dim/参名不进
chunk、文本参仍进 chunk）。
"""

import pytest
from conftest import ART, check_invariants, chunk_text

from texlate.latex import parse_tex


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


# ------------------------------------------------------------- titlesec 族


def test_titlespacing_star_dims_protected() -> None:
    r"""``\titlespacing*{\section}{0pt}{4pt}{4pt}``：dim 组不进 chunk。"""
    tex = ART % (
        "\\usepackage{titlesec}\n",
        (
            "\\titlespacing*{\\section}{0pt}{4pt}{4pt}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "0pt" not in body
    assert "4pt" not in body
    assert "titlespacing" not in body
    assert "Body text" in body


def test_titlespacing_trailing_opt_protected() -> None:
    r"""``\titlespacing*{..}{..}{..}{..}[2em]``：尾 ``[right]`` 可选参同收。"""
    tex = ART % (
        "",
        (
            "\\titlespacing*{\\section}{0pt}{4pt}{4pt}[2em]\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "2em" not in body
    assert "0pt" not in body


def test_titlespacing_nostar_variant() -> None:
    r"""``\titlespacing{\paragraph}{0pt}{1ex}{1em}``：无星形同收。

    裸 cs 形 ``\titlespacing\paragraph{..}`` 是已知 bare-cs 参洞（``m``
    不跨 ``\``，与 ``\setlength\parskip{4pt}`` 同源）——留 segmenter
    机制波次，本表盖花括号形。
    """
    tex = ART % (
        "",
        (
            "\\titlespacing{\\paragraph}{0pt}{1ex}{1em}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "1ex" not in body
    assert "1em" not in body
    assert "0pt" not in body


def test_titleformat_full_signature() -> None:
    r"""``\titleformat{\section}[hang]{\bfseries}{\thesection}{1em}{}`` 全收。"""
    tex = ART % (
        "\\usepackage{titlesec}\n",
        (
            "\\titleformat{\\section}[hang]{\\bfseries}{\\thesection}{1em}{}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "1em" not in body
    assert "hang" not in body
    assert "thesection" not in body
    assert "bfseries" not in body


def test_titleformat_star_compact() -> None:
    r"""``\titleformat*{\section}{\LARGE\bfseries}`` 紧凑形同收。"""
    tex = ART % (
        "",
        (
            "\\titleformat*{\\section}{\\LARGE\\bfseries}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "LARGE" not in body
    assert "bfseries" not in body


def test_titleformat_with_after_code_opt() -> None:
    r"""``\titleformat{cmd}[shape]{fmt}{label}{sep}{before}[after]`` 满参形。"""
    tex = ART % (
        "",
        (
            "\\titleformat{\\section}[display]{\\normalfont\\Large}"
            "{\\thesection}{1em}{\\centering}[\\vspace{2pt}]\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "1em" not in body
    assert "2pt" not in body
    assert "display" not in body
    assert "centering" not in body


def test_titlelabel_and_titleclass() -> None:
    r"""``\titlelabel{..}``/``\titleclass{..}{top}``/``[..]{..}`` 全收。"""
    tex = ART % (
        "",
        (
            "\\titlelabel{\\thetitle.\\quad}\n"
            "\\titleclass{\\chapter}{top}\n"
            "\\titleclass{\\part}[page]{straight}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "thetitle" not in body
    assert "quad" not in body
    assert "top" not in body
    assert "straight" not in body
    assert "page" not in body


def test_titlecontents_signature() -> None:
    r"""``\titlecontents{sec}[left]{above}{num}{nonum}{filler}[below]`` 全收。"""
    tex = ART % (
        "",
        (
            "\\titlecontents{section}[3.8em]{\\vspace{1em}}"
            "{\\contentslabel{2.3em}}{\\hspace*{-2.3em}}{\\titlerule*[8pt]{.}}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "3.8em" not in body
    assert "2.3em" not in body
    assert "8pt" not in body
    assert "contentslabel" not in body


# ------------------------------------------------------------- graphicx/内核盒族


def test_resizebox_dims_protected_text_live() -> None:
    r"""``\resizebox{12cm}{17.0cm}{text}``：dim 收 ``[[CMD]]``、text 可译。"""
    tex = ART % (
        "\\usepackage{graphicx}\n",
        (
            "Before words here. \\resizebox{12cm}{17.0cm}"
            "{Inner text to translate} after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "12cm" not in body
    assert "17.0cm" not in body
    assert "Inner text to translate" in body


def test_resizebox_star_variant() -> None:
    r"""``\resizebox*{w}{h}{text}`` 星形同收。"""
    tex = ART % (
        "",
        (
            "Before words here. \\resizebox*{4cm}{2cm}"
            "{Starred inner text} after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "4cm" not in body
    assert "2cm" not in body
    assert "Starred inner text" in body


def test_rotatebox_opt_origin_protected() -> None:
    r"""``\rotatebox[lt]{90}{text}``：``[lt]`` 可选原点参不进 chunk。"""
    tex = ART % (
        "",
        (
            "Before words here. \\rotatebox[lt]{90}"
            "{Rotated text} after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "lt" not in body.split()
    assert "90" not in body
    assert "Rotated text" in body


def test_rotatebox_inside_multirow_arg() -> None:
    r"""2310.16788 实证形：``\multirow`` 文本参内 ``[origin=c]`` 不被译。"""
    tex = ART % (
        "\\usepackage{graphicx,multirow,booktabs}\n",
        (
            "\\begin{table}\n\\centering\n"
            "\\begin{tabular}{lcc}\n\\toprule\n"
            "\\multirow{5}{*}{\\rotatebox[origin=c]{90}{2D}} & cell text & more \\\\\n"
            "\\bottomrule\n\\end{tabular}\n\\end{table}\n"
            "After text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "origin" not in body
    assert "origin=c" not in body
    # {90} 与 {2D} 分别走保护/可译两侧
    assert "90" not in body


def test_scalebox_hv_args() -> None:
    r"""``\scalebox{2}[1.5]{text}``：缩放比收，text 可译。"""
    tex = ART % (
        "",
        (
            "Before words here. \\scalebox{2}[1.5]"
            "{Scaled text} after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "Scaled text" in body
    assert "1.5" not in body


def test_makebox_opt_args_protected_text_live() -> None:
    r"""``\makebox[2cm][l]{text}``：``[2cm][l]`` 收、``{text}`` 可译。"""
    tex = ART % (
        "",
        (
            "Before words here. \\makebox[2cm][l]"
            "{Boxed text} after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "2cm" not in body
    assert "Boxed text" in body


def test_makebox_no_opt_still_transparent() -> None:
    r"""正常面：``\makebox{text}`` 无可选参时行为不变（text 可译）。"""
    tex = ART % (
        "",
        (
            "Before words here. \\makebox{Plain boxed text} "
            "after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "Plain boxed text" in chunk_text(res)


def test_framebox_opt_args() -> None:
    r"""``\framebox[3cm][r]{text}`` 同 ``\makebox`` 形。"""
    tex = ART % (
        "",
        (
            "Before words here. \\framebox[3cm][r]"
            "{Framed text} after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "3cm" not in body
    assert "Framed text" in body


def test_parbox_full_signature() -> None:
    r"""``\parbox[t][3cm][c]{5cm}{text}``：位/dim/宽收，text 可译。"""
    tex = ART % (
        "",
        (
            "Before words here. \\parbox[t][3cm][c]{5cm}"
            "{Parboxed inner text} after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "3cm" not in body
    assert "5cm" not in body
    assert "Parboxed inner text" in body


def test_parbox_short_form() -> None:
    r"""``\parbox{5cm}{text}`` 短形：width 收、text 可译。"""
    tex = ART % (
        "",
        (
            "Before words here. \\parbox{5cm}"
            "{Short parbox text} after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "5cm" not in body
    assert "Short parbox text" in body


def test_raisebox_signature() -> None:
    r"""``\raisebox{2pt}[1em][0pt]{text}``：lift/extent 收、text 可译。"""
    tex = ART % (
        "",
        (
            "Before words here. \\raisebox{2pt}[1em][0pt]"
            "{Raised text} after words to fill out the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "2pt" not in body
    assert "1em" not in body
    assert "0pt" not in body
    assert "Raised text" in body


def test_sbox_savebox_usebox() -> None:
    r"""``\sbox{cmd}{text}``/``\savebox{cmd}[w]{text}``/``\usebox{cmd}``。"""
    tex = ART % (
        "",
        (
            "\\sbox{\\mybox}{Saved inner text} "
            "\\savebox{\\otherbox}[4cm][l]{Other saved text} "
            "then \\usebox{\\mybox} inline words to fill the paragraph out.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "mybox" not in body
    assert "otherbox" not in body
    assert "4cm" not in body
    assert "Saved inner text" in body
    assert "Other saved text" in body


# ------------------------------------------------------------- 正常面/回归闸


def test_genfrac_outside_math_still_protected() -> None:
    r"""``\genfrac`` 散文中走未知命令探针——braced 参整组 ``[[CMD]]``。"""
    tex = ART % (
        "\\usepackage{amsmath}\n",
        (
            "Some words here. $\\genfrac{[}{]}{2pt}{0}{a}{b}$ math tail "
            "and more words to fill the paragraph out nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "genfrac" not in body
    assert "2pt" not in body


def test_shared_name_no_overconsume() -> None:
    r"""回归闸：``\makebox`` 后随散文 ``(..)`` 不被 picture-mode 误吃。"""
    tex = ART % (
        "",
        (
            "The \\makebox command (see above for details) appears here "
            "with more words to fill the paragraph out nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "see above for details" in chunk_text(res)


def test_textcolor_unchanged() -> None:
    r"""回归闸：``\textcolor{red}{text}`` 原行为不变。"""
    tex = ART % (
        "",
        (
            "Before \\textcolor{red}{colored words here} after words "
            "to fill the paragraph out nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "colored words here" in body
    assert "{red}" not in body


# ------------------------------------------------------------- thmtools restatable


def test_restatable_args_protected() -> None:
    r"""``\begin{restatable}{theorem}{main}``：``{env}``/``{cs}`` 结构参不进 chunk。"""
    tex = ART % (
        "\\usepackage{thmtools}\n",
        (
            "Intro words here to fill the paragraph out nicely and more.\n"
            "\\begin{restatable}{theorem}{main}\n"
            "\\label{thm:main} Body words of the theorem go here nicely.\n"
            "\\end{restatable}\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "{theorem}" not in body
    assert "{main}" not in body
    assert "restatable" not in body
    assert "Body words of the theorem" in body
    assert "Intro words" in body


def test_restatable_note_form_args_protected() -> None:
    r"""``\begin{restatable}[Main Theorem]{thm}{composing}``：note+两参全收进字面段。"""
    tex = ART % (
        "\\usepackage{thmtools}\n",
        (
            "\\begin{restatable}[Main Theorem]{thm}{composing}\n"
            "\\label{thm:composing} Body words of the theorem go here.\n"
            "\\end{restatable}\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "Main Theorem" not in body
    assert "{thm}" not in body
    assert "{composing}" not in body
    assert "Body words of the theorem" in body


def test_restatable_star_args_protected() -> None:
    r"""``\begin{restatable*}{lemma}{\mylem}``：star 形独立登记同收。"""
    tex = ART % (
        "\\usepackage{thmtools}\n",
        (
            "\\begin{restatable*}{lemma}{\\mylem}\n"
            "\\label{lem:x} Star body words of the lemma go here.\n"
            "\\end{restatable*}\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "{lemma}" not in body
    assert "{\\mylem}" not in body
    assert "Star body words" in body


def test_restatable_bare_text_body_bounded_lose() -> None:
    r"""体裸文起头：第三 ``m`` 单 token 过吃有界——``{cs}`` 参仍收、恒等不破。"""
    tex = ART % (
        "\\usepackage{thmtools}\n",
        (
            "\\begin{restatable}{theorem}{main}\n"
            "First word drops, rest of the body words stay chunked here.\n"
            "\\end{restatable}\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "{main}" not in body
    assert "rest of the body words" in body


def test_restatable_no_thmtools_dormant() -> None:
    r"""无 ``\usepackage{thmtools}`` 条目不激活——``{main}`` 仍裸进 chunk（门控语义）。"""
    tex = ART % (
        "",
        (
            "\\begin{restatable}{theorem}{main}\n"
            "\\label{thm:main} Body words of the theorem go here.\n"
            "\\end{restatable}\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "{main}" in chunk_text(res)


# ------------------------------------------------------------- epic/eepic 保护环境


def test_eepic_coords_protected() -> None:
    r"""``\begin{eepic}`` 体 ``(0.75);(1.5)`` 坐标串不进 chunk（PROTECTED_ENVS）。"""
    tex = ART % (
        "\\usepackage{epic,eepic}\n",
        (
            "Before words to fill the paragraph out nicely and more text.\n"
            "\\begin{eepic}(8,6)\n"
            "\\drawline(0.75,0.5)(1.5,1.5);(3,0.5)\n"
            "\\put(4,2){dot}\n"
            "\\end{eepic}\n"
            "After words to fill the paragraph out nicely and more text.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "0.75" not in body
    assert "1.5" not in body
    assert "drawline" not in body
    assert "Before words" in body
    assert "After words" in body


def test_epic_coords_protected() -> None:
    r"""``\\begin{epic}`` 同族同收——坐标与 ``\\path`` 命令名不进 chunk。"""
    tex = ART % (
        "\\usepackage{epic}\n",
        ("\\begin{epic}(6,4)\n\\path(0.75,0.5)(1.5,1.5)\n\\end{epic}\n"),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "0.75" not in body
    assert "path" not in body
