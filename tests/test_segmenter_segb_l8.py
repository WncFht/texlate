r"""L8 SEGB 道钉版 —— args.py 散文挖掘收尾面 + ``_protect_cs`` 键形态告警。

四组语义（与 ``_handle_opaque_macro``/探针/argspec 三臂同一共享判据
``_opaque_arg_prose`` + 调用点名闸 ``_prose_args_of``）：

- **死参门（W27 changes 族）**：``\deleted``/``\removed`` 参是被删文本
  ——整调用不挖；``\replaced{新}{旧}`` 只放首参（``{旧}`` 死文本不译）。
- **protect-block 第三臂（界外需求并入）**：``\markright``/``\markboth``/
  ``\address``/``\institute``/``\affiliation`` 白名单名实参逐参过散文门
  ——命中 ``[[CMD]]`` 分段 + 子扫渲 run surface，无命中全参回放走原
  ``[[AUTHOR]]`` 路径零变化；``\author`` 等元数据名不入白名单。
- **``[``-open 可选参（``\subfigure[长 caption]``）+ 零宽剔除（W85）**：
  opt 参同挖（``[width=2cm]``/``[see]`` 由 keyval/词链门挡住）；
  ``\index``/``\label`` 整调用判形前剥除，不当词链隔墙。
- **键形态告警（W89/W90）**：``\bibitem(13)`` 圆括号标号 → ``bibitem_paren``；
  ``\cite{15-20}`` 区间误植键 → ``cite_range_key``。v1 ``_protect_call``
  同款双臂 parity。

每条用例过公共不变式：``reconstruct(res) == tex`` + ``validate_result``
零告警 + pieces 无缝平铺（v1 臂例外——v1 只钉告警与 ph_map 面）。
"""

import re

import pytest
from conftest import ART, blob, check_invariants

from texlate.latex import parse_tex, parse_tex_v1, reconstruct
from texlate.latex.model import ScanResult

PROSE = "We consider a two form antisymmetric tensor field theory in detail"
KEY = "dalianis2020"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def scan(body: str, defs: str = "", art: str = ART) -> ScanResult:
    tex = art % (defs, body)
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


def cmd_bodies(res: ScanResult) -> list[str]:
    """全部 ``[[CMD_n]]`` ph 体（覆盖区间原文）。"""
    return [
        body for ph, body in res.ph_map.items() if re.fullmatch(r"\[\[CMD_\d+\]\]", ph)
    ]


def author_bodies(res: ScanResult) -> list[str]:
    """全部 ``[[AUTHOR_n]]`` ph 体。"""
    return [
        b for ph, b in res.ph_map.items() if re.fullmatch(r"\[\[AUTHOR_\d+\]\]", ph)
    ]


# ------------------------------------------------------------------ W27 死参门


def test_deleted_arg_stays_opaque() -> None:
    r"""``\deleted{prose}`` 死文本：整调用单 CMD ph——被删内容不进译文面。"""
    res = scan(f"\\deleted{{{PROSE}.}} Tail prose keeps flowing here.")
    bodies = cmd_bodies(res)
    assert f"\\deleted{{{PROSE}.}}" in bodies
    assert PROSE not in blob(res)


def test_removed_arg_stays_opaque() -> None:
    r"""``\removed{prose}`` 同款死文本门——整调用 opaque。"""
    res = scan(f"\\removed{{{PROSE}.}} Tail prose keeps flowing here.")
    bodies = cmd_bodies(res)
    assert f"\\removed{{{PROSE}.}}" in bodies
    assert PROSE not in blob(res)


def test_replaced_first_arg_surfaces_tail_dead() -> None:
    r"""``\replaced{新}{旧}``：新文本散文出 surface，``{旧}`` 死文本留 CMD。"""
    res = scan(f"\\replaced{{{PROSE}.}}{{The old removed sentence text.}} Tail.")
    text = blob(res)
    assert PROSE in text
    assert "old removed sentence" not in text
    bodies = cmd_bodies(res)
    assert any("{The old removed sentence text.}" in b for b in bodies)


def test_replaced_opt_arg_not_counted() -> None:
    r"""``\replaced`` 序数按实消费参计：首实参（新文本）仍出 surface。"""
    res = scan(f"\\replaced{{{PROSE} one.}}{{{KEY}}} Tail words keep flowing here.")
    assert PROSE in blob(res)


