r"""segmenter 机制波回归（fixer-machinery，illegal_unit 机制半场）。

覆盖 spec.md M1–M5 + keyarg 残留：

- M1 ``_emit_argspec_chunks`` in_arg 臂 lit 段 → ``[[CMD]]`` 代位
  （``\multirow{2}{*}{\parbox{3cm}{x}}`` 的 ``{3cm}`` 不裸进参内 chunk）；
- M2 新参种 ``n`` = 裸 cs 名参（``\setlength\parskip{4pt}`` 的 ``{4pt}`` 不漏），
  ``BOUNDARY_TAIL`` 直载（v1 ``_args``/v2 ``_args_tok`` 双侧 ``n`` 臂）；
- M3 ``\\[dim]`` 尾参；M4 ``\parindent[=]4pt`` 赋形尾；
- M5 ``_grp_spec_args_end`` ``m`` 臂认 ``[`` 定界组（restatable ``[N]``）；
- 残留：``\joref``/``\crefrange`` 多参书目宏签名驱动 mand——``{b}`` 不漏。

每条断言过 ``check_invariants`` 三件套 + 面级断言（结构参不进 chunk、
文本参仍进 chunk）。
"""

import pytest
from conftest import ART, check_invariants, chunk_text

from texlate.latex import parse_tex
from texlate.latex.api import new_state
from texlate.latex.macro_table import parse_argspec
from texlate.latex.model import ArgSpec, PieceKind
from texlate.latex.scanner import Scanner


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


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


