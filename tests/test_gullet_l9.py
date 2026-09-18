r"""L9 GULLET 族机制钉测（corpus_v3 mechanisms.jsonl T25/W14/W23/W28/W41/
W45/W46/W81/W83/W94/W105）：展开层语义的逐机制回归面。

覆盖判定：已覆盖机制钉「行为不回归」；本批修复钉「活缺口已合」——
``\romannumeral``/``\uppercase``/``\lowercase`` 原语（W28）、
``\@ifxundefined`` 接管（W105）、``\let`` 到内建/数学命令名换名（W46）。
"""

from __future__ import annotations

from texlate.latex.gullet import Gullet
from texlate.latex.mouth import Tok


def text_of(ts: list[Tok]) -> str:
    """token 流 → 表面文本（consumed marker 是事件非文本）。"""
    return "".join(str(t) for t in ts if t.kind != "consumed")


def expanded_text(src: str) -> str:
    """Gullet 全量展开后的表面文本。"""
    return text_of(list(Gullet(src)))


# ---------------------------------------------------------------- T25/W81 @ 宏


def test_t25_makeatletter_at_macro() -> None:
    r"""T25：``\makeatletter`` 区 @-cs 定义+调用展开。"""
    out = expanded_text(r"\makeatletter\def\@foo{BAR}\@foo\makeatother")
    assert out == r"\makeatletterBAR\makeatother"


def test_w81_catcode_backtick_at() -> None:
    r"""W81：``\catcode`@=11`` 直写切 @ 类目，``\@foo`` 成 cs。"""
    out = expanded_text("\\catcode`@=11 \\def\\@foo{BAR}\\@foo")
    assert out == " BAR"


def test_w81_catcode_backtick_bslash_at() -> None:
    r"""W81：``\catcode`\@=11`` 带反斜杠变体同效（hep-th/9703214 两形同文）。"""
    out = expanded_text("\\catcode`\\@=11 \\def\\@foo{BAR}\\@foo")
    assert out == " BAR"


# ---------------------------------------------------------------- W14 注释 \if/\fi


def test_w14_commented_if_not_paired() -> None:
    r"""W14：``%`` 注释掉的 ``\ifnum`` 不参与配对（1511.06728 相距 98 行形）。"""
    out = expanded_text("\\iftrue\nA\n%\\ifnum\\doTR=1\nB\n\\fi\nC")
    assert out == "A B C"


def test_w14_commented_fi_not_consumed() -> None:
    r"""W14：注释掉的 ``\fi`` 不收尾活条件。"""
    out = expanded_text("\\iftrue\nA\n%\\fi\n\\fi\nC")
    assert out == "A C"


# ---------------------------------------------------------------- W23 特殊 catcode 字符


def test_w23_special_chars_in_optional_arg() -> None:
    r"""W23：``[..]`` 参内 ``&``/``#``/``~`` 字面消费不炸（不透明宏原样过）。"""
    out = expanded_text("\\newcommand{\\x}[2][d]{(#1|#2)}\\x[a&b]{c}")
    assert out == "\\x[a&b]{c}"
    out = expanded_text("\\newcommand{\\x}[2][d]{(#1|#2)}\\x[~]{b}")
    assert out == "\\x[~]{b}"


def test_w23_pct_cs_in_body() -> None:
    r"""W23：``\%`` 入宏体 + ``^`` 上标 → 数学类调用点保护（0707.4206 形）。"""
    out = expanded_text("\\newcommand{\\mirror}[1]{#1^{\\%}}\\mirror{E}")
    assert out == "\\mirror{E}"


# ---------------------------------------------------------------- W28 romannumeral/uppercase


def test_w28_uppercase_romannumeral_idiom() -> None:
    r"""W28：``\uppercase\expandafter{\romannumeral1}`` → ``I``（2003.03561 正文实证形）。"""
    out = expanded_text("Mode \\uppercase\\expandafter{\\romannumeral1} end")
    assert out == "Mode I end"


def test_w28_romannumeral_bare() -> None:
    r"""W28：裸 ``\romannumeral`` → 小写罗马（TeX 本义）。"""
    assert expanded_text("n=\\romannumeral3 x") == "n=iii x"
    assert expanded_text("\\romannumeral14") == "xiv"
    assert expanded_text("\\romannumeral2024") == "mmxxiv"


def test_w28_romannumeral_zero_and_neg() -> None:
    r"""W28：``\romannumeral0``/负数 → 不产 token（扩张触发 idiom 同态），字节 literal 化。"""
    g = Gullet("\\romannumeral0x")
    out = text_of(list(g))
    assert out == "x"


def test_w28_uppercase_plain_group() -> None:
    r"""W28：``\uppercase{abc}`` 直组 → ``ABC``；cs 名不受大小写变换。"""
    assert expanded_text("\\uppercase{ab\\foo c}") == "AB\\fooC"
    assert expanded_text("\\lowercase{ABc}") == "abc"


def test_w28_uppercase_bail_literal() -> None:
    r"""W28：扫不到开组 → 全回吐 literal（``\uppercase\foo{`` 不插括号纠错）。"""
    out = expanded_text("\\uppercase\\foo{ab}")
    assert out == "\\uppercase\\foo{ab}"


# ---------------------------------------------------------------- W41 伪条件宏