def test_opaque_macro_removed_stays_opaque() -> None:
    r"""已定义 ``\newcommand{\removed}[1]{}`` + ``\removed{prose}``：
    opaque 臂同款名闸——整调用 MACRO，散文不挖。"""
    res = scan(
        f"\\removed{{{PROSE}.}} Tail prose keeps flowing here.",
        "\\newcommand{\\removed}[1]{\\ignorespaces}\n",
    )
    assert PROSE not in blob(res)


# ------------------------------------------------------------------ protect-block 第三臂


def test_markright_prose_surfaces() -> None:
    r"""``\markright{prose}`` 运行头：散文出 surface，``\markright{``/``}`` 留 CMD。"""
    res = scan(f"\\markright{{{PROSE}.}} Body prose follows here.")
    assert PROSE in blob(res)
    bodies = cmd_bodies(res)
    assert "\\markright{" in bodies
    assert "}" in bodies
    assert all(PROSE not in b for b in bodies)


def test_markboth_both_heads_surface() -> None:
    r"""``\markboth{左}{右}`` 双参逐参判定：两段运行头都出 surface。"""
    p2 = "Another independent running head phrase here"
    res = scan(f"\\markboth{{{PROSE}.}}{{{p2}.}} Body prose follows.")
    text = blob(res)
    assert PROSE in text
    assert p2 in text
    assert any("}{" in b for b in cmd_bodies(res))


def test_markboth_second_nonprose_stays() -> None:
    r"""``\markboth{prose}{KEY}``：只挖散文参——键位参随结构段留 CMD。"""
    res = scan(f"\\markboth{{{PROSE}.}}{{{KEY}}} Body prose follows here.")
    text = blob(res)
    assert PROSE in text
    assert KEY not in text
    assert any(f"}}{{{KEY}}}" in b for b in cmd_bodies(res))


def test_markright_short_head_stays_author() -> None:
    r"""``\markright{ApJ}`` 短头不过词链门——无命中走原 ``[[AUTHOR]]`` 路径。"""
    res = scan("\\markright{ApJ} Body prose follows here now.")
    assert "\\markright{ApJ}" in author_bodies(res)
    assert "ApJ" not in blob(res)


def test_markright_bare_stays_author() -> None:
    r"""裸 ``\markright`` 无组参：``[[AUTHOR]]`` 只护本体（abort 路径不变）。"""
    res = scan("\\markright Body prose follows here now today.")
    assert "\\markright" in author_bodies(res)


def test_address_prose_surfaces() -> None:
    r"""``\address{机构隶属散文}``：隶属段散文出 surface（第三臂白名单）。"""
    res = scan(
        "\\address{Department of Mathematics, University of Kansas, Lawrence}"
        " Body text follows here."
    )
    assert "Department of Mathematics" in blob(res)
    assert "\\address{" in cmd_bodies(res)


def test_institute_prose_surfaces() -> None:
    r"""``\institute{机构散文}`` 同款。"""
    res = scan(
        "\\institute{Max Planck Institute for Mathematics in the Sciences}"
        " Body text follows."
    )
    assert "Max Planck Institute" in blob(res)


def test_affiliation_prose_surfaces() -> None:
    r"""``\affiliation{机构散文}`` 同款。"""
    res = scan(
        "\\affiliation{Department of Physics, Some University, Springfield}"
        " Body prose here."
    )
    assert "Department of Physics" in blob(res)


def test_author_and_not_mined() -> None:
    r"""``\author{F \\and S}``：``\\and`` 连名虽过词链门也不入白名单——
    人名是专名元数据非散文槽位，整调用 ``[[AUTHOR]]``。"""
    res = scan("\\author{First Author \\and Second Author} Body text follows here.")
    assert "\\author{First Author \\and Second Author}" in author_bodies(res)
    assert "First Author" not in blob(res)


def test_author_embedded_fig_stays_protected() -> None:
    r"""``\author{…\\includegraphics…}`` 内嵌图（W56）：整调用 ``[[AUTHOR]]``。"""
    res = scan(
        "\\author{Some Author$^{\\includegraphics[width=2.5mm]{ORCID.png}}$}"
        " Body prose follows here."
    )
    bodies = author_bodies(res)
    assert any("includegraphics" in b for b in bodies)


def test_email_stays_author() -> None:
    r"""``\email{x@y}`` 标识元数据：``[[AUTHOR]]``。"""
    res = scan("\\email{someone@example.edu} Body prose follows here today.")
    assert "\\email{someone@example.edu}" in author_bodies(res)


