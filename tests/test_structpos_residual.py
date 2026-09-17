r"""结构位残留洞 R1–R8 回归（structpos 波次后半场）。

八个洞的同源族：保护结构的位置/配对在某些拼法下漏出字面字节进
chunk（或反方向——该 literal 的结构件被展开物质化）。每条断言走
``check_invariants`` 三件套（identity/validate/pieces 平铺）外加
面级断言（chunk 不得含裸 preamble/path/名组）：

- R1  ``\csname endX\endcsname``/旧式 ``\endX`` 不配对环境（宏表无
  登记的端点形态在 token 配对扫描里隐身）；
- R2  未闭合环境的 ``{cc}`` preamble 裸进 chunk（``hit is None``
  兜底不吃环境尾参）；
- R3  未注册环境的列型前导参 ``{>{\raggedright}p{4cm}}`` 泄漏；
- R4  ``\input \cs`` 动态文件名的 cs 被主流展开、体文本漏进 chunk；
- R5  run 项边界 ``\letters``+字母熔合（csname 合成 token 的
  zero-width ident 让 ``\w after`` 渲成 ``\endtabularafter``）；
- R6  ``\end`` 换段 ``{name}`` 收不到名 → ``{name}`` 裸进 chunk；
- R7  端点宏体不纯（``\relax\end{X}``）登记落空 + 组内
  ``\begin{保护族}`` 无配对时物质化假 tag；
- R8  裸 ``\tikz <path>;`` 整句 path 进 chunk（argspec ``o o m``
  认不出无 ``[``/``{`` 起头的路径形）。
"""

import pytest
from conftest import ART, check_invariants, chunk_text

from texlate.latex import parse_tex, reconstruct
from texlate.latex.tables import looks_like_colspec


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


# ------------------------------------------------------------------ R1