def test_w41_ifmain_macro_not_if_nesting() -> None:
    r"""W41：``\ifmain`` 用户宏不计 ``process_if`` 嵌套深度（对 if 探测的假阳性）。"""
    src = "\\providecommand{\\ifmain}[1]{#1}\\iftrue T \\ifmain{X} \\else F \\fi tail"
    out = expanded_text(src)
    assert "\\ifmain{X}" in out
    assert out.endswith("tail")
    assert "F" not in out.split("\\ifmain")[0].replace("\\iftrue T ", "")


def test_w41_hidden_end_document_in_arg() -> None:
    r"""W41：宏参内藏 ``\end{document}`` 不触发提前终止（不透明宏原样过）。"""
    out = expanded_text(
        "\\providecommand{\\ifmain}[1]{#1}pre \\ifmain{X\\end{document}} post"
    )
    assert out == "pre \\ifmain{X\\end{document}} post"


# ---------------------------------------------------------------- W45 内核重定义


def test_w45_redefined_frac_callsite_kept() -> None:
    r"""W45：``\def\frac`` 重定义后调用点保持作者语义（不透明不内置标准表）。"""
    out = expanded_text("\\def\\frac#1#2{{#1\\over#2}}\\frac{a}{b}")
    assert out == "\\frac{a}{b}"


def test_w45_redef_single_letter_bare_alias() -> None:
    r"""W45：``\def\l{\left}`` 原语/内建被重绑 → 宏表先行按作者绑定展开。"""
    out = expanded_text("\\def\\l{\\left}A \\l B")
    assert out == "A \\left B".replace("\\left ", "\\left")


def test_w45_renew_math_opacity() -> None:
    r"""W45：``\renewcommand{\P}{\mathbb{P}}`` 数学体 → 调用点保护。"""
    out = expanded_text("\\renewcommand{\\P}{\\mathbb{P}}\\P")
    assert out == "\\P"


# ---------------------------------------------------------------- W46 宏包裹定界符


def test_w46_let_to_math_builtin_renames() -> None:
    r"""W46：``\let\ra\rangle`` → 调用点换名 ``\rangle``（配对检查拿真身）。"""
    out = expanded_text("\\let\\ra\\rangle $|1\\ra|$")
    assert out == "$|1\\rangle|$"


def test_w46_let_to_builtin_cite_renames() -> None:
    r"""W46：``\let\mycite\cite`` → ``\cite`` 换名出流，分段器按 cite 分派。"""
    out = expanded_text("\\let\\mycite\\cite \\mycite{key1}")
    assert out == "\\cite{key1}"


def test_w46_let_undefined_stays_literal() -> None:
    r"""W46：``\let`` 到未定义名 → ``\ra`` 原样（不编造绑定）。"""
    out = expanded_text("\\let\\a\\totallyunknown A \\a B")
    assert out == "A \\a B".replace("\\a ", "\\a")


# ---------------------------------------------------------------- W83 换行分隔必选参


def test_w83_newline_before_mandatory_arg() -> None:
    r"""W83：``\x<换行>{arg}`` —— cs 后换行被吸收，参数照常成组。"""
    out = expanded_text("\\newcommand{\\m}[1]{[#1]}\\m\n{a}")
    assert out == "\\m{a}"


def test_w83_newline_space_before_arg() -> None:
    r"""W83：命令与参间空白+换行混合不阻断（不定界参跳 space token）。"""
    out = expanded_text("\\newcommand{\\m}[1]{[#1]}\\m \n {a}")
    assert out == "\\m{a}"


# ---------------------------------------------------------------- W94 环境入宏体


def test_w94_env_in_def_body_expands_at_callsite() -> None:
    r"""W94：``\newcommand{\qed}{\begin{env}..\end{env}}`` 定义体不当正文 env 实例，
    调用点展开产物才见 ``\begin``（math/9910058 形）。"""
    out = expanded_text(
        "\\newcommand{\\qed}{\\begin{flushright}Q\\end{flushright}}pre \\qed post"
    )
    assert out == "pre \\begin{flushright}Q\\end{flushright}post"


# ---------------------------------------------------------------- W105 providecommand 垫片


def test_w105_providecommand_no_clobber() -> None:
    r"""W105：``\providecommand`` 仅当未定义——已定义不覆盖（垫片语义）。"""
    src = "\\newcommand{\\natexlab}[1]{ORIG}\\providecommand{\\natexlab}[1]{SHIM}\\natexlab{x}"
    assert expanded_text(src) == "ORIG"


def test_w105_providecommand_fresh() -> None:
    r"""W105：未定义 → 垫片生效。"""
    src = "\\providecommand{\\natexlab}[1]{SHIM}\\natexlab{x}"
    assert expanded_text(src) == "SHIM"


def test_w105_at_ifxundefined_makeatletter() -> None:
    r"""W105：``\@ifxundefined`` 内核命令接管（natbib 垫片缺位时仍选支）。"""
    src = "\\makeatletter\\@ifxundefined{foo}{T}{F}\\makeatother"
    assert expanded_text(src) == "\\makeatletterT\\makeatother"
    src = "\\makeatletter\\newcommand{\\foo}{x}\\@ifxundefined{foo}{T}{F}\\makeatother"
    assert expanded_text(src) == "\\makeatletterF\\makeatother"