def test_protectblock_keyval_tail_preserved() -> None:
    r"""``\author{name}{key=..}`` keyval 尾组面（aipproc 五格）不回退：
    非白名单名走原路径，keyval 组仍被 ``_keyval_tail_end`` 收进 ph。"""
    res = scan(
        "\\author{Some Name}{address=Some Inst, email=a@b.edu} Body prose follows here."
    )
    assert any("address=Some Inst" in b for b in author_bodies(res))
    assert "address=Some Inst" not in blob(res)


# ------------------------------------------------------------------ [ -open 可选参 + W85 零宽


def test_opt_arg_prose_surfaces() -> None:
    r"""``\\subfigure[长 caption]{图}``：``[``-open opt 散文参出 surface。"""
    res = scan(
        "\\subfigure[This is a long optional caption text]"
        "{\\includegraphics{x.eps}}\nBody."
    )
    assert "long optional caption" in blob(res)
    bodies = cmd_bodies(res)
    assert "\\subfigure[" in bodies
    assert any("includegraphics" in b for b in bodies)


def test_opt_arg_keyval_stays() -> None:
    r"""``[width=2cm]`` 形 keyval opt 不挖——形状门挡住。"""
    res = scan(
        "\\unknowncmd[width=2cm, height=3cm]{{"
        + KEY
        + "}} Tail prose keeps flowing here."
    )
    bodies = cmd_bodies(res)
    assert any("width=2cm" in b for b in bodies)
    assert "height" not in blob(res)


def test_opt_arg_short_not_lifted() -> None:
    r"""``[see]`` 短 opt 不过词链门——维持 opaque。"""
    res = scan(f"\\unknowncmd[see]{{{KEY}}} Tail prose keeps flowing here now.")
    assert "see" not in blob(res)


def test_index_zero_width_stripped() -> None:
    r"""``{散文 \\index{x} 散文}``：``\index`` 整调用判形前剥除——
    词链连通，散文出 surface；``\index`` 子扫仍折 ``[[CMD]]`` 保真。"""
    res = scan(f"\\unknowncmd{{inflation \\index{{inflation}} and {PROSE} epoch.}}")
    text = blob(res)
    assert PROSE in text
    assert "\\index{inflation}" in cmd_bodies(res)


def test_label_zero_width_stripped() -> None:
    r"""``\\label`` 同款零宽剥除。"""
    res = scan(f"\\unknowncmd{{{PROSE} \\label{{sec:x}} continues onward.}}")
    assert PROSE in blob(res)


def test_index_body_inline_stays_opaque() -> None:
    r"""正文内嵌 ``\index``（W85 体面）：词流通畅，``\index`` 逐字保真。"""
    res = scan(
        "inflation \\index{inflation} and the reheating epoch "
        "\\index{epoch} proceed through several distinct stages."
    )
    text = blob(res)
    assert "inflation" in text
    assert "distinct stages" in text
    assert "\\index{inflation}" in cmd_bodies(res)


# ------------------------------------------------------------------ W89/W90 键形态告警


def test_bibitem_paren_warns() -> None:
    r"""``\bibitem(13)`` 圆括号标号（W89）：``[[BIB]]`` 护本体 +
    ``bibitem_paren`` 告警，标号文留 chunk。"""
    res = scan(
        "\\begin{thebibliography}{9}\n"
        "\\bibitem(13) V.D.Korepin et al, Some reference text here.\n"
        "\\end{thebibliography}\nBody."
    )
    assert any(w.kind == "bibitem_paren" for w in res.warnings)
    assert "(13)" in blob(res)


def test_bibitem_key_no_warn() -> None:
    r"""``\\bibitem{key}`` 常形：无 ``bibitem_paren`` 告警。"""
    res = scan(
        "\\begin{thebibliography}{9}\n"
        "\\bibitem{somekey} Reference text flows here onward.\n"
        "\\end{thebibliography}\nBody."
    )
    assert not any(w.kind == "bibitem_paren" for w in res.warnings)


def test_cite_range_key_warns() -> None:
    r"""``\cite{15-20}`` 区间误植键（W90）：``[[CITE]]`` 照旧 +
    ``cite_range_key`` 告警。"""
    res = scan("See \\cite{15-20} for background material and more context.")
    assert any(w.kind == "cite_range_key" for w in res.warnings)
    assert any(
        b == "\\cite{15-20}" for ph, b in res.ph_map.items() if ph.startswith("[[CITE_")
    )


