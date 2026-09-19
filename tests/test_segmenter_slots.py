r"""非文本槽位保护回归 —— loop1 stagerun 五类腐蚀形态钉版。

取证现场 ``bench/results/stagerun-loop1-2026-09-16/``：407 格 terminal-partial
中 segmenter 把非文本槽位当 TEXT 段放出，mock 翻译体落进槽位即腐蚀：

1. 维度操作数（``illegal_unit`` ×138）：``\vskip3pt``/``\\[5pt]``/``\vspace{30pt}``
   的单位字母进 chunk → ``3这是译文``；
2. cs+text 黏连（``undefined_cs`` ×104，bug-B）：``\item FSU`` 的后随空格折进
   chunk，``.strip()`` 后重建成 ``\itemFSU``——首字母黏上 cs 名；
3. 名字槽位（``Undefined color`` ×2993/``No counter`` ×292/keyval ~19）：
   ``\textcolor{red}`` 的 ``{red}``、``\arabic{section}`` 的 ``{section}``
   被当可译文本；
4. ``\par``/换行进短参（×62）——xlat 侧归属（译文体内产 ``\par``），
   segmenter 只负责不把 ``\par`` 吞进参数（``ws_skip_arg`` 旧保障），此文件不钉；
5. array preamble（``Illegal pream-token`` ×12）：``\begin{tabu}{cc}`` 的
   格式参裸进 surface。

1e 追补两条同族实证（``bench/results/modec-misschar-2026-09-16/report.md``）：

6. ``_on_math`` 混排闭符（0806.1984 miss×12）：``$\alpha(x)\)`` 的 ``\)``
   不收闭符 → 越过真闭符吞散文、``$`` 奇偶翻转；
7. accent 参保护（0806.3144）：``\c{c}``/``\~n`` 的参字母被译成
   ``\c{这是译文}``——accent+CJK 恒无字槽。

每条用例过公共不变式：``reconstruct(res) == tex`` + ``validate_result`` 零告警
+ pieces 无缝平铺 ``[0, len(vtex))``。
"""

from conftest import DOC, blob, check_invariants

from texlate.latex import parse_tex
from texlate.latex.model import PieceKind, ScanResult


def scan(body: str) -> ScanResult:
    tex = DOC % body
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


# ------------------------------------------------------------- 类1 维度操作数


def test_slot_dimen_bare_operand() -> None:
    r"""``\vskip3pt``：BOUNDARY + dimen 尾扫 → 整体 LITERAL piece，单位不进 chunk。"""
    res = scan("Para text here enough words.\\vskip3pt Tail words here more.")
    assert any(
        p.kind is PieceKind.LITERAL and p.text == "\\vskip3pt" for p in res.pieces
    )
    assert "3pt" not in blob(res)


def test_slot_dimen_glue_plus_minus() -> None:
    r"""glue 形 ``\vskip 3pt plus 1pt``：``plus/minus`` 序一并罩住。"""
    res = scan("Para text here enough words.\\vskip 3pt plus 1pt Tail here.")
    assert any(
        p.kind is PieceKind.LITERAL and p.text == "\\vskip 3pt plus 1pt"
        for p in res.pieces
    )
    assert "plus" not in blob(res)


def test_slot_bsbs_dimen_opt() -> None:
    r"""``\\[5pt]``：单字符 cs 的维度 ``[opt]`` → ``[[CMD]]`` 罩整调用。"""
    res = scan("Line one words here.\\\\[5pt] Line two words here ok.")
    assert res.ph_map["[[CMD_1]]"] == "\\\\[5pt]"
    assert "5pt" not in blob(res)


def test_slot_bsbs_space_dimen_opt() -> None:
    r"""``\\ [5pt]``（星号位空白变体）同罩——``[5pt]`` 不落正文。"""
    res = scan("Line one words here.\\\\ [5pt] Line two words here ok.")
    assert res.ph_map["[[CMD_1]]"] == "\\\\ [5pt]"
    assert "5pt" not in blob(res)


def test_slot_bsbs_nondimen_stays_text() -> None:
    r"""保守面：``\\[x]`` 非维度 ``[opt]`` 不罩——原样留文本面（不扩大打击面）。"""
    res = scan("Line one \\\\[x] line two words here enough.")
    assert "\\\\[x]" in blob(res)
    assert not res.ph_map