def test_r1_old_style_endcs_pairs_env() -> None:
    r"""``\begin{tabular}…\endtabular`` 旧式端点：整段 ENV 保护不再漏体。"""
    tex = ART % (
        "",
        (
            "\\begin{tabular}{cc}\nA & B \\\\\nC & D\\endtabular\n"
            "After words here and more text to fill.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert not any(w.kind == "unclosed_env" for w in res.warnings)
    envs = [v for k, v in res.ph_map.items() if k.startswith("[[ENV")]
    assert any("\\begin{tabular}" in v and "\\endtabular" in v for v in envs)
    assert "{cc}" not in chunk_text(res)
    assert "A & B" not in chunk_text(res)


def test_r1_csname_macro_endpoint_pairs_env() -> None:
    r"""``\def\w{\csname endtabular\endcsname}``+``\w``：端点经宏表登记配对。"""
    tex = ART % (
        "\\def\\w{\\csname endtabular\\endcsname}\n",
        (
            "\\begin{tabular}{cc}\nA & B \\\\\nC & D\\w\n"
            "After words here and more text to fill.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert not any(w.kind == "unclosed_env" for w in res.warnings)
    envs = [v for k, v in res.ph_map.items() if k.startswith("[[ENV")]
    assert any(v.endswith("\\w") for v in envs)  # \w 整调用收进 ENV 体
    assert "A & B" not in chunk_text(res)


def test_r1_direct_csname_in_body_pairs() -> None:
    r"""体内直用 ``\csname endtabular\endcsname``：raw 前瞻手工收名配对。"""
    tex = ART % (
        "",
        (
            "\\begin{tabular}{cc}\nA & B \\\\\nC & D"
            "\\csname endtabular\\endcsname\n"
            "After words here and more text to fill.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert not any(w.kind == "unclosed_env" for w in res.warnings)
    assert "A & B" not in chunk_text(res)


# ------------------------------------------------------------------ R2


def test_r2_unclosed_env_eats_colspec_arg() -> None:
    r"""未闭合 ``\begin{tabular}{cc}``：``{cc}`` preamble 进字面段不裸漏。"""
    tex = ART % (
        "",
        (
            "\\begin{tabular}{cc}\nA & B \\\\\nC & D\n"
            "After words here and more text to fill the paragraph out.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert any(w.kind == "unclosed_env" for w in res.warnings)
    assert "{cc}" not in chunk_text(res)


def test_r2_unclosed_math_env_eats_colspec() -> None:
    r"""未闭合 ``\begin{array}{cc}``（math 臂）：``{cc}`` 同样不裸漏。"""
    tex = ART % (
        "",
        (
            "\\begin{array}{cc}\nx &= y \\\\ a &= b\n"
            "After words here and more text to fill the paragraph out.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert any(w.kind == "unclosed_env" for w in res.warnings)
    assert "{cc}" not in chunk_text(res)


# ------------------------------------------------------------------ R3


def test_r3_unregistered_env_colspec_eaten() -> None:
    r"""``\begin{mytable}{>{\raggedright}p{4cm}p{4cm}}``：列参进字面段。"""
    tex = ART % (
        "",
        (
            "\\begin{mytable}{>{\\raggedright}p{4cm}p{4cm}}\nA & B\n\\end{mytable}\n"
            "After words here and more text to fill.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "raggedright" not in chunk_text(res)
    assert "p{4cm}" not in chunk_text(res)


def test_r3_title_like_arg_still_leaks_to_chunk() -> None:
    r"""正常面：``{Title}`` 形文本参不是列参——回吐主流仍可译。"""
    tex = ART % (
        "",
        "\\begin{myenv}{Some Title Here}\nBody words inside the env.\n\\end{myenv}\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "Some Title Here" in chunk_text(res)


def test_r3_star_repeat_colspec() -> None:
    r"""``*{n}{spec}`` 纯 array-repeat 列型（wave-review F3）：spec 组剥空后

    残留 ``*`` 无列字母曾漏判——解卷 ``{spec}`` 再走同判，``{*{3}{c}|l}``/
    嵌套 ``*{2}{c*{2}{l}}``/载荷 ``*{2}{p{3cm}}`` 全收；``*{3}`` 残缺形与
    文本参仍落空（fail closed）。
    """
    assert looks_like_colspec("*{3}{c}|l")
    assert looks_like_colspec("*{2}{p{3cm}}")
    assert looks_like_colspec("*{2}{c*{2}{l}}")
    assert not looks_like_colspec("*{3}")
    assert not looks_like_colspec("Summary of results")


def test_r3_star_repeat_env_arg_eaten() -> None:
    r"""集成面：``\\begin{mytab}{*{3}{c}|l}`` 列参进字面段不裸漏。"""
    tex = ART % (
        "",
        (
            "\\begin{mytab}{*{3}{c}|l}\nA & B & C & D\n\\end{mytab}\n"
            "After words here and more text to fill.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "*{3}" not in chunk_text(res)


# ------------------------------------------------------------------ R4


def test_r4_input_cs_swallowed_literal() -> None:
    r"""``\input \myfile``：cs 吞进 literal——``chapter1`` 体文本不漏。"""
    tex = ART % (
        "\\def\\myfile{chapter1}\n",
        (
            "Some intro words here. \\input \\myfile and trailing words "
            "to fill the chunk out.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "chapter1" not in chunk_text(res)
    assert not res.inputs  # 动态名非字面路径——不记 inputs[]


def test_r4_input_cs_inside_expansion() -> None:
    r"""组内 ``\input \cs`` 同规：整调用进 ``[[CMD]]``，cs 不展开。"""
    tex = ART % (
        "\\def\\myfile{chapter1}\n\\def\\load{\\input \\myfile}\n",
        "Some intro words here. \\load and trailing words to fill out.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "chapter1" not in chunk_text(res)


# ------------------------------------------------------------------ R5


def test_r5_csname_cs_then_letter_no_fusion() -> None:
    r"""``\csname endtabular\endcsname after``：项界补空格不熔成假 cs。"""
    tex = ART % (
        "",
        (
            "Pre \\csname endtabular\\endcsname after this text there are "
            "many more words to make a chunk."
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "\\endtabular after" in chunk_text(res)
    assert "\\endtabularafter" not in chunk_text(res)


def test_r5_normal_word_boundaries_untouched() -> None:
    r"""正常面：普通 ``\\foo x``（gap 全白带空格）不重复插空格。"""
    tex = ART % (
        "",
        ("Some \\unknowncs after this text there are many more words to make a chunk."),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "\\unknowncs after" in chunk_text(res)
    assert "\\unknowncs  after" not in chunk_text(res)


# ------------------------------------------------------------------ R6


def test_r6_end_par_then_name_collected() -> None:
    r"""``\\end`` 换段 ``{proof}``：名组收进 tag 不再裸进 chunk。"""
    tex = ART % (
        "",
        ("\\end\n\n{proof}\nAnd text after here to fill the paragraph out nicely.\n"),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "{proof}" not in chunk_text(res)
    # 无对应 \begin——stray_end 告警留痕（tag 本体 literal 完整）
    assert any(w.kind == "stray_end" for w in res.warnings)
    out = reconstruct(res)
    assert "\\end\n\n{proof}" in out


def test_r6_end_single_newline_still_works() -> None:
    r"""正常面：``\\end {proof}``/单换行收名行为不变。"""
    tex = ART % (
        "\\newenvironment{proof}{\\par\\textbf{Proof.}}{\\par}\n",
        (
            "\\begin{proof}\nSome proof body words here.\\end\n{proof}\n"
            "After text here to fill the paragraph out nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)


# ------------------------------------------------------------------ R7


def test_r7_impure_env_end_tail_match_pairs() -> None:
    r"""``\def\eea{\relax\end{eqnarray}}`` 尾匹配登记 → math 区整段保护。"""
    tex = ART % (
        "\\def\\eea{\\relax\\end{eqnarray}}\n",
        (
            "\\begin{eqnarray}\nx &=& y \\\\\na &=& b\n\\eea\n"
            "After text here to fill the paragraph out.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert not any(w.kind == "unclosed_env" for w in res.warnings)
    maths = [v for k, v in res.ph_map.items() if k.startswith("[[MATH")]
    assert any("\\begin{eqnarray}" in v and v.rstrip().endswith("\\eea") for v in maths)
    assert "x &=& y" not in chunk_text(res)


def test_r7_selfcontained_env_wrapper_stays_transparent() -> None:
    r"""正常面：``\\begin{c}Hi\\end{c}`` 全包宏（前缀含文本）仍展开。"""
    tex = ART % (
        "\\newcommand{\\wrap}[1]{\\begin{center}H\\par #1\\end{center}}\n",
        "\\wrap{Some wrapped text here.}",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    [c] = res.chunks
    assert "wrapped" in c.content


def test_r7_unclosed_env_begin_macro_bails_literal() -> None:
    r"""``\\bea``=``\\begin{eqnarray}\\relax``：组内无配对 → 整组 literal。"""
    tex = ART % (
        "\\def\\bea{\\begin{eqnarray}\\relax}\n",
        (
            "\\bea\nx &=& y \\\\\na &=& b\n\\end{eqnarray}\n"
            "After text here to fill the paragraph out.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    out = reconstruct(res)
    assert "\\bea\n" in out  # 调用点原样——编译期真展开成 \begin{eqnarray}
    assert "\\relax" not in chunk_text(res)


# ------------------------------------------------------------------ R8


def test_r8_bare_tikz_path_protected() -> None:
    r"""``\\tikz \\draw (0,0) -- (1,1);``：整句 ``;`` 定界进 ``[[CMD]]``。"""
    tex = ART % (
        "\\usepackage{tikz}\n",
        (
            "Some words. \\tikz \\draw (0,0) -- (1,1); more text here "
            "after the picture.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    cmds = [v for k, v in res.ph_map.items() if k.startswith("[[CMD")]
    assert any("\\tikz \\draw (0,0) -- (1,1);" in v for v in cmds)
    assert "\\draw" not in chunk_text(res)


def test_r8_tikz_braced_shorthand_still_argspec() -> None:
    r"""正常面：``\\tikz{...}``/``\\tikz[..]`` 形仍走 argspec 常路。"""
    tex = ART % (
        "\\usepackage{tikz}\n",
        (
            "Some words. \\tikz{\\draw (0,0) -- (1,1);} more text here "
            "after the picture.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    cmds = [v for k, v in res.ph_map.items() if k.startswith("[[CMD")]
    assert any("\\tikz{\\draw" in v for v in cmds)


def test_r8_tikz_no_semicolon_falls_back() -> None:
    r"""无 ``;`` 终止的 ``\\tikz``（par 界先到）→ 回落签名零参路。"""
    tex = ART % (
        "\\usepackage{tikz}\n",
        (
            "Some words. \\tikz \\draw (0,0)\n\nNew paragraph words here "
            "to fill the chunk out.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    # 无 ; ——不得把 par 后的正文吞进 [[CMD]]
    assert "New paragraph" in chunk_text(res)