def test_cite_range_in_list_warns() -> None:
    r"""``\cite{key1, 15-20}`` 逗号项中区间键同样告警。"""
    res = scan("See \\cite{key1, 15-20} for the background material here.")
    assert any(w.kind == "cite_range_key" for w in res.warnings)


def test_cite_normal_key_no_warn() -> None:
    r"""``\cite{smith-2020,key-a}`` 合法键（含连字符非纯数字区间）：无告警。"""
    res = scan("See \\cite{smith-2020, key-a} for the background material.")
    assert not any(w.kind == "cite_range_key" for w in res.warnings)


def test_v1_bibitem_paren_warns() -> None:
    r"""v1 臂同款：``\bibitem(13)`` → ``bibitem_paren`` 告警。"""
    tex = ART % ("", "\\bibitem(13) V.D.Korepin et al, Some reference text.")
    res = parse_tex_v1(tex)
    assert reconstruct(res) == tex
    assert any(w.kind == "bibitem_paren" for w in res.warnings)


def test_v1_cite_range_key_warns() -> None:
    r"""v1 臂同款：``\cite{15-20}`` → ``cite_range_key`` 告警。"""
    tex = ART % ("", "See \\cite{15-20} for the background material here.")
    res = parse_tex_v1(tex)
    assert reconstruct(res) == tex
    assert any(w.kind == "cite_range_key" for w in res.warnings)


def test_v1_cite_normal_key_no_warn() -> None:
    r"""v1 臂负向：合法键无 ``cite_range_key``。"""
    tex = ART % ("", "See \\cite{smith-2020} for the background material.")
    res = parse_tex_v1(tex)
    assert reconstruct(res) == tex
    assert not any(w.kind == "cite_range_key" for w in res.warnings)


# ------------------------------------------------------------------ 其余机制行为钉


def test_lyx_protect_caption_surfaces() -> None:
    r"""``\protect\caption{prose}``（W10 LyX 前置）：caption 照常出 chunk。"""
    res = scan(
        "\\protect\\caption{This is a fairly long caption text here.}\n"
        "Body prose follows with several words."
    )
    assert "fairly long caption text" in blob(res)


def test_url_nonascii_protected() -> None:
    r"""``\\url{…∼…}`` 非 ASCII（W12）：整调用 ``[[URL]]`` 逐字保真。"""
    res = scan("See \\url{http://web-docs.gsi.de/∼misko/overlap/} for data.")
    assert any("∼misko" in b for ph, b in res.ph_map.items() if ph.startswith("[[URL_"))
    assert "misko" not in blob(res)


def test_amsrefs_bib_keyval_stays_opaque() -> None:
    r"""amsrefs ``\bib{key}{type}{keyval}``（W30）：keyval 门整调用 opaque。"""
    res = scan(
        "\\begin{biblist}\n"
        "\\bib{Key1}{article}{author={Doe, John}, title={Some long paper"
        " title goes here}, journal={J. Math.}, year={2020}}\n"
        "\\end{biblist}\nBody text."
    )
    bodies = cmd_bodies(res)
    assert any("title={Some long paper" in b for b in bodies)
    assert "long paper title" not in blob(res)


def test_keyval_group_comment_leading_stays_opaque() -> None:
    r"""注释行起头的 keyval 组同收——形状门先剥 ``%`` 注释行再判。

    2105.00041 ``lstlean.tex`` 实证：``\lstdefinelanguage{lean}{`` 起头的
    ~250 行定义体以 ``%`` 注释行起头，裸套 ``_KEYVAL_GROUP_RX`` 在 ``%``
    处即断 → 组判成散文 → ``mathescape=``/``morekeywords=`` 键位被译成
    ``这是译文`` → ``Package keyval Error``。``\%`` 转义不剥。
    """
    res = scan(
        "\\lstdefinelanguage{lean} {\n"
        "% Anything betweeen $ becomes LaTeX math mode\n"
        "mathescape=false,\n"
        "texcl=false,\n"
        "morekeywords=[1]{import, prelude, open, as},\n"
        "basicstyle={\\ttfamily},\n"
        "}\n"
        "Tail prose words keep flowing here.\n"
    )
    bodies = cmd_bodies(res)
    assert any("mathescape=false" in b for b in bodies)
    assert "mathescape" not in blob(res)
    assert "morekeywords" not in blob(res)
    assert "texcl" not in blob(res)
    assert "Tail prose words" in blob(res)