def test_slot_vspace_brace_arg() -> None:
    r"""``\vspace{30pt}``：BOUNDARY_TAIL ``s m`` 组参 → 整调用 LITERAL。"""
    res = scan("Para text here enough words.\\vspace{30pt} Tail words here.")
    assert any(
        p.kind is PieceKind.LITERAL and p.text == "\\vspace{30pt}" for p in res.pieces
    )
    assert "30pt" not in blob(res)


def test_slot_dimen_assign_eq() -> None:
    r"""``\hangindent=.5em``：``=<atom>`` 赋值尾 → ``[[CMD]]`` 罩含等号整段。"""
    res = scan("Para text here enough words.\\hangindent=.5em Tail words.")
    assert res.ph_map["[[CMD_1]]"] == "\\hangindent=.5em"
    assert ".5em" not in blob(res)


def test_slot_kern_bare() -> None:
    r"""``\kern2em``：刚性 dimen 名裸操作数 → ``[[CMD]]``。"""
    res = scan("Para text here enough words.\\kern2em Tail words here more.")
    assert res.ph_map["[[CMD_1]]"] == "\\kern2em"
    assert "2em" not in blob(res)


def test_slot_dimen_cs_operand() -> None:
    r"""``\hskip \labelsep``：寄存器 cs 作操作数 → 尾扫覆盖整段 LITERAL。"""
    res = scan("Para text here enough words.\\hskip \\labelsep Tail words.")
    assert any(
        p.kind is PieceKind.LITERAL and p.text == "\\hskip \\labelsep"
        for p in res.pieces
    )
    assert "\\labelsep" not in blob(res)


def test_slot_rule_keywords() -> None:
    r"""``\vrule width 2pt``：``width|height|depth`` 序 → ``[[CMD]]`` 罩关键字+量。"""
    res = scan("Para text here enough words.\\vrule width 2pt Tail words.")
    assert res.ph_map["[[CMD_1]]"] == "\\vrule width 2pt"
    assert "width" not in blob(res)