def test_settowidth_family_bare_cs_arg() -> None:
    r"""M2 同族迁移：``\settowidth``/``\settoheight``/``\settodepth`` 迁入
    BOUNDARY_NAMES——裸名形 ``\settowidth\mylen{xx}`` 整调用 LITERAL，
    校准内容不译（迁前走 argspec ``key``：名本体 ``[[CMD]]`` + ``\mylen``
    孤探针，两碎片同罩但族语义不齐）。"""
    tex = ART % (
        "",
        (
            "\\settowidth\\mylen{Calib text one}\n"
            "\\settoheight\\myht{Calib text two}\n"
            "\\settodepth\\mydp{Calib text three}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    for tok in ("mylen", "myht", "mydp", "Calib text"):
        assert tok not in body
    assert "Body text" in body
    # 机制钉：BOUNDARY 臂整调用单 LITERAL piece（argspec key 臂则拆
    # ``\settowidth`` 名 ph + ``\mylen{..}`` 探针 ph 两碎片）
    lits = [p.text for p in res.pieces if p.kind is PieceKind.LITERAL]
    assert "\\settowidth\\mylen{Calib text one}" in lits
    assert "\\settoheight\\myht{Calib text two}" in lits
    assert "\\settodepth\\mydp{Calib text three}" in lits


def test_settowidth_braced_form() -> None:
    r"""M2 迁移花括号形：``\settowidth{\mylen}{xx}``——``n`` 槽认 ``{..}`` 组，
    整调用照常全收。"""
    tex = ART % (
        "",
        (
            "\\settowidth{\\mylen}{Calib text}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "Calib text" not in body
    assert "mylen" not in body
    lits = [p.text for p in res.pieces if p.kind is PieceKind.LITERAL]
    assert "\\settowidth{\\mylen}{Calib text}" in lits


def test_settowidth_bare_cs_in_arg() -> None:
    r"""M2 迁移参内形：``\caption{..\settowidth\mylen{x}..}`` 整调用 ``[[CMD]]``。"""
    tex = ART % (
        "",
        (
            "\\caption{Cap \\settowidth\\mylen{xx} tail words}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "mylen" not in body
    assert "xx" not in body
    assert "Cap " in body
    # 机制钉：参内边界臂 spec 收参 → 单 ``[[CMD]]`` 罩整调用（argspec
    # key 臂则名/探针双 ph）
    assert "\\settowidth\\mylen{xx}" in res.ph_map.values()


def test_parse_argspec_n_letter() -> None:
    r"""M2 签名语言补齐：``parse_argspec`` 认 ``n``——``"n m"`` → ``[n, m]``
    （迁前无 ``n`` 臂静默跳过 → ``arg_roles`` 位序错位隐患）。"""
    assert parse_argspec("n m") == [ArgSpec("n"), ArgSpec("m")]
    assert parse_argspec("s n") == [ArgSpec("s"), ArgSpec("n")]


def test_v1_setlength_bare_cs_whole_literal() -> None:
    r"""M2 v1 对价：``BOUNDARY_TAIL`` 直载 ``[n, m]`` 后 v1 ``_args`` ``n``
    臂收裸名——``\setlength\parskip{4pt}`` 整段单 LITERAL（迁前 v1
    ``m`` 臂遇 ``\`` 即停 → ``\parskip{4pt}`` 走未知探针碎罩）。"""
    tex = ART % (
        "",
        (
            "\\setlength\\parskip{4pt}\n"
            "\\settowidth\\mylen{xx}\n"
            "Body text here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = Scanner(new_state()).scan(tex)
    lits = [p.text for p in res.pieces if p.kind is PieceKind.LITERAL]
    assert "\\setlength\\parskip{4pt}" in lits
    assert "\\settowidth\\mylen{xx}" in lits
    body = chunk_text(res)
    assert "4pt" not in body
    assert "parskip" not in body
    assert "Body text" in body


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


# ------------------------------------------------- illegal_unit 波（2026-09-17）
# 实证机制（stagerun-loop1 残留 ~25 格逐线复核）：逗号小数、单位字母词界、
# 换行/注释间隙、计数器裸整数赋值、组内 n 槽 spec-blind、multirow 可选参、
# env argspec 缺口、genfrac literal 空签名。


def test_raise_comma_decimal_dimen() -> None:
    r"""``\raise 1,5pt``——欧陆逗号小数（TeX 认 ``,`` 为小数点）进 dimen 尾扫
    （0806.4203：``1,5`` 残留 + ``pt`` 被译 → ``1,5 这是译文``）。"""
    tex = ART % (
        "",
        "Text \\raise 1,5pt \\hbox{,} tail words here to fill the paragraph.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "1,5pt" not in body
    assert "raise" not in body
    assert "tail words" in body


def test_bsbs_comma_decimal_opt() -> None:
    r"""``\\[1,5cm]``——换行可选参同认逗号小数（0905.0575）。"""
    tex = ART % (
        "",
        "First line words here \\\\[1,5cm] second line words fill the para.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "1,5cm" not in chunk_text(res)


def test_bsbs_opt_after_newline() -> None:
    r"""``\\`` 行尾 + 次行 ``[8pt]``——单换行是 TeX 空白语义（hep-ph/0307181
    titlepage 区 ``[8这是译文]`` 残留）。"""
    tex = ART % (
        "",
        "First line words here \\\\\n[8pt] second line words fill the para.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "8pt" not in chunk_text(res)


def test_bsbs_opt_comment_interrupted() -> None:
    r"""``\\[0pt%`` + 次行 ``]``——``%`` 注释吞行尾后 ``]`` 续参
    （1511.06628 ``\\[0pt%`` 形）。"""
    tex = ART % (
        "",
        "First line \\\\\nmore \\\\[0pt%\n] tail words here fill the para.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "0pt" not in chunk_text(res)


def test_tail_operand_after_newline() -> None:
    r"""``\\hskip`` 行尾 + 次行 ``1em plus..``——换行分隔操作数随尾扫
    （2105.00030 文献区 ``1em\\relax``→``1这是译文``）；``\\relax`` 归
    INLINE_LITERAL 不裸进 surface。"""
    tex = ART % (
        "",
        (
            "Text.\\hskip\n  1em plus 0.5em minus 0.4em\\relax Avignon "
            "words here to fill the paragraph out nicely.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    for tok in ("1em", "0.5em", "0.4em", "hskip", "relax"):
        assert tok not in body
    assert "Avignon" in body


def test_tail_operand_par_boundary_kept() -> None:
    r"""``\\hskip\\n\\n1em``——``\\n\\n`` 段界不跨：``1em`` 另起段是正文。"""
    tex = ART % (
        "",
        "Text.\\hskip\n\n1em next para words here to fill the paragraph.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "1em" in chunk_text(res)


def test_dimen_unit_no_letter_boundary() -> None:
    r"""``\\baselineskip=10ptReceived``——TeX 单位是定长关键字匹配（无词界），
    ``10pt`` 随尾扫、``Received`` 留正文（physics/9901057 center 块实证）。"""
    tex = ART % (
        "",
        "{\\footnotesize\\baselineskip=10ptReceived 3 October 1997 words.}\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "10pt" not in body
    assert "baselineskip" not in body
    assert "Received" in body


def test_vskip_unit_prefix_word_split() -> None:
    r"""``\\vskip-0.015inside``——``in`` 是合法单位：收 ``-0.015in``、
    ``side`` 作正文（与 TeX 同式；旧前瞻拒配曾致整尾漏）。"""
    tex = ART % (
        "",
        "Text \\vskip-0.015inside tail words here to fill the paragraph.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "0.015in" not in body
    assert "side" in body


def test_count_register_assigns() -> None:
    r"""计数器寄存器：``\\hangafter=1``/``\\looseness=-1``/``\\tolerance=800``/
    ``\\hbadness 10000``（无等号形）全收（M1-A 簇 ``hangafter=1这是译文``
    74 行粘连实证）。"""
    tex = ART % (
        "",
        (
            "Text \\hangafter=1 and \\looseness=-1 \\tolerance=800 \\hbadness "
            "10000 tail words fill the paragraph.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    for tok in ("hangafter", "looseness", "tolerance", "hbadness", "=1", "10000"):
        assert tok not in body
    assert "tail words" in body


def test_unknown_cs_bare_int_assign() -> None:
    r"""表外名 ``\\foo=2``——通用 assign 兜底裸整数（``=N`` 非散文）。"""
    tex = ART % (
        "",
        "Text \\foo=2 tail words here to fill the paragraph out nicely.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "=2" not in body
    assert "foo" not in body


def test_hskip_dot_pt() -> None:
    r"""``\\hskip.pt``——裸 ``.``+单位 atom（TeX missing-number 形，覆盖保真
    优于 ``pt`` 漏译；1511.02686 文献区实证）。"""
    tex = ART % (
        "",
        "Preprint arXiv:\\hskip.pt 1504.00586v1 [math-ph] words to fill.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert ".pt" not in chunk_text(res)


def test_setlength_bare_cs_inside_group() -> None:
    r"""组内 ``{\\setlength\\arraycolsep{2pt} ..}``——BOUNDARY 臂改走
    ``_grp_spec_args_end`` 位序：``n`` 槽收裸 cs token（1608.02270
    ``\\setlength\\arraycolsep{2pt}`` 34 处残留实证）。"""
    tex = ART % (
        "",
        "{Pre \\setlength\\arraycolsep{2pt} post words here fill para.}\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "2pt" not in body
    assert "arraycolsep" not in body
    assert "post words" in body


def test_multirow_fixup_opt_args() -> None:
    r"""``\\multirow{2}{*}[2.5em]{text}``——签名 ``s m o m o m``：fixup
    可选参收、``{text}`` 可译留 surface（1608.02289/2009.11016/2104.00138
    ``[2.5em]``→``[2.5这是译文]`` 实证）。旧版 ``{n}[b]{w}{t}`` 序同盖。"""
    tex = ART % (
        "\\usepackage{multirow}\n",
        (
            "\\begin{tabular}{cc}\n"
            "\\multirow{2}{*}[2.5em]{Text cell one} & x \\\\\n"
            "\\multirow{2}[6]{*}{Text cell two} & y \\\\\n"
            "\\end{tabular}\n"
            "After words here to fill the paragraph out nicely and more.\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "2.5em" not in body
    assert "6]" not in body
    assert "Text cell one" in body


def test_adjustwidth_env_dimen_args() -> None:
    r"""``\\begin{adjustwidth*}{1em}{0em}``——env argspec ``m m`` 收双
    dimen 参（1706.02447 ``{1这是译文}{0这是译文}`` 实证）；体是正文。"""
    tex = ART % (
        "\\usepackage{changepage}\n",
        (
            "\\begin{adjustwidth*}{1em}{0em}\n"
            "Inner text words here to fill the paragraph out nicely.\n"
            "\\end{adjustwidth*}\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "1em" not in body
    assert "0em" not in body
    assert "Inner text" in body


def test_hangparas_env_dimen_args() -> None:
    r"""``\\begin{hangparas}{.25in}{1}``——env argspec ``m m``
    （1803.00111 ``{.25这是译文}{1}``×36 实证）。"""
    tex = ART % (
        "\\usepackage{hanging}\n",
        (
            "\\begin{hangparas}{.25in}{1}\n"
            "Reference text words here to fill the paragraph out.\n"
            "\\end{hangparas}\n"
        ),
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert ".25in" not in body
    assert "Reference text" in body


def test_genfrac_all_args_protected() -> None:
    r"""``\\genfrac{}{}{0pt}{}{a}{b}``——六参签名 + protect：math-literal 族
    空签名在散文漏 ``{0pt}``（2308.04175 ``\\be`` 未定义致数学区塌进
    散文的实证）。"""
    tex = ART % (
        "\\usepackage{amsmath}\n",
        "Text then \\genfrac{}{}{0pt}{}{a}{b} tail words fill the para.\n",
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    body = chunk_text(res)
    assert "0pt" not in body
    assert "genfrac" not in body