def test_keyval_group_comment_between_entries_stays_opaque() -> None:
    r"""keyval 组内行间注释同剥——``key=val,`` 后注释行再 ``key=`` 仍 opaque。"""
    res = scan(
        "\\author{Doe}{% affiliation line\n"
        "address=MIT, email=d@x, % trailing note\n"
        "name=Third}\nBody prose keeps flowing here.\n"
    )
    assert "address=MIT" not in blob(res)
    assert "email=d@x" not in blob(res)


def test_epigraph_first_arg_surfaces() -> None:
    r"""``\epigraph{引文}{署名}``（W33）：引文散文出 surface，署名留 CMD。"""
    res = scan(
        "\\epigraph{``Noi ci allegrammo in questo momento di gioia''}{Dante}\n"
        "Body prose follows here.",
        "\\usepackage{epigraph}\n",
    )
    text = blob(res)
    assert "allegrammo" in text
    assert "Dante" not in text
    assert any("}{Dante}" in b for b in cmd_bodies(res))


def test_renewcommand_cite_still_cite() -> None:
    r"""``\\renewcommand{\\cite}[1]{\\citep{#1}}`` 后 ``\cite``（W44）：
    名分派不穿透重定义——仍 ``[[CITE]]``。"""
    res = scan(
        "As shown in \\cite{key1,key2} the results hold. Tail words here.",
        "\\renewcommand{\\cite}[1]{\\citep{#1}}\n",
    )
    assert any(
        b == "\\cite{key1,key2}"
        for ph, b in res.ph_map.items()
        if ph.startswith("[[CITE_")
    )


def test_let_cite_still_cite() -> None:
    r"""``\\let\\cite\\citep`` 同款。"""
    res = scan(
        "As shown in \\cite{key3} the results hold. Tail words here.",
        "\\let\\cite\\citep\n",
    )
    assert any(
        b == "\\cite{key3}" for ph, b in res.ph_map.items() if ph.startswith("[[CITE_")
    )


def test_comment_macro_stays_macro() -> None:
    r"""``\\newcommand{\\comment}[1]{}`` + ``\\comment{散文}``（W50 吞块）：
    整调用 ``[[MACRO]]``——隐藏批注不进译文面。"""
    res = scan(
        "\\comment{ \\author{Hidden Name} \\institute{Hidden Inst} }"
        " Visible tail prose flows here.",
        "\\newcommand{\\comment}[1]{}\n",
    )
    assert "Hidden Name" not in blob(res)
    assert any(
        "Hidden Name" in b for ph, b in res.ph_map.items() if ph.startswith("[[MACRO_")
    )


def test_requirepackage_before_docclass() -> None:
    r"""``\\RequirePackage`` 先于 ``\\documentclass``（W54）：导言界双闸
    顺序无关——体散文照常。"""
    tex = (
        "\\RequirePackage{lineno}\n"
        "\\documentclass{article}\n"
        "\\begin{document}\nBody prose after preamble flows here.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "Body prose after preamble" in blob(res)


def test_abstracts_cmd_prose_surfaces() -> None:
    r"""期刊前置 ``\abstracts{prose}`` 命令形（W96 体面）：散文抠出。"""
    res = scan(
        "\\abstracts{This is a command-form abstract with several words inside.}\nBody."
    )
    assert "command-form abstract" in blob(res)


def test_citenum_cite_ph() -> None:
    r"""``\citenum{k}``（W97 非 ``\cite`` 引用面）：argspec ``o o m`` →
    ``[[CITE]]`` 键面正确。"""
    res = scan("See \\citenum{Karney-lh}--\\citenum{Karney-ec} for range.")
    cites = [b for ph, b in res.ph_map.items() if ph.startswith("[[CITE_")]
    assert "\\citenum{Karney-lh}" in cites
    assert "\\citenum{Karney-ec}" in cites


def test_ref_cs_arg_prose_surfaces() -> None:
    r"""``\ref\sezgin{prose}``（W97）：``\ref`` → ``[[REF]]`` 本体，
    后随 ``\sezgin{散文}`` 照常挖。"""
    res = scan("Text with \\ref\\sezgin{some label words here} inside the body prose.")
    text = blob(res)
    assert "some label words here" in text
    assert any(b == "\\ref" for ph, b in res.ph_map.items() if ph.startswith("[[REF_"))