def test_slot_font_decl() -> None:
    r"""``\font\myfont=cmr10 at 12pt``：字体声明 ``\cs=name at <dimen>`` 整罩。"""
    res = scan("Para text here enough words.\\font\\myfont=cmr10 at 12pt Tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\font\\myfont=cmr10 at 12pt"
    assert "cmr10" not in blob(res)


def test_slot_assign_generic() -> None:
    r"""表外未知名 ``\foo=2pt``：通用 ``=<atom>`` 尾扫兜底 → ``[[CMD]]``。"""
    res = scan("Para text here enough words.\\foo=2pt Tail words here.")
    assert res.ph_map["[[CMD_1]]"] == "\\foo=2pt"
    assert "2pt" not in blob(res)


def test_slot_dimen_in_arg() -> None:
    r"""in_arg 同式：``\section{A \vskip3pt B}`` 内维度尾也罩 ``[[CMD]]``。"""
    res = scan("\\section{A \\vskip3pt B tail words here}")
    [c] = res.chunks
    assert c.content == "A [[CMD_1]] B tail words here"
    assert res.ph_map["[[CMD_1]]"] == "\\vskip3pt"


# ------------------------------------------------------------- 类2 cs+latin 黏连（bug-B）


def test_bugb_item_no_leading_space() -> None:
    r"""``\item FSU``：cs 吞掉的空格剖成字面 piece，chunk 无前导空——
    下游 ``.strip()`` 不再产 ``\itemFSU``。"""
    res = scan("Text \\begin{itemize}\\item FSU words here enough text.\\end{itemize}")
    [c] = res.chunks
    assert c.context == "item"
    assert c.content == "FSU words here enough text."


def test_bugb_par_comment_gap() -> None:
    r"""``\par%note\ni)``：注释+换行的间隙同样剖出——后段 chunk 即 ``i)``。"""
    res = scan("First para words here.\\par%note\ni) second item words here.")
    assert [c.content for c in res.chunks] == [
        "First para words here.",
        "i) second item words here.",
    ]


# ------------------------------------------------------------- 类3 名字槽位


def test_slot_textcolor_head() -> None:
    r"""``\textcolor{red}{text}``：``[o]{m}`` 头参进 ``[[CMD]]``，``{text}`` 留主流。"""
    res = scan("Para \\textcolor{red}{warning words here} tail more words.")
    [c] = res.chunks
    assert c.content == "Para [[CMD_1]]{warning words here} tail more words."
    assert res.ph_map["[[CMD_1]]"] == "\\textcolor{red}"
    assert "red" not in blob(res).replace("warning", "")


def test_slot_colorbox_head() -> None:
    r"""``\colorbox{blue}{text}`` 同式：颜色名保护、文本参数可译。"""
    res = scan("Para \\colorbox{blue}{warning words here} tail more words.")
    [c] = res.chunks
    assert c.content == "Para [[CMD_1]]{warning words here} tail more words."
    assert res.ph_map["[[CMD_1]]"] == "\\colorbox{blue}"


def test_slot_color_probe() -> None:
    r"""``\color{red}``：探针路（无族表登记）``{red}`` 随 ``[[CMD]]`` 罩住。"""
    res = scan("Para \\color{red} warning words here tail more words now.")
    assert res.ph_map["[[CMD_1]]"] == "\\color{red}"
    assert "red" not in blob(res)


def test_slot_counter_probe() -> None:
    r"""``\arabic{section}``：计数器名 ``{section}`` 进 ``[[CMD]]`` 不译。"""
    res = scan("Para \\arabic{section} warning words here tail more words.")
    assert res.ph_map["[[CMD_1]]"] == "\\arabic{section}"
    assert "section}" not in blob(res)


# ------------------------------------------------------------- 类5 env preamble


def test_slot_deluxetable_preamble() -> None:
    r"""``\begin{deluxetable}{lRLc}``：argspec env ``m o`` + ``body_role=protect``
    → 整段 ``[[ENV]]``，列规不进 surface；``\tablecaption`` 内挖照常。"""
    res = scan(
        "\\begin{deluxetable}{lRLc}\\tablecaption{Cap words here}"
        "a&b\\end{deluxetable}\nTail words here enough."
    )
    [env] = [v for k, v in res.ph_map.items() if k.startswith("[[ENV_")]
    assert env.startswith("\\begin{deluxetable}{lRLc}")
    assert env.endswith("\\end{deluxetable}")
    assert "\\tablecaption{[[CHUNK_" in env
    [cap] = [c for c in res.chunks if c.context == "tablecaption"]
    assert cap.content == "Cap words here"
    assert "lRLc" not in blob(res)


def test_slot_supertabular_preamble() -> None:
    r"""``\begin{supertabular}{cc}``：``o m`` 签名 ``{cc}`` 罩进 ``[[ENV]]``。"""
    res = scan("\\begin{supertabular}{cc}a&b\\end{supertabular}\nTail words here ok.")
    assert res.ph_map["[[ENV_1]]"] == (
        "\\begin{supertabular}{cc}a&b\\end{supertabular}"
    )
    assert "cc}" not in blob(res)


def test_slot_translatedabstract_lang_arg() -> None:
    r"""``\begin{translatedabstract}{french}``：argspec env ``m`` + ``key``
    角色 → ``{french}`` 随 begin 行字面件，体散文照常成 chunk——
    2401.14887 babel 语言选择子实证（``{这是译文}`` 机位泄漏）。"""
    res = scan(
        "\\begin{translatedabstract}{french}Body words here enough text."
        "\\end{translatedabstract}\nTail words here."
    )
    assert any(
        p.kind is PieceKind.LITERAL and "\\begin{translatedabstract}{french}" in p.text
        for p in res.pieces
    )
    assert "french" not in blob(res)


def test_slot_mizar_verbatim_env() -> None:
    r"""``\begin{Mizar}{x,Y,A}``：``\lstnewenvironment`` 不走 doc 注册 →
    argspec env ``m`` + ``body_role=verbatim`` 兜底，整段 ``[[VERB]]``，
    关键词表参不进 surface——2410.00065 实证泄漏。"""
    res = scan("\\begin{Mizar}{x,Y,A}let x be set;\\end{Mizar}\nTail words here.")
    assert res.ph_map["[[VERB_1]]"] == (
        "\\begin{Mizar}{x,Y,A}let x be set;\\end{Mizar}"
    )
    assert "x,Y,A" not in blob(res)


# ------------------------------------------------------------- 展开组内镜像
# ``_group_surface`` 对 ``_dispatch`` 的同构复刻：展开体里的同一批形态
# 也必须出占位——组内没有 LITERAL piece，一切走 ph。


def test_grp_dimen_bare_operand() -> None:
    r"""组内 ``\vskip3pt`` → ``[[CMD]]``（主流是 LITERAL piece，组内对应 ph）。"""
    res = scan("\\newcommand{\\vv}{pre \\vskip3pt post words here}\nText \\vv tail.")
    [c] = res.chunks
    assert c.content == " Text pre [[CMD_1]] post words here tail. "
    assert res.ph_map["[[CMD_1]]"] == "\\vskip3pt"


def test_grp_bsbs_dimen_opt() -> None:
    r"""组内 ``\\[5pt]`` → ``[[CMD]]`` 罩维度 ``[opt]``。"""
    res = scan("\\newcommand{\\vv}{pre \\\\[5pt] post words here}\nText \\vv tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\\\[5pt]"


def test_grp_textcolor_head() -> None:
    r"""组内 ``\textcolor{red}{warn}``：头参罩 ``[[CMD]]``，``{warn}`` 留 surface。"""
    res = scan(
        "\\newcommand{\\vv}{pre \\textcolor{red}{warn words} post}\nText \\vv tail."
    )
    [c] = res.chunks
    assert c.content == " Text pre [[CMD_1]]{warn words} post tail. "
    assert res.ph_map["[[CMD_1]]"] == "\\textcolor{red}"


def test_grp_color_probe() -> None:
    r"""组内 ``\color{red}`` 探针 → ``[[CMD]]`` 罩 ``{red}``。"""
    res = scan("\\newcommand{\\vv}{pre \\color{red} post words here}\nText \\vv tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\color{red}"


def test_grp_counter_probe() -> None:
    r"""组内 ``\arabic{section}`` → ``[[CMD]]`` 罩计数器名。"""
    res = scan(
        "\\newcommand{\\vv}{pre \\arabic{section} post words here}\nText \\vv tail."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\arabic{section}"


def test_grp_env_macro_args_eaten() -> None:
    r"""``\bea{c} x \eea``（env-macro 展开）：``{c}`` 列规随 ``[[MATH]]`` 罩住——
    hep-ph--0605151 实形，组内 begin 行参数不泄 surface。"""
    res = scan(
        "\\newcommand{\\bea}{\\begin{array}}\\newcommand{\\eea}{\\end{array}}\n"
        "\\bea{c} x \\eea Tail words here enough."
    )
    assert res.ph_map["[[MATH_1]]"] == "\\bea{c} x \\eea"


def test_grp_env_begin_opt_eaten() -> None:
    r"""组内 ``\begin{itemize}[noitemsep]``：``[opt]`` 版式参随 ``[[ENVTAG]]``
    罩住（``env_opt_is_format`` 门），不裸进 surface。"""
    res = scan(
        "\\newcommand{\\vv}{pre \\begin{itemize}[noitemsep]\\item x post\\end{itemize}}\n"
        "Text \\vv tail words."
    )
    assert res.ph_map["[[ENVTAG_1]]"] == "\\begin{itemize}[noitemsep]"
    assert "noitemsep" not in blob(res)


def test_grp_item_label_flows() -> None:
    r"""组内 ``\item[lab text]``：label 是可译文本，留 surface 不随 ``[[CMD]]``——
    spec=None 的 BOUNDARY 行漂移修复（此前 label 被误吃）。"""
    res = scan(
        "\\newcommand{\\vv}{\\begin{itemize}\\item[lab text] x post\\end{itemize}}\n"
        "Text \\vv tail words here."
    )
    [c] = res.chunks
    assert "[[CMD_2]][lab text] x post" in c.content
    assert res.ph_map["[[CMD_2]]"] == "\\item"


# ------------------------------------------------------------- argspec 登记闸
# 主流 ``_handle_unknown_cs`` 约定：宏表登记名（``m is not None``）不吃
# argspec——签名表只对未登记未知名生效（``argspec_lookup`` docstring 明记
# "调用方先短路"）。组内 argspec 行与 ``_pend_spec_of`` 待绑槽形行同规。


def test_grp_argspec_reg_gate() -> None:
    r"""组内登记名不吃 argspec：``\And``（math-literal ``literal`` 策）被
    ``\renewcommand`` 登记成 opaque 宏后不再按签名逐字渲 surface——
    ``\And{aa}`` 整调用 ``[[CMD]]``（登记名落探针与主流 ``m is not None``
    同规）；无闸则命令名+参组裸进 chunk 被译。"""
    res = scan(
        "\\renewcommand{\\And}[1]{\\textbf{#1}}\n"
        "\\newcommand{\\vv}{pre \\And{aa} post words here}\n"
        "Text \\vv tail words here enough."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\And{aa}"
    assert "\\And" not in blob(res)
    assert "aa" not in blob(res)


def test_grp_argspec_unregistered_unchanged() -> None:
    r"""保守面：未登记 ``\Alph``（latex2e ``key``/``m`` 签名）组内仍走
    argspec——``{aa1}`` 随 ``[[CMD]]``、``{bb2}`` 留 surface（闸只挡
    登记名，不扩大打击面）。"""
    res = scan(
        "\\newcommand{\\vv}{pre \\Alph{aa1}{bb2} post words here}\n"
        "Text \\vv tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\Alph{aa1}"
    assert "{bb2}" in blob(res)


def test_pend_spec_reg_gate() -> None:
    r"""组尾待绑判同闸：``\Alph`` 被 ``\renewcommand`` 登记成 opaque 宏后
    不再按签名 ``m`` 只吸首组——``m is not None`` → spec ``m m`` 走参
    吸 ``{aa1}{bb2}`` 进组尾罩面，``[[EXPAND]]`` 体覆盖
    ``\\vv{aa1}{bb2}`` 整调用点（无闸按签名 ``m`` 时 ``{bb2}`` 漏出
    组界裸进 chunk）。"""
    res = scan(
        "\\renewcommand{\\Alph}[2]{\\textbf{#1#2}}\n"
        "\\newcommand{\\vv}{pre \\Alph}\n"
        "Text \\vv{aa1}{bb2} tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\Alph{aa1}{bb2}"
    assert res.ph_map["[[EXPAND_2]]"] == "\\vv{aa1}{bb2}"
    assert "bb2" not in blob(res)


# ------------------------------------------------------------- 类6 混排数学闭符


def test_math_mixed_paren_closer() -> None:
    r"""``$\alpha(x)\), for all $p \in S$``（0806.1984 实形）：``\)`` 收闭
    第一个数学段，``, for all ``/`` and `` 回散文、后两 ``$..$`` 各成 ph——
    不收则 ``for all`` 落数学、``\p`` 裸进散文被译。"""
    res = scan("\\item $\\alpha(x)\\), for all $p \\in S$ and $g_1\\in G$ words.")
    assert res.ph_map["[[MATH_1]]"] == "$\\alpha(x)\\)"
    assert res.ph_map["[[MATH_2]]"] == "$p \\in S$"
    assert res.ph_map["[[MATH_3]]"] == "$g_1\\in G$"
    assert [c.content for c in res.chunks] == [
        "[[MATH_1]], for all [[MATH_2]] and [[MATH_3]] words."
    ]


def test_math_mixed_bracket_closer_display() -> None:
    r"""``$$x\]``：display 体内 ``\]`` 同收闭符（LaTeX 语义 ``\]`` 在数学
    态即 ``$$``），尾部散文不回吞。"""
    res = scan("Para $$x\\] tail words here enough more.")
    assert res.ph_map["[[MATH_1]]"] == "$$x\\]"
    assert "tail words" in blob(res)


def test_math_paren_text_arg_not_closed() -> None:
    r"""``\( .. \text{..)..} .. \)``：``\text`` 正文参体内 ``\)`` 不关外层
    数学——``_find_math_close_tok`` 同走 ``_math_skip_textarg`` 跳扫
    （wave-2 残余洞：不收则内层 ``\)`` 截断、后半落散文被译）。"""
    res = scan("Para \\(a + \\text{ if ) b } + c\\) tail words here.")
    assert res.ph_map["[[MATH_1]]"] == "\\(a + \\text{ if ) b } + c\\)"
    assert "tail words" in blob(res)


# ------------------------------------------------------------- 类7 accent 参


def test_accent_braced_arg() -> None:
    r"""``\c{c}``（0806.3144 实形）：整调用 ``[[CMD]]``——参字母 ``c`` 不进
    chunk 被译（cedilla+CJK 无预组字槽）。"""
    res = scan("Le\\c{c}ons sur la th\\'eorie tail words here.")
    assert res.ph_map["[[CMD_1]]"] == "\\c{c}"
    assert res.ph_map["[[CMD_2]]"] == "\\'e"
    assert "Le[[CMD_1]]ons" in blob(res)


def test_accent_bare_letter_arg() -> None:
    r"""``\~n``/``\c\i`` 单 token 参同罩——花括号缺席不构成逃生口。"""
    res = scan("Espa\\~na and \\c\\i words here enough.")
    assert res.ph_map["[[CMD_1]]"] == "\\~n"
    assert res.ph_map["[[CMD_2]]"] == "\\c\\i"


def test_accent_family_chars() -> None:
    r"""族面抽查：``\v``/``\H``/``\r``/``\d``/``\b``/``\k``/``\t``/``\=``/``\.``
    参均保护（``\r`` 本轮补入 ``ACCENT_CHARS``）。"""
    res = scan("N\\v{e}mec \\H{o} Dvo\\r{r}\\'ak \\d{o} \\k{a} x\\=y \\.z tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\v{e}"
    assert res.ph_map["[[CMD_2]]"] == "\\H{o}"
    assert res.ph_map["[[CMD_3]]"] == "\\r{r}"
    assert res.ph_map["[[CMD_5]]"] == "\\d{o}"
    assert res.ph_map["[[CMD_6]]"] == "\\k{a}"
    assert res.ph_map["[[CMD_7]]"] == "\\=y"
    assert res.ph_map["[[CMD_8]]"] == "\\.z"


def test_accent_no_arg_stays_literal() -> None:
    r"""保守面：``\c`` 后随组闭（无参）→ 裸名内联字面，组结构不扰。"""
    res = scan("Text {\\it a\\c} tail words here enough more.")
    assert "{\\it a\\c}" in blob(res)
    assert not res.ph_map


def test_grp_accent_bare_arg() -> None:
    r"""组内 ``\~n`` 裸参形 → ``[[CMD]]``（``\c{c}`` 花括号形本由探针罩，
    裸参是组内镜像补齐的洞）。"""
    res = scan("\\newcommand{\\vv}{pre \\~n post words here}\nText \\vv tail.")
    assert res.ph_map["[[CMD_1]]"] == "\\~n"
    [c] = res.chunks
    assert "[[CMD_1]]" in c.content


# ------------------------------------------------------------- opaque 宏镜像
# 主流 row18 ``_handle_opaque_macro`` 的组内对价：宏表 ``opaque``/``math``
# 登记名按自身 ``spec`` 位序走参整调用罩 ``[[CMD]]``——探针 ``[o]+{m}×6``
# 形曾把 spec 外 ``{..}`` 组误吸进保护面（登记宏 nargs 越界过吸，组内
# surface 与主流 ``_args_tok`` 位序分叉）。``{``/``[``-open 组参过散文门
# 抠出子扫渲 surface；体尾 key-arg cs 调用点 ``{key}`` 同罩。


def test_grp_opaque_macro_spec_arity() -> None:
    r"""``\def\foo#1{\textbf{#1}}``（opaque ``m``）：``\foo{aa}{bb}`` 只罩
    首参——``{bb}`` 非参组留 surface 可译（探针曾按 ``{m}×6`` 双吸蒸发）。"""
    res = scan(
        "\\def\\foo#1{\\textbf{#1}}\n"
        "\\newcommand{\\vv}{pre \\foo{aa}{bb} post words here}\n"
        "Text \\vv tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo{aa}"
    assert "{bb}" in blob(res)


def test_grp_opaque_macro_opt_mand() -> None:
    r"""``o m`` 签名 opaque 宏：``[ww]{aa}`` 全随 ``[[CMD]]`` 罩住。"""
    res = scan(
        "\\newcommand{\\bar}[2][zz]{\\textbf{#1#2}}\n"
        "\\newcommand{\\vv}{pre \\bar[ww]{aa} post words here}\n"
        "Text \\vv tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\bar[ww]{aa}"


def test_grp_opaque_macro_no_arg() -> None:
    r"""零参 opaque 宏：``\foo`` 本体 ``[[CMD]]``——后随 ``{bb}`` 非参
    不吸（探针会把 ``{bb}`` 当 ``{m}`` 吞掉蒸发）。"""
    res = scan(
        "\\def\\foo{\\textbf{}}\n"
        "\\newcommand{\\vv}{pre \\foo{bb} post words here}\n"
        "Text \\vv tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo"
    assert "{bb}" in blob(res)


def test_grp_opaque_macro_prose_arg() -> None:
    r"""opaque 宏散文参挖掘：``{长散文}`` 参抠出 ``[[CMD]]`` 覆盖、子扫
    渲 surface——主流 ``_handle_opaque_macro`` 散文面同型。"""
    res = scan(
        "\\def\\foo#1{\\textbf{#1}}\n"
        "\\newcommand{\\vv}{pre \\foo{some long english prose argument} post}\n"
        "Text \\vv tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo{"
    assert "some long english prose argument" in blob(res)


def test_grp_opaque_macro_keyarg_tail() -> None:
    r"""opaque 宏体尾 key-arg：``\def\foo{\relax\ref}`` 调用点 ``{k1}``
    随 ``[[CMD]]`` 罩住不译（主流 ``_handle_opaque_macro`` keyarg 吸参同位）。"""
    res = scan(
        "\\def\\foo{\\relax\\ref}\n"
        "\\newcommand{\\vv}{pre \\foo{k1} post words here}\n"
        "Text \\vv tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo{k1}"
    assert "k1" not in blob(res)


def test_grp_opaque_math_kind() -> None:
    r"""``math`` 族宏同行兜住：``\def\foo#1{\alpha#1}`` 体含 ``\alpha``
    → ``math`` 档——``\foo{x}{bb}`` 同样只罩首参。"""
    res = scan(
        "\\def\\foo#1{\\alpha#1}\n"
        "\\newcommand{\\vv}{pre \\foo{x}{bb} post words here}\n"
        "Text \\vv tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo{x}"
    assert "{bb}" in blob(res)


# ------------------------------------------------------------- 组尾待绑 spec 臂
# ``_pend_spec_of`` opaque/math 行 + ``_grp_spec_walk`` 余量：登记宏参扫
# 吃到组末未竟 → ``_absorb_spec`` 按真实 ``m.spec`` 从流续吸——探针
# ``o m×6`` 槽形曾把 spec 外 ``{..}`` 误吸进组尾（登记宏 nargs 越界过吸，
# 组内 surface 臂与跨界待绑臂分叉）。未登记名保探针回落。


def test_pend_opaque_spec_arity() -> None:
    r"""组尾待绑 opaque 宏按 spec 吸参：``\foo{aa}{bb}``（spec ``m``）只吸
    ``{aa}``——``{bb}`` 留主流可译（探针 ``o m×6`` 曾双吸蒸发）。"""
    res = scan(
        "\\def\\foo#1{\\textbf{#1}}\n"
        "\\newcommand{\\vv}{pre \\foo}\n"
        "Text \\vv{aa}{bb} tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo{aa}"
    assert "{bb}" in blob(res)


def test_pend_opaque_opt_mand() -> None:
    r"""``o m`` 签名组尾待绑：``[ww]{aa}`` 全随 ``[[CMD]]``/``[[EXPAND]]`` 罩住。"""
    res = scan(
        "\\newcommand{\\bar}[2][zz]{\\textbf{#1#2}}\n"
        "\\newcommand{\\vv}{pre \\bar}\n"
        "Text \\vv[ww]{aa} tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\bar[ww]{aa}"
    assert res.ph_map["[[EXPAND_2]]"] == "\\vv[ww]{aa}"


def test_pend_opaque_no_arg() -> None:
    r"""零参 opaque 宏组尾不待绑：``\foo`` 调用即完结——后随 ``{bb}``
    非参不吸（探针曾当 ``{m}`` 吞掉蒸发）。"""
    res = scan(
        "\\def\\foo{\\textbf{}}\n"
        "\\newcommand{\\vv}{pre \\foo}\n"
        "Text \\vv{bb} tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo"
    assert "{bb}" in blob(res)


def test_pend_opaque_keyarg_tail() -> None:
    r"""opaque 宏体尾 key-arg 跨界：``\def\foo{\relax\ref}`` 调用点
    ``{k1}`` 经 keyarg 槽列续吸罩住（spec 尽余量仍带 ``ka_slots``）。"""
    res = scan(
        "\\def\\foo{\\relax\\ref}\n"
        "\\newcommand{\\vv}{pre \\foo}\n"
        "Text \\vv{k1} tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo{k1}"
    assert "k1" not in blob(res)


def test_pend_opaque_math_kind() -> None:
    r"""``math`` 族宏同行兜住：``\def\foo#1{\alpha#1}`` 组尾待绑同样
    只吸 spec 首参。"""
    res = scan(
        "\\def\\foo#1{\\alpha#1}\n"
        "\\newcommand{\\vv}{pre \\foo}\n"
        "Text \\vv{x}{bb} tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo{x}"
    assert "{bb}" in blob(res)


def test_pend_opaque_single_token_arg() -> None:
    r"""spec ``m`` 单 token 参跨界：``\foo a`` 的 ``a`` 吸入罩面——槽字母
    ``m`` 只认 ``{..}``，真实 spec 的 fidelity 位。"""
    res = scan(
        "\\def\\foo#1{\\textbf{#1}}\n"
        "\\newcommand{\\vv}{pre \\foo}\n"
        "Text \\vv a tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo a"


def test_pend_opaque_open_bracket_cont() -> None:
    r"""``[..]`` 组跨界续收：``\vv`` 体 ``pre \foo[ww``（``[`` 在 def 体内
    不需配平）→ spec ``m`` 参续拉 ``]`` 落位，``{aa}`` 非参留主流。"""
    res = scan(
        "\\def\\foo#1{\\textbf{#1}}\n"
        "\\newcommand{\\vv}{pre \\foo[ww}\n"
        "Text \\vv]{aa} tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo[ww]"
    assert "{aa}" in blob(res)


def test_pend_opaque_keyarg_bracket_cont() -> None:
    r"""key-arg ``o`` 槽 ``[`` 组跨界续收：``[opt`` 越组末 → ``]`` 落位后
    余槽续走 ``{k1}``——``ka_cont``/``ka_slots`` 双余量同吸。"""
    res = scan(
        "\\def\\foo{\\relax\\ref}\n"
        "\\newcommand{\\vv}{pre \\foo[opt}\n"
        "Text \\vv]{k1} tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo[opt]{k1}"
    assert "k1" not in blob(res)


def test_pend_opaque_delim_arg() -> None:
    r"""``delim`` 定界参跨界：``\def\foo#1.``——``{aa}`` 组整收后 ``.``
    定界命中，``{bb}`` 非参留主流（槽字母无 delim 对应物）。"""
    res = scan(
        "\\def\\foo#1.{\\textbf{#1}}\n"
        "\\newcommand{\\vv}{pre \\foo}\n"
        "Text \\vv{aa}.{bb} tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo{aa}."
    assert "{bb}" in blob(res)


def test_pend_opaque_e_arg_tail() -> None:
    r"""``e`` 修饰参尾位续决：体尾 ``^`` 已吃、``{arg}`` 跨界待绑——
    ``cont=("e-arg",)`` 续收 ``{x}`` 后续吃 ``_2``（``e{^_}`` 符残件同臂）。"""
    res = scan(
        "\\NewDocumentCommand{\\foo}{e{^_}}{\\textbf{#1}}\n"
        "\\newcommand{\\vv}{pre \\foo^}\n"
        "Text \\vv{x}_2 tail words here."
    )
    assert res.ph_map["[[CMD_1]]"] == "\\foo^{x}_2"


def test_pend_opaque_unregistered_probe() -> None:
    r"""保守面：未登记 ``\foo`` 仍走探针回落——``{aa}{bb}`` 双吸罩住
    （real-spec 行只兜 ``opaque``/``math`` 登记名，不扩大打击面）。"""
    res = scan("\\newcommand{\\vv}{pre \\foo}\nText \\vv{aa}{bb} tail words here.")
    assert res.ph_map["[[CMD_1]]"] == "\\foo{aa}{bb}"
    assert "bb" not in blob(res)
